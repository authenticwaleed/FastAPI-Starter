import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateContact } from "./create-contact";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { listContacts } from "@/lib/inbox";
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

  const lastPage = Math.max(1, Math.ceil(contacts.total / contacts.page_size));

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Contacts</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            The people {workspace.name} talks to.
          </p>
        </div>

        <form action="/contacts">
          <Input
            type="search"
            name="search"
            defaultValue={search ?? ""}
            placeholder="Name, number or email"
            className="h-8 w-56"
            maxLength={150}
            aria-label="Search contacts"
          />
        </form>
      </div>

      {contacts.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          {search
            ? "Nobody matches that."
            : "No contacts yet. Add one below, or wait for somebody to message the connected number."}
        </p>
      ) : (
        <ul className="grid gap-2">
          {contacts.items.map((contact) => (
            <li key={contact.id}>
              <Link
                href={`/contacts/${contact.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
              >
                <span className="text-sm font-medium">
                  {contact.name ?? "No name"}
                </span>
                <span className="text-muted-foreground font-mono text-xs">
                  {contact.phone_number}
                </span>
                <Badge
                  variant={contact.status === "blocked" ? "destructive" : "secondary"}
                  className="ml-auto"
                >
                  {contact.status}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {page} of {lastPage} · {contacts.total} in total
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/contacts?page=${page - 1}${search ? `&search=${search}` : ""}`}
                className="underline underline-offset-4"
              >
                Previous
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/contacts?page=${page + 1}${search ? `&search=${search}` : ""}`}
                className="underline underline-offset-4"
              >
                Next
              </Link>
            ) : null}
          </span>
        </nav>
      ) : null}

      <CreateContact workspaceId={workspace.id} />
    </div>
  );
}
