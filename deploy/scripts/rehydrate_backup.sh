#!/bin/sh

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

if [ "$#" -ne 2 ]; then
    echo "Usage: deploy/scripts/rehydrate_backup.sh <full-restic-snapshot-id> <YYYYMMDDTHHMMSSZ.dump>" >&2
    exit 2
fi
SNAPSHOT_ID=$1
BACKUP_NAME=$2
case "$SNAPSHOT_ID" in
    *[!0-9a-f]*|"")
        echo "Restic snapshot id must be a lowercase hexadecimal SHA." >&2
        exit 2
        ;;
esac
if [ "${#SNAPSHOT_ID}" -ne 64 ]; then
    echo "Restic snapshot id must be the full 64-character SHA." >&2
    exit 2
fi
case "$BACKUP_NAME" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.dump) ;;
    *)
        echo "Backup basename must be YYYYMMDDTHHMMSSZ.dump." >&2
        exit 2
        ;;
esac

acquire_production_operation_lock "$@"
validate_environment >&2
ensure_private_backup_directory >&2

for stale_staging in \
    "$BACKUP_DIR"/.rehydrate-dump-stage.* \
    "$BACKUP_DIR"/.rehydrate-checksum-stage.* \
    "$BACKUP_DIR"/.rehydrate-snapshots.* \
    "$BACKUP_DIR"/.rehydrate-listing.* \
    "$BACKUP_DIR"/.rehydrate-selection.*; do
    if [ -f "$stale_staging" ] && [ ! -L "$stale_staging" ]; then
        rm -f "$stale_staging"
    fi
done

if ! command -v restic >/dev/null 2>&1; then
    echo "restic is required to rehydrate an off-site backup." >&2
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

BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"
CHECKSUM_PATH="$BACKUP_PATH.sha256"
if [ -e "$BACKUP_PATH" ] || [ -L "$BACKUP_PATH" ] \
    || [ -e "$CHECKSUM_PATH" ] || [ -L "$CHECKSUM_PATH" ]; then
    echo "Refusing to overwrite an existing backup pair." >&2
    exit 1
fi

STAGING_DUMP=
STAGING_CHECKSUM=
SNAPSHOTS_JSON=
LISTING_JSON=
SELECTION_FILE=

on_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    for temporary in "$STAGING_DUMP" "$STAGING_CHECKSUM" "$SNAPSHOTS_JSON" "$LISTING_JSON" "$SELECTION_FILE"; do
        if [ -n "$temporary" ] && [ -f "$temporary" ] && [ ! -L "$temporary" ]; then
            rm -f "$temporary" || true
        fi
    done
    exit "$status"
}
trap on_exit EXIT HUP INT TERM

SNAPSHOTS_JSON=$(mktemp "$BACKUP_DIR/.rehydrate-snapshots.XXXXXX")
LISTING_JSON=$(mktemp "$BACKUP_DIR/.rehydrate-listing.XXXXXX")
SELECTION_FILE=$(mktemp "$BACKUP_DIR/.rehydrate-selection.XXXXXX")
restic snapshots --json "$SNAPSHOT_ID" >"$SNAPSHOTS_JSON"
restic ls --json "$SNAPSHOT_ID" >"$LISTING_JSON"
python3 "$SCRIPT_DIR/rehydrate_backup_metadata.py" \
    "$SNAPSHOT_ID" "$BACKUP_NAME" "$SNAPSHOTS_JSON" "$LISTING_JSON" >"$SELECTION_FILE"
REMOTE_DUMP=$(sed -n '1p' "$SELECTION_FILE")
REMOTE_CHECKSUM=$(sed -n '2p' "$SELECTION_FILE")
if [ "$(wc -l <"$SELECTION_FILE")" -ne 2 ] \
    || [ -z "$REMOTE_DUMP" ] || [ -z "$REMOTE_CHECKSUM" ]; then
    echo "Off-site backup metadata selection is invalid." >&2
    exit 1
fi

STAGING_DUMP=$(mktemp "$BACKUP_DIR/.rehydrate-dump-stage.XXXXXX")
STAGING_CHECKSUM=$(mktemp "$BACKUP_DIR/.rehydrate-checksum-stage.XXXXXX")
restic dump "$SNAPSHOT_ID" "$REMOTE_DUMP" >"$STAGING_DUMP"
restic dump "$SNAPSHOT_ID" "$REMOTE_CHECKSUM" >"$STAGING_CHECKSUM"
if [ ! -s "$STAGING_DUMP" ] || [ ! -s "$STAGING_CHECKSUM" ]; then
    echo "Rehydrated backup pair is empty." >&2
    exit 1
fi
if ! verify_backup_pair_checksum "$STAGING_DUMP" "$STAGING_CHECKSUM"; then
    echo "Rehydrated backup pair failed integrity verification." >&2
    exit 1
fi

python3 "$SCRIPT_DIR/backup_pair_publish.py" publish \
    "$BACKUP_DIR" "$STAGING_DUMP" "$STAGING_CHECKSUM" "$BACKUP_NAME"
STAGING_DUMP=
STAGING_CHECKSUM=

rm -f "$SNAPSHOTS_JSON" "$LISTING_JSON" "$SELECTION_FILE"
SNAPSHOTS_JSON=
LISTING_JSON=
SELECTION_FILE=
trap - EXIT HUP INT TERM
printf '%s\n' "$BACKUP_PATH"
