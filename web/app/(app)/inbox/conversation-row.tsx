import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { TENANT_WORDING, type InboxWording } from "@/lib/labels";
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
 *
 * `href`, `wording` and `prefetch` default to the inbox this was written
 * for, and the console passes its own. Two components would eventually be
 * two answers to "what does this thread look like", which the API refuses
 * to allow at its end -- it serves both surfaces from one service and one
 * renderer for exactly that reason.
 *
 * Two things must differ. The wording: on the console an agent's message
 * is the *team's*, never "You", and nothing is addressed to the person
 * reading. And prefetching, which has to be off there --
 * a prefetched console route is a read of `/admin`, and a prefetched row
 * of this list would record a support engineer as having opened a
 * customer's thread they never looked at. That is the worst row this
 * client could write, which is why the console's own e2e checks the
 * platform log for it rather than trusting the prop.
 */
export function ConversationRow({
  conversation,
  href,
  wording = TENANT_WORDING,
  prefetch,
}: {
  conversation: Conversation;
  href?: string;
  wording?: InboxWording;
  prefetch?: boolean;
}) {
  const { contact, last_message: last } = conversation;
  const unread = conversation.unread_count > 0;
  const waitingOnUs = last?.sender_type === "customer";

  return (
    <Link
      href={href ?? `/inbox/${conversation.id}`}
      prefetch={prefetch}
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
              {waitingOnUs ? "" : `${wording.voice[last.sender_type]}: `}
            </span>
            {last.text}
          </>
        ) : (
          "No messages yet"
        )}
      </p>

      <div className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
        <span>{wording.state[conversation.state]}</span>
        <span>
          {conversation.assigned_user
            ? `Assigned to ${conversation.assigned_user.name}`
            : "Unassigned"}
        </span>
      </div>
    </Link>
  );
}
