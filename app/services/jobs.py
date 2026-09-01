"""What each kind of job actually does.

The catalogue, in the shape `app/services/automations.py` already uses: a
handler per kind, gathered into one dictionary at the bottom, so that the
list of work this application defers is a thing somebody can read in one
place.

Every handler is written to be run twice. A worker killed between finishing
the work and recording that it finished leaves a job that will be claimed
again, so "done once" cannot mean "attempted once" -- it has to mean that
attempting it again changes nothing.
"""

import logging
import uuid

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.models.automation import AutomationTrigger
from app.models.job import Job, JobKind
from app.repositories.automation_repository import AutomationRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.ai_dispatch import build_message_service
from app.services.automation_dispatch import build_automation_service
from app.services.job_service import JobContext, JobHandler

logger = logging.getLogger(__name__)


def _window(context: JobContext) -> int:
    """Which sweep window `now` falls in.

    The deduplication key for planned work is bucketed into these, so two
    workers ticking a second apart plan the same window rather than two.
    An integer rather than a timestamp because it is being compared for
    equality and nothing else.
    """
    every = get_settings().worker_sweep_every_seconds

    return int(context.now.timestamp()) // every


class DeliverMessage:
    """Send a reply that is already written into a thread.

    Idempotent because the message service refuses to deliver one that has
    already gone out, which is the guard that matters here: this job is
    enqueued the moment a delivery fails, and the failure it is most
    likely to be recovering from is one where the provider accepted the
    message and this application did not hear so.
    """

    def run(self, context: JobContext, job: Job) -> None:
        workspace_id = job.workspace_id

        if workspace_id is None:
            # Nothing enqueues this without one. Checked because a payload
            # written minutes ago is not an argument anybody type-checked.
            logger.warning("A delivery job named no workspace")

            return

        workspace = WorkspaceRepository(context.session).get(workspace_id)

        if workspace is None:
            # The business is gone. Not an error and not worth retrying:
            # there is nobody to deliver on behalf of.
            return

        messages = build_message_service(context.session, messaging=context.messaging)
        messages.deliver_pending(workspace, uuid.UUID(job.payload["message_id"]))


class SweepAutomations:
    """Plan the scheduled work, without doing any of it.

    The fan-out, and the reason it exists rather than one job that
    iterates: an automation that fails for one business should not stop
    the sweep reaching the next, and a single job either succeeds for
    everybody or retries for everybody.

    Enqueuing is deduplicated on the window, so this running twice --
    two workers, or one worker retrying -- plans the same work once.
    """

    def run(self, context: JobContext, job: Job) -> None:
        window = _window(context)
        automations = AutomationRepository(context.session)

        for workspace_id in automations.workspace_ids_with_enabled(
            AutomationTrigger.SCHEDULE
        ):
            try:
                # A savepoint each, so a key that is already there loses
                # only its own insert. Without it the first duplicate
                # would abort the transaction and the rest of the
                # businesses would go unplanned.
                with context.session.begin_nested():
                    context.jobs.enqueue(
                        kind=JobKind.RUN_DUE_AUTOMATIONS,
                        workspace_id=workspace_id,
                        payload={},
                        dedupe_key=f"run_due_automations:{workspace_id}:{window}",
                        # One attempt. There is another sweep along in a
                        # few minutes, and a follow-up that is late by one
                        # window is not worth a backoff.
                        max_attempts=1,
                    )
            except IntegrityError:
                logger.debug(
                    "Workspace %s is already planned for this window",
                    workspace_id,
                )

        context.session.commit()


class RunDueAutomations:
    """Run one workspace's scheduled automations.

    Safe to run twice on its own terms, and not because of anything here:
    every run the engine records is deduplicated on the thing it acted on,
    so a second pass finds the same dropped threads and correctly does
    nothing about them.
    """

    def run(self, context: JobContext, job: Job) -> None:
        workspace_id = job.workspace_id

        if workspace_id is None:
            logger.warning("A scheduled automation job named no workspace")

            return

        workspace = WorkspaceRepository(context.session).get(workspace_id)

        if workspace is None:
            return

        service = build_automation_service(
            context.session,
            messaging=context.messaging,
        )
        service.run_due(workspace)


# Every kind of deferred work this application knows, in one place. A kind
# missing from here is a job that fails saying so, rather than a worker
# that will not start -- one deployment behind on a handler should drain
# the queue it can and be loud about the rest.
CATALOGUE: dict[JobKind, JobHandler] = {
    JobKind.DELIVER_MESSAGE: DeliverMessage(),
    JobKind.SWEEP_AUTOMATIONS: SweepAutomations(),
    JobKind.RUN_DUE_AUTOMATIONS: RunDueAutomations(),
}
