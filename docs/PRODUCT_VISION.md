# NewsIntel Product Vision

## One Sentence

NewsIntel is a Balkan media and political intelligence platform that collects public coverage, understands people, parties, institutions, topics, and source spread, then helps each client decide what happened, why it matters, and what they should do next.

## Core Principle

The system must be powerful, but it must not invent facts.

Every answer, response draft, briefing, risk warning, legal note, and dashboard insight should be grounded in stored articles, source metadata, citations, entity history, saved cases, or clearly marked legal research leads. If the database does not support a claim, the product should say so.

## Current Execution Order

The product is being completed in this order:

1. Keep continuous news ingestion fresh, deduplicated, processed, and operationally recoverable.
2. Maintain measurable entity and attack-understanding quality with curated acceptance sets.
3. Make chat conversational, citation-backed, and strictly limited to each client's permitted data.
4. Keep every role dashboard simple and decision-focused: political figures see attacks and responses; parties see press preparation; PR teams see client issues; analysts see evidence and spread; normal clients see clear summaries.
5. Build historical memory in small, backed-up batches for priority people and parties.
6. Treat legal material as a reviewed knowledge library with immutable counsel decisions, never as automatic legal advice.
7. Prove permissions, browser workflows, backups, Postgres migration, monitoring, and scheduler recovery before a public pilot.
8. Add social media only after the news intelligence system is dependable.

## Intelligence Core

The platform should continuously:

- collect news from configured Macedonian and Balkan sources
- scrape articles beyond RSS where possible
- store article title, URL, source, author, publish date, fetched date, images, text, summary, categories, and quality state
- deduplicate exact and fuzzy duplicates
- extract entities: people, parties, institutions, locations, companies, topics
- keep entity aliases in Cyrillic and Latin forms
- summarize each article and preserve the source link
- detect sentiment and attack-language signals around watched entities
- detect source spread: single-source, multi-source, broad spread
- build timelines by person, topic, source, and date
- save cases, response packs, press briefings, chats, reports, and evidence trails
- give users chat access over their permitted data

## Trust Model

The product should always separate:

- reported claim
- supported fact
- single-source claim
- unsupported claim
- legal research lead
- lawyer-reviewed legal reference
- official/legal source
- opinion or political criticism

Important wording:

- "From our database..."
- "Reported by..."
- "This appears in X sources..."
- "This needs verification..."
- "This needs lawyer review..."
- "We do not have enough evidence to say..."

## Client Dashboards

Each client type should feel like a different product, not a generic dashboard with renamed labels.

### Political Figure

Feels like: "Who is mentioning me, who is attacking me, why, where, and what should I do?"

Core features:

- personal mention monitoring
- attack/risk detection
- why-am-I-being-attacked explanation
- portal/source spread
- attack timeline
- response strategy
- evidence pack
- legal-review warnings
- chat over permitted personal data
- saved cases/incidents
- PDF incident reports

High-value questions:

- "What is the latest about me?"
- "Who attacked me and where?"
- "Why am I being attacked?"
- "What should I say?"
- "What should I not say yet?"
- "Was something similar reported before?"

### Political Party

Feels like: "Help us prepare the next public move or press conference."

Core features:

- topic briefing
- opponent monitoring
- press strategy
- talking points
- Q&A prep
- do-not-say warnings
- evidence/citations
- legal-context warnings
- exportable briefing pack
- chat for press preparation

High-value questions:

- "Prepare us for a press conference on this topic."
- "What are opponents saying?"
- "What are the strongest cited talking points?"
- "Which claims need legal review?"
- "What questions will journalists ask?"

### PR Agency

Feels like: "Which client has a reputation issue today and what update should we send?"

Core features:

- client issue list
- escalation status
- sensitive coverage detection
- client response strategy
- evidence to attach
- response packs
- saved client updates
- chat across allowed client data

High-value questions:

- "Which client issue needs attention?"
- "What should I send to the client?"
- "Which portals carried this?"
- "Is this single-source or spreading?"
- "Should this be escalated?"

### Journalist / Analyst

Feels like: "Help me understand what is happening and prove where it came from."

Core features:

- source trail
- story spread
- entity profiles
- connected entities
- citation-backed research chat
- timeline by topic/person
- single-source warnings
- source reliability context

High-value questions:

- "Which sources reported this?"
- "Who is connected to this story?"
- "What changed over time?"
- "What needs independent verification?"
- "Which stories are spreading fastest?"

### Diaspora / Normal Client

Feels like: "Explain what happened in Macedonia simply."

Core features:

- daily digest
- simple summaries
- top stories
- who is involved
- why it matters
- source links
- limited search/chat

High-value questions:

- "What is important today?"
- "Explain this simply."
- "Who is involved?"
- "Where can I read more?"

## Pricing Direction

Pricing should map to power and data access.

- Basic / Diaspora: daily digest, simple summaries, top stories, limited search.
- Professional / Analyst: search, sources, entities, story spread, citations.
- PR Agency: multiple monitored clients, alerts, reputation updates, evidence packs, reports.
- Political Figure: personal monitoring, attacks, response packs, legal warnings, cases.
- Political Party: press conference prep, opponent tracking, strategy packs, team access.
- Enterprise / Due Diligence: historical search, risk scoring, custom sources, API access, custom reports.

## Competitive Difference

NewsIntel should not be just a news scraper.

The difference is:

- understands entities and aliases
- understands attacks and risk
- understands source spread
- stores history over time
- answers questions over the client-permitted database
- creates evidence-backed strategies and drafts
- warns when not enough evidence exists
- separates communications support from legal advice

## Build Roadmap

### Phase 1: Strong Local Intelligence Platform

- reliable scraping and ingestion
- deduplication
- article summaries
- entity extraction and cleanup
- source metadata and reliability
- role dashboards
- grounded chat
- response packs and party briefings
- PDF/report exports

### Phase 2: Better Intelligence Memory

- historical backfill for key figures and parties
- entity profiles over time
- timeline comparisons by date
- Cyrillic/Latin search polish
- better duplicate and same-story clustering
- stronger legal-reference library

### Phase 3: Client Product Polish

- make each role dashboard feel like its own product
- simplify user flows
- improve onboarding and permissions
- create polished demo clients
- client-ready reports and exports
- saved workspaces/cases/briefings

### Phase 4: Production Readiness

- Postgres/cloud database
- reliable scheduler
- backups and restore drill
- auth hardening and permissions
- logs and monitoring
- deployment configuration
- HTTPS/domain setup

### Phase 5: Parked Expansion

- Facebook/Meta public page ingestion
- Telegram channels
- YouTube transcripts
- deeper multi-country expansion
- large historical archive

## Estimated Timeline

Assuming one focused developer plus AI assistance:

- MVP that can demo seriously to pilot clients: 3 to 5 weeks
- Strong paid pilot version: 6 to 10 weeks
- Production-ready v1 with cloud, Postgres, monitoring, polished flows, and client onboarding: 10 to 16 weeks
- More complete intelligence platform with historical memory, legal library depth, and social/video ingestion: 4 to 6 months

The current codebase is already past a basic MVP backend. The remaining time is mostly data quality, user experience, production hardening, and making the intelligence feel truly trustworthy.

## Current Priorities

1. Polish role dashboards so each client type feels distinct and easy.
2. Improve Macedonian Cyrillic/Latin entity and search quality.
3. Increase Intelligence QA and source/scraper reliability.
4. Expand legal references while keeping lawyer-review warnings.
5. Strengthen historical memory for important figures, parties, and issues.
6. Prepare production/cloud setup after the local pilot experience feels strong.
