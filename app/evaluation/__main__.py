"""Run the evaluation against the real providers.

    uv run python -m app.evaluation

Deliberately not part of the test suite. This one calls the embedding
provider and the model for real -- which costs money, needs keys, and
gives a slightly different answer every time. What belongs in CI is the
regression test beside it, which runs the same dataset through the same
runner with fakes and proves the harness itself still works.

Everything it writes is rolled back. An evaluation that leaves a dozen
contacts and conversations in a workspace would be an evaluation nobody
runs twice.
"""

import logging
import secrets
import sys
import uuid

from sqlalchemy.orm import Session

from app.core.logging import configure_logging
from app.db.session import get_engine
from app.evaluation.dataset import load_cases
from app.evaluation.runner import run
from app.integrations.embeddings.voyage import VoyageEmbeddingProvider
from app.integrations.llm.claude import ClaudeReplyWriter
from app.integrations.messaging.whatsapp import WhatsAppCloudProvider
from app.models.user import User
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate
from app.services.workspace_service import WorkspaceAccess, WorkspaceService

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    cases = load_cases()

    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        report = run(
            cases,
            session=session,
            access=_scratch_workspace(session),
            embeddings=VoyageEmbeddingProvider(),
            writer=ClaudeReplyWriter(),
            # Never used: every case runs in suggest-only, so nothing is
            # delivered. Passed because the pipeline is assembled whole.
            messaging=WhatsAppCloudProvider(),
        )
    finally:
        session.close()
        # Rolled back whatever happened, including a crash halfway
        # through: an evaluation must not leave rows behind.
        transaction.rollback()
        connection.close()

    sys.stdout.write(report.summary() + "\n")

    # Non-zero when anything was wrong, so this can be a gate rather than
    # only a report.
    return 0 if report.correct_rate == 1.0 else 1


def _scratch_workspace(session: Session) -> WorkspaceAccess:
    """A workspace that exists only for the length of this run."""
    marker = uuid.uuid4().hex[:8]
    owner = User(
        name="Evaluation",
        email=f"evaluation-{marker}@example.invalid",
        # Random rather than a fixed placeholder: nothing ever
        # authenticates as this account, and a value no password can
        # produce is a better guarantee of that than a comment saying so.
        # The whole row is rolled back when the run ends regardless.
        hashed_password=secrets.token_urlsafe(32),
    )
    session.add(owner)
    session.flush()

    workspaces = WorkspaceService(
        session=session,
        workspaces=WorkspaceRepository(session),
        memberships=WorkspaceMembershipRepository(session),
    )
    workspace = workspaces.create(
        WorkspaceCreate(name="Evaluation", slug=f"evaluation-{marker}"),
        creator=owner,
    )

    return workspaces.access(workspace.id, owner)


if __name__ == "__main__":
    raise SystemExit(main())
