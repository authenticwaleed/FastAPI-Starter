"use server";

/**
 * Changing what somebody may do, and taking them off the team.
 *
 * Removing is one endpoint doing two things, and the API is right to make
 * it one: leaving needs no rank, because anybody may walk out of a
 * workspace they are in, while removing somebody else needs the admin role
 * and a rank above theirs. The screens say which of the two a button is.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { Member, WorkspaceRole } from "@/lib/types";
import { clearActiveWorkspace } from "@/lib/workspace";

export type { FormState };

function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return {
      error: error.sentence,
      fields: error.fields,
      retryAfter: error.retryAfter ?? undefined,
    };
  }

  throw error;
}

function teamPath(workspaceId: string): string {
  return `/workspaces/${workspaceId}/team`;
}

export async function changeMemberRole(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const userId = String(form.get("user_id") ?? "");
  const role = String(form.get("role") ?? "") as WorkspaceRole;

  try {
    await api<Member>(`/workspaces/${workspaceId}/members/${userId}`, {
      method: "PATCH",
      json: { role },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(teamPath(workspaceId));

  return { done: true };
}

/**
 * Take somebody off the team.
 *
 * The row is kept and marked removed rather than deleted, so re-adding a
 * former colleague restores the membership they had instead of colliding
 * with it. Nothing here has to know that; it is why the API answers the
 * way it does when somebody comes back.
 */
export async function removeMember(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const userId = String(form.get("user_id") ?? "");

  try {
    await api(`/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(teamPath(workspaceId));

  return { done: true };
}

/**
 * Leave a workspace.
 *
 * The same endpoint as removing somebody, aimed at yourself, and a
 * separate action because what follows is different: there is no team page
 * to go back to afterwards. The cookie is cleared so the switcher does not
 * keep pointing at a workspace that now answers 404.
 *
 * `409 last_owner` is the refusal to expect, and it is an instruction
 * rather than a wall -- hand ownership over first.
 */
export async function leaveWorkspace(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const userId = String(form.get("user_id") ?? "");

  if (form.get("confirm") !== "LEAVE") {
    return { error: "Type LEAVE to confirm." };
  }

  try {
    await api(`/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  await clearActiveWorkspace();

  revalidatePath("/", "layout");
  redirect("/workspaces");
}
