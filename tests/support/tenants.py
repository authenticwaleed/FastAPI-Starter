"""One business, signed up and ready to be called as.

Lifted out of the contacts tests, where it started, once the catalogue
and orders needed the same three lines of setup. Every tenant-scoped
suite wants the same thing: an owner with a token, a workspace, and a way
to add a colleague at a chosen role so that the wall between two
businesses can actually be pushed on.
"""

import uuid

from fastapi.testclient import TestClient

from app.models.workspace_membership import WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)

PASSWORD = "correct horse battery staple"


def sign_up(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Someone", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


class Tenant:
    """A workspace, its owner, and whatever else a test needs inside it."""

    def __init__(
        self,
        client: TestClient,
        users: UserRepository,
        memberships: WorkspaceMembershipRepository,
        slug: str,
    ) -> None:
        self.client = client
        self._users = users
        self._memberships = memberships

        self.owner_headers = sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.owner_headers,
        ).json()["id"]

    def member(self, email: str, role: WorkspaceRole) -> dict[str, str]:
        headers = sign_up(self.client, email)
        user = self._users.get_by_email(email)
        assert user is not None
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user.id,
            role=role,
        )

        return headers

    def path(self, *parts: str) -> str:
        return "/".join(
            [f"/api/v1/workspaces/{self.workspace_id}", *(p for p in parts if p)]
        )

    def contact(self, phone_number: str = "+923001234567", **fields: object) -> str:
        response = self.client.post(
            self.path("contacts"),
            json={"phone_number": phone_number} | fields,
            headers=self.owner_headers,
        )
        assert response.status_code == 201, response.text

        return str(response.json()["id"])
