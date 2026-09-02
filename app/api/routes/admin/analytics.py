from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.staff import StaffAdminDep
from app.api.errors import ADMIN_FORBIDDEN, ADMIN_UNAUTHORISED, RATE_LIMITED
from app.models.admin_audit_log import AdminAction
from app.repositories.platform_analytics_repository import DailyCount
from app.schemas.admin_analytics import (
    AdminAiSpend,
    AdminGrowth,
    AdminOverview,
    AdminRevenue,
    DailyPoint,
    PlatformCounts,
)
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.platform_analytics_service import PlatformAnalyticsRepositoryDep
from app.services.staff_service import StaffActor

router = APIRouter(prefix="/analytics", tags=["platform"])

PLATFORM = {**ADMIN_UNAUTHORISED, **ADMIN_FORBIDDEN, **RATE_LIMITED}

# How far back a chart looks by default, and the furthest it will. Ninety
# days is a quarter, which is the unit these questions are actually asked
# in; the ceiling exists because every one of these is a full scan of a
# table that only grows, and a request for five years is a request that
# takes the database with it.
DEFAULT_DAYS = 30
MAX_DAYS = 365


# `admin` throughout, and this is the one part of the surface where the
# rank is about seniority rather than safety: nothing here reveals a
# customer, and none of it can be acted on. It is `admin` because a
# revenue chart is not a support tool.
#
# There is no route in this file that takes a workspace id, and that is
# the phase's whole rule -- every figure is an aggregate, and a test
# asserts it over the published paths rather than trusting this comment.
@router.get("/overview", responses=PLATFORM)
def read_overview(
    actor: StaffAdminDep,
    analytics: PlatformAnalyticsRepositoryDep,
    audit: AdminAuditServiceDep,
) -> AdminOverview:
    """Where the platform stands right now.

    Statuses and plans as maps, so a console renders a fixed set of tiles
    without asking for the vocabulary separately. A value with nothing in
    it is absent rather than zero, which reads the same on a tile.

    The plan here is what the provider says rather than what a workspace
    is entitled to. That difference matters on this page more than
    anywhere: it is a commercial number, and a business comped onto
    Business is not revenue.
    """
    overview = AdminOverview(
        counts=PlatformCounts(**analytics.counts()),
        workspaces_by_status=analytics.workspaces_by_status(),
        workspaces_by_plan=analytics.workspaces_by_plan(),
    )

    _record(actor, audit, "overview")

    return overview


@router.get("/growth", responses=PLATFORM)
def read_growth(
    actor: StaffAdminDep,
    analytics: PlatformAnalyticsRepositoryDep,
    audit: AdminAuditServiceDep,
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = DEFAULT_DAYS,
) -> AdminGrowth:
    """Signups and closures over time, and how many businesses did anything.

    The third number is the one worth having. Workspaces that exist is a
    count anybody can get; workspaces that sent a message this month is
    what says whether the product is used -- and a platform with four
    hundred of the first and nine of the second knows something the
    headline hides.

    Days are UTC. A platform-wide chart cannot be in every customer's
    local day at once, and this is the day their timestamps are stored
    in.
    """
    since = _since(days)
    growth = AdminGrowth(
        days=days,
        signups=_points(analytics.signups_by_day(since=since)),
        closures=_points(analytics.closures_by_day(since=since)),
        active_workspaces=analytics.active_workspaces(since=since),
    )

    _record(actor, audit, "growth", days=days)

    return growth


@router.get("/revenue", responses=PLATFORM)
def read_revenue(
    actor: StaffAdminDep,
    analytics: PlatformAnalyticsRepositoryDep,
    audit: AdminAuditServiceDep,
) -> AdminRevenue:
    """What is being paid for, as counts rather than as an amount.

    What a plan costs lives in `app/services/plans.py`, and multiplying
    belongs where the prices are: a figure computed here would need
    editing every time one changed, and would be quietly wrong in
    between.

    `past_due` is the number to watch. Those businesses still have their
    plan while the provider retries, and each one is either about to pay
    or about to churn.
    """
    revenue = AdminRevenue(
        subscriptions_by_status=analytics.subscriptions_by_status(),
        paying_by_plan=analytics.paying_by_plan(),
    )

    _record(actor, audit, "revenue")

    return revenue


@router.get("/ai", responses=PLATFORM)
def read_ai_spend(
    actor: StaffAdminDep,
    analytics: PlatformAnalyticsRepositoryDep,
    audit: AdminAuditServiceDep,
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = DEFAULT_DAYS,
) -> AdminAiSpend:
    """What the assistant cost across every tenant.

    The plan calls this the number that decides whether the pricing
    works, and it is in tokens rather than money on purpose: what a token
    costs is a contract with a model provider, changes without this
    application being redeployed, and differs per model.

    `replies` sits beside the totals because tokens per reply is the
    figure that moves when somebody grows a prompt -- and it moves before
    the bill does.
    """
    since = _since(days)
    spend = analytics.ai_spend(since=since)
    answer = AdminAiSpend(
        days=days,
        replies=int(spend["replies"] or 0),
        input_tokens=_whole(spend["input_tokens"]),
        output_tokens=_whole(spend["output_tokens"]),
        average_latency_ms=_number(spend["average_latency_ms"]),
        by_model=analytics.ai_by_model(since=since),
    )

    _record(actor, audit, "ai", days=days)

    return answer


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _points(counted: Sequence[DailyCount]) -> list[DailyPoint]:
    return [DailyPoint(day=point.day, count=point.count) for point in counted]


def _whole(value: float | int | None) -> int | None:
    """Tokens are whole, and SUM returns a decimal on some drivers."""
    return None if value is None else int(value)


def _number(value: float | int | None) -> float | None:
    return None if value is None else float(value)


def _record(
    actor: StaffActor,
    audit: AdminAuditService,
    page: str,
    **meta: object,
) -> None:
    """Record the read, like every other route on this surface.

    These are the one set of reads here that reveal nothing about any one
    customer, and they are recorded anyway: the rule is about the surface
    rather than about each route, and an exception would be the first
    crack in it.
    """
    audit.did(actor.logged, AdminAction.ANALYTICS_READ, meta={"page": page, **meta})
