import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationKind
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
)


class NotificationRepository:
    """Every query against the notifications table lives here.

    Every read is scoped to the recipient *and* to the workspaces they
    are still a member of. The second half is not belt and braces: a
    notification outlives the membership that justified it, and somebody
    removed from a business should stop seeing that business's activity
    the moment they are removed rather than keep a feed of it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: int,
        workspace_id: uuid.UUID,
        kind: NotificationKind,
        title: str,
        body: str | None = None,
        dedupe_key: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            workspace_id=workspace_id,
            kind=kind,
            title=title,
            body=body,
            dedupe_key=dedupe_key,
            meta=meta or {},
        )

        self._session.add(notification)
        self._session.flush()

        return notification

    def get(self, user_id: int, notification_id: uuid.UUID) -> Notification | None:
        """Scoped by recipient, not looked up by id alone.

        An id is a guess anybody can make; requiring it to be addressed to
        the caller is what stops one person marking another's read.
        """
        return self._session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )

    def list_for_user(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int,
        unread_only: bool = False,
        workspace_id: uuid.UUID | None = None,
    ) -> Sequence[Notification]:
        return self._session.scalars(
            self._visible(
                select(Notification),
                user_id,
                unread_only=unread_only,
                workspace_id=workspace_id,
            )
            .order_by(Notification.created_at.desc(), Notification.sequence.desc())
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        workspace_id: uuid.UUID | None = None,
    ) -> int:
        return (
            self._session.scalar(
                self._visible(
                    select(func.count()).select_from(Notification),
                    user_id,
                    unread_only=unread_only,
                    workspace_id=workspace_id,
                )
            )
            or 0
        )

    def mark_read(self, notification: Notification, at: datetime) -> Notification:
        if notification.read_at is None:
            # Only the first time. Marking it again would move the
            # timestamp, and "when did they see this" would stop being
            # true the moment somebody clicked twice.
            notification.read_at = at
            self._session.flush()

        return notification

    def mark_all_read(
        self,
        user_id: int,
        at: datetime,
        *,
        workspace_id: uuid.UUID | None = None,
    ) -> int:
        """Clear the badge, and say how many it cleared.

        A bulk UPDATE rather than a loop, because this is the one
        operation here that touches an unbounded number of rows -- and
        unlike the session revocation in Phase 15, nothing is holding
        these in memory afterwards, so there is no stale copy to worry
        about.
        """
        targets = self._visible(
            select(Notification.id),
            user_id,
            unread_only=True,
            workspace_id=workspace_id,
        )

        cleared = self._session.scalars(
            update(Notification)
            .where(Notification.id.in_(targets))
            .values(read_at=at)
            .returning(Notification.id)
            .execution_options(synchronize_session=False)
        ).all()
        self._session.flush()

        return len(cleared)

    def _visible(
        self,
        statement: Select[Any],
        user_id: int,
        *,
        unread_only: bool,
        workspace_id: uuid.UUID | None,
    ) -> Select[Any]:
        """This person's notifications, from the businesses they are in.

        The membership check is the whole reason this helper exists: it
        has to be on the list, the count and the bulk read, and a version
        of any one of them that forgot it would show somebody the inside
        of a workspace they had been removed from.
        """
        member_of = select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == Notification.workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == MembershipStatus.ACTIVE,
        )

        statement = statement.where(
            Notification.user_id == user_id,
            member_of.exists(),
        )

        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))

        if workspace_id is not None:
            statement = statement.where(Notification.workspace_id == workspace_id)

        return statement
