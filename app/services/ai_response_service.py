import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConversationNotFoundError,
    MessagingProviderError,
    ReplyProviderError,
)
from app.db.session import SessionDep
from app.integrations.llm.base import (
    Completion,
    Passage,
    ReplyWriter,
    Turn,
)
from app.integrations.llm.claude import ClaudeReplyWriter
from app.models.ai_response_log import AiDecision, AiResponseLog
from app.models.conversation import AiMode, Conversation
from app.models.conversation_event import EventType
from app.models.message import Direction, Message, SenderType
from app.models.workspace import Workspace
from app.repositories.ai_response_log_repository import AiResponseLogRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageCreate
from app.services.commerce_context import (
    CommerceContextService,
    CommerceContextServiceDep,
)
from app.services.conversation_service import (
    ConversationEventRepositoryDep,
    ConversationRepositoryDep,
)
from app.services.message_service import (
    MessageRepositoryDep,
    MessageService,
    MessageServiceDep,
)
from app.services.prompts import PROMPT_VERSION, system_prompt
from app.services.retrieval_service import (
    Retrieval,
    RetrievalService,
    RetrievalServiceDep,
)

logger = logging.getLogger(__name__)

# Below this the assistant does not put words in the business's mouth,
# whatever mode it is in. Separate from the retrieval floor and doing a
# different job: retrieval's floor decides what counts as evidence, this
# decides whether the model's own reading of that evidence was firm enough
# to act on.
MIN_CONFIDENCE = 0.6

# How much of the thread the model is shown. Enough that "yes, that one"
# means something; not so much that an hour-old conversation costs a
# fortune to answer and buries the actual question.
CONTEXT_TURNS = 10


@dataclass(frozen=True)
class AiReply:
    """What the pipeline decided, and why.

    Returned whatever happened, including when nothing was sent. A caller
    that has to tell a `handoff` from a `failed` from an `ai_disabled`
    cannot do it from an exception, and those three want three different
    things to happen next.
    """

    decision: AiDecision
    text: str | None = None
    confidence: float | None = None
    reason: str | None = None
    sources: list[uuid.UUID] = field(default_factory=list)
    # The reply that went out, when one did. Set only in automatic mode,
    # and set on a repeat call too -- so a caller that asks twice is told
    # about the message that exists rather than being invited to make a
    # second one.
    message_id: uuid.UUID | None = None


class AiResponseService:
    """The deterministic pipeline that answers a customer's message.

    The plan is explicit about not starting with autonomous agents, and
    this is what that looks like: eligibility, retrieval, prompt,
    model, validation, decision -- in that order, in ordinary control
    flow, with every branch visible. Nothing here decides what to do
    next; it decides what to say and whether it is allowed to say it.

    Every path writes a row to ai_response_logs, including the paths where
    the answer is "no". The question this service has to be able to answer
    later is "why did it do that", and the cases worth asking about are
    mostly the ones where it did nothing.
    """

    def __init__(
        self,
        session: Session,
        conversations: ConversationRepository,
        messages: MessageRepository,
        logs: AiResponseLogRepository,
        retrieval: RetrievalService,
        commerce: CommerceContextService,
        writer: ReplyWriter,
        outbound: MessageService,
        events: ConversationEventRepository,
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._messages = messages
        self._logs = logs
        self._retrieval = retrieval
        self._commerce = commerce
        self._writer = writer
        self._outbound = outbound
        self._events = events

    def generate_reply(
        self,
        workspace: Workspace,
        conversation_id: uuid.UUID,
        *,
        incoming_message_id: uuid.UUID | None = None,
        requested_by_human: bool = False,
    ) -> AiReply:
        """Draft a reply to the last thing the customer said.

        Never raises for a model that failed, a knowledge base that is
        empty or a conversation the assistant is switched off for. Each of
        those is a decision with a record behind it, because the one thing
        this must not do is lose a customer's message while deciding what
        to do about it.

        `requested_by_human` is what separates a webhook from a button.
        Arriving on its own, this answers a given message once and then
        replays that decision for ever -- a provider resends an envelope
        whenever it does not get a prompt 200, including when it did, and
        a customer should not hear back twice. Asked for by a person, it
        runs again, because the reason to press the button is that
        something has changed: the assistant was switched off, or the
        model was down, or the knowledge base has since been filled in.
        The one decision never repeated either way is a reply that was
        actually sent.
        """
        workspace_id = workspace.id
        conversation = self._conversations.get(workspace_id, conversation_id)

        if conversation is None:
            # The one thing that is an error: it means the caller asked
            # about a conversation this workspace does not have, and
            # answering "handoff" would hide a bug or a tenant leak.
            raise ConversationNotFoundError(workspace_id, conversation_id)

        history = self._messages.list_for_conversation(
            workspace_id,
            conversation.id,
            limit=CONTEXT_TURNS,
            offset=0,
        )
        question = _last_customer_message(history, incoming_message_id)

        if question is None:
            return self._record(
                workspace,
                conversation,
                None,
                AiDecision.BLOCKED,
                reason="no_question",
            )

        if conversation.is_with_a_human and not requested_by_human:
            # The plan's business rule. A thread somebody has taken over,
            # or that the assistant has already given up on, is not one to
            # answer into on its own -- an assistant replying alongside an
            # agent is two voices contradicting each other in front of a
            # customer. A person asking explicitly still gets a draft.
            return self._record(
                workspace,
                conversation,
                question,
                AiDecision.BLOCKED,
                reason="handed_off",
            )

        if conversation.ai_mode == AiMode.DISABLED:
            return self._record(
                workspace,
                conversation,
                question,
                AiDecision.BLOCKED,
                reason="ai_disabled",
            )

        already = self._logs.get_for_message(workspace_id, question.id)

        if already is not None and not _may_run_again(already, requested_by_human):
            logger.info("The assistant has already answered message %s", question.id)

            return _replay(already)

        return self._answer(workspace, conversation, question)

    def _answer(
        self,
        workspace: Workspace,
        conversation: Conversation,
        question: Message,
    ) -> AiReply:
        started = time.monotonic()
        asked = question.text_body or ""

        retrieval = self._retrieval.retrieve(workspace.id, asked)

        # Two kinds of evidence, gathered two different ways. The
        # knowledge base is searched by similarity; the catalogue and this
        # customer's orders are looked up. The plan insists on the second
        # for exactly the facts customers act on -- a price, a stock
        # level, where an order has got to -- because similarity search
        # returns the passage that reads most like the question, and for
        # two customers with similar orders that is a coin toss.
        commerce = self._commerce.gather(
            workspace.id,
            conversation.contact_id,
            asked,
        )

        if retrieval.is_empty and commerce.is_empty:
            # Nothing to ground an answer in. Handed over rather than
            # answered from the model's general knowledge, which is the
            # plan's rule and the whole reason evidence comes first.
            return self._record(
                workspace,
                conversation,
                question,
                AiDecision.HANDOFF,
                reason="no_knowledge",
                retrieval=retrieval,
                latency_ms=_since(started),
            )

        try:
            completion = self._writer.write(
                instructions=system_prompt(workspace.name),
                turns=_turns(
                    self._messages.list_for_conversation(
                        workspace.id,
                        conversation.id,
                        limit=CONTEXT_TURNS,
                        offset=0,
                    )
                ),
                passages=[*commerce.passages, *_passages(retrieval)],
            )
        except ReplyProviderError as exc:
            # The message is untouched and still in the thread. A model
            # being unavailable turns the assistant off for one message;
            # it does not lose a customer's question.
            logger.warning("The assistant could not draft a reply: %s", exc)

            return self._record(
                workspace,
                conversation,
                question,
                AiDecision.FAILED,
                reason="provider_error",
                retrieval=retrieval,
                latency_ms=_since(started),
            )

        return self._decide(
            workspace,
            conversation,
            question,
            retrieval,
            completion,
            latency_ms=_since(started),
        )

    def _decide(
        self,
        workspace: Workspace,
        conversation: Conversation,
        question: Message,
        retrieval: Retrieval,
        completion: Completion,
        *,
        latency_ms: int,
    ) -> AiReply:
        """Turn a draft into one of the plan's five decisions.

        The order of these checks is the safety argument. Whether the
        model could answer at all comes before how confident it was, and
        both come before what mode the conversation is in -- so a
        workspace that has switched the assistant to automatic cannot
        thereby send something the same draft would have been withheld for
        in suggest-only.
        """
        draft = completion.draft

        if not draft.can_answer or not draft.text:
            return self._record(
                workspace,
                conversation,
                question,
                AiDecision.HANDOFF,
                reason="cannot_answer",
                retrieval=retrieval,
                completion=completion,
                latency_ms=latency_ms,
            )

        if draft.confidence < MIN_CONFIDENCE:
            return self._record(
                workspace,
                conversation,
                question,
                AiDecision.HANDOFF,
                reason="low_confidence",
                retrieval=retrieval,
                completion=completion,
                latency_ms=latency_ms,
            )

        decision = (
            AiDecision.ANSWERED
            if conversation.ai_mode == AiMode.AUTOMATIC
            else AiDecision.SUGGESTED
        )

        return self._record(
            workspace,
            conversation,
            question,
            decision,
            retrieval=retrieval,
            completion=completion,
            latency_ms=latency_ms,
        )

    def _record(
        self,
        workspace: Workspace,
        conversation: Conversation,
        question: Message | None,
        decision: AiDecision,
        *,
        reason: str | None = None,
        retrieval: Retrieval | None = None,
        completion: Completion | None = None,
        latency_ms: int | None = None,
    ) -> AiReply:
        """Write the row, send if that is what was decided, then answer.

        One place that writes to the log, so there is no decision the
        pipeline can reach without leaving a record of it -- and the send
        lives here, beside the decision, rather than in the route. Split
        across two layers it was possible to reach the second without the
        first: a repeat call replayed the decision and sent the reply
        again, which is a second message to a customer who asked once.
        """
        chunk_ids = [match.chunk_id for match in retrieval.matches] if retrieval else []
        draft = completion.draft if completion else None
        text = draft.text if draft and draft.text else None

        # The log keeps what the model wrote whatever was decided -- what
        # a withheld answer would have said is the most useful thing in
        # this table for anyone tuning the assistant. The caller is told
        # only about a draft it may act on, so a reply held back for low
        # confidence cannot be sent by a client that read `text` and
        # skipped `decision`.
        usable = decision in {AiDecision.SUGGESTED, AiDecision.ANSWERED}

        log = self._logs.create(
            workspace_id=conversation.workspace_id,
            conversation_id=conversation.id,
            message_id=question.id if question else None,
            decision=decision,
            prompt_version=PROMPT_VERSION,
            reply_text=text,
            reason=reason,
            model=completion.model if completion else None,
            retrieval_query=retrieval.query if retrieval else None,
            retrieved_chunk_ids=chunk_ids,
            confidence=draft.confidence if draft else None,
            latency_ms=latency_ms,
            input_tokens=completion.input_tokens if completion else None,
            output_tokens=completion.output_tokens if completion else None,
        )
        self._session.commit()

        if decision == AiDecision.HANDOFF and not conversation.is_with_a_human:
            # Marked on the conversation as well as in the log, because
            # the log answers "what happened" and the inbox has to answer
            # "who is dealing with this". No assignee: nobody has claimed
            # it, which is what makes it appear in the unassigned queue
            # rather than quietly on somebody's list.
            self._conversations.hand_over(
                conversation,
                at=datetime.now(UTC),
                reason=reason,
            )
            self._events.record(
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                event_type=EventType.AI_HANDOFF,
                reason=reason,
            )
            self._session.commit()

        if decision == AiDecision.ANSWERED and log.reply_text:
            try:
                sent = self._outbound.send(
                    workspace,
                    conversation.id,
                    MessageCreate(text=log.reply_text),
                    # Marked `ai` so the thread shows who wrote it.
                    # Everything else about the send is identical to an
                    # agent's reply, because two delivery paths would be
                    # two sets of bugs.
                    sender_type=SenderType.AI,
                )
            except MessagingProviderError:
                # The reply is written into the thread before the provider
                # is called and stays there marked failed, so an agent
                # sees what the assistant said and that it did not go.
                # Reported as the decision it was rather than as an error:
                # the assistant answered, and WhatsApp is down.
                logger.warning("An assistant reply could not be delivered")
            else:
                self._logs.record_sent(log, sent.id)
                self._session.commit()

            return _replay(log)

        return AiReply(
            decision=decision,
            text=log.reply_text if usable else None,
            confidence=log.confidence,
            reason=log.reason,
            sources=list(log.retrieved_chunk_ids),
        )


def _last_customer_message(
    history: Sequence[Message],
    incoming_message_id: uuid.UUID | None,
) -> Message | None:
    """The message being answered.

    Named explicitly when the caller knows it -- the webhook does -- and
    otherwise the most recent inbound one. The thread comes back newest
    first, so the first inbound message in it is the latest.
    """
    if incoming_message_id is not None:
        return next(
            (message for message in history if message.id == incoming_message_id),
            None,
        )

    return next(
        (
            message
            for message in history
            if message.direction == Direction.INBOUND
            and message.sender_type == SenderType.CUSTOMER
        ),
        None,
    )


def _turns(history: Sequence[Message]) -> list[Turn]:
    """The thread as the model should read it: oldest first.

    Reversed here because the repository returns newest first, which is
    what a chat screen opens with and the opposite of what a conversation
    reads like.
    """
    return [
        Turn(
            from_customer=message.direction == Direction.INBOUND,
            text=message.text_body or "",
        )
        for message in reversed(list(history))
        if message.text_body
    ]


def _passages(retrieval: Retrieval) -> list[Passage]:
    return [
        Passage(
            id=str(match.chunk_id),
            content=match.content,
            title=match.metadata.get("title"),
        )
        for match in retrieval.matches
    ]


def _may_run_again(log: AiResponseLog, requested_by_human: bool) -> bool:
    """Whether a message already looked at may be looked at again.

    Never once a reply has gone out: that one reached the customer, and
    the cost of repeating it is their phone buzzing twice with two
    different answers. Otherwise only on request, because the automatic
    path's every repeat is a provider resending an envelope.
    """
    if log.decision == AiDecision.ANSWERED:
        return False

    return requested_by_human


def _replay(log: AiResponseLog) -> AiReply:
    """The decision already on record for this message.

    Answers exactly what the first run answered, withheld draft included:
    a second caller must not be handed a reply the first was not.
    """
    usable = log.decision in {AiDecision.SUGGESTED, AiDecision.ANSWERED}

    return AiReply(
        decision=log.decision,
        text=log.reply_text if usable else None,
        confidence=log.confidence,
        reason=log.reason,
        sources=list(log.retrieved_chunk_ids),
        message_id=log.sent_message_id,
    )


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def get_ai_response_log_repository(session: SessionDep) -> AiResponseLogRepository:
    return AiResponseLogRepository(session)


AiResponseLogRepositoryDep = Annotated[
    AiResponseLogRepository,
    Depends(get_ai_response_log_repository),
]


def get_reply_writer() -> ReplyWriter:
    """The language model the application uses, as a dependency.

    A dependency and not an import, so a test can substitute one that
    answers without reaching the network.
    """
    return ClaudeReplyWriter()


ReplyWriterDep = Annotated[ReplyWriter, Depends(get_reply_writer)]


def get_ai_response_service(
    session: SessionDep,
    conversations: ConversationRepositoryDep,
    messages: MessageRepositoryDep,
    logs: AiResponseLogRepositoryDep,
    retrieval: RetrievalServiceDep,
    commerce: CommerceContextServiceDep,
    writer: ReplyWriterDep,
    outbound: MessageServiceDep,
    events: ConversationEventRepositoryDep,
) -> AiResponseService:
    return AiResponseService(
        session=session,
        conversations=conversations,
        messages=messages,
        logs=logs,
        retrieval=retrieval,
        commerce=commerce,
        writer=writer,
        outbound=outbound,
        events=events,
    )


AiResponseServiceDep = Annotated[AiResponseService, Depends(get_ai_response_service)]
