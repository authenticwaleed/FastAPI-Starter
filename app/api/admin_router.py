"""The platform surface, composed apart from the tenant one.

Its own module beside `app/api/router.py` rather than an include inside
it, and that separation is the whole point. Every path under `api_router`
is a customer's own data, reached through a membership; every path under
this one is the business that operates Baton, reached through a staff
row. An `include_router` added to the wrong file in a hurry would put an
admin path behind a tenant guard, and nothing in a diff would look wrong.

Two routers, one mount, in `app/main.py`.
"""

from fastapi import APIRouter, Depends

from app.api.dependencies.rate_limit import limit_by_staff
from app.api.routes.admin import (
    audit,
    conversations,
    staff,
    support_access,
    users,
    workspaces,
)
from app.core.rate_limit import RateLimited

# Counted here rather than route by route, which is the opposite of how
# the tenant surface does it and is right for this one. There, limiting
# is about the few endpoints that cost money -- a paid API call, an
# email, a file to embed -- so naming them individually is the decision.
# Here every route writes to the platform's audit log, reads included, so
# there is no unlimited route to leave out and a per-route declaration
# would only be a line to forget.
admin_router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(limit_by_staff(RateLimited.ADMIN))],
)

admin_router.include_router(staff.router)
# After the staff routes, whose prefix it does not share. Order carries
# no meaning between these two -- neither has a path parameter that could
# swallow the other's literal -- and it will the moment a route like
# `/admin/{something}` is proposed, which is a reason not to propose one.
admin_router.include_router(audit.router)
# The read-only console. Two subjects rather than one, because a support
# ticket arrives from either direction: sometimes it names a business,
# and sometimes it is somebody who cannot sign in and does not know which
# businesses they are in.
admin_router.include_router(workspaces.router)
admin_router.include_router(users.router)
# Support access, and the two reads it opens. Registered after the console
# although both hang off `/workspaces/{workspace_id}`: the paths are
# distinct literals, so order carries no meaning here either -- and it
# would the moment somebody proposed `…/workspaces/{workspace_id}/{thing}`,
# which is a reason not to.
admin_router.include_router(support_access.router)
admin_router.include_router(conversations.router)
