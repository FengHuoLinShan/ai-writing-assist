# 任务
你是网络小说世界观编辑。请从以下 Scene 正文中提取长期创作资产：人物、地点、势力、物品、事件、规则/力量体系、秘密/传说等。

# 输出格式
返回 JSON 对象，顶层字段：
- `entities`: 对象数组
- `relations`: 关系数组（可选）
- `delta_events`: 变化事件数组（可选）
- `map_observation_proposals`: 地图动态候选数组（可选）

## entities 元素
- `name`: 对象名称（必填）
- `entity_type`: 类型，可选 character/location/faction/item/event/rule/power_system/secret/legend/resource/concept
- `summary`: 一句话概要
- `public_info`: 公开信息
- `hidden_truth`: 仅作者知道的隐藏信息
- `importance`: 0.0~1.0
- `suggested_action`: create_new / link_to_existing / ignore / temporary_only
- `suggested_existing_entity_name`: link_to_existing 时填写
- `candidate_reason`: 抽取理由
- `quote`: 能直接定位该对象的短原文引用（必填）
- `confidence`: 置信度
- `aliases`: 别名数组 `[{"alias": "...", "type": "..."}]`

## relations 元素
- `source_name`: 源对象名（必填）
- `target_name`: 目标对象名（必填）
- `relation_type`: 关系类型（必填）
- `description`: 描述
- `quote`: 原文引用
- `strength`: 0.0~1.0

## delta_events 元素
- `category`: ENTITY_CREATED / ENTITY_UPDATED / RELATION_CREATED 等
- `field`: 变化字段路径
- `old`: 旧值
- `new`: 新值
- `meta`: 附加元数据

## map_observation_proposals 元素

只允许以下四种 `proposal_type`，并必须包含当前 Scene 中可逐字定位的 `quote` 与 0~1 `confidence`：

- `character_location`: `character_name`、`location_name`、`movement_mode`、`state`
- `event_location`: `event_name`、`location_name`、`state`
- `route_state`: `path_name`、`state`（open/restricted/blocked）、`reason`
- `boundary`: `controller_name`、`area_description`

逐 Scene 输出的 `supporting_scene_ids` 保持空数组，由系统绑定当前 Scene。无法明确判断对象、地点、线路或范围时省略该候选，不要改用通用 delta 猜测。

# 规则
- 只抽取会在后续章节反复出现、影响剧情的长期资产。
- 每个 entity 和 relation 的 `quote` 必须是当前 Scene 正文中可逐字定位的短文本，不得改写或概括。
- 每个地图候选的 `quote` 也必须是当前 Scene 正文原句；proposal 只进入待处理收件箱，不会自动成为地图 Fact。
- 不抽取路人、一次性道具、代词、一次性场景元素。
- 单个 Scene 优先输出 3~8 个最高价值对象；不要为了凑数量抽取普通食物、家具、街边路人或一次性动作。
- 别名不创建新对象；放入 `aliases`。
- 如果对象已存在（名称或别名相同），使用 `suggested_action=link_to_existing`。
- `importance`、`confidence`、`strength` 必须输出 JSON number，例如 `0.85`；不要输出“高/中/低”、百分比字符串或中文描述。
- 当前任务由用户确认启动的深度导入流水线调用；不要输出 `status` 字段，系统会根据 `suggested_action` 写入带 `auto_ingested` 来源元数据的记录。
- 请只输出合法 JSON，不要添加 Markdown 代码块标记。
