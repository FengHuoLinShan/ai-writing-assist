# 地图快速创建与手绘地形设计

## 背景

当前地图已经是 `world` 模块内的可用子系统，具备地图层级、六边形地形、地点绑定、动态标记、势力范围、地图工作台、世界动态总控台和写作页地图摘要。

本设计补齐两类作者体验：

- 小白用户在地图页一键把已有结构化数据整理成可编辑地图。
- 作者用手绘方式表达深渊、高山、结界、污染、禁区等地形/语义覆盖层，并把这些手绘区域绑定到后来抽取或手动创建的地点对象。

地图模块的核心目标是帮助作者构建小说世界的地理关系，而不是把 Scene 顺序、人物行动或关系图强行投射为地理位置。快速创建只查询已有结构化数据并调用地图创建能力，不负责识别正文、不跑 LLM、不创建世界对象。

## 目标

- 地图页提供 `快速创建` 入口，用户可选择创建世界地图、为某个地点创建详图或基于当前地点创建下钻地图。
- 每次快速创建只生成一张地图，不批量创建父子地图。
- 快速创建默认只使用 `canonical` 数据，并提供 `包含待确认候选` 开关。
- 快速创建优先使用明确结构化地理关系：包含、方向、相邻、距离、控制范围。
- 用户在预览中调整地点位置、大小和锁定状态，确认后才写入正式地图数据。
- 地点布局和地形绘制分成两个编辑模式，避免拖拽语义冲突。
- 地形绘制采用手绘范围、快捷撤销和保存，不自动污染世界对象或正史事实。
- 手绘地形可以绑定到已有或后续出现的地点对象，绑定需用户确认，并区分地点本体范围与影响范围。
- 第一版不引入新的运行时渲染依赖，继续使用 Leaflet 视口和自研 Canvas 图层。

## 非目标

- 不让快速创建读取正文、跑 LLM 或执行实体识别。
- 不根据 Scene 出现顺序或人物移动猜测地理位置。
- 不把普通手绘地形自动创建为 `core_entities`。
- 不自动把地形覆盖关系写入世界事实层。
- 不把剧情线作为地理对象生成；剧情线只作为筛选和高亮维度。
- 不实现完整关系图视图；第一版只在地图检查器里显示局部关系片段。
- 不支持用户上传自定义素材；第一版只使用内置素材。
- 不新增后端地图布局历史表；撤销只在前端 session 内完成。
- 不替换 Leaflet，不引入 MapLibre、Cytoscape、d3-force 或 PixiJS 作为第一版运行时依赖。

## 技术路线

继续采用分层引擎：

```text
Leaflet = 视口引擎
Canvas 2D = 业务渲染图层
GeoLayoutEngine = 地理关系布局核心
MapInteractionEngine = 拖拽、锁定、+/-、撤销、命中查询
```

外部库调研结论只转化为可借鉴思想：

- MapLibre：借鉴 `feature state` 与 `queryRenderedFeatures` 风格的运行态和命中查询。
- Cytoscape.js：借鉴 `locked / grabbable / selectable` 状态和“layout 只产出位置”的边界。
- d3-force：借鉴半径碰撞、固定节点和 quadtree 剪枝；最终结果必须吸附规则网格，避免非确定性漂移。
- PixiJS：借鉴场景分层、hitArea 和 ticker 动画调度；暂不引入 Pixi。

地图模块不是通用可视化工具，而是数据库驱动的小说地理关系编辑器。外部图/地图生态只借鉴分层、命中查询、布局稳定性和多视图联动。

## 快速创建

### 入口

地图页提供 `快速创建`。用户先选择创建目标：

- 创建世界地图。
- 为某个地点创建城市/区域详图。
- 基于当前地点创建下钻地图。

每次只生成一张 `map_config`。如果用户选择为某个地点创建详图，默认数据范围只包含：

- 目标地点本身。
- 直接子地点或明确包含地点。
- 通过 canonical `contains/contained_in/located_in` 关系关联的直接子地点。

用户可以搜索并显式添加其他 canonical 地点；人物、组织和事件不进入本轮地点布局范围。

默认不拉取全世界对象库，避免详图一开始过度拥挤。

### 数据来源

快速创建本身是编排器，不是识别器：

- 查询已有世界对象、地点、组织、人物、事件、关系、Scene、剧情线、地图 observation/fact。
- 默认只用 `canonical` 数据。
- `包含待确认候选` 开关打开时，可把 candidate 数据拉入只读预览，并用明显待确认样式展示；candidate 默认不选、控件禁用且不得保存。
- 不自动新建世界对象。
- 数据不足时显示“缺少地点方向/距离关系，可在地点详情补充”，不使用叙事顺序猜地理位置。

### 预览与确认

`快速创建` 点击后先进入可调整预览，不直接落库为正式地图。

预览支持：

- 拖拽地点。
- `+ / -` 调整地点占用半径。
- 锁定/解锁地点。
- 勾选/取消勾选 canonical 预览地点；canonical 默认全选，candidate 永远只读。
- 开关候选数据。
- 选择是否生成人物、组织、事件等结构化标记。
- 前端 session 内 Undo/Redo。
- 离开确认，防止未保存预览丢失。

确认创建时，对用户表现为一键完成，内部按两层写入：

1. 必写：地图配置；地点布局、地点绑定只写入预览中已选地点。
2. 可选：人物、组织、事件等结构化标记。默认勾选“生成人物等结构化标记”，允许取消。

API 兼容旧调用：`confirm` 不传 `layouts` 时按完整预览落库；传入 `layouts` 时只按传入布局落库；传入 `layouts=[]` 时只创建地图，不写地点布局、绑定或 quick-create facts。

同层同名地图默认返回 409。preview/confirm 只有显式提供 `replace_map_id` 才替换已有地图；
替换沿用目标的类型、网格及父层级，只覆盖地点布局、地点 bindings 和对应
quick-create facts，保留底图、覆盖图层、标记与领地。

第一版预览草稿只存在前端本地状态，不新增后端草稿表。

### 地形与快速创建

快速创建第一版不自动生成地形图层。它只创建地点布局和可选结构化标记。地形创建完成后进入 `地形绘制编辑` 手绘。

以后若已有明确结构化地形设定，可考虑从设定生成地形草案，但仍需用户确认。

## 地点布局

### 设计原则

地图的核心是地理关系，所以地点布局优先满足结构化位置关系，而不是叙事路径。

优先级：

1. 用户手动锁定的位置。
2. 明确结构化地理关系：包含、方向、相邻、距离、控制范围。
3. 自动避让与美观。

拖拽地点不会修改世界事实，只修改当前地图布局。用户在地点详情里补充“东门在洛阳东侧”等设定时，才进入世界事实层。

### 编辑行为

地点布局编辑模式提供：

- 自由拖动手感，松手后吸附规则网格。
- 拖拽后默认固定位置。
- 小锁图标用于解除固定。
- 固定地点不会被自动挤走。
- 未固定地点按局部规则挤占、补位、外扩。
- 空间不足或任一 footprint 越界时拒绝整次保存，保留冲突提示和撤销入口；本轮不自动扩展既有地图边界。

### 地点大小

`+ / -` 默认只修改当前地图显示大小和占用范围，不改世界事实。

旁边提供选项：`同步修改数据库中的地理设定`。用户明确选择后，才把地点规模或影响范围写入世界事实层。

地点大小实际占用更多网格格子，而不是只视觉放大。建议占用半径：

```text
1 格 / 2 格 / 3 格 / 5 格
```

放大时周围未固定地点外扩，缩小时周围地点可回填。

### 结构化标记

人物标记默认放置规则：

- 有最新已确认位置：放在那里。
- 没有明确位置但有关联地点：放在关联地点旁边。
- 没有位置也没有关联：进入“未定位对象”列表，等待用户拖入地图。

组织/势力默认优先生成范围区域：

- 有明确控制地点、所属地点或势力范围数据：生成区域。
- 没有范围数据：进入“未定位对象”列表或作为待放置组织标记。

剧情线不作为地图对象生成，只作为筛选和高亮维度。选择剧情线后，高亮相关地点、人物、事件、风险区域。

### 布局数据表

新增独立表 `map_location_layouts`，不要把布局行为塞进 `map_location_bindings.style_override`。

建议字段：

```text
id
novel_id
map_id
location_entity_id
center_hex_q
center_hex_r
occupy_radius
locked
layout_source        // quick_create / user_drag / auto_reflow / imported
layout_version
sync_geo_setting     // 本次是否同步修改数据库中的地理设定
meta
created_at
updated_at
```

`map_location_bindings` 继续表达地点绑定到哪些 hex。`map_location_layouts` 表达地点节点中心、占用半径、锁定状态和挤占布局。

## 地理关系、剧情覆盖与冲突处理

### 主视图权威

地图主视图以地理关系为权威。地点位置、距离、方向、包含关系和手动锁定位置决定地图布局。

剧情线、人物关系、事件因果和时间顺序不能反向移动地点，也不能改变 `GeoLayoutEngine` 的布局结果。它们只能进入：

- 高亮。
- 临时轨迹线。
- 图层筛选。
- 右侧检查器。
- 问题提示。
- 冲突解释或待确认候选。

这条规则避免把“某人物下一场出现在远方”误解释成两个地点应该靠近。比如角色上一场在长安，下一场在洛阳，地图不能为了剧情连续性把长安和洛阳挤到一起。

### 剧情覆盖层

剧情覆盖层只回答“这些剧情在地图上发生在哪里”，不回答“这些地点应该怎么摆”。

第一版只提供轻量控制：

- 剧情线下拉：选择一条剧情线或全部。
- Scene 选择器：按 Scene 顺序定位当前片段。
- 人物轨迹开关：显示选中人物的移动轨迹。
- 播放按钮：按 Scene 顺序高亮地点、人物和事件，不做复杂动画。
- `只看冲突` 开关：隐藏普通轨迹，只显示待解释跳跃和设定冲突。

剧情覆盖层可以显示人物、组织、事件、风险区域和移动轨迹，但这些都是覆盖信息，不写回地点布局。

### 空间连续性与移动解释

远距离短时间移动不是自动错误，而是解释缺口。系统按三类展示：

- `合理移动`：距离、时间和已有交通/法术/剧情解释匹配。
- `待解释跳跃`：远距离短时间移动，但没有解释。
- `设定冲突`：已有设定明确排除该移动可能。

显示移动轨迹时，线条上直接显示解释文字：

- 已解释：`传送`、`秘道`、`飞舟`、`旅途省略`、`梦境`。
- 未解释：`需解释` 或 `移动待确认`。
- 冲突：`设定冲突`，使用警告样式。
- 误报或忽略：弱化显示，并保留在检查器历史中。

用户确认解释后，写入地图事实层，而不是世界地理事实层。建议复用 `map_observations / map_facts`：

```text
dynamic_type = movement_explanation
target_entity_id
from_location_id
to_location_id
from_scene_id
to_scene_id
explanation_type      // teleport / secret_route / travel_omitted / vehicle / dream / unknown
evidence_text
review_state
fact_status
```

### 冲突类型

第一版只定义四类地图冲突，避免泛化成完整写作诊断系统：

- `layout_conflict`：固定地点重叠、空间不足、占用半径无法自动挤占。
- `geo_fact_conflict`：世界地理事实与当前地图布局冲突，例如数据库说 A 在 B 东侧，但锁定布局在西侧。
- `continuity_conflict`：远距离短时间移动且没有解释。
- `terrain_conflict`：地形与地点绑定冲突，例如同一 footprint 同时绑定到互斥地点，或地形语义与地点设定明显不匹配。

选择 `设定冲突` 时，创建地图事实层记录：

```text
dynamic_type = map_conflict
conflict_type = impossible_movement / geo_fact_mismatch / layout_overlap / terrain_binding_mismatch
status = open
target_entity_id
from_location_id
to_location_id
from_scene_id
to_scene_id
reason
evidence_text
```

第一版不新增独立 issue 表，先复用地图 observation/fact 体系。

### 冲突入口与处理

冲突入口保持在作者正在使用的上下文里：

- 地图画布：点击冲突线、冲突区域或冲突标记，打开对象信息框。
- 右侧检查器：展示证据、影响对象、解释候选和处理动作。
- 写作 Scene 摘要：只展示高优先级冲突和“打开地图处理”，不在写作页做复杂处理。
- 地点详情：展示与该地点相关的未解决冲突和地形绑定冲突。

空间连续性冲突的处理动作：

- 修正文稿。
- 改人物位置。
- 添加移动解释。
- 标记误报。
- 关闭冲突。

地理事实冲突的处理动作：

- `按手动位置同步修改数据库中的地理设定`。
- `按数据库设定恢复布局`。
- `保留布局差异`。
- `标记为误报`。

### 手动布局与世界事实冲突

当用户锁定布局与数据库地理事实冲突时，当前地图显示以用户锁定位置为准，数据库事实不被静默修改。

系统创建或展示 `geo_fact_conflict`。用户可以显式选择：

- 同步修改数据库中的地理设定。
- 恢复为数据库设定对应的布局。
- 保留当前地图的表达性布局差异。
- 标记误报。

`保留布局差异` 是当前地图内的 override，不是世界事实变更：

```text
layout_override_reason = expressive_layout / readability / user_preference / unknown
suppressed_conflict_ids = [...]
```

被 suppress 的冲突不再反复弹窗，但仍能在检查器和冲突列表里看到。

### 局部关系片段

右侧检查器只显示对地图决策有用的局部关系片段：

- 地理关系：包含、相邻、方向、距离。
- 布局关系：锁定、占用半径、挤占了谁、被谁挤占。
- 地形关系：footprint、influence、重叠地形层。
- 剧情覆盖：当前剧情线相关 Scene、事件、人物。
- 问题提示：未定位对象、未解释跳跃、开放冲突。

普通社交关系、情绪关系、全局因果图不进入地图检查器。它们可以在其他模块表达，地图模块只消费与空间决策相关的摘要。

### 状态边界

运行态只存在前端或当前会话：

```text
hovered
selected
dragging
preview
candidateVisible
activeBrush
highlightedByThread
currentPlaybackFrame
```

地图事实层负责保存：

- 地点中心、占用半径和锁定状态。
- 地形 patches。
- 地形绑定。
- 已确认移动解释。
- 开放地图冲突。

其中 `map_location_layouts.center_hex` 是地点编辑锚点，实际显示范围以
`map_location_bindings` 为权威。地点移动会整体平移全部 bindings 并保留不规则 footprint、
label/style override 与唯一中心；只软废弃实际移动地点的旧 quick-create fact，不新增世界事实。

世界事实层只保存地点方向、包含、规模等 canonical 设定。只有用户明确选择 `同步修改数据库中的地理设定` 时，地图操作才写入世界事实层。

派生状态默认不落库，例如地形覆盖了哪些地点、某剧情线的临时轨迹、异常移动距离。只有用户确认后，才保存为 `movement_explanation`、`map_conflict` 或地形绑定。

### 第一版多视图边界

第一版所谓多视图联动只包含三个区域：

- 地图主视图：地理关系、地点、地形、标记、轨迹和图层。
- 右侧检查器：当前对象、局部关系片段、冲突、解释、绑定候选和处理动作。
- 时间/剧情覆盖控件：剧情线、Scene、人物轨迹、播放和只看冲突。

第一版不做独立关系图视图、不做独立大时间轴、不提供 YAML/GraphML/Mermaid 外部转换视图。

## 地形绘制

### 模式拆分

地图编辑分成两个明确模式：

**地点布局编辑**

- 快速创建。
- 拖拽地点。
- 锁定/解锁。
- `+ / -`。
- 挤占补位。
- 保存布局。

**地形绘制编辑**

- 选择素材。
- 画笔/橡皮。
- 笔刷大小。
- 透明度。
- 图层显隐。
- Undo/Redo。
- 保存地形。

普通查看模式只负责浏览、检查器、图层开关和跳转。

### 手绘范围

地形范围由用户手绘：

- 用户选择地形素材，例如深渊、高山、结界、禁区、水域。
- 按住左键拖拽绘画范围。
- 系统把笔刷经过的 hex 记录为地形覆盖区。
- 支持橡皮擦、笔刷大小、透明度。
- 支持快捷 Undo/Redo，例如 `Cmd/Ctrl+Z`。
- 点击保存后写入地形图层数据。

前端内部用增量操作栈维护绘制历史。保存到后端时按该图层最终状态覆盖保存 patches。第一版不做后端 patch log，不做多人协作冲突合并。

### 地形图层

地形和地点分图层。地形不会因为地点固定就自动大幅变形或随机让位。地形本身是可编辑地图对象，有自己的位置、范围、锁定状态、透明度和层级。

每个地形图层只对应一种素材/语义类型：

- 一个“结界层”只画结界。
- 一个“深渊层”只画深渊。
- 同一地图可以有多个地形图层。
- 每层独立透明度、显隐、锁定、绑定、保存。

地形图层允许重叠，不自动合并。视觉上按图层顺序、透明度和混合样式叠加。检查器显示该 hex 或地点下叠加了哪些地形层，例如“森林 + 污染区”。

### 数据与渲染

数据层保存离散 hex patches，便于编辑、命中、保存和计算影响地点。查看模式渲染时自动平滑/羽化边界，避免明显锯齿。

编辑模式可以显示真实 hex 覆盖，便于精确修改。

地形绘制采用“覆盖纹理 + 图案点缀”的混合渲染：

- 大范围用半透明颜色/纹理覆盖。
- 边界或中心少量放素材图案，增强识别。
- 不在每个 hex 重复铺满图标。
- 地点节点始终在上层，避免遮挡名称和地理关系。

允许地形画在地点底下。语义真实优先，视觉可读通过图层策略解决：

- 普通查看模式：地点始终在上层，地形自动降透明，地点节点加描边或底色。
- 地形编辑模式：显示地形真实覆盖范围，可短暂弱化地点层，但不修改地点数据。
- 地点详情可显示“此地点位于结界范围内”等派生影响提示。

### 地形数据表

建议新增：

```text
map_terrain_layers
- id
- novel_id
- map_id
- name
- terrain_asset_key
- opacity
- z_index
- visible
- locked
- meta
- created_at
- updated_at

map_terrain_regions
- id
- novel_id
- map_id
- layer_id
- name
- region_status        // active / hidden / deprecated
- meta
- created_at
- updated_at

map_terrain_patches
- id
- novel_id
- map_id
- layer_id
- region_id
- hex_q
- hex_r
- strength
- brush_source
- created_at
```

一个 layer 表示同类素材和显示属性。一个 region 表示一次连续手绘或一个可命名区域。patch 表示覆盖 hex。

## 地形与地点绑定

### 绑定模型

手绘地形暂不进入 `core_entities`。重要地形应该由自动抽取或手动创建进入世界对象库；地图地形层只负责可视化覆盖区。

为连接两者，新增地形区域绑定：

```text
map_terrain_bindings
- id
- novel_id
- map_id
- region_id
- location_entity_id
- binding_type         // footprint / influence
- review_state         // confirmed / candidate / needs_review / ignored
- source               // user_confirmed / suggested_by_overlap / suggested_by_name
- meta
- created_at
- updated_at
```

绑定类型：

- `footprint`：该地形区域就是地点本体范围。例如昆仑山脉、高天原、无底深渊。
- `influence`：该地形区域影响某地点。例如洛阳被结界覆盖、旧城被污染蔓延。

后续可扩展 `adjacent`、`barrier`、`source` 等，但第一版先保留两种。

### 绑定流程

- 用户手绘地形时，只生成 terrain region，不创建 `core_entity`。
- 如果后来系统自动抽取出“无底深渊”这个地点，地图提示“是否绑定到你之前画的深渊区域？”
- 用户确认后，写 `map_terrain_bindings(region_id, location_entity_id, binding_type)`。
- 一个地点可以绑定多个地形区域。
- 一个地形区域也可以绑定或影响多个地点。
- 如果地点被合并、忽略或改名，绑定标记为 `needs_review`，不自动删除手绘地形。

匹配建议来源：

- 名称相似。
- 地形素材类型相同。
- 空间重叠。
- 用户当前选中的地点。

绑定候选主入口放在地图检查器：

- 选中地形区域时，检查器显示“可能绑定到：昆仑山脉 / 无底深渊 / 洛阳”。
- 用户选择 `footprint` 或 `influence` 后确认绑定。
- 地点详情作为辅助入口，显示附近或重叠的未绑定地形区域。

### 命名

地形区域命名规则：

- 手绘时默认 `素材名 + 序号`，例如“结界 1”“深渊 2”。
- 绑定为 `footprint` 后，默认显示地点名，例如“昆仑山脉”。
- 绑定为 `influence` 后，显示“结界：影响洛阳”。
- 用户可以重命名地形区域，但重命名地形区域不修改世界对象名称。

### 世界事实同步

手绘地形保存后，默认只生成地图派生影响提示，不自动写世界事实。

例如“洛阳位于结界范围内”先显示为地图影响状态。用户明确点击 `同步修改数据库中的地理设定` 或 `记录为世界事实` 时，才写入世界事实层。

这与地点 `+ / -` 的同步规则保持一致：地图编辑默认不污染正史，用户确认后才沉淀为设定。

## 素材库

第一版不支持用户上传自定义素材，避免引入文件存储、格式校验、版权提示、缩略图生成、安全扫描和备份问题。

内置素材分两类：

- `kenney_builtin`：来自 Kenney Assets，主要覆盖基础地貌和通用地图元素。
- `project_builtin`：项目自制或生成补充素材，覆盖深渊、结界、灵气、污染、禁区、秘境等小说语义地形。

Kenney 资产用于基础地貌和通用元素；项目补充素材必须保持同一视觉风格，不能和 Kenney 基础素材割裂。

素材 manifest 建议字段：

```text
asset_key
label
category
source_type       // kenney_builtin / project_builtin
license
source_url
file_path
default_opacity
default_brush_size
tags
```

UI 不展示复杂版权信息，只在“关于/素材来源”里显示 Kenney 与 CC0，以及项目自制素材说明。

第一版素材分类：

```text
基础地貌：mountain, forest, water, desert, ruin
奇幻地貌：abyss, barrier, magic_field, danger_zone, corruption
结构地貌：road, gate, wall, bridge, city_area
效果覆盖：fog, storm, fire, ice, poison, sacred_light
```

## 检查器与辅助视图

第一版不做完整关系图视图。地图检查器只显示局部关系片段：

- 相邻地点。
- 包含地点。
- 绑定地形。
- 相关人物。
- 相关事件。
- 相关候选/事实状态。

完整关系图会把产品重心拉向图谱工具，也会引入 Cytoscape 类依赖压力。地图模块当前优先保持为地理关系编辑器。

## 前端实现建议

新增或扩展前端模块：

```text
frontend-console/views/mapQuickCreateView.js
frontend-console/views/mapGeoLayoutEngine.js
frontend-console/views/mapTerrainRenderer.js
frontend-console/views/mapTerrainAssets.js
```

实现边界：

- `mapGeoLayoutEngine.js` 以纯函数为主，输入节点、关系、锁定状态、占用半径、地图边界，输出位置、占用格、冲突列表、扩边建议和动画前后状态。
- 地图拖拽、吸附、锁定、`+ / -`、Undo/Redo 和命中查询优先收敛在现有地图视图与地形编辑模块中；只有出现第二个真实调用方时再拆独立交互引擎。
- 地形绘制模式、画笔、橡皮、图层状态和保存优先收敛在现有地图视图；只有出现第二个真实调用方时再拆独立地形编辑会话模块。
- `mapTerrainRenderer.js` 只负责地形图层渲染、边界平滑、图案点缀和查看/编辑模式差异。
- `mapTerrainAssets.js` 读取内置素材 manifest。

命中查询建议采用统一接口：

```js
queryMapObjectsAt(point, { mode, layers })
```

返回按 z-index 和交互优先级排序的地点、地形区域、人物标记、组织范围、事件标记等对象。不要把命中逻辑散在多个 Canvas 事件处理分支里。

## 后端实现建议

后端仍在 `backend/modules/world/` 内实现，不新增独立业务模块。

建议扩展：

```text
backend/modules/world/map_models.py
backend/modules/world/map_schemas.py
backend/modules/world/map_repositories.py
backend/modules/world/services/map_service.py
backend/modules/world/services/map_state_assembler.py
backend/modules/world/map_api.py
```

新增服务职责可以拆到独立文件，但仍归 `world/map` 拥有：

```text
backend/modules/world/services/map_quick_create.py
backend/modules/world/services/map_location_layout.py
backend/modules/world/services/map_terrain.py
```

API 方向：

```text
GET  /api/world/maps/quick-create/context
POST /api/world/maps/quick-create/preview
POST /api/world/maps/quick-create/confirm

GET  /api/world/maps/{map_id}/location-layouts
PUT  /api/world/maps/{map_id}/location-layouts

GET  /api/world/maps/{map_id}/terrain
PUT  /api/world/maps/{map_id}/terrain/layers/{layer_id}/patches
POST /api/world/maps/{map_id}/terrain/regions/{region_id}/bindings
PATCH /api/world/maps/{map_id}/terrain/bindings/{binding_id}
```

具体接口可在实现时按现有 map API 风格调整，但必须保持：

- `novel_id` 隔离。
- 候选和正式事实边界清晰。
- API 层薄，复杂编排下沉 service。
- 地图编辑默认不自动修改世界对象正史。

## 验收与测试

后端测试：

- 快速创建默认只使用 canonical 数据。
- 打开 `包含待确认候选` 后 candidate 数据进入预览但不自动转正。
- `map_location_layouts` 保存中心、半径和锁定状态。
- 剧情线、人物移动和 Scene 顺序不会改变地点布局结果。
- 用户确认移动解释后写入 `movement_explanation` 地图事实。
- 用户选择设定冲突后写入 open 状态的 `map_conflict`。
- 手动锁定布局与世界地理事实冲突时生成 `geo_fact_conflict`，但不自动修改世界事实。
- `保留布局差异` 只 suppress 当前地图冲突提示，不修改 canonical 地理设定。
- 地形 layer / region / patch 覆盖保存正确。
- 地形绑定区分 `footprint` 与 `influence`。
- 地形覆盖地点只生成派生提示，不自动写世界事实。
- `novel_id` 隔离覆盖所有新增查询和写入。

前端单元测试：

- GeoLayoutEngine 固定地点不被挤走。
- 未固定地点拖拽/放大后局部挤占、外扩、回填。
- 地图空间不足时生成扩边建议。
- 地形画笔保存最终 patches。
- Undo/Redo 在地点布局和地形绘制模式内独立工作。
- 命中查询按图层顺序返回对象。
- 剧情覆盖控件只高亮、筛选和显示轨迹，不触发 GeoLayoutEngine 重排。
- 远距离移动轨迹按状态显示 `传送`、`需解释` 或 `设定冲突` 等线条标签。
- 右侧检查器只显示地图决策相关的局部关系片段。

E2E 验收：

- 地图页点击快速创建，生成预览，拖拽地点，锁定，保存后重新打开位置保持。
- 地图中两个远距离地点保持地理距离；人物短时间移动只显示轨迹和解释标签，不把地点拉近。
- 用户在轨迹冲突上选择 `添加移动解释` 后，线条标签更新并刷新保持。
- 用户在地理事实冲突上选择 `保留布局差异` 后，不再反复弹窗，但检查器仍可查看该冲突。
- 地形绘制模式选择结界，按住左键拖拽绘制，Undo 后保存，刷新后地形仍存在。
- 地形覆盖地点后，地点仍可读，地点详情或检查器显示派生影响提示。
- 自动抽取或手动创建地点后，可把既有手绘地形区域绑定为 `footprint` 或 `influence`。

## 分阶段实施

### Phase 1：快速创建与地点布局

- 新增快速创建入口和预览。
- 新增 `map_location_layouts`。
- 实现 GeoLayoutEngine 的规则网格、锁定、占用半径、挤占补位和扩边建议。
- 保存后写入地图配置、地点绑定和布局。

### Phase 2：地形绘制

- 内置素材 manifest。
- 新增 terrain layer / region / patch。
- 实现画笔、橡皮、Undo/Redo、覆盖保存。
- 实现查看模式平滑渲染和编辑模式真实 hex 覆盖。

### Phase 3：地形绑定与检查器

- 新增 terrain binding。
- 检查器显示绑定候选。
- 地点详情显示附近或重叠的未绑定地形区域。
- 支持 `footprint` / `influence` 绑定和派生影响提示。

### Phase 4：体验增强

- 更丰富素材。
- 图层排序、透明度预设、低动效模式。
- 局部关系片段增强。
- 根据真实使用反馈再考虑布局历史、素材上传或 PixiJS 渲染层替换。

## 实现状态

2026-06-30 已完成第一轮增量实现：

- 后端新增 `map_location_layouts`、`map_terrain_layers`、`map_terrain_regions`、`map_terrain_patches`、`map_terrain_bindings` ORM、仓库、schema、迁移和 service。
- 后端新增快速创建 context / preview / confirm API；preview 不落库，confirm 一次只创建一张地图，默认只用 canonical，`include_candidates` 显式开启后才纳入候选；第一轮已让方向、远近、相邻和包含类地理关系参与地点布局，缺少关系时才回退为等距草稿并提示。
- 快速创建预览支持地点多选；前端默认全选，确认时只提交选中布局。后端保留旧的未传 `layouts` 全量创建语义，并把 `layouts=[]` 解释为不写任何地点输出。
- 后端新增 location layouts 与 terrain state / patch replace / binding API，并让 `MapStateResponse` 对旧地图返回空 layout/terrain 数组。
- 地形 patch 覆盖保存已支持重复保存同一 region，不会因同一 `region_id` 再次保存而主键冲突。
- 前端新增 quick-create modal 控制器、API 包装、GeoLayoutEngine、MapInteractionEngine、TerrainEditor、TerrainRenderer、TerrainAssets 和 StoryOverlay helper。
- `mapWorkspaceView` 已提供 `快速创建` 入口，modal 内可做基础位置微调、半径 `+/-`、锁定和撤销；confirm 使用用户当前预览状态落库。`mapView` 已能把手绘 terrain patches 渲染在地点层下方。
- 单元/服务测试已覆盖 canonical 默认、candidate 开关、地理关系影响布局、layout 保存、terrain patch 覆盖保存、同 region 重复保存、footprint/influence 绑定、命中查询、独立 Undo、剧情冲突标签和 suppress 语义。

仍需后续增强：

- 地图画布内的完整拖拽预览、地形绘制工具栏、TerrainEditor 接入生产工具栏、StoryOverlay 接入生产剧情覆盖控件，以及检查器绑定候选 UI 仍需继续打磨。
- 当时尚缺完整 quick-create + terrain 手绘 Playwright 流程；该缺口已在 2026-07-14 的分层编辑与统一保存 E2E 中补齐。

## 2026-07-14 一致性编辑与递归图层补充

本轮继续复用 Vanilla JS、Leaflet 1.9.4 CDN 和 Canvas，不改变 ADR-0003，也不新增独立
inspector 后端。地图作者入口由硬删除改为整棵子树归档/恢复；active 根地图与 active
同父子地图分别使用 PostgreSQL partial unique 约束名称，归档资产仍完整保留。

地图视觉写入以 `map_configs.editor_revision` 做 CAS。`POST /maps/{map_id}/editor/apply`
在一个事务中按顺序执行有类型的命令，临时创建资源用 `client_id` 引用；任一校验或写入失败
回滚整批，成功只递增一次 revision。旧视觉写入口仍保留，但每次成功写入递增一次，且与
统一入口共用 `novel_id + map_id + resource_id` 归属校验及递归锁定检查。

`map_layer_nodes` 成为图层局部 `visible/locked/opacity/sort_order/min_zoom/max_zoom` 的唯一
权威。有效显隐取祖先逻辑与，锁定取祖先逻辑或，透明度沿祖先相乘，zoom 取祖先区间交集；
空交集不绘制。terrain 旧字段只作兼容投影，新建/删除 terrain layer 同步维护一一对应 leaf。

世界对象反向定位通过只读 `GET /entities/{entity_id}/map-presence` 合并 layout 和 bindings，
默认排除归档地图与 candidate。地图端使用 typed selection；fact/observation 继续进入 dashboard
inspector。Canvas 增加视口裁剪、revision/viewport 缓存与单 RAF 调度；本轮保持地图 state
全量 tile wire shape。Playwright 在固定 Chromium 1280×720 视口下使用 200×200 地图，预热 20 帧、
采样 100 帧，生成 `map-canvas-performance.json`；视口裁剪相对同轮未裁剪基线平均帧耗时退化
超过 20% 才失败，不使用跨机器固定毫秒门限。

## 2026-07-14 楼层与连续线路补充

递归图层 group 新增 `normal/exclusive/floor` 模式和直接子层 `floor_level`。模式与楼层编号
属于持久化树结构；每个 group 的当前子层和 isolate 属于前端会话状态，通过 route 与按
novel/map 隔离的 localStorage 恢复，不写入 `editor_revision`。嵌套 group 沿全部祖先选择
共同决定有效可见性，isolate 只过滤绘制和命中，不改变服务端锁定。

道路和水系使用 `map_path_layers/map_paths/map_path_nodes` 保存连续轴向几何，继续由 Canvas 2D
渲染，Leaflet 只承担视口。线路图层显示名称和显示属性由 tree leaf 唯一拥有；线路本体保存
类型、样式、控制点、可选 canonical 地点端点和 `content_revision`。地点布局只提供显式吸附
目标，地点移动不会静默重写线路。

线路写入复用 `POST /maps/{map_id}/editor/apply` 的 CAS 与单事务。正式资源 ID 由服务端生成，
同批资源通过请求级唯一 client ID 引用；创建、修改、归档、恢复和空 layer 删除均先校验
`novel_id + map_id`、递归锁定、容量、有限坐标、类别和最终图层树。线路只归档，避免破坏
Observation/Fact 的稳定空间引用。

`MapSpatialAnchor` 对 map/path/location/hex 字段进行类型化校验。Fact 确认时保存 path ID、
内容 revision、名称和代表点；后续线路更新不改写历史事实，Playback 比较 revision 并可用
只读方式高亮归档几何。deep import 无法解析的 path 引用不会入库，而是在 observation 来源
metadata 中留下 `invalid_spatial_anchor` 诊断。
