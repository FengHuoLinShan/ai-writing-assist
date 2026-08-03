#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

BACKUP_INPUT=${1:-}
TARGET_REF=${2:-}
if [ -z "$BACKUP_INPUT" ] || [ -z "$TARGET_REF" ]; then
    echo "Usage: deploy/scripts/restore.sh <backup.dump> <full-commit-sha>" >&2
    exit 2
fi

validate_environment

BACKUP_PATH=$(realpath "$BACKUP_INPUT")
RESOLVED_BACKUP_DIR=$(realpath "$BACKUP_DIR")
case "$BACKUP_PATH" in
    "$RESOLVED_BACKUP_DIR"/*.dump) ;;
    *)
        echo "Backup must be a .dump file inside $BACKUP_DIR" >&2
        exit 1
        ;;
esac
if [ ! -s "$BACKUP_PATH" ]; then
    echo "Backup does not exist or is empty." >&2
    exit 1
fi
if ! verify_backup_checksum "$BACKUP_PATH"; then
    echo "Restore refused before confirmation because backup integrity verification failed." >&2
    exit 1
fi
case "$TARGET_REF" in
    *[!0-9a-f]*)
        echo "Target ref must be a lowercase hexadecimal commit SHA." >&2
        exit 2
        ;;
esac
if [ "${#TARGET_REF}" -ne 40 ]; then
    echo "Target ref must be the full 40-character commit SHA." >&2
    exit 2
fi

git -C "$REPO_ROOT" fetch --prune origin
TARGET_COMMIT=$(git -C "$REPO_ROOT" rev-parse "${TARGET_REF}^{commit}")
if [ "$TARGET_COMMIT" != "$TARGET_REF" ]; then
    echo "Resolved commit does not exactly match the requested SHA." >&2
    exit 1
fi
if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$TARGET_COMMIT" origin/main; then
    echo "Target restore commit is not reachable from origin/main." >&2
    exit 1
fi
RELEASE_ID=$(printf '%s' "$TARGET_COMMIT" | cut -c1-12)
export RELEASE_ID
PREVIOUS_COMMIT=$(git -C "$REPO_ROOT" rev-parse HEAD)
if [ -f "$STATE_DIR/current-commit" ]; then
    PREVIOUS_COMMIT=$(sed -n '1p' "$STATE_DIR/current-commit")
fi

(
    umask 022
    git -C "$REPO_ROOT" checkout --detach "$TARGET_COMMIT"
)
compose build api frontend
compose exec -T postgres pg_restore --list <"$BACKUP_PATH" >/dev/null

echo "This will replace the production database and application release."
printf 'Type RESTORE_PRODUCTION_BACKUP to continue: '
read -r CONFIRMATION
if [ "$CONFIRMATION" != "RESTORE_PRODUCTION_BACKUP" ]; then
    echo "Restore cancelled."
    exit 1
fi

if ! verify_backup_checksum "$BACKUP_PATH"; then
    echo "Restore refused after confirmation because backup integrity verification failed." >&2
    exit 1
fi

compose stop api worker frontend >/dev/null 2>&1 || true
SAFETY_BACKUP=$(bash "$SCRIPT_DIR/backup.sh")
POSTGRES_USER=$(env_value POSTGRES_USER)
POSTGRES_DB=$(env_value POSTGRES_DB)

compose exec -T postgres dropdb \
    --username "$POSTGRES_USER" \
    --force \
    --if-exists "$POSTGRES_DB"
compose exec -T postgres createdb \
    --username "$POSTGRES_USER" "$POSTGRES_DB"
compose exec -T postgres pg_restore \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --no-owner \
    --no-privileges \
    --exit-on-error <"$BACKUP_PATH"

compose --profile ops run --rm migrate
ensure_public_bootstrap
compose up -d api worker frontend

if ! wait_for_application_health; then
    compose stop api worker frontend >/dev/null 2>&1 || true
    echo "Restore health check failed; application services were stopped." >&2
    echo "Target commit: $TARGET_COMMIT" >&2
    echo "Restored backup: $BACKUP_PATH" >&2
    echo "Safety backup: $SAFETY_BACKUP" >&2
    exit 1
fi

write_state_file "$STATE_DIR/previous-release" "$PREVIOUS_COMMIT"
write_state_file "$STATE_DIR/current-commit" "$TARGET_COMMIT"
write_state_file "$STATE_DIR/current-backup" "$BACKUP_PATH"
# current-release is the final commit marker for a fully healthy restoration.
write_state_file "$STATE_DIR/current-release" "$RELEASE_ID"

echo "Restore healthy with release: $TARGET_COMMIT"
echo "Safety backup of replaced state: $SAFETY_BACKUP"
