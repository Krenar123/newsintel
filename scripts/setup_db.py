#!/usr/bin/env python3
"""
Setup the database — create all tables and seed initial sources.

Usage:
    python scripts/setup_db.py
    python scripts/setup_db.py --seed  # Also insert sources from country configs
"""

import sys
import argparse
import hashlib
import secrets
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from config import settings
from src.models.database import (
    get_engine, get_session_factory, create_all_tables, Source, User, UserRole,
)


def setup(seed: bool = False):
    """Create tables and optionally seed sources."""
    print(f"Connecting to: {settings.database_url}")

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    print("All tables created successfully.")

    if seed:
        Session = get_session_factory(engine)
        session = Session()
        seed_sources(session)
        seed_admin_user(session)
        session.close()

    engine.dispose()
    print("Done.")


def seed_sources(session):
    """Insert sources from country config files."""
    for config_file in settings.countries_dir.glob("*.yaml"):
        print(f"\nProcessing: {config_file.name}")

        with open(config_file, encoding="utf-8") as f:
            country = yaml.safe_load(f)

        country_code = country.get("code", "")

        for src in country.get("sources", []):
            upsert_source(session, src, country_code)

        for page in country.get("facebook_pages", []):
            if page.get("enabled", True) is False:
                continue
            source_config = {
                **page,
                "source_type": page.get("source_type", "social_media"),
                "rss_feeds": [],
            }
            upsert_source(session, source_config, country_code)

        session.commit()
        print(f"  Sources seeded for {country.get('name', country_code)}")


def seed_admin_user(session):
    """Create the default local admin user if it does not exist."""
    email = settings.seed_admin_email.lower()
    existing = session.query(User).filter(User.email == email).first()
    if existing:
        print(f"\nAdmin user exists: {email}")
        return
    user = User(
        email=email,
        name="NewsIntel Admin",
        password_hash=hash_password(settings.seed_admin_password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.commit()
    print(f"\nAdmin user added: {email}")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"pbkdf2_sha256$120000${salt}${digest}"


def upsert_source(session, src, country_code):
    """Insert or update a source-like config item."""
    existing = (
        session.query(Source)
        .filter(Source.url == src["url"])
        .first()
    )
    if existing:
        existing.country_code = country_code or existing.country_code
        existing.language = src.get("language", existing.language)
        existing.reliability_score = src.get(
            "reliability_score", existing.reliability_score
        )
        existing.source_type = src.get("source_type", existing.source_type)
        existing.political_leaning = src.get(
            "political_leaning", existing.political_leaning
        )
        existing.ownership = src.get("ownership", existing.ownership)
        existing.rss_feeds = src.get("rss_feeds", existing.rss_feeds)
        print(f"  * Updated existing: {src['name']}")
        return

    source = Source(
        name=src["name"],
        url=src["url"],
        country_code=country_code,
        language=src.get("language", "en"),
        reliability_score=src.get("reliability_score", 0.5),
        source_type=src.get("source_type", "news"),
        political_leaning=src.get("political_leaning", "unknown"),
        ownership=src.get("ownership"),
        rss_feeds=src.get("rss_feeds", []),
        is_active=True,
    )
    session.add(source)
    print(f"  + Added: {src['name']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup NewsIntel database")
    parser.add_argument(
        "--seed", action="store_true",
        help="Seed sources from country configs",
    )
    args = parser.parse_args()
    setup(seed=args.seed)
