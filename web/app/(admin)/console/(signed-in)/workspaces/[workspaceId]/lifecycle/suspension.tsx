"use client";

import { useActionState } from "react";

import { Refused } from "@/components/console/refused";
import { FieldError, SubmitButton } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { FormState } from "@/lib/form-state";
import { suspendWorkspace, unsuspendWorkspace } from "@/lib/lifecycle-actions";
import type { WorkspaceStatus } from "@/lib/types";

/**
 * Freezing an account and thawing it, in one component on purpose.
 *
 * Both directions live here because a `409 workspace_lifecycle` refuses
 * whichever of them the screen was offering, and the phase's rule is to
 * re-render the available actions when that happens. If the two were
 * separate components, revalidating would swap one for the other -- and
 * unmount the refusal before anybody had read it. Here the component
 * stays put, its props change, and the sentence explaining why survives
 * the change it caused.
 *
 * The reason is required by the API and lands in the business's own audit
 * log, which is why the field asks for a sentence and not a label:
 * "unpaid" is a category, and "the invoice of 3 March is sixty days
 * overdue" is an answer a customer can act on.
 *
 * The copy avoids implying money at all. A suspension is an operational
 * decision and most are not about an invoice; telling a business it has
 * not paid when it has is a worse mistake than saying nothing.
 */
export function Suspension({
  workspaceId,
  status,
}: {
  workspaceId: string;
  status: WorkspaceStatus;
}) {
  const [suspendState, suspend] = useActionState<FormState, FormData>(
    suspendWorkspace,
    null,
  );
  const [liftState, lift] = useActionState<FormState, FormData>(
    unsuspendWorkspace,
    null,
  );

  if (status === "cancelled") {
    return (
      <p className="text-muted-foreground text-sm">
        A closed account cannot be suspended. Restore it first.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      <Refused state={suspendState} />
      <Refused state={liftState} />

      {status === "suspended" ? (
        <form action={lift} className="flex flex-wrap items-center gap-3">
          <input type="hidden" name="workspace_id" value={workspaceId} />
          <Button type="submit" variant="outline" size="sm">
            Lift the suspension
          </Button>
          <span className="text-muted-foreground text-xs">
            They can change things again straight away.
          </span>
        </form>
      ) : (
        <form action={suspend} className="grid max-w-xl gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <div className="grid gap-2">
            <Label htmlFor="reason">Why this account is being frozen</Label>
            <Textarea
              id="reason"
              name="reason"
              required
              minLength={10}
              maxLength={500}
              rows={3}
              placeholder="The invoice of 3 March is sixty days overdue and three reminders have gone unanswered"
            />
            <p className="text-muted-foreground text-xs">
              The business reads this in their own log. At least ten characters.
            </p>
            <FieldError>{suspendState?.fields?.reason}</FieldError>
          </div>

          <SubmitButton className="w-fit">Suspend this account</SubmitButton>
        </form>
      )}
    </div>
  );
}
