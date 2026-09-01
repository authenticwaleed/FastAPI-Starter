from fastapi import APIRouter

from app.api.dependencies.workspace import WorkspaceMemberDep
from app.api.errors import (
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.schemas.usage import MetricUsage, UsageSummary
from app.services.subscription_service import SubscriptionServiceDep
from app.services.usage_service import UsageServiceDep

router = APIRouter(prefix="/workspaces/{workspace_id}/usage", tags=["usage"])

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


@router.get("", responses=SCOPED)
def read_usage(
    access: WorkspaceMemberDep,
    usage: UsageServiceDep,
    subscriptions: SubscriptionServiceDep,
) -> UsageSummary:
    """Everything this workspace has used this period, against its allowance.

    Any member, like the plan itself. Being refused for reaching a limit
    by a product that will not say how close you were is the sort of thing
    a business finds out about from a customer who did not get an answer.

    One request for all of it, because it is one screen -- and because
    every figure has to be about the same period. A page that fetched its
    lines separately would render a month boundary as an inconsistency.
    """
    plan = subscriptions.plan_for(access.workspace.id)
    measured = usage.summarise(access.workspace.id, plan)

    return UsageSummary(
        period_start=measured.period.start,
        period_end=measured.period.end,
        metrics=[
            MetricUsage(
                metric=measurement.metric,
                quantity=measurement.quantity,
                limit=measurement.limit,
            )
            for measurement in measured.measurements
        ],
    )
