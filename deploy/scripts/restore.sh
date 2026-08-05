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

acquire_production_operation_lock "$@"
validate_environment
verify_deployment_checkout
ensure_private_backup_directory

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
PREVIOUS_COMMIT=$(resolve_active_deployment_commit)
OPERATION_ID=$(deployment_state_operation_id)
DEPLOYMENT_COMMITTED=false
DEPLOYMENT_STATE_WRITE_FAILED=false
NEW_APP_SERVICES_MAY_HAVE_STARTED=false

cleanup_uncommitted_attempt() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$DEPLOYMENT_COMMITTED" != "true" ] \
        && [ "$DEPLOYMENT_STATE_WRITE_FAILED" != "true" ] \
        && deployment_state_matches "$TARGET_COMMIT" "$OPERATION_ID"; then
        DEPLOYMENT_COMMITTED=true
    fi
    if [ "$DEPLOYMENT_COMMITTED" != "true" ]; then
        if [ "$NEW_APP_SERVICES_MAY_HAVE_STARTED" = "true" ]; then
            if ! compose stop api worker frontend >/dev/null 2>&1; then
                echo "Warning: failed to stop application services after an uncommitted restore." >&2
            fi
        fi
        if ! (
            umask 022
            git -C "$REPO_ROOT" -c core.hooksPath=/dev/null checkout --detach "$PREVIOUS_COMMIT"
        ); then
            echo "Warning: failed to restore the finalized deployment checkout." >&2
        fi
    fi
    cleanup_fixed_commit_build_context
    exit "$status"
}
trap cleanup_uncommitted_attempt EXIT HUP INT TERM

(
    umask 022
    git -C "$REPO_ROOT" -c core.hooksPath=/dev/null checkout --detach "$TARGET_COMMIT"
)
verify_deployment_checkout
validate_environment
validate_deployment_state_contract
prepare_fixed_commit_build_context "$TARGET_COMMIT"
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

if ! compose stop api worker frontend; then
    echo "Unable to quiesce application services before the safety backup." >&2
    exit 1
fi

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
NEW_APP_SERVICES_MAY_HAVE_STARTED=true
compose up -d api worker frontend

if ! wait_for_application_health; then
    compose stop api worker frontend >/dev/null 2>&1 || true
    echo "Restore health check failed; application services were stopped." >&2
    echo "Target commit: $TARGET_COMMIT" >&2
    echo "Restored backup: $BACKUP_PATH" >&2
    echo "Safety backup: $SAFETY_BACKUP" >&2
    exit 1
fi

if ! write_deployment_state "$OPERATION_ID" restore \
    "$TARGET_COMMIT" "$PREVIOUS_COMMIT" "$BACKUP_PATH"; then
    DEPLOYMENT_STATE_WRITE_FAILED=true
    exit 1
fi
DEPLOYMENT_COMMITTED=true
cleanup_fixed_commit_build_context
trap - EXIT HUP INT TERM

echo "Restore healthy with release: $TARGET_COMMIT"
echo "Safety backup of replaced state: $SAFETY_BACKUP"
