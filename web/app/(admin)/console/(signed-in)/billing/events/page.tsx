import type { Metadata } from "next";

import { Replay } from "./replay";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { when } from "@/lib/console-labels";
import { listBillingEvents, PLATFORM_PAGE_SIZE } from "@/lib/platform";
import type { AdminBillingEvent, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Billing events" };

/**
 * What the payment provider sent, and what can be applied again.
 *
 * The event type is the provider's word verbatim rather than this
 * application's, which is what makes a row here something somebody can
 * hold up against the provider's own dashboard while they are on the
 * phone to them.
 *
 * Replaying is for the deliveries that were recorded and not acted on: a
 * deploy mid-flight, a bug since fixed, a subscription that did not exist
 * yet.
 */
export default async function ConsoleBillingEventsPage({
  searchParams,
}: {
  searchParams: Promise<{ event_type?: string; page?: string }>;
}) {
  const { event_type: eventType, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let events: Paged<AdminBillingEvent>;

  try {
    events = await listBillingEvents({ eventType, page });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Billing events",
      missing: "No such delivery.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Deliveries"
        back={{ href: "/console/billing", label: "Subscriptions" }}
        description="Everything the provider has sent, newest first."
      />

      <form
        action="/console/billing/events"
        className="flex flex-wrap items-end gap-3 border-y py-3"
      >
        <div className="grid gap-1.5">
          <Label htmlFor="event_type" className="text-xs">
            Event type, as the provider spells it
          </Label>
          <Input
            id="event_type"
            name="event_type"
            defaultValue={eventType ?? ""}
            maxLength={120}
            placeholder="customer.subscription.updated"
            className="h-8 w-72"
          />
        </div>

        <Button type="submit" variant="outline" size="sm">
          Filter
        </Button>

        {eventType ? (
          <ConsoleLink
            href="/console/billing/events"
            className="text-muted-foreground text-sm underline-offset-4 hover:underline"
          >
            Clear
          </ConsoleLink>
        ) : null}
      </form>

      {events.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          Nothing has arrived.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="billing-events">
          {events.items.map((event) => (
            <li
              key={event.id}
              data-event-type={event.event_type}
              className="grid gap-2 rounded-md border px-3 py-2.5"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-mono text-sm">{event.event_type}</span>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {event.provider}
                </Badge>
                <span className="text-muted-foreground ml-auto text-xs">
                  {when(event.received_at)}
                </span>
              </div>

              <p className="text-muted-foreground font-mono text-xs break-all">
                {event.provider_event_id}
              </p>

              <Replay eventId={event.id} replayable={event.replayable} />
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={events.total}
        pageSize={PLATFORM_PAGE_SIZE}
        noun="deliveries"
        href={(to) =>
          `/console/billing/events?${eventType ? `event_type=${encodeURIComponent(eventType)}&` : ""}page=${to}`
        }
      />
    </div>
  );
}
