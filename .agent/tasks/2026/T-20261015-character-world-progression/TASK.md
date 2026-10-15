---
id: T-20261015-character-world-progression
title: 世界对象档案、场景导演、写作副驾驶与世界推进设计
status: active
created: 2026-10-15T16:00:00+08:00
updated: 2026-10-16T05:44:34+08:00
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
用户确认的三份计划仍全部实施，任务保持active。primary当前产品固定`eab7b3400986b6e98347bde2f9477d02c79e13b1`：已无冲突合入A3 Sol最终`fb62a4c668f757bd239d56fa299c15f1c64bd183`（含Luna da0a035c8与v12冻结a647f1265），此前C0c为9b9c022a5/bd31d959d。目录v12新增作者Interaction/Collaboration十二项，旧冻结与map.edit哈希保持；新合入组合仍在root验证，不能直接沿用上一固定点绿色结论。

root当前eab固定点：前端251文件3175项、lint/build、docs-check与repo-gates通过，依赖棘轮仍61/61、9/9、0/0、517/517。新独占库author_operations_primary_test_20261016已创建并fresh upgrade/head/ORM parity均通过；30项Goal/Director/C0c/A3 PG组合为29通过/1失败，12.45s。失败是test_goal_run_http_postgres.py::test_goal_http_plan_receives_only_executable_catalog在tokens12000时返回planning_stopped而非plan_review；具体根因待Sol复现，不提高预算或删目录改弱断言。日志/tmp/map-a3-primary-pg-20261016.log。Sol已被重新派回author-operations-review直接修；其原author_operations_review专库重新独占，不借root库。root全modules+tasks/llm基础设施+unit/prompt扩大普通后端尚运行（session86064，/tmp/map-a3-primary-combined-20261016.log）。

上一C0c产品bd31固定点仍有5133后端/1 deselected/已知Pydantic warning、27专库PG、3173前端与门禁全绿证据（/tmp/map-c0c-primary-*20261016.log）；只用于该旧固定点，不代替eab当前组合。根脚本/tmp/map-a3-root-primary-run-pg-20261016.py已执行CREATE，后续不得盲重跑或重建专库。

C0c已完成作者有效期与Story覆盖、严格同对象/字段/时点/地图版本身份、三视角脱敏、关系稳定ID、别名有效区间写入重验和导演只读消费；自定义字段与地图事实确认真实R3，GET零事件。Sol先复现并直接修过有效期提前过滤、safe视角私有对照、来源时点/歧义/降级、Notice先截断漏报和循环导入。真实HTTP设置/独立Session CAS/地图确认合计3PG，390/1280键盘保存刷新、跨项目与390的409保稿重试有JSON证据，root已看3图；409图片是重试后保存状态，不冒称冲突画面。Sol树 `map-clue-review/codex/world-object-validity-review` 已干净结束，validity_review专库释放使用权、数据保留，18584/18585已无监听。

A3 Sol独立审修已固定fb62a4c66且原树净，root已合eab。新增十二项真实SPEC/router注册与v12冻结、摘要R4真实入队与TaskFacade幂等、Collab试改/原子R3采用已接通；原ROOT_BUDGET_ADAPTER_UNAVAILABLE临时停点已解除。Sol直接修ProjectContext novel_id、归档consumer恢复、RP管理在助手未开启时不可达；还按root复核把摘要unknown/80%/1800秒限制收窄到冻结author_project_id的新作者任务，并由Interaction注册可调用策略，worker没有业务type/metadata硬编码。旧RP无deadline且原重试保留，真实新/旧Worker对照已验。Sol证据79后端定向、3独立PG（真实HTTP→精确Worker→offline LLMClient成功/前后来源漂移；Collab独立Session CAS与R3采用回读）、3175前端/lint/build/docs/repo-gates、single head/metadata diff0。root已看390/1280两图（设置变更前），原始浏览器日志/tmp/map-a3-browser-acceptance-20261016.log记录390 true→false确认刷新读回、Escape及无溢出/错误；不能将两张图当保存后证明。18586/18587已无监听、专库数据保留。当前A3因root组合PG的Goal停点回归正在Sol追加直接审修，不能标整批验收完成。

A4 Luna/max在operation-trace-report-impl/codex/operation-trace-report-impl已合9b并只取a647中operations.py三行v12补丁。继续统计报表、前向真实edited/restore/undo/用量归属和Goal留痕；本域与ordinary operations.py、goal_runs/service.py归其写。root已在WIP确认now-180d向UTC午夜取整会使原始标识超窗保留不足一天，Luna明确保留为后续Sol直接修复项，不改ADR追认；未合primary、不能声称隐私边界已过。专库operation_trace_report_impl_test_20261016仅分配、创建尚未报告。历史缺覆盖与至少数周真实Top3依赖不造样本。

C5 Luna/max在world-progression-impl/codex/world-progression-impl继续完整实现；checkpoint4c13f5df0合C0c 9b时world/facade.py冲突，已短时全树移交Sol直接解决为9ed9426bef6d7a24ab5648a72af46b6076a34e94，双导入/静态/diff通过、MERGE_HEAD清除、净树后归还Luna；不混入A3。自有新迁移将接C0c实际head，世界推进API/任务/GuidedFlow/Notice顶层尚未装配。Luna拥有architecture-documents.toml的Story prefix窄写权，其余顶层装配仍归Sol；新专库world_progression_impl_test_20261016及18590/18591已分配，未把分配当已创建。C0模板互通树world-object-dossier-impl已在干净新分支codex/dossier-template-interchange-impl/978a14e2d准备，旧分支保留，尚未派代理。

后续仍在范围：C0自定义类型借用内核/五题材档案模板/表格与JSON互通、C3前瞻表演格式/人物弧计划实际对照/演化阅读提醒、A1章节真实重排与一般Story时间线，分别见 artifacts/C0-TEMPLATE-INTERCHANGE-TAIL.md、C3-ALIGNMENT-TAIL.md、A1-A2-HANDOFF.md，待空槽逐批Luna实施、Sol审修。C1长篇、M5势力、RP迁移、A4数周真实留痕为条件门禁，不能用合成测试替代。C4此前Sol8299普通回归与实际TaskWorker同根两轮/8本地provider受控调用/80%零新IO、历史与参考剧本390/1280证据保留，原组合5102已由当前5133范围扩大复验覆盖；此前Writing测试manager泄漏由Sol测试归属修复，生产guard未放宽。R3继续诊断封存，holdout不解码；零新真实模型请求，未push/PR/main合并/部署。

下一步：Sol优先复现并直接修A3组合Goal规划停点；root收齐eab普通后端结果后按净fix重验。A4/C5继续独立实现，空槽后启动已准备的C0模板互通，再C3/A1尾项；外部条件门禁仍保留。

批次验收见[完整范围对账](artifacts/FULL-SCOPE-ACCEPTANCE.md)。

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

## 2026-10-16T02:46:00+08:00 C2 集成与真实 UI 检查点

- primary已集成C2实现cb3e93238、Sol审修1b9afc7b1、同根预算桥fd742097c；集成后干净。v9共92项，旧冻结目录保持；Assistant.turn使用服务器冻结的V4精确子能力，Goal V3仍严格goal根，旧v1/v2不扩权。
- Sol报告571定向/5PG/Vue20及后续377定向/2PG通过；后者为真实TaskWorker→Assistant.execute_suggestion→Story inline worker离线provider成功/认证失败，父子同run/started_at、子无独立预算。root正在固定fd742跑组合回归，日志/tmp/map-c2-primary-combined-20261016.log，尚未判定结果。
- root复用干净map-assistant-operations建立codex/c2-ui-acceptance，固定b85f4373c6。专用c2_browser_test_20261016已迁移，仅合成作者手工V2卡；1280真实界面键盘保存201及GET全content相等。发现V2只展示interpretations引用的fact，未引用fact_basis和无interpretations骨架不可读，已交Sol直接修复；不据API完整回读宣称展示完成。
- root浏览器应用仍运行：backend session67609在127.0.0.1:18572（lifespan off），Vite session17943在18573，同源proxy；临时QA /tmp/map-c2-browser-acceptance-20261016.mjs，backend日志/tmp/map-c2-browser-backend-20261016.log。390初次点击超时已定位正常场景编辑modal使tab inert，QA应等待并通过真实“返回列表”关闭，不强制点击或报产品缺陷。
- PG65202所有权收窄为每库隔离：root独占c2_browser_test_20261016；Sol的dossier_consumers_review_test_20261016本批已释放。Goal专库goal_review_test_20261016尚未创建/分配；其他库、角色和原map_enhancement_test不变，不允许连接默认开发库。后续每代理仅用明确专库，可并行使用独立数据库。
- Goal Luna正完成初版固定提交，真实PG/API/UI与独立审修待交Sol；不等待空闲窗口冒称完成。C4b Luna继续服务/API/UI，新路由缺共享registry接线导致普通app导入仍未通过，固定点由Sol实际登记，不能把confcutdir纯测当应用门禁。根预算unknown新增与旧卡自由文本绕过角色知情均列Sol必审。
- C0c、A3/A4、C3尾项、C4b/C5及地图条件项继续在全范围内；未新增真实模型请求、R3重跑、holdout解码、默认库操作、push/PR/main合并或部署。

## 2026-10-16T02:52:00+08:00 C2 扩大回归与后续派发

- root固定fd742组合套完成：6 failed/4486 passed/1 deselected/1既有Pydantic warning，151.61s；并非通过。Sol直接审修为e3bf61ec8（共创手调测试补真实V4 scope、默认可选loader、Scene截止文案及搬迁后真实确认边界inventory），相关101后端/原6fail通过；root原扩大套待净fix集成后重跑。
- 390实际流程确认“返回列表”会clearSelectedScene导致人物卡/推演/剧本无上下文，先前只把遮挡归为modal的判断不完整。Sol c482b7ed9直接修关闭详情保留Scene/脏稿与焦点保护，并展示全部V2事实/模式依据和空解释；Vue61/ESLint/build过，root真实390/1280仍待复验。两笔净fix尚未集成primary。
- root临时Vite17943/backend67609已停止，18572/18573可供下一固定点重启；c2_browser_test_20261016及合成fixtures保留。不得对其他DB做清理。
- Goal Luna固定90c4d077e0138f93adefd7343439fcc85309b178，map-assistant-review/codex/assistant-goal-run-impl干净；报告379后端/8Vue/lint/build/docs通过。现结束写入交Sol直接完成C2组合、真实PG/API/UI和独立审修；未称A2完成。Sol获新goal_review_test_20261016专库独占创建/迁移授权，其他库不动；root指出approve/cancel持FOR UPDATE再触发独立Session checkpoint可能自锁，待Sol真实PG短timeout实证/直接修。
- 新Luna/max luna_c0c_validity复用干净world-object-dossier-impl新建codex/world-object-validity-impl，从fd742实施C0c全部交接范围；旧object-dossier-evidence-impl分支保留。C4b Luna获Evidence director_reference正式维度独立文件写槽，不能以缺少C2接口延期；shared bootstrap/key/catalog组合仍交Sol。
- root文档inventory及受支持BASE/no-change-reason门通过，12模块/164表/61任务/16前端路由/49ADR；日志/tmp/map-c2-root-checkpoint-docs-20261016.log与docs-impact同前缀。所有真实质量/人工验收、R3/holdout和外部交付边界不变。

## 2026-10-16T03:04:00+08:00 C2 主树组合与浏览器证据

- primary352a45fa5的同一原组合套root复验4492 passed/1 deselected/1既有Pydantic warning（162.12s），RuntimeWarning转error；日志/tmp/map-c2-primary-combined-fixed-20261016.log。全前端248文件3141 passed（32.16s），ESLint及Node24生产构建/资产校验通过；日志/tmp/map-c2-primary-frontend-20261016.log及frontend-lint/frontend-build同前缀。
- 首次PG复验误沿默认marker令7项全部deselected（exit5，不算通过）；补显式-m e2e后2 fail/5 pass，原因测试run_once()领到root浏览器合成专库里更早的2条rag_reannotate_entities。它们只做术语/appearance SQL重算，无embedding/模型，未连接默认或评测库；root没有清理或排空其他pending。Sol893a40a92净修为primary0d3123444，成对指定task_id/novel_id，并证明同项目更早无关pending仍attempt0/meta不变。root原7PG在c2_browser_test_20261016修后7 passed（1.77s），日志/tmp/map-c2-primary-pg-fixed-20261016.log；原2fail日志保留为pg-worker-selection-failure同前缀。仅测试改动未机械重跑4492。
- 真实卡片浏览器：c2-ui-acceptance树c482b7ed9，root专库手工合成作者卡，两宽1280/390均事实骨架完整可见、真实键盘Enter保存201、GET全V2 content一致、无横向溢出/pageerror。结果/tmp/map-c2-browser-result-fixed-20261016.json，截图/tmp/map-c2-card-fixed-{390,1280}-20261016.png，root已逐图看过。
- 反应浏览器仅合成已完成AsyncTask，实际task GET→生产runtime manager→V2 normalizer/界面，非模型或worker生成。1280/390两方案键盘/鼠标保留互斥、完整performance与source IDs持久化、刷新恢复与跨Scene隔离通过，零generation提交；结果/tmp/map-c2-reaction-browser-result-20261016.json，截图/tmp/map-c2-reaction-{390,1280}-20261016.png。root看图发现人物资料迟到时名字可能固化为“本场人物1”，已交Sol复现/直接修，不以其余通过掩盖。
- root Vite58190/backend36063已停止，18572/18573没有本轮运行时；QA脚本/合成专库/fixtures保留。默认开发库/R3/holdout/真实稿件与新增模型请求均未参与本批。
- Goal Sol独立树a948893c3后正在审修，真实PG已复现审批/取消FOR UPDATE与独立checkpoint互等，以及主pool2耗尽；初修专用NullPool锁与provider前独立持久化，小pool1测试2 pass/0.37s。实际C2任务映射与场景+全部人物目标冻结也在修，以上只是阶段证据，不代表A2已集成或完成。

## 2026-10-16T03:18:00+08:00 C2 延迟上下文复验完成

- Sol净修72a78147e已进入primary219a50aaa，仅在同一Scene人物资料加载后按character_id回填V2反应姓名，保留旧协议行为。root两份相关Vue共62 passed（1.90s），日志/tmp/map-c2-primary-late-character-20261016.log；没有因这一窄前端修复重复整套后端测试。
- root固定QA树2c8c11c26，真实Task GET回执先到、story-context人为延迟700ms；1280/390均最终显示“许照”，完整表演互斥选择、source IDs、本地恢复与跨Scene隔离通过，零生成POST/真实模型调用。结果/tmp/map-c2-reaction-browser-late-name-result-20261016.json，截图/tmp/map-c2-reaction-late-name-{390,1280}-20261016.png，两图已逐一目视确认。backend44977/Vite26033均已停止；合成专库/fixture保留。
- Goal仍由Sol在独立树审修；新复现规划目录暴露14个执行不可用项，正在用同一能力判定贯穿规划、确认和恢复，并公开完整嵌套参数schema。C0c和C4b继续Luna初版实现，未把初步测试当完整交付。


## 2026-10-16T03:30:00+08:00 C4b 固定点转独立 Sol 审修

- Luna候选1628717107a158b09f8f683c7223fbc65906e9ae已提交且源树clean；报告Story22通过、Evidence/Writing741通过及1项未修改的旧runtime_version6/源码7断言失败，前端105/lint/build、Ruff/修改文件format/compile/docs/diff通过。均是候选阶段证据，不能覆盖未挂app的新HTTP。
- 新Sol/high sol_review_scene_director复用已核干净map-assistant-vocab-review，从primary a14a119e6创建独立codex/scene-director-review，负责无损组合C2+导演、直接修复冲突/发现、完整真实注册与专用PG/API/390/1280验证。独占新director_review_test_20261016（65202），不访问其他DB；原分支及symlink保留，primary不共写。
- Goal Sol仍在独立map-clue-review；过滤14项不可执行操作后发现78项完整schema约105k JSON字符，可能超默认12k预算。按正式计划§3“按需发现，不一次全给”改为轻量发现与选中精确schema；选择与规划累计同一根账本，不静默加额或截断。相关132后端/7Vue/6PG只是前一阶段报告，最终预算/恢复/UI尚未完成。
- C0c Luna继续exact来源/有效期/别名/自定义文字状态；关系、地图只有相同身份与字段、confirmed来源和Scene截止可证时才覆盖读取，否则明确gap，不以同值/人物位置推断。本批未添加模型请求，R3/holdout仍封存。
