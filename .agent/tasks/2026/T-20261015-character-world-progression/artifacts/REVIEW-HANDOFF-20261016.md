# 地图增强剩余问题 Handoff

记录时间：2026-10-16T15:04:24+08:00。用户本轮要求仅为“剩余问题写 handoff”。

## 接手状态与范围

- 平台目标仍为 `paused`（本轮 `get_goal` 已核实）；本轮只整理文档，不恢复实现或真实评测。三个 TASK 的 `active` 表示工作尚开放，不代表平台目标已恢复。
- 后续实现仍按用户最后裁定由主会话完成，不开、恢复或消息子代理。本文件不是新增执行、付费调用、提交或发布授权。
- 唯一主工作树：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan`，分支 `codex/map-enhancement-plan`；原 Desktop 路径已失效。不要在主仓库或其他 worktree 覆盖 WIP。
- 本轮写文档前 HEAD：`dd9946dd0caf5d842d4421d7949e7f14a3a6b44a`，工作树干净。该提交只记暂停；最新业务代码提交为 `70e305540db5626aba92d24673f09328ae88cc8f`，第一批为 `5ce9b693ade489161dcf2c51ce66abaf008ff86f`。
- 外部报告：`/Users/tywww/项目/ai-writing-assist/out/map-enhancement-review-20261016.md`；原审查基线 `81785cd16d1310f747e7790832567a593d6a9952`。报告行号是历史定位，动手前回查当前调用链。
- 当前累计 **30 项已修并验证、L25 一项复核不成立、17 项待处理（5 medium、12 low）**。U1–U3 已被原报告自身复核推翻，不当作待修缺陷。下文 M/L 编号均为报告 ID，不能与地图计划的 M0–M5 里程碑混淆。
- M4 只完成只读调查，没有已开始而未保存的实现，也没有已选定的最终桥接设计。

恢复先读当前指令、根 `AGENTS.md`、[主 TASK](../TASK.md)、[修复账本](REVIEW-REMEDIATION-20261016.md)，再核 Git 与目标状态。完整原范围见[实施对账](FULL-SCOPE-ACCEPTANCE.md)和[质量检查点](C5-C0-C3-A1-CHECKPOINT.md)。代码路径均相对上述工作树。

## 建议批次与验收原则

恢复后先做 **M4 + L4**，再做 **M6**，避免交换格式提前固化错误桥接语义；**M7 + L8** 单独验证时序与锁；**M9 + L27 + L28** 一起核目标生命周期；**L3/L10/L12** 按所属领域独立修；**L1/L20/L21/L22/L23** 集中处理作者展示与行为测试；**M16** 最后迁移编排，保留前面已验证的事务行为。

每批复现当前问题后再修根因；完成相关单测、必要 HTTP/PG 与文档门禁后更新账本。最后再对最终业务固定点跑受影响的完整回归。历史测试通过不代替后续新代码验证，也不代替真实用户验收。

## 待修 medium：5 项

### M4：六种 strong Profile 与 Dossier 双向收敛

- 入口：`backend/modules/world/dossier_service.py::_sync_legacy_storage`（当前约 2104 行）；`services/worldbuilding/profile_service.py::_upsert_strong`；`services/entity_profile_registry.py`。冻结映射在 `backend/alembic/versions/20261015_object_dossier_v2.py` 约 310–385 行。
- 问题：species/faction/location/rule/item/secret 的迁移条目带表前缀 `legacy_field_key`，当前档案写入只同步 Character/CoreEntity，旧 strong Profile 写入又只落旧表；两套当前值会分叉，影响旧 GET/list/WorldBackground 消费者。
- 下一步：先完整追踪六类旧写入、读取与档案编辑/恢复路径，选定单一当前值的桥接方案；复用冻结映射，保持历史、CAS、来源和事务原子性。不能为打通桥接开放任意跨类型 `legacy_field_key`，也不能在普通读取时偷偷写修订。
- 稳定映射线索：species 的 origin/physiology/lifespan/abilities/weaknesses/culture/language；faction 的 ideology/leader/member_rules/territory/resources；location 的 map_refs/climate/population/resources/hazards；rule 的 domain/principle/constraints/exceptions/consequences；item 的 class/powers/limitations/origin；secret 的 truth/risk/linked_targets。精确字段与 facet 以迁移为准。
- 必守：不把 `controlling_faction_ids_json`、`owner_entity_ids_json`、`holder_entity_ids_json`、`reveal_status` 等动态事实回填稳定层；不猜 ID、不把未知内容公开、不因编辑一条档案自动采用整份 draft Profile。
- 类型陷阱：`_display_value` 把 JSON 转成可读文本，不能把编辑后的 prose 直接赋给 JSON 列或凭名称还原 ID。部分 String 长度 128，`secret.risk_level` 长度 32 且非空，多数 list JSON 非空；清空须保持合法类型。旧 strong upsert 跳过显式 None，Generic 允许显式清空，不能无审计地统一语义。保留原结构化值、状态及 visibility 的方案尚待确定。
- 验收：六类型参数化覆盖旧→新、新→旧、无变化不建修订、编辑/恢复/清空、标量/JSON/ID、draft/canonical、秘密过滤、失败回滚与跨项目隔离；真实 PG 验证 varchar/JSON/非空约束。入口测试：`backend/modules/world/tests/test_object_dossier.py`、`test_worldbuilding_workspace.py`、`backend/tests/e2e/test_world_dossier_postgres.py`。

### M6：manifest 交换保留桥接与未映射数据

- 入口：`backend/modules/world/schemas/dossier_manifest.py::DossierManifestEntry`、`dossier_interchange.py` 的 export/apply；`dossier_service.py` 的 `read()` 与 `legacy_profile_fields`。
- 问题：manifest 不携带 `legacy_field_key` 和必要桥接 metadata；`legacy_unmapped` 被移出 entries 后不导出，导回后旧 Character/Generic 兼容读取失真。
- 下一步：M4 语义落定后定义受控交换字段，保留必要 legacy key、Generic key、原始类型值和未知字段，重映射目标模板/facet/Scene 与证据，不直接透传所有 metadata。`legacy_unmapped` 是内部秘密载体，不能绕过常规写入校验或导入成公开事实。
- 验收：同项目/跨项目 round trip，Character 字段、Generic 已知/未知 JSON、数组/null/秘密均保真；owner/novel/CAS、幂等重复导入与整体回滚不退化。主要测试：`backend/tests/e2e/test_dossier_template_interchange_postgres.py` 及所属 World 单测。

### M7：章节重排后 MemoryEvent 查询与重放仍用旧章号

- 入口：`backend/modules/story/continuity/chapter_order.py::_invalidate_derived`（约 1167 行）；`services.py::get_panorama/list_events/_apply_events_in_range/capture_snapshot`；`repositories.py` 的章节区间/count/max/keyset 查询。已有正确映射参照 `fact_timeline.py::_current_chapter_index`（约 350 行）。
- 问题：重排只把 snapshot/checkpoint 标 stale，区间读取仍使用原 `chapter_index`，可能混入未来事件、漏掉已移到前面的事件，随后生成错误的 current 快照。
- 下一步：统一按 receipt 的 apply/restore 转换链与 `event.created_at` 投影当前章序，使列表、计数、分页、回放和快照一致。先审计全部仓储调用方，再选实现；共享查询投影仅是候选方案，尚未实现。
- 必守：原事件与来源锚不可直接重写，否则 fact timeline 会二次映射；重排间新增事件只消费之后的转换。覆盖多次重排/恢复和无 Scene 的权威事件，避免修改已加载 ORM 对象污染后续会话；锁与快照发布必须一致。
- 验收：双章交换后截止点正确，无漏/重/未来混入；count/keyset 与列表一致，多次 apply/restore、间隔新增事件及 snapshot replay 正确；PG 并发重排/重放。可从 `backend/tests/e2e/test_chapter_order_concurrency_postgres.py` 与 continuity 单测扩展。

### M9：outcome_unknown 缺作者核对、解除与重规划入口

- 入口：`backend/modules/assistant/goal_runs/service.py::_record_step_failure/replan/advance/resume`、`goal_runs/api.py`、相关 schema、`frontend-console/api/assistant.js` 及目标面板。
- 问题：未知结果进入 `waiting_approval/outcome_unknown` 后所有继续路径拒绝，唯一退出是取消；活跃唯一索引使同项目新目标也被阻塞。
- 下一步：提供作者可见的实际领域回执/结果核对与显式决定入口。依据可验证结果安全收敛步骤，再允许原授权和剩余预算内的重规划或合法结束；未查明时继续阻断。
- 必守：不能自动重试未知写入、重放信封、把未知 usage 当零或返还预算；保留原任务/step/call/receipt 来源，校验 owner、novel、CAS、幂等与竞态。单纯添加“忽略错误继续”不满足修复。
- 验收：已应用/确定未应用/仍未知三类，重复核对不重复写、预算不重置，外部项目/过期版本拒绝，活跃唯一约束只在合法终态解除；HTTP + PG。现有测试：`modules/assistant/tests/test_goal_runs.py`、`tests/e2e/test_goal_run_http_postgres.py`、`test_goal_run_restore_postgres.py`（均在 backend 下）。

### M16：app/main 内约 600 行留痕业务应归属 Assistant

- 入口：`backend/app/main.py::_install_operation_trace_route_adapters`（约 884–1417 行），包含撤销 SQL/LIKE 回执匹配、call 指纹、终态事件、响应头和幂等重放判断；另有两处安装调用。
- 下一步：把实际业务编排迁到 Assistant 所属模块，组合根只保留组合/注册；不是增加一个仍调用 app 内业务的空包装。遵守模块 facade/contracts/DI 边界。
- 必守：保持 FastAPI APIRoute 的真实 dispatch、owner/active 前置门禁、同引擎最终事务、成功留痕与业务原子提交、savepoint/rollback、不重复终态和缺失响应头标记语义。现有测试有 app.main monkeypatch，迁移正确 seam 或保留确有必要的兼容导出。
- 验收：`backend/tests/e2e/test_operation_trace_postgres.py`、`test_operation_trace_report_postgres.py`，实际 HTTP 注册/重放、最终 commit 失败、多阶段未知结果、秘密不进 trace，并跑模块依赖门禁。

## 待处理 low：12 项

| ID | 当前入口与问题 | 下一步与验收 |
|---|---|---|
| L1 | `frontend-console/vue/components/CreativeExperiments.vue:43` 确认文案直接展示 `task_root_capability_id`，如 `collaboration.run`。 | 解析作者可读能力名称，缺失时用友好名称而非 slug；保留实际授权/预算参数，组件验证确认文案。 |
| L3 | `backend/modules/world/services/core/entity_relation_service.py` 的 update/review_edit 缺“只有 canonical 关系可声明有效期”校验；status-only 降级还会保留原有效期。 | 按最终 status 与最终 interval 校验，不只检查本次 fields_set；明确显式清空行为。测 candidate 拒绝、canonical 通过、降级保留区间拒绝或按明确契约清空、review 确认路径及锚点/隔离。 |
| L4 | `backend/modules/world/services/core/character_service.py::ensure_for_core_entity` 的 auto_materialized 刷新可能传 `secret=None`；Repository 现支持显式 None 清空，可能误擦作者秘密且绕过 Dossier 修订。 | 保留作者显式清空能力，区分未提供 scaffold 值与主动清除；配合 M4 审计调用方并走正确同步路径。测原有作者秘密、缺省/显式 null、新旧读取与修订一致。 |
| L8 | `backend/modules/story/character_arcs/service.py::_lock_character_plan`（约 155 行）无方言判断直接调用 PG advisory lock，SQLite 实际写路径无法覆盖。 | 参照 `continuity/chapter_order.py` 的方言守卫，在支持的 SQLite 单测路径覆盖真实 save/restore/archive/unarchive；保留 PG 生产锁和首次创建并发保证，重跑 `tests/e2e/test_character_arc_plan_persistence.py`。 |
| L10 | `backend/modules/evolution/spatial_rescan.py::handle_spatial_rescan`（约 582 行）在 try 外访问缺失 run、用无 default 的 next 查 operation，裸崩且不进入核对流程。 | 显式处理 run/entry 缺失，异常分支也不能再引用不存在对象；真实缺失与未知 attempt 状态如实记录。测缺 run/operation、未知 attempt、取消任务和终态 metadata，均不得触发补发模型请求。 |
| L12 | `backend/modules/evolution/store.py` 约 535–542 行吞 `STORY_QUEUE_WORLD_PROGRESSION_READ_CHECK` 的 DI KeyError，可能成功写回执却无推进读核对。 | 依赖缺失显式失败并保持事务一致，单测按契约注入明确 no-op；验证缺 port 回滚、成功 receipt/outbox 同事务、回滚无 outbox。不要运行通用 outbox worker 来验证。 |
| L20 | `frontend-console/vue/views/writing/components/ObjectDossierPanel.vue` 的 shortId/validityLabel 把 UUID 前 8 位当对象/Scene 名。 | 解析对象、Scene、章节名称；缺失用“未命名对象/原边界待核对”等文案，保留内部导航 ID 与 stale 提示。扩展 `frontend-console/tests/vue/writing/ObjectDossierPanel.test.js`。 |
| L21 | `frontend-console/vue/views/map/mapStructureEditor.js:35–36` 候选变更明细展示完整 term/revision/Scene UUID。 | 显示词条与范围名称，缺失时用准确友好说明；保留提交的固定修订身份。测作者确认明细不含裸 ID、采用参数和范围不变。 |
| L22 | `frontend-console/vue/views/world/components/WorldAliasesTab.vue` 与 `views/world/library/WorldEntityRevisionHistory.vue` 的有效期显示截断 UUID。 | 复用或补足真实名称解析与缺失/stale 文案；`WorldObjectDossierEditor` 的 fallback 也须核实，不能直接复制 UUID fallback。测试位于 `frontend-console/tests/vue/world/` 下两组件同名文件。 |
| L23 | `frontend-console/tests/vue/writing/UnifiedNoticesPanel.test.js` 缺旧 sceneAlerts 迁移后的 stale 展示直接断言。 | 在真实挂载中断言 `item.stale` 显示“依据已变化”，连同对应定位/可用动作验证；不能用搜源码字符串替代行为测试。 |
| L27 | `backend/modules/assistant/tests/test_goal_runs.py` 缺 `auto_r2=True` 下 R3/R4 及非白名单 R2 必须人工审批的直接测试；当前 `_step_is_manual` 行为正确。 | 加真实步骤推进测试：停在 `phase=step_review`、`stop_code=step_approval`，无 apply/task/model 副作用；不为通过测试放宽风险门禁。 |
| L28 | `backend/modules/assistant/goal_runs/service.py::R2_RESTORE_OPERATIONS` 只有 `world.dossier.entry.edit` 和 `project.update_task` 两项，比 ADR-0038 §6 的 R2 自动执行范围窄。 | 审计目录中实际可恢复的 R2，逐项实现具体一键恢复 manifest/操作及 CAS 后再纳入自动授权，或继续明确记录未满足范围。不能只放宽 allowlist 或改 ADR 冒称完成；任务仅允许指定字段，恢复保留原 receipt/op/call、历史、预算与知识边界。结合 M9、L27 和 PG restore 套件验收。 |

## 已完成证据：不要重复修或误用

- 第一批 `5ce9b693a`：28 项修复。完整后端 **9044 passed / 2 skipped / 8 deselected**，随后新增入口负例后的 **195 定向通过**；前端 **257 文件 / 3217 项通过**，lint/build 通过，随后导演尾例 **12 项通过**；保留工程 PG **6 文件 / 24 项通过**。完整后端有 1 项既有 Pydantic warning，没有隐藏 RuntimeWarning。
- 第二批 `70e305540`：M2/L2 的有界读取、相关修订 SQL 筛选与单次校验局部缓存；**63 定向、1975 World+evals / 2 skipped / 1 deselected、2 新 PG** 通过，含 1 项既有 Pydantic warning。Ruff、改动文件 format、docs-check、repo-gates 通过；本批没有重跑完整后端/前端。
- 当前 Map pipeline：`df32dbcf8c4779cbe03b1ebbfc71b5bc7e477bed355f6a47a65030f31a4c05ea`。不能把它改绑到封存的旧真实评测。
- L25 不成立：独立导演 Start/Continue 的 rounds 允许多轮，worker 逐轮持久化并共用根预算；`DirectorAdvanceRequest.rounds=Literal[1]` 只是单轮快捷操作，不应为此放宽授权。
- 第一批日志前缀 `/tmp/map-external-review-batch1-`（日期后缀 `20261016.log`），关键文件有 `final-backend`、`final-focused`、`pg`、`final-frontend-full-tests/lint/build`、`director-tail`、`repo-gates`。第二批前缀 `/tmp/map-external-review-batch2-`，有 `focused`、`world-evals`、`pg`、`docs`、`repo-gates`、`committed-gates`。文件可能随临时目录清理失效，账本与提交仍是恢复依据。

## 验证环境与运行边界

- 从主工作树运行，Python 使用 `backend/.venv/bin/python`（3.14.8），不要用主仓库另一套 3.14.7 环境；Ruff 同一 `.venv`。前端 Node 路径 `/Users/tywww/.nvm/versions/node/v24.15.0/bin`，npm 11.12.1；恢复时核实存在，不重装依赖。
- backend 单测命令（backend cwd，可按批次追加文件范围）：

  ```bash
  DATABASE_URL=postgresql+asyncpg://unit@127.0.0.1:1/operation_trace_unit_test RUN_E2E_TESTS=0 .venv/bin/python -m pytest -m 'not e2e and not real_llm and not external_data' -q -W error::RuntimeWarning
  ```

- 保留工程 PG：`127.0.0.1:65202`，数据库 `operation_trace_report_primary_test_20261016`，现有 schema 头 `20261016_chapter_order`。凭证只读自 `/tmp/map-enhancement-test-20261015.env`（0600）；不输出连接串、不提交 env。读取该文件后核其原 URL 的 host=127.0.0.1、port=65202、database=map_enhancement_test，用 SQLAlchemy URL `.set(database=...)` 仅替换为上述保留测试库，再向子进程设置 `DATABASE_URL`/`E2E_DATABASE_URL`、`RUN_E2E_TESTS=1`，执行对应 `pytest -m e2e`。严禁误用真实评测库。
- 不 CREATE/DROP/重建数据库，不自动升级迁移，不清其他 worktree/stash/WIP、不安装或 sync 依赖、不删除共享 BOOTSTRAP 账户。PG 测试用随机自有账户/项目，只清自身数据；需要新 schema 时先核实适用范围与授权。
- 文档收尾：根目录 `make docs-check BASE_REF=origin/main`、`git diff --check`；业务变更另跑模块/import/适用 repo 门禁。全仓 format 有既有漂移，不为本任务批量格式化。
- 不 push、创建 PR、合并 main、发布或部署。本轮 handoff 文档仅保存到本地，未自动提交。

## 真实评测封存与整体未完成条件

- 三份计划全部实施仍是原目标：`docs/plans/2026-10-15-map-system-enhancement.md`、`2026-10-15-agent-operation-surface.md`、`2026-10-15-world-object-dossier-and-scene-director.md`，加 C0 映射与 ADR-0035–0041。修完 17 项不代表原计划全部验收。
- C1 依赖 P4 真实长篇，M5/势力扩展、RP 独立评测与 A4 数周真实使用数据/真实 Top3 仍未满足；完整真实矩阵和作者验收未通过。`human_validated=false`，holdout 未解码，导演等默认能力门禁保持关闭；工程测试不能作为开启依据。
- 用户确认的地图验收口径：明确记录“模拟作者显式指定 Scene 地点”，然后对比地图辅助写作；自动冷启动不会自动提供该身份。既有 R6 没有达成这一写作对比，不可改写其结论。
- R3/R4/R5、导演 R1/R2、地图 R6 均已封存，不恢复、不改绑、不重试、不覆盖原回执。本轮及剩余工程修复均不触发新付费调用。恢复真实评测需另按当时目标状态、已获范围和成本门禁核实。
- R6 私有根 `/Users/tywww/.codex/private/map-spatial-evaluation-20261016-r6`，原 pipeline `a3ad2b84a661fa02a61bde9ad3b427afb903b06bb3a486d589f46655b326ce2a`；30 任务 done/attempt1，161 业务调用/2517759 tokens/unknown0，另 5 个 Sol seed usage/费用未知。五族写作 eligibility 均 `not_run`、development gate `blocked/passed=false`；无 Scene PATCH、Writing/Assistant/judge 调用。后续托盘拒绝路径修复未重跑 R6。详见[去原文 R6 结果](../../T-20261015-map-enhancement-design/artifacts/evaluation/R6-COLDSTART-RESULTS.md)。
- 评测 PG `65302`、`/tmp/map-spatial-eval-runtime-20261015/app.env`、`map_spatial_eval_20261015` 不是工程测试资源，不访问或修改。原 17 个发布/RAG outbox 保持 pending/attempt0/no envelope，禁止排通用队列、预热 embedding、取消或执行。旧 `/tmp/map-r6-*` finalize/seal 脚本已经执行，不能重跑；私有原文、提示、gold、回执不进 Git。
- 导演 R2 私有根 `/Users/tywww/.codex/private/authoring-quality-pilot-20261016-r2`：12 次 foundation Luna / 191022 tokens / unknown0，但角色 facts 仍为 0，无导演/世界推进 SUT 或 judge；不得伪造知识或将自由卡片提升为 POV 事实。

## 可执行的恢复第一步

用户恢复目标后，先核 `get_goal`、当前分支/HEAD/脏文件和本文件，随后只读对照 M4 的六类 registry、冻结迁移、旧 Profile 与档案调用链，写下类型/清空/状态/秘密的实际收敛策略，再以可复现的双向失配用例开始 M4 + L4。不要从历史任务段落的“下一步”启动旧评测或子代理。

## 本轮交接验证

`make docs-check BASE_REF=origin/main`、`git diff --check` 通过；另核对 17 个问题 ID 无缺漏、本文本地链接与明确仓库路径均存在、新文件无行末空白。日志为 `/tmp/map-review-handoff-docs-20261016.log`。本轮只改交接与任务文档，没有重跑业务测试；上方业务测试数字均是所列历史固定点证据。
