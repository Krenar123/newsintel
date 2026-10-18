"""
Database models for NewsIntel.

Core tables:
  - Source:          News portal/outlet
  - Article:         Individual news article
  - Summary:         Extractive or AI-generated summary of an article
  - Entity:          A named person, org, or place (deduplicated)
  - EntityMention:   Links an entity to an article (many-to-many with metadata)
  - Category:        Article category assignment
  - Report:          Generated PDF/briefing
  - Subscription:    Client subscription for scheduled reports
"""

import datetime
from typing import Optional, List

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, Index, Enum, UniqueConstraint, Table, JSON,
    func, inspect, text,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, Session,
    sessionmaker,
)
import enum


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EntityType(str, enum.Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    EVENT = "event"
    OTHER = "other"


class SummaryType(str, enum.Enum):
    EXTRACTIVE = "extractive"       # Free, local (sumy)
    ABSTRACTIVE = "abstractive"     # Paid, Claude API


class ReportFormat(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    JSON = "json"
    EMAIL = "email"


class SubscriptionFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class ClientType(str, enum.Enum):
    POLITICAL_FIGURE = "political_figure"
    POLITICAL_PARTY = "political_party"
    PR_AGENCY = "pr_agency"
    JOURNALIST = "journalist"
    MEDIA_ANALYST = "media_analyst"
    BUSINESS_RISK = "business_risk"
    DIASPORA = "diaspora"
    ADMIN = "admin"


class SubscriptionPlan(str, enum.Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    POLITICAL_DEFENSE = "political_defense"
    CAMPAIGN = "campaign"
    ENTERPRISE = "enterprise"


class WatchlistItemType(str, enum.Enum):
    ENTITY = "entity"
    KEYWORD = "keyword"
    SOURCE = "source"
    FACEBOOK_PAGE = "facebook_page"
    OPPONENT = "opponent"
    TOPIC = "topic"


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    MONITORING = "monitoring"
    RESPONDED = "responded"
    LEGAL_REVIEW = "legal_review"
    CLOSED = "closed"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    CLIENT = "client"


class LegalSourceStatus(str, enum.Enum):
    OFFICIAL = "official"
    UNOFFICIAL_COPY = "unofficial_copy"
    NEEDS_REVIEW = "needs_review"
    OUTDATED_POSSIBLE = "outdated_possible"
    LAWYER_VERIFIED = "lawyer_verified"


class EntityStatus(str, enum.Enum):
    AUTO = "auto"
    APPROVED = "approved"
    HIDDEN = "hidden"
    NEEDS_REVIEW = "needs_review"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Source(Base):
    """A news portal or outlet (e.g., MKD.mk, Balkan Insight)."""
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(500), unique=True)
    country_code: Mapped[str] = mapped_column(String(10), index=True)
    language: Mapped[str] = mapped_column(String(10))
    reliability_score: Mapped[float] = mapped_column(Float, default=0.5)
    source_type: Mapped[str] = mapped_column(String(50), default="news", index=True)
    political_leaning: Mapped[str] = mapped_column(String(50), default="unknown")
    ownership: Mapped[Optional[str]] = mapped_column(String(500))
    rss_feeds: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )

    articles: Mapped[List["Article"]] = relationship(back_populates="source")


class User(Base):
    """Application user for admin, analyst, and client access."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.CLIENT, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    last_login_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    client: Mapped[Optional["Client"]] = relationship()


class AuthToken(Base):
    """Opaque API session token."""
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    user: Mapped["User"] = relationship()


class Client(Base):
    """A paying account/persona with its own dashboard and watchlist."""
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    client_type: Mapped[ClientType] = mapped_column(
        Enum(ClientType), default=ClientType.POLITICAL_FIGURE, index=True
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan), default=SubscriptionPlan.BASIC, index=True
    )
    country_code: Mapped[str] = mapped_column(String(10), default="mk", index=True)
    language: Mapped[str] = mapped_column(String(10), default="mk")
    risk_tolerance: Mapped[str] = mapped_column(String(50), default="balanced")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    settings_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    watchlist_items: Mapped[List["ClientWatchlistItem"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )


class ClientWatchlistItem(Base):
    """A tracked person, opponent, keyword, source, or Facebook page."""
    __tablename__ = "client_watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    item_type: Mapped[WatchlistItemType] = mapped_column(
        Enum(WatchlistItemType), index=True
    )
    label: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[str] = mapped_column(String(1000))
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("entities.id"), index=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"), index=True)
    facebook_page_url: Mapped[Optional[str]] = mapped_column(String(1000))
    priority: Mapped[int] = mapped_column(Integer, default=3, index=True)
    alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    response_assist_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )

    client: Mapped["Client"] = relationship(back_populates="watchlist_items")
    entity: Mapped[Optional["Entity"]] = relationship()
    source: Mapped[Optional["Source"]] = relationship()

    __table_args__ = (
        UniqueConstraint("client_id", "item_type", "value", name="uq_client_watch_value"),
        Index("ix_watch_client_type_priority", "client_id", "item_type", "priority"),
    )


class ClientDashboardCache(Base):
    """Short-lived personalized dashboard result, scoped to one client and window."""
    __tablename__ = "client_dashboard_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    payload: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), index=True
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "period_days",
            name="uq_client_dashboard_cache_window",
        ),
        Index("ix_client_dashboard_cache_expiry", "client_id", "expires_at"),
    )


class ClientIncident(Base):
    """A saved attack/risk case file for a client."""
    __tablename__ = "client_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    watchlist_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_watchlist_items.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(50), default="medium", index=True)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.OPEN, index=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text)
    recommended_posture: Mapped[Optional[str]] = mapped_column(Text)
    legal_review_flags: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    evidence_steps: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    draft_responses: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    source_article_ids: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), index=True
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    client: Mapped["Client"] = relationship()
    watchlist_item: Mapped[Optional["ClientWatchlistItem"]] = relationship()

    __table_args__ = (
        Index("ix_incident_client_status", "client_id", "status"),
        Index("ix_incident_client_severity", "client_id", "severity"),
    )


class ClientIncidentEvidence(Base):
    """Evidence URL/item preserved for an incident case file."""
    __tablename__ = "client_incident_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("client_incidents.id"), index=True)
    article_id: Mapped[Optional[int]] = mapped_column(ForeignKey("articles.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[Optional[str]] = mapped_column(String(500))
    source_name: Mapped[Optional[str]] = mapped_column(String(255))
    evidence_type: Mapped[str] = mapped_column(String(50), default="url", index=True)
    captured_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(1000))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())

    incident: Mapped["ClientIncident"] = relationship()
    article: Mapped[Optional["Article"]] = relationship()

    __table_args__ = (
        UniqueConstraint("incident_id", "url", name="uq_incident_evidence_url"),
        Index("ix_evidence_incident_type", "incident_id", "evidence_type"),
    )


class AttackReview(Base):
    """Human review of one target-specific attack relation in an article."""
    __tablename__ = "attack_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    watchlist_item_id: Mapped[int] = mapped_column(
        ForeignKey("client_watchlist_items.id"), index=True
    )
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    original_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    corrected_attacker: Mapped[Optional[str]] = mapped_column(String(255))
    corrected_target: Mapped[Optional[str]] = mapped_column(String(255))
    corrected_allegation: Mapped[Optional[str]] = mapped_column(Text)
    corrected_categories: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    client: Mapped["Client"] = relationship()
    watchlist_item: Mapped["ClientWatchlistItem"] = relationship()
    article: Mapped["Article"] = relationship()
    reviewer: Mapped[Optional["User"]] = relationship()

    __table_args__ = (
        UniqueConstraint("watchlist_item_id", "article_id", name="uq_attack_review_target_article"),
        Index("ix_attack_review_client_status", "client_id", "status"),
    )


class FacebookPageMonitor(Base):
    """Admin-managed Facebook Page to ingest through the Meta Graph API."""
    __tablename__ = "facebook_page_monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    page_handle: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    page_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    country_code: Mapped[str] = mapped_column(String(10), default="mk", index=True)
    language: Mapped[str] = mapped_column(String(10), default="mk")
    monitor_type: Mapped[str] = mapped_column(
        String(50), default="political_figure", index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(50), default="social_media", index=True
    )
    political_leaning: Mapped[str] = mapped_column(String(50), default="unknown")
    ownership: Mapped[Optional[str]] = mapped_column(String(500))
    reliability_score: Mapped[float] = mapped_column(Float, default=0.6)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_fetched_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_fb_monitor_country_type", "country_code", "monitor_type"),
    )


class LegalDocument(Base):
    """A stored legal reference used for cautious legal-context guidance."""
    __tablename__ = "legal_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    country_code: Mapped[str] = mapped_column(String(10), default="mk", index=True)
    legal_area: Mapped[str] = mapped_column(String(255), index=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    source_name: Mapped[Optional[str]] = mapped_column(String(255))
    source_status: Mapped[LegalSourceStatus] = mapped_column(
        Enum(LegalSourceStatus), default=LegalSourceStatus.NEEDS_REVIEW, index=True
    )
    language: Mapped[str] = mapped_column(String(10), default="mk")
    tags: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    reference_text: Mapped[Optional[str]] = mapped_column(Text)
    document_text: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(1000))
    downloaded_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    article_refs: Mapped[Optional[str]] = mapped_column(String(500))
    confidence_score: Mapped[float] = mapped_column(Float, default=0.4)
    date_accessed: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    verified_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_legal_country_area_status", "country_code", "legal_area", "source_status"),
    )


class LegalReview(Base):
    """Immutable audit record for a legal-reference review decision."""
    __tablename__ = "legal_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_document_id: Mapped[int] = mapped_column(
        ForeignKey("legal_documents.id"), index=True
    )
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    reviewer_name: Mapped[str] = mapped_column(String(255))
    reviewer_organization: Mapped[Optional[str]] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(50), index=True)
    status_before: Mapped[str] = mapped_column(String(50))
    status_after: Mapped[str] = mapped_column(String(50), index=True)
    notes: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_legal_review_document_date", "legal_document_id", "reviewed_at"),
    )


class LegalReviewAssignment(Base):
    """Counsel assignment without implying that legal review is complete."""
    __tablename__ = "legal_review_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_document_id: Mapped[int] = mapped_column(
        ForeignKey("legal_documents.id"), index=True
    )
    assigned_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    reviewer_name: Mapped[str] = mapped_column(String(255))
    reviewer_email: Mapped[Optional[str]] = mapped_column(String(320))
    reviewer_organization: Mapped[Optional[str]] = mapped_column(String(255))
    reviewer_jurisdiction: Mapped[Optional[str]] = mapped_column(String(100))
    qualification_reference: Mapped[Optional[str]] = mapped_column(String(255))
    qualification_verified_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(50), default="assigned", index=True)
    scope: Mapped[str] = mapped_column(Text)
    due_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, index=True)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_legal_assignment_document_status", "legal_document_id", "status"),
    )


class Article(Base):
    """An individual news article."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[Optional[str]] = mapped_column(Text)
    search_text: Mapped[Optional[str]] = mapped_column(
        Text,
        comment="Normalized Cyrillic/Latin search blob for title/content"
    )
    author: Mapped[Optional[str]] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(10), default="en")
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, index=True
    )
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), index=True,
        comment="When NewsIntel fetched this article from the source feed"
    )
    ingested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True,
        comment="SHA-256 of title+content for deduplication"
    )
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    quality_status: Mapped[str] = mapped_column(
        String(30), default="active", index=True,
        comment="active, excluded, needs_review, approved"
    )
    quality_notes: Mapped[Optional[str]] = mapped_column(Text)
    quality_reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    raw_html: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(1000))
    ingestion_method: Mapped[str] = mapped_column(String(50), default="rss", index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    platform_account_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    platform_account_name: Mapped[Optional[str]] = mapped_column(String(500))

    source: Mapped["Source"] = relationship(back_populates="articles")
    summaries: Mapped[List["Summary"]] = relationship(back_populates="article")
    entity_mentions: Mapped[List["EntityMention"]] = relationship(
        back_populates="article"
    )
    categories: Mapped[List["ArticleCategory"]] = relationship(
        back_populates="article"
    )

    __table_args__ = (
        Index("ix_articles_source_published", "source_id", "published_at"),
        Index("ix_articles_source_fetched", "source_id", "fetched_at"),
        UniqueConstraint("platform", "external_id", name="uq_article_platform_external_id"),
    )


class Summary(Base):
    """Article summary — either extractive (free) or abstractive (AI)."""
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), index=True
    )
    summary_type: Mapped[SummaryType] = mapped_column(
        Enum(SummaryType), default=SummaryType.EXTRACTIVE
    )
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    sentence_count: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )

    article: Mapped["Article"] = relationship(back_populates="summaries")

    __table_args__ = (
        UniqueConstraint("article_id", "summary_type", "language",
                         name="uq_summary_article_type_lang"),
    )


class Entity(Base):
    """A deduplicated named entity (person, org, location)."""
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    canonical_name: Mapped[str] = mapped_column(
        String(500), index=True,
        comment="Normalized lowercase form for dedup"
    )
    search_text: Mapped[Optional[str]] = mapped_column(
        String(1500),
        index=True,
        comment="Normalized Cyrillic/Latin search blob for entity lookup"
    )
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType), index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict,
        comment="Flexible storage: titles, aliases, wiki link, etc."
    )
    status: Mapped[EntityStatus] = mapped_column(
        Enum(EntityStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=EntityStatus.AUTO,
        index=True,
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    total_mentions: Mapped[int] = mapped_column(Integer, default=0, index=True)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )

    mentions: Mapped[List["EntityMention"]] = relationship(
        back_populates="entity"
    )

    __table_args__ = (
        UniqueConstraint("canonical_name", "entity_type",
                         name="uq_entity_name_type"),
        Index("ix_entities_type_mentions", "entity_type", "total_mentions"),
    )


class EntityMention(Base):
    """Links an entity to an article, with context."""
    __tablename__ = "entity_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id"), index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), index=True
    )
    mention_count: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="How many times entity appears in this article"
    )
    context_snippet: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="Sentence where entity was found"
    )
    sentiment_score: Mapped[Optional[float]] = mapped_column(
        Float,
        comment="Sentiment of context: -1.0 (negative) to 1.0 (positive)"
    )

    entity: Mapped["Entity"] = relationship(back_populates="mentions")
    article: Mapped["Article"] = relationship(back_populates="entity_mentions")

    __table_args__ = (
        UniqueConstraint("entity_id", "article_id",
                         name="uq_entity_article"),
    )


class ArticleCategory(Base):
    """Category assignment for an article, with confidence score."""
    __tablename__ = "article_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), index=True
    )
    category: Mapped[str] = mapped_column(String(50), index=True)
    confidence: Mapped[float] = mapped_column(
        Float, default=1.0,
        comment="ML model confidence 0.0 – 1.0"
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    article: Mapped["Article"] = relationship(back_populates="categories")

    __table_args__ = (
        UniqueConstraint("article_id", "category",
                         name="uq_article_category"),
    )


class StoryCluster(Base):
    """A group of articles that appear to report the same story/event."""
    __tablename__ = "story_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    country_code: Mapped[str] = mapped_column(String(10), default="mk", index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    canonical_key: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(50), default="single_source", index=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    high_reliability_source_count: Mapped[int] = mapped_column(Integer, default=0)
    average_reliability: Mapped[float] = mapped_column(Float, default=0.0)
    first_published_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, index=True)
    last_published_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    articles: Mapped[List["StoryClusterArticle"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_story_cluster_country_status", "country_code", "status"),
        Index("ix_story_cluster_country_last", "country_code", "last_published_at"),
    )


class StoryClusterArticle(Base):
    """Membership link between a story cluster and an article."""
    __tablename__ = "story_cluster_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("story_clusters.id"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    similarity_score: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now())

    cluster: Mapped["StoryCluster"] = relationship(back_populates="articles")
    article: Mapped["Article"] = relationship()
    source: Mapped["Source"] = relationship()

    __table_args__ = (
        UniqueConstraint("article_id", name="uq_story_cluster_article"),
        Index("ix_story_cluster_article_cluster_source", "cluster_id", "source_id"),
    )


class Report(Base):
    """A generated briefing report."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    country_code: Mapped[str] = mapped_column(String(10), index=True)
    format: Mapped[ReportFormat] = mapped_column(Enum(ReportFormat))
    categories_filter: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="Which categories were included"
    )
    date_from: Mapped[datetime.datetime] = mapped_column(DateTime)
    date_to: Mapped[datetime.datetime] = mapped_column(DateTime)
    file_path: Mapped[Optional[str]] = mapped_column(String(1000))
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )


class SavedBriefing(Base):
    """Structured saved briefing/work product that can be reopened in the UI."""
    __tablename__ = "saved_briefings"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), index=True)
    briefing_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(500))
    country_code: Mapped[str] = mapped_column(String(10), default="mk", index=True)
    topic: Mapped[Optional[str]] = mapped_column(String(500), index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("entities.id"), index=True)
    watchlist_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_watchlist_items.id"), index=True
    )
    report_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reports.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    folder: Mapped[Optional[str]] = mapped_column(String(120), default="briefings", index=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source_article_ids: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    confidence: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), index=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    client: Mapped[Optional["Client"]] = relationship()
    entity: Mapped[Optional["Entity"]] = relationship()
    watchlist_item: Mapped[Optional["ClientWatchlistItem"]] = relationship()
    report: Mapped[Optional["Report"]] = relationship()
    created_by: Mapped[Optional["User"]] = relationship()

    __table_args__ = (
        Index("ix_saved_briefing_client_type_created", "client_id", "briefing_type", "created_at"),
        Index("ix_saved_briefing_client_status_updated", "client_id", "status", "updated_at"),
    )


class SavedSearch(Base):
    """A private, reusable article search owned by one authenticated user."""
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    query: Mapped[Optional[str]] = mapped_column(String(500))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), index=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), index=True
    )

    user: Mapped["User"] = relationship()
    client: Mapped[Optional["Client"]] = relationship()

    __table_args__ = (
        Index("ix_saved_search_user_updated", "user_id", "updated_at"),
        Index("ix_saved_search_user_pinned", "user_id", "is_pinned"),
    )


class ChatConversation(Base):
    """A permission-scoped intelligence chat belonging to one client."""
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    mode: Mapped[str] = mapped_column(String(50), default="auto", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), index=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), index=True
    )

    client: Mapped["Client"] = relationship()
    created_by: Mapped["User"] = relationship()
    messages: Mapped[List["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    __table_args__ = (
        Index("ix_chat_conversation_client_updated", "client_id", "updated_at"),
    )


class ChatMessage(Base):
    """One user or assistant turn with its evidence and scope audit metadata."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[Optional[dict]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), index=True)

    conversation: Mapped["ChatConversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_chat_message_conversation_created", "conversation_id", "created_at"),
    )


class IngestionRun(Base):
    """A tracked ingestion/check run across configured sources."""
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    country_code: Mapped[str] = mapped_column(String(10), index=True)
    run_type: Mapped[str] = mapped_column(String(50), default="ingest", index=True)
    status: Mapped[str] = mapped_column(String(50), default="running", index=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), index=True)
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    total_sources: Mapped[int] = mapped_column(Integer, default=0)
    total_raw: Mapped[int] = mapped_column(Integer, default=0)
    total_new: Mapped[int] = mapped_column(Integer, default=0)
    total_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    total_duplicate_fuzzy: Mapped[int] = mapped_column(Integer, default=0)
    total_error: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    source_stats: Mapped[List["IngestionSourceStat"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class IngestionSourceStat(Base):
    """Per-source ingestion/scraper health details for one run."""
    __tablename__ = "ingestion_source_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(255), index=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    source_type: Mapped[str] = mapped_column(String(50), default="news", index=True)
    scraper_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rss_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_urls: Mapped[int] = mapped_column(Integer, default=0)
    scraped_count: Mapped[int] = mapped_column(Integer, default=0)
    rss_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_count: Mapped[int] = mapped_column(Integer, default=0)
    checked_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_fuzzy_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_streak: Mapped[int] = mapped_column(Integer, default=0)
    stopped_early: Mapped[bool] = mapped_column(Boolean, default=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    average_word_count: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    error_sample: Mapped[Optional[str]] = mapped_column(Text)
    checked_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), index=True)

    run: Mapped["IngestionRun"] = relationship(back_populates="source_stats")

    __table_args__ = (
        Index("ix_ingestion_stat_source_checked", "source_name", "checked_at"),
        Index("ix_ingestion_stat_run_status", "run_id", "status"),
    )


class Subscription(Base):
    """Client subscription for scheduled report delivery."""
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    country_code: Mapped[str] = mapped_column(String(10))
    categories: Mapped[Optional[dict]] = mapped_column(
        JSON, default=list,
        comment='Filter: ["politics", "economy"] or [] for all'
    )
    frequency: Mapped[SubscriptionFrequency] = mapped_column(
        Enum(SubscriptionFrequency), default=SubscriptionFrequency.WEEKLY
    )
    format: Mapped[ReportFormat] = mapped_column(
        Enum(ReportFormat), default=ReportFormat.PDF
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )


# ---------------------------------------------------------------------------
# Database engine & session factory
# ---------------------------------------------------------------------------

def get_engine(database_url: str):
    options = {"echo": False, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"timeout": 60}
    return create_engine(database_url, **options)


def get_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all_tables(engine):
    """Create all tables. For production, use Alembic migrations instead."""
    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)


def ensure_runtime_schema(engine):
    """
    Apply tiny additive schema repairs for local SQLite/dev databases.

    This keeps existing local data usable when models gain safe nullable/defaulted
    columns. Production should still use Alembic migrations.
    """
    inspector = inspect(engine)
    if "articles" not in inspector.get_table_names():
        return

    article_columns = {
        column["name"] for column in inspector.get_columns("articles")
    }
    if "fetched_at" not in article_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE articles ADD COLUMN fetched_at DATETIME"))
            conn.execute(text(
                "UPDATE articles "
                "SET fetched_at = COALESCE(ingested_at, published_at, CURRENT_TIMESTAMP) "
                "WHERE fetched_at IS NULL"
            ))
            if engine.dialect.name == "sqlite":
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_articles_fetched_at "
                    "ON articles (fetched_at)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_articles_source_fetched "
                    "ON articles (source_id, fetched_at)"
                ))

    source_columns = {
        column["name"] for column in inspector.get_columns("sources")
    }
    with engine.begin() as conn:
        if "source_type" not in source_columns:
            conn.execute(text(
                "ALTER TABLE sources ADD COLUMN source_type VARCHAR(50) DEFAULT 'news'"
            ))
        if "political_leaning" not in source_columns:
            conn.execute(text(
                "ALTER TABLE sources ADD COLUMN political_leaning VARCHAR(50) DEFAULT 'unknown'"
            ))
        if "ownership" not in source_columns:
            conn.execute(text(
                "ALTER TABLE sources ADD COLUMN ownership VARCHAR(500)"
            ))

    article_columns = {
        column["name"] for column in inspect(engine).get_columns("articles")
    }
    if "ingestion_method" not in article_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE articles ADD COLUMN ingestion_method VARCHAR(50) DEFAULT 'rss'"
            ))
            if engine.dialect.name == "sqlite":
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_articles_ingestion_method "
                    "ON articles (ingestion_method)"
                ))
    article_columns = {
        column["name"] for column in inspect(engine).get_columns("articles")
    }
    with engine.begin() as conn:
        if "platform" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN platform VARCHAR(50)"))
        if "external_id" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN external_id VARCHAR(255)"))
        if "platform_account_id" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN platform_account_id VARCHAR(255)"))
        if "platform_account_name" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN platform_account_name VARCHAR(500)"))
        if "search_text" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN search_text TEXT"))
        if "quality_status" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN quality_status VARCHAR(30) DEFAULT 'active'"))
            conn.execute(text("UPDATE articles SET quality_status = 'active' WHERE quality_status IS NULL"))
        if "quality_notes" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN quality_notes TEXT"))
        if "quality_reviewed_at" not in article_columns:
            conn.execute(text("ALTER TABLE articles ADD COLUMN quality_reviewed_at DATETIME"))
        if engine.dialect.name == "sqlite":
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_articles_platform "
                "ON articles (platform)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_articles_external_id "
                "ON articles (external_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_articles_platform_account_id "
                "ON articles (platform_account_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_articles_quality_status "
                "ON articles (quality_status)"
            ))

    table_names = set(inspect(engine).get_table_names())
    if "entities" in table_names:
        entity_columns = {
            column["name"] for column in inspect(engine).get_columns("entities")
        }
        with engine.begin() as conn:
            if "status" not in entity_columns:
                conn.execute(text(
                    "ALTER TABLE entities ADD COLUMN status VARCHAR(20) DEFAULT 'auto'"
                ))
                if engine.dialect.name == "sqlite":
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_entities_status "
                        "ON entities (status)"
                    ))
            if "review_notes" not in entity_columns:
                conn.execute(text("ALTER TABLE entities ADD COLUMN review_notes TEXT"))
            if "reviewed_at" not in entity_columns:
                conn.execute(text("ALTER TABLE entities ADD COLUMN reviewed_at DATETIME"))
            if "search_text" not in entity_columns:
                conn.execute(text("ALTER TABLE entities ADD COLUMN search_text VARCHAR(1500)"))
                if engine.dialect.name == "sqlite":
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_entities_search_text "
                        "ON entities (search_text)"
                    ))

    if "ingestion_source_stats" in table_names:
        stat_columns = {
            column["name"] for column in inspect(engine).get_columns("ingestion_source_stats")
        }
        with engine.begin() as conn:
            if "checked_count" not in stat_columns:
                conn.execute(text(
                    "ALTER TABLE ingestion_source_stats "
                    "ADD COLUMN checked_count INTEGER DEFAULT 0"
                ))
                conn.execute(text(
                    "UPDATE ingestion_source_stats "
                    "SET checked_count = COALESCE(raw_count, 0) "
                    "WHERE checked_count IS NULL OR checked_count = 0"
                ))
            if "duplicate_streak" not in stat_columns:
                conn.execute(text(
                    "ALTER TABLE ingestion_source_stats "
                    "ADD COLUMN duplicate_streak INTEGER DEFAULT 0"
                ))
            if "stopped_early" not in stat_columns:
                conn.execute(text(
                    "ALTER TABLE ingestion_source_stats "
                    "ADD COLUMN stopped_early BOOLEAN DEFAULT 0"
                ))

    if "saved_briefings" in table_names and engine.dialect.name == "sqlite":
        saved_briefing_columns = {
            column["name"] for column in inspect(engine).get_columns("saved_briefings")
        }
        with engine.begin() as conn:
            if "status" not in saved_briefing_columns:
                conn.execute(text(
                    "ALTER TABLE saved_briefings "
                    "ADD COLUMN status VARCHAR(50) DEFAULT 'active'"
                ))
            if "folder" not in saved_briefing_columns:
                conn.execute(text(
                    "ALTER TABLE saved_briefings "
                    "ADD COLUMN folder VARCHAR(120) DEFAULT 'briefings'"
                ))
            if "tags" not in saved_briefing_columns:
                conn.execute(text(
                    "ALTER TABLE saved_briefings "
                    "ADD COLUMN tags JSON DEFAULT '[]'"
                ))
            if "notes" not in saved_briefing_columns:
                conn.execute(text("ALTER TABLE saved_briefings ADD COLUMN notes TEXT"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_saved_briefing_client_type_created "
                "ON saved_briefings (client_id, briefing_type, created_at)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_saved_briefing_client_status_updated "
                "ON saved_briefings (client_id, status, updated_at)"
            ))

    if "legal_documents" in table_names:
        legal_columns = {
            column["name"] for column in inspect(engine).get_columns("legal_documents")
        }
        with engine.begin() as conn:
            if "document_text" not in legal_columns:
                conn.execute(text("ALTER TABLE legal_documents ADD COLUMN document_text TEXT"))
            if "content_hash" not in legal_columns:
                conn.execute(text("ALTER TABLE legal_documents ADD COLUMN content_hash VARCHAR(64)"))
            if "local_path" not in legal_columns:
                conn.execute(text("ALTER TABLE legal_documents ADD COLUMN local_path VARCHAR(1000)"))
            if "downloaded_at" not in legal_columns:
                conn.execute(text("ALTER TABLE legal_documents ADD COLUMN downloaded_at DATETIME"))
            if engine.dialect.name == "sqlite":
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_legal_documents_content_hash "
                    "ON legal_documents (content_hash)"
                ))

    if "legal_review_assignments" in table_names:
        assignment_columns = {
            column["name"]
            for column in inspect(engine).get_columns("legal_review_assignments")
        }
        date_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP"
        with engine.begin() as conn:
            if "reviewer_jurisdiction" not in assignment_columns:
                conn.execute(text(
                    "ALTER TABLE legal_review_assignments "
                    "ADD COLUMN reviewer_jurisdiction VARCHAR(100)"
                ))
            if "qualification_reference" not in assignment_columns:
                conn.execute(text(
                    "ALTER TABLE legal_review_assignments "
                    "ADD COLUMN qualification_reference VARCHAR(255)"
                ))
            if "qualification_verified_at" not in assignment_columns:
                conn.execute(text(
                    "ALTER TABLE legal_review_assignments "
                    f"ADD COLUMN qualification_verified_at {date_type}"
                ))
