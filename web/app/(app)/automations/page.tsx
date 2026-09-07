import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AutomationList } from "./automation-list";
import { CreateAutomation } from "./create-automation";
import { api } from "@/lib/api";
import { listAutomations } from "@/lib/integrations";
import { admits } from "@/lib/plans";
import { readSubscription } from "@/lib/billing";
import type { Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Automations" };

const MAY_ADMINISTER = ["owner", "admin"];

/**
 * The three things that can happen without anybody pressing anything.
 *
 * Only switching one *on* is plan-gated. Everything about the ones a
 * workspace already has — reading them, changing the wording, turning them
 * off, deleting them — keeps working on a plan that has lapsed, which is
 * the difference between losing a feature and being locked in by one.
 */
export default async function AutomationsPage() {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const [automations, current, user, members] = await Promise.all([
    listAutomations(workspace.id),
    readSubscription(workspace.id),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  const included = admits(current, "automations");

  return (
    <div className="grid gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Automations</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Things that happen on their own, so nobody has to remember to do
          them.
        </p>
      </div>

      <AutomationList
        workspaceId={workspace.id}
        automations={automations}
        canManage={administers}
      />

      {administers ? (
        <CreateAutomation
          workspaceId={workspace.id}
          existing={automations.map((automation) => automation.kind)}
          // Passed rather than inferred from a refusal: the API answers a
          // 402 either way, and telling somebody before they press is
          // better than after.
          included={included}
        />
      ) : null}
    </div>
  );
}
