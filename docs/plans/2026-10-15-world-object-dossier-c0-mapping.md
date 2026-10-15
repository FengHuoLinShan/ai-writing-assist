# 世界对象档案 C0 字段与调用方映射

本文记录 ADR-0039 C0 的现状映射，作为旧接口接入 World 档案条目的回归清单。迁移保留原列和原响应字段；World 条目保存稳定设定，Story continuity 保存按 Scene 生效的状态，Evolution 台账保存正文归纳出的理解。

## Character 旧字段映射

| 旧字段 | World 内核面向 | C0 行为 |
| --- | --- | --- |
| `role` | `identity_position` | 人物身份与社会位置 |
| `appearance` | `appearance` | 人物外貌 |
| `personality` | `personality` | 性格倾向 |
| `desire` / `fear` | `desire_fear` | 同一面向、分别保留原字段键 |
| `secret` | `secret` | 秘密可见性 |
| `weakness` | `abilities_limits` | 能力限制 |
| `stance` | `values_boundaries` | 立场与底线 |
| `voice_style` | `speech_style` | 说话方式 |
| `behavior_rules` | `habits` | 保留结构化旧值，展示文本另行渲染 |
| `relationship_summary` | `relationship_summary` | 保留原叙述，不解析成 `EntityRelation` |
| `current_goal` | 不属于稳定档案面向 | 保留为作者最新状态备注；按 Scene 的目标由 Story 状态读取 |
| `current_state` | 不属于稳定档案面向 | 保留为作者最新状态备注；按 Scene 的状况由 Story 状态读取 |
| `current_emotion` | 不属于稳定档案面向 | 保留为作者最新状态备注；按 Scene 的情绪由 Story 状态读取 |

旧 `Character` 更新只处理请求中出现的字段。字符串或结构化值与当前拼接值相同时不新增档案修订；值变化时，旧值保留在可恢复历史，新值成为该旧字段当前修订；显式 `null` 清除该字段的当前值。`expected_updated_at` 仍由行锁保护并发基线，过期或缺失返回 409。

同一面向可有多条当前档案条目；数据库只保证每个条目组有一个当前修订，不限制一个旧字段键下的当前条目数。旧人物响应仅聚合显式带 `legacy_field_key` 的条目，按创建时间、组 UUID、修订号和条目 UUID 稳定排序；文本用换行连接，`behavior_rules` 列表按项合并。旧接口改写时，把该键下所有当前条目标为过时并追加一个新修订；恢复仍追加修订。自由条目不携带旧键时不会误并入 `desire` 或 `fear`，两字段共享 `desire_fear` 面向但始终按不同旧键读取。

CoreEntity 的 `public_info` 汇总公开条目，`hidden_truth` 汇总秘密条目。其余固定类型 Profile 列按迁移映射到内核面向；数组与对象值在条目正文中保留可读显示，同时原 JSON 值留在 `legacy_value`，Profile 的 `source`、`confidence`、`evidence_refs_json` 和 `extra_json` 留在 `source_metadata`。自定义 `GenericEntityProfile.data_json` 在模板字段 key 与正式档案面向建立确定映射前仍由旧 Profile 服务保存，不伪造新词表项。别名仍由 `core_entities.content_json.aliases` 持有。
旧 Profile 的当前地点控制者、物件所有者、秘密持有知情者和揭示状态保留在原列，不回填 World 稳定档案；这些是按故事时点变化的状态，后续由 Story 截止点投影读取。

## 后端 `current_*` 命中与处置

以下 22 个非测试源码文件包含三个旧字段之一。C0 适配 Character 写入和 World 档案读口；现有消费者先保留兼容字段，并在下表指定的后续批次迁移到 Evidence/Story 接口。

| 文件 | 当前职责 | 处置 |
| --- | --- | --- |
| `backend/modules/evidence/compilation/services/context_compiler.py` | 人物卡提示渲染 | C2 改读 Evidence 简报；当前值仍标作者备注 |
| `backend/modules/imports/phase1a_context.py` | 导入阶段人物上下文 | 保持旧读法，三字段不解释为 Scene 状态 |
| `backend/modules/imports/spreadsheet_migration/ai_schemas.py` | 表格字段 schema | 保留旧列映射 |
| `backend/modules/imports/spreadsheet_migration/classify.py` | 表头识别 | 保留旧列映射 |
| `backend/modules/imports/spreadsheet_migration/constants.py` | 可迁移字段集 | 保留旧列映射 |
| `backend/modules/imports/spreadsheet_migration/planning.py` | 字段计划 | 保留旧列映射并写入 World 档案入口 |
| `backend/modules/imports/spreadsheet_migration/service.py` | 迁移展示名 | 保留作者确认后的兼容写入 |
| `backend/modules/story/outline_state/p20_context.py` | 故事资产相关性摘要 | C2 改读 Evidence 简报；现有卡片值只作为作者备注 |
| `backend/modules/story/outline_state/scene_fusion_draft.py` | Scene 融合上下文 | 后续改读 Evidence/Story Scene 投影；保留现有 wire |
| `backend/modules/story/schemas.py` | 人物卡 DTO | 保留历史字段形状 |
| `backend/modules/world/contracts.py` | 跨模块人物契约 | C2 兼容再出口；新读取方使用档案/Evidence 契约 |
| `backend/modules/world/models/character.py` | Character 兼容列 | 保留；`current_*` 不搬到 World 条目 |
| `backend/modules/world/repositories.py` | Character 持久化 | 旧列同步更新，允许显式 null 清除 |
| `backend/modules/world/schemas/characters.py` | Character API schema | 保留字段与 CAS 语义 |
| `backend/modules/world/schemas/context.py` | 人物上下文 DTO | 兼容输出，注明三字段为作者备注 |
| `backend/modules/world/services/core/character_service.py` | Character CRUD/context | 旧写回桥接档案条目；按 Scene 读取留给 Story/Evidence |
| `backend/modules/world/services/core/dedup_service.py` | 人物合并 | 保留旧字段合并并经 Character 档案写回 |
| `backend/modules/world/services/entity_baselines.py` | 实体字段基线 | 保留旧字段指纹，避免回滚/基线漂移 |
| `backend/modules/world/entity_fusion.py` | 融合任务状态指纹 | 命中为同名局部变量，不是 Character 字段消费者，保持 |
| `backend/modules/story/continuity/scene_projection.py` | checkpoint 修复状态 | 命中为同名局部变量，不是 Character 字段消费者，保持 |
| `backend/modules/world/services/core/entity_revision_service.py` | 实体修订快照变量 | 命中为通用局部状态，不是 Character `current_*` 消费者，保持 |
| `backend/evals/rp_long_memory.py` | 评测样本状态字典 | 命中为评测局部状态，不是 Character Profile 读取方，保持 |

## 前端六处命中

| 文件 | 处置 |
| --- | --- |
| `frontend-console/vue/views/world/library/WorldEntityDetail.vue` | 后续对象档案 UI 改读档案 API；本轮保留旧 API 可用 |
| `frontend-console/vue/views/scene/useStorySceneWorkspace.js` | C2 改读 Evidence/Story Scene 投影；保留旧卡片 fallback 并标注为作者备注 |
| `frontend-console/vue/views/project/logic/spreadsheetMigration.js` | 保留导入字段映射，由后端兼容写入桥接 |
| `frontend-console/vue/components/AssistantValue.vue` | 通用 JSON 展示词典，保持 |
| `frontend-console/vue/components/EvolutionPanorama.vue` | continuity 字段标签，保持；不可改成 World 静态资料 |
| `frontend-console/tests/vue/scene/StorySceneWorkspace.test.js` | 保留旧卡片兼容断言，并覆盖作者备注标签 |

## 后续依赖

- C1 Evolution 档案发现只能经 World 候选/修订预览入口写入；不直接采用条目。
- C2 Evidence 是跨层统一读取与简报唯一 owner；World facade 只返回设定层，Story port 返回 Scene 截止状态，Evolution read DI 接线另批完成。
- 导演和世界推进依赖 Evidence 简报；不得各自拼接 Character/Profile/continuity 数据。
