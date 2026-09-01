import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.dependencies.rate_limit import limit_by_workspace
from app.api.dependencies.workspace import (
    WorkspaceAdminDep,
    WorkspaceAgentDep,
    WorkspaceMemberDep,
)
from app.api.errors import (
    DOCUMENT_UNREADABLE,
    DOCUMENT_UNSUPPORTED,
    EMBEDDING_UNAVAILABLE,
    KNOWLEDGE_CONFLICT,
    KNOWLEDGE_NOT_FOUND,
    RATE_LIMITED,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.core.exceptions import UnreadableDocumentError
from app.core.rate_limit import RateLimited
from app.models.knowledge import DocumentStatus, KnowledgeDocument
from app.schemas.knowledge import (
    DocumentCreate,
    DocumentPage,
    DocumentRead,
    FaqCreate,
    SearchMatch,
    SearchRequest,
    SearchResult,
    SourceCreate,
    SourcePage,
    SourceRead,
)
from app.services.knowledge_service import (
    MAX_FILE_BYTES,
    TOO_LARGE,
    KnowledgeServiceDep,
)
from app.services.retrieval_service import MIN_SCORE, RetrievalServiceDep
from app.services.workspace_service import WorkspaceAccess

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge",
    tags=["knowledge"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}
NAMED = {**SCOPED, **KNOWLEDGE_NOT_FOUND}
INGESTING = {
    **NAMED,
    **KNOWLEDGE_CONFLICT,
    **DOCUMENT_UNREADABLE,
    **EMBEDDING_UNAVAILABLE,
}


# Read in pieces this size. Small enough that the overshoot before the
# limit is noticed is negligible, large enough not to make a syscall per
# kilobyte of a file that is going to be accepted.
_CHUNK_BYTES = 64 * 1024


async def _read_within_limit(file: UploadFile) -> bytes:
    """Read an upload, refusing it the moment it passes the limit.

    The service checks the size too, and must: it is reached from places
    that never saw a request. But by the time a value arrives there the
    whole body is already `bytes` in memory, so that check on its own
    bounds nothing -- somebody sending two gigabytes has two gigabytes
    allocated before being told the limit is ten megabytes, and on a
    process shared by every tenant that is one workspace deciding how much
    memory the others get.

    So the bound is applied while the body is still arriving. What a
    request can cost is then the limit, rather than whatever the sender
    chose to send.

    `file.size` is the count the multipart parser already made, and it
    turns the ordinary oversized upload away without reading any of it.
    It is optional, though -- absent, the loop is what holds the bound.
    """
    if file.size is not None and file.size > MAX_FILE_BYTES:
        raise UnreadableDocumentError(TOO_LARGE)

    chunks: list[bytes] = []
    read = 0

    while chunk := await file.read(_CHUNK_BYTES):
        read += len(chunk)

        if read > MAX_FILE_BYTES:
            raise UnreadableDocumentError(TOO_LARGE)

        chunks.append(chunk)

    return b"".join(chunks)


def _document(
    service: KnowledgeServiceDep,
    access: WorkspaceAccess,
    document: KnowledgeDocument,
) -> DocumentRead:
    """A document with the count of what it actually became.

    The chunk count is the honest measure of whether an upload did
    anything: a document that says `ready` and produced nothing answers no
    questions, and without this the API would report that as success.
    """
    return DocumentRead(
        id=document.id,
        knowledge_source_id=document.knowledge_source_id,
        title=document.title,
        status=document.status,
        error=document.error,
        chunk_count=service.chunk_count(access, document.id),
        metadata=document.meta,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


# Reading takes any member; writing takes an admin. Deliberately stricter
# than contacts: what goes in here is what the assistant will tell
# customers in the business's name, so adding to it is closer to changing
# the workspace's settings than to handling a conversation.
@router.post(
    "/sources",
    status_code=status.HTTP_201_CREATED,
    responses=SCOPED,
)
def create_source(
    payload: SourceCreate,
    access: WorkspaceAdminDep,
    service: KnowledgeServiceDep,
) -> SourceRead:
    return SourceRead.model_validate(service.create_source(access, payload))


@router.get("/sources", responses=SCOPED)
def list_sources(
    access: WorkspaceMemberDep,
    service: KnowledgeServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SourcePage:
    sources, total = service.list_sources(access, page=page, page_size=page_size)

    return SourcePage(
        items=[SourceRead.model_validate(source) for source in sources],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sources/{source_id}", responses=NAMED)
def read_source(
    source_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: KnowledgeServiceDep,
) -> SourceRead:
    return SourceRead.model_validate(service.get_source(access, source_id))


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NAMED,
)
def delete_source(
    source_id: uuid.UUID,
    access: WorkspaceAdminDep,
    service: KnowledgeServiceDep,
) -> None:
    """Remove a source, its documents and everything retrievable from them.

    Actually deleted. Knowledge a business has withdrawn has to stop being
    able to appear in an answer to one of its customers.
    """
    service.delete_source(access, source_id)


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    responses=INGESTING,
)
def add_document(
    payload: DocumentCreate,
    access: WorkspaceAdminDep,
    service: KnowledgeServiceDep,
) -> DocumentRead:
    """Add knowledge as text.

    Processed before this returns rather than queued: a business pasting a
    returns policy would rather wait than be told to come back, and a
    document that is `ready` when the call ends is one the assistant can
    already answer from. A large upload is correspondingly slow, which is
    what a worker will fix.
    """
    return _document(service, access, service.add_text(access, payload))


@router.post(
    "/documents/faq",
    status_code=status.HTTP_201_CREATED,
    responses=INGESTING,
)
def add_faq(
    payload: FaqCreate,
    access: WorkspaceAdminDep,
    service: KnowledgeServiceDep,
) -> DocumentRead:
    """Add one question and its answer.

    Its own endpoint because an FAQ is a pair, and the question is part of
    what gets embedded -- which is what makes a customer asking it in their
    own words find the answer.
    """
    return _document(service, access, service.add_faq(access, payload))


# Uploading and searching are limited per workspace, and neither is
# limited because it is slow. Each upload is a file to read, chunk and
# embed, and each search is an embedding of its own: both are a paid API
# call per request, charged to the business making it.
@router.post(
    "/documents/upload",
    status_code=status.HTTP_201_CREATED,
    responses={**INGESTING, **DOCUMENT_UNSUPPORTED, **RATE_LIMITED},
    dependencies=[Depends(limit_by_workspace(RateLimited.UPLOADS))],
)
async def upload_document(
    access: WorkspaceAdminDep,
    service: KnowledgeServiceDep,
    knowledge_source_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> DocumentRead:
    """Upload a PDF or a plain text file.

    `async` because reading an upload is I/O: FastAPI spools a large one
    to disk, and a synchronous handler reading it would hold a worker
    thread for the duration. The ingestion below it is ordinary blocking
    work and runs where it is.
    """
    data = await _read_within_limit(file)

    return _document(
        service,
        access,
        service.add_file(
            access,
            source_id=knowledge_source_id,
            filename=file.filename or "upload",
            content_type=file.content_type,
            data=data,
        ),
    )


@router.get("/documents", responses=SCOPED)
def list_documents(
    access: WorkspaceMemberDep,
    service: KnowledgeServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
) -> DocumentPage:
    documents, total = service.list_documents(
        access,
        page=page,
        page_size=page_size,
        source_id=source_id,
        status=status_filter,
    )

    return DocumentPage(
        items=[_document(service, access, document) for document in documents],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/documents/{document_id}", responses=NAMED)
def read_document(
    document_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: KnowledgeServiceDep,
) -> DocumentRead:
    return _document(service, access, service.get_document(access, document_id))


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NAMED,
)
def delete_document(
    document_id: uuid.UUID,
    access: WorkspaceAdminDep,
    service: KnowledgeServiceDep,
) -> None:
    service.delete_document(access, document_id)


@router.post(
    "/search",
    responses={**SCOPED, **RATE_LIMITED},
    dependencies=[Depends(limit_by_workspace(RateLimited.SEARCH))],
)
def search_knowledge(
    payload: SearchRequest,
    access: WorkspaceAgentDep,
    service: RetrievalServiceDep,
) -> SearchResult:
    """Ask the knowledge base what it has on a question.

    The same retrieval the assistant runs, on its own. That is what makes
    the plan's pilots possible: before a business lets the assistant
    answer a customer, somebody can see exactly what it would have been
    given to answer from.

    Finding nothing is a 200 with no matches. A question the knowledge
    base cannot answer is an ordinary outcome and the single most useful
    thing this endpoint reports.
    """
    retrieval = service.retrieve(
        access.workspace.id,
        payload.query,
        limit=payload.limit,
        min_score=payload.min_score if payload.min_score is not None else MIN_SCORE,
    )

    return SearchResult(
        query=retrieval.query,
        matches=[
            SearchMatch(
                document_id=match.document_id,
                chunk_id=match.chunk_id,
                score=match.score,
                content=match.content,
                metadata=match.metadata,
            )
            for match in retrieval.matches
        ],
    )
