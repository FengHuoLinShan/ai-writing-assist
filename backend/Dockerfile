FROM python:3.12-slim-bookworm

ARG UV_VERSION=0.11.7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=app:app backend/ ./
RUN uv sync --locked --no-dev --no-editable \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
