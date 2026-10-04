# 阶段 0 派工说明 — P1 / P2 / P3（G0 落定版）

依据：TASK.md §6（合同）、§7（分工）。G0 已完成，本文把 §6.3 签名逐字固定，
并补充 G0 落定的事实。子代理执行时逐字引用本文，不自行改合同；发现合同问题先交主 Agent 修订。

通用约束：
- 工作区：worktree `../ai-writing-assist-weh`，分支 `codex/world-edit-history`。
- 所有路由经 `ActiveNovelIdQuery`（api.py:393 附近）校验 owner；查询两端都带 `novel_id`。
- 测试替身一律 `patch.object(..., autospec=True)`；生产代码不出现 Mock。
- 包之间不得改同一个文件；跨包合同问题上报主 Agent。

---

## G0 已落定的事实（P1–P3 直接依赖，勿重复实现、勿回退）

1. 迁移 `20261005_world_revision_metadata` 已合入：
   - `entity_revisions`、`world_bible_page_revisions`、`map_atlas_revisions` 均已加
     `writing_chapter_index`（Integer NULL，CHECK 为空或 ≥0）、`change_summary`（JSON NULL）、
     复合索引 `ix_<table>_novel_created (novel_id, created_at, id)`。
   - `entity_revisions` 的两列**可以 UPDATE**（该表无触发器），P1 的
     `record_change_summary` 直接 UPDATE。
   - `world_bible_page_revisions` 表有 BEFORE UPDATE OR DELETE 不可变触发器，
     两列**只在插入时写入**，事后不可改。
   - `map_atlas_revisions` 的 `protect_map_revision_content` 触发器已重建，**两列受内容保护**，
     只在插入时写入。
   - 新表 `world_revision_notes`（ORM `WorldRevisionNote`，models/core.py）。
   - `entity_revisions.revision_reason` 的 DDL 注释已修正为实际取值清单。
2. `backend/modules/world/revision_history_schemas.py` 已存在（§6.2 全量）：
   `RevisionTargetKind`、`EntityRevisionField`、`EntityRevisionSnapshotView`、
   `EntityRevisionItem`、`EntityRevisionListResponse`（新版，五字段）、
   `EntityRevisionRollbackRequest`、`RevisionNoteUpdateRequest`（strip→max 500，空串=删除）、
   `RevisionNoteResponse`、`WorldChangeHistoryItem`、`WorldChangeHistoryResponse`。
   注意：`schemas.py` 里的旧版 `EntityRevisionListResponse`（仅 items/total）**仍在**，
   `api.py` 仍引用它；P2 接线时删除旧定义并统一改引新模块。
3. `schemas.py` 的 `WorldBiblePageRevisionResponse` 已加可选字段
   `writing_chapter_index` / `change_note` / `changed_fields`；
   `map_structure_schemas.py` 的 `MapRevisionResponse` 已加 `writing_chapter_index` / `change_note`。
4. `backend/modules/world/services/revision_notes.py` 已实现：
   `load_revision_notes(db, novel_id, kind, ids) -> dict[uuid.UUID, str]`、
   `set_revision_note(db, novel_id, kind, revision_id, note) -> RevisionNoteResponse`。
   语义：跨作品 404；地图候选（status≠saved）**409**（此为 §6.4 的二选一裁定，README 由 G1 记录）；
   超长 422；空串删除；重复写幂等。测试 `test_revision_notes.py` 8 例已过。
5. 前端 `api.js` 四方法已就位：`getEntityRevisions(id, novelId, { skip, limit })`
   （签名已从位置参数改为对象，`WorldEntityDetail.vue:30` 调用点已同步）、
   `rollbackEntityToRevision(entityId, { revisionId, expectedUpdatedAt }, novelId)`、
   `setRevisionNote({ targetKind, revisionId, note }, novelId)`、
   `listWorldChangeHistory(novelId, { kinds, cursor, limit })`；
   `apiContracts.js` 已登记四条契约；`tests/setup.js` 已加 mock。
6. 备注 `note` 列的语义：strip 后 ≤500 字；`WorldRevisionNote.note` 非空列，空串等价无备注。

---

## §6.3 函数签名（逐字合同）

```python
# backend/modules/writing/facade.py（经 repositories/services 实现；按章节号倒序分批找第一章有实质正文的章节）
async def get_latest_effective_chapter_index(db, novel_id: str) -> int  # 0 = 尚无正文

# backend/modules/world/services/common.py（按需导入 writing facade）
async def current_writing_chapter_index(db, novel_id) -> int

# entity_revision_service.py
EntityRevisionService.create_snapshot(..., writing_chapter_index=UNSET) -> dict  # 含 revision_id；UNSET 时自行查询
EntityRevisionService.record_change_summary(db, revision_id, fields, restored_from_revision_id=None) -> None
EntityRevisionService.get_revisions(db, entity_id, novel_id, skip, limit) -> EntityRevisionListResponse

# entity_service.py
WorldEntityService.update(..., _revision_reason=..., _restored_from_revision_id=None, _clear_fields=frozenset())
WorldEntityService.rollback_to_revision(db, entity_id, revision_id, *, novel_id, expected_updated_at) -> CoreEntityResponse

# backend/modules/world/services/revision_notes.py（G0 已交付）
async def load_revision_notes(db, novel_id, kind, ids) -> dict[uuid.UUID, str]
async def set_revision_note(db, novel_id, kind, revision_id, note) -> RevisionNoteResponse

# backend/modules/world/services/revision_history_service.py（新，P2）
WorldChangeHistoryService.list(db, *, novel_id, kinds, cursor, limit) -> WorldChangeHistoryResponse
```

签名约定：`_` 开头参数只在内部使用，不进公开请求 schema；`_clear_fields` 只允许
`models/core.py` 的三个可空文本列（summary / public_info / hidden_truth）。

`event_facade.py` 兼容：`get_entity_revisions` 继续返回 dict；
`rollback_to_revision` 改调新方法，`expected_updated_at` 必填关键字参数；
同步修改 `backend/tests/unit/test_facade_public_api.py:81`。

批量调用方在循环前只查一次写作进度再传入（不用会话级缓存）：
`adoption_package_service.py:1041-1048`、`applied_change_reversal.py:229/237`、
`focused_adoption.py:563`、`author_migration.py:1210`、`review_resolution.py:468`。

---

## P1：后端写入路径

写入范围：
- writing 模块：`repositories.py`、`services.py`、`facade.py`
- world 模块：`services/common.py`、`services/core/entity_revision_service.py`、
  `services/core/entity_service.py`、`services/worldbuilding/world_bible_lifecycle_service.py`、
  `map_structure_service.py`、上述五个批量调用方、`event_facade.py`
- 对应单元测试和模块测试

任务：
1. `get_latest_effective_chapter_index`：没有正文返回 0；全空白稿件不算正文；返回最大章节号。
2. `current_writing_chapter_index`：按需导入 writing facade（先例 `world_impact_service.py:80`）。
3. `create_snapshot` 落库 `writing_chapter_index`；保存时计算并 `record_change_summary` 改动字段
   （别名从 content_json.aliases 单独拆为 `aliases`；比较忽略内部来源标记；无改动返回空）。
4. `update()` 增加内部参数 `_revision_reason/_restored_from_revision_id/_clear_fields`；
   去掉手动编辑前快照的 `try/except`（快照失败整体失败）；
   `promote()` 去掉尽力而为、reason 改 `manual_promote`；`delete()` 保持尽力而为（§5.5）。
5. 新 `WorldEntityService.rollback_to_revision`（走 `update()`，全部编辑检查与失效链照常；
   不恢复 status；快照去内部来源标记后合并当前来源标记；空字段清空只限三个可空列）；
   删除 `entity_revision_service.py` 旧 `rollback_to_revision`。
6. `get_revisions` 改强类型输出（新 `EntityRevisionListResponse`），`created_at` 带 ISO 时间，
   SQLite 无时区值补 UTC；批量读备注填 `change_note`；`changed_fields` 缺保存记录时读相邻一条推算并标
   `changed_fields_exact=False`；`can_restore` 按实体当前状态（deprecated 不给恢复）。
7. 页面发布插入时写 `writing_chapter_index`；页面/地图列表读取时计算差异、批量带备注。

测试（§8）：`test_latest_effective_chapter_index.py`（writing 模块新）、
`test_entity_revision_history.py`、`test_entity_rollback_by_revision.py`、
`test_entity_snapshot_fail_closed.py`；同步改 `test_world_services_revision_event_helpers.py`、
`test_event_facade.py`；扩展 `test_world_bible_v2.py`、`test_map_structure.py`。

## P2：后端读取与路由

写入范围：`services/revision_history_service.py`（新）、`api.py`、`map_atlas_api.py`；
测试 `test_entity_rollback_by_revision.py`（路由断言部分）、`test_world_change_history.py`。

- 时间线：SQL 内三段 `UNION ALL` + LEFT JOIN 备注表；按 `(created_at, kind, id)` 倒序游标；
  游标为不透明 base64 JSON，坏游标 422；`limit` 1–50 默认 30；地图只取 saved 且无 confirmation_id 的行；
  不做逐条查询。
- 路由（§6.4）：`GET /entities/{id}/revisions` 响应改新 `EntityRevisionListResponse`
  （此时从 schemas.py 删除旧定义并统一改引）；`POST /entities/{id}/rollback-by-revision`
  请求体 `EntityRevisionRollbackRequest`（删查询参数）；`PUT /revision-notes`；
  `GET /change-history`。404/409/422 语义照 §6.4。
- 依赖顺序：时间线与备注路由只依赖 G0，可先做；回滚路由与实体历史路由在 P1 合入后接线。

## P3：前端

写入范围与任务照 §7 P3 表执行。G0 已提供：api.js 四方法 + 契约 + mock。
P3 新增 `shared/revisionHistory.js`（§6.5 原因词典）、`VersionTextDiff.vue`、
`WorldEntityRevisionHistory.vue`、`worldBibleHistory.js`、`WorldChangeHistory.vue`；
迁移 `versionDiff.js` 到 shared/；改 `useWorldBible.js`（拆后 <3000 行）、
`VersionHistoryDialog.vue`、`WorldEntityDetail.vue`（内联历史换组件）、
`worldEntityHelpers.js`（formatBatchTime 调共享函数）、`MapStructureEditor.vue`、
`WorldView.vue`、`worldIsland.js`（318-341 深链）、`worldSession.js` 及对应 Vitest。
禁止动态 v-html、禁 bridge 之外访问 API/全局。
