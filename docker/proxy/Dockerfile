FROM caddy:2.10.2-alpine
RUN addgroup -S -g 10001 bcauction \
    && adduser -S -D -H -u 10001 -G bcauction bcauction \
    && mkdir -p /data /config \
    && chown -R bcauction:bcauction /data /config
COPY --chown=bcauction:bcauction Caddyfile /etc/caddy/Caddyfile
USER bcauction
EXPOSE 8080 8443
