import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CloseWorkspace } from "./close-workspace";
import { SettingsForm } from "./settings-form";
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
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {workspace.name}
          </h1>
          {role ? <Badge variant="secondary">{role}</Badge> : null}
          {workspace.status !== "active" ? (
            <Badge variant="outline" className="uppercase">
              {workspace.status}
            </Badge>
          ) : null}
        </div>
        <p className="text-muted-foreground mt-1 font-mono text-sm">
          {workspace.slug}
        </p>
      </div>

      {workspace.status === "suspended" ? (
        <p className="border-destructive/40 text-muted-foreground rounded-md border px-3 py-2 text-sm">
          This workspace is suspended, so nothing here can be changed. It can
          still be read, and its data has not gone anywhere.
        </p>
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
