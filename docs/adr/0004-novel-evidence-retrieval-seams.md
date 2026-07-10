# ADR-0004 — 小说检索沿用现有模块并以原文为证据事实源

- **状态**: Accepted
- **日期**: 2026-07-10

## 背景

作者需要在长篇正文、Scene 结构、世界对象和人物知识之间搜索、读取和追踪证据，
同时不能让旧 RAG chunk、未重定位的 Scene 映射或未来剧情进入读者/角色视角。

仓库已有明确所有权：

- writing 拥有正文版本；
- outline 拥有 Scene 与正文片段映射；
- rag 拥有可删除重建的召回索引；
- context 拥有上下文选择、可见性与追踪；
- world 拥有对象和人物知识。

## 决策

### 1. 不创建平行的 retrieval/narrative 模块

小说检索继续通过 writing/outline/rag/context/world 的 `contracts.py` / `facade.py`
协作。不创建 `manuscript_versions`、`chapters`、`source_blocks`、
`narrative_units` 或 `unit_realizations`；现有 `writing_drafts`、`scenes` 和
`scene_spans` 已承担这些职责。

context 内的 `NovelEvidenceService` 是集中业务编排的深模块，不是新业务子域。

### 2. writing 是正文证据事实源

- `canonical` 选择每章最新非废弃 `published`；缺失时告警，不回退 working。
- `working` 选择最新非废弃版本。
- published 不可原地修改；编辑使用 copy-on-write 并返回新 draft ID。
- 常规删除改为 `deprecated`，版本号永不重排。
- `SourceRangeRef` 以 draft/version/content mode、章内 offset 和 source/range hash
  提供稳定范围引用；不新建 source-range 表。

### 3. Scene 映射和摘要都是版本绑定派生数据

`scene_spans` 保存 source draft/hash、content mode、mapping status 和 anchor hash。
只有唯一重定位且 hash 一致的 span 可自动归因证据；`chapter_only` 和
`unresolved` 只可人工复核。

`scene_summary_checkpoints` 只使用可见截止点之前的精确 span。缺失或 hash
失效时降级为可见原文摘录，不回退可能包含未来内容的完整 Scene 卡摘要。

### 4. RAG 只召回候选，不作为证据事实源

canonical/working 索引分开幂等重建；正文 chunk 的 `source_id` 指向具体
draft，并保存 source hash。`rag_index_state` 合并同一 novel/chapter/mode 的标脏请求，
任务执行时始终索引最新 requested source。

证据返回前必须从 writing 重读原文并校验 source hash。过期 chunk 被丢弃并告警；
工作稿索引更新中时，字面 grep 仍直读 writing，智能搜索不回退旧 chunk。

### 5. 可见性是分层硬过滤

`VisibilityContext` 支持 author/reader/character。reader 必须提供截止章，character
还必须提供人物 ID；可选同章 Scene/offset 截止。writing、RAG、SceneSpan/
checkpoint、ReaderRevealPolicy 和 CharacterKnowledge 各层先过滤，context 返回前
再校验来源位置。

同章无法确定先后的知识/揭示默认排除。缺少学习章的旧 CharacterKnowledge
只有显式 `is_public_baseline=true` 才可见。

### 6. evidence link 只解释 provenance

`evidence_links` 使用现有 `TargetRef` 指向对象、人物知识或结构字段，保存
claim path、evidence type、source ref、precision、status 和 provenance。它不引入
统一 Claim 主表，也不判定事实真假。

自动流水线只在 schema 校验通过且 quote 能在可见、版本绑定原文中唯一定位时，
在事实写入同一 savepoint 记录 active link。无法定位只记 `needs_review`，不伪造 offset。

### 7. 不实现自治检索 Agent

grep/search/read/inspect/trace 都是确定性 HTTP/facade 接口。受控 LLM 工作流只能消费
context 已编译、已校验的证据包，不自主选择工具或跨模块改写事实。

## 影响

- 新增 `scene_summary_checkpoints`、`rag_index_state` 和 `evidence_links`，它们都是派生/追踪数据，
  不是平行正史。
- 新增字段和接口为 additive；保留 `/api/rag/retrieve`、`RagChunkResponse.text`、
  `CompileOptions.visible_until_chapter` 与旧 `reveal_mode` 适配。
- 不引入新运行时依赖、向量数据库、前端框架或 Agent 框架。
- 派生 RAG 数据可全部删除后从 writing 与 outline 重建。

## 备选方案

### A. 新建统一 retrieval 模块和原文表

拒绝。它会复制 writing/outline 所有权，并创建需要双向同步的第二份正文事实。

### B. 直接把 RAG chunk text 作为证据

拒绝。chunk 可过期、被重分块或来自不同 content mode，无法保证版本与可见性。

### C. 只在 context 返回前做一次可见性过滤

拒绝。上游召回、摘要或对象搜索可以通过排序、摘要和结果数量侧漏未来信息；
必须在每个数据所有者边界先过滤，再由 context 复核。
