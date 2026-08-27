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
from app.integrations.ecommerce.base import (
    EcommerceProvider,
    EcommerceProviderName,
    InstallCallback,
)
from app.integrations.ecommerce.shopify import ShopifyProvider
from app.integrations.ecommerce.woocommerce import WooCommerceProvider
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

# Where a provider sends the shop owner back to. Named per provider and
# app-wide within one, because a provider is configured with a single
# callback URL -- which is why the workspace has to travel in `state`.
CALLBACK_PATH = "/api/v1/integrations/{provider}/callback"

# And where the browser lands afterwards. Only WooCommerce uses it:
# Shopify's flow puts the grant on the redirect itself, so there is no
# second place to go.
RETURN_PATH = "/integrations/{provider}/connected"


@lru_cache
def get_ecommerce_providers() -> dict[EcommerceProviderName, EcommerceProvider]:
    """Every storefront this application can talk to, by name.

    A registry rather than one provider, because the route names which
    one it is for. A dependency rather than an import, so a test can
    substitute fakes by overriding it; cached because the adapters hold
    no state -- only a workspace's own credentials, which arrive per call.
    """
    return {
        EcommerceProviderName.SHOPIFY: ShopifyProvider(),
        EcommerceProviderName.WOOCOMMERCE: WooCommerceProvider(),
    }


EcommerceProvidersDep = Annotated[
    dict[EcommerceProviderName, EcommerceProvider],
    Depends(get_ecommerce_providers),
]


@dataclass(frozen=True)
class Started:
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
        providers: dict[EcommerceProviderName, EcommerceProvider],
        sync: EcommerceSyncService,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._providers = providers
        self._sync = sync

    def provider(self, name: EcommerceProviderName) -> EcommerceProvider:
        """The adapter for one storefront.

        A KeyError here would be a route naming something the registry
        does not hold, which the enum in the path makes impossible: an
        unknown provider is a 422 before any of this runs.
        """
        return self._providers[name]

    # --- installing --------------------------------------------------------

    def begin_install(
        self,
        access: WorkspaceAccess,
        name: EcommerceProviderName,
        shop: str,
    ) -> Started:
        """Where to send the shop owner to approve this.

        Refused if something is already connected here, so that
        connecting a second shop is a deliberate disconnect first rather
        than a silent replacement of the one the assistant has been
        answering from -- whichever provider either one is.
        """
        workspace_id = access.workspace.id
        provider = self.provider(name)
        domain = provider.normalise_shop(shop)
        existing = self._accounts.get_for_workspace(workspace_id)

        if existing is not None and existing.status == EcommerceAccountStatus.CONNECTED:
            raise StorefrontAlreadyConnectedError(workspace_id)

        return Started(
            authorize_url=provider.authorize_url(
                shop=domain,
                state=_sign_state(workspace_id, domain),
                callback_url=callback_url(name),
                return_url=return_url(name),
            ),
            shop_domain=domain,
        )

    def complete_install(
        self,
        name: EcommerceProviderName,
        callback: InstallCallback,
    ) -> EcommerceAccount:
        """Finish what begin_install started, on the provider's callback.

        The state is read first and by this service rather than by the
        adapter, because it is the one thing both flows have in common
        and the only thing either of them can be trusted on. Shopify's
        callback is signed and WooCommerce's is not signed at all, so for
        WooCommerce a valid state is the whole of the proof -- which is
        why it is checked here, once, rather than in two adapters.

        Where the provider does name a shop, it has to be the shop the
        installation was started for. Without that check, somebody who
        could get one shop owner to approve an installation could attach
        a different shop to their own workspace.
        """
        workspace_id, expected_shop = _read_state(callback.params.get("state", ""))
        installed = self.provider(name).complete_install(callback)

        if installed.shop is not None and installed.shop != expected_shop:
            raise EcommerceProviderError("The callback names a different shop")

        return self._store(name, workspace_id, expected_shop, installed.secret)

    def _store(
        self,
        name: EcommerceProviderName,
        workspace_id: uuid.UUID,
        shop: str,
        secret: str,
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
                credentials_encrypted=encrypt(secret),
            )
            self._session.commit()

            return account

        try:
            account = self._accounts.create(
                workspace_id=workspace_id,
                provider=name,
                shop_domain=shop,
                credentials_encrypted=encrypt(secret),
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
        # Whichever storefront this workspace connected, rather than the
        # one in the path: a workspace has one, and reading it is reading
        # that one.
        provider = self.provider(account.provider)
        secret = decrypt(account.credentials_encrypted)
        report = SyncReport()

        for product in provider.fetch_products(
            shop=account.shop_domain,
            secret=secret,
        ):
            self._sync.upsert_product(account.workspace_id, product, report)

        for order in provider.fetch_orders(
            shop=account.shop_domain,
            secret=secret,
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


def callback_url(name: EcommerceProviderName) -> str:
    return f"{_api_base()}{CALLBACK_PATH.format(provider=name.value)}"


def return_url(name: EcommerceProviderName) -> str:
    """Where the browser lands once the store has handed its keys over.

    The dashboard, not this API -- what the shop owner should see next is
    their own settings page saying it worked. Falls back to the API's own
    callback path where no frontend is configured, which is a laptop.
    """
    base = get_settings().frontend_base_url

    if base is None:
        return callback_url(name)

    return f"{base.rstrip('/')}{RETURN_PATH.format(provider=name.value)}"


def _api_base() -> str:
    base = get_settings().api_base_url

    if base is None:
        raise EcommerceProviderError("api_base_url is not configured")

    return base.rstrip("/")


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
    providers: EcommerceProvidersDep,
    sync: EcommerceSyncServiceDep,
) -> EcommerceService:
    return EcommerceService(
        session=session,
        accounts=accounts,
        providers=providers,
        sync=sync,
    )


EcommerceServiceDep = Annotated[EcommerceService, Depends(get_ecommerce_service)]
