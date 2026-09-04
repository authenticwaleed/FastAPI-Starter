/**
 * Which workspace is being looked at, and what the person may do in it.
 *
 * The active workspace is a cookie rather than client state, so a server
 * component knows it on the first render instead of after a round trip.
 * It holds an id and nothing else -- the workspace itself is read from the
 * API every time, because a name cached in a cookie is a name that goes
 * stale the moment somebody renames the business.
 */

import { cookies } from "next/headers";

import { api } from "@/lib/api";
import { IS_PRODUCTION } from "@/lib/config";
import type { Member, Page, User, Workspace, WorkspaceRole } from "@/lib/types";

export const WORKSPACE_COOKIE = "baton_ws";

/** Not httpOnly, unlike the session: this is a preference, not a credential. */
const COOKIE = {
  httpOnly: false,
  secure: IS_PRODUCTION,
  sameSite: "lax" as const,
  path: "/",
  maxAge: 60 * 60 * 24 * 365,
};

export async function readActiveWorkspaceId(): Promise<string | null> {
  return (await cookies()).get(WORKSPACE_COOKIE)?.value ?? null;
}

export async function setActiveWorkspaceId(id: string): Promise<void> {
  (await cookies()).set(WORKSPACE_COOKIE, id, COOKIE);
}

export async function clearActiveWorkspace(): Promise<void> {
  (await cookies()).delete(WORKSPACE_COOKIE);
}

/**
 * The workspaces this person belongs to.
 *
 * One page of a hundred, which is not paging and is honest about it: a
 * switcher listing more than that is a different design problem, and
 * pretending otherwise would mean a switcher that silently omits a
 * workspace somebody is looking for.
 */
export async function listWorkspaces(): Promise<Workspace[]> {
  const page = await api<Page<Workspace>>("/workspaces?page=1&page_size=100");

  return page.items;
}

/**
 * The workspace to show, and the cookie kept honest.
 *
 * Falls back to the first one when the cookie names a workspace that is
 * gone -- closed, or one the person has been removed from -- because the
 * alternative is a switcher stuck on something that answers 404.
 */
export async function activeWorkspace(): Promise<Workspace | null> {
  const workspaces = await listWorkspaces();

  if (workspaces.length === 0) return null;

  const wanted = await readActiveWorkspaceId();
  const found = workspaces.find((workspace) => workspace.id === wanted);

  return found ?? workspaces[0];
}

/**
 * What this person may do in this workspace.
 *
 * Read from the member list, which is the only place the API says so: no
 * workspace response carries the caller's own role. That makes this the one
 * endpoint W2 borrows from W4, and the borrowing is deliberate -- the
 * alternatives were to show every member a form that fails for most of
 * them, or to guess, and the plan asks this client not to guess.
 *
 * Returns null where the role cannot be established, and every caller
 * treats null as "assume nothing is permitted". A disabled control that
 * should have been enabled is a nuisance; an enabled one that always fails
 * is a bug report.
 */
export async function roleIn(
  workspaceId: string,
  user: User,
): Promise<WorkspaceRole | null> {
  const members = await api<Member[]>(`/workspaces/${workspaceId}/members`);
  const mine = members.find((member) => member.user_id === user.id);

  return mine?.role ?? null;
}

export const MAY_ADMINISTER: WorkspaceRole[] = ["owner", "admin"];
export const MAY_CLOSE: WorkspaceRole[] = ["owner"];

export function permits(role: WorkspaceRole | null, allowed: WorkspaceRole[]): boolean {
  return role !== null && allowed.includes(role);
}
