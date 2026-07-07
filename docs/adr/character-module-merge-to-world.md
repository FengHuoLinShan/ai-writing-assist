# ADR — Character 能力并入 World 模块

- **状态**: Accepted
- **日期**: 2026-07-08

## 背景

早期设计中，character 曾作为独立模块维护人物档案、人物知识边界和相关上下文接口。v3 因果时空网重构后，人物已经成为 world 正史事实的一部分，与 CoreEntity、Event、EntityRelation 等对象统一管理。

旧 character 模块不再是活跃独立模块；继续把它作为跨模块集成对象会误导新 Agent 恢复旧入口、旧 API 或旧测试。

## 决策

Character 能力并入 world。当前权威入口是：

- `docs/modules/02_world.md`
- `backend/modules/world/facade.py`
- `/api/world/characters`

跨模块调用人物能力时，必须走 world facade、world contracts 或已注册的 DI port，不应恢复 `modules.character` 作为新的业务依赖入口。

本 ADR 只确认模块归属和文档入口，不恢复旧深度导入流程、不恢复旧 character 模块，也不要求迁回旧测试。

## 影响

- 文档中提到人物能力时，应表述为 world 的 character capability，而不是独立 Character 模块。
- RAG、context、imports、writing 等模块如果需要人物档案、知识边界或人物位置，应通过 world 的稳定入口获取。
- 旧 `docs/modules/character/README.md` 文档入口已移除，历史说明归档到 `docs/archive/character-module-removed.md`。

## 备选方案

### 1. 恢复独立 character 模块

拒绝。人物事实已经与 world 的实体、事件、关系和地图能力共享正史边界；恢复独立模块会重新引入跨模块所有权和 API 入口漂移。

### 2. 只在文档中弱化 character

拒绝。弱化措辞不足以阻止后续 Agent 把 Character 当作活跃模块接入。需要 ADR 明确当前权威入口和禁止恢复旧模块的边界。
