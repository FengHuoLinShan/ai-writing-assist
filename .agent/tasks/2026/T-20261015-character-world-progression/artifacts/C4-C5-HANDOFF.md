# C4 / C5 后续批次交接

本文件只记录本次并行执行的切片与接线约束。产品语义以
[主计划](../../../../../docs/plans/2026-10-15-world-object-dossier-and-scene-director.md)、
ADR-0040、ADR-0041 为准；不是新的授权或验收豁免。

## 当前依赖和写入边界

- C0a 代码已在 primary b81ba6887，跨 World/Story/Evidence 回归2978通过；C0b/C2仍在实现。
  C3a已集成后端，C3b界面仍在实施。完整导演启用要等对象聚合/简报与参考维度，不能用旧
  Character.current_*、当前 World 或假资料补历史。纯协议基础可先作为离线切片审查。
- A0b composition/Assistant既有核心、service_keys、main、alembic env由其单一写入者管理；
  后续插件提供纯SPEC与精确接线清单。每阶段同时提供静态trace字段、R0–R4和事务形态。
- C0b可能正在改Story人物卡/Reaction及其schema/task；C3b独占SceneCockpit、ReadingFlow
  和相关前端API。开始前核对当前文件归属，优先新增协议/导演独立模块、router和组件；
  不在这些共享文件并行写。root唯一写TASK；review问题和Git冲突由Sol/high直接修。
- 唯一最终验证解释器是
  `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python`
  （3.14.8/Pydantic2.14.0），配目标树backend cwd。原仓库venv版本不同，不能混用或改golden。

## C4a：共用协议与既有状态试验

- 入口源：`backend/modules/story/observations.py`、`simulation.py`、`rehearsals.py`、
  `continuity/state_trial.py`；验证源：`tests/test_simulation.py`、`tests/test_rehearsals.py`、
  `continuity/tests/test_state_trial.py`及P2-A/B知识边界测试（路径均相对Story）。
- `simulation_v3`统一意图、有限结算、StateDelta、ResolutionBatch和replay；新协议不写
  人物/地点/受众/轮次数量上限。已有身份按对象或地图节点ID；新增候选和文字标签不得
  冒充World地点身份。候选状态不能写World、continuity或正文。
- 先固定现有状态试验与RP回放样例，再迁移共用算法。HTTP状态试验保留接口、条件、
  三值判决、来源/拒绝归因、owner不变和零事件写入；协议版本和方法指纹变化须显式说明，
  不能把实际行为漂移藏进测试预期。与旧结果逐条件比较，不仅检查新实现自己能往返。
- Story停止新建旧排演协议后，旧运行仍按原协议只读，不重解释或迁移旧记录。
  Interaction观察者回合切换须过自己的真实评测；此前RP仍新建observation_v2，入口自身
  max_actors策略仍有效。不要为了统一协议提前切RP或删其安全限制。

## C4b：导演与参考剧本

- 新导演服务读Evidence统一简报；人物意图仅角色可知，导演层作者约束分开。只要无法证明
  某人物可知，不能把作者台账/秘密放进角色packet。人物/素材按上下文预算分组，列出分组
  和省略；不静默截断，不用固定低人数限制回避容量。
- 一次点击默认一轮；连续N轮须显式选择并预览根预算。80%或费用结果未知停止，原根累计
  用量不因暂停/重试重置。新引入的人物/物件/位置只标候选，意图不等于成功。
- 每轮不可变历史保存来源指纹、表演卡、素材、差量、用量和父/同级分支。支持从历史继续与
  依据变化选择；历史只作者删除、30天可恢复，AI目录不得暴露删除历史。
- 参考剧本保存内容副本/素材ID/角度/来源轮次，独立于历史是否删除。不得写SceneScriptFile、
  adopted_scripts或get_scene_story_basis_hash。director_reference只用于Writing生成/定向返修，
  默认关；缺失/陈旧/省略只提示，绝不降低核心KnowledgeScope或替代采用资格。
- C4完整验收仍包括：完整表演卡、区分与套话提示、可感知者标注、素材角度选择、参考保存、
  历史树/恢复、对象一致性，以及前端390/1280、键盘/失败/冲突/旧响应隔离。基础协议通过
  不能冒称导演全完成。

## C5：候选世界推进

- 在同一协议增加自由/导向推进模式；默认一步，参与者默认12可配置，步长/推荐/推进量
  单列。步数由作者选择与根预算约束，不设任意低上限；状态精确差量与滚动叙事摘要分存。
- 交汇检测依据结构化位置、目的地、目标、资源、路线、信息接收者；未知行程不能用示意图
  坐标推物理距离。无地图仅退化到同目的地，明确未核对范围；不交汇也要可行性核对。
- 生死、位置、保留项和作者有效期只读既有结构化事实及受信来源；自然语言不升级为成功
  证据。违反/未定在候选记录中明确，不回写continuity、World、正文或RP知识。
- 钩子经story.plan_structure预览后R3作者采用；人物近况仅作者笔记或作者确认的备注修订。
  势力和方案分支仍等独立路线图阶段1/2，不能读旧无时效字段假装上线。
- 持续推进提醒默认关闭，须根预算和既有持续授权，不自动开启。真实题材质量、长篇前置、
  RP迁移门禁及human_validated=false单列；不得把离线测试或模拟作者当真人验收。

## 审查与下一步

实现按C4a、C4b、C5分批Luna/max提交，逐批Sol/high审查并直接修复；所有必要实现仍属于
原三份计划，不因拆批变成可选项。先收到C0b/C2与C3b可审查提交并检查接口，再启动C4a。
不得重试封存R3、读取holdout或自行增加模型请求；真实评测由root在最终固定代码后重新预检。


## 2026-10-16 当前固定点与剩余C0

- C0b与C3b/C2b已在primary19589fa11（业务a18b80cd5）；root86后端/3专用PG/
  3134前端/lint/build组合通过。C2后端与Generic读写/类型迁移由新的Luna
  dossier_consumers在world-object-dossier-impl从5217f5310恢复，尚未交付。
- C4a Luna实现4cbc97e35已交Sol/high固定点审修，尚未集成。Sol实证typed object/map_node
  没核验owner/novel/真实来源、未知位置observer被视为同地两处问题，正在直接修复与专用PG验证。
  C4b必须从审修后的协议继续。Luna原代码的API/worker多轮409仅为暂时边界，不能保留成最终产品上限。
- 后续C4b独立导演运行/轮次/参考存储，读Evidence统一简报；不要把旧rehearsal记录或
  SceneScriptFile改名冒充导演历史，也不把新导演产物接入adopted_scripts/正文事实依据。
  本文上方完整C4b/C5验收不因基础协议完成而缩减。
- root逐项核对C0发现作者有效期覆盖的项目读规则/默认关闭开关与结构化冲突提醒仍缺；
  有向态度、别名生效区间及项目自定义文字状态字段也要实证盘点，不把注册静态字段或
  DossierValidity锚点过滤当这些能力已实现。C2/Generic首切片后另排C0c，仍属本次范围。
- C1真实长篇前置、M5势力阶段1与RP迁移评测仍未通过；工程可用切片与这些门禁分列。
  R3和holdout封存，不添加模型请求；新真实评测只在最终固定代码及完整预算预检后由root协调。


## 2026-10-16T01:17 当前协议已通过独立审修

- C4a现已在primary b3182b2c5，root1034后端/1专用PG/23Vue/lint/build通过；Luna原4cbc与Sol净fix均保留。身份、seed参与者一致、未知位置观察者及接收者保护已闭合，旧RP/state_trial未迁移协议语义。
- C4b从该审修后协议开始，仍需完整预算/历史/表演/素材/参考/一致性/UI，不保留C4a多轮409作最终限制。C2后端尚在另树自检，拟提供ReactionPreviewV2/ReactionProposalV2每人物2–4 performances完整表演结构，可复用；未获审不能直接当已发布API。
- A2新Luna在map-assistant-review独立实施目标引擎，Assistant现有核心仍由Sol A1组合单写。新migration需最终由Sol串成单head；不要抢写keys/bootstrap/既有Assistant状态机。

## 2026-10-16T01:44 C4b已启动

- Luna/max scene_director在map-assistant-structure/codex/scene-director-impl从ea8889f16（业务b318已审C4a）实施完整导演；primary已到A1审修6a31，后续由Sol统一组合。C2后端仍未固定，不直接依赖未审新符号，现有Evidence三层brief可用。
- 现有公共AIRunEnvelope/new_ai_run_envelope/read_ai_run_envelope/ai_run_scope/managed_step_scope足以承载导演域内累计账本；Goal正在改共享schemas/workflow_budget新版本，导演不并行写。新task/router/migration/纯SPEC/NoticeSource等给精确接线清单，最终由Sol真实装配验证，清单本身不算产品闭环。
- 原有有向态度RelationAttitude已含degree与端点配对基础schema；C0c需核验真实事件/来源/三视角读取，不能再声称完全没有态度模型。作者有效期读规则/开关、别名区间和项目自定义文字状态仍待实现。
