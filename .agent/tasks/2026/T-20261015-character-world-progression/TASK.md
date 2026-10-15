---
id: T-20261015-character-world-progression
title: 世界对象档案、场景导演、写作副驾驶与世界推进设计
status: active
created: 2026-10-15T16:00:00+08:00
updated: 2026-10-16T02:14:59+08:00
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
用户已明确三份计划全部实施。A1已审业务固定6a31ba327；root扩大回归2123 passed/1既有Pydantic warning，专用A1 PG2 passed。C2完整固定点f6c3790ccb已由Sol在map-clue-review合为c364deaee，继续独立修复；已回报字段证明、真实Settings与V2人物卡/反应UI修复及定向Evidence17/Story41/Vue20通过，尚未最终集成。新发现Assistant首次prepare无operation_id会被C2 R1错误拒绝，由Sol直接修并验证实际目录/HTTP/worker/根预算。Goal Luna在af3b00836继续A2行为测试/恢复/实际UI；C4b Luna在ea8889f16独立树实现导演协议、持久化、预算与任务，均非交付。C0c、A1后续、A3/A4、C5及真实/势力/RP门禁全部保留在范围；下一批的源代码核实与验收已记录到C0C-HANDOFF.md和A3-A4-HANDOFF.md。

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

- 后续协议/导演/推进批次的具体源文件、共享写入边界与验收切片见 [C4-C5交接](artifacts/C4-C5-HANDOFF.md)；原三份计划范围不因拆批缩小。

## 2026-10-15T23:31:00+08:00 三层简报提交与真实 HTTP 追踪审修

- C0b首切片30d5b0698已独立提交，需连同前置633293ee2审查；C3/C0a父提交不重复cherry。新增Evidence三层聚合facade/API、只读Evolution provider与明确省略；角色投影不调演化台账。Luna已在唯一正确3.14.8/Pydantic2.14.0下跑45目标测试、Ruff/diff通过。未集成，也不等于C0/C2完成。
- GenericEntityProfile旧PUT仍直接写data_json/evidence_refs；旧GET/list与WorldBackground仍读旧表；类型转换snapshot/restore和generic→strong迁移仍需bridge。Luna继续C2卡片/Reaction后独立实现事务修订桥接、兼容读投影、未知字段/证据及转换恢复保真。不能把新增只读projection当新旧真相闭环。
- Sol在A0b真实PG/HTTP先失败后修复两个P1：main读取未赋值trace context；当前FastAPI include_router有效route派发绕过source APIRoute wrapper。已直接修并3项PG E2E通过，含成功/最终commit失败回滚/原文不入trace；其它审查仍在进行，未集成。另修任意result/preview id泄露、纯flush操作事务形态误报、新Vocabulary绑定与空间线索单项真实豁免。没有将新增写路由藏入旧baseline。
- C3b统一提醒前端及G8a/editorial纯来源继续实施，共享装配仍由A0/Sol单一写入。A1/A2源码、状态机和验证交接见操作任务artifacts/A1-A2-HANDOFF.md；C4/C5交接仍见对应任务artifacts。所有剩余阶段继续属于本次范围。
- R3和holdout未动；没有新增模型请求、push、PR、main合并或部署。主树本次仍只更新任务记录，不提前纳入未审代码。

- 下一批C0b审查树已准备：map-spatial-eval-review/codex/object-dossier-evidence-review，从258ed7b23 cherry633293ee2在world/dossier_service.py遇到同一legacy projection/total_count冲突，已停住，未由root改代码；后续Sol直接解决并继续cherry30d5b0698。原codex/world-object-dossier-review/c99分支保留。Luna实现树不受影响，仍推进C2/Generic桥接。

## 2026-10-15T23:58:00+08:00 A0b集成与扩大回归失败处理

- A0b原f9a/8775/2030三笔与Sol df668净fix已集成primary为98cbdced9、1f77bf4dc、5d7b270ff、d20d27517；真实HTTP派发、事务、隐私、缺口标记、180天worker归档均有Sol112目标与6PG证据。原74项当前无live multi_stage成功路径，只有未知异常fail-closed测试，不宣称未来内部commit成功路径已实测。
- root在d20正确3.14.8环境扩大Assistant/全部tests/unit/Collaboration/World助手-空间-档案/Writing API助手及API闭环：9 failed、2162 passed、4 warnings，90.71s。失败含3个guided_flow run fixture缺session_id、R0 read fixture缺trace字段、13条active-project guard识别或入口问题、map_spatial loader期望列表、World facade __all__、一处autospec。另有3个Connection._cancel未await RuntimeWarning待triage。完整日志/tmp/map-a0b-primary-regression-20261015.log；原Sol已恢复直接修，root不手改。
- root module-import-gate 61/61、517/517通过；docs inventory164表/61任务/16路由/49ADR通过。BASE直接仅剩CLAUDE.md需审阅，root已读其仅@AGENTS导入/导航，按脚本支持no-change-reason逐项说明通过。World档案文档d7c6f45d3、架构HTML/Drawio 2c57b99bb已同步并浏览器看图，不能说未经说明的直接make BASE全绿。
- C0b新Sol/high在map-spatial-eval-review接到d20，已解633冲突再取30d，独占World/Story/Evolution narrow read ports的core keys/bootstrap与65202新review DB。原A0回归Sol不并行用PG；C3b准备树da21d3f05仍待下一批真实装配与busy/reload问题审修。
- Luna C2等待DI闭环，全部新功能和试探安全checkpoint为f6f559f922c946ba7ee7bc4e4c40103d7b0a005c，树干净、明确不可直接集成；DI前79相关测试/26prompt通过不适用于当前import失败状态，当前gate520/517。已结束该子代理释放宿主槽给Sol回归修复。待Sol净修复后由Sol安全移入该WIP再恢复Luna，继续C2验证/审修与尚未开始的Generic旧写/读桥接；修复仍Sol直接写。
- 目标跟踪读取为空后，依用户已有/goal指令建立active tracker，未改三份计划范围、授权或预算；不因工程切片通过标整套完成。封存R3/holdout/原库未动，无新模型请求、push/PR/main合并/部署。


## 2026-10-16T00:10:00+08:00 执行检查点

- primary文档HEAD 73cd5a74c，生产代码仍d20d27517；扩大套9fail/2162pass尚未修后重跑。
  A0 Sol正直接修app/main写入前owner/active门禁及失败终态会话隔离：marked HTTP 4xx可能
  绕过get_db测试注入而尝试默认全局manager连接，已暂停相关广域测试。禁止为核实而访问
  默认开发库；实际是否写入仅从现有证据判定，不能声称未发生。
- C0b Sol已复现并直接修author_safe中secret及作者层指纹/省略计数侧漏，安全投影回归7项通过；
  DI、真实API和隔离PG仍审修中。作者管理使用author_full，角色与默认safe生成必须分开；
  include_patterns/only_adopted的显式开关不能被静默空转。先交C0b净fix，再由Sol移植到
  f6f559f9后恢复Luna C2/Generic新功能，不直接集成该损坏WIP。
- C2b前端已提交a212d9faa（父53aaec35c为C3b），Luna报告248文件/3129测试、lint/build/docs/import
  通过；root看过390 Scene/1280 World mock组件截图，无横向溢出，不算真实app/API验收。
  下一Sol前端批需同时审真实来源装配、作者模式契约和跨scope异步冲突，候选问题见REVIEW-QUEUE。
- 新Luna/max luna_simulation_v3已在map-assistant-structure/codex/simulation-v3-protocol-impl
  从73cd5a74c实施C4a。仅共用协议与状态试验，保留旧run只读、RP observation_v2入口和自身
  max_actors；不碰main/core keys/bootstrap和当前C0/C2共享文件。协议切片不代表C4b/C5完成。
- /goal tracker现为active，无token预算。宿主root+3子代理，当前2 Sol/high修复与1 Luna/max实现。
  没有新增模型请求、评测/holdout读取、push/PR/main合并或部署；R3仍封存。全部剩余授权范围继续。


## 2026-10-16T00:20:00+08:00 主树回归通过与C0b补审

- primary32e63b630为Sol6962d51c1净修复集成；root同一原失败扩大套使用正确3.14.8、
  显式无secret不可达单元DB URL和RuntimeWarning转error，2178 passed/1已知schema warning，
  84.30s；日志/tmp/map-a0b-primary-regression-fixed-20261016.log。未重做当前A0 PG关键路径，
  旧6PG通过不等于新guard路径已重验；待工程PG释放后随UI真实组合复验。
- C0b Sol交付78808780f/582955cd3，61 SQLite、2真实PG、Ruff/import61/517、route ratchet、
  docs有理由门禁通过。root发现limit250先分页再过滤secret会让隐藏条数/排序影响safe覆盖，
  已由同Sol直接补分页前可见范围；因此C0b暂未进primary，不以初版通过冒称最终安全。
- C2b/C3b组合树原提交cherry为a52159a47/91fd0902f，另接A0fix为d03dce096；Sol已复现
  busy/reload、模板重读丢草稿和409二次GET晚响应，直接修复并对齐author_full作者管理请求。
- C4a Luna已锁45项旧协议/HTTP状态试验基线，保留unresolved_outcomes的actor_id旧语义，
  正迁移协议与Story新建入口；RP保留v2。当前没有新真实模型或评测数据访问。


## 2026-10-16T00:42:00+08:00 C0b集成及主树组合验证

- C0b原/审修五笔在primary为5aef92090、04dfbe9b4、3fced27ae、9e44a2391、b9307c4df；
  35937082b的安全reader回归已入20901345a。源PG2项在最终b930由root复验通过0.38s；
  A0 6PG在32e复验通过0.61s。各测试仅专用工程DB，无默认开发库/评测库访问。
- 初次扩大2fail/3014pass交Sol直接修29995771d，集成为4c04bb982：另一个Story run测试
  fixture补session_id；template新增key令操作公开schema变化，明确revision/op_version=2，
  旧v7修订1仍可describe但不能执行，不偷换旧schema。root修后3030pass/3deselect/1既有
  Pydantic warning，70.35s，日志/tmp/map-c0b-primary-regression-fixed-20261016.log。
- C0 Sol解8处组合冲突并保留backend f6全部人物卡/Reaction/optional loader，5b4623987有
  60相邻测试与61/517通过；另由SolUI移299到该树为5217f5310，当前干净，尚待Luna续写。
- 工程PG65202已由C0释放给SolUI，专用copilot_integration_review_test_20261016 head；
  新真实7来源独立Session HTTP1测试通过（含来源失败隔离/read持久化/mute/demo零写入），
  与C0组合及真实浏览器继续，UI尚未入primary。
- C4a必要调用方范围追加SceneRehearsalPanel/useStorySceneWorkspace最小v3接线，默认一轮，
  旧历史只读；Interaction ensemble.py仅显式锁rehearsal_v1以保留team_v1，不改RP策略/上限。
  A1 Luna已快进primary4c后新增纯SPEC，没带待审UI栈，不与Sol共享写。
- 没有新模型调用、R3重试、holdout读取、push、PR、main合并或部署。全部剩余授权工作继续。

## 2026-10-16T00:55:08+08:00 C3b/C2b 真实组合验收与下一批

- Sol修复真实HTTP `world.map_source`读取不存在的content_hash（正确为source_hash）、对象字段中文标签及组件裸globalThis；七来源使用独立PG sessions，局部故障只降级该来源，读处置/静音持久化、跨owner/demo零写入已验证。父组件演示模式经可注入Vue bridge，不将全局访问转移到另一个组件。
- root后端日志 `/tmp/map-c3b-primary-combined-20261016.log`：86 passed/1既有Pydantic warning（18.27s）；PG `/tmp/map-c3b-primary-pg-20261016.log`：3 passed（2.47s），使用copilot_integration_review_test_20261016专用DB，未启动lifespan/模型/worker。前端全套3134 passed（31.28s），ESLint/build/生产资产校验通过。截图 `/tmp/copilot-real-390-20261016.png`、`/tmp/copilot-real-1280-20261016.png`由Sol真实联调生成，root已看图。
- C4a Luna自有4cbc97e35（基线73cd5a74c），90后端及23最终定向、23Vue和build/lint/module/docs通过；尚待Sol独立审修，非C4b或C5交付。Sol在map-clue-review保留旧UI分支另开协议review分支，不碰primary。新Luna dossier_consumers在world-object-dossier-impl/5217f5310恢复Generic读写/类型迁移与C2真实任务链，保留全部C0安全修复。
- 三份计划全部实施的授权和用户“Sol子代理直接修”保持；只本地提交，无push/PR/main合并/部署。未完成实现及真实质量/作者验收继续如实保留。

## 2026-10-16T01:17:50+08:00 C4a审修集成与A1/A2交接

- Luna实现4cbc97e35经Sol两笔净fix接入primary三提交50c0feb54/b4cd55c78/b3182b2c5。修复API/worker/模型后重复核验typed World/地图身份；seed participants须与选定人物完全一致；资源接收者不能伪造现有身份；demo不可读私有排演。未知origin/未知observer/双未知/同地/异地五态：只有本人及明示已知同地者收到公开事件，root补测的未知origin边界由Sol直接修。旧RP v1/v2和state_trial逐条件回归保留。
- root `/tmp/map-c4a-primary-regression-20261016.log`：1034 passed/2 deselected/1既有Pydantic warning（28.70s）；`/tmp/map-c4a-primary-pg-20261016.log`专用simulation_v3_review_test_20261016中1 passed（0.16s）；frontend两文件23 passed（1.58s）、ESLint/build/生产资产校验通过。Sol另有79定向与真实页面选人/候选/确认→API验证，无模型调用，非完整导演验收。
- C2新接口拟为story.reaction.v2：每人物2–4 performances，含动机/来源fact与pattern/动作/表情/肢体/声音台词/内心/注意力/变化。旧Reaction v1保持可读。Generic旧API可选expected_dossier_revision，提供时409保护；缺省旧client仅行锁串行、仍最后写者胜出，不宣称乐观并发；现代Dossier编辑仍须expected_revision。当前Luna尚在自检，不是已审交付。
- 工程PG65202在root本批验证结束后分配Sol A1独占新a1_operations_review_test_20261016；其他review库/原库保留，C2与Goal待排队。默认dev DB/评测65302/R3/holdout不访问，无新付费请求、push/PR/main合并/部署。

## 2026-10-16T01:44:49+08:00 A1组合回归通过与导演实施

- A1 Luna原335349f08经Sol独立审查/实际app注册/HTTP路由/trace接线，主树实现20635fde5、净审修3441ab980。15项新增为v8/89 operations，保留旧冻结目录。Sol修复有原confirmation时知识范围inspect可按资产ID扩读整对象，现失败关闭；精确SourceRange回读仍受原selected/excluded/omitted限制。非平凡HTTP编排已归Assistant而非app组合根。
- root在3441扩大回归1 failed/2122 passed（82.71s），唯一失败为纯路由文件operation_http.py不符合HTTP边界识别；Sol原样重命名operation_api.py为6a31ba327，未改测试、规则或棘轮。root在6a31用正确3.14.8/Pydantic2.14.0、显式不可达unit DB与RuntimeWarning转error重跑2123 passed/1既有Pydantic warning（82.99s），日志/tmp/map-a1-primary-regression-fixed-20261016.log。root专用a1_operations_review_test_20261016真实HTTP/事务/越权/trace复验2 passed（0.46s），日志/tmp/map-a1-primary-pg-20261016.log。本批未改前端，不机械重复全前端。
- Goal专属WIP checkpoint981819ec5由Sol无冲突合primary3441为1d2c2f137，8个自有模型/infra/服务/迁移文件与checkpoint零差异；26focused+61/517通过。Luna再无冲突取已审命名修复为af3b00836，现继续实现。现有Assistant核心写槽给Goal，跨域根预算用显式版本化allowlist，旧v1/v2不全局放宽；两条真实R2恢复适配拟为World Dossier与Project author task，尚未验收。
- 新Luna/max scene_director已在独立map-assistant-structure/codex/scene-director-impl从ea8889f16恢复，完整C4b预算/角色packet/表演/素材/参考/历史/一致性/UI在实施，不能把C4a过渡的一轮409作为最终上限。C2字段与Evidence编译正在另一树写，优先独立director模块；共享infra预算由Goal单写，接线与冲突由Sol处理。
- C2仍未提交审修固定点。只读预审已确认Settings缺object_dossier_enabled_capabilities/character_pattern_enabled_capabilities导致真实env不能启用；generic legacy时点证明只比同对象同值而不比field/dimension，现有origin_place对Story state同值fixture也有问题，交Sol直接修复，不冒称安全时点链已闭合。C0c作者有效期规则/别名区间/动态文字状态仍另排；有向分级态度已存在基础schema，需按实际调用链核验而不重复建模。
- root全部测试进程已结束，工程PG65202释放且保留所有专用DB；原map_enhancement_test仍旧head不改。无默认开发DB/评测65302/R3/holdout访问，无新增模型、push/PR/main合并/部署。

## 2026-10-16T01:50:53+08:00 C2固定点进入独立审修

- Luna固定f6c3790ccb（137定向/Ruff/docs/61/517通过，树干净）包含当前30文件改动；早期f6中的loader/policy/tools等也需审，不能只cherry最后提交。Sol在保留原分支的map-clue-review新建object-dossier-consumer-review从primary d2ebc8f6d合入完整净差，初始3处合并冲突均交Sol直接处理，primary未改。
- root定位真实UI调用方仍只识别旧扁平反应/人物卡，V2 performances及fact_basis/interpretations会被丢失或兜底展示。Sol独占useStorySceneWorkspace及相关card/reaction UI与测试，修复选定一个option到script消费/保存/再读的来源保真；不能将生成输出2–4方案的min2降掉适应单选，也不能把未选方案全视为作者采用。C4另树独立导演组件/入口继续，最终冲突Sol解决。
- Sol本批独占工程PG65202新dossier_consumers_review_test_20261016，其他库保留。Settings两个参考开关与严格字段时点证明仍待直接修复；Assistant turn只有mapping、无实际consumer_action也要实际接线核验。未完成项不以137离线测试替代真实HTTP/PG/UI验收。

## 2026-10-16T02:02:37+08:00 C2 审修、PG 排队与后续批次

- primary业务仍6a31ba327，本次仅任务记录；Sol C2工作树合并点c364deaee的后续修复尚未报固定提交，定向结果是子代理报告，root尚未独立复验。
- Sol确认并直接处理generic同值跨字段证明、不可配置的Settings、V2 UI选项/保存保真及首次prepare错误要求operation_id；需完整目录v9/实际HTTP/确认/worker/PG后才可集成。
- PG65202当前Sol C2独占dossier_consumers_review_test_20261016；下一独占窗口排给Goal的goal_review_test_20261016，尚未发放，其他子代理不得连接。普通测试继续假DATABASE_URL。
- C4b继续使用相同根信封；root只读指出旧unknown确认不能豁免后来新增unknown/incomplete，Luna已确认当前WIP需按新增provider attempt状态实现，待Sol最终独立审查。
- C0c后续交接见 ../T-20261015-character-world-progression/artifacts/C0C-HANDOFF.md；A3/A4交接见 ../T-20261015-agent-operation-surface/artifacts/A3-A4-HANDOFF.md。尚未派发不等于范围移出，真实数周数据与未到势力依赖如实保留。
- 无新模型调用、默认开发库访问、holdout解码、R3重跑或后台任务排空；未推送、未创建PR、未合并main、未部署。

## 2026-10-16T02:14:59+08:00 C2 新 PG 链与 A2 离线恢复检查点

- Sol C2报告专用dossier_consumers_review_test_20261016已升级head；新增真实HTTP旧PUT→档案编辑→旧GET/清空、CAS冲突不改值、两独立PG session同基线1成功1冲突、旧无expected行锁串行last-writer已通过。窄目录HTTP read/两prepare留痕、foreign404、prepare不入队也通过；仍在补Assistant→inline worker同根预算与浏览器V2卡/反应验证，未集成primary。
- Goal Luna离线service已跑通规划/显式审批/R0执行及v3同根预算、SQLite唯一索引；两条真实R2服务apply→manifest→恢复及后续作者编辑CAS保护通过，前端仍在实施。以上为子代理阶段报告，PG与Sol独立审修仍待完成，不视为交付。
- Node验证口径已纠正：唯一primary是map-enhancement-plan，不是原repo checkout；与Goal树package/lock SHA一致，使用/bin/bash login=false的Node24.15.0/npm11.12.1。不得对原checkout依赖做同步或安装。
- 后续C3机制缺口已补交接 ../T-20261015-character-world-progression/artifacts/C3-ALIGNMENT-TAIL.md：短期前瞻人物反应的简报/表演格式、人物弧线计划与实际对照、演化阅读状态提醒、依赖正式下线的Imports替换；不能因C2/首批C3已通过而遗漏。
- PG队列仍Sol独占65202，Goal下一窗口未发放；R3封存/holdout/默认开发库/真模型/外部交付边界不变。
