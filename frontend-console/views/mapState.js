/**
 * 地图子视图会话状态 — PRD docs/PRD-动态地图功能.md
 *
 * 仅持有前端会话状态（编辑工具、待应用变更、撤销栈），不持久化。
 * 地图数据本身由后端 MapStateResponse 提供，缓存在 mapView._state。
 */

/** 地图会话状态 */
export const mapState = {
  /** 当前查看/编辑的地图 ID */
  currentMapId: null,
  /** 当前模式：browse（浏览）/ edit（编辑） */
  mode: "browse",
  /** 编辑工具：brush（地形画笔）/ bucket（油漆桶）/ bind（地点绑定）/ territory（势力范围） */
  activeTool: "brush",
  /** 画笔选中的地形（brush/bucket 工具用） */
  selectedTerrain: "grassland",
  /** 地点绑定工具选中的实体 ID */
  selectedLocationEntityId: null,
  /** 待应用的地形变更（key=`q,r` → {hex_q,hex_r,terrain_type,elevation}） */
  pendingTerrainChanges: {},
  /** 撤销栈：每个元素是一次 apply 的变更快照（用于 Ctrl+Z） */
  undoStack: [],
  /** 待应用的地点绑定变更（key=`q,r` → {location_entity_id,hex_q,hex_r,is_center}） */
  pendingBindings: {},
  /** 是否处于拖拽绘制状态 */
  dragDrawing: false,
  /** 上一次拖拽经过的格子 key=`q,r`，用于去重 */
  lastDragHex: null,
  /** 当前鼠标悬停的六边形 {hex_q,hex_r} */
  hoveredHex: null,
  /** 当前选中的六边形 {hex_q,hex_r} */
  selectedHex: null,
  /** 地点绑定是否为中心格模式 */
  bindCenterMode: false,
  /** 当前选中 scene id */
  currentSceneId: null,
  /** 所有可用 scene 列表 */
  sceneList: [],
  /** 当前 scene 信息 */
  currentScene: null,
  /** 标记工具：选中的标记类型 */
  selectedMarkerType: "character",
  /** 标记工具：选中的实体 ID */
  selectedMarkerEntityId: null,
  /** 标记工具：自定义标签 */
  selectedMarkerLabel: "",
  // === P2: 势力范围与聚焦模式 ===
  /** 当前地图的势力范围列表 */
  territories: [],
  /** 是否处于聚焦模式 */
  focusMode: false,
  /** 聚焦模式关联的实体 ID */
  focusEntityId: null,
  /** 聚焦模式下关联的六边形坐标集合（key=`q,r`） */
  focusRelatedHexes: new Set(),
  /** 当前选中的 faction ID（势力范围编辑用） */
  selectedFactionId: null,
  /** faction ID → 自定义颜色的映射 */
  factionColors: {},
}

/** 重置会话状态（切换地图时调用） */
export function resetMapState() {
  mapState.currentMapId = null
  mapState.mode = "browse"
  mapState.activeTool = "brush"
  mapState.selectedTerrain = "grassland"
  mapState.selectedLocationEntityId = null
  mapState.pendingTerrainChanges = {}
  mapState.undoStack = []
  mapState.pendingBindings = {}
  mapState.dragDrawing = false
  mapState.lastDragHex = null
  mapState.hoveredHex = null
  mapState.selectedHex = null
  mapState.bindCenterMode = false
  mapState.currentSceneId = null
  mapState.sceneList = []
  mapState.currentScene = null
  mapState.selectedMarkerType = "character"
  mapState.selectedMarkerEntityId = null
  mapState.selectedMarkerLabel = ""
  // P2 reset
  mapState.territories = []
  mapState.focusMode = false
  mapState.focusEntityId = null
  mapState.focusRelatedHexes = new Set()
  mapState.selectedFactionId = null
  mapState.factionColors = {}
}

/**
 * 记录一次地形画笔/油漆桶的本地变更（不立即提交）。
 * @param {number} q
 * @param {number} r
 * @param {string} terrainType
 * @param {number} [elevation]
 */
export function stageTerrainChange(q, r, terrainType, elevation) {
  const key = `${q},${r}`
  mapState.pendingTerrainChanges[key] = {
    hex_q: q,
    hex_r: r,
    terrain_type: terrainType,
    ...(elevation !== undefined ? { elevation } : {}),
  }
}

/** 取出并清空待应用变更，压入撤销栈。返回 changes 数组。 */
export function consumePendingChanges() {
  const changes = Object.values(mapState.pendingTerrainChanges)
  if (changes.length > 0) {
    mapState.undoStack.push(changes)
  }
  mapState.pendingTerrainChanges = {}
  return changes
}

/** 弹出最近一次 apply 的变更（撤销）。返回 changes 数组或 null。 */
export function popUndo() {
  return mapState.undoStack.pop() || null
}

/**
 * 记录一次地点绑定变更（不立即提交）。
 * 同一 entityId + 同一格子 + 同一 is_center 再次点击则取消。
 * @param {string} entityId
 * @param {number} q
 * @param {number} r
 * @param {boolean} isCenter
 */
export function stageBindingChange(entityId, q, r, isCenter) {
  const key = `${q},${r}`
  if (mapState.pendingBindings[key] &&
      mapState.pendingBindings[key].location_entity_id === entityId &&
      mapState.pendingBindings[key].is_center === isCenter) {
    delete mapState.pendingBindings[key]
    return
  }
  mapState.pendingBindings[key] = {
    location_entity_id: entityId,
    hex_q: q,
    hex_r: r,
    is_center: isCenter,
  }
}

/**
 * 取出并清空待应用绑定变更。返回 bindings 数组。
 *
 * 说明：绑定 pending 变更不进入 `undoStack`。它们在应用时通过 API 立即提交；
 * 对于尚未应用的绑定，撤销操作通过清空 `pendingBindings` 实现（将在 mapView._undo 中实现，Task 7）。
 */
export function consumePendingBindings() {
  const bindings = Object.values(mapState.pendingBindings)
  mapState.pendingBindings = {}
  return bindings
}

/** 设置当前悬停六边形 */
export function setHoveredHex(q, r) {
  mapState.hoveredHex = { hex_q: q, hex_r: r }
}

/** 清除悬停六边形 */
export function clearHoveredHex() {
  mapState.hoveredHex = null
}

/** 设置当前选中六边形 */
export function setSelectedHex(q, r) {
  mapState.selectedHex = { hex_q: q, hex_r: r }
}

/** 清除选中六边形 */
export function clearSelectedHex() {
  mapState.selectedHex = null
}

/** 开始拖拽绘制 */
export function startDragDraw() {
  mapState.dragDrawing = true
  mapState.lastDragHex = null
}

/** 结束拖拽绘制 */
export function endDragDraw() {
  mapState.dragDrawing = false
  mapState.lastDragHex = null
}

/**
 * 记录拖拽经过的格子，返回是否为新格子（用于去重）。
 * @param {number} q
 * @param {number} r
 * @returns {boolean}
 */
export function recordDragHex(q, r) {
  const key = `${q},${r}`
  if (mapState.lastDragHex === key) return false
  mapState.lastDragHex = key
  return true
}

export function setCurrentScene(sceneId) {
  mapState.currentSceneId = sceneId
}

// === P2: 聚焦模式与势力范围辅助函数 ===

/**
 * 设置或清除聚焦模式。
 * @param {boolean} enabled
 * @param {string|null} [entityId]
 */
export function setFocusMode(enabled, entityId) {
  mapState.focusMode = enabled
  mapState.focusEntityId = enabled ? entityId : null
  if (!enabled) {
    mapState.focusRelatedHexes = new Set()
  }
}

/**
 * 设置聚焦模式下关联的六边形集合。
 * @param {Array<{hex_q:number,hex_r:number}>} hexes
 */
export function setFocusRelatedHexes(hexes) {
  mapState.focusRelatedHexes = new Set((hexes || []).map((h) => `${h.hex_q},${h.hex_r}`))
}

/** 清除聚焦状态 */
export function clearFocus() {
  mapState.focusMode = false
  mapState.focusEntityId = null
  mapState.focusRelatedHexes = new Set()
}

/**
 * 设置当前选中的 faction ID。
 * @param {string|null} factionId
 */
export function setSelectedFaction(factionId) {
  mapState.selectedFactionId = factionId
}

/**
 * 设置 faction 的自定义颜色。
 * @param {string} factionId
 * @param {string} color 十六进制颜色字符串（如 "#FF0000"）
 */
export function setFactionColor(factionId, color) {
  mapState.factionColors[factionId] = color
}

export default mapState
