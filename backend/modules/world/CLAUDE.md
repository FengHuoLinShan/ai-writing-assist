# CLAUDE.md — modules/world

## 模块级禁止事项

- 不给 `WorldEntity` 添加或假设存在 `aliases` 字段；别名只存储在 `entity_aliases`
- 不把别名当作新世界对象创建；候选应标记 `alias_of_existing` 并等待用户确认
- 不自动合并正史对象；候选合并、废弃、删除必须有二次确认
- 不跨 `novel_id` 合并候选、关系、别名或正史对象
- 不假设 `EntityCandidate` 有 `hidden_truth` / `public_info` 字段；合并补充信息时使用 `source_text`
- 不用 `if value:` 判断 `importance` / `importance_score` / `confidence` 等浮点字段；`0.0` 是合法值，必须使用 `is not None`
- 不把 `_fuzzy_name_matches` 当作强一致性判断；它对英文多词名称会因空格归一化放大相似度
- 不抽取路人、普通道具、代词、一次性场景元素；实体抽取只服务长期创作资产
- 不捕获并吞掉数据库异常；数据错误可转为业务错误，DB flush / commit 异常必须向上传播
- 不在缺少精确匹配、模糊匹配、跨 `novel_id`、候选合并、LLM 抽取 mock 测试时合并去重/抽取逻辑改动
