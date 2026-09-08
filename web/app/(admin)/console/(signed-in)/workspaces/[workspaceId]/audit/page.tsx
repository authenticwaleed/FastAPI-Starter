import type { Metadata } from "next";

import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { readWorkspaceAudit } from "@/lib/console";
import { when } from "@/lib/console-labels";
import { describeEvent, describeTenantActor } from "@/lib/labels";
import type { AuditEntry, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Their own log" };

/**
 * The business's own record of what its people did to it.
 *
 * Their log, and reading it is recorded in ours. That pairing is the
 * arrangement this whole surface rests on: a customer can see what their
 * colleagues did, and the platform can see who went looking through it.
 *
 * No plan is required here, unlike the customer's own route. An audit log
 * is a paid feature for a business; whether support can answer a ticket
 * about one is not a decision that business's plan gets to make. So there
 * is no upgrade prompt on this screen and there should not be one.
 *
 * The wording comes from the same map the customer's own audit page uses,
 * so an entry quoted back to somebody reads as the entry they can see.
 */
export default async function ConsoleWorkspaceAuditPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { workspaceId } = await params;
  const { page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let log: Paged<AuditEntry>;

  try {
    log = await readWorkspaceAudit(workspaceId, { page });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Their own log",
      missing: "No workspace exists with that id.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Their own log"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description="What this business's own people did to it. Reading this page is recorded in the platform log."
      />

      {log.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          Nothing recorded yet.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="tenant-audit-log">
          {log.items.map((entry) => (
            <li
              key={entry.id}
              data-event={entry.event}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
            >
              <span className="min-w-0 flex-1 text-sm">
                {describeEvent(entry.event)}
              </span>

              <span className="text-muted-foreground truncate text-xs">
                {describeTenantActor(entry)}
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

      <ConsolePages
        page={page}
        total={log.total}
        pageSize={log.page_size}
        noun="entries"
        href={(to) => `/console/workspaces/${workspaceId}/audit?page=${to}`}
      />
    </div>
  );
}
