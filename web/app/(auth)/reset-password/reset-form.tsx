"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { resetPassword, type FormState } from "@/lib/auth-actions";

export function ResetForm({ token }: { token: string }) {
  const [state, action] = useActionState<FormState, FormData>(resetPassword, null);

  return (
    <form action={action} className="grid gap-4">
      <input type="hidden" name="token" value={token} />

      <FormError>{state?.error}</FormError>

      <div className="grid gap-2">
        <Label htmlFor="new_password">New password</Label>
        <Input
          id="new_password"
          name="new_password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
          autoFocus
        />
        <FieldError>{state?.fields?.new_password}</FieldError>
        <p className="text-muted-foreground text-xs">
          At least 8 characters. Every other session will be signed out.
        </p>
      </div>

      <SubmitButton>Set the password</SubmitButton>
    </form>
  );
}
