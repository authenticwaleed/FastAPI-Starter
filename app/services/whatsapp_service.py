import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.encryption import decrypt, encrypt
from app.core.exceptions import (
    WhatsAppAlreadyConnectedError,
    WhatsAppNotConnectedError,
)
from app.db.session import SessionDep
from app.integrations.messaging.base import MessagingProvider, SentMessage
from app.integrations.messaging.whatsapp import WhatsAppCloudProvider
from app.models.audit_log import AuditEvent
from app.models.whatsapp_account import WhatsAppAccount
from app.repositories.whatsapp_account_repository import (
    WhatsAppAccountRepository,
)
from app.schemas.whatsapp import WhatsAppConnect
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.workspace_service import WorkspaceAccess

logger = logging.getLogger(__name__)


@lru_cache
def get_messaging_provider() -> MessagingProvider:
    """The provider the application talks to.

    A dependency rather than an import, so a test substitutes a fake by
    overriding it instead of by patching a module. Cached because the
    adapter holds no state -- only the workspace's own credentials, which
    arrive per call.
    """
    return WhatsAppCloudProvider()


MessagingProviderDep = Annotated[
    MessagingProvider,
    Depends(get_messaging_provider),
]


class WhatsAppService:
    """Connecting a number, and getting a message out through it.

    The access token is decrypted here, held for the length of one call,
    and passed straight to the adapter. It is never returned, never
    logged, and never stored anywhere but the encrypted column.
    """

    def __init__(
        self,
        session: Session,
        accounts: WhatsAppAccountRepository,
        provider: MessagingProvider,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._provider = provider
        self._audit = audit

    def connect(
        self,
        access: WorkspaceAccess,
        payload: WhatsAppConnect,
    ) -> WhatsAppAccount:
        workspace_id = access.workspace.id

        if self._accounts.get_for_workspace(workspace_id) is not None:
            raise WhatsAppAlreadyConnectedError(workspace_id)

        try:
            account = self._accounts.create(
                workspace_id=workspace_id,
                provider=payload.provider,
                phone_number=payload.phone_number,
                external_phone_number_id=payload.external_phone_number_id,
                external_business_account_id=payload.external_business_account_id,
                # Encrypted before it reaches the session, so the plain
                # token never sits in an object that something else might
                # serialise.
                access_token_encrypted=encrypt(payload.access_token),
            )
            # The number, never the token. What is worth recording is
            # which line the business's customers are now reaching, and
            # who put it there; the credential itself belongs in one
            # encrypted column and nowhere else.
            self._audit.did(
                workspace_id,
                AuditEvent.WHATSAPP_CONNECTED,
                actor_user_id=access.membership.user_id,
                meta={"phone_number": account.phone_number},
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            # Either this workspace raced itself, or the number id is
            # already connected somewhere else. Both are a conflict, and
            # neither answer should say which: the second would confirm
            # that a given number is in use on this platform.
            raise WhatsAppAlreadyConnectedError(workspace_id) from exc

        logger.info("WhatsApp connected for workspace %s", workspace_id)

        return account

    def get(self, access: WorkspaceAccess) -> WhatsAppAccount:
        account = self._accounts.get_for_workspace(access.workspace.id)

        if account is None:
            raise WhatsAppNotConnectedError(access.workspace.id)

        return account

    def disconnect(self, access: WorkspaceAccess) -> None:
        """Remove the connection, and the token with it.

        Deleted rather than marked disconnected: what is being removed is
        a credential, and a revoked credential that is still in the table
        is a credential somebody can still read.
        """
        account = self.get(access)
        phone_number = account.phone_number

        self._accounts.delete(account)
        # Read off the row before it is deleted, because after this there
        # is nothing left to say which number was disconnected -- and a
        # business whose customers have stopped getting through needs
        # exactly that, along with who did it.
        self._audit.did(
            access.workspace.id,
            AuditEvent.WHATSAPP_DISCONNECTED,
            actor_user_id=access.membership.user_id,
            meta={"phone_number": phone_number},
        )
        self._session.commit()

        logger.info("WhatsApp disconnected for workspace %s", access.workspace.id)

    def deliver(self, account: WhatsAppAccount, *, to: str, text: str) -> SentMessage:
        """Hand one message to the provider.

        Raises MessagingProviderError, which the caller records on the
        message before letting it reach the client.
        """
        return self._provider.send_text(
            phone_number_id=account.external_phone_number_id,
            access_token=decrypt(account.access_token_encrypted),
            to=to,
            text=text,
        )


def get_whatsapp_account_repository(
    session: SessionDep,
) -> WhatsAppAccountRepository:
    return WhatsAppAccountRepository(session)


WhatsAppAccountRepositoryDep = Annotated[
    WhatsAppAccountRepository,
    Depends(get_whatsapp_account_repository),
]


def get_whatsapp_service(
    session: SessionDep,
    accounts: WhatsAppAccountRepositoryDep,
    provider: MessagingProviderDep,
    audit: AuditServiceDep,
) -> WhatsAppService:
    return WhatsAppService(
        session=session,
        accounts=accounts,
        provider=provider,
        audit=audit,
    )


WhatsAppServiceDep = Annotated[WhatsAppService, Depends(get_whatsapp_service)]
