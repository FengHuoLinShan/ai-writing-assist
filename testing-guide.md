# Testing Guide — 测试与 Review 规则

## Review Severity Levels

### P0 — Blocking (must fix before merge)

- AI output writes canonical without a user-confirmed automated pipeline, provenance, editable/rollback metadata, or tests
- API allows cross-novel_id data read/write
- SQL injection, XSS, API key leakage, arbitrary file read/write
- Prompt injection triggers dangerous backend operations
- author_only / hidden_truth exposed in character-perspective context
- Context Compiler has no budget control, dumps entire DB
- Dangerous operations (merge/delete/deprecate) have no confirmation
- LLM output not validated before insert

### P1 — Must fix before release

- Production module directly imports another module's models/repositories/services
- Context output too long, no budget control, unclear focus
- Candidates lack importance_score or suggested_action
- Memory proposals lack source, confidence, confirmation entry point
- RAG only does vector search, no hybrid/keyword/filter support
- Frontend only supports command bar, no button entry points
- Missing module-level basic tests
- Review only checks format, not logical risks

### P2 — Recommend optimize

- Layout polish, help text completeness, filter richness
- Command coverage, copy/export completeness, log detail

## Per-Module Tests (every module)

Three layers:
- **Repository**: basic CRUD, not found, empty update, pagination
- **Service**: business logic happy path, exception paths (not found → 404, invalid UUID → 422)
- **API** (via `tests/conftest.py` `async_client`): HTTP happy path + error path

### Test setup pattern

Use SQLite in-memory for tests. Each module's `tests/conftest.py` must create its own `db_session` fixture:

```python
# conftest.py must import all ORM models this module depends on
import modules.project.models  # noqa: F401 — FK to projects.id
import modules.other.models    # noqa: F401

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, ...]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
```

### Test import convention

跨模块行为测试应优先通过 public 接口（facade + contracts / API / DI port）进行，而非直接 import 其他模块内部实现：

```
✅ 推荐: from modules.xxx.facade import some_function
❌ 避免: from modules.other.repositories import SomeRepository
❌ 避免: from modules.other.services import SomeService
```

理由：
- **测试验证的是行为而非实现** — facade 是稳定的公共接口，内部重构不影响测试
- **跨模块测试穿过稳定接口** — 调用方不应知道另一个模块的 repository/service 形状
- **本模块内部行为可以直接测** — repository 的复杂查询、service 状态机、错误路径和事务边界属于本模块实现，直接 import 本模块内部是可接受的
- **metadata import 是例外** — fixture / conftest 为注册 FK 模型导入 `modules.project.models` 等模型，不代表业务代码可跨模块依赖内部实现

Key points:
- All ORM models with FK dependencies must be imported to register in `Base.metadata`
- `NovelMixin` references `projects.id` → always import `modules.project.models`
- `WritingDraft` references `chapter_cards.id` → import `modules.outline.models`
- Each test gets a fresh DB (tables created per session)

### Future subpackage test paths

`imports` and `world` may later split large internal service directories into subpackages such as `imports/parsing/`, `imports/workflow/`, `imports/entity_extraction/`, `imports/scene/` or `world/services/core/`, `world/services/map/`, `world/services/worldbuilding/`. When that happens, tests may follow the owning subpackage path to keep fixtures close to the implementation.

This does not relax module boundaries: cross-module behavior tests still go through facade/contracts/API/DI port, and production code still must not import another module's repositories/services/models directly.

## Key Integration Tests (in `tests/integration/`)

1. **Candidate/proposal review**: input text → generate candidates/proposals → dedup → confirm alias or preserve canonical auto-ingest provenance
2. **Character knowledge boundary**: character's unknown info not in compiled context
3. **Chapter card generation**: schema validation passes, contains goal/conflict/must_not_happen/hook
4. **Structure review**: detects early reveal of hidden_truth
5. **Novel_id isolation**: project A API cannot read project B objects
6. **XSS protection**: `<script>` tags display as text, not executed
7. **Deep import Phase 2b alias/relation extraction**: Scene text + working entity index → append candidate alias metadata inline and create candidate relations without creating new entities. Required coverage:
   - schema normalization for alias confidence/type and relation strength
   - working index includes only `canonical` / `draft` / `candidate`, never `deprecated` / `ignored`
   - alias append is novel-scoped, normalized, idempotent, and stores `status/source/workflow_id/scene_id/confidence/quote/needs_review`
   - unresolved relation endpoints are skipped; created relations use `status="candidate"`
   - single-scene Phase 2b failures mark degraded diagnostics without aborting Phase 2a output
   - manual `world_alias_relation_extraction` tasks require `novel_id` and invoke the DI handler with chapter range / scene ids
   - frontend world object auto-extract panel exposes the secondary “补抽别名/关系” entry and disables it while extraction is running

## Security Tests

- SQL injection search strings
- Cross-novel_id access
- XSS text display
- Oversized input
- Invalid enum values
- LLM output invalid JSON
- RAG top_k overflow

## Code Review Checklist

当进行 code review 时，检查以下常见错误：

### Python 陷阱
- `importance or 0.5` — 0.0 是 falsy，应使用 `is not None`
- SQLAlchemy ORM 模型上没有的属性（如 `entity.aliases` 不存在于 WorldEntity）
- `except Exception:` 吞掉数据库 flush 失败导致 session 中毒
- `dict.get("key", default)` 中 default 表达式可能被意外求值

### 跨模块
- 模块 API 是否验证 novel_id 隔离
- facade 是否导出所有新增函数到 `__init__.py`
- 新模块是否在 `app/main.py` 注册路由
- 新模块的模型是否在 `tests/conftest.py` 导入
