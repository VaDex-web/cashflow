FROM node:22-alpine AS build
WORKDIR /src
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci --no-audit --no-fund
COPY web web
COPY docs/mock docs/mock
COPY core/reports/metrics.json core/reports/metrics.json
RUN cd web && VITE_USE_MOCK=false npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/web/dist /srv
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:2019/config/ || exit 1
