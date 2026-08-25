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

## AI、来源与用户控制

普通任务只返回严格 Pydantic 预览。独立任务使用作者确认的 Context；one-click 自动编译
Context 并创建 snapshot，只有显式 `submit_authorized` 时才可将缺失或 source hash 已变化的
人物卡写成带来源的 revision。反应、剧本、World、Memory、Writing 不会被这一步静默写入。
手工 apply 如携带 `source_task_id`/`context_snapshot_id`，必须指向同一小说、同一 Story action
的已完成任务，且 snapshot 与任务 result 一致；CAS 冲突返回 409 和当前 novel-scoped read
model，便于作者另存或重新应用。

目标画像是长期创作的专业或业余作家（产品假设）：用户会喜欢它，因为回到 Scene 时不用
重新拼接人物状态和剧本，且 AI 不会越权覆盖正史。前端验收应覆盖空态、长任务离开/恢复、
冲突、采用/撤换采用、保存反馈和窄屏；真实采用率与撤销率仍需上线后验证。
