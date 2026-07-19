#!/bin/sh
set -eu

runtime_secret_directory=/tmp/bc-auction-secrets
runtime_password_file="$runtime_secret_directory/database_password"

if [ "${BC_AUCTION_DATABASE_PASSWORD_FILE:-}" = "$runtime_password_file" ]; then
    if [ "$(id -u)" -eq 0 ]; then
        exec setpriv --reuid=bcauction --regid=bcauction --init-groups -- "$@"
    fi
    exec "$@"
fi

mkdir -p "$runtime_secret_directory"
chmod 700 "$runtime_secret_directory"
chown bcauction:bcauction "$runtime_secret_directory"

if [ -n "${BC_AUCTION_DATABASE_PASSWORD_FILE:-}" ]; then
    umask 077
    cat "$BC_AUCTION_DATABASE_PASSWORD_FILE" > "$runtime_password_file"
    chown bcauction:bcauction "$runtime_password_file"
    chmod 600 "$runtime_password_file"
    exec env BC_AUCTION_DATABASE_PASSWORD_FILE="$runtime_password_file" \
        setpriv --reuid=bcauction --regid=bcauction --init-groups -- "$@"
fi

exec setpriv --reuid=bcauction --regid=bcauction --init-groups -- "$@"
