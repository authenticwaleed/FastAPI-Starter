"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  assignConversation,
  handoff,
  setStatus,
} from "@/lib/conversation-actions";
import type { FormState } from "@/lib/form-state";
import { STATE_LABEL } from "@/lib/labels";
import type { Conversation, Member } from "@/lib/types";

function Pending({ children }: { children: string }) {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      {children}
    </Button>
  );
}

/**
 * Status, assignment, and who is answering.
 *
 * The handoff control is one control in two states, and the state is the
 * conversation's `state` -- never something this component remembers. A
 * thread the assistant has is taken over; one a person has is handed back.
 * Reading it off the conversation is what keeps two agents' screens
 * agreeing about which it is.
 */
export function ThreadActions({
  workspaceId,
  conversation,
  members,
  canWrite,
}: {
  workspaceId: string;
  conversation: Conversation;
  members: Member[];
  canWrite: boolean;
}) {
  const [statusState, changeStatus] = useActionState<FormState, FormData>(
    setStatus,
    null,
  );
  const [assignState, assign] = useActionState<FormState, FormData>(
    assignConversation,
    null,
  );
  const [handoffState, changeHandoff] = useActionState<FormState, FormData>(
    handoff,
    null,
  );

  const closed = conversation.status === "closed";
  const withHuman = conversation.state === "human_active";
  const assistantOff = conversation.state === "ai_disabled";

  const hidden = (
    <>
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="conversation_id" value={conversation.id} />
    </>
  );

  const stale = statusState?.stale || assignState?.stale || handoffState?.stale;
  const error = statusState?.error ?? assignState?.error ?? handoffState?.error;

  return (
    <div className="grid gap-3 rounded-md border px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={closed ? "outline" : "secondary"}>
          {closed ? "Closed" : conversation.status === "pending" ? "Pending" : "Open"}
        </Badge>
        <span className="text-muted-foreground" data-testid="conversation-state">
          {STATE_LABEL[conversation.state]}
        </span>
      </div>

      {/*
        Not an error box. Two people working one inbox will race each
        other, and a thread somebody else closed a second ago is an
        ordinary outcome of that -- the view has already been refreshed.
      */}
      {stale ? (
        <p className="text-muted-foreground text-sm" role="status">
          {error} This thread has been refreshed.
        </p>
      ) : (
        <FormError>{error}</FormError>
      )}

      {canWrite ? (
        <div className="flex flex-wrap items-center gap-2">
          <form action={changeStatus}>
            {hidden}
            <input
              type="hidden"
              name="action"
              value={closed ? "reopen" : "close"}
            />
            <Pending>{closed ? "Reopen" : "Close"}</Pending>
          </form>

          {/* A closed thread offers reopening and nothing else. */}
          {!closed ? (
            <>
              <form action={changeHandoff}>
                {hidden}
                <input
                  type="hidden"
                  name="action"
                  value={withHuman ? "release" : "takeover"}
                />
                {/*
                  Handing back defaults to drafting rather than answering:
                  a thread somebody had to take over is not one to put
                  straight back on full automation. The API chooses that
                  default; this only names it.
                */}
                <input type="hidden" name="ai_mode" value="suggest_only" />
                <Pending>
                  {withHuman
                    ? assistantOff
                      ? "Turn the assistant on"
                      : "Hand back to the assistant"
                    : "Take over"}
                </Pending>
              </form>

              <form action={assign} className="flex items-center gap-2">
                {hidden}
                <label htmlFor="assignee" className="text-muted-foreground text-sm">
                  Assigned
                </label>
                <select
                  id="assignee"
                  name="user_id"
                  defaultValue={conversation.assigned_user?.id ?? ""}
                  className="border-input bg-background h-8 rounded-md border px-2 text-sm"
                >
                  <option value="">Nobody</option>
                  {members
                    .filter((member) => member.status === "active")
                    .map((member) => (
                      <option key={member.user_id} value={member.user_id}>
                        {member.name}
                      </option>
                    ))}
                </select>
                <Pending>Save</Pending>
              </form>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
