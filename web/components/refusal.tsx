"use client";

import Link from "next/link";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { isPlanRefusal } from "@/lib/plans";
import type { FormState } from "@/lib/form-state";

/**
 * A refusal, rendered as what it actually is.
 *
 * One component so every screen answers a 402 the same way, which is the
 * criterion W7 is judged on. The distinction it draws is the one the API
 * chose its status codes to make:
 *
 * - **402** — the *plan* is what is in the way, and the plan is something
 *   this person can change. So it links to billing, and it is blue rather
 *   than red: the same colour as a refusal would say the account is not
 *   allowed to do this, when in fact it could be, for money.
 * - **403** — *you* may not, and no amount of paying fixes it. Sending
 *   somebody to the billing page for that would be worse than saying
 *   nothing, because they would spend money and still be refused.
 *
 * Everything else is an ordinary alert. `stale` refusals -- somebody else
 * moved first -- are not this component's business; the screens that can
 * meet one render it as a status line instead.
 */
export function Refusal({ state }: { state: FormState }) {
  if (!state?.error) return null;

  if (isPlanRefusal(state.code)) {
    return (
      <Alert variant="info" role="alert" data-testid="upgrade-prompt">
        <AlertDescription className="grid gap-1">
          <span>{state.error}</span>
          <Link
            href="/billing"
            className="w-fit text-sm underline underline-offset-4"
          >
            See what each plan includes
          </Link>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Alert variant="destructive" role="alert">
      <AlertDescription>{state.error}</AlertDescription>
    </Alert>
  );
}
