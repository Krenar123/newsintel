#!/usr/bin/env python3
"""Validate deployment-sensitive NewsIntel environment settings."""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings


DEFAULT_ADMIN_PASSWORDS = {
    "",
    "changeme",
    "changeme123",
    "changeme123!",
    "password",
    "password123",
    "admin",
    "newsintel",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate NewsIntel environment readiness")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings as well as errors")
    parser.add_argument("--check-db", action="store_true", help="Attempt a database connection")
    args = parser.parse_args()

    findings: list[dict] = []
    env = (settings.app_env or "development").lower()
    production = env in {"production", "prod"}
    database_url = settings.database_url or ""

    add(finding_list=findings, level="info", code="app_env", message=f"APP_ENV={env}")
    validate_database(findings, database_url, production, args.check_db)
    validate_auth(findings, production)
    validate_cors(findings, production)
    validate_ingestion(findings)
    validate_retrieval(findings, production)
    validate_email(findings)
    validate_paths(findings)
    validate_optional_integrations(findings, production)

    print_report(findings)
    has_errors = any(item["level"] == "error" for item in findings)
    has_warnings = any(item["level"] == "warning" for item in findings)
    if has_errors or (args.strict and has_warnings):
        return 1
    return 0


def validate_database(findings: list[dict], database_url: str, production: bool, check_db: bool) -> None:
    if not database_url:
        add(findings, "error", "database_missing", "DATABASE_URL is empty.")
        return

    parsed = urlparse(database_url)
    if database_url.startswith("sqlite:///"):
        level = "error" if production else "warning"
        add(findings, level, "sqlite_database", "SQLite is fine locally but not for production pilots.")
    elif parsed.scheme.startswith("postgres"):
        if importlib.util.find_spec("psycopg2") is None:
            add(findings, "error", "postgres_driver_missing", "psycopg2 is not installed.")
        else:
            add(findings, "ok", "postgres_driver", "PostgreSQL driver is installed.")
        weak_passwords = {"newsintel", "postgres", "password", "changeme", ""}
        if (parsed.password or "").lower() in weak_passwords:
            level = "error" if production else "warning"
            add(findings, level, "postgres_weak_password", "PostgreSQL password is a demo/default value.")
    else:
        add(findings, "warning", "database_scheme", f"Unrecognized database scheme: {parsed.scheme or 'unknown'}.")

    if check_db:
        try:
            from sqlalchemy import text
            from src.models.database import get_engine

            engine = get_engine(database_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            add(findings, "ok", "database_connection", "Database connection succeeded.")
        except Exception as exc:
            add(findings, "error", "database_connection_failed", f"Database connection failed: {exc}")


def validate_auth(findings: list[dict], production: bool) -> None:
    password = settings.seed_admin_password or ""
    normalized = password.strip().lower()
    if normalized in DEFAULT_ADMIN_PASSWORDS or len(password) < 14:
        level = "error" if production else "warning"
        add(findings, level, "seed_admin_password", "SEED_ADMIN_PASSWORD should be unique and at least 14 characters.")
    else:
        add(findings, "ok", "seed_admin_password", "Seed admin password length looks acceptable.")

    if settings.seed_admin_email.lower() == "admin@newsintel.local" and production:
        add(findings, "warning", "seed_admin_email", "Use a real admin email in production.")

    if settings.token_expiry_hours <= 0 or settings.token_expiry_hours > 24:
        add(findings, "warning", "token_expiry_hours", "TOKEN_EXPIRY_HOURS should normally be between 1 and 24.")
    else:
        add(findings, "ok", "token_expiry_hours", f"Token expiry is {settings.token_expiry_hours} hours.")


def validate_cors(findings: list[dict], production: bool) -> None:
    origins = [origin.strip() for origin in str(settings.cors_origins or "").split(",") if origin.strip()]
    if not origins:
        add(findings, "error", "cors_origins", "CORS_ORIGINS is empty.")
        return
    if "*" in origins:
        level = "error" if production else "warning"
        add(findings, level, "cors_wildcard", "Do not use wildcard CORS for client deployments.")
    localhost = [origin for origin in origins if "localhost" in origin or "127.0.0.1" in origin]
    if production and localhost:
        add(findings, "warning", "cors_localhost", "Production CORS still includes localhost origins.")
    add(findings, "ok", "cors_origins", f"{len(origins)} CORS origin(s) configured.")


def validate_ingestion(findings: list[dict]) -> None:
    interval = settings.ingestion_interval_minutes
    if interval < 10:
        add(findings, "warning", "ingestion_interval", "Ingestion interval below 10 minutes may stress sources.")
    elif interval > 30:
        add(findings, "warning", "ingestion_interval", "Ingestion interval above 30 minutes may feel stale for clients.")
    else:
        add(findings, "ok", "ingestion_interval", f"Ingestion interval is {interval} minutes.")

    if settings.stop_after_consecutive_duplicates < 3:
        add(findings, "warning", "duplicate_stop", "Duplicate-stop threshold is very low.")
    else:
        add(findings, "ok", "duplicate_stop", f"Duplicate-stop threshold is {settings.stop_after_consecutive_duplicates}.")


def validate_retrieval(findings: list[dict], production: bool) -> None:
    if not 0.1 <= settings.rag_minimum_score <= 20:
        add(findings, "error", "rag_minimum_score", "RAG_MINIMUM_SCORE must be between 0.1 and 20.")
    else:
        add(findings, "ok", "rag_minimum_score", f"RAG minimum score is {settings.rag_minimum_score:.2f}.")
    if not 1 <= settings.rag_max_per_source <= 10:
        add(findings, "error", "rag_source_cap", "RAG_MAX_PER_SOURCE must be between 1 and 10.")
    if not 4 <= settings.rag_max_evidence <= 24:
        add(findings, "error", "rag_evidence_cap", "RAG_MAX_EVIDENCE must be between 4 and 24.")

    report_path = settings.base_dir / "data" / "rag_evaluations" / "latest_quality_report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            passed = bool((report.get("production_gate") or {}).get("passed"))
            add(
                findings,
                "ok" if passed else "error",
                "rag_quality_gate",
                "RAG retrieval gate passed." if passed else "Latest RAG retrieval gate did not pass.",
            )
        except (OSError, ValueError, TypeError) as exc:
            add(findings, "error", "rag_quality_report", f"Cannot read RAG quality report: {exc}")
    elif production:
        add(
            findings,
            "warning",
            "rag_quality_missing",
            "No RAG holdout report exists at data/rag_evaluations/latest_quality_report.json.",
        )


def validate_email(findings: list[dict]) -> None:
    if not settings.smtp_enabled:
        add(findings, "info", "smtp_disabled", "SMTP delivery is explicitly disabled.")
        return
    values = [settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.sender_email]
    configured = [bool(value) for value in values]
    if all(configured):
        add(findings, "ok", "smtp_configured", "SMTP settings are present.")
    else:
        add(
            findings,
            "error",
            "smtp_incomplete",
            "SMTP_ENABLED=true requires host, user, password, and sender email.",
        )


def validate_paths(findings: list[dict]) -> None:
    for code, path in {
        "reports_dir": settings.reports_dir,
        "models_dir": settings.models_dir,
        "data_dir": settings.base_dir / "data",
        "countries_dir": settings.countries_dir,
    }.items():
        if Path(path).exists():
            add(findings, "ok", code, f"{path} exists.")
        else:
            add(findings, "error", code, f"{path} does not exist.")


def validate_optional_integrations(findings: list[dict], production: bool) -> None:
    ai_enabled = settings.enable_ai_summaries or settings.enable_ai_intelligence
    ai_key = settings.ai_api_key or settings.anthropic_api_key
    if ai_enabled and not ai_key:
        add(
            findings,
            "error",
            "ai_key_missing",
            "AI intelligence is enabled but AI_API_KEY is empty.",
        )
    elif ai_enabled and not settings.ai_grounding_required:
        add(
            findings,
            "error",
            "ai_grounding_disabled",
            "AI_GROUNDING_REQUIRED must stay enabled for client-facing output.",
        )
    elif ai_enabled:
        add(
            findings,
            "ok",
            "ai_configured",
            f"AI provider {settings.ai_provider} is enabled with grounding required.",
        )
    else:
        add(findings, "info", "ai_disabled", "Production AI intelligence is disabled.")

    if settings.enable_gliner_ner:
        if importlib.util.find_spec("gliner") is None:
            add(
                findings,
                "error",
                "gliner_missing",
                "ENABLE_GLINER_NER=true requires requirements-ner.txt.",
            )
        elif not 0.0 < settings.gliner_threshold < 1.0:
            add(findings, "error", "gliner_threshold", "GLINER_THRESHOLD must be between 0 and 1.")
        else:
            add(
                findings,
                "ok",
                "gliner_configured",
                f"GLiNER {settings.gliner_model} is enabled at {settings.gliner_threshold:.2f}.",
            )
    else:
        add(findings, "info", "gliner_disabled", "Optional GLiNER entity discovery is disabled.")

    entity_report_path = settings.base_dir / "data" / "entity_annotations" / "latest_quality_report.json"
    if entity_report_path.exists():
        try:
            entity_report = json.loads(entity_report_path.read_text(encoding="utf-8"))
            gate_passed = bool((entity_report.get("production_gate") or {}).get("passed"))
            add(
                findings,
                "ok" if gate_passed else "error",
                "entity_holdout_gate",
                "Blinded entity holdout passed." if gate_passed else "Latest entity holdout did not pass.",
            )
        except (OSError, ValueError, TypeError) as exc:
            add(findings, "error", "entity_holdout_report", f"Cannot read entity holdout report: {exc}")
    elif production:
        add(
            findings,
            "warning",
            "entity_holdout_missing",
            "No blinded entity holdout report exists at data/entity_annotations/latest_quality_report.json.",
        )

    if settings.facebook_access_token:
        add(findings, "info", "facebook_configured", "Facebook token is present, but social ingestion is parked for now.")
    else:
        add(findings, "info", "facebook_disabled", "Facebook token is empty.")


def add(finding_list: list[dict], level: str, code: str, message: str) -> None:
    finding_list.append({"level": level, "code": code, "message": message})


def print_report(findings: list[dict]) -> None:
    order = {"error": 0, "warning": 1, "ok": 2, "info": 3}
    for item in sorted(findings, key=lambda row: (order.get(row["level"], 9), row["code"])):
        print(f"{item['level'].upper():7} {item['code']:<28} {item['message']}")
    errors = sum(1 for item in findings if item["level"] == "error")
    warnings = sum(1 for item in findings if item["level"] == "warning")
    ok = sum(1 for item in findings if item["level"] == "ok")
    info = sum(1 for item in findings if item["level"] == "info")
    print(f"\nSummary: {errors} error(s), {warnings} warning(s), {ok} ok, {info} info")


if __name__ == "__main__":
    raise SystemExit(main())
