"use server";

/**
 * Starting a checkout, and stopping a subscription.
 *
 * Neither of these decides anything about billing. The provider owns
 * whether a subscription is current; a checkout begins one there and a
 * webhook brings the answer back, which is why the first returns a URL
 * rather than a subscription.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { CheckoutStarted, Subscription } from "@/lib/types";

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
 * Somewhere to send somebody to pay.
 *
 * Nothing changes here, and that is the design rather than a limitation:
 * the card is entered on the provider's own page, and what makes a
 * subscription real is the webhook that follows. So this redirects out of
 * the application entirely and the return screen waits to be told.
 *
 * `502 billing_provider_error` is the provider, not the customer -- an
 * unconfigured price, or a provider that could not be reached. The screen
 * offers a retry rather than a support link, because the second is a dead
 * end for something that is usually momentary.
 */
export async function startCheckout(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const plan = String(form.get("plan") ?? "");

  let checkout: CheckoutStarted;

  try {
    checkout = await api<CheckoutStarted>(
      `/workspaces/${workspaceId}/subscription/checkout`,
      { method: "POST", json: { plan } },
    );
  } catch (error) {
    return failure(error);
  }

  // Out of this application. `redirect` refuses an absolute URL to another
  // origin in some Next configurations, so the screen is handed the URL
  // and navigates itself.
  return { done: true, checkoutUrl: checkout.checkout_url };
}

/**
 * Stop at the end of the period that has been paid for.
 *
 * Not immediately: somebody who has paid for a month is entitled to the
 * month, so the API sets the subscription to end rather than ending it,
 * and everything keeps working until it does. The provider is told rather
 * than asked, and what comes back is applied straight away, so the screen
 * does not have to wait for a webhook to show the right thing.
 */
export async function cancelSubscription(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  if (form.get("confirm") !== "CANCEL") {
    return { error: "Type CANCEL to confirm." };
  }

  try {
    await api<Subscription>(`/workspaces/${workspaceId}/subscription/cancel`, {
      method: "POST",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/billing");
  revalidatePath("/", "layout");

  return { done: true };
}

/** Re-read the subscription after coming back from the provider's page. */
export async function refreshSubscription(): Promise<void> {
  revalidatePath("/billing");
  revalidatePath("/billing/done");
  revalidatePath("/", "layout");

  redirect("/billing");
}
