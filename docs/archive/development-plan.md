# AI 长篇小说结构化创作引擎 - 开发计划 v2.0

> 文档状态：历史开发计划。当前项目结构、目录设计和技术栈以 `docs/00_整体设计.md` 为准；当前里程碑、交付状态和已知不足以 `docs/项目进度.md` 为准。本文件不再作为新增设计的归档入口。

## 项目概览

本项目是一个面向中文长篇小说的**结构化创作引擎**，核心产出是结构化创作资产（世界对象、人物档案、剧情线、章节卡等），而非直接生成正文。系统采用垂直模块化架构，让开发者可在子目录内独立完成开发。

## 当前项目状态

- ✅ 目录骨架已建立（M0 完成）
- ✅ 代码文件已全部实现（72 个 Python 文件，306 个测试通过）
- ❌ 数据库尚未搭建（需要 PostgreSQL + pgvector）
- ✅ Prompt 已编写完毕（4 个核心创作 Prompt + 1 个工具型抽取 Prompt）
- ✅ 测试框架已就位（pytest + pytest-asyncio）
- ✅ App 入口已创建（FastAPI，119 条路由）

## 整体依赖关系

```
Shared/Core ─┬─ Infrastructure ─┬─ Project ─┬─ World ─┬─ RAG ─┐
             │                  │           │         │       │
             │                  │           ├─ Character     ├─ Context ── Review
             │                  │           │                │
             │                  │           ├─ Geo ──────────┤
             │                  │           │                │
             │                  │           ├─ Memory ────┐  │
             │                  │           ├─ Timeline ──┘  │
             │                  │           │                │
             │                  │           └─ Outline ──────┘
             │                  │
             │                  └─ Writing (独立模块，依赖较少)
             │
             └─ Prompts (各阶段按需编写)
```

## 里程碑与模块分配

### Phase 1：基础设施与核心层（并行 3 组）

**组 A — Shared/Core**（依赖：无）
- 任务：建立全局共享代码
- 产出：
  - `shared/__init__.py` — 公共工具函数
  - `shared/types.py` — 全局类型定义
  - `shared/enums.py` — 枚举定义（entity_type, status, knowledge_level 等）
  - `shared/constants.py` — 全局常量
  - `core/database.py` — SQLAlchemy async engine + session 工厂
  - `core/config.py` — 项目配置（环境变量、数据库 URL、embedding 维度等）
  - `core/base.py` — SQLAlchemy Base、UUID mixin、TimestampMixin、StatusMixin
  - `core/dependencies.py` — FastAPI 依赖注入（db session, config）

**组 B — Infrastructure**（依赖：Shared/Core）
- 产出：
  - `infrastructure/llm/__init__.py`
  - `infrastructure/llm/client.py` — LLM 客户端封装（支持 OpenAI / 兼容 API）
  - `infrastructure/llm/providers.py` — 多 Provider 管理
  - `infrastructure/llm/schemas.py` — LLM 调用入参/出参 Pydantic schema
  - `infrastructure/llm/errors.py` — 自定义错误
  - `infrastructure/llm/retry.py` — 重试逻辑
  - `infrastructure/tasks/__init__.py`
  - `infrastructure/tasks/models.py` — async_tasks 表 SQLAlchemy model
  - `infrastructure/tasks/worker.py` — 进程内 worker
  - `infrastructure/tasks/registry.py` — 任务注册
  - `infrastructure/tasks/api.py` — 任务 API 路由

**组 C — Project 模块**（依赖：Shared/Core）
- 产出：
  - `modules/project/__init__.py`
  - `modules/project/README.md`
  - `modules/project/models.py` — projects 表 SQLAlchemy model
  - `modules/project/schemas.py` — Pydantic schema
  - `modules/project/repositories.py` — 数据访问层
  - `modules/project/services.py` — 业务逻辑
  - `modules/project/contracts.py` — 对外契约
  - `modules/project/facade.py` — 对外入口
  - `modules/project/api.py` — FastAPI 路由
  - `modules/project/tests/` — 测试

### Phase 2：核心业务模块（并行 4 组，依赖 Phase 1）

**组 D — World 模块**（依赖：Shared/Core + Project）
- 产出：
  - `modules/world/README.md`
  - `modules/world/models.py` — world_entities, relationships, entity_aliases, entity_candidates 表
  - `modules/world/schemas.py`
  - `modules/world/repositories.py`
  - `modules/world/services.py` — WorldEntityService, RelationshipService, EntityCandidateService, EntityDedupService, AliasService
  - `modules/world/contracts.py`
  - `modules/world/facade.py` — get_world_context, expand_related_entities, find_duplicate_entity_candidates
  - `modules/world/api.py`
  - `modules/world/tests/`

**组 E — Character 模块**（依赖：Shared/Core + Project）
- 产出：
  - `modules/character/README.md`
  - `modules/character/models.py` — characters, character_knowledge 表
  - `modules/character/schemas.py`
  - `modules/character/repositories.py`
  - `modules/character/services.py`
  - `modules/character/contracts.py`
  - `modules/character/facade.py` — get_characters_context, get_character_knowledge_context, filter_context_by_character_knowledge
  - `modules/character/api.py`
  - `modules/character/tests/`

**组 F — Geo 模块**（依赖：Shared/Core + Project + World）
- 产出：
  - `modules/geo/README.md`
  - `modules/geo/models.py` — geo_locations, geo_edges, geo_eras 表
  - `modules/geo/schemas.py`
  - `modules/geo/repositories.py`
  - `modules/geo/services.py`
  - `modules/geo/contracts.py`
  - `modules/geo/facade.py` — get_location_context, get_location_tree, get_travel_constraints, get_geo_history_context
  - `modules/geo/api.py`
  - `modules/geo/tests/`

**组 G — Memory + Timeline 模块**（依赖：Shared/Core + Project）
- 产出：
  - `modules/memory/README.md`
  - `modules/memory/models.py` — memory_records, memory_update_proposals 表
  - `modules/memory/schemas.py`
  - `modules/memory/repositories.py`
  - `modules/memory/services.py`
  - `modules/memory/contracts.py`
  - `modules/memory/facade.py` — get_recent_story_memory, create_memory_update_proposals, confirm_memory_proposal
  - `modules/memory/api.py`
  - `modules/memory/tests/`
  - `modules/timeline/README.md`
  - `modules/timeline/models.py` — timeline_events 表
  - `modules/timeline/schemas.py`
  - `modules/timeline/repositories.py`
  - `modules/timeline/services.py`
  - `modules/timeline/contracts.py`
  - `modules/timeline/facade.py` — get_relevant_timeline_context, check_timeline_conflicts
  - `modules/timeline/api.py`
  - `modules/timeline/tests/`

### Phase 3：创作核心层（并行 3 组，依赖 Phase 2）

**组 H — Outline 模块**（依赖：World + Character + Geo + Memory + Timeline）
- 产出：
  - `modules/outline/README.md`
  - `modules/outline/models.py` — plot_threads, outline_arcs, chapter_cards, foreshadowing_plans, reveal_plans 表
  - `modules/outline/schemas.py`
  - `modules/outline/repositories.py`
  - `modules/outline/services.py`
  - `modules/outline/contracts.py`
  - `modules/outline/facade.py` — get_chapter_card, get_active_threads, get_arc_context, create_chapter_cards_from_candidate
  - `modules/outline/api.py`
  - `modules/outline/tests/`

**组 I — RAG 模块**（依赖：World + Character + Geo + World Module + Memory）
- 产出：
  - `modules/rag/README.md`
  - `modules/rag/models.py` — rag_chunks 表
  - `modules/rag/schemas.py`
  - `modules/rag/repositories.py`
  - `modules/rag/services.py` — chunking, embedding, hybrid retrieval
  - `modules/rag/contracts.py`
  - `modules/rag/facade.py` — retrieve, find_similar_entities
  - `modules/rag/api.py`
  - `modules/rag/tests/`

**组 J — Writing 模块**（依赖：Project + Outline）
- 产出：
  - `modules/writing/README.md`
  - `modules/writing/models.py` — writing_drafts 表
  - `modules/writing/schemas.py`
  - `modules/writing/repositories.py`
  - `modules/writing/services.py`
  - `modules/writing/contracts.py`
  - `modules/writing/facade.py`
  - `modules/writing/api.py`
  - `modules/writing/tests/`

### Phase 4：集成与智能层（并行 2 组，依赖 Phase 3）

**组 K — Context 模块**（依赖：所有 Phase 2 + Phase 3 模块）
- 产出：
  - `modules/context/README.md`
  - `modules/context/services.py` — Context Compiler 核心逻辑
  - `modules/context/contracts.py`
  - `modules/context/facade.py` — compile_structure_context, render_context_markdown
  - `modules/context/tests/`

**组 L — Review 模块**（依赖：所有 Phase 2 + Phase 3 模块）
- 产出：
  - `modules/review/README.md`
  - `modules/review/models.py` — review_reports 表
  - `modules/review/schemas.py`
  - `modules/review/services.py`
  - `modules/review/contracts.py`
  - `modules/review/facade.py` — review_structure_candidate, get_review_report
  - `modules/review/api.py`
  - `modules/review/tests/`

### Phase 5：Prompt 体系（并行编写，贯穿各阶段）

**组 M — Prompts**
- 产出：
  - `prompts/shared_rules.md` — 所有 Prompt 共享规则
  - `prompts/structure_world_character.md` — 世界与人物结构生成 Prompt
  - `prompts/structure_plot.md` — 剧情结构生成 Prompt
  - `prompts/structure_chapter_scene.md` — 章节与场景结构生成 Prompt
  - `prompts/structure_review_memory.md` — 结构复查与状态抽取 Prompt

### Phase 6：集成测试与启动（依赖所有 Phase）

- `app/main.py` — FastAPI 应用入口，注册所有路由
- `tests/integration/` — 跨模块集成测试
- Docker Compose 基础配置
- Alembic 迁移初始版本

## 技术栈

- **运行环境**：Python 3.12+
- **Web 框架**：FastAPI
- **ORM**：SQLAlchemy 2.0 async
- **数据库**：PostgreSQL 17 + pgvector + pg_trgm
- **Schema 校验**：Pydantic v2
- **异步运行时**：uvicorn / httpx
- **测试**：pytest + pytest-asyncio
- **LLM 接入**：OpenAI-compatible API

## 模块文件结构规范

每个业务模块遵循统一结构：

```
modules/<name>/
├── README.md         # 职责、边界、数据表、对外契约、测试方式
├── __init__.py
├── contracts.py      # 对外契约（接口定义）
├── models.py         # SQLAlchemy ORM 模型
├── schemas.py        # Pydantic schema（输入/输出）
├── repositories.py   # 数据访问层
├── services.py       # 业务逻辑层
├── facade.py         # 对外入口（只代理，不写复杂逻辑）
├── api.py            # FastAPI 路由
└── tests/            # 测试文件
```

## 模块通信规则

- `modules/A` 可导入 `modules/B/contracts.py` 和 `modules/B/facade.py`
- 禁止 `modules/A` 直接导入 `modules/B/models.py`、`repositories.py`、`services.py`
- 禁止跨模块直接操作表
- API 层不写复杂业务逻辑
- facade 不写复杂业务逻辑

## 数据规则

- AI 生成内容不直接入正史
- 所有结构化结果先进入 candidate / proposal 状态
- 用户确认后才写入 canonical

## 执行策略

1. **Phase 1 为起始阶段** — Shared/Core、Infrastructure、Project 三组并行，依赖度最低
2. **Phase 2 核心业务** — World、Character、Geo、Memory+Timeline 四组并行
3. **Phase 3 创作核心** — Outline、RAG、Writing 三组并行
4. **Phase 4 集成层** — Context、Review 两组并行
5. **Phase 5 Prompt** — 与各阶段同步编写
6. 每组代码完成后运行 `pytest modules/<name>/tests/` 确保通过
7. 跨模块流程在 `tests/integration/` 中验证
