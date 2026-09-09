"use client";

import { useActionState } from "react";

import { Refused } from "@/components/console/refused";
import { FieldError, SubmitButton } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { day } from "@/lib/console-labels";
import type { FormState } from "@/lib/form-state";
import { cancelWorkspace, restoreWorkspace } from "@/lib/lifecycle-actions";
import type { WorkspaceStatus } from "@/lib/types";

/**
 * Closing an account and bringing it back, together for the same reason
 * suspension's two halves are: a 409 refuses whichever was on offer, and
 * the refusal has to outlive the re-render it causes.
 *
 * The slug is the API's own safeguard rather than this screen's caution:
 * `confirm_slug` is in the body and a mismatch is a 422 that belongs on
 * the field. An id is copied from a list and a slug has to be read and
 * typed, and the difference between those two acts is the whole point --
 * whoever does this should have to know which business they are looking
 * at.
 *
 * The copy says recoverable because it is. Overstating it would frighten
 * somebody out of an action they can undo, and a support engineer afraid
 * of the close button is one who leaves accounts open instead.
 */
export function Closure({
  workspaceId,
  slug,
  status,
  eraseAfter,
}: {
  workspaceId: string;
  slug: string;
  status: WorkspaceStatus;
  eraseAfter: string | null;
}) {
  const [closeState, close] = useActionState<FormState, FormData>(
    cancelWorkspace,
    null,
  );
  const [restoreState, restore] = useActionState<FormState, FormData>(
    restoreWorkspace,
    null,
  );

  return (
    <div className="grid gap-3">
      <Refused state={closeState} />
      <Refused state={restoreState} />

      {status === "cancelled" ? (
        <div className="grid gap-3">
          <p className="text-sm">
            Closed, and due to be erased on{" "}
            <strong>{eraseAfter ? day(eraseAfter) : "no date"}</strong>.
            Restoring brings it back intact and clears that date.
          </p>

          <form action={restore} className="flex flex-wrap items-center gap-3">
            <input type="hidden" name="workspace_id" value={workspaceId} />
            <Button type="submit" variant="outline" size="sm">
              Restore this account
            </Button>
            <span className="text-muted-foreground text-xs">
              Refused once the erasure date has passed.
            </span>
          </form>
        </div>
      ) : (
        <form action={close} className="grid max-w-xl gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <div className="grid gap-2">
            <Label htmlFor="confirm_slug">
              Type <span className="font-mono">{slug}</span> to confirm
            </Label>
            <Input id="confirm_slug" name="confirm_slug" required autoComplete="off" />
            <p className="text-muted-foreground text-xs">
              It stops appearing for everyone in it and every address answers
              as though it is gone. The rows survive, and restoring brings them
              back until the erasure date.
            </p>
            <FieldError>{closeState?.fields?.confirm_slug}</FieldError>
          </div>

          <SubmitButton className="w-fit">Close this account</SubmitButton>
        </form>
      )}
    </div>
  );
}
