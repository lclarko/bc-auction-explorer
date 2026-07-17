"""Add aggregate source timing and retry metrics to scrape runs.

Revision ID: 20260717_05
Revises: 20260716_04
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_05"
down_revision: str | None = "20260716_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_METRIC_COLUMNS = (
    "source_requests",
    "source_responses",
    "source_retries",
    "rate_limit_responses",
    "source_transport_errors",
    "source_request_duration_ms",
    "source_request_wait_duration_ms",
    "source_retry_wait_duration_ms",
)


def upgrade() -> None:
    for column_name in _METRIC_COLUMNS:
        op.add_column(
            "scrape_runs",
            sa.Column(column_name, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for column_name in reversed(_METRIC_COLUMNS):
        op.drop_column("scrape_runs", column_name)
