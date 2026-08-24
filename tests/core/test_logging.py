"""Phase 10 acceptance: real logging, controlled by the environment, with
nothing secret in it."""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter, configure_logging
from app.main import create_app


@contextmanager
def capture(level: int = logging.DEBUG) -> Iterator[list[logging.LogRecord]]:
    """Collect records from the root logger.

    pytest's own caplog fixture installs a handler on the root logger, and
    configure_logging() replaces root's handlers wholesale, so caplog stops
    hearing anything the moment an app is built. Attaching after the fact
    sidesteps that.
    """
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect(level=level)
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        yield records
    finally:
        root.removeHandler(handler)


def _messages(records: list[logging.LogRecord]) -> str:
    return "\n".join(record.getMessage() for record in records)


def test_the_root_level_comes_from_settings() -> None:
    configure_logging()

    expected = logging.getLevelName(get_settings().log_level)

    assert logging.getLogger().level == expected


def test_the_level_is_normalised() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_an_unknown_level_is_rejected_at_startup() -> None:
    # Better than accepting it and silently logging nothing all day.
    with pytest.raises(ValidationError):
        Settings(log_level="LOUD")


def test_logging_goes_to_stdout() -> None:
    configure_logging()

    (handler,) = logging.getLogger().handlers

    assert isinstance(handler, logging.StreamHandler)
    # Compared by identity rather than by name: under pytest sys.stdout is a
    # capture object, and asserting on "<stdout>" would test pytest instead.
    assert handler.stream is sys.stdout


def test_startup_and_shutdown_are_logged() -> None:
    app = create_app()

    with capture(logging.INFO) as records, TestClient(app):
        pass

    text = _messages(records)

    assert "Starting" in text
    assert "Shutting down" in text


def test_startup_does_not_log_the_configuration() -> None:
    settings = get_settings()
    app = create_app()

    with capture(logging.DEBUG) as records, TestClient(app):
        pass

    text = _messages(records)

    assert settings.jwt_secret_key.get_secret_value() not in text
    assert str(settings.database_url) not in text


def test_a_rejected_request_is_logged(client: TestClient) -> None:
    with capture(logging.WARNING) as records:
        client.get("/api/v1/users/999")

    assert "User not found: 999" in _messages(records)


def test_a_failed_login_is_logged(client: TestClient) -> None:
    with capture(logging.WARNING) as records:
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong password"},
        )

    assert "/api/v1/auth/login failed" in _messages(records)


def test_a_failed_login_does_not_log_the_password(client: TestClient) -> None:
    password = "the password that was tried"

    with capture(logging.DEBUG) as records:
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": password},
        )

    assert password not in _messages(records)


def test_an_unexpected_error_is_logged_with_its_traceback() -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("the cause")

    with (
        capture(logging.ERROR) as records,
        TestClient(app, raise_server_exceptions=False) as boom_client,
    ):
        boom_client.get("/boom")

    # The trace the client is not given has to be somewhere, and this is it.
    assert any(record.exc_info for record in records)
    assert "Unhandled error on GET /boom" in _messages(records)


def test_no_secret_reaches_the_log(client: TestClient) -> None:
    settings = get_settings()
    password = urlsplit(str(settings.database_url)).password or ""

    with capture(logging.DEBUG) as records:
        client.post(
            "/api/v1/users",
            json={
                "name": "Ada",
                "email": "ada@example.com",
                "password": "correct horse battery staple",
            },
        )
        client.post(
            "/api/v1/auth/login",
            json={"email": "ada@example.com", "password": "wrong"},
        )
        client.get("/api/v1/users/999")

    text = _messages(records)

    assert settings.jwt_secret_key.get_secret_value() not in text
    assert password not in text
    assert "correct horse battery staple" not in text


def test_the_application_does_not_debug_with_print() -> None:
    for module in sorted(Path("app").rglob("*.py")):
        assert "print(" not in module.read_text(), module


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        jwt_secret_key="a-signing-key-long-enough-to-be-plausible",
        **overrides,
    )


def test_development_logs_as_text() -> None:
    assert _settings(environment="development").log_format == "text"


def test_production_logs_as_json_without_being_told() -> None:
    settings = _settings(
        environment="production",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["api.example.com"],
    )

    assert settings.log_format == "json"


def test_an_explicit_format_wins_over_the_environment() -> None:
    settings = _settings(
        environment="production",
        log_format="text",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["api.example.com"],
    )

    assert settings.log_format == "text"


def test_json_records_are_one_object_per_line() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "WARNING"
    assert payload["logger"] == "app.test"
    # Interpolated, so a consumer never has to reassemble it.
    assert payload["message"] == "hello world"
    assert payload["timestamp"]


def test_a_json_record_carries_its_traceback() -> None:
    try:
        raise ValueError("the cause")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="it broke",
        args=(),
        exc_info=exc_info,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: the cause" in payload["exception"]
