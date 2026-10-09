---
id: T-20261009-guided-flow-implementation
title: 成果导向创作流程借鉴计划实施（BR-0 至 BR-7）
status: in_progress
created: 2026-10-09T13:30:00+09:00
updated: 2026-10-09T13:30:00+09:00
---

# 成果导向创作流程借鉴计划实施（BR-0 至 BR-7）

## 恢复快照

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
    删除 WritingView 假接线；单元测试 8 过。E2E 修复中：active 探测 mock 需回传
    当前视图（服务端契约）、候选草稿需 mock（以真实第 1 章草稿为底覆盖候选态）、
    候选面板断言对齐真实文案（"这份建议还没有改动工作稿"）。
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
