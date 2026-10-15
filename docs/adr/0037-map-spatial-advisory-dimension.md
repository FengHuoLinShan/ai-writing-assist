# ADR-0037 — 地图空间信息以参考维度进入创作（修订 ADR-0025）

- **状态**: Accepted / M3 工程切片已实现（配对评测与能力启用待验收）
- **日期**: 2026-10-15
- **关联追踪**: ADR-0025（知识治理，本 ADR 修订其第 4 条的适用范围）、ADR-0017（事实权威）、
  ADR-0035（空间模型 v2 与涌现类型）、ADR-0036（演化可选阅读步骤与空间发现）、
  ADR-0038（助手操作与 `assistant.turn` 参考维度）、
  ADR-0040（参考维度追加 `object_dossier`、`character_pattern`、`director_reference`；
  空间提醒进入写作副驾驶统一提醒）、
  [地图系统增强设计](../plans/2026-10-15-map-system-enhancement.md) §7

## 背景

`map_spatial` 知识维度目前只被地图自身的 5 个能力声明。写作维度 `_WRITING_DIMENSIONS`
（`backend/modules/evidence/compilation/knowledge/policies.py:157`）、剧本、问答世界和 RP
都不读取地图。地图对写作的帮助只有几条提醒：G8a 正文变化后提示核对地图、
G8b 冲突检查比较地图 head、前瞻 `world.map_precondition.v1`。

ADR-0025 的必查维度（`required_dimensions`）要求审查者逐项检查。维度缺失或未检查时，
裁决降为 `unverifiable`；预算型省略也不能签署 PASS。如果直接把 `map_spatial` 加进写作的
必查维度，没有地图或地图不完整的作品会被阻断，空间分歧也会被当作阻断问题。
这与用户裁定冲突：地图只是示意与提醒，不是写作必须遵守的约束。

省略的阻断不止发生在必查维度上。范围解析时 `scope_complete = not omitted and not truncated`
（`evidence/compilation/knowledge/scope.py:459`），不区分维度；声明了 `require_scope_complete` 的流程
（`workflow.py:489`）遇到范围不完整就停下，`KnowledgeScopeReceipt` 里有省略项时也不能签署 PASS。
所以只要参考维度的来源被写进 `omitted`，就会和必查维度的省略一样阻断。

## 决策

### 1. 新增参考维度 `advisory_dimensions`

在 `CapabilityKnowledgePolicy` 中新增参考维度：

- 参考维度可选，不必查。其来源可以进入 `KnowledgeScopeReceipt` 和导演计划
  （归为“生成可用”或“仅审查可见”）。
- 参考维度缺失、为空、被作者排除或因预算被省略，都不会使裁决降为 `unverifiable` 或 `blocked`。
- **省略单独记录**：参考维度的省略写入回执中单独的参考维度省略记录（拟名 `advisory_omitted`），
  不写入 `omitted`，不参与 `scope_complete` 的计算，也不触发 `require_scope_complete`。
  这些省略只提醒、不阻断：回执和审计中照常可见，并向作者披露“参考信息因预算未全部使用”。
- 审查者对参考维度的发现只能是提示（advisory note），服务端裁决不采纳其阻断请求。
- **版本**：回执结构和范围计算规则变化，相关能力的知识策略 `policy_version` 随之升级；
  旧回执按旧版本读取，不重算。
- 本条只修订 ADR-0025 第 4 条（预算型 omission 不得签署 PASS）对参考维度的适用；
  必查维度的规则不变，必查维度的省略仍写入 `omitted` 并照常阻断。
- 其他需要“可选、只提醒”的维度（ADR-0038 `assistant.turn`、ADR-0040 的 `object_dossier`、
  `character_pattern`、`director_reference`）一律使用本条机制，不另设省略规则。

### 2. 首批能力

以下能力把 `map_spatial` 声明为参考维度，并各自通过开关启用：

- `writing.generate`
- `writing.targeted_revision`
- `writing.semantic_review`
- `writing.conflict_check.ai_review`
- `story.script`
- `story.one_click`
- `world.ask`

项目助手的 `assistant.turn` 由 ADR-0038 §10 按同样规则追加。

### 3. 空间简报

- **加载方式**：Evidence 新增空间简报 loader，经 world 地图 facade 只读获取，不直接读地图表。
- **内容**：当前 Scene 地点的上级链、相邻和相通地点、相关行程声明与通行条件，以及移动对象的最后位置。
- **Scene 位置身份**：现有 Scene 只在 `structure_meta` 中可选地携带 `location_id` / `location_entity_id`
  （`evidence/compilation/services/context_compiler.py:2113`）。有地图但 Scene 没有位置身份时，
  不根据正文猜测地点，不注入以当前地点为中心的简报，只注入本场出场对象的最后位置（如有）；
  副驾驶在结构缺项中提示“本场未标注地点”（ADR-0040 §13）。
- **入选条件**（ADR-0035 / ADR-0036），须全部满足：
  - 来自已保存（已采用）的版本；
  - 图元绑定已采用对象，或是未绑定的文字标签；
  - 模态为 `event_observed`（修辞、角色说法和猜测不进入）；
  - 生效区间覆盖当前截止点；
  - 来源 hash 有效，失效的不进入。
- **v1 地图与最小切片**：v1 文档没有模态和生效区间。已采用的 v1 约束视为作者确认、全书有效
  （ADR-0035 §2），满足上述条件。因此本 ADR 可以先只基于 v1 地图实施一个最小切片
  （参考维度机制、空间简报、确定性提醒），不必等待 ADR-0035 的 v2 和 ADR-0036 的自动冷启动。
- **类型的呈现**：项目类型（含模型涌现的类型）以名称和描述的文字形式进入简报，
  让模型理解“传送阵”“洞天”等本项目说法；“涌现中”和已归档的类型只显示原文说法。
- **可见性**：绑定对象按读者揭示策略过滤，不比现有知识边界放得更宽。World 的
  `check_knowledge_visibility()` 目前只由 `world/facade.py` 导出，没有生产调用方；本 ADR 实施时
  是它的首个生产接入，需要补齐经 facade 调用的测试，不能假定它已在生成链路中生效。
- **规模**：设字数上限，具体数值在实施时按评测确定。
- **无地图时**：不注入任何内容，也不写“无地图”之类的占位文字。

#### M3 实施记录（2026-10-15）

Evidence 通过 World 只读 facade 加载已采用节点的 saved head；简报只含来源/引文新鲜且在当前揭示边界内的声明，使用 Scene 的实际章节截止与 `resolve_validity` 当前顺序解析生效锚点。已采用 v1 手工约束即使没有来源也按作者确认读取；带模型任务来源但没有引文的约束不进入简报。Scene 位置只认 `structure_meta.location_id` / `location_entity_id` 等显式身份；本场移动对象仅带入有精确来源和明确 `scene_index` 的最新位置。稳定章节 UUID 与数字章节序号尚无真实映射，因此章节 UUID 锚点保持待核对，不按序号猜测。

写作生成、定向返修、语义审查、冲突 AI 审查、剧本、一键人物包和 `world.ask` 分别由 `MAP_SPATIAL_ENABLED_CAPABILITIES` 控制，项目助手只读工具随 Assistant runtime v5 增加独立的 `assistant.turn` 开关；默认空集合，即全部关闭。简报每节点最多 3000 字符、每次最多 20 节点，超额与作者排除进入 `advisory_omitted` 或明确省略回执，不影响必查范围。确认后地图变化沿用 G8b `read_map_node_heads` 读时比对；不写回地图或建立新失效记录。Assistant run checkpoint 保存引用的 revision/hash，最终知识回执将其列为参考维度。

本切片完成离线合成用例，不调用真实模型或真实稿件。修仙、西幻、都市、科幻、悬疑五题材 paired eval 均 `not_run`，作者验收 `human_validated=false`；所有八个能力开关保持关闭。

### 4. 空间提醒

- **先跑确定性检查**：同一移动对象同时出现在两处；对象出现在尚未生效或已失效的地点；
  方位声明直接矛盾。检查只读 ADR-0035 的计算特性（如“方位有效”“可移动”），不读类型名；
  没有声明特性的类型不参与检查。
- **行程可行性**：只比较同一交通方式、同一旅行者类别的声明，并且需要明确的时间间隔。
  故事内时间能力上线前，只使用正文明确写出的场景间隔；条件不足时输出“无法确认”，不报漏洞。
- **只提示，不拦截**：所有提醒附地图版本和来源，不阻断发布、采用或生成。
  作者可以按条目或按类型静默；处置规则见 ADR-0040 §13。

### 5. 失效

- 简报把所用的地图 revision ID 和 hash 写入 context snapshot。
- 地图变化：沿用 G8b 的读时比对模式，读取时把 snapshot 中的地图 revision 与节点当前 head
  （`world.read_map_node_heads`）比对，不一致时标为“地图已变化，可重新核对”。
- 正文变化：沿用 G8a 的地图册来源核对。
- 不新增失效协议，也不保存核对结论。

### 6. 上线门禁

各能力的开关默认关闭。必须先做对比评测：带与不带空间简报，冻结开发集加单次留出集，
Sol/xhigh 评分，按题材分别报告。证明空间一致性提升、正文质量不下降后，才能开启该能力。
评测前需要在默认评测守卫下开放一个受限评分角色，并完成 seeded 自测；代理验收保留
`human_validated=false`。

### 7. 权威边界不变

地图信息是参考，不是事实。生成者可以偏离地图，审查者只出提示；
地图不进入 CanonRevision（ADR-0017），也不回写 World。

## 后果

- 知识治理新增一类维度语义，需要更新注册表、回执（新增参考维度省略记录）、范围完整性计算
  （`scope.py` 只用必查维度的省略和截断判断 `scope_complete`）、审计收口
  （`_build_audit_coverage` 只对必查维度要求 `checked`）、`make prompt-contracts` 门禁和相关测试。
  需要回归测试证明：参考维度被预算省略时，`scope_complete` 仍为真，`require_scope_complete` 流程不停下。
- 相关能力的 `policy_version` 升级，旧回执按旧版本解释。
- 写作 Prompt 会多出空间内容，成本和噪声都可能上升，必须由对比评测证明有益后才能开启。
- 地图从“只出不进”变成写作的输入；冷启动（ADR-0036）决定有多少地图可以喂给写作。

## 备选方案

### A. 把 `map_spatial` 设为必查维度

拒绝。没有地图的作品会被阻断，空间分歧也会变成阻断，违背“示意与提醒”的裁定。

### B. 绕过知识治理，直接把地图文本拼进 Prompt

拒绝。违背 ADR-0025“所有来源进入回执、可回读、可审查”的原则，也无法做失效追踪。

### C. 只在前端展示地图提示，不进入生成上下文

不足。用户要求地图参与创作决策，仅靠前端展示无法影响生成。
