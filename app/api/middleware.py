"""One line per request, and an identifier that ties everything to it.

Pure ASGI rather than Starlette's BaseHTTPMiddleware, and the reason is
context variables. BaseHTTPMiddleware runs the endpoint in a task of its
own, so anything bound during the request -- the workspace, most usefully
-- never reaches the middleware that writes the summary line. Written this
way they share one context, and the summary says which business the
request was for.

One caveat, because it is not obvious and it is easy to write code that
looks like it works: this holds for anything bound in the request's own
task, which means an asynchronous dependency. FastAPI runs a synchronous
one in a worker thread with a copy of the context, and a binding made
there is thrown away when the thread returns. See
`app/api/dependencies/workspace.py`, where that is why the workspace is
bound by a small async wrapper rather than by the resolver itself.
"""

import logging
import re
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import context

logger = logging.getLogger(__name__)

# The header a caller may use to name its own request, so that a trace
# through a load balancer or a customer's own system carries one id from
# end to end.
REQUEST_ID_HEADER = "x-request-id"

# What an inbound one is allowed to look like. Anything else is replaced
# rather than rejected: this value is written into a log line, and a log
# line is exactly where a newline or an ANSI escape from a stranger does
# damage -- a forged line in the middle of a real one is how an audit
# trail stops being evidence.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Routes that would otherwise be a line each, several times a minute, for
# ever. A container orchestrator polls readiness far more often than
# anybody reads it, and a log where nine lines in ten are health checks is
# one nobody scrolls through.
#
# Written without the `/api/v1` mount prefix, because that is what a
# matched route's own template is: FastAPI keeps an included router nested
# rather than flattening its paths onto the application, so what arrives
# here is the path relative to where the router was mounted.
_QUIET = frozenset({"/health", "/health/live", "/health/ready"})


class RequestContext:
    """Bind a request id, time the request, and log what happened."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)

            return

        request_id = _request_id(scope)
        started = time.perf_counter()
        status = 500

        async def observe(message: Message) -> None:
            nonlocal status

            if message["type"] == "http.response.start":
                status = message["status"]
                # Echoed back so that whoever reports a problem can quote
                # the id, and whoever investigates can find every line the
                # request wrote from that one string.
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id

            await send(message)

        with context.bound(request_id=request_id):
            try:
                await self._app(scope, receive, observe)
            finally:
                # In `finally`, so a request that raised past every
                # handler still leaves a line saying it happened. The
                # status stays 500 in that case, which is what the client
                # got.
                _log(scope, status=status, started=started)


def _request_id(scope: Scope) -> str:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])

    for name, value in headers:
        if name.lower() != REQUEST_ID_HEADER.encode():
            continue

        candidate = value.decode("latin-1", "replace")

        if _SAFE_REQUEST_ID.match(candidate):
            return candidate

        break

    return context.new_request_id()


def _log(scope: Scope, *, status: int, started: float) -> None:
    route = scope.get("route")

    if route is not None and getattr(route, "path", None) in _QUIET:
        return

    logger.info(
        "Request",
        extra={
            "method": scope.get("method", ""),
            # The route's template -- `/workspaces/{workspace_id}/contacts`
            # -- rather than the path that was asked for. Two reasons, and
            # both matter: it is what makes a thousand requests one thing
            # to count, and it is what keeps the invitation token that
            # lives in a path out of the log. A request that matched no
            # route has no template, and its raw path is not logged either.
            "route": getattr(route, "path", "unmatched"),
            "status": status,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    )
