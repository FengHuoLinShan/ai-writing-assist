# L4 交接报告（会话、服务与 API）

车道：L4　分支：`codex/spreadsheet-migration-l4`　提交：`0b5a6470e`

> 执行说明：车道代理因模型配额中断，仅留下 planning.py 半成品；本车道由集成者在
> 主会话续完（保留 planning.py 已有实现，补 service/api/挂载/测试），自检全绿。

## 已完成

- `spreadsheet_migration/planning.py`（车道代理遗留，920 行，已复核）：
  `build_migration_requests` 按 mapping/decisions/AI 结果构造 world/story 请求；
  文件内同名同类型合并（值不一致记文件内冲突备注）；item_key 由 sheet_key+行号+名称
  确定性生成；source_hash 为行单元格 sha256；AI 条目只合并已通过审查且作者接受的；
  AI 未覆盖/失败行回落规则映射；大纲类表（story_outline/freeform_outline）正文转
  markdown、creative_core 来自 AI；总量超限 400（migration_items_exceeded）。
- `spreadsheet_migration/service.py`：上传（扩展名/空文件/单文件 10MB/会话 2M 字符校验、
  to_thread 解析、classify 建默认 mapping、manifest 记录 headers+suggested 快照）；
  会话按 (id, novel_id, owner) 隔离 404；rows 读取（draft 之外 410）；mapping/decisions
  revision CAS + 重算 preview 写回 plan_json/preview_hash；apply 单事务五步（重算比对
  hash → require_active_project_exclusive → world.apply → story.apply(entity_ids) →
  mark_applied 清 rows → commit）；rollback dry_run/实做（story 先 world 后，kept →
  partially_rolled_back）；ai_status 对照 AsyncTask 终态修正；回执含 labels 供回滚预览
  渲染；删除会话。
- `spreadsheet_migration/api.py`：§3.6 全部 11 个端点；multipart 分块上限；作者语言错误
  文案；action/reason/field/kind 全部映射作者标签；预览渲染含 AI 覆盖标记。
- `app/main.py`：挂载路由（在 imports_api.router **之前**，避免 `/api/imports/{record_id}`
  吃掉 `/api/imports/migrations`）。
- 测试：`test_spreadsheet_migration_service.py`（11 用例）+ `test_spreadsheet_migration_api.py`
  （13 用例）：全路由、跨 novel/未知 id 404、扩展名/413 拒绝、CAS 409、stale 409 附新
  hash、Literal[True] 422、rows 410、删除需 confirmed、日志不含正文（caplog）、
  demo 白名单钉住测试。

## 改动文件

全部在本车道独占清单内（planning/service/api/app/main.py/两个测试文件）。

## 契约偏离

无（L0 冻结契约零改动）。四点实现说明：

1. **manifest 扩展字段**：file_manifest 的 sheets 增记 `headers`（表头原文）与
   `suggested`（classify 建议快照），用于采用后仍能渲染列信息与 kind_suggested/
   target_suggested；属 L0 自有 JSON 形状的向后兼容扩展。
2. **`parse_spreadsheet_file` 延迟导入**：L1 未合入时该名字不存在，service 在
   create_session 内延迟导入；测试对缺失属性用 `new=` 显式替身（autospec 无法替身
   不存在的属性，create=True 与 autospec 互斥），已在测试内注释说明；L8 换真实链路。
3. **路由挂载顺序**：必须在 imports_api.router 之前，否则 GET /api/imports/migrations
   被既有 `/api/imports/{record_id}` 抢占（实测发现）。
4. **AI 结果形状**：`ai_result_json` 约定为 `{version, scope_hash, outline:[], cleanup:[]}`，
   每组含 `source_rows`/`governance.status`/`proposal_refs`；预览 AI 覆盖标记与
   `ai_items_for_planning` 的输入都基于该形状（与 L5 车道 docstring 一致）。

## 测试

- `make test TESTS="modules/imports/tests/test_spreadsheet_migration_service.py
  modules/imports/tests/test_spreadsheet_migration_api.py"` → 24 passed。
- `make test TESTS="modules/imports/tests"`（全量）→ 744 passed。
- `make lint` → 通过。
- 未运行：docs-check（不改文档，收尾统一跑）；PG 专属（L8）。

## 文档要点（供 L7b）

- 新路由前缀 `/api/imports/migrations`（11 端点），挂在 imports 路由之前。
- apply 单事务语义与 preview_hash 组成（world.fingerprint + story.fingerprint +
  mapping + decisions + 已接受 AI 条目 + revision）。
- 回执只存 id/hash/labels/counts，rows 采用后清空；删除不可再撤销。
- 410（rows 清除）/409（CAS、stale、重复采用、未采用回滚）/422（Literal[True]、
  AI 超预算）的错误码清单。

## 风险与待决

- `_decision_label` 返回动作原文（auto/use_existing 等），L6 渲染时需映射作者语言。
- 关系预览的 source_label/target_label 依赖 planning 的标签约定（"A → B" 拆分），
  L8 联调时与 L2 的 target_label 字段对齐复核。
- ai_authorization 目前只在提交时保存 estimate；submit_ai 的 422 文案由 L5 的
  ValidationError 提供。
