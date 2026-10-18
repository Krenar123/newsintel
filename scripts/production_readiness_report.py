#!/usr/bin/env python3
"""Static production-readiness report for the repository.

This complements scripts/validate_env.py. validate_env checks the active
environment; this script checks whether the repo contains the deployment assets
and guardrails expected before moving NewsIntel to a public pilot.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


REQUIRED_ENV_KEYS = {
    "APP_ENV",
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "CORS_ORIGINS",
    "VITE_API_BASE_URL",
    "SEED_ADMIN_EMAIL",
    "SEED_ADMIN_PASSWORD",
    "TOKEN_EXPIRY_HOURS",
    "INGESTION_INTERVAL_MINUTES",
    "STOP_AFTER_CONSECUTIVE_DUPLICATES",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check production deployment assets")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings")
    args = parser.parse_args()

    findings: list[dict] = []
    check_file(findings, "dockerfile_api", ROOT / "Dockerfile")
    check_file(findings, "dockerfile_frontend", ROOT / "Dockerfile.frontend")
    check_file(findings, "compose_production", ROOT / "docker-compose.production.yml")
    check_file(findings, "frontend_nginx", ROOT / "frontend" / "nginx.conf")
    check_file(findings, "env_production_example", ROOT / ".env.production.example")
    check_file(findings, "production_docs", ROOT / "docs" / "PRODUCTION_READINESS.md")
    check_file(findings, "backup_script", ROOT / "scripts" / "backup_database.py")
    check_file(findings, "restore_script", ROOT / "scripts" / "restore_database.py")
    check_file(findings, "historical_planner", ROOT / "scripts" / "plan_historical_ingestion.py")
    check_file(findings, "release_gate", ROOT / "scripts" / "release_gate.py")
    check_file(findings, "owner_actions", ROOT / "docs" / "OWNER_ACTIONS.md")

    check_env_template(findings)
    check_compose(findings)
    check_dockerignore(findings)

    payload = {
        "summary": summarize(findings),
        "findings": findings,
        "next_actions": next_actions(findings),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload)

    has_errors = any(item["level"] == "error" for item in findings)
    has_warnings = any(item["level"] == "warning" for item in findings)
    return 1 if has_errors or (args.strict and has_warnings) else 0


def check_file(findings: list[dict], code: str, path: Path) -> None:
    if path.exists():
        add(findings, "ok", code, f"{path.relative_to(ROOT)} exists.")
    else:
        add(findings, "error", code, f"{path.relative_to(ROOT)} is missing.")


def check_env_template(findings: list[dict]) -> None:
    path = ROOT / ".env.production.example"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    keys = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    missing = sorted(REQUIRED_ENV_KEYS - keys)
    if missing:
        add(findings, "error", "env_required_keys", f"Missing production env keys: {', '.join(missing)}.")
    else:
        add(findings, "ok", "env_required_keys", "Production env template has required keys.")
    weak_markers = [
        "replace-with-strong-random-password",
        "replace-with-long-random-admin-password",
    ]
    if all(marker in text for marker in weak_markers):
        add(findings, "ok", "env_secret_placeholders", "Secret placeholders are explicit.")
    else:
        add(findings, "warning", "env_secret_placeholders", "Secret placeholders should be explicit and obvious.")


def check_compose(findings: list[dict]) -> None:
    path = ROOT / "docker-compose.production.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "--reload" in text:
        add(findings, "error", "compose_reload", "Production compose must not use uvicorn --reload.")
    else:
        add(findings, "ok", "compose_reload", "Production compose does not use --reload.")
    for service in ("api:", "scheduler:", "frontend:", "db:"):
        if service not in text:
            add(findings, "error", f"compose_service_{service[:-1]}", f"Missing {service[:-1]} service.")
    if "healthcheck:" in text:
        add(findings, "ok", "compose_healthchecks", "Production compose includes healthchecks.")
    else:
        add(findings, "warning", "compose_healthchecks", "Production compose should include healthchecks.")
    if "condition: service_healthy" in text:
        add(findings, "ok", "compose_dependencies", "Services wait for healthy dependencies.")
    else:
        add(findings, "warning", "compose_dependencies", "Services should wait for healthy dependencies.")
    if ".:/app" in text:
        add(findings, "error", "compose_bind_mount", "Production compose should not bind-mount source code.")
    else:
        add(findings, "ok", "compose_bind_mount", "Production compose avoids source bind mounts.")


def check_dockerignore(findings: list[dict]) -> None:
    path = ROOT / ".dockerignore"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for pattern in ("venv/", ".env", "data/", "reports/", "frontend/node_modules/"):
        if pattern not in text:
            add(findings, "warning", f"dockerignore_{pattern}", f".dockerignore should exclude {pattern}.")
    add(findings, "ok", "dockerignore_present", ".dockerignore is present.")


def add(findings: list[dict], level: str, code: str, message: str) -> None:
    findings.append({"level": level, "code": code, "message": message})


def summarize(findings: list[dict]) -> dict:
    return {
        "errors": sum(1 for item in findings if item["level"] == "error"),
        "warnings": sum(1 for item in findings if item["level"] == "warning"),
        "ok": sum(1 for item in findings if item["level"] == "ok"),
    }


def next_actions(findings: list[dict]) -> list[str]:
    if any(item["level"] == "error" for item in findings):
        return ["Fix error findings before attempting a public/cloud deployment."]
    actions = [
        "Create real production secrets from .env.production.example.",
        "Run scripts/validate_env.py --strict --check-db against the production database.",
        "Run scripts/smoke_test.py after deploying API and frontend.",
        "Configure daily database backups or provider snapshots before historical ingestion.",
    ]
    if any(item["level"] == "warning" for item in findings):
        actions.insert(0, "Review warning findings; decide whether they block the pilot.")
    return actions


def print_text(payload: dict) -> None:
    summary = payload["summary"]
    print(f"Production readiness assets: {summary['errors']} error(s), {summary['warnings']} warning(s), {summary['ok']} ok")
    for item in payload["findings"]:
        print(f"{item['level'].upper():7} {item['code']:<28} {item['message']}")
    print("\nNext actions:")
    for action in payload["next_actions"]:
        print(f"- {action}")


if __name__ == "__main__":
    raise SystemExit(main())
