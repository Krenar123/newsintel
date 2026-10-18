import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  Bell,
  BookmarkPlus,
  BookOpenText,
  Brain,
  ChartNoAxesCombined,
  CircleDot,
  FileText,
  Gauge,
  Globe2,
  Newspaper,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  UsersRound,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Alert,
  API_BASE,
  Article,
  ArticleQualityAudit,
  AttackReviewQueue,
  AttackTimeline,
  BackupStatus,
  CategoryStat,
  Client,
  ClientChatResponse,
  ClientDashboard,
  ClientDailyBrief,
  ClientInput,
  Entity,
  EntityArticle,
  EntityLexiconCoverage,
  EntityQualityReport,
  EvidenceInput,
  FacebookPageMonitor,
  FacebookPageMonitorInput,
  FacebookFetchResult,
  FacebookStatus,
  GroundingContract,
  Incident,
  IngestionSourceHealth,
  IntelligenceQA,
  LaunchChecklist,
  LegalDocumentInput,
  LegalReviewAssignmentInput,
  LegalReviewInput,
  LegalQuality,
  LiveOpsStatus,
  Narrative,
  OpsFixQueue,
  PartyBriefing,
  PartyBriefingInput,
  PoliticalRisk,
  ResponseDraft,
  ResponsePack,
  SavedBriefing,
  SavedBriefingInput,
  SavedSearch,
  SearchQuality,
  SavedTopicWatch,
  ScraperPreflight,
  SourceConfigValidation,
  SourceStat,
  SourceDrilldown,
  SourceReliability,
  SourceUpdateInput,
  StoryCluster,
  StorySpread,
  Subscription,
  SubscriptionInput,
  TopicBriefing,
  Trend,
  User,
  UserInput,
  WatchlistItemInput,
  api,
} from "./api";
import {
  ClientPersonaWorkspace,
  PoliticalFigureWorkspace,
  clientMetricLabels,
  clientTabItems,
  type ClientTab,
  type ClientWorkspaceComponents,
} from "./clientWorkspaces";

type View = "overview" | "demo" | "admin" | "clients" | "articles" | "entities" | "sources" | "stories" | "trends" | "alerts";

const views: Array<{ id: View; label: string; icon: React.ComponentType<{ size?: number }> }> = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "demo", label: "War Room", icon: Activity },
  { id: "admin", label: "Admin", icon: Brain },
  { id: "clients", label: "Clients", icon: ShieldCheck },
  { id: "articles", label: "Articles", icon: Newspaper },
  { id: "entities", label: "Entities", icon: UsersRound },
  { id: "sources", label: "Sources", icon: Globe2 },
  { id: "stories", label: "Stories", icon: CircleDot },
  { id: "trends", label: "Trends", icon: ChartNoAxesCombined },
  { id: "alerts", label: "Alerts", icon: Bell },
];

function visibleViews(user?: User) {
  if (!user) return views;
  if (user.role === "admin") return views;
  if (user.role === "analyst") return views.filter((item) => item.id !== "admin");
  return views.filter((item) => ["clients", "articles", "entities", "stories", "trends", "alerts"].includes(item.id));
}

function navLabel(view: View, user?: User) {
  if (user?.role !== "client") return views.find((item) => item.id === view)?.label ?? "Workspace";
  const labels: Partial<Record<View, string>> = {
    clients: "My Dashboard",
    articles: "News",
    entities: "People & Orgs",
    stories: "Story Spread",
    trends: "Trends",
    alerts: "Alerts",
  };
  return labels[view] ?? views.find((item) => item.id === view)?.label ?? "Workspace";
}

const COLORS = ["#147c80", "#3f6fa9", "#d46255", "#c7912d", "#3d8b5f", "#6f5aa8"];

function params(input: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  Object.entries(input).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  return search;
}

function dateLabel(value?: string | null) {
  if (!value) return "No date";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function sentimentClass(value?: number | null) {
  if (value === null || value === undefined) return "neutral";
  if (value > 0.05) return "positive";
  if (value < -0.05) return "negative";
  return "neutral";
}

function Pill({ children, tone = "default" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function Panel({
  eyebrow,
  title,
  children,
  action,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-header">
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h3>{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function payloadText(payload: Record<string, unknown>, keys: string[], fallback = "No saved summary for this briefing.") {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return fallback;
}

function payloadList(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function payloadObjectList(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return Array.isArray(value) ? (value.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>>) : [];
}

function savedFinalStatement(payload: Record<string, unknown>) {
  if (typeof payload.final_statement === "string" && payload.final_statement.trim()) return payload.final_statement;
  const draftOutputs = payload.draft_outputs;
  if (draftOutputs && typeof draftOutputs === "object" && !Array.isArray(draftOutputs)) {
    const pressStatement = (draftOutputs as Record<string, unknown>).press_statement;
    if (typeof pressStatement === "string" && pressStatement.trim()) return pressStatement;
  }
  const draftResponses = payloadObjectList(payload, "draft_responses");
  const firstDraft = draftResponses.find((draft) => typeof draft.text === "string" && draft.text.trim());
  if (firstDraft && typeof firstDraft.text === "string") return firstDraft.text;
  if (typeof payload.copy_text === "string") return payload.copy_text;
  return "";
}

function SavedBriefingDetail({
  briefing,
  onClose,
  onUpdate,
  onDuplicate,
  onExport,
  status,
}: {
  briefing: SavedBriefing;
  onClose: () => void;
  onUpdate: (briefingId: number, input: Partial<SavedBriefingInput>) => void;
  onDuplicate: (briefingId: number) => void;
  onExport: (briefingId: number) => void;
  status?: string;
}) {
  const [title, setTitle] = useState(briefing.title);
  const [topic, setTopic] = useState(briefing.topic || "");
  const [briefingStatus, setBriefingStatus] = useState(briefing.status || "active");
  const [folder, setFolder] = useState(briefing.folder || "briefings");
  const [tags, setTags] = useState((briefing.tags || []).join(", "));
  const [notes, setNotes] = useState(briefing.notes || "");
  const [finalStatement, setFinalStatement] = useState(savedFinalStatement(briefing.payload));
  useEffect(() => {
    setTitle(briefing.title);
    setTopic(briefing.topic || "");
    setBriefingStatus(briefing.status || "active");
    setFolder(briefing.folder || "briefings");
    setTags((briefing.tags || []).join(", "));
    setNotes(briefing.notes || "");
    setFinalStatement(savedFinalStatement(briefing.payload));
  }, [briefing.id, briefing.title, briefing.topic, briefing.status, briefing.folder, briefing.tags, briefing.notes, briefing.payload]);
  const payload = briefing.payload;
  const groundingContract = payloadGroundingContract(payload);
  const evidence = payloadObjectList(payload, "evidence_brief");
  const citations = payloadObjectList(payload, "citation_pack");
  const claimSupport = payloadObjectList(payload, "claim_support_matrix");
  const legalContext = payloadObjectList(payload, "legal_context");
  const draftResponses = payloadObjectList(payload, "draft_responses") as ResponseDraft[];
  const suggestedPoints = [
    ...payloadList(payload, "suggested_talking_points"),
    ...payloadList(payload, "recommended_actions"),
    ...payloadList(payload, "claims_to_verify"),
  ].slice(0, 8);

  return (
    <Panel
      eyebrow="Saved Briefing"
      title={briefing.title}
      action={<button className="text-button" type="button" onClick={onClose}>Close</button>}
    >
      <div className="stack">
        <div className="source-config-controls">
          <label className="wide-control">
            Title
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="wide-control">
            Topic
            <input value={topic} onChange={(event) => setTopic(event.target.value)} />
          </label>
          <label>
            Folder
            <input value={folder} onChange={(event) => setFolder(event.target.value)} />
          </label>
          <label>
            Status
            <select value={briefingStatus} onChange={(event) => setBriefingStatus(event.target.value)}>
              <option value="active">Active</option>
              <option value="pinned">Pinned</option>
              <option value="archived">Archived</option>
            </select>
          </label>
          <label className="wide-control">
            Tags
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="press, economy, response"
            />
          </label>
          <label className="wide-control">
            Notes
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Internal prep notes for this briefing"
            />
          </label>
        </div>
        <div className="tag-row">
          <button
            className="text-button"
            type="button"
            onClick={() => onUpdate(briefing.id, {
              title,
              topic: topic || null,
              status: briefingStatus,
              folder: folder || "briefings",
              tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
              notes: notes || null,
            })}
          >
            Save Changes
          </button>
          <button className="text-button" type="button" onClick={() => onDuplicate(briefing.id)}>
            Duplicate Template
          </button>
          <button className="text-button" type="button" onClick={() => onExport(briefing.id)}>
            Export PDF
          </button>
        </div>
        {status ? <p className="muted">{status}</p> : null}
        <div className="card-meta">
          <Pill tone="gold">{briefing.briefing_type.replaceAll("_", " ")}</Pill>
          <Pill tone={briefing.status === "pinned" ? "green" : briefing.status === "archived" ? "coral" : undefined}>
            {briefing.status || "active"}
          </Pill>
          {briefing.folder ? <Pill>{briefing.folder}</Pill> : null}
          <Pill>{briefing.source_article_ids.length} source items</Pill>
          <Pill>{dateLabel(briefing.created_at)}</Pill>
          {briefing.topic ? <Pill>{briefing.topic}</Pill> : null}
          {groundingContract ? <Pill tone={contractTone(groundingContract.decision)}>{groundingContract.decision}</Pill> : null}
          {(briefing.tags || []).map((tag) => <Pill key={`${briefing.id}-${tag}`}>{tag}</Pill>)}
        </div>
        <GroundingContractPanel contract={groundingContract} compact />
        {briefing.notes ? <p className="muted">{briefing.notes}</p> : null}
        <div className="drawer-section">
          <p className="eyebrow">Client-Ready Statement</p>
          <textarea
            className="statement-editor"
            value={finalStatement}
            onChange={(event) => setFinalStatement(event.target.value)}
            placeholder="Finalize the version you want to reuse, export, or bring into a press briefing."
          />
          <div className="tag-row">
            <button
              className="text-button"
              type="button"
              onClick={() => onUpdate(briefing.id, { payload: { ...payload, final_statement: finalStatement } })}
            >
              Save Final Statement
            </button>
          </div>
        </div>
        <p>
          {payloadText(payload, [
            "summary",
            "coverage_summary",
            "situation_summary",
            "headline",
            "recommended_posture",
          ])}
        </p>
        {evidence.length ? (
          <div className="draft-list">
            {evidence.slice(0, 5).map((item, index) => (
              <article className="draft-card" key={`${briefing.id}-evidence-${index}`}>
                <div className="card-meta">
                  {typeof item.source_name === "string" ? <Pill>{item.source_name}</Pill> : null}
                  {typeof item.published_at === "string" ? <Pill tone="gold">{dateLabel(item.published_at)}</Pill> : null}
                </div>
                <p>{String(item.claim || item.title || item.use_in_briefing || "Saved evidence item")}</p>
              </article>
            ))}
          </div>
        ) : null}
        {suggestedPoints.length ? (
          <ul className="response-list">
            {suggestedPoints.map((point) => (
              <li key={`${briefing.id}-${point}`}>{point}</li>
            ))}
          </ul>
        ) : null}
        {draftResponses.length ? (
          <ResponseDraftVersionList
            drafts={draftResponses}
            language="en"
            onLanguageChange={() => undefined}
          />
        ) : null}
        {claimSupport.length ? (
          <div className="drawer-section">
            <p className="eyebrow">Claim Support</p>
            <div className="draft-list">
              {claimSupport.slice(0, 6).map((item, index) => (
                <article className="draft-card" key={`${briefing.id}-claim-${index}`}>
                  <div className="card-meta">
                    <Pill tone={item.status === "source_supported" ? "green" : item.status === "single_source" ? "gold" : "coral"}>
                      {String(item.status || "unknown").replaceAll("_", " ")}
                    </Pill>
                    <Pill>{String(item.supporting_source_count || 0)} sources</Pill>
                  </div>
                  <strong>{String(item.claim || "Saved claim")}</strong>
                  <p>{String(item.safe_use || "Verify before public use.")}</p>
                </article>
              ))}
            </div>
          </div>
        ) : null}
        {citations.length ? (
          <div className="drawer-section">
            <p className="eyebrow">Citation Trail</p>
            <div className="draft-list">
              {citations.slice(0, 6).map((item, index) => (
                <article className="draft-card" key={`${briefing.id}-citation-${index}`}>
                  <div className="card-meta">
                    <Pill tone="green">[{String(item.label || index + 1)}]</Pill>
                    {typeof item.source_name === "string" ? <Pill>{item.source_name}</Pill> : null}
                    {typeof item.published_at === "string" ? <Pill tone="gold">{dateLabel(item.published_at)}</Pill> : null}
                  </div>
                  <p>{String(item.claim || item.inline || "Saved citation")}</p>
                  {typeof item.url === "string" ? <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a> : null}
                </article>
              ))}
            </div>
          </div>
        ) : null}
        {legalContext.length ? (
          <div className="drawer-section">
            <p className="eyebrow">Legal Context Review</p>
            <div className="draft-list">
              {legalContext.slice(0, 5).map((item, index) => (
                <article className="draft-card" key={`${briefing.id}-legal-${index}`}>
                  <div className="card-meta">
                    <Pill tone={item.requires_lawyer_review ? "coral" : "gold"}>
                      {item.requires_lawyer_review ? "lawyer review" : String(item.status || "reference")}
                    </Pill>
                  </div>
                  <strong>{String(item.area || "Legal reference")}</strong>
                  <p>{String(item.safe_use || item.guidance || "Use only as a research lead until verified.")}</p>
                </article>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

function StoryClusterDetail({
  cluster,
  onClose,
  onCreateAlert,
}: {
  cluster: StoryCluster;
  onClose: () => void;
  onCreateAlert: (cluster: StoryCluster) => void;
}) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
        <div className="panel-header">
          <div>
            <p className="eyebrow">Cross-Source Validation</p>
            <h3>{cluster.title}</h3>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close story validation">
            X
          </button>
        </div>
        <div className="card-meta">
          <Pill tone={cluster.status === "validated" ? "green" : cluster.status === "multi_source" ? "gold" : "coral"}>
            {cluster.status.replaceAll("_", " ")}
          </Pill>
          <Pill>{cluster.original_source_count ?? cluster.source_count} original sources</Pill>
          {cluster.aggregator_source_count ? <Pill tone="gold">{cluster.aggregator_source_count} aggregator</Pill> : null}
          <Pill>{cluster.article_count} articles</Pill>
          <Pill>{cluster.high_reliability_source_count} high reliability</Pill>
          {cluster.spread_hours !== null && cluster.spread_hours !== undefined ? <Pill>{cluster.spread_hours}h spread</Pill> : null}
          <button className="text-button" type="button" onClick={() => onCreateAlert(cluster)}>
            Alert On Spread
          </button>
        </div>
        <div className="drawer-section">
          <p className="eyebrow">Validation Note</p>
          <p>{cluster.validation_explanation}</p>
          {cluster.risk_flags.length ? (
            <div className="tag-row">
              {cluster.risk_flags.map((flag) => <Pill tone="coral" key={flag}>{flag.replaceAll("_", " ")}</Pill>)}
            </div>
          ) : null}
        </div>
        <div className="drawer-section">
          <p className="eyebrow">Source Breakdown</p>
          <div className="source-list">
            {cluster.source_breakdown.map((source) => (
              <article className="source-card" key={`${cluster.id}-${source.source_id}`}>
                <div className="source-main">
                  <div>
                    <div className="card-meta">
                      <Pill tone={source.source_type === "aggregator" ? "gold" : undefined}>{source.source_type}</Pill>
                      <Pill>{source.political_leaning}</Pill>
                      <Pill tone="gold">{source.article_count} items</Pill>
                    </div>
                    <strong>{source.source_name}</strong>
                    <p>Latest: {dateLabel(source.latest_published_at)}</p>
                  </div>
                  <strong>{Math.round(source.reliability_score * 100)}%</strong>
                </div>
              </article>
            ))}
          </div>
        </div>
        <div className="drawer-section">
          <p className="eyebrow">Original Articles</p>
          <div className="draft-list">
            {cluster.articles.map((article) => (
              <article className="draft-card" key={article.article_id}>
                <div className="card-meta">
                  <Pill>{article.source_name}</Pill>
                  <Pill tone="gold">{dateLabel(article.published_at)}</Pill>
                  <Pill>{Math.round(article.similarity_score * 100)}% match</Pill>
                </div>
                <a href={article.url} target="_blank" rel="noreferrer">{article.title}</a>
              </article>
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}

function Metric({
  label,
  value,
  caption,
  icon: Icon,
  accent = false,
}: {
  label: string;
  value: number | string;
  caption: string;
  icon: React.ComponentType<{ size?: number }>;
  accent?: boolean;
}) {
  return (
    <article className={`metric ${accent ? "accent" : ""}`}>
      <div className="metric-top">
        <p>{label}</p>
        <Icon size={20} />
      </div>
      <strong>{value}</strong>
      <span>{caption}</span>
    </article>
  );
}

function ArticleCard({ article, onInspect }: { article: Article; onInspect?: (article: Article) => void }) {
  const summary = article.summaries?.[0]?.text || "No summary available yet.";

  return (
    <article className="article-card">
      <div className="card-meta">
        <Pill>{article.source_name}</Pill>
        <Pill tone="green">{article.ingestion_method}</Pill>
        {article.platform ? <Pill tone="green">{article.platform}</Pill> : null}
        <Pill tone="gold">Published {dateLabel(article.published_at)}</Pill>
        <Pill tone="default">Fetched {dateLabel(article.fetched_at)}</Pill>
        <Pill>{article.language}</Pill>
      </div>
      <a className="article-title" href={article.url} target="_blank" rel="noreferrer">
        {article.title}
      </a>
      <p>{summary}</p>
      <div className="tag-row">
        {article.categories.slice(0, 3).map((category) => (
          <Pill key={`${article.id}-${category.category}`} tone="coral">
            {category.category}
          </Pill>
        ))}
        {article.entities.slice(0, 5).map((entity) => (
          <Pill key={`${article.id}-${entity.entity_id}`}>{entity.name}</Pill>
        ))}
        {onInspect ? (
          <button className="text-button" onClick={() => onInspect(article)}>
            Inspect
          </button>
        ) : null}
      </div>
    </article>
  );
}

function EntityRows({
  entities,
  selectedId,
  onSelect,
}: {
  entities: Entity[];
  selectedId?: number;
  onSelect: (id: number) => void;
}) {
  if (!entities.length) return <div className="empty-state">No entities match the current filters.</div>;

  return (
    <div className="entity-table">
      {entities.map((entity) => (
        <button
          className={`entity-row ${selectedId === entity.id ? "is-active" : ""}`}
          key={entity.id}
          onClick={() => onSelect(entity.id)}
        >
          <strong>{entity.name}</strong>
          <div className="card-meta">
            <Pill>{entity.entity_type}</Pill>
            <Pill tone="gold">{entity.total_mentions} mentions</Pill>
          </div>
        </button>
      ))}
    </div>
  );
}

function TrendCard({ trend }: { trend: Trend }) {
  return (
    <article className="trend-card">
      <div>
        <div className="card-meta">
          <Pill>{trend.entity_type}</Pill>
          <Pill tone="green">{trend.trend_direction}</Pill>
        </div>
        <h3>{trend.name}</h3>
        <p>
          {trend.recent_mentions} mentions across {trend.recent_articles} recent articles. Previous period:{" "}
          {trend.previous_mentions}.
        </p>
      </div>
      <div className="trend-score">{trend.trend_score.toFixed(1)}</div>
    </article>
  );
}

function RiskPanel({
  risk,
  title,
  onCreateAlert,
  alertStatus,
}: {
  risk?: PoliticalRisk;
  title: string;
  onCreateAlert?: (suggestion: PoliticalRisk["alert_suggestions"][number]) => void;
  alertStatus?: string;
}) {
  const tone = risk?.level === "critical" || risk?.level === "high"
    ? "coral"
    : risk?.level === "medium"
    ? "gold"
    : "green";
  const breakdown = Object.entries(risk?.breakdown ?? {}).filter(([, value]) => value > 0);
  return (
    <Panel eyebrow="Risk" title={title} action={<Pill tone={tone}>{risk?.level || "loading"}</Pill>}>
      {risk ? (
        <div className="risk-block">
          <div className="risk-score">
            <strong>{risk.score}</strong>
            <span>/100</span>
          </div>
          {breakdown.length ? (
            <div className="risk-breakdown">
              {breakdown.map(([key, value]) => (
                <div className="risk-breakdown-row" key={key}>
                  <div>
                    <span>{key.replaceAll("_", " ")}</span>
                    <b>{value}</b>
                  </div>
                  <div className="risk-bar">
                    <span style={{ width: `${Math.min(100, Math.max(4, value * 4))}%` }} />
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          <div className="stack">
            {risk.drivers.slice(0, 5).map((driver) => (
              <p key={driver}>{driver}</p>
            ))}
          </div>
          {risk.events?.length ? (
            <div className="risk-events">
              <p className="eyebrow">Risk Events</p>
              {risk.events.slice(0, 4).map((event) => (
                <article className="risk-event" key={`${event.event_type}-${event.title}`}>
                  <div className="card-meta">
                    <Pill tone={event.severity === "high" ? "coral" : event.severity === "medium" ? "gold" : "green"}>
                      {event.severity}
                    </Pill>
                    <Pill>{event.event_type.replaceAll("_", " ")}</Pill>
                    {event.source_count ? <Pill>{event.source_count} sources</Pill> : null}
                  </div>
                  <strong>{event.title}</strong>
                  {event.why_it_matters ? <p>{event.why_it_matters}</p> : null}
                  {event.recommended_action ? <p className="muted">{event.recommended_action}</p> : null}
                </article>
              ))}
            </div>
          ) : null}
          {risk.alert_suggestions?.length ? (
            <div className="risk-alerts">
              <p className="eyebrow">Suggested Alerts</p>
              <div className="tag-row">
                {risk.alert_suggestions.map((suggestion) => (
                  <button
                    className="text-button risk-alert-button"
                    type="button"
                    onClick={() => onCreateAlert?.(suggestion)}
                    key={`${suggestion.type}-${suggestion.label}`}
                    disabled={!onCreateAlert}
                  >
                    <Bell size={14} />
                    {suggestion.label}
                  </button>
                ))}
              </div>
              {alertStatus ? <p className="muted">{alertStatus}</p> : null}
            </div>
          ) : null}
          {risk.items.length ? (
            <div className="article-list compact">
              {risk.items.slice(0, 4).map((item) => (
                <a className="text-button" href={item.url} target="_blank" rel="noreferrer" key={item.article_id}>
                  {item.source_name}: {item.title}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="empty-state">Risk score is loading.</div>
      )}
    </Panel>
  );
}

function AlertCard({ alert, onDeactivate }: { alert: Alert; onDeactivate?: (alertId: number) => void }) {
  return (
    <article className="alert-card">
      <div className="card-meta">
        <Pill>{alert.alert_type}</Pill>
        <Pill tone="gold">{alert.channel}</Pill>
        <Pill tone={alert.is_active ? "green" : "coral"}>{alert.is_active ? "active" : "inactive"}</Pill>
      </div>
      <h3>{alert.name}</h3>
      <p>{JSON.stringify(alert.criteria)}</p>
      {alert.is_active && onDeactivate ? (
        <button className="text-button" type="button" onClick={() => onDeactivate(alert.id)}>
          Deactivate
        </button>
      ) : null}
    </article>
  );
}

function SourceCard({ source }: { source: SourceStat }) {
  const processedRatio = source.article_count
    ? Math.round((source.processed_count / source.article_count) * 100)
    : 0;

  return (
    <article className="source-card">
      <div className="source-main">
        <div>
          <div className="card-meta">
            <Pill>{source.language || "unknown"}</Pill>
            <Pill tone="gold">{source.source_type}</Pill>
            <Pill tone={source.is_active ? "green" : "coral"}>
              {source.is_active ? "active" : "inactive"}
            </Pill>
          </div>
          <a href={source.url} target="_blank" rel="noreferrer">
            {source.name}
          </a>
        </div>
        <strong>{source.article_count}</strong>
      </div>
      <div className="source-bars">
        <div>
          <span>Processed</span>
          <b>{processedRatio}%</b>
        </div>
        <div className="sentiment-meter">
          <span style={{ width: `${Math.max(3, processedRatio)}%` }} />
        </div>
      </div>
      <p>
        Latest article: {dateLabel(source.latest_article_at)}
        {source.ownership ? ` · ${source.ownership}` : ""}
      </p>
    </article>
  );
}

function EntityDetailPanel({
  selectedId,
  activeClientId,
  currentUser,
  staffAccess,
}: {
  selectedId?: number;
  activeClientId?: number;
  currentUser?: User;
  staffAccess: boolean;
}) {
  const queryClient = useQueryClient();
  const [copyStatus, setCopyStatus] = useState("");
  const [reportStatus, setReportStatus] = useState("");
  const [saveStatus, setSaveStatus] = useState("");
  const [alertStatus, setAlertStatus] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const detailQuery = useQuery({
    queryKey: ["entity-detail", selectedId],
    queryFn: () => api.entityArticles(selectedId!),
    enabled: Boolean(selectedId),
  });
  const sentimentQuery = useQuery({
    queryKey: ["entity-sentiment", selectedId],
    queryFn: () => api.entitySentiment(selectedId!),
    enabled: Boolean(selectedId),
  });
  const relatedQuery = useQuery({
    queryKey: ["entity-related", selectedId],
    queryFn: () => api.relatedEntities(selectedId!),
    enabled: Boolean(selectedId),
  });
  const briefingQuery = useQuery({
    queryKey: ["entity-briefing", selectedId],
    queryFn: () => api.entityBriefing(selectedId!),
    enabled: Boolean(selectedId),
  });

  async function copyEntityBriefing() {
    if (!briefingQuery.data?.copy_text) return;
    try {
      await navigator.clipboard.writeText(briefingQuery.data.copy_text);
      setCopyStatus("Copied briefing");
    } catch {
      setCopyStatus("Copy failed");
    }
  }

  async function exportEntityBriefing() {
    if (!selectedId) return;
    setReportStatus("Generating PDF...");
    try {
      const report = await api.generateEntityBriefingReport(selectedId);
      window.open(`${API_BASE}/api/v1/reports/${report.report_id}/download`, "_blank", "noopener,noreferrer");
      setReportStatus(`PDF ready: report #${report.report_id}`);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    } catch (error) {
      setReportStatus(error instanceof Error ? error.message : "Could not generate entity PDF");
    }
  }

  async function saveEntityBriefing() {
    if (!activeClientId || !briefingQuery.data) {
      setSaveStatus("Select a client before saving an entity dossier.");
      return;
    }
    const briefing = briefingQuery.data;
    setSaveStatus("Saving dossier...");
    try {
      await api.createSavedBriefing(activeClientId, {
        briefing_type: "entity_dossier",
        title: `Entity Dossier - ${briefing.entity.name}`,
        country_code: "mk",
        topic: briefing.entity.name,
        entity_id: briefing.entity.id,
        payload: briefing as unknown as Record<string, unknown>,
        source_article_ids: briefing.source_articles.map((article) => article.id),
        confidence: {
          source_count: briefing.source_coverage.length,
          article_count: briefing.source_articles.length,
          sentiment: briefing.sentiment.label,
          story_clusters: briefing.story_clusters.length,
        },
      });
      setSaveStatus("Dossier saved to client briefing history.");
      queryClient.invalidateQueries({ queryKey: ["saved-briefings", activeClientId] });
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : "Could not save dossier");
    }
  }

  async function createEntityAlert(alertMode: "mention" | "negative" | "story_spread") {
    const entity = briefingQuery.data?.entity ?? detailQuery.data?.entity;
    if (!entity) return;
    setAlertStatus("Creating entity alert...");
    const criteria = alertMode === "story_spread"
      ? { entity_id: entity.id, min_sources: 2, source: "entity_dossier" }
      : alertMode === "negative"
        ? { entity_id: entity.id, sentiment_below: -0.05, attack_language: true, source: "entity_dossier" }
        : { entity_id: entity.id, source: "entity_dossier" };
    try {
      await api.createAlert({
        name: `${entity.name}: ${alertMode.replaceAll("_", " ")}`,
        user_email: currentUser?.email || "admin@newsintel.local",
        alert_type: alertMode === "story_spread" ? "story_spread" : "entity",
        channel: "in_app",
        criteria,
        country_code: "mk",
        cooldown_minutes: alertMode === "mention" ? 120 : 30,
      });
      setAlertStatus("Entity alert created.");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      setAlertStatus(error instanceof Error ? error.message : "Could not create alert");
    }
  }

  async function updateSelectedEntity(status: "approved" | "hidden" | "needs_review") {
    const entity = detailQuery.data?.entity;
    if (!entity) return;
    setReviewStatus("Updating entity...");
    try {
      await api.updateEntity(entity.id, {
        status,
        review_notes: status === "hidden"
          ? "Hidden from entity dossier because it was marked as noise."
          : status === "approved"
            ? "Approved from entity dossier."
            : "Marked for manual review from entity dossier.",
      });
      setReviewStatus(status === "hidden" ? "Entity hidden." : status === "approved" ? "Entity approved." : "Entity marked for review.");
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["entity-detail", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["entity-briefing", selectedId] });
    } catch (error) {
      setReviewStatus(error instanceof Error ? error.message : "Could not update entity");
    }
  }

  if (!selectedId) {
    return (
      <Panel title="Entity Inspector" eyebrow="Coverage" className="entity-detail">
        <div className="empty-state">Select an entity to inspect coverage, sentiment, and recent mentions.</div>
      </Panel>
    );
  }

  if (detailQuery.isLoading) {
    return (
      <Panel title="Entity Inspector" eyebrow="Coverage" className="entity-detail">
        <div className="empty-state">Loading entity coverage...</div>
      </Panel>
    );
  }

  const detail = detailQuery.data;
  if (!detail) {
    return (
      <Panel title="Entity Inspector" eyebrow="Coverage" className="entity-detail">
        <div className="empty-state">Entity details are unavailable.</div>
      </Panel>
    );
  }

  const sentiment = sentimentQuery.data;
  const briefing = briefingQuery.data;
  const score = sentiment?.overall_sentiment ?? 0;
  const timeline = briefing?.mention_timeline ?? [];
  const sourceCoverage = briefing?.source_coverage ?? [];

  return (
    <Panel
      title={detail.entity.name}
      eyebrow={detail.entity.entity_type}
      className="entity-detail"
      action={
        <div className="topbar-actions">
          <button className="text-button" onClick={copyEntityBriefing} disabled={!briefing?.copy_text}>
            Copy
          </button>
          <button className="text-button" onClick={exportEntityBriefing}>
            <FileText size={14} /> PDF
          </button>
          <button className="text-button" onClick={saveEntityBriefing} disabled={!activeClientId || !briefing}>
            Save
          </button>
          <Pill tone="gold">{detail.entity.total_mentions} mentions</Pill>
        </div>
      }
    >
      {briefing ? (
        <div className="dossier-hero">
          <div>
            <p className="eyebrow">Entity Dossier</p>
            <h3>{briefing.headline}</h3>
            <p>{briefing.summary}</p>
          </div>
          <div className="dossier-facts">
            <Pill>{dateLabel(detail.entity.first_seen_at)} first seen</Pill>
            <Pill>{dateLabel(detail.entity.last_seen_at)} last seen</Pill>
            <Pill tone={sentimentClass(briefing.sentiment.score)}>
              {briefing.sentiment.label} {briefing.sentiment.score.toFixed(2)}
            </Pill>
          </div>
          {copyStatus || reportStatus ? <p className="muted">{copyStatus || reportStatus}</p> : null}
          {saveStatus || alertStatus || reviewStatus ? <p className="muted">{saveStatus || alertStatus || reviewStatus}</p> : null}
        </div>
      ) : null}

      <div className="related-strip">
        <p className="eyebrow">Entity Actions</p>
        <div className="tag-row">
          <button className="text-button" type="button" onClick={() => createEntityAlert("mention")}>
            Alert Mentions
          </button>
          <button className="text-button" type="button" onClick={() => createEntityAlert("negative")}>
            Alert Negative
          </button>
          <button className="text-button" type="button" onClick={() => createEntityAlert("story_spread")}>
            Alert Story Spread
          </button>
          {staffAccess ? (
            <>
              <button className="text-button" type="button" onClick={() => updateSelectedEntity("approved")}>
                Approve
              </button>
              <button className="text-button" type="button" onClick={() => updateSelectedEntity("needs_review")}>
                Review
              </button>
              <button className="text-button" type="button" onClick={() => updateSelectedEntity("hidden")}>
                Hide Noise
              </button>
            </>
          ) : null}
        </div>
      </div>

      <div className="sentiment-card">
        <div>
          <p className="eyebrow">Sentiment</p>
          <strong className={sentimentClass(score)}>
            {sentiment?.sentiment_label ?? "neutral"} ({score.toFixed(2)})
          </strong>
        </div>
        <div className="sentiment-meter">
          <span style={{ width: `${Math.max(4, Math.min(100, (score + 1) * 50))}%` }} />
        </div>
      </div>

      {timeline.length ? (
        <div className="mini-chart">
          <p className="eyebrow">Mention Timeline</p>
          <ResponsiveContainer width="100%" height={170}>
            <BarChart data={timeline}>
              <CartesianGrid stroke="#e2e8ef" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis width={30} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip />
              <Bar dataKey="mentions" fill="#147c80" radius={[8, 8, 0, 0]} />
              <Bar dataKey="article_count" fill="#c7912d" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : null}

      {sentiment?.timeline?.length ? (
        <div className="mini-chart">
          <p className="eyebrow">Sentiment Trend</p>
          <ResponsiveContainer width="100%" height={170}>
            <LineChart data={sentiment.timeline}>
              <CartesianGrid stroke="#e2e8ef" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis width={30} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip />
              <Line type="monotone" dataKey="avg_sentiment" stroke="#147c80" strokeWidth={3} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : null}

      {relatedQuery.data?.length ? (
        <div className="related-strip">
          <p className="eyebrow">Often Mentioned Together</p>
          <div className="tag-row">
            {relatedQuery.data.map((entity) => (
              <Pill key={entity.entity_id} tone="gold">
                {entity.name} · {entity.shared_articles}
              </Pill>
            ))}
          </div>
        </div>
      ) : null}

      {sourceCoverage.length ? (
        <div className="related-strip">
          <p className="eyebrow">Source Coverage</p>
          <div className="tag-row">
            {sourceCoverage.slice(0, 10).map((source) => (
              <Pill key={source.source_name}>
                {source.source_name} - {source.article_count} articles
              </Pill>
            ))}
          </div>
        </div>
      ) : null}

      {briefing?.story_clusters?.length ? (
        <div className="related-strip">
          <p className="eyebrow">Story Clusters Involving This Entity</p>
          <div className="draft-list">
            {briefing.story_clusters.slice(0, 5).map((cluster) => (
              <article className="draft-card" key={`entity-cluster-${cluster.id}`}>
                <div className="card-meta">
                  <Pill tone={cluster.status === "validated" ? "green" : cluster.status === "multi_source" ? "gold" : "coral"}>
                    {cluster.status.replaceAll("_", " ")}
                  </Pill>
                  <Pill>{cluster.source_count} sources</Pill>
                  <Pill>{cluster.article_count} articles</Pill>
                  <Pill>{cluster.high_reliability_source_count} high reliability</Pill>
                </div>
                <strong>{cluster.title}</strong>
                <p>{cluster.validation_explanation}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {briefing?.evidence_brief?.length ? (
        <div className="related-strip">
          <p className="eyebrow">Evidence Brief</p>
          <div className="evidence-list">
            {briefing.evidence_brief.slice(0, 4).map((item) => (
              <article className="draft-card" key={`${item.article_id}-${item.source_name}`}>
                <div className="card-meta">
                  <Pill>{item.source_name}</Pill>
                  <Pill tone="gold">{dateLabel(item.published_at)}</Pill>
                </div>
                <a className="article-title" href={item.url} target="_blank" rel="noreferrer">
                  {item.claim}
                </a>
                <p>{item.use_in_briefing}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {briefing?.recommended_actions?.length ? (
        <div className="related-strip">
          <p className="eyebrow">Verification Notes</p>
          <ul className="response-list">
            {briefing.recommended_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="article-list compact">
        {detail.articles.map((article: EntityArticle) => (
          <article className="article-card" key={article.article_id}>
            <div className="card-meta">
              <Pill>{article.source_name}</Pill>
              <Pill tone="gold">{dateLabel(article.published_at)}</Pill>
              {article.sentiment !== null && article.sentiment !== undefined ? (
                <Pill tone={sentimentClass(article.sentiment)}>{article.sentiment.toFixed(2)}</Pill>
              ) : null}
            </div>
            <a className="article-title" href={article.url} target="_blank" rel="noreferrer">
              {article.title}
            </a>
            <p>{article.context || "No context snippet available."}</p>
          </article>
        ))}
      </div>
    </Panel>
  );
}

function CategoryBars({ categories }: { categories: CategoryStat[] }) {
  if (!categories.length) return <div className="empty-state">No category data yet.</div>;

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={categories} layout="vertical" margin={{ left: 4, right: 18, top: 4, bottom: 4 }}>
        <CartesianGrid stroke="#e2e8ef" horizontal={false} />
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="category" width={82} tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
        <Tooltip />
        <Bar dataKey="article_count" radius={[0, 8, 8, 0]}>
          {categories.map((_, index) => (
            <Cell key={index} fill={COLORS[index % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function ClientCard({
  client,
  selected,
  onSelect,
}: {
  client: Client;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  return (
    <button className={`client-card ${selected ? "is-active" : ""}`} onClick={() => onSelect(client.id)}>
      <div className="card-meta">
        <Pill tone="green">{client.plan}</Pill>
        <Pill>{client.client_type}</Pill>
      </div>
      <strong>{client.name}</strong>
      <span>{client.email || client.country_code.toUpperCase()}</span>
    </button>
  );
}

function clientTypeLabel(value?: string) {
  if (!value) return "Client";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

type PersonaConfig = {
  title: string;
  mission: string;
  primaryWorkflow: string;
  nextMove: string;
  successSignal: string;
  caution: string;
  workflows: string[];
  paidFeatures: string[];
  setupChecklist: string[];
};

function clientPersonaConfig(client?: Client): PersonaConfig {
  const fallback: PersonaConfig = {
    title: "Client Intelligence Workspace",
    mission: "Track the issues, entities, and sources this client cares about.",
    primaryWorkflow: "Add watchlist items, monitor risk, and turn sourced coverage into briefings or alerts.",
    nextMove: "Open the client dashboard and review the highest-risk watchlist item.",
    successSignal: "Client sees relevant coverage, clear source trails, and one exportable briefing.",
    caution: "Do not present weak single-source coverage as confirmed.",
    workflows: ["Watchlist monitoring", "Risk signals", "Source-backed briefings"],
    paidFeatures: ["Custom watchlists", "Alerts", "PDF exports"],
    setupChecklist: ["Add priority entities or topics", "Create alerts for critical items", "Review recent source coverage"],
  };
  if (!client) return fallback;

  const configs: Record<string, PersonaConfig> = {
    political_party: {
      title: "Party War Room",
      mission: "Help the party prepare sourced positions, press conferences, and rapid responses without overclaiming.",
      primaryWorkflow: "Start from a topic, generate a fact-grounded briefing, verify claims, export the PDF, then copy talking points.",
      nextMove: "Generate a party briefing for the press-conference topic and review claim support.",
      successSignal: "The team has an opening line, evidence bullets, Q&A prep, and do-not-say warnings.",
      caution: "Legal and corruption claims stay as review notes unless official sources support them.",
      workflows: ["Press conference briefing", "Opponent/topic monitoring", "Narrative and source spread", "Evidence-first response packs"],
      paidFeatures: ["Campaign war room", "Daily briefings", "Response assistant", "PDF exports", "Advanced alerts"],
      setupChecklist: ["Add party/opponent names", "Add campaign topics", "Create alerts for attack themes", "Keep legal references reviewed"],
    },
    political_figure: {
      title: "Political Figure Defense Desk",
      mission: "Protect a public figure by showing mentions, attacks, source trails, and safe response options.",
      primaryWorkflow: "Monitor mentions, open response packs for negative stories, save cases, preserve evidence, and export legal-review dossiers.",
      nextMove: "Open the strongest negative mention and generate a response pack before replying.",
      successSignal: "The figure sees what was said, who reported it, whether it spread, and how to answer safely.",
      caution: "Avoid personal counterattacks and preserve evidence before escalating.",
      workflows: ["Mention monitoring", "Attack timeline", "Response pack", "Evidence archive", "Case PDF"],
      paidFeatures: ["Political defense", "Response assistant", "Evidence archive", "In-app alerts", "Incident PDFs"],
      setupChecklist: ["Add official name variants", "Add opponents and attack keywords", "Create mention alerts", "Save serious cases"],
    },
    pr_agency: {
      title: "PR Agency Client Desk",
      mission: "Let an agency manage multiple reputational accounts and produce sourced reporting for clients.",
      primaryWorkflow: "Create one client per account, configure watchlists, monitor source spread, and export client-ready updates.",
      nextMove: "Review client readiness and export the most urgent sourced update.",
      successSignal: "Every account has watchlists, alerts, and a clear client-ready summary.",
      caution: "Keep agency reports source-backed and separate speculation from verified coverage.",
      workflows: ["Multi-client dashboards", "Source intelligence", "Sentiment shifts", "PDF exports"],
      paidFeatures: ["Multiple clients", "White-label reports", "Advanced alerts", "Source reliability context"],
      setupChecklist: ["Create client personas", "Add brand/person keywords", "Set alert thresholds", "Schedule daily reporting"],
    },
    journalist: {
      title: "Journalist Research Desk",
      mission: "Help journalists find story spread, source trails, timelines, and connected entities quickly.",
      primaryWorkflow: "Use search, story clusters, entity profiles, and source trails to build a reporting map.",
      nextMove: "Search the topic, inspect story spread, then open the key entity dossier.",
      successSignal: "The reporter can see timeline, source attribution, related entities, and single-source risks.",
      caution: "Treat platform summaries as research navigation, not as publishable copy.",
      workflows: ["Cross-source validation", "Entity dossiers", "Timeline research", "Source comparison"],
      paidFeatures: ["Research workspace", "Source attribution", "Knowledge graph", "Archive exports"],
      setupChecklist: ["Add beats/topics", "Track institutions", "Review single-source stories", "Follow entity connections"],
    },
    media_analyst: {
      title: "Media Analyst Console",
      mission: "Turn Macedonian media flow into trends, narratives, trust signals, and executive summaries.",
      primaryWorkflow: "Review daily brief, trend shifts, story clusters, and source health, then export analysis.",
      nextMove: "Compare trend shifts with story clusters and source reliability.",
      successSignal: "The analyst can explain what changed, where it spread, and which sources carried it.",
      caution: "Do not over-read sentiment until noisy entities and weak sources are reviewed.",
      workflows: ["Trend monitoring", "Narrative mapping", "Source reliability", "Daily digest"],
      paidFeatures: ["Narrative analytics", "Trend exports", "Source intelligence", "Briefing PDFs"],
      setupChecklist: ["Define topics", "Approve noisy entities", "Watch source health", "Review daily digest"],
    },
    business_risk: {
      title: "Business Risk Monitor",
      mission: "Track political, regulatory, corruption, and reputational signals that can affect companies or deals.",
      primaryWorkflow: "Monitor companies, institutions, officials, and regulatory topics, then create due-diligence briefs.",
      nextMove: "Open risk scoring and export evidence for the highest-risk company or institution.",
      successSignal: "Decision makers see source-backed risk drivers, dates, and citation trails.",
      caution: "Do not treat media allegations as proven legal or financial facts.",
      workflows: ["Entity monitoring", "Regulatory topics", "Risk score", "Evidence exports"],
      paidFeatures: ["Political risk scoring", "Due-diligence packs", "Advanced alerts", "PDF exports"],
      setupChecklist: ["Add target companies", "Add regulators/institutions", "Track corruption/legal topics", "Export evidence packs"],
    },
    diaspora: {
      title: "Diaspora Digest",
      mission: "Give people outside Macedonia a clear, sourced digest of what matters without needing to follow every portal.",
      primaryWorkflow: "Review the daily brief, top stories, trending entities, and explainers in the preferred language.",
      nextMove: "Open the daily brief and save topics for the next digest.",
      successSignal: "Reader gets a clear, sourced snapshot without needing to follow every portal.",
      caution: "Avoid jargon and keep links to original sources visible.",
      workflows: ["Daily digest", "Top stories", "Entity explainers", "Source links"],
      paidFeatures: ["Email digest", "Language preference", "Saved topics", "Brief PDFs"],
      setupChecklist: ["Pick language", "Add hometown/topics", "Track institutions", "Send daily digest"],
    },
  };
  return configs[client.client_type] ?? fallback;
}

function PersonaSwitcher({
  clients,
  activeClientId,
  onSelect,
}: {
  clients: Client[];
  activeClientId?: number;
  onSelect: (id: number) => void;
}) {
  const priority = ["political_party", "political_figure", "media_analyst", "journalist", "pr_agency", "business_risk", "diaspora"];
  const demoClients = [...clients].sort((left, right) => {
    const leftRank = priority.indexOf(left.client_type);
    const rightRank = priority.indexOf(right.client_type);
    return (leftRank === -1 ? 99 : leftRank) - (rightRank === -1 ? 99 : rightRank);
  });
  if (!demoClients.length) return null;

  return (
    <section className="persona-switcher" aria-label="Role dashboards">
      {demoClients.slice(0, 7).map((client) => {
        const config = clientPersonaConfig(client);
        const selected = activeClientId === client.id;
        return (
          <button
            className={`persona-tile ${selected ? "is-active" : ""}`}
            key={client.id}
            type="button"
            onClick={() => onSelect(client.id)}
          >
            <span>{clientTypeLabel(client.client_type)}</span>
            <strong>{config.title}</strong>
            <p>{config.nextMove}</p>
          </button>
        );
      })}
    </section>
  );
}

function PilotReadinessRibbon({
  scheduler,
  sourceHealth,
  articleQuality,
  intelligenceQA,
}: {
  scheduler?: import("./api").SchedulerStatus;
  sourceHealth?: IngestionSourceHealth;
  articleQuality?: ArticleQualityAudit;
  intelligenceQA?: IntelligenceQA;
}) {
  const items = [
    {
      label: "Freshness",
      value: scheduler?.stale_warning ? "Needs attention" : scheduler ? "Fresh enough" : "Checking",
      tone: scheduler?.stale_warning ? "coral" : scheduler ? "green" : "gold",
      detail: scheduler?.stale_minutes !== null && scheduler?.stale_minutes !== undefined
        ? `${scheduler.stale_minutes} min since run`
        : "Scheduler not measured yet",
    },
    {
      label: "Sources",
      value: sourceHealth?.summary ? `${sourceHealth.summary.healthy_count} healthy` : "Checking",
      tone: sourceHealth?.summary?.attention_count ? "gold" : sourceHealth?.summary ? "green" : "gold",
      detail: sourceHealth?.summary ? `${sourceHealth.summary.attention_count} need attention` : "Source health loading",
    },
    {
      label: "Article Quality",
      value: articleQuality ? `${articleQuality.issue_count} flags` : "Checking",
      tone: articleQuality?.issue_count ? "gold" : articleQuality ? "green" : "gold",
      detail: articleQuality ? "Review before client exports" : "Quality audit loading",
    },
    {
      label: "Demo QA",
      value: intelligenceQA ? `${intelligenceQA.score}/100` : "Checking",
      tone: (intelligenceQA?.score ?? 0) >= 80 ? "green" : "gold",
      detail: intelligenceQA?.status?.replaceAll("_", " ") || "Readiness score loading",
    },
  ];

  return (
    <section className="readiness-ribbon" aria-label="Pilot readiness">
      {items.map((item) => (
        <article className="readiness-item" key={item.label}>
          <Pill tone={item.tone}>{item.label}</Pill>
          <strong>{item.value}</strong>
          <span>{item.detail}</span>
        </article>
      ))}
    </section>
  );
}

function PersonaPanel({ client }: { client?: Client }) {
  const config = clientPersonaConfig(client);
  return (
    <Panel eyebrow="Persona Mode" title={config.title} className="span-2">
      <div className="stack">
        <p>{config.mission}</p>
        <div className="brief-grid">
          <article className="brief-item">
            <ShieldCheck size={20} />
            <strong>Primary workflow</strong>
            <p>{config.primaryWorkflow}</p>
          </article>
          <article className="brief-item">
            <Activity size={20} />
            <strong>What to show in demos</strong>
            <p>{config.workflows.slice(0, 3).join(", ")}</p>
          </article>
          <article className="brief-item">
            <Bell size={20} />
            <strong>Billable value</strong>
            <p>{config.paidFeatures.slice(0, 3).join(", ")}</p>
          </article>
        </div>
        <div className="tag-row">
          {config.workflows.map((item) => <Pill tone="gold" key={item}>{item}</Pill>)}
        </div>
        <div className="tag-row">
          {config.setupChecklist.map((item) => <Pill key={item}>{item}</Pill>)}
        </div>
      </div>
    </Panel>
  );
}

function workspaceModeConfig(user: User, client?: Client) {
  if (user.role === "admin") {
    return {
      eyebrow: "Admin Operations",
      title: "Platform Control Room",
      detail: "Source health, scheduler freshness, data quality, clients, backups, and launch readiness.",
      tags: ["Fix queue", "Source validation", "Scheduler", "Backups"],
      tone: "coral",
      nextMove: "Clear P0 fix-queue items, confirm scheduler freshness, then run smoke before a demo.",
      successSignal: "Sources are healthy, backups exist, legal/search quality is visible, and smoke is green.",
      caution: "Do not start a pilot without fresh ingestion, backups, and clean source validation.",
    };
  }
  if (user.role === "analyst") {
    return {
      eyebrow: "Analyst Workspace",
      title: "Research and Source Intelligence",
      detail: "Search topics, compare source spread, inspect entities, and prepare sourced analysis.",
      tags: ["Search", "Stories", "Entities", "Trends"],
      tone: "gold",
      nextMove: "Start with topic search, then compare story spread and entity dossiers.",
      successSignal: "Analysis has dates, sources, citations, and clear single-source warnings.",
      caution: "Do not treat summaries as facts without opening the original source trail.",
    };
  }
  const persona = clientPersonaConfig(client);
  return {
    eyebrow: client?.client_type?.replaceAll("_", " ") || "Client Workspace",
    title: persona.title,
    detail: persona.primaryWorkflow,
    tags: persona.workflows.slice(0, 4),
    tone: "green",
    nextMove: persona.nextMove,
    successSignal: persona.successSignal,
    caution: persona.caution,
  };
}

function WorkspaceModeStrip({ user, client }: { user: User; client?: Client }) {
  const mode = workspaceModeConfig(user, client);
  return (
    <section className="mode-strip">
      <div>
        <p className="eyebrow">{mode.eyebrow}</p>
        <strong>{mode.title}</strong>
        <p>{mode.detail}</p>
      </div>
      <div className="tag-row">
        {mode.tags.map((tag) => (
          <Pill tone={mode.tone} key={tag}>{tag}</Pill>
        ))}
      </div>
      <div className="mode-cues">
        <article>
          <span>Next move</span>
          <strong>{mode.nextMove}</strong>
        </article>
        <article>
          <span>Success signal</span>
          <strong>{mode.successSignal}</strong>
        </article>
        <article>
          <span>Caution</span>
          <strong>{mode.caution}</strong>
        </article>
      </div>
    </section>
  );
}

function PersonaCommandCenter({
  clientDash,
  dailyBrief,
  topicBriefing,
  sourceHealth,
  articleQuality,
  onDemoBriefing,
  onResponsePack,
  onTimeline,
  onSaveCase,
}: {
  clientDash?: ClientDashboard;
  dailyBrief?: ClientDailyBrief;
  topicBriefing?: TopicBriefing;
  sourceHealth?: IngestionSourceHealth;
  articleQuality?: ArticleQualityAudit;
  onDemoBriefing: (topic: string, objective: string, requirements: string) => void;
  onResponsePack: (watchlistItemId: number) => void;
  onTimeline: (watchlistItemId: number) => void;
  onSaveCase: (watchlistItemId: number) => void;
}) {
  const client = clientDash?.client;
  if (!client) {
    return (
      <Panel eyebrow="Dashboard Mode" title="Select a Client" className="span-2">
        <div className="empty-state">Choose a client persona to show the right operating dashboard.</div>
      </Panel>
    );
  }

  if (client.client_type === "political_party") {
    return (
      <Panel eyebrow="Party Dashboard" title="Press Conference Command Center" className="span-2">
        <div className="stack">
          <p>Start from a topic, check source spread, then create a factual briefing with claims to verify before anyone speaks publicly.</p>
          <div className="brief-grid">
            <article className="brief-item">
              <FileText size={20} />
              <strong>{dailyBrief?.evidence_brief.length ?? 0} evidence bullets</strong>
              <p>{dailyBrief?.evidence_brief[0]?.claim || "Generate a daily brief or enter a topic to build evidence."}</p>
            </article>
            <article className="brief-item">
              <CircleDot size={20} />
              <strong>{topicBriefing?.validation_status?.replaceAll("_", " ") || "topic validation"}</strong>
              <p>{topicBriefing?.headline || "Use global search to see if a topic is single-source or widely reported."}</p>
            </article>
            <article className="brief-item">
              <Bell size={20} />
              <strong>{clientDash.risk_items.length} response items</strong>
              <p>{clientDash.risk_items[0]?.recommended_action || "No urgent response item for this party."}</p>
            </article>
          </div>
          <div className="tag-row">
            <button className="text-button" type="button" onClick={() => onDemoBriefing("EU path and constitutional changes", "Prepare a sourced party position on the EU path", "Use stored sources only; mark legal and constitutional claims for review")}>
              EU Path Brief
            </button>
            <button className="text-button" type="button" onClick={() => onDemoBriefing("Judiciary and corruption", "Prepare a rule-of-law press conference frame", "Separate allegations from official proceedings and avoid unsupported accusations")}>
              Judiciary Brief
            </button>
            <button className="text-button" type="button" onClick={() => onDemoBriefing("Economy and living costs", "Prepare a public-facing message on economic pressure", "Use dates, sources, and avoid claims beyond stored evidence")}>
              Economy Brief
            </button>
          </div>
        </div>
      </Panel>
    );
  }

  if (client.client_type === "political_figure") {
    const targetName = client.name.replace(/Defense Desk/i, "").trim() || client.name;
    const topRisk = clientDash.risk_items[0];
    const attackCount = clientDash.risk_items.reduce((sum, item) => sum + item.attack_count, 0);
    const sourceCount = topRisk?.source_count ?? 0;
    return (
      <Panel eyebrow="Personal Defense Dashboard" title={`What is being said about ${targetName}?`} className="span-2 figure-command">
        <div className="figure-hero">
          <div>
            <p>
              This dashboard is personalized to the logged-in political figure. It watches their name,
              aliases, opponents, and attack-language themes across stored Macedonian news coverage.
            </p>
            <div className="tag-row">
              <Pill tone={topRisk?.severity === "critical" || topRisk?.severity === "high" ? "coral" : "green"}>
                {topRisk ? `${topRisk.severity} risk` : "No active risk"}
              </Pill>
              <Pill>{clientDash.metrics.matched_articles} recent mentions</Pill>
              <Pill>{sourceCount} sources</Pill>
              <Pill tone={attackCount ? "coral" : "green"}>{attackCount} attack signals</Pill>
            </div>
          </div>
          {topRisk ? (
            <div className="figure-action-card">
              <p className="eyebrow">Recommended now</p>
              <strong>{topRisk.recommended_action}</strong>
              <div className="tag-row">
                <button className="primary-button inline-action" type="button" onClick={() => onResponsePack(topRisk.watchlist_item_id)}>
                  Prepare Response
                </button>
                <button className="text-button" type="button" onClick={() => onTimeline(topRisk.watchlist_item_id)}>
                  View Spread
                </button>
                <button className="text-button" type="button" onClick={() => onSaveCase(topRisk.watchlist_item_id)}>
                  Save Case
                </button>
              </div>
            </div>
          ) : null}
        </div>
        <div className="figure-grid">
          <article className="figure-step">
            <UsersRound size={20} />
            <span>Mentions</span>
            <strong>{clientDash.metrics.matched_articles}</strong>
            <p>Articles matching the figure, aliases, or tracked topics in the selected window.</p>
          </article>
          <article className="figure-step">
            <Bell size={20} />
            <span>Attacks</span>
            <strong>{attackCount}</strong>
            <p>Attack-language signals such as scandal, resignation, corruption, or competence claims.</p>
          </article>
          <article className="figure-step">
            <Globe2 size={20} />
            <span>Spread</span>
            <strong>{sourceCount}</strong>
            <p>Sources carrying the strongest current risk item.</p>
          </article>
          <article className="figure-step">
            <BookOpenText size={20} />
            <span>Response</span>
            <strong>{topRisk ? "Ready" : "Monitor"}</strong>
            <p>Open a response pack before publishing a rebuttal or correction request.</p>
          </article>
        </div>
        <div className="stack">
          <div className="section-title-row">
            <div>
              <p className="eyebrow">Current risks</p>
              <h3>Items needing attention</h3>
            </div>
          </div>
          <div className="stack">
            {clientDash.risk_items.length ? clientDash.risk_items.slice(0, 3).map((item) => (
              <RiskCard
                item={item}
                key={item.watchlist_item_id}
                onResponsePack={onResponsePack}
                onTimeline={onTimeline}
                onSaveCase={onSaveCase}
              />
            )) : <div className="empty-state">No active attack or risk item detected for this figure.</div>}
          </div>
        </div>
      </Panel>
    );
  }

  if (client.client_type === "journalist" || client.client_type === "media_analyst") {
    return (
      <Panel eyebrow={client.client_type === "journalist" ? "Journalist Dashboard" : "Media Analyst Dashboard"} title="Research Desk" className="span-2">
        <div className="stack">
          <p>Use search as the entry point: it supports Macedonian Cyrillic and Latin input, then shows timeline, sources, connected entities, and evidence.</p>
          <div className="brief-grid">
            <article className="brief-item">
              <Search size={20} />
              <strong>{topicBriefing?.article_count ?? 0} topic matches</strong>
              <p>{topicBriefing?.headline || "Search for a person, party, institution, or issue."}</p>
            </article>
            <article className="brief-item">
              <Globe2 size={20} />
              <strong>{topicBriefing?.source_count ?? 0} sources</strong>
              <p>{topicBriefing?.validation_status?.replaceAll("_", " ") || "Source validation appears after search."}</p>
            </article>
            <article className="brief-item">
              <UsersRound size={20} />
              <strong>{topicBriefing?.top_entities.length ?? 0} connected entities</strong>
              <p>{topicBriefing?.top_entities[0]?.name || "Entity connections appear when a topic has matches."}</p>
            </article>
          </div>
          <div className="tag-row">
            {(topicBriefing?.recommended_actions ?? ["Search a topic to build a sourced timeline."]).map((item) => (
              <Pill tone="gold" key={item}>{item}</Pill>
            ))}
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel eyebrow="Dashboard Mode" title="Operational Snapshot" className="span-2">
      <div className="brief-grid">
        <article className="brief-item">
          <ShieldCheck size={20} />
          <strong>{clientDash.watchlist.length} tracked interests</strong>
          <p>Watchlist terms, entities, sources, and topics configured for this client.</p>
        </article>
        <article className="brief-item">
          <Newspaper size={20} />
          <strong>{clientDash.metrics.matched_articles} matches</strong>
          <p>Recent source-backed coverage for the selected client.</p>
        </article>
        <article className="brief-item">
          <Activity size={20} />
          <strong>{sourceHealth?.summary?.healthy_count ?? "-"} healthy sources</strong>
          <p>{articleQuality?.issue_count ?? 0} article quality items currently flagged.</p>
        </article>
      </div>
    </Panel>
  );
}

function DataFreshnessStrip({ status }: { status?: import("./api").SchedulerStatus }) {
  if (!status) return null;
  return (
    <Panel
      eyebrow="Data Freshness"
      title={status.stale_warning ? "Ingestion Needs Attention" : "Ingestion Fresh"}
      action={<Pill tone={status.stale_warning ? "coral" : "green"}>{status.status.replaceAll("_", " ")}</Pill>}
    >
      <div className="tag-row">
        <Pill>Last run {dateLabel(status.last_run_at)}</Pill>
        <Pill>Next expected {dateLabel(status.next_expected_run_at)}</Pill>
        <Pill>{status.interval_minutes} min interval</Pill>
        {status.stale_minutes !== null && status.stale_minutes !== undefined ? (
          <Pill tone={status.stale_warning ? "coral" : "gold"}>{status.stale_minutes} min since run</Pill>
        ) : null}
      </div>
      <p className="muted">{status.stale_warning ? "Start or check the scheduler before relying on latest coverage." : "Freshness looks acceptable for demo and monitoring workflows."}</p>
    </Panel>
  );
}

function RiskCard({
  item,
  onResponsePack,
  onTimeline,
  onSaveCase,
  onCreateAlert,
}: {
  item: ClientDashboard["risk_items"][number];
  onResponsePack?: (watchlistItemId: number) => void;
  onTimeline?: (watchlistItemId: number) => void;
  onSaveCase?: (watchlistItemId: number) => void;
  onCreateAlert?: (watchlistItemId: number) => void;
}) {
  const tone = item.severity === "critical" || item.severity === "high" ? "coral" : "gold";
  return (
    <article className="alert-card">
      <div className="card-meta">
        <Pill tone={tone}>{item.severity}</Pill>
        <Pill>{item.item_type}</Pill>
        {item.response_assist_enabled ? <Pill tone="green">response assist</Pill> : null}
      </div>
      <h3>{item.label}</h3>
      <p>{item.recommended_action}</p>
      <div className="card-meta">
        <Pill>{item.article_count} matches</Pill>
        <Pill>{item.source_count} sources</Pill>
        <Pill tone="coral">{item.attack_count} attack signals</Pill>
        {onResponsePack ? (
          <button className="text-button" onClick={() => onResponsePack(item.watchlist_item_id)}>
            Response Pack
          </button>
        ) : null}
        {onTimeline ? (
          <button className="text-button" onClick={() => onTimeline(item.watchlist_item_id)}>
            Timeline
          </button>
        ) : null}
        {onSaveCase ? (
          <button className="text-button" onClick={() => onSaveCase(item.watchlist_item_id)}>
            Save Case
          </button>
        ) : null}
        {onCreateAlert ? (
          <button className="text-button" onClick={() => onCreateAlert(item.watchlist_item_id)}>
            Create Alert
          </button>
        ) : null}
      </div>
      {item.attack_categories && Object.keys(item.attack_categories).length ? (
        <div className="tag-row">
          {Object.entries(item.attack_categories).map(([category, count]) => (
            <Pill key={category} tone="gold">{category.replaceAll("_", " ")} · {count}</Pill>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function IncidentCard({
  incident,
  onOpen,
}: {
  incident: Incident;
  onOpen?: (incident: Incident) => void;
}) {
  const tone = incident.severity === "critical" || incident.severity === "high" ? "coral" : "gold";
  return (
    <article className="alert-card">
      <div className="card-meta">
        <Pill tone={tone}>{incident.severity}</Pill>
        <Pill>{incident.status}</Pill>
        <Pill tone="gold">{dateLabel(incident.created_at)}</Pill>
      </div>
      <h3>{incident.title}</h3>
      <p>{incident.summary || "No summary saved."}</p>
      {onOpen ? (
        <button className="text-button" onClick={() => onOpen(incident)}>
          Open Case
        </button>
      ) : null}
    </article>
  );
}

function NarrativeCard({ narrative }: { narrative: Narrative }) {
  return (
    <article className="trend-card">
      <div>
        <div className="card-meta">
          <Pill tone="gold">{narrative.article_count} items</Pill>
          <Pill>{narrative.source_count} sources</Pill>
        </div>
        <h3>{narrative.narrative.replaceAll("_", " ")}</h3>
        {narrative.examples[0] ? (
          <a className="article-title" href={narrative.examples[0].url} target="_blank" rel="noreferrer">
            {narrative.examples[0].source_name}: {narrative.examples[0].title}
          </a>
        ) : null}
      </div>
      <div className="trend-score">{narrative.article_count}</div>
    </article>
  );
}

const dashboardProfiles = [
  {
    label: "Admin",
    title: "Platform Control Room",
    description: "Sources, scheduler, clients, quality, backups, and launch readiness.",
  },
  {
    label: "Party",
    title: "Party War Room",
    description: "Prepare press conferences, talking points, evidence, and Q&A.",
  },
  {
    label: "Political Figure",
    title: "Defense Desk",
    description: "Personalized mentions, attacks, response packs, cases, and evidence trails.",
  },
  {
    label: "PR Agency",
    title: "Client Desk",
    description: "Monitor client reputation, escalations, source spread, and response work.",
  },
  {
    label: "Journalist",
    title: "Research Desk",
    description: "Search topics, source spread, timelines, and connected entities.",
  },
  {
    label: "Media Analyst",
    title: "Analyst Console",
    description: "Trends, narratives, source intelligence, and daily summaries.",
  },
  {
    label: "Diaspora",
    title: "Daily Digest",
    description: "Simple view of top stories, sources, and saved topics.",
  },
];

function LoginScreen({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [selectedProfile, setSelectedProfile] = useState(dashboardProfiles[2]);
  const [status, setStatus] = useState("");

  async function signIn(loginEmail = email, loginPassword = password) {
    setStatus("Signing in...");
    try {
      const result = await api.login(loginEmail, loginPassword);
      localStorage.setItem("newsintel_token", result.access_token);
      localStorage.setItem("newsintel_user", JSON.stringify(result.user));
      setStatus("");
      onLogin(result.user);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Login failed");
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await signIn();
  }

  return (
    <main className="login-screen">
      <section className="login-hero">
        <div className="brand">
          <div className="brand-mark login-mark">NI</div>
          <div>
            <h1>NewsIntel</h1>
            <p>Balkan media intelligence</p>
          </div>
        </div>
        <div>
          <p className="eyebrow">Choose dashboard type</p>
          <h2>Pick the workspace, then sign in with your own account.</h2>
          <p>
            The dashboard type only explains what the user will see. Access is controlled by
            the email and password assigned to that person or organization.
          </p>
        </div>
        <div className="demo-login-grid">
          {dashboardProfiles.map((account) => (
            <button
              className={`demo-login-card ${selectedProfile.label === account.label ? "is-active" : ""}`}
              type="button"
              key={account.label}
              onClick={() => setSelectedProfile(account)}
            >
              <span>{account.label}</span>
              <strong>{account.title}</strong>
              <p>{account.description}</p>
            </button>
          ))}
        </div>
      </section>
      <form className="login-card" onSubmit={submit}>
        <div>
          <p className="eyebrow">Manual sign in</p>
          <h3>{selectedProfile.title}</h3>
          <p className="muted">Enter the credentials assigned to this user. Selecting a dashboard type does not grant access.</p>
        </div>
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@organization.com" />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button className="primary-button" type="submit">Sign In</button>
        {status ? <p className="muted">{status}</p> : null}
      </form>
    </main>
  );
}

const pressPrepTemplates = [
  {
    id: "factual_press_conference",
    label: "Factual Press Conference",
    objective: "Explain the party position using only sourced claims, dates, and official records.",
    requirements: "Prioritize multi-source claims, cite every factual point, separate opinion from verified facts, and list what still needs verification.",
    audience: "general public and journalists",
    tone: "statesmanlike",
    max_articles: 24,
  },
  {
    id: "attack_response",
    label: "Attack Response",
    objective: "Respond calmly to attacks without amplifying unsupported allegations.",
    requirements: "Identify the attack theme, preserve evidence, answer only source-supported claims, request correction where facts are unsupported, and avoid personal counterattacks.",
    audience: "media and supporters",
    tone: "firm but calm",
    max_articles: 20,
  },
  {
    id: "legal_review_hold",
    label: "Legal Review Hold",
    objective: "Prepare a holding statement while legal and factual review is still open.",
    requirements: "Avoid final legal conclusions, include citation-backed known facts, say what is being reviewed, and include clear legal-review warnings.",
    audience: "media, institutions, and public",
    tone: "careful and institutional",
    max_articles: 16,
  },
  {
    id: "campaign_announcement",
    label: "Campaign Announcement",
    objective: "Frame a proactive campaign message around current coverage and public concerns.",
    requirements: "Use recent coverage as context, avoid claiming public support without data, include concrete next steps, and prepare Q&A on likely criticism.",
    audience: "voters and local media",
    tone: "confident and constructive",
    max_articles: 20,
  },
];

function usageTone(value: number, limit?: number) {
  if (!limit || limit === -1) return "green";
  const pct = value / limit;
  if (pct >= 1) return "coral";
  if (pct >= 0.8) return "gold";
  return "green";
}

const planCards = [
  { plan: "Basic", price: "€199/mo", features: ["News monitoring", "Basic alerts", "PDF digest"], bestFor: "small public-interest monitoring" },
  { plan: "Pro", price: "€499/mo", features: ["Sentiment", "Story spread", "Entity dossiers"], bestFor: "PR agencies and media analysts" },
  { plan: "Political Defense", price: "custom", features: ["Response packs", "Case files", "Evidence archive"], bestFor: "political figures" },
  { plan: "Campaign", price: "custom", features: ["War room", "Press briefing composer", "Daily readiness"], bestFor: "parties and campaigns" },
];

function PlanMatrix() {
  return (
    <div className="brief-grid">
      {planCards.map((plan) => (
        <article className="brief-item" key={plan.plan}>
          <Pill tone="gold">{plan.price}</Pill>
          <strong>{plan.plan}</strong>
          <p>{plan.bestFor}</p>
          <div className="tag-row">
            {plan.features.map((feature) => <Pill key={`${plan.plan}-${feature}`}>{feature}</Pill>)}
          </div>
        </article>
      ))}
    </div>
  );
}

function SafetyNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "empty-state" : "drawer-section"}>
      <p className="eyebrow">Use Guardrails</p>
      <p className="muted">
        Outputs are intelligence drafts grounded in stored sources. Verify original URLs, dates, numbers, and legal claims before external use. Legal context is a research aid, not legal advice.
      </p>
    </div>
  );
}

function readinessTone(status: "pass" | "warn" | "stop") {
  if (status === "pass") return "green";
  if (status === "warn") return "gold";
  return "coral";
}

function BriefingReadinessPanel({ briefing }: { briefing: PartyBriefing }) {
  const unsupportedClaims = briefing.claim_support_matrix.filter((item) => item.status === "unsupported_by_current_data");
  const singleSourceClaims = briefing.claim_support_matrix.filter((item) => item.status === "single_source");
  const legalReviewClaims = briefing.claim_support_matrix.filter((item) => item.legal_review_required);
  const legalReviewRefs = briefing.legal_context.filter((item) => item.requires_lawyer_review);
  const sourceCount = briefing.confidence.source_count ?? 0;
  const articleCount = briefing.confidence.article_count ?? 0;
  const evidenceReady = sourceCount >= 2 && articleCount >= 3;
  const citationReady = briefing.citation_pack.length > 0;
  const verificationLoad = unsupportedClaims.length + singleSourceClaims.length + briefing.claims_to_verify.length;
  const legalLoad = legalReviewClaims.length + legalReviewRefs.length;
  const stopCount = unsupportedClaims.length + legalReviewClaims.length;
  const decision =
    stopCount > 0
      ? "Use as internal prep until verification/legal review is complete."
      : verificationLoad > 0 || legalLoad > 0 || !evidenceReady
        ? "Use a cautious briefing frame and label open items clearly."
        : "Ready for a sourced press-prep draft.";
  const decisionTone = stopCount > 0 ? "coral" : verificationLoad > 0 || legalLoad > 0 || !evidenceReady ? "gold" : "green";
  const checks = [
    {
      label: "Evidence depth",
      value: `${articleCount} articles / ${sourceCount} sources`,
      status: evidenceReady ? "pass" : "warn",
      detail: evidenceReady ? "Enough source depth for a briefing frame." : "Use broader terms or ingest more before making strong claims.",
    },
    {
      label: "Citation trail",
      value: `${briefing.citation_pack.length} citations`,
      status: citationReady ? "pass" : "warn",
      detail: citationReady ? "Every public claim should point to these sources." : "No citation pack is available for this briefing.",
    },
    {
      label: "Claim support",
      value: `${unsupportedClaims.length} unsupported, ${singleSourceClaims.length} single-source`,
      status: unsupportedClaims.length ? "stop" : singleSourceClaims.length ? "warn" : "pass",
      detail: unsupportedClaims.length ? "Do not say unsupported claims externally." : "Single-source claims need careful wording.",
    },
    {
      label: "Legal posture",
      value: `${legalLoad} review flags`,
      status: legalLoad ? "warn" : "pass",
      detail: legalLoad ? "Keep legal language as review guidance, not a conclusion." : "No extra legal-review flags in this pack.",
    },
  ] as const;

  return (
    <div className="decision-panel">
      <div className="decision-summary">
        <div>
          <p className="eyebrow">Briefing Readiness</p>
          <h3>{decision}</h3>
          {briefing.confidence.reason ? <p>{briefing.confidence.reason}</p> : null}
        </div>
        <Pill tone={decisionTone}>Confidence {briefing.confidence.score ?? "-"} / 100</Pill>
      </div>
      <div className="decision-grid">
        {checks.map((check) => (
          <article className={`decision-step ${check.status}`} key={check.label}>
            <Pill tone={readinessTone(check.status)}>{check.label}</Pill>
            <strong>{check.value}</strong>
            <p>{check.detail}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function PartyBriefingStrategyPanel({ briefing }: { briefing: PartyBriefing }) {
  const strategy = briefing.briefing_strategy || {};
  const evidence = strategy.evidence_to_use ?? [];
  const avoid = strategy.claims_to_avoid ?? [];
  const questions = strategy.questions_to_answer_before_publish ?? [];
  const notes = strategy.operator_notes ?? [];
  const tone =
    strategy.decision === "hold" || strategy.public_posture?.toLowerCase().includes("internal")
      ? "coral"
      : strategy.decision === "ready"
        ? "green"
        : "gold";

  return (
    <div className="drawer-section response-strategy-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Press Strategy</p>
          <h3>{strategy.public_posture || "Cautious press-conference frame"}</h3>
        </div>
        <Pill tone={tone}>{strategy.decision || "caution"}</Pill>
      </div>
      <div className="response-summary-grid">
        <article>
          <span>Primary line</span>
          <strong>{strategy.primary_line || briefing.objective || briefing.topic}</strong>
          <p>{strategy.opening_frame || briefing.coverage_summary}</p>
        </article>
        <article>
          <span>Message angle</span>
          <strong>{strategy.message_angle || "Lead with source-backed facts"}</strong>
          <p>{strategy.publication_gate || "Keep legal and factual claims tied to source evidence."}</p>
        </article>
      </div>
      {evidence.length ? (
        <div className="strategy-block">
          <strong>Evidence to use first</strong>
          <div className="mini-source-list">
            {evidence.map((item) => (
              <a href={item.url || "#"} target="_blank" rel="noreferrer" key={`${item.label}-${item.claim}`}>
                [{item.label}] {item.source_name}: {item.claim}
              </a>
            ))}
          </div>
        </div>
      ) : null}
      <div className="persona-two-column">
        <div className="strategy-block">
          <strong>Do not say yet</strong>
          <ul className="response-list">
            {avoid.length ? avoid.slice(0, 6).map((item) => <li key={item}>{item}</li>) : <li>No extra blocked claims returned.</li>}
          </ul>
        </div>
        <div className="strategy-block">
          <strong>Before the press conference</strong>
          <ul className="response-list">
            {questions.length ? questions.slice(0, 5).map((item) => <li key={item}>{item}</li>) : <li>Verify source links, dates, names, and legal wording.</li>}
          </ul>
        </div>
      </div>
      {notes.length ? (
        <div className="tag-row">
          {notes.slice(0, 4).map((item) => <Pill tone="gold" key={item}>{item}</Pill>)}
        </div>
      ) : null}
    </div>
  );
}

function ResponseDecisionGate({ pack }: { pack: ResponsePack }) {
  const sourceCount = pack.confidence.source_count ?? 0;
  const articleCount = pack.confidence.article_count ?? 0;
  const legalFlags = pack.legal_review_flags.length + pack.legal_context.filter((item) => item.requires_lawyer_review).length;
  const unsupportedClaims = pack.claim_support_matrix.filter((item) => item.status === "unsupported_by_current_data").length;
  const singleSourceClaims = pack.claim_support_matrix.filter((item) => item.status === "single_source").length;
  const hasDraft = pack.draft_responses.length > 0;
  const hasEvidence = pack.evidence_brief.length > 0 && pack.citation_pack.length > 0;
  const stopCount = unsupportedClaims + legalFlags;
  const decision =
    stopCount > 0
      ? "Hold public reply until legal/factual review is done."
      : !hasEvidence || sourceCount < 2
        ? "Use only a cautious holding response."
        : "Response draft is usable with citations attached.";
  const decisionTone = stopCount > 0 ? "coral" : !hasEvidence || sourceCount < 2 || singleSourceClaims ? "gold" : "green";
  const checks = [
    {
      label: "Evidence",
      value: `${articleCount} articles / ${sourceCount} sources`,
      status: hasEvidence && sourceCount >= 2 ? "pass" : "warn",
      detail: hasEvidence ? "Attach the citation pack to any response." : "No source-backed evidence is available.",
    },
    {
      label: "Open claims",
      value: `${pack.claims_to_verify.length} to verify`,
      status: pack.claims_to_verify.length ? "warn" : "pass",
      detail: pack.claims_to_verify.length ? "Keep these out of public copy." : "No extra verification items listed.",
    },
    {
      label: "Legal review",
      value: `${legalFlags} flags`,
      status: legalFlags ? "stop" : "pass",
      detail: legalFlags ? "Route to legal review before final wording." : "No legal review blockers listed.",
    },
    {
      label: "Draft status",
      value: hasDraft ? `${pack.draft_responses.length} drafts` : "No draft",
      status: hasDraft ? "pass" : "warn",
      detail: hasDraft ? "Use the lowest-risk tone first." : "Generate or write a response before exporting.",
    },
  ] as const;

  return (
    <div className="decision-panel">
      <div className="decision-summary">
        <div>
          <p className="eyebrow">Response Decision Gate</p>
          <h3>{decision}</h3>
          <p>{pack.recommended_posture}</p>
        </div>
        <Pill tone={decisionTone}>{pack.severity}</Pill>
      </div>
      <div className="decision-grid">
        {checks.map((check) => (
          <article className={`decision-step ${check.status}`} key={check.label}>
            <Pill tone={readinessTone(check.status)}>{check.label}</Pill>
            <strong>{check.value}</strong>
            <p>{check.detail}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function ResponseStrategyPanel({ pack }: { pack: ResponsePack }) {
  const strategy = pack.response_strategy || {};
  const evidence = strategy.evidence_to_use ?? [];
  const avoid = strategy.claims_to_avoid ?? [];
  const questions = strategy.questions_to_answer_before_publish ?? [];
  const notes = strategy.operator_notes ?? [];
  const tone =
    strategy.decision === "hold" || strategy.public_posture?.toLowerCase().includes("internal")
      ? "coral"
      : strategy.decision === "ready"
        ? "green"
        : "gold";

  return (
    <div className="drawer-section response-strategy-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Response Strategy</p>
          <h3>{strategy.public_posture || "Cautious response plan"}</h3>
        </div>
        <Pill tone={tone}>{strategy.decision || "caution"}</Pill>
      </div>
      <div className="response-summary-grid">
        <article>
          <span>Primary line</span>
          <strong>{strategy.primary_line || pack.recommended_posture}</strong>
          <p>{strategy.safe_opening || pack.situation_summary}</p>
        </article>
        <article>
          <span>Angle</span>
          <strong>{strategy.response_angle || "Use cited facts only"}</strong>
          <p>{strategy.publication_gate || "Keep stronger claims internal until reviewed."}</p>
        </article>
      </div>
      {evidence.length ? (
        <div className="strategy-block">
          <strong>Evidence to use</strong>
          <div className="mini-source-list">
            {evidence.map((item) => (
              <a href={item.url || "#"} target="_blank" rel="noreferrer" key={`${item.label}-${item.claim}`}>
                [{item.label}] {item.source_name}: {item.claim}
              </a>
            ))}
          </div>
        </div>
      ) : null}
      <div className="persona-two-column">
        <div className="strategy-block">
          <strong>Do not claim yet</strong>
          <ul className="response-list">
            {avoid.length ? avoid.slice(0, 6).map((item) => <li key={item}>{item}</li>) : <li>No extra avoid-list items returned.</li>}
          </ul>
        </div>
        <div className="strategy-block">
          <strong>Before publishing</strong>
          <ul className="response-list">
            {questions.length ? questions.slice(0, 5).map((item) => <li key={item}>{item}</li>) : <li>Verify source links and legal wording.</li>}
          </ul>
        </div>
      </div>
      {notes.length ? (
        <div className="tag-row">
          {notes.slice(0, 3).map((item) => <Pill tone="gold" key={item}>{item}</Pill>)}
        </div>
      ) : null}
    </div>
  );
}

function draftBody(draft: ResponseDraft, language: "en" | "mk") {
  if (language === "mk" && draft.mk_text?.trim()) return draft.mk_text;
  return draft.text || draft.mk_text || "";
}

function draftTone(status?: string) {
  if (status === "approved" || status === "public_ready") return "green";
  if (status === "legal_review" || status === "hold") return "coral";
  return "gold";
}

function ResponsePacketSummary({ pack, timeline }: { pack: ResponsePack; timeline?: AttackTimeline }) {
  const sourceCount = timeline?.source_count ?? pack.confidence.source_count ?? 0;
  const attackCount = timeline?.attack_event_count ?? 0;
  const spreadLabel = timeline?.spread_label?.replaceAll("_", " ") || (sourceCount > 1 ? "multi source" : "single source");
  const nextAction = pack.grounding_contract?.decision === "hold"
    ? "Do not publish a final reply until factual/legal review is complete."
    : pack.grounding_contract?.decision === "ready"
      ? "Use a cited, source-backed response and keep citation labels attached."
      : "Use a cautious holding line and keep stronger claims internal.";

  return (
    <div className="response-summary-grid">
      <article>
        <span>Decision</span>
        <strong>{pack.grounding_contract?.decision || "caution"}</strong>
        <p>{nextAction}</p>
      </article>
      <article>
        <span>Source Depth</span>
        <strong>{sourceCount} sources</strong>
        <p>{pack.confidence.article_count ?? 0} matched articles in the response window.</p>
      </article>
      <article>
        <span>Spread</span>
        <strong>{spreadLabel}</strong>
        <p>{timeline?.timeline_summary || "Open the timeline to see first-seen, amplifiers, and attack signals."}</p>
      </article>
      <article>
        <span>Risk</span>
        <strong>{pack.severity}</strong>
        <p>{attackCount ? `${attackCount} attack-language events detected.` : "No attack-language timeline loaded yet."}</p>
      </article>
    </div>
  );
}

function AttackTimelineContext({ timeline }: { timeline?: AttackTimeline }) {
  if (!timeline) return null;
  return (
    <div className="timeline-context">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Attack Spread Context</p>
          <h3>{timeline.spread_label?.replaceAll("_", " ") || "Timeline loaded"}</h3>
        </div>
        <Pill tone={timeline.attack_event_count ? "coral" : "gold"}>{timeline.attack_event_count ?? 0} attack signals</Pill>
      </div>
      <p>{timeline.timeline_summary || "Timeline context is loaded for this response pack."}</p>
      <div className="card-meta">
        <Pill>{timeline.event_count} events</Pill>
        <Pill>{timeline.source_count ?? timeline.amplifiers.length} sources</Pill>
        <Pill>First {dateLabel(timeline.first_seen_at || timeline.first_seen?.event_at)}</Pill>
        <Pill>Latest {dateLabel(timeline.last_seen_at)}</Pill>
      </div>
      {timeline.recommended_urgency ? <p className="muted">{timeline.recommended_urgency}</p> : null}
    </div>
  );
}

function ResponseDraftVersionList({
  drafts,
  language,
  onLanguageChange,
  onStatusChange,
  onCopy,
}: {
  drafts: ResponseDraft[];
  language: "en" | "mk";
  onLanguageChange: (language: "en" | "mk") => void;
  onStatusChange?: (draft: ResponseDraft, status: string) => void;
  onCopy?: (text: string) => void;
}) {
  if (!drafts.length) return <div className="empty-state">No draft responses available.</div>;
  return (
    <div className="draft-version-panel">
      <div className="draft-toolbar">
        <div>
          <p className="eyebrow">Draft Versions</p>
          <strong>Choose the safest public line from source-backed options.</strong>
        </div>
        <div className="status-row compact-status">
          <button className={`status-button ${language === "en" ? "is-active" : ""}`} onClick={() => onLanguageChange("en")}>
            English
          </button>
          <button className={`status-button ${language === "mk" ? "is-active" : ""}`} onClick={() => onLanguageChange("mk")}>
            Macedonian
          </button>
        </div>
      </div>
      <div className="draft-list">
        {drafts.map((draft) => {
          const key = draft.version_id || `${draft.tone}-${draft.text}`;
          const text = draftBody(draft, language);
          return (
            <article className="draft-card draft-version-card" key={key}>
              <div className="card-meta">
                <Pill tone={draftTone(draft.status)}>{draft.status?.replaceAll("_", " ") || "internal review"}</Pill>
                <Pill tone="gold">{draft.tone}</Pill>
                {draft.public_readiness ? <Pill>{draft.public_readiness.replaceAll("_", " ")}</Pill> : null}
                {draft.risk_level ? <Pill>{draft.risk_level}</Pill> : null}
              </div>
              {draft.use_case ? <p className="muted">{draft.use_case}</p> : null}
              <p>{text}</p>
              <div className="tag-row">
                {onStatusChange ? (
                  ["internal_review", "approved", "public_ready", "legal_review"].map((status) => (
                    <button
                      className={`status-button ${draft.status === status ? "is-active" : ""}`}
                      key={`${key}-${status}`}
                      type="button"
                      onClick={() => onStatusChange(draft, status)}
                    >
                      {status.replaceAll("_", " ")}
                    </button>
                  ))
                ) : null}
                {onCopy ? (
                  <button className="text-button" type="button" onClick={() => onCopy(text)}>
                    Copy Draft
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function contractTone(decision?: string) {
  if (decision === "ready") return "green";
  if (decision === "hold") return "coral";
  return "gold";
}

function GroundingContractPanel({ contract, compact = false }: { contract?: GroundingContract; compact?: boolean }) {
  if (!contract) return null;
  const decision = contract.decision || "caution";
  const checks = [
    {
      label: "Evidence",
      value: `${contract.article_count ?? 0} articles / ${contract.source_count ?? 0} sources`,
      status: contract.evidence_ready ? "pass" : "warn",
      detail: contract.evidence_ready ? "Enough source depth for a sourced draft." : "Use cautious language until more source depth exists.",
    },
    {
      label: "Citations",
      value: `${contract.citation_count ?? 0} citations`,
      status: contract.citation_ready ? "pass" : "warn",
      detail: contract.citation_ready ? "Attach citation labels to public claims." : "Do not publish without a citation trail.",
    },
    {
      label: "Blocked",
      value: `${contract.unsupported_claim_count ?? 0} unsupported`,
      status: contract.unsupported_claim_count ? "stop" : "pass",
      detail: contract.unsupported_claim_count ? "Blocked claims must stay internal." : "No unsupported claims flagged.",
    },
    {
      label: "Legal",
      value: `${contract.legal_review_count ?? 0} review items`,
      status: contract.legal_review_required ? "stop" : "pass",
      detail: contract.legal_review_required ? "Route legal wording for review." : "No legal blocker in this output.",
    },
  ] as const;

  return (
    <div className={`decision-panel ${compact ? "compact-decision" : ""}`}>
      <div className="decision-summary">
        <div>
          <p className="eyebrow">Grounding Contract</p>
          <h3>{decision.toUpperCase()}: {contract.public_use || "Use only with visible source citations."}</h3>
        </div>
        <Pill tone={contractTone(decision)}>{decision}</Pill>
      </div>
      <div className="decision-grid">
        {checks.map((check) => (
          <article className={`decision-step ${check.status}`} key={check.label}>
            <Pill tone={readinessTone(check.status)}>{check.label}</Pill>
            <strong>{check.value}</strong>
            <p>{check.detail}</p>
          </article>
        ))}
      </div>
      {contract.blocked_public_claims?.length ? (
        <div className="drawer-section">
          <p className="eyebrow">Blocked Public Claims</p>
          <ul className="response-list">
            {contract.blocked_public_claims.map((claim) => <li key={claim}>{claim}</li>)}
          </ul>
        </div>
      ) : null}
      {!compact && contract.rules?.length ? (
        <div className="tag-row">
          {contract.rules.slice(0, 5).map((rule) => <Pill key={rule}>{rule}</Pill>)}
        </div>
      ) : null}
    </div>
  );
}

function payloadGroundingContract(payload: Record<string, unknown>): GroundingContract | undefined {
  const value = payload.grounding_contract;
  if (value && typeof value === "object" && !Array.isArray(value)) return value as GroundingContract;
  return undefined;
}

function PressPrepRunway({
  briefing,
  savedCount,
  onSave,
  onExport,
  onCopy,
}: {
  briefing?: PartyBriefing;
  savedCount: number;
  onSave: () => void;
  onExport: () => void;
  onCopy: () => void;
}) {
  const contract = briefing?.grounding_contract;
  const decision = contract?.decision || "not generated";
  const steps = [
    {
      label: "Minute 0-2",
      title: "Set the objective",
      detail: "Define topic, audience, requested outcome, and claims/opponents to check.",
      tone: "gold",
    },
    {
      label: "Minute 2-5",
      title: "Generate evidence",
      detail: briefing ? `${briefing.source_articles.length} source articles, ${briefing.citation_pack.length} citations.` : "Prepare a briefing to create evidence bullets and citations.",
      tone: briefing ? "green" : "gold",
    },
    {
      label: "Minute 5-8",
      title: "Clear risks",
      detail: contract ? `${contract.unsupported_claim_count ?? 0} unsupported, ${contract.legal_review_count ?? 0} legal-review items.` : "Read the grounding contract before anyone speaks.",
      tone: decision === "hold" ? "coral" : decision === "ready" ? "green" : "gold",
    },
    {
      label: "Minute 8-10",
      title: "Export the pack",
      detail: `${savedCount} saved prep packs available for reuse. Export/copy once the decision is acceptable.`,
      tone: briefing ? "green" : "gold",
    },
  ];
  return (
    <div className="runway-panel">
      <div className="runway-header">
        <div>
          <p className="eyebrow">10-Minute Press Prep</p>
          <h3>{briefing ? `${briefing.topic}: ${decision}` : "Generate a source-backed prep pack"}</h3>
        </div>
        <Pill tone={contractTone(decision)}>{decision}</Pill>
      </div>
      <div className="runway-steps">
        {steps.map((step) => (
          <article key={step.label}>
            <Pill tone={step.tone}>{step.label}</Pill>
            <strong>{step.title}</strong>
            <p>{step.detail}</p>
          </article>
        ))}
      </div>
      <div className="tag-row">
        <button className="text-button" type="button" onClick={onCopy} disabled={!briefing}>Copy</button>
        <button className="text-button" type="button" onClick={onSave} disabled={!briefing}>Save Prep Pack</button>
        <button className="primary-button inline-action" type="button" onClick={onExport}>Export PDF</button>
      </div>
    </div>
  );
}

function OperationsFreshnessPanel({
  scheduler,
  liveOps,
  sourceHealth,
  articleQuality,
  onStart,
  onRunOnce,
}: {
  scheduler?: import("./api").SchedulerStatus;
  liveOps?: LiveOpsStatus;
  sourceHealth?: IngestionSourceHealth;
  articleQuality?: ArticleQualityAudit;
  onStart?: () => void;
  onRunOnce?: () => void;
}) {
  const tone = liveOps?.overall === "healthy" ? "green" : liveOps?.overall === "watch" ? "gold" : scheduler?.stale_warning ? "coral" : "green";
  return (
    <Panel
      eyebrow="Live Operation"
      title="Freshness and Scraper Reliability"
      className="span-2"
      action={<Pill tone={tone}>{liveOps?.overall?.replaceAll("_", " ") || scheduler?.status || "checking"}</Pill>}
    >
      <div className="ops-command-grid">
        <article className="brief-item">
          <Activity size={20} />
          <strong>{scheduler?.interval_minutes ?? liveOps?.target_interval_minutes ?? "-"} min cadence</strong>
          <p>Last run {scheduler?.stale_minutes ?? liveOps?.scheduler.stale_minutes ?? "-"} minutes ago; next expected {dateLabel(scheduler?.next_expected_run_at || liveOps?.scheduler.next_expected_run_at)}.</p>
        </article>
        <article className="brief-item">
          <ShieldCheck size={20} />
          <strong>{liveOps?.ingestion.caught_up_sources ?? sourceHealth?.summary?.caught_up_count ?? 0} caught-up sources</strong>
          <p>Duplicate stopping prevents wasting time once portals are already current.</p>
        </article>
        <article className="brief-item">
          <Globe2 size={20} />
          <strong>{sourceHealth?.summary?.healthy_count ?? "-"} healthy sources</strong>
          <p>{sourceHealth?.summary?.attention_count ?? liveOps?.ingestion.attention_sources ?? 0} sources need attention.</p>
        </article>
        <article className="brief-item">
          <FileText size={20} />
          <strong>{articleQuality?.issue_count ?? 0} quality flags</strong>
          <p>Article quality should stay clean before demos and exports.</p>
        </article>
      </div>
      {liveOps?.last_run ? (
        <div className="ops-run-strip">
          <Pill tone={liveOps.last_run.status === "completed" ? "green" : liveOps.last_run.status === "failed" ? "coral" : "gold"}>
            run #{liveOps.last_run.id} {liveOps.last_run.status}
          </Pill>
          <Pill>{liveOps.last_run.total_raw} raw</Pill>
          <Pill tone="green">{liveOps.last_run.total_new} new</Pill>
          <Pill>{liveOps.last_run.total_duplicate + liveOps.last_run.total_duplicate_fuzzy} dupes</Pill>
          <Pill tone={liveOps.last_run.total_error ? "coral" : "green"}>{liveOps.last_run.total_error} errors</Pill>
          <Pill>finished {dateLabel(liveOps.last_run.finished_at || liveOps.last_run.started_at)}</Pill>
        </div>
      ) : null}
      <div className="tag-row ops-action-row">
        {onStart ? <button className="primary-button inline-action" type="button" onClick={onStart}>Start Scheduler</button> : null}
        {onRunOnce ? <button className="text-button" type="button" onClick={onRunOnce}>Run One Cycle</button> : null}
        {liveOps?.recommendations.slice(0, 4).map((item) => <Pill tone="gold" key={item}>{item}</Pill>)}
      </div>
    </Panel>
  );
}

function PostIngestionCleanupPanel({
  opsFixQueue,
  articleQuality,
  entityQuality,
  sourceHealth,
  onSourceDrilldown,
  onArticleReview,
  onEntityHide,
  onBulkExclude,
}: {
  opsFixQueue?: OpsFixQueue;
  articleQuality?: ArticleQualityAudit;
  entityQuality?: EntityQualityReport;
  sourceHealth?: IngestionSourceHealth;
  onSourceDrilldown: (sourceName: string) => void;
  onArticleReview: (articleId: number, status: "approved" | "needs_review" | "excluded") => void;
  onEntityHide: (entityId: number) => void;
  onBulkExclude: () => void;
}) {
  const total = opsFixQueue?.summary.total ?? 0;
  const articleIssues = articleQuality?.issue_count ?? 0;
  const entityIssues = entityQuality?.suspicious_count ?? 0;
  const sourceIssues = sourceHealth?.summary?.attention_count ?? 0;
  const tone = total || articleIssues || entityIssues || sourceIssues ? "gold" : "green";
  return (
    <Panel
      eyebrow="Post-Ingestion Cleanup"
      title="Operator Queue"
      className="span-2"
      action={<Pill tone={tone}>{total} queued</Pill>}
    >
      <div className="stack">
        <div className="brief-grid">
          <article className="brief-item">
            <Globe2 size={20} />
            <strong>{sourceIssues}</strong>
            <p>sources needing attention after the latest run</p>
          </article>
          <article className="brief-item">
            <FileText size={20} />
            <strong>{articleIssues}</strong>
            <p>article quality items to approve or exclude</p>
          </article>
          <article className="brief-item">
            <UsersRound size={20} />
            <strong>{entityIssues}</strong>
            <p>suspicious entities to hide, merge, or approve</p>
          </article>
        </div>
        {articleIssues ? (
          <div className="tag-row">
            <button className="text-button" type="button" onClick={onBulkExclude}>
              Bulk Exclude Flagged Articles
            </button>
          </div>
        ) : null}
        <div className="source-list">
          {opsFixQueue?.items.length ? opsFixQueue.items.slice(0, 10).map((item, index) => (
            <article className="source-card" key={`cleanup-${item.area}-${item.article_id || item.entity_id || item.source_stat_id || index}`}>
              <div className="source-main">
                <div>
                  <div className="card-meta">
                    <Pill tone={item.priority === "p0" ? "coral" : item.priority === "p1" ? "gold" : "default"}>
                      {item.priority.toUpperCase()}
                    </Pill>
                    <Pill>{item.area.replaceAll("_", " ")}</Pill>
                  </div>
                  <strong>{item.title}</strong>
                  <p>{item.detail}</p>
                  <p className="muted">{item.suggested_action}</p>
                  {item.url ? <a className="article-title" href={item.url} target="_blank" rel="noreferrer">Open source URL</a> : null}
                </div>
                <div className="board-actions">
                  {item.area === "source_health" && item.source_name ? (
                    <button className="text-button" type="button" onClick={() => onSourceDrilldown(item.source_name!)}>
                      Drilldown
                    </button>
                  ) : null}
                  {item.area === "article_quality" && item.article_id ? (
                    <>
                      <button className="text-button" type="button" onClick={() => onArticleReview(item.article_id!, "approved")}>
                        Approve
                      </button>
                      <button className="text-button" type="button" onClick={() => onArticleReview(item.article_id!, "excluded")}>
                        Exclude
                      </button>
                    </>
                  ) : null}
                  {item.area === "entity_quality" && item.entity_id ? (
                    <button className="text-button" type="button" onClick={() => onEntityHide(item.entity_id!)}>
                      Hide
                    </button>
                  ) : null}
                </div>
              </div>
            </article>
          )) : (
            <div className="empty-state">No cleanup work after the latest ingestion run.</div>
          )}
        </div>
      </div>
    </Panel>
  );
}

function SavedBriefingBoard({
  briefings,
  filter,
  statusFilter,
  typeFilter,
  folderFilter,
  onFilter,
  onStatusFilter,
  onTypeFilter,
  onFolderFilter,
  onOpen,
  onDuplicate,
  onExport,
}: {
  briefings: SavedBriefing[];
  filter: string;
  statusFilter: string;
  typeFilter: string;
  folderFilter: string;
  onFilter: (value: string) => void;
  onStatusFilter: (value: string) => void;
  onTypeFilter: (value: string) => void;
  onFolderFilter: (value: string) => void;
  onOpen: (briefing: SavedBriefing) => void;
  onDuplicate: (briefingId: number) => void;
  onExport: (briefingId: number) => void;
}) {
  const folders = Array.from(new Set(briefings.map((item) => item.folder).filter(Boolean) as string[])).sort();
  const types = Array.from(new Set(briefings.map((item) => item.briefing_type))).sort();
  const normalizedFilter = filter.trim().toLowerCase();
  const filtered = briefings.filter((briefing) => {
    const text = [
      briefing.title,
      briefing.topic || "",
      briefing.briefing_type,
      briefing.folder || "",
      ...(briefing.tags || []),
    ].join(" ").toLowerCase();
    if (normalizedFilter && !text.includes(normalizedFilter)) return false;
    if (statusFilter && (briefing.status || "active") !== statusFilter) return false;
    if (typeFilter && briefing.briefing_type !== typeFilter) return false;
    if (folderFilter && briefing.folder !== folderFilter) return false;
    return true;
  });

  return (
    <Panel eyebrow="Saved Work" title="Briefing and Case Board" className="span-2">
      <div className="stack">
        <div className="filter-row">
          <input
            className="board-search"
            value={filter}
            onChange={(event) => onFilter(event.target.value)}
            placeholder="Search saved briefings, cases, tags"
          />
          <select value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}>
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="pinned">Pinned</option>
            <option value="archived">Archived</option>
          </select>
          <select value={typeFilter} onChange={(event) => onTypeFilter(event.target.value)}>
            <option value="">All types</option>
            {types.map((type) => <option value={type} key={type}>{type.replaceAll("_", " ")}</option>)}
          </select>
          <select value={folderFilter} onChange={(event) => onFolderFilter(event.target.value)}>
            <option value="">All folders</option>
            {folders.map((folder) => <option value={folder} key={folder}>{folder}</option>)}
          </select>
        </div>
        <div className="brief-grid">
          <article className="brief-item">
            <FileText size={20} />
            <strong>{briefings.length}</strong>
            <p>total saved packs</p>
          </article>
          <article className="brief-item">
            <ShieldCheck size={20} />
            <strong>{briefings.filter((item) => item.status === "pinned").length}</strong>
            <p>pinned for reuse</p>
          </article>
          <article className="brief-item">
            <Bell size={20} />
            <strong>{filtered.length}</strong>
            <p>visible after filters</p>
          </article>
        </div>
        <div className="source-list">
          {filtered.length ? filtered.map((briefing) => {
            const contract = payloadGroundingContract(briefing.payload);
            return (
              <article className="source-card saved-board-card" key={`saved-board-${briefing.id}`}>
                <div className="source-main">
                  <div>
                    <div className="card-meta">
                      <Pill tone="gold">{briefing.briefing_type.replaceAll("_", " ")}</Pill>
                      <Pill tone={briefing.status === "pinned" ? "green" : briefing.status === "archived" ? "coral" : undefined}>
                        {briefing.status || "active"}
                      </Pill>
                      {briefing.folder ? <Pill>{briefing.folder}</Pill> : null}
                      {contract ? <Pill tone={contractTone(contract.decision)}>{contract.decision}</Pill> : null}
                      <Pill>{dateLabel(briefing.updated_at || briefing.created_at)}</Pill>
                    </div>
                    <strong>{briefing.title}</strong>
                    <p>{briefing.topic || payloadText(briefing.payload, ["coverage_summary", "situation_summary", "summary"], "Saved structured briefing.")}</p>
                    {contract ? (
                      <p className="muted">
                        {contract.article_count ?? 0} articles / {contract.source_count ?? 0} sources; {contract.unsupported_claim_count ?? 0} unsupported; {contract.legal_review_count ?? 0} legal review.
                      </p>
                    ) : null}
                    {briefing.tags?.length ? (
                      <div className="tag-row">
                        {briefing.tags.slice(0, 5).map((tag) => <Pill key={`${briefing.id}-board-${tag}`}>{tag}</Pill>)}
                      </div>
                    ) : null}
                  </div>
                  <div className="board-actions">
                    <button className="text-button" type="button" onClick={() => onOpen(briefing)}>Open</button>
                    <button className="text-button" type="button" onClick={() => onDuplicate(briefing.id)}>Duplicate</button>
                    <button className="text-button" type="button" onClick={() => onExport(briefing.id)}>Export</button>
                  </div>
                </div>
              </article>
            );
          }) : (
            <div className="empty-state">No saved work matches these filters.</div>
          )}
        </div>
      </div>
    </Panel>
  );
}

function FacebookPageCard({ page }: { page: FacebookPageMonitor }) {
  return (
    <article className="source-card">
      <div className="source-main">
        <div>
          <div className="card-meta">
            <Pill tone="gold">{page.monitor_type}</Pill>
            <Pill>{page.language}</Pill>
            <Pill tone={page.is_active ? "green" : "coral"}>
              {page.is_active ? "active" : "inactive"}
            </Pill>
          </div>
          <a href={page.url} target="_blank" rel="noreferrer">
            {page.name}
          </a>
        </div>
        <strong>{Math.round(page.reliability_score * 100)}%</strong>
      </div>
      <p>
        Handle: {page.page_handle || page.page_id || "auto from URL"}
        {page.last_fetched_at ? ` · Last fetched ${dateLabel(page.last_fetched_at)}` : ""}
      </p>
    </article>
  );
}

export function App() {
  const [currentUser, setCurrentUser] = useState<User | undefined>(() => {
    const saved = localStorage.getItem("newsintel_user");
    return saved ? JSON.parse(saved) as User : undefined;
  });
  const [view, setView] = useState<View>("overview");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [language, setLanguage] = useState("");
  const [articleSourceId, setArticleSourceId] = useState("");
  const [articleEntityId, setArticleEntityId] = useState("");
  const [articleSourceType, setArticleSourceType] = useState("");
  const [minReliability, setMinReliability] = useState("");
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [exactPhrase, setExactPhrase] = useState(false);
  const [dateBasis, setDateBasis] = useState("published");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [entityType, setEntityType] = useState("");
  const [selectedEntityId, setSelectedEntityId] = useState<number | undefined>();
  const [selectedArticle, setSelectedArticle] = useState<Article | undefined>();
  const [selectedResponsePack, setSelectedResponsePack] = useState<ResponsePack | undefined>();
  const [selectedIncident, setSelectedIncident] = useState<Incident | undefined>();
  const [selectedTimeline, setSelectedTimeline] = useState<AttackTimeline | undefined>();
  const [responseDraftLanguage, setResponseDraftLanguage] = useState<"en" | "mk">("en");
  const [clientChatQuestion, setClientChatQuestion] = useState("What is the latest about me?");
  const [clientChatAnswer, setClientChatAnswer] = useState<ClientChatResponse | undefined>();
  const [clientChatConversationId, setClientChatConversationId] = useState<number | undefined>();
  const [clientChatStatus, setClientChatStatus] = useState("");
  const [selectedStoryCluster, setSelectedStoryCluster] = useState<StoryCluster | undefined>();
  const [selectedClientId, setSelectedClientId] = useState<number | undefined>();
  const [clientForm, setClientForm] = useState<ClientInput>({
    name: "",
    email: "",
    client_type: "political_figure",
    plan: "political_defense",
    country_code: "mk",
    language: "mk",
    risk_tolerance: "balanced",
    settings: {},
  });
  const [clientSaveStatus, setClientSaveStatus] = useState("");
  const [subscriptionForm, setSubscriptionForm] = useState<SubscriptionInput>({
    email: "",
    name: "",
    country_code: "mk",
    categories: [],
    frequency: "daily",
    format: "pdf",
  });
  const [subscriptionCategoriesText, setSubscriptionCategoriesText] = useState("");
  const [subscriptionStatus, setSubscriptionStatus] = useState("");
  const [watchlistForm, setWatchlistForm] = useState<WatchlistItemInput>({
    item_type: "keyword",
    label: "",
    value: "",
    entity_id: null,
    source_id: null,
    facebook_page_url: "",
    priority: 3,
    alert_enabled: true,
    response_assist_enabled: true,
    notes: "",
  });
  const [watchlistSaveStatus, setWatchlistSaveStatus] = useState("");
  const [watchlistAlertStatus, setWatchlistAlertStatus] = useState("");
  const [responsePackStatus, setResponsePackStatus] = useState("");
  const [timelineStatus, setTimelineStatus] = useState("");
  const [incidentSaveStatus, setIncidentSaveStatus] = useState("");
  const [incidentUpdateStatus, setIncidentUpdateStatus] = useState("");
  const [incidentReportStatus, setIncidentReportStatus] = useState("");
  const [responsePackReportStatus, setResponsePackReportStatus] = useState("");
  const [clientBriefReportStatus, setClientBriefReportStatus] = useState("");
  const [partyBriefingForm, setPartyBriefingForm] = useState<PartyBriefingInput>({
    topic: "",
    objective: "",
    requirements: "",
    audience: "general public",
    tone: "statesmanlike",
    include_entities: [],
    include_opponents: [],
    include_legal_context: true,
    date_from: "",
    date_to: "",
    include_watchlist: true,
    max_articles: 20,
  });
  const [partyEntitiesText, setPartyEntitiesText] = useState("");
  const [partyOpponentsText, setPartyOpponentsText] = useState("");
  const [partyBriefing, setPartyBriefing] = useState<PartyBriefing | undefined>();
  const [selectedSavedBriefing, setSelectedSavedBriefing] = useState<SavedBriefing | undefined>();
  const [partyBriefingStatus, setPartyBriefingStatus] = useState("");
  const [partyBriefingReportStatus, setPartyBriefingReportStatus] = useState("");
  const [savedBriefingStatus, setSavedBriefingStatus] = useState("");
  const [evidenceForm, setEvidenceForm] = useState<EvidenceInput>({
    url: "",
    title: "",
    source_name: "",
    evidence_type: "url",
    notes: "",
  });
  const [evidenceStatus, setEvidenceStatus] = useState("");
  const [entityPicker, setEntityPicker] = useState("");
  const [sourcePicker, setSourcePicker] = useState("");
  const [facebookPicker, setFacebookPicker] = useState("");
  const [facebookForm, setFacebookForm] = useState<FacebookPageMonitorInput>({
    name: "",
    url: "",
    page_handle: "",
    page_id: "",
    country_code: "mk",
    language: "mk",
    monitor_type: "political_figure",
    source_type: "social_media",
    political_leaning: "unknown",
    ownership: "official page",
    reliability_score: 0.65,
    is_active: true,
    notes: "",
  });

  function handleLogin(user: User) {
    setCurrentUser(user);
    setView(user.role === "client" ? "clients" : "overview");
    if (user.client_id) setSelectedClientId(user.client_id);
  }
  const [facebookSaveStatus, setFacebookSaveStatus] = useState("");
  const [facebookFetchStatus, setFacebookFetchStatus] = useState("");
  const [lastFacebookFetch, setLastFacebookFetch] = useState<FacebookFetchResult | undefined>();
  const [userForm, setUserForm] = useState<UserInput>({
    email: "",
    name: "",
    password: "",
    role: "client",
    client_id: null,
    is_active: true,
  });
  const [userSaveStatus, setUserSaveStatus] = useState("");
  const [legalSearch, setLegalSearch] = useState("");
  const [legalForm, setLegalForm] = useState<LegalDocumentInput>({
    title: "",
    country_code: "mk",
    legal_area: "",
    source_url: "",
    source_name: "",
    source_status: "needs_review",
    language: "mk",
    tags: [],
    summary: "",
    reference_text: "",
    article_refs: "",
    confidence_score: 0.4,
    notes: "",
  });
  const [legalTagsText, setLegalTagsText] = useState("");
  const [legalSaveStatus, setLegalSaveStatus] = useState("");
  const [selectedLegalReviewId, setSelectedLegalReviewId] = useState<number | undefined>();
  const [legalReviewStatus, setLegalReviewStatus] = useState("");
  const [legalReviewForm, setLegalReviewForm] = useState<LegalReviewInput>({
    decision: "needs_review",
    reviewer_name: "",
    reviewer_organization: "",
    notes: "",
  });
  const [legalAssignmentForm, setLegalAssignmentForm] = useState<LegalReviewAssignmentInput>({
    reviewer_name: "",
    reviewer_email: "",
    reviewer_organization: "",
    reviewer_jurisdiction: "",
    qualification_reference: "",
    scope: "Verify the exact official text, amendments, cited article numbers, and limits for client-facing use.",
    due_at: "",
    notes: "",
  });
  const [legalAssignmentStatus, setLegalAssignmentStatus] = useState("");
  const [entityReviewStatus, setEntityReviewStatus] = useState("");
  const [entityLexiconStatus, setEntityLexiconStatus] = useState("");
  const [articleQualityStatus, setArticleQualityStatus] = useState("");
  const [riskAlertStatus, setRiskAlertStatus] = useState("");
  const [opsStatus, setOpsStatus] = useState("");
  const [alertOpsStatus, setAlertOpsStatus] = useState("");
  const [backupStatusText, setBackupStatusText] = useState("");
  const [sourceConfigStatus, setSourceConfigStatus] = useState("");
  const [schedulerActionStatus, setSchedulerActionStatus] = useState("");
  const [selectedSourceDrilldown, setSelectedSourceDrilldown] = useState<SourceDrilldown | undefined>();
  const [scraperPreflightStatus, setScraperPreflightStatus] = useState("");
  const [selectedScraperPreflight, setSelectedScraperPreflight] = useState<ScraperPreflight | undefined>();
  const [storyStatus, setStoryStatus] = useState("");
  const [storyClusterStatusFilter, setStoryClusterStatusFilter] = useState("");
  const [storyClusterDays, setStoryClusterDays] = useState(30);
  const [mergeTargets, setMergeTargets] = useState<Record<number, string>>({});
  const [clientTab, setClientTab] = useState<ClientTab>("briefs");
  const [clientWindowDays, setClientWindowDays] = useState<7 | 30 | 90>(30);
  const [savedBoardSearch, setSavedBoardSearch] = useState("");
  const [savedBoardStatus, setSavedBoardStatus] = useState("");
  const [savedBoardType, setSavedBoardType] = useState("");
  const [savedBoardFolder, setSavedBoardFolder] = useState("");
  const [savedSearchName, setSavedSearchName] = useState("");
  const [savedSearchStatus, setSavedSearchStatus] = useState("");
  const [attackReviewStatus, setAttackReviewStatus] = useState("");
  const queryClient = useQueryClient();
  const workspaceComponents = useMemo<ClientWorkspaceComponents>(() => ({
    Panel,
    Pill,
    ArticleCard,
    RiskCard,
    IncidentCard,
  }), []);
  const staffWorkspaceDataEnabled = Boolean(
    currentUser && currentUser.role !== "client"
  );
  const staffAccess = currentUser?.role === "admin" || currentUser?.role === "analyst";
  const adminPageDataEnabled = currentUser?.role === "admin" && view === "admin";
  const adminOperationsDataEnabled = currentUser?.role === "admin" && (view === "overview" || view === "admin");
  const clientPageDataEnabled = currentUser?.role === "client" || (staffAccess && view === "clients");

  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000 });
  const countries = useQuery({ queryKey: ["countries"], queryFn: api.countries });
  const articles = useQuery({
    queryKey: [
      "articles",
      search,
      category,
      language,
      dateBasis,
      dateFrom,
      dateTo,
      articleSourceId,
      articleEntityId,
      articleSourceType,
      minReliability,
      sentimentFilter,
      exactPhrase,
    ],
    queryFn: () => api.articles(params({
      limit: 30,
      q: search,
      category,
      language,
      source_id: articleSourceId || undefined,
      entity_id: articleEntityId || undefined,
      source_type: articleSourceType || undefined,
      min_reliability: minReliability || undefined,
      sentiment: sentimentFilter || undefined,
      exact_phrase: exactPhrase ? "true" : undefined,
      date_basis: dateBasis,
      date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
    })),
    enabled: staffWorkspaceDataEnabled,
  });
  const savedSearches = useQuery<SavedSearch[]>({
    queryKey: ["saved-searches", currentUser?.id],
    queryFn: api.savedSearches,
    enabled: staffWorkspaceDataEnabled,
  });
  const entities = useQuery({
    queryKey: ["entities", search, entityType],
    queryFn: () => api.entities(params({ limit: 60, q: search, entity_type: entityType })),
    enabled: staffWorkspaceDataEnabled,
  });
  const topicBriefing = useQuery<TopicBriefing>({
    queryKey: ["topic-briefing", search],
    queryFn: () => api.topicBriefing(search),
    enabled: staffWorkspaceDataEnabled && search.trim().length >= 2,
  });
  const trends = useQuery({ queryKey: ["trends"], queryFn: api.trends, enabled: staffWorkspaceDataEnabled && (view === "trends" || view === "demo") });
  const storyClusters = useQuery({
    queryKey: ["story-clusters", storyClusterStatusFilter, storyClusterDays],
    queryFn: () => api.storyClusters({
      days: storyClusterDays,
      status: storyClusterStatusFilter,
      limit: 36,
    }),
    enabled: staffWorkspaceDataEnabled,
  });
  const storySpread = useQuery<StorySpread>({
    queryKey: ["story-spread"],
    queryFn: api.storySpread,
    enabled: staffWorkspaceDataEnabled,
  });
  const politicalRisk = useQuery({ queryKey: ["political-risk"], queryFn: api.politicalRisk, enabled: staffWorkspaceDataEnabled });
  const dailyBrief = useQuery({ queryKey: ["daily-brief"], queryFn: api.dailyBrief, enabled: staffWorkspaceDataEnabled });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, enabled: staffWorkspaceDataEnabled });
  const narratives = useQuery({ queryKey: ["narratives"], queryFn: api.narratives, enabled: staffWorkspaceDataEnabled });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources, enabled: staffWorkspaceDataEnabled });
  const timeline = useQuery({
    queryKey: ["timeline", dateBasis],
    queryFn: () => api.timeline(dateBasis),
    enabled: staffWorkspaceDataEnabled,
  });
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts, enabled: staffWorkspaceDataEnabled });
  const clients = useQuery({
    queryKey: ["clients"],
    queryFn: api.clients,
    enabled: staffAccess && view === "clients",
  });
  const facebookPages = useQuery({
    queryKey: ["facebook-pages"],
    queryFn: api.facebookPages,
    enabled: adminPageDataEnabled,
  });
  const legalDocuments = useQuery({
    queryKey: ["legal-documents", legalSearch],
    queryFn: () => api.legalDocuments(legalSearch),
    enabled: adminPageDataEnabled,
  });
  const legalQuality = useQuery<LegalQuality>({
    queryKey: ["legal-quality"],
    queryFn: api.legalQuality,
    enabled: adminPageDataEnabled,
  });
  const facebookStatus = useQuery({
    queryKey: ["facebook-status"],
    queryFn: api.facebookStatus,
    enabled: adminPageDataEnabled,
  });
  const ingestionRuns = useQuery({
    queryKey: ["ingestion-runs"],
    queryFn: api.ingestionRuns,
    enabled: adminPageDataEnabled,
  });
  const schedulerStatus = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: api.schedulerStatus,
    enabled: adminOperationsDataEnabled,
    refetchInterval: 60_000,
  });
  const liveOps = useQuery<LiveOpsStatus>({
    queryKey: ["live-ops"],
    queryFn: api.liveOps,
    enabled: adminOperationsDataEnabled,
    refetchInterval: 60_000,
  });
  const backups = useQuery<BackupStatus>({
    queryKey: ["backups"],
    queryFn: api.backups,
    enabled: adminPageDataEnabled,
  });
  const launchChecklist = useQuery<LaunchChecklist>({
    queryKey: ["launch-checklist"],
    queryFn: api.launchChecklist,
    enabled: adminPageDataEnabled,
    refetchInterval: 60_000,
  });
  const clientBriefReadiness = useQuery({
    queryKey: ["client-brief-readiness"],
    queryFn: api.clientBriefReadiness,
    enabled: staffAccess && view === "clients",
  });
  const sourceHealth = useQuery<IngestionSourceHealth>({
    queryKey: ["source-health"],
    queryFn: api.sourceHealth,
    enabled: adminOperationsDataEnabled,
  });
  const sourceReliability = useQuery<SourceReliability>({
    queryKey: ["source-reliability"],
    queryFn: api.sourceReliability,
    enabled: adminPageDataEnabled,
  });
  const sourceConfigValidation = useQuery<SourceConfigValidation>({
    queryKey: ["source-config-validation"],
    queryFn: api.sourceConfigValidation,
    enabled: adminPageDataEnabled,
  });
  const articleQuality = useQuery<ArticleQualityAudit>({
    queryKey: ["article-quality"],
    queryFn: api.articleQuality,
    enabled: adminPageDataEnabled,
  });
  const intelligenceQA = useQuery<IntelligenceQA>({
    queryKey: ["intelligence-qa"],
    queryFn: api.intelligenceQA,
    enabled: adminPageDataEnabled,
  });
  const opsFixQueue = useQuery<OpsFixQueue>({
    queryKey: ["ops-fix-queue"],
    queryFn: api.opsFixQueue,
    enabled: adminPageDataEnabled,
  });
  const entityReviewQueue = useQuery({
    queryKey: ["entity-review"],
    queryFn: () => api.entityReviewQueue(),
    enabled: adminPageDataEnabled,
  });
  const entityQualityReport = useQuery<EntityQualityReport>({
    queryKey: ["entity-quality-report"],
    queryFn: api.entityQualityReport,
    enabled: adminPageDataEnabled,
  });
  const attackReviewQueue = useQuery<AttackReviewQueue>({
    queryKey: ["attack-review-queue"],
    queryFn: api.attackReviewQueue,
    enabled: adminPageDataEnabled,
  });
  const searchQuality = useQuery<SearchQuality>({
    queryKey: ["search-quality"],
    queryFn: api.searchQuality,
    enabled: adminPageDataEnabled,
  });
  const entityLexiconCoverage = useQuery<EntityLexiconCoverage>({
    queryKey: ["entity-lexicon-coverage"],
    queryFn: api.entityLexiconCoverage,
    enabled: adminPageDataEnabled,
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: api.users,
    enabled: adminPageDataEnabled,
  });
  const activeClientId = currentUser?.role === "client"
    ? currentUser.client_id ?? undefined
    : selectedClientId ?? clients.data?.[0]?.id;
  const clientDashboard = useQuery({
    queryKey: ["client-dashboard", activeClientId, clientWindowDays],
    queryFn: () => api.clientDashboard(activeClientId!, clientWindowDays),
    enabled: Boolean(activeClientId && clientPageDataEnabled),
  });
  const clientDailyBrief = useQuery({
    queryKey: ["client-daily-brief", activeClientId],
    queryFn: () => api.clientDailyBrief(activeClientId!),
    enabled: Boolean(activeClientId && clientPageDataEnabled && clientDashboard.data?.client.client_type && clientDashboard.data.client.client_type !== "political_figure"),
  });
  const savedTopics = useQuery<SavedTopicWatch[]>({
    queryKey: ["client-saved-topics", activeClientId],
    queryFn: () => api.clientSavedTopics(activeClientId!),
    enabled: Boolean(activeClientId && clientPageDataEnabled && clientDashboard.data?.client.client_type && clientDashboard.data.client.client_type !== "political_figure"),
  });
  const reports = useQuery({
    queryKey: ["reports", activeClientId, currentUser?.role],
    queryFn: () => api.reports(currentUser?.role === "admin" || currentUser?.role === "analyst" ? activeClientId : undefined),
    enabled: Boolean(clientPageDataEnabled && currentUser && (currentUser.role !== "client" || clientDashboard.data)),
  });
  const subscriptions = useQuery<Subscription[]>({
    queryKey: ["subscriptions"],
    queryFn: api.subscriptions,
    enabled: staffAccess && view === "clients",
  });
  const savedBriefings = useQuery<SavedBriefing[]>({
    queryKey: ["saved-briefings", activeClientId],
    queryFn: () => api.savedBriefings(activeClientId!),
    enabled: Boolean(activeClientId && clientPageDataEnabled && clientDashboard.data),
  });
  const incidents = useQuery({
    queryKey: ["client-incidents", activeClientId],
    queryFn: () => api.incidents(activeClientId!),
    enabled: Boolean(activeClientId && clientPageDataEnabled && clientDashboard.data),
  });
  const evidence = useQuery({
    queryKey: ["incident-evidence", activeClientId, selectedIncident?.id],
    queryFn: () => api.evidence(activeClientId!, selectedIncident!.id),
    enabled: Boolean(activeClientId && clientPageDataEnabled && selectedIncident?.id),
  });

  const articleData = articles.data?.articles ?? [];
  const entityData = entities.data ?? [];
  const topicBriefingData = topicBriefing.data;
  const trendData = trends.data ?? [];
  const storyClusterData = storyClusters.data ?? [];
  const storySpreadData = storySpread.data;
  const politicalRiskData = politicalRisk.data;
  const dailyBriefData = dailyBrief.data;
  const categoryData = categories.data ?? [];
  const narrativeData = narratives.data ?? [];
  const sourceData = sources.data ?? [];
  const timelineData = timeline.data ?? [];
  const alertData = alerts.data ?? [];
  const clientData = clients.data ?? [];
  const clientDash = clientDashboard.data;
  const clientDailyBriefData = clientDailyBrief.data;
  const savedTopicData = savedTopics.data ?? [];
  const reportData = reports.data ?? [];
  const subscriptionData = subscriptions.data ?? [];
  const savedBriefingData = savedBriefings.data ?? [];
  const savedSearchData = savedSearches.data ?? [];
  const incidentData = incidents.data ?? [];
  const evidenceData = evidence.data ?? [];
  const legalQualityData = legalQuality.data;
  const facebookPageData = facebookPages.data ?? [];
  const facebookOps = facebookStatus.data;
  const ingestionRunData = ingestionRuns.data ?? [];
  const schedulerStatusData = schedulerStatus.data;
  const liveOpsData = liveOps.data;
  const backupData = backups.data;
  const launchChecklistData = launchChecklist.data;
  const clientBriefReadinessData = clientBriefReadiness.data ?? [];
  const sourceHealthData = sourceHealth.data;
  const sourceReliabilityData = sourceReliability.data;
  const sourceConfigValidationData = sourceConfigValidation.data;
  const articleQualityData = articleQuality.data;
  const intelligenceQAData = intelligenceQA.data;
  const opsFixQueueData = opsFixQueue.data;
  const entityReviewData = entityReviewQueue.data ?? [];
  const entityQualityData = entityQualityReport.data;
  const attackReviewData = attackReviewQueue.data;
  const searchQualityData = searchQuality.data;
  const entityLexiconData = entityLexiconCoverage.data;
  const userData = users.data ?? [];
  const legalDocumentData = legalDocuments.data ?? [];
  const selectedLegalReview = legalDocumentData.find(
    (document) => document.id === selectedLegalReviewId
  );
  const selectedEntity = entityData.find((entity) => String(entity.id) === entityPicker);
  const selectedSource = sourceData.find((source) => String(source.source_id) === sourcePicker);
  const selectedFacebookPage = facebookPageData.find((page) => String(page.id) === facebookPicker);
  const country = countries.data?.[0];
  const apiOnline = health.data?.status === "ok";
  const navigation = visibleViews(currentUser);
  const modeClient = clientDash?.client || clientData.find((client) => client.id === activeClientId);
  const isPoliticalFigureClient = clientDash?.client.client_type === "political_figure";
  const visibleClientTabs = clientTabItems(clientDash?.client, staffAccess);

  useEffect(() => {
    setClientChatConversationId(undefined);
    setClientChatAnswer(undefined);
    setClientChatStatus("");
  }, [activeClientId]);

  useEffect(() => {
    if (currentUser?.role !== "client" || !clientDash?.client.client_type) return;
    if (clientDash.client.client_type === "political_party" && clientTab === "risks") {
      setClientTab("briefs");
    }
  }, [currentUser?.role, clientDash?.client.client_type, clientTab]);

  useEffect(() => {
    if (!navigation.some((item) => item.id === view)) {
      setView(navigation[0]?.id ?? "clients");
    }
  }, [navigation, view]);

  const brief = useMemo(() => {
    const topTrend = trendData[0];
    const topCategory = categoryData[0];
    const newest = articleData[0];
    return [
      {
        title: topTrend ? `${topTrend.name} is the strongest signal` : "No trend signal yet",
        body: topTrend
          ? `${topTrend.recent_mentions} mentions across ${topTrend.recent_articles} articles, currently ${topTrend.trend_direction}.`
          : "Ingest and process more articles to build momentum scoring.",
        icon: Brain,
      },
      {
        title: topCategory ? `${topCategory.category} leads coverage` : "Category mix pending",
        body: topCategory ? `${topCategory.article_count} recent articles are classified under this category.` : "Categories appear after processing.",
        icon: Activity,
      },
      {
        title: newest ? "Latest article is ready" : "No articles loaded",
        body: newest ? `${newest.source_name}: ${newest.title}` : "The article list is empty for the current filters.",
        icon: BookOpenText,
      },
    ];
  }, [articleData, categoryData, trendData]);

  function refreshAll() {
    queryClient.invalidateQueries();
  }

  function activeSearchFilters() {
    return {
      category: category || undefined,
      language: language || undefined,
      source_id: articleSourceId || undefined,
      entity_id: articleEntityId || undefined,
      source_type: articleSourceType || undefined,
      min_reliability: minReliability || undefined,
      sentiment: sentimentFilter || undefined,
      exact_phrase: exactPhrase || undefined,
      date_basis: dateBasis,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    };
  }

  async function saveCurrentSearch(event: React.FormEvent) {
    event.preventDefault();
    const title = savedSearchName.trim() || search.trim() || "Saved article search";
    setSavedSearchStatus("Saving search...");
    try {
      await api.createSavedSearch({
        title,
        query: search.trim(),
        filters: activeSearchFilters(),
      });
      setSavedSearchName("");
      setSavedSearchStatus("Search saved privately.");
      queryClient.invalidateQueries({ queryKey: ["saved-searches", currentUser?.id] });
    } catch (error) {
      setSavedSearchStatus(error instanceof Error ? error.message : "Could not save search");
    }
  }

  function applySavedSearch(item: SavedSearch) {
    const filters = item.filters || {};
    setSearch(item.query || "");
    setCategory(String(filters.category || ""));
    setLanguage(String(filters.language || ""));
    setArticleSourceId(String(filters.source_id || ""));
    setArticleEntityId(String(filters.entity_id || ""));
    setArticleSourceType(String(filters.source_type || ""));
    setMinReliability(String(filters.min_reliability || ""));
    setSentimentFilter(String(filters.sentiment || ""));
    setExactPhrase(Boolean(filters.exact_phrase));
    setDateBasis(String(filters.date_basis || "published"));
    setDateFrom(String(filters.date_from || ""));
    setDateTo(String(filters.date_to || ""));
    setSavedSearchStatus(`Opened ${item.title}.`);
    setView("articles");
  }

  async function removeSavedSearch(searchId: number) {
    setSavedSearchStatus("Removing saved search...");
    try {
      await api.deleteSavedSearch(searchId);
      setSavedSearchStatus("Saved search removed.");
      queryClient.invalidateQueries({ queryKey: ["saved-searches", currentUser?.id] });
    } catch (error) {
      setSavedSearchStatus(error instanceof Error ? error.message : "Could not remove search");
    }
  }

  async function reviewAttackDetection(
    watchlistItemId: number,
    articleId: number,
    status: "confirmed" | "rejected",
  ) {
    setAttackReviewStatus(status === "confirmed" ? "Confirming detection..." : "Removing false positive...");
    try {
      await api.reviewAttack(watchlistItemId, articleId, {
        status,
        notes: status === "confirmed"
          ? "Confirmed in the admin attack-quality queue."
          : "Rejected in the admin attack-quality queue; excluded from client attack views.",
      });
      setAttackReviewStatus(status === "confirmed" ? "Attack relation confirmed." : "False positive removed from client views.");
      queryClient.invalidateQueries({ queryKey: ["attack-review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["client-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["client-daily-brief"] });
    } catch (error) {
      setAttackReviewStatus(error instanceof Error ? error.message : "Could not save attack review");
    }
  }

  async function signOut() {
    try {
      await api.logout();
    } catch {
      // Local session cleanup is enough for this first auth layer.
    }
    localStorage.removeItem("newsintel_token");
    localStorage.removeItem("newsintel_user");
    setCurrentUser(undefined);
    queryClient.clear();
  }

  async function saveFacebookPage(event: React.FormEvent) {
    event.preventDefault();
    setFacebookSaveStatus("Saving...");
    try {
      await api.createFacebookPage(facebookForm);
      setFacebookSaveStatus("Saved");
      setFacebookForm({
        ...facebookForm,
        name: "",
        url: "",
        page_handle: "",
        page_id: "",
        notes: "",
      });
      queryClient.invalidateQueries({ queryKey: ["facebook-pages"] });
      queryClient.invalidateQueries({ queryKey: ["sources"] });
    } catch (error) {
      setFacebookSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function saveLegalDocument(event: React.FormEvent) {
    event.preventDefault();
    setLegalSaveStatus("Saving legal reference...");
    try {
      await api.createLegalDocument({
        ...legalForm,
        tags: legalTagsText
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      setLegalSaveStatus("Saved");
      setLegalForm({
        title: "",
        country_code: "mk",
        legal_area: "",
        source_url: "",
        source_name: "",
        source_status: "needs_review",
        language: "mk",
        tags: [],
        summary: "",
        reference_text: "",
        article_refs: "",
        confidence_score: 0.4,
        notes: "",
      });
      setLegalTagsText("");
      queryClient.invalidateQueries({ queryKey: ["legal-documents"] });
      queryClient.invalidateQueries({ queryKey: ["legal-quality"] });
    } catch (error) {
      setLegalSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function submitLegalReview(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedLegalReviewId) return;
    setLegalReviewStatus("Saving audited review...");
    try {
      const review = await api.reviewLegalDocument(selectedLegalReviewId, legalReviewForm);
      setLegalReviewStatus(`Saved: ${review.status_before.replaceAll("_", " ")} → ${review.status_after.replaceAll("_", " ")}`);
      setLegalReviewForm({
        ...legalReviewForm,
        decision: "needs_review",
        notes: "",
      });
      queryClient.invalidateQueries({ queryKey: ["legal-documents"] });
      queryClient.invalidateQueries({ queryKey: ["legal-quality"] });
    } catch (error) {
      setLegalReviewStatus(error instanceof Error ? error.message : "Review failed");
    }
  }

  async function assignLegalReview(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedLegalReviewId) return;
    setLegalAssignmentStatus("Assigning counsel review...");
    try {
      const assignment = await api.assignLegalReview(selectedLegalReviewId, {
        ...legalAssignmentForm,
        due_at: legalAssignmentForm.due_at
          ? `${legalAssignmentForm.due_at}T17:00:00`
          : undefined,
      });
      setLegalAssignmentStatus(`Assigned to ${assignment.reviewer_name}`);
      setLegalAssignmentForm({
        ...legalAssignmentForm,
        reviewer_name: "",
        reviewer_email: "",
        reviewer_organization: "",
        due_at: "",
        notes: "",
      });
    } catch (error) {
      setLegalAssignmentStatus(error instanceof Error ? error.message : "Assignment failed");
    }
  }

  async function reviewEntity(entityId: number, status: string, entityType?: string) {
    setEntityReviewStatus("Saving entity review...");
    try {
      await api.updateEntity(entityId, {
        status,
        entity_type: entityType,
        review_notes: status === "hidden" ? "Hidden from admin review queue" : "Reviewed in dashboard",
      });
      setEntityReviewStatus("Saved");
      queryClient.invalidateQueries({ queryKey: ["entity-review"] });
      queryClient.invalidateQueries({ queryKey: ["entity-lexicon-coverage"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
    } catch (error) {
      setEntityReviewStatus(error instanceof Error ? error.message : "Review failed");
    }
  }

  async function mergeEntity(entityId: number) {
    const targetEntityId = Number(mergeTargets[entityId]);
    if (!targetEntityId) {
      setEntityReviewStatus("Choose a target entity first.");
      return;
    }
    setEntityReviewStatus("Merging entity...");
    try {
      await api.mergeEntity(entityId, targetEntityId);
      setEntityReviewStatus("Merged");
      setMergeTargets({ ...mergeTargets, [entityId]: "" });
      queryClient.invalidateQueries({ queryKey: ["entity-review"] });
      queryClient.invalidateQueries({ queryKey: ["entity-lexicon-coverage"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
    } catch (error) {
      setEntityReviewStatus(error instanceof Error ? error.message : "Merge failed");
    }
  }

  async function bulkHideNoiseEntities() {
    setEntityReviewStatus("Checking entity quality...");
    try {
      const result = await api.bulkHideNoiseEntities();
      setEntityReviewStatus(`Auto-hidden ${result.hidden} noisy entities after checking ${result.checked}.`);
      queryClient.invalidateQueries({ queryKey: ["entity-review"] });
      queryClient.invalidateQueries({ queryKey: ["entity-quality-report"] });
      queryClient.invalidateQueries({ queryKey: ["entity-lexicon-coverage"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
      queryClient.invalidateQueries({ queryKey: ["political-risk"] });
    } catch (error) {
      setEntityReviewStatus(error instanceof Error ? error.message : "Bulk cleanup failed");
    }
  }

  async function mergeLexiconAliases() {
    setEntityReviewStatus("Merging curated lexicon aliases...");
    try {
      const result = await api.mergeLexiconAliases();
      setEntityReviewStatus(`Merged ${result.merged} alias entities from ${result.checked_aliases} curated aliases.`);
      queryClient.invalidateQueries({ queryKey: ["entity-review"] });
      queryClient.invalidateQueries({ queryKey: ["entity-quality-report"] });
      queryClient.invalidateQueries({ queryKey: ["entity-lexicon-coverage"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
      queryClient.invalidateQueries({ queryKey: ["political-risk"] });
    } catch (error) {
      setEntityReviewStatus(error instanceof Error ? error.message : "Alias merge failed");
    }
  }

  async function addEntityToLexicon(entityId: number) {
    setEntityLexiconStatus("Adding entity to curated lexicon...");
    try {
      const result = await api.addEntityToLexicon(entityId);
      setEntityLexiconStatus(
        result.status === "already_exists"
          ? `${result.name} is already in the curated lexicon.`
          : `${result.name} added to the curated lexicon. Backup created before writing.`,
      );
      queryClient.invalidateQueries({ queryKey: ["entity-lexicon-coverage"] });
      queryClient.invalidateQueries({ queryKey: ["entity-review"] });
      queryClient.invalidateQueries({ queryKey: ["entity-quality-report"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
      queryClient.invalidateQueries({ queryKey: ["political-risk"] });
    } catch (error) {
      setEntityLexiconStatus(error instanceof Error ? error.message : "Could not add entity to lexicon");
    }
  }

  function refreshQualityViews() {
    queryClient.invalidateQueries({ queryKey: ["article-quality"] });
    queryClient.invalidateQueries({ queryKey: ["articles"] });
    queryClient.invalidateQueries({ queryKey: ["story-clusters"] });
    queryClient.invalidateQueries({ queryKey: ["story-spread"] });
    queryClient.invalidateQueries({ queryKey: ["political-risk"] });
    queryClient.invalidateQueries({ queryKey: ["launch-checklist"] });
    queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
    queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
  }

  async function reviewArticleQuality(articleId: number, status: "approved" | "needs_review" | "excluded") {
    setArticleQualityStatus("Saving article quality review...");
    try {
      await api.updateArticleQuality(articleId, {
        quality_status: status,
        quality_notes: status === "excluded"
          ? "Excluded from intelligence from admin article quality audit."
          : status === "approved"
            ? "Approved from admin article quality audit."
            : "Marked for manual review from admin article quality audit.",
      });
      setArticleQualityStatus(
        status === "excluded"
          ? "Article excluded from intelligence outputs."
          : status === "approved"
            ? "Article approved."
            : "Article marked for review.",
      );
      refreshQualityViews();
    } catch (error) {
      setArticleQualityStatus(error instanceof Error ? error.message : "Article quality review failed");
    }
  }

  async function bulkExcludeQualityArticles() {
    setArticleQualityStatus("Excluding currently flagged article-quality issues...");
    try {
      const result = await api.bulkExcludeQualityArticles();
      setArticleQualityStatus(`Excluded ${result.excluded} flagged articles from intelligence outputs.`);
      refreshQualityViews();
    } catch (error) {
      setArticleQualityStatus(error instanceof Error ? error.message : "Bulk article exclusion failed");
    }
  }

  async function rebuildStoryClusters() {
    try {
      await api.rebuildStoryClusters();
      queryClient.invalidateQueries({ queryKey: ["story-clusters"] });
      queryClient.invalidateQueries({ queryKey: ["story-spread"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch {
      // Manual rebuild is a convenience; the CLI script remains the fallback.
    }
  }

  async function createRiskAlert(suggestion: PoliticalRisk["alert_suggestions"][number]) {
    setRiskAlertStatus("Creating alert...");
    try {
      await api.createRiskAlertSuggestion({
        suggestion_type: suggestion.type,
        label: suggestion.label,
        criteria: suggestion.criteria,
        user_email: currentUser?.email || "admin@newsintel.local",
        country_code: "mk",
        channel: "in_app",
        cooldown_minutes: 60,
      });
      setRiskAlertStatus("Alert created. It will appear in Alerts.");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      setRiskAlertStatus(error instanceof Error ? error.message : "Alert creation failed");
    }
  }

  async function fetchFacebookNow() {
    setFacebookFetchStatus("Fetching Facebook pages...");
    try {
      const result = await api.fetchFacebook();
      setLastFacebookFetch(result);
      setFacebookFetchStatus("Facebook fetch finished");
      queryClient.invalidateQueries({ queryKey: ["facebook-status"] });
      queryClient.invalidateQueries({ queryKey: ["articles"] });
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["narratives"] });
    } catch (error) {
      setFacebookFetchStatus(error instanceof Error ? error.message : "Facebook fetch failed");
    }
  }

  async function processQueueNow() {
    setOpsStatus("Processing saved article queue...");
    try {
      const result = await api.processQueue();
      setOpsStatus(`Processed ${result.processed} articles with ${result.errors} errors.`);
      queryClient.invalidateQueries({ queryKey: ["articles"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
      queryClient.invalidateQueries({ queryKey: ["political-risk"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["source-reliability"] });
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] });
      queryClient.invalidateQueries({ queryKey: ["live-ops"] });
      queryClient.invalidateQueries({ queryKey: ["client-brief-readiness"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch (error) {
      setOpsStatus(error instanceof Error ? error.message : "Processing failed");
    }
  }

  async function runIngestionNow() {
    setOpsStatus("Running scraper/RSS ingestion now. This can take a few minutes...");
    try {
      const ingest = await api.ingestNow();
      setOpsStatus(`Ingestion saved ${ingest.new} new articles, skipped ${ingest.duplicate} duplicates. Processing queue...`);
      const process = await api.processQueue();
      setOpsStatus(
        `Ingestion complete: ${ingest.new} new / ${ingest.duplicate} duplicates. Processed ${process.processed} articles. Rebuilding clusters...`
      );
      await api.rebuildStoryClusters();
      setOpsStatus(`Done: ${ingest.new} new articles, ${ingest.duplicate} duplicates, ${process.processed} processed.`);
      queryClient.invalidateQueries({ queryKey: ["articles"] });
      queryClient.invalidateQueries({ queryKey: ["entities"] });
      queryClient.invalidateQueries({ queryKey: ["trends"] });
      queryClient.invalidateQueries({ queryKey: ["political-risk"] });
      queryClient.invalidateQueries({ queryKey: ["story-clusters"] });
      queryClient.invalidateQueries({ queryKey: ["story-spread"] });
      queryClient.invalidateQueries({ queryKey: ["article-quality"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["source-reliability"] });
      queryClient.invalidateQueries({ queryKey: ["ingestion-runs"] });
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] });
      queryClient.invalidateQueries({ queryKey: ["live-ops"] });
      queryClient.invalidateQueries({ queryKey: ["client-brief-readiness"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch (error) {
      setOpsStatus(error instanceof Error ? error.message : "Ingestion failed");
    }
  }

  async function runSchedulerAction(action: "start" | "stop" | "run_once") {
    setSchedulerActionStatus(`${action.replace("_", " ")} requested...`);
    try {
      const result = action === "start"
        ? await api.startScheduler()
        : action === "stop"
          ? await api.stopScheduler()
          : await api.runSchedulerOnce();
      setSchedulerActionStatus(`Scheduler ${String(result.status || action)}.`);
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] });
      queryClient.invalidateQueries({ queryKey: ["live-ops"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["article-quality"] });
      queryClient.invalidateQueries({ queryKey: ["entity-quality-report"] });
      queryClient.invalidateQueries({ queryKey: ["launch-checklist"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch (error) {
      setSchedulerActionStatus(error instanceof Error ? error.message : "Scheduler action failed");
    }
  }

  async function createDatabaseBackup() {
    setBackupStatusText("Creating backup...");
    try {
      const result = await api.createBackup();
      setBackupStatusText(`Backup created: ${result.filename}`);
      queryClient.invalidateQueries({ queryKey: ["backups"] });
      queryClient.invalidateQueries({ queryKey: ["launch-checklist"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch (error) {
      setBackupStatusText(error instanceof Error ? error.message : "Backup failed");
    }
  }

  async function showRestorePlan(filename: string) {
    setBackupStatusText("Preparing restore steps...");
    try {
      const result = await api.restorePlan(filename);
      setBackupStatusText(result.steps.join(" | "));
    } catch (error) {
      setBackupStatusText(error instanceof Error ? error.message : "Could not prepare restore plan");
    }
  }

  async function updateSourceConfig(sourceId: number, input: SourceUpdateInput) {
    setSourceConfigStatus("Updating source...");
    try {
      await api.updateSource(sourceId, input);
      setSourceConfigStatus("Source updated.");
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["source-config-validation"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["source-reliability"] });
      queryClient.invalidateQueries({ queryKey: ["launch-checklist"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch (error) {
      setSourceConfigStatus(error instanceof Error ? error.message : "Could not update source");
    }
  }

  async function syncSourcesFromConfig() {
    setSourceConfigStatus("Syncing YAML sources to database...");
    try {
      const result = await api.syncSourcesFromConfig();
      setSourceConfigStatus(
        `Source sync complete: ${result.created_count} created, ${result.updated_count} updated, ${result.unchanged_count} unchanged.`
      );
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      queryClient.invalidateQueries({ queryKey: ["source-config-validation"] });
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["source-reliability"] });
      queryClient.invalidateQueries({ queryKey: ["launch-checklist"] });
      queryClient.invalidateQueries({ queryKey: ["intelligence-qa"] });
      queryClient.invalidateQueries({ queryKey: ["ops-fix-queue"] });
    } catch (error) {
      setSourceConfigStatus(error instanceof Error ? error.message : "Source sync failed");
    }
  }

  async function openSourceDrilldown(sourceName: string) {
    setSourceConfigStatus("Loading source drilldown...");
    try {
      const result = await api.sourceDrilldown(sourceName);
      setSelectedSourceDrilldown(result);
      setSourceConfigStatus("");
    } catch (error) {
      setSourceConfigStatus(error instanceof Error ? error.message : "Could not load source drilldown");
    }
  }

  async function runSourcePreflight(sourceId: number) {
    setScraperPreflightStatus("Running scraper preflight...");
    try {
      const result = await api.sourcePreflight(sourceId);
      setSelectedScraperPreflight(result);
      setScraperPreflightStatus(`${result.source_name}: ${result.status}, ${result.success_count}/${result.discovered_urls} extracted.`);
    } catch (error) {
      setScraperPreflightStatus(error instanceof Error ? error.message : "Scraper preflight failed");
    }
  }

  async function runPilotPreflight() {
    setScraperPreflightStatus("Running pilot preflight on top sources...");
    try {
      const result = await api.scraperPreflight();
      const failing = result.sources.filter((source) => ["failing", "no_links", "error"].includes(source.status));
      setSelectedScraperPreflight(result.sources[0]);
      setScraperPreflightStatus(
        `Preflight complete: ${result.summary.healthy || 0} healthy, ${result.summary.degraded || 0} degraded, ${failing.length} failing.`
      );
      queryClient.invalidateQueries({ queryKey: ["source-health"] });
      queryClient.invalidateQueries({ queryKey: ["source-reliability"] });
    } catch (error) {
      setScraperPreflightStatus(error instanceof Error ? error.message : "Pilot preflight failed");
    }
  }

  async function deactivateAlert(alertId: number) {
    setAlertOpsStatus("Updating alert...");
    try {
      await api.deleteAlert(alertId);
      setAlertOpsStatus("Alert deactivated.");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      setAlertOpsStatus(error instanceof Error ? error.message : "Could not deactivate alert");
    }
  }

  async function saveClient(event: React.FormEvent) {
    event.preventDefault();
    setClientSaveStatus("Saving...");
    try {
      const created = await api.createClient(clientForm);
      setSelectedClientId(created.id);
      setClientSaveStatus("Saved");
      setClientForm({
        ...clientForm,
        name: "",
        email: "",
      });
      queryClient.invalidateQueries({ queryKey: ["clients"] });
    } catch (error) {
      setClientSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function saveUser(event: React.FormEvent) {
    event.preventDefault();
    setUserSaveStatus("Saving...");
    try {
      await api.createUser({
        ...userForm,
        client_id: userForm.role === "client" ? userForm.client_id : null,
      });
      setUserSaveStatus("Saved");
      setUserForm({
        email: "",
        name: "",
        password: "",
        role: "client",
        client_id: null,
        is_active: true,
      });
      queryClient.invalidateQueries({ queryKey: ["users"] });
    } catch (error) {
      setUserSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function createDigestSubscription(event: React.FormEvent) {
    event.preventDefault();
    setSubscriptionStatus("Saving subscription...");
    const categories = subscriptionCategoriesText
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    try {
      const created = await api.createSubscription({
        ...subscriptionForm,
        categories: categories.length ? categories : [],
      });
      setSubscriptionStatus(`Subscription saved for ${created.email}.`);
      queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
      setSubscriptionForm({
        email: "",
        name: "",
        country_code: "mk",
        categories: [],
        frequency: "daily",
        format: "pdf",
      });
      setSubscriptionCategoriesText("");
    } catch (error) {
      setSubscriptionStatus(error instanceof Error ? error.message : "Could not save subscription");
    }
  }

  async function cancelDigestSubscription(subscriptionId: number) {
    setSubscriptionStatus("Cancelling subscription...");
    try {
      await api.cancelSubscription(subscriptionId);
      setSubscriptionStatus("Subscription cancelled.");
      queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    } catch (error) {
      setSubscriptionStatus(error instanceof Error ? error.message : "Could not cancel subscription");
    }
  }

  function prefillSubscriptionFromClient() {
    const client = clientDash?.client ?? clientData.find((item) => item.id === activeClientId);
    setSubscriptionForm({
      email: client?.email || "",
      name: client?.name || "",
      country_code: client?.country_code || "mk",
      categories: [],
      frequency: "daily",
      format: "pdf",
    });
    setSubscriptionCategoriesText("");
    setClientTab("reports");
  }

  async function saveWatchlistItem(event: React.FormEvent) {
    event.preventDefault();
    if (!activeClientId) {
      setWatchlistSaveStatus("Select or create a client first");
      return;
    }
    setWatchlistSaveStatus("Saving...");
    try {
      const inferred = inferWatchlistPayload();
      const payload: WatchlistItemInput = {
        ...watchlistForm,
        ...inferred,
        entity_id: inferred.entity_id ?? watchlistForm.entity_id ?? null,
        source_id: inferred.source_id ?? watchlistForm.source_id ?? null,
        facebook_page_url: (inferred.facebook_page_url ?? watchlistForm.facebook_page_url) || undefined,
      };
      await api.addWatchlistItem(activeClientId, payload);
      setWatchlistSaveStatus("Saved");
      setWatchlistForm({
        ...watchlistForm,
        label: "",
        value: "",
        entity_id: null,
        source_id: null,
        facebook_page_url: "",
        notes: "",
      });
      setEntityPicker("");
      setSourcePicker("");
      setFacebookPicker("");
      queryClient.invalidateQueries({ queryKey: ["client-dashboard", activeClientId] });
    } catch (error) {
      setWatchlistSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  function updateWatchlistType(itemType: string) {
    setWatchlistForm({
      ...watchlistForm,
      item_type: itemType,
      label: "",
      value: "",
      entity_id: null,
      source_id: null,
      facebook_page_url: "",
    });
    setEntityPicker("");
    setSourcePicker("");
    setFacebookPicker("");
  }

  async function askClientChat(questionOverride?: string) {
    if (!activeClientId) return;
    const question = (questionOverride ?? clientChatQuestion).trim();
    if (!question) return;
    setClientChatQuestion(question);
    setClientChatStatus("Searching permitted client data...");
    try {
      const answer = await api.clientChat(activeClientId, {
        question,
        days: 30,
        mode: "auto",
        include_wider_context: currentUser?.role === "admin" || currentUser?.role === "analyst",
        conversation_id: clientChatConversationId,
      });
      setClientChatAnswer(answer);
      setClientChatConversationId(answer.conversation_id);
      setClientChatStatus(answer.saved_briefing_id ? `Saved to chat history #${answer.saved_briefing_id}.` : "Answer ready.");
      queryClient.invalidateQueries({ queryKey: ["saved-briefings", activeClientId] });
    } catch (error) {
      setClientChatStatus(error instanceof Error ? error.message : "Could not answer from client data");
    }
  }

  function startNewClientChat() {
    setClientChatConversationId(undefined);
    setClientChatAnswer(undefined);
    setClientChatQuestion("");
    setClientChatStatus("New conversation ready.");
  }

  async function openResponsePack(watchlistItemId: number) {
    if (!activeClientId) return;
    setResponsePackStatus("Preparing response pack...");
    try {
      const pack = await api.responsePack(activeClientId, watchlistItemId);
      setSelectedResponsePack(pack);
      setResponseDraftLanguage("en");
      setResponsePackStatus("");
    } catch (error) {
      setResponsePackStatus(error instanceof Error ? error.message : "Could not prepare response pack");
    }
  }

  async function saveRiskItemAsIncident(watchlistItemId: number) {
    if (!activeClientId) return;
    setIncidentSaveStatus("Preparing case file...");
    try {
      const pack = await api.responsePack(activeClientId, watchlistItemId);
      await api.createIncident(activeClientId, {
        watchlist_item_id: pack.watchlist_item.id,
        title: pack.watchlist_item.label,
        severity: pack.severity,
        status: pack.severity === "critical" ? "legal_review" : "open",
        summary: pack.situation_summary,
        recommended_posture: pack.recommended_posture,
        legal_review_flags: pack.legal_review_flags,
        evidence_steps: pack.evidence_steps,
        draft_responses: pack.draft_responses,
        source_article_ids: pack.source_articles.map((article) => article.id),
      });
      setIncidentSaveStatus("Case saved with evidence trail.");
      queryClient.invalidateQueries({ queryKey: ["client-incidents", activeClientId] });
    } catch (error) {
      setIncidentSaveStatus(error instanceof Error ? error.message : "Could not save case");
    }
  }

  async function createWatchlistAlert(itemId: number) {
    const item = clientDash?.watchlist.find((entry) => entry.id === itemId);
    if (!item) return;
    setWatchlistAlertStatus("Creating watchlist alert...");
    const criteria = item.entity_id
      ? { entity_id: item.entity_id, source: "watchlist" }
      : { keywords: [item.value || item.label], match_all: false, source: "watchlist", source_id: item.source_id };
    const alertType = item.entity_id ? "entity" : "keyword";
    try {
      await api.createAlert({
        name: `Watchlist: ${item.label}`,
        user_email: currentUser?.email || "admin@newsintel.local",
        alert_type: alertType,
        channel: "in_app",
        criteria,
        country_code: "mk",
        cooldown_minutes: item.priority <= 2 ? 30 : 120,
      });
      setWatchlistAlertStatus(`Alert created for ${item.label}.`);
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      setWatchlistAlertStatus(error instanceof Error ? error.message : "Could not create alert");
    }
  }

  async function createSavedTopicAlert(topic: SavedTopicWatch, alertMode: "new_article" | "multi_source" | "attack_language") {
    setWatchlistAlertStatus("Creating topic alert...");
    const baseCriteria = {
      keywords: [topic.watchlist_item.value || topic.watchlist_item.label],
      match_all: false,
      watchlist_item_id: topic.watchlist_item.id,
    };
    const alertConfig = alertMode === "multi_source"
      ? { alert_type: "story_spread", criteria: { ...baseCriteria, min_sources: 2 } }
      : alertMode === "attack_language"
        ? { alert_type: "attack_theme", criteria: { ...baseCriteria, attack_language: true } }
        : { alert_type: "keyword", criteria: baseCriteria };
    try {
      await api.createAlert({
        name: `${topic.watchlist_item.label}: ${alertMode.replaceAll("_", " ")}`,
        user_email: currentUser?.email || "admin@newsintel.local",
        alert_type: alertConfig.alert_type,
        channel: "in_app",
        criteria: alertConfig.criteria,
        country_code: "mk",
        cooldown_minutes: alertMode === "new_article" ? 60 : 30,
      });
      setWatchlistAlertStatus(`Topic alert created for ${topic.watchlist_item.label}.`);
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      setWatchlistAlertStatus(error instanceof Error ? error.message : "Could not create topic alert");
    }
  }

  async function createStoryClusterAlert(cluster: StoryCluster) {
    setStoryStatus("Creating story spread alert...");
    try {
      await api.createAlert({
        name: `Story spread: ${cluster.title.slice(0, 80)}`,
        user_email: currentUser?.email || "admin@newsintel.local",
        alert_type: "story_spread",
        channel: "in_app",
        criteria: {
          cluster_id: cluster.id,
          min_sources: Math.max(2, cluster.source_count),
          title: cluster.title,
          country_code: cluster.country_code,
        },
        country_code: cluster.country_code,
        cooldown_minutes: 30,
      });
      setStoryStatus("Story spread alert created.");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (error) {
      setStoryStatus(error instanceof Error ? error.message : "Could not create story alert");
    }
  }

  async function openAttackTimeline(watchlistItemId: number) {
    if (!activeClientId) return;
    setTimelineStatus("Loading timeline...");
    try {
      const timeline = await api.attackTimeline(activeClientId, watchlistItemId);
      setSelectedTimeline(timeline);
      setTimelineStatus("");
    } catch (error) {
      setTimelineStatus(error instanceof Error ? error.message : "Could not load timeline");
    }
  }

  async function loadResponsePackTimeline() {
    if (!activeClientId || !selectedResponsePack) return;
    setResponsePackStatus("Loading attack timeline...");
    try {
      const timeline = await api.attackTimeline(activeClientId, selectedResponsePack.watchlist_item.id);
      setSelectedTimeline(timeline);
      setResponsePackStatus("Attack timeline loaded.");
    } catch (error) {
      setResponsePackStatus(error instanceof Error ? error.message : "Could not load attack timeline");
    }
  }

  async function saveResponsePackAsIncident() {
    if (!activeClientId || !selectedResponsePack) return;
    setIncidentSaveStatus("Saving case...");
    try {
      await api.createIncident(activeClientId, {
        watchlist_item_id: selectedResponsePack.watchlist_item.id,
        title: selectedResponsePack.watchlist_item.label,
        severity: selectedResponsePack.severity,
        status: selectedResponsePack.severity === "critical" ? "legal_review" : "open",
        summary: selectedResponsePack.situation_summary,
        recommended_posture: selectedResponsePack.recommended_posture,
        legal_review_flags: selectedResponsePack.legal_review_flags,
        evidence_steps: selectedResponsePack.evidence_steps,
        draft_responses: selectedResponsePack.draft_responses,
        source_article_ids: selectedResponsePack.source_articles.map((article) => article.id),
      });
      setIncidentSaveStatus("Case saved");
      queryClient.invalidateQueries({ queryKey: ["client-incidents", activeClientId] });
    } catch (error) {
      setIncidentSaveStatus(error instanceof Error ? error.message : "Could not save case");
    }
  }

  async function updateIncidentStatus(status: string) {
    if (!activeClientId || !selectedIncident) return;
    setIncidentUpdateStatus("Updating...");
    try {
      const updated = await api.updateIncident(activeClientId, selectedIncident.id, { status });
      setSelectedIncident(updated);
      setIncidentUpdateStatus("Updated");
      queryClient.invalidateQueries({ queryKey: ["client-incidents", activeClientId] });
    } catch (error) {
      setIncidentUpdateStatus(error instanceof Error ? error.message : "Could not update case");
    }
  }

  function updateResponseDraftStatus(draft: ResponseDraft, status: string) {
    if (!selectedResponsePack) return;
    const draftKey = draft.version_id || draft.tone;
    const updatedDrafts = selectedResponsePack.draft_responses.map((item) => {
      const itemKey = item.version_id || item.tone;
      if (itemKey !== draftKey) return item;
      const publicReadiness = status === "public_ready" ? "usable_with_citations" : status === "legal_review" ? "hold" : item.public_readiness;
      return { ...item, status, public_readiness: publicReadiness };
    });
    setSelectedResponsePack({ ...selectedResponsePack, draft_responses: updatedDrafts });
    setResponsePackReportStatus("Draft status updated. Save the pack or case to persist it.");
  }

  async function updateIncidentDraftStatus(draft: ResponseDraft, status: string) {
    if (!activeClientId || !selectedIncident) return;
    const draftKey = draft.version_id || draft.tone;
    const updatedDrafts = selectedIncident.draft_responses.map((item) => {
      const itemKey = item.version_id || item.tone;
      if (itemKey !== draftKey) return item;
      const publicReadiness = status === "public_ready" ? "usable_with_citations" : status === "legal_review" ? "hold" : item.public_readiness;
      return { ...item, status, public_readiness: publicReadiness };
    });
    setIncidentUpdateStatus("Updating draft status...");
    try {
      const updated = await api.updateIncident(activeClientId, selectedIncident.id, { draft_responses: updatedDrafts });
      setSelectedIncident(updated);
      setIncidentUpdateStatus("Draft status updated.");
      queryClient.invalidateQueries({ queryKey: ["client-incidents", activeClientId] });
    } catch (error) {
      setIncidentUpdateStatus(error instanceof Error ? error.message : "Could not update draft status");
    }
  }

  async function saveEvidence(event: React.FormEvent) {
    event.preventDefault();
    if (!activeClientId || !selectedIncident) return;
    setEvidenceStatus("Saving evidence...");
    try {
      await api.createEvidence(activeClientId, selectedIncident.id, evidenceForm);
      setEvidenceForm({
        url: "",
        title: "",
        source_name: "",
        evidence_type: "url",
        notes: "",
      });
      setEvidenceStatus("Evidence saved");
      queryClient.invalidateQueries({ queryKey: ["incident-evidence", activeClientId, selectedIncident.id] });
    } catch (error) {
      setEvidenceStatus(error instanceof Error ? error.message : "Could not save evidence");
    }
  }

  async function generateIncidentPdf() {
    if (!activeClientId || !selectedIncident) return;
    setIncidentReportStatus("Generating PDF...");
    try {
      const report = await api.generateIncidentReport(activeClientId, selectedIncident.id);
      const url = `${API_BASE}/api/v1/reports/${report.report_id}/download`;
      window.open(url, "_blank", "noopener,noreferrer");
      setIncidentReportStatus(`PDF ready: report #${report.report_id}`);
    } catch (error) {
      setIncidentReportStatus(error instanceof Error ? error.message : "Could not generate PDF");
    }
  }

  function partyBriefingPayload(): PartyBriefingInput {
    const splitList = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
    return {
      ...partyBriefingForm,
      include_entities: splitList(partyEntitiesText),
      include_opponents: splitList(partyOpponentsText),
      date_from: partyBriefingForm.date_from ? `${partyBriefingForm.date_from}T00:00:00` : undefined,
      date_to: partyBriefingForm.date_to ? `${partyBriefingForm.date_to}T23:59:59` : undefined,
    };
  }

  function applyPressPrepTemplate(template: (typeof pressPrepTemplates)[number]) {
    setPartyBriefingForm({
      ...partyBriefingForm,
      objective: template.objective,
      requirements: template.requirements,
      audience: template.audience,
      tone: template.tone,
      include_legal_context: true,
      include_watchlist: true,
      max_articles: template.max_articles,
    });
    setPartyBriefingStatus(`${template.label} template applied.`);
  }

  async function preparePartyBriefing(event?: React.FormEvent) {
    event?.preventDefault();
    if (!activeClientId) {
      setPartyBriefingStatus("Select or create a client first");
      return;
    }
    setPartyBriefingStatus("Preparing briefing...");
    try {
      const briefing = await api.partyBriefing(activeClientId, partyBriefingPayload());
      setPartyBriefing(briefing);
      setPartyBriefingStatus("Briefing ready");
    } catch (error) {
      setPartyBriefingStatus(error instanceof Error ? error.message : "Could not prepare briefing");
    }
  }

  async function generatePartyBriefingPdf() {
    if (!activeClientId) return;
    setPartyBriefingReportStatus("Generating briefing PDF...");
    try {
      const report = await api.generatePartyBriefingReport(activeClientId, partyBriefingPayload());
      window.open(`${API_BASE}/api/v1/reports/${report.report_id}/download`, "_blank", "noopener,noreferrer");
      setPartyBriefingReportStatus(`PDF ready: report #${report.report_id}`);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    } catch (error) {
      setPartyBriefingReportStatus(error instanceof Error ? error.message : "Could not generate briefing PDF");
    }
  }

  async function generateClientBriefPdf() {
    if (!activeClientId) return;
    setClientBriefReportStatus("Generating client brief PDF...");
    try {
      const report = await api.generateClientDailyBriefReport(activeClientId);
      window.open(`${API_BASE}/api/v1/reports/${report.report_id}/download`, "_blank", "noopener,noreferrer");
      setClientBriefReportStatus(`PDF ready: report #${report.report_id}`);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    } catch (error) {
      setClientBriefReportStatus(error instanceof Error ? error.message : "Could not generate client brief PDF");
    }
  }

  async function generateResponsePackPdf() {
    if (!activeClientId || !selectedResponsePack) return;
    setResponsePackReportStatus("Generating response PDF...");
    try {
      const report = await api.generateResponsePackReport(activeClientId, selectedResponsePack.watchlist_item.id);
      window.open(`${API_BASE}/api/v1/reports/${report.report_id}/download`, "_blank", "noopener,noreferrer");
      setResponsePackReportStatus(`PDF ready: report #${report.report_id}`);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    } catch (error) {
      setResponsePackReportStatus(error instanceof Error ? error.message : "Could not generate response PDF");
    }
  }

  async function saveStructuredBriefing(input: SavedBriefingInput) {
    if (!activeClientId) return;
    setSavedBriefingStatus("Saving briefing...");
    try {
      const saved = await api.createSavedBriefing(activeClientId, input);
      setSelectedSavedBriefing(saved);
      setSavedBriefingStatus("Briefing saved.");
      queryClient.invalidateQueries({ queryKey: ["saved-briefings", activeClientId] });
    } catch (error) {
      setSavedBriefingStatus(error instanceof Error ? error.message : "Could not save briefing");
    }
  }

  async function updateSavedBriefing(briefingId: number, input: Partial<SavedBriefingInput>) {
    if (!activeClientId) return;
    setSavedBriefingStatus("Updating saved briefing...");
    try {
      const saved = await api.updateSavedBriefing(activeClientId, briefingId, input);
      setSelectedSavedBriefing(saved);
      setSavedBriefingStatus("Saved briefing updated.");
      queryClient.invalidateQueries({ queryKey: ["saved-briefings", activeClientId] });
    } catch (error) {
      setSavedBriefingStatus(error instanceof Error ? error.message : "Could not update briefing");
    }
  }

  async function duplicateSavedBriefing(briefingId: number) {
    if (!activeClientId) return;
    setSavedBriefingStatus("Duplicating briefing...");
    try {
      const saved = await api.duplicateSavedBriefing(activeClientId, briefingId);
      setSelectedSavedBriefing(saved);
      setSavedBriefingStatus("Briefing duplicated as a reusable template.");
      queryClient.invalidateQueries({ queryKey: ["saved-briefings", activeClientId] });
    } catch (error) {
      setSavedBriefingStatus(error instanceof Error ? error.message : "Could not duplicate briefing");
    }
  }

  async function exportSavedBriefing(briefingId: number) {
    if (!activeClientId) return;
    setSavedBriefingStatus("Generating saved briefing PDF...");
    try {
      const report = await api.generateSavedBriefingReport(activeClientId, briefingId);
      window.open(`${API_BASE}/api/v1/reports/${report.report_id}/download`, "_blank", "noopener,noreferrer");
      setSavedBriefingStatus(`PDF ready: report #${report.report_id}`);
      queryClient.invalidateQueries({ queryKey: ["saved-briefings", activeClientId] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
    } catch (error) {
      setSavedBriefingStatus(error instanceof Error ? error.message : "Could not export saved briefing");
    }
  }

  function savePartyBriefing() {
    if (!partyBriefing) return;
    saveStructuredBriefing({
      briefing_type: "party_briefing",
      title: `Party Briefing - ${partyBriefing.topic}`,
      country_code: partyBriefing.client.country_code,
      topic: partyBriefing.topic,
      payload: partyBriefing as unknown as Record<string, unknown>,
      source_article_ids: partyBriefing.source_articles.map((article) => article.id),
      confidence: partyBriefing.confidence,
    });
  }

  function saveClientDailyBrief() {
    if (!clientDailyBriefData) return;
    saveStructuredBriefing({
      briefing_type: "client_daily_brief",
      title: clientDailyBriefData.headline,
      country_code: clientDailyBriefData.client.country_code,
      payload: clientDailyBriefData as unknown as Record<string, unknown>,
      source_article_ids: clientDailyBriefData.matched_articles.map((article) => article.id),
      confidence: { risk_items: clientDailyBriefData.risk_items.length },
    });
  }

  function saveResponsePack() {
    if (!selectedResponsePack) return;
    saveStructuredBriefing({
      briefing_type: "response_pack",
      title: `Response Pack - ${selectedResponsePack.watchlist_item.label}`,
      country_code: selectedResponsePack.client.country_code,
      topic: selectedResponsePack.watchlist_item.label,
      watchlist_item_id: selectedResponsePack.watchlist_item.id,
      payload: selectedResponsePack as unknown as Record<string, unknown>,
      source_article_ids: selectedResponsePack.source_articles.map((article) => article.id),
      confidence: selectedResponsePack.confidence,
    });
  }

  function saveTopicBriefing() {
    if (!topicBriefingData || !activeClientId) return;
    saveStructuredBriefing({
      briefing_type: "topic_briefing",
      title: `Topic Briefing - ${topicBriefingData.query}`,
      country_code: topicBriefingData.country_code,
      topic: topicBriefingData.query,
      payload: topicBriefingData as unknown as Record<string, unknown>,
      source_article_ids: topicBriefingData.recent_articles.map((article) => article.id),
      confidence: { validation_status: topicBriefingData.validation_status, source_count: topicBriefingData.source_count },
    });
  }

  async function copyTextToClipboard(text: string, statusSetter: (message: string) => void, readyMessage: string) {
    try {
      await navigator.clipboard.writeText(text);
      statusSetter(readyMessage);
    } catch {
      statusSetter("Clipboard is unavailable in this browser.");
    }
  }

  function partyBriefingCopyText() {
    if (!partyBriefing) return "";
    const strategy = partyBriefing.briefing_strategy || {};
    return [
      `Party Briefing: ${partyBriefing.topic}`,
      partyBriefing.audience ? `Audience: ${partyBriefing.audience}` : "",
      partyBriefing.tone ? `Tone: ${partyBriefing.tone}` : "",
      `Confidence: ${partyBriefing.confidence.score ?? "-"} / 100 (${partyBriefing.confidence.level || "unknown"})`,
      `Source depth: ${partyBriefing.confidence.article_count ?? 0} articles / ${partyBriefing.confidence.source_count ?? 0} sources`,
      strategy.public_posture ? `Press strategy: ${strategy.public_posture}` : "",
      strategy.primary_line ? `Primary line: ${strategy.primary_line}` : "",
      strategy.publication_gate ? `Publication gate: ${strategy.publication_gate}` : "",
      "",
      partyBriefing.coverage_summary,
      "",
      "Press statement:",
      partyBriefing.draft_outputs.press_statement || "",
      "",
      "Short social response:",
      partyBriefing.draft_outputs.short_social_response || "",
      "",
      "Talking points:",
      ...partyBriefing.suggested_talking_points.map((point) => `- ${point}`),
      "",
      "Citation pack:",
      ...partyBriefing.citation_pack.map((item) => `- [${item.label}] ${item.source_name || "Unknown"}: ${item.claim || item.inline} ${item.url || ""}`.trim()),
      "",
      "Claims to verify:",
      ...partyBriefing.claims_to_verify.map((point) => `- ${point}`),
      "",
      "Do not say unless verified:",
      ...partyBriefing.do_not_say_unless_verified.map((point) => `- ${point}`),
      "",
      "Strategy avoid-list:",
      ...(strategy.claims_to_avoid ?? []).map((point) => `- ${point}`),
    ].join("\n");
  }

  function responsePackCopyText() {
    if (!selectedResponsePack) return "";
    const firstDraftItem =
      selectedResponsePack.draft_responses.find((draft) => draft.status === "public_ready" || draft.status === "approved") ||
      selectedResponsePack.draft_responses[0];
    const firstDraft = firstDraftItem ? draftBody(firstDraftItem, responseDraftLanguage) : "";
    const strategy = selectedResponsePack.response_strategy || {};
    return [
      selectedResponsePack.situation_summary,
      "",
      `Posture: ${selectedResponsePack.recommended_posture}`,
      strategy.public_posture ? `Strategy: ${strategy.public_posture}` : "",
      strategy.primary_line ? `Primary line: ${strategy.primary_line}` : "",
      strategy.publication_gate ? `Publication gate: ${strategy.publication_gate}` : "",
      firstDraftItem?.status ? `Draft status: ${firstDraftItem.status.replaceAll("_", " ")}` : "",
      `Language: ${responseDraftLanguage === "mk" ? "Macedonian working draft" : "English"}`,
      `Confidence: ${selectedResponsePack.confidence.score ?? "-"} / 100 (${selectedResponsePack.confidence.level || "unknown"})`,
      `Source depth: ${selectedResponsePack.confidence.article_count ?? 0} articles / ${selectedResponsePack.confidence.source_count ?? 0} sources`,
      "",
      "Suggested response:",
      firstDraft,
      "",
      "Citation pack:",
      ...selectedResponsePack.citation_pack.map((item) => `- [${item.label}] ${item.source_name || "Unknown"}: ${item.claim || item.inline} ${item.url || ""}`.trim()),
      "",
      "Verify before publishing:",
      ...selectedResponsePack.claims_to_verify.map((point) => `- ${point}`),
      "",
      "Do not claim yet:",
      ...(strategy.claims_to_avoid ?? []).map((point) => `- ${point}`),
    ].join("\n");
  }

  async function generateDemoBriefing(topic: string, objective: string, requirements: string) {
    setPartyBriefingForm({
      ...partyBriefingForm,
      topic,
      objective,
      requirements,
      include_watchlist: true,
      max_articles: 20,
    });
    if (!activeClientId) {
      setPartyBriefingStatus("Select or create a client first");
      return;
    }
    setPartyBriefingStatus("Preparing demo briefing...");
    try {
      const payload = {
        ...partyBriefingPayload(),
        topic,
        objective,
        requirements,
        include_watchlist: true,
        max_articles: 20,
      };
      const briefing = await api.partyBriefing(activeClientId, payload);
      setPartyBriefing(briefing);
      setPartyBriefingStatus("Demo briefing ready");
    } catch (error) {
      setPartyBriefingStatus(error instanceof Error ? error.message : "Could not prepare demo briefing");
    }
  }

  function inferWatchlistPayload(): Partial<WatchlistItemInput> {
    if (
      (watchlistForm.item_type === "entity" || watchlistForm.item_type === "opponent")
      && selectedEntity
    ) {
      return {
        label: watchlistForm.label || selectedEntity.name,
        value: watchlistForm.value || selectedEntity.canonical_name,
        entity_id: selectedEntity.id,
        source_id: null,
      };
    }
    if (watchlistForm.item_type === "source" && selectedSource) {
      return {
        label: watchlistForm.label || selectedSource.name,
        value: watchlistForm.value || selectedSource.url,
        entity_id: null,
        source_id: selectedSource.source_id,
      };
    }
    if (watchlistForm.item_type === "facebook_page" && selectedFacebookPage) {
      return {
        label: watchlistForm.label || selectedFacebookPage.name,
        value: watchlistForm.value || selectedFacebookPage.page_handle || selectedFacebookPage.url,
        facebook_page_url: selectedFacebookPage.url,
      };
    }
    return {};
  }

  if (!currentUser) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">NI</div>
          <div>
            <h1>NewsIntel</h1>
            <p>
              {currentUser.role === "client"
                ? clientPersonaConfig(modeClient).title
                : currentUser.role === "admin"
                  ? "Platform control room"
                  : "Analyst console"}
            </p>
          </div>
        </div>

        <nav className="nav" aria-label="Primary">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={`nav-item ${view === item.id ? "is-active" : ""}`}
                key={item.id}
                onClick={() => setView(item.id)}
              >
                <Icon size={18} />
                <span>{navLabel(item.id, currentUser)}</span>
              </button>
            );
          })}
        </nav>

        <div className="api-card">
          <CircleDot className={apiOnline ? "ok" : "bad"} size={18} />
          <div>
            <p className="eyebrow">API</p>
            <strong>{apiOnline ? "Connected" : "Offline"}</strong>
          </div>
        </div>
        <div className="api-card">
          <ShieldCheck size={18} />
          <div>
            <p className="eyebrow">{currentUser.role}</p>
            <strong>{currentUser.name}</strong>
          </div>
        </div>
        <button className="nav-item" onClick={signOut}>
          <span>Sign out</span>
        </button>
        <div className="api-base">{API_BASE}</div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{view === "overview" ? country?.name ?? "North Macedonia" : "News intelligence"}</p>
            <h2>{navLabel(view, currentUser)}</h2>
          </div>
          <div className="topbar-actions">
            {currentUser.role !== "client" ? (
              <>
                <form
                  className="search-shell"
                  role="search"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setView("articles");
                  }}
                >
                  <Search size={17} aria-hidden="true" />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    type="search"
                    aria-label="Search people, topics, and articles"
                    placeholder="Person, topic, or article"
                  />
                  <button className="search-submit" type="submit" aria-label="Open search results" title="Open search results">
                    <ArrowRight size={17} />
                  </button>
                </form>
                <div className="search-hints" aria-label="Search examples">
                  {["makedonija", "Македонија", "vmro", "dui", "skopje"].map((example) => (
                    <button className="text-button" type="button" key={example} onClick={() => { setSearch(example); setView("articles"); }}>
                      {example}
                    </button>
                  ))}
                </div>
              </>
            ) : null}
            <button className="icon-button" onClick={refreshAll} aria-label="Refresh data" title="Refresh data">
              <RefreshCw size={18} />
            </button>
          </div>
        </header>
        {currentUser.role === "client" && !clientDash ? (
          <div className="workspace-loading-strip" role="status">
            <div>
              <p className="eyebrow">Private workspace</p>
              <strong>Loading intelligence for {currentUser.name}</strong>
            </div>
            <span>Checking mentions, sources, and permissions...</span>
          </div>
        ) : currentUser.role === "client" && isPoliticalFigureClient ? null : (
          <WorkspaceModeStrip user={currentUser} client={modeClient} />
        )}

        {view === "overview" ? (
          <section className="view">
            <DataFreshnessStrip status={schedulerStatusData} />
            <OperationsFreshnessPanel
              scheduler={schedulerStatusData}
              liveOps={liveOpsData}
              sourceHealth={sourceHealthData}
              articleQuality={articleQualityData}
              onStart={currentUser.role === "admin" ? () => runSchedulerAction("start") : undefined}
              onRunOnce={currentUser.role === "admin" ? () => runSchedulerAction("run_once") : undefined}
            />
            {currentUser.role === "admin" ? (
              <PostIngestionCleanupPanel
                opsFixQueue={opsFixQueueData}
                articleQuality={articleQualityData}
                entityQuality={entityQualityData}
                sourceHealth={sourceHealthData}
                onSourceDrilldown={openSourceDrilldown}
                onArticleReview={reviewArticleQuality}
                onEntityHide={(entityId) => reviewEntity(entityId, "hidden")}
                onBulkExclude={bulkExcludeQualityArticles}
              />
            ) : null}
            <div className="metric-grid">
              <Metric label="Articles" value={articles.data?.total ?? "-"} caption="local database" icon={Newspaper} />
              <Metric label="Entities" value={entityData.length} caption="people, orgs, places" icon={UsersRound} />
              <Metric
                label="Sources"
                value={country?.source_count ?? "-"}
                caption={`${country?.feed_count ?? "-"} configured feeds`}
                icon={Globe2}
              />
              <Metric
                label="Alerts"
                value={alertData.filter((alert) => alert.is_active !== false).length}
                caption="active monitoring rules"
                icon={Bell}
                accent
              />
            </div>

            <div className="dashboard-grid">
              <Panel eyebrow="Demo Flow" title="Best Presentation Path" className="span-2">
                <div className="brief-grid">
                  <article className="brief-item">
                    <Search size={20} />
                    <strong>1. Search a topic</strong>
                    <p>Use bilingual search to open Topic Intelligence.</p>
                    <button className="text-button" type="button" onClick={() => { setSearch("makedonija"); setView("articles"); }}>
                      Search makedonija
                    </button>
                  </article>
                  <article className="brief-item">
                    <UsersRound size={20} />
                    <strong>2. Open entity dossier</strong>
                    <p>Show timeline, sentiment, sources, connected entities, copy/PDF.</p>
                    <button className="text-button" type="button" onClick={() => setView("entities")}>
                      Entities
                    </button>
                  </article>
                  <article className="brief-item">
                    <FileText size={20} />
                    <strong>3. Generate client brief</strong>
                    <p>Go to client mode, prepare a party briefing, then export PDF.</p>
                    <button className="text-button" type="button" onClick={() => { setClientTab("briefs"); setView("clients"); }}>
                      Client Briefs
                    </button>
                  </article>
                </div>
              </Panel>
              <Panel eyebrow="Intelligence" title="Analyst Brief" className="span-2">
                {dailyBriefData ? (
                  <div className="stack">
                    <h3>{dailyBriefData.headline}</h3>
                    <div className="brief-grid">
                      <article className="brief-item">
                        <Brain size={20} />
                        <strong>Risk {dailyBriefData.risk.score}/100</strong>
                        <p>{dailyBriefData.risk.drivers[0] || "No major risk drivers."}</p>
                      </article>
                      <article className="brief-item">
                        <CircleDot size={20} />
                        <strong>{dailyBriefData.validated_stories.length} validated stories</strong>
                        <p>{dailyBriefData.validated_stories[0]?.summary || "No validated story in the brief window."}</p>
                      </article>
                      <article className="brief-item">
                        <UsersRound size={20} />
                        <strong>{dailyBriefData.trending_entities[0]?.name || "No top entity"}</strong>
                        <p>{dailyBriefData.recommended_actions[0] || "Continue monitoring."}</p>
                      </article>
                    </div>
                    <div className="tag-row">
                      {dailyBriefData.recommended_actions.slice(0, 4).map((action) => (
                        <Pill key={action} tone="gold">{action}</Pill>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="brief-grid">
                    {brief.map((item) => {
                      const Icon = item.icon;
                      return (
                        <article className="brief-item" key={item.title}>
                          <Icon size={20} />
                          <strong>{item.title}</strong>
                          <p>{item.body}</p>
                        </article>
                      );
                    })}
                  </div>
                )}
              </Panel>

              <RiskPanel
                risk={politicalRiskData}
                title="Political Risk"
                onCreateAlert={createRiskAlert}
                alertStatus={riskAlertStatus}
              />

              <Panel eyebrow="Momentum" title="Trending Entities">
                <div className="stack">
                  {trendData.slice(0, 6).map((trend) => (
                    <TrendCard trend={trend} key={trend.entity_id} />
                  ))}
                </div>
              </Panel>

              <Panel
                eyebrow="Validation"
                title="Cross-Source Stories"
                action={currentUser?.role === "admin" || currentUser?.role === "analyst" ? (
                  <button className="text-button" type="button" onClick={rebuildStoryClusters}>
                    Rebuild
                  </button>
                ) : undefined}
              >
                <div className="stack">
                  {storyClusterData.length ? (
                    storyClusterData.slice(0, 5).map((cluster) => (
                      <article className="trend-card" key={cluster.id}>
                        <div>
                          <div className="card-meta">
                            <Pill tone={cluster.status === "validated" ? "green" : cluster.status === "multi_source" ? "gold" : "coral"}>
                              {cluster.status.replaceAll("_", " ")}
                            </Pill>
                            <Pill>{cluster.source_count} sources</Pill>
                            <Pill>{cluster.high_reliability_source_count} high trust</Pill>
                          </div>
                          <h3>{cluster.title}</h3>
                          <p>{cluster.summary}</p>
                          <div className="tag-row">
                            {cluster.sources.slice(0, 5).map((source) => (
                              <Pill key={`${cluster.id}-${source}`}>{source}</Pill>
                            ))}
                          </div>
                        </div>
                        <div className="trend-score">{cluster.article_count}</div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">No story clusters built yet. Rebuild after ingestion to see validation signals.</div>
                  )}
                </div>
              </Panel>

              <Panel eyebrow="Coverage" title="Categories">
                <CategoryBars categories={categoryData} />
              </Panel>

              <Panel eyebrow="Narratives" title="Political Narratives">
                <div className="stack">
                  {narrativeData.length ? (
                    narrativeData.slice(0, 5).map((narrative) => (
                      <NarrativeCard narrative={narrative} key={narrative.narrative} />
                    ))
                  ) : (
                    <div className="empty-state">No narrative signals yet.</div>
                  )}
                </div>
              </Panel>

              <Panel
                eyebrow="Timeline"
                title={`Daily Coverage by ${dateBasis}`}
                className="span-2"
                action={
                  <select className="compact-select" value={dateBasis} onChange={(event) => setDateBasis(event.target.value)}>
                    <option value="published">Published date</option>
                    <option value="fetched">Fetched date</option>
                    <option value="ingested">Ingested date</option>
                  </select>
                }
              >
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={timelineData}>
                    <CartesianGrid stroke="#e2e8ef" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                    <YAxis width={34} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                    <Tooltip />
                    <Line type="monotone" dataKey="article_count" stroke="#147c80" strokeWidth={3} dot />
                    <Line type="monotone" dataKey="source_count" stroke="#d46255" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </Panel>

              <Panel eyebrow="Sources" title="Source Coverage">
                <div className="source-list compact-source">
                  {sourceData.slice(0, 5).map((source) => (
                    <SourceCard source={source} key={source.source_id} />
                  ))}
                </div>
              </Panel>

              <Panel eyebrow="Latest" title="Recent Articles" className="span-2">
                <div className="article-list compact">
                  {articleData.slice(0, 6).map((article) => (
                    <ArticleCard article={article} key={article.id} onInspect={setSelectedArticle} />
                  ))}
                </div>
              </Panel>
            </div>
          </section>
        ) : null}

        {view === "demo" ? (
          <section className="view">
            {staffAccess ? (
              <PilotReadinessRibbon
                scheduler={schedulerStatusData}
                sourceHealth={sourceHealthData}
                articleQuality={articleQualityData}
                intelligenceQA={intelligenceQAData}
              />
            ) : null}
            <div className="metric-grid">
              <Metric label="Risk" value={politicalRiskData?.score ?? "-"} caption={politicalRiskData?.level ?? "loading"} icon={ShieldCheck} accent />
              <Metric label="Fresh Articles" value={articles.data?.total ?? "-"} caption="stored coverage" icon={Newspaper} />
              <Metric label="Validated Stories" value={storyClusterData.filter((cluster) => cluster.status === "validated").length} caption="cross-source" icon={CircleDot} />
              <Metric label="Client Signals" value={clientDash?.risk_items.length ?? 0} caption="watchlist risks" icon={Bell} />
            </div>

            <div className="dashboard-grid">
              <Panel
                eyebrow="Pilot Readiness"
                title="Daily Operations Command"
                className="span-2"
                action={<Pill tone={launchChecklistData?.overall === "ready" ? "green" : "gold"}>{launchChecklistData?.overall?.replaceAll("_", " ") || "checking"}</Pill>}
              >
                <div className="ops-command-grid">
                  <article className="brief-item">
                    <ShieldCheck size={20} />
                    <strong>Scheduler</strong>
                    <p>
                      {schedulerStatusData
                        ? `${schedulerStatusData.status}; last run ${schedulerStatusData.stale_minutes ?? "unknown"} min ago; heartbeat ${schedulerStatusData.heartbeat?.age_minutes ?? "none"} min.`
                        : "Scheduler status is loading."}
                    </p>
                  </article>
                  <article className="brief-item">
                    <Globe2 size={20} />
                    <strong>Sources</strong>
                    <p>
                      {sourceHealthData?.summary
                        ? `${sourceHealthData.summary.healthy_count} healthy, ${sourceHealthData.summary.attention_count} need attention, ${sourceHealthData.summary.caught_up_count} caught up.`
                        : "Source health is loading."}
                    </p>
                  </article>
                  <article className="brief-item">
                    <FileText size={20} />
                    <strong>Backups</strong>
                    <p>{backupData?.latest ? `Latest backup ${dateLabel(backupData.latest.created_at)}.` : "Create a backup before major ingestion or demos."}</p>
                  </article>
                  <article className="brief-item">
                    <Bell size={20} />
                    <strong>Client Ops</strong>
                    <p>{clientBriefReadinessData.filter((item) => item.ready).length} clients ready for daily briefs; {alertData.filter((alert) => alert.is_active).length} alerts active.</p>
                  </article>
                </div>
                <div className="tag-row ops-action-row">
                  <button className="primary-button inline-action" type="button" onClick={() => runSchedulerAction("start")}>
                    Start Scheduler
                  </button>
                  <button className="text-button" type="button" onClick={() => runSchedulerAction("run_once")}>
                    Run One Cycle
                  </button>
                  <button className="text-button" type="button" onClick={runPilotPreflight}>
                    Scraper Preflight
                  </button>
                  <button className="text-button" type="button" onClick={createDatabaseBackup}>
                    Backup DB
                  </button>
                  <button className="text-button" type="button" onClick={() => setView("admin")}>
                    Admin Detail
                  </button>
                </div>
                {schedulerActionStatus ? <p className="muted">{schedulerActionStatus}</p> : null}
                {scraperPreflightStatus ? <p className="muted">{scraperPreflightStatus}</p> : null}
                {backupStatusText ? <p className="muted">{backupStatusText}</p> : null}
              </Panel>

              <Panel
                eyebrow="Intelligence QA"
                title="Demo Readiness Score"
                action={<Pill tone={(intelligenceQAData?.score ?? 0) >= 80 ? "green" : "gold"}>
                  {intelligenceQAData?.score ?? "-"} / 100
                </Pill>}
              >
                {intelligenceQAData ? (
                  <div className="stack">
                    <div className="tag-row">
                      <Pill tone={intelligenceQAData.status === "demo_ready" ? "green" : "gold"}>
                        {intelligenceQAData.status.replaceAll("_", " ")}
                      </Pill>
                      <Pill>{dateLabel(intelligenceQAData.generated_at)}</Pill>
                    </div>
                    <div className="source-list">
                      {intelligenceQAData.checks.map((check) => (
                        <article className="source-card" key={`qa-${check.key}`}>
                          <div className="source-main">
                            <div>
                              <div className="card-meta">
                                <Pill tone={check.status === "pass" ? "green" : check.status === "fail" ? "coral" : "gold"}>{check.status}</Pill>
                              </div>
                              <strong>{check.label}</strong>
                              <p>{check.detail}</p>
                              {check.status !== "pass" ? <p className="muted">{check.recommendation}</p> : null}
                            </div>
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Intelligence QA is loading.</div>
                )}
              </Panel>

              <Panel eyebrow="Launch Checklist" title="Pilot Gate Checks" className="span-2">
                <div className="brief-grid checklist-grid">
                  {launchChecklistData?.checks.map((check) => (
                    <article className="brief-item" key={`demo-${check.key}`}>
                      <Pill tone={check.status === "pass" ? "green" : check.status === "manual" ? "gold" : "coral"}>
                        {check.status}
                      </Pill>
                      <strong>{check.label}</strong>
                      <p>{check.detail}</p>
                    </article>
                  )) || <div className="empty-state">Launch checklist is loading.</div>}
                </div>
              </Panel>

              <Panel eyebrow="Onboarding" title="Sales Demo Runbook" className="span-2">
                <div className="brief-grid">
                  <article className="brief-item">
                    <Search size={20} />
                    <strong>1. Topic intelligence</strong>
                    <p>Search a Cyrillic or Latin term, then show source spread and evidence.</p>
                    <button className="text-button" type="button" onClick={() => { setSearch("makedonija"); setView("articles"); }}>
                      Open Search
                    </button>
                  </article>
                  <article className="brief-item">
                    <CircleDot size={20} />
                    <strong>2. Story validation</strong>
                    <p>Open a cross-source story and explain single-source vs validated coverage.</p>
                    <button className="text-button" type="button" onClick={() => setView("stories")}>
                      Open Stories
                    </button>
                  </article>
                  <article className="brief-item">
                    <UsersRound size={20} />
                    <strong>3. Entity dossier</strong>
                    <p>Show timeline, sentiment, sources, connected entities, alerts, and PDF.</p>
                    <button className="text-button" type="button" onClick={() => setView("entities")}>
                      Open Entities
                    </button>
                  </article>
                  <article className="brief-item">
                    <FileText size={20} />
                    <strong>4. Party briefing</strong>
                    <p>Generate a source-grounded press briefing with legal and verification guardrails.</p>
                    <button className="text-button" type="button" onClick={() => { setClientTab("briefs"); setView("clients"); }}>
                      Open War Room
                    </button>
                  </article>
                </div>
              </Panel>

              <Panel eyebrow="Demo Brief" title="Executive War Room" className="span-2">
                <div className="stack">
                  <h3>{dailyBriefData?.headline || "North Macedonia intelligence brief"}</h3>
                  <div className="brief-grid">
                    <article className="brief-item">
                      <ShieldCheck size={20} />
                      <strong>Risk posture</strong>
                      <p>{politicalRiskData?.drivers[0] || "Risk score is loading from stored coverage."}</p>
                    </article>
                    <article className="brief-item">
                      <CircleDot size={20} />
                      <strong>Story validation</strong>
                      <p>
                        {storyClusterData[0]
                          ? `${storyClusterData[0].title} is reported by ${storyClusterData[0].original_source_count ?? storyClusterData[0].source_count} original sources.`
                          : "No validated story cluster loaded yet."}
                      </p>
                    </article>
                    <article className="brief-item">
                      <UsersRound size={20} />
                      <strong>Client focus</strong>
                      <p>
                        {clientDash?.risk_items[0]
                          ? `${clientDash.risk_items[0].label}: ${clientDash.risk_items[0].recommended_action}`
                          : "Client watchlist is ready for political figures, parties, agencies, and media analysts."}
                      </p>
                    </article>
                  </div>
                  <div className="tag-row">
                    {(dailyBriefData?.recommended_actions ?? [
                      "Verify sourced claims before response.",
                      "Use source attribution in public statements.",
                      "Monitor cross-source spread before escalation.",
                    ]).slice(0, 4).map((action) => (
                      <Pill tone="gold" key={action}>{action}</Pill>
                    ))}
                  </div>
                </div>
              </Panel>

              <Panel
                eyebrow="Story Spread"
                title="Spread Radar"
                action={<Pill tone={storySpreadData?.summary.validated ? "green" : "gold"}>
                  {storySpreadData?.summary.validated ?? 0} validated
                </Pill>}
              >
                {storySpreadData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Multi-source" value={storySpreadData.summary.multi_source} caption="original portals" icon={Globe2} />
                      <Metric label="Aggregator" value={storySpreadData.summary.aggregator_indexed} caption="indexed spread" icon={Activity} />
                      <Metric label="Single-source" value={storySpreadData.summary.single_source} caption="verify first" icon={Bell} />
                    </div>
                    <div className="source-list">
                      {storySpreadData.stories.slice(0, 5).map((cluster) => (
                        <article className="source-card" key={`spread-${cluster.id}`}>
                          <div className="source-main">
                            <div>
                              <div className="card-meta">
                                <Pill tone={cluster.status === "validated" ? "green" : cluster.status === "multi_source" ? "gold" : "coral"}>
                                  {(cluster.spread_label || cluster.status).replaceAll("_", " ")}
                                </Pill>
                                <Pill>{cluster.original_source_count ?? cluster.source_count} original</Pill>
                                {cluster.aggregator_source_count ? <Pill tone="gold">{cluster.aggregator_source_count} aggregator</Pill> : null}
                                {cluster.spread_velocity !== undefined ? <Pill>{cluster.spread_velocity}/h</Pill> : null}
                              </div>
                              <strong>{cluster.title}</strong>
                              <p>{cluster.validation_explanation}</p>
                            </div>
                            <button className="text-button" type="button" onClick={() => setSelectedStoryCluster(cluster)}>
                              Inspect
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Story spread loads after clusters are built.</div>
                )}
              </Panel>

              <RiskPanel
                risk={politicalRiskData}
                title="Country Risk"
                onCreateAlert={createRiskAlert}
                alertStatus={riskAlertStatus}
              />

              <Panel eyebrow="Source Trust" title="Operational Health">
                {sourceHealthData?.summary ? (
                  <div className="stack">
                    <div className="tag-row">
                      <Pill tone="green">{sourceHealthData.summary.healthy_count} healthy</Pill>
                      <Pill tone="gold">{sourceHealthData.summary.caught_up_count} caught up</Pill>
                      <Pill tone={sourceHealthData.summary.attention_count ? "coral" : "green"}>
                        {sourceHealthData.summary.attention_count} attention
                      </Pill>
                      {sourceHealthData.summary.latest_run_age_minutes !== null && sourceHealthData.summary.latest_run_age_minutes !== undefined ? (
                        <Pill>{sourceHealthData.summary.latest_run_age_minutes} min old</Pill>
                      ) : null}
                    </div>
                    {sourceHealthData.run ? (
                      <div className="metric-grid compact-metrics">
                        <Metric label="New" value={sourceHealthData.run.total_new} caption="last run" icon={Activity} />
                        <Metric
                          label="Dupes"
                          value={sourceHealthData.run.total_duplicate + sourceHealthData.run.total_duplicate_fuzzy}
                          caption="skipped"
                          icon={CircleDot}
                        />
                      </div>
                    ) : null}
                    {sourceHealthData.summary.recommendations.slice(0, 3).map((item) => (
                      <p className="muted" key={item}>{item}</p>
                    ))}
                    <p className="muted">Scheduler target: run ingestion every 10-15 minutes and stop each source once duplicate streaks show it is caught up.</p>
                    <button className="text-button" type="button" onClick={runIngestionNow}>
                      Run Ingestion Now
                    </button>
                    <button className="text-button" type="button" onClick={prefillSubscriptionFromClient}>
                      Set Up Daily Digest
                    </button>
                    {opsStatus ? <p className="muted">{opsStatus}</p> : null}
                  </div>
                ) : (
                  <div className="empty-state">Source health loads for admin users.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Source Trust"
                title="Reliability Scorecard"
                action={<Pill tone={(sourceReliabilityData?.summary.average_score ?? 0) >= 70 ? "green" : "gold"}>
                  {sourceReliabilityData?.summary.average_score ?? "-"} avg
                </Pill>}
              >
                {sourceReliabilityData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Excellent" value={sourceReliabilityData.summary.excellent_count} caption="85+ score" icon={ShieldCheck} />
                      <Metric label="Stable" value={sourceReliabilityData.summary.stable_count} caption="70+ score" icon={Activity} />
                      <Metric label="Watch" value={sourceReliabilityData.summary.watch_count} caption="needs review" icon={Bell} />
                      <Metric label="Broken" value={sourceReliabilityData.summary.broken_count} caption="fix first" icon={CircleDot} />
                    </div>
                    <div className="tag-row">
                      {sourceReliabilityData.summary.recommendations.slice(0, 4).map((item) => (
                        <Pill tone="gold" key={item}>{item}</Pill>
                      ))}
                    </div>
                    <div className="source-list">
                      {sourceReliabilityData.sources.slice(0, 12).map((source) => (
                        <article className="source-card" key={`reliability-${source.source_name}`}>
                          <div className="source-main">
                            <div>
                              <div className="card-meta">
                                <Pill tone={source.status === "excellent" || source.status === "stable" ? "green" : source.status === "watch" ? "gold" : "coral"}>
                                  {source.status}
                                </Pill>
                                <Pill>{source.source_type}</Pill>
                                <Pill>{source.political_leaning}</Pill>
                                {source.configured_reliability !== null && source.configured_reliability !== undefined ? (
                                  <Pill>{Math.round(source.configured_reliability * 100)}% configured</Pill>
                                ) : null}
                              </div>
                              {source.source_url ? (
                                <a href={source.source_url} target="_blank" rel="noreferrer">{source.source_name}</a>
                              ) : (
                                <strong>{source.source_name}</strong>
                              )}
                              <p>
                                {source.new_total} new / {source.duplicate_total} dupes / {source.error_total} errors across {source.attempts} recent runs.
                                {" "}Latest: {source.latest_status.replaceAll("_", " ")} at {dateLabel(source.latest_checked_at)}
                              </p>
                              <div className="tag-row">
                                <Pill>{Math.round(source.duplicate_rate * 100)}% duplicate</Pill>
                                <Pill tone={source.error_rate ? "coral" : "green"}>{Math.round(source.error_rate * 100)}% error</Pill>
                                <Pill>{source.healthy_runs} healthy runs</Pill>
                                {source.stopped_early_runs ? <Pill tone="gold">{source.stopped_early_runs} caught up</Pill> : null}
                              </div>
                              {source.recommendations.slice(0, 2).map((item) => (
                                <p className="muted" key={`${source.source_name}-${item}`}>{item}</p>
                              ))}
                              {source.latest_error_sample ? <p className="limit-warning">{source.latest_error_sample}</p> : null}
                            </div>
                            <div className="trend-score">{source.score}</div>
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Reliability scorecard loads after ingestion history exists.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Automation"
                title="Scheduler Status"
                action={<Pill tone={schedulerStatusData?.stale_warning ? "coral" : "green"}>{schedulerStatusData?.status || "unknown"}</Pill>}
              >
                {schedulerStatusData ? (
                  <div className="stack">
                    <div className="tag-row">
                      <Pill>{schedulerStatusData.interval_minutes} min interval</Pill>
                      <Pill tone={schedulerStatusData.inferred_running ? "green" : "coral"}>
                        {schedulerStatusData.inferred_running ? "inferred running" : "attention needed"}
                      </Pill>
                      <Pill tone={schedulerStatusData.heartbeat?.healthy ? "green" : "gold"}>
                        heartbeat {schedulerStatusData.heartbeat?.age_minutes ?? "none"} min
                      </Pill>
                      {schedulerStatusData.stale_minutes !== null && schedulerStatusData.stale_minutes !== undefined ? (
                        <Pill>{schedulerStatusData.stale_minutes} min old</Pill>
                      ) : null}
                    </div>
                    <p className="muted">Last run: {dateLabel(schedulerStatusData.last_run_at)}. Next expected: {dateLabel(schedulerStatusData.next_expected_run_at)}.</p>
                    {schedulerStatusData.heartbeat?.payload?.status ? (
                      <p className="muted">Heartbeat: {String(schedulerStatusData.heartbeat.payload.status)}.</p>
                    ) : null}
                    <p className="muted">{schedulerStatusData.start_command}</p>
                  </div>
                ) : (
                  <div className="empty-state">Scheduler status loads for admin users.</div>
                )}
              </Panel>

              <Panel eyebrow="Client Defense" title="Watchlist Risks">
                <div className="stack">
                  {clientDash?.risk_items.length ? (
                    clientDash.risk_items.slice(0, 5).map((item) => (
                      <article className="risk-event" key={item.watchlist_item_id}>
                        <div className="card-meta">
                          <Pill tone={item.severity === "critical" || item.severity === "high" ? "coral" : "gold"}>
                            {item.severity}
                          </Pill>
                          <Pill>{item.source_count} sources</Pill>
                          <Pill>{item.article_count} articles</Pill>
                        </div>
                        <strong>{item.label}</strong>
                        <p>{item.recommended_action}</p>
                        <div className="card-meta">
                          <button className="text-button" type="button" onClick={() => openResponsePack(item.watchlist_item_id)}>
                            Response Pack
                          </button>
                          <button className="text-button" type="button" onClick={() => saveRiskItemAsIncident(item.watchlist_item_id)}>
                            Save Case
                          </button>
                          <button className="text-button" type="button" onClick={() => createWatchlistAlert(item.watchlist_item_id)}>
                            Create Alert
                          </button>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">No active client risk items in the selected period.</div>
                  )}
                  {incidentSaveStatus ? <p className="muted">{incidentSaveStatus}</p> : null}
                  {watchlistAlertStatus ? <p className="muted">{watchlistAlertStatus}</p> : null}
                </div>
              </Panel>

              <Panel eyebrow="Daily Digest" title="Morning Brief Preview" className="span-2">
                {dailyBriefData ? (
                  <div className="stack">
                    <div className="card-meta">
                      <Pill tone={dailyBriefData.risk.level === "high" || dailyBriefData.risk.level === "critical" ? "coral" : "gold"}>
                        Risk {dailyBriefData.risk.score}/100
                      </Pill>
                      <Pill>{dailyBriefData.period_days} day window</Pill>
                      <Pill>{dateLabel(dailyBriefData.generated_at)}</Pill>
                    </div>
                    <h3>{dailyBriefData.headline}</h3>
                    <div className="brief-grid">
                      <article className="brief-item">
                        <Newspaper size={20} />
                        <strong>{dailyBriefData.top_articles.length} lead articles</strong>
                        <p>{dailyBriefData.top_articles[0]?.title || "No top article available."}</p>
                      </article>
                      <article className="brief-item">
                        <CircleDot size={20} />
                        <strong>{dailyBriefData.validated_stories.length} validated stories</strong>
                        <p>{dailyBriefData.validated_stories[0]?.summary || "No cross-source story in this brief window."}</p>
                      </article>
                      <article className="brief-item">
                        <UsersRound size={20} />
                        <strong>{dailyBriefData.trending_entities[0]?.name || "No top entity"}</strong>
                        <p>{dailyBriefData.recommended_actions[0] || "Continue monitoring."}</p>
                      </article>
                    </div>
                    <div className="tag-row">
                      {dailyBriefData.recommended_actions.slice(0, 5).map((action) => (
                        <Pill tone="gold" key={action}>{action}</Pill>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Daily brief is loading from stored news and story clusters.</div>
                )}
              </Panel>

              <Panel eyebrow="Press Conference" title="Party Briefing" className="span-2">
                <form className="admin-form" onSubmit={preparePartyBriefing}>
                  <div className="form-grid">
                    <label>
                      Topic
                      <input
                        value={partyBriefingForm.topic}
                        onChange={(event) => setPartyBriefingForm({ ...partyBriefingForm, topic: event.target.value })}
                        placeholder="e.g. judiciary, EU path, energy prices"
                        required
                      />
                    </label>
                    <label>
                      Objective
                      <input
                        value={partyBriefingForm.objective}
                        onChange={(event) => setPartyBriefingForm({ ...partyBriefingForm, objective: event.target.value })}
                        placeholder="What should the press conference achieve?"
                      />
                    </label>
                  </div>
                  <label>
                    Requirements
                    <textarea
                      value={partyBriefingForm.requirements}
                      onChange={(event) => setPartyBriefingForm({ ...partyBriefingForm, requirements: event.target.value })}
                      placeholder="Facts, claims, opponents, dates, or legal angle to check"
                    />
                  </label>
                  <button className="primary-button" type="submit">Prepare Briefing</button>
                  {partyBriefingStatus ? <p className="muted">{partyBriefingStatus}</p> : null}
                </form>
                {partyBriefing ? (
                  <div className="briefing-result">
                    <BriefingReadinessPanel briefing={partyBriefing} />
                    <PartyBriefingStrategyPanel briefing={partyBriefing} />
                    <div className="drawer-section">
                      <p className="eyebrow">Generated Briefing</p>
                      <h3>{partyBriefing.coverage_summary}</h3>
                      <div className="brief-grid">
                        {partyBriefing.suggested_talking_points.slice(0, 3).map((point) => (
                          <article className="brief-item" key={point}>
                            <FileText size={20} />
                            <p>{point}</p>
                          </article>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : null}
              </Panel>

              <Panel eyebrow="Evidence" title="Top Cross-Source Stories" className="span-2">
                <div className="stack">
                  {storyClusterData.slice(0, 4).map((cluster) => (
                    <article className="trend-card" key={cluster.id}>
                      <div>
                        <div className="card-meta">
                          <Pill tone={cluster.status === "validated" ? "green" : "gold"}>{cluster.status.replaceAll("_", " ")}</Pill>
                          <Pill>{cluster.source_count} sources</Pill>
                          <Pill>{cluster.article_count} articles</Pill>
                        </div>
                        <h3>{cluster.title}</h3>
                        <p>{cluster.summary}</p>
                      </div>
                      <div className="trend-score">{cluster.source_count}</div>
                    </article>
                  ))}
                </div>
              </Panel>
            </div>
          </section>
        ) : null}

        {view === "admin" ? (
          <section className="view">
            {currentUser.role === "admin" ? (
            <div className="admin-grid">
              <Panel
                eyebrow="Pilot Launch"
                title="Readiness Checklist"
                className="span-2"
                action={<Pill tone={launchChecklistData?.overall === "ready" ? "green" : "gold"}>{launchChecklistData?.overall?.replaceAll("_", " ") || "checking"}</Pill>}
              >
                <div className="brief-grid">
                  {launchChecklistData?.checks.map((check) => (
                    <article className="brief-item" key={check.key}>
                      <Pill tone={check.status === "pass" ? "green" : check.status === "manual" ? "gold" : "coral"}>
                        {check.status}
                      </Pill>
                      <strong>{check.label}</strong>
                      <p>{check.detail}</p>
                    </article>
                  )) || <div className="empty-state">Loading launch checklist...</div>}
                </div>
              </Panel>

              <Panel
                eyebrow="Daily Ops"
                title="Fix Queue"
                className="span-2"
                action={<Pill tone={(opsFixQueueData?.summary.p0 ?? 0) ? "coral" : (opsFixQueueData?.summary.p1 ?? 0) ? "gold" : "green"}>
                  {opsFixQueueData?.summary.total ?? 0} items
                </Pill>}
              >
                {opsFixQueueData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="P0" value={opsFixQueueData.summary.p0} caption="blocking" icon={Bell} />
                      <Metric label="P1" value={opsFixQueueData.summary.p1} caption="important" icon={CircleDot} />
                      <Metric label="P2" value={opsFixQueueData.summary.p2} caption="cleanup" icon={ShieldCheck} />
                      <Metric label="Areas" value={Object.keys(opsFixQueueData.summary.by_area).length} caption="affected" icon={Gauge} />
                    </div>
                    <div className="source-list">
                      {opsFixQueueData.items.slice(0, 10).map((item, index) => (
                        <article className="source-card" key={`fix-${item.area}-${item.article_id || item.entity_id || item.source_id || item.source_stat_id || index}`}>
                          <div className="source-main">
                            <div>
                              <div className="card-meta">
                                <Pill tone={item.priority === "p0" ? "coral" : item.priority === "p1" ? "gold" : "default"}>
                                  {item.priority.toUpperCase()}
                                </Pill>
                                <Pill>{item.area.replaceAll("_", " ")}</Pill>
                              </div>
                              <strong>{item.title}</strong>
                              <p>{item.detail}</p>
                              <p className="muted">{item.suggested_action}</p>
                            </div>
                            {item.area === "source_health" && item.source_name ? (
                              <button className="text-button" type="button" onClick={() => openSourceDrilldown(item.source_name!)}>
                                Drilldown
                              </button>
                            ) : null}
                            {item.area === "entity_quality" && item.entity_id ? (
                              <button className="text-button" type="button" onClick={() => reviewEntity(item.entity_id!, "hidden")}>
                                Hide
                              </button>
                            ) : null}
                          </div>
                        </article>
                      ))}
                      {!opsFixQueueData.items.length ? <div className="empty-state">No operational fixes queued right now.</div> : null}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Fix queue is loading.</div>
                )}
              </Panel>

              <PostIngestionCleanupPanel
                opsFixQueue={opsFixQueueData}
                articleQuality={articleQualityData}
                entityQuality={entityQualityData}
                sourceHealth={sourceHealthData}
                onSourceDrilldown={openSourceDrilldown}
                onArticleReview={reviewArticleQuality}
                onEntityHide={(entityId) => reviewEntity(entityId, "hidden")}
                onBulkExclude={bulkExcludeQualityArticles}
              />

              <Panel
                eyebrow="Intelligence Quality"
                title="Attack Review Queue"
                className="span-2"
                action={<Pill tone={(attackReviewData?.summary.unreviewed ?? 0) ? "gold" : "green"}>
                  {attackReviewData?.summary.unreviewed ?? 0} unreviewed
                </Pill>}
              >
                {attackReviewData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Detected" value={attackReviewData.summary.total} caption="target relations" icon={Bell} />
                      <Metric label="Unreviewed" value={attackReviewData.summary.unreviewed} caption="needs decision" icon={CircleDot} />
                      <Metric label="Confirmed" value={attackReviewData.summary.confirmed} caption="human checked" icon={ShieldCheck} />
                      <Metric label="Rejected" value={attackReviewData.summary.rejected} caption="hidden from clients" icon={Trash2} />
                    </div>
                    <div className="attack-review-list">
                      {attackReviewData.candidates.slice(0, 12).map((item) => (
                        <article className="attack-review-card" key={`${item.watchlist_item_id}-${item.article_id}`}>
                          <div className="attack-review-main">
                            <div className="card-meta">
                              <Pill tone={item.review_status === "confirmed" ? "green" : item.review_status === "rejected" ? "coral" : "gold"}>
                                {item.review_status}
                              </Pill>
                              <Pill>{Math.round(item.confidence * 100)}% confidence</Pill>
                              <Pill>{item.client_name}</Pill>
                              <Pill>{item.source_name}</Pill>
                            </div>
                            <strong>{item.attacker || "Unknown attacker"} → {item.target || item.watchlist_label}</strong>
                            <p>{item.allegation || "No exact allegation was extracted."}</p>
                            <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
                          </div>
                          <div className="attack-review-actions">
                            <button className="text-button" type="button" onClick={() => reviewAttackDetection(item.watchlist_item_id, item.article_id, "confirmed")}>
                              Confirm
                            </button>
                            <button className="text-button danger-action" type="button" onClick={() => reviewAttackDetection(item.watchlist_item_id, item.article_id, "rejected")}>
                              Not an attack
                            </button>
                          </div>
                        </article>
                      ))}
                      {!attackReviewData.candidates.length ? <div className="empty-state">No target-specific attack detections need review.</div> : null}
                    </div>
                    {attackReviewStatus ? <p className="muted" role="status">{attackReviewStatus}</p> : null}
                  </div>
                ) : (
                  <div className="empty-state">Attack review candidates are loading.</div>
                )}
              </Panel>

              <Panel eyebrow="Backups" title="Database Backup / Restore">
                <div className="stack">
                  <div className="tag-row">
                    <button className="primary-button" type="button" onClick={createDatabaseBackup}>
                      Create Backup
                    </button>
                    {backupData?.latest ? <Pill tone="green">Latest {dateLabel(backupData.latest.created_at)}</Pill> : <Pill tone="gold">No backup</Pill>}
                  </div>
                  <p className="muted">{backupData?.restore_note || "Backup status is loading."}</p>
                  <div className="source-list">
                    {backupData?.backups.slice(0, 5).map((backup) => (
                      <article className="source-card" key={backup.filename}>
                        <div className="source-main">
                          <div>
                            <strong>{backup.filename}</strong>
                            <p>{Math.round(backup.size_bytes / 1024)} KB / {dateLabel(backup.created_at)}</p>
                          </div>
                          <button className="text-button" type="button" onClick={() => showRestorePlan(backup.filename)}>
                            Restore Steps
                          </button>
                        </div>
                      </article>
                    )) || <div className="empty-state">No backups created yet.</div>}
                  </div>
                  {backupStatusText ? <p className="muted">{backupStatusText}</p> : null}
                </div>
              </Panel>

              <Panel
                eyebrow="Source Config"
                title="Config Validation"
                className="span-2"
                action={<Pill tone={(sourceConfigValidationData?.summary.critical_count ?? 0) ? "coral" : (sourceConfigValidationData?.summary.warning_count ?? 0) ? "gold" : "green"}>
                  {sourceConfigValidationData?.summary.issue_count ?? 0} issues
                </Pill>}
              >
                {sourceConfigValidationData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Healthy" value={sourceConfigValidationData.summary.healthy_count} caption="ready configs" icon={ShieldCheck} />
                      <Metric label="Warnings" value={sourceConfigValidationData.summary.warning_count} caption="polish needed" icon={Bell} />
                      <Metric label="Critical" value={sourceConfigValidationData.summary.critical_count} caption="must fix" icon={CircleDot} />
                      <Metric label="Disabled" value={sourceConfigValidationData.summary.disabled_count} caption="not active" icon={Gauge} />
                    </div>
                    <div className="tag-row">
                      {sourceConfigValidationData.recommendations.map((item) => (
                        <Pill tone={(sourceConfigValidationData.summary.critical_count || sourceConfigValidationData.summary.warning_count) ? "gold" : "green"} key={item}>
                          {item}
                        </Pill>
                      ))}
                      <button className="text-button" type="button" onClick={syncSourcesFromConfig}>
                        Sync YAML to DB
                      </button>
                    </div>
                    <div className="source-list compact-source">
                      {sourceConfigValidationData.sources
                        .filter((source) => source.status !== "healthy")
                        .slice(0, 8)
                        .map((source) => {
                          const firstIssue = source.issues[0];
                          return (
                            <article className="source-card" key={`config-validation-${source.source_name}`}>
                              <div className="source-main">
                                <div>
                                  <div className="card-meta">
                                    <Pill tone={source.status === "critical" ? "coral" : source.status === "warning" ? "gold" : "muted"}>
                                      {source.status}
                                    </Pill>
                                    <Pill>{source.rss_feed_count} RSS</Pill>
                                    <Pill>{source.listing_url_count} listings</Pill>
                                    <Pill>{source.selector_count} selectors</Pill>
                                  </div>
                                  <strong>{source.source_name || "Unnamed source"}</strong>
                                  <p>{firstIssue ? `${firstIssue.field}: ${firstIssue.message}` : "Source is disabled."}</p>
                                  {firstIssue ? <p>{firstIssue.suggested_fix}</p> : null}
                                </div>
                                {source.db_source_id ? (
                                  <button className="text-button" type="button" onClick={() => runSourcePreflight(source.db_source_id!)}>
                                    Preflight
                                  </button>
                                ) : null}
                              </div>
                            </article>
                          );
                        })}
                      {sourceConfigValidationData.sources.every((source) => source.status === "healthy") ? (
                        <div className="empty-state">All active source configs look ready for preflight.</div>
                      ) : null}
                    </div>
                    {sourceConfigValidationData.db_only_sources.length ? (
                      <p className="muted">DB-only sources: {sourceConfigValidationData.db_only_sources.join(", ")}</p>
                    ) : null}
                    <p className="muted">{sourceConfigValidationData.config_path}</p>
                  </div>
                ) : (
                  <div className="empty-state">Source config validation is loading.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Source Config"
                title="Media Source Editor"
                className="span-2"
                action={<Pill tone="gold">{sourceData.length} sources</Pill>}
              >
                <div className="source-config-grid">
                  {sourceData.map((source) => (
                    <article className="source-card source-config-card" key={source.source_id}>
                      <div className="source-main">
                        <div>
                          <div className="card-meta">
                            <Pill tone={source.is_active ? "green" : "coral"}>{source.is_active ? "active" : "disabled"}</Pill>
                            <Pill>{source.source_type}</Pill>
                            <Pill>{source.political_leaning}</Pill>
                            <Pill tone="gold">{Math.round(source.reliability_score * 100)}%</Pill>
                          </div>
                          <strong>{source.name}</strong>
                          <p>{source.ownership || source.url}</p>
                        </div>
                        <button className="text-button" type="button" onClick={() => openSourceDrilldown(source.name)}>
                          Drilldown
                        </button>
                        <button className="text-button" type="button" onClick={() => runSourcePreflight(source.source_id)}>
                          Preflight
                        </button>
                      </div>
                      <div className="source-config-controls">
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={source.is_active}
                            onChange={(event) => updateSourceConfig(source.source_id, { is_active: event.target.checked })}
                          />
                          Active
                        </label>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={Boolean(source.scraper_enabled)}
                            onChange={(event) => updateSourceConfig(source.source_id, { scraper_enabled: event.target.checked })}
                          />
                          Scraper
                        </label>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={Boolean(source.rss_enabled)}
                            onChange={(event) => updateSourceConfig(source.source_id, { rss_enabled: event.target.checked })}
                          />
                          RSS
                        </label>
                        <label>
                          Reliability
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            defaultValue={source.reliability_score}
                            onBlur={(event) => updateSourceConfig(source.source_id, { reliability_score: Number(event.target.value) })}
                          />
                        </label>
                        <label>
                          Type
                          <select
                            defaultValue={source.source_type}
                            onChange={(event) => updateSourceConfig(source.source_id, { source_type: event.target.value })}
                          >
                            <option value="news">News</option>
                            <option value="wire">Wire</option>
                            <option value="government">Government</option>
                            <option value="social_media">Social media</option>
                            <option value="blog">Blog</option>
                            <option value="investigative">Investigative</option>
                          </select>
                        </label>
                        <label>
                          Leaning
                          <select
                            defaultValue={source.political_leaning}
                            onChange={(event) => updateSourceConfig(source.source_id, { political_leaning: event.target.value })}
                          >
                            <option value="unknown">Unknown</option>
                            <option value="left">Left</option>
                            <option value="center">Center</option>
                            <option value="right">Right</option>
                            <option value="government">Government</option>
                            <option value="opposition">Opposition</option>
                          </select>
                        </label>
                        <label>
                          Min words
                          <input
                            type="number"
                            min="0"
                            max="500"
                            step="5"
                            defaultValue={source.min_word_count ?? 40}
                            onBlur={(event) => updateSourceConfig(source.source_id, { min_word_count: Number(event.target.value) })}
                          />
                        </label>
                        <label className="wide-control">
                          Ownership / notes
                          <input
                            defaultValue={source.ownership || ""}
                            onBlur={(event) => updateSourceConfig(source.source_id, { ownership: event.target.value })}
                            placeholder="owner, editorial note, relationship"
                          />
                        </label>
                        <label className="wide-control">
                          Scraper note
                          <input
                            defaultValue={source.yaml_note || ""}
                            onBlur={(event) => updateSourceConfig(source.source_id, { note: event.target.value })}
                            placeholder="why scraper/RSS is enabled, blocked, or needs review"
                          />
                        </label>
                      </div>
                    </article>
                  ))}
                </div>
                {sourceConfigStatus ? <p className="muted">{sourceConfigStatus}</p> : null}
                {scraperPreflightStatus ? <p className="muted">{scraperPreflightStatus}</p> : null}
              </Panel>

              <Panel eyebrow="Access" title="Create User">
                <form className="admin-form" onSubmit={saveUser}>
                  <div className="form-grid">
                    <label>
                      Name
                      <input
                        value={userForm.name}
                        onChange={(event) => setUserForm({ ...userForm, name: event.target.value })}
                        placeholder="Full name"
                        required
                      />
                    </label>
                    <label>
                      Email
                      <input
                        value={userForm.email}
                        onChange={(event) => setUserForm({ ...userForm, email: event.target.value })}
                        placeholder="user@example.com"
                        required
                      />
                    </label>
                  </div>
                  <div className="form-grid">
                    <label>
                      Role
                      <select
                        value={userForm.role}
                        onChange={(event) => setUserForm({ ...userForm, role: event.target.value })}
                      >
                        <option value="client">Client</option>
                        <option value="analyst">Analyst</option>
                        <option value="admin">Admin</option>
                      </select>
                    </label>
                    <label>
                      Client
                      <select
                        value={userForm.client_id || ""}
                        onChange={(event) => setUserForm({ ...userForm, client_id: event.target.value ? Number(event.target.value) : null })}
                        disabled={userForm.role !== "client"}
                      >
                        <option value="">No client</option>
                        {clientData.map((client) => (
                          <option value={client.id} key={client.id}>{client.name}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label>
                    Temporary password
                    <input
                      type="password"
                      value={userForm.password}
                      onChange={(event) => setUserForm({ ...userForm, password: event.target.value })}
                      placeholder="Set a temporary password"
                      required
                    />
                  </label>
                  <button className="primary-button" type="submit">Create User</button>
                  {userSaveStatus ? <p className="muted">{userSaveStatus}</p> : null}
                </form>
              </Panel>

              <Panel eyebrow="Access" title="Users" action={<Pill tone="gold">{userData.length} users</Pill>}>
                <div className="source-list">
                  {userData.length ? (
                    userData.map((user) => (
                      <article className="source-card" key={user.id}>
                        <div className="source-main">
                          <div>
                            <div className="card-meta">
                              <Pill tone={user.role === "admin" ? "coral" : user.role === "analyst" ? "gold" : "green"}>{user.role}</Pill>
                              <Pill>{user.is_active ? "active" : "inactive"}</Pill>
                              {user.client_id ? <Pill>client #{user.client_id}</Pill> : null}
                            </div>
                            <strong>{user.name}</strong>
                            <p>{user.email}</p>
                          </div>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">No users loaded.</div>
                  )}
                </div>
              </Panel>

              <Panel
                eyebrow="Legal Library"
                title="Legal Readiness"
                action={<Pill tone={legalQualityData?.status === "ready" ? "green" : legalQualityData?.status === "needs_review" ? "gold" : "coral"}>
                  {legalQualityData?.status?.replaceAll("_", " ") || "loading"}
                </Pill>}
              >
                {legalQualityData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="References" value={legalQualityData.total} caption="stored" icon={BookOpenText} />
                      <Metric label="Official+" value={legalQualityData.official_or_verified} caption="official or verified" icon={ShieldCheck} />
                      <Metric label="Lawyer" value={legalQualityData.lawyer_verified_count} caption="verified" icon={FileText} />
                      <Metric label="Review" value={legalQualityData.needs_review_count + legalQualityData.outdated_count} caption="needs attention" icon={Bell} accent />
                    </div>
                    <div className="tag-row">
                      {Object.entries(legalQualityData.status_counts).map(([status, count]) => (
                        <Pill key={status} tone={status === "official" || status === "lawyer_verified" ? "green" : count ? "gold" : undefined}>
                          {status.replaceAll("_", " ")}: {count}
                        </Pill>
                      ))}
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Coverage Areas</p>
                      <div className="tag-row">
                        {legalQualityData.areas.length ? legalQualityData.areas.map((item) => (
                          <Pill key={item.area}>{item.area}: {item.count}</Pill>
                        )) : <Pill tone="gold">No legal areas yet</Pill>}
                      </div>
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Required Legal Coverage</p>
                      <div className="tag-row">
                        <Pill tone="green">covered: {legalQualityData.coverage_summary.covered}</Pill>
                        <Pill tone="gold">research: {legalQualityData.coverage_summary.research_lead}</Pill>
                        <Pill tone={legalQualityData.coverage_summary.missing ? "coral" : "green"}>
                          missing: {legalQualityData.coverage_summary.missing}
                        </Pill>
                      </div>
                      <div className="draft-list">
                        {legalQualityData.required_coverage.map((item) => (
                          <article className="draft-card" key={item.key}>
                            <div className="card-meta">
                              <Pill tone={item.status === "covered" ? "green" : item.status === "research_lead" ? "gold" : "coral"}>
                                {item.status.replaceAll("_", " ")}
                              </Pill>
                              <Pill>{item.official_or_verified} official+</Pill>
                              <Pill>{item.total_references} refs</Pill>
                            </div>
                            <strong>{item.label}</strong>
                            <p>
                              {item.top_references.length
                                ? item.top_references.map((ref) => ref.title).join(" | ")
                                : "Add an official source or reviewed research lead."}
                            </p>
                          </article>
                        ))}
                      </div>
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Review Notes</p>
                      {legalQualityData.recommendations.map((item) => (
                        <p className="muted" key={item}>{item}</p>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Legal readiness is loading.</div>
                )}
              </Panel>

              <Panel eyebrow="Legal Library" title="Add Macedonian Legal Reference">
                <form className="admin-form" onSubmit={saveLegalDocument}>
                  <div className="form-grid">
                    <label>
                      Law / document title
                      <input
                        value={legalForm.title}
                        onChange={(event) => setLegalForm({ ...legalForm, title: event.target.value })}
                        placeholder="Law on Civil Liability for Insult and Defamation"
                        required
                      />
                    </label>
                    <label>
                      Legal area
                      <input
                        value={legalForm.legal_area}
                        onChange={(event) => setLegalForm({ ...legalForm, legal_area: event.target.value })}
                        placeholder="defamation, elections, constitution"
                        required
                      />
                    </label>
                  </div>
                  <div className="form-grid">
                    <label>
                      Source URL
                      <input
                        value={legalForm.source_url}
                        onChange={(event) => setLegalForm({ ...legalForm, source_url: event.target.value })}
                        placeholder="PDF or source page"
                      />
                    </label>
                    <label>
                      Source status
                      <select
                        value={legalForm.source_status}
                        onChange={(event) => setLegalForm({ ...legalForm, source_status: event.target.value })}
                      >
                        <option value="needs_review">Needs review</option>
                        <option value="official">Official</option>
                        <option value="unofficial_copy">Unofficial copy</option>
                        <option value="outdated_possible">Outdated possible</option>
                      </select>
                    </label>
                  </div>
                  <label>
                    Summary / guidance
                    <textarea
                      value={legalForm.summary}
                      onChange={(event) => setLegalForm({ ...legalForm, summary: event.target.value })}
                      placeholder="What this law is useful for and how cautiously it should be used"
                    />
                  </label>
                  <label>
                    Reference text
                    <textarea
                      value={legalForm.reference_text}
                      onChange={(event) => setLegalForm({ ...legalForm, reference_text: event.target.value })}
                      placeholder="Paste relevant article text or extracted PDF section"
                    />
                  </label>
                  <div className="form-grid">
                    <label>
                      Article refs
                      <input
                        value={legalForm.article_refs}
                        onChange={(event) => setLegalForm({ ...legalForm, article_refs: event.target.value })}
                        placeholder="Article 16, Article 25..."
                      />
                    </label>
                    <label>
                      Tags
                      <input
                        value={legalTagsText}
                        onChange={(event) => setLegalTagsText(event.target.value)}
                        placeholder="speech, defamation, election"
                      />
                    </label>
                  </div>
                  <div className="form-grid">
                    <label>
                      Source name
                      <input
                        value={legalForm.source_name}
                        onChange={(event) => setLegalForm({ ...legalForm, source_name: event.target.value })}
                        placeholder="Official Gazette, ministry, court, PDF mirror"
                      />
                    </label>
                    <label>
                      Confidence
                      <input
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        value={legalForm.confidence_score}
                        onChange={(event) => setLegalForm({ ...legalForm, confidence_score: Number(event.target.value) })}
                      />
                    </label>
                  </div>
                  <button className="primary-button" type="submit">Save Legal Reference</button>
                  {legalSaveStatus ? <p className="muted">{legalSaveStatus}</p> : null}
                </form>
              </Panel>

              {selectedLegalReview ? (
                <Panel
                  eyebrow="Audited Legal Review"
                  title={selectedLegalReview.title}
                  action={<button className="text-button" type="button" onClick={() => setSelectedLegalReviewId(undefined)}>Close</button>}
                >
                  <form className="admin-form" onSubmit={assignLegalReview}>
                    <div className="form-grid">
                      <label>
                        Counsel name
                        <input
                          value={legalAssignmentForm.reviewer_name}
                          onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, reviewer_name: event.target.value })}
                          required
                        />
                      </label>
                      <label>
                        Counsel email
                        <input
                          type="email"
                          value={legalAssignmentForm.reviewer_email || ""}
                          onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, reviewer_email: event.target.value })}
                        />
                      </label>
                    </div>
                    <div className="form-grid">
                      <label>
                        Organization
                        <input
                          value={legalAssignmentForm.reviewer_organization || ""}
                          onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, reviewer_organization: event.target.value })}
                        />
                      </label>
                      <label>
                        Due date
                        <input
                          type="date"
                          value={legalAssignmentForm.due_at || ""}
                          onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, due_at: event.target.value })}
                        />
                      </label>
                    </div>
                    <div className="form-grid">
                      <label>
                        Practice jurisdiction
                        <input
                          value={legalAssignmentForm.reviewer_jurisdiction || ""}
                          onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, reviewer_jurisdiction: event.target.value })}
                          placeholder="North Macedonia"
                        />
                      </label>
                      <label>
                        Qualification reference
                        <input
                          value={legalAssignmentForm.qualification_reference || ""}
                          onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, qualification_reference: event.target.value })}
                          placeholder="Bar register or internal verification reference"
                        />
                      </label>
                    </div>
                    <label>
                      Review scope
                      <textarea
                        value={legalAssignmentForm.scope}
                        onChange={(event) => setLegalAssignmentForm({ ...legalAssignmentForm, scope: event.target.value })}
                        minLength={10}
                        required
                      />
                    </label>
                    <button className="secondary-button" type="submit">Assign Counsel Review</button>
                    {legalAssignmentStatus ? <p className="muted">{legalAssignmentStatus}</p> : null}
                  </form>
                  <div className="section-divider" />
                  <form className="admin-form" onSubmit={submitLegalReview}>
                    <p className="muted">
                      Lawyer verification requires a matching counsel assignment with a recorded jurisdiction and qualification reference.
                    </p>
                    <div className="form-grid">
                      <label>
                        Decision
                        <select
                          value={legalReviewForm.decision}
                          onChange={(event) => setLegalReviewForm({ ...legalReviewForm, decision: event.target.value })}
                        >
                          <option value="needs_review">Keep in review</option>
                          <option value="lawyer_verified">Lawyer verified</option>
                          <option value="official_source_confirmed">Official source confirmed</option>
                          <option value="outdated_possible">Possibly outdated</option>
                          <option value="unofficial_copy">Unofficial copy</option>
                        </select>
                      </label>
                      <label>
                        Reviewer name
                        <input
                          value={legalReviewForm.reviewer_name}
                          onChange={(event) => setLegalReviewForm({ ...legalReviewForm, reviewer_name: event.target.value })}
                          placeholder="Qualified reviewer"
                          required
                        />
                      </label>
                    </div>
                    <label>
                      Reviewer organization
                      <input
                        value={legalReviewForm.reviewer_organization || ""}
                        onChange={(event) => setLegalReviewForm({ ...legalReviewForm, reviewer_organization: event.target.value })}
                        placeholder="Law office, legal team, institution"
                      />
                    </label>
                    <label>
                      Review notes
                      <textarea
                        value={legalReviewForm.notes}
                        onChange={(event) => setLegalReviewForm({ ...legalReviewForm, notes: event.target.value })}
                        placeholder="What text/version was checked, amendment date, scope, and limitations"
                        minLength={10}
                        required
                      />
                    </label>
                    <button className="primary-button" type="submit">Record Review Decision</button>
                    {legalReviewStatus ? <p className="muted">{legalReviewStatus}</p> : null}
                  </form>
                </Panel>
              ) : null}

              <Panel eyebrow="Legal Library" title="Stored References" action={<Pill tone="gold">{legalDocumentData.length} refs</Pill>}>
                <div className="filter-row">
                  <input
                    value={legalSearch}
                    onChange={(event) => setLegalSearch(event.target.value)}
                    placeholder="Search laws, areas, article refs"
                  />
                </div>
                <div className="source-list">
                  {legalDocumentData.length ? (
                    legalDocumentData.map((document) => (
                      <article className="source-card" key={document.id}>
                        <div className="source-main">
                          <div>
                            <div className="card-meta">
                              <Pill tone={document.source_status === "lawyer_verified" || document.source_status === "official" ? "green" : "gold"}>
                                {document.source_status.replaceAll("_", " ")}
                              </Pill>
                              <Pill>{document.legal_area}</Pill>
                              <Pill>{Math.round(document.confidence_score * 100)}%</Pill>
                            </div>
                            {document.source_url ? (
                              <a href={document.source_url} target="_blank" rel="noreferrer">{document.title}</a>
                            ) : (
                              <strong>{document.title}</strong>
                            )}
                            <p>{document.summary || document.article_refs || "No summary saved."}</p>
                            <button
                              className="text-button"
                              type="button"
                              onClick={() => {
                                setSelectedLegalReviewId(document.id);
                                setLegalReviewStatus("");
                              }}
                            >
                              Review decision
                            </button>
                          </div>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">No legal references saved yet.</div>
                  )}
                </div>
              </Panel>

              <Panel eyebrow="Search Index" title="Search Index Notes">
                <div className="stack">
                  <p>
                    Search now matches Macedonian Cyrillic and Latin input, so a user can type either "makedonija" or "Македонија" and reach the same stored coverage.
                  </p>
                  <div className="brief-grid">
                    <article className="brief-item">
                      <Search size={20} />
                      <strong>Bilingual matching</strong>
                      <p>Articles, entities, and keyword alerts use normalized search text.</p>
                    </article>
                    <article className="brief-item">
                      <Newspaper size={20} />
                      <strong>{articles.data?.total ?? "-"} articles visible</strong>
                      <p>Current article search result count with active filters.</p>
                    </article>
                    <article className="brief-item">
                      <UsersRound size={20} />
                      <strong>{entityData.length} entities visible</strong>
                      <p>Current entity directory result count with active search.</p>
                    </article>
                  </div>
                  <div className="tag-row">
                    {["makedonija", "Македонија", "skopje", "Скопје", "vmro", "dui"].map((example) => (
                      <button className="text-button" type="button" key={example} onClick={() => setSearch(example)}>
                        Test {example}
                      </button>
                    ))}
                  </div>
                  <p className="muted">
                    Existing local data was backfilled with normalized search text; future scraped articles are indexed during ingestion.
                  </p>
                </div>
              </Panel>

              <Panel
                eyebrow="Search Index"
                title="Cyrillic / Latin Search Readiness"
                action={<Pill tone={searchQualityData?.status === "ready" ? "green" : searchQualityData ? "gold" : undefined}>
                  {searchQualityData?.status?.replaceAll("_", " ") || "loading"}
                </Pill>}
              >
                {searchQualityData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Articles" value={searchQualityData.article_count} caption="indexed scope" icon={Newspaper} />
                      <Metric label="Entities" value={searchQualityData.entity_count} caption="visible scope" icon={UsersRound} />
                      <Metric label="Article Gaps" value={searchQualityData.missing_article_search_text} caption="missing search text" icon={Search} accent />
                      <Metric label="Entity Gaps" value={searchQualityData.missing_entity_search_text} caption="missing search text" icon={Brain} accent />
                    </div>
                    <div className="draft-list">
                      {searchQualityData.query_checks.map((check) => (
                        <article className="draft-card" key={check.label}>
                          <div className="card-meta">
                            <Pill tone={check.status === "pass" ? "green" : "gold"}>{check.status}</Pill>
                            <Pill>{check.article_total} articles</Pill>
                            <Pill>{check.entity_total} entities</Pill>
                          </div>
                          <strong>{check.query}</strong>
                          <p>{check.variants.slice(0, 3).join(" / ")}</p>
                          <button className="text-button" type="button" onClick={() => setSearch(check.query)}>
                            Test in dashboard
                          </button>
                        </article>
                      ))}
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Operator Notes</p>
                      {searchQualityData.recommendations.map((item) => (
                        <p className="muted" key={item}>{item}</p>
                      ))}
                      <code>{searchQualityData.backfill_command}</code>
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Search quality is loading.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Data Quality"
                title="Entity Review"
                action={
                  <div className="tag-row">
                    <Pill tone={entityReviewData.length ? "gold" : "green"}>{entityReviewData.length} queued</Pill>
                    <button className="text-button" type="button" onClick={bulkHideNoiseEntities}>
                      Auto-hide Noise
                    </button>
                    <button className="text-button" type="button" onClick={mergeLexiconAliases}>
                      Merge Lexicon Aliases
                    </button>
                  </div>
                }
              >
                {entityQualityData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Checked" value={entityQualityData.checked} caption="unapproved entities" icon={UsersRound} />
                      <Metric label="Suspicious" value={entityQualityData.suspicious_count} caption="validator flags" icon={Bell} />
                    </div>
                    <div className="tag-row">
                      {Object.entries(entityQualityData.reason_counts).slice(0, 8).map(([reason, count]) => (
                        <Pill tone="gold" key={reason}>{reason.replaceAll("_", " ")}: {count}</Pill>
                      ))}
                    </div>
                    {entityQualityData.examples.length ? (
                      <div className="draft-list">
                        {entityQualityData.examples.slice(0, 6).map((entity) => (
                          <article className="draft-card" key={`quality-${entity.id}`}>
                            <div className="card-meta">
                              <Pill>{entity.entity_type}</Pill>
                              <Pill tone="gold">{entity.total_mentions} mentions</Pill>
                              {entity.reasons.slice(0, 3).map((reason) => (
                                <Pill tone="coral" key={`${entity.id}-${reason}`}>{reason.replaceAll("_", " ")}</Pill>
                              ))}
                            </div>
                            <strong>{entity.name}</strong>
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="source-list">
                  {entityReviewData.length ? (
                    entityReviewData.map((entity) => (
                      <article className="source-card" key={entity.id}>
                        <div className="source-main">
                          <div>
                            <div className="card-meta">
                              <Pill tone={entity.status === "hidden" ? "coral" : entity.status === "approved" ? "green" : "gold"}>
                                {entity.status.replaceAll("_", " ")}
                              </Pill>
                              <Pill>{entity.entity_type}</Pill>
                              <Pill tone="gold">{entity.total_mentions} mentions</Pill>
                              <Pill>{entity.trust_tier?.replaceAll("_", " ") || "legacy"}</Pill>
                              {entity.confidence != null ? <Pill>{Math.round(entity.confidence * 100)}% candidate score</Pill> : null}
                            </div>
                            <strong>{entity.name}</strong>
                            <p>{entity.canonical_name}</p>
                            {entity.provenance?.length ? <p className="muted">Found by {entity.provenance.join(", ")}.</p> : null}
                            {entity.decision_reasons?.length ? (
                              <p className="muted">{entity.decision_reasons.map((reason) => reason.replaceAll("_", " ")).join(" · ")}</p>
                            ) : null}
                            {entity.review_notes ? <p className="muted">{entity.review_notes}</p> : null}
                            <div className="filter-row">
                              <select
                                value={mergeTargets[entity.id] || ""}
                                onChange={(event) => setMergeTargets({ ...mergeTargets, [entity.id]: event.target.value })}
                              >
                                <option value="">Merge target</option>
                                {entityData
                                  .filter((target) => target.id !== entity.id)
                                  .slice(0, 120)
                                  .map((target) => (
                                    <option value={target.id} key={target.id}>
                                      {target.name} · {target.entity_type} · {target.total_mentions}
                                    </option>
                                  ))}
                              </select>
                              <button className="text-button" type="button" onClick={() => mergeEntity(entity.id)}>
                                Merge
                              </button>
                            </div>
                          </div>
                          <div className="stack">
                            <button className="text-button" type="button" onClick={() => reviewEntity(entity.id, "approved")}>
                              Approve
                            </button>
                            <button className="text-button" type="button" onClick={() => reviewEntity(entity.id, "hidden")}>
                              Hide
                            </button>
                            <button className="text-button" type="button" onClick={() => reviewEntity(entity.id, "needs_review")}>
                              Needs Review
                            </button>
                            <select
                              value={entity.entity_type}
                              onChange={(event) => reviewEntity(entity.id, "approved", event.target.value)}
                            >
                              <option value="person">Person</option>
                              <option value="organization">Organization</option>
                              <option value="location">Location</option>
                            </select>
                          </div>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">No suspicious entities in the current review queue.</div>
                  )}
                </div>
                {entityReviewStatus ? <p className="muted">{entityReviewStatus}</p> : null}
              </Panel>

              <Panel
                eyebrow="Entity Accuracy"
                title="Lexicon Coverage"
                action={<Pill tone={(entityLexiconData?.missing_count ?? 0) || (entityLexiconData?.uncovered_count ?? 0) ? "gold" : "green"}>
                  {entityLexiconData?.matched_count ?? 0} matched
                </Pill>}
              >
                {entityLexiconData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Known" value={entityLexiconData.known_count} caption="curated YAML" icon={UsersRound} />
                      <Metric label="Matched" value={entityLexiconData.matched_count} caption="found in DB" icon={ShieldCheck} />
                      <Metric label="Missing" value={entityLexiconData.missing_count} caption="curated not found" icon={Bell} />
                      <Metric label="Uncovered" value={entityLexiconData.uncovered_count} caption="DB not curated" icon={CircleDot} />
                    </div>
                    <div className="tag-row">
                      {entityLexiconData.recommendations.map((item) => (
                        <Pill tone="gold" key={item}>{item}</Pill>
                      ))}
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">High-Mention Entities Not In Lexicon</p>
                      <div className="source-list">
                        {entityLexiconData.uncovered_entities.length ? entityLexiconData.uncovered_entities.slice(0, 8).map((entity) => (
                          <article className="source-card" key={`uncovered-${entity.entity_id}`}>
                            <div className="source-main">
                              <div>
                                <div className="card-meta">
                                  <Pill>{entity.entity_type}</Pill>
                                  <Pill tone="gold">{entity.total_mentions} mentions</Pill>
                                  <Pill>{entity.status}</Pill>
                                </div>
                                <strong>{entity.name}</strong>
                                <p>{entity.suggested_action}</p>
                              </div>
                              <div className="button-row">
                                <button className="text-button" type="button" onClick={() => addEntityToLexicon(entity.entity_id)}>
                                  Add to Lexicon
                                </button>
                                <button className="text-button" type="button" onClick={() => reviewEntity(entity.entity_id, "approved")}>
                                  Approve
                                </button>
                              </div>
                            </div>
                          </article>
                        )) : <div className="empty-state">No high-mention uncovered entities in the current sample.</div>}
                      </div>
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Curated Entities Missing From DB</p>
                      <div className="tag-row">
                        {entityLexiconData.missing_examples.slice(0, 16).map((entity) => (
                          <Pill key={`missing-${entity.name}`}>{entity.name}</Pill>
                        ))}
                      </div>
                    </div>
                    <p className="muted">{entityLexiconData.lexicon_path}</p>
                    {entityLexiconStatus ? <p className="muted">{entityLexiconStatus}</p> : null}
                  </div>
                ) : (
                  <div className="empty-state">Lexicon coverage is loading.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Scrapers"
                title="Ingestion Health"
                action={<Pill tone={sourceHealthData?.run?.status === "completed" ? "green" : "gold"}>
                  {sourceHealthData?.run?.status || "no run"}
                </Pill>}
              >
                {sourceHealthData?.run ? (
                  <>
                    <div className="metric-grid compact-metrics">
                      <Metric label="Sources" value={sourceHealthData.run.total_sources} caption="configured" icon={Globe2} />
                      <Metric label="Raw" value={sourceHealthData.run.total_raw} caption="last run" icon={Newspaper} />
                      <Metric label="New" value={sourceHealthData.run.total_new} caption="saved" icon={Activity} />
                      <Metric label="Dupes" value={sourceHealthData.run.total_duplicate + sourceHealthData.run.total_duplicate_fuzzy} caption="skipped" icon={CircleDot} />
                    </div>
                    {sourceHealthData.summary ? (
                      <div className="ops-summary">
                        <div className="tag-row">
                          <Pill tone="green">{sourceHealthData.summary.healthy_count} healthy</Pill>
                          <Pill tone="gold">{sourceHealthData.summary.caught_up_count} caught up</Pill>
                          <Pill>{sourceHealthData.summary.rss_only_count} RSS only</Pill>
                          <Pill tone={sourceHealthData.summary.attention_count ? "coral" : "green"}>
                            {sourceHealthData.summary.attention_count} need attention
                          </Pill>
                          {sourceHealthData.summary.latest_run_age_minutes !== null && sourceHealthData.summary.latest_run_age_minutes !== undefined ? (
                            <Pill>{sourceHealthData.summary.latest_run_age_minutes} min old</Pill>
                          ) : null}
                        </div>
                        <div className="stack">
                          {sourceHealthData.summary.recommendations.map((item) => (
                            <p className="muted" key={item}>{item}</p>
                          ))}
                        </div>
                        <div className="tag-row">
                          <button className="primary-button" type="button" onClick={runIngestionNow}>
                            Run Ingestion Now
                          </button>
                          <button className="text-button" type="button" onClick={processQueueNow}>
                            Process Saved Queue
                          </button>
                        </div>
                        {opsStatus ? <p className="muted">{opsStatus}</p> : null}
                      </div>
                    ) : null}
                    <div className="source-list">
                      {sourceHealthData.sources.map((source) => (
                        <article className="source-card" key={source.id}>
                          <div className="source-main">
                            <div>
                              <div className="card-meta">
                                <Pill tone={source.status === "healthy" ? "green" : source.status === "degraded" || source.status === "rss_only" ? "gold" : "coral"}>
                                  {source.status.replaceAll("_", " ")}
                                </Pill>
                                <Pill>{source.source_type}</Pill>
                                {source.scraper_enabled ? <Pill tone="green">scraper</Pill> : null}
                                {source.rss_enabled ? <Pill>rss</Pill> : null}
                                {source.stopped_early ? <Pill tone="gold">caught up</Pill> : null}
                              </div>
                              {source.source_url ? (
                                <a href={source.source_url} target="_blank" rel="noreferrer">{source.source_name}</a>
                              ) : (
                                <strong>{source.source_name}</strong>
                              )}
                              <p>
                                Links {source.discovered_urls} / checked {source.checked_count} of {source.raw_count} / scraped {source.scraped_count} / RSS {source.rss_count} / new {source.new_count} / dupes {source.duplicate_count + source.duplicate_fuzzy_count}
                                {source.stopped_early ? ` / stopped after ${source.duplicate_streak} consecutive dupes` : ""}
                              </p>
                              {source.error_sample ? <p className="limit-warning">{source.error_sample}</p> : null}
                            </div>
                            <strong>{source.raw_count}</strong>
                          </div>
                          <div className="tag-row">
                            <button className="text-button" type="button" onClick={() => openSourceDrilldown(source.source_name)}>
                              View Failure Detail
                            </button>
                            {sourceData.find((item) => item.name === source.source_name) ? (
                              <button
                                className="text-button"
                                type="button"
                                onClick={() => {
                                  const configured = sourceData.find((item) => item.name === source.source_name);
                                  if (configured) updateSourceConfig(configured.source_id, { is_active: !configured.is_active });
                                }}
                              >
                                {sourceData.find((item) => item.name === source.source_name)?.is_active ? "Disable Source" : "Enable Source"}
                              </button>
                            ) : null}
                            {sourceData.find((item) => item.name === source.source_name)?.source_id ? (
                              <button
                                className="text-button"
                                type="button"
                                onClick={() => {
                                  const configured = sourceData.find((item) => item.name === source.source_name);
                                  if (configured) runSourcePreflight(configured.source_id);
                                }}
                              >
                                Run Preflight
                              </button>
                            ) : null}
                          </div>
                        </article>
                      ))}
                    </div>
                    {ingestionRunData.length ? (
                      <div className="tag-row">
                        {ingestionRunData.map((run) => (
                          <Pill key={run.id} tone={run.status === "completed" ? "green" : "gold"}>
                            #{run.id} {dateLabel(run.finished_at || run.started_at)} / {run.total_new} new
                          </Pill>
                        ))}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className="empty-state">No ingestion run recorded yet. Run scripts/ingest.py to populate source health.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Live Ops"
                title="Continuous Ingestion"
                action={
                  <Pill tone={liveOpsData?.overall === "healthy" ? "green" : liveOpsData?.overall === "watch" ? "gold" : "coral"}>
                    {liveOpsData?.overall?.replaceAll("_", " ") || "loading"}
                  </Pill>
                }
              >
                {liveOpsData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Cadence" value={`${liveOpsData.target_interval_minutes}m`} caption="target interval" icon={Activity} />
                      <Metric label="Freshness" value={liveOpsData.scheduler.stale_minutes ?? "-"} caption="minutes since run" icon={CircleDot} />
                      <Metric label="Dup Stop" value={liveOpsData.ingestion.caught_up_sources} caption={`threshold ${liveOpsData.duplicate_stop_threshold}`} icon={ShieldCheck} />
                      <Metric label="Attention" value={liveOpsData.ingestion.attention_sources} caption="sources" icon={Bell} accent />
                    </div>
                    <div className="tag-row">
                      <Pill tone={liveOpsData.scheduler.process_running ? "green" : "gold"}>
                        {liveOpsData.scheduler.process_running ? "scheduler running" : "process stopped"}
                      </Pill>
                      <Pill tone={liveOpsData.scheduler.heartbeat_healthy ? "green" : "gold"}>
                        heartbeat {liveOpsData.scheduler.heartbeat_age_minutes ?? "none"} min
                      </Pill>
                      <Pill>{liveOpsData.ingestion.new_total} new</Pill>
                      <Pill>{liveOpsData.ingestion.duplicate_total} duplicates</Pill>
                      <Pill>{Math.round(liveOpsData.ingestion.duplicate_rate * 100)}% duplicate rate</Pill>
                      <Pill>{liveOpsData.ingestion.rss_only_sources} RSS only</Pill>
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Operator Notes</p>
                      {liveOpsData.recommendations.map((item) => (
                        <p className="muted" key={item}>{item}</p>
                      ))}
                    </div>
                    {liveOpsData.attention_sources.length ? (
                      <div className="drawer-section">
                        <p className="eyebrow">Needs Attention</p>
                        <div className="tag-row">
                          {liveOpsData.attention_sources.slice(0, 6).map((source) => (
                            <button className="text-button" key={source.id} type="button" onClick={() => openSourceDrilldown(source.source_name)}>
                              {source.source_name}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="empty-state">Live operations status is loading.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Automation"
                title="Scheduler Control"
                action={<Pill tone={schedulerStatusData?.stale_warning ? "coral" : "green"}>{schedulerStatusData?.status || "unknown"}</Pill>}
              >
                {schedulerStatusData ? (
                  <div className="stack">
                    <div className="metric-grid compact-metrics">
                      <Metric label="Interval" value={`${schedulerStatusData.interval_minutes}m`} caption="target cadence" icon={Activity} />
                      <Metric label="Last Run" value={schedulerStatusData.stale_minutes ?? "-"} caption="minutes ago" icon={CircleDot} />
                      <Metric label="Next" value={dateLabel(schedulerStatusData.next_expected_run_at)} caption="expected run" icon={Bell} />
                      <Metric
                        label="Mode"
                        value={schedulerStatusData.process?.running ? "On" : schedulerStatusData.inferred_running ? "Fresh" : "Check"}
                        caption={schedulerStatusData.process?.pid ? `pid ${schedulerStatusData.process.pid}` : "process"}
                        icon={ShieldCheck}
                        accent
                      />
                    </div>
                    <div className="tag-row">
                      <button className="primary-button inline-action" type="button" onClick={() => runSchedulerAction("start")}>
                        Start Scheduler
                      </button>
                      <button className="text-button" type="button" onClick={() => runSchedulerAction("run_once")}>
                        Run One Cycle
                      </button>
                      <button className="text-button" type="button" onClick={() => runSchedulerAction("stop")}>
                        Stop Scheduler
                      </button>
                      <Pill tone={schedulerStatusData.process?.running ? "green" : "gold"}>
                        {schedulerStatusData.process?.running ? "process running" : "process stopped"}
                      </Pill>
                      <Pill tone={schedulerStatusData.heartbeat?.healthy ? "green" : "gold"}>
                        heartbeat {schedulerStatusData.heartbeat?.age_minutes ?? "none"} min
                      </Pill>
                    </div>
                    {schedulerActionStatus ? <p className="muted">{schedulerActionStatus}</p> : null}
                    <div className="drawer-section">
                      <p className="eyebrow">Start Command</p>
                      <p className="muted">{schedulerStatusData.start_command}</p>
                      <p className="muted">{schedulerStatusData.stop_hint}</p>
                      {schedulerStatusData.heartbeat?.payload?.status ? (
                        <p className="muted">Heartbeat status: {String(schedulerStatusData.heartbeat.payload.status)}</p>
                      ) : null}
                    </div>
                    <div className="drawer-section">
                      <p className="eyebrow">Logs</p>
                      <p className="muted">{schedulerStatusData.logs.stdout}</p>
                      <p className="muted">{schedulerStatusData.logs.stderr}</p>
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">Scheduler status is unavailable.</div>
                )}
              </Panel>

              <Panel eyebrow="Automation" title="Ingestion Run Timeline">
                <div className="source-list">
                  {ingestionRunData.length ? ingestionRunData.map((run) => (
                    <article className="source-card" key={run.id}>
                      <div className="source-main">
                        <div>
                          <div className="card-meta">
                            <Pill tone={run.status === "completed" ? "green" : run.status === "failed" ? "coral" : "gold"}>{run.status}</Pill>
                            <Pill>{run.run_type}</Pill>
                            <Pill>{dateLabel(run.finished_at || run.started_at)}</Pill>
                          </div>
                          <strong>Run #{run.id}</strong>
                          <p>{run.notes || "No notes."}</p>
                        </div>
                        <div className="stack">
                          <Pill tone="green">{run.total_new} new</Pill>
                          <Pill>{run.total_duplicate + run.total_duplicate_fuzzy} dupes</Pill>
                          <Pill tone={run.total_error ? "coral" : "green"}>{run.total_error} errors</Pill>
                        </div>
                      </div>
                    </article>
                  )) : (
                    <div className="empty-state">No ingestion runs recorded yet.</div>
                  )}
                </div>
              </Panel>

              <Panel eyebrow="Clients" title="Daily Brief Readiness">
                <div className="source-list">
                  {clientBriefReadinessData.length ? clientBriefReadinessData.map((item) => (
                    <article className="source-card" key={item.client_id}>
                      <div className="source-main">
                        <div>
                          <div className="card-meta">
                            <Pill tone={item.ready ? "green" : "gold"}>{item.status}</Pill>
                            <Pill>{item.client_type}</Pill>
                            <Pill>{item.plan}</Pill>
                          </div>
                          <strong>{item.client_name}</strong>
                          <p>{item.recommendation}</p>
                        </div>
                        <div className="stack">
                          <Pill>{item.matched_articles} matches</Pill>
                          <Pill>{item.source_count} sources</Pill>
                          <Pill tone={item.high_risk_items ? "coral" : "green"}>{item.high_risk_items} high risk</Pill>
                        </div>
                      </div>
                    </article>
                  )) : (
                    <div className="empty-state">No client readiness data yet.</div>
                  )}
                </div>
              </Panel>

              <Panel
                eyebrow="Quality"
                title="Stored Article Audit"
                action={
                  <div className="tag-row">
                    <Pill tone={articleQualityData?.issue_count ? "gold" : "green"}>
                      {articleQualityData?.issue_count ?? 0} flagged
                    </Pill>
                    <button className="text-button" type="button" onClick={bulkExcludeQualityArticles}>
                      Exclude Flagged
                    </button>
                  </div>
                }
              >
                {articleQualityData ? (
                  <div className="stack">
                    <div className="tag-row">
                      {Object.entries(articleQualityData.reason_counts).map(([reason, count]) => (
                        <Pill tone="gold" key={reason}>
                          {reason.replaceAll("_", " ")} {count}
                        </Pill>
                      ))}
                    </div>
                    {articleQualityData.issues.length ? (
                      <div className="source-list">
                        {articleQualityData.issues.map((issue) => (
                          <article className="source-card" key={issue.article_id}>
                            <div className="source-main">
                              <div>
                                <div className="card-meta">
                                  <Pill>{issue.source_name}</Pill>
                                  <Pill>{issue.ingestion_method}</Pill>
                                  <Pill tone={issue.quality_status === "excluded" ? "coral" : issue.quality_status === "approved" ? "green" : "gold"}>
                                    {issue.quality_status.replaceAll("_", " ")}
                                  </Pill>
                                  {issue.word_count ? <Pill>{issue.word_count} words</Pill> : null}
                                  {issue.reasons.map((reason) => (
                                    <Pill tone="gold" key={reason}>{reason.replaceAll("_", " ")}</Pill>
                                  ))}
                                </div>
                                <a href={issue.url} target="_blank" rel="noreferrer">{issue.title}</a>
                                <p>{dateLabel(issue.published_at || issue.ingested_at)}</p>
                                {issue.quality_notes ? <p className="muted">{issue.quality_notes}</p> : null}
                              </div>
                              <div className="stack">
                                <strong>#{issue.article_id}</strong>
                                <button className="text-button" type="button" onClick={() => reviewArticleQuality(issue.article_id, "approved")}>
                                  Approve
                                </button>
                                <button className="text-button" type="button" onClick={() => reviewArticleQuality(issue.article_id, "needs_review")}>
                                  Review
                                </button>
                                <button className="text-button" type="button" onClick={() => reviewArticleQuality(issue.article_id, "excluded")}>
                                  Exclude
                                </button>
                              </div>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <div className="empty-state">No suspicious stored articles found in the latest audit window.</div>
                    )}
                    {articleQualityData.cleanup_command ? (
                      <p className="muted">Dry-run cleanup: {articleQualityData.cleanup_command}</p>
                    ) : null}
                    {articleQualityStatus ? <p className="muted">{articleQualityStatus}</p> : null}
                  </div>
                ) : (
                  <div className="empty-state">Article quality audit is loading.</div>
                )}
              </Panel>

              <Panel
                eyebrow="Operations"
                title="Facebook Ingestion"
                action={<Pill tone={facebookOps?.token_configured ? "green" : "coral"}>{facebookOps?.token_configured ? "token ready" : "no token"}</Pill>}
              >
                <div className="metric-grid compact-metrics">
                  <Metric label="Pages" value={facebookOps?.configured_pages ?? "-"} caption="configured" icon={Globe2} />
                  <Metric label="Active" value={facebookOps?.active_pages ?? "-"} caption="monitored" icon={Activity} />
                  <Metric label="Posts" value={facebookOps?.recent_facebook_posts_7d ?? "-"} caption="last 7 days" icon={Newspaper} />
                </div>
                <div className="drawer-section">
                  <div className="card-meta">
                    <Pill>API {facebookOps?.api_version || "-"}</Pill>
                    <Pill tone={facebookOps?.never_fetched_pages ? "gold" : "green"}>
                      {facebookOps?.never_fetched_pages ?? 0} never fetched
                    </Pill>
                  </div>
                  {facebookOps?.latest_post ? (
                    <ArticleCard article={facebookOps.latest_post} onInspect={setSelectedArticle} />
                  ) : (
                    <div className="empty-state">No Facebook posts stored yet.</div>
                  )}
                  <button className="primary-button" type="button" onClick={fetchFacebookNow}>
                    Fetch Facebook Now
                  </button>
                  {facebookFetchStatus ? <p className="muted">{facebookFetchStatus}</p> : null}
                  {lastFacebookFetch ? (
                    <div className="card-meta">
                      <Pill tone="gold">{lastFacebookFetch.raw_posts} raw</Pill>
                      <Pill tone="green">{lastFacebookFetch.ingestion.new} new</Pill>
                      <Pill>{lastFacebookFetch.ingestion.duplicate} duplicates</Pill>
                      <Pill>{lastFacebookFetch.processing.processed} processed</Pill>
                    </div>
                  ) : null}
                </div>
              </Panel>

              <Panel eyebrow="Facebook / Meta" title="Add Public Page Monitor">
                <form className="admin-form" onSubmit={saveFacebookPage}>
                  <label>
                    Display name
                    <input
                      value={facebookForm.name}
                      onChange={(event) => setFacebookForm({ ...facebookForm, name: event.target.value })}
                      placeholder="Politician, media page, journalist"
                      required
                    />
                  </label>
                  <label>
                    Facebook URL
                    <input
                      value={facebookForm.url}
                      onChange={(event) => setFacebookForm({ ...facebookForm, url: event.target.value })}
                      placeholder="https://www.facebook.com/page"
                      required
                    />
                  </label>
                  <div className="form-grid">
                    <label>
                      Page handle
                      <input
                        value={facebookForm.page_handle}
                        onChange={(event) => setFacebookForm({ ...facebookForm, page_handle: event.target.value })}
                        placeholder="optional"
                      />
                    </label>
                    <label>
                      Page ID
                      <input
                        value={facebookForm.page_id}
                        onChange={(event) => setFacebookForm({ ...facebookForm, page_id: event.target.value })}
                        placeholder="optional"
                      />
                    </label>
                  </div>
                  <div className="form-grid">
                    <label>
                      Type
                      <select
                        value={facebookForm.monitor_type}
                        onChange={(event) => setFacebookForm({ ...facebookForm, monitor_type: event.target.value })}
                      >
                        <option value="political_figure">Political figure</option>
                        <option value="political_party">Political party</option>
                        <option value="journalist">Journalist</option>
                        <option value="media">Media</option>
                        <option value="government">Government</option>
                        <option value="institution">Institution</option>
                        <option value="activist">Activist</option>
                      </select>
                    </label>
                    <label>
                      Language
                      <select
                        value={facebookForm.language}
                        onChange={(event) => setFacebookForm({ ...facebookForm, language: event.target.value })}
                      >
                        <option value="mk">Macedonian</option>
                        <option value="sq">Albanian</option>
                        <option value="en">English</option>
                      </select>
                    </label>
                  </div>
                  <div className="form-grid">
                    <label>
                      Political leaning
                      <select
                        value={facebookForm.political_leaning}
                        onChange={(event) => setFacebookForm({ ...facebookForm, political_leaning: event.target.value })}
                      >
                        <option value="unknown">Unknown</option>
                        <option value="government">Government</option>
                        <option value="opposition">Opposition</option>
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                      </select>
                    </label>
                    <label>
                      Reliability
                      <input
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        value={facebookForm.reliability_score}
                        onChange={(event) => setFacebookForm({ ...facebookForm, reliability_score: Number(event.target.value) })}
                      />
                    </label>
                  </div>
                  <label>
                    Ownership / notes
                    <input
                      value={facebookForm.ownership || ""}
                      onChange={(event) => setFacebookForm({ ...facebookForm, ownership: event.target.value })}
                      placeholder="official page, public page, party page"
                    />
                  </label>
                  <button className="primary-button" type="submit">Add Facebook Page</button>
                  {facebookSaveStatus ? <p className="muted">{facebookSaveStatus}</p> : null}
                </form>
              </Panel>

              <Panel
                eyebrow="Sources"
                title="Facebook Watchlist"
                action={<Pill tone="gold">{facebookPageData.length} pages</Pill>}
              >
                <div className="source-list">
                  {facebookPageData.length ? (
                    facebookPageData.map((page) => <FacebookPageCard page={page} key={page.id} />)
                  ) : (
                    <div className="empty-state">No Facebook Pages configured yet.</div>
                  )}
                </div>
              </Panel>
            </div>
            ) : (
              <div className="empty-state">Admin role required.</div>
            )}
          </section>
        ) : null}

        {view === "clients" ? (
          <section className="view">
            {staffAccess ? (
              <PersonaSwitcher clients={clientData} activeClientId={activeClientId} onSelect={setSelectedClientId} />
            ) : null}
            {staffAccess ? (
              <PilotReadinessRibbon
                scheduler={schedulerStatusData}
                sourceHealth={sourceHealthData}
                articleQuality={articleQualityData}
                intelligenceQA={intelligenceQAData}
              />
            ) : null}
            <div className="client-layout">
              {staffAccess ? (
              <div className="client-sidebar">
                <Panel eyebrow="Setup" title="Create Client" className="flush">
                  <form className="admin-form" onSubmit={saveClient}>
                    <label>
                      Client name
                      <input
                        value={clientForm.name}
                        onChange={(event) => setClientForm({ ...clientForm, name: event.target.value })}
                        placeholder="Political figure, party, agency"
                        required
                      />
                    </label>
                    <label>
                      Email
                      <input
                        value={clientForm.email}
                        onChange={(event) => setClientForm({ ...clientForm, email: event.target.value })}
                        placeholder="optional"
                      />
                    </label>
                    <label>
                      Client type
                      <select
                        value={clientForm.client_type}
                        onChange={(event) => setClientForm({ ...clientForm, client_type: event.target.value })}
                      >
                        <option value="political_figure">Political figure</option>
                        <option value="political_party">Political party</option>
                        <option value="pr_agency">PR agency</option>
                        <option value="journalist">Journalist</option>
                        <option value="media_analyst">Media analyst</option>
                        <option value="business_risk">Business risk</option>
                        <option value="diaspora">Diaspora</option>
                      </select>
                    </label>
                    <div className="form-grid">
                      <label>
                        Plan
                        <select
                          value={clientForm.plan}
                          onChange={(event) => setClientForm({ ...clientForm, plan: event.target.value })}
                        >
                          <option value="basic">Basic</option>
                          <option value="pro">Pro</option>
                          <option value="political_defense">Political Defense</option>
                          <option value="campaign">Campaign</option>
                          <option value="enterprise">Enterprise</option>
                        </select>
                      </label>
                      <label>
                        Language
                        <select
                          value={clientForm.language}
                          onChange={(event) => setClientForm({ ...clientForm, language: event.target.value })}
                        >
                          <option value="mk">Macedonian</option>
                          <option value="sq">Albanian</option>
                          <option value="en">English</option>
                        </select>
                      </label>
                    </div>
                    <button className="primary-button" type="submit">Create Client</button>
                    {clientSaveStatus ? <p className="muted">{clientSaveStatus}</p> : null}
                  </form>
                </Panel>

                <Panel eyebrow="Accounts" title="Client Personas" className="flush">
                  <div className="client-list">
                    {clientData.length ? (
                      clientData.map((client) => (
                        <ClientCard
                          client={client}
                          key={client.id}
                          selected={activeClientId === client.id}
                          onSelect={setSelectedClientId}
                        />
                      ))
                    ) : (
                      <div className="empty-state">No client personas yet.</div>
                    )}
                  </div>
                </Panel>
              </div>
              ) : null}

              <div className="client-dashboard">
                {staffAccess ? <DataFreshnessStrip status={schedulerStatusData} /> : null}
                {staffAccess && clientTab === "setup" ? (
                <Panel eyebrow="Watchlist" title="Add Tracked Interest">
                  <form className="admin-form" onSubmit={saveWatchlistItem}>
                    <div className="form-grid">
                      <label>
                        Type
                        <select
                          value={watchlistForm.item_type}
                          onChange={(event) => updateWatchlistType(event.target.value)}
                        >
                          <option value="entity">Political figure / entity</option>
                          <option value="opponent">Opponent</option>
                          <option value="keyword">Keyword</option>
                          <option value="topic">Topic</option>
                          <option value="facebook_page">Facebook page</option>
                          <option value="source">News/media source</option>
                        </select>
                      </label>
                      <label>
                        Priority
                        <select
                          value={watchlistForm.priority}
                          onChange={(event) => setWatchlistForm({ ...watchlistForm, priority: Number(event.target.value) })}
                        >
                          <option value={1}>Critical</option>
                          <option value={2}>High</option>
                          <option value={3}>Normal</option>
                          <option value={4}>Low</option>
                          <option value={5}>Archive</option>
                        </select>
                      </label>
                    </div>
                    {watchlistForm.item_type === "entity" || watchlistForm.item_type === "opponent" ? (
                      <label>
                        Pick existing entity
                        <select
                          value={entityPicker}
                          onChange={(event) => {
                            const next = event.target.value;
                            const entity = entityData.find((item) => String(item.id) === next);
                            setEntityPicker(next);
                            if (entity) {
                              setWatchlistForm({
                                ...watchlistForm,
                                label: entity.name,
                                value: entity.canonical_name,
                                entity_id: entity.id,
                              });
                            }
                          }}
                        >
                          <option value="">Manual entry</option>
                          {entityData.slice(0, 80).map((entity) => (
                            <option value={entity.id} key={entity.id}>
                              {entity.name} · {entity.entity_type} · {entity.total_mentions}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    {watchlistForm.item_type === "source" ? (
                      <label>
                        Pick media/source
                        <select
                          value={sourcePicker}
                          onChange={(event) => {
                            const next = event.target.value;
                            const source = sourceData.find((item) => String(item.source_id) === next);
                            setSourcePicker(next);
                            if (source) {
                              setWatchlistForm({
                                ...watchlistForm,
                                label: source.name,
                                value: source.url,
                                source_id: source.source_id,
                              });
                            }
                          }}
                        >
                          <option value="">Manual entry</option>
                          {sourceData.map((source) => (
                            <option value={source.source_id} key={source.source_id}>
                              {source.name} · {source.source_type} · {source.article_count}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    {watchlistForm.item_type === "facebook_page" ? (
                      <label>
                        Pick Facebook page
                        <select
                          value={facebookPicker}
                          onChange={(event) => {
                            const next = event.target.value;
                            const page = facebookPageData.find((item) => String(item.id) === next);
                            setFacebookPicker(next);
                            if (page) {
                              setWatchlistForm({
                                ...watchlistForm,
                                label: page.name,
                                value: page.page_handle || page.url,
                                facebook_page_url: page.url,
                              });
                            }
                          }}
                        >
                          <option value="">Manual entry</option>
                          {facebookPageData.map((page) => (
                            <option value={page.id} key={page.id}>
                              {page.name} · {page.monitor_type}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    <div className="form-grid">
                      <label>
                        Label
                        <input
                          value={watchlistForm.label}
                          onChange={(event) => setWatchlistForm({ ...watchlistForm, label: event.target.value })}
                          placeholder="Display name"
                          required
                        />
                      </label>
                      <label>
                        Value
                        <input
                          value={watchlistForm.value}
                          onChange={(event) => setWatchlistForm({ ...watchlistForm, value: event.target.value })}
                          placeholder="name, keyword, handle, source"
                          required
                        />
                      </label>
                    </div>
                    <div className="form-grid">
                      <label>
                        Entity ID
                        <input
                          type="number"
                          value={watchlistForm.entity_id || ""}
                          onChange={(event) => setWatchlistForm({ ...watchlistForm, entity_id: event.target.value ? Number(event.target.value) : null })}
                          placeholder="optional"
                          disabled={Boolean(entityPicker)}
                        />
                      </label>
                      <label>
                        Source ID
                        <input
                          type="number"
                          value={watchlistForm.source_id || ""}
                          onChange={(event) => setWatchlistForm({ ...watchlistForm, source_id: event.target.value ? Number(event.target.value) : null })}
                          placeholder="optional"
                          disabled={Boolean(sourcePicker)}
                        />
                      </label>
                    </div>
                    <label>
                      Facebook page URL
                      <input
                        value={watchlistForm.facebook_page_url}
                        onChange={(event) => setWatchlistForm({ ...watchlistForm, facebook_page_url: event.target.value })}
                        placeholder="optional, for Facebook page tracking"
                      />
                    </label>
                    <label>
                      Notes
                      <input
                        value={watchlistForm.notes}
                        onChange={(event) => setWatchlistForm({ ...watchlistForm, notes: event.target.value })}
                        placeholder="why this matters"
                      />
                    </label>
                    <button className="primary-button" type="submit">Add To Watchlist</button>
                    {watchlistSaveStatus ? <p className="muted">{watchlistSaveStatus}</p> : null}
                  </form>
                </Panel>
                ) : null}

                {!clientDash ? (
                  <Panel eyebrow="Secure Workspace" title="Preparing your personalized intelligence">
                    <div className="workspace-loading-body" role="status">
                      <RefreshCw size={20} />
                      <p>Loading only the mentions, risks, cases, and sources permitted for this account.</p>
                    </div>
                  </Panel>
                ) : (
                <>
                <div className="client-context-bar" aria-label="Dashboard coverage window">
                  <div>
                    <span>Coverage window</span>
                    <strong>{clientWindowDays === 7 ? "Last week" : clientWindowDays === 30 ? "Last 30 days" : "Last 90 days"}</strong>
                  </div>
                  <div className="window-selector" role="group" aria-label="Choose coverage period">
                    {([7, 30, 90] as const).map((days) => (
                      <button
                        className={clientWindowDays === days ? "is-active" : ""}
                        key={days}
                        type="button"
                        aria-pressed={clientWindowDays === days}
                        onClick={() => setClientWindowDays(days)}
                      >
                        {days === 7 ? "7 days" : days === 30 ? "30 days" : "90 days"}
                      </button>
                    ))}
                  </div>
                </div>
                {!isPoliticalFigureClient ? (
                <div className="metric-grid compact-metrics">
                  <Metric
                    label={clientMetricLabels(clientDash?.client, clientWindowDays)[0].label}
                    value={clientDash?.metrics.watchlist_items ?? "-"}
                    caption={clientMetricLabels(clientDash?.client, clientWindowDays)[0].caption}
                    icon={ShieldCheck}
                  />
                  <Metric
                    label={clientMetricLabels(clientDash?.client, clientWindowDays)[1].label}
                    value={clientDash?.metrics.matched_articles ?? "-"}
                    caption={clientMetricLabels(clientDash?.client, clientWindowDays)[1].caption}
                    icon={Newspaper}
                  />
                  <Metric
                    label={clientMetricLabels(clientDash?.client, clientWindowDays)[2].label}
                    value={clientDash?.metrics.risk_items ?? "-"}
                    caption={clientMetricLabels(clientDash?.client, clientWindowDays)[2].caption}
                    icon={Bell}
                    accent
                  />
                  <Metric
                    label={clientMetricLabels(clientDash?.client, clientWindowDays)[3].label}
                    value={incidentData.length}
                    caption={clientMetricLabels(clientDash?.client, clientWindowDays)[3].caption}
                    icon={BookOpenText}
                  />
                </div>
                ) : null}

                <div className={`client-tabbar ${isPoliticalFigureClient ? "figure-tabs" : ""}`}>
                  {visibleClientTabs.map(({ id, label, detail }) => (
                    <button
                      className={`client-tab ${clientTab === id ? "is-active" : ""}`}
                      key={id}
                      type="button"
                      onClick={() => setClientTab(id)}
                    >
                      <strong>{label}</strong>
                      <span>{detail}</span>
                    </button>
                  ))}
                </div>

                {isPoliticalFigureClient ? (
                  <PoliticalFigureWorkspace
                    components={workspaceComponents}
                    dateLabel={dateLabel}
                    clientDash={clientDash}
                    selectedTab={clientTab}
                    incidents={incidentData}
                    status={[responsePackStatus, timelineStatus, incidentSaveStatus, watchlistAlertStatus].filter(Boolean).join(" ")}
                    onSelectTab={setClientTab}
                    onResponsePack={openResponsePack}
                    onTimeline={openAttackTimeline}
                    onSaveCase={saveRiskItemAsIncident}
                    onCreateAlert={createWatchlistAlert}
                    onInspectArticle={setSelectedArticle}
                    chatQuestion={clientChatQuestion}
                    chatAnswer={clientChatAnswer}
                    chatStatus={clientChatStatus}
                    onChatQuestionChange={setClientChatQuestion}
                    onAskChat={askClientChat}
                    onNewChat={startNewClientChat}
                  />
                ) : (
                  <ClientPersonaWorkspace
                    components={workspaceComponents}
                    dateLabel={dateLabel}
                    clientDash={clientDash}
                    selectedTab={clientTab}
                    incidents={incidentData}
                    savedBriefings={savedBriefingData}
                    savedTopics={savedTopicData}
                    dailyBrief={clientDailyBriefData}
                    status={[responsePackStatus, timelineStatus, incidentSaveStatus, watchlistAlertStatus].filter(Boolean).join(" ")}
                    chatQuestion={clientChatQuestion}
                    chatAnswer={clientChatAnswer}
                    chatStatus={clientChatStatus}
                    onChatQuestionChange={setClientChatQuestion}
                    onAskChat={askClientChat}
                    onNewChat={startNewClientChat}
                    onSelectTab={setClientTab}
                    onResponsePack={openResponsePack}
                    onTimeline={openAttackTimeline}
                    onSaveCase={saveRiskItemAsIncident}
                    onCreateAlert={createWatchlistAlert}
                    onInspectArticle={setSelectedArticle}
                    onDemoBriefing={generateDemoBriefing}
                  />

                )}

                </>
                )}

              </div>
            </div>
          </section>
        ) : null}

        {view === "articles" ? (
          <section className="view">
            <div className="saved-search-toolbar">
              <div className="saved-search-heading">
                <BookmarkPlus size={20} />
                <div>
                  <strong>Saved searches</strong>
                  <p>Keep a reusable query with its dates, sources, language, entity, reliability, and sentiment filters.</p>
                </div>
              </div>
              <form className="saved-search-form" onSubmit={saveCurrentSearch}>
                <input
                  value={savedSearchName}
                  onChange={(event) => setSavedSearchName(event.target.value)}
                  placeholder={search.trim() || "Name this search"}
                  aria-label="Saved search name"
                />
                <button className="primary-button" type="submit">
                  <BookmarkPlus size={16} />
                  Save current search
                </button>
              </form>
              {savedSearchData.length ? (
                <div className="saved-search-list" aria-label="Your saved searches">
                  {savedSearchData.map((item) => (
                    <div className="saved-search-item" key={item.id}>
                      <button className="saved-search-open" type="button" onClick={() => applySavedSearch(item)}>
                        <strong>{item.title}</strong>
                        <span>{item.query || "Filtered article search"}</span>
                      </button>
                      <button className="icon-button compact-icon" type="button" onClick={() => removeSavedSearch(item.id)} aria-label={`Delete ${item.title}`} title="Delete saved search">
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="saved-search-empty">No saved searches yet.</p>
              )}
              {savedSearchStatus ? <p className="saved-search-status" role="status">{savedSearchStatus}</p> : null}
            </div>
            <div className="filter-row">
              <select value={dateBasis} onChange={(event) => setDateBasis(event.target.value)}>
                <option value="published">Published date</option>
                <option value="fetched">Fetched date</option>
                <option value="ingested">Ingested date</option>
              </select>
              <label className="date-input">
                From
                <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
              </label>
              <label className="date-input">
                To
                <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
              </label>
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="">All categories</option>
                {categoryData.map((item) => (
                  <option value={item.category} key={item.category}>
                    {item.category}
                  </option>
                ))}
              </select>
              <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                <option value="">All languages</option>
                <option value="mk">Macedonian</option>
                <option value="en">English</option>
                <option value="sq">Albanian</option>
              </select>
              <select value={articleSourceId} onChange={(event) => setArticleSourceId(event.target.value)}>
                <option value="">All sources</option>
                {sourceData.map((source) => (
                  <option value={source.source_id} key={`article-source-${source.source_id}`}>
                    {source.name}
                  </option>
                ))}
              </select>
              <select value={articleEntityId} onChange={(event) => setArticleEntityId(event.target.value)}>
                <option value="">Any entity</option>
                {entityData.slice(0, 80).map((entity) => (
                  <option value={entity.id} key={`article-entity-${entity.id}`}>
                    {entity.name}
                  </option>
                ))}
              </select>
              <select value={articleSourceType} onChange={(event) => setArticleSourceType(event.target.value)}>
                <option value="">All source types</option>
                <option value="news">News</option>
                <option value="wire">Wire</option>
                <option value="government">Government</option>
                <option value="social_media">Social media</option>
                <option value="blog">Blog</option>
              </select>
              <select value={minReliability} onChange={(event) => setMinReliability(event.target.value)}>
                <option value="">Any reliability</option>
                <option value="0.8">80%+</option>
                <option value="0.6">60%+</option>
                <option value="0.4">40%+</option>
              </select>
              <select value={sentimentFilter} onChange={(event) => setSentimentFilter(event.target.value)}>
                <option value="">Any sentiment</option>
                <option value="negative">Negative</option>
                <option value="neutral">Neutral</option>
                <option value="positive">Positive</option>
              </select>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={exactPhrase}
                  onChange={(event) => setExactPhrase(event.target.checked)}
                />
                Exact phrase
              </label>
              <button
                className="text-button"
                type="button"
                onClick={() => {
                  setCategory("");
                  setLanguage("");
                  setArticleSourceId("");
                  setArticleEntityId("");
                  setArticleSourceType("");
                  setMinReliability("");
                  setSentimentFilter("");
                  setExactPhrase(false);
                  setDateFrom("");
                  setDateTo("");
                }}
              >
                Clear Filters
              </button>
            </div>
            {topicBriefingData ? (
              <Panel
                eyebrow="Topic Intelligence"
                title={topicBriefingData.headline}
                action={
                  <div className="tag-row">
                    <Pill tone={topicBriefingData.validation_status === "validated" ? "green" : topicBriefingData.validation_status === "multi_source" ? "gold" : "coral"}>
                      {topicBriefingData.validation_status.replaceAll("_", " ")}
                    </Pill>
                    {activeClientId ? (
                      <button className="text-button" type="button" onClick={saveTopicBriefing}>
                        Save Topic
                      </button>
                    ) : null}
                  </div>
                }
              >
                <div className="stack">
                  <p>{topicBriefingData.summary}</p>
                  <div className="brief-grid">
                    <div className="brief-item">
                      <strong>{topicBriefingData.article_count}</strong>
                      <p>matched articles</p>
                    </div>
                    <div className="brief-item">
                      <strong>{topicBriefingData.source_count}</strong>
                      <p>sources reporting</p>
                    </div>
                    <div className="brief-item">
                      <strong>{topicBriefingData.top_entities.length}</strong>
                      <p>connected entities</p>
                    </div>
                  </div>
                  {topicBriefingData.timeline.length ? (
                    <div className="mini-chart">
                      <p className="eyebrow">Coverage Timeline</p>
                      <ResponsiveContainer width="100%" height={190}>
                        <BarChart data={topicBriefingData.timeline}>
                          <CartesianGrid stroke="#e2e8ef" vertical={false} />
                          <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                          <YAxis width={30} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                          <Tooltip />
                          <Bar dataKey="article_count" fill="#147c80" radius={[8, 8, 0, 0]} />
                          <Bar dataKey="source_count" fill="#c7912d" radius={[8, 8, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : null}
                  <div className="related-strip">
                    <p className="eyebrow">Top Sources</p>
                    <div className="tag-row">
                      {topicBriefingData.source_coverage.slice(0, 8).map((source) => (
                        <Pill key={source.source_name}>{source.source_name} - {source.article_count}</Pill>
                      ))}
                    </div>
                  </div>
                  <div className="related-strip">
                    <p className="eyebrow">Connected Entities</p>
                    <div className="tag-row">
                      {topicBriefingData.top_entities.slice(0, 8).map((entity) => (
                        <Pill key={entity.entity_id} tone="gold">{entity.name} - {entity.article_count}</Pill>
                      ))}
                    </div>
                  </div>
                  <div className="related-strip">
                    <p className="eyebrow">Verification Notes</p>
                    <ul className="response-list">
                      {topicBriefingData.recommended_actions.map((action) => (
                        <li key={action}>{action}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </Panel>
            ) : search.trim().length >= 2 && topicBriefing.isLoading ? (
              <Panel eyebrow="Topic Intelligence" title="Building topic view">
                <div className="empty-state">Checking dates, sources, and connected entities...</div>
              </Panel>
            ) : null}
            <div className="article-list">
              {articleData.map((article) => (
                <ArticleCard article={article} key={article.id} onInspect={setSelectedArticle} />
              ))}
            </div>
          </section>
        ) : null}

        {view === "entities" ? (
          <section className="view">
            <div className="filter-row">
              <select value={entityType} onChange={(event) => setEntityType(event.target.value)}>
                <option value="">All entity types</option>
                <option value="person">People</option>
                <option value="organization">Organizations</option>
                <option value="location">Locations</option>
              </select>
            </div>
            <div className="entity-layout">
              <Panel eyebrow="Directory" title="Entities" className="flush">
                <EntityRows entities={entityData} selectedId={selectedEntityId} onSelect={setSelectedEntityId} />
              </Panel>
              <EntityDetailPanel
                selectedId={selectedEntityId}
                activeClientId={activeClientId}
                currentUser={currentUser}
                staffAccess={staffAccess}
              />
            </div>
          </section>
        ) : null}

        {view === "sources" ? (
          <section className="view">
            <div className="source-grid">
              {sourceData.length ? (
                sourceData.map((source) => <SourceCard source={source} key={source.source_id} />)
              ) : (
                <div className="empty-state">No source coverage data available yet.</div>
              )}
            </div>
          </section>
        ) : null}

        {view === "stories" ? (
          <section className="view">
            <div className="filter-row">
              <select value={storyClusterStatusFilter} onChange={(event) => setStoryClusterStatusFilter(event.target.value)}>
                <option value="">All validation states</option>
                <option value="validated">Validated</option>
                <option value="multi_source">Multi-source</option>
                <option value="single_source">Single-source</option>
              </select>
              <select value={storyClusterDays} onChange={(event) => setStoryClusterDays(Number(event.target.value))}>
                <option value={7}>Last 7 days</option>
                <option value={14}>Last 14 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
              </select>
              <button className="primary-button" type="button" onClick={rebuildStoryClusters}>
                Rebuild Story Clusters
              </button>
              {storyStatus ? <p className="muted">{storyStatus}</p> : null}
            </div>
            <div className="metric-grid compact-metrics">
              <Metric label="Validated" value={storyClusterData.filter((cluster) => cluster.status === "validated").length} caption="high-confidence clusters" icon={ShieldCheck} />
              <Metric label="Multi-source" value={storyClusterData.filter((cluster) => (cluster.original_source_count ?? cluster.source_count) >= 2).length} caption="original portals" icon={Globe2} />
              <Metric label="Single-source" value={storyClusterData.filter((cluster) => cluster.status === "single_source").length} caption="needs verification" icon={Bell} />
              <Metric label="Aggregator" value={storyClusterData.filter((cluster) => cluster.aggregator_source_count > 0).length} caption="indexed by TIME-like sources" icon={Activity} />
            </div>
            <div className="trend-grid">
              {storyClusterData.length ? (
                storyClusterData.map((cluster) => (
                  <article className="trend-card" key={cluster.id}>
                    <div>
                      <div className="card-meta">
                        <Pill tone={cluster.status === "validated" ? "green" : cluster.status === "multi_source" ? "gold" : "coral"}>
                          {cluster.status.replaceAll("_", " ")}
                        </Pill>
                        <Pill>{cluster.original_source_count ?? cluster.source_count} original</Pill>
                        {cluster.aggregator_source_count ? <Pill tone="gold">{cluster.aggregator_source_count} aggregator</Pill> : null}
                        <Pill>{cluster.article_count} articles</Pill>
                        <Pill>{Math.round(cluster.average_reliability * 100)}% trust</Pill>
                        <Pill>{cluster.high_reliability_source_count} high-rel</Pill>
                        {cluster.spread_hours !== null && cluster.spread_hours !== undefined ? <Pill>{cluster.spread_hours}h</Pill> : null}
                      </div>
                      <h3>{cluster.title}</h3>
                      <p>{cluster.validation_explanation}</p>
                      {cluster.summary ? <p className="muted">{cluster.summary}</p> : null}
                      <div className="tag-row">
                        {cluster.sources.slice(0, 8).map((source) => (
                          <Pill key={`${cluster.id}-${source}`}>{source}</Pill>
                        ))}
                      </div>
                      {cluster.risk_flags.length ? (
                        <div className="tag-row">
                          {cluster.risk_flags.map((flag) => <Pill tone="coral" key={`${cluster.id}-${flag}`}>{flag.replaceAll("_", " ")}</Pill>)}
                        </div>
                      ) : null}
                      <div className="article-list compact">
                        {cluster.articles.slice(0, 4).map((article) => (
                          <a className="text-button" href={article.url} target="_blank" rel="noreferrer" key={article.article_id}>
                            {article.source_name}: {article.title}
                          </a>
                        ))}
                      </div>
                      <div className="tag-row">
                        <button className="text-button" type="button" onClick={() => setSelectedStoryCluster(cluster)}>
                          Open Validation
                        </button>
                        <button className="text-button" type="button" onClick={() => createStoryClusterAlert(cluster)}>
                          Alert On Spread
                        </button>
                      </div>
                    </div>
                    <div className="trend-score">{cluster.original_source_count ?? cluster.source_count}</div>
                  </article>
                ))
              ) : (
                <div className="empty-state">No story clusters built yet.</div>
              )}
            </div>
          </section>
        ) : null}

        {view === "trends" ? (
          <section className="view">
            <div className="trend-grid">
              {trendData.map((trend) => (
                <TrendCard trend={trend} key={trend.entity_id} />
              ))}
            </div>
          </section>
        ) : null}

        {view === "alerts" ? (
          <section className="view">
            <Panel
              eyebrow="Monitoring"
              title="Alert Rules"
              action={<Pill tone="green">{alertData.filter((alert) => alert.is_active).length} active</Pill>}
            >
              <div className="alert-list">
                {alertData.length ? alertData.map((alert) => (
                  <AlertCard alert={alert} key={alert.id} onDeactivate={deactivateAlert} />
                )) : (
                  <div className="empty-state">No alerts configured yet.</div>
                )}
                {alertOpsStatus ? <div className="empty-state">{alertOpsStatus}</div> : null}
              </div>
            </Panel>
          </section>
        ) : null}

        {selectedArticle ? (
          <div className="drawer-backdrop" onClick={() => setSelectedArticle(undefined)}>
            <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">{selectedArticle.source_name}</p>
                  <h3>{selectedArticle.title}</h3>
                </div>
                <button className="icon-button" onClick={() => setSelectedArticle(undefined)} aria-label="Close article">
                  X
                </button>
              </div>
              <div className="card-meta">
                <Pill tone="gold">Published {dateLabel(selectedArticle.published_at)}</Pill>
                <Pill>Fetched {dateLabel(selectedArticle.fetched_at)}</Pill>
                <Pill>Ingested {dateLabel(selectedArticle.ingested_at)}</Pill>
                <Pill tone="green">{selectedArticle.ingestion_method}</Pill>
                {selectedArticle.platform ? <Pill tone="green">{selectedArticle.platform}</Pill> : null}
                {selectedArticle.platform_account_name ? (
                  <Pill>{selectedArticle.platform_account_name}</Pill>
                ) : null}
                <Pill tone="green">{selectedArticle.language}</Pill>
                {selectedArticle.word_count ? <Pill>{selectedArticle.word_count} words</Pill> : null}
                <Pill tone={selectedArticle.quality_status === "excluded" ? "coral" : selectedArticle.quality_status === "approved" ? "green" : "gold"}>
                  {selectedArticle.quality_status.replaceAll("_", " ")}
                </Pill>
              </div>
              {selectedArticle.quality_notes ? <p className="muted">{selectedArticle.quality_notes}</p> : null}
              <div className="drawer-section">
                <p className="eyebrow">Summary</p>
                <p>{selectedArticle.summaries?.[0]?.text || "No summary available yet."}</p>
              </div>
              <div className="drawer-section">
                <p className="eyebrow">Entities</p>
                <div className="tag-row">
                  {selectedArticle.entities.length ? (
                    selectedArticle.entities.map((entity) => (
                      <Pill key={entity.entity_id}>{entity.name}</Pill>
                    ))
                  ) : (
                    <span className="muted">No entities extracted.</span>
                  )}
                </div>
              </div>
              <div className="drawer-section article-body">
                <p className="eyebrow">Article Text</p>
                <p>{selectedArticle.content || "Full text is not stored for this article."}</p>
              </div>
              <a className="open-link" href={selectedArticle.url} target="_blank" rel="noreferrer">
                Open original article
              </a>
            </aside>
          </div>
        ) : null}

        {selectedSourceDrilldown ? (
          <div className="drawer-backdrop" onClick={() => setSelectedSourceDrilldown(undefined)}>
            <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Ingestion Failure Drilldown</p>
                  <h3>{selectedSourceDrilldown.source?.name || "Unmatched source"}</h3>
                </div>
                <button className="icon-button" onClick={() => setSelectedSourceDrilldown(undefined)} aria-label="Close source drilldown">
                  X
                </button>
              </div>
              <div className="card-meta">
                {selectedSourceDrilldown.source ? (
                  <>
                    <Pill tone={selectedSourceDrilldown.source.is_active ? "green" : "coral"}>
                      {selectedSourceDrilldown.source.is_active ? "active" : "disabled"}
                    </Pill>
                    <Pill>{selectedSourceDrilldown.source.source_type}</Pill>
                    <Pill>{selectedSourceDrilldown.source.political_leaning}</Pill>
                    <Pill tone="gold">{Math.round(selectedSourceDrilldown.source.reliability_score * 100)}% reliability</Pill>
                  </>
                ) : (
                  <Pill tone="gold">not in source table</Pill>
                )}
                <Pill>{selectedSourceDrilldown.recent_runs.length} recent runs</Pill>
              </div>
              <div className="drawer-section">
                <p className="eyebrow">Suggested Fix</p>
                <p>{selectedSourceDrilldown.suggested_fix}</p>
                {selectedSourceDrilldown.latest_error ? <p className="limit-warning">{selectedSourceDrilldown.latest_error}</p> : null}
              </div>
              {selectedSourceDrilldown.source ? (
                <div className="drawer-section">
                  <p className="eyebrow">Source Config</p>
                  <div className="source-config-controls">
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={selectedSourceDrilldown.source.is_active}
                        onChange={(event) => updateSourceConfig(selectedSourceDrilldown.source!.source_id, { is_active: event.target.checked })}
                      />
                      Active
                    </label>
                    <label>
                      Reliability
                      <input
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        defaultValue={selectedSourceDrilldown.source.reliability_score}
                        onBlur={(event) => updateSourceConfig(selectedSourceDrilldown.source!.source_id, { reliability_score: Number(event.target.value) })}
                      />
                    </label>
                    <label>
                      Type
                      <select
                        defaultValue={selectedSourceDrilldown.source.source_type}
                        onChange={(event) => updateSourceConfig(selectedSourceDrilldown.source!.source_id, { source_type: event.target.value })}
                      >
                        <option value="news">News</option>
                        <option value="wire">Wire</option>
                        <option value="government">Government</option>
                        <option value="social_media">Social media</option>
                        <option value="blog">Blog</option>
                        <option value="investigative">Investigative</option>
                      </select>
                    </label>
                    <label>
                      Leaning
                      <select
                        defaultValue={selectedSourceDrilldown.source.political_leaning}
                        onChange={(event) => updateSourceConfig(selectedSourceDrilldown.source!.source_id, { political_leaning: event.target.value })}
                      >
                        <option value="unknown">Unknown</option>
                        <option value="left">Left</option>
                        <option value="center">Center</option>
                        <option value="right">Right</option>
                        <option value="government">Government</option>
                        <option value="opposition">Opposition</option>
                      </select>
                    </label>
                    <label className="wide-control">
                      Ownership / notes
                      <input
                        defaultValue={selectedSourceDrilldown.source.ownership || ""}
                        onBlur={(event) => updateSourceConfig(selectedSourceDrilldown.source!.source_id, { ownership: event.target.value })}
                      />
                    </label>
                  </div>
                  <p className="muted">{selectedSourceDrilldown.source.url}</p>
                </div>
              ) : null}
              <div className="drawer-section">
                <p className="eyebrow">Recent Runs</p>
                <div className="source-list">
                  {selectedSourceDrilldown.recent_runs.map((run) => (
                    <article className="source-card" key={run.id}>
                      <div className="source-main">
                        <div>
                          <div className="card-meta">
                            <Pill tone={run.status === "healthy" || run.status === "caught_up" || run.status === "rss_only" ? "green" : run.status === "degraded" ? "gold" : "coral"}>
                              {run.status.replaceAll("_", " ")}
                            </Pill>
                            <Pill>run #{run.run_id}</Pill>
                            <Pill>{dateLabel(run.checked_at)}</Pill>
                            {run.stopped_early ? <Pill tone="gold">stopped on duplicates</Pill> : null}
                          </div>
                          <p>
                            discovered {run.discovered_urls}, scraped {run.scraped_count}, RSS {run.rss_count}, raw {run.raw_count}, new {run.new_count}, dupes {run.duplicate_count + run.duplicate_fuzzy_count}
                          </p>
                          {run.error_sample ? <p className="limit-warning">{run.error_sample}</p> : null}
                        </div>
                        <strong>{run.error_count + run.failed_count}</strong>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        ) : null}

        {selectedScraperPreflight ? (
          <div className="drawer-backdrop" onClick={() => setSelectedScraperPreflight(undefined)}>
            <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Scraper Preflight</p>
                  <h3>{selectedScraperPreflight.source_name}</h3>
                </div>
                <button className="icon-button" onClick={() => setSelectedScraperPreflight(undefined)} aria-label="Close scraper preflight">
                  X
                </button>
              </div>
              <div className="card-meta">
                <Pill tone={selectedScraperPreflight.status === "healthy" ? "green" : selectedScraperPreflight.status === "degraded" ? "gold" : "coral"}>
                  {selectedScraperPreflight.status.replaceAll("_", " ")}
                </Pill>
                {selectedScraperPreflight.scraper_enabled ? <Pill tone="green">scraper enabled</Pill> : <Pill tone="gold">scraper disabled</Pill>}
                {selectedScraperPreflight.rss_enabled ? <Pill>RSS enabled</Pill> : <Pill tone="gold">RSS disabled</Pill>}
              </div>
              <div className="metric-grid compact-metrics">
                <Metric label="Links" value={selectedScraperPreflight.discovered_urls} caption="discovered" icon={Globe2} />
                <Metric label="Extracted" value={selectedScraperPreflight.success_count} caption="article pages" icon={Newspaper} />
                <Metric label="Failed" value={selectedScraperPreflight.failed_count} caption="preflight sample" icon={Bell} />
                <Metric label="Avg Words" value={selectedScraperPreflight.average_word_count} caption="quality" icon={FileText} accent />
                <Metric label="Min Words" value={selectedScraperPreflight.min_word_count || 0} caption="shortest success" icon={FileText} />
              </div>
              <div className="drawer-section">
                <p className="eyebrow">Suggested Fix</p>
                <p>{selectedScraperPreflight.suggested_fix}</p>
                {selectedScraperPreflight.error_sample ? <p className="limit-warning">{selectedScraperPreflight.error_sample}</p> : null}
              </div>
              <div className="drawer-section">
                <p className="eyebrow">Failed URLs</p>
                <div className="source-list">
                  {selectedScraperPreflight.failure_details?.length ? selectedScraperPreflight.failure_details.map((failure) => (
                    <article className="draft-card" key={`${failure.url}-${failure.error}`}>
                      <div className="card-meta">
                        <Pill tone="coral">{failure.error || "failed"}</Pill>
                        <Pill>{failure.word_count || 0} words</Pill>
                      </div>
                      {failure.title ? <strong>{failure.title}</strong> : null}
                      <a className="article-title" href={failure.url} target="_blank" rel="noreferrer">{failure.url}</a>
                    </article>
                  )) : <div className="empty-state">No failed URLs in this sample.</div>}
                </div>
              </div>
              <div className="drawer-section">
                <p className="eyebrow">Sample URLs</p>
                <div className="source-list">
                  {selectedScraperPreflight.sample_urls.length ? selectedScraperPreflight.sample_urls.map((url) => (
                    <article className="draft-card" key={url}>
                      <a className="article-title" href={url} target="_blank" rel="noreferrer">{url}</a>
                    </article>
                  )) : <div className="empty-state">No sample URLs discovered.</div>}
                </div>
              </div>
            </aside>
          </div>
        ) : null}

        {selectedStoryCluster ? (
          <StoryClusterDetail
            cluster={selectedStoryCluster}
            onClose={() => setSelectedStoryCluster(undefined)}
            onCreateAlert={createStoryClusterAlert}
          />
        ) : null}

        {selectedResponsePack ? (
          <div className="drawer-backdrop" onClick={() => setSelectedResponsePack(undefined)}>
            <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Response Assistant</p>
                  <h3>{selectedResponsePack.watchlist_item.label}</h3>
                </div>
                <button className="icon-button" onClick={() => setSelectedResponsePack(undefined)} aria-label="Close response pack">
                  X
                </button>
              </div>
              <div className="card-meta">
                <Pill tone="coral">{selectedResponsePack.severity}</Pill>
                <Pill>{selectedResponsePack.client.name}</Pill>
                <Pill tone="green">{selectedResponsePack.client.plan}</Pill>
                <button className="text-button" onClick={saveResponsePackAsIncident}>
                  Save Case
                </button>
                <button className="text-button" onClick={generateResponsePackPdf}>
                  Export PDF
                </button>
                <button className="text-button" onClick={saveResponsePack}>
                  Save Pack
                </button>
                <button className="text-button" onClick={loadResponsePackTimeline}>
                  Load Timeline
                </button>
                <button
                  className="text-button"
                  onClick={() => copyTextToClipboard(responsePackCopyText(), setResponsePackReportStatus, "Press statement copied.")}
                >
                  Copy Press Statement
                </button>
              </div>
              {incidentSaveStatus ? <p className="muted">{incidentSaveStatus}</p> : null}
              {responsePackReportStatus ? <p className="muted">{responsePackReportStatus}</p> : null}
              {savedBriefingStatus ? <p className="muted">{savedBriefingStatus}</p> : null}

              <div className="drawer-section">
                <p className="eyebrow">Situation</p>
                <div className="card-meta">
                  <Pill tone={selectedResponsePack.confidence.level === "high" ? "green" : selectedResponsePack.confidence.level === "medium" ? "gold" : "coral"}>
                    Confidence {selectedResponsePack.confidence.score ?? "-"} / 100
                  </Pill>
                  <Pill>{selectedResponsePack.confidence.article_count ?? 0} articles</Pill>
                  <Pill>{selectedResponsePack.confidence.source_count ?? 0} sources</Pill>
                </div>
                <p>{selectedResponsePack.situation_summary}</p>
                {selectedResponsePack.confidence.reason ? <p className="muted">{selectedResponsePack.confidence.reason}</p> : null}
              </div>

              <div className="drawer-section attack-diagnosis">
                <p className="eyebrow">Attack Diagnosis</p>
                <div className="response-summary-grid">
                  <article>
                    <span>What</span>
                    <strong>{selectedResponsePack.attack_analysis.what_is_the_attack || "Pattern under review"}</strong>
                    <p>{selectedResponsePack.attack_analysis.why_it_matters || "Read the source trail before choosing a public line."}</p>
                  </article>
                  <article>
                    <span>Where</span>
                    <strong>{selectedResponsePack.attack_analysis.source_depth || "Source depth unknown"}</strong>
                    <p>{selectedResponsePack.attack_analysis.where_it_spread || "Open the timeline for spread context."}</p>
                  </article>
                  <article>
                    <span>Safest angle</span>
                    <strong>{selectedResponsePack.severity}</strong>
                    <p>{selectedResponsePack.attack_analysis.safest_response_angle || selectedResponsePack.recommended_posture}</p>
                  </article>
                  <article>
                    <span>History</span>
                    <strong>Current DB window</strong>
                    <p>{selectedResponsePack.attack_analysis.historical_context_note || "Historical backfill will strengthen this section."}</p>
                  </article>
                </div>
                {selectedResponsePack.attack_analysis.top_sources?.length ? (
                  <div className="tag-row">
                    {selectedResponsePack.attack_analysis.top_sources.map((source) => <Pill key={source}>{source}</Pill>)}
                  </div>
                ) : null}
              </div>

              <ResponsePacketSummary
                pack={selectedResponsePack}
                timeline={selectedTimeline?.watchlist_item.id === selectedResponsePack.watchlist_item.id ? selectedTimeline : undefined}
              />
              <AttackTimelineContext
                timeline={selectedTimeline?.watchlist_item.id === selectedResponsePack.watchlist_item.id ? selectedTimeline : undefined}
              />
              <ResponseDecisionGate pack={selectedResponsePack} />
              <ResponseStrategyPanel pack={selectedResponsePack} />
              <GroundingContractPanel contract={selectedResponsePack.grounding_contract} />

              <div className="drawer-section">
                <p className="eyebrow">Recommended Posture</p>
                <p>{selectedResponsePack.recommended_posture}</p>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Source-Backed Evidence</p>
                <div className="draft-list">
                  {selectedResponsePack.evidence_brief.length ? selectedResponsePack.evidence_brief.map((item) => (
                    <article className="draft-card" key={item.article_id}>
                      <div className="card-meta">
                        <Pill>{item.source_name}</Pill>
                        <Pill tone="gold">{dateLabel(item.published_at)}</Pill>
                      </div>
                      <a href={item.url} target="_blank" rel="noreferrer">{item.claim}</a>
                      <p className="muted">{item.use_in_briefing}</p>
                    </article>
                  )) : <div className="empty-state">No source-backed evidence found for this watchlist item.</div>}
                </div>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Citation Pack</p>
                <div className="draft-list">
                  {selectedResponsePack.citation_pack.length ? selectedResponsePack.citation_pack.map((item) => (
                    <article className="draft-card" key={item.label}>
                      <div className="card-meta">
                        <Pill tone="green">[{item.label}]</Pill>
                        {item.source_name ? <Pill>{item.source_name}</Pill> : null}
                        {item.published_at ? <Pill tone="gold">{dateLabel(item.published_at)}</Pill> : null}
                      </div>
                      {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.claim || item.inline}</a> : <strong>{item.claim || item.inline}</strong>}
                      <p className="muted">{item.safe_use}</p>
                    </article>
                  )) : <div className="empty-state">No citations because no source evidence was available.</div>}
                </div>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Claim Support Matrix</p>
                <div className="draft-list">
                  {selectedResponsePack.claim_support_matrix.length ? selectedResponsePack.claim_support_matrix.map((item) => (
                    <article className="draft-card" key={item.claim}>
                      <div className="card-meta">
                        <Pill tone={item.status === "source_supported" ? "green" : item.status === "single_source" ? "gold" : "coral"}>
                          {item.status.replaceAll("_", " ")}
                        </Pill>
                        <Pill>{item.supporting_source_count} sources</Pill>
                        <Pill>{item.supporting_article_count} articles</Pill>
                        {item.legal_review_required ? <Pill tone="coral">legal review</Pill> : null}
                      </div>
                      <strong>{item.claim}</strong>
                      <p>{item.safe_use}</p>
                    </article>
                  )) : <div className="empty-state">No claim support rows for this response pack.</div>}
                </div>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Claims To Verify Before Responding</p>
                <ul className="response-list">
                  {selectedResponsePack.claims_to_verify.map((claim) => (
                    <li key={claim}>{claim}</li>
                  ))}
                </ul>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Legal Review Flags</p>
                <ul className="response-list">
                  {selectedResponsePack.legal_review_flags.map((flag) => (
                    <li key={flag}>{flag}</li>
                  ))}
                </ul>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Legal Context To Verify</p>
                <div className="draft-list">
                  {selectedResponsePack.legal_context.length ? selectedResponsePack.legal_context.map((item) => (
                    <article className="draft-card" key={`${item.area}-${item.use_for}`}>
                      <div className="card-meta">
                        <Pill tone={item.status === "lawyer_verified" || item.status === "official" ? "green" : "gold"}>
                          {item.status.replaceAll("_", " ")}
                        </Pill>
                        {item.requires_lawyer_review ? <Pill tone="coral">lawyer review</Pill> : null}
                        {item.legal_basis_status ? <Pill>{item.legal_basis_status.replaceAll("_", " ")}</Pill> : null}
                      </div>
                      <strong>{item.area}</strong>
                      <p>{item.guidance}</p>
                      {item.safe_use ? <p className="muted">{item.safe_use}</p> : null}
                      {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.use_for}</a> : <p className="muted">{item.use_for}</p>}
                    </article>
                  )) : <div className="empty-state">No legal context matched this response pack.</div>}
                </div>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Evidence Steps</p>
                <ul className="response-list">
                  {selectedResponsePack.evidence_steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Draft Responses</p>
                <ResponseDraftVersionList
                  drafts={selectedResponsePack.draft_responses}
                  language={responseDraftLanguage}
                  onLanguageChange={setResponseDraftLanguage}
                  onStatusChange={updateResponseDraftStatus}
                  onCopy={(text) => copyTextToClipboard(text, setResponsePackReportStatus, "Draft copied.")}
                />
              </div>

              <SafetyNotice />

              <div className="drawer-section">
                <p className="eyebrow">Source Trail</p>
                <div className="article-list compact">
                  {selectedResponsePack.source_articles.map((article) => (
                    <ArticleCard article={article} key={article.id} onInspect={setSelectedArticle} />
                  ))}
                </div>
              </div>

              <p className="muted">{selectedResponsePack.disclaimer}</p>
            </aside>
          </div>
        ) : null}

        {selectedIncident ? (
          <div className="drawer-backdrop" onClick={() => setSelectedIncident(undefined)}>
            <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Case File</p>
                  <h3>{selectedIncident.title}</h3>
                </div>
                <button className="icon-button" onClick={() => setSelectedIncident(undefined)} aria-label="Close case">
                  X
                </button>
              </div>
              <div className="card-meta">
                <Pill tone={selectedIncident.severity === "critical" || selectedIncident.severity === "high" ? "coral" : "gold"}>
                  {selectedIncident.severity}
                </Pill>
                <Pill>{selectedIncident.status}</Pill>
                <Pill tone="gold">Created {dateLabel(selectedIncident.created_at)}</Pill>
                <button className="text-button icon-text" onClick={generateIncidentPdf}>
                  <FileText size={14} />
                  Generate PDF
                </button>
              </div>
              {incidentReportStatus ? <p className="muted">{incidentReportStatus}</p> : null}

              <div className="drawer-section">
                <p className="eyebrow">Workflow Status</p>
                <div className="status-row">
                  {["open", "monitoring", "responded", "legal_review", "closed"].map((status) => (
                    <button
                      className={`status-button ${selectedIncident.status === status ? "is-active" : ""}`}
                      key={status}
                      onClick={() => updateIncidentStatus(status)}
                    >
                      {status.replace("_", " ")}
                    </button>
                  ))}
                </div>
                {incidentUpdateStatus ? <p className="muted">{incidentUpdateStatus}</p> : null}
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Summary</p>
                <p>{selectedIncident.summary || "No summary saved."}</p>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Recommended Posture</p>
                <p>{selectedIncident.recommended_posture || "No recommendation saved."}</p>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Legal Review Flags</p>
                <ul className="response-list">
                  {selectedIncident.legal_review_flags.length ? (
                    selectedIncident.legal_review_flags.map((flag) => <li key={flag}>{flag}</li>)
                  ) : (
                    <li>No flags saved.</li>
                  )}
                </ul>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Evidence Steps</p>
                <ul className="response-list">
                  {selectedIncident.evidence_steps.length ? (
                    selectedIncident.evidence_steps.map((step) => <li key={step}>{step}</li>)
                  ) : (
                    <li>No evidence steps saved.</li>
                  )}
                </ul>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Evidence Trail</p>
                <div className="evidence-list">
                  {evidenceData.length ? (
                    evidenceData.map((item) => (
                      <article className="draft-card" key={item.id}>
                        <div className="card-meta">
                          <Pill tone="gold">{item.evidence_type}</Pill>
                          <Pill>{item.source_name || "source"}</Pill>
                          <Pill>{dateLabel(item.captured_at)}</Pill>
                        </div>
                        <a className="article-title" href={item.url} target="_blank" rel="noreferrer">
                          {item.title || item.url}
                        </a>
                        {item.notes ? <p>{item.notes}</p> : null}
                      </article>
                    ))
                  ) : (
                    <div className="empty-state">No evidence attached yet.</div>
                  )}
                </div>
                <form className="admin-form evidence-form" onSubmit={saveEvidence}>
                  <label>
                    Evidence URL
                    <input
                      value={evidenceForm.url}
                      onChange={(event) => setEvidenceForm({ ...evidenceForm, url: event.target.value })}
                      placeholder="https://..."
                      required
                    />
                  </label>
                  <div className="form-grid">
                    <label>
                      Title
                      <input
                        value={evidenceForm.title}
                        onChange={(event) => setEvidenceForm({ ...evidenceForm, title: event.target.value })}
                        placeholder="optional"
                      />
                    </label>
                    <label>
                      Source
                      <input
                        value={evidenceForm.source_name}
                        onChange={(event) => setEvidenceForm({ ...evidenceForm, source_name: event.target.value })}
                        placeholder="optional"
                      />
                    </label>
                  </div>
                  <label>
                    Notes
                    <input
                      value={evidenceForm.notes}
                      onChange={(event) => setEvidenceForm({ ...evidenceForm, notes: event.target.value })}
                      placeholder="what this proves"
                    />
                  </label>
                  <button className="primary-button" type="submit">Attach Evidence</button>
                  {evidenceStatus ? <p className="muted">{evidenceStatus}</p> : null}
                </form>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Saved Drafts</p>
                <ResponseDraftVersionList
                  drafts={selectedIncident.draft_responses}
                  language={responseDraftLanguage}
                  onLanguageChange={setResponseDraftLanguage}
                  onStatusChange={updateIncidentDraftStatus}
                  onCopy={(text) => copyTextToClipboard(text, setIncidentUpdateStatus, "Draft copied.")}
                />
              </div>
            </aside>
          </div>
        ) : null}

        {selectedTimeline ? (
          <div className="drawer-backdrop" onClick={() => setSelectedTimeline(undefined)}>
            <aside className="article-drawer" onClick={(event) => event.stopPropagation()}>
              <div className="panel-header">
                <div>
                  <p className="eyebrow">Attack Timeline</p>
                  <h3>{selectedTimeline.watchlist_item.label}</h3>
                </div>
                <button className="icon-button" onClick={() => setSelectedTimeline(undefined)} aria-label="Close timeline">
                  X
                </button>
              </div>
              <div className="card-meta">
                <Pill tone="gold">{selectedTimeline.event_count} events</Pill>
                <Pill>{selectedTimeline.period_days} days</Pill>
                <Pill>{selectedTimeline.source_count ?? selectedTimeline.amplifiers.length} sources</Pill>
                {selectedTimeline.spread_label ? <Pill tone="green">{selectedTimeline.spread_label.replaceAll("_", " ")}</Pill> : null}
              </div>
              {selectedTimeline.timeline_summary ? (
                <div className="drawer-section">
                  <p className="eyebrow">Timeline Summary</p>
                  <p>{selectedTimeline.timeline_summary}</p>
                  {selectedTimeline.recommended_urgency ? <p className="muted">{selectedTimeline.recommended_urgency}</p> : null}
                </div>
              ) : null}

              <div className="drawer-section">
                <p className="eyebrow">First Seen</p>
                {selectedTimeline.first_seen ? (
                  <a className="article-title" href={selectedTimeline.first_seen.url} target="_blank" rel="noreferrer">
                    {selectedTimeline.first_seen.source_name}: {selectedTimeline.first_seen.title}
                  </a>
                ) : (
                  <p>No events found.</p>
                )}
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Attack Categories</p>
                <div className="tag-row">
                  {Object.keys(selectedTimeline.attack_categories).length ? (
                    Object.entries(selectedTimeline.attack_categories).map(([category, count]) => (
                      <Pill key={category} tone="gold">{category.replaceAll("_", " ")} · {count}</Pill>
                    ))
                  ) : (
                    <span className="muted">No attack categories detected.</span>
                  )}
                </div>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Amplifiers</p>
                <div className="tag-row">
                  {selectedTimeline.amplifiers.map((source) => (
                    <Pill key={source.source_name}>{source.source_name} · {source.count}</Pill>
                  ))}
                </div>
              </div>

              <div className="drawer-section">
                <p className="eyebrow">Spread Events</p>
                <div className="timeline-list">
                  {selectedTimeline.events.map((event) => (
                    <article className="timeline-event" key={`${event.article_id}-${event.event_at}`}>
                      <div className="timeline-dot" />
                      <div>
                        <div className="card-meta">
                          <Pill>{dateLabel(event.event_at)}</Pill>
                          <Pill>{event.source_name}</Pill>
                          <Pill tone={event.attack_language ? "coral" : "default"}>
                            {event.attack_language ? "attack signal" : "mention"}
                          </Pill>
                        </div>
                        <a className="article-title" href={event.url} target="_blank" rel="noreferrer">
                          {event.title}
                        </a>
                        {event.attack_categories.length ? (
                          <div className="tag-row">
                            {event.attack_categories.map((category) => (
                              <Pill key={category} tone="gold">{category.replaceAll("_", " ")}</Pill>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        ) : null}
      </main>
    </div>
  );
}

