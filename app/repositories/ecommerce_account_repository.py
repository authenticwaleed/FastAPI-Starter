import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.ecommerce.base import EcommerceProviderName
from app.models.ecommerce_account import (
    EcommerceAccount,
    EcommerceAccountStatus,
)


class EcommerceAccountRepository:
    """Every query against the ecommerce_accounts table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        provider: EcommerceProviderName,
        shop_domain: str,
        access_token_encrypted: str,
    ) -> EcommerceAccount:
        account = EcommerceAccount(
            workspace_id=workspace_id,
            provider=provider,
            shop_domain=shop_domain,
            access_token_encrypted=access_token_encrypted,
        )

        self._session.add(account)
        self._session.flush()

        return account

    def get_for_workspace(self, workspace_id: uuid.UUID) -> EcommerceAccount | None:
        return self._session.scalar(
            select(EcommerceAccount).where(
                EcommerceAccount.workspace_id == workspace_id
            )
        )

    def get_by_shop_domain(self, shop_domain: str) -> EcommerceAccount | None:
        """The lookup a webhook costs.

        A delivery names a shop and nothing else, so this is what turns
        it into a workspace -- and the reason the column is unique across
        every workspace rather than within one.
        """
        return self._session.scalar(
            select(EcommerceAccount).where(EcommerceAccount.shop_domain == shop_domain)
        )

    def reconnect(
        self,
        account: EcommerceAccount,
        *,
        access_token_encrypted: str,
    ) -> EcommerceAccount:
        """A shop that was uninstalled and installed again.

        The row is reused rather than replaced, so everything already
        synced stays attached to it -- and so a shop that reconnects
        picks up where it left off instead of arriving as a stranger.
        """
        account.access_token_encrypted = access_token_encrypted
        account.status = EcommerceAccountStatus.CONNECTED
        self._session.flush()

        return account

    def mark_synced(
        self,
        account: EcommerceAccount,
        at: datetime,
    ) -> EcommerceAccount:
        account.last_synced_at = at
        self._session.flush()

        return account

    def disconnect(self, account: EcommerceAccount) -> EcommerceAccount:
        """Stop using it, and destroy the token.

        The row and everything synced through it stay. A business that
        uninstalls has stopped granting access; it has not asked to lose
        its own catalogue, and deleting one to express the other would be
        a data loss nobody requested.
        """
        account.status = EcommerceAccountStatus.DISCONNECTED
        # Overwritten rather than left to expire. A revoked token is
        # worthless to the application and still worth stealing.
        account.access_token_encrypted = ""
        self._session.flush()

        return account

    def delete(self, account: EcommerceAccount) -> None:
        self._session.delete(account)
        self._session.flush()
