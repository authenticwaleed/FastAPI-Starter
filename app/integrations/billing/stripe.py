"""Talking to Stripe, and the only place that knows what it says.

Raw HTTP rather than the SDK, for the reason the Shopify adapter is raw
HTTP: three calls and one signature check do not need a dependency, and
what a dependency would hide here is exactly the part worth reading --
which fields are copied, and what is done when one is missing.

Everything Stripe-shaped stops in this module. Its price identifiers, its
`t=...,v1=...` signature, its status vocabulary, its habit of expressing
every timestamp as a Unix integer and every amount in the smallest
currency unit.
"""

import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import BillingProviderError
from app.integrations.billing.base import (
    BillingEventKind,
    BillingEventPayload,
    Checkout,
    RemoteSubscription,
)
from app.models.subscription import BillingProviderName, SubscriptionStatus
from app.services.plans import PlanTier

logger = logging.getLogger(__name__)

API = "https://api.stripe.com/v1"

# How long a signature stays acceptable. Stripe signs the timestamp along
# with the body precisely so that a delivery captured today cannot be
# replayed next week, and the window is what makes that true.
TOLERANCE_SECONDS = 300

# Stripe's statuses, in this application's words. `incomplete_expired` and
# `paused` both mean the plan does not apply, which is what `unpaid` means
# here -- reducing them is the adapter's job, and inventing a fourth
# meaning for them would be inventing a state nothing handles.
_STATUSES = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.TRIALING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.UNPAID,
    "paused": SubscriptionStatus.UNPAID,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete": SubscriptionStatus.INCOMPLETE,
    "incomplete_expired": SubscriptionStatus.CANCELED,
}

# Stripe's events, mapped to what this application does about them.
_EVENTS = {
    "checkout.session.completed": BillingEventKind.SUBSCRIPTION_UPDATED,
    "customer.subscription.created": BillingEventKind.SUBSCRIPTION_UPDATED,
    "customer.subscription.updated": BillingEventKind.SUBSCRIPTION_UPDATED,
    "customer.subscription.deleted": BillingEventKind.SUBSCRIPTION_ENDED,
    "invoice.payment_failed": BillingEventKind.PAYMENT_FAILED,
}


class StripeProvider:
    """Stripe's REST API, behind `BillingProvider`."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    @property
    def name(self) -> BillingProviderName:
        return BillingProviderName.STRIPE

    # --- selling -----------------------------------------------------------

    def start_checkout(
        self,
        *,
        plan: PlanTier,
        workspace_id: str,
        customer_id: str | None,
        success_url: str,
        cancel_url: str,
    ) -> Checkout:
        """A hosted checkout session, which is a URL to send somebody to.

        The workspace travels in `client_reference_id` and in the
        subscription's own metadata. The first is what the completion
        event carries; the second is what every later event carries, and
        without it a subscription changing next month would arrive with
        no way of saying whose it is.
        """
        form: dict[str, str] = {
            "mode": "subscription",
            "line_items[0][price]": _price_for(plan),
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": workspace_id,
            "metadata[workspace_id]": workspace_id,
            "subscription_data[metadata][workspace_id]": workspace_id,
            "subscription_data[metadata][plan]": plan.value,
        }

        if customer_id:
            # A business that cancelled and came back is the same
            # customer, with the same billing history and the same card
            # on file.
            form["customer"] = customer_id

        session = self._post("checkout/sessions", form)
        url = session.get("url")

        if not isinstance(url, str) or not url:
            raise BillingProviderError("Stripe returned no checkout URL")

        return Checkout(url=url, provider_customer_id=_text(session.get("customer")))

    def cancel(self, *, provider_subscription_id: str) -> RemoteSubscription:
        updated = self._subscription(
            self._post(
                f"subscriptions/{provider_subscription_id}",
                {"cancel_at_period_end": "true"},
            )
        )

        if updated is None:
            # Stripe answered without an id for the subscription it was
            # just asked to change, which is not something it does.
            raise BillingProviderError("Stripe returned an unrecognisable subscription")

        return updated

    # --- listening ---------------------------------------------------------

    def verify_webhook(self, *, payload: bytes, signature: str | None) -> bool:
        """Check the header Stripe signs its deliveries with.

        `t=<unix>,v1=<hex>`, where the digest covers `"{t}.{body}"` -- so
        the timestamp is inside what is signed, and a stale one is
        refused rather than trusted. Both halves matter: without the
        digest anybody can forge, and without the window anybody who ever
        saw a genuine delivery can replay it.
        """
        if not signature:
            return False

        parts = dict(
            piece.split("=", 1) for piece in signature.split(",") if "=" in piece
        )
        timestamp = parts.get("t")
        given = parts.get("v1")

        if not timestamp or not given:
            return False

        try:
            age = time.time() - int(timestamp)
        except ValueError:
            return False

        if abs(age) > TOLERANCE_SECONDS:
            logger.warning("A Stripe delivery was signed %.0f seconds ago", age)

            return False

        expected = hmac.new(
            _webhook_secret().encode(),
            f"{timestamp}.".encode() + payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, given)

    def parse_webhook(self, payload: dict[str, Any]) -> BillingEventPayload:
        event_type = str(payload.get("type", ""))
        kind = _EVENTS.get(event_type)
        body = (payload.get("data") or {}).get("object") or {}

        return BillingEventPayload(
            event_id=_text(payload.get("id")) or "",
            event_type=event_type,
            kind=kind,
            subscription=self._from_event(event_type, body) if kind else None,
        )

    # --- translation -------------------------------------------------------

    def _from_event(
        self,
        event_type: str,
        body: dict[str, Any],
    ) -> RemoteSubscription | None:
        """The subscription an event is about, whatever shape it came in.

        Three shapes, because Stripe sends three. A completed checkout is
        a session that names a subscription; a subscription event is the
        subscription itself; a failed invoice is an invoice that names
        one. Reduced here so that nothing downstream has to know which.
        """
        if event_type == "checkout.session.completed":
            subscription_id = _text(body.get("subscription"))

            if subscription_id is None:
                return None

            # A completed checkout says almost nothing about the
            # subscription beyond that it exists, so it is fetched rather
            # than guessed at. The `customer.subscription.created` event
            # says the same thing, and either may arrive first.
            return self._subscription(self._get(f"subscriptions/{subscription_id}"))

        if event_type == "invoice.payment_failed":
            subscription_id = _text(body.get("subscription"))

            if subscription_id is None:
                return None

            return RemoteSubscription(
                provider_subscription_id=subscription_id,
                provider_customer_id=_text(body.get("customer")),
                status=SubscriptionStatus.PAST_DUE,
            )

        return self._subscription(body)

    def _subscription(self, body: dict[str, Any]) -> RemoteSubscription | None:
        subscription_id = _text(body.get("id"))

        if subscription_id is None:
            return None

        metadata = body.get("metadata") or {}

        return RemoteSubscription(
            provider_subscription_id=subscription_id,
            provider_customer_id=_text(body.get("customer")),
            # The plan the checkout was started for, carried on the
            # subscription's own metadata. Read from there rather than
            # from the price, because a price identifier is a deployment's
            # configuration and this has to work when it changes.
            plan=_plan(metadata.get("plan")),
            status=_STATUSES.get(
                str(body.get("status", "")),
                SubscriptionStatus.INCOMPLETE,
            ),
            current_period_start=_timestamp(body.get("current_period_start")),
            current_period_end=_timestamp(body.get("current_period_end")),
            cancel_at_period_end=bool(body.get("cancel_at_period_end")),
        )

    # --- transport ---------------------------------------------------------

    def _post(self, path: str, form: dict[str, str]) -> dict[str, Any]:
        return self._call("POST", path, data=form)

    def _get(self, path: str) -> dict[str, Any]:
        return self._call("GET", path)

    def _call(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{API}/{path}",
                data=data,
                # Stripe's own scheme: the secret key as a bearer token.
                headers={"Authorization": f"Bearer {_api_key()}"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            # Whatever Stripe said goes to the log. What the caller gets
            # is that it did not work, because a card decline message and
            # an API error read identically to somebody who is not us.
            logger.warning("Stripe refused %s %s: %s", method, path, exc)
            raise BillingProviderError(f"Stripe refused the request: {exc}") from exc

        if not isinstance(body, dict):
            raise BillingProviderError("Stripe returned something unexpected")

        return body


def _api_key() -> str:
    key = get_settings().stripe_api_key

    if key is None:
        raise BillingProviderError("stripe_api_key is not configured")

    return key.get_secret_value()


def _webhook_secret() -> str:
    secret = get_settings().stripe_webhook_secret

    if secret is None:
        raise BillingProviderError("stripe_webhook_secret is not configured")

    return secret.get_secret_value()


def _price_for(plan: PlanTier) -> str:
    """What Stripe calls this plan's price.

    Configuration rather than a fact about the product: the same plan has
    a different price id in test mode and in live mode, and hard-coding
    one would make the two deployments different code.
    """
    settings = get_settings()
    prices = {
        PlanTier.GROWTH: settings.stripe_price_growth,
        PlanTier.BUSINESS: settings.stripe_price_business,
    }
    price = prices.get(plan)

    if price is None:
        raise BillingProviderError(f"No Stripe price is configured for {plan.value}")

    return price


def _plan(value: Any) -> PlanTier | None:
    try:
        return PlanTier(str(value))
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None

    # An expanded object where an id was expected, which Stripe does when
    # asked to. The id is the part this application uses either way.
    if isinstance(value, dict):
        value = value.get("id")

    written = str(value).strip() if value is not None else ""

    return written or None


def _timestamp(value: Any) -> datetime | None:
    """Stripe counts in seconds since the epoch, and says so nowhere."""
    if value is None:
        return None

    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None
