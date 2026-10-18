# NewsIntel Pilot Operations

## Pilot Offer

Start with a 30-day paid pilot for one monitored organization or political
figure. The pilot includes the personalized dashboard, watchlists, source-backed
briefings, attack monitoring, saved cases, and reviewed PDF exports.

Suggested starting packages:

| Package | Intended user | Monthly price | Included |
| --- | --- | ---: | --- |
| Monitor | General client or diaspora organization | EUR 199 | Saved topics, summaries, source links, daily digest |
| Intelligence Pro | PR team, journalist, analyst | EUR 499 | Wider search, trends, source spread, alerts, briefings |
| Defense Desk | Political figure or party | EUR 999-1,999 | Personal watchlist, attack analysis, response prep, cases |
| Advisory | Due diligence or high-touch campaign | From EUR 5,000 | Custom scope, analyst support, reviewed reports |

Legal review and human communications advice are separate professional services.
AI-assisted drafts must never be represented as legal advice.

## Onboarding

1. Agree the client type, monitored names, aliases, opponents, topics, sources,
   languages, alert urgency, and which users may access broader research.
2. Copy `config/pilot/client_template.yaml` to a client-specific private file.
3. Replace every placeholder and review Cyrillic and Latin aliases.
4. Validate without writing:

```powershell
.\venv\Scripts\python.exe scripts\create_pilot_client.py path\to\client.yaml
```

5. Create the account using a password supplied through the environment:

```powershell
$env:PILOT_CLIENT_PASSWORD="<unique initial password>"
.\venv\Scripts\python.exe scripts\create_pilot_client.py path\to\client.yaml --apply --confirm CREATE_PILOT_CLIENT
```

6. Sign in as the client and confirm that another client's dashboard returns
   HTTP 403.
7. Review at least 20 matched articles and tune aliases before the kickoff call.
8. Configure alerts only after false-positive review.

## Daily Operations

- Confirm scheduler heartbeat is fresh and ingestion ran within 20 minutes.
- Review failed sources and article-quality exclusions.
- Review high-risk signals before notifying a client.
- Keep single-source allegations visibly marked.
- Check citations before approving response or press-conference drafts.
- Record any legal question in the counsel review queue.

## Demo Gate

Run:

```powershell
.\venv\Scripts\python.exe scripts\smoke_test.py --base-url http://127.0.0.1:8000
.\venv\Scripts\python.exe scripts\benchmark_dashboards.py --base-url http://127.0.0.1:8000
.\venv\Scripts\python.exe scripts\pilot_readiness_report.py
```

The demo is ready when the API smoke test passes, every cold dashboard is below
three seconds, the scheduler is fresh, and client isolation has been browser-tested.

## Support Procedure

- Severity 1: login, data isolation, or complete ingestion failure. Respond
  immediately and disable affected access if privacy is uncertain.
- Severity 2: stale dashboard, broken priority source, or incorrect critical
  entity. Respond the same business day.
- Severity 3: minor UI, source metadata, or report-format issue. Include in the
  next maintenance release.
- Never delete source evidence to hide a bad extraction. Exclude it from active
  intelligence and keep the audit trail.
