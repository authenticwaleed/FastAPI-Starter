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


class SecurityHeaders:
    """Tell a browser what it may do with this response.

    An API, not a site, which decides most of what is here. Nothing served
    from this application is meant to be rendered, framed, or sniffed for
    a type it did not declare -- so the headers say so, and the ones that
    only make sense for a page with markup in it are absent rather than
    set to a value nobody thought about.

    The edge is still what enforces HTTPS. A proxy terminates TLS and this
    process usually never sees a scheme; what this adds is the instruction
    that makes the *next* request go over TLS too, which is the half a
    redirect cannot do.
    """

    def __init__(self, app: ASGIApp, *, hsts_max_age: int | None) -> None:
        self._app = app
        self._headers = _security_headers(hsts_max_age)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)

            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)

                for name, value in self._headers:
                    # setdefault, so a route that has thought about one of
                    # these keeps its own answer. Nothing does today; the
                    # first one that needs to should not have to edit this.
                    headers.setdefault(name, value)

            await send(message)

        await self._app(scope, receive, with_headers)


def _security_headers(hsts_max_age: int | None) -> tuple[tuple[str, str], ...]:
    headers = [
        # Content-Type is declared on every response this application
        # sends. Without this a browser is free to disagree with the
        # declaration, and an upload echoed back as JSON can be executed
        # as something else entirely.
        ("x-content-type-options", "nosniff"),
        # Nothing here is meant to be framed, and an API in an iframe is
        # somebody else's page borrowing a logged-in session.
        ("x-frame-options", "DENY"),
        # A workspace id in a path should not travel to another origin in
        # a Referer header. `strict-origin-when-cross-origin` is the
        # modern default and this pins it rather than inheriting it.
        ("referrer-policy", "strict-origin-when-cross-origin"),
        # No response from this API needs a camera, a microphone or a
        # location, so none of it is granted -- which is what stops an
        # error page that somehow renders from asking.
        ("permissions-policy", "camera=(), microphone=(), geolocation=()"),
        # This API returns JSON and never markup. `default-src 'none'`
        # says a browser should load nothing at all on its behalf, which
        # is the honest policy for a response nobody should be rendering.
        ("content-security-policy", "default-src 'none'; frame-ancestors 'none'"),
    ]

    if hsts_max_age is not None:
        headers.append(
            (
                "strict-transport-security",
                f"max-age={hsts_max_age}; includeSubDomains",
            )
        )

    return tuple(headers)
