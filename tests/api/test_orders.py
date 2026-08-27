"""Phase 19 acceptance: order lookup, confirmation, and whose order it is.

The rule the plan singles out is the last one. A customer must not be able
to reach another customer's order, and neither must one business reach
another's -- two different walls, tested separately because they fail
separately.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.conversation import Channel
from app.models.message import Direction, MessageStatus, SenderType
from app.models.workspace_membership import WorkspaceRole
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.knowledge import FakeReplyWriter
from tests.support.tenants import Tenant


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


@pytest.fixture
def rival(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "rival-store")


def _place(
    tenant: Tenant,
    contact_id: str,
    headers: dict[str, str] | None = None,
    **fields: object,
):
    return tenant.client.post(
        tenant.path("orders"),
        json={"contact_id": contact_id} | fields,
        headers=headers or tenant.owner_headers,
    )


def _placed(tenant: Tenant, contact_id: str, **fields: object) -> dict:
    response = _place(tenant, contact_id, **fields)
    assert response.status_code == 201, response.text

    return response.json()


# --- recording ------------------------------------------------------------


def test_recording_an_order_returns_201(acme: Tenant) -> None:
    assert _place(acme, acme.contact()).status_code == 201


def test_an_order_starts_pending(acme: Tenant) -> None:
    assert _placed(acme, acme.contact())["status"] == "pending"


def test_totals_survive_the_round_trip(acme: Tenant) -> None:
    order = _placed(
        acme,
        acme.contact(),
        subtotal="4500.00",
        shipping_total="250.50",
        total="4750.50",
        currency="pkr",
    )

    assert order["subtotal"] == "4500.00"
    assert order["total"] == "4750.50"
    assert order["currency"] == "PKR"


def test_an_order_needs_a_contact_this_workspace_knows(
    acme: Tenant,
    rival: Tenant,
) -> None:
    # Not a 500 from the composite foreign key: naming somebody else's
    # customer answers "no such contact", which is what it is from here.
    theirs = rival.contact()

    response = _place(acme, theirs)

    assert response.status_code == 404
    assert response.json()["code"] == "contact_not_found"


def test_an_external_id_cannot_repeat_in_one_workspace(acme: Tenant) -> None:
    contact = acme.contact()
    _place(acme, contact, external_id="shopify-1042")

    response = _place(acme, contact, external_id="shopify-1042")

    assert response.status_code == 409
    assert response.json()["code"] == "order_already_exists"


def test_two_businesses_may_use_the_same_external_id(
    acme: Tenant,
    rival: Tenant,
) -> None:
    _place(acme, acme.contact(), external_id="1042")

    assert _place(rival, rival.contact(), external_id="1042").status_code == 201


# --- looking up -----------------------------------------------------------


def test_the_list_holds_this_workspaces_orders_only(
    acme: Tenant,
    rival: Tenant,
) -> None:
    _place(acme, acme.contact())
    _place(rival, rival.contact())

    listed = acme.client.get(acme.path("orders"), headers=acme.owner_headers).json()

    assert listed["total"] == 1


def test_orders_can_be_listed_for_one_customer(acme: Tenant) -> None:
    # What an agent opening a conversation asks for.
    ayesha = acme.contact("+923001111111")
    bilal = acme.contact("+923002222222")
    _place(acme, ayesha, order_number="A-1")
    _place(acme, bilal, order_number="B-1")

    listed = acme.client.get(
        acme.path("orders"),
        params={"contact_id": ayesha},
        headers=acme.owner_headers,
    ).json()

    assert [item["order_number"] for item in listed["items"]] == ["A-1"]


def test_searching_matches_the_number_a_customer_quotes(acme: Tenant) -> None:
    contact = acme.contact()
    _place(acme, contact, order_number="#1042")
    _place(acme, contact, order_number="#1043", external_id="b")

    listed = acme.client.get(
        acme.path("orders"),
        params={"search": "1042"},
        headers=acme.owner_headers,
    ).json()

    assert listed["total"] == 1


def test_searching_matches_a_tracking_number(acme: Tenant) -> None:
    _place(acme, acme.contact(), tracking_number="TCS-99887766")

    listed = acme.client.get(
        acme.path("orders"),
        params={"search": "99887766"},
        headers=acme.owner_headers,
    ).json()

    assert listed["total"] == 1


def test_filtering_by_status(acme: Tenant) -> None:
    contact = acme.contact()
    _place(acme, contact, status="shipped", external_id="a")
    _place(acme, contact, external_id="b")

    listed = acme.client.get(
        acme.path("orders"),
        params={"status": "shipped"},
        headers=acme.owner_headers,
    ).json()

    assert listed["total"] == 1


def test_another_workspaces_order_is_not_found(
    acme: Tenant,
    rival: Tenant,
) -> None:
    theirs = _placed(rival, rival.contact())

    response = acme.client.get(
        acme.path("orders", theirs["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404


# --- updating and confirming ----------------------------------------------


def test_recording_a_shipment(acme: Tenant) -> None:
    order = _placed(acme, acme.contact())

    updated = acme.client.patch(
        acme.path("orders", order["id"]),
        json={
            "status": "shipped",
            "tracking_number": "TCS-1",
            "tracking_url": "https://tcs.example/TCS-1",
        },
        headers=acme.owner_headers,
    ).json()

    assert updated["status"] == "shipped"
    assert updated["tracking_number"] == "TCS-1"


def test_an_order_cannot_be_moved_to_another_customer(acme: Tenant) -> None:
    # Not an edit. It is a correction of who the order was ever for, and
    # a PATCH nobody notices is how one person ends up able to ask about
    # another person's order.
    ayesha = acme.contact("+923001111111")
    bilal = acme.contact("+923002222222")
    order = _placed(acme, ayesha)

    updated = acme.client.patch(
        acme.path("orders", order["id"]),
        json={"contact_id": bilal},
        headers=acme.owner_headers,
    ).json()

    assert updated["contact_id"] == ayesha


def test_confirming_a_pending_order(acme: Tenant) -> None:
    order = _placed(acme, acme.contact())

    response = acme.client.post(
        acme.path("orders", order["id"], "confirm"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_confirming_twice_is_refused(acme: Tenant) -> None:
    order = _placed(acme, acme.contact())
    acme.client.post(
        acme.path("orders", order["id"], "confirm"),
        headers=acme.owner_headers,
    )

    response = acme.client.post(
        acme.path("orders", order["id"], "confirm"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "order_not_confirmable"


def test_a_cancelled_order_cannot_be_confirmed(acme: Tenant) -> None:
    # Confirming is a step forward, not a way to undo a cancellation.
    order = _placed(acme, acme.contact(), status="cancelled")

    response = acme.client.post(
        acme.path("orders", order["id"], "confirm"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 409


def test_another_workspaces_order_cannot_be_confirmed(
    acme: Tenant,
    rival: Tenant,
) -> None:
    theirs = _placed(rival, rival.contact())

    response = acme.client.post(
        acme.path("orders", theirs["id"], "confirm"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404


# --- who may do what ------------------------------------------------------


def test_an_agent_may_record_a_shipment(acme: Tenant) -> None:
    # Unlike the catalogue: this is the work an agent does all day.
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)
    order = _placed(acme, acme.contact())

    response = acme.client.patch(
        acme.path("orders", order["id"]),
        json={"status": "shipped"},
        headers=agent,
    )

    assert response.status_code == 200


def test_a_viewer_may_read_but_not_change(acme: Tenant) -> None:
    viewer = acme.member("viewer@example.com", WorkspaceRole.VIEWER)
    order = _placed(acme, acme.contact())

    assert acme.client.get(acme.path("orders"), headers=viewer).status_code == 200
    assert (
        acme.client.patch(
            acme.path("orders", order["id"]),
            json={"status": "shipped"},
            headers=viewer,
        ).status_code
        == 403
    )


def test_a_stranger_sees_nothing(acme: Tenant, rival: Tenant) -> None:
    response = acme.client.get(acme.path("orders"), headers=rival.owner_headers)

    assert response.status_code == 404


def test_orders_need_a_token(acme: Tenant) -> None:
    assert acme.client.get(acme.path("orders")).status_code == 401


# --- what reaches the assistant -------------------------------------------


def test_the_assistant_is_given_this_customers_orders_and_no_others(
    acme: Tenant,
    reply_writer: FakeReplyWriter,
    message_repository: MessageRepository,
    db_session: Session,
) -> None:
    """Phase 19's rule, end to end.

    The knowledge base is empty, so if the assistant answers at all it is
    from the order that was looked up -- and the passage it was handed has
    to be the one belonging to the person who is typing.
    """
    ayesha = acme.contact("+923001111111")
    bilal = acme.contact("+923002222222")
    _place(acme, ayesha, order_number="AYESHA-1", tracking_number="TCS-AYESHA")
    _place(acme, bilal, order_number="BILAL-1", tracking_number="TCS-BILAL")

    conversation = acme.client.post(
        acme.path("conversations"),
        json={"contact_id": ayesha},
        headers=acme.owner_headers,
    ).json()

    # Written straight to the table rather than through the webhook,
    # which would need a connected WhatsApp number. What is being tested
    # is which order reaches the prompt, not how the question arrived.
    message_repository.create(
        workspace_id=uuid.UUID(acme.workspace_id),
        conversation_id=uuid.UUID(conversation["id"]),
        sender_type=SenderType.CUSTOMER,
        direction=Direction.INBOUND,
        channel=Channel.WHATSAPP,
        status=MessageStatus.DELIVERED,
        text="where is my order?",
    )
    db_session.flush()

    acme.client.post(
        acme.path("conversations", conversation["id"], "ai-reply"),
        headers=acme.owner_headers,
    )

    given = "\n".join(passage.content for passage in reply_writer.calls[-1][2])
    assert "TCS-AYESHA" in given
    assert "TCS-BILAL" not in given
