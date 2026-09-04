import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { ConversationRow } from "./conversation-row";
import { InboxFilters } from "./inbox-filters";
import {
  DEFAULT_STATUSES,
  INBOX_PAGE_SIZE,
  listConversations,
} from "@/lib/inbox";
import type { ConversationStatus } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Inbox" };

const STATUSES: ConversationStatus[] = ["open", "pending", "closed"];

function statusesFrom(raw: string | string[] | undefined): ConversationStatus[] {
  const asked = (Array.isArray(raw) ? raw : raw ? [raw] : []).filter(
    (value): value is ConversationStatus =>
      STATUSES.includes(value as ConversationStatus),
  );

  // Open *and* pending when nothing was asked for: a thread waiting on a
  // delivery has not been dealt with, it is only waiting. Closed is
  // something somebody asks for, never a default.
  return asked.length > 0 ? asked : DEFAULT_STATUSES;
}

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{
    status?: string | string[];
    assigned?: string;
    search?: string;
    page?: string;
  }>;
}) {
  const workspace = await activeWorkspace();

  // Everything here belongs to a workspace, so there is nothing to show
  // somebody who has none. W2 owns that screen.
  if (!workspace) redirect("/workspaces");

  const { status, assigned, search, page: rawPage } = await searchParams;

  const page = Math.max(1, Number(rawPage ?? 1) || 1);
  const statuses = statusesFrom(status);
  const unassigned = assigned === "none";

  const feed = await listConversations(workspace.id, {
    page,
    statuses,
    assignedTo: unassigned ? null : (assigned ?? null),
    unassigned,
    search: search ?? null,
  });

  const lastPage = Math.max(1, Math.ceil(feed.total / INBOX_PAGE_SIZE));
  const query = new URLSearchParams();

  for (const value of statuses) query.append("status", value);
  if (assigned) query.set("assigned", assigned);
  if (search) query.set("search", search);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {workspace.name} · {feed.total} conversation
            {feed.total === 1 ? "" : "s"}
          </p>
        </div>

        <Link href="/contacts" className="text-sm underline underline-offset-4">
          Contacts
        </Link>
      </div>

      <InboxFilters
        statuses={statuses}
        assigned={assigned ?? null}
        search={search ?? null}
      />

      {feed.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          Nothing matches. Conversations arrive when a customer messages the
          connected number, or when somebody opens one from a contact.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="conversation-list">
          {feed.items.map((conversation) => (
            <li key={conversation.id}>
              <ConversationRow conversation={conversation} />
            </li>
          ))}
        </ul>
      )}

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {page} of {lastPage}
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/inbox?${query}&page=${page - 1}`}
                className="underline underline-offset-4"
              >
                Newer
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/inbox?${query}&page=${page + 1}`}
                className="underline underline-offset-4"
              >
                Older
              </Link>
            ) : null}
          </span>
        </nav>
      ) : null}
    </div>
  );
}
