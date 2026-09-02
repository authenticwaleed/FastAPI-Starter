"""Assembling the platform's aggregate queries as a dependency.

Deliberately not a service. Every other admin phase has one because it
has rules to enforce -- a rank, a grant, a state a workspace has to be in
-- and this one has none: it counts rows and returns numbers.

What it would add is a class that forwarded ten methods and wrote an
audit entry, and the audit entry is one line in the route. So the
repository is the dependency, and the day analytics grows a rule, this is
where the service goes.
"""

from typing import Annotated

from fastapi import Depends

from app.db.session import SessionDep
from app.repositories.platform_analytics_repository import (
    PlatformAnalyticsRepository,
)


def get_platform_analytics_repository(
    session: SessionDep,
) -> PlatformAnalyticsRepository:
    return PlatformAnalyticsRepository(session)


PlatformAnalyticsRepositoryDep = Annotated[
    PlatformAnalyticsRepository,
    Depends(get_platform_analytics_repository),
]
