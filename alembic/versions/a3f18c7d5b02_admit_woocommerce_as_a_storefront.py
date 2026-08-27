"""admit woocommerce as a storefront

Revision ID: a3f18c7d5b02
Revises: f7c30a81be24
Create Date: 2026-08-27 20:34:19.771205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f18c7d5b02'
down_revision: Union[str, Sequence[str], None] = 'f7c30a81be24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROVIDERS = ('shopify', 'woocommerce')


def upgrade() -> None:
    """Upgrade schema.

    Two changes, both of them a second storefront arriving.

    The provider column is a CHECK constraint rather than a PostgreSQL
    ENUM, which is exactly so that widening the vocabulary is an ordinary
    drop and recreate -- see app/db/types.py, which chose that trade for
    this moment.

    The credentials column held one Shopify access token when it was
    written. It now holds whatever the storefront handed over: a token for
    Shopify, a consumer key and secret together for WooCommerce. Renamed
    rather than added and backfilled, because it is the same value in the
    same place under a name that is no longer a lie about half its rows.
    """
    op.alter_column(
        'ecommerce_accounts',
        'access_token_encrypted',
        new_column_name='credentials_encrypted',
    )
    op.drop_constraint('ecommerce_provider', 'ecommerce_accounts', type_='check')
    op.create_check_constraint(
        'ecommerce_provider',
        'ecommerce_accounts',
        sa.column('provider').in_(PROVIDERS),
    )


def downgrade() -> None:
    """Downgrade schema.

    Narrowing the vocabulary again would refuse rows that already exist,
    so any WooCommerce connection goes first. Its credentials are useless
    to a version of this application that cannot read them anyway.
    """
    op.execute("DELETE FROM ecommerce_accounts WHERE provider = 'woocommerce'")
    op.drop_constraint('ecommerce_provider', 'ecommerce_accounts', type_='check')
    op.create_check_constraint(
        'ecommerce_provider',
        'ecommerce_accounts',
        sa.column('provider').in_(('shopify',)),
    )
    op.alter_column(
        'ecommerce_accounts',
        'credentials_encrypted',
        new_column_name='access_token_encrypted',
    )
