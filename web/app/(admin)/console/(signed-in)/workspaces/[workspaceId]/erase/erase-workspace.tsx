"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Refused } from "@/components/console/refused";
import { FieldError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { FormState } from "@/lib/form-state";
import { eraseWorkspaceNow } from "@/lib/lifecycle-actions";

function EraseButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" className="w-fit" disabled={pending}>
      Erase this workspace for ever
    </Button>
  );
}

/**
 * The last step, and the one that names its subject.
 *
 * The slug in the body is the API's safeguard, not this screen's caution:
 * a mismatch is a `422` that lands on the field, and the attempt is
 * recorded either way — somebody typing the wrong name into an erasure is
 * either tired or in the wrong window, and both are worth a row.
 *
 * The approval travels as a hidden field because it is not a choice: it
 * is the one a colleague agreed to, for this workspace, and offering a
 * list of them would invite spending the wrong one.
 */
export function EraseWorkspace({
  workspaceId,
  slug,
  approvalId,
}: {
  workspaceId: string;
  slug: string;
  approvalId: string;
}) {
  const [state, action] = useActionState<FormState, FormData>(
    eraseWorkspaceNow,
    null,
  );

  return (
    <form action={action} className="grid max-w-xl gap-4">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="approval_id" value={approvalId} />

      <Refused state={state} />

      <div className="grid gap-2">
        <Label htmlFor="confirm_slug">
          Type <span className="font-mono">{slug}</span> to confirm
        </Label>
        <Input
          id="confirm_slug"
          name="confirm_slug"
          required
          autoComplete="off"
          data-testid="confirm-slug"
        />
        <FieldError>{state?.fields?.confirm_slug}</FieldError>
      </div>

      <EraseButton />
    </form>
  );
}
