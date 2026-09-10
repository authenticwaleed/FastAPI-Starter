"use client";

import { useEffect, useState } from "react";

import { ConsoleLink } from "@/components/console/console-link";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { timeLeft } from "@/lib/console-labels";

/**
 * How long is left, counting down, above whatever is being read.
 *
 * The phase's hardest rule: the remaining time is on screen the whole time
 * somebody is reading a customer's data. Access that expires silently
 * mid-read is worse than access that is refused -- the second is an answer
 * and the first is a page that quietly stops working.
 *
 * A client component for the clock and for nothing else. It fetches
 * nothing, polls nothing, and knows one timestamp, handed to it by the
 * server. Every read behind it is still refused by the API the moment the
 * grant is gone; this only makes sure nobody is surprised by that.
 *
 * `now` arrives as a prop so the first client render matches the server's
 * and the number does not flicker on hydration. After that the browser's
 * own clock takes over.
 */
export function SupportWindow({
  workspaceId,
  expiresAt,
  now,
}: {
  workspaceId: string;
  expiresAt: string;
  now: number;
}) {
  const [left, setLeft] = useState(() => timeLeft(expiresAt, now));

  useEffect(() => {
    const tick = () => setLeft(timeLeft(expiresAt, Date.now()));

    tick();

    // Ten seconds. Fine enough that "less than a minute" does not sit
    // there after the window has shut, coarse enough to be nothing.
    const timer = setInterval(tick, 10_000);

    return () => clearInterval(timer);
  }, [expiresAt]);

  if (left === null) {
    return (
      <Alert
        variant="destructive"
        role="alert"
        data-testid="support-window"
        data-state="closed"
      >
        <AlertDescription>
          This window has closed. Nothing further can be read here until you{" "}
          <ConsoleLink
            href={`/console/workspaces/${workspaceId}/support-access`}
          >
            ask for access again
          </ConsoleLink>
          .
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <Alert
      // A warning while it is open, because that is what it is: a window
      // onto somebody else's data that a colleague granted and that is
      // running out. Neutral would let it be scrolled past, and red would
      // say something had gone wrong.
      variant="warning"
      role="status"
      data-testid="support-window"
      data-state="open"
      className="flex flex-wrap items-center gap-x-3 gap-y-1"
    >
      <span>
        You are reading a customer&rsquo;s own data. <strong>{left}</strong>{" "}
        left.
      </span>

      <ConsoleLink
        href={`/console/workspaces/${workspaceId}/support-access`}
        className="text-muted-foreground ml-auto text-xs underline-offset-4 hover:underline"
      >
        End access
      </ConsoleLink>
    </Alert>
  );
}
