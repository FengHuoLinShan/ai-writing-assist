FROM node:24.18.1-alpine3.23@sha256:c2cc26d8f991c2db236ad51a61efee843c482372d6d22570787309d511694110 AS build

WORKDIR /app

COPY frontend-console/package.json frontend-console/package-lock.json ./
RUN npm ci

COPY frontend-console/ ./
RUN npm run build

FROM nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752

COPY frontend-console/nginx.production.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
RUN set -eu; \
    for asset in asset-manifest.json asset-inventory.txt index.html; do \
      test -f "/usr/share/nginx/html/$asset"; \
      test ! -L "/usr/share/nginx/html/$asset"; \
      test -r "/usr/share/nginx/html/$asset"; \
    done; \
    chmod -R a+rX /usr/share/nginx/html; \
    chown nginx:nginx /run /var/cache/nginx; \
    nginx -t

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
