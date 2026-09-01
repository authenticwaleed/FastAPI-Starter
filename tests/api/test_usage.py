"""Phase 25 acceptance: what a workspace has used, counted where it spent it.

Three things the phase is judged on -- usage is workspace-scoped, period
totals are accurate, plan limits are enforceable -- and the second is the
one worth reading the tests for. The instruction was not to calculate
billing-critical usage from unreliable logs, and the tests below are
mostly about the difference between a log and a meter: the assistant
writes a row every time it decides not to answer, and none of those rows
is something a business should be charged for.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.subscription import Subscription
from app.models.usage_record import UsageMetric, UsageRecord
from app.models.workspace_membership import WorkspaceRole
from app.repositories.usage_repository import UsageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from app.services.usage_service import UsageService
from tests.support.knowledge import FakeEmbeddingProvider, FakeReplyWriter
from tests.support.services import put_on_plan
from tests.support.tenants import Tenant, sign_up
from tests.support.whatsapp import PHONE_NUMBER_ID, inbound_payload, sign

WEBHOOK = "/api/v1/webhooks/whatsapp"

RETURNS = (
    "Returns are accepted within 14 days of delivery. The item must be "
    "unworn and in its original packaging."
)

# What the fake model reports for every completion. Named rather than
# repeated, because the assertion worth making is "what the provider said",
# not "120".
TOKENS_PER_REPLY = 120


def _app_secret() -> str:
    secret = get_settings().whatsapp_app_secret
    assert secret is not None

    return secret.get_secret_value()


class Business:
    """A workspace with a number connected and something to say.

    Enough of the product to spend something: usage is only interesting
    once a customer has written in and the assistant has answered, and
    both of those go through the real webhook rather than through a
    repository, because where a meter is written is the whole question.
    """

    def __init__(self, client: TestClient, slug: str, phone_number_id: str) -> None:
        self.client = client
        self._phone_number_id = phone_number_id

        self.headers = sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.headers,
        ).json()["id"]

        client.post(
            self.path("/integrations/whatsapp/connect"),
            json={
                "phone_number": "+15550001111",
                "external_phone_number_id": phone_number_id,
                "access_token": "a-provider-token",
            },
            headers=self.headers,
        )

    def path(self, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{self.workspace_id}{suffix}"

    def knows(self, content: str = RETURNS) -> None:
        source = self.client.post(
            self.path("/knowledge/sources"),
            json={"name": "Policies", "source_type": "text"},
            headers=self.headers,
        ).json()["id"]
        response = self.client.post(
            self.path("/knowledge/documents"),
            json={
                "knowledge_source_id": source,
                "title": "Returns policy",
                "content": content,
            },
            headers=self.headers,
        )
        assert response.status_code == 201, response.text

    def thread(
        self,
        ai_mode: str = "suggest_only",
        phone: str = "+923001234567",
    ) -> str:
        contact = self.client.post(
            self.path("/contacts"),
            json={"phone_number": phone},
            headers=self.headers,
        ).json()["id"]
        conversation = self.client.post(
            self.path("/conversations"),
            json={"contact_id": contact},
            headers=self.headers,
        ).json()["id"]

        if ai_mode != "suggest_only":
            response = self.client.patch(
                self.path(f"/conversations/{conversation}"),
                json={"ai_mode": ai_mode},
                headers=self.headers,
            )
            assert response.status_code == 200, response.text

        return str(conversation)

    def asked(
        self,
        text: str = "Can I return an unworn item within 14 days?",
        *,
        message_id: str | None = None,
        from_number: str = "923001234567",
    ) -> bytes:
        """A customer writes in, through the real webhook.

        Returns the exact bytes that were delivered, so a test can hand
        the provider's own retry back to it.
        """
        payload = inbound_payload(
            message_id=message_id or f"wamid.{uuid.uuid4().hex[:12]}",
            text=text,
            from_number=from_number,
            phone_number_id=self._phone_number_id,
        )
        body, header = sign(payload, _app_secret())
        response = self.client.post(
            WEBHOOK,
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": header},
        )
        assert response.status_code == 200, response.text

        return body

    def redelivers(self, body: bytes) -> None:
        """The same delivery again, byte for byte, which is what a provider
        does."""
        digest = hmac.new(_app_secret().encode(), body, hashlib.sha256).hexdigest()
        response = self.client.post(
            WEBHOOK,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )
        assert response.status_code == 200, response.text

    def replies(self, conversation_id: str, text: str = "Yes, within 14 days.") -> None:
        response = self.client.post(
            self.path(f"/conversations/{conversation_id}/messages"),
            json={"text": text},
            headers=self.headers,
        )
        assert response.status_code == 201, response.text

    def usage(self) -> dict[str, Any]:
        response = self.client.get(self.path("/usage"), headers=self.headers)
        assert response.status_code == 200, response.text

        return dict(response.json())

    def used(self, metric: UsageMetric) -> int:
        line = next(
            item for item in self.usage()["metrics"] if item["metric"] == metric.value
        )

        return int(line["quantity"])

    def allowed(self, metric: UsageMetric) -> int | None:
        line = next(
            item for item in self.usage()["metrics"] if item["metric"] == metric.value
        )
        limit = line["limit"]

        return None if limit is None else int(limit)


@pytest.fixture
def acme(
    client: TestClient,
    reply_writer: FakeReplyWriter,
    embedding_provider: FakeEmbeddingProvider,
) -> Business:
    return Business(client, "acme-fashion", PHONE_NUMBER_ID)


@pytest.fixture
def rival(
    client: TestClient,
    reply_writer: FakeReplyWriter,
    embedding_provider: FakeEmbeddingProvider,
) -> Business:
    return Business(client, "rival-store", "209876543210987")


@pytest.fixture
def usage(db_session: Session) -> UsageService:
    return UsageService(usage=UsageRepository(db_session))


# --- what gets metered ------------------------------------------------------


def test_an_answer_is_metered_as_a_response_and_what_it_cost(
    acme: Business,
) -> None:
    acme.knows()
    acme.thread()

    acme.asked()

    assert acme.used(UsageMetric.AI_RESPONSES) == 1
    assert acme.used(UsageMetric.AI_TOKENS) == TOKENS_PER_REPLY


def test_the_assistant_declining_costs_a_business_nothing(
    acme: Business,
) -> None:
    """The regression this phase exists to remove.

    Switching the assistant off on a conversation still writes a row to
    ai_response_logs -- the pipeline records every decision, which is what
    makes it auditable. Counting the allowance from that table charged a
    business a monthly reply for turning the assistant off, which is the
    difference between a log and a meter.
    """
    acme.knows()
    acme.thread(ai_mode="disabled")

    acme.asked()

    assert acme.used(UsageMetric.AI_RESPONSES) == 0
    assert acme.used(UsageMetric.AI_TOKENS) == 0


def test_a_handoff_costs_tokens_and_no_reply(
    acme: Business,
    reply_writer: FakeReplyWriter,
) -> None:
    """What the model spent, without what the business got.

    A draft withheld for low confidence was paid for and never delivered.
    Both of those are true and they are two different numbers, which is
    why they are two metrics.
    """
    reply_writer.confidence = 0.1
    acme.knows()
    acme.thread()

    acme.asked()

    assert acme.used(UsageMetric.AI_RESPONSES) == 0
    assert acme.used(UsageMetric.AI_TOKENS) == TOKENS_PER_REPLY


def test_nothing_is_metered_when_the_model_is_never_called(
    acme: Business,
) -> None:
    # No knowledge base, so the pipeline hands over before spending
    # anything. A decision reached without a provider call is not usage.
    acme.thread()

    acme.asked()

    assert acme.used(UsageMetric.AI_TOKENS) == 0


def test_messages_are_metered_in_both_directions(acme: Business) -> None:
    conversation = acme.thread()

    acme.asked()
    acme.replies(conversation)

    # One in from the customer, one out from the agent.
    assert acme.used(UsageMetric.WHATSAPP_MESSAGES) == 2


def test_a_redelivered_message_is_metered_once(acme: Business) -> None:
    """The reason every usage row names the thing that caused it.

    A provider retries whatever it did not get a prompt 200 for, including
    what it did. The message is stored once because of the unique index on
    the provider's id; the meter has to agree, or a customer with a flaky
    connection costs a business double.
    """
    acme.thread()
    body = acme.asked()

    acme.redelivers(body)

    assert acme.used(UsageMetric.WHATSAPP_MESSAGES) == 1


def test_an_undelivered_reply_is_not_metered(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    """A business still being set up has not sent anything.

    With no number connected a reply is stored and queued rather than
    refused. It has not gone over WhatsApp, so it is not a WhatsApp
    message.
    """
    tenant = Tenant(client, user_repository, membership_repository, "unconnected")
    contact = tenant.contact()
    conversation = client.post(
        tenant.path("conversations"),
        json={"contact_id": contact},
        headers=tenant.owner_headers,
    ).json()["id"]

    response = client.post(
        tenant.path("conversations", str(conversation), "messages"),
        json={"text": "We are open until nine."},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201

    usage = client.get(tenant.path("usage"), headers=tenant.owner_headers).json()
    line = next(
        item
        for item in usage["metrics"]
        if item["metric"] == UsageMetric.WHATSAPP_MESSAGES.value
    )
    assert line["quantity"] == 0


# --- the levels -------------------------------------------------------------


def test_a_talkative_customer_is_one_active_contact(acme: Business) -> None:
    acme.thread()

    acme.asked(text="Do you have this in medium?")
    acme.asked(text="Or in large?")
    acme.asked(text="Anything at all?")

    assert acme.used(UsageMetric.WHATSAPP_MESSAGES) == 3
    assert acme.used(UsageMetric.ACTIVE_CONTACTS) == 1


def test_two_customers_are_two_active_contacts(acme: Business) -> None:
    acme.thread()

    acme.asked(from_number="923001234567")
    acme.asked(from_number="923009999999")

    assert acme.used(UsageMetric.ACTIVE_CONTACTS) == 2


def test_the_team_and_the_knowledge_base_are_counted_as_they_are(
    acme: Business,
) -> None:
    """Levels, not ledgers.

    Nothing in usage_records says how many people are in a workspace.
    These are read from the rows that define them, because a level
    assembled from a ledger of joins and departures is a number that
    drifts from the thing it describes.
    """
    acme.knows()

    assert acme.used(UsageMetric.TEAM_MEMBERS) == 1
    assert acme.used(UsageMetric.WHATSAPP_NUMBERS) == 1
    assert acme.used(UsageMetric.KNOWLEDGE_DOCUMENTS) == 1
    assert acme.used(UsageMetric.KNOWLEDGE_TOKENS) > 0


# --- workspace scoping ------------------------------------------------------


def test_one_businesss_usage_is_not_anothers(
    acme: Business,
    rival: Business,
) -> None:
    acme.knows()
    acme.thread()
    acme.asked()

    assert acme.used(UsageMetric.AI_RESPONSES) == 1
    assert rival.used(UsageMetric.AI_RESPONSES) == 0
    assert rival.used(UsageMetric.WHATSAPP_MESSAGES) == 0
    assert rival.used(UsageMetric.ACTIVE_CONTACTS) == 0


def test_a_stranger_is_told_the_workspace_does_not_exist(
    acme: Business,
    rival: Business,
) -> None:
    response = acme.client.get(acme.path("/usage"), headers=rival.headers)

    assert response.status_code == 404


def test_reading_usage_needs_a_token(client: TestClient, acme: Business) -> None:
    assert client.get(acme.path("/usage")).status_code == 401


# --- the period -------------------------------------------------------------


def test_a_free_workspace_is_metered_over_the_calendar_month(
    acme: Business,
) -> None:
    now = datetime.now(UTC)
    summary = acme.usage()

    assert summary["period_start"].startswith(now.strftime("%Y-%m-01"))
    assert summary["period_end"] > summary["period_start"]


def test_a_subscribed_workspace_is_metered_over_what_it_is_billed_for(
    acme: Business,
    db_session: Session,
    usage: UsageService,
) -> None:
    """The provider's dates, not the calendar's.

    A business billed from the 14th has an allowance that resets on the
    14th, and a usage page saying "this month" over those figures would be
    wrong for most of the month.
    """
    start = datetime(2026, 3, 14, tzinfo=UTC)
    put_on_plan(db_session, acme.workspace_id, PlanTier.GROWTH)
    subscription = db_session.scalars(
        select(Subscription).where(
            Subscription.workspace_id == uuid.UUID(acme.workspace_id)
        )
    ).one()
    subscription.current_period_start = start
    subscription.current_period_end = start + timedelta(days=31)
    db_session.flush()

    period = usage.period(uuid.UUID(acme.workspace_id))

    assert period.start == start
    assert acme.usage()["period_start"].startswith("2026-03-14")


def test_last_periods_usage_is_not_this_periods(
    acme: Business,
    db_session: Session,
) -> None:
    """A total is about one period, and stays about the one it was written
    into.

    The period is stamped on the row when it is written rather than worked
    out from a timestamp at read time, so what a business was charged for
    in March does not move when its billing dates change in April.
    """
    acme.knows()
    acme.thread()
    acme.asked()
    assert acme.used(UsageMetric.AI_RESPONSES) == 1

    last_month = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add(
        UsageRecord(
            workspace_id=uuid.UUID(acme.workspace_id),
            metric=UsageMetric.AI_RESPONSES,
            quantity=500,
            period_start=last_month,
            period_end=last_month + timedelta(days=31),
            source_id=uuid.uuid4(),
        )
    )
    db_session.flush()

    assert acme.used(UsageMetric.AI_RESPONSES) == 1


# --- what the plan allows ---------------------------------------------------


def test_usage_is_shown_against_the_plans_ceilings(acme: Business) -> None:
    # Starter, because nothing has been paid for.
    assert acme.allowed(UsageMetric.AI_RESPONSES) == 1_000
    assert acme.allowed(UsageMetric.TEAM_MEMBERS) == 2
    # Nothing limits how many tokens a knowledge base holds, and a page
    # showing a ceiling that does not exist would invent one.
    assert acme.allowed(UsageMetric.KNOWLEDGE_TOKENS) is None


def test_a_bigger_plan_shows_a_bigger_ceiling(
    acme: Business,
    db_session: Session,
) -> None:
    put_on_plan(db_session, acme.workspace_id, PlanTier.GROWTH)

    assert acme.allowed(UsageMetric.AI_RESPONSES) == 10_000


def test_the_allowance_refuses_once_the_meter_reaches_it(
    acme: Business,
    db_session: Session,
    usage: UsageService,
) -> None:
    """The acceptance criterion, from the other side.

    The number that refuses a business is the same number its usage page
    shows it -- so this fills the meter directly and then asks the
    assistant for one more.
    """
    acme.knows()
    conversation = acme.thread()
    workspace_id = uuid.UUID(acme.workspace_id)

    # One row of a thousand rather than a thousand rows, because a total
    # is a sum of quantities and that is the cheaper way to say the same
    # thing.
    usage.record(
        workspace_id,
        UsageMetric.AI_RESPONSES,
        source_id=uuid.uuid4(),
        quantity=1_000,
    )
    db_session.flush()

    acme.asked()

    logs = acme.client.get(
        acme.path(f"/conversations/{conversation}/ai-responses"),
        headers=acme.headers,
    ).json()
    assert logs["items"][0]["decision"] == "blocked"
    assert logs["items"][0]["reason"] == "plan_limit"


def test_a_team_that_fills_up_is_refused_from_the_same_count(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    """One count behind both answers.

    Starter allows two. The usage page and the invitation endpoint have to
    agree about how many there are, because a business told it has room
    and then refused has been told something untrue by the same product.
    """
    tenant = Tenant(client, user_repository, membership_repository, "filling-up")
    tenant.member("two@example.com", WorkspaceRole.AGENT)

    usage = client.get(tenant.path("usage"), headers=tenant.owner_headers).json()
    line = next(
        item
        for item in usage["metrics"]
        if item["metric"] == UsageMetric.TEAM_MEMBERS.value
    )
    assert (line["quantity"], line["limit"]) == (2, 2)

    response = client.post(
        tenant.path("invitations"),
        json={"email": "three@example.com", "role": "agent"},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 402
