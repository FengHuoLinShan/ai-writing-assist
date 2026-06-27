# ADR-0001 — state_assembler 归属与跨 seam 数据形状

- **状态**: Accepted
- **日期**: 2026-06-01
- **背景**: architecture review (#1) — `world/facade.py` 持有 100 行业务逻辑, 跨 world↔memory seam

## 背景与问题

`world/facade.py:519-618` 的 `get_full_state(novel_id)` 把 world 4 块正史数据 (entities / relations / character_locations / character_knowledge) 装成 dict 给 memory 做 snapshot / replay / diff。它是 facade 文件中唯一一段非平凡的代码, 也是跨模块的真正 seam。

在抽取之前, 三个设计轴未定:

1. **seam 归属**: 谁拥有"世界状态形状" — producer (world) 还是 consumer (memory)?
2. **数据形状**: TypedDict (无运行时检查) 还是 Pydantic (强类型)?
3. **错误策略**: 知识表读失败时, 是吞掉 (现状 `try/except: pass`) 还是传播?

## 决策

### 1. state_assembler 归 world/ (producer), 不归 memory/ (consumer)

`memory.services` 是结构层 (事件溯源 / 快照 / 重放), 它的输入是"某一时刻的世界正史"。这个正史**由 world 拥有**, memory 只是消费。

**理由**:
- 领域分层: docs/00_整体设计.md §4 把 world 放在"事实层", memory 放在"结构层"。事实层是源, 结构层是衍生。
- 跨模块反向依赖: 若 memory 拥有状态形状, 则 world 必须知道"memory 怎么读我的状态", 这是反向依赖。架构 review 的"facade-gate"原则禁止这种反向。
- 替代验证: 若 memory 拥有, world 写新字段时需要先通知 memory, 跨模块协议变更变慢。producer-owns 模式下, world 内部改字段, memory 通过 seam 自动感知。

### 2. 跨 seam 用 TypedDict, 不用 Pydantic

`memory/services.py:289-325` 的 `_apply_events` 把状态当 dict 改: `state["entities"][eid] = after`, `eid in state["entities"]` 等。

Pydantic model 在 seam 上看似类型更安全, 但 memory 拿到后立刻 `.model_dump()` 回到 dict, Pydantic 装的 typed 信息半路丢掉, round-trip 是纯开销。

**TypedDict 是 seam 上唯一正确的形状**: 类型提示给读者, 无运行时开销, 与 memory 的 dict 消费习惯一致。

### 3. 知识表 DB 异常必须传播, 不允许吞

`facade.py:595-611` 的 `try/except: pass` 违反 `world/CLAUDE.md §8`: "不捕获并吞掉数据库异常; DB flush / commit 异常必须向上传播"。

新 seam 不接收 `fail_on_knowledge_error` 参数, 默认行为即传播。

## 影响

- `world/facade.py` 的 100 行 `get_full_state` 缩为 1 行 shim
- `memory/services.py` 的 3 处调用签名不变 (都是 `dict`), 不需要 `.model_dump()`
- `world/state_assembler.py` 是新 deep module, 1 个公共函数 + 1 个真 seam (`StateSource`, 2 个 adapter)
- 未来加第 5 段状态 (例如 locations 升级为正史) 需要协调 3 处改动: `assemble()` / memory `_apply_events` / memory `_build_panorama`, 单一 seam 单一变更点

## 备选方案 (拒绝)

### B1. memory/ 拥有 state_assembler

让 memory 直接跨多个 world 仓库拉数据, 自己组装。**拒绝理由**: 反向依赖, world 写字段时需要 memory 改协议。

### B1.5. world/queries.py 混合只读查

把 `state_assembler` 和 `find_entity_by_name` 之类的简单只读查放一起。**拒绝理由**: 状态组装的复杂度不在一个量级, 混在一起会模糊 seam 责任, 单元测试需要 mock 4 个 repo 而不是测 1 个 assembler。

### B2. Pydantic model

`WorldStateSnapshot(BaseModel)`, memory 拿到后 `.model_dump()`。**拒绝理由**: 装不上的 typed 红利。memory 是按 dict 改的, Pydantic 在 seam 上只是装饰, `.model_dump()` 是纯开销。

### B3. AssembleRequest 带 sections/filters/hooks

参数化装配, 支持"只取 entities"、"按 entity_type 过滤"、"行级 hook 裁剪"。**拒绝理由**: 当前唯一 consumer (memory) 不要这些。预设计是 YAGNI; 真需求出现时再加 sibling 函数。
