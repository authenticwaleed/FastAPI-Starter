import { FilterBar, FilterGroup } from "@/components/filter-tabs";
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
    <FilterBar>
      <FilterGroup
        label="Status"
        options={[
          {
            value: "live",
            label: "Live",
            href: withStatus(["open", "pending"]),
            active: !showingClosed,
          },
          {
            value: "closed",
            label: "Closed",
            href: withStatus(["closed"]),
            active: showingClosed,
          },
        ]}
      />

      <FilterGroup
        label="Who"
        options={[
          {
            value: "everyone",
            label: "Everyone",
            href: withAssigned(null),
            active: assigned === null,
          },
          {
            value: "me",
            label: "Mine",
            href: withAssigned("me"),
            active: assigned === "me",
          },
          {
            value: "none",
            label: "Unassigned",
            href: withAssigned("none"),
            active: assigned === "none",
          },
        ]}
      />

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
          className="w-48"
          maxLength={150}
          aria-label="Search contacts"
        />
      </form>
    </FilterBar>
  );
}
