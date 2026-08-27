from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge import DocumentStatus, SourceType

Name = Annotated[str, Field(min_length=1, max_length=150)]
Title = Annotated[str, Field(min_length=1, max_length=255)]


class SourceCreate(BaseModel):
    """A place a business's knowledge comes from.

    `source_type` describes what will be put in it and does not restrict
    what can: a source named `file` holding text typed by hand is a
    labelling mistake, not a corrupt state, and refusing it would mean the
    dashboard had to know which button created which source.
    """

    name: Name
    source_type: SourceType = SourceType.TEXT


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    source_type: SourceType
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime


class SourcePage(BaseModel):
    items: list[SourceRead]
    total: int
    page: int
    page_size: int


class DocumentCreate(BaseModel):
    """Knowledge typed rather than uploaded.

    The text path: a policy pasted into the dashboard, or the answer half
    of an FAQ. Uploading a file goes to the same endpoint as multipart
    form data instead, because a PDF in a JSON body would have to be
    base64 and a third larger for no gain.
    """

    knowledge_source_id: UUID
    title: Title
    # No upper bound. A returns policy is a page; a product catalogue is
    # not, and a business that pastes one should get a slow request rather
    # than a rejection with a number in it that means nothing to them.
    content: Annotated[str, Field(min_length=1)]
    metadata: dict[str, Any] = Field(default_factory=dict)


class FaqCreate(BaseModel):
    """One question and its answer.

    A separate shape because an FAQ is a pair, and flattening it into
    `content` at the client leaves every dashboard to invent its own
    formatting -- which then becomes what the assistant retrieves. Done
    here, one way, the question is part of what is embedded, which is what
    makes a customer asking it in their own words find the answer.
    """

    knowledge_source_id: UUID
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: Annotated[str, Field(min_length=1)]
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRead(BaseModel):
    id: UUID
    knowledge_source_id: UUID
    title: str
    status: DocumentStatus
    # Present only when the status is `failed`, and in plain words: a scan
    # with no text in it is the ordinary case, and "it failed" would send
    # somebody looking for a bug rather than for a different file.
    error: str | None
    # How many passages it became. The honest measure of whether a
    # document is doing anything: a document that is `ready` with no
    # chunks answers nothing.
    chunk_count: int
    # Built by the route rather than read off the model, so this is the
    # plain name: the column is called `metadata` and only the SQLAlchemy
    # attribute has to dodge `Base.metadata`.
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentPage(BaseModel):
    items: list[DocumentRead]
    total: int
    page: int
    page_size: int


class SearchRequest(BaseModel):
    """Ask the knowledge base a question directly.

    The same retrieval the assistant runs, exposed on its own so that what
    the assistant will be given can be inspected before it is trusted with
    a customer -- which is what makes the plan's pilots possible.
    """

    query: Annotated[str, Field(min_length=1, max_length=1000)]
    limit: Annotated[int, Field(ge=1, le=20)] = 5
    # Below this a passage is not evidence. Exposed rather than fixed
    # because the right floor depends on the knowledge base, and finding
    # it is exactly what this endpoint is for.
    min_score: Annotated[float, Field(ge=-1.0, le=1.0)] | None = None


class SearchMatch(BaseModel):
    """One passage, and how close it was to the question."""

    document_id: UUID
    chunk_id: UUID
    score: float
    content: str
    metadata: dict[str, Any]


class SearchResult(BaseModel):
    """What was asked, and what came back.

    The query is echoed because it is not always what the caller sent --
    normalisation happens first -- and an answer that cannot be tied to
    the question that produced it is not reproducible.
    """

    query: str
    matches: list[SearchMatch]
