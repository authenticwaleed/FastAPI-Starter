import type { Metadata } from "next";

import { WorkspaceFilters } from "./workspace-filters";
import { WorkspaceStatusBadge } from "@/components/console/badges";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { searchWorkspaces } from "@/lib/console";
import { day } from "@/lib/console-labels";
import type { AdminWorkspaceSummary, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Workspaces" };

/**
 * Finding the business a ticket is about.
 *
 * The address is what a ticket actually arrives with, and the API matches
 * it against anyone in the workspace rather than only its owner -- whoever
 * writes in is whoever noticed the problem, and that is as often an agent
 * as the owner.
 *
 * Closed workspaces are in these results, with the date their records are
 * due to be destroyed. That is the opposite of what the customer's own API
 * does, where a closed workspace is simply gone, and it is the difference
 * that answers "it was closed last week -- can we get it back".
 */
export default async function ConsoleWorkspacesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; plan?: string; page?: string }>;
}) {
  const { q, status, plan, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let found: Paged<AdminWorkspaceSummary>;

  try {
    found = await searchWorkspaces({ q, status, plan, page });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Workspaces",
      missing: "No such workspace.",
    });
  }

  const keep = new URLSearchParams();

  if (q) keep.set("q", q);
  if (status) keep.set("status", status);
  if (plan) keep.set("plan", plan);

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Workspaces"
        description="Every business with an account, closed ones included."
      />

      <WorkspaceFilters q={q ?? null} status={status ?? null} plan={plan ?? null} />

      {found.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          {/*
            A 404 on this surface means no such row, and so does an empty
            search: no hedging about membership, because whoever is reading
            is staff and there is nothing to keep from them (§3.2).
          */}
          Nothing matches that.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="workspace-results">
          {found.items.map((workspace) => (
            <li key={workspace.id}>
              <ConsoleLink
                href={`/console/workspaces/${workspace.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
              >
                <span className="text-sm font-medium">{workspace.name}</span>
                <span className="text-muted-foreground font-mono text-xs">
                  {workspace.slug}
                </span>

                <span className="text-muted-foreground truncate text-xs">
                  {/* Null where the owner has closed their own account. A
                      real state, and one somebody would be searching about. */}
                  {workspace.owner_email ?? "No owner account"}
                </span>

                {workspace.erase_after ? (
                  <span
                    className="text-destructive ml-auto text-xs"
                    data-testid="erase-after"
                  >
                    Records go {day(workspace.erase_after)}
                  </span>
                ) : null}

                <span
                  className={`flex items-center gap-2 ${workspace.erase_after ? "" : "ml-auto"}`}
                >
                  <Badge variant="outline">{workspace.plan}</Badge>
                  <WorkspaceStatusBadge status={workspace.status} />
                </span>
              </ConsoleLink>
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={found.total}
        pageSize={found.page_size}
        noun="workspaces"
        href={(to) => `/console/workspaces?${new URLSearchParams(keep)}&page=${to}`}
      />
    </div>
  );
}
