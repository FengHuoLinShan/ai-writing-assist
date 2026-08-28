FROM node:24.19.0-alpine3.23@sha256:244cc2b53f46f9e876304391d17682b0ddae9ac33491f4857e25e35a36ba7995 AS build

WORKDIR /app

COPY frontend-console/package.json frontend-console/package-lock.json ./
RUN npm ci

COPY frontend-console/ ./
RUN npm run build

FROM nginx:1.31.4-alpine@sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913

COPY frontend-console/nginx.production.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
RUN set -eu; \
    apk add --upgrade --no-cache libcrypto3=3.5.8-r0 libssl3=3.5.8-r0; \
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
