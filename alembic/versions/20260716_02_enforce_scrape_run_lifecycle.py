"""Enforce scrape-run completion status.

Revision ID: 20260716_02
Revises: 20260715_01
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_02"
down_revision: str | None = "20260715_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIFECYCLE_CONSTRAINT = (
    "(status = 'running' AND finished_at IS NULL) OR "
    "(status IN ('succeeded', 'partial', 'failed') AND finished_at IS NOT NULL)"
)


def upgrade() -> None:
    op.create_check_constraint(
        "ck_scrape_runs_status_finished_at",
        "scrape_runs",
        _LIFECYCLE_CONSTRAINT,
    )


def downgrade() -> None:
    op.drop_constraint("ck_scrape_runs_status_finished_at", "scrape_runs", type_="check")
