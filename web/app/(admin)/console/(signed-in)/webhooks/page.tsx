import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { when } from "@/lib/console-labels";
import { listWebhookFailures, PLATFORM_PAGE_SIZE } from "@/lib/platform";
import type { AdminWebhookFailure, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Refused deliveries" };

const REASONS = ["bad_signature", "unknown_subject", "malformed"];

/** What each refusal usually means, which is the whole use of the filter. */
const MEANS: Record<string, string> = {
  bad_signature:
    "A wrong secret, or somebody probing. One address repeatedly is the second.",
  unknown_subject: "A delivery about something this platform does not hold.",
  malformed: "A body this application could not read at all.",
};

/**
 * Deliveries this application turned away.
 *
 * The one failure in the system that otherwise reaches nobody. The
 * provider is told with a status code, the sender is a machine, and the
 * customer whose storefront secret was mistyped notices days later that
 * their orders stopped arriving.
 *
 * No body is kept, ever: a delivery that failed to verify came from
 * somebody unproven, so what is here is enough to recognise a pattern --
 * which endpoint, which reason, from where -- and nothing they chose to
 * send.
 */
export default async function ConsoleWebhookFailuresPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string; page?: string }>;
}) {
  const { reason, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let failures: Paged<AdminWebhookFailure>;

  try {
    failures = await listWebhookFailures({ reason, page });
  } catch (error) {
    return consoleRefusal(error, {
      title: "Refused deliveries",
      missing: "No such delivery.",
    });
  }

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Refused deliveries"
        description="Webhooks this application turned away. Nobody else finds out about these — the sender is a machine and the customer notices days later."
      />

      <form
        action="/console/webhooks"
        className="flex flex-wrap items-end gap-3 border-y py-3"
      >
        <div className="grid gap-1.5">
          <Label htmlFor="reason" className="text-xs">
            Reason
          </Label>
          <NativeSelect
            id="reason"
            name="reason"
            defaultValue={reason ?? ""}
          >
            <option value="">Any</option>
            {REASONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </div>

        <Button type="submit" variant="outline" size="sm">
          Filter
        </Button>

        {reason ? (
          <>
            <ConsoleLink
              href="/console/webhooks"
              className="text-muted-foreground text-sm underline-offset-4 hover:underline"
            >
              Clear
            </ConsoleLink>
            <span className="text-muted-foreground w-full text-xs">
              {MEANS[reason]}
            </span>
          </>
        ) : null}
      </form>

      {failures.items.length === 0 ? (
        <EmptyState title="Nothing has been turned away" />
      ) : (
        <ul className="grid gap-2" data-testid="webhook-failures">
          {failures.items.map((failure) => (
            <li
              key={failure.id}
              data-reason={failure.reason}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 row"
            >
              <Badge variant="outline">{failure.provider}</Badge>
              <span className="font-mono text-xs">{failure.path}</span>
              <span className="text-muted-foreground font-mono text-xs">
                {failure.ip_address ?? "—"}
              </span>
              <span className="text-muted-foreground ml-auto text-xs">
                {when(failure.received_at)}
              </span>
              <Badge variant="destructive">{failure.reason}</Badge>
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={failures.total}
        pageSize={PLATFORM_PAGE_SIZE}
        noun="refusals"
        href={(to) =>
          `/console/webhooks?${reason ? `reason=${reason}&` : ""}page=${to}`
        }
      />
    </div>
  );
}
