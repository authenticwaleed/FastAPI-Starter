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
import { updateAccount } from "@/lib/account-actions";
import type { FormState } from "@/lib/form-state";
import type { User } from "@/lib/types";

/**
 * Name and address.
 *
 * The warning about the address is not decoration: changing it clears the
 * confirmation, and the API expects the client to ask for a new link
 * afterwards. Saying so before somebody types beats a banner appearing
 * afterwards with no explanation of what caused it.
 */
export function ProfileForm({ user }: { user: User }) {
  const [state, action] = useActionState<FormState, FormData>(updateAccount, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Details</h2>
        </CardTitle>
        <CardDescription>
          Changing your address means confirming the new one. Nothing stops
          working while it is unconfirmed.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <FormError>{state?.error}</FormError>

          {state?.done ? (
            <p className="text-muted-foreground text-sm" role="status">
              Saved.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              name="name"
              defaultValue={user.name}
              autoComplete="name"
              maxLength={100}
              required
            />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              defaultValue={user.email}
              autoComplete="email"
              required
            />
            <FieldError>{state?.fields?.email}</FieldError>
          </div>

          <SubmitButton className="w-fit">Save</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
