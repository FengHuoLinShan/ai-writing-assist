---
id: T-20260924-agent-cli-adapters
title: Agent 底座接入五种本机 CLI
status: active
created: 2026-09-24T00:24:52+08:00
updated: 2026-09-27T04:19:00+09:00
---

# Agent 底座接入五种本机 CLI

## 恢复快照

- 隔离工作树：`/Users/tywww/.codex/worktrees/agent-cli-adapters/ai-writing-assist`，分支 `codex/agent-cli-adapters`，基线 `eeccc4e26bd56294b13666b2111b61874e925c42`。原 V4 工作树 WIP 未触碰；本分支已提交并推送为草稿 PR https://github.com/FengHuoLinShan/ai-writing-assist/pull/173，初始实现提交 `dec4af7fd`，未合并或部署。
- 已实现五种 CLI 子进程适配、离线结构化评测入口、项目配对与出站伴随进程、逐根任务主机权限确认、租约/产品工具/回执协议；Assistant、已登录 RP、前瞻、创作协作、连续性检查及 Story 场景排演的人物意图 Agent 接入项目选择。匿名 RP 和普通非 Agent LLM 流程保持原连接。场景排演的环境裁决与剧本仍用项目账户连接。
- 本机任务统一 `never_retry`，中断保留已见回执，显式新任务重试。项目/owner、Evidence、确认、CAS、预算和租约校验保留；本机 CLI 工作目录不是主机权限沙箱。
- 下一步：等待 #172 合并提交 `1b65113ab` 的 main CI 与本分支更新后的 #173 CI 全绿，按固定 head 合并 #173，再核对最终 main CI。DSH 原生工具次数及完整跨网络产品验收单列。
- 最后核实：2026-09-27T04:19:00+09:00。

## 目标与验收边界

- 五 CLI 独立服务本机产品 Agent 与离线评测；Mac 伴随进程按作品配对，项目默认原 gateway，每个根任务单独确认完整本地文件/命令权限；离线等待、租约失效失败关闭、显式新运行重试。
- 逻辑关键路径和失败路径经定向测试；五个真实 CLI 用合成资料试跑，测试绿色不能代替真实作品或产品质量验收。
- 2026-09-24 后作者已明确要求提 PR 并合并 #171/#172/#173；部署与清理用户数据不在本次授权内。

- 2026-09-24 09:35 +08:00：为依次合并 PR #171/#172/#173，本分支已合入前两项当前 head，解决 16 处共享冲突，统一 Alembic 为 `editorial_assistant -> writing_comments -> local_agent_cli` 单 head。前瞻保留共享订阅 store 并接回本机 CLI 逐次授权；新增定向前端回归。合并后文档、Prompt、密钥、Ruff、前端 lint/build 均通过；后端 395 passed / 2 deselected，前端 203 passed；新建专用 PG 库从零迁移及 5 项 E2E 通过并已清理。远端 CI 与正式合并仍待核对。

- 2026-09-24 09:45 +08:00：PR #173 Backend quality 的 6298 项已通过，仅 `test_every_module_test_directory_is_a_package` 因新 `local_agent/tests` 缺 `__init__.py` 失败；已补空包文件，本机 test harness 与 local_agent 24 passed，待远端复验。
- 2026-09-27：合入 #172 浏览器 CI 修复 head。PR #173 浏览器 CI 额外失败源于 AI 设置页外层与本机 CLI 内层复用同一个 `ai-capabilities-tab` 类，使设置流程定位器命中两项；内层移除重复类，保留布局类。此前 #172 的三个失败已在 #172 分支定向重验 3 passed。
- 2026-09-27：#172 已按全绿 head 合并为主干 `1b65113ab`；本分支合入该主干，无内容冲突。当前 #173 的前端、后端、镜像、文档 CI 已通过，因更新基线会重跑固定 head 检查。最终主干 CI 仍待核对。

## 验证

- 后端定向回归：508 passed、2 deselected（local_agent、CLI、Assistant、Interaction、Collaboration、Story、task infrastructure、离线入口）。`python -m ruff check backend` 通过。
- 前端受影响 Vue 测试：102 passed；`npm run lint`、`npm run build` 通过。
- 独立 PostgreSQL 17/pgvector 专用测试库 Alembic 升级 head 通过；`tests/e2e/test_local_agent_cli.py` 2 passed，覆盖确认/领取门禁、真实 HTTP 伴随路由与 worker 受控工具成功和错误回执。下载的 pyz 无源码检出可运行 `--help`。`alembic check` 仍有本分支之前的 autogenerate 漂移，不能宣称全绿。
- `make docs-check BASE_REF=origin/main`、`git diff --check` 通过。
- 五 CLI 真实合成响应：Codex 显式 `gpt-5.6-luna`、Claude、Kimi、DSH 隔离 `DSH_HOME`、Pi 显式 `deepseek/deepseek-v4-flash` 均返回预期 JSON；离线 `CLIStructuredExecutor(codex)` 也返回结构化结果。仅为协议兼容 smoke，不是产品真实任务或质量验收。

## 未闭合限制

- DSH headless 只提供纯文本最终输出，stderr 是自由格式 reasoning，没有可核对的原生工具事件；因此原生文件/命令工具次数不能硬限，产品工具次数、运行时间和输出量仍受限。设置界面已明示。
- 本机现有 `~/.dsh/.env` 的 `http_proxy` 被 DSH 拒绝；隔离 `DSH_HOME` 合成试跑成功，不改用户配置。Pi 默认模型不可用，显式 DeepSeek 模型成功；Codex 默认模型在当前 CLI 登录态不可用，显式 Luna 成功。伴随进程支持 Codex/Pi 模型覆盖与外部 `DSH_HOME`。
- 设置页浏览器导航已重验；尚无 pyz 通过独立网络服务器执行完整产品 Agent 的验收。PostgreSQL 测试使用 ASGI HTTP 路由与真实 worker runtime，覆盖协议核心但非完整部署形态。
- 本分支已解决与 #171/#172 的共享冲突并推送为草稿 PR #173；本轮设置页修复待远端 CI 复验，未合并或部署。
