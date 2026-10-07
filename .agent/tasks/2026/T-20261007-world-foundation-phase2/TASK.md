# T-20261007-world-foundation-phase2

---
id: T-20261007-world-foundation-phase2
title: 世界演化第二阶段实施（P2-A/B/C）：可信历史与低成本改稿
status: active
created: 2026-10-07T00:00:00+08:00
updated: 2026-10-07T00:00:00+08:00
parent: T-20261006-world-foundation-phase1-impl
---

## 目标与授权

实施 [第二阶段主计划](../../../docs/plans/2026-10-07-world-foundation-phase2.md)，按
[并行执行规划](../../../docs/plans/2026-10-07-world-foundation-phase2-parallel-execution.md)
以子代理批次推进三顺序包：P2-A 历史字段与来源 → P2-B 知识值与揭示边界 → P2-C 实际依赖与局部重做。

授权边界：全部批次离线执行，零 LLM 调用、零真实数据写入、不延伸 USD 20 授权；
R7（真实质量/费用/留出门禁）未闭合留在父任务，不得核销为 P2 工作；不默认开放 formal family。

工作区：worktree `/Users/tywww/.codex/worktrees/world-foundation-plan/ai-writing-assist`，
分支 `codex/world-foundation-phase1-plan`（领先 main 6 提交，落后 0，基线 `b40cd0c5a`）。
phase1+P2 一并走 PR 合入 main。

## 执行方式（来自并行规划，勿回退）

- 三包串行（scene_state_view.py / reducer.py+schemas.py / scene_projection.py+repositories.py /
  scene_lens.py / basis.py 是跨包写入热点）；包内"契约先行 → 2–3 子代理按独立文件组并行 → 汇合验收"。
- 子代理只改文件+跑测试，禁 git commit/push；主会话统一验证提交。
- 契约批独占 schemas/contracts/service_keys；facade 归当包主线单元。
- 每包第 0 步先固定验收夹具与预期（xfail 形态），汇合时转绿。
- 批量派发每批 ≤3 子代理。

## 批次状态

| 批次 | 内容 | 状态 |
|---|---|---|
| 启动 | 任务记录 + 并行规划提交 | 完成 |
| P2-A 批1 | A0 夹具 ∥ A1 契约先行 | 完成（6 xfail 夹具 + 37 契约测试全绿） |
| P2-A 批2 | A2 写入端 ∥ A3 读取端 ∥ A4 展示端 | 待 P2-A 批1 |
| P2-B 批1/批2 | B0 夹具 ∥ B1 方言统一；B2/B3/B4 | 待 P2-A |
| P2-C 批1/批2 | C0 夹具 ∥ C1 登记缝；C2/C3/C4 | 待 P2-B |

### A0 产出（P2-A 批1，2026-10-07）

夹具文件：`backend/modules/story/continuity/tests/test_p2a_field_provenance.py`
（模块内 tests 惯例；全部 6 例 `xfail(reason="P2-A field provenance not implemented",
strict=False)`，当前输出 `6 xfailed`；夹具经 MemoryService / SceneMemoryProjectionService /
SceneStateViewService 公开入口真实落库执行，`--runxfail` 验证均在逐字段来源断言处失败，
非 setup 报错）。断言清单：

| 用例 | 场景 | 断言要点 |
|---|---|---|
| test_p2a_flashback_later_scene_facts_do_not_backflow | 倒叙 | 早场景位置(location_id)/指纹不回流；两场景 provenance 各指向自己事件+该章 v1 稿；timeline time_order 非母题字段不得宣称 exact |
| test_p2a_custody_handover_traces_per_scene_field_provenance | 保管交接×2 | owner 最后赋值停创建事件；holder 逐场景指向交接事件；三场景 checkpoint 可回开 |
| test_p2a_revision_keeps_old_checkpoint_on_its_version | 历史版本 | 旧 checkpoint get_record 回开且 provenance 留 v1（不洗成 v2）；新视图 provenance 形态合法 |
| test_p2a_unrelated_manuscript_change_keeps_field_fingerprint | 反向1 | 改无关章 v2 后 state_fingerprint/字段值/字段 provenance 均不变 |
| test_p2a_historical_read_does_not_backfill_current_world | 反向2 | 今日 World（summary/别名/标签/新知识）不回填历史视图值与 provenance |
| test_p2a_missing_manuscript_source_marks_fields_unverified | 来源缺失空态 | 无稿事件字段 provenance=unverified、source_refs 空，不拿整场事件列表冒充 |

逐字段来源期望契约形态决定（A1 对齐基准，文件头有同文）：

- 读取端：author 视图每条受控母题字段 fact 的 `source["provenance"]` 为单条记录
  `{field, event_id, source_refs, status}`；`status ∈ {exact, unverified, conflict}`；
  exact 要求 event_id 非空 + source_refs ≥1；非母题字段不带 provenance 或不得为 exact。
- `source_refs` 元素字段集直接从 `evidence/source_ref_contracts.py` 的
  SourceRangeRefContract dataclass 推导；content_mode 固定 `"working"`（与 basis.py 口径一致）。
- unverified：追不到赋值链（如无稿）→ source_refs 空、可留已知 event_id、禁整场列表。
- `field` 取受控母题 payload 键（custody_owner/custody_holder、location_id/text_state、
  opening_*），非视图聚合字段名——已与 A1 落地的 MOTIF_FIELD_REGISTRY 口径对齐
  （A1 用 field_key/`_field_provenance` 内嵌 state_json，读取端接线面以本夹具为准）。
- 历史回开端：`get_record` 暴露 `field_provenance`（响应属性或 state_json 的
  `_field_provenance` 内嵌键，两者取其一），保留构建当时版本语义。

## 关键代码事实（三个只读调查子代理确认，2026-10-07）

- 模块根在 `backend/modules/`（非 backend/app/modules）。
- 三母题字段全是自由 payload 无注册：`CharacterLocationInPanorama`（continuity/schemas.py:73）、
  custody_owner/custody_holder、opening_key_id/opening_moon_phase/opening_passphrase；moon_phase 在
  timeline facts payload。
- evidence_refs 现为维度级集合；`evidence/source_ref_contracts.py:19-28` 的 SourceRangeRefContract
  已存在可复用（continuity 未用——零成本接入点）。
- `scene_state_view.py`：_entries_for:303、_filter_entries:569、_knowledge_grants:530（值绑定经
  stable_hash）、_reveal_cache:608；UNSUPPORTED_DIMENSIONS:39。
- 历史 checkpoint 回开 `scene_projection.get_record:221` 返回 raw state_json 不过视角边界（P2-B 修）。
- 两套揭示系统默认相反：Story RevealPlan 无策略默认公开（outline_state/contracts.py:531）vs
  World ReaderRevealPolicy 无 cutoff 默认隐藏（knowledge_visibility_service.py:140-167）。
- Evolution 机器路径 `KnowledgeInPanorama`（schemas.py:81-91，state_gate.py:216 校验）无
  subject_id/fields/known_values，表达不了值绑定。
- `state_trial.py` 三值裁决（verdict:231-238）uncertain 分支零测试。
- `evolution/invalidation.py` coverage_note:227-230 明言细粒度登记缺失；apply_source_invalidation:209-232
  保守扩大；UNSUPPORTED_CONSUMERS:33-42。
- writing `repositories.py:38-62` 调 DI 缝（service_keys.py:131-133 / bootstrap.py:421-423）但丢弃
  InvalidationReceipt 返回值——P2-C 最小首步透传。
- 前端：SceneLensSummary.vue:111/:118 下钻入口已有；`POST /memories/scene-state-view`
  （continuity/api.py:187）无直接前端调用方；api/evolution.js 无失效端点。
- Collaboration 侧 P2-C 基本复用：试改零正史写入、merge.py:87-112 双幂等、recovery.py 三向 rebase。

## 跨会话陷阱（沿父任务，新会话必读）

- shell cwd 每次 Bash 调用后重置，命令必须显式 cd 到 worktree 绝对路径；子代理同。
- 生产 autoflush=False：改 ORM 属性后必须显式 flush（populate_existing 重读陷阱）。
- evals 模块严禁 import 时改 os.environ（模块级污染挂全量）。
- scene_lens(evidence)→story 保持函数内导入（顶层会成双向对，module-import-gate 基线 0）。
- 单测库 SQLite 无触发器；真 PG 在 5207（novelist/novel_dev_pass）；e2e 需 -m e2e。
- @patch/mock.patch 一律 autospec=True；生产禁 Mock。

## 验证与提交

每包收尾：受影响模块测试 + lint → `make docs-check`（world/story 影响）→ 真 PG migration（有 schema
变更的包）→ 前端关键流 → 固定提交 + 脱敏验证记录回写本文件。

## 恢复快照

（交接/暂停前更新）当前：P2-A 批1 已完成并提交，下一步派发 P2-A 批2（A2 写入端 + A3 读取端 + A4 展示端三子代理并行）。

## A1 产出（契约先行单元，2026-10-07）

新模块 `backend/modules/story/continuity/field_provenance.py`（369 行，零 LLM、零接线）；
契约测试 `backend/tests/unit/test_p2a_field_provenance_contract.py`（37 用例全绿；主会话改名消歧，原与 A0 夹具同 basename）。

### 注册表字段清单（MOTIF_FIELD_REGISTRY，field_key → dimension/label/value_kind）

- 人物位置（locations）：`location_id`(entity_ref)、`text_state`(text)、`chapter_index`(integer)——对齐 CharacterLocationInPanorama。
- 物品所有者/保管者（entities）：`custody_owner`(entity_ref)、`custody_holder`(entity_ref)。
- 锁的有限条件：`opening_key_id`(entity_ref)、`opening_moon_phase`(moon_phase_enum)、`opening_passphrase`(text)（entities 锁对象 payload）+ `moon_phase`(moon_phase_enum)（timeline facts payload，state_trial 开锁判断的月相来源）。
- 语义：未登记 payload 键照旧透传但无来源语义；FieldProvenance 构造即校验 (field_key, dimension) 已登记（model_validator，未登记抛 ValidationError）。

### FieldProvenance 最终形态

```
ProvenanceSourceRef(BaseModel, frozen)  # evidence SourceRangeRefContract 的 Pydantic 镜像
  draft_id/chapter_index/version_number/content_mode/start_offset/end_offset/source_hash/range_hash
  + from_source_range_contract(contract) -> duck-typed model_validate(from_attributes=True)

FieldProvenance(BaseModel, frozen)
  field_key: str; dimension: str          # 必须已注册且维度一致
  event_id: str                            # 造成赋值的 MemoryEvent
  source_refs: tuple[ProvenanceSourceRef]  # 非空时 version_number 全一致且 == version
  version: int(ge=0)                       # 资料修订版本；无区间锚为 0
  recorded_at_sequence: int(ge=0)          # scene_sequence 优先，无 Scene 锚用章内 sequence
```

镜像而非 import 复用的裁定：module-import-gate 的 function_level_imports 棘轮 525 只减不增
（实测函数内 import evidence 即 526 FAIL），且 JSON 边界须 Pydantic 校验；契约测试对拍
`set(SourceRangeRefContract.__dataclass_fields__) == set(ProvenanceSourceRef.model_fields)` 防漂移。

### status 判定规则（resolve_field_status 纯函数，三态 + None）

1. 空记录 → `None`（展示层显示"来源待核实"）；2. 完全相同记录幂等去重；
3. 取 recorded_at_sequence 最大组（reducer 后者胜：保管转移等正常演化不算冲突）；
4. 同序仍多条不同链 → `conflict`（相对顺序未知不裁决）；5. 最新链唯一：有 refs → `exact`，只追到事件 → `unverified`。

### 存放规范结论：纯 JSON 内嵌，不需要新列

- 键：checkpoint `state_json["_field_provenance"]`（常量 `FIELD_PROVENANCE_STATE_KEY`；与 `_coverage` 内部元数据键同惯例，不进 `_entries_for` 展平路径）。键存在性即新旧格式判别，无版本字段。
- 读取：`read_field_provenance(state_json)` 旧格式/空载荷/非 dict → `[]` 不报错不冒充；新格式内容非法抛 ValidationError（写入端已校验，读回非法属数据损坏应显式暴露）。便捷入口 `provenance_status_for(state_json, field_key, dimension=None) -> ProvenanceStatus | None`。
- 不新列理由：字段级来源与 checkpoint 行生命周期完全一致（随 supersede 软删）、A3 读取端本就逐 checkpoint 读 state_json（零额外 I/O）、无跨行独立查询需求；省去 models+Alembic（A2 批如需重评依本记录）。

### timeline 受控发生时间（TIMELINE_WHEN_CONTROLLED_KEYS + TimelineWhenClause）

受控键：`scene_index`/`scene_sequence`（相对顺序锚，沿用 services 注入键形）、
`relative_to_fact_id`+`relative_order`(before/after)（成对相对锚）、`stated_date`（原文明示日期
原样保存，不换算日历）。`extract_timeline_when(payload)` 容错提取：类型不符视为缺失、未受控键
忽略、半个相对锚整体丢弃，永不因 payload 形状报错；直接构造 TimelineWhenClause 则严格校验成对。

### A2/A3 落点建议

- A2 写入端：`scene_projection.py` `_project_dimension`（:449 事件循环内，`_apply_event` 旁为登记字段构建 FieldProvenance 写入 `state["_field_provenance"]`，继承 previous 的历史链供时序裁决；evidence 区间经 duck-typed 转换）；timeline 受控键规范化在事件 payload 构造处（services.py `_with_scene_event_key` 注入链附近，A2 先调查）。reducer.py 保持纯状态解释内核，不建议挂链。
- A3 读取端：`scene_state_view.py` `_entries_for`（:303，entities `_flatten_fields` 与 timeline facts 生成 SceneStateFactEntry 时用 `provenance_status_for` 把 status 填进 source dict，None → "来源待核实"）；`state_trial.py`（:72-83）custody/opening/moon 取值处附带 status，exact 才显示精确回指。
