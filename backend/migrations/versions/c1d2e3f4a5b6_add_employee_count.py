"""add_employee_count

Adds a nullable ``Integer`` column ``employee_count`` to ``job_postings``,
holding the company headcount from the Apify ``companyEmployeesCount`` field
(populated only when the actor's ``scrapeCompany`` input is enabled).

Nullable — existing rows and items scraped without company enrichment stay valid.

Revision ID: c1d2e3f4a5b6
Revises: c0d9e8f7a6b5
Create Date: 2026-06-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'c0d9e8f7a6b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'job_postings',
        sa.Column('employee_count', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_postings', 'employee_count')
