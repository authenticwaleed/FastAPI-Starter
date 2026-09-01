"""Phase 29 acceptance: being able to tell what happened, afterwards.

Three things the phase asks for. Structured logging with identifiers is
most of this file. The metrics are the same lines with a measurement on
them, so they are tested the same way. Tracing is deliberately absent, and
the plan says why.

The test that matters most is the last group: what must never reach a log
line. The existing suite already pins passwords and invitation tokens; what
is new here is that the identifiers themselves cannot become a way in --
the context takes five named fields and nothing else, and a request id
somebody else chose is not written down unless it looks like an identifier.
"""

import json
import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.middleware import REQUEST_ID_HEADER
from app.core import context
from app.core.exceptions import MessagingProviderError
from app.core.logging import ContextFilter, JsonFormatter
from app.core.observability import observed
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.tenants import Tenant


class Collector(logging.Handler):
    """A handler wired the way the real one is.

    The context filter lives on the handler in production, deliberately --
    it is how lines from uvicorn and SQLAlchemy get identifiers too. That
    means `caplog`, whose handler has no such filter, never sees them: a
    test asserting on caplog would be asserting about a record that never
    reached a formatter. So this collects through a handler that is
    arranged like the real one.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.addFilter(ContextFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def From(self, name: str) -> list[logging.LogRecord]:
        return [record for record in self.records if record.name == name]

    def last(self, name: str) -> logging.LogRecord:
        written = self.From(name)
        assert written, f"nothing logged by {name}"

        return written[-1]


@pytest.fixture
def logged() -> Iterator[Collector]:
    handler = Collector()
    root = logging.getLogger()
    was = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(was)


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Something happened",
        args=(),
        exc_info=None,
    )

    for key, value in extra.items():
        setattr(record, key, value)

    ContextFilter().filter(record)

    return record


def _rendered(record: logging.LogRecord) -> dict:
    return dict(json.loads(JsonFormatter().format(record)))


# --- the identifiers --------------------------------------------------------


def test_a_line_written_with_nothing_bound_says_nothing_extra() -> None:
    rendered = _rendered(_record())

    assert rendered["message"] == "Something happened"
    assert set(rendered) == {"timestamp", "level", "logger", "message"}


def test_bound_identifiers_reach_the_line() -> None:
    workspace = uuid.uuid4()

    with context.bound(request_id="abc123", workspace_id=workspace):
        rendered = _rendered(_record())

    assert rendered["request_id"] == "abc123"
    assert rendered["workspace_id"] == str(workspace)


def test_they_are_top_level_so_an_aggregator_can_filter_on_them() -> None:
    with context.bound(workspace_id="w"):
        rendered = _rendered(_record())

    assert "workspace_id" in rendered
    assert "fields" not in rendered


def test_a_binding_is_put_back_when_the_block_ends() -> None:
    """An outbound call binds an integration; the lines after it are not
    about that call any more."""
    with context.bound(request_id="outer"):
        with context.bound(integration="whatsapp", operation="send_text"):
            assert context.current()["integration"] == "whatsapp"

        assert "integration" not in context.current()
        assert context.current()["request_id"] == "outer"

    assert context.current() == {}


def test_a_nested_binding_keeps_what_was_already_there() -> None:
    with (
        context.bound(request_id="r", workspace_id="w"),
        context.bound(conversation_id="c"),
    ):
        bound = dict(context.current())

    assert bound == {"request_id": "r", "workspace_id": "w", "conversation_id": "c"}


def test_nothing_but_the_five_can_be_bound() -> None:
    """The plan's list, as a signature rather than as a convention.

    This is what "avoid sensitive contents by default" looks like when it
    is a property of the code: there is no argument to pass a message body
    or an access token as.
    """
    with pytest.raises(TypeError):
        context.bind(password="hunter2")  # type: ignore[call-arg]


def test_an_identifier_that_is_not_supplied_is_absent_rather_than_empty() -> None:
    with context.bound(workspace_id="w", conversation_id=None):
        assert "conversation_id" not in context.current()


# --- the measurements -------------------------------------------------------


def test_an_outbound_call_is_timed_and_called_a_success(
    logged: Collector,
) -> None:
    with observed("whatsapp", "send_text"):
        pass

    fields = logged.last("app.core.observability").fields

    assert fields["outcome"] == "ok"
    assert fields["duration_ms"] >= 0
    assert fields["integration"] == "whatsapp"
    assert fields["operation"] == "send_text"


def test_a_failed_call_is_timed_too_and_says_what_kind_of_failure(
    logged: Collector,
) -> None:
    with pytest.raises(MessagingProviderError), observed("whatsapp", "send_text"):
        raise MessagingProviderError("the provider could not be reached")

    fields = logged.last("app.core.observability").fields

    assert fields["outcome"] == "error"
    assert fields["error"] == "MessagingProviderError"


def test_a_failed_call_never_logs_what_the_provider_said(
    logged: Collector,
) -> None:
    """A provider's own words can carry a phone number or a token."""
    secret = "+923001234567 rejected: token=abcdef"

    with pytest.raises(MessagingProviderError), observed("whatsapp", "send_text"):
        raise MessagingProviderError(secret)

    written = json.dumps(
        [
            {**record.fields, "message": record.getMessage()}
            for record in logged.From("app.core.observability")
        ]
    )

    assert secret not in written
    assert "923001234567" not in written


def test_the_call_is_not_swallowed() -> None:
    with pytest.raises(ValueError), observed("anthropic", "messages.parse"):
        raise ValueError("this must reach the caller")


def test_a_measurement_reaches_the_line() -> None:
    rendered = _rendered(_record(duration_ms=42, outcome="ok"))

    assert (rendered["duration_ms"], rendered["outcome"]) == (42, "ok")


def test_an_attribute_nobody_named_does_not() -> None:
    """The formatter ships named measurements, not whatever was attached.

    A formatter that serialised every attribute would ship whatever the
    next person passed as `extra`, which is the same hole `bind` closes at
    the other end.
    """
    rendered = _rendered(_record(access_token="lp_secret"))

    assert "access_token" not in rendered
    assert "lp_secret" not in json.dumps(rendered)


# --- one request, one identifier --------------------------------------------


def test_a_response_carries_the_id_its_lines_were_written_under(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_two_requests_get_two_identifiers(client: TestClient) -> None:
    first = client.get("/api/v1/health").headers[REQUEST_ID_HEADER]
    second = client.get("/api/v1/health").headers[REQUEST_ID_HEADER]

    assert first != second


def test_a_callers_own_identifier_is_kept(client: TestClient) -> None:
    """So a trace through a load balancer carries one id end to end."""
    response = client.get(
        "/api/v1/health",
        headers={REQUEST_ID_HEADER: "trace-from-the-edge_01"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "trace-from-the-edge_01"


@pytest.mark.parametrize(
    "forged",
    [
        "line\nINFO fake log line",
        "\x1b[31mred",
        "x" * 65,
        "",
        "has spaces",
    ],
)
def test_an_identifier_that_could_forge_a_line_is_replaced(
    client: TestClient,
    forged: str,
) -> None:
    """A forged line in the middle of a real one is how a trail stops
    being evidence."""
    response = client.get("/api/v1/health", headers={REQUEST_ID_HEADER: forged})

    returned = response.headers[REQUEST_ID_HEADER]
    assert returned != forged
    assert len(returned) == 32


def test_a_request_is_logged_with_its_route_and_how_long_it_took(
    client: TestClient,
    logged: Collector,
) -> None:
    client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "no"})

    fields = logged.last("app.api.middleware").fields

    assert fields["method"] == "POST"
    assert fields["route"] == "/auth/login"
    assert fields["status"] == 401
    assert fields["duration_ms"] >= 0
    # The line the client can quote back is the line that explains it.
    assert fields["request_id"]


def test_health_checks_do_not_fill_the_log(
    client: TestClient,
    logged: Collector,
) -> None:
    """An orchestrator polls readiness far more often than anybody reads it."""
    client.get("/api/v1/health/ready")

    assert logged.From("app.api.middleware") == []


def test_a_path_with_a_token_in_it_is_logged_as_its_route(
    client: TestClient,
    logged: Collector,
) -> None:
    """The template, not the path. A log is where a secret gets kept longest."""
    client.get("/api/v1/invitations/a-real-looking-token")

    fields = logged.last("app.api.middleware").fields

    assert fields["route"] == "/invitations/{token}"
    assert "a-real-looking-token" not in json.dumps(fields)


def test_a_request_that_matched_no_route_logs_no_path(
    client: TestClient,
    logged: Collector,
) -> None:
    client.get("/api/v1/there-is-no-such-thing/secret-looking-value")

    fields = logged.last("app.api.middleware").fields

    assert fields["route"] == "unmatched"
    assert "secret-looking-value" not in json.dumps(fields)


def test_a_tenant_request_says_which_business_it_was_for(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    logged: Collector,
) -> None:
    """Bound once in the dependency every tenant route already goes through.

    The summary line is written by the middleware, outside the endpoint,
    and still has it -- which is the reason that middleware is pure ASGI
    rather than a BaseHTTPMiddleware with a task of its own.
    """
    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")

    client.get(tenant.path("contacts"), headers=tenant.owner_headers)

    assert logged.last("app.api.middleware").fields["workspace_id"] == (
        tenant.workspace_id
    )


def test_a_workspace_somebody_guessed_at_is_not_logged_as_theirs(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    logged: Collector,
) -> None:
    """Bound after the check, never before."""
    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")
    stranger = Tenant(client, user_repository, membership_repository, "rival-store")

    response = client.get(tenant.path("contacts"), headers=stranger.owner_headers)

    assert response.status_code == 404
    fields = logged.last("app.api.middleware").fields
    assert fields.get("workspace_id") != tenant.workspace_id
