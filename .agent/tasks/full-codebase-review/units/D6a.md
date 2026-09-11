# D6a 槽位报告（R08 evidence：检索/索引子域 + 模块公共面）

日期：2026-09-11。基线：main @ e7d0b8d5b（工作树）。全部 43 路径只读完成；未运行测试/构建/make，无网络。生产 20 文件逐文件语义阅读；测试 15 文件全文或结构清单+关键段精读（两个大文件 test_indexing.py 3477 行 / test_rag.py 1852 行按测试函数清单+代表性关键段精读，覆盖状态机、并发 fence、重标注、检索降级各簇）。repositories.py/models.py 归 F4（横切唯一归属），本槽位只引用其结论。跨模块消费面经 `rg` 全仓逐符号取证（facade 消费者、activation-preview 前后端链、indexing 内部符号）。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/evidence/README.md,已审,模块权威文档;docs-check 消费,无发现：与代码一致（POST/GET activation-preview、prewarm 豁免、task-only seams 与代码核对相符；"split_text_into_chunks 供 import_text 流程使用"表述轻微失实——imports 实际不用它，唯一消费者是 chunks/split HTTP 端点，随 D6a-5 一并注记）
backend/modules/evidence/__init__.py,已审,包入口（star re-export contracts）,无发现：3 行纯 re-export，metadata/契约聚合 seam
backend/modules/evidence/api.py,已审,app/main.py 组合根挂载 /api/evidence,无发现：10 行纯组合（indexing+compilation handler_router 各挂 /indexing /compilation 前缀）
backend/modules/evidence/contracts.py,已审,跨模块稳定契约入口,无发现：star(compilation)+显式8个Focused*+star(indexing)；indexing 侧 RagQueryContract 生产零消费记 D6a-5
backend/modules/evidence/facade.py,已审,全部跨模块消费方（全仓 120+ 处 import）,D6a-3（与 D6b 配对）：star-import 两个子域 facade 且二者均无 __all__，实现类经 star-export 泄漏到公共面；模块根自有 5 函数均有真实消费者
backend/modules/evidence/indexing/README.md,已审,子域权威文档,无发现：评分公式/任务 seams/freshness 语义与实现逐条相符
backend/modules/evidence/indexing/__init__.py,已审,包入口,D6a-5：__all__ 10 符号无任何外部 from-package 消费（SimilarEntity/RagQueryContract 等死契约的一部分）
backend/modules/evidence/indexing/api.py,已审,canonical HTTP /api/evidence/indexing/*（前端 rag 集群/状态页）,无发现：8 端点全部先 require_active_project（metrics/prewarm/chunks split 豁免与 README 声明一致，test_api.py 有 404/豁免回归）；prewarm 吞异常仅回 503 无日志记 D6a-11
backend/modules/evidence/indexing/chunk_annotation.py,已审,IndexingService._prepare_chapter_index,无发现：span exact/reanchored + draft/hash 双重校验后才写自动 Scene 归因，符合 README"只有精确映射可归因"
backend/modules/evidence/indexing/chunking.py,已审,IndexingService/facade.split_text_into_chunks,D6a-4（_choose_cn_boundary 死代码）、D6a-9 在测试侧；split_by_length 前进钳制与中文分块 offset 语义正确
backend/modules/evidence/indexing/circuit_breaker.py,已审,retrieval/facade.get_index_status/get_metrics_status,无发现：per-novel 熔断+全局 legacy 单例并存，status 暴露给诊断 API；dict 无淘汰但量级=项目数，可接受
backend/modules/evidence/indexing/contracts.py,已审,跨模块契约（compilation/novel_evidence、evals、interaction）,D6a-5：RagQueryContract 生产零消费；RagChunkContract/RagResultBundle/RagIndexReport/RagTaskIndexOutcome/EntityActivity/Coverage 契约均有真实消费者
backend/modules/evidence/indexing/embedding_writer.py,已审,IndexingService 两条索引路径+重试,无发现：批量失败自动 per-chunk 降级、红act 持久化诊断、client 所有权 close 语义有测试锁定（test_indexing.py:2030-2228）
backend/modules/evidence/indexing/entity_activity.py,已审,rag_reannotate_entities handler/facade.get_entity_activity_stats/bootstrap DI,无发现：fresh-hash 门禁+working 优先选择、strict 词典失败整项回滚，与 README 一致
backend/modules/evidence/indexing/facade.py,已审,evidence/api.py、bootstrap DI、run_worker、writing、interaction、evals,D6a-3（无 __all__）；index_chapter 仅 tests/e2e 消费记 X1-S3 复核；其余公开函数均有真实消费者（逐符号 rg 取证）
backend/modules/evidence/indexing/index_state.py,已审,facade request/mark_dirty/freshness/summary、IndexingService claim/fence、run_worker reconcile、evals,D6a-2（summary/freshness 全量 ORM 加载计数，挂在 GET /chunks 上）、D6a-8（mark_running 生产零调用）；owner token(generation)+advisory lock+source fence 状态机严谨
backend/modules/evidence/indexing/indexing.py,已审,tasks.py 4 handler、facade、evals,无发现：lease/project fence、预计算后 begin_prepared source 重验、scene annotation 二次刷新、空 draft 收敛 fresh 均有针对性测试（test_indexing.py 34 个状态机/并发测试）
backend/modules/evidence/indexing/mappers.py,已审,retrieval/facade,无发现：47 行纯 ORM→Contract 映射
backend/modules/evidence/indexing/metrics.py,已审,facade.get_metrics_status→GET /metrics,D6a-7（meaningful_match_fail 指标生产恒不传）；线程锁+100 次聚合日志正常
backend/modules/evidence/indexing/query_expansion.py,已审,retrieval/chunk_annotation/entity_activity/source_collection,D6a-1（_expand_query_with_project_terms 与 QueryExpander.expand 33 行逐字重复且生产零调用）；60s TTL 词典缓存由 clear_project_terms_cache 在重标注请求/执行时失效，闭环
backend/modules/evidence/indexing/reranker.py,已审,RetrievalOrchestrator（RERANKER_ENABLED 时）,无发现：P21 严格 schema（ref 未知即拒、unsupported/roles 语义互验）、run_managed_structured 有界、1800s 总预算；测试覆盖 role tier/abstention/超时传递
backend/modules/evidence/indexing/retrieval.py,已审,facade.retrieve→API /retrieve、compilation(focused/interaction_story)、evals,D6a-6（keyword_query_terms 同参数重复计算）；meaningful-match guard、熔断降级、manifest 评分前二次过滤、去重防重复入列均有测试
backend/modules/evidence/indexing/scene_mapping_coverage.py,已审,compilation/evidence_health_service（作者健康面板）,无发现：valid/dangling/wrong-source/expected-overlap 四分对账语义与测试一致
backend/modules/evidence/indexing/schemas.py,已审,indexing/api.py 全端点+内部 chunk 创建,D6a-5（SimilarEntity/SimilarEntityResponse 死 schema）；其余 schema 校验（range validator、Literal、UUID coercion）完整
backend/modules/evidence/indexing/scoring.py,已审,retrieval,tuning,无发现：纯函数评分器，权重常量来自 shared.constants；n-gram 上界 96 有测试
backend/modules/evidence/indexing/source_collection.py,已审,IndexingService._prepare_chapter_index,无发现：空 draft 保留 source 身份收敛 fresh（有专项测试）；importance 读取失败显式抛出（测试锁定不吞）
backend/modules/evidence/indexing/tasks.py,已审,TaskRegistry：rag_index_chapter/rag_reindex_novel/rag_reannotate_entities/rag_retry_embeddings（47 handler 清单内）,无发现：meta 校验 fail-fast、coalesced 出口、DI port rag.index_chapter_for_task 消费、scene_annotation_only source 白名单与 README 一致
backend/modules/evidence/indexing/tests/__init__.py,已审,pytest 包标记,无发现：1 行
backend/modules/evidence/indexing/tests/conftest.py,已审,本目录全部测试,无发现：autouse 确定性假 embedding（real_llm marker 显式退出），哈希式 768 维向量可复现
backend/modules/evidence/indexing/tests/test_api.py,已审,API 门禁回归,无发现：回收站 404、全局工具豁免、split 422、缺 body 422 全覆盖
backend/modules/evidence/indexing/tests/test_chunking.py,已审,chunking,无发现：含 overlap>half 历史死循环回归测试
backend/modules/evidence/indexing/tests/test_chunking_params.py,已审,chunking 默认参数,D6a-9：docstring 写"target=700、max=900、overlap=130"与断言(900/1400/160)不符（历史参数残留）
backend/modules/evidence/indexing/tests/test_entity_activity.py,已审,entity_activity/manifest_appearances,无发现：跨章 scene 去重、stale hash 排除、coalescing follower、重标注失败保留投影均有有效断言
backend/modules/evidence/indexing/tests/test_indexing.py,已审,index_state 状态机/IndexingService fence/embedding writer/repo 重建,无发现：34 个测试覆盖 owner generation fencing、锁序、双 checkpoint、scene annotation 刷新回退、幂等重建、跨 novel 隔离；patch 全部 autospec=True
backend/modules/evidence/indexing/tests/test_indexing_retry.py,已审,retry_embeddings 双 seam,无发现：普通 seam 事务所有权、task checkpoint 3 次、stale 重规划单次计数、lease 丢失回滚、批失败终止均有断言
backend/modules/evidence/indexing/tests/test_query_expansion.py,已审,query_expansion,无发现：短名歧义不扩展、缓存命中、词典失败日志脱敏（[REDACTED] 断言）有效
backend/modules/evidence/indexing/tests/test_rag.py,已审,repo/retrieval/facade/契约,无发现（附注）：:1220/:1259 patch 死函数 _expand_query_with_project_terms（D6a-1 佐证）；RandomID 使词典缓存不致 flaky
backend/modules/evidence/indexing/tests/test_real_index.py,已审,合成语料回归+real-llm 验收,无发现：real_llm 门禁正确；确定性/守卫断言有效
backend/modules/evidence/indexing/tests/test_retrieval.py,已审,retrieval/reranker,无发现：dedup 防重复入列、role tier、abstention 不标 degraded、managed timeout 传递有断言；patch autospec
backend/modules/evidence/indexing/tests/test_scene_mapping_coverage.py,已审,coverage 服务,无发现：四类计数全部分支验证
backend/modules/evidence/indexing/tests/test_scoring.py,已审,scoring,无发现
backend/modules/evidence/indexing/tests/test_vector_search.py,已审,vector_search/方言回退,D6a-10：test_hybrid_search_with_query_embedding 断言包在 if len(results)>0 内（空结果静默通过）；其余 SQL 生成断言（limit/ef_search/order by asc）有效
backend/modules/evidence/indexing/tuning.py,已审,CLI：python -m modules.evidence.indexing.tuning（ops 工具）,无发现：离线权重网格搜索工具，embedding 失败限幅日志，仅测试消费其纯函数；保留
```

43 行全部覆盖，无遗漏、无受阻。

## 发现

| ID | 位置/符号 | 问题与触发 | 调用链证据 | 现有契约 | 最小方案 | 预期收益 | 风险 | 依赖 | 验证命令/断言 | 回滚 | 裁定 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D6a-1 | `backend/modules/evidence/indexing/query_expansion.py:145-176`（`_expand_query_with_project_terms`） | 与 `QueryExpander.expand`（:188-220）33 行逐字重复（requested 集合构建+`_matched_project_term_keys`+expanded join）；生产零调用：orchestrator 只持有 `QueryExpander` 实例，不调用该函数 | `rg "_expand_query_with_project_terms"` 全仓仅定义处 + `test_rag.py:1220/1259` 两处 monkeypatch；`facade.py:31 _query_expander = QueryExpander()`；`retrieval.py:124` 调 `self._query_expander.expand` | 函数从未是公开契约（下划线私有）；测试把"禁用扩展"意图 patch 在一个生产不调用的符号上，patch 实为 no-op（当前靠随机 novel_id 词典为空才巧合稳定） | 删除 `_expand_query_with_project_terms`；test_rag.py 两处 patch 改为 `QueryExpander.expand`（或向 orchestrator 注入空 term_loader 的 QueryExpander） | 删 33 行重复；消除"测试 patch 死符号"的假覆盖，防未来有人误以为该函数是活路径 | 低；两测试断言不依赖被 patch 符号的具体行为 | 无 | `make test TESTS="modules/evidence/indexing/tests"`；断言两 degraded 测试仍过 | git revert 单提交 | 实施候选 | P2 |
| D6a-2 | `backend/modules/evidence/indexing/index_state.py:786-816`（`summary`）、:818-851（`freshness`） | 两方法把该 novel 全部 `RagIndexState` 行加载为 ORM 实例后 Python 计数；`summary` 经 `facade.get_index_status`（facade.py:143）挂载在 `GET /api/evidence/indexing/chunks` 每次列表请求上 | `api.py:61-82 list_rag_chunks` → `get_index_status` → `RagIndexStateService().summary`；行数=章数×content_mode 数（1000 章项目≈2000 行/请求），仅为产出 6 个整数 | 响应字段 `index_freshness.by_content_mode{total,fresh,stale}` 是已承诺 wire 契约（README:265），不能删字段 | `summary` 改 SQL 聚合（GROUP BY content_mode + 三条件计数的单查询）；`freshness` 同理加范围 WHERE 聚合 | 列表端点少加载全部 state 行；收益随章数线性增长，绝对值待测（无性能基线，收益待测） | 低；纯读路径改写，字段不变 | 无 | `make test TESTS="modules/evidence/indexing/tests/test_rag.py"`（get_index_status 3 个测试）+ `test_indexing.py` freshness 断言 | git revert | 实施候选 | P2 |
| D6a-3 | `backend/modules/evidence/indexing/facade.py`（无 `__all__`）；根因视图 `modules/evidence/facade.py:3-4` | indexing/facade 与 compilation/facade 均无 `__all__`，`modules/evidence/facade` 的 star-import 把 `ChunkingService`/`QueryExpander`/`RagChunkRepository`/`RetrievalOrchestrator`/`IndexingService`/`uuid`/`AsyncSession` 等 14 个非函数名一并导出到跨模块公共面（A7-4/X1-3 的当前形态） | facade.py:14-27 的 import 均不带下划线别名；`from modules.evidence.facade import *` 语义下全部可见；实际外部消费仅经显式 import（全仓 120+ 处均为函数/契约符号），无任何模块消费这些泄漏类 | 对外契约是"经 facade import"约定本身；泄漏名从未被消费（rg 零命中），收窄无行为变化 | 给 `indexing/facade.py` 加 `__all__` = 全部公开函数 + 4 个 contract dataclass（与 D6b 侧 compilation/facade 同批配对实施） | 公共面收窄；防止未来跨模块直接 import 实现类成习惯 | 低；star-import 消费者不存在（evidence/__init__ 只 star contracts 不 star facade） | D6b 配对（同批一个 PR） | `make lint` + `python -c "import modules.evidence.facade"` + 全仓 grep 确认无 `from modules.evidence.facade import ChunkingService` 类消费 | git revert | 实施候选 | P2 |
| D6a-4 | `backend/modules/evidence/indexing/chunking.py:397-417`（`_choose_cn_boundary`） | 生产+测试零调用：`split_chinese_novel` 用 `_choose_cn_boundary_with_scenes`（:266），本函数是旧版边界选择残留 | `rg "_choose_cn_boundary\b"` 全仓仅定义行 | 私有 staticmethod，无契约 | 删除（21 行） | 死代码清除 | 无 | 无 | `make lint` + `pytest modules/evidence/indexing/tests/test_chunking.py test_chunking_params.py` | git revert | 实施候选 | P3 |
| D6a-5 | `contracts.py:71-98`（`RagQueryContract`）；`schemas.py:349-375`（`SimilarEntity`/`SimilarEntityResponse`）；`indexing/__init__.py` `__all__` 10 符号 | 三组死契约：RagQueryContract 生产零消费（检索参数实际逐参传递）；SimilarEntity/Response 对应的"相似实体检索"功能不存在（无端点/服务/仓库方法）；包级 `__all__` 10 符号无任何 `from modules.evidence.indexing import X` 消费者 | `rg` 全仓：RagQueryContract 仅测试+`__init__`；SimilarEntityResponse 仅 test_rag_extra/test_rag；`from modules.evidence.indexing import` 唯一命中是 `import api as rag_api` | RagChunkContract（compilation/novel_evidence 消费）、RagResultBundle（evals）等是活契约须保留；死组从未写入 wire | 删 RagQueryContract + SimilarEntity 两 schema + `__init__.py` 收窄；同步删 test_rag.py:1667-1709/TestRagContracts 中对应纯构造测试与 test_rag_extra.py 对应段（迁移不得删有效断言——这几个测试仅复述构造器，无行为断言） | 减少公共契约面的"看似可用"假象；README 对外契约节无需变化（未列死组） | 低；测试删除仅限复述构造的无效断言 | 无 | `make test TESTS="modules/evidence/indexing/tests tests/unit/test_rag_extra.py"` | git revert | 实施候选（README"供 import_text 使用"表述随批修正） | P3 |
| D6a-6 | `backend/modules/evidence/indexing/retrieval.py:223 与 :228` | `keyword_query_terms(expanded_query)` 同参数调用两次（`query_terms` 与 `chinese_terms_list`），每次做 NFKC+分词+n-gram 展开+去重（长查询上限 96+ terms） | 两行相邻，`chinese_terms_list` 可直接取 `query_terms`；纯函数无副作用 | 无外部契约 | `chinese_terms_list = query_terms`（或删别名统一用一个变量） | 每候选评分前少一次词项展开；可读性 | 无 | 无 | `pytest modules/evidence/indexing/tests/test_rag.py -k "hybrid or retrieve"` | git revert | 实施候选（顺手改） | P3 |
| D6a-7 | `backend/modules/evidence/indexing/metrics.py:24/47-60/108/130`（`meaningful_match_fail`） | `record()` 接受 `meaningful_match_fail` 且 snapshot 输出 `meaningful_match_fail_count`，但生产唯一调用方 `retrieval.py:550-557` 从不传该参——指标恒 0；meaningful-match-guard 返回空只计入 `empty` | `rg "meaningful_match_fail"` 生产仅 metrics.py 自身；`backend/tests/unit/test_rag_services.py:866-874` 只测参数存在 | `/metrics` wire 含该字段（恒 0 不算破坏契约，但属死指标） | 二选一：guard 触发时（retrieval.py:336-337 返回空路径）记录该计数（需把 guard 结果带出 hybrid_search）；或删字段+snapshot 键（wire 少一个恒 0 字段，属可见变化需按功能变更立项）。建议前者 | 诊断指标恢复语义 | 低 | 无 | `pytest tests/unit/test_rag_services.py -k meaningful` + 新增 guard 触发断言 | git revert | 实施候选 | P3 |
| D6a-8 | `backend/modules/evidence/indexing/index_state.py:525-588`（`mark_running`） | 生产零调用：task 路径已改走 `claim_task_owner`/`begin_prepared`（indexing.py），普通 request 走 `request`/`mark_dirty`；仅 `test_indexing.py` 4 处消费。姊妹方法 `begin_direct` 生产消费者仅 `evals/cli.py:725`（CI 活跃评测工具，按既定惯例不删） | `rg "state_service.mark_running|\bmark_running\(" 生产文件零命中（infrastructure/tasks/models.py 同名方法不相关） | 私有 service 方法；README 未列 | 与 D 组汇总后统一裁定：删除+迁移 4 处测试改测 `begin_prepared` 等价语义，或标注保留理由 | 少一个维护面状态机入口 | 低；测试改写需保留断言语义 | 无 | `pytest modules/evidence/indexing/tests/test_indexing.py -k "claim or duplicate"` | git revert | 候选（跨槽汇总后裁定，倾向删） | P3 |
| D6a-9 | `backend/modules/evidence/indexing/tests/test_chunking_params.py:18` | 测试 docstring 写"默认参数应为 target=700、max=900、overlap=130"，断言实际 900/1400/160——历史参数残留，误导后来者 | 与 chunking.py:34-36 常量直接矛盾 | 无 | 修 docstring | 文档真实性 | 无 | 无 | 目测 | git revert | 实施候选（顺手改） | P3 |
| D6a-10 | `backend/modules/evidence/indexing/tests/test_vector_search.py:180-194`（`test_hybrid_search_with_query_embedding`） | 断言包在 `if len(results) > 0:` 内：若召回退化为空（如 guard 误杀），测试静默通过，恰好失去对"向量分数贡献>0"的验证；且 768 维硬编码假设 embedding 配置 | 该测试用真实 repo+sqlite fallback；关键词"主角"按当前实现应命中（非空），弱断言是防御性遗留 | 无 | 拆两段显式断言：`assert results`（或有 embedding chunk 命中）后再验 score>0 | 消除静默通过路径 | 低；需确认 sqlite 下确非空（当前基线该测试通过即非空） | 无 | `pytest modules/evidence/indexing/tests/test_vector_search.py` | git revert | 实施候选（顺手改） | P3 |
| D6a-11 | `backend/modules/evidence/indexing/api.py:163-172`（`prewarm_rag_embedding`） | 捕获所有异常仅回 503 固定文案，无 logger——预热失败（模型缺失/队列超时）无服务端痕迹，排障只能靠复现 | 代码即证据；对照同文件其他端点均不吞异常 | 响应契约 `{detail}` 不变 | `logger.warning(..., exc_info=True)` 后再 raise HTTPException；不改变对外行为 | 可观测性 | 无 | 无 | `pytest modules/evidence/indexing/tests/test_api.py`（不涉该端点）+ 手工触发 | git revert | 实施候选（顺手改） | P3 |

无 P0/P1：检索与索引链的 novel_id 隔离（全部 repo 调用携带 novel_id；manifest tuple 过滤在 SQL 与评分双层执行）、owner generation fencing、source hash 重验、事务切分（task commit hook + expire_all）、诊断脱敏（redact_diagnostic）均有实现与针对性测试双重保障；未发现安全、数据丢失、隔离或恢复破坏类问题。

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A7-1（compilation/api.py:660-684 legacy GET 死路由 + 前端死契约死包装） | 仍成立（领域侧归 D6b；本槽位完成移交核实，见共享事实 3） | 前端 GET 契约 `apiContracts.js:339` 唯一消费者 `api.js:2078-2080 api.context.activationPreview` 全前端零调用（rg 仅定义处）；POST 版有真实消费者（`useWorldBible.js:1731`）。后端 GET 路由仅 `test_activation_profile_api.py` 一处显式标注 legacy 的测试消费 |
| A7-3（指纹同文件先合并，跨文件集中须逐字保留编码参数） | 不属本槽位（移交 D6b） | indexing 子域无任何自定义指纹实现（`rg "sha256|md5|def .*hash"` 在 indexing/ 仅 0 命中；source_content_hash 全部来自 writing facade）；同型 hash 变体集中在 compilation 12+ 处（focused_evidence/rag_chunks_loader/retrieval_query_planner/activation_profile_service 等），与 F1-3 stable_hash census 合并裁定 |
| A7-4 / X1-3（evidence/facade `__all__` 收窄到真实外部消费面 51 符号） | 仍成立（形态更新） | 当前两个子域 facade 均无 `__all__`（`rg "^__all__"` 零命中），star-export 把实现类泄漏到公共面；"51 符号"的旧统计与现状不符，应以现消费面重算。indexing 侧=D6a-3，compilation 侧归 D6b，建议同批实施 |
| X1-S3（evidence/facade ~8 个零引用死导出，含 evidence/facade 份额） | 部分仍成立（indexing 份额已查明） | indexing facade 公开函数逐符号 rg：`index_chapter` 仅 tests/e2e 消费（生产走 `index_chapter_with_report`）；`create_chunk`/`list_chunks`/`get_metrics_status`/`prewarm_embedding_runtime`/`split_text_into_chunks` 由 indexing/api.py HTTP 端点消费；其余（request_chapter_index、mark_chapter_index_dirty、reconcile_index_task_owners、bootstrap DI 5 项、manifest 两项、get_index_freshness/status、retrieve、get_scene_mapping_coverage、current_source_manifest、get_entity_activity_stats、request_entity_activity_reannotation）均有 production 消费者。indexing 侧死导出= index_chapter（facade 包装）+ D6a-5 三组契约符号；完整 8 项名单需并 D6b 侧后由主 Agent 合并裁定 |
| A7-6/7/8/9、X1-10/12（audit Reviewer 已剔除项） | 维持剔除（无新证据推翻） | 本轮逐项对当前代码重验：均无对应死代码/重复体残留可删（如 A7-6/7/8/9 原对象在现 indexing/compilation 结构中已不可定位为独立问题）；不重新立项 |
| F3-1 移交（后端 activation-preview 死路由核实） | 已核实（结论见共享事实 3） | 前后端全链 rg + 端点代码阅读；POST 版不得误删，GET 版删除方向与 A7-1 一致，删除后须同步移除 test_activation_profile_api.py 的 legacy GET 用例（归 D6b 实施） |

## 共享事实

### 1. 索引/失效/重建触发图（W3 链 4 Context 确认段可用）

- **写侧触发（标脏/入队）**：writing 保存/发布/AI candidate 流程 → `writing/api.py` 7 处 + `writing/assistant_candidate_tools.py:198` → `modules.evidence.facade.request_chapter_index`（幂等入队 `rag_index_chapter`，scope=("chapter_index", idx, mode)，`one_pending_follower`/`reuse_active` 收敛）或 `mark_chapter_index_dirty`（publish_chapter 已持有执行权时只标脏）。canonical 与 working 是同一状态键空间的不同 content_mode 行，分别重建。
- **任务执行**：`tasks.py handle_rag_index_chapter` → DI port `rag.index_chapter_for_task` → `IndexingService.index_chapter_for_task`：短事务① project FOR SHARE + lease 重验 + `_prepare_chapter_index`（writing manifest→切分→标注）+ `preflight_prepared`（source ID/hash 变了则重来，fresh 则免 embedding）+ `claim_task_owner`（owner=task_id+generation）→ commit（释放读事务）→ embedding（无事务）→ 短事务② project+lease 重验 + `begin_prepared`（同锁下重验 source hash，旧计划不得覆盖新 source）+ chunk 锁 + scene annotation 重刷新 + 替换 chunk + `finish`（requested==indexed→succeeded；否则 pending+再入队 follower）→ commit。同一 source 重复任务由 DB 部分唯一索引+`enqueue_coalesced_task` 合并；owner token（task_id+generation）使旧 attempt/旧 task 不能覆盖新 state。
- **失效（缓存与索引）**：① 正文变化→writing 侧主动 request（上述）；② 世界词典变化（对象名/别名/类型/采用状态）→ world 经组合根 DI port `rag.request_entity_activity_reannotation` → `EntityActivityService.request_reannotation`：先 `clear_project_terms_cache(nid)`（60s TTL 的 `_PROJECT_TERMS_CACHE`），再以 scope=("entity_activity",) 入队 `rag_reannotate_entities`（one_pending_follower）；worker 只重写 chunk 术语关联与 `rag_entity_appearances`，不动 embedding，仅处理 fresh hash 章；③ Scene 提交/替换 → 既有 `rag_reindex_novel` 任务带 `meta.source ∈ {deep_import_scene_commit, scene_replacement_apply}` → handler 走 `scene_annotation_only` 分支：chunk 流（text/hash/offset/序号）完全一致时原地刷新 scene_id/span 并重建受影响 appearance，不重切分不重嵌入、不领取 index state owner；流不一致则回退完整重建。
- **恢复**：worker 启动 `run_worker.py:113 → reconcile_index_task_owners`：仅 active project；owner task 不在 pending/running（按 heartbeat gap）时清 owner/递增 generation，并按当前 requested source 补一个 keyed task；项目在回收站只保留可重建 state/chunk、不补任务。`fail()` 带 expected-source fence，旧失败不覆盖新成功/新 pending。
- **fresh 判定**：`status=="succeeded" AND indexed_hash==requested_hash AND indexed_source_id==requested_source_id`；查询侧 `get_index_freshness`（范围）与 `summary`（全项目，见 D6a-2）。

### 2. 检索链路语义

`facade.retrieve(novel_id, query, …, source_manifest=None, mode, top_k≤50)` → `RetrievalOrchestrator.retrieve`：
1. 仅当该 novel `has_embeddings` 且熔断允许时生成 query embedding（失败/格式异常→degraded warning，纯关键词降级）；RERANKER_ENABLED（默认关）时候选池取 top_k×2。
2. `hybrid_search`：查询扩展（项目词典，60s 缓存；仅精确命中/显式 ID/3-4 字唯一短名扩展）→ 三路召回（keyword LIKE、vector `pgvector <#>` 升序、metadata 过滤），manifest 以 `{draft_id: hash}` tuple 条件下推到 SQL 且评分前逐 chunk 复核（旧稿 chunk 不会挤占当前稿排名）→ 动态权重 `0.50v+0.25k+0.12r+0.13i`（短/长查询偏置）+ `reference_chapter_index` 时序衰减（extraction 不衰减）。
3. meaningful-match guard：top_k 窗口内无关键词命中且无 ≥0.65 向量相似度（extraction 模式放宽为关系/章/scene 命中）→ 返回空（防 importance 劫持）。
4. embedding 余弦语义去重（窗口 120，阈值 0.9，保 char_count 大者）；reranker（开启时）经 `open_project_llm_client`（timeout_override=1800s）→ P21 严格 schema：supported/high-conf unsupported（abstain 返回空、不标 degraded）/uncertain（保留原序+degraded）；证据角色分层排序。
5. 输出 `RagResultBundle`（chunks+total+warnings+degraded）；召回含 failed/pending_vectorization chunk 时置 degraded。
- 消费分层：`/api/evidence/indexing/retrieve` 是索引诊断入口（固定 retrieval_purpose=manual_search，非作者证据直接展示）；作者检索/RP 走 compilation（rag_chunks_loader/interaction_story_context/focused_evidence 均从 `indexing.facade` import `retrieve` 并传入 exact manifest），原文回读与可见性门禁在 compilation 侧。跨模块隔离：indexing/facade 在 evidence 模块外无直接 import（仅 evals 经 modules.evidence.facade）。

### 3. activationPreview 端点消费者核实结论（F3-1 移交项）

- 后端有两个同路径端点（均在 `compilation/api.py`，D6b 文件）：GET `/api/evidence/compilation/activation-preview`（:660-683 `activation_preview`）与 POST（:686-694 `structured_activation_preview`），二者都委托 `_preview_activation`；POST docstring 自述"preserving the legacy GET route"。
- 前端：`apiContracts.js:339` 定义 GET 契约 `"context.activationPreview"`，唯一消费者是 `api.js:2078-2080` 的 `api.context.activationPreview` 包装；该包装在全前端（views/components/logic，排除 node_modules）零调用——死契约+死包装，F3-1 判定正确。
- `api.js:2082-2084` 的 `api.context.previewActivationProfile`（裸 POST，不走契约）有真实消费者：`frontend-console/vue/views/world/bible/useWorldBible.js:1731`（世界圣经激活配置预览，带 profile_id/action/task_text/top_k/depth payload）——**不得误删**。后端 facade 符号 `preview_activation_profile`（compilation/facade.py:655）是 POST 端点的实现委托（D6b 细节）。
- 裁定支持 A7-1/F3-1 的删除方向：可安全删除前端死契约（apiContracts.js:339）+死包装（api.js:2078-2080）与后端 GET legacy 路由（含 test_activation_profile_api.py 中显式标注 legacy 的 GET 用例，:120 附近）；POST 端点与其前端消费者必须保留。GET/POST 双轨删除后 World 侧 `activation_preview_service`（D2c 文件）消费面不变（其经后端内部调用，不经 HTTP）。

## 受阻

无。43 路径全部完成审查；未执行任何被禁命令（仅 rg/sed/cat/wc/ls 只读）。
