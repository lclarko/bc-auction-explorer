#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: scripts/backup-db.sh BACKUP_DIRECTORY" >&2
    exit 2
fi

backup_directory=$1
if [ ! -d "$backup_directory" ]; then
    echo '{"event":"backup_failed","reason":"backup_directory_missing"}' >&2
    exit 2
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
archive="$backup_directory/bc-auction-$timestamp.dump"
temporary_archive="$archive.tmp"
compose="docker compose -f compose.production.yaml"

if ! $compose exec -T postgres sh -ceu '
    PGPASSWORD="$(tr -d "\r\n" < /run/secrets/migration_password)"
    export PGPASSWORD
    pg_dump --username=bc_auction_migration --dbname="$POSTGRES_DB" --format=custom
' > "$temporary_archive"; then
    rm -f "$temporary_archive"
    echo '{"event":"backup_failed","reason":"dump_failed"}' >&2
    exit 4
fi

if ! $compose exec -T postgres sh -ceu '
    PGPASSWORD="$(tr -d "\r\n" < /run/secrets/migration_password)"
    export PGPASSWORD
    pg_restore --username=bc_auction_migration --dbname="$POSTGRES_DB" --list >/dev/null
' < "$temporary_archive"; then
    rm -f "$temporary_archive"
    echo '{"event":"backup_failed","reason":"archive_validation_failed"}' >&2
    exit 5
fi

mv "$temporary_archive" "$archive"
printf '{"event":"backup_succeeded","archive":"%s"}\n' "$(basename "$archive")"
