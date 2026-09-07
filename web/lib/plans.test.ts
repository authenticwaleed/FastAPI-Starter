import { describe, expect, it } from "vitest";

import {
  admits,
  ceiling,
  ceilingLabel,
  fractionUsed,
  isEnding,
  isEntitling,
  isFree,
  isPlanRefusal,
  needsAttention,
} from "@/lib/plans";
import type { Plan, Subscription, WorkspacePlan } from "@/lib/types";

/**
 * The rule this phase exists to get right: gate on what applies, never on
 * what is being paid for.
 */

const GROWTH: Plan = {
  tier: "growth",
  name: "Growth",
  description: "A team, a storefront, and automations.",
  price: "49",
  currency: "USD",
  features: ["automations", "ecommerce", "advanced_analytics"],
  limits: {
    whatsapp_numbers: 3,
    team_members: 10,
    ai_responses_per_month: 10_000,
    knowledge_documents: 500,
  },
};

const BUSINESS: Plan = {
  ...GROWTH,
  tier: "business",
  name: "Business",
  price: "199",
  features: [
    "automations",
    "ecommerce",
    "advanced_analytics",
    "api_access",
    "audit_logs",
  ],
  limits: {
    whatsapp_numbers: null,
    team_members: null,
    ai_responses_per_month: 100_000,
    knowledge_documents: null,
  },
};

function subscription(over: Partial<Subscription> = {}): Subscription {
  return {
    id: "s1",
    provider: "stripe",
    plan: "starter",
    status: "active",
    current_period_start: null,
    current_period_end: null,
    cancel_at_period_end: false,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

describe("what applies, versus what is paid for", () => {
  it("entitles the plan while a card is only being retried", () => {
    // The failure this whole shape exists to prevent: a `past_due`
    // subscription still gets its plan while the provider retries, so a
    // screen gating on the subscription would take features away over a
    // bank's fraud check.
    const current: WorkspacePlan = {
      plan: GROWTH,
      subscription: subscription({ plan: "growth", status: "past_due" }),
    };

    expect(admits(current, "automations")).toBe(true);
    expect(isEntitling("past_due")).toBe(true);
    // And it is still worth telling somebody.
    expect(needsAttention(current)).toBe(true);
  });

  it("entitles a comped plan the provider knows nothing about", () => {
    // A platform override outranks the provider, so `plan` says Business
    // while `subscription.plan` says starter. Gating on the subscription
    // would refuse a feature the customer was given.
    const current: WorkspacePlan = {
      plan: BUSINESS,
      subscription: subscription({ plan: "starter", status: "active" }),
    };

    expect(admits(current, "api_access")).toBe(true);
  });

  it("entitles a workspace that has never paid at all", () => {
    const current: WorkspacePlan = { plan: GROWTH, subscription: null };

    expect(admits(current, "ecommerce")).toBe(true);
    // Null is "has never paid", which is not "payment failed".
    expect(needsAttention(current)).toBe(false);
  });

  it("does not entitle a status the provider has given up on", () => {
    expect(isEntitling("unpaid")).toBe(false);
    expect(isEntitling("canceled")).toBe(false);
    expect(isEntitling("incomplete")).toBe(false);
  });

  it("admits nothing when the plan is not known yet", () => {
    // Assume nothing rather than everything: a control wrongly disabled is
    // a nuisance, one wrongly enabled is a refusal in somebody's face.
    expect(admits(null, "automations")).toBe(false);
  });
});

describe("stopping, versus stopped", () => {
  it("is ending while the paid-for period is still running", () => {
    const current: WorkspacePlan = {
      plan: GROWTH,
      subscription: subscription({ status: "active", cancel_at_period_end: true }),
    };

    expect(isEnding(current)).toBe(true);
    // Still entitling: they paid for the month and are entitled to it.
    expect(admits(current, "automations")).toBe(true);
  });

  it("is not ending once it has actually ended", () => {
    const current: WorkspacePlan = {
      plan: GROWTH,
      subscription: subscription({ status: "canceled", cancel_at_period_end: true }),
    };

    expect(isEnding(current)).toBe(false);
  });
});

describe("limits", () => {
  it("says unlimited rather than leaving a cell blank", () => {
    expect(ceilingLabel(null)).toBe("Unlimited");
    expect(ceilingLabel(10)).toBe("10");
  });

  it("reads null as unlimited, never as zero", () => {
    const current: WorkspacePlan = { plan: BUSINESS, subscription: null };

    expect(ceiling(current, "team_members")).toBeNull();
    expect(ceiling(current, "ai_responses_per_month")).toBe(100_000);
  });

  it("has no fraction to show where nothing bounds it", () => {
    expect(fractionUsed({ metric: "team_members", quantity: 40, limit: null })).toBeNull();
  });

  it("does not run a meter past full", () => {
    expect(
      fractionUsed({ metric: "ai_responses", quantity: 12_000, limit: 10_000 }),
    ).toBe(100);
  });

  it("rounds to something a person reads", () => {
    expect(
      fractionUsed({ metric: "ai_responses", quantity: 3_333, limit: 10_000 }),
    ).toBe(33);
  });
});

describe("isFree", () => {
  it("recognises a zero price however it is written", () => {
    expect(isFree({ ...GROWTH, price: "0" })).toBe(true);
    expect(isFree({ ...GROWTH, price: "0.00" })).toBe(true);
  });

  it("does not mistake a real price for free", () => {
    expect(isFree(GROWTH)).toBe(false);
    expect(isFree({ ...GROWTH, price: "0.01" })).toBe(false);
  });
});

describe("isPlanRefusal", () => {
  it("catches both 402s and nothing else", () => {
    expect(isPlanRefusal("feature_not_in_plan")).toBe(true);
    expect(isPlanRefusal("plan_limit_reached")).toBe(true);
    // A 403 is a role problem, and sends somebody to an administrator
    // rather than to the billing page.
    expect(isPlanRefusal("insufficient_workspace_role")).toBe(false);
    expect(isPlanRefusal(undefined)).toBe(false);
  });
});
