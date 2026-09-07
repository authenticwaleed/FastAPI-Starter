/**
 * The three automations, described in the words a business would use.
 *
 * Pure, so a client component can import it. This is a settings form and
 * not a workflow builder -- the API is explicit about that -- so what
 * lives here is one entry per predefined automation rather than anything
 * that could describe a new one.
 *
 * The defaults mirror the settings models in `app/services/automations.py`.
 * They are only what a form shows before anybody types: sending an empty
 * definition takes every default at the API, which is the value that
 * actually applies.
 */

import type {
  AutomationKind,
  AutomationStatus,
  AutomationTrigger,
  RunStatus,
} from "@/lib/types";

export type AutomationSpec = {
  kind: AutomationKind;
  name: string;
  /** What it does, for somebody deciding whether to switch it on. */
  summary: string;
  /** When it is considered, in words rather than the enum. */
  when: string;
};

export const AUTOMATIONS: AutomationSpec[] = [
  {
    kind: "order_confirmation",
    name: "Order confirmation",
    summary:
      "Messages the customer when an order is recorded, so nobody has to remember to.",
    when: "When an order arrives",
  },
  {
    kind: "human_handoff",
    name: "Hand over to a person",
    summary:
      "Watches for somebody asking for a human — angry, or the word refund — and takes the thread off the assistant.",
    when: "When a customer writes in",
  },
  {
    kind: "unanswered_lead_followup",
    name: "Follow up an unanswered lead",
    summary:
      "Nudges a customer nobody ever replied to. Once per conversation, ever — not once per sweep.",
    when: "On a schedule",
  },
];

export function specFor(kind: AutomationKind): AutomationSpec {
  return AUTOMATIONS.find((spec) => spec.kind === kind) ?? AUTOMATIONS[0];
}

export const TRIGGER_LABEL: Record<AutomationTrigger, string> = {
  message_received: "When a customer writes in",
  order_created: "When an order arrives",
  schedule: "On a schedule",
};

export const STATUS_LABEL: Record<AutomationStatus, string> = {
  enabled: "On",
  disabled: "Off",
};

/**
 * What a run outcome means.
 *
 * `skipped` is deliberately not coloured as a problem. An automation is
 * considered on every matching event and most events are not the one it is
 * for, so a history where those read as failures is a history nobody
 * trusts.
 */
export const RUN_LABEL: Record<RunStatus, { label: string; tone: "ok" | "quiet" | "bad" }> =
  {
    running: { label: "Running", tone: "quiet" },
    succeeded: { label: "Did something", tone: "ok" },
    skipped: { label: "Not for this one", tone: "quiet" },
    failed: { label: "Failed", tone: "bad" },
  };

// --- the settings each automation takes ---------------------------------

export type OrderConfirmationSettings = { template: string };
export type HumanHandoffSettings = {
  keywords: string[];
  acknowledgement: string | null;
};
export type UnansweredLeadSettings = { after_hours: number; template: string };

export const DEFAULTS = {
  order_confirmation: {
    template:
      "Thanks for your order {order_number}! We have received it and will let you know when it ships.",
  },
  human_handoff: {
    keywords: [
      "agent",
      "human",
      "person",
      "manager",
      "complaint",
      "refund",
      "cancel my order",
      "speak to someone",
    ],
    acknowledgement: "One moment -- I am getting a colleague to help you.",
  },
  unanswered_lead_followup: {
    after_hours: 24,
    template:
      "Hi{name}, sorry for the wait -- are you still looking for help? We are here whenever you need us.",
  },
} as const;

/**
 * The placeholders a template may use.
 *
 * A fixed list rather than an expression language, which is the same
 * decision the API makes about workflows: a business writes a sentence,
 * not a program. Shown beside the field so nobody has to guess.
 */
export const PLACEHOLDERS: Partial<Record<AutomationKind, string[]>> = {
  order_confirmation: ["{order_number}"],
  unanswered_lead_followup: ["{name}"],
};

/** Read a setting off a definition without trusting its shape. */
export function settingString(
  definition: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const value = definition[key];

  return typeof value === "string" ? value : fallback;
}

export function settingNumber(
  definition: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const value = definition[key];

  return typeof value === "number" ? value : fallback;
}

export function settingList(
  definition: Record<string, unknown>,
  key: string,
  fallback: string[],
): string[] {
  const value = definition[key];

  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? (value as string[])
    : fallback;
}
