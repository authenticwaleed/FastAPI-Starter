"""What each plan admits, in one place.

The plan's instruction for this phase is the whole design: do not
hard-code plan checks around the codebase, create centralised capability
checks. So a plan is not a row that somebody can edit into a different
product -- it is code, here, and the subscription table only records which
of these a workspace is on.

Two kinds of thing, and they are enforced differently on purpose. A
*feature* is a yes or no, checked once at the door by a dependency in a
route's signature. A *limit* is a number, checked against what a workspace
already has, which means counting something -- and counting is a query, so
those live in the service.

Prices here are what a plan costs, for the page that lists them. What the
payment provider calls that price is configuration, because it is the
provider's identifier and not this product's fact.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

# Null in a limit means no ceiling. Spelled as a constant because
# `limits[X] is None` reads as "missing" at a glance and means the
# opposite.
UNLIMITED = None


class PlanTier(StrEnum):
    """The three the plan proposes, in the order they grow."""

    STARTER = "starter"
    GROWTH = "growth"
    BUSINESS = "business"


class Feature(StrEnum):
    """Something a plan either admits or does not.

    Checked at the door rather than counted. Every one of these is a
    capability a route can be gated on with one line in its signature,
    which is what stops a plan check from being an `if` somebody forgets
    to write in the route they add next month.
    """

    AUTOMATIONS = "automations"
    ECOMMERCE = "ecommerce"
    ADVANCED_ANALYTICS = "advanced_analytics"
    API_ACCESS = "api_access"
    AUDIT_LOGS = "audit_logs"


class PlanLimit(StrEnum):
    """Something a plan allows a number of.

    Enforced by counting what a workspace already has, which is why these
    are checked in the service and not in a signature: a route cannot be
    told "at most ten" without somebody running a query.
    """

    WHATSAPP_NUMBERS = "whatsapp_numbers"
    TEAM_MEMBERS = "team_members"
    AI_RESPONSES_PER_MONTH = "ai_responses_per_month"
    KNOWLEDGE_DOCUMENTS = "knowledge_documents"


@dataclass(frozen=True)
class Plan:
    tier: PlanTier
    name: str
    description: str
    price: Decimal
    currency: str
    features: frozenset[Feature]
    limits: dict[PlanLimit, int | None]

    def admits(self, feature: Feature) -> bool:
        return feature in self.features

    def ceiling(self, limit: PlanLimit) -> int | None:
        return self.limits.get(limit, UNLIMITED)

    @property
    def is_free(self) -> bool:
        return self.price == 0


PLANS: dict[PlanTier, Plan] = {
    PlanTier.STARTER: Plan(
        tier=PlanTier.STARTER,
        name="Starter",
        description="One number, a couple of people, and the assistant.",
        # Free, and that matters structurally rather than commercially:
        # it is what a workspace has before it has ever paid, and what it
        # falls back to when a payment stops working. A product whose
        # free tier does nothing would lock a business out of its own
        # inbox over a declined card.
        price=Decimal("0"),
        currency="USD",
        features=frozenset(),
        limits={
            PlanLimit.WHATSAPP_NUMBERS: 1,
            PlanLimit.TEAM_MEMBERS: 2,
            PlanLimit.AI_RESPONSES_PER_MONTH: 1_000,
            PlanLimit.KNOWLEDGE_DOCUMENTS: 50,
        },
    ),
    PlanTier.GROWTH: Plan(
        tier=PlanTier.GROWTH,
        name="Growth",
        description="A team, a storefront, and automations.",
        price=Decimal("49"),
        currency="USD",
        features=frozenset(
            {
                Feature.AUTOMATIONS,
                Feature.ECOMMERCE,
                Feature.ADVANCED_ANALYTICS,
            }
        ),
        limits={
            PlanLimit.WHATSAPP_NUMBERS: 3,
            PlanLimit.TEAM_MEMBERS: 10,
            PlanLimit.AI_RESPONSES_PER_MONTH: 10_000,
            PlanLimit.KNOWLEDGE_DOCUMENTS: 500,
        },
    ),
    PlanTier.BUSINESS: Plan(
        tier=PlanTier.BUSINESS,
        name="Business",
        description="High volume, several stores, and the API.",
        price=Decimal("199"),
        currency="USD",
        features=frozenset(Feature),
        limits={
            PlanLimit.WHATSAPP_NUMBERS: UNLIMITED,
            PlanLimit.TEAM_MEMBERS: UNLIMITED,
            PlanLimit.AI_RESPONSES_PER_MONTH: 100_000,
            PlanLimit.KNOWLEDGE_DOCUMENTS: UNLIMITED,
        },
    ),
}

# What a workspace is on before it has ever subscribed, and what it falls
# back to when a subscription stops being good. Named rather than written
# as PLANS[PlanTier.STARTER] in three places, so that changing which plan
# is the floor is one edit.
FREE_PLAN = PLANS[PlanTier.STARTER]
