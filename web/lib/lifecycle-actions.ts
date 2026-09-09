"use server";

/**
 * What the platform does to an account, as opposed to look at it.
 *
 * The first module in this client that changes a customer's world from
 * the platform's side, and three things are true of everything in it.
 *
 * **The customer sees it.** Every act here writes to the business's own
 * audit log with the staff member's address rather than an actor, so it
 * can never read as one of their own people having done it. Nothing in
 * this file has to arrange that -- the API does -- but it is the reason
 * the copy on these screens can promise it.
 *
 * **The destructive ones name their subject.** Closing and erasing take
 * the workspace's slug in the body. An id is copied from a list; a slug
 * has to be read and typed, and the difference between those two acts is
 * the safeguard. A mismatch is a 422 that belongs on the field.
 *
 * **A refusal is usually about state, not permission.** `409
 * workspace_lifecycle` means the move does not apply from where the
 * workspace is, so every act here drops the screens that render the
 * available ones and lets them be worked out again.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { raiseApproval } from "@/lib/approvals";
import { adminApi } from "@/lib/console-api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";

/**
 * What a refusal from this surface hands back to a form.
 *
 * `detail` is carried alongside the sentence for the two codes that say
 * something particular -- which state refused this, which colleague
 * already approved it. Nothing branches on those words; they are shown
 * under the sentence and nowhere else.
 */
function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return {
      error: error.sentence,
      code: error.code,
      detail: error.detail,
      fields: error.fields,
      retryAfter: error.retryAfter ?? undefined,
    };
  }

  throw error;
}

/** Every console screen that renders this workspace's state. */
function workspaceScreens(workspaceId: string): string[] {
  const base = `/console/workspaces/${workspaceId}`;

  return [base, `${base}/lifecycle`, `${base}/erase`, "/console/workspaces"];
}

async function act(
  workspaceId: string,
  path: string,
  options: { method?: string; json?: unknown } = {},
): Promise<FormState> {
  try {
    await adminApi(`/workspaces/${workspaceId}${path}`, {
      method: options.method ?? "POST",
      ...options,
    });
  } catch (error) {
    const refused = failure(error);

    // The phase's rule about a 409: it means the move does not apply from
    // where the workspace is, so the screen offering it was rendered
    // before somebody else moved it. Dropping the screens is the answer
    // -- the refusal is read once, and the controls that come back are
    // the ones that now apply. Leaving a stale "close this account" under
    // an "already closed" is how somebody presses it a third time.
    if (refused?.code === "workspace_lifecycle") {
      for (const screen of workspaceScreens(workspaceId)) revalidatePath(screen);
    }

    return refused;
  }

  for (const screen of workspaceScreens(workspaceId)) revalidatePath(screen);

  return { done: true };
}

// --- a business ---------------------------------------------------------

/**
 * Freeze an account: reachable, readable, and unchangeable.
 *
 * The reason is required and the customer reads it, which is why the form
 * asks for a sentence rather than a label. A business that finds itself
 * suspended and cannot see why has to open a ticket to be told something
 * the platform already knew.
 */
export async function suspendWorkspace(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  return act(workspaceId, "/suspend", { json: { reason: form.get("reason") } });
}

/**
 * Thaw an account.
 *
 * A no-op at the API on one that was never frozen, and nothing is
 * recorded for it -- refusing would be a confusing answer to somebody
 * trying to put things right.
 */
export async function unsuspendWorkspace(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  return act(String(form.get("workspace_id") ?? ""), "/unsuspend");
}

/**
 * Close an account on the customer's behalf, and start the clock.
 *
 * Nothing is destroyed today: the workspace is marked closed and given a
 * date, and until that date restoring brings it back intact. The copy
 * says so, because overstating this would frighten somebody out of an
 * action they can undo.
 */
export async function cancelWorkspace(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  return act(workspaceId, "/cancel", {
    json: { confirm_slug: form.get("confirm_slug") },
  });
}

/**
 * Bring a closed account back, before its erasure date.
 *
 * Refused after that date rather than pretending: by then the erasure job
 * may have run, may be running, or may run in the next minute, and
 * "restored" would be a promise nobody can keep. That refusal is a 409
 * whose detail says which of those it was, so the screen shows it.
 */
export async function restoreWorkspace(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  return act(String(form.get("workspace_id") ?? ""), "/restore");
}

/**
 * Move the date a closed account's records are destroyed.
 *
 * Both directions: forward is somebody asking to be forgotten sooner,
 * back is a dispute or a legal hold. The date arrives from a date input
 * as `YYYY-MM-DD`, and is sent as the start of that day in this server's
 * zone -- which is what the field means to whoever typed it.
 */
export async function rescheduleErasure(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const day = String(form.get("erase_after") ?? "");
  const at = new Date(`${day}T00:00:00`);

  if (Number.isNaN(at.getTime())) {
    return { error: "That is not a date.", fields: { erase_after: "Pick a date." } };
  }

  return act(workspaceId, "/erase-after", {
    method: "PATCH",
    json: { erase_after: at.toISOString() },
  });
}

/**
 * Ask a colleague to agree to destroying this workspace.
 *
 * The half of the two-person rule this phase owns: raising the request.
 * Agreeing to it is W13's screen, and it has to be somebody else -- which
 * the API checks at the moment the approval is spent, because that is the
 * only moment both people are known.
 */
export async function requestErasureApproval(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  try {
    await raiseApproval({
      action: "erase_workspace",
      subject: workspaceId,
      reason: String(form.get("reason") ?? ""),
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/console/workspaces/${workspaceId}/erase`);

  return { done: true };
}

/**
 * Destroy a workspace and everything it holds, immediately.
 *
 * The most destructive call in the product. Four things stand in front of
 * it and none of them is this client's: the owner rank, the slug typed
 * back, a colleague's approval for *this* workspace, and the audit entry
 * written before the delete rather than after.
 *
 * It answers 204 and there is nothing to come back to, so this leaves for
 * the workspace list rather than re-rendering a page about something that
 * no longer exists.
 */
export async function eraseWorkspaceNow(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  try {
    await adminApi(`/workspaces/${workspaceId}/erase-now`, {
      method: "POST",
      json: {
        confirm_slug: form.get("confirm_slug"),
        approval_id: form.get("approval_id"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/console/workspaces");
  redirect("/console/workspaces?erased=1");
}

// --- a person -----------------------------------------------------------

/**
 * The four things that can be done to an account.
 *
 * None of them destroys anything -- an account turned off can be turned
 * back on, and sessions can be signed in again -- which is why none needs
 * a typed confirmation. They are administrator rank at the API and share
 * one shape here.
 */
async function toUser(userId: string, path: string): Promise<FormState> {
  try {
    await adminApi(`/users/${userId}${path}`, { method: "POST" });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/console/users/${userId}`);
  revalidatePath("/console/users");

  return { done: true };
}

export async function deactivateUser(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  return toUser(String(form.get("user_id") ?? ""), "/deactivate");
}

export async function activateUser(_: FormState, form: FormData): Promise<FormState> {
  return toUser(String(form.get("user_id") ?? ""), "/activate");
}

/**
 * Sign an account out everywhere, without turning it off.
 *
 * The answer to "somebody has my laptop" from a customer who cannot reach
 * their own session list. They can sign straight back in, which is the
 * difference between this and deactivating.
 */
export async function revokeUserSessions(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  return toUser(String(form.get("user_id") ?? ""), "/sessions/revoke");
}

/**
 * Mark an address confirmed, when the mail will not arrive.
 *
 * The narrow case, and worth naming what it is not: a way to confirm
 * addresses for convenience. The point of a verification timestamp is
 * that somebody proved something, and here the proof is a staff member's
 * word — so the entry records whose.
 */
export async function verifyUserEmail(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  return toUser(String(form.get("user_id") ?? ""), "/verify-email");
}
