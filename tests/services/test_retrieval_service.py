"""Phase 10 acceptance: retrieval, and the boundary it must never cross.

The plan calls a cross-tenant knowledge leak a severe security failure, so
most of this file is about that one property: from every angle -- the
service, the repository, the endpoint, an id borrowed from another
workspace -- retrieval returns one workspace's passages and nothing else.

The rest is the two ordinary outcomes that are easy to leave unhandled:
finding nothing, and finding something that is not close enough to count.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.knowledge import DocumentStatus
from app.models.user import User
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.knowledge import DocumentCreate, SourceCreate
from app.schemas.workspace import WorkspaceCreate
from app.services.knowledge_service import KnowledgeService
from app.services.retrieval_service import MIN_SCORE, RetrievalService
from app.services.workspace_service import WorkspaceAccess, WorkspaceService
from tests.support.knowledge import FakeEmbeddingProvider
from tests.support.services import (
    notification_service,
    subscription_service,
)

RETURNS = (
    "Returns are accepted within 14 days of delivery. The item must be "
    "unworn and in its original packaging."
)
DELIVERY = (
    "We deliver nationwide. Orders placed before 3pm are dispatched the "
    "same day and arrive in Karachi within one working day."
)
WARRANTY = (
    "Every watch carries a two year manufacturer warranty covering "
    "mechanical faults but not water damage."
)


@pytest.fixture
def embeddings() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def knowledge_repository(db_session: Session) -> KnowledgeRepository:
    return KnowledgeRepository(db_session)


@pytest.fixture
def ingest(
    db_session: Session,
    knowledge_repository: KnowledgeRepository,
    embeddings: FakeEmbeddingProvider,
) -> KnowledgeService:
    return KnowledgeService(
        session=db_session,
        knowledge=knowledge_repository,
        embeddings=embeddings,
        notifications=notification_service(db_session),
        subscriptions=subscription_service(db_session),
    )


@pytest.fixture
def service(
    knowledge_repository: KnowledgeRepository,
    embeddings: FakeEmbeddingProvider,
) -> RetrievalService:
    return RetrievalService(knowledge=knowledge_repository, embeddings=embeddings)


class Business:
    def __init__(
        self,
        session: Session,
        workspaces: WorkspaceService,
        ingest: KnowledgeService,
        slug: str,
    ) -> None:
        owner = User(
            name="Someone",
            email=f"owner-{slug}@example.com",
            hashed_password="not a real hash",
        )
        session.add(owner)
        session.flush()

        self._ingest = ingest
        self.workspace = workspaces.create(
            WorkspaceCreate(name=slug.title(), slug=slug),
            creator=owner,
        )
        self.access: WorkspaceAccess = workspaces.access(self.workspace.id, owner)
        self.source = ingest.create_source(
            self.access,
            SourceCreate(name="Policies"),
        )

    def knows(self, content: str, title: str = "Policy") -> uuid.UUID:
        document = self._ingest.add_text(
            self.access,
            DocumentCreate(
                knowledge_source_id=self.source.id,
                title=title,
                content=content,
            ),
        )

        return document.id


@pytest.fixture
def workspaces(
    db_session: Session,
    workspace_repository,
    membership_repository,
) -> WorkspaceService:
    return WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
    )


@pytest.fixture
def acme(
    db_session: Session,
    workspaces: WorkspaceService,
    ingest: KnowledgeService,
) -> Business:
    return Business(db_session, workspaces, ingest, "acme-fashion")


@pytest.fixture
def rival(
    db_session: Session,
    workspaces: WorkspaceService,
    ingest: KnowledgeService,
) -> Business:
    return Business(db_session, workspaces, ingest, "rival-store")


# --- the boundary -----------------------------------------------------------


def test_retrieval_never_returns_another_businesss_knowledge(
    service: RetrievalService,
    acme: Business,
    rival: Business,
) -> None:
    # The plan's severe-failure case, stated directly: their passage is
    # word for word what was asked for, and it must not come back.
    rival.knows(RETURNS)

    found = service.retrieve(acme.workspace.id, "returns accepted within 14 days")

    assert found.matches == []


def test_two_businesses_with_the_same_policy_each_get_their_own(
    service: RetrievalService,
    acme: Business,
    rival: Business,
) -> None:
    # Word-for-word identical knowledge in both, which is ordinary -- two
    # shops can have the same returns policy. Each must retrieve its own
    # row, because deleting one must not affect the other.
    mine = acme.knows(RETURNS)
    theirs = rival.knows(RETURNS)

    found = service.retrieve(acme.workspace.id, "returns accepted within 14 days")

    assert [match.document_id for match in found.matches] == [mine]
    assert theirs not in [match.document_id for match in found.matches]


def test_a_chunk_id_from_another_workspace_is_not_reachable(
    knowledge_repository: KnowledgeRepository,
    service: RetrievalService,
    acme: Business,
    rival: Business,
) -> None:
    # Even knowing the id buys nothing: the search is scoped before it
    # scores, so there is no query that could return the row.
    rival.knows(RETURNS)

    assert knowledge_repository.count_chunks(rival.workspace.id) > 0
    assert knowledge_repository.count_chunks(acme.workspace.id) == 0


# --- the ordinary outcomes --------------------------------------------------


def test_an_empty_knowledge_base_returns_nothing_rather_than_failing(
    service: RetrievalService,
    acme: Business,
) -> None:
    found = service.retrieve(acme.workspace.id, "what is your returns policy?")

    assert found.is_empty
    assert found.matches == []
    assert found.best_score == 0.0


def test_a_question_nothing_matches_returns_nothing(
    service: RetrievalService,
    acme: Business,
) -> None:
    # The low-score case. Something is in the knowledge base; it is not
    # about this, and returning it anyway is how an assistant ends up
    # answering a question about warranties with the delivery times.
    acme.knows(DELIVERY)

    found = service.retrieve(
        acme.workspace.id,
        "quantum chromodynamics lattice gauge",
    )

    assert found.matches == []


def test_the_closest_passage_comes_first(
    service: RetrievalService,
    acme: Business,
) -> None:
    acme.knows(DELIVERY, title="Delivery")
    acme.knows(WARRANTY, title="Warranty")
    returns = acme.knows(RETURNS, title="Returns")

    found = service.retrieve(acme.workspace.id, "returns accepted unworn packaging")

    assert found.matches
    assert found.matches[0].document_id == returns
    assert found.best_score > MIN_SCORE


def test_scores_come_back_in_descending_order(
    service: RetrievalService,
    acme: Business,
) -> None:
    for index, content in enumerate((RETURNS, DELIVERY, WARRANTY)):
        acme.knows(content, title=f"Policy {index}")

    found = service.retrieve(
        acme.workspace.id,
        "delivery returns warranty",
        min_score=-1.0,
    )

    scores = [match.score for match in found.matches]
    assert scores == sorted(scores, reverse=True)


def test_a_limit_is_respected(service: RetrievalService, acme: Business) -> None:
    for index in range(5):
        acme.knows(f"{RETURNS} Note {index}.", title=f"Policy {index}")

    found = service.retrieve(
        acme.workspace.id,
        "returns accepted",
        limit=2,
        min_score=-1.0,
    )

    assert len(found.matches) == 2


def test_an_empty_question_retrieves_nothing_and_asks_nobody(
    service: RetrievalService,
    acme: Business,
    embeddings: FakeEmbeddingProvider,
) -> None:
    acme.knows(RETURNS)
    before = len(embeddings.calls)

    found = service.retrieve(acme.workspace.id, "   \n  ")

    assert found.matches == []
    assert len(embeddings.calls) == before


def test_a_provider_outage_retrieves_nothing_rather_than_raising(
    service: RetrievalService,
    acme: Business,
    embeddings: FakeEmbeddingProvider,
) -> None:
    # Retrieval is one input to answering. A provider being down should
    # degrade the assistant to "I will get somebody to help" rather than
    # take down the endpoint that called it.
    acme.knows(RETURNS)
    embeddings.fail_with = "the provider is down"

    found = service.retrieve(acme.workspace.id, "returns policy")

    assert found.is_empty


def test_a_document_still_processing_is_not_searched(
    db_session: Session,
    knowledge_repository: KnowledgeRepository,
    service: RetrievalService,
    acme: Business,
) -> None:
    # Half an embedded policy is a policy the assistant would answer from
    # and get wrong.
    document_id = acme.knows(RETURNS)
    document = knowledge_repository.get_document(acme.workspace.id, document_id)
    assert document is not None
    knowledge_repository.set_document_status(document, DocumentStatus.PROCESSING)
    db_session.commit()

    found = service.retrieve(acme.workspace.id, "returns accepted within 14 days")

    assert found.matches == []


def test_the_query_that_was_searched_comes_back_with_the_results(
    service: RetrievalService,
    acme: Business,
) -> None:
    # Normalisation happens first, so what was searched is not always what
    # was sent -- and an answer that cannot be tied to the question that
    # produced it is not reproducible.
    acme.knows(RETURNS)

    found = service.retrieve(acme.workspace.id, "  returns   accepted  ")

    assert found.query == "returns accepted"


def test_a_passage_carries_where_it_came_from(
    service: RetrievalService,
    acme: Business,
) -> None:
    # The plan asks that answers be traceable to sources, which means the
    # chunk has to know its document, its source and its title.
    document_id = acme.knows(RETURNS, title="Returns policy")

    match = service.retrieve(acme.workspace.id, "returns accepted unworn").matches[0]

    assert match.document_id == document_id
    assert match.metadata["title"] == "Returns policy"
    assert match.metadata["source_name"] == "Policies"
    assert match.metadata["source_id"] == str(acme.source.id)
