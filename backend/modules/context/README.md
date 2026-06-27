# Module: context / 上下文编译模块

## 定位

context 模块是系统最核心的智能模块之一。RAG 负责找资料，Context Compiler 决定哪些资料真正交给模型。

## 职责

- 按需聚合 project / world / memory / outline / rag 数据
- 按 scope 选择性加载，不预加载所有数据
- Context Budget 控制，防止上下文过载
- Reveal 过滤（author_safe 隐藏 hidden_truth）
- Markdown 渲染，产出适合 LLM Prompt 的结构化上下文

## 不负责

- 不直接创建或操作任何数据库表（本模块无数据表）
- 不负责 RAG 检索（委托 rag 模块）
- 不负责结构复查（当前无 review 模块，由 outline 和 world 各自管理一致性）
- 不负责 LLM 调用（委托 infrastructure/llm）
- 不负责剧情推理

## 核心函数

```python
# facade.py
async def compile_structure_context(db, novel_id, task, scope, ...) -> StructureContextBundle
def render_context_markdown(context: StructureContextBundle) -> str
```

## 支持 Scope

| Scope | 加载的数据 |
|-------|-----------|
| project | 项目元信息 |
| world | 项目 + 世界对象 |
| world_character | 项目 + 世界对象 + 人物 |
| arc | 篇章相关全部（含 RAG） |
| chapter | 章节相关全部（含 RAG） |
| full | 全部数据（有限预算） |

## Context Budget

| 分类 | 预算 |
|------|------|
| core_entities | 8 |
| normal_entities | 8 |
| characters | 6 |
| memory | 10 |
| foreshadowing | 5 |
| timeline | 8 |
| geo_relations | 10 |
| relationship_edges | 12 |
| rag_chunks | 8 |

## Markdown 输出结构

```markdown
# 结构化创作上下文
## 一、当前任务
## 二、必须遵守的硬约束
## 三、当前剧情阶段
## 四、相关人物
## 五、相关世界对象
## 六、相关地理与历史
## 七、相关剧情线
## 八、相关 Memory
## 九、相关伏笔与信息揭示
## 十、禁止事项
## 十一、可用创作素材
## 十二、风险提示
```

## Reveal 处理

- `author_safe`（默认）：隐藏 hidden_truth，标注"作者视角信息"
- `author_full`：显示所有信息，标注作者视角警告
- `reader`：只显示读者已知信息

## 对外契约

### StructureContextBundle

```python
@dataclass
class StructureContextBundle:
    novel_id: str
    task: str
    scope: str
    chapter_index: int | None
    arc_id: str | None
    project: dict | None
    world_entities: list
    characters: list
    geo_locations: list
    memory_records: list
    timeline_events: list
    plot_threads: list
    outline_arc: dict | None
    chapter_card: dict | None
    rag_chunks: list
    reveal_mode: str
    budget_used: dict
    warnings: list
```

## 测试方式

```bash
cd backend
pytest modules/context/tests/ -v
```

## 依赖的模块

- modules/project/facade — get_project_context
- modules/world/facade — get_world_context, expand_related_entities, get_characters_context, get_character_knowledge_context, get_events_context
- modules/memory/facade — get_recent_story_memory
- modules/outline/api — 剧情线/篇章纲/Scene 数据（outline 无 facade，API 层直接提供）
- modules/rag/facade — retrieve
