"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str = ""

    # Production AI (optional). Anthropic remains supported for backwards compatibility.
    ai_provider: str = "anthropic"
    ai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    enable_ai_summaries: bool = False
    enable_ai_intelligence: bool = False
    ai_model: str = "claude-haiku-4-5-20251001"
    ai_timeout_seconds: int = 45
    ai_max_output_tokens: int = 1400
    ai_grounding_required: bool = True

    # Evidence retrieval. Quality/source boosts never admit a lexical non-match.
    rag_minimum_score: float = 0.85
    rag_max_per_source: int = 4
    rag_max_evidence: int = 16

    # Entity intelligence. GLiNER is optional and runs locally when installed.
    enable_gliner_ner: bool = False
    gliner_model: str = "urchade/gliner_multi-v2.1"
    gliner_threshold: float = 0.62
    gliner_max_chars: int = 20000

    # Email
    smtp_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sender_email: str = "reports@yourdomain.com"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    default_country: str = "mk"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:3000,http://127.0.0.1:3000"
    token_expiry_hours: int = 12
    login_max_attempts: int = 5
    login_window_minutes: int = 15
    seed_admin_email: str = "admin@newsintel.local"
    seed_admin_password: str = "ChangeMe123!"

    # Ingestion
    ingestion_interval_minutes: int = 15
    stop_after_consecutive_duplicates: int = 10
    max_articles_per_feed: int = 50
    scheduler_max_articles_per_source: int = 20
    article_retention_days: int = 90
    scrape_delay_seconds: float = 2.0
    max_concurrent_requests: int = 5
    story_cluster_days: int = 30
    story_cluster_limit: int = 1500
    client_dashboard_cache_seconds: int = 300
    facebook_access_token: Optional[str] = None
    facebook_api_version: str = "v24.0"
    max_facebook_posts_per_page: int = 25

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    countries_dir: Path = Path(__file__).parent / "countries"
    reports_dir: Path = Path(__file__).parent.parent / "reports"
    models_dir: Path = Path(__file__).parent.parent / "ml_models"

settings = Settings()

# Ensure directories exist
settings.reports_dir.mkdir(parents=True, exist_ok=True)
settings.models_dir.mkdir(parents=True, exist_ok=True)
(settings.base_dir / "data").mkdir(parents=True, exist_ok=True)

# Default database URL using absolute path
if not settings.database_url:
    db_path = settings.base_dir / "data" / "newsintel.db"
    settings.database_url = f"sqlite:///{db_path}"
