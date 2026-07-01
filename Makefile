.PHONY: dev dev-backend dev-worker dev-frontend kill test test-v lint lint-fix format format-fix help db migrate doctor doctor-json doctor-llm

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BACKEND_DIR := $(ROOT_DIR)backend
FRONTEND_DIR := $(ROOT_DIR)frontend-console

# ─── Full Stack ─────────────────────────────────────

dev: kill-processes db  ## Start all dev services
	@echo "=== Starting all services ==="
	@(cd $(BACKEND_DIR) && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) & backend_pid=$$!; \
	(cd $(BACKEND_DIR) && python run_worker.py --reload) & worker_pid=$$!; \
	(cd $(FRONTEND_DIR) && python -m http.server 8080) & frontend_pid=$$!; \
	trap 'kill $$backend_pid $$worker_pid $$frontend_pid 2>/dev/null || true' INT TERM EXIT; \
	sleep 2; \
	echo ""; \
	echo "=== Services started ==="; \
	echo "  Backend:  http://localhost:8000 (--reload)"; \
	echo "  Frontend: http://localhost:8080"; \
	echo "  Worker:   running with --reload"; \
	echo "  Press Ctrl+C to stop all"; \
	wait

# ─── Individual Services ────────────────────────────

dev-backend:  ## Start backend API server (foreground, --reload)
	cd $(BACKEND_DIR) && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-worker:  ## Start task worker (foreground, --reload)
	cd $(BACKEND_DIR) && python run_worker.py --reload

dev-frontend:  ## Start frontend HTTP server (foreground)
	cd $(FRONTEND_DIR) && python -m http.server 8080

# ─── Database ───────────────────────────────────────

db:  ## Start PostgreSQL (idempotent)
	@if docker inspect ai-novel-db >/dev/null 2>&1; then \
		echo "=== Reusing existing ai-novel-db container ==="; \
		docker start ai-novel-db >/dev/null; \
	else \
		docker compose up -d; \
	fi
	@until docker inspect -f '{{.State.Health.Status}}' ai-novel-db 2>/dev/null | grep -q healthy; do \
		echo "Waiting for ai-novel-db healthcheck..."; \
		sleep 1; \
	done

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

doctor:  ## Run read-only local environment diagnostics
	cd $(BACKEND_DIR) && python scripts/doctor.py

doctor-json:  ## Run doctor with stable JSON output
	cd $(BACKEND_DIR) && python scripts/doctor.py --json

doctor-llm:  ## Run doctor and explicitly contact the LLM provider
	cd $(BACKEND_DIR) && python scripts/doctor.py --llm

kill:  ## Stop all services
	@echo "=== Stopping services ==="
	-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	-pkill -f "run_worker.py" 2>/dev/null || true
	-pkill -f "python -m http.server 8080" 2>/dev/null || true
	-pkill -f "python3 -m http.server 8080" 2>/dev/null || true
	@echo "Done."

kill-processes:
	-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	-pkill -f "run_worker.py" 2>/dev/null || true
	-pkill -f "python -m http.server 8080" 2>/dev/null || true
	-pkill -f "python3 -m http.server 8080" 2>/dev/null || true

# ─── Help ───────────────────────────────────────────

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
