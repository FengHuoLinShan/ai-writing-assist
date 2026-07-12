# Round 3/20 - 深层模式分析

**Status**: COMPLETE — PASS  
**Goal**: 深入分析竟态条件、事务管理、异常处理、配置安全全局模式  
**Started**: 2026-07-13

## 结果汇总（15+23+16+26 = **80 个问题**）

### 异常处理审计 — 15 个问题（2 CRITICAL + 4 HIGH + 8 MEDIUM + 1 LOW）

**最严重发现**：
1. **CRIT-1**: `settings/facade.py:37` `LookupError` 应为 `NotFoundError` — 500 而非 404
2. **CRIT-2**: `project/api.py:106-113` 无 try/except — facade 的 `LookupError` 直达 500
3. **HIGH-1**: `outline/services.py:135` 裸 `TypeError` 在 `list_response` 未设置时
4. **HIGH-2**: `writing/tasks.py:43-208` 任务处理程序裸抛 `ValueError`
5. **MEDIUM-1**: 多个 api.py 无 UUID 校验封装 — parse_uuid ValueError→500

### 竟态条件审计 — 23 个问题（5 CRITICAL + 5 HIGH + 8 MEDIUM + 5 LOW）

**最严重发现**：
1. **CRIT-1**: `writing/services.py:614-642` delete_draft — TOCTOU 在工作版本计数检查和删除之间
2. **CRIT-2**: `writing/services.py:193-271,363-445` publish_draft_result / update_draft — 复杂读判定写无序列化
3. **CRIT-3**: `outline/scene_workbench.py:610-668` scene merge — 目标和来源场景均无锁
4. **CRIT-4**: `outline/scene_workbench.py:761-810` scene split — 来源场景无锁
5. **CRIT-5**: `outline/services.py:817-892` split_chapters — 来源场景无锁
6. **HIGH-1**: `writing/repositories.py:621-640` _next_version_number — 首次插入无行可锁
7. **HIGH-2**: `world/repositories.py` relation_upsert_lock — 进程级 asyncio.Lock 多 worker 下失效
8. **HIGH-3**: `writing/services.py:363-445` update_draft — 无 FOR UPDATE
9. **HIGH-4**: `writing/services.py:387-412` 已发布草稿的 copy-on-write 竟态
10. **HIGH-5**: `infrastructure/llm/limits.py` LLMProcessLimiter — 仅进程级，无跨 worker 协调

### 事务管理审计 — 13 个问题（2 CRITICAL + 6 HIGH + 4 MEDIUM + 2 LOW）

**最严重发现**：
1. **CRIT-1/2**: `world/repositories.py:158-165,725-728` `PendingRollbackError` — `pg_trgm` 错误后 fallback 查询前未 `rollback()`
2. **HIGH-1**: `world/repositories.py:787-792` `PendingRollbackError` — `pgvector` 错误后无 rollback 直接 `return []`
3. **HIGH-2**: `imports/scene_entity_persistence.py:220-245` 别名 savepoint 缺少 try/except
4. **HIGH-3**: `tasks/worker.py:318-377` 失败后 3 个事务在同一个 session 中，脆弱
5. **HIGH-4**: `imports/workflow_structure_phase.py:215,458` rollback 后继续使用 session

### 配置安全审查 — 26 个问题（2 CRITICAL + 7 HIGH + 9 MEDIUM + 8 LOW）

**最严重发现**：
1. **CRIT-1**: `config.py:106` 默认 DATABASE_URL 硬编码密码 `novel_dev_pass`
2. **CRIT-2**: 无 HTTP 级速率限制中间件
3. **HIGH-1**: `app_env` 默认值为 `"development"` — CORS 通配符 + 访问令牌绕过级联
4. **HIGH-2**: `llm_rate_limit_per_minute` 默认 0（无限）
5. **HIGH-3**: `allowed_origins` 默认 `["*"]`
6. **HIGH-4**: `debug_api.py:76-78` 守卫使用大小写敏感比较
7. **HIGH-5**: `debug_api.py:15` 调试路由在生产环境 OpenAPI 可见
