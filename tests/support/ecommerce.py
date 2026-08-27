"""A storefront that answers from a script instead of over the network.

Substituted wherever a test needs to install a shop, read one, or take a
delivery from one. No test in this suite reaches Shopify.

`verify_webhook` and `parse_webhook` are delegated to the real adapter on
purpose, for the reason the WhatsApp fake delegates its two: checking an
HMAC and reading a provider's payload shape are the parts most worth
testing against the code that will actually run, and both are pure.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import EcommerceProviderError
from app.integrations.ecommerce.base import (
    EcommerceProviderName,
    RemoteOrder,
    RemoteProduct,
    WebhookEvent,
)
from app.integrations.ecommerce.shopify import ShopifyProvider


@dataclass
class FakeEcommerceProvider:
    """Installs whatever it is told to, and holds a catalogue in memory."""

    products: list[RemoteProduct] = field(default_factory=list)
    orders: list[RemoteOrder] = field(default_factory=list)
    token: str = "shpat_faketoken"
    exchanges: list[tuple[str, str]] = field(default_factory=list)
    fail_exchange_with: str | None = None
    fail_fetch_with: str | None = None
    # None means "ask the real adapter", which is the default because the
    # OAuth HMAC is pure and reaches nobody. Set it to force an answer
    # when the test is about what happens next.
    install_is_valid: bool | None = None

    @property
    def name(self) -> EcommerceProviderName:
        return EcommerceProviderName.SHOPIFY

    def authorize_url(self, *, shop: str, state: str, redirect_uri: str) -> str:
        return f"https://{shop}/admin/oauth/authorize?state={state}"

    def verify_install(self, params: Mapping[str, str]) -> bool:
        if self.install_is_valid is not None:
            return self.install_is_valid

        return ShopifyProvider().verify_install(params)

    def exchange_code(self, *, shop: str, code: str) -> str:
        self.exchanges.append((shop, code))

        if self.fail_exchange_with is not None:
            raise EcommerceProviderError(self.fail_exchange_with)

        return self.token

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool:
        return ShopifyProvider().verify_webhook(payload=payload, signature=signature)

    def parse_webhook(
        self,
        *,
        topic: str | None,
        shop: str | None,
        payload: dict[str, Any],
    ) -> WebhookEvent:
        return ShopifyProvider().parse_webhook(
            topic=topic,
            shop=shop,
            payload=payload,
        )

    def fetch_products(
        self,
        *,
        shop: str,
        access_token: str,
    ) -> Iterable[RemoteProduct]:
        self._maybe_fail()

        return list(self.products)

    def fetch_orders(
        self,
        *,
        shop: str,
        access_token: str,
    ) -> Iterable[RemoteOrder]:
        self._maybe_fail()

        return list(self.orders)

    def _maybe_fail(self) -> None:
        if self.fail_fetch_with is not None:
            raise EcommerceProviderError(self.fail_fetch_with)


def shopify_product_payload(
    *,
    product_id: int = 111,
    title: str = "Black Hoodie",
    status: str = "active",
    updated_at: str = "2026-08-27T10:00:00+00:00",
    variants: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A product payload shaped the way Shopify actually sends one."""
    return {
        "id": product_id,
        "title": title,
        "body_html": "<p>Heavyweight cotton</p>",
        "status": status,
        "updated_at": updated_at,
        "variants": list(variants)
        if variants is not None
        else [
            {
                "id": 9001,
                "sku": "HOOD-M",
                "title": "Medium",
                "price": "4500.00",
                "inventory_management": "shopify",
                "inventory_quantity": 4,
                "option1": "M",
            },
            {
                "id": 9002,
                "sku": "HOOD-L",
                "title": "Large",
                "price": "4500.00",
                # Inventory tracking off: the quantity below is present
                # and meaningless, which is exactly the trap.
                "inventory_management": None,
                "inventory_quantity": 0,
                "option1": "L",
            },
        ],
    }


def shopify_order_payload(
    *,
    order_id: int = 5001,
    name: str = "#1042",
    phone: str | None = "+923001234567",
    financial_status: str = "paid",
    fulfillment_status: str | None = None,
    cancelled_at: str | None = None,
    updated_at: str = "2026-08-27T10:00:00+00:00",
) -> dict[str, Any]:
    return {
        "id": order_id,
        "name": name,
        "email": "ayesha@example.com",
        "phone": phone,
        "currency": "PKR",
        "subtotal_price": "4500.00",
        "total_price": "4750.50",
        "financial_status": financial_status,
        "fulfillment_status": fulfillment_status,
        "cancelled_at": cancelled_at,
        "created_at": "2026-08-20T09:00:00+00:00",
        "updated_at": updated_at,
        "shipping_lines": [{"price": "250.50"}],
        "customer": {
            "id": 7001,
            "first_name": "Ayesha",
            "last_name": "Khan",
            "phone": phone,
            "email": "ayesha@example.com",
        },
        "shipping_address": {
            "address1": "12 Jail Road",
            "city": "Lahore",
            "country": "Pakistan",
            "phone": phone,
        },
        "fulfillments": (
            [
                {
                    "tracking_number": "TCS-99887766",
                    "tracking_url": "https://tcs.example/TCS-99887766",
                }
            ]
            if fulfillment_status == "fulfilled"
            else []
        ),
    }
