"use client";

import { useActionState } from "react";

import { Refused } from "@/components/console/refused";
import { Button } from "@/components/ui/button";
import type { FormState } from "@/lib/form-state";
import { cancelJob, retryJob } from "@/lib/platform-actions";
import type { JobStatus } from "@/lib/types";

/**
 * Retry and cancel, in one component and below the error.
 *
 * Together for the reason the lifecycle pairs are: a `409` refuses
 * whichever was offered and the answer is to re-render what applies now,
 * which would unmount a separate component holding the refusal before
 * anybody read it.
 *
 * Both are refused while the job is running, and the refusal says so. The
 * worker holding that row does not check back, so moving it would let a
 * second worker claim the same work and race the first.
 */
export function JobControls({
  jobId,
  status,
}: {
  jobId: string;
  status: JobStatus;
}) {
  const [retryState, retry] = useActionState<FormState, FormData>(retryJob, null);
  const [cancelState, cancel] = useActionState<FormState, FormData>(cancelJob, null);

  return (
    <section className="grid gap-3">
      <h2 className="text-sm font-medium">What can be done</h2>

      <Refused state={retryState} />
      <Refused state={cancelState} />

      {status === "running" ? (
        <p className="text-muted-foreground text-sm" data-testid="job-running">
          It is running. Nothing can be moved until the worker holding it is
          finished — a second worker claiming the same row would race the
          first.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <form action={retry}>
            <input type="hidden" name="job_id" value={jobId} />
            <Button type="submit" variant="outline" size="sm">
              Put it back in the queue
            </Button>
          </form>

          <form action={cancel}>
            <input type="hidden" name="job_id" value={jobId} />
            <Button type="submit" variant="ghost" size="sm">
              Cancel it
            </Button>
          </form>

          <span className="text-muted-foreground text-xs">
            Retrying forgives the attempts; cancelling is its own status, so
            afterwards it reads as a decision rather than a failure.
          </span>
        </div>
      )}
    </section>
  );
}
