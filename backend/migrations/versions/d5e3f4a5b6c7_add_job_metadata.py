"""add_job_metadata

Adds rich, optional metadata sourced from the
``curious_coder/linkedin-jobs-scraper`` actor: ``location``,
``employment_type``, ``seniority_level`` and ``salary``.

All columns are nullable so existing rows and sparse scraper results stay valid.

This migration was authored by hand (the same convention as the surrounding
revisions). The equivalent Alembic commands, once the dev DB is stamped at the
prior head, are:

    alembic revision --autogenerate -m "add_job_metadata"
    alembic upgrade head

Revision ID: d5e3f4a5b6c7
Revises: b3f1a2c4d5e6
Create Date: 2026-06-16 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'b3f1a2c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'job_postings',
        sa.Column('location', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'job_postings',
        sa.Column('employment_type', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'job_postings',
        sa.Column('seniority_level', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'job_postings',
        sa.Column('salary', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_postings', 'salary')
    op.drop_column('job_postings', 'seniority_level')
    op.drop_column('job_postings', 'employment_type')
    op.drop_column('job_postings', 'location')
