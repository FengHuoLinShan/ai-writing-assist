---
id: T-20261004-ask-world-quality
title: 问世界观模型质量诊断收尾（旧 WIP 迁移、语义审查层、校准与入口验收）
status: completed
created: 2026-10-04T00:00:00+09:00
updated: 2026-10-05T12:00:00+09:00
---

# 问世界观模型质量诊断收尾

## 恢复快照

- 实际完成：P0迁移、P1语义审查/provenance、P2候选集与教师校准自测、P3确定性API/前端回归、P4文档；均本地未提交。
  本轮主Agent逐条裁定六条原debug失败（五条分歧是其中子集），标准与理由见 `artifacts/debug-adjudication.md`。
  有来源的同主体补充可通过；真实缺口可说明，不能否认已给出的方向、属性、版本关系。Agent裁定本身不是真人校准；用户随后对46条真人核对包回复“同意”，独立收据见 `artifacts/human-calibration-receipt.json`。
- 历史报告/账本：`artifacts/deepseek-debug-result.json`、`deepseek-debug-ledger.jsonl` 保留；原v2 28条22/6教师判定是旧rubric结果。
- 新结果：`artifacts/teacher-selftest-v3-result.json` 30条预设判定全部吻合；`artifacts/debug-rejudged-v3.json`
  用新rubric复审既有28个生成输出，24 pass / 4 fail，四条fail与主Agent裁定吻合。只重审，未增加DeepSeek调用；
  报告明确 `split=debug-replay`、v3所需34条还缺6个生成，不冒充完整debug，也不能作为holdout放行证据。
- 数据修复：原教师自测用了v2 holdout六个族，原“未跑holdout”仅指DeepSeek未跑。v2保持不动；v3=46条，
  debug34/holdout12，六个已暴露族降debug，补六个新族，其余六条未暴露保留原样；v3把archive-stale的机构/地点误标冲突纠正。
  新自测只选debug并硬断言；没有查看/运行保留集输出。
- 冻结保护：分层数据集不许省略split；holdout必须绑定完整debug/通过自测、数据/runner/Prompt/rubric、教师参数和
  实际model/profile。独占启动标记按保留集实际问题/证据材料hash放在固定eval .cache，复制freeze、只改debug/参考不能重跑；
  holdout教师attempts=1。PostgreSQL探针先SET TRANSACTION READ ONLY再读owner模型连接，不检索正文；这不等同库审计。
- 环境：Homebrew Codex0.144.6遮住npm0.160.0，教师首次复跑以unsupported model失败；仅进程PATH优先已安装npm版后成功，
  仍gpt-6.1-sol/high，不改账户配置。DeepSeek代理1082不监听的历史情况只允许进程LLM_PROXY_URL空值，.env未改。
- 当前验证：前端RagSearchView 28 passed；最新后端定向156 passed（含50项eval与一次性材料身份反例）。
  Ruff check/format、ESLint、secret hygiene、git diff --check与离线Ask World门禁通过；docs-check通过，
  BASE_REF检查使用已确认的本地no-change-reason通过。两个独立轴复核都无残余缺陷，见 `artifacts/review-resolution.md`。
- 最新实测：完整v3 debug34条确定性全过，教师32 pass / 2 fail（archive-stale、guard-captain-conflict，均已知生成层失真）；参考接受率1、歧义0。
  `artifacts/holdout-freeze.json` 绑定已通过30条自测与完整debug及代码/Prompt/rubric/模型；一次性holdout12条确定性与教师语义全部通过，未据此调参。
  新46次生成费用估算0.007039671美元，旧28条费用未知；完整累计账本在仓库外私有目录。
- 已完成：用户对46条合成核对包回复“同意”，对四项真实浏览器结果回复“四项均符合预期且有帮助”；两份收据独立保存。
- 下一步：无必需剩余工作。若用户授权提交/PR，按最终本地差异交付并重跑提交态门禁；当前不自动提交。
  四类真实浏览器验收已通过，见 `artifacts/browser-acceptance-result.json`；窄屏390×844通过并已复原。
  本轮62次付费请求全部有用量结算，估算0.036511773美元，保守计价0.1045965美元；旧28条与CLI教师费用仍未知。
- 2026-10-05 提交授权兑现：用户授权提交/PR。本地差异按三个逻辑提交落盘（d9a71c774 生产修复与回归、
  2714e5b13 语义审查层与数据集 v2/v3、24bb4e7c1 任务记录收据），推送 `codex/ask-world-quality` 并开
  PR #196（未合并）。提交态重跑：`make repo-gates BASE_REF=origin/main` 通过、`make eval-ask-world`
  exit 0、`make docs-check BASE_REF=origin/main` 以 architecture-governance no-change-reason 豁免通过
  （理由同 PR 模板：仅新增手动非阻断 Make 目标与 eval/测试代码）。合并/部署仍待另行授权。
- 2026-10-04 最新授权：用户明确“不设预算上限，继续做完”。预算阻塞解除；新费用账本记 cap_usd=null，
  旧28条因未记录用量/费用保持 unavailable，不伪造零费用。沿用已验证owner连接与同一累计费用记录。
  真人与作者反馈随后实际收到，分别保留本批核对与四项用途范围；不由Agent结果代填。
- 浏览器：隔离当前分支8017/8087通过直接回答、跨来源组合、精确属性缺失拒答、收窄确认范围后拒答；原文/世界对象来源均回开。
  停止/切项目迟到回答、显式逐项排除与建议保存的失败/防重在离线回归验证。受保护项目按生产流程记录确认、检索诊断与AI快照（未作数据库审计），
  未保存建议或编辑正文/世界资产、未重建库；原共享服务8080/8000与理法之环页保留。临时服务在作者验收后停止，原共享服务保留。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-ask-world-quality`，`codex/ask-world-quality`，
  基线 `229491796b9b05fb753c02b8aa2168cbb11c04e4`。df37旧WIP及主仓ring导入/写作UI WIP均不改。
- 交付边界：无提交、推送、PR、合并或部署；任务已完成验收并从开放索引移除，保留全部任务证据。

## 目标与验收

- 目标：让作者能可靠区分“有依据的回答”“来源冲突”“证据不足”，并能回开来源核对。
  服务画像 A（长期维护小说设定的作者）；真实作者价值未验证。
- 权威计划：[artifacts/remaining-plan.md](artifacts/remaining-plan.md)（P0–P4 验收，原文来自旧 worktree
  `docs/superpowers/plans/2026-10-04-ask-world-remaining-plan.md`；主线已把该目录归档，故存于本任务目录。
  其“恢复快照与已有进度”已过期，以本文件为准）。
- 完成条件：按计划各阶段验收；真实模型、真人、浏览器验收与工程测试分别报告。
- 非目标：全世界观系统、RP、Scene 生成、通用 provider 升级、新基础设施、新增生产接口。

## 上下文与边界

- 稳定边界：`/api/world/ask-world`、citations/open、suggestions；Evidence facade；项目 owner
  的 LLM runtime。不改 wire/schema/数据库/依赖。
- 授权：用户要求执行计划，并明确要求恢复后裁定标准、重跑自测/debug、再一次性跑 holdout。
  既有模型保持；最新用户授权本任务不设费用上限。未授权提交、推送、
  PR、合并或部署。Agent 审查不替代真人与作者确认。
- 已确认事实：主线 `AskWorldService` 已含精确属性拒答 Prompt、确认资料约束与 `_govern_answer`
  知识审查；探针数据集 `ask-world-model-probes-v1.jsonl` 已在主线。
- 假设：模型诊断保持手动、非阻断；7 条样本不构成统计结论。

## 里程碑与进度

- [x] P0 迁移：runner/测试/Make 入口/README 入主线；docs-check 与离线 gate 通过。
- [x] P1 语义审查层与 provenance：逐主张审查（supported/attribute_matched/answer_consistent/
  answerability_justified/conflict_presented）汇总为 `semantic_review`；case 语义通过须“审查全过 +
  确定性前提成立”，审查不能覆盖确定性失败；无审查记录写 `available=false`；报告含 git commit/
  dirty hash、系统 Prompt hash、数据集/rubric hash；生成或教师阶段失败为 `complete=false`，
  启动时覆盖旧报告为 `running`，中断为 `aborted`。`case_pass_rate` 更名 `deterministic_pass_rate`，
  `quality_scope` 更名 `model_answer_source_set_diagnostic`（无其他消费者）。
- [x] P2 离线部分：`ask-world-model-probes-v2.jsonl` 40 case（7 锚点 + 33 新，六层，24 可答/16 应拒，
  holdout 12、debug 28，来源族不跨 split）；schema 增 `source_conflict/stratum/family/split`。
  v1 的 3 条冲突 case 补 `source_conflict=true`。参考答案未经人工核对。
- [x] P2 真实部分：旧28条debug保留；修订rubric的教师自测30条全部吻合、旧输出重审24通过/4失败。
  完整34条debug教师32/34通过；冻结后一次性12条holdout教师全部通过，原始教师报告均human_validated=false；用户对独立46条核对包回复同意，收据单独保存不改冻结报告。
  已加 `--ledger`/`LEDGER=` 保存每个 case 的模型输出（报告本身不存生成正文），供人审与教师对照。
- [x] P3 离线确定性回归：盘点后补 7 个后端用例与 1 个前端用例（见“决策、发现与失败”）；无生产代码改动。
- [x] P3 浏览器/真实模型/作者确认：四类浏览器及引用回开、窄屏通过；用户确认四项均符合预期且有帮助，收据见 `artifacts/author-acceptance-receipt.json`。
- [x] P4 门禁、文档与收尾检查：见“验证证据”。语义门禁不建立（计划要求人工校准后再议）。

## 决策、发现与失败

- 2026-10-04 P0 逐文件取舍：
  - `backend/evals/ask_world.py`、`backend/evals/tests/test_ask_world.py`：迁移（主线文件与旧基线
    一致，补丁干净应用）。
  - `Makefile`：迁移 `eval-ask-world-model` 目标与 `.PHONY`，手工合并（主线 PHONY 已变）。
  - `backend/evals/datasets/README.md`：手工合并探针章节；补充“只诊断 `_generate`，不含检索、
    确认、`_govern_answer`、回开与保存”的边界。
  - `ask_world_service.py` Prompt 微调、`test_world_generation_center_api.py` 断言、
    `Prompt体系设计.md` 说明：弃用——主线已有等价的精确属性拒答规则，重复加入会改变生产 Prompt。
  - `.zcode/`：不迁移。
- 旧探针直接调用 `_generate()`，主线 `ask()` 在其后还有 `_govern_answer`；因此探针结果只代表
  生成层。

- 2026-10-04 变异检查：临时去掉 `answerability_mismatch`/`conflict_sources_not_covered` 两个确定性
  前提后 `test_semantic_review_cannot_rescue_a_deterministic_failure` 失败，已还原。
- 2026-10-04 P3 盘点（Explore 子代理报告，已逐项对照代码核实）：补测前缺 来源漂移 409、引用 stale
  回开、带确认的端到端、非 owner 隔离、`response_hash` 篡改、前端保存防重/失败保留。
  - 新增后端（`modules/world/tests/test_world_generation_center_api.py`）：回答期间页面被另一会话
    改写→409 且 snapshot=failed、零 suggestion；页面编辑后回开→`stale` 且返回当前正文；篡改
    answer/claims/uncertainty/question 任一→409 且零写入。
  - 新增后端（`modules/world/tests/test_ask_world_confirmation_api.py`，不跳过确认预检）：确认缺失
    /动作错配/他项目确认→400 且模型零调用；确认后页面被改→409“AI 参考资料已变化”且模型零调用；
    钉选页+显式排除页→模型输入与引用只含钉选页、trace 含“已排除未出现在本次确认资料中”；
    另一账户对 ask/回开/保存三入口均 404 且零写入。
  - 新增前端（`RagSearchView.test.js`）：保存期间重复点击只提交一次；失败后回答保留、提示正确、
    按钮恢复并可重试成功。
  - 变异检查（均已还原生产文件）：去掉 `_revalidate_sources` 与 `response_hash` 比对→两个后端用例失败；
    去掉确认来源过滤/三入口 `require_active_project`/确认指纹比对→对应三个用例失败；仅去掉前端函数内
    防重时测试仍过（按钮 `disabled` 已兜底），连同 `disabled` 一起去掉才失败，说明两层冗余。
  - 发现：`world.ask` 确认若 `scope=generation_center` 则 `selected_asset_ids` 不含世界书页，所有来源
    被过滤成拒答；前端实际用 `scope=full`。测试夹具须按前端形状（`full`、`budget_tokens=12000`）
    构造确认，页面经 `pinned_refs`（world_bible_page target）进入确认。同时把 RAG 打成空会令确认
    侧编译拿不到页面，故测试用钉选而非检索。
  - 发现（非缺陷，未改）：后端 `save_ask_world_answer` 无去重，同一答案连续显式保存会得到两条
    pending suggestion；前端 `savingWorldAnswer` + 按钮 `disabled` + `answerSaved` 已阻止同页重复，
    跨标签重复只产生可单独忽略的待处理项，不写正式世界书。不增加后端幂等，避免借评测任务扩大契约。
- 2026-10-04 P4：`backend/pyproject.toml` 的 pytest `testpaths` 含 `evals/tests`，`make test-fast-coverage`
  已收集 Ask World eval 离线测试，无需改 CI；`backend-ci.yml` 对 `make eval-ask-world` 为 push 非阻断。
  `make docs-check BASE_REF=origin/main` 因 Makefile 变更触发 architecture-governance，审查
  `documentation-maintenance.md` 与架构 README 后用 `--no-change-reason` 本地确认，理由：仅新增手动非阻断
  Make 目标与 eval/测试代码，已同步 development/testing guide，无模块边界/接口/数据模型变化。
  PR 描述需勾选模板中的同一豁免并附理由。
- 2026-10-04 教师改为 `gpt-6.1-sol`/`high`（用户指令，替代 5.6 sol/medium）：`ASK_WORLD_TEACHER_*` 常量、
  CLI choices、数据集 README、testing-guide 同步；仍是校验型白名单，不接受其他教师。CLI 0.153.4 下首次尝试
  因模型不被通道支持以 400 失败（无 token 消耗）；随后 `gpt-5.6-sol` 一次 4,710 token 的 “ok” 探针只用于判断
  通道，不是教师结果。用户授权后 CLI 升到 0.160.0，`gpt-6.1-sol`/`high` 可用，自测结果见恢复快照。
  DeepSeek debug 输出见恢复快照；两次运行中第一次因本地代理未启动失败，无有效输出。
- 2026-10-04 教师自测只作 rubric 灵敏度/特异度的初步检查：未据其调整 rubric，rubric hash 保持
  `3f797f65…`，holdout 尚未运行。
- 2026-10-04 环境：`frontend-console` 执行过 `npm ci`（仅 gitignored 的 node_modules，锁文件未变）。
- 2026-10-04 设计取舍：探针不保存生成正文，故语义审查按 `claim_index` 逐条记录而非存主张文本；
  `ambiguous`/`reference_disputed` 计为未通过但不使聚合不可用，`unreviewed`/`invalid_review` 则使
  `semantic_pass_rate` 不可用。v1 仍为默认探针数据集，v2 经 `DATASET=` 显式选用。

## 验证证据

- 2026-10-04 P0：`make docs-check` 通过；`pytest evals/tests/test_ask_world.py` 13 passed；
  `make eval-ask-world` 通过（基线 `229491796` + 迁移改动，未提交）。
- 2026-10-04 P1/P2：`pytest evals/tests/test_ask_world.py` 36 passed；ruff check/format 通过；
  Ask World 相关后端测试（world/evidence，`-k "ask or guimi_confirm or governance"`）25 passed。
- 2026-10-04 P3/P4 收尾：`pytest evals/tests/test_ask_world.py` + world 生成中心 API +
  `test_ask_world_confirmation_api.py` + knowledge governance + evidence 确认三套，共 135 passed；
  `vitest tests/vue/rag/RagSearchView.test.js` 28 passed；`make eval-ask-world` exit 0；
  `ruff check evals modules/world/tests/...` 通过，改动文件 `ruff format --check` 通过
  （`evals/tests/test_editorial_dataset.py`、`test_generation_runners.py`、`world_design_review.py`
  在主线上已未格式化，非本次改动）；`eslint` 改动前端测试通过；`git diff --check` 通过；
  `make docs-check` 与带豁免的 `BASE_REF=origin/main` 通过；`make repo-gates BASE_REF=origin/main`
  通过（改动未提交，HEAD 对比为空检查，提交后须重跑）。

## 交付结果

- 已交付：P0、P1、P2 合成样本实测与本批真人核对、P3 离线与真实浏览器验收、P4 门禁与文档（见里程碑）。另修复两处真实入口阻塞（见下）；无wire/schema、数据库或依赖声明变更。
- 未交付：无既定验收剩余项。工程/真实模型/本批真人核对/四项作者与浏览器验收已完成。
  语义门禁仍不建立（本计划要求另议）；46条只是本批诊断，不构成人群准确率或发布质量阈值。
- 交付边界：仅本地工作树改动，未提交、未推送；提交后重跑 `make repo-gates` 与 `docs-check BASE_REF`。
- 正式知识与后续任务：无。


## 本轮新增真实入口修复及证据（2026-10-04至05）

- 完整检索环境下重复AI重排造成预览/确认来源变化409；`ask_world`禁用可选查询扩写与重排，
  保留既有确定性query plan/RRF、来源回读、selected/excluded边界与指纹重验。
- 同章两个片段映射同一来源身份导致director重复处置异常；`world_scope_entries`按source_key去重身份，
  不同hash修订保留，全部片段正文与其完整哈希继续进入审查；不删正文。
- 不改Prompt或模型；后续生产修复不影响只调用 `_generate` 的冻结探针，runner/Prompt/dataset保持原冻结hash。
  holdout没有重跑，也不据其调优。
- 私有启动脚本起初没有main guard导致BGE子进程重复拿锁；修正后安装锁定dev依赖，复用本地BGE缓存启动。
  仅进程覆盖proxy，不改.env；这是验收脚本/运行环境问题，不是业务修复。
- 新回归129 passed（检索规划/健康/确认/生成中心）与98 passed（知识治理/确认/生成中心/Guimi），有重叠不相加。
  模块导入门禁、最终离线Ask World门禁9 API及23数据case通过；新增6文件Ruff check/format通过；
  docs-check、带本地豁免BASE_REF检查、secret-hygiene与git diff --check通过。新增产物另扫描无凭据/连接串。
- 两轴各两次静态复核无新增问题，见 `artifacts/review-resolution.md`。
- 原始实测/截图位于 `/Users/tywww/Documents/ai-writing-assist-private/ask-world-quality-20261004/`，
  仓库只存合成账本与去原文统计/哈希；费用快照见 `artifacts/cost-ledger-redacted.json`。

- 最后身份边界回归：知识治理12 passed，page_id fallback保持不同页独立；Ruff check/format与最终docs/diff门禁通过。

- 任务关闭：2026-10-05T00:11:04+09:00；作者四项实际用途反馈通过，临时验收服务停止，无提交/推送/合并/部署。
