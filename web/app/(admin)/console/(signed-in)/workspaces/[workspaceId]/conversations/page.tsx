import type { Metadata } from "next";

import { ConversationRow } from "@/app/(app)/inbox/conversation-row";
import { ConsoleHeading } from "@/components/console/heading";
import { NeedsAccess } from "@/components/console/needs-access";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { SupportWindow } from "@/components/console/support-window";
import { EmptyState } from "@/components/empty-state";
import { CONSOLE_INBOX_PAGE_SIZE, listWorkspaceConversations } from "@/lib/console";
import { CONSOLE_WORDING } from "@/lib/console-labels";
import { ApiError } from "@/lib/errors";
import { supportWindowFor } from "@/lib/support-window";
import type { Conversation, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Their inbox" };

/**
 * A customer's inbox, read with a live grant and nothing else.
 *
 * The first screen in this client that shows what a business's own
 * customers wrote. Everything else on `/admin` is metadata; this is
 * people's messages, and it is behind a window somebody asked for with a
 * reason that the business can read in their own log.
 *
 * Rendered with the tenant's own row component, because the API serves it
 * from the same service and the same renderer the customer's dashboard
 * uses -- a second reading path would eventually show one of them
 * something the other cannot see. What changes is the voice: an agent's
 * message says "The team", never "You". A staff member is not on this
 * team, and a screen that said so would be the first place the console
 * started to look like a colleague.
 */
export default async function ConsoleConversationsPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { workspaceId } = await params;
  const { page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let inbox: Paged<Conversation>;

  try {
    inbox = await listWorkspaceConversations(workspaceId, { page });
  } catch (error) {
    // The refusal this phase exists around. Not a fault, and not a wall:
    // it means ask for access, so the form is right there.
    if (error instanceof ApiError && error.code === "support_access_required") {
      return <NeedsAccess title="Their inbox" workspaceId={workspaceId} />;
    }

    return consoleRefusal(error, {
      title: "Their inbox",
      missing: "No workspace exists with that id.",
    });
  }

  const supportWindow = await supportWindowFor(workspaceId);

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Their inbox"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description="Every thread the business has, in the order they see them."
      />

      {/*
        Always on screen while customer data is. Absent only when this
        browser was never told the expiry -- a grant asked for from another
        machine -- and the sentence says so rather than implying there is
        no window at all.
      */}
      {supportWindow ? (
        <SupportWindow
          workspaceId={workspaceId}
          expiresAt={supportWindow.expiresAt}
          now={supportWindow.now}
        />
      ) : (
        <p className="text-muted-foreground panel text-sm">
          You hold a window on this account that was opened somewhere else,
          so this console cannot say how long is left. It will stop working
          when it closes.
        </p>
      )}

      {inbox.items.length === 0 ? (
        <EmptyState title="This business has no conversations" />
      ) : (
        <ul className="grid gap-2" data-testid="console-inbox">
          {inbox.items.map((conversation) => (
            <li key={conversation.id}>
              <ConversationRow
                conversation={conversation}
                href={`/console/workspaces/${workspaceId}/conversations/${conversation.id}`}
                wording={CONSOLE_WORDING}
                // Off, like every other link in the console, and here it
                // matters most: a prefetched row is a customer's thread
                // read by nobody and recorded against somebody.
                prefetch={false}
              />
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={inbox.total}
        pageSize={CONSOLE_INBOX_PAGE_SIZE}
        noun="conversations"
        href={(to) =>
          `/console/workspaces/${workspaceId}/conversations?page=${to}`
        }
      />
    </div>
  );
}
