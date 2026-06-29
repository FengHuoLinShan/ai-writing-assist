# 写作冲突检查跨模块证据支撑设计

## 背景

写作页前两阶段已经形成 Scene 驱动正文工作台，并完成剧情设定冲突检查的基础闭环：规则检查、历史记录、详情弹窗、问题状态、AI 软冲突判断、AI 修复建议和发布前快照归档。

当前缺口不只是写作页交互问题，而是跨模块证据支撑还不够强：

- 待确认对象的纳入语义不完整。写作页固定使用 `include_candidates=false`，`world.map` 的写作摘要 seam 也没有真正消费候选事实。
- 来源证据偏粗。冲突项能说明“发生了什么”，但不能稳定说明“依据来自哪个模块、哪个对象、哪个字段、去哪修”。
- `memory` 连续性来源还缺少可打开目标，作者难以从检查结果追溯到记忆摘要。
- 后续 AI 写作工具胶囊、独立 Scene 整理工作台、发布前检查都需要复用同一套来源证据语义。

本设计主轴是补强 **跨模块冲突证据契约**。写作页剧情设定冲突检查只是第一消费方。

## 目标

- 定义可复用的冲突证据形状，让 `outline`、`world/map`、`memory`、`context` 可以各自提供自己拥有的事实来源。
- 让 `world.map` 的 Scene 写作摘要真正支持 `include_candidates`，并明确候选事实依赖。
- 让 `memory` 提供章节 / Scene 连续性证据和可打开来源目标。
- 让 `writing` 只做汇总、持久化、状态和发布快照，不解释其他模块内部事实。
- 写作页提供检查前范围选择和检查后证据抽屉，帮助作者判断问题依据与修复入口。
- 真实 LLM 参与 AI 软判断和修复建议验收，但不替代规则层检查，不固定自然语言输出。

## 非目标

- 不建设完整 trace graph、审计系统或跨模块版本 diff 系统。
- 不新增自治 Agent、多 Agent 协作或新的前端技术栈。
- 不让 AI 自动修改正文、Scene、地图、世界对象、memory 或正史资产。
- 不把独立 Scene 整理工作台纳入本轮实现。
- 不把完整 compiled context、prompt 或大段上下文归档进冲突项或发布快照。

## 产品交互

写作页保持三栏工作台。用户点击 `剧情设定冲突检查` 后，先看到轻量选项弹窗。

默认选项是 `只检查已确认事实`。用户可以勾选 `包含待确认对象`。勾选后，本次检查请求传 `include_candidates=true`。弹窗只说明一句风险：包含待确认对象后，相关结果会标记为 `需复核`，不会自动写入正文、Scene、地图或正史。

用户确认后，前端照旧先自动暂存正文。暂存失败时停止，不创建检查。

检查详情弹窗保留 `规则命中` 和 `AI 判断` 分组。每条问题新增可展开的 `证据` 区域，展示：

- 来源模块。
- 来源对象和字段。
- 人可读证据片段。
- 是否依赖待确认对象，以及需复核原因。
- 打开来源按钮。

问题处理状态仍是 `已处理`、`忽略`、`稍后`。证据区只帮助判断，不新增处理状态。

## 证据契约

本轮不新增 trace 表。`writing_conflict_items.location_json` 扩展为稳定证据载荷。现有 `source_module`、`source_type`、`source_id`、`evidence_summary` 保持兼容。

建议形状：

```json
{
  "text_range": { "start": 120, "end": 134 },
  "source": {
    "module": "outline",
    "type": "scene.must_not_happen",
    "id": "scene-id",
    "label": "Scene：东门对峙",
    "field": "禁止发生",
    "excerpt": "不得让守卫主动放行"
  },
  "open_target": {
    "kind": "outline_scene",
    "scene_id": "scene-id"
  },
  "needs_review_reason": null
}
```

字段约定：

- `evidence_summary`：一句话摘要，用于列表快速扫描。
- `location_json.text_range`：正文定位。没有正文范围时可省略。
- `location_json.source`：证据抽屉的人可读来源。
- `location_json.open_target`：前端打开来源的稳定目标。
- `needs_review=true` 时必须有 `needs_review_reason`。
- `open_target.kind` 第一版支持 `outline_scene`、`map_scene`、`map_object`、`memory_chapter`、`text_range`。
- 发布快照归档轻量证据摘要和 `open_target`，不归档完整跨模块对象。

## 跨模块支撑

### writing

`writing` 定义统一的冲突证据载荷并负责汇总：

- 创建冲突检查。
- 调用跨模块 facade。
- 把模块证据转成 `writing_conflict_items`。
- 保存历史、问题状态和发布快照。
- 暴露给前端的 API response 保持渐进增强，不引入 breaking change。

`writing` 不直接 import 其他模块的 `models.py`、`repositories.py` 或 `services.py`。跨模块调用只通过 facade / contracts。

### outline

`outline` 继续通过 `get_scene_contract` 提供 Scene 字段。`writing` 从 `SceneContract` 生成字段证据：

- `goal` → `source.field=目标`
- `must_happen` → `source.field=必须发生`
- `must_not_happen` → `source.field=禁止发生`
- `core_conflict` → `source.field=核心冲突`

`open_target.kind=outline_scene`，包含 `scene_id`。第一版前端打开大纲页时必须携带 Scene 目标；若大纲页暂不支持自动聚焦，必须显示“已打开大纲，请在 Scene 列表中定位该 Scene”的可见提示，不能静默退化。

### world / map

`world.map_facade.summarize_scene_map_for_writing(db, novel_id, scene_id, include_candidates=...)` 必须真正消费 `include_candidates`。

当 `include_candidates=false` 时，写作摘要只纳入已确认 / 正式地图事实。

当 `include_candidates=true` 时，写作摘要可以纳入 candidate / conflicted observations 或 candidate markers，但必须在返回结构中标记：

- 哪些风险依赖待确认对象。
- 待确认对象的 review state。
- 可打开地图目标，例如地图、Scene、对象或候选观察。

`writing` 不理解 world 内部状态，只把 world 返回的候选依赖转成 `needs_review=true` 和 `needs_review_reason=依赖待确认地图观察` 等。

### memory

`memory` 提供章节 / Scene 连续性证据。第一版新增轻量 facade，例如 `get_continuity_evidence_for_writing`，内部可以复用 `get_memory_panorama`，但对外输出稳定证据形状，支持：

- 上一章或上一 Scene 的角色位置。
- 当前 Scene 地图主地点。
- 人可读连续性摘要。
- `open_target.kind=memory_chapter`，包含 `chapter_index`、角色 ID 或来源摘要键。

前端第一版打开“章节记忆摘要”弹窗；后续再接独立 memory 页面。

### context / LLM

AI 软判断和 AI 修复建议继续走 context confirmation：

- AI 软判断 action 是 `writing.conflict_check.ai_review`。
- AI 修复建议 action 是 `writing.conflict_check.ai_suggestion`。
- `include_pending_objects` 与本次检查的 `include_candidates` 保持一致。
- 证据抽屉可以显示 `source_confirmation_id` 和 context action。

不把完整 compiled context、prompt 或大段上下文写入冲突项。

## 数据流

1. 前端打开检查选项弹窗，用户选择 canonical 或包含待确认对象。
2. 前端自动暂存正文。失败时停止。
3. 前端创建检查请求，带 `include_candidates`、正文、chapter、scene、draft/version。
4. `writing` 调用 `outline`、`world.map`、`memory` 的稳定入口。
5. 各模块返回自己拥有的事实和来源目标。
6. `writing` 统一生成 conflict items，每条包含 `evidence_summary`、`location_json.source` 和 `open_target`。
7. 前端打开检查详情，按 item 渲染证据抽屉。
8. 用户更新问题状态或追加 AI 软判断 / 修复建议。
9. 发布时归档最近一次检查的轻量证据快照。

## 降级规则

- `outline` 缺 Scene：检查继续，Scene 字段项跳过，`summary_json.degraded_sources` 包含 `outline`。
- `world.map` 摘要失败：检查继续，`degraded_sources` 包含 `world.map`，证据区显示地图来源不可用。
- `memory` 全景失败：检查继续，`degraded_sources` 包含 `memory`。
- `include_candidates=true` 但某模块不支持候选：该模块返回 `candidate_support=unsupported` 或等价降级信息，`writing` 标记检查降级，不能假装已检查。
- 任何依赖 candidate / conflicted 的问题必须 `needs_review=true`，并写明 `needs_review_reason`。
- AI 失败只影响 AI 状态，不能删除规则层结果。

## 真实用户路径验收

### 1. 写作前 canonical 检查

作者进入写作页，选择章节 / Scene，写正文，点击 `剧情设定冲突检查`。默认不包含待确认对象。系统先暂存，再检查 Scene 禁止项、必须项、地图 confirmed 状态和上一章记忆。作者能看到最近一条记录、展开证据、定位正文、打开来源。

### 2. 主动纳入待确认对象

同一 Scene 有 deep import 或地图观察产生的 candidate / conflicted 地图事实。作者勾选 `包含待确认对象` 后运行检查。依赖候选事实的问题必须显示 `需复核`，证据里说明来自待确认对象，并能打开地图候选来源。未勾选时这些候选事实不参与判断。

### 3. 跨模块来源排查

一次检查结果包含来自 `outline`、`world.map`、`memory` 的问题。作者分别点击来源：

- outline 能到对应 Scene 或给出可见提示。
- map 能到对应地图 / 对象 / 候选观察。
- memory 至少能打开章节记忆摘要。

目标暂不可打开时，前端必须给清楚提示，不能沉默失败。

### 4. 发布前风险路径

最近一次检查有未处理高严重度问题时，发布前提示。用户选择继续发布后，发布草稿归档当时的检查快照。之后用户把问题标为已处理，不应改写已发布版本中的快照。

### 5. 降级但不中断

world 或 memory 暂不可用时，检查仍完成，结果显示降级来源。作者能看到哪些来源没有检查到，不能误以为全量通过。

### 6. 窄屏和 XSS

窄屏下，检查选项弹窗、证据抽屉、历史列表不横向溢出。所有证据片段、AI 文本、来源名称都必须转义。

## 真实 LLM 验收

真实 LLM 参与 AI 软判断和修复建议路径。真实 LLM 验收不固定自然语言输出，只验证结构、状态机、持久化和无副作用。

### AI 软冲突追加

用户在已有规则检查记录上点击 `补充 AI 软冲突判断`。前端先打开 AI 参考资料确认。用户确认后，后端用真实 LLM 生成结构化软冲突项。

验收要求：

- confirmation action 是 `writing.conflict_check.ai_review`。
- 输出通过 Pydantic schema 校验。
- 合法项保存为 `is_ai_judgment=true`。
- 非法项可被丢弃并记录 `discarded_count`。
- LLM 失败只让 `ai_review_status=failed`，不删除规则层结果。

### AI 修复建议

用户对某条问题点击 `生成 AI 修复建议`。真实 LLM 返回结构化建议。

验收要求：

- confirmation action 是 `writing.conflict_check.ai_suggestion`。
- 建议保存到问题项。
- 不修改正文、Scene、地图、world、memory 或正史对象。
- 前端能复制建议。
- 插入正文不属于本轮范围。

### 候选对象 + AI

当检查包含待确认对象时，AI confirmation 使用 `include_pending_objects=true`。AI 产生的相关项必须 `needs_review=true`，并显示需复核原因。

### 发布快照

如果发布前跑过真实 LLM 软判断或建议，发布快照归档 AI 状态、AI 项计数、建议计数和轻量证据摘要。不归档完整 prompt 或大段上下文。

### 手动验收命令

常规 CI 继续使用 mock LLM。真实 LLM 验收作为手动路径：

```bash
RUN_REAL_LLM_TESTS=1 pytest modules/writing/tests/test_conflict_checks_real_llm.py -q -s
```

前端真实 UI 烟测：

```bash
ENABLE_REAL_LLM=1 npx playwright test e2e/writing-conflict-real-llm.spec.js --reporter=list --timeout=300000
```

验收报告记录模型名、状态机、保存结果和无副作用检查。

## 模块契约测试

后端：

- `writing`：`include_candidates=true/false` 都有测试；每条规则项包含 `source`、`open_target`、`needs_review_reason`；发布快照保留轻量证据。
- `world.map`：confirmed 与 candidate / conflicted observation 分别返回；`include_candidates=false` 不纳入候选，`true` 纳入并标记候选依赖；跨 novel_id 不泄漏。
- `memory`：连续性证据能返回 `memory_chapter` open target；失败时 writing 降级而不是报错。
- `outline`：Scene 字段证据包含 field / excerpt / open target；缺 Scene 降级。
- `context / AI`：AI 判断和建议仍要求 action 匹配的 confirmation，AI 失败不影响规则项。

前端：

- 点击检查先出现选项弹窗，默认 canonical。
- 勾选 `包含待确认对象` 后请求体传 `include_candidates=true`。
- 检查详情每条问题可以展开证据抽屉。
- 证据抽屉文本全部转义。
- outline / map / memory / text range open target 都有明确反馈。
- 发布前提示继续按未处理高严重度问题工作。
- 窄屏无横向溢出。

建议验证命令：

```bash
cd backend
pytest modules/writing/tests/test_conflict_checks.py modules/world/tests/test_map_scene_summary.py modules/memory/tests/test_memory.py -q
ruff check .
```

```bash
cd frontend-console
npx vitest run tests/writingView.test.js tests/writingConflictModal.test.js
npx playwright test e2e/writing.spec.js
```

```bash
git diff --check HEAD
```

## 实施切分建议

1. 定义 evidence helper / schema 约定，先在 `writing` 内部使用。
2. 补 `outline` Scene 字段证据载荷。
3. 补 `world.map` candidate-aware summary 和候选依赖标记。
4. 补 `memory` 连续性证据 open target。
5. 接入 `writing` 冲突项生成和发布快照。
6. 接入写作页检查选项弹窗和证据抽屉。
7. 扩展真实用户路径测试和真实 LLM 手动验收。

## 设计边界

这轮完成后，写作页冲突检查应成为跨模块证据支撑的第一个完整消费场景。后续 AI 写作工具胶囊可以复用相同的 `source`、`open_target`、`needs_review_reason` 语义；独立 Scene 整理工作台也可以复用这些证据入口，但不在本轮实现。
