---
id: T-20261015-character-world-progression
title: 世界对象档案、场景导演、写作副驾驶与世界推进设计
status: active
created: 2026-10-15T16:00:00+08:00
updated: 2026-10-15T23:20:08+08:00
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
修订经用户授权在第三个本地提交 `20d6f1eff` 中提交，未推送。
2026-10-15 用户采纳 ADR-0039 至 ADR-0041（Accepted / 未实施）；ADR-0005、0025 补充说明与索引同步。
用户已明确三份计划全部实施，包括档案、导演和世界推进；本任务执行C0–C5。主树1d503209b（代码b81ba6887）已集成C3a审修、R3严格解析修复、C0a审修，root跨域2978pass，Sol有空库/非空PG升级和独立CAS/回滚证据；新服务组合根仍待A0b。C0b/C2 Luna在world-object-dossier-impl新分支做三层聚合，WIP633293ee2接审修发生dossier_service冲突，现暂由Sol直接解决再恢复Luna。C3b Luna在simulation-v3-director-impl/codex/copilot-unified-ui做真实提醒与ReadingFlow待核候选展示、G8a/editorial来源。GenericEntityProfile迁移与消费者切换仍欠，C0/C2/C3不得提前标全完成。共享composition由A0b独占，root仅集成验证及唯一TASK写入；C4/C5继续待批次，C1长期P4/势力/RP门禁保留。

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

## 2026-10-15T21:56:18+08:00 实施检查点

- A0代理独占共享Assistant/装配文件；C0/C3新增独立纯SPEC并交接接线。分别唯一新增object_dossier_v2/notice_dispositions migration，最终Sol统一链。Evidence三层汇总与CharacterCard v2为C2独立后续，simulation_v3/state_trial零漂移为C4前置，不得重复时态真源；RP需其评测门禁后迁移。C1长期P4验收与势力相关阶段依赖保持明确，不用现有旧字段或桩冒称完成。
- 仅本地提交与隔离验证授权；未push/PR/main合并/部署。无新的真实模型/私有评测根/真实数据库访问授权给这些实现代理。工程检查与真实作者验收分开报告。

- 2026-10-15T22:16:25+08:00：地图R3五Scene完成后结构任务严格目标解析失败，已正常停止封存，真实质量未通过；当前无live runner，新功能首批提交审查后可集成，后续评测需新pipeline身份，不复用旧实验。

## 2026-10-15T22:30:37+08:00 首批交付与独立审修

- C3a 69b77838298e7fcda225ef798151a75127c98d23交Sol/high sol_review_unified_notices（map-spatial-eval-review/codex/map-full-plan-integration-review）；7定向/Ruff/import/docs158表/SQLite迁移通过，PG/app接线/UI/G8a/editorial队列详细导航仍待后批。C0 Luna继续World条目/模板/Character兼容和Story注册；Evidence统一聚合/ledger DI为C0b/C2未完成项，C4/C5依此继续。
- root主树fd372d5f2仅任务记录提交，新两批尚未集成；代码问题由Sol直接修。本地开发继续，未推送或部署。

## 2026-10-15T22:44:27+08:00 审修集成与第二批交接

- 主树HEAD158cbe57b，TASK更新前干净。A0a修复：legacy forecast v3快照保留两字段；v7按实际操作兼容关闭；团队冻结不可执行项仍可describe；恢复地图编辑真实schema hash。root在dabc0b319跑Assistant/Imports/World相关扩大回归1217 passed（33.81s）。
- C3五真实来源的Sol修复含延后到期恢复、分页更多披露、处置读timeout、静态trace字段与demo只读写拒绝。R3未解析关系主题留在batch receipt，公开作者GET /api/evolution/reading的structure_review显示数量/内容/逐Scene证据，不猜实体、不关strict。root在158cbe57b跑统一通知+全Story+Evolution workflow为797 passed（21.61s）。C3新API/DI尚待组合根接线，不当产品闭环。
- 原A0b WIP与旧审查分支保留；Sol只读复制新目标分支且核哈希+17烟测，Luna继续实施。C0a23e进入Sol独立审修，C0b/C2 Luna并行，禁止共享文件双写。三migration链待统一，新C0/C3/trace尚未PG验收。
- R3封存停止，本批未重跑真实请求、未改实验DB/原始回执/种子或holdout。真实质量未通过、human_validated=false；本地工程绿色不等于作者验收。没有push/PR/main合并/部署。

- 文档门禁：158cbe57b的inventory通过（12模块/158表/61任务/16路由/49ADR）；直接BASE_REF检查列出CLAUDE.md、模块总览html/drawio、05_memory.md四个未改文件，root已逐项核对并用脚本支持的no-change-reason通过影响检查，理由为稳定导航/现有12模块61方向未变，A0/C3/R3不改Memory事件与checkpoint写入所有权。C0 typed state尚未集成，后续须重核并更新相关文档；不把此理由沿用到未来实现。

## 2026-10-15T23:04:48+08:00 C0a 审修集成与跨域回归

- 主树实现为b81ba6887（C0原13a11cff0 + Sol直接修复），另1d503209b补05_memory类型化来源边界；当前干净。Sol修复非空旧资料created_at默认失败、C3 ORM/迁移FK索引/时间/comment漂移、恢复Scene锚与停用facet、结构化legacy值、demo拒写、typed状态与有向态度、分页unknown、静态trace白名单；动态Story字段不回填World稳定层。
- Sol证据：58 unit；独立PG dossier_review_test_20261015 fresh升级、dossier_upgrade_test_20261015非空旧数据升级；1项独立session并发CAS/失败回滚/跨novel E2E通过。原map_enhancement_test仍map_node_merge未修改；C3两表metadata parity尚依赖A0b共享env/bootstrap notice_models显式导入。
- root在b81ba6887代码上扩大World+Story+Evidence+container/registry：2978 passed、1 skipped、2 deselected（67.62s），已存在Pydantic schema warning无新增失败。1d503209b docs inventory通过：12模块/159表/61任务/16前端路由/49ADR。未完成全分支最终门禁、真实质量或作者验收。
- 三层聚合Luna保存WIP633293ee2并接C3四提交后，cherry c99a702ae在dossier_service.py冲突；root暂时interrupt该子任务释放宿主并发槽，已交Sol直接解冲突，禁止root/Luna手改审修冲突。Luna恢复后继续Evidence聚合与C2。C3b新Luna/max在simulation-v3-director-impl/codex/copilot-unified-ui做真实提醒/ReadingFlow待核候选和缺失G8a/editorial薄来源；无UI假数据。A0b Luna继续trace与组合根，已要求本轮新C0写路由显式绑定op_id，不能放进历史豁免baseline。
- 世界对象统一三层读取/GenericEntityProfile映射、C2人物卡/UI、C3产品接线与界面、A0b/A1–A4、C4/C5均未标完成。R3封存原样、无新模型请求或holdout读取；没有push/PR/main合并/部署。

- 2026-10-15T23:10:03+08:00：C0b冲突已由Sol直接解决并完成cherry为4cb98784d，33目标测试与Ruff通过；原633293ee2聚合/Profile映射与c99安全修复均保留。root已followup恢复Luna，当前继续聚合，不再处于冲突停点。首commit要求独立可导入、不依赖尚未存在ServiceKey符号；角色视角不调用Evolution台账port，作者视角可显式读取，省略单列。

## 2026-10-15T23:20:08+08:00 A0b 提交与环境校验

- A0b原实现三笔自有提交 f9a9d8f14、87752e8fd、203018dfd，Luna目标树map-advisory-review/codex/map-operation-trace-impl已干净；C3/C0父提交已在主树，不能重复取。已交Sol/high sol_review_operation_catalog在map-assistant-review/codex/operation-trace-review，以dd13268fb为基线独立审修，含真实HTTP最终commit失败时序/PG事务/隐私/路由ratchet/装配/单head+parity。当前还未集成主树，不能标A0或产品接线完成。Sol独占工程PG65202新review DB，原库与C0两review库保留，禁止eval65302。
- 实证纠正验证环境：唯一正确解释器是 /Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python（3.14.8/Pydantic2.14.0/core2.50）；原repo/backend/.venv为3.14.7/2.13.5/core2.46.5，不用于最终验证。原环境Decimal schema多pattern导致194c，正确环境schema90aa；两树用正确解释器完整schema逐字段相同，golden未改。Luna A0b在正确环境重跑组合13pass与Ruff。C0b Luna承认早期定向误用原环境，已要求首commit前用正确环境重跑；root前述1217/797/2978全部使用正确worktree解释器，仍为有效证据。
- C0b冲突已解4cb98784d并恢复Luna，继续首个可独立导入的Evidence聚合/brief/API切片；C3b UI及G8a/editorial真实来源仍在实施。后续A1–A4、C2/C4/C5和外部门禁保留；无新真实模型请求、push/PR/main合并/部署。
