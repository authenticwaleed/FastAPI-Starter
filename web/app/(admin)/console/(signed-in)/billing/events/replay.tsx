"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Refused } from "@/components/console/refused";
import { Button } from "@/components/ui/button";
import type { FormState } from "@/lib/form-state";
import { replayBillingEvent } from "@/lib/platform-actions";

function Press() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="xs" disabled={pending}>
      Apply again
    </Button>
  );
}

/**
 * Applying a stored delivery again, and saying what that did.
 *
 * Safe to press twice, and the copy says so: what gets applied is the
 * provider's own snapshot, so applying it again lands on the same values.
 * The dedupe row is deliberately left alone -- it exists to stop a
 * provider *retry* being applied twice, and defeating it here would turn
 * every replay into a way of losing that protection.
 *
 * `applied: false` is the answer this component exists to render
 * properly. It means there was nothing to do: a delivery from before
 * payloads were kept, or one naming a subscription this platform does not
 * hold. Colouring that as a failure would send somebody looking for a
 * bug that is not there.
 */
export function Replay({
  eventId,
  replayable,
}: {
  eventId: string;
  replayable: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(
    replayBillingEvent,
    null,
  );

  if (!replayable) {
    return (
      <span className="text-muted-foreground text-xs" data-testid="not-replayable">
        Recorded before payloads were kept — there is nothing to re-apply.
      </span>
    );
  }

  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="event_id" value={eventId} />

      <Press />

      {state?.done ? (
        <span className="text-muted-foreground text-xs" data-testid="replay-result">
          {state.applied
            ? "Applied. The provider's own snapshot, so nothing moved that was already right."
            : "Nothing to apply — this delivery names a subscription that is not here."}
        </span>
      ) : null}

      <span className="w-full">
        <Refused state={state} />
      </span>
    </form>
  );
}
