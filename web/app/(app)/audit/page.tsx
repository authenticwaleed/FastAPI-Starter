import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Refusal } from "@/components/refusal";
import { Badge } from "@/components/ui/badge";
import { listAuditLogs } from "@/lib/analytics";
import { ApiError } from "@/lib/errors";
import { describeEvent, describeTenantActor } from "@/lib/labels";
import type { AuditEntry, Page as Paged } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Audit log" };

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
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
          <PageHeader
            title="Audit log"
            description="Who changed what, and when."
          />

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
          <PageHeader
            title="Audit log"
            description="Who changed what, and when."
          />
          <p className="text-muted-foreground text-sm" data-testid="not-permitted">
            Only an owner or an admin can read this workspace&rsquo;s audit log.
          </p>
        </div>
      );
    }

    throw error;
  }

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Audit log"
        description={`Who changed what in ${workspace.name}, and when.`}
      />

      {log.items.length === 0 ? (
        <EmptyState title="Nothing recorded yet">
          Entries appear here when somebody changes something — a role, a
          setting, a connected number.
        </EmptyState>
      ) : (
        <ul className="grid gap-2" data-testid="audit-log">
          {log.items.map((entry) => (
            <li
              key={entry.id}
              data-event={entry.event}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 row"
            >
              <span className="min-w-0 flex-1 text-sm">{describeEvent(entry.event)}</span>

              <span className="text-muted-foreground truncate text-xs">
                {describeTenantActor(entry)}
              </span>

              <span className="text-muted-foreground text-xs">
                {when(entry.created_at)}
              </span>

              <Badge variant="outline" className="font-mono text-2xs">
                {entry.event}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      <Pagination
        page={page}
        total={log.total}
        pageSize={log.page_size}
        noun="entries"
        labels={{ previous: "Newer", next: "Older" }}
        href={(to) => `/audit?page=${to}`}
      />
    </div>
  );
}
