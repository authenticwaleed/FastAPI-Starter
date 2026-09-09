import type { Metadata } from "next";

import { ApproveRequest } from "./approve-request";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { listApprovals } from "@/lib/approvals";
import { whoami } from "@/lib/console";
import { when } from "@/lib/console-labels";
import type { Approval, Page as Paged, StaffMember } from "@/lib/types";

export const metadata: Metadata = { title: "Approvals" };

/** What each request is actually about, in the language of the act. */
const ABOUT: Record<string, string> = {
  erase_workspace: "Erase a business and everything in it",
  grant_staff_owner: "Make somebody an owner of this platform",
};

function state(approval: Approval): { label: string; variant: "default" | "outline" | "secondary" } {
  if (approval.consumed_at) return { label: "spent", variant: "outline" };
  if (approval.approved_at) return { label: "agreed", variant: "secondary" };
  if (Date.parse(approval.expires_at) <= Date.now()) {
    return { label: "lapsed", variant: "outline" };
  }

  return { label: "waiting", variant: "default" };
}

/**
 * The other half of the loop W12 opens.
 *
 * Somebody asked, on a workspace's erasure screen or while promoting a
 * colleague to owner; this is where a *different* person agrees. The API
 * refuses your own, which is the control rather than a formality: an
 * approval you raised and agreed to yourself is a form with extra steps.
 *
 * Agreeing is not performing. Whoever spends it must also be somebody
 * other than whoever agreed, so the ordinary shape is three-cornered — a
 * colleague asks, you agree, and they act.
 *
 * Spent and lapsed requests are kept, which is most of the value: a list
 * of only what is pending is almost always empty, and the question being
 * asked afterwards is what has been agreed to.
 */
export default async function ConsoleApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const { page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let approvals: Paged<Approval>;
  let me: StaffMember;

  try {
    [approvals, me] = await Promise.all([listApprovals({ page }), whoami()]);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Approvals",
      missing: "No such request.",
    });
  }

  const waiting = approvals.items.filter(
    (approval) => state(approval).label === "waiting",
  );

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Approvals"
        description="Two acts on this platform need a second person: erasing a business, and making somebody an owner. This is where the second person answers."
      />

      {waiting.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm">
          Nothing is waiting on anybody.
        </p>
      ) : (
        <p className="text-sm" data-testid="waiting-count">
          {waiting.length} request{waiting.length === 1 ? "" : "s"} waiting.
        </p>
      )}

      {approvals.items.length > 0 ? (
        <ul className="grid gap-2" data-testid="approval-list">
          {approvals.items.map((approval) => {
            const shown = state(approval);
            const mine = approval.requested_by === me.email;

            return (
              <li
                key={approval.id}
                data-action={approval.action}
                data-state={shown.label}
                className="grid gap-2 rounded-md border px-3 py-2.5"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm font-medium">
                    {ABOUT[approval.action] ?? approval.action}
                  </span>
                  <span className="text-muted-foreground ml-auto text-xs">
                    Lapses {when(approval.expires_at)}
                  </span>
                  <Badge variant={shown.variant}>{shown.label}</Badge>
                </div>

                <p className="text-sm">{approval.reason}</p>

                <p className="text-muted-foreground text-xs">
                  Asked by {approval.requested_by ?? "somebody"} on{" "}
                  {when(approval.created_at)}
                  {approval.approved_by
                    ? `, agreed to by ${approval.approved_by}`
                    : null}
                  . About{" "}
                  {approval.action === "erase_workspace" ? (
                    <ConsoleLink
                      href={`/console/workspaces/${approval.subject}`}
                      className="font-mono underline underline-offset-4"
                    >
                      {approval.subject}
                    </ConsoleLink>
                  ) : (
                    <ConsoleLink
                      href={`/console/users/${approval.subject}`}
                      className="font-mono underline underline-offset-4"
                    >
                      account {approval.subject}
                    </ConsoleLink>
                  )}
                  .
                </p>

                {shown.label === "waiting" ? (
                  mine ? (
                    <p
                      className="text-muted-foreground text-xs"
                      data-testid="your-own-request"
                    >
                      You asked for this. Agreeing to your own request is a form
                      with extra steps, so a colleague has to.
                    </p>
                  ) : (
                    <ApproveRequest approvalId={approval.id} />
                  )
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      <ConsolePages
        page={page}
        total={approvals.total}
        pageSize={50}
        noun="requests"
        href={(to) => `/console/approvals?page=${to}`}
      />
    </div>
  );
}
