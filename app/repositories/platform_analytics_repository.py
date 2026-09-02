from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, Float, cast, func, literal, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models.ai_response_log import AiResponseLog
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.services.plans import PlanTier


@dataclass(frozen=True)
class DailyCount:
    """One day, and how many of something happened on it."""

    day: date
    count: int


class PlatformAnalyticsRepository:
    """Aggregates across every workspace, and never one workspace's data.

    The last phase in the plan, and deliberately: it is the most fun to
    build and the least urgent, and building it early produces a
    dashboard nobody can act on.

    Every query here is a `COUNT`, a `SUM` or an `AVG` with a `GROUP BY`
    that is a status, a plan or a day -- never an id. That is the rule
    for this whole surface, and it is checked by a test rather than left
    to care: no route in analytics reveals one customer's data, so the
    shape of the queries has to make that hard to break.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- how many businesses, and in what state ---------------------------

    def workspaces_by_status(self) -> dict[WorkspaceStatus, int]:
        """Every business, grouped by where it stands.

        The first number anybody asks for and the one that answers "is
        the product growing or churning": active against cancelled, in
        one line, without a spreadsheet.
        """
        rows = self._session.execute(
            select(Workspace.status, func.count())
            .group_by(Workspace.status)
            .order_by(Workspace.status)
        ).all()

        return dict(rows)  # type: ignore[arg-type]

    def workspaces_by_plan(self) -> dict[PlanTier, int]:
        """Every business, grouped by what it is paying for.

        By the subscription rather than by the resolved entitlement, and
        the difference matters here more than anywhere: this is a revenue
        question, and a workspace comped onto Business is not revenue. The
        console's own search answers the entitlement question.

        Workspaces with no subscription are counted under the free tier,
        which is what they are on.
        """
        # Built once and reused, rather than written twice. Two
        # `coalesce` calls with the same arguments compile to two
        # different bind parameters, and Postgres will not match them --
        # so grouping by a second copy is a GroupingError rather than the
        # same expression.
        plan = func.coalesce(Subscription.plan, literal(PlanTier.STARTER.value))

        rows = self._session.execute(
            select(plan, func.count())
            .select_from(Workspace)
            .outerjoin(Subscription, Subscription.workspace_id == Workspace.id)
            .where(Workspace.status != WorkspaceStatus.CANCELLED)
            .group_by(plan)
        ).all()

        return {PlanTier(plan): count for plan, count in rows}

    def counts(self) -> dict[str, int]:
        """The platform's totals, in one round trip.

        Four scalar subqueries in one statement rather than four
        statements, for the reason the workspace detail's counts are: a
        dashboard whose cost is one query per tile gets slower every time
        somebody adds a tile.
        """
        row = self._session.execute(
            select(
                select(func.count()).select_from(User).scalar_subquery(),
                select(func.count()).select_from(Workspace).scalar_subquery(),
                select(func.count()).select_from(Conversation).scalar_subquery(),
                select(func.count()).select_from(Message).scalar_subquery(),
            )
        ).one()

        return {
            "users": row[0],
            "workspaces": row[1],
            "conversations": row[2],
            "messages": row[3],
        }

    # --- growth over time -------------------------------------------------

    def signups_by_day(self, *, since: datetime) -> Sequence[DailyCount]:
        """Workspaces created, per day.

        Grouped in UTC rather than in each business's own timezone, and
        that is a real limitation worth stating: a platform-wide chart
        cannot be in every customer's local day at once, so it is in the
        one day everybody's timestamps are already stored in.
        """
        return self._by_day(Workspace.created_at, since=since)

    def closures_by_day(self, *, since: datetime) -> Sequence[DailyCount]:
        """Workspaces closed, per day.

        By `erase_after` less the grace period would be exact and
        fragile; this uses `updated_at` on a cancelled row, which is
        right until somebody edits a cancelled workspace. Named here
        rather than hidden, because a churn chart that is quietly
        approximate is worse than one that says so.
        """
        return self._by_day(
            Workspace.updated_at,
            since=since,
            where=Workspace.status == WorkspaceStatus.CANCELLED,
        )

    def active_workspaces(self, *, since: datetime) -> int:
        """Businesses that actually used the product, not ones that exist.

        Counted from messages rather than from rows, which is the whole
        point of the number: a platform with four hundred workspaces and
        nine that have sent a message this month knows something a
        headline count would hide.
        """
        return (
            self._session.scalar(
                select(func.count(func.distinct(Message.workspace_id))).where(
                    Message.created_at >= since
                )
            )
            or 0
        )

    # --- what the assistant costs -----------------------------------------

    def ai_spend(self, *, since: datetime) -> dict[str, float | int | None]:
        """Tokens across every tenant, which is the number pricing turns on.

        Tokens rather than money, deliberately. What a token costs is a
        contract with a model provider, changes without this application
        being redeployed, and differs per model -- so a figure in dollars
        computed here would be authoritative-looking and wrong. Tokens
        multiplied by whoever knows the current rate is the honest shape.
        """
        row = self._session.execute(
            select(
                func.count(),
                func.sum(AiResponseLog.input_tokens),
                func.sum(AiResponseLog.output_tokens),
                func.avg(cast(AiResponseLog.latency_ms, Float)),
            ).where(AiResponseLog.created_at >= since)
        ).one()

        return {
            "replies": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "average_latency_ms": row[3],
        }

    def ai_by_model(self, *, since: datetime) -> dict[str, int]:
        """Replies per model, which is what a migration between two looks like.

        The model is a string the adapter recorded rather than an enum,
        so this groups by whatever was actually used -- including the one
        somebody changed in configuration and forgot to mention.
        """
        rows = self._session.execute(
            select(AiResponseLog.model, func.count())
            .where(
                AiResponseLog.created_at >= since,
                AiResponseLog.model.is_not(None),
            )
            .group_by(AiResponseLog.model)
            .order_by(func.count().desc())
        ).all()

        return {str(model): count for model, count in rows}

    # --- revenue ----------------------------------------------------------

    def subscriptions_by_status(self) -> dict[SubscriptionStatus, int]:
        """Every subscription, grouped by what the provider says.

        `past_due` here is the number to watch: those businesses still
        have their plan while the provider retries, and each one is
        either about to pay or about to churn.
        """
        rows = self._session.execute(
            select(Subscription.status, func.count()).group_by(Subscription.status)
        ).all()

        return dict(rows)  # type: ignore[arg-type]

    def paying_by_plan(self) -> dict[PlanTier, int]:
        """Subscriptions that are actually good for something, by plan.

        The multiplicand for a revenue figure, and it stops here: what a
        plan costs is in `app/services/plans.py`, and multiplying happens
        where the prices are rather than in SQL that would need editing
        every time one changed.
        """
        rows = self._session.execute(
            select(Subscription.plan, func.count())
            .where(
                Subscription.status.in_(
                    (
                        SubscriptionStatus.ACTIVE,
                        SubscriptionStatus.TRIALING,
                        SubscriptionStatus.PAST_DUE,
                    )
                )
            )
            .group_by(Subscription.plan)
        ).all()

        return {PlanTier(plan): count for plan, count in rows}

    # --- shared ------------------------------------------------------------

    def _by_day(
        self,
        column: InstrumentedAttribute[datetime],
        *,
        since: datetime,
        where: ColumnElement[bool] | None = None,
    ) -> Sequence[DailyCount]:
        """Count rows per calendar day, oldest first.

        `date_trunc` in the database rather than bucketing in Python: the
        alternative is fetching every row to count them, which is a chart
        that stops loading in the year the platform succeeds.

        Converted to UTC first, and that is not decoration.
        `date_trunc('day', ts)` on a `timestamptz` truncates in the
        *database session's* timezone, so a signup at 23:30 UTC lands on
        the next day wherever the server is set to Asia/Karachi and on
        the same day where it is set to UTC. Two deployments would draw
        different charts from identical data, and neither would look
        wrong.
        """
        day = func.date_trunc("day", func.timezone("UTC", column)).label("day")
        conditions: list[ColumnElement[bool]] = [column >= since]

        if where is not None:
            conditions.append(where)

        rows = self._session.execute(
            select(day, func.count()).where(*conditions).group_by(day).order_by(day)
        ).all()

        return [DailyCount(day=moment.date(), count=count) for moment, count in rows]
