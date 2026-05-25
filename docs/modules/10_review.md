# Module: review / 结构复查模块

## 定位

review 模块负责结构化创作结果的复查。当前不以正文审稿为主。

## 复查对象

world_structure / geo_structure / plot_structure / chapter_cards / memory_update / entity_candidates

## 原则

- Schema 校验先行（代码检查）
- 模型负责逻辑审查（冲突 / 剧透 / 知识边界）
- Review 不改正史，只输出问题和建议

## 数据表

- review_reports — target_type / decision / score / problems / conflict_warnings / early_reveal_warnings / character_knowledge_warnings / duplicate_entity_warnings / geo_warnings / revision_instructions

## API

```
POST /api/review               # 运行复查
GET  /api/review               # 报告列表
GET  /api/review/{id}          # 报告详情
```

## 不做

- 自动重写结构
- 多轮 Agent 辩论
- 正文文学审美评分
