# 文档维护 — 案例

## 案例 1：新增 API 端点（必须更新）

**本轮变化**：在 `modules/writing` 新增了 `POST /api/writing/draft/{draft_id}/promote` 端点，用于将 draft 晋升为 canonical。

**收集**：
- 新增 API 端点
- 行为变更：draft 现在可以从前端直接 promote

**判断**：
- ✅ API 契约变化
- ✅ 用户可感知的业务行为变化

**输出**：

```
【是否更新】YES

【修改原因】
writing 模块新增 promote 端点，前端可直接触发 draft → canonical 晋升流程

【修改内容摘要】
在 docs/modules/11_writing.md 的 API 参考章节新增 promote 端点说明

【建议修改位置】
docs/modules/11_writing.md，API 参考章节

【修改后的正文片段】
| `POST /api/writing/draft/{draft_id}/promote` | 将 draft 晋升为 canonical | writing |

【可能影响的其他文档】
docs/核心业务场景与预期行为.md（如果 promote 流程有状态机变化）
```

---

## 案例 2：Bug 修复（不应更新）

**本轮变化**：修复了 `context compiler` 中 entity count 超限时未截断的 Bug。原因是 `max_items` 参数在循环中被重复比较，导致判断失效。

**收集**：
- Bug 修复
- Debug 过程：发现循环中 max_items 比较逻辑错误

**判断**：
- ❌ 不是 Spec 变化
- ❌ 不是 API 变化
- ❌ 纯实现细节（循环比较逻辑）
- 如果这是一个架构误解导致的 → 但这里只是参数比较 Bug，不涉及架构理解

**输出**：

```
【本轮判断】无需更新文档
【理由】循环比较逻辑 Bug，不影响 API 契约、数据模型或架构边界。修复后的行为与文档中描述的 context compiler 行为完全一致。
```

---

## 案例 3：架构重构（必须更新 + ADR）

**本轮变化**：将 `character` 模块合并到 `world` 模块。删除了 `modules/character/` 目录，character 相关模型和 API 现在都在 `modules/world/` 下。

**收集**：
- 删除功能：`modules/character/` 模块
- 架构调整：character → world 合并
- 数据模型变化：character 表合并到 world 模块

**判断**：
- ✅ 架构边界变化
- ✅ API 契约变化（路由前缀变更）
- ✅ 数据模型变化

**输出**：

```
【是否更新】YES（3 个文档 + 1 个 ADR）

【修改原因】
character 模块合并到 world 模块，影响模块列表、路由注册、测试引用

【修改内容摘要】
1. CLAUDE.md：8 个活跃模块中移除 character 的 "已移除" 说明（已成历史）
2. docs/00_整体设计.md：更新模块列表
3. docs/modules/02_world.md：新增 character 相关 API 和模型说明

【建议修改位置】
1. CLAUDE.md 第 22 行 — 更新模块列表
2. docs/00_整体设计.md 模块职责章节
3. docs/modules/02_world.md 全文档

【修改后的正文片段】
（略）

【可能影响的其他文档】
- docs/archive/ 中可能需要归档旧的 character 模块文档
- 新增 ADR：docs/adr/0003-character-merge-to-world.md
```

---

## 案例 4：新增经验教训（值得写入）

**本轮变化**：一个 SQLAlchemy `importance or 0.5` 的写法导致 `importance=0.0` 被错误地替换为 0.5。在 code review checklist 中新增了这个陷阱。

**收集**：
- 测试发现的问题（P0 Bug）
- 最终方案：`importance if importance is not None else 0.5`

**判断**：
- ✅ 高代价经验教训（0.0 被覆盖，数据正确性受影响）
- 已在 testing-guide.md 的 "Code Review Checklist" 中更新

**输出**：

```
【是否更新】YES

【修改原因】
Python falsy 值陷阱（`or` 运算符吞噬 0.0），是容易被忽视的数据正确性 Bug

【修改内容摘要】
已在 testing-guide.md Code Review Checklist 中新增此项。无需重复写入。

【建议修改位置】
testing-guide.md，Python 陷阱章节（已完成）

【修改后的正文片段】
已存在，确认内容准确即可。

【可能影响的其他文档】
无
```

---

## 案例 5：内部重构（不应更新）

**本轮变化**：将 `services.py` 中的 50 行重复查询逻辑提取为私有方法 `_get_or_raise()`。

**收集**：
- 内部重构
- 无行为变更

**判断**：
- ❌ 纯实现细节
- ❌ 不影响 API、数据模型、架构边界
- ❌ 不影响未来开发决策

**输出**：

```
【本轮判断】无需更新文档
【理由】提取私有方法是纯实现细节，不影响任何对外接口或设计约束。
```
