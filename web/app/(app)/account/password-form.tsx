"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { changePassword } from "@/lib/account-actions";
import type { FormState } from "@/lib/form-state";

/**
 * Change the password.
 *
 * The consequence is stated before the button rather than after it: the API
 * ends every other session, which is exactly what makes this useful after a
 * scare and exactly what somebody needs to know before they do it on a
 * shared laptop. This device stays signed in.
 */
export function PasswordForm() {
  const [state, action] = useActionState<FormState, FormData>(changePassword, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Password</h2>
        </CardTitle>
        <CardDescription>
          Changing it signs out every other device. This one stays signed in.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <FormError>{state?.error}</FormError>

          {state?.done ? (
            <p className="text-muted-foreground text-sm" role="status">
              Changed. Every other device has been signed out.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="current_password">Current password</Label>
            <Input
              id="current_password"
              name="current_password"
              type="password"
              autoComplete="current-password"
              required
            />
            <FieldError>{state?.fields?.current_password}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="new_password">New password</Label>
            <Input
              id="new_password"
              name="new_password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
            />
            <FieldError>{state?.fields?.new_password}</FieldError>
            <p className="text-muted-foreground text-xs">At least 8 characters.</p>
          </div>

          <SubmitButton className="w-fit">Change password</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
