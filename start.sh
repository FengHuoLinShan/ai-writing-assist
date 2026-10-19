#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUTF8=1

if [[ -n "${PYTHON:-}" ]]; then
  exec "$PYTHON" "$ROOT_DIR/desktop/dev.py"
fi
exec make -C "$ROOT_DIR" dev
