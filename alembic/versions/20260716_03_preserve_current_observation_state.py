"""Preserve the current observation state alongside history.

Revision ID: 20260716_03
Revises: 20260716_02
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260716_03"
down_revision: str | None = "20260716_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auction_items",
        sa.Column("current_observation_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM auction_items AS item
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM item_observations AS observation
                    WHERE observation.auction_item_id = item.id
                )
            ) THEN
                RAISE EXCEPTION
                    'cannot backfill current observation state without observation history';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM auction_items AS item
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM item_observations AS observation
                    WHERE observation.auction_item_id = item.id
                      AND observation.status = item.status
                )
            ) THEN
                RAISE EXCEPTION
                    'cannot backfill current observation state without matching status history';
            END IF;

            IF EXISTS (
                WITH ranked AS (
                    SELECT item.id AS auction_item_id,
                           observation.observation_hash,
                           rank() OVER (
                               PARTITION BY item.id
                               ORDER BY
                                   CASE WHEN observation.status = item.status THEN 0 ELSE 1 END,
                                   (observation.observed_at = item.last_seen_at) DESC,
                                   (observation.observed_at <= item.last_seen_at) DESC,
                                   observation.observed_at DESC,
                                   run.started_at DESC,
                                   run.created_at DESC,
                                   observation.created_at DESC
                           ) AS temporal_rank
                    FROM auction_items AS item
                    JOIN item_observations AS observation
                      ON observation.auction_item_id = item.id
                    JOIN scrape_runs AS run ON run.id = observation.scrape_run_id
                )
                SELECT 1
                FROM ranked
                WHERE temporal_rank = 1
                GROUP BY auction_item_id
                HAVING count(DISTINCT observation_hash) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot backfill ambiguous current observation history';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE auction_items AS item
        SET current_observation_hash = (
            SELECT observation.observation_hash
            FROM item_observations AS observation
            JOIN scrape_runs AS run ON run.id = observation.scrape_run_id
            WHERE observation.auction_item_id = item.id
            ORDER BY
                CASE WHEN observation.status = item.status THEN 0 ELSE 1 END,
                (observation.observed_at = item.last_seen_at) DESC,
                (observation.observed_at <= item.last_seen_at) DESC,
                observation.observed_at DESC,
                run.started_at DESC,
                run.created_at DESC,
                observation.created_at DESC,
                observation.observation_hash DESC
            LIMIT 1
        )
        """
    )
    op.alter_column("auction_items", "current_observation_hash", nullable=False)


def downgrade() -> None:
    op.drop_column("auction_items", "current_observation_hash")
