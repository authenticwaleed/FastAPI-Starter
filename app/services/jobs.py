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


class EraseWorkspace:
    """Destroy one closed workspace's data, once its date has passed.

    The only job that names its workspace in the payload rather than in
    `workspace_id`, and it has to: that column cascades, so a job owned by
    the workspace it deletes deletes itself halfway through and leaves the
    runner marking a row that is no longer there. This one job has to
    outlive its subject.

    The date is checked again here and not merely when the job was queued.
    A job can sit in the queue through a restart, a reclaim, and an
    administrator changing their mind -- and the one job in this system
    that cannot be undone is the one that must not act on a stale reason.

    Nothing is written to the audit log at this point, because there is
    nowhere to write it: the entry would belong to the workspace being
    deleted and would go with it. What survives is the `workspace.closed`
    entry from when the erasure was scheduled, and the line this leaves in
    the log stream.
    """

    def run(self, context: JobContext, job: Job) -> None:
        named = job.payload.get("workspace_id")

        if not named:
            logger.warning("An erasure job named no workspace")

            return

        workspace_id = uuid.UUID(str(named))

        workspaces = WorkspaceRepository(context.session)
        workspace = workspaces.get(workspace_id)

        if workspace is None:
            # Already gone. Two workers, or a retry after the delete
            # committed and the job did not -- either way there is nothing
            # left to do and that is a success.
            return

        if workspace.erase_after is None or workspace.erase_after > context.now:
            # Reopened, or the date was moved out. Not an error: somebody
            # changed their mind, which is what the grace period is for.
            logger.info("Workspace %s is no longer due for erasure", workspace_id)

            return

        workspaces.erase(workspace)
        context.session.commit()

        logger.info("Erased workspace %s and everything it held", workspace_id)


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


class SweepErasures:
    """Queue an erasure for every workspace whose retention period is over.

    A fan-out like the automation sweep, and for a sharper version of the
    same reason: one job that deleted every due workspace would, on
    failing halfway, retry and delete the first ones again -- harmlessly,
    but with no way to tell a partial run from a complete one. One job per
    workspace makes each deletion its own success or failure.
    """

    def run(self, context: JobContext, job: Job) -> None:
        workspaces = WorkspaceRepository(context.session)

        for workspace_id in workspaces.due_for_erasure(now=context.now):
            try:
                with context.session.begin_nested():
                    context.jobs.enqueue(
                        kind=JobKind.ERASE_WORKSPACE,
                        # In the payload, not the column. See EraseWorkspace:
                        # `workspace_id` cascades, and a job owned by what
                        # it deletes deletes itself halfway through.
                        payload={"workspace_id": str(workspace_id)},
                        # One per workspace, for ever. There is no second
                        # erasure of the same business, and a key without
                        # a window in it says so.
                        dedupe_key=f"erase_workspace:{workspace_id}",
                        max_attempts=3,
                    )
            except IntegrityError:
                logger.debug("Workspace %s is already queued for erasure", workspace_id)

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
    JobKind.SWEEP_ERASURES: SweepErasures(),
    JobKind.ERASE_WORKSPACE: EraseWorkspace(),
}
