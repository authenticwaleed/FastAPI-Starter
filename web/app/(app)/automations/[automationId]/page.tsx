import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { RunHistory } from "./run-history";
import { SettingsForm } from "./settings-form";
import { BackLink, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { STATUS_LABEL, TRIGGER_LABEL, specFor } from "@/lib/automations";
import { ApiError } from "@/lib/errors";
import { listRuns, readAutomation } from "@/lib/integrations";
import type { Automation, Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Automation" };

const MAY_ADMINISTER = ["owner", "admin"];

export default async function AutomationPage({
  params,
}: {
  params: Promise<{ automationId: string }>;
}) {
  const { automationId } = await params;
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  let automation: Automation;

  try {
    automation = await readAutomation(workspace.id, automationId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const [runs, user, members] = await Promise.all([
    listRuns(workspace.id, automationId),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  return (
    <div className="grid gap-8">
      <PageHeader
        back={<BackLink href="/automations" label="Automations" />}
        title={automation.name}
        meta={
          <StatusBadge
            tone={automation.status === "enabled" ? "neutral" : "quiet"}
            status={automation.status}
          >
            {STATUS_LABEL[automation.status]}
          </StatusBadge>
        }
        description={
          <>
            {TRIGGER_LABEL[automation.trigger_type]} ·{" "}
            {specFor(automation.kind).summary}
          </>
        }
      />

      <SettingsForm
        workspaceId={workspace.id}
        automation={automation}
        canManage={administers}
      />

      <RunHistory runs={runs.items} total={runs.total} />
    </div>
  );
}
