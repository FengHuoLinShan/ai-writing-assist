FROM python:3.15.0b3-slim-bookworm@sha256:e4408792d58d928261ed76a21a28daaf3339111e0f8cefb8f8c70b139ad94c39 AS build

ARG UV_VERSION=0.11.28

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --locked --no-dev --no-editable

# Runtime deliberately starts from the pinned Python image so uv and build tools
# never cross the production boundary.
FROM python:3.15.0b3-slim-bookworm@sha256:e4408792d58d928261ed76a21a28daaf3339111e0f8cefb8f8c70b139ad94c39 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY --from=build --chown=app:app /app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
