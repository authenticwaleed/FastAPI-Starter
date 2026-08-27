"""Talking to Shopify, and the only place that knows what it says.

Everything provider-shaped stops here: the `myshopify.com` domain, the
Admin API's paths, the base64 HMAC in a header rather than a hex one in a
different header, `inventory_quantity` rather than `stock_quantity`. What
leaves this module is `base.py`'s vocabulary.
"""

import base64
import hashlib
import hmac
import logging
import re
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
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

logger = logging.getLogger(__name__)

API_VERSION = "2025-01"

# A shop domain is the one piece of the URL a caller supplies, and it is
# interpolated into a request this server makes. Constrained to what
# Shopify actually issues so that nothing else can be: without this, a
# "domain" containing a slash or an @ turns an Admin API call into a
# request to somebody else's host.
SHOP_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")

# Shopify's topics, mapped to this application's. Anything absent is
# acknowledged and ignored: a subscription is easy to widen by accident,
# and a delivery nothing can handle must not be retried for a day.
_TOPICS = {
    "products/create": WebhookTopic.PRODUCT_UPSERT,
    "products/update": WebhookTopic.PRODUCT_UPSERT,
    "products/delete": WebhookTopic.PRODUCT_DELETE,
    "orders/create": WebhookTopic.ORDER_UPSERT,
    "orders/updated": WebhookTopic.ORDER_UPSERT,
    "orders/fulfilled": WebhookTopic.ORDER_UPSERT,
    "orders/cancelled": WebhookTopic.ORDER_UPSERT,
    "app/uninstalled": WebhookTopic.UNINSTALLED,
}

# How many pages of a catalogue one sync will walk. A guard against a
# cursor that never terminates, not a real ceiling: 250 a page is
# Shopify's maximum, so this is 50,000 products.
_MAX_PAGES = 200

# How the one-time code is traded for a token. Injected rather than
# called directly, the same way SmtpEmailSender takes its connection: the
# part worth testing here is the verification in front of it and what is
# done with what comes back, and neither needs a socket.
Exchange = Callable[[str, str], str]


class ShopifyProvider:
    """The Shopify Admin API, behind `EcommerceProvider`."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        exchange: Exchange | None = None,
    ) -> None:
        self._timeout = timeout
        self._exchange = exchange or self._request_token

    @property
    def name(self) -> EcommerceProviderName:
        return EcommerceProviderName.SHOPIFY

    # --- installing --------------------------------------------------------

    def normalise_shop(self, shop: str) -> str:
        return normalise_shop(shop)

    def authorize_url(
        self,
        *,
        shop: str,
        state: str,
        callback_url: str,
        return_url: str,
    ) -> str:
        """Shopify's OAuth grant screen.

        `return_url` is unused: Shopify sends the browser straight back
        to the redirect URI with the grant on it, so there is no second
        place to land.
        """
        settings = get_settings()
        key = settings.shopify_api_key

        if key is None:
            raise EcommerceProviderError("shopify_api_key is not configured")

        query = httpx.QueryParams(
            {
                "client_id": key.get_secret_value(),
                "scope": settings.shopify_scopes,
                "redirect_uri": callback_url,
                "state": state,
            }
        )

        return f"https://{normalise_shop(shop)}/admin/oauth/authorize?{query}"

    def complete_install(self, callback: InstallCallback) -> Installation:
        """Verify Shopify's HMAC, then trade the code for a token."""
        params = callback.params

        if not self._verify_install(params):
            raise EcommerceProviderError("The installation callback did not verify")

        code = params.get("code")

        if not code:
            raise EcommerceProviderError("The callback carried no code")

        shop = normalise_shop(params.get("shop", ""))

        return Installation(secret=self._exchange(shop, code), shop=shop)

    def _verify_install(self, params: Mapping[str, str]) -> bool:
        """Check the HMAC Shopify puts on its OAuth callback.

        Signed over the query string with the `hmac` parameter removed
        and the rest sorted -- which is Shopify's rule, not a general
        one, and exactly the sort of thing that belongs in here.
        """
        given = params.get("hmac")

        if not given:
            return False

        message = "&".join(
            f"{key}={value}"
            for key, value in sorted(params.items())
            if key not in {"hmac", "signature"}
        )
        expected = hmac.new(
            _secret().encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, given)

    def _request_token(self, shop: str, code: str) -> str:
        domain = normalise_shop(shop)
        settings = get_settings()
        key = settings.shopify_api_key

        if key is None:
            raise EcommerceProviderError("shopify_api_key is not configured")

        try:
            response = httpx.post(
                f"https://{domain}/admin/oauth/access_token",
                json={
                    "client_id": key.get_secret_value(),
                    "client_secret": _secret(),
                    "code": code,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except httpx.HTTPError as exc:
            logger.warning("Shopify refused a token exchange: %s", exc)
            raise EcommerceProviderError(
                f"Shopify token exchange failed: {exc}"
            ) from exc

        if not isinstance(token, str) or not token:
            raise EcommerceProviderError("Shopify returned no access token")

        return token

    # --- listening ---------------------------------------------------------

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool:
        """Base64 HMAC-SHA256 over the raw body, which is Shopify's shape.

        Compared with `compare_digest`, so a wrong signature costs the
        same time whatever is wrong with it.
        """
        if not signature:
            return False

        expected = base64.b64encode(
            hmac.new(_secret().encode(), payload, hashlib.sha256).digest()
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
        domain = (shop or "").strip().lower()

        if known is WebhookTopic.PRODUCT_UPSERT:
            return WebhookEvent(
                topic=known,
                shop=domain,
                product=self._product(payload),
            )

        if known is WebhookTopic.PRODUCT_DELETE:
            return WebhookEvent(
                topic=known,
                shop=domain,
                external_id=_text(payload.get("id")),
            )

        if known is WebhookTopic.ORDER_UPSERT:
            return WebhookEvent(topic=known, shop=domain, order=self._order(payload))

        return WebhookEvent(topic=known, shop=domain)

    # --- reading -----------------------------------------------------------

    def fetch_products(
        self,
        *,
        shop: str,
        secret: str,
    ) -> Iterator[RemoteProduct]:
        for page in self._pages(shop, secret, "products"):
            for item in page.get("products", []):
                yield self._product(item)

    def fetch_orders(
        self,
        *,
        shop: str,
        secret: str,
    ) -> Iterator[RemoteOrder]:
        for page in self._pages(
            shop,
            secret,
            "orders",
            params={"status": "any"},
        ):
            for item in page.get("orders", []):
                yield self._order(item)

    def _pages(
        self,
        shop: str,
        access_token: str,
        resource: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Walk Shopify's cursor pagination, which lives in a Link header.

        Its `page_info` cursor cannot be combined with any other filter,
        so the first request carries the filters and every subsequent one
        carries only the cursor. Getting that wrong is a 400 on page two,
        which is the kind of bug a small test shop never reaches.
        """
        domain = normalise_shop(shop)
        url = f"https://{domain}/admin/api/{API_VERSION}/{resource}.json"
        query: dict[str, str] | None = {"limit": "250", **(params or {})}

        with httpx.Client(timeout=self._timeout) as client:
            for _ in range(_MAX_PAGES):
                try:
                    response = client.get(
                        url,
                        params=query,
                        headers={"X-Shopify-Access-Token": access_token},
                    )
                    response.raise_for_status()
                    yield response.json()
                except httpx.HTTPError as exc:
                    logger.warning("Shopify refused a read of %s: %s", resource, exc)
                    raise EcommerceProviderError(
                        f"Shopify could not be read: {exc}"
                    ) from exc

                following = _next_page(response.headers.get("Link"))

                if following is None:
                    return

                url, query = following, None

            logger.warning("Stopped walking %s after %s pages", resource, _MAX_PAGES)

    # --- translation -------------------------------------------------------

    def _product(self, payload: dict[str, Any]) -> RemoteProduct:
        variants = [self._variant(item) for item in payload.get("variants", [])]
        prices = [variant.price for variant in variants if variant.price is not None]

        return RemoteProduct(
            external_id=_text(payload.get("id")) or "",
            name=_text(payload.get("title")) or "Untitled",
            description=_plain_text(payload.get("body_html")),
            # Shopify's own three: active, draft, archived. Anything else
            # is treated as not for sale, which is the safe way round.
            active=payload.get("status", "active") == "active",
            # A Shopify product has no price of its own; the cheapest
            # variant is what a shop means by "from".
            price=min(prices) if prices else None,
            currency=None,
            variants=variants,
            updated_at=_timestamp(payload.get("updated_at")),
        )

    def _variant(self, payload: dict[str, Any]) -> RemoteVariant:
        attributes = {
            name: payload[key]
            for key, name in (("option1", "option1"), ("option2", "option2"))
            if payload.get(key)
        }

        return RemoteVariant(
            external_id=_text(payload.get("id")) or "",
            sku=_text(payload.get("sku")) or None,
            title=_text(payload.get("title")) or None,
            price=_money(payload.get("price")),
            # Only when Shopify is actually tracking it. `inventory_quantity`
            # is present and zero for products where inventory management
            # is off, and reporting that as "out of stock" is the confident
            # wrong answer the whole catalogue exists to prevent.
            stock_quantity=(
                _integer(payload.get("inventory_quantity"))
                if payload.get("inventory_management")
                else None
            ),
            attributes=attributes,
        )

    def _order(self, payload: dict[str, Any]) -> RemoteOrder:
        customer = payload.get("customer") or {}
        shipping = payload.get("shipping_address") or {}
        fulfilments = payload.get("fulfillments") or []
        latest = fulfilments[-1] if fulfilments else {}

        return RemoteOrder(
            external_id=_text(payload.get("id")) or "",
            customer=RemoteCustomer(
                external_id=_text(customer.get("id")),
                # The order's own phone, then the shipping address's, then
                # the customer record's. A guest checkout has no customer
                # and the number is on the address.
                phone_number=_first(
                    payload.get("phone"),
                    shipping.get("phone"),
                    customer.get("phone"),
                ),
                email=_first(payload.get("email"), customer.get("email")),
                name=_first(
                    _joined(customer.get("first_name"), customer.get("last_name")),
                    shipping.get("name"),
                ),
            ),
            status=_status(payload),
            order_number=_text(payload.get("name")),
            currency=_text(payload.get("currency")),
            subtotal=_money(payload.get("subtotal_price")),
            shipping_total=_shipping_total(payload),
            total=_money(payload.get("total_price")),
            shipping_address=_address(shipping),
            tracking_number=_text(latest.get("tracking_number")),
            tracking_url=_text(latest.get("tracking_url")),
            placed_at=_timestamp(payload.get("created_at")),
            updated_at=_timestamp(payload.get("updated_at")),
        )


def normalise_shop(shop: str) -> str:
    """Lowercased, and refused unless it is a real myshopify domain.

    The one caller-supplied piece of a URL this server builds, so the
    check is not politeness. Without it a "shop" of
    `evil.example.com/x?a=` turns an Admin API call, access token and
    all, into a request to somebody else's host.

    A scheme and a trailing slash are forgiven, because people paste
    `https://acme.myshopify.com/` out of a browser bar. Anything else
    with a path in it is refused rather than trimmed down to the host:
    trimming would quietly connect a shop the caller only half named,
    and a value that is not what somebody typed should not be the value
    that gets used.
    """
    domain = shop.strip().lower().removeprefix("https://").removeprefix("http://")
    domain = domain.rstrip("/")

    if not SHOP_DOMAIN.match(domain):
        raise EcommerceProviderError(f"Not a Shopify shop domain: {shop}")

    return domain


def _secret() -> str:
    secret = get_settings().shopify_api_secret

    if secret is None:
        raise EcommerceProviderError("shopify_api_secret is not configured")

    return secret.get_secret_value()


def _next_page(link_header: str | None) -> str | None:
    """The `rel="next"` URL out of an RFC 5988 Link header, if there is one."""
    if not link_header:
        return None

    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2 or 'rel="next"' not in section[1]:
            continue

        return section[0].strip().strip("<>")

    return None


def _status(payload: dict[str, Any]) -> str:
    """Shopify's three flags, read in the order a shop would read them."""
    if payload.get("cancelled_at"):
        return "cancelled"

    if payload.get("financial_status") == "refunded":
        return "refunded"

    fulfillment = payload.get("fulfillment_status")

    if fulfillment == "fulfilled":
        return "shipped"

    if payload.get("financial_status") in {"paid", "partially_paid"}:
        return "confirmed"

    return "pending"


def _shipping_total(payload: dict[str, Any]) -> Decimal | None:
    lines = payload.get("shipping_lines") or []
    amounts = [_money(line.get("price")) for line in lines]
    present = [amount for amount in amounts if amount is not None]

    return sum(present, Decimal("0")) if present else None


def _address(shipping: Mapping[str, Any]) -> str | None:
    parts = [
        shipping.get(key)
        for key in ("address1", "address2", "city", "province", "zip", "country")
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
    """Tags stripped, because a description is read by a language model.

    Crude, and deliberately: what is wanted is the words. A parser would
    be a dependency and a surface for a malformed document to fail on,
    for a field that is a sentence about a hoodie.
    """
    if not html:
        return None

    return _text(re.sub(r"<[^>]+>", " ", str(html)).replace("&nbsp;", " "))


def _money(value: Any) -> Decimal | None:
    if value is None:
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
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
