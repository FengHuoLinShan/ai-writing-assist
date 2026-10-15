---
id: T-20261015-character-world-progression
title: 世界对象档案、场景导演、写作副驾驶与世界推进设计
status: active
created: 2026-10-15T16:00:00+08:00
updated: 2026-10-15T23:00:00+08:00
---

# 世界对象档案、场景导演、写作副驾驶与世界推进设计

## 恢复快照

设计稿与 ADR（Proposed）已于 2026-10-15 经用户授权本地提交 `87e56f241`，未推送。之后按用户要求逐条核对
一份 33 条外部评审并合并 ADR：本任务的四份草案合并为 ADR-0039（档案，原 0041）、ADR-0040（副驾驶 v2：
导演、机制对齐与统一提醒，原 0042 + 0044）、ADR-0041（世界推进，原 0043）。用户随后确认设计稿三项默认值，
修正与裁定经用户授权在第二个本地提交中提交，未推送。
与地图增强（T-20261015-map-enhancement-design）、操作目录（T-20261015-agent-operation-surface）同在工作树
`.worktrees/map-enhancement-plan`、分支 `codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；
最后核对时 origin/main 为 `00d861283`，未占用 0035–0041 编号）。
2026-10-15 技术评审后按用户裁定修订：ADR-0040 统一推演协议 `simulation_v3` 并下线原协议、
导演剧本改为只作参考的“参考剧本”、提醒聚合只经登记表；ADR-0041 改为 `simulation_v3` 的世界推进模式；
ADR-0039 旧接口写回规则、共用词表与锚点、档案发现按 ADR-0036 §1 契约登记。
修订经用户授权在第三个本地提交中提交，未推送。
下一步：ADR 转 Accepted、推送与 PR 按用户授权。
实施由用户另行安排执行者，本任务只负责设计与文档。

## 目标与验收

- 目标：所有世界对象的信息分层、可自定义扩展、经统一接口被有效利用；场景导演作为写作副驾驶的高级扩展，
  以人物表演和可挑选素材辅助写作；副驾驶各项机制对齐最新计划并统一提醒；让离场人物和势力推进，
  延伸出可能的剧情。
- 验收：设计稿写明现状、分层、接口、导演、副驾驶对齐、推进、模块清单、分期和待定项；ADR 写明与
  ADR-0017、0023、0025、0027、0031、0035、0037、0038 和势力路线图的关系；
  `make docs-check BASE_REF=origin/main` 通过。

## 用户要求与裁定（2026-10-15）

- 第一轮：人物的性格、外表、喜好、主要经历等要记录和更新维护；导演利用这些信息辅助新剧情、人物反应、
  场景变化、细节修正；让一部分世界动起来。
- 第二轮：所有世界对象的信息像人物一样分层，可高度自定义扩展，暴露好接口；导演允许 AI 充分发散，
  去掉人物数量等限制；轮数默认一轮，点一下推进一轮，保留历史剧本；重点输出人物的行为、表情、心理，
  对抗同质化；场景细节给全，由作者挑选组成角度；副驾驶的提醒机制结合进来，导演是副驾驶的高级扩展；
  副驾驶各项机制同步对齐。
- 第三轮裁定：
  1. 有支持但未采用的台账倾向允许作为参考，提供开关（“只用已采用条目”，默认关）；
  2. 世界推进参与者上限默认 12，可自定义；
  3. 步数按模型每步推进量设计（步长可选、报告推进量、步数不设低上限、按模型推荐步长）；
     作者可以设定大致剧情，模型结合世界对象推演（导向推进）；
  4. 作者设定的有效期在剧情自然覆盖时提醒；默认不被覆盖，提供开关（默认关）。
- 第四轮：再确认一份 33 条评审清单，并合并可合并的 ADR。
- 第五轮确认默认值：导演发散度“平衡”；导演与推进历史保留到作者删除；统一提醒聚合放在 Assistant。
- 第六轮（技术评审后）：参考维度省略只提醒不阻断；统一原排演协议和新协议并下线原协议；草图尽量增量、
  必要时才重做；导演剧本被选用后只给作者思路，正文另写（AI 或手写）；做“可选阅读步骤”契约；其他按推荐。

## 已核实现状（main `a5a5e5d61`，评审核对时复查）

- World：`core_entities` 只有公开与隐藏两段文字；类型化 Profile 字段固定，来源只记到整份 Profile；
  `EntityProfileTemplate` 有表未接入；`Character` 扁平、`current_*` 被覆盖，并被后端 22 个非测试文件、
  前端 6 个文件读取；`EntityRelation` 无生效区间。
- continuity 实体维度对 `entity_updated` 只做字典合并；`field_provenance` 只覆盖位置、保管、锁。
- 台账五类闭集；Story、Evidence、Writing 都不读取台账；ADR-0031 依赖表没有 evidence / evolution 行。
- 生成上下文中非 POV 人物只有外观和语言风格；`KnowledgeScopeReceipt` 有 omitted 与原因，但任何 omitted
  都使 `scope_complete` 为假（`evidence/compilation/knowledge/scope.py:459`），`require_scope_complete` 流程会停下；
  `ReactionProposal` 无神态、肢体、潜台词；`ScriptBeat` 无环境与感官细节。
- 排演每轮 1–3 人、1–3 回合，`story/rehearsals.py:232` 强制生成剧本预览；交汇只有
  `story/simulation.py` 的 `resource_key` 争夺。`observation_v2` 还被状态试验（`story/continuity/state_trial.py`）
  和 RP 多角色演绎（`interaction/ensemble_v2.py`、`ensemble.py` 经 `story.facade.rehearse_round`）使用；
  `SimulationSeed.locations` ≤4、`audience` ≤3、目的地是文本。
- `get_scene_story_basis_hash`（`story/service.py:1160`）只统计 Scene、大纲、人物卡和已采用剧本；
  `SceneScriptFile` 没有文件类别字段。
- Assistant 冻结出边只有 account、evidence、project、story、writing（`scripts/check_module_imports.py:102`）。
- 人物更新 `CharacterUpdate.expected_updated_at` 不一致返回 409；服务按 `exclude_unset` 只处理传入字段。
- 副驾驶 `SceneCockpit.vue` 四标签；`sceneAlerts.js` 前端组合，不持久化、不能处置；
  `assistant_notices` 已有 `fingerprint` 唯一、四种状态与 `row_version`。
- 费用口径：`AIChargeState`（none / recorded / possible）只记计费状态，不估算金额。

## 关键决定与理由

- 三层分工（World 设定 / continuity 时点 / Evolution 理解）推广到所有对象：在 World 加按章字段会与
  continuity 形成两份时间线。档案条目只经 World 档案修订入口写入。
- 面向沿用 ADR-0035 的“内核 + 项目扩展/涌现”，接入 `EntityProfileTemplate`，与势力模板共用。
- 统一读取接口由 Evidence 汇总三层，台账经只读 DI 键，避免 L2 依赖 L3；实施时 ADR-0031 补登记一行。
- 作者有效期默认优先，剧情覆盖只提醒；确定性检测只针对有对齐键的结构化项，文字条目走演化提案。
- 推演协议统一为 `simulation_v3`（用户裁定统一并下线原协议）：导演轮次、世界推进步、状态试验、RP 观察者回合
  是模式，基于 ID，协议不设上限、入口可有运行策略；Story 停止新建 `rehearsal_v1`/`observation_v2`，
  RP 过评测门禁后迁移，旧运行只读。
- 导演界面在副驾驶；不设产品上限，用量靠一次一轮和预算预览控制。素材→参考剧本（保存内容副本，存在导演
  自己的存储中、不写 `SceneScriptFile`）只给思路：不进 story 依据 hash、不作已采用剧本约束；正文另写，
  AI 生成经 `director_reference` 参考维度读取或手写（用户裁定）。存为参考剧本为 R2。历史只由作者删除，30 天可恢复。
- 统一提醒由各领域注册只读来源、Assistant（L4）只经 `app/notice_source_registry` 聚合（不直接导入 world/evolution）；
  已有处置只转发，其余用独立处置记录，不复制进 `assistant_notices`；来源区分“已有/待接入”，结构缺项改由 Story 计算。
- 档案旧接口写回：与当前拼接相同不改；不同则收拢为该面向（该旧字段下）唯一作者条目，其他标已过时可恢复；保留 409。
- 对象档案发现是 ADR-0036 §1 可选阅读步骤契约的第二个新增实例；项目面向存于 ADR-0035 统一项目词表。
- 导演与副驾驶对齐合并为一份 ADR：两者共用简报、一致性检查、提醒，分开维护会反复交叉引用。
- 世界推进步数不设低上限，改为步长与推进量；交汇检测要求意图带结构化字段。

## 交付

- `docs/plans/2026-10-15-world-object-dossier-and-scene-director.md`
- `docs/adr/0039-world-object-dossier-layers-and-interfaces.md`
- `docs/adr/0040-writing-copilot-scene-director-and-unified-notices.md`
- `docs/adr/0041-world-progression-candidate-simulation.md`
- `docs/adr/README.md`、`docs/README.md` 索引；ADR-0037 关联追踪补链

## 验证

- 2026-10-15（第一版、重写后）：`make docs-check BASE_REF=origin/main` 通过；`git diff --cached --check` 通过。
- 2026-10-15（评审核对与合并后，未提交）：`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件，
  架构决策规则所需文档均已更新）；`git diff --cached --check` 通过；旧文件名、旧编号残留扫描为零
  （仅保留一处说明 G8c 与地图无关的文字）。

- 2026-10-15（写入默认值确认后）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。
- 2026-10-15（技术评审修订后，未提交）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过；
  `director_v1`、“存为剧本并采用”、“复用 observations.py”残留扫描为零。

## 风险与待决

- 无待用户裁定项。
- 世界演化第四阶段计划 §6 已加承接说明：受控短期推进由 ADR-0041 承接；开工前与第四阶段实施任务划分写入者。
- 实施前置：ADR-0039 的 C0 映射表与读取方清单；ADR-0040 按参考维度 → 对象接口 → 统一提醒 → 导演推进。
