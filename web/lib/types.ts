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
