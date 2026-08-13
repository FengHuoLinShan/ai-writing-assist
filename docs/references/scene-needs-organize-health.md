# Scene “待整理”健康标记—实现参考

> 2026-07-10 代码审计与重构结果。本文区分 Scene 内容复核、结构映射、正文定位和跨章建议，避免用一个“已处理”状态压平不同语义。

## 1. 原问题与关键更正

Scene Workbench 的 `needs_organize` 同时包含 Scene 结构问题和正文定位问题。旧前端的“采用/标记已检查”只处理内容复核，却给人“所有问题都已清除”的印象。

代码审计后需特别更正三个误解：

- `SceneSpan.mapping_status` 的实际取值是 `exact / reanchored / chapter_only / unresolved`，不存在 `resolved`。
- 跨章 Scene 检测只产生融合建议，不创建、修改或“清除” `SceneSpan`。`chapter_only` 来自 Scene 自身的物理映射信息不足，不是跨章任务的处理状态。
- AI 融合不会把 `mapping_status` 更新为某种“已解决”值。融合采用和正文定位确认是两个独立决策。

另一个更严重的实现缺陷是：以前 Scene 更新 `status/source` 时会通过重建 span 来同步生命周期，可能丢失已有的精确 offset、source draft/hash、anchor 及 working span。

## 2. 单一健康诊断

顶层健康筛选保持四项：

- `unreviewed`：待处理、未复核或 `needs_review`。
- `unassigned`：未关联章节。
- `missing_setup`：缺少目标、冲突、必须发生或禁止发生等关键设定。深度导入 Scene 若以
  `structure_meta.core_conflict_status=not_applicable` 明确表示正文没有真实核心冲突，则空
  `core_conflict` 不算缺设定；缺标记、`uncertain` 或手工 Scene 的空冲突仍按缺设定处理。
- `needs_organize`：需要结构整理、正文定位确认或处理 Scene 融合建议。

`needs_organize` 的子原因固定为：

| code | 含义 | 对应操作 |
|---|---|---|
| `manual_organize` | `structure_meta.needs_organize` 显式标记 | 整理映射/复核 |
| `duplicate_chapter` | Scene 内章节关联重复 | 整理映射 |
| `overlapping_span` | 两个 Scene 在同一正文版本上的精确正文 offset 真实重叠 | 整理映射或融合 |
| `chunk_chapter_mismatch` | `scene_chunks` 与 `chapter_ids` 不一致 | 整理映射 |
| `source_mapping_chapter_only` | 只能定位到章节 | 确认仅按章节关联 |
| `source_mapping_unresolved` | 物理片段无法唯一定位 | 确认章节级精度或重新整理映射 |
| `pending_scene_fusion_suggestion` | 有持久化的待处理融合建议 | 直接打开对应建议 |

工作台在同一次诊断中生成：

- 用于筛选的顶层 health key。
- 用于分页计数的 `SceneHealthSummary`。
- 用于页头子计数的 `SceneHealthSummary.breakdown`。
- 用于行内标签和主操作的 `SceneWorkbenchItem.health_details`。

这使筛选、计数、行内解释和默认按钮不再分别重算。

## 3. SceneSpan 同步责任

`SceneRepository` 按变更字段执行最小同步：

| Scene 变化 | SceneSpan/关联处理 |
|---|---|
| `chapter_ids` | 只同步 `scene_chapter_links` |
| `scene_chunks` | 重建对应 `scene_spans` |
| `status/source` | 只镜像 span 的生命周期字段 |
| 显式清空物理映射 | 删除 span |

采用、标记已检查或修改来源不再重建 span，因此保留 `exact/reanchored`、working span、source binding 和 anchor。

## 4. 复核与定位确认

### 4.1 Scene 内容复核

`POST /api/outline/scene-workbench/review` 统一接收 Scene 列表和 review 命令，由后端设置 `status/reviewed_at/needs_review/needs_organize`。前端不再用通用 Scene PATCH 拼装这组业务字段。

采用一个 Scene 只能证明内容已检查，不意味着正文物理定位或跨章融合建议已处理。若仍有待办，前端会提示“Scene 已采用，仍有 N 项待处理”。
重复章节、跨 Scene 重叠和 chunk/chapter 不一致始终由当前映射重算，不会因
`reviewed_at` 或 `canonical` 而被隐藏。这样多问题 Scene 在采用后会自然切换到“整理映射”。

同一 review 接口还提供独立的 `ignore_structure / restore_structure` 命令。前者只记录作者
“无需整理”的裁决并持续隐藏该 Scene 当前及未来的结构类提醒；后者恢复结构提醒。两者都不
改变 Scene 内容状态、复核状态、章节映射或 SceneSpan，正文定位和融合建议也不受影响。

### 4.2 正文定位确认

`POST /api/outline/scene-workbench/source-mapping/review` 要求前端携带当前 span fingerprint。后端仅记录：

- 用户接受“仅按章节关联”的有限精度。
- 确认时的 fingerprint、时间和方式。

它绝不会把 `chapter_only/unresolved` 改成 `exact/reanchored`。当 span 变化导致 fingerprint 不同，旧确认自动失效。RAG/context 仍排除不精确 span，遵守“人工接受有限精度≠生成自动证据”。

## 5. Scene 融合建议持久化

`scene_fusion_suggestions` 由 outline 模块拥有，保存：

- 深度导入 workflow、建议类型/动作、来源 Scene 列表、source fingerprint 和章节范围。
- 建议内容、理由、置信度和 scan trace。
- `pending / adopted / dismissed / stale` 状态以及处理后 Scene。

Phase 1c 将需要作者处理的结果持久化为 `pending`；高置信、精确的“保持分开”结果持久化为隐藏的 `dismissed` 决策，用于阻止智能去重重复询问，但不会增加 Workbench 待办。相同 source fingerprint 使用幂等 key 复用；任一来源 Scene 的语义、语义状态或映射字段变化后，旧建议变为 `stale`。

Workbench 返回 pending 数量，并通过专用查询接口在刷新后恢复横幅和行内按钮。`fusion/save` 接收可选 `suggestion_id`，保存成功后在同一事务中标记 `adopted`。用户可逐条处理或批量忽略；不提供“全部接受”，以免绕过主 Scene 选择、编辑和合并确认。

## 6. 前端主操作优先级

每行只显示当前最高优先级操作：

1. 待处理、未复核或 `needs_review` → `采用` / `标记已检查`。
2. 有 pending Scene 融合建议 → `查看融合建议`。
3. `chapter_only/unresolved` → `确认章节定位`。
4. Scene 内重复章节或 chunk 不一致 → `整理映射`。
5. 未关联章节 → `关联章节`。
6. 缺关键设定 → `补全设定`。
7. 无待办 → `编辑`。

多问题 Scene 完成一项后刷新为下一项。健康标签可点击并执行对应操作。桌面端显示“上下文主按钮 + 编辑 + 更多”，移动端显示“主按钮 + 更多”；“更多”固定包含打开写作、合并和拆分。

单选时批量操作条直接显示并执行该 Scene 的真实主操作，不再进入混合选择提示。结构整理弹层
同时提供“标记为无需整理”，成功后可从 Scene 更多菜单恢复整理提醒。

批量选择同类 Scene 时显示具体动作；混合选择时按问题类型列出数量和动作，每次只处理一组，
成功后仅移除已处理组的选择，失败则保留原选择，不执行含义不明的“一键清除”。

## 7. 关键代码入口

| 职责 | 位置 |
|---|---|
| 健康诊断、review、定位确认、建议处理 | `backend/modules/outline/scene_workbench.py` |
| Scene/SceneSpan 同步和建议仓库 | `backend/modules/outline/repositories.py` |
| SceneSpan 与持久建议模型 | `backend/modules/outline/models.py` |
| Workbench HTTP 契约 | `backend/modules/outline/api.py`, `schemas.py` |
| Phase 1c 融合与建议生成 | `backend/modules/imports/scene_fusion_phase1c.py` |
| 上下文主按钮与批量交互 | `frontend-console/views/sceneWorkbenchView.js` |
| API wrapper | `frontend-console/api.js` |
