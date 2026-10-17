# 第 10 批（补充）：前 9 批未审的前端组件与前瞻

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：AGENTS.md“产品与前端”（作者语言、不暴露 raw ID/内部枚举/token、失败与冲突反馈）、ADR-0040 §5/§11
人物表演卡、`backend/modules/assistant/README.md`“保存资料的短期前瞻”、计划
`docs/plans/2026-10-15-world-object-dossier-and-scene-director.md` §6.5 与迁移表。

## 结论

补审的组件大多符合规格：确认与恢复都绑定预览或版本，所有动态内容都走 `{{ }}` 转义，没有新的
`v-html`、`innerHTML`、裸全局或 `eval`。人物表演卡 v2 的知识边界做得很严：只读一名人物在截止 Scene 的
角色可见简报，不带正文、作者处置、历史理解或其他领域资料；依据的证据编号和原文引用都在服务端重验。
发现 2 个 P3，都没有写测试，原因见各条。

- B10-F1：创作试验的采用确认显示原始回执 UUID、内部术语和内部枚举，预算区显示指纹、tokens 和内部角色名。
- B10-F2：Scene 页前瞻（人物表演卡 v2 和转场卡）在界面上没有入口。

## 已审范围

- 前端：`ObjectDossierPanel.vue`（自定义状态保存）、`InteractionAuthorPanel.vue`（付费整理的确认与恢复）、
  `SceneDirectorPanel.vue`（启动、续演、转入 World 候选、参考剧本）、`StoryFactTimelinePanel.vue`、
  `WorldDossierManifestImport.vue`、`worldRelationsAliasesOps.js`、`ProjectSettingsView.vue`（对象档案设置）、
  `CreativeExperiments.vue`、`ForecastDock.vue`、`GoalPlanStep.vue`、`OperationTraceReport.vue`、
  `SceneCockpit.vue`、`CharacterCardV2Content.vue`；`writingCommandController` 带导演参考的定向返修。
- 后端：`assistant/operation_trace_report.py` 及其 API；`assistant/forecast/` 的 `character_response.py`、
  `context.py`、`runtime.py`（能力选择与 Scene 双卡执行）、`service.py`（feed 与候选读取）；
  `story/forecast.py`；`writing/semantic_review.py` 第 1595–1705 行（导演参考的定向返修校验）。
- 为核对入口补读：`router.js` 的 `_normalizeRoute`、`vue/shared/assistantContext.js`、
  `vue/composables/useForecast.js`、`ProjectAssistant.vue` 的前瞻上下文、`WritingView.vue` 的 Dock 挂载。
- 仍未审：`GoalPlanField.vue`、`WorldProgressionPanel.vue` 的连续授权与分支管理、Scene 工作台其余小改动、
  `operation_trace_http_adapter.py`。

## 确认无问题

- 对象档案自定义状态：保存带模板版本号和固定幂等键；重新读取后确认已显示才清除草稿，否则保留草稿并提示。
- 互动作者面板：
  - 旅程变更先预览、再带预览哈希确认。
  - 付费整理在发请求前把带 `operation_id` 和预览哈希的确认请求存进草稿；结果未知时按原请求查回执，
    不重新提交；409 时作废预览，要求重新读取预算。
- 导演面板：启动和续演都带 `operation_id` 与 `budget_preview_hash`；旧请求结果未知时，要作者勾选
  “可能重复计费”才能续算；转入 World 候选只建待处理候选，不直接采用。
- 事实时间线、表格清单导入、关系与别名编辑：未发现问题；`worldRelationsAliasesOps.js` 拼进 HTML 的动态文本
  都经 `esc` 转义。
- 项目设置的对象档案开关：`expected_version` CAS。
- 带导演参考的定向返修：服务端要求 Scene 与视角和原生成一致，并冻结
  `director_reference_context_snapshot`。
- 留痕报表：API 校验 owner 并拒绝演示账户；CSV 导出做公式转义；归档计数一致。前端有请求代数和 abort，
  防止切换作品或时间范围后迟到响应覆盖；操作、事件、字段都翻译成作者语言，不显示原始标识。
- 目标计划步骤卡：差异字段名经 `_field_label` 翻译，`*_id` 字段不进入差异。
- 人物表演卡 v2 的知识边界：
  - 前瞻：`materialize` 收到 v2 时只读 Story 域；跳过正文、焦点目标、历史理解、成本门禁与正文集合；
    拒绝资料确认；章节截止取 Scene 最早章节。
  - Story 来源：人物必须是本场人物卡或 POV；简报用 `reveal_mode="character"`、
    `viewpoint_character_id`、`content_mode="canonical"`，返回的作品、Scene、视角不符就丢弃；作者在
    前瞻设置里有任何排除项时 Story 来源直接返回空。
  - 执行：表演卡调用的 `author_decisions` 固定为空，和转场卡分开物化、调用、复核。
  - 校验：只接受一个 `story.character_response.v2` 资料；依据类型必须真实存在；
    `evidence_ids` 只能是这份资料；`quote` 必须出现在对应分区。
  - 现有集成测试 `test_character_response_v2_runs_through_scene_feed_and_writing_preview` 用六类秘密
    断言了模型输入不含其他人物秘密、作者未来安排和正文。
- `SceneCockpit` 改版去掉了“运行规则检查”按钮，写作页工具栏和状态区仍保留冲突检查入口。

## 发现

### B10-F1（P3）创作试验的采用确认显示原始回执 UUID、内部术语和内部枚举

- 位置：`frontend-console/vue/components/CreativeExperiments.vue`：
  - 第 54 行，采用确认正文：“这是 R3 跨域原子采用；……检查回执 {{ mergePending.preview.check_receipt_id }}，
    读集 … 项”。
  - 第 55 行，逐条来源：`{{ source.kind }} · {{ source.label }} · 修订 … · 指纹 {{ source.source_hash.slice(0, 12) }}`。
  - 第 42、44 行，预算区：资料指纹、tokens，以及 `role_snapshot_fingerprints` 的键（内部角色名）。
  - 后端 `modules/collaboration/assistant_tools.py:543` 的 `check_receipt_id` 是 `str(check.id)`，即 UUID；
    第 390 行是 `role_snapshot_fingerprints`。
- 规格：AGENTS.md“默认用作者/读者语言，不暴露 raw ID、JSON、Prompt/token、内部枚举或数据库心智模型；
  诊断放次级入口”。
- 问题：作者在决定是否采用时，看到的是 UUID、“R3”“读集”、`source.kind` 原值和哈希前缀。这些是诊断
  信息，应放进次级展开，或者换成作者能理解的说法，例如“已核对 N 项资料，均未变化”。不涉及数据或
  安全：确认仍绑定服务端回执。
- 未写测试：这个组件没有测试文件，写一条 `it.fails` 要先搭整套 API、桥接和预览替身；而且断言写成
  “不出现 UUID”还是“出现某句作者语言”，要等修复方向定下来。

### B10-F2（P3）Scene 页前瞻（人物表演卡 v2 和转场卡）在界面上没有入口

- 位置：
  - 后端 `modules/assistant/forecast/registry.py` 的 `defaults("scene")` 返回
    `["story.character_response.v2", "story.scene_transition.v1"]`；`runtime.submit` 只在
    `requested_capabilities` 显式点名或 `page == "scene"` 时才会选到 v2。
  - 前端不会发出这两种请求：
    - `router.js` `_normalizeRoute`（第 355–361 行）把 `scene` 视图统一改写成 `outline`/`scenes`，
      `state.currentView` 永远不会是 `scene`。
    - `ProjectAssistant` 把 `shellState.currentView` 作为 `page` 传给 `captureWorkContext`，所以在 Scene
      工作台得到的是 `page: "outline"`，默认能力是 `information_window` 和 `structure_impact`。
    - `WritingView.vue` 第 283–287 行的 Dock 固定 `page: 'writing'`。
    - 前端没有任何地方发送 `requested_capabilities`。
  - `ForecastDock.test.js` 新增的表演卡用例直接以 `context: { page: "scene" }` 挂载，绕过了真实入口。
- 规格：`backend/modules/assistant/README.md`“新 Scene 默认在同一父运行预算下分别生成角色已知范围的
  人物表演卡 v2 和作者视角转场卡”；计划迁移表“短期前瞻：作为副驾驶的‘下一步建议’；
  `story.character_response.v1` 改为以对象简报为依据、按表演卡格式输出”。
- 问题：后端、Dock 渲染和复制为写作参考都已完成，作者却无法触发。旧 v1 在合入前同样不可达（路由
  重定向不是本系列引入的），但本系列把表演卡 v2 作为交付项。导演面板仍能产出表演素材，所以作者不是
  完全拿不到表演卡，只是“前瞻里的表演卡”这条路走不到。
- 未写测试：修复方向有多种（Scene 工作台挂 Dock 并传 `page: "scene"`；`captureWorkContext` 在大纲
  Scene 子视图带 `scene_id` 时映射为 `scene`；写作页 Dock 带 Scene 时显式请求 v2），测试要写在哪一层
  取决于选哪种。
- 补充：一旦接入口，需同时处理 `service.feed` 的两个失败点。feed 在 Scene 页总按 v2 物化，没有
  `scene_id` 时 `materialize` 返回 422“人物表演候选需要从当前场景发起”，带资料确认时返回
  “人物表演候选不能读取混合作者确认资料”。整个 feed 失败，转场卡也看不到；合入前同样的请求会返回空列表。

### B10-F2 入口建议（2026-10-17，按 ADR-0042 草案修订，待确认）

用户指出 `codex/director-scales-plan` 上的 ADR-0042（Proposed，未提交）与配套计划
`docs/plans/2026-10-17-director-scales-independent-exploration.md` 是这类任务的后续规划。下面据此修订，
取代本节末尾的初版建议。只读了该工作树，没有改动。

- 结论：不再给表演卡 v2 单独接 Dock 按钮。“某人物对这句话会怎么反应”就是 ADR-0042 场景尺度的最小任务
  （§1 表“一句回应”，计划 M1“场景只处理一句对白”）。主入口是助手自由提问；写作页、大纲 Scene 人物卡、
  对象档案人物页做就地入口，携带选中的正文、Scene 或人物，指向同一个 Story 任务和结果（ADR-0042 §2）。
- 输出：默认单人紧凑卡；“说详细点”在同一任务里展开；作者要“完整排演”时才转导演的多人多轮（§4）。
  初版建议的“去导演”链接对应这一展开。**更正**：v2 并不紧凑，`CharacterResponseProposal.options` 要求 2–3 个
  动机不同的全字段选项，Story 反应 v2 是每人 2–4 个，导演每人每轮一张全字段卡；三套 schema 字段名也不同。
- 写作页仍是最重要的就地入口：能力清单的可控动作“在当前草稿上准备待确认的写作候选”只有写作页有草稿。
- 规划缺口：ADR-0042 全文没有“前瞻”，§8 修订表只列 ADR-0040 §1、§3、§5–§9 和 ADR-0041，没有
  ADR-0040 §14（短期前瞻作副驾驶“下一步建议”，人物反应按表演卡格式）。照现稿实施，Assistant 前瞻里的
  v2 和 Story 新的场景聚焦任务会成为两条“单人反应”路径；归属也冲突：ADR-0042 §7 把任务、编排和历史
  归 Story，v2 的执行和候选在 `assistant/forecast`。
- v2 与 ADR-0042 的差距，M0 要逐条定：
  - 起点：v2 必须从 Scene 发起（`assistant/forecast/context.py:298`），人物只认本场人物卡或 POV；
    ADR-0042 §3 要求支持临时起点和临时人物。
  - 资料确认：v2 拒绝任何资料确认（`context.py:84–86`），有排除项时 Story 来源直接返回空；ADR-0042 §3
    要求经确认的资料范围、排除和角色可知投影，并能重物化。
  - 历史：v2 结果是前瞻 feed 里的候选，没有局部修订、同起点比较、保存/恢复和分支；ADR-0042 §6 要求
    由 Story 保存。
  - 可复用：角色可见简报（`reveal_mode="character"`，不带正文和作者处置）、证据编号与引文的服务端重验。
  - 补查发现：Story 已有 `story.reaction.generate`（`story/assistant_generation_tools.py`、`story/tasks.py`），
    worker 逐人用各自可见资料、走资料确认、来源重验，助手操作在父任务预算内按 R1 执行，Scene 工作台
    `SceneSimulationPanel` 可达。它比 v2 更贴近 ADR-0042 §7 的 Story 所有权，应作主链。
  - 授权：导演与世界推进的 start/resume 登记为 R4（ADR-0038：每次单独确认、不进目标运行），与“不逐层确认”
    冲突；R1 在单轮助手内本就自动执行，跨轮目标应走 `goal_run_v1`。
- 建议：
  1. ADR-0042 §8 修订表补一行 ADR-0040 §14：人物反应改由 Story 场景尺度任务承担，前瞻保留其余“下一步
     建议”能力。计划 §2 基线表补 `assistant/forecast` 的 v2 链路，M0 加一项“定 v2 与转场卡的去向”。
  2. M1 场景尺度的“一句对白”切片以 `story.reaction.generate` 为主链，加单选项与字段子集画像，引文校验
     参照 v2 并改为按字段值匹配；不另写第四套表演卡或单人反应生成。
  3. ADR-0042 采纳前，不先给 v2 接前端入口。所有前瞻能力的 `default_enabled` 都是 false，ADR-0042 的新路径
     也默认关闭；现在接 Dock 还要先修 feed 的 422、跨章作用域和跳离写作页，做完就要迁移。B10-F2 保留为
     记录，修复挂到 ADR-0042 的 M0/M1；回归测试写在“从助手提问或写作页就地入口发起，结果落到同一任务”这一层。
  4. 转场卡（`story.scene_transition.v1`，作者视角）更接近事件尺度的因果补桥或前瞻“下一步建议”，也在 M0
     定去向。

- ADR 修订（2026-10-17，用户要求“按推荐改 ADR”）：会话隔离不允许写 `director-scales-plan` 工作树，改为生成
  补丁 [ADR-0042-revision.patch](ADR-0042-revision.patch)，覆盖 ADR-0042、配套计划、ADR 索引行和该任务记录。
  在原件副本上 `patch -p1` 结果与修改件逐字一致；生成时四个源文件与复制时一致。尚待用户应用并在该工作树跑
  `make docs-check BASE_REF=origin/main`。

#### 初版建议（ADR-0042 之前，按现行 ADR-0040 §14；仅作过渡参考）

ADR-0042 采纳前原决策继续有效（ADR-0042“关系”一行）。如果必须在采纳前开放，最小方案仍是写作页右栏
“下一步建议”（`ForecastDock`）：本章已关联 Scene 时出现“人物会怎么反应”，提供人物下拉（默认本场 POV）
和按钮，单独以 `requested_capabilities: ["story.character_response.v2"]` 发起，不和“帮我想下一步”合并。
不推荐的位置：大纲 Scene 工作台（“推演”就是导演，且没有草稿）、“对象”标签作主入口（会把 AI 建议混进
事实档案）、项目助手前瞻标签（入口深，带资料确认会被拒）、随“帮我想下一步”自动出（后端禁止 v2 混跑
和自动触发）。

无论入口放在哪里，以下几点都要处理：

- 人物列表要与后端同源：后端只认本场人物卡与 POV，对象标签还会列 Scene/World 关联对象。
- “只润色”意图会把 v2 过滤掉。
- 有任何排除项时 Story 来源返回空，后端报的原因“请从含有人物卡或 POV 的场景入口选择人物”是错的。
- Scene 跨章时，v2 的截止章与写作 feed 的作用域可能不同，刷新后卡片可能从写作页列表消失。
- 卡片跳转目标是 Scene 页，会把作者带离写作页。
- 补一条从真实入口发起的测试。

## 观察（未定为问题）

1. `SceneDirectorPanel.vue` 的 `saveReference`（第 838 行）没有设置 `busy`。按钮只看 `busy`，连点会发出两次
   保存，生成两份同名参考剧本。副本可以删除，不丢数据。
2. 关系与别名的有效期下拉只列 Scene 选项（`worldRelationsAliasesOps.js` 第 55–58 行）。已有的章节锚点即使
   仍然有效，也总被列成“原章节锚点待核对”（第 67 行），作者会误以为锚点失效。
3. 表演卡依据的 `quote` 是在 `json.dumps` 后的分区文本里做子串匹配（`character_response.py` 第 153–175 行），
   所以引用 `facing`、`visibility` 这类键名或标签（例如“人物资料”）也能通过。不会越过知识边界，因为
   这份文本本来就只含该人物可见的条目，但“逐字引用”的约束比字面意思弱。

## 回归测试

本批两个发现都没有写测试，理由见各条；后端与前端回归文件均未改动。
