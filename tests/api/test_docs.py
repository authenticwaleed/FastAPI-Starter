"""The documentation pages render without reaching for a third party.

The failure these guard against is quiet: the page returns 200, the log
says nothing is wrong, and the browser shows white, because the policy the
API sends forbade the script the page depends on.
"""

from fastapi.testclient import TestClient

from app.api.docs import STATIC_DIR
from app.core.config import Settings
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
