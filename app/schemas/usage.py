from datetime import datetime

from pydantic import BaseModel

from app.models.usage_record import UsageMetric


class MetricUsage(BaseModel):
    """One metric, what it came to, and what the plan allows of it."""

    metric: UsageMetric
    quantity: int
    # Null where nothing refuses this. A plan with no ceiling on a metric
    # and a metric no plan limits read the same to whoever is looking at
    # the page, and mean the same thing: carry on.
    limit: int | None


class UsageSummary(BaseModel):
    """What a workspace has used, and over what period.

    The period is in the response rather than assumed by the client,
    because it is not always the month: a subscribed workspace is metered
    over the dates the payment provider is billing it for, and a page
    saying "this month" over those figures would be saying the wrong
    thing for most of the month.
    """

    period_start: datetime
    period_end: datetime
    metrics: list[MetricUsage]
