import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { listPlatformAudit } from "@/lib/console";
import { describeAction, when } from "@/lib/console-labels";
import { describeActor } from "@/lib/labels";
import type { AdminAuditEntry, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Platform log" };

/** The questions this log is actually asked. Narrow, because it only grows. */
const ACTIONS = [
  "console.opened",
  "workspaces.searched",
  "workspace.read",
  "workspace.members_read",
  "workspace.subscription_read",
  "workspace.usage_read",
  "workspace.integrations_read",
  "workspace.audit_read",
  "users.searched",
  "user.read",
  "audit.read",
  "workspace.suspended",
  "workspace.unsuspended",
  "workspace.cancelled",
  "workspace.restored",
  "workspace.erased",
  "workspace.erase_refused",
  "user.deactivated",
  "user.activated",
  "user.sessions_revoked",
  "user.email_verified",
  "staff.granted",
  "staff.role_changed",
  "staff.revoked",
  "approval.requested",
  "approval.granted",
  "approval.spent",
];

/**
 * What staff have done, newest first, reads included.
 *
 * The half of this surface that makes the other half acceptable. A support
 * engineer can read a business's account; this is where somebody can ask
 * afterwards who did, and when.
 *
 * Reading it writes its own row, which is not a joke about recursion: the
 * rule is about the surface rather than about each route, and an exception
 * for the log itself would be the first crack in it. The API writes the
 * entry after the page has been queried, so nobody is handed their own
 * arrival at the top of what they asked for.
 *
 * Administrators and above at the API. Support meets a sentence here
 * rather than a hidden link, because knowing the rank would mean a call on
 * every screen in the console — see the note in this section's layout.
 */
export default async function ConsoleAuditPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; action?: string; workspace_id?: string }>;
}) {
  const {
    page: rawPage,
    action,
    workspace_id: workspaceId,
  } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let log: Paged<AdminAuditEntry>;

  try {
    log = await listPlatformAudit({ page, action, workspaceId });
  } catch (error) {
    // `insufficient_staff_role` lands here for support rank, and it is
    // terminal: there is no form to change and nothing to retry, only a
    // colleague to ask.
    return consoleRefusal(error, {
      title: "Platform log",
      missing: "No such entry.",
    });
  }

  const keep = new URLSearchParams();

  if (action) keep.set("action", action);
  if (workspaceId) keep.set("workspace_id", workspaceId);

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Platform log"
        description={
          <span>
            What the people running Baton did, to a business or to each other.{" "}
            <ConsoleLink
              href="/console/alerts"
              className="underline underline-offset-4"
            >
              Who has been reading a lot of accounts
            </ConsoleLink>{" "}
            is built from these same rows.
          </span>
        }
      />

      <form
        action="/console/audit"
        className="flex flex-wrap items-end gap-3 border-y py-3"
      >
        {/* Carried rather than shown as a field: it arrives as a link from
            a workspace, and a UUID is not something anybody types. */}
        {workspaceId ? (
          <input type="hidden" name="workspace_id" value={workspaceId} />
        ) : null}

        <div className="grid gap-1.5">
          <Label htmlFor="action" className="text-xs">
            Action
          </Label>
          <NativeSelect
            id="action"
            name="action"
            defaultValue={action ?? ""}
          >
            <option value="">Anything</option>
            {ACTIONS.map((value) => (
              <option key={value} value={value}>
                {describeAction(value)}
              </option>
            ))}
          </NativeSelect>
        </div>

        <Button type="submit" variant="outline" size="sm">
          Apply
        </Button>

        {action || workspaceId ? (
          <ConsoleLink
            href="/console/audit"
            className="text-muted-foreground text-sm underline-offset-4 hover:underline"
          >
            Clear
          </ConsoleLink>
        ) : null}

        {workspaceId ? (
          <span className="text-muted-foreground text-xs" data-testid="scoped-to">
            One workspace only.
          </span>
        ) : null}
      </form>

      {log.items.length === 0 ? (
        <EmptyState title="Nothing recorded yet" />
      ) : (
        <ul className="grid gap-2" data-testid="platform-log">
          {log.items.map((entry) => (
            <li
              key={entry.id}
              data-action={entry.action}
              className="grid gap-1 row"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="min-w-0 flex-1 text-sm">
                  {describeAction(entry.action)}
                </span>

                <span className="text-muted-foreground truncate text-xs">
                  {/*
                    Wholly null where nobody did it: the first owner, granted
                    from a command line before anybody existed who could
                    grant it. An address with no id is a colleague whose
                    account has since gone, and the address outliving it is
                    the reason this table is not the tenants' one.
                  */}
                  {describeActor(entry.actor)}
                </span>

                <span className="text-muted-foreground text-xs">
                  {when(entry.created_at)}
                </span>

                <Badge variant="outline" className="font-mono text-2xs">
                  {entry.action}
                </Badge>
              </div>

              {entry.subject ? (
                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                  <span>About</span>
                  {/*
                    A null id with a slug is a workspace that has been
                    erased. There is nothing left to link to, and the name
                    copied beside it is the whole point of the row.
                  */}
                  {entry.subject.workspace_id ? (
                    <ConsoleLink
                      href={`/console/workspaces/${entry.subject.workspace_id}`}
                      className="font-mono underline-offset-4 hover:underline"
                    >
                      {entry.subject.workspace_slug ?? entry.subject.workspace_id}
                    </ConsoleLink>
                  ) : (
                    <span className="font-mono">
                      {entry.subject.workspace_slug} (erased)
                    </span>
                  )}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={log.total}
        pageSize={log.page_size}
        noun="entries"
        href={(to) => `/console/audit?${new URLSearchParams(keep)}&page=${to}`}
      />
    </div>
  );
}
