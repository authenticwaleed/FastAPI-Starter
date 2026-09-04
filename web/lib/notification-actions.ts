"use server";

/**
 * The feed, and the badge.
 *
 * No workspace in any of these paths, and that is the API's design rather
 * than an omission: a notification is addressed to a person, and a person
 * has one feed across every business they work in. Which workspace each one
 * came from is a field on the row.
 */

import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { MarkedRead, Notification } from "@/lib/types";

export type { FormState };

function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return { error: error.sentence, fields: error.fields };
  }

  throw error;
}

/**
 * Mark one read.
 *
 * `revalidatePath` on the layout rather than the page, because the badge in
 * the header is the thing most likely to be looked at next and it lives
 * there. This is what makes the badge clear without the feed being fetched
 * again from scratch.
 */
export async function markRead(_: FormState, form: FormData): Promise<FormState> {
  const id = String(form.get("notification_id") ?? "");

  try {
    await api<Notification>(`/notifications/${id}/read`, { method: "PATCH" });
  } catch (error) {
    // Already gone is not a failure worth a red box: the state the person
    // wanted -- not being told about this any more -- already holds.
    if (error instanceof ApiError && error.code === "notification_not_found") {
      revalidatePath("/", "layout");

      return { done: true };
    }

    return failure(error);
  }

  revalidatePath("/", "layout");

  return { done: true };
}

/**
 * Clear the badge.
 *
 * The count comes back so a client that has been showing a stale number
 * learns it was stale, and so clearing nothing is visibly different from
 * clearing forty.
 */
export async function markAllRead(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = form.get("workspace_id");
  const scope = workspaceId ? `?workspace_id=${workspaceId}` : "";

  let result: MarkedRead;

  try {
    result = await api<MarkedRead>(`/notifications/read-all${scope}`, {
      method: "POST",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/", "layout");

  return { done: true, marked: result.marked_read };
}
