# L3 交接报告（story 落库）

车道：L3　分支：`codex/spreadsheet-migration-l3`　提交：`afae44dc5`

## 已完成

- `story/outline_state/author_migration.py`：实现 `plan_author_migration_structures` /
  `apply_author_migration_structures` / `rollback_author_migration_structures` 三个
  facade（L0 冻结签名未动）。
  - 映射：arc→OutlineArc；thread→PlotThread（thread_type 仅认 main/sub/background，
    另含少量中英文同义词归一，其余不合法一律 `sub`，缺省 `sub`）；foreshadowing→
    ForeshadowingPlan（fields 里的 seed_chapter/payoff_chapter/reinforce_chapters 为
    字符串，按数字解析，缺失回落 item.chapter_start/chapter_end）。
  - chapter_plan 四分支：active Scene（candidate/draft/canonical）经 chapter_ids、
    scene_chunks 或 structure_meta.planned_chapter_range 覆盖 → existing_ref；未写章节
    → planned Scene（scene_chunks=[]、chapter_ids=[]、planning_state="planned" +
    planned_chapter_range，形状同 P20 `_apply_scenes`）；已写章节 + reference_only →
    不写；已写章节 + link_scene → 建 Scene 并写 chapter_ids（字符串章节号，
    SceneChapterLink 由 SceneRepository.create 自动生成）。"已写章节"用
    `modules.writing.facade.list_chapter_indices`（草稿存在的章节），与
    outline_state 内既有跨模块用法一致。
  - 来源标记：Scene.source="spreadsheet_migration"；provenance_meta（Scene 为
    structure_meta）= {source, migration_id, source_refs, authorized_by, adopted_at}；
    全部 status="canonical"（各 Create schema 允许）。fill 只在既有 meta 上追加
    `spreadsheet_migration_fill` 子键，不覆盖作者已有 provenance。
  - 同名与重叠：同名 thread/arc/伏笔按列逐个比较，空值补、等值跳过、非空且不同
    conflict（任一冲突则整条不落库）；卷与既有其他卷或本批次已接受卷的章节范围
    重叠 → conflict(arc_range_overlap)；同一请求内同名 → conflict
    (duplicate_in_migration)。
  - 总纲：经 `StoryOutlineService.create_revision` 写入，outline_markdown 逐字保留；
    creative_core 要求 premise/tone_and_reader_promise/story_engine 非空
    （ending_direction 可选），缺失 → 合成 conflict item（见契约偏离说明）+
    outline_action="skip"；create_if_missing 仅无 head 时创建；replace 以当前 head
    为 base；skip 不写。revision 的 source 只能是 "manual"（schema Literal），迁移
    来源记在 provenance（client_ref="spreadsheet-migration"、
    source_refs=["migration:<id>"]），幂等键 `spreadsheet-migration:<migration_id>`。
  - 指纹：stable_hash({request 序列化, 每条 item 的 action/target_id/fills/conflicts/
    reason_code + 已存在目标的 (id, updated_at) 戳, outline_action + 当前 head 修订
    戳})。不含新实体 id（有测试钉住 entity_refs None 与有值指纹一致）。
  - apply：先重算 plan 比对 expected_fingerprint，不符抛
    `ConflictError(code="migration_preview_stale")` 且零写入；创建 Scene 前取
    scene_order advisory lock（PG）；回执 `StoryMigrationReceipt`
    （applied_changes 按 world contracts 的 MigrationAppliedChange，kind 为
    arc/thread/foreshadowing/scene，outline_change={revision_id, base_revision_id}）；
    全程只 flush。
  - rollback：按回执逆序；当前资产快照 hash 与 after_hash 一致才处理（create →
    status="deprecated" + rolled_back_at，保留历史不硬删；fill_empty → 恢复
    before），否则保留 reason=modified_after_migration；create 额外校验来源标记。
    总纲：head 仍指向本次修订且有 base → apply_revision(base)（幂等键
    `spreadsheet-migration-rollback:<revision_id>`）；无 base（首个修订）→
    `clear_head_if_revision` 清 head 指针、修订留历史；head 已移动 → 保留
    (outline_superseded)。dry_run 只判定不写。
- `story/outline_state/story_outline_service.py`：新增 `clear_head_if_revision`
  （先无锁读判 head 归属，再锁内复核，仅当 head 仍指向指定修订时置空
  current_revision_id 并发 structure change）；`get_current` 原本就能处理无 head /
  无 current_revision_id（返回空响应），未改动并有测试覆盖。
- `story/tests/test_author_migration_story.py`：23 个用例。

## 改动文件

全部在本车道独占清单内：

- `backend/modules/story/outline_state/author_migration.py`
- `backend/modules/story/outline_state/story_outline_service.py`
- `backend/modules/story/tests/test_author_migration_story.py`

## 契约偏离

无（未改任何 L0 冻结契约文件）。两个需要集成者知悉的实现裁定：

1. **outline 冲突的暴露方式**：`StoryMigrationPlan` 没有 outline 级 conflicts 字段，
   creative_core 缺失 / outline_markdown 为空时用合成 item
   `item_key="__outline__"`（模块导出 `OUTLINE_ITEM_KEY`）、action="conflict"、
   reason_code="outline_core_missing"（或 "outline_markdown_missing"）表达，同时
   outline_action="skip" 保证 apply 零写入。回滚结果里总纲的 reverted/kept 条目也用
   该键。L4 渲染预览/回滚文案时需把 `__outline__` 标记为"总纲"。
2. **fills 列名即 DB 列名**（如 planned_payoff_chapter、start_chapter），L4 需要时
   自行映射为作者语言标签。

## 测试

- `make test TESTS="modules/story/tests/test_author_migration_story.py"`：23 passed。
  （Makefile 先 `cd backend`，任务模板里的 `backend/modules/...` 前缀路径需去掉
  `backend/` 才能收集。）
- `make test TESTS="modules/story"`（含 story/tests 与 story/outline_state/tests 全量）：
  584 passed, 12 skipped。
- `make test TESTS="tests/unit/test_facade_public_api.py"`：5 passed（L0 公共面回归）。
- `make lint`：通过。
- `make docs-check`：**在 L0 基线提交上即失败**（`import_migration_sessions` 未录入
  `docs/01_数据库设计.md`，属 L0/L7b 文档事项），与本车道改动无关（已用 stash 验证）。
- 未运行：PostgreSQL 专项（无环境，归 L8）；`make test-ci` 全量（集成者合入时跑）。

## 文档要点（供 L7b）

- chapter_plan 的"已写章节"判定 = writing facade 的草稿章节索引；link_scene 只关联
  范围内已写章节（字符串章节号），planned_chapter_range 记录完整范围。
- 迁移 Scene 的 structure_meta 键：source/migration_id/source_refs/authorized_by/
  adopted_at + planning_state + planned_chapter_range + related_entity_ids；fill 类
  变更在 provenance_meta.spreadsheet_migration_fill 追加，回滚写入 rolled_back_at /
  spreadsheet_migration_rolled_back_at。
- 回滚语义：结构资产废弃（deprecated）而非删除；总纲回滚会追加一个 restored 修订
  （有 base 时）或清空 head 指针（首个修订时）。
- 指纹含已存在目标与 head 修订的 updated_at：预览后任何被匹配资产或总纲 head 的
  变化都会使 apply 报 migration_preview_stale（保守失败关闭）。

## 风险与待决

- plan 的 `entity_refs` 参数对计划输出无影响（输出与指纹均不含新实体 id），保留仅为
  对齐冻结签名；实体 id 仅在 apply 经 entity_ids 参与写入（related_entity_ids /
  pov_character_id）。`related_entity_keys` 中不在 refs 的键按已有 entity_id（UUID）
  理解，无法解析则丢弃；对应 world 条目被跳过时该引用静默不落。
- 匹配到的同名资产不合并 related_entity_ids（避免与指纹/预览语义分叉）；关联实体只
  附加在新建资产上。若产品需要"同名补关联"，需 L4 在预览层处理或扩契约。
- apply 的指纹校验与写入之间没有跨 world/story 的全项目锁（与 world 车道同粒度），
  并发窗口由 L8 的 PG 用例验证。
- `SceneCreate.chapter_ids` 是 list[str]，已写章节以字符串写入，`chapter_indices_for_scene`
  等消费方按 int 解析，与既有数据形状一致。
- L4 需要知道：合成键 `__outline__`、fills 列名映射、回滚结果中总纲条目的键。
