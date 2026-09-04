"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { register, type FormState } from "@/lib/auth-actions";

export function RegisterForm() {
  const [state, action] = useActionState<FormState, FormData>(register, null);

  return (
    <form action={action} className="grid gap-4">
      <FormError>{state?.error}</FormError>

      <div className="grid gap-2">
        <Label htmlFor="name">Your name</Label>
        <Input id="name" name="name" autoComplete="name" required autoFocus />
        <FieldError>{state?.fields?.name}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input id="email" name="email" type="email" autoComplete="email" required />
        <FieldError>{state?.fields?.email}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
        />
        {/*
          The API's own minimum, stated before somebody trips it. Unlike a
          sign-in attempt, saying so here leaks nothing: whoever is choosing
          a password is entitled to know the rules for it.
        */}
        <FieldError>{state?.fields?.password}</FieldError>
        <p className="text-muted-foreground text-xs">At least 8 characters.</p>
      </div>

      <SubmitButton>Create account</SubmitButton>
    </form>
  );
}
