#!/usr/bin/env python3
"""Pre-demo pilot readiness report for the local/API environment."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def request(self, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw
        except urllib.error.URLError as exc:
            return 599, str(exc.reason)


def main() -> int:
    parser = argparse.ArgumentParser(description="NewsIntel pilot/demo readiness report")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@newsintel.local")
    parser.add_argument("--password", default="ChangeMe123!")
    parser.add_argument("--country", default="mk")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    client = ApiClient(args.base_url)
    status, payload = client.request("GET", "/health")
    if status >= 400:
        return emit(args.json, [{"key": "api", "status": "fail", "detail": f"API unavailable: {payload}"}])

    status, login = client.request("POST", "/api/v1/auth/login", {"email": args.email, "password": args.password})
    if status >= 400:
        return emit(args.json, [{"key": "auth", "status": "fail", "detail": "Admin login failed."}])
    client.token = login["access_token"]

    country = urllib.parse.quote(args.country)
    data = {}
    endpoints = {
        "intelligence_qa": f"/api/v1/admin/intelligence-qa?country_code={country}",
        "scheduler": f"/api/v1/admin/scheduler/status?country_code={country}",
        "source_health": f"/api/v1/admin/ingestion/source-health?country_code={country}",
        "config": f"/api/v1/admin/sources/config-validation?country_code={country}",
        "search": f"/api/v1/admin/search/quality?country_code={country}",
        "article_quality": f"/api/v1/admin/article-quality?country_code={country}&limit=25",
        "attack_review": f"/api/v1/admin/attacks/review?country_code={country}&days=30&limit=80",
        "legal": f"/api/v1/admin/legal/quality?country_code={country}",
        "clients": "/api/v1/admin/clients/brief-readiness?days=1",
        "backups": "/api/v1/admin/backups",
        "launch": f"/api/v1/admin/launch-checklist?country_code={country}",
    }

    checks = []
    for key, path in endpoints.items():
        status, payload = client.request("GET", path)
        data[key] = payload if status < 400 else None
        if status >= 400:
            checks.append({"key": key, "status": "fail", "detail": f"Endpoint returned {status}."})

    qa = data.get("intelligence_qa") or {}
    qa_score = int(qa.get("score") or 0)
    checks.append({
        "key": "intelligence_qa",
        "status": "pass" if qa_score >= 80 else "warn",
        "detail": f"Intelligence QA score is {qa_score}/100.",
    })

    scheduler = data.get("scheduler") or {}
    checks.append({
        "key": "scheduler_freshness",
        "status": "pass" if not scheduler.get("stale_warning") else "warn",
        "detail": f"Scheduler status: {scheduler.get('status', 'unknown')}; stale minutes: {scheduler.get('stale_minutes')}.",
    })

    source_health = data.get("source_health") or {}
    source_summary = source_health.get("summary") or {}
    attention_sources = int(source_summary.get("attention_count") or 0)
    operational_sources = (
        int(source_summary.get("healthy_count") or 0)
        + int(source_summary.get("caught_up_count") or 0)
        + int(source_summary.get("rss_only_count") or 0)
    )
    checks.append({
        "key": "source_health",
        "status": "pass" if attention_sources == 0 else "warn",
        "detail": (
            f"{operational_sources} operational sources; "
            f"{attention_sources} need attention; "
            f"{source_summary.get('parked_social_count', 0)} parked social."
        ),
    })

    config = data.get("config") or {}
    config_summary = config.get("summary") or {}
    critical = int(config_summary.get("critical_count") or 0)
    warnings = int(config_summary.get("warning_count") or 0)
    checks.append({
        "key": "source_config",
        "status": "pass" if critical == 0 else "fail",
        "detail": f"{critical} critical config issues; {warnings} warnings.",
    })

    search = data.get("search") or {}
    checks.append({
        "key": "search_quality",
        "status": "pass" if search.get("status") == "ready" else "warn",
        "detail": f"Search status: {search.get('status', 'unknown')}.",
    })

    article_quality = data.get("article_quality") or {}
    issue_count = int(article_quality.get("issue_count") or 0)
    checks.append({
        "key": "article_quality",
        "status": "pass" if issue_count == 0 else "warn",
        "detail": f"{issue_count} article quality issues flagged.",
    })

    attack_review = data.get("attack_review") or {}
    unreviewed_attacks = int((attack_review.get("summary") or {}).get("unreviewed") or 0)
    checks.append({
        "key": "attack_review",
        "status": "pass" if unreviewed_attacks == 0 else "warn",
        "detail": f"{unreviewed_attacks} target-specific attack detections still need operator review.",
    })

    legal = data.get("legal") or {}
    missing = int((legal.get("coverage_summary") or {}).get("missing") or 0)
    checks.append({
        "key": "legal_context",
        "status": "pass" if missing == 0 else "warn",
        "detail": f"{missing} required legal coverage areas missing; review flags still apply.",
    })

    clients = data.get("clients") or []
    ready_clients = sum(1 for item in clients if item.get("ready"))
    checks.append({
        "key": "demo_clients",
        "status": "pass" if len(clients) >= 3 and ready_clients > 0 else "warn",
        "detail": f"{len(clients)} active clients; {ready_clients} daily-brief ready.",
    })

    backups = data.get("backups") or {}
    checks.append({
        "key": "backup",
        "status": "pass" if backups.get("latest") else "warn",
        "detail": "Latest backup exists." if backups.get("latest") else "No backup found before pilot/demo.",
    })

    launch = data.get("launch") or {}
    checks.append({
        "key": "launch_checklist",
        "status": "pass" if launch.get("overall") in {"ready", "demo_ready"} else "warn",
        "detail": f"Launch checklist: {launch.get('overall', 'unknown')}.",
    })

    return emit(args.json, checks)


def emit(as_json: bool, checks: list[dict]) -> int:
    failed = sum(1 for item in checks if item["status"] == "fail")
    warnings = sum(1 for item in checks if item["status"] == "warn")
    passed = len(checks) - failed - warnings
    if as_json:
        print(json.dumps({"failed": failed, "warnings": warnings, "passed": passed, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print(f"Pilot readiness: {failed} fail, {warnings} warning(s), {passed} pass")
        for item in checks:
            print(f"{item['status'].upper():5} {item['key']:<22} {item['detail']}")
        print("\nNext actions:")
        print("- Clear FAIL items before a real client demo.")
        print("- WARN items are acceptable for internal testing, but should be explained or cleaned before pilots.")
        print("- Keep Facebook/social integrations parked until news ingestion is stable.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
