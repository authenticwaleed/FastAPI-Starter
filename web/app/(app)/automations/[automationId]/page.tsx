import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { RunHistory } from "./run-history";
import { SettingsForm } from "./settings-form";
import { Badge } from "@/components/ui/badge";
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
      <div>
        <Link
          href="/automations"
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          ← Automations
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {automation.name}
          </h1>
          <Badge variant={automation.status === "enabled" ? "default" : "outline"}>
            {STATUS_LABEL[automation.status]}
          </Badge>
        </div>
        <p className="text-muted-foreground mt-1 text-sm">
          {TRIGGER_LABEL[automation.trigger_type]} ·{" "}
          {specFor(automation.kind).summary}
        </p>
      </div>

      <SettingsForm
        workspaceId={workspace.id}
        automation={automation}
        canManage={administers}
      />

      <RunHistory runs={runs.items} total={runs.total} />
    </div>
  );
}
