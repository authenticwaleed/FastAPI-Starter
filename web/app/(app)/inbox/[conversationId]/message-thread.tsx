import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { TENANT_WORDING, type InboxWording } from "@/lib/labels";
import type { Message } from "@/lib/types";

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * The thread, oldest at the top.
 *
 * The API returns newest first, which is what a chat screen opens with and
 * what makes paging back the same as scrolling up. The reversal happens
 * once, in `messagesOldestFirst`, rather than in a `flex-col-reverse` that
 * would also reverse the tab order.
 *
 * `queued` is shown rather than hidden. Everything this API sends is queued
 * and stays queued until the messaging phase delivers it, so a screen that
 * implied "sent" would be telling an agent their customer has the reply.
 *
 * `wording` defaults to the inbox this was written for and the console
 * passes its own, because the same thread is read by two different
 * people: here an agent's message is "You", and on the console it is the
 * team's. A staff member reading a customer's account is not on that
 * team, and the one word is where a screen would first suggest otherwise.
 */
export function MessageThread({
  messages,
  total,
  wording = TENANT_WORDING,
}: {
  messages: Message[];
  total: number;
  wording?: InboxWording;
}) {
  if (messages.length === 0) {
    return (
      <EmptyState title="Nothing has been said yet" data-testid="message-thread" />
    );
  }

  return (
    <div className="grid gap-3" data-testid="message-thread">
      {total > messages.length ? (
        <p className="text-muted-foreground text-center text-xs">
          Showing the last {messages.length} of {total}.
        </p>
      ) : null}

      <ol className="grid gap-3">
        {messages.map((message) => {
          const fromThem = message.direction === "inbound";

          return (
            <li
              key={message.id}
              data-sender={message.sender_type}
              className={
                fromThem
                  ? "max-w-[38rem] justify-self-start"
                  : "max-w-[38rem] justify-self-end"
              }
            >
              <div
                className={
                  fromThem
                    ? "bg-muted rounded-lg rounded-bl-sm px-3 py-2"
                    : "bg-primary text-primary-foreground rounded-lg rounded-br-sm px-3 py-2"
                }
              >
                <p className="text-sm whitespace-pre-wrap">{message.text}</p>
              </div>

              <div
                className={`text-muted-foreground mt-1 flex items-center gap-2 text-xs ${
                  fromThem ? "" : "justify-end"
                }`}
              >
                <span>{wording.voice[message.sender_type]}</span>
                <span>{when(message.created_at)}</span>
                {message.status === "queued" ? (
                  <Badge variant="outline" className="text-2xs">
                    Queued
                  </Badge>
                ) : null}
                {message.status === "failed" ? (
                  <Badge variant="destructive" className="text-2xs">
                    Failed
                  </Badge>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
