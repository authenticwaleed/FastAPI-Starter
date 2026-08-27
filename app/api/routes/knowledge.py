import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

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
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
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
from app.services.knowledge_service import KnowledgeServiceDep
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


@router.post(
    "/documents/upload",
    status_code=status.HTTP_201_CREATED,
    responses={**INGESTING, **DOCUMENT_UNSUPPORTED},
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
    data = await file.read()

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


@router.post("/search", responses=SCOPED)
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
