# bc-auction-explorer

Unofficial, read-only index of public BC Auction listings. It is not affiliated with
or endorsed by the Government of British Columbia.

The current milestone adds persistence and auction observation history. API, frontend,
and scheduling work come later.

## Local persistence

Start PostgreSQL with Docker Compose:

```bash
docker compose up -d postgres
```

Apply migrations and run an opt-in persisted scrape:

```bash
BC_AUCTION_DATABASE_URL=postgresql+psycopg://bc_auction:bc_auction@localhost:5432/bc_auction \
  alembic upgrade head
BC_AUCTION_DATABASE_URL=postgresql+psycopg://bc_auction:bc_auction@localhost:5432/bc_auction \
  python -m bc_auction scrape --limit 20 --persist
```

Run PostgreSQL integration tests with an isolated database URL:

```bash
BC_AUCTION_TEST_DATABASE_URL=postgresql+psycopg://bc_auction:bc_auction@localhost:5432/bc_auction_test \
  pytest -m integration
```

Run the standard checks before merge:

```bash
pytest
ruff check .
mypy src
```
