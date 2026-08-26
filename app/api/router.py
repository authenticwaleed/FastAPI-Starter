from fastapi import APIRouter

from app.api.routes import (
    account,
    auth,
    contacts,
    conversations,
    health,
    invitations,
    memberships,
    workspaces,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
# `/users` used to be included here: a public, unauthenticated CRUD surface
# over every account in the system. It is gone rather than protected,
# because what it was is administration, and administration needs a role
# before it needs a route. UserService still holds the logic, so the admin
# surface that eventually needs it has something to build on.
api_router.include_router(account.router)
api_router.include_router(workspaces.router)
api_router.include_router(memberships.router)
api_router.include_router(invitations.workspace_router)
api_router.include_router(invitations.token_router)
api_router.include_router(contacts.router)
api_router.include_router(conversations.router)
