"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
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
import { leaveWorkspace } from "@/lib/member-actions";
import type { FormState } from "@/lib/form-state";
import type { Member, Workspace } from "@/lib/types";

function LeaveButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" className="w-fit" disabled={pending}>
      Leave this workspace
    </Button>
  );
}

/**
 * Walk out.
 *
 * Needs no rank -- anybody may leave a workspace they are in -- so this is
 * on the page for every member rather than only for administrators.
 *
 * `last_owner` is the refusal worth designing for, and it is a step rather
 * than a wall: make somebody else an owner first. The screen says so, and
 * the member list above is where that is done.
 */
export function LeaveWorkspace({
  workspace,
  me,
}: {
  workspace: Workspace;
  me: Member;
}) {
  const [state, action] = useActionState<FormState, FormData>(leaveWorkspace, null);

  const strandedAsOwner = state?.error?.includes("at least one owner");

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle>
          <h2>Leave {workspace.name}</h2>
        </CardTitle>
        <CardDescription>
          You lose access to its inbox, its contacts and everything else in
          it. Somebody who administers it can invite you back.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspace.id} />
          <input type="hidden" name="user_id" value={me.user_id} />

          <FormError>{state?.error}</FormError>

          {strandedAsOwner ? (
            <p className="text-muted-foreground text-sm">
              Give somebody else the owner role in the list above, then come
              back. A workspace with no owner is one nobody can administer.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="leave-confirm">
              Type <span className="font-mono">LEAVE</span> to confirm
            </Label>
            <Input
              id="leave-confirm"
              name="confirm"
              autoComplete="off"
              className="font-mono"
              required
            />
          </div>

          <LeaveButton />
        </form>
      </CardContent>
    </Card>
  );
}
