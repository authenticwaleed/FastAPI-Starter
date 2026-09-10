import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { CancelSubscription } from "./cancel-subscription";
import { PlanPicker } from "./plan-picker";
import { UsageMeters } from "./usage-meters";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { listPlans, readSubscription, readUsage } from "@/lib/billing";
import { isEnding, needsAttention } from "@/lib/plans";
import type { Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Plan and billing" };

const MAY_ADMINISTER = ["owner", "admin"];

function when(value: string | null): string {
  return value
    ? new Date(value).toLocaleDateString(undefined, { dateStyle: "long" })
    : "—";
}

/**
 * What this workspace is on, and what it has used.
 *
 * Readable by any member, which is the API's choice and the right one:
 * what the business is on governs what everybody working in it can do, and
 * being told "your plan does not include this" by a screen that will not
 * say what the plan is would be a dead end. Changing it is admin work.
 */
export default async function BillingPage() {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const [current, usage, plans, user, members] = await Promise.all([
    readSubscription(workspace.id),
    readUsage(workspace.id),
    listPlans(),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  const { plan, subscription } = current;
  const ending = isEnding(current);
  const warn = needsAttention(current);

  return (
    <div className="grid gap-8">
      <PageHeader
        title="Plan and billing"
        description={`What ${workspace.name} may do, and what it has used.`}
      />

      <section className="grid gap-3 panel">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-medium">{plan.name}</h2>
          {/*
            The plan that applies, which is not always the one being paid
            for. An override outranks the provider, and a `past_due`
            subscription still entitles its plan while the card is retried.
          */}
          <Badge variant="secondary">In force</Badge>
          {subscription && subscription.plan !== plan.tier ? (
            <span className="text-muted-foreground text-xs">
              billed as {subscription.plan}
            </span>
          ) : null}
        </div>

        {subscription === null ? (
          <p className="text-muted-foreground text-sm">
            Nothing has been paid for yet. This is the free plan.
          </p>
        ) : (
          <dl className="grid gap-1 text-sm sm:grid-cols-3">
            <div className="grid gap-0.5">
              <dt className="text-muted-foreground text-xs uppercase">Status</dt>
              <dd>{subscription.status}</dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="text-muted-foreground text-xs uppercase">
                {ending ? "Ends" : "Renews"}
              </dt>
              <dd>{when(subscription.current_period_end)}</dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="text-muted-foreground text-xs uppercase">Since</dt>
              <dd>{when(subscription.created_at)}</dd>
            </div>
          </dl>
        )}

        {warn ? (
          // A warning and nothing else. `past_due` is a card that did not
          // go through and a provider still retrying, so the plan keeps
          // applying -- taking a business's features away over a bank's
          // fraud check is the wrong way to lose a customer.
          <Alert variant="warning" role="status" data-testid="payment-warning">
            <AlertDescription>
              A payment did not go through. Nothing has been switched off —
              the plan still applies while it is retried. Updating the card
              on file is what stops it becoming a problem.
            </AlertDescription>
          </Alert>
        ) : null}

        {ending ? (
          // Stopping, not stopped. The month has been paid for, so
          // everything keeps working until it runs out.
          <Alert role="status">
            <AlertDescription>
              This subscription ends on{" "}
              {when(subscription?.current_period_end ?? null)}. Everything
              keeps working until then, and it falls back to the free plan
              afterwards rather than to nothing.
            </AlertDescription>
          </Alert>
        ) : null}
      </section>

      <UsageMeters usage={usage} />

      <PlanPicker
        workspaceId={workspace.id}
        plans={plans}
        currentTier={plan.tier}
        canChange={administers}
      />

      {administers && subscription && !ending ? (
        <CancelSubscription workspaceId={workspace.id} />
      ) : null}
    </div>
  );
}
