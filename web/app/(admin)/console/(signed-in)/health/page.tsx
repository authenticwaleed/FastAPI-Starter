import type { Metadata } from "next";

import { StatRow, StatTile } from "@/components/charts/stat-tile";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { SectionHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { duration } from "@/lib/analytics";
import { readHealth } from "@/lib/platform";
import type { AdminHealth } from "@/lib/types";

export const metadata: Metadata = { title: "Health" };

/**
 * Whether anything is wrong right now.
 *
 * A page a person reads, and deliberately not a probe an orchestrator
 * polls -- the public `/health` is that, and it is cheap and needs no
 * rank. This one costs a row in the platform log every time it is
 * opened, so there is no refresh timer on it and there must not be one: a
 * page that refreshed itself every thirty seconds would fill that log
 * with nobody's decisions and drown the rows that are somebody's.
 *
 * The two queue numbers only mean anything together. Depth alone cannot
 * tell a busy afternoon from a dead worker -- two hundred draining in a
 * minute is fine, three where the oldest has waited an hour is not, and
 * the count looks the same in both.
 */
export default async function ConsoleHealthPage() {
  let health: AdminHealth;

  try {
    health = await readHealth();
  } catch (error) {
    return consoleRefusal(error, { title: "Health", missing: "Nothing to report." });
  }

  const waiting = health.queue.oldest_pending_seconds;

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Health"
        description="What this process can tell from where it sits, at the moment you asked. Nothing here refreshes itself."
      />

      <section className="grid gap-3">
        <SectionHeader title="The queue" />
        <StatRow>
          <StatTile label="Waiting" value={health.queue.depth} />
          <StatTile
            label="Oldest wait"
            // Null is "nothing is due", which is not zero -- zero would
            // read as "something is waiting and it just arrived".
            value={duration(waiting)}
            hint={waiting === null ? "Nothing is due" : "Read it beside the depth"}
          />
          <StatTile label="Running" value={health.queue.running} />
          <StatTile label="Failed" value={health.queue.failed} />
        </StatRow>

        {health.queue.failed > 0 ? (
          <p className="text-sm">
            <ConsoleLink
              href="/console/jobs?status=failed"
              className="underline underline-offset-4"
            >
              Look at what failed
            </ConsoleLink>
          </p>
        ) : null}
      </section>

      <section className="grid gap-3">
        <SectionHeader title="This deployment" />

        <ul className="grid gap-2" data-testid="health-checks">
          <li className="flex items-center gap-3 row text-sm">
            <span className="flex-1">Database</span>
            <Badge variant={health.database ? "secondary" : "destructive"}>
              {health.database ? "answering" : "not answering"}
            </Badge>
          </li>

          {Object.entries(health.integrations).map(([name, configured]) => (
            <li
              key={name}
              className="flex items-center gap-3 row text-sm"
              data-integration={name}
            >
              <span className="flex-1 font-mono text-xs">{name}</span>
              <Badge variant={configured ? "secondary" : "outline"}>
                {configured ? "configured" : "not configured"}
              </Badge>
            </li>
          ))}
        </ul>

        <p className="text-muted-foreground text-xs">
          {/*
            Said plainly, because the word "configured" is doing careful
            work: dialling each provider on every load would be slow,
            rate limited by somebody else's API, and would report an
            outage every time one had a slow minute.
          */}
          Configured means a key is present, not that the provider answered.
          The failure this catches is a deployment missing one, which
          otherwise surfaces at the first customer who needs it.
        </p>
      </section>
    </div>
  );
}
