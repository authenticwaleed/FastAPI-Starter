import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { EmptyState } from "@/components/empty-state";
import { SectionHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { readAlerts } from "@/lib/platform";
import type { AdminAlerts } from "@/lib/types";

export const metadata: Metadata = { title: "Alerts" };

const WINDOWS = [1, 6, 24, 168];

function label(hours: number): string {
  if (hours === 1) return "Last hour";
  if (hours === 168) return "Last week";
  if (hours === 24) return "Last day";

  return `Last ${hours} hours`;
}

/**
 * Who has been reading a lot of customers' accounts lately.
 *
 * Built from the platform's own audit log rather than from a second
 * tally, which is the reason auditing reads was worth its cost: the same
 * rows that answer "who looked at this workspace" answer "who has been
 * looking at everybody's".
 *
 * Nothing here refuses anybody anything, and that is the design rather
 * than a limitation. Twenty accounts in an hour is a migration or a
 * person working through a queue about as often as it is anything else,
 * and a control that refused it would be worked around within a week by
 * whoever was on call. The useful output is a name and a number somebody
 * can ask about.
 *
 * Distinct workspaces rather than requests: refreshing one account's page
 * forty times is working, and opening forty accounts is a question.
 */
export default async function ConsoleAlertsPage({
  searchParams,
}: {
  searchParams: Promise<{ hours?: string }>;
}) {
  const { hours: rawHours } = await searchParams;
  const hours = Math.min(168, Math.max(1, Number(rawHours ?? 1) || 1));

  let alerts: AdminAlerts;

  try {
    alerts = await readAlerts({ hours });
  } catch (error) {
    return consoleRefusal(error, { title: "Alerts", missing: "Nothing to report." });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Alerts"
        description="Patterns worth a person looking at. Nothing on this page stops anybody doing anything."
      />

      <nav
        className="flex flex-wrap items-center gap-4 border-y py-3 text-sm"
        aria-label="Window"
      >
        {WINDOWS.map((window) => (
          <ConsoleLink
            key={window}
            href={`/console/alerts?hours=${window}`}
            className={
              hours === window
                ? "font-medium underline underline-offset-4"
                : "text-muted-foreground underline-offset-4 hover:underline"
            }
          >
            {label(window)}
          </ConsoleLink>
        ))}
      </nav>

      {alerts.over_threshold.length > 0 ? (
        <section className="grid gap-3">
          <div>
            <SectionHeader title="Over the threshold" />
            <p className="text-muted-foreground text-xs">
              More than {alerts.threshold} accounts an hour, which is
              configuration rather than a rule. Worth asking about, not worth
              stopping.
            </p>
          </div>

          <ul className="grid gap-2" data-testid="over-threshold">
            {alerts.over_threshold.map((reader) => (
              <li
                key={reader.user_id ?? reader.email ?? "unknown"}
                className="border-warning/40 bg-warning/5 flex flex-wrap items-center gap-3 rounded-md border px-3 py-2.5 text-sm"
              >
                <span className="flex-1">{reader.email ?? "A deleted account"}</span>
                {/*
                  A count over a threshold is something to look into, not
                  something that has gone wrong -- an incident week is a
                  legitimate reason to have read thirty accounts.
                */}
                <Badge variant="warning" className="tabular-nums">
                  {reader.workspaces_read} accounts
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="grid gap-3">
        <SectionHeader
          title="Busiest readers"
          description="Distinct businesses opened in the window, newest activity first."
        />

        {alerts.busiest_readers.length === 0 ? (
          <EmptyState title="Nobody has opened a customer’s account in this window" />
        ) : (
          <ul className="grid gap-2" data-testid="busiest-readers">
            {alerts.busiest_readers.map((reader) => (
              <li
                key={reader.user_id ?? reader.email ?? "unknown"}
                className="flex flex-wrap items-center gap-3 row text-sm"
              >
                <span className="flex-1">{reader.email ?? "A deleted account"}</span>
                <span className="text-muted-foreground tabular-nums text-xs">
                  {reader.workspaces_read} accounts
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-muted-foreground text-xs">
        The other pattern the plan names — support access asked for outside
        working hours — is not a state and so is not here. It is a warning
        line written when the grant is asked for, in the stream operations
        already watches.{" "}
        <ConsoleLink href="/console/audit" className="underline underline-offset-4">
          The platform log
        </ConsoleLink>{" "}
        has the rows themselves.
      </p>
    </div>
  );
}
