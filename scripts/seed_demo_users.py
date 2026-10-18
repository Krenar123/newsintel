#!/usr/bin/env python3
"""Seed demo users for role/persona dashboard testing."""

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    Client,
    ClientType,
    ClientWatchlistItem,
    SubscriptionPlan,
    User,
    UserRole,
    WatchlistItemType,
    create_all_tables,
    get_engine,
    get_session_factory,
)


DEMO_PASSWORD = "Demo123!"


DEMO_CLIENT_USERS = [
    {
        "email": "party@newsintel.local",
        "name": "Party War Room Demo",
        "client_email": "demo-party@newsintel.local",
    },
    {
        "email": "figure@newsintel.local",
        "name": "Political Figure Demo",
        "client_email": "demo-figure@newsintel.local",
    },
    {
        "email": "pr@newsintel.local",
        "name": "PR Agency Demo",
        "client_email": "demo-pr@newsintel.local",
    },
    {
        "email": "media@newsintel.local",
        "name": "Media Analyst Client Demo",
        "client_email": "demo-analyst@newsintel.local",
    },
    {
        "email": "diaspora@newsintel.local",
        "name": "Diaspora Digest Demo",
        "client_email": "demo-diaspora@newsintel.local",
    },
]


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"pbkdf2_sha256$120000${salt}${digest}"


def ensure_journalist_client(session) -> Client:
    email = "demo-journalist@newsintel.local"
    client = session.query(Client).filter(Client.email == email).first()
    if not client:
        client = Client(
            name="NewsIntel Demo Journalist Desk",
            email=email,
            client_type=ClientType.JOURNALIST,
            plan=SubscriptionPlan.PRO,
            country_code="mk",
            language="mk",
            risk_tolerance="balanced",
            settings_json={"demo": True, "presentation_focus": "source_research"},
        )
        session.add(client)
        session.flush()

    watchlist = [
        (WatchlistItemType.TOPIC, "Government accountability", "влада отчетност институции јавност", 2),
        (WatchlistItemType.TOPIC, "Elections and parties", "избори партии кампања ВМРО СДСМ ДУИ", 2),
        (WatchlistItemType.KEYWORD, "Source spread demo", "Македонија влада опозиција Собрание", 3),
    ]
    for item_type, label, value, priority in watchlist:
        existing = (
            session.query(ClientWatchlistItem)
            .filter(
                ClientWatchlistItem.client_id == client.id,
                ClientWatchlistItem.item_type == item_type,
                ClientWatchlistItem.value == value,
            )
            .first()
        )
        if existing:
            existing.label = label
            existing.priority = priority
            continue
        session.add(ClientWatchlistItem(
            client_id=client.id,
            item_type=item_type,
            label=label,
            value=value,
            priority=priority,
            alert_enabled=True,
            response_assist_enabled=False,
            notes="Demo journalist research topic.",
        ))
    return client


def upsert_user(session, email: str, name: str, role: UserRole, client_id: int | None = None) -> str:
    user = session.query(User).filter(User.email == email.lower()).first()
    if user:
        user.name = name
        user.role = role
        user.client_id = client_id
        user.is_active = True
        return "updated"
    session.add(User(
        email=email.lower(),
        name=name,
        password_hash=hash_password(DEMO_PASSWORD),
        role=role,
        client_id=client_id,
        is_active=True,
    ))
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo login users for role dashboards")
    parser.add_argument("--apply", action="store_true", help="Write demo users to the database")
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()
    try:
        journalist = ensure_journalist_client(session)
        client_user_specs = [
            *DEMO_CLIENT_USERS,
            {
                "email": "journalist@newsintel.local",
                "name": "Journalist Research Demo",
                "client_email": journalist.email,
            },
        ]

        actions = []
        actions.append(("analyst@newsintel.local", "Analyst Demo", "analyst", None))
        for spec in client_user_specs:
            client = session.query(Client).filter(Client.email == spec["client_email"]).first()
            if not client:
                actions.append((spec["email"], spec["name"], "missing_client", spec["client_email"]))
                continue
            actions.append((spec["email"], spec["name"], "client", client.id))

        if not args.apply:
            print("Dry run. Re-run with --apply to write demo users.")
            for email, name, role, target in actions:
                print(f"  {email:28} {role:14} {target} {name}")
            return 0

        for email, name, role, target in actions:
            if role == "missing_client":
                print(f"SKIP {email}: missing client {target}")
                continue
            user_role = UserRole.ANALYST if role == "analyst" else UserRole.CLIENT
            result = upsert_user(session, email, name, user_role, target)
            print(f"{result.upper():7} {email} ({role})")
        session.commit()
        print(f"\nDemo password for all seeded demo users: {DEMO_PASSWORD}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
