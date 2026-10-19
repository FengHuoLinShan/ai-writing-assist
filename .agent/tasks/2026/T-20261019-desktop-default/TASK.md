---
id: T-20261019-desktop-default
title: 桌面应用默认开发与按需平台发布迁移
status: active
created: 2026-10-19T02:40:00+08:00
updated: 2026-10-19T09:48:38+08:00
---

# 目标与验收

用户要求以后以应用模式开发，放弃分离前后端交付；发布仅手动触发，默认 Mac Apple Silicon，Intel/Windows 必须明确选择。默认开发入口、发布平台选择、来源/摘要/签名门禁和权威文档一致；覆盖正常与失败路径，不实际发布或操作真实数据。

## 上下文与边界

- 基线 origin/main `7c3cb04837f9b5561a9321940857975f6282453a`，分支 `codex/desktop-default`；与原 HEAD tracked tree 相同。原 `.agent/TASKS.md` 和作者工作台 TASK.md 的本地收口改动保留。
- 已读 desktop 实现、ADR-0043、开发/测试指南、发布流程和既有桌面任务。已有桌面运行时可复用，保留内部 FastAPI/Vue/PostgreSQL 和领域安全契约，不重写业务栈。
- 影响：Makefile/start.sh、桌面源码入口、两份桌面 workflow、release.py/测试、旧服务器镜像 workflow 与相关静态合同、默认开发文档/ADR/AGENTS。
- 旧服务器脚本保留供显式诊断/历史环境；退出默认开发、安装包发布和镜像自动构建链。不迁移旧库、不读取真实作品、不调用业务 LLM；本轮续接已授权提交/PR/CI 全绿后合并，仍无安装包构建或发布授权。

## 进度与决策

- [x] 核验工作树、读取实际调用链、fetch main；实施前 make docs-check 通过。
- [x] 默认开发入口运行桌面源码；开发数据与安装版分开，准备资源无需打包。
- [x] 手动构建/发布默认 ARM64；显式选择 Intel、Windows 或 all；产物验证保留失败关闭。
- [x] 同步当前文档并验证关键失败路径。

## 发现与决定

- 真实执行 make desktop-prepare 暴露外层 MAKELEVEL/MAKEFLAGS 导致 PostgreSQL 跳过 generated headers；在 build_assets.run 清理递归环境并补回归，随后完整资源准备成功。不是缺少系统头文件，也不以重试掩盖。
- 桌面开发使用独立 venv、数据与原生资源，前端改动重开即重新构建；缺资源/构建失败均停止，不打开旧静态界面。Intel 必须显式 DESKTOP_TARGET=macos-x64，Make 对齐 Python 3.13.15；其他目标跟随 backend/.python-version。
- 原生安装包 workflow 取消 PR/push，只保留手动/复用；默认 ARM64，另两平台或 all 需显式选择。assembly 对所选平台保留同 SHA、同版本、完整性与稳定版签名门禁，并拒绝额外平台。
- 实时只读核验远端 ruleset 20497366 仍要求 Production image contract。为避免移除工作流后 Pending，保留 PR/main 触发和检查名，镜像 job 仅 workflow_dispatch 执行，其他事件明确 skipped、不分配 runner。未修改远端保护规则；手动镜像漏洞/签名等门禁均保留。

## 验证

- 最终定向单测：147 passed / 2 Windows-only skipped，日志 /tmp/desktop-default-tests.log；覆盖全部 desktop/tests、启动脚本、测试工具链、安全工作流和 CI 分类器。
- 独立 desktop/build/venv 中 desktop/tests：46 passed / 2 skipped（当时版本），日志 /tmp/desktop-default-isolated-tests.log。
- make desktop-prepare 成功（仅本机 ARM64 原生数据库/扩展/模型与依赖，不冻结安装包）；npm ci 0 vulnerabilities。
- make dev 实际构建前端并启动源码 GUI 进程及本机数据库/API/worker；新开发目录权限 0700，PG 17，随后只终止本次启动的 GUI 进程并确认所属服务关闭。未读取安装版或旧开发数据。
- 同一独立环境 desktop/smoke.py 成功，日志 /tmp/desktop-default-source-smoke.log：真实本机 ONNX、全新隔离建库、会话/单实例、作品持久化与退出重开。不调用业务模型。
- Ruff、bash -n start.sh、git diff --check、make docs-check BASE_REF=origin/main 通过；默认 ARM64 / 显式 Intel 的 Make dry-run 命令与 Python 选择核对。
- CUA 未能将无 app bundle 的源码 Python 进程绑定为可访问应用，未声称完成原生窗口视觉/作者验收。未构建安装包、未做新签名/公证或其他 OS 验收。

## 恢复快照与交付边界

首轮本地实现、测试及权威文档完成时，分支 codex/desktop-default 尚未提交或发布；当前按下方审查续轮交付，远端状态须实时核验。原有 WIP 保留，未改变真实数据库/稿件或现有模型连接。日常进入 make dev；发布命令见 desktop/RELEASE.md，默认只生成 ARM64 草稿，公开发布仍需当次授权。

当前下一步：仅提交本任务改动（排除作者工作台旧收口 WIP），推送建 PR，等待所有执行的 CI 成功后按用户授权合入 main。Intel/Windows 只有用户明确要求时才构建与原生验收。

## 2026-10-19 审查与主干交付续轮

用户明确授权审查本轮迁移，修复后提交/推送/创建 PR，等待 CI 全绿后合入 main；禁止构建安装包或发布。恢复本任务，不新建。原有作者工作台收口 WIP 不纳入提交。两路只读审查固定基线 7c3cb0483，主 Agent 追踪真实调用链并统一修复。当前恢复快照：审查与定向验证后提交本任务改动，PR 内不触发手动桌面/镜像构建与发布工作流。

### 本轮审查结果与修复

- Standards 与 Spec 两路审查均确认原打包 workflow 改为手动后 desktop Ruff 丢失自动接线；make lint/lint-fix 增补根目录同配置桌面检查，保持已有 backend 的 import 分类，不为接线批量重排 import。
- 主审发现新增源码测试 fixture/期望值固定 postgres/npm，Windows 下应为 postgres.exe/npm.cmd；改为宿主相应文件名与命令，保留全部失败路径断言，本轮不构建 Windows 包。
- make desktop-test 改为仅 ci 依赖、根目录执行的共享源码测试入口，不安装 desktop extra 或准备原生资源；Backend CI 与本地 make test-ci 共同调用，避免本机综合门禁漏桌面。
- 根 AGENTS 明确后续代码开发直接按桌面使用路径验收，涉及本机目录/会话/窗口/生命周期才补源码桌面验证，普通逻辑不重建安装包。

本轮本地验证：make lint（backend+desktop）通过，make desktop-test 47 passed/2 Windows-only skipped；受影响工具链、启动脚本、工作流安全与 CI 分类器 101 passed。未重复原生包构建/未调用业务模型；本轮源码启动与持久化沿用上一轮实际 smoke 证据（运行时代码未变）。
