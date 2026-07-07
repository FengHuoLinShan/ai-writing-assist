# ADR — world services 子包分层计划

- **状态**: Proposed
- **日期**: 2026-07-07
- **关联追踪**: H3

## 背景

`world` 是事实层核心模块，当前同时承载 CoreEntity、Character、Event、EntityRelation、动态地图、世界书、抽取、去重和回滚能力。`backend/modules/world/services/` 仍是扁平目录，领域边界需要更清楚的内部组织。

## 拟议布局

未来可将 `services/` 拆成：

- `services/core/`：核心实体、人物、事件、关系、去重、抽取、版本和回滚。
- `services/map/`：地图配置、tile、marker、territory、observation/fact、dashboard、playback、动态队列。
- `services/worldbuilding/`：世界书页面、模板、投影、作者资料整理和上下文摘要。

## 边界

本文是计划记录，不表示 H3 已完成。当前代码仍是扁平 services 目录。

拆分时必须保持：

- world facade 和 `/api/world/*` wire shape 稳定。
- `docs/modules/02_world.md` 与 `docs/modules/15_map.md` 的权威入口不漂移。
- novel_id 隔离、status/candidate 语义、危险操作确认和 Pydantic 校验。
- 跨模块调用继续走 facade/contracts/API/DI port。

## 后续验证

- 先拆内部 import，再调整测试路径；跨模块测试仍通过 public interface。
- 对 map、character、relation、rollback、worldbuilding 各保留最小行为测试。
- 完成代码拆分后再更新 H3 状态。
