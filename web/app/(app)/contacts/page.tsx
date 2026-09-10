import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateContact } from "./create-contact";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { StatusBadge } from "@/components/status-badge";
import { Input } from "@/components/ui/input";
import { listContacts } from "@/lib/inbox";
import { CONTACT_TONE } from "@/lib/tones";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Contacts" };

export default async function ContactsPage({
  searchParams,
}: {
  searchParams: Promise<{ search?: string; page?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { search, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  const contacts = await listContacts(workspace.id, {
    page,
    search: search ?? null,
  });

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Contacts"
        description={`The people ${workspace.name} talks to.`}
        actions={
          <form action="/contacts">
            <Input
              type="search"
              name="search"
              defaultValue={search ?? ""}
              placeholder="Name, number or email"
              className="w-56"
              maxLength={150}
              aria-label="Search contacts"
            />
          </form>
        }
      />

      {contacts.items.length === 0 ? (
        search ? (
          <EmptyState title="Nobody matches that">
            Search covers names, numbers and email addresses.
          </EmptyState>
        ) : (
          <EmptyState title="No contacts yet">
            A contact appears the first time somebody messages the connected
            number. You can also add one below.
          </EmptyState>
        )
      ) : (
        <ul className="grid gap-2">
          {contacts.items.map((contact) => (
            <li key={contact.id}>
              <Link
                href={`/contacts/${contact.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 row"
              >
                <span className="text-sm font-medium">
                  {contact.name ?? "No name"}
                </span>
                <span className="text-muted-foreground font-mono text-xs">
                  {contact.phone_number}
                </span>
                <StatusBadge
                  tone={CONTACT_TONE[contact.status]}
                  status={contact.status}
                  className="ml-auto"
                >
                  {contact.status}
                </StatusBadge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Pagination
        page={page}
        total={contacts.total}
        pageSize={contacts.page_size}
        noun="contacts"
        href={(to) =>
          `/contacts?page=${to}${search ? `&search=${encodeURIComponent(search)}` : ""}`
        }
      />

      <CreateContact workspaceId={workspace.id} />
    </div>
  );
}
