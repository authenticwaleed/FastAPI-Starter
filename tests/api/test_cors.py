"""Phase 12 acceptance: cross-origin access and host checks come from
configuration, and production is held to a stricter standard than a laptop."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

ORIGIN = "http://localhost:3000"
OTHER = "http://somewhere-else.example"


def _settings(**overrides: object) -> Settings:
    # _env_file=None so a value in the developer's .env cannot change what
    # these tests are asserting about.
    #
    # Production refuses to start without an encryption key, somewhere to
    # send mail, and somewhere for the links in it to point, so all four
    # are supplied by default -- as defaults rather than fixed values, so
    # a test can still assert what happens without one.
    defaults: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5432/db",
        "jwt_secret_key": "a-signing-key-long-enough-to-be-plausible",
        "encryption_key": "8GkQ0DPTPzY3RtsDcRUv0YyBFqPLmPqXbYtdzwXQvbA=",
        "smtp_host": "smtp.example.com",
        "email_from": "no-reply@example.com",
        "frontend_base_url": "https://app.example.com",
    }

    return Settings(_env_file=None, **(defaults | overrides))  # type: ignore[arg-type]


def _client(**overrides: object) -> TestClient:
    return TestClient(create_app(_settings(**overrides)))


def test_a_configured_origin_is_allowed() -> None:
    client = _client(cors_origins=[ORIGIN])

    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN


def test_an_unconfigured_origin_is_not() -> None:
    client = _client(cors_origins=[ORIGIN])

    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": OTHER,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_no_configured_origins_means_no_cross_origin_access() -> None:
    client = _client(cors_origins=[])

    response = client.get("/api/v1/health", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_credentials_are_advertised_when_enabled() -> None:
    client = _client(cors_origins=[ORIGIN], cors_allow_credentials=True)

    response = client.get("/api/v1/health", headers={"Origin": ORIGIN})

    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_the_allowed_methods_are_named_rather_than_wildcarded() -> None:
    client = _client(cors_origins=[ORIGIN])

    response = client.options(
        "/api/v1/health",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    allowed = response.headers["Access-Control-Allow-Methods"]

    assert "*" not in allowed
    assert "TRACE" not in allowed


def test_origins_can_be_given_as_a_comma_separated_string() -> None:
    settings = _settings(cors_origins=f"{ORIGIN}, {OTHER}")

    assert settings.cors_origins == [ORIGIN, OTHER]


def test_origins_can_still_be_given_as_json() -> None:
    settings = _settings(cors_origins=f'["{ORIGIN}"]')

    assert settings.cors_origins == [ORIGIN]


def test_an_unknown_host_header_is_rejected() -> None:
    client = _client(allowed_hosts=["api.example.com"])

    response = client.get("/api/v1/health", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_a_known_host_header_is_accepted() -> None:
    client = _client(allowed_hosts=["api.example.com"])

    response = client.get("/api/v1/health", headers={"Host": "api.example.com"})

    assert response.status_code == 200


def test_a_wildcard_origin_with_credentials_is_refused() -> None:
    # Browsers will not honour it, so accepting the configuration would only
    # hide the mistake until someone tried to use it.
    with pytest.raises(ValidationError):
        _settings(cors_origins=["*"], cors_allow_credentials=True)


def test_production_refuses_debug() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="production", debug=True)


def test_production_refuses_a_wildcard_origin() -> None:
    with pytest.raises(ValidationError):
        _settings(
            environment="production",
            cors_origins=["*"],
            cors_allow_credentials=False,
        )


def test_production_refuses_a_wildcard_host() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="production", allowed_hosts=["*"])


def test_development_allows_what_production_refuses() -> None:
    # The same settings object, judged differently by environment.
    settings = _settings(environment="development", debug=True)

    assert settings.debug is True
    assert settings.allowed_hosts == ["*"]


def test_production_is_satisfied_by_explicit_values() -> None:
    settings = _settings(
        environment="production",
        debug=False,
        cors_origins=["https://app.example.com"],
        allowed_hosts=["api.example.com"],
    )

    assert settings.is_production
    assert not settings.is_development


def test_an_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="prod")


@pytest.mark.parametrize(
    "missing",
    ["smtp_host", "email_from", "frontend_base_url"],
)
def test_production_refuses_to_start_without_a_way_to_send_mail(
    missing: str,
) -> None:
    # Without these, verification and password reset do not fail -- they
    # appear to work while the link goes to a log file, or goes out with
    # no page to click through to. Refusing to start is the only outcome
    # that cannot be mistaken for working.
    with pytest.raises(ValidationError):
        _settings(
            environment="production",
            cors_origins=["https://app.example.com"],
            allowed_hosts=["api.example.com"],
            **{missing: None},
        )


def test_a_blank_smtp_host_counts_as_missing() -> None:
    # A compose file writing `SMTP_HOST: ${SMTP_HOST:-}` produces an empty
    # string, and treating that as configured would start a deployment
    # that cannot send anything.
    assert _settings(smtp_host="   ").smtp_host is None


def test_the_signing_key_must_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No default, so a deployment that forgets it fails at startup rather
    # than signing tokens with something published in the repository.
    #
    # _env_file=None only skips .env; os.environ is still a source. CI
    # exports JWT_SECRET_KEY for the application, so without clearing it
    # here the field is satisfied and this asserts nothing at all.
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost:5432/db",
        )


def test_the_signing_key_is_masked_in_a_repr() -> None:
    settings = _settings()

    assert "a-signing-key-long-enough-to-be-plausible" not in repr(settings)


def test_origins_parse_the_same_way_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The form .env.example documents. pydantic-settings would otherwise
    # insist this were JSON and fail at startup.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-signing-key-long-enough-to-be-plausible")
    monkeypatch.setenv("CORS_ORIGINS", f"{ORIGIN},{OTHER}")
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com, localhost")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [ORIGIN, OTHER]
    assert settings.allowed_hosts == ["api.example.com", "localhost"]


def test_a_malformed_json_list_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        _settings(cors_origins='["unclosed')


def test_a_blank_secret_counts_as_missing() -> None:
    # A compose file writing `KEY: ${KEY:-}` produces an empty string, not
    # an absent variable. Without this it would arrive as SecretStr("") --
    # not None, so the production check would pass and the deployment
    # would start with a key that cannot encrypt anything.
    assert _settings(encryption_key="").encryption_key is None
    assert _settings(whatsapp_app_secret="   ").whatsapp_app_secret is None


def test_production_refuses_a_blank_encryption_key() -> None:
    with pytest.raises(ValidationError):
        _settings(
            environment="production",
            cors_origins=["https://app.example.com"],
            allowed_hosts=["app.example.com"],
            encryption_key="",
        )


def test_production_refuses_a_missing_encryption_key() -> None:
    # Storing a provider's access token in plain text is the kind of
    # mistake only found by somebody reading the table.
    #
    # Passed as None rather than left out: the suite sets ENCRYPTION_KEY
    # in the environment, and pydantic-settings reads that whatever
    # _env_file says, so omitting it here would not mean missing.
    with pytest.raises(ValidationError):
        _settings(
            environment="production",
            cors_origins=["https://app.example.com"],
            allowed_hosts=["app.example.com"],
            encryption_key=None,
        )
