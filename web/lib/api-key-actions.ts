"use server";

/**
 * Making and revoking the credentials a customer's own software uses.
 *
 * Creating is plan-gated at the API; listing and revoking are not, and
 * that asymmetry is deliberate on both sides. A workspace that drops off
 * the plan which included API access must still be able to revoke a key it
 * can no longer create — otherwise a downgrade leaves live credentials
 * nobody can turn off.
 */

import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";

export type { FormState };

function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return {
      error: error.sentence,
      code: error.code,
      fields: error.fields,
      retryAfter: error.retryAfter ?? undefined,
    };
  }

  throw error;
}

/**
 * Make a key, and hand it back exactly once.
 *
 * Nothing stored can reproduce it, so this response is the only chance to
 * put it anywhere. The screen shows it and will not clear it until
 * somebody says they have it.
 */
export async function createApiKey(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const days = String(form.get("expires_in_days") ?? "").trim();

  let created: ApiKeyCreated;

  try {
    created = await api<ApiKeyCreated>(`/workspaces/${workspaceId}/api-keys`, {
      method: "POST",
      json: {
        name: form.get("name"),
        // Empty means it does not expire, which the API takes as null. A
        // key that stops working on a date nobody remembers choosing is
        // an outage in a customer's system, so the choice stays theirs.
        expires_in_days: days === "" ? null : Number(days),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/api-keys");

  return { done: true, apiKey: created };
}

export async function revokeApiKey(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const keyId = String(form.get("key_id") ?? "");

  if (form.get("confirm") !== form.get("key_prefix")) {
    return { error: "Type the key's prefix to confirm." };
  }

  try {
    await api<ApiKey>(`/workspaces/${workspaceId}/api-keys/${keyId}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/api-keys");

  return { done: true };
}
