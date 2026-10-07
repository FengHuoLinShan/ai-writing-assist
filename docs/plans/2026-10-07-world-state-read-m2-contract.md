# 世界状态读取：M2 实施契约

日期：2026-10-07（Asia/Tokyo）。状态：已实施并经独立复审整改；验收结论见阶段审查与整改报告。
上游决策：[第一阶段计划](2026-10-06-world-foundation-phase1.md) §3.1/§4.1/§4.2/§7.1（A01–A03、A13）、
[ADR-0031](../adr/0031-module-dependency-directions.md)（evidence/world → story 只读消费）。
现状摸底结论（file:line 证据）见
[任务记录](../../.agent/tasks/2026/T-20261006-world-foundation-phase1-impl/TASK.md)。

本文把「指定场景状态读取与一个作者入口」固化为可实施、可验收的模块内契约。
实现事实以代码为准后回读更新；与上游计划冲突时先回计划修订，不在这里静默改口径。

## 1. 范围与非目标

交付两件事：

1. **只读状态视图**：Story 域新增 `get_scene_state_view`——按「精确 Scene +
   视角（作者/角色/读者）」返回该时点的对象状态投影，事实/信念/观察分层、
   来源可回开、未知显式。
2. **作者入口**：扩展现有 Scene Lens（evidence `scene-lens`），在写作台向作者展示
   对象级状态明细（钥匙在谁手里、谁知道什么、哪些没查过），替代现有的一句话摘要卡片。

非目标：不新增通用世界模型/规则 DSL/世界时钟；不新增 checkpoint 维度（custody 用
entities 维度字段表达，见 §4）；不做试改/比较（M5）；不自动重建或回填历史
（读路径不写库）；地图状态图层接本视图留 M4（A01 的地图入口先以在场投影一致为界）。
不需要 [计划 §8 M1/M2 决策点]（历史恢复未扩大为正式事实切换/通用规则/新 port——
复用既有六维归约与 `SceneSourcePort`）。

## 2. 输入契约（`SceneStateQuery`）

| 字段 | 类型/取值 | 语义 |
|---|---|---|
| `novel_id` | UUID | 项目隔离；经既有项目门禁 |
| `scene_id` | UUID | 精确 Scene；状态即该 Scene 截止点（既有 checkpoint 语义，`is_current` 行） |
| `viewpoint` | `{"kind": "author"}` / `{"kind": "character", "target_id"}` / `{"kind": "reader"}` | 视角决定可见层（§5）；`character` 的 target 须是本作品角色 |
| `include_dimensions` | list[str] \| None | 过滤六维（entities/relations/locations/knowledge/timeline/causality）；None=全部 |

解析与门禁：Scene 必须存在且未退役；缺省 checkpoint 不自动 ensure（读是纯读，
缺失维按 gap 返回）；视角参数只解释可见性，不改变投影本体（同 Scene 同 checkpoint
下三个视角读同一份 state，差异仅在分层输出）。正文顺序锚 = scene_index/scene_sequence；
世界内时间只在 timeline 维度有事实时表达，未记载返回 `world_valid_time: unknown`，
禁止由章节号推算日期/时长（A02）。

## 3. 输出契约（`SceneStateViewContract`）

```
{
  "contract_version": "scene-state-view-v1",
  "scene": {"scene_id", "chapter_index", "scene_index", "checkpoint_versions": {dim: version}},
  "state_fingerprint": "<stable_hash(checkpoint身份/版本/实际投影+可见名称+视角+契约版本)>",
  "dimensions": {
    "<dim>": {
      "status": "ok" | "degraded" | "missing" | "unsupported",
      "gap_reason": "…" | null,          # missing/degraded 时给出（复用 checkpoint coverage 语义）
      "evidence_refs": [ … ],            # 作者视角的维度级事件或父 checkpoint 回执；受限视角不返回全维来源
      "facts": [ FactEntry ]
    }
  },
  "unsupported_dimensions": ["world_valid_time", …],   # 显式声明，不冒充检查过
  "omissions": ["未覆盖对象/原因", …]
}
```

`FactEntry`（每条状态事实）：

| 字段 | 语义 |
|---|---|
| `subject_id` / `subject_label` | 对象（实体/关系端点/地点/知识条目） |
| `field` | 状态字段名（如 `custody_holder`、`custody_owner`、`location`、`knows:<secret_id>`） |
| `value` | 字段值；无证据时整个 FactEntry 不存在，**不得用空值表示"确定没有"** |
| `layer` | `fact`（正史投影） / `belief`（角色认知，可含 false_belief） / `observation`（在场/最近目击） |
| `occurred_at` | 发生锚（事件负载携带 scene_index/scene_sequence 时表达；未携带则缺省，不虚构）；与叙述/揭示位置分开（A02） |
| `source` | v1 粒度 = checkpoint 引用 `{checkpoint_id, dimension, confirmed}`（归约折叠后不再逐字段Attribution）；维度级事件回执在 `dimensions[dim].evidence_refs` |
| `confidence` | `confirmed`（作者确认/manual checkpoint）/ `derived`（归约推导）；confirmed 不可被系统覆盖（复用既有保护） |

状态集：`ok`=checkpoint ready；`degraded`=manual_required/retry_pending（有部分状态，
gap_reason 说明待核对，不冒充完整）；`missing`=无 checkpoint 行或 status=missing；
`unsupported`=显式不支持的维度（v1：`world_valid_time` 世界内有效时间、
`belief_fact_diff` 信念-事实自动比对——误信仅按负载 false/misconception 标记呈现）。

保管/所有权（A03 验收切片）：`custody_holder`（保管人）与 `custody_owner`（所有人）
是**两个独立字段**；两者为平铺字段：归约是浅合并，交钥匙事件只携带 `custody_holder`，`custody_owner` 的值保留。v1 来源粒度仍是 checkpoint/维度回执，不宣称已提供逐字段最后写入事件归属。
没有资源记载（如锁的开启条件）→ 不产出 FactEntry，且进 `omissions`
（「未记载」，不是「无条件」）。

## 4. 模块归属与挂载点（现状对齐）

| 职责 | 落点 | 依据/现状 |
|---|---|---|
| 投影解释（视角分层、字段覆盖、gap 语义） | `story/continuity/` 新增只读服务 `scene_state_view.py`；facade 导出 `get_scene_state_view` | §4.2 唯一职责：投影及字段覆盖由 Story 解释；归约复用 `reducer.py` 单内核与 `get_scene_checkpoints` 的 checkpoint（不重放第二套） |
| custody 语义 | entities 维度既有事件/字段表达（事件 payload 带 `custody.holder/owner` 字段变化），不新增维度、不升契约大版本 | §4.1「复用 Story 当前契约的 entities/relations/locations/knowledge 归约」；维度表 V1/V2 不动（`continuity/contracts.py:17`） |
| 信念/误信 | knowledge 维度投影（checkpoint `character_knowledge`，false_belief 既有语义） | 现状已有；character 视角不读 World 正典，只读 Story 投影 |
| 读者揭示 | 复用 `story/outline_state/reveal_visibility.py` 按章保守判定 | reader 视角的对象 facts 需 reveal 允许；timeline/causality 无逐项揭示粒度，返回 unsupported |
| 跨模块消费 | `story/scene_source_port.py` 增 `get_scene_state_view`（`STORY_SCENE_SOURCE` 注册）；Evidence/World 只经 port | ADR-0031 裁定方向；Evidence 不直引 story 内部 |
| 作者入口 | 扩展 `evidence/compilation/services/scene_lens.py`：新增「对象状态」区（per related_entity 的 FactEntry 明细 + 确定性/来源/未知标签）；经既有 `POST /scene-lens` 返回，前端 `SceneLensSummary.vue` 渲染 | 现状唯一作者 UI 路径；POV 知识单独经同 Scene character 视角读取；对象明细经 author 视角读取，不读今天的 World 知识 |
| REST | `story/continuity/api.py` 新增 `POST /memories/scene-state-view`（author 视角需 owner 门禁；reader/character 供前端诊断用） | 与既有 `/memories/*` 同门禁风格 |

写入路径零变化：不新增写入口；checkpoint 的 ensure/rebuild/repair 仍走既有入口。
状态视图永远读 `is_current` checkpoint。来源回读允许 owner 在同 novel 内显式读取历史 `GET /memories/scene-checkpoints/{checkpoint_id}`；历史记录标明用途，不当作当前事实。维度来源按父 checkpoint 链逐步回开，事件经 `GET /memories/events/by-id?event_ids=…` 同项目回读，不再被当前 Scene 的章截止误挡。

## 5. 视角分层规则

同一份 checkpoint 状态，按视角选择输出层：

| 视角 | fact 层 | belief 层 | observation 层 |
|---|---|---|---|
| author | 全部输出；已声明误信可见，自动 belief/fact 差异检查仍 unsupported | 全部 | 全部 |
| character(t) | 仅 t 自己的位置可直接输出；其他事实需 knowledge 显式声明 `subject_id + fields + known_values` 且值匹配当前事实。误信/字段名本身不授予，关系仅提到 t 不授予；A03 知道 holder 不等于知道 owner | t 的全部 belief（含 false_belief，标 `possibly_false`） | t 的在场/目击 |
| reader | 仅 reveal 判定允许的 fact；未揭示的 subject 整体不出现 | 不输出 belief（读者无角色内心） | 叙述中已呈现的观察 |

一致性（A01）：三个视角 + 写作资料（MemoryRecordsLoader 后续消费本视图）共用同一
`get_scene_state_view` 实现与同一 checkpoint 版本；「同输入多入口一致」由构造保证，
验收测试显式断言（scene lens 输出 ⊂ author 视图、同 fingerprint）。

v1 观察层范围：`changes`（未锚定的 entity_updated 等观察负载）仅 author 视角输出；
character 视角的“在场”限角色自己的 locations 事实；reader 视角的 entities/relations/locations 按 subject reveal 过滤。timeline/causality 缺少逐条揭示边界，明确 unsupported；隐藏条目只计数量，不泄露名称或全维证据。

后见不回流：collaboration 试改/后文 Scene 的知识变化只出现在其后 Scene 的 checkpoint；
本视图不融合任何 cutoff 之后的事实（§4.1「不补今天事实」既有测试钉死）。

## 6. 验收（对齐计划 §7.1）

确定性夹具 = §3.1 合成切片（直接经 `replace_scene_memory_events` 撰写事件，不依赖 LLM）：
甲把钥匙交给乙保管（owner=甲、holder=乙，两条独立证据）；秘密 S 仅丙知道；
锁 L 的开启条件未记载。

- **A01** 同一事件经 ①`get_scene_state_view`(author) ②Scene Lens 对象状态区
  ③地图在场投影读取：核心事实（谁在哪、钥匙在谁手）一致，来源可回开到同一
  event/checkpoint 版本；断言同 state_fingerprint。
- **A02** 倒叙/后文揭密夹具：后文才揭示的事件在早 Scene 视图缺席（reader/character），
   author 视图可见但带 occurred_at（发生锚≠揭示位置）；`world_valid_time` 恒 unknown；
  旧稿缺事件 → 该维 missing + gap_reason，不读当前 World 补齐。
- **A03** 保管/所有权：交钥匙后 holder=乙/owner=甲；仅看乙视角（character）时
  holder 是 fact、owner 若乙不知则不出现（unknown，不是"甲拥有"也不是"无主"）；
  误信夹具（乙误信丁持有）→ belief 层 false；锁条件未记载 → omissions 含
  「L 开启条件未记载」，任何视角不产出"无条件可开"。
- **A13** Scene Lens 首次/空态/加载/失败/窄屏：状态区区分 确定（fact/confirmed）、
  推导（derived）、认知（belief）、未检查（missing/omissions）；失败不吞错。
- 既有回归：六维投影等价、作者保护、并发乐观锁、supersede 失效传播测试全部保持。

单元覆盖 `scene_state_view.py`（分层/gap/fingerprint/不补今天）；scene lens 对接与
视角断言放 evidence 侧测试；REST 走既有 API 测试风格。不新增测试框架。

## 7. 版本与兼容

- `contract_version="scene-state-view-v1"` 进输出与 fingerprint；字段/分层语义变化 bump。
- additive：既有 `get_scene_checkpoints`/panorama/scene-lens 契约不变；Scene Lens 旧字段
  保留，新增对象状态区可空（无 related entities 时空态）；有关联但无事实的对象仍显示逐项未记载、待核对或未检查。
- 旧客户端不消费新端点不受影响；不把历史 checkpoint/receipt 重新解释为新语义。
