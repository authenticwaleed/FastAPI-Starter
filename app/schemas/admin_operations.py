from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.job import JobKind, JobStatus
from app.models.webhook_failure import WebhookRefusal
from app.models.whatsapp_account import (
    MessagingProviderName,
    WhatsAppAccountStatus,
)


class AdminJobSummary(BaseModel):
    """One job, as a row in the queue.

    No payload on the summary, and not only to keep the response small:
    a list is the screen somebody leaves open, and the payload is the
    part that is redacted by kind. Fetching one job to see it is a
    deliberate act and gets its own audit entry.
    """

    id: UUID
    kind: JobKind
    status: JobStatus
    workspace_id: UUID | None
    attempts: int
    max_attempts: int
    run_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Truncated at the column, and it is the field the whole screen is
    # for: "their message never arrived" becomes a row with a reason.
    last_error: str | None
    created_at: datetime


class AdminJobPage(BaseModel):
    items: list[AdminJobSummary]
    total: int
    page: int
    page_size: int


class AdminJobDetail(AdminJobSummary):
    """One job, with as much of its payload as its kind admits.

    Redacted by kind on a safe-list: a field nobody has named for this
    kind comes back as `[redacted]` rather than being dropped, so a
    reader can tell "there is something here I am not being shown" from
    "there is nothing here".
    """

    payload: dict[str, Any]
    # Left on the detail rather than the summary because it is
    # operational trivia most of the time and the answer exactly once:
    # when two jobs look like duplicates and one of them is not.
    dedupe_key: str | None


class AdminWebhookFailure(BaseModel):
    """One delivery that was turned away.

    No body, ever. A delivery that failed to verify came from somebody
    unproven, so what is kept is enough to recognise a pattern -- which
    endpoint, which reason, from where -- and nothing they chose to send.
    """

    id: UUID
    provider: str
    reason: WebhookRefusal
    path: str
    ip_address: str | None
    received_at: datetime


class AdminWebhookFailurePage(BaseModel):
    items: list[AdminWebhookFailure]
    total: int
    page: int
    page_size: int


class AdminWhatsAppNumber(BaseModel):
    """One connected number, and whose it is.

    The workspace is here because a broken number without an account
    beside it is a phone number nobody can act on. No token, for the
    reason nothing on this surface carries one.
    """

    workspace_id: UUID
    workspace_slug: str
    provider: MessagingProviderName
    phone_number: str
    external_phone_number_id: str
    status: WhatsAppAccountStatus
    connected_at: datetime


class AdminQueueHealth(BaseModel):
    """The two numbers that say whether the worker has stopped.

    Depth alone cannot tell a busy afternoon from a dead worker. Two
    hundred draining in a minute is fine; three where the oldest has
    waited an hour is not, and the count looks the same in both.

    `oldest_pending_seconds` is null when nothing is due, which is not
    zero -- zero would read as "something is waiting and it just
    arrived".
    """

    depth: int
    oldest_pending_seconds: float | None
    running: int
    failed: int


class AdminHealth(BaseModel):
    """What this process can tell about the platform from where it sits.

    `integrations` says whether each is *configured*, not whether it is
    reachable. Dialling them on every load would be slow, rate limited by
    somebody else's API, and would report an outage every time one had a
    slow minute -- while the failure this actually catches is a
    deployment missing a key, which otherwise surfaces at the first
    customer who needs it.
    """

    database: bool
    queue: AdminQueueHealth
    integrations: dict[str, bool]
