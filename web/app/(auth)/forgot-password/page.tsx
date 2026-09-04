"use client";

import Link from "next/link";
import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { forgotPassword, type FormState } from "@/lib/auth-actions";

export default function ForgotPasswordPage() {
  const [state, action] = useActionState<FormState, FormData>(forgotPassword, null);

  /*
    One outcome, whatever happened. The API does not say whether an account
    exists at an address, and a screen that distinguished "sent" from "no
    such account" would hand back precisely what the API withheld.
  */
  if (state?.done) {
    return (
      <Card>
        <CardHeader>
          <CardTitle><h1>Check your email</h1></CardTitle>
          <CardDescription>
            If that address has an account, a link to set a new password is on
            its way. It expires shortly, so use it soon.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Link
            href="/sign-in"
            className="text-sm underline underline-offset-4"
          >
            Back to sign in
          </Link>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle><h1>Forgotten password</h1></CardTitle>
        <CardDescription>
          Tell us the address you signed up with and we will send a link.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid gap-4">
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

          <SubmitButton>Send the link</SubmitButton>
        </form>
      </CardContent>

      <CardFooter className="text-muted-foreground justify-center text-sm">
        Remembered it?
        <Link
          href="/sign-in"
          className="text-foreground ml-1 underline underline-offset-4"
        >
          Sign in
        </Link>
      </CardFooter>
    </Card>
  );
}
