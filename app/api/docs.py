"""The interactive documentation, served from this application.

FastAPI's own `/docs` and `/redoc` fetch their JavaScript from a public
CDN, and two things make that the wrong choice here. The first is the
policy this API already sends: `default-src 'none'` tells a browser to
load nothing on the response's behalf, so the CDN script never runs and
the page renders blank -- a white screen and a 200 in the log, which is a
combination that costs an afternoon to read. The second is that a CDN is
a third party learning the address of every deployment that opens the
page, and a network without egress cannot open it at all.

So the assets are vendored under `app/static`, and the pages are declared
here carrying the policy their own content needs. The API's policy does
not move: a JSON response really should load nothing.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_STATIC_PATH = "/static"
_OAUTH2_REDIRECT_PATH = "/docs/oauth2-redirect"

# What these two pages need, and nothing beyond it. `script-src` has to
# admit inline because both generators bootstrap themselves with an inline
# <script>; the stricter alternative, a nonce spliced into markup this
# module does not own, fails back to a blank page the day FastAPI changes
# that markup, which is the exact failure it would be meant to prevent.
# The concession is bounded to these routes, whose content is first-party
# and contains nothing a caller supplied.
_DOCS_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        # The page reads /openapi.json, and "Try it out" calls this same
        # origin. There is nowhere else for it to reach.
        "connect-src 'self'",
        # ReDoc renders inside a worker it builds from a blob.
        "worker-src 'self' blob:",
        "frame-ancestors 'none'",
    )
)


def register_docs(app: FastAPI, *, title: str) -> None:
    """Serve the vendored assets, and the two pages that use them.

    The application must be built with `docs_url=None, redoc_url=None`, so
    that what is registered here is the only version of those paths.
    """
    app.mount(_STATIC_PATH, StaticFiles(directory=STATIC_DIR), name="static")

    openapi_url = app.openapi_url or "/openapi.json"

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return _with_docs_policy(
            get_swagger_ui_html(
                openapi_url=openapi_url,
                title=f"{title} - Swagger UI",
                oauth2_redirect_url=_OAUTH2_REDIRECT_PATH,
                swagger_js_url=f"{_STATIC_PATH}/swagger-ui-bundle.js",
                swagger_css_url=f"{_STATIC_PATH}/swagger-ui.css",
                swagger_favicon_url=f"{_STATIC_PATH}/favicon.png",
            )
        )

    @app.get(_OAUTH2_REDIRECT_PATH, include_in_schema=False)
    async def swagger_ui_redirect() -> HTMLResponse:
        return _with_docs_policy(get_swagger_ui_oauth2_redirect_html())

    @app.get("/redoc", include_in_schema=False)
    async def redoc() -> HTMLResponse:
        return _with_docs_policy(
            get_redoc_html(
                openapi_url=openapi_url,
                title=f"{title} - ReDoc",
                redoc_js_url=f"{_STATIC_PATH}/redoc.standalone.js",
                redoc_favicon_url=f"{_STATIC_PATH}/favicon.png",
                # Otherwise the fonts come from Google, which is the CDN
                # problem again in a smaller shape.
                with_google_fonts=False,
            )
        )


def _with_docs_policy(response: HTMLResponse) -> HTMLResponse:
    # SecurityHeaders adds its headers with setdefault, so that a route
    # which has thought about one of them keeps its own answer. This is
    # the route that has thought about it.
    response.headers["content-security-policy"] = _DOCS_CSP

    return response
