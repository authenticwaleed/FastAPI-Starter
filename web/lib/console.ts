/**
 * The eleven reads the console is allowed to make.
 *
 * No mutation lives here and none will until W11: this phase is the same
 * decision the API's own A2 took, for the same reason -- a console that is
 * useful and cannot break anything beats a half-built one that can.
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

import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { CONSOLE_SIGN_IN_PATH, readConsoleSession } from "@/lib/console-session";
import { ApiError } from "@/lib/errors";
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
  Page,
  StaffMember,
  UsageSummary,
} from "@/lib/types";

/**
 * One read, on the console's own session.
 *
 * The 401 is caught here rather than by each screen because there is one
 * right answer to it and it is the same everywhere: the console signs out
 * on its own schedule (§3.5), and what that needs is the console's sign-in
 * screen. It does not need -- and must not have -- the tenant session
 * cleared, which is why nothing in this file touches those cookies.
 *
 * `403` and `404` are left to the caller. Both mean something on this
 * surface that they do not mean on the other, and the screen is where
 * that gets said.
 */
async function read<T>(path: string): Promise<T> {
  const { accessToken } = await readConsoleSession();

  if (!accessToken) redirect(CONSOLE_SIGN_IN_PATH);

  try {
    return await api<T>(`/admin${path}`, { bearer: accessToken });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect(`${CONSOLE_SIGN_IN_PATH}?expired=1`);
    }

    throw error;
  }
}

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
