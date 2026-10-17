# R1 契约、来源与覆盖独立复核

## Baseline 与复核范围

- 固定代码基线：`22bb499789cba89fea92e918fd853ab768688e07`（2026-10-14）。集成工作树：`/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist`。本次仅改集成树之外的本报告；正式文档和源码未由 R1 写入。
- 先读适用 `AGENTS.md` 与刷新计划 P4。按差异重点复核 Project/local_agent、Interaction、World Canon、Writing、Evidence、Evolution、DI/eval、用户指南、对象存储和 ADR 索引；只读 owning source，不把 L1–L7 报告作为唯一事实证据。
- 结构清点复核：`claims.csv` 72 项，处置为 26 updated、43 retained_with_limits、2 coverage_gap_recorded_no_test_added、1 unknown_runtime_connection_no_call。`source-coverage.csv` 1,381 路径，其中 152 项标记为 claim-linked targeted sections、1,229 项明确标记 inventory-only。该账本没有宣称逐行审计；R1 也没有独立重读全部 72 项或全部 152 个源码段。
- 以下测试只读取测试源码作为断言范围证据；未运行测试、数据库、模型或生产流量。未独立渲染图形；R1 只对照图源与 HTML 标签。

## Findings

### R1-1 — P1 — Interaction 停止后的私有 hold 保留边界（已修复并复核）

- **文档位置/旧错误：** `docs/modules/18_interaction.md:59` 原文“主动停止会清理私有运行状态”容易被读成 held 正文已删除。
- **源代码反证：** `backend/modules/interaction/generation.py:621-627` 将未释放正文追加到 `knowledge_hold["text"]`；`backend/modules/interaction/services.py:1841-1856` 在无 visible text 时将 attempt 终态化为 cancelled 并调用 `clear_private_agent_state`；`backend/modules/interaction/runtime_policy.py:71-97` 清除可恢复消息，但有意保留非空 `knowledge_hold`、预算/回执等 checkpoint 数据，注释说明 hold 正文不展示、不经 API 返回，供排查与审计。
- **影响：** 将可恢复状态清理误解为私有正文删除，会造成对停止后数据保留的错误预期；也容易混淆“可公开 partial”与“私有审计留存”。
- **最小修订：** 明确停止清除可恢复模型消息、收敛 attempt；同时写明 checkpoint 仍保留私有 hold，不通过 API 返回，也不能续跑或公开。
- **复核：** 当前 `docs/modules/18_interaction.md:55-61` 限定 partial 只来自 `visible_text`，并明说 checkpoint 保留私有 `knowledge_hold` 且不经 API 返回；与 source 一致。状态：**通过，已修复**。

### R1-2 — P2 — Canon preview 与正式 admission 的 Assertion 契约分层（已修复并复核）

- **文档位置/旧错误：** `docs/modules/02_world.md:20-24` 原文称 `world_assertions`“没有准入入口”，把 schema/preview 和提交服务拒绝合并成“无入口”。
- **源代码反证：** `backend/modules/world/authority.py:796-803` 的 `AdmissionInputValueV1` 包含 `AssertBatchInputV1`；但 `AdmissionPreviewInputV1` 在 `:969-978` 仅包括 Page 发布和 Revert。正式路由存在于 `backend/modules/world/api/canon.py:61-71`；`backend/modules/world/services/worldbuilding/world_authority_service.py:383-390` 对提交侧 `AssertBatchInputV1` 校验 wire 后以 422 拒绝，Phase 0 尚未启用。
- **影响：** “无准入入口”会让维护者以为没有通用路由或 submission schema，而不是 preview 不接、提交进入 service 后被业务拒绝。
- **最小修订：** 分开写 preview schema 支持范围与正式提交侧拒绝，并保留 `formal-disabled` 状态；不把 422 误写为 preview schema 的拒绝。
- **复核：** 当前文档明确通用 Canon 路由存在、preview 仅接受 Page 发布/Revert、正式提交拒绝 Assertion，且尚不能写 `world_assertions`；与上述 schema、路由和 service 逐层一致。状态：**通过，已修复**。

### R1-3 — P2 — 用户指南不要把模型 Key 写成普通上传/编辑前置（已修复并复核）

- **文档位置/旧错误：** `docs/product/new-user-guide.md:17` 原表格将作家路径的“需要准备什么”写成作品＋Key，容易让读者误以为无 Key 不能普通上传或手动编辑。
- **源代码反证：** `backend/modules/imports/api.py:229-245` 普通 `/upload` 入口执行 Project 活跃/owner 门禁后调用上传导入服务，没有模型 Key 检查；`backend/modules/writing/api.py:399-413` autosave 与 `:727-739` 手动更新也只经 Project 门禁和写入服务。AI 正文生成则单列于 `:416-432` 并在提交链读取项目运行时配置。
- **影响：** 对无 Key 用户夸大使用门槛，可能阻止其先上传材料或手动写作。
- **最小修订：** 表中说明普通上传/手动编辑无需 Key，模型生成、AI 整理或问答才需要相应连接，并与 FAQ 对齐。
- **复核：** 当前表格 `:17` 已区分“普通上传和手动编辑无需 Key”与“AI 操作需模型连接”；RP 列限定 AI 故事生成需连接；FAQ `:92-93` 一致。状态：**通过，已修复**。

### R1-4 — P3 — 架构 HTML 的 Mac CLI 出站标签曾比图源宽（已修复并复核）

- **文档位置/旧错误：** 初读时 `docs/architecture/module-architecture.html:406` 标为“作者 Mac CLI 租约”，比同一概念的 Draw.io 节点 `:104` 少了图片用途限定。
- **源代码反证：** `backend/modules/local_agent/image_runtime.py:60-77` 的当前正常调用入口是 `run_local_image`，并校验 `CLI_KINDS`；Project 恢复拒绝旧文本 snapshot 的门在 `backend/modules/project/llm_runtime.py:208-213`，但历史 invocation/companion 文字兼容仍保留，故图应明确“正常图片用途”并另述旧兼容范围，不能用泛化标签表达当前文字能力。
- **影响：** 图源与 HTML 同屏/交叉查看时，对作者 Mac CLI 的当前用途描述不一致；泛化 HTML 标签弱化图片-only 与旧 job 兼容的边界。
- **最小修订：** 将 HTML 标签改为“作者 Mac 图片 CLI 租约”，保留旧文字 job 兼容说明。
- **定向复核：** 当前 `module-architecture.html:406` 写“作者 Mac 图片 CLI 租约”；Draw.io `:104` 写“作者 Mac 图片 CLI 出站租约：Codex / Claude / Kimi / DSH / Pi”。两者均明确图片用途，且 HTML 运行时说明 `:466` 与 Draw.io 主图 `:70` 都保留“旧 job 兼容”边界。状态：**通过，已修复**。

## 已交叉核对且当前未发现需改项

- **Local Agent/Project：** `backend/modules/project/llm_runtime.py:195-245` 校验文本快照版本、`novel_id`、hash、原 provider 当前 Key、Base URL/`extra` hash，并拒绝旧 `local_agent` 字段；`backend/modules/local_agent/executor_service.py` 的 `task_snapshot_client` 拒绝 `_local_agent` 旧文字设置。`backend/modules/local_agent/api.py` claim 未按 image mode 过滤，`companion.py` 保留非图片 `_run_text_job`，因此模块文档限定为“新入口/snapshot fail-closed”，且将现存可领取记录留作未知是准确的；本次未查询 DB。
- **Project 图片快照：** `backend/modules/project/image_runtime.py` 与 `facade.py` 的图片运行时 seam/恢复身份条件支持 `docs/modules/01_project.md` 的独立图片 snapshot 说明。未发现其声称测试已验证 restore；相关调用测试不替代真实 Key/图片 provider 验收。
- **Writing 同键采用：** `backend/modules/writing/draft_service.py:533-604` 与 `service_support.py:390-420` 将同键重放绑定到原采用 draft，异键/无键不会作为通用 replay 成功；`docs/modules/11_writing.md` 的范围与 API query key 相符。
- **Evidence GET/POST：** `backend/modules/evidence/compilation/api.py:358-380` 和 `confirmation_service.py:206-221` 证明 GET 只读已存确认、不重编译；response schema `schemas.py:789-812` 不含 `compile_options`。同一 router 的 `:822-837` 对应 focused-search POST/GET/resume，路由前缀在 `backend/modules/evidence/api.py:8-10`。`docs/modules/08_evidence.md` 当前路径和回读/编译边界一致。
- **World 图片/备份：** `deploy/compose.production.yml:169-209,342-348` 使用单个 `minio-data` volume；`deploy/README.md:82-97` 和 ADR-0014 声明两个 bucket 8/24GiB 配额、32GiB 单盘对象数据上限及首版无外部图片备份。`docs/modules/15_map.md:198-203` 没有把数据库备份表述为图片恢复手段。
- **Evolution：** `pipeline.py:858-929,1031-1055` 先准备实际消费者输入、相同证明才查复用，预留预算后冻结 attempt；`commit.py:202-282` 最终重验 owner epoch/source/parent 后领域写入并保存 receipt；`commit.py:285-312` 的 `recover_attempt` 复用冻结载荷、不接触 provider。`world.py:1014-1079` 先 World 再关系准备，并仅在 `identity_candidates` 非空时创建关系请求。测试源码 `backend/modules/evolution/tests/test_world.py:1564` 和 `test_p4_completion.py:862` 的断言范围与 `docs/modules/22_evolution.md` 新增解释相符：总 8 calls 只证明测试中未变化的冻结关系历史可复用；组级 read-set 变化反例属于 World review groups，不是 relation-history 失效证明。未运行这些测试。
- **DI、eval 与授权：** `backend/core/container.py:20-67` 证明 `ServiceKey[T]` 以 `key.name` 转字符串容器键；生产消费点使用 `core.service_keys` constants，bootstrap 注册由 `backend/app/bootstrap.py:567` 提供，API/worker 启动调用该装配。`backend/evals/codex_executor.py:29-35,110-117` 在 Codex CLI 前拒绝新调用；`ask_world.py:868-892` 在 holdout 标记创建前拒绝，`cli.py:1820-1842` 在 DeepSeek reviewer 打开前拒绝；`ProjectStructuredExecutor` 测试只是合成 facade contract，不是接线/实测证据。`docs/adr/README.md` 只调整 ADR-0029 索引对“决策目标/旧 job 兼容”的说明，ADR-0029 正文未变，未改写既有授权。

## 未查项与验证边界

本次没有对 679 个基线文档逐文件逐行阅读；没有逐项重验证全部 72 claims 或 152 个 claim-linked 路径；没有检查个人/历史 PDF 正文、私人稿件、数据库记录、模型 Key、真实 provider、部署现况；没有运行测试、`make docs-check`、`git diff --check`，也没有渲染或目视验收图形。以上均不作为 R1 通过证据。本文四项定向反证均已反映为文档修订，并按最终集成状态回读；未发现仍待 R1 修正的上述契约错误。主代理仍需完成任务全轮格式与文档门禁。
