import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from bc_auction.database import create_postgres_engine
from bc_auction.persistence import AuctionRepository


@pytest.fixture
def repository() -> AuctionRepository:
    database_url = os.environ.get("BC_AUCTION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("BC_AUCTION_TEST_DATABASE_URL is not configured")
    if make_url(database_url).database != "bc_auction_test":
        pytest.fail(
            "BC_AUCTION_TEST_DATABASE_URL must target an isolated bc_auction_test database"
        )

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_postgres_engine(database_url)
    try:
        yield AuctionRepository(engine)
    finally:
        engine.dispose()
