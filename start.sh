#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend-console"

echo "=== 停止旧进程 ==="

# 杀后端 (uvicorn)
pkill -f "uvicorn app.main:app" 2>/dev/null || true

# 杀前端 HTTP 服务 (python3 http.server)
pkill -f "python3 -m http.server 8080" 2>/dev/null || true

# 确保端口已释放
for port in 8000 8080; do
  for i in 1 2 3; do
    if ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
done

echo "=== 启动数据库 (Docker) ==="
cd "$ROOT_DIR"
docker compose up -d 2>&1 | grep -v "already exist" || true

echo "=== 启动后端 (uvicorn) ==="
cd "$BACKEND_DIR"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
sleep 3

echo "=== 启动前端 (HTTP) ==="
cd "$FRONTEND_DIR"
python3 -m http.server 8080 &
sleep 1

echo ""
echo "=== 检查状态 ==="
if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
  echo "[OK] 后端: http://localhost:8000 (已连接)"
else
  echo "[FAIL] 后端未响应"
fi

if curl -sf http://localhost:8080 > /dev/null 2>&1; then
  echo "[OK] 前端: http://localhost:8080"
else
  echo "[FAIL] 前端未响应"
fi
