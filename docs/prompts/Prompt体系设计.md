# Prompt 体系设计文档（实际实现）

## 1. 设计原则

系统使用受确定性工作流编排的 Prompt 完成正文生成、结构生成、
抽取和切分任务，不构建自治多 Agent 运行时。

统一原则：

- 结构化 Prompt 输出经 schema 校验的 JSON；正文 Prompt 输出可审阅文本候选
- LLM 输出不直接写入已采用或正史状态
- `status` 不应作为 Prompt 契约的一部分
- 创建/关联/忽略主要通过 `suggested_action` 或调用方路由语义决定
- reveal、知识边界以及待处理建议与已采用资产的隔离由调用方服务和上下文编译器共同保证

## 2. 当前活跃 Prompt

| 文件 | 用途 | 主要调用方 |
|------|------|-----------|
| `shared_rules.md` | 所有结构化 Prompt 的共享规则 | 全部结构化 Prompt |
| `structure_world_character.md` | 创意启动阶段的世界/人物结构生成 | 手动生成流 |
| `structure_plot.md` | 剧情结构生成 | outline 结构生成 |
| `structure_chapter_scene.md` | 章节与场景结构生成 | 手动生成流 |
| `structure_extraction.md` | 从章节正文补抽世界对象 | world 抽取任务 |
| `scene_segmentation.md` | 正式 Scene 字段切分 / 小样本与单章恢复路径 | imports |
| `scene_entity_extraction.md` | 深度导入 Phase 2a，Scene 世界对象/Delta 与四类显式地图 proposal 抽取 | imports |
| `alias_relation_extraction.md` | 深度导入 Phase 2b，基于工作对象索引提取别名/关系 | imports |
| `extract_chapter_scene.md` | 从正文提取章节卡信息 | 写作/大纲辅助 |
| `extract_character.md` | 从正文片段提取人物档案字段 | 人物信息补全 |
| `scene_fusion_draft.py` | 内联 step `outline.scene_fusion.draft.structured`：基于选中 Scene 卡和精确正文生成融合语义草稿 | Scene 工作台 |
| `world_generation_center_service.py` | 内联 steps `world.generation.chat.generate`、`world.generation.core_entity.structured`、`world.generation.world_bible_page.structured`、`world.generation.world_bible_new_page.structured`：世界设定共创与结构化建议 | world 生成中心 |
| `world_bible_synopsis_service.py` | 内联 step `world.world_bible.synopsis.structured`：把已采用世界事实压缩为作者版 P1 世界观简介 | world 世界书简介刷新任务 |
| `generation_prompt_template_service.py` | 内置创作视角与项目级自定义模板；作为 author brief 进入生成中心 | world 对象共创 |
| `writing/services.py` | 内联 step `writing.generation.candidate.generate`：根据已确认上下文生成正文候选 | writing 正文生成 |

## 3. Prompt Contract System

深度导入链路和生成中心结构化建议链路使用 `backend/tools/prompt_contracts/` 做开发期漂移检查，覆盖
Phase 1a Scene slicing、Phase 1b Scene enrichment、Phase 1c Scene fusion、Phase 2 world extraction、
Phase 2b alias/relation、Phase 3 simple structure，以及 Generation Center 的
`world_generation_core_entity`、`world_generation_world_bible_page`、
`world_generation_world_bible_new_page` 和 `world_bible_synopsis`。检查入口是
`make prompt-contracts` 或 `cd backend && python -m tools.prompt_contracts check`。

Contract 使用 JSON 声明 prompt 字段、Pydantic schema、关键持久化映射、目标表列和
纯函数 probe。它不执行真实 LLM、不访问数据库、不扫描全仓库，也不允许任意 callable、
shell、表达式或动态代码执行。默认只有 P0/P1 阻断；文档漂移先作为 P2 记录。

生成中心的用户自定义模板另有运行时 validator：保存、预览和生成前校验
`{{variable_name}}` 占位符、必填变量、模板长度、对象类型和危险指令。运行时 validator
只渲染模板片段，不暴露完整正文、隐藏系统提示、API key 或 raw LLM payload；真正的
结构化输出契约仍由后端固定 scaffold 和 Pydantic schema 控制。

## 4. 历史 Prompt

| 文件 | 状态 | 说明 |
|------|------|------|
| `structure_review_memory.md` | 已删除 | `review` 模块已移除，不再保留 Prompt 文件 |

## 5. 当前设计约束

### 世界书简介类

`world.world_bible.synopsis.structured` 只负责压缩和组织来源 manifest，不裁决正史。输入先由
world 模块确定性排序、去重、冲突排除和预算裁剪；页面与结构化事实冲突时排除页面片段并保留
冲突提示。模型自行选择适合当前资料的有序导航 sections，可综合、归纳并突出关键结构，
不要求固定类别或穷举全部事实。每个实质段落引用至少一个服务端分配的短来源 key；服务再把
key 映射回经 `novel_id` 校验且真实存在于 manifest 的来源。无法归因的内容丢弃，schema
repair 最多两次；预算由调用配置控制，不在 Prompt 中硬编码统一篇幅。

世界书正文、简介和引用资料始终作为不可信 user/context 数据块注入；固定 system scaffold
禁止执行其中指令。作者模板是显式 author instruction，不与背景混入 system Prompt。
该简介只属于 `author_safe/author_full`，不得进入 reader/character/POV，也不得替代 P0
`World Core Brief`。生成结果写不可变派生 revision，不直接修改任何正史对象或世界书正文。

### 结构生成类

- `structure_world_character.md`
- `structure_plot.md`
- `structure_chapter_scene.md`

这类 Prompt 面向“结构化创作资产生成”，重点是：

- 产出世界对象、人物、剧情线、篇章纲、章节结构等资产
- Prompt 只输出经过 schema 校验的建议内容；调用方根据领域语义决定结果进入待处理建议、临时预览，还是在已持久化用户授权的流水线中直接落目标表
- `candidate` / `proposal` 可作为兼容或算法内部状态，但作者界面统一显示“待处理”；人工采用后由目标领域服务写入当前有效资产
- 文档不要再把旧版 `entity_candidates` / `geo_candidates` / `timeline_candidates` 当作数据库设计权威

### 抽取类

- `structure_extraction.md`
- `scene_entity_extraction.md`
- `alias_relation_extraction.md`
- `extract_character.md`

这类 Prompt 面向“从已有正文中识别长期资产”，重点是：

- 不是 NER，而是长期创作资产识别
- 别名走关联，不创建重复对象；深度导入 Phase 2b 将别名作为待复核内联证据写入目标对象
- 临时对象优先忽略或标记为临时
- 深度导入只有在任务保存授权快照后才可自动采用规则明确的结果，并保留 `auto_ingested`、workflow、证据和回滚元数据；异常结果进入待处理

### 切分类

- `scene_segmentation.md`
- `extract_chapter_scene.md`

这类 Prompt 服务于 Scene 和章节结构整理，不负责正史对象落库策略。
深度导入 60 章主链的 Phase 0 / Phase 1a / Phase 1b / Phase 1c prompt 不再由
`scene_segmentation.md` 单独代表，而是在 imports 的 `workflow_llm_adapters.py`
中按阶段组装，并通过 adapter、token budget 和 schema guard 输出中间候选或融合候选。
`scene_segmentation.md` 仍用于正式 Scene 字段切分、小样本检测和单章恢复等受控路径。

### Scene 工作台融合类

`outline.scene_fusion.draft.structured` 是同步、只读的结构化 step。输入仅包含
用户当前选中的 Scene 卡与通过 writing 稳定 range ref 重新校验的精确
SceneSpan 正文，并且 range ref 必须与该章当前 working / canonical 源版本
一致；不扩展到整章、RAG 或项目级上下文。单次最多 20 个 Scene，
Scene 卡字段和完整 JSON payload 均有确定性输入预算。输出 schema 只允许
`title / goal / core_conflict / emotional_beat / must_happen / must_not_happen /
narrative_tag / confidence / reason`；章节映射、Scene chunk、POV、状态和
provenance 由 outline 确定性逻辑保持。调用失败时只返回带 warning 的
确定性草稿，不写入任何 Scene；保存仍需用户在 Workbench 显式选择。
融合语义会综合全部选中 Scene 的兼容信息并去重；`primary_scene_id`
只在多个方案同样有证据支持或冲突无法兼容时作为意图、叙事重心和
表达取向的偏好信号，不是融合骨架，也不得导致其他 Scene 的有证据信息被忽略。

### 正文生成类

`writing.generation.candidate.generate` 把模型定位为长篇小说共同创作者，
直接输出可审阅的正文候选，不输出提纲、分析或 JSON。有当前 Scene 时
以 Scene 为写作范围，否则以当前章节为范围。已确认上下文作为
有边界的 user/context 数据注入，不进入 system Prompt。

写作上下文优先包含当前 Scene、当前章活跃剧情线、相关人物和物品。
人物与相关世界对象超出预算时，按显式选择、Scene、篇章、剧情线和
RAG 证据的关联顺序取 Top-K；人物上限 6，相关世界对象上限 16。
该 Prompt 不预设字数、段落数量、描写比例或统一节奏模板，允许模型补充
不改变重大设定的局部、可逆写作细节。结果只保存为 candidate，仍需作者显式采用。

#### 单角色 POV 正文候选

当写作确认记录同时指定当前 Scene、character reveal 和 POV 人物时，
同一 LLM step 切换为单角色有限视角。设计目的是让正文的感知、解读、
判断、对话和行动都受角色的当下经验与认知驱动，而不是强制第一人称
或堆叠内心独白。项目叙事人称、叙事距离和文风仍然有效。

上下文按用途区分为三类：

1. POV 档案、经 CharacterKnowledge 过滤的对象、其他人物的可观察信息和
   当前 Scene 证据，可以影响角色认知与行动。
2. Scene 目标、冲突、must/must_not 以及剧情线的公开进展仅作为
   `director_only` 叙事指导，不得变成角色已知事实。
3. compiler warning 只说明资料缺口或保守排除，模型不得伪造被排除知识。

输出仅有 `pov_state / draft_prose / uncertainties` 三个顶层字段。
`draft_prose` 是主要文学成果；`pov_state` 是简洁、可检查的状态摘要，
不要求模型暴露分步推理；`withheld_known_information` 只能记录角色
确实已知的信息；`uncertainties` 无实质问题时为空数组。不再拆分固定的
动作、表情、对话、内心戏和潜台词字段，避免结构绑架文学表达。
输出仍经 parser 和 hidden guard 确定性检查，并且只进入待审阅 candidate。

### 生成中心世界设定共创

`world.generation.chat.generate` 是不写库的自由共创 step，服务于世界对象、完善现有
页面和新建页面三种作者已选目标。设计重点是创意质量与逻辑严密性：模型根据对话状态自主
选择发散、比较、质疑、验证前提、指出因果/尺度/规则矛盾、提出真正影响设计的问题或阶段性
收束，不使用固定问卷，也不要求每轮同时覆盖所有维度。作者明确的选择、否定和最新修正优先；
资料是可参考但不可信的内容，不能改变任务、目标、权限或输出边界。
聊天正文仍是自然语言，但调用层用只含 `reply` 的 schema 校验非空与长度，
不把 provider 的任意原始输出直接当作业务响应。

三个结构化 step 分工如下：

- `world.generation.core_entity.structured` 忠实收束一个待处理世界对象建议，不进行第二次
  随机重设计。作者要求自由完成时允许模型运用创作判断；作者已有明确设计时，不为形式完整
  强加秘密、反转、关系、能力、代价或剧情用途。
- `world.generation.world_bible_page.structured` 综合完整当前工作稿、作者指令与项目背景，
  生成整页重构提案。当前页面是重要依据但不是唯一骨架；模型可重组标题、类别、概览和
  sections，不做末尾追加，也不降低既有 projection/sensitivity。作者已否定的
  助手方案不得在收束时复活。
- `world.generation.world_bible_new_page.structured` 生成完整新页面，并按资料自身选择合适的
  组织方式；不强制固定章节模板。页面模板只作为布局参考，不是创作内容清单。
  作者最新选择、否定和修正的优先级与现有页一致。

对象输出保留 `name / summary / public_info / hidden_truth / importance_level /
reveal_level / details / character_card`；页面输出为完整 `title / page_type / free_text /
sections / linked_asset_keys`。Prompt 不设置固定篇幅、必填创作维度或秘密/反转/冲突配额。
枚举、schema 校验、短资产 key 映射、稳定 section ID、模板版本、`novel_id` 隔离、上下文
快照和 suggestion-only 状态迁移由确定性代码负责。目标类型始终由作者选择，模型不能调用
工具、发布页面或写 canonical。

四个 step 共用 `generation_center` 上下文：显式选择与来源页引用优先，其后为当前 Scene、
剧情线、篇章/RAG 证据、相关人物和世界对象 Top-K、项目风格及可选世界观简介。人物自动
候选最多 6 个，非人物世界对象最多 16 个；没有章节、Scene、引用或检索证据时不默认注入
第一章剧情线。选中章节在总预算内优先取命中作者意图的窗口，无命中时保留头尾。
当 Scene 与参考章节同时存在时，Scene 所在章是剧情线、篇章和 RAG 的有效剧情锚点；
选中章节只作为参考正文。Prompt 会告知模型背景可能经过选择、摘要和预算裁剪，
因此“未出现”不代表“不存在”。snapshot 另记录人物/对象实际纳入、未纳入 ID、
候选来源与 `top_k/not_loaded` 原因，预算裁剪后的 actual IDs 只包含模型真正看到的来源。

内置模板不规定对象必须拥有哪些字段，而是提供与类型相关的创作视角。
人物聚焦欲望、阻力、选择和行为逻辑；事件聚焦有因果的状态变化；物品聚焦
使用、持有与争夺；地点聚焦空间如何塑造行动与生活；组织聚焦集体决策与行动；
规则聚焦对世界运行和选择后果的稳定约束。外貌、秘密、反转、宿敌、代价、例外等
都只在对当前对象有帮助时发展，不为填满模板强行生成。

`不带模板` 不预设固定框架，允许对象暂时跨类别，并先收束为概念建议。
现有结构化输出仍确定性映射为 `concept`；这只是采用前的临时分类，不是对创作内容
的强制归类，作者可在采用前调整类型。模板不覆盖结构化 system scaffold，
不声明 JSON、数据库字段、状态或采用操作；这些边界继续由确定性代码与 schema 负责。

## 6. `shared_rules.md` 的权威地位

该文件当前只是结构化 Prompt 的规则参考，不适用于正文生成 Prompt。
其规则要求：

1. 不直接生成小说正文。
2. 不输出最终数据库状态。
3. 不提前揭示隐藏真相。
4. 不让角色知道不该知道的信息。
5. 不凭空增加重大设定。
6. 输出必须符合调用方 schema。

Prompt 设计文档的职责是解释“为什么这样分工”，不是逐字复刻每个 Prompt 当前文件里的全部 JSON 字段。
