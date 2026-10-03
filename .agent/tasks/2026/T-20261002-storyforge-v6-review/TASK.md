---
id: T-20261002-storyforge-v6-review
title: StoryForge v6 实现核查与全部整改
status: active
created: 2026-10-02T14:20:34+09:00
updated: 2026-10-03T00:00:00+09:00
---

# StoryForge v6 实现核查与全部整改

## 恢复快照

- 实际完成：首轮 S1-S4/F1-F11、第二轮 13 项、第三轮 4 项 review 发现均已修复并提交到
  `codex/storyforge-v6-implementation`；用户 2026-10-02 授权“修好后直接提 PR”。
- 当前里程碑：已推送并开 PR #188（https://github.com/FengHuoLinShan/ai-writing-assist/pull/188），等待 CI 与评审。
- 下一步：`gh pr checks 188` 跟进 CI（Backend quality、PostgreSQL critical、前端浏览器等），失败则在本分支修复；合并、部署须另行授权。真实模型（`make test-real-kimi`）仍未运行。
- 阻塞：无。
- 工作区：本仓库同分支；同一工作树另有会话的 `T-20261002-world-relational-management` 任务记录与
  `.agent/TASKS.md` 索引行未提交，属该任务，不随本 PR 提交。
- 最后核实：2026-10-02T22:50+09:00；`origin/main` 仍为 `0d555c463`；第三轮整改提交 `a55f009a9`。

## 目标与验收

- 目标：核验 StoryForge v6 实现并修复本记录全部15项，补齐实际调用链和方案验收。
- 完成条件：全部发现有修复与关键回归证据；通过受影响测试/lint、文档/仓库门，以及涉及并发/数据的专用 PostgreSQL 验证。
- 非目标：合并、部署或付费/真实模型质量验收。提交、推送与开 PR 已于第三轮获授权。

## 上下文与边界

- 主要方案：`out/storyforge-改进方案.md`，v6。
- 主要规范：AGENTS.md、适用局部 AGENTS.md、development-guide.md、testing-guide.md、模块 README。
- 用户授权：2026-10-02 前轮 review，当前明确“全部修复”；实现由主 Agent 完成，必要的独立收尾审查按 code-review 技能仅只读委派。
- 真实数据库、用户稿件与既有任务记录受保护；验证只使用离线替身、SQLite 临时 fixture 或明确隔离环境。
- 已确认：本地 origin/main 等于审查基线；本次差异 197 文件、7493 行新增、46 行删除及截图删除。无 StoryForge 匹配的既有主任务笔记。
- 已裁定：前轮完成报告不作为验收证据；当前已完成专用PG实测，实时远端与付费模型未核验。
- 下述严重度指本轮审查优先级，不沿用方案批次级别。未发现可确认 P0，不代表全路径无缺陷。

## 里程碑与进度

- [x] 固定审查范围和方案。
- [x] 调用链核查与关键问题证伪。
- [x] 汇总两轴发现，复核严重度和来源。
- [x] 交付最终审查与验证边界。

## 决策、发现与失败

- 以报告提供的 6 commit 首提交父节点为基线，无需再询问固定点。
- 原审查阶段仅新增记录；当前用户已明确授权修复下列全部问题，沿用现有模块、schema、标准库和测试入口。

## 整改进度

- [x] F1-F3：图片目标、真实输入指纹、局部冲突恢复及 PostgreSQL 事务回归。
- [x] F4/F11：结构化能力 fail-closed 与附加模型界面恢复。
- [x] F5：按实际采用生命周期统计候选。
- [x] F6-F7：逐源正文哈希、token 与处置证据。
- [x] S1-S3：导入边界、固定 CI 比较、证据 schema。
- [x] F8/S4：四链路三档规模门、B6 可消费产物、专用库和回滚。
- [x] F9-F10：全部 RP 入口计数、示例逐出反馈。
- [x] 文档、对应回归、专用 PostgreSQL 与独立收尾核查。

## 规范轴（2 P1 / 2 P2）

1. **S1 / P1，B2 跨模块门漏拦**：`scripts/check_module_imports.py:79-88` 把包导入及任意 models / *_models 当合法；扫描不解析相对导入与 ImportFrom 成员。隔离样本 beta/services.py 引用 alpha.models、alpha.session_models、`from ..alpha.services import C`、`from modules.alpha import services` 均零问题、零豁免。违反 development-guide.md:267-273 的有限例外。修复：解析真实目标，按调用位置登记例外，禁止生产业务引用另一模块实现。
2. **S2 / P1，main push 的 B11/P8 比较空范围**：`.github/workflows/repo-gates.yml:24,34` 固定 origin/main...HEAD；main push checkout 时两者相同。等价 `--base HEAD --head HEAD` 两门检查 0 文件且成功。修复：push 用事件 before/sha，PR 用事件固定 base/head。
3. **S3 / P2，B6 字段类型没被 schema 门验证**：`scripts/check_release_evidence.py:55-80` 多字段只验证存在；capability=[]、generator_version={}、dataset.name=True、空 claims 双列表可过。主 Agent 独立 validate_payload 返回 []；子代理完整 check 也返回 ([],[])。修复：字段类型和有效边界内容的负样本，使用不可变 commit 身份。方案 B6 L204。
4. **S4 / P2，B7 CLI 无专用库保护且残留夹具**：`backend/tools/scale_gate_harness.py:207-227` 直接创建任意 URL engine、commit 合成项目/全部草稿，末尾 rollback 撤不回先前 commit。子代理纯替身证实普通 main 库本应被现有 dedicated guard 拒绝，此入口却到 engine；未实际连接数据库。修复：复用专用库校验，把夹具留在可回滚事务中。

## 方案与运行时轴（8 P1 / 3 P2）

1. **F1 / P1，B9 复用候选归给错误对象**：`backend/modules/world/world_object_image_generation.py:524-543` key 没有 entity 身份/name/type；`:587-590` 副本沿用 source.entity_id。真实 service + SQLite 探针：B 与 A 同 content_json/prompt，请求 B 返回 A 的 entity_id；adopt_candidate 又按候选 entity_id 上传，会修改 A 图片。修复：目标实体/完整生成状态纳入 key，副本明确绑定并校验请求目标。方案 B9 L157-160。
2. **F2 / P1，B9 不同地图选区碰撞**：`backend/modules/world/map_atlas_workflow.py:1893-1898` 只存 has_mask，不含 mask 内容或实际参考图指纹。相同原图/提示/修改指令，不同 mask 得到相同 key；edit 路径不 force，会复用第一次选区结果。纯哈希探针确认。修复：冻结并哈希真实 mask/参考图输入。方案 B9 L157。
3. **F3 / P1，B9 唯一键冲突回滚调用方写入**：`backend/modules/world/image_request_reuse.py:142-154` 捕获 IntegrityError 后直接 session.rollback。调用方先写的图片字节、review_ready、完成计数被丢弃，ORM 还可能过期。模拟 stale SELECT + SQLite 真实唯一约束探针：登记成功、commit 后候选仍 generating。修复：局部 SAVEPOINT 或原生 upsert，不回滚调用方事务。此证据不是 PG 并发实测。
4. **F4 / P1，B5 结构化能力门被真实调用绕过**：`backend/infrastructure/llm/client.py:1109-1125` 只在 response_format 为 None 时检查；imports adapters 多处预填 json_object。fake provider 探针：档案显式 unsupported 仍成功返回。未知模型另默认 None 放行，与方案 L262-263“unverified 一律 fail-closed”不符。修复：检查独立于显式格式参数，明确未校准模型策略，测试兼容不得放宽生产边界。
5. **F5 / P1，B3 采纳率分母重复计工作稿**：`backend/modules/writing/author_example_stats.py:61-73` 只按 provenance 识别 candidate；实际采用 services.py:775-789 把来源字段拷贝到工作稿。SQLite 按该实际持久化形态探针：一个候选完整采用，返回 candidates=2/adopted=1/rate=0.5；保存更多版本继续稀释。修复：按候选生命周期/生成身份只计一次，排除派生工作稿。方案 L106。
6. **F6 / P1，B8 正文可得仍用身份哈希**：`backend/modules/evidence/compilation/knowledge/scope.py:189-196,235-240` 只取 source 自带哈希，不消费 ContextItem.content。身份相同、正文改变时哈希仍相同且 basis=identity，真实 receipt 探针复现。修复：在逐源 materialization 边界计算正文 hash，只有正文确实不可得才标 identity。方案 L182。
7. **F7 / P1，B8 token 仍丢失且多源不可复算**：`scope.py:230-248` 多源非逐行 section 各源 count=None；`:260-266` 未传真实 omitted_item.token_count。实际 enforce_budget 探针 item.count=10，而 receipt.count=None；多源得到 [None,None]。修复：传 omitted 元数据，来源装配提供逐源 item/token，不用 section 总数摊派冒充真实数量。方案 L187。
8. **F8 / P1，B7 四链路与续写成本验收缺失**：`backend/tools/scale_gate_harness.py:146-155` / `backend/tests/e2e/test_scale_gate_low.py:59-78` 只编译未索引草稿。主 Agent 重跑 low 22章每章107 tokens、high 215章108 tokens；sections 只有 writing_objective/style_assets/hard_constraints，无 prior prose/检索内容。flat growth 只说明骨架。旧 evolution harness 未改为三档，也未挂此 nightly；检索/审校分片/任务编排和 B6 消费不足。基线 note 已明确无索引边界，不能据此称全部完成。方案 L277-284。
9. **F9 / P2，P3 普通登录 RP 漏计数**：新 `backend/modules/interaction/streaming.py:345` 只接匿名入口；普通 tasks.py:302-309 不传 metadata_invalid。真实 handler + fake generation 探针：畸形尾块完成后默认 False。修复：覆盖所有 framer.finish 入口。方案 L237-238。
10. **F10 / P2，B3 逐出没提示示例未使用**：context_compiler.py:1317-1318 使用可逐出 P3；`frontend-console/shared/contextSummaryRenderer.js:200-203` 在 section 消失后只显示“一组参考资料”。真实渲染探针的文案无“示例”。修复：保存 section 标题或给 author_examples 明确提示。方案 L100-101。
11. **F11 / P2，B5 附加模型重入不回填**：`frontend-console/vue/views/settings/GlobalSettingsView.vue:205-211` loadSecondaryModels 仅由异常重试调用，普通 onMounted :439-442 不加载，:283 初始空。Vitest mount 探针：服务端有 deepseek-flash，输入仍空；直接保存 :288-298 提交空列表清配置。修复：正常进入读取，空结果也更新显示，以已加载状态保护保存。方案 L260。

## 验证证据

- `git status --short`：开始时干净。
- `git rev-parse HEAD fe3b8d702^ origin/main`：固定头和基线已核实。
- 主 Agent 后端：model_routing + image_request_reuse，20 passed。命令前缀 `UV_CACHE_DIR=/private/tmp/storyforge-v6-review-uv uv --directory backend run --locked --extra ci -- pytest`，避免默认 uv 缓存写权限限制。
- 子代理治理/绑定 19 passed；作者示例/逐源/规模夹具/framing/绑定 37 passed；两组含重叠，不加总为唯一用例数。
- 主 Agent 前端五文件 GlobalSettingsView/ProjectSettingsView/WritingEditor/WritingView/WorldEntityImage，132 passed。
- `make lint`、前端 eslint、`make repo-gates`、`make docs-check BASE_REF=origin/main`、`git diff --check` 均通过。行数门 writing/services.py=4157、api.js=3048 是告警。
- F1-F4 四个正确行为断言失败，保存在 `/private/tmp/test_storyforge_v6_review_probes.py`；复跑：`UV_CACHE_DIR=/private/tmp/storyforge-v6-review-uv uv --directory backend run --locked --extra ci -- python -m pytest -p conftest /private/tmp/test_storyforge_v6_review_probes.py -c pyproject.toml -q`。SQLite fixture 与生成替身，无真实模型。
- F11 的前端 1 failed（expected deepseek-flash，received empty）；探针已从 tests 移出，保存在 `/private/tmp/StoryforgeReview.probe.test.js`。复跑须复制到其原临时路径 `frontend-console/tests/vue/settings/StoryforgeReview.probe.test.js` 并指定该 Vitest 文件，之后删除本临时副本。
- 主 Agent 已读后独立重跑 `/private/tmp/storyforge-v6-spec-probes.py`（SQLite 内存并禁止 HTTP）和 `/private/tmp/storyforge-v6-example-notice.mjs`，复现 F5-F10 输出。
- 主 Agent 独立 stdlib 核验 S1 的 models/session_models/包目标判定 True、S3 非法类型返回 []，以及 S2 同头比较两门检查0文件。
- 未重跑报告所称后端1571+2890 / 前端2649全量、PG e2e/critical、实际 GitHub CI、付费模型，不以旧绿色数替代本轮实测。

## 下一步与交付边界

- 前轮审查完成；当前已授权全部修复，尚未提交、推送、合并或部署。
- 完成报告校正：`out/storyforge-改进方案.md`、`out/storyforge-调研报告.md` 实际已经在 f4303b536 提交；“保持未跟踪未提交”不属实。无关 MCP 任务记录确实在差异内，本轮未改它们。
- B1 CI 接线、示例确认/转义链和静态门等已有实现和离线证据，但“方案全部完成”不成立。
- 两轴最严重项：规范轴 S1 边界门漏拦；方案与运行时轴 F1 错对象复用及 F3 调用方状态回滚。

## 整改检查点 2026-10-02T15:35+09:00

- 图片复用绑定目标并哈希真实参考图/选区；唯一冲突仅撤回 SAVEPOINT。SQLite 11项通过，新增独立 PostgreSQL 双事务竞态回归1项通过，已挂 critical 选择。
- 结构化输出只放行 supported，显式 JSON 不能绕过；fake provider 测试显式声明能力。已修两项默认 fake model schema 测试（2通过）。
- 设置正常载入、空列表回填、失败禁止保存、仅当前连接可编辑、草稿离开保护；前端两文件42项通过。
- B8 正文 hash、omitted token 与多来源关联已补；不可分整块保留 shared token_groups，复算按 group key 去重，不冒充独立 token。
- B2 相对/包成员解析已实现，旧生产 models 直引迁至 Project/Assistant/Interaction facade；唯一新增窄豁免为 World ORM metadata 兼容出口。治理/证据/本机/RP定向50项通过。
- B6 类型/完整 SHA/claims/仓库相对文件约束已实现；B11/P8 CI 使用事件 fixed SHA。
- 专用临时容器 novelcraft-storyforge-v6-fix-test，端口53088，库 storyforge_v6_test，无卷，Alembic到20261002_candidate_request_hash；不触及 ai_novel_acceptance_guimi。结束仅停止该容器。
- B7 已接真实索引、SQL回读/编译、真实审校分片/请求和已有六步影子演化 harness；CLI专用库guard及外层回滚。正在修旧 harness 拒绝探针的 Scene 精确边界后定标。产物 /private/tmp/storyforge-scale-{low,mid,high}.json，不含付费调用或用户原文。
- 未提交/推送/合并/部署。

## 整改检查点 2026-10-02T15:58:28+09:00

- 原15项均已实现，三档完整索引四链路 PG 阈值4项通过，隔离数据库/账户数量无残留；真实图片竞争及复用时间写入1项通过。
- 独立 Standards 0问题；Spec唯一P2指出正文位置探针绕过 Context renderer，已改正式renderer并重跑上述5项通过，正在确认复核。
- 首轮全快速层6522过/17失败：真实缺陷为cost_routing用作者专用get_project拒绝隐藏RP（7项）；其余测试替身未声明strictstructured能力。已支持hidden owner/active context，并仅将测试替身显式建calibrated profile；Kimi纯fake传输声明supported不修改生产注册表。受影响组91项+相关19项通过。
- 首轮PG critical37过/2新库迁移失败，查到 reused_at ORM无时区/migration带时区。已对齐DateTime(timezone=True)，6个新库迁移检查全过；再次PG critical正在运行。
- test-ci第二轮正在运行，日志 /private/tmp/storyforge-fix-ci-final.log；PG /private/tmp/storyforge-fix-pg-critical-final.log；规模最终证据 backend/.test-artifacts/scale-{low,mid,high}.json（git忽略）。
- 文档/docs-check与门禁同步；无提交/推送/合并/部署，真实模型/作者验收未执行。

## 最终交付 2026-10-02T16:07:12+09:00

- 已修复规范 S1-S4 和方案/运行时 F1-F11；额外修复隐藏RP路由作者类型误判、image_request_reuse.reused_at ORM/migration时区不一致及规模探针真实renderer旁路。测试替身显式声明结构化能力，不放宽生产supported门禁。
- `make test-ci TEST_WORKERS=2` 完整通过：backend fast 6540 passed / 15 skipped / 13既有pytest marker警告，deploy guards271 passed，前端209文件2653 passed；backend/frontend依赖audit、lint、secret-hygiene及docs通过。第一轮失败事实与修复记录保留在上文，不用它宣称终态。
- `make test-postgresql-critical ARGS=-q` 39 passed；三档四链路与实际图像竞态/reuse时间写入另5 passed。新库迁移6 passed。均使用明确专用容器库与合成语料，无真实作品/付费模型。
- `make repo-gates` 四门通过（writing/services.py 4157与api.js 3048为预期行数告警）；收尾 `make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过。
- 最终三档B6产物：backend/.test-artifacts/scale-low.json、scale-mid.json、scale-high.json（git忽略）；schema、逐文件hash、HEAD可达验证通过。low/mid/high分别22/66/215章，索引115/343/1157块；固定2000字符正文输入位置增长1.0502/0.9994/0.9879，当前正文长度增长曲线单调。报告明确词法检索/确定性模型替身/六步影子链边界，不宣称向量、文学质量或真实token收费。
- 独立 Standards 与 Spec 最终均无未解决发现；Spec提的唯一renderer计量P2已修并复算等于真实请求3716 tokens。
- 专用容器novelcraft-storyforge-v6-fix-test已停止并由--rm移除；其余容器、真实验收库、worktree和WIP未操作。
- 交付状态：本地工作树完成；未新增commit、推送、PR、合并或部署。真实模型/盲评/作者验收未执行。

## 第二轮 review 整改检查点 2026-10-02T21:20+09:00

用户对本工作树（上节 S1-S4/F1-F11 未提交整改）又做了一轮 review，本轮修复其全部发现：

- **P0 路由/信封能力拆分**：`run_managed_generate/structured` 新增 `routing_capability_id`（B5 按子能力选模型），`capability_id` 仍只作信封归属（root 或 infrastructure.*）。imports 四处调用点（workflow_llm_adapters 2 处、scene_entity_llm_adapters 2 处）改传 routing 口径，深度导入 Phase1a/1b/2、场景实体/别名抽取在 `imports.deep_import` 根下不再触发 AIRunIdentityError。回归：test_agent_step_harness 新增双口径用例（路由生效+归属 root+子能力误传仍拒）。
- **P1 结构化门禁三态**：`client.generate_structured` 只对显式 `unsupported` 失败关闭；`unverified`/None 剥离 response_format（含调用方预填）走提示词 schema+修复链，Kimi k3 等 RP 摘要/导入抽取恢复可用；`supported` 照发 json_object。路由候选 fail-closed 保留并加强：`verified_secondary_models` 同时要求 structured_output=supported。能力声明注释、LLM README、docs/modules/12 同步。
- **P1/P2 示例预算统一**：`_AUTHOR_EXAMPLES_MAX_TOKENS` 1500→4000，单条 schema 满额示例（2000 字+500 注）必完整注入；部分丢弃在 section 标题与正文明示保留/未容纳条数。测试改为按新预算校准并新增单条满额注入用例。
- **P2 地图复用提示**：MapWorkspaceView 渲染 `evidence.image_reuse`（role=status + 重新生成直达按钮，走既有 regenerate 强制绕复用路径）；新增正反两条 Vitest。
- **P2 证据时间炸弹**：check_release_evidence stale 默认 WARN（`--stale-fails` opt-in），PR 不再因日历变红；方案 B6 原文即"标 stale"。测试与 docs/evidence/README 同步。
- **次要**：author_example_stats 补 canonical 状态、N+1 改单查询批量；AuthorExampleDialog 补 Esc/Tab 焦点锁定与焦点恢复（3 条新测试）；metadata_invalid 改真计数并按 incomplete_tail/parse_failed 分账（framer 重复 finish 不重复计数）；二进制门禁体积全改读 Git 对象库（head blob/merge-base/重命名旧路径，纯重命名 delta=0）+ EXEMPT 注释更正；Makefile .PHONY 去重（66→63）与 repo-gates 注释补 B6/B2；token_groups 单源上限 32+__overflow__ 折叠；`backend/tests/e2e/test_image_reuse_concurrency.py` 已 `git add` 纳入跟踪。
- **附带修复**：generation.py `prepared_see_sea_step` 拼写与使用处统一（改名 `prepared_sea_step`；本轮编辑曾造成绑定/使用不一致的 NameError，interaction 20 例复现后修复）。
- 验证：infrastructure/llm + imports 1076 passed；evidence+unit 定向 694 passed；interaction 187 passed；tests/unit+story 1653 passed；`make lint`、`make repo-gates`（行数 WARN 为既有）、`make docs-check BASE_REF=origin/main`、`git diff --check` 通过；前端 eslint 定向干净、vitest 210 文件 2658 passed。真实付费模型（test-real-kimi）未运行。
- 仍未提交/推送/合并/部署（沿用上节边界）。

## 子代理双轴审查 2026-10-02T21:45+09:00

按 code-review 技能并行只读委派 Standards/Spec 两子代理（范围=本轮清单，上轮 S/F 层为上下文）。

- Standards：硬违规 0；判断性意见 4 条（metadata_invalid bool+reason 参数结伴、incomplete_tail/parse_failed 字面量跨模块映射、unverified 归一化散布 client/model_routing、check_binary_growth.is_binary_file 成死代码仅测试引用）——均记录不阻断。
- Spec：13 项发现全部落实、无漏项/做错/越权/测试虚报；两处轻微残留：①client.py `_repair_structured_format` 无条件发 json_object，与 unverified 剥离口径不一致（HEAD 已有、本轮声明覆盖它）；②.PHONY 计数口径 67→64 非 66→63（实质一致）。
- 主 Agent 复核采纳①：新增 `LLMClient._structured_json_mode_supported` 共享三态判定，修复链 response_format 按口径发/不发；新增修复链回归（unverified 两次 generate 均 response_format=None）20+804 例、lint、repo-gates 复验通过。②仅记录。is_binary_file 保留（测试引用且为工作区探针工具函数）。

## 第三轮 review 整改检查点 2026-10-02T22:30+09:00

用户对第二轮整改再次 review，并授权“修好后直接提 PR”。先把前两轮未提交整改单独提交（`548992154`），再修本轮发现：

- **结构化 JSON 模式回归（第二轮引入）**：`unverified` 曾剥离 `response_format`（含调用方预填），v4-pro/Kimi/通义失去 main 既有的 json_object。改回 main 行为：`supported`/`unverified` 发 json_object 并尊重预填，修复链同样发送；仅 `unsupported` 失败关闭。`unverified` 只影响 B5 路由候选资格。删掉随之无用的 `_structured_json_mode_supported`；两条三态测试改为断言 json_object；LLM README、docs/modules/12、capabilities/model_routing 注释同步。
- **RP 尾块无效重复计数**：最终 checkpoint 已提交计数后，审查/释放/收尾抛错会在失败路径再计一次。framer 增加 `mark_metadata_invalid_persisted()` / `metadata_invalid_unpersisted`，普通任务与匿名流四处失败路径改用后者；新增 handler 回归（已落账不重复、checkpoint 自身失败仍计数）。
- **作者提示进模型正文**：部分丢弃的“可精简示例”提示从 section 正文移到 `bundle.warnings`（确认预览可见）；模型提示词标题来自固定 `SECTION_TITLES`，section.title 仅作者可见，保留。
- **token_groups 溢出**：overflow key 改为 `__overflow__:<source_key>`，共享组不再折叠（按 key 跨来源去重复算），overflow state 继承被折叠组（不一致为 mixed）；新增多来源溢出回归。
- **P0 适配器级回归**：`test_workflow.py` 新增深度导入信封下 `_run_deep_import_structured_call` 路由与归属用例；已验证把参数改回 `capability_id` 时该用例以 AIRunIdentityError 失败。
- 验证：`make test-ci TEST_WORKERS=4` 退出 0（后端 6553 passed/15 skipped，覆盖率 85.93%；deploy 271；前端 2658）；`make repo-gates`、`make docs-check BASE_REF=origin/main`、`make lint`、`git diff --check` 通过。未本地运行 PG critical/e2e 与真实模型。
- 交付：提交 `a55f009a9`，推送分支，开 PR #188；未合并、未部署。

## 复审修复 2026-10-03

用户授权对 PR #188 只读复审（勿回退契约四项、S/F 与 B1-B11 全部落实）后转修复模式，修 4 项（仅本地提交，未 push）：

- **B8 第 4 点（原 B4 回归）补齐**：`tests/unit/test_per_source_evidence.py` 新增 `test_generation_request_is_rendered_from_confirmed_sections`——用与 `ConfirmedAIActionService.prepare` 相同的真实渲染器冻结确认渲染，确认后制造资料漂移（改内容/新增/删 section），fake LLM 断言出站请求含冻结渲染的全部 sections 且无任何漂移内容。
- **scale_gate 首轮定标 KeyError**：`tools/scale_gate_harness.py` release_evidence 的 `orchestration["scenes_run"]` 改 `.get(..., 0)`，退化报告不再崩 CLI，证据门仍拦。
- **nightly 规模门对齐方案（nightly 只跑低档）**：`tests/e2e/test_scale_gate_low.py` 参数默认 `["low"]`，`SCALE_GATE_ALL_TIERS=1` 显式全档（沿用 test_interaction_long_context_real_kimi 的 env 开关惯例）；workflow 无需改动。本地 PG 5207 专用一次性库 `storyforge_scale_low_test`（迁移到 head 后实跑 low 档 2 passed：22 章/115 块/增长 1.0485/基线全过，跑完已 drop）。
- **build_cost_routing 消重复查询**：`_resolve_project_runtime_profile` 改返回 4 元组（附 context），`build_cost_routing` 增可选 `project_context` 预载参数，`open_project_llm_client` 与执行快照复用同一 context（顺带消除快照内 interaction 分支的重复 get_project_context）；省略参数时行为不变。
- 验证：定向 66 + project 模块 152 + harness/tasks 184 passed；改动文件 `ruff check` 全过、我方新增行 ruff format 干净（两文件 HEAD 既有行本就非 format-clean，未顺手重排）；未跑全量与 PG critical。
- 四项勿回退契约未触碰；`.agent/TASKS.md` 与 `T-20261002-world-relational-management/` 属另一任务，未 stage。
