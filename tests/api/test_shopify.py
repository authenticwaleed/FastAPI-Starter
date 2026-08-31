"""Phase 20 acceptance: install, sync, listen, and let go.

Five things the phase is judged on -- a connection established, an initial
sync, a webhook sync, duplicate deliveries handled, and a disconnect --
plus the two that would be found the hard way: a callback that names a
different shop from the one it was started for, and a delivery for a shop
this application does not hold.
"""

import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.ecommerce.base import (
    RemoteCustomer,
    RemoteOrder,
    RemoteProduct,
    RemoteVariant,
)
from app.integrations.ecommerce.shopify import ShopifyProvider
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
    shopify_order_payload,
    shopify_product_payload,
)
from tests.support.tenants import Tenant

SHOP = "acme-fashion.myshopify.com"
WEBHOOK = "/api/v1/webhooks/shopify"
CALLBACK = "/api/v1/integrations/shopify/callback"


@pytest.fixture(autouse=True)
def _shopify_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two settings the adapter reads, for the length of one test.

    Set on the cached Settings object rather than through the
    environment, because every other cached value derived from it -- the
    engine, the cipher -- would have to be rebuilt too.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "api_base_url", "https://api.example.com")


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> Tenant:
    # A storefront is a Growth feature; this suite is about the storefront.
    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")
    tenant.on_plan(db_session)

    return tenant


@pytest.fixture
def rival(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> Tenant:
    # A storefront is a Growth feature; this suite is about the storefront.
    tenant = Tenant(client, user_repository, membership_repository, "rival-store")
    tenant.on_plan(db_session)

    return tenant


def _install(tenant: Tenant, shop: str = SHOP, **kwargs: object):
    return tenant.client.post(
        tenant.path("integrations", "shopify", "install"),
        json={"shop_domain": shop},
        headers=kwargs.get("headers") or tenant.owner_headers,  # type: ignore[arg-type]
    )


def _connect(tenant: Tenant, shop: str = SHOP) -> None:
    """Walk the whole OAuth round trip, as the provider would."""
    response = _install(tenant, shop)
    assert response.status_code == 200, response.text

    state = _sign_state(uuid.UUID(tenant.workspace_id), shop)
    callback = tenant.client.get(
        CALLBACK,
        params=_signed({"code": "one-time-code", "shop": shop, "state": state}),
    )
    assert callback.status_code == 200, callback.text


def _signed(params: dict[str, str]) -> dict[str, str]:
    """Add the HMAC Shopify puts on its OAuth callback."""
    import hashlib
    import hmac

    secret = get_settings().shopify_api_secret
    assert secret is not None
    message = "&".join(f"{key}={value}" for key, value in sorted(params.items()))

    return params | {
        "hmac": hmac.new(
            secret.get_secret_value().encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
    }


def _deliver(
    client: TestClient,
    topic: str,
    payload: dict,
    *,
    shop: str = SHOP,
    secret: str | None = None,
):
    body = json.dumps(payload).encode()
    configured = get_settings().shopify_api_secret
    assert configured is not None
    signing = secret if secret is not None else configured.get_secret_value()

    import base64
    import hashlib
    import hmac

    signature = base64.b64encode(
        hmac.new(signing.encode(), body, hashlib.sha256).digest()
    ).decode()

    return client.post(
        WEBHOOK,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": signature,
            "X-Shopify-Topic": topic,
            "X-Shopify-Shop-Domain": shop,
        },
    )


# --- installing -----------------------------------------------------------


def test_installing_returns_somewhere_to_send_the_shop_owner(
    acme: Tenant,
) -> None:
    response = _install(acme)

    assert response.status_code == 200
    assert SHOP in response.json()["authorize_url"]


def test_a_domain_that_is_not_a_shop_is_refused(acme: Tenant) -> None:
    # The one caller-supplied piece of a URL this server calls.
    response = _install(acme, "evil.example.com")

    assert response.status_code == 502


def test_a_domain_smuggling_a_path_is_refused(acme: Tenant) -> None:
    response = _install(acme, "acme.myshopify.com/../evil.example.com")

    assert response.status_code == 502


def test_the_callback_connects_the_shop(
    acme: Tenant,
    ecommerce_account_repository: EcommerceAccountRepository,
) -> None:
    _connect(acme)

    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert account.shop_domain == SHOP
    assert account.status is EcommerceAccountStatus.CONNECTED


def test_the_token_is_never_stored_in_the_clear(
    acme: Tenant,
    ecommerce_provider: FakeEcommerceProvider,
    ecommerce_account_repository: EcommerceAccountRepository,
) -> None:
    _connect(acme)

    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert ecommerce_provider.token not in account.credentials_encrypted


def test_reading_what_is_connected_never_returns_the_token(
    acme: Tenant,
    ecommerce_provider: FakeEcommerceProvider,
) -> None:
    _connect(acme)

    response = acme.client.get(
        acme.path("integrations", "shopify"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["shop_domain"] == SHOP
    assert ecommerce_provider.token not in response.text
    assert "token" not in response.json()


def test_a_callback_that_does_not_verify_is_refused(acme: Tenant) -> None:
    _install(acme)
    state = _sign_state(uuid.UUID(acme.workspace_id), SHOP)

    response = acme.client.get(
        CALLBACK,
        params={"code": "x", "shop": SHOP, "state": state, "hmac": "not-it"},
    )

    assert response.status_code == 502


def test_a_callback_naming_a_different_shop_is_refused(acme: Tenant) -> None:
    # Otherwise somebody who could get one shop owner to approve an
    # installation could attach a different shop to their own workspace.
    _install(acme)
    state = _sign_state(uuid.UUID(acme.workspace_id), SHOP)

    response = acme.client.get(
        CALLBACK,
        params=_signed(
            {"code": "x", "shop": "other-shop.myshopify.com", "state": state}
        ),
    )

    assert response.status_code == 502


def test_a_state_this_application_did_not_sign_is_refused(acme: Tenant) -> None:
    response = acme.client.get(
        CALLBACK,
        params=_signed({"code": "x", "shop": SHOP, "state": "made-up"}),
    )

    assert response.status_code == 502


def test_connecting_twice_is_refused(acme: Tenant) -> None:
    _connect(acme)

    response = _install(acme, "another-shop.myshopify.com")

    assert response.status_code == 409
    assert response.json()["code"] == "storefront_already_connected"


def test_one_shop_cannot_be_connected_to_two_workspaces(
    acme: Tenant,
    rival: Tenant,
) -> None:
    _connect(acme)

    _install(rival, SHOP)
    state = _sign_state(uuid.UUID(rival.workspace_id), SHOP)
    response = rival.client.get(
        CALLBACK,
        params=_signed({"code": "x", "shop": SHOP, "state": state}),
    )

    assert response.status_code == 409


def test_an_agent_may_not_connect_a_storefront(acme: Tenant) -> None:
    from app.models.workspace_membership import WorkspaceRole

    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    assert _install(acme, headers=agent).status_code == 403


# --- the initial sync -----------------------------------------------------


def test_the_first_sync_writes_the_catalogue(
    acme: Tenant,
    ecommerce_provider: FakeEcommerceProvider,
) -> None:
    ecommerce_provider.products = [
        RemoteProduct(
            external_id="111",
            name="Black Hoodie",
            price=Decimal("4500.00"),
            variants=[
                RemoteVariant(
                    external_id="9001",
                    sku="HOOD-M",
                    stock_quantity=4,
                )
            ],
        )
    ]
    _connect(acme)

    report = acme.client.post(
        acme.path("integrations", "shopify", "sync"),
        headers=acme.owner_headers,
    ).json()

    assert report["products"] == 1

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["items"][0]["name"] == "Black Hoodie"
    assert listed["items"][0]["variants"][0]["sku"] == "HOOD-M"


def test_the_first_sync_maps_customers_and_orders(
    acme: Tenant,
    ecommerce_provider: FakeEcommerceProvider,
) -> None:
    ecommerce_provider.orders = [
        RemoteOrder(
            external_id="5001",
            customer=RemoteCustomer(
                external_id="7001",
                phone_number="+923001234567",
                name="Ayesha Khan",
            ),
            status="shipped",
            order_number="#1042",
            total=Decimal("4750.50"),
        )
    ]
    _connect(acme)

    report = acme.client.post(
        acme.path("integrations", "shopify", "sync"),
        headers=acme.owner_headers,
    ).json()

    assert report["orders"] == 1
    assert report["contacts"] == 1

    contacts = acme.client.get(
        acme.path("contacts"),
        headers=acme.owner_headers,
    ).json()
    assert contacts["items"][0]["phone_number"] == "+923001234567"
    assert contacts["items"][0]["status"] == "customer"


def test_syncing_twice_changes_nothing(
    acme: Tenant,
    ecommerce_provider: FakeEcommerceProvider,
) -> None:
    # The property every webhook relies on, exercised the easy way.
    ecommerce_provider.products = [
        RemoteProduct(external_id="111", name="Black Hoodie")
    ]
    ecommerce_provider.orders = [
        RemoteOrder(
            external_id="5001",
            customer=RemoteCustomer(phone_number="+923001234567"),
            status="pending",
        )
    ]
    _connect(acme)
    path = acme.path("integrations", "shopify", "sync")

    acme.client.post(path, headers=acme.owner_headers)
    acme.client.post(path, headers=acme.owner_headers)

    for collection in ("products", "orders", "contacts"):
        listed = acme.client.get(
            acme.path(collection),
            headers=acme.owner_headers,
        ).json()
        assert listed["total"] == 1, collection


def test_syncing_without_a_storefront_is_a_404(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("integrations", "shopify", "sync"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "storefront_not_connected"


def test_a_shop_that_refuses_a_read_is_a_502(
    acme: Tenant,
    ecommerce_provider: FakeEcommerceProvider,
) -> None:
    _connect(acme)
    ecommerce_provider.fail_fetch_with = "the shop said no"

    response = acme.client.post(
        acme.path("integrations", "shopify", "sync"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 502


# --- webhooks -------------------------------------------------------------


def test_a_product_webhook_writes_the_product(acme: Tenant) -> None:
    _connect(acme)

    response = _deliver(acme.client, "products/update", shopify_product_payload())

    assert response.status_code == 200

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "Black Hoodie"


def test_a_variant_shopify_does_not_count_arrives_untracked(
    acme: Tenant,
) -> None:
    # `inventory_quantity` is present and zero when tracking is off, and
    # reporting that as out of stock is the confident wrong answer the
    # whole catalogue exists to prevent.
    _connect(acme)
    _deliver(acme.client, "products/update", shopify_product_payload())

    variants = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()["items"][0]["variants"]
    by_sku = {variant["sku"]: variant for variant in variants}

    assert by_sku["HOOD-M"]["stock_quantity"] == 4
    assert by_sku["HOOD-L"]["stock_quantity"] is None


def test_the_same_delivery_twice_produces_one_product(acme: Tenant) -> None:
    # A provider retries anything it did not get a prompt 200 for.
    _connect(acme)
    payload = shopify_product_payload()

    _deliver(acme.client, "products/create", payload)
    _deliver(acme.client, "products/create", payload)

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 1


def test_a_retry_does_not_undo_a_newer_change(acme: Tenant) -> None:
    # The case a plain upsert gets wrong: an old delivery arriving after
    # a newer one has already landed.
    _connect(acme)
    _deliver(
        acme.client,
        "products/update",
        shopify_product_payload(
            title="Charcoal Hoodie",
            updated_at="2026-08-27T12:00:00+00:00",
        ),
    )

    _deliver(
        acme.client,
        "products/update",
        shopify_product_payload(
            title="Black Hoodie",
            updated_at="2026-08-27T10:00:00+00:00",
        ),
    )

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["items"][0]["name"] == "Charcoal Hoodie"


def test_an_order_webhook_writes_the_order_and_its_customer(
    acme: Tenant,
) -> None:
    _connect(acme)

    response = _deliver(
        acme.client,
        "orders/create",
        shopify_order_payload(fulfillment_status="fulfilled"),
    )

    assert response.status_code == 200

    order = acme.client.get(
        acme.path("orders"),
        headers=acme.owner_headers,
    ).json()["items"][0]
    assert order["order_number"] == "#1042"
    assert order["status"] == "shipped"
    assert order["tracking_number"] == "TCS-99887766"
    assert order["total"] == "4750.50"


def test_a_deleted_product_is_removed(acme: Tenant) -> None:
    _connect(acme)
    _deliver(acme.client, "products/create", shopify_product_payload())

    _deliver(acme.client, "products/delete", {"id": 111})

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 0


def test_deleting_something_that_is_not_there_is_still_a_200(
    acme: Tenant,
) -> None:
    _connect(acme)

    assert _deliver(acme.client, "products/delete", {"id": 999}).status_code == 200


def test_a_forged_delivery_is_refused(acme: Tenant) -> None:
    _connect(acme)

    response = _deliver(
        acme.client,
        "products/update",
        shopify_product_payload(),
        secret="not the app secret",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "invalid_webhook_signature"


def test_a_topic_nothing_handles_is_acknowledged(acme: Tenant) -> None:
    # A subscription is easy to widen by accident, and a delivery that can
    # never be acted on must not be retried for a day.
    _connect(acme)

    response = _deliver(acme.client, "customers/create", {"id": 1})

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_a_delivery_for_a_shop_we_do_not_hold_is_acknowledged(
    acme: Tenant,
) -> None:
    response = _deliver(
        acme.client,
        "products/update",
        shopify_product_payload(),
        shop="stranger.myshopify.com",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_one_shops_delivery_never_reaches_another_workspace(
    acme: Tenant,
    rival: Tenant,
) -> None:
    _connect(acme)
    _connect(rival, "rival-store.myshopify.com")

    _deliver(acme.client, "products/update", shopify_product_payload(), shop=SHOP)

    theirs = rival.client.get(
        rival.path("products"),
        headers=rival.owner_headers,
    ).json()
    assert theirs["total"] == 0


# --- disconnecting --------------------------------------------------------


def test_disconnecting_keeps_what_was_synced(acme: Tenant) -> None:
    _connect(acme)
    _deliver(acme.client, "products/create", shopify_product_payload())

    response = acme.client.delete(
        acme.path("integrations", "shopify"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 204
    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 1


def test_disconnecting_destroys_the_token(
    acme: Tenant,
    ecommerce_account_repository: EcommerceAccountRepository,
    db_session: Session,
) -> None:
    _connect(acme)

    acme.client.delete(
        acme.path("integrations", "shopify"),
        headers=acme.owner_headers,
    )

    db_session.expire_all()
    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert account.credentials_encrypted == ""
    assert account.status is EcommerceAccountStatus.DISCONNECTED


def test_an_uninstall_webhook_disconnects_it(
    acme: Tenant,
    ecommerce_account_repository: EcommerceAccountRepository,
    db_session: Session,
) -> None:
    _connect(acme)

    response = _deliver(acme.client, "app/uninstalled", {"id": 1})

    assert response.status_code == 200
    db_session.expire_all()
    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert account.status is EcommerceAccountStatus.DISCONNECTED


def test_an_uninstall_for_a_shop_we_never_had_is_still_a_200(
    acme: Tenant,
) -> None:
    response = _deliver(
        acme.client,
        "app/uninstalled",
        {"id": 1},
        shop="stranger.myshopify.com",
    )

    assert response.status_code == 200


def test_a_disconnected_shop_stops_being_synced(acme: Tenant) -> None:
    _connect(acme)
    _deliver(acme.client, "app/uninstalled", {"id": 1})

    _deliver(acme.client, "products/create", shopify_product_payload())

    listed = acme.client.get(
        acme.path("products"),
        headers=acme.owner_headers,
    ).json()
    assert listed["total"] == 0


def test_reinstalling_reuses_the_connection(
    acme: Tenant,
    ecommerce_account_repository: EcommerceAccountRepository,
    db_session: Session,
) -> None:
    # A shop that comes back should pick up where it left off, not arrive
    # as a stranger with a duplicate row.
    _connect(acme)
    _deliver(acme.client, "app/uninstalled", {"id": 1})

    _connect(acme)

    db_session.expire_all()
    account = ecommerce_account_repository.get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert account is not None
    assert account.status is EcommerceAccountStatus.CONNECTED


# --- the adapter itself ---------------------------------------------------


def test_shopify_status_is_read_the_way_a_shop_would_read_it() -> None:
    provider = ShopifyProvider()

    def status(**fields: object) -> str:
        event = provider.parse_webhook(
            topic="orders/updated",
            shop=SHOP,
            payload=shopify_order_payload(**fields),  # type: ignore[arg-type]
        )
        assert event.order is not None

        return event.order.status

    assert status(financial_status="pending") == "pending"
    assert status(financial_status="paid") == "confirmed"
    assert status(fulfillment_status="fulfilled") == "shipped"
    assert status(financial_status="refunded") == "refunded"
    assert status(cancelled_at="2026-08-27T10:00:00+00:00") == "cancelled"


def test_shopify_html_descriptions_arrive_as_words() -> None:
    event = ShopifyProvider().parse_webhook(
        topic="products/update",
        shop=SHOP,
        payload=shopify_product_payload(),
    )

    assert event.product is not None
    assert event.product.description == "Heavyweight cotton"
