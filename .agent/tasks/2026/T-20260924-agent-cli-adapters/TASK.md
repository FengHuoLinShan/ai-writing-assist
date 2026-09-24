---
id: T-20260924-agent-cli-adapters
title: Agent 底座接入五种本机 CLI
status: active
created: 2026-09-24T00:24:52+08:00
updated: 2026-09-24T02:04:00+08:00
---

# Agent 底座接入五种本机 CLI

## 恢复快照

- 隔离工作树：`/Users/tywww/.codex/worktrees/agent-cli-adapters/ai-writing-assist`，分支 `codex/agent-cli-adapters`，基线 `eeccc4e26bd56294b13666b2111b61874e925c42`。原 V4 工作树 WIP 未触碰；本分支未提交、推送、合并或部署。
- 已实现五种 CLI 子进程适配、离线结构化评测入口、项目配对与出站伴随进程、逐根任务主机权限确认、租约/产品工具/回执协议；Assistant、已登录 RP、前瞻、创作协作、连续性检查及 Story 场景排演的人物意图 Agent 接入项目选择。匿名 RP 和普通非 Agent LLM 流程保持原连接。场景排演的环境裁决与剧本仍用项目账户连接。
- 本机任务统一 `never_retry`，中断保留已见回执，显式新任务重试。项目/owner、Evidence、确认、CAS、预算和租约校验保留；本机 CLI 工作目录不是主机权限沙箱。
- 下一步：解决或明确验收 DSH headless 无结构化原生工具事件导致的原生工具次数不可核对；再做真实浏览器与伴随进程跨网络流程验收。没有这些证据不要宣称正式全量验收。
- 最后核实：2026-09-24T02:04:00+08:00。

## 目标与验收边界

- 五 CLI 独立服务本机产品 Agent 与离线评测；Mac 伴随进程按作品配对，项目默认原 gateway，每个根任务单独确认完整本地文件/命令权限；离线等待、租约失效失败关闭、显式新运行重试。
- 逻辑关键路径和失败路径经定向测试；五个真实 CLI 用合成资料试跑，测试绿色不能代替真实作品或产品质量验收。
- 本机实现与验证不授权自动提交、推送、合并、部署或清理用户数据。

## 验证

- 后端定向回归：508 passed、2 deselected（local_agent、CLI、Assistant、Interaction、Collaboration、Story、task infrastructure、离线入口）。`python -m ruff check backend` 通过。
- 前端受影响 Vue 测试：102 passed；`npm run lint`、`npm run build` 通过。
- 独立 PostgreSQL 17/pgvector 专用测试库 Alembic 升级 head 通过；`tests/e2e/test_local_agent_cli.py` 2 passed，覆盖确认/领取门禁、真实 HTTP 伴随路由与 worker 受控工具成功和错误回执。下载的 pyz 无源码检出可运行 `--help`。`alembic check` 仍有本分支之前的 autogenerate 漂移，不能宣称全绿。
- `make docs-check BASE_REF=origin/main`、`git diff --check` 通过。
- 五 CLI 真实合成响应：Codex 显式 `gpt-5.6-luna`、Claude、Kimi、DSH 隔离 `DSH_HOME`、Pi 显式 `deepseek/deepseek-v4-flash` 均返回预期 JSON；离线 `CLIStructuredExecutor(codex)` 也返回结构化结果。仅为协议兼容 smoke，不是产品真实任务或质量验收。

## 未闭合限制

- DSH headless 只提供纯文本最终输出，stderr 是自由格式 reasoning，没有可核对的原生工具事件；因此原生文件/命令工具次数不能硬限，产品工具次数、运行时间和输出量仍受限。设置界面已明示。
- 本机现有 `~/.dsh/.env` 的 `http_proxy` 被 DSH 拒绝；隔离 `DSH_HOME` 合成试跑成功，不改用户配置。Pi 默认模型不可用，显式 DeepSeek 模型成功；Codex 默认模型在当前 CLI 登录态不可用，显式 Luna 成功。伴随进程支持 Codex/Pi 模型覆盖与外部 `DSH_HOME`。
- 尚无真实浏览器操作及 pyz 通过独立网络服务器执行完整产品 Agent 的验收；PostgreSQL 测试使用 ASGI HTTP 路由与真实 worker runtime，覆盖协议核心但非完整部署形态。
- 当前本地实现没有提交、推送、合并、CI 或部署结果。
