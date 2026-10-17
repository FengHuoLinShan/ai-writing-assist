# 第 6 批：对象档案

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：ADR-0039（对象档案三层与接口）、`docs/plans/2026-10-15-world-object-dossier-c0-mapping.md`、
`backend/modules/evolution/README.md`“对象简报的台账只读投影”。

## 结论

档案的修订、CAS、作者确认和视角过滤整体扎实：条目写入只经 World 修订入口，编辑/恢复带
`expected_revision_id` 或 `expected_current_revision_id`，旧人物接口按“值相同不改、值不同收拢为一条作者
条目”工作，Evidence 简报在角色与读者视角下逐层收窄。问题集中在两处：迁移回填的 CoreEntity 三列
（`summary/public_info/hidden_truth`）没有接入档案，导致数据分叉且回填条目无法编辑、导入；Evolution
台账读取在较早截止点会绕过作者后来的拒绝。发现 3 个 P2，均有 strict xfail 回归测试。

## 已审范围

- World：`dossier_service.py` 的 `read`、`create_entry`、`update_entry`、`restore_entry`、
  `sync_character_legacy_field`、`_legacy_value`、`_sync_legacy_storage`、`upsert_template`（CAS 与借用
  面向移除保护）；`dossier_interchange.py` 全文；`assistant_dossier_tools.py`；`api/dossier.py`；
  `dossier_repository.py`；`models/dossier.py` 约束；迁移 `20261015_object_dossier_v2.py` 的回填。
- Evidence：`object_dossier_brief.py` 全文、`assistant_dossier_tools.py`。
- Evolution：`evidence_read.py`、`completed_read_chapters.py`；为核对台账修订语义补读 `ledger.py`
  的修订追加与 `save_ledger_decision`。
- 前端：`WorldObjectDossierEditor.vue` 的编辑与恢复入口（只为判断作者可见影响）。

## 确认无问题

- API 统一使用 world 共享 router 的 `ActiveNovelIdQuery`；仓储按 `novel_id + entity_id` 过滤。
- 编辑与恢复：锁实体与条目组，校验当前修订，旧版本保留为 superseded；清除写 `cleared` 修订；
  “无变化”直接返回原条目，不产生修订。模板保存带 `expected_version_number`，仍有活动条目使用的借用
  面向不能移除。
- 旧人物接口：`exclude_unset` 只处理请求中的字段；值相同不改；值不同把同一旧字段下全部有效条目标为
  过时并追加一条作者修订；显式 `null` 写清除修订；`expected_updated_at` 仍走 409。读取方
  （`_legacy_response`、`get_characters_context`、去重合并）都读条目汇总值。
- 导入导出：同项目来源逐条重验修订身份与载荷 hash；跨项目来源不读取来源项目，证据只存入导入
  元数据，项目面向、锚点、Story 字段必须显式映射；apply 重算预览 hash 并拒绝未处理冲突。
- 助手工具：World 写操作都是“预览 → 作者确认 → 应用时重新预览比对”；读操作要求作者运行并经
  `ASSISTANT_REQUIRE_OPERATION_TARGETS` 校验对象范围。Evidence 简报工具只读，拒绝把原确认或排除
  范围展开为新简报，Scene 与对象逐个经 `inspect_novel_target` 校验。
- Evidence 简报：读者视角直接不用档案；角色视角要求 Story 返回同一 POV，World 读取限 public 并按
  `visible_fields` 过滤，再要求条目内容与该 POV 已确认事实一致；author_safe 只给 public 条目，且
  指纹只由可见条目计算，不随隐藏条目变化；人物倾向只在作者视角读取，逐条核对来源可见性。
- `completed_read_chapters.py`：只认同一运行、同一冻结来源、成功且已应用的回执；正文 draft 与 hash
  未变、各 Scene 范围首尾相接才算整章已读，部分阅读、改稿与 shadow 运行均不计入。

## 发现

### B6-F1（P2）实体接口修改概要、公开信息、隐藏真相后，档案仍保留旧值

- 位置：`backend/modules/world/services/core/entity_service.py` 的 `update`（第 472 行起）只写
  `core_entities` 三列，不调用档案服务；迁移 `20261015_object_dossier_v2.py` 第 242–272 行把这三列回填为
  `legacy_import` 条目（`legacy_field_key` 为 `summary/public_info/hidden_truth`）。
- 规格：ADR-0039“兼容”一节与 C0 映射文档要求 `public_info`、`hidden_truth` 分别由公开条目和秘密条目
  汇总而来；作者写入应经档案修订入口。
- 问题：迁移后作者在实体面板改公开信息，实体列变成新值，回填条目仍是有效状态、内容为旧值。档案读取、
  Evidence 对象简报和档案导出都拿到旧值；生成上下文若同时启用对象档案参考，会同时看到新旧两个版本。
  迁移后新建的实体则完全没有这三列对应的条目（档案读取看不到它们）。实体修订恢复、去重合并、表格
  迁移补空等其他写这三列的路径同样不同步。反方向只部分成立：编辑带旧字段键的条目时，
  `_sync_legacy_storage` 把单条内容写回实体列，不是“所有公开条目的汇总”。
- 复现：`modules/world/tests/test_map_series_review_regressions.py` 的
  `test_b6_entity_public_info_edit_keeps_its_dossier_entry_current`，去掉 xfail 后失败在
  `['城门日落关闭'] == ['城门彻夜开放']`。
- 建议方向：实体接口写三列时按旧人物字段的规则写档案修订（值相同不改，值不同收拢为一条作者条目），
  或在读取时由条目汇总、实体列只作兼容投影；两种都需要覆盖恢复、合并、表格迁移等写入路径。

### B6-F2（P2）迁移回填的概要、公开信息、隐藏真相条目不能编辑、清除、恢复或导入

- 位置：回填使用面向键 `overview`、`public_info`、`truth`，这些键不在 `dossier_service.py` 的
  `CORE_FACINGS`（只进了 `CORE_FACING_LABELS`）。`update_entry`（第 2077 行）、`restore_entry` 与它们的
  预览先对 core 面向调用 `_validate_facing`，返回“该对象类型不支持此内核面向”。导入时
  `dossier_interchange.py` 的 `_target_facing` 返回“清单中的内核面向已失效”；即使显式映射到其他面向，
  `_compatibility_target` 里的 `_validate_legacy_field` 也会因 `public_info` 不是登记字段而拒绝，
  没有可用的绕行办法。
- 问题：档案编辑器对每条有效条目都显示“编辑”（`WorldObjectDossierEditor.vue:90`），作者点开回填的
  公开信息条目保存会得到 400，也无法清除。和 B6-F1 叠加时，过期的回填条目在档案里既改不了也删不掉。
  任何迁移前就有概要的对象（多数旧对象）导出的档案清单，导入到同项目或其他项目都会整份被拒。
- 复现：同文件 `test_b6_backfilled_public_info_entry_is_editable_in_the_dossier`（PATCH 返回 400
  “该对象类型不支持此内核面向”）与 `test_b6_manifest_with_backfilled_public_info_can_be_imported`
  （预览返回 400“清单中的内核面向已失效，必须显式映射或停止导入”）。
- 建议方向：把三个回填面向登记为所有对象类型可用的内核面向，并让 `_validate_legacy_field` 接受这三个
  CoreEntity 旧字段；与 B6-F1 一起修。

### B6-F3（P2）较早 Scene 的人物倾向读取绕过作者后来的拒绝或更正

- 位置：`backend/modules/evolution/evidence_read.py` 第 146–175 行按条目取“`scene_index` 不超过截止点的
  最新修订”。台账修订的 `scene_index` 是该修订主张依赖的最大 Scene（`ledger.py` 第 195 行）；作者决定
  修订沿用当时主张的最后 Scene（`save_ledger_decision`，第 209–247 行）。
- 问题：一条倾向先在第 2 场形成（修订 1），后续阅读用第 5 场证据扩展了它（修订 2，scene_index 5），
  作者这时拒绝或更正（修订 3，scene_index 5）。为第 2–4 场生成简报时只能看到修订 1，修订 1 的
  `author_decision` 为空、复核为 supported，于是作者已拒绝的解释重新出现在简报里；更正同理，返回的是
  更正前的旧说法。README 承诺“逐条核验复核/作者决定”。默认配置下对象倾向参考是关闭的，但助手只读
  工具 `evidence.object_dossier_brief.read` 允许 `include_patterns`。
- 复现：`modules/evolution/tests/test_map_series_review_regressions.py` 的
  `test_b6_author_reject_after_extension_applies_at_earlier_cutoff`（真实 DB 写入三条修订），去掉 xfail
  后返回修订 1。
- 建议方向：截止点只决定用哪一版主张和证据，作者决定取条目当前值（`entry.author_decision_json`）；
  被拒绝的条目在所有截止点都不出现，被更正的条目用更正后的说法或直接省略并提示。

## 观察（未定为问题）

- `evidence_read.py` 的台账查询在 SQL 中不按类别和对象过滤，按整个项目取最新 500 条后再在 Python 中
  过滤。长篇项目会很快触发“台账候选超过读取上限”，此后较早 Scene 的倾向会被截掉；截断会显式计入
  省略并标为 partial，所以不是静默丢失。
- 角色视角里 `_dossier_entry_visible` 只比对内容与该 POV 已确认事实的值，不比对字段；但 World 读取
  已按 `visible_fields` 绑定字段键，两层叠加后没有发现越界。
- author_safe 视角给出所有 public 条目，不检查读者是否已在该 Scene 前读到；ADR 只要求秘密条目按揭示
  策略过滤，符合规格。

## 回归测试

- `backend/modules/world/tests/test_map_series_review_regressions.py`：新增 B6-F1、B6-F2（编辑、导入
  两条），共用 `_location_with_backfilled_public_info`，按迁移回填的行结构插入条目。
- `backend/modules/evolution/tests/test_map_series_review_regressions.py`：新增 B6-F3，复用
  `test_evidence_read.py` 的 `_claim` 与 `_ScenePort`，用 monkeypatch 替换来源核验，台账行写入真实
  测试库以覆盖 SQL 排序。
- 验证（2026-10-16，基线 `a479e006b`，在 `backend/` 下运行）：两个回归文件 `20 xfailed`；加
  `--runxfail` 为 `20 failed`，新增 4 条各自失败在上述断言。ruff format/check 通过。
