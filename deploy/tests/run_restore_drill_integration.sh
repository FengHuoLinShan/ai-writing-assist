#!/bin/sh

set -eu
umask 077

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ai-writing-restore-integration.XXXXXX")
SOURCE_CONTAINER_ID=

cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$SOURCE_CONTAINER_ID" ]; then
        docker rm -f "$SOURCE_CONTAINER_ID" >/dev/null 2>&1 || status=1
    fi
    rm -rf -- "$TMP_ROOT"
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

cp -R "$REPO_ROOT/deploy/scripts" "$TMP_ROOT/scripts"
cp "$REPO_ROOT/deploy/tests/fixtures/closed-test.env" "$TMP_ROOT/.env.production"
chmod 0600 "$TMP_ROOT/.env.production"
mkdir -m 0700 "$TMP_ROOT/backups"

POSTGRES_IMAGE=$(python3 "$TMP_ROOT/scripts/validate_env.py" \
    --env "$TMP_ROOT/.env.production" --get POSTGRES_IMAGE)
docker pull "$POSTGRES_IMAGE" >/dev/null

SOURCE_NAME="ai-writing-restore-fixture-$$"
SOURCE_CONTAINER_ID=$(docker create --name "$SOURCE_NAME" --pull never \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=1g,uid=999,gid=999,mode=0700 \
    --tmpfs /var/run/postgresql:rw,nosuid,nodev,size=16m,uid=999,gid=999,mode=0775 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,uid=999,gid=999,mode=1777 \
    --user 999:999 \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    -e POSTGRES_USER=fixture \
    -e POSTGRES_PASSWORD=fixture-not-production \
    -e POSTGRES_DB=fixture \
    "$POSTGRES_IMAGE")
docker start "$SOURCE_CONTAINER_ID" >/dev/null

attempt=0
until docker exec "$SOURCE_CONTAINER_ID" pg_isready \
    -U fixture -d fixture >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "Synthetic restore fixture PostgreSQL did not become ready." >&2
        exit 1
    fi
    sleep 1
done

docker exec "$SOURCE_CONTAINER_ID" psql \
    -U fixture -d fixture -v ON_ERROR_STOP=1 -q -c \
    "CREATE TABLE alembic_version (version_num varchar(64) PRIMARY KEY);
     INSERT INTO alembic_version VALUES ('20260805_task_novel_id');
     CREATE TABLE accounts (id uuid PRIMARY KEY);
     CREATE TABLE projects (id uuid PRIMARY KEY);
     CREATE TABLE scenes (id uuid PRIMARY KEY);
     CREATE TABLE core_entities (id uuid PRIMARY KEY);
     CREATE TABLE async_tasks (id uuid PRIMARY KEY);
     CREATE TABLE account_llm_credentials (id uuid PRIMARY KEY);
     CREATE TABLE import_workflow_runs (id uuid PRIMARY KEY);
     CREATE TABLE interaction_journeys (id uuid PRIMARY KEY);" >/dev/null
docker exec "$SOURCE_CONTAINER_ID" pg_dump \
    -U fixture -d fixture --format custom --file /tmp/fixture.dump

BACKUP_PATH="$TMP_ROOT/backups/synthetic.dump"
docker exec "$SOURCE_CONTAINER_ID" cat /tmp/fixture.dump >"$BACKUP_PATH"
chmod 0600 "$BACKUP_PATH"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$BACKUP_PATH" >"$BACKUP_PATH.sha256"
else
    shasum -a 256 "$BACKUP_PATH" >"$BACKUP_PATH.sha256"
fi
chmod 0600 "$BACKUP_PATH.sha256"
BEFORE_DIGEST=$(awk '{ print $1 }' "$BACKUP_PATH.sha256")

DRILL_OUTPUT=$(ENV_FILE="$TMP_ROOT/.env.production" \
    /bin/sh "$TMP_ROOT/scripts/restore_drill.sh" "$BACKUP_PATH")
AFTER_DIGEST=$(python3 -c \
    'import hashlib, sys; print(hashlib.file_digest(open(sys.argv[1], "rb"), "sha256").hexdigest())' \
    "$BACKUP_PATH")
if [ "$BEFORE_DIGEST" != "$AFTER_DIGEST" ]; then
    echo "Restore drill changed its input dump." >&2
    exit 1
fi
case "$DRILL_OUTPUT" in
    *"sha256=$BEFORE_DIGEST"*"critical_tables=8"*) ;;
    *)
        echo "Restore drill returned an unexpected sanitized summary." >&2
        exit 1
        ;;
esac
if find "$TMP_ROOT/backups" -maxdepth 1 -name 'restore-input-*' -print | grep -q .; then
    echo "Restore drill left a private input snapshot behind." >&2
    exit 1
fi
if docker ps -a --filter name=ai-writing-restore-drill --format '{{.Names}}' | grep -q .; then
    echo "Restore drill left a temporary PostgreSQL container behind." >&2
    exit 1
fi

printf 'Real restore drill integration passed: sha256=%s\n' "$BEFORE_DIGEST"
