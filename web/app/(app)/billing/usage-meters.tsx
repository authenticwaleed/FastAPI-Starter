import { SectionHeader } from "@/components/page-header";
import { METRIC_LABEL, ceilingLabel, fractionUsed } from "@/lib/plans";
import type { UsageSummary } from "@/lib/types";

function when(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

/**
 * What has been used, against what the plan allows.
 *
 * The period comes from the API rather than being assumed here. A
 * subscribed workspace is metered over the dates the provider is billing
 * it for, so a heading saying "this month" would be wrong for most of the
 * month -- which is exactly why the API returns the dates.
 *
 * The number that fills a meter is the number that refuses an action: both
 * come from the same measurement, so a business at its ceiling sees a full
 * bar and gets the refusal, rather than seeing 80% and being told no.
 */
export function UsageMeters({ usage }: { usage: UsageSummary }) {
  return (
    <section className="grid gap-3">
      <SectionHeader
        title="Usage"
        description={`${when(usage.period_start)} to ${when(usage.period_end)}`}
      />

      <ul className="grid gap-3" data-testid="usage-meters">
        {usage.metrics.map((metric) => {
          const filled = fractionUsed(metric);

          return (
            <li key={metric.metric} data-metric={metric.metric} className="grid gap-1">
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span>{METRIC_LABEL[metric.metric] ?? metric.metric}</span>
                <span className="text-muted-foreground tabular-nums">
                  {metric.quantity.toLocaleString()} of{" "}
                  {/*
                    "Unlimited" rather than a blank. Null means nothing
                    refuses this, which is an answer -- carry on -- and not
                    a value the page failed to load.
                  */}
                  {ceilingLabel(metric.limit)}
                </span>
              </div>

              {filled === null ? null : (
                <progress
                  value={filled}
                  max={100}
                  aria-label={`${METRIC_LABEL[metric.metric] ?? metric.metric}: ${filled}% of the plan's allowance`}
                  className="meter"
                />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
