# D2c 槽位报告（R04 world：共创/校验/采用、正典/工作稿/资料库子域 + api/facade 公共面）

日期：2026-09-11。基线：main @ e7d0b8d5b（工作树；`git status` 确认 world 模块无 WIP）。
全部只读；未运行测试/构建/make，无网络，未读任何密钥。
47 个账本路径全部逐文件语义阅读：api.py（3871 行）、facade/worldbuilding_facade/attention_facade、
state_assembler、assistant_* 7 文件 + ports、services 22 文件（含 world_generation_center_service
4018 行、world_validation_service 2472 行、world_bible_lifecycle_service 1887 行、
adoption_package_service 1697 行等全部全文通读）、4 个测试文件全文阅读
（tests/__init__.py 为 0 字节）。无抽样。另核实横切门禁：`project/facade.require_active_project`
（owner 过滤 + FOR SHARE 行锁 + 账户 active + 缺失/回收站 404）与 `main.py` 全局
DomainError handler。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/world/AGENTS.md,已审,模块规则（先读）,无发现：与代码一致（canon 门禁/别名/CAS 描述均能对应实现）
backend/modules/world/CLAUDE.md,已审,兼容导入壳,无发现：仅导入 AGENTS.md 的兼容壳（未列入语义审查重点，确认存在且指向 AGENTS.md）
backend/modules/world/README.md,已审,模块权威文档,无发现；其中"策略不执行 regex"与 schema 的有界 regex operator 存在文档漂移，记 D2c-2
backend/modules/world/__init__.py,已审,package 标记,无发现（空/标记文件）
backend/modules/world/api.py,已审,全部 /api/world HTTP 入口,D2c-2（regex 文档漂移关联）；D2c-3（organize 死路由）；D2c-5（publication 端点私有实例化）；端点面/门禁清单见共享事实 4；A4-1 无残留
backend/modules/world/assistant_cocreation_tools.py,已审,assistant world.save_checkpoint 操作,D2c-6（经 assistant 模块跨服务） ；preview/apply 指纹重验 + pointer 锁语义正确
backend/modules/world/assistant_map_tools.py,已审,assistant map.* 4 操作,无发现：只读预览 + CAS 保存 + 原版本 review；地图领域本体归 D2b
backend/modules/world/assistant_outcome_tools.py,已审,assistant world.prepare_package/apply_page_suggestion,D2c-6（_get_pending/_lock_and_validate_page_baseline 私有访问）
backend/modules/world/assistant_page_tools.py,已审,assistant world.edit/publish/restore_page 3 操作,无发现：发布用 uuid5(run_id) 幂等 decision_id + expected_canon_head + impact hash；restore 拒绝覆盖已有工作稿
backend/modules/world/assistant_ports.py,已审,assistant 共享讨论服务的 world 校验/生成 port,D2c-6（chat_intent 深入 WorldGenerationCenterService 5 个私有成员）
backend/modules/world/assistant_review_tools.py,已审,assistant world.review + proactive 调度,D2c-6（_freeze_manifest/_active_policy_candidates/_get_model 私有访问）；advisory 回执不可作采用许可的语义正确
backend/modules/world/assistant_tools.py,已审,assistant world.add_alias/add_relation/adopt_package/create_entity/edit_entity/create_page_draft,无发现：preview/apply 全部指纹重验；create canonical 带 approved_by=owner 且走 require_operation_targets/validation 门禁
backend/modules/world/attention_facade.py,已审,root facade re-export → project"今日工作",无发现：薄委托 + 模块级单例
backend/modules/world/facade.py,已审,跨模块公共面（entity/character/event/worldbuilding re-export）,无发现：纯 re-export hub + 冻结 __all__（public-surface 测试）；X1-S3 的 world 面由 surface 测试守护
backend/modules/world/services/__init__.py,已审,core services 导出面,无发现：dedup_service 有意不重导出（注释声明）
backend/modules/world/services/attention_summary_service.py,已审,project 今日工作注意力投影,D2c-6（跨服务 import review_resolution._alias_key）；逐页拉全量评审项属有意契约（条目数计数），未见缺陷
backend/modules/world/services/common.py,已审,world 服务共享 helper,无发现：normalize_name/merge_text_field/assert_edit_baseline（UTC 归一）语义清晰
backend/modules/world/services/core/review_queue.py,已审,关系/别名类型目录 + stable_fingerprint,D2c-7（demo 语料固化同义词表，记录性）；stable_fingerprint 与 entity_fusion._hash_payload 为同域双实现（D2a 已记，勿跨用）
backend/modules/world/services/core/review_resolution.py,已审,imports 智能整理的冻结候选清单 + 守卫采用,D2c-4（candidates() 每项全项目扫描）；fingerprint/CAS/证据绑定语义完整
backend/modules/world/services/worldbuilding/activation_preview_service.py,已审,worldbuilding_facade.preview_worldbuilding_activation（context 激活预览，D6 消费）,无发现（_expand_page_links 对页面链接目标逐个查询属 N+1，规模=已确认页面×链接数，demo 级可接受，不单独立项）
backend/modules/world/services/worldbuilding/activation_target_service.py,已审,worldbuilding_facade 投影候选/来源 manifest + 测试,无发现：BFS 按深度批量读取（test_activation_target_service 断言 5 条查询/1000 实体）；256 上限与过期回退不变
backend/modules/world/services/worldbuilding/adoption_package_service.py,已审,采用包 save/preview/apply + post-import 组装 + checkpoint,无发现：双重 baseline（无锁→锁后复验）+ validation gate + provenance 追加历史（_merge_provenance）+ page claim 映射全对齐 README；私有访问属模块内组合（D2c-6 记录）
backend/modules/world/services/worldbuilding/ask_world_service.py,已审,/api/world/ask-world 只读问答,无发现：确认 allowlist 过滤 + 保守相关性门槛 + 前后 hash 复验 + 快照 fail/succeed；D2c-1 关联（未知 key 重试骨架第三份）
backend/modules/world/services/worldbuilding/cocreation_session_service.py,已审,共创会话 generation_context/enqueue_turn,无发现：状态机/指针漂移/80k 预算/历史选择校验完整（见共享事实 1）
backend/modules/world/services/worldbuilding/focused_adoption.py,已审,专项查漏授权/fence/校验/回滚,无发现：owner 复验 + lease fence + 逐字段证据 + quote 唯一 + 回滚 before/after CAS + 私有 blocker 访问（D2c-6）
backend/modules/world/services/worldbuilding/generation_prompt_template_service.py,已审,生成中心 Prompt 模板 CRUD/validate/preview,无发现：内置只读/版本 CAS/危险指令静态检查/确定性 preview 均与 README 一致
backend/modules/world/services/worldbuilding/page_template_service.py,已审,页面模板 CRUD/版本/恢复/应用到工作稿,无发现：内置 key 保留、CAS、restore 写新版本不覆盖历史
backend/modules/world/services/worldbuilding/reader_safety_service.py,已审,ReaderRevealPolicy 读者安全检查,无发现：缺失策略 fail-safe（reader_safe=False + diagnostic）、同章/scene 解锁边界明确
backend/modules/world/services/worldbuilding/suggestion_queue_service.py,已审,创设建议队列（兼容影子/确认/修订链/ask-world 保存）,无发现：_claim_pending 原子 CAS、页面/检查点/导入 target 拒绝通用 confirm、_mark_accepted 失效为 best-effort 带红act 日志；A4-5 已由 D2a 判定实现
backend/modules/world/services/worldbuilding/world_authority_service.py,已审,Canon 初始化/解析/admit/replay,无发现：authorizer 服务端注入、decision 幂等双查、head CAS rowcount、replay 迭代化 + 引用缓存；get_head 每读全链 replay 为有意 fail-closed 设计（成本观察记共享事实 5）
backend/modules/world/services/worldbuilding/world_bible_lifecycle_service.py,已审,类别/工作稿/发布影响/admit seam/revision,无发现：advisory lock 串行化 + page→draft 锁序 + O(P+E) BFS + 200 截断回执 + impact_scope_hash 全域哈希；页面 context 失效 fail-closed（与实体侧 best-effort 不同，均符合 README）
backend/modules/world/services/worldbuilding/world_bible_service.py,已审,页面查询/projection 任务编排,无发现：keyed coalescing + 失败状态写入为故障恢复路径（非吞异常）；list_pages 全量返回（项目级页面数有界）
backend/modules/world/services/worldbuilding/world_bible_synopsis_service.py,已审,世界观简介 head/revision/两阶段任务,无发现：secret-free snapshot 断言、lease-fenced checkpoint、晋升五重哈希复验、失败 fence 保护、确定性降级全部与 README 一致
backend/modules/world/services/worldbuilding/world_design_iteration.py,已审,设计检查点纯函数迭代,无发现：确定性 ID 替换/证据闭合/失效传播/深度门禁；对应测试有效
backend/modules/world/services/worldbuilding/world_generation_center_service.py,已审,生成中心 chat/converge/explore/inspection/suggestion,D2c-1（三份未知 key 重试骨架）；A4-8 复核见历史候选节；checkpoint-before-provider/freshness 复验/decision guard 语义完整
backend/modules/world/services/worldbuilding/world_library_service.py,已审,资料库统一列表/主题/收藏/最近/视图偏好,无发现：全部 novel_id 过滤 + advisory lock + 防环移动 + draft→page 引用转换去重 + 悬挂成员惰性清理；服务侧无 F4-4 关联缺陷（F4-4 仅 ORM 声明漂移）
backend/modules/world/services/worldbuilding/world_validation_engine.py,已审,纯校验规则/ReviewPacket/输出校验,无发现：结构层先于 LLM、finding_id 内容哈希、分片 quote 闭合、overall_result 门禁序确定
backend/modules/world/services/worldbuilding/world_validation_service.py,已审,校验 run 生命周期/门禁/复核/续接,D2c-8（读路径全量重冻结成本）；require_gate/stale/warn 签收/复核处置/续接语义完整（见共享事实 3）
backend/modules/world/services/worldbuilding/worldbook_import_service.py,已审,世界书目录导入 preview/apply,无发现：路径白名单/有界 YAML/三方比较/missing 不删除；policy 仅草稿态、发布才激活
backend/modules/world/services/worldbuilding/worldbuilding_service.py,已审,workspace v1 兼容 hub,无发现：纯 re-export + __all__
backend/modules/world/state_assembler.py,已审,memory 全量正史快照（ADR-0001 seam）,D2c-4 关联同文件另一处（relation Python 端过滤在 limit 之后）
backend/modules/world/tests/__init__.py,已审,package 标记,无发现（0 行）
backend/modules/world/tests/test_activation_target_service.py,已审,激活目标服务测试,无发现：SQL 计数断言（5 条查询）有效
backend/modules/world/tests/test_attention_summary_service.py,已审,注意力投影测试,无发现：计数/去重/反向组/导入分流断言有效；AsyncMock+SimpleNamespace 替身走构造注入（符合 DI 替身规则）
backend/modules/world/tests/test_review_resolution.py,已审,整理采用测试,无发现：冻结候选晋升/旧授权拒绝/漂移 fail-closed/别名回滚/legacy hash 不变 6 测试全为有效断言
backend/modules/world/tests/test_world_design_iteration.py,已审,设计迭代测试,无发现：四动作不变量/决定替换/fail-closed/深度门禁/确定性 new: ID 解析全有效
backend/modules/world/worldbuilding_facade.py,已审,世界书/激活 facade,D2c-6（inspect_world_checkpoint 访问 SuggestionQueueService._get_suggestion）；lazy import 策略与 README 一致
```

47/47 路径覆盖，无受阻。

## 发现

| ID | 位置/符号 | 问题与触发 | 调用链证据 | 现有契约 | 最小方案 | 预期收益 | 风险 | 依赖 | 验证命令/断言 | 回滚 | 裁定 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D2c-1 | `backend/modules/world/services/worldbuilding/world_generation_center_service.py:2480-2523`（`_run_semantic_inspection_pass`）、`:2557-2600`（`_run_exploration_pass`）；同骨架第三份在 `ask_world_service.py:504-539`（`_generate`） | 三个"未知 source_key/citation_key 二次修复重试"循环逐字同构：2 次尝试 → 收集未知 key（仅取键的 lambda 不同）→ 追加修复消息 → 二次失败抛 `LLMInvalidResponseError`。差异仅 schema、step_name、key 提取器与两句话术 | 生成中心 exploration/semantic-inspection 与 ask-world 三条端到端链均经此骨架；`_run_convergence_pass`(:2833) 是第四个变体（覆盖合同而非未知 key） | 无对外契约；LLM 输入流（修复话术）须逐字节保留（§6 LLM 条） | 抽一个私有 helper `_run_structured_with_known_keys(client, request, schema, *, step_name, quality_mode, keys_of, repair_note)`，三处调用方各自传 key 提取器与话术；convergence 变体不动 | 约 60 行重复合并；修复策略改动只落一处 | 低-中：属 LLM 调用路径，须保持每轮 messages 序列逐字节等价（固定样本对比） | 无 | `make test TESTS="modules/world/tests/test_world_generation_center_api.py modules/world/tests/test_guimi_ask_scope.py"` + 固定输入下两次实现 messages 快照相等断言 | git revert | 实施候选 | P3 |
| D2c-2 | `backend/modules/world/README.md`（"AI 抽取确认策略"节："策略只接受命名 operator，不执行 regex、表达式"）对照 `schemas.py:3203-3213`（operator Literal 含 `regex`/`forbid_regex`）与 `world_validation_engine.py:769-776`（`re.search(rule.value, ...)`） | 文档声明校验策略"不执行 regex"，但 schema 与引擎实际支持两个有界 regex operator（`_validate_world_policy_regex`：禁分组/或/反向引用/嵌套量词，≤500 字符）。作者按文档理解会误判策略能力；反向看也不构成漏洞（清洗器有界） | 激活校验策略的页面 `page_meta_json.validation_policy` → `WorldValidationPolicy.model_validate` → `deterministic_findings` 执行 regex 规则 | README 与 AGENTS 同句声明；代码是后加的有界实现 | 二选一：a) 修订 README/AGENTS 措辞为"仅接受有界命名 regex operator（无分组、无回溯构造）"；b) 若产品确想禁 regex 则删 operator 并迁移。按"文档对齐代码"成本最低 | 文档与行为一致，避免策略作者误配 | 无（选 a） | 无 | `make docs-check` + 目测两文件 | git revert | 实施候选（文档修正） | P3 |
| D2c-3 | `backend/modules/world/api.py:2377-2389`（`POST /bible/pages/{page_id}/organize`，硬编码 `preview_only` 空响应）+ `frontend-console/api.js:1568-1570`（`organizeBiblePage` 包装） | 后端 stub 返回固定空预览；前端仅定义包装函数，`rg "organizeBiblePage" frontend-console/` 零调用方——两端组成一对死路由/死包装 | 后端 handler 无业务委托；前端 wrapper 无仓内消费者 | 路由对外可见（OpenAPI），但无任何行为 | 按 §5 规则：仓内零引用仅构成候选。删除前端 wrapper + 后端路由（含 `make docs-check` 路由数复核），或在 api.js 标注 deprecated；实施前按计划确认无外部消费者 | 少一条僵尸端点与误导性"预览"语义 | 极低；无行为依赖 | 无 | `make docs-check`；`rg organizeBiblePage frontend-console/` 为空 | git revert 两文件 | 删除候选（待外部消费者确认） | P3 |
| D2c-4 | `backend/modules/world/state_assembler.py:118-134`（`SqlAlchemyStateSource.list_canonical_relations`）；同型问题 `services/core/review_resolution.py:40-168` + `:213`（`candidates()` 全量扫描） | a) relation 先 `limit=10_000` 再 Python 过滤 `status=="canonical"`：项目关系超 1 万且候选占比高时，正史快照静默缺行（且 limit 前无显式排序）。b) `validate_resolution_item` 对每个 item 调 `candidates(keys={key})`，而 `candidates()` 无条件加载项目全部 candidate/canonical/draft 实体（含 content_json JSONB）与全部候选关系后再按 key 过滤——O(items × 项目规模) | a) `event_facade.get_full_state` → `assemble` → memory 快照（ADR-0001）。b) imports 智能整理链：`prepare_manual_decision`/`apply`→`validate_resolution_item` 逐项调用 | a) docstring 声明"仅返回 canonical"但无上限内完整性承诺；b) 整理授权以 fingerprint 补偿正确性，只损失性能 | a) 给 repo 增加带 status 的查询（repositories.py 归 D2b）或过滤后再补页；b) `keys` 全为 `entity-`/`relation-` 前缀时在 SQL 按 id 预过滤，alias key 保持现路径 | 快照在大库下确定完整；整理批处理查询数从 O(items×全表) 降为 O(items) | 低；b 需保持 fingerprint 计算输入不变 | a) D2b repositories；b) 无 | `make test TESTS="modules/world/tests/test_state_assembler.py modules/world/tests/test_review_resolution.py"` | git revert | 实施候选 | P3 |
| D2c-5 | `backend/modules/world/api.py:1980-1991`（`get_bible_draft_publication`） | 端点内函数级 import `WorldAuthorityService` 并新建实例，而同文件 365 行已有模块级 `_world_authority_service` 单例——风格不一致，读者易误以为有意隔离 | GET /bible/drafts/{id}/publication | 无行为差异（服务无状态） | 改用 `_world_authority_service.find_page_publication(...)` | 可读性一致 | 无 | 无 | `make test TESTS="modules/world/tests/test_world_bible_v2_api.py"` | git revert | 实施候选（顺手改） | P3 |
| D2c-6 | 私有 seam 面清单：`assistant_ports.py:86-101`（`_load_source`/`_validate_explicit_context`/`_prompt_templates`/`_resolve_page_template`/`_target_brief`/`_WORLD_CORE_CHAT_BOUNDARY`）；`assistant_review_tools.py:38-50,169,274`（`_freeze_manifest`/`_active_policy_candidates`/`_get_model`）；`assistant_outcome_tools.py:106,112`（`_get_pending`/`_lock_and_validate_page_baseline`）；`worldbuilding_facade.py:29`（`_get_suggestion`）；`attention_summary_service.py:366`（`review_resolution._alias_key`）；`focused_adoption.py:629`（`_collect_blockers`）；`adoption_package_service.py` 多处 `_suggestions._*`/`_entities._*` | world 内部工具/服务大量直接访问其他服务的下划线私有成员（同模块内、多为有意组合）。三大服务（generation_center/validation/suggestion_queue）任何私有重命名都会静默破坏 assistant 工具与采用链，类型检查器不报 | 逐处读码核实（见位置列）；全部为 world→world 同模块访问，无跨模块越界 | 无正式契约；测试（如 test_assistant_*）会捕获部分破坏 | 不强改：在三大服务 docstring 增加一段"内部 seam 消费方清单"（或收集为模块 README 小节），把事实上的 seam 显性化；新代码避免再扩大 | 重构三大服务时可 grep 到全部受影响面 | 无 | 无 | 目测 + `make test TESTS="modules/world/tests"` | git revert（注释） | 记录性（seam 显性化） | P3 |
| D2c-7 | `backend/modules/world/services/core/review_queue.py:178-307`（`_CUSTOM_RELATION_KINDS`/`_ALIAS_KIND_BY_TYPE`） | 关系/别名 kind 推荐表内嵌大量 demo 语料专名（"塔罗会成员""占卜与被占卜""猜测的穿越者前辈""以命名者命名"等）。功能仅为已知详细类型→kind 的保守推荐映射，无 LLM 注入、无行为风险 | review_type_catalog()/default_relation_kind 消费；与 migration 20260822 的词表固化同源（F4 已记录该迁移词表为 demo 语料） | 推荐目录 `custom_allowed=true`，未知值不参与推导 | 保留现状（记录）；如清理须同步 0822 迁移词表语义与 `test_relation_alias_review_queue` 断言 | 去除语料痕迹（纯观感） | 清理需重验推荐回归，收益≈0 | 无 | 不适用 | 不适用 | 保留现状（记录） | P3 |
| D2c-8 | `backend/modules/world/services/worldbuilding/world_validation_service.py:1862-1872`（`_refresh_freshness`）+ `:1796-1860`（`_matches_frozen_inputs`→`_freeze_manifest`）+ `:593-624`（`list_runs` 每行 refresh） | 每次读取回执（GET/latest/list 的每行）都对 policy/manifest/dependency/target 做全量重冻结：重读全部已发布页 + 全部工作稿 + pending 包 + 全量 lookup。`list_runs(limit=10)` 最坏 10 次全量冻结；"惰性重算 freshness"是 README 声明的语义，成本随页面数线性放大 | `GET /bible/validation-runs{,/latest,/{id}}` → `_refresh_freshness`；findings/review/accept-warnings 同样先 refresh | README："按 scope/target 读取最新回执并惰性重算 freshness"——行为正确，属性能观察 | 先测量（项目页数×limit）再谈优化；可选方案为 freshness 标记列或批量复用一次冻结结果 | 收益待测 | 测量前不动 | 无 | `docs/diagnostics/performance.md` 隔离流程 | 不适用 | 补证据（收益待测） | P3 |

无 P0/P1/P2。安全、`novel_id` 隔离、数据丢失与恢复路径未发现新问题：canon admit/replay、
adoption 双重 baseline、focused fence、synopsis 两阶段 fence、共创指针 CAS、
`require_active_project` owner 门禁（全部写路径覆盖，见共享事实 4）均与生产实现一致。

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A4-8 world_generation_center 两条结构化包装疑似共享骨架 | 按字面不成立（两条包装非重复）；同文件存在真实三重骨架，已另立 D2c-1 | 字面所指的 `_run_structured_with_quality_review`(:1240-1281) 与 `_run_structured_with_decision_guard`(:1283-1341) 不等价：后者在阈值内增加确定性 `_decision_state_violations`（:1411-1434）+ LLM 边界审计（:1343-1396）+ 一次重生成，二者是"单步"与"守卫包装"关系，合并会造出 §5 P3 明令禁止的多开关框架。真实的重复是三份逐字同构的"未知 key 修复重试"循环（exploration :2557 / semantic inspection :2480 / ask_world `_generate` :504），加 convergence 覆盖变体（:2833）构成第四态——已按此形态记 D2c-1。旧收益估计不继承 |
| A4-1 world 局部 DomainError handler（"world 10 处确认冗余先删"） | 已解决（维持 D2b/F1 结论）；api.py 无残留 | `rg "except DomainError" backend/modules/world/` 为空；api.py 仅在 `_WorldApiRoute.get_route_handler`(:316-329) 把 canon 三个 body 路径的 `RequestValidationError` **raise** 为带 code 的 `DomainError`（322），由 `backend/app/main.py:559` 的全局 `@app.exception_handler(DomainError)` 唯一处理——无本地 try/except 残留 |
| A4-4 world 资产双词汇（领域侧） | 领域侧已收敛（功能变更/无需批次）；前端渐进归 D8c | 双词汇（原始 `status` vs 作者 `display_state`）的领域侧映射已收敛到 `modules/world/asset_state.py` 单点：world_library `_state_case`(:73-78)/`statuses_for_display_state`、api.py 的 4 处 `display_state` 查询参数（兼容保留）、attention/实体列表均消费该 helper；本槽 22 个 service 未发现新增散落 status→display 映射。剩余兼容面是 wire 层双参数（README 声明的契约），无需领域侧动作 |
| audit 其余落本槽项 | 分流/无新增 | X1-S3 facade 死导出（world 面）：root `facade.py` 69 个 `__all__` 符号全部自子 facade 导入且有 public-surface 冻结测试（facade 注释 :93-94 明示新增需删测）；机制侧 F1/D1 已核，本槽未见零引用死导出。A4-2/A4-5 已由 D2a 复核。A3-3 world 部分已由 D2a 裁定不参与 |

## 共享事实（供 W3 链 3"世界工作稿→校验/复核→显式采用/发布→revision/影响失效→历史读取"及后续槽位引用）

### 1. 共创会话状态机（ADR-0021/0023；表 `world_cocreation_sessions/messages`，ORM 归 assistant/D7）

- 会话状态：`active | archived`（`AssistantSession.status`）。创建经 `POST /cocreation-sessions`（require_active_project + `require_source` 校验 source_kind∈{project, world_bible_page, core_entity, world_library_topic}）。
- 回合上下文（`WorldCocreationSessionService.generation_context`，cocreation_session_service.py:19-160）：会话必须 active；`workflow_preset`/`target.kind`/`source_page_id` 与请求一致；非 project 来源复验存在性；**checkpoint 指针**：`session.current_checkpoint_id == data.expected_checkpoint_id`，漂移 → 409 `checkpoint_pointer_drift`（提案保留）；checkpoint 行必须是 `world_design_checkpoint|world_core_checkpoint` 的 CreationSuggestion；80,000 字符硬预算（超限 ValidationError，不裁历史）。
- 推进指针：`advance_checkpoint`（assistant 服务，D7 拥有）在会话行锁内刷新后比较 `expected_checkpoint_id`；DB 错误不得伪装为"会话不存在"（模块 README 声明）。
- 任务回合：`POST /cocreation-turns/task` → `enqueue_turn`（operation 幂等 + `require_fresh_confirmation("world.generation.chat")` + 预演 generation_context + llm_execution_snapshot 入 meta）；worker `world_cocreation_turn`（D2a 表）：终态幂等（已有 `_cocreation_turn_response` 直接返回）、行锁内复验 status/指针。
- 成果推导（`assistant_ports.outcome_states`）：suggestion `rejected→rejected`；`accepted + result_ref.type==world_bible_page_draft→saved_draft`；其余 accepted→adopted；pending→pending_review。
- 原同步聊天 `POST /cocreation-sessions/{id}/chat` 仅兼容；`project_assistant_enabled()` 时 chat 路由切换到 assistant `submit_cocreation` 且免 confirmation（api.py:550-556,929-930）。

### 2. 显式采用/发布门禁点清单（写正史的唯一入口集合）

- **建议队列采用**（suggestion_queue_service）：`confirm/edit-confirm/merge/resolve-as-alias` 经 `_claim_pending` 原子 CAS（`UPDATE ... WHERE status='pending' → 'processing'`，单胜者）；`confirm` 拒绝 page_draft/checkpoint/worldbook_import target；启用 validation policy 后先 `require_legacy_canon_write_allowed`（否则 409 `required_validation`）。compatibility shadow 只能经队列裁决（拒绝/合并/别名 → shadow `ignored/merged`），不能直改。
- **整页建议**：唯一入口 `POST /generation-center/suggestions/{id}/apply-page-draft` → 只写服务器工作稿（replace_existing 经 `_lock_and_validate_page_baseline` 四重基线：page_version/draft_id/draft_updated_at/content_hash），不发布。
- **采用包**（adoption_package_service.apply）：pending 复验 → focused 授权时 `fence`（exclusive 项目锁 + authorization fingerprint + task lease + `validate_items` 漂移即 409）→ 无锁 baseline → canon head 预锁（含页面项时）→ 页面 universe 锁 + FOR UPDATE baseline → **preview_hash 两次比对**（锁前后）→ `require_gate` → 逐项 apply（provenance 以 `world_adoptions` 列表追加历史，不覆盖旧来源）→ open 项另存 pending 复核包。API 层再包 `begin_nested` + exclusive 锁（api.py:2470-2486）。
- **Canon 发布**：唯一正式页写入路径 `_seal_draft_for_admission`（Authority 独占内部 seam）→ `WorldAuthorityService.admit`（authorizer 只能是服务端 `current_account_id()`/`context.owner_id`，AI/请求体不可授权；decision 幂等双查；head CAS rowcount）。API 入口：`POST /bible/drafts/{id}/publish`（expected_canon_head+canon_decision_id 成对或同缺）、legacy `POST/PATCH /bible/pages`（canonical 语义自动转 draft→admit；archived-only 仅改 workflow head 不动历史 revision）、包页面项、`activate_builtin_policy`、assistant publish（uuid5 幂等 decision）。
- **专项查漏/整理 v2 包**（focused_adoption）：`fence` = exclusive 锁 + authorization（policy/owner/fingerprint 三验 + executor_grants 只增不改）+ `require_running_task_attempt`；每 item 强制原文 quote 唯一命中 + 身份术语证据 + fill_empty 仅空字段（None/空白为空，0/false 非空）；回滚逐项 before/after CAS，新对象软废弃受关系/档案/页面引用 blocker 阻止。
- **失效链**：页面发布/归档 → `_record_adopted_page_change`（不可变 PageRevision + `_mark_page_projections_stale` + context 失效 **fail-closed**（失败→ConflictError，本次保存不落库）+ synopsis stale）；工作稿改动/丢弃/模板 → draft context 失效（同样 fail-closed）；实体/关系/采用/检查点 → `mark_asset_context_changed` **best-effort**（红act 日志，主写入有效）+ `request_entity_activity_reannotation` + `mark_synopsis_source_changed`。两档严格度的分野是页面（正史手册层）vs 实体（结构层），与 README 一致。
- **历史保留**：PageRevision/CanonRevision/TemplateRevision/Assertion 不可变（DB trigger，F4）；恢复页面/模板/简介一律"写新版本或新工作稿"；工作稿 discard 是唯一删除（非已采用资产，API 需 `confirmed=true`）。

### 3. 校验引擎输入/输出语义（world_validation_engine + service）

- 输入冻结：`_freeze_manifest` 产出 `{scope, items[], lookup[], world_state_checkpoint}`；full scope = 全部已发布页 + full-scope 工作稿（rule/schema/terminology/world_core 或带 validation_policy 或带 refs）+ pending 采用包；dependency_hash = 排序后的 linked_asset_refs 投影；语义层再经 `_freeze_semantic_scope` 只保留 confirmed Context 实际选中内容（excluded 不可回流），omissions 显式记录。
- 结构层先于 LLM：`deterministic_findings`（标题重复/wikilink 悬挂/frontmatter schema/依赖图环/待裁定页 AUTHOR-REQUIRED/策略规则/policy 多源/world_state 引擎检查），finding_id = 内容 sha256 前 24 位。
- 语义层：packet 按 `packet_character_limit` 切片，`input_hash=stable_hash(packet)` 支持断点续跑与批预算切片；`validate_semantic_output` 强制每个 question 恰好一次、quote 必须在冻结分片内、pass 必须带本分片证据（违者 ValidationError fail-closed）。
- 裁定序（`overall_result`）：`insufficient-evidence(block)` > `author-required(block)` > `fail(block)` > `mixed(warn)` > `pass(pass)`。
- 门禁（`require_gate`）：policy 未激活直接放行（旧行为）；advisory run 永不可作门禁；full-scope target 必须命中 full run manifest；error 且非 AUTHOR-REQUIRED 硬阻断；`author-required` block 只能靠逐 finding review items 清除（deferred 不计入 reviewed）；`warn` 需 receipt_hash 绑定的整单签收或逐条 warning review。
- stale：policy/manifest/dependency/target 任一哈希漂移 → `stale/block`（读路径惰性重算，成本观察 D2c-8）；失败回执同样先重验冻结输入；续接必须携带原 `context_confirmation_id`。

### 4. api.py 端点面与门禁清单（~103 路由）

- 门禁三态：a) **query novel_id** → `ActiveNovelIdQuery` 依赖 = `require_active_project`（owner 过滤 + FOR SHARE + 账户 active；缺失/回收站统一 404）——绝大多数 GET/PUT/PATCH/DELETE；b) **body novel_id** → handler 内显式 `require_active_project`（generation-center/ask-world/cocreation/checkpoints/adoption save/library 写等 POST 族）；c) **exclusive 锁** `require_active_project_exclusive`：canon admit/revert、`POST /bible/pages`（canonical 适配）、`PATCH /bible/pages`（需 admission 时）、draft publish、validation-policy activate/draft、validation create/continue/review-items、adoption apply。
- 豁免（无项目语义，符合模块 README）：`GET /bible/templates`（内置目录）、`GET /review-type-catalog`、`POST /generation-prompt-templates/validate`（novel_id 可空）。
- 错误语义：ConflictError→409（部分端点显式转换；`required_validation` 保留原 ConflictError 以便前端识别 next_action）；`SuggestionAlreadyProcessedError`→409 `{status:"already_processed"}`；TemplateVersionConflict→409 `template_version_conflict`；canon 三个 body 路径的 422 统一转 DomainError code（canon_reference_invalid/unsupported_statement_kind/invalid_statement_value）；`_test/text-archive` 种子端点仅在 `app_env=="test"` 可达否则 404。
- 死路由：`POST /bible/pages/{page_id}/organize`（D2c-3）。
- 主要端点组：canon 5（head/revisions/admissions preview+admit/revert）；generation-center 8（chat/convergence/exploration/semantic-inspection/suggestions deprecated/suggestions task/apply-page-draft + cocreation-turns/task）；cocreation-sessions 7；ask-world 3；prompt templates 9；profiles 4；bible pages/categories/drafts/publish-impact/synopsis 20；page-templates 6；library 14；validation 12；impact 3；checkpoints 3；adoption-packages 4；suggestions 决策 8；conflicts 2；knowledge-tags 3；entities 15（含 image 2、promote、merge、resolve-as-alias、revisions、rollback×2）；alias-relations extract 1；events 5；relations 7（含 review-groups/review-batch/review-edit）；entity-batches 1；aliases 7（含 review-groups/review-batch）；characters/knowledge 8；`_test` seed 1。

### 5. 其他横切观察（不构成发现）

- `WorldAuthorityService.get_head/get_revision/preview` 每次读取都做全链 `_validate_manifest_replay`（迭代化 + 引用缓存）：长历史项目上每次发布预览/读取为 O(链长×资源)。这是有意的 fail-closed tamper 检测（测试含"长历史 replay 无递归"），不改；性能如需优化须另立破坏性方案。
- world_generation_center 全部 LLM 路径共享：provider 前 `_checkpoint_before_provider`（commit + 断言无事务）、返回后 `_revalidate_source`（行锁重读来源 + 全量 freshness 证据比对，漂移 409 丢弃）、1800s 端到端预算；`_finish_context_snapshot` 失败双段降级且只记红act 日志。
- 本槽新增 `stable_hash` 同构实现 2 处（focused_adoption.py:33、world_validation_engine.py:154，均 `sort_keys+compact separators`）——F1-3 census 由 17 增至 19 处记录（同序列化域，合并仍需逐字节兼容证明）。
- `ponytail:` 注释 3 处（world_design_iteration.py:181、world_library_service.py:1229、ask_world_service.py:415、worldbook_import_service.py:135）均为有意"规模阈值"标记，语义清楚，不动。

## 受阻

无。47/47 路径完成；生产文件全部逐行通读，4 个测试文件全文阅读；未运行任何测试/构建/数据库命令。
