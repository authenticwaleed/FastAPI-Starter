import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.errors import FORBIDDEN, NOTIFICATION_NOT_FOUND, UNAUTHORISED
from app.schemas.notification import (
    MarkedRead,
    NotificationPage,
    NotificationRead,
    UnreadCount,
)
from app.services.notification_service import NotificationServiceDep

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
)

AUTHENTICATED = {**UNAUTHORISED, **FORBIDDEN}


# No workspace in any of these paths, which is the plan's endpoint list
# read literally and also the right shape. A notification is addressed to
# a person, and a person opening theirs wants everything meant for them --
# from every business they work in, not one at a time. `workspace_id` is a
# filter for a client that wants to narrow it, never a requirement.
#
# What keeps the tenant boundary is the recipient plus a membership check
# on every read: somebody removed from a business stops seeing its
# activity the moment they are removed, rather than keeping a feed of it.
@router.get("", responses=AUTHENTICATED)
def list_notifications(
    user: CurrentUserDep,
    service: NotificationServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    unread_only: Annotated[bool, Query()] = False,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
) -> NotificationPage:
    """Your notifications, newest first."""
    notifications, total = service.list_for(
        user,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
        workspace_id=workspace_id,
    )

    return NotificationPage(
        items=[
            NotificationRead.model_validate(notification)
            for notification in notifications
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/unread-count", responses=AUTHENTICATED)
def read_unread_count(
    user: CurrentUserDep,
    service: NotificationServiceDep,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
) -> UnreadCount:
    """What the badge shows.

    Its own endpoint because a client asks for this far more often than
    it opens the feed, and a count is one query where a page is two.
    """
    return UnreadCount(unread=service.unread_count(user, workspace_id=workspace_id))


@router.post("/read-all", responses=AUTHENTICATED)
def mark_all_read(
    user: CurrentUserDep,
    service: NotificationServiceDep,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MarkedRead:
    """Clear the badge, for one workspace or for all of them."""
    return MarkedRead(
        marked_read=service.mark_all_read(user, workspace_id=workspace_id)
    )


@router.patch(
    "/{notification_id}/read",
    status_code=status.HTTP_200_OK,
    responses={**AUTHENTICATED, **NOTIFICATION_NOT_FOUND},
)
def mark_read(
    notification_id: uuid.UUID,
    user: CurrentUserDep,
    service: NotificationServiceDep,
) -> NotificationRead:
    """Mark one read.

    Idempotent, and the timestamp is set once: marking it again would
    move `read_at`, and "when did they see this" would stop being true
    the moment somebody clicked twice.
    """
    return NotificationRead.model_validate(service.mark_read(user, notification_id))
