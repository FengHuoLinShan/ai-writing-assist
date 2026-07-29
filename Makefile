.PHONY: dev dev-backend dev-worker dev-frontend kill kill-apps test test-collect test-fast test-fast-parallel test-fast-coverage test-v test-integration test-e2e test-postgresql-critical test-real-llm test-real-kimi test-interaction-long-context test-manual test-frontend test-all test-ci eval-corpus eval-fixture-manifest eval-generate eval-judge eval-qc eval-review-export eval-review-import eval-report eval-baseline-check eval-freeze eval-rag-prepare eval-run eval-rag eval-full eval-pilot eval-fast eval-context-planner lint lint-fix format format-fix secret-hygiene prompt-contracts prompt-contracts-json generate-e2e help db migrate doctor doctor-json doctor-llm

ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BACKEND_DIR := $(ROOT_DIR)backend
FRONTEND_DIR := $(ROOT_DIR)frontend-console
BACKEND_FAST_TESTS := modules infrastructure tests/unit tests/integration tests/modules tests/prompt_contracts tests/test_api.py tests/test_outline_api.py tests/test_world_testonly_route.py
BACKEND_COVERAGE_PACKAGES := app core shared infrastructure modules
BACKEND_COVERAGE_ARGS := $(addprefix --cov=,$(BACKEND_COVERAGE_PACKAGES))
BACKEND_REAL_LLM_TESTS := modules/imports/tests/test_real_extraction.py modules/rag/tests/test_real_index.py modules/writing/tests/test_conflict_checks_real_llm.py modules/interaction/tests/test_real_llm.py tests/integration/test_extraction_pipeline.py
BACKEND_REAL_KIMI_TESTS := modules/interaction/tests/test_real_kimi.py
BACKEND_INTERACTION_LONG_CONTEXT_TESTS := tests/e2e/test_interaction_long_context_real_kimi.py
BACKEND_MANUAL_TESTS := $(BACKEND_REAL_LLM_TESTS) tests/e2e/test_extraction_real_file.py tests/e2e/test_outline_generation.py
BACKEND_POSTGRESQL_CRITICAL_TESTS := tests/e2e/test_00_fresh_migrations.py tests/e2e/test_context_retrieval_trace_queries.py tests/e2e/test_context_terminal_concurrency.py tests/e2e/test_interaction_generation_concurrency.py tests/e2e/test_map_editor_revision_concurrency.py tests/e2e/test_map_observation_concurrency.py tests/e2e/test_project_task_gate_concurrency.py tests/e2e/test_scene_memory_checkpoint_concurrency.py tests/e2e/test_smart_dedup_group_savepoint.py tests/e2e/test_task_coalescing_concurrency.py tests/e2e/test_writing_version_concurrency.py
FAST_TEST_TIMEOUT_SECONDS ?= 120
TEST_WORKERS ?= auto

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

test-collect:  ## Verify all backend module tests collect in one pytest session
	cd $(BACKEND_DIR) && pytest modules -q --collect-only

test-fast:  ## Run SQLite-backed tests without external services or source data
	cd $(BACKEND_DIR) && pytest $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" --timeout=$(FAST_TEST_TIMEOUT_SECONDS) $(ARGS)

test-fast-parallel:  ## Run the fast backend layer in isolated pytest-xdist workers
	cd $(BACKEND_DIR) && pytest $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" --timeout=$(FAST_TEST_TIMEOUT_SECONDS) -n $(TEST_WORKERS) --dist=loadscope $(ARGS)

test-fast-coverage:  ## Run the parallel fast layer with the configured coverage gate
	cd $(BACKEND_DIR) && pytest $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" --timeout=$(FAST_TEST_TIMEOUT_SECONDS) -n $(TEST_WORKERS) --dist=loadscope $(BACKEND_COVERAGE_ARGS) --cov-report=term-missing:skip-covered $(ARGS)

test-v:  ## Run the fast backend layer verbosely and stop on the first failure
	cd $(BACKEND_DIR) && pytest -xvs $(BACKEND_FAST_TESTS) -m "not e2e and not real_llm and not external_data" --timeout=$(FAST_TEST_TIMEOUT_SECONDS) $(ARGS)

test-integration:  ## Run the SQLite cross-module integration layer
	cd $(BACKEND_DIR) && pytest tests/integration -m "not e2e and not real_llm and not external_data" $(ARGS)

test-e2e:  ## Run PostgreSQL E2E tests; explicit dedicated E2E_DATABASE_URL required
	cd $(BACKEND_DIR) && RUN_E2E_TESTS=1 pytest tests/e2e -m "not real_llm and not external_data" $(ARGS)

test-postgresql-critical:  ## Run the serial PostgreSQL merge-gate contract subset
	mkdir -p $(BACKEND_DIR)/.test-artifacts
	cd $(BACKEND_DIR) && RUN_E2E_TESTS=1 pytest $(BACKEND_POSTGRESQL_CRITICAL_TESTS) -m "not real_llm and not external_data" --timeout=120 --junitxml=.test-artifacts/postgresql-critical.junit.xml $(ARGS)

test-real-llm:  ## Run SQLite real-LLM acceptance tests explicitly
	cd $(BACKEND_DIR) && RUN_REAL_LLM_TESTS=1 RUN_INTERACTION_REAL_LLM=1 pytest $(BACKEND_REAL_LLM_TESTS) -m real_llm $(ARGS)

test-real-kimi:  ## Run the explicit paid Kimi K3 compatibility gate
	@test "$$RUN_INTERACTION_REAL_KIMI" = "1" || (echo "RUN_INTERACTION_REAL_KIMI=1 is required" >&2; exit 2)
	@test -n "$$KIMI_API_KEY" || (echo "KIMI_API_KEY must be provided in the process environment" >&2; exit 2)
	@test -n "$$DEEPSEEK_API_KEY" || (echo "DEEPSEEK_API_KEY is required for the hot-switch gate" >&2; exit 2)
	cd $(BACKEND_DIR) && pytest infrastructure/llm/test_balance.py::test_kimi_balance_uses_open_platform_available_balance modules/settings/tests/test_llm_connections.py::test_balance_failure_is_auxiliary_and_does_not_disconnect modules/project/tests/test_llm_runtime.py::test_snapshot_provider_survives_active_template_hot_switch modules/project/tests/test_llm_runtime.py::test_snapshot_fails_when_original_provider_connection_was_cleared modules/interaction/tests/test_services.py::test_manual_overview_epoch_rejects_late_automatic_summary modules/interaction/tests/test_tasks.py::test_story_handler_checkpoints_by_size_and_flushes_tail -m "not real_llm and not external_data"
	cd $(BACKEND_DIR) && ENABLE_ACCOUNT_KIMI_K3=1 RUN_REAL_LLM_TESTS=1 pytest $(BACKEND_REAL_KIMI_TESTS) -m real_llm --maxfail=1 $(ARGS)

test-interaction-long-context:  ## Run paid Kimi token calibration and PostgreSQL long-journey gate
	@test "$$RUN_INTERACTION_LONG_CONTEXT_CALIBRATION" = "1" || (echo "RUN_INTERACTION_LONG_CONTEXT_CALIBRATION=1 is required" >&2; exit 2)
	@test "$$KIMI_LONG_CONTEXT_COST_APPROVED" = "1" || (echo "KIMI_LONG_CONTEXT_COST_APPROVED=1 is required" >&2; exit 2)
	@test -n "$$KIMI_API_KEY" || (echo "KIMI_API_KEY must be provided in the process environment" >&2; exit 2)
	@test -n "$$KIMI_CONTEXT_LIMIT_TOKENS" || (echo "KIMI_CONTEXT_LIMIT_TOKENS must match the current official model contract" >&2; exit 2)
	@test -n "$$E2E_DATABASE_URL" || (echo "E2E_DATABASE_URL must target a dedicated PostgreSQL test database" >&2; exit 2)
	cd $(BACKEND_DIR) && pytest modules/interaction/tests/test_services.py -k "extended_context_uses_full_selected_path_without_forced_summary or emergency_summary_resumes_same_story_attempt_without_losing_path or hard_context_budget_fails_closed_and_preserves_selected_path" -m "not real_llm and not external_data" --timeout=120
	cd $(BACKEND_DIR) && ENABLE_ACCOUNT_KIMI_K3=1 RUN_E2E_TESTS=1 RUN_REAL_LLM_TESTS=1 pytest $(BACKEND_INTERACTION_LONG_CONTEXT_TESTS) -m "e2e and real_llm" --maxfail=1 $(ARGS)

test-manual:  ## Run real-source and PostgreSQL/real-LLM acceptance tests explicitly
	cd $(BACKEND_DIR) && RUN_E2E_TESTS=1 RUN_REAL_LLM_TESTS=1 RUN_INTERACTION_REAL_LLM=1 pytest $(BACKEND_MANUAL_TESTS) -m "real_llm or external_data" $(ARGS)

test-frontend:  ## Run frontend tests
	cd $(FRONTEND_DIR) && npm test -- $(FRONTEND_ARGS)

test-all:  ## Run backend tests, then frontend tests
	$(MAKE) test-fast ARGS="$(BACKEND_ARGS)"
	$(MAKE) test-frontend FRONTEND_ARGS="$(FRONTEND_ARGS)"

test-ci: secret-hygiene lint  ## Run the local equivalent of required CI quality jobs
	$(MAKE) test-fast-coverage TEST_WORKERS=$(TEST_WORKERS) ARGS="$(ARGS) -W error::RuntimeWarning"
	$(MAKE) test-frontend FRONTEND_ARGS="$(FRONTEND_ARGS)"

eval-corpus:  ## Build a local corpus manifest without copying source text
	cd $(BACKEND_DIR) && python -m evals.cli corpus-manifest --variant $(or $(VARIANT),pilot) $(if $(OUTPUT),--output $(OUTPUT),)

eval-fixture-manifest:  ## Hash stable writing/outline/world fixtures without payloads
	cd $(BACKEND_DIR) && python -m evals.cli fixture-manifest $(if $(OUTPUT),--output $(OUTPUT),)

eval-generate:  ## Generate candidate semantic-eval cases with local Codex 5.3
	cd $(BACKEND_DIR) && python -m evals.cli generate --suite $(SUITE) --variant $(or $(VARIANT),pilot) --size $(or $(SIZE),20) --output $(OUTPUT) $(if $(CACHE_ONLY),--cache-only,)

eval-judge:  ## Judge a candidate dataset with local Codex 5.3 and cache results
	cd $(BACKEND_DIR) && python -m evals.cli judge $(DATASET) --variant $(or $(VARIANT),pilot) --output $(OUTPUT) $(if $(CACHE_ONLY),--cache-only,)

eval-qc:  ## Run deterministic QC for a local eval dataset
	cd $(BACKEND_DIR) && python -m evals.cli qc $(DATASET) --variant $(or $(VARIANT),pilot) $(if $(OUTPUT),--output $(OUTPUT),)

eval-review-export:  ## Export stratified offline human-review HTML and JSONL
	cd $(BACKEND_DIR) && python -m evals.cli review-export $(DATASET) --variant $(or $(VARIANT),pilot) --html $(HTML) --jsonl $(JSONL) $(if $(CSV),--csv $(CSV),) $(if $(DOUBLE_HTML),--double-html $(DOUBLE_HTML),) $(if $(DOUBLE_JSONL),--double-jsonl $(DOUBLE_JSONL),) $(if $(DOUBLE_CSV),--double-csv $(DOUBLE_CSV),)

eval-review-import:  ## Import human review decisions and calculate agreement
	cd $(BACKEND_DIR) && python -m evals.cli review-import $(DATASET) $(REVIEWS) --reviewer-version $(REVIEWER_VERSION) --output $(OUTPUT) --report $(REPORT) $(if $(ADJUDICATION),--adjudication,)

eval-report:  ## Produce versioned JSON and Markdown dataset reports
	cd $(BACKEND_DIR) && python -m evals.cli report $(DATASET) --variant $(or $(VARIANT),pilot) --dataset-id $(DATASET_ID) --dataset-version $(DATASET_VERSION) $(foreach result,$(RESULTS),--result $(result)) $(foreach reuse,$(RESULT_VERSION_REUSE),--result-version-reuse $(reuse)) $(if $(RAW_REVIEWED_DATASET),--raw-reviewed-dataset $(RAW_REVIEWED_DATASET),) --json $(JSON) --markdown $(MARKDOWN)

eval-baseline-check:  ## Validate existing QC/review decisions without rerunning QC or LLMs
	cd $(BACKEND_DIR) && python -m evals.cli baseline-check $(DATASET) --suite $(or $(SUITE),all) --tier $(or $(TIER),pilot) $(if $(OUTPUT),--output $(OUTPUT),)

eval-freeze:  ## Freeze an accepted-only baseline dataset after deterministic revalidation
	cd $(BACKEND_DIR) && python -m evals.cli freeze $(DATASET) --variant $(or $(VARIANT),pilot) --tier $(or $(TIER),pilot) --dataset-id $(DATASET_ID) --dataset-version $(DATASET_VERSION) --output $(OUTPUT) --manifest $(MANIFEST) --readiness $(READINESS)

eval-rag-prepare:  ## Build a fresh derived RAG index for a baseline chapter range
	cd $(BACKEND_DIR) && python -m evals.cli prepare-rag --novel-id $(NOVEL_ID) --chapter-from $(or $(CHAPTER_FROM),1) --chapter-to $(or $(CHAPTER_TO),60) --content-mode $(or $(CONTENT_MODE),canonical) $(if $(FORCE),--force,) $(if $(OUTPUT),--output $(OUTPUT),)

eval-run:  ## Run one/all official suite runners against an explicitly selected project
	cd $(BACKEND_DIR) && python -m evals.cli run $(DATASET) --suite $(or $(SUITE),all) --novel-id $(NOVEL_ID) --dataset-id $(DATASET_ID) --dataset-version $(DATASET_VERSION) --output-dir $(or $(OUTPUT_DIR),evals/artifacts/results) --baseline-tier $(or $(TIER),pilot) $(if $(ISOLATED_DB),--isolated-db,) $(if $(ALLOW_UNFROZEN),--allow-unfrozen,)

eval-rag:  ## Run the RAG baseline runner against an explicitly selected project
	$(MAKE) eval-run SUITE=rag DATASET=$(DATASET) NOVEL_ID=$(NOVEL_ID) DATASET_ID=$(DATASET_ID) DATASET_VERSION=$(DATASET_VERSION) OUTPUT_DIR=$(OUTPUT_DIR)

eval-full:  ## Run all four baseline runners; requires a disposable isolated database
	$(MAKE) eval-run SUITE=all DATASET=$(DATASET) NOVEL_ID=$(NOVEL_ID) DATASET_ID=$(DATASET_ID) DATASET_VERSION=$(DATASET_VERSION) OUTPUT_DIR=$(OUTPUT_DIR) ISOLATED_DB=1

eval-pilot:  ## Generate/judge the 400-raw-case Pilot with resumable local cache
	cd $(BACKEND_DIR) && python -m evals.cli pilot --variant $(or $(VARIANT),pilot) --stage $(or $(STAGE),all) --output-dir $(or $(OUTPUT_DIR),evals/datasets/local/pilot-v0) $(if $(CACHE_ONLY),--cache-only,)

eval-fast:  ## Run deterministic eval toolkit tests without remote LLM calls
	cd $(BACKEND_DIR) && pytest evals/tests -q

eval-context-planner:  ## Compare task-direct and planner-v1 on accepted RAG cases
	cd $(BACKEND_DIR) && python -m evals.cli context-planner $(or $(DATASET),evals/datasets/local/pilot-v2-work/pilot-v1.1.accepted.jsonl) --novel-id $(NOVEL_ID) --dataset-version $(or $(DATASET_VERSION),pilot-v1.1) --sut-profile $(or $(SUT_PROFILE),local) --output $(or $(OUTPUT),evals/artifacts/results/$(or $(SUT_PROFILE),local)/$(or $(DATASET_VERSION),pilot-v1.1)/context-planner.result.json)

lint:  ## Run ruff linter
	cd $(BACKEND_DIR) && ruff check .

lint-fix:  ## Run ruff auto-fix
	cd $(BACKEND_DIR) && ruff check --fix .

format:  ## Check formatting
	cd $(BACKEND_DIR) && ruff format --check .

format-fix:  ## Auto-format
	cd $(BACKEND_DIR) && ruff format .

secret-hygiene:  ## Reject tracked env files, private keys, and high-confidence credentials
	cd $(BACKEND_DIR) && python -m tools.secret_hygiene

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
