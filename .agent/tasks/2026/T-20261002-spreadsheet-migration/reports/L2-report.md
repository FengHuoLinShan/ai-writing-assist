车道：L2　分支：codex/spreadsheet-migration-l2　提交：10d340ae1（实现与测试）＋本报告提交

## 已完成

1. `backend/modules/world/services/worldbuilding/author_migration.py` — 实现三个窄 facade：
   - **plan（只读）**
     - 名称/别名解析顺序：本次条目（文件内 name 索引，重复名 → `conflict(duplicate_in_file)`）→
       `EntityContextService.find_working_entities_by_names`（一次批量，名称或别名命中）→
       `find_exact_identity_candidates`（字面名称、保留歧义；按唯一名称 memo 缓存）→
       `EntityDedupService.find_similar_entities`（仅对无精确命中的名字召回相似）。
     - 动作判定表全部落地：canonical 同名同类型 → `existing_ref` / `fill_empty`（只补空字段）；
       同名 candidate → 预检 `require_fresh_understanding_source`，不新鲜 → `conflict(stale_candidate)`，
       通过 → `adopt_existing`（promote 后补空）；pending 兼容影子 → `needs_review(compatibility_shadow)`；
       相似名/同名不同类型 → `similar_name`（`decision=different_object` 后 create）；
       别名与其他对象重名（DB 名称/别名或文件内其他条目名）→ `alias_collision`；
       字段非空且不同 → `conflict`，`hidden_truth` 冲突且 `decision=append_note` → 追加。
       同名不同类型的 canonical 对象也进入 `similar` 列表交作者裁决。
     - 关系：`relation_kind` 解析顺序 = 作者覆盖 → `suggest_relation_type`/`default_relation_kind`
       （目录同义词归一化，`盟友`→`ally_of`）→ 本地关键词兜底（见"契约偏离"）；
       文件内按（源,目标,类型）去重、对称关系视同一条，但 conflict 行不折叠（保证冲突可见）；
       已有 canonical 边：描述空 → `relation_fill`，相同/未提供 → `existing_ref`，不同 →
       `conflict(description_conflict)`；已有 candidate 边 → `conflict(candidate_edge_exists)`；
       端点缺失/歧义/指向被阻断条目/自环 → `conflict(endpoint_missing|endpoint_ambiguous|endpoint_item_blocked|self_loop)`；
       不对 canonical 边调 `create_or_merge_relation`（新建走 `EntityRelationService.create`）。
     - fingerprint = `stable_hash({"targets": sorted([id, updated_at_iso]), "items": plan items})`，
       targets 覆盖身份命中目标与关系解析到既有实体的端点，不含新实体 id。
   - **apply**：`require_active_project_exclusive` 行锁下重新 `_compose_plan` 并比对
     `expected_fingerprint`（不符 → `ConflictError(code="migration_preview_stale")`，零写入）；
     门禁一次性 `require_legacy_canon_write_allowed`（policy 生效 → 原 `required_validation` 错误，什么都不写）；
     新实体 `WorldEntityService.create(..., status="canonical", created_by="spreadsheet_migration",
     approved_by=authorized_by, force_create=True, _validation_prechecked=True)`；
     `content_json._meta = {source, spreadsheet_migration:{migration_id, source_ref, source_hash,
     authorized_by, applied_at}}`；canonical 人物经 create/promote 自动 scaffold Character 后用
     `CharacterService.update` 只补空人物字段；别名走 `EntityAliasService.create_alias(
     source="spreadsheet_migration", status="confirmed", reviewed_by=authorized_by,
     _validation_prechecked=True)`；`author_notes` 以 `【表格·列名】值` 追加 hidden_truth；
     同名对象只补空、冲突项不写；回执按 `WorldMigrationReceipt`（before 只存被改字段原值，
     alias 变更的 before 存 content_json 原值用于逆恢复；after_hash 用 `stable_hash(state)`，
     按每条变更写入后即时计算，保证逆序回滚可比对）；只 flush 不 commit，DB 异常向上传播。
   - **rollback**：`require_active_project_exclusive` → 回执条目转 dict 后经
     `reverse_applied_changes` 逆序处理；当前状态 hash == after_hash 时软废弃
     （create/relation_create）或恢复 before（fill/promote/alias），否则保留
     `modified_after_migration`；被外部关系、人物/事件扩展或世界书引用保留 `referenced`；
     回滚 CoreEntity/Character 前写 `EntityRevision` 快照（reason=spreadsheet_migration_rollback），
     回滚后逐实体 `mark_asset_context_changed` + `request_entity_activity_reannotation` +
     `mark_synopsis_source_changed`；`dry_run` 只判定不写（`reverted` 表示将会回滚）。
2. `backend/modules/world/services/worldbuilding/applied_change_reversal.py`（新增）— 通用逆序回滚
   helper：`entity_state` / `relation_state` / `character_state` 与 `reverse_applied_changes`
   （支持 after 字典比对或 after_hash 比对、dry_run、referenced/modified 原因区分、
   dry_run 下排除"本次将回滚的关系"避免误判被引用）。
3. `backend/modules/world/services/worldbuilding/focused_adoption.py` — `rollback` 的逆序循环抽到
   新 helper，`entity_state`/`relation_state` 以再导出形式保留原导入路径
   （`adoption_package_service` 与测试仍从本文件导入），行为不变；focused 回滚测试全绿。
4. `backend/modules/world/tests/test_author_migration.py` — 24 个用例，覆盖计划 §4 L2「测试」全部场景。

## 改动文件

全部在本车道独占清单内：上述 4 个文件。未触碰 contracts.py、facade.py、L0 冻结契约与其他车道文件。

## 契约偏离

无（L0 契约与 facade 签名零修改）。以下为实现层决定，请集成者知悉：

1. **L1 `guess_relation_kind` 依赖**：按任务书推荐采用本地等价兜底（`_guess_relation_kind_local`，
   关键词表照抄计划 §4 L1），解析顺序：作者覆盖 → review_queue 目录 → 本地关键词/双人物兜底
   （兜底结果 `relation_kind_guessed=True`，目录与作者覆盖为 False）。L1 合入后可改为直调
   `imports.spreadsheet_migration.synonyms.guess_relation_kind`，语义一致。
2. **关系类型归一化**：目录同义词在 plan/apply 内归一（`盟友`→`ally_of`）后再比对既有边与建边，
   未命中目录保留作者原文；这与「详细类型原值不被改写」不冲突（那条约束针对既有 review 候选）。
3. **`fill_empty` 的 fills 伪字段**：对既有对象追加别名时 fills 里会出现 `aliases`，人物字段以
   字段名出现在 fills；L4/L6 的 field_label 映射需覆盖 `aliases` 与 11 个人物字段名。
4. **receipt 的 before**：`append_note` 变更的 before 存旧 hidden_truth、alias 变更存旧 content_json
   （通常只含 `_meta`），是逆恢复所需的最小原值；其余 fill 只存空值，promote 只存 `status`。
   人物 scaffold（`ensure_for_core_entity` 补建的 Character 行）不进回执，回滚后保留 scaffold。
5. **别名经 create_alias 逐条写入**（含元数据与审计）；每次 canonical 建实体/别名都会触发
   synopsis 失效与 reannotation 请求，这是计划 §6 已列的批量性能风险点，L8 实测 1000 行后决定
   是否加批量通道。`find_exact_identity_candidates` 按唯一名称 memo 调用（每名称一次全量 alias
   source 扫描），大项目下可能仍偏慢，L8 一并实测。
6. **新增 reason_code 词汇**（L4 映射文案用）：`duplicate_in_file`、`target_not_found`、
   `ambiguous_identity`、`field_conflict`、`alias_collision`、`similar_name`、
   `compatibility_shadow`、`stale_candidate`、`endpoint_missing`、`endpoint_ambiguous`、
   `endpoint_item_blocked`、`endpoint_item_unknown`、`self_loop`、`duplicate`、
   `candidate_edge_exists`、`description_conflict`、`modified_after_migration`、`referenced`。
7. **循环 import**：world facade 模块级导入 author_migration，因此
   `modules.project.facade` 在三个函数内 lazy import（与 worldbuilding_facade 对 focused_adoption
   的处理方式一致）。

## 测试

- `make test TESTS="modules/world/tests/test_author_migration.py"` — 24 passed。
- `make test TESTS="modules/world/tests" ARGS="-k 'focused or adoption'"`
  （Makefile ARGS 用法在本仓不通，等价执行 `uv run --project backend pytest
  backend/modules/world/tests -k "focused or adoption"`）— 40 passed。
- 回归扩大：`modules/world/tests` 全量 1066 passed；`tests/unit/test_facade_public_api.py` 5 passed；
  `modules/imports/tests` 720 passed（stub 消费方不受影响）。
- `make lint` 通过。
- 未运行：`make docs-check`（本车道不改公共契约/文档，收尾门禁留给集成者统一跑）；
  PG 专属并发用例属 L8。

## 文档要点（供 L7b）

- 表格迁移 world 落库走 `world.facade.plan/apply/rollback_author_migration_world` 窄 seam，
  不复用 adoption package、不走 CreationSuggestion；新实体直接 canonical，带
  `spreadsheet_migration` 来源 `_meta`；同名只补空、冲突/相似/影子/别名碰撞不落地。
- `applied_change_reversal.py` 是 focused 补全与表格迁移共用的回执逆序回滚 helper；
  migration 回滚区分 `modified_after_migration` 与 `referenced` 两种保留原因。
- `EntityRelationService.update` 无 `_validation_prechecked` 参数（canonical 边内部会再查一次
  policy 门禁）；migration 在 apply 前已一次性门禁且持项目排他锁，语义不受影响，若后续要严格
  "只查一次"需给该 service 加参数（属他人文件，未改）。

## 风险与待决

1. 批量性能（见偏离 5）：1500 实体 + 3000 关系的 apply 会产生大量逐条
   reannotation/synopsis 失效与 per-name 解析扫描，等 L8 的 1000 行计时裁定是否加批量标志。
2. `similar_name` 依赖 `find_similar_entities`（PG 用 pg_trgm、SQLite 回退 ILIKE contains），
   阈值行为在两端可能不同；L8 真实文件验收时留意 SQLite/PG 差异。
3. L4 组装 request 时需保证 `source_ref/source_hash` 与行绑定（回执 `_meta` 直接透传）；
   `use_existing` 必须传同项目已采用/候选对象 id，否则 plan 报 `target_not_found`。
4. L1 合入后建议把本地 kind 兜底切换为 `synonyms.guess_relation_kind`（偏离 1），避免两份关键词表漂移。
