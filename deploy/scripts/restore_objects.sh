#!/bin/sh
set -eu
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"
acquire_production_operation_lock "$@"
if [ "$#" -ne 1 ] && [ "$#" -ne 2 ]; then
    echo "Usage: restore_objects.sh <private object directory> <timestamp> | <private image ZIP>" >&2
    exit 2
fi
validate_environment >&2
load_release_id
ensure_private_backup_directory >&2
REFERENCES=
TEMP_ROOT=
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$REFERENCES" ]; then rm -f -- "$REFERENCES"; fi
    if [ -n "$TEMP_ROOT" ]; then
        case "$TEMP_ROOT" in "$BACKUP_DIR"/.object-restore.*) rm -rf -- "$TEMP_ROOT" ;; *) status=1 ;; esac
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
SOURCE=$(python3 - "$1" "$#" <<'PYTHON'
import os
import stat
import sys
from pathlib import Path
p = Path(sys.argv[1])
info = p.lstat()
is_zip = sys.argv[2] == "1"
valid = stat.S_ISREG(info.st_mode) if is_zip else stat.S_ISDIR(info.st_mode)
mode = 0o600 if is_zip else 0o700
if not valid or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
    sys.exit("Unsafe private object restore input")
print(p.resolve())
PYTHON
)
if [ "$#" -eq 1 ]; then
    python3 "$SCRIPT_DIR/ensure_private_directory.py" "$BACKUP_DIR/objects"
    TEMP_ROOT=$(mktemp -d "$BACKUP_DIR/.object-restore.XXXXXX")
    OBJECT_RESTORE_DIR="$TEMP_ROOT/package"
    mkdir -m 700 "$OBJECT_RESTORE_DIR"
    TIMESTAMP=$(compose run -T --rm --no-deps --user "$(id -u):$(id -g)" \
        --volume "$SOURCE:/package.zip:ro" --volume "$OBJECT_RESTORE_DIR:/unpacked" \
        object-backup unpack /unpacked --package /package.zip)
else
    OBJECT_RESTORE_DIR=$SOURCE
    TIMESTAMP=$2
fi
if ! printf '%s\n' "$TIMESTAMP" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
    echo "Invalid object manifest timestamp." >&2
    exit 2
fi
export OBJECT_RESTORE_DIR
REFERENCES=$(mktemp "$BACKUP_DIR/.restore-object-references.XXXXXX")
compose exec -T postgres psql -U "$(env_value POSTGRES_USER)" -d "$(env_value POSTGRES_DB)" \
    -v ON_ERROR_STOP=1 -v map_bucket="$(env_value MAP_ATLAS_S3_BUCKET)" \
    -v world_bucket="$(env_value WORLD_OBJECT_S3_BUCKET)" -At \
    <"$SCRIPT_DIR/object_references.sql" >"$REFERENCES"
# Validate all bytes and target DB ownership before initializer or any bucket write.
compose run -T --rm --no-deps --user "$(id -u):$(id -g)" object-restore \
    verify /backup --snapshot "/backup/snapshots/$TIMESTAMP" \
    --target-references /dev/stdin <"$REFERENCES"
compose run -T --rm minio-init >&2
compose run -T --rm --no-deps --user "$(id -u):$(id -g)" object-restore \
    restore /backup --snapshot "/backup/snapshots/$TIMESTAMP" \
    --target-references /dev/stdin <"$REFERENCES"
