"use server";

/**
 * Creating a workspace, changing one, switching between them, closing one.
 *
 * Three of the four are admin or owner work at the API, and the screens
 * disable what a role cannot do. That is a courtesy and not the
 * enforcement: every one of these still handles its own refusal, because a
 * hidden control is not an enforced one.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { Workspace } from "@/lib/types";
import { clearActiveWorkspace, setActiveWorkspaceId } from "@/lib/workspace";

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

export async function createWorkspace(_: FormState, form: FormData): Promise<FormState> {
  let created: Workspace;

  try {
    created = await api<Workspace>("/workspaces", {
      method: "POST",
      json: {
        name: form.get("name"),
        slug: form.get("slug"),
        timezone: form.get("timezone") || "UTC",
        default_currency: form.get("default_currency") || "USD",
      },
    });
  } catch (error) {
    return failure(error);
  }

  // Switch to it. Somebody who has just made a workspace is looking at it
  // next, and leaving them on the old one is a step they would all take.
  await setActiveWorkspaceId(created.id);

  revalidatePath("/", "layout");
  redirect("/workspaces");
}

export async function updateWorkspace(_: FormState, form: FormData): Promise<FormState> {
  const id = String(form.get("workspace_id") ?? "");

  try {
    await api(`/workspaces/${id}`, {
      method: "PATCH",
      json: {
        name: form.get("name"),
        timezone: form.get("timezone"),
        default_currency: form.get("default_currency"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  // The switcher shows the name, so the shell is stale as well as the form.
  revalidatePath("/", "layout");

  return { done: true };
}

/**
 * Close a workspace.
 *
 * Owner-only, and the API takes no confirmation of any kind -- the typed
 * slug below is this client's caution rather than something the API asked
 * for. It is the workspace's own slug because a confirmation that is the
 * same word every time is one people learn to type without reading.
 *
 * Recoverable by staff for a period rather than final, and the screen says
 * so; overstating it would frighten somebody out of an action they can undo.
 */
export async function closeWorkspace(_: FormState, form: FormData): Promise<FormState> {
  const id = String(form.get("workspace_id") ?? "");
  const slug = String(form.get("slug") ?? "");

  if (form.get("confirm") !== slug) {
    return { error: `Type ${slug} to confirm.`, fields: { confirm: "Does not match." } };
  }

  try {
    await api(`/workspaces/${id}`, { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  // The cookie may still name what was just closed, and `activeWorkspace`
  // would fall back on the next render anyway -- but clearing it here means
  // the fallback is never visible as a flash of the wrong workspace.
  await clearActiveWorkspace();

  revalidatePath("/", "layout");
  redirect("/workspaces");
}

export async function switchWorkspace(form: FormData): Promise<void> {
  const id = String(form.get("workspace_id") ?? "");

  if (id) await setActiveWorkspaceId(id);

  revalidatePath("/", "layout");
}
