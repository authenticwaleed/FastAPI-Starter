"""Phase 14 acceptance: the numbers a business is shown about its own inbox.

The plan's criterion is "dashboard metrics correct", which is only worth
anything if the arithmetic is checked against a known arrangement of rows
rather than against itself. So each test builds a small, countable
situation and asserts the figure a person would arrive at by hand.

The two that are easy to get wrong and hard to notice are here as well:
the range is inclusive at both ends, and the days are the business's days
rather than UTC's.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.contact import ContactStatus
from app.models.conversation import Channel, ConversationStatus
from app.models.message import Direction, MessageStatus, SenderType
from app.models.workspace_membership import WorkspaceRole
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)

PASSWORD = "correct horse battery staple"


def _sign_up(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Someone", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


class Business:
    """A workspace whose rows are written directly, at chosen times.

    Through the repositories rather than the API, because these tests are
    about arithmetic over a known arrangement: a message has to be able to
    have happened last Tuesday, and no endpoint lets it.
    """

    def __init__(
        self,
        client: TestClient,
        session: Session,
        memberships: WorkspaceMembershipRepository,
        slug: str,
    ) -> None:
        self._client = client
        self._session = session
        self._memberships = memberships
        self._contacts = ContactRepository(session)
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._people = 0

        self.headers = _sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = uuid.UUID(
            client.post(
                "/api/v1/workspaces",
                json={"name": slug.title(), "slug": slug},
                headers=self.headers,
            ).json()["id"]
        )

    def member(self, email: str, role: WorkspaceRole) -> dict[str, str]:
        headers = _sign_up(self._client, email)
        user = self._client.get("/api/v1/auth/me", headers=headers).json()
        self._memberships.create(
            workspace_id=self.workspace_id,
            user_id=user["id"],
            role=role,
        )

        return headers

    def conversation(
        self,
        *,
        at: datetime,
        status: ConversationStatus = ConversationStatus.OPEN,
    ) -> uuid.UUID:
        self._people += 1
        contact = self._contacts.create(
            workspace_id=self.workspace_id,
            phone_number=f"+92300{self._people:07d}",
            name=None,
            email=None,
            status=ContactStatus.LEAD,
            source=None,
            external_id=None,
            meta={},
        )
        conversation = self._conversations.create(
            workspace_id=self.workspace_id,
            contact_id=contact.id,
            channel=Channel.WHATSAPP,
        )
        conversation.created_at = at

        if status != ConversationStatus.OPEN:
            self._conversations.set_status(
                conversation,
                status,
                closed_at=at if status == ConversationStatus.CLOSED else None,
            )

        self._session.flush()

        return conversation.id

    def said(
        self,
        conversation_id: uuid.UUID,
        *,
        at: datetime,
        by: SenderType = SenderType.CUSTOMER,
    ) -> None:
        inbound = by == SenderType.CUSTOMER
        message = self._messages.create(
            workspace_id=self.workspace_id,
            conversation_id=conversation_id,
            sender_type=by,
            direction=Direction.INBOUND if inbound else Direction.OUTBOUND,
            channel=Channel.WHATSAPP,
            status=MessageStatus.RECEIVED if inbound else MessageStatus.SENT,
            text="something",
        )
        message.created_at = at
        self._session.flush()

    def analytics(self, what: str = "overview", **params: Any) -> dict[str, Any]:
        self._session.commit()
        response = self._client.get(
            f"/api/v1/workspaces/{self.workspace_id}/analytics/{what}",
            params=params,
            headers=self.headers,
        )
        assert response.status_code == 200, response.text

        return response.json()


@pytest.fixture
def acme(
    client: TestClient,
    db_session: Session,
    membership_repository: WorkspaceMembershipRepository,
) -> Business:
    return Business(client, db_session, membership_repository, "acme-fashion")


@pytest.fixture
def rival(
    client: TestClient,
    db_session: Session,
    membership_repository: WorkspaceMembershipRepository,
) -> Business:
    return Business(client, db_session, membership_repository, "rival-store")


def _at(day: str, hour: int = 12) -> datetime:
    year, month, date_ = (int(part) for part in day.split("-"))

    return datetime(year, month, date_, hour, tzinfo=UTC)


RANGE = {"start": "2026-06-01", "end": "2026-06-30"}


# --- conversations ----------------------------------------------------------


def test_the_totals_count_what_is_there(client: TestClient, acme: Business) -> None:
    acme.conversation(at=_at("2026-06-02"))
    acme.conversation(at=_at("2026-06-03"))
    acme.conversation(at=_at("2026-06-04"), status=ConversationStatus.CLOSED)
    acme.conversation(at=_at("2026-06-05"), status=ConversationStatus.PENDING)

    totals = acme.analytics("conversations", **RANGE)["totals"]

    assert totals["total"] == 4
    assert totals["open"] == 2
    assert totals["closed"] == 1
    assert totals["pending"] == 1
    assert totals["unassigned"] == 4


def test_every_day_of_the_range_appears_including_the_empty_ones(
    client: TestClient,
    acme: Business,
) -> None:
    # A chart drawn only from the days that had activity makes a quiet
    # week look like a busy one with fewer points.
    acme.conversation(at=_at("2026-06-02"))
    acme.conversation(at=_at("2026-06-02"))
    acme.conversation(at=_at("2026-06-05"))

    by_day = acme.analytics(
        "conversations",
        start="2026-06-01",
        end="2026-06-05",
    )["by_day"]

    assert [point["day"] for point in by_day] == [
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
        "2026-06-04",
        "2026-06-05",
    ]
    assert [point["count"] for point in by_day] == [0, 2, 0, 0, 1]


def test_both_ends_of_the_range_are_included(
    client: TestClient,
    acme: Business,
) -> None:
    # Somebody asking for the 1st to the 7th means the 7th as well. An
    # off-by-one here silently drops a day from every report.
    acme.conversation(at=_at("2026-06-01", hour=0))
    acme.conversation(at=_at("2026-06-07", hour=23))
    acme.conversation(at=_at("2026-06-08", hour=0))

    totals = acme.analytics(
        "conversations",
        start="2026-06-01",
        end="2026-06-07",
    )["totals"]

    assert totals["total"] == 2


def test_the_days_are_the_businesss_days_not_utcs(
    client: TestClient,
    acme: Business,
) -> None:
    # Nine in the evening in Karachi is four in the afternoon UTC on the
    # same day; eight in the evening UTC is one in the morning the next
    # day there. A shop's last conversation of the day belongs to that day.
    acme.conversation(at=_at("2026-06-02", hour=20))

    utc = acme.analytics("conversations", start="2026-06-01", end="2026-06-05")
    karachi = acme.analytics(
        "conversations",
        start="2026-06-01",
        end="2026-06-05",
        timezone="Asia/Karachi",
    )

    assert {p["day"]: p["count"] for p in utc["by_day"]}["2026-06-02"] == 1
    assert {p["day"]: p["count"] for p in karachi["by_day"]}["2026-06-03"] == 1


def test_a_timezone_nobody_has_heard_of_is_refused(
    client: TestClient,
    acme: Business,
) -> None:
    # Refused rather than quietly falling back to UTC, which is wrong in a
    # way nobody notices until they count by hand.
    response = client.get(
        f"/api/v1/workspaces/{acme.workspace_id}/analytics/overview",
        params={"timezone": "Mars/Olympus_Mons"},
        headers=acme.headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_timezone"


def test_a_backwards_range_is_refused(client: TestClient, acme: Business) -> None:
    response = client.get(
        f"/api/v1/workspaces/{acme.workspace_id}/analytics/overview",
        params={"start": "2026-06-30", "end": "2026-06-01"},
        headers=acme.headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_date_range"


def test_a_range_longer_than_a_year_is_refused(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.get(
        f"/api/v1/workspaces/{acme.workspace_id}/analytics/overview",
        params={"start": "2020-01-01", "end": "2026-06-01"},
        headers=acme.headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_date_range"


# --- messages and response time ---------------------------------------------


def test_messages_are_counted_by_who_sent_them(
    client: TestClient,
    acme: Business,
) -> None:
    conversation = acme.conversation(at=_at("2026-06-02"))
    acme.said(conversation, at=_at("2026-06-02", 9))
    acme.said(conversation, at=_at("2026-06-02", 10), by=SenderType.AGENT)
    acme.said(conversation, at=_at("2026-06-02", 11), by=SenderType.AI)
    acme.said(conversation, at=_at("2026-06-02", 12), by=SenderType.AI)

    messages = acme.analytics(**RANGE)["messages"]

    assert messages["total"] == 4
    assert messages["received"] == 1
    assert messages["sent"] == 3
    assert messages["by_ai"] == 2
    assert messages["by_agents"] == 1


def test_the_first_response_time_is_the_wait_the_customer_felt(
    client: TestClient,
    acme: Business,
) -> None:
    first = acme.conversation(at=_at("2026-06-02"))
    acme.said(first, at=_at("2026-06-02", 9))
    acme.said(first, at=_at("2026-06-02", 10), by=SenderType.AGENT)

    second = acme.conversation(at=_at("2026-06-03"))
    acme.said(second, at=_at("2026-06-03", 9))
    acme.said(second, at=_at("2026-06-03", 12), by=SenderType.AI)

    # One hour and three hours, so two hours on average.
    assert acme.analytics(**RANGE)["average_first_response_seconds"] == 7200.0


def test_a_thread_nobody_has_answered_is_left_out_rather_than_counted_as_zero(
    client: TestClient,
    acme: Business,
) -> None:
    # Folding an unanswered thread in would make a busy morning look like
    # an improvement. How many are waiting is a different figure.
    answered = acme.conversation(at=_at("2026-06-02"))
    acme.said(answered, at=_at("2026-06-02", 9))
    acme.said(answered, at=_at("2026-06-02", 10), by=SenderType.AGENT)

    waiting = acme.conversation(at=_at("2026-06-03"))
    acme.said(waiting, at=_at("2026-06-03", 9))

    assert acme.analytics(**RANGE)["average_first_response_seconds"] == 3600.0


def test_nothing_answered_yet_reports_no_data_rather_than_instant(
    client: TestClient,
    acme: Business,
) -> None:
    conversation = acme.conversation(at=_at("2026-06-02"))
    acme.said(conversation, at=_at("2026-06-02", 9))

    assert acme.analytics(**RANGE)["average_first_response_seconds"] is None


# --- the assistant ----------------------------------------------------------


def test_conversations_are_counted_by_who_answered_them(
    client: TestClient,
    acme: Business,
) -> None:
    # A thread both spoke in counts for both, which is why these do not
    # sum to the number answered.
    both = acme.conversation(at=_at("2026-06-02"))
    acme.said(both, at=_at("2026-06-02", 10), by=SenderType.AI)
    acme.said(both, at=_at("2026-06-02", 11), by=SenderType.AGENT)

    ai_only = acme.conversation(at=_at("2026-06-03"))
    acme.said(ai_only, at=_at("2026-06-03", 10), by=SenderType.AI)

    unanswered = acme.conversation(at=_at("2026-06-04"))
    acme.said(unanswered, at=_at("2026-06-04", 10))

    handled = acme.analytics(**RANGE)["handled"]

    assert handled["answered"] == 2
    assert handled["by_ai"] == 2
    assert handled["by_agents"] == 1
    # Two conversations answered, both of them by the assistant.
    assert acme.analytics(**RANGE)["ai_response_rate"] == 1.0


def test_the_response_rate_is_zero_when_nothing_has_been_answered(
    client: TestClient,
    acme: Business,
) -> None:
    # Zero rather than a hundred percent: showing an untouched workspace a
    # perfect score would be the most flattering possible lie.
    acme.conversation(at=_at("2026-06-02"))

    assert acme.analytics(**RANGE)["ai_response_rate"] == 0.0
    assert acme.analytics("ai", **RANGE)["answer_rate"] == 0.0


def test_the_ai_report_has_a_row_for_every_decision(
    client: TestClient,
    acme: Business,
) -> None:
    body = acme.analytics("ai", **RANGE)

    assert set(body["decisions"]) == {
        "total",
        "answered",
        "suggested",
        "handoff",
        "blocked",
        "failed",
    }
    assert set(body["handoffs"]) == {
        "total",
        "ai_handoff",
        "human_takeover",
        "ai_released",
    }
    assert set(body["cost"]) == {
        "input_tokens",
        "output_tokens",
        "average_latency_ms",
        "average_confidence",
    }


# --- the boundary -----------------------------------------------------------


def test_another_businesss_activity_is_never_counted_in_yours(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    # A total that quietly included another business would not look wrong.
    # It would just be wrong.
    mine = acme.conversation(at=_at("2026-06-02"))
    acme.said(mine, at=_at("2026-06-02", 9))

    for _ in range(5):
        theirs = rival.conversation(at=_at("2026-06-02"))
        rival.said(theirs, at=_at("2026-06-02", 9))
        rival.said(theirs, at=_at("2026-06-02", 10), by=SenderType.AI)

    body = acme.analytics(**RANGE)

    assert body["conversations"]["total"] == 1
    assert body["messages"]["total"] == 1
    assert body["messages"]["by_ai"] == 0
    assert body["handled"]["by_ai"] == 0


def test_activity_outside_the_range_is_not_counted(
    client: TestClient,
    acme: Business,
) -> None:
    acme.conversation(at=_at("2026-05-31", hour=23))
    acme.conversation(at=_at("2026-06-15"))
    acme.conversation(at=_at("2026-07-01", hour=0))

    assert acme.analytics("conversations", **RANGE)["totals"]["total"] == 1


@pytest.mark.parametrize("role", ["owner", "admin", "agent", "viewer"])
def test_every_member_may_read_the_dashboard(
    client: TestClient,
    acme: Business,
    role: str,
) -> None:
    # The numbers are about the workspace's own work rather than about any
    # one customer, and a viewer watching the dashboard is who this is for.
    headers = acme.member(f"{role}@example.com", WorkspaceRole(role))

    for what in ("overview", "conversations", "ai"):
        response = client.get(
            f"/api/v1/workspaces/{acme.workspace_id}/analytics/{what}",
            headers=headers,
        )
        assert response.status_code == 200, what


def test_the_dashboard_requires_a_token(client: TestClient, acme: Business) -> None:
    response = client.get(f"/api/v1/workspaces/{acme.workspace_id}/analytics/overview")

    assert response.status_code == 401


def test_another_business_cannot_read_your_dashboard(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    response = client.get(
        f"/api/v1/workspaces/{acme.workspace_id}/analytics/overview",
        headers=rival.headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_the_default_range_is_the_last_thirty_days(
    client: TestClient,
    acme: Business,
) -> None:
    now = datetime.now(UTC)
    acme.conversation(at=now - timedelta(days=2))
    acme.conversation(at=now - timedelta(days=60))

    body = acme.analytics("conversations")

    assert body["totals"]["total"] == 1
    assert len(body["by_day"]) == 30
