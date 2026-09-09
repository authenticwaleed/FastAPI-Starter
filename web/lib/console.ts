/**
 * What the console reads.
 *
 * Nothing here writes into a customer's workspace, and nothing will: the
 * two acts this surface does perform -- asking for support access and
 * ending it -- change a grant on the platform's own side and live in
 * `lib/console-actions.ts` with the rest of the acts.
 *
 * Every function here writes a row to the platform's audit log, including
 * the ones that look idle. That is the API's design rather than an
 * accident, and it is why this module has no prefetching, no polling and
 * no convenience call that fetches "while we are here": a request nobody
 * asked for is a row nobody can account for, and enough of those make the
 * log useless for the one question it exists to answer.
 *
 * So each screen calls exactly what it shows. The workspace detail page in
 * particular does *not* fan out to members, subscription, usage and
 * integrations -- those are four more screens and four more rows, spent
 * only when somebody opens them.
 */

import { adminApi as read } from "@/lib/console-api";
import type {
  AdminAuditEntry,
  AdminBilling,
  AdminIntegrations,
  AdminMember,
  AdminUserDetail,
  AdminUserSummary,
  AdminWorkspaceDetail,
  AdminWorkspaceSummary,
  AuditEntry,
  Conversation,
  ConversationStatus,
  Message,
  Page,
  StaffMember,
  SupportGrant,
  UsageSummary,
} from "@/lib/types";

/**
 * Who you are on this platform.
 *
 * The console's first call, and the one that writes `console.opened`. It
 * belongs to the console's front page rather than to its layout: called
 * from a layout it would fire on every navigation, and a log claiming the
 * console was opened thirty times in an afternoon answers "who was in the
 * console on Tuesday" worse than one that says it once.
 */
export function whoami() {
  return read<StaffMember>("/me");
}

export type WorkspaceSearch = {
  q?: string | null;
  status?: string | null;
  plan?: string | null;
  page?: number;
};

/**
 * Find a business by name, by slug, or by the address of anyone in it.
 *
 * The third is the one a ticket actually arrives with. Cancelled
 * workspaces are included and carry their erasure date, unlike anything
 * the customer's own API would answer.
 */
export function searchWorkspaces({ q, status, plan, page = 1 }: WorkspaceSearch = {}) {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: "50",
  });

  if (q) parameters.set("q", q);
  if (status) parameters.set("status", status);
  if (plan) parameters.set("plan", plan);

  return read<Page<AdminWorkspaceSummary>>(`/workspaces?${parameters}`);
}

export function readWorkspace(workspaceId: string) {
  return read<AdminWorkspaceDetail>(`/workspaces/${workspaceId}`);
}

/** Unpaginated at the API: a workspace's team is people, not a page of them. */
export function readWorkspaceMembers(workspaceId: string) {
  return read<AdminMember[]>(`/workspaces/${workspaceId}/members`);
}

export function readWorkspaceSubscription(workspaceId: string) {
  return read<AdminBilling>(`/workspaces/${workspaceId}/subscription`);
}

/** The same shape, from the same meter, as the business's own usage page. */
export function readWorkspaceUsage(workspaceId: string) {
  return read<UsageSummary>(`/workspaces/${workspaceId}/usage`);
}

export function readWorkspaceIntegrations(workspaceId: string) {
  return read<AdminIntegrations>(`/workspaces/${workspaceId}/integrations`);
}

/**
 * The business's own record of what its people did to it.
 *
 * Their log, and reading it is recorded in ours. No plan is required here,
 * unlike the customer's own route: whether support can answer a ticket
 * about an audit log is not a decision that business's plan gets to make.
 */
export function readWorkspaceAudit(
  workspaceId: string,
  { page = 1 }: { page?: number } = {},
) {
  const parameters = new URLSearchParams({ page: String(page), page_size: "50" });

  return read<Page<AuditEntry>>(`/workspaces/${workspaceId}/audit?${parameters}`);
}

export function searchUsers({ q, page = 1 }: { q?: string | null; page?: number } = {}) {
  const parameters = new URLSearchParams({ page: String(page), page_size: "50" });

  if (q) parameters.set("q", q);

  return read<Page<AdminUserSummary>>(`/users?${parameters}`);
}

export function readUser(userId: number) {
  return read<AdminUserDetail>(`/users/${userId}`);
}

/**
 * What staff have done, newest first.
 *
 * Admin rank at the API, and support gets a sentence rather than a crash.
 * Reading it is itself recorded, which is the rule this surface rests on
 * and applies to the log as readily as to anything else.
 */
export function listPlatformAudit({
  page = 1,
  action = null,
  workspaceId = null,
}: {
  page?: number;
  action?: string | null;
  workspaceId?: string | null;
} = {}) {
  const parameters = new URLSearchParams({ page: String(page), page_size: "50" });

  if (action) parameters.set("action", action);
  if (workspaceId) parameters.set("workspace_id", workspaceId);

  return read<Page<AdminAuditEntry>>(`/audit?${parameters}`);
}

// --- support access, and the two reads it opens (W11) -------------------

/**
 * Who has been in this account, when, and why.
 *
 * History as well as what is live, because a list of only the live ones is
 * almost always empty and the question is about the past. Administrators
 * and above at the API: the rank that answers tickets is the one that
 * needs access, and the rank that oversees them is the one that reviews
 * whether they should have had it.
 */
export function listSupportGrants(workspaceId: string) {
  return read<SupportGrant[]>(`/workspaces/${workspaceId}/support-access`);
}

export const CONSOLE_INBOX_PAGE_SIZE = 20;
export const CONSOLE_THREAD_PAGE_SIZE = 30;

/**
 * The customer's inbox, as they see it.
 *
 * Through the API's own service and renderer, so what support is looking
 * at is what the customer is looking at. There is no "assigned to me"
 * here and the API does not offer one: it has no meaning for somebody who
 * is not on the team, and it is the first place a staff actor would start
 * to look like a colleague.
 *
 * Refused with `support_access_required` without a live grant, which is
 * the refusal this whole phase is built around.
 */
export function listWorkspaceConversations(
  workspaceId: string,
  {
    page = 1,
    statuses = [],
  }: { page?: number; statuses?: ConversationStatus[] } = {},
) {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: String(CONSOLE_INBOX_PAGE_SIZE),
  });

  for (const status of statuses) parameters.append("status", status);

  return read<Page<Conversation>>(
    `/workspaces/${workspaceId}/conversations?${parameters}`,
  );
}

/**
 * One thread, in full: the deepest anything on this surface reaches.
 *
 * The entry the API writes for it names the conversation rather than only
 * the workspace, because "they read the inbox" and "they read this
 * customer's thread with this person" are different answers to give
 * afterwards.
 */
export function listWorkspaceMessages(
  workspaceId: string,
  conversationId: string,
  { page = 1 }: { page?: number } = {},
) {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: String(CONSOLE_THREAD_PAGE_SIZE),
  });

  return read<Page<Message>>(
    `/workspaces/${workspaceId}/conversations/${conversationId}/messages?${parameters}`,
  );
}

// --- the people who run the platform (W12) -----------------------------

/**
 * Everybody who runs this platform, revoked rows included.
 *
 * Unpaginated at the API, like a workspace's member list and for the same
 * reason: this is people, and there are not going to be thousands of them.
 * Revoked rows stay because they are the useful half of the screen after
 * an incident — who used to have this, and when it was taken away.
 *
 * Administrator rank to read; only an owner may change any of it.
 */
export function listStaff() {
  return read<StaffMember[]>("/staff");
}
