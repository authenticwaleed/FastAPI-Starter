"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Refused } from "@/components/console/refused";
import { Button } from "@/components/ui/button";
import type { FormState } from "@/lib/form-state";
import { approveRequest } from "@/lib/platform-actions";

function Press() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      Agree to this
    </Button>
  );
}

/**
 * Agreeing to a colleague's request.
 *
 * Offered only on requests somebody else raised, which is this screen
 * reading `requested_by` rather than a rule of its own -- the API refuses
 * your own either way, and the refusal renders here if the two disagree.
 *
 * What agreeing does not do is perform the act. Whoever spends this has
 * to be a third state of affairs again: not you. The button says "agree"
 * rather than "erase" for that reason.
 */
export function ApproveRequest({ approvalId }: { approvalId: string }) {
  const [state, action] = useActionState<FormState, FormData>(approveRequest, null);

  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="approval_id" value={approvalId} />

      <Refused state={state} />

      <div className="flex flex-wrap items-center gap-3">
        <Press />
        <span className="text-muted-foreground text-xs">
          Agreeing is not doing it. Whoever asked still has to act, and they
          have to be somebody other than you.
        </span>
      </div>
    </form>
  );
}
