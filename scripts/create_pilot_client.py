#!/usr/bin/env python3
"""Validate or create one real pilot client from a reviewed YAML file."""

import argparse
import hashlib
import os
import secrets
import sys
from pathlib import Path

import yaml

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a configured pilot client")
    parser.add_argument("config", help="Reviewed pilot client YAML file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument(
        "--password-env",
        default="PILOT_CLIENT_PASSWORD",
        help="Environment variable holding the initial account password",
    )
    args = parser.parse_args()

    path = Path(args.config)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors = validate_payload(payload)
    if errors:
        print("Pilot config is not ready:")
        for error in errors:
            print(f"  - {error}")
        return 2

    client_data = payload["client"]
    user_data = payload["user"]
    print(f"Client: {client_data['name']} ({client_data['client_type']})")
    print(f"User: {user_data['email']}")
    print(f"Watchlist items: {len(payload['watchlist'])}")
    if not args.apply:
        print("Dry run only. Add --apply --confirm CREATE_PILOT_CLIENT to write.")
        return 0
    if args.confirm != "CREATE_PILOT_CLIENT":
        print("ERROR: --confirm CREATE_PILOT_CLIENT is required.", file=sys.stderr)
        return 2

    password = os.getenv(args.password_env, "")
    if len(password) < 14:
        print(
            f"ERROR: {args.password_env} must contain at least 14 characters.",
            file=sys.stderr,
        )
        return 2

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as db:
        if db.query(Client).filter(Client.email == client_data["email"].lower()).first():
            print("ERROR: a client already uses this email.", file=sys.stderr)
            return 2
        if db.query(User).filter(User.email == user_data["email"].lower()).first():
            print("ERROR: a user already uses this email.", file=sys.stderr)
            return 2

        client = Client(
            name=client_data["name"].strip(),
            email=client_data["email"].lower(),
            client_type=ClientType(client_data["client_type"]),
            plan=SubscriptionPlan(client_data["plan"]),
            country_code=client_data.get("country_code", "mk"),
            language=client_data.get("language", "mk"),
            risk_tolerance=client_data.get("risk_tolerance", "balanced"),
            settings_json=client_data.get("settings", {}),
        )
        db.add(client)
        db.flush()

        for item in payload["watchlist"]:
            db.add(ClientWatchlistItem(
                client_id=client.id,
                item_type=WatchlistItemType(item["item_type"]),
                label=item["label"].strip(),
                value=item["value"].strip(),
                aliases=item.get("aliases", []),
                priority=int(item.get("priority", 3)),
                alert_enabled=bool(item.get("alert_enabled", True)),
                response_assist_enabled=bool(
                    item.get("response_assist_enabled", False)
                ),
                notes="Created from reviewed pilot configuration.",
            ))

        db.add(User(
            email=user_data["email"].lower(),
            name=user_data["name"].strip(),
            password_hash=hash_password(password),
            role=UserRole.CLIENT,
            client_id=client.id,
            is_active=True,
        ))
        db.commit()
        print(f"Created pilot client id {client.id}.")
    engine.dispose()
    return 0


def validate_payload(payload: dict) -> list[str]:
    errors = []
    client = payload.get("client") or {}
    user = payload.get("user") or {}
    watchlist = payload.get("watchlist") or []
    required = {
        "client.name": client.get("name"),
        "client.email": client.get("email"),
        "client.client_type": client.get("client_type"),
        "client.plan": client.get("plan"),
        "user.email": user.get("email"),
        "user.name": user.get("name"),
    }
    for name, value in required.items():
        if not value:
            errors.append(f"{name} is required")
        elif "replace" in str(value).casefold():
            errors.append(f"{name} still contains a template placeholder")
    if client.get("client_type") not in {item.value for item in ClientType}:
        errors.append("client.client_type is not supported")
    if client.get("plan") not in {item.value for item in SubscriptionPlan}:
        errors.append("client.plan is not supported")
    if not watchlist:
        errors.append("at least one watchlist item is required")
    for index, item in enumerate(watchlist, start=1):
        if item.get("item_type") not in {entry.value for entry in WatchlistItemType}:
            errors.append(f"watchlist item {index} has an unsupported item_type")
        if not item.get("label") or not item.get("value"):
            errors.append(f"watchlist item {index} needs label and value")
        if "replace" in str(item.get("value", "")).casefold():
            errors.append(f"watchlist item {index} still contains a placeholder")
    return errors


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"pbkdf2_sha256$120000${salt}${digest}"


if __name__ == "__main__":
    raise SystemExit(main())
