import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { InvitationList } from "./invitation-list";
import { InviteForm } from "./invite-form";
import { LeaveWorkspace } from "./leave-workspace";
import { MemberList } from "./member-list";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { listInvitations, listMembers } from "@/lib/team";
import type { Invitation, User, Workspace } from "@/lib/types";

export const metadata: Metadata = { title: "Team" };

const MAY_ADMINISTER = ["owner", "admin"];

/**
 * Who is on the team.
 *
 * Any member may see who they work with, which is why the member list is
 * not behind the admin check. The invitation list is: it is a list of the
 * addresses of people being recruited, and that is not everybody's
 * business. The API draws the line in the same place.
 */
export default async function TeamPage({
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
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const members = await listMembers(workspace.id);
  const mine = members.find((member) => member.user_id === user.id);

  // Being here at all means a membership, so this is defensive rather than
  // expected -- but a page that rendered "your role: undefined" would be
  // worse than one that sends somebody somewhere real.
  if (!mine) redirect("/workspaces");

  const administers = MAY_ADMINISTER.includes(mine.role);
  const frozen = workspace.status !== "active";

  let invitations: Invitation[] = [];

  if (administers) invitations = await listInvitations(workspace.id);

  return (
    <div className="grid gap-8">
      <div>
        <Link
          href={`/workspaces/${workspace.id}/settings`}
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          ← {workspace.name}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Team</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {members.length} {members.length === 1 ? "person" : "people"} in{" "}
          {workspace.name}.
        </p>
      </div>

      {frozen ? (
        <p className="border-destructive/40 text-muted-foreground rounded-md border px-3 py-2 text-sm">
          This workspace is suspended, so the team cannot be changed. It can
          still be read.
        </p>
      ) : null}

      <MemberList
        workspaceId={workspace.id}
        members={members}
        me={mine}
        canManage={administers && !frozen}
      />

      {administers ? (
        <>
          <InviteForm
            workspaceId={workspace.id}
            myRole={mine.role}
            disabled={frozen}
          />
          <InvitationList workspaceId={workspace.id} invitations={invitations} />
        </>
      ) : null}

      <LeaveWorkspace workspace={workspace} me={mine} />
    </div>
  );
}
