# Round 5/20 - 基础设施 & 质量审计

**Status**: IN_PROGRESS  
**Goal**: 测试覆盖率、数据验证/Schema、日志/可观测性、部署/基础设施  
**Started**: 2026-07-13

## 已返回

### 部署/基础设施审计 — 19 个差距（3 CRITICAL + 7 HIGH + 5 MEDIUM + 4 LOW）

**最严重发现**：
1. **CRIT-1**: 无 Dockerfile — 无法生成可重复部署镜像
2. **CRIT-2**: 无 CI/CD — 合并前不运行 lint/test/build
3. **CRIT-3**: `backend/.env` 提交了真实 API 密钥（`LLM_API_KEY=sk-5MQh...`，`LLM_SETTINGS_ENCRYPTION_KEY=AqPK...`）— 已泄露
4. **HIGH-1**: `docker-compose.yml` 仅定义 postgres，无 app/worker 服务
5. **HIGH-2**: 无生产启动配置（单独的 gunicorn/多 worker 配置）
6. **HIGH-3**: 嵌入子进程管理 — 容器中崩溃/挂起无重启机制
7. **HIGH-4**: 无反向代理（nginx/Caddy）— 无 TLS、速率限制、静态文件
8. **HIGH-5**: 无监控/告警 — 无 metrics、Sentry、结构化日志
9. **HIGH-6**: 无备份策略
10. **HIGH-7**: 无前端静态构建/服务策略

### 测试覆盖率审计 — 16 个发现（0 CRITICAL + 3 HIGH + 8 MEDIUM + 5 LOW）

**最严重发现**：
1. **HIGH-1**: `modules/writing/conflict_ai.py`（~200 行）零测试覆盖 — AI 冲突检测逻辑未测试
2. **HIGH-2**: `modules/rag/circuit_breaker.py`（~80 行）熔断器状态机无测试
3. **HIGH-3**: `infrastructure/embedding/cache.py`（~150 行）嵌入缓存零测试
4. **MEDIUM**: Memory 模块覆盖最薄（3 个测试文件）
5. **MEDIUM**: Settings 继承链解析未测试
6. **MEDIUM**: 无覆盖率测量（pytest-cov 已安装但未配置）
7. **MEDIUM**: 仅 6 个集成测试文件，覆盖 9 个模块
8. **MEDIUM**: E2E 测试仅手动运行，不在标准流程中

**总体**：~3,176 个后端测试 + 93 前端 Vitest + Playwright E2E。World 模块覆盖最好（40 测试文件），Memory/Settings/Embedding 最弱。

### 数据验证/Schema 审计 — 12 个发现（4 HIGH + 5 MEDIUM + 3 LOW）+ 22 个端点映射

**最严重发现**：
1. **HIGH-1**: `project/api.py` + `settings/api.py` 中 15 个端点的 `project_id: str` 路径参数缺少 UUID 格式验证
2. **HIGH-2**: `imports/api.py:281,308` `resume_deep_import`/`abandon_deep_import` 使用 `body: dict = Body(...)` 绕过所有 Pydantic 验证
3. **HIGH-3**: RAG API 中 6 个端点使用 `response_model=dict` — 包括 `list_rag_chunks` 手动拼接 `**status` 到 dict
4. **HIGH-4**: World API 中 11 个端点返回裸 `dict`/`list[dict]` — 别名、批量、模板、冲突等
5. **MEDIUM**: HTML 净化仅限 writing 模块 — 其他模块的文本输入直接进数据库
6. **MEDIUM**: 多个大纲模式字符串字段无 `max_length`（PlotThread、OutlineArc、Event）

**模块评分**：context (A), outline (A), writing (A-), project (A-), memory (A-), settings (A-), world (B+), imports (B), rag (B-)

### 日志/可观测性审计 — 15 个差距（1 CRITICAL + 7 HIGH + 5 MEDIUM + 2 LOW）

**最严重发现**：
1. **CRIT-1**: 日志中几乎无 `novel_id` 上下文 — 无法按项目过滤/搜索日志
2. **HIGH-1**: 无结构化日志（纯文本）— 日志聚合器无法解析字段
3. **HIGH-2**: 无请求日志中间件 — 无访问日志
4. **HIGH-3**: 42 处 `except Exception:` 吞掉错误
5. **HIGH-4**: 业务发布无审计轨迹（API 层不记录日志）
6. **HIGH-5**: 无外部指标系统（Prometheus/Datadog）
7. **HIGH-6**: 前端生产错误传输被 `debug_api.py:77` 禁用 -- `_ensure_debug_allowed()` 在生产环境返回 404
8. **HIGH-7**: `DomainError` 处理器不记录日志

## Round 5 累计

| 轮次 | 问题数 | CRITICAL | HIGH | MEDIUM | LOW |
|------|--------|----------|------|--------|-----|
| R1 | 251 | 24 | 60 | 95 | 72 |
| R2 | 59 | 5 | 11 | 21 | 22 |
| R3 | 80 | 9 | 18 | 29 | 24 |
| R4 | 93 | 3 | 13 | 49 | 38 |
| R5 | 62 | 4 | 22 | 25 | 11 |
| **累计** | **545** | **45** | **114** | **219** | **167** |
