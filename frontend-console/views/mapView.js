/**
 * 地图主视图 — PRD docs/PRD-动态地图功能.md §5
 *
 * 作为 worldView 的"地图"子视图渲染容器。
 * 由 worldView._renderMap() 提供 #map-root 容器，本模块 mount() 命令式构建 Leaflet。
 *
 * 模式：
 * - 列表空 → 创建世界地图（showModal 表单）
 * - 浏览模式：显示中心标签、点击下钻、面包屑导航
 * - 编辑模式：侧边栏（画笔/油漆桶/地点绑定）、撤销、应用、保存
 *
 * 安全：所有动态文本（地图名、地点名、地形名）通过 esc() 转义后入 innerHTML。
 */
import {
  drawTerrain,
  drawBindings,
  drawPendingTerrain,
  drawPendingBindings,
  drawHoverHighlight,
  drawCandidateBindings,
  drawCandidateMarkers,
  drawCandidateTerritories,
  drawContextHighlights,
  drawMarkers,
  drawTerritories,
  hashColor,
  hexToPixel,
  pixelToHex,
  floodFillTerrain,
  TERRAIN_COLORS,
} from "./mapHexRenderer.js"
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "./mapEditPanel.js"
import { buildMapLayout } from "./mapLayoutEngine.js"
import { drawTerrainLayers } from "./mapTerrainRenderer.js"
import {
  bulkResultMessage,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  renderBulkToolbar,
  renderSelectionCell,
  renderSelectionHeader,
  runBulkAction,
  selectedItemsFrom,
  syncBulkSelectionUi,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../shared/bulkSelection.js"
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import {
  mapState,
  resetMapState,
  stageTerrainChange,
  stageBindingChange,
  consumePendingChanges,
  setCurrentScene,
  setFocusMode,
  setFocusRelatedHexes,
  clearFocus,
  setSelectedFaction,
  setFactionColor,
  setSelectedHex,
  setHoveredHex,
  clearHoveredHex,
  startDragDraw,
  endDragDraw,
  recordDragHex,
} from "./mapState.js"

const mapView = {
  /** @type {any|null} Leaflet map 实例 */
  _leaflet: null,
  /** @type {HTMLCanvasElement|null} 自定义地形 canvas overlay */
  _canvas: null,
  /** @type {CanvasRenderingContext2D|null} */
  _ctx: null,
  /** 当前地图聚合状态（MapStateResponse） */
  _state: null,
  /** 当前 novel 下的地图列表 */
  _maps: [],
  _mapsLoadError: null,
  _tileByHex: new Map(),
  _bindingByHex: new Map(),
  _bindingCountByEntityId: new Map(),
  _locationById: new Map(),
  _detailMapByEntityId: new Map(),
  _indexedState: null,
  _indexedLocations: null,
  _indexedMaps: null,
  _redrawFrame: null,
  _labelsDirty: true,
  _bulkSelections: {},
  /** 可绑定的 location 实体列表 */
  _locations: [],
  /** 所有实体列表（用于标记下拉） */
  _allEntities: [],
  /** canvas 偏移（地图坐标原点到画布原点），用于平移 */
  _offset: { x: 0, y: 0 },
  /** 浏览模式 tooltip 防抖 timer */
  _tooltipDebounceTimer: null,
  /** render 延迟绑定 timer */
  _pendingTimers: new Set(),
  /** Leaflet popup 实例 */
  _tooltipPopup: null,
  /** 拖拽绘制中是否已移动到新格（用于区分单击和拖拽） */
  _dragMoved: false,
  /** 当前侧边栏筛选模式 ("all" | "location") */
  _currentFilter: "all",
  /** 当前挂载容器 ID */
  _mountRootId: "map-root",
  /** 一级地图工作台传入的打开上下文 */
  _mountContext: {},

  // ============================================================
  // 生命周期：由 worldView 调用
  // ============================================================

  /**
   * 挂载到容器。worldView._renderMap 提供 #map-root 后调用。
   * @param {string} rootId
   * @param {object} context
   */
  async mount(rootId, context = {}) {
    this._mountRootId = rootId
    this._mountContext = context || {}
    if (!window.L) {
      const root = document.getElementById(rootId)
      if (root) root.innerHTML = `<div class="empty-state"><div class="empty-icon" style="color:var(--danger);">&#9888;</div><p>地图引擎加载失败</p><p style="color:var(--text-dim);font-size:12px;">Leaflet 未加载，请检查网络连接（ADR-0003）</p></div>`
      return
    }
    await this._loadMaps()
    if (context.mapId) {
      await this._loadMapState(context.mapId, context.sceneId || null)
      await Promise.all([
        this._loadLocations(),
        this._loadAllEntities(),
        this._loadScenes(),
      ])
      if (context.sceneId) setCurrentScene(context.sceneId)
      if (context.focusEntityId && this._focusEntityHasTerritory(context.focusEntityId)) {
        setFocusMode(true, context.focusEntityId)
        await this._loadFocusState(context.focusEntityId)
      }
    } else {
      await this._loadScenes()
    }
    this._render(rootId)
  },

  /** 退出时清理 Leaflet 实例 */
  unmount() {
    this._clearPendingTimers()
    this._teardownInteractiveSurface()
    this._state = null
    resetMapState()
  },

  _defer(fn) {
    const timer = setTimeout(() => {
      this._pendingTimers.delete(timer)
      fn()
    }, 0)
    this._pendingTimers.add(timer)
    return timer
  },

  _clearPendingTimers() {
    for (const timer of this._pendingTimers) {
      clearTimeout(timer)
    }
    this._pendingTimers.clear()
  },

  _teardownInteractiveSurface() {
    if (this._tooltipDebounceTimer) {
      clearTimeout(this._tooltipDebounceTimer)
      this._tooltipDebounceTimer = null
    }
    if (this._tooltipPopup) {
      if (this._leaflet) this._leaflet.closePopup(this._tooltipPopup)
      this._tooltipPopup = null
    }
    if (this._leaflet) {
      this._leaflet.remove()
      this._leaflet = null
    }
    if (this._redrawFrame) {
      cancelAnimationFrame(this._redrawFrame)
      this._redrawFrame = null
    }
    this._canvas = null
    this._ctx = null
    if (this._keyHandler) {
      document.removeEventListener("keydown", this._keyHandler)
      this._keyHandler = null
    }
  },

  // ============================================================
  // 数据加载
  // ============================================================

  async _loadMaps() {
    this._mapsLoadError = null
    if (!state.currentProjectId) {
      this._maps = []
      this._rebuildIndexes()
      return
    }
    try {
      const data = await api.world.listMaps({ novel_id: state.currentProjectId })
      this._maps = data.items || []
      this._rebuildIndexes()
    } catch (err) {
      this._maps = []
      this._mapsLoadError = err?.message || "加载失败"
      this._rebuildIndexes()
      toast("地图列表加载失败，可稍后重试", "warning")
    }
  },

  async _loadMapState(mapId, sceneId = mapState.currentSceneId) {
    try {
      this._state = await api.world.getMapState(mapId, state.currentProjectId, sceneId)
      resetMapState()
      mapState.currentMapId = mapId
      if (sceneId) setCurrentScene(sceneId)
      this._rebuildIndexes()
      this._notifyMapOpened()
    } catch (err) {
      toast(`加载地图失败：${err.message}`, "error")
      this._state = null
      this._rebuildIndexes()
    }
  },

  async _reloadMapStatePreservingSession(mapId, sceneId = mapState.currentSceneId) {
    const session = {
      mode: mapState.mode,
      activeTool: mapState.activeTool,
      selectedTerrain: mapState.selectedTerrain,
      selectedLocationEntityId: mapState.selectedLocationEntityId,
      bindCenterMode: mapState.bindCenterMode,
      currentSceneId: mapState.currentSceneId,
      sceneList: mapState.sceneList,
      currentScene: mapState.currentScene,
      selectedMarkerType: mapState.selectedMarkerType,
      selectedMarkerEntityId: mapState.selectedMarkerEntityId,
      selectedMarkerLabel: mapState.selectedMarkerLabel,
      focusMode: mapState.focusMode,
      focusEntityId: mapState.focusEntityId,
      focusRelatedHexes: new Set(mapState.focusRelatedHexes),
      selectedFactionId: mapState.selectedFactionId,
      factionColors: { ...mapState.factionColors },
    }

    await this._loadMapState(mapId, sceneId)

    mapState.mode = session.mode
    mapState.activeTool = session.activeTool
    mapState.selectedTerrain = session.selectedTerrain
    mapState.selectedLocationEntityId = session.selectedLocationEntityId
    mapState.bindCenterMode = session.bindCenterMode
    mapState.currentSceneId = session.currentSceneId
    mapState.sceneList = session.sceneList
    mapState.currentScene = session.currentScene
    mapState.selectedMarkerType = session.selectedMarkerType
    mapState.selectedMarkerEntityId = session.selectedMarkerEntityId
    mapState.selectedMarkerLabel = session.selectedMarkerLabel
    mapState.focusMode = session.focusMode
    mapState.focusEntityId = session.focusEntityId
    mapState.focusRelatedHexes = session.focusRelatedHexes
    mapState.selectedFactionId = session.selectedFactionId
    mapState.factionColors = session.factionColors
  },

  async _loadLocations() {
    this._locations = await this._listAllEntities({ entity_type: "location" }).catch(() => [])
    this._rebuildIndexes()
  },

  async _loadScenes() {
    if (!state.currentProjectId) return
    try {
      const data = await api.outline.listScenesOrdered(state.currentProjectId)
      mapState.sceneList = (data.items || data || []).map((s) => ({
        id: s.id,
        index: s.scene_index,
        title: s.title || `Scene ${s.scene_index}`,
      }))
    } catch {
      mapState.sceneList = []
    }
  },

  async _loadAllEntities() {
    if (!state.currentProjectId) return
    const types = ["character", "event", "item", "location", "organization"]
    const results = await Promise.all(
      types.map((t) => this._listAllEntities({ entity_type: t }).catch(() => []))
    )
    this._allEntities = results.flat()
    this._rebuildIndexes()
  },

  _hexKey(q, r) {
    return `${q}:${r}`
  },

  _tileAt(q, r) {
    const key = this._hexKey(q, r)
    this._ensureIndexes()
    return this._tileByHex.get(key) || null
  },

  _bindingAt(q, r) {
    const key = this._hexKey(q, r)
    this._ensureIndexes()
    return this._bindingByHex.get(key) || null
  },

  _ensureIndexes() {
    if (
      this._indexedState !== this._state
      || this._indexedLocations !== this._locations
      || this._indexedMaps !== this._maps
    ) {
      this._rebuildIndexes()
    }
  },

  _rebuildIndexes() {
    const stateData = this._state || {}
    this._tileByHex = new Map((stateData.tiles || []).map((tile) => [
      this._hexKey(tile.hex_q, tile.hex_r),
      tile,
    ]))
    this._bindingByHex = new Map((stateData.location_bindings || []).map((binding) => [
      this._hexKey(binding.hex_q, binding.hex_r),
      binding,
    ]))
    this._bindingCountByEntityId = new Map()
    for (const binding of stateData.location_bindings || []) {
      const id = binding.location_entity_id
      if (!id) continue
      this._bindingCountByEntityId.set(id, (this._bindingCountByEntityId.get(id) || 0) + 1)
    }
    this._markersByHex = new Map()
    this._eventMarkersBySceneId = new Map()
    this._eventMarkersHead = []
    for (const marker of stateData.markers || []) {
      if (!marker.visible) continue
      const key = this._hexKey(marker.hex_q, marker.hex_r)
      const markersAtHex = this._markersByHex.get(key) || []
      markersAtHex.push(marker)
      this._markersByHex.set(key, markersAtHex)
      if (marker.marker_type === "event" && marker.start_scene_id) {
        if (this._eventMarkersHead.length < 3) this._eventMarkersHead.push(marker)
        const sceneEvents = this._eventMarkersBySceneId.get(marker.start_scene_id) || []
        sceneEvents.push(marker)
        this._eventMarkersBySceneId.set(marker.start_scene_id, sceneEvents)
      }
    }
    this._locationById = new Map((this._locations || []).map((location) => [
      location.id,
      location,
    ]))
    this._detailMapByEntityId = new Map(
      (this._maps || [])
        .filter((map) => map.parent_entity_id)
        .map((map) => [map.parent_entity_id, map])
    )
    this._indexedState = this._state
    this._indexedLocations = this._locations
    this._indexedMaps = this._maps
    this._labelsDirty = true
  },

  async _loadMapDynamicState(sceneId = mapState.currentSceneId) {
    if (!this._state?.map?.id) return
    const dynamic = await api.world.getMapDynamicState(
      this._state.map.id,
      state.currentProjectId,
      sceneId,
    )
    this._applyDynamicState(dynamic)
  },

  _applyDynamicState(dynamic) {
    if (!this._state) return
    this._state = {
      ...this._state,
      markers: dynamic.markers || [],
      territories: dynamic.territories || [],
      candidate_location_bindings: dynamic.candidate_location_bindings || [],
      candidate_markers: dynamic.candidate_markers || [],
      candidate_territories: dynamic.candidate_territories || [],
      scene: dynamic.scene || null,
    }
    this._labelsDirty = true
  },

  /**
   * 分页拉取世界对象，避免 limit 超过后端 MAX_PAGE_SIZE 导致 422。
   */
  async _listAllEntities(baseParams) {
    if (!state.currentProjectId) return []
    const all = []
    const limit = 50
    let skip = 0
    while (true) {
      const data = await api.world.listEntities({
        ...baseParams,
        novel_id: state.currentProjectId,
        skip,
        limit,
      })
      const items = data.items || data || []
      all.push(...items)
      if (items.length < limit) break
      skip += limit
    }
    return all
  },

  // ============================================================
  // 渲染
  // ============================================================

  _render(rootId) {
    this._clearPendingTimers()
    const root = document.getElementById(rootId)
    if (!root) return

    if (this._maps.length === 0 && !this._state) {
      // 空列表：显示创建入口
      root.innerHTML = this._renderEmpty()
      this._defer(() => this._bindListEvents())
      return
    }

    if (!this._state) {
      // 有列表但未选地图：显示列表
      root.innerHTML = this._renderList()
      this._defer(() => this._bindListEvents())
      return
    }

    // 已选地图：渲染地图视图
    root.innerHTML = this._renderMapShell()
    this._defer(() => this._initLeaflet())
    this._defer(() => this._bindMapEvents())
  },

  _renderEmpty() {
    return `
      <div class="map-toolbar">
        <button class="btn btn-primary" data-action="map-create-world">+ 创建世界地图</button>
      </div>
      ${this._mapsLoadError ? `
        <div class="empty-state" role="alert">
          <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
          <p>地图列表加载失败</p>
          <p style="color:var(--text-dim);font-size:12px;">可稍后重试。错误信息：${esc(this._mapsLoadError)}</p>
        </div>
      ` : `
      <div class="empty-state">
        <div class="empty-icon">&#9744;</div>
        <p>暂无地图</p>
        <p style="color:var(--text-dim);font-size:12px;">创建第一张世界地图开始构建你的世界</p>
      </div>
      `}
    `
  },

  _renderList() {
    const scope = "map-list"
    const ids = this._maps.map((m) => m.id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)
    const rows = this._maps.map((m) => `
      <tr class="clickable" data-action="map-open" data-id="${esc(m.id)}">
        <td class="selection-cell">${renderSelectionCell(this, scope, m.id, `选择 ${m.name || "地图"}`)}</td>
        <td>${esc(m.name)}</td>
        <td>${esc(m.map_type)}</td>
        <td>${m.grid_width}×${m.grid_height}</td>
        <td>
          <button class="btn btn-sm" data-action="map-open" data-id="${esc(m.id)}">打开</button>
          <button class="btn btn-sm btn-danger" data-action="map-delete" data-id="${esc(m.id)}">删除</button>
        </td>
      </tr>
    `).join("")
    return `
      <div class="map-toolbar">
        <button class="btn btn-primary" data-action="map-create-world">+ 创建世界地图</button>
      </div>
      ${renderBulkToolbar(this, scope, [
        { action: "delete-maps", label: "批量删除地图", className: "btn-danger" },
      ], { noun: "地图", hint: "只处理当前地图列表" })}
      <table class="data-table">
        <thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前地图")}</th><th>名称</th><th>类型</th><th>尺寸</th><th>操作</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `
  },

  _renderSceneBar() {
    const scenes = mapState.sceneList
    if (!scenes || scenes.length === 0) {
      return `<div class="map-scene-bar"><span class="map-scene-hint">暂无 Scene 数据（需先创建大纲 Scene）</span></div>`
    }
    const currentIdx = scenes.findIndex((s) => s.id === mapState.currentSceneId)
    const sceneLabel = currentIdx >= 0
      ? `Scene ${scenes[currentIdx].index}: ${esc(scenes[currentIdx].title || "")}`
      : "选择 Scene"

    return `
      <div class="map-scene-bar">
        <button class="btn btn-sm" data-action="map-scene-prev" ${currentIdx <= 0 ? "disabled" : ""} title="${currentIdx <= 0 ? "没有上一个 Scene" : "上一个 Scene"}">←</button>
        <span class="map-scene-label" data-action="map-scene-pick">${sceneLabel}</span>
        <button class="btn btn-sm" data-action="map-scene-next" ${currentIdx >= scenes.length - 1 ? "disabled" : ""} title="${currentIdx >= scenes.length - 1 ? "没有下一个 Scene" : "下一个 Scene"}">→</button>
        <button class="btn btn-sm" data-action="map-scene-clear" ${!mapState.currentSceneId ? "disabled" : ""} title="${!mapState.currentSceneId ? "当前未选择 Scene" : "清除 Scene 聚焦"}">清除</button>
      </div>
    `
  },

  _renderMapShell() {
    const breadcrumbs = (this._state.breadcrumbs || [])
      .map((b, i) => {
        const isLast = i === this._state.breadcrumbs.length - 1
        return `<span class="map-crumb ${isLast ? "active" : ""}" data-action="map-breadcrumb" data-id="${esc(b.id)}">${esc(b.name)}</span>`
      })
      .join('<span class="map-crumb-sep">→</span>')

    const editBtn = mapState.mode === "edit"
      ? `<button class="btn btn-sm" data-action="map-exit-edit">退出编辑</button>`
      : `<button class="btn btn-sm" data-action="map-enter-edit">编辑</button>`

    const editPanelHtml = mapState.mode === "edit"
      ? renderEditPanel({ locations: this._locations, allEntities: this._allEntities, scenes: mapState.sceneList }) + this._renderTerritoryTools()
      : ""

    return `
      <div class="map-toolbar">
        <div class="map-breadcrumb">${breadcrumbs}</div>
        <div class="map-toolbar-right">
          <button class="btn btn-sm" data-action="map-back-list">地图列表</button>
          <button class="btn btn-sm" data-action="map-settings">地图设置</button>
          ${editBtn}
        </div>
      </div>
      <div class="map-container">
        <div id="map-leaflet" class="map-leaflet"></div>
        ${editPanelHtml ? `<div class="map-edit-panel">${editPanelHtml}</div>` : ""}
        <div id="map-detail-panel" class="map-detail-panel"></div>
      </div>
      ${this._renderSceneBar()}
      ${this._renderFactionList()}
      <div class="map-filter-bar">
        <span class="badge badge-canonical map-filter active" data-action="map-filter" data-filter="all">全部</span>
        <span class="badge map-filter" data-action="map-filter" data-filter="location">地点</span>
      </div>
    `
  },

  _renderDetailPanel(q, r) {
    const binding = this._bindingAt(q, r)
    if (binding?.is_center) {
      const loc = this._locationById.get(binding.location_entity_id)
      const name = loc ? loc.name : "未命名地点"
      const summary = loc && loc.summary ? loc.summary : "暂无摘要"
      const bindingCount = this._bindingCountByEntityId.get(binding.location_entity_id) || 0
      const hasDetail = this._hasDetailMap(binding.location_entity_id)
      const actionText = hasDetail ? "进入详图" : "创建详图"
      return `
        <div class="map-detail-header">${esc(name)}</div>
        <div class="map-detail-section">
          <div class="map-detail-label">摘要</div>
          <div class="map-detail-value">${esc(summary)}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">绑定格数</div>
          <div class="map-detail-value">${bindingCount}</div>
        </div>
        <div class="map-detail-actions">
          <button class="btn btn-sm btn-primary" data-action="map-detail-drill" data-id="${esc(binding.location_entity_id)}">${esc(actionText)}</button>
        </div>
      `
    }
    const tile = this._tileAt(q, r)
    if (tile) {
      return `
        <div class="map-detail-header">地形：${esc(tile.terrain_type)}</div>
        <div class="map-detail-section">
          <div class="map-detail-label">坐标</div>
          <div class="map-detail-value">q:${q}, r:${r}</div>
        </div>
      `
    }
    return `<div class="map-detail-empty">点击地图查看详情</div>`
  },

  _updateDetailPanel(q, r) {
    const panel = document.getElementById("map-detail-panel")
    if (!panel) return
    panel.innerHTML = this._renderDetailPanel(q, r)
  },

  // ============================================================
  // Leaflet 初始化 + canvas overlay
  // ============================================================

  _initLeaflet() {
    const container = document.getElementById("map-leaflet")
    if (!container || !this._state || typeof window.L === "undefined") return

    const cfg = this._state.map
    // 用一个 CRS.Simple 投影，把 hex 像素坐标当世界坐标
    this._leaflet = window.L.map(container, {
      crs: window.L.CRS.Simple,
      minZoom: -3,
      maxZoom: 3,
      zoomControl: true,
      attributionControl: false,
    })

    const size = cfg.hex_size || 30
    // 计算地图像素边界
    const w = cfg.grid_width
    const h = cfg.grid_height
    const [, lastY] = hexToPixel(w - 1, h - 1, size)
    const bounds = window.L.latLngBounds(
      [[-size, -size], [lastY + size, (size * 1.5 * (w - 1)) + size]]
    )
    this._leaflet.fitBounds(bounds)

    // canvas overlay：用 L.LayerGroup 持有一个 canvas
    this._canvas = document.createElement("canvas")
    this._canvas.dataset.testid = "map-canvas"
    this._canvas.style.position = "absolute"
    this._canvas.style.top = "0"
    this._canvas.style.left = "0"
    this._canvas.style.right = "0"
    this._canvas.style.bottom = "0"
    this._canvas.style.width = "100%"
    this._canvas.style.height = "100%"
    this._canvas.style.display = "block"
    this._canvas.style.pointerEvents = "auto"
    this._canvas.style.zIndex = "400"
    container.appendChild(this._canvas)
    this._syncCanvasSize()
    this._ctx = this._canvas.getContext("2d")

    // 初始偏移：把地图坐标原点放到容器左上偏移一点
    this._offset = { x: size * 2, y: size * 2 }
    this._redraw({ forceLabels: true })

    // 平移/缩放时同步 canvas 变换
    this._leaflet.on("resize zoom move", () => this._scheduleRedraw())
    this._leaflet.on("zoomend moveend", () => {
      this._labelsDirty = true
      this._scheduleRedraw()
    })

    // 点击：hex 命中
    this._canvas.addEventListener("click", (e) => this._handleCanvasClick(e))
    // 鼠标移动 / 离开：hover 高亮 + tooltip
    this._canvas.addEventListener("mousemove", (e) => this._handleCanvasMouseMove(e))
    this._canvas.addEventListener("mouseout", () => this._handleCanvasMouseOut())
    // 拖拽绘制
    this._canvas.addEventListener("mousedown", (e) => this._handleCanvasMouseDown(e))
    this._canvas.addEventListener("mouseup", () => this._handleCanvasMouseUp())
    this._canvas.addEventListener("mouseleave", () => this._handleCanvasMouseUp())
  },

  _scheduleRedraw() {
    if (this._redrawFrame) return
    this._redrawFrame = requestAnimationFrame(() => {
      this._redrawFrame = null
      this._redraw()
    })
  },

  /** Leaflet 视口变换 → 计算 canvas 偏移/缩放，重绘 */
  _redraw(options = {}) {
    if (!this._ctx || !this._canvas || !this._state) return
    this._syncCanvasSize()
    const cfg = this._state.map
    const size = cfg.hex_size || 30
    const origin = this._leaflet.latLngToContainerPoint([0, 0])
    const zoom = this._leaflet.getZoom()
    const scale = Math.pow(2, zoom)

    this._ctx.setTransform(1, 0, 0, 1, 0, 0)
    this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height)
    this._ctx.save()
    this._ctx.translate(origin.x, origin.y)
    this._ctx.scale(scale, scale)

    const showBoundary = this._currentFilter === "location"
    const getHexOpacity = this._getHexOpacity.bind(this)
    if (this._isLayerEnabled("terrain")) {
      drawTerrain(this._ctx, this._state.tiles, size, 0, 0, getHexOpacity)
      drawTerrainLayers(this._ctx, {
        layers: this._state.terrain_layers || [],
        regions: this._state.terrain_regions || [],
        patches: this._state.terrain_patches || [],
      }, {
        hexSize: size,
        editMode: mapState.mode === "edit",
      })
    }
    if (this._isLayerEnabled("locations")) {
      drawBindings(this._ctx, this._state.location_bindings, size, 0, 0, showBoundary, getHexOpacity)
    }
    drawMarkers(this._ctx, this._filteredMarkers(), size, 0, 0)
    if (this._isLayerEnabled("territories")) {
      drawTerritories(this._ctx, this._state.territories, size, 0, 0, mapState.factionColors, getHexOpacity)
    }
    if (this._isLayerEnabled("candidate")) {
      drawCandidateBindings(this._ctx, this._state.candidate_location_bindings || [], size, 0, 0, getHexOpacity)
      drawCandidateMarkers(this._ctx, this._candidateMarkers(), size, 0, 0)
      drawCandidateTerritories(this._ctx, this._state.candidate_territories || [], size, 0, 0, mapState.factionColors, getHexOpacity)
    }

    // 待应用变更叠加在基础地形之上
    if (this._isLayerEnabled("terrain")) {
      drawPendingTerrain(this._ctx, mapState.pendingTerrainChanges, size, 0, 0, getHexOpacity)
    }
    if (this._isLayerEnabled("locations")) {
      drawPendingBindings(this._ctx, mapState.pendingBindings, size, 0, 0, getHexOpacity)
    }

    drawContextHighlights(this._ctx, this._contextHighlightHexes(), size, 0, 0, getHexOpacity)

    // 悬停高亮
    if (mapState.hoveredHex) {
      drawHoverHighlight(
        this._ctx,
        mapState.hoveredHex.hex_q,
        mapState.hoveredHex.hex_r,
        size,
        0,
        0,
        getHexOpacity(mapState.hoveredHex.hex_q, mapState.hoveredHex.hex_r)
      )
    }

    // 浏览模式中心标签是 DOM 层，只在数据变化或移动/缩放结束后更新。
    if (options.forceLabels || this._labelsDirty) {
      this._renderCenterLabels()
      this._labelsDirty = false
    }

    this._ctx.restore()
  },

  _syncCanvasSize() {
    if (!this._canvas) return
    const container = this._leaflet?.getContainer?.() || this._canvas.parentElement
    const width = Math.max(1, Math.round(container?.clientWidth || this._canvas.width || 1))
    const height = Math.max(1, Math.round(container?.clientHeight || this._canvas.height || 1))
    if (this._canvas.width !== width) this._canvas.width = width
    if (this._canvas.height !== height) this._canvas.height = height
  },

  /** 中心点标签用 DOM（便于显示文字），通过 data-action 委托点击 */
  _renderCenterLabels() {
    if (!this._leaflet || !this._state) return
    // 清理旧标签
    this._leaflet.eachLayer((layer) => {
      if (layer._isMapLabel) this._leaflet.removeLayer(layer)
    })
    if (mapState.mode === "edit" || !this._isLayerEnabled("locations")) return // 编辑模式不显示标签

    const cfg = this._state.map
    const size = cfg.hex_size || 30
    const centers = (this._state.location_bindings || []).filter((binding) => binding.is_center)
    const layoutItems = centers.map((binding, index) => {
      const [x, y] = hexToPixel(binding.hex_q, binding.hex_r, size)
      const latlng = window.L.latLng(y, x)
      const point = this._leaflet.latLngToContainerPoint(latlng)
      const label = binding.label_override || this._locationName(binding.location_entity_id)
      return {
        item_id: binding.location_entity_id || `location-${index}`,
        item_kind: "fact",
        fact_status: "confirmed",
        title: label,
        object_type: "location",
        dynamic_type: "location",
        priority: this._hasDetailMap(binding.location_entity_id) ? 82 : 56,
        target_entity_id: binding.location_entity_id,
        anchor: { x: point.x, y: point.y },
      }
    })
    const container = this._leaflet.getContainer?.()
    const layout = buildMapLayout({
      dashboard: { dynamic_queue: layoutItems },
      viewport: {
        width: container?.clientWidth || this._canvas?.width || 640,
        height: container?.clientHeight || this._canvas?.height || 420,
      },
      viewMode: this._mountContext?.viewMode || "dashboard",
      focusEntityId: this._mountContext?.focusEntityId || null,
      sceneId: mapState.currentSceneId,
      lowMotion: Boolean(this._mountContext?.lowMotion),
    })
    const labelById = new Map(layout.labels.map((label) => [label.itemId, label]))
    for (const b of centers) {
      const [x, y] = hexToPixel(b.hex_q, b.hex_r, size)
      const latlng = window.L.latLng(y, x)
      const point = this._leaflet.latLngToContainerPoint(latlng)
      const labelLayout = labelById.get(b.location_entity_id)
      if (!labelLayout) continue
      const label = labelLayout.title
      const hasDetail = this._hasDetailMap(b.location_entity_id)
      const iconWidth = labelLayout.box.width
      const iconHeight = labelLayout.box.height
      const icon = window.L.divIcon({
        className: `map-center-marker map-layout-marker is-${labelLayout.displayLevel}`,
        html: `<div class="map-center-label" data-action="map-click-center" data-id="${esc(b.location_entity_id)}">
                 <span class="map-center-name">${esc(labelLayout.label || label)}</span>
                 <span class="map-center-drill ${hasDetail ? "has-detail" : ""}">${hasDetail ? "▾" : "·"}</span>
               </div>`,
        iconSize: [iconWidth, iconHeight],
        iconAnchor: [point.x - labelLayout.box.x, point.y - labelLayout.box.y],
      })
      const marker = window.L.marker(latlng, { icon })
      marker._isMapLabel = true
      marker.addTo(this._leaflet)
    }
    for (const cluster of layout.clusters) {
      const latlng = this._leaflet.containerPointToLatLng([
        cluster.box.x + cluster.box.width / 2,
        cluster.box.y + cluster.box.height / 2,
      ])
      const icon = window.L.divIcon({
        className: "map-center-marker map-layout-marker is-cluster",
        html: `<div class="map-center-label map-center-cluster"><span class="map-center-name">${esc(cluster.label)}</span></div>`,
        iconSize: [cluster.box.width, cluster.box.height],
        iconAnchor: [cluster.box.width / 2, cluster.box.height / 2],
      })
      const marker = window.L.marker(latlng, { icon })
      marker._isMapLabel = true
      marker.addTo(this._leaflet)
    }
  },

  _locationName(entityId) {
    this._ensureIndexes()
    const loc = this._locationById.get(entityId)
    return loc ? loc.name : "未命名地点"
  },

  _hasDetailMap(entityId) {
    this._ensureIndexes()
    return this._detailMapByEntityId.has(entityId)
  },

  // ============================================================
  // 交互
  // ============================================================

  _handleCanvasClick(e) {
    if (!this._canvas || !this._state) return
    const [q, r] = this._eventToHex(e)
    if (q == null) return
    const cfg = this._state.map
    if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) return
    if (mapState.mode === "edit") {
      if (mapState.activeTool === "bucket") {
        this._handleBucketClick(q, r)
      } else if (mapState.activeTool === "marker") {
        this._handleMarkerClick(q, r)
      } else if (!this._dragMoved) {
        this._handleDragDraw(q, r)
      }
      this._redraw()
    } else {
      this._handleBrowseClick(q, r)
    }
  },

  _handleBrowseClick(q, r) {
    setSelectedHex(q, r)
    this._updateDetailPanel(q, r)
    const eventMarker = this._markerAt(q, r, (marker) => marker.marker_type === "event")
    if (eventMarker && eventMarker.start_scene_id) {
      setCurrentScene(eventMarker.start_scene_id)
      this._reloadWithScene()
      return
    }
    const tile = this._tileAt(q, r)
    const binding = this._bindingAt(q, r)
    if (binding) {
      const name = this._locationName(binding.location_entity_id)
      toast(`地点：${name}${binding.is_center ? "（中心）" : ""}`, "info")
    } else if (tile) {
      toast(`地形：${tile.terrain_type}`, "info")
    }
  },

  _handleBucketClick(q, r) {
    const terrain = mapState.selectedTerrain
    const getTerrain = (qq, rr) => {
      const t = this._tileAt(qq, rr)
      return t ? t.terrain_type : null
    }
    const target = getTerrain(q, r)
    if (!target) return
    const changes = floodFillTerrain(q, r, target, terrain, getTerrain)
    for (const c of changes) stageTerrainChange(c.hex_q, c.hex_r, c.terrain_type)
    updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
  },

  _sceneNav(direction) {
    const scenes = mapState.sceneList
    if (!scenes.length) return
    const currentIdx = scenes.findIndex((s) => s.id === mapState.currentSceneId)
    const newIdx = Math.max(0, Math.min(scenes.length - 1, currentIdx + direction))
    const scene = scenes[newIdx]
    if (scene) {
      setCurrentScene(scene.id)
      this._reloadWithScene()
    }
  },

  _showScenePicker() {
    const scenes = mapState.sceneList
    if (!scenes.length) return
    const options = scenes.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("")
    const formHtml = `<div class="form-group"><label>选择 Scene</label><select class="form-select" id="map-scene-pick-select">${options}</select></div>`
    showModal("Scene 时间轴", formHtml, [{
      text: "跳转", class: "btn-primary", handler: async () => {
        const sel = document.getElementById("map-scene-pick-select")
        if (sel && sel.value) {
          setCurrentScene(sel.value)
          closeModal()
          await this._reloadWithScene()
        }
      },
    }])
  },

  _clearScene() {
    setCurrentScene(null)
    this._reloadWithScene()
  },

  async _reloadWithScene() {
    if (!this._state) return
    try {
      await this._loadMapDynamicState(mapState.currentSceneId)
      this._updateSceneBar()
      this._redraw({ forceLabels: true })
    } catch (err) {
      toast(`加载场景数据失败：${err.message}`, "error")
    }
  },

  _updateSceneBar() {
    const bar = document.querySelector(".map-scene-bar")
    if (bar) bar.outerHTML = this._renderSceneBar()
    this._defer(() => this._bindSceneEvents())
  },

  _bindSceneEvents() {
  },

  async _handleMarkerClick(q, r) {
    const entityId = mapState.selectedMarkerEntityId
    const markerType = mapState.selectedMarkerType || "character"
    const label = mapState.selectedMarkerLabel || null
    if (!entityId) {
      toast("请先选择一个实体", "warning")
      return
    }
    const payload = {
      entity_id: entityId,
      marker_type: markerType,
      hex_q: q,
      hex_r: r,
      label: label,
      visible: true,
    }
    const sceneStartSelect = document.getElementById("map-marker-scene-start")
    const sceneEndSelect = document.getElementById("map-marker-scene-end")
    if (sceneStartSelect && sceneStartSelect.value) {
      payload.start_scene_id = sceneStartSelect.value
      const sceneObj = mapState.sceneList.find((s) => s.id === sceneStartSelect.value)
      if (sceneObj) payload.start_scene_index = sceneObj.index
    }
    if (sceneEndSelect && sceneEndSelect.value) {
      payload.end_scene_id = sceneEndSelect.value
      const sceneObj = mapState.sceneList.find((s) => s.id === sceneEndSelect.value)
      if (sceneObj) payload.end_scene_index = sceneObj.index
    }
    try {
      await api.world.createMapMarker(
        this._state.map.id,
        payload,
        state.currentProjectId
      )
      toast("标记已添加", "success")
      await this._reloadMapStatePreservingSession(this._state.map.id)
      this._redraw()
    } catch (err) {
      toast(`标记创建失败：${err.message}`, "error")
    }
  },

  _handleCanvasMouseMove(e) {
    if (!this._canvas || !this._state || !this._leaflet) return
    const [q, r] = this._eventToHex(e)
    if (q == null) {
      clearHoveredHex()
      this._redraw()
      return
    }
    const cfg = this._state.map
    if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) {
      clearHoveredHex()
      this._redraw()
      return
    }
    setHoveredHex(q, r)
    if (mapState.mode === "edit") {
      if (mapState.dragDrawing) this._handleDragDraw(q, r)
      this._redraw()
      return
    }
    // 浏览模式：debounce 300ms 后显示 tooltip
    if (this._tooltipDebounceTimer) clearTimeout(this._tooltipDebounceTimer)
    this._tooltipDebounceTimer = setTimeout(() => {
      this._showTooltip(q, r)
    }, 300)
    this._redraw()
  },

  _handleCanvasMouseOut() {
    clearHoveredHex()
    if (this._tooltipDebounceTimer) {
      clearTimeout(this._tooltipDebounceTimer)
      this._tooltipDebounceTimer = null
    }
    if (this._tooltipPopup) {
      if (this._leaflet) this._leaflet.closePopup(this._tooltipPopup)
      this._tooltipPopup = null
    }
    this._redraw()
  },

  _handleCanvasMouseDown(e) {
    if (!this._canvas || !this._state || mapState.mode !== "edit") return
    const [q, r] = this._eventToHex(e)
    if (q == null) return
    if (mapState.activeTool === "bucket") return // bucket is click-only
    this._dragMoved = false
    startDragDraw()
    this._handleDragDraw(q, r)
    this._redraw()
  },

  _handleCanvasMouseUp() {
    if (!mapState.dragDrawing) return
    endDragDraw()
    // click 事件会在 mouseup 后触发，保留 _dragMoved 到 click 判断完成
    setTimeout(() => { this._dragMoved = false }, 0)
  },

  _handleDragDraw(q, r) {
    if (!this._state) return
    const cfg = this._state.map
    if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) return
    if (!recordDragHex(q, r)) return
    this._dragMoved = true
    if (mapState.activeTool === "brush") {
      stageTerrainChange(q, r, mapState.selectedTerrain)
      updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
    } else if (mapState.activeTool === "bind") {
      const entityId = mapState.selectedLocationEntityId
      if (!entityId) return
      const isCenter = !!mapState.bindCenterMode
      stageBindingChange(entityId, q, r, isCenter)
      updateBindingPendingCount(Object.keys(mapState.pendingBindings).length)
    } else if (mapState.activeTool === "territory") {
      this._handleTerritoryPaint(q, r)
    }
  },

  _eventToHex(e) {
    if (!this._canvas || !this._leaflet) return [null, null]
    const rect = this._canvas.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top
    const origin = this._leaflet.latLngToContainerPoint([0, 0])
    const zoom = this._leaflet.getZoom()
    const scale = Math.pow(2, zoom)
    const worldX = (px - origin.x) / scale
    const worldY = (py - origin.y) / scale
    const cfg = this._state.map
    const size = cfg.hex_size || 30
    return pixelToHex(worldX, worldY, size)
  },

  _showTooltip(q, r) {
    if (!this._leaflet) return
    const content = this._buildTooltipContent(q, r)
    if (!content) {
      if (this._tooltipPopup) {
        this._leaflet.closePopup(this._tooltipPopup)
        this._tooltipPopup = null
      }
      return
    }
    const cfg = this._state.map
    const [x, y] = hexToPixel(q, r, cfg.hex_size || 30)
    const latlng = window.L.latLng(y, x)
    if (this._tooltipPopup) {
      this._tooltipPopup.setLatLng(latlng).setContent(content)
    } else {
      this._tooltipPopup = window.L.popup({ closeButton: false, autoClose: false, className: "map-hex-tooltip" })
        .setLatLng(latlng)
        .setContent(content)
        .openOn(this._leaflet)
    }
  },

  _buildTooltipContent(q, r) {
    const binding = this._bindingAt(q, r)
    const tile = this._tileAt(q, r)
    if (binding) {
      const name = this._locationName(binding.location_entity_id)
      const centerTag = binding.is_center ? "（中心）" : ""
      return `<div class="map-tooltip-title">${esc(name)}${centerTag}</div><div class="map-tooltip-sub">${esc(tile ? tile.terrain_type : "")}</div>`
    }
    const hitMarker = this._markerAt(q, r)
    if (hitMarker) {
      const typeLabels = { character: "人物", event: "事件", item: "物品" }
      const typeLabel = typeLabels[hitMarker.marker_type] || hitMarker.marker_type
      let html = `<div class="map-tooltip-title">${esc(hitMarker.label || typeLabel)}</div>`
      html += `<div class="map-tooltip-sub">${esc(typeLabel)}</div>`
      if (hitMarker.marker_type === "character") {
        const relevantEvents = this._relevantEventMarkers()
        if (relevantEvents.length > 0) {
          html += `<div class="map-tooltip-sub" style="margin-top:4px;">相关事件：${relevantEvents.map((m) => esc(m.label || "事件")).join("、")}</div>`
        }
      }
      if (hitMarker.marker_type === "event" && hitMarker.start_scene_id) {
        html += `<div class="map-tooltip-sub">点击跳转到 Scene</div>`
      }
      return html
    }
    if (tile) {
      return `<div class="map-tooltip-title">${esc(tile.terrain_type)}</div><div class="map-tooltip-sub">q:${q}, r:${r}</div>`
    }
    return ""
  },

  _markerAt(q, r, predicate = null) {
    this._ensureIndexes()
    const markersAtHex = this._markersByHex.get(this._hexKey(q, r)) || []
    for (const marker of markersAtHex) {
      if (!this._isMarkerLayerEnabled(marker)) continue
      if (predicate && !predicate(marker)) continue
      return marker
    }
    return null
  },

  _relevantEventMarkers() {
    this._ensureIndexes()
    const sceneId = mapState.currentSceneId
    if (sceneId) {
      return this._eventMarkersBySceneId.get(sceneId) || []
    }
    return this._eventMarkersHead || []
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindListEvents() {
    bindWorkspaceClick(this, {
      "bulk-toggle-one": (e, t) => {
        e.stopPropagation()
        toggleBulkSelection(this, t.getAttribute("data-scope"), t.getAttribute("data-id"), t.checked)
        syncBulkSelectionUi(this, t.getAttribute("data-scope"))
      },
      "bulk-toggle-all": (e, t) => {
        e.stopPropagation()
        toggleAllBulkSelection(this, t.getAttribute("data-scope"), this._maps.map((m) => m.id).filter(Boolean), t.checked)
        syncBulkSelectionUi(this, t.getAttribute("data-scope"))
      },
      "bulk-clear": (_e, t) => {
        const scope = t.getAttribute("data-scope")
        clearBulkSelection(this, scope)
        syncBulkSelectionUi(this, scope)
      },
      "bulk-run": (_e, t) => this._runMapBulkAction(t.getAttribute("data-bulk-action")),
      "map-create-world": () => this._showCreateWorldForm(),
      "map-open": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._openMap(id)
      },
      "map-delete": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._deleteMap(id)
      },
    })
  },

  _bindMapEvents() {
    bindWorkspaceClick(this, {
      "map-back-list": () => this._backToList(),
      "map-settings": () => this._showSettingsModal(),
      "map-enter-edit": () => this._enterEdit(),
      "map-exit-edit": () => this._exitEdit(),
      "map-breadcrumb": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._openMap(id)
      },
      "map-click-center": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._onCenterClick(id)
      },
      "map-detail-drill": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._onCenterClick(id)
      },
      "map-filter": (_e, t) => {
        this._currentFilter = t.getAttribute("data-filter") || "all"
        document.querySelectorAll(".map-filter").forEach((el) => el.classList.remove("active"))
        t.classList.add("active")
        this._redraw()
      },
      "map-tool-brush": () => this._switchTool("brush"),
      "map-tool-bucket": () => this._switchTool("bucket"),
      "map-tool-bind": () => this._switchTool("bind"),
      "map-tool-marker": () => this._switchTool("marker"),
      "map-undo": () => this._undo(),
      "map-apply": () => this._applyAllChanges(),
      "map-save": () => this._saveAndExit(),
      "map-scene-prev": () => this._sceneNav(-1),
      "map-scene-next": () => this._sceneNav(1),
      "map-scene-pick": () => this._showScenePicker(),
      "map-scene-clear": () => this._clearScene(),
      "map-focus-toggle": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._toggleFocusMode(id)
      },
      "map-focus-clear": () => {
        clearFocus()
        this._refreshFactionList()
        this._redraw()
      },
      "map-territory-paint": () => this._switchTool("territory"),
      "map-territory-clear": () => this._clearFactionTerritory(),
    })

    // 地形选择
    const terrainSelect = document.getElementById("map-terrain-select")
    terrainSelect?.addEventListener("change", () => {
      mapState.selectedTerrain = terrainSelect.value
    })
    // 地点选择
    const bindSelect = document.getElementById("map-bind-select")
    bindSelect?.addEventListener("change", () => {
      mapState.selectedLocationEntityId = bindSelect.value || null
    })
    // 中心点绑定模式
    const bindCenterCheck = document.getElementById("map-bind-center")
    bindCenterCheck?.addEventListener("change", () => {
      mapState.bindCenterMode = bindCenterCheck.checked
    })

    const markerTypeSelect = document.getElementById("map-marker-type")
    markerTypeSelect?.addEventListener("change", () => {
      mapState.selectedMarkerType = markerTypeSelect.value
    })
    const markerEntitySelect = document.getElementById("map-marker-entity")
    markerEntitySelect?.addEventListener("change", () => {
      mapState.selectedMarkerEntityId = markerEntitySelect.value || null
    })
    const markerLabelInput = document.getElementById("map-marker-label")
    markerLabelInput?.addEventListener("input", () => {
      mapState.selectedMarkerLabel = markerLabelInput.value
    })

    // 势力范围选择
    const territoryFactionSelect = document.getElementById("map-territory-faction")
    territoryFactionSelect?.addEventListener("change", () => {
      mapState.selectedFactionId = territoryFactionSelect.value || null
    })
    const territoryColorInput = document.getElementById("map-territory-color")
    territoryColorInput?.addEventListener("change", () => {
      if (mapState.selectedFactionId) {
        setFactionColor(mapState.selectedFactionId, territoryColorInput.value)
      }
    })

    // Ctrl+Z 撤销
    this._keyHandler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && mapState.mode === "edit") {
        e.preventDefault()
        this._undo()
      }
    }
    document.addEventListener("keydown", this._keyHandler)
  },

  // ============================================================
  // 动作
  // ============================================================

  async _openMap(mapId) {
    const rootId = this._mountRootId || "map-root"
    const context = this._mountContext || {}
    this.unmount()
    this._mountRootId = rootId
    this._mountContext = context
    await this._loadMapState(mapId)
    await this._loadLocations()
    await this._loadScenes()
    this._render(rootId)
  },

  _backToList() {
    this.unmount()
    this._render("map-root")
  },

  _deleteMap(mapId) {
    const map = this._maps.find((m) => m.id === mapId)
    const name = map ? map.name : "该地图"
    confirmAction(
      `确定删除地图「${esc(name)}」？该操作不可恢复，子地图将变为顶层地图。`,
      async () => {
        try {
          await api.world.deleteMap(mapId, state.currentProjectId)
          toast("地图已删除", "success")
          await this._loadMaps()
          this._render("map-root")
        } catch (err) {
          toast(`删除失败：${err.message}`, "error")
        }
      },
      "删除"
    )
  },

  _runMapBulkAction(action) {
    if (action !== "delete-maps") return
    const items = selectedItemsFrom(this._maps, getBulkSelection(this, "map-list"))
    if (!items.length) {
      toast("请先选择地图", "warning")
      return
    }
    return confirmAction(`确定删除选中的 ${items.length} 张地图？该操作不可恢复。`, async () => {
      const result = await runBulkAction(items, async (map) => {
        await api.world.deleteMap(map.id, state.currentProjectId)
      })
      toast(bulkResultMessage(result, "批量删除地图", (item) => item.name || item.id), result.failed.length ? "warning" : "success")
      clearBulkSelection(this, "map-list")
      await this._loadMaps()
      this._render("map-root")
    }, "删除")
  },

  async _enterEdit() {
    await this._loadLocations()
    await this._loadAllEntities()
    this._teardownInteractiveSurface()
    mapState.mode = "edit"
    this._render(this._mountRootId || "map-root")
  },

  _exitEdit() {
    mapState.pendingTerrainChanges = {}
    mapState.pendingBindings = {}
    updatePendingCount(0)
    updateBindingPendingCount(0)
    this._teardownInteractiveSurface()
    mapState.mode = "browse"
    this._render(this._mountRootId || "map-root")
  },

  _switchTool(tool) {
    mapState.activeTool = tool
    toggleToolSections(tool)
  },

  _undo() {
    // P0：Ctrl+Z 只撤销未应用的 pending 变更（地形 + 绑定）
    const bindingCount = Object.keys(mapState.pendingBindings).length
    if (bindingCount > 0) {
      mapState.pendingBindings = {}
      updateBindingPendingCount(0)
      toast(`已撤销 ${bindingCount} 个待绑定变更`, "info")
      this._redraw()
      return
    }
    const terrainCount = Object.keys(mapState.pendingTerrainChanges).length
    if (terrainCount > 0) {
      mapState.pendingTerrainChanges = {}
      updatePendingCount(0)
      toast(`已撤销 ${terrainCount} 个地形变更`, "info")
      this._redraw()
      return
    }
    toast("无可撤销的操作（已应用的变更不可撤销）", "info")
  },

  async _applyAllChanges() {
    const terrainChanges = Object.keys(mapState.pendingTerrainChanges).length
    const bindingChanges = Object.keys(mapState.pendingBindings).length
    if (terrainChanges === 0 && bindingChanges === 0) {
      toast("没有待应用的变更", "info")
      return
    }
    try {
      if (terrainChanges > 0) await this._applyTerrainChanges()
      if (bindingChanges > 0) await this._applyBindings()
      toast(`已应用 ${terrainChanges + bindingChanges} 个变更`, "success")
      await this._reloadMapStatePreservingSession(this._state.map.id)
      this._redraw()
    } catch (err) {
      toast(`应用失败：${err.message}`, "error")
      // pending retained, no reload
    }
  },

  async _applyTerrainChanges() {
    const changes = consumePendingChanges()
    if (changes.length === 0) return
    try {
      await api.world.batchUpdateTiles(this._state.map.id, { changes }, state.currentProjectId)
      updatePendingCount(0)
    } catch (err) {
      mapState.undoStack.pop()
      for (const c of changes) stageTerrainChange(c.hex_q, c.hex_r, c.terrain_type, c.elevation)
      updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
      throw err
    }
  },

  async _applyBindings() {
    const bindings = Object.values(mapState.pendingBindings)
    if (bindings.length === 0) return
    const byEntity = {}
    for (const b of bindings) {
      if (!byEntity[b.location_entity_id]) byEntity[b.location_entity_id] = []
      byEntity[b.location_entity_id].push({ hex_q: b.hex_q, hex_r: b.hex_r, is_center: b.is_center })
    }
    try {
      for (const [entityId, hexes] of Object.entries(byEntity)) {
        await api.world.createLocationBindings(
          this._state.map.id,
          { location_entity_id: entityId, hexes },
          state.currentProjectId
        )
      }
      mapState.pendingBindings = {}
      updateBindingPendingCount(0)
    } catch (err) {
      toast(`绑定保存失败：${err.message}`, "error")
      throw err
    }
  },

  async _saveAndExit() {
    // 先应用未保存变更，再退出编辑
    await this._applyAllChanges()
    this._teardownInteractiveSurface()
    mapState.mode = "browse"
    this._render(this._mountRootId || "map-root")
    toast("已保存", "success")
  },

  _onCenterClick(entityId) {
    // 点击中心点：有详图则下钻，无则提示创建
    if (this._hasDetailMap(entityId)) {
      const detail = this._detailMapByEntityId.get(entityId)
      if (detail) this._openMap(detail.id)
    } else {
      confirmAction(
        `为该地点创建详图？`,
        () => setTimeout(() => this._showCreateDetailForm(entityId), 0),
        "创建详图"
      )
    }
  },

  _showCreateWorldForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="map-create-name" placeholder="如：九州世界" />
      </div>
      <div class="form-group">
        <label>尺寸</label>
        <select class="form-select" id="map-create-size">
          <option value="30,20">30×20（世界地图，600 格）</option>
        </select>
      </div>
      <div class="form-group">
        <label>模板</label>
        <select class="form-select" id="map-create-template">
          <option value="blank">空白</option>
          <option value="continent">大陆型</option>
          <option value="islands">群岛型</option>
        </select>
      </div>
    `
    showModal("创建世界地图", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const name = document.getElementById("map-create-name")?.value.trim()
        if (!name) { toast("请输入地图名称", "warning"); return }
        const [w, h] = (document.getElementById("map-create-size")?.value || "30,20").split(",").map(Number)
        const template = document.getElementById("map-create-template")?.value || "blank"
        try {
          const created = await api.world.createMap({
            name, map_type: "world", grid_width: w, grid_height: h, template,
          }, state.currentProjectId)
          closeModal()
          toast("世界地图已创建", "success")
          await this._openMap(created.id)
        } catch (err) {
          toast(`创建失败：${err.message}`, "error")
        }
      },
    }])
  },

  _showCreateDetailForm(entityId) {
    const loc = this._locationById.get(entityId)
    const locName = loc ? loc.name : "详图"
    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="map-detail-name" value="${esc(locName)}" />
      </div>
      <div class="form-group">
        <label>重要性 / 尺寸</label>
        <select class="form-select" id="map-detail-importance">
          <option value="core">核心（60×45）</option>
          <option value="important" selected>重要（40×30）</option>
          <option value="normal">普通（20×30）</option>
        </select>
      </div>
      <div class="form-group">
        <label>快速生成</label>
        <select class="form-select" id="map-detail-autogen">
          <option value="1">是（中心 city + 外 road）</option>
          <option value="0">否（空白）</option>
        </select>
      </div>
    `
    showModal("创建地点详图", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const name = document.getElementById("map-detail-name")?.value.trim() || locName
        const importance = document.getElementById("map-detail-importance")?.value || "important"
        const autogen = document.getElementById("map-detail-autogen")?.value === "1"
        const sizes = { core: [60, 45], important: [40, 30], normal: [20, 30] }
        const [w, h] = sizes[importance] || sizes.important
        try {
          const created = await api.world.createMap({
            name, map_type: "city", grid_width: w, grid_height: h,
            parent_map_id: this._state.map.id, parent_entity_id: entityId,
          }, state.currentProjectId)
          if (autogen) {
            await this._generateMapWhenAvailable(created.id)
          }
          closeModal()
          toast("详图已创建", "success")
          await this._openMap(created.id)
        } catch (err) {
          toast(`创建失败：${err.message}`, "error")
        }
      },
    }])
  },

  async _generateMapWhenAvailable(mapId) {
    let lastError = null
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        return await api.world.generateMap(mapId, state.currentProjectId)
      } catch (err) {
        lastError = err
        const message = (err?.message || "").toLowerCase()
        if (!message.includes("404") &&
            !message.includes("not found") &&
            !message.includes("不存在")) {
          throw err
        }
        await new Promise((resolve) => setTimeout(resolve, 50 * (attempt + 1)))
      }
    }
    throw lastError
  },

  _showSettingsModal() {
    const cfg = this._state.map
    const previousMode = mapState.mode
    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="map-settings-name" value="${esc(cfg.name)}" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-input" id="map-settings-desc" rows="3">${esc(cfg.description || "")}</textarea>
      </div>
    `
    showModal("地图设置", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        const name = document.getElementById("map-settings-name")?.value.trim()
        if (!name) { toast("请输入地图名称", "warning"); return }
        const description = document.getElementById("map-settings-desc")?.value.trim()
        try {
          await api.world.updateMap(
            cfg.id,
            { name, description },
            state.currentProjectId
          )
          closeModal()
          toast("地图信息已更新", "success")
          await this._loadMapState(cfg.id)
          await this._loadMaps()
          this.unmount()
          mapState.mode = previousMode
          this._render("map-root")
        } catch (err) {
          toast(`更新失败：${err.message}`, "error")
        }
      },
    }])
  },

  // === P2: 势力范围与聚焦模式 ===

  _renderTerritoryTools() {
    const orgs = this._allEntities.filter((e) => e.entity_type === "organization")
    if (orgs.length === 0) {
      return `<div class="map-tool-group"><h4>势力范围</h4><p style="color:var(--text-dim);font-size:12px;">暂无组织实体（需在 world 对象中创建 organization 类型实体）</p></div>`
    }
    const orgOptions = orgs.map((o) => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join("")
    const selectedOrg = mapState.selectedFactionId
    const currentColor = this._safeHexColor(mapState.factionColors[selectedOrg], "#FF6B6B")
    return `
      <div class="map-tool-group">
        <h4>势力范围</h4>
        <select id="map-territory-faction" class="form-select">
          <option value="">选择组织...</option>
          ${orgOptions}
        </select>
        <div class="map-faction-color-row" style="display:flex;gap:8px;align-items:center;margin-top:8px;">
          <input type="color" id="map-territory-color" value="${esc(currentColor)}" style="width:40px;height:28px;padding:0;border:none;" />
          <span style="font-size:12px;color:var(--text-dim);">颜色</span>
        </div>
        <div class="map-tool-actions" style="margin-top:8px;">
          <button class="btn btn-sm btn-primary" data-action="map-territory-paint">绘制</button>
          <button class="btn btn-sm btn-danger" data-action="map-territory-clear">清除</button>
        </div>
      </div>
    `
  },

  _renderFactionList() {
    const orgs = this._allEntities.filter((e) => e.entity_type === "organization")
    if (orgs.length === 0) return ""
    const focused = mapState.focusMode && mapState.focusEntityId
    return `
      <div class="map-faction-bar">
        <span class="map-faction-label">组织：</span>
        ${orgs.map((o) => {
          const isFocused = focused === o.id
          const color = this._safeHexColor(mapState.factionColors[o.id], "#999")
          return `<span class="map-faction-tag ${isFocused ? "focused" : ""}" data-action="map-focus-toggle" data-id="${esc(o.id)}" style="background:${esc(color)}22;border-color:${esc(color)};">${esc(o.name)}</span>`
        }).join("")}
        ${focused ? `<button class="btn btn-sm" data-action="map-focus-clear">清除聚焦</button>` : ""}
      </div>
    `
  },

  _safeHexColor(color, fallback = "#999") {
    return /^#[0-9A-Fa-f]{6}$/.test(color || "") ? color : fallback
  },

  _toggleFocusMode(entityId) {
    if (mapState.focusMode && mapState.focusEntityId === entityId) {
      clearFocus()
    } else {
      setFocusMode(true, entityId)
      this._loadFocusState(entityId)
    }
    this._refreshFactionList()
    this._redraw()
  },

  async _loadFocusState(entityId) {
    if (!this._state) return
    try {
      const resp = await api.world.getFocusState(this._state.map.id, entityId, state.currentProjectId)
      const relatedHexes = resp.related_hexes || (resp.territories || [])
      setFocusRelatedHexes(relatedHexes)
      this._redraw()
    } catch (err) {
      toast(`加载聚焦状态失败：${err.message}`, "error")
    }
  },

  _refreshFactionList() {
    const bar = document.querySelector(".map-faction-bar")
    if (bar) bar.outerHTML = this._renderFactionList()
  },

  _getHexOpacity(q, r) {
    if (!mapState.focusMode) return 1.0
    const key = `${q},${r}`
    return mapState.focusRelatedHexes.has(key) ? 1.0 : 0.3
  },

  _isLayerEnabled(layer) {
    const layers = this._mountContext?.layers || {}
    if (layer === "candidate") return layers.candidate === true
    return layers[layer] !== false
  },

  _isMarkerLayerEnabled(marker) {
    if (marker.marker_type === "event") return this._isLayerEnabled("events")
    if (marker.marker_type === "item") return this._isLayerEnabled("items")
    return this._isLayerEnabled("markers")
  },

  _filteredMarkers() {
    return (this._state?.markers || []).filter((marker) => this._isMarkerLayerEnabled(marker))
  },

  _candidateMarkers() {
    if (!this._isLayerEnabled("candidate")) return []
    return (this._state?.candidate_markers || []).filter((marker) => marker.visible !== false)
  },

  _focusEntityHasTerritory(entityId) {
    return (this._state?.territories || []).some((t) => t.faction_entity_id === entityId)
  },

  _contextHighlightHexes() {
    if (!this._state) return []
    const context = this._mountContext || {}
    const sceneId = context.sceneId || mapState.currentSceneId
    if (sceneId) {
      const sceneMarkers = (this._state.markers || []).filter((marker) => (
        marker.visible !== false
      ))
      const markerHighlights = sceneMarkers.map((marker) => ({
        hex_q: marker.hex_q,
        hex_r: marker.hex_r,
        kind: "scene",
      }))
      const locationHighlights = []
      for (const marker of sceneMarkers) {
        const binding = this._bindingAt(marker.hex_q, marker.hex_r)
        if (binding?.is_center) {
          locationHighlights.push({
            hex_q: binding.hex_q,
            hex_r: binding.hex_r,
            kind: "primary_location",
          })
        }
      }
      return this._dedupeHighlights([...locationHighlights, ...markerHighlights])
    }

    const focusEntityId = context.focusEntityId
    if (!focusEntityId) return []
    const bindingHighlights = (this._state.location_bindings || [])
      .filter((b) => b.location_entity_id === focusEntityId)
      .map((b) => ({ hex_q: b.hex_q, hex_r: b.hex_r, kind: "focus" }))
    if (bindingHighlights.length > 0) return this._dedupeHighlights(bindingHighlights)

    const markerHighlights = (this._state.markers || [])
      .filter((m) => m.entity_id === focusEntityId && m.visible !== false)
      .map((m) => ({ hex_q: m.hex_q, hex_r: m.hex_r, kind: "focus" }))
    if (markerHighlights.length > 0) return this._dedupeHighlights(markerHighlights)

    const territoryHighlights = (this._state.territories || [])
      .filter((t) => t.faction_entity_id === focusEntityId)
      .map((t) => ({ hex_q: t.hex_q, hex_r: t.hex_r, kind: "territory" }))
    return this._dedupeHighlights(territoryHighlights)
  },

  _dedupeHighlights(highlights) {
    const seen = new Set()
    const result = []
    for (const h of highlights || []) {
      const key = `${h.hex_q},${h.hex_r},${h.kind}`
      if (seen.has(key)) continue
      seen.add(key)
      result.push(h)
    }
    return result
  },

  _notifyMapOpened() {
    const callback = this._mountContext?.onMapOpened
    if (typeof callback === "function" && this._state?.map) {
      callback(this._state.map)
    }
  },

  _handleTerritoryPaint(q, r) {
    const factionId = mapState.selectedFactionId
    if (!factionId) {
      toast("请先选择组织", "warning")
      return
    }
    this._createTerritoryTile(factionId, q, r)
  },

  async _createTerritoryTile(factionId, q, r) {
    if (!this._state) return
    try {
      await api.world.createTerritories(
        this._state.map.id,
        {
          faction_entity_id: factionId,
          hexes: [{ hex_q: q, hex_r: r }],
        },
        state.currentProjectId
      )
      toast("势力范围已更新", "success")
      await this._reloadMapStatePreservingSession(this._state.map.id)
      this._redraw()
    } catch (err) {
      toast(`势力范围更新失败：${err.message}`, "error")
    }
  },

  async _clearFactionTerritory() {
    const factionId = mapState.selectedFactionId
    if (!factionId) {
      toast("请先选择组织", "warning")
      return
    }
    confirmAction(
      `确定清除该组织的全部势力范围？`,
      async () => {
        try {
          await api.world.deleteTerritoriesByFaction(
            this._state.map.id,
            factionId,
            state.currentProjectId
          )
          toast("势力范围已清除", "success")
          await this._reloadMapStatePreservingSession(this._state.map.id)
          this._redraw()
        } catch (err) {
          toast(`清除失败：${err.message}`, "error")
        }
      },
      "清除"
    )
  },
}

export default mapView
