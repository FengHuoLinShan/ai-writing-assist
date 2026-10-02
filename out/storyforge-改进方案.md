# StoryForge 调研转化：NovelCraft 改进方案（v6）

> 来源：`out/storyforge-调研报告.md`（2026-10-01，静态调研，未运行 StoryForge 任何代码）。
> 性质：建议方案，不构成新增授权。边界服从 `AGENTS.md` → 已采纳 ADR → 稳定接口；用户可见功能
> 实施前按 `docs/product/user-personas.md` §4.3 补画像判断。
> 代码基线：`origin/main` @ `fa1ccc0`（2026-10-02）。`path:line` 以此为准；路径相对仓库根，`backend/` 与
> `frontend-console/` 前缀在不致混淆时省略。历轮评审已证伪十余处现状判断，本版复核又修正多处，
> **每项开工前仍须以当日代码复核**。
> 编号沿用调研报告（B 借鉴 / P 规避 / D 差异化），正文按批次排列；SF = StoryForge，NC = NovelCraft。

## 一、结论

SF 的多数“聪明设计”NC 已有更强版本（真实 tokenizer、确认指纹链、P0 保护、服务端密钥、实体治理），
真正值得搬的只有少数缺口。按价值与成本分三批：

- **P0（约 2 周）**：把已有的能力绑定扫描接入 CI（B1，半天）；作者好例/反例 few-shot 首版（B3，只覆盖正文生成）。
- **P1（约 5–6 周，多数可并行）**：二进制增量体积门（B11）、图片请求幂等（B9）、逐源上下文证据（B8）、
  发布证据账本（B6，兼 D2 交付）、跨模块 import 守护门（B2），以及三处低成本规避项。
- **P2**：任务级模型路由（B5，含 2–3 周前置，优先级随运营成本政策联动）、长篇规模分档门（B7）。

另有四个产品方向（D1/D3/D4/D5）和八项决策待拍板，见第五、六节。

本版对 v5.1 的四处实质修正（完整依据见附录 B）：

1. B1 的真实缺口是“扫描器没进 CI”，不是“注册表缺三个字段”。三字段补登时没有任何消费者，取消独立 P0。
2. B4 的前提不成立：编译到发送之间没有让 P0 资料静默缺失的路径。撤销独立条目，只在 B8 留一条回归测试。
3. B11 把 `.test-logs` 当作持续增长的债：它是 7 月一次性入库、被验收文档引用的证据。真正在涨的是 9 月起的截图与视频，改为增量门。
4. B3 收窄为单能力首版，补上 tier 选择、反例风险和统计口径的局限。

## 二、基线：NC 已有，不得重复建设

| 能力 | 现状与证据 |
|---|---|
| 真实 tokenizer | `infrastructure/llm/token_estimation.py`：tiktoken，失败退 UTF-8 字节保守上界 |
| 模型能力档案 | `infrastructure/llm/capabilities.py:20-37` verified_input_ceiling_tokens + calibration_status；未登记模型落 24K 保守档（`:124-141`） |
| 重试错误分类 | `infrastructure/llm/retry.py` |
| 上下文编译保护 | `compiled_context.py`：P0 永不逐出（`:60`、`:229-233`），P0 超预算写 blockers（`:446-462`） |
| 确认与指纹链 | 创建确认时 blockers 拦截（`confirmation_service.py:170-171`）；执行时按确认重编译、指纹不符即 `context_changed`（`:265-319`）；发送冻结的 `plan.request` |
| 逐源证据底座 | `KnowledgeScopeReceipt`（`knowledge/contracts.py:162`）逐源 source_key + content_hash + 双指纹 + coverage；`ContextBudgetEvent` 为 section 级 token 事件 |
| 生成前治理单点 | `run_knowledge_audit` / `run_governed_generation`（`knowledge/workflow.py:388,418`） |
| 能力注册表 | `CAPABILITY_REGISTRY` 66 条（`knowledge/policies.py:163`），已含 domain、confirmation_policy、adoption_gate、output_permissions |
| 调用点绑定扫描 | `tools/prompt_contracts/capability_bindings.py`：50 个文件绑定 + AST 扫描 + 7 个豁免文件 + 负样本测试；**未进 CI**（见 B1） |
| 禁绕过项目 LLM 入口 | `tests/unit/test_novel_scoped_llm_usage.py:119` AST 白名单，随 CI pytest 运行；直接构造 LLMClient 只剩 embedding 窄例外 |
| 服务端密钥与 CSP | `secret_store.py` Fernet 信封 + HMAC 指纹；`deploy/openresty/site.conf.template:13` |
| 前端注入面 | 源码无 v-html；`RpMarkdownContent.vue` 自研 VNode 渲染 + safeHref 白名单；innerHTML 经 esc()。测试断言仅两处局部（见 P1） |
| 导入信任边界 | `modules/imports/parsers.py`：EPUB 成员审计、可执行检测、get_text 落纯文本、ebooklib 延迟导入 |
| 实体治理与审校细度 | 三级去重 + 别名提取 + 拼音 + pgvector + RRF；excerpt 唯一定位、scene_contract 三态、返修锚点 |
| 隔离与并发 | novel_id 隔离、owner 校验、锁 + 版本 CAS（`writing/services.py:841-858`）、SKIP LOCKED 队列 |
| Agent 护栏与可观测性 | ADR-0023 AIRunEnvelopeV1；`redact_diagnostic` 脱敏；usage_unknown 显式建模 |
| CI 既有门 | schema-check + fresh migrations、docs-check、CodeQL、前后端依赖审计 |
| 余额与用量 | 余额 `GET /account/settings/llm-balances`（全局设置页）；项目级 ai-usage（项目设置页） |
| 模型留痕 | `agent_step_harness.py:114-137` managed_llm_provenance，model 在 profile_summary 内 |
| 规模验证工具 | `tools/evolution_scale_harness.py`（604 行，`--repeat` / `--json-path` / 退出准则）；未接入 CI |
| 恢复与外观 | TodayView 章级续作入口（`vue/views/today/TodayView.vue:99-107`）；主题包 + prefers-reduced-motion，无字号/行距控制 |

**刻意不借**（报告原结论）：三注册表全套移植、RequireBackupBefore 全套、Voronoi 式地图参数化。

## 三、执行项

### P0 批次

#### B1 把能力绑定扫描接入 CI（半天）

**现状**：`capability_bindings.py` 已实现“含 LLM 调用形态的文件必须登记 capability_id”，当前代码树扫描 0 问题。
但它只挂在 `make prompt-contracts`（`Makefile:198` → `tools/prompt_contracts/__main__.py:49`）上；
`backend-ci.yml` 和 `make test-ci` 都不调用它，`tests/prompt_contracts/test_prompt_contracts.py:169`
的全量校验只跑 `validate_contracts`，不含绑定扫描。今天新增未登记的调用点，CI 不会失败。

**方案**：在 `tests/prompt_contracts/` 加一条测试，对真实代码树断言 `validate_capability_bindings() == []`，
随 `test-fast-coverage` 进 CI。这比在 workflow 里新增 `make prompt-contracts` 步骤更省事，也让本地 `make test` 同样生效。

**验收**：该测试在 CI 运行并通过；临时加一个未登记 `.research()` 调用的文件能使它失败（扫描逻辑本身已由
`test_capability_bindings.py:27` 覆盖，这里只证明接线）。

**不再做的部分**：v5.1 计划给注册表补 execution_boundary / allowed_callers / cost_tier 并列 P0。核实后：

- execution_boundary 与 CAPABILITY_REGISTRY 已有的 confirmation_policy、adoption_gate、output_permissions 重叠，不做，
  除非届时能说清它覆盖了哪种现有字段覆盖不了的检查。
- allowed_callers 与现有文件级绑定高度重叠（绑定本身就是“哪些文件可调哪个能力”）。B2 落地后再评估是否需要调用点级细化。
- cost_tier 只有 B5 消费，随 B5 补登。

原则：新字段只在有检查器断言或运行时消费的那一批落地，不允许“先声明、以后用”。

#### B3 作者好例/反例 → few-shot（1.5–2 周，含前端）

**缺口**：SF 让作者给模板标好例（≤3）和反例（≤2）并注入生成（`prompt-engine.ts:63-84`）。NC 全仓无对应功能。

**画像判断**：目标画像 A。消除的摩擦是“AI 写不出我要的语感，每次都要大改”。作者只需表达“以后照这个写 / 别这样写”，
不接触 Prompt 或 token 概念。验证看采纳率与采纳后修改比例。用户是否愿意持续标注仍是产品假设。

**方案**：

1. **首版范围**：只覆盖 `writing.generate`（正文生成）。采集、预算和对照统计都依赖样本量，一次铺到几十个能力只会稀释数据。
2. **存储**：沿用 editorial brief 先例，存 `Project.settings` JSON（`modules/project/editorial_brief.py:13,73`），
   Pydantic schema `extra="forbid"`，项目级开关默认关闭。首版不建表、不加 migration；扩展到多能力或需要逐条审计时再建表。
   条目字段：`kind`（good/bad）、内容、作者备注、来源（章节/候选）、capability_id（取 CAPABILITY_REGISTRY 词表，写入时拒绝未注册值）。
3. **注入**：loader 放 `evidence/compilation/services/loaders/`，按 `options.novel_id` 读取（同 `editorial_brief_loader.py:57`），
   注入条件与 editorial brief 一致（`writing.generate` 且作者视角）。作为编译期 section 进入确认预览和上下文指纹；
   内容走与正文、项目资料相同的 JSON 转义 fence，拼装层禁止裸文本拼接。
4. **tier 与逐出**：editorial brief 是 P3，预算紧张时整段逐出。few-shot 放哪一档实施时定，但被逐出时确认预览必须告诉作者
   “本次未使用你的示例”，不能静默失效。
5. **反例风险**：负面示例可能反被模型模仿（推断，未验证）。反例必须附作者的“差在哪”，以“避免”语义呈现；
   若对照数据显示反例无益，允许只保留好例。
6. **预算**：计入该能力 token 预算（tiktoken），超限时先截反例、再截好例，正文优先。
7. **入口**：生成结果卡片与正文选区就地提供“以后照这个写 / 别这样写”；项目设置次级位置可查看、删除。首次使用给一句说明。
8. **度量**：同项目、30 天窗口内带/不带示例的 run 对照采纳率（adopted / candidates）与采纳后改动比例（content_hash 变化），
   挂在 ai-usage 同级诊断入口。这是观察性数据（愿意标示例的作者本身更投入），只能作方向信号；
   要因果结论须走项目级开关对照或盲评（与 D4 同一工具链）。
9. **同步**：prompt_contracts、`docs/prompts/Prompt体系设计.md`。

**验收**：

- 确认预览可见示例 section；增删示例后指纹变化、旧确认失效。
- 注入防护：含指令样式文本的示例在最终 request 中只以转义数据字段出现（fake LLM 断言 request 结构）。
- 隔离：跨 novel_id 读不到；未注册 capability_id 被拒。
- 删除示例后，历史 run 的确认快照与指纹记录不变。
- 截断顺序、逐出提示、对照统计聚合各有测试；空态与首次引导可用。

### P1 批次

#### B11 二进制增量体积门（2–3 天）

**现状实测**（`git ls-files`，fa1ccc0）：受版本控制文件共 105MB / 3557 个；历史 pack 145MB。主要占用：

| 目录 | 体积 | 构成 |
|---|---|---|
| `.agent/tasks` | 25.2MB | 其中 artifacts 9.5MB / 185 个（111 png、55 jpg、9 mp4） |
| `backend/.test-logs` | 24.3MB | 239 个去原文真实模型账本 |
| `docs/plans` | 11.7MB | 52 png、49 svg、设计 json |
| `frontend-console/e2e` | 8.5MB | 96 png |

增长来源是二进制：9 月新增图片/视频 329 个，仍在库 28.7MB（`.agent/tasks` 14.7MB、e2e 7.4MB、docs/plans 6.6MB），
此前每月不超过 2.6MB。`.test-logs` 的 240 个文件全部在 2026-07 一次性强制入库（`.gitignore:56` 已忽略该目录），
此后零增长；T-20260911 任务有意保留它们作为“不可替代的运行证据”，`docs/superpowers/acceptance/2026-06-30-*` 按路径引用了其中 4 个。

**方案**：

1. CI 增量门：PR 新增或修改的二进制单文件超过 1MB 即失败，单 PR 二进制增量超过 5MB 即失败；豁免须登记路径与理由。阈值见第六节。
2. 在 `.agent/PLANS.md` 补一条：截图、录屏、宣传视频默认不入库，笔记只留摘要、可复现命令与仓库外位置；
   确需入库的单文件压到 1MB 以下（现行协议已写“大型原始材料不默认入 Git”，这里给出可执行阈值）。
3. 清点 `frontend-console/e2e` 与 `docs/plans` 中已无引用的图片并删除。AGENTS 规定截图像素不作阻断要求，孤儿截图没有保留价值。
4. `.test-logs` 不动。新的真实模型账本仍按 `testing-guide.md:107-111` 入库去原文快照，超阈值走豁免登记。
5. 删除文件不会缩小历史 pack；改写 Git 历史须用户另行确认，不在本项范围。

**验收**：门在 CI 生效，并有负样本测试（构造 2MB 二进制的变更被拦）；`.agent/PLANS.md` 规则落地；孤儿图片清单处理完毕。

#### B9 图片生成请求幂等（3–4 天）

**现状**：世界对象立绘只走本机 CLI（`world/world_object_image_generation.py:506`）；地图册页面可走本机 CLI
或账户图片连接（`map_atlas_workflow.py:1923,1961`）。两者都没有按请求内容复用。地图册对象 key 由
novel_id + page.id + `task.id-attempt` 组成（`map_atlas_workflow.py:1756-1761`），只防重试互相覆盖。
按 ADR-0029，本机生成不产生平台费用，真正花钱的只有地图册账户图片路径。

**方案**：

1. 幂等键 = sha256（novel_id + owner + 状态快照哈希 + prompt + 模型 + 参数）。必须含租户维度，查询必带 novel_id 过滤，
   否则构成跨项目资产泄漏。
2. 独立索引 request_hash → object_key（新表或扩展 `20260929_world_object_image_candidates` 候选表，实施时裁定并同步 schema 文档），
   不挂在随 attempt 变化的对象 key 上。
3. 资产层读时校验（字节数 + SHA-256），不符即标 corrupt 并按未命中处理。
4. **重新生成必须能绕过复用**：同参数再生成常常是作者有意想换一张。命中时告诉作者“使用了相同设置的已有图片”，
   并提供“仍然重新生成”。
5. 本机 CLI 路径复用同一机制（省时间，不省钱）。

**验收**：账户图片路径同参数第二次请求的外部调用计数为 0；“重新生成”产生新调用；跨项目同参数不命中（负向测试）；
状态快照变化时正确未命中；损坏对象不被复用。

#### B8 逐源上下文证据（约 1 周）

**缺口**：SF 每次装配都记录逐源 included/omitted/trimmed、字符与 token 数、sha256（报告 §12.2）。
NC 的 `KnowledgeScopeReceipt.included` 已逐源记录 source_key 与 content_hash，缺三样：

- 逐源 token 数；
- 逐源截断标记（现在只体现为整体 `scope_complete`）；
- 来源未自带哈希时，content_hash 退化为身份字段哈希（`scope.py:100`），不是正文哈希。

结果是 run 账本不能复算“实际发了哪些资料、各占多少 token、谁被截断”。

**方案**：

1. 扩展 `KnowledgeSourceEntry`：token 数（tiktoken）、状态（included / trimmed / omitted）与原因；不存原文。
2. 能取到正文的来源改用正文哈希；取不到的保留身份哈希，并显式标 `hash_basis=identity`。
3. `ContextBudgetEvent` 保持 section 级，不合并。
4. 原 B4 的剩余价值并入这里：加一条回归测试，以 fake LLM 断言发送的 request 由确认后的完整 sections 渲染，
   防止未来改动破坏现有保证。

**验收**：任一 run 可从 receipt 复算逐源 token 构成；trimmed 与 omitted 区分有测试；`hash_basis` 两种取值都有测试；
每个来源的元数据体积有上限断言。

**机制件另行裁定**：报告把“每源 token 预算 + 确定性截断 + L3→L2→L1 分层丢弃”列为可近乎直译的搬运首项，
而 NC 的 `CONTEXT_BUDGET`（`evidence/compilation/contracts.py:481-492`）仍是条目数上限。它与 P20 `budget_tokens==0`
确认和 tier/P0 语义交互面大，列为第六节决策 5。

#### B6 发布证据账本（3–5 天，兼 D2 交付）

**缺口**：`README.md:279` 承诺“建立脱敏、版本化长篇评测集……逐项完成真实质量准入”，但没有对外可机器查验的证据形态；
`backend/evals/artifacts` 整目录被忽略（`.gitignore:58`）。

**方案**：

1. 版本化 JSON schema：schema_version、能力名、数据集版本、指标、盲评结论、真实 token 成本、逐文件 sha256、
   generated_at 与 generator 版本、关联 commit、claims_boundary（证明什么、不证明什么，防止证据本身变成过度宣称）。
2. 新建受版本控制的证据目录（如 `docs/evidence/`，实施时定），单文件受 B11 门约束；不进 `architecture-documents.toml`（该清单刻意排除验收报告）。
3. CI 校验器：schema 合法；commit 在 origin/main 可达；sha256 一致；超过 N 个 release 未更新标 stale。
4. 首发 rp-long-memory v3 holdout 脱敏集；第二个实例留给 D4 准入；B7 的 `--json-path` 输出作第三个实例（json 契约在本项定稿）。
5. 付费原始数据留仓库外（`testing-guide.md:107-111`）。

**验收**：首发证据文件字段完整（含 claims_boundary、generated_at）；校验器在 CI 运行且有负样本；docs 索引页引用证据路径。

#### B2 跨模块 import 守护门（约 2 周）

**缺口**：AGENTS 规定生产代码跨模块只经 `contracts.py`、`facade.py` 或已注册 DI port，前端组件只经 `vue/bridge/index.js`，
两者都没有机器门。SF 的反面教训（P9）是豁免不登记，反向依赖被 CI 默许。

**现状实测**（AST，排除 tests 与 migrations）：跨模块且不经顶层 contracts/facade 的 import 共 53 条，分布在 35 个文件：

- 裸包 import 25 条，多数经包 `__init__` 再出口（如 `modules.evidence`）；
- 嵌套或命名 facade 10 条（`story.outline_state.facade`、`world.map_atlas_facade`、`world.worldbuilding_facade`）；
- 直接引用实现模块 17 条，其中含 ORM models 引用（如 `project.models`、`assistant.session_models`）；
- 嵌套 contracts 1 条。

**方案**：

1. **先定合法形态**（不可跳过）：顶层 contracts/facade、嵌套 facade、包 `__init__` 再出口、已注册 DI port、ORM metadata 引用
   （AGENTS 允许的有限例外）。据此把 53 条逐条裁定为“合法 / 登记豁免 / 整改”，清单入库。
2. 后端 `scripts/check_module_imports.py`：AST 扫描，白名单事实源取 `docs/architecture/architecture-documents.toml` 的 components；
   沿用 capability_bindings 的“注册表 + 扫描 + 豁免登记”三件套，豁免必须带理由。
3. 前端：`eslint.config.js:30-43` 目前把 api、state、router、toast、esc 声明为全局只读变量（服务旧代码）。
   在 `vue/**` 覆盖块里用 no-restricted-globals 禁用这些全局，用 no-restricted-imports 把基建访问限制在 bridge。
4. 不重复已有门：schema-check、docs-check、CodeQL、依赖审计已覆盖 SF 对应门类；SF 的死代码可达性门价值低，不做。

**验收**：反向依赖样本被拦（负样本测试）；53 条全部有裁定记录；豁免数在 CI 输出可见；`vue/**` 下使用裸全局被 lint 拦截。

#### 低成本规避项（合计约 2 天）

- **P1**：在 ESLint 启用 `vue/no-v-html`，把“零 v-html”从两处局部测试升级为全局门。
- **P3**：`modules/interaction/framing.py:88-92` 元数据尾块校验失败时静默置 None（`raw_metadata` 仍随返回值带出）。
  补 `metadata_invalid` 计数落 run receipt。正文不判废的设计保持不变。
- **P8**：行数门。生产代码超过 3000 行告警；超过 5000 行且高于入库基线即失败，允许下降。现有超 3000 行的生产文件 7 个，
  超 5000 行 2 个（`world_generation_center_service.py` 5232、`world/schemas.py` 5138）。

B1、B2、B11、P8 的负样本测试统一放进一个治理门测试文件（先例：`tests/e2e/test_20_security.py` 集中 9 条安全红线），便于检索。

### P2 批次

#### B5 任务级模型路由（前置 2–3 周 + 本体 1 周）

**缺口**：SF 按任务类别把抽取类调用路由到便宜模型（`task-routing.ts:4-15`）。NC 没有按用途选模型的机制：
`high_quality`（`project/llm_runtime.py:351,385-388`）只延长超时并切换预算档，不换模型。

**约束比 v5.1 估计的更硬**：账户层每个 provider 只有一个 `default_model`（`settings_service.py:375`、`settings_constants.py:50,63`），
全局默认设置明确禁止改模型（`settings_service.py:452-454`）；能力档案白名单只有两个 deepseek 模型，其余落 24K 保守档。

**画像约束**：路由不能变成用户负担。B 画像不懂模型，A 画像反感 token 和内部术语。默认由系统在同一账户连接内按能力自动选择，
用户最多在高级设置看到“省钱模式”一类开关；未配置时回落主模型。

**前置**：

1. 账户连接支持同一 provider 下多个模型（模板、校验、设置 UI）。
2. 目标低成本模型进入 verified 档能力档案，否则抽取类输入会撞 24K 上限。
3. 结构化输出能力声明：`capabilities.py` 没有 json/response_format 字段，而 `infrastructure/llm/client.py:1109-1110`
   对结构化调用无条件发送 `json_object`。需按模型声明 supported / unverified / unsupported，unverified 一律 fail-closed。
4. 能力注册表补 cost_tier（原 B1），补登即被路由消费。

**验收**：抽取类 step 的 managed_llm_provenance 中 `profile_summary` 的 model 为目标低成本模型；未配置时回落主模型有测试；
非 verified 模型不参与路由。

**优先级说明**：模型费用目前由作者自己的账户连接承担，路由主要省作者的钱。若决策 4 选择平台承担费用，B5 应升为 P1。

#### B7 长篇规模分档门（1.5–2 周 + 首轮定标 2–3 天）

**缺口**：SF 用 10 万 / 30 万 / 100 万字三档夹具宣示规模边界（报告口径：夹具存在、未运行）。NC 的
`evolution_scale_harness.py` 只覆盖 evolution 单链路，且没有接入任何 CI 或定时任务。

**方案**：

1. 泛化 harness 到编译、检索、审校分片、任务编排四条链路，三档确定性种子。被测维度包括“单章续写输入成本随章节长度增长”
   （报告 §12.5 标【推断】，用测量证实或证伪）。
2. 低档挂进既有每日 PG e2e workflow（`.github/workflows/backend-postgresql-e2e.yml:4-5` 已有 cron）；
   首轮全档定标在本地或手动跑（GitHub hosted runner 6 小时上限，100 万档可能超时）；nightly 只跑阈值回归。
3. 夹具生成器入库并做确定性测试（同 seed 同 sha256）；夹具文件本身受 B11 门约束。
4. 各档基线以首轮实测固化。

**验收**：夹具生成器确定性测试通过；PG e2e 低档通过、nightly 阈值回归失败即阻断；基线阈值入库；json 输出可被 B6 消费。

### 评估池（不排期，挂相关评审窗口）

- **B8 机制件**：per-source token 预算与分层丢弃，见决策 5。
- **B10 声明式 stale 传播**：SF 的 stalePolicy 用 watches 多级哈希、下游传递、变更时暂停待作者，把失败从写入时刻提前到源变更时刻。
  评估 imports/evolution 管线在任务编排层声明 watches，与 B8 证据链同源设计。
- **D3、D5（含 D8）、D7、D9、D10**：见第五节。

## 四、规避清单（P 系列）

| 编号 | SF 的坑 | NC 落点 | 形态 |
|---|---|---|---|
| P1 | 明文 Key + 未转义注入点 | 渲染侧：禁字符串拼 HTML，markdown 一律复用 VNode 渲染器，禁引入产出 HTML 字符串的 markdown 库；入库侧：导入内容按不可信数据处理（现状已达标）；LLM 往返侧：入库内容进 prompt 一律走 fenced JSON 块，system scaffold 保持静态 | 红线 + `vue/no-v-html` 门 |
| P2 | token 估算常数化 | 新路径禁止常数估算，必须走 tiktoken | 评审项 |
| P3 | 流式解析静默吞错 | 解析失败须计数并落 receipt，禁裸 catch；`framing.py` 补计数（见低成本项）。provider SSE 由 openai SDK 解析，无裸吞 | 修复 + 评审项 |
| P4 | 子串/无锚点正则做语义判断 | 判断内容含义禁用子串或正则，走结构化字段或确认语义 | 红线 |
| P5 | 文档宣称与产品目录漂移 | 能力目录带成熟度分层与边界声明，README 功能导览从目录生成，对外话术以目录为准 | 评估 |
| P6 | 媒资与生成物入库失控 | 升格为 B11 | 门 |
| P7 | 功能进主干但发版停摆 | 保持“main 可达 commit 即可发布”；发布走 `release.sh` 固定 SHA；版本号不与营销脱节 | 纪律 |
| P8 | 巨型文件 | 行数门（见低成本项）；架构评审加“同管线平行实现”检查 | 门 + 评审项 |
| P9 | 分层反向依赖被 CI 默许 | B1 接 CI + B2 落地；豁免必须登记 | 门 |
| P10 | 级联删除弱防护 + 后台失败静默 | 新增级联删除的防护等级不低于父对象；worker 失败用户可见（receipt 承载）。与 ADR-0013 的张力见决策 7 | 评审项 |
| P11 | 类型/测试门禁盲区 | 引入类型检查或收紧 mypy 时一次性覆盖测试与脚本；评估分层覆盖率门槛 | 评审项 |
| P12 | 能力宣称照抄厂商 | 新模型默认未校准、不进业务路径；校准结论与事故（日期/现象/根因/防线）写进 `capabilities.py` 档案注释，如 32768 冻结预算的由来 | 纪律 |
| P13 | “去 AI 味”靠模型自评 | 若做风格化：禁模型自评作质量门，评估输入不截断，结论走人工或盲评账本 | 红线 |
| P14 | 国产浏览器/WebView 兼容事故 | 前端构建加目标 ES 基线检查与关键 API 兼容清单，发布前做内嵌浏览器冒烟 | 评估 |

## 五、产品机会（D 系列）

素材天然偏 A 画像：SF 的互动产品线全部是未验收的 preview，可转化给 B 画像的素材很少。B 画像改进需要另立输入源，
这是素材分布所致，不代表 B 画像优先级低。

**D1 零配置 AI + 成本就地可见**（B 为主，A 为辅；产品线）。现状：余额只在全局设置页，用量只在项目设置页。
剩余工作是生成界面内就地呈现，以及 B 画像“注册即用”。两个前置：

- 余额缓存。`infrastructure/llm/balance.py` 每次实时请求所有已连接 provider，无缓存（超时 15 秒）。挂到生成界面会把页面浏览放大成
  持续出站请求，须加 TTL、手动刷新、禁止自动轮询，并确认各 provider 限频政策。
- 成本基线口径。ai-usage 是项目级，默认扫描 500 行会截断，没有账户级跨项目聚合。先定义活跃用户、窗口与能力范围，
  基线才可复算；这是决策 4 的前提。

红线：成本基于真实余额与 token 计数，不估算货币金额。市场信号：SF 约 800 star/月、B 站教程 3.9 万播放，但 release
累计下载仅约 704 次，兴趣到安装被本地部署摩擦截断，这支持 NC“注册即用”的对位价值（推断）。

**D2 长期记忆质量公开可验证**。交付即 B6 首发与此后每次能力更新的证据纪律，不另立工程批次。

**D3 RP → 创作的证据化回流**（评估）。RP 分支中作者认可的片段带完整证据链，变成正文或设定的候选，走既有 candidate/adopt 语义，
默认建议制、作者确认制。姊妹评估：B 画像旅程内“把这段故事变成我的作品”入口（B→A 转化桥）。

**D4 编辑审读质量准入**（A 画像核心承诺的验收路径）。编辑审读已落地但默认关闭（`README.md:76`），
README `:277`、`:279` 自认真实质量尚未准入；语义审校（semantic_review）的开关现状在实施前复核。

1. 迭代参照 SF 9 类语义审校 issue 分类学（world-rule-conflict、character-motivation-break、causal-gap、continuity-conflict、
   pov-knowledge-leak、future-plot-leak、character-voice-drift、outline-deviation、unsupported-state-change），缺口即迭代清单。
2. 默认开启前须有数值证据：走既有 eval 工具链（`Makefile:123-132` 的 eval-judge / eval-review-export / eval-review-import），
   准入为“盲评 kappa ≥ 0.6，或采纳率提升 ≥ N 个百分点，且满足样本量下限”；N 与样本量在实施时定标并写入 B6 证据。
3. 准入评测需要付费真实模型运行，预算见决策 8。

**D5 跨设备“改得安心”+ 用户导出**（评估，吸收 D8 的发布 CAS 与可分发成品包）。设计输入：导出前完整性校验、导入预检严格拒绝、
恢复永不覆盖。导出必须先分层：作者备份格式允许 raw ID 与 hidden_truth，仅 owner 可导、仅用于恢复；
人可读分享投影过滤 hidden 层与角色知识边界。评估阶段就把边界写死，防止实施时默认全量导出；
ADR-0018 source revision 引用的物化方式一并裁定。分享投影的成品格式（现有 txt / md / md-zip，是否补 EPUB）作为子考量。

**D6 有限协作**。维持 ADR-0027 边界（单宿主、最多三名并发成员），不扩张为通用多人编辑。

**D7 正文 → 设定草稿的显式派生**（评估）。SF 的 deriveNovelToWorld 带源修订指纹、新鲜度校验、溯源行，源永不被修改。
NC 无对应，与 D3 互为镜像；须显式、单向、可回滚、可溯源，结合 ADR-0025 边界评估。

**D9 世界完成度投影**（评估）。把 ADR-0025 coverage 投影成世界工作台的导航面板，只做“哪里还空着”的导航，不承诺质量评分。

**D10 写作旅程体验**（随前端重设计验收）。SF 的实际卖点之一是旅程丝滑度和文案资产。NC 已有章级续作入口（TodayView），
缺口在三处：

- 章内位置恢复（回到上次光标或阅读位置）；
- 阅读舒适度：用户可控的字号、行距、对比度（主题包可带字体，但没有独立档位）；
- 叙事化的空态与错误文案（统一人称与语感）。

画像优先级原则第 3 条“降低继续写作时的上下文恢复成本”直接对应前两项，建议在前端重设计中优先评估。

## 六、待拍板

| # | 决策 | 背景 | 建议 |
|---|---|---|---|
| 1 | 短篇产品线 | SF 已发布，NC 无 | 显式不做，记录理由 |
| 2 | 改编产品线（剧本/漫画） | SF 两条已发布；报告该方向材料截断 | 显式不做；重启前先补齐调研 |
| 3 | 作者可编辑 Prompt 模板 | SF 作者可改模板；NC 与 prompt_contracts 有张力 | 维持工程契约优先。B3 已提供受控的“按作者口味调整”通道，看 B3 数据后再议 |
| 4 | 零配置 AI 的运营成本政策 | D1“注册即用”意味着平台承担模型费用 | 先完成 D1 成本基线；若平台承担费用，B5 升 P1 |
| 5 | 上下文预算机制是否从条目数演进到 per-source token 预算 | 报告点名的搬运首项；与 P20、tier 语义交互大 | 先做 B8 证据件，用逐源 token 数据判断条目数上限是否真造成失真，再定。做或不做都要书面记录 |
| 6 | 门禁阈值 | P8 行数门、B11 体积门 | 行数：>3000 告警，>5000 且高于基线失败；体积：单文件 1MB，单 PR 增量 5MB |
| 7 | P10 与 ADR-0013 的张力 | 首页轻量徽标、长生成切页返回仍可见进度 | 判断是否构成“全局任务中心”，仅评估不越界 |
| 8 | D4 准入评测预算 | 付费真实模型盲评 | 给出单次准入的调用与费用上限 |

## 七、风险与实施纪律

1. **推断项**：B3 的质量提升幅度、反例副作用、D1 的迁移动机、B7 的续写成本增长都是推断，各自已写明验证路径。
2. **现状漂移**：本版以 fa1ccc0 复核后又修正了 v5.1 的多处现状判断（附录 B）。开工前以当日代码复核是硬纪律。
3. **范围**：不修改 AGENTS.md 约束；新 LLM 路径一律经 `open_project_llm_client()`；novel_id 隔离与确认制不变；
   schema 或仓库结构变更同步 ORM、migration、调用方、测试和文档。
4. **复核中顺带发现、不在本方案范围的问题**（需 ADR-0025 owner 确认是否符合设计意图）：
   - writing 生成路径的 `_governed_generate`（`modules/writing/services.py:3667-3675`）不使用导演 plan 与 generator_keys，
     实际发送确认后的完整上下文；导演阶段的可见集收窄只影响审查，不影响生成。
   - 同一调用固定 `enforce_scope_complete=False`（`:3695`）。docstring（`knowledge/workflow.py:429`）称“作者已在确认界面显式接受预算裁剪”，
     但没有独立的“接受裁剪”记录。若“确认”动作本身即视为接受，建议在 docstring 写明。
   - 结构化调用无条件发送 `json_object`（`infrastructure/llm/client.py:1109-1110`）。白名单只有两个 deepseek 模型时无害，接入新 provider 前须处理（B5 前置 3）。

## 附录 A：SF 资产去向

| SF 资产 | 去向 |
|---|---|
| AI 入口注册表 executionBoundary / allowedCallers | B1（接 CI；字段随消费方落地） |
| check-architecture 架构门 | B2 |
| 作者好例/反例 | B3 |
| 连续性保护块信封 + 发送前校验 | 前提不成立，撤销；回归测试并入 B8 |
| 每源 token 预算 + 截断 + 分层丢弃 + per-source sha256 | 证据件 → B8；机制件 → 决策 5 |
| task-routing / provider 能力矩阵 fail-closed | B5 |
| release-evidence.json / 证据边界自我克制 | B6、D2（claims_boundary） |
| long-form-scale-gate 三档夹具 | B7 |
| 图片 requestHash 幂等 + 媒资内容寻址 | B9 |
| stalePolicy / watches | B10（评估池） |
| 媒资入库失控教训 | B11 |
| 9 类语义审校 issue 分类学 | D4 |
| 八类冲突分类学、发布 CAS、分发包 bundleHash | D5（含 D8） |
| deriveNovelToWorld | D7 |
| world readiness 投影 | D9 |
| ResumeTracker、文案资产、五层备份的体验面 | D10 |
| 能力成熟度分层 + 边界声明 | P5 |
| 事故驱动防御留痕 | P12 |
| 平台级方法论写进 system prompt | B3 同步契约时评估，与作者级示例分层，勿混同 |

仅记录、暂不处理的低频项：

- ChapterContinuityHandoff 结构化交接对象（续写迭代时参考）；受控谓词事实账本（world 域评审时参考）；
- SSE 32ms 合帧（前端流式优化）；ui-preview 样例目录（前端工具链评审）；雾港 demo 复用真实流水线（公开 demo 评审）；
- source-reachability 死代码门：不做（见 B2）；
- 章节重排的身份迁移：SF 以稳定 ID 作时序身份。NC 多处以 chapter_index 作 scope 身份，若做章节重排须先迁移历史检查记录与事实引用；
  当前没有重排功能，风险未激活；
- embedding 同维度换模型：NC 已检测维度不匹配，但同维度不同模型未拦截。当前自托管单模型风险低，
  索引状态页补一行“已索引 provider/model ≠ 当前配置时标 degraded”即可。

## 附录 B：修订记录

**v1–v5.1（2026-10-01 至 10-02）**：初稿忠实转化报告第十三章，经五轮子代理评审迭代。主要演进：B1 从新建注册表改为扩展
ADR-0025 注册表；B2 实测存量 53 条；B4 改为编译期 payload manifest；新增 B8–B11、D7–D10、P13–P14、短篇与改编决策；
全部验收改写为可判定口径。

**v6（2026-10-02）**：重写为结论先行、按批次排列的版本，去掉行内版本标注；以 fa1ccc0 复核后修正：

1. **B1**：基线“绑定扫描已进 CI”不符，CI 与 pytest 都不跑真实树扫描。B1 改为接 CI（P0，半天）。三字段无消费者，
   execution_boundary 与 adoption_gate 等重叠，allowed_callers 与文件级绑定重叠，取消独立排期。
2. **B4**：前提不成立。创建确认时 blockers 拦截；执行时按确认重编译并比对指纹（覆盖 sections 内容与来源）；
   发送的是冻结的确认内容。`enforce_scope_complete=False` 只决定 omission 是否在导演前失败，不影响发送内容。撤销，回归测试并入 B8。
3. **B8**：逐源证据底座已存在（receipt 逐源 content_hash），收窄为补 token 数、截断标记与正文哈希。
4. **B11**：`.test-logs` 为一次性入库、被引用的证据，不清理；补计 v5.1 漏掉的 `docs/plans`（11.7MB）与 e2e 截图（8.5MB）；
   受版本控制体积实为 105MB；删文件不缩历史。改为增量门 + `.agent` 规则 + 孤儿图片清理。
5. **B3**：先例存储是 `Project.settings` JSON 而非独立表，首版免 migration；editorial brief 为 P3 会整段逐出，补 tier 决策与逐出可见；
   单能力首版；补反例风险与观察性统计的局限。
6. **B9**：补“重新生成”绕过复用。
7. **B5**：账户层单模型、全局设置禁改模型、白名单仅两个 deepseek 模型、`json_object` 已无条件发送，据此修正前置描述；
   降为 P2，与决策 4 联动。
8. **数字与行号**：CAPABILITY_BINDINGS 50 条（原写约 40）；CAPABILITY_REGISTRY 66 条；`_attempt_object_key` 在 `:1756`（原写 `:1974`）；
   余额端点为 `/account/settings/llm-balances`；创建确认时 blockers 抛 ValueError（ConflictError 只出现在助手工具预览路径）；
   生产代码超 3000 行的文件为 7 个（含 `frontend-console/api.js`）；D10 已有章级续作入口；evolution_scale_harness 未接入 CI；
   前端 v-html 只有两处局部测试断言。
