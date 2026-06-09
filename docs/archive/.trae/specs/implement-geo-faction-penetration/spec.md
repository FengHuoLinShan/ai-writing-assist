# 地缘/势力资产动态渗透系统 Spec

## Why
当前 AI 提取管道仅生成记忆提案，确认后只写入 `memory_records`，无法将地缘变动（势力割据、角色位移）自动渗透到 `relationships`、`characters.meta`、`chapter_cards.involved_*` 等事实层表。创作者需要手动维护这些关联，导致地图视图与实际剧情脱节。

## What Changes
- 新增 `geo/facade.py` 跨模块接口：`find_location_id_by_name`、`upsert_spatial_relationship`
- 新增 `character/facade.py` 跨模块接口：`find_character_id_by_name`、`update_character_location`
- 新增 `outline/facade.py` 跨模块接口：`merge_chapter_involved_ids`
- 扩展 `memory/services.py` 的 `confirm_memory_proposal`：确认含 `geo_mutations` 的提案时，自动多路分发到 geo/character/outline 模块
- 新增 `memory/schemas.py` 的 `ChapterStateExtraction` Pydantic 校验模型（含 `character_shifts`、`faction_shifts`）
- 新增 `writing/api.py` 的 `POST /api/writing/save-and-analyze` 端点（保存草稿 + AI 提取 + 降级保护）
- 扩展前端 `writingView.js`：保存并分析按钮
- 扩展前端 `memoryView.js`：地缘变更提案卡片渲染
- 扩展前端 `geoView.js`：右侧面板势力/活跃人物查询 + 角色链接跳转

## Impact
- Affected specs: memory 提案确认流程、writing 保存流程、geo 地点详情查询
- Affected code:
  - `backend/modules/geo/facade.py` — 新增 2 个方法
  - `backend/modules/geo/repositories.py` — 新增名称查找、关系 upsert
  - `backend/modules/character/facade.py` — 新增 2 个方法
  - `backend/modules/character/repositories.py` — 新增名称查找、meta 擦写
  - `backend/modules/outline/facade.py` — 新增 1 个方法
  - `backend/modules/outline/repositories.py` — 新增 involved_ids 合并
  - `backend/modules/world/facade.py` — 新增 `upsert_relationship` 方法
  - `backend/modules/world/repositories.py` — 新增关系 upsert
  - `backend/modules/memory/services.py` — 扩展 `confirm_memory_proposal`
  - `backend/modules/memory/schemas.py` — 新增 `ChapterStateExtraction`
  - `backend/modules/writing/api.py` — 新增 `save-and-analyze` 端点
  - `frontend-console/views/writingView.js` — 保存并分析按钮
  - `frontend-console/views/memoryView.js` — 地缘提案卡片
  - `frontend-console/views/geoView.js` — 势力/人物面板

## ADDED Requirements

### Requirement: Geo 名称查找与关系覆写

系统 SHALL 提供 `geo.facade.find_location_id_by_name(db, novel_id, name)` 方法，通过 `world_entities.name` 精确匹配或 `entity_aliases.alias` 模糊匹配获取 `canonical` 状态的地理实体 UUID。匹配优先级：精确名称 > 别名匹配 > 返回 None。

系统 SHALL 提供 `world.facade.upsert_relationship(db, novel_id, source_id, target_id, relation_type, description)` 方法，对 `relationships` 表执行幂等覆写：先查 `source_id + target_id + relation_type IN ('controls','stationed_at','hidden_presence')`，存在则更新 `description` 和 `updated_at`，不存在则插入新行。

#### Scenario: 势力控制关系覆写
- **WHEN** AI 提取"血狼帮控制炎城"，确认提案后调用 `upsert_relationship(novel_id, faction_id, location_id, 'controls', '血狼帮夺取炎城控制权')`
- **THEN** `relationships` 表中存在一条 `source_type='faction', source_id=faction_id, target_type='location', target_id=location_id, relation_type='controls'` 的 canonical 记录

#### Scenario: 名称查找精确匹配
- **WHEN** 调用 `find_location_id_by_name(db, novel_id, '炎城')`
- **THEN** 返回 `world_entities` 中 `name='炎城' AND entity_type='location' AND status='canonical'` 的 UUID

#### Scenario: 名称查找别名匹配
- **WHEN** `world_entities` 中无 `name='炎城'` 但 `entity_aliases` 中有 `alias='炎城'` 关联到某 location 实体
- **THEN** 返回该实体的 UUID

### Requirement: Character 名称查找与位置擦写

系统 SHALL 提供 `character.facade.find_character_id_by_name(db, novel_id, name)` 方法，通过 `characters.name` 精确匹配或 `characters.aliases` JSON 数组中的 `alias` 字段匹配获取角色 UUID。

系统 SHALL 提供 `character.facade.update_character_location(db, novel_id, character_id, location_id, text_state, chapter_index)` 方法，原子覆写 `characters.meta` JSONB 字典中的 `current_location_id` 和 `last_updated_chapter` 键值，同时更新 `characters.current_state` 文本字段。

#### Scenario: 角色位移更新
- **WHEN** 确认提案"林动御剑飞行至炎城"，调用 `update_character_location(db, novel_id, char_id, loc_id, '目前正御剑飞行前往炎城。', 45)`
- **THEN** `characters.meta['current_location_id'] == loc_id`，`characters.meta['last_updated_chapter'] == 45`，`characters.current_state == '目前正御剑飞行前往炎城。'`

### Requirement: ChapterCard 关联资产增量合并

系统 SHALL 提供 `outline.facade.merge_chapter_involved_ids(db, novel_id, chapter_index, character_ids, entity_ids)` 方法，对 `chapter_cards` 表中 `chapter_index` 匹配的记录，将新 ID 追加到 `involved_character_ids` 和 `involved_entity_ids` JSONB 数组，使用 `set()` 去重后写回。

#### Scenario: 章节关联增量合并
- **WHEN** 章节卡已有 `involved_character_ids=['char-a']`，调用 `merge_chapter_involved_ids(db, novel_id, 5, ['char-b', 'char-a'], ['loc-1'])`
- **THEN** `involved_character_ids=['char-a', 'char-b']`（去重），`involved_entity_ids=['loc-1']`

### Requirement: Memory 提案确认多路分发

系统 SHALL 扩展 `memory.services.confirm_memory_proposal`，当提案的 `payload` 中包含 `geo_mutations` 键时，在写入 canonical memory 后，自动执行以下分发事务：
1. 遍历 `payload.geo_mutations.character_shifts`，对每条调用 `character.facade.find_character_id_by_name` + `geo.facade.find_location_id_by_name` + `character.facade.update_character_location`
2. 遍历 `payload.geo_mutations.faction_shifts`，对每条调用 `world.facade.upsert_relationship`
3. 调用 `outline.facade.merge_chapter_involved_ids` 将涉及的 character_ids 和 entity_ids 追加到对应章节卡

若任一分发步骤失败，记录错误日志但不回滚 canonical memory 写入（memory 优先保证）。

#### Scenario: 确认含地缘变动的提案
- **WHEN** 用户确认一条 `proposal_type='chapter_state'` 且 `payload` 含 `geo_mutations={character_shifts: [{character_name: '林动', destination_location_name: '炎城', movement_type: '御剑飞行'}], faction_shifts: [{faction_name: '血狼帮', target_location_name: '炎城', new_relation: 'controls', description: '血狼帮夺取炎城'}]}` 的提案
- **THEN** canonical memory 已创建，`characters` 表中林动的 `meta.current_location_id` 已更新，`relationships` 表中已插入/更新血狼帮→炎城的 controls 关系，`chapter_cards` 的 `involved_character_ids` 和 `involved_entity_ids` 已增量合并

#### Scenario: 分发部分失败降级
- **WHEN** 角色名"林动"在数据库中找不到（`find_character_id_by_name` 返回 None）
- **THEN** 跳过该条 character_shift，记录 warning 日志，不影响其他分发和 canonical memory

### Requirement: AI 结构化提取管道与降级

系统 SHALL 提供 `POST /api/writing/save-and-analyze` 端点，接收 `{novel_id, chapter_index, content}` 请求：
1. 先保存草稿到 `writing_drafts`（100% 保证成功）
2. 再调用 LLM 结构化提取，使用 `ChapterStateExtraction` Pydantic 模型校验输出
3. 将提取结果存入 `memory_update_proposals`（`proposal_type='chapter_state'`）
4. 返回 `{draft_id, proposal_created: bool}`

LLM 调用必须包裹在独立 `try...except` 中，超时/格式错误时仅记录日志，`proposal_created=false`，草稿保存不受影响。

#### Scenario: 正常提取
- **WHEN** 用户点击"保存并让 AI 分析"，正文包含"林动御剑飞往炎城"
- **THEN** 草稿已保存，提案已创建，响应 `proposal_created=true`

#### Scenario: LLM 超时降级
- **WHEN** LLM 调用超时或返回非法 JSON
- **THEN** 草稿已保存，无提案创建，响应 `proposal_created=false`，后端记录 error 日志

### Requirement: ChapterStateExtraction Pydantic 校验模型

系统 SHALL 在 `memory/schemas.py` 中定义 `ChapterStateExtraction` 模型：
- `summary: str` — 情节主线总结
- `character_shifts: list[CharacterLocationShift]` — 角色位移列表
- `faction_shifts: list[FactionControlShift]` — 势力割据变更列表

`CharacterLocationShift` 字段：`character_name: str(min_length=1)`、`destination_location_name: str(min_length=1)`、`movement_type: str`

`FactionControlShift` 字段：`faction_name: str(min_length=1)`、`target_location_name: str(min_length=1)`、`new_relation: str`、`description: str`

`new_relation` 必须通过 `field_validator` 校验，仅允许 `'controls'`、`'stationed_at'`、`'hidden_presence'`，非法值降级为 `'stationed_at'`。

### Requirement: 前端 writingView 保存并分析按钮

系统 SHALL 在 `writingView.js` 的编辑区上方注入"保存并让 AI 分析地缘资产"按钮，点击后调用 `POST /api/writing/save-and-analyze`，成功后更新 `state.pending_proposals_count` 并显示 toast。

### Requirement: 前端 memoryView 地缘提案卡片

系统 SHALL 在 `memoryView.js` 中，当提案 `payload` 含 `character_shifts` 或 `faction_shifts` 时，渲染为 `.geo-proposal-card` 样式卡片，将 JSON 结构转为中文标签展示：
- 人物变动：角色 `【名】` `[行为]` 至 `【地点】`
- 割据变动：组织 `【名】` 对 `【地点】` 的状态转为 `[关系]`

### Requirement: 前端 geoView 势力与活跃人物面板

系统 SHALL 在 `geoView.js` 右侧详情面板中，当用户点击地点节点时，额外查询：
1. `GET /api/geo/location/{id}/factions` — 返回控制/驻扎该地的势力列表
2. `GET /api/geo/location/{id}/characters` — 返回 `meta.current_location_id` 匹配的活跃人物列表

势力列表以纯文本标签展示，活跃人物列表中每个名字为可点击链接，点击后通过 `router.go('character')` 携带 ID 跳转到人物卡视图。

## MODIFIED Requirements

### Requirement: Memory 提案确认流程扩展

原有 `confirm_memory_proposal` 仅写入 `memory_records`。现扩展为：确认后额外检查 `payload.geo_mutations`，若存在则执行跨模块多路分发。分发失败不回滚 memory 写入。
