#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

SCHEMA_MODE=full
TARGET_COMMIT=
BACKUP_INPUT=
acquire_production_operation_lock "$@"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --revision-only)
            SCHEMA_MODE=revision-only
            shift
            ;;
        --target-commit)
            if [ "$#" -lt 2 ]; then
                echo "Restore drill target commit is missing." >&2
                exit 2
            fi
            TARGET_COMMIT=$2
            shift 2
            ;;
        --*)
            echo "Unknown restore drill option: $1" >&2
            exit 2
            ;;
        *)
            if [ -n "$BACKUP_INPUT" ]; then
                echo "Restore drill accepts exactly one backup path." >&2
                exit 2
            fi
            BACKUP_INPUT=$1
            shift
            ;;
    esac
done
if [ -z "$BACKUP_INPUT" ]; then
    echo "Usage: deploy/scripts/restore_drill.sh [--revision-only] [--target-commit <full-sha>] <backup.dump>" >&2
    exit 2
fi

validate_environment >&2

SNAPSHOT_SUFFIX=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
INPUT_SNAPSHOT_PATH="$BACKUP_DIR/restore-input-${SNAPSHOT_SUFFIX}.dump"
DRILL_DIAGNOSTIC="$INPUT_SNAPSHOT_PATH.diagnostic"
DRILL_CONTAINER_ID=
INPUT_DESCRIPTORS_OPEN=false

cleanup_input_snapshot() {
    case "$INPUT_SNAPSHOT_PATH" in
        "$BACKUP_DIR"/restore-input-[0-9a-f]*.dump) ;;
        *)
            echo "Restore drill refused to clean an unexpected snapshot path." >&2
            return 1
            ;;
    esac
    rm -f -- "$INPUT_SNAPSHOT_PATH" \
        "$INPUT_SNAPSHOT_PATH.sha256" \
        "$DRILL_DIAGNOSTIC"
}

cleanup_container() {
    if [ -z "$DRILL_CONTAINER_ID" ]; then
        return 0
    fi
    if docker rm -f "$DRILL_CONTAINER_ID" >/dev/null 2>&1; then
        DRILL_CONTAINER_ID=
        return 0
    fi
    echo "Restore drill cleanup failed; temporary container may remain." >&2
    return 1
}

close_input_descriptors() {
    if [ "$INPUT_DESCRIPTORS_OPEN" != "true" ]; then
        return 0
    fi
    exec 3<&-
    exec 4<&-
    exec 5<&-
    INPUT_DESCRIPTORS_OPEN=false
}

on_exit() {
    status=$?
    trap - EXIT
    if ! cleanup_container; then
        status=1
    fi
    close_input_descriptors
    if ! cleanup_input_snapshot; then
        status=1
    fi
    exit "$status"
}
on_signal() {
    status=$1
    trap - HUP INT TERM
    exit "$status"
}
trap on_exit EXIT
trap 'on_signal 129' HUP
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

VALIDATED_PAIR=$(python3 "$SCRIPT_DIR/validate_backup_pair.py" \
    "$BACKUP_DIR" "$BACKUP_INPUT" "$INPUT_SNAPSHOT_PATH")
BACKUP_PATH=$(printf '%s\n' "$VALIDATED_PAIR" | sed -n '1p')
BACKUP_DIGEST=$(printf '%s\n' "$VALIDATED_PAIR" | sed -n '2p')
BACKUP_SIZE=$(printf '%s\n' "$VALIDATED_PAIR" | sed -n '3p')
if [ "$BACKUP_PATH" != "$INPUT_SNAPSHOT_PATH" ]; then
    echo "Restore drill validator returned an unexpected snapshot path." >&2
    exit 1
fi
: >"$DRILL_DIAGNOSTIC"
chmod 400 "$BACKUP_PATH" "$BACKUP_PATH.sha256"
exec 3<"$BACKUP_PATH"
exec 4<"$BACKUP_PATH"
exec 5<"$BACKUP_PATH"
INPUT_DESCRIPTORS_OPEN=true
if ! python3 -c '
import os
import stat
import sys

items = [os.fstat(number) for number in (3, 4, 5)]
identity = {(item.st_dev, item.st_ino, item.st_size) for item in items}
valid = all(
    stat.S_ISREG(item.st_mode)
    and stat.S_IMODE(item.st_mode) == 0o400
    and item.st_uid == os.getuid()
    and item.st_nlink == 1
    for item in items
)
sys.exit(0 if len(identity) == 1 and valid else 1)
'; then
    echo "Restore drill snapshot descriptors are inconsistent." >&2
    exit 1
fi
rm -f -- "$BACKUP_PATH" "$BACKUP_PATH.sha256"
CURRENT_BACKUP_DIGEST=$(sha256_digest_stream <&3)
if ! constant_time_equal "$BACKUP_DIGEST" "$CURRENT_BACKUP_DIGEST"; then
    echo "Restore drill snapshot changed before it was sealed for use." >&2
    exit 1
fi
if ! verify_postgres_archive_stream <&4 2>>"$DRILL_DIAGNOSTIC"; then
    echo "Restore drill archive validation failed." >&2
    exit 1
fi

POSTGRES_IMAGE=$(env_value POSTGRES_IMAGE)
DRILL_SUFFIX=$(python3 -c 'import secrets; print(secrets.token_hex(6))')
DRILL_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
DRILL_CONTAINER_NAME="ai-writing-restore-drill-${DRILL_SUFFIX}"
DRILL_STARTED_AT=$(date +%s)

DRILL_CONTAINER_ID=$(docker create --name "$DRILL_CONTAINER_NAME" --pull never \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=2g,uid=999,gid=999,mode=0700 \
    --tmpfs /var/run/postgresql:rw,nosuid,nodev,size=16m,uid=999,gid=999,mode=0775 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,uid=999,gid=999,mode=1777 \
    --cpus 1 \
    --memory 2g \
    --memory-swap 2g \
    --pids-limit 128 \
    --user 999:999 \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -e POSTGRES_USER=restore_drill \
    -e POSTGRES_PASSWORD="$DRILL_PASSWORD" \
    -e POSTGRES_DB=restore_drill \
    "$POSTGRES_IMAGE")
DRILL_PASSWORD=
docker start "$DRILL_CONTAINER_ID" >/dev/null

attempt=0
until docker exec "$DRILL_CONTAINER_ID" pg_isready \
    -U restore_drill -d restore_drill >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "Restore drill PostgreSQL did not become ready." >&2
        exit 1
    fi
    sleep 2
done

if ! docker exec -i "$DRILL_CONTAINER_ID" pg_restore \
    --username restore_drill \
    --dbname restore_drill \
    --no-owner \
    --no-privileges \
    --exit-on-error <&5 2>>"$DRILL_DIAGNOSTIC"; then
    echo "Restore drill failed while restoring the selected archive." >&2
    exit 1
fi

QUERY_RESULT=$(docker exec "$DRILL_CONTAINER_ID" psql \
    -U restore_drill -d restore_drill -Atqc "SELECT 1" 2>>"$DRILL_DIAGNOSTIC")
if [ "$QUERY_RESULT" != "1" ]; then
    echo "Restore drill database is not queryable." >&2
    exit 1
fi

ALEMBIC_REVISION=$(docker exec "$DRILL_CONTAINER_ID" psql \
    -U restore_drill -d restore_drill -Atqc \
    "SELECT version_num FROM alembic_version ORDER BY version_num" 2>>"$DRILL_DIAGNOSTIC")
ALEMBIC_REVISION_COUNT=$(printf '%s\n' "$ALEMBIC_REVISION" | awk 'NF { count += 1 } END { print count + 0 }')
case "$ALEMBIC_REVISION" in
    ""|*[!A-Za-z0-9_-]*)
        echo "Restore drill found an invalid Alembic revision." >&2
        exit 1
        ;;
esac
if [ "$ALEMBIC_REVISION_COUNT" != "1" ]; then
    echo "Restore drill requires exactly one Alembic revision." >&2
    exit 1
fi
if [ -n "$TARGET_COMMIT" ] && ! printf '%s\n' "$ALEMBIC_REVISION" \
    | python3 "$SCRIPT_DIR/migration_compatibility.py" \
        verify-target "$REPO_ROOT" "$TARGET_COMMIT"; then
    echo "Restore drill revision is incompatible with the target commit." >&2
    exit 1
fi

CRITICAL_TABLE_COUNT=not_checked
if [ "$SCHEMA_MODE" = "full" ]; then
    CRITICAL_TABLE_COUNT=$(docker exec "$DRILL_CONTAINER_ID" psql \
        -U restore_drill -d restore_drill -Atqc \
        "SELECT count(*) FROM (VALUES
            ('accounts'),
            ('projects'),
            ('scenes'),
            ('core_entities'),
            ('async_tasks'),
            ('account_llm_credentials'),
            ('import_workflow_runs'),
            ('interaction_journeys')
        ) AS required(name)
        WHERE to_regclass('public.' || quote_ident(required.name)) IS NOT NULL" \
        2>>"$DRILL_DIAGNOSTIC")
    if [ "$CRITICAL_TABLE_COUNT" != "8" ]; then
        echo "Restore drill is missing one or more critical tables." >&2
        exit 1
    fi
fi

if ! cleanup_container; then
    exit 1
fi
close_input_descriptors
if ! cleanup_input_snapshot; then
    exit 1
fi
DRILL_FINISHED_AT=$(date +%s)
DRILL_DURATION=$((DRILL_FINISHED_AT - DRILL_STARTED_AT))
COMPLETED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
trap - EXIT HUP INT TERM
printf 'Restore drill passed: completed_at=%s duration_seconds=%s sha256=%s bytes=%s alembic_revision=%s critical_tables=%s\n' \
    "$COMPLETED_AT" "$DRILL_DURATION" "$BACKUP_DIGEST" "$BACKUP_SIZE" \
    "$ALEMBIC_REVISION" "$CRITICAL_TABLE_COUNT"
