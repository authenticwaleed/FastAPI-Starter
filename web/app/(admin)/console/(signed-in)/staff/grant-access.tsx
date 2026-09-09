"use client";

import { useActionState, useState } from "react";

import { Refused } from "@/components/console/refused";
import { FieldError, SubmitButton } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { STAFF_ROLE_LABEL, when } from "@/lib/console-labels";
import type { FormState } from "@/lib/form-state";
import { grantStaffAccess, requestOwnerApproval } from "@/lib/staff-actions";
import type { Approval, StaffRole } from "@/lib/types";

const RANKS: StaffRole[] = ["support", "admin", "owner"];

/**
 * Promoting an account, and the colleague an owner promotion needs.
 *
 * Support and admin are ordinary promotions that one person decides.
 * Owner is not: an owner can promote anybody and erase any business, so
 * it is the one rank the API asks a second staff member to agree to —
 * and requiring that for every support engineer would mean nobody could
 * be added on a Friday.
 *
 * The rank is client state here, which is the exception rather than the
 * habit: nothing is fetched for it, and it decides only which of two
 * forms is on screen. What the API does with a missing approval is still
 * the authority, and the refusal renders if this guesses wrong.
 */
export function GrantAccess({
  userId,
  ready,
  waiting,
}: {
  userId: string | null;
  ready: Approval | null;
  waiting: Approval | null;
}) {
  const [role, setRole] = useState<StaffRole>("support");
  const [grantState, grant] = useActionState<FormState, FormData>(
    grantStaffAccess,
    null,
  );
  const [askState, ask] = useActionState<FormState, FormData>(
    requestOwnerApproval,
    null,
  );

  const needsColleague = role === "owner" && ready === null;

  return (
    <div className="grid max-w-xl gap-4">
      <form action={grant} className="grid gap-4" data-testid="grant-access">
        <Refused state={grantState} />

        {grantState?.done ? (
          <p className="text-muted-foreground text-sm" data-testid="granted">
            That account now has platform access.
          </p>
        ) : null}

        <div className="grid gap-2">
          <Label htmlFor="user_id">Account id</Label>
          <Input
            id="user_id"
            name="user_id"
            type="number"
            min={1}
            required
            defaultValue={userId ?? ""}
            className="w-40"
          />
          <FieldError>{grantState?.fields?.user_id}</FieldError>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="role">Rank</Label>
          <select
            id="role"
            name="role"
            value={role}
            onChange={(event) => setRole(event.target.value as StaffRole)}
            className="border-input bg-background h-8 w-48 rounded-md border px-2 text-sm shadow-xs"
          >
            {RANKS.map((rank) => (
              <option key={rank} value={rank}>
                {STAFF_ROLE_LABEL[rank]}
              </option>
            ))}
          </select>
        </div>

        {ready ? (
          <>
            <input type="hidden" name="approval_id" value={ready.id} />
            <p className="text-muted-foreground text-xs" data-testid="approval-ready">
              {ready.approved_by ?? "A colleague"} agreed to this promotion,
              and it lapses at {when(ready.expires_at)}. If that was you, the
              API refuses — it takes two people.
            </p>
          </>
        ) : null}

        {needsColleague ? (
          <p className="text-muted-foreground text-sm" data-testid="owner-needs-approval">
            An owner promotion needs a second staff member to agree to it.
            Ask below, then come back once somebody has.
          </p>
        ) : (
          <SubmitButton className="w-fit">Give access</SubmitButton>
        )}
      </form>

      {needsColleague ? (
        waiting ? (
          <div className="grid gap-2 rounded-md border px-3 py-2.5" data-testid="owner-approval-pending">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Waiting for a colleague</span>
              <Badge variant="outline">pending</Badge>
            </div>
            <p className="text-sm">{waiting.reason}</p>
            <p className="text-muted-foreground text-xs">
              Asked by {waiting.requested_by ?? "somebody"} on{" "}
              {when(waiting.created_at)}, lapsing at {when(waiting.expires_at)}.
            </p>
          </div>
        ) : (
          <form action={ask} className="grid gap-3 rounded-md border px-3 py-2.5">
            <input type="hidden" name="user_id" value={userId ?? ""} />

            <Refused state={askState} />

            <div className="grid gap-2">
              <Label htmlFor="approval_reason">
                What you are asking them to agree to
              </Label>
              <Textarea
                id="approval_reason"
                name="reason"
                required
                minLength={10}
                maxLength={500}
                rows={2}
                placeholder="Taking over platform ownership while the current owner is on leave"
              />
              <FieldError>{askState?.fields?.reason}</FieldError>
            </div>

            <SubmitButton className="w-fit">Ask a colleague</SubmitButton>
          </form>
        )
      ) : null}
    </div>
  );
}
