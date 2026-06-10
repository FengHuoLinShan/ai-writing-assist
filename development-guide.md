# Development Guide — 开发规则

## Project Overview

AI 长篇小说结构化创作引擎 (AI Novel Structural Engine) v2.0 — a structured creation system for Chinese long-form novels. Backend: Python FastAPI + async SQLAlchemy + PostgreSQL 17 + pgvector + pg_trgm. Frontend: vanilla JS SPA console.

## Commands

### One-command dev start

```bash
make dev                         # Kill old → DB → backend(—reload) + worker(—reload) + frontend
make kill                        # Stop all services
make help                        # List all targets
```

### Individual services

```bash
# Backend
cd backend
pip install -e ".[dev]"          # Install dependencies
uvicorn app.main:app --reload    # Dev server (port 8000)
python run_worker.py --reload    # Task worker with auto-reload

# Database
make db                          # docker compose up -d
make migrate                     # alembic upgrade head

# Testing & linting
make test                        # All tests
make test-v                      # Verbose, stop on first failure
make test ARGS="-k test_create"  # Filter by test name
make lint                        # ruff check
make lint-fix                    # ruff --fix
make format                      # ruff format --check
make format-fix                  # ruff format
```

## Three-Layer Architecture

| Layer | Modules | Responsibility |
|-------|---------|----------------|
| **事实层** (Fact) | project, world, memory | Maintain canonical facts. world unifies CoreEntity + Character + Event + EntityRelation |
| **结构层** (Structure) | outline | Organize facts into executable plot plans (threads → arcs → chapter cards → scene cards) |
| **辅助层** (Support) | rag, context, writing, imports | Retrieval, context compilation, draft writing, file import. infrastructure (tasks/llm) is shared infra |

## Module Structure

```
modules/<name>/
├── README.md        — Responsibility, owned tables, facade, tests
├── contracts.py     — Cross-module data contracts (dataclasses)
├── models.py        — SQLAlchemy ORM model
├── schemas.py       — Pydantic request/response schemas
├── repositories.py  — Data access layer (SQLAlchemy queries)
├── services.py      — Business logic (calls repository)
├── facade.py        — Public cross-module API (thin proxy)
├── api.py           — FastAPI router (thin: validate → delegate)
├── tasks.py         — Async task handler (optional, @task_handler)
└── tests/
    ├── conftest.py  — Module-specific fixtures (SQLite in-memory)
    └── test_*.py    — Per-layer tests
```

## Module Boundary Rules

**Allowed imports:**
- `modules/*` → `core`, `shared`
- `modules/*` → `infrastructure/llm`, `infrastructure/tasks`
- `modules/A` → `modules/B/contracts.py`
- `modules/A` → `modules/B/facade.py`

## Core Infrastructure

- **`core/`**: Config (`config.py`, frozen dataclass, `get_settings()` singleton), Database lifecycle (`database.py`, `DatabaseManager`, `get_db()` dependency), ORM base (`base.py`, UUID/Timestamp/Status mixins), Dependency injection (`dependencies.py`, `DbSession`/`AppSettings` type aliases)
- **`infrastructure/llm/`**: LLM client with OpenAI-compatible provider, retry with exponential backoff, structured JSON output with Pydantic schema validation, streaming support
- **`infrastructure/tasks/`**: Async task system with `@task_handler` registry, status tracking, heartbeat, FOR UPDATE SKIP LOCKED for worker safety
- **`shared/`**: Global enums (`enums.py`), constants (`constants.py`), types (`types.py`), utilities (`utils.py`)

## Database Design Principles

- Candidate-separate-from-canonical: AI output into candidate/proposal tables first
- Status over deletion: Use status field (draft/candidate/canonical/deprecated/ignored/conflicted) instead of hard DELETE
- Prompts merge, data splits: One prompt output contains multiple arrays → stored into separate tables
- JSONB for flex fields: Scene cards in chapter_cards.scene_cards JSONB
- PostgreSQL + pgvector + pg_trgm for vector search, name similarity, dedup

## Key Design Decisions

- **Candidate → Canonical pipeline**: AI output always enters as "candidate"; user must review and promote. No auto-promotion.
- **Facade gate**: Cross-module access only through `facade.py`. Services/repos never imported across modules.
- **Context Budget**: Context Compiler enforces per-category item limits to stay within token budgets.
- **Reveal Levels**: Every entity has visibility/reveal metadata to prevent premature spoilers in LLM prompts.
- **Enums centralized**: All shared enums in `shared/enums.py` to avoid circular imports.
- **Memory proposals only**: AI generates proposals; user confirms before writing to memory_records.
- **Lightweight timeline**: No complex relative-time reasoning, no calendar system, no automatic history simulation.
- **Scene cards in JSONB**: Scene cards live in chapter_cards.scene_cards initially, no separate table until needed.

## AI Development Rules

- When modifying contracts.py, facade.py, API routes, Pydantic schemas, or DB schema: must also update module README, tests, all callers, and docs
- Each module owns its tests. Run that module's tests after modification. Cross-module flows go in tests/integration/
- The system uses 4 core creative prompts (not multi-agent). Tool-specific prompt files may exist for bounded workflows, e.g. `structure_extraction.md` for entity candidate extraction.
- Entity extraction is NOT NER. Extract only "long-term creative assets."

## Frontend Principles

- **中文优先**: All UI text in Chinese. No engineering jargon.
- **命令行风格但易用**: Buttons + keyboard shortcuts + command bar in parallel.
- **纯文字为主**: Tables, tree views, cards, collapsible panels, ASCII maps.
- **低依赖**: Vanilla JS, no framework required, no heavy component libraries.
- **易用性**: Every page has: empty state, help text, action buttons, status labels, error messages, danger confirmation, one-click copy/export, undo last action.
- **XSS防护**: Use textContent, never innerHTML for user/AI content; sanitize Markdown rendering.

## Data Security Rules

- API Keys from environment variables only, never in logs, never returned to frontend
- .env not committed to repo; .env.example provided
- All API requests validated via Pydantic schema
- No raw SQL string concatenation
- Search/sort/filter fields whitelisted
- Pagination on all list endpoints
- File upload: type/size limits, no path traversal, not saved to executable directories
