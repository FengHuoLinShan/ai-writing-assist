# L5 交接报告（AI 整理）

车道：L5　分支：`codex/spreadsheet-migration-l5`　提交：`2fef74ca1`、`28bec4ecb`

> 执行说明：车道代理因模型配额中断，留下 ai.py 半成品（1109 行，三个入口与
> worker 主链已成形）；本车道由集成者复核后续完（prompts/契约注册/handler/
> 白名单/fixtures/测试）。

## 已完成

- `spreadsheet_migration/ai.py`：实现 `estimate_ai_run` / `submit_ai_run` /
  `ai_items_for_planning` 与 worker 主链 `run_spreadsheet_migration_ai`。
  - scope → unit → packet 打包：每包 ≤AI_PACKET_CHARS、总包数 ≤AI_MAX_PACKETS，
    超出 422（migration_ai_budget_exceeded）；空范围 422。
  - 提交四步：require_active_project → get_operation_task（同指纹复用）→
    build_project_llm_execution_snapshot → enqueue_task_with_optional_operation；
    meta 冻结 ai_packets、run_request_limit（packets*6+2）、scope_hash。
  - 两个 step：`imports.spreadsheet_migration.outline` / `.cleanup`，经
    `run_managed_structured(max_fix_attempts=1, ContextBudget(100_000/40_000))`；
    审查 `govern_group_output(capability="imports.spreadsheet_migration",
    GroupSource(source_type="imported_assets"), repair=一次返修)`。
  - 确定性校验：row_ref 必须在本包；evidence 为所引行子串（空白归一）；
    章号范围自洽（≤99_999）；forbidden keys（id/novel_id/status/source）；
    字段白名单（cleanup 13 个）。不通过项丢弃回落规则映射；审查未通过组
    passed=false 不可被作者接受。
  - scope_hash 漂移（任务与当前会话）不写回并 409 失败关闭；结果经
    repository.store_ai_result（scope_hash 一致才写）。
  - 附加上下文只有已写章节号与已知对象名（各有上限）。
- `prompts/spreadsheet_outline_convert.md`、`spreadsheet_cell_cleanup.md`：
  忠实整理、逐字 evidence、禁 id/status/source、允许 unmapped_rows/remainder、
  围栏内不可信数据声明。
- `tools/prompt_contracts/contracts/spreadsheet_{outline_convert,cell_cleanup}.json`
  + fixtures：26 契约全过；required_mappings 为空（输出不直接持久化，全部经
  作者确认的迁移请求落地）。
- `evidence/compilation/knowledge/policies.py`：`imports.spreadsheet_migration`
  （CONFIRMATION_NONE、imported_assets、紧挨 targeted_completion）。
- `tools/prompt_contracts/capability_bindings.py`：ai.py 绑定注册。
- `imports/tasks.py`：`@task_handler("spreadsheet_migration_ai", auto_requeue,
  max_attempts=2, retry_transient_llm_errors=True, root_capability_id,
  run_request_limit=meta 冻结 packets*6+2)`。
- `infrastructure/tasks/api.py`：任务类型加入 `_MODULE_API_ONLY_TASK_TYPES`。
- 测试 `test_spreadsheet_migration_ai.py`：14 用例（估算、过滤、白名单、
  envelope 声明、超预算 422、入队冻结、校验器白盒 6 例、worker 写回与
  scope 漂移失败关闭）。

## 改动文件

全部在本车道独占清单内。

## 契约偏离

无。两点说明：

1. **ai_result_json 形状**：`{version, scope_hash, outline:[], cleanup:[]}`，每组
   `{operation, sheet_key, group_key, source_rows, governance, passed, items:[{item_key,
   proposal_ref, source_rows, evidence, payload}], dropped:[]}`；L4 预览的
   `_ai_coverage` 读 `governance.status` 而本车道写 `passed` 布尔——**L8 集成时
   需对齐**（择一统一）。
2. **run_request_limit 用 meta 冻结 + callable 读取**（仿 map_atlas），计划文字
   `<packets*6+2>` 的静态形式在 packets 动态时不可行，语义一致。

## 测试

- `make prompt-contracts` → 26 contracts passed。
- `make test TESTS="tests/prompt_contracts modules/imports/tests"` → 752 passed。
- `make lint` → 通过。
- 未运行：真实模型（须用户单独授权）；worker 真实 provider 链（L8 信封实测）。

## 文档要点（供 L7b）

- capability `imports.spreadsheet_migration`（CONFIRMATION_NONE，输入只有作者
  自上传行）；step 两个；治理经 ADR-0025 govern_group_output。
- 任务类型 `spreadsheet_migration_ai`：auto_requeue、最多 2 次、信封额度
  packets*6+2；结果仅写会话 ai_result_json（预览用）。
- AI 输出永不直接落库；确定性校验四类拒绝原因码。

## 风险与待决

- `_reasoning_extra` 从 scene_entity_llm_adapters 私有函数导入（既有跨文件私有
  依赖先例待 L8 复核，如需改为公共工具属小重构）。
- 真实 LLM 的 evidence 逐字率可能低于预期（LLM 改写倾向），dropped 率要在
  真实模型验收时观察；校验是硬门槛，宁丢勿假。
