#!/usr/bin/env python3
"""Run the code-side release gates without ingesting data or deploying services."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NewsIntel pre-release verification")
    parser.add_argument("--base-url", help="Also run live API, pilot, and performance checks")
    parser.add_argument("--email", default=os.getenv("NEWSINTEL_ADMIN_EMAIL", "admin@newsintel.local"))
    parser.add_argument(
        "--password-env",
        default="NEWSINTEL_ADMIN_PASSWORD",
        help="Environment variable containing the admin password",
    )
    parser.add_argument("--check-active-env", action="store_true", help="Validate the active deployment environment and DB")
    parser.add_argument("--require-ai", action="store_true", help="Require a configured, grounded production AI provider")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip the frontend production build")
    args = parser.parse_args()

    checks: list[tuple[str, list[str], Path]] = [
        (
            "Static production assets",
            [sys.executable, "scripts/production_readiness_report.py", "--strict"],
            ROOT,
        ),
        (
            "Python regression tests",
            [sys.executable, "-m", "pytest", "-q"],
            ROOT,
        ),
    ]
    if not args.skip_frontend:
        npm = find_npm()
        if not npm:
            print("FAIL Frontend production build: npm was not found.")
            return 1
        checks.append(("Frontend production build", [npm, "run", "build"], ROOT / "frontend"))
    if args.check_active_env:
        checks.append((
            "Active environment and database",
            [sys.executable, "scripts/validate_env.py", "--strict", "--check-db"],
            ROOT,
        ))
    checks.append((
        "AI grounding",
        [
            sys.executable,
            "scripts/verify_ai_grounding.py",
            *(["--require-provider"] if args.require_ai else []),
        ],
        ROOT,
    ))

    if args.base_url:
        password = os.getenv(args.password_env, "")
        if not password:
            print(
                f"FAIL Live verification: set {args.password_env} to the admin password. "
                "The release gate does not accept secrets on the command line."
            )
            return 1
        common = ["--base-url", args.base_url, "--email", args.email, "--password", password]
        checks.extend([
            ("API smoke test", [sys.executable, "scripts/smoke_test.py", *common], ROOT),
            ("Pilot readiness", [sys.executable, "scripts/pilot_readiness_report.py", *common], ROOT),
            ("Dashboard performance", [sys.executable, "scripts/benchmark_dashboards.py", *common], ROOT),
        ])

    failures = []
    for label, command, cwd in checks:
        print(f"\n=== {label} ===", flush=True)
        result = subprocess.run(command, cwd=cwd, check=False)
        if result.returncode:
            failures.append(label)

    print("\n=== Release gate summary ===")
    if failures:
        print(f"FAIL: {len(failures)} gate(s): {', '.join(failures)}")
        return 1
    print(f"PASS: all {len(checks)} selected gates completed successfully.")
    print("No ingestion, database restore, deployment, email, or social-media action was performed.")
    return 0


def find_npm() -> str | None:
    bundled = ROOT / ".tools" / "node-v24.14.1-win-x64" / "npm.cmd"
    if bundled.exists():
        return str(bundled)
    return shutil.which("npm")


if __name__ == "__main__":
    raise SystemExit(main())
