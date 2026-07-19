#!/bin/sh
set -eu

read_secret() {
    secret_name=$1
    secret_value=$(tr -d '\r\n' < "/run/secrets/$secret_name")
    if [ -z "$(printf '%s' "$secret_value" | tr -d '[:space:]')" ]; then
        echo "required secret $secret_name was blank" >&2
        exit 1
    fi
    printf '%s' "$secret_value"
}

PGPASSWORD="$(read_secret postgres_admin_password)"
BC_AUCTION_MIGRATION_PASSWORD="$(read_secret migration_password)"
BC_AUCTION_SCRAPER_PASSWORD="$(read_secret scraper_password)"
BC_AUCTION_API_PASSWORD="$(read_secret api_password)"
export PGPASSWORD BC_AUCTION_MIGRATION_PASSWORD BC_AUCTION_SCRAPER_PASSWORD BC_AUCTION_API_PASSWORD

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
    --set database_name="$POSTGRES_DB" \
    --set migration_password="$BC_AUCTION_MIGRATION_PASSWORD" \
    --set scraper_password="$BC_AUCTION_SCRAPER_PASSWORD" \
    --set api_password="$BC_AUCTION_API_PASSWORD" <<'SQL'
CREATE ROLE bc_auction_migration LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    PASSWORD :'migration_password';
CREATE ROLE bc_auction_scraper LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    PASSWORD :'scraper_password';
CREATE ROLE bc_auction_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    PASSWORD :'api_password';

GRANT CONNECT ON DATABASE :"database_name" TO bc_auction_migration, bc_auction_scraper, bc_auction_api;
ALTER SCHEMA public OWNER TO bc_auction_migration;
GRANT USAGE ON SCHEMA public TO bc_auction_scraper, bc_auction_api;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO bc_auction_scraper;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bc_auction_scraper;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bc_auction_api;

ALTER DEFAULT PRIVILEGES FOR ROLE bc_auction_migration IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO bc_auction_scraper;
ALTER DEFAULT PRIVILEGES FOR ROLE bc_auction_migration IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO bc_auction_scraper;
ALTER DEFAULT PRIVILEGES FOR ROLE bc_auction_migration IN SCHEMA public
    GRANT SELECT ON TABLES TO bc_auction_api;
SQL

unset PGPASSWORD BC_AUCTION_MIGRATION_PASSWORD BC_AUCTION_SCRAPER_PASSWORD BC_AUCTION_API_PASSWORD
