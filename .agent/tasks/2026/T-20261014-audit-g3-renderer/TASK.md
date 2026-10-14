---
id: T-20261014-audit-g3-renderer
title: 退役旧 bundle Markdown renderer
status: active
created: 2026-10-14T20:00:00+08:00
updated: 2026-10-14T20:00:00+08:00
---

# 旧 bundle Markdown renderer 退役

## 恢复快照

- 工作区：`.worktrees/audit-g3-renderer`，`codex/audit-g3-renderer`；基线 `22bb499789cba89fea92e918fd853ab768688e07`。
- 已完成：读取规则与权威计划 §5.1/9/10，开工 docs-check 通过；tracked Python 调用追踪仅旧 facade、包导出、三个测试文件引用。
- 下一步：保存固定 IR 输出，缩公开面并提交；随后删旧 renderer 与专用测试，运行所有验收门禁。
- 阻塞：无。

## 目标与验收

按已获授权的首批计划分两次本地 commit 退役旧 renderer，保留 `StructureContextBundle`、编译、DI 与活跃 IR renderer；固定 IR 删前删后字节/hash 相同，受影响测试与门禁通过。

## 上下文与边界

只编辑本 worktree，独立任务笔记不改索引。不推送/建 PR/合并/部署，不调用真实模型或真实数据库，不清理其他 WIP。权威计划：`docs/plans/2026-10-14-audit-followup-batch.md`（audit-followup 工作树只读）。

## 里程碑与进度

- [ ] Commit 1 缩公开面；测试直接导入旧实现，行为不变。
- [ ] Commit 2 删除旧实现/专用用例，迁移隐藏真相安全断言并保留 overdue 编译断言，同步三处文档。
- [ ] 全部验收验证与结果交接。

## 决策、发现与失败

- 保留 `is_adopted_world_status`：活跃 IR renderer 的混合事实等级判断仍使用它。

## 验证证据

- 开工 `make docs-check`：通过。

## 交付结果

尚未交付；仅本地授权范围。
