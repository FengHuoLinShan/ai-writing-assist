# Module: context / 上下文编译模块

## 定位

context 模块是系统核心智能模块。RAG 负责找资料，Context Compiler 决定哪些资料交给模型。

## 聚合来源

project / world / geo / character / memory / timeline / outline / rag

## 核心函数

```python
async def compile_structure_context(db, novel_id, task, scope, chapter_index=None, ...) -> StructureContextBundle
def render_context_markdown(context: StructureContextBundle) -> str
```

## Context Budget

| 类别 | 上限 |
|------|------|
| 核心对象 | 8 |
| 普通对象 | 8 |
| 人物 | 6 |
| 记忆 | 10 |
| 伏笔 | 5 |
| 时间线 | 8 |
| 地理关系 | 10 |
| 关系边 | 12 |
| RAG 片段 | 8 |

## Markdown 层次

```markdown
# 一、当前任务
# 二、必须遵守的硬约束
# 三、当前剧情阶段
# 四、相关人物
# 五、相关世界对象
# 六、相关地理与历史
# 七、相关剧情线
# 八、相关 Memory
# 九、相关伏笔与信息揭示
# 十、禁止事项
# 十一、可用创作素材
# 十二、风险提示
```

## Reveal 处理

作者视角可给 hidden_truth，但必须标注"作者视角信息，不得直接让角色知道"。角色视角必须根据 character_knowledge 过滤。

## API

```
POST /api/context/compile    # 编译上下文
POST /api/context/render     # 渲染 Markdown
```

## 不做

- 无限上下文塞入
- 全量世界设定注入
- 自动剧情推理
