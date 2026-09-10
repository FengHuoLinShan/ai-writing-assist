# Story Scene 模块

Story 是作者工作台的 Scene 级派生层，保存人物卡的时点状态和 Scene 剧本文件的可编辑版本。
World 仍拥有 canonical Character，Outline 仍拥有 Scene；Story 通过 facade 校验二者，不把
人物卡或剧本写回 World、Memory、Writing。

## 物理 owner 融合

Story 同时拥有原 Outline 与 Memory 的唯一生产实现，内部子域位于
`backend/modules/story/outline_state` 与 `backend/modules/story/continuity`。保留原表名、任务
类型、CAS、snapshot/checkpoint/rollback、SceneSpan、Workbench、揭示状态和 TextArchive/World
回滚边界；旧 `backend/modules/outline` 与 `backend/modules/memory` 兼容层已在准备版本
完成固定 SHA 生产发布后退场。

融合后的完整 Story-owned 表清单为：`story_outline_heads`、`story_outline_revisions`、
`plot_threads`、`outline_arcs`、`scenes`、`scene_spans`、`scene_fusion_suggestions`、
`scene_summary_checkpoints`、`scene_chapter_links`、`foreshadowing_plans`、`reveal_plans`、
`memory_events`、`memory_snapshots`、`memory_scene_checkpoints`、`memory_scene_snapshots`、
`delta_log`，以及下方四张 Scene Story asset 表。公开 API 前缀不变：`/api/outline`、
`/api/novels/{novel_id}/memories`、`/api/story`。

## 对外能力

API 前缀为 `/api/story`。资源式路径提供人物卡 revision CRUD、恢复/归档，以及脚本文件的
多文件保存、revision 列表、采用、撤换采用和归档。Scene 工作台同时使用：

- `/scenes/{scene_id}/character-cards` 与 `/scenes/{scene_id}/character-cards/generate`
- `/scenes/{scene_id}/reactions/generate`
- `/scenes/{scene_id}/scripts`、`/scripts/generate`
- `/scenes/{scene_id}/simulate`

任务动作固定为 `story.character_card.generate`、`story.reaction.generate`、
`story.script.generate` 和 `story.one_click.simulate`，由 `async_tasks` 承载，不新增 Story run
表。四类 handler 都声明自动重排、最多两次尝试和可恢复的 task metadata。

## 数据与采用边界

迁移 `20260815_story_scene_assets` 创建四张表：
`story_character_cards`、`story_character_card_revisions`、`story_scene_script_files`、
`story_scene_script_revisions`。所有表有 `novel_id`；head/revision 通过复合唯一键和复合外键
阻止跨小说指针。人物卡按 `(novel_id, scene_id, character_id)` 唯一；脚本文件分离
`current_revision_id`（最近保存）与 `adopted_revision_id`（可供 Writing 执行的版本）。

`get_scene_story_assets` 是 Outline/Writing 的窄只读 seam，只投影当前人物卡和每个脚本文件的
文件 metadata + adopted revision；未采用的 current 草稿不会改变 execution bundle hash。
读取时分别用一次 `IN` 查询装载人物卡 current revision 与脚本 current/adopted revision；公共
Story baseline 只计算一次，再在内存派生排除当前脚本的 basis hash，返回字段和 stale 语义不变。

## AI、来源与用户控制

普通任务只返回严格 Pydantic 预览。人物卡、反应、剧本和 one-click 均使用作者确认的
Scene Context；worker 执行前重编译并比较通用指纹，只有显式 `submit_authorized` 时才可将缺失或 source hash 已变化的
人物卡写成带来源的 revision。反应、剧本、World、Memory、Writing 不会被这一步静默写入。
手工 apply 如携带 `source_task_id`/`context_snapshot_id`，必须指向同一小说、同一 Story action
的已完成任务，且 snapshot 与任务 result 一致；CAS 冲突返回 409 和当前 novel-scoped read
model，便于作者另存或重新应用。

目标画像是长期创作的专业或业余作家（产品假设）：用户会喜欢它，因为回到 Scene 时不用
重新拼接人物状态和剧本，且 AI 不会越权覆盖正史。前端验收应覆盖空态、长任务离开/恢复、
冲突、采用/撤换采用、保存反馈和窄屏；真实采用率与撤销率仍需上线后验证。

故事总览生成同样要求 action=`outline.story_outline.generate` 的 confirmation。作者意图、预计
篇幅与规划范围在检索前作为不可排除目标进入 Context；显式人物/对象选择必须与 confirmation
的 compile options 一致。StoryOutline 的领域背景可以补充执行资料，但自动页面、人物和对象
只从确认后的实际 selected assets 中选取，并把确认 Markdown 与通用指纹写入任务 provenance。
Scene 融合的请求 Scene 集合还必须与 confirmation 中的 pinned Scene 引用完全一致；provider
只接收重新物化的 confirmed Markdown，不再旁路加载完整 World/Outline 资料。

总览手工版本可携带既有结构的来源版本标识，源结构更新只提示核对，不双向覆盖。简单结构生成使用 main/sub/background 分类及显式兼容映射，参数版本 phase3_structure_simple_v3。
## 复核来源接口（ADR-0022）

`modules.story.facade` 新增只读反查 `list_plot_threads_referencing_entities(db, novel_id, entity_ids)`，
按故事线 `related_entity_ids` 返回声明依赖这些对象的 PlotThreadContract，供 World 模块的影响
预演枚举"故事结构"层来源。该接口不写任何 Story 状态，也不扩大生成上下文；Story 域内行为
不变。

## 项目助手与结构变化

ADR-0023 注册 Story 自有的版本化总纲、场景规划、人物卡和剧本操作；确认后调用原服务，
保留 provenance 与采用头。story_reference_review 只检查现有引用/basis失效，
不替代因果、人物或正文语义审稿。专业工作台继续拥有复杂调整与恢复体验。


信息计划编辑经原服务和版本预检。新剧本 basis v2 纳入章节/Scene/关联剧情线重叠的信息计划；
既有 v1 按原算法回验，新增 hash 字段不会使旧剧本自动失效。开放结尾的剧情线从已知起点延续。
结构采用/退役/移动保存旧受影响 Scene，再合并新范围到同事务待检标记，结果注明实际检查上限。

### 世界变更的结构来源

Story 经 list_world_dependencies/read_world_dependency 提供故事线、篇章纲、Scene 与当前总纲的只读版本依据，区分声明引用与名称提及。World 聚合复核与遗漏，Story 保留本域编辑和修订责任；检查不会改写故事结构或连续性状态。没有读者/场景可见性投影的规划资料不进入这些受限视角。
