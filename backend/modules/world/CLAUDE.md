# CLAUDE.md — modules/world

## 模块级禁止事项

- 别名统一存储在 `core_entities.aliases` JSONB 中（不再使用独立 `entity_aliases` 表）
- 不把别名当作新世界对象创建；别名直接标记在已有对象的 `aliases` 中
- AI 抽取的实体直接以 `status="canonical"` 自动入库，`content_json._meta` 记录自动入库元数据
- 不跨 `novel_id` 合并关系、别名或正史对象
- 不用 `if value:` 判断 `importance` / `importance_score` / `confidence` 等浮点字段；`0.0` 是合法值，必须使用 `is not None`
- 不把 `_fuzzy_name_matches` 当作强一致性判断；它对英文多词名称会因空格归一化放大相似度
- 不抽取路人、普通道具、代词、一次性场景元素；实体抽取只服务长期创作资产
- 不捕获并吞掉数据库异常；数据错误可转为业务错误，DB flush / commit 异常必须向上传播
- 不在缺少精确匹配、模糊匹配、跨 `novel_id`、候选合并、LLM 抽取 mock 测试时合并去重/抽取逻辑改动
