"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { requestSupportAccess } from "@/lib/console-actions";
import type { FormState } from "@/lib/form-state";

/**
 * What the API's schema permits, which is not the same as what a
 * deployment allows.
 *
 * `hours` is `1..24` in the committed reference, and the configured
 * maximum can be lower and is returned nowhere -- so these are offered and
 * a refusal says to ask for fewer. Naming the real maximum needs the API
 * to return it; guessing it here would be the client inventing a fact.
 *
 * Four is the API's own default and the reason it is: a shift.
 */
const DURATIONS = [1, 2, 4, 8, 12, 24];
const DEFAULT_HOURS = 4;

/**
 * Asking to read one customer's data, in the open.
 *
 * Both fields are the safeguard rather than paperwork, and the paragraph
 * above them is the phase's rule about no silent power: the business sees
 * this in their own audit log, with the reason typed here and the hour it
 * ends. "A staff member read your account" is frightening on its own;
 * with a reason and an expiry it is something a customer can hold
 * somebody to.
 *
 * The same form serves two places -- the support-access screen, and the
 * refusal on any screen that needed a grant and did not have one -- so
 * that "ask for access" is a thing somebody does where they are rather
 * than a page they go and find.
 */
export function RequestAccess({ workspaceId }: { workspaceId: string }) {
  const [state, action] = useActionState<FormState, FormData>(
    requestSupportAccess,
    null,
  );

  return (
    <form action={action} className="grid gap-4" data-testid="request-access">
      <input type="hidden" name="workspace_id" value={workspaceId} />

      <p className="text-muted-foreground text-sm">
        This is not quiet. The business sees it in their own audit log, with
        the reason you give and the hour it ends, and every thread you open
        is recorded separately.
      </p>

      <FormError>{state?.error}</FormError>

      <div className="grid gap-2">
        <Label htmlFor="reason">Why you need to look</Label>
        <Textarea
          id="reason"
          name="reason"
          required
          minLength={10}
          maxLength={500}
          rows={3}
          placeholder="To investigate the delivery failure they reported on Tuesday"
        />
        <p className="text-muted-foreground text-xs">
          Written to the customer&rsquo;s own log, so write it to be read by
          them. At least ten characters — &ldquo;checking&rdquo; is not a
          reason.
        </p>
        <FieldError>{state?.fields?.reason}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="hours">For how long</Label>
        <NativeSelect
          id="hours"
          name="hours"
          defaultValue={String(DEFAULT_HOURS)}
          className="w-40"
        >
          {DURATIONS.map((hours) => (
            <option key={hours} value={hours}>
              {hours === 1 ? "1 hour" : `${hours} hours`}
            </option>
          ))}
        </NativeSelect>
        <FieldError>{state?.fields?.hours}</FieldError>
      </div>

      <SubmitButton className="w-fit">Ask for access</SubmitButton>
    </form>
  );
}
