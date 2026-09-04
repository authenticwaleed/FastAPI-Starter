"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FieldError, FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { deleteAccount } from "@/lib/account-actions";
import type { FormState } from "@/lib/form-state";

function DeleteButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" className="w-fit" disabled={pending}>
      Delete my account
    </Button>
  );
}

/**
 * Close the account.
 *
 * No password field, and that is not an omission: `DELETE /account` asks
 * for none, and a client that demanded one would be inventing a rule the
 * API does not have. The typed confirmation is this client's own caution
 * and is not presented as though it were authentication.
 *
 * The refusal worth designing for is `workspace_ownership_required` -- being
 * the last owner of a workspace. That renders as an instruction with
 * somewhere to go, because it is a step to take rather than a wall.
 */
export function DeleteAccount() {
  const [state, action] = useActionState<FormState, FormData>(deleteAccount, null);

  const blockedByOwnership = state?.error?.includes("only owner");

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle>
          <h2>Delete your account</h2>
        </CardTitle>
        <CardDescription>
          Your sign-in, your devices and your place in every workspace. If you
          are the only owner of a workspace, hand it over or close it first.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <FormError>{state?.error}</FormError>

          {blockedByOwnership ? (
            <p className="text-muted-foreground text-sm">
              Open each workspace you own, give somebody else the owner role,
              or close it — then come back.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="confirm">
              Type <span className="font-mono">DELETE</span> to confirm
            </Label>
            <Input
              id="confirm"
              name="confirm"
              autoComplete="off"
              className="font-mono"
              required
            />
            <FieldError>{state?.fields?.confirm}</FieldError>
          </div>

          <DeleteButton />
        </form>
      </CardContent>
    </Card>
  );
}
