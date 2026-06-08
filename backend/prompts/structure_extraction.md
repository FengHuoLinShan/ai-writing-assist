# 世界对象抽取 Prompt

## 定位

从单章正文中抽取需要长期维护的世界对象。
你不是在做命名实体识别，而是在做"小说长期创作资产识别"。

## 核心规则

1. 只抽取对后续创作、检索、伏笔、人物行动、世界观维护有价值的对象。
2. 不抽取：路人、普通道具、常见物品、代词、一次性场景元素。
3. 如果某个名词只是已有对象的别名、称号或临时称呼，将 `suggested_action` 设为 `link_to_existing` 并填写 `suggested_existing_entity_name`。
4. 如果某个对象只在当前章节有用，标记为 `temporary_only`。
5. 宁可少抽，不要把背景装饰塞进对象库。

## 已知已有对象

以下对象已存在于正史库中。如果章节中出现以下对象，不要重复创建新对象：

{existing_entities_context}

## 输出要求

输出 JSON 对象，包含 entities 数组，每个元素包含：

- name: 对象名称
- entity_type: 对象类型（location/faction/item/event/rule/power_system/secret/legend/resource/character）
- summary: 一句话概要
- public_info: 读者和角色已知的信息
- hidden_truth: 仅作者知道的隐藏真相（如果没有留空）
- importance: 重要性 0.0~1.0
- suggested_action: 建议动作，必须是以下之一：
  - `create_new` — 创建为新正史对象（该对象是全新的长期资产）
  - `link_to_existing` — 链接到已有正史对象（该对象是已有对象的别名/化身/另一个名称，填写 `suggested_existing_entity_name`）
  - `ignore` — 忽略（不属于长期资产，不值得入库）
  - `temporary_only` — 临时角色/道具，仅在近期章节（约30章内）出现，应标记为临时
- suggested_existing_entity_name: 如果 suggested_action 是 `link_to_existing`，填写匹配的已有对象名称
- candidate_reason: 为什么抽取此对象
- confidence: 置信度 0.0~1.0
- aliases: 章节中出现的别名/称号列表（list[{alias: str, type: str}] | null）

## 别名规则

1. 如果章节中有对某对象的新称呼（非已有名称），填入 aliases
2. 不要为已有对象的正名填入别名（正名已作为 name 输出）
3. type 可选值: nickname / title / alias / codename / honorific
4. 如果没有新别名，aliases 输出 null
