import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { ContactForm } from "./contact-form";
import { OpenConversation } from "./open-conversation";
import { ConversationRow } from "../../inbox/conversation-row";
import { EmptyState } from "@/components/empty-state";
import { BackLink, PageHeader, SectionHeader } from "@/components/page-header";
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
      <PageHeader
        back={<BackLink href="/contacts" label="Contacts" />}
        title={contact.name ?? contact.phone_number}
        description={
          <span className="font-mono">{contact.phone_number}</span>
        }
      />

      <section className="grid gap-3">
        <SectionHeader
          title="Conversations"
          actions={
            <OpenConversation workspaceId={workspace.id} contact={contact} />
          }
        />

        {conversations.items.length === 0 ? (
          // An empty state, not an error. A contact somebody added a moment
          // ago has no threads yet, and that is the ordinary case.
          <EmptyState title="Nothing yet with this contact">
            Threads appear here when this person messages you, or when
            somebody opens one from this screen.
          </EmptyState>
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
