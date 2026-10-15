---
id: T-20261015-agent-operation-surface
title: 全模块 AI 操作入口、目标运行与操作留痕设计
status: active
created: 2026-10-15T14:30:00+08:00
updated: 2026-10-16T06:44:53+08:00
---

# 全模块 AI 操作入口、目标运行与操作留痕设计

## 恢复快照

设计稿与 ADR（Proposed）已于 2026-10-15 经用户授权本地提交 `87e56f241`，未推送。之后按用户要求核对
33 条外部评审并合并 ADR：原 ADR-0038（助手地图与势力操作）、0039（操作目录与目标运行）、0040（操作留痕）
合并为新 ADR-0038 `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`。用户随后裁定两项默认值
（见“关键决定”），修正与裁定经用户授权在第二个本地提交中提交，未推送。
与地图增强设计（T-20261015-map-enhancement-design）同在工作树 `.worktrees/map-enhancement-plan`、分支
`codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；最后核对时 origin/main 为 `00d861283`）。
2026-10-15 技术评审后按推荐修订 ADR-0038：目录项事务形态、目标运行 `goal` 模式与每项目唯一索引、
高频操作留痕合并或豁免。修订经用户授权在第三个本地提交 `20d6f1eff` 中提交，未推送。
2026-10-15 用户采纳 ADR-0038（Accepted / 未实施）；ADR-0023 补充说明与索引同步。
用户确认的三份计划仍全部实施，任务保持active。primary当前产品固定`3caf1288b9f3e4432fbc1924dc2b272116636506`，已合A4 Sol bb6；此前f5c6为A3合入eab、Sol Goal预算净修复bf78→1afa和三普通回归净修复f1e113e的绿色固定点。目录v12及旧冻结保留；map.edit哈希不变。

root对eab普通扩大回归为8255通过/3失败/7跳过/1 deselected，另30项专库PG为29通过/1 Goal规划失败。Sol直接修复：完整目录压缩首轮表达（9925→6812 token，不提高12000预算或删操作）；旧RP测试补真实Task.meta契约；Writing Worker断言v12；五Collab confirm在首个业务调用前用排他active/owner依赖，消除重复取锁。新增他人及软删项目五路由404的PG断言。两个净fix均已合入。

上一f5c6 root复验：author_operations_primary_test_20261016保留原合成数据，复用无CREATE脚本/tmp/map-a3-root-primary-reuse-pg-20261016.py，head/ORM parity与Goal/Director/C0c/A3的30项PG全部通过（10.57s）；docs-check/repo-gates通过。全modules+tasks/llm基础设施+unit/prompt扩大普通后端已完成：8258通过/7跳过/1 deselected/1既有Pydantic warning，295.54s，RuntimeWarning转error（/tmp/map-a3-primary-combined-fixed-20261016.log）。A3前端源未改，沿用eab的251文件3175项与lint/build证据；当前A3集成固定点工程回归通过。原CREATE脚本已执行，禁止重跑重建专库。旧bd31的5133后端/27PG/3173前端只适用于旧固定点。

A3原Sol审修fb62已合eab：作者Interaction/Collaboration十二项真实SPEC/HTTP、摘要R4精确TaskWorker+offline LLMClient、Collab原子R3采用及独立Session CAS均已验。摘要的新unknown/80%/1800秒策略只匹配冻结author_project_id；旧RP重试/deadline语义保持，worker不硬编码业务type。390/1280浏览器已看图，原始日志记录390设置保存刷新true→false、Escape及无溢出；截图本身是设置修改前。服务已停，专库保留。

A4已按Sol固定`bb6d27a46b9bb94d970dc4f22ce0791b313e7871`无冲突合primary `3caf1288b9f3e4432fbc1924dc2b272116636506`，22文件4630+/149-。Sol直接修exact now-180d、首到期整UTC日无ID快照/旧碎片缺口、report GET只读及读归档并发、批次partial retry确认重复计数、跨日同call执行→恢复关联与多次恢复/重复执行去重分母、JSON/CSV/UI比例与中文标签。没有永久groupID/HMAC。至少数周真实数据与真实Top3仍缺，不能以合成数据冒充。Sol最终源门禁有8913后端/3179前端及最终相关21后端/4Vue文件复验、30PG和追加rate/replay/idle PG；fresh专库迁移/head/parity通过，已停止18588/18589并释放operation_trace_report_review专库使用权、保留数据。

root已看两张390/1280截图，并读/tmp/map-a4-browser-review-final-20261016.log确认真实HTTP偏好PUT/GET、owner A、筛选/键盘/all、CSV无projectID/私有hash、B空隔离/失败反馈，390无溢出。当前3caf root另新建operation_trace_report_primary_test_20261016，fresh upgrade/head/parity与Goal/Director/C0c/A3/原Trace/Report共43PG全通过（11.69s）；docs/repo-gates通过。全后端普通已完成8914通过/9跳过/1 deselected/1既有Pydantic warning，337.54s，RuntimeWarning转error（/tmp/map-a4-primary-backend-all-20261016.log）。前端全套首轮3179通过/1超时、252files/3180tests：既有GenerateView的bounded World Core三轮用例超过5秒（5.436s），不是assert差异；原断言单例重跑通过（1pass/96skip），lint/build通过。后端结束后以maxWorkers=2完整前端复跑通过252文件/3180项（77.73s，/tmp/map-a4-primary-frontend-repeat-20261016.log）；未改代码或放宽超时。当前3caf A4工程整体验证已通过。A4原fresh CREATE脚本/tmp/map-a4-root-primary-run-pg-20261016.py已执行，不能盲重跑重建库。

C5 Luna已固定实现0f2dfa692，随后只cherry已审Sol8ca fixture为`ac4e08a4abce923210372a0adbd24aac779b9557`，树干净并退出。47定向后端、3178前端/lint/build/docs通过；world_progression_impl_test_20261016已创建并升级20261016_wp_cascade。PG persistence为3通过/2失败：直接Step UPDATE/DELETE拒绝、Project删除通过，但项目仍存时删除branch/root级联硬删immutable step。深度-only放行不合格，Luna停止改guard并保留红例。无真实HTTP/worker/provider/browser，不能当C5完成。

新Sol/high sol_review_world_progression已在map-clue-review/codex/world-progression-review从3caf无冲突合ac4为be600ee05，正直接修guard和领域/预算/知识。新专库world_progression_review_test_20261016及18594/18595已分配，待C4新迁移固定后才fresh升级，避免先应用C5再插祖先导致版本假完整；Luna旧库保留不用。该Sol暂不写共享顶层/目录/worker/env/api/story.js或C0 facade。当前另一Sol仍独占author-operations-review做C4候选桥接、顶层组合与api/story.js；新专库director_candidate_review_test_20261016及18596/18597已分配。C4固定后root再移交共享槽给C5 Sol完成真正装配与PG/HTTP/浏览器。

C0模板互通Luna/max已固定b4381119fc032137575f68b72ff69aa4acca9412并退出，树干净，18592/18593已停。候选含八类内核显式借用、五题材v2、CSV/XLSX/JSON预览采用撤销与作者UI，101后端/34Vue/1PG E2E/1浏览器及lint/build/docs通过。专库dossier_template_interchange_impl_test_20261016已创建，head20261016_interaction_summary_task_pointer，无新migration，保留合成项目ee824c87-3905-4dfb-954b-7f85ef1da84d。新Sol/high sol_review_dossier_interchange在map-spatial-eval-review/codex/dossier-template-interchange-review从干净primary10b4合候选，独占World facade/dossier/template/Imports/world.js；root发现新增author PUT/manifest preview/apply尚无纯SPEC/真实路由trace，已要求Sol直接补版本化接口并保持旧冻结，作者手动export不能开放为AI外发。新专库dossier_template_interchange_review_test_20261016与18598/18599分配该Sol，尚未报告创建。共享顶层先C4后C5，该C0 Sol先独立域，不争写权。root独占TASK和共享任务artifacts。

剩余C3前瞻表演格式/人物弧计划实际/演化阅读提醒、A1真实章节重排/一般Story时间线将继续分批Luna实施、Sol直接审修；root又核对C4新引入对象一键转World候选尚缺闭环，已列Sol直接补的尾项，不能用已通过的部分测试替代。C1长篇、M5势力、RP迁移、A4数周数据条件门禁如实保留。C0c/C4已审工程证据保留各handoff；真实地图R3仍诊断封存，holdout不解码，后续采用“模拟作者显式指定Scene地点”评测口径。零新真实模型请求，未push/PR/main合并/部署。



本轮审查更新：C4 Sol首版8PG/真实浏览器已通过，但root发现只从candidate_events转实体不足以覆盖表演/素材中的新人物和地点refs，现由Sol直接补event-free结构化对象转入及R3纯SPEC/真实trace；旧路径证据不当最终。C5 Sol已修角色收到作者累计摘要、地图有效期断档仍参与路线、钩子读取错回执与锁后未复核导致重复采用；52项定向后端通过。实际app导入又发现continuous从tasks导入不存在_task_meta，正在归位修复。root已明确要求第9项独立R4 resume与UI，保持同Root/start/deadline及所有累计计数、当前unknown确认集合和持久半步checkpoint，新unknown再次停点，不能重置或换根。C0 Luna作者专用模板接口与旧AI schema分离，省略借用继承旧值；101后端/34Vue/lint/build及1专库E2E通过，继续CSV/XLSX/JSON与真实UI验证，尚未交Sol。其专库已创建，当前head待最终回报。

下一步：Sol先固定C4候选桥接，再将共享槽移交C5 Sol完成装配与审修，C0 Sol继续模板互通独立审修。之后C3/A1实施继续分批；条件门禁如实保留。

批次验收见[完整范围对账](../T-20261015-character-world-progression/artifacts/FULL-SCOPE-ACCEPTANCE.md)。

## 目标与验收

- 目标：各模块开放或增加 AI 操作入口，让 AI 能自主规划、操作，完成作者的目标；
  操作留痕，便于以后把常用操作代码化。
- 验收：设计稿和 ADR 写明与 ADR-0013、0023、0027、0029、0031、0032 的关系（修订 ADR-0023 的
  写入确认在目标运行内的适用）；`make docs-check BASE_REF=origin/main` 通过。

## 用户要求（2026-10-15）

- 开放或增加各模块的 agent/AI 操作入口，方便 AI 自主规划、操作，以完成用户目标。
- 操作留痕，方便后续版本将用户常用操作代码化实现。
- 评审核对后：可合并的 ADR 合并。

## 已核实现状（main `4efe7f21a`，评审核对时复查）

- 助手业务操作 47 个：world 18（含地图 4）、story 11、writing 9、imports 5、project 3、evidence 1；
  `suggest` 9 个，其余 `confirm`。
- 装配两条路径：story、writing、project、evidence、world 开篇插件为 `OPERATIONS_SPEC`，经
  `app/assistant_operation_registry.py` 物化；world 对象、世界书页、结果、共创、复核、地图和 imports
  仍导出 `OPERATIONS`，在 `app/bootstrap.py` 直接合并。
- 后端路由约 680 个，写路由约 430 个；evolution、interaction、collaboration、account、local_agent
  没有助手操作。`available_operations` 一次返回全部操作的完整 schema。
- 费用只记计费状态（`AIChargeState`），`AgentRunBudget` 记请求、工具、网页、token 和用量是否完整，无金额。
- 没有统一操作留痕，也没有前端埋点；`local_agent` 的产品工具中继已删除（ADR-0029）。

## 关键决定与理由

- 三份草案合并为一份：目录、分级、目标运行、留痕共享同一组字段和测试，地图与势力是第一个实例。
- 界面与 AI 共用一份操作目录；剩余 `OPERATIONS` 插件先收口到注册表，未声明写路由用棘轮清单。
- R0–R4 风险分级；目标运行的计划是数据，执行由确定性引擎推进；重新规划时服务端确定性比较授权范围，
  任何扩大都停下重新审批。
- 费用只记计费状态，预算与预览用请求次数、token 和时限，不估金额。
- 留痕挂在目录层；会话 ID 加数据库单调序号，不用链表；执行事件写在保存点中，失败只标“不完整”；
  不记录内容，自由文本只记长度和加盐 hash；明细 180 天后汇总。
- 外部 Agent（MCP）接入不在本轮范围。
- 用户裁定（2026-10-15 评审后）：目标运行允许作者按目标开启 R2 自动执行，开关默认关闭；
  本机单用户默认记录界面操作，公开账户默认关闭。
- 技术评审（2026-10-15，用户同意按推荐处理）：
  - 事务形态：助手用 `begin_nested()` + `flush()`（`assistant/operations.py:502`），请求结束统一提交
    （`core/database.py:148`）；但 `world/map_atlas_service.py`、`world/entity_fusion.py` 内部多处提交，
    ADR-0013 只覆盖长任务。所以目录项声明单事务或多阶段，多阶段按领域回执对账，结果未知时停下。
  - 目标运行存储：`assistant_runs.mode` 只有 `author`/`background`，活动唯一性按 `session_id`
    （`uq_assistant_session_active`）。新增 `goal` 模式、不绑定会话、停点用 `waiting_approval`、
    按项目的部分唯一索引。
  - 高频写入（`writing/api.py:395` autosave）按会话加时间窗合并或豁免留痕。

## 交付

- `docs/plans/2026-10-15-agent-operation-surface.md`
- `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`
- `docs/adr/README.md`、`docs/README.md` 索引

## 验证

- 2026-10-15（起草）：`make docs-check BASE_REF=origin/main` 通过；`git diff --cached --check` 通过。
- 2026-10-15（评审核对与合并后，未提交）：`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）；
  `git diff --cached --check` 通过；旧文件名残留扫描为零。

- 2026-10-15（写入两项裁定后）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。
- 2026-10-15（技术评审修订后，未提交）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。

## 风险与待决

- 无待用户裁定项。ADR-0038 已采纳；若其他分支先合入同号 ADR，顺延编号并同步引用。

## 2026-10-15T21:56:18+08:00 实施检查点

- runtime目录已实调用register_container_services核实64项唯一操作：assistant1/evidence1/evolution2/imports5/map11/project3/story11/world21/writing9。旧55项只是snapshot初次赋值，后续update不可漏算。A0独占bootstrap/main/registry/service_keys和Assistant既有核心；档案、提醒子代理仅提供新纯SPEC与接线需求。只新migration operation_trace_v2，最终Sol统一链。
- 仅本地提交与隔离验证授权；未push/PR/main合并/部署。无新的真实模型/私有评测根/真实数据库访问授权给这些实现代理。工程检查与真实作者验收分开报告。

- 2026-10-15T22:16:25+08:00：地图R3五Scene完成后结构任务严格目标解析失败，已正常停止封存，真实质量未通过；当前无live runner，新功能首批提交审查后可集成，后续评测需新pipeline身份，不复用旧实验。

## 2026-10-15T22:30:37+08:00 首批交付与独立审修

- A0a f7ba93e8bc5e428a8aef76b6d483ef4236049220已交Sol/high sol_review_operation_catalog（map-advisory-review/codex/operation-catalog-v2-review）；干净归档29定向/Ruff/docs通过。trace与写路由A0b WIP完整保留原Luna树，尚未提交/集成，下一批继续。共享装配还需接C3a/C0新SPEC，不能把A0a当全A0。
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

## 2026-10-15T23:31:00+08:00 三层简报提交与真实 HTTP 追踪审修

- C0b首切片30d5b0698已独立提交，需连同前置633293ee2审查；C3/C0a父提交不重复cherry。新增Evidence三层聚合facade/API、只读Evolution provider与明确省略；角色投影不调演化台账。Luna已在唯一正确3.14.8/Pydantic2.14.0下跑45目标测试、Ruff/diff通过。未集成，也不等于C0/C2完成。
- GenericEntityProfile旧PUT仍直接写data_json/evidence_refs；旧GET/list与WorldBackground仍读旧表；类型转换snapshot/restore和generic→strong迁移仍需bridge。Luna继续C2卡片/Reaction后独立实现事务修订桥接、兼容读投影、未知字段/证据及转换恢复保真。不能把新增只读projection当新旧真相闭环。
- Sol在A0b真实PG/HTTP先失败后修复两个P1：main读取未赋值trace context；当前FastAPI include_router有效route派发绕过source APIRoute wrapper。已直接修并3项PG E2E通过，含成功/最终commit失败回滚/原文不入trace；其它审查仍在进行，未集成。另修任意result/preview id泄露、纯flush操作事务形态误报、新Vocabulary绑定与空间线索单项真实豁免。没有将新增写路由藏入旧baseline。
- C3b统一提醒前端及G8a/editorial纯来源继续实施，共享装配仍由A0/Sol单一写入。A1/A2源码、状态机和验证交接见操作任务artifacts/A1-A2-HANDOFF.md；C4/C5交接仍见对应任务artifacts。所有剩余阶段继续属于本次范围。
- R3和holdout未动；没有新增模型请求、push、PR、main合并或部署。主树本次仍只更新任务记录，不提前纳入未审代码。

- A0b新增进展：Sol在operation_trace_review_test_20261015验证fresh单head升级/ORM parity及4项真实PG E2E（成功/最终commit失败、included route、append-only与181天聚合删除）。180天归档原实现只在aggregate/export读时触发，闲置项目无法保证清理；Sol正在复用现有maintenance调度直接补齐，不引入新服务。当前仍未集成。

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

- A1 Luna报告首批14项World/Story/Writing/Evidence纯SPEC及Evolution授权准备，仍在补实际服务测试和精确接线单；未提交/未接目录，不算已交付。Writing章节重排无现存领域服务，不能直接改chapter_index破坏Story/Evolution来源；保留独立实施项。Story时间线是否已有入口仍待核实，不能以Scene排序替代。
- Assistant现有组合根在C3b集成后primary已稳定；下批A1注册/route binding/新冻结版本统一交Sol单写，不把新增route藏入历史baseline。目标运行A2尚未实施，A3/A4条件与真实数据要求不变。
- 七来源提醒/对象简报本批验证见同轮character-world-progression任务，root86后端+3PG+3134前端及lint/build通过；不把UI留痕通过当作目标引擎已完成。
- 三份计划全部实施的授权和用户“Sol子代理直接修”保持；只本地提交，无push/PR/main合并/部署。未完成实现及真实质量/作者验收继续如实保留。

## 2026-10-16T01:17:50+08:00 C4a审修集成与A1/A2交接

- A1首批为15条（先前root口误14已纠正）：World4、Story3、Writing4、Evidence3、Evolution1；固定335349f08、307测试，接线表A1-FIRST-WAVE-WIRING.md。Sol本批独占registry/bootstrap/config/既有Assistant核心与HTTP适配，完成真实路由/留痕/freeze后再审交，尚未集成。章节重排/一般事实时间线编辑不伪造已有服务，仍列剩余。
- A2 Luna goal_runs 已启动于map-assistant-review/codex/assistant-goal-run-impl（1656353fe干净基线，旧operation-trace-regression-repair/696分支保留）。先独立goal模块/AssistantRun模型迁移/专属router/前端，Sol A1共享核心写锁结束后接线。要求完整根累计预算/30步DAG/审批/唯一索引/幂等/多阶段未知停点/真实R2恢复/CAS/PG/UI，不用helper代完成。
- 工程PG65202在root本批验证结束后分配Sol A1独占新a1_operations_review_test_20261016；其他review库/原库保留，C2与Goal待排队。默认dev DB/评测65302/R3/holdout不访问，无新付费请求、push/PR/main合并/部署。

## 2026-10-16T01:44:49+08:00 A1组合回归通过与导演实施

- A1 Luna原335349f08经Sol独立审查/实际app注册/HTTP路由/trace接线，主树实现20635fde5、净审修3441ab980。15项新增为v8/89 operations，保留旧冻结目录。Sol修复有原confirmation时知识范围inspect可按资产ID扩读整对象，现失败关闭；精确SourceRange回读仍受原selected/excluded/omitted限制。非平凡HTTP编排已归Assistant而非app组合根。
- root在3441扩大回归1 failed/2122 passed（82.71s），唯一失败为纯路由文件operation_http.py不符合HTTP边界识别；Sol原样重命名operation_api.py为6a31ba327，未改测试、规则或棘轮。root在6a31用正确3.14.8/Pydantic2.14.0、显式不可达unit DB与RuntimeWarning转error重跑2123 passed/1既有Pydantic warning（82.99s），日志/tmp/map-a1-primary-regression-fixed-20261016.log。root专用a1_operations_review_test_20261016真实HTTP/事务/越权/trace复验2 passed（0.46s），日志/tmp/map-a1-primary-pg-20261016.log。本批未改前端，不机械重复全前端。
- Goal专属WIP checkpoint981819ec5由Sol无冲突合primary3441为1d2c2f137，8个自有模型/infra/服务/迁移文件与checkpoint零差异；26focused+61/517通过。Luna再无冲突取已审命名修复为af3b00836，现继续实现。现有Assistant核心写槽给Goal，跨域根预算用显式版本化allowlist，旧v1/v2不全局放宽；两条真实R2恢复适配拟为World Dossier与Project author task，尚未验收。
- 新Luna/max scene_director已在独立map-assistant-structure/codex/scene-director-impl从ea8889f16恢复，完整C4b预算/角色packet/表演/素材/参考/历史/一致性/UI在实施，不能把C4a过渡的一轮409作为最终上限。C2字段与Evidence编译正在另一树写，优先独立director模块；共享infra预算由Goal单写，接线与冲突由Sol处理。
- C2仍未提交审修固定点。只读预审已确认Settings缺object_dossier_enabled_capabilities/character_pattern_enabled_capabilities导致真实env不能启用；generic legacy时点证明只比同对象同值而不比field/dimension，现有origin_place对Story state同值fixture也有问题，交Sol直接修复，不冒称安全时点链已闭合。C0c作者有效期规则/别名区间/动态文字状态仍另排；有向分级态度已存在基础schema，需按实际调用链核验而不重复建模。
- root全部测试进程已结束，工程PG65202释放且保留所有专用DB；原map_enhancement_test仍旧head不改。无默认开发DB/评测65302/R3/holdout访问，无新增模型、push/PR/main合并/部署。

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
