import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("")
async def health_check() -> dict[str, str]:
    """The original, kept so existing callers do not break.

    New deployments should use /health/live and /health/ready, which mean
    two different things to an orchestrator.
    """
    return {"status": "ok"}


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Is the process alive?

    Deliberately checks nothing else. If this depended on the database, a
    database blip would make Kubernetes restart every healthy process it
    has, which is the one response that cannot possibly help.
    """
    return {"status": "alive"}


# Sync, like every other route that touches the database.
@router.get("/ready")
def readiness(session: SessionDep) -> JSONResponse:
    """Can this process serve traffic right now?

    Dependencies belong here rather than in liveness: a process that cannot
    reach the database should be taken out of the load balancer until it
    can, not killed and replaced by another one that also cannot.
    """
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("Readiness check failed: the database is unreachable")

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unready", "database": "unreachable"},
        )

    return JSONResponse(content={"status": "ready", "database": "reachable"})
