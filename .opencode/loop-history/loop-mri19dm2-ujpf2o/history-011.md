# Round 11/20 — Client/Server Caching / Background Jobs / Event Patterns

**Status**: PASS  
**Goal**: 前后端缓存策略、后台作业模式、事件/发布订阅模式  
**Started**: 2026-07-13  
**Completed**: 2026-07-13  

## 结果总览

| 审计模块 | 发现数 | CRITICAL | HIGH | MEDIUM | LOW |
|----------|--------|----------|------|--------|-----|
| 前端缓存策略 | ~40 | 0 | 1 | 5 | ~34 |
| 后端缓存策略 | ~10 | 0 | 2 | 1 | ~7 |
| 后台作业模式 | ~15 | 1 | 2 | 4 | ~8 |
| 事件/发布订阅 | ~12 | 0 | 1 | 2 | ~9 |
| **合计** | **~77** | **1** | **6** | **12** | **~58** |

---

## 前端缓存策略 — ~40 个发现（1 HIGH + 5 MEDIUM + 大量 LOW）

### API 响应缓存（`api.js`）
✅ 集合根失效正确覆盖列表+子资源、写操作失败不清缓存、并发 GET 共享 pending Promise
⚠️ 无 LRU 淘汰（仅 TTL）、失效粒度过粗（写操作清整个集合根）

### KeepAlive DOM 缓存（`router.js:102-360`）
✅ projectId 维度在 key 中，换项目不误用旧 DOM
🔴 **HIGH**: 无 LRU 大小限制、数据变更后其他视图的缓存 DOM 不自动失效 → 陈旧内容窗口
⚠️ 长会话可能积累大量 DOM 片段

### localStorage 缓存
⚠️ 多数 key 无版本控制、`novel_active_workflows_v1` 无大小限制、无跨标签同步（除 `global_settings_cache_version`）
✅ 所有 JSON.parse 有 try-catch 降级、`_errorLog` 最规范（50 条上限）
✅ 无 Service Worker / PWA

---

## 后端缓存策略 — ~10 个发现（2 HIGH + 1 MEDIUM）

**整体**：无外部缓存（Redis/Memcached），进程内缓存共 6 处

🔴 **HIGH**: **Embedding 缓存 key 缺模型名**（`embedding/cache.py:28-30`）— Round 8 已发现仍未修复，切模型后最多 1h 返回旧结果
🔴 **HIGH**: **LLM API 响应无缓存** — 相同 prompt 重复调用 API（实体抽取每场景一次、场景分割每章节多次），浪费 token、增加限流概率
🟡 **MEDIUM**: **Prompt 模板无文件缓存** — `prompt_loader.py` 每次调用 `path.read_text()` 读磁盘

### 现有缓存清单
| 缓存 | 位置 | 类型 | TTL | 评估 |
|------|------|------|-----|------|
| Embedding 向量 | `embedding/cache.py` | LRU + Lock | 3600s | ✅ 实现正确，⚠️ key 缺模型名 |
| Eval 缓存 | `evals/cache.py` | 磁盘 JSON | 永久 | ✅ 仅测试评估用 |
| Settings 单例 | `core/config.py:252` | `@lru_cache` | 进程 | ✅ |
| tiktoken 编码器 | `llm/token_estimation.py:11` | `@lru_cache` | 进程 | ✅ |
| 项目词典 | `rag/query_expansion.py:21` | dict | 60s | ⚠️ 无写失效自动清除 |
| PhaseRunners | `imports/workflow.py:221` | 实例属性 | 延迟初始化 | ✅ |

---

## 后台作业模式 — ~15 个发现（1 CRITICAL + 2 HIGH + 4 MEDIUM）

**基础设施**：PostgreSQL 表 + `FOR UPDATE SKIP LOCKED` 实现轻量队列，无 Redis/Arq

### 任务总览
- 21 种任务类型，分布在 6 个模块
- 命名一致 `snake_case` + 模块前缀
- 状态机 `pending→running→done/failed/cancelled`
- Recovery 策略：`restart_origin` (12)、`auto_requeue` (3)、`manual_resume` (4)、stub (2)
- Karma: `test_infra_tasks.py` 1377 行单元测试

🔴 **CRITICAL**: **无死信队列** — `max_attempts` 耗尽后任务永久 `failed` 静默驻留，无告警/清理
🔴 HIGH: **`meta` 参数无 Pydantic schema 校验** — 所有任务共用无约束 `meta: dict[str, Any]`，缺失字段只在运行时暴露
🔴 HIGH: **缺乏监控/队列可视化** — 无持久化指标、管理界面、队列深度 API
🟡 MEDIUM: 2 个 stub 任务注册了 handler 但永远 return `unsupported`
🟡 MEDIUM: `publish_chapter` 内置 3 次重试与系统 `restart_origin` 策略不对称
🟡 MEDIUM: Worker `stop()` 直接 cancel 而非 drain（runner 可能被中断写入 DB）
🟡 MEDIUM: 无 per-task 执行时间上限；`enqueue_task` 未 flush DB

---

## 事件/发布订阅模式 — ~12 个发现（1 HIGH + 2 MEDIUM）

**代码库无传统事件总线、领域事件或发布订阅机制**。模块通信三种模式：同步 facade 调用、PG 任务队列、共享 DB 表。

🔴 **HIGH**: **无领域事件机制 — 耦合的发布工作流** — `publish_chapter` handler 硬编码 RAG 索引→内存快照两步顺序执行，无办法让其他系统对新发布版本反应而不修改核心处理器
🟡 MEDIUM: **无 SQLAlchemy 生产事件** — `DeltaLog`/`MemoryEvent` 记录了丰富的变更数据但零广播，其他模块只能轮询或直接调用
🟡 MEDIUM: **前端缺乏结构化交叉视图通信** — 3 个独立的 listener 系统（`state._stateListeners`、`router._navListeners`、DOM 委托），无统一事件总线
✅ `@task_handler` 注册器 21 个、`onStateChange` 用户 2 个、`bindDelegation` 6+ 视图
✅ PostgreSQL `NOTIFY/LISTEN`、Webhook、插件系统、CustomEvent 均未使用（0）
