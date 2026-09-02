import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.whatsapp_account import (
    MessagingProviderName,
    WhatsAppAccount,
    WhatsAppAccountStatus,
)
from app.models.workspace import Workspace


class WhatsAppAccountRepository:
    """Every query against the whatsapp_accounts table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: MessagingProviderName,
        phone_number: str,
        external_phone_number_id: str,
        external_business_account_id: str | None,
        access_token_encrypted: str,
    ) -> WhatsAppAccount:
        account = WhatsAppAccount(
            workspace_id=workspace_id,
            provider=provider,
            phone_number=phone_number,
            external_phone_number_id=external_phone_number_id,
            external_business_account_id=external_business_account_id,
            access_token_encrypted=access_token_encrypted,
        )

        self._session.add(account)
        self._session.flush()

        return account

    def get_for_workspace(self, workspace_id: uuid.UUID) -> WhatsAppAccount | None:
        return self._session.scalar(
            select(WhatsAppAccount).where(WhatsAppAccount.workspace_id == workspace_id)
        )

    def get_by_phone_number_id(
        self,
        external_phone_number_id: str,
    ) -> WhatsAppAccount | None:
        """The lookup that turns a webhook delivery into a workspace.

        Deliberately not workspace-scoped, and the one query in this
        codebase that is not: the delivery arrives with nothing but a
        phone number id, and finding out whose it is *is* the question.
        Everything downstream takes the workspace from the row this
        returns, so the boundary is established here rather than assumed.
        """
        return self._session.scalar(
            select(WhatsAppAccount).where(
                WhatsAppAccount.external_phone_number_id == external_phone_number_id,
                WhatsAppAccount.status == WhatsAppAccountStatus.CONNECTED,
            )
        )

    def list_with_workspaces(self) -> list[tuple[WhatsAppAccount, Workspace]]:
        """Every connected number on the platform, with whose it is.

        Not workspace-scoped, unlike everything else in this file, and it
        is the operations console's query rather than a tenant's: the
        question is "which numbers are connected and are any of them
        broken", which no single customer can ask.

        Joined rather than looked up per row, and an inner join because
        the foreign key cascades -- an account cannot outlive its
        workspace.
        """
        rows = self._session.execute(
            select(WhatsAppAccount, Workspace)
            .join(Workspace, Workspace.id == WhatsAppAccount.workspace_id)
            .order_by(WhatsAppAccount.connected_at.desc(), WhatsAppAccount.id)
        ).all()

        return [(account, workspace) for account, workspace in rows]

    def delete(self, account: WhatsAppAccount) -> None:
        self._session.delete(account)
        self._session.flush()
