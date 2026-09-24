---
id: T-20260924-writing-comment-agents
title: 正文批注驱动的 Agent 修订
status: active
created: 2026-09-24T00:38:33+08:00
updated: 2026-09-24T09:29:00+08:00
---

# 正文批注驱动的 Agent 修订

## 恢复快照

- 实际完成：从原工作树 HEAD `aaa5fc94893f791cf1072e3d0a219b9cfb621a2c` 创建独立 worktree 与 `codex/writing-comment-agents`；批注持久化、精确锚点、AI 审稿与局部修订任务、知识与复核门禁、Assistant 独立提案、textarea 高亮镜像和卡片界面已实现。
- 当前里程碑：实现及离线工程验证完成。专用 PostgreSQL 从零迁移、后端 539 项、前端 95 项、桌面/窄屏/任务恢复浏览器 3 项、lint、生产构建、文档门禁均通过。截图复查后补上卡片精确滚动，高亮已在视口可见。
- 下一步：先核对草稿 PR #172 的远端 CI；合并前更新主干基线并处理与同期 PR 的共享文件和迁移。按作者授权进行有成本边界的真实模型质量验证，记录批注、修订与提案的实际输出和失败证据。
- 阻塞：真实模型质量尚无本轮付费验收记录；离线检查不能替代。
- 工作区：`/Users/tywww/.codex/worktrees/writing-comment-agents/ai-writing-assist`；原 checkout 中 `.agent/TASKS.md`、V4 付费账本及 PR merge 任务为其他 WIP，未复制或修改。
- 最后核实：2026-09-24T09:09:00+08:00。

## 目标与验收

- 作者与 AI 批注绑定精确正文范围，常驻高亮；作者启动批量修订，产生可比较的 AI 候选；跨资产只准备待确认提案。
- 关键门禁：项目 owner/novel 隔离、源版本新鲜度、候选知识治理和独立复核、采用确认及原工作稿保护。
- 验收：受影响模块测试、前端 lint/测试、专用库 E2E、文档门禁与 diff 检查；真实模型质量另列。

## 上下文与边界

- 已确认：AI 评论显式一键生成并自动修订阻断/重要问题；轻微问题只展示；手写批注经一次执行合并；保留 textarea 并常驻高亮；正文仅生成本章候选，World/Story 只提案。
- Writing 现有 `semantic_review` 可对人工正文审稿，但 `targeted_revision` 限原 confirmation 的 AI 候选；普通候选采用要求知识审查回执。新路径不能绕开这些门禁。
- 复用项目任务队列、模型连接、Writing 候选和 Assistant 确认批次；不另建通用 Agent 平台。

## 里程碑与进度

- [x] 持久化批注、精确锚点与批量执行领域接口。
- [x] AI 审稿、局部返修、知识治理、独立复核、资产提案的后台链路。
- [x] 正文高亮与批注卡片、任务和候选 UI。
- [x] 受影响测试、文档和离线工程验证。
- [ ] 真实模型输出质量验收（单列，不以离线通过代替）。

## 决策、发现与失败

- 2026-09-24：Plan Mode 已与作者确认交互及权限边界。尚无实现或真实模型调用。
- 2026-09-24：专用测试库 `ai_novel_comment_e2e_test_*` 从零升级当前 Alembic head，批注持久化 E2E 通过后已清理；未使用受保护 Guimi 库。
- 2026-09-24：补测定位并修复 Assistant `submit()` 返回字典的调用误用；提案实际提交测试确认只冻结 World/Story 操作且仍为 pending，不写资产。
- 2026-09-24：模型修订质量尚未进行真实模型验收；离线测试只确认工程协议与门禁。
- 2026-09-24：修复前端任务结果使用 `id` 而服务端返回 `task_id` 造成的重复轮询；浏览器刷新恢复用例通过。
- 2026-09-24：截图发现长正文定位只设置选区未滚动；利用只读高亮镜像精确滚动，桌面和 390px 触摸浏览器断言选区进入视口且截图可见。

- 2026-09-24 09:20 +08:00：为依次合并 PR #171/#172，在本分支预先合入 #171 当前 head；保留编辑交稿与正文批注两套入口，`writing_comments` migration 接在 `20260924_editorial_assistant` 后，补 `writing.comment_revision` 能力绑定。两项 PR 尚未合入 main，后续以最终 main 和 CI 重验。

- 2026-09-24 09:29 +08:00：PR #172 Backend quality 发现四个新增批注路由缺 API 层 active-project 前置守卫；保留领域内二次检查，在路由业务调用前补 `require_active_project`。`test_active_project_route_closure.py` 与批注单测 10 passed，原 CI 失败证据保留。

## 验证证据

- 2026-09-24 01:20–01:33 +08:00：本隔离工作树 `uv run --locked pytest modules/writing/tests modules/assistant/tests modules/evidence/compilation/knowledge/tests infrastructure/tasks/tests -q`：539 passed；后续局部修订的 22 项也通过。
- 新建、迁移、清理任务专用 PostgreSQL `ai_novel_comment_e2e_test_*`：`tests/e2e/test_writing_comments.py -m e2e` 1 passed；全新浏览器专用库分别运行 `writing-comments.spec.js`，桌面、390px 触摸和刷新恢复 3 passed；所有测试库结束后清理。
- 前端 `npm run lint`、Writing/API 相关 Vitest 95 passed、`npm run build` 及生产引用校验通过；后端受影响 Ruff lint 通过。
- `make docs-check BASE_REF=origin/main`、`git diff --check` 通过；真实模型调用、远端 CI 和部署未运行。

## 交付结果

- 已交付：Writing 批注表与 API、批量审稿修订任务、候选治理与采用门禁、独立 Assistant 提案、textarea 高亮与卡片、桌面/窄屏操作、任务恢复、领域文档和自动化回归。
- 未交付：真实模型语义质量验收；无已确认的 World/Story 资产写入。
- 交付边界：本地实现已提交并推送为草稿 PR https://github.com/FengHuoLinShan/ai-writing-assist/pull/172，初始实现提交 `585be279d`；远端 CI 待核对，未合并或部署。原 checkout 的其他 WIP 保留。
