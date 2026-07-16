"""Make observation-history idempotency database-enforced.

Revision ID: 20260716_04
Revises: 20260716_03
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_04"
down_revision: str | None = "20260716_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OBSERVATION_UNIQUENESS = "uq_item_observations_item_observed_hash"


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM item_observations AS duplicate
        USING (
            SELECT observation.id,
                   row_number() OVER (
                       PARTITION BY
                           observation.auction_item_id,
                           observation.observed_at,
                           observation.observation_hash
                       ORDER BY
                           run.started_at ASC,
                           run.created_at ASC,
                           observation.created_at ASC,
                           observation.id ASC
                   ) AS duplicate_number
            FROM item_observations AS observation
            JOIN scrape_runs AS run ON run.id = observation.scrape_run_id
        ) AS ranked
        WHERE duplicate.id = ranked.id
          AND ranked.duplicate_number > 1
        """
    )
    op.create_unique_constraint(
        _OBSERVATION_UNIQUENESS,
        "item_observations",
        ["auction_item_id", "observed_at", "observation_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(_OBSERVATION_UNIQUENESS, "item_observations", type_="unique")
