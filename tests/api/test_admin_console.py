"""Phase A2 acceptance: the console that makes support possible.

Nine reads and no writes, and the line they stop at is the point of the
phase. A support engineer can see that a business has eleven thousand
messages and nothing since March; they cannot see a message. Reading one
needs Phase A3, which is time-boxed and visible to the customer.

Two properties are worth more than the rest and are tested hardest: a
workspace can be found the three ways a ticket actually arrives, and
nothing here returns a credential.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.staff_member import StaffRole
from app.models.subscription import SubscriptionStatus
from app.models.workspace_membership import WorkspaceRole
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from tests.support.staff import ADMIN, Console, operations
from tests.support.tenants import Tenant

TOKEN = "a-provider-token-nobody-should-see"


@pytest.fixture
def console(client: TestClient, db_session: Session) -> Console:
    """A support engineer: the lowest rank, which is what reads this."""
    return Console(client, db_session, "support@example.com", StaffRole.SUPPORT)


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _connect_whatsapp(tenant: Tenant) -> None:
    response = tenant.client.post(
        tenant.path("integrations", "whatsapp", "connect"),
        json={
            "phone_number": "+15550001111",
            "external_phone_number_id": "109876543210987",
            "access_token": TOKEN,
        },
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text


def _search(console: Console, **params: Any) -> dict[str, Any]:
    response = console.get("/workspaces", **params)
    assert response.status_code == 200, response.text

    return dict(response.json())


def _slugs(console: Console, **params: Any) -> list[str]:
    return [item["slug"] for item in _search(console, **params)["items"]]


# --- finding a business -----------------------------------------------------


def test_a_workspace_is_found_by_its_slug(console: Console, acme: Tenant) -> None:
    assert _slugs(console, q="acme-fashion") == ["acme-fashion"]


def test_a_workspace_is_found_by_part_of_its_name(
    console: Console,
    acme: Tenant,
) -> None:
    # Case-insensitive and anywhere in the value, because a ticket says
    # "Acme" and the account is called "Acme Fashion".
    assert _slugs(console, q="acme") == ["acme-fashion"]
    assert _slugs(console, q="ACME") == ["acme-fashion"]


def test_a_workspace_is_found_by_its_owners_address(
    console: Console,
    acme: Tenant,
) -> None:
    # The way a ticket actually arrives: somebody wrote in, and their
    # address is all support has to go on.
    assert _slugs(console, q="owner-acme-fashion@example.com") == ["acme-fashion"]


def test_a_workspace_is_found_by_any_members_address(
    console: Console,
    acme: Tenant,
) -> None:
    # A superset of the plan's "by owner email", and the same thing in
    # practice: whoever writes in is whoever noticed the problem, and is
    # as often an agent as the owner.
    acme.member("agent@example.com", WorkspaceRole.AGENT)

    assert _slugs(console, q="agent@example.com") == ["acme-fashion"]


def test_one_workspace_is_one_row_however_many_members_match(
    console: Console,
    acme: Tenant,
) -> None:
    # An EXISTS rather than a join. A join would return the workspace once
    # per matching member, quietly doubling a page of results.
    acme.member("first@example.com", WorkspaceRole.AGENT)
    acme.member("second@example.com", WorkspaceRole.AGENT)

    assert _slugs(console, q="example.com") == ["acme-fashion"]


def test_a_search_matching_nothing_answers_cleanly(console: Console) -> None:
    page = _search(console, q="nobody-has-this-name")

    assert page["items"] == []
    assert page["total"] == 0


def test_a_wildcard_in_the_term_is_not_a_wildcard(
    console: Console,
    acme: Tenant,
) -> None:
    """Escaped rather than passed through to LIKE.

    Without this, searching for `%` returns every business on the
    platform, and an address with an underscore in it returns other
    people's accounts.
    """
    assert _slugs(console, q="%") == []
    assert _slugs(console, q="acme_fashion") == []
    assert _slugs(console, q="acme-fashion") == ["acme-fashion"]


def test_the_page_is_a_page(
    console: Console,
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    Tenant(client, user_repository, membership_repository, "beta-goods")

    page = _search(console, page=1, page_size=1)

    assert len(page["items"]) == 1
    assert page["total"] == 2


def test_a_workspace_is_found_by_the_plan_it_is_actually_on(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    acme.on_plan(db_session, PlanTier.GROWTH)

    assert _slugs(console, plan=PlanTier.GROWTH.value) == ["acme-fashion"]
    assert _slugs(console, plan=PlanTier.BUSINESS.value) == []


def test_a_workspace_whose_subscription_lapsed_reads_as_free(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The same rule the tenant side applies, asked across every workspace.

    A cancelled subscription entitles a business to nothing, so it is on
    the free plan -- and the console has to say so, or support would tell
    a customer they still have features they have lost.
    """
    acme.on_plan(db_session, PlanTier.BUSINESS)
    subscription = SubscriptionRepository(db_session).get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert subscription is not None
    subscription.status = SubscriptionStatus.CANCELED
    db_session.flush()

    assert _slugs(console, plan=PlanTier.BUSINESS.value) == []
    assert _slugs(console, plan=PlanTier.STARTER.value) == ["acme-fashion"]


def test_a_past_due_subscription_still_entitles_its_plan(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # A card that did not go through is a provider still retrying. Taking
    # a business's plan away over a bank's fraud check is the wrong way to
    # lose a customer, and support must not be told otherwise.
    acme.on_plan(db_session, PlanTier.GROWTH)
    subscription = SubscriptionRepository(db_session).get_for_workspace(
        uuid.UUID(acme.workspace_id)
    )
    assert subscription is not None
    subscription.status = SubscriptionStatus.PAST_DUE
    db_session.flush()

    assert _slugs(console, plan=PlanTier.GROWTH.value) == ["acme-fashion"]


# --- a closed business ------------------------------------------------------


def test_a_cancelled_workspace_is_visible_here_and_gone_to_its_own_api(
    console: Console,
    acme: Tenant,
) -> None:
    """The acceptance criterion, and the difference between the surfaces.

    The tenant boundary answers 404 for a cancelled workspace on purpose.
    Support cannot work that way: "it was closed last week and its data
    goes on the 30th" is the answer to the ticket.
    """
    assert (
        acme.client.delete(acme.path(), headers=acme.owner_headers).status_code == 204
    )

    gone = acme.client.get(acme.path(), headers=acme.owner_headers)
    assert gone.status_code == 404

    found = console.get(f"/workspaces/{acme.workspace_id}")
    assert found.status_code == 200
    assert found.json()["status"] == "cancelled"
    # The date its records are destroyed, which is the whole reason to be
    # able to see a closed account at all.
    assert found.json()["erase_after"] is not None


def test_cancelled_workspaces_can_be_listed_on_their_own(
    console: Console,
    acme: Tenant,
) -> None:
    acme.client.delete(acme.path(), headers=acme.owner_headers)

    assert _slugs(console, status="cancelled") == ["acme-fashion"]
    assert _slugs(console, status="active") == []


# --- what one workspace holds -----------------------------------------------


def test_the_detail_counts_what_the_workspace_holds(
    console: Console,
    acme: Tenant,
) -> None:
    acme.member("agent@example.com", WorkspaceRole.AGENT)
    acme.contact("+923001234567")
    acme.contact("+923009999999")

    body = console.get(f"/workspaces/{acme.workspace_id}").json()

    assert body["counts"]["members"] == 2
    assert body["counts"]["contacts"] == 2
    assert body["counts"]["conversations"] == 0
    assert body["counts"]["messages"] == 0
    assert body["counts"]["knowledge_documents"] == 0


def test_a_workspace_with_no_members_answers_cleanly(
    console: Console,
    acme: Tenant,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    """A real state: the owner closed their account and the business is
    left behind. It has to read rather than error, because it is exactly
    the situation somebody would be searching about.
    """
    owner = user_repository.get_by_email("owner-acme-fashion@example.com")
    assert owner is not None
    user_repository.delete(owner)
    db_session.flush()

    body = console.get(f"/workspaces/{acme.workspace_id}").json()

    assert body["counts"]["members"] == 0
    assert body["owner_email"] is None


def test_an_unknown_workspace_is_a_404(console: Console) -> None:
    response = console.get(f"/workspaces/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_the_member_list_shows_the_team_and_their_roles(
    console: Console,
    acme: Tenant,
) -> None:
    acme.member("agent@example.com", WorkspaceRole.AGENT)

    listed = {
        member["email"]: member["role"]
        for member in console.get(f"/workspaces/{acme.workspace_id}/members").json()
    }

    assert listed["owner-acme-fashion@example.com"] == "owner"
    assert listed["agent@example.com"] == "agent"


# --- billing, usage, integrations -------------------------------------------


def test_a_workspace_that_has_never_paid_reads_as_free(
    console: Console,
    acme: Tenant,
) -> None:
    # Null is not the same as a payment that failed, and the plan says so
    # in both cases.
    body = console.get(f"/workspaces/{acme.workspace_id}/subscription").json()

    assert body["subscription"] is None
    assert body["plan"] == PlanTier.STARTER.value


def test_the_subscription_carries_the_provider_ids_and_no_key(
    console: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The identifiers are how somebody finds the same subscription in the
    provider's dashboard, which is where refunds belong. They are handles,
    not credentials.
    """
    acme.on_plan(db_session, PlanTier.GROWTH)

    body = console.get(f"/workspaces/{acme.workspace_id}/subscription").json()

    assert body["plan"] == PlanTier.GROWTH.value
    assert body["subscription"]["provider_customer_id"].startswith("cus_")
    assert body["subscription"]["provider_subscription_id"].startswith("sub_")
    assert body["subscription"]["status"] == "active"


def test_usage_reads_the_same_meter_the_customer_sees(
    console: Console,
    acme: Tenant,
) -> None:
    body = console.get(f"/workspaces/{acme.workspace_id}/usage").json()

    assert body["period_start"] < body["period_end"]
    assert {metric["metric"] for metric in body["metrics"]} >= {"ai_responses"}


def test_nothing_connected_reads_as_two_nulls(
    console: Console,
    acme: Tenant,
) -> None:
    body = console.get(f"/workspaces/{acme.workspace_id}/integrations").json()

    assert body == {"whatsapp": None, "storefront": None}


def test_a_connected_number_is_shown_without_its_token(
    console: Console,
    acme: Tenant,
) -> None:
    """The rule this phase must not break, as a test over the whole body.

    The token is encrypted at rest and nothing on this surface decrypts
    it. Asserting on the serialised response rather than on named fields,
    because the failure this guards against is a field somebody adds
    later.
    """
    _connect_whatsapp(acme)

    response = console.get(f"/workspaces/{acme.workspace_id}/integrations")
    body = response.json()

    assert body["whatsapp"]["phone_number"] == "+15550001111"
    assert body["whatsapp"]["status"] == "connected"
    assert TOKEN not in response.text
    assert "access_token" not in response.text
    assert "token" not in response.text


def test_the_tenants_own_audit_log_is_readable_without_a_plan(
    console: Console,
    acme: Tenant,
) -> None:
    """Audit logs are a paid feature for a customer.

    Whether support can answer a ticket about a business is not a
    decision that business's plan gets to make -- so this workspace is on
    the free plan and the log still reads.
    """
    body = console.get(f"/workspaces/{acme.workspace_id}/audit").json()

    # Every workspace's history begins with its creation, written in the
    # transaction that created it.
    assert [item["event"] for item in body["items"]] == ["workspace.created"]

    on_the_tenant_surface = acme.client.get(
        acme.path("audit-logs"),
        headers=acme.owner_headers,
    )
    assert on_the_tenant_surface.status_code == 402


# --- people -----------------------------------------------------------------


def test_an_account_is_found_by_address_or_name(
    console: Console,
    acme: Tenant,
) -> None:
    by_address = console.get("/users", q="owner-acme-fashion@example.com").json()
    by_name = console.get("/users", q="Someone").json()

    assert [item["email"] for item in by_address["items"]] == [
        "owner-acme-fashion@example.com"
    ]
    assert by_name["total"] >= 1


def test_an_account_reads_with_its_workspaces_and_sessions(
    console: Console,
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    owner = user_repository.get_by_email("owner-acme-fashion@example.com")
    assert owner is not None

    body = console.get(f"/users/{owner.id}").json()

    assert body["email"] == "owner-acme-fashion@example.com"
    assert [m["slug"] for m in body["memberships"]] == ["acme-fashion"]
    assert body["memberships"][0]["role"] == "owner"
    # Signing up logged them in, so there is exactly one live session.
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["ip_address"] is not None


def test_an_account_with_nothing_answers_with_empty_lists(
    console: Console,
    client: TestClient,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    # What somebody who registered and never went further looks like. A
    # common state, not an error.
    user = user_repository.create(
        name="Nobody",
        email="nobody@example.com",
        hashed_password="not a real hash",
    )
    db_session.flush()

    body = console.get(f"/users/{user.id}").json()

    assert body["memberships"] == []
    assert body["sessions"] == []


def test_an_unknown_account_is_a_404(console: Console) -> None:
    response = console.get("/users/999999")

    assert response.status_code == 404
    assert response.json()["code"] == "user_not_found"


def test_no_response_about_a_person_carries_a_password(
    console: Console,
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    # The rule the customer-facing schema already follows, and it matters
    # more here: this response is about somebody who is not the person
    # reading it.
    owner = user_repository.get_by_email("owner-acme-fashion@example.com")
    assert owner is not None

    for path in ("/users", f"/users/{owner.id}"):
        body = console.get(path).text

        assert "password" not in body
        assert "hashed" not in body


# --- what the console still may not do --------------------------------------


def test_the_console_itself_returns_no_customer_content(
    console: Console,
    acme: Tenant,
) -> None:
    """Phase A2 stopped at a line, and Phase A3 is the only door through it.

    Two paths on this surface return what a customer's own customers
    wrote, and both need a live, time-boxed grant with a reason the
    customer can read in their own audit log. Everything else is
    aggregates and metadata.

    Asserted as an exact list rather than as "none", because the useful
    property now is that the set does not quietly grow: a third path
    returning customer content should fail here and be a decision
    somebody makes on purpose.
    """
    acme.contact("+923001234567", full_name="Ayesha Khan")

    published = {
        path
        for _, path in operations()
        if any(
            word in path
            for word in ("conversations", "messages", "contacts", "knowledge")
        )
    }

    assert published == {
        f"{ADMIN}/workspaces/{{workspace_id}}/conversations",
        f"{ADMIN}/workspaces/{{workspace_id}}/conversations"
        "/{conversation_id}/messages",
    }

    # And without a grant, neither of them opens.
    for path in sorted(published):
        response = console.get(
            path.removeprefix(ADMIN).format(
                workspace_id=acme.workspace_id,
                conversation_id=uuid.uuid4(),
            )
        )

        assert response.status_code == 403, path
        assert response.json()["code"] == "support_access_required"

    # The route that counts a customer's contacts still does not name one.
    body = console.get(f"/workspaces/{acme.workspace_id}").text

    assert "Ayesha" not in body
