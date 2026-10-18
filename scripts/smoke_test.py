#!/usr/bin/env python3
"""Smoke-test the local NewsIntel API against demo-critical endpoints."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description="NewsIntel API smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@newsintel.local")
    parser.add_argument("--password", default="ChangeMe123!")
    parser.add_argument("--country", default="mk")
    args = parser.parse_args()

    client = ApiClient(args.base_url)
    checks = []

    status, payload = client.request("GET", "/health")
    checks.append(check("health", status, payload, "status"))

    status, payload = client.request("POST", "/api/v1/auth/login", {
        "email": args.email,
        "password": args.password,
    })
    checks.append(check("login", status, payload, "user"))
    if status >= 400:
        print_report(checks)
        return 1

    client.token = payload["access_token"]
    for name, path in common_paths(args.country):
        print(f"checking {name}...", flush=True)
        status, payload = client.request("GET", path)
        checks.append(check(name, status, payload))

    status, payload = client.request(
        "GET",
        "/api/v1/articles?limit=3&q=makedonija&exact_phrase=true&min_reliability=0.4&sentiment=neutral",
    )
    checks.append(check("advanced_article_search", status, payload, "total"))

    status, saved_search = client.request(
        "POST",
        "/api/v1/saved-searches",
        {
            "title": "Smoke test search",
            "query": "makedonija",
            "filters": {"language": "mk", "date_basis": "published"},
        },
    )
    checks.append(check("saved_search_create", status, saved_search, "title"))
    if status == 200 and saved_search.get("id"):
        status, payload = client.request("GET", "/api/v1/saved-searches")
        checks.append(check("saved_search_list", status, payload))
        status, payload = client.request(
            "DELETE", f"/api/v1/saved-searches/{saved_search['id']}"
        )
        checks.append(check("saved_search_delete", status, payload, "status"))

    status, entities = client.request("GET", "/api/v1/entities?limit=1")
    if status == 200 and entities:
        entity_id = entities[0]["id"]
        status, payload = client.request(
            "GET", f"/api/v1/entities/{entity_id}/briefing?days=90"
        )
        checks.append(check("entity_briefing", status, payload, "headline"))

    status, payload = client.request(
        "GET", "/api/v1/topics/briefing?q=makedonija&country_code=mk&days=90"
    )
    checks.append(check("topic_briefing", status, payload, "headline"))

    status, clients = client.request("GET", "/api/v1/clients")
    if status == 200 and clients:
        chat_client = next((item for item in clients if item.get("plan") != "free"), clients[0])
        client_id = chat_client["id"]
        for name, path in client_paths(client_id):
            status, payload = client.request("GET", path)
            checks.append(check(name, status, payload))

        status, payload = client.request(
            "GET", f"/api/v1/clients/{client_id}/saved-topics?days=30"
        )
        checks.append(check("saved_topics", status, payload))

        status, payload = client.request(
            "GET", f"/api/v1/clients/{client_id}/saved-briefings?limit=5"
        )
        checks.append(check("saved_briefings", status, payload))

        status, payload = client.request(
            "POST",
            f"/api/v1/clients/{client_id}/chat",
            {
                "question": "What is the latest important coverage for this client?",
                "days": 30,
            },
        )
        checks.append(check("client_chat", status, payload, "answer"))
        if status == 200 and payload.get("conversation_id"):
            conversation_id = payload["conversation_id"]
            status, follow_up = client.request(
                "POST",
                f"/api/v1/clients/{client_id}/chat",
                {
                    "question": "Which sources support that answer?",
                    "days": 30,
                    "conversation_id": conversation_id,
                },
            )
            history_ok = (
                status == 200
                and follow_up.get("conversation_id") == conversation_id
                and follow_up.get("turn_number") == 2
                and len(follow_up.get("history", [])) >= 4
            )
            checks.append(check(
                "client_chat_follow_up",
                200 if history_ok else 500,
                follow_up,
                "conversation_id",
            ))
            status, transcript = client.request(
                "GET",
                f"/api/v1/clients/{client_id}/chat/conversations/{conversation_id}",
            )
            checks.append(check("client_chat_transcript", status, transcript, "messages"))

            other_client = next((item for item in clients if item["id"] != client_id), None)
            if other_client:
                status, denied = client.request(
                    "GET",
                    f"/api/v1/clients/{other_client['id']}/chat/conversations/{conversation_id}",
                )
                checks.append(check(
                    "client_chat_scope_isolation",
                    200 if status == 404 else 500,
                    denied if isinstance(denied, dict) else {"detail": str(denied)},
                    "detail",
                ))

        status, dashboard = client.request(
            "GET", f"/api/v1/clients/{client_id}/dashboard?days=30"
        )
        if status == 200 and dashboard.get("watchlist"):
            item_id = dashboard["watchlist"][0]["id"]
            for name, path in watchlist_paths(client_id, item_id):
                status, payload = client.request("GET", path)
                checks.append(check(name, status, payload))
                if name == "response_pack":
                    strategy = payload.get("response_strategy") if isinstance(payload, dict) else None
                    strategy_ok = isinstance(strategy, dict) and bool(strategy.get("primary_line")) and bool(strategy.get("publication_gate"))
                    checks.append(check(
                        "response_strategy",
                        200 if status == 200 and strategy_ok else 500,
                        strategy or {"error": "missing response_strategy"},
                        "public_posture",
                    ))

        party_client = next(
            (
                item for item in clients
                if item.get("client_type") == "political_party"
                or item.get("plan") == "campaign"
            ),
            clients[0],
        )
        party_client_id = party_client["id"]
        status, payload = client.request(
            "POST",
            f"/api/v1/clients/{party_client_id}/party-briefing",
            {
                "topic": "Македонија",
                "objective": "Prepare a factual update",
                "requirements": "Use only stored sourced coverage",
                "include_watchlist": True,
                "max_articles": 10,
            },
        )
        checks.append(check("party_briefing", status, payload))
        strategy = payload.get("briefing_strategy") if isinstance(payload, dict) else None
        strategy_ok = isinstance(strategy, dict) and bool(strategy.get("primary_line")) and bool(strategy.get("publication_gate"))
        checks.append(check(
            "party_briefing_strategy",
            200 if status == 200 and strategy_ok else 500,
            strategy or {"error": "missing briefing_strategy"},
            "public_posture",
        ))

    print_report(checks)
    return 1 if any(item["status"] >= 400 for item in checks) else 0


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token = None

    def request(self, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
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
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, TimeoutError):
                return 599, "request timed out"
            return 599, str(exc.reason)


def common_paths(country: str) -> list[tuple[str, str]]:
    quoted_country = urllib.parse.quote(country)
    return [
        ("articles", "/api/v1/articles?limit=3"),
        ("entities", "/api/v1/entities?limit=3"),
        ("trends", "/api/v1/trends?days=90&limit=3"),
        ("sources", "/api/v1/sources/stats?days=90"),
        ("story_clusters", f"/api/v1/story-clusters?country_code={quoted_country}&days=30&limit=3"),
        ("story_spread", f"/api/v1/story-spread?country_code={quoted_country}&days=30&limit=3"),
        ("risk", f"/api/v1/risk/political?country_code={quoted_country}&days=30"),
        ("daily_brief", f"/api/v1/briefs/daily?country_code={quoted_country}&days=1"),
        ("alerts", "/api/v1/alerts"),
        ("clients", "/api/v1/clients"),
        ("subscriptions", f"/api/v1/subscriptions?country_code={quoted_country}&limit=3"),
        ("source_health", f"/api/v1/admin/ingestion/source-health?country_code={quoted_country}"),
        ("source_reliability", f"/api/v1/admin/ingestion/source-reliability?country_code={quoted_country}&runs=3"),
        ("source_config_validation", f"/api/v1/admin/sources/config-validation?country_code={quoted_country}"),
        ("scheduler_status", f"/api/v1/admin/scheduler/status?country_code={quoted_country}"),
        ("live_ops", f"/api/v1/admin/live-ops?country_code={quoted_country}"),
        ("backups", "/api/v1/admin/backups"),
        ("launch_checklist", f"/api/v1/admin/launch-checklist?country_code={quoted_country}"),
        ("ops_fix_queue", f"/api/v1/admin/ops/fix-queue?country_code={quoted_country}&limit=5"),
        ("article_quality", f"/api/v1/admin/article-quality?country_code={quoted_country}&limit=3"),
        ("entity_quality", "/api/v1/admin/entities/quality-report?limit=50"),
        ("search_quality", f"/api/v1/admin/search/quality?country_code={quoted_country}"),
        ("entity_lexicon", f"/api/v1/admin/entities/lexicon-coverage?country_code={quoted_country}&limit=5"),
        ("intelligence_qa", f"/api/v1/admin/intelligence-qa?country_code={quoted_country}"),
        ("attack_review_queue", f"/api/v1/admin/attacks/review?country_code={quoted_country}&days=30&limit=5"),
        ("legal_quality", f"/api/v1/admin/legal/quality?country_code={quoted_country}"),
        ("legal_review_queue", f"/api/v1/admin/legal/review-queue?country_code={quoted_country}"),
        ("legal_docs", f"/api/v1/legal-documents?country_code={quoted_country}&limit=3"),
    ]


def client_paths(client_id: int) -> list[tuple[str, str]]:
    return [
        ("client_dashboard", f"/api/v1/clients/{client_id}/dashboard?days=30"),
        ("client_risk", f"/api/v1/clients/{client_id}/risk?days=30"),
        ("client_usage", f"/api/v1/clients/{client_id}/usage"),
        ("incidents", f"/api/v1/clients/{client_id}/incidents"),
    ]


def watchlist_paths(client_id: int, item_id: int) -> list[tuple[str, str]]:
    return [
        ("response_pack", f"/api/v1/clients/{client_id}/response-pack/{item_id}?days=30"),
        ("attack_timeline", f"/api/v1/clients/{client_id}/attack-timeline/{item_id}?days=30"),
    ]


def check(name: str, status: int, payload, key: str | None = None) -> dict:
    return {
        "name": name,
        "status": status,
        "summary": summarize(payload, key),
    }


def summarize(payload, key: str | None = None) -> str:
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    if isinstance(payload, dict):
        if key and key in payload:
            value = payload[key]
            if isinstance(value, dict):
                return ",".join(list(value.keys())[:5])
            return safe_console(str(value)[:80])
        return ",".join(list(payload.keys())[:5])
    return safe_console(str(payload)[:120])


def safe_console(value: str) -> str:
    """Keep smoke-test output printable in the default Windows console."""
    return value.encode("ascii", errors="replace").decode("ascii")


def print_report(checks: list[dict]):
    width = max(len(item["name"]) for item in checks) if checks else 10
    for item in checks:
        marker = "OK" if item["status"] < 400 else "FAIL"
        print(f"{marker:4} {item['name']:<{width}} {item['status']} {item['summary']}")
    failed = [item for item in checks if item["status"] >= 400]
    print(f"\nPassed: {len(checks) - len(failed)} / {len(checks)}")
    if failed:
        print("Failures: " + ", ".join(item["name"] for item in failed))


if __name__ == "__main__":
    sys.exit(main())
