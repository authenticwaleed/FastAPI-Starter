"""admit the analytics read

Revision ID: 3b28a09199d9
Revises: 8edd5fd4705d
Create Date: 2026-09-02 13:45:34.850707

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b28a09199d9'
down_revision: Union[str, Sequence[str], None] = '8edd5fd4705d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
    'billing.subscriptions_searched',
    'billing.plan_override_granted',
    'billing.plan_override_removed',
    'billing.events_read',
    'billing.event_replayed',
    'ops.jobs_searched',
    'ops.job_read',
    'ops.job_retried',
    'ops.job_cancelled',
    'ops.webhook_failures_read',
    'ops.whatsapp_health_read',
    'ops.health_read',
    'analytics.read',
)

NEW_ADMIN_ACTIONS = ('analytics.read',)


def upgrade() -> None:
    """Upgrade schema."""
    # One word. The analytics pages reveal nothing about any one
    # customer, and their reads are recorded anyway -- the rule is about
    # the surface rather than about each route.
    op.drop_constraint('admin_action', 'admin_audit_logs', type_='check')
    op.create_check_constraint(
        'admin_action',
        'admin_audit_logs',
        sa.column('action').in_(ADMIN_ACTIONS),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM admin_audit_logs WHERE action = 'analytics.read'")
    op.drop_constraint('admin_action', 'admin_audit_logs', type_='check')
    op.create_check_constraint(
        'admin_action',
        'admin_audit_logs',
        sa.column('action').in_(
            [a for a in ADMIN_ACTIONS if a not in NEW_ADMIN_ACTIONS]
        ),
    )
