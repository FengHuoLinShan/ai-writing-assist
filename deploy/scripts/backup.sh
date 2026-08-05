#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

acquire_production_operation_lock "$@"

# Callers capture stdout as the machine-readable backup path. Keep validation
# diagnostics visible without contaminating that command-substitution contract.
validate_environment >&2
ensure_private_backup_directory >&2

POSTGRES_USER=$(env_value POSTGRES_USER)
POSTGRES_DB=$(env_value POSTGRES_DB)
RETENTION_DAYS=$(env_value BACKUP_RETENTION_DAYS)
HEALTHCHECK_URL=$(env_value HEALTHCHECKS_BACKUP_PING_URL)
HEALTHCHECK_URL=${HEALTHCHECK_URL%/}
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_SUCCEEDED=false
STAGING_DUMP=
STAGING_CHECKSUM=
BACKUP_PATH=
CHECKSUM_PATH=

on_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$STAGING_DUMP" ] && [ -f "$STAGING_DUMP" ] && [ ! -L "$STAGING_DUMP" ]; then
        rm -f "$STAGING_DUMP" || true
    fi
    if [ -n "$STAGING_CHECKSUM" ] && [ -f "$STAGING_CHECKSUM" ] && [ ! -L "$STAGING_CHECKSUM" ]; then
        rm -f "$STAGING_CHECKSUM" || true
    fi
    if [ "$BACKUP_SUCCEEDED" != "true" ]; then
        healthcheck_ping "${HEALTHCHECK_URL}/fail" || true
    fi
    exit "$status"
}
trap on_exit EXIT HUP INT TERM

healthcheck_ping "${HEALTHCHECK_URL}/start" || true

for stale_staging in \
    "$BACKUP_DIR"/.backup-stage.* \
    "$BACKUP_DIR"/.backup-checksum-stage.* \
    "$BACKUP_DIR"/*.dump.partial; do
    if [ -f "$stale_staging" ] && [ ! -L "$stale_staging" ]; then
        rm -f "$stale_staging"
    fi
done
BACKUP_PATH="$BACKUP_DIR/${TIMESTAMP}.dump"
CHECKSUM_PATH="${BACKUP_PATH}.sha256"
if [ -e "$BACKUP_PATH" ] || [ -L "$BACKUP_PATH" ] \
    || [ -e "$CHECKSUM_PATH" ] || [ -L "$CHECKSUM_PATH" ]; then
    echo "Backup timestamp collision; refusing to overwrite an existing backup." >&2
    exit 1
fi
STAGING_DUMP=$(mktemp "$BACKUP_DIR/.backup-stage.XXXXXX")
STAGING_CHECKSUM=$(mktemp "$BACKUP_DIR/.backup-checksum-stage.XXXXXX")

compose up -d postgres >/dev/null

attempt=0
until compose exec -T postgres pg_isready \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "PostgreSQL did not become ready for backup." >&2
        exit 1
    fi
    sleep 2
done

compose exec -T postgres pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --format=custom \
    --no-owner \
    --no-privileges >"$STAGING_DUMP"

if [ ! -s "$STAGING_DUMP" ]; then
    echo "Backup is empty; refusing to publish it." >&2
    exit 1
fi

verify_postgres_archive "$STAGING_DUMP"

BACKUP_DIGEST=$(sha256_digest "$STAGING_DUMP")
printf '%s  %s\n' "$BACKUP_DIGEST" "$BACKUP_PATH" >"$STAGING_CHECKSUM"
python3 "$SCRIPT_DIR/backup_pair_publish.py" publish \
    "$BACKUP_DIR" "$STAGING_DUMP" "$STAGING_CHECKSUM" "$TIMESTAMP.dump"
STAGING_DUMP=
STAGING_CHECKSUM=

find "$BACKUP_DIR" -type f \
    \( -name "*.dump" -o -name "*.dump.sha256" \) \
    -mtime "+$RETENTION_DAYS" -delete

if ! command -v restic >/dev/null 2>&1; then
    echo "restic is required for encrypted off-site backups." >&2
    exit 1
fi

export RESTIC_REPOSITORY
export B2_ACCOUNT_ID
export B2_ACCOUNT_KEY
export RESTIC_PASSWORD
RESTIC_REPOSITORY=$(env_value RESTIC_REPOSITORY)
B2_ACCOUNT_ID=$(env_value B2_ACCOUNT_ID)
B2_ACCOUNT_KEY=$(env_value B2_ACCOUNT_KEY)
RESTIC_PASSWORD=$(env_value RESTIC_PASSWORD)

if ! restic snapshots --latest 1 >/dev/null 2>&1; then
    echo "The restic repository is unavailable or not initialized." >&2
    exit 1
fi
restic backup \
    "$BACKUP_PATH" \
    "${BACKUP_PATH}.sha256" \
    --tag ai-writing-assist-postgres >&2
restic forget \
    --tag ai-writing-assist-postgres \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 6 \
    --prune >&2

healthcheck_ping "$HEALTHCHECK_URL" || true
BACKUP_SUCCEEDED=true
trap - EXIT HUP INT TERM
printf '%s\n' "$BACKUP_PATH"
