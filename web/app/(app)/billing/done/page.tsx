import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { WaitForWebhook } from "./wait-for-webhook";
import { Badge } from "@/components/ui/badge";
import { readSubscription } from "@/lib/billing";
import { isEntitling } from "@/lib/plans";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Payment" };

/**
 * Where the payment provider sends somebody back to.
 *
 * This is the screen that has to be honest about a thing every checkout
 * flow gets wrong. Coming back here does not mean the subscription is
 * real: the card was entered on the provider's page, and what makes it
 * real is a webhook that arrives separately and may not have landed yet.
 *
 * So this reads the subscription and says which of the two it is, rather
 * than congratulating somebody on a plan they may not have for another few
 * seconds. `FRONTEND_BASE_URL/billing/done` is the address the API gives
 * the provider as the success URL.
 */
export default async function CheckoutDonePage() {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const current = await readSubscription(workspace.id);
  const subscription = current.subscription;

  // `incomplete` is a checkout that was started and has not been confirmed
  // -- which is exactly what a row looks like in the gap between paying
  // and the webhook arriving.
  const landed =
    subscription !== null && isEntitling(subscription.status);

  return (
    <div className="mx-auto grid max-w-lg gap-4 py-8">
      {landed ? (
        <>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              You are on {current.plan.name}
            </h1>
            <Badge variant="secondary">{subscription.status}</Badge>
          </div>
          <p className="text-muted-foreground text-sm">
            The payment went through and the plan is in force.
          </p>
          <Link href="/billing" className="text-sm underline underline-offset-4">
            See the plan and what you have used
          </Link>
        </>
      ) : (
        <>
          <h1 className="text-2xl font-semibold tracking-tight">
            Waiting for the payment to be confirmed
          </h1>
          <p className="text-muted-foreground text-sm">
            The card was taken on the payment provider&rsquo;s page. What makes
            the plan real is their confirmation reaching us, which is usually
            a few seconds behind you.
          </p>
          {/*
            Polls rather than pretending. A screen that said "you are on
            Growth" the instant somebody came back would be guessing, and
            would be wrong for every card that gets declined at the last
            step.
          */}
          <WaitForWebhook />
        </>
      )}
    </div>
  );
}
