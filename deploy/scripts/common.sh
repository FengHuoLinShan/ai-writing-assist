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
                "$bootstrap_email"
            ;;
        *"identity=email"*)
            ;;
        *)
            echo "Unexpected bootstrap account state; refusing public startup." >&2
            exit 1
            ;;
    esac
}
