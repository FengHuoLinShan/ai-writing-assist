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
import renderEditPanel, {
  renderMarkerEntityOptions,
  updatePendingCount,
  updateBindingPendingCount,
  toggleToolSections,
} from "./mapEditPanel.js"
import { buildMapLayout } from "./mapLayoutEngine.js"
import { drawTerrainLayers } from "./mapTerrainRenderer.js"
import { getTerrainAsset, TERRAIN_PRESETS } from "./mapTerrainAssets.js"
import {
  drawMapPaths,
  hitTestPath,
  MAP_PATH_PROFILES,
  normalizePathState,
  pathNodesFor,
  representativePathPoint,
  simplifyPathToLimit,
} from "./mapPathRenderer.js"
import {
  activeSelectionReason,
  layerNodeId,
  resolveLayerSelections,
  sessionLayerVisible,
  setLayerSelection,
} from "./mapLayerSession.js"
import {
  drawTimelineProjection,
  mapSceneDisplayNumber,
  timelineAnchorPoint,
  timelineProjectionSignature,
} from "./mapTimelineProjection.js"
import {
  beginMapNavigation,
  cancelMapTelemetry,
  endMapTelemetryStage,
  markMapTelemetryCondition,
  recordMapFrame,
  recordMapInput,
  setMapTelemetryMetadata,
  startMapTelemetryStage,
} from "./mapTelemetry.js"
import { loadLeafletForMapView } from "./leafletLoader.js"
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
import { bindDelegation } from "../shared/viewHelper.js"
import {
  mapState,
  mapEditingSession,
  resetMapState,
  stageTerrainChange,
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
  setEditorLayer,
} from "./mapState.js"

const MAP_FIT_FLOOR_ZOOM = -12
const MAP_DEFAULT_MIN_ZOOM = -3
const MAP_TILE_BATCH_LIMIT = 10000
const MAP_LOCATION_BINDING_HEX_LIMIT = 5000
const MAP_PATH_NODE_LIMIT = 500

const mapView = {
  /** @type {any|null} Leaflet map 实例 */
  _leaflet: null,
  /** @type {any|null} Leaflet 模块 API；不暴露到 window。 */
  _leafletApi: null,
  /** @type {HTMLCanvasElement|null} 自定义地形 canvas overlay */
  _canvas: null,
  /** @type {CanvasRenderingContext2D|null} */
  _ctx: null,
  /** 当前地图聚合状态（MapStateResponse） */
  _state: null,
  _layerTree: null,
  _pathState: normalizePathState(),
  _pathGeometryCache: new Map(),
  _markerBaselineById: new Map(),
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
  _renderSubsetCache: new Map(),
  _terrainOverviewCache: new Map(),
  _renderMetrics: null,
  _performanceMetrics: null,
  _performanceFrameDurations: [],
  _firstDrawStartedAt: null,
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
  _dragLocationId: null,
  _dragMarkerId: null,
  _pointerStartSnapshot: null,
  _pathPointerSamples: null,
  _dragPathNode: null,
  _dragOutOfBoundsNotified: false,
  _pointerStartHadPending: false,
  _suppressNextCanvasClick: false,
  _ignoreDirtyGuard: false,
  /** 当前侧边栏筛选模式 ("all" | "location") */
  _currentFilter: "all",
  /** 当前挂载容器 ID */
  _mountRootId: "map-root",
  /** 一级地图工作台传入的打开上下文 */
  _mountContext: {},
  /** 使异步编辑过渡在 unmount/重新 mount 后失效。 */
  _lifecycleEpoch: 0,
  /** apply 请求至服务端状态重载完成期间锁定整个地图编辑工作区。 */
  _applyingEditorChanges: false,
  _editorApplyToken: null,
  /** Scene 时间轴只读投影；不进入编辑草稿或 editor_revision。 */
  _timelineProjection: null,
  _timelineProjectionSignature: "",
  _labelClusterItemsById: new Map(),

  // ============================================================
  // 生命周期：由 worldView 调用
  // ============================================================

  /**
   * 挂载到容器。worldView._renderMap 提供 #map-root 后调用。
   * @param {string} rootId
   * @param {object} context
   */
  async mount(rootId, context = {}) {
    const lifecycleEpoch = ++this._lifecycleEpoch
    this._mountRootId = rootId
    this._mountContext = context || {}
    if (context.mapId) {
      beginMapNavigation({
        mapId: context.mapId,
        route: globalThis.location?.hash || null,
      })
    }
    await this._loadMaps()
    if (!this._isLifecycleCurrent(lifecycleEpoch, context)) return false
    if (context.mapId) {
      startMapTelemetryStage("api_and_parse")
      await this._loadMapState(context.mapId, context.sceneId || null)
      if (!this._isLifecycleCurrent(lifecycleEpoch, context)) return false
      startMapTelemetryStage("state_assembly")
      await Promise.all([
        this._loadLocations(),
        this._loadAllEntities(),
        this._loadScenes(),
        this._loadLayerTree(),
        this._loadPaths(),
      ])
      if (!this._isLifecycleCurrent(lifecycleEpoch, context)) return false
      endMapTelemetryStage("state_assembly")
      markMapTelemetryCondition("state_ready")
      if (context.sceneId) setCurrentScene(context.sceneId)
      if (context.focusEntityId && this._focusEntityHasTerritory(context.focusEntityId)) {
        setFocusMode(true, context.focusEntityId)
        await this._loadFocusState(context.focusEntityId)
        if (!this._isLifecycleCurrent(lifecycleEpoch, context)) return false
      }
    } else {
      await this._loadScenes()
      if (!this._isLifecycleCurrent(lifecycleEpoch, context)) return false
    }
    this._render(rootId)
    return true
  },

  /** 退出时清理 Leaflet 实例 */
  unmount() {
    this._lifecycleEpoch += 1
    this._setEditorApplyBusy(false)
    this._clearPendingTimers()
    this._teardownInteractiveSurface()
    this._state = null
    this._layerTree = null
    this._pathState = normalizePathState()
    this._pathGeometryCache.clear()
    this._renderSubsetCache.clear()
    this._terrainOverviewCache.clear()
    this._renderMetrics = null
    this._performanceMetrics = null
    this._performanceFrameDurations = []
    this._firstDrawStartedAt = null
    this._markerBaselineById = new Map()
    this._pathPointerSamples = null
    this._dragPathNode = null
    this._timelineProjection = null
    this._timelineProjectionSignature = ""
    this._labelClusterItemsById.clear()
    this._pointerStartHadPending = false
    cancelMapTelemetry()
    resetMapState()
  },

  _isLifecycleCurrent(lifecycleEpoch, mountContext = this._mountContext) {
    return lifecycleEpoch === this._lifecycleEpoch && this._mountContext === mountContext
  },

  _captureModalOwner(controlId) {
    const lifecycleEpoch = this._lifecycleEpoch
    const mountContext = this._mountContext
    const projectId = state.currentProjectId
    const control = document.getElementById(controlId)
    return () => this._isLifecycleCurrent(lifecycleEpoch, mountContext)
      && state.currentProjectId === projectId
      && control?.isConnected
      && document.getElementById(controlId) === control
  },

  _setEditorApplyBusy(active, attemptId = null) {
    if (!active && attemptId != null && this._editorApplyToken !== attemptId) {
      return false
    }
    this._applyingEditorChanges = Boolean(active)
    this._editorApplyToken = active ? attemptId : null
    const targets = [
      document.getElementById(this._mountRootId || "map-root")
        || document.getElementById("workspace-content"),
      document.getElementById("modal-overlay"),
    ].filter(Boolean)
    for (const element of targets) {
      element.inert = Boolean(active)
      if (active) element.setAttribute("aria-busy", "true")
      else element.removeAttribute("aria-busy")
    }
    return true
  },

  _defer(fn) {
    const timer = setTimeout(() => {
      this._pendingTimers.delete(timer)
      fn()
    }, 0)
    this._pendingTimers.add(timer)
    return timer
  },

  _bindViewClick(handlerMap) {
    const root = document.getElementById(this._mountRootId || "map-root")
      || document.getElementById("workspace-content")
    if (root) bindDelegation(this, root, "click", handlerMap)
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
      this._leaflet.off?.("resize zoom move")
      this._leaflet.off?.("zoomend moveend")
      this._leaflet.remove?.()
      this._leaflet = null
    }
    this._leafletApi = null
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
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    this._mapsLoadError = null
    if (!projectId) {
      this._maps = []
      this._rebuildIndexes()
      return true
    }
    try {
      const maps = []
      const limit = 500
      let skip = 0
      while (true) {
        const data = await api.world.listMaps({
          novel_id: projectId,
          status: "active",
          skip,
          limit,
        })
        const items = data.items || data || []
        maps.push(...items)
        if (items.length < limit) break
        skip += limit
      }
      if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
        return false
      }
      this._maps = maps
      this._rebuildIndexes()
      return true
    } catch (err) {
      if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
        return false
      }
      this._maps = []
      this._mapsLoadError = err?.message || "加载失败"
      this._rebuildIndexes()
      toast("地图列表加载失败，可稍后重试", "warning")
      return true
    }
  },

  async _loadMapState(
    mapId,
    sceneId = mapState.currentSceneId,
    { beforeStateReplace = null } = {},
  ) {
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    try {
      const startedAt = performance.now()
      const nextState = await api.world.getMapState(mapId, projectId, sceneId)
      if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
        return false
      }
      if (typeof beforeStateReplace === "function") beforeStateReplace()
      this._state = nextState
      const loadedAt = performance.now()
      const serialized = JSON.stringify(this._state)
      const payloadBytes = typeof TextEncoder === "function"
        ? new TextEncoder().encode(serialized).length
        : serialized.length
      this._performanceMetrics = {
        map_id: mapId,
        grid: `${this._state.map?.grid_width || 0}x${this._state.map?.grid_height || 0}`,
        payload_bytes: payloadBytes,
        request_and_parse_ms: loadedAt - startedAt,
        first_draw_ms: null,
        warmup_frames: 20,
        sampled_frames: 0,
        average_frame_ms: null,
        p95_frame_ms: null,
      }
      endMapTelemetryStage("api_and_parse", { durationMs: loadedAt - startedAt })
      setMapTelemetryMetadata({
        mapId,
        grid: this._performanceMetrics.grid,
        payloadBytes,
      })
      this._performanceFrameDurations = []
      this._firstDrawStartedAt = startedAt
      this._renderSubsetCache.clear()
      this._terrainOverviewCache.clear()
      this._markerBaselineById = new Map(
        (this._state.markers || []).map((marker) => [marker.id, { ...marker }]),
      )
      resetMapState()
      mapState.currentMapId = mapId
      mapEditingSession.syncBaseline(mapId, this._state.map?.editor_revision)
      if (sceneId) setCurrentScene(sceneId)
      this._rebuildIndexes()
      this._notifyMapOpened()
      return true
    } catch (err) {
      if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
        return false
      }
      toast(`加载地图失败：${err.message}`, "error")
      this._state = null
      this._layerTree = null
      this._markerBaselineById = new Map()
      this._rebuildIndexes()
      return true
    }
  },

  async _reloadMapStatePreservingSession(
    mapId,
    sceneId = mapState.currentSceneId,
    { preserveMarkers = true } = {},
  ) {
    const lifecycleEpoch = this._lifecycleEpoch
    const mountContext = this._mountContext
    const snapshotSession = () => ({
      editing: mapEditingSession.snapshotForReload(),
      currentSceneId: mapState.currentSceneId,
      sceneList: mapState.sceneList,
      currentScene: mapState.currentScene,
      focusMode: mapState.focusMode,
      focusEntityId: mapState.focusEntityId,
      focusRelatedHexes: new Set(mapState.focusRelatedHexes),
      factionColors: { ...mapState.factionColors },
      activeLayerChildIds: { ...mapState.activeLayerChildIds },
      isolateLayerNodeId: mapState.isolateLayerNodeId,
      workingMarkers: JSON.parse(JSON.stringify(this._state?.markers || [])),
    })
    let session = snapshotSession()

    const loaded = await this._loadMapState(mapId, sceneId, {
      beforeStateReplace: () => {
        session = snapshotSession()
      },
    })
    if (!loaded || !this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return false

    mapEditingSession.restoreAfterReload(session.editing, { preserveMarkers })
    mapState.currentSceneId = session.currentSceneId
    mapState.sceneList = session.sceneList
    mapState.currentScene = session.currentScene
    mapState.focusMode = session.focusMode
    mapState.focusEntityId = session.focusEntityId
    mapState.focusRelatedHexes = session.focusRelatedHexes
    mapState.factionColors = session.factionColors
    mapState.activeLayerChildIds = session.activeLayerChildIds
    mapState.isolateLayerNodeId = session.isolateLayerNodeId
    if (this._state && preserveMarkers) {
      const localMarkers = new Map(
        session.workingMarkers.map((marker) => [marker.id, marker]),
      )
      const mergedMarkers = new Map(
        (this._state.markers || []).map((marker) => [marker.id, marker]),
      )
      for (const [markerId, change] of Object.entries(
        session.editing.pendingMarkerChanges,
      )) {
        if (change.operation === "delete") {
          mergedMarkers.delete(markerId)
          continue
        }
        const local = localMarkers.get(markerId)
        if (local) mergedMarkers.set(markerId, local)
      }
      this._state.markers = [...mergedMarkers.values()]
    }
    this._rebuildIndexes()
    return true
  },

  async _loadLocations() {
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    const locations = await this._listAllEntities({
      entity_type: "location",
      novel_id: projectId,
    }).catch(() => [])
    if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
      return false
    }
    this._locations = locations
    this._rebuildIndexes()
    return true
  },

  async _loadLayerTree() {
    if (!this._state?.map?.id || !api.world.getMapLayerTree) return
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    const mapId = this._state.map.id
    try {
      const layerTree = await api.world.getMapLayerTree(
        mapId,
        projectId,
      )
      if (
        lifecycleEpoch !== this._lifecycleEpoch
        || state.currentProjectId !== projectId
        || this._state?.map?.id !== mapId
      ) return false
      this._layerTree = layerTree
      mapState.activeLayerChildIds = resolveLayerSelections({
        nodes: this._layerTree?.nodes || [],
        novelId: projectId,
        mapId,
        focusNodeId: this._mountContext?.focusLayerNodeId || null,
        previous: mapState.activeLayerChildIds,
      })
      return true
    } catch (err) {
      if (
        lifecycleEpoch !== this._lifecycleEpoch
        || state.currentProjectId !== projectId
        || this._state?.map?.id !== mapId
      ) return false
      this._layerTree = null
      toast(`图层树加载失败：${err.message}`, "warning")
      return true
    }
  },

  async _loadPaths(status = "all") {
    if (!this._state?.map?.id || !api.world.getMapPaths) {
      this._pathState = normalizePathState()
      return
    }
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    const mapId = this._state.map.id
    try {
      const pathState = normalizePathState(await api.world.getMapPaths(
        mapId,
        projectId,
        status,
      ))
      if (
        lifecycleEpoch !== this._lifecycleEpoch
        || state.currentProjectId !== projectId
        || this._state?.map?.id !== mapId
      ) return false
      this._pathState = pathState
      mapState.selectedPathLayerId ||= this._pathState.path_layers.find(
        (layer) => layer.status !== "archived",
      )?.id || null
      const focused = this._mountContext?.focusPathId
      if (focused && this._pathState.paths.some((path) => path.id === focused)) {
        mapState.selectedPathId = focused
      }
      this._pathGeometryCache.clear()
      return true
    } catch (err) {
      if (
        lifecycleEpoch !== this._lifecycleEpoch
        || state.currentProjectId !== projectId
        || this._state?.map?.id !== mapId
      ) return false
      this._pathState = normalizePathState()
      toast(`线路加载失败：${err.message}`, "warning")
      return true
    }
  },

  async _loadScenes() {
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    if (!projectId) return
    try {
      const data = await api.outline.listScenesOrdered(projectId)
      if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
        return false
      }
      mapState.sceneList = (data.items || data || []).map((s) => ({
        id: s.id,
        index: s.scene_index,
        title: s.title || `场景 ${mapSceneDisplayNumber(s.scene_index) ?? "-"}`,
      }))
      return true
    } catch {
      if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
        return false
      }
      mapState.sceneList = []
      return true
    }
  },

  async _loadAllEntities() {
    const lifecycleEpoch = this._lifecycleEpoch
    const projectId = state.currentProjectId
    if (!projectId) return
    const types = ["character", "event", "item", "location", "organization"]
    const results = await Promise.all(
      types.map((t) => this._listAllEntities({
        entity_type: t,
        novel_id: projectId,
      }).catch(() => []))
    )
    if (lifecycleEpoch !== this._lifecycleEpoch || state.currentProjectId !== projectId) {
      return false
    }
    this._allEntities = results.flat()
    this._rebuildIndexes()
    return true
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
    this._renderSubsetCache.clear()
    this._rebuildIndexes()
    this._labelsDirty = true
  },

  /**
   * 分页拉取世界对象，避免 limit 超过后端 MAX_PAGE_SIZE 导致 422。
   */
  async _listAllEntities(baseParams) {
    const novelId = baseParams.novel_id || state.currentProjectId
    if (!novelId) return []
    const all = []
    const limit = 50
    let skip = 0
    while (true) {
      const data = await api.world.listEntities({
        ...baseParams,
        novel_id: novelId,
        display_state: "active",
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

  _render(rootId, viewport = null) {
    this._clearPendingTimers()
    const root = document.getElementById(rootId)
    if (!root) return

    if (this._maps.length === 0 && !this._state) {
      // 空列表：显示创建入口
      root.innerHTML = this._renderEmpty()
      this._bindListEvents()
      return
    }

    if (!this._state) {
      // 有列表但未选地图：显示列表
      root.innerHTML = this._renderList()
      this._bindListEvents()
      return
    }

    // 已选地图：渲染地图视图
    root.innerHTML = this._renderMapShell()
    this._defer(() => this._initLeaflet(loadLeafletForMapView, viewport))
    this._bindMapEvents()
  },

  _renderEmpty() {
    return `
      <div class="view-header map-toolbar">
        <div class="view-header__title">地图</div>
        <div class="view-header__actions">
          <button class="btn btn-sm btn-primary" data-action="map-create-world">+ 创建世界地图</button>
        </div>
      </div>
      ${this._mapsLoadError ? `
        <div class="empty-state" role="alert">
          <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
          <p>地图列表加载失败</p>
          <p class="world-text-dim">可稍后重试。错误信息：${esc(this._mapsLoadError)}</p>
        </div>
      ` : `
      <div class="empty-state">
        <div class="empty-icon">&#9744;</div>
        <p>暂无地图</p>
        <p class="world-text-dim">创建第一张世界地图开始构建你的世界</p>
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
          <button class="btn btn-sm" data-action="map-delete" data-id="${esc(m.id)}">归档</button>
        </td>
      </tr>
    `).join("")
    return `
      <div class="view-header map-toolbar">
        <div class="view-header__title">
          地图
          <span class="view-header__count">${esc(this._maps.length)} 张</span>
        </div>
        <div class="view-header__actions">
          <button class="btn btn-sm btn-primary" data-action="map-create-world">+ 创建世界地图</button>
        </div>
      </div>
      ${renderBulkToolbar(this, scope, [
        { action: "delete-maps", label: "批量归档地图" },
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
      return `<div class="map-scene-bar"><span class="map-scene-hint">暂无场景资料（请先在故事结构中创建场景）</span></div>`
    }
    const currentIdx = scenes.findIndex((s) => s.id === mapState.currentSceneId)
    const sceneLabel = currentIdx >= 0
      ? `场景 ${mapSceneDisplayNumber(scenes[currentIdx].index) ?? "-"}: ${esc(scenes[currentIdx].title || "")}`
      : "选择场景"

    return `
      <div class="map-scene-bar">
        <button class="btn btn-sm" data-action="map-scene-prev" ${currentIdx <= 0 ? "disabled" : ""} title="${currentIdx <= 0 ? "没有上一个场景" : "上一个场景"}">←</button>
        <span class="map-scene-label" data-action="map-scene-pick">${sceneLabel}</span>
        <button class="btn btn-sm" data-action="map-scene-next" ${currentIdx >= scenes.length - 1 ? "disabled" : ""} title="${currentIdx >= scenes.length - 1 ? "没有下一个场景" : "下一个场景"}">→</button>
        <button class="btn btn-sm" data-action="map-scene-clear" ${!mapState.currentSceneId ? "disabled" : ""} title="${!mapState.currentSceneId ? "当前未选择场景" : "清除场景聚焦"}">清除</button>
      </div>
    `
  },

  _renderMapShell() {
    const compactViewport = this._isCompactViewport()
    const breadcrumbs = (this._state.breadcrumbs || [])
      .map((b, i) => {
        const isLast = i === this._state.breadcrumbs.length - 1
        return `<span class="map-crumb ${isLast ? "active" : ""}" data-action="map-breadcrumb" data-id="${esc(b.id)}">${esc(b.name)}</span>`
      })
      .join('<span class="map-crumb-sep">→</span>')

    const editBtn = compactViewport
      ? `<button class="btn btn-sm" data-action="map-mobile-edit-handoff">请在桌面端编辑</button>`
      : mapState.mode === "edit"
      ? `<button class="btn btn-sm" data-action="map-exit-edit">退出编辑</button>`
      : `<button class="btn btn-sm" data-action="map-enter-edit">编辑</button>`

    const editablePaths = this._effectivePaths().map((path) => {
      const nodes = pathNodesFor(path, this._pathState?.nodes || [])
      return {
        ...path,
        start_endpoint_status: this._pathEndpointStatus(path, "start", nodes[0]),
        end_endpoint_status: this._pathEndpointStatus(path, "end", nodes.at(-1)),
      }
    })
    const editPanelHtml = mapState.mode === "edit" && !compactViewport
      ? renderEditPanel({
        locations: this._locations,
        locationLayouts: this._effectiveLocationLayouts(),
        allEntities: this._allEntities,
        scenes: mapState.sceneList,
        terrainLayers: this._state.terrain_layers || [],
        layerTree: (mapState.pendingLayerTree || this._layerTree?.nodes || []).map((node) => ({
          ...node,
          session_reason: activeSelectionReason(
            node,
            mapState.pendingLayerTree || this._layerTree?.nodes || [],
            mapState.activeLayerChildIds,
          ),
        })),
        pathLayers: this._effectivePathLayers().map((layer) => {
          const leaf = (mapState.pendingLayerTree || this._layerTree?.nodes || []).find(
            (node) => node.path_layer_id === layer.id || node.path_layer_client_id === layer.id,
          )
          return { ...layer, name: leaf?.name || layer.name || layer.display_name }
        }),
        paths: editablePaths,
        pathProfiles: MAP_PATH_PROFILES,
        territoryTools: this._renderTerritoryTools(),
        pendingCount: mapEditingSession.draftChangeCount(),
      })
      : ""

    return `
      <div class="view-header map-toolbar">
        <div class="view-header__title map-breadcrumb">${breadcrumbs}</div>
        <div class="view-header__actions">
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
      ${compactViewport ? `
        <div class="map-mobile-edit-handoff" role="note">
          <strong>移动端为浏览模式</strong>
          <span>当前地图包含 ${(this._state.terrain_layers || []).length} 个地形图层、${this._effectivePaths().length} 条线路、${(this._state.territories || []).length} 个势力格。地形绘制、线路节点精修、势力涂抹和图层结构编辑请在桌面端继续。</span>
        </div>
      ` : ""}
      ${this._renderSceneBar()}
      ${this._renderFactionList()}
      <div class="map-filter-bar">
        <span class="badge badge-canonical map-filter active" data-action="map-filter" data-filter="all">全部</span>
        <span class="badge map-filter" data-action="map-filter" data-filter="location">地点</span>
      </div>
    `
  },

  _renderDetailPanel(q, r) {
    const selectedLocation = mapState.selectedMapObject?.kind === "location"
      && Number(mapState.selectedMapObject.q) === Number(q)
      && Number(mapState.selectedMapObject.r) === Number(r)
      ? mapState.selectedMapObject
      : null
    const selectedBinding = selectedLocation
      ? (this._state?.location_bindings || []).find(
        (item) => item.id === selectedLocation.id
          || (item.location_entity_id === selectedLocation.entityId && item.is_center),
      ) || null
      : null
    // Clicking an explicit location label is a stronger intent than the
    // coordinate hit order. A character marker or route may share the same
    // hex, but must not replace the location detail the author just selected.
    const marker = selectedBinding ? null : this._markerAt(q, r)
    const binding = selectedBinding || this._visibleBindingAt(q, r)
    const path = marker || binding ? null : this._pathAt(q, r)
    if (path) return this._renderPathDetail(path)
    if (marker) {
      return this._renderMarkerDetail(marker, q, r)
    }
    const territory = this._visibleTerritoryAt(q, r)
    if (territory) {
      return this._renderTerritoryDetail(territory, q, r)
    }
    const terrainState = this._terrainRenderState()
    const patch = this._visibleTerrainPatchAt(q, r, terrainState)
    if (patch) {
      const layer = terrainState.layers.find((item) => item.id === patch.layer_id)
      return `
        <div class="map-detail-header">${esc(layer?.name || "覆盖素材")}</div>
        <div class="map-detail-section"><div class="map-detail-label">类型</div><div class="map-detail-value">覆盖素材 · ${esc(layer?.terrain_asset_key || "unknown")}</div></div>
        <div class="map-detail-section"><div class="map-detail-label">坐标</div><div class="map-detail-value">q:${q}, r:${r}</div></div>
      `
    }
    if (binding) {
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
          ${binding.is_center ? `<button class="btn btn-sm btn-primary" data-action="map-detail-drill" data-id="${esc(binding.location_entity_id)}">${esc(actionText)}</button>` : ""}
          <button class="btn btn-sm" data-action="map-detail-focus-entity" data-id="${esc(binding.location_entity_id)}">叙事透镜</button>
          <button class="btn btn-sm" data-action="map-detail-world-object" data-id="${esc(binding.location_entity_id)}">查看世界对象</button>
        </div>
      `
    }
    const tile = this._visibleTileAt(q, r)
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

  _renderMarkerDetail(marker, q = marker?.hex_q, r = marker?.hex_r) {
    if (!marker) return `<div class="map-detail-empty">标记不可用</div>`
    const typeLabel = {
      character: "人物标记",
      event: "事件标记",
      item: "物品标记",
    }[marker.marker_type] || "标记"
    return `
      <div class="map-detail-header">${esc(marker.label || typeLabel)}</div>
      <div class="map-detail-section"><div class="map-detail-label">类型</div><div class="map-detail-value">${esc(typeLabel)}</div></div>
      <div class="map-detail-section"><div class="map-detail-label">坐标</div><div class="map-detail-value">q:${esc(q)}, r:${esc(r)}</div></div>
      <div class="map-detail-actions">
        <button class="btn btn-sm btn-primary" data-action="map-detail-focus-entity" data-id="${esc(marker.entity_id)}">叙事透镜</button>
        <button class="btn btn-sm" data-action="map-detail-world-object" data-id="${esc(marker.entity_id)}">查看世界对象</button>
      </div>
    `
  },

  _renderTerritoryDetail(territory, q = territory?.hex_q, r = territory?.hex_r) {
    if (!territory) return `<div class="map-detail-empty">势力范围不可用</div>`
    const entity = (this._allEntities || []).find(
      (item) => item.id === territory.faction_entity_id,
    )
    return `
      <div class="map-detail-header">${esc(entity?.name || "领地")}</div>
      <div class="map-detail-section"><div class="map-detail-label">类型</div><div class="map-detail-value">领地</div></div>
      <div class="map-detail-section"><div class="map-detail-label">坐标</div><div class="map-detail-value">q:${esc(q)}, r:${esc(r)}</div></div>
      <div class="map-detail-actions">
        <button class="btn btn-sm btn-primary" data-action="map-detail-focus-entity" data-id="${esc(territory.faction_entity_id)}">叙事透镜</button>
        <button class="btn btn-sm" data-action="map-detail-world-object" data-id="${esc(territory.faction_entity_id)}">查看世界对象</button>
      </div>
    `
  },

  _renderPathDetail(path) {
    if (!path) return `<div class="map-detail-empty">线路不可用</div>`
    const profile = MAP_PATH_PROFILES[path.path_type]
    const nodes = pathNodesFor(path, this._pathState?.nodes || [])
    const start = this._pathEndpointStatus(path, "start", nodes[0])
    const end = this._pathEndpointStatus(path, "end", nodes.at(-1))
    return `
      <div class="map-detail-header">${esc(path.name || "未命名线路")}</div>
      <div class="map-detail-section"><div class="map-detail-label">类型</div><div class="map-detail-value">${esc(profile?.label || path.path_type || "线路")}${path.status === "archived" ? " · 已归档" : ""}</div></div>
      <div class="map-detail-section"><div class="map-detail-label">路线细节</div><div class="map-detail-value">${nodes.length} 个节点</div></div>
      ${start ? `<div class="map-detail-section"><div class="map-detail-label">起点</div><div class="map-detail-value ${start.drifted ? "is-warning" : ""}">${esc(start.name)}${start.unresolved ? " · 未布置" : start.drifted ? ` · 偏离 ${start.distance.toFixed(2)} 格` : " · 已对齐"}</div></div>` : ""}
      ${end ? `<div class="map-detail-section"><div class="map-detail-label">终点</div><div class="map-detail-value ${end.drifted ? "is-warning" : ""}">${esc(end.name)}${end.unresolved ? " · 未布置" : end.drifted ? ` · 偏离 ${end.distance.toFixed(2)} 格` : " · 已对齐"}</div></div>` : ""}
    `
  },

  _locationAnchor(entityId) {
    if (!entityId) return null
    const layout = this._effectiveLocationLayouts().find(
      (item) => item.location_entity_id === entityId,
    )
    if (layout) return { q: Number(layout.center_hex_q), r: Number(layout.center_hex_r) }
    const bindings = (this._state?.location_bindings || []).filter(
      (item) => item.location_entity_id === entityId,
    )
    const center = bindings.find((item) => item.is_center)
    if (center) return { q: Number(center.hex_q), r: Number(center.hex_r) }
    if (!bindings.length) return null
    return {
      q: bindings.reduce((sum, item) => sum + Number(item.hex_q), 0) / bindings.length,
      r: bindings.reduce((sum, item) => sum + Number(item.hex_r), 0) / bindings.length,
    }
  },

  _pathEndpointStatus(path, side, node) {
    const entityId = path?.[`${side}_location_entity_id`]
    if (!entityId || !node) return null
    const anchor = this._locationAnchor(entityId)
    const entity = this._locationById.get(entityId)
    if (!anchor) return { name: entity?.name || "未命名地点", unresolved: true, drifted: false, distance: null }
    const distance = Math.hypot(anchor.q - node.q, anchor.r - node.r)
    return {
      name: entity?.name || "未命名地点",
      unresolved: false,
      drifted: distance > 0.75,
      distance,
    }
  },

  _updateDetailPanel(q, r) {
    const panel = document.getElementById("map-detail-panel")
    if (!panel) return
    panel.innerHTML = this._renderDetailPanel(q, r)
  },

  // ============================================================
  // Leaflet 初始化 + canvas overlay
  // ============================================================

  async _initLeaflet(loadLeaflet = loadLeafletForMapView, viewport = null) {
    let container = document.getElementById("map-leaflet")
    if (!container || !this._state || this._leaflet) return
    const lifecycleEpoch = this._lifecycleEpoch
    const stateAtLoad = this._state

    startMapTelemetryStage("leaflet_init")
    let leafletApi
    try {
      leafletApi = await loadLeaflet()
    } catch {
      if (this._lifecycleEpoch === lifecycleEpoch && this._state === stateAtLoad) {
        this._renderLeafletLoadFailure(container, loadLeaflet)
      }
      return
    }

    container = document.getElementById("map-leaflet")
    if (
      !container
      || this._lifecycleEpoch !== lifecycleEpoch
      || this._state !== stateAtLoad
      || this._leaflet
    ) return
    this._leafletApi = leafletApi
    container.querySelector('[data-leaflet-load-failure="true"]')?.remove()

    const cfg = this._state.map
    // 用一个 CRS.Simple 投影，把 hex 像素坐标当世界坐标
    this._leaflet = leafletApi.map(container, {
      crs: leafletApi.CRS.Simple,
      minZoom: MAP_FIT_FLOOR_ZOOM,
      maxZoom: 3,
      zoomControl: true,
      attributionControl: false,
    })
    const labelPane = this._leaflet.getPane?.("mapLabels")
      || this._leaflet.createPane?.("mapLabels")
    if (labelPane) {
      labelPane.classList?.add("map-label-pane")
      labelPane.style.zIndex = "450"
      labelPane.style.pointerEvents = "none"
    }

    const size = cfg.hex_size || 30
    // 计算地图像素边界
    const w = cfg.grid_width
    const h = cfg.grid_height
    const [, lastY] = hexToPixel(w - 1, h - 1, size)
    const bounds = leafletApi.latLngBounds(
      [[-(lastY + size), -size], [size, (size * 1.5 * (w - 1)) + size]]
    )
    const fittedZoom = Number(this._leaflet.getBoundsZoom?.(bounds))
    if (Number.isFinite(fittedZoom)) {
      this._leaflet.setMinZoom?.(Math.min(MAP_DEFAULT_MIN_ZOOM, fittedZoom))
    }
    this._leaflet.fitBounds(bounds)
    this._focusViewportFromContext(size)
    if (
      Number.isFinite(viewport?.center?.lat)
      && Number.isFinite(viewport?.center?.lng)
      && Number.isFinite(viewport?.zoom)
      && this._leaflet.setView
    ) {
      this._leaflet.setView(viewport.center, viewport.zoom, { animate: false })
    }

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
    this._canvas.style.zIndex = "350"
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
    container.addEventListener("wheel", () => {
      recordMapInput("wheel")
      this._scheduleRedraw()
    }, { capture: true, passive: true })
    // Pointer Events 同时覆盖鼠标与触控；拖动期间暂停 Leaflet 平移。
    this._canvas.style.touchAction = "none"
    this._canvas.addEventListener("pointermove", (e) => this._handleCanvasMouseMove(e))
    this._canvas.addEventListener("mouseout", () => this._handleCanvasMouseOut())
    this._canvas.addEventListener("pointerdown", (e) => this._handleCanvasMouseDown(e))
    this._canvas.addEventListener("pointerup", (e) => this._handleCanvasMouseUp(e))
    this._canvas.addEventListener("pointercancel", (e) => this._handleCanvasMouseUp(e))
    endMapTelemetryStage("leaflet_init")
    markMapTelemetryCondition("leaflet_ready")
  },

  _renderLeafletLoadFailure(container, loadLeaflet = loadLeafletForMapView) {
    const state = document.createElement("div")
    state.className = "empty-state"
    state.dataset.leafletLoadFailure = "true"
    state.setAttribute("role", "alert")
    const icon = document.createElement("div")
    icon.className = "empty-icon"
    icon.textContent = "⚠"
    const title = document.createElement("p")
    title.textContent = "地图引擎加载失败"
    const detail = document.createElement("p")
    detail.className = "world-text-dim"
    detail.textContent = "本地地图资源暂时无法加载，其他页面不受影响。"
    const retry = document.createElement("button")
    retry.type = "button"
    retry.className = "btn btn-sm btn-primary"
    retry.textContent = "重试加载地图"
    retry.addEventListener("click", () => {
      retry.disabled = true
      this._initLeaflet(loadLeaflet)
    }, { once: true })
    state.append(icon, title, detail, retry)
    container.replaceChildren(state)
  },

  _scheduleRedraw() {
    if (this._redrawFrame) return
    this._redrawFrame = requestAnimationFrame(() => {
      this._redrawFrame = null
      this._redraw()
    })
  },

  _focusViewportFromContext(size) {
    let rawQ = this._mountContext?.focusHexQ
    let rawR = this._mountContext?.focusHexR
    if ((rawQ == null || rawR == null) && this._mountContext?.focusPathId) {
      const path = this._effectivePaths().find(
        (item) => item.id === this._mountContext.focusPathId,
      )
      const point = path ? representativePathPoint(path, this._pathState?.nodes || []) : null
      rawQ = point?.q
      rawR = point?.r
    }
    if (rawQ == null || rawR == null) return
    const q = Number(rawQ)
    const r = Number(rawR)
    if (!Number.isFinite(q) || !Number.isFinite(r) || !this._leaflet?.setView) return
    const [x, y] = hexToPixel(q, r, size)
    const currentZoom = Number(this._leaflet.getZoom?.() ?? 0)
    this._leaflet.setView(this._leafletApi.latLng(-y, x), Math.max(1, currentZoom))
  },

  _effectiveLayerNode({ layerKey = null, terrainLayerId = null, pathLayerId = null, zoom = null } = {}) {
    const nodes = mapState.pendingLayerTree || this._layerTree?.nodes || []
    const node = terrainLayerId
      ? nodes.find((item) => item.terrain_layer_id === terrainLayerId || item.terrain_layer_client_id === terrainLayerId)
      : pathLayerId
        ? nodes.find((item) => item.path_layer_id === pathLayerId || item.path_layer_client_id === pathLayerId)
        : nodes.find((item) => item.layer_key === layerKey)
    if (!node) return {
      visible: true,
      interactiveVisible: true,
      sessionVisible: true,
      locked: false,
      opacity: 1,
    }
    const minZoom = node.effective_min_zoom ?? node.min_zoom
    const maxZoom = node.effective_max_zoom ?? node.max_zoom
    const inZoom = (zoom == null || minZoom == null || zoom >= minZoom)
      && (zoom == null || maxZoom == null || zoom <= maxZoom)
    const structuralVisible = (node.effective_visible ?? node.visible) !== false && inZoom
    const sessionVisible = sessionLayerVisible(
      node,
      nodes,
      mapState.activeLayerChildIds,
      mapState.isolateLayerNodeId,
    )
    const isolateBaseContext = Boolean(
      mapState.isolateLayerNodeId
      && layerKey === "baseTerrain"
      && !sessionVisible,
    )
    return {
      visible: structuralVisible && (sessionVisible || isolateBaseContext),
      interactiveVisible: structuralVisible && sessionVisible,
      sessionVisible,
      locked: Boolean(node.effective_locked ?? node.locked),
      opacity: isolateBaseContext ? 0.15 : Number(node.effective_opacity ?? node.opacity ?? 1),
      minZoom,
      maxZoom,
      sessionReason: structuralVisible
        ? activeSelectionReason(node, nodes, mapState.activeLayerChildIds)
        : "结构隐藏",
      node,
    }
  },

  _viewportPredicate(size, origin, scale) {
    const margin = size * 2
    const minX = (0 - origin.x) / scale - margin
    const maxX = (this._canvas.width - origin.x) / scale + margin
    const minY = (0 - origin.y) / scale - margin
    const maxY = (this._canvas.height - origin.y) / scale + margin
    return (item) => {
      if (item?.hex_q == null || item?.hex_r == null) return false
      const [x, y] = hexToPixel(item.hex_q, item.hex_r, size)
      return x >= minX && x <= maxX && y >= minY && y <= maxY
    }
  },

  _pathViewport(size, origin, scale) {
    const toAxial = (px, py) => {
      const x = (px - origin.x) / scale
      const y = (py - origin.y) / scale
      return {
        q: (2 / 3) * x / size,
        r: (-x / 3 + Math.sqrt(3) * y / 3) / size,
      }
    }
    const corners = [
      toAxial(0, 0),
      toAxial(this._canvas.width, 0),
      toAxial(0, this._canvas.height),
      toAxial(this._canvas.width, this._canvas.height),
    ]
    return {
      minQ: Math.min(...corners.map((point) => point.q)) - 1,
      maxQ: Math.max(...corners.map((point) => point.q)) + 1,
      minR: Math.min(...corners.map((point) => point.r)) - 1,
      maxR: Math.max(...corners.map((point) => point.r)) + 1,
    }
  },

  _effectivePathLayers() {
    const layers = new Map((this._pathState?.path_layers || []).map((layer) => [layer.id, { ...layer }]))
    for (const change of Object.values(mapState.pendingPathLayerChanges || {})) {
      const id = change.client_id || change.id
      if (!id) continue
      if (change.operation === "delete") layers.delete(id)
      else if (change.operation === "create") {
        layers.set(id, {
          id,
          client_id: change.client_id,
          __draft: true,
          category: change.data?.category || "transport",
          name: change.data?.display_name || change.data?.name || "新线路图层",
        })
      }
    }
    return [...layers.values()]
  },

  _effectivePaths() {
    const paths = new Map((this._pathState?.paths || []).map((path) => [path.id, { ...path }]))
    for (const change of Object.values(mapState.pendingPathChanges || {})) {
      const id = change.client_id || change.id
      if (!id) continue
      if (change.operation === "create") {
        paths.set(id, {
          id,
          client_id: change.client_id,
          __draft: true,
          status: "active",
          visible: true,
          opacity: 1,
          ...change.data,
        })
      } else if (change.operation === "update") {
        const current = paths.get(id)
        if (current) paths.set(id, { ...current, ...change.data })
      } else if (change.operation === "archive") {
        const current = paths.get(id)
        if (current) paths.set(id, { ...current, status: "archived" })
      } else if (change.operation === "restore") {
        const current = paths.get(id)
        if (current) paths.set(id, { ...current, status: "active" })
      }
    }
    const layerRanks = this._pathLayerDfsRanks()
    return [...paths.values()].sort((left, right) => {
      const leftLayer = this._pathLayerId(left)
      const rightLayer = this._pathLayerId(right)
      return (layerRanks.get(leftLayer) ?? Number.MAX_SAFE_INTEGER)
        - (layerRanks.get(rightLayer) ?? Number.MAX_SAFE_INTEGER)
        || String(leftLayer || "").localeCompare(String(rightLayer || ""))
        || Number(left.sort_order || 0) - Number(right.sort_order || 0)
        || String(left.id || left.client_id || "").localeCompare(String(right.id || right.client_id || ""))
    })
  },

  _pathLayerDfsRanks() {
    const nodes = mapState.pendingLayerTree || this._layerTree?.nodes || []
    const children = new Map()
    for (const node of nodes) {
      const parent = node.parent_id || node.parent_client_id || null
      const siblings = children.get(parent) || []
      siblings.push(node)
      children.set(parent, siblings)
    }
    for (const siblings of children.values()) {
      siblings.sort((left, right) => (
        Number(left.sort_order || 0) - Number(right.sort_order || 0)
        || String(this._layerNodeIdentity(left) || "").localeCompare(
          String(this._layerNodeIdentity(right) || ""),
        )
      ))
    }
    const ranks = new Map()
    let rank = 0
    const visit = (node) => {
      const layerId = node.path_layer_id || node.path_layer_client_id
      if (layerId) ranks.set(layerId, rank)
      rank += 1
      for (const child of children.get(this._layerNodeIdentity(node)) || []) visit(child)
    }
    for (const root of children.get(null) || []) visit(root)
    return ranks
  },

  _pathLayerId(path) {
    return path.path_layer_id
      || path.layer_id
      || path.path_layer_ref?.id
      || path.path_layer_ref?.client_id
      || null
  },

  _pathVisible(path, zoom = this._leaflet?.getZoom?.() ?? null) {
    if (path.status === "archived" && path.id !== this._mountContext?.focusPathId) return false
    const minZoom = path.min_zoom
    const maxZoom = path.max_zoom
    if (zoom != null && minZoom != null && zoom < minZoom) return false
    if (zoom != null && maxZoom != null && zoom > maxZoom) return false
    return path.visible !== false && this._effectiveLayerNode({
      pathLayerId: this._pathLayerId(path),
      zoom,
    }).visible
  },

  _pathOpacity(path, zoom = this._leaflet?.getZoom?.() ?? null) {
    return this._effectiveLayerNode({
      pathLayerId: this._pathLayerId(path),
      zoom,
    }).opacity
  },

  _visibleRenderSubset(size, origin, scale, zoom) {
    const predicate = this._viewportPredicate(size, origin, scale)
    const revision = Number(this._state.map.editor_revision || 0)
    // Draft edits no longer disable viewport caching wholesale. Draft mutation
    // paths invalidate this cache, so unchanged animation frames can reuse the
    // indexed visible subset even while the editor remains dirty.
    const cacheable = true
    const workspaceLayers = this._mountContext?.layers || {}
    const key = [
      this._state.map.id,
      revision,
      zoom,
      Math.round(origin.x),
      Math.round(origin.y),
      this._canvas.width,
      this._canvas.height,
      workspaceLayers.terrain !== false,
      workspaceLayers.locations !== false,
      workspaceLayers.markers !== false,
      workspaceLayers.events !== false,
      workspaceLayers.items !== false,
      workspaceLayers.territories !== false,
      workspaceLayers.candidate === true,
      JSON.stringify(mapState.activeLayerChildIds),
      mapState.isolateLayerNodeId || "",
      JSON.stringify(mapState.pendingPathChanges),
    ].join(":")
    if (cacheable && this._renderSubsetCache.has(key)) {
      if (this._renderMetrics) this._renderMetrics.cache_hit = true
      return this._renderSubsetCache.get(key)
    }
    const terrainState = this._terrainRenderState(zoom)
    const baseState = this._effectiveLayerNode({ layerKey: "baseTerrain", zoom })
    const locationState = this._effectiveLayerNode({ layerKey: "location", zoom })
    const territoryState = this._effectiveLayerNode({ layerKey: "territory", zoom })
    const pendingState = this._effectiveLayerNode({ layerKey: "pending", zoom })
    const baseVisible = this._isLayerEnabled("terrain") && baseState.visible
    const locationsVisible = this._isLayerEnabled("locations") && locationState.visible
    const territoriesVisible = this._isLayerEnabled("territories") && territoryState.visible
    const pendingVisible = this._isLayerEnabled("candidate") && pendingState.visible
    const visibleTerrainLayerIds = new Set(
      terrainState.layers.filter((layer) => layer.visible !== false).map((layer) => layer.id),
    )
    const visibleMarkers = this._filteredMarkers(zoom).filter(predicate)
    const markersByType = { character: [], event: [], item: [] }
    for (const marker of visibleMarkers) {
      const markerType = marker.marker_type || "character"
      ;(markersByType[markerType] ||= []).push(marker)
    }
    const subset = {
      tiles: baseVisible ? (this._state.tiles || []).filter(predicate) : [],
      bindings: locationsVisible
        ? (this._state.location_bindings || []).filter(predicate)
        : [],
      markers: visibleMarkers,
      markersByType,
      territories: territoriesVisible
        ? this._effectiveTerritories().filter(predicate)
        : [],
      candidateBindings: pendingVisible
        ? (this._state.candidate_location_bindings || []).filter(predicate)
        : [],
      candidateMarkers: pendingVisible
        ? this._candidateMarkers(zoom).filter(predicate)
        : [],
      candidateTerritories: pendingVisible
        ? (this._state.candidate_territories || []).filter(predicate)
        : [],
      terrain: {
        layers: terrainState.layers,
        regions: terrainState.regions,
        patches: terrainState.patches.filter(
          (patch) => visibleTerrainLayerIds.has(patch.layer_id) && predicate(patch),
        ),
      },
      predicate,
    }
    this._renderMetrics = {
      map_id: this._state.map.id,
      editor_revision: revision,
      zoom,
      total_hex_items: (this._state.tiles || []).length
        + (this._state.location_bindings || []).length
        + (this._state.markers || []).length
        + (this._state.territories || []).length
        + (terrainState.patches || []).length,
      queued_hex_items: subset.tiles.length
        + subset.bindings.length
        + subset.markers.length
        + subset.territories.length
        + subset.terrain.patches.length,
      cache_hit: false,
    }
    this._renderMetrics.culled_hex_items = Math.max(
      0,
      this._renderMetrics.total_hex_items - this._renderMetrics.queued_hex_items,
    )
    if (cacheable) {
      if (this._renderSubsetCache.size >= 8) this._renderSubsetCache.clear()
      this._renderSubsetCache.set(key, subset)
    }
    return subset
  },

  _terrainOverviewRaster(size) {
    const cfg = this._state?.map
    const tiles = this._state?.tiles || []
    if (!cfg || tiles.length < 1000 || typeof document === "undefined") return null
    const revision = Number(cfg.editor_revision || 0)
    const key = [
      cfg.id,
      revision,
      cfg.grid_width,
      cfg.grid_height,
      size,
      tiles.length,
    ].join(":")
    if (this._terrainOverviewCache.has(key)) {
      return this._terrainOverviewCache.get(key)
    }

    const rasterHexSize = 2
    const rasterScale = rasterHexSize / size
    const [lastX, lastY] = hexToPixel(
      Number(cfg.grid_width) - 1,
      Number(cfg.grid_height) - 1,
      size,
    )
    const worldBounds = {
      x: -size,
      y: -size,
      width: lastX + size * 2,
      height: lastY + size * 2,
    }
    const canvas = document.createElement("canvas")
    canvas.width = Math.max(1, Math.ceil(worldBounds.width * rasterScale))
    canvas.height = Math.max(1, Math.ceil(worldBounds.height * rasterScale))
    const context = canvas.getContext("2d")
    if (!context?.fillRect) return null

    const byColor = new Map()
    for (const tile of tiles) {
      const color = (TERRAIN_COLORS[tile.terrain_type] || TERRAIN_COLORS.grassland).fill
      const items = byColor.get(color) || []
      items.push(tile)
      byColor.set(color, items)
    }
    const cellSize = Math.ceil(rasterHexSize * 1.8)
    const halfCell = cellSize / 2
    for (const [color, items] of byColor) {
      context.fillStyle = color
      for (const tile of items) {
        const [x, y] = hexToPixel(tile.hex_q, tile.hex_r, rasterHexSize)
        context.fillRect(
          Math.floor(x + rasterHexSize - halfCell),
          Math.floor(y + rasterHexSize - halfCell),
          cellSize,
          cellSize,
        )
      }
    }
    const raster = { canvas, ...worldBounds }
    if (this._terrainOverviewCache.size >= 2) this._terrainOverviewCache.clear()
    this._terrainOverviewCache.set(key, raster)
    return raster
  },

  /** Leaflet 视口变换 → 计算 canvas 偏移/缩放，重绘 */
  _redraw(options = {}) {
    if (!this._ctx || !this._canvas || !this._state) return
    const frameStartedAt = performance.now()
    this._syncCanvasSize()
    const cfg = this._state.map
    const size = cfg.hex_size || 30
    const origin = this._leaflet.latLngToContainerPoint([0, 0])
    const zoom = this._leaflet.getZoom()
    const scale = Math.pow(2, zoom)
    const visible = this._visibleRenderSubset(size, origin, scale, zoom)

    this._ctx.setTransform(1, 0, 0, 1, 0, 0)
    this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height)
    this._ctx.save()
    this._ctx.translate(origin.x, origin.y)
    this._ctx.scale(scale, scale)

    const showBoundary = this._currentFilter === "location"
    const getHexOpacity = this._getHexOpacity.bind(this)
    const baseLayer = this._effectiveLayerNode({ layerKey: "baseTerrain", zoom })
    const locationLayer = this._effectiveLayerNode({ layerKey: "location", zoom })
    const territoryLayer = this._effectiveLayerNode({ layerKey: "territory", zoom })
    const pendingLayer = this._effectiveLayerNode({ layerKey: "pending", zoom })
    if (this._isLayerEnabled("terrain") && baseLayer.visible) {
      this._drawWithOpacity(baseLayer.opacity, () => {
        const overview = size * scale < 2
          ? this._terrainOverviewRaster(size)
          : null
        if (!overview) {
          drawTerrain(this._ctx, visible.tiles, size, 0, 0, getHexOpacity)
          return
        }
        this._ctx.save()
        this._ctx.imageSmoothingEnabled = false
        if (mapState.focusMode) this._ctx.globalAlpha *= 0.3
        this._ctx.drawImage(
          overview.canvas,
          overview.x,
          overview.y,
          overview.width,
          overview.height,
        )
        this._ctx.restore()
        if (mapState.focusMode) {
          drawTerrain(
            this._ctx,
            visible.tiles.filter((tile) => getHexOpacity(tile.hex_q, tile.hex_r) === 1),
            size,
            0,
            0,
          )
        }
      })
    }
    if (this._isLayerEnabled("terrain") && this._effectiveLayerNode({ layerKey: "terrainOverlay", zoom }).visible) {
      drawTerrainLayers(this._ctx, visible.terrain, {
        hexSize: size,
        editMode: mapState.mode === "edit",
      })
    }
    const effectivePaths = this._effectivePaths()
    const queuedPaths = drawMapPaths(
      this._ctx,
      effectivePaths,
      this._pathState?.nodes || [],
      {
        hexSize: size,
        isVisible: (path) => this._pathVisible(path, zoom),
        opacityFor: (path) => this._pathOpacity(path, zoom),
        viewport: this._pathViewport(size, origin, scale),
        selectedPathId: mapState.selectedPathId,
        selectedNodeIndex: mapState.selectedPathNodeIndex,
        focusedPathId: this._mountContext?.focusPathId || null,
        editMode: mapState.mode === "edit" && mapState.editorLayer === "path",
        geometryCache: this._pathGeometryCache,
      },
    )
    if (this._pathPointerSamples?.length > 1) {
      drawMapPaths(this._ctx, [{
        id: "__path_preview__",
        path_type: mapState.selectedPathType,
        nodes: this._normalizedPathNodes(this._pathPointerSamples),
        opacity: 0.8,
      }], [], {
        hexSize: size,
        viewport: this._pathViewport(size, origin, scale),
      })
    }
    if (this._renderMetrics) {
      this._renderMetrics.total_path_nodes = effectivePaths.reduce(
        (total, path) => total + pathNodesFor(path, this._pathState?.nodes || []).length,
        0,
      )
      this._renderMetrics.queued_path_nodes = queuedPaths.reduce(
        (total, item) => total + item.nodes.length,
        0,
      )
    }
    if (this._isLayerEnabled("locations") && locationLayer.visible) {
      this._drawWithOpacity(locationLayer.opacity, () => {
        drawBindings(this._ctx, visible.bindings, size, 0, 0, showBoundary, getHexOpacity)
      })
    }
    for (const markerType of ["character", "event", "item"]) {
      const markerLayer = this._effectiveLayerNode({ layerKey: `marker.${markerType}`, zoom })
      this._drawWithOpacity(markerLayer.opacity, () => {
        drawMarkers(
          this._ctx,
          visible.markersByType?.[markerType] || [],
          size,
          0,
          0,
        )
      })
    }
    if (this._isLayerEnabled("territories") && territoryLayer.visible) {
      this._drawWithOpacity(territoryLayer.opacity, () => {
        drawTerritories(this._ctx, visible.territories, size, 0, 0, mapState.factionColors, getHexOpacity)
      })
    }
    if (this._isLayerEnabled("candidate") && pendingLayer.visible) {
      this._drawWithOpacity(pendingLayer.opacity, () => {
        drawCandidateBindings(this._ctx, visible.candidateBindings, size, 0, 0, getHexOpacity)
        drawCandidateMarkers(this._ctx, visible.candidateMarkers, size, 0, 0)
        drawCandidateTerritories(this._ctx, visible.candidateTerritories, size, 0, 0, mapState.factionColors, getHexOpacity)
      })
    }

    // 待应用变更叠加在基础地形之上
    if (this._isLayerEnabled("terrain") && baseLayer.visible) {
      this._drawWithOpacity(baseLayer.opacity, () => {
        drawPendingTerrain(this._ctx, Object.fromEntries(Object.entries(mapState.pendingTerrainChanges).filter(([, item]) => visible.predicate(item))), size, 0, 0, getHexOpacity)
      })
    }
    if (this._isLayerEnabled("locations") && locationLayer.visible) {
      this._drawWithOpacity(locationLayer.opacity, () => {
        drawPendingBindings(this._ctx, Object.fromEntries(Object.entries(mapState.pendingBindings).filter(([, item]) => visible.predicate(item))), size, 0, 0, getHexOpacity)
      })
    }

    drawContextHighlights(this._ctx, this._contextHighlightHexes().filter(visible.predicate), size, 0, 0, getHexOpacity)

    // 时间轴投影是基于 MapFact 的只读覆盖层。observation/fact 不递增
    // editor_revision，因此由每次 timeline/state-at 响应显式更新签名和缓存。
    if (mapState.mode !== "edit" && this._timelineProjection) {
      drawTimelineProjection(this._ctx, this._timelineProjection, {
        hexSize: size,
        isVisible: (point) => visible.predicate({ hex_q: point.q, hex_r: point.r }),
      })
    }

    if (mapState.mode === "edit" && mapState.editorLayer === "location") {
      this._drawLocationEditAnchors(this._ctx, size)
    }

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
    this._recordRenderPerformance(frameStartedAt)
  },

  _drawWithOpacity(opacity, draw) {
    this._ctx.save()
    const currentAlpha = Number(this._ctx.globalAlpha)
    this._ctx.globalAlpha = (Number.isFinite(currentAlpha) ? currentAlpha : 1)
      * Math.max(0, Math.min(1, Number(opacity ?? 1)))
    draw()
    this._ctx.restore()
  },

  _recordRenderPerformance(frameStartedAt) {
    const finishedAt = performance.now()
    const duration = finishedAt - frameStartedAt
    recordMapFrame(duration, {
      nonEmpty: Boolean(
        (this._renderMetrics?.queued_hex_items || 0) > 0
        || (this._state?.tiles || []).length > 0
      ),
    })
    if (this._renderMetrics) this._renderMetrics.frame_duration_ms = duration
    if (!this._performanceMetrics) return
    if (this._performanceMetrics.first_draw_ms == null && this._firstDrawStartedAt != null) {
      this._performanceMetrics.first_draw_ms = finishedAt - this._firstDrawStartedAt
      this._firstDrawStartedAt = null
    }
    const frameIndex = (this._performanceMetrics.total_frames || 0) + 1
    this._performanceMetrics.total_frames = frameIndex
    if (frameIndex <= this._performanceMetrics.warmup_frames) return
    if (this._performanceFrameDurations.length >= 100) return
    this._performanceFrameDurations.push(duration)
    const sorted = [...this._performanceFrameDurations].sort((a, b) => a - b)
    const total = this._performanceFrameDurations.reduce((sum, value) => sum + value, 0)
    this._performanceMetrics.sampled_frames = this._performanceFrameDurations.length
    this._performanceMetrics.average_frame_ms = total / this._performanceFrameDurations.length
    this._performanceMetrics.p95_frame_ms = sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)]
  },

  _terrainRenderState(zoom = this._leaflet?.getZoom?.() ?? null) {
    const overlay = mapState.pendingTerrainOverlay
    const projectLayers = (layers) => (layers || []).map((layer) => {
      const effective = this._effectiveLayerNode({ terrainLayerId: layer.id, zoom })
      return {
        ...layer,
        visible: layer.visible !== false && effective.visible,
        opacity: effective.opacity,
        effective_locked: effective.locked,
      }
    })
    if (!overlay) {
      return {
        layers: projectLayers(this._state?.terrain_layers),
        regions: this._state?.terrain_regions || [],
        patches: this._state?.terrain_patches || [],
      }
    }
    return {
      layers: projectLayers(this._state?.terrain_layers),
      regions: [
        ...(this._state?.terrain_regions || []).filter((item) => item.layer_id !== overlay.layerId),
        ...(overlay.regions || []),
      ],
      patches: [
        ...(this._state?.terrain_patches || []).filter((item) => item.layer_id !== overlay.layerId),
        ...(overlay.patches || []),
      ],
    }
  },

  _effectiveTerritories() {
    const draft = mapState.pendingTerritoryChanges || { add: {}, remove: {} }
    const removed = new Set(Object.keys(draft.remove || {}))
    return [
      ...(this._state?.territories || []).filter((item) => !removed.has(item.id)),
      ...Object.values(draft.add || {}),
    ]
  },

  _layerInteractiveVisible(layerKey, workspaceLayer, zoom = this._leaflet?.getZoom?.() ?? null) {
    if (workspaceLayer && !this._isLayerEnabled(workspaceLayer)) return false
    const effective = this._effectiveLayerNode({ layerKey, zoom })
    return effective.interactiveVisible ?? effective.visible
  },

  _visibleTerritoryAt(q, r, zoom = this._leaflet?.getZoom?.() ?? null) {
    if (!this._layerInteractiveVisible("territory", "territories", zoom)) return null
    return this._effectiveTerritories().find(
      (item) => item.hex_q === q && item.hex_r === r,
    ) || null
  },

  _visibleTerrainPatchAt(
    q,
    r,
    terrainState = this._terrainRenderState(),
    zoom = this._leaflet?.getZoom?.() ?? null,
  ) {
    if (!this._layerInteractiveVisible("terrainOverlay", "terrain", zoom)) return null
    const visibleLayerIds = new Set(
      (terrainState.layers || []).filter((layer) => layer.visible !== false).map((layer) => layer.id),
    )
    return (terrainState.patches || []).find(
      (item) => item.hex_q === q && item.hex_r === r && visibleLayerIds.has(item.layer_id),
    ) || null
  },

  _visibleBindingAt(q, r, zoom = this._leaflet?.getZoom?.() ?? null) {
    if (!this._layerInteractiveVisible("location", "locations", zoom)) return null
    return this._bindingAt(q, r)
  },

  _visibleTileAt(q, r, zoom = this._leaflet?.getZoom?.() ?? null) {
    if (!this._layerInteractiveVisible("baseTerrain", "terrain", zoom)) return null
    return this._tileAt(q, r)
  },

  _drawLocationEditAnchors(ctx, size) {
    for (const layout of this._effectiveLocationLayouts()) {
      const [x, y] = hexToPixel(layout.center_hex_q, layout.center_hex_r, size)
      ctx.save()
      ctx.beginPath()
      ctx.arc(x, y, Math.max(8, size * 0.34), 0, Math.PI * 2)
      ctx.fillStyle = layout.locked ? "rgba(245,158,11,.9)" : "rgba(14,165,233,.92)"
      ctx.fill()
      ctx.strokeStyle = "#fff"
      ctx.lineWidth = 2
      ctx.stroke()
      ctx.fillStyle = "#fff"
      ctx.font = `${Math.max(10, size * 0.38)}px sans-serif`
      ctx.textAlign = "center"
      ctx.fillText(this._locationName(layout.location_entity_id), x, y - size * 0.62)
      ctx.restore()
    }
  },

  _effectiveLocationLayouts() {
    const persisted = this._state?.location_layouts || []
    const byId = new Map(persisted.map((layout) => [layout.location_entity_id, { ...layout }]))
    const bindingsByLocation = new Map()
    for (const binding of this._state?.location_bindings || []) {
      const items = bindingsByLocation.get(binding.location_entity_id) || []
      items.push(binding)
      bindingsByLocation.set(binding.location_entity_id, items)
    }
    for (const [locationId, bindings] of bindingsByLocation) {
      if (byId.has(locationId)) continue
      const centers = bindings.filter((binding) => binding.is_center)
      let anchor = centers.sort((a, b) => a.hex_q - b.hex_q || a.hex_r - b.hex_r || String(a.id).localeCompare(String(b.id)))[0]
      if (!anchor) {
        const meanQ = bindings.reduce((sum, item) => sum + item.hex_q, 0) / bindings.length
        const meanR = bindings.reduce((sum, item) => sum + item.hex_r, 0) / bindings.length
        anchor = [...bindings].sort((a, b) => {
          const adq = a.hex_q - meanQ
          const adr = a.hex_r - meanR
          const bdq = b.hex_q - meanQ
          const bdr = b.hex_r - meanR
          return Math.max(Math.abs(adq), Math.abs(adr), Math.abs(adq + adr))
            - Math.max(Math.abs(bdq), Math.abs(bdr), Math.abs(bdq + bdr))
            || a.hex_q - b.hex_q || a.hex_r - b.hex_r || String(a.id).localeCompare(String(b.id))
        })[0]
      }
      if (anchor) byId.set(locationId, {
        location_entity_id: locationId,
        center_hex_q: anchor.hex_q,
        center_hex_r: anchor.hex_r,
        occupy_radius: 1,
        locked: false,
        layout_source: "legacy_binding",
        layout_version: 1,
        sync_geo_setting: false,
        meta: {},
      })
    }
    for (const [locationId, pending] of Object.entries(mapState.pendingLocationLayouts || {})) {
      byId.set(locationId, { ...(byId.get(locationId) || {}), ...pending })
    }
    return [...byId.values()]
  },

  _syncCanvasSize() {
    if (!this._canvas) return
    const container = this._leaflet?.getContainer?.() || this._canvas.parentElement
    const width = Math.max(1, Math.round(container?.clientWidth || this._canvas.width || 1))
    const height = Math.max(1, Math.round(container?.clientHeight || this._canvas.height || 1))
    if (this._canvas.width !== width) this._canvas.width = width
    if (this._canvas.height !== height) this._canvas.height = height
  },

  /** 中心点标签用原生按钮，避免依赖 Leaflet marker 的事件冒泡边界。 */
  _createMapLabelButton({ className = "", opacity = 1, kind, id, q, r, label, drill, activate }) {
    const button = document.createElement("button")
    button.type = "button"
    button.className = ["map-center-label", className].filter(Boolean).join(" ")
    button.style.opacity = String(Number(opacity ?? 1))
    if (kind) button.dataset.kind = String(kind)
    if (id) button.dataset.id = String(id)
    if (Number.isFinite(q)) button.dataset.q = String(q)
    if (Number.isFinite(r)) button.dataset.r = String(r)

    const name = document.createElement("span")
    name.className = "map-center-name"
    name.textContent = label || "未命名地图对象"
    button.setAttribute("aria-label", name.textContent)
    button.appendChild(name)
    if (drill) {
      const indicator = document.createElement("span")
      indicator.className = ["map-center-drill", drill.hasDetail ? "has-detail" : ""]
        .filter(Boolean)
        .join(" ")
      indicator.setAttribute("aria-hidden", "true")
      indicator.textContent = drill.hasDetail ? "▾" : "·"
      button.appendChild(indicator)
    }
    for (const eventType of ["pointerdown", "mousedown", "touchstart", "dblclick", "contextmenu"]) {
      button.addEventListener(eventType, (event) => event.stopPropagation())
    }
    button.addEventListener("click", (event) => {
      event.stopPropagation()
      activate()
    })
    return button
  },

  _renderCenterLabels() {
    if (!this._leaflet || !this._state) return
    this._labelClusterItemsById.clear()
    // 清理旧标签
    this._leaflet.eachLayer((layer) => {
      if (layer._isMapLabel) this._leaflet.removeLayer(layer)
    })
    const locationLayer = this._effectiveLayerNode({
      layerKey: "location",
      zoom: this._leaflet.getZoom?.() ?? null,
    })
    if (mapState.mode === "edit") {
      markMapTelemetryCondition("labels_ready")
      return // 编辑模式不显示标签
    }

    const layoutItems = this._buildMapLabelItems(locationLayer)
    const container = this._leaflet.getContainer?.()
    startMapTelemetryStage("label_layout")
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
    endMapTelemetryStage("label_layout")
    for (const labelLayout of layout.labels) {
      const q = Number(labelLayout.q)
      const r = Number(labelLayout.r)
      if (!Number.isFinite(q) || !Number.isFinite(r)) continue
      const [x, y] = hexToPixel(q, r, this._state.map.hex_size || 30)
      const latlng = this._leafletApi.latLng(-y, x)
      const point = this._leaflet.latLngToContainerPoint(latlng)
      const label = labelLayout.title
      const sourceKind = labelLayout.sourceKind || "location"
      const sourceId = labelLayout.sourceId || labelLayout.targetEntityId
      const hasDetail = sourceKind === "location" && this._hasDetailMap(sourceId)
      const iconWidth = labelLayout.box.width
      const iconHeight = labelLayout.box.height
      const labelButton = this._createMapLabelButton({
        opacity: labelLayout.opacity,
        kind: sourceKind,
        id: sourceId,
        q,
        r,
        label: labelLayout.label || label,
        drill: sourceKind === "location" ? { hasDetail } : null,
        activate: () => {
          if (sourceKind === "location") {
            if (sourceId) this._onCenterClick(sourceId)
            return
          }
          this._openMapLayoutItem({ kind: sourceKind, id: sourceId, q, r })
        },
      })
      const icon = this._leafletApi.divIcon({
        className: `map-center-marker map-layout-marker is-${labelLayout.displayLevel} is-${esc(sourceKind)}`,
        html: labelButton,
        iconSize: [iconWidth, iconHeight],
        iconAnchor: [point.x - labelLayout.box.x, point.y - labelLayout.box.y],
      })
      const marker = this._leafletApi.marker(latlng, {
        icon,
        pane: "mapLabels",
        interactive: true,
        keyboard: false,
        title: labelLayout.title,
      })
      marker._isMapLabel = true
      marker.addTo(this._leaflet)
    }
    for (const cluster of layout.clusters) {
      this._labelClusterItemsById.set(cluster.id, cluster.items)
      const latlng = this._leaflet.containerPointToLatLng([
        cluster.box.x + cluster.box.width / 2,
        cluster.box.y + cluster.box.height / 2,
      ])
      const clusterButton = this._createMapLabelButton({
        className: "map-center-cluster",
        kind: "cluster",
        id: cluster.id,
        label: cluster.label,
        activate: () => this._showLocationCluster(cluster.id),
      })
      const icon = this._leafletApi.divIcon({
        className: "map-center-marker map-layout-marker is-cluster",
        html: clusterButton,
        iconSize: [cluster.box.width, cluster.box.height],
        iconAnchor: [cluster.box.width / 2, cluster.box.height / 2],
      })
      const marker = this._leafletApi.marker(latlng, {
        icon,
        pane: "mapLabels",
        interactive: true,
        keyboard: false,
        title: cluster.label,
      })
      marker._isMapLabel = true
      marker.addTo(this._leaflet)
    }
    markMapTelemetryCondition("labels_ready")
  },

  _buildMapLabelItems(locationLayer = this._effectiveLayerNode({ layerKey: "location" })) {
    if (!this._leaflet || !this._state) return []
    const size = this._state.map.hex_size || 30
    const anchorFor = (q, r) => {
      const [x, y] = hexToPixel(q, r, size)
      const point = this._leaflet.latLngToContainerPoint(this._leafletApi.latLng(-y, x))
      return { x: point.x, y: point.y }
    }
    const items = []
    if (this._isLayerEnabled("locations") && locationLayer.visible) {
      for (const [index, binding] of (this._state.location_bindings || [])
        .filter((item) => item.is_center)
        .entries()) {
        items.push({
          item_id: `location:${binding.location_entity_id || index}`,
          item_kind: "fact",
          fact_status: "confirmed",
          title: binding.label_override || this._locationName(binding.location_entity_id),
          object_type: "location",
          dynamic_type: "location",
          priority: this._hasDetailMap(binding.location_entity_id) ? 82 : 56,
          target_entity_id: binding.location_entity_id,
          source_kind: "location",
          source_id: binding.location_entity_id,
          q: binding.hex_q,
          r: binding.hex_r,
          opacity: locationLayer.opacity,
          anchor: anchorFor(binding.hex_q, binding.hex_r),
        })
      }
    }
    for (const marker of this._filteredMarkers()) {
      items.push({
        item_id: `marker:${marker.id}`,
        item_kind: "fact",
        fact_status: "confirmed",
        title: marker.label || ({ character: "人物", event: "事件", item: "物品" }[marker.marker_type] || "标记"),
        object_type: marker.marker_type || "event",
        dynamic_type: "location",
        priority: marker.marker_type === "event" ? 78 : 72,
        target_entity_id: marker.entity_id,
        source_kind: "marker",
        source_id: marker.id,
        q: marker.hex_q,
        r: marker.hex_r,
        anchor: anchorFor(marker.hex_q, marker.hex_r),
      })
    }
    for (const path of this._effectivePaths().filter((item) => this._pathVisible(item))) {
      const midpoint = representativePathPoint(path, this._pathState?.nodes || [])
      if (!midpoint) continue
      items.push({
        item_id: `path:${path.id || path.client_id}`,
        item_kind: "fact",
        fact_status: "confirmed",
        title: path.name || "未命名线路",
        object_type: "route",
        dynamic_type: "route_state",
        priority: 64,
        source_kind: "path",
        source_id: path.id || path.client_id,
        q: midpoint.q,
        r: midpoint.r,
        opacity: Number(path.opacity ?? 1),
        anchor: anchorFor(midpoint.q, midpoint.r),
      })
    }
    const territoryLayer = this._effectiveLayerNode({ layerKey: "territory" })
    if (territoryLayer.visible && this._isLayerEnabled("territories")) {
      const byFaction = new Map()
      for (const tile of this._state.territories || []) {
        if (!byFaction.has(tile.faction_entity_id)) byFaction.set(tile.faction_entity_id, [])
        byFaction.get(tile.faction_entity_id).push(tile)
      }
      for (const [factionId, tiles] of byFaction.entries()) {
        const q = tiles.reduce((sum, tile) => sum + Number(tile.hex_q), 0) / tiles.length
        const r = tiles.reduce((sum, tile) => sum + Number(tile.hex_r), 0) / tiles.length
        const entity = (this._allEntities || []).find((item) => item.id === factionId)
        items.push({
          item_id: `territory:${factionId}`,
          item_kind: "fact",
          fact_status: "confirmed",
          title: entity?.name || "势力范围",
          object_type: "organization",
          dynamic_type: "boundary",
          priority: 68,
          target_entity_id: factionId,
          source_kind: "territory",
          source_id: factionId,
          q,
          r,
          opacity: territoryLayer.opacity,
          anchor: anchorFor(q, r),
        })
      }
    }
    for (const stateItem of this._timelineProjection?.stateItems || []) {
      const point = timelineAnchorPoint(stateItem.spatial_anchor || stateItem.normalized_value)
      if (!point) continue
      const dynamicType = stateItem.dynamic_type || stateItem.normalized_value?.type || "status"
      if (!["crisis", "crisis_spread", "resource", "resource_control", "status", "boundary"].includes(dynamicType)) continue
      const id = stateItem.fact_id || stateItem.id || stateItem.dimension_key
      items.push({
        ...stateItem,
        item_id: `dynamic:${id}`,
        item_kind: "fact",
        fact_status: "confirmed",
        title: stateItem.target_name || ({ crisis: "危机", resource: "资源", boundary: "势力变化" }[dynamicType] || "状态变化"),
        object_type: dynamicType === "boundary" ? "organization" : dynamicType,
        dynamic_type: dynamicType,
        priority: dynamicType.startsWith("crisis") ? 96 : 74,
        source_kind: "dynamic",
        source_id: id,
        q: point.q,
        r: point.r,
        anchor: anchorFor(point.q, point.r),
      })
    }
    return items
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
    if (mapState.mode === "edit" && this._isCompactViewport()) return
    const [q, r] = this._eventToHex(e)
    if (q == null) return
    const cfg = this._state.map
    if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) return
    recordMapInput("click", { clickedHex: true })
    if (mapState.mode === "edit") {
      if (!this._guardEditorLayerWritable()) return
      if (mapState.editorLayer === "path") {
        if (this._suppressNextCanvasClick) {
          this._suppressNextCanvasClick = false
          return
        }
        this._handlePathSelectAtEvent(e)
      } else if (mapState.editorLayer === "terrainOverlay" && mapState.overlayTool === "bucket") {
        this._handleOverlayBucket(q, r)
      } else if (mapState.editorLayer === "baseTerrain" && mapState.activeTool === "bucket") {
        this._handleBucketClick(q, r)
      } else if (mapState.editorLayer === "marker") {
        if (this._suppressNextCanvasClick) {
          this._suppressNextCanvasClick = false
          return
        }
        const marker = this._markerAt(q, r)
        if (marker) this._showMarkerEditor(marker)
        else this._handleMarkerClick(q, r)
      } else if (mapState.editorLayer === "territory" && !this._dragMoved) {
        this._handleTerritoryEdit(q, r)
      } else if (!this._dragMoved) {
        this._handleDragDraw(q, r)
      }
      this._redraw()
    } else {
      this._handleBrowseClick(q, r)
      this._scheduleRedraw()
    }
  },

  _handleBrowseClick(q, r) {
    setSelectedHex(q, r)
    mapState.selectedMapObject = this._typedSelectionAt(q, r)
    this._updateDetailPanel(q, r)
    const eventMarker = this._markerAt(q, r, (marker) => marker.marker_type === "event")
    if (eventMarker && eventMarker.start_scene_id) {
      this._notifySceneChanged(eventMarker.start_scene_id)
      return
    }
    const tile = this._visibleTileAt(q, r)
    const binding = this._visibleBindingAt(q, r)
    if (binding) {
      const name = this._locationName(binding.location_entity_id)
      toast(`地点：${name}${binding.is_center ? "（中心）" : ""}`, "info")
    } else if (tile) {
      toast(`地形：${tile.terrain_type}`, "info")
    }
  },

  _typedSelectionAt(q, r) {
    const marker = this._markerAt(q, r)
    if (marker) return { kind: "marker", id: marker.id, entityId: marker.entity_id, q, r }
    const binding = this._visibleBindingAt(q, r)
    if (binding) return { kind: "location", id: binding.id, entityId: binding.location_entity_id, q, r }
    const path = hitTestPath(
      this._effectivePaths().filter((item) => this._pathVisible(item)),
      this._pathState?.nodes || [],
      q,
      r,
      0.45,
      this._pathGeometryCache,
    )
    if (path) return { kind: "path", id: path.id, data: path, q, r }
    const territory = this._visibleTerritoryAt(q, r)
    if (territory) return { kind: "territory", id: territory.id, entityId: territory.faction_entity_id, q, r }
    const patch = this._visibleTerrainPatchAt(q, r)
    if (patch) return { kind: "terrain", id: patch.id, layerId: patch.layer_id, q, r }
    const tile = this._visibleTileAt(q, r)
    if (tile) return { kind: "baseTerrain", id: tile.id, q, r }
    return null
  },

  _handleBucketClick(q, r) {
    const before = this._snapshotActiveDraft()
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
    const after = this._snapshotActiveDraft()
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      mapEditingSession.recordCommand("baseTerrain", { kind: "draft", before, after })
      this._notifyEditingChanged()
    }
  },

  _sceneNav(direction) {
    const scenes = mapState.sceneList
    if (!scenes.length) return
    const currentIdx = scenes.findIndex((s) => s.id === mapState.currentSceneId)
    const newIdx = Math.max(0, Math.min(scenes.length - 1, currentIdx + direction))
    const scene = scenes[newIdx]
    if (scene) {
      this._notifySceneChanged(scene.id)
    }
  },

  _showScenePicker() {
    const scenes = mapState.sceneList
    if (!scenes.length) return
    const options = scenes.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join("")
    const formHtml = `<div class="form-group"><label>选择场景</label><select class="form-select" id="map-scene-pick-select">${options}</select></div>`
    showModalHtml("场景时间轴", formHtml, [{
      text: "跳转", class: "btn-primary", handler: async () => {
        const sel = document.getElementById("map-scene-pick-select")
        if (!sel?.value) return false
        try {
          const changed = await this._notifySceneChanged(sel.value)
          if (changed === false) return false
          closeModal()
          return true
        } catch (err) {
          toast(`切换场景失败：${err.message}`, "error")
          return false
        }
      },
    }])
  },

  _clearScene() {
    this._notifySceneChanged(null)
  },

  async _notifySceneChanged(sceneId) {
    const callback = this._mountContext?.onSceneChange
    if (typeof callback === "function") return callback(sceneId)
    setCurrentScene(sceneId)
    return this._reloadWithScene()
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
    this._bindSceneEvents()
  },

  _bindSceneEvents() {
  },

  _handleMarkerClick(q, r) {
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
    const created = {
      id: crypto.randomUUID(),
      map_id: this._state.map.id,
      novel_id: state.currentProjectId,
      offset_x: 0,
      offset_y: 0,
      style_json: {},
      start_scene_id: null,
      start_scene_index: null,
      end_scene_id: null,
      end_scene_index: null,
      ...payload,
      __draft: true,
    }
    this._state.markers = [...(this._state.markers || []), created]
    mapEditingSession.recordCommand("marker", { kind: "markerCreate", marker: { ...created } })
    this._rebuildPendingMarkerChanges()
    this._rebuildIndexes()
    this._notifyEditingChanged()
    toast("标记已加入草稿", "info")
    this._redraw()
  },

  _showMarkerEditor(marker) {
    const form = `<div class="form-group"><label>标记名称</label><input id="map-marker-edit-label" class="form-input" value="${esc(marker.label || "")}" /></div><label class="map-checkbox"><input id="map-marker-edit-visible" type="checkbox" ${marker.visible !== false ? "checked" : ""}/> 显示</label>`
    showModalHtml("编辑标记", form, [
      {
        text: "删除",
        class: "btn-danger",
        handler: () => {
          const deleted = { ...marker }
          this._state.markers = (this._state.markers || []).filter((item) => item.id !== marker.id)
          mapEditingSession.recordCommand("marker", { kind: "markerDelete", marker: deleted })
          this._rebuildPendingMarkerChanges()
          this._rebuildIndexes()
          this._notifyEditingChanged()
          closeModal()
          this._redraw()
        },
      },
      {
        text: "保存",
        class: "btn-primary",
        handler: () => {
          const before = { ...marker }
          const updated = {
            label: document.getElementById("map-marker-edit-label")?.value?.trim() || null,
            visible: Boolean(document.getElementById("map-marker-edit-visible")?.checked),
          }
          Object.assign(marker, updated)
          mapEditingSession.recordCommand("marker", {
            kind: "marker",
            markerId: marker.id,
            before,
            after: { ...marker },
          })
          this._rebuildPendingMarkerChanges()
          this._rebuildIndexes()
          this._notifyEditingChanged()
          closeModal()
          this._redraw()
        },
      },
    ])
  },

  _handleCanvasMouseMove(e) {
    if (!this._canvas || !this._state || !this._leaflet) return
    if (mapState.mode === "edit" && this._isCompactViewport()) return
    recordMapInput(
      e.pointerType === "touch"
        ? "touch"
        : Number(e.buttons) > 0 ? "drag" : "pointermove",
    )
    if (mapState.mode === "edit" && mapState.editorLayer === "path") {
      if (this._pathPointerSamples || this._dragPathNode) {
        this._handlePathPointerMove(e)
        return
      }
    }
    const [q, r] = this._eventToHex(e)
    if (q == null) {
      clearHoveredHex()
      this._scheduleRedraw()
      return
    }
    const cfg = this._state.map
    if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) {
      if ((this._dragLocationId || this._dragMarkerId || mapState.dragDrawing) && !this._dragOutOfBoundsNotified) {
        this._dragOutOfBoundsNotified = true
        toast("已到地图边界，越界位置不会保存", "warning")
      }
      clearHoveredHex()
      this._scheduleRedraw()
      return
    }
    setHoveredHex(q, r)
    if (mapState.mode === "edit") {
      if (this._dragLocationId) {
        const current = this._effectiveLocationLayouts().find(
          (layout) => layout.location_entity_id === this._dragLocationId,
        )
        if (current && !current.locked) {
          mapState.pendingLocationLayouts[this._dragLocationId] = {
            ...current,
            center_hex_q: q,
            center_hex_r: r,
            layout_source: "user_drag",
          }
          this._dragMoved = true
          this._notifyEditingChanged()
        }
        this._scheduleRedraw()
        return
      }
      if (this._dragMarkerId) {
        const marker = (this._state.markers || []).find((item) => item.id === this._dragMarkerId)
        if (marker) {
          marker.hex_q = q
          marker.hex_r = r
          this._dragMoved = true
          this._renderSubsetCache.clear()
        }
        this._scheduleRedraw()
        return
      }
      if (mapState.dragDrawing) this._handleDragDraw(q, r)
      this._scheduleRedraw()
      return
    }
    // 浏览模式：debounce 300ms 后显示 tooltip
    if (this._tooltipDebounceTimer) clearTimeout(this._tooltipDebounceTimer)
    this._tooltipDebounceTimer = setTimeout(() => {
      this._showTooltip(q, r)
    }, 300)
    this._scheduleRedraw()
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
    this._scheduleRedraw()
  },

  _handleCanvasMouseDown(e) {
    if (!this._canvas || !this._state || mapState.mode !== "edit") return
    if (this._isCompactViewport()) return
    if (!this._guardEditorLayerWritable()) return
    if (mapState.editorLayer === "path") {
      this._handlePathPointerDown(e)
      return
    }
    const [q, r] = this._eventToHex(e)
    if (q == null) return
    if (mapState.editorLayer === "location" && mapState.activeTool === "locationMove") {
      const layout = this._effectiveLocationLayouts().find(
        (item) => item.center_hex_q === q && item.center_hex_r === r,
      )
      if (!layout) return
      if (layout.locked) {
        toast("该地点已锁定，请先解锁", "warning")
        return
      }
      if (this._hasPendingBindingEdits(layout.location_entity_id)) {
        toast("该地点有未应用的范围修改，请先应用或撤销后再移动", "warning")
        return
      }
      this._dragLocationId = layout.location_entity_id
      this._pointerStartSnapshot = { ...layout }
      this._pointerStartHadPending = Object.prototype.hasOwnProperty.call(
        mapState.pendingLocationLayouts,
        layout.location_entity_id,
      )
      this._dragMoved = false
      this._dragOutOfBoundsNotified = false
      this._canvas.setPointerCapture?.(e.pointerId)
      this._leaflet.dragging?.disable?.()
      e.preventDefault?.()
      return
    }
    if (mapState.editorLayer === "marker") {
      const marker = this._markerAt(q, r)
      if (marker) {
        this._dragMarkerId = marker.id
        this._pointerStartSnapshot = { ...marker }
        this._dragMoved = false
        this._dragOutOfBoundsNotified = false
        this._canvas.setPointerCapture?.(e.pointerId)
        this._leaflet.dragging?.disable?.()
        e.preventDefault?.()
        return
      }
      return
    }
    if (
      (mapState.editorLayer === "baseTerrain" && mapState.activeTool === "bucket")
      || (mapState.editorLayer === "terrainOverlay" && mapState.overlayTool === "bucket")
    ) return
    this._dragMoved = false
    this._dragOutOfBoundsNotified = false
    this._pointerStartSnapshot = this._snapshotActiveDraft()
    startDragDraw()
    this._handleDragDraw(q, r)
    this._canvas.setPointerCapture?.(e.pointerId)
    this._leaflet.dragging?.disable?.()
    e.preventDefault?.()
    this._redraw()
  },

  async _handleCanvasMouseUp(e = {}) {
    if (this._pathPointerSamples || this._dragPathNode) {
      this._handlePathPointerUp(e)
      return
    }
    if (this._dragLocationId) {
      const locationId = this._dragLocationId
      const before = this._pointerStartSnapshot
      const after = mapState.pendingLocationLayouts[locationId]
      if (e.type === "pointercancel") {
        if (this._pointerStartHadPending && before) {
          mapState.pendingLocationLayouts[locationId] = { ...before }
        } else {
          delete mapState.pendingLocationLayouts[locationId]
        }
      } else if (before && after && (before.center_hex_q !== after.center_hex_q || before.center_hex_r !== after.center_hex_r)) {
        mapEditingSession.recordCommand("location", { kind: "location", locationId, before, after: { ...after } })
      }
      this._dragLocationId = null
      this._pointerStartSnapshot = null
      this._pointerStartHadPending = false
      this._canvas?.releasePointerCapture?.(e.pointerId)
      this._leaflet?.dragging?.enable?.()
      if (e.type === "pointercancel") {
        this._notifyEditingChanged()
        this._redraw()
      }
      setTimeout(() => { this._dragMoved = false }, 0)
      return
    }
    if (this._dragMarkerId) {
      const markerId = this._dragMarkerId
      const marker = (this._state?.markers || []).find((item) => item.id === markerId)
      const before = this._pointerStartSnapshot
      this._dragMarkerId = null
      this._pointerStartSnapshot = null
      this._canvas?.releasePointerCapture?.(e.pointerId)
      this._leaflet?.dragging?.enable?.()
      if (e.type === "pointercancel" && marker && before) Object.assign(marker, before)
      const markerMoved = e.type !== "pointercancel" && Boolean(
        marker
        && before
        && (marker.hex_q !== before.hex_q || marker.hex_r !== before.hex_r),
      )
      this._suppressNextCanvasClick = markerMoved
      if (this._suppressNextCanvasClick) {
        setTimeout(() => { this._suppressNextCanvasClick = false }, 250)
      }
      if (markerMoved) {
        mapEditingSession.recordCommand("marker", {
          kind: "marker",
          markerId,
          before,
          after: { ...marker },
        })
        this._rebuildPendingMarkerChanges()
        this._notifyEditingChanged()
      }
      this._rebuildPendingMarkerChanges()
      this._rebuildIndexes()
      this._redraw()
      setTimeout(() => { this._dragMoved = false }, 0)
      return
    }
    if (!mapState.dragDrawing) return
    endDragDraw()
    if (e.type === "pointercancel") {
      this._restoreActiveDraft(this._pointerStartSnapshot)
      this._pointerStartSnapshot = null
      this._canvas?.releasePointerCapture?.(e.pointerId)
      this._leaflet?.dragging?.enable?.()
      this._notifyEditingChanged()
      this._redraw()
      setTimeout(() => { this._dragMoved = false }, 0)
      return
    }
    const after = this._snapshotActiveDraft()
    if (JSON.stringify(this._pointerStartSnapshot) !== JSON.stringify(after)) {
      mapEditingSession.recordCommand(mapState.editorLayer, {
        kind: "draft",
        before: this._pointerStartSnapshot,
        after,
      })
      this._notifyEditingChanged()
    }
    this._pointerStartSnapshot = null
    this._canvas?.releasePointerCapture?.(e.pointerId)
    this._leaflet?.dragging?.enable?.()
    // click 事件会在 mouseup 后触发，保留 _dragMoved 到 click 判断完成
    setTimeout(() => { this._dragMoved = false }, 0)
  },

  _handleDragDraw(q, r) {
    if (!this._state) return
    const cfg = this._state.map
    if (q < 0 || q >= cfg.grid_width || r < 0 || r >= cfg.grid_height) return
    if (!recordDragHex(q, r)) return
    this._dragMoved = true
    if (["baseTerrain", "none"].includes(mapState.editorLayer) && mapState.activeTool === "brush") {
      stageTerrainChange(q, r, mapState.selectedTerrain)
      updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
    } else if (["location", "none"].includes(mapState.editorLayer) && mapState.activeTool === "bind") {
      const entityId = mapState.selectedLocationEntityId
      if (!entityId) return
      const isCenter = !!mapState.bindCenterMode
      this._stageBindingEdit(entityId, q, r, isCenter)
      updateBindingPendingCount(Object.keys(mapState.pendingBindings).length)
    } else if (mapState.editorLayer === "terrainOverlay") {
      this._stageOverlayBrush(q, r)
    } else if (mapState.editorLayer === "territory") {
      this._handleTerritoryEdit(q, r)
    }
    this._renderSubsetCache.clear()
  },

  _stageBindingEdit(entityId, q, r, isCenter) {
    if (isCenter) {
      if (this._hasPendingBindingEdits(entityId)) {
        toast("该地点有未应用的范围修改，请先应用或撤销后再设置中心", "warning")
        return
      }
      const current = this._effectiveLocationLayouts().find(
        (layout) => layout.location_entity_id === entityId,
      ) || {
        location_entity_id: entityId,
        occupy_radius: 1,
        locked: false,
        layout_version: 1,
        sync_geo_setting: false,
        meta: {},
      }
      mapState.pendingLocationLayouts[entityId] = {
        ...current,
        center_hex_q: q,
        center_hex_r: r,
        layout_source: "binding_center_edit",
      }
      this._notifyEditingChanged()
      return
    }
    if (mapState.pendingLocationLayouts[entityId]) {
      toast("该地点有未应用的位置修改，请先应用或撤销后再编辑范围", "warning")
      return
    }
    const key = `${q},${r}`
    const pending = mapState.pendingBindings[key]
    if (pending?.location_entity_id === entityId) {
      delete mapState.pendingBindings[key]
      this._notifyEditingChanged()
      return
    }
    const persisted = (this._state?.location_bindings || []).find((binding) => (
      binding.location_entity_id === entityId
      && binding.hex_q === q
      && binding.hex_r === r
    ))
    if (persisted?.is_center) {
      toast("中心格不能从范围中擦除，请改用“移动地点”调整中心", "warning")
      return
    }
    mapState.pendingBindings[key] = persisted
      ? {
          location_entity_id: entityId,
          hex_q: q,
          hex_r: r,
          is_center: false,
          operation: "delete",
          binding_id: persisted.id,
        }
      : {
          location_entity_id: entityId,
          hex_q: q,
          hex_r: r,
          is_center: false,
          operation: "add",
        }
    this._notifyEditingChanged()
  },

  _hasPendingBindingEdits(entityId) {
    return Object.values(mapState.pendingBindings || []).some(
      (binding) => binding.location_entity_id === entityId,
    )
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

  _eventToAxial(e) {
    if (!this._canvas || !this._leaflet || !this._state) return [null, null]
    const rect = this._canvas.getBoundingClientRect()
    const origin = this._leaflet.latLngToContainerPoint([0, 0])
    const scale = Math.pow(2, this._leaflet.getZoom())
    const x = (e.clientX - rect.left - origin.x) / scale
    const y = (e.clientY - rect.top - origin.y) / scale
    const size = this._state.map.hex_size || 30
    return [
      (2 / 3) * x / size,
      (-x / 3 + Math.sqrt(3) * y / 3) / size,
    ]
  },

  _pathAt(q, r) {
    return hitTestPath(
      this._effectivePaths().filter((path) => this._pathVisible(path)),
      this._pathState?.nodes || [],
      q,
      r,
      0.3,
      this._pathGeometryCache,
    )
  },

  _pathWritable(path, { allowArchived = false } = {}) {
    if (!path) return false
    if (path.status === "archived" && !allowArchived) {
      toast("已归档线路只读，请先恢复", "warning")
      return false
    }
    if (path.locked) {
      toast("该线路已锁定，请先解锁", "warning")
      return false
    }
    const layer = this._effectiveLayerNode({ pathLayerId: this._pathLayerId(path) })
    if (layer.locked) {
      toast("线路图层受自身或父组锁定，请先解锁", "warning")
      return false
    }
    return true
  },

  _handlePathSelectAtEvent(e) {
    const [q, r] = this._eventToAxial(e)
    if (q == null) return
    const path = this._pathAt(q, r)
    this._selectPath(path)
    mapState.selectedMapObject = path ? { kind: "path", id: mapState.selectedPathId, data: path } : null
    this._scheduleRedraw()
    this._rerenderEditor()
  },

  _selectPath(path) {
    mapState.selectedPathId = path?.id || path?.client_id || null
    mapState.selectedPathNodeIndex = null
    if (!path) return
    mapState.selectedPathLayerId = this._pathLayerId(path)
    mapState.selectedPathType = path.path_type || mapState.selectedPathType
  },

  _handlePathPointerDown(e) {
    const [q, r] = this._eventToAxial(e)
    const cfg = this._state.map
    if (q == null || q < 0 || q > cfg.grid_width - 1 || r < 0 || r > cfg.grid_height - 1) return
    this._dragOutOfBoundsNotified = false
    if (mapState.pathTool === "draw") {
      if (!mapState.selectedPathLayerId) {
        toast("请先新建或选择线路图层", "warning")
        return
      }
      this._pathPointerSamples = [{ q, r }]
      this._pointerStartSnapshot = this._snapshotActiveDraft()
    } else {
      const path = this._pathAt(q, r)
      if (!path) return
      this._selectPath(path)
      if (mapState.pathTool !== "nodes" || !this._pathWritable(path)) {
        this._scheduleRedraw()
        return
      }
      const nodes = pathNodesFor(path, this._pathState?.nodes || [])
      let closest = null
      nodes.forEach((node, index) => {
        const distance = Math.hypot(node.q - q, node.r - r)
        if (distance <= 0.35 && (!closest || distance < closest.distance)) {
          closest = { index, distance }
        }
      })
      if (!closest) return
      this._dragPathNode = { pathId: mapState.selectedPathId, index: closest.index }
      mapState.selectedPathNodeIndex = closest.index
      this._pointerStartSnapshot = this._snapshotActiveDraft()
    }
    this._canvas.setPointerCapture?.(e.pointerId)
    this._leaflet.dragging?.disable?.()
    e.preventDefault?.()
  },

  _handlePathPointerMove(e) {
    const [q, r] = this._eventToAxial(e)
    const cfg = this._state.map
    if (q == null || q < 0 || q > cfg.grid_width - 1 || r < 0 || r > cfg.grid_height - 1) {
      if (!this._dragOutOfBoundsNotified) {
        this._dragOutOfBoundsNotified = true
        toast("已到地图边界，越界节点不会保存", "warning")
      }
      return
    }
    if (this._pathPointerSamples) {
      const last = this._pathPointerSamples.at(-1)
      if (Math.hypot(last.q - q, last.r - r) >= 0.2) this._pathPointerSamples.push({ q, r })
      this._dragMoved = this._pathPointerSamples.length > 1
    } else if (this._dragPathNode) {
      const path = this._effectivePaths().find(
        (item) => (item.id || item.client_id) === this._dragPathNode.pathId,
      )
      if (!path) return
      const nodes = pathNodesFor(path, this._pathState?.nodes || [])
      nodes[this._dragPathNode.index] = { ...nodes[this._dragPathNode.index], q, r }
      this._stagePathUpdate(path, { nodes: this._normalizedPathNodes(nodes) })
      this._dragMoved = true
    }
    this._pathGeometryCache.clear()
    this._notifyEditingChanged()
    this._scheduleRedraw()
  },

  _normalizedPathNodes(nodes) {
    return (nodes || []).map((node, index) => ({
      q: Number(node.q),
      r: Number(node.r),
      sort_order: index,
      width_scale: Number(node.width_scale ?? 1),
      tension: Number(node.tension ?? 0.5),
      ...(node.segment_type ? { segment_type: node.segment_type } : {}),
    }))
  },

  _stagePathUpdate(path, data) {
    const id = path.id || path.client_id
    const existing = mapState.pendingPathChanges[id]
    if (existing?.operation === "create") {
      existing.data = { ...existing.data, ...data }
    } else {
      mapState.pendingPathChanges[id] = {
        operation: "update",
        id,
        data: { ...(existing?.data || {}), ...data },
      }
    }
  },

  _stageSelectedPathClassification({ layerId, pathType }) {
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === mapState.selectedPathId,
    )
    const layer = this._effectivePathLayers().find((item) => item.id === layerId)
    if (!path || !layer || !this._pathWritable(path)) return false
    const requestedProfile = MAP_PATH_PROFILES[pathType]
    const compatibleType = requestedProfile?.category === layer.category
      ? pathType
      : layer.category === "water" ? "river" : "major_road"
    const nodes = pathNodesFor(path, this._pathState?.nodes || [])
    const sanitizedNodes = nodes.map((node) => {
      const segmentProfile = MAP_PATH_PROFILES[node.segment_type]
      if (!node.segment_type || segmentProfile?.category === layer.category) return { ...node }
      const next = { ...node }
      delete next.segment_type
      return next
    })
    const nodesChanged = nodes.some(
      (node, index) => node.segment_type !== sanitizedNodes[index]?.segment_type,
    )
    const before = this._snapshotActiveDraft()
    mapState.selectedPathLayerId = layerId
    mapState.selectedPathType = compatibleType
    const data = {
      path_layer_id: layerId,
      path_type: compatibleType,
      ...(nodesChanged ? { nodes: this._normalizedPathNodes(sanitizedNodes) } : {}),
    }
    this._stagePathUpdate(path, data)
    const after = this._snapshotActiveDraft()
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      mapEditingSession.recordCommand("path", { kind: "draft", before, after })
      this._pathGeometryCache.clear()
      this._notifyEditingChanged()
    }
    return true
  },

  _handlePathPointerUp(e = {}) {
    const before = this._pointerStartSnapshot
    if (e.type === "pointercancel") {
      this._restoreActiveDraft(before)
      this._pathPointerSamples = null
      this._dragPathNode = null
      this._pointerStartSnapshot = null
      this._canvas?.releasePointerCapture?.(e.pointerId)
      this._leaflet?.dragging?.enable?.()
      this._dragMoved = false
      this._suppressNextCanvasClick = false
      this._pathGeometryCache.clear()
      this._notifyEditingChanged()
      this._scheduleRedraw()
      this._rerenderEditor()
      return
    }
    if (this._pathPointerSamples) {
      const simplified = simplifyPathToLimit(this._pathPointerSamples, MAP_PATH_NODE_LIMIT)
      if (simplified.overLimit) {
        toast(`线路节点仍超过 ${MAP_PATH_NODE_LIMIT} 个，请分段绘制`, "error")
      } else if (simplified.nodes.length >= 2) {
        const clientId = crypto.randomUUID()
        const profile = MAP_PATH_PROFILES[mapState.selectedPathType] || MAP_PATH_PROFILES.major_road
        mapState.pendingPathChanges[clientId] = {
          operation: "create",
          client_id: clientId,
          data: {
            name: `${profile.label} ${this._effectivePaths().length + 1}`,
            path_type: mapState.selectedPathType,
            path_layer_id: mapState.selectedPathLayerId,
            visible: true,
            locked: false,
            opacity: 1,
            nodes: this._normalizedPathNodes(simplified.nodes),
          },
        }
        mapState.selectedPathId = clientId
        if (simplified.tolerance > 0.08) toast("线路较长，已自动提高简化强度", "info")
      }
    }
    this._pathPointerSamples = null
    this._dragPathNode = null
    const after = this._snapshotActiveDraft()
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      mapEditingSession.recordCommand("path", { kind: "draft", before, after })
      this._notifyEditingChanged()
    }
    this._pointerStartSnapshot = null
    this._canvas?.releasePointerCapture?.(e.pointerId)
    this._leaflet?.dragging?.enable?.()
    this._suppressNextCanvasClick = this._dragMoved
    setTimeout(() => {
      this._dragMoved = false
      this._suppressNextCanvasClick = false
    }, 250)
    this._pathGeometryCache.clear()
    this._scheduleRedraw()
    this._rerenderEditor()
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
    const latlng = this._leafletApi.latLng(-y, x)
    if (this._tooltipPopup) {
      this._tooltipPopup.setLatLng(latlng).setContent(content)
    } else {
      this._tooltipPopup = this._leafletApi.popup({ closeButton: false, autoClose: false, className: "map-hex-tooltip" })
        .setLatLng(latlng)
        .setContent(content)
        .openOn(this._leaflet)
    }
  },

  _buildTooltipContent(q, r) {
    const binding = this._visibleBindingAt(q, r)
    const tile = this._visibleTileAt(q, r)
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
        html += `<div class="map-tooltip-sub">点击跳转到场景</div>`
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
    this._bindViewClick({
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
    this._bindViewClick({
      "map-back-list": () => this._backToList(),
      "map-settings": () => this._showSettingsModal(),
      "map-enter-edit": () => this._enterEdit(),
      "map-mobile-edit-handoff": () => toast("复杂地图编辑请在桌面端继续；移动端保留浏览与查看详情。", "info"),
      "map-exit-edit": () => this._exitEdit(),
      "map-breadcrumb": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._openMap(id)
      },
      "map-detail-drill": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (id) this._drillToLocation(id)
      },
      "map-detail-world-object": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (!id) return
        const callback = this._mountContext?.onOpenEntity
        if (typeof callback === "function") callback(id)
        else router.navigate("world", "objects")
      },
      "map-detail-focus-entity": (_e, t) => {
        const id = t.getAttribute("data-id")
        const callback = this._mountContext?.onFocusEntity
        if (id && typeof callback === "function") callback(id)
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
      "map-tool-locationMove": () => this._switchTool("locationMove"),
      "map-tool-marker": () => this._switchTool("marker"),
      "map-editor-layer": (_e, t) => this._switchEditorLayer(t.getAttribute("data-layer")),
      "map-undo": () => this._undo(),
      "map-redo": () => this._redo(),
      "map-apply": () => this._applyAllChanges({ onlyLayer: true }),
      "map-layer-undo": () => this._undoLayerTree(),
      "map-layer-redo": () => this._redoLayerTree(),
      "map-layer-apply": () => this._applyAllChanges({ onlyLayerTree: true }),
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
      "map-territory-mode": (_e, t) => this._setTerritoryMode(t.getAttribute("data-mode")),
      "map-location-lock": () => this._toggleSelectedLocationLock(),
      "map-overlay-layer-add": () => this._showOverlayLayerCreate(),
      "map-overlay-layer-edit": () => this._showOverlayLayerSettings(),
      "map-overlay-layer-delete": () => this._deleteOverlayLayer(),
      "map-overlay-tool": (_e, t) => this._setOverlayTool(t.getAttribute("data-tool")),
      "map-layer-toggle-visible": (_e, t) => this._toggleLayerNode(t.getAttribute("data-id"), "visible"),
      "map-layer-toggle-lock": (_e, t) => this._toggleLayerNode(t.getAttribute("data-id"), "locked"),
      "map-layer-collapse": (_e, t) => {
        const id = t.getAttribute("data-id")
        if (mapState.collapsedLayerNodeIds.has(id)) mapState.collapsedLayerNodeIds.delete(id)
        else mapState.collapsedLayerNodeIds.add(id)
        this._rerenderEditor()
      },
      "map-layer-move-up": (_e, t) => this._moveLayerNode(t.getAttribute("data-id"), -1),
      "map-layer-move-down": (_e, t) => this._moveLayerNode(t.getAttribute("data-id"), 1),
      "map-layer-settings": (_e, t) => this._showLayerNodeSettings(t.getAttribute("data-id")),
      "map-layer-isolate": (_e, t) => this._toggleLayerIsolation(t.getAttribute("data-id")),
      "map-layer-add-group": () => this._addLayerGroup(),
      "map-layer-delete-group": (_e, t) => this._deleteLayerGroup(t.getAttribute("data-id")),
      "map-path-layer-add": () => this._showPathLayerCreate(),
      "map-path-layer-delete": () => this._deleteSelectedPathLayer(),
      "map-path-tool": (_e, t) => this._setPathTool(t.getAttribute("data-tool")),
      "map-path-select": (_e, t) => {
        const pathId = t.getAttribute("data-id") || null
        const path = this._effectivePaths().find(
          (item) => (item.id || item.client_id) === pathId,
        )
        this._selectPath(path)
        this._rerenderEditor()
      },
      "map-path-archive": (_e, t) => this._togglePathArchive(t.getAttribute("data-id")),
      "map-path-endpoint-snap": (_e, t) => {
        const side = t.getAttribute("data-side")
        const select = document.getElementById(`map-path-${side}-location`)
        this._stageSelectedPathEndpoint(side, select?.value || null, true)
      },
      "map-path-resnap": (_e, t) => this._resnapPathEndpoints(t.getAttribute("data-id")),
      "map-path-node-action": (_e, t) => {
        this._editSelectedPathNode(t.getAttribute("data-node-action"))
      },
    })

    document.querySelectorAll("[data-layer-active-group]").forEach((select) => {
      select.addEventListener("change", () => {
        mapState.activeLayerChildIds = setLayerSelection({
          nodes: mapState.pendingLayerTree || this._layerTree?.nodes || [],
          selections: mapState.activeLayerChildIds,
          groupId: select.dataset.layerActiveGroup,
          childId: select.value,
          novelId: state.currentProjectId,
          mapId: this._state?.map?.id,
        })
        this._replaceLayerFocusInRoute(select.value)
        this._renderSubsetCache.clear()
        this._pathGeometryCache.clear()
        this._rerenderEditor()
      })
    })

    // 地形选择
    const terrainSelect = document.getElementById("map-terrain-select")
    terrainSelect?.addEventListener("change", () => {
      mapState.selectedTerrain = terrainSelect.value
    })
    const overlayLayer = document.getElementById("map-overlay-layer")
    overlayLayer?.addEventListener("change", () => {
      if (
        mapState.pendingTerrainOverlay
        && mapState.pendingTerrainOverlay.layerId !== overlayLayer.value
      ) {
        overlayLayer.value = mapState.selectedTerrainLayerId || ""
        toast("当前覆盖图层有未应用修改，请先应用或撤销后再切换", "warning")
        return
      }
      mapState.selectedTerrainLayerId = overlayLayer.value || null
      const selected = (this._state?.terrain_layers || []).find((item) => item.id === overlayLayer.value)
      if (selected) {
        mapState.selectedTerrainAssetKey = selected.terrain_asset_key
        mapState.selectedTerrainPreset = selected.meta?.preset_key || "standard"
      }
      this._redraw()
    })
    const overlayAsset = document.getElementById("map-overlay-asset")
    overlayAsset?.addEventListener("change", () => {
      const before = this._snapshotActiveDraft()
      mapState.selectedTerrainAssetKey = overlayAsset.value
      this._ensureOverlayDraft()
      const after = this._snapshotActiveDraft()
      mapEditingSession.recordCommand("terrainOverlay", { kind: "draft", before, after })
      this._notifyEditingChanged()
    })
    const overlayPreset = document.getElementById("map-overlay-preset")
    overlayPreset?.addEventListener("change", () => {
      const before = this._snapshotActiveDraft()
      mapState.selectedTerrainPreset = overlayPreset.value
      this._ensureOverlayDraft()
      const after = this._snapshotActiveDraft()
      mapEditingSession.recordCommand("terrainOverlay", { kind: "draft", before, after })
      this._notifyEditingChanged()
    })
    const overlayBrushSize = document.getElementById("map-overlay-brush-size")
    overlayBrushSize?.addEventListener("input", () => {
      mapState.overlayBrushSize = Number(overlayBrushSize.value) || 1
    })
    const pathLayerSelect = document.getElementById("map-path-layer")
    pathLayerSelect?.addEventListener("change", () => {
      const layerId = pathLayerSelect.value || null
      const layer = this._effectivePathLayers().find((item) => item.id === layerId)
      const profile = MAP_PATH_PROFILES[mapState.selectedPathType]
      const nextType = layer && profile?.category !== layer.category
        ? layer.category === "water" ? "river" : "major_road"
        : mapState.selectedPathType
      if (mapState.selectedPathId) {
        this._stageSelectedPathClassification({ layerId, pathType: nextType })
      } else {
        mapState.selectedPathLayerId = layerId
        mapState.selectedPathType = nextType
      }
      this._rerenderEditor()
    })
    const pathTypeSelect = document.getElementById("map-path-type")
    pathTypeSelect?.addEventListener("change", () => {
      const pathType = pathTypeSelect.value || "major_road"
      if (mapState.selectedPathId) {
        this._stageSelectedPathClassification({
          layerId: mapState.selectedPathLayerId,
          pathType,
        })
      } else {
        mapState.selectedPathType = pathType
      }
      this._rerenderEditor()
    })
    const pathNameInput = document.getElementById("map-path-name")
    pathNameInput?.addEventListener("change", () => {
      this._stageSelectedPathName(pathNameInput.value)
    })
    for (const side of ["start", "end"]) {
      const endpointSelect = document.getElementById(`map-path-${side}-location`)
      endpointSelect?.addEventListener("change", () => {
        this._stageSelectedPathEndpoint(side, endpointSelect.value || null)
      })
    }
    const nodeWidth = document.getElementById("map-path-node-width")
    nodeWidth?.addEventListener("change", () => {
      this._setSelectedPathNodeField("width_scale", Number(nodeWidth.value))
    })
    const nodeTension = document.getElementById("map-path-node-tension")
    nodeTension?.addEventListener("change", () => {
      this._setSelectedPathNodeField("tension", Number(nodeTension.value))
    })
    const nodeSegment = document.getElementById("map-path-node-segment")
    nodeSegment?.addEventListener("change", () => {
      this._setSelectedPathNodeField("segment_type", nodeSegment.value || null)
    })
    // 地点选择
    const bindSelect = document.getElementById("map-bind-select")
    bindSelect?.addEventListener("change", () => {
      mapState.selectedLocationEntityId = bindSelect.value || null
      this._rerenderEditor()
    })
    // 中心点绑定模式
    const bindCenterCheck = document.getElementById("map-bind-center")
    bindCenterCheck?.addEventListener("change", () => {
      mapState.bindCenterMode = bindCenterCheck.checked
    })

    const markerTypeSelect = document.getElementById("map-marker-type")
    markerTypeSelect?.addEventListener("change", () => {
      mapState.selectedMarkerType = markerTypeSelect.value
      mapState.selectedMarkerEntityId = null
      const markerEntitySelect = document.getElementById("map-marker-entity")
      if (markerEntitySelect) {
        markerEntitySelect.innerHTML = renderMarkerEntityOptions(
          this._allEntities || [],
          mapState.selectedMarkerType,
        )
        markerEntitySelect.value = ""
      }
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
        if (this._applyingEditorChanges || mapEditingSession.isApplying()) return
        if (e.shiftKey) this._redo()
        else this._undo()
      }
    }
    document.addEventListener("keydown", this._keyHandler)
    markMapTelemetryCondition("handlers_ready")
  },

  // ============================================================
  // 动作
  // ============================================================

  async _openMap(mapId) {
    const callback = this._mountContext?.onOpenMap
    if (typeof callback === "function") return callback(mapId)
    if (!this._guardDirty()) return false
    this._discardDrafts()
    const rootId = this._mountRootId || "map-root"
    const context = this._mountContext || {}
    this.unmount()
    this._mountRootId = rootId
    this._mountContext = context
    await this._loadMapState(mapId)
    await Promise.all([
      this._loadLocations(),
      this._loadScenes(),
      this._loadLayerTree(),
      this._loadPaths(),
    ])
    this._render(rootId)
    return true
  },

  _backToList() {
    const callback = this._mountContext?.onBackOverview
    if (typeof callback === "function") return callback()
    if (!this._guardDirty()) return false
    this._discardDrafts()
    this.unmount()
    this._render("map-root")
    return true
  },

  async _deleteMap(mapId) {
    const map = this._maps.find((m) => m.id === mapId)
    const name = map ? map.name : "该地图"
    let impact
    try {
      impact = await api.world.getMapArchiveImpact(mapId, state.currentProjectId)
    } catch (err) {
      toast(`读取归档影响失败：${err.message}`, "error")
      return
    }
    return confirmAction(
      `归档地图「${esc(name)}」及其 ${impact.map_count} 张地图？关联内容会保留，可在归档列表恢复。`,
      async () => {
        try {
          await api.world.archiveMap(mapId, state.currentProjectId)
          toast("地图子树已归档", "success")
          await this._loadMaps()
          this.unmount()
          this._render("map-root")
        } catch (err) {
          toast(`归档失败：${err.message}`, "error")
        }
      },
      "归档子树"
    )
  },

  _runMapBulkAction(action) {
    if (action !== "delete-maps") return
    const items = selectedItemsFrom(this._maps, getBulkSelection(this, "map-list"))
    if (!items.length) {
      toast("请先选择地图", "warning")
      return
    }
    return confirmAction(`归档选中的 ${items.length} 张地图及其子树？内容会保留并可恢复。`, async () => {
      const result = await runBulkAction(items, async (map) => {
        await api.world.archiveMap(map.id, state.currentProjectId)
      })
      toast(bulkResultMessage(result, "批量归档地图", (item) => item.name || item.id), result.failed.length ? "warning" : "success")
      clearBulkSelection(this, "map-list")
      await this._loadMaps()
      this._render("map-root")
    }, "归档")
  },

  async _enterEdit() {
    const lifecycleEpoch = this._lifecycleEpoch
    const mountContext = this._mountContext
    const mapId = this._state?.map?.id
    if (!mapId) return false
    if (this._isCompactViewport()) {
      toast("复杂地图编辑请在桌面端继续；移动端保留浏览与查看详情。", "info")
      return false
    }
    await Promise.all([
      this._loadLocations(),
      this._loadAllEntities(),
      this._loadLayerTree(),
      this._loadPaths(),
    ])
    if (
      !this._isLifecycleCurrent(lifecycleEpoch, mountContext)
      || this._state?.map?.id !== mapId
    ) return false
    this._teardownInteractiveSurface()
    mapState.mode = "edit"
    setEditorLayer("location")
    mapState.activeTool = "locationMove"
    mapState.selectedLocationEntityId ||= this._locations[0]?.id || null
    mapState.selectedTerrainLayerId ||= this._state?.terrain_layers?.[0]?.id || null
    const firstOverlay = (this._state?.terrain_layers || []).find(
      (item) => item.id === mapState.selectedTerrainLayerId,
    )
    if (firstOverlay) {
      mapState.selectedTerrainAssetKey = firstOverlay.terrain_asset_key
      mapState.selectedTerrainPreset = firstOverlay.meta?.preset_key || "standard"
    }
    this._notifyEditingChanged()
    this._render(this._mountRootId || "map-root")
    return true
  },

  _exitEdit() {
    if (!this._guardDirty()) return false
    this._discardDrafts()
    updatePendingCount(0)
    updateBindingPendingCount(0)
    this._teardownInteractiveSurface()
    mapState.mode = "browse"
    setEditorLayer("none")
    this._notifyEditingChanged()
    this._render(this._mountRootId || "map-root")
    return true
  },

  _isCompactViewport() {
    if (typeof window === "undefined") return false
    return window.matchMedia?.("(max-width: 760px)")?.matches
      ?? window.innerWidth <= 760
  },

  _switchTool(tool) {
    mapState.activeTool = tool
    toggleToolSections(tool)
  },

  _switchEditorLayer(layer) {
    const next = ["location", "baseTerrain", "terrainOverlay", "path", "marker", "territory"].includes(layer)
      ? layer
      : "location"
    setEditorLayer(next)
    const defaultTools = {
      location: "locationMove",
      baseTerrain: "brush",
      terrainOverlay: "overlay",
      path: "pathDraw",
      marker: "marker",
      territory: "territory",
    }
    mapState.activeTool = defaultTools[next]
    this._teardownInteractiveSurface()
    this._render(this._mountRootId || "map-root")
  },

  _editorLayerEffectiveState(layer = mapState.editorLayer) {
    const layerKey = {
      location: "location",
      baseTerrain: "baseTerrain",
      marker: `marker.${mapState.selectedMarkerType || "character"}`,
      territory: "territory",
    }[layer]
    if (layer === "terrainOverlay") {
      return mapState.selectedTerrainLayerId
        ? this._effectiveLayerNode({ terrainLayerId: mapState.selectedTerrainLayerId })
        : this._effectiveLayerNode({ layerKey: "terrainOverlay" })
    }
    if (layer === "path") {
      return mapState.selectedPathLayerId
        ? this._effectiveLayerNode({ pathLayerId: mapState.selectedPathLayerId })
        : this._effectiveLayerNode({ layerKey: "path" })
    }
    return layerKey
      ? this._effectiveLayerNode({ layerKey })
      : { visible: true, locked: false, opacity: 1 }
  },

  _guardEditorLayerWritable(layer = mapState.editorLayer) {
    if (this._applyingEditorChanges || mapEditingSession.isApplying()) {
      toast("地图编辑正在应用，请稍候", "warning")
      return false
    }
    const effective = this._editorLayerEffectiveState(layer)
    if (!effective.visible) {
      toast(`当前编辑图层${effective.sessionReason ? `处于「${effective.sessionReason}」` : "不可见"}，请先切换当前子层`, "warning")
      return false
    }
    if (!effective.locked) return true
    toast("当前图层受自身或父组锁定，请先在图层树中解锁", "warning")
    return false
  },

  _layerNodeIdentity(node) {
    return node?.id || node?.client_id || null
  },

  _ensureLayerTreeDraft() {
    if (mapState.pendingLayerTree) return mapState.pendingLayerTree
    mapState.pendingLayerTree = (this._layerTree?.nodes || []).map((node) => ({
      id: node.id,
      parent_id: node.parent_id || null,
      terrain_layer_id: node.terrain_layer_id || null,
      path_layer_id: node.path_layer_id || null,
      node_type: node.node_type,
      layer_key: node.layer_key || null,
      name: node.name,
      visible: node.visible !== false,
      locked: Boolean(node.locked),
      opacity: Number(node.opacity ?? 1),
      sort_order: Number(node.sort_order || 0),
      min_zoom: node.min_zoom ?? null,
      max_zoom: node.max_zoom ?? null,
      selection_mode: node.selection_mode || "normal",
      floor_level: node.floor_level ?? null,
      meta: node.meta || {},
      depth: node.depth || 1,
      effective_visible: node.effective_visible,
      effective_locked: node.effective_locked,
    }))
    return mapState.pendingLayerTree
  },

  _findLayerNode(nodeId) {
    return this._ensureLayerTreeDraft().find(
      (node) => this._layerNodeIdentity(node) === nodeId,
    )
  },

  _refreshLayerTreeDraft() {
    const nodes = this._ensureLayerTreeDraft()
    const children = new Map()
    for (const node of nodes) {
      const parent = node.parent_id || node.parent_client_id || null
      if (!children.has(parent)) children.set(parent, [])
      children.get(parent).push(node)
    }
    for (const siblings of children.values()) {
      siblings.sort((a, b) => a.sort_order - b.sort_order)
      siblings.forEach((node, index) => { node.sort_order = index })
    }
    const ordered = []
    const visit = (node, depth, inherited) => {
      const effectiveMin = node.min_zoom == null
        ? inherited.minZoom
        : inherited.minZoom == null ? node.min_zoom : Math.max(node.min_zoom, inherited.minZoom)
      const effectiveMax = node.max_zoom == null
        ? inherited.maxZoom
        : inherited.maxZoom == null ? node.max_zoom : Math.min(node.max_zoom, inherited.maxZoom)
      const zoomRangeVisible = effectiveMin == null || effectiveMax == null || effectiveMin <= effectiveMax
      node.depth = depth
      node.effective_visible = node.visible !== false && inherited.visible && zoomRangeVisible
      node.effective_locked = Boolean(node.locked || inherited.locked)
      node.effective_opacity = Number(node.opacity ?? 1) * inherited.opacity
      node.effective_min_zoom = effectiveMin
      node.effective_max_zoom = effectiveMax
      ordered.push(node)
      for (const child of children.get(this._layerNodeIdentity(node)) || []) {
        visit(child, depth + 1, {
          visible: node.effective_visible,
          locked: node.effective_locked,
          opacity: node.effective_opacity,
          minZoom: effectiveMin,
          maxZoom: effectiveMax,
        })
      }
    }
    for (const root of children.get(null) || []) {
      visit(root, 1, {
        visible: true,
        locked: false,
        opacity: 1,
        minZoom: null,
        maxZoom: null,
      })
    }
    mapState.pendingLayerTree = ordered
    mapState.activeLayerChildIds = resolveLayerSelections({
      nodes: ordered,
      novelId: state.currentProjectId,
      mapId: this._state?.map?.id,
      focusNodeId: this._mountContext?.focusLayerNodeId || null,
      previous: mapState.activeLayerChildIds,
    })
    this._notifyEditingChanged()
  },

  _recordLayerTreeChange(before) {
    mapEditingSession.recordCommand("layerTree", {
      kind: "layerTree",
      before,
      after: JSON.parse(JSON.stringify(mapState.pendingLayerTree)),
    })
  },

  _rerenderEditor() {
    const root = document.getElementById(this._mountRootId || "map-root")
    const center = this._leaflet?.getCenter?.()
    const zoom = this._leaflet?.getZoom?.()
    const viewport = Number.isFinite(center?.lat) && Number.isFinite(center?.lng) && Number.isFinite(zoom)
      ? { center, zoom }
      : null
    const panelScrollTop = root?.querySelector(".map-edit-panel")?.scrollTop ?? null
    const activeControl = root?.contains(document.activeElement) ? document.activeElement : null
    const focusedControl = activeControl ? {
      id: activeControl.id,
      tagName: activeControl.tagName,
      dataset: { ...activeControl.dataset },
      type: activeControl.type || "",
      name: activeControl.name || "",
      value: activeControl.value || "",
    } : null
    this._teardownInteractiveSurface()
    this._render(this._mountRootId || "map-root", viewport)
    const panel = root?.querySelector(".map-edit-panel")
    const datasetEntries = Object.entries(focusedControl?.dataset || {})
    const nextControl = focusedControl
      ? [...(root?.querySelectorAll(focusedControl.tagName) || [])].find((element) => (
        (focusedControl.id && element.id === focusedControl.id)
        || (datasetEntries.length && datasetEntries.every(([key, value]) => element.dataset[key] === value))
        || (!focusedControl.id
          && !datasetEntries.length
          && element.type === focusedControl.type
          && element.name === focusedControl.name
          && element.value === focusedControl.value)
      ))
      : null
    if (nextControl && !nextControl.disabled) nextControl.focus({ preventScroll: true })
    if (panel && panelScrollTop !== null) panel.scrollTop = panelScrollTop
  },

  _toggleLayerNode(nodeId, field) {
    const before = JSON.parse(JSON.stringify(this._ensureLayerTreeDraft()))
    const node = this._findLayerNode(nodeId)
    if (!node) return
    node[field] = !node[field]
    this._refreshLayerTreeDraft()
    this._recordLayerTreeChange(before)
    this._rerenderEditor()
  },

  _moveLayerNode(nodeId, direction) {
    const node = this._findLayerNode(nodeId)
    if (!node) return
    const parent = node.parent_id || node.parent_client_id || null
    const siblings = this._ensureLayerTreeDraft()
      .filter((item) => (item.parent_id || item.parent_client_id || null) === parent)
      .sort((a, b) => a.sort_order - b.sort_order)
    const index = siblings.indexOf(node)
    const target = siblings[index + direction]
    if (!target) return
    const before = JSON.parse(JSON.stringify(this._ensureLayerTreeDraft()))
    const currentOrder = node.sort_order
    node.sort_order = target.sort_order
    target.sort_order = currentOrder
    this._refreshLayerTreeDraft()
    this._recordLayerTreeChange(before)
    this._rerenderEditor()
  },

  _addLayerGroup() {
    const groups = this._ensureLayerTreeDraft().filter((node) => node.node_type === "group")
    const options = [`<option value="">顶层</option>`, ...groups.map((group) => (
      `<option value="${esc(this._layerNodeIdentity(group))}">${esc(group.name)}</option>`
    ))].join("")
    const form = `<div class="form-group"><label>分组名称</label><input class="form-input" id="map-layer-group-name" value="新分组" /></div><div class="form-group"><label>父分组</label><select class="form-select" id="map-layer-group-parent">${options}</select></div>`
    showModalHtml("新建图层分组", form, [{
      text: "创建",
      class: "btn-primary",
      handler: () => {
        const before = JSON.parse(JSON.stringify(this._ensureLayerTreeDraft()))
        const clientId = crypto.randomUUID()
        const parentIdentity = document.getElementById("map-layer-group-parent")?.value || null
        const parentNode = groups.find((node) => this._layerNodeIdentity(node) === parentIdentity)
        const siblings = this._ensureLayerTreeDraft().filter(
          (node) => (node.parent_id || node.parent_client_id || null) === parentIdentity,
        )
        this._ensureLayerTreeDraft().push({
          client_id: clientId,
          parent_id: parentNode?.id || null,
          parent_client_id: parentNode?.client_id || null,
          node_type: "group",
          layer_key: null,
          name: document.getElementById("map-layer-group-name")?.value?.trim() || "新分组",
          visible: true,
          locked: false,
          opacity: 1,
          sort_order: siblings.length,
          min_zoom: null,
          max_zoom: null,
          selection_mode: "normal",
          floor_level: null,
          meta: {},
        })
        this._refreshLayerTreeDraft()
        this._recordLayerTreeChange(before)
        closeModal()
        this._rerenderEditor()
      },
    }])
  },

  _deleteLayerGroup(nodeId) {
    const nodes = this._ensureLayerTreeDraft()
    const node = this._findLayerNode(nodeId)
    if (!node || node.layer_key || node.node_type !== "group") return
    const hasChildren = nodes.some(
      (item) => (item.parent_id || item.parent_client_id) === nodeId,
    )
    if (hasChildren) {
      toast("请先把子图层移出该分组", "warning")
      return
    }
    const before = JSON.parse(JSON.stringify(nodes))
    mapState.pendingLayerTree = nodes.filter(
      (item) => this._layerNodeIdentity(item) !== nodeId,
    )
    this._refreshLayerTreeDraft()
    this._recordLayerTreeChange(before)
    this._rerenderEditor()
  },

  _showLayerNodeSettings(nodeId) {
    const node = this._findLayerNode(nodeId)
    if (!node) return
    const nodes = this._ensureLayerTreeDraft()
    const descendants = new Set()
    if (node.node_type === "group") {
      const pending = [nodeId]
      while (pending.length) {
        const parentId = pending.pop()
        for (const child of nodes.filter(
          (item) => (item.parent_id || item.parent_client_id) === parentId,
        )) {
          const childId = this._layerNodeIdentity(child)
          if (!descendants.has(childId)) {
            descendants.add(childId)
            pending.push(childId)
          }
        }
      }
    }
    const groupOptions = [
      `<option value="">顶层</option>`,
      ...nodes.filter((item) => (
        item.node_type === "group"
        && this._layerNodeIdentity(item) !== nodeId
        && !descendants.has(this._layerNodeIdentity(item))
      ))
        .map((item) => {
          const id = this._layerNodeIdentity(item)
          const selected = (node.parent_id || node.parent_client_id) === id ? "selected" : ""
          return `<option value="${esc(id)}" ${selected}>${esc(item.name)}</option>`
        }),
    ].join("")
    const modeControl = node.node_type === "group"
      ? `<div class="form-group"><label>分组模式</label><select class="form-select" id="map-layer-node-selection-mode"><option value="normal" ${node.selection_mode === "normal" ? "selected" : ""}>普通</option><option value="exclusive" ${node.selection_mode === "exclusive" ? "selected" : ""}>独占子层</option><option value="floor" ${node.selection_mode === "floor" ? "selected" : ""}>楼层</option></select></div>`
      : ""
    const floorControl = `<div class="form-group"><label>楼层编号（父组为楼层模式时必填）</label><input class="form-input" id="map-layer-node-floor-level" type="number" min="-1000" max="1000" value="${node.floor_level ?? ""}" /></div>`
    const form = `<div class="form-group"><label>名称</label><input class="form-input" id="map-layer-node-name" value="${esc(node.name)}" /></div><div class="form-group"><label>父分组</label><select class="form-select" id="map-layer-node-parent">${groupOptions}</select></div>${modeControl}${floorControl}<div class="form-group"><label>透明度</label><input class="form-input" id="map-layer-node-opacity" type="number" min="0" max="1" step="0.05" value="${Number(node.opacity ?? 1)}" /></div><div class="form-group"><label>最小缩放（-3~3，可空）</label><input class="form-input" id="map-layer-node-min-zoom" type="number" min="-3" max="3" value="${node.min_zoom ?? ""}" /></div><div class="form-group"><label>最大缩放（-3~3，可空）</label><input class="form-input" id="map-layer-node-max-zoom" type="number" min="-3" max="3" value="${node.max_zoom ?? ""}" /></div>`
    showModalHtml("图层设置", form, [{
      text: "保存",
      class: "btn-primary",
      handler: () => {
        const before = JSON.parse(JSON.stringify(this._ensureLayerTreeDraft()))
        const parentIdentity = document.getElementById("map-layer-node-parent")?.value || null
        const parent = nodes.find((item) => this._layerNodeIdentity(item) === parentIdentity)
        const minRaw = document.getElementById("map-layer-node-min-zoom")?.value
        const maxRaw = document.getElementById("map-layer-node-max-zoom")?.value
        const minZoom = minRaw === "" ? null : Number(minRaw)
        const maxZoom = maxRaw === "" ? null : Number(maxRaw)
        if (minZoom != null && maxZoom != null && minZoom > maxZoom) {
          toast("最小缩放不能大于最大缩放", "warning")
          return false
        }
        node.name = document.getElementById("map-layer-node-name")?.value?.trim() || node.name
        node.opacity = Math.max(0, Math.min(1, Number(document.getElementById("map-layer-node-opacity")?.value ?? node.opacity)))
        node.min_zoom = minZoom
        node.max_zoom = maxZoom
        node.parent_id = parent?.id || null
        node.parent_client_id = parent?.client_id || null
        if (node.node_type === "group") {
          node.selection_mode = document.getElementById("map-layer-node-selection-mode")?.value || "normal"
          if (node.selection_mode !== "floor") {
            for (const child of nodes.filter((item) => (
              (item.parent_id || item.parent_client_id) === this._layerNodeIdentity(node)
            ))) child.floor_level = null
          }
        }
        const floorRaw = document.getElementById("map-layer-node-floor-level")?.value
        node.floor_level = parent?.selection_mode === "floor"
          ? (floorRaw === "" ? null : Number(floorRaw))
          : null
        if (parent?.selection_mode === "floor" && node.floor_level == null) {
          mapState.pendingLayerTree = before
          this._refreshLayerTreeDraft()
          toast("楼层组的直接子层必须填写楼层编号", "warning")
          return false
        }
        this._refreshLayerTreeDraft()
        this._recordLayerTreeChange(before)
        closeModal()
        this._rerenderEditor()
      },
    }])
  },

  _toggleLayerIsolation(nodeId) {
    mapState.isolateLayerNodeId = mapState.isolateLayerNodeId === nodeId ? null : nodeId
    this._renderSubsetCache.clear()
    this._pathGeometryCache.clear()
    this._rerenderEditor()
  },

  _replaceLayerFocusInRoute(nodeId) {
    const callback = this._mountContext?.onLayerFocusChange
    if (typeof callback === "function") {
      callback(nodeId || null)
      return
    }
    const raw = (window.location.hash || "").replace(/^#/, "")
    if (!raw) return
    const [path, query = ""] = raw.split("?")
    const params = new URLSearchParams(query)
    if (nodeId) params.set("focus_layer_node_id", nodeId)
    else params.delete("focus_layer_node_id")
    const next = `#${path}${params.toString() ? `?${params}` : ""}`
    window.history?.replaceState?.(window.history.state, "", next)
  },

  async _undoLayerTree() {
    const command = mapEditingSession.undo("layerTree")
    if (!command) {
      toast("无可撤销的图层结构操作", "info")
      return
    }
    await this._applyEditorCommand(command, "before")
  },

  async _redoLayerTree() {
    const command = mapEditingSession.redo("layerTree")
    if (!command) {
      toast("无可重做的图层结构操作", "info")
      return
    }
    await this._applyEditorCommand(command, "after")
  },

  _setPathTool(tool) {
    mapState.pathTool = ["draw", "select", "nodes"].includes(tool) ? tool : "draw"
    this._rerenderEditor()
  },

  _showPathLayerCreate() {
    if (this._effectiveLayerNode({ layerKey: "path" }).locked) {
      toast("线路组已锁定，请先解锁", "warning")
      return
    }
    const form = `<div class="form-group"><label>图层名称</label><input class="form-input" id="map-path-layer-name" value="交通线路" /></div><div class="form-group"><label>类别</label><select class="form-select" id="map-path-layer-category"><option value="transport">交通</option><option value="water">水系</option></select></div>`
    showModalHtml("新建线路图层", form, [{
      text: "创建",
      class: "btn-primary",
      handler: () => {
        const before = this._snapshotActiveDraft()
        const clientId = crypto.randomUUID()
        const leafClientId = crypto.randomUUID()
        const displayName = document.getElementById("map-path-layer-name")?.value?.trim() || "线路图层"
        const category = document.getElementById("map-path-layer-category")?.value === "water"
          ? "water"
          : "transport"
        mapState.pendingPathLayerChanges[clientId] = {
          operation: "create",
          client_id: clientId,
          leaf_client_id: leafClientId,
          data: { display_name: displayName, category, meta: {} },
        }
        mapState.selectedPathLayerId = clientId
        mapState.selectedPathType = category === "water" ? "river" : "major_road"
        mapEditingSession.recordCommand("path", {
          kind: "draft",
          before,
          after: this._snapshotActiveDraft(),
        })
        closeModal()
        this._notifyEditingChanged()
        this._rerenderEditor()
      },
    }])
  },

  _deleteSelectedPathLayer() {
    const layerId = mapState.selectedPathLayerId
    const layer = this._effectivePathLayers().find((item) => item.id === layerId)
    if (!layer) return
    const effective = this._effectiveLayerNode({ pathLayerId: layerId })
    if (effective.locked) {
      toast("线路图层受自身或父组锁定，请先解锁", "warning")
      return
    }
    const paths = this._effectivePaths().filter(
      (path) => this._pathLayerId(path) === layerId,
    )
    if (!layer.__draft && paths.length) {
      toast(`该图层仍包含 ${paths.length} 条线路（含已归档），无法删除`, "warning")
      return
    }
    const stage = () => {
      const before = this._snapshotActiveDraft()
      if (layer.__draft) {
        delete mapState.pendingPathLayerChanges[layerId]
        for (const [pathId, change] of Object.entries(mapState.pendingPathChanges || {})) {
          if (change.operation === "create" && change.data?.path_layer_id === layerId) {
            delete mapState.pendingPathChanges[pathId]
          }
        }
      } else {
        mapState.pendingPathLayerChanges[layerId] = {
          operation: "delete",
          id: layerId,
        }
      }
      if (paths.some((path) => (path.id || path.client_id) === mapState.selectedPathId)) {
        mapState.selectedPathId = null
        mapState.selectedPathNodeIndex = null
      }
      mapState.selectedPathLayerId = this._effectivePathLayers().find(
        (item) => item.id !== layerId && item.status !== "archived",
      )?.id || null
      mapEditingSession.recordCommand("path", {
        kind: "draft",
        before,
        after: this._snapshotActiveDraft(),
      })
      this._notifyEditingChanged()
      this._rerenderEditor()
    }
    confirmAction(
      `删除线路图层「${layer.name || layer.display_name || "未命名图层"}」？${layer.__draft && paths.length ? `同时放弃 ${paths.length} 条未保存线路。` : ""}`,
      stage,
      "删除线路图层",
    )
  },

  _stageSelectedPathEndpoint(side, entityId, snap = false) {
    if (!["start", "end"].includes(side)) return false
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === mapState.selectedPathId,
    )
    if (!path || !this._pathWritable(path)) return false
    const before = this._snapshotActiveDraft()
    const data = { [`${side}_location_entity_id`]: entityId || null }
    if (snap && entityId) {
      const anchor = this._locationAnchor(entityId)
      if (!anchor) {
        toast("该地点尚无可用地图锚点，无法吸附", "warning")
        return false
      }
      const nodes = pathNodesFor(path, this._pathState?.nodes || [])
      if (nodes.length < 2) return false
      const index = side === "start" ? 0 : nodes.length - 1
      nodes[index] = { ...nodes[index], q: anchor.q, r: anchor.r }
      data.nodes = this._normalizedPathNodes(nodes)
    }
    this._stagePathUpdate(path, data)
    mapEditingSession.recordCommand("path", {
      kind: "draft",
      before,
      after: this._snapshotActiveDraft(),
    })
    this._pathGeometryCache.clear()
    this._notifyEditingChanged()
    this._rerenderEditor()
    return true
  },

  _mutateSelectedPathNodes(mutator) {
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === mapState.selectedPathId,
    )
    if (!path || !this._pathWritable(path)) return false
    const nodes = pathNodesFor(path, this._pathState?.nodes || [])
      .map((node) => ({ ...node }))
    const index = Number(mapState.selectedPathNodeIndex)
    if (!Number.isInteger(index) || index < 0 || index >= nodes.length) return false
    const before = this._snapshotActiveDraft()
    const nextIndex = mutator(nodes, index)
    if (!Number.isInteger(nextIndex)) return false
    mapState.selectedPathNodeIndex = nextIndex
    this._stagePathUpdate(path, { nodes: this._normalizedPathNodes(nodes) })
    mapEditingSession.recordCommand("path", {
      kind: "draft",
      before,
      after: this._snapshotActiveDraft(),
    })
    this._pathGeometryCache.clear()
    this._notifyEditingChanged()
    this._rerenderEditor()
    return true
  },

  _editSelectedPathNode(action) {
    return this._mutateSelectedPathNodes((nodes, index) => {
      if (action === "delete") {
        if (nodes.length <= 2) return NaN
        nodes.splice(index, 1)
        return Math.min(index, nodes.length - 1)
      }
      if (action !== "insert" || nodes.length >= MAP_PATH_NODE_LIMIT) return NaN
      const otherIndex = index < nodes.length - 1 ? index + 1 : index - 1
      const other = nodes[otherIndex]
      const current = nodes[index]
      if (!other) return NaN
      const inserted = {
        q: (current.q + other.q) / 2,
        r: (current.r + other.r) / 2,
        width_scale: (Number(current.width_scale ?? 1) + Number(other.width_scale ?? 1)) / 2,
        tension: (Number(current.tension ?? 0.5) + Number(other.tension ?? 0.5)) / 2,
        segment_type: current.segment_type || other.segment_type || null,
      }
      const insertAt = index < nodes.length - 1 ? index + 1 : index
      nodes.splice(insertAt, 0, inserted)
      return insertAt
    })
  },

  _setSelectedPathNodeField(field, rawValue) {
    if (!["width_scale", "tension", "segment_type"].includes(field)) return false
    return this._mutateSelectedPathNodes((nodes, index) => {
      let value = rawValue
      if (field === "width_scale") value = Math.max(0.25, Math.min(4, Number(rawValue)))
      if (field === "tension") value = Math.max(0, Math.min(1, Number(rawValue)))
      nodes[index] = { ...nodes[index], [field]: value || (field === "segment_type" ? null : value) }
      return index
    })
  },

  async _togglePathArchive(pathId) {
    const path = this._effectivePaths().find((item) => (item.id || item.client_id) === pathId)
    if (!path) return
    if (path.__draft) {
      const before = this._snapshotActiveDraft()
      delete mapState.pendingPathChanges[pathId]
      mapState.selectedPathId = null
      mapEditingSession.recordCommand("path", {
        kind: "draft",
        before,
        after: this._snapshotActiveDraft(),
      })
      this._notifyEditingChanged()
      this._rerenderEditor()
      return
    }
    const pending = mapState.pendingPathChanges[pathId]
    if (["archive", "restore"].includes(pending?.operation)) {
      const before = this._snapshotActiveDraft()
      delete mapState.pendingPathChanges[pathId]
      mapEditingSession.recordCommand("path", {
        kind: "draft",
        before,
        after: this._snapshotActiveDraft(),
      })
      this._notifyEditingChanged()
      this._rerenderEditor()
      return
    }
    if (pending?.operation === "update") {
      toast("该线路有未保存编辑，请先应用或撤销后再归档", "warning")
      return
    }
    const persisted = (this._pathState?.paths || []).find((item) => item.id === pathId)
    if (!persisted || !this._pathWritable(persisted, { allowArchived: true })) return
    let impact = null
    if (persisted.status !== "archived" && api.world.getMapPathArchiveImpact) {
      try {
        impact = await api.world.getMapPathArchiveImpact(
          this._state.map.id,
          pathId,
          state.currentProjectId,
        )
      } catch (err) {
        toast(`读取线路归档影响失败：${err.message}`, "error")
        return
      }
    }
    const action = persisted.status === "archived" ? "restore" : "archive"
    const stage = () => {
      const before = this._snapshotActiveDraft()
      mapState.pendingPathChanges[pathId] = { operation: action, id: pathId }
      mapEditingSession.recordCommand("path", {
        kind: "draft",
        before,
        after: this._snapshotActiveDraft(),
      })
      this._notifyEditingChanged()
      this._rerenderEditor()
    }
    if (action === "restore") {
      stage()
      return
    }
    const references = Number(impact?.observation_count || 0)
      + Number(impact?.fact_count || 0)
      + Number(impact?.other_reference_count || 0)
    confirmAction(
      `归档「${esc(persisted.name || "未命名线路")}」？${references ? `它仍被 ${references} 条叙事记录引用，历史回放将保留只读高亮。` : ""}`,
      stage,
      "归档线路",
    )
  },

  _setOverlayTool(tool) {
    mapState.overlayTool = ["brush", "eraser", "bucket"].includes(tool) ? tool : "brush"
    document.querySelectorAll(".map-overlay-tool").forEach((button) => button.classList.remove("active"))
    document.querySelector(`[data-action="map-overlay-tool"][data-tool="${mapState.overlayTool}"]`)?.classList.add("active")
  },

  _setTerritoryMode(mode) {
    mapState.territoryEraseMode = mode === "erase"
    this._switchEditorLayer("territory")
  },

  _toggleSelectedLocationLock() {
    if (!this._guardEditorLayerWritable("location")) return
    const locationId = mapState.selectedLocationEntityId
    if (this._hasPendingBindingEdits(locationId)) {
      toast("该地点有未应用的范围修改，请先应用或撤销后再锁定", "warning")
      return
    }
    const current = this._effectiveLocationLayouts().find(
      (layout) => layout.location_entity_id === locationId,
    )
    if (!current) {
      toast("请先选择地图上的地点", "warning")
      return
    }
    const next = { ...current, locked: !current.locked, layout_source: "user_lock" }
    mapState.pendingLocationLayouts[locationId] = next
    mapEditingSession.recordCommand("location", {
      kind: "location",
      locationId,
      before: { ...current },
      after: { ...next },
    })
    this._notifyEditingChanged()
    this._redraw()
    this._rerenderEditor()
  },

  _stageSelectedPathName(rawName) {
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === mapState.selectedPathId,
    )
    if (!path || !this._pathWritable(path)) return false
    const name = String(rawName || "").trim()
    if (!name) {
      toast("线路名称不能为空", "warning")
      this._rerenderEditor()
      return false
    }
    if (name.length > 255) {
      toast("线路名称不能超过 255 个字符", "warning")
      this._rerenderEditor()
      return false
    }
    if (path.name === name) return true
    const before = this._snapshotActiveDraft()
    this._stagePathUpdate(path, { name })
    mapEditingSession.recordCommand("path", {
      kind: "draft",
      before,
      after: this._snapshotActiveDraft(),
    })
    this._notifyEditingChanged()
    this._rerenderEditor()
    return true
  },

  _resnapPathEndpoints(pathId = mapState.selectedPathId) {
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === pathId,
    )
    if (!path || !this._pathWritable(path)) return false
    const nodes = pathNodesFor(path, this._pathState?.nodes || [])
      .map((node) => ({ ...node }))
    if (nodes.length < 2) return false
    let changed = 0
    for (const [side, index] of [["start", 0], ["end", nodes.length - 1]]) {
      const entityId = path[`${side}_location_entity_id`]
      const anchor = this._locationAnchor(entityId)
      const status = this._pathEndpointStatus(path, side, nodes[index])
      if (!entityId || !anchor || !status?.drifted) continue
      nodes[index] = { ...nodes[index], q: anchor.q, r: anchor.r }
      changed += 1
    }
    if (!changed) {
      toast("这条线路没有需要重新吸附的端点", "info")
      return false
    }
    const before = this._snapshotActiveDraft()
    mapState.selectedPathId = pathId
    this._stagePathUpdate(path, { nodes: this._normalizedPathNodes(nodes) })
    mapEditingSession.recordCommand("path", {
      kind: "draft",
      before,
      after: this._snapshotActiveDraft(),
    })
    this._pathGeometryCache.clear()
    this._notifyEditingChanged()
    toast(`已重新吸附 ${changed} 个偏离端点`, "success")
    this._rerenderEditor()
    return true
  },

  async _undo() {
    const command = mapEditingSession.undo()
    if (command) {
      try {
        await this._applyEditorCommand(command, "before")
        toast("已撤销上一步操作", "info")
      } catch (err) {
        mapEditingSession.redo()
        toast(`撤销失败：${err.message}`, "error")
      }
      return
    }
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

  async _redo() {
    const command = mapEditingSession.redo()
    if (!command) {
      toast("无可重做的操作", "info")
      return
    }
    try {
      await this._applyEditorCommand(command, "after")
      toast("已重做上一步操作", "info")
    } catch (err) {
      mapEditingSession.undo()
      toast(`重做失败：${err.message}`, "error")
    }
  },

  async _applyEditorCommand(command, side) {
    const value = command?.[side]
    if (command?.kind === "location" && command.locationId && value) {
      mapState.pendingLocationLayouts[command.locationId] = { ...value }
    } else if (
      command?.kind === "draft"
      && Object.prototype.hasOwnProperty.call(command, side)
    ) {
      this._restoreActiveDraft(value)
    } else if (command?.kind === "layerTree" && value) {
      mapState.pendingLayerTree = JSON.parse(JSON.stringify(value))
      this._refreshLayerTreeDraft()
    } else if (command?.kind === "marker" && value && this._state) {
      const marker = (this._state.markers || []).find((item) => item.id === command.markerId)
      if (marker) {
        Object.assign(marker, value)
      }
    } else if (command?.kind === "markerCreate" && this._state) {
      if (side === "before") {
        this._state.markers = (this._state.markers || [])
          .filter((marker) => marker.id !== command.marker.id)
      } else {
        this._state.markers = [
          ...(this._state.markers || []),
          { ...command.marker },
        ]
      }
    } else if (command?.kind === "markerDelete" && this._state) {
      if (side === "before") {
        this._state.markers = [
          ...(this._state.markers || []),
          { ...command.marker },
        ]
      } else {
        this._state.markers = (this._state.markers || [])
          .filter((marker) => marker.id !== command.marker.id)
      }
    }
    this._rebuildPendingMarkerChanges()
    this._rebuildIndexes()
    this._notifyEditingChanged()
    this._redraw()
  },

  _markerCreatePayload(marker) {
    const payload = {
      entity_id: marker.entity_id,
      marker_type: marker.marker_type,
      hex_q: marker.hex_q,
      hex_r: marker.hex_r,
      offset_x: marker.offset_x || 0,
      offset_y: marker.offset_y || 0,
      label: marker.label ?? null,
      style_json: marker.style_json || {},
      visible: marker.visible !== false,
    }
    if (marker.start_scene_id) payload.start_scene_id = marker.start_scene_id
    if (marker.start_scene_index != null) payload.start_scene_index = marker.start_scene_index
    if (marker.end_scene_id) payload.end_scene_id = marker.end_scene_id
    if (marker.end_scene_index != null) payload.end_scene_index = marker.end_scene_index
    return payload
  },

  _markerUpdatePayload(marker) {
    return {
      hex_q: marker.hex_q,
      hex_r: marker.hex_r,
      offset_x: marker.offset_x || 0,
      offset_y: marker.offset_y || 0,
      label: marker.label ?? null,
      style_json: marker.style_json || {},
      start_scene_id: marker.start_scene_id || null,
      start_scene_index: marker.start_scene_index ?? null,
      end_scene_id: marker.end_scene_id || null,
      end_scene_index: marker.end_scene_index ?? null,
      visible: marker.visible !== false,
    }
  },

  _rebuildPendingMarkerChanges() {
    const working = new Map((this._state?.markers || []).map((marker) => [marker.id, marker]))
    const changes = {}
    const ids = new Set([...this._markerBaselineById.keys(), ...working.keys()])
    for (const markerId of ids) {
      const baseline = this._markerBaselineById.get(markerId)
      const marker = working.get(markerId)
      if (!baseline && marker) {
        changes[markerId] = {
          operation: "create",
          client_id: markerId,
          data: this._markerCreatePayload(marker),
        }
      } else if (baseline && !marker) {
        changes[markerId] = { operation: "delete", id: markerId }
      } else if (baseline && marker) {
        const before = this._markerUpdatePayload(baseline)
        const after = this._markerUpdatePayload(marker)
        if (JSON.stringify(before) !== JSON.stringify(after)) {
          changes[markerId] = {
            operation: "update",
            id: markerId,
            data: after,
          }
        }
      }
    }
    mapState.pendingMarkerChanges = changes
  },

  _snapshotActiveDraft() {
    return mapEditingSession.snapshotActiveDraft()
  },

  _restoreActiveDraft(snapshot) {
    const restored = mapEditingSession.restoreActiveDraft(snapshot)
    if (restored.layer === "location") {
      updateBindingPendingCount(restored.bindingPendingCount)
    } else if (restored.layer === "baseTerrain") {
      updatePendingCount(restored.terrainPendingCount)
    } else if (restored.layer === "path") {
      this._pathGeometryCache.clear()
    }
  },

  _notifyEditingChanged() {
    this._renderSubsetCache.clear()
    updatePendingCount(mapEditingSession.draftChangeCount())
    const callback = this._mountContext?.onEditingChange
    if (typeof callback === "function") {
      callback({
        editing: mapState.mode === "edit",
        dirty: mapEditingSession.hasDraftChanges(),
        editorLayer: mapState.editorLayer,
      })
    }
  },

  canLeave() {
    return this._guardDirty()
  },

  selectInspectorObject(kind, item) {
    if (!["fact", "observation", "path"].includes(kind) || !item) return
    if (kind !== "path") this.clearPathFocus()
    mapState.selectedMapObject = {
      kind,
      id: item.item_id || item.id || item.event_id || null,
      data: item,
    }
  },

  setTimelineProjection(projection = null) {
    const nextSignature = projection ? timelineProjectionSignature(projection) : ""
    if (nextSignature === this._timelineProjectionSignature && projection) return false
    this._timelineProjection = projection
    this._timelineProjectionSignature = nextSignature
    this._renderSubsetCache.clear()
    this._labelsDirty = true
    this._scheduleRedraw()
    return true
  },

  setPresentationContext({ viewMode, lowMotion, focusEntityId } = {}) {
    // Presentation state is mutable within one mounted viewport. Keep the
    // lifecycle owner object stable: async editor/apply paths capture this
    // reference to distinguish an actual remount from an in-place UI change.
    const context = this._mountContext || (this._mountContext = {})
    if (viewMode) context.viewMode = viewMode
    if (lowMotion !== undefined) context.lowMotion = Boolean(lowMotion)
    if (focusEntityId !== undefined) context.focusEntityId = focusEntityId || null
    this._renderSubsetCache.clear()
    this._labelsDirty = true
    this._scheduleRedraw()
    return true
  },

  clearTimelineProjection() {
    return this.setTimelineProjection(null)
  },

  focusTimelineAnchor(anchor) {
    const point = timelineAnchorPoint(anchor)
    if (!point || !this._leaflet?.setView) return false
    const size = this._state?.map?.hex_size || 30
    const [x, y] = hexToPixel(point.q, point.r, size)
    const currentZoom = Number(this._leaflet.getZoom?.() ?? 0)
    this._leaflet.setView(this._leafletApi.latLng(-y, x), Math.max(1, currentZoom))
    return true
  },

  timelineEntityOptions() {
    return (this._allEntities || [])
      .filter((item) => item?.id && item?.name)
      .map((item) => ({ id: item.id, name: item.name, entityType: item.entity_type || null }))
      .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))
  },

  timelinePathOptions() {
    return this._effectivePaths()
      .filter((item) => item?.id && item?.name && item.status !== "archived")
      .map((item) => ({ id: item.id, name: item.name, pathType: item.path_type || null }))
      .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))
  },

  focusPath(pathId, layerNodeId = null) {
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === pathId,
    )
    if (!path) return false
    const nodes = mapState.pendingLayerTree || this._layerTree?.nodes || []
    const resolvedLayerNodeId = layerNodeId || this._layerNodeIdentity(
      nodes.find((node) => (
        node.path_layer_id === this._pathLayerId(path)
        || node.path_layer_client_id === this._pathLayerId(path)
      )),
    )
    this._mountContext = {
      ...(this._mountContext || {}),
      focusPathId: pathId,
      focusLayerNodeId: resolvedLayerNodeId || null,
    }
    mapState.activeLayerChildIds = resolveLayerSelections({
      nodes,
      novelId: state.currentProjectId,
      mapId: this._state?.map?.id,
      focusNodeId: this._mountContext.focusLayerNodeId,
      previous: mapState.activeLayerChildIds,
    })
    this._selectPath(path)
    mapState.selectedMapObject = { kind: "path", id: pathId, data: path }
    const point = representativePathPoint(path, this._pathState?.nodes || [])
    if (point && this._leaflet?.setView) {
      const [x, y] = hexToPixel(point.q, point.r, this._state?.map?.hex_size || 30)
      this._leaflet.setView(this._leafletApi.latLng(-y, x), Math.max(1, this._leaflet.getZoom?.() || 0))
    }
    this._renderSubsetCache.clear()
    this._scheduleRedraw()
    return true
  },

  clearPathFocus({ preserveSelection = false } = {}) {
    const focusedPathId = this._mountContext?.focusPathId || null
    this._mountContext = {
      ...(this._mountContext || {}),
      focusPathId: null,
      focusLayerNodeId: null,
    }
    if (!preserveSelection && (!focusedPathId || mapState.selectedPathId === focusedPathId)) {
      mapState.selectedPathId = null
      mapState.selectedPathNodeIndex = null
    }
    if (!preserveSelection && mapState.selectedMapObject?.kind === "path") {
      mapState.selectedMapObject = null
    }
    this._renderSubsetCache.clear()
    this._scheduleRedraw()
  },

  pathRevisionMismatch(anchor = {}) {
    if (!anchor?.path_id || anchor.path_revision == null) return false
    const path = this._effectivePaths().find(
      (item) => (item.id || item.client_id) === anchor.path_id,
    )
    return path?.content_revision != null
      && Number(path.content_revision) !== Number(anchor.path_revision)
  },

  _guardDirty() {
    if (this._applyingEditorChanges || mapEditingSession.isApplying()) {
      toast("地图编辑正在应用，请稍候再离开", "warning")
      return false
    }
    if (!mapEditingSession.hasDraftChanges() || this._ignoreDirtyGuard) return true
    if (typeof window.confirm !== "function") return false
    return window.confirm("地图仍有未保存修改，确定放弃并离开吗？")
  },

  _discardDrafts() {
    mapEditingSession.discardDrafts()
    if (this._state) {
      this._state.markers = [...this._markerBaselineById.values()].map(
        (marker) => ({ ...marker }),
      )
      this._rebuildIndexes()
    }
  },

  _finalLocationBindingItems() {
    const bindings = (this._state?.location_bindings || []).map((item) => ({ ...item }))
    const layouts = new Map(
      (this._state?.location_layouts || []).map((item) => [item.location_entity_id, item]),
    )
    for (const [locationId, next] of Object.entries(mapState.pendingLocationLayouts || {})) {
      const previous = layouts.get(locationId)
      if (!previous) continue
      const deltaQ = next.center_hex_q - previous.center_hex_q
      const deltaR = next.center_hex_r - previous.center_hex_r
      for (const binding of bindings) {
        if (binding.location_entity_id !== locationId) continue
        binding.hex_q += deltaQ
        binding.hex_r += deltaR
      }
    }
    for (const change of Object.values(mapState.pendingBindings || {})) {
      if (change.operation === "delete") {
        const index = bindings.findIndex((item) => item.id === change.binding_id)
        if (index >= 0) bindings.splice(index, 1)
        continue
      }
      if (change.is_center) {
        for (const binding of bindings) {
          if (binding.location_entity_id === change.location_entity_id) {
            binding.is_center = false
          }
        }
      }
      const existing = bindings.find((item) => (
        item.location_entity_id === change.location_entity_id
        && item.hex_q === change.hex_q
        && item.hex_r === change.hex_r
      ))
      if (existing) Object.assign(existing, change)
      else bindings.push({ ...change })
    }
    const grouped = new Map()
    for (const binding of bindings) {
      if (!grouped.has(binding.location_entity_id)) grouped.set(binding.location_entity_id, [])
      grouped.get(binding.location_entity_id).push({
        hex_q: binding.hex_q,
        hex_r: binding.hex_r,
        is_center: Boolean(binding.is_center),
        label_override: binding.label_override || null,
        style_override: binding.style_override || {},
      })
    }
    return [...grouped.entries()].map(([location_entity_id, hexes]) => ({
      location_entity_id,
      hexes,
    }))
  },

  _normalizedLocationLayouts(layouts) {
    return (layouts || []).map((layout) => ({
      location_entity_id: layout.location_entity_id,
      center_hex_q: layout.center_hex_q,
      center_hex_r: layout.center_hex_r,
      occupy_radius: layout.occupy_radius || 1,
      locked: Boolean(layout.locked),
      layout_source: layout.layout_source || "user_drag",
      layout_version: layout.layout_version || 1,
      sync_geo_setting: Boolean(layout.sync_geo_setting),
      meta: layout.meta || {},
    })).sort((a, b) => String(a.location_entity_id).localeCompare(String(b.location_entity_id)))
  },

  _normalizedLocationBindingItems(items) {
    return (items || []).map((item) => ({
      location_entity_id: item.location_entity_id,
      hexes: (item.hexes || []).map((hex) => ({
        hex_q: hex.hex_q,
        hex_r: hex.hex_r,
        is_center: Boolean(hex.is_center),
        label_override: hex.label_override || null,
        style_override: hex.style_override || {},
      })).sort((a, b) => (
        a.hex_q - b.hex_q
        || a.hex_r - b.hex_r
        || Number(a.is_center) - Number(b.is_center)
      )),
    })).sort((a, b) => String(a.location_entity_id).localeCompare(String(b.location_entity_id)))
  },

  _persistedLocationBindingItems() {
    const grouped = new Map()
    for (const binding of this._state?.location_bindings || []) {
      if (!grouped.has(binding.location_entity_id)) grouped.set(binding.location_entity_id, [])
      grouped.get(binding.location_entity_id).push(binding)
    }
    return [...grouped.entries()].map(([location_entity_id, hexes]) => ({
      location_entity_id,
      hexes,
    }))
  },

  _layerTreeCommandNodes({ includePendingResources = false } = {}) {
    let sourceNodes = (mapState.pendingLayerTree || []).map((node) => ({ ...node }))
    if (includePendingResources) {
      const deletedTerrainIds = new Set(mapState.pendingTerrainLayerDeletes || [])
      const deletedPathIds = new Set(
        Object.values(mapState.pendingPathLayerChanges || {})
          .filter((change) => change.operation === "delete")
          .map((change) => change.id),
      )
      sourceNodes = sourceNodes.filter((node) => (
        !deletedTerrainIds.has(node.terrain_layer_id)
        && !deletedPathIds.has(node.path_layer_id)
      ))

      const appendResourceLeaf = ({
        parentKey,
        clientId,
        resourceClientField,
        resourceClientId,
        name,
        visible = true,
        locked = false,
        opacity = 1,
      }) => {
        const alreadyPresent = sourceNodes.some(
          (node) => node[resourceClientField] === resourceClientId,
        )
        if (alreadyPresent) return
        const parent = sourceNodes.find((node) => node.layer_key === parentKey)
        if (!parent) return
        const parentIdentity = this._layerNodeIdentity(parent)
        const siblings = sourceNodes.filter(
          (node) => (node.parent_id || node.parent_client_id || null) === parentIdentity,
        )
        const usedFloorLevels = new Set(
          siblings
            .map((node) => node.floor_level)
            .filter((level) => level != null)
            .map(Number),
        )
        const floorLevel = parent.selection_mode === "floor"
          ? Array.from({ length: 2001 }, (_, index) => (
            index === 0 ? 0 : index % 2 ? (index + 1) / 2 : -(index / 2)
          )).find((level) => !usedFloorLevels.has(level))
          : null
        sourceNodes.push({
          client_id: clientId,
          ...(parent.id ? { parent_id: parent.id } : { parent_client_id: parent.client_id }),
          [resourceClientField]: resourceClientId,
          node_type: "leaf",
          layer_key: null,
          name,
          visible,
          locked,
          opacity,
          sort_order: siblings.length
            ? Math.max(...siblings.map((node) => Number(node.sort_order || 0))) + 1
            : 0,
          min_zoom: null,
          max_zoom: null,
          selection_mode: "normal",
          floor_level: floorLevel ?? null,
          meta: {},
        })
      }

      const terrainDraft = mapState.pendingTerrainOverlay
      if (terrainDraft?.layerCreate) {
        terrainDraft.leafClientId ||= crypto.randomUUID()
        appendResourceLeaf({
          parentKey: "terrainOverlay",
          clientId: terrainDraft.leafClientId,
          resourceClientField: "terrain_layer_client_id",
          resourceClientId: terrainDraft.clientId,
          name: terrainDraft.layerCreate.name,
          visible: terrainDraft.layerCreate.visible !== false,
          locked: Boolean(terrainDraft.layerCreate.locked),
          opacity: Number(terrainDraft.layerCreate.opacity ?? 1),
        })
      }
      for (const change of Object.values(mapState.pendingPathLayerChanges || {})) {
        if (change.operation !== "create") continue
        appendResourceLeaf({
          parentKey: "path",
          clientId: change.leaf_client_id,
          resourceClientField: "path_layer_client_id",
          resourceClientId: change.client_id,
          name: change.data.display_name,
        })
      }
    }
    return sourceNodes.map((node) => ({
      ...(node.id ? { id: node.id } : { client_id: node.client_id }),
      ...(node.parent_id ? { parent_id: node.parent_id } : {}),
      ...(node.parent_client_id ? { parent_client_id: node.parent_client_id } : {}),
      ...(node.terrain_layer_id ? { terrain_layer_id: node.terrain_layer_id } : {}),
      ...(node.terrain_layer_client_id
        ? { terrain_layer_client_id: node.terrain_layer_client_id }
        : {}),
      ...(node.path_layer_id ? { path_layer_id: node.path_layer_id } : {}),
      ...(node.path_layer_client_id
        ? { path_layer_client_id: node.path_layer_client_id }
        : {}),
      node_type: node.node_type,
      layer_key: node.layer_key || null,
      name: node.name,
      visible: node.visible !== false,
      locked: Boolean(node.locked),
      opacity: Number(node.opacity ?? 1),
      sort_order: Number(node.sort_order || 0),
      min_zoom: node.min_zoom ?? null,
      max_zoom: node.max_zoom ?? null,
      selection_mode: node.selection_mode || "normal",
      floor_level: node.floor_level ?? null,
      meta: node.meta || {},
    }))
  },

  _reconcilePendingLayerTreeAfterPathLayerApply(commands, clientIdMap = {}) {
    if (!mapState.pendingLayerTree) return
    const pathCommands = (commands || []).filter(
      (command) => ["path_layer_create", "path_layer_delete"].includes(command.type),
    )
    if (!pathCommands.length) return

    let nodes = mapState.pendingLayerTree.map((node) => ({ ...node }))
    nodes = nodes.map((node) => {
      const next = { ...node }
      if (next.client_id && clientIdMap[next.client_id]) {
        next.id = clientIdMap[next.client_id]
        delete next.client_id
      }
      if (next.parent_client_id && clientIdMap[next.parent_client_id]) {
        next.parent_id = clientIdMap[next.parent_client_id]
        delete next.parent_client_id
      }
      if (next.path_layer_client_id && clientIdMap[next.path_layer_client_id]) {
        next.path_layer_id = clientIdMap[next.path_layer_client_id]
        delete next.path_layer_client_id
      }
      return next
    })

    for (const command of pathCommands) {
      if (command.type === "path_layer_delete") {
        const layerId = command.ref?.id || clientIdMap[command.ref?.client_id]
        nodes = nodes.filter((node) => node.path_layer_id !== layerId)
        continue
      }
      const layerId = clientIdMap[command.client_id]
      const leafId = clientIdMap[command.leaf_client_id]
      if (!layerId || nodes.some((node) => node.path_layer_id === layerId)) continue
      const persistedLeaf = (this._layerTree?.nodes || []).find(
        (node) => node.id === leafId || node.path_layer_id === layerId,
      )
      const parent = nodes.find((node) => node.layer_key === "path")
      if (!persistedLeaf || !parent) {
        mapState.layerTreeBaselineStale = true
        continue
      }
      const parentIdentity = this._layerNodeIdentity(parent)
      const siblings = nodes.filter(
        (node) => (node.parent_id || node.parent_client_id || null) === parentIdentity,
      )
      nodes.push({
        ...persistedLeaf,
        parent_id: parent.id || null,
        parent_client_id: parent.client_id || null,
        sort_order: siblings.length
          ? Math.max(...siblings.map((node) => Number(node.sort_order || 0))) + 1
          : 0,
      })
    }
    mapState.pendingLayerTree = nodes
    this._refreshLayerTreeDraft()
  },

  _baseTerrainCommandChanges() {
    return Object.values(mapState.pendingTerrainChanges || {}).filter((change) => {
      const persisted = this._tileByHex.get(`${change.hex_q},${change.hex_r}`)
        || (this._state?.tiles || []).find((item) => (
          item.hex_q === change.hex_q && item.hex_r === change.hex_r
        ))
      if (!persisted) return true
      return persisted.terrain_type !== change.terrain_type
        || Number(persisted.elevation || 0) !== Number(change.elevation || 0)
    })
  },

  _territoryCommandHexes(factionId, draft) {
    const byHex = new Map()
    for (const item of this._state?.territories || []) {
      if (item.faction_entity_id !== factionId || draft.remove?.[item.id]) continue
      byHex.set(`${item.hex_q},${item.hex_r}`, {
        hex_q: item.hex_q,
        hex_r: item.hex_r,
        style_override: item.style_override || {},
      })
    }
    for (const item of Object.values(draft.add || {})) {
      if (item.faction_entity_id !== factionId) continue
      byHex.set(`${item.hex_q},${item.hex_r}`, {
        hex_q: item.hex_q,
        hex_r: item.hex_r,
        style_override: item.style_override || {},
      })
    }
    return [...byHex.values()]
  },

  _territoryHexesChanged(factionId, hexes) {
    const persisted = (this._state?.territories || [])
      .filter((item) => item.faction_entity_id === factionId)
      .map((item) => `${item.hex_q},${item.hex_r}:${JSON.stringify(item.style_override || {})}`)
      .sort()
    const next = hexes
      .map((item) => `${item.hex_q},${item.hex_r}:${JSON.stringify(item.style_override || {})}`)
      .sort()
    return persisted.length !== next.length || persisted.some((value, index) => value !== next[index])
  },

  _buildEditorCommands({ onlyLayer = false, onlyLayerTree = false } = {}) {
    const activeLayer = mapState.editorLayer
    const include = (layer) => !onlyLayerTree && (!onlyLayer || activeLayer === layer)
    const commands = []
    const terrainChanges = include("baseTerrain") ? this._baseTerrainCommandChanges() : []
    if (terrainChanges.length) {
      commands.push({
        type: "base_terrain_replace",
        changes: terrainChanges,
      })
    }
    if (include("location")) {
      const hasLayouts = Object.keys(mapState.pendingLocationLayouts).length > 0
      const hasBindings = Object.keys(mapState.pendingBindings).length > 0
      const layouts = this._normalizedLocationLayouts(this._effectiveLocationLayouts())
      const layoutsChanged = hasLayouts && JSON.stringify(layouts) !== JSON.stringify(
        this._normalizedLocationLayouts(this._state?.location_layouts),
      )
      const bindingItems = this._normalizedLocationBindingItems(this._finalLocationBindingItems())
      const bindingsChanged = hasBindings && JSON.stringify(bindingItems) !== JSON.stringify(
        this._normalizedLocationBindingItems(this._persistedLocationBindingItems()),
      )
      if (layoutsChanged) {
        commands.push({
          type: "location_layout_replace",
          layouts,
          sync_bindings: !bindingsChanged,
        })
      }
      if (bindingsChanged) {
        commands.push({
          type: "location_binding_replace",
          items: bindingItems,
        })
      }
    }
    if (include("terrainOverlay")) {
      const draft = mapState.pendingTerrainOverlay
      if (draft?.layerCreate) {
        commands.push({
          type: "terrain_layer_create",
          client_id: draft.clientId,
          data: { ...draft.layerCreate, ...(draft.layerUpdate || {}) },
        })
      } else if (draft?.layerUpdate) {
        commands.push({
          type: "terrain_layer_update",
          ref: { id: draft.layerId },
          data: draft.layerUpdate,
        })
      }
      for (const layerId of mapState.pendingTerrainLayerDeletes || []) {
        commands.push({ type: "terrain_layer_delete", ref: { id: layerId } })
      }
      if (draft) {
        commands.push({
          type: "terrain_patch_replace",
          layer_ref: draft.layerCreate
            ? { client_id: draft.clientId }
            : { id: draft.layerId },
          data: {
            regions: draft.regions.map((region) => ({
              id: region.id,
              layer_id: draft.layerId,
              name: region.name || "手绘区域",
              region_status: region.region_status || "active",
              meta: region.meta || {},
            })),
            patches: draft.patches.map((patch) => ({
              region_id: patch.region_id,
              hex_q: patch.hex_q,
              hex_r: patch.hex_r,
              strength: patch.strength ?? 1,
              brush_source: patch.brush_source || mapState.overlayTool,
            })),
          },
        })
      }
    }
    if (include("path")) {
      for (const change of Object.values(mapState.pendingPathLayerChanges || {})) {
        if (change.operation === "create") {
          commands.push({
            type: "path_layer_create",
            client_id: change.client_id,
            leaf_client_id: change.leaf_client_id,
            display_name: change.data.display_name,
            category: change.data.category,
            meta: change.data.meta || {},
          })
        } else if (change.operation === "delete") {
          commands.push({ type: "path_layer_delete", ref: { id: change.id } })
        }
      }
      for (const change of Object.values(mapState.pendingPathChanges || {})) {
        if (change.operation === "create") {
          const { path_layer_id: layerId, nodes = [], ...data } = change.data
          commands.push({
            type: "path_create",
            client_id: change.client_id,
            data: {
              ...data,
              layer_ref: mapState.pendingPathLayerChanges[layerId]?.operation === "create"
                ? { client_id: layerId }
                : { id: layerId },
              nodes: nodes.map(({ q, r, width_scale, tension, segment_type }) => ({
                q, r, width_scale, tension, ...(segment_type ? { segment_type } : {}),
              })),
            },
          })
        } else if (change.operation === "update") {
          const { path_layer_id: layerId, nodes, ...data } = change.data || {}
          commands.push({
            type: "path_update",
            ref: { id: change.id },
            data: {
              ...data,
              ...(layerId ? {
                layer_ref: mapState.pendingPathLayerChanges[layerId]?.operation === "create"
                  ? { client_id: layerId }
                  : { id: layerId },
              } : {}),
              ...(nodes ? {
                nodes: nodes.map(({ q, r, width_scale, tension, segment_type }) => ({
                  q, r, width_scale, tension, ...(segment_type ? { segment_type } : {}),
                })),
              } : {}),
            },
          })
        } else if (["archive", "restore"].includes(change.operation)) {
          commands.push({ type: `path_${change.operation}`, ref: { id: change.id } })
        }
      }
    }
    if (mapState.pendingLayerTree && (onlyLayerTree || !onlyLayer)) {
      commands.push({
        type: "layer_tree_replace",
        nodes: this._layerTreeCommandNodes({
          includePendingResources: !onlyLayerTree && !onlyLayer,
        }),
      })
    }
    if (include("marker")) {
      for (const change of Object.values(mapState.pendingMarkerChanges || {})) {
        if (change.operation === "create") {
          commands.push({
            type: "marker_create",
            client_id: change.client_id,
            data: change.data,
          })
        } else if (change.operation === "update") {
          commands.push({
            type: "marker_update",
            ref: { id: change.id },
            data: change.data,
          })
        } else if (change.operation === "delete") {
          commands.push({ type: "marker_delete", ref: { id: change.id } })
        }
      }
    }
    if (include("territory")) {
      const draft = mapState.pendingTerritoryChanges || { add: {}, remove: {} }
      const affected = new Set(
        Object.values(draft.add || {}).map((item) => item.faction_entity_id),
      )
      const byId = new Map((this._state?.territories || []).map((item) => [item.id, item]))
      for (const territoryId of Object.keys(draft.remove || {})) {
        const persisted = byId.get(territoryId)
        if (persisted) affected.add(persisted.faction_entity_id)
      }
      for (const factionId of affected) {
        const hexes = this._territoryCommandHexes(factionId, draft)
        if (!this._territoryHexesChanged(factionId, hexes)) continue
        commands.push({
          type: "territory_replace",
          faction_entity_id: factionId,
          hexes,
        })
      }
    }
    return commands
  },

  async _applyAllChanges({ onlyLayer = false, onlyLayerTree = false } = {}) {
    if (this._applyingEditorChanges || mapEditingSession.isApplying()) {
      toast("地图编辑正在应用，请等待当前请求完成", "warning")
      return false
    }
    if (
      mapState.dragDrawing
      || this._dragLocationId
      || this._dragMarkerId
      || this._dragPathNode
      || this._pathPointerSamples
    ) {
      toast("请先结束当前拖拽或绘制，再应用地图变更", "warning")
      return false
    }
    const commands = this._buildEditorCommands({ onlyLayer, onlyLayerTree })
    if (!commands.length) {
      toast("没有待应用的变更", "info")
      return true
    }
    const lifecycleEpoch = this._lifecycleEpoch
    const mountContext = this._mountContext
    const mapId = this._state?.map?.id
    if (!mapId) return false
    mapEditingSession.syncBaseline(mapId, this._state.map.editor_revision)
    const { validationError, attempt } = mapEditingSession.beginApply(commands, {
      onlyLayer,
      onlyLayerTree,
    })
    if (validationError) {
      toast(validationError, "error")
      return false
    }
    const applyingMarkers = attempt.commands.some(
      (command) => command.type.startsWith("marker_"),
    )
    this._setEditorApplyBusy(true, attempt.id)
    try {
      const result = await api.world.applyMapEditor(
        mapId,
        mapEditingSession.requestFor(attempt),
        state.currentProjectId,
      )
      if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) {
        mapEditingSession.cancelApply(attempt)
        return true
      }
      this._state.map.editor_revision = result.editor_revision
      const clientIdMap = result.client_id_map || {}
      const transition = mapEditingSession.commitApply(attempt, result)
      if (!transition) {
        toast("地图应用会话已失效，请刷新后确认当前状态", "warning")
        return false
      }
      const preserveMarkerDraft = Boolean(
        transition?.preservedLayers?.includes("marker"),
      )
      await this._reloadMapStatePreservingSession(
        mapId,
        mapState.currentSceneId,
        { preserveMarkers: !applyingMarkers || preserveMarkerDraft },
      )
      if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return true
      await this._loadLayerTree()
      if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return true
      this._reconcilePendingLayerTreeAfterPathLayerApply(
        attempt.commands,
        clientIdMap,
      )
      await this._loadPaths()
      if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return true
      updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
      updateBindingPendingCount(Object.keys(mapState.pendingBindings).length)
      this._notifyEditingChanged()
      if (mapState.mode === "edit") this._rerenderEditor()
      else this._redraw()
      if (transition.preservedLayers.length) {
        toast("保存期间检测到新的同层草稿，已保留；请确认后再次应用", "warning")
        return false
      }
      toast(`已原子应用 ${commands.length} 个编辑命令`, "success")
      return true
    } catch (err) {
      if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) {
        mapEditingSession.cancelApply(attempt)
        return false
      }
      const conflictCode = err.body?.error || err.body?.code
      if (err.status === 409 && conflictCode === "map_editor_revision_conflict") {
        mapEditingSession.markConflict(
          attempt,
          err.body?.context?.current_revision,
        )
        await this._reloadMapStatePreservingSession(
          this._state.map.id,
          mapState.currentSceneId,
        )
        await this._loadLayerTree()
        await this._loadPaths()
        this._redraw()
        const current = this._state?.map?.editor_revision
        toast("地图已有新版本，已刷新参考状态，草稿已保留；检查后可再次应用", "warning")
      } else {
        mapEditingSession.cancelApply(attempt)
        toast(`应用失败：${err.message}`, "error")
      }
      return false
    } finally {
      this._setEditorApplyBusy(false, attempt.id)
    }
  },

  async _applyTerrainChanges() {
    const pendingCount = Object.keys(mapState.pendingTerrainChanges).length
    if (pendingCount > MAP_TILE_BATCH_LIMIT) {
      throw new Error(`单次最多应用 ${MAP_TILE_BATCH_LIMIT} 个地形变更，请撤销部分变更后分批保存`)
    }
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
    const deletions = bindings.filter((binding) => binding.operation === "delete")
    const additions = bindings.filter((binding) => binding.operation !== "delete")
    const byEntity = {}
    for (const b of additions) {
      if (!byEntity[b.location_entity_id]) byEntity[b.location_entity_id] = []
      byEntity[b.location_entity_id].push({ hex_q: b.hex_q, hex_r: b.hex_r, is_center: b.is_center })
    }
    const oversized = Object.values(byEntity)
      .find((hexes) => hexes.length > MAP_LOCATION_BINDING_HEX_LIMIT)
    if (oversized) {
      throw new Error(`单个地点单次最多绑定 ${MAP_LOCATION_BINDING_HEX_LIMIT} 个地图格，请减少选中范围`)
    }
    try {
      for (const binding of deletions) {
        await api.world.deleteLocationBinding(
          this._state.map.id,
          binding.binding_id,
          state.currentProjectId,
        )
      }
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

  async _applyLocationLayouts() {
    const layouts = this._effectiveLocationLayouts().map((layout) => ({
      location_entity_id: layout.location_entity_id,
      center_hex_q: layout.center_hex_q,
      center_hex_r: layout.center_hex_r,
      occupy_radius: layout.occupy_radius || 1,
      locked: Boolean(layout.locked),
      layout_source: layout.layout_source || "user_drag",
      layout_version: layout.layout_version || 1,
      sync_geo_setting: Boolean(layout.sync_geo_setting),
      meta: layout.meta || {},
    }))
    await api.world.replaceLocationLayouts(this._state.map.id, {
      layouts,
      sync_bindings: true,
    }, state.currentProjectId)
    mapState.pendingLocationLayouts = {}
  },

  async _applyTerrainOverlay() {
    const draft = mapState.pendingTerrainOverlay
    if (!draft) return
    if (draft.layerUpdate) {
      await api.world.updateTerrainLayer(
        this._state.map.id,
        draft.layerId,
        draft.layerUpdate,
        state.currentProjectId,
      )
    }
    await api.world.replaceTerrainLayerPatches(this._state.map.id, draft.layerId, {
      regions: draft.regions.map((region) => ({
        id: region.id,
        layer_id: draft.layerId,
        name: region.name || "手绘区域",
        region_status: region.region_status || "active",
        meta: region.meta || {},
      })),
      patches: draft.patches.map((patch) => ({
        region_id: patch.region_id,
        hex_q: patch.hex_q,
        hex_r: patch.hex_r,
        strength: patch.strength ?? 1,
        brush_source: patch.brush_source || mapState.overlayTool,
      })),
    }, state.currentProjectId)
    mapState.pendingTerrainOverlay = null
  },

  async _applyTerritoryChanges() {
    const draft = mapState.pendingTerritoryChanges
    const additionsByFaction = {}
    for (const item of Object.values(draft.add || {})) {
      if (!additionsByFaction[item.faction_entity_id]) additionsByFaction[item.faction_entity_id] = []
      additionsByFaction[item.faction_entity_id].push({ hex_q: item.hex_q, hex_r: item.hex_r })
    }
    for (const [factionId, hexes] of Object.entries(additionsByFaction)) {
      await api.world.createTerritories(
        this._state.map.id,
        { faction_entity_id: factionId, hexes },
        state.currentProjectId,
      )
    }
    for (const territoryId of Object.keys(draft.remove || {})) {
      await api.world.deleteMapTerritory(
        this._state.map.id,
        territoryId,
        state.currentProjectId,
      )
    }
    mapState.pendingTerritoryChanges = { add: {}, remove: {} }
  },

  _ensureOverlayDraft() {
    const layerId = mapState.selectedTerrainLayerId
    const layer = (this._state?.terrain_layers || []).find((item) => item.id === layerId)
    if (!layer) {
      toast("请先新建或选择覆盖图层", "warning")
      return null
    }
    if (this._effectiveLayerNode({ terrainLayerId: layerId }).locked) {
      toast("覆盖图层受自身或父组锁定，请先在图层树中解锁", "warning")
      return null
    }
    if (mapState.pendingTerrainOverlay?.layerId === layerId) {
      mapState.pendingTerrainOverlay.layerUpdate = {
        terrain_asset_key: mapState.selectedTerrainAssetKey,
        meta: {
          ...(layer.meta || {}),
          pack_key: getTerrainAsset(mapState.selectedTerrainAssetKey).pack_key,
          preset_key: mapState.selectedTerrainPreset,
        },
      }
      return mapState.pendingTerrainOverlay
    }
    let regions = (this._state.terrain_regions || [])
      .filter((region) => region.layer_id === layerId)
      .map((region) => ({ ...region }))
    if (!regions.length) {
      regions = [{
        id: crypto.randomUUID(),
        layer_id: layerId,
        name: "手绘区域",
        region_status: "active",
        meta: {},
      }]
    }
    mapState.pendingTerrainOverlay = {
      layerId,
      regions,
      patches: (this._state.terrain_patches || [])
        .filter((patch) => patch.layer_id === layerId)
        .map((patch) => ({ ...patch })),
      layerUpdate: {
        terrain_asset_key: mapState.selectedTerrainAssetKey,
        meta: {
          ...(layer.meta || {}),
          pack_key: getTerrainAsset(mapState.selectedTerrainAssetKey).pack_key,
          preset_key: mapState.selectedTerrainPreset,
        },
      },
    }
    return mapState.pendingTerrainOverlay
  },

  _stageOverlayBrush(q, r) {
    const draft = this._ensureOverlayDraft()
    if (!draft) return
    const regionId = draft.regions[0].id
    const radius = Math.max(1, Number(mapState.overlayBrushSize || 1)) - 1
    const cfg = this._state.map
    const cells = []
    for (let dq = -radius; dq <= radius; dq += 1) {
      for (let dr = -radius; dr <= radius; dr += 1) {
        if (Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr)) > radius) continue
        const hexQ = q + dq
        const hexR = r + dr
        if (hexQ >= 0 && hexQ < cfg.grid_width && hexR >= 0 && hexR < cfg.grid_height) {
          cells.push([hexQ, hexR])
        }
      }
    }
    const keys = new Set(cells.map(([hexQ, hexR]) => `${hexQ},${hexR}`))
    if (mapState.overlayTool === "eraser") {
      draft.patches = draft.patches.filter((patch) => !keys.has(`${patch.hex_q},${patch.hex_r}`))
    } else {
      const existing = new Set(draft.patches.map((patch) => `${patch.hex_q},${patch.hex_r}`))
      for (const [hexQ, hexR] of cells) {
        const key = `${hexQ},${hexR}`
        if (existing.has(key)) continue
        draft.patches.push({
          layer_id: draft.layerId,
          region_id: regionId,
          hex_q: hexQ,
          hex_r: hexR,
          strength: 1,
          brush_source: "brush",
        })
      }
    }
    this._notifyEditingChanged()
  },

  _handleOverlayBucket(q, r) {
    const draft = this._ensureOverlayDraft()
    if (!draft) return
    const target = this._tileAt(q, r)?.terrain_type
    if (!target) return
    const changes = floodFillTerrain(
      q,
      r,
      target,
      target,
      (hexQ, hexR) => this._tileAt(hexQ, hexR)?.terrain_type || null,
    ).slice(0, 20000)
    const regionId = draft.regions[0].id
    const keys = new Set(changes.map((item) => `${item.hex_q},${item.hex_r}`))
    const before = this._snapshotActiveDraft()
    if (mapState.overlayTool === "eraser") {
      draft.patches = draft.patches.filter((patch) => !keys.has(`${patch.hex_q},${patch.hex_r}`))
    } else {
      const existing = new Set(draft.patches.map((patch) => `${patch.hex_q},${patch.hex_r}`))
      for (const item of changes) {
        const key = `${item.hex_q},${item.hex_r}`
        if (existing.has(key)) continue
        draft.patches.push({
          layer_id: draft.layerId,
          region_id: regionId,
          hex_q: item.hex_q,
          hex_r: item.hex_r,
          strength: 1,
          brush_source: "bucket",
        })
      }
    }
    mapEditingSession.recordCommand("terrainOverlay", { kind: "draft", before, after: this._snapshotActiveDraft() })
    this._notifyEditingChanged()
    this._redraw()
  },

  _showOverlayLayerCreate() {
    if (this._effectiveLayerNode({ layerKey: "terrainOverlay" }).locked) {
      toast("覆盖素材组受自身或父组锁定，请先在图层树中解锁", "warning")
      return
    }
    const layerId = crypto.randomUUID()
    const regionId = crypto.randomUUID()
    const asset = getTerrainAsset(mapState.selectedTerrainAssetKey)
    const form = `<div class="form-group"><label>图层名称</label><input id="map-overlay-new-name" class="form-input" value="${esc(asset.label)}层" /></div>`
    showModalHtml("新建覆盖素材图层", form, [{
      text: "创建",
      class: "btn-primary",
      handler: () => {
        const name = document.getElementById("map-overlay-new-name")?.value?.trim() || `${asset.label}层`
        const layerCreate = {
          name,
          terrain_asset_key: asset.asset_key,
          opacity: asset.default_opacity,
          z_index: 10 + (this._state.terrain_layers || []).length,
          visible: true,
          locked: false,
          meta: { pack_key: asset.pack_key, preset_key: mapState.selectedTerrainPreset },
        }
        this._state.terrain_layers = [
          ...(this._state.terrain_layers || []),
          { id: layerId, map_id: this._state.map.id, ...layerCreate, __draft: true },
        ]
        mapState.pendingTerrainOverlay = {
          layerId,
          clientId: layerId,
          leafClientId: crypto.randomUUID(),
          layerCreate,
          layerUpdate: null,
          regions: [{
            id: regionId,
            layer_id: layerId,
            name: `${name}区域`,
            region_status: "active",
            meta: {},
          }],
          patches: [],
        }
        closeModal()
        mapState.selectedTerrainLayerId = layerId
        this._notifyEditingChanged()
        this._rerenderEditor()
      },
    }])
  },

  _showOverlayLayerSettings() {
    const layer = (this._state?.terrain_layers || []).find((item) => item.id === mapState.selectedTerrainLayerId)
    if (!layer) return
    if (!this._guardEditorLayerWritable("terrainOverlay")) return
    const form = `<div class="form-group"><label>名称</label><input id="map-overlay-edit-name" class="form-input" value="${esc(layer.name)}" /></div><div class="form-group"><label>透明度</label><input id="map-overlay-edit-opacity" class="form-input" type="number" min="0" max="1" step="0.05" value="${Number(layer.opacity)}" /></div><div class="form-group"><label>层级</label><input id="map-overlay-edit-z" class="form-input" type="number" value="${Number(layer.z_index)}" /></div><label class="map-checkbox"><input id="map-overlay-edit-visible" type="checkbox" ${layer.visible ? "checked" : ""}/> 显示</label><label class="map-checkbox"><input id="map-overlay-edit-locked" type="checkbox" ${layer.locked ? "checked" : ""}/> 锁定</label>`
    showModalHtml("覆盖图层设置", form, [{
      text: "保存",
      class: "btn-primary",
      handler: () => {
        const update = {
          name: document.getElementById("map-overlay-edit-name")?.value?.trim() || layer.name,
          opacity: Number(document.getElementById("map-overlay-edit-opacity")?.value ?? layer.opacity),
          z_index: Number(document.getElementById("map-overlay-edit-z")?.value ?? layer.z_index),
          visible: Boolean(document.getElementById("map-overlay-edit-visible")?.checked),
          locked: Boolean(document.getElementById("map-overlay-edit-locked")?.checked),
        }
        Object.assign(layer, update)
        const draft = this._ensureOverlayDraft()
        if (draft?.layerCreate) Object.assign(draft.layerCreate, update)
        else if (draft) draft.layerUpdate = { ...(draft.layerUpdate || {}), ...update }
        closeModal()
        this._notifyEditingChanged()
        this._rerenderEditor()
      },
    }])
  },

  _deleteOverlayLayer() {
    const layer = (this._state?.terrain_layers || []).find((item) => item.id === mapState.selectedTerrainLayerId)
    if (!layer) return
    const regions = (this._state.terrain_regions || []).filter((item) => item.layer_id === layer.id)
    const regionIds = new Set(regions.map((item) => item.id))
    const patchCount = (this._state.terrain_patches || []).filter((item) => item.layer_id === layer.id).length
    const bindingCount = (this._state.terrain_bindings || []).filter((item) => regionIds.has(item.region_id)).length
    confirmAction(`删除「${esc(layer.name)}」将同时删除 ${regions.length} 个区域、${patchCount} 个 patch、${bindingCount} 个绑定。`, async () => {
      if (!this._guardEditorLayerWritable("terrainOverlay")) return
      if (!layer.__draft) mapState.pendingTerrainLayerDeletes.push(layer.id)
      this._state.terrain_layers = (this._state.terrain_layers || [])
        .filter((item) => item.id !== layer.id)
      mapState.selectedTerrainLayerId = null
      mapState.pendingTerrainOverlay = null
      this._notifyEditingChanged()
      this._rerenderEditor()
    }, "删除图层")
  },

  async _saveAndExit() {
    // 先应用未保存变更，再退出编辑
    const lifecycleEpoch = this._lifecycleEpoch
    const mountContext = this._mountContext
    const saved = await this._applyAllChanges()
    if (!saved) return false
    if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return true
    if (mapEditingSession.hasDraftChanges()) {
      toast("仍有未保存的地图草稿，请再次应用后再退出", "warning")
      return false
    }
    this._teardownInteractiveSurface()
    mapState.mode = "browse"
    setEditorLayer("none")
    this._notifyEditingChanged()
    this._render(this._mountRootId || "map-root")
    toast("已保存", "success")
    return true
  },

  _onCenterClick(entityId) {
    const binding = (this._state?.location_bindings || []).find(
      (item) => item.location_entity_id === entityId && item.is_center,
    )
    if (!binding) return false
    setSelectedHex(binding.hex_q, binding.hex_r)
    mapState.selectedMapObject = {
      kind: "location",
      id: binding.id,
      entityId,
      q: binding.hex_q,
      r: binding.hex_r,
    }
    this._updateDetailPanel(binding.hex_q, binding.hex_r)
    return true
  },

  _showLocationCluster(clusterId) {
    const items = this._labelClusterItemsById.get(clusterId) || []
    const locations = items
      .map((item) => ({
        id: item.source_id || item.target_entity_id || item.location_entity_id || item.entity_id,
        kind: item.source_kind || "location",
        name: item.title || this._locationName(item.target_entity_id),
        q: item.q ?? item.hex_q,
        r: item.r ?? item.hex_r,
      }))
      .filter((item) => item.id)
    if (!locations.length) return false
    const body = `<div class="map-cluster-member-list">${locations.map((item) => `
      <button class="btn map-cluster-member" data-map-cluster-member="${esc(item.id)}" data-kind="${esc(item.kind)}" data-q="${esc(item.q)}" data-r="${esc(item.r)}">${esc(item.name || "未命名地图对象")}</button>
    `).join("")}</div>`
    showModalHtml("选择地图对象", body, [{ text: "取消", class: "btn", handler: closeModal }])
    document.querySelectorAll("[data-map-cluster-member]").forEach((button) => {
      button.onclick = () => {
        closeModal()
        this._openMapLayoutItem({
          kind: button.dataset.kind,
          id: button.dataset.mapClusterMember,
          q: Number(button.dataset.q),
          r: Number(button.dataset.r),
        })
      }
    })
    return true
  },

  _openMapLayoutItem({ kind, id, q, r } = {}) {
    if (kind === "location") return this._onCenterClick(id)
    if (kind === "path") {
      const path = this._effectivePaths().find((item) => (item.id || item.client_id) === id)
      if (!path) return false
      this.selectInspectorObject("path", path)
      const panel = document.getElementById("map-detail-panel")
      if (panel) panel.innerHTML = this._renderPathDetail(path)
      return true
    }
    if (kind === "marker") {
      const marker = (this._state?.markers || []).find((item) => item.id === id)
      if (!marker) return false
      setSelectedHex(marker.hex_q, marker.hex_r)
      mapState.selectedMapObject = {
        kind: "marker",
        id: marker.id,
        entityId: marker.entity_id,
        q: marker.hex_q,
        r: marker.hex_r,
      }
      const panel = document.getElementById("map-detail-panel")
      if (panel) panel.innerHTML = this._renderMarkerDetail(marker)
      return true
    }
    if (kind === "territory") {
      const tiles = (this._state?.territories || []).filter(
        (item) => item.faction_entity_id === id,
      )
      const territory = [...tiles].sort((left, right) => (
        Math.hypot(Number(left.hex_q) - Number(q), Number(left.hex_r) - Number(r))
        - Math.hypot(Number(right.hex_q) - Number(q), Number(right.hex_r) - Number(r))
      ))[0]
      if (!territory) return false
      setSelectedHex(territory.hex_q, territory.hex_r)
      mapState.selectedMapObject = {
        kind: "territory",
        id: territory.id,
        entityId: territory.faction_entity_id,
        q: territory.hex_q,
        r: territory.hex_r,
      }
      const panel = document.getElementById("map-detail-panel")
      if (panel) panel.innerHTML = this._renderTerritoryDetail(territory)
      return true
    }
    if (kind === "dynamic") {
      const callback = this._mountContext?.onOpenDynamicItem
      if (typeof callback === "function") callback(id)
      return true
    }
    if (Number.isFinite(q) && Number.isFinite(r)) {
      setSelectedHex(Math.round(q), Math.round(r))
      this._updateDetailPanel(Math.round(q), Math.round(r))
      return true
    }
    return false
  },

  _drillToLocation(entityId) {
    if (this._hasDetailMap(entityId)) {
      const detail = this._detailMapByEntityId.get(entityId)
      if (detail) return this._openMap(detail.id)
    } else {
      return confirmAction(
        `为该地点创建详图？`,
        () => this._showCreateDetailForm(entityId),
        "创建详图"
      )
    }
    return false
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
    showModalHtml("创建世界地图", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const ownsModal = this._captureModalOwner("map-create-name")
        if (!ownsModal()) return true
        const name = document.getElementById("map-create-name")?.value.trim()
        if (!name) { toast("请输入地图名称", "warning"); return false }
        const [w, h] = (document.getElementById("map-create-size")?.value || "30,20").split(",").map(Number)
        const template = document.getElementById("map-create-template")?.value || "blank"
        const projectId = state.currentProjectId
        let created
        try {
          created = await api.world.createMap({
            name, map_type: "world", grid_width: w, grid_height: h, template,
          }, projectId)
        } catch (err) {
          if (!ownsModal()) return true
          toast(`创建失败：${err.message}`, "error")
          return false
        }
        if (!ownsModal()) return true
        closeModal()
        toast("世界地图已创建", "success")
        const lifecycleEpoch = this._lifecycleEpoch
        const mountContext = this._mountContext
        try {
          await this._openMap(created.id)
        } catch (err) {
          if (this._isLifecycleCurrent(lifecycleEpoch, mountContext)) {
            toast(`地图已创建，但未能自动打开：${err.message}`, "warning")
          }
        }
        return true
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
    showModalHtml("创建地点详图", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const ownsModal = this._captureModalOwner("map-detail-name")
        if (!ownsModal()) return true
        const name = document.getElementById("map-detail-name")?.value.trim() || locName
        const importance = document.getElementById("map-detail-importance")?.value || "important"
        const autogen = document.getElementById("map-detail-autogen")?.value === "1"
        const sizes = { core: [60, 45], important: [40, 30], normal: [20, 30] }
        const [w, h] = sizes[importance] || sizes.important
        const projectId = state.currentProjectId
        const parentMapId = this._state.map.id
        let created
        try {
          created = await api.world.createMap({
            name, map_type: "city", grid_width: w, grid_height: h,
            parent_map_id: parentMapId, parent_entity_id: entityId,
          }, projectId)
        } catch (err) {
          if (!ownsModal()) return true
          toast(`创建失败：${err.message}`, "error")
          return false
        }
        let generateError = null
        if (autogen) {
          try {
            await this._generateMapWhenAvailable(created.id, projectId)
          } catch (err) {
            generateError = err
          }
        }
        if (!ownsModal()) return true
        closeModal()
        toast(generateError
          ? `详图已创建，但快速生成失败：${generateError.message}`
          : "详图已创建", generateError ? "warning" : "success")
        const lifecycleEpoch = this._lifecycleEpoch
        const mountContext = this._mountContext
        try {
          await this._openMap(created.id)
        } catch (err) {
          if (this._isLifecycleCurrent(lifecycleEpoch, mountContext)) {
            toast(`详图已创建，但未能自动打开：${err.message}`, "warning")
          }
        }
        return true
      },
    }])
  },

  async _generateMapWhenAvailable(mapId, projectId = state.currentProjectId) {
    let lastError = null
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        return await api.world.generateMap(mapId, projectId)
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
    const descendantIds = new Set([cfg.id])
    let changed = true
    while (changed) {
      changed = false
      for (const candidate of this._maps || []) {
        if (
          !descendantIds.has(candidate.id)
          && descendantIds.has(candidate.parent_map_id)
        ) {
          descendantIds.add(candidate.id)
          changed = true
        }
      }
    }
    const parentMapOptions = (this._maps || [])
      .filter((candidate) => !descendantIds.has(candidate.id))
      .map((candidate) => `
        <option value="${esc(candidate.id)}" ${candidate.id === cfg.parent_map_id ? "selected" : ""}>
          ${esc(candidate.name)}
        </option>
      `)
      .join("")
    const parentEntityOptions = (this._locations || [])
      .map((location) => `
        <option value="${esc(location.id)}" ${location.id === cfg.parent_entity_id ? "selected" : ""}>
          ${esc(location.name)}
        </option>
      `)
      .join("")
    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="map-settings-name" value="${esc(cfg.name)}" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-input" id="map-settings-desc" rows="3">${esc(cfg.description || "")}</textarea>
      </div>
      <div class="form-group">
        <label>上级地图</label>
        <select class="form-select" id="map-settings-parent-map">
          <option value="">顶层地图</option>
          ${parentMapOptions}
        </select>
      </div>
      <div class="form-group">
        <label>对应的上级地点（可选）</label>
        <select class="form-select" id="map-settings-parent-entity">
          <option value="">不关联具体地点</option>
          ${parentEntityOptions}
        </select>
        <p class="map-hint">移动地图只修改层级，已绘制的地形、地点、线路和动态事实会完整保留。</p>
      </div>
    `
    showModalHtml("地图设置", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        const ownsModal = this._captureModalOwner("map-settings-name")
        if (!ownsModal()) return true
        const name = document.getElementById("map-settings-name")?.value.trim()
        if (!name) { toast("请输入地图名称", "warning"); return false }
        const description = document.getElementById("map-settings-desc")?.value.trim()
        const parentMapField = document.getElementById("map-settings-parent-map")
        const parentEntityField = document.getElementById("map-settings-parent-entity")
        const payload = { name, description }
        if (parentMapField) {
          payload.parent_map_id = parentMapField.value || null
          payload.parent_entity_id = parentMapField.value
            ? (parentEntityField?.value || null)
            : null
        }
        const projectId = state.currentProjectId
        try {
          await api.world.updateMap(
            cfg.id,
            payload,
            projectId
          )
        } catch (err) {
          if (!ownsModal()) return true
          toast(`更新失败：${err.message}`, "error")
          return false
        }
        if (!ownsModal()) return true
        closeModal()
        toast("地图信息已更新", "success")
        const lifecycleEpoch = this._lifecycleEpoch
        const mountContext = this._mountContext
        try {
          await this._reloadMapStatePreservingSession(cfg.id)
          if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return true
          await this._loadMaps()
          if (!this._isLifecycleCurrent(lifecycleEpoch, mountContext)) return true
          // Keep the current map selected after saving its metadata. A full
          // unmount clears `_state` and unexpectedly sends the author back to
          // the map list, interrupting an otherwise local settings edit.
          this._teardownInteractiveSurface()
          mapState.mode = previousMode
          this._render("map-root")
        } catch (err) {
          if (this._isLifecycleCurrent(lifecycleEpoch, mountContext)) {
            toast(`地图信息已更新，但页面对账失败：${err.message}`, "warning")
          }
        }
        return true
      },
    }])
  },

  // === P2: 势力范围与聚焦模式 ===

  _renderTerritoryTools() {
    const orgs = this._allEntities.filter((e) => e.entity_type === "organization")
    if (orgs.length === 0) {
      return `<div class="map-tool-group"><p class="world-text-dim">暂无组织实体（需在 world 对象中创建 organization 类型实体）</p></div>`
    }
    const orgOptions = orgs.map((o) => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join("")
    const selectedOrg = mapState.selectedFactionId
    const currentColor = this._safeHexColor(mapState.factionColors[selectedOrg], "#FF6B6B")
    return `
      <div class="map-tool-group">
        <select id="map-territory-faction" class="form-select">
          <option value="">选择组织...</option>
          ${orgOptions}
        </select>
        <div class="map-faction-color-row" style="display:flex;gap:8px;align-items:center;margin-top:8px;">
          <input type="color" id="map-territory-color" value="${esc(currentColor)}" style="width:40px;height:28px;padding:0;border:none;" />
          <span style="font-size:12px;color:var(--text-dim);">颜色</span>
        </div>
        <div class="map-tool-actions" style="margin-top:8px;">
          <button class="btn btn-sm btn-danger" data-action="map-territory-clear">清空该组织全部范围</button>
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

  _isMarkerLayerEnabled(marker, zoom = this._leaflet?.getZoom?.() ?? null) {
    const key = `marker.${marker.marker_type || "character"}`
    if (!this._effectiveLayerNode({ layerKey: key, zoom }).visible) return false
    if (marker.marker_type === "event") return this._isLayerEnabled("events")
    if (marker.marker_type === "item") return this._isLayerEnabled("items")
    return this._isLayerEnabled("markers")
  },

  _filteredMarkers(zoom = this._leaflet?.getZoom?.() ?? null) {
    return (this._state?.markers || []).filter(
      (marker) => marker.visible !== false && this._isMarkerLayerEnabled(marker, zoom),
    )
  },

  _candidateMarkers(zoom = this._leaflet?.getZoom?.() ?? null) {
    if (!this._isLayerEnabled("candidate")) return []
    return (this._state?.candidate_markers || []).filter(
      (marker) => marker.visible !== false && this._isMarkerLayerEnabled(marker, zoom),
    )
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

  _handleTerritoryEdit(q, r) {
    const draft = mapState.pendingTerritoryChanges
    const territory = this._effectiveTerritories().find((item) => (
      item.hex_q === q
      && item.hex_r === r
      && (!mapState.selectedFactionId || item.faction_entity_id === mapState.selectedFactionId)
    ))
    if (mapState.territoryEraseMode) {
      if (!territory) return
      if (String(territory.id).startsWith("draft:")) delete draft.add[territory.id]
      else draft.remove[territory.id] = { ...territory }
    } else {
      const factionId = mapState.selectedFactionId
      if (!factionId) {
        toast("请先选择组织", "warning")
        return
      }
      if (territory?.faction_entity_id === factionId) return
      const removed = Object.values(draft.remove).find((item) => (
        item.hex_q === q && item.hex_r === r && item.faction_entity_id === factionId
      ))
      if (removed) delete draft.remove[removed.id]
      else {
        const id = `draft:${factionId}:${q},${r}`
        draft.add[id] = { id, faction_entity_id: factionId, hex_q: q, hex_r: r }
      }
    }
    this._notifyEditingChanged()
    this._redraw()
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
    if (!this._guardEditorLayerWritable("territory")) return
    const factionId = mapState.selectedFactionId
    if (!factionId) {
      toast("请先选择组织", "warning")
      return
    }
    confirmAction(
      `确定清除该组织的全部势力范围？`,
      () => {
        const before = this._snapshotActiveDraft()
        const draft = mapState.pendingTerritoryChanges
        for (const territory of this._effectiveTerritories().filter(
          (item) => item.faction_entity_id === factionId,
        )) {
          if (String(territory.id).startsWith("draft:")) {
            delete draft.add[territory.id]
          } else {
            draft.remove[territory.id] = { ...territory }
          }
        }
        mapEditingSession.recordCommand("territory", {
          kind: "draft",
          before,
          after: this._snapshotActiveDraft(),
        })
        this._notifyEditingChanged()
        this._redraw()
        toast("势力范围清除已加入草稿", "info")
      },
      "清除"
    )
  },
}

export default mapView
