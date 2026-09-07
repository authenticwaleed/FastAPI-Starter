"use server";

/**
 * Taking and updating orders.
 *
 * Agent work rather than admin, and the API is right about that: taking an
 * order is customer work, done by whoever is talking to the customer.
 *
 * Every amount travels as the string it was typed as. See `lib/money.ts`
 * for why nothing here parses one.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { Order } from "@/lib/types";

export type { FormState };

function failure(error: unknown, orderId?: string): FormState {
  if (!(error instanceof ApiError)) throw error;

  if (error.code === "order_not_confirmable") {
    // Somebody else moved first. The view is stale rather than wrong, so
    // it is refetched and the sentence is a statement, not a complaint.
    if (orderId) revalidatePath(`/orders/${orderId}`);

    return { error: error.sentence, code: error.code, stale: true };
  }

  return {
    error: error.sentence,
    code: error.code,
    fields: error.fields,
    retryAfter: error.retryAfter ?? undefined,
  };
}

function optional(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();

  return value === "" ? null : value;
}

export async function createOrder(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let order: Order;

  try {
    order = await api<Order>(`/workspaces/${workspaceId}/orders`, {
      method: "POST",
      json: {
        contact_id: form.get("contact_id"),
        status: form.get("status") || "pending",
        order_number: optional(form, "order_number"),
        currency: optional(form, "currency"),
        subtotal: optional(form, "subtotal"),
        shipping_total: optional(form, "shipping_total"),
        total: optional(form, "total"),
        shipping_address: optional(form, "shipping_address"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/orders");
  redirect(`/orders/${order.id}`);
}

/**
 * Record what changed about an order.
 *
 * The contact is not among the fields, and that is the API's shape rather
 * than an omission here: moving an order to a different customer is not an
 * edit, it is a correction of who it was ever for, and doing that through
 * a PATCH nobody notices is how one person ends up able to ask about
 * another person's order.
 */
export async function updateOrder(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const orderId = String(form.get("order_id") ?? "");

  try {
    await api<Order>(`/workspaces/${workspaceId}/orders/${orderId}`, {
      method: "PATCH",
      json: {
        status: form.get("status"),
        order_number: optional(form, "order_number"),
        currency: optional(form, "currency"),
        subtotal: optional(form, "subtotal"),
        shipping_total: optional(form, "shipping_total"),
        total: optional(form, "total"),
        shipping_address: optional(form, "shipping_address"),
        tracking_number: optional(form, "tracking_number"),
        tracking_url: optional(form, "tracking_url"),
      },
    });
  } catch (error) {
    return failure(error, orderId);
  }

  revalidatePath(`/orders/${orderId}`);
  revalidatePath("/orders");

  return { done: true };
}

/**
 * Confirm a pending order.
 *
 * Its own endpoint rather than a PATCH setting the status, because it is
 * the one status change that records a decision rather than an
 * observation. Anything not pending is refused -- confirming is a step
 * forward, not a way to undo a cancellation -- so pressing it twice is
 * safe and says what happened.
 */
export async function confirmOrder(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const orderId = String(form.get("order_id") ?? "");

  try {
    await api<Order>(`/workspaces/${workspaceId}/orders/${orderId}/confirm`, {
      method: "POST",
    });
  } catch (error) {
    return failure(error, orderId);
  }

  revalidatePath(`/orders/${orderId}`);
  revalidatePath("/orders");

  return { done: true };
}
