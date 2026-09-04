"use client";

import Link from "next/link";
import { useActionState } from "react";

import { FormError, SubmitButton } from "@/components/form";
import { verifyEmail, type FormState } from "@/lib/auth-actions";

/**
 * Confirming takes a click.
 *
 * The obvious thing is to verify during the render, so following the link
 * is the whole of it. The obvious thing is wrong: a verification token is
 * spent on use, and mail scanners, link previewers and this application's
 * own prefetcher all issue GETs. Any one of them would burn the token
 * before the person ever saw the page, and they would arrive at a link that
 * had already been used by nobody.
 */
export function VerifyForm({ token }: { token: string }) {
  const [state, action] = useActionState<FormState, FormData>(
    () => verifyEmail(token),
    null,
  );

  if (state?.done) {
    return (
      <div className="grid gap-4">
        <p className="text-muted-foreground text-sm">
          Your address is confirmed. Nothing was locked while it was not, so
          there is nothing waiting for you — carry on where you were.
        </p>
        <Link
          href="/"
          className="text-sm underline underline-offset-4"
        >
          Go to Baton
        </Link>
      </div>
    );
  }

  return (
    <form action={action} className="grid gap-4">
      <FormError>{state?.error}</FormError>
      <SubmitButton>Confirm my address</SubmitButton>
    </form>
  );
}
