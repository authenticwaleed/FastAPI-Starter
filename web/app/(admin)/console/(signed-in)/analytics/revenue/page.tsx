import type { Metadata } from "next";

import { MagnitudeBars } from "@/components/charts/magnitude-bars";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { readRevenue } from "@/lib/platform";
import type { AdminRevenue, SubscriptionStatus } from "@/lib/types";

export const metadata: Metadata = { title: "Revenue" };

const STATUSES: SubscriptionStatus[] = [
  "active",
  "trialing",
  "past_due",
  "unpaid",
  "canceled",
  "incomplete",
];

/**
 * What is being paid for, as counts rather than as an amount.
 *
 * No money on this page, and that is the honest shape rather than a gap:
 * what a plan costs lives in the API's own plan catalogue, multiplying
 * belongs where the prices are, and a figure computed here would need
 * editing every time one changed and be quietly wrong in between. §7's
 * third refusal — the client does not compute what the API can answer.
 *
 * `past_due` is the number to watch, and it links to the list of exactly
 * those businesses: each one still has its plan while the provider
 * retries, and each is either about to pay or about to churn.
 */
export default async function ConsoleRevenuePage() {
  let revenue: AdminRevenue;

  try {
    revenue = await readRevenue();
  } catch (error) {
    return consoleRefusal(error, { title: "Revenue", missing: "Nothing to report." });
  }

  const retrying = revenue.subscriptions_by_status.past_due ?? 0;

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Revenue"
        back={{ href: "/console/analytics", label: "Analytics" }}
        description="Counts, not amounts. What a plan costs lives with the plans, and a total computed here would be wrong the first time one changed."
      />

      {retrying > 0 ? (
        <p className="rounded-md border px-4 py-3 text-sm" data-testid="past-due-note">
          {retrying} subscription{retrying === 1 ? " is" : "s are"} being
          retried by the provider.{" "}
          <ConsoleLink
            href="/console/billing?status=past_due"
            className="underline underline-offset-4"
          >
            Look at them
          </ConsoleLink>{" "}
          — each is either about to pay or about to churn.
        </p>
      ) : null}

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">Subscriptions by status</h2>
        <MagnitudeBars
          rows={STATUSES.map((status) => ({
            label: status,
            value: revenue.subscriptions_by_status[status] ?? 0,
          }))}
          empty="Nobody has subscribed."
        />
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">Paying, by plan</h2>
          <p className="text-muted-foreground text-xs">
            A business comped onto a plan is not counted here. It is not
            revenue.
          </p>
        </div>
        <MagnitudeBars
          rows={(["starter", "growth", "business"] as const).map((plan) => ({
            label: plan,
            value: revenue.paying_by_plan[plan] ?? 0,
          }))}
          empty="Nobody is paying for anything."
        />
      </section>
    </div>
  );
}
