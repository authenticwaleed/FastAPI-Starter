import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    delete,
    func,
    literal,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SourceType,
)


@dataclass(frozen=True)
class ScoredChunk:
    """One chunk, with how close it was to what was asked."""

    chunk: KnowledgeChunk
    score: float


class KnowledgeRepository:
    """Every query against the knowledge tables lives here.

    Workspace-scoped throughout, and here that is not a convention -- it is
    the security boundary the whole feature rests on. A business's uploaded
    documents are its prices, its policies and sometimes its customers'
    details; a retrieval that reached across workspaces would put one
    business's confidential material into another's customer conversation,
    which is the single worst thing this product could do.

    So every method takes `workspace_id` first, and none of them will
    answer without it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- sources -----------------------------------------------------------

    def create_source(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        source_type: SourceType,
    ) -> KnowledgeSource:
        source = KnowledgeSource(
            workspace_id=workspace_id,
            name=name,
            source_type=source_type,
        )

        self._session.add(source)
        self._session.flush()

        return source

    def get_source(
        self,
        workspace_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> KnowledgeSource | None:
        return self._session.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.workspace_id == workspace_id,
                KnowledgeSource.id == source_id,
            )
        )

    def list_sources(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[KnowledgeSource]:
        return self._session.scalars(
            select(KnowledgeSource)
            .where(KnowledgeSource.workspace_id == workspace_id)
            .order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_sources(self, workspace_id: uuid.UUID) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(KnowledgeSource)
                .where(KnowledgeSource.workspace_id == workspace_id)
            )
            or 0
        )

    def set_source_status(
        self,
        source: KnowledgeSource,
        status: DocumentStatus,
    ) -> KnowledgeSource:
        source.status = status
        self._session.flush()

        return source

    def delete_source(self, source: KnowledgeSource) -> None:
        """Take the source, and everything under it.

        The documents and their chunks go with it by cascade, which is the
        point: knowledge a business has withdrawn must stop being able to
        appear in an answer, and a chunk left behind is still retrievable.
        """
        self._session.delete(source)
        self._session.flush()

    # --- documents ---------------------------------------------------------

    def create_document(
        self,
        *,
        workspace_id: uuid.UUID,
        knowledge_source_id: uuid.UUID,
        title: str,
        content_hash: str,
        meta: dict[str, Any],
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            workspace_id=workspace_id,
            knowledge_source_id=knowledge_source_id,
            title=title,
            content_hash=content_hash,
            status=DocumentStatus.PENDING,
            meta=meta,
        )

        self._session.add(document)
        self._session.flush()

        return document

    def get_document(
        self,
        workspace_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> KnowledgeDocument | None:
        return self._session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.id == document_id,
            )
        )

    def get_document_by_hash(
        self,
        workspace_id: uuid.UUID,
        content_hash: str,
    ) -> KnowledgeDocument | None:
        """What makes re-ingesting the same file cheap instead of doubled."""
        return self._session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.content_hash == content_hash,
            )
        )

    def list_documents(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        source_id: uuid.UUID | None = None,
        status: DocumentStatus | None = None,
    ) -> Sequence[KnowledgeDocument]:
        return self._session.scalars(
            self._documents(select(KnowledgeDocument), workspace_id, source_id, status)
            .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_documents(
        self,
        workspace_id: uuid.UUID,
        *,
        source_id: uuid.UUID | None = None,
        status: DocumentStatus | None = None,
    ) -> int:
        return (
            self._session.scalar(
                self._documents(
                    select(func.count()).select_from(KnowledgeDocument),
                    workspace_id,
                    source_id,
                    status,
                )
            )
            or 0
        )

    @staticmethod
    def _documents(
        statement: Select[Any],
        workspace_id: uuid.UUID,
        source_id: uuid.UUID | None,
        status: DocumentStatus | None,
    ) -> Select[Any]:
        statement = statement.where(KnowledgeDocument.workspace_id == workspace_id)

        if source_id is not None:
            statement = statement.where(
                KnowledgeDocument.knowledge_source_id == source_id
            )

        if status is not None:
            statement = statement.where(KnowledgeDocument.status == status)

        return statement

    def set_document_status(
        self,
        document: KnowledgeDocument,
        status: DocumentStatus,
        *,
        error: str | None = None,
    ) -> KnowledgeDocument:
        """Move a document along, and say why if it stopped.

        The error is cleared on any status that is not `failed`, so a
        document that failed and was then ingested successfully does not
        keep showing yesterday's reason.
        """
        document.status = status
        document.error = error if status == DocumentStatus.FAILED else None
        self._session.flush()

        return document

    def delete_document(self, document: KnowledgeDocument) -> None:
        self._session.delete(document)
        self._session.flush()

    # --- chunks ------------------------------------------------------------

    def replace_chunks(
        self,
        *,
        workspace_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: Sequence[KnowledgeChunk],
    ) -> None:
        """Write a document's chunks, having removed whatever was there.

        Replace rather than append, so re-processing a document is
        idempotent. Appending would leave the old passages retrievable
        beside the new ones, and an assistant citing a policy that was
        edited last week is worse than one that cannot find it.
        """
        self._session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.workspace_id == workspace_id,
                KnowledgeChunk.document_id == document_id,
            )
        )
        self._session.add_all(chunks)
        self._session.flush()

    def count_chunks(
        self,
        workspace_id: uuid.UUID,
        *,
        document_id: uuid.UUID | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.workspace_id == workspace_id)
        )

        if document_id is not None:
            statement = statement.where(KnowledgeChunk.document_id == document_id)

        return self._session.scalar(statement) or 0

    def search(
        self,
        workspace_id: uuid.UUID,
        *,
        embedding: Sequence[float],
        limit: int,
        min_score: float,
    ) -> list[ScoredChunk]:
        """The nearest passages to a question, within one workspace.

        The score is a dot product, which is the cosine similarity because
        every vector on both sides of it is stored at unit length. Computed
        in the database rather than by reading every chunk into Python:
        the point of a `LIMIT` is that the rows that lose never leave the
        server.

        `workspace_id` is in the WHERE clause and there is no code path
        that omits it. That is the tenant boundary for the whole feature.
        Only documents that are `ready` are searched -- a document still
        being processed has a partial set of chunks, and answering from
        half a policy is worse than answering from none of it.

        Chunks whose vector is a different length are skipped. `unnest`
        over two arrays pads the shorter one with nulls, which sum()
        ignores, so a stored vector from before an `embedding_dimensions`
        change would otherwise score on the overlap alone -- a plausible
        number that means nothing. Returning nothing until those chunks
        are re-embedded is the failure worth having.
        """
        if not embedding:
            return []

        score = self._score(embedding)

        rows = self._session.execute(
            select(KnowledgeChunk, score.label("score"))
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .where(
                KnowledgeChunk.workspace_id == workspace_id,
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.status == DocumentStatus.READY,
                func.array_length(KnowledgeChunk.embedding, 1) == len(embedding),
                score >= min_score,
            )
            .order_by(score.desc())
            .limit(limit)
        ).all()

        return [ScoredChunk(chunk=chunk, score=float(value)) for chunk, value in rows]

    @staticmethod
    def _score(embedding: Sequence[float]) -> ColumnElement[float]:
        """The dot product of a chunk's vector with the question's.

        `unnest` over both arrays at once pairs them off position by
        position, so the whole similarity is one expression PostgreSQL
        evaluates per row -- no stored function to migrate, and no
        extension to install on every machine that runs this.

        This is the line to replace when the knowledge base outgrows a
        scan. `embedding <=> :query` against a pgvector column, with an
        index behind it, is the same number arrived at faster; everything
        above this method is written not to care which.
        """
        # `render_derived` is what emits the `AS t(chunk_value, query_value)`
        # column list. Without it PostgreSQL has no name for either column
        # of a two-argument unnest, and the query fails at the database
        # rather than in a type check.
        pair = (
            func.unnest(
                KnowledgeChunk.embedding,
                literal(list(embedding), ARRAY(Float)),
            )
            .table_valued("chunk_value", "query_value")
            .render_derived()
        )

        return (
            select(func.sum(pair.c.chunk_value * pair.c.query_value))
            .select_from(pair)
            .scalar_subquery()
        )
