# ADR — world services 子包分层计划

- **状态**: Implemented
- **日期**: 2026-07-07
- **关联追踪**: H3

> 2026-07-29 复核：`services/core/`、`services/map/` 与
> `services/worldbuilding/` 已落地。根 `services/` 仍保留少量聚合入口和兼容 import seam，
> 不代表存在第二套领域实现。

## 背景

`world` 是事实层核心模块，当前同时承载 CoreEntity、Character、Event、EntityRelation、动态地图、世界书、抽取、去重和回滚能力。`backend/modules/world/services/` 仍是扁平目录，领域边界需要更清楚的内部组织。

## 已采用布局

`services/` 按以下领域分区：

- `services/core/`：核心实体、人物、事件、关系、去重、抽取、版本和回滚。
- `services/map/`：地图配置、tile、marker、territory、observation/fact、dashboard、playback、动态队列。
- `services/worldbuilding/`：世界书页面、模板、投影、作者资料整理和上下文摘要。

## 边界

当前拆分保持：

- world facade 和 `/api/world/*` wire shape 稳定。
- `docs/modules/02_world.md` 与 `docs/modules/15_map.md` 的权威入口不漂移。
- novel_id 隔离、status/candidate 语义、危险操作确认和 Pydantic 校验。
- 跨模块调用继续走 facade/contracts/API/DI port。

## 持续验证

- 跨模块测试继续通过 public interface，不依赖子包内部文件路径。
- 对 map、character、relation、rollback、worldbuilding 各保留最小行为测试。
- 新服务进入已有三个分区；若出现第四个长期领域边界，再通过新决策评估，不把根目录重新
  扩张为平行实现。
