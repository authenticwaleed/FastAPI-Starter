import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditEvent, AuditLog
from app.models.user import User


class AuditLogRepository:
    """Every query against the audit log lives here.

    Two of them, and that is the design rather than an early draft: this
    class can append a row and it can read rows back. There is no update
    and no delete, in the repository or anywhere above it, which is what
    "append-only from the application's perspective" means in practice --
    not a rule somebody has to remember, but a method that does not exist
    to be called.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        workspace_id: uuid.UUID,
        event: AuditEvent,
        actor_user_id: int | None,
        meta: dict[str, Any],
    ) -> AuditLog:
        """Append one entry.

        Flushed and not committed, like a notification and for the same
        reason: the entry belongs in the same transaction as the act it
        records. Committed separately it could describe a role change
        that was rolled back, or be missing for one that was not -- and
        an audit log that disagrees with the system it audits is worse
        than none, because somebody will believe it.
        """
        entry = AuditLog(
            workspace_id=workspace_id,
            event=event,
            actor_user_id=actor_user_id,
            actor_email=self._email_of(actor_user_id),
            meta=meta,
        )

        self._session.add(entry)
        self._session.flush()

        return entry

    def _email_of(self, actor_user_id: int | None) -> str | None:
        """Who this account is, right now, to be written down.

        `Session.get` rather than a select, because the actor is almost
        always the person whose request this is -- and the authentication
        dependency has already loaded them, so this usually resolves in
        the identity map without touching the database at all.
        """
        if actor_user_id is None:
            return None

        user = self._session.get(User, actor_user_id)

        return user.email if user else None

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        event: AuditEvent | None = None,
        actor_user_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[tuple[AuditLog, User | None]]:
        """This workspace's history, newest first, with whoever did it.

        An outer join, because an entry with no actor is not an entry with
        no meaning: a subscription that changed because the payment
        provider said so is exactly the kind of thing somebody is looking
        for, and an inner join would hide it.

        One join rather than a lookup per row. An audit log is the one
        table in this application that only ever grows, so a query per
        entry is a page that gets slower every month it exists.
        """
        rows = self._session.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*self._filters(workspace_id, event, actor_user_id, since, until))
            # By the sequence, which is the only ordering that holds. Two
            # entries written in one transaction share a created_at to the
            # microsecond.
            .order_by(AuditLog.sequence.desc())
            .limit(limit)
            .offset(offset)
        ).all()

        return [(entry, user) for entry, user in rows]

    def count_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        event: AuditEvent | None = None,
        actor_user_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(*self._filters(workspace_id, event, actor_user_id, since, until))
            )
            or 0
        )

    def _filters(
        self,
        workspace_id: uuid.UUID,
        event: AuditEvent | None,
        actor_user_id: int | None,
        since: datetime | None,
        until: datetime | None,
    ) -> list[ColumnElement[bool]]:
        """The same narrowing for the page and its total.

        Built once rather than written twice, because a count that filters
        differently from the list it counts is a pager that runs out of
        pages early and nobody notices until a customer does.
        """
        where: list[ColumnElement[bool]] = [AuditLog.workspace_id == workspace_id]

        if event is not None:
            where.append(AuditLog.event == event)

        if actor_user_id is not None:
            where.append(AuditLog.actor_user_id == actor_user_id)

        if since is not None:
            where.append(AuditLog.created_at >= since)

        if until is not None:
            # Exclusive, like every other period in this application, so
            # that consecutive ranges neither overlap nor leave a gap.
            where.append(AuditLog.created_at < until)

        return where
