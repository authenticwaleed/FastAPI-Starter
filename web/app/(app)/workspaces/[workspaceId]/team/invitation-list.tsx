"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { EmptyState } from "@/components/empty-state";
import { FormError } from "@/components/form";
import { SectionHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { revokeInvitation } from "@/lib/invitation-actions";
import type { FormState } from "@/lib/form-state";
import type { Invitation } from "@/lib/types";

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function RevokeButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      Withdraw
    </Button>
  );
}

/**
 * Invitations sent, newest first.
 *
 * Accepted and expired ones are kept rather than filtered out: "did we
 * ever invite them" is the question this list gets asked, and one that
 * showed only the live ones could not answer it.
 *
 * Withdrawing makes a link stop working. It does not remove somebody who
 * has already accepted -- by then they are a member, and members come off
 * the list above.
 */
export function InvitationList({
  workspaceId,
  invitations,
}: {
  workspaceId: string;
  invitations: Invitation[];
}) {
  const [state, revoke] = useActionState<FormState, FormData>(
    revokeInvitation,
    null,
  );

  if (invitations.length === 0) {
    return (
      <section className="grid gap-3">
        <SectionHeader title="Invitations" />
        <EmptyState title="None sent yet">
          An invitation is a link you hand over. It is shown once, when you
          create it.
        </EmptyState>
      </section>
    );
  }

  return (
    <section className="grid gap-3">
      <SectionHeader title="Invitations" />

      <FormError>{state?.error}</FormError>

      <ul className="grid gap-2" data-testid="invitation-list">
        {invitations.map((invitation) => (
          <li
            key={invitation.id}
            data-status={invitation.status}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 row"
          >
            <div className="grid min-w-0 flex-1 gap-0.5">
              <span className="truncate text-sm">{invitation.email}</span>
              <span className="text-muted-foreground text-xs">
                {invitation.role} ·{" "}
                {invitation.status === "accepted"
                  ? `accepted ${invitation.accepted_at ? when(invitation.accepted_at) : ""}`
                  : invitation.status === "expired"
                    ? `expired ${when(invitation.expires_at)}`
                    : `expires ${when(invitation.expires_at)}`}
              </span>
            </div>

            <Badge
              variant={
                invitation.status === "pending"
                  ? "secondary"
                  : invitation.status === "accepted"
                    ? "default"
                    : "outline"
              }
            >
              {invitation.status}
            </Badge>

            {invitation.status === "pending" ? (
              <form action={revoke}>
                <input type="hidden" name="workspace_id" value={workspaceId} />
                <input type="hidden" name="invitation_id" value={invitation.id} />
                <RevokeButton />
              </form>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
