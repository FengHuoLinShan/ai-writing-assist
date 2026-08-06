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

acquire_production_operation_lock "$@"
validate_environment
verify_deployment_checkout

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

PREVIOUS_COMMIT=$(resolve_active_deployment_commit)
verify_active_deployment_checkout "$PREVIOUS_COMMIT"
if ! verify_release_migration_compatibility "$PREVIOUS_COMMIT" "$TARGET_COMMIT"; then
    exit 1
fi
OPERATION_ID=$(deployment_state_operation_id)
DEPLOYMENT_COMMITTED=false
DEPLOYMENT_STATE_WRITE_FAILED=false
NEW_APP_SERVICES_MAY_HAVE_STARTED=false
FIRST_RELEASE_FRESH=false
FIRST_RELEASE_ROLLBACK_REQUIRED=false
FIRST_RELEASE_POSTGRES_USER=
FIRST_RELEASE_POSTGRES_DB=

rollback_verified_empty_first_release() {
    if [ "$FIRST_RELEASE_ROLLBACK_REQUIRED" != "true" ]; then
        return 0
    fi
    echo "Resetting the failed first-release schema to its previously verified empty state." >&2
    if ! compose exec -T postgres dropdb \
        --username "$FIRST_RELEASE_POSTGRES_USER" \
        --force \
        --if-exists "$FIRST_RELEASE_POSTGRES_DB" \
        || ! compose exec -T postgres createdb \
            --username "$FIRST_RELEASE_POSTGRES_USER" \
            "$FIRST_RELEASE_POSTGRES_DB"; then
        echo "Failed to reset the first-release database; manual recovery is required." >&2
        return 1
    fi
    FIRST_RELEASE_ROLLBACK_REQUIRED=false
}

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
                echo "Warning: failed to stop application services after an uncommitted release." >&2
            fi
        fi
        if ! rollback_verified_empty_first_release; then
            status=1
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
    # Keep secrets, backups, and release state private without making checked-out
    # application files unreadable to non-root container processes.
    umask 022
    git -C "$REPO_ROOT" -c core.hooksPath=/dev/null checkout --detach "$TARGET_COMMIT"
)
verify_deployment_checkout

RELEASE_ID=$(printf '%s' "$TARGET_COMMIT" | cut -c1-12)
export RELEASE_ID

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Target commit does not contain production deployment assets." >&2
    exit 1
fi

validate_environment
validate_deployment_state_contract
prepare_fixed_commit_build_context "$TARGET_COMMIT"
compose build api frontend

if ! compose stop api worker frontend; then
    echo "Unable to quiesce application services before the pre-migration backup." >&2
    exit 1
fi

compose up -d postgres embedding

if [ ! -e "$STATE_DIR/deployment-state.json" ] \
    && [ ! -e "$STATE_DIR/current-release" ] \
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
    FIRST_RELEASE_FRESH=true
    FIRST_RELEASE_POSTGRES_USER=$POSTGRES_USER
    FIRST_RELEASE_POSTGRES_DB=$POSTGRES_DB
fi

if ! compose run --rm api python scripts/check_embedding.py; then
    echo "Local embedding startup or 768-dimensional contract check failed." >&2
    exit 1
fi

BACKUP_PATH=
if [ "$FIRST_RELEASE_FRESH" != "true" ]; then
    BACKUP_PATH=$(bash "$SCRIPT_DIR/backup.sh")
    bash "$SCRIPT_DIR/restore_drill.sh" \
        --target-commit "$TARGET_COMMIT" "$BACKUP_PATH"
else
    FIRST_RELEASE_ROLLBACK_REQUIRED=true
fi

if ! compose --profile ops run --rm migrate; then
    if [ -n "$BACKUP_PATH" ]; then
        echo "Migration failed. Database backup: $BACKUP_PATH" >&2
    else
        echo "Migration failed on the verified empty first-release database." >&2
    fi
    exit 1
fi

if [ "$FIRST_RELEASE_FRESH" = "true" ]; then
    BACKUP_PATH=$(bash "$SCRIPT_DIR/backup.sh")
    bash "$SCRIPT_DIR/restore_drill.sh" \
        --target-commit "$TARGET_COMMIT" "$BACKUP_PATH"
    FIRST_RELEASE_ROLLBACK_REQUIRED=false
fi

ensure_public_bootstrap
NEW_APP_SERVICES_MAY_HAVE_STARTED=true
compose up -d api worker frontend

if ! wait_for_application_health; then
    compose stop api worker frontend >/dev/null 2>&1 || true
    echo "Release health check failed; application services were stopped." >&2
    echo "Target commit: $TARGET_COMMIT" >&2
    echo "Previous commit: $PREVIOUS_COMMIT" >&2
    echo "Pre-migration backup: $BACKUP_PATH" >&2
    exit 1
fi

if ! bash "$SCRIPT_DIR/verify_public.sh"; then
    compose stop api worker frontend >/dev/null 2>&1 || true
    echo "Public release verification failed; application services were stopped." >&2
    echo "Target commit: $TARGET_COMMIT" >&2
    echo "Previous commit: $PREVIOUS_COMMIT" >&2
    echo "Pre-migration backup: $BACKUP_PATH" >&2
    exit 1
fi

if ! write_deployment_state "$OPERATION_ID" release \
    "$TARGET_COMMIT" "$PREVIOUS_COMMIT" "$BACKUP_PATH"; then
    DEPLOYMENT_STATE_WRITE_FAILED=true
    exit 1
fi
DEPLOYMENT_COMMITTED=true
cleanup_fixed_commit_build_context
trap - EXIT HUP INT TERM

echo "Release healthy: $TARGET_COMMIT"
echo "Database backup: $BACKUP_PATH"
