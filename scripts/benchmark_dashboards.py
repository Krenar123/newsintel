#!/usr/bin/env python3
"""Measure cold and cached client-dashboard response times."""

import argparse
import sys
import time
import urllib.error
import urllib.request
import json


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Benchmark every client dashboard")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@newsintel.local")
    parser.add_argument("--password", default="ChangeMe123!")
    parser.add_argument("--target-seconds", type=float, default=3.0)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    login = request_json(
        f"{args.base_url}/api/v1/auth/login",
        method="POST",
        payload={"email": args.email, "password": args.password},
    )
    token = login["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    clients = request_json(f"{args.base_url}/api/v1/clients", headers=headers)

    failures = []
    print("client | cold | cached | cache")
    for client in clients:
        url = (
            f"{args.base_url}/api/v1/clients/{client['id']}/dashboard"
            f"?days={args.days}"
        )
        started = time.perf_counter()
        cold_payload = request_json(f"{url}&refresh=true", headers=headers)
        cold = time.perf_counter() - started

        started = time.perf_counter()
        cached_payload = request_json(url, headers=headers)
        cached = time.perf_counter() - started
        cache_status = cached_payload.get("metrics", {}).get("cache_status", "unknown")
        print(
            f"{client['id']:>2} {client['name'][:28]:<28} | "
            f"{cold:>6.3f}s | {cached:>6.3f}s | {cache_status}"
        )
        if cold > args.target_seconds:
            failures.append((client["id"], client["name"], cold))
        if not cold_payload.get("client"):
            failures.append((client["id"], client["name"], "invalid payload"))

    if failures:
        print(f"\nFAIL: {len(failures)} dashboard benchmark issue(s): {failures}")
        return 1
    print(f"\nPASS: every cold dashboard loaded within {args.target_seconds:.1f}s")
    return 0


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict | None = None,
):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
