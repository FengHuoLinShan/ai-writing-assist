# 世界书系统增强计划（2026-08-13 修订版）：从「真名回响」Wiki 详细程度反推需求、核对现有能力的增量计划

> 性质：基于 2026-08-13 对真名回响 Vault（concepts 99 页 / syntheses 29 页 / meta 76 份裁定 / entities 33 页，合计约 250 文件、6MB+）的需求侧分析与 ai-writing-assist 仓库代码级供给侧核对形成的研究计划；不构成新的 API、schema、wire 或运行时契约。
> 与既有计划的关系：本计划是 2026-08-10 世界书重构计划的第一轮增强——不另起炉灶；把 wiki 新证据中三版设计达成共识的缺口以零迁移薄读形态挂入既有 seam，P1 用窄字段增强接线，其余新 schema 押后至触发条件＋ADR。**2026-08-13 用户裁定：统一待决队列立项（P1-15），取代 08-10 计划 7.4「不造统一校验队列」定案。**
> 方法：双工作流多代理——Workflow A（8 个侦察代理并行：wiki 4 维度需求侧＋系统 3 维度供给侧＋既有计划覆盖图，1 个合成代理出差距矩阵）；Workflow B（3 个设计代理：最小改动优先／生成质量优先／作者治理优先，1 个判定代理合成最终计划）。本修订版为 2026-08-13 用户裁定「做统一队列」后的版本。
> 中间产物：`docs/references/data/2026-08-13-worldbook-gap-analysis.json`（需求 41 条／供给 29 条／差距 30 条）、`docs/references/data/2026-08-13-worldbook-final-plan.json`（三版设计与修订后的合成计划）。
> 第二轮修订（2026-08-13）：补入完整创作历程与 GPT 交接证据后，用户进一步裁定首版必须覆盖「几个灵感逐轮生长 → 可恢复的 World Core → claim 级原子采纳 → DB 与 World Bible 同事务发布 → Deep Import 后置吸取 → World Bible 关联导航 → Scene/正文独立审查与定向返修」。本轮裁定优先于下文与其冲突的旧相位和“不做”措辞；完整 decision-complete 增量见第 9—12 节。

## 1. 执行结论

1. **wiki 的详细程度要求系统从「散文式设定管理」升级为「结构化规则＋触发条件＋状态分层的可查询设定库」。** 样本中 40% 概念页含表格、34% 含公式块（退化赛跑模型 D/U/R/ρ、U≥Θ 触发条件）、140 节点／494 边依赖图、63 项 R-xx 风险台账、术语按状态分层（canonical-revised/superseded/in-world-name）——写作引擎需要查询触发条件与量级，而不是读散文。
2. **现有系统 29 条已核实能力构成高质量底座，缺的是 wiki 治理机制的「产品化」。** 状态机、双视角实体、事件溯源、Scene checkpoint、分层上下文编译、证据回读、权限阶梯均已 code 级核实；但别名无语义角色、冲突队列无触发条件、无术语状态过滤、无防回流拦截——wiki 中最强的治理机制（R 门、术语分层、防回流、反捷径）尚未转成产品能力。
3. **30 条差距中 11 条 high；not-covered 且 high 的 6 条是本计划的主要新增项**：结构化规则存储与查询（A1）、R 门风险台账与剧情触发引擎（B2）、实例级社会真实度审计（C4）、术语注册表与三层可用性矩阵（E1/E2/E3）、跨层失效待复核（D2 在 7.11 之外的部分）、大型设定上下文编译项级控制（J1/A5）。
4. **P0 全部零迁移**：9 项全部以现有 JSON 字段的语义约定（薄读模型）＋Prompt 纪律＋前端编排落地，不建任何新表；三版设计全部共识的门禁项（正文质量 lint 三合一、规则触发预检、术语状态约定、负面边界）构成 P0 增量主体。
5. **P1 共 15 项：14 项窄增强（仅 3 项涉及可选字段扩展**：CharacterKnowledge 四字段、ConflictCheckQueueItem 三字段、source_anchor，全部向后兼容、旧数据默认值语义一致）**＋1 项用户裁定的新 schema**（P1-15 统一待决队列，落地细节走 ADR 记录）；其余为读模型与 Prompt 纪律。
6. **P2 全部触发式**：5 项新 schema（术语注册表、影响审查生命周期、世界书包存储、Decision Ledger、规则与 R 门台账）一律押后至 ≥3 真实项目证据或 08-10 计划 8.2 五条门槛同时成立＋用户裁定＋ADR；真名回响单项目 wiki 证据不构成新 schema 触发条件。
7. **统一待决队列分歧已由用户裁定（2026-08-13）：做统一队列**——取代 08-10 计划 7.4「不造统一校验队列」定案；落地为 P0-7 投影先行切片＋P1-15 权威 schema 立项（细节走 ADR 记录）。其余 6 条开放问题已有明确推荐（见第 8 节）。

## 2. 需求侧推测：41 条能力（从 wiki 详细程度与结构反推）

从 wiki 的证据形态反推，系统需要的能力分 10 类：

| 类 | 主题 | 条数 | 代表性 wiki 证据 |
|---|---|---|---|
| A | 设定数据模型 | 5 | 退化赛跑模型公式变量、数值置信分层（「约2000年只是示例」「约72小时只是叙事工作值」）、实体弹性粒度（0.8KB 占位页与 24KB 深度页并存）、双视角实体（「世界内可知／作者层裁定」两节） |
| B | 裁定与状态治理 | 7 | 三层状态机（status×canon_status×decision_status）、R-01…R-112 风险台账每条带剧情触发条件、canon_diff 四段变更记录、待定术语唯一权威队列（P0/P1/P2 阻塞分级）、A/B/C/D 原子选项「不随选项自动采用」 |
| C | 审查与校验 | 6 | 六面审查（账本/认知层级/生命身份/物理尺度/社会后果/叙事呈现）、「全绿≠语义完备」免责口径、反捷径检查 7 条、六环二十二面社会真实度框架、跨库交叉审计、作者编码泄漏 lint（「0+000—21+600 是作者桩号」） |
| D | 依赖与失效 | 2 | 140 节点／494 边正典依赖图、依赖边「上游变更必须复核下游」单向注册、世界层变更后人物/故事/细纲/正文至少待复核 |
| E | 术语体系 | 3 | 术语状态编码（canonical-revised/superseded/in-world-name/mythological）、三层术语对照表 9 主题五列（本源/各学派/地方世俗＋翻译方向）、术语可用性四列（地位/已见范围/获得路径/认知上限） |
| F | 溯源 | 2 | 节级溯源（来源页#小节锚点）、63 项 R-xx／164 项 FIX-xx 全局编号台账 |
| G | 创作编排 | 7 | 六技能流水线分权与 Scene Contract 交接、seed/candidate/instance 三档深度、对抗式创作伙伴（诊断四问＋反驳）、跨卷暗线管理与叙事禁区、灵感种子卡五段式、NPC 模版库 88 模版、180 条候选 Idea 分层审查 |
| H | 导入与防回流 | 5 | _raw 不可变层＋SHA-256 审计、来源吸收三分流、被取代设定降级为「世界内旧学说」＋机器拦截回归（389,300/391,714 km 旧轨道值）、外部模型交接协议（哈希留档/三分流/拒绝继承外部编号）、FIX 修复台账（冲突证据→最小修复→被保护的叙事价值） |
| I | 认知与时点 | 3 | 角色知识边界账（获取时间/来源/证据类别/可信度/术语层级/可披露对象）、Scene 时点可证状态（三时序分账、投影未记录≠当时不存在）、未裁定实体反向注入防护（龙族/精灵/飞升者） |
| J | 上下文编译 | 1 | 2MB 设定库对默认 4000 token 预算的项级控制与按需取层（总入口只作索引摘要） |

完整 41 条清单见 `docs/references/data/2026-08-13-worldbook-gap-analysis.json` 的 `demand_side` 字段（每条含 why 证据与 process_need 流程需求）。

## 3. 供给侧核对：29 条已核实能力

全部 code 级置信度（代码核实），按模块：

| 模块 | 已核实能力（摘要） |
|---|---|
| world | core_entities 统一事实底座（20 类目录＋双视角 hidden_truth/public_info＋reveal_level 四档）；候选/正典/废弃状态机＋作者采用才 canonical；别名内联 JSONB（开放 type，无语义角色）；关系边 v3（无依赖语义）；回滚双轨 TextArchive+EntityRevision；RuleProfile 类型化档案；World Bible 分类/草稿/发布 CAS/不可变 revision；CharacterKnowledge 七档＋misconception＋source_chapter_index；ConflictCheckQueueItem 列表/resolve（无优先级分级）；CreationSuggestion pending/adopted；pg_trgm+pgvector RRF 混合去重 |
| memory | 事件溯源 memory_events/panorama 重放/scene checkpoints（source_hash＋coverage gap）/delta_log，无 LLM |
| outline | 总纲不可变修订链＋head 指针＋context fingerprint 防漂移；剧情线/篇章纲/Scene/伏笔/揭示四层资产＋reader_reveal_decision；scene_spans 精确映射（anchor hash 重定位、非精确不参与自动归因） |
| map | 动态地图：hex 地形/递归图层树/路径/势力范围/观察→事实双层（UUIDv5+source 指纹 fail-closed） |
| imports | 深度导入三阶段授权流水线＋确定性锚点校验＋整批软回滚（面向小说正文，非外部模型产物） |
| rag | 混合检索五路评分＋三模式＋读者进度硬过滤＋可选 LLM rerank；索引来源仅章节正文 chunk，设定条目无正文形式不被覆盖 |
| context | 分层编译 P0/P1 tiers＋section 级排除＋预算裁剪审计（默认 4000 token）＋Activation Profile 128 条确定性规则；AI 参考确认全流程（confirm→stale→consumed→result_refs）＋三视角可见性契约＋证据回读校验 hash；evidence_links 节级证据编排 |
| writing | 四写入模式＋canonical/working 双模式＋candidate 隔离＋copy-on-write＋409 乐观锁；剧情冲突检查聚合三源＋AI 软冲突追加；POV 角色视角生成＋pov_validation 确定性泄漏诊断（仅 POV 模式） |
| settings | LLM 凭据加密/HMAC 指纹/snapshot 冻结/fail-closed/日志脱敏 |
| infrastructure/llm | ManagedLLMStep 权限阶梯 read/suggest/draft/act_with_confirmation＋OutputGuard＋ContextBudgetGuard＋journal |
| infrastructure/tasks | PG 任务队列：lease 心跳/coalescing/四档恢复策略（无 DAG/优先级/依赖等待） |
| project | workspace-summary 只读聚合＋smart-dedup 跨模块聚合 |
| interaction | RP 旅程：不可变消息树/分支选择/attempt 状态机/七分区 overview；明确不读作者 World/Outline/RAG/memory |
| 评测 | 回放评测 R01—R14 夹具三层门禁（确定性合同/模型质量/作者可用性） |

## 4. 差距矩阵：30 条

按严重度排序。关系标注：未覆盖=08-10 计划未覆盖；已计划=已覆盖（标注 7.x）；已裁定改向=用户 2026-08-13 裁定。

| # | 严重度 | 差距 | 关系 | 需求 | 供给侧现状（摘要） |
|---|---|---|---|---|---|
| 1 | high | partial | 未覆盖 | A1 结构化规则存储与查询(触发条件/公式变量/规则依赖) | RuleProfile 仅 rule_domain+constraints/exceptions/consequences 自由 JSON 列表(code 已核实 profiles.py)；RAG 只索引章节正文 chu |
| 2 | high | missing | 未覆盖 | B2 R 门风险台账与剧情触发引擎(含未裁定项自动升级) | ConflictCheckQueueItem 仅列表/resolve 无触发条件引擎、无优先级/硬边界字段(code)；CreationSuggestion 无 deferred→author-required 升级触发 |
| 3 | high | missing | 未覆盖 | C4 实例级社会真实度审计(六环/二十二面/同分母闭合/注入损耗) | 无对应能力；writing 冲突检查仅三源(code)；memory 连续性为 Scene 级非社会尺度(code) |
| 4 | high | partial | 已计划 7.11 | D1 设定依赖图与传递影响查询 | entity_relations 开放 relation_type 无依赖语义、无影响查询 API(code)；计划 7.11 仅限 World Bible page publish 的零写入反向遍历 |
| 5 | high | partial | 未覆盖 | D2 上游变更使下游工件失效待复核(世界→人物/大纲/正文跨层) | context confirmation 有 asset_changed→stale 但仅限确认引用(code)；scene_spans 重锚仅正文层(code)；7.11 只覆盖 bible publish 派生物 |
| 6 | high | partial | 未覆盖 | E1 术语注册表(别名语义角色/废弃-修订-神话态/世界内范围/认知上限) | aliases JSONB 开放 type 无语义角色、无废弃态标注、character_knowledge 不感知别名身份(code) |
| 7 | high | missing | 未覆盖 | E2/E3 多层术语对照矩阵与可用性元数据(获得路径/认知上限/已见范围) | 无等价结构(code 未见)；pov_validation 只检测 POV 模式泄漏不维护术语可达性(code) |
| 8 | high | missing | 已计划 7.9 | H4 外部模型交接协议(哈希留档/三分流/逐项验收) | imports 面向小说正文导入，无外部模型产物交接通道(code) |
| 9 | high | partial | 已计划 7.13 | I1 角色知识边界账(获取时间/来源/证据类/可信度/术语层/可披露对象) | CharacterKnowledge 仅 knowledge_level 七档/known_content/misconception/source_chapter_index/is_public_baseline(co |
| 10 | high | partial | 已计划 7.14 | I2 Scene 时点可证状态门禁 | memory scene checkpoints(source_hash/is_current/gap_reason)存在但 writing.generate 未消费、context 仅取章级 panorama(code |
| 11 | high | partial | 未覆盖 | J1/A5 大型设定上下文编译的项级控制与按需取层 | compile_with_tiers 仅 section 级排除、默认预算 4000 token、世界书展开深度 2(code/docs)；无项目级设定复杂度画像(project settings 自由 JSONB) |
| 12 | medium | missing | 未覆盖 | B3 强制结构变更记录(canon_diff 四段+六面审查三章节) | 无 change record 实体；修订链(EntityRevision/TextArchive/WorldBibleRevision)仅为内容版本(code)；计划 4.2 明确不建 Decision Ledger |
| 13 | medium | partial | 已裁定改向（第 8 节 #1） | B4 待定项唯一权威队列(P0/P1/P2 阻塞分级+最小回执) | 多队列并存(suggestion/conflict/dedup)无优先级分级、无单一入口(code)；计划 7.4 明确以运行时路由替代统一队列；2026-08-13 用户裁定做统一队列（P1-15） |
| 14 | medium | partial | 已计划 7.3 | B5 创作者决策最小化与批量采用 | review-groups/review-batch ≤20 决策/次、smart-dedup 组裁决、白堤式批量采用无专用入口(code) |
| 15 | medium | partial | 未覆盖 | B7 混合权威页面与权威链冲突消解 | 对象状态机+display_state 投影(code)无跨页权威链(最新裁定>总索引>领域页>候选页)语义 |
| 16 | medium | partial | 已计划 7.4 | C1 六面审查+覆盖面证据+轮次分级节律 | 无审查维度框架与覆盖面报告实体；任务 result 可承载回执(code/docs)；7.4 计划 preflight→定向重检→全量门禁 |
| 17 | medium | partial | 未覆盖 | C3 反捷径写作门禁(审查卡/新增实例门) | writing 冲突检查三源+Activation Profile 128 条确定性规则可承载部分(code)，但无反捷径约束库与正文 lint 形态 |
| 18 | medium | missing | 未覆盖 | C5 跨库交叉审计与状态漂移修复 | 无跨模块状态一致性审计能力；smart-dedup 只聚合去重建议(code) |
| 19 | medium | partial | 未覆盖 | C6 作者层术语/作者编码泄漏正文通用 lint | pov_validation 存在但仅 POV 生成模式(code)；作者桩号/夹具编号泄漏无通用正文扫描；R13 不覆盖作者编码分轨 |
| 20 | medium | partial | 未覆盖 | G3 对抗式创作伙伴(诊断四问/认知层标注/反驳) | writing AI 软冲突为显式追加流程(code)但无固定诊断工作流与认知层标注；7.4 preflight 覆盖部分路由 |
| 21 | medium | partial | 已计划 7.9(R03 分流+哈希去重)/7.15(P2 触发结构化世界书包) | H1/H2 不可变原始素材层+哈希审计+吸收分流记录 | imports 有内容签名校验与实体级去重(code)；无 _raw 式不可变源区、无哈希清单、无分流去向登记(code) |
| 22 | medium | partial | 未覆盖 | H3 被取代设定防回流机器门禁 | entity deprecated 状态存在但无机器规则拦截回归(code)；无「世界内旧学说」降级语义 |
| 23 | medium | partial | 未覆盖 | I3 未裁定实体反向注入防护 | include_pending_objects 默认关闭、candidate 显示为待处理(code)，但无负面边界强制执行 |
| 24 | low | missing | 未覆盖 | A2 数值置信分层与量级区间语义 | core_entities 无数值精度语义字段(code) |
| 25 | low | missing | 未覆盖 | B3 追加式日期裁定日志 | 无裁定日志实体(code) |
| 26 | low | missing | 未覆盖 | B6 事实正典与叙事定调分层 | 无独立基调/气质层；7.2 决策状态含命名边界(code/docs) |
| 27 | low | partial | 未覆盖 | F1 节级溯源(世界实体锚点级引用) | evidence_links TargetRef→SourceRangeRef 面向写作证据(code)，world 实体字段无来源锚点 |
| 28 | low | partial | 未覆盖 | G4 跨卷叙事禁区与披露过滤 | reveal_plans+reader_reveal_policies+伏笔 surface/hidden meaning(code)无卷级禁区清单与披露进度过滤 |
| 29 | low | partial | 未覆盖 | G5/G6 正典外创作资产库(灵感种子卡/NPC 模版库) | CreationSuggestion 队列 pending/adopted(code)无五段卡结构/防写歪清单/NPC 模版组合与冲突校验 |
| 30 | low | missing | 未覆盖 | H5 编号化修复台账(FIX-xx) | 无修复台账实体(code) |

完整字段（含证据与流程需求）见 `docs/references/data/2026-08-13-worldbook-gap-analysis.json` 的 `gaps` 字段。

## 5. 增强计划

### 5.1 P0 薄读门禁闭环（9 项）——全部零迁移，不建任何新表

#### P0-1 08-10 计划 P0 作者闭环首批切片延续（7.1—7.4）＋收束卡两列语义增强

- **覆盖需求**：B1, B5
- **与 08-10 计划关系**：延续 7.1/7.2/7.3/7.4（按 16.3—16.6 切片执行，不重复设计）；增强 7.3（decision_cards 每卡补「随本选项采用／不随本选项采用」两列＋decision compiler 主 payload 只含纳入项、未选细账不膨胀 pending）
- **实现形态**：前端编排 + 复用现有 JSON 薄读模型（7.3 revision_link 为计划内窄 CAS，落在现有 result_ref_json）
- **范围**：frontend-console Today 恢复指针、decision state 展示与 knowledge_expression_boundaries、收束本轮只读预览（manifest＋≤7 卡）、创作意图视图、修订此版窄 CAS；收束卡两列 + compiler 语义收窄
- **理由**：三版都以此闭环为地基（D1 显式 P0-12，D2/D3 全部增强项都挂 7.x seam）；wiki「工作名/机制细节/事件/组织/人物均不随字母选项自动采用」（第一地区裁定包 A/B/C/D）证明两列语义必须进收束卡，属零迁移 Prompt/前端扩展；本计划其余 P0 门禁（触发预检、变更记录）全部建立在此闭环之上
- **验证**：R01/R02/R04/R05/R09 夹具按 7.8 三层门禁验收；收束卡两列走查（选 A 不带走未列项、批量采用逐项回执）
- **风险**：本地会话有界存储 512KiB 边界与「修订此版」线性链 CAS 并发（计划已定义 409 回滚语义）；前端假成功态必须禁止

#### P0-2 术语与别名语义角色薄读约定（术语注册表 P0 形态）

- **覆盖需求**：E1
- **与 08-10 计划关系**：新增（7.2/7.13 均未覆盖术语中心状态）；为 P0-3 防回流 lint 与 P1-4 三层矩阵提供状态数据源
- **实现形态**：复用现有 JSON 薄读模型（world aliases JSONB 增加语义约定，不改列、旧记录可空、防御性读取）
- **范围**：aliases 条目加 type 角色枚举约定（in-world-name/canonical-revised/superseded/mythological）＋世界内使用范围＋认知上限标注；前端世界书术语视图按状态过滤（废弃灰显、神话态标注）；character_knowledge 展示感知别名身份（只读投影，不新建实体）
- **理由**：E1 high+not-covered；D1 放 P0（纯约定零迁移）、D2 放 P1（需 Pydantic 校验面）——以 wiki 证据强度裁决：canon_status 特殊值（月相缓存网关=canonical-revised、双星主节点=superseded）证明语义角色真实存在，防御性读取约定即可先上线并被 P0-3 lint 消费，typed 键校验契约随 P1-4 升级；D3 虽未立项但 P1-4/P1-5 也消费废弃别名最小子集
- **验证**：单元测试（别名投影按状态过滤、旧数据兼容）；回放夹具（superseded 旧称不回归、世界内常称与「除名」严格区分）
- **风险**：约定不被遵守时 lint 覆盖出现洞（P1-4 Pydantic 校验契约后闭合）；语义脱锚类区分仅约定级

#### P0-3 正文质量门禁确定性 lint 三合一（反捷径＋作者编码泄漏＋被取代设定防回流）

- **覆盖需求**：C3, C6, H3
- **与 08-10 计划关系**：增强 7.4（preflight 的规则内容与检查器）；新增通用正文 lint 形态（pov_validation 仅 POV 模式、7.2 forbidden_exact_terms 仅本轮约束，均未覆盖）；与 7.14 联动（历史 Scene 旧学说允许按当时态出现并带标注）
- **实现形态**：复用现有 JSON 薄读模型（Activation Profile 确定性规则集扩展 + forbidden_exact_terms + entity deprecated 状态消费）+ Prompt+流程纪律
- **范围**：writing 把 pov_validation 确定性泄漏诊断泛化为通用正文 lint（非仅 POV 模式）；Activation Profile 增三类确定性规则：反捷径 7 条（不用登记证明主体/不用失踪久证明死亡/新增实例门）、作者编码分轨（桩号/夹具编号/RH 键/FIX 编号/作者临时 ID）、防回流（deprecated/superseded 实体与别名默认排除或降级为「世界内旧学说」标注进入）；命中复用 ConflictDetailDialog 交互合同展示替代路径；LLM 语义诊断只进 7.4「可以改进」永不阻断
- **理由**：三版交集且全为 P0（C3/C6 三版均 P0；H3 两版 P0+一版 P1）；直接拦截正文质量事故（作者桩号「0+000—21+600」当门牌、失踪久=死亡、389,300/391,714 km 旧轨道值回归）；供给侧 128 条确定性规则＋forbidden_exact_terms＋deprecated 状态为现成 seam，零迁移；wiki 规则素材成熟（反捷径 7 条/防回流 19 条）
- **验证**：新增质量门禁类回放夹具（作者编码泄漏/捷径论证/旧值回流命中、历史 Scene 旧学说合法出现）；单元测试（规则命中/未命中、旧 POV 模式不回归）；走查 lint 文案与替代路径
- **风险**：确定性拦截只覆盖字面形态，语义变体靠 LLM 诊断（可改进级）；防回流依赖 P0-2 别名状态约定先行落地

#### P0-4 结构化规则条目与触发条件簿读约定（RuleProfile 语义约定）

- **覆盖需求**：A1
- **与 08-10 计划关系**：新增（7.1—7.14 均未覆盖）；为 7.2 决策状态与 7.4 运行时路由提供结构化规则数据源，为 P0-5 预检提供查询对象
- **实现形态**：复用现有 JSON 薄读模型（world profiles.py RuleProfile 现有 constraints/exceptions/consequences 自由 JSON 增加可选 typed rule_entry 子 schema 约定）
- **范围**：rule_entry 含 trigger_condition 触发条件/公式变量/magnitude_band 量级区间/derivation_chain 推导链；列结构不动、旧记录可空；前端世界书规则档案编辑视图；docs/prompts 同步契约
- **理由**：A1 not-covered+high，wiki 40% 页面含表格、34% 含公式（退化赛跑 D/U/R/ρ、U≥Θ 触发）证明写作引擎需要查询触发条件与量级而非读散文；D1 P0-1/D2 P0-3 两版 P0＋D3 P2-1，按「两版 P0 优先＋severity high」裁决进 P0；零迁移、向后兼容
- **验证**：单元测试（Pydantic 校验向后兼容、旧数据不报错）；回放夹具（规则触发条件可被确定性查询、生成情节符合已锁定量级）
- **风险**：自由 JSON 约定失控风险——P2-6 触发条件是 ≥3 真实项目 JSON 重复失控＋跨模块稳定查询

#### P0-5 写作前规则触发预检与「需要先裁定」门禁（含未闭合 R/FIX 项登记）

- **覆盖需求**：B2, F2
- **与 08-10 计划关系**：增强 7.4（7.4 原仅覆盖「已存在 live signal」的运行时分流，本项补触发条件驱动的命中门禁与数据源）
- **实现形态**：Prompt+流程纪律 + 前端编排（触发匹配为确定性代码，读 P0-4 规则条目与 P0-8 回执登记的未闭合项）
- **范围**：writing.generate 预检对当前章节/Scene 主题做确定性触发条件匹配，命中即「需要先裁定」提示＋深链，不阻断、未命中不污染待办；context confirmation 展示命中清单；生成 Prompt 纪律「涉及能力上限、主体性、法定同意的取舍必须先裁定」
- **理由**：B2 是唯一三版全 P0 的治理项（D1 P0-2/D2 P0-3+D2 P0-4/D3 P0-1）；R-46 式「写国家税基即触发开门」是 wiki 最强治理机制；触发条件存于 RuleProfile 薄读内、匹配为确定性代码即可运行，无需新表；deferred 持久语义留 P1-5（按 7.3 门槛——真实回放证明 pending 污染待办后实施）
- **验证**：回放夹具 R15（R-46 式写税基命中开门、未触发项不出现在待办）；单元测试（匹配确定性）；窄屏与文案走查
- **风险**：触发条件覆盖依赖作者登记完整性，未登记场景不拦（诚实边界，7.4 免责口径兜底）

#### P0-6 未裁定实体负面边界强制执行（含半锁定态语义）

- **覆盖需求**：I3, A3
- **与 08-10 计划关系**：增强 7.4（未触发情景门槛不污染待办的正向语义之外，补反向注入防护）
- **实现形态**：复用现有 JSON 薄读模型 + 确定性规则（context 编译纪律，fail-closed）
- **范围**：context 编译时对非 canonical 实体只投影最小定义/负面边界；include_pending_objects 保持默认关闭；「存在已锁定、属性开放」以现有 status 字段组合表达半锁定态；生成与建议 Prompt 纪律「未裁定实体不向其他页面反向注入事实」；world 前端候选审阅页只显最小定义
- **理由**：I3 两版 P0+一版 P1（D2 P0-4/D3 P0-5/D1 P1-11），按交集优先进 P0；wiki 龙族/精灵/飞升者三例证明「裁定前不反向注入」是重复出现的生成纪律而非一次性内容；编译侧确定性过滤零迁移
- **验证**：单元测试（非 canonical 实体投影只含最小定义+负面边界）；回放夹具（龙族事实不扩散、候选事实不进正文上下文）；R05/R13 夹具扩展断言
- **风险**：负面边界内容靠作者书写，无内容时退化为「最小定义」投影，覆盖深度有限

#### P0-7 统一待决队列先行切片（阻塞分级投影＋两列语义，为队列 schema 提供真实测量）

- **覆盖需求**：B4
- **与 08-10 计划关系**：替代 7.4「不造统一校验队列」定案（2026-08-13 用户裁定：做统一队列）；本项为队列的首批切片
- **实现形态**：前端编排（只读合成视图，阻塞级为计算投影不落库——先行切片）
- **范围**：Today「需要你决定」与世界书审查页为各领域待决项补阻塞分级投影（源于各领域既有状态，不聚合持久化）与最小回执模板（已锁定/仍需裁决）；为 P1-15 统一队列 schema 积累真实测量（待决项分布、分级使用频率、回执使用情况）
- **理由**：用户 2026-08-13 已裁定做统一队列；投影先行作为零迁移切片立即上线，同时为 schema 设计（数据源、分级语义、回执生命周期）提供真实测量，避免凭 wiki 单样本直接定 schema
- **验证**：R05 扩展断言（候选≠错误、延期不污染待办、P0 阻塞项醒目、批量采用后队列收缩）；窄屏与空态走查
- **风险**：投影与队列 schema 并存过渡期存在两处入口语义漂移——以投影为 schema 的验收基准，队列上线后投影收敛

#### P0-8 强制结构变更记录模板与检查回执（canon_diff 四段＋六面审查维度＋回执模板）

- **覆盖需求**：B3, C1, C2
- **与 08-10 计划关系**：增强 7.3（source manifest 补「新增锁定/未改/仍待定/受影响工件」语义）；增强 7.4 R08（审查回执补六面审查维度与覆盖面证据模板）；仍守 4.2「不建 Decision Ledger」
- **实现形态**：Prompt+流程纪律（生成中心 typed response 增固定变更记录模板区块）＋前端编排（按日期追加只读视图）；缺节降级为前端显式提示，不硬拒
- **范围**：采用/发布/裁定后从现有 EntityRevision/TextArchive/WorldBibleRevision 链、task result 回执、decision state 派生四段记录视图（新增锁定/未改/仍待定/受影响工件）＋检查范围回执（scope/checks run/not run/omissions/覆盖面计数）；FIX-xx 编号计数器用项目 settings 自由 JSONB 约定；不建 Decision Ledger（守 4.2 边界）
- **理由**：B3/C1 medium、两版 P0（D1 P0-8/D3 P0-3）而 D2 整体延后治理类——以 wiki 证据强度裁决：『编号只能证明看过原则，这些章节才记录如何裁决』是治理闭环的书面证据，且全部素材已存在于 revision 链＋task result，纯读模型零迁移；「机器校验缺节即拒」降级为前端显式提示（D1 与 D3 分歧取 D1，避免过度强制）
- **验证**：回放夹具 R17（采用后四段完整、回执带未运行项、缺节显式提示）；日期追加视图走查
- **风险**：模板过重打击轻量创作冲动——P0 人工走查持续校准模板最小化；提示级强制力弱于 wiki 原体系

#### P0-9 回放评测夹具补充（R15—R17 类场景断言）

- **覆盖需求**：B2, E1, H3, D2, B3
- **与 08-10 计划关系**：增强 7.8（R01—R14 三层门禁补规则触发/术语过滤/防回流/下游标脏/变更记录四段场景，为 P1 立项与 P2 触发判定积累证据基线，承接 open_questions#7）
- **实现形态**：复用回放评测（7.8 夹具体系扩展）
- **范围**：补 R15 规则触发与门禁、R16 下游标脏、R17 变更记录四段、术语过滤与防回流断言；脱敏合成数据，不复制 Vault schema
- **理由**：三版一致要求夹具先行（D1 P0-10 显式立项、D2 P0-4 含夹具扩充、D3 各验证节引用）；wiki 新证据（术语矩阵/触发引擎/防回流）在 7.8 夹具中无对应场景断言；零 schema、CI 离线可运行，是 P1 立项与 P2 触发条件的证据基础设施
- **验证**：CI 离线可运行、断言可审查、失败解释可读
- **风险**：合成数据失真导致断言与真实场景偏差——脱敏规则可审查

### 5.2 P1 窄增强接线＋已裁定立项（15 项）——14 项窄增强（仅 3 项可选字段扩展）＋1 项用户裁定的新 schema

#### P1-1 跨层失效下游待复核（世界变更→人物/大纲/正文待复核投影＋写作前对照）

- **覆盖需求**：D2
- **与 08-10 计划关系**：增强 7.11（发布预演外扩到跨层：world 采用/发布/revision 事件后 Today/受影响流程计算下游待复核清单；写作前对照复用 7.11 typed refs 反向遍历与 context confirmation stale 语义）
- **实现形态**：前端编排为主（零写入读模型）＋窄契约增量（可选 target 版本引用，按 7.13 延迟的 target-version 提醒门槛补）
- **范围**：world 变更事件后按需计算下游待复核：context 已有 asset_changed→stale、outline open_decisions、writing evidence_links 引用资产版本对照，前端「N 处下游待复核」卡片＋各领域深链；写作/生成前对照当前引用源变更，命中进「必须重新确认」并显示「谁引用了它」最小路径；不建依赖表、不自动标脏全部下游工件
- **理由**：D2 high；三版都覆盖但相位 P0/P1/P1——取中位 P1，并把 D1 P0-6 的纯前端读模型作为首切片（零写入先行）；wiki 可演化框架第 7 步「世界层变更后人物/故事/细纲/正文至少进入待复核」是明确行为需求，供给侧已有 asset_changed→stale 与 scene_spans 重锚，缺的是按变更事件组装成作者可见入口
- **验证**：R16 夹具（世界层变更→下游至少待复核、旧回执不冒充当前结论、作者确认后消失）；单元测试（stale 计算）
- **风险**：无依赖边时覆盖靠信号枚举会漏（「本次未检查」文案兜底）——P1-7/P2-3 逐步补边

#### P1-2 Scene 时点可证状态门禁（7.14 首批切片）

- **覆盖需求**：I2
- **与 08-10 计划关系**：延续 7.14（checkpoint 接入 writing.generate、scene_state_fingerprint 契约增量、gap 省略；D2 已把接线并入预检链，本项按 08-10 计划 P1 相位执行，只接线不重造）
- **实现形态**：复用现有能力（memory 五维 checkpoint 体系已 code 核实）＋窄契约增量（confirmation compile_options 增可选 scene_state_fingerprint）
- **范围**：修 MemoryRecordsLoader dict/list 渲染根因；writing.generate＋scene_id＋reveal_mode=character 接入 memory 五维 checkpoint 编译为可读导演约束；gap/尚无时间锚显式省略＋地图深链；「投影未记录」不得推成「当时不存在」；补旧 confirmation/旧客户端兼容测试
- **理由**：I2 high+already-planned；D1 P1-4/D2 P0-4（预检链内接线）都只接线不重立项；三版一致认可 checkpoint 体系已存在、缺的是写作接线，属纯复用
- **验证**：R14a—f 夹具（未来状态不回流、未记录≠不存在、gap 修复后指纹失效要求重新确认）
- **风险**：普通 World 编辑无 Scene 锚，首批只覆盖 writing.generate 主路径——诚实标注不宣称全模式安全

#### P1-3 角色知识账字段刷新与 7.13 首批落地

- **覆盖需求**：I1
- **与 08-10 计划关系**：增强 7.13（R13 needs-refresh 项：补 evidence_class/confidence/terminology_layer/can_disclose_to 四字段与同角色/目标确定性检查点选择；其余按 16.11 切片执行）
- **实现形态**：窄 schema 增强（world 模块 CharacterKnowledge 增加四可选字段，向后兼容、旧数据默认值语义一致；若字段超可选兼容范围需 ADR）＋复用回放评测
- **范围**：CharacterKnowledge 可选四字段；同角色/目标确定性知识检查点选择、角色卡知识进程视图与就地修复、POV 确认完整展示按 7.13 切片；RAG 命中永不自动授予知识保持硬约束；R13 编译消费 terminology_layer（喂 P1-4 角色侧过滤）
- **理由**：I1 high+already-planned；wiki 角色知识与时间账模板六字段证明这些维度真实使用（撤销「当前文明普遍知道真名/根地址」认知跳跃即靠来源与可信度证据）；D1 P1-3/D2 P1-4 方案一致
- **验证**：R13a—f 夹具＋单元测试（检查点确定性、同章保守、旧数据兼容、知识带术语层时的过滤断言）
- **风险**：字段超可选兼容范围则需迁移评审与 ADR——实施前先评审迁移面

#### P1-4 三层术语对照矩阵与可用性四列（术语×角色可达性编译）

- **覆盖需求**：E2, E3
- **与 08-10 计划关系**：增强 7.13（POV 编译补术语层过滤与翻译方向校验；7.13 是人物知识进程视角、本项是术语中心四列，不同层）
- **实现形态**：复用现有 JSON 薄读模型（P0-2 别名约定升级为 Pydantic 校验的 typed 键并扩展三层对照与可用性元数据，仍不建表）＋编译消费
- **范围**：术语条目承载三层对照（本源/各学派学术/地方世俗＋翻译方向规则：本源→学术✓、世俗→学术△）＋可用性四列（作者层地位/已见世界内范围/典型获得路径/角色认知上限）；R13 POV 上下文编译消费术语层过滤（对话只暴露角色可达含义）；跨层混用与翻译方向校验落为 P0-3 lint 确定性规则（本源层术语禁入对话/独白/叙述的 C6 完整落地）
- **理由**：E2/E3 high+not-covered；D1 P1-2/D2 P1-3 一致放 P1（依赖 P0-2 契约与 R13 编译消费）；wiki 三层术语对照表 9 主题五列、可用性矩阵四列是直接素材；跨层混用直接决定生成质量（跨学派同词不同义不混用）
- **验证**：回放夹具（本源→学术翻译方向校验、跨层混用检出、世俗→学术△警告、角色可达性过滤）；单元测试（lint 确定性、编译预算）
- **风险**：未登记术语无机器保障——薄读覆盖以作者登记为界（承接 open_questions#3 通用 per-project 术语表形态）

#### P1-5 冲突队列窄增强与 deferred→author-required 升级 CAS

- **覆盖需求**：B2
- **与 08-10 计划关系**：增强 7.4（世界冲突队列从无优先级状态补阻塞分级与触发条件持久化；按 7.3 门槛——真实回放证明 pending 污染待办才加 deferred 行为）
- **实现形态**：窄 schema 增强（world/models/worldbuilding.py 的 ConflictCheckQueueItem 增加可选 priority/hard_boundary/trigger_condition 字段，向后兼容；CreationSuggestion 增加可恢复 deferred 行为与窄升级 CAS 动作）
- **范围**：R 门台账的持久分级/硬边界/升级触发器；CreationSuggestion「首次进入剧情」延迟触发升级 author-required 的窄 CAS 动作（升级不可逆，元数据落现有 JSON 列，不建台账表）
- **理由**：P0-5 触发匹配是运行时薄读，持久分级/硬边界/升级触发器需要窄 schema；wiki deferred 五问题「剧情正面使用时立即升级 author-required」是明确行为语义；D1 P1-1/D2 P1-6/D3 P0-1 三版覆盖 B2、schema 面一致收敛到 P1
- **验证**：单元测试（CAS 升级/降级路径不可逆、并发安全）；R15 夹具（deferred 项在触发场景命中自动升级）
- **风险**：升级语义并发安全（同一 deferred 项多处消费）——CAS 加并发测试；台账化完备性留 P2-6

#### P1-6 设定复杂度画像与上下文编译项级控制

- **覆盖需求**：J1, A5
- **与 08-10 计划关系**：增强 7.6（从「被缩短/替换」透明化展示升级为可操作控制）；A5 权威链展示约定与 7.11 总入口索引摘要不重复
- **实现形态**：前端编排（画像为 project workspace-summary 只读聚合窄投影）＋窄增强（context compile 请求加可选项级白名单，旧调用方省略时行为不变）
- **范围**：workspace-summary 扩展窄投影（实体/页面/别名/规则条目数、体量分布、tier 分布）；前端「今日工作/生成中心」显示复杂度画像与默认预算分级建议（建议性不强制）；compile 请求项级白名单（钉选/排除具体实体、页面、规则条目，复用已选资产 seam）；确认弹窗展示被裁项与钉选状态；总入口只作索引摘要、权威细节挂领域页
- **理由**：J1/A5 high+not-covered（2MB/99 页设定库对 4000 token 默认预算被静默截断）；D1（画像 P0+控制 P1-7）与 D2 P1-1 合成——画像纯读先行、项级白名单为窄兼容扩展而非新 schema，直接解决控制缺口
- **验证**：单元测试（计数投影向后兼容、裁剪审计不变式、旧客户端兼容）；钉选/排除/透明可见三态走查；空项目/巨型项目两级展示
- **风险**：项级白名单加大编译请求复杂度——保持可选字段、旧调用方零改动

#### P1-7 实体依赖边语义约定与影响预演五类处置

- **覆盖需求**：D1, D2
- **与 08-10 计划关系**：增强 7.11（预演起点从页面级反向遍历扩展到实体/关系/地图事实；补五类处置动作与处置回执）
- **实现形态**：复用现有 JSON 薄读模型（world entity_relations 开放 relation_type 加 depends_on 语义约定：单向注册「上游变更必须复核下游」，非新表）＋前端编排（处置走既有 owner 路径、预演零写入保持）
- **范围**：7.11 影响预演将实体/关系/地图事实纳入起点（复用 O(P+E) 循环安全扫描与 impact_scope_hash）；发布确认区五类处置 UI（保持/同步修复/降为候选/作者裁定/继续开放）；处置记录落 task result 回执；P1-1 待复核读模型消费该边
- **理由**：D1 P1-5/D3 P1-2/D2 P2-3——两版 P1 裁决进 P1；wiki 140 节点/494 边依赖图证明「不能让孤立页面绕开影响分析」，但持久图生命周期按 7.11 门槛（跨会话复核证明返工）留 P2-3
- **验证**：R11 扩展夹具（实体变更→下游页面/人物提示复核、处置状态可回放、处置动作不写下游）；单元测试（环安全、跨项目隔离、约定边解析）
- **风险**：依赖边靠作者登记，图不完整时预演漏项——「本次未检查」文案兜底

#### P1-8 状态漂移确定性检查器与跨库权威链审计（含对抗式诊断四问）

- **覆盖需求**：C5, B7, G3
- **与 08-10 计划关系**：增强 7.4（「检修当前世界页/对象」固定 workflow 确定首个检查类型并接通 ConflictCheckQueueItem 真实生产者，满足 7.4「先证明真实生产者」验收前提；补权威链显示纪律与 LLM 诊断内容）
- **实现形态**：前端编排 + 确定性规则（漂移检出为确定性比较）＋Prompt+流程纪律（诊断四问进生成中心 guard）
- **范围**：检修 workflow 确定性检查类型「状态漂移」（已采用仍标候选、display_state 与 status 不一致、索引滞后 stale 标志、开放因果被写死→可检状态类）结果写入现有 ConflictCheckQueueItem；重跑只处理当前 target、新 hash 旧结果退出当前视图；同页分区状态标注复用 projection_policy 分区、权威顺序（最新裁定>总入口索引>领域页>候选页）为展示约定、跨页漂移处置走现有状态机 CAS；生成中心 _CHAT_SYSTEM_PROMPT 与提案 guard 加固定诊断步骤（能量守恒/认知分层/后果链/悖论四问）＋认知层标注＋允许反驳并给修正思路
- **理由**：C5 medium；D1 P0-11+P1-8/D3 P1-3/D2 延后——裁决进 P1（确定性检查器是 7.4 冲突队列首个生产者的前置，与 7.4 切片衔接）；G3 仅 D1 P0/D3 P1 覆盖、纯 Prompt 零 schema 低成本，并入本项（wiki 虚境架构师预设证明「避免唯命是从的 AI」是真实需求）
- **验证**：单元测试（漂移检出、历史记录不倒改）；回放夹具（结构 0 error 仍检出「已采用仍标候选」、提案被一致性诊断并给修正思路）；LLM 输出 schema 校验（诊断四问+认知层标注必含）
- **风险**：语义类漂移（授权来源含混等）确定性不可检——走 7.4 可选 LLM 诊断路径，只进「可以改进」

#### P1-9 实例级社会真实度审查卡（六环/二十二面压缩为审查卡＋注入损耗预演）

- **覆盖需求**：C4
- **与 08-10 计划关系**：增强 7.4（检修 workflow 的 LLM 诊断检查类型）＋新增（供给侧完全无对应能力）
- **实现形态**：Prompt+流程纪律（审查卡为固定检查表内容）
- **范围**：检修 workflow 增加 LLM 诊断检查类型「社会真实度」：六环/二十二面压缩为固定审查卡（账本闭环/认知分层/生命身份/物理尺度/社会后果/叙事呈现＋同分母闭合与注入损耗检查提示），输出 schema 化为「需要决定/可以改进」；正文生成侧 Prompt 纪律「注入损耗与执行落差」（真实城市会漏人、漏水、欠修、迟记）；覆盖面证据进 P0-8 回执
- **理由**：C4 high+missing、三版分歧最大（D1 P0-13/D3 P2-5/D2 整体延后治理类）——裁决：wiki 框架本质是审查流程而非数据结构，Prompt 审查卡零迁移，但宿主检修 workflow 与 P0-8 回执在 P0 落地后才成立，取 P1 折中；不做成熟度双轨评级与专用报告实体
- **验证**：回放夹具（白堤 WD-R 式「全知规划报告式候选」被检出）；走查（审查卡输出不冒充正典）
- **风险**：同分母闭合的确定性检查依赖 A2 数值语义（P1-10 登记数值），未登记部分仅提示；LLM 诊断覆盖深度有限

#### P1-10 数值置信分层与量级区间语义

- **覆盖需求**：A2
- **与 08-10 计划关系**：新增（7.2 命名/表达边界未覆盖数值置信语义）；承接 open_questions#6
- **实现形态**：复用现有 JSON 薄读模型（core_entities 可选数值语义 JSON 约定）＋Prompt 纪律先行
- **范围**：先以 P0-4 规则卡标注参数角色（正典值/示例值/叙事工作值＋单位＋量级区间）＋写作 Prompt 按精度语义选词（工作值不得固化为硬设定、按角色视角选表达精度）；回放证明 Prompt 纪律不稳定（工作值固化拦截率不达标）再给 core_entities 加可选 value_confidence/量级区间字段（窄迁移需兼容测试）；C4 同分母闭合确定性检查在登记数值上运行
- **理由**：A2 low；D1 P1-10/D2 P1-5 一致：低成本约定优先于继续自由文本（open_questions#6）；wiki「约2000年只是基准使用年示例」「约72小时只是叙事工作值」证明精度语义直接决定生成质量，但低 severity 不建字段类型系统
- **验证**：单元测试＋回放夹具（工作值固化拦截、量级区间选词、同分母闭合检查）
- **风险**：Prompt 纪律稳定性不确定——以回放拦截率为字段化触发证据

#### P1-11 叙事定调独立裁定类别

- **覆盖需求**：B6
- **与 08-10 计划关系**：增强 7.2（decision state 增「定调裁定」类别＋「本裁定不新增或修改任何世界事实」强制声明字段，不建基调实体）
- **实现形态**：复用现有 JSON 薄读模型（7.2 可选边界字段形状）＋前端编排（审阅视图定调分栏）
- **范围**：定调/气质裁定作为 decision state 独立区块；定调内容存世界书页面 author-only 分区；定调动作固定回执文案「本裁定不新增或修改任何世界事实」；AI 审查不得替作者改主题的 guard 语义
- **理由**：B6 low；D1 P1-14/D3 P1-6 一致；wiki 白堤气质定调「不触及 B0—B6 世界事实」＋「不宜由审稿人偷偷替创作者决定」证明定调与事实分层是真实工作形态；7.2 字段形状已备，本项只给定调正式入口与回执
- **验证**：回放夹具（定调裁定不触发事实变更、声明缺省拒收、审查不替作者改主题）；走查分栏文案
- **风险**：定调与事实边界靠作者声明——缺省拒收保证声明存在，不保证语义正确

#### P1-12 节级溯源锚点（实体字段→来源页小节）

- **覆盖需求**：F1
- **与 08-10 计划关系**：增强 7.7（问世界引用回读补实体字段级锚点；7.7 原面向页面/正文证据）
- **实现形态**：窄 schema 增强（world 核心实体增加可选 source_anchor 字段，复用 context TargetRef 形状，锚点级引用）
- **范围**：实体字段可追溯至来源页小节（[[页#小节]]）或裁定页；问世界与实体详情展示消费锚点；生成引用带来源
- **理由**：F1 low、仅 D1 P1-12 覆盖，但复用 context TargetRef seam 成本极低且直接提升 7.7 引用质量（wiki 魔杖/卷轴来源节均为页#小节锚点、Solis Primus 来源为裁定页），作为低优先级窄字段保留
- **验证**：单元测试（锚点解析）；溯源展示走查
- **风险**：锚点登记为可选字段，覆盖渐进

#### P1-13 08-10 计划 P1 证据闭环切片延续（7.5/7.7/7.9/7.10/7.12）

- **覆盖需求**：G2, H4, H1, H2
- **与 08-10 计划关系**：延续 7.5/7.7/7.9/7.10/7.12（按 16.7—16.10 切片执行，不重复设计）
- **实现形态**：Prompt+流程纪律 + 前端编排（复用 R03 收束预览 seam）
- **范围**：邻接探索一跳回查、问世界（引用/拒答门槛达标后上线，答案只存建议、需过 P0-2 术语状态过滤）、创作交接快照（单 target 出站快照 manifest/hash/回包约定≤55,000 字符/checks_run 声明/拒绝继承外部编号；回流 Web Crypto SHA-256 留档与精确重复 no-op；compatible/repair/candidate/unmapped/exact_duplicate 三分流预览；应用后 P0-8 回执定向复验；不调用 imports）、视觉简报与结构化采用、最低充分回应与单一纵切
- **理由**：H4 high+already-planned（7.9 方案已定：5 包 205KB/12,627 行/三分流/拒绝虚构 FIX 编号是最完整交接协议证据）；D1 P1-6/P1-15 承接、D2/D3 预设 7.x 为地基；增强计划只承接不重设
- **验证**：R06a—e/R07/R10/R12 夹具＋问世界引用可打开率与正确拒答率门槛；纵切夹具补同分母闭合断言
- **风险**：交接快照超限拒绝与 409 语义按 7.9 验收口径；不可变源存储留 P2-4

#### P1-14 F2/H5 未闭合项登记薄读（编号计数器约定）

- **覆盖需求**：F2, H5
- **与 08-10 计划关系**：增强 7.4（P0-5 触发预检消费未闭合 R/FIX 项；FIX-xx 编号计数器为 project settings 自由 JSONB 约定，不建台账实体）
- **实现形态**：复用现有 JSON 薄读模型（project settings 自由 JSONB 计数器约定）＋前端编排
- **范围**：FIX-xx/R-xx 编号计数器在项目 settings 自由 JSONB 约定（跨会话追加编号）；P0-5 预检读未闭合项避让正文；修复台账视图从 task result/回执派生只读展示
- **理由**：F2/H5 low；D1 P0-2/P0-8 以薄读承载、D2/D3 未立项——合成取最小承载形态置于 P1 末尾（低优先级薄读补丁，等真实使用证据再评估）
- **验证**：单元测试（计数器追加、跨会话一致）；台账派生视图走查
- **风险**：编号唯一性靠约定维护，无强校验

#### P1-15 统一待决队列权威 schema（用户裁定立项，2026-08-13）

- **覆盖需求**：B4
- **与 08-10 计划关系**：替代 7.4 路由方案（用户 2026-08-13 裁定改向；原 P2-2 触发式立项升级为正式立项）
- **实现形态**：新 schema（用户已裁定方向；落地细节走 ADR 记录：领域所有权、聚合数据源、迁移与删除语义；新接口做 deletion test）
- **范围**：world 模块内统一待决队列实体：聚合世界书领域各待决信号（CreationSuggestion pending、ConflictCheckQueueItem、smart-dedup 建议、候选/待定对象状态）为单一权威审查入口；条目持久化 P0/P1/P2 阻塞分级、「已锁定|仍需裁决」两列、最小回执模板、「首次进入剧情时再审」延迟触发、跨设备持久生命周期；裁决动作仍走各领域既有 CAS（7.3 收束卡/现有批处理），队列只承载裁决语境与分级；不建顶层模块
- **理由**：用户 2026-08-13 裁定「做统一队列」，取代 08-10 计划 7.4「不造统一校验队列」定案；wiki 证据（待定术语唯一权威队列、P0 阻塞分级、最小回执）为需求来源，产品化为通用 per-project 形态而非复制 Vault 结构；P0-7 投影测量为 schema 设计输入
- **验证**：ADR 记录（所有权/迁移/删除语义/deletion test）；单元测试（队列条目生命周期、跨设备持久、升级不可逆）；回放夹具（延期项不污染、升级路径可审计、批量采用后队列收缩）
- **风险**：聚合查询在领域侧新增读取路径，跨模块契约面扩大——限定 world 领域内聚合，跨领域扩展留待真实使用证明

### 5.3 P2 触发式 schema（5 项）——全部押后至真实项目证据＋ADR

每项的触发条件如下；在触发条件成立前，一律以 P0/P1 的薄读形态运行并积累测量证据。

#### P2-1 独立术语注册表 schema（术语一等实体）

- **覆盖需求**：E1, E2, E3
- **与 08-10 计划关系**：替代 P0-2/P1-4 薄读约定（升级为正式生命周期）
- **触发条件**：触发条件：≥3 个真实项目出现术语矩阵 JSON 重复失控、四处跨模块稳定消费同一注册表、且作者需要跨项目复用术语包；真名回响单项目证据不构成触发条件（open_questions#2/#3：先以通用 per-project 术语表薄读形态试点，P0-2/P1-4 已上线并积累测量）
- **范围（触发后）**：术语作为一等实体：三层对照＋可用性四列＋权威链＋状态机（在用语/废弃/神话）；跨模块统一契约（writing lint、context 编译、R13 过滤、问世界四处消费）；ADR 明确领域所有权、owner、迁移与删除行为
- **验证**：ADR 先行（领域所有权/API/schema/wire/迁移/删除）；回放夹具回归不倒退
- **风险**：专有方法论泛化失控——通用层抽象在 ADR 中一并回答

#### P2-3 持久影响审查生命周期与实体依赖边

- **覆盖需求**：D1, D2
- **与 08-10 计划关系**：增强/替代 7.11 与 P1-7（7.11 已列门槛：跨会话必须证明谁何时复核哪版 scope 而现有 revision＋task result 无法回答）
- **触发条件**：触发条件按 7.11 门槛：≥3 个真实项目或同一长期项目连续 3 次因「跨会话复核证明缺失」产生返工；wiki 依赖边补建后 2 条/23 条既往变更未覆盖新增下游正是该返工形态，但需产品侧真实数据触发；单纯页面多、想画关系图或一次 O(P+E) 扫描存在不满足建表条件
- **范围（触发后）**：影响复核记录生命周期：who/when/which scope hash/失效规则/保留期；依赖边持久化与图变化失效语义；传递影响查询接口
- **验证**：ADR 先行（owner/保留期/失效/迁移/删除行为）；回放夹具回归
- **风险**：建表成本与跨模块契约风险——触发门槛未达前一律用 P1-7 约定边＋「本次未检查」兜底

#### P2-4 结构化世界书包与外部导入预览

- **覆盖需求**：H1, H2, H4
- **与 08-10 计划关系**：延续 7.15（启动门槛已列：单个不可按 target 拆分的回包超限/顺序回流摩擦成主要痛点且 R06 失败回放达标）
- **触发条件**：7.15 已定义全部门槛与最小产品形态；P1-13 顺序回流失败回放达标后才触发；涉及新 world-owned 存储与稳定生命周期必须用户确认＋ADR，不得藏进 task meta/result
- **范围（触发后）**：world-owned 不可变 source 存储：哈希留档、manifest、分流去向登记、_raw 式不可变区；首版只做外部审查包预览，不做通用世界书格式；ADR 明确存储/保留/删除/加密/备份/owner 隔离
- **验证**：ADR 先行（存储/保留/删除/加密/备份/迁移）
- **风险**：通用附件存储缺失，P2-4 涉及存储选型——ADR 先行控制

#### P2-5 Decision Ledger 类持久变更记录生命周期

- **覆盖需求**：B3, C1
- **与 08-10 计划关系**：替代 P0-8 模板读模型（8.2 五条门槛：同一创作意图跨 ≥3 owner、跨设备完整审查生命周期、薄读模型已有测量证据且问题非前端信息架构造成等同时成立才 ADR）
- **触发条件**：4.2 明确不建 Decision Ledger，只有 8.2 五条门槛同时成立才 ADR；P0-8 读模型先上线积累「薄读是否足够」的测量证据，问题不是前端信息架构造成的才能触发
- **范围（触发后）**：变更记录与审查回执一等实体：canon_diff 四段、六面审查覆盖面证据、「锁定/未改/仍待定/受影响工件」语义的持久生命周期（保留期/删除语义）
- **验证**：ADR 先行；deletion test（跨模块业务判断不入 facade/组合根/前端）
- **风险**：裁定记录随 task 淘汰的跨会话追溯返工是触发形态，需真实证据计数

#### P2-6 结构化规则与 R 门台账 schema（A1/B2 完整形态）

- **覆盖需求**：A1, B2, D1
- **与 08-10 计划关系**：替代 P0-4 薄读约定与 P1-5 窄字段（触发条件/公式变量/规则依赖边成为稳定字段；写作引擎查询规则而非只读散文；R 门台账生命周期）
- **触发条件**：（对应 open_questions#2 门槛）≥3 个真实项目反复需要按触发条件/公式变量查询规则、P1-5 触发门禁被真实项目证明必不可少、且薄读 JSON+Prompt 无法承接（JSON 重复失控/跨模块稳定查询）；wiki 140 节点依赖图与 canon-dependencies.json 是专有形态，产品化须抽象到通用层（open_questions#3）
- **范围（触发后）**：world RuleProfile/风险台账字段化＋migration＋按触发条件/量级查询接口；规则条目进入 RAG/上下文；规则依赖边与传递影响查询；ADR 明确领域所有权、迁移与回滚
- **验证**：回放夹具（结构化查询断言）；ADR 门禁（领域所有权/迁移/回滚）
- **风险**：跨模块契约与迁移风险——薄读试点（P0-4/P0-5/P1-5）必须先行积累测量证据

## 6. 明确不做（本增强计划范围内）

- 不新建 Decision Ledger、依赖图表、独立术语表——4.2 边界维持，全部押后至 P2 触发条件（≥3 真实项目证据或用户裁定）＋ADR；单项目 wiki 证据（真名回响）一律不构成新 schema 触发条件。唯一例外：统一待决队列——2026-08-13 用户已裁定立项（P1-15），取代 7.4「不造统一队列」定案。
- 不复制 Vault 专有形态（三层术语矩阵/canon_diff/六面审查/140 节点依赖图/63 项 R-xx）为产品 schema——按 open_questions#3 抽象到通用层（per-project 术语表/变更记录模板/审查卡），专有内容作为该项目 World Bible 内容由作者自建。
- 不做 RP 域受控只读注入（术语白名单）——interaction 继续不读作者 World；三版一致维持隔离，待真实 RP 用户出现术语泄漏反馈再评估（open_questions#5）。
- 不做 Vault 只读导出适配/同步——接受作者手工重建或经 7.9 交接快照回流；作者侧重建成本未量化，留待真实用户数据（open_questions#4）。
- 不建社会真实度专用报告实体与成熟度评分平台——C4 只做审查卡＋回执；文件数/行数/候选数式精确统计与人工进度台账以 P0-8 回执模板承载。
- 不立项 G4 跨卷暗线管理/G5 灵感种子卡/G6 NPC 模版库/H5 编号化修复台账独立形态——仅一版覆盖＋low severity；继续走现有 CreationSuggestion 队列与页面 author-only 分区，待真实使用证据（≥3 项目或作者明确要求）再以 typed payload 约定低成本补入。
- 不建跨模块聚合 facade/顶层 review 模块/第二知识库/图数据库/Agent runtime——4.1 不变量与「统一发生在作者视图，不在数据库里复制各领域事实」维持。
- 不把『写作引擎查询规则而非读散文』『三层矩阵』『触发引擎』等能力目标当作实现形态承诺——一律先薄读试点，实现形态由 P0/P1 落地证据驱动。

## 7. 落地顺序与依赖

P0 内部依赖链：**P0-1 作者闭环**（延续 08-10 首批切片，一切门禁的宿主）→ **P0-2 术语状态约定**（数据源）→ **P0-3 质量 lint 三合一**（消费术语状态）→ **P0-4 规则条目约定**（数据源）→ **P0-5 触发预检**（消费规则条目与 P0-8 未闭合项）→ **P0-6 负面边界** → **P0-8 变更记录模板** → **P0-7 统一队列先行切片**（投影测量先行）；**P0-9 回放夹具**（R15—R17）伴随各 P0 项验收同步补。

P1 内部依赖链：**P1-2 时点门禁**（7.14 纯复用接线，最早可启动）→ **P1-3 知识账字段** → **P1-4 术语矩阵**（依赖 P0-2 契约升级与 P1-3 的 R13 编译消费）→ **P1-5 冲突队列窄增强** → **P1-15 统一待决队列 schema**（消费 P0-7 测量与 P1-5 领域字段；ADR 记录先行：所有权/迁移/删除语义/deletion test）→ **P1-1 跨层失效投影** → **P1-7 依赖边约定**（消费 P1-1 读模型）→ **P1-8 漂移检查器**（接通冲突队列真实生产者）→ **P1-9 社会真实度审查卡**（依赖 P0-8 回执宿主）→ **P1-6 复杂度画像与项级控制** → **P1-10/11/12/14** 低优先级薄读补丁 → **P1-13** 08-10 计划 P1 切片延续（7.5/7.7/7.9/7.10/7.12，独立轨道）。

P2 各触发条件独立成立才立项，互不阻塞。

## 8. 开放问题决议

| # | 问题 | 决议 | 落点 |
|---|---|---|---|
| 1 | 统一待决队列分歧：wiki 要求「唯一权威审查入口+P0/P1/P2 阻塞分级+最小回执模板」，08-10 计划 7.4 明确「不造统一校验队列」以运行时路由替代——维持路由方案还是做统一队列？ | **已裁定（2026-08-13）：做统一队列。** 取代 08-10 计划 7.4「不造统一校验队列」定案。落地：P0-7 投影先行切片（零迁移，立即上线并积累测量）→ P1-15 权威 schema 立项（world 模块内统一待决队列实体，细节走 ADR 记录：领域所有权、聚合数据源、迁移与删除语义；新接口做 deletion test）。 | P0-7 先行切片 → P1-15 权威 schema |
| 2 | 新 schema 门槛：术语注册表/规则触发引擎/R 门台账均属计划 §4.2 禁止未证明即建的新结构——真名回响单项目证据是否算触发条件（≥3 真实项目门槛）？能否先以现有 JSON 字段薄读模型试点？ | 有推荐：单项目证据不算触发条件。先以现有 JSON 字段薄读模型试点：RuleProfile 加 typed rule_entry 约定（P0-4）、aliases 加语义角色约定（P0-2）、CreationSuggestion/ConflictCheckQueueItem 窄可选字段（P1-5）；P2 立项须 ≥3 真实项目或 8.2 五条门槛同时成立＋ADR。 | — |
| 3 | 专有方法论 vs 通用产品：三层术语矩阵/canon_diff/六面审查属真名回响专有形态，产品应抽象到通用层（per-project 术语表/变更记录模板）还是仅作为该项目 World Bible 内容、不建 schema？ | 有推荐：抽象到通用层：per-project 术语表以 aliases/RuleProfile 薄读约定承载（P0-2/P1-4）、变更记录以固定模板＋回执承载（P0-8）、审查维度以审查卡 Prompt 承载（P1-9）；不复制 Vault 专有目录结构为产品 schema，专有内容由作者作为 World Bible 内容自建。 | — |
| 4 | Vault 不接入摩擦：wiki 的 63 项 R-xx、140 节点依赖图、术语对照表若要进入产品只能作者手工重建——是否接受此摩擦，还是评估只读导出适配？ | 有推荐：本增强计划接受摩擦，不做只读导出适配；作者侧重建经 7.9 交接快照（P1-13）回流。仅当真实用户中 Vault 用户占比显著且重建成本成为主诉时，再评估只读导出立项（届时需用户确认）。 | — |
| 5 | RP 域隔离边界：wiki 的三层术语/角色认知上限对 RP 对话同样适用，interaction 现明确不读作者 World——是否评估受控只读注入（如术语白名单），还是维持隔离不动？ | 有推荐：维持隔离不动。三版一致排除 RP 注入；三层术语/认知上限对 RP 的受控只读注入不立项，待真实 RP 用户出现术语泄漏反馈再评估（评估时同样先走薄读白名单而非新 schema）。 | — |
| 6 | 数值置信分层落地成本：正典值/示例值/叙事工作值+量级区间语义是否值得进 core_entities 字段（低成本），还是继续自由文本+项目约定？ | 有推荐：低成本约定先行：P1-10 先以规则卡标注参数角色＋Prompt 纪律执行，回放证明工作值固化拦截率不达标再给 core_entities 加可选 value_confidence/量级区间字段（窄迁移）；不预设字段方案。 | — |
| 7 | 回放评测夹具补充：7.8 的 R01—R14 夹具是否需要补「规则触发/术语过滤/防回流」类场景断言，为 G1/G2/E1 类后续立项积累证据？ | 有推荐：补。P0-9 在 7.8 夹具体系上补 R15（规则触发与门禁）/R16（下游标脏）/R17（变更记录四段）及术语过滤、防回流断言；脱敏合成数据、CI 离线可运行，作为 P1 立项与 P2 触发判定的证据基线。 | — |

注：正文中 open_questions#N 编号与本表一致。第 1 条已于 2026-08-13 由用户裁定：做统一队列（P0-7 先行切片＋P1-15 权威 schema，取代 7.4「不造统一队列」定案）。

## 9. 第二轮需求收束：从几个灵感到可采用世界核心

### 9.1 证据边界

- 可核实证据覆盖 Vault 原始来源与裁定、ChatGPT project 同步工件、Codex rollout 摘要、长篇正文与审查回执；本地没有逐轮完整 ChatGPT 原始聊天导出，因此只能重建操作链、状态变化和失败模式，不能声称覆盖每一句对话或模型内部思维。
- `proposed` 不等于 canon；网页成果、ZIP、历史 `hot.md` 和交接摘要均是历史来源，不是当前权威。当前指针必须由版本、hash、supersedes 和 receipt 共同确定。
- 真名回响反复出现的核心摩擦不是“缺少更多生成按钮”，而是灵感过早膨胀、候选与正典混淆、跨来源 current pointer 漂移、机械门通过后仍有文学语义缺陷，以及采纳后 DB 与 Wiki 两套事实不一致。

### 9.2 首版产品边界

首版灵感生长只交付 `World Core + consistency vertical slice`，不自动生成人物、故事总纲、Scene、完整国家地理或制度史。它必须做到：

1. 接受 1—7 个短灵感 seed，为每个 seed 分配稳定 `seed_key`，保留原文、来源和 hash。
2. 每轮只推动一个作者可理解的动作：补一条成立规则、把一条因果向下贯穿、找一个失败方式、合并重复项，或标记 open/rejected；快捷动作只预填消息，不自动发送。
3. 第三个成功的作者—AI 回合只提示 checkpoint，不自动保存、不自动收束；失败、取消和迟到响应不计数。
4. 作者显式点击“保存阶段成果”才持久化不可采用的 `world_core_checkpoint.v1`；聊天默认零业务写入。
5. 作者显式点击“准备采纳预览”才创建 pending `world_adoption_package.v1`；convergence 本身继续只读。

### 9.3 唯一交接门

`ready_for_handoff` 当且仅当：

- 每个原始 `seed_key` 已映射到体验承诺、included rule、open 或 rejected，不能静默丢失；
- 有 3—7 个规则原子，每条写明 `can / cannot / cost / failure / maintenance`，不适用项可写 `N/A + 理由`；
- 规则之间不存在未解决的阻断矛盾；
- 至少一条因果纵切到达第一个真实的人类日常后果和故障后果。

纵切只覆盖实际适用环节，不强迫每个项目填满资源、设施、制度和分配层；缺少人物、国家、完整历史或地图不得阻塞交接。第三轮 checkpoint 固定输出重复/漂移项、未覆盖 seed、阻断矛盾、横向/纵向失衡和唯一推荐下一动作；它不是成熟度分，也不自动收束。

### 9.4 跨会话恢复

`world_core_checkpoint.v1` 复用 `CreationSuggestion.payload_json`，不新建表，保存：

- seed/source manifest 与 source hashes；
- 每个 seed 的 disposition 和作者 decision state；
- `round_no`、当前 action、locked/open/rejected；
- `parent_checkpoint_id` 与 checkpoint lineage。

下一会话只从决策摘要继续，不把过时助手文本当成当前事实。未显式保存前，UI 必须说明仅保证当前浏览器恢复；原始聊天全文跨设备同步、服务器创作 session 和种子库延后。

## 10. 统一采纳、Deep Import 与 World Bible

### 10.1 claim/item 级采纳包

`world_adoption_package.v1` 使用冻结的 `source_manifest + manifest_hash`。每个 canonical claim、entity、rule、relation 和 page section 分别携带：

- `item_key`；
- `source_refs(type/id/version/hash/range 或 Scene/workflow)`；
- `authority_kind = author_seed | canonical_baseline | manuscript_observation | generated_bridge`；
- authoritative baseline 与 decision disposition。

去重只合并 identity，必须追加全部来源，不能覆盖来源或自动提升权威。状态语义固定为：

- `locked`：纳入当前精确预览，确认前仍是 candidate；
- `open`：留在决策账，排除结构化写入、eligible World Bible 正文、默认关联图和生成上下文；
- `rejected`：仅作负面防回流边界，不成为正向事实；
- `adopted/canonical`：仅在 apply 全事务成功后产生。

页面发布前执行确定性 `eligible content block → included item/source` 100% 覆盖校验。任何未映射正向事实整包拒绝；open/rejected 只能进入 `projection_policy=excluded` 的作者决策区，不能借 World Bible 正文偷渡成正典。

### 10.2 原子 apply

preview 必须零写入并返回 payload/source/baseline/impact hash、对象和每个页面的完整 before/after diff、omissions。apply 只接收当前 preview hash，授权人来自当前 account principal，不接受调用方 owner。单事务内完成：

1. 重验 source/checkpoint/baseline、候选状态和页面版本；
2. 创建或提升 included 实体；
3. 解析 package-local refs 后创建关系；
4. 仅当包含完整页面提案时，经现有 draft → publish lifecycle 发布正式 World Bible revision；
5. fail-closed 标记精确 context/synopsis stale；
6. CAS 将 package 置为 accepted，写不可变 result refs、local-ref map、canon diff、来源与授权回执。

任一漂移或发布失败都整包回滚，package 保持 pending；重试必须幂等。无页面提案的包不得制造伪 World Bible revision。成功后的包级一键撤销不在首版承诺内，仍使用现有逐资产历史；若未来需要包级 rollback，必须单独立项 CAS 协调器。

### 10.3 Deep Import 对接

Deep Import 保留现有 upfront `user_authorized_pipeline`、Phase 2 持久化、checkpoint/resume/rollback 和 asset summary 语义，不把整个 Phase 2 延迟到二次确认。工作流完成后通过 world 稳定 facade 组装 post-import package：

- 已自动合并或已采用资产写成 `existing_ref/no-op`，只进入“本流水线已写入”栏；
- candidate 使用 expected status/hash，进入本次待确认栏；
- 尚未采用的关系、补充 claim 与 World Bible 页面 revision 进入 pending writes；
- alias 若首版 package 不支持，继续走现有 alias review，不伪装为已完成；
- 同一实体来自作者 seed 与正文 Scene 时只保留一个实体，但保留两条独立 source refs 和 authority。

预览必须分栏显示“流水线已写入”与“本次确认将写入”，apply 不得二次创建对象。若未来改为 Phase 2 全部延迟确认，必须作为破坏性重构同步 checkpoint、resume、rollback、asset summary、API、前端与迁移，不得藏在 facade 复用中。

### 10.4 World Bible 关联图边界

用户目标是让现有 World Bible 提供类似 Obsidian 日常导航的关系网能力，不复制完整 Vault 工程。首版名称固定为“关联图”：

- node：canonical/confirmed World Bible page 与 canonical CoreEntity；
- edge.kind：`page_reference | page_entity_reference | entity_relation`；
- 默认仅 adopted，pending 必须显式开启并视觉区隔；
- 每条边显示 status/authority、source TargetRef/revision/hash 和 provenance receipt 摘要；
- 引用或实体关系不得推断 `depends_on/invalidates`，无显式依赖合同时显示“依赖影响未覆盖”。

局部默认 1 hop，可显式扩到 2 hop，服务端硬上限 120 nodes/240 edges；全局检索上限 500/1500，但单次 SVG 仍按局部预算聚合/下钻。返回 deterministic order、truncated、truncation reasons、omitted counts 和 source manifest。页面反向引用扫描超过 2000 个 adopted pages 时明确 partial。390px 默认等价列表优先，图只是辅助视图；不新增图数据库或布局依赖。

## 11. 世界核心之后的完整创作链

### 11.1 工件谱系与失效

唯一主链为：`World/World Bible → Character → StoryOutline revision → story_execution_profile.v1 → Scene execution_contract → prose candidate → independent review → targeted revision → adopted prose`。

- 每个下游候选和审查工件保存 `upstream_manifest(type/id/version/hash)`；打开和采用时重算，漂移显示 needs_review，采用 fail-closed 409。
- 各资产 owner 使用真实 `TargetRef(type/id)` 调 context invalidation；不得用泛 `worldbuilding` ID 代替。
- 首版先做 stale confirmation/result refs 的精确读模型，不修改 Outline/Writing 自身状态、不建依赖表；缺少历史 provenance 的资产明确列为 omission。
- `story_execution_profile.v1` 由 StoryOutline revision 持有，可用不可变 task result + hash 引用实现；人物声音、连续性和叙事约束属于 story layer，禁止复用 World Bible canonical page 承载。

### 11.2 Scene 执行与独立审查

每个 Scene contract 至少编译 POV、知识边界、entry/exit、outcome/cost、must_not_happen、continuity 和 new fact candidates。正文生成与审查必须是两个不同 managed step/run：

- reviewer 冻结 StoryOutline、Scene contracts、story execution profile 和正文 hash manifest；generator 自检不能作为独立通过证据；
- 除逐 Scene 检查外，增加卷/全书只读语义审查，输出 coverage、finding_id、severity、location、contract refs、preserve 与 not_checked；
- 机械/MCP 门只签结构、计数、残留和重复度等表面信号，不能签文学 PASS；
- 返修 candidate 必须绑定 finding_ids、base draft/hash、contract/profile hash、允许范围、preserve/must_not_change 与 supersedes，不覆盖原稿；
- 采用返修后重检目标 finding、相邻 Scene 和全书关键不变量。

## 12. 修订后的实施波次与验收

### 12.1 波次

| 波次 | 交付 | 稳定面与风险 | 完成定义 |
|---|---|---|---|
| W0 当前真相对齐 | Scene memory 固定四维；删除 context 伪 map 缺口 | memory contract、context fingerprint；无 DB/API 变化 | memory/context 全量回归通过，旧 map checkpoint 被忽略 |
| W1 采纳内核 | checkpoint/package typed payload、preview/CAS/apply、DB+可选 World Bible revision 原子发布 | world API/Pydantic；无新表；owner/novel 与事务风险最高 | baseline 漂移、claim 覆盖、发布失败回滚、local ref、幂等 E2E 全绿 |
| W2 灵感生长 UX | Generate `preset=world_core`、Today 入口、三回合 checkpoint、保存/恢复、完整采纳 diff | 前端 wire 与本地存储；不新增工作台 | 3 seed 修正/否定/恢复/handoff/390px E2E |
| W3 Deep Import 吸取 | post-import package facade、existing/no-op 与 pending 分栏 | imports→world 稳定 contract；不得改变 Phase 2 恢复语义 | asset summary/rollback 不回归，不重复建对象，来源可回跳 |
| W4 World Bible 关联图 | 1/2 hop 后端读模型、SVG 辅助视图、等价列表 | world read API；无图数据库、无依赖语义 | 三类边、反向/环/截断/隔离/390px E2E |
| W5 下游可证链 | exact stale refs、outline-owned execution profile、Scene contracts | outline/context/writing 跨模块稳定 seam | 上游漂移后仅受影响候选 needs_review，采用 409 |
| W6 独立审查返修 | 独立 managed review、卷/全书检查、finding-bound revision | task/result 与 writing candidate；无专用 campaign 表 | 机械可过但含 POV/合同缺陷的稿件被拦截，定向修复后回归通过 |

W0/W1 是其余波次的前置；W2 与 W4 可在稳定 contract 后并行；W3 在 W1 后；W5/W6 在 W2 的 package handoff 稳定后。每个波次在独立 worktree/主题分支实现，由主会话 Review 后才进入集成分支。

### 12.2 必须保留的 E2E

1. **核心生长**：输入 3 个 seed；第二轮修正一个、第三轮否定一个；checkpoint 后换会话恢复。handoff 中 3 个 seed 全有 disposition，否定项不复活，规则无阻断矛盾，有一条日常+故障纵切；未补国家/人物仍可交接。
2. **状态与原子采纳**：included/open/rejected 各一项；open/rejected 不进入 DB writes、eligible page、默认图或生成上下文。任一 baseline 变化后 apply 409，DB/page/receipt 无部分写入。
3. **来源**：同一实体来自作者 seed 与 Deep Import Scene；去重后仍保留两条 source refs/authority，generated_bridge 不能冒充 manuscript evidence。
4. **Deep Import**：现有 asset summary、checkpoint、rollback/recovery 不变；post-import package 分栏，apply 不重复创建对象，剩余 DB 写入与 World Bible revision 同事务。
5. **关联图**：覆盖 page→page、page→entity、entity→entity、反向引用、环、坏 ref、截断、adopted 默认、pending 显式、owner/novel 隔离和 390px 列表；响应无伪造 dependency edge。
6. **审查返修**：机械门可通过但含 POV 越界/合同漏项的多 Scene 稿必须产生定位明确的 finding；返修不覆盖正文；来源漂移 409；采用后目标 finding 关闭且相邻 Scene/关键不变量回归通过。

### 12.3 分支实施状态（不代表 `main` 已上线）

| 能力 | 集成分支状态 | 说明 |
|---|---|---|
| W0 Scene memory 四维 | 已完成、待合并 | 单一稳定常量，memory/context 定向回归通过 |
| W1 typed checkpoint/package 与实体/关系原子采用 | 已完成、待合并 | 复用 CreationSuggestion，无迁移 |
| W1 package → World Bible revision | 已完成、待合并 | 完整页面 diff、claim 覆盖、replace CAS、发布失败整包回滚 |
| W2—W6 | 未完成 | 必须按上表继续实现和主审；不得把计划态写成当前能力 |
