# Development Guide — 开发规则

## Project Overview

AI 长篇小说结构化创作引擎 (AI Novel Structural Engine) v2.0 — a structured creation system for Chinese long-form novels. Backend: Python FastAPI + async SQLAlchemy + PostgreSQL 17 + pgvector + pg_trgm. Frontend: Vue 3 SFC console with the existing hash router retained as a narrow route-host seam (ADR-0009).

## Commands

### One-command dev start

```bash
make dev                         # Kill old → DB → Alembic head guard → backend/worker/Vite
make kill                        # Stop app services and PostgreSQL
make kill-apps                   # Stop backend, worker, frontend; keep PostgreSQL running
make help                        # List all targets
```

### Individual services

```bash
# Backend
cd backend
pip install -e ".[dev]"          # Install dependencies
python scripts/dev_server.py     # Process-level auto-reload (port 8000)
python run_worker.py --reload    # Task worker with auto-reload
python scripts/check_llm.py      # Sanitized LLM connectivity check
python scripts/manage_accounts.py smtp-smoke --to test@example.com  # SMTP smoke
python scripts/manage_accounts.py claim-legacy --email test@example.com  # 认领存量数据

# Frontend
cd frontend-console
npm install
npm run dev                      # Vite dev server with hot reload (port 8080)
npm run test                     # Vitest unit/component tests
npm run test:watch               # Vitest watch mode
npm run test:e2e                 # Playwright E2E
npm run test:e2e:smoke           # Playwright smoke subset
npm run test:e2e:map             # Complete map regression list; workers=1/retries=0
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:map-perf  # Real map telemetry profile
npm run test:all                 # Vitest, then Playwright

# Database
make db                          # docker compose up -d
make migrate                     # alembic upgrade head (demo schema 历史已压缩；旧开发库可重建)
make schema-check                # Read-only fail-fast check: current DB must be at every Alembic head
./scripts/dev_migrate_worldbuilding_v1.py  # 补齐 Worldbuilding Workspace v1 dev schema

# Local diagnostics
make doctor                      # Read-only local Doctor: env/ports/Docker/API/DB/LLM config
make doctor-json                 # Same diagnostics as stable JSON
make doctor-llm                  # Explicitly includes remote LLM provider connectivity

# Testing & linting
make test                        # Fast backend layer: no PostgreSQL, real LLM, or local corpus
make test-fast                   # Explicit alias for the fast backend layer
make test-fast-parallel TEST_WORKERS=2  # Same fast layer with xdist; CI uses 2 workers
make test-fast-coverage TEST_WORKERS=2  # CI-equivalent fast layer with 85% coverage gate
make test-v                      # Fast layer, verbose, stop on first failure
make test ARGS="-k test_create"  # Filter by test name
make test-integration            # SQLite cross-module integration tests
E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-e2e  # Explicit test DB at Alembic head
E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-postgresql-critical  # Serial PostgreSQL merge-gate subset; retries=0
RUN_E2E_TESTS=1 E2E_DATABASE_URL='<dedicated-postgresql-url>' uv run pytest tests/e2e/test_map_observation_concurrency.py -m "not real_llm and not external_data"  # Map observation row-lock race
RUN_E2E_TESTS=1 E2E_DATABASE_URL='<dedicated-postgresql-url>' python -m pytest tests/e2e/test_map_subsystem_reset_postgresql.py -m "not real_llm and not external_data"  # Map reset dry-run/restore drill
make test-real-llm               # Explicit SQLite real-model acceptance
RUN_INTERACTION_REAL_KIMI=1 KIMI_API_KEY='<temporary-key>' DEEPSEEK_API_KEY='<temporary-key>' make test-real-kimi  # Explicit paid Kimi K3 compatibility gate; enabled only in the test process
RUN_INTERACTION_LONG_CONTEXT_CALIBRATION=1 KIMI_LONG_CONTEXT_COST_APPROVED=1 KIMI_API_KEY='<temporary-key>' KIMI_CONTEXT_LIMIT_TOKENS='<official-limit>' E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-interaction-long-context  # Paid usage calibration + PostgreSQL 530K journey gate
E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-manual REAL_SOURCE_PATH=/abs/path/novel.txt  # Real corpus + PostgreSQL/model acceptance
make test-deploy                 # Deployment static/CLI contracts; no Compose or recovery drill
make test-production-images      # Build pinned production Dockerfiles and run independent image smoke checks
make test-frontend FRONTEND_ARGS="stateTopbarHelp.test.js"  # Frontend Vitest
make audit-backend-deps          # Locked backend audit; all extras, temporary no-fix exceptions re-open on fix
make audit-frontend-deps         # Frontend lockfile audit; high/critical findings fail
make test-all                    # Fast backend layer, then frontend tests
make test-ci TEST_WORKERS=2     # Secret + backend/frontend audit + Ruff + deploy contracts + coverage/RuntimeWarning + Vitest
make secret-hygiene              # Scan tracked/indexed files for credential regressions
make lint                        # ruff check
make lint-fix                    # ruff --fix
make format                      # ruff format --check
make format-fix                  # ruff format
```

Frontend has no independent lint/format dependency in `frontend-console/package.json`; frontend validation remains the Vitest/Playwright scripts above plus `git diff --check`. `npm run build`（vite build）仅作 Vue 构建链冒烟验证；`make test-production-images` 才会实际构建两份生产镜像并检查运行时合同。
`make audit-frontend-deps` uses npm registry/advisory data to check the committed
lockfile and fails only on high/critical findings. It complements, rather than
replaces, the production build and tests; a passing audit does not mean zero risk.

`make audit-backend-deps` uses OSV advisory data against every package in
`backend/uv.lock`, including optional extras. It pins the audit to Python 3.12 on
Linux so local and CI results agree, and uses `--no-build` so metadata-only audit
does not build source distributions. Two eval-only advisories without published
fixes are temporarily marked `--ignore-until-fixed`: DiskCache unsafe pickle
deserialization (`GHSA-w8v5-vhqr-4h9v`) and Ragas multimodal Faithfulness SSRF
(`GHSA-95ww-475f-pr4f`). The latter is not in production and this project uses the
text-only local Codex evaluator, but the eval extra remains trusted/offline-only.
`--ignore-until-fixed` is deliberately not a permanent ignore: a published fix
makes the gate fail again. An audit pass does not prove zero dependency or
supply-chain risk.

`python -m scripts.reset_map_subsystem` 是地图子系统的开发管理预检工具。它只提供
dry-run 和可选 `--backup-restore-drill`，要求显式的预期环境与数据库 fingerprint，
会校验 16 张 `map_*` 表、FK、活跃引用和运行任务。当前 CLI 没有
`--execute` / `--yes` 或目标库删除分支；不得把 dry-run 的 ready 结果解释为已获得清空授权。

GitHub Actions 的后端门禁、前端 Vitest job、等价本地命令和显式验收层边界见
[`testing-guide.md`](testing-guide.md#continuous-integration)。

## Pinned production toolchains

Production Dockerfiles and PostgreSQL service declarations use reviewed image tags plus
immutable SHA-256 digests. The backend image uses Python `3.12.13`, uv `0.11.28`, and
the frontend build uses Node `24.18.0`; `backend/.python-version` and
`frontend-console/.node-version` record the matching local-tooling versions. CI runs on
`ubuntu-24.04` and installs those exact interpreter/tool versions before its relevant
jobs. These pins make build inputs reviewable and repeatable, but do not promise
byte-for-byte identical layers across Docker builders.

Rotate an image only by reviewing a new upstream tag and digest together, then update
the Dockerfile, production/example PostgreSQL declarations, relevant CI service image,
and the associated contract tests in one change. `make test-production-images` is
intentionally outside `make test-ci`: it downloads/builds production images and is too
slow for the normal local fast gate, while GitHub runs it as a separate required job.

Backend reload watches `app/`, `core/`, `shared/`, `infrastructure/`, `modules/`,
`prompts/`, and `alembic/`; worker reload watches the same schema-sensitive paths.
`make dev` compares the database's current Alembic revision set with the migration
script heads after PostgreSQL becomes healthy, and refuses to start app processes
when the local database is behind. If a new migration appears while the reload
supervisors are already running, backend and worker children pause before importing
business runtime state, print the `make migrate` action, and resume automatically
after the database reaches head. The guard is read-only and never creates a version
table, changes its capacity, or applies migrations automatically.

Each Python or prompt Markdown change stops the complete Uvicorn process before
starting a new one. During that short restart window port 8000 is closed instead
of being held by a stale reload parent; wait for `/api/health` to return before
judging the frontend/backend connection.

## Three-Layer Architecture

| Layer | Modules | Responsibility |
|-------|---------|----------------|
| **事实层** (Fact) | project, world, memory | Maintain canonical facts. world unifies CoreEntity + Character + Event + EntityRelation |
| **结构层** (Structure) | outline | Organize facts into executable plot plans (threads → arcs → chapter cards → scene cards) |
| **辅助层** (Support) | rag, context, writing, imports, settings | Retrieval, context compilation, draft writing, file import, and LLM/author preference overrides. infrastructure (tasks/llm) is shared infra |

## Module Structure

```
modules/<name>/
├── README.md        — Responsibility, owned data, stable interface, tests
├── contracts.py     — Cross-module data contracts, when callers need them
├── facade.py        — Public cross-module API, when it adds real leverage
├── models.py        — SQLAlchemy ORM model, when persistent state exists
├── schemas.py       — Pydantic request/response schemas
├── repositories.py  — Data access layer, when persistent state exists
├── services.py      — Business logic
├── api.py           — FastAPI router (thin: validate → delegate)
├── tasks.py         — Async task handler (optional, @task_handler)
└── tests/
    ├── conftest.py  — Module-specific fixtures (SQLite in-memory)
    └── test_*.py    — Per-layer tests
```

Modules choose files by responsibility. Do not create empty contracts or pass-through facades just to match the template.

## Module Boundary Rules

**Allowed imports:**
- `modules/*` → `core`, `shared`
- `modules/*` → `infrastructure/llm`, `infrastructure/tasks`
- `modules/A` → `modules/B/contracts.py`
- `modules/A` → `modules/B/facade.py`
- `modules/A` → DI container port registered by `app.main` / worker startup

**Forbidden in production business code:** cross-module imports of another module's `models.py`, `repositories.py`, or `services.py`.

**Explicit exceptions:**
- A module may test its own `repositories.py` / `services.py` directly when the behavior is internal to that module.
- Test fixtures, Alembic migrations, and ORM metadata registration may import models to build schemas or FK metadata.
- Application composition roots (`app.main`, worker startup) may import implementations for route/task/DI registration only; they must not contain business decisions.

## Architecture Quality Bar

- Prefer deep modules: a small interface should hide meaningful behavior and concentrate change in one place.
- Do not add empty `contracts.py`, pass-through `facade.py`, or DI ports just to satisfy a template.
- Before adding a seam, run the deletion test: if deleting it does not push complexity back into multiple callers, it probably is not earning its keep.
- One adapter is a hypothetical seam; two adapters, a stable cross-module interface, or a clear test substitute make it real.
- Public contract, user-visible behavior, data model, or cross-module call changes require authoritative docs and affected tests to move together.

## Core Infrastructure

- **`core/`**: Config (`config.py`, frozen dataclass, `get_settings()` singleton), Database lifecycle (`database.py`, `DatabaseManager`, `get_db()` dependency), ORM base (`base.py`, UUID/Timestamp/Status mixins), Dependency injection (`container.py` process singleton/transient scopes and shutdown, `dependencies.py` `DbSession`/`AppSettings` type aliases)
- **`infrastructure/llm/`**: LLM client with OpenAI-compatible providers, account-template runtime profiles opened through the project facade, secret-free resumable snapshots, inherited general request budgets (`max_tokens=None` resolves from the client profile; system default `12000`), explicit HTTP transport/proxy controls, retry with exponential backoff, structured JSON output with Pydantic schema validation, streaming support, balance adapters, and sanitized health checks (`GET /api/health/llm`)
- **`infrastructure/tasks/`**: Async task system with `@task_handler` registry, status tracking, heartbeat, FOR UPDATE SKIP LOCKED for worker safety
- **`shared/`**: Global enums (`enums.py`), constants (`constants.py`), types (`types.py`), utilities (`utils.py`)

## Database Design Principles

- Candidate-separate-from-canonical by default: AI output enters candidate/proposal tables first; user-confirmed automated pipelines may write canonical records directly with editable/rollback metadata
- Runtime business deletes prefer status fields (draft/candidate/canonical/deprecated/ignored/conflicted); project permanent delete and demo database rebuilds may hard delete
- Demo-stage schema refactors do not need data-preserving migrations; current Alembic history is a squashed schema initializer, so intermediate demo databases should be recreated instead of upgraded through old revisions
- Prompts merge, data splits: One prompt output contains multiple arrays → stored into separate tables
- JSONB for flex fields where the shape is genuinely unstable; current Scene cards are managed through the `scenes` table, with older JSONB references treated as historical context
- PostgreSQL + pgvector + pg_trgm for vector search, name similarity, dedup

## Key Design Decisions

- **Candidate → Canonical pipeline**: AI output enters candidate by default; user-confirmed automated pipelines may write canonical records with editable/rollback metadata.
- **Stable interface gate**: Cross-module production access goes through contracts/facade or DI ports. Services/repos/models are not imported across business modules; testing/metadata/composition-root exceptions are documented in Module Boundary Rules.
- **Context Budget**: Context Compiler enforces per-category item limits to stay within token budgets.
- **Reveal Levels**: Every entity has visibility/reveal metadata to prevent premature spoilers in LLM prompts.
- **Enums centralized**: All shared enums in `shared/enums.py` to avoid circular imports.
- **Memory event sourcing**: `memory_events` records ordered changes and `memory_snapshots` materializes stage state; the removed `memory_records` table is not a write target.
- **Lightweight timeline**: No complex relative-time reasoning, no calendar system, no automatic history simulation.
- **Scene table**: `scenes` is the active minimal narrative-unit table; `scene_chapter_links` and derived `scene_spans` carry chapter/physical mappings.

## AI Development Rules

- Public contract, user-visible behavior, data model, or cross-module call changes require updating authoritative docs and affected tests. Pure internal rearrangement does not require design-doc churn.
- DB schema refactors may reset the demo database instead of carrying historical migrations; keep ORM/schema/tests/docs in sync
- Each module owns its tests. Run that module's tests after modification. Cross-module flows go in tests/integration/
- The system uses controlled structured LLM steps, not an autonomous multi-agent runtime. The active Prompt and contract catalogue is `docs/prompts/Prompt体系设计.md`.
- Entity extraction is NOT NER. Extract only "long-term creative assets."

## Frontend Principles

- **中文优先**: All UI text in Chinese. No engineering jargon.
- **命令行风格但易用**: Buttons + keyboard shortcuts + command bar in parallel.
- **纯文字为主**: Tables, tree views, cards, collapsible panels, ASCII maps.
- **低依赖**: Vue 3 SFC 是当前前端栈；通过 `vue/mountIsland.js` + `vue/bridge/` 接入既有 hash router 与基础设施。不得另引入第二套前端栈或重型组件库，除非获得用户确认或 ADR。
- **易用性**: Every workflow needs clear empty/error states and danger confirmation. Copy/export/undo are added only where the workflow naturally needs them.
- **XSS防护**: Never write unescaped user/AI/API dynamic content into `innerHTML`; static templates and `esc()`-escaped dynamic content are acceptable.

## Data Security Rules

- API Keys come from environment defaults or project-level write-only LLM settings; never log keys and never return raw keys to frontend
- .env not committed to repo; .env.example provided
- LLM transport must not implicitly depend on system proxy state; use `LLM_TRUST_ENV` / `LLM_PROXY_URL` and verify with `python scripts/check_llm.py`
- All API requests validated via Pydantic schema
- No raw SQL string concatenation
- Search/sort/filter fields whitelisted
- Pagination on all list endpoints
- File upload: type/size limits, no path traversal, not saved to executable directories
