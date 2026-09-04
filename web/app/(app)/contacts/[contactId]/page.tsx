import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ContactForm } from "./contact-form";
import { OpenConversation } from "./open-conversation";
import { ConversationRow } from "../../inbox/conversation-row";
import { ApiError } from "@/lib/errors";
import { DEFAULT_STATUSES, listConversations, readContact } from "@/lib/inbox";
import type { Contact } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Contact" };

export default async function ContactPage({
  params,
}: {
  params: Promise<{ contactId: string }>;
}) {
  const { contactId } = await params;
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  let contact: Contact;

  try {
    contact = await readContact(workspace.id, contactId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  // Every thread with this person, closed ones included: on a profile the
  // question is "what have we said to them", which does not stop at the
  // ones still open.
  const conversations = await listConversations(workspace.id, {
    page: 1,
    statuses: [...DEFAULT_STATUSES, "closed"],
    assignedTo: null,
    unassigned: false,
    search: null,
    contactId: contact.id,
  });

  return (
    <div className="grid gap-8">
      <div>
        <Link
          href="/contacts"
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          ← Contacts
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {contact.name ?? contact.phone_number}
        </h1>
        <p className="text-muted-foreground mt-1 font-mono text-sm">
          {contact.phone_number}
        </p>
      </div>

      <section className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-medium">Conversations</h2>
          <OpenConversation workspaceId={workspace.id} contact={contact} />
        </div>

        {conversations.items.length === 0 ? (
          // An empty state, not an error. A contact somebody added a moment
          // ago has no threads yet, and that is the ordinary case.
          <p className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm">
            Nothing yet with this contact.
          </p>
        ) : (
          <ul className="grid gap-2">
            {conversations.items.map((conversation) => (
              <li key={conversation.id}>
                <ConversationRow conversation={conversation} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <ContactForm workspaceId={workspace.id} contact={contact} />
    </div>
  );
}
