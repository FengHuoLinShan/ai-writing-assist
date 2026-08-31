# AGENTS.md — modules/world

- 别名只存于 `core_entities.content_json.aliases`；不得创建重复别名对象或恢复独立 alias 表。
- 手动 AI 补抽必须绑定 fresh Context confirmation；新实体只以 candidate 进入审核，不自动成为正史。
- 公开对象、关系、别名、Canon 和图片请求同时校验 account owner 与 `novel_id`；后台任务只消费
  冻结的 owner-aligned 授权并继续按 `novel_id` 过滤，不得借 worker/system 身份绕过边界。
- `importance`、`importance_score`、`confidence` 等字段的 `0.0` 合法，判断缺失必须使用
  `is not None`。`_fuzzy_name_matches` 仅是候选召回，不是强一致身份判定。
- 实体抽取只保留长期创作资产；路人、代词、普通道具和一次性场景元素不得污染资料库。
- 数据错误可以转换为业务错误，但 DB flush/commit 异常必须向上传播，不得捕获后忽略。
- 旧动态地图 `map_*` 与 `/api/world/maps*` 已删除；AI 地图册以本模块 README、
  `docs/modules/15_map.md` 与 ADR-0012 为准。图片候选不会自动成为正式世界设定。
- 修改去重/抽取时覆盖精确/模糊匹配、跨 `novel_id`、candidate 合并和 LLM mock；修改 Canon、
  世界书或图片时再覆盖 owner、CAS/历史、确认、私有存储与回滚边界。
