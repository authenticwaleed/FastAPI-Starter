"use server";

/**
 * The five things W13 can change.
 *
 * Two of them touch a customer: a granted plan outranks whatever the
 * provider says, and retrying a job re-sends somebody's message. Two are
 * about this platform's own machinery. The last is agreeing to a
 * colleague's request, which closes the loop W12 opens.
 *
 * None of them writes into a business's own data, which is still true of
 * the whole platform surface.
 */

import { revalidatePath } from "next/cache";

import { adminApi } from "@/lib/console-api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { PlanOverride, ReplayResult } from "@/lib/types";

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

/**
 * Apply a stored delivery again.
 *
 * Safe to press twice: what gets applied is the provider's own snapshot,
 * so applying it again lands on the same values. `applied: false` means
 * there was nothing to do — a delivery from before payloads were kept, or
 * one naming a subscription this platform does not hold — and the screen
 * says so rather than colouring it as a failure.
 *
 * An unknown event id answers `502 billing_provider_error` today where
 * the schema advertises a `404`. This matches on the code and works
 * correctly either way; it does not pretend the schema is right, and a
 * fix upstream should make this comment the only thing to delete.
 */
export async function replayBillingEvent(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const eventId = String(form.get("event_id") ?? "");

  try {
    const result = await adminApi<ReplayResult>(
      `/billing/events/${eventId}/replay`,
      { method: "POST" },
    );

    revalidatePath("/console/billing/events");

    return { done: true, applied: result.applied };
  } catch (error) {
    return failure(error);
  }
}

/**
 * Put a workspace on a plan nobody is paying for.
 *
 * A pilot, a comp, an enterprise contract invoiced offline. Leaving the
 * date out is allowed and comes back `forever: true`, which the screen
 * renders as a warning rather than a refusal — the API's own intent, and
 * the honest compromise: a comp somebody negotiated has no natural end,
 * so requiring a date would mean inventing one.
 */
export async function grantPlanOverride(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const day = String(form.get("expires_at") ?? "");

  let expiresAt: string | null = null;

  if (day) {
    const at = new Date(`${day}T00:00:00`);

    if (Number.isNaN(at.getTime())) {
      return { error: "That is not a date.", fields: { expires_at: "Pick a date." } };
    }

    expiresAt = at.toISOString();
  }

  try {
    const override = await adminApi<PlanOverride>(
      `/workspaces/${workspaceId}/plan-override`,
      {
        method: "POST",
        json: {
          plan: form.get("plan"),
          reason: form.get("reason"),
          expires_at: expiresAt,
        },
      },
    );

    revalidatePath(`/console/workspaces/${workspaceId}/subscription`);
    revalidatePath(`/console/workspaces/${workspaceId}`);

    return { done: true, override };
  } catch (error) {
    return failure(error);
  }
}

/**
 * Take a granted plan away, so the provider's word applies again.
 *
 * Falls back rather than down: a workspace with a live subscription
 * returns to whatever the provider last said, and one without returns to
 * free. Always 204 — removing a grant nobody made is not an error, since
 * the state somebody wanted already holds.
 */
export async function removePlanOverride(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  try {
    await adminApi(`/workspaces/${workspaceId}/plan-override`, { method: "DELETE" });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/console/workspaces/${workspaceId}/subscription`);
  revalidatePath(`/console/workspaces/${workspaceId}`);

  return { done: true };
}

/**
 * Put a job back in the queue, or stop one that has not started.
 *
 * Both answer with the job, so the screen shows what it became rather
 * than assuming. Both are refused while it is running: the worker holding
 * that row does not check back, and moving it would let a second worker
 * claim the same work and race the first.
 */
async function moveJob(jobId: string, path: string): Promise<FormState> {
  try {
    await adminApi(`/jobs/${jobId}${path}`, { method: "POST" });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/console/jobs/${jobId}`);
  revalidatePath("/console/jobs");

  return { done: true };
}

export async function retryJob(_: FormState, form: FormData): Promise<FormState> {
  return moveJob(String(form.get("job_id") ?? ""), "/retry");
}

export async function cancelJob(_: FormState, form: FormData): Promise<FormState> {
  return moveJob(String(form.get("job_id") ?? ""), "/cancel");
}

/**
 * Agree to somebody else's request.
 *
 * Refused on your own, which is the control rather than a formality: an
 * approval you raised and agreed to yourself is a form with extra steps.
 * Agreeing is not performing — whoever spends it must be somebody other
 * than you, so the ordinary shape is that a colleague asks, you agree,
 * and they act.
 */
export async function approveRequest(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const approvalId = String(form.get("approval_id") ?? "");

  try {
    await adminApi(`/approvals/${approvalId}/approve`, { method: "POST" });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/console/approvals");

  return { done: true };
}
