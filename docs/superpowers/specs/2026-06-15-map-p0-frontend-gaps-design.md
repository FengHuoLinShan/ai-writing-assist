# 动态地图 P0 前端偏差修复设计

## 1. 背景与目标

PRD `docs/references/map-prd-v1.1.md` 的 P0 能力已在后端和前端完成主体实现，但文末“已知前端偏差”列出 7 项前端体验缺口。本次设计目标是在不改动后端架构、不引入新依赖的前提下，一次性补齐这 7 项偏差，使 P0 地图功能闭环。

待修复偏差：

1. **Layer 6 气泡/提示**：悬停六边形无 tooltip 提示。
2. **右侧详情面板**：点击地点中心仅 toast，无名称/摘要/绑定格数/下钻按钮的面板。
3. **pending 格视觉反馈**：`_redrawPending` 为空实现，画笔点击后无半透明高亮。
4. **画笔拖拽绘制**：仅支持点击，不支持拖拽连线绘制。
5. **地点绑定批量保存**：当前逐格即时调 API，非“应用”批量保存。
6. **删除地图前端入口**：列表无删除按钮 + 二次确认。
7. **地图元信息编辑 UI**：无改名/改描述入口（API 已就绪）。

## 2. 方案选择

### 2.1 候选方案

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| A. 最小补丁式 | 直接在 `mapView.js` 逐个添加功能 | 改动集中、快速 | `mapView.js` 进一步膨胀，状态与渲染耦合 |
| B. 先整理状态层 | 扩展 `mapState.js` 统一承载 pending/drag/hover/selected，再修复渲染和交互 | 边界清晰、易测试、为 P1 留扩展位 |  upfront 改动稍多 |
| C. 分两批迭代 | 第一批浏览体验，第二批编辑体验 | 风险低、验收快 | 需要两次开发/测试周期 |

### 2.2 决策

**采用方案 B：先整理状态层，再统一修复。**

理由：
- 与 PRD §5 的“状态层”设计一致。
- 批量绑定、拖拽绘制、pending 高亮都依赖统一的状态抽象，补丁式会导致多处重复。
- `mapView.js` 已经接近 700 行，继续堆积会增加维护成本。

### 2.3 用户反馈纳入

- tooltip 采用 **Leaflet popup** 而非自定义 DOM，随地图平移/缩放自动跟随。

## 3. 状态层设计（mapState.js）

### 3.1 新增状态域

```javascript
export const mapState = {
  // ... 原有字段 ...

  /** 待应用的地点绑定变更（key=`q,r` → {hex_q,hex_r,is_center,location_entity_id}） */
  pendingBindings: {},

  /** 拖拽绘制状态 */
  dragDrawing: false,
  /** 上次拖拽命中的 hex，避免同一格重复 stage */
  lastDragHex: null,

  /** 当前鼠标悬停的 hex（用于 tooltip 和高亮） */
  hoveredHex: null,
  /** 当前选中的 hex（用于右侧面板） */
  selectedHex: null,
}
```

### 3.2 新增纯函数

- `stageBindingChange(entityId, q, r, isCenter)`：把一次绑定变更加入 pending；再次点击同一格视为取消。
- `consumePendingBindings()`：取出所有 pendingBindings，清空队列，返回数组。
- `setHoveredHex(q, r)` / `clearHoveredHex()`。
- `setSelectedHex(q, r)` / `clearSelectedHex()`。
- `startDragDraw()` / `endDragDraw()` / `recordDragHex(q, r)`：用于拖拽去重。
- `resetMapState()` 扩展：同时清空上述新状态。

## 4. 渲染层设计

### 4.1 mapHexRenderer.js 新增绘制函数

- `drawPendingTerrain(ctx, pendingChanges, size, offsetX, offsetY)`：在已有地形上叠加 30% 透明度同色系填充，提示“待应用”。
- `drawPendingBindings(ctx, pendingBindings, size, offsetX, offsetY)`：虚线框 + 中心格星标，与已绑定格区分。
- `drawHoverHighlight(ctx, q, r, size, offsetX, offsetY)`：鼠标所在 hex 白色描边高亮。

### 4.2 右侧详情面板（mapView.js）

- 在 `.map-container` 右侧新增 `.map-detail-panel`，宽度 240px，绝对定位或 flex 布局。
- 点击地点中心 hex：显示地点名称、摘要、绑定格数、下钻按钮（有详图则“进入详图”，无则“创建详图”）。
- 点击无地点 hex：显示地形类型、坐标。
- 所有动态文本通过 `esc()` 转义后写入 DOM text/attribute，不直接写 `innerHTML`。

### 4.3 Tooltip

- 使用 Leaflet `L.popup()` 绑定到 hex 像素坐标。
- 浏览模式下，鼠标悬停 300ms 后弹出：
  - 有地点绑定：显示地点名 +（中心）标记。
  - 无地点：显示地形类型。
- 编辑模式下 tooltip 可关闭或显示简略坐标，避免干扰编辑。

## 5. 交互层设计

### 5.1 拖拽绘制

- `canvas` 监听 `mousedown`、`mousemove`、`mouseup`。
- `mousedown`：进入拖拽状态，记录起始 hex。
- `mousemove`（brush 工具）：把新进入的 hex 加入 `pendingTerrainChanges`，触发 `_redraw()`。
- `mousemove`（bind 工具）：把新进入的 hex 加入 `pendingBindings`。
- `mouseup`：退出拖拽状态。
- 每次 `stage` 前检查 `lastDragHex`，避免同一事件周期内重复写入。

### 5.2 地点绑定批量保存

- bind 工具下，点击/拖拽的 hex 进入 `pendingBindings`，不立即调 API。
- 编辑面板“应用”按钮统一处理：
  - 先 `consumePendingTerrainChanges()` 批量更新地形。
  - 再 `consumePendingBindings()` 批量创建/更新绑定（当前 P0 采用全量 POST 新绑定；如格子已绑定其他地点，先 DELETE 再 POST）。
- 失败时保留 pending，toast 错误，不重载 state，允许用户继续调整。
- 编辑面板显示 pending 绑定计数。

### 5.3 撤销与保存

- `Ctrl+Z` 仍只撤销最近一次“应用”的 terrain 变更（PRD 偏差修复说明 #7）。
- 未应用的 pendingBindings 不支持撤销，但可逐格点击取消。
- “保存并退出编辑”先应用所有 pending，再切回浏览模式。

## 6. 地图管理 UI

### 6.1 删除地图

- 地图列表每行增加“删除”按钮。
- 点击调用 `confirmAction("确定删除地图？该操作不可恢复，子地图将变为顶层地图。", ...)`。
- 确认后调 `api.world.deleteMap(mapId, novelId)`，成功后刷新列表。

### 6.2 地图元信息编辑

- 已打开地图的工具栏增加“地图设置”按钮。
- 弹出 modal：名称、描述输入框。
- 确认后调 `api.world.updateMap(mapId, {name, description}, novelId)`。
- P0 不开放修改尺寸、类型等字段。

## 7. 文件改动范围

```
frontend-console/views/mapState.js          # 扩展状态域与纯函数
frontend-console/views/mapHexRenderer.js    # 新增 pending/悬停绘制函数
frontend-console/views/mapEditPanel.js      # 显示 pending 绑定计数
frontend-console/views/mapView.js           # 渲染、事件、详情面板、tooltip、拖拽、管理 UI
frontend-console/styles.css                 # 右侧面板、pending 样式、设置 modal
frontend-console/tests/mapView.test.js      # 补充/更新测试
backend/modules/world/map_schemas.py        # 不改动（已有 update/delete API）
backend/modules/world/map_api.py            # 不改动
```

## 8. 测试策略

- 单元测试聚焦 `mapState.js` 的纯函数：
  - `stageBindingChange` 去重与取消逻辑。
  - `consumePendingBindings` 清空队列。
  - 拖拽去重逻辑。
- `mapHexRenderer.js` 绘制函数做轻量断言（canvas 调用次数/参数）。
- `mapView.js` 通过现有 `frontend-console/tests/setup.js` 的 DOM + Leaflet mock 验证：
  - 点击中心点打开右侧面板。
  - 删除按钮触发 `confirmAction`。
  - 设置 modal 调用 `updateMap`。

## 9. 风险与边界

- **Leaflet popup 性能**：悬停 tooltip 频繁创建/销毁 popup，300ms debounce 控制频率。
- **拖拽与点击冲突**：拖拽结束后不触发 click；通过 `dragDrawing` 状态区分。
- **批量绑定失败恢复**：保留 pending 状态，用户可重试或继续编辑。
- **不改动后端**：依赖现有 `updateMap`/`deleteMap` API；如测试发现字段缺失再评估。
- **右侧面板空间**：小屏下右侧面板可能压缩地图，CSS 使用 `min-width` 和可选折叠（P0 不做折叠，仅保证不溢出）。

## 10. 验收标准

- [ ] 悬停任意 hex 显示 Leaflet popup 提示。
- [ ] 点击地点中心显示右侧面板，含名称、摘要、绑定格数、下钻/创建详图按钮。
- [ ] 画笔/油漆桶 pending 变更在 canvas 上半透明高亮。
- [ ] brush 工具支持按住鼠标拖拽绘制连续格子。
- [ ] bind 工具下点击/拖拽的格子进入 pending，点击“应用”批量保存。
- [ ] 地图列表支持删除按钮 + 二次确认。
- [ ] 已打开地图支持“地图设置”修改名称和描述。
- [ ] 所有受影响前端测试通过；如新增测试失败则修复。
