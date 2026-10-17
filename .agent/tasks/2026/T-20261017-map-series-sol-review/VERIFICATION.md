# R1–R12 修复后独立核对

## 最新复核：2026-10-17 15:24 +08:00

用户要求再次检查。当前补丁已修复下述 V1/V2；**两个原失败复现原样重跑均通过，本次核对范围未发现新增阻断问题**。
以下 15:16 的失败分析保留为历史证据，不能作为当前仍有两个 P2 的结论。

- V1：不再先过滤历史修订。有 active 无锚条目时使用该组当前修订；否则若真正最新修订有锚，
  为新长期值另建组。新增实际 ORM 用例断言旧时点组保持 active，新长期条目属于不同组。
- V2：旧根保留停止提示，新完成根提供显式重新授权；当前项目 revision 继续用于 CAS，
  用户重新选择新根参与者并确认新 Scene。组件回归实际点击授权，验证新 root/branch、Scene、
  参与者和 expected_revision，服务端仍保留最新 Scene、范围、预算和并发门禁。
- 本次独立重跑五个后端文件 **46 passed**，`/tmp/map-series-reverify-backend.log`；
  三个前端文件 **58 passed**，`/tmp/map-series-reverify-frontend.log`。
- 上次两个临时复现从 `/tmp` 原样恢复，分别 **1 passed**，日志
  `/tmp/map-series-reverify-dossier-edge.log`、`/tmp/map-series-reverify-auth-edge.log`；
  前端 10 skipped 仅为测试名过滤。临时文件已移除，没有修改生产代码或既有测试。
- 工作树和 HEAD 与下文一致；当前 `git diff HEAD -- backend frontend-console docs` SHA-256
  `dea9d4af5aefed53e9b4ed904dba9ea9b4bba6a63220ee297f870b42490db824`。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过；文档门禁日志
  `/tmp/map-series-reverify-docs.log`。
- 未重跑全量 CI、PostgreSQL 并发、浏览器、真实模型或作者验收；未提交、推送、合并或部署。

## 首次核对：2026-10-17 15:16 +08:00

核对时间：2026-10-17 15:16 +08:00。结论：**仍有 2 项 P2，建议修复后再合入**。
已回读全部 12 项对应改动及调用链；现有定向回归全部通过，但新增边界复现均失败。
本次由主会话核对，没有再次委派子代理，没有修改生产代码或保留新增测试。

## V1 · P2 · 档案改为时点有效后，实体编辑仍撞唯一约束（R2 残留）

位置：`backend/modules/world/dossier_repository.py:158-168`，调用方
`dossier_service.py:2429-2436,2466-2472`。

触发步骤：通过实体接口创建含 `public_info` 的对象，生成同组无锚修订 v1；通过档案编辑给该条目
增加 Scene 起始有效期，生成 active 的有锚 v2；再从实体接口填写新的长期 `public_info`。

`unanchored_only=True` 在选取最新修订前过滤了有锚行，因此跳过当前 v2，取回已 superseded 的 v1。
同步服务沿用 v1 的条目组并尝试插入 active v2，既有 active v2 未被收拢，触发
`uq_world_dossier_active_group`（同组修订号也重复）。实体编辑失败，事务回滚。
现有新增测试只覆盖两个独立条目组，没有覆盖同组有效期修改历史。

最小修法：先确定条目组的真正最新修订，再判断该组是否无锚；不得从被过滤掉当前修订的历史组
继续追加。若不存在可复用的无锚当前组，为实体长期值建立新组，保留已有时点组。

独立复现经 `WorldEntityService.create` → `WorldObjectDossierService.update_entry` →
`WorldEntityService.update`，在 rollback-only SQLite fixture 中实际失败：
`IntegrityError: UNIQUE constraint failed: world_object_dossier_entries.novel_id, world_object_dossier_entries.entry_group_id`。
日志 `/tmp/map-series-verify-dossier-edge.log`；复现源码 `/tmp/map-series-verify-dossier-repro.py`。
可临时复制到 `backend/modules/world/tests/test_map_series_verify_temp.py` 并运行
`UV_CACHE_DIR=/tmp/ai-writing-assist-uv-cache make test TESTS=modules/world/tests/test_map_series_verify_temp.py`。
临时文件已移除，未操作业务数据库。

## V2 · P2 · 自动停止后新建推进仍无法重新授权（R8/R9 相邻生命周期遗漏）

位置：`frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:1149-1150,1486-1493,372-373`。

触发步骤：旧根 A 开启持续授权；读入新 Scene 后服务端以 `confirmation_scope_changed` 自动停止；
作者按提示从最新 Scene 新建并完成根 B，再刷新推进面板。

服务端 `_stop_continuous_authorization` 只关闭 enabled，保留旧 root/branch 和 revision；
面板仍将 `activeAuthorizationRootId` 设为 A，只在旧分支展示持续区域。
该区域又因 stop_reason 隐藏授权按钮，关闭按钮也因 enabled=false 隐藏；B 没有持续区域。
所以“从最新 Scene 新建推进并重新开启”的既定恢复路径不可达。首次授权、手动关闭后重开和旧的
**启用中**授权撤销测试均通过，但没有覆盖这条自动停止后的恢复路径。

最小修法：区分启用中的绑定与已停止的历史绑定，允许在新根合格分支显示重新授权入口，并沿用
项目当前授权 revision 做 CAS；保留旧根停止原因，不自动启用、不重置旧预算或扩大确认范围。

独立 Vitest 复现以真实组件渲染两个已完成根，使用服务端自动停止的真实返回形状；
断言新根存在“确认持续授权”，实际按钮数为 0。日志 `/tmp/map-series-verify-auth-edge.log`；
复现源码 `/tmp/map-series-verify-auth-repro.test.js`，可临时复制到
`frontend-console/tests/vue/outline/MapSeriesVerifyTemp.test.js`，在前端目录运行
`npx vitest run tests/vue/outline/MapSeriesVerifyTemp.test.js -t 'verify:'`。
日志中的 10 skipped 是按名称过滤的历史测试，不计入本次 57 项通过数。临时文件已移除。

## 原 12 项核对结果

| 原编号 | 本次结论 |
|---|---|
| R1 | 原清空场景修复，实际 ORM 回归通过。 |
| R2 | 独立有锚/无锚组场景修复；同组改有效期仍失败，见 V1。 |
| R3 | 共享撤销调用同步修订；实际表格补空、撤销后的列值与档案状态断言通过。 |
| R4 | 草图校验、托盘和通知调用方均传入同词条历史修订兼容；采用与草图校验回归通过。 |
| R5 | 作者与角色求交前恢复 scene_id；选中连续性事实保留、排除事实未回流的回归通过。 |
| R6 | append 共用计划在预览与项目排他锁内启动时检查活动补扫；原 operation_id 重放在新计划前返回。计划拒绝回归通过；未实测 PostgreSQL 并发。 |
| R7 | 有 pending 时不再受新启动 canStart 门槛阻断；needs_scene_review 停点使用原请求核对后可恢复，组件回归通过。 |
| R8 | 首次、手动关闭后重开入口回归通过；自动停止后换新根恢复缺口见 V2。 |
| R9 | 读取返回实际项目授权，旧启用中根可定位并关闭，前后端定向回归通过；V2 是已停止状态遗漏。 |
| R10 | 交汇导演预览与启动指示相同，组件实际点击启动并比对载荷的回归通过。 |
| R11 | worker 传 active_ids，意图校验在 resolve 调用前拒绝离场收听者；缺位置与已离场断言通过。 |
| R12 | 明确 422 清 pending 并保留输入，组件回归通过。 |

未将代码静态闭环或替身测试表述成浏览器、模型质量或生产验收。

## 本次验证与快照

- 工作树：`.worktrees/map-series-review-fixes`，分支 `codex/map-series-review-fixes`，
  HEAD `3b2ac9441c0dc08533a3e62269cd054ff35c5302`，核对其未提交修复及未跟踪测试。
- 生产/已跟踪测试/正式文档补丁：`git diff HEAD -- backend frontend-console docs` SHA-256
  `dc65ef83ccd17090dc5b45254248c1035689b1f911ee79085cfd1b0b475b8143`，本次核对未改。
- 后端五个定向文件：**45 passed**，`/tmp/map-series-verify-backend.log`。
- ReadingFlow、GoalRunsPanel、WorldProgressionPanel 三个文件：**57 passed**，
  `/tmp/map-series-verify-frontend.log`。
- 两项临时独立边界复现：**各 1 failed**，失败原因分别为数据库唯一约束、组件缺恢复入口。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过；文档门禁日志
  `/tmp/map-series-verify-docs.log`。
- 未跑全量 CI、PostgreSQL、浏览器、真实模型、真实稿件或作者验收；未提交、推送、合并、部署。
- B10-F2 仍按用户决定留给 ADR-0042。本次只核对，V1/V2 未修复。
