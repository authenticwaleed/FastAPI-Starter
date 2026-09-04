"use client";

/**
 * The parts every form on the authentication screens shares.
 *
 * Small on purpose. A form here is a `<form action={…}>` posting to a
 * server action, so there is no submit handler, no fetch, and no state to
 * manage -- these three cover what is left: saying a request is in flight,
 * showing the one sentence that came back, and putting a field's own
 * message beside it.
 */

import { useFormStatus } from "react-dom";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function SubmitButton({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" className={cn("w-full", className)} disabled={pending}>
      {/*
        The label does not change to "Signing in…". A button whose text
        swaps on click moves under the cursor and reads as a different
        control; disabled plus the cursor is enough to say the same thing.
      */}
      {children}
    </Button>
  );
}

export function FormError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;

  return (
    <Alert variant="destructive" role="alert">
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}

export function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;

  return <p className="text-destructive text-sm">{children}</p>;
}
