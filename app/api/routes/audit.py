from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.plan import REQUIRES_AUDIT_LOGS
from app.api.dependencies.workspace import WorkspaceAdminDep
from app.api.errors import (
    PLAN_REQUIRED,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.audit_log import AuditEvent, AuditLog
from app.models.user import User
from app.schemas.audit import AuditActor, AuditEntry, AuditPage
from app.services.audit_service import AuditServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/audit-logs",
    tags=["audit"],
)


# Administrators only, and on a plan that includes it. Both are declared
# rather than checked in the body: an audit log is a list of what every
# colleague has done, which is administration by definition, and a route
# added beside this one without the same two lines would look exactly
# like a route that is deliberately open.
@router.get(
    "",
    responses={
        **UNAUTHORISED,
        **WORKSPACE_FORBIDDEN,
        **WORKSPACE_NOT_FOUND,
        **PLAN_REQUIRED,
    },
    dependencies=[REQUIRES_AUDIT_LOGS],
)
def list_audit_logs(
    access: WorkspaceAdminDep,
    service: AuditServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    event: Annotated[AuditEvent | None, Query()] = None,
    actor_user_id: Annotated[int | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> AuditPage:
    """What has been done to this workspace, newest first.

    Filtered on the way in. The questions worth asking an audit log are
    narrow -- what did this account do, what happened to the knowledge
    base last month -- and this is the one table in the application that
    only ever grows, so paging through all of it to find one act is not a
    workable answer.

    `until` is exclusive, like every other period here, so that two
    consecutive ranges neither overlap nor leave a gap.
    """
    entries, total = service.list_for(
        access.workspace.id,
        page=page,
        page_size=page_size,
        event=event,
        actor_user_id=actor_user_id,
        since=since,
        until=until,
    )

    return AuditPage(
        items=[entry_of(log, user) for log, user in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


def entry_of(entry: AuditLog, user: User | None) -> AuditEntry:
    """One row of a workspace's history, as the API renders it.

    Public, and shared with the platform console, which serves this same
    log to support. Two renderers would eventually be two shapes, and the
    entry a support engineer reads back to a customer has to be the entry
    that customer can see for themselves.
    """
    return AuditEntry(
        id=entry.id,
        event=entry.event,
        actor=_actor(entry, user),
        metadata=entry.meta,
        created_at=entry.created_at,
    )


def _actor(entry: AuditLog, user: User | None) -> AuditActor | None:
    """Whoever did it, as much as is still known.

    Three states, and they are three different facts.

    Nobody did it -- a payment provider changed a subscription -- and both
    columns are null, so the whole actor is.

    Somebody did and is still here: their name from the joined row, which
    is current rather than copied, so a colleague who has since changed
    their name reads as the person they are.

    Somebody did and their account is gone. The foreign key nulled the id
    when the row went, but the address written down at the time did not
    go with it -- which is the difference between an audit log and a
    record an administrator can erase themselves from.
    """
    if entry.actor_user_id is None and entry.actor_email is None:
        return None

    return AuditActor(
        user_id=entry.actor_user_id,
        name=user.name if user else None,
        email=user.email if user else entry.actor_email,
    )
