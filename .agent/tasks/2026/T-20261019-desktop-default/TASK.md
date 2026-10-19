---
id: T-20261019-desktop-default
title: 桌面应用默认开发与按需平台发布迁移
status: completed
created: 2026-10-19T02:40:00+08:00
updated: 2026-10-19T10:37:00+08:00
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

当前结果：PR #259 固定 head `9ec7deedc4c2c286b95b6c753be6f082ccaf147d` 的所有执行检查成功，已按用户授权 squash 合入 main，合并 SHA `bdc6e303793d64774d5701a59006db255ef2b0fe`，fetch 确认 origin/main 可达。本轮无剩余实现或合并项；main 合并后流水线仍在运行，不能当作已全绿。Intel/Windows 只有用户明确要求时才构建与原生验收。

## 2026-10-19 审查与主干交付续轮

用户明确授权审查本轮迁移，修复后提交/推送/创建 PR，等待 CI 全绿后合入 main；禁止构建安装包或发布。恢复本任务，不新建。原有作者工作台收口 WIP 不纳入提交。两路只读审查固定基线 7c3cb0483，主 Agent 追踪真实调用链并统一修复。当前恢复快照：审查与定向验证后提交本任务改动，PR 内不触发手动桌面/镜像构建与发布工作流。

### 本轮审查结果与修复

- Standards 与 Spec 两路审查均确认原打包 workflow 改为手动后 desktop Ruff 丢失自动接线；make lint/lint-fix 增补根目录同配置桌面检查，保持已有 backend 的 import 分类，不为接线批量重排 import。
- 主审发现新增源码测试 fixture/期望值固定 postgres/npm，Windows 下应为 postgres.exe/npm.cmd；改为宿主相应文件名与命令，保留全部失败路径断言，本轮不构建 Windows 包。
- make desktop-test 改为仅 ci 依赖、根目录执行的共享源码测试入口，不安装 desktop extra 或准备原生资源；Backend CI 与本地 make test-ci 共同调用，避免本机综合门禁漏桌面。
- 根 AGENTS 明确后续代码开发直接按桌面使用路径验收，涉及本机目录/会话/窗口/生命周期才补源码桌面验证，普通逻辑不重建安装包。

本轮本地验证：make lint（backend+desktop）通过，make desktop-test 47 passed/2 Windows-only skipped；受影响工具链、启动脚本、工作流安全与 CI 分类器 101 passed。未重复原生包构建/未调用业务模型；本轮源码启动与持久化沿用上一轮实际 smoke 证据（运行时代码未变）。

本轮提交推送 `a36792de5`，PR #259：https://github.com/FengHuoLinShan/ai-writing-assist/pull/259 已创建。当前等待该固定 head 的所有执行 CI，全部成功且 main 基线不漂移后按授权 squash 合并；禁止手动安装包/发布。旧作者工作台 TASK 与 TASKS 的收口 WIP 仍未提交。

首轮 CI：Backend 9310 passed/2 skipped（覆盖率 85.30%）、desktop 47 passed/2 skipped、PostgreSQL critical、前端单测、浏览器分片 1、CodeQL 与文档/治理门禁成功。浏览器分片 2 为 169 passed/2 skipped/1 failed：固定参考恢复的 390px 用例先在 1280px 进入再 resize，WritingView 的窄屏 watcher 关闭章节栏与 fixture 读取旧 aria-expanded 竞态，trace/screenshot 证实；未合并失败版本。

修复仅将该固定尺寸用例的目标 viewport 前置到进入工作区之前，保留所有功能断言，两路审查中的 Spec reviewer 复核通过。真实 Chromium + 全新隔离 PostgreSQL 中 1280/390 各重复 3 次，6 passed（35.1s），无 retry；日志 /tmp/pr259-browser-check.log。本机首次复测因缺少新版 Chromium 未启动，安装对应测试浏览器后通过。测试结束仅关闭专用 PG，未访问真实作品或调用业务模型。ESLint、docs-check 与 diff 检查通过；等待新提交完整 CI。

最终 head `9ec7deedc` CI 进度：Backend 9310 passed/2 skipped、coverage 85.30%，desktop 47 passed/2 skipped，部署工具合同 323 passed/1 skipped；PostgreSQL 417 passed/7 deselected；前端单测、浏览器分片 2、全部 CodeQL、架构文档与治理门禁成功。仅分片 1（含 WebKit/助手/创作/编辑合成 harness）尚在运行，未合并。日志 /tmp/pr259-final-backend.log、/tmp/pr259-final-postgres.log、/tmp/desktop-default-pr259-final-checks.log；工作流 39189102438/39189102520。Production image contract 按策略 skipped；桌面安装包/发布工作流未触发。重复 Architecture docs 的旧 run 因并发规则 cancelled，新的同名检查已成功，无需重复执行。

### 最终交付

2026-10-19T10:36:15+08:00，固定 head 的 18 项当前检查核验：17 SUCCESS，仅 Production image contract 按新策略 SKIPPED。分片 1 常规 209 passed/1 skipped、分片 2 为 170 passed/2 skipped；WebKit 14、助手 14、创作 9、编辑 10 全部通过。补充 PR 正文后触发的文档检查也成功。随后以 --match-head-commit squash 合并，API 确认 MERGED，远端 main 为 `bdc6e303793d64774d5701a59006db255ef2b0fe`；未绕过保护规则。证据 /tmp/pr259-final-ci.json、/tmp/pr259-merge-receipt.json、/tmp/pr259-final-browser-shard1.log 与 shard2.log。

合并后 main 已启动常规 Backend/Frontend/CodeQL/repo-gates；Architecture docs 成功，Production Image CI skipped，未启动 Desktop installers/桌面发布。未构建安装包、未发布或部署、未调用业务模型、未读写真实稿件。源码 native/作者人工验收和 Intel/Windows 原生运行不在本轮验证范围。本地停留 codex/desktop-default；本任务收口笔记与索引仅本地，不为笔记另提交 main 或重复推送。原有作者工作台收口 WIP 及执行期间新增的 novel-data-readiness-research 未跟踪目录均保留、不纳入本 PR。
