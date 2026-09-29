# 世界观工作台、上下文激活与深度导入完整方案

## 目标

建立完整的世界观功能，并让它成为 AI 参考资料和深度导入的上游能力。

核心方向：

- `world` 维护世界观资产，包括人物、势力、地点、规则、历史事件、重要物品、地图事实、人物知识边界和关系。
- `context` 负责把世界观资产按任务、Scene、地图焦点、关键词和激活规则编译成可审计 `ContextSection`。
- `imports` 不拥有世界观聚合，只通过 context facade 消费上下文，支持 Phase 2/3。
- 参考 SillyTavern World Info 的确定性激活、递归、预算、组内竞争和 prompt 装配机制，但映射到本项目的 `ContextSection` / 任务上下文，不照搬裸 prompt 位置。

## 非目标

- 不引入新的多 Agent 运行时。
- 不把 SillyTavern 的 World Info 文件格式作为本项目存储格式。
- 不让 imports 直接读取 world/context 内部 repository 或 service。
- 不把 LLM compact 输出写成正史事实。
- 不让写作或 Scene-local 抽取默认读取未来 Scene。

## 领域模型

### World Bible

`World Bible` 是世界观手册，是世界设定工作台的核心产品形态。它面向作者，而不是面向数据库表。

手册应像百科/创作指引一样组织内容，并采用固定核心册页 + 可扩展自定义册页：

- 世界基本背景：世界观一句话、基调、时代、文明阶段、核心矛盾、超自然/科技边界、作者硬约束。
- 种族/群体：种族、物种、阶层、职业体系、文化习俗、偏见和禁忌。
- 势力：组织、国家、宗教、公司、家族、秘密社团、阵营目标和冲突。
- 地点/地图：世界地图、区域、城市、建筑、秘境、势力范围、移动约束。
- 历史重大事件：战争、灾难、王朝更替、组织成立、秘密事故、纪年。
- 规则体系：魔法、超凡、科技、契约、代价、禁忌、社会制度。
- 重要物品：神器、钥匙、资源、文件、笔记、传承物。
- 主要人物：人物档案、所属势力、人物知识边界、关系网。
- 秘密与伏笔：作者已知、读者未知、揭示计划、冲突风险。
- 自定义册页：面向特定类型小说的扩展入口，例如修仙境界、科幻技术树、神系/位面、怪物图鉴、职业/技能树。

每个手册页采用三层结构：

- 页面元数据模板：面向展示、组织、写作状态、关联入口和局部校验提示。不同册页可以有不同页面组织字段，但不重复保存 profile 已拥有的事实属性。
- 自由正文：面向作者完整表达设定，不强迫所有内容拆成表单字段。
- 关联资产/激活规则：把页面连接到 CoreEntity、EntityRelation、地图事实、历史事件、人物知识边界、结构资产、AI 建议、冲突检查项和 `ContextActivationRule`。

这种结构借鉴 SillyTavern World Info 的“条目卡 + 激活元数据”心智，但不把世界观手册降级为纯文本 lorebook。可验证、可编译、可联动的事实核心在 profile / 关系 / 地图事实等世界资产里，手册页负责组织和呈现。

页面元数据采用模板注册机制：

- `world_bible_pages` 只保存 `template_key`、`template_version`、`page_meta_json`、`free_text` 和关联引用。
- 页面元数据 schema、字段类型、前端渲染提示、上下文投影和冲突检查提示由 `World Bible Page Template` 提供。
- 内置固定册页模板第一版由代码注册表提供，包含世界基本背景、种族/群体、势力、地点/地图、历史、规则体系、重要物品、主要人物、秘密与伏笔。
- 自定义册页第一版只提供通用模板，不做自定义模板编辑器；当作者需要自定义字段时，后续再用 `world_bible_page_templates` 持久化模板定义。
- 模板升级通过 `template_version` 管理；旧页保留页面元数据，迁移逻辑负责补默认值、重命名字段或标记废弃字段。

手册页是资产视图，不是第二套正史文档：

- 正史事实仍由 CoreEntity、类型 profile 强字段 / `extra_json`、EntityRelation、地图事实、人物知识边界和结构资产拥有。
- 人物、种族/群体、势力、地点、重要物品、历史事件、规则体系、秘密、资源等世界对象优先复用 CoreEntity，不新建平行的人物表、种族表、势力表、事件表或规则表作为 World Bible 主数据。
- World Bible 的种族、势力、地点、物品、主要人物等入口页只是基于 `entity_type`、标签、profile 字段和关系的分类视图；它们可以提供不同编辑模板，但底层仍写同一套世界资产。
- 历史事件和规则体系也是世界对象；它们可以用事件类 / 规则类 CoreEntity 承载正史身份。事件排序优先复用现有 `Event.timeline_order`、`occurrence_time_label`、事件关系和时间线视图；规则层级优先用 EntityRelation、profile 字段和规则视图表达。
- 只有世界基本背景、跨对象说明、自由手册正文或纯组织型页面，才主要由 `world_bible_pages` 或 projection 表达。
- 手册页负责组织、展示、编辑入口、自由说明、按需一致性检查报告入口和上下文预览。
- 自由正文可以长期保存，服务作者表达和阅读；当页面被激活时，`free_text` 默认可作为 AI 参考资料来源，但必须通过 `Free Text Projection` 进入上下文，不能整段无审计地塞入 prompt。
- 自由正文中的新事实如果要进入冲突检查、地图联动、深度导入支持或正史资产，必须转成 profile 字段、关系、地图事实或待确认建议。
- 页面渲染时可以把 profile 字段、关系、地图事实和自由正文组合成百科体验；context 编译可读取权威资产字段和 free text projection；冲突检查必须依赖结构化资产、明确来源和待确认建议。
- 这避免同一设定在“百科正文”和“实体库”中各写一份后互相冲突。

事实所有权和单向数据流：

- Profile 强字段是结构化、可查询、可计算的事实属性，是世界对象事实的首选真相源。例如种族寿命、势力成员规则、地点可达性、规则触发条件。
- Profile `extra_json` / generic profile `data_json` 是尚未固化为强字段的半结构化事实，仍属于对应 CoreEntity profile，是强字段孵化器；它必须有模板 schema，不能作为绕过校验的自由 JSON。
- World Bible Page 只保存 `page_meta_json`、`free_text`、关联资产引用和激活默认值；它可以组织、解释和引用事实，但不定义 profile 事实。
- World Bible Page `free_text` 是作者手册旁注/叙述草稿，默认非权威。若出现新事实，进入创设建议或冲突检查；作者确认后提升到 profile、关系、地图事实、人物知识边界或结构资产。
- `writing_drafts` 正文是唯一读者面向艺术文本，不作为世界设定真相源。正文与 profile 冲突时，profile 仍是作者设定真相；正文可被解释为角色有限视角、误传、戏剧化表达或待修订文本。
- Projection 是从 profile、页面引用和 `free_text` 派生的上下文缓存，只服务运行时预算和 AI 参考资料，不回写正史事实。
- 数据流必须单向：作者编辑 profile / 关系 / 地图事实 / 人物知识边界 -> World Bible Page 引用和叙述 -> projection 缓存 -> AI 参考资料。反向写入只能走建议队列和作者确认。

`Free Text Projection` 的生成策略：

- 短 `free_text` 可由代码直接摘录或分段截取，不必调用 LLM。
- 长 `free_text` 由 LLM 按 `World Bible Page Template` 生成投影，提示词必须要求只摘录/压缩/整理，不新增事实、不推断、不改变正史状态。
- 投影应优先补充 profile 字段没有覆盖的背景气质、文化偏好、例子、创作语感和未结构化细节，避免重复塞入已经由 profile 强字段表达的事实。
- 如果 LLM 从 `free_text` 发现可结构化事实，输出进入 `creation_suggestion_queue` 或冲突检查队列，不直接写 CoreEntity、关系或地图事实。
- 投影进入 `ContextSection` 时必须带 source page、source spans、activation reason、token 占比、裁剪原因和 stale 状态。

投影进入上下文的默认 tier：

- `World Core Brief`：P0，短，永不驱逐。
- profile 强字段 / profile `extra_json` 的模板投影：P1/P2，优先于自由正文投影。
- `free_text_projection.context_brief`：P2，作为常规世界设定背景。
- `free_text_projection.style_notes`：P3，补充气质、口吻、文化偏好和例子，预算紧张时先裁剪。
- `free_text_projection.excerpt` fallback：P3/P4；只有用户显式选择该页或任务强相关时才提升。
- `free_text_projection.fact_candidates`：不进入创作上下文，只进入建议队列、冲突检查和审查 UI。

投影可见性和剧透门禁：

- `sensitivity` 默认从页面、模板字段和关联资产中取最保守值；同一 projection 混合多个来源时，按最敏感来源标记。
- `reader_safe` 不是全局布尔字段，也不是长期存储枚举；它是运行时根据 `ReaderRevealInfo` 和 `ReaderProgress` 计算出的结果。
- `ReaderRevealInfo` 记录某个 TargetRef 或 projection span 的首次揭示位置：`status(unrevealed/partial/revealed)`、`reveal_chapter_index`、可选 `reveal_scene_id`、可选 `reveal_plan_id`。
- `ReaderProgress` 由读者向任务、预览或测试读者状态显式传入，第一版至少包含 `effective_chapter_index`，可选 `scene_id`。
- 若目标没有 `ReaderRevealInfo`，或状态为 `unrevealed`，默认不对读者安全；只有显式标记为 `public_baseline` 的世界常识可以在无揭示点时进入读者向上下文。
- `author_safe`：作者可见但可能包含尚未揭示的设定，可进入作者规划、深度导入、结构分析和世界观整理；写作正文时只有在任务明确为作者全知规划或显式选择时使用。
- `author_only`：隐藏真相、未来揭示、秘密血统、幕后组织、伏笔答案、未公开规则等，只能进入作者全知任务；角色视角、读者安全上下文和当前 Scene-local 抽取默认排除。
- 写作某角色视角时，projection 还必须通过 `character_knowledge` 过滤：unknown 删除；restricted 使用 `known_content` 替换；false_belief/misunderstood 使用误解内容；partial/rumor 只追加角色已知版本。
- 不同角色视野通过 `character_knowledge(character_id, target_type, target_id)` 区分。同一个 CoreEntity、关系、事件、规则或地图事实，可以为 A 角色记录 full，为 B 角色记录 false_belief，为 C 角色没有记录；在 character reveal 模式下，缺失记录按 unknown 处理并从该角色上下文移除。
- `known_content` 是“该角色视角能使用的版本”，不是 canonical 事实副本；`misconception` 是该角色的错误认知。canonical 作者事实仍保存在 CoreEntity、类型扩展表、关系、地图事实或 projection 中。
- `source_chapter_index` / `source_memory_id` 用于判断角色何时知道某事。编译某章节或 Scene 的角色视角时，只能使用在该章节之前或当前 Scene 已发生证据能够支持的 knowledge 记录，不能让后文知识提前进入。
- 群体视角或多 POV 任务必须显式传入 `focus_character_id` 或 POV 列表；没有角色视角参数时，默认走作者/读者可见性规则，不隐式猜测某个角色视野。
- 角色数量很大时，不建立“角色 × 世界对象”的完整知识矩阵。`character_knowledge` 是稀疏覆盖表，只记录主角、POV、关键配角、秘密知情人、误解者、偏离群体默认值的例外和明确剧情证据。
- 公共常识和读者已揭示内容不写 per-character 记录；角色可见性由 `KnowledgeVisibilityPolicy` / `CharacterKnowledge` 控制，读者安全由 `ReaderRevealInfo` / `ReaderProgress` 控制。
- 不在事实字段内嵌 `visible_to: [character_id...]` 列表。普通事实片段必须使用规范化的 `KnowledgeVisibilityPolicy`；少量个人秘密才使用 private 兜底。
- `KnowledgeVisibilityPolicy` 第一版正式执行三层：`public` 全可见；`tag` 基于 `KnowledgeTag`；`private` 直接授权少量角色。
- `KnowledgeTag` 压缩共同知识域，例如某势力成员、某种族、本地居民、亲历某事件、读过某书。事实来源通过 `asset_knowledge_tags` 关联标签，角色通过 `character_knowledge_tags` 或 EntityRelation 推导标签。
- `KnowledgeTag` 维护采用混合模式：基础身份标签由系统从 CoreEntity、类型扩展表和 EntityRelation 自动派生；叙事专属标签由作者手工创建；AI 只能生成待确认标签建议。
- 作者拥有最高控制权：可以固定添加标签、通过 `KnowledgeTagExclusion` 永久排除某个自动派生标签、覆盖某个事实片段的可见性，也可以把某个秘密设为 private，使自动标签/规则都不能触达。
- `rule`、`KnowledgeImplication`、事件触发器第一版只存草案和提供静态预览，不参与正式可见性判决。`rule` 草案仍禁止 eval / exec，只能保存白名单结构化谓词，例如 entity_has_relation、character_has_tag、chapter_at_least、located_in、holds_item、member_of、species_is、role_is。
- 群体默认知识第一版主要通过 derived/manual `KnowledgeTag` 表达，例如某势力成员、某种族、本地居民。更复杂的 `KnowledgeScopeRule` 作为后续 rule 草案预留。
- 角色视角上下文的正式可见性按优先级解析：直接 `CharacterKnowledge` 覆盖 > 作者手工标签/排除 > 明确剧情记忆/当前 Scene 证据 > `private` grant > tag 命中 > `public` 默认知识 > 默认 unknown。若该输出同时面向读者，还必须再通过 reader-safe 过滤。
- 若继承规则和 per-character 记录冲突，以 per-character 为准；若多个标签/规则冲突，取更保守的 knowledge_level，并记录冲突诊断给作者确认。
- `KnowledgeImplication` 可表达知识继承，例如知道“国王被毒杀”默认知道“国王不是自然死亡”。第一版只在 UI 侧栏预览“如果启用继承，可能额外可见哪些事实”，不自动授权；后续启用时继承链必须有上限，必须记录来源和解释，不能让 LLM 自行无边界推理出角色可见性。
- LLM 可以辅助模糊边界判断或生成建议，但不能替代结构化门禁。进入最终 prompt 前必须经过 deterministic visibility filter；第一版 filter 只执行 public/tag/private + CharacterKnowledge，LLM 判断结果只能作为待确认建议或 diagnostics。
- 深度导入和手册页整理不得为所有路人批量创建 `character_knowledge`。它们只能创建重要角色或异常知识的建议项；大范围默认知识应生成 KnowledgeScopeRule 建议。
- `free_text` fallback 摘录必须保守：无法判定 sensitivity 或 reveal 信息时按 `author_only` 处理，不能因为 projection 缺失而把整段设定泄露给角色视角或读者向输出。
- `source_spans_json` 应为每段投影记录 sensitivity、source field/page、ReaderRevealInfo 和 risk 标签，便于 AI 参考资料预览显示“为什么进入”和“为什么被裁剪/隐藏”。
- 若同一页面同时有公开种族常识和隐藏起源秘密，projection 应拆成多个 sensitivity / reveal 信息不同的片段，而不是生成一个混合敏感度的大摘要。

投影生成应异步后台化：

- 保存 World Bible Page 时只做确定性操作：保存 `free_text`、计算 `free_text_hash`、短文本生成 excerpt projection、长文本把 projection 标记为 pending/stale 并入队。
- 前端保存立即返回成功，并在手册页和 AI 参考资料预览中显示“AI 参考资料整理中”或等价状态。
- 后台任务生成长文本 projection，成功后写 `world_bible_page_projections(status="valid")`；失败时写 failed 诊断，不阻塞页面保存。
- context 编译遇到 stale/pending projection 时，优先使用同 page/hash 之前最近的 valid projection 并标记 stale；没有旧版时使用有界摘录 fallback，并记录 `truncated_reason` / `activation_reason`。
- projection 生成和上下文编译都必须继续经过 `ContextSection` 预算裁剪；持久化 projection 不代表它每次都会完整进入 prompt。

### Page Organization Task

`整理此页` 是页面级受控 AI 整理任务，参考深度导入的可观察 workflow 形态，但范围限定为单个 World Bible Page。

输入：

- `world_bible_pages` 的 title、template_key、template_version、page_meta_json、free_text、linked_asset_refs_json。
- 当前 valid/stale projection 摘要和 free_text_hash。
- 关联 CoreEntity、EntityRelation、地图事实、人物知识边界和结构资产的只读摘要。
- 当前模板的 fields_json、context_projection_json、conflict_rules_json。

阶段建议：

1. `page_preflight`：校验 novel_id、页面状态、模板版本、free_text_hash、projection 状态和关联资产可读性。
2. `projection_refresh`：必要时刷新 short excerpt 或触发/等待长文本 projection；不阻塞已可执行的整理。
3. `page_meta_suggestion`：从 free_text/projection 中提取页面展示、组织、写作状态和关联入口建议，不生成 profile 事实字段。
4. `asset_suggestion`：提取可提升到 CoreEntity profile、EntityRelation、地图事实、人物知识边界或结构资产的待确认建议。
5. `conflict_scan`：按模板 conflict_rules_json 和现有资产检查事实冲突、设定重复和叙事风险。
6. `result_commit`：只写 `creation_suggestion_queue` / `conflict_check_queue` / task result，不直接写 canonical。

诊断形态参考深度导入：

- 每次任务有 `workflow_id` / task_id。
- task result 包含 `phase_timeline`、`quality_stats`、`phase_artifacts`、`diagnostic_counts`、`last_error`。
- phase artifacts 只保存脱敏摘要、计数、hash、source refs 和建议 ID，不保存 raw prompt、raw output、整段 free_text 或 API key。
- quality_stats 至少包含 checked_page_meta、page_meta_suggestions、asset_suggestions、conflicts_found、duplicates_suspected、projection_stale_used、fallback_excerpt_used、format_repairs、degraded。
- 任务可按 page_id + free_text_hash 幂等重跑；重复建议应按 source page、source span、target type、normalized title 去重。

写入语义：

- 页面元数据补全、profile 字段、实体、关系、地图事实和人物知识边界都先进入建议队列。
- 事实冲突和叙事风险进入冲突检查队列。
- 作者确认后才写入 page_meta_json、CoreEntity profile、EntityRelation、地图事实或其他正史资产。
- 若整理任务失败，页面保存和现有 projection 不回滚，只记录 failed diagnostics 和可重跑范围。

整理结果必须分组确认：

- 页面元数据建议：只影响当前 `world_bible_pages.page_meta_json`，可一键应用到当前页草稿或正史页，并记录来源 span。
- 新对象/profile 字段/关系/地图事实建议：可能创建或修改 CoreEntity profile、EntityRelation、地图事实、人物知识边界或结构资产，必须逐条确认或在明确范围内批量确认。
- 冲突/叙事风险：进入冲突检查队列，只标记处理、忽略、转任务或关联修订，不自动修改正史。
- 后续任务建议：例如“整理关联势力页”“检查地图分布”，只创建待办或任务建议，不自动运行。

页面元数据补全应用后的页面状态：

- 页面本身是 draft 时，页面元数据补全默认写入 draft。
- 页面本身是 canonical 时，页面元数据补全默认生成未发布修改，状态可表达为 `draft_changes` 或等价 pending publish 状态。
- 未发布修改可用于手册页预览和再次整理，但默认不进入 canonical 世界观手册上下文。
- 作者点击“确认并发布到正史手册页”后，才更新 canonical 版本、创建 `World Bible Page Revision`，并触发 projection hash / projection stale 流程。
- 自动保存、光标级编辑和未发布修改不创建版本历史；版本只在发布、应用整理建议、回滚等有意义节点记录。

发布前检查：

- schema / template 校验失败必须阻塞发布，避免非法字段形状进入 canonical 手册页。
- `free_text` 可保存原文，但如果投影生成失败，只标记 projection failed / stale，不阻塞页面发布。
- 事实冲突和叙事风险不阻塞发布；它们进入冲突检查队列，并在发布确认 UI 中作为警告展示。
- 若冲突项涉及隐藏真相、人物知识边界或地图事实，发布成功后仍需保留待处理冲突项，不能自动当作已解决。
- 发布结果应返回 revision id、schema 校验结果、projection 状态和新增冲突/风险计数，供前端展示。

确认动作应保留 result group、source page、source span、target asset、before/after 和 confirmed_by，方便回滚、审计和 AI 参考资料预览显示来源。

范围约束：

- 第一版默认只整理当前 `page_id`。
- 关联实体、地图、关系、人物知识边界、结构资产和其他 World Bible Page 只作为只读上下文。
- 不递归启动关联页面整理，不自动改写关联页面的 free_text、page_meta_json 或 projection。
- 如果发现关联页面也需要整理，只创建“建议整理关联页面”的后续任务建议，等待作者确认。
- task result 必须记录 `scope.page_id`、`scope.free_text_hash`、`read_context_refs` 和 `suggested_followup_page_ids`，便于重跑和审计。

`世界基本背景` 是完整作者页，不等同于每次塞进 LLM 的常驻资料。进入 AI 参考资料时应派生出 `World Core Brief`：

- 作为 P0 常驻 section，但保持很短。
- 只包含世界一句话、时代/文明阶段、核心规则边界、叙事禁区、核心矛盾和作者硬约束。
- 不包含完整历史、全部种族、全部势力、长篇设定说明或作者备注正文。
- 详细背景段落降为 P1/P2，通过关键词、任务、地图焦点、Scene 证据或用户显式选择激活。
- `World Core Brief` 不交给 LLM compact 改写；需要压缩时由确定性字段拼装或由作者确认后的摘要版本生成。

### Worldbuilding Workspace

世界设定工作台是作者维护世界观的产品入口，不是独立世界观数据库。它复用并增强：

- `core_entities`
- 类型扩展表：现有 `characters` / `events`，新增 species / group / faction / location / item / rule / power system 等扩展表。
- `entity_relations`
- `character_knowledge`
- `map_*`
- `plot_threads` / `outline_arcs` / `foreshadowing_plans` / `reveal_plans`
- context activation metadata

世界观资产类型包括：

- 人物：`entity_type="character"`，主角、配角、组织成员、临时角色；人物特有字段由现有 `characters` 扩展表承载。
- 势力：`entity_type="faction"`，组织、国家、宗教、公司、家族、秘密社团；由势力扩展表承载目标、资源、成员规则、领地摘要等字段。
- 种族/物种：`entity_type="species"`，种族、物种、血脉、人类分支、妖族等；由种族扩展表承载起源、能力边界、生理/文化特征、分布等字段。第一版需要补充现有实体类型校验和 LLM 中文类型映射。
- 群体：`entity_type="group"`，阶层、职业体系、社会群体、族群联盟、非正式群体；由群体扩展表承载准入条件、社会地位、职责、禁忌等字段。不要和 context activation 的 `inclusion_group` 字段混淆。
- 地点：`entity_type="location"`，城市、区域、建筑、秘境、路径、势力范围；由地点扩展表承载地理层级、可达性、环境、地图绑定摘要等字段。
- 规则：`entity_type="rule"`，社会规则、禁忌、契约、代价、具体规则条目；由规则扩展表承载适用范围、触发条件、代价、例外、冲突检查语义等字段。
- 力量体系：`entity_type="power_system"`，魔法体系、超凡体系、科技体系、修炼体系；由力量体系扩展表承载等级、资源消耗、限制、晋升/升级规则等字段。
- 历史事件：`entity_type="event"`，战争、灾难、王朝更替、组织成立、秘密事故；由现有 `events` 扩展表承载来源章节、发生地、时间线顺序和时间标签。
- 重要物品：`entity_type="item"`，神器、钥匙、卷轴、笔记、特殊道具；由物品扩展表承载功能、限制、持有状态、来源、关联规则等字段。
- 资源：`entity_type="resource"`，矿物、能源、货币、稀缺材料、战略资源；由资源扩展表承载产地、用途、稀缺度、流通规则等字段。
- 秘密：`entity_type="secret"`，隐藏真相、未揭示设定、伏笔事实；由秘密扩展表承载 reveal plan、读者/角色已知边界和泄露风险。
- 传说：`entity_type="legend"`，神话、民间传说、历史误传；由传说扩展表承载版本、可信度、传播范围和真相关联。
- 抽象概念：`entity_type="concept"`，无法归入规则、秘密或资源的世界观概念；由概念扩展表承载定义、边界、关联对象和例子。
- 生物/怪物：`entity_type="creature"`，非种族级的怪物、召唤物、普通生物类别；由生物扩展表承载习性、能力、弱点、栖息地等字段。
- 技能/能力：`entity_type="skill"`，具体能力、职业技能、法术；由技能扩展表承载效果、消耗、限制、学习条件和关联规则。
- 其他：`entity_type="other"`，临时兼容类型；进入 World Bible 后应尽量整理成更具体类型。
- 地图事实：位置、领地、标记、移动约束、空间冲突。
- 人物知识边界：某角色在某章节/Scene 对某事实的了解状态。
- 结构资产：剧情线、篇章纲、伏笔、揭示。

### WorldBackgroundAggregation

`WorldBackgroundAggregation` 是世界观资产到 AI 上下文之间的聚合层。它不是简单实体列表，而是分层摘要。

建议输出的内部条目形状：

```json
{
  "entry_id": "stable-derived-id",
  "novel_id": "...",
  "asset_type": "entity | relation | map_fact | rule | history | item | character_knowledge | structure",
  "asset_id": "...",
  "group": "faction:塔罗会 | location:廷根 | rule:占卜家途径",
  "title": "塔罗会",
  "summary": "短摘要",
  "facts": ["可进入上下文的短事实"],
  "keywords": ["塔罗会", "愚者", "聚会"],
  "primary_entities": ["..."],
  "map_ids": ["..."],
  "chapter_range": [1, 213],
  "scene_range": [1, 209],
  "importance": 0.92,
  "tier": "P0 | P1 | P2 | P3 | P4",
  "status": "canonical | draft | candidate | pending",
  "sensitivity": "author_only | author_safe | public_baseline",
  "reveal_info": {
    "status": "unrevealed | partial | revealed",
    "reveal_chapter_index": 12,
    "reveal_scene_id": "optional-scene-id",
    "reveal_plan_id": "optional-plan-id"
  },
  "reader_safe": false,
  "source_ids": [{"type": "core_entity", "id": "..."}],
  "activation_defaults": {
    "constant": false,
    "recursive": true,
    "max_recursion_depth": 2,
    "top_k": 8
  }
}
```

聚合由 world/context 协作提供：

- world facade 提供世界观资产和关系的稳定读取能力。
- context 模块负责将聚合条目编译成 `ContextSection`。
- imports 只通过 context facade 消费结果。

## 激活规则

### ContextActivationRule

激活规则描述“哪些世界观资料在什么场景进入 AI 参考资料”。第一版需要默认规则可用，后续开放细调。

建议字段：

```json
{
  "rule_id": "...",
  "novel_id": "...",
  "target_type": "core_entity | profile | generic_profile | relation | world_bible_page | map_fact | projection_span | event | character_knowledge | structure",
  "target_id": "...",
  "enabled": true,
  "task_triggers": ["deep_import_phase2", "deep_import_phase3", "writing", "conflict_check"],
  "scope_filters": {
    "scene_ids": [],
    "chapter_ranges": [],
    "map_ids": [],
    "focus_entity_ids": [],
    "character_ids": []
  },
  "primary_keywords": [],
  "secondary_keywords": [],
  "selective_logic": "and_all | and_any | not_any | not_all",
  "recursion": {
    "enabled": true,
    "max_depth": 2,
    "top_k": 8,
    "exclude_recursion": false
  },
  "budget": {
    "tier": "P1",
    "ignore_budget": false,
    "max_tokens": 600
  },
  "inclusion_group": "world-rule:占卜家途径",
  "priority": 100,
  "sensitivity": "author_only",
  "activation_reason_template": "当前 Scene 提到 {keyword}，激活 {title}"
}
```

表 `context_activation_rules` 可以在规则内容变多时新增。若先不建表，也必须让默认规则以同一 contract 形状表达，避免后续迁移语义。

作者默认 UI 不直接暴露完整规则字段。第一版只提供激活预览和简单开关：

- 默认参与 AI 参考资料。
- 仅显式选择时参与。
- 禁用。

默认预览应展示：

- 是否会进入 AI 参考资料。
- 为什么进入：Scene 命中、地图焦点、显式选择、关联实体、World Core Brief、递归激活等。
- 进入哪个 `ContextSection`。
- token 占比。
- 是否被裁剪、过期、fallback 或等待 projection。
- sensitivity：public_baseline / author_safe / author_only；reader_safe 为按读者进度实时计算的预览结果。

高级设置或调试视图再暴露 keywords、secondary keywords、selective logic、recursive、top-k、inclusion group、tier override、budget cap、projection 类型和 match source 诊断。普通作者不需要直接理解 SillyTavern 式 scan depth / insertion position / probability 等底层参数。

### 默认激活规则

默认规则应覆盖：

- 当前 Scene 明确关联的实体、地点、势力、物品。
- 当前 Scene 的前序邻居中共享实体/地点/关系的背景。
- 当前地图焦点关联的地点、势力范围、地图事实。
- 当前 focus entity 的别名、关系、人物知识边界。
- 当前任务需要的结构资产，例如 Phase3 读取全书结构摘要。
- `World Core Brief`、P0 项目核心设定和作者声明，永不被普通预算驱逐；完整世界基本背景页不能整体常驻。

## 参考 SillyTavern 的机制

SillyTavern 可迁移的是机制包装，不是具体 UI 或 prompt 位置。

### 数据来源合并

SillyTavern 会把 global lore、character lore、chat lore、persona lore 合并，并按策略排序。本项目对应：

- project core facts
- world asset aggregation
- map focus facts
- structure assets
- current Scene evidence
- previous Scene briefs
- user explicit focus

输出不进入裸 prompt 槽位，而是进入 `ContextSection`：

- `project_core`
- `scene_evidence`
- `world_asset_context`
- `map_focus`
- `character_knowledge`
- `structure_context`
- `retrieval_evidence`
- `compact_summary`

### 扫描 Buffer

SillyTavern 的 depth buffer、inject buffer、recursion buffer 在本项目映射为：

- current evidence buffer：当前 Scene chunks、显式 map_id、focus entity。
- previous neighbor buffer：前序 `NeighborSceneBrief`。
- global world asset buffer：世界资产聚合条目。
- recursion buffer：已激活条目暴露出的关键词、实体、地点和关系。
- injection buffer：用户显式选择的 AI 参考资料、作者备注、任务参数。

Phase2 Scene-local 抽取禁止把后续 Scene 放入 current evidence buffer。

### 激活主循环

本项目的 `ContextActivationEngine` 应采用确定性主循环：

1. 载入候选 world asset entries。
2. 按任务、novel_id、visibility、status、chapter/map/focus filters 过滤。
3. 常驻 P0 / explicit selected entries 直接激活。
4. 通过 primary keywords 匹配 current/previous/global buffer。
5. 对 secondary keywords 执行 and/all、and/any、not/any、not/all。
6. 对 inclusion group 做组内竞争，避免同一事实多版本重复进入上下文。
7. 对激活条目按 priority、importance、recency、source confidence 排序。
8. 执行 token budget cap 和 per-section cap。
9. 对允许递归的条目生成 recursion buffer，最多 2 层，每层 top-k。
10. 记录每个条目的 activation reason、match source、budget decision。

### 预算和溢出

预算策略应继承现有 `CompiledContext` tier 思路：

- P0：必需，不驱逐。
- P1：高优先级，可 delta compact。
- P2：中优先级，可按条目裁剪。
- P3：低优先级，可整段移除。
- P4：补充氛围，最先移除。

参考 SillyTavern 的要点：

- 每个 section 有 identifier。
- 加入 prompt 前检查 token budget。
- 溢出时记录具体 section 和原因。
- 少数 `ignore_budget` 只允许用于 P0 项，不能滥用。
- 用户界面展示 token 占比和裁剪原因。

### LLM Compact Step

LLM compact 只能在确定性筛选之后触发。

触发条件：

- 同一 group 中高价值条目过多，P1/P2 预算仍超限。
- Phase3 全书摘要视角需要跨 200+ Scene 做结构压缩。
- 世界背景聚合中某类资产过长，但不能完全丢弃。

禁止条件：

- P0 事实不得交给 LLM 改写。
- Scene-local 当前正文不得用 compact 替代证据。
- 格式失败不得通过扩上下文 compact 解决，应走格式 repair。
- compact 不得新增事实、补剧情、推断缺失设定。

compact 输出必须包含：

```json
{
  "summary": "短摘要",
  "source_ids": [],
  "coverage": "covered | partial",
  "omitted_reason": [],
  "token_before": 0,
  "token_after": 0,
  "uncertainty": [],
  "facts_not_preserved": []
}
```

## 上下文模块方案

### 新增核心服务

建议在 context 模块新增：

- `ContextActivationEngine`
- `ContextActivationRuleService`
- `WorldBackgroundLoader`
- `MapFocusContextLoader`
- `CharacterKnowledgeBoundaryLoader`
- `ContextCompactService`

这些服务通过 world/outline/map facade 读取数据，不跨模块 import 内部实现。

### ContextCompiler 扩展

`ContextCompiler` 增强为：

- 支持 task-specific activation，例如 `deep_import_phase2_scene`、`deep_import_phase3_structure`、`writing_scene`、`conflict_check`。
- 支持 explicit `map_id`、`scene_id`、`focus_entity_id`。
- 支持 `context_mode="working"` 时包含 candidate/draft/pending。
- 输出 `ContextSection.activation_reason`、`sources`、`token_count`、`truncated_reason`。
- 把 activation reasons 放在元数据中，不进入 LLM token。

### AI 参考资料预览

前端继续复用现有 AI 参考资料弹窗，但扩展展示：

- 世界观分组。
- 激活原因。
- source 类型和标题。
- token 占比。
- 裁剪原因。
- compact 标记和覆盖率。
- 用户可排除 section。

## 世界观手册与工作台方案

### UI 结构

完整世界观功能需要采用“百科手册 + 任务工作台”的双层 UI：

手册层：

- 第一版不做仪表盘式首页或跨册页总览；World Bible 首页只作为轻入口，展示册页导航、最近打开页或世界基本背景页入口。
- World Bible 首页下方放两个操作按钮：`创设建议` 和 `冲突检查`。点击后分别展开弹窗展示 `CreationSuggestionQueue` 和 `ConflictCheckQueue`；不在首页常驻展示完整队列、统计图或一致性报告。
- `创设建议` / `冲突检查` 弹窗默认显示当前页相关项，可切换到“全部”范围。弹窗允许跨页批量确认、忽略或转任务，但必须显示处理范围、影响对象和数量，并在跨页批量操作前二次确认。
- 世界基本背景：固定介绍页，记录世界常识、文明阶段、叙事禁区和作者硬约束；同时显示派生的 `World Core Brief` 预览，明确哪些短事实会默认进入 AI 参考资料。
- 种族/群体：CoreEntity 分类入口 + 条目页，默认包含 `species` 和 `group` 两个筛选类型，支持文化、能力、禁忌、历史、关系和地图分布。
- 势力：CoreEntity 分类入口 + 条目页，支持目标、资源、敌友、领地、成员、秘密计划。
- 地点/地图：CoreEntity 地点入口 + 地图联动页，支持对象到地图、地图到对象和地图事实。
- 历史：事件类 CoreEntity 入口，结合 `Event.timeline_order`、发生时间标签、事件关系和时间线视图，支持重大事件、影响对象、事实冲突检查。
- 规则体系：规则类 CoreEntity 入口，结合 EntityRelation、规则模板字段和层级视图，支持规则、代价、例外、冲突检查。
- 重要物品：CoreEntity 物品入口，支持持有关系、来源、规则关联、地图位置。
- 主要人物：CoreEntity 人物入口，支持人物档案、人物知识边界、关系网、当前位置。
- 秘密与伏笔：作者全知页，按 reveal plan 控制读者已知和角色已知。
- 自定义册页：作者可为特殊世界观增加入口；每个自定义册页仍要绑定资产类型、字段模板、上下文激活默认规则和冲突检查规则。

每个入口页负责浏览、筛选和排序；可显示当前页相关的字段缺失、projection stale / failed 等局部状态，但不提供跨册页仪表盘。普通实体详情页默认由 CoreEntity、关系、地图事实和人物知识边界动态渲染；只有作者为某个实体额外撰写百科正文、创作手册正文或特殊模板字段时，才创建绑定该实体的 `Entity Bible Extension Page`。高级激活参数默认折叠，不作为普通作者编辑世界观时的第一焦点。
手册页不是独立事实副本；它编辑和展示底层资产，并把自由正文中的可结构化事实送入建议或补全流程。

世界一致性检查报告：

- 第一版不做首页评分、仪表盘或常驻监控面板。
- World Bible 页面和对象详情页提供 `运行一致性校验` 操作，按需生成报告。
- 报告列出缺失引用、矛盾事实、不可解析关系、projection stale / failed、可见性冲突、地图事实冲突和待确认建议。
- 报告结果进入任务结果或诊断弹窗，不写入作者正文，不默认阻塞页面发布。
- 内部诊断类 API 可以保留给开发和后台任务，但不作为作者端 World Bible 首页能力描述。

工作台层：

- 对象库：高级筛选和批量编辑，不作为普通作者第一入口。
- 关系图：实体关系、势力归属、持有、敌对、知识边界。
- 地图联动：地图焦点影响 AI 参考资料，地图事实参与冲突检查。
- 激活规则：默认规则预览、单对象激活预览、简单参与开关；高级参数折叠到调试/高级设置。
- AI 参考资料预览：选择任务/Scene/map/focus entity 后预览将进入上下文的资料。
- 创设建议队列：LLM 提出的新增/补全/关系/地图候选，作者确认后写入正史；第一版从 World Bible 首页底部按钮打开弹窗。
- 冲突检查队列：事实冲突和叙事风险；第一版从 World Bible 首页底部按钮打开弹窗。

SillyTavern 的 Worlds/Lorebooks UI 提供了可借鉴的“册页、条目、搜索、排序、复制/移动、激活设置”心智，但本项目的普通作者 UI 不应暴露所有底层触发字段。关键词、递归、预算、组内竞争等能力应默认化，并在高级设置或调试视图中展示。

### 写入语义

- 作者手动编辑可以写 draft/canonical，遵守已有确认语义。
- LLM 自动维护写入建议队列，不直接写正史。
- 深度导入是用户确认启动的自动流水线，但只能按写入风险分级自动写入：低风险事实轮廓写 draft/candidate；知识可见性、叙事标签和角色认知进入导入审核建议；任何自动写入都必须保留 provenance、needs_review、rollback 信息。
- 冲突检查不自动改正史，只创建 queue item。

## 深度导入接入方案

### Phase2

Phase2 改为两段式并发：

1. 对每个 Scene 调用 context facade，生成 `ImportContextActivation`。
2. Scene-local LLM 抽取高并发执行，官方 DeepSeek-v4-flash 默认并发 64。
3. 写库、去重、关系融合、checkpoint、memory snapshot 按 `scene_index` 顺序提交。
4. 质量门禁标记问题 Scene 后自动 rerun 一轮。

Scene-local 上下文规则：

- 当前 Scene：完整 `scene_chunks`。
- 前序邻居：默认前 2 个 `NeighborSceneBrief`，rerun 可到前 4 个。
- 前序局部原文：只有共享实体、地点、关系、伏笔、地图焦点或跨章延续强证据时读取。
- 后续 Scene：禁止进入当前 Scene 上下文。
- 跨章 Scene：自身覆盖的 chunks 全部算当前证据。

future evidence 规则：

- 可用于实体去重、别名归并、关系对账、跨章连续性评分、Phase3 总览、伏笔回收链识别。
- 不可回写当前 Scene 的角色知识、读者已知状态、当章事实或 delta 发生时间。
- 若发现前文漏抽重要对象，只能创建补抽建议或触发前文 Scene rerun；rerun 仍使用当时可见上下文。

导入写入风险分级：

- 低风险：CoreEntity、类型 profile draft、关系候选、地图事实候选、World Bible 素材页或 `free_text` 摘录。可自动写入 draft/candidate，`status` 不得直接为 canonical，meta 必须记录 `source="deep_import"`、workflow_id、scene_id/chapter_index、evidence refs、confidence 和 needs_review。
- 低风险 profile 写入仍不是知识推理权威输入；只有作者确认并提升为 canonical 后，才可作为正式 `KnowledgeVisibilityPolicy`、reader safety 或冲突检查的强依据。
- 中风险：系统可推导的公共标签，例如由 profile 明确属性派生的 species/faction/home_location 标签。只有当标签与 CoreEntity/profile 字段完全一致、只影响 public 默认知识、通过 `knowledge_tag_exclusions` 检查且没有叙事专属语义时，才允许自动 upsert derived grant，并标记 `grant_source="derived"`、source_ref=deep_import。
- 高风险：`KnowledgeVisibilityPolicy`、private grant、rule_draft、叙事专属 KnowledgeTag、manual/triggered 标签、CharacterKnowledge 覆写、reader reveal policy。深度导入第一版不得直接写这些表；只能写入导入审核建议。
- Scene 内显式“角色得知某事”也属于高风险角色认知边界。即便有 scene_id 和直接引语，第一版也只生成 `character_knowledge` 建议，附 evidence span、confidence、source_scene_id 和建议 knowledge_level；作者接受后再写 CharacterKnowledge 或 confirmed_suggestion grant。
- 导入审核建议第一版复用 `creation_suggestion_queue`，用 `source_module="imports"`、`review_group="import_knowledge"`、`target_type` 区分 character_tag / character_knowledge / visibility_policy / reader_reveal_policy。若后续需要独立查询性能，可物化为 `import_suggestions` 表，但语义必须与建议队列一致。
- 接受导入建议前必须重新检查 `knowledge_tag_exclusions`、目标资产状态和 novel_id；若与排除或作者锁定标签冲突，建议标记 conflict，不能静默写入。

### Phase3

Phase3 使用作者全知的全书摘要视角，但不默认读取全书正文。

上下文层次：

1. 全量 Scene Brief：全书 Scene 标题、章节跨度、目标、核心冲突、情绪节拍、跨章标记。
2. WorldBackgroundAggregation：世界对象、关系、势力、地点、规则、历史事件、物品、地图事实、人物知识边界、结构资产。
3. 证据抽样 snippets：每条候选剧情线/篇章纲最多 top-k 证据片段。
4. Compact summary：只有预算溢出时对同组低优先级资料做 LLM compact。

Phase3 质量门禁：

- 剧情线必须引用 Scene 或实体。
- 篇章纲必须覆盖明确章节范围。
- fallback 结构资产比例过高时 degraded。
- related_entity_ids 为空比例过高时 rerun。
- 跨章 Scene 没有结构承接时 degraded。

## 自动质量门禁

质量门禁不只看数量。

指标：

- Scene 覆盖率：是否连续空 Scene。
- 实体质量：核心实体重复率、temporary/ignore 比例、候选泛化程度。
- 关系质量：重复边、方向错误、关系类型变体。
- 跨章连续性：跨章 Scene 是否保留，是否在结构中被承接。
- 格式健康：format repair、format conversion、partial list skip 比例。
- compact 健康：compact coverage、omitted reason、uncertainty。
- 结构质量：fallback 比例、引用完整性、剧情线和篇章纲是否真实关联。

门禁动作：

- 单 Scene 问题：自动 rerun 一轮。
- 重复率高：优先去重/融合，不重跑正文抽取。
- 格式问题：优先格式 repair / 格式智能转换，不扩上下文。
- 跨章连续性问题：扩大前序 brief/snippet，不读取未来 Scene。
- Phase3 结构泛化：用全书摘要视角 rerun 一轮。
- 仍失败：标记 degraded，记录可复跑范围。

## 数据模型

完整方案建议新增或扩展：

### CoreEntity typed extension tables

`CoreEntity` 保持世界对象统一身份层；主要 World Bible 类型都需要 1:1 类型扩展表，避免把高频结构化事实只塞进 `world_bible_pages.page_meta_json` 或 `free_text`。

已有扩展表：

- `characters`：人物特有字段。
- `events`：事件来源章节、发生地、时间线顺序、发生时间标签。

第一批强类型扩展表：

- `species_profiles`：种族/物种/血脉的起源、能力边界、生理特征、文化特征、禁忌、分布、寿命/繁衍等。
- `faction_profiles`：势力目标、资源、成员规则、领地摘要、敌友策略、公开立场、秘密计划。
- `location_profiles`：地点层级、地理/空间属性、可达性、环境、危险、地图绑定摘要、所属势力。
- `rule_profiles`：规则适用范围、触发条件、代价、例外、冲突检查语义、违反后果。
- `item_profiles`：物品功能、限制、来源、持有状态、损耗/代价、关联规则、地图位置。
- `secret_profiles`：隐藏真相、揭示计划、读者/角色已知边界、泄露风险、关联伏笔。

第二批及以后先走通用档案：

- `entity_profile_templates`：定义 CoreEntity 类型的字段 schema、展示/校验规则、上下文投影和后续迁移规则。它服务实体档案，不等同于 `World Bible Page Template`；前者定义对象字段，后者定义手册页面组织。
- `generic_entity_profiles`：用于尚未拆强表的类型，例如 group、power_system、resource、legend、concept、creature、skill、other。字段包括 entity_id、novel_id、entity_type、template_key、template_version、data_json、extra_json、status、created_at、updated_at。
- 当某个 generic 类型在查询频率、冲突检查、地图联动、上下文激活或 API 过滤上成熟后，再迁移到独立 profile 表。迁移以 CoreEntity entity_type + template version + data_json 为来源，不改变前端和 AI 引擎的 profile contract。

通用约束：

- 每张扩展表以 `entity_id` 作为 PK + FK 到 `core_entities.id`，并带 `novel_id` 以保持隔离和查询效率。
- 扩展表不重复保存 CoreEntity 的统一身份字段；name、aliases、summary、public_info、hidden_truth、status、provenance 等仍由 CoreEntity 拥有。
- 扩展表只能保存该类型的强结构字段；统一身份字段仍在 `CoreEntity`，关系仍在 `EntityRelation`，地图事实仍在 `map_*`。
- `world_bible_pages.page_meta_json` 保存页面层字段、展示偏好和手册组织字段，不替代类型扩展表。
- 扩展表第一版采用“核心强字段 + `extra_json`”混合形态：高频检索、冲突检查、地图联动、上下文激活、排序和权限/可见性需要的字段必须是强字段；长尾世界观模板字段先进入 `extra_json`。
- 强字段命名保持类型内稳定，服务 API 查询、索引、冲突检查和上下文编译；`extra_json` 是 profile 的半结构化事实孵化区，可服务作者补充设定和低频模板字段，但不作为关键查询唯一来源。
- 当某个 `extra_json` 字段连续进入检索、冲突检查、地图联动或上下文预算决策，应迁移为强字段，并同步模板版本和 projection 规则。
- `extra_json` 仍必须经过模板 schema 校验，不能成为绕过 Pydantic / 类型约束的自由写入口。
- LLM 整理或深度导入生成的高风险字段、canonical 提升和知识连接先进入建议队列；低风险 profile 轮廓可按 Import Write Risk Classifier 写入 draft/candidate。
- 删除或归档 CoreEntity 时扩展表随实体级状态处理；业务运行时不默认 hard delete 正史对象。
- 上层只能通过 world facade / contracts 访问 profile，例如 `get_entity_profile(novel_id, entity_id)`、`list_entity_profiles(novel_id, entity_type, filters)`；调用方不关心数据来自强表还是 `generic_entity_profiles`。

### TargetRef contract

`TargetRef` 是世界事实的统一寻址合约，供可见性、冲突检查、projection、知识标签、知识继承、建议队列和前端高亮共用。它不引入统一 `facts` 主表，而是给现有资产、字段或文本片段提供稳定坐标。

传输层统一使用 JSON 对象：

```json
{
  "target_type": "core_entity",
  "target_id": "character:<uuid>",
  "target_path": "optional.field.path"
}
```

字段语义：

- `target_type`：预定义枚举，表示资产类别。
- `target_id`：该类别下的唯一标识。数据库资产优先使用 UUID；需要包含物理表或类型时使用受控前缀格式，不使用任意自然语言 slug。
- `target_path`：可选，指向资产内部字段、JSON 字段、projection span 或段落。为空表示整个资产。

第一版支持的 `target_type`：

| target_type | 说明 | target_id 格式 |
|-------------|------|----------------|
| `core_entity` | CoreEntity 身份层对象 | `<entity_type>:<entity_uuid>` |
| `profile` | 第一批强类型 profile 表字段 | `<profile_table>:<entity_uuid>` |
| `generic_profile` | `generic_entity_profiles` 承载的对象档案 | `generic:<entity_type>:<entity_uuid>` |
| `relation` | EntityRelation | `<relation_type>:<relation_uuid>` |
| `world_bible_page` | World Bible Page 或页面字段 | `bible:<page_uuid>` |
| `map_fact` | 地图事实、标记、领地、移动约束等 | `map_fact:<fact_uuid>` |
| `projection_span` | projection 中的一段派生上下文 | `projection:<projection_uuid>:span:<span_id>` |
| `event` | Event 扩展对象，仍绑定 CoreEntity event | `event:<entity_uuid>` |
| `character_knowledge` | CharacterKnowledge 记录 | `character_knowledge:<knowledge_uuid>` |
| `structure` | outline 结构资产，例如剧情线、篇章纲、伏笔、揭示 | `<structure_type>:<structure_uuid>` |

`target_path` 语法：

- 基本路径使用点号：`traits.magic_resistance`、`history.origin`。
- 数组索引用方括号：`members[0].name`、`sections[2]`。
- 第一版不执行通配符；`items[*].name` 只作为后续预留，不参与写入校验通过。
- 对文本型资产，`target_path` 可以指向稳定段落或 span，例如 `sections[2]`、`source_spans[3]`。
- 对关系资产，`target_path` 指向关系属性，例如 `terms.military_support`、`status`。

落地约束：

- API、task result、phase artifacts、projection metadata、visibility preview 和前端事件统一传输 TargetRef JSON，不使用临时字符串字段表达事实位置。
- 数据库表可以将 TargetRef 物化为 `target_type` / `target_id` / `target_path` 三列以便索引；这些列必须能无损还原为同一个 TargetRef。
- 需要简写时只允许工具层提供 `TargetRef.to_string()` / `TargetRef.from_string()`，例如 `profile:species_profiles:<uuid>#history.origin`；业务 API 不以简写字符串作为权威 wire shape。
- `TargetValidator` 必须校验 `target_type` 枚举、`target_id` 前缀/UUID 格式、`target_path` 简化路径语法和 novel_id 隔离。
- `target_path` 不得承载业务判断表达式；条件判断属于 visibility policy 的白名单谓词。

### Knowledge visibility model

知识可见性不能在事实字段内嵌角色列表，也不能为每个角色和每个事实预建矩阵。第一版执行“事实来源 + public/tag/private visibility policy + sparse CharacterKnowledge override”的组合模型；rule、implication、trigger 只存草案和预览。

事实来源不新增统一 `facts` 主表。可见性策略通过 TargetRef 挂到现有事实来源或其片段上：

- `CoreEntity` / 类型扩展表字段。
- `EntityRelation`。
- 地图事实。
- `world_bible_page_projections.source_spans_json` 中的片段。
- 重要的 World Bible Page 字段或 free text projection。

建议新增表：

- `knowledge_tags`：知情者标签，字段包括 id、novel_id、tag_key、title、description、source_mode(derived/manual/suggested/triggered)、source_type、source_id、status。
- `character_knowledge_tags`：角色拥有的标签，字段包括 id、novel_id、character_id、tag_id、grant_source(derived/manual/confirmed_suggestion/triggered)、source_ref_type(scene_revision/scene/event/memory/import_workflow/trigger_preview/manual)、source_ref_id、source_scene_id、source_chapter_index、source_memory_id、author_locked、status。
- `knowledge_tag_exclusions`：作者强制某角色不拥有某个自动派生标签，字段包括 id、novel_id、character_id、tag_id、reason、source(manual/system_migration)、created_at；唯一约束为 (novel_id, character_id, tag_id)。
- `asset_knowledge_tags`：事实来源或事实片段需要的标签，字段包括 id、novel_id、target_type、target_id、target_path、tag_id、knowledge_level、status。
- `knowledge_visibility_policies`：TargetRef 的可见性策略，字段包括 id、novel_id、target_type、target_id、target_path、visibility_type(public/tag/private/rule_draft)、policy_json、effective_chapter_index、status。
- `knowledge_visibility_grants`：private 少量直接授权，字段包括 id、novel_id、policy_id、character_id、knowledge_level、known_content、misconception、status。
- `knowledge_implications`：知识继承边草案，字段包括 id、novel_id、source_target_type、source_target_id、target_target_type、target_target_id、relation_type、confidence、status。
- `knowledge_tag_triggers`：剧情触发标签规则草案，字段包括 id、novel_id、trigger_type(enter_location/witness_event/obtain_item/read_text/manual_event)、condition_json、tag_id、grant_level、status。

语义约束：

- `target_type` / `target_id` / `target_path` 是 TargetRef 的物化列；写入时必须通过 TargetValidator。
- `target_path` 用于指向字段或 projection span，例如 `history.origin`、`source_spans[3]`；没有字段级需求时为空，表示整个 target。
- 可见性策略可以挂在整个 target 上，也可以挂在字段/span target 上。字段/span 策略优先于整个资产默认策略；缺失字段/span 策略时继承最近父级 target 策略。
- `visibility_type="public"` 不创建 per-character 行。
- `visibility_type="tag"` 通过 `asset_knowledge_tags` 和已扣除 exclusions 的 `character_knowledge_tags` / EntityRelation 推导角色是否可见。
- `visibility_type="rule_draft"` 的 `policy_json` 只能使用白名单结构化谓词，不能保存或执行任意代码；第一版不参与正式判决，只服务预览。
- `visibility_type="private"` 只能用于少量例外，超过阈值时应提示改用 tag 或 rule_draft。
- `character_knowledge` 保留为稀疏覆盖和误解表达层，优先级高于 tag/private 推导和 rule_draft 预览。
- 深度导入、手册页整理和其他 LLM 批处理不得直接创建 `knowledge_visibility_policies`、`knowledge_visibility_grants` 或 `character_knowledge`。它们只能生成带 evidence refs 的审核建议；作者确认后再由 world facade 写入正式知识表。
- derived 标签由角色档案、类型扩展表和 EntityRelation 自动同步，例如 species、faction membership、home location、profession group；作者选择“移除并永久排除”时创建 `knowledge_tag_exclusions` 记录并删除当前 `character_knowledge_tags` grant，不能只把 grant 标记 inactive。
- derived 标签同步必须先构建候选集合，再执行差集：`final_derived_tags = derived_candidates - excluded_tags(character_id)`；只有差集结果才允许 upsert 到 `character_knowledge_tags`。
- 删除 `knowledge_tag_exclusions` 记录代表作者撤销排除；下次同步可按角色属性重新授予该标签。手工赋予的 manual 标签不受 derived exclusion 自动删除，若作者要撤销 manual 标签，应删除对应 manual grant。
- manual 标签承载叙事专属经历，例如亲历某事件、偷听某次密谈、读过某本书；作者可手动赋予或撤销。
- suggested 标签来自 LLM、深度导入或整理任务，只进入建议队列；作者确认后才转为 confirmed_suggestion grant。
- triggered 标签第一版只作为 `knowledge_tag_triggers` 草案预览，不自动赋予。预览应说明如果触发器启用，哪个角色会因哪个 source scene / chapter / memory 获得哪个标签；若作者确认该建议，实际 grant 写入 `character_knowledge_tags(grant_source="confirmed_suggestion")`，并保留 source_ref 便于后续回滚影响分析。
- `grant_source="triggered"` 预留给第二版自动触发执行；第一版不得在后台静默生成 triggered grant。
- 所有非 manual grant 都必须写来源追踪。`source_ref_type/source_ref_id` 指向触发来源，例如 scene revision、Scene、Event、Memory、导入 workflow 或 trigger preview；`source_scene_id` / `source_chapter_index` 用于 Scene 重写、删除和回滚时做影响查询。
- `author_locked=true` 表示作者显式保留该标签，使其脱离来源生命周期。第一版只作为 UI 和影响提示的锁定标记；第二版启用自动回滚时，未锁定的 event/triggered 衍生 grant 才可自动撤销。
- 查询角色视角上下文时，后端应先收集候选事实来源，再批量加载该角色 tags、关系、private grants 和 CharacterKnowledge，避免 N+1；只有 preview 模式才额外加载 implications 和 triggers。
- `knowledge_implications` 第一版不推导正式可见性，只用于 UI 预览；后续启用时只推导可见性，不自动改写 canonical 事实，继承深度限制为 2 层，并在 diagnostics 中记录 inherited_from。

角色知识标签工作流：

- 自动派生标签旁提供“移除并永久排除”操作；后端创建 `knowledge_tag_exclusions`，并删除当前角色对应的 derived grant。
- 重新添加时不直接修改 derived grant；后端删除对应 exclusion，下次标签同步重新从角色属性派生。
- 排除记录是最高优先级的否定意图，只作用于自动派生标签；若后续需要“仅针对某个事实排除此标签”，再扩展 `scope_target_type/id/path`，第一版不做。
- 不在 `character_knowledge_tags` 上用 `is_active=false` 表达排除。主 grant 表只表达有效授予；否定意图由 exclusion 表独立表达，避免同步任务和可见性查询混淆 manual grant、derived grant 和作者排除。

衍生标签生命周期：

- `knowledge_tag_exclusions` 负责“以后不要自动加这个标签”；grant provenance 负责“这个已授予标签来自哪个事件或 Scene 证据”。
- 事件触发或建议确认产生的标签必须能追溯到 `source_ref_type/source_ref_id`，不能只记录一段自然语言原因。
- 第一版在 Scene 重写、删除或回滚前，只做影响预览：查询 `source_scene_id` / `source_ref_id` 命中的非 manual grant，展示角色、标签、来源、是否 `author_locked`，提示这些衍生标签可能失效。
- 第一版不自动删除这些 grant，避免作者重写章节后想保留叙事结果却被系统清掉。UI 应提供“批量锁定保留”和“手动移除选中标签”。
- 第二版启用自动回滚时，Scene 重写、删除或正式回滚会移除 `grant_source in ("triggered", "confirmed_suggestion")`、来源命中且 `author_locked=false` 的 grant；`author_locked=true` 和 manual grant 永不自动删除。
- 自动回滚结果必须写入操作摘要，包含移除数量、角色/标签摘要、source scene/revision 和可恢复提示；涉及 canonical 资产的批量删除仍需用户确认。

统一可见性检查 contract：

- `check_knowledge_visibility(novel_id, character_id, targets, mode="enabled")` 是 world facade 对 context / writing / UI 暴露的稳定接口。
- `targets` 是 TargetRef JSON 数组，可指向实体、profile 字段、关系、地图事实、World Bible 页面字段或 projection span。
- `mode="enabled"` 第一版只执行 public / tag / private / CharacterKnowledge 覆盖，返回 visible、knowledge_level、effective_source、known_content、misconception、diagnostics。
- `mode="preview"` 在 enabled 结果之外，额外返回 rule_draft、knowledge_implications、knowledge_tag_triggers 如果启用会带来的潜在可见性变化；preview 结果只供 UI 展示，不进入正式 prompt 判决。
- HTTP API 可后续包装该 facade；不要让前端或 imports 直接拼 SQL 判断可见性。

### Reader safety model

读者安全解决的是叙事信息释放节奏，不是角色主观知识。它和 `CharacterKnowledge` / `KnowledgeVisibilityPolicy` 独立建模，最终在上下文编译阶段取交集。

第一版不新增统一 `facts` 主表。读者揭示信息通过 TargetRef 挂到现有事实来源或 projection span 上：

- `CoreEntity` / 类型扩展表字段。
- `EntityRelation`。
- 地图事实。
- `world_bible_page_projections.source_spans_json` 中的片段。
- 重要的 World Bible Page 字段或 free text projection。
- outline / reveal plan 中明确计划揭示的结构资产。

建议新增表：

- `reader_reveal_policies`：TargetRef 的读者揭示策略，字段包括 id、novel_id、target_type、target_id、target_path、reveal_status(unrevealed/partial/revealed)、reveal_chapter_index、reveal_scene_id、reveal_plan_id、public_baseline、known_content、status。

语义约束：

- `reader_safe` 是查询结果，不是表上的全局布尔值。
- `reveal_status="unrevealed"` 或缺少 reader reveal policy 时，读者向输出默认隐藏；`public_baseline=true` 的世界常识例外。
- `reveal_status="partial"` 时，读者向输出只能使用 `known_content` 或对应 projection span 的已揭示版本，不能使用 hidden truth。
- `reveal_status="revealed"` 且 `ReaderProgress.effective_chapter_index >= reveal_chapter_index` 时，才计算为 `reader_safe=true`；如有 `reveal_scene_id`，需要读者进度已越过该 Scene。
- 作者重排章节时，只需要更新 reveal policy 或 reveal plan 映射，不扫描写死的布尔字段。
- 读者向摘要、回顾、旁白、AI 问答和普通预览必须传入 `ReaderProgress`；没有传入时采用保守默认，只返回 public baseline。
- 角色 POV 且面向读者的输出同时执行两道门禁：先按角色可见性得到角色可用版本，再按 reader safety 过滤剧透。

统一读者安全检查 contract：

- `check_reader_safety(novel_id, targets, reader_progress)` 是 world facade 对 context / writing / UI 暴露的稳定接口。
- `reader_progress` 第一版包含 `effective_chapter_index`，可选 `scene_id` / `reveal_plan_id`；预览模式可由作者临时传入任意章节。
- 返回 `reader_safe`、`reveal_status`、`effective_reveal_point`、`visible_content`、`public_baseline`、`diagnostics`。
- HTTP API 获取事实、投影或上下文预览时可以返回计算后的 `reader_safe`，但写入接口不得让前端直接保存 `reader_safe=true/false` 作为权威状态。

### world_bible_pages

存储 World Bible 手册页本身，解决自由正文和页面组织没有明确承载字段的问题。它是页面层，不是第二套正史事实表。

建议字段：

- `id`
- `novel_id`
- `page_type`：固定册页类型或 `custom`。
- `page_key`：同一 novel 内稳定键，例如 `world_basic_background`、`species`、`faction:xxx`、`entity:<entity_id>`、`custom:cultivation_realms`。
- `title`
- `status`：draft / canonical / archived。
- `page_meta_json`：页面元数据模板的当前值，只保存展示、组织、写作状态、关联入口和局部校验提示。
- `free_text`：作者自由正文。
- `linked_asset_refs_json`：关联的 CoreEntity、EntityRelation、地图事实、历史事件、人物知识边界、结构资产、建议项或冲突项引用。
- `activation_defaults_json`：该页进入 AI 参考资料时的默认激活规则摘要，不替代正式 `ContextActivationRule`。
- `template_key`
- `template_version`
- `version_number`：当前已发布手册页版本号，从 1 递增；draft 页面可为 0 或 1。
- `sort_order`
- `created_by`
- `updated_by`
- `created_at`
- `updated_at`

语义约束：

- `free_text` 可长期保存，但不能被当作已结构化正史事实直接参与冲突判定。
- `page_meta_json` 可参与页面检索、导航、上下文预览和建议生成，但不得重复保存 profile 已有事实属性。
- 需要进入正史的新增事实必须进入 CoreEntity profile、EntityRelation、地图事实、人物知识边界或结构资产；AI 从 `free_text` 整理出的内容先进 `creation_suggestion_queue`。
- 若 `free_text` 或 `page_meta_json` 与 profile 强字段 / `extra_json` 表达冲突，冲突检查以 profile 为准，生成“手册正文疑似过期/矛盾”提示或修订建议，不自动覆盖 profile。
- 固定核心册页可由系统初始化，作者不能删除；自定义册页可归档。
- 普通实体详情页不自动创建 `world_bible_pages`；只有存在额外手册正文或特殊模板字段时，才创建 `page_type="entity_extension"` 的实体扩展页。
- `page_meta_json` 只保存页面元数据字段值；字段定义、类型、校验、上下文投影和冲突检查提示来自 `template_key + template_version` 指向的模板。
- `version_number` 只表达当前页面的已发布版本；未发布修改可存在于 page 当前草稿态或独立 pending publish 表达中，但不进入 canonical 上下文。

### world_bible_page_revisions

存储 World Bible Page 的轻量版本历史，语义接近 `writing_drafts` 的章节版本，但粒度是“有意义的手册页发布点”，不是每次自动保存。

建议字段：

- `id`
- `novel_id`
- `page_id`
- `version_number`
- `title`
- `status_snapshot`：revision 创建时页面状态，例如 canonical / archived。
- `page_meta_json`
- `free_text`
- `free_text_hash`
- `linked_asset_refs_json`
- `activation_defaults_json`
- `template_key`
- `template_version`
- `change_summary`
- `diff_summary_json`
- `source_task_id`
- `source_suggestion_ids_json`
- `created_by`
- `created_at`

语义约束：

- 每次 canonical 发布后写入一条完整页面快照，便于回滚、对比和审计。
- 应用 `Page Organization Task` 的页面元数据补全或自由正文整理建议并发布时，也创建 revision，并记录来源 task / suggestion ids。
- 回滚不删除历史、不覆盖旧 revision；回滚是把某个旧 revision 恢复为当前页面后，再创建一个新的 revision。
- revision 保存的是作者页面数据，可以包含完整 `free_text`；LLM phase artifacts 仍不得保存未脱敏原文。
- `novel_id + page_id + version_number` 唯一，版本号从 1 递增。
- revision 不拥有正史事实。回滚手册页不会自动回滚 CoreEntity profile、EntityRelation、地图事实或结构资产，只影响页面元数据、自由正文、关联引用和 activation defaults。
- 恢复旧 revision 后必须重新计算 `free_text_hash`，并按 projection stale / rebuild 流程处理上下文缓存。

版本对比第一版：

- 页面元数据按 `World Bible Page Template` 做字段级 diff，显示字段标签、字段 key、before、after；未知字段按 legacy / custom 展示，不进入上下文投影。
- `free_text` 做段落级文本 diff；不要求语义摘要，不调用 LLM 解释差异。
- `linked_asset_refs_json` 只展示新增、移除和引用类型 / 标题变化，不做复杂语义 diff。
- `activation_defaults_json` 做浅层 key diff，帮助作者判断该页是否改变了默认上下文参与方式。
- `diff_summary_json` 可缓存变更数量、变更字段 key、文本变更段落数和引用增删数量；完整对比仍以 revision 快照即时计算为准。
- diff 过大时前端展示有界预览，并显示 truncated reason；不能因为 diff 太大阻塞回滚或发布。

### world_bible_page_templates

可选的自定义模板表。内置固定模板第一版可先用代码注册表，只有作者创建自定义字段模板时才需要持久化。

建议字段：

- `id`
- `novel_id`
- `template_key`
- `template_version`
- `title`
- `scope`：builtin_override / custom。
- `fields_json`：字段定义、类型、标签、默认值、校验规则和 UI 渲染提示。
- `context_projection_json`：哪些字段进入 AI 参考资料、映射到哪个 `ContextSection`、默认 tier 和可裁剪性。
- `conflict_rules_json`：哪些字段是可检查事实、地图事实、秘密字段、作者备注或叙事风险来源。
- `activation_defaults_json`
- `status`
- `created_at`
- `updated_at`

语义约束：

- 内置模板由代码注册表提供权威默认值；自定义模板不能静默覆盖内置模板，只能创建新 `template_key` 或显式 `builtin_override`。
- `world_bible_pages.page_meta_json` 必须能按对应模板 schema 校验；未知字段保留但标记为 legacy 或 custom，不能直接进入上下文投影。

### world_bible_page_projections

持久化 `free_text` 派生出来的上下文投影，避免每次上下文编译都重新调用 LLM。

建议字段：

- `id`
- `novel_id`
- `page_id`
- `template_key`
- `template_version`
- `free_text_hash`
- `projection_type`：context_brief / style_notes / fact_candidates / excerpt。
- `sensitivity`：author_only / author_safe / public_baseline。
- `content`
- `source_spans_json`
- `reveal_info_json`
- `token_estimate`
- `omitted_reason_json`
- `uncertainty_json`
- `status`：valid / stale / failed。
- `model_info_json`
- `created_at`
- `updated_at`

语义约束：

- 这是派生缓存，不是正史事实；删除后可由 `world_bible_pages.free_text` 重建。
- 保存 `free_text` 时计算 hash；hash 变化后旧 projection 标记 stale，后台重建。
- 短文本 projection 可确定性生成；长文本 projection 才调用 LLM。
- `fact_candidates` projection 只服务建议队列和审查 UI，不能直接进入 canonical。
- `fact_candidates` projection 也不能直接进入创作上下文，避免未确认事实污染正文生成。
- 页面保存接口不得同步等待长文本 LLM projection；长文本 projection 必须走异步任务。
- context 编译可使用旧 valid projection 或有界摘录 fallback，但必须在 section metadata 中暴露 stale/fallback 原因。
- `sensitivity` 不明或来源混合无法拆分时按 `author_only` 处理；projection 生成任务应尽量拆分公开常识、作者安全设定和隐藏真相。
- `reveal_info_json` 只记录揭示位置和已揭示版本；`reader_safe` 在上下文编译或预览时按 ReaderProgress 计算，不持久化为权威布尔字段。

### context_activation_rules

用于存储可调规则。默认规则也应能序列化成同一 contract。

### world_asset_context_snapshots 或缓存

可选。若聚合成本高或需要预览历史，可建立缓存表。第一版也可以按需计算，但 contract 应稳定。

建议字段：

- `id`
- `novel_id`
- `scope`
- `status`
- `source_hash`
- `aggregation_json`
- `token_estimate`
- `created_at`
- `expires_at`

### creation_suggestion_queue

LLM 提出的世界观创设建议。

用于深度导入时，它也承载导入审核建议：

- `source_module`：imports / world_bible / conflict_check / manual。
- `review_group`：import_profile / import_knowledge / import_structure / page_organization。
- `target_type`：profile_field / relation / map_fact / character_tag / character_knowledge / visibility_policy / reader_reveal_policy / structure。
- `payload_json`：建议写入的结构化数据，不直接执行。
- `evidence_refs_json`：scene_id、chapter_index、source span、quote hash、workflow_id；不保存整段未脱敏原文。
- `risk_level`：low / medium / high。
- `status`：pending / accepted / rejected / conflict。

导入审核建议接受时必须通过对应 world facade、TargetValidator、Pydantic schema 和 `knowledge_tag_exclusions` 检查；不得从 queue payload 直接拼 SQL 写正式知识表。

### conflict_check_queue

事实冲突和叙事风险。

注意：数据库 schema 变更必须同步 ORM、Pydantic schema、测试和文档。demo 阶段允许重建开发库，但不能放松 novel_id 隔离和 schema 校验。

## 模块边界

### world

拥有：

- 世界对象、关系、人物知识、地图事实的业务规则。
- 世界观工作台核心 service。
- world facade 中暴露聚合所需稳定接口。

不拥有：

- LLM prompt 编译。
- context token budget。
- imports workflow。

### context

拥有：

- activation rules。
- activation engine。
- context compiler。
- compact step。
- context snapshots。

不拥有：

- 世界对象正史写入规则。
- 深度导入阶段编排。

### imports

拥有：

- 深度导入 workflow。
- Phase artifact、checkpoint、repair、quality stats。
- Phase2/Phase3 调用 context facade 的 adapter。

不拥有：

- 世界观聚合。
- 激活规则持久化。
- world/context 内部 repository/service。

### frontend-console

拥有：

- 世界观工作台 UI。
- AI 参考资料预览。
- 深度导入进度和质量诊断展示。

不拥有：

- 激活规则业务判定。
- compact 事实生成。

## API 形状

尽量复用现有 API。需要新增时建议：

- `GET /api/world/profiles?entity_type=...`
- `GET /api/world/profiles/{entity_id}`
- `GET /api/world/bible/pages`
- `POST /api/world/bible/pages`
- `GET /api/world/bible/pages/{id}`
- `PATCH /api/world/bible/pages/{id}`
- `GET /api/world/bible/templates`
- `POST /api/world/bible/pages/{id}/consistency-check`
- `POST /api/world/bible/pages/{id}/refresh-projection`
- `POST /api/world/bible/pages/{id}/organize`
- `POST /api/world/characters/{character_id}/knowledge-tags/{tag_id}/exclude`
- `DELETE /api/world/characters/{character_id}/knowledge-tags/{tag_id}/exclude`
- `GET /api/world/scenes/{scene_id}/knowledge-tag-impact`
- `POST /api/world/characters/{character_id}/knowledge-tags/{tag_id}/lock`
- `GET /api/context/activation-preview`
- `POST /api/context/confirm`
- `GET /api/world/suggestions`
- `POST /api/world/suggestions/{id}/confirm`
- `GET /api/world/conflicts`
- `POST /api/world/conflicts/{id}/resolve`

上下文预览、AI 参考资料确认、事实/投影读取接口可接受可选 `reader_progress` / `reader_effective_chapter_index`，返回计算后的 `reader_safe`、`effective_reveal_point` 和隐藏原因；写入接口不得接受 `reader_safe` 作为权威存储字段。

深度导入现有 HTTP API 和前端 wire shape 不应因为 Phase2/3 接入而破坏。新增诊断进入 task result / progress / phase artifacts。

## 迁移路径

1. 设计 world/context contracts。
2. 扩展 CoreEntity 类型规范、schema 校验和 LLM 中文类型映射，至少补充 `species` 和 `group`。
3. 增加第一批强 profile 表：species / faction / location / rule / item / secret；现有 `characters` / `events` 保留。
4. 增加 `entity_profile_templates` 和 `generic_entity_profiles`，承载 group / power_system / resource / legend / concept / creature / skill 等未拆强表类型。
5. 增加统一 world profile facade / contracts，屏蔽物理表差异。
6. 固化 Fact Ownership contract：profile 强字段 / `extra_json` 是世界对象事实来源；World Bible Page 只保存 page meta、free_text 和引用；projection 不回写事实。
7. 若已有 `world_bible_pages.structured_fields_json`，迁移为 `page_meta_json`；其中疑似事实属性不得直接保留在页面字段，应转成 profile 字段更新建议或人工迁移任务。
8. 增加 TargetRef contract 和 TargetValidator，统一可见性、冲突、projection、建议队列和前端高亮的事实寻址。
9. 增加 Knowledge visibility model：第一版执行 public/tag/private + CharacterKnowledge 覆盖；rule_draft、knowledge implications、tag triggers 只存草案和预览。
10. 增加 `knowledge_tag_exclusions`，让作者对 derived KnowledgeTag 的排除能跨同步任务持久生效。
11. 扩展 `character_knowledge_tags` grant provenance：source_ref、source_scene/chapter、author_locked；第一版只做 Scene 重写/删除/回滚影响预览和手动锁定，不做自动回滚。
12. 增加 Reader safety model：`reader_reveal_policies` / projection reveal metadata，`reader_safe` 只作为按 ReaderProgress 计算的结果。
13. 增加 `world_bible_pages`、`world_bible_page_revisions` 和内置 `World Bible Page Template` 代码注册表；第一版只支持固定核心模板和通用自定义页，不做自定义模板编辑器。
14. 实现手册页发布、轻量版本历史、版本对比和回滚；回滚通过创建新 revision 完成。
15. 增加 `world_bible_page_projections`，实现短文本确定性 projection、长文本异步 projection 任务和 stale/fallback 诊断。
16. 增加 Page Organization Task，把 `整理此页` 输出写入建议队列和冲突队列，并在 task result 中记录 phase_timeline、quality_stats 和 phase_artifacts。
17. 增加 Import Write Risk Classifier：低风险写 draft/candidate，中风险 derived public tag 条件自动同步，高风险知识连接写导入审核建议。
18. 实现 `WorldBackgroundAggregation` contract 和 world facade 读取接口。
19. 实现 `ContextActivationRule` 默认规则和 activation preview。
20. 将 aggregation 和 projection 编译成 `ContextSection`。
21. 接入 AI 参考资料预览，展示 activation reason、sources、token、sensitivity、computed reader_safe、stale/fallback 和 truncated reason。
22. 接入 Phase3 全书摘要视角。
23. 接入 Phase2 Scene-local activation。
24. 改造 Phase2 两段式并发，默认官方高并发 64。
25. 接入质量门禁和自动 rerun。
26. 完整跑 212 全量 213 章验收，记录详细日志和调参结果。

## 验收标准

世界观：

- 能浏览对象、关系、地图事实、人物知识边界和结构资产。
- 能看到世界背景聚合分组和来源。
- 能预览某个 Scene/map/focus entity 的 AI 参考资料。
- activation reason 可见但不进入 LLM token。
- token 占比和裁剪原因可见。

深度导入：

- Phase2 使用 Scene-local 当前+过去上下文。
- 后续 Scene 不污染当前 Scene 抽取。
- Phase2 LLM 并发默认 64，可自适应降级。
- 写库顺序稳定，去重/融合统计完整。
- Phase3 使用全书摘要视角而不是全书正文。
- 质量门禁能自动 rerun 标记项。
- 212 全量导入中 fallback 剧情线比例下降，related_entity_ids 空值比例下降，核心实体重复率下降，跨章 Scene 结构承接提升。

## 测试计划

后端：

- context activation 单元测试：primary/secondary keyword、scope filters、recursion、inclusion group、budget overflow。
- world background aggregation 测试：分组、source ids、novel_id 隔离、sensitivity 和 reader safety。
- fact ownership 测试：profile 强字段优先于 World Bible free_text / page_meta_json；projection 不回写事实；旧 structured_fields_json 迁移不会把 profile 事实留在 page_meta_json。
- import write risk 测试：CoreEntity/profile 自动写入 draft/candidate；KnowledgeVisibilityPolicy、CharacterKnowledge、叙事专属标签只生成审核建议；derived public tag 通过 exclusion 检查后才自动同步；exclusion 冲突建议标记 conflict。
- knowledge tag sync 测试：derived 标签同步会扣除 exclusions；删除 exclusion 后可重新派生；manual grant 不被 derived exclusion 误删；唯一约束防止重复排除。
- knowledge tag provenance 测试：确认建议写入 source_ref；Scene 重写影响预览只列出来源命中的非 manual grant；author_locked grant 在预览中标注保留；第一版不自动删除。
- compact step 测试：只在溢出时触发、保留 source ids、不新增事实、失败降级。
- Phase2 测试：不读取 future Scene、两段式并发、顺序写库、quality gate rerun。
- Phase3 测试：全书摘要视角、结构引用完整性、fallback 比例门禁。
- facade 边界测试：imports 不跨模块 import world/context 内部实现。

前端：

- AI 参考资料预览展示 activation reason、sources、token、truncated reason。
- 世界观工作台对象/分组/冲突/建议基本流程。
- 深度导入任务结果展示 quality gate、rerun、throttle、compact 诊断。
- 移动宽度验证。

回归：

- imports targeted pytest。
- world/context targeted pytest。
- outline structure tests。
- frontend-console npm test。
- ruff check。
- git diff --check。
- 真实 LLM 小样本验收。
- 212 全量 213 章验收。
