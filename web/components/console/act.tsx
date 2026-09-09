"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Refused } from "@/components/console/refused";
import { Button } from "@/components/ui/button";
import type { FormState } from "@/lib/form-state";

/**
 * One button that does one thing, and says so when it is refused.
 *
 * Six of this phase's acts are a single press with nothing to fill in --
 * lifting a suspension, restoring a closed account, turning an account
 * off and on again, confirming an address, ending somebody's sessions.
 * None of them destroys anything, which is why none asks for a typed
 * confirmation: the worst outcome of a mis-click is doing it again the
 * other way.
 *
 * Every one of them can still be refused, and by something the person
 * cannot see from the screen -- an account restored a minute ago by a
 * colleague, an erasure date that has just passed. So the refusal is
 * rendered here rather than swallowed, which is the whole reason this is
 * a client component and not a plain `<form action={…}>`.
 */
function Press({
  label,
  variant,
}: {
  label: string;
  variant: "outline" | "destructive" | "default";
}) {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant={variant} size="sm" disabled={pending}>
      {label}
    </Button>
  );
}

export function Act({
  action,
  fields,
  label,
  note,
  variant = "outline",
  done,
}: {
  action: (state: FormState, form: FormData) => Promise<FormState>;
  /** Hidden inputs: the id this acts on, and anything else the API needs. */
  fields: Record<string, string>;
  label: string;
  /** What pressing it means, in one line. */
  note?: string;
  variant?: "outline" | "destructive" | "default";
  /** What to say once it has happened, where the screen cannot show it. */
  done?: string;
}) {
  const [state, submit] = useActionState<FormState, FormData>(action, null);

  return (
    <form action={submit} className="grid gap-2">
      {Object.entries(fields).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}

      <Refused state={state} />

      {state?.done && done ? (
        <p className="text-muted-foreground text-sm" data-testid="act-done">
          {done}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Press label={label} variant={variant} />
        {note ? <span className="text-muted-foreground text-xs">{note}</span> : null}
      </div>
    </form>
  );
}
