"""What this application needs of a storefront, in its own vocabulary.

The plan's instruction for this phase is one sentence: keep the product
services independent of Shopify-specific code. Everything below is that
sentence as types. A Shopify payload is turned into these on the way in,
and nothing downstream -- the sync, the catalogue, the orders -- has ever
heard of a `variants` array or a `line_items` key.

The value that buys is not hypothetical. WooCommerce is the next phase,
and it describes the same shop with different words; the adapter is where
that difference is allowed to exist.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol


class EcommerceProviderName(StrEnum):
    """Which storefront is behind the connection.

    One value today. WooCommerce is the reason this is a column rather
    than an assumption baked into the sync.
    """

    SHOPIFY = "shopify"


class WebhookTopic(StrEnum):
    """The kinds of change worth acting on, named the way this app thinks.

    A provider's own topic strings -- `products/update`, `orders/create`
    -- are translated to these by the adapter. Anything a provider sends
    that is not one of them is acknowledged and ignored: a webhook
    subscription is easy to widen by accident, and a delivery that cannot
    be handled must not be retried for a day.
    """

    PRODUCT_UPSERT = "product_upsert"
    PRODUCT_DELETE = "product_delete"
    ORDER_UPSERT = "order_upsert"
    UNINSTALLED = "uninstalled"


@dataclass(frozen=True)
class RemoteVariant:
    """One buyable version of a remote product."""

    external_id: str
    sku: str | None = None
    title: str | None = None
    price: Decimal | None = None
    stock_quantity: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RemoteProduct:
    """A product as the storefront describes it, in this app's words."""

    external_id: str
    name: str
    description: str | None = None
    # None means the storefront did not say. `active` is decided by the
    # adapter, which knows what its own status strings mean.
    active: bool = True
    price: Decimal | None = None
    currency: str | None = None
    variants: Sequence[RemoteVariant] = ()
    # When the storefront last changed it, when it says. Used to ignore a
    # retry that arrives after a newer change has already been applied.
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RemoteCustomer:
    """Who an order belongs to, as much as the storefront knows.

    A phone number is what this product needs, because a phone number is
    what it can reach somebody on. An order for a customer with no number
    is still stored -- it is a real order -- and it is attached to a
    contact created from whatever else there is.
    """

    external_id: str | None = None
    phone_number: str | None = None
    email: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class RemoteOrder:
    external_id: str
    customer: RemoteCustomer
    status: str
    order_number: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    shipping_total: Decimal | None = None
    total: Decimal | None = None
    shipping_address: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    placed_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """One delivery, sorted into something the sync can act on.

    `product` and `order` are mutually exclusive and both may be absent:
    an uninstall carries neither, and a topic this application does not
    handle produces an event with a topic of None.
    """

    topic: WebhookTopic | None
    shop: str
    product: RemoteProduct | None = None
    order: RemoteOrder | None = None
    # The provider's id for the deleted thing, for a delete topic.
    external_id: str | None = None


class EcommerceProvider(Protocol):
    """Installing a storefront, listening to it, and reading from it.

    A Protocol rather than a base class, for the reason MessagingProvider
    is one: the adapter used in tests is not a Shopify client with pieces
    removed, it is a different object answering the same questions.
    """

    @property
    def name(self) -> EcommerceProviderName: ...

    def authorize_url(self, *, shop: str, state: str, redirect_uri: str) -> str:
        """Where to send a shop owner to approve the installation."""
        ...

    def verify_install(self, params: Mapping[str, str]) -> bool:
        """Whether this callback really came from the provider."""
        ...

    def exchange_code(self, *, shop: str, code: str) -> str:
        """Trade the one-time code for a lasting access token.

        Raises EcommerceProviderError if the provider refuses.
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool: ...

    def parse_webhook(
        self,
        *,
        topic: str | None,
        shop: str | None,
        payload: dict[str, Any],
    ) -> WebhookEvent:
        """Turn one delivery into something the sync understands."""
        ...

    def fetch_products(
        self,
        *,
        shop: str,
        access_token: str,
    ) -> Iterable[RemoteProduct]:
        """Every product in the shop, for the first sync."""
        ...

    def fetch_orders(
        self, *, shop: str, access_token: str
    ) -> Iterable[RemoteOrder]: ...
