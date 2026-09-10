"use client";

import { useActionState, useState } from "react";

import { CopyField } from "@/components/copy";
import { FieldError, SubmitButton } from "@/components/form";
import { Refusal } from "@/components/refusal";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { inviteMember } from "@/lib/invitation-actions";
import type { FormState } from "@/lib/form-state";
import { ROLE_DESCRIPTION, grantableBy } from "@/lib/roles";
import type { WorkspaceRole } from "@/lib/types";

/**
 * The link, shown once, because nothing emails it.
 *
 * The API returns the token in this one response and never again -- what
 * it stores is a digest. So the honest thing is to put the link on screen
 * and make it easy to hand over, rather than to say "an invitation has
 * been sent" when nothing has been sent at all.
 *
 * This whole component should be deleted the day the API emails these.
 */
function TheLink({ token }: { token: string }) {
  const link =
    typeof window === "undefined"
      ? `/invitations/${token}`
      : `${window.location.origin}/invitations/${token}`;

  return (
    <div className="grid gap-2 panel">
      <p className="text-sm font-medium">Send them this link</p>
      <p className="text-muted-foreground text-xs">
        It is shown once and cannot be shown again. Nothing emails it yet, so
        it has to be handed over.
      </p>
      <CopyField value={link} data-testid="invitation-link" />
    </div>
  );
}

export function InviteForm({
  workspaceId,
  myRole,
  disabled,
}: {
  workspaceId: string;
  myRole: WorkspaceRole;
  disabled: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(inviteMember, null);
  const [email, setEmail] = useState("");
  const grantable = grantableBy(myRole);

  // Controlled, because React resets a form after its action completes --
  // which is right after a success and wrong after a refusal. A 409 here
  // is "already invited" or "already a member", and the next thing
  // somebody does is change one character rather than retype the address.
  //
  // Cleared during render rather than in an effect. That is the pattern
  // React documents for "reset when something changes", and the effect
  // version costs a second render pass for a value nobody sees.
  const [issued, setIssued] = useState<string | null>(null);

  if (state?.invitation && state.invitation.id !== issued) {
    setIssued(state.invitation.id);
    setEmail("");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Invite somebody</h2>
        </CardTitle>
        <CardDescription>
          The invitation only admits the address it was sent to. They will
          need an account — signing up first and accepting second is the flow.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        {state?.invitation ? <TheLink token={state.invitation.token} /> : null}

        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <Refusal state={state} />

          <div className="grid gap-2">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              name="email"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              disabled={disabled}
            />
            <FieldError>{state?.fields?.email}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="invite-role">Role</Label>
            <NativeSelect
              id="invite-role"
              name="role"
              defaultValue={grantable.includes("agent") ? "agent" : grantable[0]}
              disabled={disabled}
            >
              {grantable.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </NativeSelect>
            <dl className="text-muted-foreground grid gap-1 text-xs">
              {grantable.map((role) => (
                <div key={role} className="flex gap-2">
                  <dt className="font-medium">{role}</dt>
                  <dd>{ROLE_DESCRIPTION[role]}</dd>
                </div>
              ))}
            </dl>
          </div>

          {disabled ? null : (
            <SubmitButton className="w-fit">Create invitation</SubmitButton>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
