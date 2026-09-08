import type { Metadata } from "next";

import { UsageMeters } from "@/app/(app)/billing/usage-meters";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { readWorkspaceUsage } from "@/lib/console";
import type { UsageSummary } from "@/lib/types";

export const metadata: Metadata = { title: "Usage" };

/**
 * What a business has used, over the period it is billed for.
 *
 * The customer's own meters, rendered by the customer's own component.
 * That sharing is the point rather than a shortcut: the figure comes from
 * the same endpoint and the same meter, and a support engineer and a
 * customer looking at "how many assistant replies this month" must not be
 * able to see two different numbers.
 *
 * The two surfaces share components and nothing else -- no layout, no
 * navigation, no session. This is exactly the sort of thing principle 7
 * leaves room for.
 */
export default async function ConsoleWorkspaceUsagePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let usage: UsageSummary;

  try {
    usage = await readWorkspaceUsage(workspaceId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Usage",
      missing: "No workspace exists with that id.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Usage"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description="The same numbers the business sees, from the same meter. Unlimited is a limit of none, not a limit of zero."
      />

      <UsageMeters usage={usage} />
    </div>
  );
}
