"use server";

/**
 * Who runs this platform, and the record of every change to that.
 *
 * Owner-only, all three of them, and that is the line the surface is built
 * around: granting is the one act that creates more of this surface, and
 * an admin who could promote themselves would make the ranks decorative.
 *
 * Staff are ordinary accounts that have been promoted, so there is no
 * endpoint here that creates a user and none that sets a password. What
 * these do is add a row beside an account that already exists.
 */

import { revalidatePath } from "next/cache";

import { raiseApproval } from "@/lib/approvals";
import { adminApi } from "@/lib/console-api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";

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

function staffScreens(userId: string): string[] {
  return ["/console/staff", `/console/users/${userId}`];
}

/**
 * Give an existing account access to the platform.
 *
 * Granting `owner` needs a second staff member's agreement and answers
 * `403 approval_required` without one; the screen raises the request and
 * shows it waiting. Only `owner`: an owner can promote anybody and erase
 * any business, and requiring a colleague for every support engineer
 * would mean nobody could be added on a Friday.
 *
 * Re-granting to somebody whose access was revoked reinstates their row
 * rather than adding a second one, so a colleague who left and came back
 * has one history rather than two that have to be read together.
 */
export async function grantStaffAccess(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const userId = String(form.get("user_id") ?? "");
  const approvalId = form.get("approval_id");

  try {
    await adminApi("/staff", {
      method: "POST",
      json: {
        user_id: Number(userId),
        role: form.get("role"),
        // Sent only when there is one. The API asks for it at `owner` and
        // ignores it below that, so an absent field is the ordinary shape
        // of an ordinary promotion rather than something missing.
        ...(approvalId ? { approval_id: approvalId } : {}),
      },
    });
  } catch (error) {
    return failure(error);
  }

  for (const screen of staffScreens(userId)) revalidatePath(screen);

  return { done: true };
}

/**
 * Ask a colleague to agree to an owner promotion.
 *
 * The rank travels with the request, because the API checks it when the
 * approval is spent: an agreement given for `admin` cannot be used to
 * grant `owner`, which would defeat the only promotion this guards.
 */
export async function requestOwnerApproval(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const userId = String(form.get("user_id") ?? "");

  try {
    await raiseApproval({
      action: "grant_staff_owner",
      subject: userId,
      reason: String(form.get("reason") ?? ""),
      role: "owner",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/console/staff");

  return { done: true };
}

/**
 * Move a colleague up or down the ladder.
 *
 * Refused if it would leave the platform with no live owner, including
 * when the person doing it is that owner: only an owner may grant access,
 * so a platform without one is a console nobody can be added to again
 * without a database client.
 */
export async function changeStaffRole(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const userId = String(form.get("user_id") ?? "");

  try {
    await adminApi(`/staff/${userId}`, {
      method: "PATCH",
      json: { role: form.get("role") },
    });
  } catch (error) {
    return failure(error);
  }

  for (const screen of staffScreens(userId)) revalidatePath(screen);

  return { done: true };
}

/**
 * Take somebody's platform access away.
 *
 * Their sessions are left alone, deliberately: a staff member is an
 * ordinary account with ordinary workspaces, and signing them out of a
 * customer's inbox because they no longer run the platform would be this
 * surface reaching into the tenant one.
 */
export async function revokeStaffAccess(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const userId = String(form.get("user_id") ?? "");

  try {
    await adminApi(`/staff/${userId}`, { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  for (const screen of staffScreens(userId)) revalidatePath(screen);

  return { done: true };
}
