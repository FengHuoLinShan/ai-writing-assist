# Round 6/20 - 依赖、数据流、代码债务、异步审计

**Status**: IN_PROGRESS  
**Goal**: 依赖/包审计、数据流/状态审计、代码组织/技术债、异步/并发模式  
**Started**: 2026-07-13

## 已返回

### 依赖/包审计 — 13 个发现（4 HIGH + 5 MEDIUM + 4 LOW）

**最严重发现**：
1. **HIGH-1**: 无 Python lock 文件 — 不同 install 解析不同依赖图，不可复现
2. **HIGH-2**: `pydantic-settings` 和 `python-dotenv` 声明为生产依赖但代码零使用（自定义 dataclass + 手动 loader）
3. **HIGH-3**: `requirements.txt` 与 `pyproject.toml` 漂移 — 缺失 6 个生产包，包含未使用的 `python-dateutil`
4. **HIGH-4**: 无 hash 校验 — supply-chain 攻击面
5. **MEDIUM-1**: `beautifulsoup4` 用 `"lxml"` parser 但 `lxml` 未在任何依赖组中
6. **MEDIUM-2**: `sentence-transformers` 声明为 `[dev]` 但生产代码（`worker.py:86`）导入 — 不加 `[dev]` 会失败
7. **MEDIUM-3**: `pyproject.toml` 中 `[dev]` 与 `[test]` 重复声明 `httpx`/`pytest`/`pytest-asyncio`/`pytest-cov`
8. **MEDIUM-4**: `joblib` 声明为 `[dev]` 但零 import

**亮点**：前端零运行时依赖（vanilla JS），`package-lock.json` 有 integrity 哈希。

### 异步/并发模式审计 — 7 个发现（1 HIGH + 3 MEDIUM + 3 LOW）

**最严重发现**：
1. **HIGH-1**: `imports/parsers.py:219-220` `parse_mobi()` 同步 `open()`/`read()` 在 async 上下文 — 阻塞事件循环
2. **MEDIUM-1**: 代码库零处使用 `run_in_executor` — CPU 密集操作（`tiktoken`、`HTMLParser`、大 `json.dumps`）在事件循环中同步运行
3. **MEDIUM-2**: `infrastructure/tasks/enqueuer.py:18-38` `enqueue_task()` 是 sync 函数但接受 AsyncSession
4. **MEDIUM-3**: `embedding/cache.py:23` 和 `rag/circuit_breaker.py:50` 在 async 代码中使用 `threading.Lock`

**优秀模式**：
- `infrastructure/llm/limits.py` 正确的 asyncio.Lock + Semaphore + 熔断器
- `infrastructure/tasks/worker.py` 取消安全的 CancelledError 处理
- `infrastructure/embedding/client.py` asyncio.shield + wait_for
- `core/container.py` 有序清理 + ExceptionGroup

### 数据流/状态审计 — 4 个发现（0 CRITICAL + 1 MEDIUM + 3 LOW）+ 架构观察

**最严重发现**：
1. **MEDIUM-1**: `writing/tasks.py:52` 直接 import `rag.index_state.RagIndexStateService` 而非通过 RAG facade — 唯一中级跨模块违规
2. **LOW**: `project/services.py:261` → `settings.constants`（常量绕过）
3. **LOW**: `project/api.py:28` → `settings.schemas`（Schema 绕过）
4. **LOW**: `writing/services.py:1260` → `world.map_facade` 而非 `world.facade`
5. **广泛模式**: `writing/api.py`, `outline/api.py`, `memory/api.py` API 路由直接实例化服务绕过自身 facade

**架构观察**：
- 模块依赖图：9 个模块全部连接，无运行时循环导入
- facade 层设计良好（9/9 模块有 facade，仅 2 个有微小逻辑）
- Novel_id 隔离强 — API 参数 + 任务验证 + ORM NovelMixin
- 无领域事件机制 — 实体变更不会自动传播到依赖数据

### 代码组织/技术债审计 — ~36 个发现（12 HIGH + 7 MEDIUM + 17 LOW）

**最严重发现**：
1. **HIGH**: 18 个生产文件 >1000 行 — `world/repositories.py`(2,189), `writing/services.py`(1,639) 等
2. **HIGH**: 前端 `worldView.js`(3,178), `styles.css`(7,568)
3. **HIGH**: 14 个函数 >150 行 — `run_full_pipeline`(614 行)
4. **MEDIUM**: `assetDisplayState 2.js` 带空格的重复文件，无法被 import
5. **MEDIUM**: `backend/backend/` 嵌套目录 — 测试工作目录产物
6. **MEDIUM**: `core/crud.py` 定义 CRUD 模板，但多个模块仍手动实现
7. **MEDIUM**: 测试散落在 3 个位置
8. **MEDIUM**: `writing/services.py` 有 24 处 `# type: ignore`

**积极**：零通配符导入、零 TODO/FIXME/HACK、一致命名。

## Round 6 累计

| 轮次 | 问题数 | CRITICAL | HIGH | MEDIUM | LOW |
|------|--------|----------|------|--------|-----|
| R1 | 251 | 24 | 60 | 95 | 72 |
| R2 | 59 | 5 | 11 | 21 | 22 |
| R3 | 80 | 9 | 18 | 29 | 24 |
| R4 | 93 | 3 | 13 | 49 | 38 |
| R5 | 62 | 4 | 22 | 25 | 11 |
| R6 | ~60 | 0 | 17 | 16 | 27 |
| **累计** | **~605** | **45** | **131** | **235** | **194** |