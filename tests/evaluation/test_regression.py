"""Phase 13 acceptance: the harness that says whether the AI is any good.

What is tested here is the harness, not the model. The fake writer answers
however it is told to, so the assertions are about whether the runner
correctly identifies a right answer, a wrong one, a hallucination and a
handoff -- which is what has to be trustworthy before any number it
produces means anything.

The real evaluation, against the real providers, is
`uv run python -m app.evaluation`. It costs money and gives a slightly
different answer every time, which is why it is not in this suite.
"""

import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.orm import Session

from app.evaluation.dataset import Case, load_cases
from app.evaluation.runner import Report, run
from app.models.user import User
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate
from app.services.workspace_service import WorkspaceAccess, WorkspaceService
from tests.support.knowledge import FakeEmbeddingProvider, FakeReplyWriter
from tests.support.messaging import FakeMessagingProvider
from tests.support.services import audit_service

RETURNS = (
    "Returns are accepted within 14 days of delivery. The item must be "
    "unworn and in its original packaging."
)


@pytest.fixture
def access(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> WorkspaceAccess:
    owner = User(
        name="Someone",
        email="owner@example.com",
        hashed_password="not a real hash",
    )
    db_session.add(owner)
    db_session.flush()

    workspaces = WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
        audit=audit_service(db_session),
    )
    workspace = workspaces.create(
        WorkspaceCreate(name="Acme Fashion", slug="acme-fashion"),
        creator=owner,
    )

    return workspaces.access(workspace.id, owner)


def _run(
    cases: Sequence[Case],
    session: Session,
    access: WorkspaceAccess,
    writer: FakeReplyWriter | None = None,
) -> Report:
    return run(
        cases,
        session=session,
        access=access,
        embeddings=FakeEmbeddingProvider(),
        writer=writer or FakeReplyWriter(),
        messaging=FakeMessagingProvider(),
    )


# --- the dataset ------------------------------------------------------------


def test_the_dataset_loads_and_is_not_empty() -> None:
    cases = load_cases()

    assert cases
    assert all(case.question for case in cases)
    assert all(case.id for case in cases)


def test_every_case_that_should_be_answered_names_its_source() -> None:
    # A case that expects an answer without saying where it must come from
    # cannot distinguish a grounded answer from a lucky one, which is the
    # distinction the whole exercise exists to make.
    for case in load_cases():
        if case.should_answer:
            assert case.required_source, case.id
            assert case.knowledge, case.id


def test_every_case_that_should_not_be_answered_says_what_to_do_instead() -> None:
    for case in load_cases():
        if not case.should_answer:
            assert case.should_handoff or case.forbidden_phrases, case.id


def test_two_cases_cannot_share_an_id(tmp_path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        '[{"id": "a", "question": "q", "should_answer": true},'
        ' {"id": "a", "question": "q", "should_answer": true}]'
    )

    with pytest.raises(ValueError, match="share an id"):
        load_cases(path)


def test_a_malformed_case_is_refused_rather_than_skipped(tmp_path) -> None:
    # A typo in a field name would otherwise quietly stop a case being
    # evaluated, and an evaluation measuring less than it claims is worse
    # than one that fails.
    path = tmp_path / "cases.json"
    path.write_text('[{"id": "a", "question": "q", "shuold_answer": true}]')

    with pytest.raises(TypeError):
        load_cases(path)


# --- the runner -------------------------------------------------------------


def test_a_right_answer_scores_as_correct_and_grounded(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    case = Case(
        id="returns",
        question="Can I return an unworn item within 14 days?",
        should_answer=True,
        expected_phrases=["14 days"],
        required_source="unworn",
        knowledge=[RETURNS],
    )
    writer = FakeReplyWriter(reply="Yes, within 14 days if it is unworn.")

    report = _run([case], db_session, access, writer)

    outcome = report.outcomes[0]
    assert outcome.is_correct
    assert outcome.is_grounded
    assert not outcome.is_hallucination
    assert report.correct_rate == 1.0
    assert report.retrieval_success_rate == 1.0


def test_an_answer_missing_what_it_should_say_is_not_correct(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    case = Case(
        id="returns",
        question="Can I return an unworn item within 14 days?",
        should_answer=True,
        expected_phrases=["14 days"],
        required_source="unworn",
        knowledge=[RETURNS],
    )
    writer = FakeReplyWriter(reply="Yes, you can send it back.")

    report = _run([case], db_session, access, writer)

    assert not report.outcomes[0].is_correct
    assert report.outcomes[0].missing_phrases == ["14 days"]
    assert report.incorrect_answer_rate == 1.0


def test_answering_a_question_that_should_be_handed_over_is_a_hallucination(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # The failure the plan cares most about, and it has to be provoked
    # past the pipeline's own guard: a question the passages *do* match,
    # so the model is asked, but that the dataset says a person should
    # take. An angry refund demand is the plan's own example.
    case = Case(
        id="angry-refund",
        question="I demand a refund for my unworn item within 14 days.",
        should_answer=False,
        should_handoff=True,
        knowledge=[RETURNS],
    )
    writer = FakeReplyWriter(reply="Yes, your refund has been issued today.")

    report = _run([case], db_session, access, writer)

    outcome = report.outcomes[0]
    assert outcome.is_hallucination
    assert not outcome.is_correct
    # Kept rather than counted: what improves the next prompt is reading
    # the sentence that was wrong.
    assert report.hallucinations == [outcome]
    assert "refund has been issued" in report.summary()


def test_a_forbidden_phrase_is_a_hallucination_even_in_a_wanted_answer(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # Where an invented price gets recorded so no future prompt can
    # reproduce it unnoticed.
    case = Case(
        id="price",
        question="How much is an unworn item to return within 14 days?",
        should_answer=True,
        expected_phrases=["14 days"],
        forbidden_phrases=["Rs"],
        required_source="unworn",
        knowledge=[RETURNS],
    )
    writer = FakeReplyWriter(reply="Returns are free within 14 days, or Rs 500.")

    report = _run([case], db_session, access, writer)

    assert report.outcomes[0].is_hallucination
    assert report.outcomes[0].forbidden_found == ["Rs"]


def test_a_handoff_where_one_was_wanted_scores_as_correct(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    case = Case(
        id="human",
        question="Can I speak to a human about an unworn item?",
        should_answer=False,
        should_handoff=True,
        knowledge=[RETURNS],
    )
    writer = FakeReplyWriter(can_answer=False)

    report = _run([case], db_session, access, writer)

    assert report.outcomes[0].is_correct
    assert report.outcomes[0].handed_off
    assert report.handoff_precision == 1.0
    assert report.no_answer_rate == 1.0


def test_a_handoff_where_an_answer_was_wanted_lowers_precision(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    case = Case(
        id="returns",
        question="Can I return an unworn item within 14 days?",
        should_answer=True,
        expected_phrases=["14 days"],
        required_source="unworn",
        knowledge=[RETURNS],
    )
    writer = FakeReplyWriter(can_answer=False)

    report = _run([case], db_session, access, writer)

    assert not report.outcomes[0].is_correct
    assert report.handoff_precision == 0.0
    assert report.grounded_answer_rate == 0.0


def test_the_report_names_the_prompt_it_measured(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # Without this, a change in the numbers cannot be attributed to a
    # change in the instructions -- which is the whole point of measuring.
    from app.services.prompts import PROMPT_VERSION

    report = _run(load_cases()[:1], db_session, access)

    assert report.prompt_version == PROMPT_VERSION
    assert PROMPT_VERSION in report.summary()


def test_the_whole_dataset_runs_through_the_real_pipeline(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # Not an assertion about quality -- the writer is a fake that answers
    # the same thing to everything. What this proves is that every case in
    # the dataset can be executed, which is what stops the dataset rotting
    # while nobody is running it against a real model.
    cases = load_cases()

    report = _run(cases, db_session, access)

    assert report.total == len(cases)
    assert {o.case.id for o in report.outcomes} == {c.id for c in cases}
    assert report.summary()


def test_an_evaluation_never_sends_a_message(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # Every case runs in suggest-only, whatever the workspace is set to,
    # so an evaluation cannot put a message on a real customer's phone.
    messaging = FakeMessagingProvider()

    run(
        load_cases()[:3],
        session=db_session,
        access=access,
        embeddings=FakeEmbeddingProvider(),
        writer=FakeReplyWriter(),
        messaging=messaging,
    )

    assert messaging.sent == []


def test_each_case_is_answered_in_its_own_conversation(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # The pipeline reads the thread for context, so a dozen unrelated
    # questions in one thread would measure something nobody experiences.
    writer = FakeReplyWriter()

    _run(load_cases()[:3], db_session, access, writer)

    for _, turns, _ in writer.calls:
        assert len([turn for turn in turns if turn.from_customer]) == 1


def test_an_empty_dataset_reports_nothing_rather_than_dividing_by_zero(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    report = _run([], db_session, access)

    assert report.total == 0
    assert report.correct_rate == 1.0
    assert report.median_latency_ms == 0
    assert report.hallucinations == []


def test_the_run_leaves_the_workspace_it_was_given(
    db_session: Session,
    access: WorkspaceAccess,
) -> None:
    # Its own contacts and conversations, in the workspace handed to it,
    # and nothing reaching outside: the caller decides whether any of it
    # survives.
    from app.repositories.conversation_repository import ConversationRepository

    _run(load_cases()[:2], db_session, access)

    rows = ConversationRepository(db_session).list_for_workspace(
        access.workspace.id,
        limit=50,
        offset=0,
    )
    assert len(rows) == 2
    assert all(row.conversation.workspace_id == access.workspace.id for row in rows)


def test_a_case_from_one_run_cannot_see_another_workspaces_knowledge(
    db_session: Session,
    access: WorkspaceAccess,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    other = User(
        name="Rival",
        email="rival@example.com",
        hashed_password="not a real hash",
    )
    db_session.add(other)
    db_session.flush()
    workspaces = WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
        audit=audit_service(db_session),
    )
    rival = workspaces.create(
        WorkspaceCreate(name="Rival", slug=f"rival-{uuid.uuid4().hex[:6]}"),
        creator=other,
    )
    rival_access = workspaces.access(rival.id, other)

    case = Case(
        id="returns",
        question="Can I return an unworn item within 14 days?",
        should_answer=True,
        expected_phrases=["14 days"],
        required_source="unworn",
        knowledge=[RETURNS],
    )
    _run([case], db_session, access)

    # The same question, in a workspace whose evaluation has its own
    # knowledge. It must not retrieve the first one's.
    empty = Case(
        id="returns",
        question="Can I return an unworn item within 14 days?",
        should_answer=False,
        should_handoff=True,
        knowledge=[],
    )
    report = _run([empty], db_session, rival_access)

    assert report.outcomes[0].retrieved == 0
    assert report.outcomes[0].handed_off
