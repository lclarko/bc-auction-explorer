#!/bin/sh
set -eu

if [ "$#" -ne 2 ] || [ "$1" != "--replace" ]; then
    echo "usage: scripts/restore-db.sh --replace BACKUP_ARCHIVE" >&2
    exit 2
fi

archive=$2
if [ ! -f "$archive" ]; then
    echo '{"event":"restore_failed","reason":"archive_missing"}' >&2
    exit 2
fi

compose="docker compose -f compose.production.yaml"

if ! $compose exec -T postgres sh -ceu '
    PGPASSWORD="$(tr -d "\r\n" < /run/secrets/migration_password)"
    export PGPASSWORD
    pg_restore --username=bc_auction_migration --dbname="$POSTGRES_DB" --list >/dev/null
' < "$archive"; then
    echo '{"event":"restore_failed","reason":"archive_validation_failed"}' >&2
    exit 2
fi

$compose stop operations api

if ! $compose exec -T postgres sh -ceu '
    PGPASSWORD="$(tr -d "\r\n" < /run/secrets/migration_password)"
    export PGPASSWORD
    pg_restore --username=bc_auction_migration --dbname="$POSTGRES_DB" \
        --clean --if-exists --no-owner --no-privileges
' < "$archive"; then
    echo '{"event":"restore_failed","reason":"restore_failed"}' >&2
    exit 4
fi

if ! $compose run --rm migrate; then
    echo '{"event":"restore_failed","reason":"migration_failed"}' >&2
    exit 5
fi

$compose up -d api operations proxy
if ! $compose exec -T api python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/ready').read()"; then
    echo '{"event":"restore_failed","reason":"readiness_failed"}' >&2
    exit 5
fi

printf '{"event":"restore_succeeded","archive":"%s"}\n' "$(basename "$archive")"
