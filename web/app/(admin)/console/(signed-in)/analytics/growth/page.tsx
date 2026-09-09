import type { Metadata } from "next";

import { DaySeries } from "@/components/charts/day-series";
import { StatRow, StatTile } from "@/components/charts/stat-tile";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { DaysPicker, windowOf } from "../days-picker";
import { readGrowth } from "@/lib/platform";
import type { AdminGrowth } from "@/lib/types";

export const metadata: Metadata = { title: "Growth" };

/**
 * Signups and closures over time, and how many businesses did anything.
 *
 * The third number is the one worth having. Workspaces that exist is a
 * count anybody can get; workspaces that sent a message is what says
 * whether the product is used -- and a platform with four hundred of the
 * first and nine of the second knows something the headline hides.
 *
 * Days are UTC, because a platform-wide chart cannot be in every
 * customer's local day at once and this is the day their timestamps are
 * stored in. Said on the page rather than left for somebody to wonder
 * about when a number disagrees with a customer's own analytics.
 */
export default async function ConsoleGrowthPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const days = windowOf((await searchParams).days);

  let growth: AdminGrowth;

  try {
    growth = await readGrowth({ days });
  } catch (error) {
    return consoleRefusal(error, { title: "Growth", missing: "Nothing to report." });
  }

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Growth"
        back={{ href: "/console/analytics", label: "Analytics" }}
        description="Counted in UTC days, which is how the timestamps are stored — not in any one customer's local day."
      />

      <DaysPicker path="/console/analytics/growth" days={days} />

      <StatRow>
        <StatTile
          label="Signups"
          value={growth.signups.reduce((all, point) => all + point.count, 0)}
          hint={`Over ${growth.days} days`}
        />
        <StatTile
          label="Closures"
          value={growth.closures.reduce((all, point) => all + point.count, 0)}
        />
        <StatTile
          label="Businesses that did anything"
          value={growth.active_workspaces}
          hint="Counted from messages sent"
        />
      </StatRow>

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">Signups by day</h2>
        <DaySeries points={growth.signups} label="signups" />
      </section>

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">Closures by day</h2>
        <DaySeries points={growth.closures} label="closures" />
      </section>
    </div>
  );
}
