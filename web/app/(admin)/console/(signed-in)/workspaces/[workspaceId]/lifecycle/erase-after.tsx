"use client";

import { useActionState } from "react";

import { Refused } from "@/components/console/refused";
import { FieldError, SubmitButton } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { FormState } from "@/lib/form-state";
import { rescheduleErasure } from "@/lib/lifecycle-actions";

/** The date as a date input wants it, from the timestamp the API sends. */
function asDay(value: string | null): string {
  if (value === null) return "";

  const at = new Date(value);

  return Number.isNaN(at.getTime()) ? "" : at.toISOString().slice(0, 10);
}

/**
 * Moving the day a closed account's records are destroyed.
 *
 * Pre-filled with the date that applies, because this is a change to
 * something rather than a fresh decision: somebody pushing a date out for
 * a legal hold needs to see what it is now.
 *
 * The field has no minimum. A date in the past is the API's to refuse --
 * its schema says it does, and if it ever stops, a `min` here would have
 * been the client quietly enforcing a rule of its own and hiding the
 * difference.
 */
export function EraseAfter({
  workspaceId,
  eraseAfter,
}: {
  workspaceId: string;
  eraseAfter: string | null;
}) {
  const [state, action] = useActionState<FormState, FormData>(
    rescheduleErasure,
    null,
  );

  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <input type="hidden" name="workspace_id" value={workspaceId} />

      <div className="grid gap-1.5">
        <Label htmlFor="erase_after" className="text-xs">
          Erase after
        </Label>
        <Input
          id="erase_after"
          name="erase_after"
          type="date"
          defaultValue={asDay(eraseAfter)}
          required
          className="h-8 w-44"
        />
        <FieldError>{state?.fields?.erase_after}</FieldError>
      </div>

      <SubmitButton className="w-fit">Move the date</SubmitButton>

      <div className="w-full">
        <Refused state={state} />
      </div>
    </form>
  );
}
