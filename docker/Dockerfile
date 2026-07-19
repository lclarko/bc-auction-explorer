FROM python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c AS build
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/bc-auction-venv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.11.29 \
    && uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c AS runtime
ARG BC_AUCTION_VERSION=development
ARG BC_AUCTION_GIT_COMMIT=unknown
ARG BC_AUCTION_BUILD_TIMESTAMP=unknown
LABEL org.opencontainers.image.version=$BC_AUCTION_VERSION \
      org.opencontainers.image.revision=$BC_AUCTION_GIT_COMMIT \
      org.opencontainers.image.created=$BC_AUCTION_BUILD_TIMESTAMP
ENV PATH=/opt/bc-auction-venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BC_AUCTION_VERSION=$BC_AUCTION_VERSION \
    BC_AUCTION_GIT_COMMIT=$BC_AUCTION_GIT_COMMIT \
    BC_AUCTION_BUILD_TIMESTAMP=$BC_AUCTION_BUILD_TIMESTAMP
RUN groupadd --gid 10001 bcauction \
    && useradd --uid 10001 --gid bcauction --create-home --shell /usr/sbin/nologin bcauction
WORKDIR /app
COPY --from=build --chown=bcauction:bcauction /opt/bc-auction-venv /opt/bc-auction-venv
COPY docker/entrypoint.sh /usr/local/bin/bc-auction-entrypoint
ENTRYPOINT ["/usr/local/bin/bc-auction-entrypoint"]

FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "bc_auction.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM runtime AS operations
CMD ["python", "-m", "bc_auction.operations"]

FROM runtime AS migrate
COPY --chown=bcauction:bcauction alembic.ini ./
COPY --chown=bcauction:bcauction alembic ./alembic
CMD ["alembic", "upgrade", "head"]
