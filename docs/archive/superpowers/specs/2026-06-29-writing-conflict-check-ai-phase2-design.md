# 写作页剧情设定冲突检查第二阶段设计

## 背景

`2026-06-29-writing-scene-workbench-design.md` 定义了写作页第一阶段：以 Scene 驾驶舱为默认写作形态，提供单一高频动作 `剧情设定冲突检查`，并优先落地规则层检查、持久化历史、问题定位、处理状态和发布归档。

第二阶段在第一阶段基础上补齐三类能力：

- LLM 软冲突判断。
- AI 修复建议。
- 待确认对象可选纳入检查，并清楚标记“需复核”。

第二阶段不改变一阶段的产品主轴：写作页仍是 Scene 驱动的正文工作台，AI 只辅助判断和建议，不自动改正文、不自动改正史、不替代规则层。

## 目标

- 在规则检查之外识别叙事软冲突，例如动机不连贯、情绪跳变、伏笔误揭示、隐含设定不一致。
- 为单条冲突问题生成可解释的 AI 修复建议。
- 复用现有 `AI 参考资料` 确认流程和 `context_confirmation_id` 追踪机制。
- 支持用户显式打开“包含待确认对象”，并让相关结论标记“需复核”。
- 将 AI 判断、规则命中、待确认对象影响清楚区分，避免作者把 AI 判断误解为事实。
- 保持检查历史可追溯：每条 AI 判断必须保存输入摘要、确认记录、判断类型、置信度和可见理由。

## 非目标

- 不做一键应用 AI 修复。
- 不让 AI 直接修改正文草稿、Scene、地图、世界对象、记忆或正史资产。
- 不让 LLM 重新判定规则层已经明确命中的硬冲突。
- 不把完整上下文 Markdown 暴露成可编辑正文。
- 不把待确认对象默认纳入正式检查。
- 不引入新的多 Agent 协同系统。
- 不绕过 `context_confirmation_id` 和 `novel_id` 校验。

## 产品流程

### LLM 软冲突检查

用户点击 `剧情设定冲突检查` 后，第一阶段规则层先运行。第二阶段在规则层结果之后追加一个可选 LLM 层：

```text
自动暂存当前正文
  → 规则层检查
  → 如用户启用 AI 软冲突检查，打开或复用“AI 参考资料”确认
  → 后端按确认记录编译上下文
  → LLM 输出软冲突候选
  → 后端按 schema 校验并保存为问题项
  → 前端在同一检查弹窗中展示“AI 判断”分组
```

默认交互：

- 第一版第二阶段可以把 AI 软冲突作为检查弹窗里的开关：`补充 AI 软冲突判断`。
- 如果用户未启用，检查仍只展示规则层。
- 如果用户启用，必须经过 `AI 参考资料` 确认或复用当前检查已创建的确认记录。
- AI 判断的问题项默认显示 `AI 判断` 标签。
- 如果启用了待确认对象，相关问题项同时显示 `需复核`。

### AI 修复建议

用户在单条问题上点击 `生成 AI 修复建议`。

流程：

```text
用户点击某条问题的“生成 AI 修复建议”
  → 打开或复用“AI 参考资料”确认
  → 后端校验问题项、检查记录、novel_id 和确认记录
  → LLM 只针对该问题生成建议
  → 建议保存到问题项或建议表
  → 前端展示建议文本、依据和注意事项
```

建议必须保持手动采纳：

- 可复制。
- 可定位回正文。
- 可作为“参考改写”显示。
- 不提供一键覆盖正文。
- 不提供一键修改 Scene / 地图 / 世界对象。

## AI 参考资料语义

第二阶段复用现有 `context` 模块确认体系。

### context action

建议新增或保留以下 action：

```text
writing.conflict_check.ai_review
writing.conflict_check.ai_suggestion
```

`writing.conflict_check.ai_review` 用于整次检查中的 AI 软冲突判断。

`writing.conflict_check.ai_suggestion` 用于单条问题的修复建议。

### 默认上下文模式

默认：

- `context_mode="canonical"`
- `include_pending_objects=false`

用户显式打开待确认对象后：

- `include_pending_objects=true`
- 所有依赖待确认对象的 AI 判断和建议必须标记 `needs_review=true`
- 前端显示“包含待确认对象，结果需复核”

### 上下文范围

AI 软冲突判断默认范围：

- 当前 Scene。
- 当前章节正文。
- 当前章节前后相邻 Scene。
- 当前 Scene 关联的世界 / 地图摘要。
- 当前 Scene 关联的伏笔 / 揭示。
- 规则层已命中的问题摘要。

AI 修复建议默认范围：

- 当前问题项。
- 当前问题项证据。
- 当前正文中定位片段。
- 当前 Scene 的目标、必须发生、禁止发生、核心冲突。
- 必要的前后 Scene 摘要。

## 后端设计

### 模块归属

第二阶段仍由 `writing` 拥有检查记录、问题项和建议结果。

跨模块读取：

- `context`：确认记录、上下文编译、`context_confirmation_id` 校验。
- `outline`：Scene 和前后 Scene 契约。
- `world`：地图 / 世界状态摘要。
- `memory`：前后章节 / Scene 记忆摘要。
- `infrastructure/llm`：LLM 调用。

生产业务代码不得直接 import 其他模块的 `models.py`、`repositories.py` 或 `services.py`。

### 服务边界

建议在 `writing` 内拆分：

```text
ConflictCheckService
ConflictCheckRuleEngine
ConflictCheckAiReviewService
ConflictSuggestionService
```

职责：

- `ConflictCheckService`：检查流程编排、记录持久化、状态更新。
- `ConflictCheckRuleEngine`：规则层硬冲突。
- `ConflictCheckAiReviewService`：LLM 软冲突判断。
- `ConflictSuggestionService`：单条问题的 AI 修复建议。

LLM 服务只接收已经整理好的检查上下文，不负责直接跨模块查询。

### 数据扩展

第一阶段的 `writing_conflict_checks` 可增加：

- `ai_review_enabled`
- `ai_review_status`
- `ai_review_confirmation_id`
- `ai_review_model`
- `ai_review_error`

第一阶段的 `writing_conflict_items` 可增加或使用已有字段：

- `is_ai_judgment`
- `needs_review`
- `confidence`
- `source_confirmation_id`
- `llm_rationale`
- `suggestion_status`
- `suggestion_confirmation_id`
- `ai_suggestion`
- `suggestion_error`

如果单条建议需要版本化，可新增：

```text
writing_conflict_suggestions
```

字段包括：

- `id`
- `novel_id`
- `item_id`
- `confirmation_id`
- `suggestion_text`
- `rationale`
- `model`
- `created_at`

第一版第二阶段可以先把最新建议内联到 `writing_conflict_items.ai_suggestion`，后续再拆建议表。

## API 设计

第一阶段接口基础上新增：

```http
POST /api/writing/conflict-checks/{check_id}/ai-review
```

用途：为一次检查追加 LLM 软冲突判断。

请求：

```json
{
  "novel_id": "uuid",
  "context_confirmation_id": "uuid"
}
```

响应：

```json
{
  "check_id": "uuid",
  "ai_review_status": "done",
  "items": []
}
```

约束：

- 校验 `check_id` 属于 `novel_id`。
- 校验确认记录 action 为 `writing.conflict_check.ai_review`。
- 校验确认记录 `novel_id` 一致。
- 追加的问题项必须 `is_ai_judgment=true`。

```http
POST /api/writing/conflict-check-items/{item_id}/ai-suggestion
```

用途：为单条问题生成修复建议。

请求：

```json
{
  "novel_id": "uuid",
  "context_confirmation_id": "uuid"
}
```

响应：

```json
{
  "item_id": "uuid",
  "suggestion_status": "done",
  "ai_suggestion": "..."
}
```

约束：

- 校验 `item_id` 属于 `novel_id`。
- 校验确认记录 action 为 `writing.conflict_check.ai_suggestion`。
- 只保存建议，不修改正文或结构化资产。

## LLM 输出 schema

### 软冲突判断

LLM 必须输出结构化 JSON。

```json
{
  "issues": [
    {
      "kind": "motivation_gap",
      "severity": "medium",
      "summary": "主角突然信任港务长，缺少动机过渡",
      "evidence": "正文片段或上下文摘要",
      "rationale": "为什么这属于软冲突",
      "location_hint": {
        "chapter_index": 12,
        "scene_id": "uuid",
        "text_quote": "短引用"
      },
      "confidence": 0.72,
      "depends_on_pending_objects": false
    }
  ]
}
```

允许的 `kind`：

- `motivation_gap`
- `emotion_jump`
- `foreshadowing_misfire`
- `premature_reveal`
- `implicit_lore_conflict`
- `voice_or_pov_drift`
- `scene_goal_drift`
- `continuity_soft_risk`

允许的 `severity`：

- `low`
- `medium`
- `high`

后端必须丢弃不符合 schema 的条目，并把降级信息写入检查摘要。

### 修复建议

```json
{
  "suggestion": {
    "strategy": "补一段动机过渡",
    "suggested_text": "可手动采纳的改写建议",
    "rationale": "为什么这样能修复问题",
    "constraints": [
      "不能提前揭示证人全部真相"
    ],
    "risk_notes": [
      "若采用该建议，需要保持港务长仍不可信"
    ]
  }
}
```

`suggested_text` 是建议，不是自动补丁。前端不能把它作为一键应用按钮。

## 前端设计

### 检查弹窗扩展

检查弹窗增加两个区域：

- `规则命中`
- `AI 判断`

`AI 判断` 区域默认显示：

- `补充 AI 软冲突判断` 按钮。
- 当前是否包含待确认对象。
- 最近一次 AI 判断状态。

点击后：

1. 打开 `AI 参考资料` 弹窗。
2. action 使用 `writing.conflict_check.ai_review`。
3. 确认后调用 `/api/writing/conflict-checks/{check_id}/ai-review`。
4. 返回后刷新问题列表。

### 单条问题建议

每条问题的详情区增加：

- `生成 AI 修复建议` 按钮。
- 建议状态：未生成 / 生成中 / 已生成 / 失败。
- 建议内容。
- 复制按钮。

按钮点击后：

1. 打开 `AI 参考资料` 弹窗。
2. action 使用 `writing.conflict_check.ai_suggestion`。
3. 确认后调用 `/api/writing/conflict-check-items/{item_id}/ai-suggestion`。
4. 只刷新该问题项。

### 待确认对象提示

当用户勾选包含待确认对象：

- 弹窗内显示“包含待确认对象，结果需复核”。
- AI 判断问题项显示 `需复核`。
- AI 修复建议显示来源提示。

前端文案不使用 `candidate`，统一使用“待确认对象”。

## Prompt 约束

LLM 软冲突判断 prompt 必须明确：

- 只报告与当前 Scene 写作目标相关的问题。
- 不重复规则层已经明确列出的问题，除非提供新的叙事角度。
- 不把缺少信息当作事实错误。
- 不输出正史修改指令。
- 不输出一键应用补丁。
- 对每条问题给出依据和置信度。
- 依赖待确认对象时标记 `depends_on_pending_objects=true`。

AI 修复建议 prompt 必须明确：

- 只针对单条问题。
- 生成可手动采纳的建议。
- 尊重 Scene 的必须发生和禁止发生。
- 不提前揭示隐藏真相。
- 不引入新的正史事实。
- 如果需要新增事实，必须标记为“需要作者确认”。

## 异常与降级

- 确认记录缺失：返回 400，不调用 LLM。
- 确认记录 action 不匹配：返回 400。
- 确认记录 novel_id 不匹配：返回 404 或 403。
- LLM 超时：检查记录保留规则层结果，AI 判断状态为 `failed`。
- LLM 输出部分不合法：保留合法条目，摘要显示“部分 AI 判断已丢弃”。
- AI 建议失败：只更新该问题项建议状态，不影响检查结果。
- 待确认对象后续被忽略 / 合并 / 改名：相关 AI 判断和建议标记 `stale_context` 或 `needs_review`，不自动重算。

## 安全与边界

- AI 输出必须通过 Pydantic schema 校验。
- 不 `eval` / `exec` LLM 输出。
- 前端展示 AI 输出必须转义。
- AI 建议不得自动写入正文。
- AI 建议不得自动修改结构化资产。
- AI 判断不得覆盖规则命中。
- AI 判断不得提升待确认对象为正史。
- 真实 LLM 测试默认跳过，只保留手动验收开关。

## 测试策略

后端：

- `ai-review` 校验 `context_confirmation_id`、`action`、`novel_id`。
- LLM 软冲突合法输出保存为 `is_ai_judgment=true` 的问题项。
- 依赖待确认对象的问题项保存 `needs_review=true`。
- LLM 部分非法输出只丢弃非法条目。
- LLM 超时不破坏规则层检查记录。
- `ai-suggestion` 只保存建议，不修改 draft / Scene / world 对象。
- `novel_id` 隔离。

前端：

- 检查弹窗显示 `规则命中` 和 `AI 判断` 分组。
- 点击 `补充 AI 软冲突判断` 打开 AI 参考资料弹窗。
- 确认后调用 `ai-review` API 并刷新问题列表。
- 单条问题点击 `生成 AI 修复建议` 后显示建议。
- AI 建议失败时显示错误且保留原问题。
- 包含待确认对象时显示“需复核”。
- AI 输出和建议文本转义。

E2E：

- 运行规则检查。
- 补充 AI 软冲突判断。
- 生成单条 AI 修复建议。
- 标记问题为 `稍后`。
- 刷新后历史记录仍保留 AI 判断和建议摘要。

真实 LLM 验收：

- 使用环境变量显式启用。
- 只验证 schema、UI 流和人工可读结果。
- 不进入默认 CI 门禁。

## 分阶段落地

### 2A：AI 判断骨架

- API、状态字段、前端分组。
- Mock LLM / fixture 驱动测试。
- 不接真实 prompt。

### 2B：真实 LLM 软冲突

- Prompt。
- schema 校验。
- 部分失败降级。
- 待确认对象标记。

### 2C：AI 修复建议

- 单条问题建议 API。
- 前端建议展示和复制。
- 失败态与历史持久化。

## 验收标准

- 规则层检查不依赖 LLM 也能独立完成。
- 用户可在检查弹窗中追加 AI 软冲突判断。
- AI 判断和规则命中分组展示。
- AI 判断问题项带来源、理由、置信度和 `AI 判断` 标签。
- 待确认对象参与时，相关结论显示 `需复核`。
- 用户可为单条问题生成 AI 修复建议。
- AI 修复建议不能一键应用。
- AI 失败不影响规则层检查记录。
- 刷新后历史记录仍能看到 AI 判断和建议摘要。
- 所有 AI 输出安全转义。
- 不破坏 `novel_id` 隔离和模块稳定接口边界。
