import type { Metadata } from "next";

import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsolePages } from "@/components/console/pages";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { when } from "@/lib/console-labels";
import { PLATFORM_PAGE_SIZE, searchJobs } from "@/lib/platform";
import type { AdminJobSummary, Page as Paged } from "@/lib/types";

export const metadata: Metadata = { title: "Queue" };

const KINDS = [
  "deliver_message",
  "sweep_automations",
  "run_due_automations",
  "sweep_erasures",
];
const STATUSES = ["pending", "running", "succeeded", "failed", "cancelled"];

const FIELD =
  "border-input bg-background h-8 rounded-md border px-2 text-sm shadow-xs";

/**
 * The queue, across every workspace.
 *
 * `kind=deliver_message&status=failed` is the query this screen exists
 * for: it turns "their message never arrived" into a row with a reason on
 * it, without anybody opening a database console. So it is a link at the
 * top rather than two dropdowns somebody has to think about.
 *
 * Half the rows name no workspace, which is not a gap: the recurring
 * sweeps belong to the platform rather than to any customer.
 */
export default async function ConsoleJobsPage({
  searchParams,
}: {
  searchParams: Promise<{
    kind?: string;
    status?: string;
    workspace_id?: string;
    page?: string;
  }>;
}) {
  const {
    kind,
    status,
    workspace_id: workspaceId,
    page: rawPage,
  } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  let jobs: Paged<AdminJobSummary>;

  try {
    jobs = await searchJobs({ kind, status, workspaceId, page });
  } catch (error) {
    return consoleRefusal(error, { title: "Queue", missing: "No such job." });
  }

  const keep = new URLSearchParams();

  if (kind) keep.set("kind", kind);
  if (status) keep.set("status", status);
  if (workspaceId) keep.set("workspace_id", workspaceId);

  return (
    <div className="grid gap-6">
      <ConsoleHeading
        title="Queue"
        description="Everything waiting, running, or finished badly. A job that names no workspace is one of the platform's own sweeps."
      />

      <p className="text-sm">
        <ConsoleLink
          href="/console/jobs?kind=deliver_message&status=failed"
          className="underline underline-offset-4"
          data-testid="failed-deliveries"
        >
          Messages that failed to send
        </ConsoleLink>{" "}
        <span className="text-muted-foreground text-xs">
          — the question this screen is usually opened with.
        </span>
      </p>

      <form action="/console/jobs" className="flex flex-wrap items-end gap-3 border-y py-3">
        {workspaceId ? (
          <input type="hidden" name="workspace_id" value={workspaceId} />
        ) : null}

        <div className="grid gap-1.5">
          <Label htmlFor="kind" className="text-xs">
            Kind
          </Label>
          <select id="kind" name="kind" defaultValue={kind ?? ""} className={FIELD}>
            <option value="">Any</option>
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="status" className="text-xs">
            Status
          </Label>
          <select id="status" name="status" defaultValue={status ?? ""} className={FIELD}>
            <option value="">Any</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        <Button type="submit" variant="outline" size="sm">
          Filter
        </Button>

        {kind || status || workspaceId ? (
          <ConsoleLink
            href="/console/jobs"
            className="text-muted-foreground text-sm underline-offset-4 hover:underline"
          >
            Clear
          </ConsoleLink>
        ) : null}
      </form>

      {jobs.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          Nothing matches that.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="job-list">
          {jobs.items.map((job) => (
            <li key={job.id}>
              <ConsoleLink
                href={`/console/jobs/${job.id}`}
                className="hover:bg-accent/50 grid gap-1 rounded-md border px-3 py-2.5"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-mono text-sm">{job.kind}</span>

                  <span className="text-muted-foreground text-xs tabular-nums">
                    {job.attempts} of {job.max_attempts} attempts
                  </span>

                  <span className="text-muted-foreground ml-auto text-xs">
                    {when(job.created_at)}
                  </span>

                  <Badge
                    variant={
                      job.status === "failed"
                        ? "destructive"
                        : job.status === "succeeded"
                          ? "secondary"
                          : "outline"
                    }
                    data-status={job.status}
                  >
                    {job.status}
                  </Badge>
                </div>

                {/*
                  On the row rather than behind a click, because it is the
                  whole reason somebody opened this: a failed job with its
                  reason beside it answers the ticket without a second
                  read of the queue.
                */}
                {job.last_error ? (
                  <p className="text-destructive truncate text-xs" data-testid="job-error">
                    {job.last_error}
                  </p>
                ) : null}
              </ConsoleLink>
            </li>
          ))}
        </ul>
      )}

      <ConsolePages
        page={page}
        total={jobs.total}
        pageSize={PLATFORM_PAGE_SIZE}
        noun="jobs"
        href={(to) => `/console/jobs?${new URLSearchParams(keep)}&page=${to}`}
      />

      {/*
        The rest of operations, from the screen somebody is most often on.
        Not in the console's own navigation, which is already nine links --
        these three are asked about from here or not at all.
      */}
      <nav className="text-muted-foreground flex flex-wrap gap-x-5 gap-y-2 border-t pt-4 text-xs">
        <ConsoleLink href="/console/health" className="underline underline-offset-4">
          Health
        </ConsoleLink>
        <ConsoleLink href="/console/webhooks" className="underline underline-offset-4">
          Refused deliveries
        </ConsoleLink>
        <ConsoleLink href="/console/integrations" className="underline underline-offset-4">
          Connected numbers
        </ConsoleLink>
      </nav>
    </div>
  );
}
