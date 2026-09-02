import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.staff import StaffAdminDep
from app.api.errors import (
    ADMIN_FORBIDDEN,
    ADMIN_UNAUTHORISED,
    JOB_CONFLICT,
    JOB_NOT_FOUND,
    RATE_LIMITED,
)
from app.models.job import Job, JobKind, JobStatus
from app.models.webhook_failure import WebhookFailure, WebhookRefusal
from app.models.whatsapp_account import WhatsAppAccount
from app.models.workspace import Workspace
from app.schemas.admin_operations import (
    AdminHealth,
    AdminJobDetail,
    AdminJobPage,
    AdminJobSummary,
    AdminQueueHealth,
    AdminWebhookFailure,
    AdminWebhookFailurePage,
    AdminWhatsAppNumber,
)
from app.services.admin_operations_service import (
    AdminOperationsServiceDep,
    PlatformHealth,
    visible_payload,
)

router = APIRouter(tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}
NAMED = {**PLATFORM, **JOB_NOT_FOUND}


# `admin` throughout. Operations is not the rank that answers tickets: a
# retry re-sends somebody's message, and a cancellation stops one being
# sent at all.
@router.get("/jobs", responses=PLATFORM)
def search_jobs(
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
    kind: Annotated[JobKind | None, Query()] = None,
    status: Annotated[JobStatus | None, Query()] = None,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminJobPage:
    """The queue, across every workspace.

    `kind=deliver_message&status=failed&workspace_id=…` is the query this
    screen exists for: it turns "their message never arrived" into a row
    with an error on it, without anybody opening a database console.

    Half the rows here name no workspace, which is not a gap -- the
    recurring sweeps belong to the platform rather than to any customer.
    """
    found, total = service.search_jobs(
        actor,
        kind=kind,
        status=status,
        workspace_id=workspace_id,
        page=page,
        page_size=page_size,
    )

    return AdminJobPage(
        items=[_summary(job) for job in found],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}", responses=NAMED)
def read_job(
    job_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
) -> AdminJobDetail:
    """One job, with its attempts, its error, and as much payload as its
    kind admits.

    The payload is redacted on a safe-list rather than dumped. A job can
    carry a customer's message text, and an operations console is not a
    licence to read messages -- Phase A3 exists for when that is
    genuinely needed, with a reason and an expiry the customer can see.
    """
    return _detail(service.read_job(actor, job_id))


@router.post("/jobs/{job_id}/retry", responses={**NAMED, **JOB_CONFLICT})
def retry_job(
    job_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
) -> AdminJobDetail:
    """Put a job back in the queue, attempts forgiven.

    Refused while it is running. The worker holding that row does not
    check back, so moving it to pending would let a second worker claim
    the same work and race the first -- which is what respecting the
    dedupe key comes to in practice. The key itself is left untouched, so
    nothing can enqueue a twin while this one waits.
    """
    return _detail(service.retry_job(actor, job_id))


@router.post("/jobs/{job_id}/cancel", responses={**NAMED, **JOB_CONFLICT})
def cancel_job(
    job_id: uuid.UUID,
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
) -> AdminJobDetail:
    """Stop a job that has not started.

    Its own status rather than `failed`, because the two answer different
    questions afterwards: a failure is something to investigate, and this
    is something somebody already decided about.
    """
    return _detail(service.cancel_job(actor, job_id))


@router.get("/webhooks/failures", responses=PLATFORM)
def list_webhook_failures(
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
    provider: Annotated[str | None, Query(max_length=64)] = None,
    reason: Annotated[WebhookRefusal | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminWebhookFailurePage:
    """Deliveries this application turned away.

    The one failure in the system that otherwise reaches nobody: the
    provider is told with a status code, the sender is a machine, and the
    customer whose storefront secret was mistyped notices days later that
    their orders stopped arriving.

    Filter by reason to tell the two cases apart. A run of
    `bad_signature` from one address is somebody probing; the same reason
    from one provider, steadily, is a customer with the wrong secret.
    """
    found, total = service.webhook_failures(
        actor,
        provider=provider,
        reason=reason,
        since=since,
        page=page,
        page_size=page_size,
    )

    return AdminWebhookFailurePage(
        items=[_failure(failure) for failure in found],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/integrations/whatsapp", responses=PLATFORM)
def list_whatsapp_numbers(
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
) -> list[AdminWhatsAppNumber]:
    """Every connected number, and whose it is.

    Health as the account row records it rather than by asking Meta about
    each number in turn: a page costing one API call per customer is a
    page that times out on the day it is most needed.
    """
    return [
        _number(account, workspace)
        for account, workspace in service.whatsapp_numbers(actor)
    ]


@router.get("/health", responses=PLATFORM)
def read_platform_health(
    actor: StaffAdminDep,
    service: AdminOperationsServiceDep,
) -> AdminHealth:
    """Whether anything is wrong right now.

    Distinct from `/api/v1/health`, which answers an orchestrator and
    must stay cheap and public. This one is for a person, needs a staff
    rank, and says the two things an orchestrator has no use for: how
    deep the queue is, and how long the oldest waiting job has been
    waiting. Either alone says nothing; together they are what tells a
    busy afternoon from a worker that has stopped.
    """
    return _health(service.health(actor))


def _summary(job: Job) -> AdminJobSummary:
    return AdminJobSummary(
        id=job.id,
        kind=job.kind,
        status=job.status,
        workspace_id=job.workspace_id,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        run_at=job.run_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        last_error=job.last_error,
        created_at=job.created_at,
    )


def _detail(job: Job) -> AdminJobDetail:
    return AdminJobDetail(
        **_summary(job).model_dump(),
        # Never `job.payload`. Redacted by kind, in one function, so
        # there is exactly one place this could go wrong.
        payload=visible_payload(job),
        dedupe_key=job.dedupe_key,
    )


def _failure(failure: WebhookFailure) -> AdminWebhookFailure:
    return AdminWebhookFailure(
        id=failure.id,
        provider=failure.provider,
        reason=failure.reason,
        path=failure.path,
        ip_address=failure.ip_address,
        received_at=failure.received_at,
    )


def _number(account: WhatsAppAccount, workspace: Workspace) -> AdminWhatsAppNumber:
    return AdminWhatsAppNumber(
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        provider=account.provider,
        phone_number=account.phone_number,
        external_phone_number_id=account.external_phone_number_id,
        status=account.status,
        connected_at=account.connected_at,
    )


def _health(health: PlatformHealth) -> AdminHealth:
    return AdminHealth(
        database=health.database,
        queue=AdminQueueHealth(
            depth=health.queue.depth,
            oldest_pending_seconds=health.queue.oldest_pending_seconds,
            running=health.queue.running,
            failed=health.queue.failed,
        ),
        integrations=health.integrations,
    )
