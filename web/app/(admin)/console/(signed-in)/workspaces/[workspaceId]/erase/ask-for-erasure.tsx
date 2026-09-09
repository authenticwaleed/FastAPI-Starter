"use client";

import { useActionState } from "react";

import { Refused } from "@/components/console/refused";
import { FieldError, SubmitButton } from "@/components/form";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { FormState } from "@/lib/form-state";
import { requestErasureApproval } from "@/lib/lifecycle-actions";

/**
 * Asking a colleague to agree to an erasure.
 *
 * The reason is what they will be agreeing to, so it has to say which
 * business and why now. A colleague approving "cleanup" has not approved
 * anything they could be held to afterwards, and this is the record that
 * outlives the workspace it names.
 */
export function AskForErasure({ workspaceId }: { workspaceId: string }) {
  const [state, action] = useActionState<FormState, FormData>(
    requestErasureApproval,
    null,
  );

  return (
    <form action={action} className="grid max-w-xl gap-4">
      <input type="hidden" name="workspace_id" value={workspaceId} />

      <Refused state={state} />

      <div className="grid gap-2">
        <Label htmlFor="reason">What you are asking them to agree to</Label>
        <Textarea
          id="reason"
          name="reason"
          required
          minLength={10}
          maxLength={500}
          rows={3}
          placeholder="They asked to be forgotten on 2 September and confirmed it by reply; nothing is outstanding"
        />
        <FieldError>{state?.fields?.reason}</FieldError>
      </div>

      <SubmitButton className="w-fit">Ask a colleague</SubmitButton>
    </form>
  );
}
