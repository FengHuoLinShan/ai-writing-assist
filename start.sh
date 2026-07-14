#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python}"

echo "start.sh is a compatibility entrypoint; starting the managed dev stack." >&2
exec "$PYTHON_BIN" "$ROOT_DIR/scripts/dev_stack.py" start
