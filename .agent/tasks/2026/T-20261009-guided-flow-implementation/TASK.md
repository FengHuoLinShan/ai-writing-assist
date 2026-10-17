---
id: T-20261009-guided-flow-implementation
title: 成果导向创作流程借鉴计划实施（BR-0 至 BR-7）
status: active
created: 2026-10-09T13:30:00+09:00
updated: 2026-10-12T23:36:26+08:00
---

# 成果导向创作流程借鉴计划实施（BR-0 至 BR-7）

## 当前恢复快照（2026-10-12 整理核实）

- 工程交付：BR-0/1/2/7 经 PR #212–#218 集成；BR-3/4/5/6、tails、九项 P1/P2 整改与 Issue 修复通过 [PR #220](https://github.com/FengHuoLinShan/ai-writing-assist/pull/220) 已合入 main，合并提交 `2dce04f42a7d7eb41eaf0c025033c1eb4a051e50`，当前 main 可达。
- 旧“等待 BR 分支/尚未推送/尚未合 main”均已过期。当前没有未交付的引导业务补丁；报告与记录已在 main，旧树的重复副本已清理。
- 作者验收按用户明确要求跳过，`human_validated=false`；真实模型对照、质量/费用验收未执行，保留 active，不能把跳过当作通过。
- 后续主笔记迁回当前主树；P4 树只保留版本化历史。下一步：在已明确目标、资料范围和费用授权后执行剩余模型验收；本次不启动模型或部署。

- 唯一后续主笔记：主工作树本路径 `/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261009-guided-flow-implementation/TASK.md`；旧工作树副本只读。
- 最后核实：2026-10-12T23:36:26+08:00。以下各节保留原验收、失败和授权的历史证据，不代表当前交付状态。

## 历史记录

## 当前交付续接（2026-10-12 PR合并授权）

- 用户明确要求跳过作者验收，通过PR合入main；本次在P4整理树提交上述工程整改与Issue修复，原集成树任务/WIP不动。
- 主交付记录改为本整理树的P4 [TASK](../T-20261009-world-evolution-phase4-impl/TASK.md)，本记录保留BR复审与验证来源。
- 作者验收按用户指令跳过，human_validated=false；未执行真实模型质量验收或部署，不把跳过写成通过。
- 以下为合并前历史检查点，远端CI与最终合并身份以P4 TASK及GitHub为准。

## 历史恢复快照（2026-10-12 九项整改工程完成）

- 当前用户授权：当前集成分支修复旧审查7项P1/2项P2、验证/复审/更新记录，保留原WIP、不合main。无真实模型/真实数据、推送或部署授权。
- 本地修复提交 `af731b0392e8df2012741d14d8d9d3f942f570e5`，基线 ebd3bac3732c16641e96ce4690014779acf60a98；分支 codex/guided-flow-integration，worktree `/Users/tywww/.codex/worktrees/guided-flow-integration/ai-writing-assist`。生产、测试和权威文档已提交；本TASK与新旧报告留未提交。旧REVIEW/VALIDATION完整保留。
- 实际结果：原S1/S2/F1–F7全部关闭，Standards与Spec独立只读复审绑定最终提交通过。跨窗原资产保护、规范化数据库并发锁、付费输出checkpoint复用/未落盘失败关闭、完整输入身份、子集采用指纹、多证据/重叠确认、骨架卡内CAS取舍与撤销恢复、三层顺序确认采用、编辑台active恢复已闭合。
- 验证：test-ci后端7675 passed/2 skipped/13 warnings、覆盖86.72%，前端2964 passed；部署272 passed；PGcritical91 passed（新增竞争6）；最终受影响617 passed；桌面与390×844各6 passed；lint/build/docs/repo门禁通过。文档impact保留逐项不变理由，import ratchet524/524。
- 原工作树保留：57修改/未跟踪文件hash、HEAD、暂存diff及status完全相同。执行前与复核摘要在/tmp，任务独占PG18432已停止；不动5432共享集群。
- 证据：[整改复审](REVIEW-REMEDIATION-20261012.md)、[整改验证](VALIDATION-REMEDIATION-20261012.md)；此前报告保留历史结论。费用未知且结果未落盘的任务停止自动重试，需要核对费用；不宣称能恢复未保存输出。
- 未完成：真实模型质量/作者接受度与BR-3/4/5/6真实产品验收。总任务保持active；工程整改完成不代替这些门禁。未推送/PR/远端CI/main/部署。
- 可执行下一步：在本worktree查看 `git show af731b0392e8df2012741d14d8d9d3f942f570e5` 与整改报告；按用户下一次授权确定真实模型评测或作者验收范围、合成/真实资料与费用上限。任何main合入另等明确授权，不自行扩大数据或付费范围。
- 最后核实：2026-10-12T14:38:39+08:00。

## 上轮恢复快照（2026-10-12 集成验证；历史）

- 本轮授权：整合 borrow-tails 与当前集成分支、同步最新主干、完成 BR-3/4/5/6 验证与审查，更新记录；保留原工作树全部 WIP，暂不合入 main。本轮未运行真实模型/真实数据、未推送或发布。
- 主记录：本隔离工作树的 TASK.md；原工作树已有未提交内容完整保留于下方历史。原工作树 57 个修改/未跟踪文件的 SHA256、HEAD、暂存 diff 与状态均和执行前一致；原 codex/guided-flow-borrowing 仍为 636d790120d66ed41010e22f9c527c3942dd5918。
- 工作区：`/Users/tywww/.codex/worktrees/guided-flow-integration/ai-writing-assist`，分支 `codex/guided-flow-integration`；最终提交 `ebd3bac3732c16641e96ce4690014779acf60a98`。本轮记录文件留为未提交，不自动提交任务笔记。
- 主干基线：`5a2958660f65b663555a68d445e19c3d0c8ff1c9`，结束前再次核实远端 main 未变。BR-0a/b/c、BR-1a/b、BR-2、BR-7 已经 PR #212–#218 合入主干。
- 整合：3e679b844 合入 tails 的 5 个提交；a24af0fc4 同步 origin/main。唯一 tails 冲突为控制器注释/空行，保留 reactive/confirmAsync 修复与新的作者选择/规划能力；WritingView 未恢复无效 confirmDialog 接线。已验证 tails、原集成头与最新主干均是最终提交祖先。
- 修复：1ffd64678 补窗口末章/覆盖已写章校验、条目更新基线、复核排队状态、知识策略/能力注册和套件接线；50aff8ddc 修复真实 HTTP 重复路由前缀、取消 stop=None 与 skipped 诚实状态；ebd3bac37 复用选章辅助函数覆盖窄屏测试入口。
- 验证完成：[验证记录](VALIDATION-20261012.md)。全量 test-ci 后端 7661、前端 2953、部署 272，通过；覆盖率 86.69%。后续生产小修后 Assistant 132、EditorialDesk 8；PostgreSQL critical 85；最终桌面/390×844 各 6 个浏览器用例通过；lint/build、repo-gates、文档 inventory/差异影响及 diff-check 通过。版本边界、替身覆盖和文档无改动确认理由均已记录，未把浏览器替身当作真实领域验收。
- 审查完成但未通过：[双轴审查](REVIEW-20261012.md)，生产代码头 50aff8ddc。Standards 2 项 P1；Spec 5 项 P1、2 项 P2，共 9 个未解决项。修过的窗口 K、缺失基线、排队提前完成、真实 HTTP 路由等不再列为未解决。
- 包状态：BR-3 实现已集成，但并发唯一性/恢复仍未验收；BR-4 多证据与重叠确认、审读台刷新恢复未完成；BR-5 方向卡付费恢复及逐条编辑/冲突取舍/撤销 UI 未完成；BR-6 跨窗保护、输入身份、子集采用、近期 Scene 阶段未完成。全部保持待验收，原任务 status=active。
- 环境：Docker daemon 不可用；使用任务专属原生 PostgreSQL 17+pgvector 集群 `/tmp/codex-guided-flow-20261012-pg`（18432）完成合成数据验证，收尾已停止，保留目录/日志。未使用真实项目库。
- 下一步：首先修复 REVIEW 中 F1 跨窗已有资产写入保护与 S1 活动 run 并发唯一性，以跨窗采用回归和 PostgreSQL 双连接竞争测试验收；随后完成付费恢复、作者取舍/恢复及 Scene 入口。不要先运行真实模型或合入 main。
- 交付边界：整合与小修仅本地已提交；本轮任务/审查/验证记录已落盘但未提交。无远端 CI 运行、无 PR、无 main 合入、无部署。真实模型质量和作者验收未执行，不宣称 BR-3/4/5/6 完成。

## 历史实施记录（2026-10-09，过期待办由上方快照替代）


- 目标：实施 `docs/plans/2026-10-09-guided-flow-borrowing.md` §5 全部实施包（BR-0a/0b/0c、BR-1a/1b、BR-2、
  BR-3（含 ADR-0032）、BR-4、BR-5、BR-6、BR-7），§6 五项裁定已授权。
- 集成分支：`codex/guided-flow-borrowing`（基线 `f35c2bb0f`/`origin/main`，计划文档已提交于 7b30d9b44）。
- 工作方式：每包独立 worktree `.worktrees/br<id>` + 分支 `codex/borrow-br<id>`，完成后顺序合入集成分支；
  主工作树不做包内实现。
- 进度：
  - Wave 1（并行）完成：BR-0a（dd487a7bc）、BR-0b（47997fcfd，含两处真实缺陷修复：finalize 前崩溃重排
    重复调用付费模型→已付费输出冻结复用；采用幂等键）、BR-0c（68b3bee8f）、BR-1a（69185192f，
    GET /api/tasks + 前端服务端优先恢复 + 双上下文 E2E）。
  - Wave 1 集合完成：BR-1a 合并落 3eddf68e3（冲突 docs/modules/14_frontend.md 与
    writingCommandController.test.js 均双保留；合并结果上后端 tasks/writing/knowledge 278 过、
    前端 workflowProgress/控制器/todayIsland 96 过）。集合分支现含全部 4 包。
  - BR-2 完成：13b4cbaa3 合入集合分支（无冲突）。knowledge_review 投影补
    policy_version/output_hash/维度作者标签；语义审查回执带 check_version+output_hash；
    采用记录 adopted_with_open_issues；生成任务 result 带 knowledge_review_status；
    前端四态分流（生成完成≠可采用、候选面板门禁+遗漏维度、结果详情、发布确认部分完成提示）。
    验证：后端 writing+knowledge+tasks 531 过、前端 114 过、E2E"资料复核未完成不可采用"
    2 过（nc_e2e_br2 专用库，临时库已删）、docs-check 过、ruff/eslint 过。
  - BR-1b 完成：016aab480 合入集合分支（无冲突）。workspace-summary 加性 creation_progress
    （writing adapter 合并 BR-1a 任务概要与最近候选/已采用，V4 六维+停点+动作词表）；
    evidence 只读缝 get_confirmation_staleness（批量确认失效信号）；生成 finalize 把
    source_fingerprint 写进候选 provenance；Today 首页"进行中的创作"由投影驱动
    （TodayView 四态视觉、stale 提示重新确认；WritingHomeView/TodayView 补 prop；
    todayIsland 暴露 creationProgress）。验证：集合分支后端 960 过（project+writing+
    evidence compilation+tasks）、前端 119 过、docs-check 过、ruff/eslint 过。
  - BR-3 先行决策已落：ADR-0032（`docs/adr/0032-guided-flow-orchestration.md`，已登记
    索引，docs-check 过）以 f8edb4375 合入集合分支。运行层实现与流程 2 v1 未开始。
  - 2026-10-09 用户指令"并行执行完整计划"：五包并行派发（各包独立 worktree/分支，
    基线 f8edb4375，完成后由主会话顺序合入集合分支做集成验证）：
    - BR-3 全包（运行层+流程2 v1+写作页流程宿主）→ `.worktrees/br3` / `codex/borrow-br3`
    - BR-7 全包（用量按作品成果归因+设置页）→ `.worktrees/br7` / `codex/borrow-br7`
    - BR-4 独立部分（审读意见→批注修订桥接，不含挂流程）→ `.worktrees/br4` / `codex/borrow-br4`
    - BR-6 Story 侧（窗口参数+章号硬校验+操作签名+确定性 operation_id，不含 assistant
      流程步骤/触发/补窗）→ `.worktrees/br6` / `codex/borrow-br6`
    - BR-5 World 侧（骨架 suggest 操作+条目级取舍+回滚，不含方向卡/流程定义/首页流程卡）
      → `.worktrees/br5` / `codex/borrow-br5`
  - 集成进度（主会话，顺序合入 + 逐次验证）：
    - BR-7 已合入（6fdb34935）。归因实为五桶（adopted/pending/not_adopted/failed/other，
      未确认费用按 BR-0a 语义逐桶单列）；归因数据源用确认记录 result_status，未新增
      writing 依赖。
    - 依赖棘轮修复已落（集成提交）：BR-1b+BR-7 新增的两条函数内 evidence facade 导入
      按 AO-5 口径改 DI 键 `evidence.confirmation_reads`（新
      modules/evidence/confirmation_reads_port.py + service_keys + bootstrap 注册），
      function_level_imports 回落 525/525。注意：AO 后续清理不可回退此端口契约。
    - BR-4 已合入（3297f2a9b，无冲突）。修订选区取意见首条依据；成功条目自动记
      "准备处理"处置（复用 decide_issue→_append_decision）；采用后复核经
      `assistant.editorial.post_adoption_rechecks` DI 键自动触发、失败降级不阻塞采用。
      E2E 已在集成分支跑通（2 passed）：代理 spec 未真机跑过，集成时修五处——编辑台
      功能开关套件归属（playwright.editorial.config.js testMatch 放宽
      editorial*.spec.js）、真实入口（选章→交给编辑）、reviews 过滤链路模拟、mock
      候选草稿响应、复核折叠与瞬态排队断言（310a38bbf）；临时库用后即删。
    - BR-6 已合入（f421618ec → 合并 022e97544，无冲突）。窗口参数进确认与提示词、
      章号/条数硬校验（越窗丢弃并说明）、覆盖窗口走修订、operation_id 加入 mode 与
      修订目标 id（同窗口同层仍幂等）、evidence contracts 增 record-only
      planning_window_end；偏离裁定：修订模式不丢弃作者显式选中的已有资产、Scene 层
      窗口默认 1 上限 2、硬校验只作用于 rolling_window 请求。story+evidence+registry
      939 过、棘轮过、docs-check 过。
  - 并行事故记录：BR-5 代理一度在 .worktrees/br6（错误 worktree）未提交工作，与
    BR-6 的 stash 交错险些丢工作；已通知其用 patch 迁回 br5（禁用 git stash，
    stash 列表是仓库级共享的，多 worktree 并行时互相可见且易误操作）。
    教训：多代理并行时每个代理的提示词必须强调"只在你自己的绝对路径 worktree 内
    执行所有 git 命令"，且禁用跨 worktree 语义的命令。
    - 集成验证累计：writing+assistant 422 过、project+evidence compilation 488 过、
      story+evidence+registry 939 过、前端组件 33 过、棘轮 525/525 过、editorial
      E2E 2 过。
  - BR-5 已合入（3b5cac0e8）。world 骨架生成/条目取舍/回滚
    （assistant_opening_tools.py、api/opening_skeleton.py、services/worldbuilding/
    opening_skeleton.py、tests 960 行）。
  - BR-3 已合入（55d28fbe8/12afee213）。集成修两处真实缺陷：控制器 state 必须用
    reactive()（普通对象让宿主永不渲染）；结束流程确认链路——根因是控制器默认
    confirmDialog 用原生 globalThis.confirm 且 WritingView 接线传了不存在的
    vm.confirmDialog（useWritingWorkspace return 未导出），真实用户也只看到原生弹窗。
    修法：控制器默认改走 shared/confirmAsync（外壳 modal，与全站一致），
    删除 WritingView 假接线；单元测试 8 过。E2E 修复四处：active 探测 mock 回传
    当前视图（服务端契约，刷新后 URL query 会丢、写作页按设计回落探测）、候选草稿
    以真实第 1 章草稿为底覆盖候选态、候选面板断言对齐真实文案
    （"这份建议还没有改动工作稿"）、capabilities mock 强制 200。
    验证：guided-flow E2E 2 passed（nc_e2e_br3fix）。修复落 636d79012（pathspec
    提交恰好 5 路径；主工作树暂存区里第三方的 architecture-documents.toml 保持
    staged 未被扫入——期间本会话 Bash spawn ENOENT 宿主故障，由 tails 代理代跑
    E2E 与提交，只读 git status 确认现场后精确下达命令）。
    tails 代理已对齐契约：其新增代码一律 confirmAsync + reactive state，合并以
    集成分支为准。
  - 主工作树杂物（勿提交勿覆盖）：docs/README.md 与 docs/architecture/*（feature-map
    功能描述图一组）是第三方并行编辑（时间戳早于代理派发），不属于任何包；合并/提交
    一律显式路径暂存，避开这些文件。
  - 当前：等待 BR-3（br3）、BR-5（br5）、BR-6（br6）三个代理完成。
    BR-3 = Assistant 内 guided_flow 运行层 + ADR-0032 + 流程 2 v1（首页"继续第 N 章"
    到可审阅候选两次决定）。要点：步骤表服务端注册带版本、模型不可改；步骤类型仅
    自动执行（复用 suggest uuid5 幂等）/作者确认（复用批次指纹重验）/作者选择；进度由
    领域产物存在性与新鲜度推导，不存当前步索引；复用 AssistantRun 存储，新增运行类型；
    开关 ASSISTANT_GUIDED_FLOWS_ENABLED 默认关；单会话单活动 run 约束
    （assistant/models.py:65）与流程并行冲突需实现时裁定；依赖方向只用已冻结边
    （Assistant 不能直依赖 World）。operation_id 由流程运行与步骤确定。
  - 后续：BR-3 → BR-4 与 BR-6 并行 → BR-5、BR-7。每包完成后顺序合入集合并跑受影响
    测试（后端 make test TESTS=.../前端 vitest+eslint/涉及文档 make docs-check）。
  - 环境注意：各 worktree 无 backend/.venv（用主工作树 venv 跑 pytest）与
    frontend-console/node_modules（cp -Rc 克隆主树）；E2E 配方见记忆
    playwright-e2e-local-runbook（专用库 nc_e2e_*、BACKEND_PORT=18000、FRONTEND_PORT=18080、
    PW_REUSE_EXISTING_SERVER=0、剥代理 env）。
- 验证口径：每包按计划的验收与测试清单；收尾 `make docs-check BASE_REF=origin/main` 与受影响模块测试。
- 风险：行号基于 f35c2bb0f，实施前已在各包内重核；BR-0b 只在测试暴露真实缺陷时才改实现。
