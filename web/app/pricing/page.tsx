import type { Metadata } from "next";
import Link from "next/link";

import { PlanCard } from "@/components/plan-card";
import { listPlans } from "@/lib/billing";

export const metadata: Metadata = { title: "Pricing" };

/**
 * The price list, for somebody who has not signed up.
 *
 * Outside both the signed-in shell and the sign-in card, with its own thin
 * chrome, because it belongs to neither: whoever is reading it is deciding
 * whether to have an account at all. The API serves `/plans`
 * unauthenticated for the same reason -- asking somebody to register to
 * find out what it costs is the wrong way round.
 */
export default async function PricingPage() {
  const plans = await listPlans();

  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-4 px-4">
          <Link href="/" className="font-semibold tracking-tight">
            Baton
          </Link>
          <div className="ml-auto flex items-center gap-4 text-sm">
            <Link href="/sign-in" className="underline-offset-4 hover:underline">
              Sign in
            </Link>
            <Link
              href="/register"
              className="bg-primary text-primary-foreground rounded-md px-3 py-1.5"
            >
              Create an account
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-12">
        <div className="mb-8 max-w-xl">
          <h1 className="text-3xl font-semibold tracking-tight text-balance">
            One inbox, and an assistant that knows your catalogue
          </h1>
          <p className="text-muted-foreground mt-2">
            Start free. Everything below is per workspace — one business, its
            team, its customers and its plan.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3" data-testid="plan-list">
          {plans.map((plan) => (
            <PlanCard key={plan.tier} plan={plan} />
          ))}
        </div>

        <p className="text-muted-foreground mt-8 text-sm">
          A card that stops working does not lock you out: a failed payment
          keeps your plan while it is retried, and an account that lapses
          falls back to the free tier rather than to nothing.
        </p>
      </main>
    </div>
  );
}
