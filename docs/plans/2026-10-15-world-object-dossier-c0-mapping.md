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

CoreEntity 的 `public_info` 汇总公开条目，`hidden_truth` 汇总秘密条目。其余固定类型 Profile 列按迁移映射到内核面向；数组与对象值在条目正文中保留可读显示，同时原 JSON 值留在 `legacy_value`，Profile 的 `source`、`confidence`、`evidence_refs_json` 和 `extra_json` 留在 `source_metadata`。别名仍由 `core_entities.content_json.aliases` 持有。

自定义 `GenericEntityProfile.data_json` 的旧 PUT 写入现已通过同一 Dossier revision 服务桥接：当前活动模板中 key/facing 唯一且有效的字段写成对应面向，否则写入 `legacy_unmapped` 秘密区；未知值不推断为公开。旧 GET/list 和 `WorldBackground` 从当前 Dossier 修订作只读兼容投影，GET 不物化或写回数据；写入才会将旧 JSON 中尚未桥接的字段追加为修订。`expected_dossier_revision` 是兼容性可选字段：调用方提供时按基线 CAS，冲突返回 409；旧客户端不提供时仍由实体/Profile 行锁串行化，整份 `data_json` 替换保持最后写者胜出，不代表旧客户端获得乐观并发保护。`exclude_unset` 保留 PATCH 语义；省略 `data_json` 不改值，显式 `data_json: null` 清除当前键并追加清除修订。类型转换快照保留通用值、未知区、template、source、status、confidence、evidence、extra 与迁移历史。Dossier 读投影从当前 Generic profile 只读叠加 `profile_status/source/confidence/evidence` 元数据；切为 draft/migrated 后，旧桥接值及其显式作者修订均不会因修订元数据旧而继续进入简报。只有 `source=legacy_import` 的桥接修订还需目标 Scene 有当前、已确认且有正文区间来源的 Story fact 证明同主体同值；后续显式作者 Dossier 修订不继承这个旧导入证明门槛，也不会被升级成 timeless。**字段级时点证明仍待 Sol 固定点审修**：当前 helper 校验 Story fact 自身的 field/source 配对，但尚未把该 fact 的 field 与 Generic profile 字段 key 绑定；不能据此宣称来源已对齐到具体旧字段。
旧 Profile 的当前地点控制者、物件所有者、秘密持有知情者和揭示状态保留在原列，不回填 World 稳定档案；这些是按故事时点变化的状态，后续由 Story 截止点投影读取。

## C2 消费端与操作契约

| 实际入口 / action | 档案能力 ID | 当前接入与边界 |
| --- | --- | --- |
| `POST /api/evidence/compilation/object-dossier-brief`；Assistant `evidence.object_dossier_brief.read` v1 | R0 只读简报 | 两入口共用 `ObjectDossierBriefRequest/Response` 与 Evidence facade；只读、free、无 apply，仍须当前项目和 Scene/对象归属校验。独立 `assistant_dossier_tools.py` 已声明操作目录清单；全局 Assistant route/registry 接线由共享写入批次完成。 |
| `story.character_card.generate`；Story HTTP 确认与任务，Assistant R1 v1 | `story.character_card` | 每人物独立 POV 和 Scene cutoff；卡片 v2 由服务端固定事实骨架，模型只提带本范围 source ID 的解释。对象档案/倾向参考各有独立默认关闭开关，省略不降级核心资料。 |
| `story.reaction.generate`；Story HTTP 确认与任务，Assistant R1 v2 | `story.reaction` | Reaction v2 每人物输出 2–4 张表演卡，每张有不同动机/表现和本人物已编译范围内 source ID；旧 v1 只读兼容。生成仅预览。 |
| `story.script.generate` | `story.script` | 本批补齐 Evidence action→参考能力映射；继续使用现有 Story script HTTP/task，不改变写入或采用行为。 |
| `world.ask` | `world.ask` | Evidence 已有 action consumer 和空间参考 loader；本批补入对象档案参考能力映射。两类参考都只在 capability 开关显式启用时加载。 |
| `assistant.turn` | `assistant.turn` | Evidence 能识别该 capability，但本树未找到 Assistant context compile 以 `consumer_action="assistant.turn"` 调用对象简报的实际入口；目前不能算已消费。后续 Assistant 接线须由服务端固定 action、沿同一确认/预算快照消费，且不得把工具返回的旧 snapshot 当作授权。 |
| `writing.generate`、`writing.targeted_revision`、`writing.semantic_review`、`writing.conflict_check.ai_review`；`story.one_click.simulate` | 同 action 的 capability ID | 既有 action 映射保留；本批未改 one-click simulation。 |

对象档案与倾向开关目前由 Evidence loader 分别读取 `object_dossier_enabled_capabilities`、`character_pattern_enabled_capabilities`，未配置时均为空集关闭；`only_adopted_patterns` 默认 `false`。当前 `core.config.Settings` 尚无这两个 tuple 设置字段和 env 解析，所以部署/应用尚无正式 opt-in 配置入口；需要后续加入 `OBJECT_DOSSIER_ENABLED_CAPABILITIES`、`CHARACTER_PATTERN_ENABLED_CAPABILITIES`（逗号分隔 capability ID、默认空 tuple），并测默认关闭、单独启用两维、能力隔离与未知 capability 不加载。本批没有修改配置层。

卡片/反应/剧本的确认用途由已知 Story action 在服务端解析为 `story_character_card`、`story_character_reaction`、`story_scene_script`；Story card/reaction 若提交与 action 不匹配的 retrieval purpose 会以 400 拒绝。`consumer_action` 仅为内部 `CompileOptions` 参数，不是客户端确认 schema 字段。R0 简报读取不创建 apply 事务或模型任务。

## 后端 `current_*` 命中与处置

以下 22 个非测试源码文件包含三个旧字段之一。C0 适配 Character 写入和 World 档案读口；现有消费者先保留兼容字段，并在下表指定的后续批次迁移到 Evidence/Story 接口。

| 文件 | 当前职责 | 处置 |
| --- | --- | --- |
| `backend/modules/evidence/compilation/services/context_compiler.py` | 人物卡提示渲染 | 已接 Evidence 简报为独立可选参考；current_* 仍标作者备注 |
| `backend/modules/imports/phase1a_context.py` | 导入阶段人物上下文 | 保持旧读法，三字段不解释为 Scene 状态 |
| `backend/modules/imports/spreadsheet_migration/ai_schemas.py` | 表格字段 schema | 保留旧列映射 |
| `backend/modules/imports/spreadsheet_migration/classify.py` | 表头识别 | 保留旧列映射 |
| `backend/modules/imports/spreadsheet_migration/constants.py` | 可迁移字段集 | 保留旧列映射 |
| `backend/modules/imports/spreadsheet_migration/planning.py` | 字段计划 | 保留旧列映射并写入 World 档案入口 |
| `backend/modules/imports/spreadsheet_migration/service.py` | 迁移展示名 | 保留作者确认后的兼容写入 |
| `backend/modules/story/outline_state/p20_context.py` | 故事资产相关性摘要 | 待 C2 消费端迁移；现有卡片值只作为作者备注 |
| `backend/modules/story/outline_state/scene_fusion_draft.py` | Scene 融合上下文 | 待 C2 消费端迁移；保留现有 wire |
| `backend/modules/story/schemas.py` | 人物卡 DTO | 保留历史字段形状 |
| `backend/modules/world/contracts.py` | 跨模块人物契约 | 兼容再出口；新读取方使用档案/Evidence 契约 |
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
| `frontend-console/vue/views/scene/useStorySceneWorkspace.js` | 待 C2 消费端迁移；保留旧卡片 fallback 并标注为作者备注 |
| `frontend-console/vue/views/project/logic/spreadsheetMigration.js` | 保留导入字段映射，由后端兼容写入桥接 |
| `frontend-console/vue/components/AssistantValue.vue` | 通用 JSON 展示词典，保持 |
| `frontend-console/vue/components/EvolutionPanorama.vue` | continuity 字段标签，保持；不可改成 World 静态资料 |
| `frontend-console/tests/vue/scene/StorySceneWorkspace.test.js` | 保留旧卡片兼容断言，并覆盖作者备注标签 |

## 后续依赖

- C1 Evolution 档案发现只能经 World 候选/修订预览入口写入；不直接采用条目。
- C2 Evidence 是跨层统一读取与简报唯一 owner；World facade 只返回设定层，Story port 返回 Scene 截止状态，Evolution read DI 接线另批完成。World context compiler 已接独立可选档案参考；P20、Scene fusion 与前端 Scene workspace 等剩余消费方仍待迁移。
- 导演和世界推进依赖 Evidence 简报；不得各自拼接 Character/Profile/continuity 数据。
