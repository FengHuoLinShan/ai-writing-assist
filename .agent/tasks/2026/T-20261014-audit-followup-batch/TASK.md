---
id: T-20261014-audit-followup-batch
title: 能力审计后续任务批次规划
status: active
created: 2026-10-14T10:16:00+08:00
updated: 2026-10-15T10:40:00+08:00
---

# 能力审计后续任务批次规划

## 恢复快照

- 2026-10-15 上午（用户：“下一批计划如何规划？”→“生产暂时不管，其他按你推荐”）：已核对第二批结果并交付
  [第三批计划](../../../../docs/plans/2026-10-15-audit-followup-wave3.md)，只写计划、未实施、未指派执行者、未提交。
  核实：G6b 完成但未提交（`~/.codex/worktrees/g6b-recalibration`，5 文件改动+1 新测试）；G6c 单次留出已结束，
  `frozen_acceptance_met=true`（修复版过拒答 0/16、语义 31/32，66 次调用 unknown 0），故 Prompt 修复随 R1 合入；
  G7b 无任务记录、未启动。主仓库已移到 `~/项目/ai-writing-assist`，外部树 `.git` 已指向新路径、无 prunable。
  下一步由用户安排执行者：R1（G6b/G6c+rp_matrix 冻结入库）→ A1 G6d → A2 G7b；G8c、HTTP 客户端迁移、R2 可并行。

- 2026-10-15 本轮审查/修复/合并已完成：R1/R2及大项目追加R3由#241固定d065c5460交付，
  Standards/Spec最终无新增发现、18项有效CI全部成功后，经用户授权合入main d2ab2dbf3c78785a24d3f419002fbb13b36bc99c。
  main文件树与已验收头完全一致；原231–238也均MERGED。后端8053/2skip覆盖87.03%、前端3025、PG关键100、
  本地部署324及浏览器/7.51GiB恢复160/160对账通过。详见REVIEW-20261015.md和仓库外证明目录。
  临时服务已清理，大包及浏览器缓存已删除但清单/摘要/源PNG/脚本保留；本任务两托管树已可恢复归档，收尾完成。
  未运行真实模型/真实稿件/生产恢复/部署；未验收32GiB双桶满额及其他浏览器。主任务保持active，不代替后续业务验收。

- 2026-10-15 #241最终d065c5460两路独立审查均无新增发现；最终头远端后端8053/2skip、87.03%覆盖，
  前端3025、PG关键100通过。全部质量/安全/文档已绿，仅两个远端浏览器分片仍运行。
  7.51GiB最终头普通Chromium153复验15/15下载，峰值2036MiB；160对象ZIP成员/摘要/大小与合成清单逐项一致。
  同一对象集的15分包经隔离Linux restore_objects.sh恢复，160/160摘要/大小/类型/DB引用对账成功；
  390px真实样式2001张按条数分两包逐个下载/无横溢也通过。所有自建PG/MinIO容器已自动清理。
  只剩固定头全部CI成功→合并241→核实主干树与原PRs→最终记录/归档本任务两托管工作树。不部署/真实模型。

- 2026-10-15 R3最终补修已推送#241 d065c54607f9ea377c94e5629e12ab58aa4f41f8：逐包下载、列表重试及离开/
  内部页签/刷新/重新生成确认，ZIP Blob异步暂存失败在交付前读回一个字节并整轮失败。全前端3025、lint、文档门禁通过；
  新普通Chromium持久上下文160图7.51GiB已15/15下载，峰值2812MiB；隐私上下文真实暂存失败时零下载、无done。
  最终双轴复核/固定头CI正在运行。容量产物恢复私有runner使用真实copy（最初hardlink被安全门禁正确拒绝，已改），
  隔离Linux PostgreSQL/MinIO逐15包恢复运行中，1/15已过。脚本/日志在archives/.../capacity及/tmp/audit-capacity-restore.log。
  下一步等容量160对象对账、最终审查与有效CI后合并241；随后核实原231–238与241均MERGED、更新记录/保存证明、
  归档仅本任务创建audit-r1-fix/r2-fix两托管树。不得动audit-followup原计划WIP、其他会话工作树或真实服务；不部署。

- 2026-10-15 补齐G4b大项目验收时发现R3/P2：160张合法4096²合成PNG共7.51GiB（地图桶8GiB配额约94%），
  Chromium153可完成15包打包，峰值进程组RSS约2.5GiB，但原自动连点仅发起10/15下载且部分取消；等待45s仍缺5包。
  #241固定1e1f56c0f的18项CI已经全成功，但暂不合并。隔离树正在补修多包逐个下载/重试列表，单包自动下载不变，
  离开/刷新/重新生成保留确认。相关前端63项通过（原回归先红），真实7.51GiB容量复验进行中；
  新固定头提交、双轴审查和CI后再合并。私有合成脚本/证明在archives/.../capacity，不进入仓库，无真实模型/数据。

- 2026-10-15 #241最新固定头1e1f56c0fbd3a48b2efb81f96a53b08ee054d62f整合main258c8ba2a后，修复必要E2E时序：
  第二次截断输出审读现在等待新POST回执，并确认选中record ID及第二章未查，原失败/继续入口断言保持。
  Standards/Spec两名独立复核者无新增发现；独立单用例与完整审读浏览器4/4均通过，实际API/worker/PG、
  合成模型输出。只删除本任务临时PG容器，未触碰ai-novel-db。最新远端质量/安全/文档门禁已过，
  Backend及两浏览器分片仍运行；等待所有有效检查通过再合并#241。原#231–#238已全部合入，未部署。

- 2026-10-15 #241固定56a543409最终CI仅浏览器第一分片失败：assistant-editorial.spec.js:187第二次截断输出
  审读断言“继续未完成部分”按钮缺失；旧失败review相同文案可能使未等待第二次提交的断言误匹配旧记录。
  正在用新建合成PG容器audit-review-browser-pg-20261015（localhost:15487，agent_e2e_audit_review）单用例复现，
  不接触ai-novel-db真实/开发数据，不运行真实模型。依赖链接因另一流程清理原工作树变为悬空，已仅在本任务
  两个隔离树删除坏链接并uv/npm重建。最新main=258c8ba2a，新增仅生产compose/.env.example8行配置；
  其与56a543409的隔离合并树28b6dd48c部署324项通过，其他源码零差异。后续修复这项必要CI问题再提交/复核/合并。

- 2026-10-15 原#231–#238已全部合并。#237最终7d6c6028d的17项有效检查全成功，另一流程先行squash为
  df08377784b8d256b7286604d7d78f6234c6b93c。本补修#241因此再次整合main，四份文档保留已复核版本。
  最新#241固定56a5434094bf5314bd8e55187bae0a4d29e2721a；相对已双轴复核1a7300495的源码差异仅验证脚本
  EOF一空行。同功能前一头1a7300495的完整远端后端8053/2skip，87.03%覆盖；PG关键100passed；本轮仅剩#241固定头CI与合并。

- 2026-10-15 最后基线同步：另一流程另合入范围外#240及#224，main=798b27c46；与#237/#241冲突仅ADR索引
  相邻两行，明确同时保留0029退役与0031 G8b DI事实，未改自身补修代码。
  #237最终7d6c6028d7f870e29405941e4bdeb597ac26a9c5，#241最终1a7300495df399d565166358a9b99672d2b02cb7；
  最新依赖环境父52/联合62通过，两名复核者核对最终头无新增发现。只剩最终固定头CI与两PR合并。

- 2026-10-15 本轮补修已提交追加 PR #241（原 #235/#236 已被并行流程合入），最终审查头
  `1b585551de36341f90fa8324726fbf1c9c7ce283`，已同时整合 #237 最新9c96d1728并解决四份权威文档冲突。
  双轴复核无新发现；组合完整门禁8045/2skip backend+3017frontend+324deploy，最新依赖/G3d联合62passed。
  #233验收已由#239带入，保留main严格超集后零内容差异，以固定60cbf00b1的16成功/1适用skip门禁合入8136105ca。
  下一步等#237/#241固定head所有有效CI通过，再按依赖合并；不得将本轮范围扩大至#240或真实模型/部署。

- 2026-10-15 修复进展：R1 在 Story 共享输入入口拒绝本机标记/第二快照，Context/provider 调用前失败关闭；
  R2 在面板卸载及最后 manifest hash 后重验取消，阻止迟到下载。回归先在旧代码失败，修复后通过。
  R1 完整门禁：8015 backend passed/2 skipped，2986 frontend，323 deployment；R2 全前端 3021 passed。
  Chromium 153/390px 合成图片包真实下载并经隔离 Linux PostgreSQL/MinIO 恢复，10/10 摘要及 DB 引用对账。
  证明保存在 `/Users/tywww/.codex/archives/ai-writing-assist-audit-review-20261015`；无真实模型或真实数据。
  另一会话已合并 #232/#235/#236，并另外合入范围外 #239；主干 8e1be388f。原修复分支未推送，
  下一步在最新 main 合成追加修复 PR，双轴复核后固定 head CI/合并；原 #233/#237 仍须核对合入。

- 2026-10-15 用户授权“修复发现的问题，再合并”：本轮修复 R1/R2，并完成 #231–#238 的门禁与合并；
  不包含新开的 #239、Dependabot 或真实模型/生产发布。核实现状：#238/#231/#234 已由另一会话合入，
  main=9bcd63a6c；#236/#235 已整合该基线但两缺陷仍存在，#237 因父分支变化出现文档冲突。
  为避免与原 worktree 的整合写入冲突，本轮新建隔离修复树，再以非强制推送更新原 PR。
- 2026-10-15 本轮用户要求 review 已执行计划的相关 PR：独立复核 #231–#238，固定版本与证据见
  [REVIEW-20261015.md](REVIEW-20261015.md)。确认 R1/P1（#236 旧本机排演双快照被忽略，改走账户客户端）
  与 R2/P2（#235 离开/最后打包阶段取消仍下载）；本轮只审查，不修复、提交或操作远端。
  直接重跑既有测试共 335 passed/2 skipped，临时用例复现两问题。#233/#237 当时 CI 全绿；
  #231/#234/#236/#238 文档 CI 失败；#232 浏览器失败重跑中；#235 新文档 head bd89a5d55 CI 未完。
  本轮后续：先修 R1/R2，再补依赖文档、真实浏览器验收及固定 head CI。审查期间另一会话在 w2-g3bc
  整合且有 README 冲突，本轮未操作其 WIP/index；恢复前须重新核对状态与 PR head。
- 2026-10-14 深夜（用户：“计划文档已更新，你自行规划并发执行，有必要的话可以超过 3 并发”）：执行权移交本会话（ZCode），
  第二批开工。核实 origin/main 已前移 `fd9e72790`（PR #230 独立模型池/Luna 范围演化/500k 输入预算，恰好改了
  imports 测试、codex_provider、llm_runtime、CONTEXT、development-guide、docs/00、docs/01、Makefile、deploy/*，
  各项行号须重核）；#219 已关闭，开放 PR 为 #229（Actions 组，CI 全绿）/#224（openai 大版本）/#223（8 小版本）。
- 已从 `fd9e72790` 建 8 个 worktree/分支并并发派发 8 个后台执行代理：w2-g3-window（G3②）、w2-g5a（G5a）、
  w2-g6a（G6a）、w2-g7a（G7a）、w2-h1（H1）、w2-h3（H3）、w2-g3bc（G3③b+c 代码部分）、w2-g4b（G4b 代码部分）。
  均只本地提交，不 push/PR/合并。
- 协调决定：H1 集成源为 docs-refresh-luna 集成树（RESULT.md 明确其为权威；docs-refresh-l1..l7 是已停写的领域
  writer 副本，不集成）；H1 排除 backend/modules/imports/README.md（G3② 写入面）与 .agent/tasks 快照（已在
  codex/guided-flow-borrowing 分支提交过）；testing-guide.md 评测段归 G6a、其余归 H1；G3③b+c/G4b 的正式文档
  commit 推迟到 H1 合入后（代理报告已列待同步清单）；G8b/G3③d 将基于 G3bc 分支堆叠执行。
- 测试隔离：各代理用独占 PG 库名（novel_pg_g3win/g6a/g7a/h3/g3bc/g4b）与独占浏览器端口（G5a 18100/18101、
  G3bc 18200/18201、G4b 18300/18301）。
- 2026-10-14 晚续接（用户：“核对 g 系列计划进度，规划或更新下一批计划文档”）：已核对 G1–G8 实际进度，新建
  [第二批计划](../../../../docs/plans/2026-10-14-audit-followup-wave2.md)，并更新主计划状态、过时前提和指向第二批的链接。
- 进度事实：G1 完成；G2 已经 PR #225/#226/#228 合入 main `fdd3ec598`；G3①/G3③a/G4a/G8a 及评审补修已由 #227 合入 main `0e572c75f`；第二波均未开工。
- 第二批依据：4 份只读核查（Explore 子代理，基线 M=`fdd3ec598`、P=`5b5934262`），主会话抽查 v3 包装门禁、评测暂停守卫、
  编辑台开关未进生产 compose、`open_task_snapshot_client` 通用调用方、依赖棘轮 522、主计划“key 不经 API 暴露”、
  writing 依赖边不含 world、`geometry_hash` 排除来源、冲突检查 `summary_json` 只记覆盖度、mask 无读取端点均属实。
- 2026-10-14 晚用户裁定第二批 §5：#227 补修同意提交推送（已推 `d54498792`，**合入未授权**）；G7 新开 v3 run，由 G2 新接入的
  Codex Luna 执行、不设费用上限；G6 被测 Luna 不限次、教师与评分 Sol/xhigh；其余按推荐（G5 三类部分采用 + 编辑台开关透传、
  G4b 三项、#209 关闭、worktree 在 #227 合入后核对清理）；执行者由用户自行安排。#209 已附证据关闭。
- 2026-10-14 晚用户授权合入 #227（合入前核实 base 仍为 `fdd3ec598`、同 head CI 全绿），G7c 暂不做。
- main `0e572c75f` push 工作流六项 success（Backend、Frontend、Production Image、CodeQL、repo-gates、Architecture docs）。
- H4 已完成：用户明确授权清理后，已删除 audit-first-batch、audit-g3-renderer、audit-g3-local-text、audit-g4-object-backup、audit-g8-atlas-invalidation 五个 worktree 及本地分支；远端同名分支已不存在。完整目录、提交 bundle 与差异备份在 `/Users/tywww/.codex/archives/ai-writing-assist-audit-cleanup-20261014`。主工作区 WIP 和其他 worktree 注册核验未变。
- 下一步：泳道 A/B 执行者由用户安排；本会话仅整理提交计划，不实施 G 项、不指派执行者。
- 阻塞：无。G2 的 8 个旧运行时 worktree 属于 T-20261012，继续保留；audit-followup-plan 保留。
- 工作区：计划 worktree `.worktrees/audit-followup`，分支 `codex/audit-followup-plan`（基于 22bb49978，无 upstream）；第二批计划中 M 上才有的文件用固定 SHA 永久链接。
- 最后核实：2026-10-14，fetch/prune 后 `origin/main=0e572c75ffba654cc117c502f91a489307589837`，远端 `codex/audit-*` 分支查询为空；本次只整理本地提交，不推送、合并或部署。

## 目标与验收

- 目标：把审计 A/B/C 批次转换为可立项任务，排除已合入事项，标明依赖、规模、完成标准与授权门。
- 完成条件：计划文档通过文档门禁；每个 G 项有现状证据、完成标准、依赖与授权门；G2 验收要求可直接转交 Codex 线程。
- 非目标：不实施任何 G 项（用户裁定不由本会话执行）；不写 G2 相关 worktree 与 T-20261012 记录；不调用业务模型；不生产发布。

## 上下文与边界

- 来源：[审计 REPORT](../T-20261013-capability-debt-audit/REPORT.md) 第 0.5 / 7 节、[复核](../T-20261013-capability-debt-audit/REVIEW-20261014.md)；
  图解页 `novelcraft-capability-audit.html?v=20261014`。基线证据见计划 §2。
- 硬约束：业务实测只用 Luna/max；新基础设施、数据外发、生产发布须明确授权；migration/provider 归 G2 单一写入；
  DI/ADR-0031/import 预算由 G8a 先写；受版权原文的真实请求/输出留仓库外。
- 协调：T-20261014-codebase-docs-plan（docs-refresh-luna）在刷新正式文档，README 交叠须先约定写入者；
  Luna 规则已随 PR #225/#226 进 main（主工作树本地 b22f7334e 已被取代）；Dependabot #224 现可评估（第二批 H3）。

## 里程碑与进度

- [x] G1 新主干 nightly 签收：run `38500624771`，287 passed，success。
- [x] G2 Codex/Luna 收敛：PR #225/#226/#228 合入 main `fdd3ec598`。
- [x] G3① bundle renderer 退役。（PR #227 合入 main `0e572c75f`）
- [x] G3③a 本机文字入口缩面 + RP 连接误判修复。（PR #227 合入 main `0e572c75f`）
- [x] G4a 服务器侧图片备份、恢复演练、保留期对齐 30 天。（PR #227 合入 main `0e572c75f`）
- [x] G8a 改章 → 地图册来源失效登记。（PR #227 合入 main `0e572c75f`）
- [x] 第二批计划交付（2026-10-14 晚）：`docs/plans/2026-10-14-audit-followup-wave2.md`。
- [x] 第二批 §5 用户裁定已记录（2026-10-14 晚）；H2 #209 已关闭。
- [x] S0：#227 补修 `d54498792` 同 head 18 项 CI 通过，经用户授权合入 main（merge commit `0e572c75f`，保留各切片提交）。
- [x] 第二批 G3② window Phase2 退役（2026-10-14 深夜，ZCode 执行）：分支 `codex/g3-window-phase2-retire` 提交
  `fae161c0b`（8 文件净删 1655 行）。代理因速率限制死在收尾前，门禁由主会话补跑：imports 931 通过、
  prompt-contracts 26、设置页 Vitest 81+14、lint、repo-gates 全绿，棘轮 65/9/522 不变。未推送。
- [x] 第二批 H1 文档刷新集成（2026-10-14 深夜）：分支 `codex/h1-docs-refresh-integration` 提交 `850b1dfe1`
  （31 文件 +512/−106 纯文档；27 修改文档+4 新件，6 处三方冲突按 main 事实优先解决；imports/README、
  testing-guide 评测段、.agent 快照按写入者规则排除）。docs-check 双通道通过；testing-guide 走
  --no-change-reason 豁免，开 PR 时须在模板复填同一理由。未推送。
- [x] 第二批 H3 Dependabot 评估（2026-10-14 深夜，纯评估零提交）：三个 PR 均可合并——#224 openai 3.28 零代码适配
  （llm 483+引用方 251+project 183 全过，legacy httpx escape hatch 实测生效；后续需独立 httpx2 迁移 PR：
  _build_http_client/egress guard/MockTransport 三处）；#223 8 小版本全验证含 PG 迁移 10 例；#229 Actions
  digest-pin 对账一致。合并顺序 #229 → #223 → #224（后两个 uv.lock 冲突，第二个需 rebase）。
  均待用户合并授权。代理误操作一次：alembic 漏带 DATABASE_URL 把共享开发库 ai_novel_engine 前滚到 main head
  （等价 make migrate，无数据变更）。
- [x] 第二批 G6a 评测模型合同迁移（2026-10-14 深夜）：分支 `codex/g6a-eval-model-contract` 提交 `6decad7e1`
  （17 文件 +478/−153）。教师/judge/reviewer/adjudicator/scene-gold 全部 pin gpt-6.1-sol/xhigh，被测端经
  ProjectStructuredExecutor 走 Luna/max；旧模型仅存 FROZEN_LEGACY_EVAL_MODELS 冻结元数据；守卫
  require_live_eval_calibration 保留拒绝（文案改写）；DeepSeek 死分支清理（review --novel-id、
  scene-gold --fallback-model 移除）。evals 234 passed + eval-fast/corpus/technical-coverage/ask-world +
  lint + repo-gates 全绿；docs-check BASE_REF 走 --no-change-reason（Makefile 注释变更，开 PR 需复填理由）。
  既有基线问题：make format 在干净 main 上也报 149 文件（非本次引入）。Ask World 旧 freeze 的
  runner_sha256 失配属预期（G6c 新 family 处置）。G6b 开工范围草稿已在代理报告。未推送。
- [x] 第二批 G7a 导入扫描基线+账本模板（2026-10-14 深夜）：分支 `codex/g7a-import-scan-baseline` 提交
  `35974f98e`（10 文件 +1929，backend/tools/import_scan_baseline/ 含合成生成、采集器、README 指标、
  ledger_template.json；P4-E 承接说明已标注）。核心结论：热点 prepare 的 SQL 数恒为 31 不随规模增长；
  真实长篇规模（60 章）单次 prepare 约 40ms/2.2MiB；C2 建议：当前规模无需优化，实体数逼近 10_000 上限
  （D10000 档实测 DB 0.19s/墙钟 0.62s/66MiB）才立项，G7b 账本记录实体数增长曲线、超约 5000 再议。
  15 单测 + 2 PG e2e + lint/repo-gates/docs-check 双通道全绿。PG 测试放 tests/tools/（conftest 门禁
  与指定库名不匹配的合理偏差）。未推送。
- [x] 第二批 G5a 编辑闭环 harness+E2E（2026-10-14 深夜）：分支 `codex/g5a-editorial-closed-loop` 提交
  `9dc8548ee`（7 文件 +539）。harness 新增审读/改后复核/批注修订/导演四类脚本化回复；4 条真实 API/worker/SQL
  闭环 E2E（首次进入/空态/390px、全链路含 stale 冲突、审读失败终态、停止刷新恢复）全过；assistant 档位 5/5、
  模块 141、全门禁绿。关键发现：失败注入必须用合法 JSON 违反 schema——截断 JSON 会被截断恢复策略补全成 {}
  静默通过（缺口 G2）。G5b 缺口清单 6 项在 docs/acceptance/2026-10-14-editorial-closed-loop-g5a.md
  （G1 采用门禁与文案脱节、G2 截断恢复静默降级、G3 英文内部诊断文案、G4 harness 日志淹没、G5/G6 计划已知）。
  偏差：库名按 harness 门禁用 agent_e2e_g5a_editorial；testing-guide.md 套件边界两处说明（与 G6a 不同段，
  集成时注意三方合并）。未推送。
- [x] 第二批 G4b 作者手动导出图片包（2026-10-15 凌晨，代码部分）：分支 `codex/g4b-image-export-package`
  提交 `4f799048b`（后端清单端点：owner+novel_id、no-store、nosniff、allow_demo_readonly=False、mask 窄读取，
  9 项测试）+ `366d00365`（前端 fflate 流式 store 打包/清单/sha256/进度取消失败/离开保护/512MiB+2000 项
  顺序分包）。验证：world 1257、make test-deploy 324、前端 3018、repo-gates/lint/docs-check 全绿；
  跨语言包格式验收（Node 同逻辑产真实 ZIP → Python unpack/read_manifest/verify 全过，覆盖中文/emoji/同名/
  255B/大小写）与 Linux 容器隔离恢复演练（7/7 对账）均实际执行通过。待同步文档（H1 后）：ADR-0010/0014、
  deploy/README :350、12_infrastructure、README chmod 600、14_frontend+frontend README（BASE_REF 复核项）。未推送。
- [x] 第二批 G5c 编辑台开关透传（2026-10-15 凌晨）：分支 `codex/g5c-editorial-switch-passthrough` 提交
  `7c50e5901`（compose x-runtime-environment 两开关默认 false + .env.production.example 注释条目）。
  validate_env/README 按先例不动（无白名单、非变量清单表）。test-deploy 323、lint、docs-check、diff-check
  全绿。生产开启另需发布授权。未推送。
- [x] 第二批 G3③b+c 文字审批退役（2026-10-15 凌晨）：分支 `codex/g3-local-agent-ui-retire` 提交 `317cbf603`
  （前端 11 文件）+ `24fff7b3a`（后端 31 文件），合计 +261/−504。open_task_snapshot_client 由
  open_project_snapshot_llm_client 接替并补 Key 轮换恢复测试；图片任务路径与历史失败关闭门全部保留；
  棘轮实测重算 65→61 边、522→517 函数级、豁免 8→7、local_agent 入边 5→1（仅 world 图片）。后端 8001、
  PG critical 100、前端 2986、浏览器流（assistant/creative/functional 含图片批准 6 条）全过。待同步文档
  20 项清单在代理报告。偏差：库名按门禁要求调整；forecast/collaboration 历史守卫保留与规格方向一致；
  _DEPENDENCY_EDGES 冻结集超集许可。未推送。G8b（w2-g8b）与 G3③d（w2-g3d）已基于 24fff7b3a 堆叠开工。
- 2026-10-15 凌晨用户指令「已完成的批次 review+修复」：按 code-review skill 双轴模型对已完成项派发
  11 个只读评审代理（G3②/G7a/G6a/G4b/G5a+G5c 双轴、H1 双轴合一、G3bc 双轴；H3 纯评估无 diff 跳过），
  规格轴对照 wave2 计划节，标准轴对照 AGENTS.md+开发/测试指南+Fowler 基线。发现汇总后统一修复并复跑门禁。
- 2026-10-15 评审+修复轮完成：11 份评审全部返回，修复提交 8 笔——G3② `43dd46972`（死统计键+测试）、
  G7a `80847d9f2`（账本补 structure/writing_checks 阶段+测试）、G5a `b3c4cb099`（验收表补文档门禁行）、
  G6a `bd477fcd4`（新合同禁冻结 spark 缓存回放×3+守卫文案+死常量+testing-guide）、G3bc `672947e6b`
  （棘轮冻结集删 story→local_agent+local_agent README 两段）与 `cd3f27391`（assistant README 批准链
  过时段落，评审 A1）、G4b `1d773749c`（P0 导出清单行携带 novel_id+nosniff+刷新清单按钮+only-map/entity
  测试+README 口径）、H1 `b43a00cd7`（计划文件 2 处 .agent 断链改写，评审唯一实质发现）。G3③d 由续作
  完成并提交 `bbae5ef01`（w2-g3d，净删 499 行，repo-gates/docs-check 全过）。G3bc+G3d 合并树预演无冲突，
  棘轮门禁在合并树实测 61/61、517/517。评审裁定的延迟项：G4b 正式文档等 H1 合入后（§4 写作规则）、
  rp_matrix.py DeepSeek 冻结登记为规格盲点待用户裁定、512MiB/2000 项假设与真实浏览器 ZIP 证明随集成
  验收。G5b 完成：9430a937c（含前序 9dc8548ee harness E2E，共 2 提交 15 文件 +339/−29），六缺口全处置
  （G1 文案/停点、G2 summary 必填窄修、G3 失败分流+技术详情次级入口、G4 harness 清理 no-op、
  G5 部分采用仅文档、G6 读者层检查点去重），模块 145、E2E 5/5+9/9、worker 1/1、前端 2990、
  repo-gates/docs-check 全过，双轴评审已派发；G8b 仍在执行。八分支已推送并开草稿 PR：#231 G3②、#232 G7a、#233 G5a、
  #234 G6a、#235 G4b、#236 G3③b+c、#237 G3③d（base=#236 分支）、#238 H1。全部待合并授权。
- 第二批执行者由用户自行安排；本记录只跟踪计划，不跟踪实施。
- [x] 第三批计划交付（2026-10-15 上午）：`docs/plans/2026-10-15-audit-followup-wave3.md`；用户裁定见其 §6。

## 决策、发现与失败

- 2026-10-14：不再立项 A1 修复、A3、A4 及 C2 已合入子项；依据 PR #222 与审计复核。
- 2026-10-14：用户裁定 G4 服务器侧放同机独立目录、B2 后接；本机先做手动导出；保留期全部对齐 30 天（含 DB restic
  的 keep-monthly 6 修正）；地图/正典优先；G2 由 Codex 原线程收敛。
- 2026-10-14：G8 沿用 M4 契约（正典只记基线 + 提示），首片只做建议性登记，不进重算；未另问用户。
- 2026-10-14：B4 拆三簇，window Phase2 与 G2 文件重叠，排在 G2 后；本机文字链路先服务端缩面，因旧 companion 无法撤回。
- 2026-10-14：发现 `InteractionView.vue:204-214` 把图片执行器误判为文字连接，纳入 G3③a。
- 2026-10-14 晚：第二批按依赖分三条泳道：A 不依赖 #227 现在可开；B 等 #227 合入；C 等用户裁定或授权。G3③b+c 合为一个 PR，
  因 API 字段 `local_agent` 前后端须同改；`open_task_snapshot_client` 改指 Project facade。
- 2026-10-14 晚：G7 不能续跑旧 v2 run（`llm_runtime.py:231-243` v3 包装门禁），推荐新 v3 run、旧结果只读，待用户裁定；
  P4-E 并入 G7 单一账本（默认假设）。G6 实际要迁的是 `CodexStructuredExecutor` 路径。
- 2026-10-14 晚：新增计划外收尾 H1（docs-refresh-luna 34 个未提交文件需在 #227 后集成）、H2（#209 结案）、
  H3（Dependabot）、H4（已被取代的 worktree 清理，需确认）。
- 2026-10-14 晚：G4b 重写——现有端点拼不出清单（世界列表分页且排除归档，地图无全量端点、无 key/attempts token，mask 无读取
  端点），须新增 owner + novel_id 只读导出清单端点；G4a 包格式已实现，fflate 流式 store 打包经 scratchpad 实验可被
  `unpack_package` 接受。与主计划 §6.3 第 5 条“key 不经 API 暴露”冲突，连同 mask 去向、部分失败行为列为待裁定。
- 2026-10-14 晚：G8b 重写——基线记全部载入事实，以 revision_id 为主比较（`geometry_hash` 不含来源），比较结果只在
  响应中算（否则漂移 AI 复核指纹）；不复用 G8a port（Protocol 在 evolution）；默认新增 world 批量 head 出口与 DI 键，
  排在 G3③b+c 后。
- 2026-10-14 晚：用户裁定 G6 教师与评分用 Sol/xhigh，与原“教师迁 Luna/max”方向相反；第二批 §3.7 改为两类执行器：教师/
  judge/scene-gold 走 Sol/xhigh 的独立 Codex 执行器，被测生成经 `ProjectStructuredExecutor` 走 Luna/max；
  `testing-guide.md` 教师合同 Sol/high → Sol/xhigh 归 G6a。G6b、G7b 免调用与费用上限，但账本照记。
- 2026-10-14 晚：#227 合入不在“提交并推送”授权内，保持 draft；G7c 未在裁定中提及，按推荐仍须另行确认。
- 2026-10-14 晚 H4 只读核对（#227 合入后）：4 个切片树中 g3-renderer 干净（2 个提交 SHA 不在 main，内容已由 #227 重新集成）；
  g3-local-text、g4-object-backup、g8-atlas-invalidation 的 HEAD 都是 `22bb49978`，未提交内容是 main 上已合入版本的早期副本，
  只在 main 缺的是 g4 子任务笔记约 10 行 CI initializer 回归叙述（修复与测试已在 main）和 g8 早期设计文件
  `evolution/map_consumption.py`（已被 `world/map_source_consumption.py` 取代）；audit-first-batch 只剩本地 CI 收尾笔记。
  远端 `codex/audit-*` 分支已不存在。随后用户明确授权清理，五树及本地分支已删除；恢复副本与保护核验见恢复快照。
- 2026-10-14：用户明确计划不由本会话执行；已删除刚建的 4 个空 worktree/分支（无改动、无提交），未派发任何子代理。
- 2026-10-15 第三批规划：G7b 为主线（审计原则“先收敛→证明长篇质量→定向扩展”）；G6b 只放行 Ask World 教师，
  G7b 的源化字段复核是另一套 rubric，须先做 G6d 校准；G8c 与主线零文件交叉并行；#244 因工具链钉版一致性检查与
  镜像冒烟失败不能直接合并。用户裁定：生产暂时不管；Prompt 修复按 G6c 冻结验收机械决定；G6d 在既有
  Sol/xhigh 授权内；rp_matrix 冻结为历史；旧 worktree 核对后逐项授权删除。
- 2026-10-15 观察（不处理）：G6c 中 3/64 份输出教师判通过、确定性冲突检查因 `uncertainty` 为空判失败，
  留到第四批在新开发集上评估。

## 验证证据

- G1：GitHub Actions run `38500624771`（headSha 22bb49978）`287 passed, 7 deselected in 187.99s`。
- 计划文档：`make docs-check BASE_REF=origin/main` 通过（no architecture-sensitive source changes），`git diff --check` 通过。

## 交付结果

- 2026-10-15 用户授权合并后执行：已合 main 9 笔——#238 H1 文档集成 d4bfc5807、#231 G3②
  4a447374d、#234 G6a 9bcd63a6c、#232 G7a a3c9ef713、#236 G3③b+c 2e54f38f3（含 H1 落地后
  local_agent README 冲突的本地合并解）、#235 G4b 0713ee80d（含补齐的 14_frontend/前端
  README 文档）、#239 G5b 8e1be388f、#229 actions 771bae48f、#223 backend deps f01b4462c。
  过程要点：分支保护要求 up-to-date，兄弟合并致 BEHIND 时按「检查全绿+文件集不相交」
  判定用 --admin 合并；#236→#237 叠层经 retarget+rebase；Architecture docs 门禁的 PR 正文
  勾选通道（edited 事件触发重跑）首次使用成功。进行中：#237 G3③d（rebase 后含快照门
  措辞同步）、#240 G8b（评审修后可合+P1 已修+rebase）、#224 openai 3.28（dependabot
  rebase 走全量 CI，三连中唯一运行时依赖故不用 admin 跳过基线）。
- 2026-10-15 合并收官：#237 df0837778、#240 G8b a5d562b53（评审 P1 已修+rebase 后新开 PR）、
  #224 openai 3.28 798b27c46（dependabot rebase 全量 CI 绿后合）相继 MERGED；补查发现 G5c
  （7c50e5901 编辑开关透传，一直未开 PR）rebase 后开 #242 并合并 258c8ba2a——共 14 笔 MERGED
  （#233 为用户本人所合）。main 最终落点 258c8ba2a 全套工作流（Backend/Frontend/CodeQL/
  Production Image/Architecture docs/repo-gates/Dependabot）success。11 个 w2-* worktree 及
  本地分支全部清理（含无 diff 的 w2-h3）；audit-followup 任务树保留。wave2 除 G6b/G7b 真实
  模型运行（授权已给待启动指令）与 rp_matrix DeepSeek 冻结裁定外全部落地。
- 已交付：计划文档、本记录与开放索引条目（本地提交）。
- 未交付：G6b/G7b 真实模型运行（授权已给，待启动指令）；rp_matrix DeepSeek 冻结裁定。
  （2026-10-15 更新：G6b/G6c 已由执行会话完成待入库；rp_matrix 已裁定冻结；G7b 转入第三批 A2。）
- 2026-10-15 已交付：第三批计划，主计划/第二批状态行与文档索引同步（未提交）。

## 2026-10-14 本地整理提交

用户要求整理提交差异，本计划、第二批计划、任务笔记与导航一并提交到 `codex/audit-followup-plan`；H4 清理事实已同步。文档门禁、差异检查与凭据检查通过；仅本地提交，不实施计划、不推送、合并或部署。
