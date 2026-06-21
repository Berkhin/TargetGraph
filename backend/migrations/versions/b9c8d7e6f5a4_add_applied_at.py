"""add_applied_at

Adds the ``applied_at`` timestamp column to ``job_postings``. Stamped when a
recruiter outreach email is sent successfully, so the card can show a
"Подано · date" marker. Nullable so existing rows and not-yet-applied postings
stay valid.

Revision ID: b9c8d7e6f5a4
Revises: 777c6c8d6179
Create Date: 2026-06-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c8d7e6f5a4'
down_revision: Union[str, Sequence[str], None] = '777c6c8d6179'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('job_postings', sa.Column('applied_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_postings', 'applied_at')
