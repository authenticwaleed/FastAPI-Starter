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

// --- the console, read-only (W10) -------------------------------------

/**
 * What somebody who runs Baton itself may do, in ascending order.
 *
 * Not to be confused with `WorkspaceRole`, which is about a customer's own
 * team. These three are a ladder rather than a fan: everything support may
 * do, an admin may do too.
 */
export type StaffRole = "support" | "admin" | "owner";

/** `GET /admin/me`. Who you are on this platform, and what you may reach. */
export type StaffMember = {
  user_id: number;
  name: string;
  email: string;
  role: StaffRole;
  /** Null for the first owner, and only for them: nobody granted it. */
  granted_by_user_id: number | null;
  granted_at: string;
  revoked_at: string | null;
};

/**
 * One business, as a console search result.
 *
 * `plan` is what applies right now, after overrides and status — the same
 * field §3.4 says to gate on, here shown rather than gated on. `owner_email`
 * is null where the owner has closed their account, which is a real state
 * and one somebody would be searching about.
 */
export type AdminWorkspaceSummary = {
  id: string;
  name: string;
  slug: string;
  status: WorkspaceStatus;
  plan: PlanTier;
  owner_email: string | null;
  /**
   * When a cancelled workspace's records are due to be destroyed.
   *
   * Null while it is live. This is the field the customer's own API will
   * not show at all — a closed workspace is simply gone there — and it is
   * the answer to "it was closed last week, can we get it back".
   */
  erase_after: string | null;
  created_at: string;
};

/** How much of everything a workspace holds. Counts, and this phase stops here. */
export type AdminWorkspaceCounts = {
  members: number;
  contacts: number;
  conversations: number;
  messages: number;
  knowledge_documents: number;
};

export type AdminWorkspaceDetail = AdminWorkspaceSummary & {
  timezone: string;
  default_currency: string;
  counts: AdminWorkspaceCounts;
  updated_at: string;
};

/** The same fields the business sees in its own member list, deliberately. */
export type AdminMember = {
  user_id: number;
  name: string;
  email: string;
  role: WorkspaceRole;
  status: MembershipStatus;
  joined_at: string;
};

/**
 * What the payment provider says about a workspace.
 *
 * The provider's identifiers are here because they are how somebody finds
 * the same subscription in the provider's own dashboard, which is where
 * refunds belong. They are handles rather than secrets.
 */
export type AdminSubscription = {
  id: string;
  provider: string;
  provider_customer_id: string | null;
  provider_subscription_id: string | null;
  plan: PlanTier;
  status: SubscriptionStatus;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  created_at: string;
  updated_at: string;
};

/**
 * What the provider says, and what the workspace actually gets.
 *
 * §3.4 again, and the gap between the two is where billing support
 * happens: a `past_due` subscription still entitles the full plan while
 * the provider retries. `subscription` is null for a workspace that has
 * never paid, which is not the same as one whose payment failed.
 */
export type AdminBilling = { plan: PlanTier; subscription: AdminSubscription | null };

/** A connected number. There is no field for the token and will not be one. */
export type AdminWhatsApp = {
  provider: string;
  phone_number: string;
  /** The provider's public handle for the number. Not a credential. */
  external_phone_number_id: string;
  status: WhatsAppStatus;
  connected_at: string;
};

export type AdminStorefront = {
  provider: string;
  shop_domain: string;
  status: StorefrontStatus;
  /** Null until the first sync finishes. Stale is what a null or old date is. */
  last_synced_at: string | null;
  created_at: string;
};

/** Each null where nothing is connected, never an absent key. */
export type AdminIntegrations = {
  whatsapp: AdminWhatsApp | null;
  storefront: AdminStorefront | null;
};

/** One account, as a console search result. No hash, and nowhere to put one. */
export type AdminUserSummary = {
  id: number;
  name: string;
  email: string;
  is_active: boolean;
  email_verified_at: string | null;
  created_at: string;
};

/**
 * One workspace an account belongs to, or used to.
 *
 * Removed memberships and cancelled workspaces are both here, which the
 * person's own view of themselves would not show: "an admin of that
 * business until it closed" is an answer rather than noise.
 */
export type AdminUserMembership = {
  workspace_id: string;
  name: string;
  slug: string;
  workspace_status: WorkspaceStatus;
  role: WorkspaceRole;
  status: MembershipStatus;
  joined_at: string;
};

/** One live sign-in, as staff see it. The same fields its owner sees. */
export type AdminUserSession = {
  id: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  user_agent: string | null;
  ip_address: string | null;
};

/** Both lists are empty for somebody who registered and stopped there. */
export type AdminUserDetail = AdminUserSummary & {
  memberships: AdminUserMembership[];
  sessions: AdminUserSession[];
};

/** Whichever staff member did it, as much as is still known. */
export type AdminAuditActor = {
  user_id: number | null;
  name: string | null;
  email: string | null;
};

/**
 * Which business an entry was about, where it was about one.
 *
 * Absent for the acts that belong to no workspace, and present with a null
 * id and a readable slug once the workspace has been erased — which is the
 * state this log exists to outlive.
 */
export type AdminAuditSubject = {
  workspace_id: string | null;
  workspace_slug: string | null;
};

export type AdminAuditEntry = {
  id: string;
  action: string;
  actor: AdminAuditActor | null;
  subject: AdminAuditSubject | null;
  target_user_id: number | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
};

// --- support access (W11) ---------------------------------------------

/**
 * One time-boxed window over a customer's data, live or historical.
 *
 * The staff member's address rather than their id, because whoever reads
 * this list is asking who was in an account and an id sends them to
 * another table to find out.
 *
 * `live` is computed by the API from `expires_at`, `revoked_at` and the
 * clock rather than stored — there is no status column, for the same
 * reason a session has none. A client must not recompute it from
 * `expires_at` alone: a revoked grant has not expired and is not live.
 */
export type SupportGrant = {
  id: string;
  workspace_id: string;
  staff_user_id: number;
  staff_email: string;
  /** What was told to the customer. It lands in their own audit log. */
  reason: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  live: boolean;
};

// --- lifecycle, and the people who run it (W12) -----------------------

/**
 * The two acts that need a second person.
 *
 * Two, and short on purpose: requiring a colleague for everything means
 * nobody can do anything alone at three in the morning, and a rule people
 * cannot follow is one they route around. One of these destroys a
 * business's records with no way back, and the other creates somebody who
 * can do the first.
 */
export type ApprovableAction = "erase_workspace" | "grant_staff_owner";

/**
 * One colleague agreeing, in advance, to one specific act.
 *
 * `subject` is the workspace id for an erasure and the account id for a
 * promotion, as text — an approval has to be able to outlive the workspace
 * it names.
 *
 * `usable` is computed by the API from the three timestamps and the clock.
 * What it does not say is whether *you* may spend it: that depends on who
 * is asking, and the answer is no if you are the one who approved it.
 */
export type Approval = {
  id: string;
  action: ApprovableAction;
  subject: string;
  reason: string;
  requested_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  consumed_at: string | null;
  expires_at: string;
  created_at: string;
  metadata: Record<string, unknown>;
  usable: boolean;
};

// --- the platform's own books and machinery (W13) ----------------------

/** One subscription, with the business it belongs to named. */
export type AdminSubscriptionRow = AdminSubscription & { workspace_slug: string };

/**
 * One delivery from the payment provider.
 *
 * `replayable` is false for deliveries recorded before payloads were
 * kept: there is genuinely nothing to re-apply, and saying so beats a
 * button that answers "nothing happened".
 */
export type AdminBillingEvent = {
  id: string;
  provider: string;
  provider_event_id: string;
  /** The provider's own word, so a row can be held up against their dashboard. */
  event_type: string;
  received_at: string;
  replayable: boolean;
  /** The delivery in this application's words — never the raw body. */
  payload: Record<string, unknown>;
};

/**
 * What a replay did.
 *
 * `applied: false` means there was nothing to do — a delivery from before
 * payloads were kept, or one naming a subscription this platform does not
 * hold. An ordinary answer, not a failure.
 */
export type ReplayResult = { applied: boolean };

/**
 * A plan granted rather than paid for, and whether it is in force.
 *
 * It outranks the subscription and survives every webhook, which is why
 * it is a row of its own rather than a value written onto the
 * subscription — that would revert on the next delivery, silently.
 */
export type PlanOverride = {
  workspace_id: string;
  plan: PlanTier;
  reason: string;
  granted_by_user_id: number | null;
  expires_at: string | null;
  created_at: string;
  /** Computed from the expiry and the clock. An expired grant is kept and shown. */
  applies: boolean;
  /** True where no date was set: a plan nothing will ever take away. */
  forever: boolean;
};

export type JobKind =
  | "deliver_message"
  | "sweep_automations"
  | "run_due_automations"
  | "sweep_erasures";

export type JobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

/** One job in the queue. Null `workspace_id` is a platform sweep, not a gap. */
export type AdminJobSummary = {
  id: string;
  kind: JobKind;
  status: JobStatus;
  workspace_id: string | null;
  attempts: number;
  max_attempts: number;
  run_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** The field the whole screen is for. */
  last_error: string | null;
  created_at: string;
};

/**
 * One job, with as much of its payload as its kind admits.
 *
 * Redacted on a safe-list by the API: a field nobody named for this kind
 * comes back as `[redacted]` rather than being dropped, so a reader can
 * tell "something is here I am not being shown" from "nothing is here".
 */
export type AdminJobDetail = AdminJobSummary & {
  payload: Record<string, unknown>;
  dedupe_key: string | null;
};

export type WebhookRefusal = "bad_signature" | "unknown_subject" | "malformed";

/** One delivery that was turned away. No body, ever. */
export type AdminWebhookFailure = {
  id: string;
  provider: string;
  reason: WebhookRefusal;
  path: string;
  ip_address: string | null;
  received_at: string;
};

export type AdminWhatsAppNumber = {
  workspace_id: string;
  workspace_slug: string;
  provider: string;
  phone_number: string;
  external_phone_number_id: string;
  status: WhatsAppStatus;
  connected_at: string;
};

/**
 * The two numbers that say whether the worker has stopped.
 *
 * Depth alone cannot tell a busy afternoon from a dead worker: two
 * hundred draining in a minute is fine, three where the oldest has waited
 * an hour is not, and the count looks the same. `oldest_pending_seconds`
 * is null when nothing is due, which is not zero.
 */
export type AdminQueueHealth = {
  depth: number;
  oldest_pending_seconds: number | null;
  running: number;
  failed: number;
};

/** `integrations` says whether each is configured, never whether it answers. */
export type AdminHealth = {
  database: boolean;
  queue: AdminQueueHealth;
  integrations: Record<string, boolean>;
};

export type PlatformCounts = {
  users: number;
  workspaces: number;
  conversations: number;
  messages: number;
};

/** A value with nothing in it is absent rather than zero. Read a gap as zero. */
export type AdminOverview = {
  counts: PlatformCounts;
  workspaces_by_status: Partial<Record<WorkspaceStatus, number>>;
  workspaces_by_plan: Partial<Record<PlanTier, number>>;
};

export type DailyPoint = { day: string; count: number };

/**
 * Signups, closures, and how many businesses actually used the product.
 *
 * The third is the one a row count cannot give: counted from messages
 * sent, so four hundred workspaces and nine active says something the
 * headline hides.
 */
export type AdminGrowth = {
  days: number;
  signups: DailyPoint[];
  closures: DailyPoint[];
  active_workspaces: number;
};

/** Counts per plan rather than an amount: what a plan costs lives elsewhere. */
export type AdminRevenue = {
  subscriptions_by_status: Partial<Record<SubscriptionStatus, number>>;
  paying_by_plan: Partial<Record<PlanTier, number>>;
};

/**
 * What the assistant cost across every tenant, in tokens rather than money.
 *
 * What a token costs is a contract with a model provider and changes
 * without this application being redeployed; a figure in dollars would
 * look authoritative and be wrong within a quarter.
 */
export type AdminAiSpend = {
  days: number;
  replies: number;
  input_tokens: number | null;
  output_tokens: number | null;
  average_latency_ms: number | null;
  by_model: Record<string, number>;
};

/** One staff member, and how many distinct customers they opened. */
export type BusyReader = {
  user_id: number | null;
  email: string | null;
  workspaces_read: number;
};

/**
 * Patterns worth a person looking at, not refusals.
 *
 * Nothing here stops anybody doing anything, and that is the design: both
 * patterns are perfectly ordinary during an incident and worth noticing
 * afterwards, and a control that refused them would be worked around
 * within a week by whoever was on call.
 */
export type AdminAlerts = {
  hours: number;
  threshold: number;
  busiest_readers: BusyReader[];
  over_threshold: BusyReader[];
};
