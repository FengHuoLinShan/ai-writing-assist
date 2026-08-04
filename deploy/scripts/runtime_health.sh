#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

validate_environment
load_release_id
HEALTHCHECK_URL=$(env_value HEALTHCHECKS_RUNTIME_PING_URL)
HEALTHCHECK_URL=${HEALTHCHECK_URL%/}
RUNTIME_HEALTH_SUCCEEDED=false

on_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$RUNTIME_HEALTH_SUCCEEDED" != "true" ]; then
        healthcheck_ping "${HEALTHCHECK_URL}/fail" || true
    fi
    exit "$status"
}
trap on_exit EXIT HUP INT TERM

healthcheck_ping "${HEALTHCHECK_URL}/start" || true
wait_for_application_health
compose exec -T api python scripts/check_embedding.py \
    --timeout-seconds 45 \
    --request-timeout-seconds 10 \
    --retry-delay-seconds 5
bash "$SCRIPT_DIR/verify_public.sh" --runtime
healthcheck_ping "$HEALTHCHECK_URL" || true
RUNTIME_HEALTH_SUCCEEDED=true
trap - EXIT HUP INT TERM
