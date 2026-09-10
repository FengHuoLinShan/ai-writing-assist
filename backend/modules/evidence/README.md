# Evidence 模块

小说证据的唯一领域实现。Evidence 把原 RAG 召回和 Context 编译放在同一所有权边界内，
但保留两条清晰的内部流水线：

- `indexing/`：chunk、混合检索、embedding、索引新鲜度、Scene 映射、对象出场与四个
  `rag_*` task handler；
- `compilation/`：检索计划、原文回读、可见性、Context Compiler、confirmation、snapshot、
  trace、Activation Profile 和 hidden guard。

两条流水线只共享本模块的 ORM、contracts 和 facade，不建立第二套服务、表或双写。
跨模块生产调用只允许使用 `modules.evidence.contracts` 与 `modules.evidence.facade`；调用方
不得直接读取 `rag_chunks`。内部细节见 `indexing/README.md` 与 `compilation/README.md`。

## 数据与不变量

- 表名保持 `rag_*`、`context_*` 和 `evidence_links`；`context_snapshots` 新增可空
  `consumer_novel_id`，用于记录同 owner RP consumer，`novel_id` 仍是资料来源项目；
- task type、recovery policy、owner scope 与 action/payload 保持不变；
- 所有查询和写入保持 owner + `novel_id` 隔离；
- reader/character 可见性、hidden truth guard、confirmation 精确失效、snapshot 生命周期、
  retrieval trace 和索引 freshness 均沿用原行为；
- 检索结果只是候选，编译阶段按 source ID/hash 回读 writing 原文并再次执行可见性门禁。
- chapter-text chunk 按具体 Writing draft/hash 并存。普通作者 Context 自动物化当前
  Writing manifest；RP 传入冻结 source revision manifest。候选在排序前就过滤草稿/hash，
  历史版本回读不会被新章节版本覆盖。作者 evidence/manuscript search 同样先构建当前
  draft/hash manifest；低层 indexing retrieve 仍可诊断孤立或失败 chunk，不作为作者证据直接展示。
- `compile_interaction_story_context()` 是 Evidence 拥有的深层稳定入口；它固定
  `consumer_action=interaction.story`、读者/人物知识与章节/offset 截止。调用方可传本轮
  剩余预算，Evidence 将其限制在 0～16K；必需资料无法容纳时返回 blocker。
- `author_safe + scene_id` 固定以当前 Scene 为同章截止点；后续或跨越截止点的正文候选在
  原文回读阶段 fail closed，`author_full` 不自动增加该截止。

## HTTP 与 import 边界

canonical HTTP 路径为 `/api/evidence/indexing/*` 与
`/api/evidence/compilation/*`。旧 `/api/rag/*`、`/api/context/*` 与
`modules.rag`、`modules.context` 已在兼容准备版本完成固定 SHA 生产发布后退场。

## 验证

```bash
cd backend
pytest modules/evidence/indexing/tests modules/evidence/compilation/tests -q
```

统一地图沿用本模块确认与来源回读：`world.map_atlas.structure` 只消费原确认中保留的空间资料；
图元阅读预览通过已有 `inspect_novel_target` / `read_novel_evidence` 获取受限可见性，
不新增检索 scope、索引表或第二套证据服务。

## 指定对象的补查

`retrieve_focused_evidence` / `revalidate_focused_evidence` 是 compilation 拥有的共享只读
专项能力，供导入、地图和写作消费。它复用 World 身份/一跳邻接和 Writing 冻结原文扫描，
输出可回读证据、完整性回执与独立预算后的 CompiledContext；只读结果不携带资产写入授权。
深度固定为 0 或 1，内部 continuation 和异步恢复沿用现有任务表，不新增检索设施或业务表。
HTTP 与内部边界、来源范围及恢复详见 compilation/README.md。
原文选择支持 `start_offset=0`，以半开区间定位章首；缺失或负数起点仍拒绝。地图的已保存图元
来源通过既有 pinned_refs 预填，仍受作者排除、预算、正文版本/hash与可见性重验约束。

## Agent 读取出口（ADR-0023）

Assistant 的搜索、精确原文、当前对象/Scene 和项目事项投影均经本模块出口。
author-only inspection 加入 World 工作稿、采用地图与 Scene 人物卡/剧本；reader/character
不能从这些作者入口获得内容。引用与实际读取分开计量，确认前重新物化/重验原来源。
资产失效事件在原事务向组合根注册的 source.changed port 发出；Evidence 不调度主动任务，
也不取得业务写入权限。专门 confirmation preview 与确认使用同一参数和指纹。

`list_author_task_evidence` 是作者待办的有界只读出口；调用方必须为作者视角，复用 Project
的日期/状态/分页查询，不将工作事项当成角色知识。TargetRef.target_path 继续只表示字段
路径，不复用为任意查询表达式。

writing_candidate 只对作者提供有界候选摘录及 ID/hash/版本定位。它不能伪装为 working 或
canonical 的 SourceRangeRef，reader/character 与越过章/Scene 范围的读取被拒绝。
read_organization_evidence 只返回原整理状态与恢复投影，不把任务进度当正文或世界事实。

### 作者规划与历史的读取边界

`world_bible_page_history`、`foreshadowing_plan`、`reveal_plan` 仅在无截止点的作者范围内读取，
分别标注历史非当前事实、规划非已发生故事。完整作者地图也不能进入带截止点的资料包；章节
阅读预览继续由 World 提供。地图读取附最近20张图片的状态及结果引用，不返回私有 URL、
存储 key 或生图 Prompt。正文精确回读、排除、同 owner 固定 RP 来源版本约束不变。
