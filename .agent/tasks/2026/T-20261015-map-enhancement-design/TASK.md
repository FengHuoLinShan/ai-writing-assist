---
id: T-20261015-map-enhancement-design
title: 地图系统增强设计与分批实施（自动冷启动、参与创作决策、题材鲁棒性）
status: active
created: 2026-10-15T10:54:00+08:00
updated: 2026-10-16T01:17:50+08:00
---

# 地图系统增强设计

## 恢复快照

- 当前授权：2026-10-15 用户 `/goal` 要求执行 `codex/map-enhancement-plan` 的计划；Luna/max 子代理并行实现，Sol/high 按批次 review 与修复。只做本地开发验证；没有发布、真实数据破坏或对外发送授权。用户16:43补充“修复由sol子代理直接修”：后续代码修复均由Sol/high子代理直接执行。用户曾要求“由你收尾”；其后明确答复范围为三份计划全部实施，包括操作目录、对象档案、导演、世界推进。root继续负责分批拆解、集成、验证、任务记录与实际隔离评测；已明确确认采用“模拟作者显式指定Scene地点后做辅助Writing对比”。
- 主工作区：`/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan`，分支 `codex/map-enhancement-plan`。原 Desktop 路径已失效；仓库实际已迁至 `/Users/tywww/项目/ai-writing-assist`。
- 恢复时基线：设计提交 `3fd5ca29e`；刚 fetch 的 `origin/main=00d861283` 已无冲突合并为 `b74d7c28d`（本地），包含 G8c 与第三批评测/HTTPX2 变更。开始时主工作区干净，其他 worktree/WIP 保留。
- 当前里程碑：primary b3182b2c5 已集成 C4a 共用simulation_v3及Sol身份/观察边界修复（50c0feb54、b4cd55c78、b3182b2c5），均无冲突；root扩大Story+Interaction+助手目录/路由验证1034 passed/2 deselected/1既有Pydantic warning（28.70s）、1专用PG、23Vue/ESLint/build通过，RuntimeWarning转error无失败。C3b/C2b前批86后端/3PG/3134前端与C0b3030证据保留。连续轮次409仍仅C4a过渡，C4b/C5未实施；C2/Generic由Luna dossier_consumers继续，ReactionV2与修订桥接已写但未固定点验收。A1 Luna首批15插件335349f08（307测试）已交Sol在map-clue-review组合审修/接线，尚未集成。新Luna goal_runs在map-assistant-review/codex/assistant-goal-run-impl从1656353fe实施A2独立目标引擎/前端，暂不并行写Sol的既有Assistant核心。C0c、A1剩余、A3/A4及外部真实/势力/RP门禁保留，全部TASK仍active。
- 下一步：收Sol A1组合审修与Luna C2/Generic固定点；Goal独立模块同步推进，A1核心接线结束后再开放其共享写入。C2可审后启动C4b导演及C0c有效期等剩余切片，随后C5/A3/A4。R3封存、holdout不读。
- 范围：用户已明确“该分支三份计划全部实施，包括操作目录、对象档案、导演和世界推进”。执行地图M0–M5及两个配套完整计划；既有计划的条件依赖和真实质量门禁仍有效，不能冒称完成。
- 依赖：M5 依赖独立势力路线图阶段 1，现有计划明确阶段 1 前不提供领地图层；不得读取旧无时效势力字段冒充完成。
- 已落地共享前置：`6fcce3bfd` 把7种ObservationModality上移shared并保持Evolution兼容再出口（16测）；`16f64570a` 在既有Story scene-source port提供按当前顺序的锚点/替换链只读数据（5测）。两者ruff通过，后续纳入Sol审查。
- 验证环境：主树独立backend/.venv（Python3.14.8、locked ci）及frontend node_modules；本任务专用PostgreSQL容器 `map-enhancement-test-20261015`、loopback65202、数据库 `map_enhancement_test`，基线完整Alembic升级已通过，未接触真实库。
- 验证：实现前 `make docs-check` 已通过（152 ORM表、49ADR）；没有真实模型/真实稿件验证。
- 最后核实：2026-10-16T01:17:50+08:00

## 批次与分工

1. M0/参考维度基础：空间schema/hash/锚点；词表storage/service/API/presets；Evidence参考维度。三棵独立树，并行实现后Sol/high分项review+修复。
2. M1：Evolution统一可选阅读步骤与discover_details行为不变迁移；空间抽取/独立复核；World线索候选存储与审核。
3. M2：按批增量草图/分片/托盘/补扫/来源核对；候选绑定降级与显式采用；审核界面和助手操作。
4. M3–M4：World只读空间简报、Evidence loader与各能力默认关闭开关、snapshot记录；确定性提醒、查询和修复预览；五题材离线评测骨架与真实对比验收单列。
5. M5：势力阶段1是外部前置，未落地时不提供领地图层。

## 第一批实施与审查检查点

- 词表：Luna原d43bce757→ae91bd434，Sol原141a098cc→3d3035025；共享PG复核原4fb9f1d78→d8c0a64ed。绑定生成run/完整词义/traits/证据；修复多跳合并、空键、别名上限和归档/合并确认。历史不可改删，项目cascade按父项目真实消失判定，防嵌套trigger和TEMP同名表绕过。
- 空间v2：Luna原bb928c2ee→4f78511c9；Sol原1c1e9a14f→370c0e0ac。修复局部路线丢失、停用/孤立类型进入计算、读者journey过滤、连续性端点/途经点可信度和区间、跨空间锚点与替换链部分缺失、读时陈旧诊断。主树空间+词表+Story锚点255测通过。型别traits尚非M4完整计算。
- Evidence：Luna原680fb3218→d24cbaaa0，Sol原1a7b6b438→59e30ca92。参考维度不能降级剧透/越范围知识，不能掩盖必查未验证；参考来源未查/缺失/重复单独省略，隐藏key与reason脱敏。116/339相关回归、26 prompt contracts通过；尚无空间brief loader和能力开关。
- 主装配：1b17bed2d词表迁移/API；529f3ed4c地图level类型成对列+same-term/project/revision FK；e5d3341f1空间抽取/复核能力与prompt binding；899c8ca00 clue metadata/contracts/migration。PG head为20261015_map_draft_superseded，升级与ORM parity通过；4项词表PG测试通过。新clue表已随M1服务Sol复核，见第二轮检查点。
- M1 registry：Luna原32da4ea18→c2b3bae48，纯SPEC并保持discover_details旧行为，30测通过；完整spatial步骤仍在独立树实施。
- 项目词表UI：49392cc38，按项目懒加载，5预设可混搭、编辑/合并/拆分/归档/恢复与CAS冲突反馈，表单未保存和异步离开保护。77单测/eslint通过；真实API浏览器390px和桌面2用例通过并看图，production build通过；尚待Sol/high独立review。
- 评测骨架f1c8bfccf：5题材、开发/留出10独立资料族槽位，全not_materialized/not_run，不含原文/期望/评分；不能作为默认开关启用依据。
- 架构门：module-import-gate 12模块/61依赖棘轮通过；docs inventory 155表/49ADR通过。BASE_REF影响检查已按真实改动逐项核对，脚本支持--no-change-reason说明未变的治理/总览/模块图；后续改动随实际重核。
- 当前并行树：map-evolution-spatial（原luna_plan_discovery，M1主链；已取World Sol bec204c809→43aa89d38）、map-auto-drafts（原luna_plan_advisory，新树aab2924e6，M2 backend）、map-spatial-brief（luna_spatial_brief，fa057ed31，M3 World/Evidence/Assistant v5）。均Luna/max。原树map-clues-drafts、map-assistant-operations保留；已完Sol树map-assistant-vocab-review/map-clue-review保留，不清理WIP。
- 第二轮助手/UI Sol原12e728bfc→8f27d3596：修复不同词条不能同批确认、整确认累计20实际项、重叠目标、NOWAIT与savepoint冲突、旧map.create schema在prepare/confirm/team恢复全链冻结、v4词表只读入口、split确认、延迟响应/重挂丢地图草稿。183后端扩大+后续14目标、146前端、PG5通过。主树49装配/工具回归通过；2项真实浏览器（390px含split确认/桌面）通过11.3s并看图，细微移动间距改进1fbc7879a尚待最终视觉复核。
- 第二轮World Sol bec204c809→aab2924e6：修canonical/working锚点混用、段落回读扩展导致精确Scene误拒/Scene外引文、未来类型证据、失败review仍创建emerging、作者类型降级/墓碑遗漏、GET status query、端点状态冲突/词表种类、合并签名、NOWAIT并发升级、越界Story/Account import。92目标与PG3通过；Story validate_source_ranges新可选content_mode=None保留旧行为，World显式传实际mode，经现有SceneSourcePort。root最终门禁517/517与26prompt contracts通过。
- quota原9cb8a2465→d94907aae：空间授权版本化独立details/spatial额度与主阅读剩余预留、旧路径不升级，preview计量入指纹；全Evolution离线547pass/1deselected。完整抽取/World stage/rescan尚未交付，quota将随完整M1再Sol复审。ReadingFlow e671de1e9/5bacd6b32：新阅读默认显式spatial，续读冻结，改选项失效旧预览，费用+独立额度+四态覆盖，21测。
- root补M2存储aff2403e1：superseded CHECK/migration，保留被取代候选历史；旧PG scope-budget测试改检查拒绝降级保持原head，2目标PG通过/ORM parity通过。PG critical首轮103pass/1旧硬编码版本失败，修后两项定向通过，尚未重跑整critical。
- root前端f1e08410d/b2770eb8c/abb072374：本地排演不推断未核对类型/区间/模态或跨空间路径，删图元清相关journey；空间/行程/类型修订/模态/区间逐项差异；画布分空间，读者图片加space_id且不露私有空间名。85后端+reader新1、134前端通过，尚待Sol批次review与带地图浏览器覆盖。ad2297d98补助手层级类型预览精确固定name/description/revision/status，23测。
- 集成曾出现root错误：解冲突正则DOTALL把bootstrap/service_keys尾部截断，未推送；发现后从8f27父版本逐项恢复fa057ed31，检查合并净差仅新词表DI 8行，完整49装配测试与后续module-import-gate通过。后续冲突不用该正则，逐块确认完整diff/stat。

- 未跑真实模型、真实稿件、作者验收，未推送/建PR/合并main/部署。宿主总并发4，仅3子代理能同时活动，多轮实现/审查保持用户指定模型。

## 本次实施验收补充

- M0–M4 依计划和 ADR-0035/0036/0037、0038 §10 逐项对账，助手与界面同步；不可用依赖或真实质量验收必须明确保留，不能以离线测试冒称完成。
- 空间草图只作候选、不自动采用、不自动生成图片；参考维度省略不影响必查完整性，提醒不阻断；各创作能力开关默认关闭，真实对比评测通过前不启用。
- 所有实现独立工作树和分支，主代理顺序集成；schema/migration/共享合同单一写入者。主 TASK.md 仅主代理写入，子代理不改开放索引。
- 受影响测试、lint、必要 PostgreSQL/浏览器、prompt contracts 与收尾 `make docs-check BASE_REF=origin/main`、`git diff --check`；工程绿色与模型/作者验收分别报告。
- 代码级 review 使用用户指定 Sol/high；业务真实请求须遵守 owner 已验证 Codex Luna/max 与 Project facade/snapshot 门禁，教师/评分守卫不因本任务绕过。

## 目标与验收

- 目标：让地图冷启动变短，并让地图参与写作等模块的决策；模型要能兼容大量题材和风格，
  并为未列举的情况预留用户自定义和模型涌现。
- 验收：设计稿和 ADR 覆盖用户裁定，与现有 ADR（0005、0012、0017、0025、0026、0031）
  的关系写明（对 ADR-0005 的偏离只限空间类型）；`make docs-check BASE_REF=origin/main` 通过。

## 用户裁定（2026-10-15）

- 两个痛点：冷启动太长；地图对写作和其他模块帮助有限。
- 保持示意与提醒级，不做强制约束；空间数据作者不填时只从原文抽取并审核。
- 冷启动自动进行；草图允许绑定候选地点；允许写 ADR 等文档。
- 势力路线图先单独推进，后续合入地图；领地要多形态（海上按船），势力可多层嵌套；
  船可以是势力单元，小船也可以只是物品，要能灵活转换。
- 未列举的情况预留用户自定义；首批验收题材：修仙、西幻、都市、科幻、悬疑。
- 第二轮：深度导入即将被世界演化替代并下线；允许模型在演化中总结常用类型，按项目维护。
- 第三轮：同步增强助手，帮助作者使用地图修改、势力控制等功能（不限于这两项）。
- 技术评审后：参考维度省略只提醒不阻断；草图尽量在原有版本上做增量候选、必要时才重做；
  为演化可选步骤建立统一契约；其余评审项按推荐处理。

## 关键决定与理由

- 本次实施前置已落地：`85cf1eea1` 冻结v1几何约束白名单（新golden/calibration 3测，集成map结构/选择共56测通过）；`a5e52f17c` 将现有地图助手操作转为纯SPEC由组合根物化（4测通过），为配套操作扩展准备；`cfaa6df52` 同步锚点/几何兼容权威说明。尚未经过Sol/high批次审查，不代表M0完成。

- 小型封闭的计算特性内核加开放的项目类型（ADR-0035）：程序只读特性，类型由作者自定义或模型涌现；
  特性在作者采用引用该类型的地图版本后才参与提醒；归档类型保留墓碑，模型不得重建。
- 层级保留 `level` 列与 CHECK 作系统粗层，新增可选 `level_type_ref`，深度由父链推导。
- 可信度复用 `ObservationModality` 7 种值：只有 `event_observed` 参与计算；`author_plan` 只进作者视图，
  `unclear` 进待核对。v1 已采用约束视为作者确认、全书有效。
- 几何指纹：现有 `geometry_hash` 对约束用排除名单，新增字段会改指纹；落地前先冻结为 v1 字段白名单。
- 冷启动改为演化阅读的 `discover_spatial` 步骤（ADR-0036）：API 默认关、新界面显式开启；层级来源冲突按
  已采用 World 关系 > 已采用地图父子 > 复核线索 > 候选 World 关系取舍；扩展 G8a 地图册消费端口；
  演化成为默认导入入口前保留手动生成回退。
- `map_spatial` 作为参考维度（ADR-0037）；地图变化沿用 G8b 读时比对，正文变化沿用 G8a；
  Scene 无位置身份时不猜；v1 地图即可做最小切片；`check_knowledge_visibility()` 将是首个生产接入。
- G8c（第三批）是正典修订基线（main #248 已落地），与地图无关；地图设计只依赖已实现的 G8a、G8b。
- 现有 `territory_refs_json`、`controlling_faction_ids_json` 保留原样，迁移由势力路线图阶段 1 决定。
- 技术评审核实：任何 `omitted` 都使 `scope_complete` 为假（`evidence/compilation/knowledge/scope.py:459`），
  所以参考维度省略须单独记录，否则照样阻断（ADR-0037 §1）。
- 演化可选步骤契约（ADR-0036 §1）：`discover_details` 为第一个实例、空间发现与对象档案发现按此登记；
  并行生成、顺序写入、只与严格更早的提议去重（`evolution/discovery.py:1810`）；项目数据指纹只进
  `consumer_read_set`，方法指纹只含方法本身，避免续读时方法版本对不上。
- 草图增量（ADR-0036 §7）：`map_atlas_revisions` 只追加、整份文档、`uq_map_revision_task_node`；
  因此每节点至多一条待审 `auto_draft` 候选，以待审候选或已保存版本为基础增量，旧候选标 `superseded`，
  按批次合并生成，五种情形才整片重做。
- 锚点规则（ADR-0035 §2）：Scene 会重排（`scene_order` 锁）和被融合替换（`replaced_by_scene_ids`），
  所以锚点按当前顺序解析、不存序号；档案与势力账本共用。

## 交付

- `docs/plans/2026-10-15-map-system-enhancement.md`（设计稿）
- `docs/adr/0035-genre-neutral-spatial-model-and-custom-vocabulary.md`
- `docs/adr/0036-evolution-optional-reading-steps-and-spatial-discovery.md`（技术评审后由
  `0036-evolution-spatial-discovery-map-cold-start.md` 改名）
- `docs/adr/0037-map-spatial-advisory-dimension.md`
- 助手地图与势力操作：`docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md` §10
- `docs/adr/README.md` 与 `docs/README.md` 索引

## 验证

- 2026-10-15 第一至三轮：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 均通过。
- 2026-10-15 评审核对与合并后（未提交）：origin/main 已前进到 `00d861283`（含 G8c #248，未占用
  0035–0041 编号）；`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）；
  `git diff --cached --check` 通过。
- 2026-10-15 写入用户裁定与第四阶段承接说明后：上述两项检查再次通过。
- 2026-10-15 技术评审修订后（未提交）：`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）、
  `git diff --cached --check` 通过；旧 0036 文件名只在本记录的改名说明中保留；跨 ADR 章节引用逐一核对有效。

## 风险与待决

- 若其他分支先合入同号 ADR，需要顺延编号并同步索引与引用。
- 空间发现改动演化链路，需要与世界演化第四阶段实施、#209 容量优化等任务划分写入者。
- 移动可行性检查的完整版依赖故事内时间能力（势力路线图、世界演化后续阶段）。

## 2026-10-15 16:08 集成检查点

- M2合同/ORM df16a1e9e 与主装配334ace27b：map_auto_draft_batches持久化cursor，PG head 20261015_map_auto_drafts，专用PG升级/ORM parity以及4项storage/并发测试通过；PG目前交World M2代理做服务测试。M2服务仍实现中，WORLD_BUILD_MAP_AUTO_DRAFTS尚未注册组合根，不能宣称实际闭环。
- M1完整Evolution 8a2aec71d→8ecaafeda已集成（13文件3109行）。最终安全修正27定向通过；此前全Evolution563pass/1deselected。新树map-evolution-review的Sol/high sol_review_evolution_spatial独立审查和修复中，含G8a候选地图消费接线；已发现optional异常隔离、builder running恢复/缺DI silent None问题，正在修。World同run working context f074ca22d加严格更早+当前源/quote/hash回读，default/crossrun保持canonical；59 World/容器/注册表回归通过。
- M3 World首片acda90caa→a8305aa66，主装配e7a8d6f13；World空间brief真实源/Scene/可见性检查已入主树。Evidence/各调用方/Assistant v5仍由Luna空间brief代理实现；默认关闭。当前主树function import gate 523>517，代理已在后续代码修回517待集成；不得抬baseline。
- root UI：fecffd517线索复核（确认/拒绝/合并+CAS/异步隔离/编辑互斥），ec26a4584空间补扫授权与恢复（沿用操作编号，不绕未知费用）；100项相关前端回归通过。MapSpatialMetadataPanel新增独立空间/类型固定修订/模态/Scene锚点和有限分页，126项回归通过但尚未commit/真浏览器/Sol。覆盖UI正在适配ADR四态，details旧投影不变。
- root实际工具失误：World首片cherry时在同一主树并行跑了Python测试，测试读取未解冲突文件导致SyntaxError；已手动有界解import冲突，之后59测试通过。后续不在依赖文件变更期间启动/保持测试进程。
- 下一步：R3已实际启动，private-root=/Users/tywww/.codex/private/map-spatial-evaluation-20261015-r3，code ba20/pipeline f69a01881711c288c0d8c38c819a7862bf39724d2a5ec7127d479d6c735e1627，Project f7ea5188-d1ba-42c6-9d55-aad470610ce6，run reading-895bdc74-1515-47c8-ab30-cba6bbb7e31b / operation895bdc74-1515-47c8-ab30-cba6bbb7e31b。新Sol-xhigh seed实际4/4及raw/hash守卫通过；真实预览M21/Q10，rootcap51/headroom20已原指纹启动（不topup）。首task14736d15-f942-4769-a9b7-e42cf4222cce，第一批exact max_tasks2 session80380正在运行，先poll完成及只读monitor再决定后两批2/2。脚本/tmp/map-spatial-eval-runtime-20261015/run_phase_r3.py与monitor_r3_evolution.py，必须source同目录app.env而不打印；每phase日志唯一不可盲重发unknown。之后正常review→显式作者UUID→final binding→5双臂/Assistant/judge。所有子代理已收尾，无待集成代码，任何修复仍Sol直接写。M5前置缺，holdout禁解码。

## 2026-10-15 16:29 集成检查点

- M2 World原f35e9988→38daae399（9文件3785行）及bf820675b组合根已集成；持久化分片/前缀/托盘manualpoint preview+fingerprint确认/候选审核canonical gate；41装配/契约回归通过。Sol/high map-auto-draft-review独立树正在修复游标UUID类型错误未挡来源失效、图元/约束/行程丢effective、作者标签被entity.name覆盖、working/candidate身份降级绕canonical、净化前候选错误标saved可历史恢复等；95目标与PG6通过，待commit。按ADR严格把revision.base指真实增量候选，另显式review_base_revision_id冻结正式headCAS；root同步UI，null不回退。新列表返回有类型node（候选不进正式Atlas）、offset/limit分页+准确total_count，truncated与batches_truncated分开。
- M1 Sol原c5d21c9e4/19a28cc99→6c2722138/3b520fc4b：修可选步骤异常隔离/savepoint、未知补扫历史保留、方法冻结、旧Scene额度不能抵新Scene保留、running builder可续跑、缺DI显式缺口、G8a按来源模式区分与完整覆盖。全Evolution585passed/1deselected，Ruff/格式/diff通过；未跑真实模型。
- M3原4a39dd752→fdd685112完整33文件集成，仅docs15有界手工合并，保留M2+新M3。Sol/high map-spatial-brief-review发现semantic_review/targeted_revision仍consumer_action=writing.generate，正在修复确认复用与独立开关；另核隐藏标题/缺引文/引用排除/v5默认off/地图receipt与required facts隔离。Luna定向66通过，root尚未做最终组合回归。
- M4 Luna/max新树map-spatial-advisories在fdd685112实现确定性提醒+Writing/forecast地理视角，World ask_world_service由M3 Sol唯一写入，Luna新helper/typedport交root接线。后续Sol复核、M2助手结构操作/map_cold_start仍待开始。
- root UI已166686eef元数据编辑（空间/固定类型/模态/Scene锚点）、fb910810d真浏览器1pass10.2s并看桌面/390px截图，无横向溢出，API保存精确值；150相关前端通过。新的MapAutoDraftPanel/候选真实node上下文/lineageCAS/分页/托盘选点与确认在主树未提交，单测新增有1个上下文关闭失败，142其余通过，eslint通过。尚未独立Sol前端复核。
- 专用PG65202已由M2 Sol释放；当前head20261015_map_auto_drafts。所有真实项目DB/模型/稿件未触碰，未push/PR/main合并/部署。宿主3子代理同时活动：Sol M2、Sol M3、Luna M4。

## 2026-10-15 16:45 检查点与用户修正

- 用户最新“修复由sol子代理直接修”，已向两个Luna明确：只交新功能实现与必要自测；review/既有bug交Sol直接改。root后续不写修复代码，当前UI由新Sol接手。主树91f0ae79a除本TASK外干净，未push。
- M2 Sol原786614e18→535085aee已集成，95领域/PG6通过。M3 Sol原f62659dcd→6f402d1b6已集成，修7能力真实consumer开关、core剩余预算、指纹不受地图省略污染、隐藏标题/类型/缺引文/排除引用、Assistant v5默认关闭和advisory receipt。末次764pass/1仅M1策略清单，root补齐details/spatial 4能力并10pass；26prompt contracts通过。当前root扩大Evidence/Assistant/Worldbrief/ask API回归在跑。
- 91f0ae79a root UI已提交16文件566+/28-，195前端回归+eslint通过；专用PG真浏览器1pass15.0s（实际流程7.4s）完成托盘键盘选点→预览指纹确认→新草图→真实provisional节点比较→单项采用→正式目录出现，390px无横向溢出。已查看placement/adopted截图。浏览器中发现并修的root遗留都在用户16:43修正前：同级Panel重复key重挂、忙碌状态watch漏loading/saving、前后空白MapDocument v1/v2不一致、null/JSON字段序伪变更、review_preview回显lineage而非正式headCAS。末项新服务回归1pass，剩E501交Sol直接处理。
- 当前Sol/high sol_review_map_interface树map-interface-review基于91f0ae79a，审M0-M2新增UI、clue/rescan/multispace/metadata与真实API边界。已发现并在直接修：旧200批外候选托盘按钮缺batchStatus、失败翻页错offset；允许窄扩MapAutoDraftListItem.batch_status，不猜completed。PG/browser65202/65211/65212空闲交其使用。
- Luna助手树map-assistant-structure：新增MapAuthorDecision窄来源，Journey sources=[]要求quoted source或显式作者决定，不扩MapSource；assistant marker需provider按真实project/run/USER message hash验证。ee3e3f51f仅新增ASSISTANT_READ_MAP_AUTHOR_DECISION key（未ALL/装配），provider/typedport尚未交主树。Assistant operations.py由Luna唯一写prepared_preview基线，M3 Sol已结束。后续v6新目录、作者安排、批审、Evolution R4授权预览与map_cold_start仍实施中。
- Luna M4树map-spatial-advisories：新World contracts.WorldReadMapSpatialAdvisoriesPort(db,MapSpatialAdvisoryRequest)->Response、facade read_map_spatial_advisories；主键建议WORLD_READ_MAP_SPATIAL_ADVISORIES。默认复用MAP_SPATIAL_ENABLED_CAPABILITIES新增writing.conflict_check.spatial_advisory，core config不共享写。根DI/Ask接线由后续Sol完成，Luna不再改root代码；新功能5单测通过，已毁/未生效地点/同时两处与import ratchet仍自测实施中，未交SHA。
- 所有真实模型/稿件/业务DB和五题材paired eval未跑，flags保持关闭；M5外部势力阶段1仍前置。未push/PR/main合并/部署。

## 2026-10-15 17:18 组合验证检查点

- 主树08bc1ad0e，全前端243文件/3093测试通过（30.89秒）。六域World/Writing/Story/Assistant/Evolution/Evidence+container/registry/prompt为3101通过、4失败、2deselected（126.87秒）：作者消息reader缺组合根装配、无引文错误文案regex旧预期、missing-builder测试FakeDb缺savepoint能力、操作注册快照缺v6新增项，均交Sol助手唯一writer直接修。缺reader属于尚未集成的后续装配，不能把组合回归先报绿。
- module-import门新失败：Assistant来源provider直接import World合同产生assistant→world新边（62/61，双向10/9，顶层双向1/0）。交Sol用消息身份窄结果在World边界校验，不抬基线或以函数import掩盖。Ruff仅auto-draft测试I001，format另2文件由Sol处理；文件大小107生产文件无warning、binary增量0、release-evidence通过。
- 根审额外边界交Sol：手动MapAuthorDecision按schema没有hash，M4 sources=[]时仅检查hash会丢手动作者声明；需保留手动来源与assistant核验来源等权、同时严守模态/已保存/canonical/可见性。
- docs影响门剩8份待核：assistant20确有v6/cold_start/新工具影响由Sol更新；其余CLAUDE/development-guide/architecture README与治理/模块图drawio+html/Memory仅在实际核对确定职责、导航和冻结依赖方向不变后给具体no-change reason，不为了过检改治理文件。
- 评测当前新Luna/max独立树map-spatial-evaluation补5开发+5独立单次留出私有资料与实际产品配对流程。require_live_eval_calibration仍默认拒绝，现有AskWorld/G7窄scope不能借用；地图独立评分角色待后续Sol审查实现，真实请求尚未发出。

## 2026-10-15 17:29 稳定批与真实HTTP验证

- 助手Sol0b60a9ea4→33ad05c95已无冲突集成32文件：作者来源provider改Assistant拥有的窄dict，World边界转MapAuthorDecision并按owner/run/message/hash重验；修依赖方向新增边与4项组合回归。root重跑六域组合3111passed/2deselected（115.12秒），架构全部棘轮及166文件Ruff/format通过。
- 文档inventory156表/61handler/16route/49ADR通过；BASE_REF影响检查用脚本受支持的--no-change-reason逐项说明七份全局治理/总览/Memory无当前架构变更，未抬棘轮或改治理规则。普通make docs-check亦通过。没有声称裸make docs-check BASE_REF在无说明时通过。
- UI Sol真实HTTP冷启动1pass13.2秒（实际5.7秒）：真实capabilities、flows latest/start、基于saved正文+Scene准备冻结预览、ReadingFlow原arguments/fingerprint提交Evolution start201（仅排队不启worker）、bind重验、monitor pending与refresh200；只对模型effective/snapshot配置做synthetic-no-network替身，并硬禁OpenAIProvider.generate，未mock flow/Evolution路由。已清理本批合成项目、停止服务。另mock契约浏览器验证丢响应/unknown交互，二者证据分开。
- 最新fetch origin/main仍00d861283，M5势力stage1未落地，任务原文仍要求另启阶段1；不以旧territory/controlling字段冒充。模型质量、五题材teacher/paired评分、真实稿件与作者验收均未做，默认cap flags继续关闭。

## 2026-10-15 17:45 地点确认与范围边界集成

- 1a5b7c27d→7ff8f1a5a：原World promote增加可选expected_source_hash，在行锁且populate_existing后核对；旧调用向后兼容，原owner/prefix/policy门禁保留。候选地点只列有界20项及can_adopt/block_reason/hash，正常采用/409/cross-project真实HTTP已验证。root全World/Assistant+容器/注册表1603passed/1deselected（45.09秒），架构棘轮全部通过。
- b79b12878→3b6a9c262：真实Evidence.confirm_context→World→Assistant整链验证读取/静默只限原确认map(node,revision)；新确认排除、optional-stale省略和无可核版本不再读回旧地图，返回unknown并拒旧fingerprint；compiler source.id归一为node_id。Sol全Assistant+map snapshot+auto-draft199passed。
- 096b92223→1f0c11d6a：冷启动界面实际授权冻结与恢复，World地点原promote(CAS)确认成功后重新map preview，再独立确认地图；默认不勾选，部分成功保留，409重预览。Sol236定向前端/ESLint/Ruff/build/docs/file-size通过；4browser全通过32.8秒，分开覆盖mock回执/丢响应、真实HTTP只排Evolution201不启worker、真实CAS200与真实CAS409；390px六截图已查看。独立临时服务/MinIO/合成项目已清理。
- 评测Luna已准备五题材开发/独立留出10族50原创案例，原文与gold只在0700私有目录，文件0600，matrix仅hash；状态not_run/human_validated=false。Sol发现pair冻结Settings直接赋值、真实Scene只存正文引用被误拒、holdout占用非原子等实质缺陷，正在独占eval写区直接修；新teacher scope不得借用AskWorld/G7或绕过默认暂停。没有DB/模型请求。
- §9最后对账发现主动提醒与助手托盘入口尚缺，已由Sol分别直接补；node merge原领域无执行原语，目前只有诚实的候选预览，后续需受控实现及独立审查。M5仍受另启势力stage1外部前置。

## 2026-10-15 17:55 剩余工程与评测准备

- root集成后全前端245files/3108passed（30.36秒），production build通过；新确认范围+Assistant+auto-draft+DI/registry223passed（12.26秒）。docs inventory、119生产文件大小门与0二进制增量通过。一次snapshot测试路径拼错导致未收集，改正确test_map_spatial_snapshot.py后完整223通过，不是测试失败修代码。
- root抽看096真实地点确认成功与stale409的390px截图：布局无横向溢出，地点采用与地图按钮分开、409保留候选并提示重新预览。UI Sol仍在补有界map.prepare_tray_placement→实际工作台深链/作者选点，无自由point；助手Sol真实build/type/save产品事件触发的持续授权合并提醒已有目标回归，待最终提交。
- 节点合并尚未实施，新隔离树`.worktrees/map-node-merge`/codex/map-node-merge基于1f0c11d6a已创建，无agent写入；桌面managed create_worktree因Git ref lookup failed不可用，改用实际仓库git worktree add，未触碰其他WIP。待空槽Luna/max实现，之后Sol/high审修；当前现有candidate不等于合并执行。
- 新评测专用空PG `map-spatial-eval-20261015`、loopback65302、数据库`map_spatial_eval_20261015`已完成Alembic升级至20261015_map_auto_drafts。受限运行环境在`/tmp/map-spatial-eval-runtime-20261015/app.env`（0600，目录0700），不入Git，不输出凭据。未配置账户连接或创建评测项目、未验证连接/请求模型、未接触真实作品DB。
- eval Sol修真实Scene来源/冻结Settings/原子占用与窄scope中。根审发现原草稿假设所有task.meta都有scene_id、result有eval_observations，实际Assistant仅run_id、Evolution范围任务无该统一字段；已交Sol删假设，不向正式任务塞伪造评测字段。本批只保留真实pair+seeded teacher执行能力、未适配三组硬拒完整judge/gate；下一波Luna补真实facade driver与证据适配，再Sol审修。所有评测仍not_run/human_validated=false。

## 2026-10-15 18:09 新能力与评测稳定批

- 776817cda→a719d23bd：map.prepare_tray_placement冻结≤20 item/候选/原节点/正式head/指纹，schema无坐标；真实成果helper→深链→工作台作者选点→原HTTP preview/place。Sol92后端/224前端、390px真实PG浏览器1pass15.1秒；root集成后220后端、169前端通过。旧入口不静默换目标，两个真实409后保留点位重预览，地图仍候选。URL只IDs/hash，无原文。domain prepare由受限fixture调用，非真实LLM助手整轮。
- 4ea7300ff→6767c7089、280942b54→c0ba97226：eval稳定批修冻结Settings/真实Scene引用、case原子防重与重复kwargs TypeError，新增Map-only Sol/xhigh seeded scope/原始IO ledger。root44定向通过、eval-fast344passed2skipped（4.17秒），没有远程请求。完整judge/dev gate/holdout因三组适配未完成而硬拒；Writing先有adopted map的binding只用于pair，下一Luna须拆共同source/Scene基线先校准再真实coldstart，不能把手工map当coldstart产物。
- f13b0410d→8372dfe16：持续授权内默认关map notice，真实batch/type/save/Scene事件，按授权代次/日期合并≤20来源信号；24h/源/排除/owner重验、0模型/0任务/0自动采用。root审发现active后新类型被隐去、map_changes查看来源无handler，均由Sol直接修并补服务真链/ProactiveCare→helper→router回归。Sol1601后端pass1deselected（最后小修前）、最终81受影响+20通知/proactive、18UI通过；PG65202并发3通过，统一project→watch锁序且finally清理。共享3文件/doc/helper均自动无冲突cherry，root无手工代码修复。
- 新Luna节点合并采用有界纯空间兄弟节点：无源子节点、图片/标注/托盘/地点绑定/待审revision，稳定重映射独立空间内部ID保留坐标；真实源merged_into墓碑/目标新revision，双head CAS与可撤回。当前实施中，未宣称完成。其PG65202为工程专用；eval空库65302仍未配owner连接/业务项目，两个库不能混用。
- eval Luna需要三类纯读facade，Sol final已接：World精确run/Scene artifacts、Evolution真实run/range/Scene receipt、Assistant由meta.run_id回读固定confirmation/context/tool与answer。禁止通吃不存在的task.meta.scene_id或eval_observations，GET get_run会reconcile不可用作评分纯读。Luna可继续driver，Sol独占生产窄read helpers；不增加DI/module边、不返回secret/token。

## 2026-10-15 18:22 纯读回执与组合修复

- 7e7a614cd→e1a11c591：World按run/Scene读实际线索、草图、地图head与类型谱系；Evolution按真实授权range/attempt读receipt，主阅读attempt到operation绑定无持久化证据时明示unknown；Assistant纯读实际answer/actions/action batch/evidence refs，原系统未保留的tool invocation明示unknown，不借GET get_run的reconcile。无新DI/module边、无secret/token输出；root4新测试通过。
- 0cc30f00b→83923aa0f：Sol实际红测复现后直接修候选revision排除未挡pending+tray、类型current revision排除未挡新类型notice；新修订仍独立触发。另修候选地点勾选后结束引导selected残留导致dirty一直true，子组件卸载清空状态。Sol23后端/145前端与lint/docs/import gates通过；root主树19后端/25前端通过。
- 后续node墓碑需覆盖不止主读API：cold-start adopted计数/saved revision、notification batch refs/map变更、新eval World heads/status lineage；Luna已收到并会交接给后续Sol。当前Sol final继续M0–M4整体规格组合审查，node/eval仍两Luna唯一writer，root不写修复代码。

## 2026-10-15 18:27 新调度规格缺口

- Sol整体review确认 `_finish_scene_results` await details和spatial后，主Scene applier/receipt才提交，虽failure隔离但不满足ADR36§1“主理解回执不等待任何可选步骤”。root按文字语义要求根修，不改文档弱化；Sol final先交brief来源/精确revision排除修复，再独占Evolution pipeline/tasks/optional registry/持久journal相关写区直接修。
- 修复边界：主理解身份/World候选先可靠提交；可选产出须持久阶段关联原Scene receipt，保留旧冻结运行兼容、原root/子额度、unknown不重发和严格更早Scene写入。禁止fire-and-forget、修改immutable主回执、另起预算。需要新任务/schema时由Sol先给最小方案；eval Luna已知不能假设主reading任务done即全部optional产物齐，后续精确drive已授权步骤，不能drain队列。当前尚未修完，不宣称M1全部达标。
- Luna node工程PG实证：head20261015_map_node_merge，same-novel FK与self CHECK存在并拒错；双提交仅1成功，undo追加saved新版本，合成账号/项目已清理；PG65202释放待Sol node复核。既定61/9/0/517门禁通过。节点feature尚未提交/独立Sol复核。

## 2026-10-15 18:31 节点合并审查准备与复制缺陷

- Sol6393ddb8b→83bb15f04修brief移动对象provenance排除、精确地图/类型修订排除，原9测含真实Evidence excluded_refs→World loader组合回归；root World brief/Evidence loader/snapshot36passed。一次root测试路径写错未收集，改用实际compilation/tests路径后通过，未改生产代码。
- 已复用本任务已完成且clean的旧map-auto-draft-review树，新建branch codex/map-node-merge-review，base83bb15f04；保留原codex/map-auto-draft-review和旧提交。app list_artifacts仍空，managed路径失效，无归档/重置任何WIP。等Luna node提交后由Sol在该树cherry并直接解冲突、审修/补受控UI，root仅集成Sol最终净改动。
- Luna实际copy实验证实副本实体ID重写、preview_undo+undo可成功并恢复源墓碑；但新增内容一致性断言暴露既有Project copy缺陷：重写MapAtlasRevision.document内entity_id后未重算geometry_hash，`geometry_hash(copied_document) != stored_hash`；merge_metadata.source_geometry_hash也仍源值，当前undo因两个旧存储hash相等而通过，不能视为一致性正确。明确交后续Sol node直接修Project copy地图hash/receipt并加回归，Luna不改该生产写区。
- 新map.merge_nodes revision2/schema hash与原preview入参相同；bootstrap固定operation snapshot多新条目而失败（其余2pass），由Sol更新新run目录快照并验证旧run不升级，Luna不修旧快照。

## 2026-10-15 18:36 当前三路并行

- Luna节点实现2e1f1475c4a43fb570ce2c261bd9bc7e97393156已提交clean。已知红测copy geometry hash和registry新项都保留，明确移交Sol，不由root/Luna改既有缺陷。新Sol/high sol_review_node_merge已在专属树无冲突重放63818215c并实跑13pass/2fail复现，开始直接修；新发现通知batch refs/tray/当前head遗漏墓碑或精确revision过滤也同批修。node Sol独占PG65202及浏览器65211/65212，禁止eval65302/真实库/模型。
- Sol final非阻塞方案无需新schema/独立任务：仅新空间协议plan冻结optional_stage_version=1进attempt；原durable reading task先main receipt提交，再details/spatial各自原journal/同root与子额度执行，持久阶段关联原receipt attempt，恢复继续，不修改immutable主receipt。旧frozen/append不升级。root要求多会话挂起可选provider时主receipt/World结果已可读，外层resume须处理committed-but-optional-running，不能只helper恢复。实现中未验证通过。
- 评测最小pilot按正式API受支持边界选1个development family的5Scene（同一chapter，ReadingRequest仅end_chapter），不伪造单case授权/截断重跑。Luna会给真实preview mandatory+spatial子额度的总上限及准确阶段预算；root待独立Sol审后才启动。holdout只hash检查，不解码。Codex本机身份元数据预检available=true，AUTH_MODE=local/APP_ENV=test，0模型请求；未写owner连接或业务项目。

## 2026-10-15 18:44 审修与恢复证据

- Sol final新增7项真实SQLite持久store测试：两个物理连接，optional provider挂起时观察方已读主receipt/World同事务实体；version0对照仍等provider，未升级旧run；真实AsyncTask→reading_status→resume→原handler取消恢复；unknown只1次请求并允许后续步骤；details两Scene真实prepare/compile/apply只读严格更早observation（0→1）。修shadow底层可达pending不收尾，待完整Evolution与gate，不提前报绿批。
- 根审具体发现节点多跳风险：A→B后B→C，原undo(A,B)不检查B已墓碑，会恢复A但C仍含A资料并破坏B→C回执。Sol node已选有界限制：source若接收其他合并不能再合出，undo拒target已merged；加有界链与乱序撤回回归。另核update_node缓存对象跨会话CAS，必要根修由Sol执行。
- eval Luna生产基线conftest缺map_notification_service，root未自行修；Sol node在eval专树merge83bb→7758800e8d3afa5bfd2b791e47ccd2018e919035，仅docs20冲突保留两段，所有eval WIP保留。root实际git diff确认该HEAD相对83bb无任何committed净差（生产及模块文档完全相同），4 seam tests collect通过，Luna已恢复测试。其旧8c追加冲突净差已随此同步收敛。
- 根审还标出新eval gate WIP把total_cost未知强制失败、n/a与缺覆盖混同：原计划要求诚实按题材报告费用，BOUNDS无货币阈值；不能把不可观测辅助指标私自升级硬准入，也不能unknown填0求绿。交付后由独立Sol review+直接修，Luna留记录，不在本批偷放宽质量门。真实required质量缺证据仍失败，genre必要coverage仍需证明。

## 2026-10-15 18:50 主回执解耦集成

- Sol6c40c400d93ae5f6d625629dce1492b1851d8be2→0c7369a31已无冲突集成，primary root12新增optional/DTO测试passed3.58秒；Solfinal主phase+shadow全Evolution/DI/prompt638pass1deselected，末尾rescan边界66目标pass，正在其最终HEAD再全域确认。
- 补扫两个clone明确剥离optional_stage_version/optional_scene_stage，保留原rescan parent与独立授权；category_rescan对新main已提交但details journal unknown拒绝清journal重发，沿用既有已确认旧gap语义。shadow阶段settled为not_run/shadow_isolated，不留永远pending。主receipt可选完成前后逐字段不变，stage冻结main_state_fingerprint，新增stageDTO纯读。
- node Sol已127普通/65组件/PG并发1通过，真实HTTP桌面/390已完成merge409重预览→成功→旧link显式target→undo，正在历史revision实际断言/看图/门禁收尾，尚未交最终SHA。primary未先拿有红测的638原功能。
- eval Luna四组driver新代码约3k行，已在775生产稳定基线；已有8失败1setup的报告，root要求既有fixture/回归直接交后续Sol，收尾功能/预算/文档/红测即可提交。追加根审明确assistant.turn提交时会剔除4读工具且执行仍检查flag，harness需隔离进程一致启用并恢复；task_hint硬编码retrieve会误导编辑意图，交后续Sol根修。仍禁止真实模型/holdout解码。
- 本次fetch origin/main再次确认00d861283不变，势力阶段1未在main落地，M5依赖判断未漂移。Codex只做本机身份元数据读取，未配置连接/发验证请求。

## 2026-10-15T19:40:18+08:00 实际 pilot 校准与引擎恢复

- 共同source/Scene/owner/LLM基线已冻结；真实Sol/xhigh seeded请求完成，原始IO与模型/effort/hash守卫4/4通过。共2次实际模型请求（正常账户验证1+校准1），无SUT业务模型调用。
- 只读Evolution preview HTTP409，未创建run/task；原因是新Project正常默认legacy。保留原operation unknown，不覆盖/重发。root走正常engine接口切换至evolution/epoch2，stop_active=false，停止/取消均0；实际再次验证原五Scene/source/LLM snapshot、Scene hash及原seed raw完全一致，0模型调用，不重写冻结材料。新preview使用新UUID。
- 此缺陷修复明确由Sol/high子代理直接实施：future setup增加正常GET epoch→POST engine及真实ASGI回归，单独提交暂不集成；当前pilot代码d8b152不变。仍无人类作者验收、holdout解码、真实作品或部署。

## 2026-10-15T19:51:18+08:00 真实启动冻结合同缺陷

- d8实际只读证据：Scene0已applied并有独立receipt，Scene1已在运行，两者optional_stage_version均缺失、optional steps空、顶层spatial_method_fingerprint缺失。Scene0真实scene_text与冻结source_excerpt逐字相同（51 chars），空间状态inspected/low_spatial_density、无空间请求journal。不把未触发抽取冒称空间质量通过。
- P1根因：workflow._plan298生成version1，但start_reading856白名单重建plan漏传，pipeline949/1026读取真实persisted run因而走旧执行路径。guard1164要求同attempt已收尾optional阶段；另1073要求attempt固定方法指纹，当前payload亦漏传。Sol/high已接收并直接修生产与真实产品链回归；root不改代码。
- 当前只让已在途2任务批次收尾，随后封存这次诊断pilot；不继续后三Scene、作者代理审核、Writing/Assistant/judge。修复须新hash新实验身份，不能通过手改旧plan/attempt、移植seed或放宽guard补成通过；冻结corpus/gold/BOUNDS不变。

## 2026-10-15T19:58:42+08:00 诊断批收尾与新版本准备

- 首批2Task正常done、两份主receipt，旧run停止前预算31剩16/消耗15（请求实际数保留unknown，不把reservation当模型调用）。root正常engine read_only/expected_epoch2/stop_active=true：stopped_run1、取消未尝试pending1，epoch3；0额外模型请求。所有raw、seed、common、ledger与PG记录保留，未改旧plan/attempt补成通过。
- 生产冻结小修2bed→de736745a与setup修8db→3b4b3b10f已正常无冲突cherry；root只集成未改产品代码。真实全链继续捕获adapter把Evolution optional range_hash与Writing切片hash误作相同、遗漏第6结构task，Sol直接修，模型上界不加、wall+900s。
- World Sol独立泛化2fail1pass证明当前已物化标准location候选但主observation无mention/中文类型时endpoint投影漏ID，原文无固定词则density误跳；已授权其独占Evolution/spatial.py与相关测试，保持原DB run/Scene/source状态验证，方法指纹版本化，禁止调私有case词表。另消费Sol在正常Writing/Assistant链检验，未确认缺陷不改。
- 新私有root `/Users/tywww/.codex/private/map-spatial-evaluation-20261015-r2` 仅逐字节复制matrix的10族source/expected共20文件，均原hash/0700+0600，holdout只读bytes做hash未解码，无binding/seed/request迁移，无新项目/请求。tmp run_phase_r2.py强制显式同root，不会误写旧账本；原诊断与新实验分开。

## 2026-10-15T20:07:45+08:00 正常消费接口修复与可达性边界

- Sol6a12f3406→primary75af638e9：实际开启地图后Evidence confirm因ContextSectionItem.status不接受adopted而500，现保留来源状态并接受该正式值；前端对应“已采用”。root真实产品链新文件3pass3.77s。覆盖source-only无地图正常Writing done、可信Scene位置on/off双任务done及core fingerprint相同、排除及地图revision漂移仅省略map、Assistant真实ASGI submit v6/read工具调用/真实exact worker done与map_spatial知识回执。均受控provider，不是实际模型质量结论。
- 当前eval真实normal preview/start→5Scene+第6structure→全receipt守卫在受控模型下已通，Sol完整Evolution+eval991pass2skip1deselect；仍补range_hash不同语义/5+1 task预算/额外关键执行文件pin，尚待SHA和World方法修正交叉验证。
- 严格保留source-only Writing可达性：无可信Scene位置则诚实空brief，不能为评测猜地点；当前Scene正文是否进入writing.generate确认上下文另查正常合同，不强塞全文/弱化futureScene界限。此类未满足前提不能冒称配对/开发质量门通过。
- World Sol正常ASGI start→主handler真实World候选→空间独立抽取/审核→structure→auto-draft已跑通：无主mention/中文地点类型、无固定density词亦按真实落库端点触发；自定义type初场emerging、clue待审、地图candidate且所有head空。7拒绝负例与原receipt/paid不可变重放通过，最终门禁中。无实际模型/评测PG访问。

## 2026-10-15T20:19:38+08:00 最终集成验证与r2启动

- aa706→339270370严格6Task/来源合同，99f285→24b82a3c5正常精确pin种子，7edb42→a518b93eb World端点投影/方法版本，c1719→abe911c35 Writing双臂共同pin/r2显式路径，72a653文档→3ed3db5c2。root只做自动无冲突cherry，所有代码修复由Sol/high直接写。
- root精确abe六域Evolution/World/Story/Assistant/Writing/Evidence+eval+container/assistant registry/task registry/prompt contracts：4561passed2skipped4deselected166.97s；仅原有Pydantic NovelIdQuery schema warning。生产同代码、3ed只文档。Sol独立精确abe联合1061passed2skipped1deselected83.81s，map eval72；source-only缺可信地点仍不能冒称完整Writing配对可达。
- 最终208变更Python Ruff/format、138生产file-size无warn、binary0、release、secret、普通docs inventory12域156表61handler16route49ADR、BASE_REF脚本支持明确逐项no-change说明及61/9/0/517通过。未宣称裸BASE_REF make无说明通过；未声称PG/真模型工程门替代质量。
- r2私有pilot-execution记录新execution_id、3ed代码、pipeline a2967ac124b888c595854309098164f941fbfb28b7e20aece936fd5c360938c8、原manifest与10族50case验证、5Scene+1structure/2-2-2、concurrency2、模型界297+M+Q、含首验证wall24870s、硬token不支持/费用unknown/humanfalse。现新setup进行中；新Project/seed都不复用r1身份。

## 2026-10-15T20:30:52+08:00 R2 可评估性核查

- R2首Scene主receipt已先提交，随后同attempt optional_stage_version=1，spatial extract/review均真实sampled且complete/inspected、无gap；第二Scene正在原max_tasks2批内执行，尚无第二receipt。这是执行链证据，不代表空间内容质量/paired gate通过。
- Sol/high只读确认：source-only canonical手工Scene没有structure_meta.location_id/location_entity_id，Writing loader传空query；Evolution只保留原文位置text_state、presence不写Scene地点，自动草图只有location图元。World/map正常采用不能凭空提供Scene地点焦点。ADR0037要求无Scene位置身份不猜。当前harness blanket expected_map_state=present是过强资格前提；若空应记本族coverage/可评估性失败和pair not_run，不弱化guard、改gold或猜地点。Sol继续调查正常自动enrichment路径，暂不改冻结代码。
- Sol/high预算核查：M21为静态最低mandatory，未计尚未物化World审查组；Q10是子上限，31是总调用硬闸门，不保证全部动态mandatory和10空间请求都完成。实际无传输/schema自动重试，budget消耗不能冒称实际调用数/费用。有限余量不足可产生组blocked或后续needs_budget，尚不能静态断言31必然不足。
- 决定：等当前2任务批完成，正常engine read_only/expected_epoch停止后续未执行任务并保存R2原始回执；不再盲跑后续paid阶段。之后仅Sol直接修评测资格/预算表述或明确合法路径，root不写修复代码。

## 2026-10-15T20:38:35+08:00 R2 已正常封存与后续边界

- 第一批session84584正常exit0：tasks_completed2，第三task01909d55-e024-4ccf-ba8c-2879c85304c6 pending/attempt0。随后正常引擎接口stop HTTP200，read_only/epoch3、停止1run/取消1task，纯读最终run stopped，两个主receipt hash前后完全一致，新增模型请求0。stop receipt/final snapshot及私有ledger均0700/0600保留。
- R2两Scene optional_stage_version=1，空间extract2/review2均真实sampled、stage complete/inspected；Scene0无gap，Scene1 unresolved_scope。教师4/4通过，但World作者审核/地图采用、Writing pairs、Assistant和judge均not_run，real quality gate未通过；human_validated=false、holdout未解码。R2实际SUT请求数unknown，预算硬cap31，含teacher已开始请求上界32，不用预算消耗替代实际调用/美元。
- Sol续查：正常Evolution draft enrichment也不产生稳定Scene地点ID；切分/扩增反而增加boundary和至多10个enrichment/review模型请求，不能补资格。现有合法入口是作者明确选定canonical World地点，经正常Scene PATCH写location_entity_id，再final freeze；这是额外作者输入。当前R2未做该修改。
- 已发可选验收口径问题：推荐保持ADR、单列模拟作者地点指定后辅助评测；另一选项为扩展带来源Scene地点提议/审核功能。等待期间继续独立的已确认harness预算/资格修复，不改生产guard和固定gold。新Luna/max只读规划最小显式author manifest；后续代码修复仍Sol/high直接做。

## 2026-10-15T20:48:58+08:00 预算与资格修复集成、author-assisted 准备

- Sol/high直接修复27ad8a6e17→主树cbb5fbd20，8文件415+/39-。root主树evals393pass2skip（12.25s）、make docs-check（12域/156表/61handler/16routes/49ADR）、diff check通过；Sol扩大真实TaskWorker/冷启动/Writing414pass2skip及lint/format/import61/9/0/517通过。另一Sol/high正在独立审查此批，有问题由其直接修。
- budget：显式原preview cap可≥M+Q、1..1000整数，headroom单列，completion_guaranteed=false，运行后不topup；M static_minimum、Q child_maximum。单family不含验证硬界296+root_cap、单列验证则297+root_cap。无地点的实际空brief生成私有unavailable/not_run诊断且不建可执行最终binding；合法mover-only brief仍可用。原head/nonempty/core与安全边界未弱化。
- R2只读实证：五Scene均无显式location，0 brief items；两个已执行attempt方法pin均匹配原common冻结值，0新模型请求；private diagnostic-readonly-proof保留。
- R3仅准备材料：/Users/tywww/.codex/private/map-spatial-evaluation-20261015-r3，新0700目录仅复制原20source/expected字节同hash（0600），holdout只核hash不解码，0Project/0模型/无旧binding/seed/requests。代码/方法/预算尚未冻结，不允许现在真实执行。
- 可选问题暂未回复，已说明先按推荐准备：保持ADR0037不从正文猜Scene位置；额外代理作者逐例明确指定canonical稳定地点ID，origin=agent_simulated、human_validated=false，两Writing臂共用同一Scene卡，额外输入/决定/PATCH步数耗时单列，不能声称零输入自动链通过。Luna/max只读最小manifest规划与Sol只读边界审查完成；eval Sol正在独立下一小批直接实现。正常Scene PATCH无CAS、meta整对象赋值；隔离无其他writer，前后完整meta/source/hash复核，unknown不重发。Scene既有任一地点字段不能覆盖、不能名称/alias/gold算法代选，实际World/map/brief稳定来源身份验证；不改生产guard/gold/BOUNDS。

## 2026-10-15T21:06:32+08:00 author-assisted 核心与并行真实API验证

- 预算/eligibility批cbb5fbd20已由独立Sol/high审查通过，无追加修复；79地图eval+29Worldbrief/Evidence（共108）及Ruff/diff通过。主树仍cbb，只有TASK未提交。
- eval Sol提交author-assisted core 2e97eacf864593735b6d90a440c480d0df96f362（6文件，专用487行helper+窄CLI/binding/report/文档，无新生产API/框架），当前未集成/未冻结/未实跑。旧eval393pass2skip与lint/docs绿，但不能当作新helper验证通过。scope Sol独占其树新 backend/evals/tests/test_map_spatial_scene_locations.py 并行写真SQLite ASGI正反例，main Sol独占helper修复，双方直接协调提交；root只集成验证。
- 新真实ASGI正例已复现正常PATCH updated_at带Z、GET同一时刻无Z而全对象字符串比较误判unknown；已交main Sol直接修，只允许服务端updated_at语义/格式差异，原raw回执和其它字段/source严格保持。等待修复SHA与联合tests后再集成/freeze。
- 新Luna/max在任何R3 SUT输出前独占创建首族私有作者意图：author-intents/map-xianxia-development-v1.json SHA34b7a7be17cbd5dc4d62bdc5ba70c6773a9d5a62ac9d3cebcb602da8d2d20eb7，5provided/0unavailable；root已核schema/hash/逐字quote/source hash/仅当前或更早case引用，receipt保留。明确新增author_added_scene_setting、agent_simulated、human_validated=false，不冒充原文已发生地，不写UUID/Scene。另4development族同类意图由同Luna继续准备，禁止gold/holdout/SUT输出读取。未来SUT无对应canonical地点/歧义就not_run，不补World实体或事后换有利地点。
- R3仍仅材料+私有意图，0Project/0业务模型请求；root准备显式root cap51（若实际preview M21/Q10则headroom20），启动后不topup，无完成保证。总业务模型硬界296+51=347，独立验证若发生另1；本次预期复用既有verified连接不再验证。author步骤0业务模型、至多5正常PATCH、deadline600；含author的family wall理论上界无验证25410s/含验证25470s（7h4m30s），cleanup/startup及额外有界review另计。
- 20:50再次fetch origin/main仍00d861283e34bdc0ef3f34ee5605c71e1f89c553，M5势力stage1外部依赖未满足；默认map flags保持关闭，quality/human/holdout均未通过或未执行。


## 2026-10-15T21:22:00+08:00 用户口径确认与最终评测边界

- 用户确认保留现方案：明确记录模拟作者指定Scene地点，再做地图辅助Writing对比；最新目标由root负责收尾。代码修复仍由既有Sol/high直接实施，root不写产品修复，不扩展地图以外独立计划。
- authorhelper新核心2e97eacf8、timestamp正常序列化修75e789d90及ledger/deadline31ef4e6d2仍待集成。独立Sol真实ASGI清理发现旧测试把rag_index_chapter手工done，旧425不能证明正常setup可达；已清除，不能以虚假任务状态交付。正常draft→五Scene留下publish_chapter×1和rag_index_chapter×2 pending/attempt0。两handler执行都可能重锚SceneSpan/embedding；本评测无lifespan/后台worker、绝不执行/取消/drain这三任务，逐次exact source回读，才允许保留其pending0。main Sol直接修ce6a51e10/daf021e95；scope Sol新test-only e6a5aa85b真实前后task_id/type/status/attempt完全相同、ledger记录未执行及副作用限定，新9ASGI通过，等待最终联合重验。
- root已对另四development作者意图核0600/schema/文件SHA/source/excerpt SHA/逐字quote/仅当前或更早引用，私有frozen-other-development-intents-receipt保留。五题材共23provided、2unavailable；意图label是代理解释，尚非正式World实体身份。urban-p4为信息不足、scifi-p5为退休无替换锚点，两者unavailable本身不能证明无空间机会，后者原gold有客观空间原子。未改原资料/gold/BOUNDS，holdout仍仅hash未解码。
- Luna/max只读确认指标Metric允许0/0 N/A，但当前执行链每case必须nonempty brief，因此合法省略控制亦不能完成完整评分。root决定保留所有5case真实Writing两臂（不skip、无手填N/A），由main Sol最小补SUT前冻结逐case positive/omission_control role：前者仍严格实际node/head/nonempty；后者无作者地点输入、实际brief必须空，两臂仍运行并评正文/错误断言。任一positive漏抽或omission实际有mover brief均失败，不能事后换role；全genre严格改善/正文不下降、全N/A失败与BOUNDS不变。roles在common冻结且早于任何本族SUT输出，source/hash绑定、reader重验；无roles旧路径不变。authorhelper只patch positive显式UUID，omission记录0输入/原卡未改。所有代码修复仍Sol直接写，等待其独立下一小批及真实负例。
- R3仍0Project、0业务模型请求，未冻结pipeline。首族准备rootcap51，无已启动run自动topup。先完成最终代码/测试/文档，再新hash/正常Project/校准/隔离pilot；旧R1/R2封存不可复用。M5前置仍缺，默认开关关闭、真实质量与作者验收未通过。

## 2026-10-15T21:22:53+08:00 authorhelper最终集成与预声明完成

- 2e97→eb0e44c07、75e→e45d2aa3c、fe0→2090d034f、31ef→4eaf2de85、ce6a→b6dd7479e、daf→f31c0c325、c3abc→42615ebdd。只改eval/测试/README/预检，不改生产。root同HEAD联合425passed2skipped22.83s，10资料族50case离线verify、全eval Ruff/9format、docs库存及带逐项no-change理由的origin/main影响门均通过；不能将9 helper ASGI的明确Evolution HTTP替身前提说成真实paid全链。
- 私有writing-roles五dev JSON于任何R3 Project/业务输出前创建，完整source与excerpt hash绑定，origin=agent_simulated/humanfalse：23positive、urban-p4/scifi-p5两omission。omission仍需两正式Writing任务和正常judge，不强制0/0，遇实际有brief拒绝；positive漏抽不能事后改role。xianxia roles文件SHA1088b381f0c07614f88a22433adf82dc116db9dee8028e2b2832bf945c4cd670；完整五族hash与作者intent hash在私有frozen-roles-receipt。仍未冻结R3 pipeline、未启动任何模型。

## 2026-10-15T21:34:28+08:00 最终工程冻结与R3实际启动

- role批f14f16e08→287955212、574f69259→ba20dc793已无冲突集成；root精确联合435pass2skip24.92s，Ruff全eval/10format、docs inventory156/61/16/49与diff绿。Sol精确同码435pass2skip25.35s，明确七authority no-change的BASE_REF门、61/9/0/517绿；独立scope真ASGI新文件604（等价574）包含4PATCH+1卡不动、source-only两个正常TaskWorker done、baseline双空/core相同/候选未采用。均providerstub，非真实质量。无roles旧默认严格positive，omission仍双task且judge正常评空间/错误断言与正文，全genre严格改善与BOUNDS未改。
- R3 pipeline f69a01881711c288c0d8c38c819a7862bf39724d2a5ec7127d479d6c735e1627、code ba20、execution_id8ae7a00d-5849-46a7-83e9-1a0e78dd7664已冻结至私有pilot-execution-20261015-r3.json。实际新Project f7ea5188-d1ba-42c6-9d55-aad470610ce6正常setup5Scene与freeze-common（带预声明roles）完成；复用原正常verified连接，无新连接验证。新seed校准正在独立session18498，尚未声称通过；Evolution尚未preview/start。计划cap51只在实际M/Q确认后启动、不topup，单族全阶段模型硬上界347（无新连接验证）、wall25410s另计startup/取消清理及每额外review1440s；真实费用unknown、硬token预算unsupported。
- 最新fetch origin/main仍00d861283e34bdc0ef3f34ee5605c71e1f89c553，M5独立势力stage1未落地。Guimi/真实作品/受保护库未接触，holdout仍仅hash。作者模拟辅助非原文自动地点抽取，humanfalse/真实质量尚未通过。

## 2026-10-15T21:37:41+08:00 R3校准与实际Evolution批次

- 新seeded4/4及实际Sol-xhigh/executor/schema/prompt/raw hash守卫通过，1次新教师请求；连接原verified复用，无再次验证。只读cap30预览明确budget_insufficient（M21+Q10=31），保留operation221ba250-1c6b-4c27-955c-369e2473320c原记录；cap51新preview operation895bdc74-1515-47c8-ab30-cba6bbb7e31b、fingerprint1f8eb40e8ae236c95be4c63466d0e617afb49cd4bcc5c8b3f66de6534b8ba437。root对实际request/facts/common/原pipeline断言并冻结root-checked-preview-r3.json（0600），extraheadroom20、totalcallupper347、completion_guaranteed=false。
- 正常start pending，run reading-895bdc74-1515-47c8-ab30-cba6bbb7e31b，5Scene，firsttask14736d15-f942-4769-a9b7-e42cf4222cce。第一批只执行原正式回执指向的两个pending0 exact task，session80380；尚未声称Scene/空间独立审核完成或质量通过。unknown/超时不重发，不执行pending派生索引，不drain队列。实际SUT调用数/费用未具可验证遥测仍unknown，root51是调用硬cap而非实际消费。

## 2026-10-15T21:56:18+08:00 三计划完整实施授权与新批次

- 用户正式答复之前范围澄清：三份计划全部实施，包括操作目录、档案、导演、世界推进；再次选择保留显式模拟作者地点输入的地图辅助评测口径。原“暂未答复/只做地图”现已失效，历史证据保留。
- 三棵本地隔离树均从ba20创建：map-operation-catalog-impl（Luna/max，A0目录/纯SPEC/trace/写路由棘轮）、world-object-dossier-impl（Luna/max，C0 World档案+Character兼容闭环）、simulation-v3-director-impl（Luna/max，先C3统一提醒，后C4/C5）。根树实跑评测期间禁止集成生产变更。宿主仅3子代理并行槽，分轮满足多代理要求。
- 共享装配与Assistant现有核心文件由A0唯一写；C0/C3新增纯SPEC及独立模块后提供接线需求。各自只新建唯一migration，不改旧文件，最终由Sol统一线性链。TASK根唯一写，代码问题Sol/high直接修，不push/PR/main合并/部署。
- R3首批2任务正常完成，下一task8ad6152f-a8bc-4bf4-a67f-1baaa3640496。运行中曾只读观察main receipt已可见、空间步骤仍在跑，私有diagnostics/r3-main-before-spatial-snapshot.json保存；Scene0 receipt SHA1590058796e72f9409fa60fbea5be6d518ae23374855d6c73dfbf8269e8ca513待批后复核。空间存在endpoint_reference_not_in_input/unresolved_scope，不能把inspected当质量通过。

## 2026-10-15T22:02:26+08:00 R3第二批与复用审查树

- 首批2任务后只读核实main receipt不变，根运行第二批exact max_tasks2（phase evolution_batch_2_xianxia，session48632），不扩大root51、不执行派生索引。Scene2 running/attempt1、旧两Scene空间已complete但均有scope类gap。
- 下一轮Sol审查预备复用已完成且干净、无未跟踪文件的map-spatial-eval-review树；原codex/map-eval-final-joint/574f692分支保留，新建codex/map-full-plan-integration-review从ba20起点。无reset/清理，其他WIP保持。新三实现树均运行中，尚无新代码集成。

## 2026-10-15T22:06:26+08:00 R3四Scene完成

- 第二批正常完成，累计4任务、committed_scene_index3、4 main receipts；Scene0/1独立空间抽取与复核sampled但有gap，Scene2/3因low_spatial_density未发空间调用，保留实际覆盖，不补造。next_task=c9e2e578-71c8-4d25-8255-ad94d0ceba17。
- 已启动第三批phase evolution_batch_3_xianxia/session56492，仍max_tasks2、root51原冻结预算；待第五Scene及结构结束后按正常World审核再核预声明作者地点。

## 2026-10-15T22:16:25+08:00 R3结构失败与正常封存

- 第三批实际完成第五Scene，5条main receipt可读，空间Scene4真实extract/review均sampled/complete但unresolved_scope。第6个structure task e9be27ca-ebfb-4375-8af1-3e0bf8cdb926 failed/attempt1/recovery_required=true；错误为strict持久化揭示目标无法解析。错误全量只在private diagnostics/r3-structure-task-failure.json，批次日志SHAd0731153d610f425c9ad626608c87466206ecb8b60f0b63223da080657ffa485；不是HTTP超时，也不能据此放宽目标校验。harness状态unknown，不盲重试。
- root经正常GET reading核epoch2，再POST engine(read_only,expected_epoch2,stop_active=true,authorization_confirmed=true)返回200/epoch3/stopped_runs1/cancelled_tasks0。前后5 main receipts哈希一致，原failed task内容与其他publish/rag pending任务状态也完全一致；private diagnostic-{before-stop,final}-snapshot、stop-response与stop receipt均0600。控制记录diagnostic_stopped/previous_status unknown，不伪造completed。停止0模型请求。
- R3 teacher实际4/4通过、五Scene读取已执行；World地图审核、显式作者UUID步骤、Writing双臂、Assistant、judge均not_run，完整质量gate未通过/humanfalse。实际SUT请求数及金额仍unknown，原root51与总upper347上界不等于实际花费。保留所有原资料/gold/BOUNDS与holdout未解码。
- 当前无live付费runner，主树仍ba20仅三份TASK修改，新的A0/C0/C3代码尚在各自隔离树。后续Sol应先只读诊断结构失败；若为模型无效输出就记录质量失败，不能为过评测删除有效strict断言。无需重复跑同一R3或复用旧seed/binding。

## 2026-10-15T22:30:37+08:00 A0a/C3a提交与Sol并行审修

- A0a Luna提交f7ba93e8bc5e428a8aef76b6d483ef4236049220：64项目录/六插件纯SPEC/v7发现冻结/v1–v6兼容。干净归档29定向/Ruff/docs156表通过。A0b trace migration/model/service/DI/config等WIP留原map-operation-catalog-impl，不stash/reset/清理，不把混合树验证冒充净commit。Sol/high sol_review_operation_catalog在复用干净map-advisory-review、新branch codex/operation-catalog-v2-review从ba20 cherry后独立审修。旧codex/map-eval-author-review与604260提交保留。
- C3a Luna提交69b77838298e7fcda225ef798151a75127c98d23：5真实providers（Story结构，Writing冲突与失效，Assistant主动与前瞻）、独立session/失败占位、处置与类别静默。7 tests/Ruff/import61/517/docs158表及SQLite migrate up/down通过；app共享接线、PG和前端未完成，G8a未接、editorial队列具体导航/处置未闭环。Sol/high sol_review_unified_notices在map-spatial-eval-review、codex/map-full-plan-integration-review审修；同时只读R3两个精确diagnostics JSON triage，禁止读其余gold/holdout或发模型。
- R3新增private diagnostics/r3-structure-journal.json保留generate与review:0两次sampled原始数据，可离线定位strict unresolved target；不以合法失败校验当待删除缺陷。无新业务请求。
- C0本批为World设定条目/模板/Character兼容与Story状态注册，Evidence三层聚合和ledger只读DI端口待下一C0b/C2闭环，不能称整个C0已完成。root与Luna已核多条当前条目必须允许同一legacy字段并存、legacy整体写回只收拢该组、desire/fear分键、null/no-op/CAS。档案SPEC留World领域目录。
- 下一步：收Sol两批直接修复及精确验证；再同步A0b并接组合根，C0提交后Sol审、开C0b/C2，再C3b前端/G8a与C4/C5。所有新migration最终单Sol统一线性链并做PG fresh/ORM parity/CAS门，不由root手改冲突。

## 2026-10-15T22:31:24+08:00 Sol确定R3结构失败根因

- sol_review_unified_notices只读冻结generate/review journal确认两条reveals均supported；reading_structure._simple_structure_to_parsed把揭示主题title当target_name，而persist_structure_drafts传空entity/character映射且strict=True，任意非空reveal均必然ValueError，是确定性实现缺陷。Sol正在单独离线复现与直接修，保留strict和内容/provenance，不猜World实体、不静默丢候选冒称已保存。原R3失败/stop/账本保持，无付费重试，后续实跑须新pipeline。

## 2026-10-15T22:44:27+08:00 审修集成与第二批交接

- 主树HEAD158cbe57b，TASK更新前干净。A0a修复：legacy forecast v3快照保留两字段；v7按实际操作兼容关闭；团队冻结不可执行项仍可describe；恢复地图编辑真实schema hash。root在dabc0b319跑Assistant/Imports/World相关扩大回归1217 passed（33.81s）。
- C3五真实来源的Sol修复含延后到期恢复、分页更多披露、处置读timeout、静态trace字段与demo只读写拒绝。R3未解析关系主题留在batch receipt，公开作者GET /api/evolution/reading的structure_review显示数量/内容/逐Scene证据，不猜实体、不关strict。root在158cbe57b跑统一通知+全Story+Evolution workflow为797 passed（21.61s）。C3新API/DI尚待组合根接线，不当产品闭环。
- 原A0b WIP与旧审查分支保留；Sol只读复制新目标分支且核哈希+17烟测，Luna继续实施。C0a23e进入Sol独立审修，C0b/C2 Luna并行，禁止共享文件双写。三migration链待统一，新C0/C3/trace尚未PG验收。
- R3封存停止，本批未重跑真实请求、未改实验DB/原始回执/种子或holdout。真实质量未通过、human_validated=false；本地工程绿色不等于作者验收。没有push/PR/main合并/部署。

- 文档门禁：158cbe57b的inventory通过（12模块/158表/61任务/16路由/49ADR）；直接BASE_REF检查列出CLAUDE.md、模块总览html/drawio、05_memory.md四个未改文件，root已逐项核对并用脚本支持的no-change-reason通过影响检查，理由为稳定导航/现有12模块61方向未变，A0/C3/R3不改Memory事件与checkpoint写入所有权。C0 typed state尚未集成，后续须重核并更新相关文档；不把此理由沿用到未来实现。

## 2026-10-15T23:04:48+08:00 C0a 审修集成与跨域回归

- 主树实现为b81ba6887（C0原13a11cff0 + Sol直接修复），另1d503209b补05_memory类型化来源边界；当前干净。Sol修复非空旧资料created_at默认失败、C3 ORM/迁移FK索引/时间/comment漂移、恢复Scene锚与停用facet、结构化legacy值、demo拒写、typed状态与有向态度、分页unknown、静态trace白名单；动态Story字段不回填World稳定层。
- Sol证据：58 unit；独立PG dossier_review_test_20261015 fresh升级、dossier_upgrade_test_20261015非空旧数据升级；1项独立session并发CAS/失败回滚/跨novel E2E通过。原map_enhancement_test仍map_node_merge未修改；C3两表metadata parity尚依赖A0b共享env/bootstrap notice_models显式导入。
- root在b81ba6887代码上扩大World+Story+Evidence+container/registry：2978 passed、1 skipped、2 deselected（67.62s），已存在Pydantic schema warning无新增失败。1d503209b docs inventory通过：12模块/159表/61任务/16前端路由/49ADR。未完成全分支最终门禁、真实质量或作者验收。
- 三层聚合Luna保存WIP633293ee2并接C3四提交后，cherry c99a702ae在dossier_service.py冲突；root暂时interrupt该子任务释放宿主并发槽，已交Sol直接解冲突，禁止root/Luna手改审修冲突。Luna恢复后继续Evidence聚合与C2。C3b新Luna/max在simulation-v3-director-impl/codex/copilot-unified-ui做真实提醒/ReadingFlow待核候选和缺失G8a/editorial薄来源；无UI假数据。A0b Luna继续trace与组合根，已要求本轮新C0写路由显式绑定op_id，不能放进历史豁免baseline。
- 世界对象统一三层读取/GenericEntityProfile映射、C2人物卡/UI、C3产品接线与界面、A0b/A1–A4、C4/C5均未标完成。R3封存原样、无新模型请求或holdout读取；没有push/PR/main合并/部署。

- 2026-10-15T23:10:03+08:00：C0b冲突已由Sol直接解决并完成cherry为4cb98784d，33目标测试与Ruff通过；原633293ee2聚合/Profile映射与c99安全修复均保留。root已followup恢复Luna，当前继续聚合，不再处于冲突停点。首commit要求独立可导入、不依赖尚未存在ServiceKey符号；角色视角不调用Evolution台账port，作者视角可显式读取，省略单列。

## 2026-10-15T23:20:08+08:00 A0b 提交与环境校验

- A0b原实现三笔自有提交 f9a9d8f14、87752e8fd、203018dfd，Luna目标树map-advisory-review/codex/map-operation-trace-impl已干净；C3/C0父提交已在主树，不能重复取。已交Sol/high sol_review_operation_catalog在map-assistant-review/codex/operation-trace-review，以dd13268fb为基线独立审修，含真实HTTP最终commit失败时序/PG事务/隐私/路由ratchet/装配/单head+parity。当前还未集成主树，不能标A0或产品接线完成。Sol独占工程PG65202新review DB，原库与C0两review库保留，禁止eval65302。
- 实证纠正验证环境：唯一正确解释器是 /Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python（3.14.8/Pydantic2.14.0/core2.50）；原repo/backend/.venv为3.14.7/2.13.5/core2.46.5，不用于最终验证。原环境Decimal schema多pattern导致194c，正确环境schema90aa；两树用正确解释器完整schema逐字段相同，golden未改。Luna A0b在正确环境重跑组合13pass与Ruff。C0b Luna承认早期定向误用原环境，已要求首commit前用正确环境重跑；root前述1217/797/2978全部使用正确worktree解释器，仍为有效证据。
- C0b冲突已解4cb98784d并恢复Luna，继续首个可独立导入的Evidence聚合/brief/API切片；C3b UI及G8a/editorial真实来源仍在实施。后续A1–A4、C2/C4/C5和外部门禁保留；无新真实模型请求、push/PR/main合并/部署。

## 2026-10-15T23:31:00+08:00 三层简报提交与真实 HTTP 追踪审修

- C0b首切片30d5b0698已独立提交，需连同前置633293ee2审查；C3/C0a父提交不重复cherry。新增Evidence三层聚合facade/API、只读Evolution provider与明确省略；角色投影不调演化台账。Luna已在唯一正确3.14.8/Pydantic2.14.0下跑45目标测试、Ruff/diff通过。未集成，也不等于C0/C2完成。
- GenericEntityProfile旧PUT仍直接写data_json/evidence_refs；旧GET/list与WorldBackground仍读旧表；类型转换snapshot/restore和generic→strong迁移仍需bridge。Luna继续C2卡片/Reaction后独立实现事务修订桥接、兼容读投影、未知字段/证据及转换恢复保真。不能把新增只读projection当新旧真相闭环。
- Sol在A0b真实PG/HTTP先失败后修复两个P1：main读取未赋值trace context；当前FastAPI include_router有效route派发绕过source APIRoute wrapper。已直接修并3项PG E2E通过，含成功/最终commit失败回滚/原文不入trace；其它审查仍在进行，未集成。另修任意result/preview id泄露、纯flush操作事务形态误报、新Vocabulary绑定与空间线索单项真实豁免。没有将新增写路由藏入旧baseline。
- C3b统一提醒前端及G8a/editorial纯来源继续实施，共享装配仍由A0/Sol单一写入。A1/A2源码、状态机和验证交接见操作任务artifacts/A1-A2-HANDOFF.md；C4/C5交接仍见对应任务artifacts。所有剩余阶段继续属于本次范围。
- R3和holdout未动；没有新增模型请求、push、PR、main合并或部署。主树本次仍只更新任务记录，不提前纳入未审代码。

## 2026-10-15T23:58:00+08:00 A0b集成与扩大回归失败处理

- A0b原f9a/8775/2030三笔与Sol df668净fix已集成primary为98cbdced9、1f77bf4dc、5d7b270ff、d20d27517；真实HTTP派发、事务、隐私、缺口标记、180天worker归档均有Sol112目标与6PG证据。原74项当前无live multi_stage成功路径，只有未知异常fail-closed测试，不宣称未来内部commit成功路径已实测。
- root在d20正确3.14.8环境扩大Assistant/全部tests/unit/Collaboration/World助手-空间-档案/Writing API助手及API闭环：9 failed、2162 passed、4 warnings，90.71s。失败含3个guided_flow run fixture缺session_id、R0 read fixture缺trace字段、13条active-project guard识别或入口问题、map_spatial loader期望列表、World facade __all__、一处autospec。另有3个Connection._cancel未await RuntimeWarning待triage。完整日志/tmp/map-a0b-primary-regression-20261015.log；原Sol已恢复直接修，root不手改。
- root module-import-gate 61/61、517/517通过；docs inventory164表/61任务/16路由/49ADR通过。BASE直接仅剩CLAUDE.md需审阅，root已读其仅@AGENTS导入/导航，按脚本支持no-change-reason逐项说明通过。World档案文档d7c6f45d3、架构HTML/Drawio 2c57b99bb已同步并浏览器看图，不能说未经说明的直接make BASE全绿。
- C0b新Sol/high在map-spatial-eval-review接到d20，已解633冲突再取30d，独占World/Story/Evolution narrow read ports的core keys/bootstrap与65202新review DB。原A0回归Sol不并行用PG；C3b准备树da21d3f05仍待下一批真实装配与busy/reload问题审修。
- Luna C2等待DI闭环，全部新功能和试探安全checkpoint为f6f559f922c946ba7ee7bc4e4c40103d7b0a005c，树干净、明确不可直接集成；DI前79相关测试/26prompt通过不适用于当前import失败状态，当前gate520/517。已结束该子代理释放宿主槽给Sol回归修复。待Sol净修复后由Sol安全移入该WIP再恢复Luna，继续C2验证/审修与尚未开始的Generic旧写/读桥接；修复仍Sol直接写。
- 目标跟踪读取为空后，依用户已有/goal指令建立active tracker，未改三份计划范围、授权或预算；不因工程切片通过标整套完成。封存R3/holdout/原库未动，无新模型请求、push/PR/main合并/部署。


## 2026-10-16T00:10:00+08:00 执行检查点

- primary文档HEAD 73cd5a74c，生产代码仍d20d27517；扩大套9fail/2162pass尚未修后重跑。
  A0 Sol正直接修app/main写入前owner/active门禁及失败终态会话隔离：marked HTTP 4xx可能
  绕过get_db测试注入而尝试默认全局manager连接，已暂停相关广域测试。禁止为核实而访问
  默认开发库；实际是否写入仅从现有证据判定，不能声称未发生。
- C0b Sol已复现并直接修author_safe中secret及作者层指纹/省略计数侧漏，安全投影回归7项通过；
  DI、真实API和隔离PG仍审修中。作者管理使用author_full，角色与默认safe生成必须分开；
  include_patterns/only_adopted的显式开关不能被静默空转。先交C0b净fix，再由Sol移植到
  f6f559f9后恢复Luna C2/Generic新功能，不直接集成该损坏WIP。
- C2b前端已提交a212d9faa（父53aaec35c为C3b），Luna报告248文件/3129测试、lint/build/docs/import
  通过；root看过390 Scene/1280 World mock组件截图，无横向溢出，不算真实app/API验收。
  下一Sol前端批需同时审真实来源装配、作者模式契约和跨scope异步冲突，候选问题见REVIEW-QUEUE。
- 新Luna/max luna_simulation_v3已在map-assistant-structure/codex/simulation-v3-protocol-impl
  从73cd5a74c实施C4a。仅共用协议与状态试验，保留旧run只读、RP observation_v2入口和自身
  max_actors；不碰main/core keys/bootstrap和当前C0/C2共享文件。协议切片不代表C4b/C5完成。
- /goal tracker现为active，无token预算。宿主root+3子代理，当前2 Sol/high修复与1 Luna/max实现。
  没有新增模型请求、评测/holdout读取、push/PR/main合并或部署；R3仍封存。全部剩余授权范围继续。


## 2026-10-16T00:20:00+08:00 主树回归通过与C0b补审

- primary32e63b630为Sol6962d51c1净修复集成；root同一原失败扩大套使用正确3.14.8、
  显式无secret不可达单元DB URL和RuntimeWarning转error，2178 passed/1已知schema warning，
  84.30s；日志/tmp/map-a0b-primary-regression-fixed-20261016.log。未重做当前A0 PG关键路径，
  旧6PG通过不等于新guard路径已重验；待工程PG释放后随UI真实组合复验。
- C0b Sol交付78808780f/582955cd3，61 SQLite、2真实PG、Ruff/import61/517、route ratchet、
  docs有理由门禁通过。root发现limit250先分页再过滤secret会让隐藏条数/排序影响safe覆盖，
  已由同Sol直接补分页前可见范围；因此C0b暂未进primary，不以初版通过冒称最终安全。
- C2b/C3b组合树原提交cherry为a52159a47/91fd0902f，另接A0fix为d03dce096；Sol已复现
  busy/reload、模板重读丢草稿和409二次GET晚响应，直接修复并对齐author_full作者管理请求。
- C4a Luna已锁45项旧协议/HTTP状态试验基线，保留unresolved_outcomes的actor_id旧语义，
  正迁移协议与Story新建入口；RP保留v2。当前没有新真实模型或评测数据访问。


## 2026-10-16T00:42:00+08:00 C0b集成及主树组合验证

- C0b原/审修五笔在primary为5aef92090、04dfbe9b4、3fced27ae、9e44a2391、b9307c4df；
  35937082b的安全reader回归已入20901345a。源PG2项在最终b930由root复验通过0.38s；
  A0 6PG在32e复验通过0.61s。各测试仅专用工程DB，无默认开发库/评测库访问。
- 初次扩大2fail/3014pass交Sol直接修29995771d，集成为4c04bb982：另一个Story run测试
  fixture补session_id；template新增key令操作公开schema变化，明确revision/op_version=2，
  旧v7修订1仍可describe但不能执行，不偷换旧schema。root修后3030pass/3deselect/1既有
  Pydantic warning，70.35s，日志/tmp/map-c0b-primary-regression-fixed-20261016.log。
- C0 Sol解8处组合冲突并保留backend f6全部人物卡/Reaction/optional loader，5b4623987有
  60相邻测试与61/517通过；另由SolUI移299到该树为5217f5310，当前干净，尚待Luna续写。
- 工程PG65202已由C0释放给SolUI，专用copilot_integration_review_test_20261016 head；
  新真实7来源独立Session HTTP1测试通过（含来源失败隔离/read持久化/mute/demo零写入），
  与C0组合及真实浏览器继续，UI尚未入primary。
- C4a必要调用方范围追加SceneRehearsalPanel/useStorySceneWorkspace最小v3接线，默认一轮，
  旧历史只读；Interaction ensemble.py仅显式锁rehearsal_v1以保留team_v1，不改RP策略/上限。
  A1 Luna已快进primary4c后新增纯SPEC，没带待审UI栈，不与Sol共享写。
- 没有新模型调用、R3重试、holdout读取、push、PR、main合并或部署。全部剩余授权工作继续。

## 2026-10-16T00:55:08+08:00 C3b/C2b 真实组合验收与下一批

- 配套C3b/C2b已集成并经root86后端+3专用PG+3134前端及lint/build组合验证；地图来源提醒实际读取正文manifest的source_hash，修复保存正文后来源不可用。详情见character-world-progression同轮记录。
- 工程PG65202已由Sol释放、root本批3测试完毕，目前无使用者；原map_enhancement_test及各专用reviewDB均保留。评测65302封存R3、holdout、默认开发DB不访问，无新付费请求。
- 三份计划全部实施的授权和用户“Sol子代理直接修”保持；只本地提交，无push/PR/main合并/部署。未完成实现及真实质量/作者验收继续如实保留。

## 2026-10-16T01:17:50+08:00 C4a审修集成与A1/A2交接

- 配套协议C4a已审修集成，root1034后端+1专用PG+23Vue/lint/build通过；C4b/C5仍待实施。地图typed引用现在按本作品当前adopted head核验，不能凭字符串ID冒充来源；未知位置不能让角色获知公开事件。
- 工程PG65202在root本批验证结束后分配Sol A1独占新a1_operations_review_test_20261016；其他review库/原库保留，C2与Goal待排队。默认dev DB/评测65302/R3/holdout不访问，无新付费请求、push/PR/main合并/部署。
