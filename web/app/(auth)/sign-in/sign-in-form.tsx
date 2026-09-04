"use client";

import Link from "next/link";
import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { signIn, type FormState } from "@/lib/auth-actions";

export function SignInForm({ next, justReset }: { next: string; justReset: boolean }) {
  const [state, action] = useActionState<FormState, FormData>(signIn, null);

  return (
    <form action={action} className="grid gap-4">
      <input type="hidden" name="next" value={next} />

      {justReset ? (
        <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-sm">
          Your password has been changed. Sign in with the new one.
        </p>
      ) : null}

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
        <div className="flex items-center justify-between">
          <Label htmlFor="password">Password</Label>
          <Link
            href="/forgot-password"
            className="text-muted-foreground hover:text-foreground text-sm underline-offset-4 hover:underline"
          >
            Forgot?
          </Link>
        </div>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
        <FieldError>{state?.fields?.password}</FieldError>
      </div>

      <SubmitButton>Sign in</SubmitButton>
    </form>
  );
}
