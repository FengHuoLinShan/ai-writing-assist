---
id: T-20260928-cli-image-scope-editorial-stale
title: 本机 CLI 收窄为图片生成、审稿失效闭环与本机预算中止
status: review
created: 2026-09-28T22:32:00+09:00
updated: 2026-09-29T23:17:00+09:00
---

# 本机 CLI 收窄为图片生成、审稿失效闭环与本机预算中止

## 恢复快照

- 实际完成：三项需求全部实现；2026-09-29 用户授权后按主题拆为 5 个提交（预算中止 e5741c84b、审稿闭环 d4cd9cb05、CLI 收窄底座 491520470、world 生图 d0b894e69、任务记录）推送到 `codex/cli-image-scope-editorial-stale` 并开 PR。
- 拆分验证：工作树最终内容与拆分前逐字节一致（62 修改 + 17 新文件全入库）；C1/C2 中间态补跑预算测试、editorial 7 passed、前端 6 文件 285 passed。
- 当前里程碑：PR 待评审合并。
- 下一步：合并前补一次真实伴随进程 + 真实 CLI 的合成图片端到端冒烟（需用户授权本机 CLI 运行）和浏览器走查。
- 阻塞：无。
- 工作区：主工作树，分支 `codex/cli-image-scope-editorial-stale`（基线 `origin/main@5097ed1a9`）。
- 最后核实：2026-09-29T23:17:00+09:00。

## 目标与验收

- 用户 2026-09-28 要求：
  1. 本机 CLI 暂不开放给现有路径（助手、前瞻、协作、RP 连续性、场景排演等），仅用于生成图片，并由我们自己加一层包装审核。
  2. 审稿任务补全异常处理，作者修改其他信息（使运行中的审稿失效）时先提示并确认；排查全库同类问题。
  3. 修复本机运行时把预算超限当成单个工具失败的问题。
- 完成条件：受影响后端/前端测试与 lint 通过，docs-check 通过，权威文档同步。
- 非目标：合并、部署、Git 历史重写（公开仓库原文问题单列，待用户决定）。

## 上下文与边界

- 来源：本会话对 #170–#177 的审查，已核实问题 1（本机执行器下建议工具失效）、2（审稿 SOURCE_STALE 卡在 running）、3（`local_agent/runtime.py` 吞 `AgentBudgetError`）。
- 相关旧任务：[CLI 适配](../T-20260924-agent-cli-adapters/TASK.md)、[编辑审读](../T-20260924-editorial-assistant/TASK.md)。

## 里程碑与进度

- [x] 本机运行时预算超限中止整次运行（`local_agent/runtime.py`，测试无修复时失败）。
- [x] 本机 CLI 仅用于图片生成：文字路径撤下；生图底座、世界对象图片候选、地图册本机后端与前端入口均已实现。
- [x] 审稿异常路径全部落到终态（含孤儿收敛）；前端失效确认已集成；同类排查无新问题。

## 决策、发现与失败

- 2026-09-28：用户选择生图场景「两者都做」（世界对象图片 + 地图册页面）。
- 本机 CLI 文字路径采用「入口断开、底层保留」：快照构建与助手入口不再选本机；遗留本机快照/运行失败关闭，不静默改走网关；`run_local_agent` 工具中继保留（已修预算中止）以便日后重开。
- 审核包装层设计：服务端拼提示词且作者可改；每根任务单独确认主机权限；图片任务不给产品工具（无 shim/socket）、独立目录、结束即删除；输出经服务端严格复核（PNG/JPEG 魔数、Pillow verify、单帧、尺寸/字节上限、重编码去元数据）；结果只作候选，作者采用后才生效。
- 本机协议原为纯文本（回答≤10 万字符、伴随进程读响应≤2MiB），图片需新增二进制输入/输出端点与 `local_agent_files` 暂存表。
- 审稿孤儿行：编辑审读任务为 `manual_resume`，进程崩溃/租约过期不会进入异常处理；比照助手 `get_run`，在 `view()` 读取时按任务生命周期收敛为 failed/cancelled。
- 同类排查（story/interaction/imports/teams/proactive/map atlas/writing comment）均有 reconciler 或 `schedule_due` 兜底，未发现新问题。
- 前端确认点：编辑约定保存、世界对象/世界书/关系别名/大纲的显式保存与删除、章节发布；自动保存不阻断（阻断会违反草稿不丢失规则），改为本章审读中的就地提示。

## 验证证据

- 2026-09-28：后端受影响 307 passed（local_agent/story/assistant/collaboration/project）；editorial 7 passed；local_agent+cli_agent+evals+base 62 passed；WP1 在临时 PG 库 fresh migration 6 passed（子代理报告）。
- 2026-09-29：前端受影响 77 文件 1092 passed，WP5 子代理全量 2624 passed；`npm run lint` 通过；`make docs-check BASE_REF=origin/main` 通过（WP2/3 前）。
- 2026-09-29 最终：在无本机 `.env` 的临时 worktree（origin/main + 本分支全部改动）跑完整后端 `pytest -n 4`：6390 passed / 15 skipped；前端全量 209 文件 2638 passed，`npm run lint`、`npm run build` 通过；`ruff check .` 通过，新文件格式合规（全库 `ruff format --check` 在 main 上已有 189 个旧文件不合规，本分支 188，非 CI 门禁）；`make docs-check BASE_REF=origin/main`、`make secret-hygiene`、`git diff --check` 通过。WP1、WP2/3 子代理各自在临时 PostgreSQL 库验证 fresh migration 6 passed。
- 本机 `backend/.env` 含 `ASSISTANT_ENABLED=true` 等开关，直接在主工作树跑 `modules/world` 会有 35 个与本分支无关的失败（origin/main 同样失败）；验证须在无 `.env` 的环境中进行。

## 交付结果

- 已交付（分支已提交并开 PR）：问题 3 修复；审稿异常终态+孤儿收敛+前端失效确认；本机 CLI 只用于生图（文字路径失败关闭、审核包装层、世界对象图片候选、地图册本机后端、前端入口与设置页）；ADR-0029 与各模块文档。
- 未交付：真实伴随进程 + 真实 CLI 端到端生图冒烟、浏览器走查、合并/部署；公开仓库原文清理（单列，待用户决定）。
- 交付边界：已提交 `codex/cli-image-scope-editorial-stale`，等待 CI 与评审。
