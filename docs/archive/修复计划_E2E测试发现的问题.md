# E2E 测试发现的预存问题修复计划

> 测试环境：PostgreSQL 17 + pgvector（Docker），诡秘之主 第一部 种子数据
> 2026-05-25 测试，92 passed / 5 failed / 1 skipped

## P0 — DB Schema 缺失列或类型不匹配

### 1. RAG: `rag_chunks.meta` 列缺失
- **症状**：POST /api/rag/retrieve → `UndefinedColumnError: column rag_chunks.meta does not exist`
- **原因**：ORM 模型 `RagChunk` 定义了 `meta` 列，但初始迁移没有它（后来在 ORM 中添加但未生成迁移）
- **涉及端点**：所有 RAG 检索端点
- **修复**：Alembic 迁移 ADD COLUMN `rag_chunks.meta`

### 2. Review: `review_reports.status` 列缺失
- **症状**：POST /api/review → `UndefinedColumnError: column "status" of relation "review_reports" does not exist`
- **原因**：ORM 模型 `ReviewReport` 在初始迁移后加了 `status` 列
- **涉及端点**：所有 Review 创建/查询端点
- **修复**：Alembic 迁移 ADD COLUMN `review_reports.status`

### 3. Review: 缺少 `GET /api/review` 列表端点
- **症状**：405 Method Not Allowed — API 路由中只有 `POST /` 和 `GET /{id}`，没有 GET /
- **涉及端点**：复查报告列表
- **修复**：在 `modules/review/api.py` 增加列表路由

### 4. ChapterCard: `arc_id` 类型不匹配
- **症状**：`column "arc_id" is of type uuid but expression is of type character varying`
- **原因**：ORM 模型定义 `arc_id` 为 `String(36)` 但 DB 实际是 `UUID`
- **涉及端点**：章节卡创建
- **修复**：统一为 UUID 类型

## P1 — 模型代码问题

### 5. CharacterKnowledge: `created_at` 时区不匹配
- **症状**：`can't subtract offset-naive and offset-aware datetimes`
- **原因**：模型使用 `default=datetime.utcnow`（naive）而 DB 是 `TIMESTAMP WITH TIME ZONE`
- **涉及端点**：人物知识边界创建
- **修复**：改 `default=datetime.now(timezone.utc)` 或 `server_default=func.now()`

### 6. MemoryUpdateProposal: `updated_at` 列缺失
- **症状**：`column memory_update_proposals.updated_at does not exist`
- **原因**：ORM 模型后来加了 `updated_at` 字段
- **涉及端点**：记忆提案查询
- **修复**：Alembic 迁移添加此列

## 修复策略

建议统一使用 Alembic 迁移修复所有缺失列，而非逐一手动 ALTER TABLE：
1. 添加所有缺失列到 ORM 模型（部分可能已有）
2. 确保 `alembic/env.py` 导入 `modules.imports.models`
3. 运行 `alembic revision --autogenerate -m "sync orm schema"` 生成迁移
4. 手动审查迁移文件，移除破坏性操作（如 ALTER COLUMN type）
5. `alembic upgrade head` 应用
