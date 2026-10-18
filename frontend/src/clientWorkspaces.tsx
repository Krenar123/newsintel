import type { ComponentType, ReactNode } from "react";
import type {
  Article,
  AttackDetail,
  Client,
  ClientChatResponse,
  ClientDashboard,
  ClientDailyBrief,
  Incident,
  SavedBriefing,
  SavedTopicWatch,
} from "./api";

export type ClientTab = "setup" | "briefs" | "risks" | "cases" | "reports";

export function clientMetricLabels(client?: Client, days = 30) {
  const labels: Record<string, Array<{ label: string; caption: string }>> = {
    political_figure: [
      { label: "Monitoring", caption: "people and topics" },
      { label: "Recent coverage", caption: "latest matched articles" },
      { label: "Open issues", caption: "watchlist items to review" },
      { label: "Evidence cases", caption: "saved incidents" },
    ],
    political_party: [
      { label: "Press scope", caption: "tracked issues" },
      { label: "Coverage", caption: `last ${days} days` },
      { label: "Opposition signals", caption: "needs review" },
      { label: "Briefing files", caption: "saved work" },
    ],
    pr_agency: [
      { label: "Client scope", caption: "tracked issues" },
      { label: "Coverage", caption: `last ${days} days` },
      { label: "Escalations", caption: "needs action" },
      { label: "Client cases", caption: "saved issues" },
    ],
    journalist: [
      { label: "Research scope", caption: "tracked leads" },
      { label: "Articles", caption: `last ${days} days` },
      { label: "Signals", caption: "worth checking" },
      { label: "Notebooks", caption: "saved research" },
    ],
    media_analyst: [
      { label: "Narratives", caption: "tracked themes" },
      { label: "Coverage", caption: `last ${days} days` },
      { label: "Movement", caption: "changing signals" },
      { label: "Analysis", caption: "saved work" },
    ],
    diaspora: [
      { label: "My interests", caption: "followed topics" },
      { label: "Stories", caption: `last ${days} days` },
      { label: "Important", caption: "developments" },
      { label: "Saved", caption: "read later" },
    ],
  };
  return labels[client?.client_type || ""] ?? [
    { label: "Watchlist", caption: "tracked interests" },
    { label: "Matches", caption: `last ${days} days` },
    { label: "Risk", caption: "actionable signals" },
    { label: "Cases", caption: "saved incidents" },
  ];
}

type PanelProps = {
  eyebrow?: string;
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
};

type PillProps = {
  children: ReactNode;
  tone?: string;
};

export type ClientWorkspaceComponents = {
  Panel: ComponentType<PanelProps>;
  Pill: ComponentType<PillProps>;
  ArticleCard: ComponentType<{ article: Article; onInspect?: (article: Article) => void }>;
  RiskCard: ComponentType<{
    item: ClientDashboard["risk_items"][number];
    onResponsePack?: (watchlistItemId: number) => void;
    onTimeline?: (watchlistItemId: number) => void;
    onSaveCase?: (watchlistItemId: number) => void;
    onCreateAlert?: (watchlistItemId: number) => void;
  }>;
  IncidentCard: ComponentType<{ incident: Incident; onOpen?: (incident: Incident) => void }>;
};

type DateLabel = (value?: string | null) => string;

type WorkspaceSharedProps = {
  components: ClientWorkspaceComponents;
  dateLabel: DateLabel;
};

export function clientTabItems(client?: Client, staffAccess = false): Array<{ id: ClientTab; label: string; detail: string }> {
  if (client?.client_type === "political_figure") {
    return [
      { id: "briefs", label: "Overview", detail: "What happened and what needs attention" },
      { id: "risks", label: "Attacks", detail: "Why they are being attacked" },
      { id: "reports", label: "Portals", detail: "Where the story is spreading" },
      { id: "cases", label: "Cases", detail: "Saved incidents and evidence" },
      ...(staffAccess ? [{ id: "setup" as ClientTab, label: "Setup", detail: "Watchlist and alerts" }] : []),
    ];
  }
  if (client?.client_type === "political_party") {
    return [
      ...(staffAccess ? [{ id: "setup" as ClientTab, label: "Setup", detail: "Configure party monitoring" }] : []),
      { id: "briefs", label: "War Room", detail: "Ask, brief, and prepare press conference material" },
      { id: "risks", label: "Opposition", detail: "Response and attack signals" },
      { id: "cases", label: "Cases", detail: "Saved incidents" },
      { id: "reports", label: "Archive", detail: "Saved chats, reports, and source trail" },
    ];
  }
  if (client?.client_type === "pr_agency") {
    return [
      ...(staffAccess ? [{ id: "setup" as ClientTab, label: "Setup", detail: "Configure agency clients" }] : []),
      { id: "briefs", label: "Client Desk", detail: "Ask about accounts, stories, and next actions" },
      { id: "risks", label: "Risks", detail: "Escalations and sensitive coverage" },
      { id: "cases", label: "Cases", detail: "Saved client issues" },
      { id: "reports", label: "Deliverables", detail: "Saved chats, briefs, and reports" },
    ];
  }
  if (client?.client_type === "journalist" || client?.client_type === "media_analyst") {
    return [
      ...(staffAccess ? [{ id: "setup" as ClientTab, label: "Setup", detail: "Configure research scope" }] : []),
      { id: "briefs", label: "Research", detail: "Ask questions and inspect source-backed answers" },
      { id: "risks", label: "Signals", detail: "Trends, risks, and narrative movement" },
      { id: "cases", label: "Notebooks", detail: "Saved research cases" },
      { id: "reports", label: "Source Trail", detail: "Portals, citations, and saved outputs" },
    ];
  }
  if (client?.client_type === "diaspora") {
    return [
      ...(staffAccess ? [{ id: "setup" as ClientTab, label: "Setup", detail: "Configure digest interests" }] : []),
      { id: "briefs", label: "Digest", detail: "Simple answers about what matters today" },
      { id: "risks", label: "Important", detail: "High-signal developments" },
      { id: "cases", label: "Saved", detail: "Saved topics and questions" },
      { id: "reports", label: "Sources", detail: "Where the news came from" },
    ];
  }
  return [
    ...(staffAccess ? [{ id: "setup" as ClientTab, label: "Setup", detail: "Configure this client" }] : []),
    { id: "briefs", label: "Briefs", detail: "Daily summary and saved topics" },
    { id: "risks", label: "Risks", detail: "Alerts and response items" },
    { id: "cases", label: "Cases", detail: "Saved incidents" },
    { id: "reports", label: "Reports", detail: "PDFs and subscriptions" },
  ];
}

function sourceBreakdownFromArticles(articles: Article[]) {
  const map = new Map<string, { name: string; count: number; latest?: string | null; samples: Article[] }>();
  for (const article of articles) {
    const name = article.source_name || article.platform_account_name || "Unknown";
    const current = map.get(name) ?? { name, count: 0, latest: null, samples: [] };
    const articleDate = article.published_at || article.fetched_at || article.ingested_at;
    current.count += 1;
    if (articleDate && (!current.latest || articleDate > current.latest)) current.latest = articleDate;
    if (current.samples.length < 3) current.samples.push(article);
    map.set(name, current);
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count || (b.latest || "").localeCompare(a.latest || ""));
}

function attackReasonSummary(item?: ClientDashboard["risk_items"][number]) {
  if (!item) return "No active attack pattern is visible in the current data window.";
  const categories = Object.entries(item.attack_categories || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([category, count]) => `${category.replaceAll("_", " ")} (${count})`);
  if (categories.length) {
    return `The current pattern is mainly about ${categories.join(", ")}. Treat this as a signal from article language, not a final legal conclusion.`;
  }
  if (item.negative_count) {
    return `${item.negative_count} matched items carry negative sentiment, but the exact attack theme needs source review.`;
  }
  return "The item is high-volume or widely spread, but no strong attack category is detected yet.";
}

const ATTACK_THEME_LABELS: Record<string, string> = {
  corruption: "allegations about corruption",
  crime_legal: "legal or criminal allegations",
  dishonesty: "claims about honesty or misleading statements",
  competence: "criticism of competence and performance",
  ethics_nepotism: "ethics, nepotism, or conflict-of-interest claims",
  abuse_of_power: "claims about abuse of office or authority",
  policy_failure: "criticism of policy decisions or results",
  conflict_of_interest: "claims about conflicts of interest",
  personal_attack: "personal criticism",
};

function attackThemes(item?: ClientDashboard["risk_items"][number]) {
  if (!item) return [];
  return Object.entries(item.attack_categories || {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 3)
    .map(([category]) => ATTACK_THEME_LABELS[category] || category.replaceAll("_", " "));
}

function attackExplanation(item?: ClientDashboard["risk_items"][number]) {
  if (!item) return "No active allegation is supported by the current source trail.";
  const themes = attackThemes(item);
  if (!themes.length) {
    return `${item.attack_count} report${item.attack_count === 1 ? "" : "s"} contain targeted negative language. Open the sources before deciding whether a response is needed.`;
  }
  return `The current criticism focuses on ${themes.join(", ")}. This is a media-language signal, not a verified finding or legal conclusion.`;
}

function uniqueAttackDetails(items: ClientDashboard["risk_items"]) {
  const details = new Map<number, AttackDetail>();
  for (const item of items) {
    for (const detail of item.attack_details || []) {
      if (!details.has(detail.article_id)) details.set(detail.article_id, detail);
    }
  }
  return Array.from(details.values()).sort((left, right) =>
    (right.published_at || "").localeCompare(left.published_at || ""),
  );
}

function sourceBreakdownFromAttacks(details: AttackDetail[]) {
  const map = new Map<string, { name: string; count: number; latest?: string | null; samples: AttackDetail[] }>();
  for (const detail of details) {
    const name = detail.reported_by || "Unknown";
    const current = map.get(name) ?? { name, count: 0, latest: null, samples: [] };
    current.count += 1;
    if (detail.published_at && (!current.latest || detail.published_at > current.latest)) current.latest = detail.published_at;
    if (current.samples.length < 3) current.samples.push(detail);
    map.set(name, current);
  }
  return Array.from(map.values()).sort((left, right) => right.count - left.count || (right.latest || "").localeCompare(left.latest || ""));
}

function prAgencyWorkflowStrategy(
  clientDash: ClientDashboard,
  topRisk: ClientDashboard["risk_items"][number] | undefined,
  sourceBreakdown: ReturnType<typeof sourceBreakdownFromArticles>,
) {
  const topSource = sourceBreakdown[0];
  const evidence = sourceBreakdown.flatMap((source) => source.samples.map((article) => ({
    source: source.name,
    title: article.title,
    url: article.url,
  }))).slice(0, 5);
  const publicPosture = topRisk?.severity === "critical" || topRisk?.severity === "high"
    ? "Client escalation update"
    : topRisk
      ? "Monitored client update"
      : "Routine reputation watch";
  const primaryLine = topRisk
    ? `${clientDash.client.name} should frame the update around ${topRisk.label}: ${topRisk.recommended_action}`
    : `${clientDash.client.name} has no urgent risk item in the current window; send a short monitoring update only if the client expects daily reporting.`;
  const publicationGate = topRisk?.attack_count
    ? "Do not send a strong rebuttal to the client until the response pack and original URLs are reviewed."
    : "Use this as a client update, not as public-facing copy.";

  return {
    publicPosture,
    primaryLine,
    messageAngle: topRisk ? attackReasonSummary(topRisk) : "Summarize source spread and keep the tone calm.",
    publicationGate,
    evidence,
    claimsToAvoid: [
      "Do not say an outlet attacked the client unless the source text clearly supports that wording.",
      "Do not imply legal wrongdoing, corruption, or criminality without official documents.",
      "Do not present single-source items as confirmed reputation damage.",
      "Do not send public response copy without checking dates, names, and URLs.",
    ],
    questions: [
      "Which portal or journalist matters most for this client?",
      "Is this single-source, multi-source, or broad spread?",
      "Does the client need a quiet monitoring note, direct outreach, or public response?",
      "Which cited article should the account manager attach?",
    ],
    notes: [
      `${clientDash.metrics.matched_articles} matched articles`,
      `${sourceBreakdown.length} sources`,
      topSource ? `Top source: ${topSource.name}` : "No source spread yet",
    ],
  };
}

function personaWorkflowPlan(
  clientDash: ClientDashboard,
  topRisk: ClientDashboard["risk_items"][number] | undefined,
  sourceBreakdown: ReturnType<typeof sourceBreakdownFromArticles>,
) {
  const type = clientDash.client.client_type || "client";
  const topSource = sourceBreakdown[0]?.name || "No source leader yet";
  const riskLabel = topRisk?.label || "No urgent risk";
  const riskAction = topRisk?.recommended_action || "Keep monitoring and ask NewsIntel when a new question appears.";
  const common = {
    metric: `${clientDash.metrics.matched_articles} matched articles`,
    source: `${sourceBreakdown.length} sources`,
    topSource,
  };

  const plans: Record<string, { title: string; cards: Array<{ label: string; title: string; detail: string }> }> = {
    political_party: {
      title: "Press conference flow",
      cards: [
        { label: "1", title: "Choose the issue", detail: "Start with a topic, opponent claim, or public question the party must answer." },
        { label: "2", title: "Check evidence", detail: `${common.metric}. Use citations and mark single-source or legal-review claims clearly.` },
        { label: "3", title: "Prepare response", detail: "Generate the briefing, review the press strategy, then export or save the final pack." },
      ],
    },
    pr_agency: {
      title: "Client reputation flow",
      cards: [
        { label: "1", title: "Find the client issue", detail: `${riskLabel}. Decide whether this is monitoring, escalation, or public response.` },
        { label: "2", title: "Attach evidence", detail: `${common.source}. Lead with ${common.topSource} only if the original article supports the client update.` },
        { label: "3", title: "Send safely", detail: riskAction },
      ],
    },
    journalist: {
      title: "Research flow",
      cards: [
        { label: "1", title: "Ask the question", detail: "Start with a person, institution, topic, date, or source you want to verify." },
        { label: "2", title: "Follow the trail", detail: `${common.source}. Check source spread before treating a story as established.` },
        { label: "3", title: "Save leads", detail: "Use citations, connected entities, and cases as a research notebook." },
      ],
    },
    media_analyst: {
      title: "Country signal flow",
      cards: [
        { label: "1", title: "Spot movement", detail: "Review narratives, risk items, and entity momentum before drawing conclusions." },
        { label: "2", title: "Check spread", detail: `${common.metric} across ${common.source}; separate broad spread from isolated reporting.` },
        { label: "3", title: "Explain change", detail: "Use chat to compare what changed since the previous period." },
      ],
    },
    diaspora: {
      title: "Simple digest flow",
      cards: [
        { label: "1", title: "Read the simple answer", detail: "Start with the assistant summary instead of opening every portal." },
        { label: "2", title: "See who matters", detail: "Check people, parties, institutions, and sources involved in the story." },
        { label: "3", title: "Open originals", detail: "Use source links when you want the full article or local context." },
      ],
    },
  };

  return plans[type] ?? {
    title: "Client intelligence flow",
    cards: [
      { label: "1", title: "Ask", detail: "Ask about latest mentions, risk, sources, or what changed." },
      { label: "2", title: "Verify", detail: "Use citations, dates, source spread, and legal warnings before acting." },
      { label: "3", title: "Save", detail: "Save important chats, cases, reports, and evidence for later." },
    ],
  };
}

function personaWorkspaceConfig(client?: Client) {
  const type = client?.client_type || "client";
  const configs: Record<string, {
    eyebrow: string;
    title: string;
    description: string;
    chatTitle: string;
    chatDescription: string;
    placeholder: string;
    prompts: string[];
    primaryMetric: string;
    actionLabel: string;
  }> = {
    political_party: {
      eyebrow: "Party War Room",
      title: "Prepare the next public move",
      description: "Ask about topics, opponents, source spread, and press-conference angles. Keep answers sourced before anyone speaks.",
      chatTitle: "Ask about the political situation",
      chatDescription: "Ask what happened, which portals carried it, what opponents are saying, or how to shape a press conference.",
      placeholder: "Example: Prepare a press conference angle on the latest opposition claims.",
      prompts: [
        "What should we know before a press conference?",
        "What are opponents saying about us?",
        "Which stories are spreading across portals?",
        "Give me sourced talking points.",
      ],
      primaryMetric: "Press prep",
      actionLabel: "Generate Brief",
    },
    pr_agency: {
      eyebrow: "PR Agency Desk",
      title: "Manage client reputation from one place",
      description: "Ask about client mentions, sensitive coverage, source spread, and what needs escalation today.",
      chatTitle: "Ask about clients and reputation",
      chatDescription: "Use the chat to understand client mentions, risks, and what to send as a client-ready update.",
      placeholder: "Example: Which client topic needs attention today?",
      prompts: [
        "Which client issue needs attention today?",
        "Who is mentioning our client the most?",
        "What should we include in a client update?",
        "Which stories are single-source risks?",
      ],
      primaryMetric: "Client issues",
      actionLabel: "Prepare Update",
    },
    journalist: {
      eyebrow: "Journalist Research Desk",
      title: "Find the story, source trail, and context",
      description: "Ask research questions and use citations, source spread, and entities as a reporting map.",
      chatTitle: "Ask a research question",
      chatDescription: "Ask about people, institutions, story spread, dates, source reliability, and connected entities.",
      placeholder: "Example: What sources reported this story and who is connected?",
      prompts: [
        "What are the strongest stories today?",
        "Which sources reported this?",
        "Who are the connected entities?",
        "What needs independent verification?",
      ],
      primaryMetric: "Research leads",
      actionLabel: "Open Research",
    },
    media_analyst: {
      eyebrow: "Media Analyst Console",
      title: "Understand what is moving in the country",
      description: "Ask about narratives, source behavior, entity momentum, and how coverage is changing.",
      chatTitle: "Ask about coverage movement",
      chatDescription: "Use the chat to compare narratives, sources, entities, and risks from the stored data.",
      placeholder: "Example: What narratives are growing and which sources are driving them?",
      prompts: [
        "What narratives are growing?",
        "Which portals are driving the story?",
        "Which entities are connected?",
        "What changed since the last period?",
      ],
      primaryMetric: "Signals",
      actionLabel: "Analyze",
    },
    diaspora: {
      eyebrow: "Diaspora Digest",
      title: "Simple Macedonia briefing",
      description: "Ask plain-language questions about the latest news, key people, and what matters without needing to read every portal.",
      chatTitle: "Ask for a simple explanation",
      chatDescription: "Ask what happened, why it matters, who is involved, and where to read the original coverage.",
      placeholder: "Example: Explain the most important Macedonia news today simply.",
      prompts: [
        "What is important today?",
        "Explain this in simple terms.",
        "Who is involved?",
        "Where can I read more?",
      ],
      primaryMetric: "Digest items",
      actionLabel: "Explain",
    },
  };
  return configs[type] ?? {
    eyebrow: "Client Intelligence Desk",
    title: "Ask about monitored coverage",
    description: "Use the assistant to search this client's permitted news data, citations, sources, and saved history.",
    chatTitle: "Ask NewsIntel",
    chatDescription: "Ask about latest mentions, sources, risks, summaries, and recommended next actions.",
    placeholder: "Example: What is the latest important coverage?",
    prompts: [
      "What is the latest important coverage?",
      "Who is mentioning this client?",
      "What needs attention?",
      "Summarize the source trail.",
    ],
    primaryMetric: "Matches",
    actionLabel: "Ask",
  };
}

function ClientChatPanel({
  components,
  title,
  description,
  placeholder,
  prompts,
  chatQuestion,
  chatAnswer,
  chatStatus,
  onChatQuestionChange,
  onAskChat,
  onNewChat,
}: {
  components: Pick<ClientWorkspaceComponents, "Panel" | "Pill">;
  title: string;
  description: string;
  placeholder: string;
  prompts: string[];
  chatQuestion: string;
  chatAnswer?: ClientChatResponse;
  chatStatus?: string;
  onChatQuestionChange: (question: string) => void;
  onAskChat: (question?: string) => void;
  onNewChat: () => void;
}) {
  const { Panel, Pill } = components;

  return (
    <Panel eyebrow="Ask NewsIntel" title={title} className="span-2 client-chat-panel">
      <div className="client-chat-layout">
        <div className="client-chat-input">
          <div className="client-chat-toolbar">
            <p>{description}</p>
            <button className="text-button" type="button" onClick={onNewChat}>New conversation</button>
          </div>
          <form
            className="client-chat-form"
            onSubmit={(event) => {
              event.preventDefault();
              onAskChat();
            }}
          >
            <textarea
              value={chatQuestion}
              onChange={(event) => onChatQuestionChange(event.target.value)}
              placeholder={placeholder}
              rows={3}
            />
            <button className="primary-button" type="submit">Ask</button>
          </form>
          <div className="tag-row">
            {prompts.map((prompt) => (
              <button className="text-button" type="button" key={prompt} onClick={() => onAskChat(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
          {chatStatus ? <p className="muted">{chatStatus}</p> : null}
        </div>
        <div className="client-chat-answer">
          {chatAnswer ? (
            <div className="stack">
              <div className="card-meta">
                <Pill tone={chatAnswer.confidence.level === "high" ? "green" : chatAnswer.confidence.level === "medium" ? "gold" : "coral"}>
                  {chatAnswer.confidence.level || "unknown"} confidence
                </Pill>
                <Pill>{chatAnswer.confidence.article_count ?? 0} articles</Pill>
                <Pill>{chatAnswer.confidence.source_count ?? 0} sources</Pill>
                <Pill>{chatAnswer.mode.replaceAll("_", " ")}</Pill>
                <Pill tone={chatAnswer.generation?.grounding_validated ? "green" : "gold"}>
                  {chatAnswer.generation?.grounding_validated ? "AI + citations checked" : "Local evidence answer"}
                </Pill>
              </div>
              <div className="client-chat-transcript" aria-label="Conversation history">
                {chatAnswer.history.slice(-8).map((message) => (
                  <div className={`client-chat-message is-${message.role}`} key={message.id}>
                    <span>{message.role === "user" ? "You" : "NewsIntel"}</span>
                    <p>{message.content}</p>
                  </div>
                ))}
              </div>
              <div className="client-chat-summary">
                {chatAnswer.summary.split("\n").slice(0, 4).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
              {chatAnswer.suggested_actions.length ? (
                <div className="tag-row">
                  {chatAnswer.suggested_actions.map((action) => <Pill tone="gold" key={action}>{action}</Pill>)}
                </div>
              ) : null}
              {chatAnswer.citations.length ? (
                <div className="mini-source-list">
                  {chatAnswer.citations.slice(0, 4).map((item) => (
                    <a className="article-title" href={item.url || undefined} target="_blank" rel="noreferrer" key={item.article_id}>
                      {item.source_name}: {item.claim}
                    </a>
                  ))}
                </div>
              ) : null}
              {chatAnswer.restrictions.length ? (
                <p className="muted">{chatAnswer.restrictions[0]}</p>
              ) : null}
            </div>
          ) : (
            <div className="empty-state">Ask a question to get a sourced answer from this client's saved news database.</div>
          )}
        </div>
      </div>
    </Panel>
  );
}

export function PoliticalFigureWorkspace({
  components,
  dateLabel,
  clientDash,
  selectedTab,
  incidents,
  status,
  onResponsePack,
  onTimeline,
  onSaveCase,
  onCreateAlert,
  onInspectArticle,
  chatQuestion,
  chatAnswer,
  chatStatus,
  onChatQuestionChange,
  onAskChat,
  onNewChat,
}: WorkspaceSharedProps & {
  clientDash?: ClientDashboard;
  selectedTab: ClientTab;
  incidents: Incident[];
  status?: string;
  onResponsePack: (watchlistItemId: number) => void;
  onTimeline: (watchlistItemId: number) => void;
  onSaveCase: (watchlistItemId: number) => void;
  onCreateAlert: (watchlistItemId: number) => void;
  onInspectArticle: (article: Article) => void;
  chatQuestion: string;
  chatAnswer?: ClientChatResponse;
  chatStatus?: string;
  onChatQuestionChange: (question: string) => void;
  onAskChat: (question?: string) => void;
  onNewChat: () => void;
}) {
  const { Panel, Pill, ArticleCard, IncidentCard } = components;

  if (!clientDash) {
    return (
      <Panel eyebrow="Political Figure" title="Select a Figure" className="span-2">
        <div className="empty-state">Choose a political figure client to open their personal monitoring desk.</div>
      </Panel>
    );
  }

  const targetName = clientDash.client.name.replace(/Defense Desk|Demo/gi, "").replace(/\s+/g, " ").trim() || clientDash.client.name;
  const targetRisk = clientDash.risk_items.find((item) => item.item_type === "entity" && item.attack_count > 0)
    || clientDash.risk_items.find((item) => item.attack_count > 0)
    || clientDash.risk_items[0];
  const attackItems = clientDash.risk_items.filter((item) => item.attack_count > 0);
  const allAttackDetails = uniqueAttackDetails(attackItems);
  const targetAttackDetails = targetRisk?.attack_details || [];
  const attackSources = sourceBreakdownFromAttacks(allAttackDetails);
  const primaryAttack = targetAttackDetails[0];
  const seriousRisk = targetRisk?.severity === "critical" || targetRisk?.severity === "high";
  const recentMentions = clientDash.recent_articles.slice(0, 4);
  const attackerLabel = primaryAttack?.attacker || "Attacker not confidently identified";
  const targetLabel = primaryAttack?.target || targetRisk?.label || targetName;

  return (
    <div className="figure-dashboard-shell">
      <section className="figure-profile-header" aria-label="Political figure workspace">
        <div>
          <p className="eyebrow">Private intelligence desk</p>
          <h3>{targetName}</h3>
          <p>Mentions, allegations, source spread, response preparation, and saved evidence.</p>
        </div>
        <div className="figure-profile-status">
          <span>Selected window</span>
          <strong className={seriousRisk ? "is-urgent" : "is-stable"}>
            {seriousRisk ? "Review recommended" : "No urgent response"}
          </strong>
        </div>
      </section>

      {selectedTab === "briefs" ? <>
        <Panel
          eyebrow="Current evidence"
          title="What needs your attention"
          className="figure-focus-panel"
          action={<Pill tone={seriousRisk ? "coral" : "green"}>{targetRisk ? targetRisk.severity : "stable"}</Pill>}
        >
          {targetRisk && targetRisk.attack_count > 0 ? (
            <div className="figure-incident-card">
              <div className="figure-incident-heading">
                <div>
                  <span>Who is criticizing you?</span>
                  <strong>{attackerLabel}</strong>
                </div>
                <div className="figure-incident-count">
                  <strong>{targetRisk.attack_count}</strong>
                  <span>flagged reports</span>
                </div>
              </div>
              <div className="figure-fact-grid">
                <div>
                  <span>Target</span>
                  <strong>{targetLabel}</strong>
                </div>
                <div>
                  <span>Why?</span>
                  <strong>{attackThemes(targetRisk)[0] || "Targeted negative coverage"}</strong>
                </div>
                <div>
                  <span>Confirmed portals</span>
                  <strong>{new Set(targetAttackDetails.map((detail) => detail.reported_by)).size}</strong>
                </div>
                <div>
                  <span>Latest report</span>
                  <strong>{dateLabel(primaryAttack?.published_at || targetRisk.latest_at)}</strong>
                </div>
              </div>
              <p className="figure-plain-summary">{attackExplanation(targetRisk)}</p>
              <div className="figure-action-row">
                <button className="primary-button" type="button" onClick={() => onResponsePack(targetRisk.watchlist_item_id)}>
                  Prepare sourced response
                </button>
                <button className="secondary-button" type="button" onClick={() => onTimeline(targetRisk.watchlist_item_id)}>
                  Open timeline
                </button>
                <button className="secondary-button" type="button" onClick={() => onSaveCase(targetRisk.watchlist_item_id)}>
                  Save evidence case
                </button>
              </div>
            </div>
          ) : (
            <div className="figure-clear-state">
              <strong>No supported attack pattern is active.</strong>
              <p>Recent mentions remain available below. A public response is not recommended without a specific sourced allegation.</p>
            </div>
          )}
        </Panel>

        <Panel eyebrow="Attack Evidence" title="Reports tied to this allegation">
          <div className="figure-evidence-list">
            {targetAttackDetails.length ? targetAttackDetails.slice(0, 5).map((detail) => (
              <article className="figure-evidence-row" key={detail.article_id}>
                <div className="figure-evidence-meta">
                  <Pill>{detail.reported_by}</Pill>
                  <span>{dateLabel(detail.published_at)}</span>
                  <span>{detail.confidence_label} confidence</span>
                </div>
                <strong>{detail.title}</strong>
                <p>{detail.attacker ? `${detail.attacker} is identified as the speaker or critic.` : "The critic could not be identified confidently from the stored text."}</p>
                <details>
                  <summary>Show original-language allegation</summary>
                  <p>{detail.allegation || detail.quote || "No exact allegation extract was preserved."}</p>
                </details>
                <a href={detail.url} target="_blank" rel="noreferrer">Open original article</a>
              </article>
            )) : <div className="empty-state">No article is confidently tied to an attack. Recent mentions are not presented as attack evidence.</div>}
          </div>
        </Panel>

        <details className="figure-chat-disclosure">
          <summary>
            <span>Ask NewsIntel</span>
            <strong>Search your private coverage and prepare a cited answer</strong>
          </summary>
          <ClientChatPanel
            components={{ Panel, Pill }}
            title="Ask anything about your coverage"
            description="Ask about latest mentions, who is mentioning you, why an attack is spreading, or how to prepare a sourced response."
            placeholder="Example: Who criticized me in this period and what evidence do we have?"
            prompts={[
              "What is the latest about me?",
              "Who is mentioning me the most?",
              "Why am I being attacked?",
              "Help me prepare a response.",
            ]}
            chatQuestion={chatQuestion}
            chatAnswer={chatAnswer}
            chatStatus={chatStatus}
            onChatQuestionChange={onChatQuestionChange}
            onAskChat={onAskChat}
            onNewChat={onNewChat}
          />
        </details>
      </> : null}

      {selectedTab === "briefs" ? (
        <Panel eyebrow="Recent Mentions" title="Latest coverage about you">
          <p className="panel-intro">These are recent mentions. They are not automatically classified as attacks.</p>
          <div className="article-list compact figure-article-list">
            {recentMentions.length ? recentMentions.map((article) => (
              <ArticleCard article={article} key={article.id} onInspect={onInspectArticle} />
            )) : <div className="empty-state">No matched articles in this period.</div>}
          </div>
        </Panel>
      ) : null}

      {selectedTab === "risks" ? (
        <Panel eyebrow="Attack Analysis" title="Why you are being attacked">
          <p className="panel-intro">Each item below separates the detected theme from the original wording and source trail.</p>
          <div className="figure-risk-list">
            {attackItems.length ? attackItems.map((item) => (
              <article className="figure-attack-card" key={item.watchlist_item_id}>
                <div>
                  <div className="card-meta">
                    <Pill tone={item.severity === "critical" || item.severity === "high" ? "coral" : "gold"}>{item.severity}</Pill>
                    <Pill>{item.article_count} mentions reviewed</Pill>
                    <Pill>{item.source_count} mention sources</Pill>
                    <Pill tone="coral">{item.attack_count} sourced attacks</Pill>
                  </div>
                  <h3>{item.label}</h3>
                  <p>{attackExplanation(item)}</p>
                  <p className="muted">{item.recommended_action}</p>
                  {item.attack_details?.length ? (
                    <details className="attack-evidence-disclosure">
                      <summary>Open cited allegations ({item.attack_details.length})</summary>
                      <div className="attack-evidence-body">
                        {item.attack_details.slice(0, 5).map((detail) => (
                          <article className="attack-source-item" key={detail.article_id}>
                            <strong>{detail.attacker || "Attacker not identified"} {" → "} {detail.target || item.label}</strong>
                            <p>{detail.allegation || "No exact allegation extract was preserved."}</p>
                            <div className="card-meta">
                              <Pill>{detail.reported_by}</Pill>
                              <Pill>{detail.confidence_label} confidence</Pill>
                              <span>{dateLabel(detail.published_at)}</span>
                            </div>
                            <a href={detail.url} target="_blank" rel="noreferrer">Open original report</a>
                          </article>
                        ))}
                      </div>
                    </details>
                  ) : null}
                  {item.attack_categories && Object.keys(item.attack_categories).length ? (
                    <div className="tag-row">
                      {Object.entries(item.attack_categories).map(([category, count]) => (
                        <Pill key={category} tone="gold">{category.replaceAll("_", " ")}: {count}</Pill>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="figure-action-row vertical">
                  <button className="primary-button" type="button" onClick={() => onResponsePack(item.watchlist_item_id)}>
                    Prepare Response
                  </button>
                  <button className="text-button" type="button" onClick={() => onTimeline(item.watchlist_item_id)}>
                    Timeline
                  </button>
                  <button className="text-button" type="button" onClick={() => onCreateAlert(item.watchlist_item_id)}>
                    Alert Me
                  </button>
                  <button className="text-button" type="button" onClick={() => onSaveCase(item.watchlist_item_id)}>
                    Save Case
                  </button>
                </div>
              </article>
            )) : <div className="empty-state">No sourced attack reports in the selected window.</div>}
            {status ? <div className="empty-state">{status}</div> : null}
          </div>
        </Panel>
      ) : null}

      {selectedTab === "reports" ? (
        <Panel eyebrow="Portal Spread" title="Attack coverage by portal">
          <p className="panel-intro">Only portals carrying a report classified as a targeted attack appear here. Ordinary mentions are excluded.</p>
          <div className="portal-grid">
            {attackSources.length ? attackSources.map((source) => (
              <article className="portal-card" key={source.name}>
                <div>
                  <span>{source.name}</span>
                  <strong>{source.count}</strong>
                  <p>flagged report{source.count === 1 ? "" : "s"}<br />Latest: {dateLabel(source.latest)}</p>
                </div>
                <div className="mini-source-list">
                  {source.samples.map((detail) => (
                    <a className="portal-source-link" href={detail.url} target="_blank" rel="noreferrer" key={detail.article_id}>
                      {detail.title}
                    </a>
                  ))}
                </div>
              </article>
            )) : <div className="empty-state">No attack-specific portal spread is supported by the current evidence.</div>}
          </div>
        </Panel>
      ) : null}

      {selectedTab === "cases" ? (
        <Panel eyebrow="Case Files" title="Saved attacks and response history">
          <div className="alert-list">
            {incidents.length ? incidents.map((incident) => (
              <IncidentCard incident={incident} key={incident.id} />
            )) : <div className="empty-state">No saved case files yet. Save important attack items from the Attacks tab.</div>}
          </div>
        </Panel>
      ) : null}

      {selectedTab === "setup" ? (
        <Panel eyebrow="Watchlist" title="What this desk tracks">
          <div className="tag-row">
            {clientDash.watchlist.map((item) => (
              <button className="text-button" key={item.id} type="button" onClick={() => onCreateAlert(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

export function ClientPersonaWorkspace({
  components,
  dateLabel,
  clientDash,
  selectedTab,
  incidents,
  savedBriefings,
  savedTopics,
  dailyBrief,
  status,
  chatQuestion,
  chatAnswer,
  chatStatus,
  onChatQuestionChange,
  onAskChat,
  onNewChat,
  onSelectTab,
  onResponsePack,
  onTimeline,
  onSaveCase,
  onCreateAlert,
  onInspectArticle,
  onDemoBriefing,
}: WorkspaceSharedProps & {
  clientDash?: ClientDashboard;
  selectedTab: ClientTab;
  incidents: Incident[];
  savedBriefings: SavedBriefing[];
  savedTopics: SavedTopicWatch[];
  dailyBrief?: ClientDailyBrief;
  status?: string;
  chatQuestion: string;
  chatAnswer?: ClientChatResponse;
  chatStatus?: string;
  onChatQuestionChange: (question: string) => void;
  onAskChat: (question?: string) => void;
  onNewChat: () => void;
  onSelectTab: (tab: ClientTab) => void;
  onResponsePack: (watchlistItemId: number) => void;
  onTimeline: (watchlistItemId: number) => void;
  onSaveCase: (watchlistItemId: number) => void;
  onCreateAlert: (watchlistItemId: number) => void;
  onInspectArticle: (article: Article) => void;
  onDemoBriefing: (topic: string, objective: string, requirements: string) => void;
}) {
  const { Panel, Pill, RiskCard, IncidentCard } = components;

  if (!clientDash) {
    return (
      <Panel eyebrow="Client Workspace" title="Select a Client" className="span-2">
        <div className="empty-state">Choose a client to open their assistant workspace.</div>
      </Panel>
    );
  }

  const config = personaWorkspaceConfig(clientDash.client);
  const topRisk = clientDash.risk_items[0];
  const sourceBreakdown = sourceBreakdownFromArticles(clientDash.recent_articles);
  const latestArticles = clientDash.recent_articles.slice(0, 6);
  const chatHistory = savedBriefings.filter((item) => item.briefing_type === "client_chat").slice(0, 6);
  const seriousRisk = topRisk?.severity === "critical" || topRisk?.severity === "high";
  const prStrategy = clientDash.client.client_type === "pr_agency"
    ? prAgencyWorkflowStrategy(clientDash, topRisk, sourceBreakdown)
    : null;
  const workflowPlan = personaWorkflowPlan(clientDash, topRisk, sourceBreakdown);
  const workflowActions = [
    () => onAskChat(config.prompts[0]),
    () => onSelectTab("reports"),
    () => onSelectTab(
      clientDash.client.client_type === "diaspora" || clientDash.client.client_type === "journalist"
        ? "cases"
        : "risks",
    ),
  ];

  return (
    <div className="persona-workspace-shell span-2">
      {selectedTab === "briefs" ? <>
        <Panel
        eyebrow={config.eyebrow}
        title={config.title}
        className="persona-focus-panel"
        action={<Pill tone={seriousRisk ? "coral" : "green"}>{topRisk ? topRisk.severity : "stable"}</Pill>}
      >
        <div className="persona-focus-grid">
          <article className="persona-main-card">
            <span>Today's job</span>
            <strong>{config.description}</strong>
            <p>
              This workspace is scoped to {clientDash.client.name}. It uses stored articles, summaries,
              entities, watchlist matches, citations, and saved chat history.
            </p>
          </article>
          <article className="persona-metric-card">
            <span>{config.primaryMetric}</span>
            <strong>{clientDash.metrics.matched_articles}</strong>
            <p>{clientDash.watchlist.length} tracked interests, {sourceBreakdown.length} sources, {incidents.length} saved cases.</p>
          </article>
          <article className="persona-metric-card">
            <span>Priority</span>
            <strong>{topRisk?.label || "No urgent item"}</strong>
            <p>{topRisk?.recommended_action || "Keep monitoring latest coverage and source spread."}</p>
          </article>
        </div>
        </Panel>

        <ClientChatPanel
          components={{ Panel, Pill }}
          title={config.chatTitle}
          description={config.chatDescription}
          placeholder={config.placeholder}
          prompts={config.prompts}
          chatQuestion={chatQuestion}
          chatAnswer={chatAnswer}
          chatStatus={chatStatus}
          onChatQuestionChange={onChatQuestionChange}
          onAskChat={onAskChat}
          onNewChat={onNewChat}
        />
      </> : null}

      {selectedTab === "briefs" ? (
        <>
          <Panel eyebrow="Workflow" title={workflowPlan.title} className="span-2">
            <div className="persona-action-grid">
              {workflowPlan.cards.map((card, index) => (
                <button
                  className="persona-action-card"
                  type="button"
                  onClick={workflowActions[index]}
                  key={`${workflowPlan.title}-${card.label}`}
                >
                  <Pill tone="green">{card.label}</Pill>
                  <strong>{card.title}</strong>
                  <span>{card.detail}</span>
                  <span className="persona-action-link">
                    {index === 0 ? config.actionLabel : index === 1 ? "Open source trail" : "Open workspace"}
                  </span>
                </button>
              ))}
            </div>
          </Panel>

          {clientDash.client.client_type === "political_party" ? (
            <Panel eyebrow="Press Conference Prep" title="Fast party briefing starters" className="span-2">
              <div className="persona-action-grid">
                <button className="persona-action-card" type="button" onClick={() => onDemoBriefing("EU path and constitutional changes", "Prepare a sourced party position on the EU path", "Use stored sources only; mark legal and constitutional claims for review")}>
                  <strong>EU path brief</strong>
                  <span>Generate sourced talking points and verification warnings.</span>
                </button>
                <button className="persona-action-card" type="button" onClick={() => onDemoBriefing("Judiciary and corruption", "Prepare a rule-of-law press conference frame", "Separate allegations from official proceedings and avoid unsupported accusations")}>
                  <strong>Rule-of-law brief</strong>
                  <span>Prepare careful language around allegations and institutions.</span>
                </button>
                <button className="persona-action-card" type="button" onClick={() => onDemoBriefing("Economy and living costs", "Prepare a public-facing message on economic pressure", "Use dates, sources, and avoid claims beyond stored evidence")}>
                  <strong>Economy brief</strong>
                  <span>Build a simple public-facing frame from stored coverage.</span>
                </button>
              </div>
            </Panel>
          ) : null}

          {prStrategy ? (
            <Panel
              eyebrow="Client Response Strategy"
              title={prStrategy.publicPosture}
              className="span-2 response-strategy-panel"
              action={<Pill tone={seriousRisk ? "coral" : topRisk ? "gold" : "green"}>{topRisk?.severity || "stable"}</Pill>}
            >
              <div className="response-summary-grid">
                <article>
                  <span>Primary client line</span>
                  <strong>{prStrategy.primaryLine}</strong>
                  <p>{prStrategy.messageAngle}</p>
                </article>
                <article>
                  <span>Send gate</span>
                  <strong>{prStrategy.publicationGate}</strong>
                  <p>Use this as an account-manager update. Open a response pack before drafting public copy.</p>
                </article>
              </div>
              {prStrategy.evidence.length ? (
                <div className="strategy-block">
                  <strong>Evidence to attach</strong>
                  <div className="mini-source-list">
                    {prStrategy.evidence.map((item) => (
                      <a href={item.url} target="_blank" rel="noreferrer" key={`${item.source}-${item.title}`}>
                        {item.source}: {item.title}
                      </a>
                    ))}
                  </div>
                </div>
              ) : null}
              <div className="persona-two-column">
                <div className="strategy-block">
                  <strong>Do not overclaim</strong>
                  <ul className="response-list">
                    {prStrategy.claimsToAvoid.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div className="strategy-block">
                  <strong>Before sending</strong>
                  <ul className="response-list">
                    {prStrategy.questions.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              </div>
              <div className="tag-row">
                {prStrategy.notes.map((item) => <Pill tone="gold" key={item}>{item}</Pill>)}
              </div>
            </Panel>
          ) : null}

          <Panel eyebrow="Latest Coverage" title={dailyBrief?.headline || "What changed recently"} className="span-2">
            <div className="persona-two-column">
              <div className="stack">
                <p>{dailyBrief?.summary || "Ask the assistant or review the latest matched articles for this client."}</p>
                <div className="tag-row">
                  {(dailyBrief?.recommended_actions ?? ["Ask a question to create a sourced client update."]).slice(0, 4).map((action) => (
                    <Pill tone="gold" key={action}>{action}</Pill>
                  ))}
                </div>
              </div>
              <div className="mini-source-list">
                {latestArticles.length ? latestArticles.slice(0, 4).map((article) => (
                  <button className="text-button subtle-link" type="button" key={article.id} onClick={() => onInspectArticle(article)}>
                    {article.source_name}: {article.title}
                  </button>
                )) : <div className="empty-state">No matched articles yet.</div>}
              </div>
            </div>
          </Panel>
        </>
      ) : null}

      {selectedTab === "risks" ? (
        <Panel eyebrow="Signals" title="Items needing attention" className="span-2">
          <div className="figure-risk-list">
            {clientDash.risk_items.length ? clientDash.risk_items.map((item) => (
              <RiskCard
                item={item}
                key={item.watchlist_item_id}
                onResponsePack={onResponsePack}
                onTimeline={onTimeline}
                onSaveCase={onSaveCase}
                onCreateAlert={onCreateAlert}
              />
            )) : <div className="empty-state">No risk signals in this period.</div>}
            {status ? <div className="empty-state">{status}</div> : null}
          </div>
        </Panel>
      ) : null}

      {selectedTab === "reports" ? (
        <>
          <Panel eyebrow="Source Trail" title="Where this client appears" className="span-2">
            <div className="portal-grid">
              {sourceBreakdown.length ? sourceBreakdown.map((source) => (
                <article className="portal-card" key={source.name}>
                  <div>
                    <span>{source.name}</span>
                    <strong>{source.count}</strong>
                    <p>Latest: {dateLabel(source.latest)}</p>
                  </div>
                  <div className="mini-source-list">
                    {source.samples.map((article) => (
                      <button className="text-button subtle-link" type="button" key={article.id} onClick={() => onInspectArticle(article)}>
                        {article.title}
                      </button>
                    ))}
                  </div>
                </article>
              )) : <div className="empty-state">No source spread yet.</div>}
            </div>
          </Panel>
          <Panel eyebrow="Saved Outputs" title="Chat history and saved work" className="span-2">
            <div className="source-list">
              {chatHistory.length ? chatHistory.map((item) => (
                <article className="source-card" key={item.id}>
                  <div className="source-main">
                    <div>
                      <div className="card-meta">
                        <Pill>{item.briefing_type.replaceAll("_", " ")}</Pill>
                        <Pill tone="gold">{dateLabel(item.created_at)}</Pill>
                      </div>
                      <strong>{item.title}</strong>
                      <p>{String(item.payload?.answer || item.notes || "").slice(0, 220)}</p>
                    </div>
                    <strong>#{item.id}</strong>
                  </div>
                </article>
              )) : <div className="empty-state">No saved chat answers yet. Ask a question to create the first one.</div>}
            </div>
          </Panel>
        </>
      ) : null}

      {selectedTab === "cases" ? (
        <Panel eyebrow="Saved Work" title="Cases and watched topics" className="span-2">
          <div className="persona-two-column">
            <div className="alert-list">
              {incidents.length ? incidents.map((incident) => (
                <IncidentCard incident={incident} key={incident.id} />
              )) : <div className="empty-state">No saved case files yet.</div>}
            </div>
            <div className="source-list">
              {savedTopics.length ? savedTopics.slice(0, 6).map((topic) => (
                <article className="source-card" key={topic.watchlist_item.id}>
                  <div className="source-main">
                    <div>
                      <div className="card-meta">
                        <Pill>{topic.article_count} articles</Pill>
                        <Pill>{topic.source_count} sources</Pill>
                      </div>
                      <strong>{topic.watchlist_item.label}</strong>
                      <p>{topic.recommended_action}</p>
                    </div>
                  </div>
                </article>
              )) : <div className="empty-state">No saved topic watches yet.</div>}
            </div>
          </div>
        </Panel>
      ) : null}

      {selectedTab === "setup" ? (
        <Panel eyebrow="Watchlist" title="What this workspace can see" className="span-2">
          <div className="tag-row">
            {clientDash.watchlist.map((item) => (
              <button className="text-button" key={item.id} type="button" onClick={() => onCreateAlert(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}


