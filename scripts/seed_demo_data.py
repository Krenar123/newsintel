#!/usr/bin/env python3
"""Seed demo clients and watchlists for presenting the NewsIntel war room."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    Client,
    ClientType,
    ClientWatchlistItem,
    SubscriptionPlan,
    WatchlistItemType,
    create_all_tables,
    get_engine,
    get_session_factory,
)


DEMO_CLIENTS = [
    {
        "name": "NewsIntel Demo Party War Room",
        "email": "demo-party@newsintel.local",
        "client_type": ClientType.POLITICAL_PARTY,
        "plan": SubscriptionPlan.CAMPAIGN,
        "country_code": "mk",
        "language": "mk",
        "risk_tolerance": "active",
        "settings_json": {
            "demo": True,
            "presentation_focus": "press_conference_response",
            "briefing_language": "mk",
        },
        "watchlist": [
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "EU path and constitutional changes",
                "value": "ЕУ уставни измени Бугари Европска Унија",
                "priority": 1,
                "notes": "High-value geopolitical topic for party messaging.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Judiciary and corruption",
                "value": "судство корупција обвинителство правда",
                "priority": 1,
                "notes": "Core attack and credibility theme.",
            },
            {
                "item_type": WatchlistItemType.KEYWORD,
                "label": "VMRO-DPMNE",
                "value": "ВМРО ДПМНЕ VMRO DPMNE",
                "priority": 2,
                "notes": "Party/opponent monitoring keyword.",
            },
            {
                "item_type": WatchlistItemType.KEYWORD,
                "label": "SDSM",
                "value": "СДСМ SDSM",
                "priority": 2,
                "notes": "Party/opponent monitoring keyword.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Economy and living costs",
                "value": "економија цени плати инфлација животен стандард",
                "priority": 2,
                "notes": "Useful for public-facing press conference preparation.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Foreign policy pressure",
                "value": "Софија Брисел Вашингтон НАТО ЕУ",
                "priority": 3,
                "notes": "Tracks diplomatic pressure and regional narratives.",
            },
        ],
    },
    {
        "name": "NewsIntel Demo Political Figure",
        "email": "demo-figure@newsintel.local",
        "client_type": ClientType.POLITICAL_FIGURE,
        "plan": SubscriptionPlan.POLITICAL_DEFENSE,
        "country_code": "mk",
        "language": "mk",
        "risk_tolerance": "balanced",
        "settings_json": {
            "demo": True,
            "presentation_focus": "attack_detection_response_pack",
            "briefing_language": "mk",
        },
        "watchlist": [
            {
                "item_type": WatchlistItemType.KEYWORD,
                "label": "Personal attack signals",
                "value": "оставка скандал одговорност напад критика",
                "priority": 1,
                "notes": "Generic attack language demo for a political figure.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Public trust and institutions",
                "value": "доверба институции јавност рејтинг анкета",
                "priority": 2,
                "notes": "Tracks reputation-sensitive coverage.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Legal response angle",
                "value": "клевета навреда закон одговор демант",
                "priority": 1,
                "notes": "Connects response packs to legal-reference guidance.",
            },
        ],
    },
    {
        "name": "NewsIntel Demo PR Agency Desk",
        "email": "demo-pr@newsintel.local",
        "client_type": ClientType.PR_AGENCY,
        "plan": SubscriptionPlan.ENTERPRISE,
        "country_code": "mk",
        "language": "mk",
        "risk_tolerance": "balanced",
        "settings_json": {
            "demo": True,
            "presentation_focus": "multi_client_reputation_monitoring",
            "briefing_language": "mk",
        },
        "watchlist": [
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Client reputation and criticism",
                "value": "критика реакција јавност доверба репутација",
                "priority": 1,
                "notes": "Agency workflow for reputation-sensitive coverage.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Media spread signals",
                "value": "објави медиуми пренесуваат реакција портали",
                "priority": 2,
                "notes": "Shows when a story is spreading across outlets.",
            },
            {
                "item_type": WatchlistItemType.KEYWORD,
                "label": "Crisis language",
                "value": "скандал афера оставка одговорност истрага",
                "priority": 1,
                "notes": "Useful for agency crisis monitoring demos.",
            },
        ],
    },
    {
        "name": "NewsIntel Demo Media Analyst",
        "email": "demo-analyst@newsintel.local",
        "client_type": ClientType.MEDIA_ANALYST,
        "plan": SubscriptionPlan.PRO,
        "country_code": "mk",
        "language": "mk",
        "risk_tolerance": "balanced",
        "settings_json": {
            "demo": True,
            "presentation_focus": "narratives_trends_source_intelligence",
            "briefing_language": "mk",
        },
        "watchlist": [
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Government and institutions",
                "value": "Влада Собрание Министерство институции претседател",
                "priority": 2,
                "notes": "Core analyst topic for institutional coverage.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Regional foreign policy",
                "value": "Бугарија Грција Србија Косово НАТО Албанија",
                "priority": 3,
                "notes": "Useful for narrative and source spread demos.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Election and campaign coverage",
                "value": "избори кампања анкета коалиција партии",
                "priority": 2,
                "notes": "Shows election-cycle media monitoring.",
            },
        ],
    },
    {
        "name": "NewsIntel Demo Diaspora Digest",
        "email": "demo-diaspora@newsintel.local",
        "client_type": ClientType.DIASPORA,
        "plan": SubscriptionPlan.BASIC,
        "country_code": "mk",
        "language": "en",
        "risk_tolerance": "calm",
        "settings_json": {
            "demo": True,
            "presentation_focus": "daily_digest_for_communities_abroad",
            "briefing_language": "en",
        },
        "watchlist": [
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Top Macedonia news",
                "value": "Македонија Влада Собрание економија вести",
                "priority": 2,
                "notes": "Broad digest topic for people outside the country.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Travel and consular relevance",
                "value": "граница пасоши дијаспора аеродром конзуларно",
                "priority": 3,
                "notes": "Practical diaspora interest area.",
            },
            {
                "item_type": WatchlistItemType.TOPIC,
                "label": "Culture and community",
                "value": "култура заедница иселеници образование",
                "priority": 4,
                "notes": "Lighter digest material beyond politics.",
            },
        ],
    },
]


def _upsert_watchlist_item(db, client: Client, item: dict) -> bool:
    existing = (
        db.query(ClientWatchlistItem)
        .filter(
            ClientWatchlistItem.client_id == client.id,
            ClientWatchlistItem.item_type == item["item_type"],
            ClientWatchlistItem.value == item["value"],
        )
        .first()
    )
    if existing:
        existing.label = item["label"]
        existing.priority = item["priority"]
        existing.notes = item.get("notes")
        existing.alert_enabled = True
        existing.response_assist_enabled = True
        return False

    db.add(
        ClientWatchlistItem(
            client_id=client.id,
            item_type=item["item_type"],
            label=item["label"],
            value=item["value"],
            priority=item["priority"],
            alert_enabled=True,
            response_assist_enabled=True,
            notes=item.get("notes"),
        )
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="Seed demo clients for the NewsIntel dashboard")
    parser.add_argument("--apply", action="store_true", help="Write demo data to the database")
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    db = session_factory()
    try:
        created_clients = 0
        updated_clients = 0
        created_items = 0
        updated_items = 0

        for spec in DEMO_CLIENTS:
            client = db.query(Client).filter(Client.email == spec["email"]).first()
            if client:
                updated_clients += 1
                if args.apply:
                    client.name = spec["name"]
                    client.client_type = spec["client_type"]
                    client.plan = spec["plan"]
                    client.country_code = spec["country_code"]
                    client.language = spec["language"]
                    client.risk_tolerance = spec["risk_tolerance"]
                    client.settings_json = spec["settings_json"]
                    client.is_active = True
            else:
                created_clients += 1
                if args.apply:
                    client = Client(
                        name=spec["name"],
                        email=spec["email"],
                        client_type=spec["client_type"],
                        plan=spec["plan"],
                        country_code=spec["country_code"],
                        language=spec["language"],
                        risk_tolerance=spec["risk_tolerance"],
                        settings_json=spec["settings_json"],
                        is_active=True,
                    )
                    db.add(client)
                    db.flush()

            if not args.apply:
                created_items += len(spec["watchlist"])
                continue

            for item in spec["watchlist"]:
                if _upsert_watchlist_item(db, client, item):
                    created_items += 1
                else:
                    updated_items += 1

        if args.apply:
            db.commit()

        prefix = "Inserted/updated" if args.apply else "Would seed"
        print(
            f"{prefix}: clients created={created_clients}, clients updated={updated_clients}, "
            f"watchlist created={created_items}, watchlist updated={updated_items}"
        )
        if not args.apply:
            print("Dry run only. Re-run with --apply to write demo data.")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
