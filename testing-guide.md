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
- **API** (via root `backend/conftest.py` `async_client`): HTTP happy path + error path

## Test execution layers

| Command | Scope | External prerequisites |
|---|---|---|
| `make test` / `make test-fast` | Modules, infrastructure, unit, SQLite integration, prompt contracts | None; excludes E2E, real LLM, and external source data |
| `make test-fast-coverage TEST_WORKERS=2` | Same fast layer with parallel production-code coverage and an 85% gate | None |
| `make secret-hygiene` | Tracked/indexed runtime env, private-key, and high-confidence credential gate | Git working tree; no Python dependency install required |
| `make test-integration` | SQLite cross-module flows | None |
| `make test-e2e` | PostgreSQL/pgvector behavior | Running test database at Alembic head; fails fast if unavailable or stale |
| `make test-real-llm` | Explicit SQLite real-model acceptance | Configured provider credentials |
| `make test-manual REAL_SOURCE_PATH=/abs/path/novel.txt` | Real source corpus and PostgreSQL/real-model acceptance | Source path, PostgreSQL, and configured provider credentials |

`pytest` uses the same fast test paths by default. Every marker is strict: use
`real_llm` for a remote provider call and `external_data` for a user-supplied
local corpus. Neither may enter the default fast layer.

### Continuous integration

GitHub Actions 在 pull request 和 `main` push 上运行 `Backend quality`：checkout 后先用
系统 Python 执行零依赖的 repository secret hygiene gate，再通过 `backend/uv.lock` 安装
Python 3.12 的窄 `ci` 依赖（不安装本地 embedding 运行时），然后依次执行 `make lint` 与
`make test-fast-coverage TEST_WORKERS=2 ARGS="-W error::RuntimeWarning"`。
secret hygiene gate 同时检查 Git index 的各 stage 和已跟踪工作区版本，拒绝运行时 `.env`、
常见私钥文件名、私钥块与高置信服务凭据；测试/文档中的显式占位值仅在受控路径豁免。
失败日志只包含安全化路径、规则名和不可逆短指纹，不输出凭据原文。等价本地入口是
`make secret-hygiene`；它不替代真实凭据发生泄露后的吊销、轮换和历史处置。
并行目标与串行 `make test-fast` 使用完全相同的测试路径、marker 排除和单测试超时，
`loadscope` 只把独立 module/class 分配到隔离 worker。coverage 只统计
`app/core/shared/infrastructure/modules` 中的生产 Python 文件，排除测试目录、pytest
支持的测试文件命名和 `conftest.py`，输出缺失行并要求总覆盖率不低于 85.0%。该检查不连接 PostgreSQL、真实
LLM 或本地语料；这些验收层仍按上表显式触发，且不继承 fast 层超时。远端启用分支保护
后，应把 `Backend quality` 设为合并前必需状态检查。

`make format` 暂未纳入 CI：当前仓库仍有历史格式债务，应先在独立机械变更中形成干净
基线，避免新门禁因无关存量文件持续失败。

### Test setup pattern

Use the root `backend/conftest.py` SQLite fixture for normal tests. It imports
the ORM metadata and creates the schema once per test session; every test gets
an outer transaction plus a savepoint-backed `AsyncSession`, so application
`commit()` calls are rolled back before the next test. Module `conftest.py`
files should contain only module-specific factories and mocks:

```python
@pytest_asyncio.fixture
async def world_map(db_session: AsyncSession, project_novel_id: str):
    return await _create_default_map(db_session, project_novel_id)
```

测试 schema 中的 PostgreSQL `UUID` 类型由根 `conftest.py` 仅在 SQLite dialect 下编译为
`CHAR(32)`。不要删除这一测试适配：SQLite 会给未知的 `UUID` 类型名 NUMERIC affinity，
并可能把形如科学计数法的合法 UUID hex 转成浮点 `inf`；生产 PostgreSQL 仍使用原生
`UUID` DDL。

Fixture 使用者只通过测试函数参数名请求 fixture。不得使用
`from conftest import ...`、`from tests.conftest import ...` 或其他普通 Python
import 复用 fixture；这会让 `conftest` 的解析取决于 pytest 收集顺序。所有
`backend/modules/*/tests/` 目录必须包含 `__init__.py`，统一收集可用
`make test-collect` 快速验证。

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
- Root conftest owns model registration, the shared schema, DI reset, and FastAPI dependency override cleanup.
- Each test starts with an empty logical database through transaction rollback; do not add per-module `create_all()` fixtures.
- Feature fixtures may import the concrete models they construct (for example `modules.outline.models` for `scenes` / `scene_spans`); `WritingDraft` itself has no `chapter_cards` FK.

### Mock conventions

给 `@patch` / `mock.patch` 的所有调用必须加 `autospec=True`，确保 mock 对象签名与被 mock 的 API 一致：

```python
# ✅ 正确
@patch("modules.world.services.SomeService.method", autospec=True)
# ❌ 错误 — 签名变化时不失败
@patch("modules.world.services.SomeService.method")
```

例外仅在 C 扩展等无法 autospec 的场景，需显式注释原因。

**禁止在生产代码中检测 Mock** — 不要写 `isinstance(db, Mock)` 守卫或 `from unittest.mock import Mock` 在生产 import。测试替身应通过 DI 注入（可选参数或 `Depends` override）传递，而非运行时类型检测改变生产逻辑。

### Fixture conventions

- 异步 fixture 必须使用 `@pytest_asyncio.fixture`，而非 `@pytest.fixture` + `async def`。虽然 `asyncio_mode = "auto"` 下后者技术上可运行，但 `@pytest_asyncio.fixture` 是显式约定，与 `conftest.py` 用法一致
- `asyncio_mode = "auto"` 启用后，`@pytest.mark.asyncio` 是冗余装饰器。新测试无需添加；旧测试可逐步清理
- 模块级 fixture 应放在模块的 `conftest.py` 中；E2E 共用的 `ctx` fixture 应提取到 `e2e/conftest.py`，避免 20+ 次重复实现

### Future subpackage test paths

`imports` and `world` may later split large internal service directories into subpackages such as `imports/parsing/`, `imports/workflow/`, `imports/entity_extraction/`, `imports/scene/` or `world/services/core/`, `world/services/map/`, `world/services/worldbuilding/`. When that happens, tests may follow the owning subpackage path to keep fixtures close to the implementation.

This does not relax module boundaries: cross-module behavior tests still go through facade/contracts/API/DI port, and production code still must not import another module's repositories/services/models directly.

## Key Integration Tests (in `tests/integration/`)

1. **Candidate/proposal review**: input text → generate candidates/proposals → dedup → confirm alias or preserve canonical auto-ingest provenance
2. **Character knowledge boundary**: character's unknown info not in compiled context
3. **Scene and structure generation**: schema validation passes and retains goal/conflict/must_not_happen/hook
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
8. **Authoring lifecycle**: `test_authoring_lifecycle.py` serially verifies import → imported chapter publish/index/snapshot → confirmed generation using imported evidence → explicit adoption → publish/index/snapshot → canonical retrieval. It must also prove foreign-novel evidence and project LLM credentials never enter the generation prompt.

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
- 新模块的模型是否在 root `backend/conftest.py` 导入
