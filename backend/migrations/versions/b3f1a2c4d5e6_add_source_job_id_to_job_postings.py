"""add source_job_id to job_postings

Adds a stable, opaque provider id (SerpAPI google_jobs ``job_id``) used to
deduplicate sourced postings. Nullable so existing/manually-created rows remain
valid; a unique index backs both dedup lookups and the cross-run uniqueness
guarantee.

Revision ID: b3f1a2c4d5e6
Revises: 2682ca1c3796
Create Date: 2026-06-15 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3f1a2c4d5e6'
down_revision: Union[str, Sequence[str], None] = '2682ca1c3796'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'job_postings',
        sa.Column('source_job_id', sa.String(length=512), nullable=True),
    )
    op.create_index(
        op.f('ix_job_postings_source_job_id'),
        'job_postings',
        ['source_job_id'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_job_postings_source_job_id'), table_name='job_postings'
    )
    op.drop_column('job_postings', 'source_job_id')
