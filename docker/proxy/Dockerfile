FROM caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
# Caddy listens only on unprivileged ports here, so its base-image capability is unnecessary.
RUN addgroup -S -g 10001 bcauction \
    && adduser -S -D -H -u 10001 -G bcauction bcauction \
    && mkdir -p /data /config \
    && chown -R bcauction:bcauction /data /config \
    && setcap -r /usr/bin/caddy
COPY --chown=bcauction:bcauction Caddyfile /etc/caddy/Caddyfile
USER bcauction
EXPOSE 8080 8443
