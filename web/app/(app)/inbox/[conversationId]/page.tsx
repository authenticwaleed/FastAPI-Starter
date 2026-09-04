import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { AssistantPanel } from "./assistant-panel";
import { Composer } from "./composer";
import { ContactPanel } from "./contact-panel";
import { MarkRead } from "./mark-read";
import { MessageThread } from "./message-thread";
import { ThreadActions } from "./thread-actions";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import {
  listAiResponses,
  listEvents,
  listMessages,
  messagesOldestFirst,
  readConversation,
} from "@/lib/inbox";
import type { Conversation, Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Conversation" };

/** Who may write here. A viewer reads the thread and sends nothing. */
const MAY_HANDLE_CUSTOMERS = ["owner", "admin", "agent"];

export default async function ConversationPage({
  params,
  searchParams,
}: {
  params: Promise<{ conversationId: string }>;
  searchParams: Promise<{ stale?: string }>;
}) {
  const [{ conversationId }, { stale }] = await Promise.all([params, searchParams]);
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  let conversation: Conversation;

  try {
    conversation = await readConversation(workspace.id, conversationId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const [messages, events, assistant, user, members] = await Promise.all([
    listMessages(workspace.id, conversationId),
    listEvents(workspace.id, conversationId),
    listAiResponses(workspace.id, conversationId),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const canWrite =
    mine !== undefined &&
    MAY_HANDLE_CUSTOMERS.includes(mine.role) &&
    workspace.status === "active";

  const closed = conversation.status === "closed";

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Link
            href="/inbox"
            className="text-muted-foreground text-sm underline-offset-4 hover:underline"
          >
            ← Inbox
          </Link>
          <h1 className="text-xl font-semibold tracking-tight">
            {conversation.contact.name ?? conversation.contact.phone_number}
          </h1>
        </div>

        <ThreadActions
          workspaceId={workspace.id}
          conversation={conversation}
          members={members}
          canWrite={canWrite}
        />

        <MessageThread
          messages={messagesOldestFirst(messages.items)}
          total={messages.total}
        />

        {/*
          A closed conversation offers reopening and nothing else. The API
          refuses a reply to one, so a composer here would be a control
          whose only outcome is a refusal.
        */}
        {stale ? (
          // Somebody else moved first while this page was open. Said
          // plainly, because the reply that was typed did not go anywhere
          // and the screen changing under them does not explain itself.
          <p
            role="status"
            className="text-muted-foreground rounded-md border px-3 py-2 text-sm"
          >
            Your reply was not sent — this conversation was closed while you
            were writing. The thread has been refreshed.
          </p>
        ) : null}

        {closed ? (
          <p className="text-muted-foreground rounded-md border border-dashed px-3 py-4 text-center text-sm">
            This conversation is closed. Reopen it to reply.
          </p>
        ) : canWrite ? (
          <Composer workspaceId={workspace.id} conversation={conversation} />
        ) : (
          // Absent rather than disabled, unlike the workspace settings
          // form. There is nothing here for a viewer to read off a
          // greyed-out box, and a permanently dead composer is worse than
          // none at all.
          <p className="text-muted-foreground text-sm">
            You can read this conversation. Replying needs the agent role.
          </p>
        )}

        <MarkRead
          workspaceId={workspace.id}
          conversationId={conversation.id}
          unread={conversation.unread_count}
        />
      </div>

      <aside className="grid gap-4">
        <ContactPanel contact={conversation.contact} events={events.items} />
        <AssistantPanel
          workspaceId={workspace.id}
          conversation={conversation}
          history={assistant.items}
          canWrite={canWrite && !closed}
        />
      </aside>
    </div>
  );
}
