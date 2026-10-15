---
id: T-20261015-character-world-progression
title: 世界对象档案、场景导演、写作副驾驶与世界推进设计
status: active
created: 2026-10-15T16:00:00+08:00
updated: 2026-10-15T20:00:00+08:00
---

# 世界对象档案、场景导演、写作副驾驶与世界推进设计

## 恢复快照

设计稿与 ADR-0041 至 ADR-0044（Proposed）已按用户三轮要求重写，2026-10-15 经用户授权本地提交，未推送。与地图增强
（T-20261015-map-enhancement-design）、操作目录（T-20261015-agent-operation-surface）同在工作树
`.worktrees/map-enhancement-plan`、分支 `codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；
核对现状时 origin/main 为 `a5a5e5d61`，相关模块无变化）。
下一步：用户评审四份 ADR 和设计稿 §13 的三项默认值；推送或开 PR 按用户安排。实施由用户另行安排执行者，
本任务只负责设计与文档。

## 目标与验收

- 目标：所有世界对象的信息分层、可自定义扩展、经统一接口被有效利用；场景导演作为写作副驾驶的高级扩展，
  以人物表演和可挑选素材辅助写作；副驾驶各项机制对齐最新计划并统一提醒；让离场人物和势力推进，
  延伸出可能的剧情。
- 验收：设计稿写明现状、分层、接口、导演、副驾驶对齐、推进、模块清单、分期和待定项；ADR 写明与
  ADR-0017、0023、0025、0027、0031、0035、0037、0039、0040 和势力路线图的关系；
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

## 已核实现状（main `a5a5e5d61`）

- World：`core_entities` 只有公开与隐藏两段文字；类型化 Profile 字段固定，来源只记到整份 Profile；
  `EntityProfileTemplate` 有表未接入；`Character` 扁平、`current_*` 被覆盖；`EntityRelation` 无生效区间。
- continuity 实体维度对 `entity_updated` 只做字典合并；`field_provenance` 只覆盖位置、保管、锁。
- 台账五类闭集；Story、Evidence、Writing 都不读取台账。
- 生成上下文中非 POV 人物只有外观和语言风格；`ReactionProposal` 无神态、肢体、潜台词；
  `ScriptBeat` 无环境与感官细节。
- 排演每轮 1–3 人、1–3 回合，`story/rehearsals.py:232` 强制生成剧本预览。
- 副驾驶 `SceneCockpit.vue` 四标签；`sceneAlerts.js` 前端组合，不持久化、不能处置；
  `assistant_notices` 已有 `fingerprint` 唯一、四种状态与 `row_version`；
  `app/assistant_operation_registry.py` 为组合根装配件。
- `writing/generation_service.py` 已消费 `adopted_scripts` 并核对依据。

## 关键决定与理由

- 三层分工（World 设定 / continuity 时点 / Evolution 理解）推广到所有对象：在 World 加按章字段会与
  continuity 形成两份时间线。
- 面向沿用 ADR-0035 的“内核 + 项目扩展/涌现”，接入 `EntityProfileTemplate`，与势力模板共用；
  人物新增“表达方式”、地点与物件新增“感官细节”内核面向，直接服务导演输出。
- 统一读取接口由 Evidence 汇总三层，台账经只读 DI 键，避免 L2 依赖 L3。
- 作者有效期默认优先，剧情覆盖只提醒；开关只改变读取规则，不改数据。
- 导演归 Story 新协议 `director_v1`，界面在副驾驶；不设产品上限，成本靠一次一轮和预算预览控制；
  素材→剧本→单章生成复用现有已采用剧本路径。
- 统一提醒由各领域注册只读来源、Assistant（L4）聚合；已有处置只转发，提示类来源用独立处置记录，
  不复制进 `assistant_notices`。
- 世界推进步数不设低上限，改为步长与推进量；导向推进必须报告不自然处，不得强推。

## 交付

- `docs/plans/2026-10-15-world-object-dossier-and-scene-director.md`
- `docs/adr/0041-world-object-dossier-layers-and-interfaces.md`
- `docs/adr/0042-scene-director-copilot-extension.md`
- `docs/adr/0043-world-progression-candidate-simulation.md`
- `docs/adr/0044-writing-copilot-alignment-and-unified-notices.md`
- `docs/adr/README.md`、`docs/README.md` 索引；ADR-0037 关联追踪补链

## 验证

- 2026-10-15（第一版）：`make docs-check BASE_REF=origin/main` 通过；`git diff --cached --check` 通过。
- 2026-10-15（重写后）：`make docs-check BASE_REF=origin/main` 通过（52 个 ADR 文件，架构决策规则所需
  文档均已更新）；`git diff --cached --check` 通过；0041–0044 在 origin/main 与本地各分支均未占用。

## 风险与待决

- 仍待确认的默认值（设计稿 §13）：导演发散度默认“平衡”；导演与推进历史保留到作者删除；
  统一提醒聚合放在 Assistant。
- ADR 编号 0041–0044：起草时 main、各分支和本机 worktree 中没有占用；提交前需再核对。
