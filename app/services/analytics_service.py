from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends

from app.core.exceptions import InvalidDateRangeError, UnknownTimezoneError
from app.db.session import SessionDep
from app.repositories.analytics_repository import (
    AnalyticsRepository,
    DayCount,
    Window,
)
from app.services.workspace_service import WorkspaceAccess

# What a dashboard opens on when nobody has chosen a range.
DEFAULT_DAYS = 30

# Long enough for a quarter, short enough that nobody accidentally asks
# for a scan of everything a successful business has ever done.
MAX_DAYS = 366


class AnalyticsService:
    """The numbers a business is shown about its own inbox.

    Thin on purpose: the counting is the repository's job and belongs in
    SQL, and what is left here is the part that is genuinely a decision --
    what period "the last month" means, in which timezone, and which of
    the raw counts get combined into a rate.
    """

    def __init__(self, analytics: AnalyticsRepository) -> None:
        self._analytics = analytics

    def window(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        timezone: str = "UTC",
    ) -> Window:
        """Turn two dates and a timezone into an instant range.

        The dates are the business's own days, so they are anchored in its
        timezone before becoming instants. `end` is inclusive as a date --
        somebody asking for the 1st to the 7th means the 7th as well --
        and exclusive as an instant, which is why a day is added: those
        are the same request expressed for a person and for a database.
        """
        zone = _zone(timezone)
        last = end or datetime.now(zone).date()
        first = start or (last - timedelta(days=DEFAULT_DAYS - 1))

        if first > last:
            raise InvalidDateRangeError("The start of the range is after its end")

        if (last - first).days + 1 > MAX_DAYS:
            raise InvalidDateRangeError(f"A range may cover at most {MAX_DAYS} days")

        return Window(
            start=datetime.combine(first, datetime.min.time(), tzinfo=zone),
            end=datetime.combine(
                last + timedelta(days=1), datetime.min.time(), tzinfo=zone
            ),
            timezone=timezone,
        )

    def overview(self, access: WorkspaceAccess, window: Window) -> dict[str, object]:
        """The headline figures, in one call.

        One call because it is one screen. A dashboard that has to make
        five requests to draw its top row is a dashboard that renders in
        pieces.
        """
        workspace_id = access.workspace.id
        conversations = self._analytics.conversation_totals(workspace_id, window)
        messages = self._analytics.message_totals(workspace_id, window)
        handled = self._analytics.conversations_handled_by(workspace_id, window)
        ai = self._analytics.ai_totals(workspace_id, window)
        handoffs = self._analytics.handoff_totals(workspace_id, window)

        return {
            "conversations": conversations,
            "messages": messages,
            "handled": handled,
            "handoffs": handoffs["total"],
            "ai_response_rate": _rate(handled["by_ai"], handled["answered"]),
            "ai_decisions": ai["total"],
            "average_first_response_seconds": (
                self._analytics.average_first_response_seconds(workspace_id, window)
            ),
        }

    def conversations(
        self,
        access: WorkspaceAccess,
        window: Window,
    ) -> dict[str, object]:
        workspace_id = access.workspace.id

        return {
            "totals": self._analytics.conversation_totals(workspace_id, window),
            "by_day": _fill(
                self._analytics.conversations_by_day(workspace_id, window),
                window,
            ),
            "average_first_response_seconds": (
                self._analytics.average_first_response_seconds(workspace_id, window)
            ),
        }

    def ai(self, access: WorkspaceAccess, window: Window) -> dict[str, object]:
        workspace_id = access.workspace.id
        decisions = self._analytics.ai_totals(workspace_id, window)
        handled = self._analytics.conversations_handled_by(workspace_id, window)

        return {
            "decisions": decisions,
            "handoffs": self._analytics.handoff_totals(workspace_id, window),
            "cost": self._analytics.ai_cost(workspace_id, window),
            "by_day": _fill(
                self._analytics.ai_decisions_by_day(workspace_id, window),
                window,
            ),
            # Of the conversations somebody answered, how many the
            # assistant spoke in. The plan's "AI response rate", and the
            # figure a business is actually buying.
            "response_rate": _rate(handled["by_ai"], handled["answered"]),
            # Of the times it was asked, how often it produced something
            # to send. A different question, and the one that says whether
            # the knowledge base is good enough yet.
            "answer_rate": _rate(
                decisions["answered"] + decisions["suggested"],
                decisions["total"],
            ),
        }


def _fill(counts: list[DayCount], window: Window) -> list[dict[str, object]]:
    """Every day of the range, including the ones with nothing in them.

    A chart drawn from only the days that had activity has no gaps in it,
    which makes a quiet week look like a busy one with fewer points.
    """
    found = {row.day: row.count for row in counts}
    zone = _zone(window.timezone)
    first = window.start.astimezone(zone).date()
    last = (window.end.astimezone(zone) - timedelta(days=1)).date()

    days: list[dict[str, object]] = []
    current = first

    while current <= last:
        days.append({"day": current, "count": found.get(current, 0)})
        current += timedelta(days=1)

    return days


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        # Refused rather than quietly falling back to UTC. A dashboard
        # showing a shop in Karachi its days measured from London midnight
        # is wrong in a way nobody notices until somebody counts by hand.
        raise UnknownTimezoneError(name) from exc


def _rate(part: int, whole: int) -> float:
    """A proportion, with nothing to divide by reported as zero.

    Zero here rather than the one the evaluation uses: a workspace that
    has answered nothing has an AI response rate of nothing, and showing
    it as 100% would be the most flattering possible lie.
    """
    return 0.0 if whole == 0 else round(part / whole, 4)


def get_analytics_repository(session: SessionDep) -> AnalyticsRepository:
    return AnalyticsRepository(session)


AnalyticsRepositoryDep = Annotated[
    AnalyticsRepository,
    Depends(get_analytics_repository),
]


def get_analytics_service(analytics: AnalyticsRepositoryDep) -> AnalyticsService:
    return AnalyticsService(analytics=analytics)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
