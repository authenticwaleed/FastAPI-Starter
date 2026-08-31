"""Assembling real services against a test's own session.

A service that reaches another service needs that other service, so
constructing one by hand in a test means constructing its graph. What
lives here is the wiring several suites would otherwise repeat -- and,
more to the point, the wiring several suites would otherwise each have to
be edited for the next time a constructor grows an argument.
"""

from sqlalchemy.orm import Session

from app.repositories.notification_repository import NotificationRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.notification_service import NotificationService


def notification_service(session: Session) -> NotificationService:
    """The real one, on a test's own session.

    Real rather than a stub. What notifications have to get right is
    landing in the same transaction as whatever caused them, and a stub
    would be a second implementation of exactly that -- one that could
    not be wrong in the way the real one can.
    """
    return NotificationService(
        session=session,
        notifications=NotificationRepository(session),
        memberships=WorkspaceMembershipRepository(session),
    )
