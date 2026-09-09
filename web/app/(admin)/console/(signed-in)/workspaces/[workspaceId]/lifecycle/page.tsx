import type { Metadata } from "next";

import { Closure } from "./closure";
import { EraseAfter } from "./erase-after";
import { Suspension } from "./suspension";
import { WorkspaceStatusBadge } from "@/components/console/badges";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { readWorkspace } from "@/lib/console";
import type { AdminWorkspaceDetail } from "@/lib/types";

export const metadata: Metadata = { title: "Lifecycle" };

/**
 * What the platform may do to a business, as opposed to look at.
 *
 * Its own screen rather than controls on the detail page, and the reason
 * is not tidiness: reading a customer's account to answer a ticket and
 * freezing it are different acts with different consequences, and putting
 * them on one page means the second is always one mis-click from the
 * first. The detail page stays read-only; this is a deliberate step away
 * from it.
 *
 * Only what the workspace's state permits is offered. The API refuses the
 * rest with `409 workspace_lifecycle`, and the phase's rule is to refetch
 * and re-render the available actions rather than leave a dead control
 * on screen -- which is what every act here does on its way out.
 *
 * Erasure is not here. It is the one act that cannot be undone, it needs
 * a colleague, and it has a screen of its own.
 */
export default async function ConsoleLifecyclePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let workspace: AdminWorkspaceDetail;

  try {
    workspace = await readWorkspace(workspaceId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Lifecycle",
      missing: "No workspace exists with that id.",
    });
  }

  const suspended = workspace.status === "suspended";
  const closed = workspace.status === "cancelled";

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Lifecycle"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>{workspace.name}</span>
            <span className="font-mono text-xs">{workspace.slug}</span>
            <WorkspaceStatusBadge status={workspace.status} />
          </span>
        }
      />

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">
            {suspended ? "Lift the suspension" : "Suspend"}
          </h2>
          <p className="text-muted-foreground text-xs">
            {/*
              An operational decision, and the copy must not imply the
              customer failed to pay -- most suspensions are not about
              money, and telling a business it has when it has not is the
              worst thing this screen could say.
            */}
            A suspended account is reachable, readable and unchangeable. Its
            inbox keeps receiving; nothing of theirs is taken away.
          </p>
        </div>

        <Suspension workspaceId={workspaceId} status={workspace.status} />
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">
            {closed ? "Restore this account" : "Close this account"}
          </h2>
          <p className="text-muted-foreground text-xs">
            Closing takes the same path the customer&rsquo;s own close does:
            the same status, the same grace period, the same erasure job.
            Nothing is destroyed today.
          </p>
        </div>

        <Closure
          workspaceId={workspaceId}
          slug={workspace.slug}
          status={workspace.status}
          eraseAfter={workspace.erase_after}
        />
      </section>

      {closed ? (
        <section className="grid gap-3">
          <div>
            <h2 className="text-sm font-medium">When its records go</h2>
            <p className="text-muted-foreground text-xs">
              Both directions. Sooner is a customer asking to be forgotten;
              later is a dispute or a legal hold. Without this, one of those
              happens in a database console.
            </p>
          </div>
          <EraseAfter
            workspaceId={workspaceId}
            eraseAfter={workspace.erase_after}
          />
        </section>
      ) : null}

      <section className="border-destructive/40 grid gap-3 rounded-md border px-4 py-3">
        <div>
          <h2 className="text-sm font-medium">Erase everything, now</h2>
          <p className="text-muted-foreground text-xs">
            The one act on this surface with nothing behind it afterwards.
            An owner, this workspace&rsquo;s address typed back, and a
            colleague who agreed — on its own screen.
          </p>
        </div>
        <ConsoleLink
          href={`/console/workspaces/${workspaceId}/erase`}
          className="w-fit text-sm underline underline-offset-4"
        >
          Go to erasure
        </ConsoleLink>
      </section>
    </div>
  );
}
