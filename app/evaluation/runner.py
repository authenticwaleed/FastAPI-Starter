"""Putting the dataset through the real pipeline, and counting what happens.

Through the real pipeline deliberately. A runner that called the model
directly would measure the prompt and nothing else; what a business
actually experiences is retrieval, the confidence floor, the modes and the
handoff rules all together, and any of those can be the thing that is
wrong.

Every run is stamped with the prompt version it exercised, which is what
makes "did that change help" a question with an answer.
"""

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.dataset import Case
from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.llm.base import ReplyWriter
from app.integrations.messaging.base import MessagingProvider
from app.models.ai_response_log import AiDecision
from app.models.contact import ContactStatus
from app.models.conversation import AiMode, Channel
from app.models.knowledge import KnowledgeChunk
from app.models.message import Direction, MessageStatus, SenderType
from app.models.workspace import Workspace
from app.repositories.ai_response_log_repository import AiResponseLogRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.schemas.knowledge import DocumentCreate, SourceCreate
from app.services.ai_dispatch import (
    build_ai_response_service,
    build_audit_service,
    build_subscription_service,
)
from app.services.ai_response_service import AiResponseService
from app.services.knowledge_service import KnowledgeService
from app.services.notification_service import NotificationService
from app.services.prompts import PROMPT_VERSION
from app.services.workspace_service import WorkspaceAccess

logger = logging.getLogger(__name__)

# Decisions in which the assistant said something to the customer, or
# would have. Everything else is a decline of one kind or another.
_SPOKE = frozenset({AiDecision.ANSWERED, AiDecision.SUGGESTED})


@dataclass(frozen=True)
class Outcome:
    """What the pipeline did with one case, and whether that was right."""

    case: Case
    decision: AiDecision
    text: str | None
    confidence: float | None
    reason: str | None
    retrieved: int
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    source_matched: bool = False

    @property
    def answered(self) -> bool:
        return self.decision in _SPOKE and bool(self.text)

    @property
    def handed_off(self) -> bool:
        return self.decision == AiDecision.HANDOFF

    @property
    def missing_phrases(self) -> list[str]:
        haystack = (self.text or "").lower()

        return [
            phrase
            for phrase in self.case.expected_phrases
            if phrase.lower() not in haystack
        ]

    @property
    def forbidden_found(self) -> list[str]:
        haystack = (self.text or "").lower()

        return [
            phrase
            for phrase in self.case.forbidden_phrases
            if phrase.lower() in haystack
        ]

    @property
    def is_grounded(self) -> bool:
        """Answered, from the passage the case said it had to come from.

        An answer that is right by luck is not grounded, and the
        distinction is the whole point of retrieval: the same sentence
        produced without the evidence behind it will be wrong the next
        time the policy changes.
        """
        if not self.answered:
            return False

        return self.source_matched if self.case.required_source else True

    @property
    def is_hallucination(self) -> bool:
        """Said something the case says is not true.

        Either a forbidden phrase -- an invented price, a delivery date --
        or an answer to a question the dataset says has no answer.
        """
        if self.forbidden_found:
            return True

        return self.answered and not self.case.should_answer

    @property
    def is_correct(self) -> bool:
        """Did what the case asked for.

        Both halves have to hold: the right kind of outcome, and, when it
        answered, an answer that contains what a right answer contains.
        """
        if self.is_hallucination:
            return False

        if self.case.should_answer:
            return self.answered and not self.missing_phrases

        if self.case.should_handoff:
            return self.handed_off

        return not self.answered


@dataclass(frozen=True)
class Report:
    """The metrics the plan names, over one run of the dataset."""

    prompt_version: str
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def grounded_answer_rate(self) -> float:
        """Of the cases that should be answered, how many were, from source."""
        wanted = [o for o in self.outcomes if o.case.should_answer]

        return _rate(sum(1 for o in wanted if o.is_grounded), len(wanted))

    @property
    def handoff_precision(self) -> float:
        """Of the handoffs, how many were cases that wanted one.

        Precision rather than recall on purpose. A handoff that should not
        have happened costs an agent's time; the opposite failure -- an
        answer that should have been a handoff -- is counted below as an
        incorrect answer, where it belongs.
        """
        handoffs = [o for o in self.outcomes if o.handed_off]

        return _rate(sum(1 for o in handoffs if o.case.should_handoff), len(handoffs))

    @property
    def incorrect_answer_rate(self) -> float:
        """Of the cases that were answered, how many got it wrong."""
        answered = [o for o in self.outcomes if o.answered]

        return _rate(sum(1 for o in answered if not o.is_correct), len(answered))

    @property
    def no_answer_rate(self) -> float:
        """How much of the dataset produced nothing to send."""
        return _rate(sum(1 for o in self.outcomes if not o.answered), self.total)

    @property
    def retrieval_success_rate(self) -> float:
        """How often the required passage was among what came back.

        Measured only over cases that name one: a case with no required
        source has nothing to succeed or fail at, and counting it either
        way would move this number for no reason.
        """
        wanted = [o for o in self.outcomes if o.case.required_source]

        return _rate(sum(1 for o in wanted if o.source_matched), len(wanted))

    @property
    def hallucinations(self) -> list[Outcome]:
        """Every case that said something untrue, kept rather than counted.

        The plan asks for hallucination examples to be tracked, and a
        percentage is not an example: what makes the next prompt better is
        reading the sentence that was wrong.
        """
        return [o for o in self.outcomes if o.is_hallucination]

    @property
    def correct_rate(self) -> float:
        return _rate(sum(1 for o in self.outcomes if o.is_correct), self.total)

    @property
    def median_latency_ms(self) -> int:
        return _median([o.latency_ms for o in self.outcomes])

    @property
    def total_tokens(self) -> tuple[int, int]:
        return (
            sum(o.input_tokens or 0 for o in self.outcomes),
            sum(o.output_tokens or 0 for o in self.outcomes),
        )

    def summary(self) -> str:
        """The report as something to paste into a pull request."""
        written, read = self.total_tokens
        lines = [
            f"prompt {self.prompt_version} over {self.total} cases",
            f"  correct                {self.correct_rate:.0%}",
            f"  grounded answers       {self.grounded_answer_rate:.0%}",
            f"  handoff precision      {self.handoff_precision:.0%}",
            f"  incorrect answers      {self.incorrect_answer_rate:.0%}",
            f"  no answer              {self.no_answer_rate:.0%}",
            f"  retrieval success      {self.retrieval_success_rate:.0%}",
            f"  median latency         {self.median_latency_ms}ms",
            f"  tokens in/out          {written}/{read}",
            f"  hallucinations         {len(self.hallucinations)}",
        ]

        for outcome in self.hallucinations:
            lines.append(f"    ! {outcome.case.id}: {outcome.text!r}")

        for outcome in self.outcomes:
            if not outcome.is_correct and not outcome.is_hallucination:
                lines.append(
                    f"    x {outcome.case.id}: {outcome.decision.value}"
                    f" ({outcome.reason or 'no reason'})"
                )

        return "\n".join(lines)


def run(
    cases: Sequence[Case],
    *,
    session: Session,
    access: WorkspaceAccess,
    embeddings: EmbeddingProvider,
    writer: ReplyWriter,
    messaging: MessagingProvider,
) -> Report:
    """Run every case in its own conversation, in one workspace.

    Its own conversation because the pipeline reads the thread for
    context, and a dozen unrelated questions in one thread would measure
    something nobody experiences. The knowledge each case declares is
    ingested once, shared by all of them, so a case whose answer is in
    another case's document still has to retrieve it -- which is the
    situation a real knowledge base is always in.
    """
    knowledge = KnowledgeService(
        session=session,
        knowledge=KnowledgeRepository(session),
        embeddings=embeddings,
        notifications=NotificationService(
            session=session,
            notifications=NotificationRepository(session),
            memberships=WorkspaceMembershipRepository(session),
        ),
        subscriptions=build_subscription_service(session),
        audit=build_audit_service(session),
    )
    source = knowledge.create_source(access, SourceCreate(name="Evaluation"))

    for index, content in enumerate(_all_knowledge(cases)):
        knowledge.add_text(
            access,
            DocumentCreate(
                knowledge_source_id=source.id,
                title=f"Evaluation document {index + 1}",
                content=content,
            ),
        )

    service = build_ai_response_service(
        session,
        embeddings=embeddings,
        writer=writer,
        messaging=messaging,
    )
    logs = AiResponseLogRepository(session)

    return Report(
        prompt_version=PROMPT_VERSION,
        outcomes=[
            _run_case(
                case,
                session=session,
                workspace=access.workspace,
                service=service,
                logs=logs,
                index=index,
            )
            for index, case in enumerate(cases)
        ],
    )


def _run_case(
    case: Case,
    *,
    session: Session,
    workspace: Workspace,
    service: AiResponseService,
    logs: AiResponseLogRepository,
    index: int,
) -> Outcome:
    contacts = ContactRepository(session)
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)

    contact = contacts.create(
        workspace_id=workspace.id,
        # A distinct number per case, because a contact has at most one
        # live thread and every case needs its own.
        phone_number=f"+92300{index:07d}",
        name=f"Case {case.id}",
        email=None,
        status=ContactStatus.LEAD,
        source="evaluation",
        external_id=None,
        meta={},
    )
    conversation = conversations.create(
        workspace_id=workspace.id,
        contact_id=contact.id,
        channel=Channel.WHATSAPP,
    )
    # Drafting rather than sending: an evaluation must not be able to put
    # a message on a real number, whatever is configured.
    conversations.set_ai_mode(conversation, AiMode.SUGGEST_ONLY)
    question = messages.create(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        sender_type=SenderType.CUSTOMER,
        direction=Direction.INBOUND,
        channel=Channel.WHATSAPP,
        status=MessageStatus.RECEIVED,
        text=case.question,
    )
    session.commit()

    started = time.monotonic()
    reply = service.generate_reply(
        workspace,
        conversation.id,
        incoming_message_id=question.id,
    )
    latency = int((time.monotonic() - started) * 1000)

    log = logs.get_for_message(workspace.id, question.id)

    return Outcome(
        case=case,
        decision=reply.decision,
        text=reply.text,
        confidence=reply.confidence,
        reason=reply.reason,
        retrieved=len(reply.sources),
        latency_ms=latency,
        input_tokens=log.input_tokens if log else None,
        output_tokens=log.output_tokens if log else None,
        source_matched=_source_matched(case, session, workspace.id, reply.sources),
    )


def _source_matched(
    case: Case,
    session: Session,
    workspace_id: uuid.UUID,
    chunk_ids: Sequence[uuid.UUID],
) -> bool:
    """Whether the passage the case requires was among what was retrieved."""
    if not case.required_source or not chunk_ids:
        return False

    contents = session.scalars(
        select(KnowledgeChunk.content).where(
            KnowledgeChunk.workspace_id == workspace_id,
            KnowledgeChunk.id.in_(list(chunk_ids)),
        )
    ).all()

    needle = case.required_source.lower()

    return any(needle in content.lower() for content in contents)


def _all_knowledge(cases: Sequence[Case]) -> list[str]:
    """Every case's supporting text, once each and in a stable order."""
    seen: dict[str, None] = {}

    for case in cases:
        for content in case.knowledge:
            seen.setdefault(content, None)

    return list(seen)


def _rate(part: int, whole: int) -> float:
    """A proportion, with nothing to divide by reported as a perfect score.

    Zero cases of a kind means nothing went wrong of that kind. Reporting
    it as 0% would make an empty category look like the worst possible
    result, which is the reading that sends somebody chasing a problem
    that is not there.
    """
    return 1.0 if whole == 0 else part / whole


def _median(values: Sequence[int]) -> int:
    if not values:
        return 0

    ordered = sorted(values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]

    return (ordered[middle - 1] + ordered[middle]) // 2
