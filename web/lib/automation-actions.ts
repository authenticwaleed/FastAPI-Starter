"use server";

/**
 * Switching automations on, configuring them, and switching them off.
 *
 * Only creating is plan-gated at the API, and only creating is gated here.
 * A workspace whose plan has lapsed keeps being able to read, disable and
 * delete the automations it already has -- which is the difference between
 * losing a feature and being locked in by one.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { Automation, AutomationKind, SweepReport } from "@/lib/types";

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
 * Switch one on with its defaults.
 *
 * An empty definition takes every default at the API, which is where the
 * defaults actually live. Sending the ones this client knows about would
 * mean two copies that drift, and the copy that loses is the one a
 * business is looking at.
 */
export async function createAutomation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const kind = String(form.get("kind") ?? "") as AutomationKind;

  let automation: Automation;

  try {
    automation = await api<Automation>(`/workspaces/${workspaceId}/automations`, {
      method: "POST",
      json: { kind, definition: {} },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/automations");
  redirect(`/automations/${automation.id}`);
}

/**
 * Change the settings, the name, or whether it runs.
 *
 * `422 invalid_automation_settings` comes back with per-field detail,
 * which is why this carries the fields through: those settings belong to
 * one automation, and a page-level message would leave somebody hunting
 * for which box was wrong.
 */
export async function updateAutomation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const automationId = String(form.get("automation_id") ?? "");
  const kind = String(form.get("kind") ?? "") as AutomationKind;

  const definition = definitionFrom(kind, form);
  const name = String(form.get("name") ?? "").trim();

  try {
    await api<Automation>(
      `/workspaces/${workspaceId}/automations/${automationId}`,
      {
        method: "PATCH",
        json: {
          ...(name ? { name } : {}),
          ...(form.has("status") ? { status: form.get("status") } : {}),
          ...(definition ? { definition } : {}),
        },
      },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/automations/${automationId}`);
  revalidatePath("/automations");

  return { done: true };
}

/** Turn one on or off without opening it. */
export async function setAutomationStatus(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const automationId = String(form.get("automation_id") ?? "");

  try {
    await api<Automation>(
      `/workspaces/${workspaceId}/automations/${automationId}`,
      { method: "PATCH", json: { status: form.get("status") } },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/automations");
  revalidatePath(`/automations/${automationId}`);

  return { done: true };
}

export async function deleteAutomation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const automationId = String(form.get("automation_id") ?? "");

  try {
    await api(`/workspaces/${workspaceId}/automations/${automationId}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/automations");
  redirect("/automations");
}

/**
 * Run whatever is due, now.
 *
 * The one automation nothing fires is the unanswered-lead follow-up: it is
 * about an event *failing* to happen, so it is found by a sweep. A
 * scheduler will call this eventually; until then it is a button, and the
 * report says how much work it looked at and correctly left alone.
 */
export async function runDue(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let report: SweepReport;

  try {
    report = await api<SweepReport>(
      `/workspaces/${workspaceId}/automations/run-due`,
      { method: "POST" },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/automations");

  return { done: true, sweep: report };
}

/** The settings for one kind, read off the form it was submitted from. */
function definitionFrom(
  kind: AutomationKind,
  form: FormData,
): Record<string, unknown> | null {
  if (kind === "order_confirmation") {
    return { template: form.get("template") };
  }

  if (kind === "human_handoff") {
    const acknowledgement = String(form.get("acknowledgement") ?? "").trim();

    return {
      // One per line is what a person can read and edit, which is the
      // whole reason this is a keyword list rather than a model.
      keywords: String(form.get("keywords") ?? "")
        .split("\n")
        .map((word) => word.trim())
        .filter(Boolean),
      // Empty means say nothing, which the API takes as null. A business
      // whose agents answer within a minute may prefer silence.
      acknowledgement: acknowledgement === "" ? null : acknowledgement,
    };
  }

  if (kind === "unanswered_lead_followup") {
    return {
      after_hours: Number(form.get("after_hours")),
      template: form.get("template"),
    };
  }

  return null;
}
