"""The documentation pages render without reaching for a third party.

The failure these guard against is quiet: the page returns 200, the log
says nothing is wrong, and the browser shows white, because the policy the
API sends forbade the script the page depends on.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.docs import STATIC_DIR
from app.core.config import Settings
from app.docs_cli import (
    _ENOUGH_TO_RENDER_A_DOCUMENT,
    BUNDLE,
    build,
    render,
    schema,
)
from app.main import create_app

VENDORED = (
    "swagger-ui-bundle.js",
    "swagger-ui.css",
    "redoc.standalone.js",
    "favicon.png",
)


def test_every_vendored_asset_is_present() -> None:
    missing = [name for name in VENDORED if not (STATIC_DIR / name).is_file()]

    assert not missing, f"missing vendored assets: {missing}"


def test_swagger_ui_is_served(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_redoc_is_served(client: TestClient) -> None:
    response = client.get("/redoc")

    assert response.status_code == 200


def test_the_oauth2_redirect_page_is_served(client: TestClient) -> None:
    response = client.get("/docs/oauth2-redirect")

    assert response.status_code == 200


def test_the_pages_load_nothing_from_another_origin(client: TestClient) -> None:
    """No cdn.jsdelivr.net, no fonts.googleapis.com, no favicon from a docs site."""
    for path in ("/docs", "/redoc"):
        body = client.get(path).text

        assert "cdn.jsdelivr.net" not in body, path
        assert "fonts.googleapis.com" not in body, path
        assert "fastapi.tiangolo.com" not in body, path


def test_the_assets_the_pages_ask_for_are_actually_served(client: TestClient) -> None:
    for name in VENDORED:
        response = client.get(f"/static/{name}")

        assert response.status_code == 200, name
        assert response.content, name


def test_the_documentation_relaxes_the_policy_only_for_itself(
    client: TestClient,
) -> None:
    """`default-src 'none'` blanks these pages, so they carry their own."""
    for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        policy = client.get(path).headers["content-security-policy"]

        assert "default-src 'self'" in policy, path
        assert "script-src 'self' 'unsafe-inline'" in policy, path
        assert "default-src 'none'" not in policy, path


def test_the_api_keeps_the_strict_policy(client: TestClient) -> None:
    policy = client.get("/api/v1/health").headers["content-security-policy"]

    assert policy == "default-src 'none'; frame-ancestors 'none'"


def test_the_documentation_stays_out_of_the_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for path in ("/docs", "/redoc", "/docs/oauth2-redirect", "/static"):
        assert path not in paths


def _production_app_client() -> TestClient:
    """Production, configured well enough to actually start."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="production",
        debug=False,
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        jwt_secret_key="a-signing-key-long-enough-to-be-plausible",
        encryption_key="8GkQ0DPTPzY3RtsDcRUv0YyBFqPLmPqXbYtdzwXQvbA=",
        smtp_host="smtp.example.com",
        email_from="no-reply@example.com",
        frontend_base_url="https://app.example.com",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
    )

    return TestClient(create_app(settings), base_url="https://app.example.com")


def test_production_serves_no_documentation() -> None:
    client = _production_app_client()

    for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path


def test_production_withholds_the_schema_as_well() -> None:
    """A hidden page and a readable schema would hide nothing."""
    assert _production_app_client().get("/openapi.json").status_code == 404


def test_production_does_not_serve_the_documentation_assets() -> None:
    assert (
        _production_app_client().get("/static/swagger-ui-bundle.js").status_code == 404
    )


# --- the reference somebody can be sent ------------------------------------
#
# Same failure as the pages above, one step worse: a file that has to
# fetch something opens blank on the aeroplane it was sent for, and there
# is no log to say so.

_MINIMAL_SPEC = {"info": {"title": "Baton", "version": "0.1.0"}, "paths": {}}


def test_the_reference_builds_to_a_single_file(tmp_path: Path) -> None:
    output = build(tmp_path / "api.html")

    assert output.is_file()
    # The bundle is inlined rather than linked, so the file is at least
    # as large as it is. Anything much smaller means it was referenced.
    assert output.stat().st_size > BUNDLE.stat().st_size


def test_the_reference_has_nothing_left_to_fetch(tmp_path: Path) -> None:
    page = build(tmp_path / "api.html").read_text(encoding="utf-8")

    assert "<script src" not in page
    assert "<link rel" not in page
    assert "fonts.googleapis.com" not in page
    assert "cdn.jsdelivr.net" not in page


def test_the_reference_carries_the_schema_the_application_serves() -> None:
    page = render(schema(), bundle="/* bundle */")

    for path in ("/api/v1/health/ready", "/api/v1/plans", "/api/v1/admin/staff"):
        assert path in page, path


def test_a_description_quoting_a_script_tag_cannot_break_out() -> None:
    """The quiet one: the element closes early and the rest lands as text."""
    spec = {**_MINIMAL_SPEC, "paths": {"/x": {"description": "</script><b>hi</b>"}}}

    page = render(spec, bundle="/* bundle */")

    assert "</script><b>" not in page
    assert "\\u003c/script" in page


def test_a_bundle_quoting_a_script_tag_cannot_close_the_element() -> None:
    page = render(_MINIMAL_SPEC, bundle='var t = "</script>";')

    assert '"</script>"' not in page
    assert '"<\\/script>"' in page


def test_the_stand_in_settings_cover_everything_with_no_default() -> None:
    """Otherwise an unconfigured checkout stops being able to build this.

    The failure is a new required setting added months from now, which
    nothing else here would notice: the reference still builds on every
    developer's machine, and only CI and the colleague with a fresh
    clone are told they need a database to be sent a document.
    """
    required = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.is_required()
    }

    assert required == set(_ENOUGH_TO_RENDER_A_DOCUMENT)


def test_the_page_is_the_same_twice() -> None:
    """No timestamp, so a diff between builds is the API and nothing else."""
    assert render(schema(), bundle="/* bundle */") == render(
        schema(), bundle="/* bundle */"
    )
