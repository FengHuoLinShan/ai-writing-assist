# E：演化系统详细计划——替代深度导入

V4.0｜设计提案｜代码基线与证据等级同总计划。本文中的类型和新模块为拟议接口，除特别说明外不是已存在实现。

## 1. 替代范围与最终所有权

最终只有 Evolution 负责“理解推进”的运行所有权、批次、重试、恢复、状态提交与进度解释。Imports 保留格式解析、上传校验、章节识别、来源差异和 Writing 适配，不继续拥有 deep_import 的独立推进事实。

保留现有 PostgreSQL worker lease、项目所有权门禁、`AIRunEnvelopeV1`、账户模型连接、Evidence 物化、World/Story 领域命令及人工采用。新模块建议放在 `backend/modules/evolution/`；运行记录能合理迁移或适配现有 `import_workflow_runs` 时优先复用，不机械添加重复 ORM。名称和表结构最终由迁移设计核定。

### 1.1 四种用户任务，一条内部主链

| 用户任务 | 内部模式 | 来源边界 | 预期效果 |
|---|---|---|---|
| 让系统读懂这本书 | bootstrap | 已保存指定来源版本与范围 | 从有限初始信息逐步建立观察和状态 |
| 继续理解新章节 | append | 现有已提交前缀 + 新来源 | 继承前序状态，不重新盲扫全书 |
| 我修改了这里 | revise | 新旧版本差异 + 明确依赖闭包 | 使相关旧产物失效并局部重算 |
| 重新核对这件事 | scoped_recompute | 用户指定对象/命题/范围 | 定向查证、保留其他已完成产物 |

用户看到“读取正文—整理变化—需要决定—理解已更新”，不需要选择抽取 Phase 或手工串联按钮。没有 Scene 时系统先准备场景边界；没有世界对象时从观察开始，不阻塞写作。

## 2. 先修复现有语义风险

### 2.1 观察、变化日志与状态操作不能混为一谈

现有 `ingest_delta_events()` 会把 Delta 组织成 `manual_correction` 的 MemoryEvent。状态归约不能仅保存一条 changes 就宣称位置、实体或关系已更新。V4 定义独立的三层：

- Observation：原文确实出现了什么说法或行为；必须可定位，允许未解析身份。
- Interpretation：系统如何理解观察，可能含竞争解释、推断和不确定性。
- StateOperation：在明确权限与准入资格下，对指定状态做什么操作。

“逐字证据命中”只证明引用定位，不证明该引用一定蕴含解释。角色说“我已杀死某人”可以成为 statement/character_belief；不能仅因这句话存在就产生 objective death operation。

### 2.2 保护人工确认事件

当前 `replace_scene_events()` 按 Scene 的全部事件和序号替换，没有在此函数中过滤人工来源。V4 的替换操作必须明确命名其机器产物代际：

```text
replace_derived_scene_events(
  novel_id, scene_id, producer_family, generation, input_revision,
  owned_event_keys, new_operations, expected_parent_receipt
)
```

允许替换的仅是同一 producer/generation 的派生产物。作者确认、作者修复和已采用事实由独立 authority/source identity 标识，不能因机器输出条数减少、顺序改变或返回空列表而被删除。新证据反驳人工修正时产生争议决定，不直接覆盖。

身份键不能继续把“第几个输出”视为事件身份。使用来源范围、观察身份、操作语义及生产器版本构成稳定键；输出重新排序不改变事件身份。作者确认修复必须在空重跑、部分重跑、分章重排和历史恢复测试中保留。

### 2.3 统一归约语义，而非强行统一所有输出形状

同一契约版本的类型化操作只有一个解释内核。章节和 Scene 允许保留不同投影结构，但截止到同一叙事位置时，核心实体状态、关系、位置和知识必须一致。

建议 `StoryStateReducer` 做纯函数解释；Repository 负责序列化写入，ProjectionService 负责检查点与读取。历史事件通过显式版本 adapter 读取，不在数据库中就地改变其含义。

## 3. 类型契约草案

下面是实现边界说明，不是要求一次建出所有字段。

### 3.1 SourceRevisionRef

```text
novel_id; source_kind; draft_id; content_hash;
chapter_identity; start_offset; end_offset; range_hash;
source_revision; segmentation_version; source_visibility
```

章节序号用于展示与排序，不独自承担不可变来源身份。修改标题、同字数替换、复制工作稿、恢复旧稿和整章删除都必须产生可识别变化。

### 3.2 ObservationEnvelope

```text
observation_id; source_ref; observer_contract_version;
mention_refs[]; predicate_or_description; modality;
speaker_ref?; valid_story_time?; learned_at_position;
evidence_quotes[]; unresolved_parts[]; disposition;
producer_run_id; input_manifest_hash
```

modality 至少区分观察到的事件、角色陈述、信念、假设、作者规划、比喻/非字面表达、不明确。不能因 schema 只能填实体 ID 就让模型伪造 UUID；未解析提及保留可追踪 mention identity。

### 3.3 IdentityResolution

身份解析返回 `reuse / new_candidate / ambiguous / unrelated`，包含同名、别名、类型、证据与候选集合。去重分为：身份去重避免创建影子人物；观察去重避免同一来源同一断言重复记录。已有身份不能导致新的字段观察、反证和来源被跳过。

合并身份时保留别名来源和全部 observation lineage，按领域命令迁移引用；同名不同人、冒名、称号复用保持竞争身份，不能靠相似度阈值直接合并已采用对象。

### 3.4 TypedStateOperation

```text
operation_id; schema_version; operation_kind;
subject_ref; relation_or_field; before_precondition; value;
story_position; valid_time?; knowledge_subject?;
source_observation_ids[]; authority_basis; derivation_version
```

初始操作族：entity.create/update/remove、relation.establish/end、location.observe/move、knowledge.learn/revise/revoke、timeline.assert、causal_constraint.assert。不是为每种文学句式设计一个永久枚举；通用 documentary assertion 可承载尚不能安全投影的观察，但不得冒充已改变状态。

对于未知前值，操作可为 `assert_observed`，不能伪造 before 值。对位置要分“此处出现”与“从甲移动到乙”，后一项只有在移动事实有据时使用。物品 ownership、custody、carried_by 不混为一条关系。

### 3.5 EvolutionReceipt 与游标

```text
run_id; attempt_id; owner_epoch; producer_version;
source_manifest_hash; input_state_receipt; previous_receipt;
observation_dispositions; world_result_refs; story_result_refs;
evidence_result_refs; pending_decisions; coverage;
committed_prefix; blocked_dependencies; paid_call_receipts;
execution_status; outcome_status; freshness
```

Receipt 是跨模块交接证明，不是另存全部世界表。游标只在领域提交成功后推进，模型返回或任务进度到 100% 不足以推进 committed prefix。

## 4. 顺序语义与并行效率

### 4.1 正确的推进顺序

```text
读取冻结原文
  → 准备当前 Scene 的观察任务
  → 编译当前可用前序状态（前一批已提交）
  → 窄任务模型处理与确定性定位
  → 独立复核 / 冲突分流
  → 准备 World/Story/Evidence 写入
  → 短事务内重验来源与 parent receipt
  → 提交操作、来源、回执与推进游标
  → 编译下一 Scene 的依赖状态
```

前一 Scene 未完成的争议不必总是阻塞全书，但后续必须明确继承 unknown/blocked 的依赖，不能继承尚未提交的假结论。若某项身份裁决是后续解释的必要条件，则暂停相关依赖分支，不把其他无关范围一起停止。

### 4.2 可以并行什么

可并行纯来源读取、无副作用解析、当前 Scene 内独立命题的提取与复核、与时间推进无依赖的资料检查、不同小说运行。预取后续正文只提高 I/O 效率，不冻结其依赖前序理解的最终 Prompt。

不允许把所有 Scene 的“当前世界解释”提前冻结，再把顺序落库包装成顺序认知。可把大书分成有依赖的批次屏障，批次内已证明独立的任务并行；必须以 read-set / dependency key 证明，而不是模型自称“可以并行”。

### 4.3 小模型适配

Evidence 为每个窄任务提供最小充分资料、固定身份候选和原文范围。模型负责解释，不负责构造数据库写入、预算或 retry。输出短且有类型；当前 Scene 超出能力时显式分片并记录跨片覆盖，不能静默截断后宣称完整。

引用定位、来源版本、类型、单位、同项目约束、前置条件、矛盾检查先由代码完成；语义蕴含再交独立复核。多 Agent 使用场景见 03，不要求所有 Scene 走昂贵团队。

## 5. 窄事务及运行可靠性

Provider I/O 不在长期数据库事务内执行。每个窄批次的准备阶段收集输入 manifest 和 expected parent；最终提交短事务内锁定当前项目/运行 owner，重验来源、代际和领域写集。沿用项目锁定顺序，避免持有共享锁后升级排他锁形成死锁。

同数据库中的 World 工作变化、Story 事件、Evidence 引用和该批次回执可以组成一个有限 UoW；正文大范围改写、正式世界采用、媒体对象存储不必和它处于同一巨型事务。超范围成果由后续领域确认处理。

### 5.1 三种失败不能使用同一个重试

| 失败位置 | 恢复方式 | 禁止行为 |
|---|---|---|
| Provider 尚未返回，是否计费未知 | 优先读取供应商请求/任务回执；无法判定则标 unknown 并按策略要求确认 | 立即重发整条流水线造成重复计费 |
| Provider 已返回，持久化前失败 | 复用冻结返回内容重新验证；不重新采样模型 | 把数据库错误当模型质量问题重生成 |
| 领域提交完成，响应/投影失败 | 按 operation_id 返回原回执并补投递 | 再次执行领域写入或再次消耗模型预算 |

Root budget 跨重试、requeue、成员和人工恢复累计。并发调用先原子预留额度，再发请求；取消后已发调用可能仍计费，记录实际消耗，不显示“撤销了费用”。成员完成但根任务过期时，禁止晚到结果修改当前状态。

### 5.2 幂等键与 fencing

幂等键建议覆盖 novel、来源范围、输入状态回执、方法版本、任务意图和操作版本，而不是只含章节号。owner_epoch 随切换或重建推进；旧 epoch 的 worker 即使恢复也不能提交。未变化输入返回原 receipt；改变了来源或方法需要新 attempt 并保留旧结果。

## 6. 修改、重排、删除与失效传播

### 6.1 修订影响范围

正文变更先计算物理来源差异，再查询显式依赖；对尚无细粒度依赖的范围，采用保守扩大并向 UI 说明范围。不要以文字相似度证明完整因果影响。

同字数修改和标题变化也需要 source hash；复制、还原、切换当前工作版本意味着 current selection 改变，即使旧版本本身不可变。Scene 切分变化要保存旧新 lineage，不能复用不再匹配的 offsets。重排不仅重写 scene_index，还使依赖顺序的事件、检查点、角色知识与推荐失效。

### 6.2 发布与自动保存

自动保存默认只保存正文、标明变化并合并维护请求。长模型任务在安静窗口或明确授权条件触发，不逐按键运行。发布是正文成熟度变化，不等于语义理解完成；UI 可显示“正文已发布，相关理解待更新”。

统一写入命令须由 API、助手、协作采用、导入、恢复和批量操作消费。提议 `WritingChangeReceipt` 输出旧新 current source、affected chapters、requested effects；领域在同事务记录待投递变化，消费者按幂等键执行。已有 outbox 可扩展为窄协议，不另造泛化全局消息总线。

### 6.3 失效不是删除历史

旧推断标记失效，原观察与历史回执保留。历史首次阅读使用当时合法信息；事后解释可以读取后来的授权证据，但标为 retrospective。认知方法、题目、缩略图、图片和角色外观同样可能剧透，不能只过滤正文。

删除项目则不同：原文、观察、认知、派生索引、媒体引用和缓存都必须按现有删除工作流清理；不能以“追加式历史”为由保留用户已要求永久删除的数据。

## 7. 从旧系统迁移

### 7.1 不可省略的迁移资产分类

| 旧资产/能力 | 去向 | 处理要求 |
|---|---|---|
| 文件解析、章节识别 | Imports 保留 | 不变更已经验证的输入格式边界 |
| 原文 draft/hash/offset | Writing/Evidence 保留 | 不重新编号破坏引用 |
| 场景切分、补全、抽取 adapters | 迁为可调用步骤 | 保留 schema、预算、回读和实际测试，解除旧编排所有权 |
| import_workflow_runs | 迁移或适配为 Evolution legacy run | 历史只读、来源与已消耗预算可查 |
| 旧 deep_import handler/阶段调度 | 最终退役 | 所有新入口转向 Evolution；禁止双提交 |
| 旧 checkpoint | 版本适配器 | 不兼容则明确失效/人工续接，不无条件跳过 |
| manual_correction/Delta | 分级转换 | 有据可转 typed op；仅文献记录；缺依据则未知 |
| 人工确认与采用历史 | 原领域保留 | 不被机器回放删除或重新解释 |
| 旧进度文案与状态 | 兼容读取 | 不把旧 done 当作新版全部维度完成 |

不能因为历史信息已丢失就在 migration 中造出新的“原始证据”。只有真实来源可重读时才能重建；不存在的历史图像也无法凭放大恢复。

### 7.2 六步切换

**E07.a 先修旧链关键保护。** 在新模块开发前补人工事件保护、两视图归约契约测试、观察去重和入口副作用测试，避免迁移期间继续扩大风险。

**E07.b 影子运行。** 新引擎读取同一冻结来源，只保存隔离实验产物；禁止给正式 World/Story 写第二套有效事实。对比 observation disposition、typed state、coverage、实际调用及成本。

**E07.c 项目级 canary。** 为一个测试项目记录 active engine、schema version、owner_epoch。新旧运行不可同时拥有同项目的有效提交权。先排空或显式停止旧 owner，再切换代际。

**E07.d 在途兼容。** 能证明兼容的旧任务按冻结 contract adapter 继续；不兼容的保留费用与成果，提示从可验证批次继续。不得伪装原 task 原地换模型换方法。

**E07.e 入口重定向。** 新用户入口只显示“理解这本书/继续理解”；旧 deep-import API 暂作参数适配，返回真实新回执和 deprecation 提示。旧状态页可读不可启动第二个 owner。

**E08 彻底退役。** 移除旧独立调度、自动重跑策略、重复恢复 owner、旧前端阶段面板及无调用副本；保留历史读取 adapter 到明确的兼容期。完成登记表逐项核销。

### 7.3 回滚不是复活第二套世界

回滚到兼容二进制与已验证 active pointer，提升 epoch，使旧 worker 无权提交。已提交新版本不物理擦除；不能回到不能解释新事件 schema 的旧引擎继续写。必要时停止自动处理、保留只读和正文写作，再通过前向修复恢复。

## 8. 代码落点与包划分

| 包 | 建议位置 | 关键结果 |
|---|---|---|
| E00 | 现有 imports/story/writing tests | 复现与保护、入口副作用清单 |
| E01 | evolution/contracts、observations、sources | 来源与观察外壳，稳定观察 ID |
| E02 | world facade + evolution/identity | 身份去重与观察积累分离 |
| E03 | story/continuity reducer + evolution/commit | 单一语义内核、人工保护、窄提交 |
| E04 | evolution/orchestrator + existing tasks | 前序屏障、有限并行、游标与预算 |
| E05 | Evidence dependencies + evolution/invalidation | 修订、时态、重排、删除影响 |
| E06 | story checkpoints + evolution/recovery | 分页回放、检查点、owner fence |
| E07 | legacy adapters + migration | 影子、canary、在途与回滚 |
| E08 | handlers/frontend/旧文档退役 | 唯一编排所有权、旧代码删除证明 |
| E09 | end-to-end evaluation fixtures | 真实模型、长书、跨模块质量验收 |

## 9. 最小纵切与退出标准

虚构测试小说包含林舟、青竹、白石城、铜钥匙。第 1 个 Scene 建立人物；后续同名观察补充而不重复建人；青竹保管钥匙但所有权不变；林舟的移动与“最后出现”分开。下一 Scene 的输入必须实际包含前一 Scene 的已提交理解。新的独立写作 case 读取相同合法认知，地图展示来源一致的在场和未知。

然后修改前文为同长度文本、调换场景顺序、注入一次作者修复，分别在 provider 返回前、返回后、领域提交后中断。验收最终状态、来源与费用回执，而不是仅比较运行日志或页面有绿色成功条。

必须通过：人工事实不被重跑覆盖；同输入串行/分批/恢复语义一致；不同版本的历史有明确解释；失败不推进 committed prefix；旧 epoch 无权写；原文完整保存；认知和地图实际消费新回执；缺失来源不造假通过。

性能测试以 1k/5k/10k 场景分别测 checkpoint 命中与回放长度；这些是测量档位，不是已证明的性能承诺。长链不逐次全书重算，只有明确依赖和观察账本才能支持可解释的局部恢复。
