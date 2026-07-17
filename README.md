# bc-auction-explorer

Unofficial, read-only index of public BC Auction listings. It is not affiliated with
or endorsed by the Government of British Columbia.

The current milestone adds a read-only API over persisted listings and scrape status.
Frontend and scheduling work come later.

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

## Local API

After applying migrations and storing at least one detail-complete scrape, start the
read-only API:

```bash
BC_AUCTION_DATABASE_URL=postgresql+psycopg://bc_auction:bc_auction@localhost:5432/bc_auction \
  uvicorn bc_auction.api:app --reload
```

Interactive documentation is available at `http://127.0.0.1:8000/docs`.

Initial endpoints:

- `GET /api/listings`
- `GET /api/listings/{source_id}`
- `GET /api/locations`
- `GET /api/categories`
- `GET /api/scrape-status`

Listings support keyword, location, category, status, bid, and closing-time filters;
bounded pagination; and deterministic sorting. API responses expose canonical public
listing and image URLs only, use UTC timestamps, and omit request/session data, source
HTML, persistence IDs, hashes, and scrape error details.

For deployment, give the API database role `SELECT`-only access. The application has no
write routes and its query layer issues only read statements.

Run the standard checks before merge:

```bash
pytest
ruff check .
mypy src
```
