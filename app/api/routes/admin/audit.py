import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.staff import StaffAdminDep
from app.api.errors import ADMIN_FORBIDDEN, ADMIN_UNAUTHORISED, RATE_LIMITED
from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.user import User
from app.schemas.admin_audit import (
    AdminAuditActor,
    AdminAuditEntry,
    AdminAuditPage,
    AdminAuditSubject,
)
from app.services.admin_audit_service import AdminAuditServiceDep

router = APIRouter(prefix="/audit", tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}


# Read-only, and there is no other verb on this path at any rank. An
# append-only log is not a rule somebody remembers to keep; it is a route
# that does not exist to be called, and a repository with no method
# behind it if one ever were.
@router.get("", responses=PLATFORM)
def list_admin_audit_logs(
    actor: StaffAdminDep,
    service: AdminAuditServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    action: Annotated[AdminAction | None, Query()] = None,
    actor_user_id: Annotated[int | None, Query()] = None,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> AdminAuditPage:
    """What staff have done, newest first.

    Filtered on the way in, because the questions worth asking are narrow
    -- what did this colleague do, what was done to this business, what
    happened that afternoon -- and this is a table that only ever grows.

    Reading it is itself recorded, which is the rule this whole surface
    is built on and applies to the log as readily as to anything else.
    The entry is written after this page is queried, so nobody is handed
    their own arrival at the top of what they asked for.

    `until` is exclusive, like every other period here, so that two
    consecutive ranges neither overlap nor leave a gap.
    """
    entries, total = service.list_entries(
        actor.logged,
        page=page,
        page_size=page_size,
        action=action,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        since=since,
        until=until,
    )

    return AdminAuditPage(
        items=[_entry(entry, user) for entry, user in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


def _entry(entry: AdminAuditLog, user: User | None) -> AdminAuditEntry:
    return AdminAuditEntry(
        id=entry.id,
        action=entry.action,
        actor=_actor(entry, user),
        subject=_subject(entry),
        target_user_id=entry.target_user_id,
        metadata=entry.meta,
        ip_address=entry.ip_address,
        user_agent=entry.user_agent,
        created_at=entry.created_at,
    )


def _actor(entry: AdminAuditLog, user: User | None) -> AdminAuditActor | None:
    """Whoever did it, as much as is still known.

    Three states, and they are three different facts.

    Nobody did it: the first owner, granted from a command line before
    anybody existed who could grant it. Both columns are null, so the
    whole actor is.

    Somebody did and is still here: their name from the joined row, which
    is current rather than copied, so a colleague who has changed their
    name reads as the person they are.

    Somebody did and their account is gone. The foreign key nulled the id
    when the row went; the address written down at the time did not go
    with it, which is the difference between this log and a record a
    staff member could erase themselves from by closing their account.
    """
    if entry.actor_user_id is None and entry.actor_email is None:
        return None

    return AdminAuditActor(
        user_id=entry.actor_user_id,
        name=user.name if user else None,
        email=user.email if user else entry.actor_email,
    )


def _subject(entry: AdminAuditLog) -> AdminAuditSubject | None:
    """Which business this was about, where it was about one.

    Absent for the acts that are about the platform itself -- granting a
    colleague access belongs to no workspace -- and present with a null
    id and a readable slug once the workspace has been erased. That
    second state is the reason this table exists.
    """
    if entry.workspace_id is None and entry.workspace_slug is None:
        return None

    return AdminAuditSubject(
        workspace_id=entry.workspace_id,
        workspace_slug=entry.workspace_slug,
    )
