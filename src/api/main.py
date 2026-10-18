"""
FastAPI Application — REST API for NewsIntel.

Provides endpoints for:
  - Article listing and search
  - Entity lookup and trending
  - Report generation
  - Subscription management
  - Ingestion triggers
"""

import datetime
import hashlib
import hmac
import json
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import yaml
from fastapi import (
    FastAPI, Query, HTTPException, Depends, BackgroundTasks, Header, Request,
)
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case, select, or_, and_, union_all

from config import settings
from src.models.database import (
    get_engine, get_session_factory, create_all_tables,
    Article, Summary, Entity, EntityMention, ArticleCategory as ArticleCategoryModel,
    Source, Subscription, Report, SummaryType, EntityType,
    SubscriptionFrequency, ReportFormat,
    Client, ClientWatchlistItem, ClientType, SubscriptionPlan, WatchlistItemType,
    ClientDashboardCache,
    FacebookPageMonitor, ClientIncident, ClientIncidentEvidence, IncidentStatus,
    AttackReview,
    User, AuthToken, UserRole, LegalDocument, LegalSourceStatus, LegalReview,
    LegalReviewAssignment,
    IngestionRun, IngestionSourceStat, EntityStatus,
    StoryCluster, StoryClusterArticle, SavedBriefing, SavedSearch,
    ChatConversation, ChatMessage,
)
from src.search.engine import SearchEngine, SearchFilters
from src.search.normalization import search_variants
from src.search.predicates import (
    article_text_match,
    client_publishable_entity_filter,
    entity_text_match,
    is_client_publishable_entity,
)
from src.processing.pipeline import ProcessingPipeline
from src.ingestion.rss_fetcher import RSSFetcher
from src.ingestion.scraper import ArticleScraper
from src.ingestion.facebook_fetcher import FacebookPageFetcher
from src.delivery.pdf_report import PDFReportGenerator, ReportConfig
from src.delivery.incident_report import IncidentReportGenerator
from src.delivery.briefing_export import BriefingExportGenerator
from src.processing.alerts import (
    Alert, AlertNotification, AlertChannel, AlertType,
    AlertEngine, NotificationDispatcher,
)
from src.processing.sentiment import SentimentAnalyzer
from src.api.schemas import (
    ArticleResponse, ArticleListResponse, ArticleSummary, ArticleEntity,
    ArticleCategory, EntityResponse, EntityDetailResponse, EntityArticle,
    TrendingEntity, CategoryStats, SourceUpdate, ReportRequest, ReportResponse, ReportListItem,
    SavedBriefingCreate, SavedBriefingUpdate, SavedBriefingResponse,
    SubscriptionCreate, SubscriptionResponse, SearchQuery,
    SavedSearchCreate, SavedSearchUpdate, SavedSearchResponse,
    IngestResponse, ProcessResponse, CountryResponse,
    ClientCreate, ClientResponse, WatchlistItemCreate, WatchlistItemResponse,
    ClientDashboardResponse, ClientDailyBriefResponse, ClientUsageResponse,
    ClientChatRequest, ClientChatResponse,
    ClientChatConversationResponse, ClientChatTurnResponse,
    FacebookPageMonitorCreate, FacebookPageMonitorResponse,
    PartyBriefingRequest, PartyBriefingResponse,
    ResponsePackResponse, IncidentCreate, IncidentUpdate, IncidentResponse,
    EvidenceCreate, EvidenceResponse,
    UserCreate, UserResponse, LoginRequest, LoginResponse,
    LegalDocumentCreate, LegalDocumentUpdate, LegalDocumentResponse,
    LegalReviewCreate, LegalReviewResponse,
    LegalReviewAssignmentCreate, LegalReviewAssignmentResponse,
    EntityReviewUpdate, EntityMergeRequest,
    EntityLexiconAddRequest,
    ArticleQualityReviewUpdate,
    AttackReviewUpdate,
    PoliticalRiskResponse, AlertCreate, RiskAlertSuggestionCreate,
)
from src.processing.entities import (
    corrected_entity_type, is_likely_entity_name, EntityExtractor,
)
from src.processing.story_clustering import StoryClusterer
from src.processing.risk_scoring import PoliticalRiskScorer
from src.processing.attack_analysis import analyze_attack_text, detect_attack_categories
from src.intelligence.grounded_ai import GroundedAI
from src.logging_config import configure_logging

import structlog

configure_logging(settings.log_level, json_logs=settings.app_env.lower() in {"production", "prod"})
logger = structlog.get_logger()

REQUIRED_LEGAL_COVERAGE = [
    {
        "key": "constitution",
        "label": "Constitution and public institutions",
        "keywords": ["constitution", "constitutional", "ustav", "public institutions"],
    },
    {
        "key": "defamation_media",
        "label": "Defamation, insult, and media response",
        "keywords": ["defamation", "insult", "media", "civil liability"],
    },
    {
        "key": "elections_campaigns",
        "label": "Elections and campaign conduct",
        "keywords": ["election", "campaign", "electoral"],
    },
    {
        "key": "criminal_procedure",
        "label": "Criminal allegations and procedure",
        "keywords": ["criminal", "crime", "procedure", "presumption"],
    },
    {
        "key": "anti_corruption",
        "label": "Anti-corruption and conflict of interest",
        "keywords": ["corruption", "conflict of interest", "public office"],
    },
    {
        "key": "public_information",
        "label": "Free access to public information",
        "keywords": ["public information", "access to information", "transparency"],
    },
    {
        "key": "legal_aid",
        "label": "Legal aid and access to justice",
        "keywords": ["legal aid", "access to justice", "legal support"],
    },
]


# ── Database setup ────────────────────────────────────────────────────

engine = None
SessionFactory = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    global engine, SessionFactory
    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    SessionFactory = get_session_factory(engine)
    logger.info("database_initialized")
    yield
    engine.dispose()


def _cors_origins() -> list[str]:
    origins = [
        origin.strip()
        for origin in str(settings.cors_origins or "").split(",")
        if origin.strip()
    ]
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


app = FastAPI(
    title="NewsIntel API",
    description="Country-level news intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_login_attempts_lock = threading.Lock()


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers["Cache-Control"] = (
        "no-store"
        if request.url.path.startswith("/api/v1/auth/")
        else "private, no-cache"
    )
    if (
        str(settings.app_env).lower() in {"production", "prod"}
        and request.url.scheme == "https"
    ):
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


def get_db() -> Session:
    """Database session dependency."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve bearer token to an active user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    token_hash = _hash_token(token)
    auth = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == token_hash,
            AuthToken.revoked_at.is_(None),
            AuthToken.expires_at > datetime.datetime.utcnow(),
        )
        .first()
    )
    if not auth or not auth.user or not auth.user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return auth.user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.ANALYST):
        raise HTTPException(status_code=403, detail="Staff role required")
    return user


# ── Helper: Convert ORM → Pydantic ───────────────────────────────────

def article_to_response(article: Article) -> ArticleResponse:
    """Convert Article ORM model to API response."""
    return ArticleResponse(
        id=article.id,
        title=article.title,
        url=article.url,
        content=article.content,
        source_name=article.source.name if article.source else "Unknown",
        author=article.author,
        language=article.language,
        published_at=article.published_at,
        fetched_at=article.fetched_at,
        ingested_at=article.ingested_at,
        ingestion_method=article.ingestion_method,
        platform=article.platform,
        external_id=article.external_id,
        platform_account_id=article.platform_account_id,
        platform_account_name=article.platform_account_name,
        word_count=article.word_count,
        quality_status=article.quality_status or "active",
        quality_notes=article.quality_notes,
        quality_reviewed_at=article.quality_reviewed_at,
        image_url=article.image_url,
        summaries=[
            ArticleSummary(
                text=s.text,
                summary_type=s.summary_type.value,
                language=s.language,
            )
            for s in article.summaries
        ],
        categories=[
            ArticleCategory(
                category=c.category,
                confidence=c.confidence,
                is_primary=c.is_primary,
            )
            for c in article.categories
        ],
        entities=[
            ArticleEntity(
                entity_id=m.entity_id,
                name=m.entity.name,
                entity_type=corrected_entity_type(m.entity.name, m.entity.entity_type.value),
                mention_count=m.mention_count,
                context=m.context_snippet,
            )
            for m in article.entity_mentions
            if is_client_publishable_entity(m.entity)
            and is_likely_entity_name(m.entity.name, m.entity.entity_type.value)
        ],
    )


def _active_article_filter():
    return or_(Article.quality_status == None, Article.quality_status != "excluded")


def _active_article_query(query):
    return query.filter(_active_article_filter())


def _entity_to_response(entity: Entity) -> EntityResponse:
    metadata = entity.metadata_json or {}
    provenance = metadata.get("provenance", [])
    if isinstance(provenance, str):
        provenance = [provenance]
    matched_aliases = metadata.get("matched_aliases", metadata.get("aliases", []))
    if isinstance(matched_aliases, str):
        matched_aliases = [matched_aliases]
    return EntityResponse(
        id=entity.id,
        name=entity.name,
        canonical_name=entity.canonical_name,
        entity_type=corrected_entity_type(entity.name, entity.entity_type.value),
        status=entity.status.value if entity.status else "auto",
        review_notes=entity.review_notes,
        provenance=provenance,
        confidence=metadata.get("confidence"),
        publishable=is_client_publishable_entity(entity),
        matched_aliases=matched_aliases,
        total_mentions=entity.total_mentions,
        first_seen_at=entity.first_seen_at,
        last_seen_at=entity.last_seen_at,
    )


def _recompute_entity_totals(db: Session, entity: Entity):
    total = (
        db.query(func.coalesce(func.sum(EntityMention.mention_count), 0))
        .filter(EntityMention.entity_id == entity.id)
        .scalar()
    )
    last_seen = (
        db.query(func.max(Article.published_at))
        .join(EntityMention, EntityMention.article_id == Article.id)
        .filter(EntityMention.entity_id == entity.id)
        .scalar()
    )
    entity.total_mentions = int(total or 0)
    if last_seen:
        entity.last_seen_at = last_seen


def _merge_entity_records(db: Session, source: Entity, target: Entity):
    """Move mentions from source to target and hide the duplicate source."""
    source_mentions = (
        db.query(EntityMention)
        .filter(EntityMention.entity_id == source.id)
        .all()
    )
    for mention in source_mentions:
        existing = (
            db.query(EntityMention)
            .filter(
                EntityMention.entity_id == target.id,
                EntityMention.article_id == mention.article_id,
            )
            .first()
        )
        if existing:
            existing.mention_count += mention.mention_count
            if not existing.context_snippet:
                existing.context_snippet = mention.context_snippet
            db.delete(mention)
        else:
            mention.entity_id = target.id

    source.status = EntityStatus.HIDDEN
    source.review_notes = f"Merged into entity #{target.id}: {target.name}"
    source.reviewed_at = datetime.datetime.utcnow()
    target.status = EntityStatus.APPROVED
    _recompute_entity_totals(db, target)
    _recompute_entity_totals(db, source)


def _story_cluster_to_response(cluster: StoryCluster) -> dict:
    articles = sorted(
        cluster.articles,
        key=lambda link: (
            link.article.published_at
            or link.article.fetched_at
            or link.article.ingested_at
            or datetime.datetime.min
        ),
        reverse=True,
    )
    source_stats: dict[int, dict] = {}
    for link in articles:
        if not link.article or not link.source:
            continue
        stat = source_stats.setdefault(
            link.source.id,
            {
                "source_id": link.source.id,
                "source_name": link.source.name,
                "source_type": link.source.source_type,
                "political_leaning": link.source.political_leaning,
                "reliability_score": link.source.reliability_score,
                "article_count": 0,
                "latest_published_at": None,
            },
        )
        stat["article_count"] += 1
        article_date = link.article.published_at or link.article.fetched_at or link.article.ingested_at
        if article_date and (
            not stat["latest_published_at"] or article_date > stat["latest_published_at"]
        ):
            stat["latest_published_at"] = article_date
    aggregator_stats = [
        row for row in source_stats.values()
        if row["source_type"] == "aggregator"
    ]
    evidence_stats = [
        row for row in source_stats.values()
        if row["source_type"] != "aggregator"
    ]
    original_source_count = len(evidence_stats)
    aggregator_source_count = len(aggregator_stats)
    spread_hours = None
    if cluster.first_published_at and cluster.last_published_at:
        spread_hours = round(
            (cluster.last_published_at - cluster.first_published_at).total_seconds() / 3600,
            1,
        )
    validation_explanation = (
        f"Validated by {original_source_count} original sources, including "
        f"{cluster.high_reliability_source_count} high-reliability sources."
        if cluster.status == "validated"
        else f"Reported by {original_source_count} original sources. Treat as multi-source but keep checking attribution."
        if cluster.status == "multi_source"
        else "Only one source is currently reporting this. Verify before treating it as established."
    )
    risk_flags = []
    if cluster.status == "single_source":
        risk_flags.append("single_source")
    if cluster.average_reliability and cluster.average_reliability < 0.55:
        risk_flags.append("low_average_reliability")
    if original_source_count >= 4:
        risk_flags.append("fast_spreading")
    if aggregator_source_count:
        risk_flags.append("aggregator_indexed")
        validation_explanation += f" Also indexed by {aggregator_source_count} aggregator source(s), which signals spread but is not counted as independent evidence."
    return {
        "id": cluster.id,
        "title": cluster.title,
        "status": cluster.status,
        "validation_explanation": validation_explanation,
        "country_code": cluster.country_code,
        "article_count": cluster.article_count,
        "source_count": cluster.source_count,
        "original_source_count": original_source_count,
        "aggregator_source_count": aggregator_source_count,
        "aggregator_sources": [row["source_name"] for row in aggregator_stats],
        "high_reliability_source_count": cluster.high_reliability_source_count,
        "average_reliability": round(cluster.average_reliability or 0, 2),
        "spread_hours": spread_hours,
        "risk_flags": risk_flags,
        "first_published_at": cluster.first_published_at,
        "last_published_at": cluster.last_published_at,
        "summary": cluster.summary,
        "source_breakdown": sorted(
            source_stats.values(),
            key=lambda row: (row["article_count"], row["reliability_score"] or 0),
            reverse=True,
        ),
        "sources": sorted({
            link.source.name
            for link in articles
            if link.source
        }),
        "articles": [
            {
                "article_id": link.article.id,
                "title": link.article.title,
                "url": link.article.url,
                "source_name": link.source.name if link.source else "Unknown",
                "source_reliability": link.source.reliability_score if link.source else None,
                "published_at": link.article.published_at,
                "similarity_score": round(link.similarity_score or 0, 2),
            }
            for link in articles[:8]
            if link.article
        ],
    }


def _brief_headline(risk_level: str, clusters: list[StoryCluster], trends: list[dict]) -> str:
    if clusters:
        top = clusters[0]
        if top.status == "validated":
            return f"Validated story leads the brief: {top.title}"
        return f"Top developing story: {top.title}"
    if trends:
        return f"{trends[0]['name']} is the strongest entity signal today"
    if risk_level in {"critical", "high"}:
        return f"Political risk is {risk_level}; monitor validated sources closely"
    return "Coverage is stable with no dominant validated story yet"


def _brief_recommended_actions(risk, clusters: list[StoryCluster]) -> list[str]:
    actions = []
    if risk.level in {"critical", "high"}:
        actions.append("Review high-risk articles and prepare sourced talking points before public response.")
    if any(cluster.status == "single_source" for cluster in clusters):
        actions.append("Verify single-source stories independently before using them in briefings.")
    if any(cluster.status == "validated" for cluster in clusters):
        actions.append("Prioritize validated cross-source stories in the morning briefing.")
    if risk.metrics.get("attack_hits"):
        actions.append("Check whether attack-language themes affect any client watchlists.")
    actions.append("Refresh ingestion and story clustering before sending a client-facing digest.")
    return actions[:5]


def client_to_response(client: Client) -> ClientResponse:
    """Convert Client ORM model to API response."""
    return ClientResponse(
        id=client.id,
        name=client.name,
        email=client.email,
        client_type=client.client_type.value,
        plan=client.plan.value,
        country_code=client.country_code,
        language=client.language,
        risk_tolerance=client.risk_tolerance,
        is_active=client.is_active,
        settings=client.settings_json or {},
        created_at=client.created_at,
    )


def watchlist_item_to_response(item: ClientWatchlistItem) -> WatchlistItemResponse:
    """Convert watchlist ORM model to API response."""
    return WatchlistItemResponse(
        id=item.id,
        client_id=item.client_id,
        item_type=item.item_type.value,
        label=item.label,
        value=item.value,
        entity_id=item.entity_id,
        source_id=item.source_id,
        facebook_page_url=item.facebook_page_url,
        priority=item.priority,
        alert_enabled=item.alert_enabled,
        response_assist_enabled=item.response_assist_enabled,
        notes=item.notes,
        created_at=item.created_at,
    )


def facebook_monitor_to_response(
    monitor: FacebookPageMonitor,
) -> FacebookPageMonitorResponse:
    """Convert Facebook monitor ORM model to API response."""
    return FacebookPageMonitorResponse(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        page_handle=monitor.page_handle,
        page_id=monitor.page_id,
        country_code=monitor.country_code,
        language=monitor.language,
        monitor_type=monitor.monitor_type,
        source_type=monitor.source_type,
        political_leaning=monitor.political_leaning,
        ownership=monitor.ownership,
        reliability_score=monitor.reliability_score,
        is_active=monitor.is_active,
        last_fetched_at=monitor.last_fetched_at,
        notes=monitor.notes,
        created_at=monitor.created_at,
    )


def incident_to_response(incident: ClientIncident) -> IncidentResponse:
    """Convert incident ORM model to API response."""
    return IncidentResponse(
        id=incident.id,
        client_id=incident.client_id,
        watchlist_item_id=incident.watchlist_item_id,
        title=incident.title,
        severity=incident.severity,
        status=incident.status.value,
        summary=incident.summary,
        recommended_posture=incident.recommended_posture,
        legal_review_flags=incident.legal_review_flags or [],
        evidence_steps=incident.evidence_steps or [],
        draft_responses=incident.draft_responses or [],
        source_article_ids=incident.source_article_ids or [],
        first_seen_at=incident.first_seen_at,
        last_seen_at=incident.last_seen_at,
        created_at=incident.created_at,
    )


def evidence_to_response(evidence: ClientIncidentEvidence) -> EvidenceResponse:
    """Convert evidence ORM model to API response."""
    return EvidenceResponse(
        id=evidence.id,
        incident_id=evidence.incident_id,
        article_id=evidence.article_id,
        url=evidence.url,
        title=evidence.title,
        source_name=evidence.source_name,
        evidence_type=evidence.evidence_type,
        captured_at=evidence.captured_at,
        published_at=evidence.published_at,
        content_hash=evidence.content_hash,
        screenshot_path=evidence.screenshot_path,
        notes=evidence.notes,
    )


def _model_to_export_dict(model) -> dict:
    """Serialize Pydantic response models for PDF export payloads."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _report_list_item(report: Report) -> ReportListItem:
    return ReportListItem(
        id=report.id,
        title=report.title,
        country_code=report.country_code,
        format=report.format.value if hasattr(report.format, "value") else str(report.format),
        categories_filter=report.categories_filter,
        date_from=report.date_from,
        date_to=report.date_to,
        file_path=report.file_path,
        article_count=report.article_count,
        created_at=report.created_at,
        download_url=f"/api/v1/reports/{report.id}/download",
    )


def saved_briefing_to_response(briefing: SavedBriefing) -> SavedBriefingResponse:
    return SavedBriefingResponse(
        id=briefing.id,
        client_id=briefing.client_id,
        briefing_type=briefing.briefing_type,
        title=briefing.title,
        country_code=briefing.country_code,
        topic=briefing.topic,
        entity_id=briefing.entity_id,
        watchlist_item_id=briefing.watchlist_item_id,
        report_id=briefing.report_id,
        status=briefing.status or "active",
        folder=briefing.folder,
        tags=_saved_briefing_tags(briefing.tags),
        notes=briefing.notes,
        payload=briefing.payload or {},
        source_article_ids=briefing.source_article_ids or [],
        confidence=briefing.confidence or {},
        created_at=briefing.created_at,
        updated_at=briefing.updated_at,
    )


def _saved_briefing_tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def legal_document_to_response(document: LegalDocument) -> LegalDocumentResponse:
    """Convert legal document ORM model to API response."""
    return LegalDocumentResponse(
        id=document.id,
        title=document.title,
        country_code=document.country_code,
        legal_area=document.legal_area,
        source_url=document.source_url,
        source_name=document.source_name,
        source_status=document.source_status.value,
        language=document.language,
        tags=document.tags or [],
        summary=document.summary,
        reference_text=document.reference_text,
        content_hash=document.content_hash,
        local_path=document.local_path,
        downloaded_at=document.downloaded_at,
        text_length=len(document.document_text or ""),
        article_refs=document.article_refs,
        confidence_score=document.confidence_score,
        date_accessed=document.date_accessed,
        verified_at=document.verified_at,
        notes=document.notes,
        created_at=document.created_at,
    )


def user_to_response(user: User) -> UserResponse:
    """Convert user ORM model to API response."""
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value,
        client_id=user.client_id,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


SAVED_SEARCH_FILTERS = {
    "category", "source_id", "language", "date_from", "date_to", "date_basis",
    "entity_id", "source_type", "min_reliability", "sentiment", "exact_phrase",
}


def _clean_saved_search_filters(filters: dict) -> dict:
    """Keep only article-search filters and JSON-safe scalar values."""
    cleaned: dict = {}
    for key, value in (filters or {}).items():
        if key not in SAVED_SEARCH_FILTERS or value in (None, ""):
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
    return cleaned


def saved_search_to_response(item: SavedSearch) -> SavedSearchResponse:
    return SavedSearchResponse(
        id=item.id,
        title=item.title,
        query=item.query,
        filters=item.filters or {},
        is_pinned=bool(item.is_pinned),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# ── Routes: Articles ─────────────────────────────────────────────────

@app.get("/api/v1/articles", response_model=ArticleListResponse)
def list_articles(
    q: Optional[str] = None,
    category: Optional[str] = None,
    source_id: Optional[int] = None,
    country_code: Optional[str] = None,
    language: Optional[str] = None,
    date_from: Optional[datetime.datetime] = None,
    date_to: Optional[datetime.datetime] = None,
    date_basis: str = Query(default="published", pattern="^(published|fetched|ingested)$"),
    entity_id: Optional[int] = None,
    exact_phrase: bool = False,
    source_type: Optional[str] = None,
    min_reliability: Optional[float] = Query(default=None, ge=0, le=1),
    sentiment: Optional[str] = Query(default=None, pattern="^(positive|negative|neutral)$"),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List and search articles with filters."""
    search = SearchEngine(db)
    filters = SearchFilters(
        query=q,
        category=category,
        source_id=source_id,
        country_code=country_code,
        language=language,
        date_from=date_from,
        date_to=date_to,
        date_basis=date_basis,
        entity_id=entity_id,
        exact_phrase=exact_phrase,
        source_type=source_type,
        min_reliability=min_reliability,
        sentiment=sentiment,
        limit=limit,
        offset=offset,
    )
    result = search.search_articles(filters)

    return ArticleListResponse(
        articles=[article_to_response(a) for a in result["articles"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
        has_more=result["has_more"],
    )


@app.get("/api/v1/articles/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int, db: Session = Depends(get_db)):
    """Get a single article with full details."""
    article = db.query(Article).get(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article_to_response(article)


@app.get("/api/v1/saved-searches", response_model=list[SavedSearchResponse])
def list_saved_searches(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List only the current user's reusable searches."""
    items = (
        db.query(SavedSearch)
        .filter(SavedSearch.user_id == user.id)
        .order_by(desc(SavedSearch.is_pinned), desc(SavedSearch.updated_at))
        .limit(50)
        .all()
    )
    return [saved_search_to_response(item) for item in items]


@app.post("/api/v1/saved-searches", response_model=SavedSearchResponse)
def create_saved_search(
    request: SavedSearchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save the current search without exposing it to another account."""
    item = SavedSearch(
        user_id=user.id,
        client_id=user.client_id,
        title=request.title.strip(),
        query=(request.query or "").strip() or None,
        filters=_clean_saved_search_filters(request.filters),
        is_pinned=request.is_pinned,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return saved_search_to_response(item)


@app.patch("/api/v1/saved-searches/{search_id}", response_model=SavedSearchResponse)
def update_saved_search(
    search_id: int,
    request: SavedSearchUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.query(SavedSearch).filter(
        SavedSearch.id == search_id,
        SavedSearch.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Saved search not found")
    values = request.model_dump(exclude_unset=True)
    if "title" in values:
        item.title = values["title"].strip()
    if "query" in values:
        item.query = (values["query"] or "").strip() or None
    if "filters" in values:
        item.filters = _clean_saved_search_filters(values["filters"] or {})
    if "is_pinned" in values:
        item.is_pinned = bool(values["is_pinned"])
    db.commit()
    db.refresh(item)
    return saved_search_to_response(item)


@app.delete("/api/v1/saved-searches/{search_id}")
def delete_saved_search(
    search_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.query(SavedSearch).filter(
        SavedSearch.id == search_id,
        SavedSearch.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Saved search not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted", "id": search_id}


# ── Routes: Entities ─────────────────────────────────────────────────

@app.get("/api/v1/entities", response_model=list[EntityResponse])
def list_entities(
    q: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """Search entities by name."""
    search = SearchEngine(db)
    etype = EntityType(entity_type) if entity_type else None
    entities = search.search_entities(q or "", entity_type=etype, limit=limit)

    return [_entity_to_response(entity) for entity in entities]


@app.get("/api/v1/entities/{entity_id}/articles",
         response_model=EntityDetailResponse)
def get_entity_articles(
    entity_id: int,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get all articles mentioning a specific entity."""
    search = SearchEngine(db)
    result = search.get_entity_articles(entity_id, limit=limit, offset=offset)

    if not result["entity"]:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity = result["entity"]
    return EntityDetailResponse(
        entity=_entity_to_response(entity),
        articles=[
            EntityArticle(
                article_id=item["article"].id,
                title=item["article"].title,
                url=item["article"].url,
                source_name=(
                    item["article"].source.name
                    if item["article"].source else "Unknown"
                ),
                published_at=item["article"].published_at,
                mention_count=item["mention_count"],
                context=item["context"],
                sentiment=item["sentiment"],
            )
            for item in result["articles"]
        ],
        total=result["total"],
        has_more=result["has_more"],
    )


@app.get("/api/v1/admin/entities/review", response_model=list[EntityResponse])
def list_entities_for_review(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=300),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """List suspicious or explicitly queued entities for human review."""
    query = db.query(Entity)
    if status:
        query = query.filter(Entity.status == EntityStatus(status))
    else:
        query = query.filter(Entity.status.notin_([EntityStatus.APPROVED, EntityStatus.HIDDEN]))

    candidates = (
        query.order_by(desc(Entity.total_mentions), Entity.name.asc())
        .limit(limit * 4)
        .all()
    )
    reviewed = []
    for entity in candidates:
        likely = is_likely_entity_name(entity.name, entity.entity_type.value)
        if status or entity.status == EntityStatus.NEEDS_REVIEW or not likely:
            reviewed.append(entity)
        if len(reviewed) >= limit:
            break

    return [_entity_to_response(entity) for entity in reviewed]


@app.patch("/api/v1/admin/entities/{entity_id}", response_model=EntityResponse)
def update_entity_review(
    entity_id: int,
    request: EntityReviewUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Approve, hide, rename, or correct the type of an entity."""
    entity = db.query(Entity).get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    if request.name is not None and request.name.strip():
        entity.name = request.name.strip()
        entity.canonical_name = EntityExtractor._canonicalize(entity.name)
    if request.entity_type is not None:
        entity.entity_type = EntityType(request.entity_type)
    if request.status is not None:
        entity.status = EntityStatus(request.status)
        entity.reviewed_at = datetime.datetime.utcnow()
    if request.review_notes is not None:
        entity.review_notes = request.review_notes

    db.commit()
    db.refresh(entity)
    return _entity_to_response(entity)


@app.post("/api/v1/admin/entities/bulk-hide-noise")
def bulk_hide_noise_entities(
    limit: int = Query(default=300, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Hide auto-created entities that fail the current quality validator."""
    candidates = (
        db.query(Entity)
        .filter(Entity.status.notin_([EntityStatus.APPROVED, EntityStatus.HIDDEN]))
        .order_by(desc(Entity.total_mentions), Entity.name.asc())
        .limit(limit)
        .all()
    )
    hidden = []
    now = datetime.datetime.utcnow()
    for entity in candidates:
        reasons = EntityExtractor.entity_quality_reasons(entity.name, entity.entity_type.value)
        if not reasons:
            continue
        entity.status = EntityStatus.HIDDEN
        entity.review_notes = f"Auto-hidden by bulk quality cleanup: {', '.join(reasons)}"
        entity.reviewed_at = now
        hidden.append(entity)
    db.commit()
    return {
        "checked": len(candidates),
        "hidden": len(hidden),
        "examples": [
            {
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type.value,
                "total_mentions": entity.total_mentions,
                "reasons": EntityExtractor.entity_quality_reasons(entity.name, entity.entity_type.value),
            }
            for entity in hidden[:20]
        ],
    }


@app.get("/api/v1/admin/entities/quality-report")
def entity_quality_report(
    limit: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Summarize likely noisy entities before cleanup."""
    candidates = (
        db.query(Entity)
        .filter(Entity.status.notin_([EntityStatus.APPROVED, EntityStatus.HIDDEN]))
        .order_by(desc(Entity.total_mentions), Entity.name.asc())
        .limit(limit)
        .all()
    )
    reason_counts: dict[str, int] = {}
    suspicious = []
    suspicious_count = 0
    for entity in candidates:
        reasons = EntityExtractor.entity_quality_reasons(entity.name, entity.entity_type.value)
        if not reasons:
            continue
        suspicious_count += 1
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if len(suspicious) < 30:
            suspicious.append({
                "id": entity.id,
                "name": entity.name,
                "entity_type": entity.entity_type.value,
                "status": entity.status.value,
                "total_mentions": entity.total_mentions,
                "reasons": reasons,
            })
    return {
        "checked": len(candidates),
        "suspicious_count": suspicious_count,
        "reason_counts": reason_counts,
        "examples": suspicious,
    }


@app.get("/api/v1/admin/search/quality")
def search_quality_report(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Check Cyrillic/Latin search index readiness for demos and pilots."""
    article_scope = db.query(Article).outerjoin(Source)
    if country_code:
        article_scope = article_scope.filter(Source.country_code == country_code)

    entity_scope = db.query(Entity).filter(Entity.status != EntityStatus.HIDDEN)

    article_count = article_scope.count()
    entity_count = entity_scope.count()
    missing_article_search = article_scope.filter(
        or_(Article.search_text == None, Article.search_text == "")
    ).count()
    missing_entity_search = entity_scope.filter(
        or_(Entity.search_text == None, Entity.search_text == "")
    ).count()

    sample_queries = [
        ("latin_country", "makedonija"),
        ("cyrillic_country", "\u043c\u0430\u043a\u0435\u0434\u043e\u043d\u0438\u0458\u0430"),
        ("latin_capital", "skopje"),
        ("cyrillic_capital", "\u0441\u043a\u043e\u043f\u0458\u0435"),
        ("latin_party", "vmro"),
        ("cyrillic_party", "\u0432\u043c\u0440\u043e"),
        ("latin_party_dui", "dui"),
    ]
    query_checks = []
    for label, value in sample_queries:
        article_query = db.query(Article.id).join(Source).filter(
            Source.country_code == country_code,
            _active_article_filter(),
        )
        article_condition = article_text_match(db, [value])
        if article_condition is not None:
            article_query = article_query.filter(article_condition)
        article_found = article_query.limit(1).first() is not None

        entity_query = db.query(Entity.id).filter(Entity.status != EntityStatus.HIDDEN)
        entity_condition = entity_text_match(db, [value])
        if entity_condition is not None:
            entity_query = entity_query.filter(entity_condition)
        entity_found = entity_query.limit(1).first() is not None
        query_checks.append({
            "label": label,
            "query": value,
            "variants": search_variants(value),
            "article_total": 1 if article_found else 0,
            "entity_total": 1 if entity_found else 0,
            "status": "pass" if article_found or entity_found else "warn",
        })

    missing_total = missing_article_search + missing_entity_search
    weak_queries = [item for item in query_checks if item["status"] != "pass"]
    status = "ready"
    if missing_total:
        status = "needs_backfill"
    elif weak_queries:
        status = "needs_review"

    recommendations = []
    if missing_total:
        recommendations.append("Run scripts/backfill_search_text.py --force after ingestion or entity cleanup.")
    if weak_queries:
        recommendations.append("Review weak demo queries; add aliases to the entity lexicon or ingest more source coverage.")
    if not recommendations:
        recommendations.append("Search normalization looks ready for Cyrillic and Latin demo queries.")

    return {
        "country_code": country_code,
        "status": status,
        "article_count": article_count,
        "entity_count": entity_count,
        "missing_article_search_text": missing_article_search,
        "missing_entity_search_text": missing_entity_search,
        "query_checks": query_checks,
        "recommendations": recommendations,
        "backfill_command": ".\\venv\\Scripts\\python.exe scripts\\backfill_search_text.py --force",
    }


@app.get("/api/v1/admin/entities/lexicon-coverage")
def entity_lexicon_coverage(
    country_code: str = "mk",
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Compare curated country entity lexicon with entities discovered in the DB."""
    path = settings.countries_dir.parent / "entities" / f"{_code_to_filename(country_code)}.yaml"
    data = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    known_entities = []
    known_canonicals = set()
    for item in data.get("entities", []):
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        aliases = [str(alias).strip() for alias in item.get("aliases", []) if str(alias).strip()]
        canonicals = {EntityExtractor._canonicalize(name)}
        canonicals.update(EntityExtractor._canonicalize(alias) for alias in aliases)
        known_canonicals.update(canonicals)
        known_entities.append({
            "name": name,
            "type": item.get("type", "unknown"),
            "aliases": aliases,
            "canonicals": sorted(canonicals),
        })

    db_entities = (
        db.query(Entity)
        .filter(Entity.status != EntityStatus.HIDDEN)
        .order_by(desc(Entity.total_mentions), Entity.name.asc())
        .limit(1000)
        .all()
    )
    db_by_canonical = {
        EntityExtractor._canonicalize(entity.name): entity
        for entity in db_entities
    }
    matched = []
    missing = []
    for item in known_entities:
        match = next(
            (db_by_canonical.get(canonical) for canonical in item["canonicals"] if db_by_canonical.get(canonical)),
            None,
        )
        if match:
            matched.append({
                "lexicon_name": item["name"],
                "db_entity_id": match.id,
                "db_name": match.name,
                "entity_type": match.entity_type.value,
                "total_mentions": match.total_mentions,
                "status": match.status.value,
            })
        else:
            missing.append({
                "name": item["name"],
                "entity_type": item["type"],
                "aliases": item["aliases"],
            })

    uncovered = []
    for entity in db_entities:
        canonical = EntityExtractor._canonicalize(entity.name)
        if canonical in known_canonicals:
            continue
        if not is_likely_entity_name(entity.name, entity.entity_type.value):
            continue
        uncovered.append({
            "entity_id": entity.id,
            "name": entity.name,
            "entity_type": corrected_entity_type(entity.name, entity.entity_type.value),
            "total_mentions": entity.total_mentions,
            "status": entity.status.value,
            "suggested_action": "Add to lexicon if this is a recurring Macedonian political/media entity; otherwise approve/hide in review.",
        })
        if len(uncovered) >= limit:
            break

    recommendations = []
    if missing:
        recommendations.append("Add aliases or ingest more data for curated entities that are not appearing in the database.")
    if uncovered:
        recommendations.append("Review high-mention uncovered entities and add important politicians, parties, institutions, journalists, and media owners to the YAML lexicon.")
    if not recommendations:
        recommendations.append("Curated lexicon coverage looks healthy for the current database sample.")

    return {
        "country_code": country_code,
        "lexicon_path": str(path),
        "known_count": len(known_entities),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "uncovered_count": len(uncovered),
        "matched_examples": matched[:limit],
        "missing_examples": missing[:limit],
        "uncovered_entities": uncovered,
        "recommendations": recommendations,
    }


@app.post("/api/v1/admin/entities/{entity_id}/add-to-lexicon")
def add_entity_to_lexicon(
    entity_id: int,
    request: EntityLexiconAddRequest,
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Append an existing DB entity to the curated country entity lexicon YAML."""
    entity = db.query(Entity).get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    path = settings.countries_dir.parent / "entities" / f"{_code_to_filename(country_code)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("country_code", country_code)
    data.setdefault("entities", [])

    name = entity.name.strip()
    aliases = [alias.strip() for alias in request.aliases if alias.strip()]
    entity_type = request.entity_type or corrected_entity_type(entity.name, entity.entity_type.value)
    canonical_candidates = {EntityExtractor._canonicalize(name)}
    canonical_candidates.update(EntityExtractor._canonicalize(alias) for alias in aliases)
    for item in data.get("entities", []):
        existing = {EntityExtractor._canonicalize(str(item.get("name", "")))}
        existing.update(EntityExtractor._canonicalize(str(alias)) for alias in item.get("aliases", []) or [])
        if canonical_candidates & existing:
            return {
                "status": "already_exists",
                "path": str(path),
                "entity_id": entity.id,
                "name": entity.name,
                "matched_lexicon_name": item.get("name"),
            }

    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup = None
    if path.exists():
        backup = _config_backup_dir() / f"{path.stem}-{stamp}.yaml"
        shutil.copy2(path, backup)

    item = {
        "name": name,
        "type": entity_type,
    }
    if aliases:
        item["aliases"] = aliases
    data["entities"].append(item)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )

    if request.approve_entity:
        entity.status = EntityStatus.APPROVED
        entity.review_notes = "Added to curated country entity lexicon."
        entity.reviewed_at = datetime.datetime.utcnow()
        db.commit()

    return {
        "status": "added",
        "path": str(path),
        "backup": str(backup) if backup else None,
        "entity_id": entity.id,
        "name": name,
        "entity_type": entity_type,
        "aliases": aliases,
    }


@app.post("/api/v1/admin/entities/{entity_id}/merge", response_model=EntityResponse)
def merge_entity(
    entity_id: int,
    request: EntityMergeRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Merge a duplicate entity into a target entity and recompute totals."""
    source = db.query(Entity).get(entity_id)
    target = db.query(Entity).get(request.target_entity_id)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Entity not found")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot merge an entity into itself")

    _merge_entity_records(db, source, target)
    db.commit()
    db.refresh(target)
    return _entity_to_response(target)


# ── Routes: Trends ───────────────────────────────────────────────────

@app.post("/api/v1/admin/entities/merge-lexicon-aliases")
def merge_lexicon_alias_entities(
    country_code: str = "mk",
    limit: int = Query(default=100, ge=1, le=500),
    dry_run: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Merge stored alias entities into their curated lexicon canonical entity."""
    path = settings.countries_dir.parent / "entities" / f"{_code_to_filename(country_code)}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Entity lexicon not found")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    alias_to_target: dict[str, str] = {}
    for item in data.get("entities", []):
        target_name = str(item.get("name", "")).strip()
        if not target_name:
            continue
        target_canonical = EntityExtractor._canonicalize(target_name)
        for alias in item.get("aliases", []) or []:
            alias_canonical = EntityExtractor._canonicalize(str(alias).strip())
            if alias_canonical and alias_canonical != target_canonical:
                alias_to_target[alias_canonical] = target_canonical
    alias_to_target.update({
        "shkup": "\u0441\u043a\u043e\u043f\u0458\u0435",
        "tetove": "\u0442\u0435\u0442\u043e\u0432\u043e",
        "tetov\u00eb": "\u0442\u0435\u0442\u043e\u0432\u043e",
        "tetov\u00ebs": "\u0442\u0435\u0442\u043e\u0432\u043e",
        "rusia": "\u0440\u0443\u0441\u0438\u0458\u0430",
        "shba": "\u0441\u0430\u0434",
    })

    def resolve_target(canonical: str) -> str:
        seen = set()
        while canonical in alias_to_target and canonical not in seen:
            seen.add(canonical)
            canonical = alias_to_target[canonical]
        return canonical

    actions = []
    for alias_canonical, raw_target_canonical in alias_to_target.items():
        if len(actions) >= limit:
            break
        target_canonical = resolve_target(raw_target_canonical)
        if alias_canonical == target_canonical:
            continue
        target = (
            db.query(Entity)
            .filter(Entity.canonical_name == target_canonical, Entity.status != EntityStatus.HIDDEN)
            .order_by(desc(Entity.total_mentions))
            .first()
        )
        if not target:
            continue
        sources = (
            db.query(Entity)
            .filter(
                Entity.canonical_name == alias_canonical,
                Entity.id != target.id,
                Entity.status != EntityStatus.HIDDEN,
            )
            .order_by(desc(Entity.total_mentions))
            .all()
        )
        for source in sources:
            if len(actions) >= limit:
                break
            actions.append({
                "source_id": source.id,
                "source_name": source.name,
                "source_mentions": source.total_mentions,
                "target_id": target.id,
                "target_name": target.name,
                "target_mentions_before": target.total_mentions,
            })
            if not dry_run:
                _merge_entity_records(db, source, target)

    if not dry_run:
        db.commit()
    return {
        "country_code": country_code,
        "dry_run": dry_run,
        "checked_aliases": len(alias_to_target),
        "merged": 0 if dry_run else len(actions),
        "planned": len(actions),
        "actions": actions[:50],
    }


@app.get("/api/v1/entities/{entity_id}/related")
def get_related_entities(
    entity_id: int,
    limit: int = Query(default=12, le=50),
    db: Session = Depends(get_db),
):
    """Get entities that frequently appear in the same articles."""
    entity = db.query(Entity).get(entity_id)
    if not is_client_publishable_entity(entity):
        raise HTTPException(status_code=404, detail="Entity not found")

    article_ids = select(EntityMention.article_id).where(
        EntityMention.entity_id == entity_id
    )

    rows = (
        db.query(
            Entity.id,
            Entity.name,
            Entity.entity_type,
            func.count(func.distinct(EntityMention.article_id)).label("shared_articles"),
            func.sum(EntityMention.mention_count).label("mention_count"),
        )
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .filter(
            EntityMention.article_id.in_(article_ids),
            Entity.id != entity_id,
            client_publishable_entity_filter(),
        )
        .group_by(Entity.id, Entity.name, Entity.entity_type)
        .order_by(desc("shared_articles"), desc("mention_count"))
        .limit(limit)
        .all()
    )

    return [
        {
            "entity_id": row.id,
            "name": row.name,
            "entity_type": row.entity_type.value,
            "shared_articles": row.shared_articles,
            "mention_count": row.mention_count or 0,
        }
        for row in rows
    ]


@app.get("/api/v1/entities/{entity_id}/briefing")
def get_entity_briefing(
    entity_id: int,
    days: int = Query(default=90, le=365),
    db: Session = Depends(get_db),
):
    """Entity dossier briefing with timeline, source coverage, evidence, and copy text."""
    entity = db.query(Entity).get(entity_id)
    if not is_client_publishable_entity(entity):
        raise HTTPException(status_code=404, detail="Entity not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    date_column = func.coalesce(Article.published_at, Article.fetched_at, Article.ingested_at)
    rows = (
        db.query(EntityMention, Article, Source)
        .join(Article, Article.id == EntityMention.article_id)
        .join(Source, Source.id == Article.source_id)
        .filter(EntityMention.entity_id == entity_id)
        .filter(_active_article_filter())
        .filter(date_column >= since)
        .order_by(date_column.desc())
        .limit(80)
        .all()
    )
    articles = [article for _, article, _ in rows if _is_client_usable_article(article)]
    timeline: dict[str, dict] = {}
    source_stats: dict[str, dict] = {}
    sentiment_scores = []
    for mention, article, source in rows:
        article_date = article.published_at or article.fetched_at or article.ingested_at
        if article_date:
            day = article_date.strftime("%Y-%m-%d")
            timeline.setdefault(day, {"date": day, "mentions": 0, "articles": set()})
            timeline[day]["mentions"] += mention.mention_count or 1
            timeline[day]["articles"].add(article.id)
        source_key = source.name if source else "Unknown"
        source_stats.setdefault(source_key, {
            "source_name": source_key,
            "source_type": source.source_type if source else "unknown",
            "reliability_score": source.reliability_score if source else None,
            "article_count": 0,
            "mention_count": 0,
        })
        source_stats[source_key]["article_count"] += 1
        source_stats[source_key]["mention_count"] += mention.mention_count or 1
        if mention.sentiment_score is not None:
            sentiment_scores.append(mention.sentiment_score)

    timeline_rows = [
        {
            "date": row["date"],
            "mentions": row["mentions"],
            "article_count": len(row["articles"]),
        }
        for row in sorted(timeline.values(), key=lambda item: item["date"])
    ]
    source_rows = sorted(
        source_stats.values(),
        key=lambda item: (item["article_count"], item["mention_count"]),
        reverse=True,
    )[:10]
    related = get_related_entities(entity_id, limit=8, db=db)
    evidence_brief = _source_evidence_brief(articles, limit=6)
    article_ids = [article.id for article in articles]
    story_clusters = []
    if article_ids:
        clusters = (
            db.query(StoryCluster)
            .join(StoryClusterArticle, StoryClusterArticle.cluster_id == StoryCluster.id)
            .filter(StoryClusterArticle.article_id.in_(article_ids))
            .order_by(
                StoryCluster.source_count.desc(),
                StoryCluster.article_count.desc(),
                StoryCluster.last_published_at.desc().nullslast(),
            )
            .limit(8)
            .all()
        )
        seen_cluster_ids = set()
        for cluster in clusters:
            if cluster.id in seen_cluster_ids:
                continue
            seen_cluster_ids.add(cluster.id)
            story_clusters.append(_story_cluster_to_response(cluster))
    avg_sentiment = round(sum(sentiment_scores) / max(len(sentiment_scores), 1), 4)
    sentiment_label = "positive" if avg_sentiment > 0.05 else "negative" if avg_sentiment < -0.05 else "neutral"
    headline = f"{entity.name}: {len(articles)} recent sourced articles across {len(source_rows)} sources"
    summary = (
        f"{entity.name} appears as a {corrected_entity_type(entity.name, entity.entity_type.value)} "
        f"with {entity.total_mentions} stored mentions. In the last {days} days, the dossier found "
        f"{len(articles)} usable articles and an overall {sentiment_label} sentiment signal."
    )
    recommended_actions = [
        "Use source-backed article titles as evidence; do not infer facts beyond the articles.",
        "Check the mention timeline before making claims about momentum or escalation.",
        "Verify dates, names, numbers, and legal claims against original URLs before external use.",
    ]
    if related:
        recommended_actions.append("Review connected entities before preparing a response or briefing.")
    if any(cluster["status"] == "single_source" for cluster in story_clusters):
        recommended_actions.append("Treat single-source connected stories as unverified until another source confirms them.")
    if any(cluster["status"] == "validated" for cluster in story_clusters):
        recommended_actions.append("Use validated story clusters as stronger evidence, but still cite original URLs.")
    copy_text = _entity_brief_copy_text(entity.name, summary, evidence_brief, related, recommended_actions)
    return {
        "entity": _entity_to_response(entity),
        "generated_at": datetime.datetime.utcnow(),
        "period_days": days,
        "headline": headline,
        "summary": summary,
        "sentiment": {
            "score": avg_sentiment,
            "label": sentiment_label,
            "scored_mentions": len(sentiment_scores),
        },
        "mention_timeline": timeline_rows,
        "source_coverage": source_rows,
        "connected_entities": related,
        "story_clusters": story_clusters,
        "evidence_brief": evidence_brief,
        "source_articles": [article_to_response(article) for article in articles[:20]],
        "recommended_actions": recommended_actions,
        "copy_text": copy_text,
    }


@app.post("/api/v1/entities/{entity_id}/briefing/report", response_model=ReportResponse)
def generate_entity_briefing_report(
    entity_id: int,
    days: int = Query(default=90, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Generate a PDF dossier for a single entity profile."""
    entity = db.query(Entity).get(entity_id)
    if not is_client_publishable_entity(entity):
        raise HTTPException(status_code=404, detail="Entity not found")

    payload = jsonable_encoder(get_entity_briefing(entity_id, days, db))
    generator = BriefingExportGenerator(settings.reports_dir)
    filepath = generator.generate_entity_briefing(payload)
    date_to = datetime.datetime.utcnow()
    date_from = date_to - datetime.timedelta(days=days)
    article_count = len(payload.get("source_articles") or payload.get("evidence_brief") or [])
    report = Report(
        title=f"Entity Dossier - {entity.name}",
        country_code="mk",
        format=ReportFormat.PDF,
        categories_filter={
            "type": "entity_briefing",
            "entity_id": entity_id,
        },
        date_from=date_from,
        date_to=date_to,
        file_path=str(filepath),
        article_count=article_count,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=report.article_count,
        categories=["entity_briefing"],
        date_range=f"{date_from.strftime('%Y-%m-%d')} to {date_to.strftime('%Y-%m-%d')}",
    )


@app.get("/api/v1/trends", response_model=list[TrendingEntity])
def get_trends(
    days: int = Query(default=7, le=90),
    entity_type: Optional[str] = None,
    country_code: Optional[str] = None,
    limit: int = Query(default=20, le=50),
    db: Session = Depends(get_db),
):
    """Get trending entities."""
    search = SearchEngine(db)
    etype = EntityType(entity_type) if entity_type else None
    trending = search.get_trending_entities(
        days=days, entity_type=etype,
        limit=limit, country_code=country_code,
    )
    return [TrendingEntity(**t) for t in trending]


# ── Routes: Categories ───────────────────────────────────────────────

@app.get("/api/v1/topics/briefing")
def get_topic_briefing(
    q: str = Query(..., min_length=2),
    days: int = Query(default=90, le=365),
    country_code: Optional[str] = "mk",
    db: Session = Depends(get_db),
):
    """Research view for a topic across dates, sources, entities, and evidence."""
    date_to = datetime.datetime.utcnow()
    date_from = date_to - datetime.timedelta(days=days)
    search = SearchEngine(db)
    result = search.search_articles(SearchFilters(
        query=q,
        country_code=country_code,
        date_from=date_from,
        date_to=date_to,
        date_basis="published",
        limit=80,
        offset=0,
    ))
    articles = [article for article in result["articles"] if _is_client_usable_article(article)]
    timeline: dict[str, dict] = {}
    source_stats: dict[str, dict] = {}
    entity_stats: dict[int, dict] = {}

    for article in articles:
        article_date = article.published_at or article.fetched_at or article.ingested_at
        if article_date:
            day = article_date.strftime("%Y-%m-%d")
            timeline.setdefault(day, {"date": day, "article_count": 0, "source_ids": set()})
            timeline[day]["article_count"] += 1
            timeline[day]["source_ids"].add(article.source_id)

        source = article.source
        source_key = source.name if source else "Unknown"
        source_stats.setdefault(source_key, {
            "source_name": source_key,
            "source_type": source.source_type if source else "unknown",
            "reliability_score": source.reliability_score if source else None,
            "article_count": 0,
            "latest_at": None,
        })
        source_stats[source_key]["article_count"] += 1
        latest_at = source_stats[source_key]["latest_at"]
        if article_date and (latest_at is None or article_date > latest_at):
            source_stats[source_key]["latest_at"] = article_date

        for mention in article.entity_mentions:
            entity = mention.entity
            if (
                not is_client_publishable_entity(entity)
                or not is_likely_entity_name(entity.name, entity.entity_type.value)
            ):
                continue
            entity_stats.setdefault(entity.id, {
                "entity_id": entity.id,
                "name": entity.name,
                "entity_type": corrected_entity_type(entity.name, entity.entity_type.value),
                "mention_count": 0,
                "article_ids": set(),
            })
            entity_stats[entity.id]["mention_count"] += mention.mention_count or 1
            entity_stats[entity.id]["article_ids"].add(article.id)

    timeline_rows = [
        {
            "date": item["date"],
            "article_count": item["article_count"],
            "source_count": len(item["source_ids"]),
        }
        for item in sorted(timeline.values(), key=lambda row: row["date"])
    ]
    source_rows = sorted(
        source_stats.values(),
        key=lambda item: (item["article_count"], item.get("reliability_score") or 0),
        reverse=True,
    )[:12]
    entity_rows = []
    for item in entity_stats.values():
        item["article_count"] = len(item.pop("article_ids"))
        entity_rows.append(item)
    entity_rows = sorted(
        entity_rows,
        key=lambda item: (item["article_count"], item["mention_count"]),
        reverse=True,
    )[:12]

    source_count = len(source_stats)
    status = "single_source"
    if source_count >= 5:
        status = "validated"
    elif source_count >= 2:
        status = "multi_source"
    headline = f"{q}: {len(articles)} articles across {source_count} sources"
    summary = (
        f"The stored coverage for '{q}' has {len(articles)} usable articles in the last {days} days. "
        f"Source validation status is {status.replace('_', ' ')}. Use the timeline and source trail "
        "to separate what is widely reported from what still needs independent confirmation."
    )
    recommended_actions = [
        "Use multi-source items first when briefing a client or preparing public remarks.",
        "Treat single-source items as leads until independently verified.",
        "Check exact dates, numbers, names, and legal claims in original URLs before external use.",
    ]
    if source_count <= 1 and articles:
        recommended_actions.insert(0, "Do not present this as broadly confirmed; current stored coverage is single-source.")

    return {
        "query": q,
        "generated_at": datetime.datetime.utcnow(),
        "period_days": days,
        "country_code": country_code,
        "headline": headline,
        "summary": summary,
        "validation_status": status,
        "article_count": len(articles),
        "source_count": source_count,
        "timeline": timeline_rows,
        "source_coverage": source_rows,
        "top_entities": entity_rows,
        "evidence_brief": _source_evidence_brief(articles, limit=6),
        "recent_articles": [article_to_response(article) for article in articles[:12]],
        "recommended_actions": recommended_actions,
    }


@app.get("/api/v1/categories", response_model=list[CategoryStats])
def get_categories(
    days: int = Query(default=7, le=90),
    country_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get article counts per category."""
    search = SearchEngine(db)
    stats = search.get_category_stats(days=days, country_code=country_code)
    return [CategoryStats(**s) for s in stats]


@app.get("/api/v1/narratives")
def get_narratives(
    days: int = Query(default=30, le=365),
    country_code: Optional[str] = None,
    client_id: Optional[int] = None,
    limit: int = Query(default=12, le=50),
    db: Session = Depends(get_db),
):
    """Detect high-level political narratives across articles/posts."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    date_column = func.coalesce(
        Article.published_at, Article.fetched_at, Article.ingested_at
    )
    query = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(_active_article_filter())
        .filter(date_column >= since)
    )
    if country_code:
        query = query.filter(Source.country_code == country_code)

    if client_id:
        client = _get_client_or_404(db, client_id)
        watchlist = _dedupe_watchlist_items(
            db.query(ClientWatchlistItem)
            .filter(ClientWatchlistItem.client_id == client_id)
            .all()
        )
        articles = _matching_watchlist_articles(
            db, client, watchlist, since, limit=500
        )
    else:
        articles = query.order_by(date_column.desc()).limit(500).all()

    narrative_stats: dict[str, dict] = {}
    for article in articles:
        text_value = f"{article.title} {article.content or ''}".lower()
        narratives = _narrative_categories(text_value)
        if not narratives:
            continue

        event_at = article.published_at or article.fetched_at or article.ingested_at
        source_name = article.source.name if article.source else "Unknown"
        for narrative in narratives:
            stats = narrative_stats.setdefault(narrative, {
                "narrative": narrative,
                "article_count": 0,
                "source_count": 0,
                "sources": set(),
                "latest_at": None,
                "examples": [],
            })
            stats["article_count"] += 1
            stats["sources"].add(source_name)
            stats["source_count"] = len(stats["sources"])
            if event_at and (stats["latest_at"] is None or event_at > stats["latest_at"]):
                stats["latest_at"] = event_at
            if len(stats["examples"]) < 3:
                stats["examples"].append({
                    "article_id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "source_name": source_name,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                })

    rows = []
    for stats in narrative_stats.values():
        rows.append({
            "narrative": stats["narrative"],
            "article_count": stats["article_count"],
            "source_count": stats["source_count"],
            "latest_at": stats["latest_at"].isoformat() if stats["latest_at"] else None,
            "examples": stats["examples"],
        })

    return sorted(
        rows,
        key=lambda row: (row["article_count"], row["source_count"]),
        reverse=True,
    )[:limit]


@app.get("/api/v1/story-clusters")
def list_story_clusters(
    days: int = Query(default=14, le=90),
    country_code: str = "mk",
    status: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """List same-story clusters with cross-source validation signals."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    query = (
        db.query(StoryCluster)
        .filter(StoryCluster.country_code == country_code)
        .filter(
            (StoryCluster.last_published_at >= since)
            | (StoryCluster.last_published_at == None)
        )
    )
    if status:
        query = query.filter(StoryCluster.status == status)
    clusters = (
        query.order_by(
            StoryCluster.source_count.desc(),
            StoryCluster.article_count.desc(),
            StoryCluster.last_published_at.desc().nullslast(),
        )
        .limit(limit)
        .all()
    )
    return [_story_cluster_to_response(cluster) for cluster in clusters]


@app.get("/api/v1/story-spread")
def list_story_spread(
    days: int = Query(default=7, le=90),
    country_code: str = "mk",
    limit: int = Query(default=12, le=50),
    db: Session = Depends(get_db),
):
    """Rank stories by original-source spread and aggregator amplification."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    clusters = (
        db.query(StoryCluster)
        .filter(StoryCluster.country_code == country_code)
        .filter(
            (StoryCluster.last_published_at >= since)
            | (StoryCluster.last_published_at == None)
        )
        .order_by(
            StoryCluster.source_count.desc(),
            StoryCluster.article_count.desc(),
            StoryCluster.last_published_at.desc().nullslast(),
        )
        .limit(limit * 3)
        .all()
    )
    rows = []
    for cluster in clusters:
        item = _story_cluster_to_response(cluster)
        spread_hours = item.get("spread_hours") or 24
        velocity = round(item["article_count"] / max(1, spread_hours), 2)
        spread_score = (
            item["original_source_count"] * 12
            + item["aggregator_source_count"] * 4
            + item["high_reliability_source_count"] * 5
            + min(12, item["article_count"])
            + min(10, velocity * 2)
        )
        item["spread_score"] = round(spread_score, 1)
        item["spread_velocity"] = velocity
        item["spread_label"] = (
            "validated_spread" if item["status"] == "validated"
            else "multi_source_spread" if item["original_source_count"] >= 2
            else "aggregator_seen" if item["aggregator_source_count"]
            else "single_source"
        )
        rows.append(item)
    rows.sort(key=lambda row: (row["spread_score"], row["last_published_at"] or ""), reverse=True)
    return {
        "country_code": country_code,
        "period_days": days,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "stories": rows[:limit],
        "summary": {
            "validated": len([row for row in rows if row["status"] == "validated"]),
            "multi_source": len([row for row in rows if row["original_source_count"] >= 2]),
            "aggregator_indexed": len([row for row in rows if row["aggregator_source_count"] > 0]),
            "single_source": len([row for row in rows if row["status"] == "single_source"]),
        },
    }


@app.get("/api/v1/risk/political", response_model=PoliticalRiskResponse)
def get_political_risk(
    country_code: str = "mk",
    days: int = Query(default=7, le=90),
    db: Session = Depends(get_db),
):
    """Country-wide political/media risk score."""
    result = PoliticalRiskScorer(db).country_risk(country_code=country_code, days=days)
    return PoliticalRiskResponse(
        score=result.score,
        level=result.level,
        drivers=result.drivers,
        breakdown=result.breakdown,
        metrics=result.metrics,
        items=result.items,
        events=result.events,
        alert_suggestions=result.alert_suggestions,
    )


@app.get("/api/v1/briefs/daily")
def get_daily_intelligence_brief(
    country_code: str = "mk",
    days: int = Query(default=1, le=30),
    db: Session = Depends(get_db),
):
    """One-page daily intelligence brief for dashboards, email, and PDF."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    risk = PoliticalRiskScorer(db).country_risk(country_code=country_code, days=max(days, 7))
    clusters = (
        db.query(StoryCluster)
        .filter(StoryCluster.country_code == country_code)
        .filter(
            (StoryCluster.last_published_at >= since)
            | (StoryCluster.last_published_at == None)
        )
        .order_by(
            StoryCluster.source_count.desc(),
            StoryCluster.article_count.desc(),
            StoryCluster.last_published_at.desc().nullslast(),
        )
        .limit(5)
        .all()
    )
    search = SearchEngine(db)
    trends = search.get_trending_entities(days=max(days, 7), country_code=country_code, limit=5)
    articles = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(Source.country_code == country_code)
        .filter(func.coalesce(Article.published_at, Article.fetched_at, Article.ingested_at) >= since)
        .order_by(func.coalesce(Article.published_at, Article.fetched_at, Article.ingested_at).desc())
        .limit(8)
        .all()
    )
    narratives = get_narratives(days=max(days, 7), country_code=country_code, limit=5, db=db)
    headline = _brief_headline(risk.level, clusters, trends)
    recommended_actions = _brief_recommended_actions(risk, clusters)
    return {
        "country_code": country_code,
        "generated_at": datetime.datetime.utcnow(),
        "period_days": days,
        "headline": headline,
        "risk": {
            "score": risk.score,
            "level": risk.level,
            "drivers": risk.drivers[:5],
            "breakdown": risk.breakdown,
            "metrics": risk.metrics,
            "events": risk.events[:5],
            "alert_suggestions": risk.alert_suggestions,
        },
        "validated_stories": [_story_cluster_to_response(cluster) for cluster in clusters],
        "trending_entities": trends,
        "narratives": narratives,
        "top_articles": [article_to_response(article) for article in articles],
        "recommended_actions": recommended_actions,
    }


@app.get("/api/v1/clients/{client_id}/risk", response_model=PoliticalRiskResponse)
def get_client_risk(
    client_id: int,
    days: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Client-specific risk score from watchlist matches."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    result = PoliticalRiskScorer(db).client_risk(client_id=client_id, days=days)
    return PoliticalRiskResponse(
        score=result.score,
        level=result.level,
        drivers=result.drivers,
        breakdown=result.breakdown,
        metrics=result.metrics,
        items=result.items,
        events=result.events,
        alert_suggestions=result.alert_suggestions,
    )


@app.post("/api/v1/admin/story-clusters/rebuild")
def rebuild_story_clusters(
    country_code: str = "mk",
    days: int = Query(default=14, le=90),
    limit: int = Query(default=1000, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Rebuild story clusters after ingestion/reprocessing."""
    return StoryClusterer(db).rebuild(country_code=country_code, days=days, limit=limit)


# ── Routes: Reports ──────────────────────────────────────────────────

@app.get("/api/v1/admin/ingestion/runs")
def list_ingestion_runs(
    country_code: str = "mk",
    limit: int = Query(default=10, le=50),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List recent ingestion runs with totals."""
    runs = (
        db.query(IngestionRun)
        .filter(IngestionRun.country_code == country_code)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": run.id,
            "country_code": run.country_code,
            "run_type": run.run_type,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "total_sources": run.total_sources,
            "total_raw": run.total_raw,
            "total_new": run.total_new,
            "total_duplicate": run.total_duplicate,
            "total_duplicate_fuzzy": run.total_duplicate_fuzzy,
            "total_error": run.total_error,
            "notes": run.notes,
        }
        for run in runs
    ]


@app.get("/api/v1/admin/scheduler/status")
def get_scheduler_status(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return inferred scheduler status, commands, and freshness signals."""
    run = (
        db.query(IngestionRun)
        .filter(IngestionRun.country_code == country_code)
        .order_by(IngestionRun.started_at.desc())
        .first()
    )
    interval = settings.ingestion_interval_minutes
    stale_minutes = None
    next_expected_at = None
    inferred_running = False
    status = "no_runs"
    if run:
        anchor = run.finished_at or run.started_at
        if anchor:
            stale_minutes = round((datetime.datetime.utcnow() - anchor).total_seconds() / 60)
            next_expected_at = anchor + datetime.timedelta(minutes=interval)
            inferred_running = run.status == "running" or stale_minutes <= interval * 2
        if run.status == "running":
            status = "running"
        elif inferred_running:
            status = "healthy"
        else:
            status = "stale"

    root = Path.cwd()
    command = f".\\scripts\\start_scheduler.ps1 -Country {country_code} -IntervalMinutes {interval} -NoEmail"
    return {
        "country_code": country_code,
        "status": status,
        "inferred_running": inferred_running,
        "process": _scheduler_process_status(),
        "heartbeat": _scheduler_heartbeat_status(),
        "interval_minutes": interval,
        "last_run_at": (run.finished_at or run.started_at).isoformat() if run else None,
        "last_run_status": run.status if run else None,
        "last_run_id": run.id if run else None,
        "next_expected_run_at": next_expected_at.isoformat() if next_expected_at else None,
        "stale_minutes": stale_minutes,
        "stale_warning": stale_minutes is None or stale_minutes > interval * 2,
        "start_command": command,
        "stop_hint": "Stop the scheduler process from Windows Task Manager or PowerShell if needed.",
        "logs": {
            "stdout": str(root / "data" / "scheduler.out.log"),
            "stderr": str(root / "data" / "scheduler.err.log"),
        },
    }


@app.get("/api/v1/admin/live-ops")
def get_live_operations_status(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """One-screen operational readiness for scheduled ingestion."""
    scheduler = get_scheduler_status(country_code=country_code, db=db, _=_)
    source_health = list_ingestion_source_health(country_code=country_code, db=db, _=_)
    run = source_health.get("run") or {}
    source_summary = source_health.get("summary") or {}
    sources = source_health.get("sources") or []

    attention_sources = [
        source for source in sources
        if source.get("status") in {"error", "degraded", "no_links"}
        or source.get("error_count", 0) > 0
        or source.get("failed_count", 0) > 0
    ]
    caught_up_sources = [source for source in sources if source.get("stopped_early")]
    duplicate_total = sum(
        source.get("duplicate_count", 0) + source.get("duplicate_fuzzy_count", 0)
        for source in sources
    )
    new_total = sum(source.get("new_count", 0) for source in sources)
    raw_total = sum(source.get("raw_count", 0) for source in sources)
    duplicate_rate = round(duplicate_total / raw_total, 3) if raw_total else 0

    recommendations = []
    if scheduler.get("stale_warning"):
        recommendations.append("Start the scheduler or run one ingestion cycle before relying on latest coverage.")
    if not scheduler.get("process", {}).get("running"):
        recommendations.append("Scheduler process is not currently running from the tracked PID file.")
    if attention_sources:
        recommendations.append("Open source failure drilldown for the highest-value sources needing attention.")
    if not caught_up_sources and raw_total:
        recommendations.append("Duplicate stopping has not triggered recently; watch for repeated full-source crawls.")
    if not recommendations:
        recommendations.append("Live operations look ready for continuous monitoring.")

    overall = "healthy"
    if scheduler.get("stale_warning") or attention_sources:
        overall = "watch"
    if not run or run.get("status") == "failed" or (scheduler.get("stale_warning") and not scheduler.get("process", {}).get("running")):
        overall = "action_required"

    return {
        "country_code": country_code,
        "overall": overall,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "target_interval_minutes": settings.ingestion_interval_minutes,
        "duplicate_stop_threshold": settings.stop_after_consecutive_duplicates,
        "scheduler": {
            "status": scheduler.get("status"),
            "process_running": scheduler.get("process", {}).get("running"),
            "heartbeat_healthy": scheduler.get("heartbeat", {}).get("healthy"),
            "heartbeat_age_minutes": scheduler.get("heartbeat", {}).get("age_minutes"),
            "stale_minutes": scheduler.get("stale_minutes"),
            "stale_warning": scheduler.get("stale_warning"),
            "next_expected_run_at": scheduler.get("next_expected_run_at"),
        },
        "last_run": run,
        "ingestion": {
            "raw_total": raw_total,
            "new_total": new_total,
            "duplicate_total": duplicate_total,
            "duplicate_rate": duplicate_rate,
            "caught_up_sources": len(caught_up_sources),
            "attention_sources": len(attention_sources),
            "healthy_sources": source_summary.get("healthy_count", 0),
            "rss_only_sources": source_summary.get("rss_only_count", 0),
        },
        "attention_sources": attention_sources[:8],
        "caught_up_sources": caught_up_sources[:8],
        "recommendations": recommendations,
    }


@app.post("/api/v1/admin/scheduler/start")
def start_scheduler(
    country_code: str = "mk",
    interval_minutes: Optional[int] = None,
    no_email: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Start the local scheduler process and record a PID file."""
    current = _scheduler_process_status()
    if current["running"]:
        return {"status": "already_running", **current}

    root = settings.base_dir
    log_dir = root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "scheduler.out.log"
    err_log = log_dir / "scheduler.err.log"
    interval = interval_minutes or settings.ingestion_interval_minutes
    command = [
        sys.executable,
        str(root / "scripts" / "scheduler.py"),
        "--country",
        country_code,
        "--interval-minutes",
        str(interval),
    ]
    if no_email:
        command.append("--no-email")

    with out_log.open("ab") as stdout, err_log.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=stdout,
            stderr=stderr,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    _scheduler_pid_file().write_text(str(process.pid), encoding="utf-8")
    return {
        "status": "started",
        "pid": process.pid,
        "interval_minutes": interval,
        "stdout": str(out_log),
        "stderr": str(err_log),
    }


@app.post("/api/v1/admin/scheduler/stop")
def stop_scheduler(
    _: User = Depends(require_admin),
):
    """Stop the scheduler process recorded in the local PID file."""
    status = _scheduler_process_status()
    if not status["pid"]:
        return {"status": "not_running", **status}
    try:
        if status["running"]:
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(status["pid"]), "/T", "/F"], check=False, capture_output=True)
            else:
                import os
                os.kill(status["pid"], signal.SIGTERM)
        _scheduler_pid_file().unlink(missing_ok=True)
        return {"status": "stopped", "pid": status["pid"]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not stop scheduler: {exc}") from exc


@app.post("/api/v1/admin/scheduler/run-once")
def run_scheduler_once(
    country_code: str = "mk",
    _: User = Depends(require_admin),
):
    """Run one scheduler ingestion cycle in a background process."""
    root = settings.base_dir
    log_dir = root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "scheduler.run_once.out.log"
    err_log = log_dir / "scheduler.run_once.err.log"
    command = [
        sys.executable,
        str(root / "scripts" / "scheduler.py"),
        "--country",
        country_code,
        "--run-once",
        "--no-email",
    ]
    with out_log.open("ab") as stdout, err_log.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=stdout,
            stderr=stderr,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return {"status": "started", "pid": process.pid, "stdout": str(out_log), "stderr": str(err_log)}


@app.get("/api/v1/admin/backups")
def list_backups(_: User = Depends(require_admin)):
    """List local database backups."""
    backup_dir = _backup_dir()
    backups = []
    for path in sorted(backup_dir.glob("newsintel-*.db"), reverse=True):
        stat = path.stat()
        backups.append({
            "filename": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {
        "database_url": settings.database_url,
        "backup_dir": str(backup_dir),
        "latest": backups[0] if backups else None,
        "backups": backups[:20],
        "restore_note": (
            "For safety, restore is a manual operation: stop API/scheduler, copy the backup over data/newsintel.db, then restart."
            if settings.database_url.startswith("sqlite:///") else
            "For PostgreSQL, use pg_dump/pg_restore with your production credentials."
        ),
    }


@app.post("/api/v1/admin/backups/create")
def create_backup(_: User = Depends(require_admin)):
    """Create a timestamped local DB backup for SQLite deployments."""
    if not settings.database_url.startswith("sqlite:///"):
        raise HTTPException(status_code=400, detail="Automatic backup is only available for SQLite. Use pg_dump for PostgreSQL.")
    db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"Database file not found: {db_path}")
    backup_dir = _backup_dir()
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"newsintel-{stamp}.db"
    shutil.copy2(db_path, target)
    return {
        "status": "created",
        "filename": target.name,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "created_at": datetime.datetime.fromtimestamp(target.stat().st_mtime).isoformat(),
    }


@app.post("/api/v1/admin/backups/restore-plan")
def backup_restore_plan(
    filename: str,
    _: User = Depends(require_admin),
):
    """Return safe manual restore steps for a selected backup."""
    backup = _backup_dir() / filename
    if not backup.exists() or backup.parent != _backup_dir():
        raise HTTPException(status_code=404, detail="Backup not found")
    db_path = (
        Path(settings.database_url.replace("sqlite:///", "", 1))
        if settings.database_url.startswith("sqlite:///") else None
    )
    return {
        "backup": str(backup),
        "database": str(db_path) if db_path else settings.database_url,
        "steps": [
            "Stop the scheduler from the Admin dashboard.",
            "Stop the API server.",
            f"Copy {backup} over {db_path or 'the production database using pg_restore'}.",
            "Restart the API server.",
            "Run scripts/smoke_test.py before re-enabling the scheduler.",
        ],
    }


@app.get("/api/v1/admin/clients/brief-readiness")
def list_client_brief_readiness(
    days: int = Query(default=1, le=30),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Show whether each client has enough fresh coverage for a daily digest."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    clients = (
        db.query(Client)
        .filter(Client.is_active == True)
        .order_by(Client.name.asc())
        .all()
    )
    client_ids = [client.id for client in clients]
    watchlist_rows = (
        db.query(ClientWatchlistItem)
        .filter(ClientWatchlistItem.client_id.in_(client_ids))
        .order_by(ClientWatchlistItem.priority.asc())
        .all()
        if client_ids else []
    )
    watchlist_by_client: dict[int, list[ClientWatchlistItem]] = {}
    for item in watchlist_rows:
        watchlist_by_client.setdefault(item.client_id, []).append(item)
    countries = {client.country_code for client in clients}
    date_column = func.coalesce(
        Article.published_at, Article.fetched_at, Article.ingested_at
    )
    recent_articles = (
        db.query(Article)
        .options(joinedload(Article.source))
        .join(Source, Source.id == Article.source_id)
        .filter(Source.country_code.in_(countries))
        .filter(_active_article_filter())
        .filter(date_column >= since)
        .order_by(date_column.desc())
        .limit(2000)
        .all()
        if countries else []
    )
    recent_article_ids = [article.id for article in recent_articles]
    entity_ids = {
        item.entity_id
        for item in watchlist_rows
        if item.entity_id
    }
    entity_article_pairs = (
        db.query(EntityMention.article_id, EntityMention.entity_id)
        .filter(
            EntityMention.article_id.in_(recent_article_ids),
            EntityMention.entity_id.in_(entity_ids),
        )
        .all()
        if recent_article_ids and entity_ids else []
    )
    article_entity_ids: dict[int, set[int]] = {}
    for article_id, entity_id in entity_article_pairs:
        article_entity_ids.setdefault(article_id, set()).add(entity_id)

    rows = []
    for client in clients:
        watchlist = _dedupe_watchlist_items(
            watchlist_by_client.get(client.id, [])
        )
        articles = [
            article
            for article in recent_articles
            if article.source
            and article.source.country_code == client.country_code
            and _readiness_article_matches(
                article,
                watchlist,
                article_entity_ids.get(article.id, set()),
            )
        ][:20]
        source_count = len({article.source_id for article in articles})
        attack_article_count = sum(
            1
            for article in articles
            if _contains_attack_language(
                f"{article.title or ''} {(article.content or '')[:1500]}"
            )
        )
        risk_signal_count = 1 if attack_article_count else 0
        high_risk = (
            1
            if attack_article_count >= 2 and source_count >= 2
            else 0
        )
        ready = len(articles) >= 3 or bool(risk_signal_count)
        rows.append({
            "client_id": client.id,
            "client_name": client.name,
            "client_type": client.client_type.value,
            "plan": client.plan.value,
            "watchlist_items": len(watchlist),
            "matched_articles": len(articles),
            "source_count": source_count,
            "risk_items": risk_signal_count,
            "high_risk_items": high_risk,
            "ready": ready,
            "status": "ready" if ready else "thin",
            "recommendation": (
                "Ready to send: review evidence and copy/export the client brief."
                if ready else
                "Not enough fresh watchlist coverage; broaden watchlist or wait for next ingestion."
            ),
        })
    return rows


def _readiness_article_matches(
    article: Article,
    watchlist: list[ClientWatchlistItem],
    mentioned_entity_ids: set[int],
) -> bool:
    """Fast bounded matching for the admin readiness overview."""
    blob = (article.search_text or f"{article.title or ''} {article.content or ''}").casefold()
    for item in watchlist:
        if (
            item.entity_id
            and item.item_type in {
                WatchlistItemType.ENTITY,
                WatchlistItemType.OPPONENT,
            }
            and item.entity_id in mentioned_entity_ids
        ):
            return True
        if (
            item.source_id
            and item.item_type == WatchlistItemType.SOURCE
            and item.source_id == article.source_id
        ):
            return True
        if item.item_type in {
            WatchlistItemType.KEYWORD,
            WatchlistItemType.TOPIC,
            WatchlistItemType.FACEBOOK_PAGE,
        }:
            terms = [item.value]
            if any(
                variant.casefold() in blob
                for term in terms
                for variant in search_variants(term)
                if variant
            ):
                return True
    return False


@app.get("/api/v1/admin/ingestion/source-health")
def list_ingestion_source_health(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return per-source stats for the latest ingestion run."""
    run = (
        db.query(IngestionRun)
        .filter(IngestionRun.country_code == country_code)
        .order_by(IngestionRun.started_at.desc())
        .first()
    )
    if not run:
        return {"run": None, "sources": [], "summary": {"recommendations": ["Run ingestion once to populate source health."]}}
    rows = (
        db.query(IngestionSourceStat)
        .filter(IngestionSourceStat.run_id == run.id)
        .order_by(IngestionSourceStat.source_name.asc())
        .all()
    )
    attention_statuses = {"error", "degraded", "no_links", "no_posts", "failing"}

    def is_parked_social(row: IngestionSourceStat) -> bool:
        return (
            row.source_name == "Facebook Pages"
            and row.source_type == "social_media"
            and row.status == "no_posts"
            and not settings.facebook_access_token
        )

    attention_rows = [
        row
        for row in rows
        if not is_parked_social(row)
        and (row.status in attention_statuses or row.error_count)
    ]
    stale_minutes = None
    if run.finished_at:
        stale_minutes = round((datetime.datetime.utcnow() - run.finished_at).total_seconds() / 60)
    recommendations = []
    if stale_minutes is not None and stale_minutes > settings.ingestion_interval_minutes * 2:
        recommendations.append(
            f"Last completed run is {stale_minutes} minutes old; scheduler may need attention."
        )
    for row in attention_rows[:5]:
        if row.status == "no_links":
            recommendations.append(f"{row.source_name}: scraper discovered no article links; check selectors.")
        elif row.status == "error":
            recommendations.append(f"{row.source_name}: ingestion errors reported; inspect source config.")
        elif row.status == "degraded":
            recommendations.append(f"{row.source_name}: scraper/RSS returned little usable content.")
        elif row.status == "no_posts":
            recommendations.append(f"{row.source_name}: no posts found in latest check.")
        elif row.error_count:
            recommendations.append(f"{row.source_name}: {row.error_count} failed items in latest run.")
    if not recommendations:
        recommendations.append("Latest ingestion run looks healthy.")
    return {
        "run": {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "total_sources": run.total_sources,
            "total_raw": run.total_raw,
            "total_new": run.total_new,
            "total_duplicate": run.total_duplicate,
            "total_duplicate_fuzzy": run.total_duplicate_fuzzy,
            "total_error": run.total_error,
        },
        "summary": {
            "latest_run_age_minutes": stale_minutes,
            "healthy_count": len([row for row in rows if row.status == "healthy"]),
            "caught_up_count": len([row for row in rows if row.status == "caught_up"]),
            "rss_only_count": len([row for row in rows if row.status == "rss_only"]),
            "parked_social_count": len([row for row in rows if is_parked_social(row)]),
            "attention_count": len(attention_rows),
            "recommendations": recommendations[:6],
        },
        "sources": [
            {
                "id": row.id,
                "source_name": row.source_name,
                "source_url": row.source_url,
                "source_type": row.source_type,
                "scraper_enabled": row.scraper_enabled,
                "rss_enabled": row.rss_enabled,
                "discovered_urls": row.discovered_urls,
                "scraped_count": row.scraped_count,
                "rss_count": row.rss_count,
                "raw_count": row.raw_count,
                "checked_count": row.checked_count,
                "new_count": row.new_count,
                "duplicate_count": row.duplicate_count,
                "duplicate_fuzzy_count": row.duplicate_fuzzy_count,
                "duplicate_streak": row.duplicate_streak,
                "stopped_early": row.stopped_early,
                "error_count": row.error_count,
                "success_count": row.success_count,
                "failed_count": row.failed_count,
                "average_word_count": row.average_word_count,
                "status": row.status,
                "error_sample": row.error_sample,
                "checked_at": row.checked_at,
            }
            for row in rows
        ],
    }


@app.get("/api/v1/admin/ingestion/source-reliability")
def list_ingestion_source_reliability(
    country_code: str = "mk",
    runs: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Roll up recent ingestion health into an operator-friendly source scorecard."""
    recent_runs = (
        db.query(IngestionRun)
        .filter(IngestionRun.country_code == country_code)
        .order_by(IngestionRun.started_at.desc())
        .limit(runs)
        .all()
    )
    if not recent_runs:
        return {
            "country_code": country_code,
            "run_count": 0,
            "sources": [],
            "summary": {
                "average_score": 0,
                "excellent_count": 0,
                "stable_count": 0,
                "watch_count": 0,
                "broken_count": 0,
                "recommendations": ["Run ingestion to build source reliability history."],
            },
        }

    run_ids = [run.id for run in recent_runs]
    stats = (
        db.query(IngestionSourceStat)
        .filter(IngestionSourceStat.run_id.in_(run_ids))
        .all()
    )
    source_meta = {
        source.name: source
        for source in db.query(Source).filter(Source.country_code == country_code).all()
    }
    grouped: dict[str, list[IngestionSourceStat]] = {}
    for row in stats:
        grouped.setdefault(row.source_name, []).append(row)

    rows = []
    for source_name, items in grouped.items():
        items = sorted(items, key=lambda item: item.checked_at or datetime.datetime.min, reverse=True)
        attempts = len(items)
        raw_total = sum(item.raw_count for item in items)
        new_total = sum(item.new_count for item in items)
        duplicate_total = sum(item.duplicate_count + item.duplicate_fuzzy_count for item in items)
        error_total = sum(item.error_count + item.failed_count for item in items)
        healthy_runs = sum(1 for item in items if item.status in {"healthy", "caught_up", "rss_only"})
        attention_runs = sum(1 for item in items if item.status in {"error", "degraded", "no_links", "no_posts", "failing"} or item.error_count)
        stopped_early_runs = sum(1 for item in items if item.stopped_early)
        duplicate_rate = duplicate_total / max(1, raw_total)
        error_rate = error_total / max(1, raw_total + error_total)
        freshness = items[0].checked_at if items else None
        latest = items[0]

        score = 100
        score -= min(45, round(error_rate * 100))
        score -= attention_runs * 8
        score -= 12 if all(item.raw_count == 0 for item in items) else 0
        score += min(15, healthy_runs * 4)
        score += 5 if stopped_early_runs else 0
        score = max(0, min(100, score))
        if latest.status == "disabled":
            score = 0
            status = "disabled"
        elif latest.status in {"failing", "no_links", "error"} and raw_total == 0:
            status = "broken"
            score = min(score, 30)
        else:
            status = "excellent" if score >= 85 else "stable" if score >= 70 else "watch" if score >= 45 else "broken"

        recommendations = []
        if latest.status == "no_links":
            recommendations.append("Check scraper selectors; latest run discovered no article links.")
        if latest.status == "disabled":
            recommendations.append("Source is disabled in configuration; re-enable only when needed.")
        if latest.status == "failing":
            recommendations.append("Source produced no usable items; run scraper preflight and inspect RSS availability.")
        if latest.status == "error" or latest.error_count:
            recommendations.append("Inspect latest error sample and source availability.")
        if latest.status == "degraded":
            recommendations.append("Review extraction quality and minimum text length.")
        if duplicate_rate > 0.75 and new_total <= 2:
            recommendations.append("Duplicate rate is high; stop-on-duplicates is working, but source may be caught up.")
        if not recommendations:
            recommendations.append("Source looks reliable across recent runs.")

        meta = source_meta.get(source_name)
        rows.append({
            "source_name": source_name,
            "source_url": latest.source_url,
            "source_type": latest.source_type,
            "configured_reliability": meta.reliability_score if meta else None,
            "political_leaning": meta.political_leaning if meta else "unknown",
            "ownership": meta.ownership if meta else None,
            "score": score,
            "status": status,
            "attempts": attempts,
            "healthy_runs": healthy_runs,
            "attention_runs": attention_runs,
            "raw_total": raw_total,
            "new_total": new_total,
            "duplicate_total": duplicate_total,
            "duplicate_rate": round(duplicate_rate, 3),
            "error_total": error_total,
            "error_rate": round(error_rate, 3),
            "stopped_early_runs": stopped_early_runs,
            "latest_status": latest.status,
            "latest_checked_at": freshness,
            "latest_error_sample": latest.error_sample,
            "recommendations": recommendations[:3],
        })

    rows.sort(key=lambda row: (row["score"], row["new_total"]), reverse=True)
    average_score = round(sum(row["score"] for row in rows) / max(1, len(rows)))
    summary = {
        "average_score": average_score,
        "excellent_count": len([row for row in rows if row["status"] == "excellent"]),
        "stable_count": len([row for row in rows if row["status"] == "stable"]),
        "watch_count": len([row for row in rows if row["status"] == "watch"]),
        "broken_count": len([row for row in rows if row["status"] == "broken"]),
        "disabled_count": len([row for row in rows if row["status"] == "disabled"]),
        "recommendations": [
            f"{row['source_name']}: {row['recommendations'][0]}"
            for row in rows
            if row["status"] in {"watch", "broken"}
        ][:6] or ["Recent source reliability looks usable for demos and monitoring."],
    }
    return {
        "country_code": country_code,
        "run_count": len(recent_runs),
        "sources": rows,
        "summary": summary,
    }


@app.get("/api/v1/admin/ingestion/source-health/{source_name}")
def get_source_failure_drilldown(
    source_name: str,
    country_code: str = "mk",
    limit: int = Query(default=10, le=50),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Inspect recent ingestion stats/errors for one source."""
    source = (
        db.query(Source)
        .filter(Source.country_code == country_code, Source.name == source_name)
        .first()
    )
    rows = (
        db.query(IngestionSourceStat)
        .filter(IngestionSourceStat.source_name == source_name)
        .order_by(IngestionSourceStat.checked_at.desc())
        .limit(limit)
        .all()
    )
    latest = rows[0] if rows else None
    suggested_fix = "No recent stats; run ingestion to populate diagnostics."
    if latest:
        if latest.status == "no_links":
            suggested_fix = "Check scraper include/exclude patterns and article link selectors for this portal."
        elif latest.status == "error" or latest.error_count:
            suggested_fix = "Open the source URL and inspect the latest error sample; the site may block requests or selectors may be stale."
        elif latest.status == "degraded":
            suggested_fix = "Review article extraction quality and minimum word count; scraper may be collecting non-article pages."
        elif latest.duplicate_streak:
            suggested_fix = "Source appears caught up; duplicate stop logic is protecting the run."
        else:
            suggested_fix = "Recent source checks look usable."
    return {
        "source": _source_admin_response(source) if source else None,
        "suggested_fix": suggested_fix,
        "latest_error": latest.error_sample if latest else None,
        "recent_runs": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "status": row.status,
                "checked_at": row.checked_at,
                "discovered_urls": row.discovered_urls,
                "scraped_count": row.scraped_count,
                "rss_count": row.rss_count,
                "raw_count": row.raw_count,
                "new_count": row.new_count,
                "duplicate_count": row.duplicate_count,
                "duplicate_fuzzy_count": row.duplicate_fuzzy_count,
                "duplicate_streak": row.duplicate_streak,
                "stopped_early": row.stopped_early,
                "error_count": row.error_count,
                "failed_count": row.failed_count,
                "average_word_count": row.average_word_count,
                "error_sample": row.error_sample,
            }
            for row in rows
        ],
    }


@app.patch("/api/v1/admin/sources/{source_id}")
def update_source_config(
    source_id: int,
    request: SourceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Edit source metadata used by reliability, filtering, and dashboards."""
    source = db.query(Source).get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    for field in ("is_active", "reliability_score", "source_type", "political_leaning", "ownership", "language"):
        value = getattr(request, field)
        if value is not None:
            setattr(source, field, value)
    db.commit()
    db.refresh(source)
    yaml_result = None
    if request.persist_to_yaml:
        yaml_result = _persist_source_config_to_yaml(source, request)
    response = _source_admin_response(source)
    response["yaml_persistence"] = yaml_result
    return response


@app.get("/api/v1/admin/sources/config-validation")
def validate_source_config(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Validate country source YAML without running network fetches."""
    return _source_config_validation_report(country_code, db)


@app.post("/api/v1/admin/sources/sync-from-config")
def sync_sources_from_config(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create/update DB source rows from country YAML without deleting DB-only sources."""
    country_config = _load_country_config(country_code)
    created = []
    updated = []
    unchanged = []
    for source_config in country_config.get("sources", []):
        result = _sync_source_config_to_db(source_config, country_code, db)
        if result["status"] == "created":
            created.append(result)
        elif result["status"] == "updated":
            updated.append(result)
        else:
            unchanged.append(result)
    db.commit()
    validation = _source_config_validation_report(country_code, db)
    return {
        "country_code": country_code,
        "created_count": len(created),
        "updated_count": len(updated),
        "unchanged_count": len(unchanged),
        "created": created,
        "updated": updated,
        "unchanged": unchanged[:20],
        "db_only_sources": validation.get("db_only_sources", []),
        "validation_summary": validation.get("summary", {}),
    }


@app.post("/api/v1/admin/sources/{source_id}/scraper-preflight")
def run_source_scraper_preflight(
    source_id: int,
    max_articles: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Run a focused scraper preflight for one configured source."""
    source = db.query(Source).get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    country_config = _load_country_config(source.country_code)
    source_config = _find_source_config(country_config, source.name)
    if not source_config:
        raise HTTPException(status_code=404, detail="Source not found in country YAML config")
    source_config = {**source_config, "country_code": source.country_code}
    return _scraper_preflight_result(source_config, max_articles=max_articles)


@app.post("/api/v1/admin/scrapers/preflight")
def run_scraper_preflight(
    country_code: str = "mk",
    max_sources: int = Query(default=6, ge=1, le=25),
    max_articles: int = Query(default=2, ge=1, le=5),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Run a bounded scraper preflight across enabled sources."""
    country_config = _load_country_config(country_code)
    rows = []
    for source_config in country_config.get("sources", [])[:max_sources]:
        rows.append(_scraper_preflight_result(
            {**source_config, "country_code": country_code},
            max_articles=max_articles,
        ))
    summary = {
        "healthy": len([row for row in rows if row["status"] == "healthy"]),
        "degraded": len([row for row in rows if row["status"] == "degraded"]),
        "failing": len([row for row in rows if row["status"] in {"failing", "no_links", "error"}]),
        "disabled": len([row for row in rows if row["status"] == "disabled"]),
    }
    return {"country_code": country_code, "summary": summary, "sources": rows}


@app.get("/api/v1/admin/launch-checklist")
def get_launch_checklist(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Pilot/demo readiness checklist from operational signals."""
    scheduler = get_scheduler_status(country_code=country_code, db=db, _=_)
    source_health = list_ingestion_source_health(country_code=country_code, db=db, _=_)
    source_config_validation = _source_config_validation_report(country_code, db)
    source_config_summary = source_config_validation.get("summary", {})
    config_path = settings.countries_dir / f"{_code_to_filename(country_code)}.yaml"
    config_backups = list(_config_backup_dir().glob(f"{config_path.stem}-*.yaml"))
    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.country_code == country_code, Subscription.is_active == True)
        .count()
    )
    client_count = db.query(Client).filter(Client.country_code == country_code, Client.is_active == True).count()
    alert_count = db.query(Alert).filter(Alert.is_active == True).count()
    saved_brief_count = db.query(SavedBriefing).count()
    story_spread = list_story_spread(days=30, country_code=country_code, limit=12, db=db)
    story_summary = story_spread.get("summary", {})
    article_quality = audit_article_quality(country_code=country_code, limit=25, method="all", db=db, _=_)
    entity_quality = entity_quality_report(limit=500, db=db, _=_)
    checks = [
        {
            "key": "sources_healthy",
            "label": "Sources healthy",
            "status": "pass" if source_health.get("summary", {}).get("attention_count", 1) == 0 else "warn",
            "detail": f"{source_health.get('summary', {}).get('healthy_count', 0)} healthy, {source_health.get('summary', {}).get('attention_count', 0)} need attention.",
        },
        {
            "key": "scheduler_fresh",
            "label": "Scheduler fresh",
            "status": "pass" if not scheduler.get("stale_warning") and scheduler.get("heartbeat", {}).get("healthy") else "warn",
            "detail": (
                f"Scheduler status: {scheduler.get('status')}; last run {scheduler.get('stale_minutes')} minutes ago; "
                f"heartbeat {scheduler.get('heartbeat', {}).get('age_minutes')} minutes ago."
            ),
        },
        {
            "key": "source_config_persisted",
            "label": "Source config valid",
            "status": (
                "fail" if source_config_summary.get("critical_count", 0) else
                "pass" if config_path.exists() and source_config_summary.get("warning_count", 1) == 0 else
                "warn"
            ),
            "detail": (
                f"Country YAML exists at {config_path.name}; "
                f"{source_config_summary.get('critical_count', 0)} critical, "
                f"{source_config_summary.get('warning_count', 0)} warnings; "
                f"{len(config_backups)} config backups available."
                if config_path.exists() else "Country YAML file is missing."
            ),
        },
        {
            "key": "clients_ready",
            "label": "Clients configured",
            "status": "pass" if client_count >= 3 else "warn",
            "detail": f"{client_count} active clients configured.",
        },
        {
            "key": "alerts_ready",
            "label": "Alerts configured",
            "status": "pass" if alert_count >= 1 else "warn",
            "detail": f"{alert_count} active alert rules.",
        },
        {
            "key": "digest_ready",
            "label": "Daily digest ready",
            "status": "pass" if subscriptions >= 1 or saved_brief_count >= 1 else "warn",
            "detail": f"{subscriptions} active subscriptions, {saved_brief_count} saved briefings.",
        },
        {
            "key": "story_validation_ready",
            "label": "Story validation ready",
            "status": "pass" if story_summary.get("validated", 0) > 0 or story_summary.get("multi_source", 0) > 0 else "warn",
            "detail": (
                f"{story_summary.get('validated', 0)} validated, "
                f"{story_summary.get('multi_source', 0)} multi-source, "
                f"{story_summary.get('single_source', 0)} single-source story clusters in the last 30 days."
            ),
        },
        {
            "key": "article_quality_ready",
            "label": "Article quality clean",
            "status": "pass" if article_quality.get("issue_count", 0) == 0 else "warn",
            "detail": f"{article_quality.get('issue_count', 0)} stored article quality issues flagged.",
        },
        {
            "key": "entity_quality_ready",
            "label": "Entity quality clean",
            "status": "pass" if entity_quality.get("suspicious_count", 0) == 0 else "warn",
            "detail": f"{entity_quality.get('suspicious_count', 0)} suspicious unreviewed entities flagged.",
        },
        {
            "key": "smoke_test",
            "label": "Smoke test",
            "status": "manual",
            "detail": "Run .\\venv\\Scripts\\python.exe scripts\\smoke_test.py before demos.",
        },
    ]
    overall = "ready" if all(check["status"] in {"pass", "manual"} for check in checks) else "needs_attention"
    return {"country_code": country_code, "overall": overall, "checks": checks}


@app.get("/api/v1/admin/ops/fix-queue")
def get_operations_fix_queue(
    country_code: str = "mk",
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Prioritized daily operations queue across source, article, and entity quality."""
    items = _operations_fix_queue(country_code=country_code, limit=limit, db=db, user=_)
    summary = {
        "total": len(items),
        "p0": len([item for item in items if item["priority"] == "p0"]),
        "p1": len([item for item in items if item["priority"] == "p1"]),
        "p2": len([item for item in items if item["priority"] == "p2"]),
        "by_area": {},
    }
    for item in items:
        summary["by_area"][item["area"]] = summary["by_area"].get(item["area"], 0) + 1
    return {
        "country_code": country_code,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "summary": summary,
        "items": items[:limit],
    }


@app.get("/api/v1/admin/article-quality")
def audit_article_quality(
    country_code: str = "mk",
    limit: int = Query(default=25, le=100),
    method: str = "scrape",
    include_reviewed: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return likely non-article pages already stored in the database."""
    query = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(Source.country_code == country_code)
    )
    if not include_reviewed:
        query = query.filter(or_(
            Article.quality_status == None,
            Article.quality_status.notin_(["approved", "excluded"]),
        ))
    if method != "all":
        query = query.filter(Article.ingestion_method == method)
    query = query.order_by(Article.ingested_at.desc()).limit(max(limit * 5, limit))

    issues = []
    reason_counts = {}
    for article in query.all():
        reasons = _stored_article_quality_reasons(article)
        if not reasons:
            continue
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        issues.append({
            "article_id": article.id,
            "source_name": article.source.name if article.source else "Unknown",
            "title": article.title,
            "url": article.url,
            "published_at": article.published_at,
            "ingested_at": article.ingested_at,
            "ingestion_method": article.ingestion_method,
            "word_count": article.word_count,
            "quality_status": article.quality_status or "active",
            "quality_notes": article.quality_notes,
            "quality_reviewed_at": article.quality_reviewed_at,
            "reasons": reasons,
        })
        if len(issues) >= limit:
            break

    return {
        "country_code": country_code,
        "method": method,
        "issue_count": len(issues),
        "reason_counts": reason_counts,
        "issues": issues,
        "cleanup_command": (
            f".\\venv\\Scripts\\python.exe scripts\\audit_article_quality.py "
            f"--country {country_code} --method {method} --limit {limit} --apply --exclude"
        ),
    }


@app.patch("/api/v1/admin/articles/{article_id}/quality", response_model=ArticleResponse)
def update_article_quality_review(
    article_id: int,
    request: ArticleQualityReviewUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Mark stored article quality without deleting evidence from the database."""
    article = db.query(Article).get(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.quality_status = request.quality_status
    article.quality_notes = request.quality_notes
    article.quality_reviewed_at = datetime.datetime.utcnow()
    if request.quality_status == "excluded":
        article.is_processed = True
        article.processing_error = "Excluded from intelligence by article quality review"
    db.commit()
    db.refresh(article)
    return article_to_response(article)


@app.post("/api/v1/admin/articles/bulk-exclude-quality")
def bulk_exclude_quality_articles(
    country_code: str = "mk",
    limit: int = Query(default=25, le=100),
    method: str = "all",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Reversibly exclude currently flagged article-quality issues from intelligence outputs."""
    audit = audit_article_quality(
        country_code=country_code,
        limit=limit,
        method=method,
        include_reviewed=False,
        db=db,
        _=_,
    )
    article_ids = [issue["article_id"] for issue in audit.get("issues", [])]
    if not article_ids:
        return {"checked": audit.get("issue_count", 0), "excluded": 0, "article_ids": []}

    now = datetime.datetime.utcnow()
    articles = db.query(Article).filter(Article.id.in_(article_ids)).all()
    for article in articles:
        reasons = _stored_article_quality_reasons(article)
        article.quality_status = "excluded"
        article.quality_notes = f"Bulk excluded by article quality audit: {', '.join(reasons)}"
        article.quality_reviewed_at = now
        article.is_processed = True
        article.processing_error = "Excluded from intelligence by article quality review"
    db.commit()
    return {
        "checked": audit.get("issue_count", 0),
        "excluded": len(articles),
        "article_ids": article_ids,
    }


def _stored_article_quality_reasons(article: Article) -> list[str]:
    reasons = []
    url = article.url or ""
    title = article.title or ""
    content = article.content or ""
    source_domain = ""
    if article.source and article.source.url:
        source_domain = urlparse(article.source.url).netloc.replace("www.", "")

    reject_reason = ArticleScraper._url_reject_reason(url, source_domain=source_domain)
    if reject_reason not in {None, "external_domain", "not_in_include_patterns"}:
        reasons.append(reject_reason)
    is_rss = (article.ingestion_method or "").lower() == "rss"
    min_word_count = 15 if is_rss else 40
    min_unique_words = 8 if is_rss else 25
    if len(content.split()) < min_word_count:
        reasons.append("short_content")
    if ArticleScraper._content_quality_error(
        title=title,
        content=content,
        canonical_url=url,
        published_at=article.published_at,
        min_word_count=min_word_count,
        min_unique_words=min_unique_words,
    ):
        reasons.append("content_quality")
    return sorted(set(reasons))


@app.get("/api/v1/admin/intelligence-qa")
def get_intelligence_qa(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """One-page operational QA summary for demo and pilot readiness."""
    scheduler = get_scheduler_status(country_code=country_code, db=db, _=_)
    source_health = list_ingestion_source_health(country_code=country_code, db=db, _=_)
    source_config_validation = _source_config_validation_report(country_code, db)
    story_spread = list_story_spread(days=30, country_code=country_code, limit=12, db=db)
    article_quality = audit_article_quality(country_code=country_code, limit=25, method="all", db=db, _=_)
    entity_quality = entity_quality_report(limit=500, db=db, _=_)

    story_summary = story_spread.get("summary", {})
    source_summary = source_health.get("summary", {})
    source_config_summary = source_config_validation.get("summary", {})
    checks = [
        {
            "key": "freshness",
            "label": "Data freshness",
            "status": "pass" if not scheduler.get("stale_warning") else "warn",
            "detail": f"Last run {scheduler.get('stale_minutes')} minutes ago; heartbeat {scheduler.get('heartbeat', {}).get('age_minutes')} minutes old.",
            "recommendation": "Start the scheduler or run one ingestion cycle before demoing latest coverage.",
        },
        {
            "key": "sources",
            "label": "Source operations",
            "status": "pass" if source_summary.get("attention_count", 1) == 0 else "warn",
            "detail": f"{source_summary.get('healthy_count', 0)} healthy, {source_summary.get('attention_count', 0)} need attention.",
            "recommendation": "Open ingestion failure drilldown and fix the highest-value failing sources first.",
        },
        {
            "key": "source_config",
            "label": "Source configuration",
            "status": (
                "fail" if source_config_summary.get("critical_count", 0) else
                "pass" if source_config_summary.get("warning_count", 1) == 0 else
                "warn"
            ),
            "detail": (
                f"{source_config_summary.get('healthy_count', 0)} healthy configs, "
                f"{source_config_summary.get('warning_count', 0)} warnings, "
                f"{source_config_summary.get('critical_count', 0)} critical."
            ),
            "recommendation": "Open Admin Config Validation and fix critical YAML/RSS/scraper setup issues before demos.",
        },
        {
            "key": "story_validation",
            "label": "Story validation",
            "status": "pass" if story_summary.get("validated", 0) > 0 or story_summary.get("multi_source", 0) > 0 else "warn",
            "detail": f"{story_summary.get('validated', 0)} validated and {story_summary.get('multi_source', 0)} multi-source stories in 30 days.",
            "recommendation": "Rebuild story clusters after ingesting fresh data.",
        },
        {
            "key": "article_quality",
            "label": "Article quality",
            "status": "pass" if article_quality.get("issue_count", 0) == 0 else "warn",
            "detail": f"{article_quality.get('issue_count', 0)} likely bad stored articles found.",
            "recommendation": "Review flagged URLs before using them in client-facing summaries.",
        },
        {
            "key": "entity_quality",
            "label": "Entity quality",
            "status": "pass" if entity_quality.get("suspicious_count", 0) == 0 else "warn",
            "detail": f"{entity_quality.get('suspicious_count', 0)} suspicious unreviewed entities found.",
            "recommendation": "Use auto-hide noise, then manually approve important people, parties, and institutions.",
        },
    ]
    score = 100 - sum(0 if item["status"] == "pass" else 15 for item in checks)
    score = max(0, score)
    recommendations = [
        item["recommendation"]
        for item in checks
        if item["status"] != "pass"
    ][:5]
    return {
        "country_code": country_code,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "score": score,
        "status": "demo_ready" if score >= 80 else "needs_attention",
        "checks": checks,
        "recommendations": recommendations,
        "signals": {
            "scheduler": {
                "status": scheduler.get("status"),
                "stale_minutes": scheduler.get("stale_minutes"),
                "heartbeat_age_minutes": scheduler.get("heartbeat", {}).get("age_minutes"),
            },
            "sources": source_summary,
            "source_config": source_config_summary,
            "story_spread": story_summary,
            "article_quality": {
                "issue_count": article_quality.get("issue_count", 0),
                "reason_counts": article_quality.get("reason_counts", {}),
            },
            "entity_quality": {
                "checked": entity_quality.get("checked", 0),
                "suspicious_count": entity_quality.get("suspicious_count", 0),
                "reason_counts": entity_quality.get("reason_counts", {}),
            },
        },
    }


@app.get("/api/v1/admin/attacks/review")
def attack_review_queue(
    country_code: str = "mk",
    days: int = Query(default=30, ge=1, le=365),
    status: str = Query(default="all", pattern="^(all|unreviewed|confirmed|rejected|corrected)$"),
    limit: int = Query(default=80, ge=1, le=250),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Build an operator queue from live target-specific attack detections."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    watchlist = (
        db.query(ClientWatchlistItem)
        .join(Client, Client.id == ClientWatchlistItem.client_id)
        .filter(
            Client.country_code == country_code,
            Client.is_active == True,
            ClientWatchlistItem.response_assist_enabled == True,
            ClientWatchlistItem.entity_id.isnot(None),
            ClientWatchlistItem.item_type.in_([
                WatchlistItemType.ENTITY,
                WatchlistItemType.OPPONENT,
            ]),
        )
        .order_by(ClientWatchlistItem.priority.asc(), ClientWatchlistItem.id.asc())
        .limit(40)
        .all()
    )
    review_map = {
        (review.watchlist_item_id, review.article_id): review
        for review in db.query(AttackReview).filter(
            AttackReview.watchlist_item_id.in_([item.id for item in watchlist] or [-1])
        ).all()
    }
    candidates = []
    for item in watchlist:
        rows = _articles_for_watchlist_item(db, item, since)[:20]
        for article, _, _ in rows:
            raw_detail = _attack_detail_for_article(item, article)
            review = review_map.get((item.id, article.id))
            if not raw_detail.get("is_attack") and not review:
                continue
            detail = _apply_attack_review(raw_detail, review)
            review_status = detail.get("review_status", "unreviewed")
            if status != "all" and review_status != status:
                continue
            candidates.append({
                "review_id": review.id if review else None,
                "review_status": review_status,
                "review_notes": review.notes if review else None,
                "client_id": item.client_id,
                "client_name": item.client.name if item.client else "Unknown client",
                "watchlist_item_id": item.id,
                "watchlist_label": item.label,
                "article_id": article.id,
                "title": article.title,
                "url": article.url,
                "source_name": article.source.name if article.source else "Unknown",
                "published_at": detail.get("published_at"),
                "attacker": detail.get("attacker"),
                "target": detail.get("target"),
                "allegation": detail.get("allegation"),
                "quote": detail.get("quote"),
                "categories": detail.get("categories", []),
                "confidence": detail.get("confidence", 0),
                "confidence_label": detail.get("confidence_label", "low"),
                "extraction_basis": detail.get("extraction_basis", []),
            })
    status_rank = {"unreviewed": 0, "corrected": 1, "confirmed": 2, "rejected": 3}
    candidates.sort(
        key=lambda row: (
            status_rank.get(row["review_status"], 9),
            -(row.get("confidence") or 0),
            row.get("published_at") or "",
        )
    )
    counts = defaultdict(int)
    for row in candidates:
        counts[row["review_status"]] += 1
    return {
        "country_code": country_code,
        "period_days": days,
        "summary": {
            "total": len(candidates),
            "unreviewed": counts["unreviewed"],
            "confirmed": counts["confirmed"],
            "rejected": counts["rejected"],
            "corrected": counts["corrected"],
        },
        "candidates": candidates[:limit],
    }


@app.put("/api/v1/admin/attacks/review/{watchlist_item_id}/{article_id}")
def review_attack_detection(
    watchlist_item_id: int,
    article_id: int,
    request: AttackReviewUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Persist an audited decision and immediately apply it to client results."""
    item = db.query(ClientWatchlistItem).get(watchlist_item_id)
    article = db.query(Article).get(article_id)
    if not item or not article:
        raise HTTPException(status_code=404, detail="Watchlist item or article not found")
    raw_detail = _attack_detail_for_article(item, article)
    if request.status == "corrected" and not (
        request.corrected_attacker or request.corrected_allegation or request.corrected_categories
    ):
        raise HTTPException(status_code=400, detail="A corrected review requires at least one corrected field")
    review = db.query(AttackReview).filter(
        AttackReview.watchlist_item_id == watchlist_item_id,
        AttackReview.article_id == article_id,
    ).first()
    if not review:
        review = AttackReview(
            client_id=item.client_id,
            watchlist_item_id=watchlist_item_id,
            article_id=article_id,
            original_detail=raw_detail,
        )
        db.add(review)
    review.status = request.status
    review.original_detail = raw_detail
    review.corrected_attacker = request.corrected_attacker
    review.corrected_target = request.corrected_target
    review.corrected_allegation = request.corrected_allegation
    review.corrected_categories = request.corrected_categories
    review.notes = request.notes
    review.reviewer_user_id = user.id
    review.reviewed_at = datetime.datetime.utcnow()
    _invalidate_client_dashboard_cache(db, item.client_id)
    db.commit()
    db.refresh(review)
    return {
        "id": review.id,
        "status": review.status,
        "watchlist_item_id": review.watchlist_item_id,
        "article_id": review.article_id,
        "reviewed_at": review.reviewed_at,
        "detail": _apply_attack_review(raw_detail, review),
    }


@app.get("/api/v1/legal-documents", response_model=list[LegalDocumentResponse])
def list_legal_documents(
    q: str = "",
    country_code: str = "mk",
    legal_area: Optional[str] = None,
    source_status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Search the internal legal reference library."""
    query = db.query(LegalDocument).filter(LegalDocument.country_code == country_code)
    if legal_area:
        query = query.filter(LegalDocument.legal_area.ilike(f"%{legal_area}%"))
    if source_status:
        query = query.filter(LegalDocument.source_status == LegalSourceStatus(source_status))
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(
            LegalDocument.title.ilike(pattern),
            LegalDocument.legal_area.ilike(pattern),
            LegalDocument.summary.ilike(pattern),
            LegalDocument.reference_text.ilike(pattern),
            LegalDocument.article_refs.ilike(pattern),
        ))
    documents = (
        query.order_by(LegalDocument.confidence_score.desc(), LegalDocument.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [legal_document_to_response(document) for document in documents]


@app.get("/api/v1/admin/legal/quality")
def legal_library_quality(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Summarize legal-reference readiness for cautious response assistance."""
    documents = (
        db.query(LegalDocument)
        .filter(LegalDocument.country_code == country_code)
        .order_by(LegalDocument.updated_at.desc())
        .all()
    )
    status_counts = {status.value: 0 for status in LegalSourceStatus}
    area_counts: dict[str, int] = {}
    for document in documents:
        status_counts[document.source_status.value] = status_counts.get(document.source_status.value, 0) + 1
        for area in re.split(r"[;,]", document.legal_area or ""):
            area = area.strip().lower()
            if area:
                area_counts[area] = area_counts.get(area, 0) + 1
    required_coverage = _legal_required_coverage(documents)
    missing_coverage = [item for item in required_coverage if item["status"] == "missing"]
    research_leads = [item for item in required_coverage if item["status"] == "research_lead"]

    official_count = status_counts.get(LegalSourceStatus.OFFICIAL.value, 0)
    lawyer_verified_count = status_counts.get(LegalSourceStatus.LAWYER_VERIFIED.value, 0)
    needs_review_count = status_counts.get(LegalSourceStatus.NEEDS_REVIEW.value, 0)
    outdated_count = status_counts.get(LegalSourceStatus.OUTDATED_POSSIBLE.value, 0)
    recommendations = []
    if not documents:
        recommendations.append("Add official or lawyer-reviewed Macedonian legal references before enabling legal-context claims.")
    if lawyer_verified_count == 0:
        recommendations.append("Mark at least core constitutional and defamation/media-law references as lawyer verified after counsel review.")
    if needs_review_count or outdated_count:
        recommendations.append("Review references marked needs review or outdated before citing them in response packs.")
    if official_count + lawyer_verified_count < 5:
        recommendations.append("Expand official references for constitution, criminal procedure, civil liability/defamation, elections, and media regulation.")
    if missing_coverage:
        labels = ", ".join(item["label"] for item in missing_coverage[:4])
        recommendations.append(f"Add legal research leads for uncovered areas: {labels}.")
    if research_leads:
        labels = ", ".join(item["label"] for item in research_leads[:4])
        recommendations.append(f"Verify exact official texts or counsel review for research-lead areas: {labels}.")
    if not recommendations:
        recommendations.append("Legal library is ready as a research aid; final legal positions still require counsel.")

    status = "ready"
    if not documents or official_count + lawyer_verified_count < 3 or missing_coverage:
        status = "thin"
    if needs_review_count or outdated_count or research_leads:
        status = "needs_review"

    return {
        "country_code": country_code,
        "status": status,
        "total": len(documents),
        "status_counts": status_counts,
        "official_or_verified": official_count + lawyer_verified_count,
        "lawyer_verified_count": lawyer_verified_count,
        "needs_review_count": needs_review_count,
        "outdated_count": outdated_count,
        "areas": [
            {"area": area, "count": count}
            for area, count in sorted(area_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        ],
        "required_coverage": required_coverage,
        "coverage_summary": {
            "covered": len([item for item in required_coverage if item["status"] == "covered"]),
            "research_lead": len(research_leads),
            "missing": len(missing_coverage),
        },
        "recommendations": recommendations,
    }


def _legal_required_coverage(documents: list[LegalDocument]) -> list[dict]:
    coverage = []
    verified_statuses = {
        LegalSourceStatus.OFFICIAL.value,
        LegalSourceStatus.LAWYER_VERIFIED.value,
    }
    for requirement in REQUIRED_LEGAL_COVERAGE:
        matches = []
        for document in documents:
            haystack = " ".join([
                document.title or "",
                document.legal_area or "",
                document.summary or "",
                document.reference_text or "",
                document.article_refs or "",
                " ".join(document.tags or []),
            ]).lower()
            if any(keyword in haystack for keyword in requirement["keywords"]):
                matches.append(document)
        verified_count = len([
            document for document in matches
            if document.source_status.value in verified_statuses
        ])
        if verified_count:
            status = "covered"
        elif matches:
            status = "research_lead"
        else:
            status = "missing"
        coverage.append({
            "key": requirement["key"],
            "label": requirement["label"],
            "status": status,
            "total_references": len(matches),
            "official_or_verified": verified_count,
            "needs_review": len([
                document for document in matches
                if document.source_status in {
                    LegalSourceStatus.NEEDS_REVIEW,
                    LegalSourceStatus.OUTDATED_POSSIBLE,
                    LegalSourceStatus.UNOFFICIAL_COPY,
                }
            ]),
            "top_references": [
                {
                    "id": document.id,
                    "title": document.title,
                    "source_status": document.source_status.value,
                    "confidence_score": document.confidence_score,
                }
                for document in sorted(
                    matches,
                    key=lambda item: (item.source_status.value not in verified_statuses, -(item.confidence_score or 0)),
                )[:3]
            ],
        })
    return coverage


@app.post("/api/v1/legal-documents", response_model=LegalDocumentResponse)
def create_legal_document(
    request: LegalDocumentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Add a manually reviewed legal reference to the internal library."""
    if request.source_status == LegalSourceStatus.LAWYER_VERIFIED.value:
        raise HTTPException(
            status_code=400,
            detail="Create the reference first, then use the audited legal review endpoint.",
        )
    document = LegalDocument(
        title=request.title,
        country_code=request.country_code,
        legal_area=request.legal_area,
        source_url=request.source_url,
        source_name=request.source_name,
        source_status=LegalSourceStatus(request.source_status),
        language=request.language,
        tags=request.tags,
        summary=request.summary,
        reference_text=request.reference_text,
        article_refs=request.article_refs,
        confidence_score=request.confidence_score,
        notes=request.notes,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return legal_document_to_response(document)


@app.patch("/api/v1/legal-documents/{document_id}", response_model=LegalDocumentResponse)
def update_legal_document(
    document_id: int,
    request: LegalDocumentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Update a legal reference after review or source verification."""
    document = db.query(LegalDocument).get(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Legal document not found")
    for field in (
        "title", "legal_area", "source_url", "source_name", "summary",
        "reference_text", "article_refs", "confidence_score", "notes",
    ):
        value = getattr(request, field)
        if value is not None:
            setattr(document, field, value)
    if request.source_status is not None:
        if request.source_status == LegalSourceStatus.LAWYER_VERIFIED.value:
            raise HTTPException(
                status_code=400,
                detail="Use the audited legal review endpoint for lawyer verification.",
            )
        document.source_status = LegalSourceStatus(request.source_status)
    if request.tags is not None:
        document.tags = request.tags
    if request.mark_verified:
        raise HTTPException(
            status_code=400,
            detail="Use the audited legal review endpoint for lawyer verification.",
        )
    db.commit()
    db.refresh(document)
    return legal_document_to_response(document)


LEGAL_REVIEW_DECISIONS = {
    "lawyer_verified": LegalSourceStatus.LAWYER_VERIFIED,
    "needs_review": LegalSourceStatus.NEEDS_REVIEW,
    "outdated_possible": LegalSourceStatus.OUTDATED_POSSIBLE,
    "unofficial_copy": LegalSourceStatus.UNOFFICIAL_COPY,
    "official_source_confirmed": LegalSourceStatus.OFFICIAL,
}


@app.get("/api/v1/admin/legal/review-queue")
def legal_review_queue(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return references that still need counsel or source-status review."""
    documents = (
        db.query(LegalDocument)
        .filter(
            LegalDocument.country_code == country_code,
            LegalDocument.source_status != LegalSourceStatus.LAWYER_VERIFIED,
        )
        .order_by(LegalDocument.confidence_score.desc(), LegalDocument.updated_at.asc())
        .all()
    )
    document_ids = [document.id for document in documents]
    assignments = (
        db.query(LegalReviewAssignment)
        .filter(
            LegalReviewAssignment.legal_document_id.in_(document_ids),
            LegalReviewAssignment.status.in_(
                ["pending_qualification", "assigned", "in_review"]
            ),
        )
        .order_by(LegalReviewAssignment.created_at.desc())
        .all()
        if document_ids else []
    )
    assignment_by_document = {}
    for assignment in assignments:
        assignment_by_document.setdefault(assignment.legal_document_id, assignment)
    items = []
    for document in documents:
        item = jsonable_encoder(legal_document_to_response(document))
        assignment = assignment_by_document.get(document.id)
        item["counsel_assignment"] = (
            jsonable_encoder(_legal_assignment_to_response(assignment))
            if assignment else None
        )
        items.append(item)
    return {
        "country_code": country_code,
        "count": len(documents),
        "assigned_count": len(assignment_by_document),
        "unassigned_count": len(documents) - len(assignment_by_document),
        "items": items,
    }


@app.get(
    "/api/v1/admin/legal/{document_id}/reviews",
    response_model=list[LegalReviewResponse],
)
def legal_review_history(
    document_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return the immutable decision trail for one legal reference."""
    _legal_document_or_404(db, document_id)
    reviews = (
        db.query(LegalReview)
        .filter(LegalReview.legal_document_id == document_id)
        .order_by(LegalReview.reviewed_at.desc(), LegalReview.id.desc())
        .all()
    )
    return [legal_review_to_response(review) for review in reviews]


@app.get(
    "/api/v1/admin/legal/{document_id}/assignments",
    response_model=list[LegalReviewAssignmentResponse],
)
def legal_review_assignments(
    document_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return counsel assignments without treating assignment as verification."""
    _legal_document_or_404(db, document_id)
    rows = (
        db.query(LegalReviewAssignment)
        .filter(LegalReviewAssignment.legal_document_id == document_id)
        .order_by(LegalReviewAssignment.created_at.desc())
        .all()
    )
    return [_legal_assignment_to_response(row) for row in rows]


@app.post(
    "/api/v1/admin/legal/{document_id}/assignments",
    response_model=LegalReviewAssignmentResponse,
)
def assign_legal_review(
    document_id: int,
    request: LegalReviewAssignmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Assign a reference to counsel while its safe-use status stays unchanged."""
    _legal_document_or_404(db, document_id)
    jurisdiction = (request.reviewer_jurisdiction or "").strip() or None
    qualification_reference = (
        request.qualification_reference or ""
    ).strip() or None
    assignment = LegalReviewAssignment(
        legal_document_id=document_id,
        assigned_by_user_id=user.id,
        reviewer_name=request.reviewer_name.strip(),
        reviewer_email=(request.reviewer_email or "").strip() or None,
        reviewer_organization=(request.reviewer_organization or "").strip() or None,
        reviewer_jurisdiction=jurisdiction,
        qualification_reference=qualification_reference,
        status="assigned" if jurisdiction and qualification_reference
        else "pending_qualification",
        scope=request.scope.strip(),
        due_at=request.due_at,
        notes=(request.notes or "").strip() or None,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return _legal_assignment_to_response(assignment)


@app.post(
    "/api/v1/admin/legal/{document_id}/reviews",
    response_model=LegalReviewResponse,
)
def review_legal_document(
    document_id: int,
    request: LegalReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Record an audited legal-reference decision and update its safe-use status."""
    if request.decision not in LEGAL_REVIEW_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported decision. Use one of: {', '.join(LEGAL_REVIEW_DECISIONS)}",
        )
    document = _legal_document_or_404(db, document_id)
    before = document.source_status.value
    next_status = LEGAL_REVIEW_DECISIONS[request.decision]
    assignment = (
        db.query(LegalReviewAssignment)
        .filter(
            LegalReviewAssignment.legal_document_id == document.id,
            LegalReviewAssignment.status.in_(
                ["pending_qualification", "assigned", "in_review"]
            ),
        )
        .order_by(LegalReviewAssignment.created_at.desc())
        .first()
    )
    if next_status == LegalSourceStatus.LAWYER_VERIFIED:
        if not _qualified_assignment_matches(
            assignment, request.reviewer_name
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Lawyer verification requires a matching counsel assignment "
                    "with jurisdiction and a qualification reference."
                ),
            )

    document.source_status = next_status
    if next_status == LegalSourceStatus.LAWYER_VERIFIED:
        verified_at = datetime.datetime.utcnow()
        document.verified_at = verified_at
        document.confidence_score = max(document.confidence_score or 0, 0.9)
        assignment.qualification_verified_at = verified_at
    else:
        document.verified_at = None

    review = LegalReview(
        legal_document_id=document.id,
        reviewer_user_id=user.id,
        reviewer_name=request.reviewer_name.strip(),
        reviewer_organization=(request.reviewer_organization or "").strip() or None,
        decision=request.decision,
        status_before=before,
        status_after=next_status.value,
        notes=request.notes.strip(),
        reviewed_at=datetime.datetime.utcnow(),
    )
    if assignment:
        assignment.status = "completed"
        assignment.completed_at = datetime.datetime.utcnow()
    db.add(review)
    db.commit()
    db.refresh(review)
    return legal_review_to_response(review)


def _legal_document_or_404(db: Session, document_id: int) -> LegalDocument:
    document = db.get(LegalDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Legal document not found")
    return document


def legal_review_to_response(review: LegalReview) -> LegalReviewResponse:
    return LegalReviewResponse(
        id=review.id,
        legal_document_id=review.legal_document_id,
        reviewer_user_id=review.reviewer_user_id,
        reviewer_name=review.reviewer_name,
        reviewer_organization=review.reviewer_organization,
        decision=review.decision,
        status_before=review.status_before,
        status_after=review.status_after,
        notes=review.notes,
        reviewed_at=review.reviewed_at,
        created_at=review.created_at,
    )


def _legal_assignment_to_response(
    assignment: LegalReviewAssignment,
) -> LegalReviewAssignmentResponse:
    return LegalReviewAssignmentResponse(
        id=assignment.id,
        legal_document_id=assignment.legal_document_id,
        assigned_by_user_id=assignment.assigned_by_user_id,
        reviewer_name=assignment.reviewer_name,
        reviewer_email=assignment.reviewer_email,
        reviewer_organization=assignment.reviewer_organization,
        reviewer_jurisdiction=assignment.reviewer_jurisdiction,
        qualification_reference=assignment.qualification_reference,
        qualification_verified_at=assignment.qualification_verified_at,
        status=assignment.status,
        scope=assignment.scope,
        due_at=assignment.due_at,
        completed_at=assignment.completed_at,
        notes=assignment.notes,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _qualified_assignment_matches(
    assignment: Optional[LegalReviewAssignment],
    reviewer_name: str,
) -> bool:
    """Require a traceable qualification record for lawyer-verified status."""
    return bool(
        assignment
        and assignment.reviewer_name.strip().casefold()
        == reviewer_name.strip().casefold()
        and (assignment.reviewer_jurisdiction or "").strip()
        and (assignment.qualification_reference or "").strip()
    )


@app.get("/api/v1/timeline/daily")
def get_daily_timeline(
    days: int = Query(default=30, le=365),
    date_basis: str = Query(default="published", pattern="^(published|fetched|ingested)$"),
    country_code: Optional[str] = None,
    category: Optional[str] = None,
    entity_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Daily article counts by published, fetched, or ingested date."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    date_columns = {
        "published": func.coalesce(
            Article.published_at, Article.fetched_at, Article.ingested_at
        ),
        "fetched": Article.fetched_at,
        "ingested": Article.ingested_at,
    }
    date_column = date_columns[date_basis]
    day = func.date(date_column).label("day")

    query = (
        db.query(
            day,
            func.count(func.distinct(Article.id)).label("article_count"),
            func.count(func.distinct(Source.id)).label("source_count"),
        )
        .join(Source, Source.id == Article.source_id)
        .filter(date_column >= since)
    )

    if country_code:
        query = query.filter(Source.country_code == country_code)
    if category:
        query = query.join(ArticleCategoryModel).filter(
            ArticleCategoryModel.category == category
        )
    if entity_id:
        query = query.join(EntityMention).filter(
            EntityMention.entity_id == entity_id
        )

    rows = query.group_by(day).order_by(day).all()

    return [
        {
            "date": row.day,
            "article_count": row.article_count,
            "source_count": row.source_count,
            "date_basis": date_basis,
        }
        for row in rows
    ]


@app.get("/api/v1/sources/stats")
def get_source_stats(
    days: int = Query(default=90, le=365),
    country_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get source coverage, processing, and recency metrics."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    query = (
        db.query(
            Source.id,
            Source.name,
            Source.url,
            Source.country_code,
            Source.language,
            Source.reliability_score,
            Source.source_type,
            Source.political_leaning,
            Source.ownership,
            Source.is_active,
            func.count(Article.id).label("article_count"),
            func.max(Article.published_at).label("latest_article_at"),
            func.sum(
                case((Article.is_processed == True, 1), else_=0)
            ).label("processed_count"),
        )
        .outerjoin(
            Article,
            (Article.source_id == Source.id)
            & (
                (Article.published_at >= since)
                | (Article.published_at.is_(None))
            ),
        )
    )

    if country_code:
        query = query.filter(Source.country_code == country_code)

    rows = (
        query.group_by(
            Source.id,
            Source.name,
            Source.url,
            Source.country_code,
            Source.language,
            Source.reliability_score,
            Source.source_type,
            Source.political_leaning,
            Source.ownership,
            Source.is_active,
        )
        .order_by(desc("article_count"), Source.name)
        .all()
    )
    config_cache: dict[str, dict] = {}

    output = []
    for row in rows:
        if row.country_code not in config_cache:
            try:
                config_cache[row.country_code] = _load_country_config(row.country_code)
            except HTTPException:
                config_cache[row.country_code] = {"sources": []}
        yaml_config = _find_source_config(config_cache[row.country_code], row.name)
        output.append({
            "source_id": row.id,
            "name": row.name,
            "url": row.url,
            "country_code": row.country_code,
            "language": row.language,
            "reliability_score": row.reliability_score,
            "source_type": row.source_type,
            "political_leaning": row.political_leaning,
            "ownership": row.ownership,
            "is_active": row.is_active,
            "article_count": row.article_count,
            "processed_count": row.processed_count or 0,
            "latest_article_at": (
                row.latest_article_at.isoformat()
                if row.latest_article_at else None
            ),
            **_source_yaml_operational(yaml_config),
        })
    return output


@app.post("/api/v1/reports/generate", response_model=ReportResponse)
def generate_report(
    request: ReportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Generate a news briefing report."""
    config = ReportConfig(
        country_code=request.country_code,
        date_from=request.date_from,
        date_to=request.date_to,
        categories=request.categories,
    )

    generator = PDFReportGenerator(db, settings.reports_dir)
    filepath = generator.generate(config)

    # Save report record
    report = Report(
        title=f"Briefing — {config.country_name}",
        country_code=config.country_code,
        format=ReportFormat.PDF,
        categories_filter={"categories": config.categories},
        date_from=config.date_from,
        date_to=config.date_to,
        file_path=str(filepath),
    )
    db.add(report)
    db.commit()

    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=0,
        categories=config.categories or [],
        date_range=(
            f"{config.date_from.strftime('%Y-%m-%d')} to "
            f"{config.date_to.strftime('%Y-%m-%d')}"
        ),
    )


@app.get("/api/v1/reports/{report_id}/download")
def download_report(report_id: int, db: Session = Depends(get_db)):
    """Download a generated report PDF."""
    report = db.query(Report).get(report_id)
    if not report or not report.file_path:
        raise HTTPException(status_code=404, detail="Report not found")

    filepath = Path(report.file_path)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Report file missing")

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type="application/pdf",
    )


# ── Routes: Subscriptions ────────────────────────────────────────────

@app.get("/api/v1/reports", response_model=list[ReportListItem])
def list_reports(
    limit: int = Query(default=20, le=100),
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List generated PDF/report exports."""
    reports = (
        db.query(Report)
        .order_by(Report.created_at.desc())
        .limit(limit * 3)
        .all()
    )
    if user.role == UserRole.CLIENT:
        client_id = user.client_id
    if client_id:
        reports = [
            report for report in reports
            if (report.categories_filter or {}).get("client_id") == client_id
        ]
    elif user.role not in (UserRole.ADMIN, UserRole.ANALYST):
        reports = []
    return [_report_list_item(report) for report in reports[:limit]]


@app.get("/api/v1/clients/{client_id}/saved-briefings",
         response_model=list[SavedBriefingResponse])
def list_saved_briefings(
    client_id: int,
    briefing_type: Optional[str] = None,
    status: Optional[str] = Query(default="active"),
    folder: Optional[str] = None,
    q: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = Query(default=30, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List structured saved work products for a client."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    query = db.query(SavedBriefing).filter(SavedBriefing.client_id == client_id)
    if briefing_type:
        query = query.filter(SavedBriefing.briefing_type == briefing_type)
    if status == "active":
        query = query.filter(SavedBriefing.status.in_(["active", "pinned"]))
    elif status and status != "all":
        query = query.filter(SavedBriefing.status == status)
    if folder:
        query = query.filter(SavedBriefing.folder == folder)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(SavedBriefing.title.ilike(pattern), SavedBriefing.topic.ilike(pattern)))
    tag_values = [item.strip().lower() for item in (tags or "").split(",") if item.strip()]
    fetch_limit = min(max(limit * 3, limit), 300) if tag_values else limit
    briefings = query.order_by(SavedBriefing.updated_at.desc()).limit(fetch_limit).all()
    if tag_values:
        briefings = [
            briefing for briefing in briefings
            if set(tag_values).issubset({tag.lower() for tag in _saved_briefing_tags(briefing.tags)})
        ]
    return [saved_briefing_to_response(briefing) for briefing in briefings[:limit]]


@app.post("/api/v1/clients/{client_id}/saved-briefings",
          response_model=SavedBriefingResponse)
def create_saved_briefing(
    client_id: int,
    request: SavedBriefingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save a structured briefing payload for later reopening."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    if request.watchlist_item_id:
        item = (
            db.query(ClientWatchlistItem)
            .filter(
                ClientWatchlistItem.id == request.watchlist_item_id,
                ClientWatchlistItem.client_id == client_id,
            )
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="Watchlist item not found for client")
    if request.report_id and not db.query(Report).get(request.report_id):
        raise HTTPException(status_code=404, detail="Report not found")

    briefing = SavedBriefing(
        client_id=client_id,
        briefing_type=request.briefing_type,
        title=request.title,
        country_code=request.country_code or client.country_code,
        topic=request.topic,
        entity_id=request.entity_id,
        watchlist_item_id=request.watchlist_item_id,
        report_id=request.report_id,
        status=request.status or "active",
        folder=request.folder or "briefings",
        tags=request.tags,
        notes=request.notes,
        payload=jsonable_encoder(request.payload),
        source_article_ids=request.source_article_ids,
        confidence=request.confidence,
        created_by_user_id=user.id,
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    return saved_briefing_to_response(briefing)


@app.get("/api/v1/clients/{client_id}/saved-briefings/{briefing_id}",
         response_model=SavedBriefingResponse)
def get_saved_briefing(
    client_id: int,
    briefing_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Open a saved structured briefing."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    briefing = (
        db.query(SavedBriefing)
        .filter(SavedBriefing.id == briefing_id, SavedBriefing.client_id == client_id)
        .first()
    )
    if not briefing:
        raise HTTPException(status_code=404, detail="Saved briefing not found")
    return saved_briefing_to_response(briefing)


@app.patch("/api/v1/clients/{client_id}/saved-briefings/{briefing_id}",
           response_model=SavedBriefingResponse)
def update_saved_briefing(
    client_id: int,
    briefing_id: int,
    request: SavedBriefingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit saved prep-pack metadata or payload so briefings can be reused."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    briefing = (
        db.query(SavedBriefing)
        .filter(SavedBriefing.id == briefing_id, SavedBriefing.client_id == client_id)
        .first()
    )
    if not briefing:
        raise HTTPException(status_code=404, detail="Saved briefing not found")
    fields_set = request.model_fields_set if hasattr(request, "model_fields_set") else request.__fields_set__
    for field in (
        "briefing_type", "title", "country_code", "topic", "entity_id",
        "watchlist_item_id", "report_id", "status", "folder", "tags", "notes",
        "payload", "source_article_ids", "confidence",
    ):
        if field in fields_set:
            setattr(briefing, field, jsonable_encoder(getattr(request, field)))
    db.commit()
    db.refresh(briefing)
    return saved_briefing_to_response(briefing)


@app.post("/api/v1/clients/{client_id}/saved-briefings/{briefing_id}/duplicate",
          response_model=SavedBriefingResponse)
def duplicate_saved_briefing(
    client_id: int,
    briefing_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Duplicate a saved briefing as a reusable press-prep template."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    briefing = (
        db.query(SavedBriefing)
        .filter(SavedBriefing.id == briefing_id, SavedBriefing.client_id == client_id)
        .first()
    )
    if not briefing:
        raise HTTPException(status_code=404, detail="Saved briefing not found")
    copy = SavedBriefing(
        client_id=client_id,
        briefing_type=briefing.briefing_type,
        title=f"Copy - {briefing.title}",
        country_code=briefing.country_code,
        topic=briefing.topic,
        entity_id=briefing.entity_id,
        watchlist_item_id=briefing.watchlist_item_id,
        report_id=briefing.report_id,
        status="active",
        folder=briefing.folder or "briefings",
        tags=_saved_briefing_tags(briefing.tags),
        notes=briefing.notes,
        payload=jsonable_encoder(briefing.payload or {}),
        source_article_ids=list(briefing.source_article_ids or []),
        confidence=jsonable_encoder(briefing.confidence or {}),
        created_by_user_id=user.id,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return saved_briefing_to_response(copy)


@app.post("/api/v1/clients/{client_id}/saved-briefings/{briefing_id}/report",
          response_model=ReportResponse)
def generate_saved_briefing_report(
    client_id: int,
    briefing_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a PDF from a saved briefing payload."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "pdf_reports")
    briefing = (
        db.query(SavedBriefing)
        .filter(SavedBriefing.id == briefing_id, SavedBriefing.client_id == client_id)
        .first()
    )
    if not briefing:
        raise HTTPException(status_code=404, detail="Saved briefing not found")

    payload = dict(briefing.payload or {})
    generator = BriefingExportGenerator(settings.reports_dir)
    if briefing.briefing_type == "party_briefing":
        filepath = generator.generate_party_briefing(client, payload)
    elif briefing.briefing_type == "response_pack":
        filepath = generator.generate_response_pack(client, payload)
    elif briefing.briefing_type in {"client_daily_brief", "topic_briefing"}:
        if briefing.briefing_type == "topic_briefing":
            payload = {
                "period_days": payload.get("period_days", 30),
                "headline": payload.get("headline") or briefing.title,
                "summary": payload.get("summary") or payload.get("coverage_summary"),
                "evidence_brief": payload.get("evidence_brief") or [],
                "recommended_actions": payload.get("recommended_actions") or payload.get("claims_to_verify") or [],
                "risk_items": payload.get("risk_items") or [],
                "matched_articles": payload.get("matched_articles") or payload.get("recent_articles") or [],
            }
        filepath = generator.generate_client_daily_brief(client, payload)
    elif briefing.briefing_type == "entity_briefing":
        filepath = generator.generate_entity_briefing(payload)
    else:
        summary_parts = [
            str(payload.get("summary") or payload.get("coverage_summary") or payload.get("description") or ""),
            str(briefing.notes or ""),
        ]
        generic_payload = {
            "period_days": payload.get("period_days", 30),
            "headline": briefing.title,
            "summary": "\n".join(part for part in summary_parts if part).strip()
            or "Saved prep pack exported from the client workspace.",
            "evidence_brief": payload.get("evidence_brief") or [],
            "recommended_actions": (
                payload.get("recommended_actions")
                or payload.get("suggested_talking_points")
                or payload.get("claims_to_verify")
                or payload.get("press_conference_outline")
                or []
            ),
            "risk_items": payload.get("risk_items") or [],
            "matched_articles": payload.get("matched_articles") or payload.get("source_articles") or [],
        }
        filepath = generator.generate_client_daily_brief(client, generic_payload)

    now = datetime.datetime.utcnow()
    report = Report(
        title=f"Saved Briefing - {briefing.title}",
        country_code=briefing.country_code or client.country_code,
        format=ReportFormat.PDF,
        categories_filter={
            "type": "saved_briefing",
            "client_id": client_id,
            "briefing_id": briefing.id,
            "briefing_type": briefing.briefing_type,
        },
        date_from=briefing.created_at or now,
        date_to=now,
        file_path=str(filepath),
        article_count=len(briefing.source_article_ids or []),
    )
    db.add(report)
    db.flush()
    briefing.report_id = report.id
    db.commit()
    db.refresh(report)
    db.refresh(briefing)
    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=report.article_count,
        categories=["saved_briefing", briefing.briefing_type],
        date_range=f"{report.date_from.strftime('%Y-%m-%d')} to {report.date_to.strftime('%Y-%m-%d')}",
    )


@app.get("/api/v1/subscriptions", response_model=list[SubscriptionResponse])
def list_subscriptions(
    country_code: Optional[str] = None,
    active_only: bool = False,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """List report/digest subscriptions for admin delivery control."""
    query = db.query(Subscription).order_by(Subscription.created_at.desc())
    if country_code:
        query = query.filter(Subscription.country_code == country_code)
    if active_only:
        query = query.filter(Subscription.is_active == True)
    subscriptions = query.limit(limit).all()
    return [
        SubscriptionResponse(
            id=subscription.id,
            email=subscription.email,
            name=subscription.name,
            country_code=subscription.country_code,
            categories=subscription.categories,
            frequency=subscription.frequency.value,
            format=subscription.format.value,
            is_active=subscription.is_active,
            last_sent_at=subscription.last_sent_at,
        )
        for subscription in subscriptions
    ]


@app.post("/api/v1/subscriptions", response_model=SubscriptionResponse)
def create_subscription(
    sub: SubscriptionCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Create a new report subscription."""
    subscription = Subscription(
        email=sub.email,
        name=sub.name,
        country_code=sub.country_code,
        categories=sub.categories,
        frequency=SubscriptionFrequency(sub.frequency),
        format=ReportFormat(sub.format),
    )
    db.add(subscription)
    db.commit()

    return SubscriptionResponse(
        id=subscription.id,
        email=subscription.email,
        name=subscription.name,
        country_code=subscription.country_code,
        categories=subscription.categories,
        frequency=subscription.frequency.value,
        format=subscription.format.value,
        is_active=subscription.is_active,
        last_sent_at=subscription.last_sent_at,
    )


@app.delete("/api/v1/subscriptions/{sub_id}")
def cancel_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Cancel a subscription."""
    sub = db.query(Subscription).get(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.is_active = False
    db.commit()
    return {"status": "cancelled"}


# ── Routes: Ingestion / Processing ───────────────────────────────────

@app.post("/api/v1/ingest/{country_code}", response_model=IngestResponse)
def trigger_ingestion(
    country_code: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Manually trigger article ingestion for a country and record source health."""
    # Load country config
    config_path = settings.countries_dir / f"{_code_to_filename(country_code)}.yaml"
    if not config_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Country config not found: {country_code}",
        )

    with open(config_path, encoding="utf-8") as f:
        country_config = yaml.safe_load(f)

    run = IngestionRun(
        country_code=country_code,
        run_type="manual_ingest",
        status="running",
        total_sources=len(country_config.get("sources", [])),
    )
    db.add(run)
    db.commit()

    fetcher = RSSFetcher(
        delay_seconds=settings.scrape_delay_seconds,
        max_articles=settings.max_articles_per_feed,
    )
    scraper = ArticleScraper(
        delay_seconds=settings.scrape_delay_seconds,
        max_articles_per_source=settings.max_articles_per_feed,
    )
    facebook = FacebookPageFetcher(
        access_token=settings.facebook_access_token,
        api_version=settings.facebook_api_version,
        delay_seconds=settings.scrape_delay_seconds,
        max_posts_per_page=settings.max_facebook_posts_per_page,
    )

    pipeline = ProcessingPipeline(
        session=db,
        enable_ai=settings.enable_ai_summaries,
        api_key=settings.anthropic_api_key,
        model_path=settings.models_dir,
        languages=country_config.get("languages", ["en"]),
    )
    totals = {
        "total": 0,
        "checked": 0,
        "new": 0,
        "duplicate": 0,
        "duplicate_fuzzy": 0,
        "error": 0,
        "stopped_sources": 0,
    }

    try:
        for source in country_config.get("sources", []):
            source = {**source, "country_code": country_config.get("code", country_code)}
            if source.get("is_active", True) is False:
                _record_ingestion_source_stat(
                    db=db,
                    run=run,
                    source=source,
                    discovered_urls=0,
                    scraped_count=0,
                    rss_count=0,
                    stats={"total": 0, "checked": 0, "new": 0, "duplicate": 0, "duplicate_fuzzy": 0, "error": 0},
                    status="disabled",
                    raw_articles=[],
                )
                continue
            scraper_enabled = bool((source.get("scraper") or {}).get("enabled"))
            discovered_urls = scraper.discover_article_urls(source) if scraper_enabled else []
            discovered = len(discovered_urls)
            scraped_articles = scraper.scrape_source(source, article_urls=discovered_urls)
            rss_articles = fetcher.fetch_all_feeds(source) if source.get("rss_enabled", True) else []
            raw_articles = [*scraped_articles, *rss_articles]
            source_stats = pipeline.ingest_articles(
                raw_articles,
                stop_after_consecutive_duplicates=settings.stop_after_consecutive_duplicates,
            )
            _add_ingestion_totals(totals, source_stats)
            _record_ingestion_source_stat(
                db=db,
                run=run,
                source=source,
                discovered_urls=discovered,
                scraped_count=len(scraped_articles),
                rss_count=len(rss_articles),
                stats=source_stats,
                status=_ingestion_source_status(discovered, len(scraped_articles), source_stats),
                raw_articles=raw_articles,
            )

        _merge_facebook_monitors(country_config, db, country_code)
        facebook_articles = facebook.fetch_all_pages(country_config)
        _mark_facebook_monitors_fetched(db, country_code)
        facebook_stats = pipeline.ingest_articles(
            facebook_articles,
            stop_after_consecutive_duplicates=settings.stop_after_consecutive_duplicates,
        )
        _add_ingestion_totals(totals, facebook_stats)
        if facebook_articles or country_config.get("facebook_pages"):
            _record_ingestion_source_stat(
                db=db,
                run=run,
                source={
                    "name": "Facebook Pages",
                    "url": "https://facebook.com",
                    "source_type": "social_media",
                    "scraper": {"enabled": False},
                    "rss_feeds": [],
                },
                discovered_urls=0,
                scraped_count=0,
                rss_count=0,
                stats=facebook_stats,
                status="healthy" if facebook_stats.get("new") or facebook_stats.get("duplicate") else "no_posts",
                raw_articles=facebook_articles,
            )

        run.status = "completed"
        run.finished_at = datetime.datetime.utcnow()
        run.total_raw = totals["total"]
        run.total_new = totals["new"]
        run.total_duplicate = totals["duplicate"]
        run.total_duplicate_fuzzy = totals["duplicate_fuzzy"]
        run.total_error = totals["error"]
        run.notes = f"manual trigger; stopped_sources={totals['stopped_sources']}"
        db.commit()
        return IngestResponse(**totals)
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.finished_at = datetime.datetime.utcnow()
        run.notes = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        facebook.close()
        scraper.close()
        fetcher.close()


@app.post("/api/v1/process", response_model=ProcessResponse)
def trigger_processing(
    batch_size: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Process unprocessed articles (summarize, categorize, extract entities)."""
    pipeline = ProcessingPipeline(
        session=db,
        enable_ai=settings.enable_ai_summaries,
        api_key=settings.anthropic_api_key,
        model_path=settings.models_dir,
    )

    stats = pipeline.process_unprocessed(batch_size=batch_size)
    return ProcessResponse(**stats)


# ── Routes: Countries ────────────────────────────────────────────────

@app.get("/api/v1/countries", response_model=list[CountryResponse])
def list_countries():
    """List all configured countries."""
    countries = []
    for config_file in settings.countries_dir.glob("*.yaml"):
        with open(config_file, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        feed_count = sum(
            len(s.get("rss_feeds", []))
            for s in cfg.get("sources", [])
        )

        countries.append(CountryResponse(
            name=cfg.get("name", ""),
            code=cfg.get("code", ""),
            languages=cfg.get("languages", []),
            source_count=len(cfg.get("sources", [])),
            feed_count=feed_count,
        ))

    return countries


# -- Routes: Clients / Watchlists -------------------------------------

@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """Login and create a bearer token."""
    login_key = _login_attempt_key(http_request, request.email)
    retry_after = _login_retry_after(login_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.query(User).filter(User.email == request.email.lower()).first()
    if not user or not user.is_active or not _verify_password(request.password, user.password_hash):
        _record_login_failure(login_key)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _clear_login_failures(login_key)
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=settings.token_expiry_hours)
    db.add(AuthToken(
        token_hash=_hash_token(raw_token),
        user_id=user.id,
        expires_at=expires_at,
    ))
    user.last_login_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(user)
    return LoginResponse(
        access_token=raw_token,
        expires_at=expires_at,
        user=user_to_response(user),
    )


def _login_attempt_key(request: Request, email: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{email.strip().casefold()}"


def _login_retry_after(key: str) -> int:
    now = time.monotonic()
    window_seconds = max(settings.login_window_minutes, 1) * 60
    with _login_attempts_lock:
        attempts = _login_attempts[key]
        while attempts and now - attempts[0] >= window_seconds:
            attempts.popleft()
        if len(attempts) < max(settings.login_max_attempts, 1):
            return 0
        return max(1, int(window_seconds - (now - attempts[0])))


def _record_login_failure(key: str) -> None:
    with _login_attempts_lock:
        _login_attempts[key].append(time.monotonic())


def _clear_login_failures(key: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(key, None)


@app.get("/api/v1/auth/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return user_to_response(user)


@app.post("/api/v1/auth/logout")
def logout(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Revoke the current bearer token."""
    if authorization and authorization.lower().startswith("bearer "):
        token_hash = _hash_token(authorization.split(" ", 1)[1].strip())
        auth = db.query(AuthToken).filter(AuthToken.token_hash == token_hash).first()
        if auth:
            auth.revoked_at = datetime.datetime.utcnow()
            db.commit()
    return {"status": "logged_out"}


@app.get("/api/v1/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List application users."""
    return [
        user_to_response(user)
        for user in db.query(User).order_by(User.created_at.desc()).all()
    ]


@app.post("/api/v1/users", response_model=UserResponse)
def create_user(
    request: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create an application user."""
    existing = db.query(User).filter(User.email == request.email.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")
    user = User(
        email=request.email.lower(),
        name=request.name,
        password_hash=_hash_password(request.password),
        role=UserRole(request.role),
        client_id=request.client_id,
        is_active=request.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_to_response(user)


@app.get("/api/v1/admin/facebook-pages",
         response_model=list[FacebookPageMonitorResponse])
def list_facebook_pages(
    country_code: Optional[str] = None,
    monitor_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List admin-managed Facebook Pages used for ingestion."""
    query = db.query(FacebookPageMonitor).order_by(
        FacebookPageMonitor.is_active.desc(),
        FacebookPageMonitor.monitor_type,
        FacebookPageMonitor.name,
    )
    if country_code:
        query = query.filter(FacebookPageMonitor.country_code == country_code)
    if monitor_type:
        query = query.filter(FacebookPageMonitor.monitor_type == monitor_type)
    return [facebook_monitor_to_response(page) for page in query.all()]


@app.post("/api/v1/admin/facebook-pages",
          response_model=FacebookPageMonitorResponse)
def create_facebook_page(
    request: FacebookPageMonitorCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create an admin-managed Facebook Page monitor."""
    monitor = FacebookPageMonitor(
        name=request.name,
        url=request.url,
        page_handle=request.page_handle or _facebook_handle_from_url(request.url),
        page_id=request.page_id,
        country_code=request.country_code,
        language=request.language,
        monitor_type=request.monitor_type,
        source_type=request.source_type,
        political_leaning=request.political_leaning,
        ownership=request.ownership,
        reliability_score=request.reliability_score,
        is_active=request.is_active,
        notes=request.notes,
    )
    db.add(monitor)
    _upsert_facebook_source(db, monitor)
    db.commit()
    db.refresh(monitor)
    return facebook_monitor_to_response(monitor)


@app.put("/api/v1/admin/facebook-pages/{monitor_id}",
         response_model=FacebookPageMonitorResponse)
def update_facebook_page(
    monitor_id: int,
    request: FacebookPageMonitorCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update an admin-managed Facebook Page monitor."""
    monitor = db.query(FacebookPageMonitor).get(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Facebook Page monitor not found")

    monitor.name = request.name
    monitor.url = request.url
    monitor.page_handle = request.page_handle or _facebook_handle_from_url(request.url)
    monitor.page_id = request.page_id
    monitor.country_code = request.country_code
    monitor.language = request.language
    monitor.monitor_type = request.monitor_type
    monitor.source_type = request.source_type
    monitor.political_leaning = request.political_leaning
    monitor.ownership = request.ownership
    monitor.reliability_score = request.reliability_score
    monitor.is_active = request.is_active
    monitor.notes = request.notes
    _upsert_facebook_source(db, monitor)
    db.commit()
    db.refresh(monitor)
    return facebook_monitor_to_response(monitor)


@app.delete("/api/v1/admin/facebook-pages/{monitor_id}")
def delete_facebook_page(
    monitor_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Deactivate a Facebook Page monitor."""
    monitor = db.query(FacebookPageMonitor).get(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Facebook Page monitor not found")
    monitor.is_active = False
    db.commit()
    return {"status": "deactivated"}


@app.get("/api/v1/admin/facebook/status")
def get_facebook_status(
    country_code: str = "mk",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Operational status for Facebook ingestion."""
    page_count = (
        db.query(FacebookPageMonitor)
        .filter(FacebookPageMonitor.country_code == country_code)
        .count()
    )
    active_pages = (
        db.query(FacebookPageMonitor)
        .filter(
            FacebookPageMonitor.country_code == country_code,
            FacebookPageMonitor.is_active == True,
        )
        .count()
    )
    never_fetched = (
        db.query(FacebookPageMonitor)
        .filter(
            FacebookPageMonitor.country_code == country_code,
            FacebookPageMonitor.is_active == True,
            FacebookPageMonitor.last_fetched_at.is_(None),
        )
        .count()
    )
    latest_post = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(
            Source.country_code == country_code,
            Article.ingestion_method == "facebook",
        )
        .order_by(
            func.coalesce(
                Article.published_at, Article.fetched_at, Article.ingested_at
            ).desc()
        )
        .first()
    )
    recent_count = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(
            Source.country_code == country_code,
            Article.ingestion_method == "facebook",
            Article.fetched_at >= datetime.datetime.utcnow() - datetime.timedelta(days=7),
        )
        .count()
    )

    return {
        "country_code": country_code,
        "token_configured": bool(settings.facebook_access_token),
        "api_version": settings.facebook_api_version,
        "configured_pages": page_count,
        "active_pages": active_pages,
        "never_fetched_pages": never_fetched,
        "recent_facebook_posts_7d": recent_count,
        "latest_post": article_to_response(latest_post) if latest_post else None,
    }


@app.post("/api/v1/admin/facebook/fetch")
def trigger_facebook_fetch(
    country_code: str = "mk",
    process: bool = Query(default=True),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Fetch Facebook Page posts only, using admin-managed and YAML pages."""
    config_path = settings.countries_dir / f"{_code_to_filename(country_code)}.yaml"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"Country config not found: {country_code}")

    with open(config_path, encoding="utf-8") as f:
        country_config = yaml.safe_load(f)

    _merge_facebook_monitors(country_config, db, country_code)
    facebook = FacebookPageFetcher(
        access_token=settings.facebook_access_token,
        api_version=settings.facebook_api_version,
        delay_seconds=settings.scrape_delay_seconds,
        max_posts_per_page=settings.max_facebook_posts_per_page,
    )
    raw_articles = facebook.fetch_all_pages(country_config)
    facebook.close()

    pipeline = ProcessingPipeline(
        session=db,
        enable_ai=settings.enable_ai_summaries,
        api_key=settings.anthropic_api_key,
        model_path=settings.models_dir,
        languages=country_config.get("languages", ["en"]),
    )
    ingest_stats = pipeline.ingest_articles(raw_articles)
    process_stats = {"processed": 0, "errors": 0}
    if process and ingest_stats["new"]:
        process_stats = pipeline.process_unprocessed(batch_size=ingest_stats["new"])
    if raw_articles:
        _mark_facebook_monitors_fetched(db, country_code)

    return {
        "country_code": country_code,
        "token_configured": bool(settings.facebook_access_token),
        "raw_posts": len(raw_articles),
        "ingestion": ingest_stats,
        "processing": process_stats,
    }


@app.get("/api/v1/clients", response_model=list[ClientResponse])
def list_clients(
    client_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """List client accounts/personas."""
    query = db.query(Client).order_by(Client.created_at.desc())
    if client_type:
        query = query.filter(Client.client_type == ClientType(client_type))
    return [client_to_response(client) for client in query.all()]


@app.post("/api/v1/clients", response_model=ClientResponse)
def create_client(
    request: ClientCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Create a client account/persona."""
    client = Client(
        name=request.name,
        email=request.email,
        client_type=ClientType(request.client_type),
        plan=SubscriptionPlan(request.plan),
        country_code=request.country_code,
        language=request.language,
        risk_tolerance=request.risk_tolerance,
        settings_json=request.settings,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client_to_response(client)


@app.get("/api/v1/clients/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a client account/persona."""
    client = db.query(Client).get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _authorize_client_access(user, client_id)
    return client_to_response(client)


@app.get("/api/v1/clients/{client_id}/watchlist",
         response_model=list[WatchlistItemResponse])
def list_client_watchlist(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List tracked items for a client."""
    _authorize_client_access(user, client_id)
    _get_client_or_404(db, client_id)
    items = (
        db.query(ClientWatchlistItem)
        .filter(ClientWatchlistItem.client_id == client_id)
        .order_by(ClientWatchlistItem.priority.asc(), ClientWatchlistItem.created_at.desc())
        .all()
    )
    return [watchlist_item_to_response(item) for item in items]


@app.post("/api/v1/clients/{client_id}/watchlist",
          response_model=WatchlistItemResponse)
def create_watchlist_item(
    client_id: int,
    request: WatchlistItemCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Add a tracked item to a client watchlist."""
    client = _get_client_or_404(db, client_id)
    _enforce_plan_limit(db, client, "watchlist_items")
    if WatchlistItemType(request.item_type) == WatchlistItemType.FACEBOOK_PAGE:
        _enforce_plan_limit(db, client, "facebook_pages")
    item = ClientWatchlistItem(
        client_id=client_id,
        item_type=WatchlistItemType(request.item_type),
        label=request.label,
        value=request.value,
        entity_id=request.entity_id,
        source_id=request.source_id,
        facebook_page_url=request.facebook_page_url,
        priority=request.priority,
        alert_enabled=request.alert_enabled,
        response_assist_enabled=request.response_assist_enabled,
        notes=request.notes,
    )
    db.add(item)
    _invalidate_client_dashboard_cache(db, client_id)
    db.commit()
    db.refresh(item)
    return watchlist_item_to_response(item)


@app.delete("/api/v1/clients/{client_id}/watchlist/{item_id}")
def delete_watchlist_item(
    client_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    """Remove a tracked item from a client watchlist."""
    item = (
        db.query(ClientWatchlistItem)
        .filter(
            ClientWatchlistItem.client_id == client_id,
            ClientWatchlistItem.id == item_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    db.delete(item)
    _invalidate_client_dashboard_cache(db, client_id)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/v1/clients/{client_id}/dashboard",
         response_model=ClientDashboardResponse)
def get_client_dashboard(
    client_id: int,
    days: int = Query(default=30, le=365),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Personalized dashboard data for a client watchlist."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    now = datetime.datetime.utcnow()
    if not refresh:
        cached = (
            db.query(ClientDashboardCache)
            .filter(
                ClientDashboardCache.client_id == client_id,
                ClientDashboardCache.period_days == days,
                ClientDashboardCache.expires_at > now,
            )
            .first()
        )
        if cached:
            payload = dict(cached.payload or {})
            payload["metrics"] = dict(payload.get("metrics") or {})
            payload["metrics"]["cache_status"] = "hit"
            payload["metrics"]["cache_age_seconds"] = max(
                0,
                int((now - cached.generated_at).total_seconds()),
            )
            return ClientDashboardResponse.model_validate(payload)

    watchlist = _dedupe_watchlist_items(
        db.query(ClientWatchlistItem)
        .filter(ClientWatchlistItem.client_id == client_id)
        .order_by(ClientWatchlistItem.priority.asc())
        .all()
    )

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    recent_articles = _matching_watchlist_articles(db, client, watchlist, since, limit=20)
    risk_items = _build_watchlist_risk_items(db, watchlist, since)
    high_risk_count = sum(
        1 for item in risk_items if item["severity"] in ("high", "critical")
    )

    metrics = {
        "period_days": days,
        "watchlist_items": len(watchlist),
        "matched_articles": len(recent_articles),
        "risk_items": len(risk_items),
        "high_risk_items": high_risk_count,
        "response_assist_items": sum(
            1 for item in watchlist if item.response_assist_enabled
        ),
    }

    metrics["cache_status"] = "miss"
    metrics["cache_age_seconds"] = 0
    response = ClientDashboardResponse(
        client=client_to_response(client),
        watchlist=[watchlist_item_to_response(item) for item in watchlist],
        metrics=metrics,
        risk_items=risk_items,
        recent_articles=[article_to_response(article) for article in recent_articles],
    )
    _store_client_dashboard_cache(db, client_id, days, response, now)
    return response


@app.get("/api/v1/clients/{client_id}/saved-topics")
def get_client_saved_topics(
    client_id: int,
    days: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Saved topic watch stats for a client watchlist."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    topics = (
        db.query(ClientWatchlistItem)
        .filter(
            ClientWatchlistItem.client_id == client_id,
            ClientWatchlistItem.item_type.in_([
                WatchlistItemType.TOPIC,
                WatchlistItemType.KEYWORD,
                WatchlistItemType.OPPONENT,
            ]),
        )
        .order_by(ClientWatchlistItem.priority.asc(), ClientWatchlistItem.created_at.desc())
        .all()
    )
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    rows = []
    for item in topics:
        article_rows = _articles_for_watchlist_item(db, item, since)
        articles = [row[0] for row in article_rows]
        source_names = sorted({
            article.source.name
            for article in articles
            if article.source
        })
        latest_at = None
        for article in articles:
            article_date = article.published_at or article.fetched_at or article.ingested_at
            if article_date and (latest_at is None or article_date > latest_at):
                latest_at = article_date
        validation_status = "no_coverage"
        if len(source_names) >= 5:
            validation_status = "validated"
        elif len(source_names) >= 2:
            validation_status = "multi_source"
        elif source_names:
            validation_status = "single_source"
        rows.append({
            "watchlist_item": watchlist_item_to_response(item),
            "period_days": days,
            "article_count": len(articles),
            "source_count": len(source_names),
            "validation_status": validation_status,
            "latest_at": latest_at,
            "sources": source_names[:8],
            "sample_articles": [article_to_response(article) for article in articles[:3]],
            "recommended_action": (
                "Ready for briefing; enough sources are reporting this topic."
                if validation_status == "validated"
                else "Monitor and verify; this topic is not yet broadly validated."
                if validation_status in {"single_source", "multi_source"}
                else "No recent stored coverage; broaden terms or wait for ingestion."
            ),
        })
    return rows


@app.get("/api/v1/clients/{client_id}/briefs/daily",
         response_model=ClientDailyBriefResponse)
def get_client_daily_brief(
    client_id: int,
    days: int = Query(default=1, le=30),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Client-specific daily brief from watchlist matches and risk items."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    watchlist = _dedupe_watchlist_items(
        db.query(ClientWatchlistItem)
        .filter(ClientWatchlistItem.client_id == client_id)
        .order_by(ClientWatchlistItem.priority.asc())
        .all()
    )
    matched_articles = _matching_watchlist_articles(db, client, watchlist, since, limit=8)
    risk_items = _build_watchlist_risk_items(db, watchlist, since)
    evidence_brief = _source_evidence_brief(matched_articles, limit=5)
    headline = _client_brief_headline(client, risk_items, matched_articles)
    summary = _client_brief_summary(client, matched_articles, risk_items)
    recommended_actions = _client_brief_actions(client, matched_articles, risk_items)
    copy_text = _client_brief_copy_text(
        headline=headline,
        summary=summary,
        evidence_brief=evidence_brief,
        recommended_actions=recommended_actions,
    )

    return ClientDailyBriefResponse(
        client=client_to_response(client),
        generated_at=datetime.datetime.utcnow(),
        period_days=days,
        headline=headline,
        summary=summary,
        risk_items=risk_items[:6],
        evidence_brief=evidence_brief,
        recommended_actions=recommended_actions,
        matched_articles=[article_to_response(article) for article in matched_articles],
        copy_text=copy_text,
    )


@app.post("/api/v1/clients/{client_id}/chat",
          response_model=ClientChatResponse)
def ask_client_intelligence(
    client_id: int,
    request: ClientChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Grounded client chat over permitted watchlist/persona data."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "intelligence_chat")
    plan = _plan_limits(client.plan)
    history_limit = plan["limits"].get("history_days", request.days)
    effective_days = request.days if history_limit == -1 else min(request.days, history_limit)
    turn_limit = plan["limits"].get("chat_turns_per_conversation", 10)

    conversation = None
    if request.conversation_id is not None:
        conversation = _get_chat_conversation_or_404(db, client_id, request.conversation_id)
    prior_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(12)
        .all()
        if conversation else []
    )
    prior_messages.reverse()
    prior_turns = sum(1 for message in prior_messages if message.role == "user")
    if turn_limit != -1 and prior_turns >= turn_limit:
        raise HTTPException(
            status_code=402,
            detail=f"This plan allows {turn_limit} chat turns per conversation. Start a new conversation to continue.",
        )

    settings_json = client.settings_json or {}
    wider_context_entitled = (
        user.role in (UserRole.ADMIN, UserRole.ANALYST)
        or bool(settings_json.get("chat_wider_context_enabled"))
    )
    allow_wider_context = request.include_wider_context and wider_context_entitled
    watchlist = _dedupe_watchlist_items(
        db.query(ClientWatchlistItem)
        .filter(ClientWatchlistItem.client_id == client_id)
        .order_by(ClientWatchlistItem.priority.asc())
        .all()
    )
    since = datetime.datetime.utcnow() - datetime.timedelta(days=effective_days)
    response_payload = _build_client_chat_response(
        db=db,
        client=client,
        watchlist=watchlist,
        question=request.question,
        mode=request.mode,
        since=since,
        allow_wider_context=allow_wider_context,
        requested_wider_context=request.include_wider_context,
        conversation_history=[
            {"role": message.role, "content": message.content}
            for message in prior_messages
        ],
        requested_days=request.days,
        effective_days=effective_days,
    )
    response_payload = _enhance_client_chat_with_ai(
        client=client,
        question=request.question,
        response_payload=response_payload,
        conversation_history=[
            {"role": message.role, "content": message.content}
            for message in prior_messages
        ],
    )

    now = datetime.datetime.utcnow()
    if conversation is None:
        conversation = ChatConversation(
            client_id=client.id,
            created_by_user_id=user.id,
            title=request.question.strip()[:120],
            mode=response_payload["mode"],
            is_active=True,
        )
        db.add(conversation)
        db.flush()
    conversation.mode = response_payload["mode"]
    conversation.updated_at = now

    user_message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content=request.question.strip(),
        citations=[],
        metadata_json={
            "requested_days": request.days,
            "effective_days": effective_days,
            "wider_context_requested": request.include_wider_context,
            "wider_context_allowed": allow_wider_context,
        },
    )
    assistant_message = ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=response_payload["answer"],
        citations=response_payload["citations"],
        metadata_json={
            "mode": response_payload["mode"],
            "summary": response_payload["summary"],
            "claims": response_payload["claims"],
            "legal_context": response_payload["legal_context"],
            "confidence": response_payload["confidence"],
            "restrictions": response_payload["restrictions"],
            "generation": response_payload["generation"],
        },
    )
    db.add_all([user_message, assistant_message])

    briefing = SavedBriefing(
        client_id=client.id,
        briefing_type="client_chat",
        title=f"Chat - {request.question.strip()[:90]}",
        country_code=client.country_code,
        topic=request.question.strip(),
        folder=f"chat_{conversation.id}",
        tags=["chat", client.client_type.value],
        notes="Grounded client intelligence chat answer saved for audit/history.",
        payload={
            "question": request.question,
            "mode": response_payload["mode"],
            "answer": response_payload["answer"],
            "summary": response_payload["summary"],
            "conversation_id": conversation.id,
            "turn_number": prior_turns + 1,
            "restrictions": response_payload["restrictions"],
            "suggested_actions": response_payload["suggested_actions"],
            "citations": response_payload["citations"],
            "claims": response_payload["claims"],
            "legal_context": response_payload["legal_context"],
            "matched_entities": response_payload["matched_entities"],
            "generation": response_payload["generation"],
        },
        source_article_ids=[article.id for article in response_payload["source_articles"]],
        confidence=response_payload["confidence"],
        created_by_user_id=user.id,
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(40)
        .all()
    )

    return ClientChatResponse(
        client=client_to_response(client),
        question=request.question,
        mode=response_payload["mode"],
        conversation_id=conversation.id,
        turn_number=prior_turns + 1,
        answer=response_payload["answer"],
        summary=response_payload["summary"],
        restrictions=response_payload["restrictions"],
        suggested_actions=response_payload["suggested_actions"],
        citations=response_payload["citations"],
        claims=response_payload["claims"],
        legal_context=response_payload["legal_context"],
        source_articles=[article_to_response(article) for article in response_payload["source_articles"]],
        matched_entities=response_payload["matched_entities"],
        confidence=response_payload["confidence"],
        generation=response_payload["generation"],
        history=[_chat_turn_to_response(message) for message in history],
        saved_briefing_id=briefing.id,
        disclaimer=(
            "This answer is generated from stored NewsIntel data and citations only. "
            "Verify original portal links before public use; legal claims require counsel review."
        ),
    )


@app.get(
    "/api/v1/clients/{client_id}/chat/conversations",
    response_model=list[ClientChatConversationResponse],
)
def list_client_chat_conversations(
    client_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List conversation history visible to the authenticated client account."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "intelligence_chat")
    conversations = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.client_id == client_id,
            ChatConversation.is_active == True,
        )
        .order_by(ChatConversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [_chat_conversation_to_response(item, include_messages=False) for item in conversations]


@app.get(
    "/api/v1/clients/{client_id}/chat/conversations/{conversation_id}",
    response_model=ClientChatConversationResponse,
)
def get_client_chat_conversation(
    client_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return one client-scoped conversation and its sourced transcript."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "intelligence_chat")
    conversation = _get_chat_conversation_or_404(db, client_id, conversation_id)
    return _chat_conversation_to_response(conversation, include_messages=True)


@app.post("/api/v1/clients/{client_id}/briefs/daily/report",
          response_model=ReportResponse)
def generate_client_daily_brief_report(
    client_id: int,
    days: int = Query(default=1, le=30),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a PDF export from the client-specific daily brief."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "pdf_reports")
    brief = get_client_daily_brief(client_id, days, db, user)
    payload = _model_to_export_dict(brief)

    generator = BriefingExportGenerator(settings.reports_dir)
    filepath = generator.generate_client_daily_brief(client, payload)
    date_to = datetime.datetime.utcnow()
    date_from = date_to - datetime.timedelta(days=days)
    report = Report(
        title=f"Client Daily Brief - {client.name}",
        country_code=client.country_code,
        format=ReportFormat.PDF,
        categories_filter={
            "type": "client_daily_brief",
            "client_id": client_id,
        },
        date_from=date_from,
        date_to=date_to,
        file_path=str(filepath),
        article_count=len(payload.get("matched_articles") or []),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=report.article_count,
        categories=["client_daily_brief"],
        date_range=f"{date_from.strftime('%Y-%m-%d')} to {date_to.strftime('%Y-%m-%d')}",
    )


@app.get("/api/v1/clients/{client_id}/usage",
         response_model=ClientUsageResponse)
def get_client_usage(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return plan limits and current usage for a client."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    limits = _plan_limits(client.plan)
    usage = _plan_usage(db, client_id)
    return ClientUsageResponse(
        client=client_to_response(client),
        plan=client.plan.value,
        limits=limits["limits"],
        usage=usage,
        features=limits["features"],
    )


@app.post("/api/v1/clients/{client_id}/party-briefing",
          response_model=PartyBriefingResponse)
def generate_party_briefing(
    client_id: int,
    request: PartyBriefingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Prepare a press-conference briefing from stored news/social coverage."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "campaign_war_room")

    date_to = request.date_to or datetime.datetime.utcnow()
    date_from = request.date_from or (date_to - datetime.timedelta(days=30))
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be before date_to")

    watchlist = _dedupe_watchlist_items(
        db.query(ClientWatchlistItem)
        .filter(ClientWatchlistItem.client_id == client_id)
        .order_by(ClientWatchlistItem.priority.asc())
        .all()
    )
    rows = _party_briefing_articles(
        db=db,
        client=client,
        topic=request.topic,
        requirements=" ".join(filter(None, [
            request.requirements or "",
            " ".join(request.include_entities or []),
            " ".join(request.include_opponents or []),
        ])),
        watchlist=watchlist if request.include_watchlist else [],
        date_from=date_from,
        date_to=date_to,
        limit=request.max_articles,
    )
    articles = [row[0] for row in rows]

    attack_categories = {}
    sources = set()
    for article, _, _ in rows:
        sources.add(article.source.name if article.source else "Unknown")
        text_value = f"{article.title} {article.content or ''}".lower()
        for category in _attack_categories(text_value):
            attack_categories[category] = attack_categories.get(category, 0) + 1

    coverage_summary = _build_party_coverage_summary(
        topic=request.topic,
        objective=request.objective,
        articles=articles,
        source_count=len(sources),
        date_from=date_from,
        date_to=date_to,
    )
    talking_points = _build_party_talking_points(
        topic=request.topic,
        objective=request.objective,
        requirements=request.requirements,
        articles=articles,
        attack_categories=attack_categories,
    )
    outline = _build_press_conference_outline(request.topic, request.objective, articles)
    risk_warnings = _party_risk_warnings(articles, attack_categories)
    legal_context = (
        _macedonian_legal_context(db, client.country_code, request.topic, request.requirements)
        if request.include_legal_context else []
    )
    evidence_brief = _source_evidence_brief(articles)
    citation_pack = _citation_pack(evidence_brief)
    evidence_buckets = _party_evidence_buckets(articles)
    claim_support_matrix = _claim_support_matrix(
        topic=request.topic,
        requirements=request.requirements,
        articles=articles,
        legal_context=legal_context,
        extra_claims=[
            *[f"Entity to mention: {item}" for item in request.include_entities],
            *[f"Opponent/claim to address: {item}" for item in request.include_opponents],
        ],
    )
    confidence = _briefing_confidence(
        articles=articles,
        source_count=len(sources),
        legal_context=legal_context,
    )
    grounding_contract = _grounding_contract(
        evidence_brief=evidence_brief,
        citation_pack=citation_pack,
        claim_support_matrix=claim_support_matrix,
        legal_context=legal_context,
        confidence=confidence,
    )
    claims_to_verify = _claims_to_verify(
        topic=request.topic,
        requirements=request.requirements,
        articles=articles,
        legal_context=legal_context,
    )
    claims_to_verify.extend(_claim_matrix_verification_notes(claim_support_matrix))
    do_not_say = _party_do_not_say_unless_verified(
        articles=articles,
        legal_context=legal_context,
        requirements=request.requirements,
    )
    do_not_say.extend(_claim_matrix_do_not_say(claim_support_matrix))
    briefing_strategy = _party_briefing_strategy(
        topic=request.topic,
        objective=request.objective,
        audience=request.audience,
        tone=request.tone,
        evidence_brief=evidence_brief,
        citation_pack=citation_pack,
        claim_support_matrix=claim_support_matrix,
        claims_to_verify=claims_to_verify,
        do_not_say=do_not_say,
        risk_warnings=risk_warnings,
        legal_context=legal_context,
        grounding_contract=grounding_contract,
        attack_categories=attack_categories,
        source_count=len(sources),
        article_count=len(articles),
    )
    draft_outputs = _party_draft_outputs(
        topic=request.topic,
        objective=request.objective,
        audience=request.audience,
        tone=request.tone,
        evidence_brief=evidence_brief,
        claims_to_verify=claims_to_verify,
        legal_context=legal_context,
        briefing_strategy=briefing_strategy,
    )
    party_generation = _grounded_work_product_generation(
        task=(
            f"Prepare an evidence-bound press-conference briefing on {request.topic}. "
            f"Objective: {request.objective or 'explain the verified position clearly'}."
        ),
        instructions=(
            f"Audience: {request.audience or 'general public'}. Tone: {request.tone or 'statesmanlike'}. "
            "The answer should be a concise opening statement. Claims must remain attributed "
            "to sources; legal references are not legal conclusions."
        ),
        citation_pack=citation_pack,
        legal_context=legal_context,
    )
    if party_generation.accepted:
        generated = party_generation.payload
        coverage_summary = generated["summary"]
        talking_points = [
            f"{claim['text']} {' '.join(f'[{label}]' for label in claim['citation_labels'])}"
            for claim in generated["claims"]
        ]
        draft_outputs["ai_evidence_bound_opening"] = {
            "text": generated["answer"],
            "status": "internal_review",
            "grounding_validated": True,
        }
        briefing_strategy["ai_recommended_actions"] = generated["suggested_actions"]

    return PartyBriefingResponse(
        client=client_to_response(client),
        topic=request.topic,
        objective=request.objective,
        audience=request.audience,
        tone=request.tone,
        date_range=(
            f"{date_from.strftime('%Y-%m-%d')} to "
            f"{date_to.strftime('%Y-%m-%d')}"
        ),
        coverage_summary=coverage_summary,
        verified_facts=evidence_buckets["verified_facts"],
        single_source_claims=evidence_buckets["single_source_claims"],
        evidence_brief=evidence_brief,
        citation_pack=citation_pack,
        claim_support_matrix=claim_support_matrix,
        claims_to_verify=claims_to_verify,
        confidence=confidence,
        generation=party_generation.metadata(),
        grounding_contract=grounding_contract,
        briefing_strategy=briefing_strategy,
        suggested_talking_points=talking_points,
        press_conference_outline=outline,
        draft_outputs=draft_outputs,
        do_not_say_unless_verified=do_not_say,
        risk_warnings=risk_warnings,
        legal_context=legal_context,
        source_articles=[article_to_response(article) for article in articles],
        disclaimer=(
            "This briefing is communications intelligence, not legal advice. "
            "Use official legal texts and qualified Macedonian counsel before making legal claims."
        ),
    )


@app.post("/api/v1/clients/{client_id}/party-briefing/report",
          response_model=ReportResponse)
def generate_party_briefing_report(
    client_id: int,
    request: PartyBriefingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a client-ready PDF from a party briefing request."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "pdf_reports")
    briefing = generate_party_briefing(client_id, request, db, user)
    payload = _model_to_export_dict(briefing)

    generator = BriefingExportGenerator(settings.reports_dir)
    filepath = generator.generate_party_briefing(client, payload)
    date_from = request.date_from or (datetime.datetime.utcnow() - datetime.timedelta(days=30))
    date_to = request.date_to or datetime.datetime.utcnow()
    report = Report(
        title=f"Party Briefing - {request.topic}",
        country_code=client.country_code,
        format=ReportFormat.PDF,
        categories_filter={
            "type": "party_briefing",
            "client_id": client_id,
            "topic": request.topic,
        },
        date_from=date_from,
        date_to=date_to,
        file_path=str(filepath),
        article_count=len(payload.get("source_articles") or []),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=report.article_count,
        categories=["party_briefing"],
        date_range=payload.get("date_range", ""),
    )


@app.get("/api/v1/clients/{client_id}/response-pack/{watchlist_item_id}",
         response_model=ResponsePackResponse)
def get_response_pack(
    client_id: int,
    watchlist_item_id: int,
    days: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a first-pass response pack for a tracked risk item."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "response_assistant")
    item = (
        db.query(ClientWatchlistItem)
        .filter(
            ClientWatchlistItem.client_id == client_id,
            ClientWatchlistItem.id == watchlist_item_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    article_rows = _articles_for_watchlist_item(db, item, since)[:12]
    risk_item = _risk_item_from_article_rows(db, item, article_rows)
    source_articles = [row[0] for row in article_rows[:8]]
    pack = _build_response_pack(db, client, item, risk_item, source_articles)

    return ResponsePackResponse(
        client=client_to_response(client),
        watchlist_item=watchlist_item_to_response(item),
        severity=pack["severity"],
        situation_summary=pack["situation_summary"],
        evidence_brief=pack["evidence_brief"],
        citation_pack=pack["citation_pack"],
        claim_support_matrix=pack["claim_support_matrix"],
        claims_to_verify=pack["claims_to_verify"],
        confidence=pack["confidence"],
        generation=pack["generation"],
        grounding_contract=pack["grounding_contract"],
        attack_analysis=pack["attack_analysis"],
        response_strategy=pack["response_strategy"],
        recommended_posture=pack["recommended_posture"],
        legal_review_flags=pack["legal_review_flags"],
        legal_context=pack["legal_context"],
        evidence_steps=pack["evidence_steps"],
        draft_responses=pack["draft_responses"],
        source_articles=[article_to_response(article) for article in source_articles],
        disclaimer=(
            "This is communications support and legal-risk triage, not legal advice. "
            "Use a qualified Macedonian lawyer for final legal positions."
        ),
    )


@app.post("/api/v1/clients/{client_id}/response-pack/{watchlist_item_id}/report",
          response_model=ReportResponse)
def generate_response_pack_report(
    client_id: int,
    watchlist_item_id: int,
    days: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a client-ready PDF directly from a response pack."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "pdf_reports")
    pack = get_response_pack(client_id, watchlist_item_id, days, db, user)
    payload = _model_to_export_dict(pack)

    generator = BriefingExportGenerator(settings.reports_dir)
    filepath = generator.generate_response_pack(client, payload)
    date_to = datetime.datetime.utcnow()
    date_from = date_to - datetime.timedelta(days=days)
    report = Report(
        title=f"Response Pack - {payload.get('watchlist_item', {}).get('label', watchlist_item_id)}",
        country_code=client.country_code,
        format=ReportFormat.PDF,
        categories_filter={
            "type": "response_pack",
            "client_id": client_id,
            "watchlist_item_id": watchlist_item_id,
        },
        date_from=date_from,
        date_to=date_to,
        file_path=str(filepath),
        article_count=len(payload.get("source_articles") or []),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=report.article_count,
        categories=["response_pack"],
        date_range=f"{date_from.strftime('%Y-%m-%d')} to {date_to.strftime('%Y-%m-%d')}",
    )


@app.get("/api/v1/clients/{client_id}/attack-timeline/{watchlist_item_id}")
def get_attack_timeline(
    client_id: int,
    watchlist_item_id: int,
    days: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Show how a tracked attack/risk item appeared and spread."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    item = (
        db.query(ClientWatchlistItem)
        .filter(
            ClientWatchlistItem.client_id == client_id,
            ClientWatchlistItem.id == watchlist_item_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    rows = _articles_for_watchlist_item(db, item, since)
    review_map = _attack_review_map(
        db,
        [item.id],
        [article.id for article, _, _ in rows],
    )
    events = []
    source_counts = {}
    category_counts = {}

    for article, sentiment, mention_count in rows:
        event_at = article.published_at or article.fetched_at or article.ingested_at
        detail = _apply_attack_review(
            _attack_detail_for_article(item, article),
            review_map.get((item.id, article.id)),
        )
        categories = detail["categories"] if detail["is_attack"] else []
        attack_language = detail["is_attack"]
        source_name = article.source.name if article.source else "Unknown"
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
        for category in categories:
            category_counts[category] = category_counts.get(category, 0) + 1

        events.append({
            "article_id": article.id,
            "title": article.title,
            "url": article.url,
            "source_name": source_name,
            "source_type": article.source.source_type if article.source else "unknown",
            "reliability_score": article.source.reliability_score if article.source else None,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
            "event_at": event_at.isoformat() if event_at else None,
            "sentiment": sentiment,
            "mention_count": mention_count or 1,
            "attack_language": attack_language,
            "attack_categories": categories,
            "attacker": detail.get("attacker"),
            "target": detail.get("target"),
            "allegation": detail.get("allegation"),
            "quote": detail.get("quote"),
            "attack_confidence": detail.get("confidence"),
            "attack_confidence_label": detail.get("confidence_label"),
            "extraction_basis": detail.get("extraction_basis", []),
            "ingestion_method": article.ingestion_method,
            "platform": article.platform,
        })

    events.sort(key=lambda event: event["event_at"] or "")
    first_event = events[0] if events else None
    last_event = events[-1] if events else None
    amplifiers = sorted(
        [{"source_name": name, "count": count} for name, count in source_counts.items()],
        key=lambda row: row["count"],
        reverse=True,
    )
    source_count = len(source_counts)
    attack_event_count = sum(1 for event in events if event["attack_language"])
    negative_event_count = sum(1 for event in events if event["sentiment"] is not None and event["sentiment"] < -0.05)
    if source_count >= 5:
        spread_label = "broad_spread"
    elif source_count >= 2:
        spread_label = "multi_source"
    elif source_count == 1:
        spread_label = "single_source"
    else:
        spread_label = "no_recent_spread"

    if attack_event_count >= 3 and source_count >= 3:
        recommended_urgency = "Prepare a source-cited response in the current news cycle and keep legal review on standby."
    elif attack_event_count:
        recommended_urgency = "Prepare a cautious holding response and monitor whether the claim spreads beyond the first sources."
    elif events:
        recommended_urgency = "Monitor mentions and avoid escalating unless attack language or broader spread appears."
    else:
        recommended_urgency = "No recent events found for this tracked item."

    timeline_summary = (
        f"{len(events)} recent events across {source_count} sources; "
        f"{attack_event_count} attack-language signals and {negative_event_count} negative sentiment signals."
    )

    return {
        "watchlist_item": watchlist_item_to_response(item),
        "period_days": days,
        "event_count": len(events),
        "source_count": source_count,
        "attack_event_count": attack_event_count,
        "negative_event_count": negative_event_count,
        "spread_label": spread_label,
        "timeline_summary": timeline_summary,
        "recommended_urgency": recommended_urgency,
        "first_seen_at": first_event.get("event_at") if first_event else None,
        "last_seen_at": last_event.get("event_at") if last_event else None,
        "first_seen": first_event,
        "amplifiers": amplifiers,
        "attack_categories": category_counts,
        "events": events,
    }


@app.get("/api/v1/clients/{client_id}/incidents",
         response_model=list[IncidentResponse])
def list_client_incidents(
    client_id: int,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List saved attack/risk case files for a client."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    query = (
        db.query(ClientIncident)
        .filter(ClientIncident.client_id == client_id)
        .order_by(ClientIncident.updated_at.desc(), ClientIncident.created_at.desc())
    )
    if status:
        query = query.filter(ClientIncident.status == IncidentStatus(status))
    return [incident_to_response(incident) for incident in query.all()]


@app.post("/api/v1/clients/{client_id}/incidents",
          response_model=IncidentResponse)
def create_client_incident(
    client_id: int,
    request: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save a response pack or risk signal as a client case file."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_limit(db, client, "incidents")
    if request.watchlist_item_id:
        item = (
            db.query(ClientWatchlistItem)
            .filter(
                ClientWatchlistItem.client_id == client_id,
                ClientWatchlistItem.id == request.watchlist_item_id,
            )
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="Watchlist item not found")

    now = datetime.datetime.utcnow()
    incident = ClientIncident(
        client_id=client_id,
        watchlist_item_id=request.watchlist_item_id,
        title=request.title,
        severity=request.severity,
        status=IncidentStatus(request.status),
        summary=request.summary,
        recommended_posture=request.recommended_posture,
        legal_review_flags=request.legal_review_flags,
        evidence_steps=request.evidence_steps,
        draft_responses=request.draft_responses,
        source_article_ids=request.source_article_ids,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(incident)
    db.flush()
    _seed_incident_evidence_from_articles(db, incident, request.source_article_ids)
    db.commit()
    db.refresh(incident)
    return incident_to_response(incident)


@app.patch("/api/v1/clients/{client_id}/incidents/{incident_id}",
           response_model=IncidentResponse)
def update_client_incident(
    client_id: int,
    incident_id: int,
    request: IncidentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update status/details for a saved client case file."""
    _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    incident = (
        db.query(ClientIncident)
        .filter(
            ClientIncident.client_id == client_id,
            ClientIncident.id == incident_id,
        )
        .first()
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if request.title is not None:
        incident.title = request.title
    if request.severity is not None:
        incident.severity = request.severity
    if request.status is not None:
        incident.status = IncidentStatus(request.status)
    if request.summary is not None:
        incident.summary = request.summary
    if request.recommended_posture is not None:
        incident.recommended_posture = request.recommended_posture
    if request.legal_review_flags is not None:
        incident.legal_review_flags = request.legal_review_flags
    if request.evidence_steps is not None:
        incident.evidence_steps = request.evidence_steps
    if request.draft_responses is not None:
        incident.draft_responses = request.draft_responses
    if request.source_article_ids is not None:
        incident.source_article_ids = request.source_article_ids

    incident.last_seen_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(incident)
    return incident_to_response(incident)


@app.get("/api/v1/clients/{client_id}/incidents/{incident_id}/evidence",
         response_model=list[EvidenceResponse])
def list_incident_evidence(
    client_id: int,
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List preserved evidence for a case file."""
    _authorize_client_access(user, client_id)
    _get_incident_or_404(db, client_id, incident_id)
    evidence = (
        db.query(ClientIncidentEvidence)
        .filter(ClientIncidentEvidence.incident_id == incident_id)
        .order_by(ClientIncidentEvidence.captured_at.desc())
        .all()
    )
    return [evidence_to_response(item) for item in evidence]


@app.post("/api/v1/clients/{client_id}/incidents/{incident_id}/evidence",
          response_model=EvidenceResponse)
def create_incident_evidence(
    client_id: int,
    incident_id: int,
    request: EvidenceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Attach a URL/article/screenshot reference to a case file."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "evidence_archive")
    _get_incident_or_404(db, client_id, incident_id)
    evidence = ClientIncidentEvidence(
        incident_id=incident_id,
        article_id=request.article_id,
        url=request.url,
        title=request.title,
        source_name=request.source_name,
        evidence_type=request.evidence_type,
        published_at=request.published_at,
        content_hash=request.content_hash,
        screenshot_path=request.screenshot_path,
        notes=request.notes,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence_to_response(evidence)


# ── Routes: Alerts ───────────────────────────────────────────────────

@app.post("/api/v1/clients/{client_id}/incidents/{incident_id}/report",
          response_model=ReportResponse)
def generate_incident_report(
    client_id: int,
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a client-ready PDF dossier for an incident case file."""
    client = _get_client_or_404(db, client_id)
    _authorize_client_access(user, client_id)
    _enforce_plan_feature(client, "pdf_reports")
    incident = _get_incident_or_404(db, client_id, incident_id)
    evidence_items = (
        db.query(ClientIncidentEvidence)
        .filter(ClientIncidentEvidence.incident_id == incident_id)
        .order_by(ClientIncidentEvidence.captured_at.asc())
        .all()
    )

    generator = IncidentReportGenerator(settings.reports_dir)
    filepath = generator.generate(client, incident, evidence_items)

    date_from = incident.first_seen_at or incident.created_at
    date_to = incident.last_seen_at or datetime.datetime.utcnow()
    report = Report(
        title=f"Incident Report - {incident.title}",
        country_code=client.country_code,
        format=ReportFormat.PDF,
        categories_filter={
            "type": "incident",
            "client_id": client_id,
            "incident_id": incident_id,
        },
        date_from=date_from,
        date_to=date_to,
        file_path=str(filepath),
        article_count=len(evidence_items),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return ReportResponse(
        report_id=report.id,
        file_path=str(filepath),
        article_count=len(evidence_items),
        categories=["incident"],
        date_range=(
            f"{date_from.strftime('%Y-%m-%d')} to "
            f"{date_to.strftime('%Y-%m-%d')}"
        ),
    )
def _alert_response(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "name": alert.name,
        "alert_type": alert.alert_type.value,
        "channel": alert.channel.value,
        "criteria": alert.criteria,
        "is_active": alert.is_active,
        "total_triggers": alert.total_triggers,
        "last_triggered_at": (
            alert.last_triggered_at.isoformat() if alert.last_triggered_at else None
        ),
    }


def _risk_suggestion_alert_payload(request: RiskAlertSuggestionCreate) -> tuple[AlertType, dict]:
    criteria = dict(request.criteria or {})
    suggestion_type = request.suggestion_type
    if suggestion_type == "risk_threshold":
        criteria.setdefault("risk_score_gte", 70)
        criteria.setdefault("window_hours", 24)
        return AlertType.RISK_SCORE, criteria
    if suggestion_type == "story_spread":
        criteria.setdefault("source_count_gte", 3)
        criteria.setdefault("status", "validated")
        criteria.setdefault("window_hours", 24)
        return AlertType.STORY_SPREAD, criteria
    if suggestion_type == "attack_theme":
        criteria.setdefault("count_gte", 3)
        criteria.setdefault("window_hours", 24)
        return AlertType.ATTACK_THEME, criteria
    if suggestion_type == "watchlist_negative_story":
        criteria.setdefault("risk_score_gte", 55)
        criteria.setdefault("window_hours", 24)
        return AlertType.RISK_SCORE, criteria
    raise HTTPException(status_code=400, detail=f"Unsupported risk suggestion type: {suggestion_type}")


@app.post("/api/v1/alerts/from-risk-suggestion")
def create_alert_from_risk_suggestion(
    request: RiskAlertSuggestionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create an actionable alert rule from a political-risk suggestion."""
    _authorize_alert_email(user, request.user_email)
    alert_type, criteria = _risk_suggestion_alert_payload(request)
    try:
        channel = AlertChannel(request.channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    alert = Alert(
        name=request.label,
        user_email=request.user_email,
        alert_type=alert_type,
        channel=channel,
        criteria=criteria,
        channel_config={},
        country_code=request.country_code,
        cooldown_minutes=request.cooldown_minutes,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return _alert_response(alert)


@app.post("/api/v1/alerts/json")
def create_alert_json(
    request: AlertCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new alert rule from a JSON body."""
    _authorize_alert_email(user, request.user_email)
    try:
        alert_type = AlertType(request.alert_type)
        channel = AlertChannel(request.channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = (
        db.query(Alert)
        .filter(
            Alert.name == request.name,
            Alert.user_email == request.user_email,
            Alert.alert_type == alert_type,
            Alert.country_code == request.country_code,
        )
        .first()
    )
    if existing:
        existing.channel = channel
        existing.criteria = request.criteria
        existing.channel_config = request.channel_config or {}
        existing.cooldown_minutes = request.cooldown_minutes
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return _alert_response(existing)

    alert = Alert(
        name=request.name,
        user_email=request.user_email,
        alert_type=alert_type,
        channel=channel,
        criteria=request.criteria,
        channel_config=request.channel_config or {},
        country_code=request.country_code,
        cooldown_minutes=request.cooldown_minutes,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return _alert_response(alert)


@app.post("/api/v1/alerts")
def create_alert(
    name: str,
    user_email: str,
    alert_type: str,         # entity, keyword, category, sentiment, volume
    channel: str,            # email, webhook, telegram, in_app
    criteria: dict,          # flexible JSON — see Alert model for examples
    channel_config: dict = None,
    country_code: Optional[str] = None,
    cooldown_minutes: int = 60,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new alert rule."""
    _authorize_alert_email(user, user_email)
    alert = Alert(
        name=name,
        user_email=user_email,
        alert_type=AlertType(alert_type),
        channel=AlertChannel(channel),
        criteria=criteria,
        channel_config=channel_config or {},
        country_code=country_code,
        cooldown_minutes=cooldown_minutes,
    )
    db.add(alert)
    db.commit()

    return {
        "id": alert.id,
        "name": alert.name,
        "alert_type": alert.alert_type.value,
        "channel": alert.channel.value,
        "criteria": alert.criteria,
        "is_active": alert.is_active,
    }


@app.get("/api/v1/alerts")
def list_alerts(
    user_email: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all alerts, optionally filtered by user."""
    query = db.query(Alert)
    if user.role == UserRole.CLIENT:
        query = query.filter(Alert.user_email == user.email)
    elif user_email:
        query = query.filter(Alert.user_email == user_email)

    alerts = query.all()
    return [_alert_response(a) for a in alerts]


@app.delete("/api/v1/alerts/{alert_id}")
def delete_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deactivate an alert."""
    alert = db.query(Alert).get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    _authorize_alert_email(user, alert.user_email)
    alert.is_active = False
    db.commit()
    return {"status": "deactivated"}


@app.get("/api/v1/alerts/{alert_id}/notifications")
def get_alert_notifications(
    alert_id: int,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get notification history for an alert."""
    alert = db.query(Alert).get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    _authorize_alert_email(user, alert.user_email)
    notifications = (
        db.query(AlertNotification)
        .filter(AlertNotification.alert_id == alert_id)
        .order_by(AlertNotification.sent_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": n.id,
            "alert_id": n.alert_id,
            "articles_matched": n.articles_matched,
            "payload": n.payload,
            "channel": n.channel.value,
            "sent_at": n.sent_at.isoformat(),
            "delivered": n.delivered,
            "is_read": n.is_read,
        }
        for n in notifications
    ]


@app.get("/api/v1/notifications/unread")
def get_unread_notifications(
    user_email: str,
    limit: int = Query(default=50, le=100),
    db: Session = Depends(get_db),
):
    """Get unread in-app notifications for a user."""
    notifications = (
        db.query(AlertNotification)
        .join(Alert)
        .filter(
            Alert.user_email == user_email,
            AlertNotification.channel == AlertChannel.IN_APP,
            AlertNotification.is_read == False,
        )
        .order_by(AlertNotification.sent_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": n.id,
            "alert_id": n.alert_id,
            "articles_matched": n.articles_matched,
            "payload": n.payload,
            "sent_at": n.sent_at.isoformat(),
        }
        for n in notifications
    ]


@app.post("/api/v1/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    """Mark a notification as read."""
    notification = db.query(AlertNotification).get(notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    return {"status": "read"}


# ── Routes: Sentiment ────────────────────────────────────────────────

@app.get("/api/v1/entities/{entity_id}/sentiment")
def get_entity_sentiment(
    entity_id: int,
    days: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
):
    """
    Get sentiment analysis for an entity over time.

    Returns overall sentiment, trend direction, and per-article scores.
    """
    entity = db.query(Entity).get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    previous_start = since - datetime.timedelta(days=days)

    # Recent mentions with sentiment
    recent = (
        db.query(EntityMention, Article)
        .join(Article)
        .filter(
            EntityMention.entity_id == entity_id,
            EntityMention.sentiment_score.isnot(None),
            Article.published_at >= since,
            _active_article_filter(),
        )
        .order_by(Article.published_at.desc())
        .all()
    )

    # Previous period for trend comparison
    previous = (
        db.query(EntityMention)
        .join(Article)
        .filter(
            EntityMention.entity_id == entity_id,
            EntityMention.sentiment_score.isnot(None),
            Article.published_at >= previous_start,
            Article.published_at < since,
            _active_article_filter(),
        )
        .all()
    )

    recent_scores = [m.sentiment_score for m, _ in recent]
    previous_scores = [m.sentiment_score for m in previous]

    # Compute trend
    analyzer = SentimentAnalyzer()
    trend = analyzer.compute_sentiment_trend(recent_scores, previous_scores)

    # Build timeline data (daily averages)
    daily_scores: dict[str, list[float]] = {}
    for mention, article in recent:
        if article.published_at:
            day_key = article.published_at.strftime("%Y-%m-%d")
            daily_scores.setdefault(day_key, []).append(mention.sentiment_score)

    timeline = [
        {
            "date": day,
            "avg_sentiment": round(sum(scores) / len(scores), 4),
            "article_count": len(scores),
            "min_sentiment": round(min(scores), 4),
            "max_sentiment": round(max(scores), 4),
        }
        for day, scores in sorted(daily_scores.items())
    ]

    return {
        "entity": {
            "id": entity.id,
            "name": entity.name,
            "type": entity.entity_type.value,
        },
        "period_days": days,
        "total_scored_mentions": len(recent_scores),
        "overall_sentiment": round(
            sum(recent_scores) / max(len(recent_scores), 1), 4
        ),
        "sentiment_label": (
            "positive" if sum(recent_scores) / max(len(recent_scores), 1) > 0.05
            else "negative" if sum(recent_scores) / max(len(recent_scores), 1) < -0.05
            else "neutral"
        ),
        "trend": trend,
        "timeline": timeline,
        "recent_mentions": [
            {
                "article_id": article.id,
                "title": article.title,
                "url": article.url,
                "published_at": (
                    article.published_at.isoformat() if article.published_at else None
                ),
                "sentiment_score": mention.sentiment_score,
                "context": mention.context_snippet,
            }
            for mention, article in recent[:20]
        ],
    }


# ── Health check ─────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.datetime.utcnow().isoformat()}


# ── Helpers ──────────────────────────────────────────────────────────

def _get_client_or_404(db: Session, client_id: int) -> Client:
    client = db.query(Client).get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _authorize_client_access(user: User, client_id: int):
    if user.role in (UserRole.ADMIN, UserRole.ANALYST):
        return
    if user.role == UserRole.CLIENT and user.client_id == client_id:
        return
    raise HTTPException(status_code=403, detail="Client access denied")


def _get_chat_conversation_or_404(
    db: Session,
    client_id: int,
    conversation_id: int,
) -> ChatConversation:
    conversation = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.client_id == client_id,
            ChatConversation.is_active == True,
        )
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Chat conversation not found")
    return conversation


def _chat_turn_to_response(message: ChatMessage) -> ClientChatTurnResponse:
    return ClientChatTurnResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        citations=message.citations or [],
        metadata=message.metadata_json or {},
        created_at=message.created_at,
    )


def _chat_conversation_to_response(
    conversation: ChatConversation,
    include_messages: bool,
) -> ClientChatConversationResponse:
    messages = list(conversation.messages) if include_messages else []
    return ClientChatConversationResponse(
        id=conversation.id,
        client_id=conversation.client_id,
        title=conversation.title,
        mode=conversation.mode,
        message_count=len(conversation.messages),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_chat_turn_to_response(message) for message in messages],
    )


def _authorize_alert_email(user: User, user_email: str):
    if user.role in (UserRole.ADMIN, UserRole.ANALYST):
        return
    if user.role == UserRole.CLIENT and user.email.lower() == user_email.lower():
        return
    raise HTTPException(status_code=403, detail="Alert access denied")


def _scheduler_pid_file() -> Path:
    return settings.base_dir / "data" / "scheduler.pid"


def _scheduler_heartbeat_file() -> Path:
    return settings.base_dir / "data" / "scheduler_heartbeat.json"


def _backup_dir() -> Path:
    path = settings.base_dir / "data" / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _config_backup_dir() -> Path:
    path = settings.base_dir / "config" / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        import os
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _scheduler_process_status() -> dict:
    pid_file = _scheduler_pid_file()
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
    running = _process_running(pid) if pid else False
    if pid and not running:
        pid_file.unlink(missing_ok=True)
    return {"pid": pid, "running": running, "pid_file": str(pid_file)}


def _scheduler_heartbeat_status() -> dict:
    heartbeat = _scheduler_heartbeat_file()
    if not heartbeat.exists():
        return {
            "exists": False,
            "path": str(heartbeat),
            "age_minutes": None,
            "healthy": False,
            "payload": None,
        }
    try:
        payload = json.loads(heartbeat.read_text(encoding="utf-8"))
        raw_seen = payload.get("updated_at")
        seen_at = datetime.datetime.fromisoformat(raw_seen) if raw_seen else None
        age_minutes = (
            round((datetime.datetime.utcnow() - seen_at).total_seconds() / 60)
            if seen_at else None
        )
        healthy = age_minutes is not None and age_minutes <= settings.ingestion_interval_minutes * 2
        return {
            "exists": True,
            "path": str(heartbeat),
            "age_minutes": age_minutes,
            "healthy": healthy,
            "payload": payload,
        }
    except Exception as exc:
        return {
            "exists": True,
            "path": str(heartbeat),
            "age_minutes": None,
            "healthy": False,
            "payload": None,
            "error": str(exc),
        }


def _source_admin_response(source: Optional[Source]) -> Optional[dict]:
    if not source:
        return None
    yaml_config = _find_source_config(_load_country_config(source.country_code), source.name)
    yaml_ops = _source_yaml_operational(yaml_config)
    return {
        "source_id": source.id,
        "name": source.name,
        "url": source.url,
        "country_code": source.country_code,
        "language": source.language,
        "reliability_score": source.reliability_score,
        "source_type": source.source_type,
        "political_leaning": source.political_leaning,
        "ownership": source.ownership,
        "is_active": source.is_active,
        "rss_feeds": source.rss_feeds or [],
        "last_fetched_at": source.last_fetched_at,
        **yaml_ops,
    }


def _source_yaml_operational(source_config: Optional[dict]) -> dict:
    scraper = (source_config or {}).get("scraper") or {}
    rss_feeds = (source_config or {}).get("rss_feeds") or []
    return {
        "yaml_configured": bool(source_config),
        "scraper_enabled": bool(scraper.get("enabled")),
        "rss_enabled": bool((source_config or {}).get("rss_enabled", True)) and bool(rss_feeds),
        "yaml_note": scraper.get("note") or (source_config or {}).get("note"),
        "min_word_count": scraper.get("min_word_count"),
        "listing_urls": scraper.get("listing_urls") or [],
    }


def _load_country_config(country_code: str) -> dict:
    path = settings.countries_dir / f"{_code_to_filename(country_code)}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Country config not found: {country_code}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_country_config(country_code: str, country_config: dict) -> dict:
    path = settings.countries_dir / f"{_code_to_filename(country_code)}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Country config not found: {country_code}")
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup = _config_backup_dir() / f"{path.stem}-{stamp}.yaml"
    shutil.copy2(path, backup)
    text = yaml.safe_dump(country_config, sort_keys=False, allow_unicode=True, width=120)
    path.write_text(text, encoding="utf-8")
    return {"path": str(path), "backup": str(backup), "updated_at": datetime.datetime.utcnow().isoformat()}


def _find_source_config(country_config: dict, source_name: str) -> Optional[dict]:
    for source in country_config.get("sources", []):
        if source.get("name") == source_name:
            return source
    return None


def _persist_source_config_to_yaml(source: Source, request: SourceUpdate) -> Optional[dict]:
    country_config = _load_country_config(source.country_code)
    source_config = _find_source_config(country_config, source.name)
    if not source_config:
        return {"status": "not_found", "message": "Source is not present in the country YAML config."}

    for field in ("language", "source_type", "political_leaning", "ownership", "reliability_score"):
        value = getattr(request, field)
        if value is not None:
            source_config[field] = value
    if request.is_active is not None:
        source_config["is_active"] = request.is_active
    if request.rss_enabled is not None:
        source_config["rss_enabled"] = request.rss_enabled
    scraper = source_config.setdefault("scraper", {})
    if request.scraper_enabled is not None:
        scraper["enabled"] = request.scraper_enabled
    if request.min_word_count is not None:
        scraper["min_word_count"] = request.min_word_count
    if request.note is not None:
        scraper["note"] = request.note

    result = _write_country_config(source.country_code, country_config)
    result["status"] = "persisted"
    return result


def _source_config_validation_report(country_code: str, db: Session) -> dict:
    country_config = _load_country_config(country_code)
    db_sources = {
        source.name: source
        for source in db.query(Source).filter(Source.country_code == country_code).all()
    }
    rows = [
        _source_config_validation_row(source_config, db_sources.get(source_config.get("name", "")))
        for source_config in country_config.get("sources", [])
    ]
    db_only = sorted(set(db_sources) - {row["source_name"] for row in rows})
    summary = {
        "total_sources": len(rows),
        "healthy_count": len([row for row in rows if row["status"] == "healthy"]),
        "warning_count": len([row for row in rows if row["status"] == "warning"]),
        "critical_count": len([row for row in rows if row["status"] == "critical"]),
        "disabled_count": len([row for row in rows if row["status"] == "disabled"]),
        "db_only_count": len(db_only),
        "issue_count": sum(len(row["issues"]) for row in rows) + len(db_only),
    }
    recommendations = []
    if summary["critical_count"]:
        recommendations.append("Fix critical source config issues before relying on scheduled ingestion.")
    if summary["warning_count"]:
        recommendations.append("Review warning-level selector/RSS metadata gaps during source polish.")
    if db_only:
        recommendations.append("Some DB sources are not represented in YAML; reconcile DB seed/config state.")
    if not recommendations:
        recommendations.append("Source configuration looks ready for scraper/RSS preflight.")
    return {
        "country_code": country_code,
        "config_path": str(settings.countries_dir / f"{_code_to_filename(country_code)}.yaml"),
        "summary": summary,
        "recommendations": recommendations,
        "sources": rows,
        "db_only_sources": db_only,
    }


def _sync_source_config_to_db(source_config: dict, country_code: str, db: Session) -> dict:
    name = source_config.get("name") or ""
    url = source_config.get("url") or ""
    if not name or not url:
        return {
            "status": "skipped",
            "source_id": None,
            "name": name,
            "url": url,
            "changes": ["missing_name_or_url"],
        }

    source = (
        db.query(Source)
        .filter(Source.country_code == country_code)
        .filter(or_(Source.url == url, Source.name == name))
        .first()
    )
    values = {
        "name": name,
        "url": url,
        "country_code": country_code,
        "language": source_config.get("language", "mk"),
        "reliability_score": float(source_config.get("reliability_score", 0.5)),
        "source_type": source_config.get("source_type", "news"),
        "political_leaning": source_config.get("political_leaning", "unknown"),
        "ownership": source_config.get("ownership"),
        "rss_feeds": source_config.get("rss_feeds") or [],
        "is_active": bool(source_config.get("is_active", True)),
    }
    if not source:
        source = Source(**values)
        db.add(source)
        db.flush()
        return {
            "status": "created",
            "source_id": source.id,
            "name": source.name,
            "url": source.url,
            "changes": sorted(values.keys()),
        }

    changes = []
    for field, value in values.items():
        if getattr(source, field) != value:
            setattr(source, field, value)
            changes.append(field)
    if changes:
        db.flush()
    return {
        "status": "updated" if changes else "unchanged",
        "source_id": source.id,
        "name": source.name,
        "url": source.url,
        "changes": changes,
    }


def _operations_fix_queue(country_code: str, limit: int, db: Session, user: User) -> list[dict]:
    items: list[dict] = []

    def add_item(priority: str, area: str, title: str, detail: str, action: str, **extra) -> None:
        items.append({
            "priority": priority,
            "area": area,
            "title": title,
            "detail": detail,
            "suggested_action": action,
            **extra,
        })

    config_validation = _source_config_validation_report(country_code, db)
    for source in config_validation.get("sources", []):
        for issue in source.get("issues", []):
            add_item(
                "p0" if issue.get("severity") == "critical" else "p2",
                "source_config",
                f"{source.get('source_name') or 'Unnamed source'}: {issue.get('field')}",
                issue.get("message", ""),
                issue.get("suggested_fix", "Review source YAML config."),
                source_name=source.get("source_name"),
                source_url=source.get("source_url"),
                source_id=source.get("db_source_id"),
            )

    source_health = list_ingestion_source_health(country_code=country_code, db=db, _=user)
    for source in source_health.get("sources", []):
        status = source.get("status")
        if status in {"healthy", "caught_up", "rss_only", "disabled"}:
            continue
        if (
            source.get("source_type") == "social_media"
            and source.get("raw_count", 0) == 0
            and source.get("error_count", 0) == 0
        ):
            continue
        add_item(
            "p0" if status in {"failing", "no_links", "error"} else "p1",
            "source_health",
            f"{source.get('source_name')}: ingestion {str(status).replace('_', ' ')}",
            (
                f"{source.get('raw_count', 0)} raw, {source.get('new_count', 0)} new, "
                f"{source.get('failed_count', 0)} failed, {source.get('error_count', 0)} errors."
            ),
            "Open source drilldown, then run scraper preflight for this source.",
            source_name=source.get("source_name"),
            source_url=source.get("source_url"),
            source_stat_id=source.get("id"),
        )

    article_quality = audit_article_quality(country_code=country_code, limit=min(limit, 25), method="all", db=db, _=user)
    for issue in article_quality.get("issues", [])[:limit]:
        reasons = issue.get("reasons", [])
        add_item(
            "p1",
            "article_quality",
            f"{issue.get('source_name')}: {issue.get('title')}",
            f"Reasons: {', '.join(reasons) if reasons else 'quality issue'}.",
            "Review the article; approve if valid or exclude it from active intelligence.",
            article_id=issue.get("article_id"),
            source_name=issue.get("source_name"),
            url=issue.get("url"),
        )

    entity_quality = entity_quality_report(limit=500, db=db, _=user)
    for entity in entity_quality.get("examples", [])[:limit]:
        reasons = entity.get("reasons", [])
        add_item(
            "p2",
            "entity_quality",
            f"{entity.get('name')}",
            f"{entity.get('total_mentions', 0)} mentions; reasons: {', '.join(reasons) if reasons else 'needs review'}.",
            "Approve important real entities, merge duplicates, or hide noisy words.",
            entity_id=entity.get("id"),
            entity_type=entity.get("entity_type"),
        )

    priority_order = {"p0": 0, "p1": 1, "p2": 2}
    return sorted(
        items,
        key=lambda item: (
            priority_order.get(item.get("priority"), 9),
            item.get("area", ""),
            item.get("title", ""),
        ),
    )[:limit]


def _source_config_validation_row(source_config: dict, db_source: Optional[Source]) -> dict:
    scraper = source_config.get("scraper") or {}
    selectors = scraper.get("selectors") or {}
    rss_feeds = source_config.get("rss_feeds") or []
    rss_enabled = bool(source_config.get("rss_enabled", True)) and bool(rss_feeds)
    scraper_enabled = bool(scraper.get("enabled"))
    active = bool(source_config.get("is_active", True))
    issues = []

    def add_issue(severity: str, field: str, message: str, suggested_fix: str) -> None:
        issues.append({
            "severity": severity,
            "field": field,
            "message": message,
            "suggested_fix": suggested_fix,
        })

    name = source_config.get("name") or ""
    url = source_config.get("url") or ""
    if not name:
        add_issue("critical", "name", "Source is missing a name.", "Add a stable source name in YAML.")
    if not url:
        add_issue("critical", "url", "Source is missing a homepage URL.", "Add the public source homepage URL.")
    elif urlparse(url).scheme not in {"http", "https"}:
        add_issue("critical", "url", "Source URL is not HTTP/HTTPS.", "Use a full https:// URL.")
    if source_config.get("language") not in {"mk", "sq", "en", "sr", "bg", "el"}:
        add_issue("warning", "language", "Language is missing or uncommon.", "Set a language code such as mk, sq, or en.")
    if source_config.get("source_type") in {None, "", "unknown"}:
        add_issue("warning", "source_type", "Source type is not set.", "Classify as news, wire, government, blog, investigative, etc.")
    reliability = source_config.get("reliability_score")
    if reliability is None:
        add_issue("warning", "reliability_score", "Reliability score is missing.", "Set an initial 0.0-1.0 reliability score.")
    elif not isinstance(reliability, (int, float)) or not 0 <= reliability <= 1:
        add_issue("critical", "reliability_score", "Reliability score is outside 0.0-1.0.", "Use a decimal between 0 and 1.")
    if active and not rss_enabled and not scraper_enabled:
        add_issue("critical", "ingestion", "Neither RSS nor scraper is enabled.", "Enable RSS, scraper, or intentionally disable the source.")
    if active and source_config.get("rss_enabled", True) and not rss_feeds:
        add_issue("warning", "rss_feeds", "RSS is enabled but no feeds are configured.", "Add feed URLs or set rss_enabled: false.")
    for index, feed in enumerate(rss_feeds):
        feed_url = feed.get("url") if isinstance(feed, dict) else None
        if not feed_url:
            add_issue("critical", f"rss_feeds[{index}].url", "RSS feed is missing a URL.", "Add the feed URL.")
        elif urlparse(feed_url).scheme not in {"http", "https"}:
            add_issue("critical", f"rss_feeds[{index}].url", "RSS feed URL is not HTTP/HTTPS.", "Use a full https:// feed URL.")
    if scraper_enabled:
        if not scraper.get("listing_urls"):
            add_issue("critical", "scraper.listing_urls", "Scraper has no listing pages.", "Add at least one listing URL.")
        if not scraper.get("article_link_selectors"):
            add_issue("critical", "scraper.article_link_selectors", "Scraper has no article link selectors.", "Add selectors for article links.")
        if not scraper.get("include_url_patterns"):
            add_issue("warning", "scraper.include_url_patterns", "Scraper has no include URL patterns.", "Add source-specific patterns to reduce bad links.")
        if not selectors.get("title"):
            add_issue("critical", "scraper.selectors.title", "Title selector is missing.", "Add h1 or og:title selector.")
        if not selectors.get("body"):
            add_issue("critical", "scraper.selectors.body", "Body selector is missing.", "Add article/body content selector.")
        if not selectors.get("date"):
            add_issue("warning", "scraper.selectors.date", "Date selector is missing.", "Add time or article:published_time selector.")
        if not selectors.get("image"):
            add_issue("warning", "scraper.selectors.image", "Image selector is missing.", "Add og:image selector where available.")
        if not scraper.get("min_word_count"):
            add_issue("warning", "scraper.min_word_count", "Minimum word count is missing.", "Set min_word_count to avoid thin/non-article pages.")
    if not db_source:
        add_issue("warning", "database", "Source exists in YAML but is not present in the database.", "Run setup/seed or sync source config.")

    critical_count = len([issue for issue in issues if issue["severity"] == "critical"])
    warning_count = len([issue for issue in issues if issue["severity"] == "warning"])
    if not active:
        status = "disabled"
    elif critical_count:
        status = "critical"
    elif warning_count:
        status = "warning"
    else:
        status = "healthy"

    return {
        "source_name": name,
        "source_url": url,
        "db_source_id": db_source.id if db_source else None,
        "active": active,
        "rss_enabled": rss_enabled,
        "rss_feed_count": len(rss_feeds),
        "scraper_enabled": scraper_enabled,
        "listing_url_count": len(scraper.get("listing_urls") or []),
        "selector_count": len([value for value in selectors.values() if value]),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "status": status,
        "issues": issues,
    }


def _scraper_preflight_result(source_config: dict, max_articles: int = 3) -> dict:
    scraper_cfg = source_config.get("scraper") or {}
    row = {
        "source_name": source_config.get("name"),
        "source_url": source_config.get("url"),
        "scraper_enabled": bool(scraper_cfg.get("enabled")),
        "rss_enabled": bool(source_config.get("rss_enabled", True)) and bool(source_config.get("rss_feeds")),
        "discovered_urls": 0,
        "success_count": 0,
        "failed_count": 0,
        "average_word_count": 0,
        "minimum_average_word_count": int(scraper_cfg.get("preflight_min_average_words", 100)),
        "published_date_count": 0,
        "author_count": 0,
        "image_count": 0,
        "status": "disabled" if not scraper_cfg.get("enabled") else "unknown",
        "error_sample": None,
        "sample_urls": [],
        "failed_urls": [],
        "failure_details": [],
        "min_word_count": 0,
        "max_word_count": 0,
        "suggested_fix": "Enable scraper or rely on RSS for this source.",
    }
    if not scraper_cfg.get("enabled"):
        return row

    scraper = ArticleScraper(delay_seconds=0, max_articles_per_source=max_articles)
    try:
        urls = scraper.discover_article_urls(source_config)
        row["discovered_urls"] = len(urls)
        row["sample_urls"] = urls[:max_articles]
        word_counts = []
        for url in urls[:max_articles]:
            result = scraper.scrape_article(url, scraper_cfg)
            if result.success:
                row["success_count"] += 1
                word_counts.append(result.word_count)
                row["published_date_count"] += int(result.published_at is not None)
                row["author_count"] += int(bool(result.author))
                row["image_count"] += int(bool(result.image_url))
            else:
                row["failed_count"] += 1
                row["error_sample"] = row["error_sample"] or result.error
                row["failed_urls"].append(url)
                row["failure_details"].append({
                    "url": url,
                    "error": result.error,
                    "title": result.title,
                    "word_count": result.word_count,
                })
        if word_counts:
            row["average_word_count"] = round(sum(word_counts) / len(word_counts), 1)
            row["min_word_count"] = min(word_counts)
            row["max_word_count"] = max(word_counts)
        row["status"] = _scraper_preflight_status(row)
        row["suggested_fix"] = _scraper_preflight_fix(row)
        return row
    except Exception as exc:
        row["status"] = "error"
        row["error_sample"] = str(exc)
        row["suggested_fix"] = "Open the source manually and check if requests are blocked or selectors changed."
        return row
    finally:
        scraper.close()


def _scraper_preflight_status(row: dict) -> str:
    if row["discovered_urls"] == 0:
        return "no_links"
    if row["success_count"] == 0:
        return "failing"
    checked = row["success_count"] + row["failed_count"]
    failure_rate = row["failed_count"] / checked if checked else 0
    if row["failed_count"] > row["success_count"] or failure_rate >= 0.25:
        return "degraded"
    if row["published_date_count"] < row["success_count"]:
        return "degraded"
    if (
        row["average_word_count"]
        and row["average_word_count"] < row.get("minimum_average_word_count", 100)
    ):
        return "degraded"
    return "healthy"


def _scraper_preflight_fix(row: dict) -> str:
    if row["status"] == "no_links":
        return "Check listing URL, include URL patterns, and article link selectors."
    if row["status"] == "failing":
        return "Discovered links but extraction failed; check title/body/date selectors and blocking."
    if row["status"] == "degraded":
        if row.get("published_date_count", 0) < row.get("success_count", 0):
            return "Publication dates are missing; update the date selector before trusting scheduled ingestion."
        if (
            row.get("average_word_count", 0)
            and row["average_word_count"] < row.get("minimum_average_word_count", 100)
        ):
            return "Extraction works but content is thin; tighten URL filters or improve the body selector."
        return "Some articles extract and some fail; tighten URL filters or add fallback selectors."
    return "Scraper preflight looks usable."


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"pbkdf2_sha256$120000${salt}${digest}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_incident_or_404(
    db: Session,
    client_id: int,
    incident_id: int,
) -> ClientIncident:
    incident = (
        db.query(ClientIncident)
        .filter(
            ClientIncident.client_id == client_id,
            ClientIncident.id == incident_id,
        )
        .first()
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


def _plan_limits(plan: SubscriptionPlan) -> dict:
    matrix = {
        SubscriptionPlan.FREE: {
            "limits": {
                "watchlist_items": 3,
                "facebook_pages": 0,
                "incidents": 3,
                "history_days": 7,
                "chat_turns_per_conversation": 0,
            },
            "features": {
                "alerts": False,
                "response_assistant": False,
                "evidence_archive": False,
                "pdf_reports": False,
                "campaign_war_room": False,
                "intelligence_chat": False,
            },
        },
        SubscriptionPlan.BASIC: {
            "limits": {
                "watchlist_items": 10,
                "facebook_pages": 2,
                "incidents": 25,
                "history_days": 30,
                "chat_turns_per_conversation": 10,
            },
            "features": {
                "alerts": True,
                "response_assistant": False,
                "evidence_archive": True,
                "pdf_reports": False,
                "campaign_war_room": False,
                "intelligence_chat": True,
            },
        },
        SubscriptionPlan.PRO: {
            "limits": {
                "watchlist_items": 30,
                "facebook_pages": 10,
                "incidents": 100,
                "history_days": 90,
                "chat_turns_per_conversation": 50,
            },
            "features": {
                "alerts": True,
                "response_assistant": True,
                "evidence_archive": True,
                "pdf_reports": True,
                "campaign_war_room": False,
                "intelligence_chat": True,
            },
        },
        SubscriptionPlan.POLITICAL_DEFENSE: {
            "limits": {
                "watchlist_items": 75,
                "facebook_pages": 25,
                "incidents": 300,
                "history_days": 365,
                "chat_turns_per_conversation": 100,
            },
            "features": {
                "alerts": True,
                "response_assistant": True,
                "evidence_archive": True,
                "pdf_reports": True,
                "campaign_war_room": True,
                "intelligence_chat": True,
            },
        },
        SubscriptionPlan.CAMPAIGN: {
            "limits": {
                "watchlist_items": 200,
                "facebook_pages": 75,
                "incidents": 1000,
                "history_days": 730,
                "chat_turns_per_conversation": 200,
            },
            "features": {
                "alerts": True,
                "response_assistant": True,
                "evidence_archive": True,
                "pdf_reports": True,
                "campaign_war_room": True,
                "intelligence_chat": True,
            },
        },
        SubscriptionPlan.ENTERPRISE: {
            "limits": {
                "watchlist_items": -1,
                "facebook_pages": -1,
                "incidents": -1,
                "history_days": -1,
                "chat_turns_per_conversation": -1,
            },
            "features": {
                "alerts": True,
                "response_assistant": True,
                "evidence_archive": True,
                "pdf_reports": True,
                "campaign_war_room": True,
                "intelligence_chat": True,
            },
        },
    }
    return matrix.get(plan, matrix[SubscriptionPlan.BASIC])


def _plan_usage(db: Session, client_id: int) -> dict:
    return {
        "watchlist_items": (
            db.query(ClientWatchlistItem)
            .filter(ClientWatchlistItem.client_id == client_id)
            .count()
        ),
        "facebook_pages": (
            db.query(ClientWatchlistItem)
            .filter(
                ClientWatchlistItem.client_id == client_id,
                ClientWatchlistItem.item_type == WatchlistItemType.FACEBOOK_PAGE,
            )
            .count()
        ),
        "incidents": (
            db.query(ClientIncident)
            .filter(ClientIncident.client_id == client_id)
            .count()
        ),
        "open_incidents": (
            db.query(ClientIncident)
            .filter(
                ClientIncident.client_id == client_id,
                ClientIncident.status != IncidentStatus.CLOSED,
            )
            .count()
        ),
    }


def _enforce_plan_limit(db: Session, client: Client, limit_name: str):
    limits = _plan_limits(client.plan)["limits"]
    limit = limits.get(limit_name)
    if limit is None or limit == -1:
        return
    usage = _plan_usage(db, client.id).get(limit_name, 0)
    if usage >= limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Plan limit reached for {limit_name}: "
                f"{usage}/{limit}. Upgrade the client plan to continue."
            ),
        )


def _enforce_plan_feature(client: Client, feature_name: str):
    features = _plan_limits(client.plan)["features"]
    if features.get(feature_name):
        return
    raise HTTPException(
        status_code=402,
        detail=(
            f"Feature '{feature_name}' is not included in the "
            f"{client.plan.value} plan."
        ),
    )


def _seed_incident_evidence_from_articles(
    db: Session,
    incident: ClientIncident,
    article_ids: list[int],
):
    """Create evidence rows from source articles saved with a case."""
    if not article_ids:
        return
    articles = (
        db.query(Article)
        .filter(Article.id.in_(article_ids))
        .all()
    )
    for article in articles:
        db.add(ClientIncidentEvidence(
            incident_id=incident.id,
            article_id=article.id,
            url=article.url,
            title=article.title,
            source_name=article.source.name if article.source else None,
            evidence_type=article.ingestion_method or "article",
            published_at=article.published_at,
            content_hash=article.content_hash,
            notes="Seeded from response pack source trail.",
        ))


def _invalidate_client_dashboard_cache(db: Session, client_id: int) -> None:
    db.query(ClientDashboardCache).filter(
        ClientDashboardCache.client_id == client_id
    ).delete(synchronize_session=False)


def _store_client_dashboard_cache(
    db: Session,
    client_id: int,
    days: int,
    response: ClientDashboardResponse,
    generated_at: datetime.datetime,
) -> None:
    expires_at = generated_at + datetime.timedelta(
        seconds=max(30, settings.client_dashboard_cache_seconds)
    )
    payload = jsonable_encoder(response)
    cached = (
        db.query(ClientDashboardCache)
        .filter(
            ClientDashboardCache.client_id == client_id,
            ClientDashboardCache.period_days == days,
        )
        .first()
    )
    if cached:
        cached.payload = payload
        cached.generated_at = generated_at
        cached.expires_at = expires_at
    else:
        db.add(ClientDashboardCache(
            client_id=client_id,
            period_days=days,
            payload=payload,
            generated_at=generated_at,
            expires_at=expires_at,
        ))
    db.commit()


def _matching_watchlist_articles(
    db: Session,
    client: Client,
    watchlist: list[ClientWatchlistItem],
    since: datetime.datetime,
    limit: int = 20,
) -> list[Article]:
    """Find recent articles/posts matching a client's tracked items."""
    if not watchlist:
        return []

    date_column = func.coalesce(
        Article.published_at, Article.fetched_at, Article.ingested_at
    )
    recent_condition = (
        date_column >= since
        if db.get_bind().dialect.name == "postgresql"
        else _recent_article_filter(since)
    )
    query = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(Source.country_code == client.country_code)
        .filter(_active_article_filter())
        .filter(recent_condition)
    )

    conditions = []
    entity_ids = [
        item.entity_id for item in watchlist
        if item.entity_id and item.item_type in (
            WatchlistItemType.ENTITY,
            WatchlistItemType.OPPONENT,
        )
    ]
    source_ids = [
        item.source_id for item in watchlist
        if item.source_id and item.item_type == WatchlistItemType.SOURCE
    ]
    keywords = [
        item.value.strip() for item in watchlist
        if item.value and item.item_type in (
            WatchlistItemType.KEYWORD,
            WatchlistItemType.TOPIC,
            WatchlistItemType.FACEBOOK_PAGE,
        )
    ]

    if entity_ids:
        mentioned_articles = select(EntityMention.article_id).where(
            EntityMention.entity_id.in_(entity_ids)
        )
        conditions.append(Article.id.in_(mentioned_articles))
    if source_ids:
        conditions.append(Article.source_id.in_(source_ids))
    for keyword in keywords:
        condition = article_text_match(db, [keyword])
        if condition is not None:
            conditions.append(condition)

    if not conditions:
        return []

    if len(conditions) == 1:
        query = query.filter(conditions[0])
    else:
        # PostgreSQL can choose a very poor plan for OR across entity, source,
        # and full-text predicates. Resolve each indexed predicate separately.
        id_queries = [
            select(Article.id)
            .join(Source, Source.id == Article.source_id)
            .filter(Source.country_code == client.country_code)
            .filter(_active_article_filter())
            .filter(recent_condition)
            .filter(condition)
            for condition in conditions
        ]
        matched_ids = union_all(*id_queries).subquery()
        query = query.filter(Article.id.in_(select(matched_ids.c.id)))

    articles = (
        query
        .order_by(date_column.desc())
        .limit(limit * 2)
        .all()
    )
    return [article for article in articles if _is_client_usable_article(article)][:limit]


def _dedupe_watchlist_items(
    items: list[ClientWatchlistItem],
) -> list[ClientWatchlistItem]:
    """Collapse repeated setup rows without mutating the client's stored configuration."""
    unique = []
    seen = set()
    for item in items:
        key = (
            item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type),
            (item.label or item.value or "").strip().casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _party_briefing_articles(
    db: Session,
    client: Client,
    topic: str,
    requirements: Optional[str],
    watchlist: list[ClientWatchlistItem],
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    limit: int,
) -> list[tuple[Article, Optional[float], int]]:
    """Find coverage for a party briefing topic and optional watchlist context."""
    date_column = func.coalesce(
        Article.published_at, Article.fetched_at, Article.ingested_at
    )
    query = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(Source.country_code == client.country_code)
        .filter(date_column >= date_from)
        .filter(date_column <= date_to)
    )

    terms = _briefing_terms(topic, requirements)
    conditions = []
    text_condition = article_text_match(db, terms)
    if text_condition is not None:
        conditions.append(text_condition)

    entity_ids = [
        item.entity_id for item in watchlist
        if item.entity_id and item.priority <= 2
    ]
    if entity_ids:
        mentioned_articles = select(EntityMention.article_id).where(
            EntityMention.entity_id.in_(entity_ids)
        )
        conditions.append(Article.id.in_(mentioned_articles))

    if not conditions:
        return []

    articles = (
        query.filter(or_(*conditions))
        .order_by(date_column.desc())
        .limit(limit * 2)
        .all()
    )
    articles = [article for article in articles if _is_client_usable_article(article)][:limit]
    return [(article, _article_average_sentiment(article), 1) for article in articles]


def _briefing_terms(topic: str, requirements: Optional[str]) -> list[str]:
    raw = f"{topic} {requirements or ''}".replace(",", " ").replace(";", " ")
    terms = []
    for chunk in raw.split():
        value = chunk.strip().lower()
        if len(value) >= 4 and value not in {
            "what", "with", "from", "that", "this", "they", "want",
            "about", "please", "press", "conference",
        }:
            terms.append(value)
    if topic.strip():
        terms.insert(0, topic.strip())
    seen = set()
    unique = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return unique[:12]


def _article_average_sentiment(article: Article) -> Optional[float]:
    scores = [
        mention.sentiment_score for mention in article.entity_mentions
        if mention.sentiment_score is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _build_party_coverage_summary(
    topic: str,
    objective: Optional[str],
    articles: list[Article],
    source_count: int,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
) -> str:
    if not articles:
        return (
            f"No stored coverage matched '{topic}' between "
            f"{date_from.strftime('%Y-%m-%d')} and {date_to.strftime('%Y-%m-%d')}. "
            "Use broader keywords or ingest more sources before relying on this briefing."
        )
    latest = articles[0].published_at or articles[0].fetched_at or articles[0].ingested_at
    objective_text = f" The stated objective is: {objective}." if objective else ""
    return (
        f"Found {len(articles)} relevant items across {source_count} sources for '{topic}'. "
        f"The latest matched item is dated {latest.strftime('%Y-%m-%d') if latest else 'unknown date'}. "
        "Use the strongest sourced examples below, avoid overclaiming beyond the article trail, "
        "and separate political argument from factual/legal assertions."
        f"{objective_text}"
    )


def _build_party_talking_points(
    topic: str,
    objective: Optional[str],
    requirements: Optional[str],
    articles: list[Article],
    attack_categories: dict,
) -> list[str]:
    if not articles:
        return [
            f"Open by stating the party position on {topic} in one clear sentence.",
            "Acknowledge that the available database has limited stored coverage for this exact query.",
            "Use verified party documents or official records before making specific factual claims.",
        ]

    top_sources = []
    for article in articles[:5]:
        source_name = article.source.name if article.source else "Unknown"
        if source_name not in top_sources:
            top_sources.append(source_name)

    points = [
        f"Start with the core frame: {objective or f'the party position on {topic}'}.".strip(),
        f"Ground the statement in the coverage trail: {len(articles)} matched items from {len(top_sources)}+ visible source names.",
        f"Mention the most recent development first: {articles[0].title}",
        "Use dates and source attribution when making factual claims.",
    ]
    if requirements:
        points.append(f"Address the requested angle directly: {requirements}")
    if attack_categories:
        categories = ", ".join(category.replace("_", " ") for category in attack_categories)
        points.append(f"Prepare a calm rebuttal for likely attack themes: {categories}.")
    points.append("Close with the next concrete action the party wants institutions or the public to take.")
    return points[:7]


def _source_evidence_brief(articles: list[Article], limit: int = 6) -> list[dict]:
    """Create short, source-backed facts without adding claims beyond stored articles."""
    evidence = []
    for article in articles[:limit]:
        article_date = article.published_at or article.fetched_at or article.ingested_at
        source = article.source
        evidence.append({
            "article_id": article.id,
            "claim": article.title,
            "source_name": source.name if source else "Unknown",
            "source_type": source.source_type if source else "unknown",
            "reliability_score": source.reliability_score if source else None,
            "published_at": article_date.isoformat() if article_date else None,
            "url": article.url,
            "use_in_briefing": (
                "Use as a sourced article title or reported development. "
                "Do not expand it into a legal/factual conclusion without the article text and official documents."
            ),
        })
    return evidence


def _citation_pack(evidence_brief: list[dict]) -> list[dict]:
    """Turn evidence items into explicit citation-ready references."""
    citations = []
    for index, item in enumerate(evidence_brief, start=1):
        label = f"S{index}"
        citations.append({
            "label": label,
            "inline": f"[{label}] {item.get('source_name', 'Unknown')} - {item.get('claim', 'Source item')}",
            "article_id": item.get("article_id"),
            "claim": item.get("claim"),
            "source_name": item.get("source_name"),
            "source_type": item.get("source_type"),
            "reliability_score": item.get("reliability_score"),
            "published_at": item.get("published_at"),
            "url": item.get("url"),
            "safe_use": (
                f"Use [{label}] only for what this source reports. "
                "Do not turn it into a proven fact, legal conclusion, or accusation without independent verification."
            ),
        })
    return citations


def _party_evidence_buckets(articles: list[Article]) -> dict:
    """Separate stronger multi-source facts from single-source claims."""
    by_title: dict[str, list[Article]] = {}
    for article in articles:
        key = " ".join((article.title or "").lower().split()[:12])
        by_title.setdefault(key, []).append(article)

    verified = []
    single_source = []
    for article in articles:
        source_count = len({
            candidate.source_id
            for candidate in by_title.get(" ".join((article.title or "").lower().split()[:12]), [])
        })
        item = _source_evidence_brief([article], limit=1)[0]
        item["source_count"] = max(1, source_count)
        if source_count >= 2:
            item["validation_status"] = "multi_source"
            verified.append(item)
        else:
            item["validation_status"] = "single_source"
            single_source.append(item)
    if not verified and len({article.source_id for article in articles}) >= 3:
        for item in _source_evidence_brief(articles[:3], limit=3):
            item["validation_status"] = "source_diverse"
            item["source_count"] = len({article.source_id for article in articles})
            verified.append(item)
    return {
        "verified_facts": verified[:6],
        "single_source_claims": single_source[:8],
    }


def _party_briefing_strategy(
    topic: str,
    objective: Optional[str],
    audience: Optional[str],
    tone: Optional[str],
    evidence_brief: list[dict],
    citation_pack: list[dict],
    claim_support_matrix: list[dict],
    claims_to_verify: list[str],
    do_not_say: list[str],
    risk_warnings: list[str],
    legal_context: list[dict],
    grounding_contract: dict,
    attack_categories: dict,
    source_count: int,
    article_count: int,
) -> dict:
    """Build a press-conference strategy without inventing beyond stored evidence."""
    legal_review_required = bool(
        grounding_contract.get("legal_review_required")
        or any(item.get("requires_lawyer_review") for item in legal_context)
    )
    unsupported = [
        item.get("claim")
        for item in claim_support_matrix
        if item.get("status") == "unsupported_by_current_data" and item.get("claim")
    ][:5]
    single_source = [
        item.get("claim")
        for item in claim_support_matrix
        if item.get("status") == "single_source" and item.get("claim")
    ][:5]
    supported = [
        item.get("claim")
        for item in claim_support_matrix
        if item.get("status") == "source_supported" and item.get("claim")
    ][:5]
    top_attack = None
    if attack_categories:
        top_attack = sorted(attack_categories.items(), key=lambda row: row[1], reverse=True)[0][0].replace("_", " ")

    if grounding_contract.get("decision") == "hold" or unsupported or legal_review_required:
        public_posture = "Internal prep until review clears blockers"
        publication_gate = "Do not use final public language until unsupported and legal-review items are cleared."
    elif source_count >= 2 and citation_pack:
        public_posture = "Cited press-conference frame"
        publication_gate = "Usable for press prep if every factual line keeps a citation or source reference attached."
    else:
        public_posture = "Holding frame only"
        publication_gate = "Use a short position statement and avoid detailed claims until more source evidence is available."

    first_source = citation_pack[0] if citation_pack else {}
    primary_line = (
        f"For {audience or 'the public'}, keep the main line on {topic}: "
        f"{objective or 'we will speak with facts, dates, and source-backed claims'}."
    )
    if first_source:
        primary_line += f" Start from [{first_source.get('label')}] {first_source.get('source_name')} and do not go beyond what that source reports."

    opening_frame = (
        f"The stored database found {article_count} relevant items across {source_count} sources for {topic}."
        + (f" The main attack/risk theme to prepare for is {top_attack}." if top_attack else "")
    )

    evidence_to_use = [{
        "label": item.get("label"),
        "source_name": item.get("source_name"),
        "claim": item.get("claim") or item.get("inline"),
        "url": item.get("url"),
        "safe_use": item.get("safe_use"),
    } for item in citation_pack[:5]]

    return {
        "public_posture": public_posture,
        "decision": grounding_contract.get("decision") or "caution",
        "primary_line": primary_line,
        "opening_frame": opening_frame,
        "message_angle": (
            f"Address {top_attack} calmly with citations and no counter-accusations."
            if top_attack else
            "Lead with the party position, then source-backed facts, then what should happen next."
        ),
        "publication_gate": publication_gate,
        "tone_guidance": tone or "statesmanlike",
        "evidence_to_use": evidence_to_use,
        "supported_claims": supported,
        "claims_to_avoid": [
            *unsupported,
            *single_source,
            *claims_to_verify[:4],
            *do_not_say[:4],
        ][:10],
        "questions_to_answer_before_publish": [
            "Which exact source or document supports each factual sentence?",
            "Which claims are single-source and need softer wording?",
            "Does any line imply criminality, corruption, illegality, or constitutional/legal conclusions?",
            "What is the one action the party wants the public or institutions to take?",
        ],
        "operator_notes": [
            "Keep the press statement shorter than the internal briefing.",
            "Use citations for factual claims and avoid legal conclusions without counsel.",
            *risk_warnings[:3],
        ][:6],
    }


def _party_draft_outputs(
    topic: str,
    objective: Optional[str],
    audience: Optional[str],
    tone: Optional[str],
    evidence_brief: list[dict],
    claims_to_verify: list[str],
    legal_context: list[dict],
    briefing_strategy: Optional[dict] = None,
) -> dict:
    """Build structured communications drafts from source-backed inputs only."""
    briefing_strategy = briefing_strategy or {}
    audience_text = audience or "the public"
    tone_text = tone or "statesmanlike"
    strongest = evidence_brief[0]["claim"] if evidence_brief else "the currently available sourced coverage"
    source_name = evidence_brief[0]["source_name"] if evidence_brief else "stored sources"
    legal_note = (
        f"Legal reference to verify: {legal_context[0].get('area')}."
        if legal_context else
        "Legal context is not confirmed in this briefing; verify with official documents or counsel."
    )
    press_statement = (
        f"{briefing_strategy.get('primary_line') or f'Our position on {topic} is guided by the public interest and by verified information.'} "
        f"The current source trail includes {strongest} ({source_name}). "
        f"{briefing_strategy.get('publication_gate') or 'We will rely on facts, dates, and documents, and we will correct any unsupported claims.'}"
    )
    social_response = (
        f"On {topic}: we will respond with facts, not speculation. "
        f"{briefing_strategy.get('opening_frame') or 'Our team is reviewing sourced coverage and documents.'} {legal_note}"
    )
    rebuttal = (
        f"If attacked on {topic}, answer in a {tone_text} tone: {briefing_strategy.get('message_angle') or 'acknowledge the claim, cite the source trail'}, "
        "separate reported allegations from proven facts, and ask opponents to provide evidence for factual accusations."
    )
    qa_prep = [
        {
            "question": f"What is your strongest evidence on {topic}?",
            "answer": f"Use the source trail first: {strongest} ({source_name}). Do not go beyond what the article or document says.",
        },
        {
            "question": "Is this legally confirmed?",
            "answer": legal_note,
        },
        {
            "question": "What still needs verification?",
            "answer": claims_to_verify[0] if claims_to_verify else "Verify dates, names, numbers, and official documents before speaking.",
        },
    ]
    return {
        "press_statement": press_statement,
        "short_social_response": social_response,
        "attack_rebuttal": rebuttal,
        "qa_prep": qa_prep,
    }


def _claim_support_matrix(
    topic: str,
    requirements: Optional[str],
    articles: list[Article],
    legal_context: list[dict],
    extra_claims: Optional[list[str]] = None,
) -> list[dict]:
    """Classify requested claims against stored evidence without inferring truth."""
    claims = _candidate_claims(topic, requirements, extra_claims or [])
    official_legal_refs = [
        item for item in legal_context
        if item.get("status") in {"official", "lawyer_verified"}
    ]
    rows = []
    for claim in claims:
        terms = _briefing_terms(claim, None)
        support = []
        for article in articles:
            text_value = f"{article.title} {article.content or ''} {article.search_text or ''}".lower()
            if any(term.lower() in text_value for term in terms):
                support.append(article)

        source_count = len({article.source_id for article in support})
        legal_trigger = _claim_has_legal_trigger(claim)
        if not support:
            status = "unsupported_by_current_data"
            safe_use = "Do not present this as fact from the database; say more evidence is needed or broaden the search."
        elif legal_trigger and not official_legal_refs:
            status = "legal_review_required"
            safe_use = "Use only as a question or legal-review note until official legal text or counsel confirms it."
        elif source_count >= 2:
            status = "source_supported"
            safe_use = "May be used as a sourced coverage point with article names, dates, and URLs; still verify originals."
        else:
            status = "single_source"
            safe_use = "Use cautiously as one-source reporting; do not make it the central factual claim without another source."

        rows.append({
            "claim": claim,
            "status": status,
            "supporting_article_count": len(support),
            "supporting_source_count": source_count,
            "supporting_article_ids": [article.id for article in support[:6]],
            "legal_review_required": legal_trigger,
            "safe_use": safe_use,
            "evidence": _source_evidence_brief(support, limit=3),
        })
    return rows


def _candidate_claims(
    topic: str,
    requirements: Optional[str],
    extra_claims: list[str],
) -> list[str]:
    claims = [topic.strip()] if topic and topic.strip() else []
    if requirements:
        parts = re.split(r"[.;\n]+", requirements)
        claims.extend(part.strip(" -:") for part in parts if len(part.strip()) >= 8)
    claims.extend(item.strip() for item in extra_claims if item and item.strip())
    seen = set()
    unique = []
    for claim in claims:
        key = " ".join(claim.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique[:10]


def _claim_has_legal_trigger(claim: str) -> bool:
    text_value = claim.lower()
    legal_terms = [
        "law", "legal", "constitution", "constitutional", "criminal", "crime",
        "corruption", "investigation", "court", "prosecutor", "illegal",
        "закон", "устав", "уставен", "кривич", "криминал", "корупц",
        "истрага", "суд", "обвинител", "незакон",
    ]
    return any(term in text_value for term in legal_terms)


def _claim_matrix_verification_notes(matrix: list[dict]) -> list[str]:
    notes = []
    for row in matrix:
        status = row.get("status")
        claim = row.get("claim")
        if status == "unsupported_by_current_data":
            notes.append(f"Unsupported by current stored data: {claim}")
        elif status == "single_source":
            notes.append(f"Find a second independent source before relying on: {claim}")
        elif status == "legal_review_required":
            notes.append(f"Legal review required before using this claim externally: {claim}")
    return notes


def _claim_matrix_do_not_say(matrix: list[dict]) -> list[str]:
    warnings = []
    for row in matrix:
        status = row.get("status")
        claim = row.get("claim")
        if status == "unsupported_by_current_data":
            warnings.append(f"Do not state as fact because the current database does not support it: {claim}")
        elif status == "legal_review_required":
            warnings.append(f"Do not claim Macedonian law supports this before legal verification: {claim}")
    return warnings


def _party_do_not_say_unless_verified(
    articles: list[Article],
    legal_context: list[dict],
    requirements: Optional[str],
) -> list[str]:
    warnings = [
        "Do not say someone committed a crime unless there is an official proceeding, decision, or verified legal document.",
        "Do not present article headlines as independent proof; say what the source reported and cite the URL.",
        "Do not use exact numbers, dates, or names without checking the original source.",
    ]
    if len({article.source_id for article in articles}) <= 1 and articles:
        warnings.append("Do not frame this as broadly confirmed; current coverage is single-source.")
    if requirements:
        warnings.append(f"Do not claim the requested angle is proven until documents support it: {requirements}")
    if not legal_context:
        warnings.append("Do not cite Macedonian law as supporting the position until legal references are verified.")
    return warnings


def _build_client_chat_response(
    db: Session,
    client: Client,
    watchlist: list[ClientWatchlistItem],
    question: str,
    mode: str,
    since: datetime.datetime,
    allow_wider_context: bool,
    requested_wider_context: bool,
    conversation_history: list[dict],
    requested_days: int,
    effective_days: int,
) -> dict:
    """Answer client questions from permitted stored data with source citations."""
    clean_question = " ".join(question.strip().split())
    detected_mode = _client_chat_mode(clean_question, mode)
    retrieval_question = _chat_retrieval_query(clean_question, conversation_history)
    base_articles = _matching_watchlist_articles(db, client, watchlist, since, limit=120)
    scored_articles = _score_chat_articles(retrieval_question, base_articles)
    source_articles = scored_articles[:12] if scored_articles else base_articles[:12]

    if allow_wider_context:
        wider_articles = _search_articles_for_question(db, client.country_code, retrieval_question, since, limit=60)
        by_id = {article.id: article for article in source_articles}
        for article in wider_articles:
            by_id.setdefault(article.id, article)
        source_articles = sorted(
            by_id.values(),
            key=lambda article: article.published_at or article.fetched_at or article.ingested_at or datetime.datetime.min,
            reverse=True,
        )[:16]

    risk_items = _build_watchlist_risk_items(db, watchlist, since)
    source_counts = _article_source_counts(source_articles)
    matched_entities = _top_entities_for_articles(db, source_articles)
    citations = _citation_pack(_source_evidence_brief(source_articles, limit=8))
    legal_context = []
    if detected_mode == "response_help" or _claim_has_legal_trigger(clean_question):
        legal_context = _macedonian_legal_context(
            db,
            client.country_code,
            clean_question,
            None,
        )
        legal_context = [
            {**item, "label": f"L{index}"}
            for index, item in enumerate(legal_context[:5], start=1)
        ]
    summary_lines = _chat_article_summaries(source_articles[:5], citations)
    restrictions = [
        "Client answers are limited to this client's configured watchlist, own persona, and permitted sources.",
        "Original URLs should be opened before public use.",
    ]
    if requested_wider_context and not allow_wider_context:
        restrictions.append("Wider cross-client/platform context was requested but not allowed for this account.")
    if allow_wider_context:
        restrictions.append("Admin/analyst wider context is enabled for this answer.")
    if effective_days < requested_days:
        restrictions.append(
            f"The requested {requested_days}-day window was limited to {effective_days} days by this client's plan."
        )

    answer = _client_chat_answer(
        client=client,
        question=clean_question,
        mode=detected_mode,
        articles=source_articles,
        risk_items=risk_items,
        source_counts=source_counts,
        matched_entities=matched_entities,
        citations=citations,
        legal_context=legal_context,
    )
    claims = _client_chat_claims(citations, legal_context)
    suggested_actions = _client_chat_actions(
        mode=detected_mode,
        articles=source_articles,
        risk_items=risk_items,
        source_counts=source_counts,
    )
    confidence = {
        "level": "high" if len(source_counts) >= 3 and len(source_articles) >= 6 else "medium" if source_articles else "low",
        "article_count": len(source_articles),
        "source_count": len(source_counts),
        "risk_item_count": len(risk_items),
        "history_messages_used": len(conversation_history),
        "effective_days": effective_days,
        "reason": "Grounded in stored articles matching the client scope and question; each surfaced report has a citation label.",
    }
    return {
        "mode": detected_mode,
        "answer": answer,
        "summary": "\n".join(summary_lines) if summary_lines else "No stored articles matched this question in the permitted scope.",
        "restrictions": restrictions,
        "suggested_actions": suggested_actions,
        "citations": citations,
        "claims": claims,
        "legal_context": legal_context,
        "source_articles": source_articles,
        "matched_entities": matched_entities,
        "confidence": confidence,
    }


def _enhance_client_chat_with_ai(
    client: Client,
    question: str,
    response_payload: dict,
    conversation_history: list[dict],
) -> dict:
    """Improve wording with AI only when every factual sentence remains evidence-bound."""
    ai = GroundedAI()
    evidence = []
    for citation in response_payload.get("citations", []):
        evidence.append({
            "label": citation.get("label"),
            "kind": "news_report",
            "source_name": citation.get("source_name"),
            "title": citation.get("title"),
            "claim": citation.get("claim"),
            "published_at": citation.get("published_at"),
            "url": citation.get("url"),
            "reliability_score": citation.get("reliability_score"),
        })
    for legal in response_payload.get("legal_context", []):
        evidence.append({
            "label": legal.get("label"),
            "kind": "legal_research_reference",
            "title": legal.get("title"),
            "guidance": legal.get("guidance"),
            "legal_basis_status": legal.get("legal_basis_status"),
            "requires_lawyer_review": legal.get("requires_lawyer_review", True),
            "source_url": legal.get("source_url"),
        })

    generation = ai.generate_json(
        task=f"Answer this client question: {question}",
        instructions=(
            f"The client is {client.name} ({client.client_type.value}). "
            f"The detected workflow is {response_payload.get('mode')}. "
            "Write a direct, plain-language answer. Distinguish what a source reported "
            "from what is independently established. Use recommendations only in "
            "suggested_actions. Preserve any uncertainty."
        ),
        evidence=evidence,
        history=conversation_history,
    )
    updated = dict(response_payload)
    updated["generation"] = generation.metadata()
    if not generation.accepted:
        return updated

    generated = generation.payload
    updated["answer"] = generated["answer"]
    updated["summary"] = generated["summary"]
    updated["suggested_actions"] = generated["suggested_actions"]
    updated["claims"] = [
        {
            **claim,
            "status": "ai_generated_evidence_bound",
        }
        for claim in generated["claims"]
    ]
    updated["confidence"] = {
        **updated.get("confidence", {}),
        "generation": "production_ai",
        "grounding_validated": True,
    }
    return updated


def _grounded_work_product_generation(
    *,
    task: str,
    instructions: str,
    citation_pack: list[dict],
    legal_context: list[dict],
):
    """Generate optional work-product wording from the same labeled evidence pack."""
    evidence = [
        {
            "label": item.get("label"),
            "kind": "news_report",
            "source_name": item.get("source_name"),
            "title": item.get("title"),
            "claim": item.get("claim"),
            "published_at": item.get("published_at"),
            "url": item.get("url"),
            "reliability_score": item.get("reliability_score"),
        }
        for item in citation_pack
    ]
    evidence.extend({
        "label": item.get("label") or f"L{index}",
        "kind": "legal_research_reference",
        "title": item.get("title"),
        "guidance": item.get("guidance"),
        "legal_basis_status": item.get("legal_basis_status"),
        "requires_lawyer_review": item.get("requires_lawyer_review", True),
        "source_url": item.get("source_url"),
    } for index, item in enumerate(legal_context, start=1))
    return GroundedAI().generate_json(
        task=task,
        instructions=instructions,
        evidence=evidence,
    )


def _chat_retrieval_query(question: str, history: list[dict]) -> str:
    """Resolve short follow-ups with recent user turns without widening permissions."""
    terms = _chat_question_terms(question)
    follow_up_markers = {
        "it", "that", "this", "they", "them", "there", "those",
        "тоа", "ова", "тие", "нив", "таму", "истото",
    }
    lowered = set(question.lower().split())
    if len(terms) > 5 and not lowered.intersection(follow_up_markers):
        return question
    previous_questions = [
        str(item.get("content", "")).strip()
        for item in history
        if item.get("role") == "user" and str(item.get("content", "")).strip()
    ][-2:]
    return " ".join([*previous_questions, question]).strip()


def _client_chat_claims(citations: list[dict], legal_context: list[dict]) -> list[dict]:
    """Expose exactly what the answer may safely attribute to each reference."""
    claims = [
        {
            "text": f"{item.get('source_name', 'Unknown')} reported: {item.get('claim', 'Untitled item')}",
            "citation_labels": [item.get("label")],
            "status": "source_report",
            "confidence": item.get("reliability_score"),
        }
        for item in citations[:5]
    ]
    for item in legal_context[:3]:
        claims.append({
            "text": item.get("guidance") or item.get("use_for") or item.get("area"),
            "citation_labels": [item.get("label")],
            "status": item.get("legal_basis_status", "legal_review_required"),
            "confidence": item.get("confidence_score"),
            "requires_lawyer_review": item.get("requires_lawyer_review", True),
        })
    return claims


def _client_chat_mode(question: str, requested_mode: str) -> str:
    if requested_mode and requested_mode != "auto":
        return requested_mode
    text_value = question.lower()
    attack_terms = ["attack", "attacked", "critic", "scandal", "accus", "напад", "крити", "обвин", "скандал"]
    source_terms = ["source", "portal", "media", "who mentioned", "where", "извор", "портал", "медиум", "каде"]
    response_terms = ["respond", "reply", "answer", "statement", "одговор", "реакц", "изјава"]
    latest_terms = ["latest", "new", "today", "recent", "послед", "нов", "денес", "најнов"]
    if any(term in text_value for term in response_terms):
        return "response_help"
    if any(term in text_value for term in attack_terms):
        return "attacks"
    if any(term in text_value for term in source_terms):
        return "sources"
    if any(term in text_value for term in latest_terms):
        return "latest"
    return "research"


def _chat_question_terms(question: str) -> list[str]:
    stopwords = {
        "what", "who", "where", "when", "why", "how", "latest", "about", "please",
        "show", "tell", "me", "the", "and", "for", "with", "that", "this",
        "што", "кој", "каде", "кога", "зошто", "како", "последно", "за", "со",
        "на", "во", "и", "или", "ми", "кажи", "покажи",
    }
    words = re.findall(r"[\wА-Яа-яЃѓЌќЅѕЉљЊњЏџ]+", question.lower(), flags=re.UNICODE)
    unique = []
    seen = set()
    for word in words:
        if len(word) < 3 or word in stopwords or word in seen:
            continue
        seen.add(word)
        unique.append(word)
    return unique[:12]


def _score_chat_articles(question: str, articles: list[Article]) -> list[Article]:
    terms = _chat_question_terms(question)
    if not terms:
        return articles
    scored: list[tuple[int, Article]] = []
    for article in articles:
        text_value = " ".join([
            article.title or "",
            article.content or "",
            article.search_text or "",
            article.source.name if article.source else "",
            article.platform_account_name or "",
        ]).lower()
        score = 0
        for term in terms:
            variants = search_variants(term)
            if any(variant.lower() in text_value for variant in variants):
                score += 3 if term in (article.title or "").lower() else 1
        if score:
            scored.append((score, article))
    if not scored:
        return articles
    return [
        article for _score, article in sorted(
            scored,
            key=lambda row: (
                row[0],
                row[1].published_at or row[1].fetched_at or row[1].ingested_at or datetime.datetime.min,
            ),
            reverse=True,
        )
    ]


def _search_articles_for_question(
    db: Session,
    country_code: str,
    question: str,
    since: datetime.datetime,
    limit: int,
) -> list[Article]:
    terms = _chat_question_terms(question)
    if not terms:
        return []
    date_column = func.coalesce(Article.published_at, Article.fetched_at, Article.ingested_at)
    condition = article_text_match(db, terms[:6])
    if condition is None:
        return []
    rows = (
        db.query(Article)
        .join(Source, Source.id == Article.source_id)
        .filter(Source.country_code == country_code)
        .filter(_active_article_filter())
        .filter(date_column >= since)
        .filter(condition)
        .order_by(date_column.desc())
        .limit(limit * 2)
        .all()
    )
    return [article for article in rows if _is_client_usable_article(article)][:limit]


def _article_source_counts(articles: list[Article]) -> list[dict]:
    counts: dict[str, dict] = {}
    for article in articles:
        source_name = article.source.name if article.source else article.platform_account_name or "Unknown"
        current = counts.setdefault(source_name, {
            "source_name": source_name,
            "article_count": 0,
            "latest_at": None,
            "reliability_score": article.source.reliability_score if article.source else None,
        })
        current["article_count"] += 1
        article_date = article.published_at or article.fetched_at or article.ingested_at
        if article_date and (current["latest_at"] is None or article_date > current["latest_at"]):
            current["latest_at"] = article_date
    rows = []
    for item in counts.values():
        rows.append({
            **item,
            "latest_at": item["latest_at"].isoformat() if item["latest_at"] else None,
        })
    return sorted(rows, key=lambda row: (-row["article_count"], row["source_name"]))[:8]


def _top_entities_for_articles(db: Session, articles: list[Article]) -> list[dict]:
    article_ids = [article.id for article in articles]
    if not article_ids:
        return []
    rows = (
        db.query(
            Entity.id,
            Entity.name,
            Entity.entity_type,
            func.sum(EntityMention.mention_count).label("mentions"),
            func.count(func.distinct(EntityMention.article_id)).label("articles"),
        )
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .filter(EntityMention.article_id.in_(article_ids))
        .filter(client_publishable_entity_filter())
        .group_by(Entity.id, Entity.name, Entity.entity_type)
        .order_by(desc("mentions"))
        .limit(10)
        .all()
    )
    return [
        {
            "entity_id": row.id,
            "name": row.name,
            "entity_type": row.entity_type.value if hasattr(row.entity_type, "value") else str(row.entity_type),
            "mention_count": int(row.mentions or 0),
            "article_count": int(row.articles or 0),
        }
        for row in rows
    ]


def _chat_article_summaries(articles: list[Article], citations: list[dict]) -> list[str]:
    labels = {
        item.get("article_id"): item.get("label")
        for item in citations
    }
    lines = []
    for article in articles:
        summary = ""
        if article.summaries:
            summary = article.summaries[0].text
        elif article.content:
            summary = re.sub(r"\s+", " ", article.content).strip()[:260]
        source_name = article.source.name if article.source else "Unknown"
        date_text = (article.published_at or article.fetched_at or article.ingested_at)
        date_label = date_text.strftime("%Y-%m-%d") if date_text else "no date"
        label = labels.get(article.id)
        prefix = f"[{label}] " if label else ""
        lines.append(f"{prefix}{source_name} ({date_label}): {article.title}. {summary}".strip())
    return lines


def _client_chat_answer(
    client: Client,
    question: str,
    mode: str,
    articles: list[Article],
    risk_items: list[dict],
    source_counts: list[dict],
    matched_entities: list[dict],
    citations: list[dict],
    legal_context: list[dict],
) -> str:
    client_label = client.name.replace("Defense Desk", "").strip() or client.name
    if not articles:
        if legal_context:
            first_legal = legal_context[0]
            return (
                f"I found a stored legal research reference for this question [{first_legal.get('label', 'L1')}], "
                "but no matching news article in this client's permitted scope. "
                "Treat the legal item as a research lead unless it is marked lawyer verified."
            )
        return (
            f"I did not find stored coverage for {client_label} that matches this question in the permitted scope. "
            "Try a broader term, extend the date window, or add the missing person/topic to the watchlist."
        )
    latest = articles[0]
    latest_source = latest.source.name if latest.source else "Unknown"
    citation_by_article = {item.get("article_id"): item.get("label") for item in citations}
    latest_label = citation_by_article.get(latest.id, "S1")
    if mode == "attacks":
        if risk_items:
            top = risk_items[0]
            categories = ", ".join(
                category.replace("_", " ") for category in (top.get("attack_categories") or {}).keys()
            ) or "coverage volume / sentiment"
            return (
                f"I found {len(risk_items)} risk item(s) for {client_label}. The strongest item is "
                f"{top['label']} with {top['article_count']} articles across {top['source_count']} sources. "
                f"The main detected themes are {categories}. Latest matched report: {latest_source} [{latest_label}]."
            )
        return (
            f"I found {len(articles)} recent mentions for {client_label}, but no strong attack-language risk item in this window. "
            f"The latest mention is a report from {latest_source}: {latest.title} [{latest_label}]."
        )
    if mode == "sources":
        top_sources = ", ".join(f"{row['source_name']} ({row['article_count']})" for row in source_counts[:5])
        return (
            f"{client_label} is mentioned in {len(articles)} matched articles across {len(source_counts)} sources. "
            f"Top portals/sources in this answer: {top_sources or 'none'}."
        )
    if mode == "response_help":
        if risk_items:
            top = risk_items[0]
        return (
            f"For a response, start with the highest-risk item: {top['label']} ({top['severity']}). "
                f"Use the response pack for that item, cite [{latest_label}], and avoid claims not supported by the database. "
                + (
                    f"A legal research reference is available [{legal_context[0].get('label', 'L1')}], but it still requires the review status shown in the source trail."
                    if legal_context else
                    "No legal conclusion is included in this answer."
                )
            )
        return (
            f"I do not see an urgent response item for {client_label}. A short monitoring/holding line is safer than amplifying the story."
        )
    if mode == "latest":
        return (
            f"The latest stored mention I found is from {latest_source}: {latest.title}. "
            f"[{latest_label}] In total, this answer uses {len(articles)} matched article(s) across {len(source_counts)} source(s)."
        )
    entity_names = ", ".join(item["name"] for item in matched_entities[:5])
    return (
        f"I searched the permitted database for {client_label} and this question. "
        f"I found {len(articles)} matched article(s) across {len(source_counts)} source(s). "
        f"Connected entities include: {entity_names or 'none detected in the selected articles'}. "
        f"Latest matched report: {latest_source} [{latest_label}]."
    )


def _client_chat_actions(
    mode: str,
    articles: list[Article],
    risk_items: list[dict],
    source_counts: list[dict],
) -> list[str]:
    actions = []
    if risk_items:
        actions.append("Open the top risk item response pack before making a public reply.")
        actions.append("Save the top risk item as a case if it needs follow-up.")
    if len(source_counts) <= 1 and articles:
        actions.append("Treat this as single-source until another source confirms or repeats it.")
    if mode == "response_help":
        actions.append("Use only cited facts in public copy; keep legal conclusions for lawyer review.")
    if articles:
        actions.append("Open original portal URLs before using any claim externally.")
    else:
        actions.append("Broaden the question or add a new watchlist item if this should be tracked.")
    return actions[:5]


def _client_brief_headline(
    client: Client,
    risk_items: list[dict],
    articles: list[Article],
) -> str:
    if risk_items:
        top = risk_items[0]
        return f"{client.name}: {top['severity'].title()} watchlist signal on {top['label']}"
    if articles:
        return f"{client.name}: {len(articles)} new watchlist matches in the latest brief"
    return f"{client.name}: no new watchlist movement in this brief window"


def _client_brief_summary(
    client: Client,
    articles: list[Article],
    risk_items: list[dict],
) -> str:
    source_count = len({article.source_id for article in articles})
    client_type = client.client_type.value if hasattr(client.client_type, "value") else str(client.client_type)
    if not articles:
        return (
            f"No stored articles matched this {client_type} watchlist in the selected window. "
            "Keep monitoring and broaden the watchlist if the client expects active coverage."
        )
    high_count = sum(1 for item in risk_items if item.get("severity") in ("high", "critical"))
    return (
        f"Found {len(articles)} relevant items across {source_count} sources for this {client_type} client. "
        f"{high_count} high-priority risk signals need review. "
        "Use the evidence bullets below as source-backed references, not as independent factual conclusions."
    )


def _client_brief_actions(
    client: Client,
    articles: list[Article],
    risk_items: list[dict],
) -> list[str]:
    actions = []
    if risk_items:
        top = risk_items[0]
        actions.append(f"Review {top['label']} first: {top['recommended_action']}")
    if any(item.get("attack_count", 0) for item in risk_items):
        actions.append("Open a response pack for attack-language items before publishing a rebuttal.")
    if len({article.source_id for article in articles}) <= 1 and articles:
        actions.append("Treat this as limited-source coverage; verify independently before using it externally.")
    if client.client_type == ClientType.POLITICAL_PARTY:
        actions.append("Turn the strongest source-backed items into a press briefing if a statement is planned.")
    elif client.client_type == ClientType.POLITICAL_FIGURE:
        actions.append("Save serious negative mentions as incident cases to preserve evidence.")
    elif client.client_type == ClientType.PR_AGENCY:
        actions.append("Send the client a short sourced update and flag anything requiring approval.")
    elif client.client_type == ClientType.MEDIA_ANALYST:
        actions.append("Compare these matches with narratives and story clusters before writing analysis.")
    elif client.client_type == ClientType.DIASPORA:
        actions.append("Summarize only the top sourced items and link back to originals for context.")
    if not actions:
        actions.append("No urgent action. Continue monitoring the watchlist and source health.")
    actions.append("Verify dates, names, numbers, and legal claims against the original URLs before external use.")
    return actions[:6]


def _client_brief_copy_text(
    headline: str,
    summary: str,
    evidence_brief: list[dict],
    recommended_actions: list[str],
) -> str:
    evidence_lines = [
        f"- {item.get('claim')} ({item.get('source_name')}, {item.get('published_at') or 'no date'})"
        for item in evidence_brief[:5]
    ] or ["- No matched source items in this period."]
    action_lines = [f"- {action}" for action in recommended_actions]
    return "\n".join([
        headline,
        "",
        summary,
        "",
        "Evidence:",
        *evidence_lines,
        "",
        "Recommended actions:",
        *action_lines,
    ])


def _entity_brief_copy_text(
    entity_name: str,
    summary: str,
    evidence_brief: list[dict],
    related_entities: list[dict],
    recommended_actions: list[str],
) -> str:
    evidence_lines = [
        f"- {item.get('claim')} ({item.get('source_name')}, {item.get('published_at') or 'no date'})"
        for item in evidence_brief[:6]
    ] or ["- No recent source-backed evidence found."]
    related_lines = [
        f"- {item.get('name')} ({item.get('shared_articles')} shared articles)"
        for item in related_entities[:6]
    ] or ["- No connected entities found."]
    action_lines = [f"- {action}" for action in recommended_actions]
    return "\n".join([
        f"Entity briefing: {entity_name}",
        "",
        summary,
        "",
        "Evidence:",
        *evidence_lines,
        "",
        "Connected entities:",
        *related_lines,
        "",
        "Verification notes:",
        *action_lines,
    ])


def _briefing_confidence(
    articles: list[Article],
    source_count: int,
    legal_context: list[dict],
) -> dict:
    if not articles:
        return {
            "level": "low",
            "score": 15,
            "reason": "No stored source coverage matched the query.",
        }

    official_or_lawyer_refs = [
        item for item in legal_context
        if item.get("status") in {"official", "lawyer_verified"}
    ]
    score = 30
    score += min(30, len(articles) * 3)
    score += min(25, source_count * 5)
    if official_or_lawyer_refs:
        score += 15
    score = min(95, score)
    if score >= 75:
        level = "high"
    elif score >= 50:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "score": score,
        "article_count": len(articles),
        "source_count": source_count,
        "official_legal_refs": len(official_or_lawyer_refs),
        "reason": (
            "Confidence is based on stored article volume, source diversity, and whether official/legal references exist. "
            "It is not a truth score."
        ),
    }


def _grounding_contract(
    evidence_brief: list[dict],
    citation_pack: list[dict],
    claim_support_matrix: list[dict],
    legal_context: list[dict],
    confidence: dict,
) -> dict:
    """Summarize what can be safely used without inventing beyond sources."""
    source_count = confidence.get("source_count") or len({
        item.get("source_name")
        for item in evidence_brief
        if item.get("source_name")
    })
    article_count = confidence.get("article_count") or len(evidence_brief)
    unsupported = [
        item for item in claim_support_matrix
        if item.get("status") == "unsupported_by_current_data"
    ]
    single_source = [
        item for item in claim_support_matrix
        if item.get("status") == "single_source"
    ]
    legal_review_claims = [
        item for item in claim_support_matrix
        if item.get("legal_review_required") or item.get("status") == "legal_review_required"
    ]
    legal_review_refs = [
        item for item in legal_context
        if item.get("requires_lawyer_review")
    ]
    citation_ready = bool(citation_pack)
    evidence_ready = article_count >= 3 and source_count >= 2
    legal_review_required = bool(legal_review_claims or legal_review_refs)
    blocked_claims = [
        item.get("claim")
        for item in [*unsupported, *legal_review_claims]
        if item.get("claim")
    ]
    caution_claims = [
        item.get("claim")
        for item in single_source
        if item.get("claim")
    ]

    if unsupported or legal_review_required:
        decision = "hold"
        public_use = "Internal prep only until unsupported claims and legal-review items are cleared."
    elif not evidence_ready or not citation_ready or single_source:
        decision = "caution"
        public_use = "Use cautious wording, cite sources directly, and label single-source items clearly."
    else:
        decision = "ready"
        public_use = "Usable as a sourced briefing draft with citations attached."

    return {
        "decision": decision,
        "public_use": public_use,
        "evidence_ready": evidence_ready,
        "citation_ready": citation_ready,
        "legal_review_required": legal_review_required,
        "article_count": article_count,
        "source_count": source_count,
        "citation_count": len(citation_pack),
        "unsupported_claim_count": len(unsupported),
        "single_source_claim_count": len(single_source),
        "legal_review_count": len(legal_review_claims) + len(legal_review_refs),
        "blocked_public_claims": blocked_claims[:10],
        "caution_claims": caution_claims[:10],
        "rules": [
            "Use article titles, dates, source names, URLs, and citation labels exactly as stored.",
            "Do not turn reported allegations into proven facts.",
            "Do not make legal conclusions unless the legal reference is official or lawyer verified.",
            "Single-source items can be mentioned only as single-source reporting.",
            "Unsupported claims must stay out of public statements.",
        ],
    }


def _claims_to_verify(
    topic: str,
    requirements: Optional[str],
    articles: list[Article],
    legal_context: list[dict],
) -> list[str]:
    checks = [
        "Verify exact dates, names, and numbers against the original article URLs before speaking publicly.",
        "Separate what a source reported from what the party independently knows or alleges.",
    ]
    if not articles:
        checks.append(f"No stored articles matched '{topic}'; ingest more sources or broaden the query before relying on this briefing.")
    if requirements:
        checks.append(f"Check the requested angle against documents or official records before claiming it: {requirements}")
    if len({article.source_id for article in articles}) <= 1 and articles:
        checks.append("Only one source is represented; find a second independent source before using this as a central claim.")
    if not any(item.get("status") in {"official", "lawyer_verified"} for item in legal_context):
        checks.append("Legal references are research leads unless marked official or lawyer verified; do not present them as legal advice.")
    checks.append("For accusations of corruption, criminal conduct, or illegality, cite official proceedings or phrase as a request for investigation.")
    return checks


def _build_press_conference_outline(
    topic: str,
    objective: Optional[str],
    articles: list[Article],
) -> list[str]:
    evidence_line = (
        f"Evidence: cite {min(3, len(articles))} strongest sourced items with dates."
        if articles else
        "Evidence: say the party is still collecting verified material."
    )
    return [
        "Opening: one sentence that names the issue and the public interest.",
        f"Context: explain why {topic} matters now.",
        evidence_line,
        f"Position: {objective or 'state the party position and desired outcome.'}",
        "Accountability: name what institutions, officials, or opponents should answer.",
        "Legal caution: avoid accusing individuals of crimes unless backed by official proceedings.",
        "Close: repeat the requested action and invite questions.",
    ]


def _party_risk_warnings(articles: list[Article], attack_categories: dict) -> list[str]:
    warnings = [
        "Do not present allegations as proven facts unless supported by official documents or final decisions.",
        "Keep personal attacks separate from public-interest criticism.",
    ]
    if not articles:
        warnings.append("Coverage is thin for this query; mark claims as party position, not established fact.")
    if attack_categories:
        warnings.append(
            "Detected attack-language themes in the coverage; prepare sourced answers and avoid escalating tone."
        )
    if len({article.source_id for article in articles}) <= 1 and articles:
        warnings.append("Single-source coverage: verify independently before using it as a main argument.")
    return warnings


def _macedonian_legal_context(
    db: Session,
    country_code: str,
    topic: str,
    requirements: Optional[str],
) -> list[dict]:
    """Return stored legal references first, then starter fallback cards."""
    text_value = f"{topic} {requirements or ''}".lower()
    terms = _briefing_terms(topic, requirements)
    conditions = []
    for term in terms[:8]:
        pattern = f"%{term}%"
        conditions.append(or_(
            LegalDocument.title.ilike(pattern),
            LegalDocument.legal_area.ilike(pattern),
            LegalDocument.summary.ilike(pattern),
            LegalDocument.reference_text.ilike(pattern),
            LegalDocument.article_refs.ilike(pattern),
        ))
    if conditions:
        documents = (
            db.query(LegalDocument)
            .filter(LegalDocument.country_code == country_code)
            .filter(or_(*conditions))
            .order_by(LegalDocument.confidence_score.desc(), LegalDocument.updated_at.desc())
            .limit(5)
            .all()
        )
        if documents:
            return [_legal_context_from_document(document) for document in documents]

    cards = [
        {
            "area": "Freedom of expression and public debate",
            "use_for": "Political speech, criticism, press statements, media response.",
            "guidance": (
                "Frame statements as opinion, public-interest criticism, or sourced factual claims. "
                "Avoid presenting unverified allegations as final legal conclusions."
            ),
            "status": "starter_reference_needs_official_text",
        },
        {
            "area": "Defamation and insult risk",
            "use_for": "Responding to attacks or making allegations about opponents.",
            "guidance": (
                "Use evidence, dates, and sources. Prefer 'we ask institutions to investigate' "
                "over direct accusations unless official records support the claim."
            ),
            "status": "starter_reference_needs_official_text",
        },
        {
            "area": "Presumption of innocence",
            "use_for": "Criminal allegations, corruption claims, investigations.",
            "guidance": (
                "If discussing investigations or accusations, distinguish allegation, investigation, "
                "charge, and final judgment."
            ),
            "status": "starter_reference_needs_official_text",
        },
    ]
    if any(term in text_value for term in ("election", "campaign", "избор", "кампањ")):
        cards.append({
            "area": "Election and campaign communications",
            "use_for": "Campaign-period press conferences and party messaging.",
            "guidance": (
                "Check election silence, paid political advertising, financing, and equal-access rules "
                "before publishing campaign claims."
            ),
            "status": "starter_reference_needs_official_text",
        })
    return [_starter_legal_context_card(card) for card in cards]


def _legal_context_from_document(document: LegalDocument) -> dict:
    verified = document.source_status in {
        LegalSourceStatus.OFFICIAL,
        LegalSourceStatus.LAWYER_VERIFIED,
    }
    lawyer_verified = document.source_status == LegalSourceStatus.LAWYER_VERIFIED
    return {
        "area": document.legal_area,
        "use_for": document.title,
        "guidance": document.summary or document.reference_text or "Stored legal reference. Review source before relying on it.",
        "status": document.source_status.value,
        "source_url": document.source_url,
        "article_refs": document.article_refs,
        "confidence_score": document.confidence_score,
        "legal_basis_status": (
            "lawyer_verified" if lawyer_verified
            else "official_research_reference" if verified
            else "research_lead_needs_review"
        ),
        "requires_lawyer_review": not lawyer_verified,
        "safe_use": (
            "Can be cited as a lawyer-verified legal reference, while still checking the exact context."
            if lawyer_verified else
            "Use as an official research reference only; verify exact articles and current amendments before public legal claims."
            if verified else
            "Use only as a research lead. Do not say the law supports the position until the exact text is verified."
        ),
        "warning": "This is communications support, not legal advice. Final legal positions require qualified Macedonian counsel.",
    }


def _starter_legal_context_card(card: dict) -> dict:
    return {
        **card,
        "source_url": None,
        "article_refs": None,
        "confidence_score": 0.2,
        "legal_basis_status": "starter_reference_needs_official_text",
        "requires_lawyer_review": True,
        "safe_use": "Use only as a checklist prompt. Add an official or lawyer-reviewed legal reference before relying on it.",
        "warning": "Starter cards are not legal sources. They only tell operators what to verify.",
    }


def _attack_detail_for_article(
    item: ClientWatchlistItem,
    article: Article,
) -> dict:
    """Extract a target-specific attack relation and preserve its source trail."""
    target_entity = item.entity
    target = target_entity.name if target_entity else item.label or item.value
    aliases = [item.label, item.value]
    if target_entity:
        aliases.extend((target_entity.metadata_json or {}).get("aliases", []) or [])
    candidate_attackers = []
    for mention in article.entity_mentions:
        entity = mention.entity
        if not is_client_publishable_entity(entity):
            continue
        entity_type = corrected_entity_type(entity.name, entity.entity_type.value)
        if entity_type not in (EntityType.PERSON.value, EntityType.ORGANIZATION.value):
            continue
        if not is_likely_entity_name(entity.name, entity_type):
            continue
        stripped_name = entity.name.strip()
        if not stripped_name[:1].isupper() and stripped_name.upper() != stripped_name:
            continue
        if entity_type == EntityType.PERSON.value:
            tokens = entity.name.split()
            if len(tokens) > 3 or not all(token[:1].isupper() for token in tokens):
                continue
        candidate_attackers.append(entity.name)
    detail = analyze_attack_text(
        title=article.title or "",
        content=article.content or "",
        target=target,
        target_aliases=aliases,
        candidate_attackers=candidate_attackers,
    )
    article_date = article.published_at or article.fetched_at or article.ingested_at
    return {
        **detail,
        "article_id": article.id,
        "title": article.title,
        "url": article.url,
        "reported_by": article.source.name if article.source else "Unknown",
        "source_type": article.source.source_type if article.source else "unknown",
        "reliability_score": article.source.reliability_score if article.source else None,
        "published_at": article_date.isoformat() if article_date else None,
    }


def _attack_review_map(
    db: Session,
    watchlist_item_ids: list[int],
    article_ids: list[int],
) -> dict[tuple[int, int], AttackReview]:
    if not watchlist_item_ids or not article_ids:
        return {}
    reviews = db.query(AttackReview).filter(
        AttackReview.watchlist_item_id.in_(set(watchlist_item_ids)),
        AttackReview.article_id.in_(set(article_ids)),
    ).all()
    return {(review.watchlist_item_id, review.article_id): review for review in reviews}


def _apply_attack_review(detail: dict, review: Optional[AttackReview]) -> dict:
    """Apply audited operator feedback before an attack reaches a client view."""
    if not review:
        return {**detail, "review_status": "unreviewed"}
    reviewed = {
        **detail,
        "review_id": review.id,
        "review_status": review.status,
        "review_notes": review.notes,
    }
    if review.status == "rejected":
        return {
            **reviewed,
            "is_attack": False,
            "attacker": None,
            "allegation": None,
            "quote": None,
            "categories": [],
        }
    if review.status == "corrected":
        reviewed.update({
            "is_attack": True,
            "attacker": review.corrected_attacker or detail.get("attacker"),
            "target": review.corrected_target or detail.get("target"),
            "allegation": review.corrected_allegation or detail.get("allegation"),
            "categories": review.corrected_categories or detail.get("categories", []),
        })
    return reviewed


def _enrich_attack_spread(
    details: list[dict],
    article_count: int,
    source_count: int,
) -> list[dict]:
    if source_count >= 3:
        spread = "broad_spread"
    elif source_count == 2:
        spread = "multi_source"
    else:
        spread = "single_source"
    enriched = [
        {
            **detail,
            "spread": spread,
            "spread_article_count": article_count,
            "spread_source_count": source_count,
        }
        for detail in details
    ]
    return sorted(
        enriched,
        key=lambda detail: (
            detail.get("confidence") or 0,
            detail.get("published_at") or "",
        ),
        reverse=True,
    )


def _build_watchlist_risk_items(
    db: Session,
    watchlist: list[ClientWatchlistItem],
    since: datetime.datetime,
) -> list[dict]:
    """Build first-pass risk signals for tracked entities/keywords."""
    risk_items: list[dict] = []
    article_rows_by_item = {
        item.id: _articles_for_watchlist_item(db, item, since)
        for item in watchlist
    }
    review_map = _attack_review_map(
        db,
        [item.id for item in watchlist],
        [article.id for rows in article_rows_by_item.values() for article, _, _ in rows],
    )
    for item in watchlist:
        articles = article_rows_by_item[item.id]
        if not articles:
            continue

        negative_count = 0
        attack_count = 0
        attack_categories = {}
        total_mentions = 0
        sources = set()
        latest_at = None
        attack_details = []

        for article, sentiment, mention_count in articles:
            total_mentions += mention_count or 1
            sources.add(article.source.name if article.source else "Unknown")
            article_date = article.published_at or article.fetched_at or article.ingested_at
            if article_date and (latest_at is None or article_date > latest_at):
                latest_at = article_date
            if sentiment is not None and sentiment < -0.05:
                negative_count += 1
            detail = _apply_attack_review(
                _attack_detail_for_article(item, article),
                review_map.get((item.id, article.id)),
            )
            if detail["is_attack"]:
                attack_details.append(detail)
                attack_count += 1
                for category in detail["categories"]:
                    attack_categories[category] = attack_categories.get(category, 0) + 1

        severity = _risk_severity(
            article_count=len(articles),
            source_count=len(sources),
            negative_count=negative_count,
            attack_count=attack_count,
            priority=item.priority,
        )
        if severity == "none":
            continue

        attack_details = _enrich_attack_spread(
            attack_details,
            article_count=len(articles),
            source_count=len(sources),
        )

        risk_items.append({
            "watchlist_item_id": item.id,
            "label": item.label,
            "item_type": item.item_type.value,
            "severity": severity,
            "article_count": len(articles),
            "source_count": len(sources),
            "negative_count": negative_count,
            "attack_count": attack_count,
            "attack_categories": attack_categories,
            # Keep enough cited rows for attack-specific portal spread while
            # still bounding dashboard payload size.
            "attack_details": attack_details[:25],
            "mention_count": total_mentions,
            "latest_at": latest_at.isoformat() if latest_at else None,
            "recommended_action": _recommended_action(severity, attack_count),
            "response_assist_enabled": item.response_assist_enabled,
        })

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        risk_items,
        key=lambda row: (severity_rank.get(row["severity"], 9), -row["article_count"]),
    )


def _risk_item_from_article_rows(
    db: Session,
    item: ClientWatchlistItem,
    articles: list[tuple[Article, Optional[float], int]],
) -> dict:
    negative_count = 0
    attack_count = 0
    attack_categories = {}
    total_mentions = 0
    sources = set()
    latest_at = None
    attack_details = []
    review_map = _attack_review_map(
        db,
        [item.id],
        [article.id for article, _, _ in articles],
    )

    for article, sentiment, mention_count in articles:
        total_mentions += mention_count or 1
        sources.add(article.source.name if article.source else "Unknown")
        article_date = article.published_at or article.fetched_at or article.ingested_at
        if article_date and (latest_at is None or article_date > latest_at):
            latest_at = article_date
        if sentiment is not None and sentiment < -0.05:
            negative_count += 1
        detail = _apply_attack_review(
            _attack_detail_for_article(item, article),
            review_map.get((item.id, article.id)),
        )
        if detail["is_attack"]:
            attack_details.append(detail)
            attack_count += 1
            for category in detail["categories"]:
                attack_categories[category] = attack_categories.get(category, 0) + 1

    severity = _risk_severity(
        article_count=len(articles),
        source_count=len(sources),
        negative_count=negative_count,
        attack_count=attack_count,
        priority=item.priority,
    )
    attack_details = _enrich_attack_spread(
        attack_details,
        article_count=len(articles),
        source_count=len(sources),
    )
    return {
        "label": item.label,
        "item_type": item.item_type.value,
        "severity": severity,
        "article_count": len(articles),
        "source_count": len(sources),
        "negative_count": negative_count,
        "attack_count": attack_count,
        "attack_categories": attack_categories,
        "attack_details": attack_details[:25],
        "mention_count": total_mentions,
        "latest_at": latest_at.isoformat() if latest_at else None,
    }


def _build_response_pack(
    db: Session,
    client: Client,
    item: ClientWatchlistItem,
    risk_item: dict,
    source_articles: list[Article],
) -> dict:
    severity = risk_item.get("severity", "none")
    article_count = risk_item.get("article_count", 0)
    source_count = risk_item.get("source_count", 0)
    attack_count = risk_item.get("attack_count", 0)
    negative_count = risk_item.get("negative_count", 0)
    target = item.label
    latest_titles = [article.title for article in source_articles[:3]]

    summary = (
        f"{target} has {article_count} recent matched items across "
        f"{source_count} sources. Detected {attack_count} attack-language "
        f"signals and {negative_count} negative sentiment signals."
    )
    if latest_titles:
        summary += f" Latest examples: {'; '.join(latest_titles)}."

    posture = _response_posture(severity, attack_count, client.risk_tolerance)
    legal_flags = _legal_review_flags(source_articles, attack_count, severity)
    evidence_brief = _source_evidence_brief(source_articles)
    citation_pack = _citation_pack(evidence_brief)
    legal_context = _macedonian_legal_context(db, client.country_code, item.label, item.notes)
    claim_support_matrix = _claim_support_matrix(
        topic=item.label,
        requirements=item.notes,
        articles=source_articles,
        legal_context=legal_context,
        extra_claims=[],
    )
    confidence = _briefing_confidence(source_articles, source_count, legal_context)
    grounding_contract = _grounding_contract(
        evidence_brief=evidence_brief,
        citation_pack=citation_pack,
        claim_support_matrix=claim_support_matrix,
        legal_context=legal_context,
        confidence=confidence,
    )
    attack_analysis = _response_attack_analysis(
        target=target,
        risk_item=risk_item,
        source_articles=source_articles,
        posture=posture,
    )
    claims_to_verify = _claims_to_verify(item.label, item.notes, source_articles, legal_context)
    claims_to_verify.extend(_claim_matrix_verification_notes(claim_support_matrix))
    if any(item.get("requires_lawyer_review") for item in legal_context):
        legal_flags.append("Legal context includes research leads or official references that still require qualified lawyer review before public legal claims.")
    response_strategy = _response_strategy(
        target=target,
        severity=severity,
        posture=posture,
        risk_item=risk_item,
        evidence_brief=evidence_brief,
        citation_pack=citation_pack,
        claim_support_matrix=claim_support_matrix,
        claims_to_verify=claims_to_verify,
        legal_flags=legal_flags,
        legal_context=legal_context,
        grounding_contract=grounding_contract,
    )
    evidence_steps = [
        "Save URLs, timestamps, source names, and full post/article text.",
        "Preserve screenshots before responding, especially for social posts.",
        "Separate factual claims from opinion or political criticism.",
        "Collect documents or public records that support any factual correction.",
    ]

    draft_responses = [
        _response_draft_version(
            version_id="holding_statement",
            tone="cautious holding statement",
            use_case="Use when the story is still developing or evidence needs verification.",
            status="internal_review",
            public_readiness="caution",
            target=target,
            text=(
                f"We have seen the recent claims concerning {target}. "
                f"{response_strategy['safe_opening']} "
                "We ask media and public figures to rely on verified information and to correct any unsupported statements."
            ),
        ),
        _response_draft_version(
            version_id="firm_rebuttal",
            tone="firm rebuttal",
            use_case="Use only when evidence/citations support a stronger public reply.",
            status="internal_review",
            public_readiness="caution",
            target=target,
            text=(
                f"{response_strategy['primary_line']} "
                "Any stronger claim should be made only after the evidence and legal-review items below are cleared."
            ),
        ),
        _response_draft_version(
            version_id="request_correction",
            tone="request correction",
            use_case="Use when a source should clarify or correct a factual statement.",
            status="internal_review",
            public_readiness="caution",
            target=target,
            text=(
                f"We request that the source correct or clarify the statements made about {target}. "
                "If factual allegations are being made, they should be backed by evidence, dates, documents, and responsible attribution."
            ),
        ),
        _response_draft_version(
            version_id="press_qa_answer",
            tone="press Q&A answer",
            use_case="Use as a short answer when journalists ask about the attack.",
            status="internal_review",
            public_readiness="caution",
            target=target,
            text=(
                f"Our answer on {target} is simple: we will separate sourced facts from claims and speculation. "
                f"{response_strategy['publication_gate']} "
                "Where claims are unsupported, they should not be repeated as fact."
            ),
        ),
    ]
    if severity in ("critical", "high"):
        draft_responses.append(
            _response_draft_version(
                version_id="legal_review_hold",
                tone="legal-review hold",
                use_case="Use for high-risk allegations until counsel reviews wording.",
                status="legal_review",
                public_readiness="hold",
                target=target,
                text=(
                    "Because the claims may affect reputation and legal rights, we are preserving the record and will respond after legal review. "
                    "Until then, we ask all parties to avoid repeating unverified allegations."
                ),
            )
        )

    response_generation = _grounded_work_product_generation(
        task=f"Explain the reported attack or criticism concerning {target} and draft a cautious response.",
        instructions=(
            f"Severity signal: {severity}. Recommended posture: {posture}. "
            "State who reported or alleged what only when the evidence identifies them. "
            "The answer should be a client-readable attack explanation, not a legal conclusion."
        ),
        citation_pack=citation_pack,
        legal_context=legal_context,
    )
    if response_generation.accepted:
        generated = response_generation.payload
        summary = generated["summary"]
        attack_analysis["ai_explanation"] = generated["answer"]
        response_strategy["ai_recommended_actions"] = generated["suggested_actions"]
        draft_responses.insert(0, _response_draft_version(
            version_id="ai_evidence_bound_response",
            tone="evidence-bound",
            use_case="AI-assisted draft; use only after the cited originals are reviewed.",
            status="internal_review",
            public_readiness="caution",
            target=target,
            text=generated["answer"],
        ))

    return {
        "severity": severity,
        "situation_summary": summary,
        "evidence_brief": evidence_brief,
        "citation_pack": citation_pack,
        "claim_support_matrix": claim_support_matrix,
        "claims_to_verify": claims_to_verify,
        "confidence": confidence,
        "generation": response_generation.metadata(),
        "grounding_contract": grounding_contract,
        "attack_analysis": attack_analysis,
        "response_strategy": response_strategy,
        "recommended_posture": posture,
        "legal_review_flags": legal_flags,
        "legal_context": legal_context,
        "evidence_steps": evidence_steps,
        "draft_responses": draft_responses,
    }


def _response_strategy(
    target: str,
    severity: str,
    posture: str,
    risk_item: dict,
    evidence_brief: list[dict],
    citation_pack: list[dict],
    claim_support_matrix: list[dict],
    claims_to_verify: list[str],
    legal_flags: list[str],
    legal_context: list[dict],
    grounding_contract: dict,
) -> dict:
    """Build a practical response plan from evidence and guardrails only."""
    source_count = risk_item.get("source_count", 0)
    article_count = risk_item.get("article_count", 0)
    attack_categories = risk_item.get("attack_categories") or {}
    top_attack = None
    if attack_categories:
        top_attack = sorted(attack_categories.items(), key=lambda row: row[1], reverse=True)[0][0].replace("_", " ")

    strongest_citations = []
    for citation in citation_pack[:4]:
        strongest_citations.append({
            "label": citation.get("label"),
            "source_name": citation.get("source_name"),
            "claim": citation.get("claim") or citation.get("inline"),
            "url": citation.get("url"),
            "safe_use": citation.get("safe_use"),
        })

    supported_claims = [
        item.get("claim")
        for item in claim_support_matrix
        if item.get("status") == "source_supported" and item.get("claim")
    ][:4]
    caution_claims = [
        item.get("claim")
        for item in claim_support_matrix
        if item.get("status") != "source_supported" and item.get("claim")
    ][:4]

    legal_review_required = bool(
        legal_flags
        or grounding_contract.get("legal_review_required")
        or any(item.get("requires_lawyer_review") for item in legal_context)
    )
    evidence_ready = bool(evidence_brief and citation_pack and source_count >= 2)
    decision = grounding_contract.get("decision") or "caution"

    if decision == "hold" or legal_review_required:
        publication_gate = "Do not publish a final factual or legal rebuttal until review clears the flagged items."
        public_posture = "Internal prep only"
    elif evidence_ready:
        publication_gate = "A cautious public response is usable if citation labels and source links stay attached."
        public_posture = "Cited cautious response"
    else:
        publication_gate = "Use only a short holding line until more source evidence is available."
        public_posture = "Holding line only"

    if strongest_citations:
        first = strongest_citations[0]
        primary_line = (
            f"The safest line is to acknowledge the coverage on {target}, point to the cited source trail "
            f"starting with [{first.get('label')}] {first.get('source_name')}, and avoid claims beyond what the sources say."
        )
    else:
        primary_line = (
            f"The safest line is to acknowledge the issue around {target}, say the team is checking the facts, "
            "and avoid a detailed rebuttal until stored evidence is available."
        )

    safe_opening = (
        f"The current database shows {article_count} matched items across {source_count} sources"
        + (f", with the main detected attack theme: {top_attack}." if top_attack else ".")
    )

    response_angle = (
        f"Respond to the {top_attack} theme with documented facts and calm wording."
        if top_attack else
        "Respond to the coverage pattern, not to assumed motives or unsupported claims."
    )

    return {
        "public_posture": public_posture,
        "decision": decision,
        "severity": severity,
        "primary_line": primary_line,
        "safe_opening": safe_opening,
        "response_angle": response_angle,
        "publication_gate": publication_gate,
        "evidence_to_use": strongest_citations,
        "supported_claims": supported_claims,
        "claims_to_avoid": [
            *caution_claims,
            *claims_to_verify[:4],
            "Do not state that a legal position is confirmed unless counsel has reviewed the exact law and facts.",
            "Do not accuse a person or institution of criminal conduct without official documents or proceedings.",
        ][:8],
        "questions_to_answer_before_publish": [
            "Which exact source sentence or document supports the response?",
            "Is the item multi-source, single-source, or only a low-spread mention?",
            "Are there legal terms, accusations, corruption claims, or criminal claims that need counsel review?",
            "Can the response be written as a correction request instead of a counter-accusation?",
        ],
        "operator_notes": [
            posture,
            "Keep citation labels attached when copying text outside the system.",
            "Use this as communications intelligence, not legal advice.",
        ],
    }


def _response_attack_analysis(
    target: str,
    risk_item: dict,
    source_articles: list[Article],
    posture: str,
) -> dict:
    """Explain the attack pattern without inventing actors or unsupported motives."""
    categories = risk_item.get("attack_categories") or {}
    sorted_categories = sorted(categories.items(), key=lambda row: row[1], reverse=True)
    top_category = sorted_categories[0][0].replace("_", " ") if sorted_categories else None
    source_counts: dict[str, int] = {}
    for article in source_articles:
        source_name = article.source.name if article.source else "Unknown"
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
    top_sources = [
        source for source, _count in sorted(
            source_counts.items(),
            key=lambda row: (-row[1], row[0]),
        )[:5]
    ]
    article_count = risk_item.get("article_count", len(source_articles))
    source_count = risk_item.get("source_count", len(source_counts))
    attack_count = risk_item.get("attack_count", 0)
    attack_details = risk_item.get("attack_details") or []
    primary_detail = attack_details[0] if attack_details else {}

    if top_category:
        what = f"The strongest detected theme around {target} is {top_category}."
    elif attack_count:
        what = f"Attack-language is appearing around {target}, but the exact theme needs article review."
    elif source_count > 1:
        what = f"{target} is being discussed across multiple portals without a strong attack theme."
    else:
        what = f"{target} has limited recent coverage in the current response window."

    if source_count >= 5:
        spread = f"The story has broad portal spread across {source_count} sources."
    elif source_count >= 2:
        spread = f"The story appears in {source_count} sources, so treat it as a spreading issue."
    else:
        spread = "This is still a single-source or low-spread item; avoid amplifying it unless the claim is serious."

    return {
        "what_is_the_attack": what,
        "why_it_matters": (
            f"The system found {article_count} matched articles and {attack_count} attack-language signals. "
            "Use this as a triage signal, then read the source trail before speaking publicly."
        ),
        "where_it_spread": spread,
        "source_depth": f"{article_count} articles across {source_count} sources.",
        "safest_response_angle": posture,
        "historical_context_note": (
            "This pack uses the current database window only. Historical comparison becomes stronger after backfill."
        ),
        "top_sources": top_sources,
        "attack_categories": categories,
        "attacker": primary_detail.get("attacker"),
        "target": primary_detail.get("target") or target,
        "exact_allegation": primary_detail.get("allegation"),
        "quoted_speech": primary_detail.get("quote"),
        "relation_confidence": primary_detail.get("confidence"),
        "relation_confidence_label": primary_detail.get("confidence_label"),
        "extraction_basis": primary_detail.get("extraction_basis", []),
        "attack_details": attack_details[:8],
    }


def _response_draft_version(
    version_id: str,
    tone: str,
    use_case: str,
    status: str,
    public_readiness: str,
    target: str,
    text: str,
) -> dict:
    """Return an auditable response draft version with Macedonian-facing copy."""
    risk_level = "high" if status == "legal_review" or public_readiness == "hold" else "medium" if public_readiness == "caution" else "low"
    return {
        "version_id": version_id,
        "tone": tone,
        "use_case": use_case,
        "status": status,
        "public_readiness": public_readiness,
        "risk_level": risk_level,
        "language": "en",
        "text": text,
        "mk_text": _mk_response_template(version_id, target),
    }


def _mk_response_template(version_id: str, target: str) -> str:
    """Conservative Macedonian-facing response templates without unsourced claims."""
    templates = {
        "holding_statement": (
            f"Ги следиме последните тврдења поврзани со {target}. "
            "Јавноста заслужува точни информации, затоа ги проверуваме конкретните наводи и ќе одговориме со факти, извори и датуми. "
            "Бараме сите јавни изјави да се темелат на проверени информации."
        ),
        "firm_rebuttal": (
            f"Тврдењата што се шират за {target} не смеат да се претставуваат како факт без докази. "
            "Ги отфрламе неподдржаните наводи и повикуваме секој што изнесува фактички тврдења да ги поткрепи со документи и проверливи извори."
        ),
        "request_correction": (
            f"Бараме изворот да ја појасни или коригира изјавата поврзана со {target}. "
            "Доколку се изнесуваат фактички наводи, тие треба да бидат поткрепени со докази и претставени одговорно."
        ),
        "press_qa_answer": (
            f"Нашиот став за {target} е дека мора јасно да се одвојат фактите од шпекулациите. "
            "Ќе се повикуваме само на извори, датуми и документи што можат да се проверат."
        ),
        "legal_review_hold": (
            "Бидејќи наводите може да засегаат углед и правни прашања, го зачувуваме доказниот материјал и ќе одговориме по правна проверка. "
            "До тогаш, бараме да не се повторуваат непроверени обвинувања."
        ),
    }
    return templates.get(version_id, templates["holding_statement"])


def _response_posture(severity: str, attack_count: int, risk_tolerance: str) -> str:
    if severity in ("critical", "high"):
        return "Respond only with verified facts; preserve evidence and request legal review before naming accusers."
    if severity == "medium":
        return "Prepare a calm clarification and publish only if the story spreads beyond the first sources."
    if attack_count:
        return "Monitor closely; avoid amplifying the attack unless a correction is necessary."
    if risk_tolerance == "aggressive":
        return "A short factual rebuttal is acceptable, but avoid personal counterattacks."
    return "No public response is required yet; continue monitoring."


def _legal_review_flags(
    source_articles: list[Article],
    attack_count: int,
    severity: str,
) -> list[str]:
    flags = []
    combined = " ".join(
        f"{article.title} {article.content or ''}" for article in source_articles
    ).lower()
    serious_terms = [
        "corruption", "criminal", "crime", "fraud", "bribe", "investigation",
        "корупција", "криминал", "измама", "поткуп", "истрага",
    ]
    if any(term in combined for term in serious_terms):
        flags.append("Potential serious factual allegation; verify evidence before responding.")
    if attack_count > 0:
        flags.append("Attack-language detected; avoid defamatory counterclaims in response.")
    if severity in ("critical", "high"):
        flags.append("High reputational risk; lawyer review recommended before escalation.")
    if not flags:
        flags.append("No immediate legal escalation detected; keep response factual and proportionate.")
    return flags


def _articles_for_watchlist_item(
    db: Session,
    item: ClientWatchlistItem,
    since: datetime.datetime,
) -> list[tuple[Article, Optional[float], int]]:
    date_column = func.coalesce(
        Article.published_at, Article.fetched_at, Article.ingested_at
    )

    if item.entity_id:
        rows = (
            db.query(Article, EntityMention.sentiment_score, EntityMention.mention_count)
            .join(EntityMention, EntityMention.article_id == Article.id)
            .filter(EntityMention.entity_id == item.entity_id)
            .filter(_active_article_filter())
            .filter(_recent_article_filter(since))
            .order_by(date_column.desc())
            .limit(100)
            .all()
        )
        return _filter_client_article_rows(rows)[:50]

    if item.source_id:
        rows = (
            db.query(Article)
            .filter(Article.source_id == item.source_id)
            .filter(_active_article_filter())
            .filter(_recent_article_filter(since))
            .order_by(date_column.desc())
            .limit(100)
            .all()
        )
        return [(article, None, 1) for article in rows if _is_client_usable_article(article)][:50]

    condition = article_text_match(db, [item.value.strip()])
    if condition is None:
        return []
    rows = (
        db.query(Article)
        .filter(_active_article_filter())
        .filter(_recent_article_filter(since))
        .filter(condition)
        .order_by(date_column.desc())
        .limit(100)
        .all()
    )
    return [(article, None, 1) for article in rows if _is_client_usable_article(article)][:50]


def _recent_article_filter(since: datetime.datetime):
    """Use indexed date columns instead of filtering through SQL COALESCE."""
    return or_(
        Article.published_at >= since,
        and_(
            Article.published_at.is_(None),
            Article.fetched_at >= since,
        ),
        and_(
            Article.published_at.is_(None),
            Article.fetched_at.is_(None),
            Article.ingested_at >= since,
        ),
    )


def _filter_client_article_rows(
    rows: list[tuple[Article, Optional[float], int]]
) -> list[tuple[Article, Optional[float], int]]:
    return [row for row in rows if _is_client_usable_article(row[0])]


def _is_client_usable_article(article: Article) -> bool:
    """Keep non-article scraper pages out of client-facing packs and briefings."""
    if (article.quality_status or "active") == "excluded":
        return False
    if article.ingestion_method != "scrape":
        return True
    return not _stored_article_quality_reasons(article)


def _contains_attack_language(text_value: str) -> bool:
    return bool(_attack_categories(text_value))


def _attack_categories(text_value: str) -> list[str]:
    return detect_attack_categories(text_value)


def _narrative_categories(text_value: str) -> list[str]:
    narrative_terms = {
        "corruption_and_tenders": [
            "corruption", "tender", "procurement", "bribe", "abuse of office",
            "корупција", "тендер", "набавка", "поткуп", "злоупотреба",
        ],
        "eu_integration": [
            "european union", "eu", "brussels", "screening", "accession",
            "еу", "европска унија", "брисел", "пристапување", "интеграција",
        ],
        "economy_prices": [
            "economy", "inflation", "prices", "budget", "wages", "investment",
            "економија", "инфлација", "цени", "буџет", "плати", "инвестиции",
        ],
        "judiciary_rule_of_law": [
            "court", "judge", "prosecutor", "rule of law", "justice",
            "суд", "судија", "обвинител", "правда", "владеење на правото",
        ],
        "elections_campaign": [
            "election", "campaign", "poll", "candidate", "coalition",
            "избори", "кампања", "анкета", "кандидат", "коалиција",
        ],
        "ethnic_relations": [
            "ethnic", "albanian", "macedonian", "minority", "language law",
            "етнич", "албан", "македон", "малцинство", "закон за јазици",
        ],
        "crime_security": [
            "crime", "police", "arrest", "security", "violence",
            "криминал", "полиција", "апсење", "безбедност", "насилство",
        ],
        "local_governance": [
            "municipality", "mayor", "council", "urban", "construction",
            "општина", "градоначалник", "совет", "урбан", "градба",
        ],
        "foreign_policy_region": [
            "bulgaria", "greece", "serbia", "kosovo", "nato", "region",
            "бугарија", "грција", "србија", "косово", "нато", "регион",
        ],
    }
    matches = []
    for narrative, terms in narrative_terms.items():
        if any(term in text_value for term in terms):
            matches.append(narrative)
    return matches


def _risk_severity(
    article_count: int,
    source_count: int,
    negative_count: int,
    attack_count: int,
    priority: int,
) -> str:
    score = 0
    score += min(article_count, 8)
    score += source_count * 2
    score += negative_count * 2
    score += attack_count * 3
    score += max(0, 4 - priority)

    if score >= 18:
        return "critical"
    if score >= 12:
        return "high"
    if score >= 7:
        return "medium"
    if attack_count or negative_count:
        return "low"
    return "none"


def _recommended_action(severity: str, attack_count: int) -> str:
    if severity == "critical":
        return "Prepare response pack now; preserve evidence and escalate for legal review."
    if severity == "high":
        return "Draft a factual response and monitor amplification over the next few hours."
    if severity == "medium":
        return "Review context and prepare a measured clarification if the story spreads."
    if attack_count:
        return "Monitor closely; response may be useful if more sources repeat the claim."
    return "No immediate response recommended."


def _merge_facebook_monitors(
    country_config: dict,
    db: Session,
    country_code: str,
) -> dict:
    """Add active DB-managed Facebook pages to the country config."""
    pages = list(country_config.get("facebook_pages", []))
    monitors = (
        db.query(FacebookPageMonitor)
        .filter(
            FacebookPageMonitor.country_code == country_code,
            FacebookPageMonitor.is_active == True,
        )
        .all()
    )
    existing = {
        (page.get("url") or page.get("page_handle") or page.get("page_id"))
        for page in pages
    }
    for monitor in monitors:
        key = monitor.url or monitor.page_handle or monitor.page_id
        if key in existing:
            continue
        pages.append(_facebook_monitor_to_fetch_config(monitor))
    country_config["facebook_pages"] = pages
    return country_config


def _facebook_monitor_to_fetch_config(monitor: FacebookPageMonitor) -> dict:
    return {
        "name": monitor.name,
        "url": monitor.url,
        "page_handle": monitor.page_handle,
        "page_id": monitor.page_id,
        "enabled": monitor.is_active,
        "language": monitor.language,
        "source_type": monitor.source_type,
        "political_leaning": monitor.political_leaning,
        "ownership": monitor.ownership,
        "reliability_score": monitor.reliability_score,
        "monitor_type": monitor.monitor_type,
    }


def _mark_facebook_monitors_fetched(db: Session, country_code: str):
    now = datetime.datetime.utcnow()
    monitors = (
        db.query(FacebookPageMonitor)
        .filter(
            FacebookPageMonitor.country_code == country_code,
            FacebookPageMonitor.is_active == True,
        )
        .all()
    )
    for monitor in monitors:
        monitor.last_fetched_at = now
    db.commit()


def _add_ingestion_totals(total: dict, stats: dict):
    for key in ("total", "checked", "new", "duplicate", "duplicate_fuzzy", "error"):
        total[key] += stats.get(key, 0)
    if stats.get("stopped_early"):
        total["stopped_sources"] += 1


def _ingestion_source_status(discovered_urls: int, scraped_count: int, stats: dict) -> str:
    if stats.get("stopped_early"):
        return "caught_up"
    if stats.get("error", 0) and not stats.get("new", 0) and not stats.get("duplicate", 0):
        return "error"
    if discovered_urls == 0 and scraped_count == 0:
        return "rss_only" if stats.get("total", 0) else "failing"
    if scraped_count == 0:
        return "rss_only" if stats.get("total", 0) else "no_links"
    if stats.get("new", 0) or stats.get("duplicate", 0) or stats.get("duplicate_fuzzy", 0):
        return "healthy"
    return "degraded"


def _record_ingestion_source_stat(
    db: Session,
    run: IngestionRun,
    source: dict,
    discovered_urls: int,
    scraped_count: int,
    rss_count: int,
    stats: dict,
    status: str,
    raw_articles: list,
):
    word_counts = [
        len(article.content.split())
        for article in raw_articles
        if getattr(article, "content", None)
    ]
    average_word_count = round(sum(word_counts) / len(word_counts), 1) if word_counts else 0.0
    db.add(IngestionSourceStat(
        run_id=run.id,
        source_name=source.get("name", ""),
        source_url=source.get("url"),
        source_type=source.get("source_type", "news"),
        scraper_enabled=bool((source.get("scraper") or {}).get("enabled")),
        rss_enabled=bool(source.get("rss_feeds")),
        discovered_urls=discovered_urls,
        scraped_count=scraped_count,
        rss_count=rss_count,
        raw_count=stats.get("total", 0),
        checked_count=stats.get("checked", stats.get("total", 0)),
        new_count=stats.get("new", 0),
        duplicate_count=stats.get("duplicate", 0),
        duplicate_fuzzy_count=stats.get("duplicate_fuzzy", 0),
        duplicate_streak=stats.get("duplicate_streak", 0),
        stopped_early=bool(stats.get("stopped_early")),
        error_count=stats.get("error", 0),
        success_count=stats.get("new", 0) + stats.get("duplicate", 0) + stats.get("duplicate_fuzzy", 0),
        failed_count=stats.get("error", 0),
        average_word_count=average_word_count,
        status=status,
    ))
    db.commit()


def _upsert_facebook_source(db: Session, monitor: FacebookPageMonitor):
    """Mirror a Facebook monitor into sources for attribution and stats."""
    source = db.query(Source).filter(Source.url == monitor.url).first()
    if not source:
        source = Source(
            name=monitor.name,
            url=monitor.url,
            country_code=monitor.country_code,
            language=monitor.language,
            reliability_score=monitor.reliability_score,
            source_type=monitor.source_type,
            political_leaning=monitor.political_leaning,
            ownership=monitor.ownership,
            rss_feeds=[],
            is_active=monitor.is_active,
        )
        db.add(source)
        return

    source.name = monitor.name
    source.country_code = monitor.country_code
    source.language = monitor.language
    source.reliability_score = monitor.reliability_score
    source.source_type = monitor.source_type
    source.political_leaning = monitor.political_leaning
    source.ownership = monitor.ownership
    source.is_active = monitor.is_active


def _facebook_handle_from_url(url: str) -> Optional[str]:
    if "facebook.com/" not in url:
        return None
    tail = url.split("facebook.com/", 1)[1].strip("/")
    if not tail or tail.startswith("profile.php"):
        return None
    return tail.split("?")[0].split("/")[0]


def _code_to_filename(code: str) -> str:
    """Map country code to config filename."""
    mapping = {
        "mk": "north_macedonia",
        "rs": "serbia",
        "al": "albania",
        "bg": "bulgaria",
        "xk": "kosovo",
    }
    return mapping.get(code.lower(), code.lower())
