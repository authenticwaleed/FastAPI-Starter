"""Phase A7 acceptance: aggregates, and nothing that names a customer.

Last in the plan and deliberately so -- the most fun to build and the
least urgent, and building it early produces a dashboard nobody can act
on.

One rule runs through the whole phase and is worth more than the figures:
**no route here reveals one customer's data.** It is asserted over the
published paths rather than trusted, because a dashboard is exactly where
somebody would later add "and show me which workspaces" without noticing
what that changes.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAction
from app.models.ai_response_log import AiDecision, AiResponseLog
from app.models.staff_member import StaffRole
from app.models.workspace import Workspace, WorkspaceStatus
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from tests.support.staff import ADMIN, Console, entries, operations
from tests.support.tenants import Tenant

ANALYTICS = f"{ADMIN}/analytics"


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


# --- the rule ---------------------------------------------------------------


def test_no_analytics_route_takes_a_workspace(admin: Console) -> None:
    """The phase's rule, over the published paths.

    A dashboard is exactly where somebody would later add "and show me
    which workspaces" without noticing that it turns an aggregate page
    into a page about one customer.
    """
    analytics = [path for _, path in operations() if path.startswith(ANALYTICS)]

    assert len(analytics) == 4
    assert not [path for path in analytics if "{" in path]


def test_no_analytics_response_names_a_customer(
    admin: Console,
    acme: Tenant,
) -> None:
    # Every figure is a count grouped by a status, a plan or a day. A
    # slug, a name or an address appearing here would mean one of those
    # groupings had become an id.
    acme.contact("+923001234567", full_name="Ayesha Khan")

    for page in ("overview", "growth", "revenue", "ai"):
        body = admin.get(f"/analytics/{page}").text

        assert "acme-fashion" not in body, page
        assert "Ayesha" not in body, page
        assert acme.workspace_id not in body, page


# --- what the figures say ---------------------------------------------------


def test_the_overview_counts_workspaces_by_status_and_plan(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    acme.on_plan(db_session, PlanTier.GROWTH)

    body = admin.get("/analytics/overview").json()

    assert body["counts"]["workspaces"] == 1
    assert body["workspaces_by_status"][WorkspaceStatus.ACTIVE.value] == 1
    assert body["workspaces_by_plan"][PlanTier.GROWTH.value] == 1


def test_the_overview_counts_by_what_is_paid_rather_than_what_is_granted(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """A commercial number, so a comped workspace is not revenue.

    The console's own workspace search answers the entitlement question;
    this page answers the money one, and they disagree on purpose.
    """
    acme.on_plan(db_session, PlanTier.STARTER)
    admin.post(
        f"/workspaces/{acme.workspace_id}/plan-override",
        {"plan": PlanTier.BUSINESS.value, "reason": "Pilot until March"},
    )

    body = admin.get("/analytics/overview").json()

    assert body["workspaces_by_plan"].get(PlanTier.STARTER.value) == 1
    assert PlanTier.BUSINESS.value not in body["workspaces_by_plan"]
    # And the console, asked the entitlement question, says the other.
    assert admin.get(f"/workspaces/{acme.workspace_id}").json()["plan"] == (
        PlanTier.BUSINESS.value
    )


def test_growth_counts_use_rather_than_rows(
    admin: Console,
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    """The number a headline count cannot give.

    A platform with two workspaces and none that sent a message knows
    something that "two workspaces" hides.
    """
    Tenant(client, user_repository, membership_repository, "beta-goods")

    body = admin.get("/analytics/growth").json()

    assert sum(point["count"] for point in body["signups"]) == 2
    # Neither has sent anything, so neither is active -- which is the
    # distinction the whole figure exists for.
    assert body["active_workspaces"] == 0


def test_closures_appear_once_an_account_is_closed(
    admin: Console,
    acme: Tenant,
) -> None:
    admin.post(
        f"/workspaces/{acme.workspace_id}/cancel", {"confirm_slug": "acme-fashion"}
    )

    body = admin.get("/analytics/growth").json()

    assert sum(point["count"] for point in body["closures"]) == 1


def test_the_window_is_bounded(admin: Console) -> None:
    # Every one of these scans a table that only grows, so a request for
    # five years is a request that takes the database with it.
    assert admin.get("/analytics/growth", days=365).status_code == 200
    assert admin.get("/analytics/growth", days=366).status_code == 422
    assert admin.get("/analytics/growth", days=0).status_code == 422


def test_revenue_counts_subscriptions_rather_than_pricing_them(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """No amount anywhere.

    What a plan costs lives in plans.py, and multiplying belongs where
    the prices are -- a figure computed in SQL would need editing every
    time one changed and be quietly wrong in between.
    """
    acme.on_plan(db_session, PlanTier.BUSINESS)

    body = admin.get("/analytics/revenue").json()

    assert body["paying_by_plan"][PlanTier.BUSINESS.value] == 1
    assert body["subscriptions_by_status"]["active"] == 1
    assert "amount" not in body
    assert "revenue" not in body
    assert "usd" not in admin.get("/analytics/revenue").text.lower()


def test_ai_spend_is_in_tokens_and_says_which_model(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The number the plan says decides whether the pricing works.

    In tokens rather than money: what a token costs is a contract that
    changes without a redeploy and differs per model, so a dollar figure
    computed here would look authoritative and be wrong within a quarter.
    """
    # A real thread: `ai_response_logs` carries a composite foreign key
    # tying the conversation to the same workspace, which is the tenant
    # boundary drawn in the schema rather than in code.
    conversation_id = acme.client.post(
        acme.path("conversations"),
        json={"contact_id": acme.contact()},
        headers=acme.owner_headers,
    ).json()["id"]

    db_session.add(
        AiResponseLog(
            workspace_id=uuid.UUID(acme.workspace_id),
            conversation_id=uuid.UUID(conversation_id),
            decision=AiDecision.ANSWERED,
            prompt_version="v1",
            model="claude-opus-5",
            input_tokens=1200,
            output_tokens=300,
            latency_ms=850,
        )
    )
    db_session.flush()

    body = admin.get("/analytics/ai").json()

    assert body["replies"] == 1
    assert body["input_tokens"] == 1200
    assert body["output_tokens"] == 300
    assert body["by_model"] == {"claude-opus-5": 1}
    # Tokens per reply is the figure that moves when a prompt grows, and
    # it moves before the bill does.
    assert body["average_latency_ms"] == 850.0


def test_an_empty_platform_answers_cleanly(admin: Console) -> None:
    # Every one of these runs on the day the product launches, when there
    # is nothing to count.
    for page in ("overview", "growth", "revenue", "ai"):
        assert admin.get(f"/analytics/{page}").status_code == 200, page

    ai = admin.get("/analytics/ai").json()

    assert ai["replies"] == 0
    assert ai["input_tokens"] is None


def test_analytics_is_admin_only(client: TestClient, db_session: Session) -> None:
    # The one place on this surface where the rank is about seniority
    # rather than safety: nothing here reveals a customer, and a revenue
    # chart is still not a support tool.
    console = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)

    assert console.get("/analytics/overview").status_code == 403


def test_every_analytics_read_is_recorded(
    admin: Console,
    db_session: Session,
) -> None:
    # Recorded although these reveal nothing about any one customer: the
    # rule is about the surface, and an exception would be the first
    # crack in it.
    admin.get("/analytics/overview")
    admin.get("/analytics/ai", days=7)

    recorded = entries(db_session, AdminAction.ANALYTICS_READ)

    assert [entry.meta["page"] for entry in recorded] == ["overview", "ai"]
    assert recorded[1].meta["days"] == 7


def test_a_day_is_utc_and_says_so(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # A platform-wide chart cannot be in every customer's local day at
    # once. Worth a test because a reader who assumes local time reads
    # the edges of every chart wrongly.
    workspace = db_session.get(Workspace, uuid.UUID(acme.workspace_id))
    assert workspace is not None
    workspace.created_at = datetime(2026, 9, 1, 23, 30, tzinfo=UTC)
    db_session.flush()

    body = admin.get(
        "/analytics/growth",
        days=(datetime.now(UTC) - datetime(2026, 9, 1, tzinfo=UTC)).days + 2,
    ).json()

    assert any(point["day"] == "2026-09-01" for point in body["signups"])
