"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { DangerZone, TypedConfirm } from "@/components/danger-zone";
import { Refusal } from "@/components/refusal";
import { Button } from "@/components/ui/button";
import { cancelSubscription } from "@/lib/billing-actions";
import type { FormState } from "@/lib/form-state";

function CancelButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" className="w-fit" disabled={pending}>
      Cancel the subscription
    </Button>
  );
}

/**
 * Stop at the end of the period that has been paid for.
 *
 * The copy is careful because the thing itself is: cancelling does not
 * switch anything off. Somebody who has paid for a month is entitled to
 * the month, so the subscription is set to end rather than ended, and the
 * workspace falls back to the free plan afterwards rather than to nothing.
 *
 * A person expecting to lose access immediately, and a person expecting to
 * keep it forever, are both about to be surprised. Saying which happens is
 * cheaper than either.
 */
export function CancelSubscription({ workspaceId }: { workspaceId: string }) {
  const [state, action] = useActionState<FormState, FormData>(
    cancelSubscription,
    null,
  );

  return (
    <DangerZone
      title="Cancel the subscription"
      description="Nothing stops today. It runs to the end of the period you have paid for, and then this workspace goes back to the free plan — it does not go away, and neither does anything in it."
    >
      <form action={action} className="grid gap-4">
        <input type="hidden" name="workspace_id" value={workspaceId} />

        <Refusal state={state} />

        {state?.done ? (
          <p className="text-muted-foreground text-sm" role="status">
            Cancelled. It ends at the close of the current period.
          </p>
        ) : null}

        <TypedConfirm phrase="CANCEL" id="cancel-confirm" />

        <CancelButton />
      </form>
    </DangerZone>
  );
}
