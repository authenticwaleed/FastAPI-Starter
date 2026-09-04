"use server";

/**
 * The account looking at itself: name, address, password, sessions.
 *
 * None of these take an id. The API resolves "me" from the token, so there
 * is no way to aim one of these at somebody else and no id for a client to
 * get wrong.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { clearSession } from "@/lib/session";
import { clearActiveWorkspace } from "@/lib/workspace";
import type { FormState } from "@/lib/form-state";

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

export async function updateAccount(_: FormState, form: FormData): Promise<FormState> {
  try {
    await api("/account", {
      method: "PATCH",
      json: { name: form.get("name"), email: form.get("email") },
    });
  } catch (error) {
    return failure(error);
  }

  // The header carries the name, so the shell has to be re-rendered too --
  // and changing the address clears its confirmation, which is the banner's
  // whole condition.
  revalidatePath("/", "layout");

  return { done: true };
}

/**
 * Change the password, and keep this device signed in.
 *
 * The API ends every *other* session, which is what makes this useful
 * after a scare. This one survives, so there is nothing to clean up here --
 * and a client that signed itself out afterwards would be undoing the one
 * thing the API deliberately preserved.
 */
export async function changePassword(_: FormState, form: FormData): Promise<FormState> {
  try {
    await api("/account/change-password", {
      method: "POST",
      json: {
        current_password: form.get("current_password"),
        new_password: form.get("new_password"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/account");

  return { done: true };
}

/**
 * Sign out one device.
 *
 * Ending the current session is allowed and is a sign-out, not an error.
 * The API cannot know which one a client considers "here", so the client
 * has to notice and clear its own cookies.
 */
export async function revokeSession(_: FormState, form: FormData): Promise<FormState> {
  const id = String(form.get("session_id") ?? "");
  const isCurrent = form.get("current") === "1";

  try {
    await api(`/account/sessions/${id}`, { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  if (isCurrent) {
    await clearSession();
    redirect("/sign-in");
  }

  revalidatePath("/account");

  return { done: true };
}

/**
 * Sign out everywhere, this device included.
 *
 * The API is explicit that "everywhere" contains the caller, so this always
 * ends with the cookies cleared. The access token in hand keeps working for
 * minutes; every refresh chain is gone before this returns.
 */
export async function revokeAllSessions(): Promise<void> {
  try {
    await api("/account/sessions", { method: "DELETE" });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
  }

  await clearSession();
  await clearActiveWorkspace();

  redirect("/sign-in");
}

/**
 * Close the account.
 *
 * No password. The API asks for none, and a client that demanded one would
 * be inventing a rule -- which is the thing the plan's section 7 asks it not
 * to do. What stands in for it is a typed confirmation on the screen, which
 * is this client's own caution and does not pretend to be authentication.
 *
 * The refusal worth handling is `workspace_ownership_required`: somebody who
 * is the last owner of a workspace has to deal with that first.
 */
export async function deleteAccount(_: FormState, form: FormData): Promise<FormState> {
  if (form.get("confirm") !== "DELETE") {
    return { error: "Type DELETE to confirm." };
  }

  try {
    await api("/account", { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  await clearSession();
  await clearActiveWorkspace();

  redirect("/sign-in");
}
