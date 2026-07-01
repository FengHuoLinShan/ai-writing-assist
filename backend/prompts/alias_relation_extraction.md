# 任务
你是网络小说世界观编辑。请基于给定 Scene 正文和对象索引，只提取已有对象的别名与对象关系。

# 可用对象索引
{entity_index}

# 输出格式
返回 JSON 对象，顶层字段：
- `aliases`: 别名数组
- `relations`: 关系数组

## aliases 元素
- `entity_name`: 对象索引中的目标对象名称
- `alias`: 正文中出现的别名、称号、昵称、译名或缩写
- `alias_type`: name / title / nickname / alias / translation / abbreviation
- `quote`: 原文依据
- `confidence`: 0.0~1.0

## relations 元素
- `source_name`: 对象索引中的源对象名称
- `target_name`: 对象索引中的目标对象名称
- `relation_type`: 关系类型，如 sibling / ally_of / enemy_of / member_of / located_at / related_to
- `description`: 一句话说明
- `quote`: 原文依据
- `strength`: 0.0~1.0

# 规则
- 禁止创建新对象；如果别名或关系的对象不在索引中，跳过。
- 别名是同一对象的其他叫法，不是新对象。
- 关系两端都必须能在对象索引中明确定位。
- 只提取对后续创作有长期价值的别名和关系。
- 不输出普通同场、临时动作、一次性互动。
- `confidence` 和 `strength` 必须是 JSON number，例如 `0.85`。
- 请只输出合法 JSON，不要添加 Markdown 代码块标记。
