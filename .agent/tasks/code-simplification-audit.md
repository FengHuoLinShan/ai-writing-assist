# 全库代码简化审查（Code Simplification Audit）— 2026-09-10

> 2026-09-11 计划更新：后续全量审查遵循 [全代码库优化审查计划](full-codebase-optimization-review-plan.md)。用户本轮仅要求写计划，功能保持兼容，允许提出内部架构调整；新增全量审查与实施均未启动。下文保留历史候选及当时判断，不作为执行授权；尤其 Wave 0 清理命令、零引用结论和收益估计必须重新取证。当前工作区已有他人/其他任务 WIP，本轮未修改实现。
>
> 2026-09-11 全量审查完成：上段"未启动"状态已终结。全库 2453 文件已按新计划审毕，本文约 70 项候选逐条复核（多项重大纠偏，如 `deep_import_phase01`/`deepseek_scene_probe` 判误报不得删除、A3-5 规模 24→64 处、A1-1"恒 403"不成立）。结论与批次见 [full-codebase-review/review-report.md](full-codebase-review/review-report.md) 与 [full-codebase-review/batch-plan.md](full-codebase-review/batch-plan.md)；本文历史段落仅作线索留存，执行以新账本为准。优化实施仍未授权。

多 Agent 并行只读审查：10 个区域/跨模块单元（A1–A9、X1）+ 1 个 Reviewer（Wave 2）。
基线：codex/agent-integration 工作树（只读）；原始候选 ~106 条，合并去重后约 70 项；Reviewer 对 5 个关键 S/A 项读码重验全部证实。本文是执行阶段的工作底稿。

## 总体判断

复杂度形态不是"过度抽象"（后缀型抽象类仅 16 个且几乎全部有增值；TODO/FIXME 全库为 0），而是四类：
1. 扁平巨石 service（77–95 方法/文件）
2. 双轨/镜像状态（同一事实多套词汇，imports 达 7 路）
3. 复制漂移 helper 与纯转发/死导出
4. git 历史包袱与交付面冗余

预计删除量：Phase1 约 700 行死代码 + git 卫生；Phase2 约 1400 行重复合并；Phase3–5 另计。

⚠️ 安全附带发现：`tools/deepseek_scene_probe/config.local.json` 本地含真实 DeepSeek API key（未入库、已被 gitignore 覆盖），建议立即轮换该 key。

## Wave 0 零风险清理（在新分支 codex/repo-hygiene 执行，勿混入当前脏工作树）

```bash
git rm -r --cached backend/backend/.test-logs && rm -rf backend/backend/.test-logs   # 实测 tracked 11 文件 100KB
git rm -r --cached .superpowers .opencode .playwright-mcp && rm -rf .superpowers .opencode .playwright-mcp
git rm -r --cached .claude && rm -rf .claude                  # 若仍用 Claude Code 本地流可仅删 settings/lock
git rm backend/scripts/deep_import_phase01_real_llm_check.py  # 零引用
git rm -r tools/deepseek_scene_probe && rm -rf tools/deepseek_scene_probe  # 24 文件零外部引用；先轮换 key
rm -rf tools/world_evolution_preview                          # 仅剩 pyc 空壳（未 track）
rm -f backend/data/dedup_training/dedup_features.jsonl        # 10MB 孤立数据零引用（未 track）
rm -rf frontend-console/docs                                  # 5 文件全 untracked 零引用
rm -f backend/nul backend/test.db                             # 本地垃圾（未 track）
# .gitignore 追加 .superpowers/ .opencode/ .playwright-mcp/ 防复发
```

## Phase 1 死代码/legacy 删除（小 diff、独立可回滚）

| 项 | 位置 | 内容 | 验证 |
|---|---|---|---|
| A8-1 S | shared/bulkSelection.js:60-178 | vanilla 渲染器+DOM 同步 ~120 行，生产零调用（Vue 用模板绑定） | vitest+build |
| A6-1 S | workflow_entity_phase.py / workflow_structure_phase.py | 4 个旧签名 shim ~140 行，唯一调用方 test_workflow.py:348-379 | imports 测试迁移 |
| A7-1+A8-4 B | compilation/api.py:660-684 + apiContracts.js:339 + api.js:2036-2038 | legacy GET 死路由 + 死契约 + 死包装 + 12 个已定义未切契约中的死项 | e2e + 契约测试 |
| A2-1 S | agent_step_harness.py:446-503 | OutputGuard 死修复层（生产唯一构造点 :831 无 repairer）~40 行 | harness 测试 |
| X1-S3 B | world/facade 5 + story/facade 3 + evidence/facade 8 + project/facade 1 + core/dependencies 2 | ~19 个零引用死导出/死类（CurrentProject 骨架、get_db re-export）；**必须逐符号以 `from modules.X...` 限定路径 grep 重验**（裸符号名跨模块同名） | facade public-surface 测试 |
| A5-5 A | writing/services.py:2478-2615 | generate_candidate 同步路径 ~140 行，生产零调用（API/助手/任务全走 task 版）；先迁 8 处测试 | writing 测试 |
| A5-4 A | writing conflict_ai 同步端点（:119-282、:689-810；api.py:145-161、:271-287 已 deprecated） | 同步/任务双轨，同步版防护更弱、前端零调用 ~250 行；删除=收紧 | conflict 测试 |
| A1-2 S | infrastructure/tasks/api.py:66-137 | 35 项手工黑名单删除（generic_submit_schema 生产注册面为零，端点恒 403；端点整体去留 NV） | tasks api 测试 |
| A9 组 | 见 Wave 0 命令 | git 卫生 | git status |

## Phase 2 重复合并

S 级链：
- **A2-4+A5-2 snapshot LLM client 链**：llm_runtime 双入口尾部 30 行逐字重复先抽 helper（注意 profile_source 字符串分歧统一为有意语义）→ 暴露公开 snapshot contextmanager → 6 处私有 `_open_task_llm_client` 改调（writing/services.py:2081、semantic_review.py:325、conflict_ai.py:88、story/tasks.py:444、outline_state/ai_workflow_service.py:166、story_outline_generation.py:550）~110 行。CURRENT: 调用方→私有 CM→open_project_llm_client；PROPOSED: 调用方→llm_runtime 公开 CM。
- **A5-3+A1-7 checkpoint/snapshot 链**："commit→in_transaction 断言→expire_all" 9 处收敛到 infrastructure/tasks/facade.py 单 helper；4 份 _require_llm_execution_snapshot 变体收敛到 project facade 单 helper（严格/rebuild 差异参数化）~120 行。与上一条同文件簇（六文件伴生）→ 捆绑同 PR、保持两个独立 helper。
- **A3-1**：PlotThread/OutlineArc 两 repo 收敛到 StructurePlanRepository（钩子覆写式：PlotThread.update 含领域分支需 override 扩展点，非纯 4 行声明）~300 行。
- **A5-1**：story/api.py 两个 enqueue 函数 95% 相同 → 合并+extra_meta ~55 行。
- **A2-2**：imports 15 个旋钮函数 → 声明式表+删 _workflow_constant 动态反查 220→40 行。
- **A4-2**：world/schemas.py 34 处 uuid coercion validator → Annotated 别名 ~180 行。
- **A8-2**：scene 三处手写 workflow manager → createWorkflowManager 工厂扩展（cancel/dismiss/ownerSceneId/receiptStorage 参数），净删 ~250 行。

A 级：A3-2（reveal/foreshadowing 45 行重复）、A3-5（24 处手写 novel_id 列→NovelMixin ~140 行）、A5-6（prepare/finalize 冻结序列 helper ~60 行，重验语义保留）、A5-7（interaction summary 合并+harness 化）、A5-8（API 改调 submit_review）、A5-10（stable_hash 16 份→infrastructure 单实现 ~90 行）、A6-3/4（imports 9 个转发 classmethod 删 ~90 行 + full/stage 双入口折叠 ~150-200 行）、A6-5/6/7（env helper 收编、preflight 合并、fence 探测单 helper）、A1-4（enqueue 包装内联 ~45 行）、A1-5（4 handler 样板+删测试专用 else 分支）、A8-6（bulkSelection store 合并 ~50 行）、A4-3（前端 isVersionActive helper 8 处）、A4-5（compatibility_status 收窄）、A2-7+A9-5（wheel 剔除 test 文件与 evals）。
B 级：A1-1 部分（心跳循环共享）、A1-6（publish 重试局部 helper）、A1-8 二小项、A2-6（health legacy 壳内联）、A7-3（指纹同文件先合并，跨文件集中须逐字保留编码参数）、A8-7（stateSlices 并回）、A5-11（双 facade 名合一）。

## Phase 3 状态收敛

- **X1-6 S**：任务/运行状态词汇收敛到 shared/enums TaskStatus（CENTRALIZE EXISTING）：infrastructure/tasks 裸字符串改枚举、imports phase 翻译段、assistant completed 对外值不变内部收敛。连锁缩减 A6-8（imports 7 路状态）与 workflow_runs reconcile 维护负担。
- A1-3：imports get_active_organization 改读队列权威源（或读前 reconcile），run.status 降为 fencing 内部状态（NV：方案待产品确认）。
- A3-3：业务枚举 Literal→StrEnum 值域普查后分批替换（独立于 X1-6，勿三合一）。
- A4-4 B 渐进：world 资产双词汇不做大迁移；前端 raw status 判断渐进归入 worldAssetDisplay；禁新模块自建映射。

## Phase 4 转发层/契约面压缩

- X1-7/A4-1：全局 DomainError handler 统一——world 10 处确认冗余先删；余 15 处逐点区分"转译 vs 独立校验"（NV）。
- X1-3+A7-4：evidence/facade __all__ 收窄到真实外部消费面 51 符号；不回迁 25 处内部直连（扩大 diff 无收益）。
- A8-4：api.js 契约迁移收尾（切 12 个已定义契约 + ~19 无契约端点；3 处 multipart/blob 保留手写；坑：timeout 默认 15s vs 契约 600s）。
- A8-5/X1-9：views/ 2 文件迁 vue/views/writing 后删目录（含 tests/api-contract.test.js productionJsFiles 目录表）。
- A5-13 最小交集：interaction/proactive.py:236 改走 run_managed_structured。

## Phase 5 架构级（需授权/前置查证）

- A8-3：smartDedup split-brain 迁移（app.js DOM 桥接 → composable+组件；smartDedup.js 1238 行领域逻辑保留）。
- X1-8：_uses_domain_workflow_run 双轨消亡（需确认生产 flag 状态）。
- A3-6/A9-12：alembic squash（前提：squash 基点=生产已部署 revision；common.sh:573 校验存在性）。
- A2-3：deep import 接入 WorkflowBudget（机制已存在纯接线；是否有意排除预算 NV）。
- A4-8 NV：world_generation_center 两条结构化包装疑似共享骨架。

## 不建议简化（安全边界/设计意图）

novel_id 隔离与鉴权/CSRF/输入校验；evidence confirmation 三段重验（安全不变量，A5-2 证实公共 helper 单一实现无复制）；文件格式/大小校验；provider/key 校验与限流脱敏；infrastructure/tasks/facade.py 转发（AGENTS.md 制度性 seam）；agent_runtime（ADR-0023）；vue/bridge 测试 seam；evidence/models.py star（metadata 注册 seam）；evals 与 Makefile eval-*（CI 活跃调用）；deploy/ 生产体系；docs/superpowers+archive+audit（ADR 活跃互链，删除会断链）；NOTES/DECISIONS/workflows/prototypes（注册在案）；CrudService 软删探测（现状正确，扩大采用时复核）。

## 剔除项（Reviewer 裁定）

A5-12（latch 近似或有语义分化）、A8-9（~15 行微）、A6-9（微）、A2-5（低收益 NV）、A5-14（转功能 backlog）、A8-10/11、A2-8、A7-6/7/8/9、X1-10/12（各单元 NO 维持）。

## 每阶段验证门

模块限定 grep 零引用复查 → 受影响模块 pytest + 前端 vitest/build → 任务提交/LLM/world API 回归（P2 起）→ `make docs-check`（契约/行为变化时）→ API 对外值不变断言（P3）→ facade 守卫测试扩展（P4）。测试迁移不得删断言。小 diff、不混无关修改、独立回滚。


## 2026-09-11 首批执行：批量选择旧 DOM 清理

- 授权范围：仅移除无生产调用的批量选择渲染器及 DOM 同步，保留状态与执行逻辑、历史资料、当前 imports API/测试和 styles.css 的用户改动。
- 工作区：主仓库，`codex/bulk-selection-cleanup`；建分支前及合并前 fetch 后核实基线与 origin/main 相同。用户已授权提交本批并快进合入本地 main；不推送或部署。原有三个未提交文件不纳入本批提交。
- 已完成：删除三个旧 HTML 渲染函数、DOM 同步及专用转义 helper；有效断言迁移至现有 world Vue 测试，更新失效代码注释。
- 证据：旧符号仅剩历史设计文档引用；55 个相关测试文件、836 个测试通过；前端 lint、生产构建与资源校验通过；编辑前 docs-check 通过。
- 当前状态：首批完成；完整 Vitest 183 文件 / 2480 测试通过。其余审查候选未执行。
- 收尾文档门禁：make docs-check BASE_REF=origin/main 要求架构影响说明；核对所列四份文档后，以检查器 --no-change-reason 记录旧 DOM 删除及原有路由顺序/CSS 改动不改变架构描述的理由，通过同一检查器。git diff --check 通过。
- 下一步：如继续简化，先复核下一候选的当前调用与兼容契约；本批无需后续实现。
