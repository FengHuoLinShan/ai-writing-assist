#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$DEPLOY_DIR/.." && pwd)
ENV_FILE=${ENV_FILE:-"$DEPLOY_DIR/.env.production"}
COMPOSE_FILE="$DEPLOY_DIR/compose.production.yml"
STATE_DIR="$DEPLOY_DIR/.state"
BACKUP_DIR="$DEPLOY_DIR/backups"
FIXED_COMMIT_BUILD_CONTEXT_ROOT=
FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE=
FIXED_COMMIT_BUILD_CONTEXT_PREFIX=

acquire_production_operation_lock() {
    lock_path="$STATE_DIR/production-operation.lock"
    if [ "${AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD+x}" = "x" ]; then
        python3 "$SCRIPT_DIR/production_operation_lock.py" verify \
            "$lock_path" "$AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD"
        return
    fi
    exec python3 "$SCRIPT_DIR/production_operation_lock.py" acquire-wait \
        "$lock_path" 300 /bin/sh "$0" "$@"
}

acquire_runtime_health_lock() {
    lock_path="$STATE_DIR/production-operation.lock"
    if [ "${AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD+x}" = "x" ]; then
        python3 "$SCRIPT_DIR/production_operation_lock.py" verify \
            "$lock_path" "$AI_WRITING_ASSIST_PRODUCTION_OPERATION_LOCK_FD"
        return
    fi
    exec python3 "$SCRIPT_DIR/production_operation_lock.py" acquire-or-skip \
        "$lock_path" /bin/sh "$0" "$@"
}

compose() {
    if [ -n "$FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE" ]; then
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
            -f "$FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE" "$@"
    else
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
}

env_value() {
    python3 "$SCRIPT_DIR/validate_env.py" --env "$ENV_FILE" --get "$1"
}

validate_environment() {
    python3 "$SCRIPT_DIR/validate_env.py" --env "$ENV_FILE"
}

ensure_private_backup_directory() {
    python3 "$SCRIPT_DIR/ensure_private_directory.py" "$BACKUP_DIR"
}

verify_deployment_checkout() {
    if ! python3 - "$REPO_ROOT" <<'PY'
import subprocess
import sys

repo_root = sys.argv[1]
commands = [
    [
        "git",
        "-C",
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=no",
        "--",
        ".",
    ],
    [
        "git",
        "-C",
        repo_root,
        "ls-files",
        "-z",
        "--",
        "deploy/.env.production",
        "deploy/.state",
        ":(glob)deploy/.state/**",
        "deploy/backups",
        ":(glob)deploy/backups/**",
    ],
    [
        "git",
        "-C",
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--ignored",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)deploy/.env.production",
        ":(exclude)deploy/.state",
        ":(exclude)deploy/.state/**",
        ":(exclude)deploy/backups",
        ":(exclude)deploy/backups/**",
    ],
]
try:
    results = [
        subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for command in commands
    ]
except OSError:
    sys.exit(1)
sys.exit(0 if all(result.returncode == 0 and not result.stdout for result in results) else 1)
PY
    then
        echo "Deployment checkout is unsafe or contains unapproved paths." >&2
        return 1
    fi
}

cleanup_fixed_commit_build_context() {
    cleanup_root=$FIXED_COMMIT_BUILD_CONTEXT_ROOT
    cleanup_prefix=$FIXED_COMMIT_BUILD_CONTEXT_PREFIX
    FIXED_COMMIT_BUILD_CONTEXT_ROOT=
    FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE=
    FIXED_COMMIT_BUILD_CONTEXT_PREFIX=

    if [ -z "$cleanup_root" ]; then
        return 0
    fi
    case "$cleanup_root" in
        "$cleanup_prefix"*) ;;
        *)
            echo "Warning: refusing to remove an unexpected fixed-commit build context." >&2
            return 0
            ;;
    esac
    if [ ! -d "$cleanup_root" ] || [ -L "$cleanup_root" ] \
        || [ ! -f "$cleanup_root/.fixed-commit-build-context" ] \
        || [ -L "$cleanup_root/.fixed-commit-build-context" ]; then
        echo "Warning: refusing to remove an invalid fixed-commit build context." >&2
        return 0
    fi
    if ! rm -rf "$cleanup_root"; then
        echo "Warning: unable to remove fixed-commit build context." >&2
    fi
}

prepare_fixed_commit_build_context() {
    target_commit=$1
    if [ -n "$FIXED_COMMIT_BUILD_CONTEXT_ROOT" ]; then
        echo "Fixed-commit build context is already active." >&2
        return 1
    fi

    context_parent=${TMPDIR:-/tmp}
    context_parent=${context_parent%/}
    FIXED_COMMIT_BUILD_CONTEXT_PREFIX="$context_parent/ai-writing-assist-build."
    FIXED_COMMIT_BUILD_CONTEXT_ROOT=$(mktemp -d "${FIXED_COMMIT_BUILD_CONTEXT_PREFIX}XXXXXX") || {
        echo "Unable to create fixed-commit build context." >&2
        FIXED_COMMIT_BUILD_CONTEXT_PREFIX=
        return 1
    }
    case "$FIXED_COMMIT_BUILD_CONTEXT_ROOT" in
        "$FIXED_COMMIT_BUILD_CONTEXT_PREFIX"*) ;;
        *)
            echo "Fixed-commit build context path is unsafe." >&2
            cleanup_fixed_commit_build_context
            return 1
            ;;
    esac
    if [ ! -d "$FIXED_COMMIT_BUILD_CONTEXT_ROOT" ] \
        || [ -L "$FIXED_COMMIT_BUILD_CONTEXT_ROOT" ]; then
        echo "Fixed-commit build context path is unsafe." >&2
        cleanup_fixed_commit_build_context
        return 1
    fi
    chmod 700 "$FIXED_COMMIT_BUILD_CONTEXT_ROOT" || {
        echo "Unable to secure fixed-commit build context." >&2
        cleanup_fixed_commit_build_context
        return 1
    }
    if ! printf '%s\n' fixed-commit-build-context \
        >"$FIXED_COMMIT_BUILD_CONTEXT_ROOT/.fixed-commit-build-context"; then
        echo "Unable to initialize fixed-commit build context." >&2
        cleanup_fixed_commit_build_context
        return 1
    fi
    build_source="$FIXED_COMMIT_BUILD_CONTEXT_ROOT/source"
    if ! mkdir -m 700 "$build_source"; then
        echo "Unable to initialize fixed-commit build source." >&2
        cleanup_fixed_commit_build_context
        return 1
    fi
    archive_path="$FIXED_COMMIT_BUILD_CONTEXT_ROOT/source.tar"
    if ! git -C "$REPO_ROOT" archive --format=tar "$target_commit" >"$archive_path" \
        || ! tar -xf "$archive_path" -C "$build_source" \
        || ! rm -f "$archive_path"; then
        echo "Unable to materialize fixed-commit build source." >&2
        cleanup_fixed_commit_build_context
        return 1
    fi
    FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE="$FIXED_COMMIT_BUILD_CONTEXT_ROOT/compose-build-context.json"
    if ! python3 - "$FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE" "$build_source" <<'PY'
import json
import os
import sys

override_path, source_path = sys.argv[1:]
backend_build = {"context": source_path, "dockerfile": "backend/Dockerfile"}
payload = {
    "services": {
        "api": {"build": backend_build},
        "worker": {"build": backend_build},
        "frontend": {
            "build": {"context": source_path, "dockerfile": "frontend-console/Dockerfile"}
        },
        "migrate": {"build": backend_build},
        "account-maintenance": {"build": backend_build},
    }
}
with open(override_path, "x", encoding="utf-8") as output:
    json.dump(payload, output, separators=(",", ":"))
os.chmod(override_path, 0o600)
PY
    then
        echo "Unable to create fixed-commit build override." >&2
        cleanup_fixed_commit_build_context
        return 1
    fi
}

sha256_digest() {
    digest_path=$1
    if command -v sha256sum >/dev/null 2>&1; then
        digest_output=$(sha256sum "$digest_path") || {
            echo "Unable to calculate SHA-256 with sha256sum." >&2
            return 1
        }
    elif command -v shasum >/dev/null 2>&1; then
        digest_output=$(shasum -a 256 "$digest_path") || {
            echo "Unable to calculate SHA-256 with shasum." >&2
            return 1
        }
    else
        echo "No SHA-256 command is available (need sha256sum or shasum)." >&2
        return 1
    fi
    digest=${digest_output%% *}
    case "$digest" in
        ""|*[!0-9a-f]*)
            echo "SHA-256 command returned an invalid digest." >&2
            return 1
            ;;
    esac
    if [ "${#digest}" -ne 64 ]; then
        echo "SHA-256 command returned an invalid digest." >&2
        return 1
    fi
    printf '%s\n' "$digest"
}

sha256_digest_stream() {
    if command -v sha256sum >/dev/null 2>&1; then
        digest_output=$(sha256sum) || {
            echo "Unable to calculate streamed SHA-256 with sha256sum." >&2
            return 1
        }
    elif command -v shasum >/dev/null 2>&1; then
        digest_output=$(shasum -a 256) || {
            echo "Unable to calculate streamed SHA-256 with shasum." >&2
            return 1
        }
    else
        echo "No SHA-256 command is available (need sha256sum or shasum)." >&2
        return 1
    fi
    digest=${digest_output%% *}
    case "$digest" in
        ""|*[!0-9a-f]*)
            echo "SHA-256 command returned an invalid digest." >&2
            return 1
            ;;
    esac
    if [ "${#digest}" -ne 64 ]; then
        echo "SHA-256 command returned an invalid digest." >&2
        return 1
    fi
    printf '%s\n' "$digest"
}

constant_time_equal() {
    python3 - "$1" "$2" <<'PY'
import hmac
import sys

sys.exit(0 if hmac.compare_digest(sys.argv[1], sys.argv[2]) else 1)
PY
}

verify_backup_checksum() {
    verified_backup_path=$1
    verify_backup_pair_checksum "$verified_backup_path" "${verified_backup_path}.sha256"
}

verify_backup_pair_checksum() {
    verified_backup_path=$1
    checksum_path=$2

    if [ ! -f "$checksum_path" ] || [ -L "$checksum_path" ] || [ ! -s "$checksum_path" ]; then
        echo "Backup checksum sidecar is missing, empty, or not a regular file." >&2
        return 1
    fi

    expected_digest=$(awk '
        /[^[:space:]]/ {
            records += 1
            if (records != 1 || $1 !~ /^[0-9a-f]{64}$/) {
                invalid = 1
            }
            digest = $1
        }
        END {
            if (records != 1 || invalid) {
                exit 1
            }
            print digest
        }
    ' "$checksum_path") || {
        echo "Backup checksum sidecar must contain exactly one lowercase SHA-256 record." >&2
        return 1
    }

    actual_digest=$(sha256_digest "$verified_backup_path") || {
        echo "Unable to calculate backup SHA-256 digest." >&2
        return 1
    }
    if ! constant_time_equal "$expected_digest" "$actual_digest"; then
        echo "Backup checksum does not match the selected backup." >&2
        return 1
    fi
}

verify_postgres_archive() {
    archive_path=$1
    postgres_image=$(env_value POSTGRES_IMAGE) || return 1
    if [ ! -f "$archive_path" ] || [ -L "$archive_path" ] || [ ! -s "$archive_path" ]; then
        echo "PostgreSQL archive is missing, empty, or not a regular file." >&2
        return 1
    fi
    verify_postgres_archive_stream <"$archive_path"
}

verify_postgres_archive_stream() {
    postgres_image=$(env_value POSTGRES_IMAGE) || return 1
    if ! docker image inspect "$postgres_image" >/dev/null 2>&1; then
        docker pull "$postgres_image" >&2 || {
            echo "Unable to pull the PostgreSQL archive verifier image." >&2
            return 1
        }
    fi
    docker run --rm -i --pull never \
        --network none \
        --read-only \
        --cap-drop ALL \
        --security-opt no-new-privileges:true \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
        --cpus 1 \
        --memory 512m \
        --memory-swap 512m \
        --pids-limit 64 \
        --user 65534:65534 \
        --entrypoint pg_restore \
        "$postgres_image" --list >/dev/null
}

deployment_state_operation_id() {
    python3 "$SCRIPT_DIR/deployment_state.py" generate-operation-id
}

write_deployment_state() {
    operation_id=$1
    operation=$2
    current_commit=$3
    previous_commit=$4
    backup_path=$5
    python3 "$SCRIPT_DIR/deployment_state.py" write \
        "$STATE_DIR" "$REPO_ROOT" "$operation_id" "$operation" \
        "$current_commit" "$previous_commit" "$backup_path"
}

deployment_state_matches() {
    current_commit=$1
    operation_id=$2
    python3 "$SCRIPT_DIR/deployment_state.py" matches \
        "$STATE_DIR" "$REPO_ROOT" "$current_commit" "$operation_id"
}

write_first_release_prepared_state() {
    prepared_commit=$1
    python3 "$SCRIPT_DIR/first_release_state.py" write \
        "$STATE_DIR" "$prepared_commit"
}

read_first_release_prepared_commit() {
    python3 "$SCRIPT_DIR/first_release_state.py" read "$STATE_DIR"
}

clear_first_release_prepared_state() {
    python3 "$SCRIPT_DIR/first_release_state.py" clear "$STATE_DIR"
}

validate_deployment_state_contract() {
    contract_marker="$DEPLOY_DIR/deployment-state-contract.version"
    state_helper="$SCRIPT_DIR/deployment_state.py"
    if [ ! -f "$contract_marker" ] || [ -L "$contract_marker" ] \
        || [ "$(wc -l <"$contract_marker")" -ne 1 ] \
        || [ "$(cat "$contract_marker")" != "1" ]; then
        echo "Target commit does not contain a valid deployment state contract." >&2
        return 1
    fi
    if [ ! -f "$state_helper" ] || [ -L "$state_helper" ]; then
        echo "Target commit does not contain the deployment state helper." >&2
        return 1
    fi
    if [ ! -f "$SCRIPT_DIR/first_release_state.py" ] \
        || [ -L "$SCRIPT_DIR/first_release_state.py" ]; then
        echo "Target commit does not contain the first-release recovery helper." >&2
        return 1
    fi
    python3 "$state_helper" generate-operation-id >/dev/null
}

resolve_active_deployment_commit() {
    deployment_state_path="$STATE_DIR/deployment-state.json"
    current_release_path="$STATE_DIR/current-release"
    current_commit_path="$STATE_DIR/current-commit"
    release_exists=false
    commit_exists=false

    if [ -e "$current_release_path" ] || [ -L "$current_release_path" ]; then
        release_exists=true
    fi
    if [ -e "$current_commit_path" ] || [ -L "$current_commit_path" ]; then
        commit_exists=true
    fi

    if [ -e "$deployment_state_path" ] || [ -L "$deployment_state_path" ]; then
        candidate_commit=$(python3 "$SCRIPT_DIR/deployment_state.py" read-current-commit \
            "$STATE_DIR" "$REPO_ROOT") || return 1
    else
        if [ "$release_exists" != "$commit_exists" ]; then
            echo "Deployment state is incomplete; current-release and current-commit must both exist." >&2
            return 1
        fi

        if [ "$release_exists" = "true" ]; then
        if [ ! -f "$current_release_path" ] || [ -L "$current_release_path" ] \
            || [ ! -f "$current_commit_path" ] || [ -L "$current_commit_path" ]; then
            echo "Deployment state files must be regular non-symlink files." >&2
            return 1
        fi
        if [ "$(wc -l <"$current_release_path")" -ne 1 ] \
            || [ "$(wc -l <"$current_commit_path")" -ne 1 ]; then
            echo "Deployment state files must each contain exactly one line." >&2
            return 1
        fi

        state_release=$(cat "$current_release_path")
        state_commit=$(cat "$current_commit_path")
        if ! printf '%s\n' "$state_release" | grep -Eq '^[0-9a-f]{12}$'; then
            echo "Deployment current-release is invalid." >&2
            return 1
        fi
        if ! printf '%s\n' "$state_commit" | grep -Eq '^[0-9a-f]{40}$'; then
            echo "Deployment current-commit is invalid." >&2
            return 1
        fi
        if [ "$(printf '%s' "$state_commit" | cut -c1-12)" != "$state_release" ]; then
            echo "Deployment state release marker does not match current commit." >&2
            return 1
        fi
        candidate_commit=$state_commit
        else
        candidate_commit=$(git -C "$REPO_ROOT" rev-parse --verify 'HEAD^{commit}' 2>/dev/null) || {
            echo "Unable to resolve the first-release deployment HEAD." >&2
            return 1
        }
        fi
    fi

    case "$candidate_commit" in
        *[!0-9a-f]*|"")
            echo "Active deployment commit must be a lowercase hexadecimal SHA." >&2
            return 1
            ;;
    esac
    if [ "${#candidate_commit}" -ne 40 ]; then
        echo "Active deployment commit must be a full 40-character SHA." >&2
        return 1
    fi

    resolved_commit=$(git -C "$REPO_ROOT" rev-parse --verify "${candidate_commit}^{commit}" 2>/dev/null) || {
        echo "Active deployment commit cannot be resolved locally." >&2
        return 1
    }
    if [ "$resolved_commit" != "$candidate_commit" ]; then
        echo "Active deployment commit does not resolve exactly." >&2
        return 1
    fi
    if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$resolved_commit" origin/main; then
        echo "Active deployment commit is not reachable from origin/main." >&2
        return 1
    fi

    printf '%s\n' "$resolved_commit"
}

verify_active_deployment_checkout() {
    active_commit=$1
    checked_out_commit=$(git -C "$REPO_ROOT" rev-parse --verify 'HEAD^{commit}' 2>/dev/null) || {
        echo "Unable to resolve the deployment checkout." >&2
        return 1
    }
    if [ "$checked_out_commit" != "$active_commit" ]; then
        echo "Deployment checkout does not match the finalized active deployment state." >&2
        return 1
    fi
}

migration_guard_state_kind() {
    deployment_state_path="$STATE_DIR/deployment-state.json"
    first_release_prepared_path="$STATE_DIR/first-release-prepared.json"
    current_release_path="$STATE_DIR/current-release"
    current_commit_path="$STATE_DIR/current-commit"
    manifest_exists=false
    release_exists=false
    commit_exists=false

    if [ -e "$deployment_state_path" ] || [ -L "$deployment_state_path" ]; then
        manifest_exists=true
    fi
    if [ -e "$current_release_path" ] || [ -L "$current_release_path" ]; then
        release_exists=true
    fi
    if [ -e "$current_commit_path" ] || [ -L "$current_commit_path" ]; then
        commit_exists=true
    fi
    if [ "$manifest_exists" = true ]; then
        printf '%s\n' active
    elif [ "$release_exists" = true ] && [ "$commit_exists" = true ]; then
        printf '%s\n' active
    elif [ "$release_exists" = false ] && [ "$commit_exists" = false ]; then
        if [ -e "$first_release_prepared_path" ] \
            || [ -L "$first_release_prepared_path" ]; then
            printf '%s\n' first-release-prepared
        else
            printf '%s\n' first-release
        fi
    else
        echo "Deployment state is incomplete; refusing migration compatibility preflight." >&2
        return 1
    fi
}

read_live_migration_revisions() {
    postgres_user=$(env_value POSTGRES_USER) || return 1
    postgres_db=$(env_value POSTGRES_DB) || return 1
    compose exec -T -e PGCONNECT_TIMEOUT=5 postgres psql -w -X -qAt -v ON_ERROR_STOP=1 \
        -U "$postgres_user" -d "$postgres_db" \
        -c "BEGIN READ ONLY; SET LOCAL statement_timeout = '5s'; SELECT version_num FROM public.alembic_version ORDER BY version_num; COMMIT;"
}

read_live_non_system_table_count() {
    postgres_user=$(env_value POSTGRES_USER) || return 1
    postgres_db=$(env_value POSTGRES_DB) || return 1
    compose exec -T -e PGCONNECT_TIMEOUT=5 postgres psql -w -X -qAt -v ON_ERROR_STOP=1 \
        -U "$postgres_user" -d "$postgres_db" \
        -c "BEGIN READ ONLY; SET LOCAL statement_timeout = '5s'; SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema'); COMMIT;"
}

read_live_legacy_map_table_count() {
    postgres_user=$(env_value POSTGRES_USER) || return 1
    postgres_db=$(env_value POSTGRES_DB) || return 1
    compose exec -T -e PGCONNECT_TIMEOUT=5 postgres psql -w -X -qAt -v ON_ERROR_STOP=1 \
        -U "$postgres_user" -d "$postgres_db" \
        -c "BEGIN READ ONLY; SET LOCAL statement_timeout = '5s'; SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND left(table_name, 4) = 'map_' AND left(table_name, 10) <> 'map_atlas_'; COMMIT;"
}

verify_release_migration_compatibility() {
    active_commit=$1
    target_commit=$2
    state_kind=$(migration_guard_state_kind) || return 1

    if [ "$state_kind" = first-release ]; then
        table_count=$(read_live_non_system_table_count) || {
            echo "Unable to verify that the first-release database is empty; confirm Postgres is running/reachable. Release will not start Postgres automatically." >&2
            return 1
        }
        if [ "$table_count" != 0 ]; then
            echo "Deployment state is absent but the live database is not empty; refusing lost-state release." >&2
            return 1
        fi
        return 0
    fi

    if [ "$state_kind" = first-release-prepared ]; then
        prepared_commit=$(read_first_release_prepared_commit) || return 1
        if [ "$prepared_commit" != "$target_commit" ]; then
            echo "An unfinished first release may only retry its prepared fixed SHA: $prepared_commit" >&2
            return 1
        fi
        active_commit=$prepared_commit
    fi

    if [ ! -f "$SCRIPT_DIR/migration_compatibility.py" ] \
        || [ -L "$SCRIPT_DIR/migration_compatibility.py" ]; then
        echo "Migration compatibility helper is missing or unsafe." >&2
        return 1
    fi
    live_revisions=$(read_live_migration_revisions) || {
        echo "Unable to read live Alembic revisions; confirm Postgres is running/reachable and public.alembic_version is valid. Release will not start Postgres automatically." >&2
        return 1
    }
    if [ -z "$live_revisions" ]; then
        echo "Live migration revision output is empty; refusing compatibility preflight." >&2
        return 1
    fi
    if ! printf '%s\n' "$live_revisions" | python3 "$SCRIPT_DIR/migration_compatibility.py" \
        verify "$REPO_ROOT" "$active_commit" "$target_commit"; then
        echo "Target migration graph is incompatible with the deployed database; refusing before checkout." >&2
        echo "Use deploy/scripts/restore.sh <backup.dump> <target-sha> after explicit confirmation." >&2
        return 1
    fi
}

healthcheck_ping() {
    ping_url=$1
    if ! curl --fail --silent --show-error \
        --retry 3 \
        --retry-delay 2 \
        --max-time 15 \
        --output /dev/null \
        "$ping_url"; then
        echo "Warning: monitoring ping failed." >&2
        return 1
    fi
}

frontend_runtime_healthy() {
    contract_marker="$REPO_ROOT/deploy/frontend-asset-contract.version"
    if [ ! -e "$contract_marker" ] && [ ! -L "$contract_marker" ]; then
        frontend_asset_contract=legacy
    else
        if [ ! -f "$contract_marker" ] || [ -L "$contract_marker" ] \
            || [ "$(wc -l <"$contract_marker")" -ne 1 ] \
            || [ "$(cat "$contract_marker")" != "1" ]; then
            echo "Invalid frontend asset contract marker." >&2
            return 1
        fi
        frontend_asset_contract=1
    fi

    if [ "$frontend_asset_contract" = legacy ]; then
        compose exec -T frontend sh -ec '
            output_root=/usr/share/nginx/html
            for asset in \
                / \
                /shared/esc.js \
                /ui/toast.js \
                /ui/modal.js \
                /stateSlices.js \
                /state.js \
                /apiContracts.js \
                /router.js \
                /commands.js
            do
                case "$asset" in
                    /) asset_file="$output_root/index.html" ;;
                    *) asset_file="$output_root$asset" ;;
                esac
                if [ ! -f "$asset_file" ] || [ -L "$asset_file" ]; then exit 1; fi
                wget -q -O /dev/null "http://127.0.0.1:8080$asset"
            done
        ' >/dev/null 2>&1
        return
    fi

    compose exec -T frontend sh -ec '
        output_root=/usr/share/nginx/html
        inventory="$output_root/asset-inventory.txt"
        if [ ! -f "$inventory" ] || [ -L "$inventory" ]; then exit 1; fi
        record_count=$(awk "END { print NR }" "$inventory")
        if [ "$(wc -c <"$inventory")" -gt 65536 ] \
            || [ "$record_count" -gt 512 ]; then exit 1; fi
        allowed_inventory_bytes="
/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        invalid_byte_count=$(LC_ALL=C tr -d "$allowed_inventory_bytes" <"$inventory" | wc -c)
        if [ "$invalid_byte_count" -ne 0 ]; then exit 1; fi
        if grep -q "$(printf "\\r")" "$inventory"; then exit 1; fi
        if sort "$inventory" | uniq -d | grep -q .; then exit 1; fi

        for required in \
            / \
            /index.html \
            /asset-manifest.json \
            /asset-inventory.txt \
            /shared/esc.js \
            /ui/toast.js \
            /ui/modal.js \
            /stateSlices.js \
            /state.js \
            /apiContracts.js \
            /router.js \
            /commands.js
        do
            grep -Fqx "$required" "$inventory"
        done
        grep -Eq "^/assets/[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*\\.js$" "$inventory"

        while IFS= read -r asset || [ -n "$asset" ]; do
            case "$asset" in
                /) ;;
                *) printf "%s\\n" "$asset" | grep -Eq "^/[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$" ;;
            esac
            case "$asset" in
                /) asset_file="$output_root/index.html" ;;
                *) asset_file="$output_root$asset" ;;
            esac
            if [ ! -f "$asset_file" ] || [ -L "$asset_file" ]; then exit 1; fi
            wget -q -O /dev/null "http://127.0.0.1:8080$asset"
        done <"$inventory"
    ' >/dev/null 2>&1
}

worker_runtime_healthy() {
    worker_liveness_contract="$REPO_ROOT/deploy/worker-liveness-contract.version"
    if [ ! -e "$worker_liveness_contract" ] && [ ! -L "$worker_liveness_contract" ]; then
        compose exec -T worker python -c \
            "from pathlib import Path; import sys; argv = Path('/proc/1/cmdline').read_bytes().split(b'\\0'); sys.exit(0 if any(token == b'run_worker.py' or (token.startswith(b'/') and token.endswith(b'/run_worker.py')) for token in argv) else 1)" \
            >/dev/null 2>&1
        return
    fi
    if [ ! -f "$worker_liveness_contract" ] || [ -L "$worker_liveness_contract" ] \
        || [ "$(wc -l <"$worker_liveness_contract")" -ne 1 ] \
        || [ "$(cat "$worker_liveness_contract")" != "1" ]; then
        echo "Invalid worker liveness contract marker." >&2
        return 1
    fi
    compose exec -T worker python infrastructure/tasks/liveness.py \
        >/dev/null 2>&1
}

wait_for_application_health() {
    attempt=0
    until compose exec -T api python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" \
        >/dev/null 2>&1 \
        && frontend_runtime_healthy \
        && worker_runtime_healthy; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 40 ]; then
            return 1
        fi
        sleep 3
    done
}

validate_private_state_directory_if_present() {
    if [ -e "$STATE_DIR" ] || [ -L "$STATE_DIR" ]; then
        python3 "$SCRIPT_DIR/ensure_private_directory.py" "$STATE_DIR"
    fi
}

load_release_id() {
    validate_private_state_directory_if_present || return 1
    active_commit=$(resolve_active_deployment_commit) || return 1
    RELEASE_ID=$(printf '%s' "$active_commit" | cut -c1-12)
    export RELEASE_ID
}

ensure_public_bootstrap() {
    if [ "$(env_value AUTH_MODE)" != "public" ]; then
        return 0
    fi
    bootstrap_status=$(compose run --rm api \
        python scripts/manage_accounts.py status LEGACY-000000)
    case "$bootstrap_status" in
        *"identity=unclaimed"*)
            bootstrap_email=$(env_value BOOTSTRAP_OWNER_EMAIL)
            compose run --rm api \
                python scripts/manage_accounts.py claim-legacy \
                --email "$bootstrap_email"
            ;;
        *"identity=email"*)
            ;;
        *)
            echo "Unexpected bootstrap account state; refusing public startup." >&2
            exit 1
            ;;
    esac
}
