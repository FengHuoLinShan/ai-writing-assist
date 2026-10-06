# ADR-0031 — 模块依赖方向分层与逐对解环裁定

- **状态**: Accepted / 第一、二、三批已实现
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
理由、三批落地方式（第一批非 assistant 七对 + world 内部
core↔worldbuilding；第二批 assistant 相关六对；第三批剩余 13 个仅剩
函数内反方向的双向对）。

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
| assistant ↔ collaboration | collaboration → assistant（既有顶层方向） | assistant forecast 消费理解包经 `collaboration.collect_forecast_understanding` DI 键，assistant→collaboration 保持零顶层导入；第三批把 creative queue/service 四处函数内消费改 `collaboration.changed_cases`、`collaboration.submit_changed_case`、`collaboration.stop_unavailable_runs`、`collaboration.read_projected_run` DI 键，该方向全清 |
| evidence ↔ story | story → evidence（story 消费 evidence Context/确认基础设施，同 world→evidence 先例；ADR-0004/0015：Context 归 evidence） | evidence 编译消费 story 场景事实经 `story.scene_source` DI port（Scene contract、读者揭示决策、Scene memory 契约版本）；契约唯一事实源仍是 `story/continuity/contracts.py`，evidence 侧仅在消费方 contracts 声明 Protocol，无副本 |
| evidence ↔ writing | writing → evidence（evidence 是确认/编译枢纽；writing→evidence 消费确认与治理能力） | evidence 编译消费稿源区间/清单/字面扫描经 `writing.manuscript_source` DI port（ADR-0004：writing 保持原文事实源）；正文区间引用契约 `SourceRangeRefContract`/`ManuscriptScanCursor` 定义上移 `evidence/source_ref_contracts.py`（source_ref 是 evidence 编译产物的引用锚点），`writing.contracts` 兼容再出口 |
| story ↔ world | story → world（world 是对象/设定事实库，story 叙事消费事实；ADR-0001、ADR-0022 先例） | world 地图在场投影/读者揭示消费 story 经 `story.scene_source` DI port；world→story 顶层导入清零 |
| story ↔ writing | story → writing（既有先例：outline-writing ADR 的注入 provider + 只读 facade 边界） | writing→story 经既有函数内 provider/loader（Scene contract loader、continuity ingest），方向不变 |
| interaction ↔ local_agent | interaction → local_agent（L3→L1） | local_agent 设备确认回写经 `interaction.mark_task_local_approved` DI 键 |
| account ↔ assistant | assistant → account（L4→L0） | account forecast 事实改纯数据：`inspect` 返回纯 dict，assistant 消费侧以 `ForecastDomainFact.model_validate` 物化校验（原单点消费边界不变，校验等价）；无插件操作文件 |
| assistant ↔ evidence | assistant → evidence（L4→L2） | evidence forecast 插件改纯数据：`OPERATIONS_SPEC` 声明 + `inspect` 返回纯 dict；`novel_evidence.py` 读取讨论经 `assistant.inspect_discussion` DI 键 |
| assistant ↔ local_agent | assistant → local_agent（L4→L1，既有顶层方向） | local_agent api 的运行回写经 `assistant.mark_task_local_approved` DI 键（与第一批 `interaction.mark_task_local_approved` 是两个不同实现、两个键） |
| assistant ↔ project | assistant → project（L4→L1） | project 两个操作插件与 forecast 插件改纯数据：`OPERATIONS_SPEC` 声明 + `inspect` 返回纯 dict |
| assistant ↔ story | assistant → story（L4→L2） | story 四个操作插件改纯数据 `OPERATIONS_SPEC`；forecast `inspect` 返回纯 dict |
| assistant ↔ writing | assistant → writing（L4→L2） | writing 三个操作插件改纯数据 `OPERATIONS_SPEC`；forecast `inspect` 返回纯 dict；`comment_run`/`services` 经 `assistant.submit_comment_proposals`、`assistant.mark_editorial_ready` DI 键 |
| collaboration ↔ world | collaboration → world（L4→L2） | world creative 资源 SPI 类型改容器解析（`collaboration.ResourceSnapshot`/`CreativeResourcePort`，`world_bible_draft` 端口改工厂装配，同 story/writing 第二批先例）；world 情境重测 schema（`WorldScenarioCheck`/`ScenarioOutcome`）迁 `collaboration/world_stress_checks.py`——唯一消费方是 collaboration runtime，schema 即 V2 检查协议代码（同第一批 evidence creative manifest 先例），world 语义以字段与 instruction 表达；world→collaboration 与 collaboration→world（runtime 对该 schema 的懒加载）双方向归零 |
| account ↔ project | project → account（L1→L0） | account 生命周期 purge/list_ids 与公共 demo 主体解析消费 project 经 `account.project_context`、`account.project_ids_for_owner`、`account.project_purge_for_owner` DI 键（AO-4 `account.project_owner_ref` 同款） |
| assistant ↔ imports | imports → assistant（既有插件 SPI contracts 通道：`ForecastDomainFact`/`AssistantOperation` 纯类型导入，冻结事实；与理想分层相反，同法物化留待后续批次） | assistant proactive 活跃导入检查经 `imports.get_active_organization` DI 键 |
| assistant ↔ interaction | interaction → assistant（既有主导方向：RP journey 经 assistant facade 消费 forecast/notices，persona 经组合根注册；L3→L4 与理想分层相反，冻结事实，完整反转留待后续批次） | assistant proactive 连续性复核经 `interaction.read_continuity_review` DI 键 |
| assistant ↔ world | world → assistant（既有插件 SPI contracts 通道，冻结事实） | assistant capabilities 地图与 team stress 复核经 `world.map_capabilities`、`world.review_team_stress` DI 键 |
| evolution ↔ world | evolution → world（L3→L2） | world 理解来源重验经 `evolution.require_current_world_candidate` DI 键 |
| evolution ↔ writing | evolution → writing（L3→L2） | writing 源变更失效经 `evolution.record_writing_source_change` DI 键 |
| project ↔ writing | writing → project（L2→L1） | project 作者任务章节来源解析改用既有 `writing.list_latest_drafts_for_chapters` DI 键 |
| project ↔ story | story → project（L2→L1） | project 作者任务 Scene 来源解析经 `story.get_scene_contract` DI 键 |
| evidence ↔ interaction | interaction → evidence（L3→L2） | evidence 公共 demo 来源上下文校验经 `interaction.validate_public_demo_source_context` DI 键 |
| world ↔ writing | world → writing（L2 内既有方向：world 是地图/实体事实源，writing 生成消费；同 story→world 裁定） | writing 地图连续性默认 loader 经 `world.list_adopted_map_continuity_facts` DI 键（注入 seam 语义不变） |
| imports ↔ world | imports → world（L3→L2，既有主导方向） | world 注意力摘要复核处置默认读取经 `imports.get_review_dispositions` DI 键（保留 `_resolution_reader` 注入 seam） |

**第二批机制**：assistant 是 L4 最高层，`assistant→{account, evidence,
project, story, writing, local_agent}` 为合法方向；反向清零落在两类装配
位置移动上，运行期产物逐字节等价（46 个操作的名称、label、permission、
revision、参数 schema 指纹与 prepare/apply/read_result 函数对象经快照
diff 为零，见 `backend/tests/unit/test_assistant_operation_registry.py`）：

- **操作/事实声明数据与 assistant 类型解耦**：领域插件文件只导出纯数据
  `OPERATIONS_SPEC`（label/schema/prepare/apply 与可选
  permission/read_result/revision 的 dict）或让 forecast `inspect` 返回纯
  dict 事实；组合根装配件 `app/assistant_operation_registry.py`（仅被
  `app/bootstrap.py` 导入）依赖 `AssistantOperation` 物化声明数据，未知
  字段失败关闭。`ForecastDomainFact` 的唯一消费点
  （`assistant/forecast/context.py`）本就以 `model_validate` 物化来源数据，
  dict 直传校验等价。world/imports 插件文件因 world↔assistant、
  imports↔assistant 不构成本批顶层双向对而保持原样（后续如需可同法处理）。
- **facade 能力消费改 DI 键**：evidence（`inspect_discussion`）、writing
  （`submit_comment_proposals`、`mark_editorial_ready`）、local_agent
  （`mark_task_local_approved`）经组合根注册的字符串键运行期解析。

**第三批机制**：顶层双向对清零后，剩余 22 个双向对全部只剩函数内反方向。
第三批按"优先消灭低层→高层的非法方向、单侧导入量小者优先"消灭 13 对
（22→9），全部来自消除导入，无顶层降级：

- **SPI 类型容器解析延伸到 world**：`world/creative.py` 与 story/writing
  同款——`ResourceSnapshot`/`CreativeResourcePort` 经容器键解析，
  `world_bible_draft` 端口从模块级常量 `PORT` 改为 `port()` 工厂，组合根
  装配 `collaboration.resources` 时调用（SPI 类型先注册的顺序由
  `_register_collaboration_resource_spi` 保证）；端口形状由
  `test_resource_spi_container.py` 锁定。
- **协议词汇归位 owner 侧**：`WorldScenarioCheck` 唯一消费方是
  collaboration runtime 的 `world_stress` 配方，schema 即 V2 检查协议
  代码，从 `world/creative_scenarios.py` 整体迁
  `collaboration/world_stress_checks.py`（行为零改动，类名与校验逻辑
  不变），连带消除 collaboration runtime 对 world 的反方向懒加载；
  `world/contracts.py` 兼容再出口删除。
- **单点 facade 消费改 DI 键**：account（3 处）、assistant（8 处）、
  world（2 处）、writing（2 处）、project（2 处）、evidence（1 处）
  共 18 处函数内消费改经组合根注册的 17 个新 DI 键
  （project→writing 复用既有 `writing.list_latest_drafts_for_chapters`）；
  键值为原 facade 函数对象，注册即等价，`test_container.py` 扩展键清单。
  消费方持有的既有注入 seam（world `_resolution_reader`、writing
  默认 loader、`creative.port` 工厂）语义不变，仅默认实现改为容器解析。
- **诚实记录反冻结方向**：`assistant↔imports`、`assistant↔interaction`
  的存活方向（imports→assistant、interaction→assistant）与理想分层相反，
  属既有冻结事实（插件 SPI 类型通道 / RP journey 主导消费面），本批按
  单侧量级选择消灭 assistant 侧 1 条函数内导入，完整反转留待后续批次。

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

- 棘轮基线（AO-5 第二批落地后）：`directed_edges` 85→79、
  `bidirectional_pairs` 28→22、`top_level_bidirectional_pairs` 6→**0**
  （12 对全部单向化）、`function_level_imports` 549→544（assistant 六对
  的 5 条函数内导入随 DI 键/纯数据事实消除）、
  `world_core_to_worldbuilding` 0、`world_worldbuilding_to_core` 26。
- 棘轮基线（AO-5 第三批落地后）：`directed_edges` 79→65、
  `bidirectional_pairs` 22→**9**（本批消灭 13 对：collaboration↔world、
  account↔project、assistant↔{collaboration, imports, interaction, world}、
  evolution↔{world, writing}、project↔{story, writing}、
  evidence↔interaction、world↔writing、imports↔world）、
  `top_level_bidirectional_pairs` 0、`function_level_imports` 544→525
  （18 处 facade 消费 DI 键化 + 1 条 schema 迁移连带消除；全部来自消除
  导入，无顶层降级）、`world_core_to_worldbuilding` 0、
  `world_worldbuilding_to_core` 26。
  剩余 9 对：evidence↔{imports, project, story, world, writing}、
  evolution↔story、project↔world、story↔world、story↔writing——
  反方向均为批量消费点（17~34 条函数内）或既有裁定方向的批量 DI port
  消费，留待后续批次按消费方 contracts Protocol / 组合根装配逐对处理。
- 操作注册产物零变化：46 个操作快照测试
  （`backend/tests/unit/test_assistant_operation_registry.py`）钉住操作名
  集合、label、permission、revision 与参数 schema 指纹；解环前后完整
  注册产物（含 JSON schema 与函数对象）逐字段 diff 为零。
- 每个注入 port 的 adapter 均有正常态 + 空态锁定测试
  （镜像 `test_project_ports.py` 风格）；组合根装配的 collaboration 资源
  SPI 类型/端口形状有容器解析测试。
- 本裁定不改变 HTTP API、schema、事件与用户流程；旧
  `outline-writing-bidirectional-dependency.md` 的单例机制成为本 ADR 第 2 节
  机制在 story↔writing 对上的既有先例。
