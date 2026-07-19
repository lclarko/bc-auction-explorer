FROM postgres:17-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193
COPY postgres-entrypoint.sh /usr/local/bin/bc-auction-postgres-entrypoint
ENTRYPOINT ["/usr/local/bin/bc-auction-postgres-entrypoint"]
