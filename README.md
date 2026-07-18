# bc-auction-explorer

Unofficial, read-only index of public BC Auction listings. It is not affiliated with
or endorsed by the Government of British Columbia.

The project includes a read-only API and a responsive web interface over persisted
listings and scrape status. It does not schedule scrapes, accept user accounts, or
modify the auction source.

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

`--limit` is always explicit. Start with a small run such as 20 or 100 listings,
review the resulting scrape status, then increase the limit deliberately for a
larger ingest. The scraper enumerates the source's product groups because its
"Browse All Open Auctions" view can omit listings. It makes sequential public
requests with a minimum request interval and respects source retry guidance; it
does not attempt to bypass source access controls.

Each detail listing currently requires several public source requests, so a run's
duration is governed by both source response time and the request interval. The
read-only scrape-status endpoint reports aggregate request, retry, rate-limit, and
timing metrics for each completed run. It never exposes request URLs, cookies, or
session identifiers.

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

## Local frontend

Use Python 3.12 or newer for the API and schema-generation commands:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

In a second terminal, start the API after applying migrations:

```bash
BC_AUCTION_DATABASE_URL=postgresql+psycopg://bc_auction:bc_auction@localhost:5432/bc_auction \
  uvicorn bc_auction.api:app --reload
```

Then install and run the frontend:

```bash
cd frontend
npm ci
npm run dev
```

Vite serves the frontend at `http://127.0.0.1:5173` and proxies `/api` requests to the
local API. Regenerate the checked-in API contract and TypeScript client after an API
contract change:

```bash
cd frontend
npm run generate:api-types
```

For production, serve `frontend/dist` as static files, proxy `/api` to the FastAPI
application, and route all remaining paths to the frontend entry point so direct links
to listing details continue to work.

Run the standard checks before merge:

```bash
pytest
ruff check .
mypy src
```

Frontend checks:

```bash
cd frontend
npm run check:api-types
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```
