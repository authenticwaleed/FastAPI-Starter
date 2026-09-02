"""Writing down a delivery that was turned away.

Small, and one property matters more than the rest: **this must never be
able to turn a refusal into a 500.** It runs inside a request that is
already answering 403, on a path a stranger can reach, so an exception
escaping here would replace a clean refusal with an unhandled error --
and would do it on exactly the endpoint somebody probing would be
poking at.

So it commits on its own and swallows whatever goes wrong. Losing a
diagnostic row is a smaller failure than the alternative, and the log
line stays either way.
"""

import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import SessionDep
from app.models.webhook_failure import WebhookRefusal
from app.repositories.webhook_failure_repository import WebhookFailureRepository

logger = logging.getLogger(__name__)


class WebhookFailureService:
    """Recording a refusal, without being able to cause one."""

    def __init__(
        self,
        session: Session,
        failures: WebhookFailureRepository,
    ) -> None:
        self._session = session
        self._failures = failures

    def note(
        self,
        *,
        provider: str,
        reason: WebhookRefusal,
        path: str,
        ip_address: str | None,
    ) -> None:
        """Write the row, and never mind if it cannot be written.

        Committed here rather than left to the caller, and that is
        forced: every caller is about to raise, and the session's
        teardown rolls back what an exception passed through.
        """
        try:
            self._failures.record(
                provider=provider,
                reason=reason,
                path=path,
                ip_address=ip_address,
            )
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            logger.warning("A refused delivery could not be recorded")


def get_webhook_failure_repository(session: SessionDep) -> WebhookFailureRepository:
    return WebhookFailureRepository(session)


WebhookFailureRepositoryDep = Annotated[
    WebhookFailureRepository,
    Depends(get_webhook_failure_repository),
]


def get_webhook_failure_service(
    session: SessionDep,
    failures: WebhookFailureRepositoryDep,
) -> WebhookFailureService:
    return WebhookFailureService(session=session, failures=failures)


WebhookFailureServiceDep = Annotated[
    WebhookFailureService,
    Depends(get_webhook_failure_service),
]
