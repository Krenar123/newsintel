# NewsIntel Build Progress

Last updated: 2026-08-12

## Visual And Workflow Checkpoint - 2026-08-12

- Replaced the blue/teal gradient-heavy dashboard theme with a flat editorial
  intelligence palette: charcoal navigation, warm neutral canvas, white working
  surfaces, evergreen actions, amber caution, and brick-red verified risk states.
- Removed all CSS gradients and old blue AI-theme tokens from the frontend.
- Added accessible keyboard focus treatment, reduced-motion support, and neutral
  browser-autofill styling.
- Added a shared 7/30/90-day coverage window to every client dashboard. Dashboard
  data and metric captions now follow the selected period.
- Replaced misleading political-figure wording such as `Today` with `Current
  evidence` and `Selected window`.
- Clamped article titles and summaries in list views so clients can scan coverage
  without opening a page made of full article-length text.
- Fixed mobile refresh sizing and metric-label wrapping; visual inspection at
  390px and 1280px found no horizontal overflow.

Verification: frontend production build passed, Python tests passed `21 / 21`,
political-figure desktop/mobile browser checks passed `2 / 2`, and the full
desktop role/permission workflow passed `11 / 11`.

## Authoritative Checkpoint - 2026-08-07

This is the current resume point. News intelligence remains the product focus,
social-media ingestion remains parked, and the scheduler is intentionally
stopped until the production database is selected and ready.

### Completed In This Build

- Added private saved searches for every authenticated user:
  - search text, dates, source, entity, language, sentiment, reliability, and
    exact-match settings can be saved and reopened
  - saved searches are owned by one user and cannot be read or edited by another
  - the global search bar now opens the evidence-first article search flow
- Improved role workspaces for parties, PR agencies, journalists, analysts, and
  diaspora/general clients:
  - workflow cards are real actions rather than explanatory decoration
  - each role can start its most useful assistant question, open its source trail,
    and move directly to risks or saved work
  - client accounts keep their permission-scoped assistant and do not receive the
    unrestricted staff search box
- Added an audited attack-review system:
  - admin can confirm, correct, or reject detected attacks
  - corrections can replace attacker, target, allegation, categories, and notes
  - rejected detections disappear from client risk, response, timeline, and brief
    views while the original machine output remains auditable
  - dashboard caches are invalidated after review decisions
- Hardened search and SQLite development performance:
  - trending calculations bound candidate IDs before period comparison
  - search-quality checks use bounded existence queries
  - attack-review candidates are limited to active response-assist entities and
    bounded recent evidence
- Added a safe release gate at `scripts/release_gate.py`:
  - validates production assets, Python tests, frontend build, and AI grounding
  - optionally runs live smoke, pilot-readiness, environment, and dashboard-speed
    checks
  - never ingests, restores, deploys, emails, or activates social media
- Added `docs/OWNER_ACTIONS.md` with simple instructions for hosting, domains,
  secrets, AI activation, Macedonian legal counsel, and final release checks.
- Updated local CORS defaults for both Vite ports 5173 and 5174.

### Verification

- Python tests: `21 passed`
- API smoke test: `51 / 51 passed`
- Static production readiness: `18 / 18`, zero warnings
- Frontend production build: passed
- Focused browser checks:
  - political figure desktop and mobile: `2 passed`
  - party, PR agency, journalist, analyst, and diaspora desktop: `5 passed`
  - admin legal and attack-review controls: `1 passed`
  - private bilingual saved-search workflow: `1 passed`
- Visual browser inspection passed for the personalized Mickoski workspace:
  critic, allegation, portal spread, evidence, actions, and recent mentions are
  clear in the first decision view with no visible desktop overlap.
- The complete single-worker role matrix still exceeds the aggregate timeout on
  the large SQLite development database. Individual role tests pass; PostgreSQL
  remains the production performance path.

### Owner/External Gates

1. Choose the cloud/VPS, domain names, and managed PostgreSQL service.
2. Create production secrets outside source control.
3. Add a real AI provider key and run the grounding gate before enabling AI for
   clients.
4. Have a qualified Macedonian lawyer review and sign off critical legal texts.
5. Configure the first real client accounts and watchlists, run backup/restore and
   public HTTPS smoke tests, then start the 15-minute scheduler.

See `docs/OWNER_ACTIONS.md` for exact commands. Do not start Facebook/social
ingestion until the news product is dependable under pilot use.

## Verified Checkpoint - 2026-07-16 Late Session

This is the current resume point. News remains the product focus; social ingestion is still intentionally deferred.

### Completed In This Build

- Continuous data operation:
  - local database reached 2,460 stored articles with 0 unprocessed immediately before the next live cycle
  - scheduler is running every 15 minutes and now writes its real PID for dashboard start/stop controls
  - shared `ingestion_job.lock` prevents scheduler, run-once, and manual processing jobs from writing SQLite concurrently
  - a second operation now exits cleanly with code 2 and a useful message instead of causing `database is locked`
  - stale scheduled runs are marked `interrupted` on safe scheduler recovery instead of remaining `running` forever
  - SQLite connections now wait up to 60 seconds for short write contention
  - direct scraper discovery now removes already-stored URL and trailing-slash variants before downloading article pages
  - verified optimized live run 12: completed in 122 seconds versus 19 minutes for the previous fetch-first cycle; 444 raw checks, 5 new, 246 duplicates, 0 errors, 27 caught-up sources, 0 attention sources
- Scraper/data repair:
  - article extraction removes related/recommended/share/comment/ad blocks before text extraction
  - corrected focused selectors for Makfax and Sloboden Pechat; verified Gazeta Lajm contamination removal
  - refreshed affected stored source content, reprocessed summaries/entities, reconciled entity statistics, and rebuilt story clusters
  - current recent cluster build: 1,248 article links across 1,106 clusters
  - 29 source records are present; 28 are active and the parked source remains explicit
- Intelligence quality:
  - entity acceptance set passes 21/21 with 100% precision/recall/F1 and no forbidden entities
  - structured attack-understanding set passes 6/6
  - chat now stores conversations and returns permission-scoped, citation-backed answers
  - attack records carry attacker, target, allegation, quote when present, reporting source, spread, and confidence
- Client experience:
  - named-person demo shortcuts were removed from login; workspace selection explains the role but credentials control access
  - political-figure workspace is personalized and focused on what happened, who/where, why, urgency, evidence, response, and saved cases
  - role navigation is compact and responsive with no horizontal overflow at the tested mobile viewport
  - non-client/admin readiness panels no longer leak into political-figure workspaces
- Historical ingestion foundation:
  - archive-capable WordPress configuration added for 360 Stepeni, Sloboden Pechat, Meta.mk, and Portalb
  - `scripts/ingest_historical_entity.py` supports source allowlists, named entity/query, date range, bounded limits, duplicate stopping, dry-run by default, backup confirmation, and optional processing
  - verified dry-run for `Христијан Мицкоски` on Meta.mk in 2020: 83 archive matches, 3 oldest candidates selected, 0 writes
- Legal trust workflow:
  - added immutable `legal_reviews` audit records with reviewer identity/organization, decision, previous/new status, notes, and timestamps
  - ordinary legal-document create/update routes cannot silently grant `lawyer_verified`
  - admin-only review queue, review history, and audited decision endpoint are live
  - analyst access to the review queue returns 403; attempted direct lawyer-verified creation returns 400 and saves nothing
  - admin dashboard exposes the audited review form; 11 references are stored, 6 need review, and 0 are falsely marked lawyer verified
- Testing/security:
  - API smoke test passes 47/47
  - Playwright desktop/mobile suite covers identity-safe login, personalized political workspace, responsive overflow, audited legal UI, and legal queue role denial
  - complete Playwright suite passes 8/8 in one serial run across desktop Chromium and mobile Chromium
  - production dependency audit reports 0 vulnerabilities; Vite updated to 7.3.6
  - Python compile, frontend production build, entity tests, attack tests, and production readiness report all pass
  - production readiness assets remain 0 errors, 0 warnings, 16 checks OK
  - online SQLite backup `newsintel-live-rehearsal-20260716_233108.db` passed `PRAGMA integrity_check`, contains 2,485 articles, and produced the expected safe restore plan
  - fresh in-memory database creation passes for all 24 tables after removing a duplicate article-quality index declaration
  - URL-filter regression tests pass 2/2

### Live State At Handoff

- API: `http://127.0.0.1:8000`, healthy after restart.
- Frontend: `http://127.0.0.1:5173`.
- Scheduler: tracked and running every 15 minutes; optimized run 12 completed successfully at `2026-07-16T23:41:46Z`.
- Database after run 12: 2,490 stored articles and 0 unprocessed.
- Local environment warnings are expected: SQLite is development-only, SMTP is incomplete, AI summaries are disabled, and production secrets are not set.
- Docker is not installed on this Windows workstation, so production Compose execution remains a deployment-stage rehearsal item; static Compose/readiness validation passes.

### Exact Next Checkpoint

1. Add real official legal texts and route the six-item review queue through qualified Macedonian counsel; never self-mark lawyer verification.
2. Run small, backed-up historical batches for priority figures/parties, review extraction/entity quality, then expand the batch size.
3. Rehearse Postgres migration, backup/restore, scheduler recovery, and monitoring with production-shaped environment variables.
4. Improve dashboard query performance and split the large frontend bundle before a public pilot.
5. Expand role-level browser tests for party, PR agency, journalist/analyst, and diaspora daily workflows.
6. Add Facebook/social ingestion only after the news, history, permissions, and legal-review workflows stay dependable under pilot use.

## Current Direction

Build the news/web intelligence platform first. Social media/Facebook/Telegram/YouTube are intentionally parked until the core news product is reliable enough to demo and sell.

## Completed Recently

- Expanded Albanian-language North Macedonia coverage:
  - confirmed Portalb and Zhurnal were already configured and kept their existing source records
  - added Tetova Sot, Gazeta Lajm/LajmPress, Almakos, INA Online, Koha, Flaka, Top24, FOL, E-Gazeta, Nistori, and Lajme.mk
  - classified Lajme.mk as an aggregator so it signals amplification but does not count as independent confirmation
  - verified ten live RSS feeds; Lajme.mk is scraper-only because it does not expose a working feed
  - ran three-article direct-scraper preflights for all eleven new entries: 33/33 articles extracted successfully
  - every sampled article supplied a publication date and image after adding schema.org JSON-LD metadata extraction
  - added source-specific minimum-average-word handling for legitimate short-news portals without weakening global extraction thresholds
  - extended scraper preflight diagnostics with publication-date, author, and image coverage; missing publication dates now degrade source health
  - synced the source YAML into the local database: 11 sources created, 18 unchanged, 29 configured total, 28 active
  - source config validation: 28 healthy, 0 warnings, 0 critical, 1 intentionally disabled; DB-only count 0
  - Python compile and API smoke test `43 / 43` passed after the scraper/config changes
  - no article ingestion was run in this slice; next operation should be a bounded ingestion cycle followed by backlog processing and quality review

- Hardened live MK ingestion after a full scheduler run:
  - triggered scheduler run-once from the API: run `6`, completed, 576 raw items, 119 new articles, 202 exact duplicates, 12 fuzzy duplicates, 0 errors
  - verified live scheduler duplicate-stop: 12 sources stopped early once caught up
  - processed 200 queued articles with 0 processing errors; smoke watchlist alert triggered once
  - added scraper bad-content detection for subscriber/paywall pages, including MIA subscriber notices
  - added source-specific bad-title/bad-content support to scraper quality checks
  - tightened TV21 filters for horoscope/programme URLs and titles
  - tightened Telma filters for horoscope, TV-novela, episode, and schedule-listing URLs/titles
  - switched MIA direct scraping off for the pilot because direct story pages can be subscriber-only; RSS remains active
  - targeted-cleaned historical active data: excluded 11 MIA paywall notices and 25 TV21/Telma non-news listing pages while preserving rows for audit
  - adjusted article quality audits so RSS briefs use RSS-appropriate thresholds while scraped articles still require full article text
  - excluded 1 remaining thin Zhurnal RSS sports snippet from active intelligence
  - rebuilt story clusters after cleanup: 555 active recent articles considered, 516 clusters created
  - verified TV21 scraper healthy, Telma scraper healthy, MIA scraper intentionally disabled/RSS-only
  - current article quality audit: 0 active suspects
  - reviewed entity quality: hid noise entities `украинскиот` and `досега`; approved legitimate institution `Министерство за образование и наука`
  - current pilot readiness: 0 failures, 0 warnings, 10 passes; Intelligence QA `100/100`; scheduler fresh; source health healthy; launch checklist `ready`
  - verified smoke test `40 / 40`, production readiness assets `0 errors / 0 warnings / 16 ok`, Python compile, and API health
- Added briefing/response decision gates for safer party and political-figure workflows:
  - party briefing outputs now show a Briefing Readiness panel with evidence depth, citation trail, claim support, legal posture, and a clear safe-use decision
  - response pack drawers now show a Response Decision Gate with evidence status, open claims, legal review blockers, draft status, and hold/cautious/usable guidance
  - demo War Room briefing output also shows the same readiness gate so demos do not bypass verification language
  - copy-to-clipboard text for party briefings and response packs now includes confidence score and source/article depth
  - verified frontend build, smoke test `40 / 40`, and pilot readiness `0 failures / 0 warnings / 10 passes`
- Added source-grounding contract to assistant outputs:
  - backend party briefings and response packs now return `grounding_contract` with decision (`ready`/`caution`/`hold`), public-use guidance, evidence readiness, citation readiness, unsupported claim count, single-source count, legal-review count, blocked claims, caution claims, and exact-use rules
  - PDF party briefing and response pack exports now include a Grounding Contract section so reports carry the same fact-safety status as the UI/API
  - frontend API types now include `GroundingContract` for party briefings and response packs
  - verified Python compile, frontend build, API restart, smoke test `40 / 40`, pilot readiness `0 failures / 0 warnings / 10 passes`, direct API contract check (`hold`, 10 articles, 4 sources, 6 citations), and PDF export `reports/party_briefing_4_export_20260626_083940.pdf`
- Built the next five dashboard workflow improvements:
  - added a saved briefing/case board with search, status/type/folder filters, open/duplicate/export actions, saved-work counts, and grounding-status badges
  - added a 10-minute press-conference prep runway to the party War Room, showing objective setup, evidence generation, risk clearing, and export/copy/save actions
  - strengthened the political-figure dashboard as a defense desk with mention counts, attack-signal totals, response-pack actions, timeline actions, and case-saving from top risk items
  - exposed grounding contracts in party briefing outputs, response pack drawers, saved briefing detail, and saved-work board summaries
  - added an operational freshness/reliability panel to Overview with scheduler cadence, next run, duplicate-stop status, source health, article-quality flags, and start/run-once actions for admins
  - verified frontend build, API smoke `40 / 40`, frontend HTTP `200`; pilot readiness is `0 failures / 2 warnings / 8 passes` because scheduler freshness is stale at 121 minutes and launch checklist follows that stale-scheduler warning
- Restored live scheduler freshness and added post-ingestion operator workflow:
  - triggered scheduler run-once from the API: run `7`, completed at `2026-06-26T12:21:24.621904`, 18 sources, 560 raw items, 177 new articles, 201 exact duplicates, 14 fuzzy duplicates, 0 errors
  - duplicate stopping worked: 8 sources caught up during the run
  - inspected post-run quality: source attention 0, article quality 1 thin RSS issue, entity quality 0 suspicious
  - excluded thin Zhurnal RSS article `1816` from active intelligence while preserving it for audit
  - adjusted operations fix queue so disabled/parked sources and intentionally parked social-media no-post rows do not appear as news-pilot P1 cleanup work
  - added Overview/Admin Post-Ingestion Cleanup panel with source drilldown, article approve/exclude, entity hide, and bulk-exclude actions
  - added last-run detail strip to the operations freshness panel showing run id/status, raw/new/duplicate/error counts, and finish time
  - final state: live ops `healthy`, ops fix queue `0`, launch checklist `ready`, pilot readiness `0 failures / 0 warnings / 10 passes`, smoke `40 / 40`, frontend HTTP `200`
- Added a claim support matrix for party briefings and response packs.
- Claim support statuses now classify requested claims as:
  - `source_supported`
  - `single_source`
  - `unsupported_by_current_data`
  - `legal_review_required`
- Party briefing and response pack UIs now show claim support, source count, article count, legal-review requirement, and safe-use guidance.
- Unsupported/legal-review claims are automatically added to verification and do-not-say guidance.
- Added Admin entity lexicon coverage:
  - backend endpoint `/api/v1/admin/entities/lexicon-coverage`
  - frontend Admin panel showing known/matched/missing/uncovered entities
  - high-mention DB entities not yet in the curated YAML
  - curated YAML entities missing from the current DB
- Added safe Admin "Add to Lexicon" workflow:
  - backend endpoint `/api/v1/admin/entities/{entity_id}/add-to-lexicon`
  - YAML duplicate detection before writing
  - automatic config backup before lexicon changes
  - optional DB entity approval after lexicon add
  - frontend action in the Lexicon Coverage panel
- Expanded `config/entities/north_macedonia.yaml` from 29 to 67 unique canonical entities.
- Added Latin aliases for major Macedonian politicians, parties, institutions, and municipalities.
- Validated the lexicon has zero duplicate canonical names.
- Added local source config validation:
  - backend endpoint `/api/v1/admin/sources/config-validation`
  - validates YAML names, URLs, RSS feed URLs, scraper listing URLs, selectors, reliability score, DB sync
  - frontend Admin "Config Validation" panel with healthy/warning/critical/disabled counts
  - top issue drilldown with suggested fixes and one-click scraper preflight where DB source exists
- Fed source config validation into launch/demo readiness:
  - launch checklist now fails on critical source config issues
  - Intelligence QA now includes a Source Configuration check
  - frontend QA status pills render `fail` distinctly
- Added safe source sync from YAML to DB:
  - backend endpoint `/api/v1/admin/sources/sync-from-config`
  - creates/updates DB source rows from country YAML
  - never deletes DB-only sources
  - frontend button in Admin Config Validation panel
- Added daily operations fix queue:
  - backend endpoint `/api/v1/admin/ops/fix-queue`
  - combines source config, ingestion source health, article quality, and entity quality issues
  - priorities use P0/P1/P2 so admin can see what blocks demos first
  - frontend Admin "Fix Queue" panel with quick source drilldown and entity-hide actions
- Strengthened party/response assistant evidence handling:
  - `citation_pack` now returned by party briefings and response packs
  - citations include labels like `[S1]`, source, date, URL, claim, reliability, and safe-use warning
  - frontend shows Citation Pack sections in party briefing and response pack drawers
  - copy-to-clipboard output now includes citation labels and URLs
- Updated PDF exports:
  - party briefing PDFs include Citation Pack after Source-Backed Evidence
  - response pack PDFs include Citation Pack after Source-Backed Evidence
  - verified by generating `reports/party_briefing_4_makedonija_20260623_125313.pdf`
- Added reusable press-conference prep workflow:
  - backend PATCH `/api/v1/clients/{client_id}/saved-briefings/{briefing_id}` for saved prep edits
  - backend POST `/api/v1/clients/{client_id}/saved-briefings/{briefing_id}/duplicate` for reusable template copies
  - frontend saved briefing detail can edit title/topic and duplicate a saved briefing
  - party briefing UI now has reusable templates: Factual Press Conference, Attack Response, Legal Review Hold, Campaign Announcement
  - verified via API create/duplicate/update: created saved briefing #1, duplicated #2, updated title/topic
- Added role-specific dashboard polish:
  - persistent Workspace Mode strip under the topbar
  - Admin shows Platform Control Room with fix queue/source validation/scheduler/backups cues
  - Analyst shows Research and Source Intelligence with search/story/entity/trend cues
  - Client users inherit persona-specific mode text from political party, political figure, journalist, media analyst, business risk, diaspora, or fallback config
  - responsive CSS added for the mode strip
  - frontend build passed; in-app browser visual check still blocked by local browser asset error `os error 3`
- Hardened scraper preflight and MK source reliability:
  - CLI/API preflight now records failed URLs, failure details, min/max word counts, and stricter degraded status rules
  - frontend scraper preflight drawer now shows failed URL drilldown and shortest successful extraction
  - Balkan Insight direct scraper disabled for now because its country listing exposes thin `techresponses` pages; RSS remains enabled/reliable
  - latest scraper check: active direct scrapers healthy; Fokus/TIME/Balkan Insight disabled intentionally; MIA healthy in latest sample
  - compile/build passed after the changes
- Added live scheduler/ingestion operations summary:
  - backend `GET /api/v1/admin/live-ops` combines scheduler freshness, heartbeat, process state, last run, duplicate stopping, and source attention
  - dashboard Admin now has a "Continuous Ingestion" card with cadence, freshness, duplicate-stop threshold, attention sources, and operator notes
  - smoke test now covers `live_ops`
  - verified compile/build and smoke: `38 / 38`
- Improved entity data quality and trend cleanliness:
  - entity validator now catches social-share widgets (`Telegram Viber Share`, `Facebook X WhatsApp`, `Telegram Pinterest`), UI fragments (`LEXO`, `Spotify`), date fragments, initials, and several MK/Albanian generic topic fragments
  - corrected Latin/Albanian place variants like `Shkup`, `Tetovës`, `Rusia`, and `SHBA` to location handling
  - added backend `POST /api/v1/admin/entities/merge-lexicon-aliases` with dry-run support and alias-chain resolution
  - Admin Entity Review panel now has "Merge Lexicon Aliases" beside "Auto-hide Noise"
  - applied cleanup locally: 31 lexicon alias entities merged and 43 noisy entities hidden; trend list now shows canonical entities instead of share-widget noise
  - entity quality report reduced to 1 suspicious item in the latest 500-entity sample
  - verified compile/build and smoke: `38 / 38`
- Added legal-library readiness monitoring:
  - backend `GET /api/v1/admin/legal/quality` summarizes legal reference coverage by source status and legal area
  - Admin dashboard now has a Legal Readiness card showing total references, official/verified count, lawyer-verified count, review backlog, coverage areas, and recommendations
  - smoke test now covers `legal_quality`
  - verified compile/build and smoke: `39 / 39`
- Polished client-facing PDF exports:
  - party briefing, response pack, client daily brief, and entity dossier PDFs now start with an executive snapshot
  - added a visible evidence/legal guardrail box near the top of each export
  - citation packs now render as structured tables with label, claim/use, source, date, and URL
  - party and response PDFs now include the claim support matrix
  - party PDFs now include "Do Not Say Unless Verified" guidance
  - source trails now render as source/date/title/URL tables with published and fetched dates
  - footer now labels reports as source-backed intelligence
  - verified compile, smoke `39 / 39`, and generated sample PDFs:
    - `reports/party_briefing_4_export_20260624_073849.pdf`
    - `reports/entity_briefing_export_20260624_073907.pdf`
    - `reports/response_pack_4_client_reputation_and_criticism_20260624_073918.pdf`
- Improved saved briefing organization and export:
  - saved briefings now support status, folder, tags, and internal notes
  - local SQLite auto-upgrade adds the new saved-briefing columns and indexes on startup
  - saved-work list defaults to active/pinned items while keeping archived items available by filter
  - dashboard saved briefing detail can edit title, topic, folder, status, tags, and notes
  - dashboard saved briefing detail can export a saved item directly to PDF
  - backend `POST /api/v1/clients/{client_id}/saved-briefings/{briefing_id}/report` exports saved party briefings, response packs, daily briefs, topic briefings, entity dossiers, and generic prep templates
  - verified saved template update/export with `reports/client_daily_brief_4_newsintel_demo_pr_agency_desk_20260624_074616.pdf`
  - verified compile, frontend build, and smoke: `39 / 39`
- Added production readiness foundation:
  - configurable `CORS_ORIGINS` and `TOKEN_EXPIRY_HOURS`
  - API token expiry now uses settings instead of a hardcoded 12 hours
  - shared logging setup for API, scheduler, and ingestion CLI with JSON logs in production
  - `scripts/validate_env.py` checks production-sensitive settings: database, default admin password, CORS, token expiry, ingestion cadence, SMTP, paths, and optional integrations
  - `scripts/backup_database.py` creates SQLite backups locally and uses `pg_dump` for PostgreSQL when available
  - `scripts/restore_database.py` provides restore plans by default and requires explicit confirmation before execution
  - `.env.example`, `docker-compose.yml`, and `docs/PRODUCTION_READINESS.md` updated for Postgres, safer secrets, 15-minute worker cadence, validation, and backup/restore operations
  - verified compile, frontend build, environment validator, real SQLite backup, restore dry-run, API health, and smoke: `39 / 39`
- Added scraper reliability and TIME.mk aggregator hardening:
  - `scripts/check_scrapers.py` now supports UTF-8 Windows output, `--fail-on-problems`, failed URL drilldown, min/max word diagnostics, and suggested fixes
  - active scraper health now fails CI/operator checks when an enabled source is degraded, failing, has no links, or throws an error
  - MIA now has source-specific article quality thresholds for legitimate short wire items instead of weakening global quality rules
  - added `src/ingestion/time_mk.py` as a dedicated TIME.mk cluster/source parser so TIME is used as a story-spread validation layer, not as an original article source
  - added `scripts/check_time_aggregator.py` to verify live TIME.mk clusters, reported counts, article references, source names, and summary/related-topic links
  - verified live TIME.mk parsing against the front page and verified the active MK scraper gate: active sources healthy; TIME.mk/Fokus/Balkan Insight direct scrapers remain intentionally disabled where appropriate
- Added search/data-quality readiness monitoring:
  - backend endpoint `GET /api/v1/admin/search/quality` checks missing normalized `search_text` for articles/entities and runs Macedonian Latin/Cyrillic demo query probes
  - Admin dashboard now shows live Cyrillic/Latin search readiness with article/entity counts, search-index gaps, query pass/warn cards, recommendations, and the backfill command
  - smoke test now covers `search_quality`
  - fixed article-quality audit compatibility with source-specific `min_unique_words`, which restored launch checklist, operations fix queue, intelligence QA, entity briefing, and topic briefing endpoints after API restart
  - verified search readiness locally: status `ready`, 0 article gaps, 0 entity gaps; `makedonija/македонија`, `skopje/скопје`, `vmro/вмро`, and `dui` all pass
  - verified compile, frontend build, API restart, and smoke: `40 / 40`
- Strengthened Macedonian legal knowledge readiness:
  - added required legal coverage tracking for constitution/institutions, defamation/media, elections/campaigns, criminal allegations/procedure, anti-corruption/conflict of interest, public information, and legal aid
  - backend `GET /api/v1/admin/legal/quality` now returns `required_coverage` and `coverage_summary` with `covered`, `research_lead`, and `missing` statuses
  - Admin Legal Readiness card now shows required legal coverage cards with official/reference counts and top references
  - expanded `scripts/seed_legal_references.py` with six cautious research leads: civil liability/defamation, Electoral Code, criminal law/procedure, anti-corruption/conflict of interest, free access to public information, and media/audiovisual regulation
  - seed dedupe now uses title+country so multiple legal topics can point to the same official legal database without being skipped
  - applied legal seed locally: 6 inserted, 5 skipped existing
  - current local legal readiness: 11 total references, 0 missing required coverage areas, 3 covered areas, 4 research-lead areas, overall `needs_review` until exact official texts or counsel verification are added
  - verified compile, frontend build, API restart, and smoke: `40 / 40`
- Tightened party/politician response assistant legal safeguards:
  - legal context items now include `legal_basis_status`, `requires_lawyer_review`, `safe_use`, and stronger legal-advice warnings
  - starter legal fallback cards are explicitly marked as checklist prompts, not legal sources
  - response packs now fetch Macedonian legal context from the DB instead of passing an empty legal context into claim support/confidence checks
  - response pack legal flags now warn when legal context includes research leads or official references that still require lawyer review
  - frontend party briefing legal context cards now show legal basis status, lawyer-review badges, and safe-use guidance
  - frontend response pack drawer now includes a "Legal Context To Verify" section with source links and safe-use text
  - verified a sample response pack includes legal context marked `research_lead_needs_review` with `requires_lawyer_review=true`
  - verified compile, frontend build, API restart, and smoke: `40 / 40`
- Polished role-specific dashboard guidance:
  - persona configs now include role-specific next move, success signal, and caution guidance for party/campaign, political figure, PR agency, journalist, media analyst, business risk, diaspora, and general client workspaces
  - Admin workspace strip now emphasizes fix queue, scheduler freshness, source validation, backups, and smoke testing before demos
  - Analyst workspace strip now emphasizes topic search, story spread, entity dossiers, citations, and single-source warnings
  - client workspace strip now shows persona-specific operating cues so each dashboard feels intentionally different, not just cosmetically renamed
  - added responsive `mode-cues` cards to the workspace strip
  - verified frontend build, Python compile, and smoke: `40 / 40`
- Polished PDF/report legal output:
  - response-pack PDFs now include the legal context section, not only legal review flags
  - PDF legal context now renders legal basis status, lawyer-review requirement, safe-use guidance, and source/reference fields in a structured table
  - party briefing PDFs also benefit from the richer legal context table
  - generated sample response-pack PDF: `reports/response_pack_4_client_reputation_and_criticism_20260624_205835.pdf`
  - verified Python compile, frontend build, API restart, generated PDF export, and smoke: `40 / 40`
- Added safe historical ingestion planner:
  - new `scripts/plan_historical_ingestion.py` reports stored article coverage by source/date range before any large archive fetch
  - supports `--date-from`, `--date-to`, `--target-per-source`, `--max-per-run`, `--duplicate-stop`, `--include-inactive`, and `--json`
  - flags whether each source has archive URLs configured, how many articles are already stored in range, target gap, recommended batch size, and next action
  - planner keeps historical ingestion honest: it will not pretend current listing/RSS scraping is a true archive backfill
  - local MK plan for `2010-01-01..2026-06-24`, target 1000/source: 17 sources checked, 0 archive-ready, 15 need archive config, 2 direct scrapers disabled/RSS-only
  - verified compile and planner run
- Added production deployment scaffolding for a near-production dev handoff:
  - new `.dockerignore` keeps secrets, local databases, reports, tools, virtualenvs, model artifacts, and frontend build artifacts out of Docker build context
  - new `Dockerfile.frontend` builds the Vite dashboard with Node 24 and serves it from Nginx
  - new `frontend/nginx.conf` serves the SPA with a `/health` endpoint and client-side routing fallback
  - new `docker-compose.production.yml` defines production-shaped `db`, `api`, `scheduler`, and `frontend` services with health checks, persistent volumes, Postgres wiring, and no source-code bind mounts
  - new `.env.production.example` documents public URLs, CORS, Postgres, admin seed credentials, scheduler settings, AI toggles, SMTP, and parked Facebook/Meta values
  - new `scripts/production_readiness_report.py` checks production assets, required env keys, compose healthchecks, no `--reload`, no source bind mount, `.dockerignore`, backup/restore scripts, and historical planner presence
  - expanded `docs/PRODUCTION_READINESS.md` with production compose commands, cloud topology, launch gate, historical ingestion warning, and public smoke-test requirements
  - added `docs/CLOUD_DEPLOYMENT_RUNBOOK.md` covering first deployment, validation, paying-user gate, historical rollout, backup, rollback, and ongoing operations
  - latest readiness report: `0 error(s), 0 warning(s), 16 ok`
  - verified Python compile, frontend build, and API smoke test: `40 / 40`
- Added pilot-readiness dashboard polish and demo operations tooling:
  - corrected `scripts/seed_demo_data.py` so demo client watchlists use real Macedonian Cyrillic/Latin search terms instead of encoding-damaged text
  - applied corrected demo seed locally: 5 clients updated, 17 watchlist items created, 1 watchlist item updated
  - added role dashboard selector tiles for party war room, political figure defense, analyst/journalist research, PR agency, business risk, and diaspora modes
  - added a pilot readiness ribbon that surfaces scheduler freshness, source health, article quality, and Intelligence QA directly in War Room and Clients views
  - polished dashboard styling with stronger role cards, readiness cards, cleaner shadows, improved active navigation, and more professional intelligence-console spacing
  - added `scripts/pilot_readiness_report.py` for a pre-demo API checklist covering Intelligence QA, scheduler freshness, source health, source config, search quality, article quality, legal context, demo clients, backups, and launch checklist
  - fixed the smoke-test party briefing topic to use proper `Македонија`
  - current pilot readiness report: 0 failures, 5 warnings, 5 passes; warnings are stale scheduler, low Intelligence QA from stale operations, one source-health attention item, no daily-brief-ready clients, and launch checklist needs attention
  - live scraper health check with network access: 15 active scrapers healthy on a one-article sample; Fokus, TIME.mk, and Balkan Insight remain disabled/parked
  - verified Python compile, frontend build, local frontend HTTP 200, smoke test `40 / 40`, and pilot readiness report
- Ran a fresh pilot ingestion and cleanup cycle:
  - executed bounded MK ingestion with processing and duplicate-stop: run `4`, completed, 18 sources, 851 raw items, 520 new articles, 140 exact duplicates, 8 fuzzy duplicates, 0 errors
  - rebuilt story clusters after ingestion: 517 articles considered, 481 clusters created, 517 article links
  - pilot readiness improved from 0 failures / 5 warnings / 5 passes to 0 failures / 3 warnings / 7 passes after ingestion
  - fixed `scripts/audit_article_quality.py` to match the scraper content-quality signature (`min_unique_words`)
  - reviewed six low-quality MIA rows flagged as short/content-quality issues and marked them `excluded`, preserving them in the DB for audit while removing them from active intelligence
  - rebuilt story clusters after exclusion: 511 articles considered, 476 clusters created, 511 article links
  - updated article quality audit default behavior so it audits active intelligence only; excluded rows can still be inspected with `--include-excluded`
  - current DB article counts: 1,592 total stored, 1,586 active, 6 excluded
  - current pilot readiness: 0 failures, 2 warnings, 8 passes; remaining warnings are Intelligence QA score `70/100` and launch checklist `needs_attention`
  - verified smoke test `40 / 40`, production readiness `0 errors / 0 warnings`, active article quality audit `0` suspects, and Python compile
- Ran live scheduler validation and tightened scheduled ingestion:
  - triggered dashboard/API run-once scheduler cycle: run `5`, completed, 18 sources, 848 raw items, 8 new articles, 165 exact duplicates, 9 fuzzy duplicates, 0 errors
  - scheduler duplicate-stop worked across live news portals: 16 sources stopped as caught up, while Facebook remained intentionally parked because no token is configured
  - processed 200 queued articles and rebuilt story clusters during the scheduler run
  - added `scheduler_max_articles_per_source` so frequent 10-15 minute scheduler cycles use a smaller live scrape window while full/manual ingestion can still use the larger `max_articles_per_feed`
  - optimized scraper entry points so scheduler, CLI ingest, and API ingest reuse already-discovered article URLs instead of crawling listing pages twice
  - updated source-health logic so intentionally parked Facebook/social ingestion does not block the news-only pilot checklist
  - excluded 3 new MIA calendar/announcement stubs from active intelligence while preserving rows for audit
  - hid noisy auto entity `поддршка` that had been misclassified as a person
  - rebuilt story clusters after cleanup: 459 articles considered, 428 clusters created, 459 article links
  - current DB article counts: 1,600 total stored, 1,533 active, 67 excluded
  - current pilot readiness: 0 failures, 0 warnings, 10 passes; Intelligence QA `100/100`; launch checklist `ready`
  - verified smoke test `40 / 40`, production readiness `0 errors / 0 warnings`, article quality audit `0` suspects, and Python compile
- Cleaned MK source config validation:
  - SDK and IRL explicitly marked scraper-only with `rss_enabled: false`
  - TIME.mk marked inactive and scraper/RSS disabled until a dedicated aggregator parser exists
  - latest validation: 17 healthy active sources, 1 disabled aggregator, 0 warnings, 0 critical issues
- Expanded smoke test to 37 checks including entity lexicon, source config validation, and operations fix queue.
- Added story spread intelligence with original-source vs aggregator-source separation.
- Added entity quality report and stricter entity noise detection.
- Added Intelligence QA score and War Room readiness card.
- Expanded smoke test coverage to 34 API checks.
- Added reversible article quality review:
  - `quality_status`
  - `quality_notes`
  - `quality_reviewed_at`
- Added admin article quality actions:
  - approve
  - mark review
  - exclude
  - bulk exclude flagged
- Excluded articles are stored for audit but ignored by active intelligence paths.
- Added safe CLI path: `scripts/audit_article_quality.py --apply --exclude`.

## Active Priorities

Current state note: the app/API/build are healthy, but the pilot gate currently shows `0 failures / 2 warnings / 8 passes` because the scheduler is stale and the launch checklist wants fresh ingestion. Treat the list below as the ongoing build roadmap, not as current blockers.

## Latest Build Checkpoint

- Added response-assistant workflow polish:
  - response drafts now carry version id, use case, workflow status, public-readiness level, risk level, English text, and Macedonian working-copy text
  - response pack drawer now has a client-ready packet summary, loadable attack-spread timeline context, draft language toggle, draft copy action, and draft status controls
  - saved incident/case drawer now reopens the same draft versions and lets staff update draft statuses
  - saved briefing detail now acts as an editable prep pack with a final/client-ready statement, citations, claim support, legal context, evidence, and saved response drafts
  - attack timeline API now returns source count, attack event count, negative event count, spread label, timeline summary, urgency recommendation, first seen, and last seen timestamps
  - response pack and incident PDFs now include draft status/readiness/risk/use-case metadata and Macedonian working draft text when present
  - added dashboard styling for response packet summaries, timeline context, draft version cards, and statement editor
- Verification:
  - Python compile passed: `venv\Scripts\python.exe -m compileall src scripts`
  - frontend production build passed: `..\.tools\node-v24.14.1-win-x64\npm.cmd run build`
  - API restarted and health check passed on `http://127.0.0.1:8000/health`
  - frontend HTTP check passed on `http://127.0.0.1:5173`
  - smoke test passed: `40 / 40`
  - direct response-pack probe confirmed draft keys: `version_id`, `use_case`, `status`, `public_readiness`, `risk_level`, `text`, `mk_text`
  - direct attack-timeline probe confirmed new spread fields
  - pilot readiness is currently `0 fail / 2 warnings / 8 pass`; warnings are stale scheduler freshness and launch checklist attention due to scheduler staleness
  - in-app browser visual check could not run because the local browser bridge still reports an asset-path error
- Local dev fix:
  - allowed CORS preflight from any `localhost` / `127.0.0.1` frontend dev port so Vite fallback ports like `5174` can sign in without `OPTIONS /api/v1/auth/login 400`
- UX/accessibility polish:
  - added real demo login users for admin, analyst, party, political figure, PR agency, journalist, media analyst, and diaspora persona testing
  - added `scripts/seed_demo_users.py --apply` so demo users can be recreated safely
  - redesigned login into a role-selection screen with one-click demo buttons and clear descriptions of what each dashboard shows
  - client users now land directly on `My Dashboard` instead of a generic overview
  - simplified client navigation labels: `My Dashboard`, `News`, `People & Orgs`, `Story Spread`, `Trends`, `Alerts`
  - refreshed the color system toward a more professional navy/teal/blue palette with restrained gold/coral status accents
  - updated smoke test to choose the political-party demo client for party-briefing checks
  - verification: all demo accounts authenticated successfully, frontend build passed, API health passed, frontend HTTP passed, smoke test passed `40 / 40`
- Added dedicated political-figure demo for `Христијан Мицкоски`:
  - created client `Христијан Мицкоски Defense Desk` with political-defense plan
  - linked login `mickoski@newsintel.local` / `Demo123!`
  - added watchlist items for the approved entity, Cyrillic/Latin aliases, attack signals, government/institution coverage, and opposition/party reactions
  - added a `Mickoski` one-click login card
  - verified dashboard: 5 watchlist items, 20 dashboard matched articles, 1 critical risk item
  - verified response pack: critical severity, high confidence score 79, 8 article/source evidence pack, legal-review warnings, 5 draft response versions
  - verified attack timeline: broad spread, 50 events across 11 sources, 29 attack-language signals
  - verification: frontend build passed and smoke test passed `40 / 40`
- Corrected login and political-figure UX after testing:
  - removed person-specific login card so the login screen no longer presents `Христијан Мицкоски` as a public one-click account
  - changed login cards into generic dashboard-type selectors; users must still enter their assigned credentials
  - login screen now says selecting a dashboard type does not grant access
  - political-figure clients now land on the risk/defense workflow instead of the party briefing workflow
  - party press-conference briefing panel is now shown only for political-party clients
  - redesigned political-figure command center around `What is being said about [person]?`, mentions, attacks, spread, response, save case
  - added responsive styling for the new personal defense layout to avoid narrow/overlong dashboard sections
  - verification: frontend build passed and smoke test passed `40 / 40`

- Simplified political-figure dashboard into a focused personal monitoring desk:
  - replaced generic `Setup / Briefs / Risks / Cases / Reports` pills with wide contextual tabs (`Overview`, `Attacks`, `Portals`, `Cases`, staff-only `Setup`)
  - political-figure clients no longer see generic client blocks, party war-room tools, billing, report delivery, narrative map, and long recent-coverage dumps on the main page
  - added a focused top section answering: what is happening, why it matters, where it spread, urgency, and next best move
  - `Attacks` tab now explains attack categories, article/source counts, recommended action, response pack, timeline, alert, and save-case actions per risk item
  - `Portals` tab shows portal/source spread with sample article links instead of burying this in a long article list
  - `Cases` tab is now the saved incident history for that figure
  - response-pack API now returns `attack_analysis` with `what_is_the_attack`, `why_it_matters`, `where_it_spread`, `source_depth`, `safest_response_angle`, `historical_context_note`, `top_sources`, and `attack_categories`
  - response assistant drawer now shows an `Attack Diagnosis` panel before drafts/evidence, so suggested responses start from source-backed context instead of generic copy
  - verification: Python compile passed, frontend production build passed, smoke test passed `40 / 40`, in-process response-pack probe confirmed `attack_analysis` keys and source depth
  - live Uvicorn must be restarted to expose the new `attack_analysis` field in the already-open app session
- Added grounded client intelligence chat:
  - new `POST /api/v1/clients/{client_id}/chat` answers questions from the client permitted scope: watchlist/persona data by default, wider platform context only for admin/analyst access
  - chat can answer latest mentions, who/which portals mention the client, why attack-language is appearing, response-prep questions, and general research questions
  - answers include restrictions, confidence, suggested actions, citations, source articles, matched entities, and a disclaimer
  - every chat answer is saved into `saved_briefings` as `client_chat` in `chat_history` so the system has an audit/history trail
  - political-figure workspace now has an `Ask NewsIntel` chat panel with quick prompts and source-backed answers
  - smoke test now includes `client_chat`
  - verification: frontend build passed, Python compile passed, live backend restarted, direct live chat probe passed, smoke test passed `41 / 41`
- Expanded assistant-style workspaces beyond political figures:
  - party clients now get a `War Room` surface with grounded chat prompts and fast press-conference briefing starters
  - PR agency clients now get a `Client Desk` focused on reputation, client updates, sensitive coverage, and escalation
  - journalist and media analyst clients now get research/source-trail-oriented prompts and tabs
  - diaspora clients now get a simpler digest/explanation workspace
  - non-political-figure clients now route through the new shared persona workspace instead of the old long generic dashboard branch
  - added reusable `ClientChatPanel`, persona prompt/config helpers, role-specific tabs, latest coverage, source trail, saved chat history, saved topics/cases, and risk/action sections
  - verification: frontend build passed and smoke test passed `41 / 41`
- Cleaned up the client workspace migration:
  - removed the temporary `ts-nocheck` from `frontend/src/App.tsx`
  - removed the old long generic client dashboard branch from the render path
  - the client route now renders typed workspace components: `PoliticalFigureWorkspace` or `ClientPersonaWorkspace`
  - verification: frontend build passed, Python compile passed, smoke test passed `41 / 41`
- Extracted client workspaces out of the app shell:
  - moved typed client workspace rendering into `frontend/src/clientWorkspaces.tsx`
  - `frontend/src/App.tsx` now imports `PoliticalFigureWorkspace`, `ClientPersonaWorkspace`, `clientTabItems`, and shared workspace types instead of carrying the full role-specific workspace implementation inline
  - shared UI primitives (`Panel`, `Pill`, article/risk/incident cards, and `dateLabel`) are passed into the workspace module explicitly, keeping behavior stable while making the code easier to maintain
  - verification: frontend build passed, Python compile passed, smoke test passed `41 / 41`
- Strengthened response-pack assistant strategy:
  - backend response packs now return `response_strategy` with public posture, decision, primary line, safe opening, response angle, publication gate, evidence to use, supported claims, claims to avoid, pre-publication questions, and operator notes
  - draft response text now pulls from the generated response strategy so it is less generic and more tied to source depth, citation labels, legal flags, and publication gates
  - response drawer now shows a `Response Strategy` panel before evidence and drafts, focused on what to say, what evidence to use, what not to claim yet, and what must be checked before publishing
  - copied response-pack text now includes strategy, primary line, publication gate, and do-not-claim guidance
  - smoke test now validates the `response_strategy` field
  - verification: restarted local API, direct response-pack probe confirmed strategy present, frontend build passed, Python compile passed, smoke test passed `42 / 42`
- Applied strategy-style guidance to party and PR workflows:
  - party briefing API now returns `briefing_strategy` with public posture, decision, primary line, opening frame, message angle, publication gate, tone guidance, evidence to use, supported claims, claims to avoid, pre-publication questions, and operator notes
  - party press statement, short social response, and rebuttal drafts now use the generated briefing strategy instead of only generic template wording
  - party war-room UI now shows a `Press Strategy` panel after readiness and before generated talking points
  - copied party briefing text now includes press strategy, primary line, publication gate, and strategy avoid-list
  - PR agency workspace now shows a `Client Response Strategy` panel with account-manager guidance, evidence to attach, do-not-overclaim rules, and send-check questions
  - smoke test now validates both `response_strategy` and `party_briefing_strategy`
  - verification: Python compile passed, frontend build passed, local API restarted, smoke test passed `43 / 43`

## 2026-07-29 Intelligence, History, Legal, And Role Checkpoint

- Added a provider-neutral production AI layer:
  - configurable `AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`, and separate summary/intelligence toggles
  - Anthropic provider support with deterministic temperature, timeouts, and local fallback
  - strict evidence labels for every generated factual sentence and claim
  - generated output is rejected when citations are missing, unknown, or outside the permitted evidence pack
  - article summaries, client chat, party briefings, attack explanations, and response packs now expose generation metadata
  - without a configured key, all workflows remain available through the deterministic local evidence path
- Added grounding regression tests:
  - missing-key fallback
  - valid citation acceptance
  - unsupported sentence rejection
  - out-of-scope citation rejection
  - current result: `5 passed`
- Added controlled historical political campaigns:
  - `config/historical/north_macedonia.yaml` defines Mickoski, VMRO-DPMNE, SDSM, DUI, VLEN, Ahmeti, Filipche, Zaev, Gruevski, Kovachevski, Siljanovska-Davkova, and Pendarovski
  - `scripts/run_historical_campaign.py` runs bounded year-by-year slices, is dry-run by default, requires backup confirmation for writes, and records a JSONL ledger
  - historical writes share the live ingestion lock
  - validated a 2024 Mickoski slice across four archives
  - applied and processed a six-article 2024 sample with zero processing errors
- Expanded the Macedonian legal library workflow:
  - six priority research leads now point to official Gazette, Assembly, LDBIS, DKSK, or AVMU sources
  - imported and archived exact content for all six, with SHA-256 hashes and extracted-text lengths
  - added `pypdf` and `scripts/import_legal_source.py`
  - added counsel assignments with reviewer, organization, email, scope, due date, status, and completion time
  - lawyer verification remains available only through the immutable review decision endpoint
  - no document was automatically marked lawyer verified
  - full extracted text stays in the database; list endpoints return only hash/path/text length to remain fast
- Finished another role-workspace pass:
  - role-specific metric language for political figures, parties, PR agencies, journalists, analysts, and diaspora
  - PR Agency is now selectable on the login workspace chooser
  - client accounts no longer trigger staff-wide trends, stories, risk, source, narrative, timeline, and article queries
  - secondary client requests wait for the personalized dashboard to load first
  - repeated watchlist setup rows are deduplicated at read time without deleting configuration history
  - direct dashboard profiling improved the slowest role from timeout territory to roughly 9-22 seconds on the current 19k-article SQLite dataset
- Verification completed:
  - database backup: `data/backups/newsintel-before-ai-history-legal-upgrade-20260729_202555.db`
  - Python compile passed
  - frontend production build passed
  - API and frontend health checks passed
  - political figure, party, PR agency, journalist, media analyst, diaspora, admin legal review, and non-admin permission checks each passed in browser tests
  - legal list and review queue respond in under 0.1 seconds without full-text payload expansion
  - scoped chat, response pack, and party briefing return HTTP 200 with local/AI generation metadata

### Resume Point

1. Configure a production model key, enable AI in a controlled environment, and run the same citation-rejection tests against real provider output.
2. Run the historical campaign in bounded yearly batches after each backup; the 2024 Mickoski sample is complete, not the full multi-year campaign.
3. Assign the imported legal texts to qualified Macedonian counsel and record real decisions. Eleven references remain unverified by a lawyer.
4. Move client intelligence matching to PostgreSQL full-text search or cached/materialized watchlist results; SQLite role dashboards are improved but still slower than a production target.
5. Re-run the complete browser matrix with a multi-worker/Postgres rehearsal. Individual role tests pass; the single-worker all-role suite exceeds the current aggregate timeout.
- Saved the product vision and continued role-dashboard polish:
  - added `docs/PRODUCT_VISION.md` covering the platform vision, trust model, intelligence core, client-specific dashboards, pricing direction, competitive difference, roadmap, and estimated timeline
  - added role-specific workflow cards inside `frontend/src/clientWorkspaces.tsx` so party, PR agency, journalist, media analyst, diaspora, and general client dashboards explain their intended flow more clearly
  - party clients now see a press-conference flow, PR agencies see a client-reputation flow, journalists see a research flow, media analysts see a country-signal flow, and diaspora users see a simple digest flow
  - verification: frontend build passed, Python compile passed, local API started, smoke test passed `43 / 43`

1. Raise Intelligence QA score toward 80+ by cleaning article/entity/source quality.
2. Improve Macedonian entity accuracy with curated people, parties, institutions, aliases, and Cyrillic/Latin handling.
3. Improve source/scraper coverage and source-specific extraction quality.
4. Strengthen party/political figure response assistant with evidence-only, citation-first outputs.
5. Expand legal knowledge library and make legal references clearly “review required.”
6. Polish dashboard surfaces by role: admin, party, political figure, journalist/media analyst.
7. Production readiness: run a real cloud/VPS rehearsal with production env values, managed Postgres or compose Postgres, HTTPS/domain wiring, restore drill, and public smoke test.
8. Pilot freshness: keep scheduler running, run another bounded ingestion cycle after the next news interval, and use `scripts/pilot_readiness_report.py` to push Intelligence QA above 80.

## Parked For Later

- Facebook/Meta ingestion.
- Telegram ingestion.
- YouTube transcript ingestion.
- Large historical backfill.

## Resume Point

Continue from the active priorities above. Latest build slice added and preflighted 11 Albanian-language sources, synced them into the database, and strengthened scraper date/JSON-LD checks. No ingestion was run for the new sources yet. Next best operation is a bounded ingestion cycle, process the existing active backlog, rebuild story clusters, and review article/entity quality before returning to grounded chat and attack-understanding work.

## Current Resume Point - 2026-07-29

This is the authoritative resume point for the latest build:

1. Add a production AI API key and enable `ENABLE_AI_INTELLIGENCE`; the grounded adapter, citation validation, local fallback, and UI metadata are complete.
2. Continue the historical campaign in backed-up, year-by-year batches. The tooling and six-article Mickoski validation sample are complete; the full multi-year dataset is intentionally not yet downloaded.
3. Assign the 11 imported legal references to qualified Macedonian counsel. Import, hashing, local archival, assignment, and immutable decision recording are complete; human verification cannot be automated.
4. Move role-dashboard matching to PostgreSQL full-text search or cached materialized results. All role experiences work, but the current 19k-article SQLite database takes roughly 9-22 seconds for a cold personalized dashboard.
5. Run the full browser matrix against the PostgreSQL rehearsal. Each role and the legal permission checks pass independently; the complete sequential SQLite run exceeds the aggregate test timeout.
6. Keep social-media ingestion parked until news intelligence quality, production search performance, and legal review are dependable.

Final verification for this build: backend tests `5 passed`, Python compilation passed, frontend production build passed, live authentication passed, live legal review queue returned 11 items, and live client chat returned HTTP 200 with eight permitted citations.

## 2026-07-31 Production Foundation Checkpoint

This is the authoritative checkpoint for the current production-readiness pass.

### Completed

- Strengthened grounded AI validation:
  - provider output must identify exact evidence quotations for every claim
  - citations, quotations, lexical support, and final answer sentences are validated
  - unsupported provider output is rejected and the deterministic evidence path remains available
  - `scripts/verify_ai_grounding.py` safely reports whether a real provider key is configured
- Ran a bounded historical political backfill:
  - 31 yearly slices completed for Mickoski, VMRO-DPMNE, SDSM, DUI, VLEN,
    Ahmeti, Filipche, and Gruevski
  - 128 new historical articles were added; all retained historical rows have dates
  - remaining unprocessed backlog was reduced to zero before the live cycle
  - recent story clusters were rebuilt
  - `scripts/historical_coverage_report.py` now makes year-by-year archive gaps visible
- Improved data quality:
  - entity lexicon expanded to 72 curated entries
  - 14 duplicate entities merged, 1,436 noisy entities hidden, and 15 non-article
    pages excluded from active intelligence while preserving their audit trail
  - entity evaluation passes 21/21 with 100% fixture precision and recall
  - attack understanding passes 6/6 conservative fixtures
  - Meta.mk dotted publication dates now parse correctly
  - bounded live checks mark Meta.mk and INA Online healthy
- Completed the legal handoff safeguards:
  - legal library expanded from 11 to 15 official-source references
  - a lawyer-verified decision now requires a matching counsel assignment with
    jurisdiction and qualification reference
  - no reference was falsely marked lawyer verified
  - exported a counsel packet under `reports/legal-review`
- Rehearsed PostgreSQL:
  - migrated 442,770 SQLite rows with verified table counts
  - added PostgreSQL full-text indexes and personalized dashboard caching
  - fixed PostgreSQL-specific article search queries found by the smoke test
  - created a custom PostgreSQL backup and restored it into a disposable database
  - restore counts verified: 20,435 articles, 69,416 entities, 265,132 mentions,
    and 15 legal documents
- Met the dashboard performance target:
  - every cold personalized dashboard loads in 0.03-1.47 seconds
  - cached responses load in 0.01-0.08 seconds
  - `scripts/benchmark_dashboards.py` enforces the three-second release target
- Hardened authentication and delivery:
  - failed login throttling returns 429 after five invalid attempts
  - API and Nginx security headers added
  - production frontend bundle split into React, chart, icon, and application chunks
  - explicit `SMTP_ENABLED` prevents accidental delivery and false readiness warnings
- Added pilot operations:
  - reviewed-YAML client creation with placeholder and password checks
  - scheduler stale-PID recovery
  - pilot onboarding, pricing direction, demo gate, and support procedure

### Verified

- API smoke test on PostgreSQL: `47 / 47`
- Browser matrix: `20 / 20` desktop and mobile tests
- Python tests: `14 / 14`
- Static production assets: `16 / 16`, zero warnings
- Strict production-shaped environment validation: zero errors and zero warnings
- PostgreSQL backup and actual restore drill: passed
- Cross-client dashboard access: HTTP 403
- Cold dashboard target below three seconds: passed for all eight configured clients

### External Activation Gates

These cannot be honestly completed without owner-supplied external credentials or
professional review:

1. Add a real `AI_API_KEY`, enable AI in a controlled environment, and run
   `scripts/verify_ai_grounding.py`. No key is stored in source control.
2. Assign legal references to a qualified Macedonian lawyer and record genuine
   corrections, effective dates, and sign-off through the audited workflow.
3. Supply the cloud/VPS account, public domain, HTTPS certificates, production
   secrets, and optional SMTP service for the final public deployment.
4. Continue source-specific archive work for historical gap years. The bounded
   recent backfill is complete, but the 2010+ archive is not yet complete.

### Live Operation

- PostgreSQL API rehearsal: `http://127.0.0.1:8001`
- Vite rehearsal: `http://127.0.0.1:5174`
- PostgreSQL scheduler cycle `1232` completed with 328 new articles, 192 total
  duplicates (189 exact and 3 fuzzy), 9 sources stopped early, 328 processed,
  zero errors, and 1,194 rebuilt story clusters.
- Automatic follow-up cycle `1233` completed in roughly two minutes with zero
  new articles, 246 duplicates, 24 sources stopped early, zero processing
  backlog, and zero errors. The scheduler remains active on a 15-minute interval.
- Current rehearsal data: 20,763 articles, 70,217 entities, 269,089 mentions,
  1,194 current story clusters, 15 legal references, and one in-app pilot alert.
- Local and Docker NLP are aligned on spaCy 3.8 with `xx_ent_wiki_sm` 3.8.0.
- Final pilot readiness: `10 / 10`, zero failures and zero warnings.
