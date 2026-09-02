"""Recording what the people who run this platform did.

The second of two audit logs, and the reasons it is separate are in
`app/models/admin_audit_log.py`. What this module adds is the same
discipline the tenant one keeps: an entry is written by whoever caused
it, in that caller's transaction, and nothing here can edit or remove
one.

Like `app/services/audit_service.py`, nothing in this file takes the
access object a route resolved. It speaks in ids and strings, which is
all an entry is made of -- and which is what stops the service every
writer imports from importing the service that resolves them.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.user import User
from app.repositories.admin_audit_log_repository import AdminAuditLogRepository


@dataclass(frozen=True)
class AdminActor:
    """Whoever is acting, reduced to what the log has to freeze.

    Ids and strings rather than the loaded rows, for this module's own
    reason above, and one property of the reduction is load-bearing: the
    address is copied as it is now, so the entry still names somebody
    after the account behind it is deleted.

    Every field is optional because one caller has none of them. The
    first staff owner is granted from the command line, before anybody
    exists who could grant it, and an entry claiming a person did that
    would be an accusation rather than a gap.
    """

    user_id: int | None = None
    email: str | None = None
    # Best effort, and neither decides anything: a header anyone can set,
    # and an address a proxy may have rewritten. They are here because
    # the question asked after an incident is "was that really them".
    ip_address: str | None = None
    user_agent: str | None = None


class AdminAuditService:
    """Writing the platform's record, and reading it back.

    Writing is done by whichever service the act happened in, inside that
    service's transaction, so this side only flushes -- an entry
    committed apart from the act it describes can outlive a rollback.

    Reading is the exception that this surface makes and the tenant one
    does not: a read here is itself an act, so `list_entries` records
    that somebody read the log and owns the commit for that row. The
    entry is written after the page has been queried, so a reader is not
    handed their own arrival at the top of it.
    """

    def __init__(self, session: Session, logs: AdminAuditLogRepository) -> None:
        self._session = session
        self._logs = logs

    # --- writing -----------------------------------------------------------

    def did(
        self,
        actor: AdminActor,
        action: AdminAction,
        *,
        workspace_id: uuid.UUID | None = None,
        workspace_slug: str | None = None,
        target_user_id: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AdminAuditLog:
        """Record that a staff member did this.

        Called before the caller commits, so that the act and the record
        of it are one write. A workspace is named by both its id and its
        slug wherever one is involved: the id is nulled when the
        workspace is erased, and the slug is what still says whose
        account the entry was about.
        """
        return self._logs.record(
            actor_user_id=actor.user_id,
            actor_email=actor.email,
            action=action,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            target_user_id=target_user_id,
            meta=meta or {},
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
        )

    # --- reading -----------------------------------------------------------

    def list_entries(
        self,
        actor: AdminActor,
        *,
        page: int = 1,
        page_size: int = 50,
        action: AdminAction | None = None,
        actor_user_id: int | None = None,
        workspace_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[tuple[AdminAuditLog, User | None]], int]:
        """A page of the platform's history, newest first, with a total.

        Filtered on the way in, because the questions worth asking are
        narrow -- what did this colleague do, what was done to this
        business, what happened that afternoon -- and this table only
        ever grows.
        """
        entries = self._logs.list_entries(
            limit=page_size,
            offset=(page - 1) * page_size,
            action=action,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            since=since,
            until=until,
        )
        total = self._logs.count_entries(
            action=action,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            since=since,
            until=until,
        )

        # After the query, so the reader is not shown their own read at
        # the top of the page they asked for. It will be there on the
        # next one, which is where it belongs.
        self.did(
            actor,
            AdminAction.AUDIT_READ,
            meta=_asked(
                page=page,
                page_size=page_size,
                action=action,
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
            ),
        )
        self._session.commit()

        return entries, total


def _asked(
    *,
    page: int,
    page_size: int,
    action: AdminAction | None,
    actor_user_id: int | None,
    workspace_id: uuid.UUID | None,
) -> dict[str, Any]:
    """What was looked for, which is the useful half of a read entry.

    "Somebody read the log" is not worth a row on its own. What they
    narrowed it to is: a colleague reading every entry about one
    workspace, or about one other colleague, is the thing an
    investigation follows, and the page number alone would not show it.
    """
    return {
        "page": page,
        "page_size": page_size,
        "action": action.value if action else None,
        "actor_user_id": actor_user_id,
        "workspace_id": str(workspace_id) if workspace_id else None,
    }


def get_admin_audit_log_repository(session: SessionDep) -> AdminAuditLogRepository:
    return AdminAuditLogRepository(session)


AdminAuditLogRepositoryDep = Annotated[
    AdminAuditLogRepository,
    Depends(get_admin_audit_log_repository),
]


def get_admin_audit_service(
    session: SessionDep,
    logs: AdminAuditLogRepositoryDep,
) -> AdminAuditService:
    return AdminAuditService(session=session, logs=logs)


AdminAuditServiceDep = Annotated[
    AdminAuditService,
    Depends(get_admin_audit_service),
]
