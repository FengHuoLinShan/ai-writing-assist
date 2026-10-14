---
id: T-20261014-audit-g8-atlas-invalidation
title: 改章后提示当前地图册来源需核对
status: completed
created: 2026-10-14T11:38:03+08:00
updated: 2026-10-14T12:33:55+08:00
---

# 地图册来源接入写作失效回执

## 恢复快照

- 工作区：`.worktrees/audit-g8-atlas-invalidation` / `codex/audit-g8-atlas-invalidation`，基线 `22bb499789cba89fea92e918fd853ab768688e07`。
- 已完成：原切片工程验收；主审追加的完整正文热路径风险已用SQL身份投影修复，文档重复收敛，当前专项65例与PG1例、lint/docs/import复验通过；保持未提交交主代理。
- 下一步：主代理按三份fixture/test变更集成，更新实际522导入棘轮，再完成集成树全门禁；本树专项与完整fast已通过，保持未提交。
- 阻塞：无。

## 目标与验收

发布来源变化在同事务建议性披露受影响地图名/章/核对入口；仅 saved current head，owner+novel 隔离，真实来源 ID/hash/章重验；上限/未覆盖/SAVEPOINT 降级明确。Scene 窗口/登记/重算选项不改，不新增表列/outbox。

## 上下文与边界

用户授权首批并行，主代理指派独立切片；只读权威计划 §7.2/7.3/7.6/9/10。只在本树编辑，不提交/推送/PR/合并/部署/真实模型或数据调用，不改共享索引/G2/W8。本切片无自动地图status改变、正史写入或地图重算。

## 决策、发现与失败

- 2026-10-14T11:38:03+08:00：主代理采纳最小匹配：当前地图 head 的同 owner/novel/章真实历史 canonical 来源 ID/hash 重验，再与当前 canonical 身份比较，旧历史版也披露；不限定紧邻上一 canonical，不扩大到 Writing 全生命周期预捕获。不存在当前 canonical 时，真实旧引用仍提示；不匹配真实身份/hash须显式未覆盖。

## 里程碑与进度

- [x] world只读port / DI / 回执 fingerprint 与公共视图。
- [x] 作者地图名/章节/核对入口；不增加重算项。
- [x] 模块/前端/PG/浏览器/仓库门禁与文档。

## 验证证据

- 开工 `make docs-check`：通过。

## 交付结果

已本地实现与验证，未 commit/push/PR/merge/deploy。无真实数据库/用户语料或业务 LLM 调用；专用数据库与浏览器 fixture 全为合成。测试通过不等于生产或作者实际验收。地图对象/世界书页/待审 candidate、正典和 world_knowledge 仍未覆盖。

## 实现与验证证据

- `world/map_source_consumption.py`：最大 200 saved current head、1000 条 source_range；project 门禁校验请求 owner，node 与 revision 同时 novel/node/current_revision 过滤。MapDocument 和权威 Writing facade 分别验证引用结构与真实旧稿章/version/hash；不信任 map 自报章号，同章当前canonical不误报，旧版/撤回后的引用提示。
- `evolution/map_consumption.py` 消费方 Protocol，`WORLD_READ_MAP_CHAPTER_CONSUMERS` 常量与 bootstrap 无条件装配；map_atlas_facade 只导出本域实现。移除 record_writing_source_change 多余 function-level request import，把 canonical/map 组装移到 apply_source_invalidation 最终 fingerprint 前。实际依赖边/双向对不增，函数级导入 524→523，脚本棘轮收紧至523。
- `consumption.py` 作者标签/地图 affected 条目与 canonical/map 指纹；既有 scene assessment/chapter_registered/from_scene_index/recompute covers 均不改。指纹忽略临时 canonical 索引状态，只纳入权威 source ID/hash；重复相同回执重放一致。残余 unsupported 明确列对象/世界书页/候选。
- 前端只在既有 invalidationModel、InvalidationNotice、RecomputePanel 添加名称、章节和核对入口，复用 bridge/router 离开保护；URL 查询安全编码为现有 router 接受的字符串，不显示 raw ID。残余 unsupported 名称与已接线地图区分。
- runtime 只读复用 `/Users/tywww/.codex/worktrees/codex-luna-runtime/ai-writing-assist/backend/.venv/bin`；前端 node_modules 仅在本树软链接主树已安装依赖，不修改共享依赖、不安装新包。
- 开工 docs-check 通过。模块回归 [module-tests.log](artifacts/module-tests.log)：`modules/evolution/tests`、world 的 test_map_structure/test_map_structure_selection、Story test_scene_basis 与 test_container，522 passed / 1 deselected（排除真实模型）；新增标签对拍后 [map-contract-tests.log](artifacts/map-contract-tests.log) 52 passed。七个新来源/事务/隔离测试覆盖旧版、当前版、working、撤回、伪造章/hash、非current/candidate、空态、地图/来源两个上限、foreign novel、owner 与保存回执落库/幂等。
- 三个指定前端测试 [vitest.log](artifacts/vitest.log)：54 passed；全 `npm run lint` [frontend-lint.log](artifacts/frontend-lint.log) 通过；全 `make lint`（用既有python -m作为runner）[backend-lint.log](artifacts/backend-lint.log) 通过；26份合同 [prompt-contracts.log](artifacts/prompt-contracts.log) 通过。
- 专用 PG `127.0.0.1:18647/audit_g8_e2e_test`（只使用父任务给定合成账户）：本树 `APP_ENV=test DATABASE_URL=<explicit> python -m alembic upgrade head` [migration.log](artifacts/migration.log) 通过。`make test-postgresql-critical` [postgresql-critical.log](artifacts/postgresql-critical.log)：95 passed /157.59s；指定 `test_p2c_invalidation_recompute.py` + 新 `test_map_consumption_invalidation.py` [postgresql-map.log](artifacts/postgresql-map.log)：4 passed/2.38s。后者在真正 PG SQL 错误后证明 SAVEPOINT 回滚、主失效回执保留、session 仍可查询/flush。初次直接 pytest 命令受默认 marker 排除4例，已显式 `-m 'not real_llm and not external_data'` 重跑实际执行，未将 deselected 当通过。
- 浏览器 [browser.log](artifacts/browser.log)：2 passed/11.0s，独立 BACKEND_PORT18122/FRONTEND_PORT18123/PW_REUSE_EXISTING_SERVER0；实际后端与仅合成/mock notice provider，不启动模型。390px 显示/无横向溢出、地图名称与章、离开刷新恢复、正确 node_id 导航、三类重算不增、失败“地图册未核对”与正文保留通过。截图 `/tmp/g8-writing-map-390.png` 已视觉检查；trace/output `/tmp/g8-playwright-results`，不入Git。测试配置 [playwright.config.mjs](artifacts/playwright.config.mjs) 使用既有解释器，避免 uv 操作共享env。
- 初次 Chromium 在沙箱内因 macOS MachPort denied 无法启动，按浏览器验收授权 escalation 后完成。发现并修复真实 router 普通 object 查询变 `[object Object]` 的错误，补点击断言；另两次失败属测试章节选择/标题定位器，与产品失败区别记录。
- `make repo-gates` [repo-gates.log](artifacts/repo-gates.log) 通过：import523/523、release-evidence通过。未提交时 binary/file-size 的 `--head HEAD` 只扫描已提交差异；补全工作树 `python3 scripts/check_file_sizes.py` [file-size-all.log](artifacts/file-size-all.log)：1093文件通过，无新增二进制（截图外置）。集成commit后需重跑增量门禁。
- `make docs-check BASE_REF=origin/main` 初次提示额外9份总览。02_world 实际地图调用块已同步；CLAUDE仅导入规则，CONTEXT/00设计地图所有权和来源边界不变，ADR索引0031标题/状态不变，architecture README/drawio/html模块/拓扑不变，12_infrastructure任务/队列/schema不变，具体无影响说明通过 [docs-check.log](artifacts/docs-check.log)。未重绘图或修改门禁。
- `git diff --check` 通过。没有对未提交实现创建Git commit。
- 发现并修复热路径风险：初版复用 `list_drafts_by_ids` 会加载最多1000章正文。主审要求本切片闭合，现已换成 `get_historical_source_identities` 的六字段SQL投影；正文和完整provenance不进入查询/返回，见下方实际投影证据。未做整体大规模性能基准。

## 文档交叠与交接

只修改本树，不写 docs-refresh 活跃树。正式文档主集成由主代理单一写入：

- `evolution/README.md`：原“全部 map unsupported”两处限缩为残余来源，末尾新增G8a正文来源核对块；可能与G2 Runtime文档叠加，仅本G8a块由本切片提供。
- `22_evolution.md` 是G8a完整权威合同，旧unsupported陈述同步限缩。world/evolution README及15_map现只保留各自职责或作者行为摘要并链接权威合同，不复制完整16行；02_world为窄port摘要+链接，不覆盖其他任务段落。
- `docs/modules/02_world.md`：当前地图连续性查询段后补新只读port语义。
- `ADR-0031`：只改 evolution-world 既有依赖表行，不新立长期决定或扩边。
- 未改共享任务索引、G2/W8代码或其他worktree。下一步主代理评审与按块集成；真实作者体验/模型质量和生产发布另需独立验收与授权。

## 主审修正：历史身份只读投影（2026-10-14T12:04:29+08:00）

- 范围：Writing `ManuscriptSourceService.historical_source_identities` 与 facade 的 `get_historical_source_identities`、World MapPort消费、Writing README/11_writing接口行，以及四份G8文档收敛。没有新表/通用repo/配置/原Draft契约变更，也没有函数级跨模块import增量。
- SQL只查询 `id/chapter_index/version_number/content_hash/status` 和 `provenance_json["deprecated_from_status"].as_string()`，不查询title/content或完整provenance；复用active-project owner+novel门禁，empty列表也先验证owner。
- 新一个大正文关键测试：100万字正文与100万字符无关provenance，捕获实际SQLAlchemy执行select的六个selected_columns，返回仅6字段且<300字符；同query请求外部作品ID不返回，empty列表正常，foreign owner拒绝。
- 当前版本 targeted pytest：Writing test_manuscript_source/test_manuscript_source_port + Evolution test_map_consumption/test_consumption_registry，[metadata-tests.log](artifacts/metadata-tests.log)：65 passed/1.78s；此前地图正常/empty/owner/novel/stale/伪造/SAVEPOINT等证明均保留。
- 新JSON单键SQL投影另跑现有合成PG地图专用（未重复95 critical或全部522/UI）：[metadata-postgresql.log](artifacts/metadata-postgresql.log)，1 passed/0.32s，真实SQL错误SAVEPOINT证明仍通过。
- 全lint [metadata-lint.log](artifacts/metadata-lint.log)、import gate [metadata-import-gate.log](artifacts/metadata-import-gate.log) 通过，65边/9双向/0顶层双向/523函数级不增；docs-check（已同步11_writing，其余总览具体无影响说明）[metadata-docs-check.log](artifacts/metadata-docs-check.log) 通过；git diff --check通过。
- 原522/95/54/浏览器2属于主审修正前较广工程回归，不能冒充本修正全部重跑；本次按明确要求只复验受影响Writing/MapPort与SQL/lint/docs路径，集成HEAD由主代理最终验证。无commit/push/PR/merge/deploy/真实LLM或真实数据。

## 集成fast层的fixture整改（已完成）

- 主代理集成首轮36失败/7712通过；2个导入棘轮属G3/G8叠加实际522，由主集成调整，本树保持523。34个NotFound定位到测试准备：Writing正向published测试和Imports两份项目fixture只有随机UUID没有Project；公开demo seed创建foreign source owner的作品却以默认fixture principal发布，连带opening测试；另一个修改演示稿的seed也需真实作者principal。
- 只修fixture：Writing sample_draft_data改为test_project_id，五个真实Facade正向用例用真实Project，项目统计中的第二项目经project_factory创建、missing ID负例保留；Imports两份fixture各自用project_factory建立独立项目（保留原两ID不同的语义）；公开demo两个发布seed仅在正确source owner的作者principal下执行并finally恢复。生产owner gate及已有隔离/404/幂等/正文断言未改，不用system/Mock绕过。
- 初版seed错取Account.identity_type（身份类型属于AccountIdentity），只造成14个fixture AttributeError；已改为同文件/Opening测试既有的local作者principal模式，保留真实owner/account行。

- 失败文件全回归 `test_writing.py/test_imports.py/test_scene_commit.py/test_public_demo.py/test_openings.py`：174 passed/4.57s，已消除34个首次集成NotFound路径。AST核查原断言数不变：Writing206→206、public_demo57→57；无fixture断言删除。全ruff通过；当前完整fast/backend使用2workers、coverage和`-W error::RuntimeWarning`，尚在执行。
- 真实生产调用核查：published写端为Writing发布/恢复，以及Imports普通导入/source_update；Imports公开API持active author门禁，source_update持exclusive project门禁，InteractionSourceService冻结源明确要求author kind和owner。公开demo只读例外不能授权发布，因此seed应绑定真实source owner作者，而非放宽MapPort owner守卫。

- 完整fast第一次以共享python的Make命令行runner override执行：7754 passed/1 failed/2 skipped、coverage86.80%。剩余唯一失败是test_test_harness锁定runner契约：MAKEFLAGS将override传入make -n，使uv字面检查失败；不是业务失败，未改测试或门禁。已改为默认uv --locked runner，UV_PROJECT_ENVIRONMENT只读指向既有env、UV_NO_SYNC=1与临时cache避免同步共享依赖，完整层正在重跑。
- 分类：Writing10例、Imports10例（Scene3/导入7）、公开demo12例、opening2例，共34。未扩大合法项目kind/owner范围，主代理集成树2个导入棘轮仍由其收紧522，本树523。

- 最终默认锁定uv runner完整fast/backend：[full-fast-locked.log](artifacts/full-fast-locked.log)，7755 passed / 2 skipped / 13 warnings，coverage86.80%（要求85%），189.25s。明确使用2workers和`-W error::RuntimeWarning`，未删除/削弱runner契约断言；共享env只读且UV_NO_SYNC=1，不同步依赖。原集成NotFound全部解决，主审之前的两条导入棘轮在本树正常，本树预算523不改。
- 环境override失败日志 [full-fast-runner-override.log](artifacts/full-fast-runner-override.log) 保留作恢复证据；runner契约单独正常执行 [runner-contract.log](artifacts/runner-contract.log) 1 passed；失败路径文件 [fixture-regression.log](artifacts/fixture-regression.log) 174 passed。全ruff [fixture-lint.log](artifacts/fixture-lint.log) 通过，git diff --check通过。pytest的13条警告与首次集成日志同类（含既有SQLite GC ResourceWarning），未隐藏；RuntimeWarning按error执行。
- 本轮只新增三份测试准备修正：`backend/modules/imports/tests/conftest.py`、`backend/modules/writing/tests/test_writing.py`、`backend/modules/interaction/tests/test_public_demo.py`。production代码/owner守卫无额外变更，未跑无关G4或浏览器，未commit。正式文档无需因fixture准备变化更新。
