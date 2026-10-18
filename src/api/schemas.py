"""Pydantic schemas for API request/response models."""

import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Article schemas ───────────────────────────────────────────────────

class ArticleSummary(BaseModel):
    """Summary within an article response."""
    text: str
    summary_type: str
    language: str

class ArticleEntity(BaseModel):
    """Entity mention within an article response."""
    entity_id: int
    name: str
    entity_type: str
    mention_count: int
    context: Optional[str] = None

class ArticleCategory(BaseModel):
    """Category assignment."""
    category: str
    confidence: float
    is_primary: bool

class ArticleResponse(BaseModel):
    """Full article response."""
    id: int
    title: str
    url: str
    content: Optional[str] = None
    source_name: str
    author: Optional[str] = None
    language: str
    published_at: Optional[datetime.datetime] = None
    fetched_at: Optional[datetime.datetime] = None
    ingested_at: Optional[datetime.datetime] = None
    ingestion_method: str = "rss"
    platform: Optional[str] = None
    external_id: Optional[str] = None
    platform_account_id: Optional[str] = None
    platform_account_name: Optional[str] = None
    word_count: Optional[int] = None
    quality_status: str = "active"
    quality_notes: Optional[str] = None
    quality_reviewed_at: Optional[datetime.datetime] = None
    image_url: Optional[str] = None
    summaries: list[ArticleSummary] = []
    categories: list[ArticleCategory] = []
    entities: list[ArticleEntity] = []

class ArticleListResponse(BaseModel):
    """Paginated article list."""
    articles: list[ArticleResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class ArticleQualityReviewUpdate(BaseModel):
    """Admin review payload for stored article quality."""
    quality_status: str = Field(pattern="^(active|approved|needs_review|excluded)$")
    quality_notes: Optional[str] = None


class AttackReviewUpdate(BaseModel):
    """Confirm, reject, or correct one detected attack relation."""
    status: str = Field(pattern="^(confirmed|rejected|corrected)$")
    corrected_attacker: Optional[str] = Field(default=None, max_length=255)
    corrected_target: Optional[str] = Field(default=None, max_length=255)
    corrected_allegation: Optional[str] = None
    corrected_categories: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ── Entity schemas ────────────────────────────────────────────────────

class EntityResponse(BaseModel):
    """Entity response."""
    id: int
    name: str
    canonical_name: str
    entity_type: str
    status: str = "auto"
    review_notes: Optional[str] = None
    provenance: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    publishable: bool = False
    matched_aliases: list[str] = Field(default_factory=list)
    total_mentions: int
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime


class EntityReviewUpdate(BaseModel):
    """Admin review/update payload for entity quality control."""
    status: Optional[str] = None
    entity_type: Optional[str] = None
    name: Optional[str] = None
    review_notes: Optional[str] = None


class EntityMergeRequest(BaseModel):
    """Merge one duplicate/bad entity into a canonical entity."""
    target_entity_id: int


class EntityLexiconAddRequest(BaseModel):
    """Add a DB entity to the curated country lexicon."""
    aliases: list[str] = Field(default_factory=list)
    entity_type: Optional[str] = None
    approve_entity: bool = True


class SourceUpdate(BaseModel):
    """Admin-editable source metadata/config."""
    is_active: Optional[bool] = None
    reliability_score: Optional[float] = Field(default=None, ge=0, le=1)
    source_type: Optional[str] = None
    political_leaning: Optional[str] = None
    ownership: Optional[str] = None
    language: Optional[str] = None
    scraper_enabled: Optional[bool] = None
    rss_enabled: Optional[bool] = None
    min_word_count: Optional[int] = Field(default=None, ge=0, le=500)
    note: Optional[str] = None
    persist_to_yaml: bool = True

class EntityArticle(BaseModel):
    """Article as seen from entity perspective."""
    article_id: int
    title: str
    url: str
    source_name: str
    published_at: Optional[datetime.datetime] = None
    mention_count: int
    context: Optional[str] = None
    sentiment: Optional[float] = None

class EntityDetailResponse(BaseModel):
    """Entity with all its article mentions."""
    entity: EntityResponse
    articles: list[EntityArticle]
    total: int
    has_more: bool


# ── Trending schemas ──────────────────────────────────────────────────

class TrendingEntity(BaseModel):
    """A trending entity."""
    entity_id: int
    name: str
    entity_type: str
    recent_mentions: int
    recent_articles: int
    previous_mentions: int
    trend_score: float
    trend_direction: str  # rising, falling, stable


class PoliticalRiskResponse(BaseModel):
    """Computed political/media risk score."""
    score: int
    level: str
    drivers: list[str]
    breakdown: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    items: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    alert_suggestions: list[dict] = Field(default_factory=list)


class AlertCreate(BaseModel):
    """Create a user alert rule from JSON."""
    name: str
    user_email: str = "admin@newsintel.local"
    alert_type: str
    channel: str = "in_app"
    criteria: dict = Field(default_factory=dict)
    channel_config: dict = Field(default_factory=dict)
    country_code: Optional[str] = "mk"
    cooldown_minutes: int = Field(default=60, ge=0)


class RiskAlertSuggestionCreate(BaseModel):
    """Turn a computed risk suggestion into an alert rule."""
    suggestion_type: str
    label: str
    criteria: dict = Field(default_factory=dict)
    user_email: str = "admin@newsintel.local"
    country_code: str = "mk"
    channel: str = "in_app"
    cooldown_minutes: int = Field(default=60, ge=0)


# ── Category schemas ──────────────────────────────────────────────────

class CategoryStats(BaseModel):
    """Category with article count."""
    category: str
    article_count: int


# ── Report schemas ────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    """Request to generate a report."""
    country_code: str = "mk"
    categories: Optional[list[str]] = None
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None
    format: str = "pdf"  # pdf, json

class ReportResponse(BaseModel):
    """Report generation response."""
    report_id: int
    file_path: str
    article_count: int
    categories: list[str]
    date_range: str


# ── Subscription schemas ─────────────────────────────────────────────

class ReportListItem(BaseModel):
    """Generated report list item."""
    id: int
    title: str
    country_code: str
    format: str
    categories_filter: Optional[dict] = None
    date_from: datetime.datetime
    date_to: datetime.datetime
    file_path: Optional[str] = None
    article_count: int
    created_at: datetime.datetime
    download_url: str


class SavedBriefingCreate(BaseModel):
    """Persist a structured briefing so it can be reopened later."""
    briefing_type: str
    title: str
    country_code: str = "mk"
    topic: Optional[str] = None
    entity_id: Optional[int] = None
    watchlist_item_id: Optional[int] = None
    report_id: Optional[int] = None
    status: str = "active"
    folder: Optional[str] = "briefings"
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    source_article_ids: list[int] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict)


class SavedBriefingUpdate(BaseModel):
    """Update an existing saved structured briefing."""
    briefing_type: Optional[str] = None
    title: Optional[str] = None
    country_code: Optional[str] = None
    topic: Optional[str] = None
    entity_id: Optional[int] = None
    watchlist_item_id: Optional[int] = None
    report_id: Optional[int] = None
    status: Optional[str] = None
    folder: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    payload: Optional[dict] = None
    source_article_ids: Optional[list[int]] = None
    confidence: Optional[dict] = None


class SavedBriefingResponse(BaseModel):
    """Saved structured briefing item."""
    id: int
    client_id: Optional[int] = None
    briefing_type: str
    title: str
    country_code: str
    topic: Optional[str] = None
    entity_id: Optional[int] = None
    watchlist_item_id: Optional[int] = None
    report_id: Optional[int] = None
    status: str = "active"
    folder: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    payload: dict
    source_article_ids: list[int] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict)
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SubscriptionCreate(BaseModel):
    """Create a new subscription."""
    email: str
    name: Optional[str] = None
    country_code: str = "mk"
    categories: Optional[list[str]] = None
    frequency: str = "weekly"
    format: str = "pdf"

class SubscriptionResponse(BaseModel):
    """Subscription details."""
    id: int
    email: str
    name: Optional[str] = None
    country_code: str
    categories: Optional[list[str]] = None
    frequency: str
    format: str
    is_active: bool
    last_sent_at: Optional[datetime.datetime] = None


# ── Search schemas ────────────────────────────────────────────────────

class SearchQuery(BaseModel):
    """Search request parameters."""
    q: str = ""
    category: Optional[str] = None
    source_id: Optional[int] = None
    country_code: Optional[str] = None
    language: Optional[str] = None
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None
    date_basis: str = "published"
    entity_id: Optional[int] = None
    limit: int = Field(default=20, le=100)
    offset: int = Field(default=0, ge=0)


class SavedSearchCreate(BaseModel):
    """Create a private reusable search from the current article filters."""
    title: str = Field(min_length=1, max_length=160)
    query: Optional[str] = Field(default=None, max_length=500)
    filters: dict = Field(default_factory=dict)
    is_pinned: bool = False


class SavedSearchUpdate(BaseModel):
    """Update the label, query, filters, or pinned state of a saved search."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    query: Optional[str] = Field(default=None, max_length=500)
    filters: Optional[dict] = None
    is_pinned: Optional[bool] = None


class SavedSearchResponse(BaseModel):
    id: int
    title: str
    query: Optional[str] = None
    filters: dict = Field(default_factory=dict)
    is_pinned: bool = False
    created_at: datetime.datetime
    updated_at: datetime.datetime


# ── Ingestion schemas ────────────────────────────────────────────────

class IngestResponse(BaseModel):
    """Ingestion result stats."""
    total: int
    new: int
    duplicate: int
    error: int

class ProcessResponse(BaseModel):
    """Processing result stats."""
    processed: int
    errors: int


# ── Country schemas ──────────────────────────────────────────────────

class CountryResponse(BaseModel):
    """Country configuration summary."""
    name: str
    code: str
    languages: list[str]
    source_count: int
    feed_count: int


# Client/watchlist schemas

class ClientCreate(BaseModel):
    """Create a client account/persona."""
    name: str
    email: Optional[str] = None
    client_type: str = "political_figure"
    plan: str = "basic"
    country_code: str = "mk"
    language: str = "mk"
    risk_tolerance: str = "balanced"
    settings: dict = Field(default_factory=dict)


class ClientResponse(BaseModel):
    """Client account/persona response."""
    id: int
    name: str
    email: Optional[str] = None
    client_type: str
    plan: str
    country_code: str
    language: str
    risk_tolerance: str
    is_active: bool
    settings: dict = Field(default_factory=dict)
    created_at: datetime.datetime


class WatchlistItemCreate(BaseModel):
    """Create a tracked entity, keyword, source, opponent, or Facebook page."""
    item_type: str
    label: str
    value: str
    entity_id: Optional[int] = None
    source_id: Optional[int] = None
    facebook_page_url: Optional[str] = None
    priority: int = Field(default=3, ge=1, le=5)
    alert_enabled: bool = True
    response_assist_enabled: bool = True
    notes: Optional[str] = None


class WatchlistItemResponse(BaseModel):
    """Tracked item response."""
    id: int
    client_id: int
    item_type: str
    label: str
    value: str
    entity_id: Optional[int] = None
    source_id: Optional[int] = None
    facebook_page_url: Optional[str] = None
    priority: int
    alert_enabled: bool
    response_assist_enabled: bool
    notes: Optional[str] = None
    created_at: datetime.datetime


class ClientDashboardResponse(BaseModel):
    """Personalized dashboard summary for one client."""
    client: ClientResponse
    watchlist: list[WatchlistItemResponse]
    metrics: dict
    risk_items: list[dict]
    recent_articles: list[ArticleResponse]


class ClientDailyBriefResponse(BaseModel):
    """Client-specific daily brief generated from watchlist coverage."""
    client: ClientResponse
    generated_at: datetime.datetime
    period_days: int
    headline: str
    summary: str
    risk_items: list[dict]
    evidence_brief: list[dict]
    recommended_actions: list[str]
    matched_articles: list[ArticleResponse]
    copy_text: str


class ClientChatRequest(BaseModel):
    """Ask a grounded question against a client's permitted intelligence data."""
    question: str = Field(..., min_length=2, max_length=1200)
    days: int = Field(default=30, ge=1, le=365)
    mode: str = "auto"
    include_wider_context: bool = False
    conversation_id: Optional[int] = None


class ClientChatTurnResponse(BaseModel):
    """One stored turn in a client intelligence conversation."""
    id: int
    role: str
    content: str
    citations: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime.datetime


class ClientChatConversationResponse(BaseModel):
    """Conversation summary or full transcript for one permitted client."""
    id: int
    client_id: int
    title: str
    mode: str
    message_count: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime
    messages: list[ClientChatTurnResponse] = Field(default_factory=list)


class ClientChatResponse(BaseModel):
    """Grounded client chat answer with citations and permission notes."""
    client: ClientResponse
    question: str
    mode: str
    conversation_id: int
    turn_number: int
    answer: str
    summary: str
    restrictions: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)
    legal_context: list[dict] = Field(default_factory=list)
    source_articles: list[ArticleResponse] = Field(default_factory=list)
    matched_entities: list[dict] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict)
    generation: dict = Field(default_factory=dict)
    history: list[ClientChatTurnResponse] = Field(default_factory=list)
    saved_briefing_id: Optional[int] = None
    disclaimer: str


class ClientUsageResponse(BaseModel):
    """Plan usage and limits for billing/product control."""
    client: ClientResponse
    plan: str
    limits: dict
    usage: dict
    features: dict


class PartyBriefingRequest(BaseModel):
    """Prepare a political party press-conference briefing from stored coverage."""
    topic: str
    objective: Optional[str] = None
    requirements: Optional[str] = None
    audience: Optional[str] = None
    tone: Optional[str] = "statesmanlike"
    include_entities: list[str] = Field(default_factory=list)
    include_opponents: list[str] = Field(default_factory=list)
    include_legal_context: bool = True
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None
    include_watchlist: bool = True
    max_articles: int = Field(default=20, ge=5, le=50)


class PartyBriefingResponse(BaseModel):
    """Party war-room briefing response."""
    client: ClientResponse
    topic: str
    objective: Optional[str] = None
    audience: Optional[str] = None
    tone: Optional[str] = None
    date_range: str
    coverage_summary: str
    verified_facts: list[dict] = Field(default_factory=list)
    single_source_claims: list[dict] = Field(default_factory=list)
    evidence_brief: list[dict] = Field(default_factory=list)
    citation_pack: list[dict] = Field(default_factory=list)
    claim_support_matrix: list[dict] = Field(default_factory=list)
    claims_to_verify: list[str] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict)
    generation: dict = Field(default_factory=dict)
    grounding_contract: dict = Field(default_factory=dict)
    briefing_strategy: dict = Field(default_factory=dict)
    suggested_talking_points: list[str]
    press_conference_outline: list[str]
    draft_outputs: dict = Field(default_factory=dict)
    do_not_say_unless_verified: list[str] = Field(default_factory=list)
    risk_warnings: list[str]
    legal_context: list[dict]
    source_articles: list[ArticleResponse]
    disclaimer: str


class ResponsePackResponse(BaseModel):
    """Suggested response pack for a watchlist risk item."""
    client: ClientResponse
    watchlist_item: WatchlistItemResponse
    severity: str
    situation_summary: str
    evidence_brief: list[dict] = Field(default_factory=list)
    citation_pack: list[dict] = Field(default_factory=list)
    claim_support_matrix: list[dict] = Field(default_factory=list)
    claims_to_verify: list[str] = Field(default_factory=list)
    confidence: dict = Field(default_factory=dict)
    generation: dict = Field(default_factory=dict)
    grounding_contract: dict = Field(default_factory=dict)
    attack_analysis: dict = Field(default_factory=dict)
    response_strategy: dict = Field(default_factory=dict)
    recommended_posture: str
    legal_review_flags: list[str]
    legal_context: list[dict] = Field(default_factory=list)
    evidence_steps: list[str]
    draft_responses: list[dict]
    source_articles: list[ArticleResponse]
    disclaimer: str


class IncidentCreate(BaseModel):
    """Create a saved client incident/case file."""
    watchlist_item_id: Optional[int] = None
    title: str
    severity: str = "medium"
    status: str = "open"
    summary: Optional[str] = None
    recommended_posture: Optional[str] = None
    legal_review_flags: list[str] = Field(default_factory=list)
    evidence_steps: list[str] = Field(default_factory=list)
    draft_responses: list[dict] = Field(default_factory=list)
    source_article_ids: list[int] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    """Update a saved client incident/case file."""
    title: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    recommended_posture: Optional[str] = None
    legal_review_flags: Optional[list[str]] = None
    evidence_steps: Optional[list[str]] = None
    draft_responses: Optional[list[dict]] = None
    source_article_ids: Optional[list[int]] = None


class IncidentResponse(BaseModel):
    """Saved client incident/case file response."""
    id: int
    client_id: int
    watchlist_item_id: Optional[int] = None
    title: str
    severity: str
    status: str
    summary: Optional[str] = None
    recommended_posture: Optional[str] = None
    legal_review_flags: list[str] = Field(default_factory=list)
    evidence_steps: list[str] = Field(default_factory=list)
    draft_responses: list[dict] = Field(default_factory=list)
    source_article_ids: list[int] = Field(default_factory=list)
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    created_at: datetime.datetime


class EvidenceCreate(BaseModel):
    """Create evidence for a saved incident."""
    article_id: Optional[int] = None
    url: str
    title: Optional[str] = None
    source_name: Optional[str] = None
    evidence_type: str = "url"
    published_at: Optional[datetime.datetime] = None
    content_hash: Optional[str] = None
    screenshot_path: Optional[str] = None
    notes: Optional[str] = None


class EvidenceResponse(BaseModel):
    """Evidence item for a saved incident."""
    id: int
    incident_id: int
    article_id: Optional[int] = None
    url: str
    title: Optional[str] = None
    source_name: Optional[str] = None
    evidence_type: str
    captured_at: datetime.datetime
    published_at: Optional[datetime.datetime] = None
    content_hash: Optional[str] = None
    screenshot_path: Optional[str] = None
    notes: Optional[str] = None


class UserCreate(BaseModel):
    """Create an app user."""
    email: str
    name: str
    password: str
    role: str = "client"
    client_id: Optional[int] = None
    is_active: bool = True


class UserResponse(BaseModel):
    """Application user response."""
    id: int
    email: str
    name: str
    role: str
    client_id: Optional[int] = None
    is_active: bool
    created_at: datetime.datetime
    last_login_at: Optional[datetime.datetime] = None


class LoginRequest(BaseModel):
    """Login request."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Login response with bearer token."""
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime.datetime
    user: UserResponse


class FacebookPageMonitorCreate(BaseModel):
    """Create an admin-managed Facebook Page monitor."""
    name: str
    url: str
    page_handle: Optional[str] = None
    page_id: Optional[str] = None
    country_code: str = "mk"
    language: str = "mk"
    monitor_type: str = "political_figure"
    source_type: str = "social_media"
    political_leaning: str = "unknown"
    ownership: Optional[str] = None
    reliability_score: float = Field(default=0.6, ge=0, le=1)
    is_active: bool = True
    notes: Optional[str] = None


class FacebookPageMonitorResponse(BaseModel):
    """Admin-managed Facebook Page monitor response."""
    id: int
    name: str
    url: str
    page_handle: Optional[str] = None
    page_id: Optional[str] = None
    country_code: str
    language: str
    monitor_type: str
    source_type: str
    political_leaning: str
    ownership: Optional[str] = None
    reliability_score: float
    is_active: bool
    last_fetched_at: Optional[datetime.datetime] = None
    notes: Optional[str] = None
    created_at: datetime.datetime


class LegalDocumentCreate(BaseModel):
    """Create a legal reference from a manually found source."""
    title: str
    country_code: str = "mk"
    legal_area: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_status: str = "needs_review"
    language: str = "mk"
    tags: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    reference_text: Optional[str] = None
    article_refs: Optional[str] = None
    confidence_score: float = Field(default=0.4, ge=0, le=1)
    notes: Optional[str] = None


class LegalDocumentUpdate(BaseModel):
    """Update review fields for a legal reference."""
    title: Optional[str] = None
    legal_area: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_status: Optional[str] = None
    tags: Optional[list[str]] = None
    summary: Optional[str] = None
    reference_text: Optional[str] = None
    article_refs: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    notes: Optional[str] = None
    mark_verified: bool = False


class LegalDocumentResponse(BaseModel):
    """Stored legal reference response."""
    id: int
    title: str
    country_code: str
    legal_area: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_status: str
    language: str
    tags: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    reference_text: Optional[str] = None
    content_hash: Optional[str] = None
    local_path: Optional[str] = None
    downloaded_at: Optional[datetime.datetime] = None
    text_length: int = 0
    article_refs: Optional[str] = None
    confidence_score: float
    date_accessed: datetime.datetime
    verified_at: Optional[datetime.datetime] = None
    notes: Optional[str] = None
    created_at: datetime.datetime


class LegalReviewCreate(BaseModel):
    """Audited review decision submitted by an administrator."""
    decision: str
    reviewer_name: str = Field(min_length=2, max_length=255)
    reviewer_organization: Optional[str] = Field(default=None, max_length=255)
    notes: str = Field(min_length=10, max_length=5000)


class LegalReviewResponse(BaseModel):
    id: int
    legal_document_id: int
    reviewer_user_id: Optional[int] = None
    reviewer_name: str
    reviewer_organization: Optional[str] = None
    decision: str
    status_before: str
    status_after: str
    notes: str
    reviewed_at: datetime.datetime
    created_at: datetime.datetime


class LegalReviewAssignmentCreate(BaseModel):
    """Assign a legal reference to qualified external or internal counsel."""
    reviewer_name: str = Field(min_length=2, max_length=255)
    reviewer_email: Optional[str] = Field(default=None, max_length=320)
    reviewer_organization: Optional[str] = Field(default=None, max_length=255)
    reviewer_jurisdiction: Optional[str] = Field(default=None, max_length=100)
    qualification_reference: Optional[str] = Field(default=None, max_length=255)
    scope: str = Field(min_length=10, max_length=5000)
    due_at: Optional[datetime.datetime] = None
    notes: Optional[str] = Field(default=None, max_length=5000)


class LegalReviewAssignmentResponse(BaseModel):
    id: int
    legal_document_id: int
    assigned_by_user_id: Optional[int] = None
    reviewer_name: str
    reviewer_email: Optional[str] = None
    reviewer_organization: Optional[str] = None
    reviewer_jurisdiction: Optional[str] = None
    qualification_reference: Optional[str] = None
    qualification_verified_at: Optional[datetime.datetime] = None
    status: str
    scope: str
    due_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    notes: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
