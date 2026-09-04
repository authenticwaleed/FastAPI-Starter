import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { STATE_LABEL } from "@/lib/labels";
import type { Conversation } from "@/lib/types";

function when(value: string): string {
  const at = new Date(value);
  const today = new Date().toDateString() === at.toDateString();

  return at.toLocaleString(undefined, {
    ...(today ? {} : { month: "short", day: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * One row of the inbox.
 *
 * The API embeds the contact, the assignee and the last message in every
 * conversation it returns, so a row of thirty is one request rather than
 * ninety-one. Nothing here fetches anything.
 *
 * `sender_type` on the preview is what an agent is really scanning for: it
 * says whether the business is waiting on the customer or the customer is
 * waiting on the business.
 */
export function ConversationRow({ conversation }: { conversation: Conversation }) {
  const { contact, last_message: last } = conversation;
  const unread = conversation.unread_count > 0;
  const waitingOnUs = last?.sender_type === "customer";

  return (
    <Link
      href={`/inbox/${conversation.id}`}
      data-unread={unread ? "" : undefined}
      data-testid="conversation-row"
      className="hover:bg-accent/50 data-unread:border-l-primary grid gap-1 rounded-md border border-l-2 border-l-transparent px-3 py-2.5"
    >
      <div className="flex items-baseline gap-2">
        <span className="truncate text-sm font-medium">
          {contact.name ?? contact.phone_number}
        </span>

        {unread ? (
          <Badge variant="default" className="tabular-nums">
            {conversation.unread_count}
          </Badge>
        ) : null}

        {conversation.status === "closed" ? (
          <Badge variant="outline">Closed</Badge>
        ) : conversation.status === "pending" ? (
          <Badge variant="secondary">Pending</Badge>
        ) : null}

        <span className="text-muted-foreground ml-auto shrink-0 text-xs">
          {conversation.last_message_at ? when(conversation.last_message_at) : null}
        </span>
      </div>

      <p className="text-muted-foreground truncate text-sm">
        {last?.text ? (
          <>
            {/*
              Named rather than coloured. "Them" and "us" is the distinction
              an agent scans for, and it has to survive being read by
              somebody who cannot tell two greys apart.
            */}
            <span className="text-foreground/70">
              {waitingOnUs ? "" : last.sender_type === "ai" ? "Assistant: " : "You: "}
            </span>
            {last.text}
          </>
        ) : (
          "No messages yet"
        )}
      </p>

      <div className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
        <span>{STATE_LABEL[conversation.state]}</span>
        <span>
          {conversation.assigned_user
            ? `Assigned to ${conversation.assigned_user.name}`
            : "Unassigned"}
        </span>
      </div>
    </Link>
  );
}
