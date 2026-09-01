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
