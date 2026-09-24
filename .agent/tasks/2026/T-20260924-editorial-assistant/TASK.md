---
id: T-20260924-editorial-assistant
title: 作者助手编辑员级审读与意见闭环
status: active
created: 2026-09-24T00:48:00+08:00
updated: 2026-09-24T09:33:00+08:00
---

# 作者助手编辑员级审读与意见闭环

## 恢复快照

- 实际完成：隔离主题分支；Project 版本化编辑约定、Writing 完成标记、Assistant 持久审稿/证据/作者处置/定向复核/停止续跑和 Watch 主动队列；Vue 编辑台及写作入口。原创冻结样本与评分量表、权威文档均已落盘。专用 PostgreSQL fresh migration、真实 worker/CAS、合成演示源复制边界、真实浏览器桌面和 390px 流程均已通过。
- 当前里程碑：最终 `make test-ci TEST_WORKERS=2` 通过（部署 270、后端 6276 passed / 15 skipped、前端 2587、覆盖率 85.97%）。Prompt/doc/diff 门禁、PG worker/CAS 与演示副本隔离均通过。本机工程实现及合成内测链已完成。
- 下一步：先核对草稿 PR #171 的远端 CI；合并前更新主干基线并处理与同期 PR 的共享文件和迁移。作者明确本轮费用上限和目标测试连接后，再做零费用预检、核对共享账本及真实模型内容评测。
- 阻塞：真实模型内容评测缺少本轮费用上限与目标连接授权，不能启动付费调用；线上发布同样需单独授权。工程实现与合成验证不受阻。
- 工作区：`/Users/tywww/.codex/worktrees/editorial-assistant/ai-writing-assist`，`codex/editorial-assistant`，基线 `origin/main@9b9175be3b3ccb0fbef32cdcf86dbf9c78268040`。原工作树 `codex/v4-phase3-wip` 有用户 WIP，未复制或改动。
- 最后核实：2026-09-24T09:09:00+08:00。

## 目标与验收

- 用户明确要求实施上一轮已确定的全量计划：作者项目优先，只给编辑意见，章节/卷/全书结构、场景、行文和文字审读；作者确认的长期意图；交编辑标记；证据化意见书、处置、改后复核和克制后台跟进；本机及演示项目内测。
- 工程验收：API/ORM/迁移/领域调用/前端闭环、来源与 owner/novel_id 边界、任务恢复和预算、PostgreSQL/浏览器与项目门禁。
- 内容验收：冻结原创样本与真实模型输出单列；本轮由 Codex 单人 AI 评阅，不能冒充独立人工或专业编辑认证。
- 非目标：自动改写、采用或发布正文/设定；RP 编辑；未经授权付费调用、提交、推送、合并或部署。

## 上下文与边界

- 现有 `assistant.teams.deep_review` 仅以单章 draft 为入口，`blind_reader` 单次最多八章；Writing 语义审查有 selection/volume/book 且最多 24 分片，并写 AI candidate 的审稿 provenance。编辑意见不能冒充正式采用资格。
- Project 持有项目设置；Writing 持有正文版本；Assistant 持有任务、意见与提醒；Evidence 持有资料精确回读。复用现有 Project LLM gateway、PostgreSQL task queue 和前端 Vue bridge。
- 现有自动检查默认关闭、同项目后台槽和每日额度；新主动编辑还需要明确项目授权。公共只读演示源不能发起付费分析，线上部署单列。

## 里程碑与进度

- [x] 核对基线、隔离工作树、`make docs-check`。
- [x] 编辑约定与交编辑标记，本地 API 测试覆盖版本冲突、哈希冲突和幂等。
- [x] 单章只读审读、证据、意见书、作者处置和定向复核；本机 PG worker 通过。
- [x] 卷/全书分段阅读、层级汇总、覆盖/遗漏、长章预算后续跑；合成测试通过。
- [x] 后台授权、完成标记与结构变化 Watch 触发、共享槽/额度/安静通知；项目设置 CAS 与撤销检查通过。
- [x] 前端桌面/390px 浏览器闭环、合成原创样本、权威文档与专用库演示副本边界。
- [x] 最终变更后的完整工程门禁。
- [ ] 真实模型内容质量评阅（付费部分待另行授权）。

## 决策、发现与失败

- 2026-09-24：用户选择作者项目、只给意见、章节完成触发、独立于正式发布的完成标记、长期意图需作者确认、章节至全书、本机/演示项目先内测、由 Codex 评阅。见当前会话批准的计划；任务记录不增加授权。
- 当前原工作树有其他 WIP；本任务基于核实的 `origin/main` 隔离实施。
- 2026-09-24：单章 worker 测试发现来源变化前置 guard 的异常没有进入失败状态回写；已把 guard 纳入异常处理，并在 DB 回滚前保存任务身份。测试现在覆盖新来源失效与不写正文。
- 2026-09-24：全新专用 `ai_novel_editorial_test` PostgreSQL 数据库迁移到新 head 通过。全库 `alembic check` 仍报告多项现存 ORM/migration 漂移（Evolution/Story 等），不把它当作本次迁移失败或门禁绿色；需窄核对新表与字段。
- 2026-09-24：`make docs-check BASE_REF=origin/main` 已通过（11 模块、136 表、53 task handlers）。
- 2026-09-24：浏览器检查发现“编辑约定已保存”提示随约定详情自动收起而隐藏；已移至详情外。主动授权读取还发现严格 schema 不能解析带内部授权元数据的 Watch 记录；已收窄投影并补测试。
- 2026-09-24：首次 `test-ci` 11 项新增失败来自 Writing 旧 mock 缺新字段和项目路由守卫清单；均已修复，第二轮全绿。未删除有效断言。
- 2026-09-24：审读 finding 改为在来源最终重验后随报告发布；最终发布先获取 Writing 章节版本锁，再锁 Watch/review，避免旧版本被推送及与正文写入倒序死锁。作者意图引用必须逐字命中冻结约定；缺优先级理由/方向的高意见降级并展示未核对。

- 2026-09-24 09:33 +08:00：PR #171 浏览器门禁将 `editorial.spec.js` 误放进默认关闭编辑功能的 functional 宿主，按钮不可见；独立 editorial 配置此前已有且本机通过。现从通用套件排除该用例并在同一 CI job 增加专用 editorial 步骤，保留所有功能断言；新建专用 PG 测试库本机重跑浏览器 1 passed 后清理。

## 验证证据

- `make docs-check`：通过，11 business modules / 134 ORM tables / 51 task handlers / 16 frontend routes / 36 ADR（基线，2026-09-24）。
- 新实现：`pytest modules/assistant/tests/test_editorial.py -q` 5 passed；Writing/路由守卫/编辑定向回归 113 passed；原创样本哈希测试通过；前端 `npm run lint`、`npm run build`、`npm run test -- --run` 通过（203 文件、2587 测试）；Prompt 契约 24 passed。
- 专用 PostgreSQL `alembic upgrade head` 到 `20260924_editorial_assistant` 通过，临时全新库 migration 回归 5 passed；PG 编辑 worker + 并发作者决定 CAS 1 passed，合成演示源复制与意见隔离 1 passed；浏览器真实后端桌面/390px 1 passed。全库 `alembic check` 报其他模块既有 ORM/migration 漂移，须单列。
- 最终 `make test-ci TEST_WORKERS=2` 通过：部署契约 270、后端 6276 passed / 15 skipped、前端 2587 passed，覆盖率 85.97%。最终 `make docs-check BASE_REF=origin/main`、`make prompt-contracts`（24 contracts）、`git diff --check` 均通过；PG worker/CAS 与演示副本隔离 2 passed。

## 交付结果

- 已交付：本地实现已提交并推送为草稿 PR #171；工程/合成内测链、专用 PG 迁移与演示副本边界已验证。
- 未交付：付费真实模型输出及单人 AI 内容质量评阅、独立人工精确率、线上发布。
- 交付边界：草稿 PR https://github.com/FengHuoLinShan/ai-writing-assist/pull/171，初始实现提交 `e2473157a`；远端 CI 待核对，未合并或部署。
