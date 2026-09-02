from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models.webhook_failure import WebhookFailure, WebhookRefusal


class WebhookFailureRepository:
    """Every query against the webhook_failures table lives here.

    One write, on a path that is already refusing somebody, and two
    reads. The write matters most: it happens inside a request that is
    about to answer 403, so it must not be able to turn a refusal into a
    500 -- which is why the caller commits it separately and swallows,
    and why there is nothing here that could fail on a constraint.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        provider: str,
        reason: WebhookRefusal,
        path: str,
        ip_address: str | None,
    ) -> WebhookFailure:
        failure = WebhookFailure(
            provider=provider,
            reason=reason,
            path=path,
            ip_address=ip_address,
        )

        self._session.add(failure)
        self._session.flush()

        return failure

    def list_recent(
        self,
        *,
        limit: int,
        offset: int,
        provider: str | None = None,
        reason: WebhookRefusal | None = None,
        since: datetime | None = None,
    ) -> Sequence[WebhookFailure]:
        """What has been turned away, newest first.

        Narrowed by provider and reason because those are the two
        questions: "is the storefront misconfigured" and "is somebody
        probing us", which look identical in an unfiltered list.
        """
        return self._session.scalars(
            select(WebhookFailure)
            .where(*_filters(provider, reason, since))
            .order_by(WebhookFailure.received_at.desc(), WebhookFailure.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_recent(
        self,
        *,
        provider: str | None = None,
        reason: WebhookRefusal | None = None,
        since: datetime | None = None,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(WebhookFailure)
                .where(*_filters(provider, reason, since))
            )
            or 0
        )


def _filters(
    provider: str | None,
    reason: WebhookRefusal | None,
    since: datetime | None,
) -> list[ColumnElement[bool]]:
    """The same narrowing for a page and its total."""
    where: list[ColumnElement[bool]] = []

    if provider is not None:
        where.append(WebhookFailure.provider == provider)

    if reason is not None:
        where.append(WebhookFailure.reason == reason)

    if since is not None:
        where.append(WebhookFailure.received_at >= since)

    return where
