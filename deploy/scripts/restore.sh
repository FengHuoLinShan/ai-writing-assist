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

SNAPSHOT_SUFFIX=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
INPUT_SNAPSHOT_PATH="$BACKUP_DIR/restore-input-${SNAPSHOT_SUFFIX}.dump"
RESTORE_INPUT_DESCRIPTORS_OPEN=false

close_restore_input_descriptors() {
    if [ "$RESTORE_INPUT_DESCRIPTORS_OPEN" != "true" ]; then
        return 0
    fi
    exec 6<&-
    exec 7<&-
    RESTORE_INPUT_DESCRIPTORS_OPEN=false
}

cleanup_restore_snapshot() {
    case "$INPUT_SNAPSHOT_PATH" in
        "$BACKUP_DIR"/restore-input-[0-9a-f]*.dump) ;;
        *)
            echo "Restore refused to clean an unexpected snapshot path." >&2
            return 1
            ;;
    esac
    rm -f -- "$INPUT_SNAPSHOT_PATH" "$INPUT_SNAPSHOT_PATH.sha256"
}

cleanup_early_restore_attempt() {
    status=$?
    trap - EXIT HUP INT TERM
    close_restore_input_descriptors
    if ! cleanup_restore_snapshot; then
        status=1
    fi
    exit "$status"
}
trap cleanup_early_restore_attempt EXIT HUP INT TERM

VALIDATED_PAIR=$(python3 "$SCRIPT_DIR/validate_backup_pair.py" \
    "$BACKUP_DIR" "$BACKUP_INPUT" "$INPUT_SNAPSHOT_PATH")
BACKUP_PATH=$(printf '%s\n' "$VALIDATED_PAIR" | sed -n '1p')
BACKUP_DIGEST=$(printf '%s\n' "$VALIDATED_PAIR" | sed -n '2p')
ORIGINAL_BACKUP_PATH=$(printf '%s\n' "$VALIDATED_PAIR" | sed -n '4p')
if [ "$BACKUP_PATH" != "$INPUT_SNAPSHOT_PATH" ]; then
    echo "Restore validator returned an unexpected snapshot path." >&2
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
    close_restore_input_descriptors
    if ! cleanup_restore_snapshot; then
        status=1
    fi
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
bash "$SCRIPT_DIR/restore_drill.sh" --revision-only \
    --target-commit "$TARGET_COMMIT" "$BACKUP_PATH"
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
CURRENT_BACKUP_DIGEST=$(sha256_digest "$BACKUP_PATH")
if ! constant_time_equal "$BACKUP_DIGEST" "$CURRENT_BACKUP_DIGEST"; then
    echo "Restore refused because the validated input snapshot changed." >&2
    exit 1
fi

if ! compose stop api worker frontend; then
    echo "Unable to quiesce application services before the safety backup." >&2
    exit 1
fi

SAFETY_BACKUP=$(bash "$SCRIPT_DIR/backup.sh")
POSTGRES_USER=$(env_value POSTGRES_USER)
POSTGRES_DB=$(env_value POSTGRES_DB)

if ! verify_backup_checksum "$BACKUP_PATH"; then
    echo "Restore refused after the safety backup because input integrity verification failed." >&2
    exit 1
fi
chmod 400 "$BACKUP_PATH" "$BACKUP_PATH.sha256"
exec 6<"$BACKUP_PATH"
exec 7<"$BACKUP_PATH"
RESTORE_INPUT_DESCRIPTORS_OPEN=true
if ! python3 -c '
import os
import stat
import sys

first = os.fstat(6)
second = os.fstat(7)
same = (first.st_dev, first.st_ino, first.st_size) == (
    second.st_dev,
    second.st_ino,
    second.st_size,
)
valid = all(
    stat.S_ISREG(item.st_mode)
    and stat.S_IMODE(item.st_mode) == 0o400
    and item.st_uid == os.getuid()
    and item.st_nlink == 1
    for item in (first, second)
)
sys.exit(0 if same and valid else 1)
'; then
    echo "Restore refused because snapshot descriptors are inconsistent." >&2
    exit 1
fi
rm -f -- "$BACKUP_PATH" "$BACKUP_PATH.sha256"
CURRENT_BACKUP_DIGEST=$(sha256_digest_stream <&6)
exec 6<&-
if ! constant_time_equal "$BACKUP_DIGEST" "$CURRENT_BACKUP_DIGEST"; then
    echo "Restore refused because the private snapshot changed before use." >&2
    exit 1
fi

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
    --exit-on-error <&7
exec 7<&-
RESTORE_INPUT_DESCRIPTORS_OPEN=false

compose --profile ops run --rm migrate
ensure_public_bootstrap
NEW_APP_SERVICES_MAY_HAVE_STARTED=true
compose up -d api worker frontend

if ! wait_for_application_health; then
    compose stop api worker frontend >/dev/null 2>&1 || true
    echo "Restore health check failed; application services were stopped." >&2
    echo "Target commit: $TARGET_COMMIT" >&2
    echo "Restored backup: $ORIGINAL_BACKUP_PATH" >&2
    echo "Safety backup: $SAFETY_BACKUP" >&2
    exit 1
fi

if ! bash "$SCRIPT_DIR/verify_public.sh"; then
    compose stop api worker frontend >/dev/null 2>&1 || true
    echo "Public restore verification failed; application services were stopped." >&2
    echo "Target commit: $TARGET_COMMIT" >&2
    echo "Restored backup: $ORIGINAL_BACKUP_PATH" >&2
    echo "Safety backup: $SAFETY_BACKUP" >&2
    exit 1
fi

if ! write_deployment_state "$OPERATION_ID" restore \
    "$TARGET_COMMIT" "$PREVIOUS_COMMIT" "$ORIGINAL_BACKUP_PATH"; then
    DEPLOYMENT_STATE_WRITE_FAILED=true
    exit 1
fi
DEPLOYMENT_COMMITTED=true
cleanup_fixed_commit_build_context
close_restore_input_descriptors
cleanup_restore_snapshot
trap - EXIT HUP INT TERM

echo "Restore healthy with release: $TARGET_COMMIT"
echo "Safety backup of replaced state: $SAFETY_BACKUP"
