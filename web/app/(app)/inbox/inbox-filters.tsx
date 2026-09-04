import Link from "next/link";

import { Input } from "@/components/ui/input";
import type { ConversationStatus } from "@/lib/types";

/**
 * The three questions somebody scanning an inbox actually asks.
 *
 * Links rather than a form, so each view has an address that can be
 * bookmarked, shared in a message, and opened in a second tab. A filter
 * bar that only lived in client state would make "the unassigned ones" a
 * thing you cannot send to a colleague.
 *
 * Search is a form because it carries a value, and it matches the contact
 * rather than what was said inside the threads -- whoever is looking has a
 * person in mind, and searching message bodies is a different feature with
 * a different index behind it.
 */
function tab(active: boolean) {
  return active
    ? "font-medium underline underline-offset-4"
    : "text-muted-foreground underline-offset-4 hover:underline";
}

export function InboxFilters({
  statuses,
  assigned,
  search,
}: {
  statuses: ConversationStatus[];
  assigned: string | null;
  search: string | null;
}) {
  const showingClosed = statuses.includes("closed");
  const keep = new URLSearchParams();

  if (assigned) keep.set("assigned", assigned);
  if (search) keep.set("search", search);

  const withStatus = (values: ConversationStatus[]) => {
    const query = new URLSearchParams(keep);

    for (const value of values) query.append("status", value);

    return `/inbox?${query}`;
  };

  const withAssigned = (value: string | null) => {
    const query = new URLSearchParams();

    for (const status of statuses) query.append("status", status);
    if (value) query.set("assigned", value);
    if (search) query.set("search", search);

    return `/inbox?${query}`;
  };

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-y py-3 text-sm">
      <div className="flex items-center gap-3">
        <span className="text-muted-foreground text-xs uppercase">Status</span>
        <Link href={withStatus(["open", "pending"])} className={tab(!showingClosed)}>
          Live
        </Link>
        <Link href={withStatus(["closed"])} className={tab(showingClosed)}>
          Closed
        </Link>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-muted-foreground text-xs uppercase">Who</span>
        <Link href={withAssigned(null)} className={tab(assigned === null)}>
          Everyone
        </Link>
        <Link href={withAssigned("me")} className={tab(assigned === "me")}>
          Mine
        </Link>
        <Link href={withAssigned("none")} className={tab(assigned === "none")}>
          Unassigned
        </Link>
      </div>

      <form action="/inbox" className="ml-auto flex items-center gap-2">
        {statuses.map((status) => (
          <input key={status} type="hidden" name="status" value={status} />
        ))}
        {assigned ? <input type="hidden" name="assigned" value={assigned} /> : null}
        <Input
          type="search"
          name="search"
          defaultValue={search ?? ""}
          placeholder="Search contacts"
          className="h-8 w-48"
          maxLength={150}
          aria-label="Search contacts"
        />
      </form>
    </div>
  );
}
