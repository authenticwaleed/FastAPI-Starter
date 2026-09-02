import io
import logging
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

import pypdf
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import text as text_tools
from app.core.exceptions import (
    DocumentAlreadyIngestedError,
    EmbeddingProviderError,
    KnowledgeDocumentNotFoundError,
    KnowledgeSourceNotFoundError,
    UnreadableDocumentError,
    UnsupportedDocumentTypeError,
)
from app.db.session import SessionDep
from app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingPurpose,
)
from app.integrations.embeddings.voyage import (
    MAX_BATCH,
    VoyageEmbeddingProvider,
)
from app.models.audit_log import AuditEvent
from app.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)
from app.models.notification import NotificationKind
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.knowledge import DocumentCreate, FaqCreate, SourceCreate
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.notification_service import (
    NotificationService,
    NotificationServiceDep,
)
from app.services.plans import PlanLimit
from app.services.subscription_service import (
    SubscriptionService,
    SubscriptionServiceDep,
)
from app.services.workspace_service import MAY_ADMINISTER, WorkspaceAccess

logger = logging.getLogger(__name__)

PDF_TYPE = "application/pdf"
TEXT_TYPES = frozenset(
    {"text/plain", "text/markdown", "text/csv", "application/octet-stream"}
)

# What a file may weigh. Generous for a policy document and far short of
# what would take an API worker off the air for a minute.
MAX_FILE_BYTES = 10 * 1024 * 1024

# Said in one place because two say it: the route refuses an oversized
# upload while it is still arriving, and this service refuses one that
# reached it by some other road.
TOO_LARGE = f"The file is larger than the {MAX_FILE_BYTES // (1024 * 1024)}MB limit"


class KnowledgeService:
    """A workspace's knowledge, and the pipeline that makes it retrievable.

    The plan's flow, in one place: validate, extract, normalise, chunk,
    embed, store. It runs inside the request that uploaded the document.
    That is a deliberate MVP choice rather than an oversight -- a queue
    and a worker are real infrastructure, and a business uploading a
    returns policy would rather wait two seconds than be told "processing"
    and have to come back. The status column exists so that moving this
    behind a worker later changes this file and nothing above it.
    """

    def __init__(
        self,
        session: Session,
        knowledge: KnowledgeRepository,
        embeddings: EmbeddingProvider,
        notifications: NotificationService,
        subscriptions: SubscriptionService,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._knowledge = knowledge
        self._embeddings = embeddings
        self._notifications = notifications
        self._subscriptions = subscriptions
        self._audit = audit

    # --- sources -----------------------------------------------------------

    def create_source(
        self,
        access: WorkspaceAccess,
        payload: SourceCreate,
    ) -> KnowledgeSource:
        source = self._knowledge.create_source(
            workspace_id=access.workspace.id,
            name=payload.name,
            source_type=payload.source_type,
        )
        self._session.commit()

        return source

    def get_source(
        self,
        access: WorkspaceAccess,
        source_id: uuid.UUID,
    ) -> KnowledgeSource:
        source = self._knowledge.get_source(access.workspace.id, source_id)

        if source is None:
            raise KnowledgeSourceNotFoundError(access.workspace.id, source_id)

        return source

    def list_sources(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[KnowledgeSource], int]:
        workspace_id = access.workspace.id

        return (
            self._knowledge.list_sources(
                workspace_id,
                limit=page_size,
                offset=(page - 1) * page_size,
            ),
            self._knowledge.count_sources(workspace_id),
        )

    def delete_source(self, access: WorkspaceAccess, source_id: uuid.UUID) -> None:
        """Remove a source, its documents and their chunks.

        Actually deleted rather than marked inactive. Knowledge a business
        has withdrawn must stop being able to appear in an answer to one of
        its customers, and a row that is only flagged is a row some future
        query forgets to filter.
        """
        source = self.get_source(access, source_id)
        self._knowledge.delete_source(source)
        self._session.commit()

    # --- documents ---------------------------------------------------------

    def add_text(
        self,
        access: WorkspaceAccess,
        payload: DocumentCreate,
    ) -> KnowledgeDocument:
        return self._ingest(
            access,
            source_id=payload.knowledge_source_id,
            title=payload.title,
            raw=payload.content,
            meta=payload.metadata,
        )

    def add_faq(
        self,
        access: WorkspaceAccess,
        payload: FaqCreate,
    ) -> KnowledgeDocument:
        """Store a question and its answer as one passage.

        The question goes into the text that is embedded, not just into
        the title. A customer asks "can I send this back?" and the passage
        that should match is the one whose question was "what is your
        returns policy?" -- which it will not be if only the answer was
        embedded.
        """
        return self._ingest(
            access,
            source_id=payload.knowledge_source_id,
            title=payload.question,
            raw=f"{payload.question}\n\n{payload.answer}",
            meta={**payload.metadata, "kind": "faq", "question": payload.question},
        )

    def add_file(
        self,
        access: WorkspaceAccess,
        *,
        source_id: uuid.UUID,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> KnowledgeDocument:
        # Kept although the route now refuses an oversized upload before it
        # is all in memory: this is also reached from places that never saw
        # a request, and a rule enforced only at the edge is not a rule.
        if len(data) > MAX_FILE_BYTES:
            raise UnreadableDocumentError(TOO_LARGE)

        raw = _extract(filename=filename, content_type=content_type, data=data)

        return self._ingest(
            access,
            source_id=source_id,
            title=filename,
            raw=raw,
            meta={"filename": filename, "content_type": content_type},
        )

    def get_document(
        self,
        access: WorkspaceAccess,
        document_id: uuid.UUID,
    ) -> KnowledgeDocument:
        document = self._knowledge.get_document(access.workspace.id, document_id)

        if document is None:
            raise KnowledgeDocumentNotFoundError(access.workspace.id, document_id)

        return document

    def list_documents(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
        source_id: uuid.UUID | None = None,
        status: DocumentStatus | None = None,
    ) -> tuple[Sequence[KnowledgeDocument], int]:
        workspace_id = access.workspace.id
        filters: dict[str, Any] = {"source_id": source_id, "status": status}

        return (
            self._knowledge.list_documents(
                workspace_id,
                limit=page_size,
                offset=(page - 1) * page_size,
                **filters,
            ),
            self._knowledge.count_documents(workspace_id, **filters),
        )

    def chunk_count(
        self,
        access: WorkspaceAccess,
        document_id: uuid.UUID,
    ) -> int:
        return self._knowledge.count_chunks(
            access.workspace.id,
            document_id=document_id,
        )

    def delete_document(self, access: WorkspaceAccess, document_id: uuid.UUID) -> None:
        document = self.get_document(access, document_id)
        title = document.title

        self._knowledge.delete_document(document)
        # The title is read before the row goes, because this is the entry
        # somebody comes looking for when the assistant stops being able
        # to answer a question it used to answer -- and "document
        # 4f2a-... was deleted" does not tell them which policy went.
        self._audit.did(
            access.workspace.id,
            AuditEvent.KNOWLEDGE_DOCUMENT_DELETED,
            actor_user_id=access.actor_user_id,
            meta={"document_id": str(document_id), "title": title},
        )
        self._session.commit()

    # --- the pipeline ------------------------------------------------------

    def _ingest(
        self,
        access: WorkspaceAccess,
        *,
        source_id: uuid.UUID,
        title: str,
        raw: str,
        meta: dict[str, Any],
    ) -> KnowledgeDocument:
        """Validate, normalise, chunk, embed, store.

        The document row is written and committed before the embedding
        provider is called, and the status moves with it. Deliberately
        that order, for the reason a reply is written before it is sent: a
        crash in the middle leaves a document that says `processing` and
        can be retried, where the other order leaves an upload that
        vanished.
        """
        # Before any of it, and before the provider is called: a document
        # that cannot be kept is not worth paying to embed.
        self._subscriptions.require_within_limit(
            access.workspace.id,
            PlanLimit.KNOWLEDGE_DOCUMENTS,
        )

        workspace_id = access.workspace.id
        source = self.get_source(access, source_id)

        normalised = text_tools.normalise(raw)

        if not normalised:
            raise UnreadableDocumentError("There is no text in this document")

        digest = text_tools.content_hash(normalised)

        if self._knowledge.get_document_by_hash(workspace_id, digest) is not None:
            raise DocumentAlreadyIngestedError(workspace_id, digest)

        try:
            document = self._knowledge.create_document(
                workspace_id=workspace_id,
                knowledge_source_id=source.id,
                title=title,
                content_hash=digest,
                meta=meta,
            )
            self._knowledge.set_document_status(document, DocumentStatus.PROCESSING)
            # Recorded here, in the transaction that accepts the upload,
            # rather than after the embedding finishes. The audited act is
            # somebody putting a document into the business's knowledge
            # base; whether the provider then managed to read it is the
            # document's own status, and a crash mid-embedding should not
            # lose the record of who uploaded it.
            self._audit.did(
                access.workspace.id,
                AuditEvent.KNOWLEDGE_DOCUMENT_UPLOADED,
                actor_user_id=access.actor_user_id,
                meta={"document_id": str(document.id), "title": title},
            )
            self._session.commit()
        except IntegrityError as exc:
            # Two uploads of the same file at once. The check above is not
            # a lock; the unique constraint on the hash is what settles it.
            self._session.rollback()
            raise DocumentAlreadyIngestedError(workspace_id, digest) from exc

        try:
            self._embed_into(document, source, normalised)
        except EmbeddingProviderError as exc:
            # Recorded on the document and re-raised. The upload is not
            # lost -- it is a row saying what went wrong, which somebody
            # can retry -- and the caller is told rather than being left
            # with a document that will never become ready.
            self._session.rollback()
            self._knowledge.set_document_status(
                document,
                DocumentStatus.FAILED,
                error=exc.detail,
            )
            self._knowledge.set_source_status(source, DocumentStatus.FAILED)
            # Told once while it is still unread, for the reason a failed
            # delivery is: a business uploading twenty documents against a
            # provider that is down would otherwise get twenty alerts
            # about one outage.
            self._notifications.tell_everyone(
                workspace_id=access.workspace.id,
                roles=MAY_ADMINISTER,
                kind=NotificationKind.KNOWLEDGE_INGESTION_FAILED,
                title="A document could not be added to the knowledge base",
                body=exc.detail,
                meta={"document_id": str(document.id), "title": title},
            )
            self._session.commit()
            raise

        return document

    def _embed_into(
        self,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        normalised: str,
    ) -> None:
        pieces = text_tools.chunk(normalised)

        if not pieces:
            raise UnreadableDocumentError("There is no text in this document")

        vectors: list[list[float]] = []
        counts: list[int | None] = []

        # Batched because the provider caps one request, and a catalogue
        # is thousands of passages. One failed batch fails the document,
        # which is the right outcome: half an embedded policy is a policy
        # the assistant will answer from and get wrong.
        for start in range(0, len(pieces), MAX_BATCH):
            batch = pieces[start : start + MAX_BATCH]
            result = self._embeddings.embed(
                [piece.content for piece in batch],
                purpose=EmbeddingPurpose.DOCUMENT,
            )
            vectors.extend(result.vectors)
            counts.append(result.total_tokens)

        # Unknown if any batch did not say. Summing the ones that did would
        # report a total that looks precise and is short by however much
        # the silent batch cost.
        tokens = None if any(count is None for count in counts) else sum(counts)  # type: ignore[arg-type]

        if len(vectors) != len(pieces):
            raise EmbeddingProviderError(
                f"Got {len(vectors)} vectors for {len(pieces)} passages"
            )

        # Divided evenly rather than measured per chunk: the provider
        # reports one total for the batch, and an average across passages
        # of one document is close enough for a cost estimate and honest
        # about being an estimate.
        per_chunk = None if tokens is None else tokens // len(pieces)

        self._knowledge.replace_chunks(
            workspace_id=document.workspace_id,
            document_id=document.id,
            chunks=[
                KnowledgeChunk(
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    chunk_index=piece.index,
                    content=piece.content,
                    embedding=vector,
                    token_count=per_chunk,
                    # What the plan asks a chunk to preserve, so an answer
                    # can be traced to a document a business uploaded
                    # rather than to a row id.
                    meta={
                        "source_id": str(source.id),
                        "source_name": source.name,
                        "title": document.title,
                        "chunk_index": piece.index,
                        **{
                            key: value
                            for key, value in document.meta.items()
                            if key in {"page", "section", "kind", "question"}
                        },
                    },
                )
                for piece, vector in zip(pieces, vectors, strict=True)
            ],
        )
        self._knowledge.set_document_status(document, DocumentStatus.READY)
        self._knowledge.set_source_status(source, DocumentStatus.READY)
        self._session.commit()


def _extract(*, filename: str, content_type: str | None, data: bytes) -> str:
    """Get text out of an upload, or say clearly why there is none."""
    kind = (content_type or "").split(";")[0].strip().lower()
    name = filename.lower()

    if kind == PDF_TYPE or name.endswith(".pdf"):
        return _from_pdf(data)

    if kind in TEXT_TYPES or name.endswith((".txt", ".md", ".markdown", ".csv")):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnreadableDocumentError(
                "This file is not UTF-8 text. Save it as UTF-8 and upload it again"
            ) from exc

    raise UnsupportedDocumentTypeError(content_type or filename)


def _from_pdf(data: bytes) -> str:
    """Read a PDF's text, page by page.

    A page break becomes a blank line, which is what the chunker treats as
    a boundary -- so a chunk is less likely to run across two pages that
    have nothing to do with each other.
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        # pypdf raises several unrelated types for a malformed file, and
        # every one of them means the same thing to whoever uploaded it.
        logger.info("A PDF could not be read: %s", exc)
        raise UnreadableDocumentError("This PDF could not be read") from exc

    extracted = "\n\n".join(page for page in pages if page.strip())

    if not extracted.strip():
        raise UnreadableDocumentError(
            "This PDF has no text in it. A scanned document needs to be run "
            "through OCR before it can be used"
        )

    return extracted


def get_knowledge_repository(session: SessionDep) -> KnowledgeRepository:
    return KnowledgeRepository(session)


KnowledgeRepositoryDep = Annotated[
    KnowledgeRepository,
    Depends(get_knowledge_repository),
]


def get_embedding_provider() -> EmbeddingProvider:
    """The provider the application uses, as a dependency.

    A dependency and not an import, so a test can substitute one that
    answers without reaching the network -- which is what keeps this
    suite's rule that nothing in it makes a real call.
    """
    return VoyageEmbeddingProvider()


EmbeddingProviderDep = Annotated[
    EmbeddingProvider,
    Depends(get_embedding_provider),
]


def get_knowledge_service(
    session: SessionDep,
    knowledge: KnowledgeRepositoryDep,
    embeddings: EmbeddingProviderDep,
    notifications: NotificationServiceDep,
    subscriptions: SubscriptionServiceDep,
    audit: AuditServiceDep,
) -> KnowledgeService:
    return KnowledgeService(
        session=session,
        knowledge=knowledge,
        embeddings=embeddings,
        notifications=notifications,
        subscriptions=subscriptions,
        audit=audit,
    )


KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
