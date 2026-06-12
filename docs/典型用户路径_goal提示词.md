# 典型用户路径 /goal 提示词

> 用途：给后续编码 Agent 直接复制为 `/goal` 的任务提示词。每条提示词对应一条典型网络小说作者使用路径，要求 Agent 按项目现有架构实现、补测或修复到可验收状态。
>
> 来源：`docs/核心业务场景与预期行为.md`、`frontend-console/e2e/scenario-coverage.md`、各模块文档。

## 通用执行约束

所有 `/goal` 都必须遵守：

- 开始前读取 `AGENTS.md`、`CLAUDE.md`、`development-guide.md`、`testing-guide.md`，再读目标模块 README / contracts / facade。
- 不跨模块 import 其他模块的 `models.py` / `repositories.py` / `services.py`；跨模块只走 contracts / facade / DI port。
- API 层保持薄层；复杂业务逻辑放在 service 或已有编排层。
- 所有写入必须受 `novel_id` 限定；危险操作必须保留二次确认。
- 用户/AI/API 动态内容不得未经 `esc()` 或 DOM API 处理后写入 `innerHTML`。
- LLM 输出必须经 Pydantic schema 校验；不得 `eval` / `exec` LLM 输出。
- 受影响模块测试必须通过；公共契约、用户可见行为或数据模型变化必须同步权威文档。
- 涉及真实 LLM 调用的验收路径，必须使用数据库中《诡秘之主 第一部》项目的第 1-3 章真实内容，不使用 mock 替代真实调用。若本地库没有该项目或章节，先通过现有测试种子/导入能力创建同名项目与 1-3 章数据，再执行验收。

---

## 1. 项目创建与管理

```text
/goal 实现并验收“项目创建与管理”用户路径。

背景：
网络小说作者进入系统后，第一件事是创建或选择一个小说项目。项目是全系统根聚合，后续 world / outline / writing / imports / rag / context 数据都必须通过 novel_id 隔离。

目标：
让作者可以在首页完成项目创建、项目列表选择、工作台内项目信息编辑、软删除、回收站恢复与永久删除。

范围：
- 后端主模块：backend/modules/project
- 前端主视图：frontend-console/projectView 及项目工作台面包屑相关逻辑
- 相关测试：project 单测、project E2E、回收站 E2E

必须满足：
- 创建项目时 title 必填，空标题返回 422，前端提示“请输入项目标题”。
- 创建成功后 language 默认 zh，default_reveal_policy 默认 author_safe，并跳转到 /workbench/:projectId/writing。
- 首页项目列表展示标题、题材、创建时间，并支持分页默认每页 20 条。
- 工作台内编辑项目标题、题材、风格基调、目标规模后，面包屑同步刷新。
- 删除项目先软删除并进入回收站；回收站恢复可恢复；永久删除必须二次确认并级联删除当前 novel_id 下关联数据。
- 404 项目不可被继续打开或编辑。

实现约束：
- 不绕过 ProjectService / ProjectRepository 的 novel_id 与 deleted_at 规则。
- 永久删除只允许在用户二次确认路径触发。
- 不影响其他项目的数据。

验收：
- 后端覆盖创建、列表、编辑、软删除、恢复、永久删除、空标题和 404。
- 前端 E2E 覆盖创建后跳转写作视图、列表进入工作台、编辑面包屑刷新、软删除进回收站、恢复、永久删除不可恢复。
- 运行受影响测试和 lint；若现有全量 lint 有预存问题，至少证明本次修改文件通过聚焦 lint。
```
ok



## 2. 文件上传与章节导入

```text
/goal 实现并验收“文件上传与章节导入”用户路径。

背景：
网络小说作者常见入口是导入已有正文。系统需要把 txt/epub/html/htm/mobi/azw3 文件解析为章节草稿，并为后续深度导入、RAG 和写作工作台准备数据。

目标：
让作者在写作工作台上传本地小说文件，系统解析章节、写入 writing_drafts，记录 import_records，并在成功后提示是否启动深度导入。

范围：
- 后端主模块：backend/modules/imports、backend/modules/writing、backend/modules/rag
- 前端主视图：projectView / writingView 的导入入口和结果反馈
- 相关测试：imports 单测、import E2E、import-errors E2E

必须满足：
- 文件白名单：.txt .epub .html .htm .mobi .azw3；其他格式返回 400。
- 文件大小上限 50MB；超限返回 413 或由前端拦截并展示清晰错误。
- 文件名必须使用 os.path.basename 防路径穿越。
- txt 需要编码检测与章节正则分割；解析为空或编码失败时 import_records.status=failed，并展示可读错误。
- 成功导入后每章写入 writing_drafts，version_number=1，status=draft。
- import_records 记录 file_name / file_type / file_size / total_chapters / imported_chapters / status。
- 前端显示上传进度、导入结果“共解析 N 章，成功 M 章”，并提示是否启动深度导入。
- 导入成功后按现有设计触发或准备 RAG 索引任务，避免任务队列爆炸。

实现约束：
- imports 模块不直接访问 rag/writing 内部实现，跨模块走稳定接口或现有编排入口。
- 不接受非白名单扩展名，也不保存可执行路径。
- 空文件不得创建 writing_drafts。

验收：
- 后端测试覆盖成功导入、格式不支持、超大文件、空文件、路径穿越文件名、编码/解析失败。
- 前端 E2E 覆盖成功导入结果、格式错误、超大文件、空文件失败且不创建章节。
- 使用一个小型测试文件验证 UI 可观察结果；不需要真实 LLM。
```
ok




## 3. 深度导入流水线

```text
/goal 实现并验收“深度导入流水线（三遍 Workflow）”用户路径。

背景：
网络小说作者导入正文后，希望系统自动建立可编辑的结构化创作资产：Scene、世界对象、关系、Delta、记忆快照、剧情线、篇章纲、伏笔和揭示计划。

目标：
作者点击“启动深度导入”并选择章节范围后，系统后台完成三阶段流水线：Scene 切分 -> Entity 增量提取 -> 结构分析。浏览器关闭后任务继续执行，重新进入项目时能恢复进度展示。

真实 LLM 验收数据：
- 必须使用数据库中《诡秘之主 第一部》项目的第 1-3 章。
- 不允许用 mock LLM 代替真实 LLM 验收。
- 若数据库中没有该项目或章节，先用现有导入/种子能力创建同名项目和第 1-3 章正文，再运行真实调用。

范围：
- 后端主模块：backend/modules/imports、backend/modules/outline、backend/modules/world、backend/modules/memory、infrastructure/tasks、infrastructure/llm
- 前端主视图：writingView 深度导入入口、进度条、任务恢复提示
- 相关测试：workflow 单测/集成、deep-import E2E、真实同步或手动验收脚本

必须满足：
- 启动接口返回 workflow_id / task_id，async_tasks 创建 deep_import 任务并进入 scene_segmentation phase。
- Phase 1：读取章节正文，按 5 章/批 + 1 章 overlap 策略切分；1-3 章小规模导入应作为单批处理；LLM 输出 scenes[] 并写入 scenes。
- Phase 2：按 scene_index 串行实体抽取；新实体/关系/Delta 写入对应表，自动入库对象标记 canonical 且 content_json._meta.auto_ingested=true；每个 Scene 完成后更新记忆快照。
- Phase 3：基于 Scene 摘要、Delta 流、实体索引生成 plot_threads、outline_arcs、foreshadowing_plans、reveal_plans。
- 前端展示三阶段进度，关闭浏览器后重新打开能查询任务状态并恢复展示。
- 重复导入同一章节范围时必须检测已有派生数据，弹出覆盖警告；用户确认后才允许旧数据 deprecated 并写入新数据。
- 单次 LLM 调用失败重试 3 次；Phase 1 批次失败后降级到逐章切分，仍失败再机械分章。

实现约束：
- 真实 LLM 输出必须使用 Pydantic schema 校验后入库。
- 自动写 canonical 仅限用户确认启动的深度导入流水线，并保留可编辑/可回滚元数据。
- 所有派生数据只处理当前 novel_id 和指定章节范围。
- 不引入 Redis/Celery 或新的多 Agent 框架。

验收：
- 自动化测试可 mock LLM 覆盖状态机、失败降级、重复导入确认、novel_id 隔离。
- 真实 LLM 手动或集成验收必须跑《诡秘之主 第一部》第 1-3 章，并记录生成的 scenes、entities、plot_threads/outline_arcs 数量。
- 前端 E2E 覆盖启动、进度展示、路由切换后恢复、无章节时不显示启动按钮。
```

## 4. 手工写作工作台

```text
/goal 实现并验收“手工写作工作台”用户路径。

背景：
网络小说作者需要长时间在写作工作台中反复写正文、切换 Scene、查看结构提示、保存版本、发布索引，并从正文反向提取章节/Scene 卡。

目标：
让作者在 /workbench/:projectId/writing 中完成正文编辑、暂存、发布、版本历史、断章、Scene 树导航、右侧 Scene 卡联动、实体轻量查询和 AI 章节卡提取。

真实 LLM 验收数据：
- “AI 提取章节卡”路径必须使用数据库中《诡秘之主 第一部》项目的第 1-3 章真实内容。
- 不允许用 mock LLM 代替该路径的最终验收。

范围：
- 后端主模块：backend/modules/writing、backend/modules/outline、backend/modules/rag
- 前端主视图：writingView
- 相关测试：writing 单测、writing E2E、writing-conflict E2E；AI 提取可增加真实调用验收记录

必须满足：
- 进入项目后默认落到 /workbench/:projectId/writing。
- 左侧展示 Scene 树 + Chapter 折叠；未关联 Scene 的章节进入“未归类”。
- 中间编辑器加载上次编辑位置或第一个有草稿章节。
- 右侧只读展示当前 Scene 卡字段：goal / core_conflict / emotional_beat / must_happen / must_not_happen / narrative_tag。
- 光标 offset 命中 scene_chunks 时，右侧 Scene 卡随光标切换。
- “暂存”或 Ctrl+S 原地更新当前最新版本，不新增版本号，并提示“已暂存”。
- “发布”新增 writing_drafts 版本，version_number 自增，并入队 publish_chapter/RAG 索引；空内容发布被前端拦截。
- “断章至此”按 offset 切分当前 Chapter，生成新 Chapter 与新草稿版本，更新 scene_chunks，不立即触发 RAG 索引。
- Scene 切换时编辑器内容进入前端暂存，不触发后端保存，不丢失当前输入。
- 版本历史可预览并恢复到编辑器，恢复后需用户再次保存才入库。
- 多 Tab 保存冲突返回 409，前端提示且保留用户输入。
- “AI 提取章节卡”调用 outline 生成能力并刷新 Scene 列表/右侧 Scene 卡。

实现约束：
- writing 模块不直接写 outline 内部实现；Scene 卡编辑走 outline API/稳定入口。
- 发布触发 RAG 索引按现有任务系统实现，不引入新队列。
- 编辑器中的用户正文渲染必须防 XSS。

验收：
- 前端 E2E 覆盖空状态、新建章节、暂存、发布、Scene 切换不丢内容、版本历史、断章、光标联动、AI 提取弹窗、localStorage 备份、多 Tab 冲突。
- 后端覆盖 draft CRUD、版本号、发布任务入队、断章映射、409 expected_version。
- 真实 LLM 验收记录《诡秘之主 第一部》第 1-3 章 AI 提取后生成/更新的 Scene 卡数量和关键字段。
```

## 5. 世界对象管理

```text
/goal 实现并验收“世界对象管理”用户路径。

背景：
网络小说作者需要维护人物、地点、势力、物品、概念、事件、别名、关系和人物知识边界。深度导入自动入库的对象必须可手动编辑、合并、回滚。

目标：
让作者在 worldView 中完成对象浏览、搜索、过滤、创建、编辑、删除/废弃、别名管理、关系管理、实体合并、实体回滚、人物知识边界管理。

范围：
- 后端主模块：backend/modules/world、backend/modules/memory
- 前端主视图：worldView
- 相关测试：world 单测、world E2E、world-relations-aliases E2E

必须满足：
- 对象库列表显示状态、类型、名称、重要度、摘要、操作；默认分页每页 20 条。
- 支持按实体类型、状态过滤，支持名称/别名搜索。
- 自动入库对象折叠在“自动入库”分组并带“新”标记。
- 手动创建实体时 name 必填、entity_type 必选，status=draft，created_by=manual。
- 编辑实体可更新名称、类型、摘要；结构化字段若未在当前 UI 暴露，不强行新增复杂表单。
- 别名写入 core_entities.content_json.aliases，不创建新实体；同实体别名不可重复；支持删除。
- 关系创建必须校验 source_id != target_id、双方属于同一 novel_id、同 source/target/type 不重复；支持删除。
- 合并实体必须二次确认，并在一个事务内完成别名继承、关系迁移、自环清理、文本字段合并、冲突归档、候选标 merged、目标标 canonical。
- 回滚实体按 scene_index 从 text_archive 或 entity_revisions 恢复，并记录 rollback 归档。
- 人物知识边界支持 unknown / rumor / partial / full / false_belief，false_belief 必填误解内容。

实现约束：
- 不跨 novel_id 合并、建关系、添加知识边界或回滚。
- 合并、删除、回滚都是危险操作，必须保留确认。
- 别名是对象属性，不是新对象。
- 不把 hidden_truth 泄露到公开摘要或角色视角不应知道的上下文中。

验收：
- 后端覆盖实体 CRUD、搜索/过滤、别名、关系、自环/重复/跨 novel_id 拒绝、合并事务、回滚、人物知识边界。
- 前端 E2E 覆盖对象库空态、创建/编辑/删除、关系子标签、别名子标签、合并、回滚、知识弹窗。
- 使用已有《诡秘之主 第一部》种子实体可做手动验收，但本路径不要求真实 LLM。
```

## 6. 大纲与结构管理

```text
/goal 实现并验收“大纲与结构管理”用户路径。

背景：
网络小说作者需要把素材组织成可执行剧情结构：Scene 卡、剧情线、篇章纲、伏笔和揭示计划，并能从已有正文用 AI 生成结构草案。

目标：
让作者在 outlineView 中浏览和维护 Scene 卡、剧情线、篇章纲、伏笔、揭示计划，并完成 AI 生成剧情结构。

真实 LLM 验收数据：
- “AI 生成结构”路径必须使用数据库中《诡秘之主 第一部》项目的第 1-3 章真实内容。
- 不允许用 mock LLM 代替该路径的最终验收。

范围：
- 后端主模块：backend/modules/outline、backend/modules/context
- 前端主视图：outlineView，writingView 右侧 Scene 卡联动
- 相关测试：outline scene 单测、foreshadowing/reveal 单测、outline-scenes E2E、outline-threads-arcs E2E

必须满足：
- outlineView 至少提供场景卡、剧情线、篇章纲、伏笔、揭示相关子标签或入口。
- Scene 卡列表按 scene_index 展示 title、narrative_tag、goal 摘要、状态、来源。
- Scene 可手动创建/编辑字段：scene_index、title、goal、core_conflict、emotional_beat、must_happen、must_not_happen、narrative_tag。
- 手动 Scene 默认 narrative_tag=draft，source=manual。
- Scene 上移/下移调用 reorder，只调整 scene_index，不改物理 chapter/scene_chunks 映射。
- 删除 Scene 标记 deprecated，不删除正文 Chapter。
- 剧情线和篇章纲支持创建、编辑、删除，并按类型/arc_index/start_chapter 展示。
- 伏笔和揭示计划支持列表、创建、状态更新、删除；删除必须二次确认并限定 novel_id。
- AI 生成结构调用 POST /api/outline/generate：编译上下文 -> LLM 调用 structure_plot.md -> schema 校验 -> 去重 -> 持久化 plot_threads + outline_arcs；extra_sections 只展示不持久化。
- 章节范围已有结构数据时必须警告并由用户确认。

实现约束：
- 不在 outline API 层写复杂业务逻辑。
- LLM 输出必须结构化校验；不把 prompt 中的导入文本指令当系统指令执行。
- Scene 与 Chapter 的 M:N 映射由 scene_chunks 维护，不通过删除正文解决结构问题。

验收：
- 后端测试覆盖 Scene CRUD/reorder/delete、剧情线 CRUD、篇章纲 CRUD、伏笔/揭示 CRUD、AI generate schema 和重复范围警告。
- 前端 E2E 覆盖 Scene 默认标签、创建/编辑/删除、上移/下移、AI 生成弹窗、伏笔创建/状态更新、揭示创建、剧情线/篇章纲 CRUD。
- 真实 LLM 验收记录《诡秘之主 第一部》第 1-3 章生成的 plot_threads 和 outline_arcs 数量，以及是否刷新到 UI。
```

## 7. RAG 混合检索

```text
/goal 实现并验收“RAG 混合检索”用户路径。

背景：
网络小说作者写作时需要从大量正文和结构化设定中找回相关细节。RAG 模块负责把章节分块、标注实体/人物/剧情线、生成 embedding，并在向量不可用时降级到关键词/项目词典检索。

目标：
让作者在 ragView 中查看索引状态、重建索引、搜索正文片段，并让 writing 发布路径自动触发章节索引。

范围：
- 后端主模块：backend/modules/rag、backend/modules/writing
- 前端主视图：ragView，writingView 发布进度提示
- 相关测试：rag 单测、rag E2E、writing 发布触发索引测试

必须满足：
- 保存/发布正文章节后自动入队 rag_index_chapter，替换该章旧 chunk。
- 分块策略适合中文小说：约 600-800 字子块，overlap 约 18%，每块标注 chapter_index、chunk_index、start_offset、end_offset、char_count。
- chunk 尽量标注 scene_id/entity_ids/character_ids/thread_ids；embedding 失败不阻塞 chunk 创建。
- retrieve 支持 mode=search/context/extraction，支持 entity_ids、character_ids、thread_ids、chapter_index、visibility、top_k、reference_chapter_index。
- 混合检索包含向量、关键词、项目词典、metadata 过滤；embedding 失败时返回 degraded=true 和 warnings。
- ragView 展示索引状态、chunk 列表/搜索结果、embedding_failed_count、degraded/warnings，并提供重建索引按钮。
- 重建索引可按项目或章节范围执行，返回每章 chunk 数和 warning。

实现约束：
- 不引入复杂 GraphRAG、Neo4j 或 reranker。
- top_k 必须受上限控制，避免一次返回过大上下文。
- 检索结果只能来自当前 novel_id。

验收：
- 后端覆盖分块、创建 chunk、索引章节、重建索引、检索过滤、embedding 失败降级、top_k 上限、跨 novel_id 隔离。
- 前端 E2E 覆盖索引状态页、搜索子标签、搜索空结果、真实 chunk UI 召回、embedding 降级 warning、重建索引按钮。
- 可使用《诡秘之主 第一部》第 1-3 章作为真实检索数据；本路径不要求真实 LLM，但如调用真实 embedding provider，需要记录 provider 可用性与降级情况。
```

## 8. 上下文编译

```text
/goal 实现并验收“上下文编译（Scene-Centric Compiler v2）”用户路径。

背景：
网络小说作者准备让 AI 辅助续写或调试剧情时，不能把全库内容塞给模型。Context Compiler 必须按 Scene、POV、知识边界、伏笔义务、RAG 证据和预算裁剪生成可控上下文。

目标：
让作者在 contextView 中选择任务、章节/Scene、揭示模式、视角人物和预算后，编译结构化上下文并渲染为 Markdown Prompt。

范围：
- 后端主模块：backend/modules/context，聚合 project/world/memory/outline/rag
- 前端主视图：contextView
- 相关测试：context 单测、context E2E、hidden_truth/知识边界集成测试

必须满足：
- API 支持 POST /api/context/compile 和 POST /api/context/render。
- 编译输出包含 9 段 Tier：Writing Objective、Scene Blueprint、POV Knowledge、Delta Timeline、Open Narrative Obligations、Retrieval Evidence Packs、Style Assets、Hard Constraints、Compiler Warnings。
- P0 段永不截断；Tier 驱逐顺序为 P4 -> P3 -> P2 -> P1，P0 保留。
- reveal_mode 支持 author_safe / character 等现有模式；character 模式必须要求 viewpoint_character_id。
- CharacterKnowledge 约束生效：unknown 禁止透露，restricted 限制表达，misunderstood 按误判表现。
- seeded 且 payoff_scene 晚于当前 Scene 的伏笔不得提前揭示。
- Scene.must_not_happen 必须进入 Hard Constraints。
- RAG 证据包受 top_k 和预算控制，不无限拉取数据库。
- MarkdownRenderer 只渲染编译后的 IR，不在渲染层重新做业务决策。
- contextView 展示编译结果、警告、预算裁剪信息；未选择项目或缺少视角人物时给出清晰提示。

实现约束：
- context 聚合跨模块数据必须走 facade/contracts/DI port；不能直接 import 其他模块内部 models/repositories/services。
- 不泄露 author_only / hidden_truth 到角色视角上下文。
- 不为了补资料绕过预算控制。

验收：
- 后端覆盖预算裁剪、P0 保留、知识边界、伏笔提前揭示禁止、must_not_happen、RAG 证据包上限、render markdown。
- 前端 E2E 覆盖页面加载、未选择项目警告、编译并显示结果、character reveal_mode 缺视角人物拦截、提交契约。
- 使用《诡秘之主 第一部》项目数据做一次真实编译验收，重点检查克莱恩视角下不应知道的 hidden_truth 不出现在角色模式输出中。本路径通常不直接调用 LLM；若后续接入真实生成调用，必须限定第 1-3 章。
```

