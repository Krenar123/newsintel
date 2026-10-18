# NewsIntel Owner Actions

The codebase can prepare and validate the platform, but it cannot create your
commercial accounts, approve legal advice, or choose your public identity. Do
these steps in order. Keep ingestion stopped until the production database is
ready.

## 1. Choose Hosting And Domains

Buy or prepare one cloud/VPS account and one domain. Create two DNS names:

- `app.yourdomain.com` for the dashboard
- `api.yourdomain.com` for the FastAPI service

Prefer a managed PostgreSQL database. Record the database host, database name,
username, password, and whether the provider requires SSL.

## 2. Create Production Secrets

Copy `.env.production.example` to a private `.env.production` file on the
server. Replace every `yourdomain.com` and `replace-with-...` value. Do not send
the completed file in chat and do not commit it to source control.

Keep these settings until each integration is tested:

```text
AI_GROUNDING_REQUIRED=true
ENABLE_AI_INTELLIGENCE=false
ENABLE_AI_SUMMARIES=false
SMTP_ENABLED=false
FACEBOOK_ACCESS_TOKEN=
```

## 3. Choose And Configure AI

Create an Anthropic API account and key if you want the currently implemented
provider. Put the key only in the production secret store:

```text
AI_PROVIDER=anthropic
AI_API_KEY=your-private-key
ENABLE_AI_INTELLIGENCE=true
AI_GROUNDING_REQUIRED=true
```

Then run:

```powershell
python scripts/verify_ai_grounding.py --require-provider
```

Do not enable AI for clients if that check rejects the provider response.

## 4. Appoint Macedonian Counsel

Choose a qualified lawyer in North Macedonia. Give them the packet under
`reports/legal-review`. In Admin, assign each legal reference with the lawyer's
real jurisdiction and qualification reference. Only the lawyer should approve
effective dates, corrections, and final legal status.

The response assistant is communications support, not a substitute for legal
advice.

## 5. Run The Release Gate

For local code checks:

```powershell
.\venv\Scripts\python.exe scripts\release_gate.py
```

For a running production rehearsal, store the password in the current terminal
and run the live checks:

```powershell
$env:NEWSINTEL_ADMIN_EMAIL="admin@yourdomain.com"
$env:NEWSINTEL_ADMIN_PASSWORD="your-private-admin-password"
.\venv\Scripts\python.exe scripts\release_gate.py `
  --base-url https://api.yourdomain.com `
  --check-active-env `
  --require-ai
```

After the release gate passes, test a backup and restore, create the first real
client and watchlist, and only then start the 15-minute scheduler. Social-media
ingestion remains parked until news quality is dependable.
