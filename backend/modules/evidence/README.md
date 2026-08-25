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

- 表名保持 `rag_*`、`context_*` 和 `evidence_links`，没有 schema migration；
- task type、recovery policy、owner scope 与 action/payload 保持不变；
- 所有查询和写入保持 owner + `novel_id` 隔离；
- reader/character 可见性、hidden truth guard、confirmation 精确失效、snapshot 生命周期、
  retrieval trace 和索引 freshness 均沿用原行为；
- 检索结果只是候选，编译阶段按 source ID/hash 回读 writing 原文并再次执行可见性门禁。

## 兼容期

canonical HTTP 路径为 `/api/evidence/indexing/*` 与
`/api/evidence/compilation/*`，主动调用方已全部迁入这两个前缀。`/api/rag/*` 与
`/api/context/*` 仍挂载同一组 Evidence endpoint，只等待兼容准备版本以固定 SHA
完成一次生产发布后退场。`modules.rag` 与 `modules.context` 同期仅作薄 import
alias，不注册 handler、不声明 ORM、不创建 service，也不拥有任何写入路径。

## 验证

```bash
cd backend
pytest modules/evidence/indexing/tests modules/evidence/compilation/tests -q
```
