"use client";

import { useActionState, useEffect } from "react";
import { useFormStatus } from "react-dom";

import { SectionHeader } from "@/components/page-header";
import { PlanCard } from "@/components/plan-card";
import { Refusal } from "@/components/refusal";
import { Button } from "@/components/ui/button";
import { startCheckout } from "@/lib/billing-actions";
import type { FormState } from "@/lib/form-state";
import { isFree, isUpgradeFrom } from "@/lib/plans";
import type { Plan, PlanTier } from "@/lib/types";

function CheckoutButton({ label }: { label: string }) {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" size="sm" className="w-full" disabled={pending}>
      {pending ? "Opening…" : label}
    </Button>
  );
}

/**
 * The plans, and a way onto a paid one.
 *
 * Checkout changes nothing here. The API answers with a URL at the
 * payment provider, the card is entered on their page, and what makes the
 * subscription real is the webhook that follows -- so this navigates away
 * and the return screen waits to be told.
 *
 * There is no button onto the free plan. Cancelling is how somebody
 * returns to it, and the API refuses a checkout for a plan with nothing to
 * pay; a button whose only outcome is a 502 would be worse than no button.
 */
export function PlanPicker({
  workspaceId,
  plans,
  currentTier,
  canChange,
}: {
  workspaceId: string;
  plans: Plan[];
  currentTier: PlanTier;
  canChange: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(startCheckout, null);

  useEffect(() => {
    // Out of the application entirely, once the API has said where to.
    if (state?.checkoutUrl) window.location.assign(state.checkoutUrl);
  }, [state]);

  return (
    <section className="grid gap-3">
      <SectionHeader title="Plans" />

      <Refusal state={state} />

      {state?.checkoutUrl ? (
        <p className="text-muted-foreground text-sm" role="status">
          Taking you to the payment page…
        </p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3" data-testid="plan-list">
        {plans.map((plan) => (
          <PlanCard key={plan.tier} plan={plan} current={plan.tier === currentTier}>
            {canChange && plan.tier !== currentTier && !isFree(plan) ? (
              <form action={action}>
                <input type="hidden" name="workspace_id" value={workspaceId} />
                <input type="hidden" name="plan" value={plan.tier} />
                <CheckoutButton
                  label={
                    isUpgradeFrom(currentTier, plan.tier)
                      ? `Move to ${plan.name}`
                      : `Change to ${plan.name}`
                  }
                />
              </form>
            ) : null}

            {plan.tier !== currentTier && isFree(plan) ? (
              <p className="text-muted-foreground text-xs">
                Cancelling is how you come back to this one.
              </p>
            ) : null}
          </PlanCard>
        ))}
      </div>

      {canChange ? null : (
        <p className="text-muted-foreground text-sm">
          Only an owner or an admin can change the plan.
        </p>
      )}
    </section>
  );
}
