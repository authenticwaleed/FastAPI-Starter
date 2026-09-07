"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Button } from "@/components/ui/button";
import { confirmOrder } from "@/lib/order-actions";
import type { FormState } from "@/lib/form-state";
import type { Order } from "@/lib/types";

function ConfirmButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" size="sm" disabled={pending}>
      Confirm this order
    </Button>
  );
}

/**
 * Confirm a pending order.
 *
 * Only for a pending one: the API refuses anything else, because
 * confirming is a step forward rather than a way to undo a cancellation.
 * So a confirmed order shows no button at all, and pressing it twice --
 * two agents on the same order, or one double click -- is safe and says
 * what happened rather than raising a red box.
 */
export function ConfirmOrder({
  workspaceId,
  order,
}: {
  workspaceId: string;
  order: Order;
}) {
  const [state, action] = useActionState<FormState, FormData>(confirmOrder, null);

  if (order.status !== "pending") {
    return (
      <p className="text-muted-foreground text-sm" data-testid="confirm-note">
        {state?.stale
          ? `${state.error} It has been refreshed.`
          : `Confirmed orders cannot be confirmed again. This one is ${order.status}.`}
      </p>
    );
  }

  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="order_id" value={order.id} />

      {state?.error ? (
        <p
          className="text-muted-foreground text-sm"
          role="status"
          data-testid="confirm-note"
        >
          {state.error} It has been refreshed.
        </p>
      ) : null}

      <ConfirmButton />
    </form>
  );
}
