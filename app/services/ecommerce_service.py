import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from jwt import InvalidTokenError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.encryption import decrypt, encrypt
from app.core.exceptions import (
    EcommerceProviderError,
    StorefrontAlreadyConnectedError,
    StorefrontNotConnectedError,
)
from app.db.session import SessionDep
from app.integrations.ecommerce.base import EcommerceProvider
from app.integrations.ecommerce.shopify import ShopifyProvider, normalise_shop
from app.models.ecommerce_account import (
    EcommerceAccount,
    EcommerceAccountStatus,
)
from app.repositories.ecommerce_account_repository import (
    EcommerceAccountRepository,
)
from app.services.ecommerce_sync_service import (
    EcommerceSyncService,
    EcommerceSyncServiceDep,
    SyncReport,
)
from app.services.workspace_service import WorkspaceAccess

logger = logging.getLogger(__name__)

# How long a half-finished installation stays valid. Long enough for
# somebody to read a permissions screen and think about it, short enough
# that a link left in a browser tab overnight is not a way to attach a
# shop to a workspace tomorrow.
INSTALL_WINDOW = timedelta(minutes=15)

# Where the provider sends the shop owner back to. App-wide rather than
# per workspace, because a provider is configured with one redirect URI --
# which is why the workspace has to travel in `state`.
CALLBACK_PATH = "/api/v1/integrations/shopify/callback"


@lru_cache
def get_ecommerce_provider() -> EcommerceProvider:
    """The storefront this application talks to.

    A dependency rather than an import, so a test substitutes a fake by
    overriding it. Cached because the adapter holds no state -- only the
    workspace's own credentials, which arrive per call.
    """
    return ShopifyProvider()


EcommerceProviderDep = Annotated[
    EcommerceProvider,
    Depends(get_ecommerce_provider),
]


@dataclass(frozen=True)
class Installation:
    """Where to send a shop owner, and which shop they are approving."""

    authorize_url: str
    shop_domain: str


class EcommerceService:
    """Connecting a storefront, reading it, and letting it go.

    Two halves, and they are asymmetric for the same reason invitations
    are. Starting an installation is administration and runs behind the
    workspace dependency; finishing one cannot -- the provider is the
    caller, there is no session, and the only thing vouching for the
    request is a signed state parameter and the provider's own HMAC.
    """

    def __init__(
        self,
        session: Session,
        accounts: EcommerceAccountRepository,
        provider: EcommerceProvider,
        sync: EcommerceSyncService,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._provider = provider
        self._sync = sync

    # --- installing --------------------------------------------------------

    def begin_install(self, access: WorkspaceAccess, shop: str) -> Installation:
        """Where to send the shop owner to approve this.

        Refused if something is already connected here, so that
        connecting a second shop is a deliberate disconnect first rather
        than a silent replacement of the one the assistant has been
        answering from.
        """
        workspace_id = access.workspace.id
        domain = normalise_shop(shop)
        existing = self._accounts.get_for_workspace(workspace_id)

        if existing is not None and existing.status == EcommerceAccountStatus.CONNECTED:
            raise StorefrontAlreadyConnectedError(workspace_id)

        return Installation(
            authorize_url=self._provider.authorize_url(
                shop=domain,
                state=_sign_state(workspace_id, domain),
                redirect_uri=callback_url(),
            ),
            shop_domain=domain,
        )

    def complete_install(self, params: dict[str, str]) -> EcommerceAccount:
        """Finish what begin_install started, on the provider's callback.

        Three things have to hold, and all three fail the same way. The
        provider's HMAC has to verify, the state has to be one this
        application signed and not yet expired, and the shop named in the
        state has to be the shop in the callback -- otherwise an operator
        who could get a shop owner to approve one installation could
        attach a different shop to their own workspace.
        """
        if not self._provider.verify_install(params):
            raise EcommerceProviderError("The installation callback did not verify")

        workspace_id, expected_shop = _read_state(params.get("state", ""))
        shop = normalise_shop(params.get("shop", ""))

        if shop != expected_shop:
            raise EcommerceProviderError("The callback names a different shop")

        code = params.get("code")

        if not code:
            raise EcommerceProviderError("The callback carried no code")

        token = self._provider.exchange_code(shop=shop, code=code)

        return self._store(workspace_id, shop, token)

    def _store(
        self,
        workspace_id: uuid.UUID,
        shop: str,
        token: str,
    ) -> EcommerceAccount:
        existing = self._accounts.get_by_shop_domain(shop)

        if existing is not None:
            if existing.workspace_id != workspace_id:
                # This shop is already somebody else's. Refused with the
                # same error a workspace gets for its own second shop,
                # because saying which would confirm that a given shop
                # uses this platform to anyone who guessed its domain.
                raise StorefrontAlreadyConnectedError(workspace_id)

            account = self._accounts.reconnect(
                existing,
                access_token_encrypted=encrypt(token),
            )
            self._session.commit()

            return account

        try:
            account = self._accounts.create(
                workspace_id=workspace_id,
                provider=self._provider.name,
                shop_domain=shop,
                access_token_encrypted=encrypt(token),
            )
            self._session.commit()
        except IntegrityError as exc:
            # One storefront per workspace, and one workspace per shop.
            # Two installations racing settle here.
            self._session.rollback()
            raise StorefrontAlreadyConnectedError(workspace_id) from exc

        return account

    # --- reading -----------------------------------------------------------

    def connected(self, access: WorkspaceAccess) -> EcommerceAccount:
        account = self._accounts.get_for_workspace(access.workspace.id)

        if account is None:
            raise StorefrontNotConnectedError(access.workspace.id)

        return account

    def sync_all(self, access: WorkspaceAccess) -> SyncReport:
        """Read the whole shop and write it into this workspace.

        The first sync, and the button somebody presses when they think
        something is missing. Idempotent, like every webhook: it is the
        same upsert, run over everything rather than over one record.
        """
        account = self._live(access.workspace.id)
        token = decrypt(account.access_token_encrypted)
        report = SyncReport()

        for product in self._provider.fetch_products(
            shop=account.shop_domain,
            access_token=token,
        ):
            self._sync.upsert_product(account.workspace_id, product, report)

        for order in self._provider.fetch_orders(
            shop=account.shop_domain,
            access_token=token,
        ):
            self._sync.upsert_order(account.workspace_id, order, report)

        self._accounts.mark_synced(account, datetime.now(UTC))
        self._session.commit()

        return report

    # --- letting go --------------------------------------------------------

    def disconnect(self, access: WorkspaceAccess) -> None:
        self._accounts.disconnect(self.connected(access))
        self._session.commit()

    def uninstalled(self, shop: str) -> None:
        """The shop owner removed the app, which arrives as a webhook.

        The same as disconnecting, and reached without any workspace
        having asked -- so it looks the account up by the only thing the
        delivery carries. Silent if there is nothing to disconnect: an
        uninstall webhook for a shop this application never had is
        somebody else's problem, and answering differently would say so.
        """
        account = self._accounts.get_by_shop_domain(shop)

        if account is None:
            return

        self._accounts.disconnect(account)
        self._session.commit()

    def _live(self, workspace_id: uuid.UUID) -> EcommerceAccount:
        account = self._accounts.get_for_workspace(workspace_id)

        if account is None or account.status != EcommerceAccountStatus.CONNECTED:
            raise StorefrontNotConnectedError(workspace_id)

        return account


def callback_url() -> str:
    base = get_settings().api_base_url

    if base is None:
        raise EcommerceProviderError("api_base_url is not configured")

    return f"{base.rstrip('/')}{CALLBACK_PATH}"


def _sign_state(workspace_id: uuid.UUID, shop: str) -> str:
    """The workspace and the shop, signed, for the round trip.

    A provider is configured with one redirect URI, so the callback
    cannot say which workspace it belongs to -- `state` has to. Signed
    rather than stored, because a nonce table would be a second thing to
    expire and sweep for a value that lives fifteen minutes.

    The shop is in there as well as the workspace, and that is the part
    that matters: without it, somebody who started an installation for
    their own workspace could complete it against a callback for a shop
    they do not own.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    return jwt.encode(
        {
            "workspace_id": str(workspace_id),
            "shop": shop,
            "iat": now,
            "exp": now + INSTALL_WINDOW,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _read_state(state: str) -> tuple[uuid.UUID, str]:
    settings = get_settings()

    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )

        return uuid.UUID(str(payload["workspace_id"])), str(payload["shop"])
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise EcommerceProviderError("The installation state did not verify") from exc


def get_ecommerce_account_repository(
    session: SessionDep,
) -> EcommerceAccountRepository:
    return EcommerceAccountRepository(session)


EcommerceAccountRepositoryDep = Annotated[
    EcommerceAccountRepository,
    Depends(get_ecommerce_account_repository),
]


def get_ecommerce_service(
    session: SessionDep,
    accounts: EcommerceAccountRepositoryDep,
    provider: EcommerceProviderDep,
    sync: EcommerceSyncServiceDep,
) -> EcommerceService:
    return EcommerceService(
        session=session,
        accounts=accounts,
        provider=provider,
        sync=sync,
    )


EcommerceServiceDep = Annotated[EcommerceService, Depends(get_ecommerce_service)]
