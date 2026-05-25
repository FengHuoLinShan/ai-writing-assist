# CLAUDE.md — modules/world

## 模块职责

世界对象（WorldEntity）、关系（Relationship）、别名（EntityAlias）、候选对象（EntityCandidate）的 CRUD 与去重。

## 关键提醒

### WorldEntity 没有 aliases 字段
别名存储在独立表 `entity_aliases` 中。合并候选时使用 `EntityAliasRepository.create()`，不要直接设置 `entity.aliases`。

### EntityCandidate 有限字段
`EntityCandidate` 没有 `hidden_truth` 或 `public_info` 字段。合并到正史对象时应使用 `source_text` 作为补充。

### Falsy-zero 陷阱
`importance`、`importance_score`、`confidence` 等 float 字段为 0.0 时是合法值。检查时用 `is not None` 而非 `if value:`。

### 模糊匹配
`_fuzzy_name_matches` 在 `_normalize_name` 中移除了空格，英文多词名称相似度会膨胀。仅用于中文名称匹配时效果较好。

### 抽取管线
- `EntityExtractionService` 读取 WritingDraft 通过 `writing/facade.get_latest_draft_for_chapter`
- 批次中所有 entity 优先使用 LLM 报告的 `source_chapter`，fallback 到 `batch[0]["chapter_index"]`
- `except ValueError` 只捕获数据错误，DB 异常应向上传播避免 session 中毒

## 测试要求

- conftest 必须 import `modules.project.models`（NovelMixin FK）
- dedup 测试：精确匹配 + 模糊匹配 + 合并
- 抽取测试：mock LLMClient，验证候选创建和去重逻辑
