from fastapi import APIRouter

from app.api.routes import (
    account,
    ai,
    analytics,
    auth,
    automations,
    contacts,
    conversations,
    ecommerce,
    health,
    invitations,
    knowledge,
    memberships,
    notifications,
    orders,
    products,
    webhooks,
    whatsapp,
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
# Beside /account rather than under a workspace, for the same reason: a
# notification is addressed to a person, and a person has one feed.
api_router.include_router(notifications.router)
api_router.include_router(workspaces.router)
api_router.include_router(memberships.router)
api_router.include_router(invitations.workspace_router)
api_router.include_router(invitations.token_router)
api_router.include_router(contacts.router)
api_router.include_router(conversations.router)
# After conversations, whose prefix it extends. Its own module because the
# assistant is a different concern from the inbox, and one that is meant to
# be switchable off entirely.
api_router.include_router(ai.router)
api_router.include_router(knowledge.router)
api_router.include_router(products.router)
api_router.include_router(orders.router)
api_router.include_router(automations.router)
api_router.include_router(analytics.router)
# Before the storefront routes, and this order is load-bearing. Both hang
# off `/integrations/`, and the storefront ones take the provider as a
# path parameter -- so `…/integrations/whatsapp` would match
# `…/integrations/{provider}` and be refused as an unknown storefront.
# Starlette matches in registration order, so a literal registered first
# wins. Two tests pin this, one per pair, because a re-order here is a
# silent 422 on a route nobody was thinking about.
api_router.include_router(whatsapp.router)
api_router.include_router(ecommerce.router)
api_router.include_router(ecommerce.callback_router)
# Same rule again: the WhatsApp webhook is a literal path and the
# storefront one is `/webhooks/{provider}`, both inside this router.
api_router.include_router(webhooks.router)
