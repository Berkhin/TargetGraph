"""add_company_linkedin_url

Adds a nullable ``String(512)`` column ``company_linkedin_url`` to
``job_postings``, holding the company's LinkedIn page from the Apify
``companyLinkedinUrl`` field (populated only when the actor's ``scrapeCompany``
input is enabled). Surfaced as a direct link on the job card.

Nullable — existing rows and items scraped without company enrichment stay valid.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'job_postings',
        sa.Column('company_linkedin_url', sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job_postings', 'company_linkedin_url')
