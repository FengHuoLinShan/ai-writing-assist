# M4 实施契约：状态/包/试改的依赖登记与失效

主计划 [2026-10-06-world-foundation-phase1.md](2026-10-06-world-foundation-phase1.md) §4.3 与工作包 M4。
前置：M2（[状态读契约](2026-10-07-world-state-read-m2-contract.md)）、M3（[检索重构契约](2026-10-07-rp-retrieval-refactor-m1-contract.md)）。

## 1. 范围与原则

本契约只处理**本闭环消费者**（M2 状态投影、Evidence 包、M3 RP 缓存、M5 试改检查）的依赖登记、
失效与复用；不新建第二套失效框架，全部复用各域既有 seam：

- Writing：`hash_text` 全文 sha256（同长度替换必变指纹）；`get_manuscript_source_manifest`
  一次索引查询返回各章最新 draft 的 `{draft_id, chapter_index, version_number, source_hash}`；
  `read_manuscript_range` 读时复验（stale 即 ValidationError）。
- Evolution：稿件保存/采用 hook（`_changed` → `record_writing_source_change` →
  `apply_source_invalidation`）先做确定性物理差异（同字数替换也检出，`compute_source_change`），
  再传播失效：事件 `source_stale=True`（作者确认行豁免）、章快照 `mark_stale_from`、
  checkpoint `supersede_system_from`、稀疏快照 supersede；Scene 重排经
  `apply_scene_reorder_invalidation`（对齐 scene_index 后从最早移动 Scene 起 supersede）。
  重建是懒式的（读路径 ensure）。
- World 复核：`_matches_frozen_inputs` 读时重冻 policy/manifest/dependency/target hash，
  不符即 `_mark_stale`；impact 预览跨域枚举依赖方并显式列 uncovered。
- Collaboration：`dependencies_json` 登记来源快照 + `inspect_cognition_freshness` 读时逐依赖
  经 port 重读比对，返回 current/stale/unsupported/needs_scope_check。
- Evidence：编译 reference_manifest + proof 引用（M3 缓存命中按冻结 ref 完整字段重放复验）；
  索引新鲜度 `request_chapter_index`/`mark_chapter_index_dirty`/`read_chapter_index_fingerprint`。

原则（主计划 §4.3）：

1. 派生成果登记**实际消费的权威输入**；登记语义之外的变更沿既有路径保守扩大，不宣称不受影响。
2. 失效与昂贵重算分开：标记/降级是廉价确定性动作，重建仍走显式或懒式 ensure。
3. 历史与作者确认保留：软 supersede 链、作者行豁免、manual/confirmed 不被机器覆盖——
   本契约不新增任何删除或覆盖路径。
4. 只有来源、范围、解释版本及完整依赖均重新验证的结果才可复用（M3 缓存已按
   M1 契约 §4 实现；本契约把同一标准落到 M2 状态投影）。

## 2. 缺口（为什么需要 M4）

- checkpoint 的 `source_hash` 是**投影链指纹**（上一 checkpoint 指纹 + 本维度 state + refs），
  不指向正文 revision；`get_scene_state_view` 把它计入 fingerprint 但从不与现行输入比对。
  事件驱动失效覆盖了已接线的修改路径（保存/采用/重排/确认），但任何绕过 hook 的变更
  （历史数据、直改库、未来新路径）会让视图**静默供给旧投影**——违反「本闭环无静默旧结果」。
- 世界正典修订（CoreEntity/EntityRelation 等）不传播到 story checkpoint：
  `evolution/invalidation.py` 明确把 world_knowledge/map_atlas 列为 unsupported_consumers。
  这是既有设计决定（观察层记录「当时所见」，世界修订不回写历史），M4 只需把它**显式化**，
  不新增 world→story 自动失效。
- M3 缓存的撤权/归档立即拒绝语义已实现，验收矩阵 A09 的「来源归档/软删→立即拒绝命中」
  需要一条显式测试钉住。

## 3. checkpoint 来源基线（basis）登记

### 3.1 语义

系统行（`source="system_generated"` 且 `confirmed=False`）在**构建时**（ensure/rebuild 的
`replace_system` 新建行路径）记录环境基线 `basis_json`：

```json
{
  "contract_version": 2,
  "manuscript": {"<chapter_index>": "<source_hash>"},
  "scenes": [["<scene_id>", <scene_index>, [<chapter_ids>]], ...]
}
```

- `manuscript`：重放窗口内各 Scene 的 `chapter_ids` 并集（≤ 本 Scene cutoff）到
  `get_manuscript_source_manifest` 的最新指纹切片。写方向 story→writing 是 ADR-0031
  既有合法方向（函数内只读 facade 导入）。
- `scenes`：`scene_index` ≤ 本 Scene 的全部 Scene 的 `(id, scene_index, chapter_ids)`
  有序列表指纹来源（重排、重归属、增删均会变化）。
- `contract_version`：`CURRENT_SCENE_MEMORY_CONTRACT_VERSION`（解释方法版本）。
- 不进 `source_hash`：`source_hash` 保持投影链语义与幂等短路不变；`replace_system`
  的可比字段短路保留旧行旧 basis——绕过 hook 的变更因此**保持**待核对标记，
  直到事件层追上后重建换行，这正是保守扩大所要的行为。
- manual/confirmed 行**不记 basis、不参与读时比对**：作者决定不因环境漂移被降级或重建。

### 3.2 读时新鲜度判定

`get_scene_state_view` 在纯读路径上重算当前环境基线（同一 helper，一次 manifest 查询 +
一次有序 Scene 读取），对每个当前系统 checkpoint：

- basis 一致 → 维度 `status="ok"`（现状语义不变）。
- basis 不一致 → `status="degraded"`，`gap_reason="来源基线已变化（正文/场景结构修订），投影待重验"`。
  **不自动重建、不写库**（失效与重算分开）；作者经既有 ensure/rebuild 入口或下次编译
  loader 的懒 ensure 恢复。
- 无 basis 的历史系统行（迁移前已存在）按「基线缺失」处理：`degraded` +
  `gap_reason="缺少来源基线登记，待重建后补齐"`，一次 ensure 仅为 basis 缺失的行补登记后消除；已有 basis 漂移且投影 hash 未变时保留旧 basis，不能把旧内容洗成新鲜。
- `state_fingerprint` 语义不变（投影内容指纹）；freshness 是对同一内容的新鲜度裁决，
  不改变 fingerprint 组成。

### 3.3 响应扩展（向后兼容，M2 契约 v1 内追加字段）

`SceneStateViewResponse` 增：

- `unsupported_dependencies: list[str]`——恒含 `"world_canon_revision"`、`"map_atlas"`：
  世界正典修订与地图册变化不自动失效本视图（观察层语义），核对待走 World 复核
  （其 validation run 读时冻结比对已会把受影响 run 标 stale）。未支持依赖显式列出，
  不假装覆盖。
- 各维度 `SceneStateDimensionView.gap_reason` 承载 §3.2 的降级原因。

## 4. Evidence 包与 RP 缓存（复验既有，补齐清理与原因码）

现状（摸底确认）：

- 项目级门禁**在缓存 fetch 之前**执行：`require_active_project(source)` + consumer/owner 校验
  把归档/软删项目隐藏为 404——源项目归档或撤权时入口即失败关闭，缓存正文根本不被触碰。
- 草稿级漂移由 key 覆盖（`exact_manifest` 全集指纹）+ 命中后 `_verify_cached_proofs` 冻结 ref
  重放 + 未缓存路径 rehydrate 三重 hash 比对承担；必需引用验不出→blockers，非异常。
- 索引新鲜度：`RagIndexState` requested/indexed 双 id+hash，preflight 重读不符即 `source_changed`
  重来；查询侧 chunk 的 `source_content_hash` 必须命中当前 manifest。

M4 补齐清理与原因码：

1. **来源失效后的立即清理**（主计划 §5.1「立即拒绝使用，随后清理；不能等待 TTL 再生效」）：
   沿既有 evolution→evidence 失效缝（`apply_source_invalidation` 已调 `request_chapter_index`），
   同址增加按 `source_novel_id` 的缓存行删除（`ix_interaction_source_cache_source` 索引已建）。
   「拒绝使用」已由门禁+key+证明重放承担；清理只删不可达行，不碰权威历史。
   项目软删/归档、consumer 归档与账户封禁/申请删除经组合根 DI 清 source 或 consumer 缓存；永久删除另由 FK CASCADE 承担。清理失败会阻止权限生命周期事务成功，避免撤权后遗留敏感缓存。稿件失效的附属 purge 用 SAVEPOINT 隔离 SQL 故障，主失效事务继续成功且回执明示未清理；入口拒绝独立成立。Scene 重排不清理（不改稿指纹，仅 cutoff 变化→key 自然变化，TTL 兜底）。
2. **fetch miss 原因码**（主计划 §7.2「每 attempt 记录……命中/miss/失效原因」）：
   `fetch` 返回原因（absent/expired/version_mismatch/integrity），compile 路径与测量 harness
   原样记录；TTL 过期与版本不匹配在遥测上可区分。

## 5. 试改检查（M5 预备，仅登记映射）与范围外已知缺口

M5 试改的依赖登记载体即 Collaboration `dependencies_json`（来源快照）+
`revalidate_cognition_refs`/`inspect_cognition_freshness` 读时重读比对；世界侧依赖经
World impact 预览枚举。M4 不为试改新增表或失效路径，M5 复用同一登记-复验模式。

范围外已知缺口（摸底确认，显式登记避免「未支持依赖不明确」；属确认/链接基础设施，
不在本闭环四消费者内，M4 不扩）：`ContextConfirmation` 只登记 asset ID 不登记来源
revision/hash；`EvidenceLink.source_ref` 持久化了 hash 契约但无读时重验服务；
`ContextSnapshot` 的 source_revision 埋在 compile_options JSON；`manuscript_source.read`
不校验 draft status（「当前稿」由 manifest 定义承担）。

## 6. 验收

| 项 | 场景 | 预期 |
|---|---|---|
| A04-正文 | 同长度替换绕过失效 hook（直接改 draft content_hash 后不触发 invalidation） | 视图对应维度 degraded + gap_reason；无静默 ok |
| A04-重排 | Scene 重排绕过 hook（scene_index 直接变化） | 同上（scenes 基线指纹变化） |
| A04-正流程 | 保存→hook→supersede→ensure 重建 | 新行携带新 basis，视图恢复 ok；作者确认行全程保留 |
| 规则修订 | 世界正典修订 | 视图不降级不重建；`unsupported_dependencies` 明示；World validation run 标 stale |
| A09-归档 | source 项目归档/软删后编译或命中 RP 缓存 | 入口门禁立即 NotFoundError 失败关闭；缓存行随来源失效钩子立即清理，不等 TTL |
| A09-清理 | 稿源变更触发 `apply_source_invalidation` | 该 novel 的缓存行删除（miss 原因 absent）；权威历史与快照不受影响 |
| miss 原因 | 分别制造 absent/expired/version_mismatch/integrity | fetch 返回对应原因码并进入 attempt 记录 |
| 基线缺失 | 迁移前历史行 | degraded + 「缺少来源基线登记」，ensure 仅补缺失；已有漂移不得因同 hash 短路而洗新 |
| 作者行 | manual/confirmed 行在任意基线漂移下 | 不降级、不重建、不记 basis |

## 7. 版本与迁移

- Alembic：`memory_scene_checkpoints` 增 `basis_json`（JSON，nullable）；ORM parity；
  非破坏性（不回填，旧行按基线缺失语义）。down 就地删列。
- `SCENE_STATE_VIEW_CONTRACT_VERSION` 维持 `scene-state-view-v1`（追加字段，
  fingerprint 组成不变）；basis 语义记入本契约即为本闭环权威描述。
