# NewsIntel Testing Runbook

Use these commands from the project root on Windows PowerShell.

## Start The App

```powershell
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
..\.tools\node-v24.14.1-win-x64\npm.cmd run dev
```

Dashboard: http://127.0.0.1:5173

API health: http://127.0.0.1:8000/health

## Fast Checks

```powershell
.\venv\Scripts\python.exe -m compileall src scripts
cd frontend
..\.tools\node-v24.14.1-win-x64\npm.cmd run build
```

## API Smoke Test

Start the API first, then run:

```powershell
.\venv\Scripts\python.exe scripts\smoke_test.py
```

Expected result: all checks show `OK` and the final line shows all checks passed.

## Scraper Checks

Check all configured Macedonian sources with a small sample:

```powershell
.\venv\Scripts\python.exe scripts\check_scrapers.py --country mk --max-articles 3
```

Check one source:

```powershell
.\venv\Scripts\python.exe scripts\check_scrapers.py --country mk --source "360 Stepeni" --max-articles 5
```

## Article Quality Audit

Dry-run only:

```powershell
.\venv\Scripts\python.exe scripts\audit_article_quality.py --country mk --limit 20 --delete
```

Apply cleanup only after reviewing the output:

```powershell
.\venv\Scripts\python.exe scripts\audit_article_quality.py --country mk --limit 20 --delete --apply
```

## Legal Research Leads

Dry-run starter legal references:

```powershell
.\venv\Scripts\python.exe scripts\seed_legal_references.py
```

Apply starter legal references:

```powershell
.\venv\Scripts\python.exe scripts\seed_legal_references.py --apply
```

These are research leads only. Keep them marked as needing review or official/lawyer verification before using them as legal claims.

## Scheduler

Run ingestion once:

```powershell
.\venv\Scripts\python.exe scripts\scheduler.py --country mk --interval-minutes 15 --run-once --no-email
```

Start continuous ingestion:

```powershell
.\scripts\start_scheduler.ps1 -Country mk -IntervalMinutes 15 -NoEmail
```
