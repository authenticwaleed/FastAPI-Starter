import type { Metadata } from "next";

import { MessageThread } from "@/app/(app)/inbox/[conversationId]/message-thread";
import { ConsoleHeading } from "@/components/console/heading";
import { NeedsAccess } from "@/components/console/needs-access";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { SupportWindow } from "@/components/console/support-window";
import { CONSOLE_THREAD_PAGE_SIZE, listWorkspaceMessages } from "@/lib/console";
import { CONSOLE_WORDING } from "@/lib/console-labels";
import { ApiError } from "@/lib/errors";
import { messagesOldestFirst } from "@/lib/inbox";
import { supportWindowFor } from "@/lib/support-window";
import type { Message, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "A thread" };

/**
 * One thread, in full, and the deepest this client reaches into anybody's
 * account.
 *
 * The entry the API writes for this names the conversation rather than
 * only the workspace, because "they read the inbox" and "they read this
 * customer's thread with this person" are different answers to give
 * afterwards.
 *
 * There is no composer and there will not be one. Nothing on this surface
 * writes into a customer's workspace: the access a grant hands out carries
 * a staff actor rather than a membership, so its role is `viewer` and
 * every write in the application refuses it — but the honest reason there
 * is no box to type in is that support answering a customer's customer as
 * the business would be a different product.
 *
 * The thread is read with one request. The conversation's own row is not
 * fetched to head the page: that is a second read of a customer's inbox
 * for a heading, and it would be recorded as one.
 */
export default async function ConsoleThreadPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string; conversationId: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { workspaceId, conversationId } = await params;
  const { page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let thread: Paged<Message>;

  try {
    thread = await listWorkspaceMessages(workspaceId, conversationId, { page });
  } catch (error) {
    // A grant that ran out while this was open lands here, and so does one
    // that was never asked for. The API answers all three states the same
    // way, and so does this screen: ask for access.
    if (error instanceof ApiError && error.code === "support_access_required") {
      return <NeedsAccess title="A thread" workspaceId={workspaceId} />;
    }

    return consoleRefusal(error, {
      title: "A thread",
      missing: "No such conversation in this workspace.",
    });
  }

  const supportWindow = await supportWindowFor(workspaceId);

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="A thread"
        back={{
          href: `/console/workspaces/${workspaceId}/conversations`,
          label: "Their inbox",
        }}
        description="What this business's customer said to them, and what was said back. Read-only."
      />

      {supportWindow ? (
        <SupportWindow
          workspaceId={workspaceId}
          expiresAt={supportWindow.expiresAt}
          now={supportWindow.now}
        />
      ) : (
        <p className="text-muted-foreground rounded-md border px-4 py-3 text-sm">
          You hold a window on this account that was opened somewhere else,
          so this console cannot say how long is left. It will stop working
          when it closes.
        </p>
      )}

      <MessageThread
        messages={messagesOldestFirst(thread.items)}
        total={thread.total}
        wording={CONSOLE_WORDING}
      />

      <ConsolePages
        page={page}
        total={thread.total}
        pageSize={CONSOLE_THREAD_PAGE_SIZE}
        noun="messages"
        href={(to) =>
          `/console/workspaces/${workspaceId}/conversations/${conversationId}?page=${to}`
        }
      />
    </div>
  );
}
