---
id: T-20261014-audit-g3-renderer
title: 退役旧 bundle Markdown renderer
status: completed
created: 2026-10-14T11:23:43+08:00
updated: 2026-10-14T11:32:41+08:00
---

# 旧 bundle Markdown renderer 退役

## 恢复快照

- 工作区：`.worktrees/audit-g3-renderer`，`codex/audit-g3-renderer`；基线 `22bb499789cba89fea92e918fd853ab768688e07`。
- 已完成：Commit 1 `8625354b6` 缩公开面；Commit 2 删除旧实现及 22 个专用测试，迁移隐藏真相断言、保留 overdue 编译断言；三处文档同步，回归与门禁通过。
- 下一步：主 Agent 审查两个本地提交；合并前更新基线和复跑必要门禁，仍需合并授权。
- 阻塞：无。

## 目标与验收

按已获授权的首批计划分两次本地 commit 退役旧 renderer，保留 `StructureContextBundle`、编译、DI 与活跃 IR renderer；固定 IR 删前删后字节/hash 相同，受影响测试与门禁通过。

## 上下文与边界

只编辑本 worktree，独立任务笔记不改索引。不推送/建 PR/合并/部署，不调用真实模型或真实数据库，不清理其他 WIP。权威计划：`docs/plans/2026-10-14-audit-followup-batch.md`（audit-followup 工作树只读）。

## 里程碑与进度

- [x] Commit 1 缩公开面；测试直接导入旧实现，行为不变。
- [x] Commit 2 删除旧实现/专用用例，迁移隐藏真相安全断言并保留 overdue 编译断言，同步三处文档。
- [x] 全部验收验证与结果交接。

## 决策、发现与失败

- 保留 `is_adopted_world_status`：活跃 IR renderer 的混合事实等级判断仍使用它。

## 验证证据

- 开工 `make docs-check`：通过。

## 交付结果

已实现与验证；两个本地提交，无 push/PR/merge/deploy。未运行真实模型/数据库或浏览器验收（本切片无用户界面/数据行为变更）。现存 bundle 字段的继续精简属于另批；不改 indexing 文档或加抽象。

## 验证明细与恢复方法

- 解释器/依赖只读复用 `/Users/tywww/.codex/worktrees/codex-luna-runtime/ai-writing-assist/backend/.venv/bin`，未安装依赖；本次未通过 uv 同步新环境。
- Commit 1 三个受影响测试文件：213 passed。
- Commit 2：`python -m pytest modules/evidence/compilation/tests tests/unit/test_context*.py modules/story/tests/test_story_tasks.py modules/story/tests/test_run_envelope_story.py modules/story/outline_state/tests/test_task_ai_transactions.py modules/story/outline_state/tests/test_context_integration.py tests/modules/outline/generation/test_context_builder.py -q --disable-warnings`：470 passed，8.83s。SQLite 专用内存 fixture，不接真实数据库。完整汇总 [tests.log](artifacts/tests.log)。
- `make lint BACKEND_LOCKED_CI_RUN='<runtime>/python -m'`：All checks passed；仅替换 runner 为既有解释器，不改检查内容。
- `PATH=<runtime>:$PATH make prompt-contracts`：26 contracts passed，[记录](artifacts/prompt-contracts.log)。
- `make repo-gates`：binary-growth、file-size、release-evidence、module-import 全过，[记录](artifacts/repo-gates.log)。Commit 2 落地后已按最终 HEAD 再跑通过。
- 初次 `make docs-check BASE_REF=origin/main` 按 module-contract 规则要求复核总览和 indexing README。已读 `backend/modules/evidence/README.md`：其公开面描述活跃 `render_compiled_context`，未引用已退役函数；已读 `backend/modules/evidence/indexing/README.md`：索引/检索流水线不调用旧 renderer，不改数据、API 或任务契约。三个指定文档已同步，因此使用既有 `--no-change-reason` 记录上述具体理由通过，[记录](artifacts/docs-check.log)。无修改门禁或 blanket 豁免；未来 PR 同样须填写具体说明。
- `git diff --check`：通过；四个改动 Python 文件 `ruff format` 通过。
- 固定 IR 覆盖乱序 tier、事实/计划/候选/混合等级、未知 section、预算截断/逐出及无事件回退。删除前保存 [fixed-ir.json](artifacts/fixed-ir.json)、[render-before.md](artifacts/render-before.md)、[SHA256](artifacts/render-before.sha256)；删除后重新渲染，字节与 hash 完全一致，967 bytes，SHA256 `6af9283cc8145bef1fe15466992580a07fa3d3474dadea7e78b86e2212d10d74`，[核对记录](artifacts/render-after-verification.txt)。
- 复核固定 IR：在 backend cwd，用 `CompiledContext.model_validate(json.loads(Path('../.agent/tasks/2026/T-20261014-audit-g3-renderer/artifacts/fixed-ir.json').read_text()))` 喂给 `render_compiled_context`，其 UTF-8 bytes 应等于 `render-before.md`，hash 应等于 `render-before.sha256`。
- 保留 `StructureContextBundle`/compiler/loader 和 `CONTEXT_COMPILE` DI 全链；删除后 tracked Python 搜索无旧 renderer/旧 helper 引用。
