# 审读与修订链路改进设计

> **供决策的设计稿；不是实施授权。**现状截至 2026-10-16，依据当前工作树代码。本文只在本任务目录起草；未修改代码、提示词、方法文本、权威文档或评测数据集，也未调用业务模型。

## 摘要与建议

本项目已有一条有明确授权边界的审读闭环：作者保存编辑约定并选择审读范围；Assistant 顺序执行读者层和作者层，只有带当前正文唯一引文、必要时带可回读世界/结构依据的意见才进入报告；作者自行处置；选定引文后 Writing 只生成局部替换候选；作者审阅并采用后，Assistant 再给“仍在 / 可能改善 / 无法判断”的改后复核。语义审查则服务 AI 正文候选及采用门禁，和作者编辑台的 `editorial_suggestion` 不是同一类回执。

首轮改进建议是先收紧诊断方法并减少意见负担，不先增造一套“11 类错误”产品分类：让审读明确区分作品承诺、文本证据、读者可理解性、个人口味和未核实事实；把“不足以回看未标注线索”明确列为当前能力边界，若要真正搜索回看线索，需另设计有来源约束的定向回读；加入最小修订和不应报告清单；不再为每条意见机械要求 2–3 个方案。现有类别继续表达“编辑发生在哪一层”，严重度继续表达“处理影响”，二者都不等同于失配类型。新增独立的 `mismatch_type` 可作为下一阶段候选，但应先由本报告的合成评测验证其能改变作者处置而不增加误报、拆碎根因或增加负担。

读者模拟只能生成待核对的读者体验假设。研究已显示，模型可能给出具体却漏掉最大问题的意见，长故事的连贯性判断会退化；通用评审偏差和文风趋同证据值得测试，但并不等于已经证明模型会偏好某个小说文风。意见采纳率、语气或清晰度都不能单独证明修订更好。设计必须保留来源重验、失效判定、作者选择、候选独立复审和采用确认。

**当前代码事实纠正：**用户提示中“桥接只取首条依据、跨章其他依据不进入批次”已不适用于当前工作树。`IssueRevisionItem.evidence_indices`、前端多选和 Writing 按章分任务都已允许作者选择多处、跨章依据；仍然只做被选范围的替换，不提供全局结构改写。`assistant/README.md` 对“首条依据”的描述过时，本轮不改它，列入文档同步候选。

## 1. 范围、输入与证据口径

### 1.1 输入

- 主输入《文学创作与长篇小说中的常见失误：条件式诊断报告》：以作品目标、体裁/读者承诺和具体阅读效果的失配为判准；列出 8 步诊断、6 类失配、11 个领域和常见口诀的边界。详见 `T-20261016-literary-writing-errors/RESEARCH.md` 第 2、3、5 节。
- 辅助输入《文学与长篇小说创作技法》：强调不把修订流程固定成唯一流水线，先检查结构承诺、因果和人物关系，再依据目标读者检查；见 `T-20261016-literary-craft-research/RESEARCH.md` 第 4、5 节。
- 产品边界：`docs/product/user-personas.md` 的画像 A；目标作家写长篇、重视复杂设定和历史可追踪性，想要可编辑、可撤销的意见，不愿被迫维护低价值字段，也不接受 AI 静默改正文或正史。
- 代码事实以 `codex/guided-flow-borrowing` 当前文件为准。未把 README 旧表述当作运行事实。

### 1.2 证据分层

| 层 | 可回答的问题 | 不能单独证明的事 |
|---|---|---|
| 项目当前代码、schema、测试与调用链 | 实际接受什么输入、由谁调用、做哪些校验、作者在哪确认 | 文学意见真的准确、有用或被作者接受 |
| 叙事理论、文学细读、作家/编辑实践 | 可用的分析概念、例外、工作方法 | 一套普适小说质量分数或最佳流程 |
| 读者/写作实验与语料研究 | 特定文本、样本、模型、任务中的理解或改写效果 | 所有读者、长篇连载或中文小说都同样反应 |
| 编辑协会标准、专业服务定义、出版社流程 | 现实中常见的编辑职责和术语边界 | 严格固定的产品流程，或某顺序有因果优势 |
| AI 作者/编辑研究 | 现有模型在限定任务中的意见、改写和作者体验风险 | 本项目当前模型已出现同样幅度的错误或声音损害 |

直接针对中文长篇小说、专业编辑一致性、创意作者意见采纳和多轮修订声音保留的研究仍少。报告中的“常见”沿用输入报告口径：来源反复讨论的风险，不是本项目或行业的发生率估计。

## 2. 当前链路盘点

### 2.1 作者编辑台与意见展示

**输入。**`ReviewSubmit` 冻结项目、单章/区间/全书范围、审读维度、排除章节、操作幂等标识和当前编辑约定版本；worker 绑定工作稿 ID/hash、约定版本、排除范围与不含密钥的模型快照。单段 12,000 字符顺序近读，跨章合并最多八个节点逐层汇总，受每任务请求预算约束。`assistant/editorial.py:278–370, 1340–1410`；`assistant/README.md:269–288`。

**模型输出。**`ReviewPass` 含 `summary`、`reader_state`、最多 8 条 `ReviewFinding`。finding 的 `category` 是 `structure / scene / line / copy / reader`，即编辑层次；另有 `judgment`、`reader_impact`、`severity=high/medium/low`、正文 `evidence`、可选 `context_evidence`、`counterevidence`、`intent_relation/intent_quote`、`why_now`、`unchecked` 和最多 3 个 `directions(approach, affected_chapters, tradeoff)`。`editorial_contracts.py:125–175`。

**读者层与作者层。**读者层只见当段正文和此前 `reader_state`，不见后文、作者约定或私有资料；其 finding 只能是 `reader`。作者层见当段正文、项目编辑约定，以及结构/场景维度可回读的世界资料和大纲。作者意图关系必须逐字命中冻结约定，否则服务端清空该关系并标为未核对。读者层结果没有单独作为 `reader_state` 返回给前端；状态只用于下一段阅读。`editorial.py:52–62, 1042–1106, 1443–1504`；`view()` 在返回的报告里不包含 `reader_state`，见 `editorial.py:396–438`。

**确定性校验。**正文引文须在冻结正文中唯一出现，范围/章节/片段一致；上下文引文须属于已物化的 World/Story 来源；来源发布前再验。缺失范围、缺依据、未核对项及高严重度有未核对事项时，均显式保留或降级，不能靠模型自信越过。只读意见保存为 `editorial_suggestion`，不写正文、不记 Writing `independent_review`，也不成为正式事实。`editorial.py:955–1107, 1204–1245`。

**作者看到并能做什么。**报告先显最多 3 条，其余折叠；卡片显示编辑类别、严重度、影响、原文、上下文、反证、与作者约定的关系、未核对事项、方向与代价。作者可定位、处置为准备/稍后/刻意安排/判断不成立/自行修改/关闭，或在明确选中的意见上发起修订。前端 `EditorialDesk.vue:39–79`；`EditorialIssueCard.vue:1–31,43–46`。`_rank` 先排没有 `unchecked` 的 finding，再按不同证据章节数、精确作者意图引用、证据总量、模型严重度排序；`_assign_identities` 是意见稳定身份/去重，不是语义根因聚类。`editorial.py:84–141,1194–1201`。

**改后复核。**复核只在与原意见绑定的现稿与约定仍有效时运行；检查相关节选、重验原文及引用，输出 `still / possibly_improved / unknown`。模型不负责宣布解决；“仍在”若无新证据会被服务端改为 `unknown`，作者才决定是否关闭。`RecheckOutput` 见 `editorial_contracts.py:177–183`，调用和输出校验见 `editorial.py:590–678, 680–864`。这是当前可复用的三态语义，不建议改为二态“通过/未通过”。

### 2.2 Writing 语义审查与定向返修

**输入。**`WritingSemanticReviewRequest` 选正文草稿及 `selection / volume / book` 范围。审查冻结目标稿、相邻章回归资料、Scene 执行包、AI 候选的原 confirmation、已物化 Context/hidden guard 指纹。AI 正文只在其原 confirmation/范围有效时检查知识边界；没有 confirmation 的人工正文可以 prose-only 审查，但不能宣称检查了人物知识边界。`writing/schemas.py:431–445`；`semantic_review.py:583–728, 971–1040`。

**输出。**finding 的类别为 `contract_omission / pov_boundary / continuity / causality / character_voice / pacing / literary_quality / copy_error`，严重度为 `blocker / major / minor`，带唯一正文 `excerpt`、`contract_refs`、带 hash 的世界证据和 `preserve`。另有每草稿 `coverage`、`not_checked`、Scene must_happen 条目 `met/unmet/unknown`。类别是已注册的语义检查面，不是“错误分类”。`writing/schemas.py:453–533`。

**模型可做/不能做。**模型可以对当前 candidate 提交需核实的意见和覆盖声明；服务端验证坐标、正文引文、范围外输出、各适用覆盖项、确定性 POV guard、来源指纹。任何 blocker/major 可令 candidate 进入 `needs_revision`；缺少适用 coverage 为 `incomplete`，不可签 PASS。它不是对作者全书审稿，也不联网查外部事实。`semantic_review.py:1042–1077,1190–1413`；`writing/README.md:260–282`。

**返修。**只有作者选择了属于指定 AI candidate、原正文/Context/Scene 合同仍新鲜的 finding，或显式纳入带位置的待核实合同条目，才能提交 `WritingTargetedRevisionRequest`。模型每个 `patch_id` 只返回 replacement；代码只替换选区，随后重跑 hidden guard 与独立语义审查；采用门禁不因返修而放松。作者在写作页审阅并采用，AI 不写回原稿。`writing/schemas.py:536–575`；`semantic_review.py:143–192,1616–1779`。

### 2.3 批注修订与设定提案

作者可显式启动一批手写批注修订，或让已有语义审查先生成批注；AI 自动纳入的仅为可精确定位的 blocker/major。批注位置、稿件 hash 和范围 hash 由代码检查；重叠选区合并前须作者确认。`comment_run.py:52–94,97–145,154–205`。

修订模型只接收所选范围、前后各 500 字上下文和所选批注，系统提示限定为给指定 `patch_id` 返回替换，不改范围外文字、不建世界正史。产物是另存候选；通过治理审查后还要独立语义审查，作者再审阅采用。失败不提供候选，来源变化丢弃过时结果。`comment_run.py:208–339`；`writing/README.md:284–304`。

助手可另起一次无联网会话，为正文批注准备 World/Story 设定方案；操作目录仅开放相应 World/Story 操作，输出仍是作者确认的提案，不证明正文意见正确，也不自动写资产。`assistant/comment_proposals.py:19–74`；Assistant README “领域提案与受控恢复”。

### 2.4 协作审稿与盲读

`deep_review` 对作者明确选中的单章运行三个只读调查角色：事实/规则、人物动机/知识、叙事结构/读者信息；每个成员输出 `Investigation(summary, findings, read_evidence_ids, checked_dimensions, omissions)`，findings 带 `claim/category/severity/claim_type/evidence/counterevidence/assumptions/uncertainty/suggested_repair`。蓝图 v2 冻结连续性、人物知识和世界规则方法文本及 hash。不同成员的报告不是投票通过；深度审稿将假设交 Writing 现有语义审查复核，最终由主编汇总并保留遗漏/争议。`deep_review` 本身不提交可采用的 action/plan，也不写正文。若用户之后走其他有可执行操作的蓝图，确认仍走既有批次协议。成员工具只读，联网关闭。`teams/contracts.py:16–73,81–115,138–156,220–254`；`teams/review_methods.py:10–38`；`teams/runner.py:304–390,451–475,550–636`；`assistant/README.md:122–148`。

冻结方法要求追踪来源、时间/状态、人物如何获得知识、规则前提/代价/例外，并主动找反证；无资料则写“未检查”，有意歧义不由票数或模型身份裁决。`blind_reader` 最多连续盲读 8 章，不得带作者 Context 确认包；每章输出 `ReadingNode(known, guesses, unanswered, newly_revealed)`，每个 ReaderBelief 带原文摘录和解释；新揭示不能回写过去节点。它是读者体验探针，不是连续性事实裁决。`story/observations.py:17–28`；`teams/blind_reader.py:21–52,90–163`；`assistant/README.md:135–148`。

### 2.5 `editorial_revision` v1 与桥接现状

流程是确定性薄编排：审读台选意见与处置 → BR-4 批注修订 → 停在候选供作者审阅 → 作者在写作页采用 → 自动请求改后复核 → 作者查看三态结论并结束。流程不自带额外审读 Agent、不做多意见语义融合、不自动采用。`guided_flow/flows.py:293–347,1725–1819,1989–2115`；`assistant/README.md:231–235`。

当前 UI 对每条意见让作者勾选一个或多个原文依据，允许跨章锚点；Writing 按章创建独立修订任务。正文 hash 不匹配时失败关闭；无法唯一定位的锚点逐条说明；重叠选区要求确认。**限制是只替换选中的局部范围，没有“先改总纲/重排结构”的返修承载方式，不是只能用首条引文。**`editorial_contracts.py:68–105`；`editorial_bridge.py:87–196`；`writing/facade.py:343–364`；`writing/comments.py:227–365`；`EditorialDesk.vue:62–77,163–180,347–365`。

`assistant/README.md:295–305` 和 `editorial_bridge.py` 模块说明仍称每条意见使用“首条原文依据”、跨章其余依据不入批次；这与当前 `evidence_indices`、前端勾选及按章分任务实现不符。建议后续只修文档说明并加合同级测试固化多证据/跨章选择；本轮遵守不改权威文档边界。

## 3. 分类对齐：不要把三种现有 category 当成失配类型

`ReviewFinding.category` 是**编辑层级**；`WritingSemanticReviewFindingDraft.category` 是**具体检查项**；两者都不是“为什么这件事值得报告”。`severity` 又是后果/紧急程度。三者不应互相重命名或一对一转换。尤其 `blocker/major/minor` 会影响 AI candidate 的 PASS/采用路径，绝不能把编辑台 `high/medium/low` 或“读者不喜欢”直接映射成 blocker。

| 输入报告的失配类型 | Editorial category 候选 | Semantic review category / coverage 候选 | 严重度与作者口径 | 设计判断 |
|---|---|---|---|---|
| 硬矛盾 | `structure` 或 `scene`；如果只是读者误认可为 `reader` | `continuity`、`pov_boundary`、`contract_omission`，也可能只是某 coverage 发现未覆盖 | 只有两条陈述不能同时成立、且版本/视角/谎言/时间差等替代解释已检查，才可建议高优先；Semantic blocker 仅由其现行候选门禁决定 | 不自动等同于严重度高；先验证范围和反证 |
| 因果缺口 | `structure`、`scene`，局部文字可能为 `line` | `causality`、`contract_omission`、`ability_world_rule` | 看缺口是否改变关键人物选择、解法或结局；一个模型猜不到的中间过程不等于因果断裂 | 可做结构解释，不能靠只改一段措辞假装修好 |
| 理解摩擦 | `reader`；造成摩擦的具体位置也可归 `scene/line/copy` | 无专门类别；可能与 `pacing`、`literary_quality` 或 `copy_error` 重叠，coverage 只表示检查了什么 | 说清“读者在此形成了什么理解/无法形成什么理解”；区分读不懂和读懂但不喜欢 | 把读者反应作为证据假设，不将模拟读者当真实读者抽样 |
| 目标失配 | 可落到 `structure/scene/line/reader`，取决于文本位置 | `contract_omission`、`pacing`、`literary_quality`、`character_voice` 等 | 约定或体裁承诺必须有保存证据；作者写过某意图不证明其已实现，也不自动证明失败 | 这是最需要“失配类型”说明的类；不能只报偏好 |
| 审美偏好 | 可能被装入 `line/copy/reader`；现有字段不能标出“理解了但不喜欢” | Semantic 的 `literary_quality/pacing` 也不代表偏好 | 默认过滤，不进问题卡和严重度。作者明确提出本轮风格建议请求时，才作为独立、低优先、不可自动桥接的可选观察；选中 `line` 不算 opt-in，因为该维度默认勾选 | 目前 ReviewSubmit/UI 没有本轮偏好请求信号；若要开放，需新增默认关闭的一次性入口和兼容字段，不能靠模型猜作者授权 |
| 伦理风险 | 当前没有专属类；不应塞进 `reader` 伪装成普通可读性，也不应强行塞进 `structure` | 当前没有伦理类别，`literary_quality` 不能代表伦理裁定 | 单列、条件式、非指控语气；不以单一风险分代替语境；不做“伦理通过”承诺 | 若提供，采用作者主动选择的再现/视角入口，并鼓励目标读者/相关经验读者检视 |

**是否新增维度：**建议保留“失配性质”作为独立设计轴，但不在首步强制新增六类必填字段。先用提示词/离线样本确认它确实让作者分得清“文本错、阅读有摩擦、目标没兑现、只是口味、需事实查证、伦理观察”，且不造成更多卡片。通过后再考虑可选 `mismatch_type`，默认 `unknown/not_assessed`；它仅是 LLM 候选标签，不写事实账本、不决定 severity、不触发返修或采用。若用户认为六类标签对其处理意见无帮助，可不加字段，继续把分类用于离线评测。

## 4. 八步诊断法落点与缺口

| 报告诊断步骤 | 当前体现 | 缺口 | 建议落点与机制 |
|---|---|---|---|
| 1 写清作品承诺 | `EditorialBrief` 有 `target_readers / genre_promise / goals / voice / preserve / intentional_choices`；作者保存版本；作者层收到冻结约定 | 约定是自由文本，没有明确区分“明示承诺、反复建立惯例、审读者习惯”；匹配精确 quote 只证明作者写过，不证明正文达到效果 | 先改 `editorial.py` 方法文本：每条意见标明依据是显式约定、文本重复建立还是仅为读者预期；后者不得报告成内部错误。作者保持可选填，避免画像 A 被迫新增必填字段 |
| 2 定位文本信号 | finding 必须给 1–4 条正文引文；服务端检验唯一定位；作者/读者引用范围分离 | 目前没有要求模型把“观察到的句子”和“由此推断的问题”用短句分开 | 用现有 `evidence + judgment` 提示模板；数据边界已有，先不增加新 evidence schema |
| 3 说明预期影响 | `reader_impact`、`why_now`、`severity` 已存在；前端显示 | `reader_impact` 是模型预测，不是测得的读者结果；读者状态本身不对作者显示；“不懂/懂但不喜欢”没有专门结果定义 | 提示词要求写“读者可能如何理解/困惑”及依据；若只是偏好，标明它是个人审美而不入问题清单。评测分别评分“误解风险”和“理解后不喜欢” |
| 4 测试替代解释 | `_SYSTEM` 明确允许留白、误导和错误信念；`counterevidence`、`intent_relation`；团队冻结方法主动查反证 | 没有把反例验证拆成可审查的短步骤；段落级读者层看不到作者 intent 是正确隔离，但作者层只看到文本/brief，不自动获得读者真实反馈 | 方法文本规定在下严重度前检查有限视角、延迟揭示、不可靠叙述、群像/单元结构、讽刺、主题/类型惯例等；模型最多给出一条“尚未排除的解释”，不无限列可能性 |
| 5 查找回看线索 | `counterevidence` 可记录已提供的反证；blind reader 严格顺序阅读，不用后文改写早先状态 | Editorial 每段按 12,000 字符局部处理；跨章 synthesis 仅收章节摘要和既有 findings，允许引用的句子也只来自这些 findings，不能搜索从未成为 finding 的旧线索 | 当前提示词只能复核本轮实际提供的证据；未提供旧线索时必须标“未核对/无法判断”。真正回看需新增作者选定范围内的定向检索/回读步骤，绑定原文来源、范围与 hash，复核后再引用，并把额外请求计入预算 |
| 6 按后果定序 | `_rank` 当前先按未核对状态、证据章节数、作者意图引用、证据数，再看模型 severity；报告/UI 默认先显示 top 3 | 这些前置项是来源/覆盖质量或范围信号，不等于优先级；章节数不证明同一根因反复伤害理解，intent quote 只证明声明命中，不证明问题严重。现有字段也没有可由服务端确定性计算的“关键行动后果” | 将当前正文/范围/精确引文/coverage 作为确定性准入与可信度检查，不当优先级。其后只把 LLM 的 severity/why_now 当候选影响判断，不能由服务端从文本推断“关键后果”；先离线比较现排序与 severity 优先的稳定排序。反复伤害理解须先证明是同一根因，不可用章节数代替；证据不足不提升。若收益不稳，保留当前排序。 |
| 7 提出最小修订 | `ReviewDirection` 有 approach、受影响章节、tradeoff；作者批注桥接只生成选区 replacement；作者必须选 evidence 和写 instruction | `_SYSTEM` 要“尽量给 2–3 方向”，服务端将少于 2 条标 `unchecked`，可能驱动多方案；没有最小修改 / 回大纲 / 作者先定方向的修订尺度 | 改提示词为“先给一条最小有效路径；只有真实取舍时才补一个备选”；`directions` 允许 0–2/沿用 max3，且不能仅因只有 1 条就降级。跨章/结构/事实/伦理类别明确标记“先由作者定方向”，不自动送局部 patch |
| 8 必要时目标读者试读 | 读者层角色扮演模拟首次阅读；独立人工评估列入已有六项评分与真实模型计划 | 模型模拟不是真实读者；当前评测包的零费用预检强调评阅者独立，但任务不运行真实读者 | 样本盲评至少 2 名独立读者/编辑；记录理解、偏好和分歧，不把单人/多数票升为绝对真相。作者最终选择仍是产品边界 |

## 5. 十一个领域逐项映射

表中 `[E]` 为输入报告所依据的叙事理论/创作论/读者研究/行业材料；`[C]` 为本项目代码现状。复合来源和证据边界以主报告各节为准；“审读层级”明确哪些是 reader pass、author pass、确定性校验或作者另启的外部流程。

| 来源条目与证据类型 → 落点 | 审读层级 / 来源 | 现状（代码为准） | 机制类型 | 作者看到的形式 | 主要误报风险 | 验证方式 |
|---|---|---|---|---|---|---|
| **1 结构、因果、伏笔与结尾**。[E] 失误报告 3.1；叙事理论+创作个案，明确松散/单元/开放结尾反例。→ E `structure/scene`；SR `causality/continuity/contract_omission`；Story outline Evidence。 | 读者 pass 观察实际阅读摩擦；作者 pass 对照 brief/outline；服务端只校验范围、引文和来源，不判因果真伪 | E 作者层读 World 与 `scenes/arcs/plot_threads/foreshadowing/reveal`；方向字段可以跨章。SR 对 candidate 按 Scene 合同/连续性/因果产 finding，但不是全书总纲意见。 | LLM 待处理建议；证据来源/覆盖检查为确定性；是否改结尾、支线或结构由作者决定。 | 1 条根因意见+当前输入已提供的关键转折/伏笔引用；未提供旧线索时标未核对，不要求模型列出无法检索的线索。若未来增加回读，须先确认范围再复验来源；跨章方向先回作者结构决策。 | 把单元式、流浪汉式、留白结尾误判为失效；把伏笔未立刻解释当作遗漏；把不熟悉的因果当作不存在。 | 正例中存在无法推出的高潮解法；负例为铺垫后兑现、开放结局、松散但有主题连接的篇章；评分反例误报、遗漏和修订层级。 |
| **2 人物目标、知识、关系与能动性**。[E] 3.2；读者实验+叙事学+人物反例。→ E `structure/scene/reader`；SR `pov_boundary/continuity/character_voice`+知识 coverage；Teams `characters`。 | 读者 pass 观察当前理解；作者 pass 对照目标/关系/已授权来源；Semantic review/POV guard 只处理绑定候选的边界 | SR 只有 AI candidate 有有效 confirmation/角色视角时才签知识边界；deterministic POV guard separately reports confirmed hidden-boundary hits。Deep review 的人物方法区分事实、信念、推断、谎言。 | 知识边界来源/确定性 guard 优先；动机/关系/弧线是 LLM 待处理建议；人物要不要变化、能动性要多强由作者决定。 | 明确引用“先前目标/知识/关系”与当前行为，说明信息源或触发过程缺哪一段；报告“行为差异”而非“人物必须成长”。 | 把稳定/扁平/被动人物当坏写作；作者/叙述者全知投射给角色；角色变化被期待读者弧线模板支配。 | 设“有意稳定角色”“被制度限制的被动角色”“确实未获信息的角色”配对样本；核对 POV coverage 不可越权签署。 |
| **3 场景、节奏、悬念和信息**。[E] 3.3、横向网文部分；叙事理论+有限读者实验；输入明确说“每场主线推进/每章钩子/五感齐全”不是硬律。→ E `scene/reader/line`；SR `pacing/literary_quality/copy_error`；T `blind_reader`。 | 读者 pass 给顺序体验假设；作者 pass 对照作品目标；Semantic review 仅处理其已绑定候选 | E 可顺序维护读者状态；SR 查看 scene contract 与相邻回归上下文；无“钩子”语义类别。前端 top 3 再折叠其余。 | 读者角色给体验假设；场景/类型匹配为 LLM 建议；结构节奏与连载钩子由作者决定。 | 指出读者“现在在等什么/知道什么/失去了什么”，而不是单纯“慢”；如果是理解问题，标阅读阻碍；若理解后不喜欢快慢/中断，标偏好。 | 将停顿、日常、劳动、仪式、回环、完整章节结尾误判为低效；移植短篇 cliffhanger 实验结论到网文长篇。 | 配对有意重复/无功能重复，完整钩子章节/闭合式章节；测“理解对错”和“个人喜欢”两类标注，不合并。 |
| **4 叙述者、视角与可靠性**。[E] 3.4；叙事理论+有限视角实验，尚无“head-hopping 错误”直接实验证据。→ E `reader/structure`；SR `pov_boundary` + deterministic POV；T `blind_reader` 与 `deep_review` methods。 | 读者 pass 观察可见视角与理解；作者 pass 对照声明/来源；确定性 POV guard 与 Semantic review 只在各自授权范围检查 | SR 会将已确认隐性知识 guard finding 合并；非-character reveal 不声称检查知识边界；blind reader 没有作者私有资料。E 允许误导/错误信念但无专门 unreliable narrator 标签。 | 规则/POV guard 确定性；叙述者可靠性需文本证据的 LLM 待处理建议；是否保持不可靠由作者决定。 | 用“这段叙述把谁当作知道/感知者？”表达，不把人物误信念当作者事实；显示反证与未覆盖段落。 | 将叙述者和人物声音重叠、全知/合唱、自由间接话语当作错位；用外部模型知识填未来答案。 | 相同事件配上明确可靠 narrator 与不可靠线索；负控为切换视角有标记、叙述者全知。测试证据位置变化。 |
| **5 世界设定、环境与行动条件**。[E] 3.5；世界设计理论/作者规范，强调环境和制度改变行动条件但不需百科式完整。→ E `scene/structure/line` 可引用 World/Outline；SR `ability_world_rule` 与 world evidence；Story 设定只读。 | 读者 pass 观察信息效果；作者 pass 对照 World/Outline；来源版本/范围由服务端重验；内审不联网 | E 仅在结构/场景选项请求中物化 World/outline sources；SR 对 AI candidate 重读原 confirmation，人工正文只可 prose-only 或显式手工 world scope。内部审读未联网。 | 引文/hash、规则版本/coverage 为确定性；虚构规则与空间作用是 LLM 建议；世界规则是否采纳为作者决定。 | 显示引用的规则、地图/场景前提、遗漏；不把“没有把所有细节写出来”当问题。 | 缺少地图/系统上下文造成误报；“设定必须推动剧情/环境要写满五感”的套路；事实错误与内设不一致混淆。 | 同一行为在来源完整/不完整、地图有效/未覆盖、现实法则/架空规则中成对测试；外部事实样本只能报待查。 |
| **6 长篇连续性与系列状态**。[E] 3.6；出版编辑访谈+Situation Model 读者研究。→ SR `continuity`、timeline/space/logic coverage；Writing conflict check/Story Continuity/Evolution；E 只用已读正文与可回读 outline/world。 | Editorial 作者 pass 对照正文、brief、World/Outline；Writing conflict/semantic 各自检查覆盖；Story checkpoint 当前不进入 Editorial | 现有 Writing conflict check 可基于可信 Scene checkpoints 做空间/时间/逻辑候选，并对覆盖与缺失分开；Story V2/ Evolution 提供状态/来源/失效链。E 当前**不读 Story Scene continuity checkpoint**，只读世界资料与大纲；SR 对 AI candidate 按 Evidence confirmation 查连续性及适用 coverage。 | 已确认/系统来源 state 的校验与 hash 是确定性；Evolution 是受限事件/状态传播，不是文学评价；正文叙事连续性仍是 LLM suggestion。 | 当前只能指出已实际提供的 World/Outline 依据或声明尚未对照 Story continuity receipt；Editorial 没有读取该 checkpoint。未来若接入回执，须注明确认状态、版本与 coverage；同根因只在来源支持时关联。 | 把错误/待决事件当 canonical；重复发出 Writing/Story 已经有的同一状态提示；未经确认的状态被当事实。 | 用相同事件分别标记 confirmed / system-derived / hypothesis / stale；比较模块回执数量与 editorial findings 的重复率；验证 stale 不能进入当前意见。 |
| **7 语言、对话、人物声音与修辞**。[E] 3.7；文学细读/语料研究/编辑经验；“禁副词/被动”不作硬律。→ E `line/copy/reader`；SR `character_voice/literary_quality/copy_error`；Writing comment revision。 | 读者 pass 与作者 voice/preserve 分开；确定性检查只验证引文/选区，不裁定风格质量 | E `voice/preserve/intentional_choices` 可进入作者层；E finding 没有 `preserve` 字段。Semantic finding 有 `preserve` 并给定向返修。Editorial BR 传 `judgment + reader_impact + author instruction`，不传原 `directions/preserve/intent_relation`；局部替换有范围边界，但没有自动风格量表。 | 拼写/范围 hash 为确定性；风格和声音为 LLM 待处理建议；原文、候选差异、是否采用由作者决定。 | 行文层的问题须与可选风格偏好分开；目前 line 默认开启，不能当作明确风格邀请。若作者本轮 opt-in，单独呈现中性风格观察，不生成错误卡；局部替换前由作者选范围与指令。 | 提高流畅度但抹掉节奏、口语、断裂、重复、留白；把作者声音简化成词频指标。 | 使用同义不同风格配对样本；盲评是否保留人物意图、句法/节奏与有意重复；量非目标改动率，另测作者声音判断。 |
| **8 主题、价值冲突与观念表达**。[E] 3.8；文学理论/作家创作论，明示不要求一句主题句。→ E `structure/reader/scene`；SR 暂以 `literary_quality`/`character_voice` 承载部分发现。 | 读者 pass 可给理解/反应假设；作者 pass 对照声明与行动后果；没有确定性主题裁定 | 当前无主题/价值专类；reviewer 可基于作品目标引用已有文本；E 无权裁定作品“主题正确”。 | 只有作品自己建立的价值问题与其行动/后果矛盾时，才给 LLM suggestion；主题多义、无单句答案由作者决定。 | 给出文本如何呈现两种读法，指出“说法/行动/后果”的证据，不写成道德裁决或让角色都替作者辩论。 | 把未表态、多义、悲观、反高潮、反英雄当成缺陷；审读模型把个人道德偏好当创作目标。 | 有/无明确主题约定的同稿；测试“说法与行动矛盾但有意”与“作者明示的价值冲突未兑现”；多人标注保留分歧。 |
| **9 计划、写作流程、修订与反馈**。[E] 3.9 与 craft report §4；写作过程研究/工作坊材料，证据不支持固定流水线。→ F `editorial_revision`，ReviewDirection/author dispositions；Team `deep_review/cross_revision` 是显式路径。 | 作者在 UI 选择处置；finding 身份与现有排序由服务端稳定生成；意见及方向仍是 LLM 待处理建议 | 作者可先看 top 3、按一条或多条意见发起修订、自己填写处置；待候选再决定采用。当前模型要求“尽量 2–3 个方向”，且 fewer than 2 directions 会标未核对；意见身份证明不是因果根因。 | 意见排序/回溯是确定性；意见解释和建议是 LLM；收/改/拒/延后与改稿层级由作者决定。 | 少量根因簇先显示；需要时展开证据/同类实例；每簇先给最小路径，只有存在真实取舍再给备选。 | 意见过量/碎片、泛泛 praise sandwich、要求作者为每条都写拒绝理由；将采纳率当成功。 | 计发现数、根因数、重复症状数、每 1k 字作者处置动作数、阅读负担、采纳与修改后质量，分开统计。 |
| **10 事实查证与可信度**。[E] 3.10；专业编辑/事实来源惯例与叙事研究。→ 内审读不联网；World/Story/Evidence 已有材料；Assistant 专题 `research` 蓝图是作者显式允许联网的另一路。 | 作者层只比对正文与已有内设来源；外部事实需作者另启 research；内审模型不联网 | Editorial read不开放 web；non-research Team `allow_web=True` 被拒；`research` 必须当次开 web 并使用指定来源工具。编辑台只能检查内部设定/文本相互关系，不能确认历史/现实事实。 | 无外部来源时只标“需查证”待处理；事实 assertion 需要正式 source evidence 和版本；外部 research 另由作者明确启动和审定。 | 单独显示待查问题、关联剧情影响、未查范围；不能显示“史实错误/不真实”结论。 | 把架空设定当历史错误；把文本中角色的错误认知当作者错误；模型记忆猜测冒充引用。 | 编入无网络的虚构现实/史料问句，预期输出未知；开启公开资料的研究任务再核查来源引用、作者确认与来源时效，不计入本轮模型 run。 |
| **11 伦理再现与文化语境**。[E] 3.11；叙事伦理/再现理论/读者研究，强调历史与不同读者群。→ 当前 E/SR 无专类；可作为作者主动邀请的再现视角候选，不替代真实经验读者。 | 当前没有专门层；未来仅在作者本轮 opt-in 后由 LLM 提供观察，并由相关经验读者补充；服务端不做伦理裁定 | 无当前伦理 finding category 或“伦理通过”状态。Teams deep_review 的 narrative 角色不自动承担 sensitivity review；本轮审读不联网。 | 当前链路没有作者本轮伦理 opt-in；未来只有新增明确入口后才由 LLM 给候选；相应群体/历史事实需专业/经验读者提供，不将单一读者意见升级为群体裁决；作者决定采纳。 | 另放“再现/视角观察”入口，语气用“可能产生的阅读影响/文本信号/尚缺情境”；附反向证据，不贴作者人格标签，不承诺“已清除风险”。 | 把描写某群体=作者认同；把作者意图=效果已成立；让 AI 冒充群体授权或普遍敏感度。 | 由不同经验读者独立标注、保留分歧；用同稿反讽/平叙对照；评测误报、具体证据、语气指控度与“clearance”虚假宣称。 |

### 5.1 与 Story Continuity、Evidence/Evolution 的责任边界

- **Story Continuity / Evolution**持有事件和 Scene state 的来源、维度、版本、作者确认、依赖失效与传播边界；Evolution 能验证其允许的状态事件是否有观察证据及规则，不负责评估一个章节是否好读。未就绪/未确认/unknown 的状态必须保持为未覆盖或待作者决策，不能被 E/SR 的模型补成事实。`story/README.md:66–70`；`evolution/README.md:83–97`；`evolution/impact.py:58–81`。
- **Writing conflict check**会用可信 Scene checkpoints 对场景/地图做空间、时间、逻辑候选检查，记录 coverage/omission；`needs_review` 不是确定真相。正文事实是否要写成项目 continuity event 仍走原作者确认。`writing/services.py:1898–2017,2545–2606`。
- **Writing semantic review**只为冻结候选执行其独立审稿；基于原 confirmation 做 Knowledge boundary、Scene contract、world/continuity coverage 与 deterministic POV guard。它是采用门禁，不替作者编辑台发全书“编辑意见”。
- **Assistant editorial review**目前用正文、作者简报、World 和 outline 给“待处理建议”；其 `_materialize_context` 不读取 Story scene continuity checkpoint。设计上不要再让 LLM 重建/修改 Evolution state。若未来接入已确认 continuity receipt，应通过只读来源回执引用、注明覆盖/版本；重复的同一根因在作者报告层关联，不另造事实 finding。
- **Teams deep_review**负责分角色找待证假设，之后写域语义审查；不和 E 叠加成多模型票决。`blind_reader` 负责顺序冷读体验，不接受 hidden knowledge scope，也不适合裁定事实来源。

### 5.2 中国传统、连载媒介和平台压力是横轴，不是第 12 个错误类

输入报告 §4 把章回回目、晚清日报连载、当代网文平台、订阅/反馈压力分开讨论。它们改变一章可能承诺什么、何时回收问题、读者以什么节奏接触作品，但不能推出所有小说“每章都要钩子”或“必须迎合即时数据”。当前简报能用 `target_readers`、`genre_promise`、`goals`、`intentional_choices` 表达这些约束，但没有独立的 `medium/platform` 字段；不建议为网文/传统小说新增必填字段，作者可在已有 free text 声明本轮承诺。样本评测应包括章回标题预示、传统预言、网文局部闭合与跨卷积累，测试模型能否按具体 brief 判断，而不是根据媒介标签触发规则。

## 6. 作品承诺、回看线索与“不应报告”清单

### 6.1 作者声明如何和文本效果并存

当前 `EditorialBrief` 已可用自由文本保存目标读者、体裁承诺、目标、声音、需保留项和有意选择，并带版本。它足以表达“留白、非线性、不可靠叙述、松散/单元结构、开放结局”等意图，无需另建五种类型字段。关键限制是服务端验证 `intent_quote` 只证明这是作者保存过的声明，不证明正文效果成立。

设计上保留两类互不代替的证据：

1. **作者意图证据：**精确显示命中的约定原文、版本和适用范围。读者 pass 不接收该文本，以免被答案诱导。
2. **作品效果证据：**读者 pass 只读当前片段及此前生成的 reader state；作者 pass 读当前片段、brief 和前文摘要，不拿到所有先前正文；跨章 synthesis 只见摘要和已有 findings。故当前模型不能保证发现“尚未成为 finding 的旧线索”，也不能把未提供的后文当已核对。

如作者声明“延迟揭露”，模型不应直接报“没说明人物动机”；如果读者 pass 在揭露前确实无法判断人物做了什么，可提出限定的体验：“我现在无法判断……，可能是作者有意延迟；后文线索本轮未核对”。只有线索被实际提供且来源复验后，author pass/受控回读才可讨论它是否支持回看重释。作者声明不能自动消除实际阅读摩擦，读者困惑也不能自动否决作者的形式选择。

### 6.2 不应报告

以下项目除非作者明确写入作品承诺，或文本提供具体失配证据，否则不应成为错误卡、严重度或提醒：

- 没有三幕结构、固定中点、线性情节或单一主线。
- 每章没有钩子/反转；章节以局部解决、停顿、回望或留白结束。
- 人物没有成长弧、积极行动、疗愈轨迹、明确欲望/恐惧表；人物稳定、扁平、被动、沉默或功能化。
- 每场没有推进主线，或没有发生剧情/关系/信息变化；有意呈现日常、仪式、停滞、重复、哀伤、空间和主题回环。
- 没写足五感、地图、背景、物件用途，或读者不知道作者心中但作品无需交代的设定。
- 用了副词、被动句、直接讲述、总结、重复句、长描写、全知视角、自由间接话语、群像或不可靠叙述。
- 开放结局、反高潮、预言、意象不回收、伏笔延迟、结尾没有解释一切。
- 作者没有采用 AI 的建议、把意见标成“刻意安排”、暂缓修改，或不同读者对美感有分歧。
- 角色说错事实、不可靠叙述者自相矛盾、有限视角不知道答案；只要作品没有把这当作者事实承诺，就不等于错误。
- 模型/审读者对某词、风格、主题、道德立场的个人好恶；或仅因一个群体身份就宣判作品伦理失败。
- 任何没有网络/来源核对的历史、职业、医疗、法律或现实制度事实“错误”。

这是一份“报告门槛的反向约束”，不是封闭白名单，也不阻止作者主动请求 line edit、事实研究或再现视角审阅。

## 7. 反馈数量、语气与修订依赖

`top 3` 是作者首页注意力预算，不是“全书最多 3 条”；任何新设计都不应把 11 个领域各自变成独立意见卡。`_fingerprint` 只按类目/对象/章节/引文锚区分稳定身份；跨章 synthesis 可以合并共同根因，但没有 typed `root_cause` 字段，也不能保证不同 category 的同一症状只产生一条。增加分类字段前先测每 1,000 字 finding 数、重复根因数和作者一次需要做的决定数。

教育写作研究关于意见数与 uptake 的结果异质：有研究中高于班级平均的评论数量对应较低逐条采纳；另一些跨课程研究发现反馈深度比数量更能解释后续成长，且意见量和总体增长可能相关。创意作者访谈更常强调具体文本反馈、作者能设定 AI 介入边界和可追问“为什么”，而不是笼统鼓励。上述大多不是成熟小说家或长篇文学编辑实验，因此本项目不据此硬设“最多 N 条”。

**建议展示依赖而非强制线性轮次：**跨章节承诺/因果/规则先显示“需要作者先定方向”；确认方向后，作者再选择局部锚点进行 line/copy 修订；采用候选后沿现有流程复核 affected ranges。独立且不会因结构决定失效的低层问题可仍在折叠区呈现。Developmental/structural、line/style、copy 是解释“影响范围”的参考，不是要求作者理解的三个固定产品阶段。Editors Canada 2024 标准把结构、风格和 copy 的职责分开，同时明确阶段可重叠或按不同顺序；EFA 对 line edit 的服务定义也承认可独立、可在大方向之后、或与 copyedit 合并。`[Editors Canada 2024 Standards](https://editors.ca/publications/professional-editorial-standards/fundamentals-editing/)`；`[EFA service definitions](https://www.the-efa.org/editorial-services-definitions/)`。这些是行业定义/规范，不是证明某种先后有因果优势的实验。

## 8. 缺口研究

### 8.1 LLM 作为小说审读者：可作候选，不能签文学事实

- **直接故事反馈研究。**Rashkin 等在 ACL 2025 发布了 1,300 个经过扰动的故事测试集，对模型反馈做自动与人工评价；摘要结论是意见常具体且大体准确，但模型容易漏掉故事中最大的问题、不能稳定决定何时应批评还是肯定。[ACL Anthology](https://aclanthology.org/2025.acl-long.1254/)。其样本来自 326 个原故事、单轮模型意见，并不是长篇稿或专业编辑裁定。
- **直接连续性任务。**Ahuja 等的 COLM 2025 FlawedFictions 包含短篇与较长童话，模型连续性检测随故事长度增加而下降；自动找矛盾也会带来误报。该基准是可控 plot-hole 检测，不是所有形式的“写错”。[COLM 2025 paper](https://openreview.net/pdf/8e9100661069abe51439f185fa13b0680bdf9b03.pdf)。De Langis 等 EACL 2026 发现模型末尾整体连贯评分不能稳定区分配对故事，并对违反世界常识比角色既定特质的违背更敏感，提醒 character consistency 不能只靠一般常识判断。[ACL Anthology](https://aclanthology.org/2026.eacl-long.280/)。
- **文学标注与专家一致性。**Jang & Jung 对韩国科幻短篇中的人工生命角色行为做模型/人类标注比较；标注分歧本身提示文学位置发现与解释标签应分开评测。[ACL Anthology](https://aclanthology.org/2024.nlp4dh-1.34/)。任务限于特定角色问题，并非自由式编辑意见，也不能证明专业编辑对此类问题的认可度。
- **误报与无问题作品。**故事反馈基准和现有编辑台四层样本都表明，应测“无问题时敢不报告”，而不是只问能否找出合成矛盾。精确引文成立，不代表推论成立；模型说得具体也不等于挑中最值得处理的点。
- **谄媚。**Sharma 等相邻研究把用户立场/偏好作为提示变量，在数学、论证、诗歌反馈任务中发现反馈正负性会随用户表态变化；这是预印本/相邻任务，不是小说审读精确率研究。[arXiv](https://arxiv.org/abs/2310.13548)。设计应测试：作者说“我觉得这段很好/很糟”是否改变模型找出的文本证据；合法的 intent/genre 信息应改变相关性判断，但不应把同一处未变化的证据改说成事实成立/不成立。
- **自偏好、位置偏差、风格偏好。**Panickssery 等的 NeurIPS 2024 研究在新闻摘要任务发现部分 LLM 评审器偏好自身生成；Shi 等的 2025 评审器研究显示候选顺序会影响 pair/list judging；Liu 等长上下文 QA 研究发现相关证据在中段时可能更难被模型利用。它们是**间接**证据：不能据此宣称模型已偏爱自身写法、某个文学风格，或小说中段必然“lost in the middle”。现有强证据不足，需作为配对压力测试。

### 8.2 LLM 改写、作者声音与过度修改

- Sourati 等 2026 *Nature Human Behaviour* 的多数据集研究覆盖 7 个文本数据集、超过 88 万文本，报告润色/改写保留核心意思但把跨文本复杂度差异压缩约 21%–50%。其中包含创意文本，但“复杂度方差”不是长篇小说作者声音或读者价值；不能套成所有作者都会丢风格。[Nature article](https://www.nature.com/articles/s41562-026-02550-0)；书目和摘要另见 [PubMed](https://pubmed.ncbi.nlm.nih.gov/42637911/)。
- 创意写作小样本访谈/观察记录了作者对控制、接回文本和具体反馈的担忧；HCI 研究比较个性化与通用建议，没有证明个性化就能保留作者声音。短篇、旧模型和质性访谈只给出风险线索，不能代表本项目写作模型。
- **设计启示是范围守卫和评测，而不是自动“声音相似度门禁”。**当前 Writing patch 已确保选区外正文不变；目标范围内的句法、节奏、词汇仍可能被流畅化。应该比较 before/after、保留 `preserve`、人物意图、节奏和作者表达，人工判断非目标改变。`writing.semantic_review` 对自有返修候选会传 `preserve` 和 `must_not_change`；BR-4 comment prompt 目前只给所选批注、引文和局部上下文，并未单独传作者 Brief 的 `voice/preserve`，是后续候选，不是已验证故障。

### 8.3 作者如何接受编辑/AI 意见

- 多数数量/语气实证来自学生同伴评语和学术写作：理解与同意、意见具体度/解释、方案可执行性和领域高低层次与 uptake/修订质量有关；不同研究中评论数量与 uptake/总体成长的关系不一。采纳可以是“听话但改坏了”，拒绝也可以是理解意见后保护作品。
- 直接创意写作者访谈倾向于要具体、有位置的意见、可追问原因，并希望作者控制 AI 介入范围；短文共写研究把作者身份和 AI 生成多少关联起来，但样本小，不足以预测 NovelCraft 作者。
- 因而不应把采用率优化成唯一指标，也不应为了“温柔”加入模糊的赞美夹批评模板。更可测的是：作者能复述问题、知道依据、认为这是事实/体验/偏好、可拒绝并保留理由、候选质量/声音是否改善、处理时间和意见碎片数。

### 8.4 人类编辑实践：职责层次，不是固定产品瀑布

Editors Canada 2024 说明结构编辑、风格编辑、copy editing 和 proofreading 各有职责，但阶段能重叠、顺序会变化；其标准还要求维持 voice/tone/register、沟通清楚且可行动、在可能时对敏感语言“flag”并提出替代，而非宣告清除。[标准](https://editors.ca/publications/professional-editorial-standards/fundamentals-editing/)。EFA 定义 developmental editing 处理内容、组织与体裁；line editing 可独立、在大方向处理后或与 copyediting 合并。[EFA](https://www.the-efa.org/editorial-services-definitions/)。Sundac 2026 对澳大利亚 30 名作者/编辑访谈发现 developmental/structural 术语使用并不完全统一；这属于小样本行业访谈，不是顺序因果研究。[DOI](https://doi.org/10.1007/s12109-026-10091-7)。

因此产品优先显示“全书/跨章/段落/选区”与依赖关系，不要求作者选择英语出版行业术语；一般顺序为结构方向先定、依赖它的局部措辞后修、返修后重新检查，但允许独立小问题平行处理。

## 9. 改进候选：收益/成本排序

以下全部为备选方案，按预期收益和实施成本排序；本轮不实施。成本是相对工程范围，真实模型/数据外发另需按现行项目门禁授权。

| 顺序 / 候选 | 涉及文件/契约 | schema / migration 影响 | 用户行为变化 | 同步的文档与测试 | 收益 / 成本 / 风险 |
|---|---|---|---|---|---|
| **0. 先修准当前桥接说明** | `backend/modules/assistant/README.md` “意见转批注修订桥接”；`editorial_bridge.py` module docstring。根据现行 `IssueRevisionItem.evidence_indices`、UI 勾选和 Writing 按章拆任务写准。 | 无。 | 无。 | README、模块说明；`test_editorial_bridge.py` 复用现有 bridge tests 中的多依据与跨章分任务覆盖，不重复新增同义测试；如未来发现真实缺口再补断言。 | 收益高/成本极低/风险极低；否则后续设计和实现都沿旧前提展开。只属文档/合同维护，不解决文学质量。 |
| **1. 诊断顺序与反向约束；收敛建议数** | `assistant/editorial.py:_SYSTEM`、`_validated_findings`；`editorial_contracts.ReviewFinding/ReviewDirection` 可先不变；`backend/modules/assistant/tests/test_editorial.py`。 | 首选不改 schema；让现有 `directions` 允许 1 个有据方案，只有缺关键路径时标 `unchecked`，不因“不够两条”降级。若发现需要 `cause/effect` 单独展示，再另评 optional 字段。 | finding 不再为了填 2–3 项罗列泛泛修法；作者仍可展开其他意见并决定。审读区分：明示承诺/已建立惯例/审读者偏好、理解摩擦/不喜欢、alternative/re-read cues、最小修订/作者需定方向。 | 同步 Assistant README 的 finding/排序/桥接描述；回归 `test_editorial.py`（少于 2 方案不会仅因此 `unchecked`，未核实范围仍标记，高严重度门禁不削弱）、前端卡片单方向显示、Prompt contract。 | 收益高/成本低；避免“2–3 选项”导致建议膨胀；风险是删掉“替代方向不足”的质量信号，需用人工评分验证最小方案是否有用。 |
| **2. 扩展本任务评测设计并先做离线标注** | 本任务目录样本草案；未来按 `backend/evals/datasets/editorial_cases.json` 新版本新增，不覆盖现有四层；评分定义落入 eval README。 | 本轮无；将来应新增 data version/hash，不改旧 case。 | 不变；首轮比较现有和候选 prompt 的 finding 数量/质量，不先加用户界面字段。 | `test_editorial_dataset.py` 新版本哈希/原文检查；eval README 量表/记录项；人工双评结果账本。 | 收益高/成本低至中；先知道问题是否真存在，避免错误扩 schema。风险是合成样本覆盖窄，不代表实际稿件。 |
| **3. 仅在作者本轮明确请求时提供风格偏好观察** | ReviewSubmit、EditorialDesk.vue、审读输出展示；默认勾选的 line 维度不代表授权。 | 新增默认关闭的一次性请求信号及兼容输出；若只存现有冻结 scope JSON，无关系表迁移，仍须检查版本/恢复兼容。风格偏好不进入问题 finding 的 severity、排序和 BR-4。 | 作者多一个可选入口；默认完全不显示口味意见，开启后仍可忽略，不要求写拒绝理由。 | Assistant README、请求合同/序列化测试、前端流程和辅助功能检查；评测区分看懂但不喜欢与误解。 | 收益低至中/成本中；回应主动请求，风险是多一个设置和偏好被误写成错误。若不做，继续过滤偏好。 |
| **4. 试加正交 `mismatch_type`（仅在评测支持后）** | `assistant/editorial_contracts.py::ReviewFinding`、`assistant/editorial.py` prompt/validator/report、`EditorialIssueCard.vue`、前端 schema 消费和 tests。不要改变 `category` 的意义。 | JSONB `finding_json` 可兼容新增可选值，不需要数据库列迁移；历史记录默认映射 `unknown`，不做回填/身份变更。若进 fingerprint 必须另做历史兼容，建议不要让 mismatch_type 进入 issue identity。 | 真实问题 finding 才考虑显示失配性质；偏好与伦理观察须分别 opt-in，并以独立观察呈现，不作为问题严重度、优先排序、BR-4 路由或正史事实。 | Assistant README、front-end label/localization、合同/兼容性测试、冻结合成 eval、报告/导出 schema tests。 | 收益中高/成本中；能把编辑层、问题性质、严重度分开。风险是模型把本体分类写得像真相、作者需要多读一个枚举。可以不做，先自然语言说明。 |
| **5. 把返修层级和保留项安全送到局部修订** | `assistant/editorial_bridge.py` 从冻结 review brief/finding 读取已选 `preserve/voice/intentional_choices`；`writing/contracts.py`、`writing/comments.py` 或 `writing/comment_run.py` prompt 构造。只在原 finding/brief 来源 still-fresh 时传递。 | 可将 frozen brief excerpt/preservation list 放在 task request JSON，不增加关系表；若新 API 字段则设可选且有长度上限。 | 候选修订明确“保留什么”和作者指定的修改范围；不新增自动 voice score 或在作者拒绝时阻断采用。 | Assistant/Writing README、bridge/comment revision prompt tests、候选 provenance/来源新鲜度测试、before/after 声音盲评。 | 收益中高/成本中；尤其对行文建议。风险是把 brief 当通用风格模板反而规范化；必须保留原稿局部上下文和作者确认。 |
| **6. 增设作者主动的再现/伦理观察入口** | ReviewSubmit 新增默认关闭的一次性 opt-in、EditorialDesk.vue 入口和分离的伦理观察展示；现有 dimensions 不含此授权。 | 建议不复用普通 ReviewFinding/severity；单独输出投影可放现有 JSON snapshot，不建关系表，迁移/版本兼容须核查；不新增通过/否决状态或 adoption gate。若引入独立真实读者流程则需另行设计持久化/权限。 | 只有作者本轮显式 opt-in 才给“可能的阅读效果”观察；不向所有项目默开，不宣称伦理清除；鼓励目标读者或相关经验读者核对。 | Product persona A、Assistant README、伦理/再现指南、隐私与来源注释、至少多读者评测/误报测试。 | 潜在收益中/成本高；风险高于普通行文建议，需口吻和授权评估。建议后置，先跑离线样本与真实作者访谈。 |
| **7. 对结构/跨章意见增加作者定向的“先定方案”路径** | 可能复用 `teams.cross_revision`（当前聚焦 World/结构变更依赖）或增加一个 Assistant/Story 提案；不要复用 Writing selected-range patch 伪装结构重排。 | 不应从现有 `IssueRevisionRequest` 扩成任意重写；若真做，需新任务/response contract、来源范围和候选类型；migration 是否需要依持久化设计决定。 | 作者先确认“修改 outline/压缩支线/只调整本章/保留开放式结构”，再生成候选；没有确认方向时不产候选。 | Assistant/Writing/Story README、候选采用与 stale 处理、端到端合成覆盖、作者真实流程测试。 | 可能收益高/成本高；当前不建议马上做。现有 BR-4 已能处理作者所选的多处、跨章节锚点，但没有完整结构改写能力。 |

### 9.1 不建议做的项

- **不把 11 个领域各自变成一个必开 checkbox/必出报告 section。**这会让画像 A 要维护多个低频设置，并把“找不到问题”变成“没有检查”。复用当前五维，评测端用领域标签覆盖。
- **不把六类失配直接合成一个通用评分或 error enum 决定 severity。**审美/伦理、读者理解和硬矛盾的证据结构不同；数字会制造虚假精确。
- **不要求每条意见强制给 2–3 个修订方案、不要求作者写拒绝理由。**只有确实有取舍时才提供备选；作者可以快速选择或暂缓。
- **不把审美偏好作为普通 `line` 错误默认推送，也不设置“每章无钩子/无人物弧”自动规则。**作品没有承诺就不应报。
- **不把“作者说有意”当作阅读效果已经成立，也不把 reader-sim 的一次困惑当成作者意图失败。**保留 intent 和 effect 两类证据。
- **不允许模型在小说内审读时联网事实核查；不让其凭预训练记忆断言史实。**另由作者显式开研究任务并核验外部来源。
- **不把伦理观察做成合规门禁、风险总分或“已通过”认证，也不让 AI 冒充群体代表。**需要不同经验读者/专业研究者参与。
- **不把 Editorial、Semantic Review、Writing conflict check、Story Continuity/Evolution 结果揉成一个“共识分”。**所有者、证据和授权不同；可做引用与去重，不做投票提升权威。
- **不把 `finding fingerprint` 改成新根因聚类键而继承/丢失旧作者处置。**身份聚合若要改，先设计历史迁移和可撤销行为；首阶段只在报告呈现层合并相同根因。
- **不以自动“声音保留分数”作为写作门禁。**当前文风量化研究测的指标并非文学声音；用非目标改动率+盲评/作者自评作研究指标。

## 10. 评测扩展方案（只在本任务目录起草）

### 10.1 现有基线

`backend/evals/datasets/editorial_cases.json` 有四层、固定正文 hash 的原创样本：`explicit_error` 的唯一物件矛盾、`multiple_explanations` 的多种合理解释、`intentional_gap` 的刻意延迟揭示、`no_major_issue` 的无主要问题。现有六项 0/1/2：来源误读、强意见误报、重大问题漏报、方向可执行性、作者声音尊重、改后判断。零费用预检要求冻结文本、brief、模型、预算与共享账本；Codex 单人 AI 自评不得登记成独立人工 precision。`backend/evals/datasets/editorial/README.md:1–13`。

### 10.2 新增原创合成样本草案

下列片段只作为本任务目录的设计例子，不写入 `editorial_cases.json`，不改变现有哈希/版本。运行用例应扩成 1–3 个小章节，保留明示 brief、已读/未读范围及 oracle 说明。

| ID / 失配类型 | 简短合成正文与 brief 设计 | 预期结果/反向检查 |
|---|---|---|
| S01 硬矛盾阳性 | brief：“只铸过一把铜钥匙，熔掉后不可能复原。”第 1 章写主角当面把钥匙熔成铜液；第 3 章她从空袋里取出齿纹完整的同一把，直接开门，全文无重铸/替换线索。 | 两处原文一起引用；在覆盖完整时可标硬矛盾；不要只引用末句，也不需把它转成改稿。 |
| S02 硬矛盾近失误 | 第 1 章只由不可靠第一人称说“城里没有钟”；页边日志由另一角色写下“钟声仍在”。brief 表明叙述者有意撒谎，正文前文已有隐瞒线索。 | 不报作客观矛盾；可说明两种证据来源和不可靠叙述线索。测试 author intent 不是唯一线索。 |
| S03 因果缺口阳性 | 冻结规则：“盐印只能封住木门；隔着石墙不生效。”高潮中主角站在石墙后，仅凭盐印封住门外追兵，未打开门、未移位、未出现新规则。 | 指出执行条件与结果的因果断点；最小修订是补位置/触发/代价或改解法，不强迫重写全卷。 |
| S04 因果缺口反例 | 前文多次写主角把备用细线藏在袖口，并演示可从门缝触发铃；结尾她用同一根线报警。 | 不称结尾解法凭空出现；可接受读者漏看但要准确引用铺垫。 |
| S05 理解摩擦 | “阿岚把它递给她。她摇头。那人把灯放下。”此前场景有三位女性角色，附近没有再次命名/动作线索。brief 目标是限制视角悬疑。 | 可报告局部指代的多个解读/无法判断行动者；severity 不升为 continuity contradiction；指出需盲读验证。 |
| S06 理解与偏好分离 | 同一段重复“雨落在空椅上”三次。brief 明示仪式式重复作为哀悼节拍。独立读者 A 看懂并觉得太慢，读者 B 看懂并认为有力。 | 输出只记录读者可读懂但反应不同；不得把“重复=信息错误”。预设真实人类标注可分歧。 |
| S07 目标失配阳性 | brief 明示“封闭空间推理，线索应让读者在揭晓前可回推”。前 4 章嫌疑人和线索按规则陈列，结尾凶手是前文未出现的邮差，并凭此前未设定的暗门进入现场。 | 目标失配/因果问题依据 brief+正文；作者声明能证明承诺，正文证据证明效果不符。 |
| S08 目标失配反例 | brief 明示“旅行见闻式单元小说，主角无统一成长弧，结尾开放”；三章分别完成一次小型关系变化，以风景/重复母题相连。 | 不报告“没有主线、钩子、成长弧或解释不完”。测试口诀边界。 |
| S09 审美偏好反例 | 平缓小镇夜班片段：只写值班者擦杯、听雨、等最后一班车；无危险、无悬念、无强冲突。brief 是节制日常文学。 | 默认 0 问题；任何“要加钩子/冲突/删描写”记为 taste-as-error false positive。 |
| S10 审美偏好主动邀请 | 与 S09 等价内容；假设本轮存在默认关闭的明确风格请求信号（当前请求/UI 尚无该字段），说明“本次只想要句子精简建议”。 | 可作为独立、低优先、非错误卡的可选观察；不得自动进入局部修订桥接或抹平原语气。 |
| S11 伦理观察阳性候选 | 架空“雾港迁徙者”一组角色在当前章节只作匿名背景，被主角替他们说话/决定；另一个角色有名字和个人利益。假设本轮存在作者明确启用的再现视角信号（当前链路尚无此字段）。 | 用“可能造成的读法”指出多处具体信号和相反证据；不推断作者偏见，不替群体表态，也不计 high/low 质量总分。 |
| S12 伦理反例 | 同一身份群体中角色有互相冲突的目标、行动与话语；主角确有偏见，但情节通过后果与反方声音暴露其局限。作者未请求伦理审读。 | 默认不出现伦理警报；若主动请求，呈现解释分歧而不是“引用偏见词 = 作者赞同”。 |
| S13 长篇回看线索/位置偏差 | 两版同一悬疑故事：线索分别放第 1 章开头和第 5 章中段，揭晓在第 6 章；设置一个排除/缺章变体。 | 比较证据定位/覆盖：没读到的前章必须 `unchecked`；不能把中段线索因位置而消失；不要用后文覆盖早期盲读状态。 |
| S14 人物知识边界 | AI candidate 的 POV 角色在未见/未闻/未确认资料前直接说出秘密身份；配一版已在前章获知同一秘密的负控。 | 只在有效 confirmation/character POV 下签 knowledge coverage；优先合并 deterministic hidden guard；无 confirmation 人工稿明示未检查而非判 PASS。 |
| S15 外部事实待核 | 架空世界作者问“永乐年间的某种商税是否确实存在”，项目只含虚构设定，没有外部资料。 | 小说内审读不得回答史实；显示“待外部查证”问题及其剧情关联，不产生“史实错误”finding。 |
| S16 领域重叠/复读 | Writing conflict check 已有 `timeline/location` 候选和覆盖回执；相同章节 Editorial 又看到同一两句文本，brief 未新增文学目标。 | 比较是否出现重复卡片/多个“根因”；保留 E suggestion 与领域 receipt 的权威区别，若关联同因则显示引用/入口而非另造事实。 |
| S17 中文章回/连载横轴 | brief：“章回式奇幻连载；每回可有局部收束，长线靠物件与关系变化推进，不要求每回险处断章。”一回写道：“赵三交完船票，接回妹妹。纸鸢还在北岸；他决定明日再找失踪的船师。” | 不报“章节没有 cliffhanger/钩子”；注意局部收束与跨回未结线程并存。本例仅测“单回无钩子不等于错误”的口诀边界，不代表覆盖回目节奏与跨回长线互动；媒介承诺也不混为一谈。 |

### 10.3 评分项与统计

保留现有 6 项，每项 0/1/2，并新增以下分项；各项报告均值、误报率/分母、置信区间和分歧，**不合成一个文学质量总分**。

| 新增评分 | 0 分 | 1 分 | 2 分 |
|---|---|---|---|
| 有意形式误判 | 把开放、留白、不可靠叙述/无钩子写成确定错误 | 提到意图但仍推必改 | 用线索和范围说明可能效果，保留作者决策 |
| 口味伪装错误 | 把审读者喜好报成 flaw | 标为风格但仍进高优先/返修 | 默认不报；作者主动请求时作为可选偏好 |
| 理解 vs 不喜欢区分 | 混为“读者影响不好” | 有区分但证据不清 | 说明实际理解/歧义与审美反应，保留不同读者结果 |
| 回看线索与替代解释 | 未找反例或把缺范围当不存在 | 找到一种但来源未核 | 引用支持/反证并标明未读范围 |
| 最小修订与层级 | 大改/选区修复结构问题/扩大范围 | 方案方向可用但路径过多或不明 | 给一条最小方案；确需取舍才给备选；结构问题先作者定方向 |
| 作者声音/过度修改 | 删除非目标语气/句法/信息或越过选区 | 留住意思但表达明显泛化 | 保持关键声音特征，仅改支持 finding 所需范围 |
| 意见聚合/处理负担 | 同根因拆成多卡/重复症状多 | 聚合部分重复，作者仍需多次处置 | 每个根因一个主要卡片，多处证据/症状折叠 |
| 伦理呈现边界 | 指控/泛化/宣称 clear | 有具体引用但模糊评断 | 只在 author-opt-in 显示可能读法与反证，不冒充群体授权 |
| 外部事实克制 | 无资料也断言史实 | 明示疑问但仍推理作答 | 标成待外部查证，不并入内审严重度 |

此外收集非评分指标：每 1,000 字 strong findings、全部 findings、唯一根因数、finding/根因比、`unchecked` 比例、跨章引用数、作者打开/折叠/定位/选择/采纳/改写/拒绝/延后/理由、候选非目标改动比例、改后复核仍在/可能改善/未知分布、耗时与作者感知控制。采纳率仅作行为指标，不单独视为质量。

**评测判读门槛（建议，供作者决策，不是自动发布门禁）。**当前 21 个合成 case 只用于探索性筛查，不能单凭均值、单个评审者或置信区间决定加字段。候选至少应：不降低现有六项评分的总体表现；在 S02、S08、S09、S12 等保护样本上不出现高严重度误报；不增加重复根因拆卡和每条意见的作者处理步骤。只有在独立留出样本中，两名盲评者能在多个不同失配案例上指出新字段改变了正确处置路径、且卡片数/决策负担不升，才进入新增 schema/UI 的方案评审；否则留在自然语言提示或不输出。上述是本项目建议的实用筛查标准，不是文献证明的阈值。真实作者掌控感和采纳行为仍需单独用户研究，不能由合成集代替。

### 10.4 离线盲评与真实模型验证计划、费用估计

**本轮不运行。**未来先离线冻结四个旧样本和 13 个主失配样本（S01–S12、S17），再选 S13–S16 做领域/长篇压力集；共 21 个 case。baseline 与候选提示词用同一 owner 已核验连接、provider/model/effort/wrapper、固定范围、相同样本 hash。先完成无模型 schema/来源核验，再由两名独立中文小说编辑/目标读者盲评；解释性样本保留分歧，不把 Codex 自评当独立人工 precision。另做条件对照：作者 brief 为空/准确/含与阅读效果相冲突的有意声明；关键线索位置前/中/后；同一内容的两种有意声音。评估先准确，再看用户负担。

费用分为受限情景估算和真实长篇预算，不能把单次 worker 的 4 请求预算当成每份审读的上限。

1. **审读意见质量 pilot（预算情景）：**21 个 case × 2 个提示词条件 = 42 次审读。按每 case 最多 6 章、每章一个 12,000 字符段、读者层和作者层各 1 次请求、跨章合并 1 次请求，估为每次审读 13 个请求，共 546 个请求。按每请求 30k 输入 / 4k 输出 token 作规划估算，为 16.38M input + 2.184M output。
2. **闭环修订 pilot（预算情景）：**8 个明确适合局部修订的 case，各 1 次候选生成、1 次 Semantic review、1 次 editorial recheck，共 24 个请求；按每次 6k 输入 / 1.5k 输出，计 0.144M input + 0.036M output。结构类/伦理类不强行走局部 patch。
3. **费用换算：**按本次查阅的 GPT-6 Luna Standard 公开费率，不计缓存，审读情景约 $2.73，闭环修订约 $0.0324，合计约 $2.76；加 50% 预留约 **US$4.20**。这只是限定每例不超过 6 个单段章节的 token 费率情景，不是系统硬上限或承诺报价。将来若增加真正的回读检索、章节多于 6 个、单章超过一个段、额外确认/复核请求，须按实际调用/收据重算；全文审读费用没有可由当前 requests<4 推出的总上限。

4 请求限制只作用于单次 worker execution；resume 会把该执行的 budget 重置，后续续跑与 synthesis 可继续消耗请求（assistant/editorial.py:899–909, 1263–1317, 1397–1420）。因此真实 pilot 必须先冻结总章节/段数、复核轮数和停止预算，核验 owner 已验证的连接、provider/model/effort/wrapper 与实际账号费率，再决定硬预算。reasoning effort=max 不改单价，但可能改变 token 总量；超授权预算应停并核账，不自动回退供应商。实际 Codex/Project facade 是否按该 token card 计费、是否被 included allowance 覆盖，须启动前按当日协议确认；本轮没有费用或模型调用。公开费率见 [GPT-6 Luna model pricing](https://developers.openai.com/api/docs/models/gpt-6-luna) 和 [ChatGPT Work/Codex rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card)。

两位评阅者各评 21 个 case，假设每条 10–15 分钟，约 7–10.5 小时，另加分歧仲裁时间；此人力成本不含在 token 估算里。若后续需真实目标读者/相关经验读者试读，样本招募与费用要单独定，不从本次模型费用推算。

## 11. 待作者决定的问题

1. 是否接受下一轮先做低成本 prompt/方案数修订+离线评测，然后再决定新增 `mismatch_type`？或者您认为“一眼区分矛盾、因果、理解、目标、口味、伦理”值得直接加 optional schema 字段。
2. 是否接受审美偏好默认过滤；若开放，是否增加默认关闭的本轮风格建议 opt-in（当前选 line 不算邀请，因为它默认勾选）？是否保留 top 3 主入口/其余折叠，并把同根因多锚点折在一条？
3. 是否希望设独立的“再现/伦理观察”主动入口？本设计建议后置、非默认、非通过门禁，并另做不同经验读者评测。
4. 结构性问题未来是保持“意见+作者回 Story/outline 自行决定”，还是要设计一条需作者先选方向的跨章 prose revision route？现有 BR-4 只覆盖选区替换。
5. 后续真实模型 pilot 若另获授权，是否先以最多 6 章/例的探索性情景（约 US$4.20 费率等值预算，启动前重核并按实际 token/call 数设封顶）开始？更长文本应先重新计数；两名独立盲评者及实际作者研究是否纳入，也待决定。

## 12. 反方审查与本稿修订记录

2026-10-16，由独立审查人按验收项检查代码事实、口诀门禁化、作者意见量/碎片、画像 A 负担和候选范围。审查确认桥接“多依据/跨章分别分任务”的事实及 README/docstring 过时判断正确；也确认“不应报告”清单明示不是封闭白名单/服务端门禁，候选没有把 11 领域拆成默认意见卡，整体未增加作者必须处置的意见。审查指出并已修订：

- 4 请求预算只限制一次 worker execution，续跑会清空该段预算，跨章汇总也耗请求；撤销原 US$0.50 全 pilot cap，改为限定章节/分段情景估算，并把长篇费用留作先计段/回合再预算。
- synthesis 看不到未形成 finding 的旧线索；收紧为“当前能力做不到”，把真正回读列为需来源重验的新路径并计入未来预算。
- 11 领域表新增读者层/作者层/确定性/外部流程列，明确语义审查不能替 editorial 全书判断。
- 说明当前 finding 无可执行的优先级依据：范围/引文/coverage 是可信度检查；章节数不是根因重复，intent quote 不是严重度。候选排序须由显式、可评估的 LLM 影响依据支持，未核实时不升序；改排序前先离线盲评。
- line 默认勾选，不能代表作者主动请求风格建议；审美偏好默认过滤，若产品决定开放须新增本轮默认关闭的 opt-in，并与错误卡/严重度/返修桥接分开。伦理观察同样没有当前 opt-in 字段。
- 21 个合成样本只能作探索性筛查，新增 schema 需另设可复现的实用收益/误报/负担门槛；S17 仅覆盖单章无钩子反例。费用情景覆盖 S13 的最多六章，但不覆盖新建的回读检索。
- 候选 0 修订为更新过时文档并复用现有 test_editorial_bridge.py 多依据及跨章测试；除非后续发现真实缺口，不重复加测。

剩余边界：这些改动仍是设计建议；反方审查没有运行代码测试、模型或作者访谈。

## 13. 研究限制

- 本稿没有审读作者真实小说，也没有运行真实模型/付费调用；合成样本不证明真实作者满意、准确率或创作质量。
- 模型反馈与声音研究多是英文短故事、课堂作文、短文本共写、行为/风格代理变量；不能直接外推中文长篇网文。
- 编辑行业标准/协会服务定义是职责与实践描述，不是证明固定工序有效的随机对照实验。
- “有意形式”“读者摩擦”“伦理影响”可能产生合理分歧。评测应保留多读者解释，不追求把所有情况收敛成单标签。
- 公开研究采用来自团队分支的初筛和元数据核对；核心研究原文/出版社页优先核验，OpenReview/ACM/Nature 部分页面有访问限制；本稿不宣称穷尽相关文献。

## 14. 来源分层与关键来源

### 直接小说/故事研究

- Rashkin, H., Clark, E., Huot, F., & Lapata, M. (2025). “Help Me Write a Story: Evaluating LLMs’ Ability to Generate Writing Feedback.” ACL 2025. [ACL Anthology](https://aclanthology.org/2025.acl-long.1254/)。直接故事反馈基准；结论边界见 §8.1。
- Ahuja, K., Sclar, M., & Tsvetkov, Y. (2025). “Finding Flawed Fictions: Evaluating Complex Reasoning in Language Models via Plot Hole Detection.” COLM 2025. [论文 PDF](https://openreview.net/pdf/8e9100661069abe51439f185fa13b0680bdf9b03.pdf)。受控短故事/童话连续性基准。
- De Langis, K., Öncel, P., Peters, R., Elfenbein, A., Allen, L. K., Schramm, A., & Kang, D. (2026). “Mary, the Cheeseburger-Eating Vegetarian: Do LLMs Recognize Incoherence in Narratives?” EACL 2026. [ACL Anthology](https://aclanthology.org/2026.eacl-long.280/)。成对叙事连贯/不连贯判断。
- Jang, H., & Jung, W. (2024). “Evaluating LLM Performance in Character Analysis: A Study of Artificial Beings in Recent Korean Science Fiction.” NLP4DH 2024. [ACL Anthology](https://aclanthology.org/2024.nlp4dh-1.34/)。特定人物行为的文学标注比较，不是开放式审稿。

### 声音/创作者过程

- Sourati, Z. et al. (2026). “The Shrinking Landscape of Linguistic Diversity in the Age of Large Language Models.” *Nature Human Behaviour*. [Nature](https://www.nature.com/articles/s41562-026-02550-0)；[PubMed](https://pubmed.ncbi.nlm.nih.gov/42637911/)。已同行评审的多数据集写作多样性研究；复杂度方差不是作者声音完整测量。
- Chakrabarty, T., Padmakumar, V., & He, H. (2024). “Creativity Support in the Age of Large Language Models: An Empirical Study Involving Professional Writers.” C&C 2024. [DOI](https://doi.org/10.1145/3635636.3656201)。小样本创意作者研究。
- Hwang, A. et al. (2025). “Authenticity, Authorship, and Agency: How Writers Experience AI Writing Assistance.” CSCW 2025. [DOI](https://doi.org/10.1145/3711020)。专业作者短文写作辅助的体验/读者评价，不能证明长篇声音保留。
- Agarwal, S., Naaman, M., & Vashistha, A. (2025). “AI Suggestions Homogenize Writing Toward Western Styles.” CHI 2025. [DOI](https://doi.org/10.1145/3706598.3713564)。短任务和特定文化样本，非小说风格质量。
- Doshi, A. R., & Hauser, O. P. (2024). “Generative AI enhances individual creativity but reduces the collective diversity of novel content.” *Science Advances*, 9(26). [DOI](https://doi.org/10.1126/sciadv.adn5290)。写作创意，而非审读意见或局部修订。

### 反馈采纳与意见层次

- Wu, Y., & Schunn, C. D. (2020). “From feedback to revisions: Effects of feedback features and perceptions.” *Contemporary Educational Psychology*, 60, 101826. [DOI](https://doi.org/10.1016/j.cedpsych.2019.101826)。高中 AP 英语同伴反馈观察研究。
- Patchan, M. M., Schunn, C. D., & Correnti, R. J. (2016). “The Nature of Feedback: How Peer Feedback Features Affect Students’ Implementation Rate and Quality of Revisions.” *Journal of Educational Psychology*, 108(8). [DOI](https://doi.org/10.1037/edu0000103)。大学课程语料，采纳率和修订质量是不同结果。
- Gero, K. I., Long, T., & Chilton, L. B. (2023). “Social Dynamics of AI Support in Creative Writing.” CHI 2023. [DOI](https://doi.org/10.1145/3544548.3580782)。创意写作者访谈，不能推成普遍操作因果。
- Guo, S. et al. (2025). “From Pen to Prompt: How Creative Writers Integrate AI into their Writing Practice.” C&C 2025. [DOI](https://doi.org/10.1145/3698061.3726910)。高频 AI 使用创作者访谈观察，非长篇意见采纳试验。
- Sundac, M. (2026). “Defining Macrostructural Editing Processes in the Australian Publishing Industry.” *Publishing Research Quarterly*. [DOI](https://doi.org/10.1007/s12109-026-10091-7)。30 名澳大利亚小说作者/出版从业者访谈，界定术语不统一，不证明流程顺序的因果优势。
- Editors Canada. (2024). *Professional Editorial Standards*. [The Fundamentals of Editing](https://editors.ca/publications/professional-editorial-standards/fundamentals-editing/)。行业标准。
- Editorial Freelancers Association. *Editorial Service Definitions*. [EFA](https://www.the-efa.org/editorial-services-definitions/)。协会服务定义，非实证次序研究。

### 评审偏差（间接证据）

- Sharma, M. et al. (2023; arXiv revision 2025). “Towards Understanding Sycophancy in Language Models.” [arXiv](https://arxiv.org/abs/2310.13548)。反馈正负性受用户立场影响的相邻任务研究，不是小说审读。
- Panickssery, N., Bowman, S. R., & Feng, S. (2024). “LLM Evaluators Recognize and Favor Their Own Generations.” NeurIPS 2024. [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html)。摘要任务自偏好，不等于偏好 AI 风格。
- Shi, W. et al. (2025). “Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge.” IJCNLP-AACL 2025. [ACL Anthology](https://aclanthology.org/2025.ijcnlp-long.18/)。成对/list 评审顺序效应，不等于小说文本位置效应。

### 费用口径（研究时点）

本稿于 2026-10-16 查阅公开费率；正式启动时须重新核对当前模型快照、计费模式、账号额度和 Standard/Fast 等 processing mode。OpenAI 官方 rate card 表示按实际 input/cached input/output token 计费，GPT-6 Luna Standard 每百万 token 分别为 `$0.10 / $0.01 / $0.50`；提高 reasoning effort 不改单价，但会影响 token 总消耗。[GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna)；[ChatGPT Work/Codex rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing)。
