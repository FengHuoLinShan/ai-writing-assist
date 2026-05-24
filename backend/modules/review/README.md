# Module: review / 结构复查模块

## 定位

review 模块负责结构化创作结果的复查。当前不以正文审稿为主。

## 原则

- **Schema 校验先行**：字段、枚举、引用对象等由代码检查
- **模型负责逻辑审查**：冲突、剧透、知识边界、结构质量
- **Review 不改正史**：只输出问题和修改建议，不直接修改正史数据

## 复查对象

| target_type | 说明 |
|---|---|
| `world_structure` | 世界对象与关系结构 |
| `geo_structure` | 地理关系与宏观历史结构 |
| `plot_structure` | 剧情线、篇章纲、章节卡结构 |
| `chapter_cards` | 单独的章节卡结构 |
| `memory_update` | 记忆更新提案 |
| `entity_candidates` | 候选对象池 |

## 数据表

- `review_reports` — 复查报告

## 检查维度

| 维度 | 方法 | 说明 |
|---|---|---|
| Schema 校验 | `_check_schema()` | 检查必填字段、枚举值合法性、UUID 格式 |
| 实体引用检查 | `_check_entity_references()` | 检查引用的对象/人物/剧情线是否存在 |
| 提前揭示检查 | `_check_early_reveal()` | 检查 hidden_truth 是否被提前揭示 |
| 人物知识边界检查 | `_check_character_knowledge()` | 检查角色是否知道不该知道的信息 |
| 时间线冲突检查 | `_check_timeline()` | 检查顺序矛盾、事件重复、角色位置冲突 |
| 地理冲突检查 | `_check_geo()` | 检查地点引用一致性和通行关系合理性 |
| 重复检查 | `_check_duplicates()` | 检查对象/剧情线/章节是否与正史重复 |

## 决策逻辑

| 条件 | 决策 |
|---|---|
| 存在 high 严重度警告 | `reject` — 拒绝 |
| >3 个 medium 严重度警告 | `major_revision` — 大修 |
| 存在 medium 严重度警告 | `minor_revision` — 小修 |
| 无严重警告 | `pass` — 通过 |

## Facade

```python
async def review_structure_candidate(
    db, novel_id, target_type, candidate_payload
) -> ReviewReportContext:
    """提交结构候选进行复查，返回复查报告"""

async def get_review_report(db, review_id) -> ReviewReportContext:
    """获取已存在的复查报告"""
```

## API

```http
POST /api/review
Content-Type: application/json

{
  "novel_id": "...",
  "target_type": "plot_structure",
  "candidate_payload": { ... }
}

Response:
{
  "id": "...",
  "decision": "minor_revision",
  "problems": [...],
  "conflict_warnings": [...],
  "early_reveal_warnings": [...],
  "character_knowledge_warnings": [...],
  "duplicate_entity_warnings": [...],
  "geo_warnings": [...],
  "revision_instructions": [...]
}
```

```http
GET /api/review/{review_id}
```

## 模块边界

**允许导入：**
- `core.*`
- `shared.*`
- `modules/world/facade.py` — 验证实体引用
- `modules/character/facade.py` — 验证人物知识和知识边界
- `modules/geo/facade.py` — 验证地点引用
- `modules/timeline/facade.py` — 验证时间线冲突
- `modules/outline/facade.py` — 验证章节卡重复

**禁止：**
- 直接导入其他模块的 `models.py`、`repositories.py`、`services.py`
- 直接操作其他模块的表

## 测试方式

```bash
cd backend
pytest modules/review/tests/ -v
```
