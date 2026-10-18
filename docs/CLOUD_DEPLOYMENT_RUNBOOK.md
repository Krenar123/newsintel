# NewsIntel Cloud Deployment Runbook

This is the practical path from local dev to a first public/pilot deployment.

## Target Architecture

- Frontend: Vite build served by Nginx at `https://app.yourdomain.com`.
- API: FastAPI/Uvicorn at `https://api.yourdomain.com`.
- Database: managed PostgreSQL preferred; Docker Postgres acceptable for a first small VPS pilot.
- Scheduler: one long-running worker using `scripts/scheduler.py` every 15 minutes.
- Storage: persistent volume or object storage for PDFs, reports, and backups.
- Backups: daily provider snapshots plus manual backup before historical ingestion.

## First Deployment

1. Create production secrets from `.env.production.example`.
2. Set exact public URLs:
   - `PUBLIC_FRONTEND_URL`
   - `PUBLIC_API_URL`
   - `CORS_ORIGINS`
   - `VITE_API_BASE_URL`
3. Use strong values for:
   - `POSTGRES_PASSWORD`
   - `SEED_ADMIN_PASSWORD`
   - SMTP credentials, if email is enabled
   - `AI_API_KEY`, if production AI is enabled
4. Keep these safety switches explicit:
   - `AI_GROUNDING_REQUIRED=true`
   - `SMTP_ENABLED=false` until delivery is tested
5. Start the production stack:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d
```

6. Validate the environment:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml exec api python scripts/validate_env.py --strict --check-db
```

7. Run smoke test from your local machine against the public API:

```powershell
.\venv\Scripts\python.exe scripts\smoke_test.py --base-url https://api.yourdomain.com --email admin@yourdomain.com --password YOUR_ADMIN_PASSWORD
```

## Before Enabling Paying Users

- Admin login works through the public frontend.
- API smoke test passes.
- Scheduler heartbeat is fresh in Admin.
- Source config validation has no critical issues.
- Search quality is `ready`.
- Legal readiness is visible and still marks research-lead areas clearly.
- Client users only see their own client workspace.
- A database backup exists and a restore plan has been reviewed.
- SMTP is tested before enabling digest email.
- Every personalized dashboard passes the three-second benchmark.
- Invalid logins are throttled and cross-client dashboard access returns 403.

## Historical Data Rollout

Do not run a huge archive fetch first.

1. Plan the current gap:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml exec api python scripts/plan_historical_ingestion.py --country mk --date-from 2010-01-01 --target-per-source 1000
```

2. Add archive configs source by source.
3. Backfill the last 2-3 years for 3-5 reliable sources.
4. Build political figure and party dossiers from those years.
5. Expand older years only after duplicate rate and article quality are acceptable.

## Backup

Before deployments, source-config changes, or historical ingestion:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml exec api python scripts/backup_database.py --label before-change
```

Preview restore steps:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml exec api python scripts/restore_database.py data/backups/YOUR_BACKUP_FILE
```

Only execute restore after stopping API/scheduler and creating a fresh backup.

## Rollback

1. Stop scheduler first to prevent new writes:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml stop scheduler
```

2. Keep API available if the issue is only ingestion/reporting.
3. If database restore is needed, stop API too and follow the restore plan.
4. Restart in order: `db`, `api`, `frontend`, `scheduler`.
5. Run smoke test again.

## Ongoing Operations

- Check Admin Fix Queue daily.
- Check Source Health after ingestion changes.
- Keep scheduler interval at 15 minutes unless sources start rate-limiting.
- Review legal references before enabling legal-heavy response features for a real client.
- Keep Facebook/social integrations parked until news ingestion is stable in production.
