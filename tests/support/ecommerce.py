"""A storefront that answers from a script instead of over the network.

Substituted wherever a test needs to install a shop, read one, or take a
delivery from one. No test in this suite reaches Shopify.

`verify_webhook` and `parse_webhook` are delegated to the real adapter on
purpose, for the reason the WhatsApp fake delegates its two: checking an
HMAC and reading a provider's payload shape are the parts most worth
testing against the code that will actually run, and both are pure.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import EcommerceProviderError
from app.integrations.ecommerce.base import (
    EcommerceProvider,
    EcommerceProviderName,
    Installation,
    InstallCallback,
    RemoteOrder,
    RemoteProduct,
    WebhookEvent,
)
from app.integrations.ecommerce.shopify import ShopifyProvider
from app.integrations.ecommerce.woocommerce import WooCommerceProvider


@dataclass
class FakeEcommerceProvider:
    """A real adapter with the network taken out of it.

    Composition rather than a subclass, and delegation rather than a
    reimplementation. Everything pure -- deciding whether an address is a
    usable shop, verifying a callback, checking a webhook signature,
    reading a provider's payload shape -- runs against the code that will
    actually run in production, because those are the parts most worth
    testing. What is replaced is only what would open a socket: the token
    exchange, which the real adapter already takes as an argument for
    exactly this reason, and the two reads.
    """

    provider: EcommerceProviderName = EcommerceProviderName.SHOPIFY
    products: list[RemoteProduct] = field(default_factory=list)
    orders: list[RemoteOrder] = field(default_factory=list)
    token: str = "shpat_faketoken"
    exchanges: list[tuple[str, str]] = field(default_factory=list)
    fail_exchange_with: str | None = None
    fail_fetch_with: str | None = None
    real: EcommerceProvider = field(init=False)

    def __post_init__(self) -> None:
        self.real = (
            ShopifyProvider(exchange=self._exchange)
            if self.provider is EcommerceProviderName.SHOPIFY
            else WooCommerceProvider()
        )

    @property
    def name(self) -> EcommerceProviderName:
        return self.real.name

    def normalise_shop(self, shop: str) -> str:
        return self.real.normalise_shop(shop)

    def authorize_url(
        self,
        *,
        shop: str,
        state: str,
        callback_url: str,
        return_url: str,
    ) -> str:
        return self.real.authorize_url(
            shop=shop,
            state=state,
            callback_url=callback_url,
            return_url=return_url,
        )

    def complete_install(self, callback: InstallCallback) -> Installation:
        return self.real.complete_install(callback)

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool:
        return self.real.verify_webhook(payload=payload, signature=signature)

    def parse_webhook(
        self,
        *,
        topic: str | None,
        shop: str | None,
        payload: dict[str, Any],
    ) -> WebhookEvent:
        return self.real.parse_webhook(topic=topic, shop=shop, payload=payload)

    def fetch_products(self, *, shop: str, secret: str) -> Iterable[RemoteProduct]:
        self._maybe_fail()

        return list(self.products)

    def fetch_orders(self, *, shop: str, secret: str) -> Iterable[RemoteOrder]:
        self._maybe_fail()

        return list(self.orders)

    def _exchange(self, shop: str, code: str) -> str:
        self.exchanges.append((shop, code))

        if self.fail_exchange_with is not None:
            raise EcommerceProviderError(self.fail_exchange_with)

        return self.token

    def _maybe_fail(self) -> None:
        if self.fail_fetch_with is not None:
            raise EcommerceProviderError(self.fail_fetch_with)


def fake_providers(
    **overrides: FakeEcommerceProvider,
) -> dict[EcommerceProviderName, FakeEcommerceProvider]:
    """One fake per real provider, so a test can reach either."""
    return {
        EcommerceProviderName.SHOPIFY: overrides.get(
            "shopify",
            FakeEcommerceProvider(provider=EcommerceProviderName.SHOPIFY),
        ),
        EcommerceProviderName.WOOCOMMERCE: overrides.get(
            "woocommerce",
            FakeEcommerceProvider(
                provider=EcommerceProviderName.WOOCOMMERCE,
                token="ck_fakekey:cs_fakesecret",
            ),
        ),
    }


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


def woo_product_payload(
    *,
    product_id: int = 222,
    name: str = "Black Hoodie",
    status: str = "publish",
    date_modified: str = "2026-08-27T10:00:00",
    manage_stock: bool = True,
    stock_quantity: int | None = 4,
) -> dict[str, Any]:
    """A product payload shaped the way WooCommerce actually sends one."""
    return {
        "id": product_id,
        "name": name,
        "status": status,
        "short_description": "<p>Heavyweight cotton</p>",
        "price": "4500.00",
        "sku": "HOOD-M",
        "manage_stock": manage_stock,
        "stock_quantity": stock_quantity,
        "date_modified_gmt": date_modified,
        "attributes": [{"name": "Size", "option": "M"}],
    }


def woo_order_payload(
    *,
    order_id: int = 6001,
    number: str = "1042",
    status: str = "processing",
    phone: str | None = "+923001234567",
    customer_id: int = 7001,
    date_modified: str = "2026-08-27T10:00:00",
) -> dict[str, Any]:
    return {
        "id": order_id,
        "number": number,
        "status": status,
        "currency": "PKR",
        "total": "4750.50",
        "shipping_total": "250.50",
        "customer_id": customer_id,
        "date_created_gmt": "2026-08-20T09:00:00",
        "date_modified_gmt": date_modified,
        "line_items": [{"subtotal": "4500.00"}],
        "billing": {
            "first_name": "Ayesha",
            "last_name": "Khan",
            "phone": phone,
            "email": "ayesha@example.com",
        },
        "shipping": {
            "address_1": "12 Jail Road",
            "city": "Lahore",
            "country": "PK",
        },
        "meta_data": [
            {"key": "_tracking_number", "value": "TCS-99887766"},
            {"key": "_tracking_url", "value": "https://tcs.example/TCS-99887766"},
        ],
    }
