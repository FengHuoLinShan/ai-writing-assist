# Development Guide — 开发规则

## Project Overview

AI 长篇小说结构化创作引擎 (AI Novel Structural Engine) v2.0 — a structured creation system for Chinese long-form novels. Backend: Python FastAPI + async SQLAlchemy + PostgreSQL 17 + pgvector + pg_trgm. Frontend: vanilla JS SPA console.

## Commands

### One-command dev start

```bash
make dev                         # Kill old → DB → backend reload + worker reload + Vite frontend HMR
make kill                        # Stop app services and PostgreSQL
make kill-apps                   # Stop backend, worker, frontend; keep PostgreSQL running
make help                        # List all targets
```

### Individual services

```bash
# Backend
cd backend
pip install -e ".[dev]"          # Install dependencies
python scripts/dev_server.py     # Dev server with auto-reload (port 8000)
python run_worker.py --reload    # Task worker with auto-reload
python scripts/check_llm.py      # Sanitized LLM connectivity check

# Frontend
cd frontend-console
npm install
npm run dev                      # Vite dev server with hot reload (port 8080)
npm run test                     # Vitest unit/component tests
npm run test:watch               # Vitest watch mode
npm run test:e2e                 # Playwright E2E
npm run test:e2e:smoke           # Playwright smoke subset
npm run test:all                 # Vitest, then Playwright

# Database
make db                          # docker compose up -d
make migrate                     # alembic upgrade head (demo schema 历史已压缩；旧开发库可重建)
./scripts/dev_migrate_worldbuilding_v1.py  # 补齐 Worldbuilding Workspace v1 dev schema

# Local diagnostics
make doctor                      # Read-only local Doctor: env/ports/Docker/API/DB/LLM config
make doctor-json                 # Same diagnostics as stable JSON
make doctor-llm                  # Explicitly includes remote LLM provider connectivity

# Testing & linting
make test                        # Fast backend layer: no PostgreSQL, real LLM, or local corpus
make test-fast                   # Explicit alias for the fast backend layer
make test-v                      # Fast layer, verbose, stop on first failure
make test ARGS="-k test_create"  # Filter by test name
make test-integration            # SQLite cross-module integration tests
make test-e2e                    # PostgreSQL E2E; database and Alembic head are required
make test-real-llm               # Explicit SQLite real-model acceptance
make test-manual REAL_SOURCE_PATH=/abs/path/novel.txt  # Real corpus + PostgreSQL/model acceptance
make test-frontend FRONTEND_ARGS="stateTopbarHelp.test.js"  # Frontend Vitest
make test-all                    # Fast backend layer, then frontend tests
make lint                        # ruff check
make lint-fix                    # ruff --fix
make format                      # ruff format --check
make format-fix                  # ruff format
```

Frontend currently has no build script and no independent lint/format dependency in `frontend-console/package.json`; frontend validation remains the Vitest/Playwright scripts above plus `git diff --check`.

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
- **`infrastructure/llm/`**: LLM client with OpenAI-compatible provider, project-level profile helpers, inherited general request budgets (`max_tokens=None` resolves from the client profile; system default `12000`), explicit HTTP transport/proxy controls, retry with exponential backoff, structured JSON output with Pydantic schema validation, streaming support, and sanitized health checks (`GET /api/health/llm`)
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
- **低依赖**: Vanilla JS by default. New frontend stack or heavy component libraries require user/ADR approval.
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
