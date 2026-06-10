# CLAUDE.md

## Essential commands

| Action | Command |
|--------|---------|
| Start all services | `make dev` |
| Stop all services | `make kill` |
| Backend tests | `make test` or `make test-v` |
| Single test | `make test ARGS="-k test_name -xvs"` |
| Frontend tests | `(cd frontend-console && npm test)` |
| Lint / format check | `make lint` / `make format` |
| DB up + migrate | `make db && make migrate` |
| Install backend | `pip install -e ".[dev]"` from `backend/` |

See `development-guide.md` for full reference, `testing-guide.md` for test conventions.

## Architecture

Two-package layout: `backend/` (FastAPI) + `frontend-console/` (vanilla JS, zero build step, zero framework, no TypeScript).

**8 active backend modules** (`app/main.py:293-301`): `project`, `imports`, `world`, `memory`, `outline`, `rag`, `context`, `writing`. Removed: `geo`, `review`, `character`, `timeline`. Character lives in `modules/world`. `infrastructure/tasks/` is a shared infra layer, not a business module.

Each module: `contracts.py` → `models.py` → `repositories.py` → `services.py` → `api.py`; tasks in `tasks.py`. `facade.py` is optional — memory/outline modules omit it, routing directly through `api.py` → `services.py`.

**Cross-module imports (strict):** Only `contracts.py` and `facade.py` — never `models.py`, `repositories.py`, or `services.py`. Facade/API are thin delegators with no complex business logic.

**Entrypoints:**
- Backend API: `backend/app/main.py` (FastAPI app, run via `uvicorn app.main:app`)
- Worker: `backend/run_worker.py` (async task worker, PostgreSQL-based queue, no Redis/Celery)
- Frontend: `frontend-console/index.html` (serve via `python -m http.server 8080`)

## Domain conventions

- **Candidate → Canonical**: AI output enters as "candidate"; user reviews and promotes. No auto-promotion.
- **Status over deletion**: Use status fields (`draft`/`candidate`/`canonical`/`deprecated`/`ignored`/`conflicted`), never hard DELETE.
- **Entity extraction ≠ NER**: Extract only long-term creative assets (not passersby, generic items, pronouns, one-shot elements).
- **Aliases**: Stored inline in `core_entities.aliases` JSONB, tagged `alias_of_existing`.
- **Scene cards**: Stored in `chapter_cards.scene_cards` JSONB (no separate table).
- **novel_id isolation**: Every API enforces cross-novel access control at service layer.
- **No innerHTML**: Use `textContent` or `esc()` (defined in `frontend-console/state.js:6`) for user/AI content.
- **No eval/exec on LLM output**.
- **No complex multi-agent**: 4 core creative prompts + 3 tool extraction prompts only.
- **API keys**: Env vars only, never logged or returned to frontend.
- **Merge/delete/deprecate**: Must have user confirmation before executing.
- **File upload**: Whitelist formats only, ≤50MB, no path traversal.

## Testing

| Context | DB | Pattern |
|---------|----|---------|
| Unit/Integration | SQLite in-memory (`aiosqlite`) | Fresh tables per test session |
| E2E | Real PostgreSQL | Docker PG via `docker compose` |

- **Test through facades**: Prefer `from modules.x.facade import func` over importing internals.
- **Import FK models**: Each test `conftest.py` must import all models with FK dependencies (always `modules.project.models`).
- **Mock-free E2E**: `tests/e2e/test_extraction_real_file.py` uses real LLM calls.
- **pytest-asyncio**: `asyncio_mode = "auto"` in `pyproject.toml`.
- **Run affected modules before merge**: "不跑受影响模块测试不合并".

## Toolchain quirks

- **Ruff**: line-length=90, target py312, rules E/F/W/I/N/UP, **double quotes**.
- **No mypy/pyright** configured — only ruff for static analysis.
- **Alembic**: git-revision-hash prefix naming (auto-generated).
- **No `.env` committed**: Copy `backend/.env.example`.
- **pgvector**: Vector fields stored as JSON-serialized text in SQLite test mode.

## Naming (non-obvious)

| Convention | Rule |
|------------|------|
| Python enum members | `lowercase` (StrEnum member name = DB value) |
| Python module-level logger | `logger` (no underscore prefix) |
| JS private methods | `_camelCase` (internal only, public via non-underscore methods) |
| JS View files | `PascalCaseView.js` (matches exported object name) |

## Agent skills

### Structure docs update

Auto-sync design docs on git push. See `docs/skills/structure-docs-update.md`.

### Issue tracker

Issues and PRDs live as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles use their default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. See `docs/agents/domain.md`.

## Meta

- Keep AGENTS.md ↔ CLAUDE.md equivalent prohibitions in sync.
- After `git push`, run `/structure-docs-update` to sync design docs.
- Skills: `/tdd` for code dev (RED→GREEN→REFACTOR), `/grill-with-docs` for design decisions.
