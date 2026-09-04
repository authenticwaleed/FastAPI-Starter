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
