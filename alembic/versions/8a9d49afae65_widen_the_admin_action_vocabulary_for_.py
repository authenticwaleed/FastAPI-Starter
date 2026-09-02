"""widen the admin action vocabulary for the console

Revision ID: 8a9d49afae65
Revises: d8239847fa74
Create Date: 2026-09-02 13:05:41.882714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a9d49afae65'
down_revision: Union[str, Sequence[str], None] = 'd8239847fa74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# What the previous migration admitted: the door, and what it recorded.
DOOR = (
    'console.opened',
    'staff.listed',
    'staff.granted',
    'staff.role_changed',
    'staff.revoked',
    'audit.read',
)

# The read-only console, which is nine reads and no writes.
CONSOLE = (
    'workspaces.searched',
    'workspace.read',
    'workspace.members_read',
    'workspace.subscription_read',
    'workspace.usage_read',
    'workspace.integrations_read',
    'workspace.audit_read',
    'users.searched',
    'user.read',
)

ADMIN_ACTIONS = DOOR + CONSOLE


def upgrade() -> None:
    """Upgrade schema."""
    # A CHECK constraint dropped and recreated, rather than an ALTER TYPE.
    # That trade is the reason app/db/types.py stores these as text with a
    # constraint in the first place -- a vocabulary that is still settling
    # should be cheap to widen, and this is the phase that proves it.
    op.drop_constraint('admin_action', 'admin_audit_logs', type_='check')
    op.create_check_constraint(
        'admin_action',
        'admin_audit_logs',
        sa.column('action').in_(ADMIN_ACTIONS),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Narrowing the vocabulary would refuse rows that already exist, so
    # the console's entries go first. Losing them is a real loss -- they
    # are the record of who read which customer's account -- and it is
    # what reversing this migration means. Take a copy before running it.
    op.execute(
        "DELETE FROM admin_audit_logs WHERE action IN "
        f"({', '.join(repr(action) for action in CONSOLE)})"
    )
    op.drop_constraint('admin_action', 'admin_audit_logs', type_='check')
    op.create_check_constraint(
        'admin_action',
        'admin_audit_logs',
        sa.column('action').in_(DOOR),
    )
