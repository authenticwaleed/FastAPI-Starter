"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { SectionHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { changeMemberRole, removeMember } from "@/lib/member-actions";
import type { FormState } from "@/lib/form-state";
import { ROLE_DESCRIPTION, grantableBy, mayManage } from "@/lib/roles";
import type { Member } from "@/lib/types";

function Saving({ children }: { children: string }) {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      {children}
    </Button>
  );
}

/**
 * The team, and what this person may do to each row.
 *
 * A control is shown only where `mayManage` says the API would allow it,
 * and the reason is written beside the rows where it would not. An admin
 * looking at an owner sees "only an owner can change this" rather than a
 * button that always fails -- which is the acceptance criterion, and also
 * just the difference between a screen that explains itself and one that
 * argues with you.
 *
 * The picker offers only roles this person may grant. The API checks the
 * role being handed out as well as the one being taken away, because
 * otherwise an admin could not demote another admin but could still make
 * an agent into one, which is the same privilege through another door.
 */
export function MemberList({
  workspaceId,
  members,
  me,
  canManage,
}: {
  workspaceId: string;
  members: Member[];
  me: Member;
  canManage: boolean;
}) {
  const [roleState, changeRole] = useActionState<FormState, FormData>(
    changeMemberRole,
    null,
  );
  const [removeState, remove] = useActionState<FormState, FormData>(
    removeMember,
    null,
  );

  const grantable = grantableBy(me.role);

  return (
    <section className="grid gap-3">
      <SectionHeader title="Members" />

      <FormError>{roleState?.error ?? removeState?.error}</FormError>

      <ul className="grid gap-2" data-testid="member-list">
        {members
          .filter((member) => member.status === "active")
          .map((member) => {
            const isMe = member.user_id === me.user_id;
            const manageable = canManage && !isMe && mayManage(me.role, member.role);

            return (
              <li
                key={member.user_id}
                data-role={member.role}
                className="flex flex-wrap items-center gap-x-3 gap-y-2 row"
              >
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="flex items-center gap-2 text-sm">
                    {member.name}
                    {isMe ? <Badge variant="secondary">You</Badge> : null}
                  </span>
                  <span className="text-muted-foreground truncate text-xs">
                    {member.email}
                  </span>
                </div>

                {manageable ? (
                  <form action={changeRole} className="flex items-center gap-2">
                    <input type="hidden" name="workspace_id" value={workspaceId} />
                    <input type="hidden" name="user_id" value={member.user_id} />
                    <label htmlFor={`role-${member.user_id}`} className="sr-only">
                      Role for {member.name}
                    </label>
                    <NativeSelect
                      id={`role-${member.user_id}`}
                      name="role"
                      defaultValue={member.role}
                    >
                      {grantable.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </NativeSelect>
                    <Saving>Save</Saving>
                  </form>
                ) : (
                  <Badge variant="outline">{member.role}</Badge>
                )}

                {manageable ? (
                  <form action={remove}>
                    <input type="hidden" name="workspace_id" value={workspaceId} />
                    <input type="hidden" name="user_id" value={member.user_id} />
                    <Saving>Remove</Saving>
                  </form>
                ) : !isMe && canManage ? (
                  // The criterion: say why, rather than showing a control
                  // that would only be refused.
                  <span className="text-muted-foreground text-xs">
                    Only an owner can change this
                  </span>
                ) : null}
              </li>
            );
          })}
      </ul>

      <dl className="text-muted-foreground grid gap-1 text-xs">
        {grantable.map((role) => (
          <div key={role} className="flex gap-2">
            <dt className="font-medium">{role}</dt>
            <dd>{ROLE_DESCRIPTION[role]}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
