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
    """Which storefront is behind the connection."""

    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"


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
class InstallCallback:
    """Everything the provider sent to finish an installation.

    Both halves, because the two providers use different ones. Shopify
    redirects a browser back with its grant in the query string; a
    WooCommerce store POSTs the credentials to a callback URL as JSON,
    server to server, and sends the browser somewhere else entirely.
    """

    params: Mapping[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class Installation:
    """What a finished installation handed over.

    `secret` is opaque above this layer. Shopify's is an access token;
    WooCommerce's is a key and a secret together. Nothing but the adapter
    that produced it ever takes it apart, which is what lets one
    encrypted column hold either.

    `shop` is what the provider itself says the installation was for, or
    None where it does not say. Shopify names the shop in its callback,
    and the service checks that against the shop the installation was
    started for; WooCommerce names nothing, so the signed state is the
    only thing that decides.
    """

    secret: str
    shop: str | None = None


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

    def normalise_shop(self, shop: str) -> str:
        """The canonical form of a shop's address, or a refusal.

        Each provider knows what one of its own looks like -- Shopify
        issues `something.myshopify.com`, a WooCommerce store is wherever
        its owner put WordPress -- and this is the only piece of a URL
        that a caller supplies, so the check belongs beside the knowledge
        rather than in a shared guess. Raises EcommerceProviderError for
        anything it will not accept.
        """
        ...

    def authorize_url(
        self,
        *,
        shop: str,
        state: str,
        callback_url: str,
        return_url: str,
    ) -> str:
        """Where to send a shop owner to approve the installation.

        Both URLs are offered because the two flows use them
        differently. Shopify redirects the browser to `callback_url`
        carrying its grant and has no use for `return_url`; a WooCommerce
        store POSTs to `callback_url` behind the scenes and then sends
        the browser to `return_url`.
        """
        ...

    def complete_install(self, callback: InstallCallback) -> Installation:
        """Turn the provider's callback into credentials worth storing.

        Verifies whatever the provider offers as proof, and does any
        exchange the flow needs. Raises EcommerceProviderError if any of
        that does not hold -- one answer for every way of failing,
        because whoever sent it has proved nothing.
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
        secret: str,
    ) -> Iterable[RemoteProduct]:
        """Every product in the shop, for the first sync."""
        ...

    def fetch_orders(self, *, shop: str, secret: str) -> Iterable[RemoteOrder]: ...
