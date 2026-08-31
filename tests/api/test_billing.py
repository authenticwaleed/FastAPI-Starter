"""Phase 24: what a workspace is paying for, and what that lets it do.

Four things the phase is judged on -- subscription state synced, webhook
idempotency, feature limits enforced centrally, billing failure states
handled -- and the fourth is the one worth reading the tests for. A card
that did not go through is a provider still retrying, and taking a
business's features away over a bank's fraud check is the wrong way to
lose a customer.
"""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.workspace_membership import WorkspaceRole
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from tests.support.billing import (
    FakeBillingProvider,
    invoice_failed_event,
    subscription_event,
)
from tests.support.tenants import Tenant

PLANS = "/api/v1/plans"
WEBHOOK = "/api/v1/webhooks/billing"


@pytest.fixture
def subscription_repository(db_session: Session) -> SubscriptionRepository:
    return SubscriptionRepository(db_session)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _deliver(client: TestClient, event: dict, *, secret: str | None = None):
    body = json.dumps(event).encode()
    configured = get_settings().stripe_webhook_secret
    assert configured is not None
    signing = secret if secret is not None else configured.get_secret_value()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        signing.encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()

    return client.post(
        WEBHOOK,
        content=body,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": f"t={timestamp},v1={digest}",
        },
    )


def _subscribe(
    tenant: Tenant,
    plan: PlanTier = PlanTier.GROWTH,
    status: str = "active",
) -> None:
    """Buy a plan the way a customer would: checkout, then the webhook."""
    response = tenant.client.post(
        tenant.path("subscription", "checkout"),
        json={"plan": plan.value},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 200, response.text

    delivered = _deliver(
        tenant.client,
        subscription_event(
            event_id=f"evt_{uuid.uuid4().hex[:10]}",
            plan=plan,
            status=status,
        ),
    )
    assert delivered.status_code == 200, delivered.text


def _plan_of(tenant: Tenant) -> dict:
    return tenant.client.get(
        tenant.path("subscription"),
        headers=tenant.owner_headers,
    ).json()


# --- the price list -------------------------------------------------------


def test_the_plans_are_public(client: TestClient) -> None:
    # Whoever is deciding whether to sign up has no account yet, and
    # asking them to make one to see what it costs is the wrong way round.
    response = client.get(PLANS)

    assert response.status_code == 200
    assert [plan["tier"] for plan in response.json()] == [
        "starter",
        "growth",
        "business",
    ]


def test_a_plan_says_what_it_includes_and_what_it_limits(
    client: TestClient,
) -> None:
    plans = {plan["tier"]: plan for plan in client.get(PLANS).json()}

    assert "automations" in plans["growth"]["features"]
    assert "automations" not in plans["starter"]["features"]
    assert plans["starter"]["limits"]["team_members"] == 2
    # Null is unlimited, and present rather than absent: a comparison
    # table needs a row for every limit on every plan.
    assert plans["business"]["limits"]["team_members"] is None


# --- what a workspace is on -----------------------------------------------


def test_a_new_workspace_is_on_the_free_plan(acme: Tenant) -> None:
    body = _plan_of(acme)

    assert body["plan"]["tier"] == "starter"
    # Never subscribed is not the same as a subscription that lapsed, and
    # a dashboard needs to tell them apart.
    assert body["subscription"] is None


def test_any_member_may_see_the_plan(acme: Tenant) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.get(acme.path("subscription"), headers=agent)

    assert response.status_code == 200


def test_another_workspaces_plan_is_not_visible(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")

    response = acme.client.get(
        acme.path("subscription"),
        headers=rival.owner_headers,
    )

    assert response.status_code == 404


# --- buying ---------------------------------------------------------------


def test_checkout_returns_somewhere_to_pay(
    acme: Tenant,
    billing_provider: FakeBillingProvider,
) -> None:
    response = acme.client.post(
        acme.path("subscription", "checkout"),
        json={"plan": "growth"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["checkout_url"] == billing_provider.checkout_url


def test_checkout_changes_nothing_by_itself(acme: Tenant) -> None:
    # The card is entered on the provider's page. What makes a
    # subscription real is the webhook that follows.
    acme.client.post(
        acme.path("subscription", "checkout"),
        json={"plan": "growth"},
        headers=acme.owner_headers,
    )

    assert _plan_of(acme)["plan"]["tier"] == "starter"


def test_the_free_plan_cannot_be_checked_out(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("subscription", "checkout"),
        json={"plan": "starter"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 502


def test_an_agent_may_not_spend_the_businesss_money(acme: Tenant) -> None:
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.post(
        acme.path("subscription", "checkout"),
        json={"plan": "growth"},
        headers=agent,
    )

    assert response.status_code == 403


def test_coming_back_reuses_the_same_customer(
    acme: Tenant,
    billing_provider: FakeBillingProvider,
) -> None:
    # A business that cancels and returns should not become a second
    # customer with a second billing history.
    _subscribe(acme)

    acme.client.post(
        acme.path("subscription", "checkout"),
        json={"plan": "business"},
        headers=acme.owner_headers,
    )

    assert billing_provider.checkouts[-1][1] == billing_provider.customer_id


# --- what the provider says -----------------------------------------------


def test_the_webhook_puts_the_workspace_on_its_plan(acme: Tenant) -> None:
    _subscribe(acme)

    body = _plan_of(acme)
    assert body["plan"]["tier"] == "growth"
    assert body["subscription"]["status"] == "active"
    assert body["subscription"]["current_period_end"]


def test_the_same_delivery_twice_is_applied_once(
    acme: Tenant,
    subscription_repository: SubscriptionRepository,
) -> None:
    # The one place in this application where a repeat is not merely
    # untidy: what is being got wrong is what somebody is charged.
    acme.client.post(
        acme.path("subscription", "checkout"),
        json={"plan": "growth"},
        headers=acme.owner_headers,
    )
    event = subscription_event(event_id="evt_same", plan=PlanTier.GROWTH)

    first = _deliver(acme.client, event)
    second = _deliver(acme.client, event)

    assert first.json()["status"] == "applied"
    assert second.json()["status"] == "ignored"
    assert second.status_code == 200


def test_a_later_change_is_applied(acme: Tenant) -> None:
    _subscribe(acme, PlanTier.GROWTH)

    _deliver(
        acme.client,
        subscription_event(event_id="evt_up", plan=PlanTier.BUSINESS),
    )

    assert _plan_of(acme)["plan"]["tier"] == "business"


def test_a_forged_delivery_is_refused(acme: Tenant) -> None:
    response = _deliver(
        acme.client,
        subscription_event(),
        secret="not the signing secret",
    )

    assert response.status_code == 403


def test_a_delivery_signed_long_ago_is_refused(acme: Tenant) -> None:
    # The timestamp is inside what is signed precisely so a delivery
    # captured today cannot be replayed next week.
    body = json.dumps(subscription_event()).encode()
    secret = get_settings().stripe_webhook_secret
    assert secret is not None
    stale = str(int(time.time()) - 3600)
    digest = hmac.new(
        secret.get_secret_value().encode(),
        f"{stale}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()

    response = acme.client.post(
        WEBHOOK,
        content=body,
        headers={"Stripe-Signature": f"t={stale},v1={digest}"},
    )

    assert response.status_code == 403


def test_a_topic_nothing_handles_is_acknowledged(acme: Tenant) -> None:
    response = _deliver(
        acme.client,
        {"id": "evt_x", "type": "customer.created", "data": {"object": {}}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_a_subscription_we_do_not_hold_is_acknowledged(
    acme: Tenant,
) -> None:
    response = _deliver(
        acme.client,
        subscription_event(
            subscription_id="sub_STRANGER",
            customer_id="cus_STRANGER",
        ),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_the_billing_webhook_still_has_its_own_path(
    client: TestClient,
) -> None:
    # `/webhooks/{provider}` is a storefront enum, and this path is a
    # literal registered before it -- so this must not become a 422.
    response = client.post(WEBHOOK, content=b"{}")

    assert response.status_code == 403


# --- billing failure states -----------------------------------------------


def test_a_failed_payment_does_not_take_the_plan_away(acme: Tenant) -> None:
    # The provider is still retrying. Taking a business's features away
    # over a bank's fraud check is the wrong way to lose a customer.
    _subscribe(acme)

    _deliver(acme.client, invoice_failed_event(event_id="evt_fail"))

    body = _plan_of(acme)
    assert body["subscription"]["status"] == "past_due"
    assert body["plan"]["tier"] == "growth"


def test_a_failed_payment_tells_the_administrators(acme: Tenant) -> None:
    _subscribe(acme)

    _deliver(acme.client, invoice_failed_event(event_id="evt_fail"))

    feed = acme.client.get(
        "/api/v1/notifications",
        headers=acme.owner_headers,
    ).json()
    assert feed["items"][0]["kind"] == "billing_payment_failed"


def test_a_subscription_that_ends_falls_back_to_the_free_plan(
    acme: Tenant,
) -> None:
    # Back to free rather than to nothing: a declined card must not lock
    # a business out of its own inbox.
    _subscribe(acme)

    _deliver(
        acme.client,
        subscription_event(
            event_id="evt_gone",
            event_type="customer.subscription.deleted",
            status="canceled",
        ),
    )

    body = _plan_of(acme)
    assert body["plan"]["tier"] == "starter"
    assert body["subscription"]["status"] == "canceled"


def test_an_unpaid_subscription_falls_back_too(acme: Tenant) -> None:
    _subscribe(acme)

    _deliver(
        acme.client,
        subscription_event(event_id="evt_unpaid", status="unpaid"),
    )

    assert _plan_of(acme)["plan"]["tier"] == "starter"


# --- cancelling -----------------------------------------------------------


def test_cancelling_stops_at_the_end_of_the_period(
    acme: Tenant,
    billing_provider: FakeBillingProvider,
) -> None:
    # Somebody who has paid for a month is entitled to the month.
    _subscribe(acme)

    response = acme.client.post(
        acme.path("subscription", "cancel"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["cancel_at_period_end"] is True
    assert response.json()["status"] == "active"
    assert _plan_of(acme)["plan"]["tier"] == "growth"
    assert billing_provider.cancelled == [billing_provider.subscription_id]


def test_cancelling_without_a_subscription_is_a_404(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("subscription", "cancel"),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "no_subscription"


def test_an_agent_may_not_cancel(acme: Tenant) -> None:
    _subscribe(acme)
    agent = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.post(
        acme.path("subscription", "cancel"),
        headers=agent,
    )

    assert response.status_code == 403


# --- what the plan admits -------------------------------------------------


def test_automations_need_a_plan_that_includes_them(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("automations"),
        json={"kind": "human_handoff", "definition": {}},
        headers=acme.owner_headers,
    )

    assert response.status_code == 402
    assert response.json()["code"] == "feature_not_in_plan"


def test_subscribing_switches_the_feature_on(acme: Tenant) -> None:
    _subscribe(acme)

    response = acme.client.post(
        acme.path("automations"),
        json={"kind": "human_handoff", "definition": {}},
        headers=acme.owner_headers,
    )

    assert response.status_code == 201


def test_a_lapsed_plan_keeps_what_is_already_there_readable(
    acme: Tenant,
) -> None:
    # Losing a feature must not mean losing your data, or your ability to
    # switch off something that is still running.
    _subscribe(acme)
    automation = acme.client.post(
        acme.path("automations"),
        json={"kind": "human_handoff", "definition": {}},
        headers=acme.owner_headers,
    ).json()

    _deliver(
        acme.client,
        subscription_event(event_id="evt_gone", status="canceled"),
    )

    assert (
        acme.client.get(
            acme.path("automations"),
            headers=acme.owner_headers,
        ).status_code
        == 200
    )
    assert (
        acme.client.patch(
            acme.path("automations", automation["id"]),
            json={"status": "disabled"},
            headers=acme.owner_headers,
        ).status_code
        == 200
    )


def test_a_storefront_needs_a_plan_that_includes_one(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("integrations", "shopify", "install"),
        json={"shop_domain": "acme.myshopify.com"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 402


def test_a_stranger_is_told_the_workspace_does_not_exist(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    # Membership is established before the plan is consulted, so a
    # stranger guessing at an id learns nothing about what it pays for.
    rival = Tenant(client, user_repository, membership_repository, "rival-store")

    response = acme.client.post(
        acme.path("automations"),
        json={"kind": "human_handoff", "definition": {}},
        headers=rival.owner_headers,
    )

    assert response.status_code == 404


# --- what the plan limits -------------------------------------------------


def test_a_team_fills_up(acme: Tenant) -> None:
    # Starter allows two, and the owner is one of them.
    response = acme.client.post(
        acme.path("invitations"),
        json={"email": "one@example.com", "role": "agent"},
        headers=acme.owner_headers,
    )
    assert response.status_code == 201

    acme.member("two@example.com", WorkspaceRole.AGENT)

    response = acme.client.post(
        acme.path("invitations"),
        json={"email": "three@example.com", "role": "agent"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 402
    assert response.json()["code"] == "plan_limit_reached"
    # The number is in the message: "you have reached the limit" without
    # saying what it is leaves somebody guessing at what to delete.
    assert "2" in response.json()["detail"]


def test_a_bigger_plan_makes_room(acme: Tenant) -> None:
    acme.member("two@example.com", WorkspaceRole.AGENT)
    _subscribe(acme)

    response = acme.client.post(
        acme.path("invitations"),
        json={"email": "three@example.com", "role": "agent"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 201


def test_a_seat_is_taken_when_an_invitation_is_used(
    acme: Tenant,
    client: TestClient,
) -> None:
    """The check that actually holds the line.

    Inviting is checked as a courtesy, against how many members there are
    at that moment. A team can fill up afterwards -- somebody else joins,
    two people are invited into one remaining place -- so what refuses is
    accepting, because that is when a seat is taken.
    """
    invitation = acme.client.post(
        acme.path("invitations"),
        json={"email": "later@example.com", "role": "agent"},
        headers=acme.owner_headers,
    ).json()
    assert invitation["email"] == "later@example.com"

    # The team fills up between the invitation being sent and being used.
    acme.member("sooner@example.com", WorkspaceRole.AGENT)

    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Later",
            "email": "later@example.com",
            "password": "correct horse battery staple",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={
            "email": "later@example.com",
            "password": "correct horse battery staple",
        },
    ).json()["access_token"]

    response = client.post(
        f"/api/v1/invitations/{invitation['token']}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 402
    assert response.json()["code"] == "plan_limit_reached"
