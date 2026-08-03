FROM node:24.18.0-alpine3.23@sha256:595398b0081eacda8e1c4c5b97b76cd1020e4d58a8ebcb4843b9bca1e79e7436 AS build

WORKDIR /app

COPY frontend-console/package.json frontend-console/package-lock.json ./
RUN npm ci

COPY frontend-console/ ./
RUN npm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46

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
