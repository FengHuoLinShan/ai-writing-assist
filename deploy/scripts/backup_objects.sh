#!/bin/sh
set -eu
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"
acquire_production_operation_lock "$@"
validate_environment >&2
ensure_private_backup_directory >&2
OBJECT_ROOT="$BACKUP_DIR/objects"
python3 "$SCRIPT_DIR/ensure_private_directory.py" "$OBJECT_ROOT"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
POSTGRES_USER=$(env_value POSTGRES_USER)
POSTGRES_DB=$(env_value POSTGRES_DB)
POSTGRES_IMAGE=$(env_value POSTGRES_IMAGE)
STAGING=$(mktemp "$BACKUP_DIR/.object-db-stage.XXXXXX")
CHECKSUM=$(mktemp "$BACKUP_DIR/.object-db-checksum.XXXXXX")
REFERENCES=$(mktemp "$OBJECT_ROOT/.references.XXXXXX")
CONTAINER=
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$CONTAINER" ]; then docker rm -fv "$CONTAINER" >/dev/null 2>&1 || status=1; fi
    rm -f -- "$STAGING" "$CHECKSUM" "$REFERENCES"
    if [ "$status" -ne 0 ]; then echo "Object backup incomplete." >&2; fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --format=custom --exclude-table-data=public.context_interaction_source_cache \
    --no-owner --no-privileges >"$STAGING"
verify_postgres_archive "$STAGING"
DIGEST=$(sha256_digest "$STAGING")
printf '%s  %s\n' "$DIGEST" "$BACKUP_DIR/$TIMESTAMP.dump" >"$CHECKSUM"
python3 "$SCRIPT_DIR/backup_pair_publish.py" publish "$BACKUP_DIR" "$STAGING" "$CHECKSUM" "$TIMESTAMP.dump"
CONTAINER=$(docker create --pull never --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --user 999:999 \
    --volume /var/lib/postgresql/data \
    --tmpfs /var/run/postgresql:rw,nosuid,nodev,size=16m,uid=999,gid=999,mode=0775 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,uid=999,gid=999,mode=1777 \
    --cpus 1 --memory 2g --memory-swap 2g --pids-limit 128 \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -e POSTGRES_USER=object_snapshot -e POSTGRES_DB=object_snapshot \
    -e POSTGRES_HOST_AUTH_METHOD=trust "$POSTGRES_IMAGE")
docker start "$CONTAINER" >/dev/null
attempt=0
until docker exec "$CONTAINER" pg_isready -U object_snapshot >/dev/null 2>&1; do
    attempt=$((attempt + 1)); [ "$attempt" -lt 30 ] || exit 1; sleep 1
done
docker exec -i "$CONTAINER" pg_restore -U object_snapshot -d object_snapshot \
    --no-owner --no-privileges --exit-on-error <"$BACKUP_DIR/$TIMESTAMP.dump" >/dev/null
docker exec -i "$CONTAINER" psql -U object_snapshot -d object_snapshot \
    -v ON_ERROR_STOP=1 -v map_bucket="$(env_value MAP_ATLAS_S3_BUCKET)" \
    -v world_bucket="$(env_value WORLD_OBJECT_S3_BUCKET)" -At \
    <"$SCRIPT_DIR/object_references.sql" >"$REFERENCES"
docker rm -fv "$CONTAINER" >/dev/null
CONTAINER=
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name "*.dump" -o -name "*.dump.sha256" \) \
    -mmin "+$(($(env_value BACKUP_RETENTION_DAYS) * 1440))" -delete
compose run --rm --no-deps --user "$(id -u):$(id -g)" object-backup \
    backup /backup --references "/backup/$(basename "$REFERENCES")" \
    --timestamp "$TIMESTAMP" --db-sha256 "$DIGEST" \
    --retention-days "$(env_value BACKUP_RETENTION_DAYS)"
