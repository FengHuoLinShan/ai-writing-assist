# D6b 槽位报告（R08 evidence：Context confirmation / compilation / 指纹）

日期：2026-09-11。基线：main @ e7d0b8d5b（含 WIP imports api/test、styles.css，与本槽位无冲突证据）。
全部只读完成；未运行测试/构建/make，无网络，未读 .env。slot-paths-W2.json "D6b" 全部 70 路径
（compilation/ 11 根文件 + services 24 文件含 12 loaders + tests 24 文件含空 `__init__`）逐一
语义阅读，无目录抽样；另按 A7-4 候选跨读 `modules/evidence/facade.py`、`modules/evidence/__init__.py`。
confirmation 三段重验（preview→confirm 比对指纹→执行前 prepare 重编译比对）为安全边界，本槽位
未发现复制实现，未列为简化对象。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/evidence/compilation/README.md,已审,模块权威文档/HTTP 契约声明,无发现：与代码逐节核对一致（含 focused/scene-lens/activation/snapshot 维护与 trace 保留语义）
backend/modules/evidence/compilation/__init__.py,已审,模块包入口（star 语义 re-export）,无发现：导出面随 D6b-2 收缩
backend/modules/evidence/compilation/api.py,已审,/api/evidence/compilation/* 全部 HTTP 路由,D6b-9（legacy GET 死路由）；无发现备注：全部路由先 require_active_project；render 路由活（GenerateView）
backend/modules/evidence/compilation/contracts.py,已审,compilation 对外契约（跨模块经 facade）,无发现：CompileOptions.__post_init__ 固定 author_safe+scene 截止；world_entries 恒空见 D6b-1
backend/modules/evidence/compilation/evidence_repository.py,已审,evidence_links 持久化,D6b-4（list_for_source_chapter 全量加载 Python 过滤）；create/list_for_target 均带 novel_id
backend/modules/evidence/compilation/facade.py,已审,compilation 唯一对外入口,D6b-2/D6b-8；无发现备注：服务单例与惰性工厂混用但全部无状态；mark_asset_context_changed 经 source.changed port 派发
backend/modules/evidence/compilation/focused_contracts.py,已审,focused evidence 请求/续查契约,无发现：continuation no_prose 校验禁止持久化正文；identity policy 限 imports.targeted_completion
backend/modules/evidence/compilation/focused_tasks.py,已审,evidence_focused_search 任务 handler+HTTP 提交/读取/恢复,无发现：任务 novel_id 与 request 比对、secret-free snapshot、失败保留证据不切 provider（test_focused_boundaries 覆盖）；跨模块私有引用为同包内风格问题
backend/modules/evidence/compilation/markdown_renderer.py,已审,CompiledContext/Bundle 渲染,D6b-2/D6b-3（legacy bundle 渲染器死代码；geo/chapter_card 死分支）
backend/modules/evidence/compilation/novel_evidence.py,已审,grep/search/read/inspect/trace/rehydrate 编排,D6b-4；无发现备注：可见性三模式、候选 hash 绑定回读、伪造 link 不计入证据且 index_fresh=false
backend/modules/evidence/compilation/schemas.py,已审,compilation API Pydantic schema,无发现：start_offset=0 半开区间正确处理（bool/None 拒绝）；hash 64 位 hex 校验；writing.generate 默认 12000 预算
backend/modules/evidence/compilation/services/__init__.py,已审,服务层兼容导出,无发现
backend/modules/evidence/compilation/services/activation_profile_service.py,已审,Activation Profile 生命周期+规则求值,F1-3 增量（_rule_hash）；无发现备注：发布校验目标存在、revision 不可变、CAS、reader/character 一律排除
backend/modules/evidence/compilation/services/author_question_evidence.py,已审,问世界证据预算,无发现：SHA-256 形状校验、5 源/24000 字符上限、排除诊断不含正文
backend/modules/evidence/compilation/services/compiled_context.py,已审,CompiledContext IR+预算+F1-3 权威指纹,无发现（自身）；compiled_context_fingerprint 为持久化比对权威——任何统一化禁止改其输出
backend/modules/evidence/compilation/services/confirmation_service.py,已审,confirmation 三段重验核心,D6b-1 相关无、D6b-6（类体顺序/伪 docstring）、D6b-7（_selected_asset_ids 死方法）、F1-3 增量、A7-3
backend/modules/evidence/compilation/services/confirmed_ai_action.py,已审,确认后 AI 动作物化,无发现：require_fresh+compile_from_confirmation 组合；bind_result 锁行刷新
backend/modules/evidence/compilation/services/constraint_engine.py,已审,P0 硬约束编译,D6b-11（英文约束死数据）；reader/character 不渲染动态约束防剧透
backend/modules/evidence/compilation/services/context_compiler.py,已审,编译核心（scope 调度/裁剪/排除/pinned/activation）,无发现：loader 异常降级为 warning 且 redact；pinned 优先于 excluded；P0/必需/作者加入不被静默裁剪；消费串话风险见 D6b-5（planner）
backend/modules/evidence/compilation/services/evidence_health_service.py,已审,证据健康聚合,无发现
backend/modules/evidence/compilation/services/focused_evidence.py,已审,专项补查根到一跳检索,F1-3 增量（_digest）；无发现备注：请求/来源/世界/邻接四重指纹、续查 fail-closed、角色原文窄门禁（逐字相等+range EvidenceLink）
backend/modules/evidence/compilation/services/generation_background.py,已审,生成中心背景编译+快照 provenance,无发现：included_asset_ids 只记预算后实际保留项；source hash 权威优先
backend/modules/evidence/compilation/services/hidden_guard.py,已审,角色视角隐藏守卫词项,无发现：knowledge_level=full 豁免、去重、短语切分下限 4 字符
backend/modules/evidence/compilation/services/import_activation.py,已审,深导入 Phase 2a 跨模块预检,D6b-1（死方法簇+world_entries 恒空）；F1-3 增量（_context_fingerprint）
backend/modules/evidence/compilation/services/interaction_story_context.py,已审,RP 冻结 source revision 资料包,F1-3 增量（_hash）；无发现备注：owner 同人校验、截止前可见性、必需固定项缺证据即 blocker、围栏结束标记统一转义（渲染边界整体 sanitize，knowledge block 亦被覆盖）
backend/modules/evidence/compilation/services/loaders/__init__.py,已审,loader 注册表,无发现：is_loader_available 仅测试消费（登记不删）
backend/modules/evidence/compilation/services/loaders/characters_loader.py,已审,人物加载+知识边界过滤,无发现：character 模式过滤失败保守清空；POV 不可用即清空
backend/modules/evidence/compilation/services/loaders/events_loader.py,已审,事件加载,无发现
backend/modules/evidence/compilation/services/loaders/memory_records_loader.py,已审,记忆全景规范化+Scene checkpoint ensure,无发现：author_full 才含 hidden_truth；checkpoint 失败不回填
backend/modules/evidence/compilation/services/loaders/outline_analysis_loader.py,已审,手动大纲分析范围加载,无发现：reader/character 拒绝；范围缺失/无效 fail-closed（confirmation 侧复核）
backend/modules/evidence/compilation/services/loaders/outline_arc_loader.py,已审,篇章纲加载,无发现：经 DI outline.arc_service
backend/modules/evidence/compilation/services/loaders/plot_threads_loader.py,已审,剧情线加载,无发现：无锚点且无显式 ID 时不默认加载第一章
backend/modules/evidence/compilation/services/loaders/project_loader.py,已审,项目元信息加载,无发现：白名单 8 个 prompt-safe 字段，settings/Key 不进上下文
backend/modules/evidence/compilation/services/loaders/rag_chunks_loader.py,已审,RAG 计划执行+RRF+融合重排+回读,D6b-12（_hash_payload 死）；F1-3 增量；trace 旁路会话 2s 锁超时不阻塞
backend/modules/evidence/compilation/services/loaders/scene_loader.py,已审,Scene 卡加载,无发现：跨项目 Scene 由 story facade 拒绝（测试覆盖）
backend/modules/evidence/compilation/services/loaders/world_bible_loader.py,已审,简介/工作稿加载,无发现：非作者视角仅 warning 不加载；provenance 回写 options
backend/modules/evidence/compilation/services/loaders/world_entities_loader.py,已审,世界对象加载+Top-K+reveal 过滤,D6b-12（_related_entity_ids 死包装）；map_atlas 背景 160/240 上限一致
backend/modules/evidence/compilation/services/planned_retrieval_service.py,已审,非编译消费者的 planner/RAG 直通,无发现：消费方 world entity_fusion/ask_world
backend/modules/evidence/compilation/services/review_projection.py,已审,审查台投影（selected/selection_state/指纹）,无发现：selected_asset_ids 从预算后 items 生成
backend/modules/evidence/compilation/services/review_resolution_sources.py,已审,导入整理来源回读,无发现：manifest hash+章节区间双校验、边界未核场景拒绝、总量 100K 上限
backend/modules/evidence/compilation/services/retrieval_query_planner.py,已审,确定性检索计划+有界 LLM 扩展,D6b-5（死分支+搬家关键词特判）；F1-3 增量（_hash_payload）
backend/modules/evidence/compilation/services/retrieval_trace_service.py,已审,检索 trace 持久化/聚合/清理,无发现：诊断码与计数白名单规范化
backend/modules/evidence/compilation/services/scene_lens.py,已审,写作台 Scene 透镜只读视图,无发现：无检索/无写入/仅 label+summary+availability
backend/modules/evidence/compilation/services/selection_proposal.py,已审,一次性只读选择提议,无发现：无工具/无循环/120s/候选短键绑定/未知引用拒绝
backend/modules/evidence/compilation/services/snapshot_service.py,已审,快照生命周期+维护+旁路事务,F1-3 增量（_prompt_hash）；无发现备注：terminal first-wins、owner 心跳对账、durable 事务按 Engine/Connection 分派
backend/modules/evidence/compilation/tests/__init__.py,已审,测试包标记,无发现（空文件）
backend/modules/evidence/compilation/tests/conftest.py,已审,测试配置,无发现（1 行注释，复用根 fixtures）
backend/modules/evidence/compilation/tests/test_activation_profile_api.py,已审,Profile HTTP 生命周期,关联 D6b-9（legacy_get_survives 守卫）；novel 越权 404 断言有效
backend/modules/evidence/compilation/tests/test_activation_profiles.py,已审,Profile 规则/CAS/revision/围栏转义/确认标脏,无发现：断言有效且覆盖失效标脏（world_bible_page_published）
backend/modules/evidence/compilation/tests/test_author_question_evidence.py,已审,问世界预算,无发现
backend/modules/evidence/compilation/tests/test_context.py,已审,编译/确认/快照/隔离 API 大套件,D6b-10（helper 与 test_context_compiler 重复；空 section 头）；关联 D6b-7
backend/modules/evidence/compilation/tests/test_context_compiler.py,已审,编译器/渲染/角色 reveal 分层,D6b-10
backend/modules/evidence/compilation/tests/test_context_selection.py,已审,逐项排除/pinned/指纹语义,无发现：指纹只随 provider 可见输入变化（title/preview/status 不影响）
backend/modules/evidence/compilation/tests/test_focused_boundaries.py,已审,focused 真实 seam 边界,无发现：时点/别名/邻接指纹/角色未学秘密 fail-closed、无模型不切 provider
backend/modules/evidence/compilation/tests/test_focused_evidence.py,已审,focused 检索主链,无发现：quote 唯一+逐字+含 proof term、HTTP 不收内部字段、pending/跨项目 404
backend/modules/evidence/compilation/tests/test_generation_background_service.py,已审,生成背景 provenance,无发现
backend/modules/evidence/compilation/tests/test_generation_snapshot_transactions.py,已审,生成快照事务边界,无发现：caller 回滚不影响 durable 快照
backend/modules/evidence/compilation/tests/test_guimi_confirmation.py,已审,预算/来源/检索回归,关联 D6b-5（固化搬家关键词行为）；其余断言有效
backend/modules/evidence/compilation/tests/test_import_activation.py,已审,深导入预检,关联 D6b-1（前两个测试仅测死方法）；其余断言有效（Top-K/指纹/越章裁剪/关系分页）
backend/modules/evidence/compilation/tests/test_interaction_story_context.py,已审,RP 资料包,无发现：版本共存/冻结回读/超预算 blocker/跨 owner 拒绝/围栏转义
backend/modules/evidence/compilation/tests/test_novel_evidence.py,已审,证据检索/可见性/回读,无发现：截止 Scene 重绑版本、伪造 link 不计、working 索引过期不回退
backend/modules/evidence/compilation/tests/test_project_gate.py,已审,回收站/缺失项目 404 门禁,无发现
backend/modules/evidence/compilation/tests/test_rag_chunks_loader_trace_lock.py,已审,trace 旁路锁超时,无发现：trace 写失败不进 warnings 不破坏指纹（回归有效）
backend/modules/evidence/compilation/tests/test_retrieval_health.py,已审,trace/健康/RRF/重排,无发现：drop 规范化、跨项目隔离、手动搜索 fail-open 与上下文 fail-closed 区分
backend/modules/evidence/compilation/tests/test_retrieval_query_planner.py,已审,计划器确定性/LLM 扩展边界,无发现：grounding/数字注入拒绝、safety path 禁扩展
backend/modules/evidence/compilation/tests/test_scene_lens.py,已审,Scene 透镜,无发现：内部字段不外泄、owner 门禁
backend/modules/evidence/compilation/tests/test_selection_proposal.py,已审,选择提议,无发现：候选短键绑定、未知引用安全忽略
backend/modules/evidence/compilation/tests/test_selection_reference_schema.py,已审,start_offset=0 半开区间,无发现：参数化覆盖 0/1/None/-1/False
backend/modules/evidence/compilation/tests/test_snapshot_task_reconciliation.py,已审,快照与 owner 任务对账,无发现：心跳新鲜不算 stale、terminal 孤儿、auto_requeue pending
```

70/70 覆盖，无受阻路径。

## 发现

| ID | 位置/符号 | 问题与触发 | 调用链证据 | 现有契约 | 最小方案 | 预期收益 | 风险 | 依赖 | 验证命令/断言 | 回滚 | 裁定 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D6b-1 | `services/import_activation.py`：`_slice_text`(:597)、`_entry_dict`(:620)、`_matching_terms`(:1063)、`_world_context`(:1072)；`contracts.py:309 world_entries`；`import_activation.py:163,230` | P13 改为不做应用层输入预算（`_ = budget_tokens`，:47 注释）后，旧"世界背景条目预算"路径残留：`_entry_dict`/`_matching_terms` 全库零引用；`_slice_text`/`_world_context` 仅 `tests/test_import_activation.py:16,25,33` 消费；`prepare` 中 `world_entries` 恒为 `[]` 且契约字段无任何读者 | rg 全库：`_entry_dict\|_matching_terms` 仅定义处；`.world_entries` 无消费（imports/tests 均无）；`world_entries = []` 后无赋值 | ImportContextActivationContract 冻结契约；`world_entries` 是其字段（冻结 dataclass，删除=改对外契约字段名面） | 删 4 个死方法 + test_import_activation 前 3 个测试；`world_entries` 字段删除需同步 contracts 与构造点（facade 消费方不读该字段，rg 证实），或保留字段标注"恒空，历史契约" | ~110 行 + 2 个失实测试；消除"Phase 2a 有世界背景预算"的误导 | 低：死代码与恒空字段；若保留字段则零行为差异 | 无 | `make test TESTS="modules/evidence/compilation/tests modules/imports/tests"`；rg 断言零引用 | git revert | 实施候选 | P2 |
| D6b-2 | `markdown_renderer.py:32-590`（`SECTION_TITLES`+`render_context_markdown`+12 个 `_render_*`）；`facade.py:128-140`；`__init__.py` | legacy Bundle 12 段 Markdown 渲染器生产零调用：`render_context_markdown` 全库引用仅 facade 包装、包导出与 3 个测试文件；唯一 bundle 生产消费者 `story/outline_state/generation/context_builder.py:88` 自带 `_render_bundle_to_markdown` 不经本渲染器。活渲染器是 `render_compiled_context`（api /render、confirmed_ai_action、generation_background 消费） | rg `render_context_markdown` 全库；rg `SECTION_TITLES` 无外部引用；context_builder 渲染自查 | facade 公开函数（`__init__.__all__` 列名）——删除=收 facade 面，非内部裁剪 | 删渲染器主体+两个 facade 包装+`__init__` 导出+迁移/删除对应测试（test_context_compiler TestMarkdownRenderer、test_context 渲染类、tests/unit/test_context.py 渲染用例）。`compile_structure_context` bundle 编译路径保留（context_builder 消费 bundle 数据） | ~600 行死代码 + 约 40 个失真测试用例的维护面 | 中低：需确认无动态字符串调用（rg 已查全库无）；tests/unit/test_context.py 归 E1 配合 | E1 | `make test TESTS="modules/evidence/compilation/tests"` + rg 断言零生产引用 | git revert | 实施候选（与 D6b-3 同批） | P2 |
| D6b-3 | `schemas.py:146 enable_geo_filter`→`api.py:222,273,329,379`→`facade.py:182,253,695,730`→`contracts.py:57`；`StructureContextBundle.geo_locations/chapter_card`；`CONTEXT_BUDGET["geo_relations"]` | `enable_geo_filter` 端到端无生产读取点（编译器/加载器从不读），API→facade→options 全链传空；`geo_locations`、`chapter_card` 无任何生产写入点（无 loader 赋值），仅 legacy 渲染器读取（随 D6b-2 消亡后成为死字段）；README:537 已声明 geo_locations 为兼容名 | rg `enable_geo_filter` 生产侧仅传参链；`geo_locations =`/`chapter_card =` 生产零写入 | API 字段与 CompileOptions 字段（对外兼容面：前端可继续提交该字段） | 分两步：a) 随 D6b-2 删 geo/chapter_card 渲染消费；b) `enable_geo_filter`/`location_ids` 之外的字段保留接受但标注 deprecated（或前端停发后删）——删 API 字段属对外契约变更须单独确认 | 消除"地缘过滤存在"的假象；减少 4 处透传 | 中：API 字段删除属 §2 兼容面变更 | 前端确认 | rg 断言 + `npm run build` | git revert | 实施候选（b 步需产品确认） | P3 |
| D6b-4 | `novel_evidence.py:_search_world(:1282)`、`inspect(:626)`、`_object_refs_for_source(:1925)`、`evidence_repository.list_for_source_chapter(:66)` | world scope 智能搜索 N+1：对 `max(limit*4,50)`（top_k=100 时 400）个实体逐个 `self.inspect`，每次 inspect 再触发单实体 `get_world_context`+`list_for_target`+逐条 link 一次 `read` 重验——单次搜索可放大约千级查询；grep/read 每个命中调 `list_for_source_chapter`，该方法加载项目全部 active evidence_links 后在 Python 按 JSON chapter_index 过滤 | 代码路径直读；`_search_world` 循环内 `await self.inspect`；repo `list((await db.execute(stmt)).scalars().all())` 后 Python 过滤 | 无明确契约；行为正确（可见性逐项复核） | a) `_search_world` 先批量取实体投影再只对字面命中的候选 inspect；b) `list_for_source_chapter` 加 limit 或按 `target_ref->>'draft_id'` SQL 端预过滤 | 收益待测（无性能基线，按计划 §5 不承诺百分比）；减少搜索延迟与 DB 压力 | 中：可见性语义必须逐项保持，需现有测试全绿 | 性能基线（W3） | 现有 `test_novel_evidence.py` 全绿 + SQL 计数对比 | git revert | 实施候选（先测量后改） | P2 |
| D6b-5 | `retrieval_query_planner.py:134`（`搬到\|搬家\|新家\|住在哪\|哪条街`→固定 `residence_evidence` 子查询）；`:185-188` 死分支 | a) 确定性 planner 内嵌 demo 语料关键词特判：任意项目 world.ask 命中这些通用词即插入固定查询"搬家"的检索子句——与 D5a-1 同类（领域语料固化进生产逻辑），但不注入 LLM prompt、仅检索偏置，后果轻；b) `_draft_clauses` 第二个 task fallback 条件（:187-188）在前一条件相同输入下不可达（`clauses.append` 后必非空） | `test_guimi_confirmation.py:105-123` 以《诡秘之主》克莱恩问题固化该行为（断言 `clauses[0].query_text == "搬家"`）；控制流直读 | 现行为有测试背书 = 事实契约 | a) 删除关键词特判+改测试（属功能行为变更，须产品确认后单列）；b) 删死分支纯清理 | a) 移除语料特判维护点；b) 微小 | a) 改变 world.ask 检索行为（特定问题少一条子句）；b) 无 | 产品确认（a） | b) rg/单测；a) `test_guimi_confirmation` 相应改写 | git revert | b) 实施候选；a) 单列功能变更候选 | P3 |
| D6b-6 | `confirmation_service.py:41-77` | `preview_confirmation` 定义在 `__init__` 之前；:69 字符串 `"Owns AI reference confirmation semantics."` 位于方法之间，是无副作用的孤儿表达式而非类 docstring（类实际无 docstring） | 文件直读 | 无 | 将 `__init__` 提到类首，字符串改为真正类 docstring | 可读性 | 无 | 无 | 目测 + lint | git revert | 实施候选（顺手改） | P3 |
| D6b-7 | `confirmation_service.py:_selected_asset_ids(:414-461)` | 生产零调用：confirm 路径用 `review_projection.selected_asset_ids_from_compiled`（语义已分化：items 优先、含 `writing_drafts`、`_ASSET_KEYS` 映射）；该方法仅 `test_context.py:383` 消费 | rg 全库仅定义+测试 | 无对外契约（静态私有） | 删方法，测试改为断言 `selected_asset_ids_from_compiled` 的 outline_analysis 语义（等价覆盖） | ~48 行 + 消除双实现漂移风险 | 低 | E1 配合 | `make test TESTS="modules/evidence/compilation/tests"` | git revert | 实施候选 | P3 |
| D6b-8 | `modules/evidence/facade.py:1-4`；`compilation/facade.py`（无 `__all__`）；`indexing/facade.py`（无 `__all__`） | 统一 evidence facade 由双 star-import 组成且两个源 facade 均未定义 `__all__`：`AsyncSession`、`CompileOptions`、`ContextCompiler`、`DurableContextSnapshotService` 等内部/类型符号全部成为 `modules.evidence.facade` 的公共导入面，守卫测试（tests/unit/test_facade_public_api.py 白名单）是唯一软约束 | ast 解析确认无 `__all__`；外部 20+ 模块经该 facade 导入 | A7-4/X1-3 历史候选：收窄到真实外部消费面 ~51 符号；不回迁 25 处内部直连 | 在 compilation/facade.py、indexing/facade.py 定义 `__all__`（真实外部消费面），evidence/facade.py 组合后仍成立；不改任何调用方 | 导出面受控；防新内部符号意外外泄 | 低：需先 enumerate 外部实际导入符号（含测试） | E1 facade 守卫测试 | `python -c "import modules.evidence.facade"` + facade public-surface 测试 | git revert | 实施候选 | P3 |
| D6b-9 | `api.py:660-683 GET /activation-preview`；`frontend-console/api.js:2078-2080`（`context.activationPreview` 包装）；`apiContracts.js:339`；`test_activation_profile_api.py:99-125` | legacy GET 路由无生产消费者：前端唯一包装 `api.context.activationPreview` 零调用方；唯一后端测试即名为 `..._legacy_get_survives` 的守卫（断言 200+profile null）。POST 路由活（`useWorldBible.js:1731 previewActivationProfile`） | rg 前端 vue/tests 零调用；后端 rg `activation-preview` 仅 api/README/该测试 | HTTP 路径属 §2 兼容面：删除=移除已承诺路径，需确认无仓外消费者 | 删 GET 路由 + 守卫测试的 legacy 断言 + 前端死包装/死契约（前端侧已由 F3-1 记 11 个死契约之一）；或保持现状并注明"无消费者，等待移除窗口" | 删 1 死路由 + 1 死契约 + 1 失实守卫测试 | 低（仓内无消费者） | F3-1 前端侧同批 | `make test TESTS="modules/evidence/compilation/tests"` + `npm test -- api-contract` | git revert | 实施候选（与 F3-1 合批） | P3 |
| D6b-10 | `tests/test_context.py` 与 `tests/test_context_compiler.py`：`_snapshot_request`/`_open_snapshot`、`_setup_character_knowledge`、`_response_text` 各两份；test_context.py:3284-3292 空 section 注释头 | 测试 helper 逐字重复 ~120 行；两份 `_setup_character_knowledge` 隐藏内容（源堡/诡秘之主文案）也重复；文件内留有已掏空的注释分节头 | 双文件对照直读 | 测试内部 | helper 提到本 tests 包共享模块；删空注释头 | 测试维护面收敛 | 无 | E1 | `make test TESTS="modules/evidence/compilation/tests"` | git revert | 实施候选（顺手改） | P3 |
| D6b-11 | `constraint_engine.py:28-32 _STATIC_CONSTRAINTS_EN`、`_static_constraints(language)` | 唯一调用点 `:46 _static_constraints("zh")`，英文约束与 language 参数为死数据 | rg 唯一调用 | 无 | 删英文表与参数（或接项目语言，属功能变更另议） | ~8 行 + 消除假多语言印象 | 无 | 无 | 目测 | git revert | 实施候选 | P3 |
| D6b-12 | `loaders/world_entities_loader.py:332-339 _related_entity_ids`；`loaders/rag_chunks_loader.py:595-597 _hash_payload` | 前者"兼容包装"零调用（rg 全库无）；后者与 planner 同名实现重复且本文件零调用 | rg 精确匹配 | 模块内部 | 删两处 | ~20 行 | 无 | 无 | rg 断言 | git revert | 实施候选 | P3 |
| D6b-13（增量标注，不单独立项） | 本槽位 9 处 sha256(json) 指纹/哈希实现 | 并入 F1-3 census（19→约 27）：`compiled_context.compiled_context_fingerprint`、`confirmation_service._outline_analysis_fingerprint/_scene_state_fingerprint`、`activation_profile_service._rule_hash`、`import_activation._context_fingerprint`、`focused_evidence._digest`、`interaction_story_context._hash`、`snapshot_service._prompt_hash`、`planner/rag_chunks_loader._hash_payload`。序列化参数不一致（separators 有/无、default=str 有/无），跨函数输出不可互换 | 各文件直读；交互序列化参数对照 | `compiled_context_fingerprint`（持久化于 confirmation.compile_options 并跨请求 409 比对）、`rule_hash`（持久化于不可变 revision）输出字节必须稳定；其余多为诊断/自比较 | 收敛时同文件先合并（A7-3）；跨文件统一 helper 须逐份提供字节兼容证明，持久化比对面禁止输出变化 | 减少 9 份实现漂移面 | 高（若输出漂移→旧 confirmation 全量失效） | F1-3 主批 | 固定输入/输出样本对比（§6 要求） | 逐函数可回退 | 并入 F1-3 批 | P2（并入） |

无 P0/P1：未发现安全、novel_id 隔离、数据丢失或恢复破坏类问题。confirmation 三段重验、
排除/截止/隐藏保护、focused 四重指纹、角色原文窄门禁、RP owner 同人校验均有实现且测试覆盖有效。

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A7-1（compilation/api.py:660-684 legacy GET 死路由 + apiContracts.js:339 死契约 + 12 个已定义未切契约） | 仍成立（形态更新/缩小） | 行号漂移后 GET `/activation-preview` 在 api.py:660-683，行区间基本未变。后端侧：路由无仓内生产消费者（前端 GET 包装 `api.context.activationPreview` 零调用；后端唯一引用是名为 `test_activation_profile_api_is_novel_scoped_and_legacy_get_survives` 的守卫测试：119-125）。前端死包装/死契约与"12 个未切契约中的死项"由 F3-1 记为 11 个（含本条 context.activationPreview），归属 F3。删除建议见 D6b-9 |
| A7-3（指纹同文件先合并，跨文件集中须逐字保留编码参数） | 仍成立（范围落实到本槽位） | 本槽位 census 9 处（D6b-13）。同文件对：confirmation_service 两个 fingerprint 方法参数完全一致可合并 helper；generation_background 两处 sha256 可共享。跨文件集中必须字节兼容：`compiled_context_fingerprint`（ensure_ascii=False+sort_keys+separators+default=str+utf-8）持久化于 confirmation 并在 compile_from_confirmation 409 比对（test_context.py:638-646 证实行为），输出变化将使全部现存 confirmation 失效——禁止无理由统一 |
| A7-4 / X1-3（evidence/facade `__all__` 收窄到真实外部消费面 51 符号；不回迁 25 处内部直连） | 仍成立（形态更新） | 现状 `modules/evidence/facade.py` 是 54 行组合 facade：`from compilation.facade import *` + `from indexing.facade import *` + 5 个 focused/review 入口；两个源 facade 均无 `__all__`（rg/ast 证实），故实际动作是"新增 `__all__`"而非"收窄既有清单"。外部消费面广（writing/world/story/imports 20+ 文件），白名单需按真实 import enumerate；"不回迁内部直连"的旧判断维持（diff 无收益） |
| A7-6/7/8/9（历史剔除项） | 维持剔除（待查原始明细不可得，按现状无异常） | 原审计仅列 ID 无明细；本槽位逐文件阅读未发现与其最可能所指（evidence 域微清理）相符的现存问题；按计划 §5 "与当前工作树不符时以代码为准"，无证据重启 |
| F3-1 移交：后端 activation-preview 死路由核实 | 已完成（归入 D6b-9） | 见 D6b-9 |

## 共享事实（供 W3 链 4：总纲/篇章/Scene → Context 确认 → Story/正文候选 → 独立审查/返修 → 采用/发布）

### 1. Confirmation 物化与指纹语义图

三段重验（安全不变量，单一实现无复制）：

1. **Preview（零写入）**：`POST /compile`（api.py:191）或 facade `preview_context_confirmation`
   （assistant ADR-0023 三处消费：writing/assistant_generation_tool、world/assistant_review_tools、
   story/assistant_structure_workflow）→ `ContextCompiler.compile_with_tiers` →
   `context_review_metadata(ctx, options)` 产出 `context_fingerprint`。preview 不建 confirmation 行。
2. **Confirm**：`POST /confirm` 携带 `expected_context_fingerprint` →
   `ContextConfirmationService.confirm_context`：重新编译 → blockers 即 ValueError →
   指纹不等抛 `ConflictError(context_preview_changed)` 409 → 通过后把指纹写入
   `compile_options.compiled_context_fingerprint`（JSON 字段，非独立列）并同步写
   `context_confirmation_asset_refs`（selected 角色，与 JSON 同事务）。
3. **执行前**：`prepare_confirmed_ai_action`（ConfirmedAIActionService.prepare）=
   `require_fresh_confirmation`（stale_context/needs_review 拒绝；for_update 行锁）+
   `compile_from_confirmation`（`CompileOptions(**record.compile_options)` 重编译 →
   指纹不等抛 `ConflictError(context_changed)`；旧记录无新指纹时回退
   `outline_analysis_fingerprint`/`scene_state_fingerprint` 两条历史兼容分支——当前生产
   `_compile_options_json` 不再写这两个键，仅服务历史 DB 记录）。

**指纹函数**：`compiled_context.compiled_context_fingerprint` 是唯一权威：payload 只含
section.key/tier/content + 排序后的 source 身份键（type/id/source_hash/content_hash/hash/
source_ref/target_ref/revision_id/version）+ 排序的 checkpoint_versions；序列化
`ensure_ascii=False, sort_keys=True, separators=(",",":"), default=str` + utf-8 + sha256。
审查展示字段（title/preview/status/activation_trace）不影响指纹（test_context_selection:140 实证）。
**统一化禁令**：该函数与 `_rule_hash` 的输出持久化并被跨请求比较，任何收敛不得改变其输出字节。

**selection/失效**：`selected_asset_ids` 由 `review_projection.selected_asset_ids_from_compiled`
从预算后 items 的 sources 生成（含 `writing_drafts` 来自 source_ref.draft_id、`context_sections`
为最终 section key 列表）；`excluded_asset_ids.context_sections` 兼容排除、P0 不可排除返回
warning；`pinned_refs` 优先于 `excluded_refs`（excluded_keys 先减 pinned_keys）；必需+作者加入
超预算 → blockers（含最大占用 Top3 提示）。失效入口 `mark_asset_context_changed`：精确表
`context_confirmation_asset_refs` 按单数资产类型匹配（复数 JSON 键经 `_ASSET_TYPE_ALIASES`
规范），reason=candidate_promoted → needs_review，否则 stale_context；批内一次 update_tracking_many；
facade 层随后向组合根 `source.changed` port 派发。

**Scene 锚点语义**：`author_safe+scene_id` 在 `CompileOptions.__post_init__` 强制
`visible_until_scene_id=scene_id`（调用方不可扩宽）；跨章 Scene 编译时 `_apply_scene_chapter_anchor`
把 `options.chapter_index` 改写为 Scene 末章并 warning，`_compile_options_json` 持久化的是
改写后有效锚点（requested_chapter_index 保留作者目标章，消费方如 writing 用它校验确认未被跨章复用）。

### 2. 排除 / 截止 / 隐藏保护点清单（逐项有代码位置）

- 作者逐项排除：`ContextCompiler._apply_item_exclusions`（P0/required 项拒绝并 warning）；
  section 级兼容排除 `_apply_section_exclusions`（P0/can_exclude=False 忽略）。
- 作者 pinned：`_apply_pinned_refs` 命中项标 author_pinned 且不参与预算静默裁剪
  （enforce_budget Phase 4 跳过含 author_pinned 的 P1 section）；未命中项经
  `_load_pinned_item` 重验（content_mode 一致 + hash + offset 范围 + 可见性），不可用 → blocker。
- 预算：`CompiledContext.enforce_budget` P4/P3 整段驱逐 → P2 逐条 → P1 前缀压缩；被逐条目进
  `omitted_items`（selection_state=omitted），不冒充已发送。
- 章节截止：`_effective_chapter_to`、`_source_visible`（章<截止通过；同章比 end_offset）；
  RAG 侧 `visible_until_chapter` 硬过滤（rag_chunks_loader→indexing.retrieve）。
- Scene/offset 截止：`NovelEvidenceService._resolve_visibility_cursor` 把截止 Scene 解析为
  版本绑定的字符偏移；无精确绑定 → `cutoff_offset=0` + "同章正文已保守排除" warning
  （fail-closed，test_novel_evidence:672 实证两模式）。
- RAG 候选回读门禁：`rehydrate_manuscript_candidates`——novel_id/content_mode/source_id/
  source_hash/范围/可见性六重校验后才从 writing 读原文，缓存 chunk text 永不直接信任。
- 角色知识：`CharactersLoader`→`filter_context_by_character_knowledge`（学习章严格早于截止章；
  同章无序保守排除）；`false_belief/misunderstood` 以 misconception 替换 summary 且删 hidden_truth；
  `_format_role_visible_knowledge` 视角分层；director_only 约束独立标注不冒充角色已知。
- 隐藏守卫：`HiddenGuardBuilder` 生成 prompt 外确定性校验词项（hidden_truth/隐藏关系/导演约束），
  knowledge_level=full 豁免。
- focused 专项：request/source/world(身份+邻接)四指纹 + `allowed_refs` 精确回放边界 +
  角色"已知内容逐字相等 + range 精度 EvidenceLink"窄门禁（否则 omission/blocker，
  knowledge_boundary_audit 恒 not_performed）。
- RP 冻结：interaction_story_context 以 source_manifest 限定 draft/hash、截止前可见性、
  必需固定项无截止前原文即 blocker；owner 同人 + author/interaction kind 校验。
- 生成中心快照：`included_asset_ids` 只记预算后实际保留项（truncated/evicted 不冒充），
  activation profile 作为控制 provenance 独立保留。
- 项目门禁：api.py 每路由 `require_active_project`（owner+活跃，回收站/缺失 404，
  test_project_gate）；快照/confirmation/trace 读写均带 novel_id；focused 任务 handler 比对
  `task.novel_id == request.novel_id`。

### 3. compilation 编排职责地图

- **对外入口**：`compilation/facade.py`（45+ 函数）→ 组合根统一经 `modules/evidence/facade.py`。
  HTTP 面仅 api.py（scope/character 校验后全部委托）。
- **编译核心**：`ContextCompiler.compile`（scope→SCOPE_LOADERS；前置 loader（project/scene/
  outline_analysis）先于依赖 loader（plot_threads→world_entities→characters），relevance 类
  consumer_action 走三段编排）；`compile_with_tiers` 加 constraint sections（P0 硬约束）、
  activation section、section/item 排除、pinned、预算。
- **加载器（12）**：project（安全字段白名单）、world_entities（Top-K 16/背景 160/240）、
  world_bible（作者简介/工作稿）、characters（Top-6+知识过滤）、events、memory_records
  （全景规范化+checkpoint ensure）、rag_chunks（计划→RRF→融合重排→回读→trace）、plot_threads、
  outline_arc、scene（章节锚点）、outline_analysis（范围包）。
- **确认域**：confirmation_service（preview/confirm/replay/attach_result(s)/mark_asset_changed）
  + confirmed_ai_action（执行前物化）。
- **快照域**：snapshot_service（普通=参与调用方事务；Durable=独立 Engine/Connection 事务，
  生成中心失败也留审计）+ run_snapshot_maintenance（stale 对账 owner 心跳、prune rendered、
  prune trace，默认 dry_run）。
- **证据域**：novel_evidence（grep/search/read/inspect/trace/rehydrate/locate_scene_quote/
  record_link）+ evidence_repository（evidence_links）+ evidence_health/trace 服务。
- **专项域**：focused_contracts/focused_tasks（evidence_focused_search 任务，
  manual_resume+5 次重试）/focused_evidence 服务（分相 roots→graph→neighbors→done，续游标）。
- **RP 域**：interaction_story_context（冻结 source revision 资料包+快照）。
- **导入域**：import_activation（Phase 2a 唯一预检，无应用层裁剪）+ review_resolution_sources。
- **辅助**：generation_background（生成中心深模块）、scene_lens（只读透镜）、
  selection_proposal（一次性只读提议）、activation_profile_service（规则生命周期）、
  retrieval_query_planner（确定性计划+有界 LLM 扩展）、markdown_renderer（活=render_compiled_context）。
- **任务注册**：`evidence_focused_search`（本槽位唯一 @task_handler，recovery_policy=manual_resume）。

### 4. legacy 死路由现状

- `GET /api/evidence/compilation/activation-preview`（api.py:660-683）：无生产消费者；POST 同路径
  为活路由（useWorldBible）。前端 `context.activationPreview` 契约+api.js 包装为死项（F3-1 清单）。
  守卫测试 `..._legacy_get_survives` 是其唯一仓内"消费者"。处置建议见 D6b-9。
- `POST /render` 活（GenerateView.vue:1394）；`POST /compile`、`/confirm`、`/selection-proposals`、
  `focused-search` 三路由、snapshots 三路由、activation-profiles 六路由、evidence 五路由、
  scene-lens、evidence-health、retrieval-traces 均有生产消费或测试+文档背书，非死路由。
- markdown_renderer 的 legacy bundle 渲染路径（非路由）为生产死代码（D6b-2）。

## 受阻

无。全部 70 路径完成审查；未执行被禁命令；无外部环境依赖缺口。
（注：D6b-4 的性能收益、D6b-3b 的字段移除需 W3 性能基线与产品确认，属实施前置条件，非审查受阻。）
