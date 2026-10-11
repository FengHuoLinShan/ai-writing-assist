FROM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS build

WORKDIR /app

COPY frontend-console/package.json frontend-console/package-lock.json ./
RUN npm ci

COPY frontend-console/ ./
RUN npm run build

FROM nginx:1.31.6-alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2

COPY frontend-console/nginx.production.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
RUN set -eu; \
    apk add --upgrade --no-cache libcrypto3=3.5.8-r0 libexpat=2.8.5-r0 libssl3=3.5.8-r0 libuuid=2.42.3-r1 pcre2=10.49-r0 tiff=4.7.2-r0; \
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
