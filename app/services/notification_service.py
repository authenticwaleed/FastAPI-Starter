import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotificationNotFoundError
from app.db.session import SessionDep
from app.models.notification import Notification, NotificationKind
from app.models.user import User
from app.models.workspace_membership import WorkspaceRole
from app.repositories.notification_repository import NotificationRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.workspace_service import WorkspaceMembershipRepositoryDep

# The kinds that are about a condition rather than an event, and so must
# not pile up. An integration is not more broken for having failed twice,
# and a second unread alert saying so is noise on top of a problem.
_ALERTS = frozenset(
    {
        NotificationKind.KNOWLEDGE_INGESTION_FAILED,
        NotificationKind.MESSAGE_DELIVERY_FAILED,
    }
)


class NotificationService:
    """Telling people things, and letting them mark them read.

    Two halves that barely touch. Reading is a person's own feed, across
    every business they work in, which is why the endpoints have no
    workspace in their path. Writing is done by other services, in the
    transaction where the thing actually happened -- so this side only
    flushes, and whoever caused the notification owns the commit.

    That is not a detail. A notification committed separately from the
    thing it describes is a notification that can exist for an assignment
    that was rolled back, or be missing for one that was not.
    """

    def __init__(
        self,
        session: Session,
        notifications: NotificationRepository,
        memberships: WorkspaceMembershipRepository,
    ) -> None:
        self._session = session
        self._notifications = notifications
        self._memberships = memberships

    # --- writing -----------------------------------------------------------

    def tell(
        self,
        *,
        user_id: int,
        workspace_id: uuid.UUID,
        kind: NotificationKind,
        title: str,
        body: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Notification | None:
        """Tell one person one thing.

        Returns None when there was nothing new to say -- an alert of a
        kind they already have unread. Not an error: the caller asked for
        somebody to be informed, and somebody already is.
        """
        try:
            with self._session.begin_nested():
                return self._notifications.create(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    kind=kind,
                    title=title,
                    body=body,
                    dedupe_key=kind.value if kind in _ALERTS else None,
                    meta=meta,
                )
        except IntegrityError:
            # The partial unique index refused a second unread alert of
            # this kind. Nested so that the refusal rolls back this insert
            # and nothing else: the caller is in the middle of its own
            # transaction, and a failed notification must not take a
            # delivered message down with it.
            return None

    def tell_everyone(
        self,
        *,
        workspace_id: uuid.UUID,
        roles: frozenset[WorkspaceRole],
        kind: NotificationKind,
        title: str,
        body: str | None = None,
        meta: dict[str, Any] | None = None,
        except_user_id: int | None = None,
    ) -> list[Notification]:
        """Tell everybody in a workspace who holds one of these roles.

        One row each, because read state is per person. `except_user_id`
        is for the case that comes up constantly: somebody who did the
        thing does not need telling that they did it.
        """
        told = []

        for membership in self._memberships.list_for_workspace(workspace_id):
            if membership.role not in roles or membership.user_id == except_user_id:
                continue

            notification = self.tell(
                user_id=membership.user_id,
                workspace_id=workspace_id,
                kind=kind,
                title=title,
                body=body,
                meta=meta,
            )

            if notification is not None:
                told.append(notification)

        return told

    # --- reading -----------------------------------------------------------

    def list_for(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        unread_only: bool = False,
        workspace_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Notification], int]:
        notifications = self._notifications.list_for_user(
            user.id,
            limit=page_size,
            offset=(page - 1) * page_size,
            unread_only=unread_only,
            workspace_id=workspace_id,
        )
        total = self._notifications.count_for_user(
            user.id,
            unread_only=unread_only,
            workspace_id=workspace_id,
        )

        return notifications, total

    def unread_count(
        self,
        user: User,
        *,
        workspace_id: uuid.UUID | None = None,
    ) -> int:
        return self._notifications.count_for_user(
            user.id,
            unread_only=True,
            workspace_id=workspace_id,
        )

    def mark_read(self, user: User, notification_id: uuid.UUID) -> Notification:
        notification = self._notifications.get(user.id, notification_id)

        if notification is None:
            raise NotificationNotFoundError(user.id, notification_id)

        self._notifications.mark_read(notification, datetime.now(UTC))
        self._session.commit()

        return notification

    def mark_all_read(
        self,
        user: User,
        *,
        workspace_id: uuid.UUID | None = None,
    ) -> int:
        cleared = self._notifications.mark_all_read(
            user.id,
            datetime.now(UTC),
            workspace_id=workspace_id,
        )
        self._session.commit()

        return cleared


def get_notification_repository(session: SessionDep) -> NotificationRepository:
    return NotificationRepository(session)


NotificationRepositoryDep = Annotated[
    NotificationRepository,
    Depends(get_notification_repository),
]


def get_notification_service(
    session: SessionDep,
    notifications: NotificationRepositoryDep,
    memberships: WorkspaceMembershipRepositoryDep,
) -> NotificationService:
    return NotificationService(
        session=session,
        notifications=notifications,
        memberships=memberships,
    )


NotificationServiceDep = Annotated[
    NotificationService,
    Depends(get_notification_service),
]
