# PLAN v3：小说可信重建、持续认知与沉浸式地图统一实施计划

> 一部小说，一个持续成长的项目；正文与领域资产保有权威，派生理解能够继承，地图成为可查证、可纠正、可返回写作的空间入口。

- 项目：`FengHuoLinShan/ai-writing-assist`
- 整合日期：2026-09-21。
- 输入 C：`PLAN-novel-cognitive-seed-v2.md`，以下简称“认知计划”。
- 输入 V：`PLAN-novel-map-immersive-frontend.md`，以下简称“地图计划”。
- 两份输入共同记录的源码基线：`b5a3ef2e660ddaa65b9bf0ac1ada48f795c53201`。这是继承的核对基线，**不是本次重新查询 main 的结果**。
- 本次交付范围：完整阅读两份输入并整合目标、边界、契约、依赖、实施批次、实验和验收；未修改业务代码、数据库、GitHub 或部署，未运行产品测试或模型实验。
- 标记规则：`[C] §x`、`[V] §x` 指输入计划章节；`Dxx` 是本次为连接两计划提出的整合决策。拟新增文件、表、DTO、开关、测试和接口均是待实现设计。
- 使用关系：本文件作为后续集成实施主计划；原文件在 `sources/` 原样保留。只有明确列入本文件决策表的调整改变原执行顺序或接入方式，其余细化要求继续保留，不以摘要代替原约束。
- 外部依赖说明：C 还引用了 `PLAN-novel-world-reconstruction.md`。该原始文件不是本次两份输入之一；本文件承接 C 已写明的 W 主线要求，不声称逐条复核了该外部文件中的全部细节。W00 开工时仍需按 C 的要求核对原计划与实际调用方。

[C]: sources/PLAN-novel-cognitive-seed-v2.md
[V]: sources/PLAN-novel-map-immersive-frontend.md

## 0. 执行结论与交付导航

本次不是把两个计划首尾相接，而是将它们变成三个各有所有者、共享证据与版本协议的工作面：

| 主线 | 负责的问题 | 不承担的职责 |
|---|---|---|
| **W：可信世界重建** | 每次观察是否保留；状态是否按含义更新；下一 Scene 是否看到前一提交；历史与修订是否正确 | 不因重建成功就自动推进 Canon，不把模型解释当状态操作 |
| **C：持续认知** | 跨任务保留可用理解、未知、解释和方法；新任务能否受益并接受纠正 | 不拥有第二套 World 正史，不绕过 Evidence，不把方法自评当成长证明 |
| **V：沉浸式地图与故事浏览** | 将地图、Scene、人物、物品、来源和修正入口连接起来；让普通作者少做维护 | 不另抽实体、不推测未知路径、不用图片或热点创建事实、不因浏览触发模型 |

三条主线共同形成：

```text
正文 / 作者明确决定
  → W：观察承接 → 身份解析 → 类型化操作 → 有序提交与工作视图
  → C：选择性保留理解 → Evidence 受控消费 → 新任务反馈与修正
  → V：空间 / Scene / 对象投影 → 沉浸浏览 → 查看依据 / 提交纠正
  → 对应领域预览与采用 → 新来源版本 → 重新验证 W / C / V 的适用性
```

这不是要求一次事务同步完成三条链。W 的正确提交不等待 C 的可选整理或 V 的图片处理；依赖过时的结果须在读入口立即退出可用集合，后台再按授权恢复。

**最先并行开展 W00、C00、V00；随后 W01/W02 修观察承接，C01/C02 建跨任务消费，V01～V05 完成已有项目可用的沉浸浏览。** 不让前端等整书认知实验，也不以漂亮画面代替正确重建。

阅读导航：§1～§4 定目标和边界；§5～§7 定接入与重建；§8～§12 定认知、地图、图片和前端；§13～§15 定失效、事务和 API；§16～§18 定用户切片与开发批次；§19～§23 定实验、测试、发布和开工；附录提供完整来源与批次追踪。

## 1. 统一产品目标：只操作小说，不维护系统内部结构

来源：[C] §0、§3、§14；[V] §1、§3、§9。整合决策：D01、D02、D11。

### 1.1 典型用户流程

作者导入正文或继续写作，系统在明确授权的范围内承接变化。作者可以先继续写，不必等待全书整理。打开资料库看到“本书理解”和“需要你决定”；打开地图看到已有地图与可核验的场景关系；点人物或物品能知道信息适用到哪里、有哪些原文依据。

需要修正时，作者表达“这里不是所有权转移，只是暂时保管”。系统先定位相关来源与候选影响，再通过 World/Story/Writing 原属模块的合法命令处理。地图上的卡片不是额外的一套对象编辑主数据。

日常高频动作只要求作者理解地点、人物、章节、来源和待决定事项。record key、commit、scope hash、lease、schema 和图结构只进入诊断抽屉。

### 1.2 “自动维护”的具体含义

自动维护优先包括：确定性失效标记、索引更新、重复待检合并、已授权的派生理解修正和候选准备。它不默认包括正式事实采用、正史对象合并、图片付费生成或跨书数据使用。

未授权后台模型消费时，系统可以标记“资料有更新，尚未重查”，不能为了让状态看起来完整而调用模型。没有值得保存的发现时，`no_change` 是合法结果；不要求每章生成笔记、每次拖动画布记录经验。

作者可以按任务批次处理真正影响后续使用的问题，不必审批每条内部派生笔记；正式资产采用继续保持原确认和权限条件。

### 1.3 完成状态不能压成一个百分比

产品分别显示：来源已读范围、已提交重建游标、待复核事项、作者已采用结果、认知维护进度、地图/图片可用性。

建议文案：

> “已处理至第三章。林舟最后确认在白石城；铜钥匙由青竹保管，所有权未明确。当前地图可浏览，一张地点配图因来源变化待复核。”

不得显示“完整世界已生成”“知识增长 27%”之类无法由真实回执支持的总成绩。地图缺图与事实缺失是不同问题；没有图片并不意味着世界重建失败。

## 2. 继承的仓库基线与必须保留的修复

来源：[C] §1、§2；[V] §2。以下是两份计划记录的源码观察，本次没有重新执行源码审计或生产复现。

### 2.1 W/C 基础

| 输入记录的现状 | 具体位置 / 来源 | 整合后的处理 |
|---|---|---|
| 身份键命中后可能跳过整条新观察；命中 working 对象后附证据即退出 | `imports/entity_extraction/scene_entity_persistence.py::_persist_entities`；C §1.1 | W01/W02 修复；地图与认知只能消费真正承接的新内容，不能用后续总结补遮观察丢失 |
| 并行入口提前准备各 Scene activation | `scene_entity_parallel.py::_process_scenes_parallel_llm`；C §1.1 | W04 在前驱提交后编译依赖前序状态的输入，不能只把并发参数改为 1 |
| 导入 Delta 使用 `manual_correction`，主体依赖 `meta.entity_id` | `story/continuity/services.py::ingest_delta_events`；C §1.1 | W03 增加稳定主体绑定和类型化 reducer；位置投影不直接解释自由文本 Delta |
| `ensure_scene()` 从前缀起点遍历 | `story/continuity/scene_projection.py`；C §1.1 | W06 增量检查点；V 的故事带不在每次切 Scene 时重复扫描全书 |
| Collaboration 已有动态工作图、Grant、Manifest、Recipe、Workspace、角色连接和受控 apply | C §1.2、附录 R09～R14 | C 在既有运行时内增加跨任务生命周期，不重建多 Agent 平台 |
| Evidence 已合并索引与上下文编译，已有完整依赖的 same-scope 转交门禁 | C §1.2、§6.5、§7 | C 和地图 AI 说明均通过同一 Evidence；旧检查不为跨任务共享而删除 |
| Assistant、Interaction、ReadingNode 已有不同形式的记忆 | C §1.2 | 不称当前项目“没有记忆”；新增的是本书派生理解跨任务维护闭环 |
| 已有认知研究与本地试验，但对照存在局限 | C §2 | 恢复旧研究任务，用新材料和公平条件验证，不把旧成绩当新验收 |

### 2.2 V 基础

| 输入记录的现状 | 具体位置 / 来源 | 整合后的处理 |
|---|---|---|
| Vue 岛、bridge、SVG、旧深链均已存在 | `mapIsland.js`、`MapWorkspaceView.vue`；V §2～§4 | 保留入口，提取共享画布与只读观看层 |
| 编辑器已有备份、离开保护、409 对照、候选差异和采用预览 | `MapStructureEditor.vue`；V §2 | 作为硬回归项，不能因改视觉删除 |
| MapDocument v1 限定五类图元，200 features / 400 constraints / 40 images / 100 annotation bindings | `map_structure_schemas.py`；V §2 | 人物、物品及认知提示使用独立读投影，不扩成通用实体图 |
| 结构编辑仅 region/city/district/street | V §2 | world/cover/interior 可图片浏览；不冒称完整空间编辑 |
| 地图/图片采用与 Canon 准入不是同一机制 | V §2.1、§3.2；C §3.4 | 地图继续自有 revision/review；不强行迁入 Canon |
| 对象 full 图最长边 896、上限 256 KiB，thumbnail 192，规范化为 RGB | `world_object_images.py`；V §2、§8 | V05 增加高清/alpha 派生，不靠 CSS 放大 |
| 当前 image_version 替换后旧图会清理；账号配额 20 人物/50 其他对象 | V §2、§8、§13.1 | 当前参考图与历史保留图分开；新保留能力不得被旧 cleanup 误删 |
| SceneContract 不保证可靠地点和完整在场名单 | V §2、§9.1 | Story 提供窄契约；无数据返回 omission，不猜测补满 |
| 当前世界位置不是任意历史位置；路线排演不等于实际旅程 | V §2、§10 | 历史位置使用 W/Story 有据投影；未知路径继续未知 |
| reader-preview 是 owner-only 作者检查工具 | V §2、§12 | 不当公开分享/RP 入口，不复用作者缓存越过读者边界 |

## 3. 两计划的连接与冲突决策

本表是本次新增的整合约定；其后的工程设计以此表为连接规则，不把它们冒充既有实现。

| ID | 连接问题 | 明确决策 | 对原计划的影响 |
|---|---|---|---|
| D01 | 是否建立“一份世界真相”统一所有数据 | 保留领域权威、工作重建、派生认知、视觉配置和观看会话五类身份 | 合并入口与证据协议，不合并存储权威 |
| D02 | 地图是否等待认知种子和整书重建 | V01～V05 可独立上线；Scene 浏览先消费已确认领域资料 | 保留 V 的 M1 价值，W/C 可以并行 |
| D03 | C 的工作理解如何进入地图 | 作者可显式查看“重建工作视图/派生解释”；与正式资料层分开；图元与正式生图仍走原门禁 | 新增只读桥接，不把 W/C 候选提升成 canonical |
| D04 | 多种版本如何保持一致 | 使用一次请求的组合视图引用，分别保存依赖的各版本；不新建全局世界 head | 统一 DTO/快照摘要，不替代各域 CAS |
| D05 | 谁提供人物位置与流转 | Story/continuity 拥有时序状态；World 拥有实体和领域资产；MapExplore 只组装 | 避免 V08 另写 Delta 解释器 |
| D06 | 点击、拖拽、选图是否可作为认知学习证据 | 只作为可选使用反馈；事实/偏好学习需额外语义与授权，浏览不直接触发模型 | 收紧 V→C 的反馈边界 |
| D07 | 谁负责失效与重查 | 领域发出真实来源变更；读入口立即重验；既有 source.changed/watch/任务根合并维护 | 合并重复工作，不新建事件总线或调度器 |
| D08 | 用一个采用批次同时更新 W/C/V 吗 | 原属领域事务各自提交；认知发布、视觉保存、正式采用是不同操作 | 保留 W 原子性，不新增跨三线长事务 |
| D09 | C 能为地图解释提供信息吗 | 可以，但必须经接收任务 Evidence 重新物化；author-full 方法和笔记不得直接给历史/读者 | 新增只读消费，不放宽旧 same-scope 转交 |
| D10 | 图片和热点如何参与事实链 | 图片是展示资产；热点是视觉标注；语义支撑由来源验证，图片不产生独立事实证据 | 高清、配图和历史形象功能不扩张事实权限 |
| D11 | 如何证明整体提升 | W 正确性、C 成长实验、V 操作体验分别验收，再做共同纵向切片 | M1/M2/M3 与 L1/L2/L3/L4 不互相替代 |
| D12 | 如何统一任务编号 | 保留 W00～W08、C00～C06；地图 PR-00～11 改记 V00～V11 | 保留 28 个原有工作包；集成事项嵌入这些包，不另开平台主线 |
| D13 | 要不要让所有 API 经 Evidence | 涉及模型输入、认知、证据和视角的读取走 Evidence；普通已鉴权图片/CRUD 保留原服务 | 不把 Context confirmation 加到纯浏览或手动视觉保存 |
| D14 | 是否开放新的地图历史/读者能力 | 首发作者 Scene 投影；已有安全 reader-preview 保持；新增读者人物图/认知/历史解释需独立完成门禁 | 未实现能力返回不支持/缺项，不回退到作者全量资料 |

## 4. 统一不变量

来源：[C] §3～§9、§10.1；[V] §2.1、§3、§9～§12。

| 不变量 | 可执行含义 |
|---|---|
| 一本书一个隔离根 | 所有对象、任务、认知、地图、图片和缓存绑定 `novel_id` 与 owner；同名不得跨书复用 |
| 正文版本与状态分开 | 来源修订、W generation/游标、Canon、认知 commit、地图 revision、presentation 和 image hash 各自保留 |
| 原文 / 说法 / 信念 / 推断 / 创作候选分开 | 不把人物说法当客观事实，不把暂时保管当所有权，不把相关人物当在场 |
| 未知必须可表示 | 无位置、无路线、无世界时间、未明确身份均保留；不能以随机布局补成事实 |
| 身份复用不丢观察 | 同一 ID 后的新事实、反证、条件和来源有独立处置回执 |
| 依赖状态的输入有提交屏障 | 下一 Scene 的真实输入使用已提交前序状态，不使用提前编译的旧 activation |
| 模型不获得领域写权 | 只能返回有界候选；宿主解析 ID、来源、写入类型和授权 |
| 认知发布不等于 Canon | World Bible 发布仍有正式意义；普通认知不得借其自动持久化 |
| 地图保存不等于世界改变 | 几何/图片布局、Scene 热点与正式事实写入分离 |
| 输入依赖不靠模型自报 | 完整实际读集、形成时点和来源集合由宿主记录；合法 citation ID 不等于语义支撑 |
| 引用过期立即不可用 | 当前读取不等待后台整理；历史可按指定旧来源解释，但不冒充当前有效 |
| 授权、版本、租约一起重验 | 入队、调用前、提交前执行适用的检查；旧 worker/撤权后的任务不得发布 |
| 总预算不因重试重置 | 继承 AIRunEnvelope/既有累计账本；认知维护与团队成员不另开无限额度 |
| 浏览无业务副作用 | GET/点卡片/平移不创建 revision、确认、付费任务或事实；受控遥测不构成领域写入 |
| 只读与试改能力分开 | 认知只读类型不得因加入 ResourceKind 就获得 ResourcePatch 写权限 |
| 图片可见性覆盖像素 | 隐藏文字不能消除图中秘密；整图批准、哈希与视角须服务端判断 |
| 正常归档与数据删除分开 | 任务清理不误删已提升认知/保留图；永久删除覆盖派生、索引、缓存与存储 |
| 形式能力不越级开放 | 不以本次整合启用 `world_assertions` 形式写入，或让地图无适配地消费 Canon manifest |

## 5. 模块职责与依赖方向

来源：[C] §4；[V] §3。整合决策：D01、D05、D07、D13。

| 模块 / 子域 | 原有所有权 | 本次新增或接入 | 禁止扩张 |
|---|---|---|---|
| Imports | 来源规划、抽取、恢复与导入进度 | 观察处置、已提交结果引用、有序接续 | 不直接把认知或地图写成正史 |
| World | 身份、对象、关系、知识、作者采用、Canon | 增量目标提案；地图/媒体仍在 World 内 | 不作为任意认知笔记仓库 |
| Story / continuity | Scene 顺序、状态、投影与重放 | 类型化 reducer、工作代际、SceneMapContext、有限位置/事件读取 | 不把图片布局当时空状态 |
| Writing | 正文版本、修订、候选和采用 | 提供来源变化与可用反馈 | C/V 不绕过 Writing 改正文 |
| Evidence | 来源、检索、Context、权限/视角与回读 | CognitionViewRef 物化、组合依赖、地图解释上下文 | 不拥有新业务调度器 |
| Collaboration / cognition（拟新增内部包） | Run/Case/Workspace/检查与协作 | 本书派生记录、commit、方法版本与维护 | 不保存 API key、不自由 SQL、不跨域直写 |
| World / map（既有子系统） | 地图节点、revision、图片和审核 | Explore 投影、Scene presentation、高清派生 | 不增加第二套实体抽取和状态 reducer |
| Assistant | 交互入口、讨论、watch、提醒与授权 | 就地解释、纠正入口、合并维护信号 | 不存第二份本书认知真相 |
| Project / infrastructure | owner、连接、任务、预算、租约 | 继续提供运行根与组合根 port | 不增加专用模型客户端/常驻调度根 |
| Frontend | 各工作区视图与交互状态 | 共享地图画布、图片加载、理解面板、来源定位 | 不把本机筛选视为读者安全边界 |

依赖方向：Imports/Writing 的已提交来源经公开 port 进入 World/Story；C 接收候选和依赖并由 Evidence 决定可消费内容；V 经 World 自有服务与 Story/Evidence/Collaboration 公开 facade 读取。跨模块不直接导入私有 ORM，不读取 `.agent/` 当小说记忆。

没有必要新增图数据库、向量数据库、LangGraph/CrewAI 平台、通用媒体微服务、全局事件总线或多世界 head。真正新增的是有限生命周期与接入契约。

## 6. 组合视图契约：统一读取语义，不统一所有版本

来源：[C] §3.1、§6～§7；[V] §3.2、§5、§10.2。本节 `NovelExperienceViewRefV1` 是 D04 的拟新增接入形状，不是新的数据库权威表。

### 6.1 最小结构

```text
NovelExperienceViewRefV1
  protocol_version
  novel_id
  consumer                         # 本次请求的服务端注册消费者
  audience                         # author / 受支持的 reader_preview
  knowledge_cutoff                 # 读到哪里；须规定章首/Scene 前后语义
  event_time_query                 # 可空；故事有效时间/区间/偏序查询
  interpretation_mode              # current / historical_first_read / retrospective
  source_manifest_ref              # 本次实际材料版本与集合
  domain_baselines                  # 仅实际依赖的 Writing/World/Story/Canon 引用
  reconstruction_view_ref?          # 保留既有/拟定 EvolutionViewRef 的职责
  cognition_view_ref?               # CognitionViewRef；不是 W 视图别名
  map_revision_ref?
  presentation_revision_ref?
  media_refs?                      # kind + ID + image_version/content_hash
  method_revision_ref?
  authorization_policy_fingerprint # 服务端授权范围摘要；非 bearer token
  request_fingerprint
```

actor/owner 来自会话和运行授权，不信任客户端传入的 owner。`reader_preview` 仅指已实现、通过门禁的作者检查能力；character 与公开读者消费者不能仅靠新增枚举获得权限。

不依赖认知的普通地图浏览可省略 cognition；文风讨论可省略 reconstruction 与 map；不能为所有请求强制装入全套世界快照。与既有协议重复的字段保存引用或摘要，不复制多个独立可变版本；组合指纹引用各域已有 digest，不重新用一套序列化规则替代各域 hash/准入合同。

### 6.2 组合一致性

先从请求解析候选范围，再读取各域明确版本并收集 manifest；验证相互引用和来源是否兼容。返回的画布、侧栏和相关 Scene 使用同一个已解析范围，不在后续组件中私自读取“最新”。

读聚合过程中发现 head/来源漂移时，有界重试或返回 `stale/needs_refresh`；不展示彼此矛盾的半新半旧结果。模型任务在确认时冻结范围，调用前与提交前按原机制重验；UI 的普通读取不因此新增 AI confirmation。

“当前”的解析结果可以随下一次请求更新，“历史首次阅读”必须固定当时的可用来源、认知和方法；无法取得对应历史版本时明确缺项，不能用当前全知笔记填补。

### 6.3 内容、支撑与权限分开

实体 ID 回答“是谁”，revision 回答“哪一版”，`source_ref` 回答“何处支持”，完整 `input_dependencies` 回答“生产者实际看过什么”。四者不能互相替代。

认知内容若接触过后文，哪怕文字看似没有剧透，也不得直接转给早期读者。地图的标题、别名、热点标签、搜索查询、ARIA 文本、导览顺序和方法提示都属于可能泄漏的信息。

反向依赖既记录精确来源，也记录范围集合；“截至第三章未发现所有权转让”的判断会被该范围内的新来源或修订影响。空间邻近、语义相似与“必须重算”依赖分别存储。

### 6.4 既有协议兼容

`InputManifest.protocol=collaboration_v2`、`Recipe.revision=1` 的冻结行为按 C 保留。新增读引用/方法版本应采用新协议和显式 adapter；不能把 JSON 偷加字段后仍称旧版本可精确重放。

`project_team_artifact()` 的同范围检查不变。新的接收任务跨 scope 复用内容时，由 Evidence 在新范围重验并重新物化，不通过删除旧 scope 相等条件来共享。

### 6.5 缓存与派生投影

私有图片 key 至少含 account/project/kind/resource/version/variant/audience/阅读范围；认知和 Explore 缓存另含所用 W/C/领域范围指纹。纯 camera 缓存不依赖认知正文，但仍绑定账号、项目、节点和视图身份。

服务端生成的语义 DTO、图片字节与本机观看状态可以分别缓存；不把作者原始 payload 带到 reader-preview 后再靠 CSS 隐藏。

## 7. W 主线：从观察到可信工作状态

来源：[C] §1.1、§3.3、§10、§12。此处落实 C 已明确的 W 要求；原重建计划未载于 C 的细节仍由 W00 核对，不将本节补充伪称原文。

### 7.1 先修承接，再连接认知与地图

`_persist_entities` 中，身份命中只决定复用哪个身份，不决定丢弃这次观察。每条有效观察至少得到一种可追踪处置：已承接为新证据、形成目标对象增量提案、形成可执行状态操作、保留未解析候选、保留开放解释、或明确拒绝并给原因。

命中 working 对象时，附上来源不足以完成更新；新增字段、条件或命题需要 World 的目标修订提案真正保存。别名/同名消歧不能因 C 的组织合并就改 World 身份。未解析 mention 保留原文位置和候选集合，不能靠模型随意生成 UUID。

`ObservationEnvelope` 的可信外壳承载来源版本、范围、说话者/认识身份和处理回执。可执行 `EvolutionOperation` 是封闭效果集合；新概念暂不能编译时，转有来源的开放记录或候选，而不是直接丢弃或任意执行。

### 7.2 状态 reducer 与原子提交

服务端解析稳定主体，将受支持变化编译为类型化操作。位置变化、保管变化、获得知识与人物说法应有不同语义；C 的自由笔记不能直接充当 reducer 参数。

导入的旧 `manual_correction` 记录用明确 adapter 分流：主体/来源/语义充分的才转换；仅有来源但含义不明确的保留 documentary-only；来源版本不足的保留历史覆盖未知。已被旧代码跳过的内容不能靠迁移凭空恢复。

同一 Scene 批次的世界工作增量、Story 状态操作、必要 Evidence 回执和工作游标在调用方 UoW 内原子提交。保护作者已有事件和 `replace_scene_events` 的边界，稳定锁序；任何 flush/commit 异常传播，不吞掉后标记成功。

图像处理、C 维护和地图画布重绘不进入该原子批次。它们只引用已提交批次身份。

### 7.3 逐 Scene 顺序

```text
冻结 Scene i 的正文/授权/前驱批次
  → 用已提交 S(i-1) 编译输入（可选：合规的 cognition view）
  → 在数据库长事务外调用模型
  → 验证观察/身份/来源/操作
  → 重验来源、前驱、目标版本、confirmation、lease/attempt
  → 原子提交批次 Bi 和 S(i)
  → 编译 Scene i+1 的依赖输入
```

可并行预取不依赖新状态的原文或做独立解析，但不能提前冻结后一 Scene 的状态依赖 activation；调低并发不代替提交屏障。

C 维护可能落后一个或多个批次。后一 Scene 仍可用正确的 W 状态继续，过时认知由 Evidence 排除；不得等待每次认知反思，也不得让旧笔记覆盖新状态。

### 7.4 历史与修订

故事中的制度改变、后来揭露此前事实、人物信念纠正、作者追溯改写，必须产生不同的适用范围。每个工作视图区分事件有效时间、获知游标和来源修订。

前文改写后形成新工作 generation/受影响范围；旧 worker 必须被 fence 拒绝。旧 generation 可按旧来源解释，但不进入当前默认状态。历史显示“当时已知”与“后来重释”是两种查询。

V 的人物/物品历史投影只消费这些明确视图；没有可靠状态能力时返回来源节点和未知，不把当前 `state_assembler` 的位置套到过去。

### 7.5 性能与可靠恢复

最近有效检查点增量推进，索引和投影可以重建；记录检查点读取、序列化、源集合验证、内存与实际回放成本，不承诺整个系统严格 O(N)。W06 按 C 保留 1K/5K/10K Scene 压测，与 V 单图渲染预算分别统计。

模型回执完成、领域提交完成、ACK 到达是不同状态。提交成功但 ACK 丢失返回原回执；仅回执存在但未提交时先重验基线再应用。重试不重新“猜一次”并伪装成同一确定性结果。

## 8. C 主线：可继承理解与方法的独立生命周期

来源：[C] §2～§9、§11、§13、§15。整合新增仅为接入 V 的消费与反馈边界。

### 8.1 数据模型保持最小

在现有 Collaboration 内拟新增 `backend/modules/collaboration/cognition/`，通过现有 contracts/facade 或注册 DI port 对外。初版三类权威记录：

| 拟新增记录 | 主要内容 | 生命周期 |
|---|---|---|
| `novel_cognition_heads` | novel、当前发布 commit、epoch | 每本书一个活动认知 head；不是 Canon head |
| `novel_cognition_commits` | 父 commit、幂等操作、来源/授权回执、增量/digest | 追加式有界提交，不每次复制整书 |
| `novel_cognition_record_revisions` | 稳定 record key、修订链、开放内容、认识身份、来源/依赖、条件与验证引用 | 独立于原 run 的正常清理；退役不原地抹写历史 |

当前选择索引、检索索引和反向依赖可以是可重建投影；需要查询索引时按真实规模选择，不因坚持“三张表”而每次重放全部历史。

当前 CollaborationArtifact 仍可作为候选来源；通过作用域和载荷检查后提升为独立记录。保存必要来源/生成身份，不持久化供应商私有思考、密钥或整段运行秘密。普通 run 清理不能级联删除已提升结果；项目永久删除必须覆盖全部相关数据。

### 8.2 开放内容，稳定可信外壳

人物卡、事件链、条件表、自由笔记、竞争解释、问题组织和工作经验均可作为有界内容。不强制固定 taxonomy，不让一本书的逻辑 schema 自动执行数据库迁移。

字段支撑和完整输入依赖不同。某个句子引用第一章，不代表产出它的模型没看第十章。记录至少区分正文陈述、人物说法/信念、作者说明、模型解释、假设、创作候选与方法。

拆分/合并认知组织不得合并 World 身份；标签相同也不自动成为强依赖。引用多份同源模型总结不能增加独立证据数量。

### 8.3 发布与消费

模型返回 `CognitionPatch` 候选，宿主解析引用、认识身份、基线与依赖。检查 expected head、来源、授权和租约，在短事务中写 revisions、commit 与 head CAS；并发冲突不覆盖，重放同一接受回执不重复生效。

新任务通过 Evidence 召回允许的候选，重验完整依赖与源集合，必要时回读原文，再加入统一 Context 编译。消费回执记录“候选召回”“实际入模”“排除/省略”“原文回读”“方法版本”和 provider 可见指纹；检索到不等于用过，用过不等于产生收益。

首个消费者依旧按 C02 选择 Collaboration 调查，再连接作者问答或写作审稿。地图的“解释此处”是后续消费者，不能成为仅接通 UI 却没有跨任务实际使用的替代验收。

### 8.4 与地图的安全连接

MapObjectDrawer 或 SceneStage 可以就地显示合规派生说明，例如“这里仍有两种身份解释”，并附“系统理解/待复核”标签和来源入口。不得把解释内容写入人物位置、地理名称或正式生图输入。

选中对象只是缩小查询对象，不扩大 grant。点击“解释此处”属于明确 AI 行为，沿已有合法 action/confirmation；普通打开卡片从已物化摘要读取，不自动调用模型。

作者切换 reader-preview 或历史首次阅读时，先清空作者派生 payload，再请求被允许的投影。无法从允许的来源证明独立性时，重新按受限材料生成或不提供，不用“摘要脱敏”规避隐藏输入。

### 8.5 按需维护与反馈

触发可以来自有效已提交观察、作者修订/采用、来源变化、重复查证、失败任务、未决项获得新材料。重复小保存先确定性合并 dirty/待检，不每次反思。可选动作包括不更新、回读、补查反证、保存局部发现、修正解释、调整组织和提出方法试验。

地图中的点击、驻留、相机移动、自动布局不作为世界证据。作者选择一张图只证明这个视觉选择；一次改句只是一条局部反馈，不能自动提炼成全书永久规则。正式采用的新正文构成新作品，不反向证明旧模型推断原本正确。

维护复用 watch/run、冷却、累计用量和期限；撤销授权后旧任务不能提交。可选维护失败不撤销已保存正文，也不能把源任务成功冒充认知已更新。

### 8.6 方法与联合演化

在既有 `revision/deep_review/world_stress/blind_reader/research/import_consult` 等基础 Recipe 能力内，版本化保存查证顺序、问题分解、组织方式和可选模型分工。硬性权限/预算/来源检查留在宿主，不可由方法删除。

方法候选可与结构联合实验，不要求结构先独立证明收益。允许保留未胜出的有界中间候选，但提升默认需要真实质量/成本和不退化观察。每 run 冻结方法与模型快照；恢复不自动换成最新版。

跨模型继承要求实际不同且被授权的连接。只有一个连接时只报告跨会话/跨 run，不用变换角色名称冒充换模型。

## 9. V 的故事读投影：一个入口，两个明确的数据基础

来源：[V] §3、§9～§11；[C] §3、§10。D03～D05 是本节新增整合决策。

### 9.1 已确认资料层先行

M1 只用已有地图和对象 API。V06 的 Story 窄契约先读取已确认 Scene/正文/领域引用，不等待整本 W 完成，也不要求 C 数据存在。

拟在 Story 公开 contracts/facade 导出 `SceneMapContextContract`，字段包含 scene/novel、scene_index、章节映射、location_refs、participant_refs、item_refs、source_manifest/fingerprint 和 omissions。具体内部文件位置在 V00 核对后确定，跨模块消费者不能直接导入 `outline_state` 私有实现。

SceneContract 未保证完整地点与在场名单的部分返回缺项。普通相关性可以显示在侧栏，但不变成在场标记。

### 9.2 工作重建层的有界接入

W03/W04 后，可在作者明确选择“查看重建工作结果”时，以 `reconstruction_view_ref` 为输入取得只读工作投影。显示其 generation、游标、来源版本和未采用标识。

工作投影不是 canonical MapDocument，也不写进当前地图 head；已有地点可通过精确 ID 映射，新地点无法绑定现有有效图元时进入“待定位/待采用”列表。不能为了在图上出现而自动创建正式实体或伪造坐标。

进入现有结构生成/图片生成时，继续仅使用该工作流原本允许且已确认的来源；工作候选需要先合法采用，或另行实现明确隔离的候选预览适配。初版不以 V 的叠加能力绕过 canonical-only 门禁。

派生认知可以解释工作状态，但不能覆盖 reducer 的结构化值。二者不一致时显示来源与待核对，不由前端选择更“可信”的一句话。

### 9.3 MapExploreService 责任

拟新增 `backend/modules/world/map_explore_service.py` 及 schema，组装当前页所需地图 revision、Scene、对象摘要、presence、media refs、允许的派生说明引用和覆盖缺项。

World 地图服务读取 World 自有资产，经 Story facade 取状态，经 Evidence 取受控认知/证据；不直接查 Collaboration cognition ORM。响应携带组合范围指纹和分页游标；一次切 Scene 只读取有界相关集合，禁止平移时重新扫描整书。

原有静态地图用户可在 C/W 未启用时继续使用。请求了明确的历史工作视图却无法提供时，返回不支持/待重建，不能降级成“当前档案位置”。

### 9.4 Presence 与位置类别

| 类别 | 含义 | 展示规则 |
|---|---|---|
| `confirmed_in_scene` | 来源直接支持本 Scene 中出现在该地点 | 仅在对应有效图元上落点 |
| `profile_location` | 当前档案位置 | 仅在当前档案模式显示，不能进入历史 Scene 冒充事实 |
| `last_observed` | 在明确截止范围内最后一次被确认的位置 | 显示“最后确认”，不宣称仍在那里 |
| `related_only` | 与地点/Scene 有关，不能证明位置 | 进入相关卡片，不落位置点 |
| `unknown` | 无足够依据 | 明确未知，不随机摆点 |

记录位置基础是已确认领域资料还是 W 工作视图，不能只靠枚举隐藏未采用性质。存在同范围冲突时返回冲突/待核对项，不挑一条坐标显示成确定状态。

人物在场不自动等于知道；听到不自动等于相信。物品所有者、保管者、携带者分开。只有明确携带关系且时间范围相容时，才能通过人物推导物品所在。

### 9.5 故事带与时间

首发 StoryRibbon 使用 Scene/章节阅读结构；一个 Scene 可以关联多章。倒叙不强行改成递增日期，世界时间未知或偏序时如实显示。

人物旅程先展示有证据的出现节点；两节点之间为“中间路径未知”。既有 `rehearseMapRoute` 作为独立排演，不变成历史事件/最短距离/耗时计算。地图 revision 历史和世界时间回放是不同功能。

角色知识地图、战前战后事实对比、势力范围等继续按 V §13.3 的进入条件，不能因为有画布就提前开放未经验证的状态能力。

## 10. 图片与视觉配置：保留两条资产链，增加必要版本

来源：[V] §8～§9、§12～§13。整合决策：D08、D10、D14。

### 10.1 图片只统一读取，不重建媒体平台

MapAtlasPage 继续持有地图/地点配图字节与派生链；CoreEntity 图片继续持有人物、物品、地点当前形象。前端用 tagged media ref 统一展示：kind、project、resource ID、observedVersion/content_hash、selectionPolicy。不含 S3 key、任意 URL 或 token。

M1/M2 的对象图为 `current` 选择，在历史 Scene 中标“当前形象参考”。MapAtlasPage 可以固定 page/hash；不能把它的 ID 与 entity image ID 混塞入 MapDocument.images。

### 10.2 V05 高清派生规格

保留旧 `thumbnail/full` 兼容，建议新增 `display`：最长边 2048、文件上限 1 MiB，透明 PNG 保留 alpha。以上是继承 V 的起始设计值，需实际样图测试，不是已达到的性能或画质。

上传仍为真实单帧 PNG/JPEG、小于 6 MiB、最大 4096×4096、去元数据。不要为了压到上限不断降低质量而不告知用户；参数需以立绘/物品/复杂背景样例冻结。

同时修改规范化结果、variant 白名单、响应可用规格元数据、存储读写边界、全部 cleanup 枚举、失败补偿、配额并发与项目永久删除。旧图没有 display 时明确回退 full；从已丢失细节的小图不能恢复真实原始清晰度。

MapAtlasPage 增加缩略/展示派生图，绑定原图 hash，不改变原批准 hash 或三点校准。新上传在处理链生成；旧图使用显式有界补齐批次，GET 不临时发起无界转换/任务。

### 10.3 共享私有图片加载

从 `WorldEntityImage.vue` 与地图加载代码提取 `usePrivateMedia`。同 key 去重；缩略先到，选中后展示，明确放大再取大规格；并发初始上限 4，仅有界相邻 Scene 预取。

按引用计数释放 Object URL；账号/项目/audience 切换取消并推进 epoch；迟到解码也重验。Abort 不当损坏，错误不永久缓存，上传失败保留原图。上传回传完整图片版本元数据，不仅改 `has_image=true`。

解码预算与压缩字节分别计量。禁止同时解码所有图层的大图，禁止持久化 blob URL；退出 reader-preview 或授权变化时淘汰不再允许的引用。

### 10.4 Scene presentation 两表

V06 拟新增：

| 表 | 主要字段与约束 |
|---|---|
| `map_scene_presentations` | id、novel_id、node_id、scene_id、current_revision_id；`(novel_id,node_id,scene_id)` 唯一 |
| `map_scene_presentation_revisions` | id、novel_id、presentation_id、base_revision_id、schema_version、有界 document、source_manifest/fingerprint、created_by/at；内容追加式 |

document 只保存已采用背景 page、可选 feature、fit/focal point、hotspots 和白名单视觉配置。热点建议最多 50 个；使用图片内 0..1 有限坐标、稳定热点 ID、实体引用、原图内容 hash 和可选来源。

`visual_annotation` 表示视觉关联，`source_supported` 需要服务端验证源支持；客户端布尔值不能授予后者。JSON 不允许脚本、HTML、任意 URL/CSS 或事实写入命令。

同项目复合约束能用则用；跨模块 Scene 校验经 Story facade，物理外键依既有迁移规则，不由文档假定可直接跨域建 FK。current revision 必须属于同一 presentation/novel。

### 10.5 保存、修订和热点坐标

读当前 revision 与来源基线，编辑独立 presentation draft；提交时重验项目/节点/Scene/page/实体/图片和 base_revision；短事务 CAS、插入新 revision、推进指针。409 保留草稿和差异。

换原图内容后热点待复核；换同图派生分辨率不需重新标点。图片 contain 留白、cover 裁切、横竖图、DPR 必须使用同一内容矩形换算。Scene 分拆/合并、实体归档/合并或图片移出不自动绑定同名替代对象。

保存视觉配置不修改 CoreEntity、正文、Canon 或地图 geometry hash；来源待核对时不毁掉作者布局，保留为待复核配置，不继续作为来源支持展示。

### 10.6 多形象与删除

V09 独立按需求实现 retained-image 记录、variants manifest、保留状态和用途范围。当前形象只有一个权威指针；保留图不被旧 cleanup 清理；配额明确按保留数量/字节计量并事务预占/释放。旧已清理图不可补回。

“适用此 Scene 形象”和“读者可见于某章”是两个条件。衣服、年龄外观或图内人物不自动变成故事事实。删除最后支撑资源时，相关 presentation、认知引用和缓存分别失效，不能为了不可变历史保留应删除字节。

## 11. 前端整合：共享证据入口，不增加系统管理负担

来源：[C] §11 C05、§14；[V] §4～§7、§9。所有下列新文件仍为拟建。

### 11.1 文件清单与责任

| 路径（均在 frontend-console 下） | 操作 | 责任 |
|---|---|---|
| `vue/mapIsland.js` | 保留/窄改 | 原 map 注册、参数与 bridge |
| `vue/views/map/MapWorkspaceView.vue` | 逐项拆分 | 工作台协调、原 run/review 命令、路由与保护 |
| `vue/views/map/MapStructureEditor.vue` | 提取画布 | draft/undo/save/409/恢复/采用继续由其控制 |
| `vue/views/map/mapStructureEditor.js` | 提取纯展示 helper、兼容导出 | 来源、几何、差异和排演语义不变 |
| `vue/views/map/MapViewerShell.vue` | 新增 | 全屏根、布局、overlay host |
| `vue/views/map/MapExplorer.vue` | 新增 | 只读探索，无写 API |
| `vue/views/map/MapCanvas.vue` | 提取/新增 | 纯 props+events 的共享 SVG，无网络 |
| `vue/views/map/useMapCamera.js` | 新增 | 相机变换、安全边距、可打断定位 |
| `vue/views/map/useMapSession.js` | 新增 | 深链、返回栈、scope 恢复与 epoch |
| `vue/views/map/mapViewModel.js` | 新增 | 组合范围到展示 DTO；不推断世界事实 |
| `vue/views/map/MapObjectDrawer.vue` | 新增 | 三类对象卡、来源与就地理解入口 |
| `vue/views/map/MapSceneStage.vue` | 新增 | M1 地点配图；M2 Scene/热点 |
| `vue/views/map/MapStoryRibbon.vue` | V07 新增 | 真实 Scene/章节顺序 |
| `vue/views/map/mapAppearance.css` | 新增 | 地图作用域主题和响应式 |
| `vue/composables/usePrivateMedia.js` | 共享抽取 | 鉴权图片、缓存、并发、释放 |
| `vue/components/media/{PrivateImage,MediaLightbox}.vue` | 新增 | 图片状态、高清查看与焦点 |
| `vue/views/world/components/WorldEntityImage.vue` | 改造 | 调用共享加载器，保留上传/替换 |
| `vue/views/world/cognition/CognitionPanel.vue` | C05 新增 | 本书理解、来源、未决、修正和方法按需展开 |
| `vue/worldIsland.js`、`views/world/WorldView.vue` | C05 接入 | 复用原资料库与审阅入口，不新增认知管理后台 |
| `api.js`、`apiContracts.js` | 分批增量 | 新 variant、组合范围、Explore/presentation/认知读取 |

地图和认知面板复用既有来源定位/对象卡能力或稳定的窄组件。共享的是引用、错误语义和展示身份，不把两个工作区改成一个巨型 Vue 组件。采用 Vue composable/JSDoc，不为本计划迁移 React、全项目 TypeScript 或状态库。

### 11.2 状态必须正交

工作区 explore/edit、舞台 map/illustration/scene、audience、saved/candidate/history、正式资料/重建工作结果是独立维度。全屏不是另一个领域状态，查看认知不是采用。

保留旧 `atlas_view/node_id/page_id/feature_id/revision_id/from_chapter`，新增参数先规定优先级。选中目标使用 tagged ref，不混 feature/entity/scene/record ID。进入子图/Scene 产生导航历史，拖拽缩放仅节流保存会话。

返回栈保存节点、revision、舞台、选择、相机和来源章节；失效 ID 显示不可用并可返回，不按名称替换。本地只存允许的视口和引用，不存私密完整资料、token 或 blob URL。

地图 draft 和 presentation draft 分命名空间，聚合到同一 leave guard。图片查看器不卸载 dirty 编辑控制器；切项目/地图/audience 时取消请求，迟到 HTTP/解码不得覆盖新视图。

### 11.3 全屏行为

MapViewerShell 是唯一全屏根；地图、图片、对象卡、搜索、菜单、来源预览和理解面板在根内。提供已挂载 overlay host，Teleport 指向该宿主，不硬编码 body。

页面沉浸为可靠基础；原生全屏仅由用户操作请求，失败回退；状态来自浏览器实际事件而非前端自报。浏览器退出、Esc、切应用/横竖屏不重置相机。弹层有可见关闭与焦点恢复，不假设能拦截系统 Escape。

尚未支持宿主的旧写入确认框，先明确退出原生全屏再操作，保留位置；不把确认框打开到不可见 body。浏览不保存、不采用、不上传、不调用模型。

### 11.4 镜头、标签与主题

共享 `mapBounds/mapFeatureCenter` 与统一相机，提供 fitBounds、focusFeature、zoomAt、screenToMap、mapToScreen、restoreCamera。画布、命中、标签、热点各用正确且统一的坐标转换；图片内部坐标不能混成地图坐标。

指针锚定缩放；相机定位计算面板安全区；手势可打断动画；后台更新不抢镜头。未知地点进入待定位列表。图上单位不推算千米或耗时。

图层：底色/纹理 → 有效校准底图 → 区域 → 河流道路 → 地点 → 合规故事叠加 → 选择 → 标签/UI。无图也有设计完整的矢量示意，标“不按比例”。

中文长名/混排采用真实字体测量与屏幕空间避碰；选中优先，语义缩放加滞回，聚合不丢搜索对象或产生新世界实体。浅色象牙白/深靛蓝，深色冷蓝紫/少量琥珀，沿用全站主题变量；人物/物品 contain，场景默认完整呈现。

桌面工具条/侧栏初值按 V 保留：56px、详情约 320～360px、故事带约 96～120px；390px 移动视口采用底部抽屉，触控目标建议 44px。尺寸是设计初值，需实机校准。减少动态效果时信息与操作不减少。

## 12. 作者工作流与“超简单操作”的授权设计

来源：[C] §3.4、§8、§14；[V] §9、§13.2。以下意图分流是 D06/D08 的整合设计。

| 作者动作 | 默认行为 | 必须保持的边界 |
|---|---|---|
| “看看白石城” | 已鉴权只读定位/打开配图/列相关 Scene | 不生图、不抽实体、不改变 head |
| “解释这里发生了什么” | 先展示可用来源/理解；明确要求 AI 时走既有确认与预算 | 不把新 AI 请求伪装成 GET |
| “这张图换成另一张” | presentation/当前图片的明确视觉操作 | 不改世界事实、不学习永久风格偏好 |
| “把人物卡挪到右边” | 纯面板布局或视觉热点；就地说明改变的是哪一种 | 不更新人物位置 |
| “这里是保管，不是赠送” | 精确定位待修正命题，给来源和影响预览，再走原领域命令 | 不能只改卡片文字掩盖旧状态错误 |
| “自动整理以后章节” | 配置可持续授权：项目/来源/行为/预算/到期 | 默认不包含正式采用、联网、跨书迁移和付费生图 |
| “补齐本章图片” | 有界缺图清单、候选数量与预算，确认后才入原任务链 | 对象生图未有合法路径时只给上传入口/画面说明 |
| “使用这个新设定” | 原 Writing/World/Story preview/apply/admit | 不顺带采用笔记中的其他解释、热点或候选 |

纯视觉和正式事实含义可能混淆的操作，采用就地预览分开显示效果；不能把任意自然语言命令直接路由成宽权限 patch。

需要作者处理的事项按影响呈现：阻止当前任务正确推进的问题优先；其后是相关来源过期与可能冲突，再是可选缺图或组织建议。具体优先规则是本次 UI 决策，不能让模型热度排序遮住高风险问题。忽略/暂不处理不等于判事实为假。

普通作者不必输入 raw ID 或管理 schema。仍可展开诊断看到数据基础、版本、授权与实际运行回执，以便精确排查。

## 13. 统一失效链：立即限制读取，分线异步修复

来源：[C] §7.5、§8、§10、§15；[V] §8～§10、§16。本节是 D07 的跨计划连接，不新增第二套调度设施。

### 13.1 事务内信号与读取校验

Writing/World/Story 按其真实来源变更接口通知组合根，写入事务内标记所需依赖待检或推进已有失效版本。沿现有 `source.changed`、watch 和任务设施合并后续工作；现有 `domain_outbox` 与采用回执相关，不能未改造就当所有保存事件的通用总线。

即使通知暂未送达或后台维护排队，读取时仍验证当前来源/范围指纹，排除过期结果。后台状态不作为唯一可信校验。消息/任务可以重复，消费按源版本和目标范围幂等；乱序通知不能回退新状态。

### 13.2 失效矩阵

| 变化 | W | C / Evidence | V / 媒体 | 自动处理与作者决定 |
|---|---|---|---|---|
| 新 Scene 批次提交 | 后续以新前驱继续 | 相关查询范围/负结论待重验，可合并维护 | 更新受影响 Scene/presence 的读投影；不重置镜头 | 不自动生成图片或采用候选 |
| 作者追溯改写早期正文 | 新 generation/受影响后缀，旧 worker 拒绝 | 相关记录及方法依赖失效，历史按旧版保留 | 当前位置/Scene 支撑待检；视觉布局保留但不能假装仍有原支撑 | 按授权重建/重查；正式采用单独 |
| 后文揭露旧事实 | 保持当时未知，新增后来的知识/回溯解释 | 首次阅读与事后解释分开版本 | 历史阅读不出现后来地点名/身份/说明 | 不篡改早期理解历史 |
| 人物信念变化 | 更新适用主体与时间 | 解释可修正，不能改成客观世界改变 | 角色视角仅在能力完成后显示 | 不自动迁移到全知层 |
| 正式对象合并/别名变化 | 仅按领域命令的精确映射更新后续引用 | 重验身份相关依赖与索引 | 旧热点/图元引用需要精确迁移或待检，不按名称猜 | 合并权限沿原领域规则 |
| 地图坐标/关系修改 | 不更新 Story 人物状态 | 仅使实际依赖该空间版本的解释待检 | 几何 hash/校准/结构引导图按原规则失效 | 不自动付费重画 |
| presentation 换图/热点移动 | 无世界状态效果 | 仅使实际依赖该视觉配置的任务资料待检 | 原图 hash 变化重核热点；仅位置改变只更新视觉 revision | 不提炼为事实或永久偏好 |
| 同图新增 display 派生尺寸 | 无 | 无语义失效，除非引用方式本身改变 | 更新 variant 元数据；批准 hash/热点/校准不变 | 不重复批准同内容图片 |
| 人物当前图片替换 | 无 | 不影响未消费图片的普通认知 | 当前参考图版本刷新；保留历史图不受当前指针切换影响 | 未保留旧图不可假装可回放 |
| 认知记录/方法退役或修正 | 新任务仅使用可用版本；旧已提交 W 不原地改写 | 当前选择索引和相关派生回执重验 | 只刷新实际显示/依赖的说明，不改变几何 | 不因笔记变化自动重写整书 |
| 来源删除/授权撤销/项目关闭 | 停止相关提交与当前读取 | 禁止当前使用并处理派生留存政策 | 关闭不再允许的图片/说明/搜索缓存 | 撤权不等于所有历史字节已删 |
| 平移/缩放/展开卡片 | 无 | 默认不创建认知/反思任务 | 仅有界本机会话与允许的遥测 | 无 AI 费用和业务写入 |

### 13.3 局部失效与负结论

保守失效允许多查一些，不允许读旧结论的错误窗口；同时记录误失效/重查成本，再细化字段依赖。语义相似或空间邻近不等于强依赖。

“没有找到转让”“没有其他出口”的结论还依赖当时查询集合；新内容进入该集合也必须触发重验，不能只监听已引用段落。新媒体规格不改变这种语义集合，纯视觉更新不应无条件重建 W/C。

### 13.4 当前与历史显示

来源过时可以显示“历史记录/待复核”并提供原版本，但不能把它放入当前事实或默认模型输入。历史像素本身含秘密时，即便关联对象已经过滤，也不能出现在较早 reader-preview。

布局和标签也可能隐含信息；受限投影必须复用原安全图元/依赖闭包，而不是取得 author-full 地图后在客户端删几个点。超出已有 reader-preview 能力的说明/图片默认不显示。

## 14. 采用、发布、保存与运行可靠性

来源：[C] §3.4、§5.4、§6、§10.1；[V] §3.2、§9.3、§11。

### 14.1 五类操作分别有回执

| 操作 | 写入结果 | 授权基础 | 不意味着 |
|---|---|---|---|
| 保存任务产物 | Run/Artifact 的可恢复候选 | 当前 run grant/范围/预算 | 不成为全项目默认理解 |
| 提交 W 工作批次 | 工作增量、状态、游标与来源回执 | 原授权流水线及服务端校验 | 不推进正式 Canon |
| 发布 C 派生 commit | 可受控检索的解释/记录/方法候选 | 持久化派生维护授权与 CAS | 不采用 World Bible，不把假设证明为真 |
| 保存地图/presentation | 地图或视觉新版 | 现有作者写权、基线和资源验证 | 不改正文或世界事实 |
| 采用正式领域成果 | World/Story/Writing 原属资产；需要时原 Canon admission | 原 preview/apply/admit 的明确作者决定 | 不顺带采用所有附带笔记/图层 |

可以用一个用户动作界面协调多个步骤，但每项效果和结果分别呈现；不得显示“全部完成”而实际只有认知发布。正式对象、关系、别名和地图继续使用各自既有确认条件，本计划不普遍降低采用权限。

### 14.2 三个提交边界，不是一笔巨大事务

W 的跨 World/Story/Evidence 原子批次仍由调用方 UoW 负责。C 使用自身短提交发布派生记录，V 使用自身短提交保存视觉配置。它们通过已提交引用关联，没有跨模型/图片 I/O 的长事务。

查询校验和昂贵模型调用分开：冻结输入、checkpoint/释放事务、外部 I/O、重新验来源/授权/目标/租约、短提交。普通 service 不私自 commit；task-only seam 只在现有 Worker 生命周期合同允许时 checkpoint。

### 14.3 幂等和并发

operation ID 绑定接受的输出回执及范围，不按名称或文本 hash 代替业务幂等。ACK 丢失返回原回执；新的模型输出是新候选；C head/map head/工作代际变化均不能通过覆盖旧记录解决。

一张图上传成功但元数据提交失败要执行补偿或可收敛清理；旧 cleanup 删除前再次核验版本是否当前/已保留，避免误删新图。图片可能重复扣费继续使用原状态机的独立确认原因，不因新增 C 维护而自动重试计费。

### 14.4 自动化范围

C 的自动维护不包含正式世界采用；V 的自动缺图清单不包含付费生图。确已存在的作者专项自动采用例外，只在原范围、逐项验证、CAS 和回滚合同内使用，不扩展成“一键整理＝自动全部接受”。

本书通用方法跨书迁移需去除案例内容、独立授权和验证；Interaction/RP 私人分支不反向写作者世界。

## 15. 接口、文件与协议接入清单

来源：[C] §4、§6～§7、§11；[V] §4、§9～§11。未确定的内部路径由基线批次核对，不能借建议文件名宣称仓库已有。

### 15.1 后端改动矩阵

| 位置 | 修改 / 新增 | 对应批次 |
|---|---|---|
| `modules/imports/entity_extraction/scene_entity_persistence.py` | 身份命中与观察承接分离、目标增量和处置回执 | W01/W02 |
| `modules/imports/entity_extraction/scene_entity_parallel.py` | 前驱提交后的输入编译屏障 | W04 |
| `modules/story/continuity/services.py` | 类型化导入状态、旧 adapter、作者事件保护 | W03/W05 |
| `modules/story/continuity/scene_projection.py` | 检查点/工作代际/历史查询 | W05/W06 |
| World 现有 contracts/facade/目标修订服务 | 新观察目标提案、合法采用、精确身份映射 | W01/W02/W07 |
| `modules/collaboration/cognition/{models,contracts,services,repositories}.py`（拟） | 跨 run 认知持久化/生命周期 | C01 |
| `modules/collaboration/cognition/{maintenance,methods}.py`（拟） | 按需维护与方法候选 | C03/C04 |
| `modules/collaboration/{contracts,facade,runtime,recipes}.py` | 新读取协议、方法快照、原能力复用 | C02/C04 |
| `modules/evidence/{facade,creative}.py`、compilation 适配 | 受控认知读取、依赖复验、消费回执 | C02；I01 |
| `modules/evidence/team_projection.py` 调用方 | 保留原 same-scope；跨任务另行物化 | C02 |
| Story 公开 contracts/facade | SceneMapContext 和受支持的历史工作读取 | V06/V08；I01 |
| `modules/world/map_explore_service.py` 及 schema（拟） | 有界只读聚合，无状态 reducer | V06/V08 |
| World map 的 presentation models/service（拟；落点待核对） | 两表、源绑定、CAS 与当前指针 | V06 |
| `modules/world/map_atlas_api.py` 或窄 explore adapter | 保留原路由，新增只读/视觉接口 | V06 |
| `modules/world/world_object_images.py`、原图片路由/清理 | display、alpha、manifest、补偿与兼容 | V05/V09 |
| 现有 MapAtlasPage 图片处理/私有存储链 | 派生规格与原图 hash 保持 | V05 |
| 现有 source.changed 组合根、watch/worker finalizer | 统一失效适配与合并任务，不建调度根 | C03/W06/V10；I02 |
| `backend/evals/novel_cognition.py` 及 tests（拟） | 五条件成长 runner | C00/C04/C06 |

### 15.2 HTTP 增量

继续复用 `/api/world/map-atlas` 下现有 map、map-links、revisions、review-preview、review、reader-preview 和 reader image 接口。现有对象图片 API 扩展可用规格，不重建上传协议。

拟新增的 V 接口保持：

```text
GET  /api/world/map-atlas/{novel_id}/nodes/{node_id}/explore
GET  /api/world/map-atlas/{novel_id}/nodes/{node_id}/scene-presentations/{scene_id}
POST /api/world/map-atlas/{novel_id}/nodes/{node_id}/scene-presentations/{scene_id}/revisions
对象图片：新增 variant=display
地图图片：新增可用缩略/展示规格
```

Explore 可接 scene_id、页游标和受支持的组合视图引用。参数只是请求，不是授权；不允许 client 选择 `author_full` 绕过服务端范围。

C 的持久化/消费优先扩展现有 Collaboration/Evidence facade 和运行入口，作者面板增加窄只读适配。不在本文件虚构一整套已经存在的 `/cognition` API，也不为了接入 C 添加任意资源 patch。

地图“解释此处”“整理当前范围”先匹配已有注册 action 和能力；确需新增 action，先在工具目录、根 capability、预算、confirmation 和测试中登记，再开放入口。

### 15.3 错误与降级

沿 V 保留：404 为不可访问/范围不符，409 为保存基线或来源漂移，422 为不合法配置/引用，503 为暂时读取失败。区分 `no_data`、`unavailable`、`needs_review`、`unsupported_view` 等拟定业务原因，并在 contracts 中统一枚举，不让不同组件猜 HTTP 错误含义。

无认知能力时可明确不显示认知说明；无图片时显示资料板；明确历史查询失败不能回退到当前事实。503 不显示成“没有这个对象”，409 不删除草稿。

## 16. 首个联合纵向切片

来源：[C] §12；[V] §1、§9～§10、§14 PR-00。本节新增联合演示安排，不把新增片段称为原十 Scene fixture 的完整内容。

### 16.1 开发材料与权限

采用 C 已描述的最小连续情境：林舟出现、进入白石城、铜钥匙交给青竹保管。W00 仍恢复原十 Scene fixture 的真实定义；联合新增的修订/视觉轨迹单独标为开发夹具。

V 的区域/城市/两 Scene/三人物/一物品/缺图对象 fixture 可继续作技术 UI 测试，但**其全量数据库准备不能供认知成长试验读取**。成长条件按正文顺序解锁，不提前提供全量人物表、地图秘密或评估 oracle。

### 16.2 验收轨迹

| 步骤 | 系统行为 | 必须留下的证据 |
|---|---|---|
| 1. 读到人物首次出现 | 建立/复用身份，记录原文位置 | 实体处置回执与来源范围 |
| 2. 读到进入白石城 | 重复身份仍承接位置变化，下一输入看到前驱状态 | 原子批次、工作游标、实际输入中的前序状态 |
| 3. 读到钥匙交保管 | 保管者更新，所有权保持未知 | 类型化操作、未知表示、精确支撑 |
| 4. 有选择地保留理解 | 可保留“保管与所有权不同”的解释/方法，也可选择不额外组织 | C 候选/commit 或明确 no_change；不要求固定结构 |
| 5. 结束 run、清空聊天、新建 case | 新任务问保管者/所有权，经 Evidence 取合法积累并可回原文 | 新 case 的真实消费回执，而非复用聊天 |
| 6. 打开沉浸地图 | 显示有效地点、相关 Scene、人物/物品资料；缺图有回退 | 真实 API、无业务写请求/模型调用、返回视野一致 |
| 7. 看工作视图与正式资料 | 已采用层和未采用工作结果标签明确；未知不补点 | 分离的 projection/scope；原地图/Canon 不被改 |
| 8. 作者修订前文 | 旧结论退出当前读取，W/C/V 依赖分别待重验 | 源版本变更、旧 worker 拒绝、当前无过期读窗口 |
| 9. 重新查看历史 | 旧源历史仍按旧语义解释，当前形象不冒充当时形象 | 历史视图版本/方法/读者截止明确 |
| 10. 公平消融 | 相同原文/预算/视觉条件，对照无积累、固定记忆和开放联合条件 | 逐任务质量、来源、成本、失败及人工复核 |

第一条完整体验链是“正文变化 → 可信状态 → 合法理解 → 新 case 使用 → 地图看见 → 作者纠正 → 三线重验”，而不是“导入后卡片数量增加”。

该切片只证明已测范围。没有真实第二模型时不报告跨模型；只有开发 fixture 时不报告整书质量；只有 mocked 全屏时不报告真实设备兼容。

## 17. 统一里程碑与发布依赖

来源：[C] §11.1、§18；[V] §14、§16。里程碑协调不取代各自完成定义。

| 集成里程碑 | 主要工作包 | 可交付成果 | 尚不能宣称 |
|---|---|---|---|
| G0：共同基线与安全协议 | W00 + C00 + V00；I00 | 固定源码/缺陷、测试夹具、公平 runner 协议、边界与依赖表 | 已修复、实验有收益 |
| G1-V：已有项目沉浸浏览 | V01～V05 | 原地图全屏、地点配图、对象高清、稳定返回；等于 V 的 M1 | 历史状态/认知成长已完成 |
| G1-W：重建最小可信链 | W01～W04 | 观察不丢、类型化状态、前驱输入屏障；对应 C 中 L1 范围 | 整书正确性 |
| G1-C：跨任务认知接续 | C01/C02 | 新 case 受控使用合法派生理解；与 W 独立资料也可先测 | 成长有收益/跨模型 |
| G2：地图与可信故事接通 | V06～V08 + 相应 W05/W06/W07 + C03/C05；I01～I03 | 首个联合切片；V 的 M2 与 C 的 L2 分别验收 | 方法演化或所有章节覆盖 |
| G3：有限成长证据 | C04/C06；验证范围所需 W05/W06/W08 | 同材料五条件与纵向真实报告；可能支持 L3，也可能无收益 | 全书/跨书普遍有效 |
| G4：长期使用与可选扩展 | W08/C06 扩围、V09/V10、V11 | 授权整书/跨书试用、保留形象、局部视觉维护；按范围对应 L4/M3 | 从一次试用推断全域成熟 |

G2 的修订轨迹只要求 W06 中来源失效、代际/fence 和最小重建能力先通过；完整 1K/5K/10K 压测仍按实际规模推进，不阻塞 V 的已有资料浏览。

G1-V、G1-W、G1-C 可以不同时间完成。C 的小型公平实验可以在最小安全闭环后开展，不必等全书压测或地图 M2；V 的 M1 不依赖 C02。新增 reader 语义能力保持独立门禁。

建议关键依赖图：

```text
W00 → W01 → W02 → W03 → W04 → W05 / W06 → W07 → W08
C00 → C01 → C02 → C03 → C04 / C05 → C06
V00 → V01 → V02 / V03 / V04
V00 → V05（媒体后端并行）
V00 → V06（先已确认资料的 Scene/presentation）
V02 + V04 + V06 → V07 → V08
W03/W04/W05 → V08 的历史工作状态能力
C02 → 地图可选的合规理解说明（不是 V07 基础浏览的前置）
W03/W04 + C02 → C03 的生产重建反馈接入
V05 + V06 → V09（可选）；既有授权任务能力 + V06/V07 → V10（可选）
各已启用 V 能力 → V11；联合切片分阶段贯穿所有主线
```

箭头表示启用相应能力的依赖，不要求所有文件串行开发。W07 的不同 UI/采用部分可按已稳定合同并行，不在 W06 尚未压完整书时阻止小范围核验。

## 18. 28 个工作包与四项嵌入式集成责任

原 W/C 编号保留，地图原 PR 编号改记 V；所有批次默认“待实施”。下表指定主要文件/任务、退出测试和额外跨线依赖，不把测试拖到最后。

### 18.1 W00～W08

| 包 | 交付与主要位置 | 验收 | 依赖 / 整合点 |
|---|---|---|---|
| W00 | 原计划/实际调用方与十 Scene fixture；导入 DI 入口失败样例；source/作者先验/模型派生分流 | 原失败可重现，权限/未来信息/DB 样例明确；不足不假装通过 | 与 C00/V00 共用源码和证据清单 |
| W01 | ObservationEnvelope、目标增量、处置回执、版本 adapter；World/Imports contracts | 新命题有载荷；未知概念不被丢；模型自报 ID/hash 不直信 | W00；I01 定义可引用批次/视图 |
| W02 | `_persist_entities` 身份缓存修复、同名/别名/候选分流 | 重复出场仍保留观察；不隐式 canonical 合并；精确项目隔离 | W01；为 V 精确实体映射提供基础 |
| W03 | typed reducer、稳定主体、工作代际、事务/锁序、作者事件保护 | 原子批次、重复回执幂等、部分失败回滚、作者事件未覆写 | W01/W02；C/V 只消费已提交引用 |
| W04 | 前驱提交后再编译 activation，限制预取 | 下一实际输入含前序状态；不含未来状态；取消/旧 attempt 拒绝 | W03；C03 生产反馈前置 |
| W05 | 故事时间/获知位置/说法/信念/例外/迟到揭示 | retcon 与故事改制不同；首次阅读与事后解释分开 | W04；V08 历史语义依赖 |
| W06 | 最近检查点、来源改写范围、worker fence、A/B/C 历史兼容、规模测试 | 旧结果不覆盖；有界成本与内存；不可恢复部分标未知 | W04；I02 失效与 C/V 同步 |
| W07 | 章节变化审阅、原文定位、preview/apply/CAS/窄屏恢复 | 保存理解≠采用设定；部分覆盖可见；正史写入按原命令 | W03/W05 的相关合同；与 C05/V 卡片纠正入口接通 |
| W08 | 冻结材料/配置、真实模型、整书性能、回滚和范围上线 | W 候选质量门槛经基线校准；报告失败/未运行 | 前序对应能力；不能用其证明 C 成长 |

### 18.2 C00～C06

| 包 | 交付与主要位置 | 验收 | 依赖 / 整合点 |
|---|---|---|---|
| C00 | 恢复已有 cognitive-seed-research；新增 eval runner/tests；新材料、oracle 隔离与公平预算 | scripted 轨迹可重放，未知答案/未来文本不可见；默认 quality_claim_allowed=false | 与 W00/V00 并行；UI fixture 与成长材料隔离 |
| C01 | cognition 三类记录、metadata/迁移、独立提升、索引、删除策略 | 跨 case 复用、head CAS、幂等、run cleanup 不误删、真实 PG | C00；可与 W01/W02 并行 |
| C02 | Evidence cognition 读取/manifest 版本/消费回执；保持 team scope 门禁 | 新 case 的实际入模可查；隐藏依赖不通过；旧协议可恢复 | C01；接 W 时使用 W01 视图，普通资料不必等 W04 |
| C03 | maintenance/source.changed/watch/finalizer；局部修正、no_change、去重触发 | 小保存不无限反思；撤权/旧 worker 拒绝；源成功不被维护失败撤销 | C02；生产 W 反馈需 W03/W04；I02 |
| C04 | Recipe/方法修订、开放组织 patch、隔离联合实验 | 可回读/不写/局部改；候选不自动默认；不能删硬检查；旧 run 冻结 | C00～C03 最小安全闭环；实验不等整书 |
| C05 | WorldView/CognitionPanel、范围/依据/未决/修正/暂停、正式提案入口 | 无 raw ID 管理要求；晚到不串书；窄屏恢复；身份清晰 | C02/C03；正式采用部分需 W07；地图只复用展示引用 |
| C06 | 五条件纵向真实验证、人工核查、错误经验/换模型/成本/跨题材 | 硬门禁先过，逐任务收益与波动；未授权/未运行明确记录 | C00～C05 相应能力及材料范围内的 W；I03 |

### 18.3 V00～V11（对应地图原 PR-00～PR-11）

| 包 | 交付与主要位置 | 验收 | 依赖 / 整合点 |
|---|---|---|---|
| V00 | 源码差异、原地图/图片测试、unified-map UI fixture、隐藏/过期/容量数据 | 原功能失败基线保留；作者首发/不扩配额；成长实验不读 UI 全量夹具 | 与 W00/C00 共用基线；I00 |
| V01 | MapCanvas/MapExplorer 提取；旧编辑器继续用共享画布 | doc 序列化不变；编辑/撤销/恢复/采用通过；探索无写请求 | V00 |
| V02 | Shell/fullscreen/overlay host/session/deep-link/leave guard | 全屏卡片/图片/子图往返，拒绝回退、Esc、窄屏、跨项目隔离 | V01 |
| V03 | camera/labels/theme/safe insets/减少动态效果 | 坐标不漂移、选中可读、搜索不因聚合丢失、容量记录 | V01；与 V02/V04 可并行 |
| V04 | usePrivateMedia/WorldEntityImage/对象卡/地点 Stage/Lightbox | 去重/abort/替换/释放/迟到解码/范围缓存；无自动生图 | V01；V05 的 display 可后接 |
| V05 | display/alpha/地图派生/manifest/全部 cleanup 与补偿 | 透明与配额边界、旧图回退、旧客户端可用、失败保原图 | V00 后媒体后端可并行；M1 必须完成 |
| V06 | Story 窄契约、Explore、两张 presentation 表/接口/CAS | 不猜地点/在场；跨项目拒绝；换图失效；保存不改世界/几何/正文 | V00；I01/I02；已确认资料接入不强制依赖 W |
| V07 | SceneStage 热点/StoryRibbon/人物物品/正文返回 | 一 Scene 多章、缺图、横竖图、当前参考身份、完整返回链 | V02/V04/V06；C 说明可选 |
| V08 | presence/有据旅程/物品事件/阅读隔离 | 当前位置不冒充过去；路径未知；所有权≠携带；旧 reader 不退化 | V06/V07；历史 W 能力需 W03/W04/W05，修订恢复需 W06 对应部分；I01/I03 |
| V09 | retained-image/单一当前指针/保留配额与 cleanup | 旧清理不误删保留图；并发不超额；删除与历史引用明确 | V05/V06；可选不阻塞 M2 |
| V10 | 按范围缺图清单、候选维护、预算、原任务/导览 | 无隐式费用/采用；部分成功/取消/恢复；任务进度真实 | V06/V07+相应既有任务；C/W 反馈按启用范围接入 |
| V11 | 扩大设备/容量/长期内存矩阵、文档与发布 | 新旧同数据；关闭 viewer 不丢 presentation；存储/DB 可独立回退 | 已启用 V 功能；V09/V10 未选时不虚构必需依赖 |

### 18.4 嵌入式集成责任，不另开四套基础设施

| 责任 | 落入现有工作包 | 必须交付 |
|---|---|---|
| I00：共同基线与材料隔离 | W00/C00/V00 | 同 SHA、能力矩阵、共享测试身份规则、开发/验收/oracle 隔离、原计划外部依赖清单 |
| I01：组合视图与只读投影 | W01/C02/V06/V08 | 版本兼容表、语义游标、Scene 公开读接口、工作/正式层分离、scope 驱动缓存 |
| I02：来源变更与恢复 | W06/C03/V06/V10 | §13 失效矩阵对应的真实 source.changed 接入、乱序/重复/撤权/旧 worker 用例 |
| I03：联合切片与独立证明 | W07/W08/C05/C06/V07/V08/V11 | §16 的可复核轨迹；W/C/V 分别报告，图像/人力/模型成本不混淆 |

由一位集成人负责跨模块契约、迁移、UoW 和验证证据。W 负责人维护 reducer/导入顺序；C 负责人维护 Evidence 接入和认知生命周期；V 前后端分别负责观看与媒体/视觉配置。MapWorkspaceView、MapStructureEditor、Collaboration contracts/runtime 同时修改时按冻结接口分批合并，避免多分支自由文本约定。

## 19. 成长实验：W 正确性、C 收益与 V 易用性分开测

来源：[C] §2、§13、§18；[V] §15。D11 新增控制视觉条件与跨线成本口径。

### 19.1 继承旧研究，但不复用旧题当留出集

恢复 `.agent/tasks/2026/T-20260912-cognitive-seed-research/` 的实际研究记录。C 记录旧 v3 本地试验有 15 次请求，有限题中自由记忆 19/20、原文条件 16/20、恒答 no 也为 16/20；构建成本和原文回读条件不公平。这是输入计划转述的历史研究，本次没有重跑，不能作为本次收益证据。

继承的失败类别包括：条件保存正确但使用错误、理由引用未来资料、作者修订被误归为台词、漏合取条件、编号合法但原文不支持。旧 r17/r29/r43/r61 与已知 oracle 只作开发诊断，新材料改变人物、条件组合、叙述和问题。

### 19.2 五条件保持强对照

| 条件 | 持久内容 | 组织是否可演化 | 方法是否可演化 |
|---|---|---|---|
| A：原文/正常工具 | 无跨任务认知，保留必要执行记录 | 不适用 | 固定 |
| B：固定表示+固定方法 | 完整合理的人物/事件/关系/时间/视角记忆，内容可更新 | schema 固定 | 固定 |
| C：开放表示+固定方法 | 同来源权限的持久记忆 | 可调整粒度/组织/关系 | 固定 |
| D：固定表示+可调方法 | 与 B 同等表示能力 | 固定 | 可调整查证/分解/工作图 |
| E：开放表示+可调方法 | 自主组织派生理解 | 可调整 | 可调整 |

固定表示不等于冻结事实，也不能故意去掉时间/人物知识使 B 变弱。修复前后差异先记为 W 工程收益；多模型与更多计算是独立变量，不能只让 E 获得。

### 19.3 公平条件与地图变量

所有组相同已解锁原文、作者说明、修订、工具权限、问题与预算，均可回读来源。认知移除消融保留原文并允许在同预算重建，计入重建成本。

比较 C 时，V 界面、可用图片、Scene/地图资料权限保持相同；不能只给实验组完整地图、已知对象表或更有信息的导览。比较 V 时，底层状态/认知答案固定，以操作完成、来源核对和恢复负担为主，不把更好的模型回答算成界面收益。

所有模型输入均计形成时点：方法、标题、查询、任务提示、地图说明和组织结构也不能透露未来。全书读完后解释前文另立 retrospective 条件，不伪装首次阅读。

### 19.4 两条纵向路径

固定材料按顺序解锁，在相同检查点接受同任务。创作/修订长期轨迹允许正文分化，但比较时复制相同来源版本做配对任务，自由创作结果另报告，不把不同任务难度当记忆优势。

先用原十 Scene fixture 验证工程；再用全新连续短篇与四类修订轨迹执行约 20～40 个交错任务，再扩展已授权连续章节/整书。此规模只是原型起点，不保证统计充分性。

### 19.5 指标与独立核查

同时报告任务完成、来源实际支持、条件/说话者/时态、未知处理、纠错和历史保留、跨 case/run/模型继承、结构/方法消融、人物/情节/表达质量、人工修改负担、总成本与失败重试。

平衡肯定、否定、未知和人物已知/未知问题，区分必要/充分/充要/伴随条件；不能恒答 unknown、少写正文或回避推进来取高一致性。记忆中已有正确内容但回答错误，单列读取选择/推理使用/验证问题，不统称忘记。

自动工具检查 ID、范围、协议、版本和权限；语义支撑与核心金标要人工或独立复核，记录分歧。评分器/oracle 不向被测工具开放，测试答案不能回流维护后再反复作为未知题。固定条件多次运行，逐任务报告波动，样本足够才计算配对区间。

没有测出收益时保留实验身份，不写“成长提高 X%”。V 的美观和点击次数不能证明 C 成长；C 的少出错也不能掩盖创作同质化或作者负担增加。

## 20. 工程测试、观测与性能预算

来源：[C] §16、§13.5、§15.3；[V] §15。下列新增测试名是待实现建议，不是仓库已存在/已通过的用例。

### 20.1 跨线核心测试矩阵

| 场景 / 拟定测试 | 层次 | 必须证明 |
|---|---|---|
| `test_repeated_identity_keeps_new_observations` | Imports/World | 重复身份不丢新命题/反证/来源 |
| `test_next_scene_uses_committed_state` | W 输入链 | 实际入模含已提交前驱，未来不可见 |
| `test_work_batch_is_atomic_and_preserves_author_events` | 真实 PostgreSQL | W 部分失败回滚、作者事件不覆盖 |
| `test_working_projection_does_not_advance_canon_or_map_head` | W/V | 工作预览不提升正式资产/地图 |
| `test_cognition_survives_run_cleanup` | PG/生命周期 | 已提升认知独立于 run 正常清理 |
| `test_cognition_commit_cas_and_idempotency` | PG/并发 | CAS、同回执、旧 lease/attempt 正确 |
| `test_new_case_reads_cognition_through_evidence` | C 闭环 | 新 case 真正消费合法记录并可回读 |
| `test_cognition_rechecks_all_input_dependencies` | Evidence | 不能只过滤模型自报引用 |
| `test_future_method_is_not_historical_reader_input` | Evidence | 方法/标题/查询也是未来信息通道 |
| `test_new_source_invalidates_negative_finding` | 失效 | 新增来源影响原未发现结论 |
| `test_retcon_differs_from_in_story_rule_change` | W/C/V | 修订与故事事件的影响范围不同 |
| `test_source_change_blocks_stale_explore_before_maintenance` | 集成 | 后台未完成也无当前错误读窗口 |
| `test_optional_cognition_failure_keeps_committed_scene` | 集成 | 可选维护失败不撤销源成功 |
| `test_method_cannot_remove_required_checks` | C | 方法不能授予权限/删检查 |
| `test_oracle_and_future_text_are_unavailable` | eval | 原文工具/文件/地图夹具均无答案泄漏 |
| `test_scene_presence_does_not_use_current_profile_as_history` | Story/MapExplore | 当前档案不冒充过去 |
| `test_item_custody_is_not_ownership_or_carrying` | W/V | 三类关系不同，不伪造物品位置 |
| `test_presentation_save_does_not_write_world_facts` | PG/V | 只改视觉版本，geometry/World/Writing 不变 |
| `test_hotspot_rechecks_background_content_hash` | V/media | 换内容待检，换尺寸不重标 |
| `test_retained_image_is_not_deleted_by_current_cleanup` | 存储/PG | 保留图与新图不被旧任务删除 |
| `test_reader_projection_clears_author_media_and_labels` | 服务端/浏览器 | 搜索/ARIA/说明/像素/缓存皆受限 |
| `test_explore_navigation_has_no_business_writes_or_llm_calls` | 浏览器/服务 | 浏览不发写库/生成/确认请求 |
| `test_reader_or_historical_view_never_falls_back_to_author_current` | 集成 | 不支持或失败时不扩大范围 |
| `test_revoked_watch_cannot_publish_late_result` | Worker/PG | 撤权/旧 worker 不能发布 C/V 候选 |

### 20.2 现有测试和新增前端测试

保留 `e2e/map-atlas.spec.js`、`e2e/map-structure.spec.js`、`world/tests/test_map_structure.py` 与图片/导入/Story/Collaboration/Evidence 套件。新增 `map-explorer.spec.js`、`map-scene-stage.spec.js` 和 CognitionPanel 测试，落入现有收集范围。

canvas/camera 单测覆盖 screen↔map 往返、指针缩放、安全边距、resize、手势取消；标签覆盖中文、长名、选中、聚合和滞回；hotspot 覆盖 contain/cover/裁切/DPR；media 覆盖同 key 合并、引用计数、迟到 decode、上传失败和清理。

现有 atlas 测试有 mock 请求，关键场景持久化沿真实 project 创建/保存/读取链测试。全屏 mock 可验证拒绝回退，不替代 headed 浏览器与实机验证。数据库约束、并发配额、CAS、清理和回滚使用隔离 PostgreSQL，不以 SQLite 或纯 schema 测试代替。

`test:e2e:map` 当前按输入 V 只匹配 atlas spec，V00/相关实现需扩入 structure 和新 viewer；新脚本落地前不声称已有聚合命令。

### 20.3 候选性能与质量门槛

| 面向 | 原计划保留的初始目标 / 测量要求 |
|---|---|
| W 关键事实召回 | ≥95% 是待基线校准的候选门槛，不是当前成绩 |
| W 工作状态精确率 | ≥98% 同上；必须规定事实/状态分母与未知处理 |
| W 规模 | 1K/5K/10K Scene；检查点、源重验、序列化、索引、内存分别计 |
| C 容量 | 每任务候选数/入模数、回读量、依赖集合检查、commit 体积、维护量和误失效成本 |
| V 已加载选中/摘要 | p95 <100ms，不含首次网络 |
| V 桌面连续平移 | 帧时长 p95 初始目标 ≤20ms，报告长任务与掉帧 |
| V 移动容量 | 初始目标至少 30fps，动效可降级但信息不可隐藏 |
| V 容量数据 | 200 个多控制点图元，而非 200 个圆点；保持 MapDocument 限制 |
| V 图片 | 并发初值 4；当前舞台和有界相邻预取，不同时解码 40 张大图 |
| V 连续切换 | 100 次后 URL/监听器/请求进入受限稳态，内存不线性增长 |
| Explore | 分页、manifest、截断/omissions；不随平移扫描整本小说 |
| 联合维护 | 分别报告 W 已提交、C 当前可用、V 来源可用的延迟，不把 pending 当成功 |

固定设备/浏览器/网络/数据再判断。2048² RGBA 约 16 MiB 是像素存储量级计算，不代表总进程内存上限；还要记录解码、DOM 和缓存开销。

不能把 W 数据库吞吐预测成模型速度，也不能把 V 帧率预测成整书阅读质量。预算包含构建、维护、检索、生成、检查、重试和人工；图像生成/派生存储与认知试验分账，同时报告用户工作流总成本。

### 20.4 观测与隐私

用受控关联 ID 对齐 source revision、W 批次、C commit/run、V scope 与任务回执，不再复制一份全量事件日志。普通日志只记耗时、计数、状态和受限错误码，不记录正文、人物描述、图片字节、密钥、鉴权信息或 S3 key。

受控审计保存必要可回读证据，与普通遥测分离；受永久删除影响的数据范围须包括它们。

## 21. 数据迁移、灰度、回滚与生命周期

来源：[C] §5、§10.2、§15；[V] §8、§13、§16。

### 21.1 不迁移出第二套世界

旧 W 记录按 C 的 A/B/C 分层；来源完整才确定性转换。影子 generation 不改正式资产/默认读模型，切换只改工作选择指针，不改 Canon。

旧 Artifact/聊天/RP 回顾/世界设计 checkpoint 不批量宣布为认知真知。能重验来源/范围才提升，否则保留历史候选或诊断。RP 继续归 Interaction，不混入作者事实。

地图 v1、原 API 和上传/审核合同保持；新 viewer 读同一 revision。C 三类记录、V presentation 两表和图片元数据分别加法迁移；M1 不提前为旧图创建大量空 presentation。

### 21.2 能力开关与安全依赖

拟按能力分开控制：重建 v2、认知读取、认知自动维护、方法实验、沉浸 viewer、Scene presentation、工作重建叠加、保留形象/局部补图。具体开关名在实施时沿仓库命名，不声称现存。

开启 viewer 不自动启用认知后台维护；开启 C 读取不自动采用领域成果；开启 presentation 不开放人物图的 reader 权限。后端同时校验能力依赖，不能仅由前端隐藏按钮。

工作叠加缺 W 对应语义时返回不支持；C 不可用时普通已确认地图可以继续。显式历史/读者请求不能因开关关闭回退到更宽作者当前视图。

### 21.3 发布顺序

先新后端读取兼容/迁移，再 capabilities/元数据，再前端优先使用。图片 display 缺失回退 full，旧客户端仍能读取原规格；派生图处理和 DB 发布分开验证。

C 先 shadow，只观察不纳入默认 Context；再在明确试用任务开启读取；最后获长期授权并过质量/成本门禁后启用维护。方法实验独立，不因离线 runner 通过自动成为生产默认。

V 先 M1，再 Scene/presentation，再受支持工作/历史投影。新 viewer 可关闭但已保存视觉数据必须保留；旧编辑入口仍读原地图，不建两套编辑真相。

### 21.4 回滚和删除

回滚选受支持的指针/协议/功能开关，不原地改不可变内容，不删除作者新保存的图层/认知历史来适配旧 UI。明确显示哪些能力降级、哪些源版本仍可解释。

普通任务归档、派生退役、权限撤销、永久删除分别定义。任务归档不误删提升认知；认知退役不删除全部字节；图片解除引用不代表立刻物理删除；永久删除需要清理记录/摘录/索引/缓存/任务留存/图片派生与保留资产。失败清理按精确范围可收敛，不能跨项目通配删除。

## 22. 风险与进入后续范围的条件

来源：[C] §17；[V] §13、§15～§16；本次增加跨线反馈风险。

| 风险 | 处理 / 退出条件 |
|---|---|
| 地图成为另一套世界权威 | 独立 presentation/读投影；无第二 reducer；写事实回原属模块 |
| C 笔记发布绕过 Canon | 发布动作与权限分开；World Bible 仍走原准入 |
| W 缺陷被 C 总结或漂亮图遮盖 | 观察处置/真实输入/状态应用先单测；分线成功状态 |
| 未来信息经方法/地图名/图片泄漏 | 完整输入依赖、形成时点、服务端受限投影和像素审核 |
| 切视图失败回退到作者全量 | 明确 unsupported/stale，不扩大范围；缓存隔离 |
| 点击图像被当成偏好或世界事实 | 浏览反馈只作候选使用信号，默认无模型；语义改动明确授权 |
| 每次保存触发三套模型任务 | 单来源变更适配、有界合并/冷却、先确定性失效、共享预算 |
| 源已变而后台未完成时仍读旧值 | 读入口即时重验，不仅依赖任务状态 |
| cleanup 误删新图/历史图/认知 | 生命周期独立、精确引用、旧任务再验版本、真实 PG/存储测试 |
| 作者已在两个窗口修改 | 各域 head CAS，409 保草稿；不“最后返回者赢” |
| 增加只读认知类型意外扩写权 | read contract 与 ResourcePatch 能力单独评审 |
| 开放组织被误当数据库自迁移 | 逻辑内容开放；物理 schema/新工具仍走工程发布 |
| 评估弱对照或数据泄漏 | 强 B、五条件、全成本、相同原文/图片权限、oracle 隔离 |
| 恒答未知降低错误却阻碍创作 | 同测完成率、表达/人物/情节、作者修改负担 |
| SVG 容量或图片解码出现瓶颈 | 真实边界先测、可降动效；需要 WebGL 再独立基准，不先换引擎 |
| 整合后工作范围失控 | 28 包保留、集成责任嵌入；V09/V10 可选，G1 独立交付 |

暂缓的功能保持原进入条件：公开分享需裁剪不可变快照、身份/撤销、媒体与防剧透测试；角色知识地图需主体信念/来源投影；势力范围需有效时间与已采用区域；室内空间 schema 需显式扩展；导览可以创作镜头，不可编造事件；环境音/雨雾/视差必须可关闭并满足性能回退。

本计划不把这些高级功能作为 W/C 最小闭环或 V M1/M2 的隐含前置。

## 23. 开工顺序、命令边界与最终完成声明

### 23.1 第一个实施批次

先固定实际工作树 SHA，比较两份输入的共同基线，恢复已有认知研究任务并建立与本计划的关联，不新增多个互不知情的研究主任务。记录原重建计划外部依赖与需要回读的实际调用方。

同步推进 W00/C00/V00：复现观察/状态/输入屏障失败；建立公平且无泄漏的新 eval runner 协议；跑原地图/图片/恢复回归并固化 UI 夹具。先冻结 I01 中版本、scope、数据身份、只读/写入分离和错误语义，再并行编码。

随后三个最小交付：W01/W02 修掉观察丢失，C01/C02 让新 case 真实继承并回读，V01/V02/V04 配合 V05 形成可靠观看与高清图片。不能只改 README 宣称接通。

### 23.2 复用命令（待执行，不是本次成绩）

先按仓库现有工具链和隔离环境安装配置。以下命令继承输入计划的已记录入口，实施时核对实际 main；不运行生产数据库或真实模型作为默认测试。

```bash
# 仓库根目录：按受影响模块选择
make docs-check
make test TESTS=modules/imports
make test TESTS=modules/story/continuity
make test TESTS=modules/collaboration
make test TESTS=modules/evidence
make test TESTS=modules/world

# 前端单元与构建
npm --prefix frontend-console run lint
npm --prefix frontend-console run test
npm --prefix frontend-console run build

# 专用 PostgreSQL；必须在测试环境中显式提供
: "${DEDICATED_E2E_DATABASE_URL:?请先配置隔离的 PostgreSQL 测试库}"
E2E_DATABASE_URL="$DEDICATED_E2E_DATABASE_URL" make test-postgresql-critical

# 已有地图真实浏览器专项；脚本本身继续执行其测试库安全校验
DATABASE_URL="$DEDICATED_E2E_DATABASE_URL" PW_REUSE_EXISTING_SERVER=0 \
  npm --prefix frontend-console run test:e2e:functional -- \
  e2e/map-atlas.spec.js e2e/map-structure.spec.js --workers=1 --retries=0

# 跨层集成 / 已有离线协议 / 文档
make test-ci TEST_WORKERS=2
make eval-technical-coverage
make docs-check BASE_REF=origin/main
git diff --check
```

`make test TESTS=modules/world` 是本计划按同一模块选择约定给出的实施建议，仍须由 W00/V00 核对收集范围。新 map-explorer/map-scene-stage 与 cognition runner 的 CLI/Make 目标由对应批次实现和测试后加入，不在落地前给出假装可运行的专用命令。

真实模型、已授权整书、图片生成和第二模型实验须单独冻结账号连接、材料、预算、期限和复核安排。没有这些条件时记录“未运行”，不能将 skipped/mock 标为质量通过。

### 23.3 分级完成声明

| 声明 | 必需证据 |
|---|---|
| “沉浸地图 M1 可用” | 旧项目无需重生成；全屏/图片/返回/恢复可靠；浏览无业务副作用 |
| “可信重建核心 L1 通过” | 重复观察、类型化状态与前驱真实输入链已验收 |
| “可继承认知 L2 通过” | 新 case/run 经 Evidence 实际使用合法积累；范围/历史/修订/恢复可验证 |
| “地图与故事 M2 接通” | 真实 Scene/对象/有据状态/来源/返回链完整，工作层不冒充正式层 |
| “有限成长证据 L3” | 相同材料/权限/预算的可复核重复结果，结构/方法/联合与 W 工程修复可区分 |
| “整书/跨书 L4 或高级 M3” | 各自授权范围的连续验证、独立作者评价、生命周期/成本/性能与回滚；不由小样本外推 |

**本次仅完成这些计划的文档整合与文档级校验。业务实现、数据库迁移、模型实验、浏览器验收、CI 和部署都仍待对应工作包执行。**

## 附录 A. 两份输入的逐章追踪

本表避免整合时把研究公平性、媒体生命周期、旧恢复与隐藏边界删掉。C/V 原文均保留，章节编号按原文件；原索引 Rxx/Sxx 继续是原作者记录的源码定位，不是本次新核对结果。

### A.1 认知计划 C → 本文件

| C 原章节 | 主要承接位置 | 处理 |
|---|---|---|
| §0 执行结论 / 不采用方案 | §0、§3、§5 | 保留 W/C，新增 V；不增框架/数据库/调度根 |
| §1 已核对现状 | §2、§7、§18.1 | 保留五项缺陷与已有能力；不称当前系统无记忆 |
| §2 旧研究接续 | §8.6、§19.1、§23.1 | 原任务恢复、旧结果局限、开发材料身份保留 |
| §3 种子语义与三种发布 | §1、§3～§6、§14 | 保留；新增工作/视觉层的明确边界 |
| §4 模块职责 | §5、§15.1 | Collaboration 内 cognition；Map 保持 World 子系统 |
| §5 持久化与生命周期 | §8.1～§8.3、§21 | 三类权威记录、独立提升、删除与索引保留 |
| §6 接入契约 | §6、§15 | CognitionViewRef/EvolutionViewRef 不合并；组合包装与协议 adapter |
| §7 Evidence 与失效 | §6、§8.3～§8.4、§13 | 完整依赖/查询集合/跨 scope/未来方法保留并扩至 V |
| §8 自主维护 | §8.5、§12～§14 | no_change、反馈、watch/预算保留；视觉反馈不作事实 |
| §9 结构/方法联合演化 | §8.6、§19 | 联合实验与不可删除硬检查保留 |
| §10 W 主线与兼容 | §7、§18.1、§21.1 | W00～W08 不丢；原计划未载细节作为明确外部依赖 |
| §11 C 批次 | §17、§18.2 | C00～C06 保留并标跨线依赖 |
| §12 首个切片 | §16 | 保留保管/所有权与新 case；增加地图和视觉失效 |
| §13 成长实验 | §19、§20.3 | 五条件、公平原文/预算、oracle、创作价值与波动完整保留 |
| §14 作者体验 | §1、§11～§12 | 本书理解/需要决定、raw ID 隐藏、渐进展示 |
| §15 迁移/性能/发布 | §20～§21 | shadow、独立开关、来源检查、增量与不承诺 O(N) |
| §16 测试/命令 | §20、§23.2 | 新旧测试分明；专用库与未运行边界 |
| §17 风险 | §22 | 保留核心风险并补跨线副作用 |
| §18 完成/开工/未执行 | §17、§23 | L1～L4 不被 M1～M3 覆盖；计划不冒充成果 |
| 附录 A/B | 本附录、附录 C、sources/C | 原源码索引与原计划替代关系原样保留 |

### A.2 地图计划 V → 本文件

| V 原章节 | 主要承接位置 | 处理 |
|---|---|---|
| §1 目标 | §0～§1、§16～§17 | 原核心观看链/M1/M2 保留，与 W/C 协同 |
| §2 基础与限制 | §2.2、§4、§9～§10 | 地理枚举/配额/图规格/当前 vs 历史等保留 |
| §3 架构所有权 | §3～§5、§9～§11 | 三类地图状态保留，连接领域/认知外壳 |
| §4 前端清单 | §11.1 | 共享画布/媒体/控制器全部承接，附认知入口 |
| §5 状态与路由 | §6、§11.2 | 正交状态、旧参数、返回栈、dirty 与 epoch |
| §6 全屏布局 | §11.3～§11.4、§20 | 固定根/Teleport/回退/写确认/无副作用 |
| §7 地图视觉与相机 | §11.4、§20 | SVG/统一相机/语义缩放/主题/性能测量 |
| §8 图片架构 | §10.1～§10.3、§20～§21 | 两条链、display/alpha、旧图回退、清理/预算保留 |
| §9 Scene/热点 | §9.1、§10.4～§10.5、§11 | 窄契约/两表/坐标/源绑定/CAS；不写世界 |
| §10 位置/故事/历史 | §6、§7.4、§9.4～§9.5 | Presence 语义保留，历史数据接 W 而非重复实现 |
| §11 接口 | §15.2～§15.3 | 旧接口复用、新增 Explore/presentation/variant 保留 |
| §12 读者/缓存/导出 | §6、§13.4、§21～§22 | 作者首发；像素/名称/ARIA/缓存；公开分享另立项 |
| §13 M3 | §10.6、§12、§18.3、§22 | 多形象/局部补图/导览/高级条件保留，不阻塞 M1/M2 |
| §14 PR 与依赖 | §17～§18 | 原 PR-00～11 一一映射 V00～V11，无消失项 |
| §15 测试与观测 | §19.3、§20、§23.2 | 真实/Mock 分明、容量/资源、脚本补齐与隐私 |
| §16 灰度回退 | §21 | 同地图数据、加法迁移、旧规格和视觉历史保留 |
| §17 源码索引 | 附录 C、sources/V | S01～S17 与原 W01/W02 文档链接保留，不冒充新浏览 |

## 附录 B. 原批次与统一编号速查

- 认知计划引用的原重建 PR-00～PR-08：按 C 已规定保留为 **W00～W08**。
- 认知计划新增 C00～C06：保持 **C00～C06**。
- 地图计划 PR-00～PR-11：一一映射 **V00～V11**，顺序不丢失；只是明确跨线启用依赖与可选能力。
- 原地图 M1＝V01～V05；M2＝V06～V08 及前序；M3 为 V09/V10 与按进入条件选择的扩展，V11 负责启用范围的整体验收。
- 原认知 L1～L4 与本文件 §23.3 对应；并非按 V 的 M 编号换名。
- I00～I03 是落在既有工作包中的集成责任，不是额外数据库/调度器/管理模块。

## 附录 C. 输入清单、校验和与事实等级

| 代号 | 文件 | SHA-256 |
|---|---|---|
| C | `sources/PLAN-novel-cognitive-seed-v2.md` | `82bbf3db805ceceb1b07d14cf33a3e10cfd910bb852421bb82f06cbccd243d5d` |
| V | `sources/PLAN-novel-map-immersive-frontend.md` | `cd32661c41b033e54a302c1c8e9af6d788c7f0d840b29c3365b8e3d7aef83863` |

C 原文件记录它引用的更早 `PLAN-novel-world-reconstruction.md` SHA-256 为 `5c5ac696465d0e95a756efbfb64b6ac4422053030cd50843d77aa668cd320612`；这不是 C 自身哈希，且本包不声称包含该更早文件。

事实等级：输入中的源码观察保留为“计划记录的代码路径”；规则文档保留为规则，不升级为实现；旧研究保留为历史报告，不升级为本次重跑；本次 Dxx/组合视图/Ixx 是整合设计，不升级为现有接口；所有性能/质量阈值是候选目标，不升级为测试成绩。

文档交付附带主计划 Markdown、离线 HTML、原输入副本和内容校验清单。输入副本不覆盖原文件；本次不改变远端仓库与用户资料库。
