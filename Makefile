.PHONY: dev dev-backend dev-worker dev-frontend kill kill-apps test test-fast test-v test-integration test-e2e test-real-llm test-manual test-frontend test-all lint lint-fix format format-fix prompt-contracts prompt-contracts-json generate-e2e help db migrate doctor doctor-json doctor-llm

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BACKEND_DIR := $(ROOT_DIR)backend
FRONTEND_DIR := $(ROOT_DIR)frontend-console
BACKEND_FAST_TESTS := modules infrastructure tests/unit tests/integration tests/modules tests/prompt_contracts tests/test_api.py tests/test_outline_api.py tests/test_world_testonly_route.py
BACKEND_REAL_LLM_TESTS := modules/imports/tests/test_real_extraction.py modules/rag/tests/test_real_index.py modules/writing/tests/test_conflict_checks_real_llm.py tests/integration/test_extraction_pipeline.py
BACKEND_MANUAL_TESTS := $(BACKEND_REAL_LLM_TESTS) tests/e2e/test_extraction_real_file.py tests/e2e/test_outline_generation.py

# ─── Full Stack ─────────────────────────────────────

dev:  ## Start all dev services
	python scripts/dev_stack.py start

# ─── Individual Services ────────────────────────────

dev-backend:  ## Start backend API server (foreground, --reload)
	cd $(BACKEND_DIR) && python scripts/dev_server.py --host 0.0.0.0 --port 8000

dev-worker:  ## Start task worker (foreground, --reload)
	cd $(BACKEND_DIR) && python run_worker.py --reload

dev-frontend:  ## Start frontend Vite dev server (foreground, hot reload)
	cd $(FRONTEND_DIR) && FRONTEND_PORT=8080 npm run dev

# ─── Database ───────────────────────────────────────

db:  ## Start PostgreSQL (idempotent)
	python scripts/dev_stack.py start-db

migrate:  ## Run database migrations
	cd $(BACKEND_DIR) && alembic upgrade head

# ─── Testing & Linting ──────────────────────────────

test: test-fast  ## Run the fast backend test layer

test-fast:  ## Run SQLite-backed tests without external services or source data
	cd $(BACKEND_DIR) && pytest $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" $(ARGS)

test-v:  ## Run the fast backend layer verbosely and stop on the first failure
	cd $(BACKEND_DIR) && pytest -xvs $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" $(ARGS)

test-integration:  ## Run the SQLite cross-module integration layer
	cd $(BACKEND_DIR) && pytest tests/integration -m "not e2e and not real_llm and not external_data" $(ARGS)

test-e2e:  ## Run PostgreSQL E2E tests; database and migrations are required
	cd $(BACKEND_DIR) && RUN_E2E_TESTS=1 pytest tests/e2e -m "not real_llm and not external_data" $(ARGS)

test-real-llm:  ## Run SQLite real-LLM acceptance tests explicitly
	cd $(BACKEND_DIR) && RUN_REAL_LLM_TESTS=1 pytest $(BACKEND_REAL_LLM_TESTS) -m real_llm $(ARGS)

test-manual:  ## Run real-source and PostgreSQL/real-LLM acceptance tests explicitly
	cd $(BACKEND_DIR) && RUN_E2E_TESTS=1 RUN_REAL_LLM_TESTS=1 pytest $(BACKEND_MANUAL_TESTS) -m "real_llm or external_data" $(ARGS)

test-frontend:  ## Run frontend tests
	cd $(FRONTEND_DIR) && npm test -- $(FRONTEND_ARGS)

test-all:  ## Run backend tests, then frontend tests
	cd $(BACKEND_DIR) && pytest $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" $(BACKEND_ARGS)
	cd $(FRONTEND_DIR) && npm test -- $(FRONTEND_ARGS)

lint:  ## Run ruff linter
	cd $(BACKEND_DIR) && ruff check .

lint-fix:  ## Run ruff auto-fix
	cd $(BACKEND_DIR) && ruff check --fix .

format:  ## Check formatting
	cd $(BACKEND_DIR) && ruff format --check .

format-fix:  ## Auto-format
	cd $(BACKEND_DIR) && ruff format .

prompt-contracts:  ## Check prompt contracts
	cd $(BACKEND_DIR) && python -m tools.prompt_contracts check

prompt-contracts-json:  ## Check prompt contracts with stable JSON output
	cd $(BACKEND_DIR) && python -m tools.prompt_contracts check --json

generate-e2e:  ## Run Generation Center Playwright E2E from frontend project config
	cd $(FRONTEND_DIR) && BACKEND_PORT=18000 FRONTEND_PORT=18080 npx playwright test e2e/generate.spec.js

# ─── Utilities ──────────────────────────────────────

doctor:  ## Run read-only local environment diagnostics
	cd $(BACKEND_DIR) && python scripts/doctor.py

doctor-json:  ## Run doctor with stable JSON output
	cd $(BACKEND_DIR) && python scripts/doctor.py --json

doctor-llm:  ## Run doctor and explicitly contact the LLM provider
	cd $(BACKEND_DIR) && python scripts/doctor.py --llm

kill:  ## Stop all dev services, including PostgreSQL
	@echo "=== Stopping services ==="
	python scripts/dev_stack.py stop
	@echo "Done."

kill-apps:  ## Stop backend, worker, and frontend only
	@echo "=== Stopping app services ==="
	python scripts/dev_stack.py stop-apps
	@echo "Done."

# ─── Help ───────────────────────────────────────────

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
