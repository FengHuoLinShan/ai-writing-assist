#!/bin/bash
# E2E test server starter: backend + frontend
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../../backend" && python scripts/dev_server.py --host 0.0.0.0 --port "${BACKEND_PORT:-8000}" &
echo $! > /tmp/e2e-backend.pid
cd "$SCRIPT_DIR/.." && FRONTEND_PORT="${FRONTEND_PORT:-8080}" npm run dev &
echo $! > /tmp/e2e-frontend.pid
wait
