import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class SourceType(StrEnum):
    """Where a piece of knowledge came from.

    Three of the plan's five, because those are the three the MVP can
    actually ingest. `website` and `product_catalog` are named in the plan
    and deliberately absent here: a value the API accepts and nothing can
    process is worse than a value it refuses.
    """

    # Typed or pasted into the dashboard.
    TEXT = "text"
    # Uploaded -- a PDF, or plain text.
    FILE = "file"
    # A question and its answer, entered as a pair.
    MANUAL_FAQ = "manual_faq"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeSource(Base):
    """One place a workspace's knowledge comes from.

    A grouping rather than content: "our returns policy", "the autumn
    catalogue". Documents hang off it, and deleting it takes them and
    their chunks with it.
    """

    __tablename__ = "knowledge_sources"

    __table_args__ = (
        # The target of the composite foreign key on documents: it is what
        # lets a document say "this source, in this workspace" rather than
        # "this source, and trust me about the workspace".
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_knowledge_sources_workspace_id_id",
        ),
        Index(
            "ix_knowledge_sources_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    name: Mapped[str] = mapped_column(String(150))

    source_type: Mapped[SourceType] = mapped_column(
        enum_column(SourceType, name="knowledge_source_type"),
    )

    # Whether anything under this source is usable. Mirrors a document's
    # own status one level up, so a dashboard can grey out a source whose
    # ingestion failed without opening it.
    status: Mapped[DocumentStatus] = mapped_column(
        enum_column(DocumentStatus, name="knowledge_source_status"),
        default=DocumentStatus.PENDING,
        server_default=text("'pending'"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"KnowledgeSource(id={self.id!r}, name={self.name!r})"


class KnowledgeDocument(Base):
    """One document, and what became of trying to read it."""

    __tablename__ = "knowledge_documents"

    __table_args__ = (
        # A source belongs to a workspace, and so does this document.
        # Naming both columns means the database refuses a document that
        # reaches across the boundary, rather than the application
        # refusing it correctly every time somebody remembers to.
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_source_id"],
            ["knowledge_sources.workspace_id", "knowledge_sources.id"],
            ondelete="CASCADE",
            name="fk_knowledge_documents_source_in_same_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_knowledge_documents_workspace_id_id",
        ),
        # The same text, ingested twice, is one document. Uploading last
        # month's price list again should not double every answer's
        # evidence, and a business that re-uploads a folder should not pay
        # to embed all of it a second time.
        UniqueConstraint(
            "workspace_id",
            "content_hash",
            name="uq_knowledge_documents_workspace_id_content_hash",
        ),
        Index(
            "ix_knowledge_documents_workspace_id_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    knowledge_source_id: Mapped[uuid.UUID]

    title: Mapped[str] = mapped_column(String(255))

    # SHA-256 of the normalised text, which is what makes re-ingestion
    # idempotent. Of the normalised text and not the file: the same policy
    # saved as PDF twice by two different tools is the same knowledge.
    content_hash: Mapped[str] = mapped_column(String(64))

    status: Mapped[DocumentStatus] = mapped_column(
        enum_column(DocumentStatus, name="knowledge_document_status"),
        default=DocumentStatus.PENDING,
        server_default=text("'pending'"),
    )

    # Why it failed, when it did. Held on the document so the dashboard can
    # say "this PDF has no text in it, it is probably a scan" rather than
    # showing a red badge and nothing else.
    error: Mapped[str | None] = mapped_column(Text, default=None)

    # Mapped under a different attribute for the reason the contact's is:
    # `metadata` is taken on a declarative class by `Base.metadata`.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"KnowledgeDocument(id={self.id!r}, status={self.status!r})"


class KnowledgeChunk(Base):
    """One passage of one document, with the vector that finds it.

    The unit an answer is grounded in. Small enough that a retrieved chunk
    is mostly relevant, and carrying enough of where it came from that an
    answer can be traced back to a page of a document a business uploaded.
    """

    __tablename__ = "knowledge_chunks"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["knowledge_documents.workspace_id", "knowledge_documents.id"],
            ondelete="CASCADE",
            name="fk_knowledge_chunks_document_in_same_workspace",
        ),
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_id_chunk_index",
        ),
        # Every retrieval starts by narrowing to one workspace, and the
        # scan that follows is over what is left. This index is the reason
        # that is a workspace's chunks rather than the installation's.
        Index("ix_knowledge_chunks_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    document_id: Mapped[uuid.UUID]

    # Where in the document this passage came from, so retrieved chunks can
    # be put back in order and a neighbour can be fetched later.
    chunk_index: Mapped[int]

    content: Mapped[str] = mapped_column(Text)

    # A plain array of doubles rather than a pgvector column, deliberately.
    # pgvector is the right answer at scale and needs an extension that
    # every developer machine, every CI runner and every deployment would
    # then have to have; an array needs stock PostgreSQL. The vectors are
    # stored normalised to unit length, which makes a dot product the
    # cosine similarity -- so the query is arithmetic the database already
    # does, and swapping in pgvector later is a migration and one method.
    embedding: Mapped[list[float]] = mapped_column(ARRAY(Float))

    # What the embedding provider charged for. Kept because it is the only
    # honest input to "what will this business's knowledge base cost".
    token_count: Mapped[int | None] = mapped_column(default=None)

    # What the plan asks a chunk to preserve: the source it belongs to, the
    # document's title, and the page or section when the format had one.
    # JSONB rather than columns because which of those exist depends
    # entirely on what was uploaded.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"KnowledgeChunk(id={self.id!r}, document_id={self.document_id!r}, "
            f"chunk_index={self.chunk_index!r})"
        )
