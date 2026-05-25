.PHONY: dev dev-backend dev-worker dev-frontend kill test test-v lint lint-fix format format-fix help db migrate

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BACKEND_DIR := $(ROOT_DIR)backend
FRONTEND_DIR := $(ROOT_DIR)frontend-console

# ─── Full Stack ─────────────────────────────────────

dev: kill-processes db  ## Start all dev services
	@echo "=== Starting all services ==="
	@cd $(BACKEND_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
	@sleep 2
	@cd $(BACKEND_DIR) && python run_worker.py --reload &
	@sleep 1
	@cd $(FRONTEND_DIR) && python3 -m http.server 8080 &
	@sleep 1
	@echo ""
	@echo "=== Services started ==="
	@echo "  Backend:  http://localhost:8000 (--reload)"
	@echo "  Frontend: http://localhost:8080"
	@echo "  Worker:   running with --reload"
	@echo "  Run 'make kill' to stop all"

# ─── Individual Services ────────────────────────────

dev-backend:  ## Start backend API server (foreground, --reload)
	cd $(BACKEND_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-worker:  ## Start task worker (foreground, --reload)
	cd $(BACKEND_DIR) && python run_worker.py --reload

dev-frontend:  ## Start frontend HTTP server (foreground)
	cd $(FRONTEND_DIR) && python3 -m http.server 8080

# ─── Database ───────────────────────────────────────

db:  ## Start PostgreSQL (idempotent)
	docker compose up -d

migrate:  ## Run database migrations
	cd $(BACKEND_DIR) && alembic upgrade head

# ─── Testing & Linting ──────────────────────────────

test:  ## Run all tests
	cd $(BACKEND_DIR) && pytest $(ARGS)

test-v:  ## Run tests verbosely (stop on first failure)
	cd $(BACKEND_DIR) && pytest -xvs $(ARGS)

lint:  ## Run ruff linter
	cd $(BACKEND_DIR) && ruff check .

lint-fix:  ## Run ruff auto-fix
	cd $(BACKEND_DIR) && ruff check --fix .

format:  ## Check formatting
	cd $(BACKEND_DIR) && ruff format --check .

format-fix:  ## Auto-format
	cd $(BACKEND_DIR) && ruff format .

# ─── Utilities ──────────────────────────────────────

kill:  ## Stop all services
	@echo "=== Stopping services ==="
	-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	-pkill -f "run_worker.py" 2>/dev/null || true
	-pkill -f "python3 -m http.server 8080" 2>/dev/null || true
	@echo "Done."

kill-processes:
	-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	-pkill -f "run_worker.py" 2>/dev/null || true
	-pkill -f "python3 -m http.server 8080" 2>/dev/null || true

# ─── Help ───────────────────────────────────────────

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
