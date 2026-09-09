import type { Metadata } from "next";

import { JobControls } from "./job-controls";
import { ConsoleLink } from "@/components/console/console-link";
import { Fact, Facts } from "@/components/console/facts";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { when } from "@/lib/console-labels";
import { readJob } from "@/lib/platform";
import type { AdminJobDetail } from "@/lib/types";

export const metadata: Metadata = { title: "A job" };

/**
 * One job, why it failed, and only then what can be done about it.
 *
 * The order on this screen is the phase's rule: a failed job shows why it
 * failed *before* offering a retry. Pressing retry without reading the
 * error is how a message that will fail for the same reason gets sent
 * four more times.
 *
 * The payload is redacted by the API on a safe-list by kind, and a field
 * nobody named comes back as `[redacted]` rather than being dropped -- so
 * a reader can tell "there is something here I am not being shown" from
 * "there is nothing here". An operations console is not a licence to read
 * customers' messages; support access is, with a reason and an expiry the
 * customer can see.
 */
export default async function ConsoleJobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  let job: AdminJobDetail;

  try {
    job = await readJob(jobId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "A job",
      missing: "No job exists with that id.",
    });
  }

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title={job.kind}
        back={{ href: "/console/jobs", label: "Queue" }}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge
              variant={job.status === "failed" ? "destructive" : "outline"}
              data-status={job.status}
            >
              {job.status}
            </Badge>
            <span className="text-xs tabular-nums">
              {job.attempts} of {job.max_attempts} attempts
            </span>
          </span>
        }
      />

      {job.last_error ? (
        <section className="grid gap-2">
          <h2 className="text-sm font-medium">Why it failed</h2>
          <p
            className="border-destructive/40 text-destructive rounded-md border px-4 py-3 font-mono text-xs break-all"
            data-testid="job-error"
          >
            {job.last_error}
          </p>
        </section>
      ) : null}

      <JobControls jobId={job.id} status={job.status} />

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">The job</h2>
        <Facts>
          <Fact label="Due">{when(job.run_at)}</Fact>
          <Fact label="Started">{job.started_at ? when(job.started_at) : null}</Fact>
          <Fact label="Finished">
            {job.finished_at ? when(job.finished_at) : null}
          </Fact>
          <Fact label="Workspace">
            {job.workspace_id ? (
              <ConsoleLink
                href={`/console/workspaces/${job.workspace_id}`}
                className="font-mono text-xs underline underline-offset-4"
              >
                {job.workspace_id}
              </ConsoleLink>
            ) : (
              // Not a gap. The recurring sweeps belong to the platform.
              "One of the platform's own sweeps"
            )}
          </Fact>
          <Fact label="Dedupe key" mono>
            {job.dedupe_key}
          </Fact>
          <Fact label="Id" mono>
            {job.id}
          </Fact>
        </Facts>
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">Payload</h2>
          <p className="text-muted-foreground text-xs">
            As much as this kind of job admits. Anything shown as
            &ldquo;[redacted]&rdquo; is there and not being shown.
          </p>
        </div>
        <pre className="bg-muted overflow-x-auto rounded-md px-3 py-2.5 text-xs">
          {JSON.stringify(job.payload, null, 2)}
        </pre>
      </section>
    </div>
  );
}
