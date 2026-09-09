"use client";

import { useActionState } from "react";

import { Refused } from "@/components/console/refused";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { STAFF_ROLE_LABEL, when } from "@/lib/console-labels";
import type { FormState } from "@/lib/form-state";
import { changeStaffRole, revokeStaffAccess } from "@/lib/staff-actions";
import type { StaffMember, StaffRole } from "@/lib/types";

const RANKS: StaffRole[] = ["support", "admin", "owner"];

/**
 * One colleague, and what may be done about them.
 *
 * Your own row carries a sentence instead of the two controls, and it is
 * worth being exact about why, because it is the one place in this client
 * that withholds something the API would allow.
 *
 * The API refuses to strand the *last* owner and nothing more: with two
 * owners, revoking yourself succeeds. What it cannot know is that the
 * person it just signed out of the console is the one holding the mouse
 * — and only an owner can grant access, so undoing it means finding a
 * colleague. So the sentence talks about the consequence rather than
 * claiming a permission that does not exist, and there is no control to
 * press by accident.
 *
 * The last owner's row says the same thing for the API's reason instead.
 * Both rows still meet a real refusal if somebody reaches the endpoint
 * another way; a hidden control is never assumed to be an enforced one.
 */
export function StaffRow({
  member,
  yours,
  lastOwner = false,
}: {
  member: StaffMember;
  yours: boolean;
  lastOwner?: boolean;
}) {
  const [roleState, changeRole] = useActionState<FormState, FormData>(
    changeStaffRole,
    null,
  );
  const [revokeState, revoke] = useActionState<FormState, FormData>(
    revokeStaffAccess,
    null,
  );

  const revoked = member.revoked_at !== null;

  return (
    <li
      className="grid gap-2 rounded-md border px-3 py-2.5"
      data-testid="staff-row"
      data-user={member.user_id}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-medium">{member.name}</span>
        <span className="text-muted-foreground truncate text-xs">
          {member.email}
        </span>

        {yours ? <Badge variant="outline">you</Badge> : null}

        <span className="text-muted-foreground ml-auto text-xs">
          {revoked
            ? `Ended ${when(member.revoked_at as string)}`
            : `Since ${when(member.granted_at)}`}
        </span>

        <Badge variant={revoked ? "outline" : "secondary"}>
          {STAFF_ROLE_LABEL[member.role]}
        </Badge>
      </div>

      <Refused state={roleState} />
      <Refused state={revokeState} />

      {revoked ? null : yours ? (
        <p className="text-muted-foreground text-xs" data-testid="your-own-row">
          Your own access. Changing it here would sign you out of the console,
          and only an owner could put you back — ask a colleague to do it.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <form action={changeRole} className="flex items-center gap-2">
            <input type="hidden" name="user_id" value={member.user_id} />
            <label className="text-muted-foreground text-xs" htmlFor={`role-${member.user_id}`}>
              Rank
            </label>
            <select
              id={`role-${member.user_id}`}
              name="role"
              defaultValue={member.role}
              className="border-input bg-background h-7 rounded-md border px-2 text-xs shadow-xs"
            >
              {RANKS.map((rank) => (
                <option key={rank} value={rank}>
                  {STAFF_ROLE_LABEL[rank]}
                </option>
              ))}
            </select>
            <Button type="submit" variant="outline" size="xs">
              Change
            </Button>
          </form>

          <form action={revoke}>
            <input type="hidden" name="user_id" value={member.user_id} />
            <Button type="submit" variant="ghost" size="xs">
              Take access away
            </Button>
          </form>

          {lastOwner ? (
            <span className="text-muted-foreground text-xs">
              The last owner. The platform must keep one, so both of these are
              refused.
            </span>
          ) : null}
        </div>
      )}
    </li>
  );
}
