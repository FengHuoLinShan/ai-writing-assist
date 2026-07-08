# CONTEXT.md — AI 长篇小说结构化创作引擎 v2.0

领域术语表、概念关系图、状态流转。保持本文与 `docs/agents/domain.md` 一致。

## 1. 核心产物（Core Products）

系统产生结构化创作资产，而非直接生成完整正文。

| 中文概念 | 英文 | 数据表 | 职责 |
|---------|------|--------|------|
| 核心实体 | CoreEntity | `core_entities` + 类型扩展表 | 世界对象身份主表。`entity_type` 区分 **character** / location / faction / item / event / rule / power_system / species / group / secret / legend / resource / concept / creature / skill / other。`species` 表达种族/物种/血脉，`group` 表达阶层/职业/社会群体；各主要类型通过 1:1 扩展表保存高频结构化字段，CoreEntity 保存统一身份、名称、摘要、别名、状态和 provenance |
| 实体档案模板 | EntityProfileTemplate | `entity_profile_templates` | 定义某个 CoreEntity 类型的档案字段 schema、展示规则、校验规则、上下文投影和迁移规则。第一版用于 generic profile 和强表 profile 共用模板，不等同于 World Bible Page Template |
| 通用实体档案 | GenericEntityProfile | `generic_entity_profiles` | 尚未拆出独立强表的 CoreEntity 类型档案承载层，以 entity_id 1:1 绑定 CoreEntity，并按 EntityProfileTemplate 校验 `data_json` / `extra_json`。用于 power_system、resource、legend、concept、creature、skill 等后续类型的完整可用占位 |
| 目标引用 | TargetRef | 跨模块 contract | 可见性、冲突检查、投影、知识标签和建议队列共用的世界事实寻址对象，统一由 `target_type`、`target_id`、`target_path` 三段组成。传输层使用 JSON 对象，数据库层可物化三列以便索引；不再使用 `background_group` 等临时寻址词 |
| 人物 | Character | `characters` | `entity_id` FK→CoreEntity。存人物特有字段（role, personality, desire, fear, secret, weakness, stance, voice_style 等） |
| 人物知识 | CharacterKnowledge | `character_knowledge` | 某角色对某事物的了解程度（unknown / rumor / partial / full / restricted / false_belief / misunderstood）。它是稀疏 per-character 覆盖记录，不为每个角色和每个世界对象预建矩阵 |
| 知识标签 | KnowledgeTag | `knowledge_tags` / `character_knowledge_tags` / `asset_knowledge_tags` | 压缩“角色 × 事实”可见性矩阵的知情者标签，例如某势力成员、某种族、本地居民、亲历某事件、读过某书。第一版执行 derived / manual / confirmed_suggestion：系统自动推导公共身份，作者维护叙事专属标签，AI 只提出待确认建议；triggered 事件触发标签先作为草案/预览预留 |
| 知识标签授予来源 | KnowledgeTagGrantProvenance | `character_knowledge_tags` | 角色获得某个 KnowledgeTag 的来源追踪。记录 grant_source、source_ref_type、source_ref_id、source_scene_id、source_chapter_index 和 author_locked，用于 Scene 重写/删除/回滚时提示哪些衍生标签可能失效；第一版只提示和允许锁定，第二版才自动回滚未锁定授予 |
| 知识标签排除 | KnowledgeTagExclusion | `knowledge_tag_exclusions` | 作者对自动派生标签的持久否定意图。同步任务重新计算 species、faction、home location 等 derived 标签时，必须先扣除该表记录；删除 exclusion 后，下次同步可重新授予对应标签 |
| 知识可见性策略 | KnowledgeVisibilityPolicy | `knowledge_visibility_policies` | 世界事实片段的可见性策略，分 public / tag / private 三个第一版执行层；rule 作为草案/预览预留。public 不写 per-character；tag 用 KnowledgeTag；private 只用于极少数个人秘密 |
| 读者揭示信息 | ReaderRevealInfo | TargetRef metadata / projection metadata | 某个 TargetRef 或投影片段首次对真实读者揭示的位置，包含 reveal_status、reveal_chapter_index、reveal_scene_id、reveal_plan_id。它控制叙事信息释放节奏，不等同于角色是否知道 |
| 读者进度 | ReaderProgress | context compile option | 当前读者或预览视角的阅读进度，至少包含 effective_chapter_index，可选 scene_id / reveal_plan_id。读者向摘要、回顾、旁白和 AI 辅助问答必须用它过滤剧透 |
| 读者安全 | ReaderSafe | computed result | 运行时由 ReaderRevealInfo + ReaderProgress 计算出的布尔结果，不作为全局静态字段存储。未配置揭示点或状态为 unrevealed 的目标默认不对读者安全，除非它被显式标为 public baseline |
| 知识继承 | KnowledgeImplication | `knowledge_implications` | 事实之间的可见性继承或蕴含关系，例如知道 A 的角色默认知道 B。第一版只存储和预览，不参与正式权限判决；后续启用时必须可解释、可追踪来源，并在冲突时采用更保守可见性 |
| 知识范围规则 | KnowledgeScopeRule | `knowledge_tags` / `entity_relations` / `knowledge_visibility_policies` | 角色数量爆炸时的知识继承规则。第一版以 derived/manual KnowledgeTag 为主；rule/trigger 仅作为草案预留。公共可见不写 per-character；只有 POV、主角、关键误解、秘密知情人和偏离群体默认值的情况才写 CharacterKnowledge |
| 剧情线 | PlotThread | `plot_threads` | 主线/支线/隐藏线/关系线/反派线/伏笔线。含起止章节、表层目标、隐藏真相、读者/作者已知状态 |
| 篇章纲 | OutlineArc | `outline_arcs` | 小说卷/篇章结构。含 arc_goal, core_conflict, entry_hook, midpoint_turn, climax, result, next_hook |
| 章节卡 | ChapterCard | `chapter_cards` | 单章的 goal, main_conflict, emotional_point, plot_function, must_happen / must_not_happen |
| 场景卡 | Scene | `scenes` | 最小叙事单元。旧 `chapter_cards.scene_cards` JSONB 仅作历史兼容/冗余上下文，不是当前权威来源 |
| 伏笔计划 | ForeshadowingPlan | `foreshadowing_plans` | 埋点→加强→收束 三阶段。含 surface_meaning, hidden_meaning |
| 揭示计划 | RevealPlan | `reveal_plans` | 秘密的分阶段揭示。含 target 和 reveal_stages |
| 长期记忆 | Memory | `memory_events` / `memory_snapshots` / `delta_log` | 章节事件、时间性快照和结构化字段差分。memory 拥有 temporal delta/snapshot 与 delta ingestion；world 拥有 canonical state assembly |
| 正文草稿 | WritingDraft | `writing_drafts` | 人工写作的章节正文。支持 version_number 递增的多版本管理 |
| RAG 分块 | RagChunk | `rag_chunks` | 正文分块 + embedding 向量 + 元信息标注（entity_ids, character_ids, thread_ids） |
| 事件 | Event | `core_entities` (entity_type="event") | 小说时间线事件。timeline_order 存于 content_json |
| 导入记录 | ImportRecord | `import_records` | 小说文件导入跟踪。不存原文 |
| 候选创作资产 | Candidate Creative Asset | 多表状态表达 | AI 或系统从正文中提取出的、具备长期维护价值但尚未被用户确认的结构化资产。可对应 CoreEntity、Relation、Alias、Event、Scene、PlotThread 等对象；默认进入 candidate 或等价待确认状态，可进入工作上下文但不进入正史上下文 |
| 世界对象草稿 | World Object Draft | `core_entities` / profile / suggestion queues | 作者通过生成中心或 World Bible AI 入口主动创建的非正史世界对象工作稿。第一版用户界面不区分“草稿”和“候选对象”；若草稿来自页面正文、章节证据或导入结果，必须用来源标记提示作者其依据和复核风险 |
| 导入写入风险分级 | Import Write Risk Classifier | imports workflow / suggestion queues | 深度导入写库前的风险分类边界。低风险事实轮廓可写 draft/candidate；公共可推导标签可在严格条件下自动同步；KnowledgeVisibilityPolicy、叙事专属 KnowledgeTag、CharacterKnowledge 等知识连接默认只进导入审核建议，作者确认前不写正式知识表 |
| ~~候选实体~~ | ~~EntityCandidate~~ | ~~`entity_candidates`~~ | 已废弃。候选对象不再使用独立候选表，改由对应资产表的状态与自动入库元数据表达 |
| 关系 | EntityRelation | `entity_relations` | 实体间关系（人物、势力、对象、通用）。source_id/target_id 为 UUID hex 字符串 |
| 修订快照 | EntityRevision | `entity_revisions` | CoreEntity 的编辑历史快照，支持 rollback |
| 世界观手册 | World Bible | `core_entities` / `entity_relations` / `map_*` / `context_*` | 作者开书前和创作过程中维护世界观的百科/指引手册式产品入口，采用固定核心册页 + 可扩展自定义册页。固定册页包括世界基本背景、种族/群体、势力、地点/地图、历史重大事件、规则体系、重要物品、主要人物、秘密与伏笔；自定义册页服务修仙境界、科幻技术树、神系/位面/怪物图鉴等类型化设定。它不是独立世界观数据库，而是把世界对象、关系、地图事实、人物知识边界和上下文激活规则组织成作者可浏览、可补全、可预览 AI 参考资料的手册 |
| 事实所有权模型 | Fact Ownership Model | 跨模块 contract | 同一个世界事实只能有一个权威归属。世界对象事实属于 CoreEntity、类型 profile 强字段、profile `extra_json`、EntityRelation、地图事实、人物知识边界或结构资产；World Bible Page 只组织、引用和解释这些事实；projection 只是缓存；正文草稿是读者面向艺术呈现，不回写设定真相 |
| 世界观手册页 | World Bible Page | `world_bible_pages` | World Bible 中的一个作者可编辑页面，承载页面标题、页面元数据、自由正文、关联资产引用和激活默认规则。作者确认保存即视为发布当前手册页内容；它保存作者的手册正文和页面组织方式，但不拥有结构化正史事实 |
| 手册页保存点 | World Bible Page Save Point | `world_bible_page_revisions` | World Bible Page 在作者确认保存、应用 AI 整理建议或回滚等有意义节点形成的轻量历史点。第一版不维护“未发布修改”层；回滚通过创建新的保存点完成，不删除旧历史 |
| 实体手册扩展页 | Entity Bible Extension Page | `world_bible_pages` | 绑定单个 CoreEntity 的可选 World Bible Page，只在作者为该实体额外撰写百科正文、创作手册正文或特殊模板字段时创建。普通实体详情页默认由 CoreEntity、关系、地图事实和人物知识边界动态渲染，不为每个实体自动创建空手册页 |
| 世界观手册页模板 | World Bible Page Template | 代码注册表 / `world_bible_page_templates` | 定义 World Bible Page 的页面元数据字段、展示规则、上下文投影、冲突检查提示和默认激活规则。`world_bible_pages` 只保存 `template_key`、`template_version` 和 `page_meta_json`；内置固定册页模板由代码注册表提供，自定义册页模板后续持久化到模板表 |
| 世界观手册页结构 | World Bible Page Structure | World Bible | 每个固定册页和自定义册页的作者编辑结构，由页面元数据、自由正文、关联资产/激活规则三层组成。页面元数据服务展示顺序、关联故事线、写作状态和组织方式；自由正文服务作者表达手册式叙述；关联资产把页面连接到实体、关系、地图事实、历史事件、人物知识边界和 AI 参考资料激活规则 |
| 自由正文投影 | Free Text Projection | `world_bible_page_projections` | World Bible Page 的 `free_text` 进入 AI 参考资料前形成的派生上下文材料。它可以是短文本摘录、模板化摘要、风格/文化要点或事实候选摘要，带 source page、source spans、token 估算、裁剪原因和不确定性；可持久化缓存并按 `free_text_hash` 失效重建，但不是结构化正史事实 |
| 世界书 AI 生成入口 | World Bible AI Generation Entry | Generate Center / World Bible | World Bible 页面内复用生成中心交互的上下文化入口。它不限定用户生成的设定内容，只限定输出目标：仅聊天、写入当前页、新建手册页、生成世界对象草稿、生成 profile/关系/地图观察/揭示策略等创设建议 |
| 手册页整理任务 | Page Organization Task | `async_tasks` / suggestion queues | 针对单个 World Bible Page 的受控 AI 整理流程，参考深度导入的 workflow_id、phase timeline、quality stats 和 phase artifacts。它读取页面元数据、自由正文、关联资产和 projection，产出页面元数据补全建议、profile/实体/关系/地图事实建议、冲突检查项和 projection 诊断；结果进入建议队列或冲突队列，作者确认前不写正史 |
| 单页整理边界 | Single Page Organization Scope | Page Organization Task | `整理此页` 的默认执行边界。任务只整理当前 World Bible Page；关联实体、地图、关系和其他手册页只作为只读上下文，不被递归整理或自动改写。若发现关联页面也需要整理，只生成后续任务建议 |
| 整理结果确认分组 | Organization Result Review Groups | Page Organization Task | `整理此页` 的结果审查分组。页面元数据补全建议、profile/新对象/关系/地图事实建议、冲突/叙事风险、后续任务建议分开确认；低风险的当前页元数据补全不和高风险正史资产写入混在同一个确认动作里 |
| 世界观资产卡片视图 | World Bible Asset Card View | World Bible | World Bible 中以卡片形式浏览和编辑世界对象的 UI 视图，不是新的对象类型或数据表。人物、种族/群体、势力、地点、重要物品、历史事件、规则体系、秘密、资源等世界对象优先复用 CoreEntity，通过 entity_type、类型扩展表、标签、profile 字段和关系区分；手册页负责把这些资产组织成百科/指引体验 |
| 世界核心简报 | World Core Brief | `world` / `context` | 世界基本背景页进入 AI 参考资料时的 P0 短版，而不是完整百科页。它只保留世界一句话、时代/文明阶段、核心规则边界、叙事禁区、核心矛盾和作者硬约束等必须常驻的短事实；完整世界基本背景页仍面向作者浏览和维护，详细段落按关键词、任务、地图焦点、Scene 证据或显式选择进入上下文 |
| 世界设定工作台 | Worldbuilding Workspace | `core_entities` / `entity_relations` / `map_*` / `context_*` | 维护 World Bible 的工作台能力集合，包括手册浏览、对象编辑、地图联动、创设建议、冲突检查、AI 参考资料预览和深度导入消费。它不是独立世界观数据库，而是面向 CoreEntity、关系、地图事实和 AI 参考资料激活规则的统一操作入口 |
| 世界背景聚合 | WorldBackgroundAggregation | `world` / `context` | 面向长篇小说的世界设定背景聚合层，把世界对象、关系、势力/地点/规则、历史事件、重要物品、地图事实、人物知识边界和结构资产整理成可被 AI 参考资料激活和冲突检查消费的分层摘要。它不是简单实体列表，也不由 imports 拥有；世界设定工作台负责维护和预览，context 模块负责按 `ContextActivationRule` 编译进 AI 参考资料，深度导入通过 context facade 消费它来改善 Phase 2/3 |
| 上下文激活规则 | ContextActivationRule | `context_activation_rules` | 描述某个重要世界对象、规则或地图事实在什么任务、Scene、人物、地点、地图焦点或关键词下应进入 AI 参考资料。激活规则只决定上下文选择和解释，不改变对象本身的正史状态 |
| 导入上下文激活 | ImportContextActivation | 跨模块概念 | 深度导入中每个 LLM 步骤运行前的确定性上下文预检。它以当前 Scene 为主证据，完整保留当前 Scene 覆盖的 `scene_chunks` 正文；Phase 2 Scene-local 抽取默认只读取前序 `NeighborSceneBrief`，只在共享实体、地点、关系、伏笔、地图焦点或跨章延续等强证据命中时读取前序局部原文，不把后续 Scene 放入当前 Scene 上下文，避免剧透污染。`NeighborSceneBrief` 由 deep import workflow 基于稳定接口和已落库资产生成，默认只进入任务结果、phase artifacts 或 context snapshot metadata，不作为长期正史表。它基于 Scene、章节范围、地图焦点、已知世界对象、关系、结构资产、关键词和递归激活规则选择 `ContextSection`，记录 activation_reason、sources、token 占比和裁剪原因；它不直接生成事实、不写正史，也不替代 Pydantic schema 校验 |
| 深度导入上下文接入 | Deep Import Context Integration | 跨模块概念 | 深度导入对世界观和上下文模块的消费方式。交付顺序是先在 world/context 中形成世界观聚合、激活规则和可审计 `ContextSection`，再由 imports 通过 context facade 获取这些 section 支持 Phase 2/3；imports 不拥有世界观聚合，不直接读取 world/context 内部 repository/service，也不复制一套临时世界观系统 |
| 创设建议队列 | CreationSuggestionQueue | `creation_suggestion_queue` | LLM 对世界设定提出的新对象、补全、关系、地图候选、揭示策略或规则建议集合。World Bible AI 生成入口默认把会改变结构化资产的结果放入该队列；作者确认前不写入对应事实表 |
| 冲突检查队列 | ConflictCheckQueue | 待建队列表 | LLM 或确定性检查发现的设定矛盾与叙事风险集合。队列项按事实冲突和叙事风险分级，作者确认处理后才修改正史或地图事实 |
| 事实冲突 | FactConflict | 冲突检查队列 | 与已确认正史、时间线、人物知识边界或地图事实直接矛盾的问题。事实冲突需要修正、改写、废弃候选或显式解释 |
| 叙事风险 | NarrativeRisk | 冲突检查队列 | 不一定违反正史、但可能削弱故事张力、重复设定、提前泄露秘密或破坏规则边界的风险提示。叙事风险默认非阻断，由作者决定是否采纳 |
| 空间连续性地图 | Spatial Continuity Map | `map_*` | 写作伴随的空间连续性工具，用于表达 Scene 中地点、人物/事件位置、势力范围和相邻 Scene 的移动合理性。它是作者校对空间事实的辅助资产，不是自动推演、战棋模拟或地图美术系统 |
| Scene 级空间连续性 | Scene Spatial Continuity | `scenes` + `map_*` | 单个 Scene 及其相邻 Scene 之间的空间事实一致性，包括主地点、在场人物/事件、所属势力范围和移动跳变是否合理。第一版只提供轻提示，不阻断写作、发布或 AI 生成；它优先服务写作时的事实校对，不替代剧情因果、时间线或路线规划 |
| 空间连续性提示 | Spatial Continuity Hint | `scenes` + `map_*` | 面向作者的非阻断提示，用于指出 Scene 空间事实缺失或可疑跳变。第一版只基于结构化地图事实，不读正文、不调用 LLM、不推断未记录位置；只覆盖缺少主地点、缺少地图上下文和人物跨地图；主入口在写作页 Scene 面板，地图页用于展开查看和修正 |
| 类型化地图观察 | Typed Map Observation | `map_observations` | 带明确动态类型、时间锚点、空间锚点、证据和审查状态的地图候选事实。它可以表达人物移动、事件发生地、路线阻隔、势力范围、资源控制、地形变化、危机扩散或语义关联；确认前不改变正式地图事实 |
| 地图事实 | Map Fact | `map_facts` | 作者确认后的时间化地图事实。它是地图动态、写作空间连续性提示和世界观手册地图联动的可信来源；被回滚或废弃时保留历史状态，不硬删除业务事实 |
| 地图待处理队列 | Map Review Queue | `map_observations` + 派生视图 | 作者审查地图候选、冲突和缺失锚点的工作队列。它按对象、时间、风险、置信度和来源组织待确认事项，不拥有正史事实，也不替代地图事实本身 |
| 地图轨道 | Map Track | `map_facts` / `map_observations` 派生 | 按叙事时间组织的一类地图动态视图，例如人物旅程、事件顺序、势力边界变化、危机扩散、资源控制或地形变化。轨道是可视化和复核方式，不是新的事实来源 |
| 证据锚点 | Evidence Anchor | 跨模块 contract | 支撑候选事实、地图事实、冲突检查和上下文片段的可追溯来源引用。它可以指向 Scene、章节片段、RAG chunk、context snapshot 或导入 workflow 产物；它证明“这条结论从哪里来”，但自身不是正史事实 |
| 创作工作流 Agent | Creative Workflow Agent | 跨模块概念 | 面向长篇小说创作任务的受控 AI 执行层。它不是通用自治多 Agent 平台；agent 化的目的不是追求自由自治，而是借鉴 Claude Code 关于工具调用、上下文超限、schema 容错、任务恢复和可验证执行的工程处理方式。它围绕创作工作流提供工具注册、权限门、上下文/记忆管理和可验证任务循环，多 Agent 只作为受控的内部执行策略。第一阶段服务系统内部长流程任务，如深度导入、Scene 整理、世界对象抽取、剧情结构分析和写作前上下文准备；用户看到任务计划、权限确认、进度、证据和可回滚结果，而不是泛用自由对话 agent。默认只能写入 draft / candidate / pending 等待确认资产；canonical 必须由用户确认后产生。Agent 工具只能通过现有模块稳定接口、service 编排入口或明确 DI port 执行业务动作，不直接暴露底层数据库、任意文件系统或任意代码执行 |
| Agent Harness | Agent Harness | 跨模块概念 | 支撑创作工作流 Agent 的横切执行底座，不是新的用户可见创作资产。第一阶段优先覆盖工具调用协议、上下文管理、LLM 输出容错和任务循环可观测性；目标是让现有深度导入、Scene 整理、世界对象抽取和结构分析更稳定、更可恢复、更可验证，而不是先增加新 UI 或新多 Agent 协调器。第一阶段以 imports 深度导入作为试验场，第一条竖切线是 Phase 0/1 Scene 提取；第一版代码应留在 `backend/modules/imports/` 内部（如 `managed_llm_step.py` 或 `agent_step_harness.py`），不先创建 `modules/agent`。在真实 LLM 长流程中验证 harness pattern 且 Phase 0/1、Phase 2 形成稳定复用后，再决定是否抽到共享 `backend/infrastructure/agent/` |
| LLM 供应商配置 | LLM Provider Profile | `projects.settings["llm"]` | 项目级 LLM 供应商配置，采用 OpenAI-compatible 形状表达 api_key、base_url、model 和常用生成参数。系统提供国内外供应商模板用于预填，包括 DeepSeek、Kimi、通义千问/阿里云百炼、智谱、百川、MiniMax、腾讯混元、百度千帆、阶跃星辰、零一万物、硅基流动、火山方舟和自定义 OpenAI-compatible 网关；模板只是可编辑默认值，用户选择后仍可调整 Base URL、模型、timeout、max_tokens、temperature、top_p 和供应商扩展 JSON。Agent Harness 不硬编码供应商。业务 LLM 调用以项目级配置为权威来源；环境变量只作为未配置项目的 fallback、本机开发和真实 LLM 验收 override。每次长流程运行应记录脱敏后的 effective provider/model/host/timeout/参数摘要和字段来源（project/env/test_override/default） |
| LLM Step Harness | LLM Step Harness | 跨模块概念 | Agent Harness 第一阶段的最小交付物，用于包住现有 Phase 0 / Phase 1a / Phase 1b LLM 调用，而不是重写深度导入 workflow 编排。它统一处理输入上下文预算、LLM timeout / retry / total watchdog、schema validate / repair / degraded fallback、step 级 JSONL / timeline / checkpoint 诊断，以及 step 的只读/写入、权限级别和可重跑粒度定义。Phase 0/1 的上下文超限治理采用五层链路：step input budget、tool/context result budget、snip、microcompact/collapse、autocompact fallback；任何裁剪或压缩都必须写入 degraded diagnostics，且压缩摘要只作为 working context，不产生正史事实 |
| LLM Compact Step | LLM Compact Step | 跨模块概念 | 受控 LLM 上下文压缩步骤，工作方式参考 Codex 式上下文 compact：先由代码完成分层预算、优先级排序、去重、snip 和 deterministic collapse；只有仍超预算或资料过碎时才调用 LLM，把一组有来源的 Scene brief、世界背景聚合片段或证据 snippet 压缩成短摘要。compact 输出必须保留 source ids、coverage、omitted_reason、token_before/after 和 uncertainty，不允许新增事实、改写事实状态或产生正史；它只作为后续 LLM step 的 working context，并进入 snapshot metadata / phase artifacts |
| 受控 LLM 步骤 | Managed LLM Step | 跨模块概念 | 介于主创作工作流 Agent 和普通工具调用之间的确定性 LLM 执行单元，适用于 Phase 0 / Phase 1a / Phase 1b。它比普通 tool call 更重，包含 prompt 构造、上下文预算、LLM 调用、schema 守门、retry、degraded fallback 和 journal；但比 subagent 更轻，不自主规划、不选择下一步、不长期持有记忆、不递归启动 agent、不拥有 workflow。主 orchestrator 仍负责调度、并发、合并、降级和写库 |
| 两段式并发提取 | Two-Stage Concurrent Extraction | 跨模块概念 | 深度导入 Phase 2 的目标执行语义：先基于 `ImportContextActivation` 为每个 Scene 独立准备可审计上下文，再按 Scene 并发执行 LLM 抽取；随后按 `scene_index` 顺序串行提交写库、去重、实体融合、关系 create-or-merge、checkpoint 和 memory snapshot。它用显式上下文预检替代 batch 内隐式 rolling context，保留写库顺序和可恢复性。后续 Scene 证据只允许在别名融合、实体去重、关系对账、跨章连续性评分、Phase 3 结构总览和伏笔回收链路识别等全局对账步骤使用，并标记为 `future_evidence`；它不能回写成当前 Scene 的角色知识、读者已知状态、当章事实或 delta 发生时间。若全局对账发现前文漏抽重要对象，只能创建补抽建议或触发前文 Scene rerun，rerun 仍必须只使用该前文 Scene 当时可见的上下文 |
| 自适应并发窗口 | Adaptive Concurrency Window | 跨模块概念 | 深度导入 LLM 抽取阶段的并发控制语义。官方高并发模型默认从 64 个 Scene 并发起步，并根据 provider profile、错误率、超时率、格式失败率、repair 次数和本地写库积压动态收缩或恢复；opencode 等可能限流的兼容网关使用保守默认，并在前端提示建议使用官方 DeepSeek-v4-flash。任务结果应记录 effective concurrency、throttle reason 和降级统计 |
| 深度导入质量门禁 | Deep Import Quality Gate | 跨模块概念 | 深度导入阶段完成后的质量检查语义，不只检查数量，也检查 Scene 覆盖率、实体/关系重复率、跨章连续性、格式修复率、fallback 比例、结构资产引用完整性和剧情线/篇章纲是否真实关联 Scene 或实体。被质量门禁标记的 Scene、batch 或结构资产会自动进入最多一轮受控 rerun；rerun 仍未通过时标记 degraded，记录原因和可复跑范围，不静默通过 |
| Step/Tool Envelope | Step/Tool Envelope | 跨模块概念 | Agent Harness 对单个确定性执行单元的统一描述和结果包，借鉴 Claude Code 的 `ToolDef` / ToolStart / ToolEnd 思路，但第一阶段不让 LLM 自主选择下一步。每个 envelope 至少声明 name、input_schema、output_schema、permission_level、read_only、concurrent_safe、timeout、retry_policy、context_budget 和 output_guard；每次执行记录 call_id、started_at、elapsed_ms、attempts、input_hash、output_hash、token_budget、error_kind、degraded_reason 和 quality_stats。Phase 0/1 的 `phase0_prefetch`、`phase1a_reinforce`、`phase1b_fusion` 是 Managed LLM Step；Workflow Read、Novel Text Search / Read 是只读工具。二者都应逐步收敛到该 envelope；workflow 顺序暂时仍由现有 orchestrator 决定 |
| Agent Run Journal | Agent Run Journal | 跨模块概念 | 创作工作流 Agent 的追加式运行日志，用于把 Step/Tool Envelope 的关键执行事件持续落盘，借鉴 Claude Code 先写 transcript 再进入长模型请求的恢复思路。第一版不新增数据库表，复用 async task result、phase_timeline、checkpoints、quality_stats 和真实 LLM JSONL；每条事件记录 workflow_id、run_id、call_id、envelope_name、phase、event_type、started_at、elapsed_ms、attempts、input_hash、output_hash、error_kind、degraded_reason、checkpoint_ref 和 quality_stats。它只服务诊断、恢复、验收和调参，不作为用户创作资产；待 Phase 0/1 真实 60 章稳定后，再决定是否沉淀为正式表 |
| Step 输出守门 | Step Output Guard | 跨模块概念 | LLM Step Harness 对每个 LLM step 输出的确定性守门层，参考 Claude Code 的工具 schema / 结果 envelope 思路，但面向本项目的 Pydantic 业务 schema。它先做严格 schema 校验，并只允许确定安全的轻量归一化（如缺失列表归一为空列表、兼容字段别名）；解析失败或 schema 失败时最多进行 1 次有边界的 repair，repair 输入包含原始输出、目标 schema 摘要和校验错误；repair 后仍失败则记录 raw output hash、schema_errors、repair_attempts、error_kind、degraded_reason，并回退为可审计的空结果、上一阶段候选或局部 fallback。Step 输出守门不得把未通过 schema 的内容写入 canonical，也不得无限重试或静默吞错 |
| Workflow Read Tool | Workflow Read Tool | 跨模块概念 | 创作工作流 Agent 的只读内部工具，用于读取 workflow 状态、task result、checkpoint、phase timeline、quality stats、phase errors 和诊断摘要。它不等同于任意数据库、任意文件或任意日志读取；输出必须受预算、截断和脱敏约束 |
| 小说正文搜索工具 | Novel Text Search Tool | 跨模块概念 | 创作工作流 Agent 的只读内部工具，用于查找相关正文片段。第一版不新建第二套索引，而是在 imports 内部通过 adapter 优先调用 `modules.rag.facade.retrieve(...)`，把 `RagChunkContract` 转成 agent anchor；如果 RAG 无索引、embedding 失败或无命中，则降级为对 writing 最新草稿的有界关键词扫描，并记录 degraded reason。它负责返回 chapter_index、chunk_index、offset、scene_id、rag_chunk_id、短 snippet、匹配原因或 score，为后续精读定位候选材料；它不是把全文直接交给 LLM 的工具 |
| 小说正文读取工具 | Novel Text Read Tool | 跨模块概念 | 创作工作流 Agent 的只读内部工具，用于按 search anchor、rag_chunk_id、scene_id、chapter range 或 paragraph/offset range 读取精确正文片段。正文最高权威源是 `writing.facade.get_latest_draft_for_chapter()` 返回的最新章节草稿；RAG chunk text 只作为快速 fallback 或 stale offset 降级备援，避免索引过期时读错正文。Read 必须带范围；无范围读整章且超过预算时返回 context_overflow 并提示先 search 或缩小范围。所有结果都带 chapter_index、chunk_index、start_offset、end_offset、scene_id、rag_chunk_id 和 source_type anchor，并遵守上下文预算、snip 和 degraded diagnostics 规则 |
| Agent 权限阶梯 | Agent Trust Ladder | 跨模块概念 | 创作工作流 Agent 的权限模型，分为 Read、Suggest、Draft、Act with Confirmation、Autonomous。Read 只能读取受 novel_id 隔离、预算、截断和脱敏约束的工作流状态与正文片段；Suggest 只能生成候选计划或建议；Draft 可在用户启动的自动流程中写入 draft / candidate / pending 并保留 provenance、needs_review 和 rollback 信息；Act with Confirmation 包括 promote canonical、废弃已有资产、批量覆盖和合并实体，必须用户确认；第一阶段不开放 Autonomous |

## 2. 状态流转（Status Lifecycle）

遵循 **状态优先于删除**：业务运行时默认用 `status` 字段表达废弃/忽略/冲突。项目永久删除和 demo 开发库重建可以硬 DELETE。

```
                    ┌─→ ignored
draft → candidate ──┤
                    ├─→ canonical ──→ deprecated
                    ├─→ conflicted
                    └─→ pending (waiting for user)

异步任务:
pending → running → done / failed / cancelled
```

### 候选对象建议动作（CandidateAction）

```
create_new           — 创建新正史 CoreEntity
merge_with_existing  — 合并到已有实体
alias_of_existing    — 标记为已有实体的别名
ignore               — 忽略
temporary_only       — 仅临时场景
needs_user_decision  — 等待用户决策
```

### 重要性级别（ImportanceLevel）

```
core > important > normal > temporary > alias
```

实体抽取阈值：严格模式 ≥0.75，正常模式 ≥0.45。

## 3. 关键揭示层级（Reveal）

| 层级 | 含义 |
|------|------|
| author_only | 仅作者知道 |
| hinted | 已埋伏笔 |
| revealed | 已揭示给读者 |
| fully_known | 读者和角色都已知 |

读者安全不是固定布尔字段：

- `ReaderRevealInfo.status = unrevealed` 或缺失揭示点时，读者向输出默认不能使用该目标。
- `ReaderRevealInfo.status = partial` 时，只能使用对应 `known_content` / projection span 中已揭示的版本。
- `ReaderRevealInfo.status = revealed` 且 `ReaderProgress.effective_chapter_index >= reveal_chapter_index` 时，才计算为 `reader_safe=true`。
- 角色可见性和读者安全是两个独立维度；面向读者或角色 POV 的最终上下文取两者交集。

人物知识层级：

- `unknown`：角色不知道该目标，角色视角上下文中移除。
- `rumor`：角色只听过传闻，使用 `known_content` 中的传闻版本。
- `partial`：角色知道部分事实，使用 `known_content` 追加或替换为有限版本。
- `full`：角色知道完整事实，可按目标 sensitivity 和 reader safety 进入对应上下文。
- `restricted`：角色知道该事实存在，但具体内容受限；使用 `known_content`，不得暴露 hidden truth。
- `false_belief`：角色自认为知道但事实完全错误；必须提供 `misconception`。
- `misunderstood`：角色知道部分正确信息但归因、因果或意义理解偏差；必须提供 `misconception`。

## 4. 系统三层（Architecture Layers）

| 层 | 模块 | 说明 |
|---|------|------|
| **事实层** | `project`, `world`, `memory` | 小说的正史事实。world 拥有 CoreEntity + Character + Event + EntityRelation 以及 canonical state assembly；memory 拥有事件溯源、temporal snapshot 和 `delta_log` ingestion |
| **结构层** | `outline` | 把事实组织为可执行的剧情计划。PlotThread + OutlineArc + ChapterCard |
| **辅助层** | `rag`, `context`, `writing`, `imports` | 检索增强（RAG 分块）、上下文编译（跨模块组装 LLM context）、正文草稿承载、文件导入 |

模块通信：跨模块生产代码只能导入 `contracts.py`、`facade.py` 或 DI port。`api.py` 是 HTTP 入口，不作为模块间调用接口。Facade/API 不写复杂业务逻辑。

结构化差分边界：`delta_log` 归 memory 模块。deep import、world map 等模块需要记录
字段变化时，通过 `memory.facade.ingest_delta_events(...)` 或兼容 shim 委托 memory
完成 JSON 编码、provenance 合并和 row creation；world map 只接收已形成的 delta
event/delta_log 引用并组装地图候选观察，不拥有 memory provenance 拼装。

## 5. 关键流程约定（Key Conventions）

### 候选→正史（Candidate → Canonical）
默认流程：
1. AI 生成 → 入 candidate / proposal 状态
2. 用户审查（确认/编辑/忽略/合并）
3. 用户确认后 promote 为 canonical
4. 后台任务不在无用户授权的情况下自动 promote

例外：用户明确启动的自动流水线（如深度导入）可批量写入低风险 draft/candidate 创作资产，但必须先通过 Pydantic schema 校验，并保留来源、可编辑/可回滚标记。它不得自动写入 KnowledgeVisibilityPolicy、叙事专属 KnowledgeTag 或 CharacterKnowledge；这些知识连接必须进入导入审核建议，作者确认后才生效。

### 工作上下文（Working Context）
工作上下文是 AI 流水线内部使用的临时上下文层，用于长文档批量导入、后续结构分析和跨阶段抽取。它可以读取正史资产、草稿资产、候选创作资产、证据片段、置信度和来源依赖，但不等同于正史上下文。

- 长文档导入的第二轮/后续阶段可以基于候选创作资产继续抽取，避免等待用户逐条确认后才推进剧情线、篇章纲、关系和伏笔分析
- 工作上下文中的候选资产只能作为待确认依据，不作为用户确认后的硬事实
- 由候选资产派生的 PlotThread、OutlineArc、EntityRelation、ForeshadowingPlan、RevealPlan 等下游资产必须保持 draft / candidate / pending 等待确认状态
- 深度导入中基于待确认世界对象生成的 EntityRelation 和 Alias 也是待确认世界对象证据；它们可以参与后续 working context，但在用户确认前不应被视为正史事实
- 下游资产必须记录来源依赖；当依赖的候选资产被拒绝、合并或改名时，下游资产需要标记为需复核或重新计算
- 面向正式写作、最终一致性校验和用户确认后的输出时，应使用正史上下文，而不是直接使用未确认的工作上下文

实现方向：
1. 近期：在上下文编译入口提供显式模式（如 `context_mode="canonical" | "working"`）。默认使用 canonical；深度导入、批量抽取和结构分析等内部流水线显式请求 working。
2. Deep import snapshot v1：深度导入 Phase 2/Phase 3 的真实 LLM 调用会写入 `context_snapshots`，记录 task_id、workflow_id、phase、context_mode、included_asset_ids、摘要、prompt_hash、token/section metadata、result_refs、created_at，用于审计、复现和问题定位。
3. 持久化快照只记录当次 AI 调用使用过的上下文视图，不替代正史资产表，也不改变 candidate → canonical 的用户确认语义。
4. `context_snapshots` 默认不保存完整 rendered context；只保存摘要、资产 ID、hash 和 metadata。调用方显式启用 `retain_rendered_context=true` 时才保存完整上下文，并按保留策略清理 `rendered_context` 字段，不删除快照行和 provenance metadata。
5. Snapshot lifecycle v1：context 模块提供 `snapshot_health_summary` 聚合和显式 maintenance API，默认 dry-run；超时 running 快照标为 `failed/stale_running`，full context 清理只清正文和过期时间。
6. 手动 AI 操作应先创建 AI 参考资料确认记录，再把 `context_confirmation_id` 传给正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象等接口。手动 AI 第一版继续使用 `context_confirmations`；后续可在快照表稳定后迁移或补充回放入口。
7. `/api/context/confirm` 负责按用户当前选择重新编译上下文并创建确认记录，而不是只保存前端已预览结果；这样可以避免预览与最终执行之间的数据漂移。

用户控制边界：
- 正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象必须先展示并确认“AI 参考资料”，再执行 LLM 调用
- 深度导入不插入手动上下文确认；它保持自动化体验，由系统内部维护 working context，并在完成后集中展示结果、降级原因和待复核资产
- 上下文页保留为高级预览/调试台；手动 AI 操作应在自身流程中打开参考资料确认界面，而不是要求用户跳转到上下文页

“AI 参考资料”第一版可控项：
- 章节/Scene 范围
- 揭示模式（作者安全、作者全知、读者进度安全、角色视角）
- 是否包含待确认对象（内部状态为 candidate 的候选创作资产）
- 排除本次不想引用的世界对象、人物、剧情线、伏笔
- 本次 AI 额外注意事项

“AI 参考资料”弹窗编辑规则：
- 弹窗内编辑的是参考资料选择规则和本次补充说明，不直接编辑编译后的 Markdown 上下文正文
- 用户调整范围、揭示模式、是否包含待确认对象或排除资产后，通过“重新整理参考资料”重新调用上下文编译并刷新预览
- 如用户发现结构化资产本身错误，应跳转或弹出对应资产编辑表单；保存后再重新整理参考资料
- “本次 AI 额外注意事项”可作为临时高优先级上下文参与本次调用，并记录到 `_meta.user_note`，但不写入正史资产
- 第一版不支持手动粘贴/改写完整上下文 Markdown，避免产生脱离结构化资产体系的临时事实

用户可见文案应使用“待确认对象”，不直接暴露“候选资产 / candidate asset”等工程术语；代码、数据库和文档中的领域术语仍可使用 candidate / 候选创作资产。

待确认对象默认值：
- 正文生成默认不包含待确认对象
- 手动剧情分析、手动剧情结构生成、手动补抽世界对象默认包含待确认对象，并在界面提示“包含待确认对象，结果需复核”
- 深度导入内部自动使用待确认对象推进后续阶段，但不打断用户逐步确认

待确认对象变更后的影响处理：
- 第一版只标记受影响结果，不自动级联重算或覆盖用户已编辑内容
- 当生成结果或任务 `_meta.included_asset_ids` 引用了被忽略、合并、改名或提升的待确认对象时，相关结果应标记为 `needs_review` 或 `stale_context`
- `ready` 表示当前参考资料仍有效；`needs_review` 表示结果依赖待确认对象，需要用户复核；`stale_context` 表示依赖对象已发生结构性变化，建议重新分析或重新生成
- 用户可手动触发“用当前 AI 参考资料重新分析/重新生成”

### 实体抽取（Entity Extraction）
- **不是 NER**。不抽取路人、普通道具、代词、一次性场景元素
- 只识别值得长期维护的**创作资产**
- 深度导入等用户确认启动的抽取结果默认作为候选创作资产入库，`content_json._meta` 记录自动入库元数据；用户确认后再提升为正史

### 深度导入 Scene 预取（Deep Import Scene Prefetch）
- Scene 预取是深度导入正式 Scene 切分前的机会主义加速层，用于并发请求 LLM 获取 batch 级候选切分结果；batch 是现有 Scene 切分批次的别名，不是新的领域对象
- 预取结果默认不等同于正式 Scene。只有通过提交门（Commit Gate）的高质量结果，才可按顺序写入 `draft Scene`
- 提交门是确定性质量边界，而不是 LLM 自评；它至少要求 schema 校验通过、章节范围匹配、来源 hash 匹配、章节引用合法且覆盖目标章节
- Phase 0 结果分为高质量候选和低质量参考：通过提交门的结果进入高质量候选，Phase 1a 可强参考；未通过提交门但 schema 可解析的结果进入低质量参考，Phase 1a 可参考但可重写；schema 不可解析或空结果只记录失败，不进入参考
- 未通过提交门的预取结果只能作为正式 Phase 1 的参考材料，与原文一起提供给 LLM；正式 Phase 1 可以重写这些低质量结果
- 通过提交门的预取结果进入可写候选集合，但在正式写库前仍可由 Phase 1b 自动整理；已写入正式 `Scene` 表后的 Scene 不应被后台静默覆盖，如需改写，应走显式重新导入或用户编辑路径
- 预取结果只作为本次异步任务的中间状态持久化，不升格为长期业务资产；它可进入任务结果或 workflow 中间结果，用于恢复、审计和后续 Phase 1 参考
- Scene 预取同时承担真实 LLM API 稳定性探针职责；Phase 0 只在两轮预取最终 422 错误率超过 40% 时阻断深度导入，超时、空结果和 schema 失败进入诊断与质量统计，不单独作为 Phase 0 阻断条件
- 因 API 稳定性阻断时，用户可见提示应推荐切换更稳定的官方 API，例如：“推荐使用官方 API 以保障稳定性与质量（强推 DeepSeek-v4-flash，质量高、价格低、并发超快）”
- 正式 Phase 1a 可并发补强两轮预取中的可解析 batch，默认并发 50；Round A / Round B 的每个 batch 分别带正文补强，不在 Phase 1a 合并相交结果。补强输出仍是中间候选，不预先拥有正式输出权。Phase 1a 对 422、网络错误和 timeout 允许 1 次 retry，schema 解析失败、空结果或质量不过提交门不 retry；最终 422 错误率单独统计，超过 40% 时阻断深度导入并提示 API 通道不稳定。相邻参考只取章节意义上的前后 batch（按 `batch_index` / 章节范围），不能使用 LLM 返回完成时间作为叙事顺序
- 通过提交门的高质量预取结果也应等待正式 Phase 1 的顺序归并器统一写库；提交门决定“可写”，顺序归并器负责“何时写、以什么 `scene_index` 写”
- 深度导入允许在正式写库前自动整理中间 Scene 候选，包括融合、切分、重排和保留重叠 Scene；自动整理只作用于本次 workflow 中间结果，不直接删除或覆盖已写入的正式 Scene
- Scene 预取可采用双轮错位批次：第一轮默认 5 章窗口按起始章节顺序分批（如 1-5、6-10），第二轮默认从第 3 章开始偏移后再按 5 章分批（如 3-7、8-12），不额外补书首边界，书尾不足 5 章时允许短 batch；两轮结果地位平等，都是 Scene 候选观察，用于降低固定 batch 边界截断 Scene 的风险，最终正式输出权由 Phase 1b 自动 fusion / reducer 决定
- Phase 0 是机会主义预取层，一般失败不阻断正式 Phase 1；每个预取 batch 对 422、网络错误和 timeout 允许 1 次 retry。若 retry 后该 batch 最终仍为 422，则计入 422 错误率；schema 解析失败、空结果或质量不过提交门不触发 Phase 0 retry。当 Phase 0 两轮预取的最终 422 错误率超过 40% 时，应阻断深度导入并提示 API 通道质量不稳定。422 错误率以两轮预取 batch 数为分母，不按章节数、成功 batch 数或实际请求次数计算；初次失败和 retry 情况应记录到 workflow 诊断信息。用户提示建议为：“推荐使用官方 API 以保障稳定性与质量（强推 DeepSeek-v4-flash，质量高价格低并发超快！）”
- Phase 0 的 LLM 超时时间默认与正式 Phase 1a 流程一致，因为二者输入的正文规模一致；Phase 0 的定位差异体现在并发、暂存和降级策略，而不是更短的请求时间预算
- 正式 Phase 1 分为带正文质量补强和无正文自动整理：Phase 1a 使用正文和两轮预取 Scene 结果补强每个 batch 的 Scene 质量，产出两轮平等候选；Phase 1b 不带正文，只基于补强后的两轮候选做自动融合、切分、重排和生成整理提示，再交由顺序归并器写入正式 Scene
- Phase 1b 自动整理后的 Scene 数量可以多于或少于 Phase 1a；数量变化本身不是错误，但输出必须覆盖目标章节，并保留可追溯到 Phase 1a Scene 和章节来源的依赖信息
- Phase 1b 自动整理可以生成或改写最终 Scene 的标题、目标、核心冲突、情绪节拍和叙事标签等展示字段；但必须保留来源章节和 scene_chunks，不能生成脱离来源的漂亮摘要
- Phase 1b 可以调整 `scene_chunks.start_paragraph`，但只能基于 Phase 1a 候选、证据锚点或已有范围校正；没有可靠锚点时应保守沿用来源候选值或 0，并标记边界不确定，不能凭空发明精确段落
- Phase 1b 可以丢弃尚未写入正式表的 Phase 1a 中间候选；丢弃必须记录原因，如已融合、已拆分、重复候选、低置信不可用或超出目标范围。丢弃中间候选不等同于删除用户资产
- Phase 1b 自动整理失败时应按 Scene / 候选粒度降级：成功整理的输出继续使用，失败、无效或缺失覆盖的局部结果回退到对应 Phase 1a 补强候选；不应因为少数 Scene 整理失败而整批回退
- Phase 1b 对 422、网络错误和 timeout 允许 1 次 retry，schema 解析失败或空结果不 retry；最终 422 错误率也单独统计，超过 40% 时不阻断整个深度导入，而是放弃 Phase 1b 自动整理结果，降级为 Phase 1a 候选顺序写库并标记 degraded；用户提示应说明自动整理失败，已使用质量补强结果继续导入，并建议切换官方 API 提高整理质量
- 每个 Phase 1b 输出 Scene 必须声明来源和操作类型，包括来源候选 ID、来源章节、整理操作（kept / merged / split / reordered / rewritten）、置信度和是否需要回退；未被任何 Phase 1b 输出引用且没有明确丢弃原因的 Phase 1a 候选应回退写入，避免内容丢失
- Phase 1b 自动整理按章节窗口分段执行，不做全书一次性整理；默认窗口 30 章、窗口 overlap 3 章、并发 4。Phase 1b 输出允许在窗口 overlap 覆盖范围内跨窗口边界形成连续 Scene，但不能越权覆盖远超当前窗口范围的章节。窗口 overlap 区域若多个窗口覆盖同一来源候选，优先采用该候选主要章节所在 core range 的主窗口输出；非主窗口输出只作为边界参考或 fallback。最终由顺序归并器按章节顺序合并窗口输出并应用候选覆盖 / 回退规则
- 最终写入 `Scene` 表时应保留自动整理 provenance，但不新增业务表；优先放入现有可承载元数据的 JSON 字段，记录自动入库标记、workflow_id、生成阶段（如 phase1b_fusion / phase1a_fallback）、来源候选 ID、来源轮次、来源章节、融合/切分/重写操作、置信度和可选降级原因；若边界不确定，还应记录 boundary_status、boundary_reason、needs_review 和 review_reason，供后续 Scene 整理界面提示复核
- 深度导入前端进度条周围应展示阶段质量统计和降级信息，包括 Phase 0 两轮请求数、成功数、422 率、timeout 数、schema 失败数，Phase 1a 成功数、fallback 数、422 率，Phase 1b 自动整理窗口数、成功窗口数、降级窗口数、422 率，最终写入 Scene 数、needs_review Scene 数和是否使用 phase1a_fallback；这些信息应随 workflow 进度更新，而不是只在任务结束后展示
- 深度导入前端除主进度条外，应动态显示当前处理位置，包括当前章节范围、当前章节和当前 Scene / 候选 / 整理窗口；主进度条和当前处理提示应有克制的光效或流动状态，用于表达任务正在推进，避免用户误判为卡死
- 当前处理位置和质量统计应持续写入异步任务 result，刷新页面后可恢复展示；建议记录 current_phase、current_round、current_chapter_range、current_chapter、current_scene_candidate_id、current_window、current_operation 和 quality_stats
- 深度导入任务应支持从中断处恢复，但继续执行需用户明确确认：worker 启动时触发一次中断任务检测，运行中循环检测 stale / interrupted deep_import 任务并将状态写入 task result / 可查询状态；前端发现可恢复任务时提示用户“检测到上次深度导入中断，可从当前阶段继续”，用户点击继续后才恢复原 deep_import 任务并复用 async task result 中的 checkpoint。恢复后继续展示阶段、章节、候选、窗口和质量统计
- 用户确认继续中断任务时，应复用原 deep_import task，将原 task 恢复为可领取状态（如 pending），不新建 recovery task；这样 localStorage 中的 task_id、workflow_id、checkpoint 和 provenance 保持稳定
- 中断恢复第一版不新增任务状态枚举；保持现有 pending / running / done / failed / cancelled 体系。检测到 stale running deep_import 时，在 task result / meta 中标记 interrupted、recoverable、interrupted_at、last_heartbeat_at、recovery_required 等恢复信息；用户确认继续后再将原 task 改回 pending
- 用户也可选择放弃恢复；放弃恢复是破坏性清理操作，前端必须先警告会清理本次 workflow 已写入的派生 Scene / 自动实体 / 关系 / delta 等结果。用户确认后，系统按 workflow_id / provenance 清理本次中断导入已写入的派生资产，并将原 task 标记 cancelled；默认将已暴露的派生资产标记 deprecated，只有纯中间且未暴露资产才可硬删除；不得删除用户编辑过、canonical 或不属于该 workflow 的资产
- 用户点击继续恢复前，应展示 checkpoint 摘要，包括上次中断阶段、已完成章节 / 窗口 / Scene、已写入 Scene 数、已抽取世界对象数、将重跑的最小范围，以及是否存在 deprecated / 冲突 / needs_review 资产
- 中断恢复允许按阶段粒度局部重跑：Phase 0 按 batch，Phase 1a 按 batch，Phase 1b 按窗口，Scene commit 按 Scene / provenance 补写且不得整批重复写，Phase 2 世界对象抽取按 Scene，Phase 3 结构分析可整阶段重跑
- Scene commit 阶段应使用稳定 provenance_key 做幂等判断；provenance_key 由 workflow_id、source_candidate_ids、fusion_operation 和 source_chapter_indices 等来源信息生成并写入 Scene meta。恢复时若同 provenance_key 的 Scene 已存在则跳过，缺失则补写，已存在但 status 为 deprecated 时不自动复活，应记录冲突并标记 needs_review / fallback
- Phase 2 世界对象抽取应按 Scene 记录 checkpoint，包含 scene_id、scene_provenance_key、状态、创建的实体 / 关系 / delta ID、错误类型和 retry 次数。恢复时已成功 Scene 跳过，failed / stale Scene 局部重跑；若已成功抽取的实体后来被用户 deprecated，不自动复活，应标记 needs_review
- Phase 3 结构分析恢复时可整阶段重跑；重跑前只将同 workflow_id 且 source=deep_import 的自动生成结构资产标记 deprecated，再写入新的 draft / candidate 结构结果。用户编辑过、canonical 或不属于该 workflow 的结构资产不应被自动覆盖
- Phase 1a 可使用扩展的中间 schema，记录边界状态、证据锚点、融合建议、拆分建议、置信度和缺失/不确定项；这些增强字段只保存在本次 workflow 中间结果中，不写入正式 `Scene` 表

### 手动 Scene 融合（Manual Scene Fusion）
- 手动 Scene 融合是作者整理 Scene 时的显式操作：用户选择多个已有 Scene，请求 LLM 生成一个融合后的新 Scene
- 融合操作不应静默覆盖原 Scene；融合结果出来后，由用户选择后续动作：保留原 Scene 并保存融合 Scene、保存融合 Scene 并将原 Scene 标记为 `deprecated`、放弃融合结果、继续编辑融合结果后再保存
- 保存的融合结果默认创建新的 `draft Scene`，并记录来源 Scene 依赖；原 Scene 只在用户明确选择时才标记为 `deprecated`
- 融合后的新 Scene 必须继续保留章节来源、scene_chunks 和可编辑字段，不能只保存 LLM 摘要
- 手动融合是导入后的作者整理工具，与深度导入写库前的自动整理并存；它要求用户明确选择输入 Scene，不由后台任务静默触发

### 创作资产整理筛选（Creative Asset Triage Filters）
- Scene、世界对象和相关派生资产的管理界面应支持按状态、标签和导入标记筛选，方便用户快速整理深度导入结果
- 基础筛选至少包括 status（draft / candidate / canonical / deprecated / ignored / conflicted / pending）、needs_review、boundary_status、review_reason、source=deep_import、workflow_id、自动入库标记、实体类型和章节范围
- 管理界面应能快速定位 deprecated、needs_review、边界不确定、phase1a_fallback、phase1b_fusion、恢复冲突和用户待确认对象
- 大数据量导入后，筛选应优先由后端 API 查询参数支持，并配合分页；前端可做轻量二次过滤和状态呈现，但不应依赖全量拉取后本地筛选
- 筛选只改变管理视图，不隐式修改资产状态；批量废弃、恢复、融合、忽略或提升为正史都必须是显式用户操作

### novel_id 隔离（Project Isolation）
- 所有 API 在 service 层强制项目隔离
- 不跨 novel_id 合并关系、别名或正史对象
- BaseCRUDService 通过 keyword-only `novel_id` 参数强制该约束

### 别名管理（Aliases）
- 别名统一存储在 `core_entities.aliases` JSONB
- 标记为 `alias_of_existing` 而非创建新实体
- 深度导入 Phase 2b 发现的别名以内联待复核形式写入目标对象 aliases，单条别名保留 source、workflow_id、scene_id、confidence、quote、needs_review 等来源元数据
- 别名类型：name / title / nickname / alias / translation / abbreviation

### 嵌入与向量（Embedding）
- 向量字段在 PostgreSQL 用 pgvector，在 SQLite 测试模式存 JSON 序列化文本
- embedding 失败不阻塞索引（chunk 仍创建，检索退化到纯文本）

### 文件导入（Import）
- 白名单格式：.txt / .epub / .html / .htm / .mobi / .azw3
- 文件限制 ≤50MB
- 不信任上传文件名（os.path.basename 保护）
- 不把原文存入 import_records

## 6. 核心枚举速查（Key Enums Reference）

详见 `shared/enums.py`。以下是关键枚举值：

| 枚举 | 值 |
|------|-----|
| ObjectStatus | draft, candidate, canonical, deprecated, ignored, conflicted, pending |
| EntityType | character, location, faction, item, event, rule, power_system, species, group, secret, legend, resource, concept, creature, skill, other |
| ImportanceLevel | core, important, normal, temporary, alias |
| RevealLevel | author_only, hinted, revealed, fully_known |
| KnowledgeLevel | unknown, rumor, partial, full, restricted, false_belief, misunderstood |
| KnowledgeTagGrantSource | derived, manual, confirmed_suggestion, triggered |
| CharacterRole | protagonist, antagonist, supporting, minor, mentor, love_interest, comic_relief, foil, narrator, cameo |
| ContentSensitivity | author_only, author_safe, public_baseline |
| ReaderRevealStatus | unrevealed, partial, revealed |
| TaskStatus | pending, running, done, failed, cancelled |
| RelationType | parent_of, child_of, spouse_of, sibling_of, friend_of, rival_of, enemy_of, ally_of, mentor_of, student_of, lover_of, master_of, servant_of, member_of, leader_of, allied_with, at_war_with, trading_with, belongs_to, created_by, located_at, contains, controls, related_to, opposes, supports |
| ForeshadowingStatus | planned, seeded, reinforced, paid_off, abandoned |

## 7. AI 创作提示（Prompts）

系统使用 **8 个 prompt**（非复杂多 Agent）：

| Prompt | 用途 |
|--------|------|
| `structure_world_character.md` | 世界与人物结构生成 |
| `structure_plot.md` | 剧情结构生成 |
| `structure_chapter_scene.md` | 章节与场景结构生成 |
| `structure_review_memory.md` | 结构复查与状态抽取 |
| `structure_extraction.md` | 从章节正文抽取世界对象候选 |
| `extract_chapter_scene.md` | 从正文提取章节卡字段 |
| `extract_character.md` | 从正文提取人物档案字段 |
| `scene_segmentation.md` | 深度导入中的 Scene 切分 |

所有 prompt 通过 `infrastructure/llm/prompt_loader.py` 从 `backend/prompts/` 加载。

Prompt 合并策略：一次 prompt 输出多个 JSON 数组，入库时分别写入对应表。不按数据库表拆 prompt。

## 8. 技术栈概览（Tech Stack）

| 层 | 技术 |
|----|------|
| 后端 | Python 3.13 + FastAPI + async SQLAlchemy 2.0 + Pydantic v2 |
| 数据库 | PostgreSQL 17 + pgvector + pg_trgm |
| LLM | OpenAI 兼容 API（支持结构化输出 response_format） |
| 任务队列 | PostgreSQL 表 + 进程内 worker（FOR UPDATE SKIP LOCKED） |
| 前端 | Vanilla JS + CSS 变量 + Proxy 响应式状态 |
| 测试 | pytest + pytest-asyncio + SQLite 内存引擎 |
| 容器 | Docker Compose（PostgreSQL 17 + pgvector） |

## 9. 相关文档索引（Document Index）

| 文档 | 内容 |
|------|------|
| `docs/00_整体设计.md` | 系统三层结构、模块职责、目录结构 |
| `docs/01_数据库设计.md` | 活跃表完整字段定义（已移除废弃模块表） |
| `AGENTS.md` | AI agent 禁止事项、命令速查、命名规范 |
| `development-guide.md` | 开发命令、模块开发规则 |
| `testing-guide.md` | 测试约定（unit/integration/e2e） |
| `docs/adr/` | 架构决策记录 |
| `shared/enums.py` | 完整枚举定义 |
| `shared/constants.py` | 全局常量（分页/阈值/权重） |
| `modules/world/CLAUDE.md` | world 模块禁止事项 |
| `modules/imports/CLAUDE.md` | imports 模块禁止事项 |
