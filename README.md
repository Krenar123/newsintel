# NewsIntel — Country-Level News Intelligence Platform

A self-hosted news aggregation, summarization, and intelligence platform. Pick a country, automatically discover its top news sources, ingest articles via RSS/scraping, summarize and categorize them using local ML (zero API cost for core features), extract named entities (people, orgs, places), and deliver curated briefings via PDF, email, or API.

## Architecture

```
RSS Feeds / Scrapers
        ↓
   Ingestion Worker (cron-scheduled)
        ↓
   Local NLP Pipeline (spaCy + sumy + scikit-learn)
   → Summarize → Categorize → Extract Entities
        ↓                    ↓ (optional)
   PostgreSQL            Claude API (premium summaries)
        ↓
   ┌──────────────┬───────────────┬──────────────┐
   FastAPI (REST)  PDF Generator   Email Sender
                   (reportlab)     (SMTP/SES)
        ↓               ↓              ↓
   Web Dashboard    Weekly PDF     Client Inbox
```

## Key Design Decisions

- **Local-first ML**: spaCy for NER, sumy for extractive summarization, TF-IDF + Naive Bayes for categorization. Core pipeline costs $0.
- **Claude API optional**: Only used for premium abstractive summaries. Can be toggled off entirely.
- **RSS-first ingestion**: Legal, structured, reliable. HTML scraping is a fallback only.
- **Entity-centric storage**: Every article is linked to extracted entities, enabling "search by person" across all news.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- PostgreSQL 15+
- (Optional) Docker & Docker Compose

### 2. Setup

```bash
# Clone and enter project
cd newsintel

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Download spaCy language models
python -m spacy download en_core_web_sm
python -m spacy download xx_ent_wiki_sm  # Multilingual NER

# Copy and configure environment
cp .env.example .env
# Edit .env with your database URL and optional API keys

# Initialize database
python scripts/setup_db.py

# Run initial ingestion for your configured country
python scripts/ingest.py

# Generate a PDF report
python scripts/generate_report.py

# Start the API server
uvicorn src.api.main:app --reload --port 8000
```

### 3. Docker (Alternative)

```bash
docker-compose up -d
```

## Configuration

### Adding a Country

Create a YAML file in `config/countries/`:

```yaml
name: "North Macedonia"
code: "mk"
languages: ["mk", "en"]
timezone: "Europe/Skopje"

sources:
  - name: "MKD News Portal"
    url: "https://example.mk"
    rss_feeds:
      - url: "https://example.mk/rss/latest"
        category: "general"
      - url: "https://example.mk/rss/politics"
        category: "politics"
    language: "mk"
    reliability_score: 0.8
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | No | For premium AI summaries |
| `SMTP_HOST` | No | Email delivery |
| `SMTP_PORT` | No | Email port (default: 587) |
| `SMTP_USER` | No | Email username |
| `SMTP_PASSWORD` | No | Email password |
| `SENDER_EMAIL` | No | From address for reports |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/articles` | List articles (filterable) |
| GET | `/api/v1/articles/{id}` | Article detail with summary |
| GET | `/api/v1/entities` | List all extracted entities |
| GET | `/api/v1/entities/{id}/articles` | All articles mentioning entity |
| GET | `/api/v1/search?q=...` | Full-text search |
| GET | `/api/v1/categories` | Articles grouped by category |
| GET | `/api/v1/trends` | Trending entities/topics |
| POST | `/api/v1/reports/generate` | Generate PDF briefing |
| GET | `/api/v1/countries` | List configured countries |
| POST | `/api/v1/ingest/{country_code}` | Trigger ingestion |

## Project Structure

```
newsintel/
├── config/
│   ├── settings.py          # App configuration
│   └── countries/            # Country YAML configs
├── src/
│   ├── models/database.py    # SQLAlchemy ORM models
│   ├── ingestion/
│   │   ├── rss_fetcher.py    # RSS feed parser
│   │   └── scraper.py        # HTML fallback scraper
│   ├── processing/
│   │   ├── summarizer.py     # Extractive + AI summarization
│   │   ├── categorizer.py    # ML text categorization
│   │   ├── entities.py       # spaCy NER extraction
│   │   └── pipeline.py       # Processing orchestrator
│   ├── delivery/
│   │   ├── pdf_report.py     # PDF report generator
│   │   └── email_sender.py   # Email delivery
│   ├── api/
│   │   ├── main.py           # FastAPI application
│   │   ├── routes.py         # API route handlers
│   │   └── schemas.py        # Pydantic models
│   └── search/engine.py      # Search functionality
├── scripts/                   # CLI scripts
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Cost Analysis

| Component | Monthly Cost |
|-----------|-------------|
| VPS (Hetzner CX21) | €5-10 |
| PostgreSQL (same VPS) | $0 |
| Core NLP pipeline | $0 |
| Claude API (200 articles/day, Haiku Batch) | ~$30-50 |
| Email (AWS SES, 1000 emails) | ~$1 |
| **Total without AI summaries** | **~$10/mo** |
| **Total with AI summaries** | **~$50/mo** |

## License

Proprietary — All rights reserved.
