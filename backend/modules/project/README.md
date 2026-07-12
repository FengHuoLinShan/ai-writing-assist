# Module: project / 小说项目模块

## 定位

project 模块负责小说项目基础元信息，是其他所有模块的根。
其他模块通过 `novel_id` 引用项目，并通过 `facade.get_project_context()` 获取项目配置。

## 职责

- 创建小说项目
- 管理标题、题材、风格、语言
- 管理目标规模（字数/章节数）和当前创作阶段
- 提供 `novel_id` / `project_id`
- 提供项目级默认策略（如 `default_reveal_policy`）
- 提供项目级 LLM Profile（供应商、Base URL、模型、按供应商模板隔离的写入式 API Key）
- 提供项目级智能去重扫描入口，聚合各业务模块自己的去重建议

## 边界

明确不做：

- 世界观管理 / 人物管理 → world 模块
- 大纲管理 → outline 模块
- RAG 检索 → rag 模块
- 正文生成 → writing 模块

## 数据表

| 表名 | 用途 |
|------|------|
| `projects` | 小说项目基础元信息 |

### projects 表字段

- `id` — UUID 主键
- `title` — 项目标题（必填）
- `genre` — 题材（如：玄幻、科幻、悬疑）
- `tone` — 风格基调（如：严肃、轻松、黑暗）
- `language` — 创作语言（默认 `zh`）
- `target_length` — 目标规模（如：short, medium, novel, epic）
- `current_stage` — 当前创作阶段（如：world_building, outlining, writing, revising）
- `default_reveal_policy` — 默认揭示策略（默认 `author_safe`）
- `settings` — 小说配置（JSON，如 `temporary_entity_expiry_chapters`、`llm`）
- `created_at` / `updated_at` — 时间戳
- `deleted_at` — 软删除时间（`NULL` 表示未删除）

## 对外契约（contracts.py）

```python
class ProjectContract:
    """其他模块可依赖的项目契约"""
    novel_id: str
    title: str
    genre: str | None
    tone: str | None
    language: str
    target_length: str | None
    current_stage: str | None
    default_reveal_policy: str
```

## Facade（facade.py）

```python
async def get_project_context(db, novel_id: str) -> ProjectContext: ...

@asynccontextmanager
async def open_project_llm_client(
    db, novel_id: str, *, timeout_override: int | None = None
): ...

async def build_project_llm_execution_snapshot(
    db, novel_id: str
) -> dict: ...

async def restore_project_llm_execution_settings(
    db, novel_id: str, snapshot: dict
) -> dict: ...

def create_project_snapshot_llm_client(
    project_settings: dict,
    *,
    timeout_override: int | None = None,
    novel_id: str | None = None,
): ...
```

供其他模块获取项目上下文信息，包含项目基本元信息和策略配置。
所有带 `novel_id` 的业务文本/结构化 LLM 调用通过
`open_project_llm_client()` 获取 effective project profile。该 seam 统一执行
项目存在性、Key/Base URL/模型 fail-closed 校验、字段来源物化、脱敏 runtime
metadata 和成功/异常/取消时的 client 关闭；调用方不能传 provider/Key 绕过设置。
普通业务请求不填写 `LLMCallRequest.max_tokens` 时，由 client 物化项目有效默认值；
当前系统默认是 `12000`。只有深度导入阶段预算和健康检查可以显式覆盖该值。
深度导入 worker 消费已持久化的 effective profile snapshot 时，通过
`create_project_snapshot_llm_client()` 执行相同的 Key/Base URL/model/timeout
fail-closed 校验；传入 `novel_id` 时同时绑定脱敏的
`profile_source="project_snapshot"` runtime scope。调用方拥有并必须关闭返回的
client。

`build_project_llm_execution_snapshot()` 用于可恢复任务的提交时冻结：
只持久化 provider/model/非 secret 参数、字段来源、deep-import 设置、
Base URL/extra 的 hash 和脱敏摘要，不保存 API Key、完整 URL/query
或 extra values。`restore_project_llm_execution_settings()` 允许调用时使用
当前轮换后的 Key，但会拒绝 endpoint 或 provider-specific extra 漂移，
并继续使用任务提交时的 model/参数/字段来源。
deep-import 快照在提交时已将项目值、环境覆盖和代码默认
物化成显式字段，因此恢复期间的 env/default 变化不会改写已提交任务。

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{project_id}` | 项目详情 |
| PUT | `/api/projects/{project_id}` | 更新项目 |
| DELETE | `/api/projects/{project_id}` | 软删除项目（移至回收站） |
| GET | `/api/projects/recycle-bin` | 回收站列表 |
| GET | `/api/projects/llm/provider-templates` | LLM 供应商模板 |
| GET | `/api/projects/{project_id}/llm-settings` | 项目级 LLM 配置（不回显 API Key） |
| PUT | `/api/projects/{project_id}/llm-settings` | 更新项目级 LLM 配置 |
| POST | `/api/projects/{project_id}/smart-dedup/scan` | 提交项目级智能去重扫描任务 |
| POST | `/api/projects/{project_id}/smart-dedup/apply` | 应用用户确认的智能去重建议 |
| POST | `/api/projects/{project_id}/restore` | 恢复项目 |
| DELETE | `/api/projects/{project_id}/permanent` | 永久删除（级联清理） |

## 智能去重

`smart_dedup_scan` 是项目级聚合任务，只负责调用各模块 facade 并把建议写入
`AsyncTask.result`。实际资产判断和写入规则仍属于资产拥有模块：

- `world_entity` 走 world 的实体融合建议和确认合并 / 别名登记逻辑。
- `plot_thread`、`outline_arc`、`scene`、`foreshadowing_plan`、`reveal_plan`
  走 outline 的结构资产去重逻辑。

LLM 只生成建议；`smart-dedup/apply` 必须 `confirmed=true`。正史对象到正史对象的
世界对象合并仍需逐条 `allow_canonical_merge=true`。

### LLM 配置安全规则

- 当前模板使用的 `settings.llm.api_key` 与项目内按模板保存的 Key 均为加密写入字段；
  `ProjectResponse` 和专用 LLM 设置响应只返回 `api_key_configured` 以及不含密钥的
  `api_key_configured_providers`
- 写入密钥需要配置 `LLM_SETTINGS_ENCRYPTION_KEY`；旧明文值可兼容读取，并会在后续保存时转为密文
- 前端空提交 `api_key` 会保留已有密钥；`clear_api_key=true` 才清除
- 供应商模板切换会预填该模板的常用 Base URL、默认模型、显示名称和参数；保存时 Key
  绑定到当前项目的对应模板，回切模板会恢复该模板已保存的 Key
- managed step journal 只记录 `novel_id`、profile source 和脱敏
  `profile_summary`；不记录 Key、完整 Base URL query 或正文

## 测试方式

```bash
cd backend
python -m pytest modules/project/tests/ -v
```

## 依赖

- `core.database` — 数据库连接
- `core.base` — Base ORM、UUIDMixin、TimestampMixin
- `core.dependencies` — DbSession 依赖注入
- `shared.types` — NovelID 等类型别名
- `shared.enums` — 枚举定义
- `shared.constants` — DEFAULT_PAGE_SIZE 等常量

## 当前范围

除 CRUD 和项目上下文外，project 当前还拥有 effective LLM profile
物化、novel-scoped client lifecycle、可恢复任务的 secret-free execution
snapshot 和项目级智能去重聚合入口。它不拥有各业务模块的生成、
去重或采用规则。
