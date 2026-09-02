# Module: project / 小说项目模块

## 定位

project 模块是每部小说的根聚合。所有小说业务模块通过 `novel_id` 关联到项目；公开身份与
浏览器会话由 `account` 拥有，project 只通过 account facade 执行 owner 门禁。

## 数据表

- `projects` — id / owner_id / title / genre / tone / language / target_length / current_stage / default_reveal_policy / settings / deleted_at
- `project_author_preferences` — 每个项目最多一行的作者偏好覆盖
- `project_author_tasks` — 按 `novel_id` 隔离的轻量作者待办；封闭来源只保存 kind + 同项目对象 ID

`owner_id → accounts.id` 非空。项目 API、回收站、项目上下文和 worker 提交门禁均按当前
owner 过滤；跨账号访问返回 404，业务响应不返回 `owner_id`。owner 门禁不替代任何
`novel_id` 查询条件。

### settings 字段

JSONB 配置字段，存储项目级可调参数，如 `temporary_entity_expiry_chapters` 等。
业务 LLM 的 provider/model/API Key 不再由项目拥有：Key 按 owner 加密保存在
`account_llm_credentials`，当前 DeepSeek/Kimi 模板由 account 解析；project 只经 account facade
读取 secret-free contract 并负责 effective composition。
隐藏 consumer 可显式绑定同 owner author 项目的不可变 RP source revision，但这只是版本化
只读 Evidence 例外；来源查询仍用 author `novel_id`，旅程写入仍用 interaction `novel_id`。
`settings.llm` 只保留旧项目的非 secret 兼容字段，`settings.deep_import` 继续承载项目级
深度导入参数；任何项目创建、通用更新或兼容 LLM 设置接口中的 Key 写入都会被拒绝。

可恢复任务由 project facade 生成不含 secret 的执行快照，冻结提交时的
provider/model/预算与配置哈希；执行时按项目 owner 重新读取该 provider 的当前账户 Key，
因此轮换 Key 不要求重建既有任务，也不会把密钥写进任务 API、日志或项目详情。

地图册图片运行时使用独立 `open_project_image_client()` 与 secret-free 图片快照，固定
`gpt-image-2`，不改变文本 provider。账户级对象图片配额通过
`lock_project_ids_for_owner()` 在短事务中锁住该 owner 的项目 ID 后重算，不能替代后续
`novel_id` 过滤或在锁内进行对象存储 I/O。永久删除取得项目排他锁，取消普通任务并创建
`owner_scope=global`、`novel_id=NULL` 的地图册和对象图片 S3 前缀清理任务后再级联删除，阻止
晚到上传。

### deleted_at 字段

软删除标记。`DELETE` 接口仅设置 `deleted_at`，数据不动。回收站 API 可列出/恢复/永久删除已软删除的项目。

## 回收站流程

```
用户点击"删除项目" → 标记 deleted_at（软删除）
    ↓
回收站中列出已删除项目
    ↓
恢复 → 清空 deleted_at
永久删除 → 级联 DELETE 所有 novel_id 关联行
```

如果 author 项目的 source revision 仍被任一 RP 旅程引用，永久删除在进入级联前返回
409；软删除/恢复语义不变。此计数只经 interaction DI port 读取，project 不导入其 ORM。

## 服务

- ProjectService：项目 CRUD + 软删除/恢复/永久删除；创建作者项目时在同一
  事务内通过 world facade 初始化空 `C0` 与唯一 Canon head，失败则项目不落库
- ProjectWorkspaceSummaryService：在 owner/活跃作者项目门禁后，只读聚合续写位置、章节/字数和场景优先待处理事项
- AuthorTaskService：在同一 owner + `novel_id` 边界内持有项目 `FOR SHARE` 门禁，新建、分组、完成/重开与归档作者任务，并经稳定 facade 解析来源；变更用 `expected_updated_at` 防止晚到响应覆盖新状态

## Facade

```python
async def get_project_context(db, novel_id) -> ProjectContext | None
async def lock_project_ids_for_owner(db, owner_id) -> list[UUID]
```

`ProjectContext` 只包含 project 拥有的非 secret 配置，并防御性清理遗留 Key；它不再
物化账户运行时 provider/model/Key。LLM 调用通过 project 的 client 或 secret-free
execution snapshot seam 解析当前 owner 凭据；snapshot 还一次冻结 infrastructure-owned
model capability profile 与 hash，业务模块不得再维护平行窗口表。

`initialize_world_canon()` 是项目创建组合根唯一使用的窄 world facade；project
不读写 Canon 表、manifest 或 receipt，后续准入仍完全归 world 拥有。

## API

```
POST   /api/projects                          # 创建项目
GET    /api/projects                           # 项目列表
GET    /api/projects/{id}                      # 项目详情
GET    /api/projects/{id}/workspace-summary    # 今日工作只读摘要，可带作者本地 on_date
GET/POST /api/projects/{id}/author-tasks        # 列出分组或新建作者任务
PATCH  /api/projects/{id}/author-tasks/{task_id} # 编辑/完成/重开/归档/恢复
PUT    /api/projects/{id}                      # 更新项目
DELETE /api/projects/{id}                      # 软删除（移至回收站）
GET    /api/projects/recycle-bin               # 回收站列表
GET    /api/projects/llm/provider-templates     # 兼容的供应商模板清单
GET    /api/projects/{id}/llm-settings          # 读取项目非 secret 兼容设置
PUT    /api/projects/{id}/llm-settings          # 更新非 secret 兼容设置；拒绝 Key
GET    /api/projects/{id}/effective-llm-settings # canonical 有效 LLM 配置投影
GET    /api/projects/{id}/effective-author-preferences # canonical 有效作者偏好投影
GET/PUT/DELETE /api/projects/{id}/author-preferences # canonical 项目偏好覆盖
POST   /api/projects/{id}/smart-dedup/scan      # 提交跨模块去重建议扫描
POST   /api/projects/{id}/smart-dedup/apply     # 应用已确认的去重建议
POST   /api/projects/{id}/restore              # 恢复项目
DELETE /api/projects/{id}/permanent            # 永久删除（级联）
```

工作台摘要固定返回 `project_id`、可空 `continuation`、`writing`、`attention` 与加性 `author_tasks`。`attention`
保留原计数和 `total`，增加最多 6 条 `items`、`actionable_total`、`has_more`，以及按领域类型
去重且不绑定单条 item 的隐藏领域入口 `more_targets`；除必须逐项打开的 `world_adoption` 采用包外，该入口清空 item/chapter/Scene/page/suggestion 定位字段。API 先通过
当前账户项目读取门禁，再以同一 ID 调用 writing/world/outline 稳定 facade；调用方不能指定 owner
或额外 `novel_id`。可选 `focus_chapter_index` / `focus_scene_id` 只影响固定排序，Scene 必须经
Outline seam 验证属于当前项目，并以 `chapter_ids` 或 `scene_chunks` 验证指定章节。该投影不返回正文、内部任务、密钥或 owner 信息，
空作品返回零计数、空事项和空续写位置。

`author_tasks` 摘要只返回今日/收件箱/之后计数和最多 3 条今日预览。任务本体只有
标题、可选备注/日期、`open/completed/archived` 与一个封闭来源；请求不接受 owner/
`novel_id` 或任意路由。来源限于 `world_page | world_entity | writing_chapter | outline_scene`，
经对应模块 facade 验证同项目。失效来源不删任务，已归档任务不硬删除。

项目级智能去重只聚合各资产模块的建议；`schema_version=2` 任务结果同时提供
group 裁决和 legacy suggestions。group apply 必须引用原扫描任务，服务端以任务结果
校验成员、动作和 execution fingerprint，并以每组 savepoint 保证组内原子、组间
独立。实体或结构资产的判断、指纹和实际写入仍由 world / outline 拥有。
`smart_dedup_workbench_decisions` 只保存当前 pair 和 semantic fingerprints 的
`keep_separate`，不替代两个资产模块的领域权威。

智能去重扫描接受可选 `operation_id` 以兼容旧客户端；官方前端提交前持久化 UUID，并以
该 UUID 恢复原任务和裁决工作台。相同 receipt 的不同请求返回 409；不同标签页或设备仍可
各自发起扫描，不增加项目级排他锁。
