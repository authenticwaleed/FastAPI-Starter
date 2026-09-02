"""Phase A5 acceptance: granting a plan the payment provider disagrees with.

The problem this phase solves is one line of the plan and easy to miss:
`Subscription.plan` is a copy of what the provider said, kept current by
webhooks -- so a tier written into it by hand survives until the next
delivery and then reverts, silently. A separate row is the fix, and the
tests that matter are the ones about the two never fighting.

Two answers to one question is the risk this introduces: `plan_for`
resolves it one workspace at a time in Python and `entitled_plan`
resolves it for every workspace at once in SQL. The last test in this
file holds the two side by side on every combination that matters.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.integrations.billing.base import (
    BillingEventKind,
    BillingEventPayload,
    RemoteSubscription,
)
from app.models.admin_audit_log import AdminAction
from app.models.plan_override import PlanOverride
from app.models.staff_member import StaffRole
from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.repositories.plan_override_repository import PlanOverrideRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from tests.support.services import subscription_service
from tests.support.staff import Console, entries
from tests.support.tenants import Tenant

REASON = "Pilot until the March contract lands"


@pytest.fixture
def admin(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-admin@example.com", StaffRole.ADMIN)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _grant(admin: Console, tenant: Tenant, **body: Any) -> Any:
    return admin.post(
        f"/workspaces/{tenant.workspace_id}/plan-override",
        {"plan": PlanTier.BUSINESS.value, "reason": REASON} | body,
    )


def _plan_in_console(admin: Console, tenant: Tenant) -> str:
    body = admin.get(f"/workspaces/{tenant.workspace_id}").json()

    return str(body["plan"])


def _plan_in_service(session: Session, tenant: Tenant) -> PlanTier:
    return subscription_service(session).plan_for(uuid.UUID(tenant.workspace_id)).tier


# --- an override outranks the provider --------------------------------------


def test_a_granted_plan_outranks_what_the_provider_says(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    acme.on_plan(db_session, PlanTier.STARTER)

    assert _grant(admin, acme).status_code == 201

    assert _plan_in_service(db_session, acme) == PlanTier.BUSINESS
    assert _plan_in_console(admin, acme) == PlanTier.BUSINESS.value


def test_a_provider_webhook_afterwards_does_not_disturb_it(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The failure the whole design exists to prevent.

    Writing the tier onto `subscriptions.plan` would survive exactly
    until this delivery, and then revert -- and somebody would find out
    when the customer wrote in about features disappearing.
    """
    acme.on_plan(db_session, PlanTier.STARTER)
    _grant(admin, acme)

    subscriptions = SubscriptionRepository(db_session)
    subscription = subscriptions.get_for_workspace(uuid.UUID(acme.workspace_id))
    assert subscription is not None
    assert subscription.provider_subscription_id is not None

    subscription_service(db_session).apply_event(
        BillingEventPayload(
            event_id="evt_after_the_grant",
            event_type="customer.subscription.updated",
            kind=BillingEventKind.SUBSCRIPTION_UPDATED,
            subscription=RemoteSubscription(
                provider_subscription_id=subscription.provider_subscription_id,
                plan=PlanTier.STARTER,
                status=SubscriptionStatus.ACTIVE,
            ),
        )
    )

    # The provider's column moved, and what the workspace may do did not.
    assert subscription.plan == PlanTier.STARTER
    assert _plan_in_service(db_session, acme) == PlanTier.BUSINESS


def test_removing_a_grant_falls_back_to_the_provider(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    acme.on_plan(db_session, PlanTier.GROWTH)
    _grant(admin, acme)

    assert (
        admin.delete(f"/workspaces/{acme.workspace_id}/plan-override").status_code
        == 204
    )
    assert _plan_in_service(db_session, acme) == PlanTier.GROWTH


def test_removing_a_grant_from_a_workspace_that_never_paid_falls_to_free(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    _grant(admin, acme)
    admin.delete(f"/workspaces/{acme.workspace_id}/plan-override")

    assert _plan_in_service(db_session, acme) == PlanTier.STARTER


def test_an_expired_grant_stops_applying_with_nothing_having_to_run(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The acceptance criterion, and the reason there is no status column.

    A row with a date behind it stops matching the lookup. No sweep, no
    job, no flag anybody has to keep in step.
    """
    _grant(admin, acme)
    override = PlanOverrideRepository(db_session).get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert override is not None
    override.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    assert _plan_in_service(db_session, acme) == PlanTier.STARTER
    assert _plan_in_console(admin, acme) == PlanTier.STARTER.value


def test_granting_twice_replaces_rather_than_stacks(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # One granted plan per workspace, so it stays something that can be
    # spoken about in the singular.
    _grant(admin, acme, plan=PlanTier.GROWTH.value)
    _grant(admin, acme, plan=PlanTier.BUSINESS.value)

    assert _plan_in_service(db_session, acme) == PlanTier.BUSINESS
    assert len(list(PlanOverrideRepository(db_session).list_all())) == 1


def test_a_grant_with_no_end_says_so(admin: Console, acme: Tenant) -> None:
    # Allowed, because comps somebody negotiated are real -- and warned
    # about, because a plan nothing ever takes away is worth being told
    # about rather than found on a revenue report two years later.
    body = _grant(admin, acme).json()

    assert body["forever"] is True
    assert body["applies"] is True

    dated = _grant(
        admin,
        acme,
        expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    ).json()

    assert dated["forever"] is False


def test_a_reason_is_required_to_grant_a_plan(admin: Console, acme: Tenant) -> None:
    # Read by the next person who wonders why this business is on
    # Business without paying for it.
    response = admin.post(
        f"/workspaces/{acme.workspace_id}/plan-override",
        {"plan": PlanTier.BUSINESS.value, "reason": "comp"},
    )

    assert response.status_code == 422


def test_granting_is_recorded_but_not_in_the_customers_log(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """A comp is a commercial arrangement, not an act on their account.

    An entry saying the platform changed their plan -- when what changed
    is that they stop being charged for it -- would raise a question
    rather than answer one.
    """
    _grant(admin, acme)

    (recorded,) = entries(db_session, AdminAction.PLAN_OVERRIDE_GRANTED)

    assert recorded.meta["plan"] == PlanTier.BUSINESS.value
    assert recorded.meta["reason"] == REASON
    assert recorded.workspace_slug == "acme-fashion"

    # Asserted on the contents rather than on a 402, and the reason is
    # itself the phase working: granting Business *entitles* this
    # workspace to its audit log, so the route now answers. What matters
    # is that the grant put nothing in it.
    tenant_log = acme.client.get(acme.path("audit-logs"), headers=acme.owner_headers)

    assert tenant_log.status_code == 200
    assert [item["event"] for item in tenant_log.json()["items"]] == [
        "workspace.created"
    ]


# --- the provider's ledger --------------------------------------------------


def test_the_subscription_list_names_its_workspaces(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    acme.on_plan(db_session, PlanTier.GROWTH)

    body = admin.get("/billing/subscriptions").json()

    assert body["total"] == 1
    assert body["items"][0]["workspace_slug"] == "acme-fashion"
    assert body["items"][0]["provider_customer_id"].startswith("cus_")


def test_the_ledger_shows_what_the_provider_says_not_what_was_granted(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # The point of this screen. A business comped onto Business appears
    # here on whatever it is actually paying for.
    acme.on_plan(db_session, PlanTier.STARTER)
    _grant(admin, acme)

    body = admin.get("/billing/subscriptions", plan=PlanTier.STARTER.value).json()

    assert body["total"] == 1
    assert body["items"][0]["plan"] == PlanTier.STARTER.value


def test_a_delivery_is_kept_and_can_be_replayed(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """For the deliveries recorded and not acted on.

    Here the subscription is moved out from under the stored payload, and
    the replay puts it back -- which is what re-applying a delivery means.
    """
    acme.on_plan(db_session, PlanTier.STARTER)
    subscriptions = SubscriptionRepository(db_session)
    subscription = subscriptions.get_for_workspace(uuid.UUID(acme.workspace_id))
    assert subscription is not None
    assert subscription.provider_subscription_id is not None

    subscription_service(db_session).apply_event(
        BillingEventPayload(
            event_id="evt_upgrade",
            event_type="customer.subscription.updated",
            kind=BillingEventKind.SUBSCRIPTION_UPDATED,
            subscription=RemoteSubscription(
                provider_subscription_id=subscription.provider_subscription_id,
                plan=PlanTier.BUSINESS,
                status=SubscriptionStatus.ACTIVE,
            ),
        )
    )
    assert subscription.plan == PlanTier.BUSINESS

    listed = admin.get("/billing/events").json()
    assert listed["total"] == 1
    assert listed["items"][0]["replayable"] is True
    event_id = listed["items"][0]["id"]

    # Something moves it away, and the replay brings it back.
    subscription.plan = PlanTier.STARTER
    db_session.flush()

    replayed = admin.post(f"/billing/events/{event_id}/replay", {})

    assert replayed.status_code == 200
    assert replayed.json()["applied"] is True
    assert subscription.plan == PlanTier.BUSINESS


def test_replaying_does_not_defeat_the_dedupe(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The acceptance criterion, and the subtle one.

    The claim row exists to stop a provider *retry* being applied twice.
    A replay must leave it alone, or every replay would be a way of
    losing that protection -- and replaying twice must land on the same
    values, which it does because what is applied is the provider's own
    snapshot.
    """
    acme.on_plan(db_session, PlanTier.STARTER)
    subscriptions = SubscriptionRepository(db_session)
    subscription = subscriptions.get_for_workspace(uuid.UUID(acme.workspace_id))
    assert subscription is not None
    assert subscription.provider_subscription_id is not None

    delivery = BillingEventPayload(
        event_id="evt_once",
        event_type="customer.subscription.updated",
        kind=BillingEventKind.SUBSCRIPTION_UPDATED,
        subscription=RemoteSubscription(
            provider_subscription_id=subscription.provider_subscription_id,
            plan=PlanTier.GROWTH,
            status=SubscriptionStatus.ACTIVE,
        ),
    )
    subscription_service(db_session).apply_event(delivery)

    event_id = admin.get("/billing/events").json()["items"][0]["id"]

    admin.post(f"/billing/events/{event_id}/replay", {})
    admin.post(f"/billing/events/{event_id}/replay", {})

    # One claim row still, so the provider retrying this delivery is
    # still refused.
    assert subscriptions.count_events() == 1
    assert subscription_service(db_session).apply_event(delivery) is False
    # And the state is where the snapshot says, however many replays.
    assert subscription.plan == PlanTier.GROWTH


def test_a_delivery_from_before_payloads_were_kept_is_not_replayable(
    admin: Console,
    db_session: Session,
) -> None:
    # Honest rather than a button that answers "nothing happened":
    # reconstructing one from the subscription's current state would
    # replay something the provider never sent.
    SubscriptionRepository(db_session).record_event(
        provider=BillingProviderName.STRIPE,
        provider_event_id="evt_from_before",
        event_type="customer.subscription.updated",
    )
    db_session.flush()

    listed = admin.get("/billing/events").json()
    assert listed["items"][0]["replayable"] is False

    replayed = admin.post(f"/billing/events/{listed['items'][0]['id']}/replay", {})

    assert replayed.json()["applied"] is False


def test_support_may_not_read_the_ledger_or_grant_a_plan(
    client: TestClient,
    db_session: Session,
    acme: Tenant,
) -> None:
    # Neither is a support question. Reading who pays what and granting a
    # plan nobody pays for are both commercial decisions.
    console = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)

    assert console.get("/billing/subscriptions").status_code == 403
    assert (
        console.post(
            f"/workspaces/{acme.workspace_id}/plan-override",
            {"plan": PlanTier.BUSINESS.value, "reason": REASON},
        ).status_code
        == 403
    )


# --- the two resolutions must agree -----------------------------------------


@pytest.mark.parametrize(
    ("subscribed", "status", "granted", "expected"),
    [
        (None, None, None, PlanTier.STARTER),
        (PlanTier.GROWTH, SubscriptionStatus.ACTIVE, None, PlanTier.GROWTH),
        (PlanTier.GROWTH, SubscriptionStatus.PAST_DUE, None, PlanTier.GROWTH),
        (PlanTier.GROWTH, SubscriptionStatus.CANCELED, None, PlanTier.STARTER),
        (PlanTier.GROWTH, SubscriptionStatus.UNPAID, None, PlanTier.STARTER),
        (None, None, PlanTier.BUSINESS, PlanTier.BUSINESS),
        (
            PlanTier.STARTER,
            SubscriptionStatus.ACTIVE,
            PlanTier.BUSINESS,
            PlanTier.BUSINESS,
        ),
        (
            PlanTier.BUSINESS,
            SubscriptionStatus.CANCELED,
            PlanTier.GROWTH,
            PlanTier.GROWTH,
        ),
    ],
)
def test_python_and_sql_resolve_the_same_plan(
    admin: Console,
    acme: Tenant,
    db_session: Session,
    subscribed: PlanTier | None,
    status: SubscriptionStatus | None,
    granted: PlanTier | None,
    expected: PlanTier,
) -> None:
    """One question asked in two languages, on every combination that matters.

    `plan_for` answers it one workspace at a time in Python and
    `entitled_plan` answers it for every workspace at once in SQL. They
    share the statuses and the free tier, so what is left to drift is the
    shape -- and this is what would catch it.
    """
    if subscribed is not None:
        acme.on_plan(db_session, subscribed)

        if status is not None:
            subscription = SubscriptionRepository(db_session).get_for_workspace(
                uuid.UUID(acme.workspace_id)
            )
            assert subscription is not None
            subscription.status = status
            db_session.flush()

    if granted is not None:
        db_session.add(
            PlanOverride(
                workspace_id=uuid.UUID(acme.workspace_id),
                plan=granted,
                reason=REASON,
            )
        )
        db_session.flush()

    assert _plan_in_service(db_session, acme) == expected
    assert _plan_in_console(admin, acme) == expected.value
