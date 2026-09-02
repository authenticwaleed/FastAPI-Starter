from datetime import date

from pydantic import BaseModel

from app.models.subscription import SubscriptionStatus
from app.models.workspace import WorkspaceStatus
from app.services.plans import PlanTier


class PlatformCounts(BaseModel):
    """The totals, which are the least interesting numbers here.

    Included because they are the first thing anybody looks for, and
    beside `active` on the growth page so that nobody reads a headline
    workspace count as usage.
    """

    users: int
    workspaces: int
    conversations: int
    messages: int


class AdminOverview(BaseModel):
    """Where the platform stands right now.

    Statuses and plans as maps rather than lists of rows, so a console
    can render a fixed set of tiles without knowing which values happen
    to have anything in them today. A status with no workspaces is absent
    rather than zero, and a client should read a missing key as zero --
    which is the same thing and one fewer round trip than asking for the
    vocabulary separately.
    """

    counts: PlatformCounts
    workspaces_by_status: dict[WorkspaceStatus, int]
    workspaces_by_plan: dict[PlanTier, int]


class DailyPoint(BaseModel):
    """One day, and how many."""

    day: date
    count: int


class AdminGrowth(BaseModel):
    """Signups, closures, and how many businesses actually used the product.

    `active_workspaces` is the number that matters and the one a row
    count cannot give: it is counted from messages sent, so a platform
    with four hundred workspaces and nine that did anything this month
    knows something the headline would hide.
    """

    days: int
    signups: list[DailyPoint]
    closures: list[DailyPoint]
    active_workspaces: int


class AdminRevenue(BaseModel):
    """What the provider says is being paid for.

    Counts per plan rather than an amount. What a plan costs lives in
    `app/services/plans.py`, and multiplying belongs where the prices are
    -- a figure computed in SQL would need editing every time one
    changed, and would be wrong in between.

    `past_due` in `subscriptions_by_status` is the number to watch: those
    businesses still have their plan while the provider retries, and each
    is either about to pay or about to churn.
    """

    subscriptions_by_status: dict[SubscriptionStatus, int]
    paying_by_plan: dict[PlanTier, int]


class AdminAiSpend(BaseModel):
    """What the assistant cost across every tenant.

    In tokens, not money, and that is the honest shape: what a token
    costs is a contract with a model provider, changes without this
    application being redeployed, and differs per model. A dollar figure
    computed here would look authoritative and be wrong within a quarter.

    This is the number the plan says decides whether the pricing works,
    so `replies` sits beside it -- tokens per reply is the figure that
    moves when a prompt grows.
    """

    days: int
    replies: int
    input_tokens: int | None
    output_tokens: int | None
    average_latency_ms: float | None
    # Replies per model, which is what a migration between two looks like
    # from here -- including the one somebody changed in configuration
    # and forgot to mention.
    by_model: dict[str, int]
