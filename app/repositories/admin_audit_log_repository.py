import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.user import User


class AdminAuditLogRepository:
    """Every query against the admin audit log lives here.

    Two of them, like the tenant log's repository, and for the same
    reason: this class can append a row and it can read rows back. There
    is no update and no delete, at any role, anywhere above it. That is
    what "append-only" means in practice -- not a rule somebody has to
    remember, but a method that does not exist to be called.

    The stakes are higher here than on the tenant side. A business's own
    log is evidence for that business; this one is the record of what the
    people who can reach every business did, and the first thing anybody
    with something to hide would want is a way to edit it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        actor_user_id: int | None,
        actor_email: str | None,
        action: AdminAction,
        workspace_id: uuid.UUID | None = None,
        workspace_slug: str | None = None,
        target_user_id: int | None = None,
        meta: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AdminAuditLog:
        """Append one entry.

        Flushed and not committed, like every other write in this
        application that belongs to somebody else's transaction. An entry
        committed separately could describe a grant that was rolled back,
        and a log that disagrees with the system it audits is worse than
        no log, because somebody will believe it.

        The actor's address is passed in rather than looked up. It is the
        address as it was at the moment they acted, which is what has to
        be frozen here -- and the caller is a dependency that has already
        loaded the account, so there is nothing to fetch.
        """
        entry = AdminAuditLog(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            action=action,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            target_user_id=target_user_id,
            meta=meta or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self._session.add(entry)
        self._session.flush()

        return entry

    def list_entries(
        self,
        *,
        limit: int,
        offset: int,
        action: AdminAction | None = None,
        actor_user_id: int | None = None,
        workspace_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[tuple[AdminAuditLog, User | None]]:
        """A page of what staff did, newest first, with whoever did it.

        An outer join, because an entry with no actor is a real entry
        rather than a broken one: the first owner was granted before
        anybody existed to grant it, and a staff member whose account has
        since been deleted leaves rows that still name them by address.
        An inner join would hide both.
        """
        rows = self._session.execute(
            select(AdminAuditLog, User)
            .outerjoin(User, User.id == AdminAuditLog.actor_user_id)
            .where(*self._filters(action, actor_user_id, workspace_id, since, until))
            # By the sequence, which is the only ordering that holds: two
            # entries written in one transaction share a created_at to
            # the microsecond.
            .order_by(AdminAuditLog.sequence.desc())
            .limit(limit)
            .offset(offset)
        ).all()

        return [(entry, user) for entry, user in rows]

    def count_entries(
        self,
        *,
        action: AdminAction | None = None,
        actor_user_id: int | None = None,
        workspace_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(
                    *self._filters(action, actor_user_id, workspace_id, since, until)
                )
            )
            or 0
        )

    def _filters(
        self,
        action: AdminAction | None,
        actor_user_id: int | None,
        workspace_id: uuid.UUID | None,
        since: datetime | None,
        until: datetime | None,
    ) -> list[ColumnElement[bool]]:
        """The same narrowing for the page and its total.

        Built once rather than written twice, because a count that
        filters differently from the list it counts is a pager that runs
        out of pages early and nobody notices until somebody is looking
        for one particular afternoon.
        """
        where: list[ColumnElement[bool]] = []

        if action is not None:
            where.append(AdminAuditLog.action == action)

        if actor_user_id is not None:
            where.append(AdminAuditLog.actor_user_id == actor_user_id)

        if workspace_id is not None:
            where.append(AdminAuditLog.workspace_id == workspace_id)

        if since is not None:
            where.append(AdminAuditLog.created_at >= since)

        if until is not None:
            # Exclusive, like every other period in this application, so
            # that consecutive ranges neither overlap nor leave a gap.
            where.append(AdminAuditLog.created_at < until)

        return where
