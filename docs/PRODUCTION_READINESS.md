# NewsIntel Production Readiness

This checklist is for moving the local Macedonian news intelligence MVP toward a client-facing deployment.

## Environment

- Copy `.env.example` to `.env`.
- Use PostgreSQL for production-like deployments.
- Keep `SEED_ADMIN_PASSWORD` strong and rotate after first login.
- Set `TOKEN_EXPIRY_HOURS=8` to `12` for normal dashboard sessions.
- Set `CORS_ORIGINS` to the exact dashboard domains. Do not use `*`.
- Keep social/API tokens empty unless the integration is actively used.
- Set `INGESTION_INTERVAL_MINUTES=15` for near-real-time news monitoring.
- Keep `SMTP_ENABLED=false` until a real delivery test passes.
- Keep `AI_GROUNDING_REQUIRED=true` whenever production AI is enabled.
- Validate before demos or deployment:

```powershell
.\venv\Scripts\python.exe scripts\validate_env.py
```

For production CI/deployment checks:

```powershell
$env:APP_ENV="production"
.\venv\Scripts\python.exe scripts\validate_env.py --strict --check-db
```

Expected local warnings are SQLite, default/admin password, or incomplete SMTP. Production should have zero errors and ideally zero warnings.

## PostgreSQL Pilot Setup

Docker Compose can start the local development API, database, and ingestion worker:

```powershell
$env:POSTGRES_PASSWORD="replace-with-strong-password"
$env:SEED_ADMIN_PASSWORD="replace-with-long-admin-password"
$env:APP_ENV="production"
docker compose up --build
```

For a production-shaped deployment, use the production compose file:

```powershell
Copy-Item .env.production.example .env.production
# edit .env.production with real domains and secrets
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d
```

Production compose includes:

- PostgreSQL 16 with persistent volume.
- API without `--reload`, with multiple workers.
- Scheduler as a proper long-running `scripts/scheduler.py` process.
- Frontend built with Vite and served by Nginx.
- Healthchecks and service dependency ordering.
- Persistent `reports`, `data`, and `ml_models` volumes.

For production, set `DATABASE_URL` explicitly rather than relying on defaults:

```text
DATABASE_URL=postgresql://newsintel:replace-with-strong-password@db:5432/newsintel
```

Run the static repo readiness report before deployment:

```powershell
.\venv\Scripts\python.exe scripts\production_readiness_report.py
```

## Services

Run three long-lived processes:

- API: `venv\Scripts\python.exe -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000`
- Frontend: build with `npm run build`, then serve `frontend/dist` behind a reverse proxy.
- Scheduler: `powershell -File scripts\start_scheduler.ps1 -Country mk -IntervalMinutes 15 -NoEmail`
- Scheduler recovery: `powershell -File scripts\recover_scheduler.ps1 -Country mk -IntervalMinutes 15 -NoEmail`

For a first paid pilot, keep the scheduler in `-NoEmail` mode until SMTP is verified.

In Docker production mode, the equivalent services are `api`, `scheduler`, `frontend`, and `db`.

## Cloud Deployment Shape

Recommended first public setup:

- Managed PostgreSQL if possible, or the `db` service on a VPS for the first pilot.
- API container behind HTTPS at `https://api.yourdomain.com`.
- Frontend container or static hosting at `https://app.yourdomain.com`.
- Exact `CORS_ORIGINS=https://app.yourdomain.com`.
- Daily provider database snapshots plus `scripts/backup_database.py` before risky operations.
- Persistent volume or object storage for generated PDFs/reports.
- Scheduler enabled every 15 minutes after source health is stable.

Minimum cloud environment:

```text
APP_ENV=production
DATABASE_URL=postgresql://...
CORS_ORIGINS=https://app.yourdomain.com
VITE_API_BASE_URL=https://api.yourdomain.com
SEED_ADMIN_EMAIL=admin@yourdomain.com
SEED_ADMIN_PASSWORD=<strong secret>
POSTGRES_PASSWORD=<strong secret if using compose db>
```

## Data Operations

- Check Admin -> Source Health after every ingestion run.
- Treat sources marked `watch` or `broken` as operational tasks before client demos.
- Use Article Quality Audit to catch scraper pages that are not real articles.
- Rebuild story clusters after ingestion if the scheduler has not already done it.
- Back up the database daily before adding historical/backfill ingestion.
- Create a local SQLite backup:

```powershell
.\venv\Scripts\python.exe scripts\backup_database.py --label before-demo
```

- Preview restore steps without changing data:

```powershell
.\venv\Scripts\python.exe scripts\restore_database.py data\backups\YOUR_BACKUP.db
```

- PostgreSQL backups use `pg_dump` when available:

```powershell
.\venv\Scripts\python.exe scripts\backup_database.py --label before-backfill
```

Windows PostgreSQL client tools are discovered automatically from standard
PostgreSQL installation folders when they are not on `PATH`.

- Restores are deliberately plan-first. Only execute after stopping API/scheduler and making a fresh backup.

## Historical Ingestion

Historical ingestion should be planned before fetching:

```powershell
.\venv\Scripts\python.exe scripts\plan_historical_ingestion.py --country mk --date-from 2010-01-01 --target-per-source 1000 --max-per-run 250
```

Current state: the MK sources are good for live/current scraping, but true archive backfill still needs per-source `archive_urls` / archive selector configs. Do not market current listing/RSS ingestion as a 2010+ archive until those configs and bounded archive fetches are added.

Recommended historical sequence:

1. Add archive config for 3-5 strongest sources.
2. Run a bounded backfill for the last 2-3 years.
3. Backfill dossiers for key political figures and parties.
4. Expand older years only after duplicate rate and article quality are acceptable.

## Client Isolation

- Client users should only access their own client dashboard, reports, saved briefings, incidents, and alerts.
- Staff/admin users can manage all clients and subscriptions.
- Use separate demo clients for sales presentations rather than real customer data.

## Delivery

- Create digest subscriptions from the client Reports tab.
- Verify SMTP settings with a test recipient before enabling scheduler email delivery.
- Generated PDFs remain available through the Reports tab and should be reviewed before sending externally.

## Safety Language

- Briefings are communications intelligence, not legal advice.
- Legal references are research leads unless marked official or lawyer verified.
- Single-source claims must be treated as unverified.
- AI-generated or template-generated responses must be checked against source URLs before public use.

## Suggested Pilot Setup

- 15-20 reliable Macedonian sources active.
- Scheduler running every 15 minutes.
- At least 3 demo clients seeded: party, political figure, media analyst.
- One daily digest subscription per demo client.
- Smoke test passing before every demo: `venv\Scripts\python.exe scripts\smoke_test.py`.
- Dashboard benchmark passing below three seconds:
  `venv\Scripts\python.exe scripts\benchmark_dashboards.py`.
- Create real pilot accounts only from a reviewed YAML file using
  `scripts/create_pilot_client.py`; never expose named demo-account shortcuts.

## Public Launch Gate

Before real paying users:

- `scripts/production_readiness_report.py` passes.
- `scripts/validate_env.py --strict --check-db` passes against production env.
- `scripts/smoke_test.py --base-url https://api.yourdomain.com` passes.
- Admin can see scheduler fresh, source config healthy, search quality ready, and legal quality visible.
- Client users have been tested for client-data isolation.
- Database backup and restore plan have been tested.
- First historical/archive feature is labeled accurately: either live-monitoring only, recent backfill, or true archive.
