"""Phase 18 acceptance: the catalogue, its variants, and the tenant wall."""

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

HOODIE = {
    "name": "Black Hoodie",
    "description": "Heavyweight cotton, unisex",
    "price": "4500.00",
    "currency": "PKR",
    "variants": [
        {"sku": "HOOD-M", "title": "Medium", "stock_quantity": 4,
         "attributes": {"size": "M", "color": "Black"}},
        {"sku": "HOOD-L", "title": "Large", "stock_quantity": 0,
         "attributes": {"size": "L", "color": "Black"}},
    ],
}  # fmt: skip


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


def _add(tenant: Tenant, headers: dict[str, str] | None = None, **fields: object):
    return tenant.client.post(
        tenant.path("products"),
        json=HOODIE | fields,
        headers=headers or tenant.owner_headers,
    )


def _created(tenant: Tenant, **fields: object) -> dict:
    response = _add(tenant, **fields)
    assert response.status_code == 201, response.text

    return response.json()


# --- creating -------------------------------------------------------------


def test_adding_a_product_returns_201(acme: Tenant) -> None:
    assert _add(acme).status_code == 201


def test_a_product_comes_back_with_its_variants(acme: Tenant) -> None:
    product = _created(acme)

    assert [variant["sku"] for variant in product["variants"]] == [
        "HOOD-M",
        "HOOD-L",
    ]


def test_money_survives_the_round_trip(acme: Tenant) -> None:
    # Decimal all the way through. A price stored as a float comes back as
    # 4499.999999999999 and every total built on it is wrong.
    product = _created(acme, price="4500.55")

    assert product["price"] == "4500.55"


def test_a_currency_is_stored_uppercased(acme: Tenant) -> None:
    assert _created(acme, currency="pkr")["currency"] == "PKR"


def test_a_currency_that_is_not_a_code_is_refused(acme: Tenant) -> None:
    assert _add(acme, currency="PK1").status_code == 422


def test_a_negative_price_is_refused(acme: Tenant) -> None:
    assert _add(acme, price="-1.00").status_code == 422


def test_stock_is_allowed_to_be_unknown(acme: Tenant) -> None:
    # Null is "this business does not count stock", which is a different
    # answer from zero and has to stay one.
    product = _created(
        acme,
        variants=[{"sku": "ONE-SIZE", "title": "One size"}],
    )

    assert product["variants"][0]["stock_quantity"] is None


def test_a_product_may_have_no_variants(acme: Tenant) -> None:
    assert _created(acme, variants=[])["variants"] == []


def test_an_external_id_cannot_repeat_in_one_workspace(acme: Tenant) -> None:
    # So a storefront sync can re-run without doubling the catalogue.
    _add(acme, external_id="shopify-1")

    response = _add(acme, external_id="shopify-1", name="Something else")

    assert response.status_code == 409
    assert response.json()["code"] == "product_conflict"


def test_a_sku_cannot_repeat_in_one_workspace(acme: Tenant) -> None:
    _add(acme)

    response = _add(acme, name="Another", external_id="x")

    assert response.status_code == 409


def test_two_businesses_may_use_the_same_external_id(
    acme: Tenant,
    rival: Tenant,
) -> None:
    _add(acme, external_id="shopify-1")

    assert _add(rival, external_id="shopify-1").status_code == 201


def test_two_businesses_may_use_the_same_sku(acme: Tenant, rival: Tenant) -> None:
    _add(acme)

    assert _add(rival).status_code == 201


# --- reading and searching ------------------------------------------------


def test_the_list_holds_this_workspaces_products_only(
    acme: Tenant,
    rival: Tenant,
) -> None:
    _add(acme)
    _add(rival, name="Rival Hoodie")

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()

    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "Black Hoodie"


def test_searching_matches_a_name(acme: Tenant) -> None:
    _add(acme)
    _add(acme, name="Blue Cap", external_id="cap", variants=[])

    listed = acme.client.get(
        acme.path("products"),
        params={"search": "hood"},
        headers=acme.owner_headers,
    ).json()

    assert [item["name"] for item in listed["items"]] == ["Black Hoodie"]


def test_searching_matches_a_variants_sku(acme: Tenant) -> None:
    # A customer quoting a SKU is quoting the only identifier they were
    # ever given.
    _add(acme)

    listed = acme.client.get(
        acme.path("products"),
        params={"search": "HOOD-L"},
        headers=acme.owner_headers,
    ).json()

    assert listed["total"] == 1


def test_filtering_by_status(acme: Tenant) -> None:
    _add(acme)
    _add(acme, name="Draft Tee", status="draft", external_id="tee", variants=[])

    listed = acme.client.get(
        acme.path("products"),
        params={"status": "draft"},
        headers=acme.owner_headers,
    ).json()

    assert [item["name"] for item in listed["items"]] == ["Draft Tee"]


def test_filtering_to_what_is_in_stock(acme: Tenant) -> None:
    _add(acme)
    _add(
        acme,
        name="Sold Out Cap",
        external_id="cap",
        variants=[{"sku": "CAP-1", "stock_quantity": 0}],
    )

    listed = acme.client.get(
        acme.path("products"),
        params={"in_stock": "true"},
        headers=acme.owner_headers,
    ).json()

    assert [item["name"] for item in listed["items"]] == ["Black Hoodie"]


def test_a_product_nobody_counts_is_neither_in_nor_out_of_stock(
    acme: Tenant,
) -> None:
    _add(acme, name="Untracked", external_id="u", variants=[{"sku": "U-1"}])

    def total(**params: str) -> int:
        return acme.client.get(
            acme.path("products"),
            params={"search": "Untracked", **params},
            headers=acme.owner_headers,
        ).json()["total"]

    assert total() == 1
    assert total(in_stock="true") == 0
    assert total(in_stock="false") == 0


def test_reading_one_product(acme: Tenant) -> None:
    product = _created(acme)

    response = acme.client.get(
        acme.path("products", product["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == product["id"]


def test_another_workspaces_product_is_not_found(
    acme: Tenant,
    rival: Tenant,
) -> None:
    theirs = _created(rival)

    response = acme.client.get(
        acme.path("products", theirs["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404


# --- updating -------------------------------------------------------------


def test_updating_leaves_variants_alone_when_they_are_not_mentioned(
    acme: Tenant,
) -> None:
    product = _created(acme)

    updated = acme.client.patch(
        acme.path("products", product["id"]),
        json={"name": "Charcoal Hoodie"},
        headers=acme.owner_headers,
    ).json()

    assert updated["name"] == "Charcoal Hoodie"
    assert len(updated["variants"]) == 2


def test_supplying_variants_replaces_them(acme: Tenant) -> None:
    product = _created(acme)

    updated = acme.client.patch(
        acme.path("products", product["id"]),
        json={"variants": [{"sku": "HOOD-XL", "title": "Extra large"}]},
        headers=acme.owner_headers,
    ).json()

    assert [variant["sku"] for variant in updated["variants"]] == ["HOOD-XL"]


def test_replacing_variants_frees_their_skus(acme: Tenant) -> None:
    # The old rows go before the new ones are written, or the unique
    # index fires against rows on their way out.
    product = _created(acme)

    response = acme.client.patch(
        acme.path("products", product["id"]),
        json={"variants": [{"sku": "HOOD-M", "title": "Medium again"}]},
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["variants"][0]["title"] == "Medium again"


def test_an_empty_variant_list_removes_them_all(acme: Tenant) -> None:
    product = _created(acme)

    updated = acme.client.patch(
        acme.path("products", product["id"]),
        json={"variants": []},
        headers=acme.owner_headers,
    ).json()

    assert updated["variants"] == []


# --- deleting -------------------------------------------------------------


def test_deleting_takes_the_variants_with_it(acme: Tenant) -> None:
    product = _created(acme)

    assert (
        acme.client.delete(
            acme.path("products", product["id"]),
            headers=acme.owner_headers,
        ).status_code
        == 204
    )

    # The SKUs are free again, which is only true if the variants went.
    assert _add(acme).status_code == 201


def test_another_workspaces_product_cannot_be_deleted(
    acme: Tenant,
    rival: Tenant,
) -> None:
    theirs = _created(rival)

    response = acme.client.delete(
        acme.path("products", theirs["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404
    assert (
        rival.client.get(
            rival.path("products", theirs["id"]),
            headers=rival.owner_headers,
        ).status_code
        == 200
    )


# --- who may do what ------------------------------------------------------


def test_an_agent_may_read_the_catalogue(acme: Tenant) -> None:
    _add(acme)
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.get(acme.path("products"), headers=agent)

    assert response.status_code == 200


def test_an_agent_may_not_change_a_price(acme: Tenant) -> None:
    # A price list is what the business charges. An agent answering
    # messages should not be able to edit it mid-conversation.
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    assert _add(acme, headers=agent).status_code == 403


def test_a_stranger_sees_nothing(acme: Tenant, rival: Tenant) -> None:
    response = acme.client.get(acme.path("products"), headers=rival.owner_headers)

    assert response.status_code == 404


def test_the_catalogue_needs_a_token(acme: Tenant) -> None:
    assert acme.client.get(acme.path("products")).status_code == 401


# --- what reaches the assistant -------------------------------------------


def test_the_assistant_is_given_the_catalogue_rather_than_guessing(
    acme: Tenant,
    reply_writer: FakeReplyWriter,
    message_repository: MessageRepository,
    db_session: Session,
) -> None:
    """Phase 18's rule, end to end.

    Nothing is in the knowledge base, so the only way a price or a stock
    level can reach the model is the lookup. Both are exact, and the
    variant nobody counts says so rather than reporting zero.
    """
    _add(acme, variants=[*HOODIE["variants"], {"sku": "HOOD-XL", "title": "XL"}])
    contact = acme.contact()
    conversation = acme.client.post(
        acme.path("conversations"),
        json={"contact_id": contact},
        headers=acme.owner_headers,
    ).json()

    message_repository.create(
        workspace_id=uuid.UUID(acme.workspace_id),
        conversation_id=uuid.UUID(conversation["id"]),
        sender_type=SenderType.CUSTOMER,
        direction=Direction.INBOUND,
        channel=Channel.WHATSAPP,
        status=MessageStatus.DELIVERED,
        text="is the hoodie available?",
    )
    db_session.flush()

    acme.client.post(
        acme.path("conversations", conversation["id"], "ai-reply"),
        headers=acme.owner_headers,
    )

    given = "\n".join(passage.content for passage in reply_writer.calls[-1][2])
    assert "4500 PKR" in given
    assert "4 in stock" in given
    assert "out of stock" in given
    assert "stock not tracked" in given
