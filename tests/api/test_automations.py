"""Phase 22 acceptance: a predefined automation runs, once, and says so.

Four things the phase is judged on -- a predefined automation can run,
retry behaviour is defined, run history is available, and duplicate
execution is prevented where required -- plus the one that would be found
the expensive way: connecting a storefront must not message every customer
the business has ever had.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.automation import AutomationKind, AutomationTrigger
from app.models.conversation import Channel
from app.models.message import Direction, MessageStatus, SenderType
from app.models.workspace_membership import WorkspaceRole
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.automation_dispatch import build_automation_service
from app.services.automations import Trigger
from tests.support.messaging import FakeMessagingProvider
from tests.support.tenants import Tenant


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    whatsapp_account_repository: WhatsAppAccountRepository,
    db_session: Session,
) -> Tenant:
    """A business with a number connected, so a send actually goes out."""
    from app.core.encryption import encrypt

    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")
    whatsapp_account_repository.create(
        workspace_id=uuid.UUID(tenant.workspace_id),
        provider="meta_cloud",  # type: ignore[arg-type]
        phone_number="+15550001111",
        external_phone_number_id=f"pnid-{tenant.workspace_id[:8]}",
        external_business_account_id=None,
        access_token_encrypted=encrypt("a-provider-token"),
    )
    db_session.flush()

    return tenant


def _enable(tenant: Tenant, kind: AutomationKind, **definition: object) -> dict:
    response = tenant.client.post(
        tenant.path("automations"),
        json={"kind": kind.value, "definition": definition},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return response.json()


def _runs(tenant: Tenant, automation_id: str, **params: str) -> dict:
    return tenant.client.get(
        tenant.path("automations", automation_id, "runs"),
        params=params,
        headers=tenant.owner_headers,
    ).json()


def _say(
    tenant: Tenant,
    messages: MessageRepository,
    conversations: ConversationRepository,
    session: Session,
    text: str,
    *,
    contact_id: str | None = None,
) -> tuple[str, str]:
    """A customer writes in, written straight to the table.

    Through the repository rather than the webhook, because what is being
    tested is what the automation does with a message rather than how the
    message arrived -- and the webhook path needs a signature and a
    payload shape that say nothing about automations.
    """
    contact = contact_id or tenant.contact()
    conversation = conversations.create(
        workspace_id=uuid.UUID(tenant.workspace_id),
        contact_id=uuid.UUID(contact),
        channel=Channel.WHATSAPP,
    )
    message = messages.create(
        workspace_id=uuid.UUID(tenant.workspace_id),
        conversation_id=conversation.id,
        sender_type=SenderType.CUSTOMER,
        direction=Direction.INBOUND,
        channel=Channel.WHATSAPP,
        status=MessageStatus.DELIVERED,
        text=text,
    )
    session.flush()

    return str(conversation.id), str(message.id)


def _fire(
    tenant: Tenant,
    session: Session,
    messaging: FakeMessagingProvider,
    trigger_type: AutomationTrigger,
    *,
    conversation_id: str | None = None,
    message_id: str | None = None,
    order_id: str | None = None,
) -> None:
    """Fire a trigger the way the background task does.

    Through the engine rather than the endpoint that schedules it,
    because what is being tested is what an automation does -- and the
    dispatch module's own job is only opening a session, which the
    fixtures have already done.
    """
    workspace = WorkspaceRepository(session).get(uuid.UUID(tenant.workspace_id))
    assert workspace is not None

    build_automation_service(session, messaging=messaging).fire(
        workspace,
        Trigger(
            type=trigger_type,
            workspace=workspace,
            conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
            message_id=uuid.UUID(message_id) if message_id else None,
            order_id=uuid.UUID(order_id) if order_id else None,
        ),
    )


def _age(
    session: Session,
    conversations: ConversationRepository,
    tenant: Tenant,
    conversation_id: str,
    *,
    hours: int,
) -> None:
    """Move a thread's last message into the past.

    Written directly, because no endpoint lets a customer have written in
    yesterday -- and waiting a day is not a test.
    """
    conversation = conversations.get(
        uuid.UUID(tenant.workspace_id),
        uuid.UUID(conversation_id),
    )
    assert conversation is not None
    conversation.last_message_at = datetime.now(UTC) - timedelta(hours=hours)
    session.flush()


def _connect_shopify(tenant: Tenant) -> None:
    from app.services.ecommerce_service import _sign_state

    shop = "acme-fashion.myshopify.com"
    tenant.client.post(
        tenant.path("integrations", "shopify", "install"),
        json={"shop_domain": shop},
        headers=tenant.owner_headers,
    )
    state = _sign_state(uuid.UUID(tenant.workspace_id), shop)
    params = {"code": "one-time-code", "shop": shop, "state": state}
    secret = get_settings().shopify_api_secret
    assert secret is not None
    message = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    params["hmac"] = hmac.new(
        secret.get_secret_value().encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    response = tenant.client.get(
        "/api/v1/integrations/shopify/callback",
        params=params,
    )
    assert response.status_code == 200, response.text


# --- configuring ----------------------------------------------------------


def test_switching_an_automation_on(acme: Tenant) -> None:
    created = _enable(acme, AutomationKind.HUMAN_HANDOFF)

    assert created["kind"] == "human_handoff"
    assert created["trigger_type"] == "message_received"
    assert created["status"] == "enabled"


def test_the_stored_definition_carries_its_defaults(acme: Tenant) -> None:
    # So the row answers "what will this say?" without anybody having to
    # know what the code defaults to.
    created = _enable(acme, AutomationKind.ORDER_CONFIRMATION)

    assert "{order_number}" in created["definition"]["template"]


def test_a_name_is_defaulted_from_the_kind(acme: Tenant) -> None:
    assert _enable(acme, AutomationKind.ORDER_CONFIRMATION)["name"]


def test_settings_are_checked_against_the_automation_named(
    acme: Tenant,
) -> None:
    # A definition the code reading it cannot understand would be a run
    # that fails every time, for a reason nobody could see from the form.
    response = acme.client.post(
        acme.path("automations"),
        json={
            "kind": "unanswered_lead_followup",
            "definition": {"after_hours": 10_000},
        },
        headers=acme.owner_headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_automation_settings"


def test_an_automation_nobody_has_written_is_refused(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("automations"),
        json={"kind": "abandoned_cart", "definition": {}},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


def test_one_configuration_per_kind(acme: Tenant) -> None:
    # Two order confirmations would be two messages about one purchase.
    _enable(acme, AutomationKind.ORDER_CONFIRMATION)

    response = acme.client.post(
        acme.path("automations"),
        json={"kind": "order_confirmation", "definition": {}},
        headers=acme.owner_headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "automation_already_exists"


def test_an_agent_may_not_change_what_the_business_says(acme: Tenant) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.post(
        acme.path("automations"),
        json={"kind": "human_handoff", "definition": {}},
        headers=agent,
    )

    assert response.status_code == 403


def test_an_agent_may_read_what_is_switched_on(acme: Tenant) -> None:
    _enable(acme, AutomationKind.HUMAN_HANDOFF)
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.get(acme.path("automations"), headers=agent)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_another_workspaces_automation_is_not_found(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    theirs = _enable(rival, AutomationKind.HUMAN_HANDOFF)

    response = acme.client.get(
        acme.path("automations", theirs["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404


# --- a predefined automation runs -----------------------------------------


def test_an_order_is_confirmed_to_the_customer(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    contact = acme.contact()

    acme.client.post(
        acme.path("orders"),
        json={"contact_id": contact, "order_number": "#1042"},
        headers=acme.owner_headers,
    )

    assert len(messaging_provider.sent) == 1
    assert "#1042" in messaging_provider.sent[0].text


def test_nothing_is_sent_when_the_automation_is_off(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    contact = acme.contact()

    acme.client.post(
        acme.path("orders"),
        json={"contact_id": contact, "order_number": "#1042"},
        headers=acme.owner_headers,
    )

    assert messaging_provider.sent == []


def test_a_disabled_automation_does_not_run(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    automation = _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    acme.client.patch(
        acme.path("automations", automation["id"]),
        json={"status": "disabled"},
        headers=acme.owner_headers,
    )

    acme.client.post(
        acme.path("orders"),
        json={"contact_id": acme.contact(), "order_number": "#1"},
        headers=acme.owner_headers,
    )

    assert messaging_provider.sent == []


def test_the_template_is_the_businesss_own(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    _enable(
        acme,
        AutomationKind.ORDER_CONFIRMATION,
        template="Shukriya! Order {order_number} for {total} is confirmed.",
    )

    acme.client.post(
        acme.path("orders"),
        json={
            "contact_id": acme.contact(),
            "order_number": "#7",
            "total": "4500.00",
            "currency": "PKR",
        },
        headers=acme.owner_headers,
    )

    assert messaging_provider.sent[0].text == (
        "Shukriya! Order #7 for 4500 PKR is confirmed."
    )


def test_a_template_placeholder_cannot_reach_inside_the_process(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    # str.format would evaluate this. A fixed substitution leaves anything
    # it does not recognise exactly as it was written.
    _enable(
        acme,
        AutomationKind.ORDER_CONFIRMATION,
        template="Order {order_number} {0.__class__} {oops}",
    )

    acme.client.post(
        acme.path("orders"),
        json={"contact_id": acme.contact(), "order_number": "#7"},
        headers=acme.owner_headers,
    )

    assert messaging_provider.sent[0].text == "Order #7 {0.__class__} {oops}"


def test_a_customer_asking_for_a_person_is_handed_over(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    automation = _enable(acme, AutomationKind.HUMAN_HANDOFF)
    conversation, message = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "this is useless, I want to speak to a human",
    )

    _fire(
        acme,
        db_session,
        messaging_provider,
        AutomationTrigger.MESSAGE_RECEIVED,
        conversation_id=conversation,
        message_id=message,
    )

    thread = acme.client.get(
        acme.path("conversations", conversation),
        headers=acme.owner_headers,
    ).json()
    assert thread["handoff_at"] is not None
    # Nobody has claimed it, which is what puts it in the unassigned queue
    # rather than quietly on somebody's list.
    assert thread["handoff_by_user_id"] is None
    assert len(messaging_provider.sent) == 1

    history = _runs(acme, automation["id"])
    assert history["items"][0]["status"] == "succeeded"
    assert history["items"][0]["metadata"]["keyword"] == "human"


def test_an_ordinary_question_is_left_alone(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    automation = _enable(acme, AutomationKind.HUMAN_HANDOFF)
    conversation, message = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "do you have this in medium?",
    )

    _fire(
        acme,
        db_session,
        messaging_provider,
        AutomationTrigger.MESSAGE_RECEIVED,
        conversation_id=conversation,
        message_id=message,
    )

    assert messaging_provider.sent == []
    history = _runs(acme, automation["id"])
    assert history["items"][0]["status"] == "skipped"
    assert history["items"][0]["metadata"]["skipped"] == "no_keyword"


def test_a_keyword_inside_a_longer_word_does_not_fire(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    # "cancel" must not fire on "cancellation policy", which is a
    # question the assistant can answer perfectly well.
    _enable(acme, AutomationKind.HUMAN_HANDOFF, keywords=["cancel"])
    conversation, message = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "what is your cancellation policy?",
    )

    _fire(
        acme,
        db_session,
        messaging_provider,
        AutomationTrigger.MESSAGE_RECEIVED,
        conversation_id=conversation,
        message_id=message,
    )

    assert messaging_provider.sent == []


def test_a_thread_already_with_a_person_is_left_alone(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    # Handing over again would move nothing, and acknowledging again
    # would be a second promise to somebody already being helped.
    automation = _enable(acme, AutomationKind.HUMAN_HANDOFF)
    conversation, message = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "I want a refund",
    )
    acme.client.post(
        acme.path("conversations", conversation, "takeover"),
        json={},
        headers=acme.owner_headers,
    )

    _fire(
        acme,
        db_session,
        messaging_provider,
        AutomationTrigger.MESSAGE_RECEIVED,
        conversation_id=conversation,
        message_id=message,
    )

    assert messaging_provider.sent == []
    assert _runs(acme, automation["id"])["items"][0]["metadata"]["skipped"] == (
        "already_with_a_human"
    )


# --- duplicate execution prevented where required -------------------------


def test_an_order_is_confirmed_once_however_often_it_fires(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    db_session: Session,
) -> None:
    # A storefront retries anything it did not get a prompt 200 for.
    automation = _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    order = acme.client.post(
        acme.path("orders"),
        json={"contact_id": acme.contact(), "order_number": "#1042"},
        headers=acme.owner_headers,
    ).json()

    for _ in range(3):
        _fire(
            acme,
            db_session,
            messaging_provider,
            AutomationTrigger.ORDER_CREATED,
            order_id=order["id"],
        )

    assert len(messaging_provider.sent) == 1
    # And one run, not four: the second claim is refused by the index
    # before any work is done rather than halfway through sending.
    assert _runs(acme, automation["id"])["total"] == 1


def test_two_orders_are_two_confirmations(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    contact = acme.contact()

    for number in ("#1", "#2"):
        acme.client.post(
            acme.path("orders"),
            json={"contact_id": contact, "order_number": number},
            headers=acme.owner_headers,
        )

    assert len(messaging_provider.sent) == 2


def test_a_handoff_is_acknowledged_once_per_message(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    _enable(acme, AutomationKind.HUMAN_HANDOFF)
    conversation, message = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "get me a human",
    )

    for _ in range(3):
        _fire(
            acme,
            db_session,
            messaging_provider,
            AutomationTrigger.MESSAGE_RECEIVED,
            conversation_id=conversation,
            message_id=message,
        )

    assert len(messaging_provider.sent) == 1


# --- the sweep, and the automation nothing fires --------------------------


def test_a_dropped_lead_is_followed_up(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    automation = _enable(
        acme,
        AutomationKind.UNANSWERED_LEAD_FOLLOWUP,
        after_hours=2,
    )
    conversation, _ = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "are you open on Sunday?",
    )
    _age(db_session, conversation_repository, acme, conversation, hours=3)

    report = acme.client.post(
        acme.path("automations", "run-due"),
        headers=acme.owner_headers,
    ).json()

    assert report == {"considered": 1, "ran": 1}
    assert len(messaging_provider.sent) == 1
    assert _runs(acme, automation["id"])["items"][0]["status"] == "succeeded"


def test_a_lead_that_is_not_old_enough_is_left(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    _enable(acme, AutomationKind.UNANSWERED_LEAD_FOLLOWUP, after_hours=24)
    conversation, _ = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "are you open on Sunday?",
    )
    _age(db_session, conversation_repository, acme, conversation, hours=1)

    acme.client.post(
        acme.path("automations", "run-due"),
        headers=acme.owner_headers,
    )

    assert messaging_provider.sent == []


def test_a_lead_somebody_answered_is_not_followed_up(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    # A conversation with a history is not a dropped lead, and a
    # stranger's automated nudge is the wrong thing to put in it.
    _enable(acme, AutomationKind.UNANSWERED_LEAD_FOLLOWUP, after_hours=2)
    conversation, _ = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "are you open on Sunday?",
    )
    acme.client.post(
        acme.path("conversations", conversation, "messages"),
        json={"text": "Yes, 11 to 8."},
        headers=acme.owner_headers,
    )
    _age(db_session, conversation_repository, acme, conversation, hours=3)
    # The agent's own reply is a send too, so what is asserted below is
    # that the sweep added nothing to it.
    already = len(messaging_provider.sent)

    report = acme.client.post(
        acme.path("automations", "run-due"),
        headers=acme.owner_headers,
    ).json()

    assert report["considered"] == 0
    assert len(messaging_provider.sent) == already


def test_a_lead_is_followed_up_once_ever(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    # Without this every sweep would find the same dropped thread and
    # send the same message again, for as long as it stayed dropped.
    _enable(acme, AutomationKind.UNANSWERED_LEAD_FOLLOWUP, after_hours=2)
    conversation, _ = _say(
        acme,
        message_repository,
        conversation_repository,
        db_session,
        "are you open on Sunday?",
    )
    _age(db_session, conversation_repository, acme, conversation, hours=3)

    for _ in range(3):
        acme.client.post(
            acme.path("automations", "run-due"),
            headers=acme.owner_headers,
        )
        _age(db_session, conversation_repository, acme, conversation, hours=3)

    assert len(messaging_provider.sent) == 1


def test_a_sweep_with_nothing_to_do_says_so(acme: Tenant) -> None:
    _enable(acme, AutomationKind.UNANSWERED_LEAD_FOLLOWUP)

    report = acme.client.post(
        acme.path("automations", "run-due"),
        headers=acme.owner_headers,
    ).json()

    assert report == {"considered": 0, "ran": 0}


def test_an_agent_may_not_set_the_sweep_running(acme: Tenant) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.post(
        acme.path("automations", "run-due"),
        headers=agent,
    )

    assert response.status_code == 403


# --- retry behaviour and run history --------------------------------------


def test_a_provider_refusing_is_a_failed_run_with_the_attempts_counted(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    automation = _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    # Set before the order is recorded, because recording one is what
    # fires the automation -- the endpoint schedules it, and the test
    # client runs what it scheduled.
    messaging_provider.fail_with = "the provider said no"

    acme.client.post(
        acme.path("orders"),
        json={"contact_id": acme.contact(), "order_number": "#1042"},
        headers=acme.owner_headers,
    )

    run = _runs(acme, automation["id"])["items"][0]
    assert run["status"] == "failed"
    # Three, which is this automation's declared policy: a send the
    # provider briefly refused is worth another go.
    assert run["attempts"] == 3
    assert run["error"]


def test_history_can_be_filtered_to_what_actually_happened(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    message_repository: MessageRepository,
    conversation_repository: ConversationRepository,
    db_session: Session,
) -> None:
    # Most runs are skips, which is the point rather than noise -- but
    # "what did this actually do" is the question people arrive with.
    automation = _enable(acme, AutomationKind.HUMAN_HANDOFF)

    for text in ("do you deliver?", "put me through to a person", "thanks"):
        conversation, message = _say(
            acme,
            message_repository,
            conversation_repository,
            db_session,
            text,
            contact_id=acme.contact(f"+92300111{len(text):04d}"),
        )
        _fire(
            acme,
            db_session,
            messaging_provider,
            AutomationTrigger.MESSAGE_RECEIVED,
            conversation_id=conversation,
            message_id=message,
        )

    assert _runs(acme, automation["id"])["total"] == 3
    assert _runs(acme, automation["id"], status="succeeded")["total"] == 1
    assert _runs(acme, automation["id"], status="skipped")["total"] == 2


def test_a_run_records_when_it_started_and_finished(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
) -> None:
    automation = _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    acme.client.post(
        acme.path("orders"),
        json={"contact_id": acme.contact(), "order_number": "#1"},
        headers=acme.owner_headers,
    )

    run = _runs(acme, automation["id"])["items"][0]
    assert run["started_at"]
    assert run["completed_at"]


def test_deleting_an_automation_takes_its_history(acme: Tenant) -> None:
    automation = _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    acme.client.post(
        acme.path("orders"),
        json={"contact_id": acme.contact(), "order_number": "#1"},
        headers=acme.owner_headers,
    )

    assert (
        acme.client.delete(
            acme.path("automations", automation["id"]),
            headers=acme.owner_headers,
        ).status_code
        == 204
    )

    # And the same automation can be switched on again afterwards, which
    # is only true if the runs went with it.
    assert _enable(acme, AutomationKind.ORDER_CONFIRMATION)["id"]


# --- the expensive mistake ------------------------------------------------


def test_a_storefronts_first_sync_does_not_message_anybody(
    acme: Tenant,
    messaging_provider: FakeMessagingProvider,
    ecommerce_provider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one that would be found by a customer rather than a test.

    A shop connecting for the first time hands over its whole history.
    Confirming all of it would message every customer the business has
    ever had, about orders they placed months ago.
    """
    from decimal import Decimal

    from app.core.config import get_settings
    from app.integrations.ecommerce.base import RemoteCustomer, RemoteOrder

    monkeypatch.setattr(get_settings(), "api_base_url", "https://api.example.com")
    _enable(acme, AutomationKind.ORDER_CONFIRMATION)
    ecommerce_provider.orders = [
        RemoteOrder(
            external_id=str(number),
            customer=RemoteCustomer(phone_number=f"+9230012345{number:02d}"),
            status="shipped",
            total=Decimal("100.00"),
        )
        for number in range(5)
    ]

    _connect_shopify(acme)
    acme.client.post(
        acme.path("integrations", "shopify", "sync"),
        headers=acme.owner_headers,
    )

    assert messaging_provider.sent == []
