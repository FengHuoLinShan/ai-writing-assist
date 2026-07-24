#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

validate_environment
load_release_id
HEALTHCHECK_URL=$(env_value HEALTHCHECKS_MAINTENANCE_PING_URL)
HEALTHCHECK_URL=${HEALTHCHECK_URL%/}
MAINTENANCE_SUCCEEDED=false

on_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$MAINTENANCE_SUCCEEDED" != "true" ]; then
        healthcheck_ping "${HEALTHCHECK_URL}/fail" || true
    fi
    exit "$status"
}
trap on_exit EXIT HUP INT TERM

healthcheck_ping "${HEALTHCHECK_URL}/start" || true
compose --profile ops run --rm account-maintenance
healthcheck_ping "$HEALTHCHECK_URL" || true
MAINTENANCE_SUCCEEDED=true
trap - EXIT HUP INT TERM
