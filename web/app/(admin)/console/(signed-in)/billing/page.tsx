import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { day } from "@/lib/console-labels";
import { listSubscriptions, PLATFORM_PAGE_SIZE } from "@/lib/platform";
import { isEntitling } from "@/lib/plans";
import type { AdminSubscriptionRow, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Billing" };

/**
 * Every subscription, and one list that matters more than the rest.
 *
 * `past_due` is the reason this screen exists, so it is a link of its own
 * rather than a value in a dropdown: those are the businesses whose card
 * did not go through and who still have their plan while the provider
 * retries. Each is either about to pay or about to churn, and somebody
 * should be looking at them before they become `unpaid`.
 *
 * These are the provider's words, not this platform's. A business comped
 * onto Business appears here on whatever it is actually paying for --
 * which is the point: this is the ledger, and the console's workspace
 * search is where "what may they actually do" is asked.
 */
const LISTS = [
  { status: "past_due", label: "Needs attention", note: "Retrying, still entitled" },
  { status: "unpaid", label: "Unpaid", note: "The provider has given up" },
  { status: "active", label: "Active" },
  { status: "trialing", label: "Trialing" },
  { status: "canceled", label: "Cancelled" },
];

function tab(active: boolean) {
  return active
    ? "font-medium underline underline-offset-4"
    : "text-muted-foreground underline-offset-4 hover:underline";
}

export default async function ConsoleBillingPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; page?: string }>;
}) {
  const { status, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let ledger: Paged<AdminSubscriptionRow>;

  try {
    ledger = await listSubscriptions({ status, page });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Billing",
      missing: "No such subscription.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Subscriptions"
        description="What the payment provider says is being paid for. Not what a workspace may do — a comped business shows here on what it actually pays."
      />

      <nav
        className="flex flex-wrap items-center gap-x-5 gap-y-2 border-y py-3 text-sm"
        aria-label="Subscription lists"
      >
        <ConsoleLink href="/console/billing" className={tab(!status)}>
          All
        </ConsoleLink>

        {LISTS.map((list) => (
          <span key={list.status} className="flex items-baseline gap-2">
            <ConsoleLink
              href={`/console/billing?status=${list.status}`}
              className={tab(status === list.status)}
              data-testid={`list-${list.status}`}
            >
              {list.label}
            </ConsoleLink>
            {list.note ? (
              <span className="text-muted-foreground text-xs">{list.note}</span>
            ) : null}
          </span>
        ))}
      </nav>

      {ledger.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          {status === "past_due"
            ? "Nothing is being retried. This is the list you want to be empty."
            : "No subscriptions here."}
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="subscription-list">
          {ledger.items.map((row) => (
            <li key={row.id}>
              {/*
                The ledger names a workspace by slug and every console
                route is keyed on its id, so this goes to the search
                rather than pretending to be a link to the account. One
                more click, and no invented id.
              */}
              <ConsoleLink
                href={`/console/workspaces?q=${encodeURIComponent(row.workspace_slug)}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
              >
                <span className="font-mono text-sm">{row.workspace_slug}</span>

                <span className="text-muted-foreground text-xs">
                  {row.current_period_end
                    ? `Period ends ${day(row.current_period_end)}`
                    : "No period"}
                </span>

                {row.cancel_at_period_end ? (
                  <Badge variant="outline">ending</Badge>
                ) : null}

                <span className="ml-auto flex items-center gap-2">
                  <Badge variant="outline">{row.plan}</Badge>
                  {/*
                    Coloured on whether it still entitles rather than on
                    whether it is tidy. `past_due` is amber-ish here on
                    purpose: the customer has their plan, and the risk is
                    commercial rather than technical.
                  */}
                  <Badge
                    variant={isEntitling(row.status) ? "secondary" : "destructive"}
                    data-status={row.status}
                  >
                    {row.status}
                  </Badge>
                </span>
              </ConsoleLink>
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={ledger.total}
        pageSize={PLATFORM_PAGE_SIZE}
        noun="subscriptions"
        href={(to) =>
          `/console/billing?${status ? `status=${status}&` : ""}page=${to}`
        }
      />

      <p className="text-muted-foreground text-xs">
        <ConsoleLink
          href="/console/billing/events"
          className="underline underline-offset-4"
        >
          Deliveries from the provider
        </ConsoleLink>{" "}
        — what arrived, and what can be applied again.
      </p>
    </div>
  );
}
