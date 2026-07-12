# Round 7/20 - 数据层 & 构建系统审计

**Status**: IN_PROGRESS  
**Goal**: SQLAlchemy 模型、前端 CSS/样式、构建系统/环境变量、API 文档  
**Started**: 2026-07-13

### SQLAlchemy 模型审计 — ~42 个差距（1 CRITICAL + 7 HIGH + 17 MEDIUM + 17 LOW）

**最严重发现**：
1. **CRIT-1**: `memory_events` 缺少 `(novel_id, chapter_index, sequence)` 复合索引 — 记忆回放核心路径，无此索引每次回放全表扫描
2. **HIGH-1**: `projects.deleted_at` 无索引 — 软删除过滤全表扫描
3. **HIGH-2**: `reveal_plans` 缺少 `(novel_id, target_type, target_id)` 复合索引 — 主要查找模式
4. **HIGH-3**: `imported_chapters.import_record_id` FK 无索引
5. **HIGH-4**: `entity_revisions.novel_id` 完全无索引
6. **HIGH-5**: `core_entities` 缺少 `(novel_id, entity_type)` 复合索引 — 核心查询模式
7. **HIGH-6**: `memory_snapshots` 缺少 `(novel_id, chapter_index)` 复合索引
8. **HIGH-7**: `async_tasks` 缺少 `(task_type, status)` 复合索引 — worker 轮询查询

**其他问题**：`outline/models.py:128` `pov_character_id` 是 String(36) 而非 UUID；多处 `func.now()` 而非 UTC 变体。

### 构建系统 & 环境变量审计 — ~18 个发现（2 CRITICAL + 5 HIGH + 8 MEDIUM + 3 LOW）

**最严重发现**：
1. **CRIT-1**: `backend/.env` 提交了真实 `LLM_API_KEY` 和加密密钥到仓库 — 已泄露
2. **CRIT-2**: `.env` 可能在 `.gitignore` 之外（需验证）
3. **HIGH-1**: 后端和前端均无生产构建管道 — 无法部署
4. **HIGH-2**: `APP_DEBUG` vs `DEBUG` 环境变量名不匹配 — `APP_DEBUG=true` 无效果
5. **HIGH-3**: 自定义 env 解析器 reinvents pydantic-settings（已依赖但未使用）
6. **HIGH-4**: imports 模块 6+ 文件使用裸 `os.getenv()` 绕过 Settings dataclass
7. **HIGH-5**: `.env.example` 缺失 ~15 个使用中的环境变量

**Makefile**: 56 个 targets，13 个测试相关，15 个 eval 相关。但缺少 `install`/`build`/`clean`/`pre-commit`。

### OpenAPI/Swagger 文档审计 — ~10 个发现（1 CRITICAL + 5 HIGH + 4 MEDIUM）

**最严重发现**：
1. **CRIT-1**: 整个项目**无任何端点使用 `responses=` dict 文档化错误响应** — 消费者不知端点返回什么错误
2. **HIGH-1**: 所有 schema 文件**无任何 `example=` 在 Field() 中** — 无示例值
3. **HIGH-2**: 无 Pydantic 模型使用 `model_config` 定义 examples
4. **HIGH-3**: RAG 模块 6 个端点用 `response_model=dict`（最差 OpenAPI 输出）
5. **HIGH-4**: imports 模块 5 个端点 + world map 6+ 端点无 `response_model`
6. **HIGH-5**: `imports/api.py:281,308` `body: dict = Body(...)` 生成无名 schema

**Schema 字段描述覆盖**：2,500 字段中 703（28%）无 description。memory(47%) 最差，imports(4%) 最好。

**整体评分**：5.5/10 — 基础良好但错误文档和示例严重缺失。

## Round 7 累计

| 轮次 | 问题数 | CRITICAL | HIGH | MEDIUM | LOW |
|------|--------|----------|------|--------|-----|
| R1 | 251 | 24 | 60 | 95 | 72 |
| R2 | 59 | 5 | 11 | 21 | 22 |
| R3 | 80 | 9 | 18 | 29 | 24 |
| R4 | 93 | 3 | 13 | 49 | 38 |
| R5 | 62 | 4 | 22 | 25 | 11 |
| R6 | ~60 | 0 | 17 | 16 | 27 |
| R7 | ~90 | 7 | 21 | 38 | 24 |
| **累计** | **~695** | **52** | **162** | **273** | **218** |