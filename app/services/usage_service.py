"""What a workspace has used, and over what period.

The plan's instruction for this phase is short and the whole design is in
it: create usage events at the service boundary, and do not calculate
billing-critical usage from unreliable logs.

Both halves matter. *At the service boundary*, because a meter written at
the point where something is spent is a meter that cannot forget a route
somebody adds next month. *Not from logs*, because a log records what
happened and a meter records what was used, and those are only the same
number by coincidence -- ai_response_logs has a row for every decision the
pipeline reached, including the ones that declined to answer and spent
nothing.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends

from app.db.session import SessionDep
from app.models.usage_record import UsageMetric
from app.repositories.usage_repository import UsageRepository
from app.services.plans import Plan, PlanLimit

logger = logging.getLogger(__name__)

# The metrics that accumulate and reset, and so are written as events.
# Everything not in here is a level: true right now, counted from the rows
# that define it. The distinction is not a preference -- summing a ledger
# of joins and departures to find out how many people are in a team is how
# a number starts drifting from the thing it describes.
METERED = frozenset(
    {
        UsageMetric.AI_RESPONSES,
        UsageMetric.AI_TOKENS,
        UsageMetric.WHATSAPP_MESSAGES,
    }
)

# Where a plan's limits and a workspace's usage meet, and the only place
# they do. A plan is written in the language of what is sold and a meter
# in the language of what is spent; one table between them means adding a
# limit is naming the metric it is counted against, rather than writing a
# fifth query somewhere.
LIMIT_METRICS: dict[PlanLimit, UsageMetric] = {
    PlanLimit.WHATSAPP_NUMBERS: UsageMetric.WHATSAPP_NUMBERS,
    PlanLimit.TEAM_MEMBERS: UsageMetric.TEAM_MEMBERS,
    PlanLimit.AI_RESPONSES_PER_MONTH: UsageMetric.AI_RESPONSES,
    PlanLimit.KNOWLEDGE_DOCUMENTS: UsageMetric.KNOWLEDGE_DOCUMENTS,
}


@dataclass(frozen=True)
class Period:
    """The stretch of time a total covers.

    Half open -- `start` included, `end` excluded -- like every other
    period in this application, so consecutive periods neither overlap nor
    leave a gap. A month counted in two periods is the classic way a
    usage page stops adding up.
    """

    start: datetime
    end: datetime


@dataclass(frozen=True)
class Measurement:
    """One metric, what it came to, and how much of it a plan allows."""

    metric: UsageMetric
    quantity: int
    # Null where the plan sets no ceiling on this, which covers both an
    # unlimited allowance and a metric nothing is limited by. Those read
    # the same on a usage page and mean the same thing to whoever is
    # looking at it: nothing here will refuse you.
    limit: int | None


@dataclass(frozen=True)
class Usage:
    """Everything a workspace has used, for the period it is being billed for."""

    period: Period
    measurements: list[Measurement]


class UsageService:
    """The meter. Writes what was used, and answers how much.

    Every question about how much a workspace has used is answered here,
    and every plan limit is checked against one of these answers -- so
    "am I allowed one more" and "how many have I had" cannot give
    different numbers, which is the failure that makes a usage page
    something customers write in about.

    The one service in this application that holds no session, and the
    omission is the design: a meter never owns a transaction. It writes
    into whatever transaction the caller is already in, so that the thing
    used and the record of using it are one write.
    """

    def __init__(self, usage: UsageRepository) -> None:
        self._usage = usage

    # --- writing -----------------------------------------------------------

    def record(
        self,
        workspace_id: uuid.UUID,
        metric: UsageMetric,
        *,
        source_id: uuid.UUID,
        quantity: int = 1,
        period: Period | None = None,
    ) -> None:
        """Meter one thing that was used.

        Called from the service that spent it, in the same transaction as
        whatever it spent -- the caller's commit is what makes both real,
        and the pair being one write is what stops an answer existing
        that nobody was charged for.

        Nothing is written for a quantity of nothing. A model that
        reported no tokens is not zero tokens, it is a provider that did
        not say, and a row saying zero would be a claim this does not
        have.

        A caller metering two things about one event passes the period in,
        so that one event costs one lookup -- and so that its two rows
        cannot land in different periods across a month boundary.
        """
        if quantity <= 0:
            return

        period = period or self.period(workspace_id)

        self._usage.record(
            workspace_id=workspace_id,
            metric=metric,
            quantity=quantity,
            period_start=period.start,
            period_end=period.end,
            source_id=source_id,
        )

    # --- reading -----------------------------------------------------------

    def period(self, workspace_id: uuid.UUID) -> Period:
        """The period this workspace is currently being metered over.

        The subscription's when the provider has said what it is, and the
        calendar month when it has not -- a workspace on the free plan has
        no billing period, and "this month" is what anybody would mean.

        Resolved in one place because writing and reading have to agree.
        An event stamped with a period nobody asks about is an event that
        does not count, and a limit checked against a period nothing was
        written into never refuses anything.
        """
        start, end = self._usage.subscription_period(workspace_id)

        if start is not None and end is not None:
            return Period(start=start, end=end)

        return _calendar_month(datetime.now(UTC))

    def measure(
        self,
        workspace_id: uuid.UUID,
        metric: UsageMetric,
        period: Period | None = None,
    ) -> int:
        """How much of one metric this workspace has used.

        Summed from the ledger for what accumulates, counted from the
        rows for what is a level. A caller that needs several passes the
        period in, so that a page of figures is a page about one period
        rather than about whenever each line happened to be computed.
        """
        period = period or self.period(workspace_id)

        if metric in METERED:
            return self._usage.total(workspace_id, metric, period_start=period.start)

        return self._level(workspace_id, metric, period)

    def summarise(self, workspace_id: uuid.UUID, plan: Plan) -> Usage:
        """Every metric at once, against what the plan allows.

        The plan comes in rather than being looked up, because what a
        workspace is entitled to is the subscription service's question
        and asking it from here would have each service waiting on the
        other.
        """
        period = self.period(workspace_id)
        metered = self._usage.totals(workspace_id, period_start=period.start)
        ceilings = {
            metric: plan.ceiling(limit) for limit, metric in LIMIT_METRICS.items()
        }

        return Usage(
            period=period,
            measurements=[
                Measurement(
                    metric=metric,
                    quantity=(
                        metered.get(metric, 0)
                        if metric in METERED
                        else self._level(workspace_id, metric, period)
                    ),
                    limit=ceilings.get(metric),
                )
                for metric in UsageMetric
            ],
        )

    def _level(
        self,
        workspace_id: uuid.UUID,
        metric: UsageMetric,
        period: Period,
    ) -> int:
        """A metric that is not accumulated but simply true right now.

        Active contacts is in here rather than in the ledger for a reason
        worth stating: it is period-scoped like a total but it is a
        distinct count, and a customer who sends twenty messages is one
        active contact.
        """
        if metric == UsageMetric.ACTIVE_CONTACTS:
            return self._usage.active_contacts(
                workspace_id,
                start=period.start,
                end=period.end,
            )

        counters = {
            UsageMetric.TEAM_MEMBERS: self._usage.team_members,
            UsageMetric.WHATSAPP_NUMBERS: self._usage.whatsapp_numbers,
            UsageMetric.KNOWLEDGE_DOCUMENTS: self._usage.knowledge_documents,
            UsageMetric.KNOWLEDGE_TOKENS: self._usage.knowledge_tokens,
        }

        return counters[metric](workspace_id)


def _calendar_month(now: datetime) -> Period:
    """This month, in UTC, for a workspace that has no billing period.

    UTC rather than the business's own timezone, unlike the analytics
    dashboard. A dashboard is about a shopkeeper's days and should end
    them when they do; an allowance is about a boundary that must be the
    same one every time it is asked, from a webhook with no member behind
    it as much as from a page.
    """
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # The first of next month, found by stepping into it rather than by
    # arithmetic on month numbers, which is where December goes wrong.
    end = (start + timedelta(days=32)).replace(day=1)

    return Period(start=start, end=end)


def get_usage_repository(session: SessionDep) -> UsageRepository:
    return UsageRepository(session)


UsageRepositoryDep = Annotated[UsageRepository, Depends(get_usage_repository)]


def get_usage_service(usage: UsageRepositoryDep) -> UsageService:
    return UsageService(usage=usage)


UsageServiceDep = Annotated[UsageService, Depends(get_usage_service)]
