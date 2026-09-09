import type { Metadata } from "next";

import { PlanOverrideControls } from "./plan-override";
import { Fact, Facts } from "@/components/console/facts";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { readWorkspaceSubscription } from "@/lib/console";
import { when } from "@/lib/console-labels";
import { isEntitling } from "@/lib/plans";
import type { AdminBilling } from "@/lib/types";

export const metadata: Metadata = { title: "Subscription" };

/**
 * What the provider says, and what the workspace actually gets.
 *
 * Both, side by side, because they answer different questions and the gap
 * between them is where billing support happens (§3.4). A `past_due`
 * subscription still entitles the full plan while the provider retries, so
 * a screen showing only the status would have somebody telling a customer
 * their account is restricted when it is not.
 *
 * Reading only. Refunds and invoice corrections stay in the provider's
 * dashboard, which is better at them and is already the system of record;
 * the provider ids below are how somebody gets there.
 */
export default async function ConsoleWorkspaceSubscriptionPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let billing: AdminBilling;

  try {
    billing = await readWorkspaceSubscription(workspaceId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Subscription",
      missing: "No workspace exists with that id.",
    });
  }

  const subscription = billing.subscription;

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Subscription"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
      />

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">What applies</h2>
          <p className="text-muted-foreground text-xs">
            After overrides and status. This is what the workspace may
            actually do right now, and it is the answer to give a customer.
          </p>
        </div>
        <p className="text-2xl font-semibold tracking-tight" data-testid="entitled-plan">
          {billing.plan}
        </p>
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">What is being paid for</h2>
          <p className="text-muted-foreground text-xs">
            The provider&rsquo;s side of it. Display only — never the plan to
            answer &ldquo;can they use this&rdquo; with.
          </p>
        </div>

        {subscription === null ? (
          <p
            className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm"
            data-testid="never-subscribed"
          >
            {/*
              Null means never subscribed, which is not the same as a
              payment that failed. The plan above still applies.
            */}
            This workspace has never had a subscription.
          </p>
        ) : (
          <Facts>
            <Fact label="Status">
              <span className="flex flex-wrap items-center gap-2">
                <Badge
                  variant={isEntitling(subscription.status) ? "secondary" : "outline"}
                  data-testid="subscription-status"
                >
                  {subscription.status}
                </Badge>
                {/*
                  Spelled out rather than left to be inferred from the
                  status word, because this is the sentence a support
                  engineer reads back down the phone.
                */}
                <span className="text-muted-foreground text-xs">
                  {isEntitling(subscription.status)
                    ? "Still entitles the plan above."
                    : "Does not entitle anything on its own."}
                </span>
              </span>
            </Fact>
            <Fact label="Paying for">{subscription.plan}</Fact>
            <Fact label="Ending">
              {subscription.cancel_at_period_end
                ? "Cancelled — runs to the end of the period"
                : "No"}
            </Fact>
            <Fact label="Period">
              {subscription.current_period_start && subscription.current_period_end
                ? `${when(subscription.current_period_start)} to ${when(subscription.current_period_end)}`
                : null}
            </Fact>
            <Fact label="Provider">{subscription.provider}</Fact>
            <Fact label="Customer id" mono>
              {subscription.provider_customer_id}
            </Fact>
            <Fact label="Subscription id" mono>
              {subscription.provider_subscription_id}
            </Fact>
            <Fact label="Created">{when(subscription.created_at)}</Fact>
            <Fact label="Last changed">{when(subscription.updated_at)}</Fact>
          </Facts>
        )}
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">Grant a plan</h2>
          <p className="text-muted-foreground text-xs">
            A pilot, a comp, an enterprise contract invoiced offline. It
            outranks whatever the provider says and survives every delivery
            that follows — which is exactly why it is worth being careful
            with.
          </p>
        </div>

        <PlanOverrideControls workspaceId={workspaceId} />
      </section>
    </div>
  );
}
