# Module: review / 结构复查模块

## 定位

review 模块负责结构化创作结果的复查。当前不以正文审稿为主。

## 复查对象

world_structure / geo_structure / plot_structure / chapter_cards / memory_update / entity_candidates

## 原则

- Schema 校验先行（代码检查）
- 模型负责逻辑审查（冲突 / 剧透 / 知识边界）
- Review 不改正史，只输出问题和建议
- 7 个检查维度使用策略模式（CheckStrategy 协议），注册在 services/ 目录下

## 检查策略

| 策略 | 文件 | 职责 |
|------|------|------|
| SchemaCheck | schema_check.py | 必填字段 / UUID 格式 / 枚举值 |
| EntityReferenceCheck | entity_reference_check.py | 引用实体/人物的存在性 |
| EarlyRevealCheck | early_reveal_check.py | hidden_truth 泄露 / 揭示计划间隔 |
| CharacterKnowledgeCheck | character_knowledge_check.py | 角色知识边界 / 进度重叠 |
| TimelineCheck | timeline_check.py | 章节重复 / 伏笔顺序 / facade 委派 |
| GeoCheck | geo_check.py | 地点引用存在性 |
| DuplicateCheck | duplicate_check.py | 章节卡 / 实体名称 / 候选内部重复 |

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
