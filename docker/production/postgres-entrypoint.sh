#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
    set -- postgres
fi

runtime_secret_directory=/var/lib/postgresql/runtime-secrets
mkdir -p "$runtime_secret_directory"
chmod 700 "$runtime_secret_directory"
chown postgres:postgres "$runtime_secret_directory"

for secret_name in postgres_admin_password migration_password scraper_password api_password; do
    runtime_secret="$runtime_secret_directory/$secret_name"
    cp "/run/secrets/$secret_name" "$runtime_secret"
    chown postgres:postgres "$runtime_secret"
    chmod 600 "$runtime_secret"
done

export BC_AUCTION_POSTGRES_SECRET_DIRECTORY="$runtime_secret_directory"
export POSTGRES_PASSWORD_FILE="$runtime_secret_directory/postgres_admin_password"
exec /usr/local/bin/docker-entrypoint.sh "$@"
