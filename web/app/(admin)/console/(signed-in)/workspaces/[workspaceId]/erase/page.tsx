import type { Metadata } from "next";

import { AskForErasure } from "./ask-for-erasure";
import { EraseWorkspace } from "./erase-workspace";
import { WorkspaceStatusBadge } from "@/components/console/badges";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { SectionHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { approvalsFor, pendingApproval, usableApproval } from "@/lib/approvals";
import { readWorkspace } from "@/lib/console";
import { when } from "@/lib/console-labels";
import { ApiError } from "@/lib/errors";
import type { AdminWorkspaceDetail, Approval } from "@/lib/types";

export const metadata: Metadata = { title: "Erase" };

/**
 * Destroying a business's records, in two people's hands.
 *
 * Its own screen, and reached only on purpose. It is the only page in
 * this client that reads the approval list, which is a row in the
 * platform log — so the cost is paid by somebody who came here to erase
 * something, and not by everybody who opens a workspace.
 *
 * The flow is the phase's rule made visible. Somebody asks, with a reason;
 * the request sits here waiting, which is the "visible pending request"
 * this phase is judged on; a colleague who is not them agrees to it in
 * W13's approvals screen; and only then does the erase form appear, with
 * the workspace's address to be typed back.
 *
 * Whether the person reading may spend an approval is not something this
 * screen can know. `usable` says the approval is live and unspent; it does
 * not say who agreed to it, and the API refuses at the moment it is spent
 * if that was you. So the form is offered and the refusal is rendered —
 * a hidden control is never assumed to be an enforced one.
 */
export default async function ConsoleErasePage({
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
      title: "Erase",
      missing: "No workspace exists with that id.",
    });
  }

  let approvals: Approval[] = [];
  let approvalsRefusal: string | null = null;

  try {
    approvals = await approvalsFor("erase_workspace", workspaceId);
  } catch (error) {
    // Administrator rank reads the approval list; erasing is owner-only.
    // Support rank gets this far and can go no further, and saying so
    // beats a screen that looks broken.
    if (error instanceof ApiError && error.status === 403) {
      approvalsRefusal = error.sentence;
    } else {
      throw error;
    }
  }

  const ready = usableApproval(approvals);
  const waiting = pendingApproval(approvals);

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Erase this workspace"
        back={{ href: `/console/workspaces/${workspaceId}/lifecycle`, label: "Lifecycle" }}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>{workspace.name}</span>
            <span className="font-mono text-xs">{workspace.slug}</span>
            <WorkspaceStatusBadge status={workspace.status} />
          </span>
        }
      />

      {/*
        Said plainly and once. Everything on the screen below is about
        slowing this down; the sentence is about what it does.
      */}
      <Alert variant="destructive">
        <AlertDescription>
          This destroys the workspace and everything in it — its contacts,
          conversations, messages, documents and its own audit log — with no
          way back. {workspace.counts.messages.toLocaleString()} messages
          and {workspace.counts.contacts.toLocaleString()} contacts are in
          it now. What survives is the entry in the platform log naming it.
        </AlertDescription>
      </Alert>

      {approvalsRefusal !== null ? (
        <p className="text-muted-foreground text-sm" data-testid="approvals-refused">
          {approvalsRefusal}
        </p>
      ) : ready ? (
        <section className="grid gap-4">
          <SectionHeader
            title="A colleague has agreed"
            description={
              <>
                {ready.approved_by ?? "Somebody"} agreed to this on{" "}
                {ready.approved_at
                  ? when(ready.approved_at)
                  : "an unknown date"}
                , and it lapses at {when(ready.expires_at)}. If that colleague
                was you, the API refuses — it takes two people, not two
                clicks.
              </>
            }
          />

          <EraseWorkspace
            workspaceId={workspaceId}
            slug={workspace.slug}
            approvalId={ready.id}
          />
        </section>
      ) : waiting ? (
        <section className="grid gap-3" data-testid="approval-pending">
          <SectionHeader
            title="Waiting for a colleague"
            actions={<StatusBadge tone="pending">pending</StatusBadge>}
          />

          <p className="text-sm">{waiting.reason}</p>

          <p className="text-muted-foreground text-xs">
            Asked by {waiting.requested_by ?? "somebody"} on{" "}
            {when(waiting.created_at)}, and it lapses at {when(waiting.expires_at)}
            . Any administrator other than whoever asked can agree to it, and
            until one does there is nothing to press here.
          </p>
        </section>
      ) : (
        <section className="grid gap-4">
          <SectionHeader
            title="Ask a colleague first"
            description={
              <>
                An approval is for <em>this</em> workspace: agreeing to erase
                a test account is not agreeing to erase any of them. It is
                short-lived, because two people looking at the same situation
                is the point — one collected this morning and spent tonight is
                one signature, not two.
              </>
            }
          />

          <AskForErasure workspaceId={workspaceId} />
        </section>
      )}
    </div>
  );
}
