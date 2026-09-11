# D2a 槽位报告（R04 world：对象/关系/知识子域 + schemas/llm_schemas/contracts/任务/facade）

日期：2026-09-11。基线：main @ e7d0b8d5b（工作树）。全部只读；未运行测试/构建/make，无网络。
生产 32 文件全部逐文件语义阅读（schemas.py 5244 行全文通读、entity_fusion.py 2209 行全文通读、
entity_alias_service/entity_relation_service/authority/tasks 等 8 个大文件全文通读）；48 个模块内
测试文件：≤700 行者全文阅读，更大者按文件通读导入/fixture + 逐测试函数清单提取 + 抽读
断言密集段（覆盖声明见文末受阻节）。正典/工作稿/资料库可见性归 D2c，地图/图片/CAS 归 D2b，
本报告仅在交叉处记 cross-ref。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/world/asset_state.py,已审,CoreEntityResponse/EntityRelationResponse/CreationSuggestionResponse 派生投影 + attention service,无发现：纯函数投影；confidence 用 try/float 防 0.0 误判（符合模块 AGENTS is-not-None 语义）
backend/modules/world/authority.py,已审,world_authority_service(D2c)/canon API,无发现：Phase 0 封闭 wire；导入期 descriptor digest 自校验；canonical_json 拒绝 float/naive datetime；legacy float digest 独立函数不污染新输入
backend/modules/world/character_facade.py,已审,root facade re-export → interaction/evidence/story,无发现：薄委托；get_character_knowledge_entries limit=10000 硬上限（跨模块只读）
backend/modules/world/contracts.py,已审,跨模块契约（interaction/evidence/context/project）,无发现：frozen dataclass；WorldAliasRelationTaskPort/GenerationBackgroundProvider 为 DI Protocol
backend/modules/world/entity_facade.py,已审,root facade + imports/story/project 调用方,无发现：repair/get_deep_import_alias_metadata_summary 全项目扫描仅修复路径；parse_uuid 复用 shared.utils（非重复实现）
backend/modules/world/entity_fusion.py,已审,entity_facade.suggest/apply_entity_fusion* + tasks world_entity_fusion_suggestions + imports dedupe seam,无发现（指纹语义、锁序、fence 见共享事实）；性能观察记 D2a-8；execution 指纹冗余键记 D2a-7
backend/modules/world/event_facade.py,已审,root facade → story/memory,无发现：get_full_state 薄代理到 state_assembler（ADR-0001）
backend/modules/world/llm_schemas.py,已审,生成中心/问世界/校验 LLM 输出契约（generation_center_service 等消费）,无发现：字段级长度/枚举/去重归一化完整；AskWorldOutput 的 no_answer↔claims 互斥由 model_validator 强制
backend/modules/world/schemas.py,已审,world/api.py 全部 HTTP 契约 + 跨模块 facade 输出,D2a-5（json_encoders 死配置）；A4-2/A4-5/A3-3 复核见历史候选节
backend/modules/world/services/core/__init__.py,已审,package 标记,无发现（1 行 docstring）
backend/modules/world/services/core/character_knowledge_service.py,已审,/api/world/characters/{id}/knowledge + PUT/DELETE /api/world/knowledge,无发现：create/update 均做 character/target 双向 canonical+类型+novel_id 门禁；misconception 422 双层校验（schema+service）
backend/modules/world/services/core/character_service.py,已审,character_facade + ensure_for_core_entity（entity_service/promote 调用）,无发现：scaffold 原位升级（auto_materialized）；filter_context_by_character_knowledge 的唯一检查点选择依赖 repo 查询（cross-ref D2b repositories）
backend/modules/world/services/core/dedup_scorer.py,已审,EntityDedupService.find_similar_entities,D2a-6（to_vector/pg_trgm_raw/len_diff_ratio 生产零消费）
backend/modules/world/services/core/dedup_service.py,已审,entity_facade.find_similar_entities/merge_candidate_into_entity + entity_fusion + resolve_candidate,无发现：9 步合并事务锁序 target→candidate FOR UPDATE；跨 novel 双重校验；compatibility_shadow 拒绝直改；CandidateAction 为 shared.enums 生产引用点（F1-1 证据）
backend/modules/world/services/core/entity_alias_service.py,已审,world/api.py 别名全部路由 + entity_facade + entity_fusion apply,D2a-3（create_alias 大小写敏感查重与内部其它路径/README 不一致）；指纹/锁序见共享事实
backend/modules/world/services/core/entity_context_service.py,已审,entity_facade（get_world_context/list_entity_terms/find_*）+ imports Phase 2b,无发现：find_working_entity_by_name 单名版每次全量加载 ≤10000 行（调用方循环时 N+1，批量版已备，cross-ref D5a/D2b）
backend/modules/world/services/core/entity_embedding_service.py,已审,entity_facade.backfill_entity_embeddings,无发现：批失败 continue 并 redact 日志；空名配对过滤防索引错位
backend/modules/world/services/core/entity_relation_service.py,已审,world/api.py 关系全部路由 + review-batch + entity_facade,D2a-2（expand_related set 截断/无序）；复核批锁序/指纹语义见共享事实
backend/modules/world/services/core/entity_revision_service.py,已审,rollback 路由 + entity_service.update/delete/promote 快照,无发现：TextArchive 优先、EntityRevision 兜底（符合 README）；rollback 前先在行锁内打快照
backend/modules/world/services/core/entity_service.py,已审,world/api.py 实体 CRUD/promote + suggestion_queue（_from_suggestion_queue 旁路）,无发现：类型转换快照传播失败、普通编辑快照 best-effort；canonical 直写全走 require_legacy_canon_write_allowed 门禁
backend/modules/world/services/core/entity_stats_service.py,已审,entity_facade 统计/深度导入废弃 seam,无发现：deprecate 后请求活动重标注
backend/modules/world/services/core/entity_type_transition_service.py,已审,entity_service.update/promote/rollback 类型转换唯一入口,无发现： blocker 计数用 DB 粗筛+Python 精判（语义注释明确）；profile 迁移带快照 journal 可回溯
backend/modules/world/services/core/entity_types.py,已审,schemas 归一化 + entity_service + AI 边界,无发现：作者 1-64 字符安全自定义 vs AI 固定目录双边界清晰；控制字符拒绝
backend/modules/world/services/core/event_service.py,已审,world/api.py 事件路由 + event_facade,无发现：entity/location 双 canonical 门禁；变更后 mark_synopsis_source_changed
backend/modules/world/services/worldbuilding/__init__.py,已审,package 标记,无发现（1 行 docstring）
backend/modules/world/services/worldbuilding/conflict_queue_service.py,已审,worldbook import/semantic inspection 冲突队列 + /api/world/conflicts,无发现：替换语义只 stale 同 source_key/page_id 的 pending；resolve 按 novel_id 门禁
backend/modules/world/services/worldbuilding/knowledge_graph_service.py,已审,GET /api/world/knowledge-graph（只读关联图）,无发现：节点/边全量 id 排序 + 固定 cap + 截断回执 + source_hash；坏引用计入 omissions 不冒充 0
backend/modules/world/services/worldbuilding/knowledge_tag_service.py,已审,knowledge 标签排除/锁定/派生同步 API,无发现：author_locked 派生标签不被清理；species/location 引用做同项目 canonical 校验
backend/modules/world/services/worldbuilding/profile_service.py,已审,world profile upsert/migrate API,无发现：strong/generic 互斥由 _ensure_no_generic 门禁；写后 mark_synopsis_source_changed
backend/modules/world/services/worldbuilding/shared.py,已审,PROFILE_REGISTRY 常量（transition/profile_service 消费）,无发现
backend/modules/world/tasks.py,已审,TaskWorker 注册面（7 个 handler）,无发现：各 handler 身份校验/两阶段 checkpoint/锁序见共享事实；bare "running" 字符串为 F2-5 领域侧证据（cross-ref）
backend/modules/world/world_background.py,已审,worldbuilding_facade.get_world_background → context 编译/地图册,D2a-1（CharacterKnowledge limit 无 ORDER BY；relation strength 平局未消序）
backend/modules/world/tests/conftest.py,已审,world 模块全部测试,无发现：project_novel_id/two_projects fixture 走真实 project 创建
backend/modules/world/tests/helpers.py,已审,world 模块测试,无发现：publish_bible_draft 走 owner-confirm canon adapter
backend/modules/world/tests/test_activation_preview.py,已审,activation_preview_service（D6 消费面）,无发现：legacy refs + missing/top_k 排除追踪断言有效
backend/modules/world/tests/test_active_child_guards.py,已审,characters/events/character_knowledge 活跃扩展守卫,无发现：shadow/未采用 owner/target 拒绝与列表隐藏均覆盖
backend/modules/world/tests/test_adoption_package.py,已审,WorldAdoptionPackage 领域+API,无发现：幂等 apply/失败回滚可重试/owner 隔离/页 claim 覆盖 20 测试全为有效断言
backend/modules/world/tests/test_ai_extraction_api.py,已审,补抽 API 入队 + 任务 session 门禁,无发现
backend/modules/world/tests/test_alias_relation_task_transactions.py,已审,alias/relation 任务 checkpoint/fence/恢复,无发现：17 测试覆盖 provider 前 checkpoint、receipt 复用、v1 fail-closed、lease 丢失、source-writer 冲突、真实 _TaskHandlerSession fence
backend/modules/world/tests/test_assistant_cocreation_tools.py,已审,assistant 页面维护工具（world baseline 侧）,无发现
backend/modules/world/tests/test_assistant_map_tools.py,已审,assistant 地图工具,无发现；注意其 helper 从 test_map_structure 跨测试模块 import（轻微组织问题，不立项）
backend/modules/world/tests/test_assistant_page_tools.py,已审,assistant 共创工具（world baseline 侧）,无发现
backend/modules/world/tests/test_character_api.py,已审,/api/world/characters 契约,无发现：scaffold 物化/升级/类型纠正后隐藏全覆盖
backend/modules/world/tests/test_character_knowledge_levels.py,已审,knowledge 等级 schema/API/filter_context,无发现：false_belief 必须 misconception、misconception 替换不回泄作者事实等断言有效
backend/modules/world/tests/test_custom_entity_types.py,已审,entity_types/类型转换守卫,无发现：作者自定义 vs AI 系统边界、profile 反向引用 blocker、行锁断言全有效
backend/modules/world/tests/test_dedup_scorer.py,已审,DedupScorer/级联评分,D2a-4（test_exact_name_not_handled_by_cascade 空测试仅 pass）
backend/modules/world/tests/test_edit_baseline.py,已审,expected_updated_at 409 契约（draft/entity/character）,无发现：missing/stale/refresh 全路径
backend/modules/world/tests/test_entity_alias_service.py,已审,EntityAliasService 全域,无发现：31 测试含 marker 失败不阻塞写、投影历史态、rollback 保留手改、无 HTTPException 依赖静态断言
backend/modules/world/tests/test_entity_context_service.py,已审,EntityContextService,无发现：include_review/临时对象过期/reveal_mode/批量单次加载均有有效断言
backend/modules/world/tests/test_entity_embedding_service.py,已审,EntityEmbeddingService,无发现：BGE 不可用返回 0、批失败继续
backend/modules/world/tests/test_entity_fusion.py,已审,WorldEntityFusionService 全域,无发现：34 测试覆盖 fence/锁序事件序列/novel 隔离/snapshot 冻结复用/asset 漂移跳过/keep_separate 重生成/SQL 批量断言；patch 均 autospec=True
backend/modules/world/tests/test_entity_rollback_snapshot.py,已审,手动编辑快照/回滚,无发现：跨 novel 快照拒绝有断言
backend/modules/world/tests/test_entity_stats_service.py,已审,EntityStatsService,无发现：边界（0、畸形 chapter index、candidate 显式请求）全覆盖
backend/modules/world/tests/test_focused_completion.py,已审,专项查漏 v2 包（focused_adoption 消费面）,无发现：授权/lease/quote 唯一性/跨项目拒绝/undo 保留冲突
backend/modules/world/tests/test_generation_prompt_templates.py,已审,生成 Prompt 模板,无发现：内置只读/版本 CAS/危险指令拒绝/确定性 preview
backend/modules/world/tests/test_guimi_ask_scope.py,已审,ask-world 确认范围/预算,无发现
backend/modules/world/tests/test_knowledge_graph.py,已审,WorldKnowledgeGraphService,无发现：确定性截断/manifest 跟随 revision/有界查询数/owner 隔离
backend/modules/world/tests/test_manual_context_gate.py,已审,手动 action↔confirmation 精确匹配,无发现：validation/synopsis worker 只消费 confirmed allowlist
backend/modules/world/tests/test_map_spatial_v2.py,已审,map_structure v2（D2b 领域）,本槽只覆盖文件存在性与测试面清点；领域结论归 D2b（cross-ref）
backend/modules/world/tests/test_project_gate.py,已审,项目活跃门禁 404 回归,无发现：回收站项目 6 端点统一 404、全局模板目录豁免
backend/modules/world/tests/test_relation_alias_review_queue.py,已审,关系/别名复核工作台,无发现：schema 拒绝/DB 故障传播/组指纹 stale/50 条分批/反向组/注意力过滤先于分页全覆盖
backend/modules/world/tests/test_repositories.py,已审,CoreEntityRepository 等（D2b 主审）,无发现（本槽读毕）：0 strength 保留、fuzzy fallback savepoint、稳定分页 tie-break 均有断言
backend/modules/world/tests/test_state_assembler.py,已审,state_assembler（memory 快照契约）,无发现：canonical 过滤/0 importance 保留/novel 隔离/DB 错误传播
backend/modules/world/tests/test_world.py,已审,WorldEntityService/NovelIsolation/DedupService/路由,无发现：2015 行 38 测试；uow/复用已加载实体/跨项目隔离/别名列表隔离全有效
backend/modules/world/tests/test_world_authority.py,已审,authority kernel + canon admission,无发现：幂等 admission/revert append-only/长历史 replay 无递归/未注册 calendar 拒绝
backend/modules/world/tests/test_world_background_hash.py,已审,WorldBackgroundAggregation source_hash,无发现（但未覆盖 D2a-1 的选择稳定性，见该发现）
backend/modules/world/tests/test_world_bible_canon_adapters.py,已审,legacy 页面 adapter→Canon,无发现：canon 先锁/决策重放/错误稳定
backend/modules/world/tests/test_world_bible_synopsis_workspace.py,已审,简介工作台,无发现：35 测试覆盖 task fence/CAS/pin/降级/来源冻结
backend/modules/world/tests/test_world_bible_v2.py,已审,World Bible v2 sections/模板/发布影响,无发现（工作稿/正典主审 D2c）
backend/modules/world/tests/test_world_bible_v2_api.py,已审,页模板 API,无发现
backend/modules/world/tests/test_world_cocreation_sessions.py,已审,共创会话,无发现：checkpoint 漂移/崩溃恢复/分页/项目隔离
backend/modules/world/tests/test_world_cross_domain_review.py,已审,跨域校验冻结范围,无发现
backend/modules/world/tests/test_world_facade.py,已审,entity_facade 全 facade 面,无发现：1728 行 39 测试含 0.0 float 保留、importance map canonical-only、facade leak 各方法
backend/modules/world/tests/test_world_generation_center_api.py,已审,生成中心 API,无发现：66 测试覆盖只读/409 漂移/预算/快照/跨项目拒绝/死路由不注册
backend/modules/world/tests/test_world_library_api.py,已审,资料库 API,无发现（资料库主审 D2c）
backend/modules/world/tests/test_world_object_management.py,已审,实体搜索/手动创建/关系校验/知识边界 API,无发现
backend/modules/world/tests/test_world_review_phase4.py,已审,校验复核 phase4,无发现：硬错误不可签收/失败回执重验/语义 gap 冻结/跨项目隔离
backend/modules/world/tests/test_world_validation.py,已审,WorldValidationService 校验面,无发现：声明式 operator/full run 单飞/stale/warning 签收/预算
backend/modules/world/tests/test_worldbook_import.py,已审,worldbook 目录导入,无发现：三方比较/不安全路径拒绝/中断回滚可重试
backend/modules/world/tests/test_worldbuilding_workspace.py,已审,workspace hub/建议队列/投影,无发现：old hub monkeypatch 兼容、shadow 不可绕过队列、未知 target_type 拒绝
```

80/80 路径覆盖，无受阻路径（测试大文件阅读深度声明见受阻节）。

## 发现

| ID | 位置/符号 | 问题与触发 | 调用链证据 | 现有契约 | 最小方案 | 预期收益 | 风险 | 依赖 | 验证命令/断言 | 回滚 | 裁定 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D2a-1 | `backend/modules/world/world_background.py:186-193`（CharacterKnowledge 查询）、`:144-159`（relation 查询） | CharacterKnowledge 查询 `.limit(limit)` 前无任何 `ORDER BY`——PG 无序 limit 的返回子集不稳定；relation 仅 `order_by(strength.desc())`，同 strength 平局顺序未定义。当单项目知识/关系数超过 `limit`（默认 160）时，每次 build 选取与排序的条目集可能不同，派生 WorldBackgroundBundle 组合（进而 context 激活输入）逐次波动 | `WorldBackgroundAggregation.build` 被(worldbuilding_facade.py)`get_world_background` 消费，进入 context 编译与地图册 operation；实体/页面两查询已显式排序（importance,name / sort_order,title），唯独 knowledge 与 relation 弱 | 契约仅承诺"只读派生、不写事实"（contracts.py docstring），未承诺选择稳定；但 source_hash 逐条内容寻址使组合漂移可被上层感知 | knowledge 查询加 `.order_by(CharacterKnowledge.id)`（或 character_id,id）；relation 追加 `, EntityRelation.id` tie-break。不改变 payload/hash 字节格式，仅稳定成员选择 | 消除 context 背景组成的非确定性波动；便于 W3 链 3"历史读取"断言稳定 | 极低；纯确定性排序，无行为语义变化 | 无 | `make test TESTS="modules/world/tests/test_world_background_hash.py modules/world/tests/test_world_facade.py"`；新增断言：同一数据两次 build 的 entries 列表逐项相等 | git revert 单文件 | 实施候选 | P2 |
| D2a-2 | `backend/modules/world/services/core/entity_relation_service.py:1387-1401,1416`（`expand_related`） | `related_ids` 为 `set`，`list(related_ids)[:limit]` 截断与 `related_entity_ids=list(related_ids)` 输出均依赖 set 迭代序——同批种子命中超过 `limit` 时每次返回的子集与顺序都可能不同 | `entity_facade.expand_related` → root facade（README 对外契约）→ context/RP 调用方；repo `get_related_entity_ids_for_seeds` 的 DB 排序在入 set 后丢失 | README 未承诺顺序；但返回是 `list[WorldEntityContext]`，消费方按序展示 | 改为 `sorted(related_ids)[:limit]`，输出 `related_entity_ids=sorted(related_ids)`（或保留 repo 序：repo 返回 list 前不移入 set） | 结果可复现，测试不再依赖隐式序 | 极低；纯排序 | 无 | `make test TESTS="modules/world/tests/test_world_facade.py"` | git revert | 实施候选 | P3 |
| D2a-3 | `backend/modules/world/services/core/entity_alias_service.py:891-894`（`create_alias` 查重） | `create_alias` 用大小写敏感精确匹配（`existing == normalized_alias`）拒绝重复；同文件 `_has_duplicate_alias`(:339-353) 与 `append_candidate_alias`(:1320-1323) 均大小写不敏感；模块 README 明确"去重检查：别名不与已有别名重复（大小写不敏感）"。`POST /api/world/aliases`（api.py:3794→create_alias）传 "Klein" 而已有 "klein" 时创建成功，违反声明契约并在后续 edit/复核路径造成大小写变体重复 | api.py:3794 路由 → create_alias；对照 `_has_duplicate_alias` 的 casefold 语义与 README aliases 节 | README："别名不与已有别名重复（大小写不敏感）" | create_alias 的重复检查改用 `self._has_duplicate_alias(aliases, normalized_alias)`；注意这是收紧：曾可创建的大小写变体现在 409。属修复既与文档不符的行为，按计划 §2 单列为功能修正而非纯优化 | 契约一致；消除变体重复别名进入复核队列 | 低；行为收紧需在发布说明标注；已有变体数据不自动清洗 | 无 | `make test TESTS="modules/world/tests/test_entity_alias_service.py"`（补一条大小写变体 409 断言） | git revert | 实施候选（行为修正） | P3 |
| D2a-4 | `backend/modules/world/tests/test_dedup_scorer.py:232-237`（`test_exact_name_not_handled_by_cascade`） | 测试体只有 `pass` 与注释，零断言；它在测试清单里伪装成"精确匹配不走级联"的覆盖，实际无任何验证 | `pytest` 收集后恒绿 | 无 | 删除该测试，或改写为真实断言（对 `find_similar_entities` 的 exact_name 分支断言 method=="exact_name" 且未调用 `_cascade_score`） | 消除假覆盖 | 无 | 无 | `make test TESTS="modules/world/tests/test_dedup_scorer.py"` | git revert | 实施候选（顺手改） | P3 |
| D2a-5 | `backend/modules/world/schemas.py:1120,1219,1942,2059`（`json_encoders={uuid.UUID: str}`） | 4 个 Response 模型保留 Pydantic v1 风格 `json_encoders`；v2.13 下这些字段全部声明为 `str`，UUID 仅经 `mode="before"` coercion 进入，该配置在 model_dump_json 序列化路径上已无作用，属死配置（且是 v2 已弃用面） | pydantic 2.13.4（pyproject `pydantic>=2.6.0`）；4 个模型的 UUID 字段均被 coerce validator 提前转 str | 无（无行为依赖） | 删除 4 处 `json_encoders`（连同仅为此保留的 ConfigDict，如无其它键） | 减少弃用面/误导后来者 | 低；需确认无调用方依赖被弃用的 `.json()` 对 UUID 的编码——字段类型为 str，无此路径 | 无 | `make test TESTS="modules/world/tests/test_world.py"` + 全模块 fast | git revert | 实施候选 | P3 |
| D2a-6 | `backend/modules/world/services/core/dedup_scorer.py:100-110`（`DedupSignals.to_vector`）、`:88-97`（`len_diff_ratio`/`pg_trgm_raw` 字段） | `to_vector`"供 ML 模型使用"无任何生产/训练消费（rg 全仓仅 test_dedup_scorer 引用）；`pg_trgm_raw`/`len_diff_ratio` 每次被 compute_signals 计算但不参与 `_cascade_score` 任何路径 | `rg "to_vector|pg_trgm_raw|len_diff_ratio" -g '!**/.venv/**'` 仅命中 scorer 与其测试；dedup_service._cascade_score 只用 ratio/token_sort/pinyin/substring/semantic/prefix_conflict | 无外部契约 | 保留现状（记录性）或顺手删 to_vector + 两个未消费信号的计算与字段（需同步更新其单测）。因 compute_signals 成本极低，非必要不动 | 删去"伪 ML 接口"误导；每次去重少 2 次纯计算（可忽略） | 低；删字段需改测试 | 无 | `make test TESTS="modules/world/tests/test_dedup_scorer.py"` | git revert | 保留现状 / P3 顺手项 | P3 |
| D2a-7 | `backend/modules/world/entity_fusion.py:1270-1289`（`_entity_fingerprints` execution dict） | `execution = {**semantic, ...}` 展开后又逐字重列 `public_info/hidden_truth/importance/importance_level/reveal_level`——值与 semantic 展开完全相同，纯冗余键（疑为 semantic 曾收窄后的防御残留） | 直接读码；`_hash_payload` 对重复键赋同值，序列化字节不变 | 指纹字节不得变化（§6 hash 条） | 仅当能以固定样本证明删除前后 `_hash_payload(execution)` 字节一致时删除冗余键；否则保留（写注释说明） | 可读性 | 关键风险是指纹字节漂移——**保守裁定：保留现状，仅记录**（删除收益≈0，风险≠0） | 无 | 如实施：固定输入样本对比 sha256 前后一致 + fusion 全测试 | git revert | 保留现状（记录） | P3 |
| D2a-8 | `backend/modules/world/entity_fusion.py:1505-1621`（`_candidate_pairs`） | 双重 O(n²) Python 循环 + 每个 source 一次 `find_similar_entities`（每次 2 个 DB 查询 + 打分）；workflow 去重路径以 `limit=10_000/max_suggestions=10_000` 调用 `_prepare_task_scan`（:416-428），最坏 ~10⁸ 次相似度计算 + 2 万次查询发生在首个 lease-fenced commit 之前的单个只读长事务内 | `dedupe_workflow_candidates_for_task`（imports 深度导入调用）→ `suggest_for_task` → `_prepare_task_scan`；注释自认"one import is capped at 10k objects" | 首个 commit 前"不做 provider I/O"契约未被破坏（纯 DB/内存）；但事务持有时长随候选规模平方增长 | 不单独立项：先由 D2b/X2 用真实规模测量 `_prepare_task_scan` 耗时与事务时长；超标再谈分块 checkpoint 或 DB 侧预筛 | 待测 | 测量前不动（避免破坏"完整候选边集成组"语义） | D2b/X2 性能取证 | `docs/diagnostics/performance.md` 隔离流程（本机 performance_probe 必败，需按 runbook） | 不适用 | 补证据（收益待测） | P3 |

无 P0/P1：未发现安全、`novel_id` 隔离、数据丢失或恢复破坏类新问题。任务 fence/锁序/CAS/二次确认等关键不变量与生产实现一致并有有效测试（详见共享事实）。

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A4-2 world/schemas.py 34 处 uuid coercion validator → Annotated 别名（~180 行） | 仍成立（形态修正，收益估计下调） | 实测 schemas.py 中纯 coercion（`_uuid_validator`/`_optional_uuid_validator` 直传）的 validator 定义共 **29 个**（:580,1149,1228,1315,1456,1976,2088,2124,2645,2743,2777,2800,2986,2991,3334,3476,3551,3565,3581,3595,3600,3723,3814,3838,3949,4006,4989,5038,5158），覆盖约 34 个字段实例——历史"34 处"按字段计。可收敛为 `UuidStr = Annotated[str, BeforeValidator(_uuid_validator)]` / `OptionalUuidStr = Annotated[str\|None, BeforeValidator(_optional_uuid_validator)]` 两个别名；行为逐字保留（同一函数、同为 before 语义、错误消息不变、OpenAPI schema 不变，因 validator 不改变 schema）。**不得并入**的 4 个特殊 validator：`:951/:970`（`str(uuid.UUID(value))` 严格校验+规范化）、`:3648/:3678`（纯 `str(value)` 非 UUID 语义）。行数收益约 120–150 而非 180 |
| A4-5 compatibility_status 收窄 | 已解决（已实现）/ 进一步收窄属新行为变更 | `suggestion_queue_service.py:110-115` 已将 compatibility_status 限定为 `{None,"draft","candidate"}`，越界直接 ValidationError；当前生产调用方（world_generation_center_service.py:1514）与全部测试只传 `"candidate"`。若要再收窄到 candidate-only 属 §2 行为收紧，需按功能变更立项，非清理项 |
| A3-3 业务枚举 Literal→StrEnum（world 枚举部分） | 保留现状（world 面收益不足） | world 生产对 shared.enums 的消费仅 2 个：`CandidateAction`（dedup_service.py:36）、`RelationType`（review_queue.py:9）——这两处已是 StrEnum。world/schemas.py 其余枚举全部是 Pydantic `Literal`（`RelationKind/AliasKind/ObjectDraftTemplate/...` + WorldState* 内联 Literal），职责是 wire 校验/OpenAPI；换成 StrEnum 需同步 wire 值与错误面，收益仅风格。authority.py 的 Literal 同理（封闭 wire，改动会触碰 canon 语义）。裁定：world 部分不参与 A3-3 批次 |
| 其余 A4-* 落本槽范围者 | 分流 | A4-1（全局 DomainError handler，"world 10 处确认冗余先删"）：目标文件是 world/api.py，**不在本槽 80 路径**，移交持有 api.py 的槽位复核；A4-3/A4-4 前端侧归 D8；A4-8（world_generation_center 结构化包装共享骨架）目标在 world_generation_center_service.py，归 D2c（cross-ref） |
| F1-1（交叉佐证请求）：shared/enums 14/17 枚举零引用 vs world 的 import | world 域证据已核实，修正 F1-1 统计 | `rg "from shared.enums import" modules/world -g '!tests/**'` 仅 2 处：dedup_service.py:36 `CandidateAction`、review_queue.py:9 `RelationType`。即 world 生产引用了 CandidateAction 与 RelationType 两个枚举；F1-1 的"14/17 零引用"若把这两个计入零引用则需扣除。world/tests 另引用 CandidateAction（test_dedup_scorer），不构成生产引用 |

## 共享事实（供 W3 链 3"工作稿→校验→采用→失效→历史读取"、链 5 及后续槽位引用）

### 1. 对象/关系/知识数据流地图（本槽生产面）

- 写入边界（候选→正史）：AI/导入一律 `status=candidate/draft` 进入 `core_entities`；唯一提升入口 `WorldEntityService.promote`（/entities/{id}/promote）与 suggestion 队列采用（`_from_suggestion_queue` 旁路 compatibility_shadow 门禁）；所有 canonical 直写（create/update 关系/别名/合并/promote/upsert_relationship）先经 `WorldValidationService.require_legacy_canon_write_allowed`（启用 validation policy 后 fail-closed，D2c 拥有策略本体）。
- 合并/别名化：`EntityDedupService.merge_candidate_into_entity`（9 步：target FOR UPDATE → 验证 → candidate FOR UPDATE → 别名继承 → 关系迁移/去重 → 自环清理 → Character 同步 → 文本合并 → 冲突归档 → source 标 `merged`）；`EntityAliasService.resolve_candidate_as_alias`（组内原子：登记别名/原位确认已存在待复核别名 → 迁移关系 → source 标 `merged`+`resolved_as`）。组级严格路径 `WorldEntityFusionService.apply_group`：每操作验 execution fingerprint + canonical 双确认位（allow_canonical_merge/alias），错误上抛由调用方 savepoint 回滚。
- 失效联动（对象/关系/知识变更后）：`mark_asset_context_changed`（evidence facade，best-effort+日志，reason: entity_renamed/ignored/deprecated/merged/candidate_promoted/entity_type_changed/alias_updated/relation_review_batch 等）；`mark_synopsis_source_changed`（entity_relation/core_entity/event/profile）；`request_entity_activity_reannotation`（RAG 出场词表重标注，组合根 port）。类型转换（`EntityTypeTransitionService`）是唯一类型迁移入口：blocker 计数 + profile 快照 journal（`_type_migration_v1`）+ 图片配额门禁。
- 知识数据流：`CharacterKnowledgeService.create/update` 强制 character 与 target 双 canonical+类型+novel 门禁；读者/角色侧消费只取 canonical、按目标唯一检查点（先最晚生效章、再更新时间+稳定 ID，唯一性逻辑在 repo，D2b 引用）；`false_belief/misunderstood` 仅下发 `misconception`。
- 回滚链：活跃回滚 `rollback_to_scene_index` 优先 TextArchive、无归档回退最近 EntityRevision；显式 `rollback_to_revision`；回滚前在行锁内先打当前快照。

### 2. schemas 校验面摘要（schemas.py 5244 行 + llm_schemas.py）

- UUID 面：Response/Facade 输出模型一律 `mode="before"` 字符串化（29 个纯 coercion validator）；两个请求 payload（EntityRelationSuggestionPayload、EntityAliasSuggestionPayload）用 `str(uuid.UUID(v))` 严格校验；世界对象创建/更新 entity_type 走 `normalize_author_entity_type`（1–64 字符、拒保留名/控制字符），AI/suggestion 走 `normalize_system_entity_type`（固定 20 类目录）。
- null/空串语义：`*_Update` 模型普遍 `Annotated[str|None, Field(None)]` + `model_fields_set` 区分"未传"与"显式 null"；WorldBiblePageUpdate/CategoryUpdate/DraftUpdate/TemplateUpdate 显式 `reject_null_required_fields`（409/422 拒绝置 null）；fill_empty 语义把 `None/纯空白` 视为空、`0/false` 不视为空（schemas.py:4744-4750 注释一致）。
- hash/fingerprint 字段：全库统一小写 sha256 hex64（`pattern=^[0-9a-f]{64}$` 或 `_validate_lower_sha256`），出现在 execution_fingerprint/source_hash/manifest_hash/preview_hash/receipt_hash/impact_scope_hash/request_fingerprint 等——任何上游序列化变化都会在此显式 fail。
- 批处理契约：关系 review-batch（≤20 决策、≤50 关系、confirmed=true、成员唯一、组指纹必带）；别名 review-batch（≤50、`(entity_id, alias.casefold())` 唯一、confirmed=true）；extra="forbid" 广泛用于 checkpoint/policy/package/adoption 类封闭 payload。
- llm_schemas.py：全部 LLM 结构化输出的入站校验（长度/枚举/互斥），AskWorld 的 `no_answer↔claims` 互斥由 model_validator 强制；生成中心聊天禁 json_object 模式（空 content 重试一次）由消费方实现。

### 3. world/tasks.py handler 清单及幂等/恢复语义（7 个，全部 `auto_requeue, max_attempts=2`）

| handler | 身份校验 | 幂等/恢复 |
|---|---|---|
| `world_validation` | task_type/status=running/lease_id/attempt≥1/novel_id/run_id 全验 | confirmation 重物化（可选）；执行委托 `execute_run`（run 内部 attempt/lease/冻结 hash，D2c） |
| `world_alias_relation_extraction` | 同上 + confirmation owner（result_refs 末个 task ref == 本 task） | 三段 checkpoint `prepared→llm_complete→done`（state 存 task.result）；stage=done 直接返回 final_result；llm_complete 复用 detached receipt 不再调 provider；v1 残留 fail-closed；提交时缺 snapshot 则补建+commit+全量重门禁；终局锁序：project exclusive → running source-writer 冲突检查 → running attempt lease 复验 → confirmation FOR UPDATE → finalize → attach refs → done checkpoint（`_commit_alias_relation_checkpoint` 失败回滚 detached 字段并保持无事务） |
| `world_entity_fusion_suggestions` | 委托 `suggest_for_task`（require_task_checkpoint_session + require_active_project） | `_decide_task_plan`：初始 checkpoint 后 `db.commit()`（首个 lease-fenced commit），此后每批（12 对）锁序重验（semantic/execution/disposition/pair 四指纹）+ checkpoint + commit；漂移只记 reason 跳过；snapshot 缺失由 snapshot_callback 冻结进 meta，重试复用 |
| `world_cocreation_turn` | lease 校验 + `WorldCocreationTurnTaskRequest` 从 meta 重建 | `task.result._cocreation_turn_response` 存在即直接返回（终态幂等）；会话行锁内校验 status=active + checkpoint 指针 == expected，漂移 409 不写；消息与回执同一 fenced commit |
| `world_generation_suggestion` | meta 重建请求（仅取 model_fields 内键） | 必须带 llm_execution_snapshot；session outcome 由 `record_generation_outcome` 幂等绑定（缺会话跳过） |
| `world_bible_projection_refresh` | novel_id/page_id 必填 | 领域幂等：`(page_id, projection_type)` DB keyed coalescing + page version/source hash CAS（提交侧）决定旧结果不覆盖新页 |
| `world_bible_synopsis_refresh` | novel_id/source_hash 必填 | 两阶段 seam（project FOR SHARE 冻结 manifest/snapshot → lease-fenced checkpoint 释放事务 → LLM → 重验 source/desired/pin/current/active）；异常走 `record_task_failure`（带 fence）后重抛；旧失败不得覆盖新成功/作者 pin |

### 4. 指纹/hash 生成点清单（§6 hash 条——动任何一个都会使旧指纹/回执失效）

| 生成点 | 序列化 | 消费/失效语义 |
|---|---|---|
| `entity_fusion._hash_payload`（:2180）`json.dumps(sort_keys, ensure_ascii=False, default=str)`（默认分隔符 `, `/`: `） | 生成 semantic/execution/pair/disposition/workflow state/input fingerprint | apply_group 乐观锁、task 批次重验、keep_separate 抑制、workflow checkpoint 复用判定。改动=全部未决 fusion 建议与 checkpoint 失效 |
| `review_queue.stable_fingerprint`（review_queue.py:310，compact 分隔符 `,`/`:`） | 关系组 execution_fingerprint、别名条目 execution_fingerprint、group_id、evidence 去重键 | review-batch 乐观锁；组内任一成员变化（含 review_meta/updated_at）即 stale。**与 `_hash_payload` 是同域两种序列化，未跨用**；统一须逐字节兼容证明，否则保留双实现 |
| `authority.canonical_json/canonical_digest`（拒绝 float/naive dt，sort_keys，`allow_nan=False`）+ `legacy_resource_revision_digest`（仅回放旧 PageRevision float） | Canon manifest/decision/receipt/admission input/resource revision/断言 content digest | Phase 0 全部 fail-closed 回放；legacy 变体仅为历史 replay 保留，新输入禁用 |
| `world_background._entry` source_hash（内联，compact + 固定 payload shape） | 每条背景条目来源指纹（内容含被截断前全文） | context 激活来源重验；D2a-1 修复不影响其字节 |
| `knowledge_graph_service._hash`（compact + default=str） | 节点/边 source_hash 与响应级 source_hash（manifest json.dumps(sort_keys)） | 关联图截断回执/来源对账 |

另：schemas 内所有 hash 字段统一 `^[0-9a-f]{64}$` 小写校验；`PageDraftSnapshotV1.updated_at` 进 Canon digest，工作稿任何保存都会使发布基线漂移（409）——链 3 的"工作稿漂移保留"由此实现。

### 5. 交叉引用（不重复审）

- F2-5 领域侧证据：tasks.py 使用裸字符串 `"running"`（:51,:91）而非 TaskStatus 枚举。
- F2-3/F2-4：world 融合/别名/简介任务已统一走 `modules.project.facade` 的 snapshot helper 与 `require_task_checkpoint_session` seam，未见 world 私有 LLM client 复制；`commit→expire_all` 样板在 tasks.py/world_bible_synopsis（归 F2 汇总）。
- F4-6（world_library ORM 无 FK 声明）涉及表不属本槽路径；本槽 services 均按 novel_id 显式过滤，未受影响。
- D2b：`services/common.py`（parse_uuid re-export/normalize_name/assert_edit_baseline）、repositories.py、map_* 与并发细节；D2c：world_authority_service/lifecycle/validation/suggestion_queue/generation_center/api.py 与正典可见性。
- entity_service._list_hot 对 RAG activity port 的 `except Exception` 降级为 README 声明的正式退化路径（活动索引不可用→recent_heat=0），不视为宽泛吞异常缺陷。

## 受阻

无受阻路径。声明一点阅读深度边界：48 个测试文件中，≤700 行的 22 个全文逐行阅读；>700 行的 26 个完成了导入/fixture/全局 mock 面通读 + 全部测试函数清单提取（每个测试名与位置逐一核对）+ 与本槽生产发现及历史候选相关的断言段精读（如 test_entity_fusion 全文、test_dedup_scorer 全文、test_relation_alias_review_queue schema 段、test_world 摘要段）；这些大文件未做逐行全文阅读。生产 32 文件无此保留，全部逐行通读。未运行任何测试/构建/数据库命令（按槽位禁令）。
