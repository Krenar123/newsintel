#!/usr/bin/env python3
"""
Generate a news briefing PDF report.

Usage:
    python scripts/generate_report.py                    # Last 7 days, all categories
    python scripts/generate_report.py --days 30          # Last 30 days
    python scripts/generate_report.py --categories politics economy
    python scripts/generate_report.py --email user@example.com
"""

import sys
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    get_engine, get_session_factory, Subscription, SubscriptionFrequency,
)
from src.delivery.pdf_report import PDFReportGenerator, ReportConfig
from src.delivery.email_sender import EmailSender


def main():
    parser = argparse.ArgumentParser(description="Generate news briefing report")
    parser.add_argument(
        "--country", default=settings.default_country,
        help="Country code",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Number of days to include",
    )
    parser.add_argument(
        "--categories", nargs="+", default=None,
        help="Filter by categories (e.g., politics economy)",
    )
    parser.add_argument(
        "--email", default=None,
        help="Send report to this email address",
    )
    parser.add_argument(
        "--send-subscribers", action="store_true",
        help="Send to all active subscribers",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for PDF",
    )
    args = parser.parse_args()

    # Database
    engine = get_engine(settings.database_url)
    Session = get_session_factory(engine)
    session = Session()

    # Country name mapping
    country_names = {"mk": "North Macedonia", "rs": "Serbia", "al": "Albania"}

    # Generate report
    config = ReportConfig(
        country_name=country_names.get(args.country, args.country.upper()),
        country_code=args.country,
        date_to=datetime.datetime.utcnow(),
        date_from=datetime.datetime.utcnow() - datetime.timedelta(days=args.days),
        categories=args.categories,
    )

    output_dir = Path(args.output_dir) if args.output_dir else settings.reports_dir
    generator = PDFReportGenerator(session, output_dir)

    print(f"Generating report for {config.country_name}...")
    print(f"  Period: {config.date_from.strftime('%Y-%m-%d')} to "
          f"{config.date_to.strftime('%Y-%m-%d')}")
    if args.categories:
        print(f"  Categories: {', '.join(args.categories)}")

    filepath = generator.generate(config)
    print(f"\nReport saved: {filepath}")

    # Email delivery
    if args.email or args.send_subscribers:
        if not settings.smtp_enabled:
            print("\nError: email delivery is disabled. Set SMTP_ENABLED=true after testing.")
            sys.exit(1)
        if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password]):
            print("\nError: SMTP settings not configured. Set SMTP_* in .env")
            sys.exit(1)

        sender = EmailSender(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            sender_email=settings.sender_email,
        )

        subject = (
            f"NewsIntel Briefing — {config.country_name} — "
            f"{config.date_to.strftime('%B %d, %Y')}"
        )

        template_data = {
            "title": "News Intelligence Briefing",
            "subtitle": config.country_name,
            "frequency": "weekly",
            "country": config.country_name,
            "date_range": (
                f"{config.date_from.strftime('%B %d')} — "
                f"{config.date_to.strftime('%B %d, %Y')}"
            ),
            "total_articles": 0,
            "total_sources": 0,
            "total_entities": 0,
            "categories": {},
            "pdf_attached": True,
            "unsubscribe_url": "#",
        }

        if args.email:
            print(f"\nSending to {args.email}...")
            success = sender.send_report(
                recipient_email=args.email,
                recipient_name="",
                subject=subject,
                template_data=template_data,
                pdf_path=filepath,
            )
            print("Sent!" if success else "Failed to send.")

        if args.send_subscribers:
            # Get active subscribers for this country
            subs = (
                session.query(Subscription)
                .filter(
                    Subscription.country_code == args.country,
                    Subscription.is_active == True,
                )
                .all()
            )
            print(f"\nSending to {len(subs)} subscribers...")
            recipients = [
                {"email": s.email, "name": s.name or ""}
                for s in subs
            ]
            stats = sender.send_batch(
                recipients=recipients,
                subject=subject,
                template_data=template_data,
                pdf_path=filepath,
            )
            print(f"  Sent: {stats['sent']}, Failed: {stats['failed']}")

    session.close()
    engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    main()
