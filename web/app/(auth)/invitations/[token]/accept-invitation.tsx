"use client";

import { useActionState } from "react";

import { FormError, SubmitButton } from "@/components/form";
import { acceptInvitation } from "@/lib/invitation-actions";
import type { FormState } from "@/lib/form-state";

/**
 * Take the seat.
 *
 * The refusal to expect is `invitation_not_yours`: signed in, but as
 * somebody else. That is a real case -- one browser, two accounts -- and
 * the sentence for it says which address the link admits rather than
 * implying the link is broken.
 */
export function AcceptInvitation({ token }: { token: string }) {
  const [state, action] = useActionState<FormState, FormData>(
    acceptInvitation,
    null,
  );

  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="token" value={token} />

      <FormError>{state?.error}</FormError>

      <SubmitButton>Accept and join</SubmitButton>
    </form>
  );
}
