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
    exec python3 "$SCRIPT_DIR/production_operation_lock.py" acquire \
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

constant_time_equal() {
    python3 - "$1" "$2" <<'PY'
import hmac
import sys

sys.exit(0 if hmac.compare_digest(sys.argv[1], sys.argv[2]) else 1)
PY
}

verify_backup_checksum() {
    verified_backup_path=$1
    checksum_path="${verified_backup_path}.sha256"

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

write_state_file() {
    state_file=$1
    state_value=$2
    state_directory=$(dirname "$state_file")
    state_name=$(basename "$state_file")

    mkdir -p "$state_directory"
    state_temp=$(mktemp "$state_directory/.${state_name}.tmp.XXXXXX") || return 1
    if ! printf '%s\n' "$state_value" >"$state_temp"; then
        rm -f "$state_temp"
        return 1
    fi
    if ! mv -f "$state_temp" "$state_file"; then
        rm -f "$state_temp"
        return 1
    fi
}

resolve_active_deployment_commit() {
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
