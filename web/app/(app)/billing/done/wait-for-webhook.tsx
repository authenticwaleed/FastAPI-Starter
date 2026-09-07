"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/** How long to keep looking before saying so. */
const ATTEMPTS = 10;
const EVERY_MS = 3000;

/**
 * Wait for the provider's confirmation, and stop waiting.
 *
 * `router.refresh()` re-renders the page above from the server, which
 * re-reads the subscription. When the webhook lands, that render finds an
 * entitling status and this component is no longer on the page.
 *
 * Bounded on purpose. A poll that never gives up is a tab quietly making
 * requests for the rest of the afternoon, and the honest thing after half
 * a minute is to say it has not arrived and offer the page that will show
 * it when it does. Nothing is lost by leaving: the webhook does not need
 * anybody watching.
 */
export function WaitForWebhook() {
  const [attempts, setAttempts] = useState(0);
  const router = useRouter();

  useEffect(() => {
    if (attempts >= ATTEMPTS) return;

    const timer = setTimeout(() => {
      setAttempts((so_far) => so_far + 1);
      router.refresh();
    }, EVERY_MS);

    return () => clearTimeout(timer);
  }, [attempts, router]);

  if (attempts >= ATTEMPTS) {
    return (
      <div className="grid gap-2">
        <p className="text-muted-foreground text-sm" role="status">
          It has not come through yet. It usually does within a minute or two,
          and nothing needs you here for that to happen.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={() => {
            setAttempts(0);
            router.refresh();
          }}
        >
          Check again
        </Button>
      </div>
    );
  }

  return (
    <p className="text-muted-foreground text-sm" role="status">
      Checking…
    </p>
  );
}
