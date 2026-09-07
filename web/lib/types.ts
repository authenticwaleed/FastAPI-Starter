/**
 * Shapes the API returns.
 *
 * Hand-written and deliberately few. Decision 5.5 of the plan is that these
 * come from the committed schema by way of `openapi-typescript`, and the
 * generator lands with the phase that first needs a shape too large to be
 * worth typing out. Until then, one small file that says what these
 * endpoints answer with beats a generated union nothing yet reads.
 */

/** Everything paged answers with this envelope. */
export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

/** `GET /auth/me`, and what `/account` returns. */
export type User = {
  id: number;
  name: string;
  email: string;
  is_active: boolean;
  /**
   * Null until somebody follows the link sent to this address, and null
   * again when the address changes. Nothing in the API is gated on it, so
   * this client nudges rather than locks.
   */
  email_verified_at: string | null;
  created_at: string;
  updated_at: string;
};

/**
 * One sign-in, as the person who owns the account sees it.
 *
 * No token and no hash — the whole point of the list is that it can be
 * shown to somebody.
 */
export type Session = {
  id: string;
  created_at: string;
  /** Moves when the session refreshes, not on every request. */
  last_used_at: string;
  expires_at: string;
  /** Both best effort, and both to be recognised rather than trusted. */
  user_agent: string | null;
  ip_address: string | null;
  /** The session this request arrived on. Think twice before ending it. */
  current: boolean;
};

export type WorkspaceStatus = "active" | "suspended" | "cancelled";

export type Workspace = {
  id: string;
  name: string;
  slug: string;
  status: WorkspaceStatus;
  timezone: string;
  default_currency: string;
  created_at: string;
  updated_at: string;
};

/**
 * The four tenant roles, in descending order of what they may do.
 *
 * They fan out rather than nest: an admin manages people, an agent handles
 * customers, and neither contains the other. Anything deciding what to show
 * says which roles it means, never "at least".
 */
export type WorkspaceRole = "owner" | "admin" | "agent" | "viewer";

export type MembershipStatus = "active" | "invited" | "removed";

export type Member = {
  user_id: number;
  name: string;
  email: string;
  role: WorkspaceRole;
  status: MembershipStatus;
  joined_at: string;
};

export type Notification = {
  id: string;
  kind: string;
  /** Always present: a person in three businesses needs to know which. */
  workspace_id: string;
  title: string;
  body: string | null;
  /** Ids to link on — a conversation, a document. Not what it says. */
  metadata: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
};

/** `GET /notifications/unread-count`. Its own endpoint, because a badge polls. */
export type UnreadCount = { unread: number };

/** `POST /notifications/read-all`. Zero is visibly different from forty. */
export type MarkedRead = { marked_read: number };

// --- the inbox (W3) --------------------------------------------------

export type ContactStatus = "lead" | "customer" | "blocked";

export type Contact = {
  id: string;
  phone_number: string;
  name: string | null;
  email: string | null;
  status: ContactStatus;
  source: string | null;
  external_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

/** A name, a number and a badge — not the profile, which has its own page. */
export type ContactSummary = {
  id: string;
  name: string | null;
  phone_number: string;
  status: ContactStatus;
};

export type AssigneeSummary = { id: number; name: string; email: string };

export type ConversationStatus = "open" | "pending" | "closed";

/** How much the assistant may do here. `suggest_only` is where pilots start. */
export type AiMode = "disabled" | "suggest_only" | "automatic";

/**
 * Who is answering, as one value.
 *
 * Derived by the API from `ai_mode` and the handoff together, so a screen
 * renders this rather than reimplementing the rule that produces it.
 */
export type ConversationState =
  | "ai_active"
  | "suggest_only"
  | "human_active"
  | "ai_disabled";

export type SenderType = "customer" | "agent" | "ai" | "system";
export type Direction = "inbound" | "outbound";
export type MessageStatus =
  | "queued"
  | "sent"
  | "delivered"
  | "read"
  | "failed"
  | "received";

/** The last line of a thread, as an inbox row shows it. Text is truncated. */
export type MessagePreview = {
  text: string | null;
  sender_type: SenderType;
  direction: Direction;
  status: MessageStatus;
  created_at: string;
};

export type Conversation = {
  id: string;
  contact: ContactSummary;
  channel: string;
  status: ConversationStatus;
  assigned_user: AssigneeSummary | null;
  ai_mode: AiMode;
  state: ConversationState;
  handoff_at: string | null;
  handoff_reason: string | null;
  /** Set with `handoff_at` and null here means the assistant handed over. */
  handoff_by_user_id: number | null;
  last_message: MessagePreview | null;
  last_message_at: string | null;
  unread_count: number;
  last_read_at: string | null;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  conversation_id: string;
  sender_type: SenderType;
  direction: Direction;
  channel: string;
  content_type: string;
  text: string | null;
  status: MessageStatus;
  sent_at: string | null;
  received_at: string | null;
  created_at: string;
};

export type ConversationEvent = {
  id: string;
  event_type: string;
  /** Null means the assistant did it: the only actor here that is not a person. */
  actor_user_id: number | null;
  reason: string | null;
  created_at: string;
};

/**
 * What the pipeline did about one customer message.
 *
 * Branch on this, never on `text`: a reply with no text is the ordinary
 * shape of a handoff, and a client that checks the text first reads "a
 * person should take this" as an empty answer.
 */
export type AiDecision = "answered" | "suggested" | "handoff" | "blocked";

export type AiReply = {
  decision: AiDecision;
  text: string | null;
  confidence: number | null;
  /** `no_knowledge`, `low_confidence`, `cannot_answer`, `plan_limit`, … */
  reason: string | null;
  sources: string[];
  /** Present when the decision was `answered` and the reply went out. */
  message_id: string | null;
};

export type AiResponseLog = {
  id: string;
  message_id: string | null;
  decision: AiDecision;
  reply_text: string | null;
  sent_message_id: string | null;
  reason: string | null;
  model: string | null;
  prompt_version: string;
  confidence: number | null;
  retrieved_chunk_ids: string[];
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
};

// --- the team (W4) ---------------------------------------------------

/** Derived from two timestamps and the clock, never stored. */
export type InvitationStatus = "pending" | "accepted" | "expired";

export type Invitation = {
  id: string;
  email: string;
  role: WorkspaceRole;
  status: InvitationStatus;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
};

/**
 * What creating an invitation returns, once.
 *
 * The token is here and in no later response: what the API stores is a
 * digest, so it cannot be produced again. This is the only chance to put
 * it in a link, which is why the screen that creates one has to show it.
 */
export type InvitationCreated = Invitation & { token: string };

/**
 * What somebody holding the link may see before deciding.
 *
 * Enough to answer "who is asking me to join what, and as what", and
 * deliberately nothing that would matter to whoever else got hold of it.
 */
export type InvitationPreview = {
  workspace_name: string;
  workspace_slug: string;
  email: string;
  role: WorkspaceRole;
  status: InvitationStatus;
  expires_at: string;
};

// --- knowledge (W5) ---------------------------------------------------

/**
 * Where a piece of knowledge came from.
 *
 * Three of the plan's five: `website` and `product_catalog` are named
 * there and deliberately absent from the API, because a value it accepted
 * and nothing could process would be worse than one it refuses.
 */
export type SourceType = "text" | "file" | "manual_faq";

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export type KnowledgeSource = {
  id: string;
  name: string;
  source_type: SourceType;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
};

export type KnowledgeDocument = {
  id: string;
  knowledge_source_id: string;
  title: string;
  status: DocumentStatus;
  /** Present only when `failed`, and in plain words rather than a trace. */
  error: string | null;
  /**
   * How many passages it became — the honest measure of whether a document
   * is doing anything. One that is `ready` with no chunks answers nothing.
   */
  chunk_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

/** One passage, and how close it was to the question. */
export type SearchMatch = {
  document_id: string;
  chunk_id: string;
  score: number;
  content: string;
  metadata: Record<string, unknown>;
};

/**
 * What was asked, and what came back.
 *
 * The query is echoed because it is not always what was sent —
 * normalisation happens first — and an answer that cannot be tied to the
 * question that produced it is not reproducible.
 */
export type SearchResult = { query: string; matches: SearchMatch[] };

// --- the catalogue and its orders (W6) --------------------------------

/**
 * Whether the business is selling this.
 *
 * The assistant is told about `active` products only: talking about a
 * draft is worse than saying nothing, because the customer then asks for
 * something the business has not decided to sell yet.
 */
export type ProductStatus = "active" | "draft" | "archived";

/** One buyable version of a product. */
export type Variant = {
  id: string;
  external_id: string | null;
  sku: string | null;
  title: string | null;
  /** Null means the product's price applies — not that it is free. */
  price: string | null;
  /** Null means this business does not track stock, which is not zero. */
  stock_quantity: number | null;
  attributes: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Product = {
  id: string;
  /** Set by a storefront sync. Its presence is what makes a product theirs. */
  external_id: string | null;
  name: string;
  description: string | null;
  status: ProductStatus;
  /** A decimal string. Never parse it — see lib/money.ts. */
  price: string | null;
  currency: string | null;
  metadata: Record<string, unknown>;
  variants: Variant[];
  created_at: string;
  updated_at: string;
};

/**
 * Where an order has got to.
 *
 * The vocabulary a customer asks about rather than a payment processor's:
 * "has it shipped" is the question, and these six are the answers a shop
 * actually gives.
 */
export type OrderStatus =
  | "pending"
  | "confirmed"
  | "shipped"
  | "delivered"
  | "cancelled"
  | "refunded";

export type Order = {
  id: string;
  contact_id: string;
  external_id: string | null;
  order_number: string | null;
  status: OrderStatus;
  currency: string | null;
  /** All decimal strings. */
  subtotal: string | null;
  shipping_total: string | null;
  total: string | null;
  shipping_address: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
  placed_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

// --- plans, billing and usage (W7) ------------------------------------

export type PlanTier = "starter" | "growth" | "business";

/** Something a plan either admits or does not. Checked at the door. */
export type Feature =
  | "automations"
  | "ecommerce"
  | "advanced_analytics"
  | "api_access"
  | "audit_logs";

/** Something a plan allows a number of. Counted, not checked at the door. */
export type PlanLimit =
  | "whatsapp_numbers"
  | "team_members"
  | "ai_responses_per_month"
  | "knowledge_documents";

export type Plan = {
  tier: PlanTier;
  name: string;
  description: string;
  /** A decimal string. `"0"` for the free tier. Never parse it. */
  price: string;
  currency: string;
  features: Feature[];
  /** Every limit on every plan; `null` means unlimited, never absent. */
  limits: Record<PlanLimit, number | null>;
};

/**
 * Where a subscription stands, in the provider's vocabulary.
 *
 * Kept as the provider says it rather than reduced to working/not: the
 * difference between `past_due` and `canceled` is the whole of how a
 * billing failure is handled.
 */
export type SubscriptionStatus =
  | "active"
  | "trialing"
  | "past_due"
  | "unpaid"
  | "canceled"
  | "incomplete";

export type Subscription = {
  id: string;
  provider: string;
  /** What is being paid for — which is not always what applies. */
  plan: PlanTier;
  status: SubscriptionStatus;
  current_period_start: string | null;
  current_period_end: string | null;
  /** True between somebody cancelling and the period running out. */
  cancel_at_period_end: boolean;
  created_at: string;
  updated_at: string;
};

/**
 * What a workspace may do, and what it is paying for.
 *
 * Two fields because they are two questions and they routinely disagree.
 * `plan` is what actually applies, after overrides and status; gate on it.
 * `subscription` is display only, and is null for a workspace that has
 * never paid — which is not the same as one whose payment failed.
 */
export type WorkspacePlan = { plan: Plan; subscription: Subscription | null };

export type UsageMetric =
  | "ai_responses"
  | "ai_tokens"
  | "whatsapp_messages"
  | "active_contacts"
  | "team_members"
  | "whatsapp_numbers"
  | "knowledge_documents"
  | "knowledge_tokens";

export type MetricUsage = {
  metric: UsageMetric;
  quantity: number;
  /** Null where nothing refuses this. Means carry on, not zero. */
  limit: number | null;
};

/**
 * What a workspace has used, and over what.
 *
 * The period comes from the API rather than being assumed: a subscribed
 * workspace is metered over the dates the provider is billing it for, and
 * a page saying "this month" over those figures would be wrong for most
 * of the month.
 */
export type UsageSummary = {
  period_start: string;
  period_end: string;
  metrics: MetricUsage[];
};

/** `POST …/subscription/checkout`. Nothing has changed yet. */
export type CheckoutStarted = { checkout_url: string };

// --- automations and integrations (W8) --------------------------------

/**
 * Which of the predefined automations a row configures.
 *
 * Three, and this is a settings form rather than a workflow builder: the
 * definition holds settings for a known automation, not a program.
 */
export type AutomationKind =
  | "order_confirmation"
  | "human_handoff"
  | "unanswered_lead_followup";

export type AutomationTrigger =
  | "message_received"
  | "order_created"
  /** Not an event: something failing to happen for long enough. */
  | "schedule";

export type AutomationStatus = "enabled" | "disabled";

/**
 * How one attempt ended.
 *
 * `skipped` is not a failure and is the most common outcome by far — an
 * automation is considered on every matching event and most events are
 * not the one it is for.
 */
export type RunStatus = "running" | "succeeded" | "failed" | "skipped";

export type Automation = {
  id: string;
  kind: AutomationKind;
  name: string;
  trigger_type: AutomationTrigger;
  status: AutomationStatus;
  definition: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AutomationRun = {
  id: string;
  automation_id: string;
  status: RunStatus;
  /** What the run was about, when it was about something. */
  dedupe_key: string | null;
  attempts: number;
  started_at: string;
  completed_at: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
};

/** `ran` is what did something; the gap to `considered` is work left alone. */
export type SweepReport = { considered: number; ran: number };

export type WhatsAppStatus = "connected" | "disconnected";

/**
 * The connection, as anybody is ever allowed to see it.
 *
 * There is no token field of any kind. A value absent from the schema
 * cannot be serialised into a response by accident, which is the same
 * guarantee the user schema makes about passwords.
 */
export type WhatsAppAccount = {
  id: string;
  provider: string;
  phone_number: string;
  external_phone_number_id: string;
  external_business_account_id: string | null;
  status: WhatsAppStatus;
  connected_at: string;
  created_at: string;
  updated_at: string;
};

export type StorefrontProvider = "shopify" | "woocommerce";
export type StorefrontStatus = "connected" | "disconnected";

export type Storefront = {
  id: string;
  provider: StorefrontProvider;
  shop_domain: string;
  status: StorefrontStatus;
  /** Null until the first full read finishes — "not synced yet". */
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
};

/** Where to send the shop owner. Nothing is connected until they approve. */
export type StorefrontInstall = { authorize_url: string; shop_domain: string };

/** `skipped` counts records already as new here — what a retry looks like. */
export type SyncReport = {
  products: number;
  orders: number;
  contacts: number;
  skipped: number;
};

// --- analytics, audit and API keys (W9) -------------------------------

/** One day of a chart. Days with nothing in them arrive as zero. */
export type DayPoint = { day: string; count: number };

export type ConversationTotals = {
  total: number;
  open: number;
  pending: number;
  closed: number;
  with_a_human: number;
  unassigned: number;
};

export type MessageTotals = {
  total: number;
  received: number;
  sent: number;
  by_ai: number;
  by_agents: number;
};

/**
 * Conversations somebody replied in, split by who.
 *
 * A thread both the assistant and an agent spoke in counts in both — it
 * was handled by both — which is why these do not sum to `answered`.
 */
export type HandledTotals = { answered: number; by_ai: number; by_agents: number };

export type Overview = {
  conversations: ConversationTotals;
  messages: MessageTotals;
  handled: HandledTotals;
  handoffs: number;
  ai_decisions: number;
  ai_response_rate: number;
  /** Null when nothing has been answered — an honest gap, not a zero. */
  average_first_response_seconds: number | null;
};

export type ConversationAnalytics = {
  totals: ConversationTotals;
  by_day: DayPoint[];
  average_first_response_seconds: number | null;
};

export type AiDecisionTotals = {
  total: number;
  answered: number;
  suggested: number;
  handoff: number;
  blocked: number;
  failed: number;
};

export type HandoffTotals = {
  total: number;
  ai_handoff: number;
  human_takeover: number;
  ai_released: number;
};

/** Null where nothing was recorded. */
export type AiCost = {
  input_tokens: number | null;
  output_tokens: number | null;
  average_latency_ms: number | null;
  average_confidence: number | null;
};

export type AiAnalytics = {
  decisions: AiDecisionTotals;
  handoffs: HandoffTotals;
  cost: AiCost;
  by_day: DayPoint[];
  /** The share of answered conversations the assistant spoke in. */
  response_rate: number;
  /** Of the times it was asked, how often it produced something. */
  answer_rate: number;
};

/**
 * Whoever did it, as much as is still known.
 *
 * Present with an address and no id where the account has since been
 * deleted — the record of what somebody did outliving their account is why
 * the table exists. Wholly null where no person did it at all.
 */
export type AuditActor = {
  user_id: number | null;
  name: string | null;
  email: string | null;
};

export type AuditEntry = {
  id: string;
  event: string;
  actor: AuditActor | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

/** A key as it can be shown again: everything except the key. */
export type ApiKey = {
  id: string;
  name: string;
  /** The readable fragment — which of these three is on staging. */
  key_prefix: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

/**
 * The one response that carries the key itself.
 *
 * Its own type rather than an optional field, so the secret is in the
 * shape of exactly one endpoint. Nothing stored can reproduce it.
 */
export type ApiKeyCreated = ApiKey & { key: string };
