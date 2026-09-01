"""Declaring what a plan has to include, in a route's signature.

The plan's instruction for this phase is not to hard-code plan checks
around the codebase, and this is the half of that which routes touch: a
capability is named once, in the decorator, and the check happens before
any handler body runs.

The same argument `require_workspace_role` makes, for the same reason. An
`if` at the top of a handler is not hard to write; it is hard to notice
missing, and a route added next month without one looks exactly like a
route that is deliberately available on every plan.
"""

from collections.abc import Callable

from fastapi import Depends

from app.api.dependencies.workspace import WorkspaceAccessDep
from app.services.plans import Feature
from app.services.subscription_service import SubscriptionServiceDep


def require_feature(feature: Feature) -> Callable[..., None]:
    """Build a dependency that admits only plans including this.

    Depends on WorkspaceAccessDep, so membership is established first: a
    stranger guessing at a workspace id is told it does not exist rather
    than being told what its plan includes.
    """

    def dependency(
        access: WorkspaceAccessDep,
        subscriptions: SubscriptionServiceDep,
    ) -> None:
        subscriptions.require_feature(access.workspace.id, feature)

    return dependency


# Named once each rather than at every call site, so that the set of
# gated capabilities is a list somebody can read.
REQUIRES_AUTOMATIONS = Depends(require_feature(Feature.AUTOMATIONS))
REQUIRES_ECOMMERCE = Depends(require_feature(Feature.ECOMMERCE))
REQUIRES_ADVANCED_ANALYTICS = Depends(require_feature(Feature.ADVANCED_ANALYTICS))
REQUIRES_AUDIT_LOGS = Depends(require_feature(Feature.AUDIT_LOGS))
