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
interactive CLI shows phase progress and an ETA on stderr while structured JSON
remains on stdout for redirection or processing. The
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

The browser defaults to the Active auctions view. The Ended auctions view shows source-confirmed
closed or withdrawn listings, along with open listings whose scheduled closing time has
passed. All auctions includes every indexed listing. The API exposes the same lifecycle
views through `view=active`, `view=ended`, and `view=all`, alongside keyword, location,
category, bid, and closing-time filters; bounded pagination; and deterministic sorting.
Location and category facets are scoped to the selected view.
Source-open listings without a closing time remain in Active and show the closing time
as unavailable.

A scheduled closing time passing never overwrites the source status. An open listing
whose scheduled closing time has passed is clearly marked as last observed open, not
closed, until the source confirms a terminal status. API responses expose canonical
public listing and image URLs only, use UTC timestamps, and omit request/session data,
source HTML, persistence IDs, hashes, and scrape error details.

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

## Production runtime

The default production stack is provider-neutral Docker Compose. It builds images locally,
uses Caddy as its replaceable edge proxy, keeps PostgreSQL on an internal network, and
binds the proxy to loopback by default. Public ingress, tunnels, and host firewall policy
belong to the deployment environment.

Copy the example configuration and create four password files outside the repository. Each
file must contain one password and be readable only by the deployment account:

```bash
cp .env.example .env
mkdir -p /etc/bc-auction-explorer/secrets
chmod 700 /etc/bc-auction-explorer/secrets
```

Set the four `*_PASSWORD_FILE` paths in `.env`, create the referenced files with mode
`0600`, then start the stack:

```bash
docker compose --env-file .env -f compose.production.yaml up -d --build
docker compose --env-file .env -f compose.production.yaml ps
```

Only the proxy publishes ports. `/health/live` reports process liveness and `/health/ready`
reports API database readiness. `/health/operations` is intentionally internal to the
Compose network and reports the scheduler-derived freshness state without exposing it
through the default proxy. The public `/api/scrape-status` remains session-free and omits
persistence identifiers.

The operations service scrapes at 06:00, 12:00, and 18:00 in the configured timezone. It
uses a PostgreSQL advisory lock, so a second scheduler cannot overlap a running scrape. It
starts one scrape only when no successful complete scrape is already present. A complete
scrape requires full source enumeration, so the production limit defaults to 1000.

To upgrade, pull the desired Git revision, review `.env`, rebuild, and let the one-shot
migration service finish before the API and operations service start:

```bash
docker compose --env-file .env -f compose.production.yaml up -d --build
```

### Backup and restore

Back up PostgreSQL to an operator-supplied host directory:

```bash
scripts/backup-db.sh /srv/bc-auction-backups
```

The command creates a validated custom-format `pg_dump` archive. To restore an archive,
use the explicit destructive flag. The script stops writers, validates the archive, restores
with the migration role, upgrades to the current migration head, verifies readiness, and
restarts application services:

```bash
scripts/restore-db.sh --replace /srv/bc-auction-backups/bc-auction-20260719T120000Z.dump
```

Keep `.env`, the external secret files, and any host-specific ingress configuration backed
up separately. Backup schedules, remote storage, retention, encryption, alerts, and
hardware-recovery procedures are deployment-specific follow-up work.

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
