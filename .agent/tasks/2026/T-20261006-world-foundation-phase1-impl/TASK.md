---
id: T-20261006-world-foundation-phase1-impl
title: 远景第一阶段实施（M0–M7）
status: active
created: 2026-10-06T23:30:00+09:00
updated: 2026-10-07T14:51:27+09:00
---

# 远景第一阶段实施（M0–M7）

执行 [主计划](../../../../docs/plans/2026-10-06-world-foundation-phase1.md)。
规划决策（D1–D6）、范围与验收以主计划为准；本记录只记实施事实，不改授权边界。

## 恢复快照

- 授权：修复全部审查发现、整理本地提交、第二阶段仅做计划；补跑现有 DeepSeek 账户，沿用累计 USD 20 和旧账本。无推送、PR、合入、部署授权。
- 已修：缓存匿名禁用、全行容量与 PG 并发锁、备份排除/旧备份恢复冷启动、项目及账户权限撤销清缓存、purge 保存点；Lens REST 完整响应、角色/秘密过滤、历史来源回开、缺失来源显式；basis 仅补缺失不覆盖漂移；真实章节影响锚定；窄屏交接；只读钥匙转交/三条件锁比较及 actual/required，候选指纹/digest 绑定原试改 Grant、InputManifest 并重验。
- 新发现已修：POV 可见知识从本场 Story 角色投影读取，禁止今天的 World 知识回流；冻结 RP 来源检索不按语义相似度合并事实不同的原文范围。基线同时固定原 compiler 和原 retrieval。
- 验证：后端全量 7199 项（3 skipped）、前端全量 2792 项、定向后端 823 项、Lens/召回/条件 27 项、部署脚本 272 项通过；专用 PG fresh upgrade/check、容量并发/幂等、真实 SQL 保存点与软删恢复冷启动通过；真实 dump/restore 冷缓存通过。后端全量首轮 7195 passed / 3 门禁失败已修，最终复跑通过；前端 lint、module-import/secret/prompt 门禁通过。浏览器 3 流程全部通过（追加完整确认后改稿/重建闭环最终40.8s）；重建局限说明被刷新清空的新UI问题已修并先红后绿；PG critical 64 项（65.72s）、账户撤权缓存 66 项、历史来源 REST/投影 12 项通过；前端 lint/build 通过。
- 真实评测：全量上下文矩阵 dev 6 来源族×30轮、holdout 3 独立族×30轮；生产保留原 packet index=1，新布局不宣称获准。来源事实分章，不在每轮输入重复完整真相；第30轮强制截断后续写。固定生产 Python/harness/来源/裁判哈希，开发质量或成本失败不打开留出。
- 原矩阵 session 59628 已结束：累计1563调用，上界USD9.3664236、估计USD5.119041414（不是账单）；原dev USD9规划帽触顶导致6臂预算阻断，dev-clinic:new第30轮128 token全被推理耗尽、空正文经审查失败关闭。留出未使用。保留原freeze、report和全部失败，不将空正文阻断记为实际续写成功。专库 ai_novel_agent_e2e_rp_fullmatrix_20261007 被只读observer保留，原脚本DROP因连接占用失败；这是刻意保全付费结果，observer session2346已停止，非产品故障。
- 原账本 paid-calls.json 不重置，旧4笔usage_unknown仍按既有授权保留上界和状态；本矩阵没有新增未知收费。已冻结恢复协议并在原累计USD20内重分配：共享普通调用上界USD18、保留USD2失败额度。一次性私有恢复协议/harness固定输入、来源、rubric、baseline和配置；只对原USD9发送前拒绝及已结算空正文截断创建领域新attempt，旧task/envelope/hold不重置、已有成功结果不重跑。continue语义不能用普通retry替代，同轮未知收费/泄漏/其他质量失败禁止自动恢复。
- 工作区：/Users/tywww/.codex/worktrees/world-foundation-plan/ai-writing-assist，codex/world-foundation-phase1-plan@85fb1c7be35ae687f949863d179f5fd63c53f3c0；原 M0–M7 WIP 与整改均未提交，主工作区不动。
- 最终复审：Spec 未见新阻断；Standards 缓存证明回读失败残留正文已在共享入口立即purge，794项相关回归通过。freeze后5处候选变化逐项留证：Lens、Story状态/历史响应、状态影响作者标签，以及证明失败purge；正常有效RP输入不改变。原始冻结文件不覆盖，恢复另记协议及代码哈希。
- 下一步：私有恢复session47196（matrix-resume-run.log；matrix-resume-protocol.json）完成后整理实际质量/费用与代理作者结论，本地提交后保存第二阶段计划。未通过的第一阶段门禁不得转移第二阶段冒充完成。
- 状态 active；原失败审查报告保留，整改另存验收收据。最后核实 2026-10-07 15:45 +09:00。

## 目标与验收

- M0：固定基线、业务差距复核、真实链（普通/Agent RP、实际 embedding、冷/热路径）可复跑
  观测，冻结目标与样本族。门禁见主计划 §6。
- M1–M7 按 M0 之后的顺序推进，各自门禁以主计划为准。

## 保护清单

- 不触碰持久 Guimi 项目与真实库；测量只用显式专用库（名称含 e2e）或 SQLite 临时文件。
- 本阶段零付费模型调用（D6：USD 20 仅规划）；M0 embedding 用本地 BGE ONNX/ST 链。
- 原始测量报告 JSON 含合成语料，不含用户数据；仍不写入仓库正文产物目录。

## M0 记录

### 基线

- origin/main = 85fb1c7be（= 规划固定基线，PR #201 架构优化 + PR #202 事件软删已含）。
- `make docs-check` 基线通过（12 模块、146 ORM 表、56 task handler、16 前端路由、39 ADR）。

### 代码调查结论（M0 输入）

- RP 每轮全价成本链：`InteractionStoryContextService.compile`
  （evidence/compilation/services/interaction_story_context.py:31）→
  `RetrievalOrchestrator.retrieve`（indexing/retrieval.py:402，embedding 点 :442，
  rerank=False 硬编码于 service :230-243）→
  `NovelEvidenceService.rehydrate_manuscript_candidates`（逐 chunk 回读+三重校验）→
  `ContextSnapshotService.create_context_snapshot`（DB 写，rendered 不落库）。
- 调用方：普通 RP（interaction/generation.py:437）、Agent 补查 lookup_source
  （agent_runtime.py:220，budget≤8K，每次工具调用全价重跑）、ensemble 每演员一次
  （ensemble.py:99，≤3 次）、proactive 一次（proactive.py:131）。单轮 Agent 模式最多
  1+N+3+1 次全价 compile，无包级缓存。
- embedding 双路径：本地 bge_onnx（infrastructure/embedding/client.py:43，LRU
  sha256(text|query)=10000 条/TTL 1h，仅本地路径用）；远程 OpenAI 兼容
  （EMBEDDING_BASE_URL，无缓存，计量 honest-unknown）。生产 TEI 未接 LRU。
- 查询组装：`_source_retrieval_query`（generation.py:186）= 当前输入+回顾+最近发展，
  ≤4000 字符，逐轮变化 → 全包精确缓存跨轮难命中（与计划判断一致）。
- 索引首次填充真实链：`IndexingService.index_chapter_with_report`（chunk→persist→embed）。

### 测量 harness

- 新增 `backend/evals/rp_cost_baseline.py`（CLI：`python -m evals.rp_cost_baseline run|describe`），
  Makefile 目标 `eval-rp-cost-baseline`（`SCALES/ROUNDS/REPEATS/OUTPUT/DATABASE_URL` 可覆盖）。
  冻结样本族 seed=20261006，spec_hash=
  `2d40ed20bc8ae3df3fa83fcfb58aeccee4a5402c8ceed634339c1cbdd00a6698`（守护测试
  `backend/evals/tests/test_rp_cost_baseline.py` 钉住哈希与确定性）。
- 语料族：S=12 章 / M=36 章 / L=60 章，每章 2-3 chunk（chunker 目标 ~900 字）；
  阵容 4 角色+铜钥匙+3 地点，母题事件固定章号（钥匙交接 ch2、秘密 ch5、锁条件 ch7），
  与主计划 §3.1 验收切片对齐。查询族 6 轮 ×（回顾+最近发展+当前输入，~430 字）。
- 场景矩阵：rp_normal_fresh（6 轮新查询）、agent_requery_same（同查询×3，budget 8K）、
  ensemble_actors（3 演员视角）、budget_pair（16K/8K）、reader_mode（2 轮）。
- 计时：compile 全链 wall；RagMetrics 原始累计字段差分（embed/search/latency）；
  rehydrate/snapshot 写入进程内包装计时；EmbeddingCache hits/misses 差分；
  渲染 token 估算；索引逐章 wall（含首次模型加载）。fail-closed：降级/阻断/无 embedding
  即 invalid、退出码 2。报告写入 `backend/evals/artifacts/rp-cost-baseline/`（gitignore，
  本地私有证据）；PG 目标库名强制含 e2e/baseline 标记且 schema 须在 Alembic head。

### 首次测量结果（2026-10-06，本机 darwin/arm64，PG@5207 专用库 novel_rp_cost_baseline_e2e，
### SQLite 临时库；EMBEDDING_PROVIDER=bge_onnx，SentenceTransformer 本地缓存加载）

**PG 代表性运行（s=35 chunks / m=104 chunks，各 16 attempts，valid=true）：**

- 每轮普通 RP 编译（新查询）：s 中位 ~1010ms，m 中位 ~2035ms；渲染 ~4200 tokens（s）/
  ~2300（m，多章后预算内纳入的片段更分散）。
- Agent 同轮重复补查（同查询）：s 中位 ~810ms、m ~2089ms——仅省 embedding 差值
  （fresh ~200ms → LRU 命中 ~15ms），检索主成本全价重复。
- 首次填充：s 16.2s / m 14.1s（含 BGE 模型加载 ~10s，仅首次）；暖态 ~120-400ms/章。
- 分段归属（s attempt0）：compile 1204.6ms = search 847ms（70%）+ embedding 214ms
  （18%）+ rehydrate 13.9ms + snapshot 写 4.3ms + 其余（激活/装块/Python 评分）。
  m attempt0：compile 2079.6ms = search 2036.5ms（98%）+ embedding 16ms（LRU 命中）。

**瓶颈根因（生产路径同构，非夹具假象）：**

- `keyword_query_terms`（indexing/scoring.py:36）对中文长查询做 2-4 字 n-gram 展开：
  >8 字 token 每个采样上限 96 gram（_MAX_QUERY_NGRAMS），425 字查询展开 **812 个词项**
  （4000 字生产形查询同为 812，受 token 结构与采样上限约束）。
- `keyword_search`（repositories.py:1012）把全部词项编译为 OR-ILIKE + CASE 排序表达式：
  812 词项 × 全 chunk 行扫描，139 行小库实测单查 **~1.85s**（40 字短查询 75 词项 ~185ms），
  成本随 词项×行数 线性放大。hybrid_search 内 Python 端 812 词项邻近评分同窗重复付费。
- pgvector 向量检索本身暖态 ~6ms——检索延迟主体不是向量链。embedding 本地 CPU
  ~200ms/新查询、LRU 命中 ~15ms；回读+快照合计 <20ms。
- 结论：M3 持久缓存/同轮去重瞄准正确（整包复用可整体跳过 search）；且暴露一个
  独立于本计划的检索性能缺陷候选（词项爆炸），是否修复属于 M0 决策输入。

**已知边界：** 生产 TEI 远程 embedding 费用未测（须另行授权）；生产库行数/负载与
本机不同，绝对值仅作结构判断；SQLite 运行（python 回退向量扫描）仅作冒烟对照。

**SQLite 对照运行（同族同参，valid=true）：** s 档 fresh 中位 ~480ms、m 档全场景
~530-630ms——SQLite 的 ILIKE 执行路径显著快于 PG，进一步确认延迟主体在 PG 的
词项×行数扫描而非向量链；生产判断以 PG 运行为准。

**M0 提出的目标建议（待用户确认后冻结，主计划 §7.3/§8）：**

1. 同轮重复补查（同 query/scope）：第二次起不再重复检索/编译/回读，目标 <50ms
   （现状 ~810-2090ms）。
2. 全包精确命中（跨 worker/重启）：权限/来源复验+缓存读取，目标 <150ms
   （冷编译现状 ~1-2s），冷热包渲染正文逐字节一致。
3. 新查询 miss 路径：不劣于现状（D2 质量优先，不为延迟牺牲召回/审查覆盖）。
4. 检索词项爆炸：m 规模（104 chunks）单次 search 目标 <200ms（现状 ~2s）；
   新 embedding 约 200ms 另计，不再把该目标写成全 retrieve <200ms。
   用户已确认 D7：片段/排序允许变化，按关键证据召回、知识边界与最终 RP 质量验收。
5. 真实费用节省比例不在 M0 宣称；进入 M6/M7 成对测量后在 USD 20 预算内核实。




## 决策、发现与失败

- M0 发现 1（结构）：RP 编译每轮全价且无包级缓存，与主计划判断一致；重复补查只省
  embedding 差值，检索主成本（词项爆炸的 keyword_search）每次全付。
- M0 发现 2（缺陷候选）：keyword_query_terms 的 n-gram 采样使长查询展开数百词项，
  keyword_search 的 OR-ILIKE×CASE SQL 随 词项×行数 线性变慢；小库 139 行实测
  单查 0.19s（75 词项）→ 1.85s（812 词项）。属既有主干行为，非本阶段引入；
  用户已允许按重构思路设计并确认 D7；实现目标冻结仍见主计划 §8。
- M0 边界：embedding 仅测本地 bge_onnx（ST 后端，本地缓存模型）；onnxruntime
  后端在生产镜像可用性未测；TEI 远程费用未测（须授权）。
- Makefile 陷阱：`$(or $(SCALES),s,m)` 只返回第一个非空参数（s），多值默认须用
  shell 语法 `$${SCALES:-s,m}`。
- BGE worker 为 multiprocessing spawn：调用进程必须是可导入的真实模块文件
  （stdin 脚本不行），且需 `__main__` 守卫；harness 已满足。

### 2026-10-07 检索重构设计修订

- [RP 检索与编译重构设计](../../../../docs/plans/2026-10-07-rp-retrieval-refactor.md)
  已补入主计划 §5.4/M3；D1–D6 及 USD 20 保持。D7 来源为本轮用户明确选择，
  不是旧实测或任务记录推断。
- 已核实调用链与性能归属：keyword_query_terms 的上限按短句而非整查询；
  keyword_search SQL 同时召回/排序；RP 通用扩展读当前 World 目录，计划改用冻结可见目录。
- 设计建议：确定性完整语义输入/有界词项、PG 原生词项倒排、候选融合/原文证明、
  预算前材料/编译正文/本次回执分工。一个私有派生缓存表支持不同预算从完整材料重编译；
  保留原文回读、当前身份/来源复验与独立输出审查。
- 词项数组 GIN 为目标候选，pg_trgm 为较小实现对照；原生索引能力按 PG 官方文档核实，
  具体性能/容量、词项配额与候选上限仍需 PG 规模验证，不把新设计称为已验证实现。
- 本轮只改主计划、新设计文件和本文；既有 M0 harness/Makefile/任务索引 WIP 保留。
  未修改业务代码/ADR/schema，未重跑实测、未调用模型、未提交/推送/部署。

## M1 记录（M3 线契约，2026-10-07）

- 交付物与位置：
  - [M1 实施契约](../../../../docs/plans/2026-10-07-rp-retrieval-refactor-m1-contract.md)：
    S1 查询规划 / S2 候选召回与融合 / S3 材料物化 / S4 预算编译 / S5 使用记录五段
    （输入/输出/失败语义/版本键）；`RetrievalPlan` 契约（完整语义输入+全查询有界词项
    +配额次序，禁简单截前 N）；材料 key 与编译 key 字段规格；
    `context_interaction_source_cache` 表设计（UNIQUE(novel_id, material_key_hash)、
    consumer/source 双 FK 级联、256KiB/32MiB 应用侧门禁、SQLite 窄适配）；
    命中四步复验（门禁→完整性→证明重验→spec 匹配）；失败语义（DB 故障不吞为 miss）；
    生命周期/隐私/回退；计量口径（search 与 embedding 分开，延迟门禁引用设计 §7）。
  - [ADR-0018](../../../../docs/adr/0018-versioned-author-source-context-for-rp.md)
    增补修订：缓存例外决策级边界（按仓库 Amended 惯例块引用补充，未改原条目文字）；
    docs/adr/README.md 索引状态同步为 Accepted / Amended（2026-10-07 缓存例外，M3 落地）。
  - Evidence README / interaction README / 01_数据库设计：仅加「契约先行，M3 实施」
    指针段（数据库设计明确标注"规划中（尚未建表）"，不违反其"当前实现"章程）；
    docs/README 计划导航同步。
- 范围说明：M1 的"增量状态/依赖契约"（M2 线投影）不在本段，按主计划在 M2 启动前
  另行补足；本段完成 M3 线全部前置。
- 验证：docs-check（BASE_REF=origin/main，no-change-reason 说明 README/数据库设计
  仅指针）与 git diff --check 通过；本轮无代码改动，未重跑业务测试。


## M3 切片 1 记录（等价拆分，2026-10-07）

- 目标：按 M1 契约把 `InteractionStoryContextService.compile` 的确定性组装段等价拆为
  S3 预算前材料 / S4 按预算编译 / S5 使用记录，检索行为与四个 RP 调用方
  （generation/agent_runtime/ensemble(_v2)/proactive，全部经 facade）语义不变。
- 改动：
  - 新增 `backend/modules/evidence/compilation/services/interaction_source_material.py`：
    `InteractionSourceMaterial`（S3 纯数据：identity/reference 全量块与次序、必需集、
    知识块、必需证明 reads、全量 excerpts、warnings）+ `compile_source_material`
    （S4 纯函数：必需项优先、可选资料 continue 让位、原文证据 break 让位、超预算 blocker）
    + 块构造/渲染/stable_hash 从 service 原样搬移 +
    `INTERACTION_MATERIAL_METHOD_VERSION`/`INTERACTION_RENDER_METHOD_VERSION`
    （切片 3 缓存 key 用，行为变更须 bump）。
  - `interaction_story_context.py`：权限/进度/版本/必需证明门禁与检索、回读留在 compile；
    尾段改为构造 material → `compile_source_material` → `_snapshot_result`（S5 不变）；
    删除已搬移的静态方法与助手。三个早退路径（进度/版本失效直返、固定超进度与必需证明
    缺失走 snapshot blocker）保持原位原语义。
  - 测试：新增 `test_interaction_source_material.py` 5 条（必需优先次序、continue/break
    两种让位语义、必需超预算 blocker、同材料多预算前缀复用——切片 3 缓存重编译前提）；
    `test_interaction_story_context.py` 仅改两处 fence 测试的 import/调用点到新模块，
    断言未动。
  - harness 增强：attempt 记录 `rendered_sha` 与原始 `included_refs`/`source_refs`
    （指纹含每次运行随机的 revision/draft ID，跨运行不可比；内容摘要才是等价对照物）。
- 等价验收（PG+BGE 真实链，专用库 migrate→run→drop）：
  - A/B 方法：`git stash` 重构跑 pre → `stash pop` 跑 post，同 seed/同查询族/同预算。
  - 结果：32/32 attempt（s/m 各 16：fresh 6 + requery 3 + ensemble 3 + budget_pair 2 +
    reader 2）`rendered_sha` 逐字节一致；`included_refs`/`source_refs` 在 ID 掩码
    （uuid/64-hex→<ID>）后全等；rendered_tokens/blockers/warnings 全同。报告（本地
    不入库）：report-pre-m3s1b.json / report-post-m3s1b.json。
  - 首轮对比的教训：指纹与 refs 摘要跨运行必差（fixture uuid4），不能作为等价判据；
    第一轮 32/32 rendered_sha 已一致，差异全部来自随机 ID。
- 单测/门禁：evidence 全模块 621 passed；interaction 全模块 192 passed；public_demo/
  sources/ensemble 43 passed；新增 S4 契约 5 条 + harness 自测通过；ruff format/check
  与 `git diff --check` 干净；docs-check（no-change-reason：README 实施状态段）通过。
- 踩坑：harness 不自建库（需先 createdb + `DATABASE_URL=... alembic upgrade head`）；
  `uv run` 不钉 `--python 3.13 --locked` 会把 .venv 重建成 3.14 并拆掉依赖；
  管道 `| tail` 掩盖退出码，后台命令须 `set -o pipefail`；zsh 变量不做词切分，
  脚本内命令串须用数组。


## M3 切片 2 记录（有界查询规划与词法索引召回，2026-10-07，完成）

- 已完成 2a——S1 规划器 `backend/modules/evidence/indexing/lexical_plan.py`：
  - `build_lexical_query_plan(query, *, frozen_terms, cap=64)` 纯确定性：语义输入
    原样保留；词项 = 冻结名称/别名（规范化去重，优先）→ 按句切分（`。！？!?；;\n`）
    后跨句轮转取词（每轮各句一个新词直到总上限），晚到输入保证有席位，不做前 N 截断。
  - 句内词项次序：冻结命中 → 英文词（从保留空格的 NFKC 原句提取，紧缩会破坏词边界）
    → 中文连续段 2–4 字 n-gram（单段 >12 个按等距确定采样）。
  - `LEXICAL_PLANNER_VERSION="lexical-plan-v1"`；`normalize_lexical_term` 统一
    NFKC/去空白/小写。测试 `test_lexical_plan.py` 8 条全绿（语义不变/冻结优先/
    总上限/轮转公平/确定性规范化/去重/空查询回退/零上限）。
- 尚未接线：规划器尚未接入 `retrieve()`/`hybrid_search`（有意——先落地 2b 索引列与
  2c 召回路径，接线与旧行为同跑对照后再切换；接线点为 interaction compile 传入冻结
  目录 labels/aliases 作 frozen_terms）。
- 2b（索引侧）：
  - `models.LexicalTerms` TypeDecorator（PG TEXT[] / SQLite JSON）；`rag_chunks.
    lexical_terms` nullable，空值/空数组=词法未就绪。`_chunk_row` 单一汇聚点用
    `extract_index_terms(data.text)`（全文 2–4 字 n-gram，不套查询侧上限）填充，
    新建/替换 chunk 全路径覆盖。
  - 迁移 `20261007_rag_lexical_terms`（down_revision=20261006_event_soft_delete）：
    加列 → Python 分批回填（500/批，executemany，只改派生列不动 embedding）→ 建
    `ix_rag_chunks_lexical_terms_gin`。真库验证：升到上一 head 手工插中文 chunk 行
    再升级，78 词项回填、`&&` 命中 1/误检 0、GIN 建立；坑：executemany 行取值需
    `.mappings()`（Row 下标 str 报 tuple 错误）；psql 种子须补 accounts.support_code/
    projects.owner_id/default_reveal_policy/settings/rag_chunks.meta 等 NOT NULL。
- 2c（召回通道）：
  - `repositories.lexical_search`（PG `&&` + 元数据过滤，确定性排序 limit，非 PG
    返回空）与 `has_unindexed_lexical_terms` 探针（`array_length(x,1) IS NULL`，
    非 PG 恒 False）；`keyword_search` 增 `precomputed_terms`（跳过本地 n-gram 展开）。
  - `hybrid_search`/`retrieve`/facade `retrieve` 增 `lexical_terms` 透传：提供时词法
    通道 PG 走数组召回，未就绪/非 PG 回退同批词项的有界 ILIKE；评分直接消费规划词项
    （不再 812 项重复展开）；`diagnostics["lexical_method"]`∈{array-gin-v1,
    bounded-like-v1, legacy-ngram-v1}。interaction compile 用激活对象 label/别名作
    冻结词项构建规划传入（其余 retrieve 调用方不受影响）。
  - 单测：`test_lexical_recall.py` 4 条（precomputed 精确过滤/非 PG 空返回+探针 False/
    bounded-like 回退诊断/无词项保持 legacy）+ test_rag 落库填充断言。
- 2d（实测，冻结样本族 s/m 各 16 attempts，专用 PG 库 migrate→run→drop）：
  - 延迟：compile 中位 1539.5→68.6ms（22×），search 中位 1417.1→32.3ms（44×）；
    s 档 fresh 246ms（含 embedding）；全部场景 60–250ms、valid=true、零阻断零警告。
    设计 §7 目标（M 档 search p50<200ms、暖态全链<500ms）在本族达成。
  - EXPLAIN (ANALYZE, BUFFERS)：53 词项时数组 `&&` 5.3ms（planner 选 novel 复合
    索引 + 数组过滤，458 buffers）；pg_trgm 对照——即使建 gin_trgm_ops 索引，
    两字中文模式无可提取 trigram，planner 直接 Seq Scan（2.3ms@139 行），
    证实设计预判「pg_trgm 小实现不可靠、不并跑两套」。
  - D7 对照（vs 切片 1 基线）：32 attempts 引用激活集合、阻断、warnings 全一致；
    23/32 的差异仅为身份证明片段选中不同章节（ch31→ch13，同为 cutoff 前有效
    character-filtered 证明，D7 允许片段/排序变化）；rendered_tokens 2300→2258。
  - 遗留校准项：GIN 索引 ~33KB/chunk 偏重（139 行 4.5MB）；冻结族每次编译仅 1–2
    条有效 read，区分度有限——更大合成库的 p95/规模/并发与召回质量对照按设计 §7
    后补，不作生产外推。
- 文档同步：01_数据库设计（evidence/indexing 行登记 lexical_terms）、docs/modules/
  08_evidence.md（rag_chunks 条目）、Evidence README（切片 1/2 状态+实测）；
  docs-check 无豁免通过。


## M3 切片 3 记录（持久缓存，2026-10-07，完成）

- 交付物：
  - `compilation/models.py`：`CacheJSON`（PG JSONB/SQLite JSON）+ `InteractionSourceCache`
    ORM（UNIQUE(novel_id, material_key_hash)、expires/source 索引、consumer/source 双 FK
    CASCADE、material_bytes/compiled_bytes 容量列）。
  - `services/interaction_source_cache.py`：`build_material_key`（覆盖 owner/consumer/
    source ids、revision、anchor cutoffs、exact_manifest、可见引用/歧义/玩家身份摘要、
    pinned/excluded、resolutions、语义输入 sha、词法词项、方法版本）、
    `serialize/deserialize_material|compiled`、`InteractionSourceCacheStore.fetch/store/
    touch_compiled`（TTL 24h、材质 sha 校验、compiled spec sha 校验、256KiB/32MiB 门禁、
    PG ON CONFLICT 覆盖 / SQLite 先删后插、`_evict_expired`）。
  - 迁移 `20261007_interaction_source_cache`（down_revision=20261007_rag_lexical_terms；
    PG 真库升级验证：表/索引/FK/JSONB 全就位）。
  - compile 接线（`interaction_story_context.py`）：门禁后、检索前 fetch；命中且
    `_verify_cached_proofs`（按冻结 ref 完整契约字段重读比对）通过→预算相同直接复用
    compiled，不同则 `compile_source_material` 重裁剪并 `touch_compiled`；未命中走原
    路径并在无阻断时 store。snapshot 每次新建，审查资格不缓存。
- 测试：`compilation/tests/test_interaction_source_cache.py` 6 条——精确命中跳检索
  （retrieve spy 只 1 次）+逐字节复用+新 snapshot；预算变体材料复用（阻断不被编译
  缓存掩盖、成功变体 touch 后直用）；revision 变化换 key 重查；TTL 过期/版本不匹配
  不消费；超限材料跳过；证明漂移（sha 同步篡改）降级未命中。evidence 全套 643、
  interaction+unit 1881 全绿。
- 实施中修的 3 个真缺陷（全部先被验收测试暴露）：
  1) `_verify_cached_proofs` 原按 4 字段裁剪 ref，`SourceRangeRefContract` 要求
     version/mode/hash 等完整字段，构造必 TypeError 被吞成永久 miss——改为按契约
     字段集过滤重建（缺必需键仍 fail-closed）。
  2) `_evict_expired` 的 `expires_at <= now` 在 SQLite naive/aware datetime 上被 ORM
     session 同步评估炸 TypeError——delete 加 `synchronize_session=False`（仅 SQL 侧比较）。
  3) touch 原无条件写回（含 blocker 包），而 `deserialize_compiled` 恒置 blockers=()，
     小预算阻断会被同预算后续命中复用成成功包——阻断结果不落编译缓存。
- harness：`_segment_instrumentation` 增包 `InteractionSourceCacheStore.fetch`，attempt
  记 `source_cache_hit`，summary 增 `source_cache_hit_attempts`/`hit_compile_ms`。
- PG 真库实测（专用库 migrate→run→drop，s/m 各 16 attempts，valid=true 零阻断）：
  agent_requery_same 3/3 命中 compile 中位 9.5~11ms（精确命中目标 <150ms 大幅达标，
  重复第 2+ 次更低）；budget_pair 2/2 材料复用（8K 变体重裁剪）；fresh/ensemble/
  reader 未命中场景 62~257ms 与切片 2 持平（缓存零回退）；命中 attempts embedding
  调用为 0。报告（本地）：backend/evals/artifacts/rp-cost-baseline/report-post-m3s3.json。
- 文档同步：01_数据库设计（§3.7 行 + 规划段改已建表）、docs/modules/08_evidence.md
  （缓存表条目）、Evidence README（切片 3 状态+实测）、compilation/README（模型表 +
  RP snapshot「不长期持久化」补 ADR-0018 例外表述）、indexing/README（词法检索行/
  facade lexical_terms 签名/离线对照段改口）；docs-check BASE_REF=origin/main 以收窄的
  no-change-reason（仅剩 development-guide 等 4 份无影响项）通过。


## M2 记录（世界状态读取线，2026-10-07，完成）

- 契约：[docs/plans/2026-10-07-world-state-read-m2-contract.md](../../../../docs/plans/2026-10-07-world-state-read-m2-contract.md)
  ——`get_scene_state_view` 只读投影 + Scene Lens 对象状态展示；无新维度/DSL/时钟，M1/M2
  均不需用户决策。契约书写阶段已修两处口径：custody 平铺字段（浅合并会整块覆盖嵌套
  dict，改 `custody_holder`/`custody_owner` 顶层字段）、知识授予字段级（subject 级太粗，
  乙能看到甲的 custody_owner）。
- 交付物：
  - `story/continuity/scene_state_view.py`（约 470 行）：`SceneStateViewService.get_view`，
    契约版本 `scene-state-view-v1`，六维中 `world_valid_time`/`belief_fact_diff` 显式
    unsupported；fact/belief/observation 三层 + author/character/reader 三视角；知识授予
    只认显式 `fields` 列表且 false 标记行永不授予；reader 揭示走既有
    `get_reader_reveal_decision`（无策略=默认可见，cutoff None=全部门控）；
    `state_fingerprint`=stable_hash(checkpoint ids+source_hashes+viewpoint+contract_version)；
    响应附 `subject_labels`（实体/位置名，供 lens 展示层不读 ID）。
  - `continuity/schemas.py`：`SceneStateFactEntry`（含 possibly_false）/`SceneStateDimensionView`
    （status ok/degraded/missing/unsupported + gap_reason）/Request/Response；checkpoint
    响应补 `source_hash`。
  - 出口：`continuity/facade.py`→`story/facade.py`→`scene_source_port.py`（STORY_SCENE_SOURCE
    增 `get_scene_state_view`，方向 {evidence,world}→story 只读）+ REST
    `POST /api/novels/{id}/memories/scene-state-view`（`_require_active_project` 门禁，
    scene 缺失 404、非法视角 422）。
  - Scene Lens：`compilation/services/scene_lens.py` 增 `_get_state_view`（author 视角）+
    `object_states`（related_ids∪POV 分组、字段/位置/认知（可能误信）标记、`_display_value`
    递归以标签渲染 ID）；前端 `sceneLensModel.js` `sceneObjectStates` +
    `SceneLensSummary.vue` 对象状态区（已确认/推导徽章、空态文案「未记载的状态不会显示
    为『确定没有』」）。
- 测试：story `test_scene_state_view.py` 7 条（custody/ownership/误信三分离、甲乙授予
  字段级隔离、reader 默认可见+门控分支、fingerprint 决定性、显式 missing、非法视角、
  A01 lens 集成——lens 展示乙/甲而视图层保真原值）；lens 4 条（含内部泄漏断言保留）；
  REST 2 条；vitest 2 条；Playwright A13 空态切片 1 条（专用库 m2_lens_e2e_1010，
  30.3s 通过，库已 DROP）。story+evidence+tests/test_api 合计 1295 passed。
- 实施中修的语义缺陷（全部先被验收测试暴露）：
  1) services 注入的 `meta.event_key` 进了存储 snapshot——flatten 跳过 meta 键 +
     值过 `_clean_payload`，视图层永不吐内部指纹。
  2) 嵌套 custody 被浅合并整块覆盖（handover 事件只带 holder，owner 丢失）——契约与
     fixture 全改平铺字段。
  3) false 标记的误信行曾授予 subject 事实访问——false 行直接跳过。
  4) subject 级授予过粗——必须 payload 显式 `fields` 列表，dict[subject→set(fields)]。
  5) reader 默认语义曾按「无策略=不可见」实现——对齐既有契约默认 revealed=True，门控
     分支用 patch(autospec=True) 桩验证。
- 文档同步：docs/modules/05_memory.md（facade 条目+REST 清单）、19_story.md（对外能力
  状态视图段）、backend/modules/story/README.md（Stable seams）、
  evidence/compilation/README.md（object_states 段）；模块文档指向契约用 `../plans/`
  相对链接（首轮 `../../plans/` 被 docs-check 断链拦下）。docs-check 与
  `--base-ref origin/main`（no-change-reason：07_outline 只读消费未改、四份治理文档无
  当前架构影响）均通过。
- 已记录的缓办项：custody 浏览器走查待 M4/M5 事件播种 seam；`belief_fact_diff` 自动
  比对 v1 不支持（A02 以 world_valid_time unsupported + reader 门控覆盖）。

## M4 记录（依赖登记与失效，2026-10-07，完成）

- 摸底（两路只读 Explore + 自查）结论：事件驱动失效已全覆盖已接线路径（保存/采用
  hook→`compute_source_change` 确定性差异（同字数替换可检出）→事件 source_stale/章快照/
  checkpoint supersede/稀疏快照；重排另有 align+supersede；重建懒式 ensure）；checkpoint
  `source_hash` 是投影链指纹非正文指纹；**缺口=读时新鲜度比对不存在 + world 侧修订为
  unsupported_consumers 不传播 + RP 缓存无立即清理（仅 TTL+key 变化，索引已建无消费者）
  + fetch miss 无原因码（§7.2 要求）**。源项目归档/撤权在缓存 fetch **之前**就被
  `require_active_project` 入口拦下（摸底修正了契约草稿的认知）。
- 契约：[docs/plans/2026-10-07-m4-dependency-invalidation-contract.md](../../../../docs/plans/2026-10-07-m4-dependency-invalidation-contract.md)。
- 交付物（story）：
  - 迁移 `20261007_scene_checkpoint_basis`：`memory_scene_checkpoints.basis_json`（JSON
    nullable，不回填，down 删列）；PG 专用库 upgrade/downgrade 验证后 DROP。
  - `continuity/basis.py`：`compute_scene_basis`（≤ cutoff 的 working 稿 manifest 切片 +
    重放窗口场景结构 + CURRENT_SCENE_MEMORY_CONTRACT_VERSION）+ `basis_hash`；
    story→writing 函数内只读 facade 导入（ADR-0031 既有方向）。
  - ensure/rebuild/repair 三处循环在维度构建前算一次基线传入 `_build_dimension` →
    `replace_system` values；`source_hash` 投影链语义与幂等短路不变——短路保留旧行旧
    basis，绕过钩子的变更因此**保持**待核对标记直到事件层追上（保守扩大）。
  - `get_scene_state_view` 读时重算比对：系统行漂移→degraded+「来源基线已变化」、
    基线缺失→degraded+「缺少来源基线登记，待重建后补齐」；manual/confirmed 豁免；
    纯读不重算；`unsupported_dependencies=["world_canon_revision","map_atlas"]` 显式
    （世界正典修订不降级观察层投影，核对待走 World 复核 `_matches_frozen_inputs`）。
  - Scene Lens：`_read_state_view` 单次读取共用；`scene_world_state` 卡片带 `stale`
    （行 ready 但视图 degraded）；前端 `sceneLensItems` stale 映射 + 「待核对」徽章。
- 交付物（evidence/evolution）：
  - `fetch` 返回 `CacheFetch(hit, miss_reason)`，原因码 absent/expired/version_mismatch/
    integrity；compile 路径取 `.hit`；harness attempt 记 `source_cache_miss_<reason>`。
  - `InteractionSourceCacheStore.purge_for_source`（按 source_novel_id，用既有索引）+
    compilation facade `purge_interaction_source_cache`；`apply_source_invalidation`
    同址调用并记回执 `interaction_source_cache.purged_rows`；清理失败（SQLAlchemyError）
    降级记回执 TTL 兜底、不阻断失效传播，非 DB 异常上抛。
- 测试：story `test_scene_basis.py` 6 条（A04 同长度替换绕钩子/重排绕钩子→degraded、
  正流程 invalidate→ensure→恢复 ok 且新行带 basis、基线缺失 degraded、confirmed 行豁免、
  unsupported_dependencies 显式）；缓存套件 +2（A09 源项目软删→入口立即 NotFoundError
  不消费缓存、purge 后 absent 且重编译等价）；evolution `test_invalidation.py` 补回执
  断言；lens 套件断言更新（state_view 单次读取顺序 + stale 字段）。story+evidence+
  evolution+test_api 1534 passed；ruff 全绿。
- 实施中的岔路与修正：①误改主仓 frontend-console/sceneLensModel.js（已立即还原，
  改 worktree 副本）；②dir 级 `ruff format` 波及 26 个范围外文件（纯格式噪音），
  对照 M0–M4 变更集逐一 `git checkout --` 还原至最小 diff；③一次 lens 测试调用顺序
  断言失败（单次读取重构改变了 checkpoints/state_view 顺序，非契约）——更新断言并
  拆分 role_visible_knowledge 与 scene_world_state 的形状断言。
- 文档同步：01_数据库设计（continuity 行+basis_json 语义）、05_memory（M4 读时基线
  段）、22_evolution（同址清理）、story/README（basis seam）、evidence/compilation
  README（原因码+清理+lens stale）。docs-check 基线+BASE_REF=origin/main
  （no-change-reason：四份治理文档无当前架构影响）通过。
- 已记录的范围外缺口（契约 §5，属确认/链接基础设施不扩）：ContextConfirmation 只登记
  asset ID、EvidenceLink 无读时重验、ContextSnapshot source_revision 非结构化、
  manuscript_source.read 不校验 draft status（「当前稿」由 manifest 定义承担）。
- M4 缓办：浏览器走查「待核对」徽章（随 M5 试改入口一起验收）；PG 并发清理与
  跨 worker purge 观察（随合入前 e2e）。

## M5 记录（试改改动级对照，2026-10-07，完成）

- 契约：[docs/plans/2026-10-07-m5-trial-change-comparison-contract.md](../../../../docs/plans/2026-10-07-m5-trial-change-comparison-contract.md)
  ——`field_changes`（dict 逐字段 changed/added/removed，非 dict 回退 None 走整份对照）、
  `state_impact`（确定性锚定 Scene，世界正典/无法锚定显式 not_checked 不冒充无影响）、
  rebase 冲突 UI 逐字段三方选择（保留当前稿/采用试改，默认试改）。
- 后端（M5-2）：`workspaces.py` `field_changes` 接入 workspace_view changes；新增
  `state_impact.py`（kind=scene 直接锚定、writing_draft 按 chapter_ids 锚定、
  world_bible_draft 等进 notes/not_checked；纯读零写入）；测试
  `test_trial_comparison.py`（字段级/影响锚定/世界正典不推算）。
- 前端（M5-3）：CreativeExperiments 逐 change 「字段级改动」「状态影响」折叠面板 +
  stale 就地「基于当前稿重建试改」+ 冲突面板（radio 三方选择、expected_current_hash
  绑定、二次冲突提示重新选择；4 处状态重置点接线）；SceneLensSummary
  「从本场状态发起试改」直达入口（openProjectAssistant creative 分支 → 助手面板
  隔离试改 tab，正文/场景预选来自 captureWorkContext）；vitest 2792 全过。
- 浏览器验收（M5-4，Playwright `e2e/creative-rebase.spec.js` 2 条，专用库已 DROP）：
  ①Scene Lens 入口直达试改、正文+场景预选、零写入；②试改期间作者改稿→rebase 返回
  冲突→就地三方选择（采用试改 content）→重建（重建试改 label）→检查这一版→采用→
  正文=作者标题+试改正文拼接，作者中途修改不静默丢失。后端幂等/回滚/stale 拒绝/
  revert 补偿由既有 7+ 条单测覆盖（盘点确认，不重复造测）。
- **实施中修掉的真缺陷（A06 验收抓到，先 400 后定位）**：生产会话
  `autoflush=False`（core/database.py:71），`require_case`/`require_workspace` 以
  `populate_existing=True` 重读会把未 flush 的属性改写丢弃——`rebase()` 里重定位授权
  （case.grant_json）与子试改血缘/幂等哈希（child.parent_id/request_hash）写入后即被
  `create_workspace`/`edit_workspace` 的重读吞掉，导致第二次 rebase（带 resolutions）
  必 400 GRANT_SCOPE_CONFLICT、重放识别损坏；`proactive.submit_changed_case` 的续期
  授权同样被 `submit_run` 重读丢弃。单测会话默认 autoflush=True 完全掩盖。修复：
  recovery.py 两处 + proactive.py 一处显式 `await db.flush()`；回归：rebase 冲突解决、
  revert 补偿两条既有测试与新增 proactive 续期测试改为在 `sync_session.autoflush=False`
  （生产语义）下运行，stash 验证无修复时 3 条全红、有修复 42 全绿。
- 文档同步：collaboration/README（recovery 段补 flush 不变量）；docs-check 基线 +
  BASE_REF=origin/main（no-change-reason ×5：development-guide/架构 README/维护指南/
  07_outline/testing-guide 均无当前影响）通过。
- PR 时注意：BASE_REF 门禁的 5 份 no-change-reason 需写入 PR 正文「已逐项核对未更新
  文档」栏（正则逐字匹配，见 docs-check 记忆）。
- M5 缓办（沿 M4）：「待核对」徽章浏览器走查未单独成测（Lens 空态/入口用例已覆盖
  渲染路径）；PG 并发清理与跨 worker purge 观察仍随合入前 e2e。

## M6 记录（稳定输入与质量不变的 RP 对照，2026-10-07，完成）

- 摸底（只读 Explore）：普通 RP `compile_story_messages` 已天然满足稳定前缀→动态后部
  （规则→约定→回顾→来源包→重抽→tail→续写），来源包内固定优先；偏差仅两处——
  Agent 准备包 `insert(1)` 落在稳定段中间，快照 `prompt_name="interaction-story-v7"`
  与 `STORY_PROMPT_VERSION="interaction-story-v8"` 漂移（Prompt 体系文档已按 v8 登记
  两文件，代码落后于文档）。审查同源（govern_held_story join prepared.messages +
  最后一条 user 消息取 author_requirements）与测试锚点（test_prompts 约定块 index 1、
  agent 哨兵、material 前缀性质）已核实。
- 契约：[docs/plans/2026-10-07-m6-stable-input-rp-contract.md](../../../../docs/plans/2026-10-07-m6-stable-input-rp-contract.md)
  ——消息分组契约/准备包归位/prompt_name 单一事实源/等价判据/明确不做（不拆来源包、
  不动普通路径、不新增摘要模型、供应商前缀缓存计量留真实模型阶段）。
- 实现：①agent_runtime 准备包改为插在最后一条 system 之后、对话尾部之前（定位第一条
  非 system 消息；文本/转义/优先声明/预算链不变）；②evidence facade+service
  `compile_interaction_story_context` 增 `prompt_name` 参数（缺省家族名
  "interaction-story"），interaction 五个调用方统一传 `STORY_PROMPT_VERSION`。
- 等价验收：新增 `test_preparation_packet_stays_after_stable_prefix_and_before_tail`
  （准备包前全 system、包后存在 tail、用户输入最后）；`test_sources` 预算测试补
  `prompt_name == "interaction-story-v8"` 断言（防再次漂移）；evidence 快照测试补
  prompt_name 透传断言。普通路径既有测试即逐字节回归（未动）。interaction 193 +
  evidence 644（合并跑 837）全绿；`make prompt-contracts` 26 契约通过；ruff 干净。
- 文档同步：interaction README（v7→v8 现行段修正 + 新增「稳定前缀→动态后部」条目）；
  docs-check 基线 + BASE_REF=origin/main（同批 5 份 no-change-reason）通过。
- usage 可解释（盘点确认不新增字段）：attempt 已记 source_cache_hit/miss 原因码/
  检索与 embedding 计量（M3/M4）；供应商前缀缓存 token 属真实模型阶段（§7.4 另行授权）。

## M7 记录（完整闭环验收·离线部分，2026-10-07，完成；真实模型阶段未启动）

- 工程门禁（主计划 §7.2）全过：
  - `make repo-gates`：binary-growth / file-size / release-evidence / module-import 全过。
    module-import 棘轮持平 **525/525**（本批新增 3 处函数内跨模块导入已消除：
    collaboration/state_impact 与 story/continuity/basis 提升为顶层（无环、边已在冻结集），
    evolution/invalidation 的 outline_state.facade 提升为顶层抵扣；scene_lens→story
    保持函数内——提升会与 story→evidence 形成顶层双向对（基线 0），该惰性是有意设计）。
  - `make secret-hygiene`、`make prompt-contracts`（26 契约）、`git diff --check`、
    `make docs-check` 基线+BASE_REF（no-change-reason ×5）全过。
  - 后端全量单测 **7192 passed / 0 failed**（4m10s）；vitest 2792；Playwright creative 2 条。
  - 三个新迁移均已在 PG 专用库 upgrade/downgrade 验证后 DROP（M2/M3/M4 各自完成）。
- 修掉两个 M7 收尾暴露的真缺陷：
  1) `evals/rp_cost_baseline.py` 模块级硬设 `EMBEDDING_PROVIDER=bge_onnx`——pytest 收集
     import 即污染进程环境，全量跑挂 `test_effective_embedding_provider`（断言 openai）与
     `test_llm_client_generate_embedding_delegates_to_provider`（单跑过、全量挂的典型症状）。
     修复：环境固定移入 `if __name__ == "__main__"` 守卫（CLI -m 仍在仓库 import 前生效，
     describe 冒烟 + evals 209 passed 复核）。
  2) module-import 棘轮 528>525（见上）。
- 确定性降本门禁（主计划 §7.3）逐条核销：
  1. 相同有效输入命中持久包不重复召回/embedding/完整编译——M3 切片 3 测试 + PG 实测
     （agent_requery_same 3/3 命中，compile 中位 9.5~11ms，命中 attempts embedding 调用 0；
      必要来源复验保留：_verify_cached_proofs fail-closed）。
  2. 同轮相同查询去重、budget/视角不一致不误命中——缓存 key 覆盖预算/身份/视角，
     预算变体只复用材料重裁剪（8K 不套 16K 正文），测试钉住。
  3. 冷热包事实/范围/来源/必需项/遗漏语义一致、精确包渲染正文一致——切片 1 A/B
     32/32 rendered_sha 逐字节一致；切片 3 命中逐字节复用测试。
  4. 输入优化不裁必需证据、审查与生成消费同一消息集合——M6 契约与断言（普通路径
     未动即字节回归；agent 仅顺序；govern_held_story 同源 join）。
  - 延迟：冻结族 s/m compile 中位 1539.5→68.6ms（22×）、search 1417→32.3ms（44×），
    全场景 60~250ms valid=true 零阻断；miss 路径无回退劣化。目标（M 档 search p50<200ms、
    命中<150ms）在冻结族达成；p95/规模/并发见未完成项。
  - 新 query 仍检索（D5）：既有断言 + fresh 场景全价检索实测。
- **未完成项（明示，不冒充完成）**：
  1. §7.4 真实模型阶段整体未启动——需用户明确授权（付费运行、真实 RP 对照、费用账本
     USD 口径）。本批所有实测为本地免费链（BGE/合成语料），无任何真实费用节省宣称。
  2. 更大合成库的 p95/规模/并发对照与 GIN 体积校准（M3 遗留：GIN ~33KB/chunk、
     冻结族每编译仅 1–2 条有效 read 区分度有限），不作生产外推。
  3. 生产 TEI 远程 embedding 费用与供应商前缀缓存 token 计量未接（属真实模型阶段）。
  4. M4/M5 缓办：Scene Lens「待核对」徽章浏览器走查、PG 并发清理与跨 worker purge
     观察（建议随合入前 e2e 一并）。
  5. 发布/提交/PR：本批全部改动仍未提交（主计划 §9，需用户授权合入流程）；
     BASE_REF docs-check 的 5 份 no-change-reason 需写入 PR 正文对应栏。

## 验证证据

- `make docs-check`（基线）通过；收尾 `docs-check --base-ref origin/main` 以
  no-change-reason 通过（Makefile 新增 eval 目标不触架构文档）；`git diff --check` 通过。
- `backend/evals/tests`（含新增 test_rp_cost_baseline.py 3 例）209 passed、3 skipped。
- PG 真实链测量：专用库 novel_rp_cost_baseline_e2e（名称含 e2e+baseline 标记，
  alembic upgrade head 至 20261006_event_soft_delete），s/m 两档各 16 attempts
  全部 valid（无降级、无阻断、embedding 零失败）；测量后库已 DROP。
  报告（本地，不入库）：backend/evals/artifacts/rp-cost-baseline/postgresql.json、
  sqlite.json（s/m 双档）。

## 真实阶段记录（§7.4，2026-10-07，授权「授真实调用，暂不提pr」）

### 阶段 0：零成本准备（完成）

- 预算与账本：累计 USD 20 硬顶；阶段帽 adaptation 3 / dev 9 / holdout 6、失败预留
  2 不发放。唯一累计账本 `~/.ai_writing_private/rp-real-20261007/paid-calls.json`
  （仓库外，700 权限目录 + flock 单进程；RPMeter 继承 v4_live.Meter——未知用量
  阻断、脱敏快照拒绝计费、峰值价预留/结算语义原样复用）。仓库内只进脱敏快照与结论。
- 定价核验（2026-10-07，api-docs.deepseek.com）：flash 档 peak 输入(未命中)
  $0.30 / 缓存命中 $0.006 / 输出 $1.20 每 M，off-peak 一律半价——与 Meter 价表
  完全一致，无需修订。
- 凭据链：dev 库 ai_novel_acceptance_guimi 只读取 owner_id=0 的 GlobalLLMDefaults
  + 已验证 deepseek 凭据**密文原样复制**到一次性账户；运行时由应用用
  LLM_SETTINGS_ENCRYPTION_KEY 解密——密钥全程不落盘、不打印、不进仓库
  （比原「先解密到私有文件」方案更干净，私有密钥文件取消）。
- 费用口径决策（重要）：精确缓存/app 级材料缓存已离线证明字节等价 → 不改变
  LLM 费用；真实阶段可测的费用杠杆是**供应商 KV 前缀缓存**（命中 $0.006 vs
  未命中 $0.30，50×）。M6 旧布局 packet 插在 system 块内（insert(1)），跨轮
  前缀在第一条 system 后即分叉；新布局整段稳定前缀（规则+约定+回顾+来源包）
  跨轮字节一致 → 命中率应显著上升。布局成对同时测盲评质量与缓存 token。
- 场景脚本冻结（dev/holdout 前不得改）：开场白/分支输入/逐轮输入复用 M0 冻结
  查询族（_QUERY_RECAP + _QUERY_INPUTS/_QUERY_RECENT）；失效场景=重发布第 1 章
  新版本，预期服务层或任务级 fail-closed 且零付费调用。

### 阶段 1：harness `backend/evals/rp_real_pairs.py`（完成）

- 复用 v4_live 一次性库模式（e2e 标记库 ai_novel_agent_e2e_rp_pairs_20261007 +
  alembic + 组合根 + TaskWorker(run_once)）与 M0 冻结族 fixture（含真实索引，
  bge_onnx 本地 embedding）。
- RPMeter：阶段帽在总帽前检查、每笔 call 打 stage/label 标签；wrap_stream 在
  SDK 传输层观测 prompt_cache_hit/miss_tokens（LLMStreamChunk 不透传 raw usage，
  只能包 chat.completions.create），非流式走 Meter.wrap 原生 raw usage。
- 场景：opening + N 轮 send_message + regenerate + continue_from_node 分支 +
  重发布失效（零付费断言）+ 布局成对（旧布局=把 packet 移回 index 1 的字节级
  变换，新旧两臂真实生成 + 匿名随机顺序盲评裁判）+ 确定性质量门（无失败尝试/
  无项目标记泄漏/失效通过）。§7.3 每尝试记录 token/缓存命中/价格档/费用上界与
  估计/worker 墙钟。
- 修订记录：revision 行直建但 manifest/anchor/reference 全部来自 fixture 真实
  行（draft 哈希真实），指纹用 InteractionSourceService._set_fingerprint 同源
  计算；scene 覆盖检查只在冻结服务 gate，story 链不查。
- 已过 ruff check/format；import 无环境污染（EMBEDDING_PROVIDER 外值不被
  -m 以外路径改写）；`--help` 冒烟通过。

### 阶段 2：适配冒烟（≤USD 3，2026-10-07 完成）

- 结果：**通过**。s 族 12 章/35 chunks；opening+3 轮+重抽+分支全部 completed
  （每段 400–1600 字，worker 墙钟 25–107s）；零项目标记泄漏；40 笔真实调用，
  实付 **USD 0.1266** / 上界 0.2357（阶段帽 3，总帽 20）；一次性库已 DROP。
- **布局成对核心证据**（同条件背靠背重放，prompt 基本同长）：
  旧布局（packet 插 system 块内 index 1）供应商前缀缓存命中 **512** tokens；
  新布局（M6：稳定前缀后）命中 **6400** tokens —— 12.5×，且真实跨轮流式调用
  命中随对话增长（opening 512 → turn-2 1792/2432/3328）。缓存 token 计量
  在 SDK 传输层观测（LLMStreamChunk 不透传 raw usage），流式/非流式全覆盖。
- 适配期修掉的接线问题（均为一次性库内，无生产影响）：
  1) revision 直建缺 manifest_hash（NOT NULL）；
  2) 服务层变更需显式 commit（API 层职责，测试直调没有）；
  3) 所有权口径：local 鉴权下服务与 worker system scope 都解析到 bootstrap
     账户——全部行挂 bootstrap（与 dev 库 GlobalLLMDefaults owner=0 同形），
     不再 bind 自定义 principal；
  4) create_journey 为旅程建独立 interaction 项目，worker 领取须按
     journey.novel_id 传参（fixture consumer 是另一个项目）；
  5) selection_epoch 被 worker 推进——每次变更前现读；
  6) 本机代理 127.0.0.1:1082（dev .env LLM_PROXY_URL）未运行导致
     LLMConnectionError；该笔 usage_unknown 按保留上界 USD 0.0821 经
     Meter authorized_reserved_cap 机制核销（请求未出本机，证据已留账本）；
     harness 以 LLM_PROXY_URL="" 直连复测 401→连通。请求字节级确定性
     （重构特性）触发 Meter 防重试闸，适配期换开场白常量绕开同一哈希。
- 适配期两处场景校准（dev/holdout 冻结前的最后修订）：
  1) 失效场景改为「冻结 manifest 引用的源稿行被删除」——实测重发布新章节
     版本是冻结修订的合法继续（任务照常完成，4 笔调用），真正的 fail-closed
     触发是 manifest 引用不可解析；
  2) 盲评裁判 max_tokens 600→1500（首轮 600 全耗在推理、content 为空）。
- 场景脚本自本节起冻结：开场白「我在雾渡港的雾里醒来，靴筒里还折着那张
  抄着三个条件的旧纸条。」、分支输入、逐轮输入复用 M0 查询族（_QUERY_RECAP/
  INPUTS/RECENT）、失效=删源稿行、布局对=turn-1/turn-2 请求重放 + 匿名盲评。

### 阶段 3：dev（≤USD 9）+ holdout（≤USD 6）+ 收尾（2026-10-07 完成）

- dev（s 族 6 轮）：9/9 尝试 completed；50 笔调用实付 $0.1821/上界 0.2292；
  布局成对 512 vs 6656 命中。失效场景二次校准：删第 1 章源稿不影响编译
  （mandatory reads 只含锚点章/知识引用章）→ 场景改删锚点章。
- 盲评修复记录：deepseek-flash 裁判是推理型——600/1500/4000 max_tokens 全烧
  推理 content 为空；response_format=json_object 不改变推理行为；12000 才完成
  （完成 6547 tokens）。dev 裁判从账本重放两臂单独补跑（一次性裁判库用后 DROP）。
- holdout（m 族 36 章 6 轮）：9/9 completed；50 笔实付 $0.1876/上界 0.2337；
  真实路径后期调用命中 9600–13312 / 13K prompt（70–98%）；布局成对 512 vs 8064。
  失效（删锚点章源稿）fail-closed 成立：任务失败、无故事产出，Agent 探索烧
  2 笔规划调用（≈$0.0007）后终止——零成本断言过严，契约（不回退纯模型知识）成立。
- 盲评两样本：dev 双臂四维全过（裁判风格性偏好旧臂）；holdout **新布局胜**
  （旧臂违反冻结约束：温若近乎点破灯塔秘密，faithfulness/voice fail）。
  合计：无「新布局质量下降」证据，holdout 有正面证据。
- 总账：140 笔调用，实付 **USD 0.4963** / 上界 0.6986（硬顶 20；失败预留未动）。
  一次性库三阶段 + 裁判库全部 DROP。
- 入仓产物：`backend/evals/rp_real_pairs.py`（harness）+
  `backend/evals/artifacts/rp-real-pairs/{ledger-snapshot-20261007.json,
  CONCLUSIONS-20261007.md}`（脱敏快照不含请求/输出正文，完整账本留私有目录）。

## 真实阶段总结论（§7.4 完成度）

> 历史结果，2026-10-07 独立复审已撤销本节整体完成判断。140笔仅短程布局 smoke，独立来源族/30轮不足，费用为估计而非账单；当前结论以恢复快照与整改验收报告为准。用户已授权代理作者验收，无需等待人类再试用。

- 已完成：成对运行（同模型同档）、全场景覆盖、精确缓存离线等价 + 布局成对
  真实盲评、§7.3 逐尝试 token/命中/费用记录、质量门（零泄漏/零失败）、
  预算纪律（累计账本、未知用量核销留证、阶段帽）。
- 未完成/明示：作者验收需用户实际试用；语义盲评不替代人工；p95/并发/
  TEI 远程 embedding 费用不在本阶段；盲评仅 2 样本（dev 1 + holdout 1），
  「质量不下降」为无反证 + 1 正证，非统计结论。


## 2026-10-07 独立复审与代理作者验收（完成，结果失败）

- 用户本轮授权：review 世界演化第一阶段，并由主 Agent 完成作者验收；采用代理作者评阅，human_validated=false，不要求用户再次试用才能完成本轮验收判断。
- 固定实现基线仍为 85fb1c7be35ae687f949863d179f5fd63c53f3c0，检查全部 WIP 和未跟踪新增实现；修改前逐文件 SHA-256 保存在仓库外私有 review 目录。原主工作区与其他任务改动不动。
- 独立 Standards/Spec 审查已证实：Lens REST 丢弃 object_states/stale；角色标签/秘密关系过滤不完整；缓存匿名路径与备份排除违反例外；容量检查不完整；旧基线恢复、来源回开/逐项未知与状态影响锚定不达契约。真实评测只有同族短程布局对照，不能核销冻结的独立来源族及30轮长程要求。
- 主 Agent 已重跑定向单测 47 passed；本轮新建可丢弃 agent_e2e_world_phase1_review_20261007_b84c1 专库，全新 migration head upgrade 成功；真实 REST 与浏览器重现对象永远空态。浏览器正在执行预览/比较/确认/改稿后回看，合成 provider、真实 API/PG/worker；新增付费调用为0。
- 临时服务仅本任务18007/18087；私有证据目录 /Users/tywww/.ai_writing_private/world-phase1-review-20261007，旧 rp-real-20261007 费用账本仅读、不改、不重建。
- 当前结论：验收不通过；待完成剩余作者步、保存正式 review/acceptance 产物后收尾。本阶段不能标 completed。
- 下一步：完成改稿后状态回看与独立RP输出代理评阅，固化证据、停本任务服务并更新恢复快照。本轮不提交/推送/PR/合入/部署。

- 复审收尾：浏览器确认后drafts 1→2、采用回执0→1，作者再改稿后drafts=3；memory_events始终9行。确认保存与历史有效，状态入口和有限后果比较失败。默认窄屏双抽屉互相inert已按DOM祖先属性确证。复阅旧RP双臂的代理作者反例与收据已保存，无新模型调用。
- 新增PG验证：fresh migration upgrade成功；alembic check失败，缓存novel_id索引名和lexical GIN登记与ORM不一致。普通docs-check通过，BASE_REF缺5份文档核对说明未通过，不追认原M7全绿。本轮不修产品代码，仅交付审查证据。

- 收尾：18007/18087本任务服务已停止，合成验收专库保留用于整改复跑；原始WIP指纹核对仅本文发生变化，产品文件未动。旧paid-calls.json SHA-256与原快照一致。
