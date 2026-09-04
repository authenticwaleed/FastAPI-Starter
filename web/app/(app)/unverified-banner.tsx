"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { resendVerification, type FormState } from "@/lib/auth-actions";

/**
 * A nudge, not a gate.
 *
 * Confirming an address gates nothing in this API -- `email_verified_at` is
 * recorded and reported and nothing reads it to decide anything. So this
 * says what is missing and offers to send the link again, and does not
 * stand in front of the product. Making it a requirement would be a rule
 * this client invented, which is the one thing the plan asks it not to do.
 */
export function UnverifiedBanner({ email }: { email: string }) {
  const [state, action] = useActionState<FormState, FormData>(
    resendVerification,
    null,
  );

  return (
    <div className="bg-muted/60 border-b">
      <div className="text-muted-foreground mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
        {state?.done ? (
          <span>Sent. Follow the link in your inbox to confirm {email}.</span>
        ) : (
          <>
            <span>
              {state?.error ?? `We have not confirmed ${email} yet.`}
            </span>
            <form action={action}>
              <input type="hidden" name="email" value={email} />
              <Button
                type="submit"
                variant="link"
                size="sm"
                className="h-auto p-0 text-sm"
              >
                Send the link again
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
