# ADR-0031 — 模块依赖方向分层与逐对解环裁定

- **状态**: Accepted / 第一批已实现
- **日期**: 2026-10-06
- **关联追踪**: AO-5（architecture-optimization）、ADR-0004、ADR-0015、ADR-0022、ADR-0027

## 背景

12 个业务模块间存在大量双向依赖，模块边界随编排逻辑互相渗透。
`docs/architecture/README.md` 已给出五层目标态（L0 `account`；L1 `project`、
`local_agent`；L2 `world`、`story`、`evidence`、`writing`；L3 `imports`、
`evolution`、`interaction`；L4 `assistant`、`collaboration`），但 L2 内部
（world/story/evidence/writing 之间）的方向此前未逐对裁定，
`scripts/check_module_imports.py` 的 `_DEPENDENCY_BASELINE` 棘轮只冻结事实、
不裁定方向。Outline / Writing 的双向 facade 依赖曾在
`outline-writing-bidirectional-dependency.md` 中按"注入 provider + 只读消费"
单例处理，本 ADR 把该机制推广为通用裁定。

本 ADR 记录：分层原则、跨层调用的执行机制、每对依赖方向的 owner 裁定与
理由、第一批（非 assistant 七对 + world 内部 core↔worldbuilding）的落地
方式；assistant 相关六对留待第二批补充。

## 决策

### 1. 分层原则（引用 architecture/README 目标态）

编号高者可依赖编号低者。高层经 facade/contracts 调用低层；**低层需要高层
能力时，只能依赖消费方 contracts 声明的纯 SPI Protocol，并经组合根
（`app/bootstrap.py`）注册的 DI port 在运行期解析，不得直接 import 高层
实现**。L2 内部按本 ADR 逐对裁定的 owner 方向消费。

### 2. 执行机制

- **DI port**：消费方 `contracts.py` 声明 Protocol（文档与类型口径），
  owner 侧提供 adapter，`bootstrap.register_container_services()` 注册字符串键，
  消费方运行期 `core.container.get(key)` 解析（AO-3 同款机制；测试经
  `container_scope` 或根 conftest 的全量注册）。
- **共享词汇上移**：同一模块内两个子包（或同层模块间）共同消费的纯数据
  契约/注册表，上移到双方平级的共享位置；不允许任何一方为了共享词汇而
  反向依赖对方实现。
- **禁止降级凑指标**：顶层 import 不允许改写为函数内 import 来满足
  `top_level` 指标；`function_level_imports` 基线只降不升，解环只能通过
  消除导入（注入、事件、搬迁代码到 owner 侧）达成。
- **行为不变**：注入只改依赖方向；pydantic 校验位置、错误码、`novel_id`
  隔离、owner 校验、confirmation 指纹、CAS、事件语义原样保留。

### 3. 逐对裁定

| 对 | owner 方向（合法消费） | 反方向处置 |
|---|---|---|
| collaboration ↔ evidence | collaboration → evidence（L4→L2） | evidence/creative.py 的授权输入物化实为 collaboration V2 协议代码，整体迁移为 `collaboration/creative_manifest.py`；evidence→collaboration 全方向归零 |
| collaboration ↔ story | collaboration → story | story/writing creative adapter 仍是 collaboration 资源 SPI 的 provider：构造 SPI 类型经容器键解析，端口装配收归组合根 |
| collaboration ↔ writing | collaboration → writing | 同上 |
| assistant ↔ collaboration | collaboration → assistant（既有顶层方向） | assistant forecast 消费理解包经 `collaboration.collect_forecast_understanding` DI 键，assistant→collaboration 保持零顶层导入 |
| evidence ↔ story | story → evidence（story 消费 evidence Context/确认基础设施，同 world→evidence 先例；ADR-0004/0015：Context 归 evidence） | evidence 编译消费 story 场景事实经 `story.scene_source` DI port（Scene contract、读者揭示决策、Scene memory 契约版本）；契约唯一事实源仍是 `story/continuity/contracts.py`，evidence 侧仅在消费方 contracts 声明 Protocol，无副本 |
| evidence ↔ writing | writing → evidence（evidence 是确认/编译枢纽；writing→evidence 消费确认与治理能力） | evidence 编译消费稿源区间/清单/字面扫描经 `writing.manuscript_source` DI port（ADR-0004：writing 保持原文事实源）；正文区间引用契约 `SourceRangeRefContract`/`ManuscriptScanCursor` 定义上移 `evidence/source_ref_contracts.py`（source_ref 是 evidence 编译产物的引用锚点），`writing.contracts` 兼容再出口 |
| story ↔ world | story → world（world 是对象/设定事实库，story 叙事消费事实；ADR-0001、ADR-0022 先例） | world 地图在场投影/读者揭示消费 story 经 `story.scene_source` DI port；world→story 顶层导入清零 |
| story ↔ writing | story → writing（既有先例：outline-writing ADR 的注入 provider + 只读 facade 边界） | writing→story 经既有函数内 provider/loader（Scene contract loader、continuity ingest），方向不变 |
| interaction ↔ local_agent | interaction → local_agent（L3→L1） | local_agent 设备确认回写经 `interaction.mark_task_local_approved` DI 键 |

**第二批占位**：`account↔assistant`、`assistant↔evidence`、
`assistant↔local_agent`、`assistant↔project`、`assistant↔story`、
`assistant↔writing` 六对为本批解环后仅剩的顶层双向对，方向裁定与落地方式
由 AO-5 第二批补充进本表。

### 4. world 内部 core↔worldbuilding

core（实体/关系/事件内核）与 worldbuilding（世界书/Profile/采用域）同为
world 模块子包，方向按能力归属裁定：

- **校验与失效钩子注入**：core 写路径的旧正典校验门
  （`world.worldbuilding.require_legacy_canon_write_allowed`）、Synopsis 失效
  钩子（`world.worldbuilding.mark_synopsis_source_changed`）、聚焦采用授权
  （`focused_adoption.authorize/check_sources/fence`）与采用包引擎
  （`world.worldbuilding.adoption_package_service`）由组合根注册，core 运行期
  经容器解析；core→worldbuilding 导入语句 23→0。
- **共享词汇上移 world services 共享根**：关系分组视角
  （`services/relation_group_views.py`）、实体 Profile 注册表
  （`services/entity_profile_registry.py`）、候选基线快照
  （`services/entity_baselines.py`）原放在 worldbuilding 侧迫使 core 反向
  import；上移后 core/worldbuilding 平级导入，原位置保留兼容再出口。

## 结果

- 棘轮基线（AO-5 第一批落地后）：`directed_edges` 90→85、
  `bidirectional_pairs` 33→28、`top_level_bidirectional_pairs` 13→6
  （仅剩 assistant 六对）、`function_level_imports` 558→549（全部来自
  消除导入，无顶层降级）、`world_core_to_worldbuilding` 23→0、
  `world_worldbuilding_to_core` 27→26。
- 每个注入 port 的 adapter 均有正常态 + 空态锁定测试
  （镜像 `test_project_ports.py` 风格）；组合根装配的 collaboration 资源
  SPI 类型/端口形状有容器解析测试。
- 本裁定不改变 HTTP API、schema、事件与用户流程；旧
  `outline-writing-bidirectional-dependency.md` 的单例机制成为本 ADR 第 2 节
  机制在 story↔writing 对上的既有先例。
