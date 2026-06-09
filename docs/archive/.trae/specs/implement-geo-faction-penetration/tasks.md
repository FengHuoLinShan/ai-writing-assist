# Tasks

- [x] Task 1: 扩展事实层 Facade — geo/character/outline/world 跨模块接口
  - [x] 1.1: `world/repositories.py` — 新增 `find_entity_by_name`（精确匹配 `world_entities.name` + 别名匹配 `entity_aliases.alias`）和 `upsert_relationship`（幂等覆写 `relationships` 表）
  - [x] 1.2: `world/facade.py` — 新增 `find_entity_id_by_name(db, novel_id, name, entity_type)` 和 `upsert_relationship(db, novel_id, source_id, target_id, source_type, target_type, relation_type, description)` 对外接口
  - [x] 1.3: `character/repositories.py` — 新增 `find_character_by_name`（精确匹配 `characters.name` + 别名匹配 `characters.aliases` JSON 数组）和 `update_character_meta_location`（原子覆写 `meta.current_location_id` + `meta.last_updated_chapter` + `current_state`）
  - [x] 1.4: `character/facade.py` — 新增 `find_character_id_by_name(db, novel_id, name)` 和 `update_character_location(db, novel_id, character_id, location_id, text_state, chapter_index)` 对外接口
  - [x] 1.5: `outline/repositories.py` — 新增 `merge_involved_ids`（读取 `chapter_cards` 的 `involved_character_ids` / `involved_entity_ids`，追加新 ID，`set()` 去重后写回）
  - [x] 1.6: `outline/facade.py` — 新增 `merge_chapter_involved_ids(db, novel_id, chapter_index, character_ids, entity_ids)` 对外接口
  - [x] 1.7: 编写 Task 1 单元测试（名称查找精确/别名/未命中、关系 upsert 幂等、角色位置擦写、章节 involved 去重合并）

- [x] Task 2: AI 结构化提取管道与降级接口
  - [x] 2.1: `memory/schemas.py` — 新增 `CharacterLocationShift`、`FactionControlShift`、`ChapterStateExtraction` Pydantic v2 模型（含 `new_relation` field_validator 降级）
  - [x] 2.2: `writing/api.py` — 新增 `POST /api/writing/save-and-analyze` 端点：先保存草稿，再调用 LLM 结构化提取，try/except 降级保护，返回 `{draft_id, proposal_created}`
  - [x] 2.3: `writing/services.py` — 新增 `save_and_analyze` 业务方法：保存草稿 → LLM 提取 → 创建 memory proposal
  - [x] 2.4: 编写 Task 2 单元测试（正常提取流程、LLM 超时降级、Pydantic 校验 new_relation 非法值降级）

- [x] Task 3: Memory 提案确认多路分发
  - [x] 3.1: `memory/services.py` — 扩展 `confirm_memory_proposal`：确认后检查 `payload.geo_mutations`，执行 character_shifts 分发（find_character → find_location → update_location）、faction_shifts 分发（find_entity → upsert_relationship）、chapter involved 合并
  - [x] 3.2: 分发失败降级：单条分发失败记录 warning 日志跳过，不影响其他分发和 canonical memory
  - [x] 3.3: 编写 Task 3 单元测试（完整分发流程、角色名未找到跳过、势力关系幂等覆写、章节 involved 合并）

- [x] Task 4: 前端三视图联动
  - [x] 4.1: `writingView.js` — 编辑区上方注入"保存并让 AI 分析地缘资产"按钮，调用 `save-and-analyze` API，成功后更新 `state.pending_proposals_count` + toast
  - [x] 4.2: `memoryView.js` — 提案卡片渲染：检测 `payload.character_shifts` / `payload.faction_shifts`，渲染为 `.geo-proposal-card` 样式，中文标签展示
  - [x] 4.3: `geoView.js` — 右侧详情面板新增势力列表和活跃人物列表查询渲染，人物名可点击跳转 `router.go('character')`
  - [x] 4.4: `api.js` — 新增 `writing.saveAndAnalyze`、`geo.getLocationFactions`、`geo.getLocationCharacters` API 方法

- [x] Task 5: Geo API 新增势力/人物查询端点
  - [x] 5.1: `geo/api.py` — 新增 `GET /api/geo/location/{id}/factions` 和 `GET /api/geo/location/{id}/characters` 端点
  - [x] 5.2: `geo/services.py` — 新增 `get_location_factions`（查询 `relationships` 表 `target_id=location_id AND relation_type IN ('controls','stationed_at','hidden_presence')`）和 `get_location_characters`（查询 `characters.meta->>'current_location_id'=location_id`）
  - [x] 5.3: 编写 Task 5 单元测试

# Task Dependencies
- Task 2 depends on Task 1（LLM 提取管道需要 `ChapterStateExtraction` schema，但 API 端点不依赖 facade 接口）
- Task 3 depends on Task 1（多路分发调用 geo/character/outline facade）
- Task 4 depends on Task 2 + Task 5（前端需要 API 端点就绪）
- Task 5 depends on Task 1（geo 查询需要 world facade 的 relationship 查询能力）
