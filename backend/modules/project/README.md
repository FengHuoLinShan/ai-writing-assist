# Module: project / 小说项目模块

## 定位

project 模块负责统一项目隔离根。作者项目使用 `project_kind=author`；每个 RP 旅程另有一个
不出现在作者项目列表/回收站的 `project_kind=interaction` 隐藏项目。
其他模块通过 `novel_id` 引用项目，并通过 kind-aware facade 获取项目配置或门禁。

## 职责

- 创建作者项目和供 interaction 使用的隐藏隔离项目
- 管理标题、题材、风格、语言
- 管理目标规模（字数/章节数）和当前创作阶段
- 提供 `novel_id` / `project_id`
- 提供项目级默认策略（如 `default_reveal_policy`）
- 管理项目作者偏好覆盖，并组合 account 默认与项目覆盖形成 effective 配置
- 根据项目 owner 打开账户级文本与图片连接；项目只保留非 secret 工作流设置和可恢复 snapshot
- 提供项目级智能去重扫描入口，聚合各业务模块自己的去重建议
- 提供作者“今日工作”所需的只读工作台摘要，不返回正文、owner、密钥或内部任务信息

## 边界

明确不做：

- 世界观管理 / 人物管理 → world 模块
- 大纲管理 → outline 模块
- RAG 检索 → rag 模块
- 正文生成 → writing 模块
- RP 旅程、消息树与回顾 → interaction 模块

## 数据表

| 表名 | 用途 |
|------|------|
| `projects` | 小说项目基础元信息 |
| `project_author_preferences` | 每个项目最多一行的作者偏好覆盖 |
| `smart_dedup_workbench_decisions` | 项目级去重工作台的 `keep_separate` 指纹裁决 |

### projects 表字段

`owner_id → accounts.id` 为非空唯一所有者边界。项目 API、回收站、项目上下文和 worker
提交门禁都验证 owner；跨账号访问统一返回 404，业务响应不暴露 `owner_id`。

- `id` — UUID 主键
- `project_kind` — `author` 或 `interaction`；普通项目 API 默认只接受 `author`
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
class InteractionProjectContract:
    """interaction 创建隐藏隔离根后得到的窄契约"""
    novel_id: str
    owner_id: UUID
```

## Facade（facade.py）

```python
async def get_project_context(db, novel_id: str) -> ProjectContext: ...

async def require_active_project(db, novel_id: str) -> None: ...

async def require_active_project_exclusive(db, novel_id: str) -> None: ...

async def lock_project_ids_for_owner(db, owner_id: UUID) -> list[UUID]: ...

async def create_interaction_project(db, *, title: str) -> InteractionProjectContract: ...

async def require_interaction_project(db, novel_id: str) -> None: ...

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

@asynccontextmanager
async def open_project_image_client(db, novel_id: str, *, snapshot: dict | None = None): ...

async def build_project_image_execution_snapshot(db, novel_id: str) -> dict: ...
```

供其他模块获取项目上下文信息，包含项目基本元信息和项目拥有的非 secret
策略配置。该 interface 不解析账户运行时 provider/model/Key，也会防御性移除遗留
`api_key` / `api_keys_by_provider`；需要 LLM 的调用方必须使用下方 client/snapshot seam。
`require_active_project()` 是所有项目级业务入口的稳定门禁：项目不存在或已软删除
均返回同样的 404，调用方不得绕过该 seam 自行读取 project 内部实现。
该门禁在 PostgreSQL 上对活跃项目持有 `FOR SHARE` 行锁直到调用方事务结束：
并发读取互不阻塞，但 `deleted_at` 更新必须等待已通过门禁的业务写入/入队先提交或回滚。
软删除随后在自己的同一事务中取消刚提交的未完成任务，避免 guard 与业务
操作之间的 TOCTOU。调用方不得在 guard 和受保护写入之间提前提交。
`require_active_project_exclusive()` 是删除测试后仍必要的独立 seam：
普通 `FOR SHARE` 无法阻止 Scene/正文/对象并发写入，而需重验多类来源的
task finalizer 需要一个项目级短临界区。它在 PostgreSQL 上使用 `FOR UPDATE`，
只允许在无 provider/网络 I/O 的最终 DB 事务中持有；普通请求和长工作流
不得以它取代 `require_active_project()`。
`lock_project_ids_for_owner()` 只为账户级对象图片配额在短数据库事务内取得该 owner 的 advisory
transaction lock 后重算项目 ID；调用方仍要按这些 ID 保持 `novel_id` 过滤，不能把它当成 owner
或项目读取门禁，也不能在锁内进行图片处理或对象存储 I/O。
所有带 `novel_id` 的业务文本/结构化 LLM 调用通过
`open_project_llm_client()` 获取项目 owner 当前已验证的账户连接。该 seam 统一执行
项目存在性、owner、Key/Base URL/模型 fail-closed 校验、脱敏 runtime metadata 和
成功/异常/取消时的 client 关闭；调用方不能传 provider/Key 绕过账户设置。
普通业务请求不填写 `LLMCallRequest.max_tokens` 时，由 client 物化项目有效默认值；
当前系统默认是 `12000`。只有深度导入阶段预算和健康检查可以显式覆盖该值。
新增业务 LLM 服务必须复用此 seam，不得直接构造 `LLMClient` 或调用
`from_project_settings()`；`backend/tests/unit/test_novel_scoped_llm_usage.py` 对生产模块执行
静态门禁，并显式限制独立 embedding 等窄例外。
深度导入 worker 消费已持久化的 effective profile snapshot 时，通过
`create_project_snapshot_llm_client()` 执行相同的 Key/Base URL/model/timeout
fail-closed 校验；传入 `novel_id` 时同时绑定脱敏的
`profile_source="project_snapshot"` runtime scope。调用方拥有并必须关闭返回的
client。

`open_project_image_client()` 是地图册固定 `gpt-image-2` 的独立运行时 seam。它按项目 owner
解析 `openai-image` 加密凭据，固定 OpenAI base URL/model，不读取或修改文本
`active_provider_id`。可恢复任务只保存 provider/model/连接版本等 secret-free 字段，运行时
读取当前轮换后的账户 Key；缺少连接或 snapshot 漂移时 fail closed。

项目永久删除持 exclusive project lock，取消普通任务并经 world 的窄 facade 创建
`owner_scope=global`、`novel_id=NULL` 的地图册和对象图片 S3 前缀清理任务，再删除项目。该顺序
和图片上传的 share lock 共同阻止晚到对象；普通业务模块不能自行创建全局任务。

`build_project_llm_execution_snapshot()` 用于可恢复任务的提交时冻结：
只持久化账户 provider/model/非 secret 参数、字段来源、deep-import 设置、
Base URL/extra 的 hash 和脱敏摘要，不保存 API Key、完整 URL/query
或 extra values。`restore_project_llm_execution_settings()` 允许调用时使用同 provider
当前轮换后的账户 Key；即使账户切换到另一模板，旧任务仍按 snapshot 的 provider 恢复。
原 provider 凭据被清除时 fail-closed，并拒绝 endpoint 或 provider-specific extra 漂移，
并继续使用任务提交时的 model/参数/字段来源。
deep-import 快照在提交时已将项目值、环境覆盖和代码默认
物化成显式字段，因此恢复期间的 env/default 变化不会改写已提交任务。

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/{project_id}` | 项目详情 |
| GET | `/api/projects/{project_id}/workspace-summary` | 作者工作台摘要：续写位置、章节/字数统计和场景优先待处理事项 |
| PUT | `/api/projects/{project_id}` | 更新项目 |
| DELETE | `/api/projects/{project_id}` | 软删除项目（移至回收站）并取消未完成任务 |
| GET | `/api/projects/recycle-bin` | 回收站列表 |
| GET | `/api/projects/llm/provider-templates` | LLM 供应商模板 |
| GET | `/api/projects/{project_id}/llm-settings` | 兼容读取项目非 secret LLM/深度导入设置 |
| PUT | `/api/projects/{project_id}/llm-settings` | 兼容更新非 secret 项目设置；Key 写入被拒绝 |
| GET/PUT/DELETE | `/api/settings/projects/{project_id}/author-preferences` | 一版兼容的项目作者偏好覆盖 |
| GET | `/api/settings/projects/{project_id}/effective` | 一版兼容的有效配置投影 |
| POST | `/api/projects/{project_id}/smart-dedup/scan` | 提交项目级智能去重扫描任务 |
| POST | `/api/projects/{project_id}/smart-dedup/apply` | 应用用户确认的智能去重建议 |
| POST | `/api/projects/{project_id}/restore` | 恢复项目 |
| DELETE | `/api/projects/{project_id}/permanent` | 永久删除（级联清理） |
| POST | `/api/projects/recycle-bin/permanent-delete` | 批量永久删除回收站项目（最多 100 个，原子操作） |

`workspace-summary` 先通过项目 API 的当前账户 owner 与活跃作者项目门禁，再由
`ProjectWorkspaceService` 只读聚合 writing、world 和 outline 的稳定 facade。响应固定包含
`project_id`、可空 `continuation`、`writing` 和 `attention`；调用方不能传 owner 或额外
`novel_id`。`attention` 保留原分类计数和 `total`，并增加最多 6 条的 `items`、去重后的
`actionable_total` 与 `has_more`；截断后按领域处理范围去重的 `more_targets` 提供不绑定单条 item
的类型化队列入口（只有必须逐项打开的采用包保留精确 target），避免同类隐藏事项无法到达。每条只包含作者可读标题、摘要、行动类型、
严重度和类型化领域 target，不包含正文、原始任务或路由字符串。

调用方可传 `focus_chapter_index` / `focus_scene_id` 帮助 Today 排序；Scene 必须通过 Outline
稳定契约验证属于当前 `novel_id`，并以 `chapter_ids` 或 `scene_chunks` 与指定章节一致，否则只忽略 Scene 焦点。排序固定为当前
Scene、本章、项目级，再按需要决定、严重度、更新时间和稳定 key。最近正文只返回章节序号、
标题、更新时间和是否存在未正式化改动，不返回正文内容。任一业务投影都使用门禁确认后的同一
个 `project_id` 作为 `novel_id`，不建立跨模块 ORM 依赖，也不提供跨领域处理写入口。

单个和批量永久删除都必须显式提交 `confirmed=true`，且只能删除已在回收站的
项目。批量请求会去重 ID；任一项目不在回收站时整批拒绝，不会部分删除。

项目软删除与按 `novel_id` 取消 `pending/running` 任务在同一数据库事务中完成。
取消会清除 lease，记录 `transition_reason="project_soft_deleted"` 和结束时间；终态任务、
其他项目任务不受影响。恢复项目只恢复资产可访问性，不会重启已取消的旧任务。

## 智能去重

`smart_dedup_scan` 是项目级聚合任务，提交时先保存不含密钥的
LLM execution snapshot，worker 恢复冻结配置后调用各模块 facade。旧 pending
任务在第一次 LLM 调用前补建并持久化 snapshot。结果以 `schema_version=2`
返回 `groups`，同时保留 `suggestions` 供旧客户端降级展示。实际资产判断、
语义/执行指纹和写入规则仍属于资产拥有模块：

官方前端提交扫描前先持久化页内 `operation_id`；同一 ID 和请求指纹可在刷新后恢复
原任务（含终态），不同请求复用同一 ID 返回 409。该 receipt 只约束当前操作，不建立
账户级、项目级或跨设备扫描锁。

- `world_entity` 走 world 的实体融合建议和确认合并 / 别名登记逻辑。
- `plot_thread`、`outline_arc`、`scene`、`foreshadowing_plan`、`reveal_plan`
  走 outline 的结构资产去重逻辑。
  其中 Scene 会跳过来源指纹仍有效的 Phase 1c pending、dismissed、adopted 融合决定的
  来源对，以及 adopted 融合结果与其来源的组合；Scene 工作台是唯一处理入口，来源变化后可再次参加全局扫描。

LLM 只生成建议；`smart-dedup/apply` 必须 `confirmed=true`。新 group 路径还必须
携带同项目、已完成的 `scan_task_id`，服务端从任务结果重新校验成员、主对象、
动作白名单和 execution fingerprint。批量应用会在任何写入前预校验并锁定全部组的
execution fingerprint，再逐组使用独立 savepoint 原子执行；因此前一组迁移关系不会
把后一组误判为外部并发漂移，一组真实失败也不会阻断其他组。`keep_separate` 只对相同 pair 和 semantic fingerprints
生效；所属模块会在整组任何写入前校验所有当前 execution fingerprints，并在组内
融合完成后重新生成最终 semantic fingerprints，再由 project 保存 disposition。
同一组的 disposition 以一次项目锁和一次涉及 pair 的批量查询持久化，避免随历史裁决
数量重复全表扫描。
任一对象语义变化后旧裁决失效。正史融合与正史别名化分别需要
`allow_canonical_merge` / `allow_canonical_alias`。

### LLM 配置安全规则

- provider、model 和 Key 的运行时真相源是项目 owner 的账户级连接；项目 LLM API 不得再
  写入 Key，migration 会不可逆清除 `api_key` / `api_keys_by_provider` 遗留字段
- 账户凭据按 owner/provider 唯一并使用 `LLM_SETTINGS_ENCRYPTION_KEY` 加密；project
  context/contract、response、task meta、snapshot、日志和 producer provenance 均不返回密钥
- 项目内遗留的 provider/model/Base URL 字段仅为兼容读取或工作流配置，不能覆盖账户模板
- 切换账户模板只影响新任务；已持久化 snapshot 按原 provider 增量恢复，不重建已有资产
- managed step journal 只记录 `novel_id`、profile source 和脱敏
  `profile_summary`；不记录 Key、完整 Base URL query 或正文
- 公开模式下，无显式 `LLM_PROXY_URL` 时只允许内置供应商的 HTTPS 域名，并在运行时
  复核 DNS，不接受用户控制 DNS 的自定义目标。自定义 OpenAI-compatible Base URL 必须
  经过运维显式配置的出站代理，由代理承担私网阻断和域名解析边界；`LLM_TRUST_ENV`
  不等价于该显式代理。`local / closed_test` 继续允许本机 Ollama 等 HTTP loopback。

## 测试方式

project 的 `settings_service.py` 拥有项目偏好与 effective composition；它只经 account facade
读取账户默认，不读取 account ORM/repository。`/api/settings` 路径仅是一版 HTTP 兼容别名，
领域所有权仍由 account/project 分开承担。

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

除 CRUD 和项目上下文外，project 当前还拥有 author/interaction kind 门禁、隐藏互动项目
生命周期、账户连接解析、novel-scoped client lifecycle、可恢复任务的 secret-free
execution snapshot 和项目级智能去重聚合入口。它不拥有各业务模块的生成、去重或采用规则。
