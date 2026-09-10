import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { EmptyState } from "@/components/empty-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { when } from "@/lib/console-labels";
import { listWhatsAppNumbers } from "@/lib/platform";
import type { AdminWhatsAppNumber } from "@/lib/types";

export const metadata: Metadata = { title: "Numbers" };

/**
 * Every connected number, and whose it is.
 *
 * Health as the account row records it rather than by asking Meta about
 * each number in turn: a page costing one API call per customer is a page
 * that times out on the day it is most needed.
 *
 * The workspace is on every row because a broken number without an
 * account beside it is a phone number nobody can act on.
 */
export default async function ConsoleNumbersPage() {
  let numbers: AdminWhatsAppNumber[];

  try {
    numbers = await listWhatsAppNumbers();
  } catch (error) {
    return consoleRefusal(error, { title: "Numbers", missing: "No such number." });
  }

  const broken = numbers.filter((number) => number.status !== "connected");

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Numbers"
        description="Every WhatsApp number connected to this platform, and the business it belongs to."
      />

      {broken.length > 0 ? (
        <Alert variant="destructive" role="status" data-testid="broken-numbers">
          <AlertDescription>
            {broken.length} number{broken.length === 1 ? " is" : "s are"} not
            connected. Their customers&rsquo; messages are not being answered.
          </AlertDescription>
        </Alert>
      ) : null}

      {numbers.length === 0 ? (
        <EmptyState title="Nobody has connected a number" />
      ) : (
        <ul className="grid gap-2" data-testid="number-list">
          {numbers.map((number) => (
            <li key={number.external_phone_number_id}>
              <ConsoleLink
                href={`/console/workspaces/${number.workspace_id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 row"
              >
                <span className="text-sm">{number.phone_number}</span>
                <span className="text-muted-foreground font-mono text-xs">
                  {number.workspace_slug}
                </span>
                <span className="text-muted-foreground text-xs">
                  Connected {when(number.connected_at)}
                </span>
                <Badge
                  variant={number.status === "connected" ? "secondary" : "destructive"}
                  className="ml-auto"
                  data-status={number.status}
                >
                  {number.status}
                </Badge>
              </ConsoleLink>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
