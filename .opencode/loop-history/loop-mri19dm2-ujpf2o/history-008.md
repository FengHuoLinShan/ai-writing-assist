# Round 8/20 - 深层架构 & 一致性审计

**Status**: PASS  
**Goal**: DI 容器、基础设施模式、前端渲染性能、Schema/模型同步  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | HIGH | MEDIUM | LOW |
|----------|--------|------|--------|-----|
| DI 容器深度审计 | 8 | 2 | 3 | 3 |
| 基础设施模式审计 | 19 | 5 | 6 | 8 |
| 前端渲染性能 & 内存 | 15 | 1 | 8 | 6 |
| Schema/模型同步 | 13 | 0 | 7 | 6 |
| **合计** | **55** | **8** | **24** | **23** |

---

## DI 容器深度审计 — 8 个发现（2 HIGH + 3 MEDIUM + 3 LOW）

**未注册但调用的 Key**：
1. **HIGH**: `rag/source_collection.py:125` 调用 `_container_get("world.get_entity_importance_map")`，该 key **从未在 `bootstrap.py` 注册**。调用被 `except Exception: pass` 吞噬，在每个 RAG 索引路径上静默降级实体重要性数据。
2. **HIGH**: 20 个服务在模块级全局初始化（`world/api.py:129-146` 18个 + `writing/api.py:74-75` 2个），**完全绕过 DI 容器**，无法 mock。
3. **MEDIUM**: `RagIndexStateService` 在 6+ 处被 `new`-ed（`rag/facade.py`、`rag/tasks.py`、`writing/tasks.py`），未走容器。
4. **MEDIUM**: Task handler 手动创建服务（`WritingGenerationService()`、`EntityExtractionService()`、`IndexingService()` 等），不走容器 → 测试性差。
5. **MEDIUM**: 容器是全局单例，无 async 作用域隔离 → 异步上下文中测试可能交叉污染。
6. **LOW**: `Injected` descriptor（`core/container.py:147-165`）定义了但生产代码零使用，死代码。
7. **LOW**: 容器外服务无生命周期清理（`MemoryService` 无 `close()`/`aclose()`，world/writing API 模块级 singleton 从不清理）。
8. **LOW**: 所有服务在 `bootstrap.py` 中用 `register(name, instance)` 注册而非 `register_factory()`，即使传参是 callable 也按不可变单例存储 → 所有服务在 import 时主动初始化。

**核心结论**：容器在其主要设计目标（打破模块间循环依赖）上成功，但采用率不足一半（约 40 个服务实例化走容器，21 个外），形成"跨模块走容器、模块内硬编码"的两层系统。

---

## 基础设施模式审计 — 19 个发现（5 HIGH + 6 MEDIUM + 8 LOW/INFO）

**LLM 客户端**：
1. **HIGH**: `LLMConnectionError` 未被显式标记为可重试（`retry.py:33-52`），虽然通过 `LLMError` 兜底分支实际可重试，但文档承诺的分类不匹配。
2. **MEDIUM**: 结构化输出重试延迟无 jitter（`client.py:75-83`），多 worker 同时结构化失败时产生惊群效应。
3. **MEDIUM**: `transport_retries=False` 时结构化路径绕过 circuit breaker（`client.py:536-538`）。
4. **MEDIUM**: `prompt_loader.py:59-60` 用 `str.replace()` 做模板替换，脆弱（子串冲突、无默认值、无转义）。
5. **LOW**: `get_provider()` 只接受 `"openai"`，无 provider 插件系统。
6. **LOW**: Prompt 文件无缓存（每次 `load_prompt()` 读磁盘）。
7. **LOW**: Fix 消息在重试迭代中积累无界内容。

**Embedding 系统**：
1. **HIGH**: 缓存 key 不含模型名（`cache.py:28-30`），切换 embedding 模型后最多 1 小时返回旧模型结果。
2. **MEDIUM**: BGE 失败时回退逻辑隐式依赖新 `LLMClient()` 无 runtime_scope，脆弱。

**Task Worker**：
1. **LOW**: `_claim_task_runner()` 手动管理 DB session 上下文（`worker.py:220-239`）。
2. **LOW**: Heartbeat 持有独立 DB session，高并发下可能竞争连接池。
3. **INFO**: Stale 检测延迟最高 `max_heartbeat_gap + poll_interval`。

**Secret Store**：
1. **HIGH**: 无密钥轮换支持（`secret_store.py:9-10`），`_SECRET_ENVELOPE_VERSION = "fernet-v1"` 暗示有计划但未实现。

**Circuit Breaker**（LLM + RAG）：
1. **HIGH** (×2): LLM CB（`limits.py:72-75`）和 RAG CB（`rag/circuit_breaker.py:72-77`）的 `record_success()` 在 CLOSED 状态不重置 `_failure_count`，导致断路器基于累计失败而非连续失败打开——违反文档声明的"连续失败 N 次"语义。
2. **MEDIUM**: LLM CB 无显式 HALF_OPEN 状态（行为正确但难以推理）。
3. **MEDIUM**: RAG CB 全局单例 `_circuit_breaker` 跨所有 novel 共享。

---

## 前端渲染性能审计 — 15 个发现（1 HIGH + 8 MEDIUM + 6 LOW）

**最严重发现**：
1. **HIGH**: `writing/submodules.js` orchestrator 通过回调闭包传递给每个子模块，创建循环引用链
2. **MEDIUM-HIGH**: `workflowProgress.js:497` 等轮询每 1.5s 触发 `router.renderCurrentView()` 完全重新渲染
3. **MEDIUM**: `editor.js:95-133` 通过属性赋值（`oninput`/`onclick`）分配事件处理程序，每次重新渲染创建新闭包
4. **MEDIUM**: `viewHelper.js:108-110` `bindActionMenus()` 每次调用添加 `document click` 监听器，从未在 `onLeave` 移除
5. **MEDIUM**: keep-alive `_viewDomCache` 可能因后台数据变化显示过时信息
6. **MEDIUM**: `editor.js:99,109` 每次按键 `_saveBackup()` 写入 localStorage（阻塞主线程）
7. **MEDIUM**: 编辑器 `oninput` 直接调用 `updateWordcount()` 无去抖 — 7+ DOM 查询每次按键
8. **MEDIUM**: `setTimeout(() => this._bindEvents(), 0)` 模式脆弱

**渲染架构**：基于 `innerHTML` 完全重新渲染，无虚拟 DOM/差异比较。`writing`/`outline` 使用 KeepAlive 缓存。

---

## Schema/模型同步审计 — 13 个发现（7 MEDIUM + 6 LOW）

| # | 模块 | 文件:行 | 问题 | 严重性 |
|---|------|---------|------|--------|
| 1 | rag | `api.py:51,143,149,161,183,202` | 6 个端点使用 `response_model=dict` 而非 typed schema | MEDIUM |
| 2 | memory | `models.py:157` | `DeltaLog` 模型无 Pydantic schema | MEDIUM |
| 3 | world | `schemas.py:914-918` | `RevisionListResponse` 用 `list[dict]` 而非 typed schema | MEDIUM |
| 4 | outline | `models.py:32-34` | ORM `nullable=True`+`default=list` 与 Pydantic `list[str]=[]` 冲突 | MEDIUM |
| 5 | context | `schemas.py:206-226, 325-356` | `created_at` 在 response 中类型为 `str` 但 ORM 为 `DateTime` | MEDIUM |
| 6 | world | `schemas.py:1220-1251` | `knowledge_level` 在 Create schema 中 required（ORM 默认 "unknown"） | MEDIUM |
| 7 | world | `schemas.py:473-539` | `content_json` Pydantic `default=None` vs ORM `default=dict` | MEDIUM |
| 8 | world | `models/profiles.py:48-190` | 6 个 profile 模型无专用 response schema → 通过 `dict` 序列化 | MEDIUM |
| 9 | rag | `models.py:128-145` | ORM `Mapped[dict]` 注解错误（存的是 list） | LOW |
| 10 | writing | `schemas.py:79-82` | Pydantic `max_length` vs ORM `Text`（无界） | LOW |
| 11 | outline | `schemas.py:29-44,109-126` | Create schema 字段缺 `description=` → 影响 OpenAPI 文档 | LOW |
| 12 | memory | `schemas.py:124-146` | 字段缺 descriptions | LOW |
| 13 | writing | `api.py:50-70` | 内联 schema 定义在 api.py 而非 schemas.py | LOW |

**各模块对齐评分**：
- project: 95/100，imports: 92/100，writing: 90/100
- outline: 88/100，memory: 85/100，rag: 85/100
- context: 82/100，world: 78/100（最多不匹配）
