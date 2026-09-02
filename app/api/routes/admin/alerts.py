from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, EmailStr

from app.api.dependencies.staff import StaffAdminDep
from app.api.errors import ADMIN_FORBIDDEN, ADMIN_UNAUTHORISED, RATE_LIMITED
from app.core.config import get_settings
from app.models.admin_audit_log import AdminAction
from app.services.admin_audit_service import (
    AdminAuditLogRepositoryDep,
    AdminAuditServiceDep,
)

router = APIRouter(prefix="/alerts", tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}

# What counts as reading a customer's account. Not every admin action:
# searching the workspace list touches every business by definition, and
# counting it would put whoever opened the console at the top of this
# page every time.
READING_A_CUSTOMER = (
    AdminAction.WORKSPACE_READ,
    AdminAction.WORKSPACE_MEMBERS_READ,
    AdminAction.WORKSPACE_AUDIT_READ,
    AdminAction.CONVERSATIONS_READ,
    AdminAction.MESSAGES_READ,
)


class BusyReader(BaseModel):
    """One staff member, and how many customers they opened.

    Distinct workspaces rather than requests: somebody refreshing one
    account's page forty times is working, and somebody opening forty
    accounts is either running a migration or going through the customer
    list. Only the second is a question.
    """

    user_id: int | None
    email: EmailStr | None
    workspaces_read: int


class AdminAlerts(BaseModel):
    """Patterns worth a person looking at, not refusals.

    Nothing on this page stops anybody doing anything, and that is the
    design rather than a limitation. The two patterns the plan names --
    support access outside working hours, and one staff member reading
    many accounts quickly -- are both perfectly ordinary during an
    incident and both worth noticing afterwards. A control that refused
    them would be worked around within a week by whoever was on call.

    The out-of-hours half is not here: it is a warning line written when
    the grant is asked for, in the stream operations already watches,
    because it is an event rather than a state and there is nothing to
    poll for.
    """

    hours: int
    threshold: int
    busiest_readers: list[BusyReader]
    over_threshold: list[BusyReader]


@router.get("", responses=PLATFORM)
def read_alerts(
    actor: StaffAdminDep,
    logs: AdminAuditLogRepositoryDep,
    audit: AdminAuditServiceDep,
    hours: Annotated[int, Query(ge=1, le=168)] = 1,
) -> AdminAlerts:
    """Who has been reading a lot of customers' accounts lately.

    Built from the platform's own audit log rather than from a second
    tally, which is the reason auditing reads was worth its cost: the
    same rows that answer "who looked at this workspace" answer "who has
    been looking at everybody's".

    The threshold is configuration and the answer is a list rather than
    an alarm. Twenty accounts in an hour is a migration or a person
    working through a queue about as often as it is anything else, and
    the useful output is a name and a number that somebody can ask about.
    """
    settings = get_settings()
    since = datetime.now(UTC) - timedelta(hours=hours)
    readers = [
        BusyReader(user_id=user_id, email=email, workspaces_read=count)
        for user_id, email, count in logs.busiest_readers(
            since=since,
            actions=READING_A_CUSTOMER,
        )
    ]

    audit.did(actor.logged, AdminAction.ALERTS_READ, meta={"hours": hours})

    return AdminAlerts(
        hours=hours,
        threshold=settings.admin_workspace_reads_per_hour,
        busiest_readers=readers[:20],
        over_threshold=[
            reader
            for reader in readers
            if reader.workspaces_read > settings.admin_workspace_reads_per_hour * hours
        ],
    )
