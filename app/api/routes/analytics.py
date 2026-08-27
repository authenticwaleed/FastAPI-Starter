from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.workspace import WorkspaceMemberDep
from app.api.errors import (
    BAD_RANGE,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.repositories.analytics_repository import Window
from app.schemas.analytics import (
    AiAnalytics,
    ConversationAnalytics,
    Overview,
)
from app.services.analytics_service import AnalyticsService, AnalyticsServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/analytics",
    tags=["analytics"],
)

SCOPED = {
    **UNAUTHORISED,
    **WORKSPACE_FORBIDDEN,
    **WORKSPACE_NOT_FOUND,
    **BAD_RANGE,
}


def _window(
    service: AnalyticsService,
    start: date | None,
    end: date | None,
    timezone: str,
) -> Window:
    """The period asked for, or the last thirty days.

    Both dates are inclusive and are the business's own days, read in the
    timezone given: somebody asking for the 1st to the 7th means the 7th
    as well, and means their 7th rather than UTC's.
    """
    return service.window(start=start, end=end, timezone=timezone)


# Any member may read the numbers. They are about the workspace's own
# work rather than about any one customer, and a viewer whose job is to
# watch the dashboard is exactly who this is for.
@router.get("/overview", responses=SCOPED)
def read_overview(
    access: WorkspaceMemberDep,
    service: AnalyticsServiceDep,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    timezone: Annotated[str, Query(max_length=64)] = "UTC",
) -> Overview:
    """The headline figures, in one request.

    One request because it is one screen: a dashboard that makes five
    calls to draw its top row renders in pieces.
    """
    window = _window(service, start, end, timezone)

    return Overview.model_validate(service.overview(access, window))


@router.get("/conversations", responses=SCOPED)
def read_conversation_analytics(
    access: WorkspaceMemberDep,
    service: AnalyticsServiceDep,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    timezone: Annotated[str, Query(max_length=64)] = "UTC",
) -> ConversationAnalytics:
    """Volume and responsiveness, with a point for every day of the range."""
    window = _window(service, start, end, timezone)

    return ConversationAnalytics.model_validate(service.conversations(access, window))


@router.get("/ai", responses=SCOPED)
def read_ai_analytics(
    access: WorkspaceMemberDep,
    service: AnalyticsServiceDep,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    timezone: Annotated[str, Query(max_length=64)] = "UTC",
) -> AiAnalytics:
    """What the assistant did, what it cost, and how often it stepped back."""
    window = _window(service, start, end, timezone)

    return AiAnalytics.model_validate(service.ai(access, window))
