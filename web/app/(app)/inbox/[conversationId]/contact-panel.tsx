import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { ContactSummary, ConversationEvent } from "@/lib/types";

/** The handoff history, in words rather than in the API's vocabulary. */
const EVENT: Record<string, string> = {
  ai_handoff: "The assistant handed this over",
  human_takeover: "Taken over by a person",
  released_to_ai: "Handed back to the assistant",
  assigned: "Assigned",
  unassigned: "Unassigned",
  closed: "Closed",
  reopened: "Reopened",
};

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Who the thread is with, and who has had it.
 *
 * The summary is what the conversation already carries -- a name, a number
 * and a badge -- so this fetches nothing. The full profile is a page of its
 * own, linked rather than inlined, because an inbox is for answering
 * people and not for editing records.
 */
export function ContactPanel({
  contact,
  events,
}: {
  contact: ContactSummary;
  events: ConversationEvent[];
}) {
  return (
    <section className="grid gap-3 rounded-md border px-3 py-3">
      <h2 className="text-sm font-medium">Contact</h2>

      <div className="grid gap-1">
        <div className="flex items-center gap-2">
          <span className="text-sm">{contact.name ?? "No name yet"}</span>
          <Badge variant={contact.status === "blocked" ? "destructive" : "secondary"}>
            {contact.status}
          </Badge>
        </div>
        <span className="text-muted-foreground font-mono text-xs">
          {contact.phone_number}
        </span>
        <Link
          href={`/contacts/${contact.id}`}
          className="text-xs underline underline-offset-4"
        >
          Open profile
        </Link>
      </div>

      {events.length > 0 ? (
        <div className="grid gap-1.5">
          <h3 className="text-muted-foreground text-xs uppercase">History</h3>
          <ol className="grid gap-1">
            {events.map((event) => (
              <li key={event.id} className="text-muted-foreground text-xs">
                <span className="text-foreground/80">
                  {EVENT[event.event_type] ?? event.event_type}
                </span>
                {/*
                  A null actor means the assistant did it: it is the only
                  actor here that is not a person.
                */}
                {event.actor_user_id === null ? " (assistant)" : ""}
                {event.reason ? ` — ${event.reason}` : ""} · {when(event.created_at)}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
