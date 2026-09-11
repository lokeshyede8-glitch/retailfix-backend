"""add_manufacturing_progress_fields

Revision ID: e7980129dd92
Revises: f868e8f93030
Create Date: 2026-09-09 01:11:39.558109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7980129dd92'
down_revision: Union[str, Sequence[str], None] = 'f868e8f93030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('production_material_requirements', sa.Column('prepared_qty', sa.Float(), server_default='0.0', nullable=False))
    op.add_column('production_material_requirements', sa.Column('manufacturing_status', sa.String(), server_default='Pending', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('production_material_requirements', 'manufacturing_status')
    op.drop_column('production_material_requirements', 'prepared_qty')
