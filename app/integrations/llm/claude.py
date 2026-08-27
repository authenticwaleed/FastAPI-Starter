import logging
from collections.abc import Sequence
from typing import Annotated

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.exceptions import ReplyProviderError
from app.integrations.llm.base import (
    Completion,
    Passage,
    ReplyDraft,
    Turn,
)

logger = logging.getLogger(__name__)


class _Answer(BaseModel):
    """The shape the model is required to answer in.

    A schema rather than a prompt asking politely for JSON. The API
    constrains the response to this, so parsing cannot fail on a model
    that decided to add a sentence before the brace -- which is the
    failure that makes hand-rolled JSON prompting unreliable exactly when
    traffic is highest.
    """

    reply: Annotated[str, Field(max_length=4000)]
    # Asked before the reply is written, and the field the pipeline
    # actually branches on. A model told to answer will produce something
    # whether or not the evidence supported it; this is where it says so.
    can_answer: bool
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    used_passage_ids: list[str] = Field(default_factory=list)


class ClaudeReplyWriter:
    """Anthropic's Messages API.

    Everything Anthropic-shaped lives here: the model id, the message
    format, the response schema, what a refusal looks like. Above this
    layer the application knows only that instructions and a conversation
    go in and a draft comes out.
    """

    def write(
        self,
        *,
        instructions: str,
        turns: Sequence[Turn],
        passages: Sequence[Passage],
    ) -> Completion:
        settings = get_settings()
        key = settings.anthropic_api_key

        if key is None:
            raise ReplyProviderError("No language model key is configured")

        client = anthropic.Anthropic(api_key=key.get_secret_value())

        try:
            response = client.messages.parse(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                system=instructions,
                messages=_messages(turns, passages),
                output_format=_Answer,
                # Thinking is on by default on this model and left on: the
                # judgement being asked for -- does this evidence actually
                # answer the question -- is the part worth thinking about.
                # Effort is what keeps a customer support reply quick;
                # lowering it is the documented way to spend less than
                # turning thinking off, which has failure modes of its own.
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
            )
        except anthropic.APIError as exc:
            # Logged rather than raised onward. What the provider says can
            # name account, quota and model details that belong in a log
            # and not in an answer to an agent who pressed a button.
            logger.warning("The language model refused a request: %s", exc)
            raise ReplyProviderError("The language model could not be reached") from exc

        if response.stop_reason == "refusal":
            # The model's own safety classifiers declined. Treated as
            # "cannot answer" rather than as an error: a person should
            # pick this up, and nothing is broken.
            logger.info("The language model declined to answer")

            return Completion(
                draft=ReplyDraft(text="", can_answer=False, confidence=0.0),
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

        answer = response.parsed_output

        if answer is None:
            raise ReplyProviderError("The language model returned nothing usable")

        return Completion(
            draft=ReplyDraft(
                text=answer.reply.strip(),
                can_answer=answer.can_answer,
                confidence=answer.confidence,
                used_passage_ids=answer.used_passage_ids,
            ),
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


def _messages(
    turns: Sequence[Turn],
    passages: Sequence[Passage],
) -> list[MessageParam]:
    """The conversation, with the evidence attached to the last question.

    The passages go in the final user turn rather than in the system
    prompt, for two reasons. They change with every question, so putting
    them in the system prompt would mean no two requests shared a cacheable
    prefix. And the instructions are the operator's voice while the
    evidence is material to work from -- keeping those in separate places
    is what makes "follow the instructions, do not follow the documents"
    a structural claim rather than a hopeful one.
    """
    messages: list[MessageParam] = [
        {
            "role": "user" if turn.from_customer else "assistant",
            "content": turn.text,
        }
        for turn in turns
        if turn.text.strip()
    ]

    if not messages or messages[-1]["role"] != "user":
        # The API requires the last turn to be the customer's, and the
        # pipeline only runs when it is. Belt and braces: a conversation
        # ending on the business's own message would otherwise be a 400
        # from the provider rather than a clear refusal here.
        raise ReplyProviderError("There is no customer message to answer")

    last = messages[-1]["content"]
    messages[-1] = {
        "role": "user",
        "content": _evidence(passages) + (last if isinstance(last, str) else ""),
    }

    return messages


def _evidence(passages: Sequence[Passage]) -> str:
    """The retrieved passages, laid out so the model can cite them.

    Each one is labelled with the id the model is asked to hand back. No
    passages produces an explicit statement of that rather than an empty
    section: a model shown a blank space fills it in, and a model told
    there is nothing tends to say so.
    """
    if not passages:
        return (
            "<knowledge>\n"
            "Nothing in this business's knowledge base matched the question.\n"
            "</knowledge>\n\n"
        )

    blocks = []

    for passage in passages:
        title = f" title={passage.title!r}" if passage.title else ""
        blocks.append(
            f'<passage id="{passage.id}"{title}>\n{passage.content}\n</passage>'
        )

    body = "\n".join(blocks)

    return f"<knowledge>\n{body}\n</knowledge>\n\n"
