"""Phase 9 acceptance: the knowledge base a business fills in itself.

The pipeline the plan draws -- validate, extract, normalise, chunk, embed,
store -- with each step's failure tested rather than only its success.
What matters most here is the last acceptance criterion: chunks are
workspace-isolated, and deleting a document takes them with it.
"""

import io
import uuid
from typing import Any

import pypdf
import pytest
from fastapi.testclient import TestClient

from app.models.workspace_membership import WorkspaceRole
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.knowledge import FakeEmbeddingProvider

PASSWORD = "correct horse battery staple"

RETURNS = (
    "Returns are accepted within 14 days of delivery. The item must be "
    "unworn and in its original packaging. Refunds are issued to the "
    "original payment method within five working days of the return "
    "arriving at our warehouse."
)
DELIVERY = (
    "We deliver nationwide. Orders placed before 3pm are dispatched the "
    "same day. Delivery within Karachi takes one working day; elsewhere "
    "in Pakistan it takes two to three working days."
)


def _sign_up(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Someone", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


class Business:
    def __init__(
        self,
        client: TestClient,
        memberships: WorkspaceMembershipRepository,
        slug: str,
    ) -> None:
        self._client = client
        self._memberships = memberships

        self.headers = _sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.headers,
        ).json()["id"]

    def member(self, email: str, role: WorkspaceRole) -> dict[str, str]:
        headers = _sign_up(self._client, email)
        user = self._client.get("/api/v1/auth/me", headers=headers).json()
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user["id"],
            role=role,
        )

        return headers

    def path(self, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{self.workspace_id}/knowledge{suffix}"

    def source(self, name: str = "Policies") -> str:
        response = self._client.post(
            self.path("/sources"),
            json={"name": name, "source_type": "text"},
            headers=self.headers,
        )
        assert response.status_code == 201, response.text

        return response.json()["id"]

    def add(
        self,
        content: str,
        *,
        title: str = "Returns policy",
        source_id: str | None = None,
    ) -> dict[str, Any]:
        response = self._client.post(
            self.path("/documents"),
            json={
                "knowledge_source_id": source_id or self.source(),
                "title": title,
                "content": content,
            },
            headers=self.headers,
        )
        assert response.status_code == 201, response.text

        return response.json()

    def search(self, query: str, **extra: Any) -> dict[str, Any]:
        response = self._client.post(
            self.path("/search"),
            json={"query": query, **extra},
            headers=self.headers,
        )
        assert response.status_code == 200, response.text

        return response.json()


@pytest.fixture
def embeddings(embedding_provider: FakeEmbeddingProvider) -> FakeEmbeddingProvider:
    """The fake the client fixture has already installed.

    Named locally because these tests read what it was asked to embed; the
    substitution itself happens in conftest, for every test.
    """
    return embedding_provider


@pytest.fixture
def acme(
    client: TestClient,
    membership_repository: WorkspaceMembershipRepository,
    embeddings: FakeEmbeddingProvider,
) -> Business:
    return Business(client, membership_repository, "acme-fashion")


@pytest.fixture
def rival(
    client: TestClient,
    membership_repository: WorkspaceMembershipRepository,
    embeddings: FakeEmbeddingProvider,
) -> Business:
    return Business(client, membership_repository, "rival-store")


def _pdf(pages: list[str]) -> bytes:
    """A real PDF, built here rather than checked in as a fixture file."""
    writer = pypdf.PdfWriter()

    for body in pages:
        page = writer.add_blank_page(width=595, height=842)
        writer.pages[-1]

        # pypdf cannot lay out text on its own, so the content stream is
        # written directly. Two lines of PostScript is less machinery than
        # a reportlab dependency for one test.
        from pypdf.generic import DecodedStreamObject

        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 800 Td ({body}) Tj ET".encode("latin-1"))
        page[pypdf.generic.NameObject("/Contents")] = stream
        page[pypdf.generic.NameObject("/Resources")] = pypdf.generic.DictionaryObject(
            {
                pypdf.generic.NameObject("/Font"): pypdf.generic.DictionaryObject(
                    {
                        pypdf.generic.NameObject("/F1"): pypdf.generic.DictionaryObject(
                            {
                                pypdf.generic.NameObject(
                                    "/Type"
                                ): pypdf.generic.NameObject("/Font"),
                                pypdf.generic.NameObject(
                                    "/Subtype"
                                ): pypdf.generic.NameObject("/Type1"),
                                pypdf.generic.NameObject(
                                    "/BaseFont"
                                ): pypdf.generic.NameObject("/Helvetica"),
                            }
                        )
                    }
                )
            }
        )

    buffer = io.BytesIO()
    writer.write(buffer)

    return buffer.getvalue()


# --- sources ----------------------------------------------------------------


def test_a_source_can_be_created_and_read_back(
    client: TestClient,
    acme: Business,
) -> None:
    created = client.post(
        acme.path("/sources"),
        json={"name": "Store policies", "source_type": "manual_faq"},
        headers=acme.headers,
    )

    assert created.status_code == 201

    body = created.json()
    assert body["name"] == "Store policies"
    assert body["source_type"] == "manual_faq"
    assert body["status"] == "pending"

    read = client.get(acme.path(f"/sources/{body['id']}"), headers=acme.headers)
    assert read.json() == body


def test_a_source_from_another_business_is_a_404(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    theirs = rival.source()

    response = client.get(acme.path(f"/sources/{theirs}"), headers=acme.headers)

    assert response.status_code == 404
    assert response.json()["code"] == "knowledge_source_not_found"


# --- ingesting --------------------------------------------------------------


def test_text_is_ingested_and_becomes_retrievable(
    client: TestClient,
    acme: Business,
) -> None:
    document = acme.add(RETURNS)

    assert document["status"] == "ready"
    assert document["chunk_count"] >= 1
    assert document["error"] is None


def test_an_faq_embeds_the_question_as_well_as_the_answer(
    client: TestClient,
    acme: Business,
    embeddings: FakeEmbeddingProvider,
) -> None:
    # A customer asks the question in their own words; the passage that
    # should match is the one whose question was similar. That only works
    # if the question is part of what was embedded.
    source_id = acme.source("FAQ")

    response = client.post(
        acme.path("/documents/faq"),
        json={
            "knowledge_source_id": source_id,
            "question": "Do you deliver to Karachi?",
            "answer": "Yes, within one working day.",
        },
        headers=acme.headers,
    )

    assert response.status_code == 201

    embedded = embeddings.calls[-1][0][0]
    assert "Do you deliver to Karachi?" in embedded
    assert "Yes, within one working day." in embedded


def test_the_same_content_twice_is_refused(
    client: TestClient,
    acme: Business,
) -> None:
    # Two copies of a policy do not make the assistant twice as sure of
    # it; they make every answer cite the same thing twice.
    source_id = acme.source()
    acme.add(RETURNS, source_id=source_id)

    response = client.post(
        acme.path("/documents"),
        json={
            "knowledge_source_id": source_id,
            "title": "Returns policy (copy)",
            "content": RETURNS,
        },
        headers=acme.headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "document_already_ingested"


def test_the_same_content_in_two_businesses_is_two_documents(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    # The hash is unique per workspace and deliberately not globally: two
    # shops can have word-for-word the same returns policy.
    acme.add(RETURNS)

    assert rival.add(RETURNS)["status"] == "ready"


def test_whitespace_alone_does_not_make_it_a_different_document(
    client: TestClient,
    acme: Business,
) -> None:
    # The hash is of normalised text, so the same policy exported by two
    # tools is one piece of knowledge.
    source_id = acme.source()
    acme.add(RETURNS, source_id=source_id)

    response = client.post(
        acme.path("/documents"),
        json={
            "knowledge_source_id": source_id,
            "title": "Returns policy",
            "content": RETURNS.replace(" ", "  ") + "\n\n\n",
        },
        headers=acme.headers,
    )

    assert response.status_code == 409


def test_a_document_with_no_text_in_it_is_refused(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.post(
        acme.path("/documents"),
        json={
            "knowledge_source_id": acme.source(),
            "title": "Nothing",
            "content": "   \n\n  ",
        },
        headers=acme.headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unreadable_document"


def test_an_unknown_source_is_a_404(client: TestClient, acme: Business) -> None:
    response = client.post(
        acme.path("/documents"),
        json={
            "knowledge_source_id": str(uuid.uuid4()),
            "title": "Returns policy",
            "content": RETURNS,
        },
        headers=acme.headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "knowledge_source_not_found"


def test_a_documents_source_must_be_in_the_same_workspace(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    theirs = rival.source()

    response = client.post(
        acme.path("/documents"),
        json={
            "knowledge_source_id": theirs,
            "title": "Returns policy",
            "content": RETURNS,
        },
        headers=acme.headers,
    )

    assert response.status_code == 404


def test_a_long_document_becomes_several_chunks(
    client: TestClient,
    acme: Business,
) -> None:
    long_text = "\n\n".join(f"Paragraph {index}. {RETURNS}" for index in range(10))

    document = acme.add(long_text, title="Everything")

    assert document["chunk_count"] > 1


def test_a_provider_failure_leaves_the_document_saying_why(
    client: TestClient,
    acme: Business,
    embeddings: FakeEmbeddingProvider,
) -> None:
    # The upload is not lost. It is a row somebody can retry, with the
    # reason on it, rather than a document that never becomes ready.
    source_id = acme.source()
    embeddings.fail_with = "the provider is down"

    response = client.post(
        acme.path("/documents"),
        json={
            "knowledge_source_id": source_id,
            "title": "Returns policy",
            "content": RETURNS,
        },
        headers=acme.headers,
    )

    assert response.status_code == 502
    assert response.json()["code"] == "embedding_provider_error"

    listed = client.get(acme.path("/documents"), headers=acme.headers).json()
    assert listed["total"] == 1
    assert listed["items"][0]["status"] == "failed"
    assert listed["items"][0]["error"]


# --- uploads ----------------------------------------------------------------


def test_a_pdf_is_read_and_ingested(client: TestClient, acme: Business) -> None:
    response = client.post(
        acme.path("/documents/upload"),
        data={"knowledge_source_id": acme.source()},
        files={
            "file": (
                "policies.pdf",
                _pdf(["Returns within 14 days"]),
                "application/pdf",
            )
        },
        headers=acme.headers,
    )

    assert response.status_code == 201, response.text

    body = response.json()
    assert body["status"] == "ready"
    assert body["title"] == "policies.pdf"
    assert body["chunk_count"] >= 1


def test_a_plain_text_file_is_ingested(client: TestClient, acme: Business) -> None:
    response = client.post(
        acme.path("/documents/upload"),
        data={"knowledge_source_id": acme.source()},
        files={"file": ("policy.txt", RETURNS.encode(), "text/plain")},
        headers=acme.headers,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "ready"


def test_a_pdf_with_no_text_says_so_rather_than_failing_vaguely(
    client: TestClient,
    acme: Business,
) -> None:
    # A scan is pages of images. Saying that is the difference between
    # somebody finding another copy and somebody reporting a bug.
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)

    response = client.post(
        acme.path("/documents/upload"),
        data={"knowledge_source_id": acme.source()},
        files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")},
        headers=acme.headers,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unreadable_document"
    assert "OCR" in response.json()["detail"]


def test_a_file_type_the_mvp_does_not_read_is_refused(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.post(
        acme.path("/documents/upload"),
        data={"knowledge_source_id": acme.source()},
        files={
            "file": (
                "prices.xlsx",
                b"PK\x03\x04 not really a spreadsheet",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=acme.headers,
    )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_document_type"


# --- deleting ---------------------------------------------------------------


def test_deleting_a_document_makes_it_unretrievable(
    client: TestClient,
    acme: Business,
) -> None:
    # The plan's last acceptance criterion, and the one that matters: what
    # a business has withdrawn must stop being able to appear in an answer.
    document = acme.add(RETURNS)
    assert acme.search("returns within 14 days")["matches"]

    deleted = client.delete(
        acme.path(f"/documents/{document['id']}"),
        headers=acme.headers,
    )

    assert deleted.status_code == 204
    assert acme.search("returns within 14 days")["matches"] == []


def test_deleting_a_source_takes_its_documents_with_it(
    client: TestClient,
    acme: Business,
) -> None:
    source_id = acme.source()
    acme.add(RETURNS, source_id=source_id)
    acme.add(DELIVERY, title="Delivery", source_id=source_id)

    client.delete(acme.path(f"/sources/{source_id}"), headers=acme.headers)

    assert (
        client.get(acme.path("/documents"), headers=acme.headers).json()["total"] == 0
    )
    assert acme.search("returns within 14 days")["matches"] == []


# --- who may do what --------------------------------------------------------


def test_an_agent_may_read_and_search_but_not_add(
    client: TestClient,
    acme: Business,
) -> None:
    # What goes in here is what the assistant will tell customers in the
    # business's name, so adding to it is nearer to changing the
    # workspace's settings than to handling a conversation.
    headers = acme.member("agent@example.com", WorkspaceRole.AGENT)
    acme.add(RETURNS)

    assert client.get(acme.path("/sources"), headers=headers).status_code == 200
    assert client.get(acme.path("/documents"), headers=headers).status_code == 200
    assert (
        client.post(
            acme.path("/search"), json={"query": "returns"}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            acme.path("/sources"),
            json={"name": "Sneaky", "source_type": "text"},
            headers=headers,
        ).status_code
        == 403
    )


def test_a_viewer_may_not_search(client: TestClient, acme: Business) -> None:
    headers = acme.member("viewer@example.com", WorkspaceRole.VIEWER)

    response = client.post(
        acme.path("/search"),
        json={"query": "returns"},
        headers=headers,
    )

    assert response.status_code == 403


def test_the_knowledge_base_requires_a_token(
    client: TestClient,
    acme: Business,
) -> None:
    assert client.get(acme.path("/sources")).status_code == 401
    assert client.post(acme.path("/search"), json={"query": "x"}).status_code == 401
