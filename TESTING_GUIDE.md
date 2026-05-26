# Testing Guide — 测试与 Review 规则

## Review Severity Levels

### P0 — Blocking (must fix before merge)

- AI output directly writes to canonical, bypassing candidate/review
- API allows cross-novel_id data read/write
- SQL injection, XSS, API key leakage, arbitrary file read/write
- Prompt injection triggers dangerous backend operations
- author_only / hidden_truth exposed in character-perspective context
- Context Compiler has no budget control, dumps entire DB
- Dangerous operations (merge/delete/deprecate) have no confirmation
- LLM output not validated before insert

### P1 — Must fix before release

- Module directly imports another module's models/repositories/services
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

测试应优先通过 public 接口（facade + contracts）进行，而非直接 import 内部模块：

```
✅ 推荐: from modules.xxx.facade import some_function
❌ 避免: from modules.xxx.repositories import SomeRepository
❌ 避免: from modules.xxx.services import SomeService
```

理由：
- **测试验证的是行为而非实现** — facade 是稳定的公共接口，内部重构不影响测试
- **facade 层本身就是薄层** — 测 facade 等价于测 service
- 当 facade 未暴露某个特定行为、或需要测试 repository 的复杂查询逻辑时，直接 import 内部是可以接受的，但应作为例外备注说明

Key points:
- All ORM models with FK dependencies must be imported to register in `Base.metadata`
- `NovelMixin` references `projects.id` → always import `modules.project.models`
- `WritingDraft` references `chapter_cards.id` → import `modules.outline.models`
- Each test gets a fresh DB (tables created per session)

## Key Integration Tests (in `tests/integration/`)

1. **Candidate cleaning**: input text → generate candidates → dedup → confirm alias
2. **Character knowledge boundary**: character's unknown info not in compiled context
3. **Chapter card generation**: schema validation passes, contains goal/conflict/must_not_happen/hook
4. **Structure review**: detects early reveal of hidden_truth
5. **Novel_id isolation**: project A API cannot read project B objects
6. **XSS protection**: `<script>` tags display as text, not executed

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
