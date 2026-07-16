# 前端产品体验与地图作者闭环改进设计

## 状态

- 状态：Approved for implementation（产品决策已确认，已完成多视角设计复核，尚未实施）。
- 日期：2026-07-15。
- 依据：2026-07-15 实际运行的前后端、Chromium 桌面/390px 浏览器走查、当前 API/ORM、
  前端路由、Vitest 与地图 Playwright E2E；不以旧报告或计划推断当前事实。
- 相关设计：[`地图一级工作台设计`](./2026-06-26-map-workspace-design.md)、
  [`世界动态地图设计`](./2026-06-29-world-dynamics-map-design.md)、
  [`地图快速创建与地形设计`](./2026-06-30-map-quick-create-terrain-design.md)。
- 当前契约来源：[`地图模块说明`](../../modules/15_map.md)、`backend/modules/world/README.md`、
  `backend/modules/imports/README.md`、ORM、Alembic migration、facade/contracts 与测试。

本文档记录已确认的目标行为与实施边界。实现完成后，当前运行时事实仍须同步回模块 README、
前端文档、数据库设计和测试；本文档届时保留为设计快照，不替代当前契约。

## 1. 结论

本轮不更换 Vanilla JS、Leaflet、FastAPI、PostgreSQL 或任务队列，不新增顶级地图模块，也不
重建整库。目标是把当前“地图能操作”的基础提升为作者可以长期使用的确定性闭环：

```mermaid
flowchart LR
    A["深度导入产生类型已识别候选"] --> B["项目级地图收件箱"]
    B --> C["查看 Scene / 章节 / 原文证据"]
    C --> D["选择对象、地图与空间锚点"]
    D --> E["确认或忽略"]
    E -->|确认| F["MapFact 正式事实"]
    E -->|忽略| G["历史记录"]
    F --> H["Scene 时间线与状态差分"]
    H --> I["地图回看与连续性检查"]
```

产品目标分层如下：

- 桌面端达到真实作者长期使用标准，承担完整写作、世界书和复杂地图编辑。
- 390px 是查看与轻量操作端，支持定位、Scene/视图切换、候选审核和简单字段修改；地形绘制、
  势力涂抹、图层树和批量空间编辑转交桌面端。
- 地图首先闭环人物位置、事件发生地、线路/阻隔、势力范围四类动态；资源控制、地形变化、
  危机扩散和语义关联复用同一模型后再接入。
- 作者默认不接触技术 ID 或原始 JSON。诊断信息只允许只读复制，不能成为绕过 schema 的编辑面。

## 2. 已确认决策

| 决策项 | 确认结果 |
|---|---|
| 产品目标 | 桌面端长期可用；390px 作为查看和轻量操作端 |
| 未归属 observation | 进入项目级地图收件箱，分配地图后才进入该地图队列 |
| 首批类型化动态 | 人物位置、事件发生地、线路/阻隔、势力范围 |
| 地图 URL | 保存 map、视图模式、Scene、聚焦对象/hex；不保存工具、临时选择和未保存草稿 |
| 390px 地图 | 允许查看、定位、切换、审核和简单修改；复杂空间编辑提示使用桌面端 |
| 性能预算 | 普通地图首个可交互 Canvas ≤2s；200×200 ≤3s；交互 p95 ≤33ms |
| 技术信息 | 默认隐藏；对象菜单提供只读“复制诊断信息” |
| 长期可用门禁 | 全部 P1 清零，并通过性能、390px 关键页和完整作者闭环 E2E |
| 旧地图数据 | 不迁移；清空整个地图子系统数据，保留其他项目数据 |
| 清空范围 | 仅 16 张 `map_*` 表；不重建整库 |
| 地图产生方式 | 深度导入完成后展示一键创建预览，作者确认后才写入 |
| 文档形态 | 产品与实施一体的决策完整规格 |

审查后补充以下实现约束，不改变上表的产品选择：

| 技术决策 | 确认结果 |
|---|---|
| 候选与事实值 | 类型已识别但尚未解析的 proposal 与 canonical `MapDynamicValueV1` 分离；只有后者可采用 |
| 审核一致性 | 写操作使用 `expected_updated_at` CAS；confirm 锁定 observation；冲突统一返回 409 |
| 导入幂等 | 新导入链路使用确定性 observation UUID；相同 provenance 重试复用，payload 不同则 fail closed |
| Schema | 本轮不新增表或列；proposal 与 canonical value 复用现有 `value_json`，但必须分别经过显式 Pydantic union 校验 |
| 初始事实 | deep-import 动态必须绑定 Scene/章节；人工基线事实可显式使用“故事初始状态”时间锚点 |
| Reset | 正式清空属于一次性开发环境 cutover，不属于产品长期可用能力；仍需独立二次确认 |

## 3. 当前基线与必须解决的问题

2026-07-15 的运行证据显示：24 个桌面路由和 11 个 390px 代表路由均能加载，未发现新的
console error、page error、失败响应或 document 横向溢出；全量前端 Vitest 65 个文件、
1280 个测试通过；地图 E2E 19 个场景通过 18 个，失败项是 200×200 性能采样对象为空。

当前地图已具备地图层级、hex、地点绑定、地形、线路、标记、势力、图层树、Scene 摘要、
Observation/Fact、时间线服务、冲突与未保存保护。本轮不是重做地图，而是修复以下作者路径：

| 优先级 | 当前问题 | 目标结果 |
|---|---|---|
| P1 | Canvas 覆盖 Leaflet 地点标签，标签可见但不能点击 | 标签、聚合簇和下钻入口可由真实指针点击 |
| P1 | 打开最近地图只改内存状态，刷新回到总览 | 所有地图入口生成可恢复的规范 URL |
| P1 | 未分配 observation 混入每张地图 | 项目收件箱与地图队列明确分离 |
| P1 | 作者表单暴露 JSON、ID 和内部枚举 | 名称选择器、类型化表单、只读证据和诊断复制 |
| P1 | 当前真实导入数据没有进入 Scene 时间线 | 首批四类 observation 可确认成 Fact 并回看 |
| P1 | 390px 世界书头部挤压正文 | 标题、操作和编辑器单栏可用 |
| P2 | 普通/200×200 地图首帧约 4.21s/5.32s | 达到 2s/3s 预算并建立可靠门禁 |
| P2 | 390px 控件偏小、部分字段缺少程序化标签 | 主要按钮 ≥44px、普通操作 ≥40px，并补 label/aria |
| P2 | 移动 Scene 工作台默认打开第一项详情 | 无 `scene_id` 时先显示列表 |
| P2 | RAG 一次挂载全部结果卡片 | 首批最多 20 条，分页或加载更多 |

## 4. 目标用户体验

### 4.1 地图入口与规范 URL

地图路由继续使用：

```text
#workbench/{novel_id}/map
  ?map_id={map_id}
  &mode=dashboard|live|lens
  &scene_id={scene_id}
  &focus_entity_id={entity_id}
  &focus_hex_q={q}
  &focus_hex_r={r}
```

已有 `focus_path_id`、`focus_layer_node_id` 深链接保持兼容，只在显式定位线路/图层时保留。
`mode=overview` 表示地图总览；旧 `mode=map` 继续兼容为 `live`，但首次解析后替换成规范 URL。

路由行为固定如下：

- 从总览、最近地图、地图树、面包屑或世界对象打开地图时，必须调用 `buildMapUrl()` 并写入
  browser history，不能只设置 `_activeMapId` 后 `router.refresh()`。
- 打开另一张地图或返回总览创建新的 history entry。
- 同一地图内切换 dashboard/live/lens、Scene 或聚焦对象时更新当前 URL，但使用 replace，
  避免一次查看产生大量后退记录。
- 刷新、收藏、前进、后退必须恢复同一地图和已序列化上下文。
- 编辑工具、图层面板开合、临时选择、播放状态、未保存命令和草稿不进入 URL。
- 任何 URL 变更前继续调用 `mapView.canLeave()`；脏草稿不得被导航静默丢弃。
- 写作页地图入口继续按现有设计默认打开新标签，并携带完整上下文 URL。

### 4.2 Canvas 与地点标签

Leaflet 地点标签和聚合簇必须位于可交互 marker pane；Canvas 只接收未被 marker/控件消费的
背景指针事件。实现应建立明确 pane 层级，而不是依赖 DOM 追加顺序：

```text
地图控件 / 弹层
地点标签、聚合簇、标记
只读时间线覆盖
可编辑 Canvas hex / 线路 / 势力
底图
```

鼠标和触控点击地点标签均打开地点信息框；有详图时显示下钻，没有详图时显示创建预览；
“查看世界对象”返回相同对象。Canvas 的平移、缩放、hex 选择和拖动行为保持不变。

### 4.3 项目级地图收件箱

地图总览新增一级卡片和计数“地图收件箱 N”。它只列出 `map_id IS NULL` 且
`review_state IN (candidate, conflicted)` 的 observation，不把这些候选复制到任意具体地图。

收件箱卡片默认显示：

- 作者可读的动态类型、对象名和建议地点/线路/势力名；
- Scene、章节和时间；
- 原文证据摘要、来源工作流和置信度；
- 缺失项，如“未选择地图”“未匹配地点”“需要绘制势力范围”；
- `分配并继续`、`忽略`、`复制诊断信息`。

`分配并继续` 先选择同一 `novel_id` 的 active 地图，再直接打开同一 observation 的类型化编辑器，
并以一次性导航状态定位相关对象/地点；该临时选择不写入规范 URL。分配只设置地图归属，
observation 仍为 candidate；只有完成必填字段并明确点击“采用”才创建 MapFact。忽略保留来源、
workflow 和审计信息，不创建事实。

candidate/conflicted 在确认前始终允许纠错：作者可以更换 active 地图或退回项目收件箱；操作
保留来源、编辑和分配审计。已经生成 MapFact 的 observation 不允许直接重分配，必须先通过
既有 Fact 状态入口明确废弃或回滚，再基于原证据创建新的待处理 observation。

具体地图 dashboard 只读取 `map_id == 当前地图` 的候选与事实，不再隐式包含 `map_id IS NULL`。

### 4.4 首批四类类型化动态

现有 `MapDynamicValueV1`、`MapObservation`、`MapFact` 和只读 timeline 继续复用，不新增平行
事实表。首批导入先生成 `MapObservationProposalV1` 的四类显式 discriminated union；其中只
保存类型已识别的作者字段、未解析名称/引用和缺失项，不接受自由 `dynamic_type + 任意 JSON`。
空间与对象引用完整后，world 才把 proposal 确定性转换为当前 canonical value：

| 作者类型 | canonical value | 导入候选 | 采用前必须补齐 |
|---|---|---|---|
| 人物位置 | `location` | 人物、Scene、地点名、证据、置信度 | 已采用人物、地图、已采用地点或有效 path/hex |
| 事件发生地 | `location` | 事件、Scene、地点名、证据、置信度 | 已采用事件、地图、已采用地点或有效 hex |
| 线路/阻隔 | `route_state` | 线路名、open/restricted/blocked、原因、证据 | 地图内有效 `path_id`；无匹配时由作者选择或创建线路 |
| 势力范围 | `boundary` | 组织、范围地点描述、Scene、证据 | 已采用组织、地图和明确 hex 集合 |

导入可以创建尚未完全空间解析的 candidate，但不得把它伪装为 typed Fact：

- `value_json` 在 candidate 阶段只能是通过 `MapObservationProposalV1` 校验的 proposal；解析完成
  后整体替换为通过 `MapDynamicValueV1` 校验的 canonical value，不把未解析名称塞进 canonical ID。
  proposal 使用独立 `payload_kind=proposal` discriminator；现有投影将其报告为
  `normalization_state=untyped` 并返回 proposal type/missing items，而不是误报为 invalid 或 typed。
- 缺少地图、地点、path 或 hex 时，候选留在项目收件箱并显示具体缺失项。
- deep-import 候选只有在 `normalization_state=typed`、目标对象/空间引用通过同项目校验且
  Scene/章节来源完整时才允许采用。人工创建的项目基线事实可以没有 Scene，但必须显式选择
  `time_anchor.kind=initial_state`，不能由 deep-import 自动降级生成。
- “是否可采用”由 world 服务端统一计算并返回 eligibility/missing items；前端只投影该结果，
  不复制规则。服务端必须校验 active map、同项目且类型正确的 canonical target/location/
  controller、有效 active path、非空且界内 hex，以及相应 Scene/章节或 initial-state 锚点。
- `route_state` 没有匹配线路时不自动创建线路；作者在桌面端选择现有线路或显式创建。
- `boundary` 没有明确 hex 时不允许采用；移动端只可查看/忽略并提示使用桌面端完成范围编辑。
- candidate 不进入正式 state/delta；时间线可在显式开启“显示待处理”时作为只读预览层显示。
- MapFact 仍是唯一持久化动态事实，timeline/delta/continuity 均为确定性只读投影。

### 4.5 作者表单与诊断信息

默认编辑器不显示 UUID、`time_anchor JSON`、`spatial_anchor JSON`、`value_json`、`source_ref JSON`
或 `member_of`、`deep_import_delta_event` 等内部枚举。四类编辑器固定为：

- 可搜索的对象、地点、线路和组织名称选择器；
- Scene/章节选择器和只读来源时间；
- 类型专属字段与地图定位预览；
- 只读原文证据、来源工作流和置信度；
- 明确的缺失项、冲突原因与采用后结果预览。

对象菜单提供“复制诊断信息”，生成只读、secret-free 的文本或 JSON，允许包含 observation/fact/
map/entity ID、raw refs、normalization error 和 revision。该入口不得提供回写，不得显示 API Key、
完整 prompt、未脱敏 URL query 或超出当前 `novel_id` 的信息。

作者更新使用专用 `MapObservationAuthorUpdate`：只允许修改目标对象、proposal 中的作者字段、
空间选择和 review action。`source_ref`、原始 `evidence_text`、来源 workflow、原始 confidence 和
来源时间只能由受控内部 facade 写入；项目级和 map-scoped 公共 PATCH 均拒绝修改这些字段，
不能只依靠前端隐藏。

### 4.6 深度导入后的地图创建

不新增静默自动建图。深度导入成功后，前端使用现有 quick-create context/preview 能力判断：

- 没有 active 地图且存在已采用 canonical 地点时，结果页显示“一键创建地图”。
- 只有 candidate 地点时不展示会产生空地图的确认入口，改为显示“先审核 N 个地点”，深链到
  地点复核；candidate 继续可以作为明显标识的只读预览覆盖层。
- 已有 active 地图时，显示“查看地图收件箱”，不建议创建重复世界地图。
- 点击“一键创建地图”先进入不落库但可调整的预览；默认只包含已采用地点，待处理地点默认
  关闭。预览继续支持拖拽、半径、锁定、选择和 Undo/Redo；只有 candidate 覆盖层只读。
- 作者确认后才调用 quick-create confirm，创建地图、tiles、地点布局和绑定。
- 创建完成后打开规范地图 URL，并提示仍有多少 observation 待分配。
- 创建地图不自动采用或分配 observation；事实确认继续在收件箱/地图队列完成。
- 作者取消预览时不写数据库，候选继续保留在收件箱。

该流程不要求 imports 直接拥有地图 UI，也不允许 imports 直接写 map ORM。

### 4.7 390px 行为

390px 必须支持：地图查看、平移缩放、名称定位、Scene/视图切换、证据查看、候选确认/忽略、
人物/事件地点等简单字段修改，以及 quick-create 预览/确认。

390px 不承担：地形绘制、线路节点精修、势力 hex 涂抹、递归图层树编辑和批量空间修改。
这些入口在移动端显示为只读摘要与“请在桌面端继续”，不能展示压缩后不可用的完整工具栏。

其他核心页面的轻量操作边界固定如下，避免实现者自行扩大移动端职责：

| 页面 | 390px 支持 | 转交桌面端 |
|---|---|---|
| 写作 | 查看、短文本编辑、自动保存、查看版本摘要 | 发布、版本恢复、长篇结构性编辑 |
| 世界书 | 查看、轻量字段编辑、保存工作稿 | 发布、模板维护、AI 规则配置 |
| Scene | 列表、详情、审核、简单字段修改 | 融合/拆分、结构重排、批量操作 |
| RAG | 检索、筛选、证据查看 | 索引维护与技术诊断 |
| 地图 | 查看、定位、Scene/视图切换、轻量审核、quick-create 预览/确认 | 复杂空间和图层编辑 |

同时修复：

- 世界书活动页头部改为单栏，操作区使用折叠菜单或两列按钮，编辑器占满可用宽度。
- Scene 工作台只有显式 `scene_id` 或用户点击后才打开详情；默认先显示列表。
- 主要操作目标最小高度 44px，普通可点击控件不低于 40px。
- 搜索框、正文编辑器和高级字段补齐 `label for` 或 `aria-label`。
- 地图动态摘要在移动端使用可折叠的底部/下方区域，不覆盖 Canvas。

## 5. 接口、模块与数据边界

### 5.1 模块所有权

| 模块 | 本轮职责 |
|---|---|
| `world/map` | observation/fact、收件箱、分配、类型校验、地图创建、时间线和作者可读投影 |
| `imports` | 通过 world 稳定 facade 提交首批四类候选及来源；不导入 map models/services |
| `outline` | 继续提供 Scene 稳定身份和顺序，不拥有地图状态 |
| `frontend-console` | 路由、收件箱、类型化表单、响应式、加载反馈和性能采样 |
| `writing` | 继续消费 Scene map summary 和 map open-target，不直接读地图表 |

`world` 新增稳定 `MapObservationCandidateInput` contract 与批量 facade，例如
`create_map_observation_candidates(...)`。contract 内部使用人物位置、事件发生地、线路状态、
势力范围四个显式 proposal schema；每项携带稳定 source item key、workflow、Scene/章节、证据、
原始名称/引用及可选 resolved value。它负责 Pydantic 校验、`novel_id`/对象/Scene 引用校验、
来源规范化、幂等 provenance 和 candidate 持久化；imports 只构造 contract，不自行拼装 ORM。

`source_item_key` 由 imports 根据冻结的 Scene 来源指纹、proposal type、证据 anchor 和本地稳定序号
确定性生成，不接受 LLM 自报的随机 ID。新链路按 `novel_id + workflow_id + scene_id +
source_item_key + proposal_type` 生成 UUIDv5 observation ID，并在 `source_ref` 保存 identity 与不可变
original payload hash。相同 identity 重试必须复用已有 observation；identity 相同但原始 payload hash
不同视为 provenance conflict，fail closed 并进入可见错误，不覆盖作者后来编辑的 proposal。
旧 `create_map_observation_from_delta_event()` 保留兼容，但新的四类数据不得退回通用
`delta_event + 任意 JSON` 路径。新增 facade 前必须完成 deletion test，并为 root/map facade
`__all__`、imports 只依赖稳定 contract/facade 的静态边界及错误 DTO 增加回归测试。

### 5.2 Additive API

在 `/api/world/maps` 下增加项目级收件箱接口：

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/project-observations/inbox?novel_id=&dynamic_type=&scene_id=&source=&confidence=&eligibility=&skip=&limit=` | 只列未分配 candidate/conflicted，筛选在分页前生效，返回 total/has_more |
| PATCH | `/project-observations/{observation_id}?novel_id=` | body 含作者字段与 `expected_updated_at`；可编辑未确认候选，来源字段只读 |
| POST | `/project-observations/{observation_id}/assign?novel_id=` | body 含 `map_id|null` 与 `expected_updated_at`；支持分配、更换地图或退回收件箱 |
| POST | `/project-observations/{observation_id}/ignore?novel_id=` | body 含 `expected_updated_at`；软更新为 ignored，不伪造 map_id |

具体地图下现有 observations/confirm/ignore/batch-review 路径保持兼容。所有作者写入口统一使用
受限 `MapObservationAuthorUpdate` 与 `expected_updated_at`；来源字段出现在 request 时返回 422。
dashboard 查询语义改为只返回当前 map 的 observation；响应不删除字段，并 additive 返回
`eligibility={can_confirm, missing_items, conflict_reason}` 与当前 `updated_at`。

收件箱 assignment 响应返回更新后的 `MapObservationResponse`。前端随后导航到目标地图并通过现有
map-scoped PATCH/confirm 完成编辑与采用。assign 与 confirm 不合并为一步，避免未检查空间锚点时
直接形成事实。

assign/reassign/unassign 必须使用单条条件更新：只有 `review_state IN (candidate, conflicted)` 且
`updated_at == expected_updated_at` 才写入；confirm、ignore 和 PATCH 同样执行 CAS。陈旧 revision、
状态已变化或双分配统一返回 409，并返回最新只读摘要；前端保留本地编辑。confirm 在同一事务内
对 observation 执行 `SELECT ... FOR UPDATE`，锁后再次校验 eligibility、查询或创建 Fact、更新
review state。这样在不新增唯一索引的前提下串行化双 confirm；不得继续使用无锁“先查再创建”。
batch-review 请求改为 `items=[{observation_id, expected_updated_at}]`，按 observation UUID 稳定顺序
加锁并先验证全部项目、状态和 eligibility；任一条陈旧或无效时整批不写并返回 409/422，不产生
难以解释的部分成功。

### 5.3 Schema 与 wire 风险

- 数据库：现有 16 张地图表、主键、`value_json`、`source_ref` 和 Scene/time/spatial 字段足以
  承载本轮；proposal/canonical value 由 Pydantic schema 分层，幂等使用确定性主键，confirm
  使用 observation 行锁，因此不新增表/列、不修改 MapFact 事实边界、不需要 Alembic migration。
  如果实现无法用行锁与确定性 ID 满足并发/幂等测试，必须停止并另行评审唯一索引 migration，
  不得以应用层先查代替。
- API：新增收件箱路径和 eligibility 字段属于 additive；dashboard 排除 null-map candidate 是
  用户行为修正。公共作者 PATCH 拒绝修改来源字段、所有写入要求 CAS 是有意的请求语义收紧，
  应同步模块 README、前端契约、错误处理和测试。
- imports → world：新增稳定 contract/facade，风险中等；必须保留 `novel_id`、workflow、Scene、
  context snapshot、source item key、证据、payload hash 和确定性幂等身份。
- 前端 wire：继续消费现有 observation/fact response，并读取 additive eligibility/updated_at；不得
  在浏览器端自行解释 raw JSON 为事实，也不得自行复制 adoption 规则。
- ADR：不需要。地图仍由 world 拥有、MapFact 仍是事实源、技术栈与基础设施不变。若实现试图
  新增地图模块、事实表、队列或改写所有权，应停止并另行取得用户确认/ADR。
- 新依赖：无。

## 6. 地图子系统数据重置

### 6.1 已确认范围

不迁移或保留旧地图数据。一次性清空当前开发数据库中的全部地图子系统行：

```text
map_configs
map_tiles
map_location_bindings
map_location_layouts
map_terrain_layers
map_path_layers
map_layer_nodes
map_paths
map_path_nodes
map_terrain_regions
map_terrain_patches
map_terrain_bindings
map_markers
map_territory_tiles
map_observations
map_facts
```

必须保留 projects、writing chapters/drafts/versions、outline Scenes/structures、world entities/
relations/world bible、memory、RAG、context、imports、settings、async tasks 和其他非 `map_*` 数据。
特别保留 `memory.delta_log` 和来源审计；本轮只声明旧地图数据无保留价值，不授权删除小说或
跨模块证据。

### 6.2 安全执行协议

实现一个一次性受控管理命令或脚本，不提供公开 HTTP 清空 API。它必须：

1. 默认 `dry-run`，打印规范化的 host、port、database、user、server version、Alembic revision、
   数据库 fingerprint、环境、16 张表的行数和受影响 novel 数量；不能只相信 `APP_ENV`。
2. 拒绝 production 环境；目标数据库必须与命令行显式环境和预期 fingerprint 相符。
3. 运行时比较 ORM metadata/`information_schema` 与 16 表白名单；发现未知或缺失的 `map_%` 表、
   白名单外数据库 FK 或未知依赖立即停止，避免 schema 漂移后漏删或误级联。
4. 扫描白名单外所有 active 作者/上下文资产引用，包括世界书正式页与工作稿、当前/固定的
   synopsis revision、可进入 context 的 active derived content 及其他 map/map_fact TargetRef。
   发现活动引用立即停止，不在本授权下修改非地图资产。仅不可进入当前产品投影的历史 task/
   context provenance 可保留；报告必须记录悬空引用，完整旧值由已验证备份承担。
5. 执行前创建 PostgreSQL custom-format 备份，记录大小和 checksum，运行 `pg_restore --list`；
   正式删除前还必须恢复到临时数据库，核对 Alembic revision、16 张地图表和关键非地图表计数。
   恢复演练不通过时不得进入确认阶段。
6. 正式执行使用维护窗口：停止 API 与 worker，拒绝存在 pending/running/recovery-required 的
   deep-import、world extraction 或其他地图写入任务。表锁不能替代停止写入者，因为等待中的
   insert 会在事务提交后继续执行。
7. 要求包含数据库 fingerprint 的第二次显式确认短语；普通 `--yes` 不足以跳过。
8. 在一个事务内按 FK 拓扑固定顺序删除白名单表数据：facts → observations → path nodes →
   paths → layer nodes → terrain bindings/patches/regions → terrain/path layers → markers/territories →
   location bindings/layouts → tiles → configs。不得使用可能级联到白名单外的裸
   `TRUNCATE ... CASCADE`。
9. 删除前后记录每张表计数和关键非地图摘要；任一非地图表计数或校验摘要变化立即回滚并停止。
10. 服务仍停止时验证 16 张表均为 0，项目、章节、Scene、世界对象、世界书和 RAG 保持不变；
    应用恢复前再次核验。恢复服务后只做只读健康检查，不自动重跑任务或生成地图数据。
11. 不执行 Alembic downgrade、不 drop table、不重建整个数据库。

重置工具可以提前实现和 dry-run，但实际删除属于一次性开发环境 cutover：安排在新收件箱、
类型化导入与 quick-create 流程通过隔离测试之后、最终验收数据生成之前。它不属于产品长期可用
门禁，也不是本设计批准后自动执行的步骤。本设计不构成现在立即清空数据的授权；真正执行仍须
按 `AGENTS.md` 再次二次确认。

重置后不做旧地图数据 backfill。已有项目优先直接使用仍保留的已采用地点进入 quick-create，
不得把“重新运行完整深度导入”作为地图恢复操作，因为它还会改变 Scene、实体、关系和 memory。
新导入从本设计的类型化候选链路产生 observation；基于既有 Scene 重新扫描地图候选属于未来
独立工作流，不在本轮静默执行。系统不得自动重跑 LLM 或覆盖既有非地图资产。

## 7. 性能、加载与列表策略

### 7.1 指标定义

- 路由提交时记录 `map-nav-start`；地图数据就绪、Canvas 完成首个非空 frame、控件和 pointer
  handler 已安装后只发出一次 `map:interactive` mark/event。Playwright 等待该信号后真实点击一个
  hex，证明不是只完成视觉首帧；固定 sleep 不得计为完成。
- 普通基线使用仓库内确定性 24×18 fixture；预算 ≤2s。大图基线使用确定性 200×200、40,000
  hex 混合压力 fixture；预算 ≤3s。两个 fixture 的 tile、binding、marker、territory、layer、
  label、Fact/candidate 数量和 payload checksum 固定在 manifest，不依赖 reset 前的开发库地图。
- 首屏分别报告一次冷启动，以及 1 次预热后的至少 10 次正式导航；正式样本按统一 nearest-rank
  算法输出 median/p75/max，任何单次不得超过预算两倍，不把冷启动混入热样本 p75。
- 平移/缩放必须使用真实 wheel/drag/touch 输入并采样至少 100 个可见 frame；33ms p95 作用于
  `input_to_paint_ms`。同步 `_redraw()` CPU 时间单独记录为 `redraw_cpu_ms`，同时记录 long task。
- telemetry 在 mount 时初始化并由页面公开只读 mark/event；测试不得动态 import 另一模块实例后
  修改空 metrics，也不得以直接循环 `_redraw()` 代替真实交互。

绝对预算只在固定参考 profile 判定：Playwright bundled Chromium、1280×720、workers=1、
retries=0、fresh backend/frontend、显式独立 PostgreSQL `DATABASE_URL`、`PW_REUSE_EXISTING_SERVER=0`。
附件记录 commit、浏览器版本、CPU、内存、供电/负载、DB fingerprint、fixture checksum 和全部原始
样本。普通 CI 继续使用同轮裁剪/未裁剪相对退化门禁；2s/3s 的长期可用结论必须来自标记过的
参考 profile，不允许由 retry 后偶然通过替代。

### 7.2 实施方向

- 分别记录 API、状态组装、Leaflet 初始化、布局、Canvas 首帧和标签首帧，先定位瓶颈。
- 保留视口裁剪和布局缓存；大图只绘制可见 hex/标记/标签，不为 40,000 hex 创建 DOM。
- 先渲染底图与主要地点，再补低优先级标签和动态层；提供可解释的加载状态而不是空白 Canvas。
- 快速切换地图时取消旧请求/旧 render epoch，旧响应不得覆盖当前地图。
- RAG 搜索首批最多挂载 20 张结果卡，使用分页或“加载更多”；20 是避免无界 DOM 的初始实现
  默认，不是不可调整的产品常量。搜索词和筛选保留在 URL，临时加载游标和抽屉状态不持久化。

## 8. 实施顺序

### Phase 0：安全工具与基线

- 实现地图重置命令、dry-run、schema 漂移检查、备份恢复演练和非地图摘要保护；只 dry-run，
  不停止服务、不执行删除。
- 修复 200×200 性能采样器，建立公开 telemetry、真实输入采样和无 retry 的参考 profile。
- 固化桌面、390px、普通地图和 200×200 的确定性 fixture manifest/checksum。

### Phase 1：现有 P1 缺陷

- 修复 Canvas/地点标签 pane 和真实点击。
- 所有地图入口改用规范 URL，补齐 refresh/back/forward/recent-map 回归。
- 修复 390px 世界书头部、Scene 默认详情和关键触控目标；用真实 Chromium 几何/触控断言验收。
- 默认作者界面移除 raw ID/JSON/内部枚举，先提供只读诊断复制。

### Phase 2：收件箱与类型化编辑

- 增加项目级收件箱 API、world service/repository 和地图总览入口。
- 具体地图 dashboard 排除未分配候选。
- 实现四类 proposal/类型化表单、服务端 eligibility、缺失项提示、assign/reassign/unassign、ignore
  和 typed-only confirm 门禁。
- 把公共作者 PATCH 收敛到 `MapObservationAuthorUpdate`；实现 `expected_updated_at` CAS、409 最新
  摘要和 confirm observation 行锁。
- 对全部新增读取/写入增加 cross-novel、archived map、invalid Scene/entity/path/hex、陈旧 revision
  和 PostgreSQL 并发测试。

### Phase 3：导入与创建闭环

- 增加 world stable contract/facade，imports Phase 2 的 Pydantic LLM 输出显式包含首批四类
  proposal；定义 Prompt 字段、确定性映射和无法识别时的可见降级，不从自由 delta JSON 猜类型。
- 保存 workflow、Scene、章节、context snapshot、source item key、原文证据、payload hash 和确定性
  observation UUID；增加 facade deletion test 和跨模块静态边界测试。
- 深度导入成功页接入 quick-create context/preview：有 canonical 地点时提供一键创建，只有
  candidate 地点时提供“先审核地点”，已有地图时进入收件箱。
- 完成 observation → assign/edit → confirm/ignore → MapFact → timeline/state-at/playback E2E。

### Phase 4：性能与长期可用验收

- 优化普通和 200×200 地图首屏，达到 2s/3s 和 33ms p95 预算。
- 完成 390px 轻量地图审核、世界书、Scene、写作与 RAG 代表流。
- 完成确定性 seed E2E、mock-LLM worker integration 和参考 profile 性能验收；真实 LLM 质量测试
  保持 opt-in，不作为前端全绿条件。
- 产品门禁通过后，可以另行进入开发环境 cutover：先 reset dry-run，再独立取得正式清空确认。
- cutover 完成后使用新的导入/预览流程生成验收项目，不恢复旧地图数据。

## 9. 测试与验收

### 9.1 Backend/unit/integration

- 四类 `MapObservationCandidateInput`/`MapObservationProposalV1`、canonical value、转换状态和必填字段；
  deep-import 必须有 Scene/章节，人工 `initial_state` 基线事实单独覆盖。
- imports 只能通过 world facade 写 candidate；缺来源、跨 novel、无授权、无稳定 source item key 或
  invalid schema fail closed；相同确定性 UUID 重试复用，payload hash 冲突不得覆盖。
- 收件箱只返回 `map_id IS NULL` 的 candidate/conflicted，分页和过滤稳定。
- assign/reassign/unassign 校验 active map、同 novel 和 `expected_updated_at`；失败不部分写入。
- 作者 PATCH 不接受 source/evidence/workflow/confidence/source-time；内部 facade 仍可在创建时写入。
- eligibility 校验正确 canonical 对象类型、Scene/initial-state、active path、非空且界内 hex；未 typed
  的 candidate 不可 confirm。
- PostgreSQL 集成覆盖双 assign、陈旧 PATCH、confirm/ignore 竞态和双 confirm；confirm 锁后
  幂等创建/复用唯一逻辑 Fact。
- dashboard 不返回未分配 candidate；timeline 默认只使用 confirmed Fact。
- reset 覆盖 dry-run、unknown map table/FK fail closed、活动 JSON/synopsis 引用、运行中写任务、
  错误 DB fingerprint、备份失败/截断、临时恢复失败、错误确认短语、事务中途异常回滚、空库重复
  执行和非地图摘要保护。

### 9.2 Vitest

- `buildMapUrl`/`parseMapRouteContext` 覆盖 overview、recent、旧 `mode=map`、三视图和 focus。
- 最近地图、地图树、面包屑和世界对象入口必须写规范 URL。
- Canvas pane 顺序、地点标签和聚合簇保留可交互命中。
- 四类作者表单不渲染 JSON/ID，诊断入口只读且脱敏。
- 390px Scene 无 route Scene 时显示列表；移动复杂地图入口隐藏/转为只读提示；控件有 accessible
  name。Vitest 只验证结构和语义，不宣称验证 CSS 几何。
- RAG 首批 DOM 卡片不超过 20。

### 9.3 Playwright

- 真实 pointer 点击地点标签 → 地点信息 → 创建/下钻详图 → 返回。
- 总览/最近地图/地图树/面包屑/世界对象入口分别验证 push；同图 mode/Scene/focus 切换只 replace，
  不增加 history length；refresh/back/forward 恢复规范路由和地图。
- 每个地图入口在脏草稿下验证取消后 URL/地图不变，确认后才清理草稿；非法/归档 map 和失效
  entity/path/layer focus 显示可恢复错误。
- 世界对象 → 地图聚焦 → 世界对象双向定位。
- 确定性 deep-import 结果 fixture → 有 canonical 地点时可调整预览 → 确认创建地图；只有
  candidate 地点时显示“先审核地点”，不得创建空地图。
- 四类动态分别完成证据查看、分配后自动聚焦、编辑、换图/退回、采用、忽略和历史查看。
- 已采用事实出现在正确 Scene 的 timeline/state-at/playback；candidate 不污染正式状态。
- 409 revision conflict 保留本地草稿；未保存导航继续二次确认。
- 390×844 + `hasTouch=true` 验证 quick-create、人物/事件地点审核、tap/drag/地图标签、世界书标题/
  编辑器宽度、主要按钮 ≥44px、普通操作 ≥40px、无横向溢出、Canvas 不被摘要遮挡；线路/势力
  复杂编辑不可进入并显示桌面端提示。现有移动线路精修用例必须替换，不能 skip/fixme。
- 世界书、Scene、RAG、深浅色、键盘、焦点循环和失败重试代表流；RAG 固定 58 条结果验证
  20 条首批、加载更多无重复/丢失、total、查询切换取消旧响应和前进后退恢复。
- inbox 加载失败保留筛选并可重试；assign/confirm 或 quick-create 在服务端成功但响应丢失时，
  重试不得重复写入。覆盖 401/403/404/409/422/500 的可见文案和恢复动作。

### 9.4 性能

- 参考 profile 下普通地图热样本 p75 首个可交互 Canvas ≤2s，另报冷启动。
- 参考 profile 下 200×200 地图热样本 p75 ≤3s，另报冷启动。
- 真实平移/缩放 100+ frame 的 `input_to_paint_ms` p95 ≤33ms；另报 `redraw_cpu_ms`。
- 大量 hex + marker + territory + layer + label 混合 fixture 无全页溢出、无未界定 DOM 增长。
- 测试输出 runner/DB/fixture 元数据、原始样本、API/布局/首帧分段指标；telemetry 为空直接失败，
  retries 必须为 0，不允许跳过断言。

### 9.5 测试拓扑与命令门禁

- 标准 Playwright 使用确定性 test-only seed/mock task result，验证完整 UI/API，不依赖 worker 或 LLM。
- 另设 worker-enabled integration，使用 mock LLM/固定 provider response 验证
  `imports → world facade → candidate` 真正落库；默认 Playwright 未启动 worker 时不得声称覆盖它。
- 真实 LLM 质量验收单独 opt-in，不作为前端全绿或产品日常可用门禁。
- 新增无 retry、workers=1 的 `test:e2e:map-perf`；地图子集命令必须通过统一 tag/清单包含全部地图
  spec，包括移动端，且检查 skipped/fixme 数为 0，不能只看退出码。

## 10. “适合真实作者长期使用”门禁

只有同时满足以下条件才能改变产品结论：

1. 本文列出的全部 P1 缺陷清零。
2. 首批四类 observation 在桌面端完成导入、收件箱、证据、编辑、采用/忽略和时间线回看。
3. proposal/canonical 分层、服务端 eligibility、来源只读、确定性幂等与 observation 并发测试通过，
   不存在双 confirm、陈旧覆盖或 candidate 污染正式状态。
4. 390px 世界书、Scene、地图轻量审核、quick-create、写作和 RAG 代表流通过真实 Chromium
   几何/触控验收；复杂地图编辑明确转交桌面端。
5. 普通/200×200 地图在参考 profile 达到性能预算，性能测试不再依赖空或重复模块实例；普通
   CI 同轮相对退化门禁通过。
6. 全量 Vitest、完整地图 E2E、受影响 Playwright、worker-enabled mock integration 与 API contract
   全绿；受影响范围 skipped/fixme 为 0，性能命令 retries=0。
7. reset 工具的 dry-run、恢复演练、schema 漂移、活动引用、并发写入拒绝和回滚测试通过；这里
   只证明工具安全，不要求在产品门禁内对开发数据库正式执行删除。
8. 模块 README、`docs/modules/14_frontend.md`、`docs/modules/15_map.md`、数据库设计、
   Prompt 契约和 E2E coverage 已按实际实现同步。

### 10.1 一次性开发环境 cutover 清单

产品长期可用门禁与当前开发数据库清理分开。只有用户另行授权 cutover 后才依次执行：

1. 停止 API/worker，确认无运行中或待恢复的地图写入任务。
2. 对目标开发数据库运行 dry-run，核对 fingerprint、16 表、未知依赖和活动非地图引用。
3. 创建备份并完成临时数据库恢复演练。
4. 再次展示影响摘要并取得包含 fingerprint 的独立确认短语。
5. 在单事务中正式清空，仅验证 16 张地图表和非地图摘要；任一异常回滚。
6. 恢复服务并只读健康检查，再用新 quick-create/候选流程生成验收地图。

cutover 未执行或因活动引用被拒绝，只表示当前开发环境尚未切换，不反向否定产品能力验收；
不得为了通过 cutover 修改或删除白名单外资产。

## 11. 非目标与停止条件

- 不把移动端做成桌面复杂地图编辑器。
- 不在首批接入资源、地形、危机和语义关联闭环。
- 不自动采用 observation、不静默创建地图、不让 GET 派生请求回写事实。
- 不允许作者编辑 raw JSON，不以隐藏高级模式绕过 Pydantic/schema。
- 不新增自治 Agent、地图顶级模块、新前端框架、数据库、队列或渲染依赖。
- 不删除或重建非地图数据，不执行未经二次确认的正式 reset。
- 如果实现需要改变 MapFact 事实所有权、增加新基础设施、跨 `novel_id` 读取、放宽用户授权，
  或发现 reset 会触及白名单外数据，立即停止并重新取得用户确认。
