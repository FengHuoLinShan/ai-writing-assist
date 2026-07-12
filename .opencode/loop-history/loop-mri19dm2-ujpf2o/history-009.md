# Round 9/20 — Middleware & Error Handling / Frontend State / DB Migration / WebSocket

**Status**: PASS  
**Goal**: 中间件/错误处理、前端状态管理、数据库迁移与种子、WebSocket/实时通信  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| 中间件与错误处理 | 16 | 1 | 2 | 8 | 5 |
| 前端状态管理 | 32 | 7 | 11 | 10 | 4 |
| 数据库迁移与种子 | 12 | 1 | 3 | 5 | 3 |
| WebSocket/实时通信 | 5 | 0 | 0 | 1 | 4 |
| **合计** | **65** | **9** | **16** | **24** | **16** |

---

## 中间件与错误处理 — 16 个发现（1 CRITICAL + 2 HIGH + 8 MEDIUM + 5 LOW）

### 中间件审计
- ✅ 执行顺序正确：CORS→ApiSecurity→Timing（从外到内）
- ✅ `_ApiSecurityMiddleware` 使用 `hmac.compare_digest` 常量时间比较，OPTIONS 请求跳过安全检查（正确）
- ✅ `CORSMiddleware` 阻止生产环境通配符 Origin，通配符时 `allow_credentials=False`
- ⚠️ LOW: `X-Request-Time-Ms` 响应头可能辅助时序分析攻击（内部部署风险极低）
- ⚠️ LOW: `allow_methods=["*"]` 在生产环境可考虑明确列出

### 全局异常处理器
- ✅ `DomainError` handler 正确映射 `status_code`，返回统一 JSON
- ✅ 兜底 `Exception` handler 使用 `logger.exception()`，不暴露内部细节
- 🔴 **HIGH**: 无 `RequestValidationError` 处理器 — FastAPI 默认 422 响应暴露完整 `loc`/`type`/`msg` 泄露内部 Pydantic schema 结构

### 自定义异常层级
- ✅ 层次清晰：`DomainError` → `NotFoundError`/`ConflictError`/`ValidationError`
- ✅ LLM 异常按 retryability 分层（`LLMTimeoutError`、`LLMConnectionError` 等）
- 🟡 **MEDIUM**: `DomainError` 无 5xx 子类 — LLM 错误（继承 `Exception`）绕过 DomainError 处理器，被全局兜底按 500 返回

### 模块错误处理
- 🔴 **CRITICAL**: **~20+ 处 `except Exception: pass` / `continue` / `return`** — 包括 `infrastructure/embedding/worker.py` (3处)、`world/services/core/entity_alias_service.py:181`、`suggestion_queue_service.py:680`、`rag/source_collection.py:127`、`context/novel_evidence.py` (3处) 等。**裸吞异常不记录日志**，掩盖 DB 连接失败、LLM 超时、竞态条件等可操作性关键问题
- 🔴 **HIGH**: `_workbench_error`（`outline/api.py:85`）将未知异常转为 500 但**完全不记录日志** — ~15 个场景工作台端点受影响
- 🟡 MEDIUM: `writing/api.py:311,324` 冲突快照失败使用 `logger.warning` 而非 `exception`
- 🟡 MEDIUM: `imports/services.py:150` 保存原始异常文本到 DB（可能包含 SQL/路径）
- 🟡 MEDIUM: `rag/tuning.py:198` Embedding 降级无日志
- 🟡 MEDIUM: `outline/structure_dedup.py:300` RAG 错误吞掉

---

## 前端状态管理 — 32 个发现（7 CRITICAL + 11 HIGH + 10 MEDIUM + 4 LOW）

### Top 3

**🔴 #1 CRITICAL**: `setTimeout(() => _bindEvents(), 0)` 竞赛条件 — 各视图普遍使用（`projectView.js:129`、`writingView.js:229`、`outlineView.js:332` 等）。若用户在 4-16ms 延迟窗口内导航离开，事件绑定在已销毁的 DOM 节点上 → 内存泄漏 + 跨视图污染

**🔴 #2 CRITICAL**: `_syncCurrentProject` 并发导航状态竞赛（`router.js:276-306`）— A→B→A 快速导航时，慢请求可能覆盖为新项目的数据。无请求取消（`AbortController`）机制

**🔴 #3 CRITICAL**: `generateView:1093-1150` 完整聊天历史 + 大型对象持久化到 `localStorage` — 无大小限制（可能超 5MB 配额）、敏感创作思路持久化、失败被静默 `catch {}`

### 模式总结
- ✅ 正面：Proxy 响应式状态、`bindDelegation` + `data-action` 模式、Writing 子模块 `dispose()` 约定、`pollTaskProgress` 可见性暂停、`generateView` 的 `_abortAllRequests`
- ❌ 系统性问题：`setTimeout(() => _bindEvents(), 0)` 散落各视图、event listener 清理不一致（仅 writing 子模块系统化 dispose）、无状态变更审计追踪、localStorage 膨胀无防护、竞态防护靠运气

---

## 数据库迁移与种子 — 12 个发现（1 CRITICAL + 3 HIGH + 5 MEDIUM + 3 LOW）

### 迁移总览
- 15 个迁移文件，线性无分叉链
- 13/15 可逆 downgrade，2 个不可逆
- 4 个迁移混合了 schema + data migration

**🔴 CRITICAL**: 4 次数据迁移与 Schema 变更混合（`20260709_scene_spans_rag_visibility` backfill INSERT、`20260710_novel_evidence` content_hash UPDATE + rag_chunks DELETE、`20260710_asset_state_simplification` status UPDATE、`20260712_llm_max_tokens_12000` settings UPDATE）→ 长事务锁表 + 数据迁移不可回滚

**🔴 HIGH**: 两个迁移 `downgrade()` 为 noop（`asset_state_simplification`、`llm_max_tokens_12000`），状态修改不可逆

**🔴 HIGH**: 全表操作无分批 — `content_hash` 逐行全表 UPDATE、`rag_chunks` 全表 DELETE、`scene_spans` 单批次大量 INSERT → 大表时锁表 + WAL 暴涨

**🟡 MEDIUM**: `env.py:44-73` 每次迁移运行时动态修改 `alembic_version` 表 schema（不必要 DDL）

**🟡 MEDIUM**: 无 `pool_recycle` 和 `pool_timeout` 配置（`pool_pre_ping=True` 部分缓解）

**🟡 MEDIUM**: 迁移中广泛使用 inspector idempotent 检查（增加复杂度）

**🟡 MEDIUM**: 4 个迁移文件 revision ID 与文件名不一致

**⚪ LOW**: `alembic.ini` 硬编码明文数据库密码（有环境变量覆盖缓解）

**⚪ LOW**: `SceneSpan` 缺少 `ix_scene_spans_novel_id` ORM 声明（索引在 DB 中存在但 ORM 未注册）

**⚪ LOW**: `RagChunk` 唯一约束未在 ORM `__table_args__` 中声明

---

## WebSocket/实时通信 — 5 个发现（1 MEDIUM + 4 LOW）

**项目无 WebSocket 和 SSE** — 所有异步进度更新通过客户端 REST 轮询实现

| # | 严重性 | 位置 | 问题 |
|---|--------|------|------|
| 1 | MEDIUM | `publish.js:168-238` | `setInterval(poll, 2000)` 无 `inFlight` 守卫 → 可能堆叠请求 |
| 2 | LOW | `workflowProgress.js:508-518` | 网络错误无指数退避，继续以恒定速率轮询 |
| 3 | LOW | `app.js:67` | 健康检查轮询无 `inFlight` 守卫 |
| 4 | LOW | `worldView.js:725-758` | 两个轮询器可能同时运行（共享 + 遗留 `setInterval`） |
| 5 | LOW | 全局 | 无服务器推送通道（当前可接受，任务大多 <30s） |
