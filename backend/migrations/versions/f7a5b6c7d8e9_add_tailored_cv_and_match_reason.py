"""add_tailored_cv_and_match_reason

Adds two nullable ``Text`` columns to ``job_postings``:

* ``tailored_cv_draft`` — ATS-optimised résumé produced by the new
  ``generate_tailored_cv`` LangGraph node (in parallel with the cover letter).
* ``match_reason`` — short justification for ``match_score``, written by the
  sourcing pre-screen and the matching pipeline.

Both nullable — populated only after the relevant node runs.

Revision ID: f7a5b6c7d8e9
Revises: e6f4a5b6c7d8
Create Date: 2026-06-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e6f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'job_postings',
        sa.Column('tailored_cv_draft', sa.Text(), nullable=True),
    )
    op.add_column(
        'job_postings',
        sa.Column('match_reason', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_postings', 'match_reason')
    op.drop_column('job_postings', 'tailored_cv_draft')
