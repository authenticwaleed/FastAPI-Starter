"""Write the API reference as one file somebody can be sent.

    uv run python -m app.docs_cli
    uv run python -m app.docs_cli --output /tmp/baton-api.html
    ./run.sh docs

`/docs` and `/redoc` already exist and are better for the person building
against a running deployment. This is for the person who is not: a
customer's integrator, somebody on a support ticket, a colleague reviewing
the surface on a plane. They get one file that opens in a browser with no
server, no network and no build step, and it is the same schema the
application actually serves rather than a description of it somebody
maintained by hand.

Self-contained is the whole point, so the schema and ReDoc are inlined
rather than referenced. ReDoc is already vendored under `app/static` for
the served page, which is why this adds no dependency: the open-source
package the deployment already ships is the one that renders the file.

The output is deterministic -- no timestamp, no build id -- so that a
diff between two builds is the API changing and nothing else.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from string import Template
from typing import Any

from pydantic import ValidationError

from app.api.docs import STATIC_DIR
from app.core.config import get_settings

# Beside the served page's own bundle, and deliberately the same file. A
# second copy would be a second version, and the reference somebody is
# sent would drift from the one the deployment renders.
BUNDLE = STATIC_DIR / "redoc.standalone.js"

DEFAULT_OUTPUT = Path("docs/api.html")

# The two settings that have no default, filled with values that go
# nowhere. They exist so a checkout with no `.env` can still write the
# reference: the schema is the routes, and neither of these is read to
# produce it. Installed only when the real configuration does not load at
# all, and with `setdefault`, so a deployment's own values always win.
_ENOUGH_TO_RENDER_A_DOCUMENT = {
    "DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/baton",
    "JWT_SECRET_KEY": "unused: this process signs nothing",
}

# What the reader of a static file can use. `expandResponses` is the one
# that earns its place: with no server to call, the response bodies are
# the whole of what this page has to teach, and leaving them collapsed
# hides it behind a click per endpoint.
_REDOC_OPTIONS: dict[str, Any] = {
    "expandResponses": "200,201",
    "hideDownloadButton": False,
    "jsonSampleExpandLevel": 3,
    "sortTagsAlphabetically": False,
}

_PAGE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
  body { margin: 0; }
  #redoc { min-height: 100vh; }
  noscript {
    display: block;
    padding: 2rem;
    font: 16px/1.5 system-ui, -apple-system, sans-serif;
  }
</style>
</head>
<body>
<noscript>
  This reference renders in the browser. Enable JavaScript to read it.
</noscript>
<div id="redoc"></div>
<script type="application/json" id="openapi">$spec</script>
<script>$bundle</script>
<script>
  Redoc.init(
    JSON.parse(document.getElementById("openapi").textContent),
    $options,
    document.getElementById("redoc")
  );
</script>
</body>
</html>
"""
)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)

    if not BUNDLE.is_file():
        sys.stderr.write(
            f"The vendored ReDoc bundle is missing from {BUNDLE}. "
            "The reference is built from it, so restore it first.\n"
        )

        return 2

    output = build(arguments.output)
    size = output.stat().st_size

    sys.stdout.write(f"{output} ({size // 1024} KB, self-contained)\n")

    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.docs_cli",
        description="Write the API reference as one self-contained HTML file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where to write it (default: {DEFAULT_OUTPUT})",
    )

    return parser


def build(output: Path = DEFAULT_OUTPUT) -> Path:
    """Render the reference and put it where it was asked for."""
    page = render(schema(), bundle=BUNDLE.read_text(encoding="utf-8"))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")

    return output


def schema() -> dict[str, Any]:
    """The schema the application would serve, whatever this box is set up as.

    Imported inside the function, and after the check above it, because
    importing `app.main` is not free: that module builds an application
    at import time, which reads settings. At the top of the file it would
    make this module one that cannot be imported without a database URL
    -- and so one CI could not use to check that the reference still
    builds.

    Production is not a special case even though it withholds
    `/openapi.json`. Withholding is about who may read the schema over
    the network; whoever is running this already has the source.
    """
    _ensure_configured()

    from app.main import create_app

    return create_app().openapi()


def _ensure_configured() -> None:
    """Make sure settings will load, without overriding any that do.

    The schema depends on the routes and on the application's name, not
    on where its database is -- so a checkout with no `.env` should still
    be able to produce the reference. Requiring one would mean a
    colleague had to configure Postgres to be sent a document.

    Nothing happens in the ordinary case: a deployment that is configured
    loads its own settings here and the application below reuses them,
    cached, so the title on the document is the one that deployment
    actually answers to.
    """
    try:
        get_settings()
    except ValidationError:
        for name, value in _ENOUGH_TO_RENDER_A_DOCUMENT.items():
            os.environ.setdefault(name, value)


def render(spec: dict[str, Any], *, bundle: str) -> str:
    """The whole page, as a string, with nothing left to fetch."""
    return _PAGE.substitute(
        title=f"{spec['info']['title']} API {spec['info']['version']}",
        spec=_as_embedded_json(spec),
        bundle=_as_embedded_script(bundle),
        options=json.dumps(_REDOC_OPTIONS),
    )


def _as_embedded_json(spec: dict[str, Any]) -> str:
    """The schema, safe to sit inside a <script> element.

    `<` becomes its own escape, which JSON.parse reads back as `<`. That
    is what stops a description containing `</script>` -- a docstring
    quoting HTML, one day -- from closing the element early and leaving
    the rest of the schema on the page as text.
    """
    return json.dumps(spec, separators=(",", ":")).replace("<", "\\u003c")


def _as_embedded_script(source: str) -> str:
    """The bundle, safe to sit inside a <script> element.

    Today's vendored bundle contains no `</script`, so this changes
    nothing. It is here for the upgrade that introduces one, because the
    failure would be a blank page with no error anywhere -- the same
    quiet failure the vendoring in `app/api/docs.py` exists to avoid.
    """
    return source.replace("</script", "<\\/script")


if __name__ == "__main__":
    raise SystemExit(main())
