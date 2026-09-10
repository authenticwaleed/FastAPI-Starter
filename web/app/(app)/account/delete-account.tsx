"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { DangerZone, TypedConfirm } from "@/components/danger-zone";
import { FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { deleteAccount } from "@/lib/account-actions";
import type { FormState } from "@/lib/form-state";

function DeleteButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="danger" className="w-fit" disabled={pending}>
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
    <DangerZone
      title="Delete your account"
      description="Your sign-in, your devices and your place in every workspace. If you are the only owner of a workspace, hand it over or close it first."
    >
      <form action={action} className="grid gap-4">
        <FormError>{state?.error}</FormError>

        {blockedByOwnership ? (
          <p className="text-muted-foreground text-sm">
            Open each workspace you own, give somebody else the owner role,
            or close it — then come back.
          </p>
        ) : null}

        <TypedConfirm phrase="DELETE" error={state?.fields?.confirm} />

        <DeleteButton />
      </form>
    </DangerZone>
  );
}
