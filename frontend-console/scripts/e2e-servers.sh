#!/bin/bash
# E2E test server starter: backend + frontend
cd "$(dirname "$0")/../backend" && python -m app.main &
echo $! > /tmp/e2e-backend.pid
cd "$(dirname "$0")" && python -m http.server 8080 &
echo $! > /tmp/e2e-frontend.pid
wait
