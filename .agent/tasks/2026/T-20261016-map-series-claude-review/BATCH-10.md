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
