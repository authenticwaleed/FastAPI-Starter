"""Phase 21: a second storefront behind the same interface.

The plan asks for two things -- follow the same internal interface, and do
not duplicate business logic -- so most of what is worth asserting here is
that nothing was written twice. The sync, the catalogue, the orders and
the webhook handler are the ones Shopify already used; what is new is one
adapter, and the ways its flow differs from Shopify's are exactly what
these tests are about.
"""

import base64
import hashlib
import hmac
import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.ecommerce.base import (
    EcommerceProviderName,
    InstallCallback,
    RemoteCustomer,
    RemoteOrder,
    RemoteProduct,
    RemoteVariant,
)
from app.integrations.ecommerce.woocommerce import WooCommerceProvider
from app.models.ecommerce_account import EcommerceAccountStatus
from app.repositories.ecommerce_account_repository import (
    EcommerceAccountRepository,
)
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.ecommerce_service import _sign_state
from tests.support.ecommerce import (
    FakeEcommerceProvider,
    woo_order_payload,
    woo_product_payload,
)
from tests.support.tenants import Tenant

STORE = "shop.example.com"
WEBHOOK = "/api/v1/webhooks/woocommerce"
CALLBACK = "/api/v1/integrations/woocommerce/callback"


@pytest.fixture(autouse=True)
def _woocommerce_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "api_base_url", "https://api.example.com")


@pytest.fixture
def woo(
    ecommerce_providers: dict[EcommerceProviderName, FakeEcommerceProvider],
) -> FakeEcommerceProvider:
    return ecommerce_providers[EcommerceProviderName.WOOCOMMERCE]


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _install(tenant: Tenant, store: str = STORE, **kwargs: object):
    return tenant.client.post(
        tenant.path("integrations", "woocommerce", "install"),
        json={"shop_domain": store},
        headers=kwargs.get("headers") or tenant.owner_headers,  # type: ignore[arg-type]
    )


def _connect(tenant: Tenant, store: str = STORE) -> None:
    """Walk the whole flow, as a WooCommerce store would.

    Note the shape: the store POSTs its credentials, and nothing in that
    POST is signed. What vouches for it is the state it echoes back.
    """
    response = _install(tenant, store)
    assert response.status_code == 200, response.text

    state = _sign_state(uuid.UUID(tenant.workspace_id), store)
    callback = tenant.client.post(
        CALLBACK,
        params={"state": state},
        json={
            "key_id": 1,
            "user_id": state,
            "consumer_key": "ck_realkey",
            "consumer_secret": "cs_realsecret",
            "key_permissions": "read",
        },
    )
    assert callback.status_code == 200, callback.text


def _deliver(client: TestClient, topic: str, payload: dict, *, store: str = STORE):
    body = json.dumps(payload).encode()
    secret = get_settings().woocommerce_webhook_secret
    assert secret is not None
    signature = base64.b64encode(
        hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).digest()
    ).decode()

    return client.post(
        WEBHOOK,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-WC-Webhook-Signature": signature,
            "X-WC-Webhook-Topic": topic,
            "X-WC-Webhook-Source": f"https://{store}",
        },
    )


# --- installing -----------------------------------------------------------


def test_installing_points_at_the_stores_own_auth_endpoint(acme: Tenant) -> None:
    response = _install(acme)

    assert response.status_code == 200
    assert response.json()["authorize_url"].startswith(
        f"https://{STORE}/wc-auth/v1/authorize"
    )


def test_the_state_travels_as_woocommerce_user_id(acme: Tenant) -> None:
    # WooCommerce treats user_id as an opaque string to hand back, and
    # since it signs the callback with nothing, that string is the only
    # thing vouching for it.
    url = _install(acme).json()["authorize_url"]

    assert "user_id=" in url


def test_a_store_reached_over_plain_http_is_refused(acme: Tenant) -> None:
    # A storefront on http hands its API credentials to anybody on the
    # path, and silently upgrading the scheme would be pretending somebody
    # asked for something they did not.
    assert _install(acme, "http://shop.example.com").status_code == 502


@pytest.mark.parametrize(
    "address",
    [
        "localhost",
        "169.254.169.254",
        "10.0.0.1",
        "shop.local",
        "shop.example.com:8080",
        "shop.example.com/wp",
    ],
)
def test_an_address_inside_the_wall_is_refused(acme: Tenant, address: str) -> None:
    # This server makes requests to whatever address a caller supplies, and
    # on a cloud host 169.254.169.254 is the machine's own credentials.
    assert _install(acme, address).status_code == 502


def test_the_stores_post_connects_it(
    acme: Tenant,
    ecommerce_account_repository: EcommerceAccountRepository,
) -> None:
    _connect(acme)

    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert account.shop_domain == STORE
    assert account.provider is EcommerceProviderName.WOOCOMMERCE
    assert account.status is EcommerceAccountStatus.CONNECTED


def test_both_halves_of_the_key_pair_are_stored_encrypted(
    acme: Tenant,
    ecommerce_account_repository: EcommerceAccountRepository,
) -> None:
    _connect(acme)

    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert "ck_realkey" not in account.credentials_encrypted
    assert "cs_realsecret" not in account.credentials_encrypted


def test_a_callback_without_a_valid_state_is_refused(acme: Tenant) -> None:
    # The whole of the proof, for a POST the store signs with nothing.
    response = acme.client.post(
        CALLBACK,
        params={"state": "made-up"},
        json={"consumer_key": "ck_x", "consumer_secret": "cs_x"},
    )

    assert response.status_code == 502


def test_a_callback_carrying_no_credentials_is_refused(acme: Tenant) -> None:
    _install(acme)
    state = _sign_state(uuid.UUID(acme.workspace_id), STORE)

    response = acme.client.post(CALLBACK, params={"state": state}, json={"key_id": 1})

    assert response.status_code == 502


def test_a_shopify_style_get_callback_does_not_connect_a_store(
    acme: Tenant,
) -> None:
    # WooCommerce never sends one, and the Shopify adapter would be the
    # one to answer it -- which cannot verify a WooCommerce install.
    _install(acme)
    state = _sign_state(uuid.UUID(acme.workspace_id), STORE)

    response = acme.client.get(CALLBACK, params={"state": state})

    assert response.status_code == 502


# --- the same wall as everything else -------------------------------------


def test_connecting_a_second_storefront_is_refused(acme: Tenant) -> None:
    # Whichever provider either one is: a workspace has one storefront.
    _connect(acme)

    assert _install(acme, "other.example.com").status_code == 409


def test_shopify_and_woocommerce_cannot_both_be_connected(
    acme: Tenant,
) -> None:
    _connect(acme)

    response = acme.client.post(
        acme.path("integrations", "shopify", "install"),
        json={"shop_domain": "acme.myshopify.com"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 409


def test_a_storefront_nobody_has_heard_of_is_a_422(acme: Tenant) -> None:
    # The enum in the path, before any handler runs.
    response = acme.client.post(
        acme.path("integrations", "magento", "install"),
        json={"shop_domain": STORE},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


def test_an_agent_may_not_connect_a_store(acme: Tenant) -> None:
    from app.models.workspace_membership import WorkspaceRole

    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    assert _install(acme, headers=agent).status_code == 403


# --- syncing, through the code Shopify already used -----------------------


def test_the_first_sync_writes_the_catalogue(
    acme: Tenant,
    woo: FakeEcommerceProvider,
) -> None:
    woo.products = [
        RemoteProduct(
            external_id="222",
            name="Black Hoodie",
            price=Decimal("4500.00"),
            variants=[RemoteVariant(external_id="222", sku="HOOD-M", stock_quantity=4)],
        )
    ]
    _connect(acme)

    report = acme.client.post(
        acme.path("integrations", "woocommerce", "sync"),
        headers=acme.owner_headers,
    ).json()

    assert report["products"] == 1
    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["items"][0]["variants"][0]["sku"] == "HOOD-M"


def test_the_first_sync_maps_customers_and_orders(
    acme: Tenant,
    woo: FakeEcommerceProvider,
) -> None:
    woo.orders = [
        RemoteOrder(
            external_id="6001",
            customer=RemoteCustomer(
                external_id="7001",
                phone_number="+923001234567",
                name="Ayesha Khan",
            ),
            status="shipped",
            order_number="1042",
        )
    ]
    _connect(acme)

    report = acme.client.post(
        acme.path("integrations", "woocommerce", "sync"),
        headers=acme.owner_headers,
    ).json()

    assert report["orders"] == 1
    assert report["contacts"] == 1


def test_the_sync_uses_the_storefront_that_is_connected(
    acme: Tenant,
    woo: FakeEcommerceProvider,
    ecommerce_provider: FakeEcommerceProvider,
) -> None:
    # Not the one in the path. A workspace has one storefront, and reading
    # it means reading that one.
    woo.products = [RemoteProduct(external_id="222", name="From WooCommerce")]
    ecommerce_provider.products = [
        RemoteProduct(external_id="111", name="From Shopify")
    ]
    _connect(acme)

    acme.client.post(
        acme.path("integrations", "shopify", "sync"),
        headers=acme.owner_headers,
    )

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert [item["name"] for item in listed["items"]] == ["From WooCommerce"]


# --- webhooks -------------------------------------------------------------


def test_a_product_webhook_writes_the_product(acme: Tenant) -> None:
    _connect(acme)

    response = _deliver(acme.client, "product.updated", woo_product_payload())

    assert response.status_code == 200
    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["items"][0]["name"] == "Black Hoodie"


def test_a_store_that_does_not_manage_stock_arrives_untracked(
    acme: Tenant,
) -> None:
    # WooCommerce sends stock_quantity: null with manage_stock: false, and
    # a shop that has never counted must not be reported as out of stock.
    _connect(acme)

    _deliver(
        acme.client,
        "product.updated",
        woo_product_payload(manage_stock=False, stock_quantity=None),
    )

    variant = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()["items"][0]["variants"][0]
    assert variant["stock_quantity"] is None


def test_an_order_webhook_writes_the_order_and_its_customer(
    acme: Tenant,
) -> None:
    _connect(acme)

    response = _deliver(acme.client, "order.created", woo_order_payload())

    assert response.status_code == 200
    order = acme.client.get(
        acme.path("orders"),
        headers=acme.owner_headers,
    ).json()["items"][0]
    assert order["order_number"] == "1042"
    assert order["status"] == "confirmed"
    assert order["tracking_number"] == "TCS-99887766"
    assert order["subtotal"] == "4500.00"


def test_the_same_delivery_twice_produces_one_product(acme: Tenant) -> None:
    _connect(acme)
    payload = woo_product_payload()

    _deliver(acme.client, "product.created", payload)
    _deliver(acme.client, "product.created", payload)

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 1


def test_a_retry_does_not_undo_a_newer_change(acme: Tenant) -> None:
    _connect(acme)
    _deliver(
        acme.client,
        "product.updated",
        woo_product_payload(
            name="Charcoal Hoodie",
            date_modified="2026-08-27T12:00:00",
        ),
    )

    _deliver(
        acme.client,
        "product.updated",
        woo_product_payload(name="Black Hoodie", date_modified="2026-08-27T10:00:00"),
    )

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["items"][0]["name"] == "Charcoal Hoodie"


def test_a_deleted_product_is_removed(acme: Tenant) -> None:
    _connect(acme)
    _deliver(acme.client, "product.created", woo_product_payload())

    _deliver(acme.client, "product.deleted", {"id": 222})

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 0


def test_a_forged_delivery_is_refused(acme: Tenant) -> None:
    _connect(acme)
    body = json.dumps(woo_product_payload()).encode()

    response = acme.client.post(
        WEBHOOK,
        content=body,
        headers={
            "X-WC-Webhook-Signature": "not-the-right-digest",
            "X-WC-Webhook-Topic": "product.updated",
            "X-WC-Webhook-Source": f"https://{STORE}",
        },
    )

    assert response.status_code == 403


def test_a_topic_nothing_handles_is_acknowledged(acme: Tenant) -> None:
    _connect(acme)

    response = _deliver(acme.client, "coupon.created", {"id": 1})

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_a_delivery_for_a_store_we_do_not_hold_is_acknowledged(
    acme: Tenant,
) -> None:
    response = _deliver(
        acme.client,
        "product.updated",
        woo_product_payload(),
        store="stranger.example.com",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_the_whatsapp_webhook_still_has_its_own_path(
    client: TestClient,
) -> None:
    # `/webhooks/{provider}` is a storefront enum, and the WhatsApp route
    # is literal and registered first -- so this must not become a 422.
    # A re-order in app/api/router.py is what this catches.
    response = client.post("/api/v1/webhooks/whatsapp", json={})

    assert response.status_code == 403


def test_the_whatsapp_integration_still_has_its_own_path(
    acme: Tenant,
) -> None:
    # The same collision one level up: `…/integrations/{provider}` would
    # swallow `…/integrations/whatsapp` and refuse it as an unknown
    # storefront. Nothing is connected, so a 404 is the right answer --
    # and a 422 would mean the route never ran.
    response = acme.client.get(
        acme.path("integrations", "whatsapp"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "whatsapp_not_connected"


# --- disconnecting --------------------------------------------------------


def test_disconnecting_keeps_what_was_synced(acme: Tenant) -> None:
    _connect(acme)
    _deliver(acme.client, "product.created", woo_product_payload())

    assert (
        acme.client.delete(
            acme.path("integrations", "woocommerce"),
            headers=acme.owner_headers,
        ).status_code
        == 204
    )

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 1


def test_a_disconnected_store_stops_being_synced(acme: Tenant) -> None:
    _connect(acme)
    acme.client.delete(
        acme.path("integrations", "woocommerce"),
        headers=acme.owner_headers,
    )

    _deliver(acme.client, "product.created", woo_product_payload())

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 0


# --- the adapter itself ---------------------------------------------------


def test_woocommerce_status_is_read_the_way_a_shop_would_read_it() -> None:
    provider = WooCommerceProvider()

    def status(value: str) -> str:
        event = provider.parse_webhook(
            topic="order.updated",
            shop=STORE,
            payload=woo_order_payload(status=value),
        )
        assert event.order is not None

        return event.order.status

    assert status("pending") == "pending"
    assert status("on-hold") == "pending"
    assert status("processing") == "confirmed"
    assert status("completed") == "shipped"
    assert status("cancelled") == "cancelled"
    assert status("refunded") == "refunded"


def test_a_status_a_plugin_invented_lands_as_pending() -> None:
    # Inventing a meaning for one would be the confident wrong answer the
    # catalogue exists to prevent.
    event = WooCommerceProvider().parse_webhook(
        topic="order.updated",
        shop=STORE,
        payload=woo_order_payload(status="awaiting-shipment-by-camel"),
    )

    assert event.order is not None
    assert event.order.status == "pending"


def test_a_guest_checkout_is_not_mapped_onto_one_contact() -> None:
    # WooCommerce sends customer_id 0 for a guest, and treating that as an
    # id would map every guest order a shop ever took onto one person.
    event = WooCommerceProvider().parse_webhook(
        topic="order.created",
        shop=STORE,
        payload=woo_order_payload(customer_id=0),
    )

    assert event.order is not None
    assert event.order.customer.external_id is None


def test_woocommerce_timestamps_are_read_as_utc() -> None:
    # Its `_gmt` fields are UTC and say so nowhere in the string. Left
    # naive they compare unequal to every aware timestamp this application
    # holds, which is how a staleness check silently stops working.
    event = WooCommerceProvider().parse_webhook(
        topic="product.updated",
        shop=STORE,
        payload=woo_product_payload(),
    )

    assert event.product is not None
    assert event.product.updated_at is not None
    assert event.product.updated_at.tzinfo is not None


def test_woocommerce_descriptions_arrive_as_words() -> None:
    event = WooCommerceProvider().parse_webhook(
        topic="product.updated",
        shop=STORE,
        payload=woo_product_payload(),
    )

    assert event.product is not None
    assert event.product.description == "Heavyweight cotton"


def test_the_credentials_are_one_opaque_string_above_the_adapter() -> None:
    installed = WooCommerceProvider().complete_install(
        InstallCallback(
            params={},
            body=json.dumps(
                {"consumer_key": "ck_a", "consumer_secret": "cs_b"}
            ).encode(),
        )
    )

    assert installed.secret == "ck_a:cs_b"
    # And no shop, because the body does not name one -- the signed state
    # is the only thing that says which store this was for.
    assert installed.shop is None
