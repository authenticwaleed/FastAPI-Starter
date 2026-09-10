import { EmptyState } from "@/components/empty-state";
import { SectionHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { RUN_LABEL } from "@/lib/automations";
import type { AutomationRun } from "@/lib/types";

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * What this automation has actually done.
 *
 * `skipped` is rendered quietly rather than as a problem, and it will be
 * most of the list: an automation is considered on every matching event
 * and most events are not the one it is for. A history that coloured those
 * red would be a history nobody reads, which defeats the point of keeping
 * one.
 */
export function RunHistory({ runs, total }: { runs: AutomationRun[]; total: number }) {
  if (runs.length === 0) {
    return (
      <section className="grid gap-2">
        <SectionHeader title="History" />
        {/*
          An empty state rather than an error. A brand-new automation has
          run nothing, and so has one whose trigger has not happened yet --
          both are ordinary.
        */}
        <EmptyState title="It has not run yet" data-testid="run-history">
          Nothing is wrong — it is waiting for something to happen.
        </EmptyState>
      </section>
    );
  }

  return (
    <section className="grid gap-2">
      <SectionHeader title="History" />
      <p className="text-muted-foreground text-xs">
        {total} attempt{total === 1 ? "" : "s"}. Most will say &ldquo;not for
        this one&rdquo; — it is considered on every matching event.
      </p>

      <ul className="grid gap-2" data-testid="run-history">
        {runs.map((run) => {
          const outcome = RUN_LABEL[run.status];

          return (
            <li
              key={run.id}
              data-status={run.status}
              className="row flex flex-wrap items-center gap-x-3 gap-y-1"
            >
              <Badge
                variant={
                  outcome.tone === "bad"
                    ? "destructive"
                    : outcome.tone === "ok"
                      ? "default"
                      : "outline"
                }
              >
                {outcome.label}
              </Badge>

              <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs">
                {/*
                  What the run was about, when it was about something. Null
                  for one that may happen again.
                */}
                {run.dedupe_key ?? "—"}
              </span>

              {run.attempts > 1 ? (
                <span className="text-muted-foreground text-xs tabular-nums">
                  {run.attempts} attempts
                </span>
              ) : null}

              <span className="text-muted-foreground text-xs">
                {when(run.started_at)}
              </span>

              {run.error ? (
                <p className="text-destructive w-full text-xs">{run.error}</p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
