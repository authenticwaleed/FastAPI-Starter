"""Phases 18 and 19: the facts the assistant is given, and where they came from.

Both plans say the same thing in two places. A price or a stock level is
looked up, not recalled; an order's status is queried, not retrieved by
similarity. This is that, as a test -- including the part that matters
most, which is that one customer's orders never reach another's prompt.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.contact import ContactStatus
from app.models.order import OrderStatus
from app.models.product import ProductStatus
from app.repositories.contact_repository import ContactRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import (
    ProductRepository,
    VariantSpec,
)
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.commerce_context import CommerceContextService, keywords


@pytest.fixture
def products(db_session: Session) -> ProductRepository:
    return ProductRepository(db_session)


@pytest.fixture
def orders(db_session: Session) -> OrderRepository:
    return OrderRepository(db_session)


def _contact(
    contacts: ContactRepository,
    workspace_id: uuid.UUID,
    phone_number: str,
) -> uuid.UUID:
    return contacts.create(
        workspace_id=workspace_id,
        phone_number=phone_number,
        name=None,
        email=None,
        status=ContactStatus.LEAD,
        source=None,
        external_id=None,
        meta={},
    ).id


@pytest.fixture
def service(
    products: ProductRepository,
    orders: OrderRepository,
) -> CommerceContextService:
    return CommerceContextService(products=products, orders=orders)


@pytest.fixture
def workspace_id(
    db_session: Session,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
) -> uuid.UUID:
    user = user_repository.create(
        name="Ada",
        email="ada@example.com",
        hashed_password="x",
    )
    workspace = workspace_repository.create(
        name="Acme Fashion",
        slug="acme-fashion",
        timezone="Asia/Karachi",
        default_currency="PKR",
        created_by_user_id=user.id,
    )
    db_session.flush()

    return workspace.id


def _hoodie(
    products: ProductRepository,
    workspace_id: uuid.UUID,
    *,
    status: ProductStatus = ProductStatus.ACTIVE,
    stock: int | None = 4,
) -> None:
    product = products.create(
        workspace_id=workspace_id,
        name="Black Hoodie",
        description="Heavyweight cotton",
        price=Decimal("4500.00"),
        currency="PKR",
        status=status,
    )
    products.replace_variants(
        workspace_id,
        product,
        [
            VariantSpec(
                sku="HOOD-M",
                title="Medium",
                stock_quantity=stock,
                attributes={"size": "M"},
            )
        ],
    )


# --- what counts as a search term -----------------------------------------


def test_short_and_common_words_are_not_searched_on() -> None:
    # Without this, "do you have it in stock" searches for "have" and
    # matches the whole catalogue, which is worse than matching nothing.
    assert keywords("do you have it in stock?") == []


def test_the_words_that_name_a_thing_are_kept() -> None:
    kept = set(keywords("is the black hoodie available"))

    assert {"black", "hoodie"} <= kept
    # "is" and "the" are gone; "available" survives, which is the right
    # side of the trade -- the list is there to stop a question matching
    # everything, not to be a stemmer.
    assert "the" not in kept


# --- products -------------------------------------------------------------


def test_a_matching_product_becomes_a_passage(
    service: CommerceContextService,
    products: ProductRepository,
    workspace_id: uuid.UUID,
) -> None:
    _hoodie(products, workspace_id)

    context = service.gather(workspace_id, uuid.uuid4(), "do you have the hoodie?")

    assert len(context.products) == 1
    assert context.products[0].title == "Black Hoodie"


def test_the_passage_carries_the_price_and_the_stock(
    service: CommerceContextService,
    products: ProductRepository,
    workspace_id: uuid.UUID,
) -> None:
    # The whole point: these are looked up, so they are exact.
    _hoodie(products, workspace_id)

    body = service.gather(workspace_id, uuid.uuid4(), "hoodie").products[0].content

    assert "4500 PKR" in body
    assert "4 in stock" in body


def test_stock_nobody_counts_is_said_so_rather_than_reported_as_zero(
    service: CommerceContextService,
    products: ProductRepository,
    workspace_id: uuid.UUID,
) -> None:
    _hoodie(products, workspace_id, stock=None)

    body = service.gather(workspace_id, uuid.uuid4(), "hoodie").products[0].content

    assert "stock not tracked" in body
    assert "out of stock" not in body


def test_nothing_in_stock_says_out_of_stock(
    service: CommerceContextService,
    products: ProductRepository,
    workspace_id: uuid.UUID,
) -> None:
    _hoodie(products, workspace_id, stock=0)

    assert (
        "out of stock"
        in service.gather(workspace_id, uuid.uuid4(), "hoodie").products[0].content
    )


def test_a_draft_product_is_never_offered(
    service: CommerceContextService,
    products: ProductRepository,
    workspace_id: uuid.UUID,
) -> None:
    # A draft is something the business has not decided to sell, and
    # offering it is worse than saying nothing.
    _hoodie(products, workspace_id, status=ProductStatus.DRAFT)

    assert service.gather(workspace_id, uuid.uuid4(), "hoodie").products == []


def test_another_workspaces_catalogue_is_never_reached(
    service: CommerceContextService,
    products: ProductRepository,
    workspace_id: uuid.UUID,
) -> None:
    _hoodie(products, workspace_id)

    assert service.gather(uuid.uuid4(), uuid.uuid4(), "hoodie").products == []


# --- orders ---------------------------------------------------------------


def test_a_customers_own_orders_are_offered(
    service: CommerceContextService,
    orders: OrderRepository,
    contact_repository: ContactRepository,
    workspace_id: uuid.UUID,
) -> None:
    contact = _contact(contact_repository, workspace_id, "+923001111111")
    orders.create(
        workspace_id=workspace_id,
        contact_id=contact,
        status=OrderStatus.SHIPPED,
        order_number="#1042",
        tracking_number="TCS-9",
        total=Decimal("4750.50"),
        currency="PKR",
        placed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    context = service.gather(workspace_id, contact, "where is my order")

    assert len(context.orders) == 1
    body = context.orders[0].content
    assert "Status: shipped" in body
    assert "#1042" in body
    assert "TCS-9" in body


def test_orders_are_offered_whatever_the_question_says(
    service: CommerceContextService,
    orders: OrderRepository,
    contact_repository: ContactRepository,
    workspace_id: uuid.UUID,
) -> None:
    # "Where is it" names nothing searchable, and it is how the question
    # is most often put.
    contact = _contact(contact_repository, workspace_id, "+923001111111")
    orders.create(workspace_id=workspace_id, contact_id=contact)

    assert service.gather(workspace_id, contact, "where is it").orders


def test_one_customer_never_sees_anothers_order(
    service: CommerceContextService,
    orders: OrderRepository,
    contact_repository: ContactRepository,
    workspace_id: uuid.UUID,
) -> None:
    # The rule the plan singles out, and the one a conversation can get
    # wrong. This is what makes it a WHERE clause rather than a similarity
    # search over a shared vector store.
    ayesha = _contact(contact_repository, workspace_id, "+923001111111")
    bilal = _contact(contact_repository, workspace_id, "+923002222222")
    orders.create(
        workspace_id=workspace_id,
        contact_id=ayesha,
        order_number="AYESHA-1",
        tracking_number="SECRET-TRACKING",
    )

    context = service.gather(workspace_id, bilal, "where is my order")

    assert context.orders == []


def test_only_the_most_recent_orders_are_offered(
    service: CommerceContextService,
    orders: OrderRepository,
    contact_repository: ContactRepository,
    workspace_id: uuid.UUID,
) -> None:
    contact = _contact(contact_repository, workspace_id, "+923001111111")

    for day in range(1, 8):
        orders.create(
            workspace_id=workspace_id,
            contact_id=contact,
            order_number=f"#{day}",
            external_id=f"e{day}",
            placed_at=datetime(2026, 8, day, tzinfo=UTC),
        )

    context = service.gather(workspace_id, contact, "my orders")

    assert [passage.title for passage in context.orders] == [
        "Order #7",
        "Order #6",
        "Order #5",
    ]


# --- both together --------------------------------------------------------


def test_nothing_relevant_is_an_empty_context(
    service: CommerceContextService,
    workspace_id: uuid.UUID,
) -> None:
    context = service.gather(workspace_id, uuid.uuid4(), "hello there")

    assert context.is_empty
    assert context.passages == []


def test_orders_come_before_products(
    service: CommerceContextService,
    products: ProductRepository,
    orders: OrderRepository,
    contact_repository: ContactRepository,
    workspace_id: uuid.UUID,
) -> None:
    # A customer asking about a hoodie they have already ordered is
    # asking about their order.
    _hoodie(products, workspace_id)
    contact = _contact(contact_repository, workspace_id, "+923001111111")
    orders.create(workspace_id=workspace_id, contact_id=contact)

    ids = [
        passage.id
        for passage in service.gather(
            workspace_id, contact, "where is my hoodie"
        ).passages
    ]

    assert ids[0].startswith("order:")
    assert ids[-1].startswith("product:")
