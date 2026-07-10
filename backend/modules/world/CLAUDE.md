# CLAUDE.md — modules/world

## 模块级禁止事项

- 别名统一存储在 `core_entities.content_json.aliases` JSONB 中（不再使用独立 `entity_aliases` 表）
- 不把别名当作新世界对象创建；别名直接标记在已有对象的 `aliases` 中
- 手动 AI 补抽必须先校验 `context_confirmation_id`，抽取实体以 `status="candidate"` 入库，等待用户确认、合并或忽略
- 不跨 `novel_id` 合并关系、别名或正史对象
- 不用 `if value:` 判断 `importance` / `importance_score` / `confidence` 等浮点字段；`0.0` 是合法值，必须使用 `is not None`
- 不把 `_fuzzy_name_matches` 当作强一致性判断；它对英文多词名称会因空格归一化放大相似度
- 不抽取路人、普通道具、代词、一次性场景元素；实体抽取只服务长期创作资产
- 不捕获并吞掉数据库异常；数据错误可转为业务错误，DB flush / commit 异常必须向上传播
- 不在缺少精确匹配、模糊匹配、跨 `novel_id`、候选合并、LLM 抽取 mock 测试时合并去重/抽取逻辑改动

## 动态地图（map_*）禁止事项

- `map_markers.start_scene_id` / `end_scene_id` 不建数据库 FK 到 `outline.scenes`（PRD §7.2 跨模块不强耦合）；Scene 信息通过 outline facade/DI port 校验
- 地点绑定只能绑定 `core_entities.entity_type = "location"` 的实体，由 `MapLocationBindingService` 校验
- 同一地点在同一地图最多一个 `is_center=true` 中心点；DB 层 PG 部分唯一索引 + 业务层 `clear_center` 双重保证（SQLite 测试仅业务层）
- 六边形第三坐标 `s = -q - r` 不在后端存储（ORM 无 `hex_s` 列），由前端计算；后端只存 `(q, r)`
- 地图删除是硬 DELETE（demo 阶段允许），前端必须二次确认；不使用 status 软删除
