#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

RELEASE_REF=${1:-}
if [ -z "$RELEASE_REF" ]; then
    echo "Usage: deploy/scripts/release.sh <full-commit-sha>" >&2
    exit 2
fi
case "$RELEASE_REF" in
    *[!0-9a-f]*)
        echo "Release ref must be a lowercase hexadecimal commit SHA." >&2
        exit 2
        ;;
esac
if [ "${#RELEASE_REF}" -ne 40 ]; then
    echo "Release ref must be the full 40-character commit SHA." >&2
    exit 2
fi

validate_environment

if ! git -C "$REPO_ROOT" diff-index --quiet HEAD --; then
    echo "Tracked working tree changes exist; refusing to release." >&2
    exit 1
fi

git -C "$REPO_ROOT" fetch --prune origin
TARGET_COMMIT=$(git -C "$REPO_ROOT" rev-parse "${RELEASE_REF}^{commit}")
if [ "$TARGET_COMMIT" != "$RELEASE_REF" ]; then
    echo "Resolved commit does not exactly match the requested SHA." >&2
    exit 1
fi
if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$TARGET_COMMIT" origin/main; then
    echo "Requested release is not reachable from origin/main." >&2
    exit 1
fi

PREVIOUS_COMMIT=$(git -C "$REPO_ROOT" rev-parse HEAD)
git -C "$REPO_ROOT" checkout --detach "$TARGET_COMMIT"

RELEASE_ID=$(printf '%s' "$TARGET_COMMIT" | cut -c1-12)
export RELEASE_ID

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Target commit does not contain production deployment assets." >&2
    exit 1
fi

validate_environment
compose build api frontend
compose up -d postgres embedding

if [ ! -f "$STATE_DIR/current-release" ] \
    && [ "$(env_value DATABASE_MODE)" = "fresh" ]; then
    POSTGRES_USER=$(env_value POSTGRES_USER)
    POSTGRES_DB=$(env_value POSTGRES_DB)
    TABLE_COUNT=$(compose exec -T postgres psql \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        -Atqc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    if [ "$TABLE_COUNT" != "0" ]; then
        echo "DATABASE_MODE=fresh but the first-release database is not empty." >&2
        exit 1
    fi
fi

if ! compose run --rm api python scripts/check_embedding.py; then
    echo "Local embedding startup or 768-dimensional contract check failed." >&2
    exit 1
fi

BACKUP_PATH=$(bash "$SCRIPT_DIR/backup.sh")

if ! compose --profile ops run --rm migrate; then
    echo "Migration failed. Database backup: $BACKUP_PATH" >&2
    exit 1
fi

ensure_public_bootstrap
compose up -d api worker frontend

attempt=0
until compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" \
    >/dev/null 2>&1 \
    && compose exec -T frontend wget -q -O /dev/null \
        http://127.0.0.1:8080/healthz; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 40 ]; then
        compose stop api worker frontend >/dev/null 2>&1 || true
        echo "Release health check failed; application services were stopped." >&2
        echo "Previous commit: $PREVIOUS_COMMIT" >&2
        echo "Pre-migration backup: $BACKUP_PATH" >&2
        exit 1
    fi
    sleep 3
done

mkdir -p "$STATE_DIR"
printf '%s\n' "$PREVIOUS_COMMIT" >"$STATE_DIR/previous-release"
printf '%s\n' "$TARGET_COMMIT" >"$STATE_DIR/current-commit"
printf '%s\n' "$RELEASE_ID" >"$STATE_DIR/current-release"
printf '%s\n' "$BACKUP_PATH" >"$STATE_DIR/current-backup"

echo "Release healthy: $TARGET_COMMIT"
echo "Database backup: $BACKUP_PATH"
