import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CloseWorkspace } from "./close-workspace";
import { SettingsForm } from "./settings-form";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { User, Workspace } from "@/lib/types";
import { MAY_ADMINISTER, MAY_CLOSE, permits, roleIn } from "@/lib/workspace";

export const metadata: Metadata = { title: "Workspace settings" };

/**
 * One workspace, and what this person may do to it.
 *
 * The role comes from the member list, which is the only place the API says
 * so -- no workspace response carries the caller's own role. That is the one
 * endpoint W2 borrows from W4, and the borrowing is deliberate: the
 * alternatives were showing every member a form that fails for most of them,
 * or guessing.
 */
export default async function WorkspaceSettingsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let workspace: Workspace;
  let user: User;

  try {
    [workspace, user] = await Promise.all([
      api<Workspace>(`/workspaces/${workspaceId}`),
      api<User>("/auth/me"),
    ]);
  } catch (error) {
    // A workspace that does not exist and one this person is not in are the
    // same answer on purpose, so this renders the same page for both and
    // does not try to be more helpful than the API was.
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const role = await roleIn(workspace.id, user);

  return (
    <div className="grid gap-8">
      <PageHeader
        title={workspace.name}
        meta={
          <>
            {role ? <Badge variant="secondary">{role}</Badge> : null}
            {workspace.status !== "active" ? (
              <StatusBadge
                tone={workspace.status === "suspended" ? "critical" : "quiet"}
                status={workspace.status}
              >
                {workspace.status}
              </StatusBadge>
            ) : null}
          </>
        }
        description={
          <span className="font-mono">{workspace.slug}</span>
        }
        actions={
          <Link
            href={`/workspaces/${workspace.id}/team`}
            className="hover:text-foreground text-sm underline underline-offset-4"
          >
            Team and invitations
          </Link>
        }
      />

      {workspace.status === "suspended" ? (
        <Alert variant="warning" role="status">
          <AlertDescription>
            This workspace is suspended, so nothing here can be changed. It
            can still be read, and its data has not gone anywhere.
          </AlertDescription>
        </Alert>
      ) : null}

      <SettingsForm
        workspace={workspace}
        // Disabled rather than absent, so somebody can see what the settings
        // are and who to ask. Enforcement is the API's; this is the courtesy.
        canEdit={permits(role, MAY_ADMINISTER) && workspace.status === "active"}
      />

      {permits(role, MAY_CLOSE) ? (
        <CloseWorkspace workspace={workspace} />
      ) : null}
    </div>
  );
}
