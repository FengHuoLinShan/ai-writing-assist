# Module: outline / 大纲与结构管理模块

## 定位

outline 模块负责把事实层资产组织成“可执行的剧情计划”。

作者界面把人工 Scene/结构编辑视为普通工作内容；AI 合并、拆分和补全
先返回可编辑预览，只有显式应用后才写入普通 Scene。正文 Scene 提取统一由 imports 的
Scene stage 负责。旧 `candidate` 仅兼容读取，不再允许
作为新 Scene 写入状态；`needs_review` 是注意原因，不是第二套生命周期。

当前活跃对象：

- `plot_threads`：剧情线
- `outline_arcs`：篇章纲
- `scenes`：最小叙事单元
- `scene_spans`：从 `scene_chunks` 派生的只读物理片段索引
- `scene_chapter_links`：Scene 与章节的轻量关联
- `foreshadowing_plans`：伏笔计划
- `reveal_plans`：揭示计划

## 架构现状

- HTTP 入口在 `api.py`
- 业务逻辑在 `services.py`
- AI 结构生成拆在 `generation/`
- 当前**已有** `facade.py`，主要对外提供 Scene 相关稳定接口，供 rag、world/map 等模块跨 seam 调用

## 职责

- 剧情线、篇章纲、Scene、伏笔、揭示计划的 CRUD
- Scene 顺序重排
- 按章节查询相关 Scene
- 根据 AI 参考资料确认记录，发起结构生成任务
- 为其他模块提供 Scene 查询能力

## 关键服务

- `PlotThreadService`
- `OutlineArcService`
- `SceneService`
- `SceneWorkbenchService`
- `ForeshadowingPlanService`
- `RevealPlanService`
- `PlotStructureGenerator`

## `generation/` 子模块

`PlotStructureGenerator` 不是神类，当前职责被拆为：

- `context_builder`：组装结构生成所需上下文
- `parser`：调用 LLM、解析 JSON、处理重试/降级
- `persister`：把结果写入 thread / arc / scene / foreshadowing / reveal
- `models`：生成流程专用 Pydantic 模型

## API

```http
POST   /api/outline/threads
GET    /api/outline/threads
GET    /api/outline/threads/{thread_id}
PATCH  /api/outline/threads/{thread_id}
DELETE /api/outline/threads/{thread_id}

POST   /api/outline/arcs
GET    /api/outline/arcs
GET    /api/outline/arcs/{arc_id}
PATCH  /api/outline/arcs/{arc_id}
DELETE /api/outline/arcs/{arc_id}

POST   /api/outline/scenes
GET    /api/outline/scenes
GET    /api/outline/scenes/ordered
GET    /api/outline/scenes/by-chapter
GET    /api/outline/scenes/{scene_id}
PATCH  /api/outline/scenes/{scene_id}
DELETE /api/outline/scenes/{scene_id}
POST   /api/outline/scenes/reorder
POST   /api/outline/scenes/split

GET    /api/outline/scene-workbench
POST   /api/outline/scene-workbench/review
POST   /api/outline/scene-workbench/source-mapping/review
PATCH  /api/outline/scene-workbench/scenes/{scene_id}/mapping
POST   /api/outline/scene-workbench/merge/preview
POST   /api/outline/scene-workbench/merge
POST   /api/outline/scene-workbench/split/preview
POST   /api/outline/scene-workbench/split
POST   /api/outline/scene-workbench/fusion/preview
POST   /api/outline/scene-workbench/fusion/save
GET    /api/outline/scene-workbench/fusion-suggestions
POST   /api/outline/scene-workbench/fusion-suggestions/dismiss

POST   /api/outline/foreshadowing
GET    /api/outline/foreshadowing
GET    /api/outline/foreshadowing/{plan_id}
PATCH  /api/outline/foreshadowing/{plan_id}
DELETE /api/outline/foreshadowing/{plan_id}

POST   /api/outline/reveals
GET    /api/outline/reveals
GET    /api/outline/reveals/{plan_id}
PATCH  /api/outline/reveals/{plan_id}
DELETE /api/outline/reveals/{plan_id}

POST   /api/outline/generate
```

## 对外 facade

跨模块调用优先走 `modules.outline.facade`。`facade.py` 是兼容 re-export hub，
内部按 seam 拆到 `scene_facade.py`、`structure_dedup_facade.py`、
`deep_import_repair_facade.py` 和 `foreshadowing_facade.py`。子 facade 只提升
outline 内部 locality；旧 `modules.outline.facade.*` 仍是跨模块公共 seam 和测试
monkeypatch 路径。

当前常用入口包括：

- `get_scene()`
- `get_scene_contract()`
- `get_scenes_by_novel()`
- `get_scenes_by_chapter()`
- `get_scene_spans_by_chapter()`
- `get_scene_spans_for_scene()`

## 与 writing 的依赖方向

outline 可以只读依赖 `modules.writing.facade` / `modules.writing.contracts` 加载最新
草稿和章节索引，供结构生成上下文、Scene 工作台和跨章 Scene 检测使用；outline 不直接
访问 writing 的 model / repository / service。

writing 侧不在服务模块顶层依赖 outline facade。断章同步 Scene chunk 和冲突检查读取
Scene contract 都通过可注入 provider 完成；默认 provider 在调用时 lazy import
`modules.outline.facade`，因此旧的用户流程、HTTP/API schema 和 wire shape 保持不变。

## Scene 设计要点

- `scenes` 是当前最小叙事单元的权威表
- `scene_index` 是逻辑顺序
- `scene_chunks` 保存 Scene 到正文物理区间的映射
- `scene_spans` 是从 `scene_chunks` 派生的只读查询索引，记录
  `scene_id/chapter_index/content_mode/source_draft_id/source_content_hash/offset/paragraph/part_no/mapping_status/anchor_hash`
- `structure_meta` 保存结构整理元信息，如 `needs_organize`、`reviewed_at`、`merged_into_scene_id`、`merged_from_scene_ids`、`split_from_scene_id`、`split_at_chapter_index`
- 深度导入 / 手动融合等自动整理来源通过 `source` 与 `structure_meta` / `provenance_meta` 暴露给管理筛选；手动融合新 Scene 使用 `source="manual_fusion"`
- `scene_chapter_links` 与 `scene_spans` 表达章节映射；旧章卡 JSON 语境不属于当前 ORM schema
- 写作页、地图摘要、RAG `scene_id` 关联都依赖 `scenes` 表；RAG 精确正文归因通过
  outline facade 只读获取 `SceneSpanContract`

`scene_spans` 不替代 `scene_chunks`，也不是前端编辑入口。`SceneRepository` 按字段责任同步：
`chapter_ids` 只更新 `scene_chapter_links`，只有 `scene_chunks` 变化才重建
`scene_spans`，`source/status` 只镜像 span 生命周期字段，清空物理映射时才显式
删除 span。因此采用、标记已检查或来源变更不会丢失精确定位、source hash、
anchor 或 working span。默认只读查询排除 `deprecated` span。跨模块只允许调用 `modules.outline.facade` 中的
`get_scene_spans_by_chapter()` 和 `get_scene_spans_for_scene()`。

span 按 `(novel_id, scene_id, content_mode, part_no)` 唯一。正文版本变化后以
anchor 文本/hash 重定位；唯一命中是 `reanchored`，仅知章节是 `chapter_only`，
歧义或缺失是 `unresolved`。非精确 span 不参与自动证据归因，并作为
Scene 工作台“待整理”健康项进入人工复核。

`scene_summary_checkpoints` 只摘要可见截止点之前的 span，并以 source refs 和
`based_on_hash` 校验有效性。缺少/失效时降级为可见原文摘录，不回退完整
Scene 卡摘要。`get_reader_reveal_decision()` 使用 `reveal_plans` 与截止章确定读者可见性，
同章无可判定顺序的揭示默认排除。

## Scene 工作台

Scene 工作台是 Scene 管理、章节映射和结构整理的主入口，直接位于大纲页
`outline/scenes` 子标签；旧 `scene/{scene_id}` 路由兼容重定向到该入口并保留
Scene 定位，不再维护第二套 Scene 管理 UI。

第一版健康项固定为：

- `未复核`：导入来源带 `needs_review`、低质量或缺少人工检查标记；它是注意原因
- `未关联章节`：Scene 没有关联章节，或存在有正文草稿但未归入任何 Scene 的章节
- `缺设定`：目标、核心冲突、必须发生、禁止发生等关键字段缺失
- `待整理`：人工标记、Scene 内重复章节映射、chunk/chapter 不一致，或
  `chapter_only` / `unresolved` 来源映射等需要复核的信号

顶层 `health` wire shape 保持不变。工作台同时返回每行 `health_details` 和汇总
`breakdown`，其中待整理子原因固定为 `manual_organize`、
`duplicate_chapter`、`overlapping_span`、`chunk_chapter_mismatch`、
`source_mapping_chapter_only`、`source_mapping_unresolved` 和
`pending_scene_fusion_suggestion`。同一章中 span 不重叠的多个独立 Scene 是合法状态。筛选、计数、响应和行内操作共用同一次
健康诊断，避免同一 Scene 在不同界面口径不一致。

Scene 内容复核由 `scene-workbench/review` 统一设置 `status`、`reviewed_at`、
`needs_review` 和 `needs_organize`，前端不再拼装这些业务字段。正文定位确认是
独立操作：`source-mapping/review` 记录当前 span fingerprint 和“接受仅按章节
关联”决策，但不改写 `mapping_status`。自动证据归因仍只接受
`exact/reanchored`，`chapter_only/unresolved` 即使经人工确认也继续排除。
复核仅清除人工 `needs_organize` 标记；重复、重叠和 chunk/chapter 不一致由当前
映射重算，不会因 Scene 已采用而被隐藏。

跨多章 Scene 是正常创作形态，不作为默认风险。合并 / 拆分必须先请求影响预览，
再二次确认执行；预览只提示章节映射、字段、剧情线、伏笔 / 揭示和地图摘要影响，
不自动阻断。合并来源 Scene 标记为 `deprecated` 而不是硬删除；拆分只调整映射并
创建新 Scene，不修改正文内容。

工作台使用 `skip/limit` 服务端分页。显式 `selected_scene_id` 不在请求页时，后端
将返回窗口对齐到目标 Scene 所在页，并通过响应 `skip` 告知实际窗口起点；目标不属于
当前 novel 或筛选结果时返回 404。前端在用户主动翻页或修改筛选时清除旧 Scene 定位，
避免 URL 与详情指向不同对象。

Scene 工作台区分机械合并和 AI 融合建议。机械合并由目标 Scene 吸收来源 Scene，
来源标记为 `deprecated`；AI 融合先由用户选择 `primary_scene_id`，`fusion/preview`
返回可编辑建议、字段来源引用和冲突提示，再由用户选择保留原 Scene、保存并废弃原
Scene、放弃结果或继续编辑后保存。只有“保存并废弃原 Scene”会把来源 Scene 标记为
`deprecated`；所有融合新 Scene 都记录 `structure_meta.fused_from_scene_ids` 和主
Scene 信息，并在采用时写入 `adopted_at`、来源并清除 `needs_review`。

跨章检测只创建 outline-owned 建议记录，不修改 Scene 或 `SceneSpan`。建议以
`pending/adopted/dismissed/stale` 管理，持久化 task、来源 Scene、source fingerprint、
建议内容与处理结果。相同 fingerprint 幂等复用；来源 Scene 的语义或映射字段
变化后，旧建议标记为 `stale`。`fusion/save` 可带 `suggestion_id`，保存成功时
在同一事务中标记 `adopted`；用户可逐条融合或批量忽略，不提供绕过主 Scene
选择、编辑和确认的“全部接受”。

剧情线、篇章纲、伏笔和揭示列表支持按 `status`、`source`、`workflow_id`、
`needs_review`、分页参数筛选；`source` / `workflow_id` / `needs_review` 来自
`provenance_meta`，用于整理深度导入 Phase 3 结构资产。

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
