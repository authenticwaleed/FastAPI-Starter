import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import (
    ColumnElement,
    Date,
    Float,
    and_,
    case,
    cast,
    func,
    select,
)
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models.ai_response_log import AiDecision, AiResponseLog
from app.models.conversation import Conversation, ConversationStatus
from app.models.conversation_event import ConversationEvent, EventType
from app.models.message import Direction, Message, SenderType


@dataclass(frozen=True)
class Window:
    """The period a figure covers, and the clock it is read by.

    Half open -- `start` included, `end` excluded -- because that is the
    only arrangement where consecutive periods neither overlap nor leave a
    gap, and a day counted in two weeks is the classic way a dashboard
    stops adding up.
    """

    start: datetime
    end: datetime
    # An IANA name. Days are the business's days: a shop in Karachi
    # closing at nine in the evening has its last order of the day counted
    # on that day, not on the next one because UTC has already rolled over.
    timezone: str = "UTC"


@dataclass(frozen=True)
class DayCount:
    day: date
    count: int


class AnalyticsRepository:
    """Every aggregate the dashboard shows, computed in the database.

    In the database and not in Python, throughout. These are counts over
    every conversation and message a business has ever had; reading them
    into the application to count them there would work on a pilot's data
    and stop working on the first customer who succeeds.

    Workspace-scoped like everything else, and here the scoping is also
    what makes the numbers mean anything: a total that quietly included
    another business would not look wrong, it would just be wrong.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- conversations -----------------------------------------------------

    def conversation_totals(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> dict[str, int]:
        """How many conversations there are, and how many are still live.

        One query with conditional counts rather than one query per figure.
        Four round trips for four numbers that come from the same rows is
        the shape that makes a dashboard slow for no reason.
        """
        row = self._session.execute(
            select(
                func.count().label("total"),
                _count_if(Conversation.status == ConversationStatus.OPEN).label("open"),
                _count_if(Conversation.status == ConversationStatus.PENDING).label(
                    "pending"
                ),
                _count_if(Conversation.status == ConversationStatus.CLOSED).label(
                    "closed"
                ),
                _count_if(Conversation.handoff_at.is_not(None)).label("with_a_human"),
                _count_if(Conversation.assigned_user_id.is_(None)).label("unassigned"),
            ).where(
                Conversation.workspace_id == workspace_id,
                Conversation.created_at >= window.start,
                Conversation.created_at < window.end,
            )
        ).one()

        return {
            "total": row.total,
            "open": row.open,
            "pending": row.pending,
            "closed": row.closed,
            "with_a_human": row.with_a_human,
            "unassigned": row.unassigned,
        }

    def conversations_by_day(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> list[DayCount]:
        """How many conversations were opened on each day of the period.

        The date is taken after converting to the workspace's timezone, so
        the buckets are the days a person there would recognise. Days with
        nothing in them are absent rather than zero -- filling the range in
        is the caller's job, because only the caller knows whether a gap
        should be drawn as a zero or as no data.
        """
        day = _local_date(Conversation.created_at, window.timezone)

        rows = self._session.execute(
            # Labelled `total` and not `count`: a Row is tuple-like and
            # already has a `.count` method, so the attribute would resolve
            # to that rather than to the column.
            select(day.label("day"), func.count().label("total"))
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.created_at >= window.start,
                Conversation.created_at < window.end,
            )
            .group_by(day)
            .order_by(day)
        ).all()

        return [DayCount(day=row.day, count=row.total) for row in rows]

    # --- messages ----------------------------------------------------------

    def message_totals(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> dict[str, int]:
        """What was said, and by whom.

        The split by sender is the one that answers the plan's question
        about value: an assistant that sends nothing is not saving anybody
        any work, whatever else the dashboard says.
        """
        row = self._session.execute(
            select(
                func.count().label("total"),
                _count_if(Message.direction == Direction.INBOUND).label("received"),
                _count_if(Message.direction == Direction.OUTBOUND).label("sent"),
                _count_if(Message.sender_type == SenderType.AI).label("by_ai"),
                _count_if(Message.sender_type == SenderType.AGENT).label("by_agents"),
            ).where(
                Message.workspace_id == workspace_id,
                Message.created_at >= window.start,
                Message.created_at < window.end,
            )
        ).one()

        return {
            "total": row.total,
            "received": row.received,
            "sent": row.sent,
            "by_ai": row.by_ai,
            "by_agents": row.by_agents,
        }

    def average_first_response_seconds(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> float | None:
        """How long a customer waits, on average, to hear anything back.

        Measured per conversation from its first inbound message to the
        first outbound one after it. Conversations nobody has answered yet
        are left out rather than counted as zero or as infinity: an
        unanswered thread is a different figure -- how many are waiting --
        and folding it in here would make a busy morning look like an
        improvement.

        None when nothing in the period has been answered at all, which is
        an honest "no data" rather than a zero that reads as instant.
        """
        first_in = (
            select(
                Message.conversation_id.label("conversation_id"),
                func.min(Message.created_at).label("at"),
            )
            .where(
                Message.workspace_id == workspace_id,
                Message.direction == Direction.INBOUND,
                Message.created_at >= window.start,
                Message.created_at < window.end,
            )
            .group_by(Message.conversation_id)
            .subquery()
        )

        first_out = (
            select(
                Message.conversation_id.label("conversation_id"),
                func.min(Message.created_at).label("at"),
            )
            .where(
                Message.workspace_id == workspace_id,
                Message.direction == Direction.OUTBOUND,
            )
            .group_by(Message.conversation_id)
            .subquery()
        )

        gap = func.extract("epoch", first_out.c.at - first_in.c.at)

        return self._session.scalar(
            select(func.avg(cast(gap, Float))).select_from(
                first_in.join(
                    first_out,
                    and_(
                        first_out.c.conversation_id == first_in.c.conversation_id,
                        # Only replies that came after the question. A
                        # thread reopened months later has an outbound
                        # message older than its newest inbound one, and
                        # counting that would produce a negative wait.
                        first_out.c.at >= first_in.c.at,
                    ),
                )
            )
        )

    # --- the assistant -----------------------------------------------------

    def ai_totals(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> dict[str, int]:
        """What the assistant decided, counted by decision."""
        row = self._session.execute(
            select(
                func.count().label("total"),
                *[
                    _count_if(AiResponseLog.decision == decision).label(decision.value)
                    for decision in AiDecision
                ],
            ).where(
                AiResponseLog.workspace_id == workspace_id,
                AiResponseLog.created_at >= window.start,
                AiResponseLog.created_at < window.end,
            )
        ).one()

        return {"total": row.total} | {
            decision.value: getattr(row, decision.value) for decision in AiDecision
        }

    def ai_cost(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> dict[str, float | None]:
        """What the assistant spent, and how long it took."""
        row = self._session.execute(
            select(
                func.sum(AiResponseLog.input_tokens).label("input_tokens"),
                func.sum(AiResponseLog.output_tokens).label("output_tokens"),
                func.avg(cast(AiResponseLog.latency_ms, Float)).label("latency"),
                func.avg(cast(AiResponseLog.confidence, Float)).label("confidence"),
            ).where(
                AiResponseLog.workspace_id == workspace_id,
                AiResponseLog.created_at >= window.start,
                AiResponseLog.created_at < window.end,
            )
        ).one()

        return {
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "average_latency_ms": row.latency,
            "average_confidence": row.confidence,
        }

    def handoff_totals(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> dict[str, int]:
        """How often a thread changed hands, and in which direction."""
        row = self._session.execute(
            select(
                func.count().label("total"),
                *[
                    _count_if(ConversationEvent.event_type == kind).label(kind.value)
                    for kind in EventType
                ],
            ).where(
                ConversationEvent.workspace_id == workspace_id,
                ConversationEvent.created_at >= window.start,
                ConversationEvent.created_at < window.end,
            )
        ).one()

        return {"total": row.total} | {
            kind.value: getattr(row, kind.value) for kind in EventType
        }

    def ai_decisions_by_day(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> list[DayCount]:
        day = _local_date(AiResponseLog.created_at, window.timezone)

        rows = self._session.execute(
            # Labelled `total` and not `count`: a Row is tuple-like and
            # already has a `.count` method, so the attribute would resolve
            # to that rather than to the column.
            select(day.label("day"), func.count().label("total"))
            .where(
                AiResponseLog.workspace_id == workspace_id,
                AiResponseLog.created_at >= window.start,
                AiResponseLog.created_at < window.end,
            )
            .group_by(day)
            .order_by(day)
        ).all()

        return [DayCount(day=row.day, count=row.total) for row in rows]

    def conversations_handled_by(
        self,
        workspace_id: uuid.UUID,
        window: Window,
    ) -> dict[str, int]:
        """How many distinct conversations the assistant and people spoke in.

        Conversations rather than messages, because "the AI handled forty
        threads" is the sentence a business wants and "the AI sent ninety
        messages" is not. A thread both answered in counts for both, which
        is right: it was handled by both.
        """
        row = self._session.execute(
            select(
                func.count(func.distinct(Message.conversation_id)).label("any"),
                func.count(
                    func.distinct(
                        case(
                            (
                                Message.sender_type == SenderType.AI,
                                Message.conversation_id,
                            )
                        )
                    )
                ).label("by_ai"),
                func.count(
                    func.distinct(
                        case(
                            (
                                Message.sender_type == SenderType.AGENT,
                                Message.conversation_id,
                            )
                        )
                    )
                ).label("by_agents"),
            ).where(
                Message.workspace_id == workspace_id,
                Message.direction == Direction.OUTBOUND,
                Message.created_at >= window.start,
                Message.created_at < window.end,
            )
        ).one()

        return {
            "answered": row.any,
            "by_ai": row.by_ai,
            "by_agents": row.by_agents,
        }


def _count_if(condition: ColumnElement[bool]) -> ColumnElement[int]:
    """Count the rows matching a condition, alongside other counts.

    `count` ignores nulls, so a CASE that yields NULL when the condition
    fails counts exactly the rows that met it -- which is what lets six
    figures come from one pass over the table instead of six.
    """
    return func.count(case((condition, 1)))


def _local_date(
    column: "InstrumentedAttribute[datetime]", timezone: str
) -> ColumnElement[date]:
    """The calendar day a timestamp falls on, in a given timezone.

    `AT TIME ZONE` turns the stored instant into a wall clock reading
    there, and the date of that is the day a person in that place would
    call it. Without this every figure is bucketed by UTC midnight, which
    for a shop in Karachi puts its evening into the following day.
    """
    return cast(func.timezone(timezone, column), Date)
