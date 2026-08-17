# Module: outline / 大纲与结构管理模块

## 定位

outline 模块负责把事实层资产组织成“可执行的剧情计划”。

作者界面把人工 Scene/结构编辑视为普通工作内容；AI 合并、拆分和补全
先返回可编辑预览，只有显式应用后才写入普通 Scene。正文 Scene 提取统一由 imports 的
Scene stage 负责。旧 `candidate` 仅兼容读取，不再允许
作为新 Scene 写入状态；`needs_review` 是注意原因，不是第二套生命周期。

当前活跃对象：

- `story_outline_heads` / `story_outline_revisions`：小说总纲当前指针与不可变版本
- `plot_threads`：剧情线
- `outline_arcs`：篇章纲
- `scenes`：最小叙事单元
- `scene_spans`：从 `scene_chunks` 派生的只读物理片段索引
- `scene_chapter_links`：Scene 与章节的轻量关联
- `scene_fusion_suggestions`：融合、替换和重复提取的待处理/历史决定
- `foreshadowing_plans`：伏笔计划
- `reveal_plans`：揭示计划

## 架构现状

- HTTP 入口在 `api.py`
- 业务逻辑在 `services.py`
- P20 当前层创作由 `p20_context.py` / `p20_service.py` 编排；`generation/` 只保留深度导入
  Scene 证据结构化与 v1 完成预览兼容
- 当前**已有** `facade.py`，主要对外提供 Scene 相关稳定接口，供 rag、world、writing 等模块跨 seam 调用

## 职责

- 剧情线、篇章纲、Scene、伏笔、揭示计划的 CRUD
- Scene 顺序重排
- 按章节查询相关 Scene
- 根据 AI 参考资料确认记录，在当前页面发起剧情线、篇章纲或 Planned Scene 创作任务
- 为其他模块提供 Scene 查询能力
- 为正文生成与独立审查编译 version-bound、只读的 Scene execution bundle

## 关键服务

- `PlotThreadService`
- `OutlineArcService`
- `SceneService`
- `SceneWorkbenchService`
- `ForeshadowingPlanService`
- `RevealPlanService`
- `PlotStructureGenerator`
- `P20GenerationService`
- `P20ApplyService`

## `generation/` 子模块

`PlotStructureGenerator` 只服务深度导入 Phase 3，当前职责被拆为：

- `context_builder`：组装结构生成所需上下文
- `parser`：只根据已采用 Scene 证据调用 Phase 3 strict schema；无 Scene 时返回空/复核
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
POST   /api/outline/scene-workbench/chapters/{chapter_index}/scenes/{scene_id}
POST   /api/outline/scene-workbench/chapters/{chapter_index}/scenes
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
POST   /api/outline/generate/apply
```

## 当前层 AI 创作与信息推进

剧情线页、篇章纲页、Scene 工作台分别提供“AI 创作剧情线”“AI 创作篇章纲”“AI 创作细纲”。
三者都要求当前 StoryOutline，每次只生成或修订当前层，其他层仅作为上下文；不在生成中心
建立 P20 入口。create 允许并行方案并在 preview 展示重叠，revise 只能更新显式选择资产。
总纲、选择资产或确认 context 漂移时 apply 返回 409。

PlotThread 聚合作者侧信息推进。模型输出一条 movement 中的隐藏、暗示、局部揭示和兑现节点，
服务确定性投影到伏笔/揭示两张底层表，共享 `information_movement_id`。RevealPlan 和
ForeshadowingPlan 都用 `related_thread_ids` 关联一到多条同项目线程；旧计划保持空关联，在线程
页未归类区域人工分配。线程进入历史不级联计划，最后一个 active 关联消失后计划重新归类为
unassigned。底层 CRUD 和 reader reveal decision 保持。

OutlineArc 只能引用已有 PlotThread；Planned Scene 新建时没有正文 chunks/anchors，工作台显示
“计划中”，建立真实映射后转为 materialized。P20 修订不能更改已有正文映射。正文 Scene
提取继续进入 imports 深度导入。

P20 confirmation 使用 `budget_tokens=0`，完整总纲、作者确认 context、相关结构、信息推进、
人物 Top-6 和非人物对象 Top-16 进入 provider；人物候选经 world facade 全分页加载后再按作者
指令、总纲、Scene 与结构相关性选择，不受单页 50 条限制。不做应用层输入裁剪。结果是 strict 可编辑
preview，采用时在单一 savepoint 中原子写入，并记录总纲 revision、context fingerprint、task、
采用时间和修订前值。

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
- `get_scene_execution_bundle(db, novel_id, scene_id)`：返回可 `dataclasses.asdict()` 的
  `SceneExecutionBundleContract`；冻结当前总纲 revision/version/content hash、
  `story_execution_profile.v1`/hash、Scene 的 POV 与 execution metadata、缺字段、精确
  `upstream_manifest(type/id/version/hash)` 和 contract hash。缺当前总纲时明确返回
  `current_story_outline` omission，不伪造上游引用，也不写入 Scene 或正文。

StoryOutline revision 的 provenance 持有 version-bound execution profile：作者未显式提供时，
服务从采用版的 creative core、剧情线收束方向与宏观状态变化确定性派生；恢复历史 revision
继承目标 revision 的 profile。profile 属于 story layer，不复用 World Bible 页面。

## 与 writing 的依赖方向

outline 可以只读依赖 `modules.writing.facade` / `modules.writing.contracts` 加载最新
草稿和章节索引，供结构生成上下文、Scene 工作台和跨章 Scene 检测使用；outline 不直接
访问 writing 的 model / repository / service。

writing 侧不在服务模块顶层依赖 outline facade。冲突检查读取 Scene contract 通过可注入
loader 完成，默认 loader 在调用时 lazy import `modules.outline.facade`。

## Scene 设计要点

- `scenes` 是当前最小叙事单元的权威表
- `scene_index` 是逻辑顺序
- `scene_chunks` 保存 Scene 到正文物理区间的映射
- `scene_spans` 是从 `scene_chunks` 派生的只读查询索引，记录
  `scene_id/chapter_index/content_mode/source_draft_id/source_content_hash/offset/paragraph/part_no/mapping_status/anchor_hash`
- `structure_meta` 保存结构整理元信息，如 `needs_organize`、可恢复的 `organize_ignored / organize_ignored_at / organize_ignored_by` 人工裁决、`reviewed_at`、`merged_into_scene_id`、`merged_from_scene_ids`、`split_from_scene_id`、`split_at_chapter_index`
- 深度导入 / 手动融合等自动整理来源通过 `source` 与 `structure_meta` / `provenance_meta` 暴露给管理筛选；手动融合新 Scene 使用 `source="manual_fusion"`
- `scene_chapter_links` 与 `scene_spans` 表达章节映射；旧章卡 JSON 语境不属于当前 ORM schema
- 写作页与 RAG `scene_id` 关联依赖 `scenes` 表；RAG 精确正文归因通过
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

写作台只通过两个章节级快速接口补充当前参考：按 Scene ID 关联时服务端锁定
同项目 Scene，原子合并、去重 `chapter_ids`，并保留 `scene_chunks`；仅传 `title`
快速新建时，服务端在项目级顺序锁内分配末尾 `scene_index`，以 `manual/draft`
一次事务完成创建与关联。两个接口都先校验章节存在和项目边界，只创建
章节级关联，不伪造正文位置 `scene_chunks`。

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
作者可用同一 review 接口的 `ignore_structure` 把这些结构提醒永久标记为无需整理，并用
`restore_structure` 恢复；裁决只增删 `structure_meta` 中的忽略元数据，不改变 Scene 状态、
复核状态、映射或 SceneSpan，也不隐藏正文定位和融合建议。

跨多章 Scene 是正常创作形态，不作为默认风险。合并 / 拆分必须先请求影响预览，
再二次确认执行；预览只提示章节映射、字段、剧情线和伏笔 / 揭示影响，
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
伏笔/揭示列表另支持 `related_thread_id` 与 `unassigned`，供剧情线页统一时间线和未归类区
消费；作者界面不再提供两者的顶层子标签。

作者触发的生成、分析、故事总纲和 Scene 融合预览使用 ADR-0013 operation receipt。
`POST /api/outline/scene-workbench/fusion/preview-task` 返回 202；完成后只在 Scene 工作台原位
显示“查看预览”，不会晚到重开旧弹窗或整岛刷新。兼容同步 preview 保留一个正式版本并在
OpenAPI 标记 deprecated；来源 Scene 在 worker 写回前按项目和来源指纹重验。

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
