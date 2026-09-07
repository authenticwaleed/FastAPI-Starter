"use server";

/**
 * Sending, withdrawing and answering an invitation.
 *
 * The API does not email these. It returns the token once, in the response
 * to creating one, and never again -- what is stored is a digest, so it
 * cannot be produced a second time. That is why `inviteMember` hands the
 * token back to the screen: showing the link is currently the only way it
 * reaches anybody, and pretending otherwise would leave invitations that
 * nobody can accept.
 *
 * When the API grows a sender this should stop returning the token, and
 * the screen that copies it should go with it.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { InvitationCreated, Workspace, WorkspaceRole } from "@/lib/types";
import { setActiveWorkspaceId } from "@/lib/workspace";

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

export async function inviteMember(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let created: InvitationCreated;

  try {
    created = await api<InvitationCreated>(
      `/workspaces/${workspaceId}/invitations`,
      {
        method: "POST",
        json: {
          email: form.get("email"),
          role: String(form.get("role") ?? "agent") as WorkspaceRole,
        },
      },
    );
  } catch (error) {
    // The form keeps what was typed on a 409 -- already invited, already a
    // member -- because the next thing somebody does is change one field
    // rather than start again.
    return failure(error);
  }

  revalidatePath(`/workspaces/${workspaceId}/team`);

  return { done: true, invitation: created };
}

export async function revokeInvitation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const invitationId = String(form.get("invitation_id") ?? "");

  try {
    await api(`/workspaces/${workspaceId}/invitations/${invitationId}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/workspaces/${workspaceId}/team`);

  return { done: true };
}

/**
 * Take the seat.
 *
 * Needs an account, because a membership has to belong to somebody, and
 * the invitation only admits the address it was sent to. Somebody arriving
 * without an account registers first and comes back to the link.
 */
export async function acceptInvitation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const token = String(form.get("token") ?? "");

  let workspace: Workspace;

  try {
    workspace = await api<Workspace>(`/invitations/${token}/accept`, {
      method: "POST",
    });
  } catch (error) {
    return failure(error);
  }

  // Straight into the workspace just joined. Landing on somebody else's
  // workspace after accepting an invitation to this one is a step every
  // single person would then take by hand.
  await setActiveWorkspaceId(workspace.id);

  revalidatePath("/", "layout");
  redirect("/");
}
