# 架构决策索引

本目录记录会长期约束实现的架构决策。ADR 正文保留作出决策时的背景和取舍；实现演进只通过
状态、补充说明或新的取代 ADR 表达，不把历史正文改写成当前模块说明。当前运行事实仍应先查
`docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块 README、ORM、migration 与测试。

新增、改名或调整 ADR 状态时，必须同步本索引，并运行：

```bash
make docs-check BASE_REF=origin/main
```

## 编号 ADR

| ADR | 状态 | 当前约束 |
|---|---|---|
| [ADR-0001](0001-state-assembler-ownership.md) | Accepted | `state_assembler` 归属 memory；world 只经稳定 seam 消费。 |
| [ADR-0002](0002-base-crud-service-shape.md) | Accepted | world 通用 CRUD 使用受限 BaseCRUDService 形状，不额外建立空 port。 |
| [ADR-0003](0003-leaflet-for-map-viewport.md) | Superseded | 旧 Leaflet 地图视口已由 ADR-0012 的 AI 地图册取代。 |
| [ADR-0004](0004-novel-evidence-retrieval-seams.md) | Accepted | 原文、Scene、RAG、Context 沿既有模块分工，不新增平行检索领域。 |
| [ADR-0005](0005-core-entity-type-transition.md) | Accepted | CoreEntity 支持受控自定义类型和可逆 Profile 迁移。 |
| [ADR-0006](0006-world-bible-context-activation-ownership.md) | Accepted | world 拥有世界书资料，context 拥有激活规则和编译审计。 |
| [ADR-0007](0007-world-generation-center-consolidation.md) | Accepted | 世界设定 AI 统一进入生成中心；其接口收口部分取代 ADR-0006 的旧共存范围。 |
| [ADR-0008](0008-plot-thread-information-progression.md) | Accepted | 大纲按当前层创作，PlotThread 聚合信息推进，伏笔/揭示保留投影。 |
| [ADR-0009](0009-vue-frontend-incremental-migration.md) | Accepted / Implemented | Vue 3 SFC 已接管实际页面，hash router 仅保留 route-host seam。 |
| [ADR-0009 附录 A](0009-appendix-a-keep-alive-policy.md) | Accepted / Implemented | 所有视图离开时卸载；草稿和恢复状态使用显式 session，不缓存活 DOM。 |
| [ADR-0010](0010-public-browser-account-system.md) | Accepted / Amended | 公开账号、浏览器会话和 owner 门禁；LLM Key 所有权已按账户连接补充修订。 |
| [ADR-0011](0011-keyed-task-coalescing-and-domain-owners.md) | Accepted | 任务合并只管 transport，领域 owner/generation/checkpoint 由所属模块保存。 |
| [ADR-0012](0012-ai-map-atlas-image-storage.md) | Accepted / Implemented | 固定图片模型、私有 S3、独立图片凭证与删除竞态边界。 |
| [ADR-0013](0013-operation-receipts-and-page-local-recovery.md) | Accepted | 作者发起的 AI 长任务以 operation receipt 去重，最多两个 attempt，只在原页恢复。 |
| [ADR-0014](0014-world-object-images-and-single-node-minio.md) | Accepted | 对象图片只经鉴权 API 读取；单机 MinIO 用私有双桶、受限应用凭据和 32GiB 硬配额。 |
| [ADR-0015](0015-story-evidence-and-settings-physical-fusion.md) | Accepted / Phased implementation | 先交付 Story Scene 垂直切片，再在不改持久化身份的前提下物理融合 Settings、Evidence 和 Story。 |

`ADR-0009 附录 A` 延续 ADR-0009 的编号，不是第二个独立决策编号。

## 主题 ADR 与细化索引

| ADR | 状态 | 当前约束 |
|---|---|---|
| [Character 能力并入 World](character-module-merge-to-world.md) | Accepted / Implemented | character 不再是独立模块，人物事实和知识边界归 world。 |
| [LLM、Worker、Embedding 背压与 CSP](llm-worker-embedding-backpressure-and-csp.md) | Accepted | 共享 LLM/任务基础设施采用有界并发、恢复和前端 CSP 基线。 |
| [Embedding batch queue 索引](embedding-batch-queue-architecture.md) | Accepted / Index | 指向上游背压 ADR 的 embedding 批处理细化，不建立第二事实源。 |
| [LLM 限流与熔断索引](llm-concurrency-throttling-circuit-breaker.md) | Accepted / Index | 指向上游背压 ADR 的并发和熔断细化。 |
| [imports 子包拆分](imports-module-decomposition.md) | Partially implemented | `entity_extraction/` 已落地；parsing/workflow/scene 仍保留兼容扁平入口。 |
| [world services 子包布局](world-services-subpackage-layout.md) | Implemented | 已按 core/map/worldbuilding 分区，并保留必要兼容 import seam。 |
| [Outline / Writing 依赖方向](outline-writing-bidirectional-dependency.md) | Partially superseded | offset 断章入口已取消；Scene contract loader 与只读 facade 边界继续有效。 |

## 状态约定

- **Proposed**：尚未批准或尚未成为实现约束。
- **Accepted**：已批准，后续实现必须遵守。
- **Implemented**：Accepted 决策已经在当前代码兑现。
- **Partially implemented**：只兑现了明确列出的部分，剩余范围不能当作当前事实。
- **Partially superseded**：部分原决策已被后续实现或决策取代，正文保留追溯。
- **Superseded**：原决策已被后续 ADR 完整取代，仅保留历史追溯。
- **Index**：细化导航，不制造第二个权威决策源。

完整性由 `docs/architecture/architecture-documents.toml` 和
`scripts/check_architecture_docs.py` 自动校验；`docs/README.md` 只链接本索引，不再手工维护
一份容易漏项的 ADR 子集。
