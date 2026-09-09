import type { Metadata } from "next";

import { MagnitudeBars } from "@/components/charts/magnitude-bars";
import { StatRow, StatTile } from "@/components/charts/stat-tile";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { readPlatformOverview } from "@/lib/platform";
import type { AdminOverview } from "@/lib/types";

export const metadata: Metadata = { title: "Analytics" };

const DASHBOARDS = [
  {
    href: "/console/analytics/growth",
    title: "Growth",
    body: "Signups, closures, and how many businesses actually did anything.",
  },
  {
    href: "/console/analytics/revenue",
    title: "Revenue",
    body: "What the provider says is being paid for, as counts rather than an amount.",
  },
  {
    href: "/console/analytics/ai",
    title: "Assistant spend",
    body: "Tokens across every tenant, and what a reply costs in them.",
  },
];

/**
 * Where the platform stands right now.
 *
 * Four dashboards rather than one page with four sections, and four
 * reads: a single page calling all of them would spend four rows in the
 * platform log on somebody who wanted the headline. The same argument the
 * workspace detail screen makes about its five sub-screens.
 *
 * Nothing here reveals a customer, and none of it can be acted on. It is
 * administrator rank because a revenue chart is not a support tool, which
 * is the one place on this surface where the rank is about seniority
 * rather than safety.
 *
 * A status or plan with nothing in it is absent from the API's maps
 * rather than zero, and a missing key reads as zero -- which is the same
 * thing and one fewer round trip than asking for the vocabulary.
 */
export default async function ConsoleAnalyticsPage() {
  let overview: AdminOverview;

  try {
    overview = await readPlatformOverview();
  } catch (error) {
    return consoleRefusal(error, {
      title: "Analytics",
      missing: "Nothing to report.",
    });
  }

  const statuses = ["active", "suspended", "cancelled"] as const;
  const plans = ["starter", "growth", "business"] as const;

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Analytics"
        description="Aggregates only. No figure on any of these pages is about one business."
      />

      <StatRow>
        <StatTile label="Accounts" value={overview.counts.users} />
        <StatTile label="Workspaces" value={overview.counts.workspaces} />
        <StatTile label="Conversations" value={overview.counts.conversations} />
        <StatTile label="Messages" value={overview.counts.messages} />
      </StatRow>

      <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
        <section className="grid gap-3">
          <div>
            <h2 className="text-sm font-medium">Where workspaces stand</h2>
            <p className="text-muted-foreground text-xs">Right now, not over time.</p>
          </div>
          <MagnitudeBars
            rows={statuses.map((status) => ({
              label: status,
              value: overview.workspaces_by_status[status] ?? 0,
            }))}
            empty="No workspaces yet."
          />
        </section>

        <section className="grid gap-3">
          <div>
            <h2 className="text-sm font-medium">What they are on</h2>
            <p className="text-muted-foreground text-xs">
              {/*
                The provider's word rather than what a workspace is
                entitled to, and the difference matters most here: this is
                a commercial number, and a business comped onto Business
                is not revenue.
              */}
              What is being paid for, not what has been granted.
            </p>
          </div>
          <MagnitudeBars
            rows={plans.map((plan) => ({
              label: plan,
              value: overview.workspaces_by_plan[plan] ?? 0,
            }))}
            empty="Nobody is on a plan."
          />
        </section>
      </div>

      <section className="grid gap-3 sm:grid-cols-3">
        {DASHBOARDS.map((dashboard) => (
          <ConsoleLink
            key={dashboard.href}
            href={dashboard.href}
            className="hover:bg-accent/50 grid content-start gap-1 rounded-md border px-4 py-3"
          >
            <span className="text-sm font-medium">{dashboard.title}</span>
            <span className="text-muted-foreground text-xs">{dashboard.body}</span>
          </ConsoleLink>
        ))}
      </section>
    </div>
  );
}
