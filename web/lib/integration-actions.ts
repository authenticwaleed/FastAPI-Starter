"use server";

/**
 * Connecting and disconnecting the two things this product talks through.
 *
 * Only starting a storefront install is plan-gated at the API, and only it
 * is gated here. Reading, syncing and disconnecting keep working on a plan
 * that has lapsed -- otherwise a downgrade would leave a business unable
 * to disconnect the shop it can no longer use, which is being locked in by
 * your own cancellation.
 */

import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type {
  StorefrontInstall,
  StorefrontProvider,
  SyncReport,
  WhatsAppAccount,
} from "@/lib/types";

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
 * Connect a WhatsApp number.
 *
 * The access token is submitted once and never comes back: no response
 * carries it, encrypted or otherwise. So the form that follows shows
 * connected-or-not and has no token field to pre-fill -- there is nothing
 * to pre-fill it with, which is the point.
 */
export async function connectWhatsApp(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  try {
    await api<WhatsAppAccount>(
      `/workspaces/${workspaceId}/integrations/whatsapp/connect`,
      {
        method: "POST",
        json: {
          phone_number: form.get("phone_number"),
          external_phone_number_id: form.get("external_phone_number_id"),
          access_token: form.get("access_token"),
          external_business_account_id:
            String(form.get("external_business_account_id") ?? "").trim() || null,
        },
      },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/integrations");

  return { done: true };
}

export async function disconnectWhatsApp(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  if (form.get("confirm") !== form.get("phone_number")) {
    return { error: "Type the number to confirm." };
  }

  try {
    await api(`/workspaces/${workspaceId}/integrations/whatsapp`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/integrations");

  return { done: true };
}

/**
 * Start a storefront install.
 *
 * Nothing is connected when this returns. It answers with a URL at the
 * provider, the shop owner approves the app there, and the provider calls
 * back -- so this hands the URL to the screen, which navigates away.
 */
export async function beginInstall(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const provider = String(form.get("provider") ?? "") as StorefrontProvider;

  let install: StorefrontInstall;

  try {
    install = await api<StorefrontInstall>(
      `/workspaces/${workspaceId}/integrations/${provider}/install`,
      { method: "POST", json: { shop_domain: form.get("shop_domain") } },
    );
  } catch (error) {
    return failure(error);
  }

  return { done: true, checkoutUrl: install.authorize_url };
}

/**
 * Read the shop again.
 *
 * Not plan-gated, deliberately: a lapsed plan can still pull its own
 * catalogue across. The report's `skipped` is the interesting number --
 * records the shop sent that were already as new here, which is what a
 * retry looks like from the inside.
 */
export async function syncStorefront(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const provider = String(form.get("provider") ?? "") as StorefrontProvider;

  let report: SyncReport;

  try {
    report = await api<SyncReport>(
      `/workspaces/${workspaceId}/integrations/${provider}/sync`,
      { method: "POST" },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/integrations");
  revalidatePath("/products");
  revalidatePath("/orders");

  return { done: true, sync: report };
}

/**
 * Disconnect a storefront.
 *
 * What was already synced stays. A business that disconnects a shop has
 * not asked to lose its own catalogue, and the API keeps the rows for
 * exactly that reason -- the screen says so before the button.
 */
export async function disconnectStorefront(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const provider = String(form.get("provider") ?? "") as StorefrontProvider;

  if (form.get("confirm") !== form.get("shop_domain")) {
    return { error: "Type the shop's domain to confirm." };
  }

  try {
    await api(`/workspaces/${workspaceId}/integrations/${provider}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/integrations");

  return { done: true };
}
