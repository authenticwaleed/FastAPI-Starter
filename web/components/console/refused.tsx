"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { FormState } from "@/lib/form-state";

/**
 * Two of the platform's refusals say something the code cannot.
 *
 * `workspace_lifecycle` covers five different states -- already
 * suspended, never closed, its erasure date has passed -- and
 * `approval_required` covers five different reasons a colleague's
 * agreement does not apply, one of which is that it was yours. The code
 * is the same in each case and the sentence has to be general; the
 * particular is in the API's `detail`.
 *
 * So it is shown, on those two and nowhere else. This is not branching on
 * `detail` -- nothing anywhere decides anything from those words, and the
 * decision above is made on the code, which is the stable half.
 */
const SAYS_MORE = ["workspace_lifecycle", "approval_required"];

export function Refused({ state }: { state: FormState }) {
  if (!state?.error) return null;

  const particular =
    state.code && SAYS_MORE.includes(state.code) && state.detail !== state.error
      ? state.detail
      : null;

  return (
    <Alert variant="destructive" role="alert" data-code={state.code}>
      <AlertDescription className="grid gap-1">
        <span>{state.error}</span>
        {particular ? (
          <span className="text-xs opacity-80" data-testid="refusal-detail">
            {particular}
          </span>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
