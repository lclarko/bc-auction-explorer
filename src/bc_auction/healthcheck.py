"""Container-local health checks for operational services."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime

from bc_auction.database import create_postgres_engine, resolve_database_url
from bc_auction.read_repository import AuctionReadRepository
from bc_auction.runtime import OperationsSettings, RuntimeMetadata


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bc_auction.healthcheck")
    parser.add_argument("service", choices=("operations",))
    args = parser.parse_args(argv)
    if args.service != "operations":
        raise AssertionError("unsupported healthcheck service")
    engine = create_postgres_engine(resolve_database_url())
    try:
        status = AuctionReadRepository(engine).operations_status(
            request_time=datetime.now(UTC),
            started_at=datetime.now(UTC),
            metadata=RuntimeMetadata.from_environment(),
            settings=OperationsSettings.from_environment(),
        )
    finally:
        engine.dispose()
    return 1 if status.state.value in {"stale", "stalled"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
