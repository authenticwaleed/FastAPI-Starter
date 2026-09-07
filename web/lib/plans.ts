/**
 * What a workspace may do, and how to say it.
 *
 * Pure, so a client component can import it. The rule below is the one
 * every other screen in this client depends on, and it is short enough to
 * state in a sentence: **gate on `plan`, never on `subscription.plan`.**
 *
 * They disagree routinely and the disagreement is the point. A `past_due`
 * subscription still entitles the full plan while the provider retries; a
 * workspace the platform has comped is entitled to more than it pays for.
 * A client that gated on what is being paid for would take features away
 * from a customer whose card is merely being retried, which is the exact
 * failure the API arranged its response shape to prevent.
 */

import type {
  Feature,
  MetricUsage,
  Plan,
  PlanLimit,
  PlanTier,
  SubscriptionStatus,
  UsageMetric,
  WorkspacePlan,
} from "@/lib/types";

/** Whether this workspace may use a capability right now. */
export function admits(current: WorkspacePlan | null, feature: Feature): boolean {
  return current?.plan.features.includes(feature) ?? false;
}

/** What the plan allows of something. `null` is unlimited, never zero. */
export function ceiling(
  current: WorkspacePlan | null,
  limit: PlanLimit,
): number | null {
  return current?.plan.limits[limit] ?? null;
}

/**
 * The statuses under which a workspace actually gets what it pays for.
 *
 * `past_due` is in here deliberately, matching the API: a card that did
 * not go through is a provider still retrying, and taking a business's
 * features away over a bank's fraud check is the wrong way to lose a
 * customer. What happens instead is that somebody is told.
 */
const ENTITLING: SubscriptionStatus[] = ["active", "trialing", "past_due"];

export function isEntitling(status: SubscriptionStatus): boolean {
  return ENTITLING.includes(status);
}

/**
 * Whether to warn about the subscription, without disabling anything.
 *
 * `past_due` and `unpaid` both want a warning; only the first still
 * entitles. The screens read these separately for that reason.
 */
export function needsAttention(current: WorkspacePlan | null): boolean {
  const status = current?.subscription?.status;

  return status === "past_due" || status === "unpaid";
}

/**
 * Stopping, as distinct from stopped.
 *
 * Cancelling sets `cancel_at_period_end` and leaves the status `active`,
 * because the month has been paid for. A screen that could not tell these
 * apart would say the wrong thing about both.
 */
export function isEnding(current: WorkspacePlan | null): boolean {
  const subscription = current?.subscription;

  return subscription?.cancel_at_period_end === true && subscription.status === "active";
}

export const TIER_ORDER: PlanTier[] = ["starter", "growth", "business"];

export function isUpgradeFrom(from: PlanTier, to: PlanTier): boolean {
  return TIER_ORDER.indexOf(to) > TIER_ORDER.indexOf(from);
}

/**
 * A plan with nothing to pay. Cancelling is how somebody returns to it.
 *
 * Tested against the string rather than parsed, like everything else that
 * touches money here: `"0"`, `"0.00"` and `"0.000"` are all the free plan.
 */
export function isFree(plan: Plan): boolean {
  return /^0(\.0+)?$/.test(plan.price);
}

// --- wording ------------------------------------------------------------

export const FEATURE_LABEL: Record<Feature, string> = {
  automations: "Automations",
  ecommerce: "Storefront sync",
  advanced_analytics: "Advanced analytics",
  api_access: "API access",
  audit_logs: "Audit log",
};

export const LIMIT_LABEL: Record<PlanLimit, string> = {
  whatsapp_numbers: "WhatsApp numbers",
  team_members: "Team members",
  ai_responses_per_month: "Assistant replies a month",
  knowledge_documents: "Knowledge documents",
};

export const METRIC_LABEL: Record<UsageMetric, string> = {
  ai_responses: "Assistant replies",
  ai_tokens: "Assistant tokens",
  whatsapp_messages: "WhatsApp messages",
  active_contacts: "Contacts",
  team_members: "Team members",
  whatsapp_numbers: "WhatsApp numbers",
  knowledge_documents: "Knowledge documents",
  knowledge_tokens: "Knowledge tokens",
};

/** Unlimited, spelled out. A blank cell reads as a missing value. */
export function ceilingLabel(limit: number | null): string {
  return limit === null ? "Unlimited" : limit.toLocaleString();
}

/**
 * How full a meter is, as a percentage, or null where nothing bounds it.
 *
 * Integers, so no float creeps into a number somebody reads. A limit of
 * zero would divide by nothing, so it reads as full rather than as an
 * error.
 */
export function fractionUsed(usage: MetricUsage): number | null {
  if (usage.limit === null) return null;
  if (usage.limit === 0) return 100;

  return Math.min(100, Math.round((usage.quantity / usage.limit) * 100));
}

/** The codes that mean the plan is what is in the way, rather than you. */
const PLAN_CODES = ["feature_not_in_plan", "plan_limit_reached"];

export function isPlanRefusal(code: string | undefined): boolean {
  return code !== undefined && PLAN_CODES.includes(code);
}
