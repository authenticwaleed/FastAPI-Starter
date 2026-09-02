"""make suspension real and widen the lifecycle vocabularies

Revision ID: d209996b5e5c
Revises: 0d9f60f4e1d9
Create Date: 2026-09-02 13:19:13.660909

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd209996b5e5c'
down_revision: Union[str, Sequence[str], None] = '0d9f60f4e1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUDIT_EVENTS = (
    'workspace.created',
    'workspace.updated',
    'workspace.closed',
    'member.invited',
    'member.joined',
    'member.role_changed',
    'member.removed',
    'whatsapp.connected',
    'whatsapp.disconnected',
    'knowledge.document_uploaded',
    'knowledge.document_deleted',
    'conversation.assigned',
    'conversation.closed',
    'conversation.ai_disabled',
    'subscription.changed',
    'api_key.created',
    'api_key.revoked',
    'support.access_granted',
    'support.access_ended',
    'workspace.suspended',
    'workspace.unsuspended',
    'workspace.restored',
)

ADMIN_ACTIONS = (
    'console.opened',
    'staff.listed',
    'staff.granted',
    'staff.role_changed',
    'staff.revoked',
    'audit.read',
    'workspaces.searched',
    'workspace.read',
    'workspace.members_read',
    'workspace.subscription_read',
    'workspace.usage_read',
    'workspace.integrations_read',
    'workspace.audit_read',
    'users.searched',
    'user.read',
    'support_access.granted',
    'support_access.revoked',
    'support_access.listed',
    'workspace.conversations_read',
    'workspace.messages_read',
    'workspace.suspended',
    'workspace.unsuspended',
    'workspace.cancelled',
    'workspace.restored',
    'workspace.erase_after_changed',
    'workspace.erased',
    'workspace.erase_refused',
    'user.deactivated',
    'user.activated',
    'user.sessions_revoked',
    'user.email_verified',
)

NEW_AUDIT_EVENTS = (
    'workspace.suspended',
    'workspace.unsuspended',
    'workspace.restored',
)
NEW_ADMIN_ACTIONS = (
    'workspace.suspended',
    'workspace.unsuspended',
    'workspace.cancelled',
    'workspace.restored',
    'workspace.erase_after_changed',
    'workspace.erased',
    'workspace.erase_refused',
    'user.deactivated',
    'user.activated',
    'user.sessions_revoked',
    'user.email_verified',
)


def upgrade() -> None:
    """Upgrade schema."""
    # No table and no column: `workspaces.status` has admitted
    # `suspended` since the tenant boundary was drawn, and what this
    # phase adds is the behaviour behind it -- reads permitted, writes
    # refused, inbound messages accepted and not auto-answered. All of
    # that is application code.
    #
    # What the database has to learn is the vocabulary: three events a
    # customer can now see in their own log, and eleven actions the
    # platform records.
    op.drop_constraint('audit_event', 'audit_logs', type_='check')
    op.create_check_constraint(
        'audit_event',
        'audit_logs',
        sa.column('event').in_(AUDIT_EVENTS),
    )

    op.drop_constraint('admin_action', 'admin_audit_logs', type_='check')
    op.create_check_constraint(
        'admin_action',
        'admin_audit_logs',
        sa.column('action').in_(ADMIN_ACTIONS),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Rows first, or a narrowed constraint refuses what already exists.
    # Note what this destroys: a customer's record that their account was
    # frozen, and the platform's record of every erasure it performed.
    # Take a copy before running it.
    #
    # Workspaces left in `suspended` are not moved. Reversing this leaves
    # them frozen in name only, which is exactly where this phase found
    # them -- and quietly reactivating an account somebody suspended on
    # purpose would be the worse of the two.
    _forget('audit_logs', 'event', NEW_AUDIT_EVENTS)
    op.drop_constraint('audit_event', 'audit_logs', type_='check')
    op.create_check_constraint(
        'audit_event',
        'audit_logs',
        sa.column('event').in_(_without(AUDIT_EVENTS, NEW_AUDIT_EVENTS)),
    )

    _forget('admin_audit_logs', 'action', NEW_ADMIN_ACTIONS)
    op.drop_constraint('admin_action', 'admin_audit_logs', type_='check')
    op.create_check_constraint(
        'admin_action',
        'admin_audit_logs',
        sa.column('action').in_(_without(ADMIN_ACTIONS, NEW_ADMIN_ACTIONS)),
    )


def _forget(table: str, column: str, values: Sequence[str]) -> None:
    listed = ", ".join(repr(value) for value in values)

    op.execute(f"DELETE FROM {table} WHERE {column} IN ({listed})")


def _without(vocabulary: Sequence[str], removed: Sequence[str]) -> list[str]:
    return [value for value in vocabulary if value not in removed]
