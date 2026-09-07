import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Refusal } from "@/components/refusal";
import { Badge } from "@/components/ui/badge";
import { listAuditLogs } from "@/lib/analytics";
import { ApiError } from "@/lib/errors";
import type { AuditEntry, Page as Paged } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Audit log" };

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** The API's event names, as a sentence. Unknown ones show as they are. */
function describe(event: string): string {
  const said: Record<string, string> = {
    "workspace.created": "Workspace created",
    "workspace.updated": "Workspace settings changed",
    "workspace.closed": "Workspace closed",
    "member.invited": "Somebody was invited",
    "member.joined": "Somebody joined",
    "member.role_changed": "A role was changed",
    "member.removed": "Somebody left or was removed",
    "whatsapp.connected": "WhatsApp connected",
    "whatsapp.disconnected": "WhatsApp disconnected",
    "knowledge.document_uploaded": "A document was added",
    "knowledge.document_deleted": "A document was deleted",
    "conversation.assigned": "A conversation was assigned",
    "conversation.closed": "A conversation was closed",
    "conversation.ai_disabled": "The assistant was switched off for a thread",
    "subscription.changed": "The subscription changed",
    "api_key.created": "An API key was created",
    "api_key.revoked": "An API key was revoked",
    "support.access_granted": "Support was given access",
    "support.access_ended": "Support access ended",
    "workspace.suspended": "The workspace was suspended",
    "workspace.unsuspended": "The suspension was lifted",
    "workspace.restored": "The workspace was restored",
  };

  return said[event] ?? event;
}

/**
 * What the business did to itself.
 *
 * A Business-plan feature, and a workspace without it gets the upgrade
 * prompt rather than a 403 page — the plan is what is in the way and the
 * plan is something they can change, which is the whole reason the API
 * answers 402 here rather than 403.
 */
export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; event?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { page: rawPage, event } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let log: Paged<AuditEntry>;

  try {
    log = await listAuditLogs(workspace.id, { page, event: event ?? null });
  } catch (error) {
    if (error instanceof ApiError && error.status === 402) {
      return (
        <div className="grid gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
            <p className="text-muted-foreground mt-1 text-sm">
              Who changed what, and when.
            </p>
          </div>

          {/*
            The criterion: a prompt, not a wall. Every other 402 in this
            client renders the same component, and this is why it takes a
            state rather than only being reachable from a form.
          */}
          <Refusal state={{ error: error.sentence, code: error.code }} />

          <p className="text-muted-foreground text-sm">
            The log is being kept either way — switching to a plan that
            includes it shows everything from before you did.
          </p>
        </div>
      );
    }

    if (error instanceof ApiError && error.status === 403) {
      // A role problem rather than a plan one, and the difference is where
      // it sends somebody: to an administrator, not to the billing page.
      return (
        <div className="grid gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
            <p className="text-muted-foreground mt-1 text-sm">
              Who changed what, and when.
            </p>
          </div>
          <p className="text-muted-foreground text-sm" data-testid="not-permitted">
            Only an owner or an admin can read this workspace&rsquo;s audit log.
          </p>
        </div>
      );
    }

    throw error;
  }

  const lastPage = Math.max(1, Math.ceil(log.total / log.page_size));

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Who changed what in {workspace.name}, and when.
        </p>
      </div>

      {log.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          Nothing recorded yet.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="audit-log">
          {log.items.map((entry) => (
            <li
              key={entry.id}
              data-event={entry.event}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
            >
              <span className="min-w-0 flex-1 text-sm">{describe(entry.event)}</span>

              <span className="text-muted-foreground truncate text-xs">
                {/*
                  A null actor is a real entry rather than missing data: a
                  payment provider changed a subscription, and naming
                  somebody would put an accusation in the record. An actor
                  with an address and no id is a deleted account, which is
                  the case this table exists to outlive.
                */}
                {entry.actor === null
                  ? "Not a person"
                  : (entry.actor.name ?? entry.actor.email ?? "A deleted account")}
              </span>

              <span className="text-muted-foreground text-xs">
                {when(entry.created_at)}
              </span>

              <Badge variant="outline" className="font-mono text-[10px]">
                {entry.event}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {page} of {lastPage} · {log.total} entries
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/audit?page=${page - 1}`}
                className="underline underline-offset-4"
              >
                Newer
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/audit?page=${page + 1}`}
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
