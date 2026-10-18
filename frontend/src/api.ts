export const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export type ArticleSummary = {
  text: string;
  summary_type: string;
  language: string;
};

export type ArticleCategory = {
  category: string;
  confidence: number;
  is_primary: boolean;
};

export type ArticleEntity = {
  entity_id: number;
  name: string;
  entity_type: string;
  mention_count: number;
  context?: string | null;
};

export type Article = {
  id: number;
  title: string;
  url: string;
  content?: string | null;
  source_name: string;
  author?: string | null;
  language: string;
  published_at?: string | null;
  fetched_at?: string | null;
  ingested_at?: string | null;
  ingestion_method: string;
  platform?: string | null;
  external_id?: string | null;
  platform_account_id?: string | null;
  platform_account_name?: string | null;
  word_count?: number | null;
  quality_status: string;
  quality_notes?: string | null;
  quality_reviewed_at?: string | null;
  image_url?: string | null;
  summaries: ArticleSummary[];
  categories: ArticleCategory[];
  entities: ArticleEntity[];
};

export type ArticleListResponse = {
  articles: Article[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type Entity = {
  id: number;
  name: string;
  canonical_name: string;
  entity_type: string;
  status: string;
  review_notes?: string | null;
  provenance?: string[];
  confidence?: number | null;
  publishable?: boolean;
  matched_aliases?: string[];
  decision_reasons?: string[];
  evidence_count?: number;
  trust_tier?: string;
  total_mentions: number;
  first_seen_at: string;
  last_seen_at: string;
};

export type EntityReviewInput = {
  status?: string;
  entity_type?: string;
  name?: string;
  review_notes?: string;
};

export type EntityBulkHideResult = {
  checked: number;
  hidden: number;
  examples: Array<{
    id: number;
    name: string;
    entity_type: string;
    total_mentions: number;
    reasons?: string[];
  }>;
};

export type EntityQualityReport = {
  checked: number;
  suspicious_count: number;
  reason_counts: Record<string, number>;
  examples: Array<{
    id: number;
    name: string;
    entity_type: string;
    status: string;
    total_mentions: number;
    reasons: string[];
    candidate_score?: number | null;
    decision_reasons?: string[];
    evidence_count?: number;
    trust_tier?: string;
  }>;
};

export type SearchQuality = {
  country_code: string;
  status: string;
  article_count: number;
  entity_count: number;
  missing_article_search_text: number;
  missing_entity_search_text: number;
  query_checks: Array<{
    label: string;
    query: string;
    variants: string[];
    article_total: number;
    entity_total: number;
    status: string;
  }>;
  recommendations: string[];
  backfill_command: string;
};

export type EntityLexiconCoverage = {
  country_code: string;
  lexicon_path: string;
  known_count: number;
  matched_count: number;
  missing_count: number;
  uncovered_count: number;
  matched_examples: Array<{
    lexicon_name: string;
    db_entity_id: number;
    db_name: string;
    entity_type: string;
    total_mentions: number;
    status: string;
  }>;
  missing_examples: Array<{
    name: string;
    entity_type: string;
    aliases: string[];
  }>;
  uncovered_entities: Array<{
    entity_id: number;
    name: string;
    entity_type: string;
    total_mentions: number;
    status: string;
    suggested_action: string;
  }>;
  recommendations: string[];
};

export type EntityLexiconAddResult = {
  status: string;
  path: string;
  backup?: string | null;
  entity_id: number;
  name: string;
  entity_type?: string;
  aliases?: string[];
  matched_lexicon_name?: string;
};

export type EntityArticle = {
  article_id: number;
  title: string;
  url: string;
  source_name: string;
  published_at?: string | null;
  mention_count: number;
  context?: string | null;
  sentiment?: number | null;
};

export type EntityDetail = {
  entity: Entity;
  articles: EntityArticle[];
  total: number;
  has_more: boolean;
};

export type EntitySentiment = {
  entity: { id: number; name: string; type: string };
  period_days: number;
  total_scored_mentions: number;
  overall_sentiment: number;
  sentiment_label: string;
  timeline: Array<{
    date: string;
    avg_sentiment: number;
    article_count: number;
    min_sentiment: number;
    max_sentiment: number;
  }>;
  recent_mentions: Array<{
    article_id: number;
    title: string;
    url: string;
    published_at?: string | null;
    sentiment_score: number;
    context?: string | null;
  }>;
};

export type Trend = {
  entity_id: number;
  name: string;
  entity_type: string;
  recent_mentions: number;
  recent_articles: number;
  previous_mentions: number;
  trend_score: number;
  trend_direction: string;
};

export type StoryCluster = {
  id: number;
  title: string;
  status: string;
  validation_explanation: string;
  country_code: string;
  article_count: number;
  source_count: number;
  original_source_count: number;
  aggregator_source_count: number;
  aggregator_sources: string[];
  high_reliability_source_count: number;
  average_reliability: number;
  spread_hours?: number | null;
  spread_score?: number;
  spread_velocity?: number;
  spread_label?: string;
  risk_flags: string[];
  first_published_at?: string | null;
  last_published_at?: string | null;
  summary?: string | null;
  sources: string[];
  source_breakdown: Array<{
    source_id: number;
    source_name: string;
    source_type: string;
    political_leaning: string;
    reliability_score: number;
    article_count: number;
    latest_published_at?: string | null;
  }>;
  articles: Array<{
    article_id: number;
    title: string;
    url: string;
    source_name: string;
    source_reliability?: number | null;
    published_at?: string | null;
    similarity_score: number;
  }>;
};

export type StorySpread = {
  country_code: string;
  period_days: number;
  generated_at: string;
  stories: StoryCluster[];
  summary: {
    validated: number;
    multi_source: number;
    aggregator_indexed: number;
    single_source: number;
  };
};

export type PoliticalRisk = {
  score: number;
  level: string;
  drivers: string[];
  breakdown: Record<string, number>;
  metrics: Record<string, unknown>;
  items: Array<{
    article_id: number;
    title: string;
    url: string;
    source_name: string;
    published_at?: string | null;
    attack_categories?: string[];
    narratives?: string[];
    political_context?: boolean;
    reliability?: number | null;
  }>;
  events: Array<{
    event_type: string;
    severity: string;
    title: string;
    why_it_matters?: string | null;
    source_count?: number;
    article_count?: number;
    recommended_action?: string;
  }>;
  alert_suggestions: Array<{
    type: string;
    label: string;
    criteria: Record<string, unknown>;
  }>;
};

export type DailyBrief = {
  country_code: string;
  generated_at: string;
  period_days: number;
  headline: string;
  risk: {
    score: number;
    level: string;
    drivers: string[];
    breakdown?: Record<string, number>;
    metrics: Record<string, unknown>;
    events?: PoliticalRisk["events"];
    alert_suggestions?: PoliticalRisk["alert_suggestions"];
  };
  validated_stories: StoryCluster[];
  trending_entities: Trend[];
  narratives: Narrative[];
  top_articles: Article[];
  recommended_actions: string[];
};

export type CategoryStat = {
  category: string;
  article_count: number;
};

export type Country = {
  name: string;
  code: string;
  languages: string[];
  source_count: number;
  feed_count: number;
};

export type Alert = {
  id: number;
  name: string;
  alert_type: string;
  channel: string;
  criteria: Record<string, unknown>;
  is_active: boolean;
  total_triggers?: number;
  last_triggered_at?: string | null;
};

export type SavedSearch = {
  id: number;
  title: string;
  query?: string | null;
  filters: Record<string, string | number | boolean>;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
};

export type SavedSearchInput = {
  title: string;
  query?: string;
  filters: Record<string, string | number | boolean | undefined>;
  is_pinned?: boolean;
};

export type RiskAlertSuggestionInput = {
  suggestion_type: string;
  label: string;
  criteria: Record<string, unknown>;
  user_email: string;
  country_code: string;
  channel: string;
  cooldown_minutes: number;
};

export type AlertInput = {
  name: string;
  user_email: string;
  alert_type: string;
  channel: string;
  criteria: Record<string, unknown>;
  channel_config?: Record<string, unknown>;
  country_code?: string;
  cooldown_minutes: number;
};

export type IngestResult = {
  total: number;
  new: number;
  duplicate: number;
  error: number;
};

export type RelatedEntity = {
  entity_id: number;
  name: string;
  entity_type: string;
  shared_articles: number;
  mention_count: number;
};

export type EntityBriefing = {
  entity: Entity;
  generated_at: string;
  period_days: number;
  headline: string;
  summary: string;
  sentiment: {
    score: number;
    label: string;
    scored_mentions: number;
  };
  mention_timeline: Array<{
    date: string;
    mentions: number;
    article_count: number;
  }>;
  source_coverage: Array<{
    source_name: string;
    source_type: string;
    reliability_score?: number | null;
    article_count: number;
    mention_count: number;
  }>;
  connected_entities: RelatedEntity[];
  story_clusters: StoryCluster[];
  evidence_brief: EvidenceBriefItem[];
  source_articles: Article[];
  recommended_actions: string[];
  copy_text: string;
};

export type SourceStat = {
  source_id: number;
  name: string;
  url: string;
  country_code: string;
  language: string;
  reliability_score: number;
  source_type: string;
  political_leaning: string;
  ownership?: string | null;
  is_active: boolean;
  article_count: number;
  processed_count: number;
  latest_article_at?: string | null;
  yaml_configured?: boolean;
  scraper_enabled?: boolean;
  rss_enabled?: boolean;
  yaml_note?: string | null;
  min_word_count?: number | null;
  listing_urls?: string[];
};

export type SourceUpdateInput = {
  is_active?: boolean;
  reliability_score?: number;
  source_type?: string;
  political_leaning?: string;
  ownership?: string;
  language?: string;
  scraper_enabled?: boolean;
  rss_enabled?: boolean;
  min_word_count?: number;
  note?: string;
  persist_to_yaml?: boolean;
};

export type ScraperPreflight = {
  source_name: string;
  source_url?: string | null;
  scraper_enabled: boolean;
  rss_enabled: boolean;
  discovered_urls: number;
  success_count: number;
  failed_count: number;
  average_word_count: number;
  min_word_count?: number;
  max_word_count?: number;
  status: string;
  error_sample?: string | null;
  sample_urls: string[];
  failed_urls?: string[];
  failure_details?: Array<{
    url: string;
    error?: string | null;
    title?: string | null;
    word_count?: number;
  }>;
  suggested_fix: string;
};

export type SourceDrilldown = {
  source?: (SourceStat & { rss_feeds?: string[]; last_fetched_at?: string | null }) | null;
  suggested_fix: string;
  latest_error?: string | null;
  recent_runs: Array<{
    id: number;
    run_id: number;
    status: string;
    checked_at: string;
    discovered_urls: number;
    scraped_count: number;
    rss_count: number;
    raw_count: number;
    new_count: number;
    duplicate_count: number;
    duplicate_fuzzy_count: number;
    duplicate_streak: number;
    stopped_early: boolean;
    error_count: number;
    failed_count: number;
    average_word_count: number;
    error_sample?: string | null;
  }>;
};

export type BackupStatus = {
  database_url: string;
  backup_dir: string;
  latest?: BackupItem | null;
  backups: BackupItem[];
  restore_note: string;
};

export type BackupItem = {
  filename: string;
  path: string;
  size_bytes: number;
  created_at: string;
};

export type LaunchChecklist = {
  country_code: string;
  overall: string;
  checks: Array<{ key: string; label: string; status: string; detail: string }>;
};

export type TimelinePoint = {
  date: string;
  article_count: number;
  source_count: number;
  date_basis: string;
};

export type Narrative = {
  narrative: string;
  article_count: number;
  source_count: number;
  latest_at?: string | null;
  examples: Array<{
    article_id: number;
    title: string;
    url: string;
    source_name: string;
    published_at?: string | null;
  }>;
};

export type Client = {
  id: number;
  name: string;
  email?: string | null;
  client_type: string;
  plan: string;
  country_code: string;
  language: string;
  risk_tolerance: string;
  is_active: boolean;
  settings: Record<string, unknown>;
  created_at: string;
};

export type User = {
  id: number;
  email: string;
  name: string;
  role: string;
  client_id?: number | null;
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
};

export type UserInput = {
  email: string;
  name: string;
  password: string;
  role: string;
  client_id?: number | null;
  is_active: boolean;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
};

export type WatchlistItem = {
  id: number;
  client_id: number;
  item_type: string;
  label: string;
  value: string;
  entity_id?: number | null;
  source_id?: number | null;
  facebook_page_url?: string | null;
  priority: number;
  alert_enabled: boolean;
  response_assist_enabled: boolean;
  notes?: string | null;
  created_at: string;
};

export type ClientInput = {
  name: string;
  email?: string;
  client_type: string;
  plan: string;
  country_code: string;
  language: string;
  risk_tolerance: string;
  settings: Record<string, unknown>;
};

export type WatchlistItemInput = {
  item_type: string;
  label: string;
  value: string;
  entity_id?: number | null;
  source_id?: number | null;
  facebook_page_url?: string;
  priority: number;
  alert_enabled: boolean;
  response_assist_enabled: boolean;
  notes?: string;
};

export type AttackDetail = {
  is_attack: boolean;
  target?: string | null;
  attacker?: string | null;
  allegation?: string | null;
  quote?: string | null;
  categories: string[];
  confidence: number;
  confidence_label: string;
  extraction_basis: string[];
  article_id: number;
  title: string;
  url: string;
  reported_by: string;
  source_type: string;
  reliability_score?: number | null;
  published_at?: string | null;
  spread?: string;
  spread_article_count?: number;
  spread_source_count?: number;
  review_id?: number | null;
  review_status?: "unreviewed" | "confirmed" | "rejected" | "corrected" | string;
  review_notes?: string | null;
};

export type AttackReviewQueue = {
  country_code: string;
  period_days: number;
  summary: {
    total: number;
    unreviewed: number;
    confirmed: number;
    rejected: number;
    corrected: number;
  };
  candidates: Array<{
    review_id?: number | null;
    review_status: string;
    review_notes?: string | null;
    client_id: number;
    client_name: string;
    watchlist_item_id: number;
    watchlist_label: string;
    article_id: number;
    title: string;
    url: string;
    source_name: string;
    published_at?: string | null;
    attacker?: string | null;
    target?: string | null;
    allegation?: string | null;
    quote?: string | null;
    categories: string[];
    confidence: number;
    confidence_label: string;
    extraction_basis: string[];
  }>;
};

export type RiskItem = {
  watchlist_item_id: number;
  label: string;
  item_type: string;
  severity: string;
  article_count: number;
  source_count: number;
  negative_count: number;
  attack_count: number;
  attack_categories?: Record<string, number>;
  attack_details?: AttackDetail[];
  mention_count: number;
  latest_at?: string | null;
  recommended_action: string;
  response_assist_enabled: boolean;
};

export type AttackTimeline = {
  watchlist_item: WatchlistItem;
  period_days: number;
  event_count: number;
  source_count?: number;
  attack_event_count?: number;
  negative_event_count?: number;
  spread_label?: string;
  timeline_summary?: string;
  recommended_urgency?: string;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  first_seen?: {
    article_id: number;
    title: string;
    url: string;
    source_name: string;
    event_at?: string | null;
  } | null;
  amplifiers: Array<{ source_name: string; count: number }>;
  attack_categories: Record<string, number>;
  events: Array<{
    article_id: number;
    title: string;
    url: string;
    source_name: string;
    source_type: string;
    reliability_score?: number | null;
    published_at?: string | null;
    fetched_at?: string | null;
    event_at?: string | null;
    sentiment?: number | null;
    mention_count: number;
    attack_language: boolean;
    attack_categories: string[];
    attacker?: string | null;
    target?: string | null;
    allegation?: string | null;
    quote?: string | null;
    attack_confidence?: number | null;
    attack_confidence_label?: string | null;
    extraction_basis?: string[];
    ingestion_method: string;
    platform?: string | null;
  }>;
};

export type ClientDashboard = {
  client: Client;
  watchlist: WatchlistItem[];
  metrics: Record<string, number | string>;
  risk_items: RiskItem[];
  recent_articles: Article[];
};

export type SavedTopicWatch = {
  watchlist_item: WatchlistItem;
  period_days: number;
  article_count: number;
  source_count: number;
  validation_status: string;
  latest_at?: string | null;
  sources: string[];
  sample_articles: Article[];
  recommended_action: string;
};

export type ClientDailyBrief = {
  client: Client;
  generated_at: string;
  period_days: number;
  headline: string;
  summary: string;
  risk_items: RiskItem[];
  evidence_brief: EvidenceBriefItem[];
  recommended_actions: string[];
  matched_articles: Article[];
  copy_text: string;
};

export type ClientChatInput = {
  question: string;
  days?: number;
  mode?: string;
  include_wider_context?: boolean;
  conversation_id?: number;
};

export type ClientChatTurn = {
  id: number;
  role: "user" | "assistant" | string;
  content: string;
  citations: CitationItem[];
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ClientChatResponse = {
  client: Client;
  question: string;
  mode: string;
  conversation_id: number;
  turn_number: number;
  answer: string;
  summary: string;
  restrictions: string[];
  suggested_actions: string[];
  citations: CitationItem[];
  claims: Array<{
    text: string;
    citation_labels: string[];
    status: string;
    confidence?: number | null;
    requires_lawyer_review?: boolean;
  }>;
  legal_context: Array<Record<string, unknown>>;
  source_articles: Article[];
  matched_entities: Array<{
    entity_id: number;
    name: string;
    entity_type: string;
    mention_count: number;
    article_count: number;
  }>;
  confidence: BriefingConfidence;
  generation: {
    mode?: "ai" | "local" | string;
    provider?: string;
    model?: string | null;
    grounding_validated?: boolean;
    reason?: string;
  };
  retrieval: {
    engine?: string;
    query_terms?: string[];
    considered_count?: number;
    eligible_count?: number;
    returned_count?: number;
    source_count?: number;
    abstained?: boolean;
    abstention_reason?: string;
    top_results?: Array<Record<string, unknown>>;
  };
  history: ClientChatTurn[];
  saved_briefing_id?: number | null;
  disclaimer: string;
};

export type ClientUsage = {
  client: Client;
  plan: string;
  limits: Record<string, number>;
  usage: Record<string, number>;
  features: Record<string, boolean>;
};

export type PartyBriefingInput = {
  topic: string;
  objective?: string;
  requirements?: string;
  audience?: string;
  tone?: string;
  include_entities: string[];
  include_opponents: string[];
  include_legal_context: boolean;
  date_from?: string;
  date_to?: string;
  include_watchlist: boolean;
  max_articles: number;
};

export type GuidanceStrategy = {
  public_posture?: string;
  decision?: string;
  severity?: string;
  primary_line?: string;
  safe_opening?: string;
  opening_frame?: string;
  response_angle?: string;
  message_angle?: string;
  publication_gate?: string;
  tone_guidance?: string;
  evidence_to_use?: Array<{
    label?: string;
    source_name?: string;
    claim?: string;
    url?: string;
    safe_use?: string;
  }>;
  supported_claims?: string[];
  claims_to_avoid?: string[];
  questions_to_answer_before_publish?: string[];
  operator_notes?: string[];
};

export type PartyBriefing = {
  client: Client;
  topic: string;
  objective?: string | null;
  audience?: string | null;
  tone?: string | null;
  date_range: string;
  coverage_summary: string;
  verified_facts: EvidenceBriefItem[];
  single_source_claims: EvidenceBriefItem[];
  evidence_brief: EvidenceBriefItem[];
  citation_pack: CitationItem[];
  claim_support_matrix: ClaimSupportItem[];
  claims_to_verify: string[];
  confidence: BriefingConfidence;
  grounding_contract: GroundingContract;
  briefing_strategy: GuidanceStrategy;
  suggested_talking_points: string[];
  press_conference_outline: string[];
  draft_outputs: {
    press_statement?: string;
    short_social_response?: string;
    attack_rebuttal?: string;
    qa_prep?: Array<{ question: string; answer: string }>;
  };
  do_not_say_unless_verified: string[];
  risk_warnings: string[];
  legal_context: LegalContextItem[];
  source_articles: Article[];
  disclaimer: string;
};

export type ClaimSupportItem = {
  claim: string;
  status: string;
  supporting_article_count: number;
  supporting_source_count: number;
  supporting_article_ids: number[];
  legal_review_required: boolean;
  safe_use: string;
  evidence: EvidenceBriefItem[];
};

export type EvidenceBriefItem = {
  article_id: number;
  claim: string;
  source_name: string;
  source_type: string;
  reliability_score?: number | null;
  published_at?: string | null;
  url: string;
  use_in_briefing: string;
};

export type CitationItem = {
  label: string;
  inline: string;
  article_id?: number | null;
  claim?: string | null;
  source_name?: string | null;
  source_type?: string | null;
  reliability_score?: number | null;
  published_at?: string | null;
  url?: string | null;
  safe_use: string;
};

export type TopicBriefing = {
  query: string;
  generated_at: string;
  period_days: number;
  country_code: string;
  headline: string;
  summary: string;
  validation_status: string;
  article_count: number;
  source_count: number;
  timeline: Array<{ date: string; article_count: number; source_count: number }>;
  source_coverage: Array<{
    source_name: string;
    source_type: string;
    reliability_score?: number | null;
    article_count: number;
    latest_at?: string | null;
  }>;
  top_entities: Array<{
    entity_id: number;
    name: string;
    entity_type: string;
    mention_count: number;
    article_count: number;
  }>;
  evidence_brief: EvidenceBriefItem[];
  recent_articles: Article[];
  recommended_actions: string[];
};

export type BriefingConfidence = {
  level?: string;
  score?: number;
  article_count?: number;
  source_count?: number;
  official_legal_refs?: number;
  reason?: string;
};

export type GroundingContract = {
  decision?: string;
  public_use?: string;
  evidence_ready?: boolean;
  citation_ready?: boolean;
  legal_review_required?: boolean;
  article_count?: number;
  source_count?: number;
  citation_count?: number;
  unsupported_claim_count?: number;
  single_source_claim_count?: number;
  legal_review_count?: number;
  blocked_public_claims?: string[];
  caution_claims?: string[];
  rules?: string[];
};

export type LegalContextItem = {
  area: string;
  use_for: string;
  guidance: string;
  status: string;
  source_url?: string | null;
  article_refs?: string | null;
  confidence_score?: number;
  legal_basis_status?: string;
  requires_lawyer_review?: boolean;
  safe_use?: string;
  warning?: string;
};

export type ResponseDraft = {
  version_id?: string;
  tone: string;
  text: string;
  mk_text?: string;
  language?: string;
  use_case?: string;
  status?: string;
  public_readiness?: string;
  risk_level?: string;
};

export type ResponsePack = {
  client: Client;
  watchlist_item: WatchlistItem;
  severity: string;
  situation_summary: string;
  evidence_brief: EvidenceBriefItem[];
  citation_pack: CitationItem[];
  claim_support_matrix: ClaimSupportItem[];
  claims_to_verify: string[];
  confidence: BriefingConfidence;
  grounding_contract: GroundingContract;
  attack_analysis: {
    what_is_the_attack?: string;
    why_it_matters?: string;
    where_it_spread?: string;
    source_depth?: string;
    safest_response_angle?: string;
    historical_context_note?: string;
    top_sources?: string[];
    attack_categories?: Record<string, number>;
  };
  response_strategy: GuidanceStrategy;
  recommended_posture: string;
  legal_review_flags: string[];
  legal_context: LegalContextItem[];
  evidence_steps: string[];
  draft_responses: ResponseDraft[];
  source_articles: Article[];
  disclaimer: string;
};

export type Incident = {
  id: number;
  client_id: number;
  watchlist_item_id?: number | null;
  title: string;
  severity: string;
  status: string;
  summary?: string | null;
  recommended_posture?: string | null;
  legal_review_flags: string[];
  evidence_steps: string[];
  draft_responses: ResponseDraft[];
  source_article_ids: number[];
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
};

export type IncidentInput = {
  watchlist_item_id?: number | null;
  title: string;
  severity: string;
  status: string;
  summary?: string;
  recommended_posture?: string;
  legal_review_flags: string[];
  evidence_steps: string[];
  draft_responses: ResponseDraft[];
  source_article_ids: number[];
};

export type Evidence = {
  id: number;
  incident_id: number;
  article_id?: number | null;
  url: string;
  title?: string | null;
  source_name?: string | null;
  evidence_type: string;
  captured_at: string;
  published_at?: string | null;
  content_hash?: string | null;
  screenshot_path?: string | null;
  notes?: string | null;
};

export type EvidenceInput = {
  article_id?: number | null;
  url: string;
  title?: string;
  source_name?: string;
  evidence_type: string;
  published_at?: string;
  content_hash?: string;
  screenshot_path?: string;
  notes?: string;
};

export type FacebookPageMonitor = {
  id: number;
  name: string;
  url: string;
  page_handle?: string | null;
  page_id?: string | null;
  country_code: string;
  language: string;
  monitor_type: string;
  source_type: string;
  political_leaning: string;
  ownership?: string | null;
  reliability_score: number;
  is_active: boolean;
  last_fetched_at?: string | null;
  notes?: string | null;
  created_at: string;
};

export type FacebookPageMonitorInput = {
  name: string;
  url: string;
  page_handle?: string;
  page_id?: string;
  country_code: string;
  language: string;
  monitor_type: string;
  source_type: string;
  political_leaning: string;
  ownership?: string;
  reliability_score: number;
  is_active: boolean;
  notes?: string;
};

export type FacebookStatus = {
  country_code: string;
  token_configured: boolean;
  api_version: string;
  configured_pages: number;
  active_pages: number;
  never_fetched_pages: number;
  recent_facebook_posts_7d: number;
  latest_post?: Article | null;
};

export type FacebookFetchResult = {
  country_code: string;
  token_configured: boolean;
  raw_posts: number;
  ingestion: {
    total: number;
    new: number;
    duplicate: number;
    duplicate_fuzzy?: number;
    error: number;
  };
  processing: {
    processed: number;
    errors: number;
  };
};

export type ReportResponse = {
  report_id: number;
  file_path: string;
  article_count: number;
  categories: string[];
  date_range: string;
};

export type ReportItem = {
  id: number;
  title: string;
  country_code: string;
  format: string;
  categories_filter?: Record<string, unknown> | null;
  date_from: string;
  date_to: string;
  file_path?: string | null;
  article_count: number;
  created_at: string;
  download_url: string;
};

export type SubscriptionInput = {
  email: string;
  name?: string;
  country_code: string;
  categories?: string[] | null;
  frequency: string;
  format: string;
};

export type Subscription = SubscriptionInput & {
  id: number;
  is_active: boolean;
  last_sent_at?: string | null;
};

export type SavedBriefingInput = {
  briefing_type: string;
  title: string;
  country_code: string;
  topic?: string | null;
  entity_id?: number | null;
  watchlist_item_id?: number | null;
  report_id?: number | null;
  status?: string;
  folder?: string | null;
  tags?: string[];
  notes?: string | null;
  payload: Record<string, unknown>;
  source_article_ids: number[];
  confidence: Record<string, unknown>;
};

export type SavedBriefing = SavedBriefingInput & {
  id: number;
  client_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type LegalDocument = {
  id: number;
  title: string;
  country_code: string;
  legal_area: string;
  source_url?: string | null;
  source_name?: string | null;
  source_status: string;
  language: string;
  tags: string[];
  summary?: string | null;
  reference_text?: string | null;
  content_hash?: string | null;
  local_path?: string | null;
  downloaded_at?: string | null;
  text_length: number;
  article_refs?: string | null;
  confidence_score: number;
  date_accessed: string;
  verified_at?: string | null;
  notes?: string | null;
  created_at: string;
};

export type LegalDocumentInput = {
  title: string;
  country_code: string;
  legal_area: string;
  source_url?: string;
  source_name?: string;
  source_status: string;
  language: string;
  tags: string[];
  summary?: string;
  reference_text?: string;
  article_refs?: string;
  confidence_score: number;
  notes?: string;
};

export type LegalReviewInput = {
  decision: string;
  reviewer_name: string;
  reviewer_organization?: string;
  notes: string;
};

export type LegalReview = LegalReviewInput & {
  id: number;
  legal_document_id: number;
  reviewer_user_id?: number | null;
  status_before: string;
  status_after: string;
  reviewed_at: string;
  created_at: string;
};

export type LegalReviewAssignmentInput = {
  reviewer_name: string;
  reviewer_email?: string;
  reviewer_organization?: string;
  reviewer_jurisdiction?: string;
  qualification_reference?: string;
  scope: string;
  due_at?: string;
  notes?: string;
};

export type LegalReviewAssignment = LegalReviewAssignmentInput & {
  id: number;
  legal_document_id: number;
  assigned_by_user_id?: number | null;
  status: string;
  completed_at?: string | null;
  qualification_verified_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type LegalQuality = {
  country_code: string;
  status: string;
  total: number;
  status_counts: Record<string, number>;
  official_or_verified: number;
  lawyer_verified_count: number;
  needs_review_count: number;
  outdated_count: number;
  areas: Array<{ area: string; count: number }>;
  required_coverage: Array<{
    key: string;
    label: string;
    status: string;
    total_references: number;
    official_or_verified: number;
    needs_review: number;
    top_references: Array<{
      id: number;
      title: string;
      source_status: string;
      confidence_score: number;
    }>;
  }>;
  coverage_summary: {
    covered: number;
    research_lead: number;
    missing: number;
  };
  recommendations: string[];
};

export type IngestionRun = {
  id: number;
  country_code: string;
  run_type: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  total_sources: number;
  total_raw: number;
  total_new: number;
  total_duplicate: number;
  total_duplicate_fuzzy: number;
  total_error: number;
  notes?: string | null;
};

export type SchedulerStatus = {
  country_code: string;
  status: string;
  inferred_running: boolean;
  process?: {
    pid?: number | null;
    running: boolean;
    pid_file: string;
  };
  heartbeat?: {
    exists: boolean;
    path: string;
    age_minutes?: number | null;
    healthy: boolean;
    payload?: Record<string, unknown> | null;
    error?: string;
  };
  interval_minutes: number;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_run_id?: number | null;
  next_expected_run_at?: string | null;
  stale_minutes?: number | null;
  stale_warning: boolean;
  start_command: string;
  stop_hint: string;
  logs: {
    stdout: string;
    stderr: string;
  };
};

export type LiveOpsStatus = {
  country_code: string;
  overall: string;
  generated_at: string;
  target_interval_minutes: number;
  duplicate_stop_threshold: number;
  scheduler: {
    status?: string | null;
    process_running?: boolean;
    heartbeat_healthy?: boolean;
    heartbeat_age_minutes?: number | null;
    stale_minutes?: number | null;
    stale_warning?: boolean;
    next_expected_run_at?: string | null;
  };
  last_run?: IngestionSourceHealth["run"] | null;
  ingestion: {
    raw_total: number;
    new_total: number;
    duplicate_total: number;
    duplicate_rate: number;
    caught_up_sources: number;
    attention_sources: number;
    healthy_sources: number;
    rss_only_sources: number;
  };
  attention_sources: IngestionSourceHealth["sources"];
  caught_up_sources: IngestionSourceHealth["sources"];
  recommendations: string[];
};

export type ClientBriefReadiness = {
  client_id: number;
  client_name: string;
  client_type: string;
  plan: string;
  watchlist_items: number;
  matched_articles: number;
  source_count: number;
  risk_items: number;
  high_risk_items: number;
  ready: boolean;
  status: string;
  recommendation: string;
};

export type IngestionSourceHealth = {
  run?: {
    id: number;
    status: string;
    started_at: string;
    finished_at?: string | null;
    total_sources: number;
    total_raw: number;
    total_new: number;
    total_duplicate: number;
    total_duplicate_fuzzy: number;
    total_error: number;
  } | null;
  summary?: {
    latest_run_age_minutes?: number | null;
    healthy_count: number;
    caught_up_count: number;
    rss_only_count: number;
    attention_count: number;
    recommendations: string[];
  };
  sources: Array<{
    id: number;
    source_name: string;
    source_url?: string | null;
    source_type: string;
    scraper_enabled: boolean;
    rss_enabled: boolean;
    discovered_urls: number;
    scraped_count: number;
    rss_count: number;
    raw_count: number;
    checked_count: number;
    new_count: number;
    duplicate_count: number;
    duplicate_fuzzy_count: number;
    duplicate_streak: number;
    stopped_early: boolean;
    error_count: number;
    success_count: number;
    failed_count: number;
    average_word_count: number;
    status: string;
    error_sample?: string | null;
    checked_at: string;
  }>;
};

export type SourceReliability = {
  country_code: string;
  run_count: number;
  summary: {
    average_score: number;
    excellent_count: number;
    stable_count: number;
    watch_count: number;
    broken_count: number;
    recommendations: string[];
  };
  sources: Array<{
    source_name: string;
    source_url?: string | null;
    source_type: string;
    configured_reliability?: number | null;
    political_leaning: string;
    ownership?: string | null;
    score: number;
    status: string;
    attempts: number;
    healthy_runs: number;
    attention_runs: number;
    raw_total: number;
    new_total: number;
    duplicate_total: number;
    duplicate_rate: number;
    error_total: number;
    error_rate: number;
    stopped_early_runs: number;
    latest_status: string;
    latest_checked_at?: string | null;
    latest_error_sample?: string | null;
    recommendations: string[];
  }>;
};

export type SourceConfigValidation = {
  country_code: string;
  config_path: string;
  summary: {
    total_sources: number;
    healthy_count: number;
    warning_count: number;
    critical_count: number;
    disabled_count: number;
    db_only_count: number;
    issue_count: number;
  };
  recommendations: string[];
  sources: Array<{
    source_name: string;
    source_url?: string | null;
    db_source_id?: number | null;
    active: boolean;
    rss_enabled: boolean;
    rss_feed_count: number;
    scraper_enabled: boolean;
    listing_url_count: number;
    selector_count: number;
    critical_count: number;
    warning_count: number;
    status: string;
    issues: Array<{
      severity: string;
      field: string;
      message: string;
      suggested_fix: string;
    }>;
  }>;
  db_only_sources: string[];
};

export type SourceSyncResult = {
  country_code: string;
  created_count: number;
  updated_count: number;
  unchanged_count: number;
  created: Array<{ status: string; source_id?: number | null; name: string; url: string; changes: string[] }>;
  updated: Array<{ status: string; source_id?: number | null; name: string; url: string; changes: string[] }>;
  unchanged: Array<{ status: string; source_id?: number | null; name: string; url: string; changes: string[] }>;
  db_only_sources: string[];
  validation_summary: SourceConfigValidation["summary"];
};

export type OpsFixQueue = {
  country_code: string;
  generated_at: string;
  summary: {
    total: number;
    p0: number;
    p1: number;
    p2: number;
    by_area: Record<string, number>;
  };
  items: Array<{
    priority: string;
    area: string;
    title: string;
    detail: string;
    suggested_action: string;
    source_name?: string | null;
    source_url?: string | null;
    source_id?: number | null;
    source_stat_id?: number | null;
    article_id?: number | null;
    entity_id?: number | null;
    entity_type?: string | null;
    url?: string | null;
  }>;
};

export type ArticleQualityAudit = {
  country_code: string;
  method: string;
  issue_count: number;
  reason_counts: Record<string, number>;
  cleanup_command: string;
  issues: Array<{
    article_id: number;
    source_name: string;
    title: string;
    url: string;
    published_at?: string | null;
    ingested_at?: string | null;
    ingestion_method: string;
    word_count?: number | null;
    quality_status: string;
    quality_notes?: string | null;
    quality_reviewed_at?: string | null;
    reasons: string[];
  }>;
};

export type ArticleQualityReviewInput = {
  quality_status: "active" | "approved" | "needs_review" | "excluded";
  quality_notes?: string;
};

export type ArticleBulkExcludeResult = {
  checked: number;
  excluded: number;
  article_ids: number[];
};

export type IntelligenceQA = {
  country_code: string;
  generated_at: string;
  score: number;
  status: string;
  checks: Array<{
    key: string;
    label: string;
    status: string;
    detail: string;
    recommendation: string;
  }>;
  recommendations: string[];
  signals: {
    scheduler: Record<string, unknown>;
    sources: Record<string, unknown>;
    story_spread: Record<string, number>;
    article_quality: {
      issue_count: number;
      reason_counts: Record<string, number>;
    };
    entity_quality: {
      checked: number;
      suspicious_count: number;
      reason_counts: Record<string, number>;
    };
  };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("newsintel_token");
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  login: (email: string, password: string) =>
    post<LoginResponse>("/api/v1/auth/login", { email, password }),
  me: () => request<User>("/api/v1/auth/me"),
  logout: () => post<{ status: string }>("/api/v1/auth/logout", {}),
  users: () => request<User[]>("/api/v1/users"),
  createUser: (input: UserInput) => post<User>("/api/v1/users", input),
  health: () => request<{ status: string; timestamp: string }>("/health"),
  countries: () => request<Country[]>("/api/v1/countries"),
  articles: (params: URLSearchParams) =>
    request<ArticleListResponse>(`/api/v1/articles?${params.toString()}`),
  savedSearches: () => request<SavedSearch[]>("/api/v1/saved-searches"),
  createSavedSearch: (input: SavedSearchInput) =>
    post<SavedSearch>("/api/v1/saved-searches", input),
  updateSavedSearch: (searchId: number, input: Partial<SavedSearchInput>) =>
    patch<SavedSearch>(`/api/v1/saved-searches/${searchId}`, input),
  deleteSavedSearch: (searchId: number) =>
    request<{ status: string; id: number }>(`/api/v1/saved-searches/${searchId}`, { method: "DELETE" }),
  entities: (params: URLSearchParams) =>
    request<Entity[]>(`/api/v1/entities?${params.toString()}`),
  entityReviewQueue: (status = "") =>
    request<Entity[]>(`/api/v1/admin/entities/review?limit=80${status ? `&status=${encodeURIComponent(status)}` : ""}`),
  entityQualityReport: () =>
    request<EntityQualityReport>("/api/v1/admin/entities/quality-report?limit=500"),
  attackReviewQueue: () =>
    request<AttackReviewQueue>("/api/v1/admin/attacks/review?country_code=mk&days=30&status=all&limit=80"),
  reviewAttack: (
    watchlistItemId: number,
    articleId: number,
    input: { status: "confirmed" | "rejected" | "corrected"; notes?: string },
  ) => put<Record<string, unknown>>(
    `/api/v1/admin/attacks/review/${watchlistItemId}/${articleId}`,
    input,
  ),
  searchQuality: () =>
    request<SearchQuality>("/api/v1/admin/search/quality?country_code=mk"),
  entityLexiconCoverage: () =>
    request<EntityLexiconCoverage>("/api/v1/admin/entities/lexicon-coverage?country_code=mk&limit=20"),
  addEntityToLexicon: (entityId: number) =>
    post<EntityLexiconAddResult>(`/api/v1/admin/entities/${entityId}/add-to-lexicon?country_code=mk`, {
      aliases: [],
      approve_entity: true,
    }),
  updateEntity: (entityId: number, input: EntityReviewInput) =>
    patch<Entity>(`/api/v1/admin/entities/${entityId}`, input),
  bulkHideNoiseEntities: () =>
    post<EntityBulkHideResult>("/api/v1/admin/entities/bulk-hide-noise?limit=500", {}),
  mergeLexiconAliases: () =>
    post<{ merged: number; planned: number; checked_aliases: number; actions: Array<Record<string, unknown>> }>(
      "/api/v1/admin/entities/merge-lexicon-aliases?country_code=mk&limit=100",
      {},
    ),
  mergeEntity: (entityId: number, targetEntityId: number) =>
    post<Entity>(`/api/v1/admin/entities/${entityId}/merge`, { target_entity_id: targetEntityId }),
  entityArticles: (entityId: number) =>
    request<EntityDetail>(`/api/v1/entities/${entityId}/articles?limit=12`),
  entitySentiment: (entityId: number) =>
    request<EntitySentiment>(`/api/v1/entities/${entityId}/sentiment?days=90`),
  relatedEntities: (entityId: number) =>
    request<RelatedEntity[]>(`/api/v1/entities/${entityId}/related?limit=12`),
  entityBriefing: (entityId: number) =>
    request<EntityBriefing>(`/api/v1/entities/${entityId}/briefing?days=90`),
  generateEntityBriefingReport: (entityId: number) =>
    post<ReportResponse>(`/api/v1/entities/${entityId}/briefing/report?days=90`, {}),
  trends: () => request<Trend[]>("/api/v1/trends?days=90&limit=24"),
  topicBriefing: (query: string) =>
    request<TopicBriefing>(`/api/v1/topics/briefing?q=${encodeURIComponent(query)}&country_code=mk&days=90`),
  storyClusters: (options?: { days?: number; status?: string; limit?: number }) => {
    const query = new URLSearchParams({
      country_code: "mk",
      days: String(options?.days ?? 30),
      limit: String(options?.limit ?? 24),
    });
    if (options?.status) query.set("status", options.status);
    return request<StoryCluster[]>(`/api/v1/story-clusters?${query.toString()}`);
  },
  storySpread: () => request<StorySpread>("/api/v1/story-spread?country_code=mk&days=30&limit=12"),
  rebuildStoryClusters: () => post<{ articles_considered: number; clusters_created: number; cluster_links: number }>("/api/v1/admin/story-clusters/rebuild?country_code=mk&days=30&limit=1500", {}),
  politicalRisk: () => request<PoliticalRisk>("/api/v1/risk/political?country_code=mk&days=30"),
  dailyBrief: () => request<DailyBrief>("/api/v1/briefs/daily?country_code=mk&days=1"),
  clientRisk: (clientId: number) => request<PoliticalRisk>(`/api/v1/clients/${clientId}/risk?days=30`),
  categories: () => request<CategoryStat[]>("/api/v1/categories?days=90"),
  narratives: () => request<Narrative[]>("/api/v1/narratives?days=90&country_code=mk&limit=12"),
  clientNarratives: (clientId: number) =>
    request<Narrative[]>(`/api/v1/narratives?days=90&client_id=${clientId}&limit=12`),
  sources: () => request<SourceStat[]>("/api/v1/sources/stats?days=90"),
  timeline: (dateBasis = "published") =>
    request<TimelinePoint[]>(`/api/v1/timeline/daily?days=90&date_basis=${dateBasis}`),
  alerts: () => request<Alert[]>("/api/v1/alerts"),
  createAlert: (input: AlertInput) => post<Alert>("/api/v1/alerts/json", input),
  deleteAlert: (alertId: number) => request<{ status: string }>(`/api/v1/alerts/${alertId}`, { method: "DELETE" }),
  createRiskAlertSuggestion: (input: RiskAlertSuggestionInput) =>
    post<Alert>("/api/v1/alerts/from-risk-suggestion", input),
  clients: () => request<Client[]>("/api/v1/clients"),
  createClient: (input: ClientInput) => post<Client>("/api/v1/clients", input),
  clientDashboard: (clientId: number, days = 30) =>
    request<ClientDashboard>(`/api/v1/clients/${clientId}/dashboard?days=${days}`),
  clientSavedTopics: (clientId: number) =>
    request<SavedTopicWatch[]>(`/api/v1/clients/${clientId}/saved-topics?days=30`),
  clientDailyBrief: (clientId: number) =>
    request<ClientDailyBrief>(`/api/v1/clients/${clientId}/briefs/daily?days=1`),
  clientChat: (clientId: number, input: ClientChatInput) =>
    post<ClientChatResponse>(`/api/v1/clients/${clientId}/chat`, input),
  generateClientDailyBriefReport: (clientId: number) =>
    post<ReportResponse>(`/api/v1/clients/${clientId}/briefs/daily/report?days=1`, {}),
  clientUsage: (clientId: number) =>
    request<ClientUsage>(`/api/v1/clients/${clientId}/usage`),
  partyBriefing: (clientId: number, input: PartyBriefingInput) =>
    post<PartyBriefing>(`/api/v1/clients/${clientId}/party-briefing`, input),
  generatePartyBriefingReport: (clientId: number, input: PartyBriefingInput) =>
    post<ReportResponse>(`/api/v1/clients/${clientId}/party-briefing/report`, input),
  addWatchlistItem: (clientId: number, input: WatchlistItemInput) =>
    post<WatchlistItem>(`/api/v1/clients/${clientId}/watchlist`, input),
  responsePack: (clientId: number, watchlistItemId: number) =>
    request<ResponsePack>(`/api/v1/clients/${clientId}/response-pack/${watchlistItemId}?days=30`),
  attackTimeline: (clientId: number, watchlistItemId: number) =>
    request<AttackTimeline>(`/api/v1/clients/${clientId}/attack-timeline/${watchlistItemId}?days=30`),
  incidents: (clientId: number) =>
    request<Incident[]>(`/api/v1/clients/${clientId}/incidents`),
  createIncident: (clientId: number, input: IncidentInput) =>
    post<Incident>(`/api/v1/clients/${clientId}/incidents`, input),
  updateIncident: (clientId: number, incidentId: number, input: Partial<IncidentInput>) =>
    patch<Incident>(`/api/v1/clients/${clientId}/incidents/${incidentId}`, input),
  evidence: (clientId: number, incidentId: number) =>
    request<Evidence[]>(`/api/v1/clients/${clientId}/incidents/${incidentId}/evidence`),
  createEvidence: (clientId: number, incidentId: number, input: EvidenceInput) =>
    post<Evidence>(`/api/v1/clients/${clientId}/incidents/${incidentId}/evidence`, input),
  generateIncidentReport: (clientId: number, incidentId: number) =>
    post<ReportResponse>(`/api/v1/clients/${clientId}/incidents/${incidentId}/report`, {}),
  generateResponsePackReport: (clientId: number, watchlistItemId: number) =>
    post<ReportResponse>(`/api/v1/clients/${clientId}/response-pack/${watchlistItemId}/report`, {}),
  reports: (clientId?: number) =>
    request<ReportItem[]>(`/api/v1/reports?limit=20${clientId ? `&client_id=${clientId}` : ""}`),
  subscriptions: () => request<Subscription[]>("/api/v1/subscriptions?country_code=mk&limit=100"),
  createSubscription: (input: SubscriptionInput) => post<Subscription>("/api/v1/subscriptions", input),
  cancelSubscription: (subscriptionId: number) =>
    request<{ status: string }>(`/api/v1/subscriptions/${subscriptionId}`, { method: "DELETE" }),
  savedBriefings: (clientId: number) =>
    request<SavedBriefing[]>(`/api/v1/clients/${clientId}/saved-briefings?limit=30`),
  createSavedBriefing: (clientId: number, input: SavedBriefingInput) =>
    post<SavedBriefing>(`/api/v1/clients/${clientId}/saved-briefings`, input),
  savedBriefing: (clientId: number, briefingId: number) =>
    request<SavedBriefing>(`/api/v1/clients/${clientId}/saved-briefings/${briefingId}`),
  updateSavedBriefing: (clientId: number, briefingId: number, input: Partial<SavedBriefingInput>) =>
    patch<SavedBriefing>(`/api/v1/clients/${clientId}/saved-briefings/${briefingId}`, input),
  duplicateSavedBriefing: (clientId: number, briefingId: number) =>
    post<SavedBriefing>(`/api/v1/clients/${clientId}/saved-briefings/${briefingId}/duplicate`, {}),
  generateSavedBriefingReport: (clientId: number, briefingId: number) =>
    post<ReportResponse>(`/api/v1/clients/${clientId}/saved-briefings/${briefingId}/report`, {}),
  facebookPages: () => request<FacebookPageMonitor[]>("/api/v1/admin/facebook-pages"),
  createFacebookPage: (input: FacebookPageMonitorInput) =>
    post<FacebookPageMonitor>("/api/v1/admin/facebook-pages", input),
  facebookStatus: () => request<FacebookStatus>("/api/v1/admin/facebook/status?country_code=mk"),
  fetchFacebook: () => post<FacebookFetchResult>("/api/v1/admin/facebook/fetch?country_code=mk&process=true", {}),
  ingestionRuns: () => request<IngestionRun[]>("/api/v1/admin/ingestion/runs?country_code=mk&limit=5"),
  schedulerStatus: () => request<SchedulerStatus>("/api/v1/admin/scheduler/status?country_code=mk"),
  liveOps: () => request<LiveOpsStatus>("/api/v1/admin/live-ops?country_code=mk"),
  startScheduler: () => post<Record<string, unknown>>("/api/v1/admin/scheduler/start?country_code=mk&no_email=true", {}),
  stopScheduler: () => post<Record<string, unknown>>("/api/v1/admin/scheduler/stop", {}),
  runSchedulerOnce: () => post<Record<string, unknown>>("/api/v1/admin/scheduler/run-once?country_code=mk", {}),
  backups: () => request<BackupStatus>("/api/v1/admin/backups"),
  createBackup: () => post<BackupItem & { status: string }>("/api/v1/admin/backups/create", {}),
  restorePlan: (filename: string) =>
    post<{ backup: string; database: string; steps: string[] }>(`/api/v1/admin/backups/restore-plan?filename=${encodeURIComponent(filename)}`, {}),
  clientBriefReadiness: () => request<ClientBriefReadiness[]>("/api/v1/admin/clients/brief-readiness?days=1"),
  sourceHealth: () => request<IngestionSourceHealth>("/api/v1/admin/ingestion/source-health?country_code=mk"),
  sourceDrilldown: (sourceName: string) =>
    request<SourceDrilldown>(`/api/v1/admin/ingestion/source-health/${encodeURIComponent(sourceName)}?country_code=mk&limit=10`),
  sourceReliability: () => request<SourceReliability>("/api/v1/admin/ingestion/source-reliability?country_code=mk&runs=5"),
  sourceConfigValidation: () => request<SourceConfigValidation>("/api/v1/admin/sources/config-validation?country_code=mk"),
  syncSourcesFromConfig: () => post<SourceSyncResult>("/api/v1/admin/sources/sync-from-config?country_code=mk", {}),
  opsFixQueue: () => request<OpsFixQueue>("/api/v1/admin/ops/fix-queue?country_code=mk&limit=25"),
  updateSource: (sourceId: number, input: SourceUpdateInput) =>
    patch<SourceStat>(`/api/v1/admin/sources/${sourceId}`, input),
  sourcePreflight: (sourceId: number) =>
    post<ScraperPreflight>(`/api/v1/admin/sources/${sourceId}/scraper-preflight?max_articles=3`, {}),
  scraperPreflight: () =>
    post<{ country_code: string; summary: Record<string, number>; sources: ScraperPreflight[] }>(
      "/api/v1/admin/scrapers/preflight?country_code=mk&max_sources=6&max_articles=2",
      {},
    ),
  launchChecklist: () => request<LaunchChecklist>("/api/v1/admin/launch-checklist?country_code=mk"),
  articleQuality: () => request<ArticleQualityAudit>("/api/v1/admin/article-quality?country_code=mk&limit=12"),
  updateArticleQuality: (articleId: number, input: ArticleQualityReviewInput) =>
    patch<Article>(`/api/v1/admin/articles/${articleId}/quality`, input),
  bulkExcludeQualityArticles: () =>
    post<ArticleBulkExcludeResult>("/api/v1/admin/articles/bulk-exclude-quality?country_code=mk&method=all&limit=25", {}),
  intelligenceQA: () => request<IntelligenceQA>("/api/v1/admin/intelligence-qa?country_code=mk"),
  ingestNow: () => post<IngestResult>("/api/v1/ingest/mk", {}),
  processQueue: () => post<{ processed: number; errors: number }>("/api/v1/process?batch_size=200", {}),
  legalDocuments: (q = "") =>
    request<LegalDocument[]>(`/api/v1/legal-documents?country_code=mk&limit=50${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  legalQuality: () => request<LegalQuality>("/api/v1/admin/legal/quality?country_code=mk"),
  createLegalDocument: (input: LegalDocumentInput) =>
    post<LegalDocument>("/api/v1/legal-documents", input),
  reviewLegalDocument: (documentId: number, input: LegalReviewInput) =>
    post<LegalReview>(`/api/v1/admin/legal/${documentId}/reviews`, input),
  legalReviewHistory: (documentId: number) =>
    request<LegalReview[]>(`/api/v1/admin/legal/${documentId}/reviews`),
  assignLegalReview: (documentId: number, input: LegalReviewAssignmentInput) =>
    post<LegalReviewAssignment>(`/api/v1/admin/legal/${documentId}/assignments`, input),
};
