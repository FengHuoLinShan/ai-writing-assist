# 文档影响核对

本次 AO-12 新增 events.status 及 canonical/deprecated 生命周期，并增加锁内状态重验、
安全降级保护及专用 PG 验证。已同步 World README、World 模块设计、数据库设计与测试指南。

未改文档逐项核对如下：

- development-guide.md：工具链、启动/发布入口与回退机制未变；原有应用回退保留 schema 的
  规则继续适用。新增 migration 的版本跟随既有 head 管理，无新人工操作或生产发布。
- docs/architecture/README.md：模块归属、依赖方向、技术栈、运行 topology 和 DI 注册未变；
  复用原 CoreEntityRepository 的锁方法，不新增 port 或依赖边。
- docs/architecture/documentation-maintenance.md：只消费既有文档影响与无影响说明协议，
  不改变文档权威、维护步骤或机器清单。
- docs/modules/15_map.md：地图 API、模型、图层与生成流程未变；world 的事件背景读取
  过滤 deprecated 扩展，与 World 文档说明一致，不新增地图状态或历史推演能力。
- CONTEXT.md、docs/00_整体设计.md 与架构图：仍由 World 拥有事件扩展，Story 解释时序状态；
  没有正式事实权威切换或模块拓扑变化。events.status 不是 Story 事件/断言状态。

HTTP 响应仅加性提供 event.status，旧请求字段、novel_id/owner 门禁、删除 CoreEntity 的
领域确认与项目永久删除语义保持；Prompt、LLM 调用、前端和部署配置未变化。
