"""Talking to WooCommerce, and the only place that knows what it says.

The same job the Shopify adapter does, and almost none of it the same way.
Worth naming the differences, because they are the reason the interface
above had to be the shape it is rather than Shopify's shape with a second
name on it:

Installation. Shopify is OAuth: a redirect back to this server with a code
on the query string, signed with an HMAC. WooCommerce's auth endpoint
sends the browser to the store, and the *store* then POSTs the credentials
to a callback URL as JSON, server to server, before sending the browser
somewhere else entirely. There is no signature on that POST at all -- what
vouches for it is that it arrives quoting the signed state this
application put in the request, which is why `user_id` below carries one.

Credentials. Shopify hands over one access token. WooCommerce hands over a
consumer key and a consumer secret, used as HTTP Basic. They are stored as
one opaque string because nothing above this module ever takes either
apart.

Webhooks. Shopify signs with the app secret it already gave you.
WooCommerce signs with a secret whoever created the webhook typed into a
form, so this application publishes one and asks for it to be used --
which is exactly how the WhatsApp app secret works.

Addresses. A Shopify shop is `something.myshopify.com`. A WooCommerce
store is wherever its owner put WordPress, which is why `hosts.py` exists.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import EcommerceProviderError
from app.integrations.ecommerce.base import (
    EcommerceProviderName,
    Installation,
    InstallCallback,
    RemoteCustomer,
    RemoteOrder,
    RemoteProduct,
    RemoteVariant,
    WebhookEvent,
    WebhookTopic,
)
from app.integrations.ecommerce.hosts import normalise_host

logger = logging.getLogger(__name__)

API_PATH = "/wp-json/wc/v3"
AUTH_PATH = "/wc-auth/v1/authorize"

# What appears on the approval screen in the shop owner's own admin. Read
# access only, for the reason the Shopify scopes are read-only: this
# product answers questions about a catalogue, it does not edit one.
SCOPE = "read"

# WooCommerce's topics, mapped to this application's. Its vocabulary is
# dotted where Shopify's is slashed, and it has no separate "fulfilled"
# -- an order's status simply changes to `completed`.
_TOPICS = {
    "product.created": WebhookTopic.PRODUCT_UPSERT,
    "product.updated": WebhookTopic.PRODUCT_UPSERT,
    "product.deleted": WebhookTopic.PRODUCT_DELETE,
    "order.created": WebhookTopic.ORDER_UPSERT,
    "order.updated": WebhookTopic.ORDER_UPSERT,
    "order.deleted": WebhookTopic.ORDER_UPSERT,
}

# WooCommerce's own order statuses, in this application's words. Anything
# absent lands as pending rather than as a guess -- a shop can add its own
# statuses through a plugin, and inventing a meaning for one would be the
# confident wrong answer the catalogue exists to prevent.
_STATUSES = {
    "pending": "pending",
    "on-hold": "pending",
    "processing": "confirmed",
    "completed": "shipped",
    "cancelled": "cancelled",
    "failed": "cancelled",
    "refunded": "refunded",
}

# One page is 100, which is WooCommerce's maximum. The cap is a guard
# against a paginator that never terminates, not a real ceiling.
_PER_PAGE = 100
_MAX_PAGES = 500


class WooCommerceProvider:
    """The WooCommerce REST API, behind `EcommerceProvider`."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    @property
    def name(self) -> EcommerceProviderName:
        return EcommerceProviderName.WOOCOMMERCE

    def normalise_shop(self, shop: str) -> str:
        return normalise_host(shop)

    # --- installing --------------------------------------------------------

    def authorize_url(
        self,
        *,
        shop: str,
        state: str,
        callback_url: str,
        return_url: str,
    ) -> str:
        """WooCommerce's auth endpoint, in the shop owner's own admin.

        `user_id` is the odd one. WooCommerce treats it as an opaque
        string to hand back with the credentials, so it is where the
        signed state goes -- and, since the POST that follows carries no
        signature of its own, it is the only thing vouching for that POST.
        """
        host = normalise_host(shop)
        query = httpx.QueryParams(
            {
                "app_name": get_settings().app_name,
                "scope": SCOPE,
                "user_id": state,
                "return_url": return_url,
                "callback_url": callback_url,
            }
        )

        return f"https://{host}{AUTH_PATH}?{query}"

    def complete_install(self, callback: InstallCallback) -> Installation:
        """Read the key pair out of the store's POST.

        Nothing here proves where the POST came from, because WooCommerce
        signs it with nothing. What proves it is the state, checked by the
        caller: a POST that does not quote one this application signed
        within the last few minutes gets no further than that check.

        The shop is not returned, because the body does not name it. The
        signed state is the only thing that says which store this was for,
        which is exactly why the state carries it.
        """
        payload = _json(callback.body)
        key = _text(payload.get("consumer_key"))
        secret = _text(payload.get("consumer_secret"))

        if not key or not secret:
            raise EcommerceProviderError("The callback carried no credentials")

        return Installation(secret=_pack(key, secret), shop=None)

    # --- listening ---------------------------------------------------------

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool:
        """Base64 HMAC-SHA256 over the raw body, like Shopify's.

        Signed with a secret the shop owner types in when they create the
        webhook rather than one this application already shares with the
        store, so it is configured separately. Without it configured,
        nothing verifies -- which is refusing every delivery, and is the
        right way round.
        """
        if not signature:
            return False

        expected = base64.b64encode(
            hmac.new(_webhook_secret().encode(), payload, hashlib.sha256).digest()
        ).decode()

        return hmac.compare_digest(expected, signature)

    def parse_webhook(
        self,
        *,
        topic: str | None,
        shop: str | None,
        payload: dict[str, Any],
    ) -> WebhookEvent:
        known = _TOPICS.get(topic or "")
        # The source header is a URL rather than a host. Reduced to a host
        # here, because that is what the account table is keyed on.
        host = _host_of(shop)

        if known is WebhookTopic.PRODUCT_UPSERT:
            return WebhookEvent(topic=known, shop=host, product=self._product(payload))

        if known is WebhookTopic.PRODUCT_DELETE:
            return WebhookEvent(
                topic=known,
                shop=host,
                external_id=_text(payload.get("id")),
            )

        if known is WebhookTopic.ORDER_UPSERT:
            return WebhookEvent(topic=known, shop=host, order=self._order(payload))

        return WebhookEvent(topic=known, shop=host)

    # --- reading -----------------------------------------------------------

    def fetch_products(self, *, shop: str, secret: str) -> Iterator[RemoteProduct]:
        for item in self._pages(shop, secret, "products"):
            yield self._product(item)

    def fetch_orders(self, *, shop: str, secret: str) -> Iterator[RemoteOrder]:
        for item in self._pages(shop, secret, "orders"):
            yield self._order(item)

    def _pages(
        self,
        shop: str,
        secret: str,
        resource: str,
    ) -> Iterator[dict[str, Any]]:
        """Walk WooCommerce's page numbers.

        Numbered rather than cursored, unlike Shopify. Stops on the first
        short page, which is what "no more" looks like when the total is
        only in a header nobody promises to send.
        """
        host = normalise_shop_url(shop)
        key, password = _unpack(secret)

        with httpx.Client(timeout=self._timeout) as client:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    response = client.get(
                        f"{host}{API_PATH}/{resource}",
                        params={"per_page": _PER_PAGE, "page": page},
                        auth=(key, password),
                    )
                    response.raise_for_status()
                    items = response.json()
                except httpx.HTTPError as exc:
                    logger.warning(
                        "WooCommerce refused a read of %s: %s", resource, exc
                    )
                    raise EcommerceProviderError(
                        f"WooCommerce could not be read: {exc}"
                    ) from exc

                if not isinstance(items, list):
                    return

                yield from (item for item in items if isinstance(item, dict))

                if len(items) < _PER_PAGE:
                    return

            logger.warning("Stopped walking %s after %s pages", resource, _MAX_PAGES)

    # --- translation -------------------------------------------------------

    def _product(self, payload: dict[str, Any]) -> RemoteProduct:
        variations = payload.get("variations_detail") or []
        variants = [self._variant(item) for item in variations]

        if not variants:
            # A simple product with no variations is still something a
            # customer buys, and it has the stock level. Represented as a
            # single variant so the catalogue has one shape rather than
            # two, and so "is it in stock" has somewhere to look.
            variants = [self._variant(payload)]

        return RemoteProduct(
            external_id=_text(payload.get("id")) or "",
            name=_text(payload.get("name")) or "Untitled",
            description=_plain_text(
                payload.get("short_description") or payload.get("description")
            ),
            # WooCommerce's own: publish, draft, pending, private.
            active=payload.get("status", "publish") == "publish",
            price=_money(payload.get("price")),
            currency=None,
            variants=variants,
            updated_at=_timestamp(payload.get("date_modified_gmt")),
        )

    def _variant(self, payload: dict[str, Any]) -> RemoteVariant:
        attributes = {
            str(attribute.get("name")): str(attribute.get("option"))
            for attribute in payload.get("attributes") or []
            if attribute.get("name") and attribute.get("option")
        }

        return RemoteVariant(
            external_id=_text(payload.get("id")) or "",
            sku=_text(payload.get("sku")),
            title=_text(payload.get("name")),
            price=_money(payload.get("price")),
            # Only when the shop is actually managing stock. WooCommerce
            # sends `stock_quantity: null` with `manage_stock: false`, and
            # a shop that has simply never counted must not be reported as
            # out of stock.
            stock_quantity=(
                _integer(payload.get("stock_quantity"))
                if payload.get("manage_stock")
                else None
            ),
            attributes=attributes,
        )

    def _order(self, payload: dict[str, Any]) -> RemoteOrder:
        billing = payload.get("billing") or {}
        shipping = payload.get("shipping") or {}
        customer_id = payload.get("customer_id")

        return RemoteOrder(
            external_id=_text(payload.get("id")) or "",
            customer=RemoteCustomer(
                # WooCommerce sends 0 for a guest checkout, which is not
                # an id -- and treating it as one would map every guest
                # order a shop has ever taken onto a single contact.
                external_id=_text(customer_id) if customer_id else None,
                phone_number=_first(billing.get("phone"), shipping.get("phone")),
                email=_text(billing.get("email")),
                name=_first(
                    _joined(billing.get("first_name"), billing.get("last_name")),
                    _joined(shipping.get("first_name"), shipping.get("last_name")),
                ),
            ),
            status=_STATUSES.get(str(payload.get("status", "")), "pending"),
            order_number=_text(payload.get("number")),
            currency=_text(payload.get("currency")),
            subtotal=_subtotal(payload),
            shipping_total=_money(payload.get("shipping_total")),
            total=_money(payload.get("total")),
            shipping_address=_address(shipping or billing),
            # WooCommerce keeps no tracking fields of its own; they live
            # in whatever shipping plugin the shop installed, under
            # meta_data. The two keys below are what the common ones use.
            tracking_number=_meta(payload, "_tracking_number"),
            tracking_url=_meta(payload, "_tracking_url"),
            placed_at=_timestamp(payload.get("date_created_gmt")),
            updated_at=_timestamp(payload.get("date_modified_gmt")),
        )


def normalise_shop_url(shop: str) -> str:
    return f"https://{normalise_host(shop)}"


def _host_of(source: str | None) -> str:
    """The host out of the store URL WooCommerce puts in its header.

    Best effort and never raised from: this is used to look a delivery up,
    and a delivery naming something unusable simply matches no account.
    """
    if not source:
        return ""

    try:
        return normalise_host(source.split("?")[0])
    except EcommerceProviderError:
        return ""


def _pack(key: str, secret: str) -> str:
    """Both halves as one opaque string.

    A colon is safe as the separator: WooCommerce issues `ck_` and `cs_`
    followed by hex, and neither half can contain one.
    """
    return f"{key}:{secret}"


def _unpack(secret: str) -> tuple[str, str]:
    key, _, password = secret.partition(":")

    if not key or not password:
        raise EcommerceProviderError("The stored WooCommerce credentials are unusable")

    return key, password


def _webhook_secret() -> str:
    secret = get_settings().woocommerce_webhook_secret

    if secret is None:
        raise EcommerceProviderError("woocommerce_webhook_secret is not configured")

    return secret.get_secret_value()


def _json(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise EcommerceProviderError("The callback was not JSON") from exc

    if not isinstance(payload, dict):
        raise EcommerceProviderError("The callback was not an object")

    return payload


def _subtotal(payload: dict[str, Any]) -> Decimal | None:
    """Summed from the lines, because WooCommerce reports no subtotal.

    Its `total` includes shipping and tax; the line items carry the goods
    on their own. Absent lines it returns nothing rather than the total,
    which would be a number labelled as something it is not.
    """
    lines = payload.get("line_items") or []
    amounts = [_money(line.get("subtotal")) for line in lines]
    present = [amount for amount in amounts if amount is not None]

    return sum(present, Decimal("0")) if present else None


def _meta(payload: dict[str, Any], key: str) -> str | None:
    for entry in payload.get("meta_data") or []:
        if entry.get("key") == key:
            return _text(entry.get("value"))

    return None


def _address(fields: dict[str, Any]) -> str | None:
    parts = [
        fields.get(key)
        for key in ("address_1", "address_2", "city", "state", "postcode", "country")
    ]
    written = ", ".join(str(part) for part in parts if part)

    return written or None


def _joined(*parts: Any) -> str | None:
    written = " ".join(str(part) for part in parts if part)

    return written or None


def _first(*values: Any) -> str | None:
    for value in values:
        text = _text(value)

        if text:
            return text

    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None

    written = str(value).strip()

    return written or None


def _plain_text(html: Any) -> str | None:
    """Tags stripped, for the reason the Shopify adapter strips them.

    WooCommerce descriptions are WordPress content, so they arrive with
    rather more markup than Shopify's -- and what a language model wants
    is the words.
    """
    if not html:
        return None

    return _text(re.sub(r"<[^>]+>", " ", str(html)).replace("&nbsp;", " "))


def _money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None

    # WooCommerce's `_gmt` fields are UTC and say so nowhere in the
    # string. Left naive they would compare unequal to every timezone-aware
    # timestamp this application holds, which is how a staleness check
    # silently stops working.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)

    return parsed
