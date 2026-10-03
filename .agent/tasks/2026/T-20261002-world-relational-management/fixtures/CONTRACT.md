# 世界对象关系分组 — G0 共享契约（固定）

基线 SHA：`0d555c463f2010b9206a51b3a838ce0a2e9d4fb8`（origin/main）
主 Agent 单一拥有：`api.py`、`schemas.py`、`relation_group_views.py`、`services/common.py` 指纹入口、`frontend-console/api.js`、Makefile。G0 已落盘上述内容；A/B/C 不得并行写入这些文件，发现合同问题交主 Agent 修订。

## 已固定的共享实现（G0 完成，勿回退）

1. `backend/modules/world/services/worldbuilding/relation_group_views.py`
   - `PRESET_VIEWS`：affiliation / location / possessions / event 四个预设（组类型、成员类型、匹配规则 (relation_type, group_side)、默认添加三元组）。
   - `resolve_group_view(group_view, *, group_type, member_type, relation_type, group_side) -> ResolvedGroupView`：预设忽略自定义覆盖；custom 要求 group_type + relation_type + group_side（member_type 可选）。非法时抛 `RelationViewError`（API 层映射 422）。
   - `preset_view_payloads() -> list[dict]`：响应 `views` 字段负载。
2. `backend/modules/world/services/common.py`
   - `entity_relation_execution_snapshot(relation) -> dict`：**唯一**执行快照字段清单（读取端与写入端重验共用）。
   - `entity_relation_execution_fingerprint(relation) -> str`：单条关系指纹。
   - `EntityRelationService._relation_execution_snapshot` 已改为委托上述函数。
3. `backend/modules/world/schemas.py`
   - `WorldLibraryItemResponse.relation_refs: list[WorldLibraryRelationRef]`（默认空，非分组请求维持原行为）。
   - `WorldLibraryRelationRef {relation: EntityRelationResponse, execution_fingerprint: str(64)}`。
   - `WorldRelationGroupListResponse {views, items, total, unlinked_total, skip, limit}`；`WorldRelationGroupItem {id, name, entity_type, member_count}`；`WorldRelationGroupViewInfo`。
   - `WorldRelationMembershipBatchRequest`（`extra="forbid"`；`confirmed: Literal[True]`；member_ids 1–50 去重；add 拒绝 relation_refs / remove 必须携带；custom add 必须显式 relation_type+relation_kind+group_side）。
   - `WorldRelationMembershipBatchResponse {added_count, reused_count, removed_count, affected_relation_ids}`。
   - `EntityRelationReviewEditRequest.expected_execution_fingerprint: str|None`（可选 CAS 前置）。
4. `frontend-console/api.js`
   - `world.listRelationGroups(params)` → GET `/world/library/relation-groups`
   - `world.applyRelationMembershipBatch(payload, novelId)` → POST `/world/relations/membership-batch?novel_id=`
5. `Makefile`：`BACKEND_POSTGRESQL_CRITICAL_TESTS` 已追加 `tests/e2e/test_world_relation_membership_concurrency.py`（B 必须创建该文件）。

## 服务层方法合同（A/B 实现签名，勿改）

### A：WorldLibraryService（world_library_service.py）

```python
async def list_relation_groups(
    self, db, novel_id: str, *,
    group_view: str,
    group_type: str | None = None,       # custom 配置
    member_type: str | None = None,
    relation_type: str | None = None,
    group_side: str | None = None,
    q: str | None = None,                # 组名/别名搜索
    skip: int = 0, limit: int = 50,
) -> WorldRelationGroupListResponse
```

`list_library` 追加可选参数：`group_view, group_id, group_unlinked, group_type, member_type, relation_type, group_side`。
- 选组（group_view+group_id）与未关联（group_view+group_unlinked=true）互斥，同给 422。
- 分组模式：kind 强制 entity、仅 active CoreEntity（canonical 组+成员）；复用既有 q/sort/skip/limit 语义（作用域在成员）。
- 每个成员页 item 装配 `relation_refs`：该视角匹配的全部 canonical 关系 + `entity_relation_execution_fingerprint(relation)`。候选/历史(deprecated)/归档端点不构成成员。
- `member_count` 按对象去重（多关系同对象只计 1）；`total` 为组数；`unlinked_total` 为本视角成员类型范围内、在本视角全部有效分组中都没有匹配关系的去重 active 对象数。
- 聚合、排序、分页在 SQL 中执行；关系装配仅对当前页批量（避免 N+1）。
- 分组查询与两端 join 都必须带 novel_id 与状态条件；跨项目/跨 owner 由 API 层鉴权保证。

### B：EntityRelationService（entity_relation_service.py）

```python
async def membership_batch(
    self, db, novel_id: str, data: WorldRelationMembershipBatchRequest
) -> WorldRelationMembershipBatchResponse
```

行为合同（TASK.md §3.3/§4.2 全文为准）：
- add：解析视角 → 每成员建立 `member →(relation_type, kind)→ group`（group_side 决定端序；side=target 时 source=member,target=group；side=source 时 source=group,target=member）。已存在同端点同类型 canonical 直接复用（reused，不改描述/证据/强度）；匹配候选（`find_duplicate_relation` 命中 status=candidate）→ 拒绝整批 `409 relation_exists_as_candidate`。canonical 校验门禁沿用 `_require_legacy_canon_write_allowed`（409 required_validation）。
- remove：按 `relation_refs` 精确清单；服务端核对每条属于给定组、成员及视角，缺/多/越界 → 422 或 404；指纹不匹配 → `409 stale_execution`。置 status=deprecated，保留行与 review_meta（before/after 审计）。重复移出（已 deprecated）按过期指纹处理（409 stale_execution）。
- 每批一个事务：先按稳定 UUID 顺序锁对象与关系（entity 先锁，参考 `_prelock_review_batch`），锁定后重验；任何失败撤回整批。
- 成功后：canonical 变更触发 `_mark_synopsis_changed`；两端 `_mark_endpoint_context_changed`（reason 用 "relation_membership_batch"）。
- `EntityRelationService.review_edit` 扩展：`data.expected_execution_fingerprint` 存在时先锁行（with_for_update）校验指纹再更新；不匹配 409 stale_execution。旧调用不传字段行为不变。
- 新关系为作者手动确认：review_meta 记 `reviewed_by="manual"`、`reviewed_from="world_relation_membership_batch"`、before/after 快照；不附会原文来源（无 quote/scene 证据）。

### C：前端（详见 TASK.md §4.3）

URL 参数（worldCardFiltersFromQuery / worldCardQuery 完整编解码）：
`group_view`、`group_id`、`group_unlinked=1`、`group_type`、`member_type`、`relation_type`、`group_side`。
`usesServerLibrary` 识别关系视角；分组失败不回退扁平列表（区别于现状）。

## 错误码（固定）

| 场景 | 状态码 / code |
|---|---|
| 参数/视角配置无效 | 422（Pydantic / `RelationViewError` 映射） |
| 对象/关系不存在或不属于该组 | 404 not_found |
| 过期指纹（remove/review-edit） | 409 stale_execution |
| 候选冲突（add 命中 candidate） | 409 relation_exists_as_candidate |
| 校验策略拒绝 | 409 required_validation |
| 事务失败 | 500，无部分写入 |

## 合成样例

同目录 `relation-groups-response.json`（GET relation-groups）、`library-grouped-response.json`（GET library 分组模式）、`membership-batch-samples.json`（add/remove 成功与各错误）。C 先用这些样例实现交互与 Vitest；G1 撤替身接真实 API。
