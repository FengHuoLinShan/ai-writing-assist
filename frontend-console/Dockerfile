FROM node:24.22.0-alpine3.23@sha256:e44c87c7dd212720eb00469aeac89504ca2be77b8f0d6dbffb30665d5fcc59e1 AS build

WORKDIR /app

COPY frontend-console/package.json frontend-console/package-lock.json ./
RUN npm ci

COPY frontend-console/ ./
RUN npm run build

FROM nginx:1.31.7-alpine@sha256:892bb2152464f0c5d8972593a5f5afaf8054552580b699d95f8ff4af08c2d33d

COPY frontend-console/nginx.production.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
RUN set -eu; \
    apk add --upgrade --no-cache libcrypto3=3.5.8-r0 libexpat=2.9.0-r0 libssl3=3.5.8-r0 libuuid=2.42.3-r1 pcre2=10.49-r0 tiff=4.7.2-r0; \
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
