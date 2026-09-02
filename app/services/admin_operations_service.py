"""Answering "why did this not work" without a database console.

Phase A6, and it is the phase that decides whether anybody can run this
product at three in the morning. Three questions, and each has a shape:

**Where is that message?** The queue, searchable by kind, status and
workspace, with the payload redacted by kind rather than dumped.

**Why are their orders not arriving?** The deliveries this application
turned away, which is otherwise the one failure nobody hears about.

**Is anything wrong right now?** Queue depth and the age of the oldest
waiting job -- two numbers, because either alone says nothing.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import JobNotFoundError, JobNotRetryableError
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.job import Job, JobKind, JobStatus
from app.models.webhook_failure import WebhookFailure, WebhookRefusal
from app.models.whatsapp_account import WhatsAppAccount
from app.models.workspace import Workspace
from app.repositories.job_repository import JobRepository
from app.repositories.webhook_failure_repository import WebhookFailureRepository
from app.repositories.whatsapp_account_repository import WhatsAppAccountRepository
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.job_service import JobRepositoryDep
from app.services.staff_service import StaffActor
from app.services.webhook_failure_service import WebhookFailureRepositoryDep
from app.services.whatsapp_service import WhatsAppAccountRepositoryDep

# What each kind of job is allowed to show. A safe-list rather than a list
# of things to hide, and that direction is the whole protection: a payload
# that grows a field is redacted by default, where a deny-list would leak
# it until somebody noticed.
#
# Every value here is an identifier. None of them is text a customer
# wrote, and none of them ever should be -- an operations console is not
# a licence to read messages, and Phase A3 exists for when that is
# genuinely needed.
VISIBLE_PAYLOAD: dict[JobKind, frozenset[str]] = {
    JobKind.DELIVER_MESSAGE: frozenset({"message_id"}),
    JobKind.SWEEP_AUTOMATIONS: frozenset({"window"}),
    JobKind.RUN_DUE_AUTOMATIONS: frozenset({"automation_id", "window"}),
    JobKind.SWEEP_ERASURES: frozenset({"window"}),
    JobKind.ERASE_WORKSPACE: frozenset({"workspace_id"}),
}

# What a redacted field is replaced by. A marker rather than removal, so
# a reader can tell "this job carries something I am not being shown"
# from "this job carries nothing".
REDACTED = "[redacted]"


def visible_payload(job: Job) -> dict[str, Any]:
    """A job's payload, with everything not named for its kind hidden.

    By kind, because that is the only thing that says what a payload
    holds. A `deliver_message` job names a message; the day somebody adds
    the message *text* to that payload to save a lookup, this keeps it
    out of the console without anybody having to remember.

    A kind nobody has listed shows nothing at all, which is the safe end
    of the failure: a new job type appears in the console with its
    payload hidden, and somebody adds it to the list on purpose.
    """
    allowed = VISIBLE_PAYLOAD.get(job.kind, frozenset())

    return {
        key: (value if key in allowed else REDACTED)
        for key, value in job.payload.items()
    }


@dataclass(frozen=True)
class QueueHealth:
    """The two numbers that say whether the worker has stopped.

    Depth alone cannot: two hundred draining in a minute is a busy
    afternoon, and three where the oldest has waited an hour is a worker
    that died. The age is what tells them apart, and it is why both are
    here rather than one.
    """

    depth: int
    # None where nothing is due, which is not zero -- zero would read as
    # "something is waiting and it just arrived".
    oldest_pending_seconds: float | None
    running: int
    failed: int


@dataclass(frozen=True)
class PlatformHealth:
    """What is working, as far as this process can tell from where it sits."""

    database: bool
    queue: QueueHealth
    # Whether each integration is configured, which is not whether it is
    # reachable -- see AdminOperationsService.health for why this stops
    # short of dialling them.
    integrations: dict[str, bool]


class AdminOperationsService:
    """The queue, the refusals, and whether anything is wrong right now."""

    def __init__(
        self,
        session: Session,
        jobs: JobRepository,
        failures: WebhookFailureRepository,
        whatsapp: WhatsAppAccountRepository,
        admin_audit: AdminAuditService,
    ) -> None:
        self._session = session
        self._jobs = jobs
        self._failures = failures
        self._whatsapp = whatsapp
        self._admin_audit = admin_audit

    # --- the queue ---------------------------------------------------------

    def search_jobs(
        self,
        actor: StaffActor,
        *,
        kind: JobKind | None = None,
        status: JobStatus | None = None,
        workspace_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[Job], int]:
        """Jobs across every workspace, newest first.

        The acceptance criterion is one query away from here: a failed
        `deliver_message` is findable by workspace and by kind, which is
        how "their message never arrived" turns into a row with an error
        on it.
        """
        found = self._jobs.search(
            limit=page_size,
            offset=(page - 1) * page_size,
            kind=kind,
            status=status,
            workspace_id=workspace_id,
        )
        total = self._jobs.count_matching(
            kind=kind,
            status=status,
            workspace_id=workspace_id,
        )

        self._admin_audit.did(
            actor.logged,
            AdminAction.JOBS_SEARCHED,
            workspace_id=workspace_id,
            meta={
                "kind": kind.value if kind else None,
                "status": status.value if status else None,
                "results": total,
            },
        )
        self._session.commit()

        return found, total

    def read_job(self, actor: StaffActor, job_id: uuid.UUID) -> Job:
        job = self._job(job_id)

        self._record(actor, AdminAction.JOB_READ, job, {})

        return job

    def retry_job(self, actor: StaffActor, job_id: uuid.UUID) -> Job:
        """Put a job back in the queue, attempts forgiven.

        Refused while it is running, and that refusal is the plan's
        "retry must respect dedupe_key" in practice: the row is claimed
        by a worker that may still be part-way through it, and moving it
        back to pending would let a second worker claim it and race the
        first.

        The dedupe key itself is untouched, so nothing else can enqueue a
        twin while this one waits.
        """
        job = self._job(job_id)

        if job.status is JobStatus.RUNNING:
            raise JobNotRetryableError(job_id, "it is running")

        if job.status is JobStatus.SUCCEEDED:
            raise JobNotRetryableError(job_id, "it already succeeded")

        self._jobs.requeue(job, now=datetime.now(UTC))
        self._record(actor, AdminAction.JOB_RETRIED, job, {})

        return job

    def cancel_job(self, actor: StaffActor, job_id: uuid.UUID) -> Job:
        """Stop a job that has not started.

        Running is refused for the same reason a retry is: the worker
        holding it does not check back, so marking the row cancelled
        would be a lie about what is happening in another process.
        """
        job = self._job(job_id)

        if job.status is JobStatus.RUNNING:
            raise JobNotRetryableError(job_id, "it is running")

        if job.status is not JobStatus.PENDING:
            raise JobNotRetryableError(job_id, "it is not waiting to run")

        self._jobs.cancel(job, now=datetime.now(UTC))
        self._record(actor, AdminAction.JOB_CANCELLED, job, {})

        return job

    # --- the refusals ------------------------------------------------------

    def webhook_failures(
        self,
        actor: StaffActor,
        *,
        provider: str | None = None,
        reason: WebhookRefusal | None = None,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[WebhookFailure], int]:
        """Deliveries this application turned away.

        The screen that turns "our orders stopped arriving" from a
        mystery into a mistyped secret. Nothing here holds a body: a
        delivery that failed to verify came from somebody unproven.
        """
        found = self._failures.list_recent(
            limit=page_size,
            offset=(page - 1) * page_size,
            provider=provider,
            reason=reason,
            since=since,
        )
        total = self._failures.count_recent(
            provider=provider,
            reason=reason,
            since=since,
        )

        self._admin_audit.did(
            actor.logged,
            AdminAction.WEBHOOK_FAILURES_READ,
            meta={"provider": provider, "results": total},
        )
        self._session.commit()

        return found, total

    def whatsapp_numbers(
        self,
        actor: StaffActor,
    ) -> list[tuple[WhatsAppAccount, Workspace]]:
        """Every connected number, and whose it is.

        Health as the account row records it -- connected, or not any
        more -- rather than by asking Meta about each number in turn. A
        page whose cost is one API call per customer is a page that times
        out on the day it is most needed.
        """
        listed = self._whatsapp.list_with_workspaces()

        self._admin_audit.did(
            actor.logged,
            AdminAction.WHATSAPP_HEALTH_READ,
            meta={"numbers": len(listed)},
        )
        self._session.commit()

        return listed

    # --- is anything wrong -------------------------------------------------

    def health(self, actor: StaffActor) -> PlatformHealth:
        """What this process can tell about the platform from where it sits.

        The queue is measured; the database is asked; the integrations
        are *not dialled*. That last one is a deliberate stop: a health
        page that called Meta, Stripe and two storefronts on every load
        would be slow, would be rate limited by somebody else's API, and
        would report an outage every time one of them had a slow minute.
        What it says instead is whether each is configured, which is the
        failure this actually catches -- a deployment missing a key does
        not fail loudly, it fails at the first customer who needs it.
        """
        now = datetime.now(UTC)
        settings = get_settings()

        health = PlatformHealth(
            database=self._database_answers(),
            queue=QueueHealth(
                depth=self._jobs.depth(now=now),
                oldest_pending_seconds=self._jobs.oldest_pending_age(now=now),
                running=self._jobs.count_matching(status=JobStatus.RUNNING),
                failed=self._jobs.count_matching(status=JobStatus.FAILED),
            ),
            integrations={
                "whatsapp": settings.whatsapp_app_secret is not None,
                "billing": settings.stripe_api_key is not None,
                "embeddings": settings.voyage_api_key is not None,
                "assistant": settings.anthropic_api_key is not None,
                "email": settings.smtp_host is not None,
                "encryption": settings.encryption_key is not None,
            },
        )

        self._admin_audit.did(
            actor.logged,
            AdminAction.HEALTH_READ,
            meta={"queue_depth": health.queue.depth},
        )
        self._session.commit()

        return health

    def _database_answers(self) -> bool:
        """Whether this process can still reach the database.

        Always true by the time anybody reads it -- the request that
        asked came through the same session -- and asked anyway, because
        a pool that has gone stale answers here rather than on a
        customer's next request.
        """
        try:
            self._session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return False

        return True

    # --- shared ------------------------------------------------------------

    def _job(self, job_id: uuid.UUID) -> Job:
        job = self._jobs.get(job_id)

        if job is None:
            raise JobNotFoundError(job_id)

        return job

    def _record(
        self,
        actor: StaffActor,
        action: AdminAction,
        job: Job,
        meta: dict[str, object],
    ) -> None:
        """Record what was done to a job, naming its workspace where it has one.

        Half of these rows name none, and that is not a gap: the
        recurring sweeps belong to the platform rather than to any
        customer, which is exactly why the admin log's workspace
        reference is nullable.
        """
        self._admin_audit.did(
            actor.logged,
            action,
            workspace_id=job.workspace_id,
            meta={"job_id": str(job.id), "kind": job.kind.value, **meta},
        )
        self._session.commit()


def get_admin_operations_service(
    session: SessionDep,
    jobs: JobRepositoryDep,
    failures: WebhookFailureRepositoryDep,
    whatsapp: WhatsAppAccountRepositoryDep,
    admin_audit: AdminAuditServiceDep,
) -> AdminOperationsService:
    return AdminOperationsService(
        session=session,
        jobs=jobs,
        failures=failures,
        whatsapp=whatsapp,
        admin_audit=admin_audit,
    )


AdminOperationsServiceDep = Annotated[
    AdminOperationsService,
    Depends(get_admin_operations_service),
]
