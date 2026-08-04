#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$DEPLOY_DIR/.." && pwd)
ENV_FILE=${ENV_FILE:-"$DEPLOY_DIR/.env.production"}
COMPOSE_FILE="$DEPLOY_DIR/compose.production.yml"
STATE_DIR="$DEPLOY_DIR/.state"
BACKUP_DIR="$DEPLOY_DIR/backups"

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

env_value() {
    python3 "$SCRIPT_DIR/validate_env.py" --env "$ENV_FILE" --get "$1"
}

validate_environment() {
    python3 "$SCRIPT_DIR/validate_env.py" --env "$ENV_FILE"
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

load_release_id() {
    if [ -f "$STATE_DIR/current-release" ]; then
        RELEASE_ID=$(sed -n '1p' "$STATE_DIR/current-release")
    else
        RELEASE_ID=$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)
    fi
    case "$RELEASE_ID" in
        *[!0-9a-f]*|"")
            echo "Invalid stored release ID." >&2
            exit 1
            ;;
    esac
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
