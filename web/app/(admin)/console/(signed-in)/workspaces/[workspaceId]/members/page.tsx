import type { Metadata } from "next";

import { MembershipStatusBadge } from "@/components/console/badges";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { readWorkspaceMembers } from "@/lib/console";
import { when } from "@/lib/console-labels";
import type { AdminMember } from "@/lib/types";

export const metadata: Metadata = { title: "Members" };

/**
 * Who is on a customer's team.
 *
 * The same fields the business can see for itself, deliberately: what
 * support quotes back to somebody should be what that somebody can check,
 * and a second shape would eventually be a second answer.
 *
 * The workspace's name is not fetched to head this page. That would be a
 * second read and a second row in the platform log for a screen nobody
 * asked twice for -- the way back to the workspace is the link above.
 */
export default async function ConsoleWorkspaceMembersPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let members: AdminMember[];

  try {
    members = await readWorkspaceMembers(workspaceId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Members",
      missing: "No workspace exists with that id.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Members"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description="Everybody the business has added, including the ones who have left."
      />

      {members.length === 0 ? (
        <EmptyState
          // A real state rather than an error. A workspace whose owner
          // closed their account has nobody in it, and that is exactly the
          // sort of thing a ticket is about.
          title="Nobody is in this workspace"
          data-testid="no-members"
        />
      ) : (
        <ul className="grid gap-2" data-testid="member-list">
          {members.map((member) => (
            <li
              key={member.user_id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 row"
            >
              <ConsoleLink
                href={`/console/users/${member.user_id}`}
                className="text-sm font-medium underline-offset-4 hover:underline"
              >
                {member.name}
              </ConsoleLink>

              <span className="text-muted-foreground truncate text-xs">
                {member.email}
              </span>

              <span className="text-muted-foreground ml-auto text-xs">
                Joined {when(member.joined_at)}
              </span>

              <Badge variant="outline">{member.role}</Badge>
              <MembershipStatusBadge status={member.status} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
