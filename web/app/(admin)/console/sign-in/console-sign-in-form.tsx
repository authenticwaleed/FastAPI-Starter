"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { consoleSignIn, type FormState } from "@/lib/console-actions";

/**
 * The same three fields as the app's sign-in, posting somewhere else.
 *
 * No "forgot your password" link, and that is not an oversight: resetting
 * a password is an account matter rather than a console one, and the
 * screen for it lives on the customer surface where it belongs. A link
 * from here would be the console's first door back into the app.
 */
export function ConsoleSignInForm({ next }: { next: string }) {
  const [state, action] = useActionState<FormState, FormData>(consoleSignIn, null);

  return (
    <form action={action} className="grid gap-4">
      <input type="hidden" name="next" value={next} />

      <FormError>{state?.error}</FormError>

      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          autoFocus
        />
        <FieldError>{state?.fields?.email}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
        <FieldError>{state?.fields?.password}</FieldError>
      </div>

      <SubmitButton>Sign in to the console</SubmitButton>
    </form>
  );
}
