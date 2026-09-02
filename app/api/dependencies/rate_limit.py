"""Declaring a limit in a route's signature rather than in its body.

The same argument `require_workspace_role` makes. An `if` at the top of a
handler is not hard to write; it is hard to notice missing, and a route
added next month without one looks exactly like a route that is
deliberately unlimited. In the signature it is in the OpenAPI, and leaving
it out is a decision somebody made rather than one nobody made.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.api.dependencies.staff import StaffActorDep
from app.api.dependencies.workspace import WorkspaceAccessDep
from app.core.config import Settings, get_settings
from app.core.rate_limit import Limit, RateLimited, RateLimiter


def limits_from(settings: Settings) -> dict[RateLimited, Limit]:
    """One allowance per scope, so no scope can be left unconfigured."""
    return {
        RateLimited.AUTH: Limit(settings.rate_limit_auth_per_minute, 60),
        RateLimited.EMAIL: Limit(settings.rate_limit_email_per_hour, 3600),
        RateLimited.INVITATIONS: Limit(
            settings.rate_limit_invitations_per_hour,
            3600,
        ),
        RateLimited.AI: Limit(settings.rate_limit_ai_per_minute, 60),
        RateLimited.SEARCH: Limit(settings.rate_limit_search_per_minute, 60),
        RateLimited.UPLOADS: Limit(settings.rate_limit_uploads_per_hour, 3600),
        RateLimited.WEBHOOK_REJECTIONS: Limit(
            settings.rate_limit_webhook_rejections_per_minute,
            60,
        ),
        RateLimited.ADMIN: Limit(settings.rate_limit_admin_per_minute, 60),
    }


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """The counters this process keeps.

    Cached, because the whole point is that the state outlives a request.
    A dependency rather than a module-level object so a test can swap in
    one of its own -- which is also how most of the suite runs with
    limiting off.
    """
    settings = get_settings()

    return RateLimiter(
        limits=limits_from(settings),
        enabled=settings.rate_limit_enabled,
    )


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_address(request: Request) -> str:
    """Who to count against, when there is no account to count against.

    The peer's address, which is the proxy's unless uvicorn is running
    with `--proxy-headers`. Deployments behind a load balancer have to
    set that, or every caller shares one bucket -- which is noted in the
    README next to the rest of the proxy configuration.

    Never the address plus the email that was submitted. Keying on
    somebody else's address is how a limiter becomes a way to lock a
    specific person out of their own account.
    """
    return request.client.host if request.client else "unknown"


def limit_by_client(scope: RateLimited) -> Callable[..., None]:
    """Count this route's requests against the caller's address."""

    def dependency(request: Request, limiter: RateLimiterDep) -> None:
        limiter.spend(scope, client_address(request))

    return dependency


def limit_by_workspace(scope: RateLimited) -> Callable[..., None]:
    """Count this route's requests against the workspace they are for.

    Depends on WorkspaceAccessDep, so membership is established before
    anything is counted: a stranger cannot spend a business's allowance
    by guessing at its id.
    """

    def dependency(access: WorkspaceAccessDep, limiter: RateLimiterDep) -> None:
        limiter.spend(scope, str(access.workspace.id))

    return dependency


def limit_by_staff(scope: RateLimited) -> Callable[..., None]:
    """Count this route's requests against the staff member making them.

    Depends on StaffActorDep, so platform access is established before
    anything is counted -- a signed-in stranger cannot spend a
    colleague's allowance, and cannot learn anything from being refused
    either, because they are refused before the limiter is consulted.

    Against the person rather than the address, unlike the
    unauthenticated endpoints: there is an account here to count, and
    counting on the address instead would put a whole office behind one
    bucket.
    """

    def dependency(actor: StaffActorDep, limiter: RateLimiterDep) -> None:
        limiter.spend(scope, str(actor.user.id))

    return dependency
