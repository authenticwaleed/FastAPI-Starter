"""What the assistant is told about a shop's products and a customer's orders.

The plan asks for two things that are really one thing. Phase 18: the AI
uses a product lookup rather than hallucinating inventory. Phase 19: order
status must be *queried* and not left to a vector knowledge base. Both are
the same instruction -- facts a customer will act on come from a WHERE
clause, not from whichever passage read most like the question.

What comes back is Passages, the same shape retrieval returns, so the
model sees one kind of evidence and cites it the same way. The difference
is entirely in how they were found: these were looked up.

The two lookups are scoped differently, and the difference is the point.
Products are the workspace's, because a catalogue is public. Orders are
the *contact's*, because an order is not -- and the method that fetches
them takes a contact id with no default and no way to widen it.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from fastapi import Depends

from app.integrations.llm.base import Passage
from app.models.order import Order
from app.models.product import Product, ProductVariant
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.services.order_service import ORDERS_IN_CONTEXT, OrderRepositoryDep
from app.services.product_service import ProductRepositoryDep

# How many products one question can pull in. A customer asks about one
# thing; four is enough to cover "the black one or the blue one" and few
# enough that a vague question cannot paste the catalogue into a prompt.
PRODUCTS_IN_CONTEXT = 4

# Words too short or too common to search on. Without this, "do you have
# it in stock" searches for "do", "you" and "have" and matches
# everything, which is worse than matching nothing.
_NOISE = frozenset(
    {
        "the", "and", "for", "you", "your", "are", "any", "have", "has", "was",
        "with", "this", "that", "there", "what", "when", "where", "does", "did",
        "can", "could", "would", "will", "please", "thanks", "thank", "hello",
        "order", "orders", "stock", "price", "cost", "how", "much", "many",
        "want", "need", "buy", "get", "got", "from", "about", "still", "not",
    }
)  # fmt: skip

_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


@dataclass(frozen=True)
class CommerceContext:
    """Structured facts, ready to hand to a language model."""

    products: Sequence[Passage]
    orders: Sequence[Passage]

    @property
    def passages(self) -> list[Passage]:
        return [*self.orders, *self.products]

    @property
    def is_empty(self) -> bool:
        return not self.orders and not self.products


class CommerceContextService:
    """Looks up what this customer's question needs, and nothing else."""

    def __init__(
        self,
        products: ProductRepository,
        orders: OrderRepository,
    ) -> None:
        self._products = products
        self._orders = orders

    def gather(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        question: str,
    ) -> CommerceContext:
        return CommerceContext(
            products=self._product_passages(workspace_id, question),
            orders=self._order_passages(workspace_id, contact_id),
        )

    def _product_passages(
        self,
        workspace_id: uuid.UUID,
        question: str,
    ) -> list[Passage]:
        matches = self._products.search(
            workspace_id,
            keywords(question),
            limit=PRODUCTS_IN_CONTEXT,
        )

        if not matches:
            return []

        variants = self._products.variants_for(
            workspace_id,
            [product.id for product in matches],
        )

        return [
            Passage(
                id=f"product:{product.id}",
                title=product.name,
                content=describe_product(product, variants.get(product.id, [])),
            )
            for product in matches
        ]

    def _order_passages(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
    ) -> list[Passage]:
        """This contact's recent orders, whatever they asked about.

        Fetched without looking at the question, unlike products. A
        customer asking "where is it" has named nothing searchable, and
        that is the most common way the question is put -- so the orders
        are offered and the model decides whether they are relevant.

        Safe to offer unconditionally precisely because of the scoping:
        these are the orders of the person who is typing, so the worst
        case is a prompt carrying something they already know.
        """
        orders = self._orders.list_for_contact(
            workspace_id,
            contact_id,
            limit=ORDERS_IN_CONTEXT,
        )

        return [
            Passage(
                id=f"order:{order.id}",
                title=f"Order {order.order_number or order.id}",
                content=describe_order(order),
            )
            for order in orders
        ]


def keywords(question: str) -> list[str]:
    """The words worth searching a catalogue for.

    Three letters or more, no digits, and none of the words every message
    contains. Crude on purpose: this is a filter in front of an ILIKE
    over one workspace's products, not a search engine, and the failure
    mode that matters is matching everything rather than missing a
    synonym.
    """
    return [
        word
        for word in {match.group().lower() for match in _WORD.finditer(question)}
        if word not in _NOISE
    ]


def describe_product(product: Product, variants: Sequence[ProductVariant]) -> str:
    """A product as a few lines of fact.

    Written out rather than dumped as JSON. The model reads this, and
    "Price: 4500 PKR" is less likely to be garbled on the way into a
    sentence than a brace-and-quote structure it has to parse first.
    """
    lines = [product.name]

    if product.description:
        lines.append(product.description)

    if product.price is not None:
        lines.append(f"Price: {_money(product.price)} {product.currency or ''}".strip())

    for variant in variants:
        lines.append(_variant_line(variant, product))

    return "\n".join(lines)


def describe_order(order: Order) -> str:
    lines = [f"Status: {order.status.value}"]

    if order.order_number:
        lines.append(f"Order number: {order.order_number}")

    if order.placed_at is not None:
        lines.append(f"Placed: {order.placed_at.date().isoformat()}")

    if order.total is not None:
        lines.append(f"Total: {_money(order.total)} {order.currency or ''}".strip())

    if order.tracking_number:
        lines.append(f"Tracking number: {order.tracking_number}")

    if order.tracking_url:
        lines.append(f"Tracking link: {order.tracking_url}")

    return "\n".join(lines)


def _variant_line(variant: ProductVariant, product: Product) -> str:
    name = variant.title or variant.sku or "Variant"
    parts = [name]

    if variant.attributes:
        described = ", ".join(
            f"{key}: {value}" for key, value in sorted(variant.attributes.items())
        )
        parts.append(f"({described})")

    price = variant.price if variant.price is not None else product.price

    if price is not None:
        parts.append(f"- {_money(price)} {product.currency or ''}".strip())

    # Three states, said in three ways. "Stock not tracked" rather than
    # silence, so the model has something to say other than guessing, and
    # so it never reports zero for a shop that simply does not count.
    if variant.stock_quantity is None:
        parts.append("- stock not tracked")
    elif variant.stock_quantity == 0:
        parts.append("- out of stock")
    else:
        parts.append(f"- {variant.stock_quantity} in stock")

    return " ".join(parts)


def _money(amount: Decimal) -> str:
    """Trailing zeros trimmed, because 4500.00 reads as a machine wrote it."""
    return f"{amount.normalize():f}"


def get_commerce_context_service(
    products: ProductRepositoryDep,
    orders: OrderRepositoryDep,
) -> CommerceContextService:
    return CommerceContextService(products=products, orders=orders)


CommerceContextServiceDep = Annotated[
    CommerceContextService,
    Depends(get_commerce_context_service),
]
