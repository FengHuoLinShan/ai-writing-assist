/**
 * 地图一级工作台。
 */
import mapView from "./mapView.js"
import { buildMapLayout } from "./mapLayoutEngine.js"
import mapQuickCreateView from "./mapQuickCreateView.js"
import { buildMapQuery, parseMapRouteContext } from "./mapRouteContext.js"
import { authorFacingStateText, mapAssetDisplay } from "../shared/assetDisplayState.js"
import { formatMapDiagnosticInfo } from "./mapDiagnosticInfo.js"
import { renderWorkspaceRail, workspaceRailKey } from "../shared/workspaceRail.js"
import {
  createMapTimelineState,
  filterTimelineItems,
  formatMapDynamicValue,
  MAP_TIMELINE_TRACKS,
  mapDynamicNormalizationLabel,
  mapDynamicTrackLabel,
  normalizeMapStateAtResponse,
  normalizeMapTimelineResponse,
  timelineAnchorPoint,
  timelineItemsAtScene,
} from "./mapTimelineProjection.js"

const RECENT_PREFIX = "novel_map_recent:"
const MAP_BATCH_ID_LIMIT = 100
const ARCHIVED_PAGE_SIZE = 20
const MAP_INBOX_PAGE_SIZE = 20

function createMapInboxFilters() {
  return {
    dynamicType: "",
    sceneId: "",
    source: "",
    confidence: "",
    eligibility: "",
  }
}

const DEFAULT_LAYERS = {
  terrain: true,
  locations: true,
  markers: true,
  events: true,
  items: true,
  territories: true,
  candidate: false,
}

function createDynamicIndexes() {
  return {
    byItemId: new Map(),
    observationsById: new Map(),
    factsById: new Map(),
    playbackEventsById: new Map(),
    queueByObjectKey: new Map(),
    candidateIdsByGroup: new Map(),
  }
}

const mapWorkspaceView = {
  _maps: [],
  _archivedMaps: [],
  _locations: [],
  _inbox: {
    loading: false,
    items: [],
    total: 0,
    hasMore: false,
    error: null,
    page: 0,
    projectId: null,
    filters: createMapInboxFilters(),
  },
  _pendingObservationEditorId: null,
  _mapById: new Map(),
  _detailMapByLocationId: new Map(),
  _mapsByParentId: new Map(),
  _mode: "overview",
  _message: null,
  _activeMapId: null,
  _activeSceneId: null,
  _focusEntityId: null,
  _focusHexQ: null,
  _focusHexR: null,
  _focusPathId: null,
  _focusLayerNodeId: null,
  _focusedDynamicItemId: null,
  _viewMode: "dashboard",
  _lowMotion: false,
  _editingState: { editing: false, dirty: false, editorLayer: "none" },
  _showHistory: false,
  _showArchivedMaps: false,
  _archivedPage: 0,
  _layers: { ...DEFAULT_LAYERS },
  _dynamicSummary: {
    mapId: null,
    loading: false,
    loaded: false,
    dashboard: null,
    observations: [],
    facts: [],
    historyItems: [],
    historyLoaded: false,
    historyLoading: false,
    error: null,
  },
  _playback: {
    loading: false,
    loaded: false,
    playback: null,
    error: null,
    playing: false,
    activeIndex: 0,
  },
  _timeline: createMapTimelineState(),
  _timelineLoadEpoch: 0,
  _timelineProjectionVersion: 0,
  _dynamicLoadEpoch: 0,
  _dynamicIndexes: createDynamicIndexes(),
  _pendingTimers: new Set(),
  _beforeUnloadHandler: null,
  _dataLoadEpoch: 0,
  _mountEpoch: 0,
  _mountPromise: Promise.resolve(),

  async onEnter() {
    this._bindBeforeUnloadGuard()
    this._showHistory = false
    this._archivedPage = 0
    this._showArchivedMaps = false
    if (this._inbox.projectId !== state.currentProjectId) {
      this._inbox = {
        ...this._inbox,
        projectId: state.currentProjectId || null,
        items: [],
        total: 0,
        hasMore: false,
        error: null,
        page: 0,
        filters: createMapInboxFilters(),
      }
    }
    await this._loadData()
  },

  canLeave() {
    return mapView.canLeave()
  },

  onLeave() {
    this._dataLoadEpoch += 1
    this._mountEpoch += 1
    this._unbindBeforeUnloadGuard()
    this._clearPendingTimers()
    this._timelineLoadEpoch += 1
    this._dynamicLoadEpoch += 1
    mapView.unmount()
    this._editingState = { editing: false, dirty: false, editorLayer: "none" }
    return true
  },

  _bindBeforeUnloadGuard() {
    if (this._beforeUnloadHandler) return
    this._beforeUnloadHandler = (event) => {
      if (!this._editingState.dirty) return
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", this._beforeUnloadHandler)
  },

  _unbindBeforeUnloadGuard() {
    if (!this._beforeUnloadHandler) return
    window.removeEventListener("beforeunload", this._beforeUnloadHandler)
    this._beforeUnloadHandler = null
  },

  async render() {
    this._clearPendingTimers()
    const hadLegacyMapMode = /(?:^|[?&])mode=map(?:&|$)/.test(window.location.hash || "")
    const context = parseMapRouteContext()
    if (context.projectId && !state.currentProjectId) {
      state.currentProjectId = context.projectId
    }
    if (context.mapId && context.mode !== "recent" && context.mode !== "overview") {
      this._mode = "map"
      this._activeMapId = context.mapId
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      this._focusHexQ = context.focusHexQ
      this._focusHexR = context.focusHexR
      this._focusPathId = context.focusPathId
      this._focusLayerNodeId = context.focusLayerNodeId
      this._viewMode = this._normalizeViewMode(context.mode)
      if (hadLegacyMapMode) {
        this._defer(() => this._replaceActiveMapRoute())
      }
    } else if (context.mode === "recent") {
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      this._focusHexQ = context.focusHexQ
      this._focusHexR = context.focusHexR
      this._focusPathId = context.focusPathId
      this._focusLayerNodeId = context.focusLayerNodeId
      if (!(this._mode === "map" && this._activeMapId)) {
        const preferredViewMode = context.sceneId || context.focusEntityId ? "live" : null
        this._defer(() => this._openRecentMap({ viewMode: preferredViewMode }))
      }
    } else if (
      context.projectId
      && !context.mapId
      && !this._activeMapId
      && context.mode !== "overview"
    ) {
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      this._focusHexQ = context.focusHexQ
      this._focusHexR = context.focusHexR
      this._focusPathId = context.focusPathId
      this._focusLayerNodeId = context.focusLayerNodeId
      this._defer(() => this._openDefaultTarget())
    }

    if (this._mode === "map" && this._activeMapId) {
      return this._renderMapWorkspace()
    }
    return this._renderOverview()
  },

  async onRendered() {
    if (this._mode === "map" && this._activeMapId) {
      await this._mountMap()
    } else {
      this._bindEvents()
    }
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

  async _loadData() {
    const epoch = ++this._dataLoadEpoch
    const projectId = state.currentProjectId
    if (!projectId) {
      this._maps = []
      this._archivedMaps = []
      this._locations = []
      this._inbox = {
        ...this._inbox,
        loading: false,
        items: [],
        total: 0,
        hasMore: false,
        error: null,
        page: 0,
      }
      this._rebuildMapIndexes()
      return true
    }
    const inboxPage = Math.max(0, Number(this._inbox?.page || 0))
    const inboxFilters = this._inbox?.filters || {}
    this._inbox = { ...this._inbox, loading: true, error: null }
    const [maps, archivedMaps, locations, inboxResult] = await Promise.all([
      this._listAllMaps("active", projectId),
      this._listAllMaps("archived", projectId),
      this._listAllLocations(projectId),
      Promise.resolve(api.world.listProjectMapObservationInbox(projectId, {
        dynamicType: inboxFilters.dynamicType,
        sceneId: inboxFilters.sceneId,
        source: inboxFilters.source,
        confidence: inboxFilters.confidence,
        eligibility: inboxFilters.eligibility,
        skip: inboxPage * MAP_INBOX_PAGE_SIZE,
        limit: MAP_INBOX_PAGE_SIZE,
      })).then((data) => ({ data })).catch((error) => ({ error })),
    ])
    if (epoch !== this._dataLoadEpoch || state.currentProjectId !== projectId) {
      return false
    }
    this._maps = maps.items || maps || []
    this._archivedMaps = archivedMaps.items || archivedMaps || []
    this._locations = locations.items || locations || []
    const inboxItems = inboxResult.data?.items || inboxResult.data || []
    const inboxTotal = Number(inboxResult.data?.total || 0)
    const lastPage = Math.max(0, Math.ceil(inboxTotal / MAP_INBOX_PAGE_SIZE) - 1)
    if (!inboxResult.error && inboxPage > lastPage && inboxPage !== 0) {
      this._inbox = { ...this._inbox, page: lastPage }
      return this._loadData()
    }
    this._inbox = {
      ...this._inbox,
      loading: false,
      projectId,
      items: inboxItems,
      total: inboxTotal,
      hasMore: Boolean(inboxResult.data?.has_more),
      error: inboxResult.error?.message || null,
    }
    this._rebuildMapIndexes()
    return true
  },

  _rebuildMapIndexes() {
    this._mapById = new Map()
    this._detailMapByLocationId = new Map()
    this._mapsByParentId = new Map()
    for (const map of this._maps || []) {
      if (map?.id) this._mapById.set(map.id, map)
      if (map?.parent_entity_id) this._detailMapByLocationId.set(map.parent_entity_id, map)
      const parentId = map?.parent_map_id || null
      if (!this._mapsByParentId.has(parentId)) this._mapsByParentId.set(parentId, [])
      this._mapsByParentId.get(parentId).push(map)
    }
  },

  _ensureMapIndexes() {
    if (this._mapById.size !== (this._maps || []).length) {
      this._rebuildMapIndexes()
    }
  },

  async _listAllLocations(projectId = state.currentProjectId) {
    const all = []
    const limit = 50
    let skip = 0
    while (true) {
      const data = await api.world.listEntities({
        novel_id: projectId,
        entity_type: "location",
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

  async _listAllMaps(status = "active", projectId = state.currentProjectId) {
    const all = []
    const limit = 500
    let skip = 0
    while (true) {
      const data = await api.world.listMaps({
        novel_id: projectId,
        status,
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

  _recentKey() {
    return `${RECENT_PREFIX}${state.currentProjectId || "none"}`
  },

  _saveRecentMap(map) {
    if (!state.currentProjectId || !map?.id) return
    localStorage.setItem(this._recentKey(), JSON.stringify({
      mapId: map.id,
      name: map.name,
      mapType: map.map_type,
      openedAt: new Date().toISOString(),
    }))
  },

  _getRecentMap() {
    const raw = localStorage.getItem(this._recentKey())
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      localStorage.removeItem(this._recentKey())
      return null
    }
  },

  _clearRecentMap() {
    localStorage.removeItem(this._recentKey())
  },

  _showOverviewFallback(message = "最近地图不可用，已返回地图总览") {
    this._message = message
    toast(this._message, "warning")
    this._mode = "overview"
    this._activeMapId = null
    this._replaceMapRoute({ mapId: null, mode: "overview" })
  },

  async _openRecentMap({
    fallbackToDefault = true,
    viewMode = null,
  } = {}) {
    const recent = this._getRecentMap()
    const canUseRouteTarget = fallbackToDefault && (this._activeSceneId || this._focusEntityId)
    if (!recent?.mapId) {
      if (canUseRouteTarget) {
        await this._openDefaultTarget({
          fallbackToRecent: false,
          preferredViewMode: viewMode,
        })
        if (this._mode === "map" && this._activeMapId) return
      }
      this._showOverviewFallback()
      return
    }
    try {
      const map = await api.world.getMap(recent.mapId, state.currentProjectId)
      const options = {
        sceneId: this._activeSceneId,
        focusEntityId: this._focusEntityId,
      }
      if (viewMode) options.viewMode = viewMode
      this._openMap(map.id, { ...options, history: "replace" })
      this._saveRecentMap(map)
    } catch {
      this._clearRecentMap()
      if (canUseRouteTarget) {
        await this._openDefaultTarget({
          fallbackToRecent: false,
          preferredViewMode: viewMode,
        })
        if (this._mode === "map" && this._activeMapId) return
      }
      this._showOverviewFallback()
    }
  },

  async _openDefaultTarget({
    fallbackToRecent = true,
    preferredViewMode = null,
  } = {}) {
    if (!state.currentProjectId) return
    try {
      const target = await api.world.getMapOpenTarget(state.currentProjectId, {
        sceneId: this._activeSceneId,
        focusEntityId: this._focusEntityId,
      })
      if (target.fallback_message) toast(target.fallback_message, "warning")
      if (target.map_id) {
        const openOptions = {
          sceneId: target.scene_id || this._activeSceneId,
          focusEntityId: target.focus_entity_id || this._focusEntityId,
          viewMode: preferredViewMode || target.mode || "dashboard",
        }
        if (target.focus_path_id) openOptions.focusPathId = target.focus_path_id
        if (target.focus_layer_node_id) openOptions.focusLayerNodeId = target.focus_layer_node_id
        this._openMap(target.map_id, { ...openOptions, history: "replace" })
      }
    } catch {
      if (fallbackToRecent) {
        await this._openRecentMap({ fallbackToDefault: false })
      } else {
        this._showOverviewFallback("地图打开目标不可用，已返回地图总览")
      }
    }
  },

  _openMap(mapId, {
    sceneId = null,
    focusEntityId = null,
    focusHexQ = null,
    focusHexR = null,
    focusPathId = null,
    focusLayerNodeId = null,
    viewMode = null,
    history = "auto",
  } = {}) {
    const hasMountedMap = this._mode === "map" && Boolean(this._activeMapId)
    const previousMapId = this._activeMapId
    const onlyViewModeChanges = hasMountedMap
      && this._activeMapId === mapId
      && sceneId == null
      && focusEntityId == null
      && focusHexQ == null
      && focusHexR == null
      && focusPathId == null
      && focusLayerNodeId == null
    if (onlyViewModeChanges) {
      if (viewMode) this._setViewMode(viewMode)
      return true
    }
    if (hasMountedMap && !mapView.canLeave()) {
      return false
    }
    if (hasMountedMap) {
      mapView.unmount()
      this._onMapEditingChange()
    }
    this._mode = "map"
    this._activeMapId = mapId
    this._activeSceneId = sceneId
    this._focusEntityId = focusEntityId
    this._focusHexQ = focusHexQ
    this._focusHexR = focusHexR
    this._focusPathId = focusPathId
    this._focusLayerNodeId = focusLayerNodeId
    if (viewMode) this._viewMode = this._normalizeViewMode(viewMode)
    this._resetDynamicSummary()
    this._ensureMapIndexes()
    const map = this._mapById.get(mapId)
    if (map) this._saveRecentMap(map)
    const shouldReplace = history === "replace"
      || (history === "auto" && hasMountedMap && previousMapId === mapId)
    this._navigateMapRoute({ replace: shouldReplace })
    return true
  },

  _openLocation(locationId) {
    this._ensureMapIndexes()
    const detailMap = this._detailMapByLocationId.get(locationId)
    const fallbackMap = detailMap || this._maps[0]
    if (!fallbackMap) {
      toast("该地点尚未绑定地图", "warning")
      return
    }
    this._openMap(fallbackMap.id, { focusEntityId: locationId })
  },

  _setLayer(layer, visible) {
    this._layers = { ...this._layers, [layer]: visible }
    if (this._mode === "map") {
      mapView._mountContext = { ...(mapView._mountContext || {}), layers: this._layers }
      mapView._redraw?.()
    }
  },

  _setViewMode(viewMode) {
    viewMode = this._normalizeViewMode(viewMode)
    if (this._mode === "map") {
      if (!mapView.canLeave()) return false
      mapView.unmount()
      this._onMapEditingChange()
      this._viewMode = viewMode
      mapView._mountContext = {
        ...(mapView._mountContext || {}),
        viewMode: this._viewMode,
        lowMotion: this._lowMotion,
      }
      mapView._redraw?.()
      this._updateViewModeControlsDom()
      this._updateWorkspaceLayoutDom()
      this._navigateMapRoute({ replace: true })
      return true
    }
    this._viewMode = viewMode
    return true
  },

  _mapRouteQuery(overrides = {}) {
    const hasMapIdOverride = Object.prototype.hasOwnProperty.call(overrides, "mapId")
    const mapId = hasMapIdOverride ? overrides.mapId : this._activeMapId
    return buildMapQuery({
      projectId: state.currentProjectId,
      mapId,
      sceneId: Object.prototype.hasOwnProperty.call(overrides, "sceneId")
        ? overrides.sceneId
        : this._activeSceneId,
      focusEntityId: Object.prototype.hasOwnProperty.call(overrides, "focusEntityId")
        ? overrides.focusEntityId
        : this._focusEntityId,
      focusHexQ: Object.prototype.hasOwnProperty.call(overrides, "focusHexQ")
        ? overrides.focusHexQ
        : this._focusHexQ,
      focusHexR: Object.prototype.hasOwnProperty.call(overrides, "focusHexR")
        ? overrides.focusHexR
        : this._focusHexR,
      focusPathId: Object.prototype.hasOwnProperty.call(overrides, "focusPathId")
        ? overrides.focusPathId
        : this._focusPathId,
      focusLayerNodeId: Object.prototype.hasOwnProperty.call(overrides, "focusLayerNodeId")
        ? overrides.focusLayerNodeId
        : this._focusLayerNodeId,
      mode: overrides.mode || (mapId ? this._viewMode : "overview"),
    })
  },

  _navigateMapRoute({ replace = false, ...overrides } = {}) {
    const query = this._mapRouteQuery(overrides)
    if (replace && typeof router.replace === "function") {
      void router.replace("map", null, query)
    } else {
      void router.navigate("map", null, true, query)
    }
  },

  _replaceMapRoute(overrides = {}) {
    this._navigateMapRoute({ ...overrides, replace: true })
  },

  _replaceActiveMapRoute(overrides = {}) {
    if (!this._activeMapId) return false
    this._replaceMapRoute(overrides)
    return true
  },

  _returnToOverview() {
    if (!mapView.canLeave()) return false
    mapView.unmount()
    this._mode = "overview"
    this._activeMapId = null
    this._activeSceneId = null
    this._focusEntityId = null
    this._focusHexQ = null
    this._focusHexR = null
    this._focusPathId = null
    this._focusLayerNodeId = null
    this._resetDynamicSummary()
    this._onMapEditingChange()
    void router.navigate("map", null, true, buildMapQuery({
      projectId: state.currentProjectId,
      mode: "overview",
    }))
    return true
  },

  _setLowMotion(enabled) {
    this._lowMotion = Boolean(enabled)
    if (this._mode === "map") {
      mapView._mountContext = {
        ...(mapView._mountContext || {}),
        viewMode: this._viewMode,
        lowMotion: this._lowMotion,
      }
      this._syncTimelineProjection()
      this._updateWorkspaceLayoutDom()
    }
  },

  _resetDynamicSummary(mapId = null) {
    this._focusedDynamicItemId = null
    this._showHistory = false
    this._dynamicSummary = {
      mapId,
      sceneId: this._activeSceneId,
      focusEntityId: this._focusEntityId,
      focusHexQ: this._focusHexQ,
      focusHexR: this._focusHexR,
      focusPathId: this._focusPathId,
      focusLayerNodeId: this._focusLayerNodeId,
      focusedDynamicItemId: this._focusedDynamicItemId,
      loading: false,
      loaded: false,
      dashboard: null,
      observations: [],
      facts: [],
      historyItems: [],
      historyLoaded: false,
      historyLoading: false,
      error: null,
    }
    this._dynamicIndexes = createDynamicIndexes()
    this._resetPlayback()
    this._resetTimeline()
  },

  _resetPlayback() {
    this._playback = {
      loading: false,
      loaded: false,
      playback: null,
      error: null,
      playing: false,
      activeIndex: 0,
    }
    this._dynamicIndexes = createDynamicIndexes()
  },

  _resetTimeline() {
    this._timelineLoadEpoch += 1
    this._timeline = createMapTimelineState()
    mapView.clearTimelineProjection?.()
  },

  _normalizeViewMode(mode) {
    if (mode === "map") return "live"
    return ["dashboard", "live", "lens"].includes(mode) ? mode : "dashboard"
  },

  _search(query) {
    const text = (query || "").trim().toLowerCase()
    if (!text) return []
    const mapResults = this._maps
      .filter((m) => (m.name || "").toLowerCase().includes(text))
      .map((m) => ({ type: "map", id: m.id, name: m.name, map: m }))
    const locationResults = this._locations
      .filter((e) => (e.name || "").toLowerCase().includes(text))
      .map((e) => ({ type: "location", id: e.id, name: e.name, entity: e }))
    return [...mapResults, ...locationResults]
  },

  _renderOverview() {
    const recent = this._getRecentMap()
    const tree = this._renderMapTree()
    const message = this._message
      ? `<div class="alert alert-warning">${esc(this._message)}</div>`
      : ""
    return `
      <div class="map-workspace">
        <div class="view-header map-toolbar">
          <div class="view-header__title">
            地图
            <span class="view-header__count">${esc(this._maps.length)} 张 · ${esc(this._locations.length)} 个地点</span>
          </div>
          <div class="view-header__actions">
            <button class="btn btn-sm btn-primary" data-action="map-open-recent">打开最近地图</button>
            <button class="btn btn-sm btn-primary" data-action="map-quick-create">快速创建</button>
            <button class="btn btn-sm" data-action="map-create-world">创建世界地图</button>
            <button class="btn btn-sm" data-action="map-toggle-archived">${this._showArchivedMaps ? "返回当前地图" : `归档地图 ${this._archivedMaps.length}`}</button>
            <input class="form-input map-overview-search" id="map-workspace-search" placeholder="搜索地图或地点" />
          </div>
        </div>
        ${message}
        ${this._showArchivedMaps ? this._renderArchivedMaps() : `<div class="map-overview-grid">
          ${this._renderProjectObservationInbox()}
          <section class="card">
            <h3>最近地图</h3>
            <p>${recent ? esc(recent.name) : "暂无最近地图"}</p>
          </section>
          <section class="card">
            <h3>空间总览</h3>
            <p>地图 ${this._maps.length} 张，地点 ${this._locations.length} 个</p>
          </section>
          <section class="card">
            <h3>地图树</h3>
            ${tree}
          </section>
          <section class="card">
            <h3>图层</h3>
            ${this._renderLayerToggles()}
          </section>
        </div>`}
        <div id="map-search-results"></div>
      </div>
    `
  },

  _filteredProjectObservationInbox() {
    const filters = this._inbox?.filters || {}
    return (this._inbox?.items || []).filter((item) => {
      const source = item.source || item.source_ref?.source || item.source_ref?.workflow || ""
      if (filters.source && source !== filters.source) return false
      if (filters.confidence === "low" && Number(item.confidence ?? 1) >= 0.6) return false
      if (filters.confidence === "high" && Number(item.confidence ?? 0) < 0.6) return false
      if (filters.eligibility === "ready" && !item.eligibility?.can_confirm) return false
      if (filters.eligibility === "missing" && item.eligibility?.can_confirm) return false
      return true
    })
  },

  _removeProjectInboxItem(observationId) {
    const total = Math.max(0, Number(this._inbox?.total || 0) - 1)
    const lastPage = Math.max(0, Math.ceil(total / MAP_INBOX_PAGE_SIZE) - 1)
    const previousPage = Number(this._inbox?.page || 0)
    this._inbox = {
      ...this._inbox,
      items: (this._inbox?.items || []).filter((entry) => entry.id !== observationId),
      total,
      page: Math.min(previousPage, lastPage),
    }
    return this._inbox.page !== previousPage
  },

  _proposalTypeLabel(item) {
    return {
      character_location: "人物位置",
      event_location: "事件位置",
      route_state: "线路状态",
      boundary: "势力范围",
      location: "位置建议",
      entity_created: "对象位置建议",
      entity_updated: "对象位置建议",
      relation_created: "关系位置建议",
      relation_updated: "关系位置建议",
    }[item.proposal_type || item.dynamic_type] || item.dynamic_type || "地图建议"
  },

  _inboxSourceLabel(item) {
    const source = item.source || item.source_ref?.source || item.source_ref?.workflow || ""
    return {
      deep_import: "深度导入",
      deep_import_delta_event: "深度导入",
      entity_created: "对象抽取",
      relation_created: "关系抽取",
      manual: "人工录入",
    }[source] || source || "来源已保留"
  },

  _inboxEvidenceText(item) {
    const raw = item.evidence_text
      || item.proposal_value?.area_description
      || item.proposal_value?.location_name
      || item.proposal_value?.path_name
      || ""
    const cleaned = String(raw).replace(
      /^(?:deep_import_delta_event|entity_created|relation_created)\s*[·:：-]\s*/,
      "",
    ).trim()
    return cleaned || "尚无可读的空间证据；可查看诊断信息或忽略此建议。"
  },

  _inboxMissingLabels(item) {
    const hasScene = item.scene_id || item.scene_index != null || item.time_anchor?.scene_index != null
    const hasChapter = item.source_chapter_id || item.source_chapter_index != null
    return (item.eligibility?.missing_item_labels || []).filter((label) => {
      const normalized = String(label || "").toLowerCase()
      if (hasScene && (normalized.includes("scene") || normalized.includes("场景"))) return false
      if (hasChapter && (normalized.includes("chapter") || normalized.includes("章节"))) return false
      return true
    }).map((label) => {
      if (String(label).includes("未选择地图")) return "选择目标地图"
      if (String(label).includes("动态字段尚未解析完整")) return "补全空间字段"
      return label
    })
  },

  _inboxConfidenceLabel(item) {
    if (item.confidence === null || item.confidence === undefined) {
      return "置信度未提供"
    }
    const confidence = Number(item.confidence)
    return Number.isFinite(confidence)
      ? `${Math.round(confidence * 100)}%`
      : "置信度未提供"
  },

  _inboxTimeLabel(item) {
    const parts = []
    const sceneIndex = item.scene_index ?? item.time_anchor?.scene_index
    if (sceneIndex !== null && sceneIndex !== undefined) {
      parts.push(`Scene ${Number(sceneIndex) + 1}`)
    }
    else if (item.scene_id) parts.push("已关联 Scene")
    const chapterIndex = item.source_chapter_index
    if (chapterIndex !== null && chapterIndex !== undefined) parts.push(`第 ${chapterIndex} 章`)
    if (item.time_anchor?.kind === "initial_state") parts.push("初始状态")
    return parts.join(" · ") || item.time_label || "时间来源待补全"
  },

  _renderProjectObservationInbox() {
    const inbox = this._inbox || {}
    const filters = inbox.filters || {}
    const items = this._filteredProjectObservationInbox()
    const sources = [...new Set([
      filters.source,
      ...(inbox.items || [])
        .map((item) => item.source || item.source_ref?.source || item.source_ref?.workflow),
    ].filter(Boolean))].sort()
    const page = Number(inbox.page || 0)
    const pageStart = inbox.total ? page * MAP_INBOX_PAGE_SIZE + 1 : 0
    const pageEnd = Math.min(inbox.total, pageStart + (inbox.items || []).length - 1)
    return `
      <section class="card map-project-inbox">
        <div class="map-inbox-heading">
          <div><h3>地图收件箱</h3><p>未分配地图的建议先在这里分流，不会进入任意地图面板。</p></div>
          <span class="badge">${esc(inbox.total || 0)} 条</span>
        </div>
        <div class="map-inbox-filters" aria-label="地图收件箱筛选">
          <select class="form-select" aria-label="按动态类型筛选" data-action="map-inbox-filter" data-filter="dynamicType">
            <option value="">全部类型</option>
            ${[["location", "人物/事件位置"], ["route_state", "线路状态"], ["boundary", "势力范围"]].map(([value, label]) => `<option value="${value}" ${filters.dynamicType === value ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <details class="map-inbox-diagnostic-filter">
            <summary>诊断筛选</summary>
            <input class="form-input" aria-label="按 Scene 原始 ID 筛选" data-diagnostic-field data-action="map-inbox-filter" data-filter="sceneId" value="${esc(filters.sceneId || "")}" placeholder="Scene 原始 ID" />
          </details>
          <select class="form-select" aria-label="按来源筛选" data-action="map-inbox-filter" data-filter="source">
            <option value="">全部来源</option>
            ${sources.map((value) => `<option value="${esc(value)}" ${filters.source === value ? "selected" : ""}>${esc(this._inboxSourceLabel({ source: value }))}</option>`).join("")}
          </select>
          <select class="form-select" aria-label="按置信度筛选" data-action="map-inbox-filter" data-filter="confidence">
            <option value="">全部置信度</option>
            <option value="low" ${filters.confidence === "low" ? "selected" : ""}>低于 60%</option>
            <option value="high" ${filters.confidence === "high" ? "selected" : ""}>60% 及以上</option>
          </select>
          <select class="form-select" aria-label="按字段完整度筛选" data-action="map-inbox-filter" data-filter="eligibility">
            <option value="">全部完整度</option>
            <option value="ready" ${filters.eligibility === "ready" ? "selected" : ""}>可确认</option>
            <option value="missing" ${filters.eligibility === "missing" ? "selected" : ""}>待补全</option>
          </select>
        </div>
        ${inbox.loading ? `<p class="map-muted-text">正在加载地图待处理项...</p>` : ""}
        ${inbox.error ? `<div class="alert alert-warning map-inbox-error">
          <span>${esc(inbox.error)}</span>
          <button class="btn btn-sm" data-action="map-inbox-retry">重试</button>
        </div>` : ""}
        ${!inbox.loading && !items.length ? `<p class="map-muted-text">当前筛选下没有未分配建议。</p>` : `
          <div class="map-inbox-list">
            ${items.map((item) => {
              const missing = this._inboxMissingLabels(item)
              const source = this._inboxSourceLabel(item)
              return `<article class="map-inbox-item">
                <div>
                  <strong>${esc(item.target_name || this._proposalTypeLabel(item))}</strong>
                  <div class="map-dynamic-meta">${esc(this._proposalTypeLabel(item))} · ${esc(source)} · ${esc(this._inboxConfidenceLabel(item))}</div>
                  <div class="map-dynamic-meta">${esc(this._inboxTimeLabel(item))}</div>
                  <div class="map-dynamic-source">${esc(this._inboxEvidenceText(item))}</div>
                  <div class="map-dynamic-meta">${missing.length ? `待补：${esc(missing.join("、"))}` : "字段完整，分配地图后可确认"}</div>
                </div>
                <div class="map-dynamic-actions">
                  <button class="btn btn-sm btn-primary" data-action="map-inbox-assign" data-id="${esc(item.id)}">分配并继续</button>
                  <button class="btn btn-sm" data-action="map-inbox-ignore" data-id="${esc(item.id)}">忽略</button>
                  <button class="btn btn-sm" data-action="map-inbox-copy-diagnostic" data-id="${esc(item.id)}">复制诊断信息</button>
                </div>
              </article>`
            }).join("")}
          </div>`}
        ${inbox.total > MAP_INBOX_PAGE_SIZE ? `<div class="map-pagination">
          <button class="btn btn-sm" data-action="map-inbox-page" data-page="${page - 1}" ${page === 0 ? "disabled" : ""}>上一页</button>
          <span>${pageStart}–${pageEnd} / ${esc(inbox.total)}</span>
          <button class="btn btn-sm" data-action="map-inbox-page" data-page="${page + 1}" ${!inbox.hasMore ? "disabled" : ""}>下一页</button>
        </div>` : ""}
      </section>
    `
  },

  _renderMapTree(parentId = null) {
    this._ensureMapIndexes()
    const children = this._mapsByParentId.get(parentId) || []
    if (!children.length) return parentId ? "" : `<p class="map-muted-text">暂无地图</p>`
    return `
      <ul class="map-tree">
        ${children.map((m) => `
          <li>
            <button class="link-button" data-action="map-open" data-id="${esc(m.id)}">
              ${esc(m.name)}
            </button>
            <button class="btn btn-xs" data-action="map-archive" data-id="${esc(m.id)}">归档</button>
            ${this._renderMapTree(m.id)}
          </li>
        `).join("")}
      </ul>
    `
  },

  _renderArchivedMaps() {
    const archivedIds = new Set(this._archivedMaps.map((map) => map.id))
    const roots = this._archivedMaps.filter(
      (map) => !map.parent_map_id || !archivedIds.has(map.parent_map_id),
    )
    if (!roots.length) {
      return `<section class="card"><h3>归档地图</h3><p class="map-muted-text">暂无归档地图</p></section>`
    }
    const pageCount = Math.max(1, Math.ceil(roots.length / ARCHIVED_PAGE_SIZE))
    this._archivedPage = Math.min(this._archivedPage, pageCount - 1)
    const pageRoots = roots.slice(
      this._archivedPage * ARCHIVED_PAGE_SIZE,
      (this._archivedPage + 1) * ARCHIVED_PAGE_SIZE,
    )
    return `
      <section class="card map-archived-list">
        <h3>归档地图</h3>
        <p class="map-muted-text">归档地图不参与地图树、定位和编辑；恢复会连同其完整子树执行。</p>
        ${pageRoots.map((map) => `
          <div class="map-archived-row">
            <span><strong>${esc(map.name)}</strong><small>${esc(map.map_type)} · ${map.archived_at ? esc(new Date(map.archived_at).toLocaleString()) : "归档时间未知"}</small></span>
            <button class="btn btn-sm" data-action="map-restore" data-id="${esc(map.id)}">恢复子树</button>
          </div>
        `).join("")}
        <div class="map-pagination">
          <button class="btn btn-sm" data-action="map-archive-page" data-page="${this._archivedPage - 1}" ${this._archivedPage === 0 ? "disabled" : ""}>上一页</button>
          <span>第 ${this._archivedPage + 1} / ${pageCount} 页，共 ${roots.length} 个归档子树</span>
          <button class="btn btn-sm" data-action="map-archive-page" data-page="${this._archivedPage + 1}" ${this._archivedPage + 1 >= pageCount ? "disabled" : ""}>下一页</button>
        </div>
      </section>
    `
  },

  _renderLayerToggles() {
    const labels = {
      terrain: "地形",
      locations: "地点",
      markers: "人物",
      events: "事件",
      items: "物品",
      territories: "势力",
      candidate: "待处理",
    }
    return Object.entries(labels).map(([key, label]) => `
      <label class="map-layer-toggle">
        <input type="checkbox" data-action="map-layer-toggle" data-layer="${esc(key)}"
          ${this._layers[key] ? "checked" : ""} />
        ${esc(label)}
      </label>
    `).join("")
  },

  _renderMapWorkspace() {
    const map = this._mapById.get(this._activeMapId) || {}
    return `
      <div class="map-workspace map-workspace-active ${this._editingState.editing ? "is-map-editing" : ""}">
        <div class="view-header map-toolbar">
          <div class="view-header__title">
            <button class="btn btn-sm" data-action="map-overview">← 返回总览</button>
            <span>${esc(map.name || "地图")}</span>
          </div>
          <div class="view-header__actions">
            <button class="btn btn-sm btn-primary" data-action="map-quick-create">快速创建</button>
            ${this._renderViewModeControls()}
            ${this._renderLayerToggles()}
          </div>
        </div>
        <div class="map-workspace-body">
          <main class="map-workspace-main">
            <div id="map-semantic-band" class="map-semantic-band">
              ${this._renderSemanticBand()}
            </div>
            <div id="map-root" class="map-root"></div>
          </main>
          ${renderWorkspaceRail({
            key: workspaceRailKey("map", state.currentProjectId, "dynamic-summary"),
            title: "动态摘要",
            className: "map-dynamic-rail workspace-rail--right",
            defaultOpen: typeof window === "undefined" || window.innerWidth > 1099,
            content: `<aside id="map-dynamic-summary" class="map-dynamic-panel">${this._renderDynamicSummary()}</aside>`,
          })}
        </div>
      </div>
    `
  },

  _renderViewModeControls() {
    const modes = [
      ["dashboard", "世界动态总控台"],
      ["live", "活地图"],
      ["lens", "叙事透镜"],
    ]
    return `
      <div id="map-view-controls" class="map-view-controls" role="group" aria-label="地图视图">
        ${modes.map(([mode, label]) => `
          <button class="btn btn-sm map-view-mode${this._viewMode === mode ? " is-active" : ""}"
            data-action="map-view-mode" data-view-mode="${mode}">
            ${esc(label)}
          </button>
        `).join("")}
        <label class="map-low-motion-toggle">
          <input type="checkbox" data-action="map-low-motion-toggle" ${this._lowMotion ? "checked" : ""} />
          低动效
        </label>
      </div>
    `
  },

  _buildLayout() {
    const dashboard = this._dynamicSummary?.dashboard
    const bandRect = document.getElementById("map-semantic-band")?.getBoundingClientRect?.()
    const rootRect = document.getElementById("map-root")?.getBoundingClientRect?.()
    const measuredWidth = bandRect?.width || rootRect?.width || window.innerWidth || 720
    return buildMapLayout({
      dashboard: dashboard || {},
      viewport: {
        width: Math.max(320, Math.min(960, measuredWidth)),
        height: 360,
      },
      viewMode: this._viewMode,
      focusEntityId: this._focusEntityId,
      sceneId: this._activeSceneId,
      lowMotion: this._lowMotion,
    })
  },

  _renderSemanticBand() {
    if (this._editingState.editing) return ""
    const dashboard = this._dynamicSummary?.dashboard
    if (!dashboard) return ""
    const layout = this._buildLayout()
    const bubbles = layout.semanticBubbles || []
    if (!bubbles.length) return ""
    return `
      <div class="map-semantic-bubbles ${layout.motion === "low" ? "is-low-motion" : ""}">
        ${bubbles.map((bubble) => `
          <button class="map-semantic-bubble" data-action="map-open-dynamic-item" data-id="${esc(bubble.itemId)}"
            style="left:${bubble.box.x}px;top:${bubble.box.y}px;width:${bubble.box.width}px;">
            <span>${esc(bubble.label)}</span>
          </button>
        `).join("")}
      </div>
    `
  },

  _renderDynamicSummary() {
    const summary = this._dynamicSummary || {}
    if (summary.loading) {
      return `<p class="map-muted-text">正在加载世界动态...</p>`
    }
    if (summary.error) {
      return `<div class="alert alert-warning">${esc(summary.error)}</div>`
    }
    const dashboard = summary.dashboard
    if (!dashboard) {
      return `<p class="map-muted-text">暂无世界动态</p>`
    }
    const dashboardItems = dashboard.dynamic_queue || []
    const activeItems = dashboardItems.filter((item) => !mapAssetDisplay(item).isHistory)
    const historyItems = [
      ...dashboardItems.filter((item) => mapAssetDisplay(item).isHistory),
      ...(summary.historyItems || []),
    ]
    const historyCount = historyItems.length
    const queue = this._showHistory ? [...activeItems, ...historyItems] : activeItems
    const inspector = this._focusedInspector(dashboard)
    const candidateCount = queue.filter((item) => mapAssetDisplay(item).displayState === "review").length
    const factCount = queue.filter((item) => item.item_kind === "fact" && !mapAssetDisplay(item).isHistory).length
    return `
      <div class="map-dynamic-header">
        <h3>${esc(dashboard.title || "世界动态总控台")}</h3>
        <span>${candidateCount} 待处理 · ${factCount} 已采用</span>
        <button class="btn btn-sm" data-action="map-toggle-history" ${summary.historyLoading ? "disabled" : ""}>
          ${summary.historyLoading ? "加载历史…" : this._showHistory ? "隐藏历史" : ((summary.historyLoaded || historyCount) ? `查看历史 ${historyCount}` : "查看历史")}
        </button>
      </div>
      ${this._renderFirstVisualLayer(dashboard.first_visual_layer || {})}
      ${this._renderTimelinePanel()}
      ${queue.length
        ? `<div class="map-dynamic-section">
            <h4>动态队列</h4>
            ${queue.slice(0, 8).map((item) => this._renderQueueItem(item)).join("")}
          </div>`
        : `<p class="map-muted-text">暂无动态队列</p>`}
      ${this._renderInspector(inspector)}
      ${this._renderBatchGroups(dashboard.batch_groups || [])}
    `
  },

  _renderFirstVisualLayer(layer) {
    const risks = (layer.top_risks || []).map(authorFacingStateText)
    const characters = layer.main_characters || []
    return `
      <section class="map-dashboard-priority">
        <div>
          <span>主线危机</span>
          <strong>${esc(authorFacingStateText(layer.main_crisis) || "暂无主线危机")}</strong>
        </div>
        <div>
          <span>主要对象</span>
          <strong>${esc(characters.length ? characters.join("、") : "暂无焦点对象")}</strong>
        </div>
        <div>
          <span>最重要风险</span>
          <strong>${esc(risks.length ? risks.join("；") : "暂无高风险")}</strong>
        </div>
      </section>
    `
  },

  _renderQueueItem(item) {
    const display = mapAssetDisplay(item)
    const statusLabel = display.isHistory && item.status_label
      ? item.status_label
      : display.label
    const canReview = item.item_kind === "observation" && display.displayState === "review"
    const riskClass = item.risk_level === "danger" ? " is-danger" : item.risk_level === "warning" ? " is-warning" : ""
    return `
      <article class="map-dynamic-item${riskClass}" data-action="map-open-dynamic-item" data-id="${esc(item.item_id)}">
        <div class="map-dynamic-title">${esc(item.title || "地图事实")}</div>
        <div class="map-dynamic-meta">
          ${esc(item.time_label || "时间未确定")} · ${esc(statusLabel)}
          ${item.confidence !== null && item.confidence !== undefined ? ` · 置信度 ${Math.round(item.confidence * 100)}%` : ""}
          ${item.normalization_state ? ` · ${esc(mapDynamicNormalizationLabel(item.normalization_state))}` : ""}
        </div>
        <div class="map-dynamic-source">${esc(item.source_summary || "来源未确定")}</div>
        ${display.attentionReasons.length ? `<div class="map-dynamic-attention">${display.attentionReasons.map((reason) => `<span class="badge badge-warning">${esc(reason)}</span>`).join("")}</div>` : ""}
        ${canReview
          ? `<div class="map-dynamic-actions">
              <button class="btn btn-sm btn-primary" data-action="map-confirm-observation" data-id="${esc(item.item_id)}">采用</button>
              <button class="btn btn-sm" data-action="map-ignore-observation" data-id="${esc(item.item_id)}">忽略</button>
            </div>`
          : ""}
      </article>
    `
  },

  _historyQueueItem(item, itemKind) {
    const sceneIndex = item.scene_index ?? item.time_anchor?.scene_index
    const chapterIndex = item.source_chapter_index
    return {
      ...item,
      item_id: item.item_id || item.id,
      item_kind: itemKind,
      title: item.title || item.target_name || item.dynamic_type || "历史地图记录",
      object_type: item.object_type || item.target_entity_type || item.dynamic_type || "world",
      time_label: item.time_label
        || (sceneIndex != null ? `Scene ${sceneIndex}` : "")
        || (chapterIndex != null ? `第 ${chapterIndex} 章` : "")
        || "时间未确定",
      source_summary: item.source_summary || item.evidence_text || "来源已保留",
      status_label: itemKind === "fact"
        ? this._factStatusLabel(item.fact_status)
        : this._reviewStateLabel(item.review_state),
    }
  },

  async _toggleHistory() {
    if (this._showHistory) {
      this._showHistory = false
      this._updateWorkspaceLayoutDom()
      return
    }
    if (!this._activeMapId || !state.currentProjectId) return
    if (!this._dynamicSummary?.historyLoaded) {
      this._dynamicSummary.historyLoading = true
      this._updateWorkspaceLayoutDom()
      try {
        const [observationPage, rolledBackFactPage, deprecatedFactPage] = await Promise.all([
          api.world.listMapObservations(
            this._activeMapId,
            state.currentProjectId,
            "ignored",
          ),
          api.world.listMapFacts(
            this._activeMapId,
            state.currentProjectId,
            "rolled_back",
          ),
          api.world.listMapFacts(
            this._activeMapId,
            state.currentProjectId,
            "deprecated",
          ),
        ])
        const observations = observationPage?.items || observationPage || []
        const factsById = new Map()
        for (const factPage of [rolledBackFactPage, deprecatedFactPage]) {
          for (const fact of factPage?.items || factPage || []) {
            const id = fact?.id || fact?.item_id
            if (id) factsById.set(String(id), fact)
          }
        }
        const facts = Array.from(factsById.values())
        const historyObservations = observations.map((item) => this._historyQueueItem(item, "observation"))
        const historyFacts = facts.map((item) => this._historyQueueItem(item, "fact"))
        this._dynamicSummary.historyItems = [...historyObservations, ...historyFacts]
        this._dynamicSummary.observations = [
          ...(this._dynamicSummary.observations || []),
          ...historyObservations,
        ]
        this._dynamicSummary.facts = [
          ...(this._dynamicSummary.facts || []),
          ...historyFacts,
        ]
        this._dynamicSummary.historyLoaded = true
        this._rebuildDynamicIndexes()
      } catch (err) {
        toast(`历史记录加载失败：${err.message || "未知错误"}`, "warning")
        return
      } finally {
        this._dynamicSummary.historyLoading = false
      }
    }
    this._showHistory = true
    this._updateWorkspaceLayoutDom()
  },

  _renderInspector(inspector) {
    if (!inspector) return ""
    const candidates = inspector.ai_candidates || []
    const facts = inspector.map_facts || []
    const conflicts = inspector.conflicts || []
    const evidence = inspector.source_evidence || []
    const timeline = inspector.timeline || []
    const actions = inspector.available_actions || []
    const inspectorStatus = candidates.some((item) => mapAssetDisplay(item).displayState === "review")
      ? "待处理"
      : (facts.some((item) => !mapAssetDisplay(item).isHistory) ? "已采用" : "待判断")
    return `
      <div class="map-dynamic-section map-inspector">
        <h4>检查器</h4>
        <article class="map-dynamic-item">
          <div class="map-dynamic-title">${esc(inspector.title || "暂无世界动态")}</div>
          <div class="map-dynamic-meta">${esc(inspectorStatus)}</div>
          ${inspector.type_label || inspector.location_label || inspector.spatial_anchor_label
            ? `<div class="map-dynamic-meta">
                ${[inspector.type_label, inspector.location_label, inspector.spatial_anchor_label].filter(Boolean).map((text) => esc(text)).join(" · ")}
              </div>`
            : ""}
          <div class="map-dynamic-source">${esc(inspector.summary || "")}</div>
          <div class="map-inspector-counts">
            <span>待处理 ${candidates.filter((item) => mapAssetDisplay(item).displayState === "review").length}</span>
            <span>已采用 ${facts.filter((item) => !mapAssetDisplay(item).isHistory).length}</span>
            <span>注意 ${conflicts.length}</span>
          </div>
          ${evidence.length
            ? `<ul class="map-evidence-list">${evidence.slice(0, 3).map((text) => `<li>${esc(text)}</li>`).join("")}</ul>`
            : ""}
          ${timeline.length
            ? `<div class="map-inspector-timeline">
                ${timeline.slice(0, 4).map((item) => `
                  <button class="link-button" data-action="map-open-dynamic-item" data-id="${esc(item.item_id)}">
                    ${esc(item.time_label || "时间未确定")} · ${esc(item.title || "地图对象")}
                  </button>
                `).join("")}
              </div>`
            : ""}
          ${actions.length
            ? `<div class="map-inspector-actions">
                ${actions.map((action) => `<span>${esc(this._actionLabel(action))}</span>`).join("")}
              </div>`
            : ""}
        </article>
      </div>
    `
  },

  _focusedInspector(dashboard) {
    if (!dashboard) return null
    if (!this._focusedDynamicItemId || this._focusEntityId) {
      return dashboard.inspector
    }
    if (dashboard.inspector?.debug_ref?.id === this._focusedDynamicItemId) {
      return dashboard.inspector
    }
    let indexes = this._dynamicIndex()
    let focus = indexes.byItemId.get(this._focusedDynamicItemId)
    if (!focus) {
      indexes = this._rebuildDynamicIndexes()
      focus = indexes.byItemId.get(this._focusedDynamicItemId)
    }
    if (!focus) return dashboard.inspector
    const objectKey = this._dynamicObjectKey(focus)
    const timeline = indexes.queueByObjectKey.get(objectKey) || []
    const candidates = timeline.filter((item) => item.item_kind === "observation")
    const facts = timeline.filter((item) => item.item_kind === "fact")
    const conflicts = candidates.filter((item) => item.review_state === "conflicted")
    const evidence = timeline
      .map((item) => item.source_summary)
      .filter(Boolean)
      .slice(0, 5)
    const availableActions = []
    if (candidates.length) availableActions.push("confirm", "ignore", "conflict")
    if (facts.length) availableActions.push("rollback", "deprecated")
    return {
      title: focus.title || "地图对象",
      status_label: focus.status_label || "待判断",
      summary: focus.change_summary || focus.source_summary || dashboard.inspector?.summary,
      object_type: focus.object_type || null,
      object_name: focus.title || null,
      type_label: focus.type_label || null,
      location_label: focus.location_label || null,
      spatial_anchor_label: focus.spatial_anchor_label || null,
      timeline,
      available_actions: availableActions,
      map_facts: facts,
      ai_candidates: candidates,
      conflicts,
      source_evidence: evidence,
    }
  },

  _dynamicObjectKey(item) {
    if (item.target_entity_id) return `entity:${item.target_entity_id}`
    return [
      item.title || "",
      item.object_type || item.dynamic_type || "unknown",
    ].join("|")
  },

  _rebuildDynamicIndexes() {
    const indexes = createDynamicIndexes()
    const queue = [
      ...(this._dynamicSummary?.dashboard?.dynamic_queue || []),
      ...(this._dynamicSummary?.historyItems || []),
    ]
    for (const item of queue) {
      if (item.item_id) indexes.byItemId.set(item.item_id, item)
      if (item.id) indexes.byItemId.set(item.id, item)
      const objectKey = this._dynamicObjectKey(item)
      if (!indexes.queueByObjectKey.has(objectKey)) {
        indexes.queueByObjectKey.set(objectKey, [])
      }
      indexes.queueByObjectKey.get(objectKey).push(item)
      const groupKey = item.object_type || item.dynamic_type || "unknown"
      if (item.item_kind === "observation" && mapAssetDisplay(item).displayState === "review") {
        if (!indexes.candidateIdsByGroup.has(groupKey)) {
          indexes.candidateIdsByGroup.set(groupKey, [])
        }
        indexes.candidateIdsByGroup.get(groupKey).push(item.item_id)
      }
    }
    for (const item of this._dynamicSummary?.observations || []) {
      if (item.item_id) indexes.observationsById.set(item.item_id, item)
      if (item.id) indexes.observationsById.set(item.id, item)
      if (item.item_id) indexes.byItemId.set(item.item_id, item)
    }
    for (const item of this._dynamicSummary?.facts || []) {
      if (item.item_id) indexes.factsById.set(item.item_id, item)
      if (item.id) indexes.factsById.set(item.id, item)
      if (item.item_id) indexes.byItemId.set(item.item_id, item)
    }
    for (const event of this._playback?.playback?.events || []) {
      if (event.event_id) indexes.playbackEventsById.set(event.event_id, event)
      if (event.id) indexes.playbackEventsById.set(event.id, event)
    }
    this._dynamicIndexes = indexes
    return indexes
  },

  _dynamicIndex() {
    if (!this._dynamicIndexes) return this._rebuildDynamicIndexes()
    return this._dynamicIndexes
  },

  _dynamicObservation(id) {
    let item = this._dynamicIndex().observationsById.get(id)
    if (item) return item
    return this._rebuildDynamicIndexes().observationsById.get(id)
  },

  _dynamicFact(id) {
    let item = this._dynamicIndex().factsById.get(id)
    if (item) return item
    return this._rebuildDynamicIndexes().factsById.get(id)
  },

  _renderBatchGroups(groups) {
    if (!groups.length) return ""
    return `
      <div class="map-dynamic-section">
        <h4>批量修改</h4>
        ${groups.slice(0, 6).map((group) => `
          <div class="map-batch-row">
            <span>${esc(group.group_label)}</span>
            <strong>${group.count}</strong>
            <small>${this._pendingGroupCount(group)} 待处理 · ${group.confirmed_count} 已采用</small>
            ${this._renderBatchTimeGroups(group.time_groups || [])}
            <div class="map-batch-actions">
              ${this._renderBatchButton(group, "confirm", "采用待处理项")}
              ${this._renderBatchButton(group, "ignore", "忽略待处理项")}
              ${this._renderBatchButton(group, "conflict", "标记冲突")}
            </div>
          </div>
        `).join("")}
      </div>
    `
  },

  _renderBatchTimeGroups(timeGroups) {
    if (!timeGroups.length) return ""
    return `
      <div class="map-batch-times">
        ${timeGroups.slice(0, 4).map((timeGroup) => `
          <small>${esc(timeGroup.time_label || "时间未确定")} · ${esc(this._pendingGroupCount(timeGroup))} 待处理 · ${esc(timeGroup.confirmed_count || 0)} 已采用</small>
        `).join("")}
      </div>
    `
  },

  _renderBatchButton(group, action, label) {
    const pendingCount = this._pendingGroupCount(group)
    const disabled = pendingCount > 0 ? "" : "disabled"
    return `<button class="btn btn-sm" data-action="map-batch-review" data-group="${esc(group.group_key)}" data-review-action="${esc(action)}" ${disabled}>${esc(pendingCount > 0 ? label : "无待处理项")}</button>`
  },

  _pendingGroupCount(group = {}) {
    return Number(group.pending_count ?? group.review_count ?? group.candidate_count ?? 0) || 0
  },

  _renderTimelinePanel() {
    const timeline = this._timeline || createMapTimelineState()
    if (timeline.loading) {
      return `<div class="map-dynamic-section"><h4>Scene 时间轴</h4><p class="map-muted-text">正在组装正式世界状态...</p></div>`
    }
    const data = timeline.data
    const scenes = data?.scenes || []
    if (!data || !scenes.length) {
      const fallback = this._renderPlaybackPanel()
      const note = timeline.error
        ? `<div class="map-timeline-fallback"><span>类型化时间轴暂不可用，已保留旧播放。</span><button class="btn btn-sm" data-action="map-timeline-retry">重试</button></div>`
        : ""
      return `${note}${fallback}`
    }

    const activeIndex = Math.max(0, Math.min(timeline.activeIndex || 0, scenes.length - 1))
    const activeScene = scenes[activeIndex]
    const sceneIndex = activeScene?.scene_index
    const stateAt = timeline.stateAt || { items: [], conflicts: [] }
    const stateItems = filterTimelineItems(stateAt.items, timeline.selectedTracks)
    const candidates = timeline.includeCandidates
      ? timelineItemsAtScene(data.candidates, sceneIndex, timeline.selectedTracks)
      : []
    const conflicts = timelineItemsAtScene(
      [...(data.conflicts || []), ...(stateAt.conflicts || [])],
      sceneIndex,
      timeline.selectedTracks,
    )

    return `
      <div class="map-dynamic-section map-timeline-panel${this._lowMotion ? " is-low-motion" : ""}">
        <div class="map-playback-header">
          <h4>Scene 时间轴</h4>
          <button class="btn btn-sm" data-action="${timeline.playing ? "map-timeline-stop" : "map-timeline-start"}" ${this._editingState.editing ? "disabled" : ""}>
            ${timeline.playing ? "暂停" : "播放"}
          </button>
        </div>
        ${this._renderTimelineControls(scenes, activeIndex)}
        ${timeline.stateLoading
          ? `<p class="map-muted-text">正在加载 Scene ${esc(sceneIndex)} 的正式状态...</p>`
          : timeline.stateError
            ? `<div class="alert alert-warning">${esc(timeline.stateError)}</div>`
            : this._renderTimelineStateItems(stateItems, sceneIndex)}
        ${this._renderTimelineCandidates(candidates, sceneIndex)}
        ${this._renderTimelineConflicts(conflicts)}
        ${this._renderTimelineUntypedFacts(data.untyped_facts || [], sceneIndex)}
        ${data.has_more || stateAt.has_more
          ? `<p class="map-timeline-page-note">还有更多记录，请缩小 Scene 范围后查看。</p>`
          : ""}
        ${(data.undated_facts || []).length
          ? `<p class="map-timeline-page-note">另有 ${esc(data.undated_facts.length)} 条正式事实尚未确定 Scene，不参与当前状态。</p>`
          : ""}
      </div>
      ${this._renderContinuityIssues(data.continuity_issues || [])}
    `
  },

  _renderTimelineControls(scenes, activeIndex) {
    const timeline = this._timeline
    const active = scenes[activeIndex] || scenes[0]
    const sceneSummary = active
      ? `${Number(active.delta_count || 0)} 项变化 · ${Number(active.conflict_count || 0)} 个冲突`
      : "暂无变化"
    return `
      <div class="map-timeline-controls">
        <div class="map-timeline-stepper">
          <button class="btn btn-sm" data-action="map-timeline-step" data-delta="-1" ${activeIndex <= 0 ? "disabled" : ""} aria-label="上一个 Scene">←</button>
          <select class="form-select" data-action="map-timeline-scene-select" aria-label="选择 Scene">
            ${scenes.map((scene, index) => `
              <option value="${index}" ${index === activeIndex ? "selected" : ""}>Scene ${esc(scene.scene_index)}</option>
            `).join("")}
          </select>
          <button class="btn btn-sm" data-action="map-timeline-step" data-delta="1" ${activeIndex >= scenes.length - 1 ? "disabled" : ""} aria-label="下一个 Scene">→</button>
        </div>
        <input class="map-timeline-cursor" type="range" min="0" max="${Math.max(0, scenes.length - 1)}" value="${activeIndex}"
          data-action="map-timeline-cursor" aria-label="Scene 时间游标" />
        <div class="map-timeline-caption">
          <span>Scene ${esc(active?.scene_index ?? "-")}</span>
          <span>${esc(sceneSummary)}</span>
        </div>
        <div class="map-timeline-options">
          <label>
            播放节奏
            <select class="form-select" data-action="map-timeline-speed">
              ${[[2400, "舒缓"], [1600, "标准"], [900, "紧凑"]].map(([value, label]) => `
                <option value="${value}" ${Number(timeline.speedMs) === value ? "selected" : ""}>${label}</option>
              `).join("")}
            </select>
          </label>
          <label class="map-timeline-candidate-toggle">
            <input type="checkbox" data-action="map-timeline-candidates" ${timeline.includeCandidates ? "checked" : ""} />
            待处理预览
          </label>
        </div>
        <div class="map-timeline-tracks" role="group" aria-label="时间轴轨道">
          ${MAP_TIMELINE_TRACKS.map((track) => `
            <label>
              <input type="checkbox" data-action="map-timeline-track" data-track="${track.key}"
                ${timeline.selectedTracks[track.key] !== false ? "checked" : ""} />
              ${esc(track.label)}
            </label>
          `).join("")}
        </div>
        ${this._lowMotion ? `<span class="map-timeline-motion-note">低动效：逐 Scene 切换</span>` : ""}
      </div>
    `
  },

  _renderTimelineStateItems(items, sceneIndex) {
    if (!items.length) {
      return `<div class="map-timeline-state"><h5>正式状态</h5><p class="map-muted-text">Scene ${esc(sceneIndex)} 暂无已结构化的正式状态。</p></div>`
    }
    return `
      <div class="map-timeline-state">
        <h5>正式状态</h5>
        ${items.slice(0, 8).map((item) => `
          <article class="map-timeline-state-item is-canonical">
            <div class="map-dynamic-title">${esc(item.target_name || item.dynamic_type || "地图对象")}</div>
            <div class="map-dynamic-meta">${esc(mapDynamicTrackLabel(item))} · 已采用 · ${esc(mapDynamicNormalizationLabel(item.normalization_state))}</div>
            <div class="map-dynamic-source">${esc(formatMapDynamicValue(item.normalized_value, "正式状态已记录"))}</div>
          </article>
        `).join("")}
        ${items.length > 8 ? `<p class="map-timeline-page-note">当前 Scene 另有 ${esc(items.length - 8)} 项正式状态。</p>` : ""}
      </div>
    `
  },

  _renderTimelineCandidates(candidates, sceneIndex) {
    if (!this._timeline.includeCandidates) {
      return `<p class="map-timeline-candidate-note">待处理内容默认隐藏，不会进入 Scene ${esc(sceneIndex)} 的正式状态。</p>`
    }
    if (!candidates.length) {
      return `<div class="map-timeline-candidates"><h5>待处理预览</h5><p class="map-muted-text">当前 Scene 没有待处理候选。</p></div>`
    }
    return `
      <div class="map-timeline-candidates">
        <h5>待处理预览</h5>
        ${candidates.slice(0, 6).map((item) => `
            <article class="map-timeline-state-item is-candidate">
              <div class="map-dynamic-title">${esc(item.target_name || item.title || item.dynamic_type || "待处理地图对象")}</div>
              <div class="map-dynamic-meta">${esc(mapDynamicTrackLabel(item))} · 只读预览 · ${esc(mapDynamicNormalizationLabel(item.normalization_state))}</div>
              <div class="map-dynamic-source">${esc(formatMapDynamicValue(item.normalized_value, item.evidence_text || "等待作者判断"))}</div>
            </article>
          `).join("")}
      </div>
    `
  },

  _renderTimelineConflicts(conflicts) {
    if (!conflicts.length) return ""
    return `
      <div class="map-timeline-conflicts">
        <h5>同一 Scene 冲突</h5>
        ${conflicts.slice(0, 5).map((item) => `
          <article class="map-timeline-state-item is-conflict">
            <div class="map-dynamic-title">${esc(item.target_name || item.dynamic_type || "地图状态冲突")}</div>
            <div class="map-dynamic-source">存在 ${esc((item.values || []).length || 2)} 个互相矛盾的正式值，当前状态未替作者做选择。</div>
          </article>
        `).join("")}
      </div>
    `
  },

  _renderTimelineUntypedFacts(facts, sceneIndex) {
    if (this._timeline.selectedTracks.world === false) return ""
    const current = (facts || []).filter((fact) => (
      Number(fact.scene_index ?? fact.time_anchor?.scene_index) === Number(sceneIndex)
    ))
    if (!current.length) return ""
    return `
      <div class="map-timeline-untyped">
        <h5>尚未结构化（仅展示）</h5>
        ${current.slice(0, 5).map((fact) => `
          <article class="map-timeline-state-item is-untyped">
            <div class="map-dynamic-title">${esc(fact.target_name || fact.dynamic_type || "旧地图事实")}</div>
            <div class="map-dynamic-meta">世界动态 · ${esc(mapDynamicNormalizationLabel(fact.normalization_state || "untyped"))}</div>
            <div class="map-dynamic-source">${esc(fact.evidence_text || fact.source_summary || "原始来源已保留")}</div>
          </article>
        `).join("")}
      </div>
    `
  },

  _renderContinuityIssues(issues) {
    if (!issues.length) return ""
    return `
      <div class="map-dynamic-section map-continuity-panel">
        <div class="map-playback-header">
          <h4>空间连续性</h4>
          <span>${esc(issues.length)} 项待核对</span>
        </div>
        ${issues.slice(0, 8).map((issue) => {
          const riskClass = issue.severity === "danger" || issue.severity === "error"
            ? " is-danger"
            : " is-warning"
          const sceneRange = issue.from_scene_index === issue.to_scene_index
            ? `Scene ${issue.to_scene_index}`
            : `Scene ${issue.from_scene_index} → ${issue.to_scene_index}`
          return `
            <article class="map-continuity-issue${riskClass}">
              <div class="map-dynamic-title">${esc(issue.target_name || this._continuityIssueLabel(issue.issue_type))}</div>
              <div class="map-dynamic-meta">${esc(sceneRange)}${issue.distance_hex == null ? "" : ` · ${esc(issue.distance_hex)} 格`}</div>
              <div class="map-dynamic-source">${esc(issue.message || this._continuityIssueLabel(issue.issue_type))}</div>
              <div class="map-dynamic-actions">
                <button class="btn btn-sm" data-action="map-continuity-focus" data-side="from" data-issue="${esc(issue.issue_key)}">定位起点</button>
                <button class="btn btn-sm" data-action="map-continuity-focus" data-side="to" data-issue="${esc(issue.issue_key)}">定位终点</button>
                <button class="btn btn-sm" data-action="map-continuity-evidence" data-issue="${esc(issue.issue_key)}">查看证据</button>
                ${issue.target_entity_id
                  ? `<button class="btn btn-sm" data-action="map-continuity-open-entity" data-entity="${esc(issue.target_entity_id)}">打开对象</button>`
                  : ""}
                ${issue.suggested_observation
                  ? `<button class="btn btn-sm btn-primary" data-action="map-continuity-explain" data-issue="${esc(issue.issue_key)}">补充解释</button>`
                  : ""}
              </div>
            </article>
          `
        }).join("")}
      </div>
    `
  },

  _continuityIssueLabel(issueType) {
    return {
      same_scene_conflict: "同一 Scene 的位置冲突",
      missing_anchor: "位置锚点缺失",
      route_unknown: "路线信息不足",
      no_route: "未找到连通路线",
      blocked_route: "移动经过受阻线路",
      path_revision_mismatch: "线路版本已经变化",
    }[issueType] || "空间连续性待核对"
  },

  _renderPlaybackPanel() {
    const playbackState = this._playback || {}
    if (playbackState.loading) {
      return `<div class="map-dynamic-section"><h4>电影化播放</h4><p class="map-muted-text">正在加载播放事件...</p></div>`
    }
    if (playbackState.error) {
      return `<div class="map-dynamic-section"><h4>电影化播放</h4><div class="alert alert-warning">${esc(playbackState.error)}</div></div>`
    }
    const playback = playbackState.playback
    if (!playback) return ""
    const events = playback.events || []
    const tracks = playback.tracks || []
    const active = events[playbackState.activeIndex] || events[0]
    return `
      <div class="map-dynamic-section map-playback-panel">
        <div class="map-playback-header">
          <h4>电影化播放</h4>
          <button class="btn btn-sm" data-action="${playbackState.playing ? "map-playback-stop" : "map-playback-start"}">
            ${playbackState.playing ? "停止" : "播放"}
          </button>
        </div>
        ${tracks.length
          ? `<div class="map-playback-tracks">
              ${tracks.map((track) => `<span>${esc(track.label)} ${track.count}</span>`).join("")}
            </div>`
          : `<p class="map-muted-text">暂无可播放动态</p>`}
        ${active
          ? `<article class="map-dynamic-item ${active.risk_level === "danger" ? "is-danger" : active.risk_level === "warning" ? "is-warning" : ""}" data-action="map-open-dynamic-item" data-id="${esc(active.event_id)}">
              <div class="map-dynamic-title">${esc(active.title)}</div>
              <div class="map-dynamic-meta">${esc(active.time_label)} · ${esc(this._mapStatusLabel(active))}</div>
              <div class="map-dynamic-source">${esc(active.change_summary || active.source_summary || "")}</div>
              ${mapView.pathRevisionMismatch(active.spatial_anchor)
                ? `<div class="map-path-revision-warning">线路已更新，回放保留原事实快照</div>`
                : ""}
            </article>`
          : ""}
      </div>
    `
  },

  _mountMap() {
    const epoch = ++this._mountEpoch
    const context = {
      mapId: this._activeMapId,
      sceneId: this._activeSceneId,
      focusEntityId: this._focusEntityId,
      focusHexQ: this._focusHexQ,
      focusHexR: this._focusHexR,
      focusPathId: this._focusPathId,
      focusLayerNodeId: this._focusLayerNodeId,
      viewMode: this._viewMode,
      lowMotion: this._lowMotion,
      mode: this._activeMapId ? "map" : "overview",
      layers: this._layers,
      onMapOpened: (map) => this._saveRecentMap(map),
      onEditingChange: (editingState) => this._onMapEditingChange(editingState),
      onOpenMap: (mapId) => this._openMap(mapId, { viewMode: "live" }),
      onBackOverview: () => this._returnToOverview(),
      onSceneChange: (sceneId) => this._changeSceneRoute(sceneId),
      onLayerFocusChange: (focusLayerNodeId) => {
        this._focusLayerNodeId = focusLayerNodeId || null
        this._replaceActiveMapRoute({ focusLayerNodeId: this._focusLayerNodeId })
      },
      onOpenEntity: (entityId) => {
        state.selectedItem = entityId
        router.navigate("world", "objects")
      },
    }
    this._mountPromise = this._mountPromise.catch(() => {}).then(async () => {
      if (epoch !== this._mountEpoch) return false
      mapView.unmount()
      await mapView.mount("map-root", context)
      if (epoch !== this._mountEpoch) {
        mapView.unmount()
        return false
      }
      this._loadDynamicSummary()
      this._bindEvents()
      return true
    })
    return this._mountPromise
  },

  _changeSceneRoute(sceneId) {
    if (!this._activeMapId || !mapView.canLeave()) return false
    mapView.unmount()
    this._onMapEditingChange()
    this._activeSceneId = sceneId || null
    this._replaceActiveMapRoute({ sceneId: this._activeSceneId })
    return true
  },

  _onMapEditingChange(editingState = {}) {
    const wasEditing = Boolean(this._editingState?.editing)
    this._editingState = {
      editing: Boolean(editingState.editing),
      dirty: Boolean(editingState.dirty),
      editorLayer: editingState.editorLayer || "none",
    }
    document.querySelector(".map-workspace-active")?.classList.toggle("is-map-editing", this._editingState.editing)
    const band = document.getElementById("map-semantic-band")
    if (band) band.style.display = this._editingState.editing ? "none" : ""
    document.querySelector(".map-dynamic-rail")?.classList.toggle("is-map-editing", this._editingState.editing)
    if (this._editingState.editing && !wasEditing) {
      this._timeline = { ...this._timeline, playing: false }
      this._playback = { ...this._playback, playing: false }
      mapView.clearTimelineProjection?.()
      mapView.clearPathFocus?.({ preserveSelection: true })
    } else if (!this._editingState.editing) {
      this._syncTimelineProjection({ fresh: true })
    }
  },

  async _loadDynamicSummary({ force = false } = {}) {
    if (!state.currentProjectId || !this._activeMapId) return
    if (
      !force
      && this._dynamicSummary?.mapId === this._activeMapId
      && this._dynamicSummary?.sceneId === this._activeSceneId
      && this._dynamicSummary?.focusEntityId === this._focusEntityId
      && this._dynamicSummary?.focusedDynamicItemId === this._focusedDynamicItemId
      && this._dynamicSummary?.loaded
      && !this._dynamicSummary?.error
      && !this._playback?.error
    ) {
      return
    }
    const projectId = state.currentProjectId
    const mapId = this._activeMapId
    const sceneId = this._activeSceneId
    const focusEntityId = this._focusEntityId
    const focusedDynamicItemId = this._focusedDynamicItemId
    const loadEpoch = ++this._dynamicLoadEpoch
    const isCurrentRequest = () => (
      this._dynamicLoadEpoch === loadEpoch
      && state.currentProjectId === projectId
      && this._activeMapId === mapId
      && this._activeSceneId === sceneId
      && this._focusEntityId === focusEntityId
      && this._focusedDynamicItemId === focusedDynamicItemId
    )
    this._dynamicSummary = {
      mapId,
      sceneId,
      focusEntityId,
      focusedDynamicItemId,
      loading: true,
      loaded: false,
      dashboard: null,
      observations: [],
      facts: [],
      historyItems: [],
      historyLoaded: false,
      historyLoading: false,
      error: null,
    }
    this._playback = {
      loading: true,
      loaded: false,
      playback: null,
      error: null,
      playing: false,
      activeIndex: 0,
    }
    const timelinePreferences = this._timeline || createMapTimelineState()
    this._timeline = {
      ...createMapTimelineState(),
      includeCandidates: Boolean(timelinePreferences.includeCandidates),
      speedMs: Number(timelinePreferences.speedMs || 1600),
      selectedTracks: { ...timelinePreferences.selectedTracks },
      loading: true,
    }
    this._updateDynamicSummaryDom()
    try {
      const [dashboard, playback, timelineResult, observationPage] = await Promise.all([
        api.world.getMapDashboard(
          mapId,
          projectId,
          sceneId,
          focusEntityId,
          focusedDynamicItemId,
        ),
        api.world.getMapPlayback(
          mapId,
          projectId,
          sceneId,
          focusEntityId,
          true,
        ),
        Promise.resolve(api.world.getMapTimeline(mapId, projectId, {
          focusEntityId,
          includeCandidates: this._timeline.includeCandidates || undefined,
          limit: 500,
        })).then((data) => ({ data })).catch((error) => ({ error })),
        api.world.listMapObservations(mapId, projectId, null),
      ])
      if (!isCurrentRequest()) return
      const dashboardObservations = new Map((dashboard.dynamic_queue || [])
        .filter((item) => item.item_kind === "observation")
        .map((item) => [String(item.item_id), item]))
      const observationItems = observationPage?.items
        || (Array.isArray(observationPage) ? observationPage : [...dashboardObservations.values()])
      const observationsById = new Map(dashboardObservations)
      for (const item of observationItems) {
        const id = String(item.id || item.item_id)
        observationsById.set(id, { ...(observationsById.get(id) || {}), ...item })
      }
      const observations = [...observationsById.values()].map((item) => ({
        ...item,
        item_id: item.id || item.item_id,
        item_kind: "observation",
        title: item.target_name || item.title || item.dynamic_type || "地图待处理项",
      }))
      this._dynamicSummary = {
        mapId,
        sceneId,
        focusEntityId,
        focusedDynamicItemId,
        loading: false,
        loaded: true,
        dashboard,
        observations,
        facts: (dashboard.dynamic_queue || [])
          .filter((item) => item.item_kind === "fact"),
        historyItems: [],
        historyLoaded: false,
        historyLoading: false,
        error: null,
      }
      this._playback = {
        loading: false,
        loaded: true,
        playback,
        error: null,
        playing: false,
        activeIndex: 0,
      }
      if (timelineResult.data) {
        const data = normalizeMapTimelineResponse(timelineResult.data)
        const previousScene = timelinePreferences.sceneIndex
        let activeIndex = data.scenes.findIndex((item) => item.scene_index === previousScene)
        if (activeIndex < 0) activeIndex = Math.max(0, data.scenes.length - 1)
        this._timeline = {
          ...this._timeline,
          loading: false,
          loaded: true,
          error: null,
          data,
          activeIndex,
          sceneIndex: data.scenes[activeIndex]?.scene_index ?? null,
          playing: false,
        }
      } else {
        this._timeline = {
          ...this._timeline,
          loading: false,
          loaded: true,
          error: timelineResult.error?.message || "Scene 时间轴暂不可用",
          data: null,
          playing: false,
        }
      }
      this._rebuildDynamicIndexes()
      if (this._timeline.sceneIndex !== null) {
        await this._loadTimelineStateAt(this._timeline.sceneIndex, {
          updateDom: false,
          isCurrentRequest,
        })
      } else {
        mapView.clearTimelineProjection?.()
      }
      const pendingObservationId = this._pendingObservationEditorId
      const pendingObservation = pendingObservationId
        ? this._dynamicObservation(pendingObservationId)
        : null
      if (pendingObservation) {
        this._pendingObservationEditorId = null
        this._defer(() => this._showDynamicEditForm(pendingObservation))
      }
    } catch (err) {
      if (!isCurrentRequest()) return
      this._dynamicSummary = {
        mapId,
        sceneId,
        focusEntityId,
        focusedDynamicItemId,
        loading: false,
        loaded: true,
        dashboard: null,
        observations: [],
        facts: [],
        historyItems: [],
        historyLoaded: false,
        historyLoading: false,
        error: "地图动态事实暂不可用",
      }
      this._playback = {
        loading: false,
        loaded: true,
        playback: null,
        error: "世界动态播放暂不可用",
        playing: false,
        activeIndex: 0,
      }
      this._timeline = {
        ...this._timeline,
        loading: false,
        loaded: true,
        error: "Scene 时间轴暂不可用",
        data: null,
        playing: false,
      }
      mapView.clearTimelineProjection?.()
      this._rebuildDynamicIndexes()
      toast(`地图动态事实暂不可用：${err.message || "加载失败"}`, "warning")
    }
    this._updateDynamicSummaryDom()
  },

  async _loadTimelineStateAt(sceneIndex, {
    updateDom = true,
    isCurrentRequest = null,
  } = {}) {
    if (!state.currentProjectId || !this._activeMapId || sceneIndex == null) return false
    const projectId = state.currentProjectId
    const mapId = this._activeMapId
    const epoch = ++this._timelineLoadEpoch
    this._timeline = {
      ...this._timeline,
      stateLoading: true,
      stateError: null,
      sceneIndex: Number(sceneIndex),
    }
    if (updateDom) this._updateDynamicSummaryDom()
    try {
      const response = await api.world.getMapStateAt(mapId, projectId, Number(sceneIndex), {
        focusEntityId: this._focusEntityId,
        limit: 500,
      })
      if (
        epoch !== this._timelineLoadEpoch
        || state.currentProjectId !== projectId
        || this._activeMapId !== mapId
        || this._timeline.sceneIndex !== Number(sceneIndex)
        || (typeof isCurrentRequest === "function" && !isCurrentRequest())
      ) {
        return false
      }
      this._timeline = {
        ...this._timeline,
        stateAt: normalizeMapStateAtResponse(response),
        stateLoading: false,
        stateError: null,
      }
      this._syncTimelineProjection({ fresh: true })
      if (updateDom) this._updateDynamicSummaryDom()
      return true
    } catch (err) {
      if (epoch !== this._timelineLoadEpoch) return false
      this._timeline = {
        ...this._timeline,
        stateAt: null,
        stateLoading: false,
        stateError: err.message || "Scene 正式状态暂不可用",
      }
      mapView.clearTimelineProjection?.()
      if (updateDom) this._updateDynamicSummaryDom()
      return false
    }
  },

  _syncTimelineProjection({ fresh = false } = {}) {
    const timeline = this._timeline
    if (!timeline?.data || timeline.sceneIndex == null || timeline.stateError) {
      mapView.clearTimelineProjection?.()
      return false
    }
    if (fresh) this._timelineProjectionVersion += 1
    return mapView.setTimelineProjection?.({
      projectionToken: timeline.stateAt?.projection_token
        || timeline.data?.projection_token
        || `local-${this._timelineProjectionVersion}`,
      sceneIndex: timeline.sceneIndex,
      stateItems: timeline.stateAt?.items || [],
      conflicts: timeline.stateAt?.conflicts || [],
      deltas: timeline.data.deltas || [],
      candidates: timeline.data.candidates || [],
      includeCandidates: Boolean(timeline.includeCandidates),
      selectedTracks: { ...timeline.selectedTracks },
      lowMotion: this._lowMotion,
    }) || false
  },

  async _setTimelineScenePosition(position, { fromPlayback = false } = {}) {
    const scenes = this._timeline?.data?.scenes || []
    if (!scenes.length) return false
    const nextPosition = Math.max(0, Math.min(Number(position) || 0, scenes.length - 1))
    const nextSceneIndex = scenes[nextPosition].scene_index
    this._timeline = {
      ...this._timeline,
      activeIndex: nextPosition,
      sceneIndex: nextSceneIndex,
      stateAt: null,
      stateError: null,
      playing: fromPlayback ? this._timeline.playing : false,
    }
    mapView.clearPathFocus?.()
    this._syncTimelineProjection({ fresh: true })
    this._updateDynamicSummaryDom()
    return this._loadTimelineStateAt(nextSceneIndex)
  },

  async _stepTimeline(delta, { fromPlayback = false } = {}) {
    const scenes = this._timeline?.data?.scenes || []
    if (!scenes.length) return false
    const current = Math.max(0, Math.min(this._timeline.activeIndex || 0, scenes.length - 1))
    const next = current + Number(delta || 0)
    if (next < 0 || next >= scenes.length) {
      if (fromPlayback) this._stopTimeline()
      return false
    }
    return this._setTimelineScenePosition(next, { fromPlayback })
  },

  _startTimeline() {
    if (this._editingState.editing) {
      toast("请先结束地图编辑，再播放 Scene 时间轴", "info")
      return false
    }
    const scenes = this._timeline?.data?.scenes || []
    if (!scenes.length) return this._startPlayback()
    const restart = this._timeline.activeIndex >= scenes.length - 1
    this._timeline = {
      ...this._timeline,
      playing: true,
      activeIndex: restart ? 0 : this._timeline.activeIndex,
      sceneIndex: restart ? scenes[0].scene_index : this._timeline.sceneIndex,
    }
    this._updateDynamicSummaryDom()
    const begin = restart
      ? this._loadTimelineStateAt(scenes[0].scene_index)
      : Promise.resolve(true)
    Promise.resolve(begin).then((loaded) => {
      if (loaded && this._timeline.playing) this._scheduleTimelineAdvance()
      else if (!loaded) this._timeline = { ...this._timeline, playing: false }
    })
    return true
  },

  _stopTimeline({ clearProjection = false } = {}) {
    this._timeline = { ...this._timeline, playing: false }
    if (clearProjection) mapView.clearTimelineProjection?.()
    this._updateDynamicSummaryDom()
    return true
  },

  _scheduleTimelineAdvance() {
    const delay = Math.max(600, Number(this._timeline.speedMs || 1600))
    const timer = setTimeout(async () => {
      this._pendingTimers.delete(timer)
      if (!this._timeline?.playing || this._editingState.editing) return
      const moved = await this._stepTimeline(1, { fromPlayback: true })
      if (moved && this._timeline.playing) this._scheduleTimelineAdvance()
      else if (!moved) this._stopTimeline()
    }, delay)
    this._pendingTimers.add(timer)
  },

  _setTimelineTrack(track, enabled) {
    if (!MAP_TIMELINE_TRACKS.some((item) => item.key === track)) return false
    this._timeline = {
      ...this._timeline,
      selectedTracks: {
        ...this._timeline.selectedTracks,
        [track]: Boolean(enabled),
      },
      playing: false,
    }
    this._syncTimelineProjection()
    this._updateDynamicSummaryDom()
    return true
  },

  async _setTimelineCandidates(enabled) {
    this._timeline = {
      ...this._timeline,
      includeCandidates: Boolean(enabled),
      playing: false,
    }
    await this._loadDynamicSummary({ force: true })
    return true
  },

  _findContinuityIssue(issueKey) {
    return (this._timeline?.data?.continuity_issues || [])
      .find((issue) => issue.issue_key === issueKey)
  },

  _continuityAnchor(issue, side) {
    const facts = new Set(issue?.source_fact_ids || [])
    const deltas = (this._timeline?.data?.deltas || []).filter((delta) => (
      (delta.source_fact_ids || []).some((id) => facts.has(id))
    ))
    const delta = side === "from" ? deltas[0] : deltas.at(-1)
    const primary = side === "from"
      ? delta?.spatial_anchor_before
      : delta?.spatial_anchor_after
    const fallback = side === "from"
      ? issue?.suggested_observation?.source_ref?.from_spatial_anchor
      : issue?.suggested_observation?.spatial_anchor
    return primary || fallback || null
  },

  _focusContinuityIssue(issueKey, side) {
    const issue = this._findContinuityIssue(issueKey)
    if (!issue) return false
    const anchor = this._continuityAnchor(issue, side)
    const pathId = (issue.path_ids || [])[side === "from" ? 0 : (issue.path_ids || []).length - 1]
    const pathFocused = pathId ? mapView.focusPath?.(pathId) : false
    const anchorFocused = anchor ? mapView.focusTimelineAnchor?.(anchor) : false
    if (!pathFocused && !anchorFocused) {
      toast("该端点尚无可定位的地图锚点", "info")
      return false
    }
    toast(side === "from" ? "已定位移动起点" : "已定位移动终点", "info")
    return true
  },

  _showContinuityEvidence(issueKey) {
    const issue = this._findContinuityIssue(issueKey)
    if (!issue) return
    const evidence = (issue.source_fact_ids || [])
      .map((id) => this._dynamicFact(id))
      .filter(Boolean)
      .map((fact) => fact.evidence_text || fact.source_summary)
      .filter(Boolean)
    const sceneRange = issue.from_scene_index === issue.to_scene_index
      ? `Scene ${issue.to_scene_index}`
      : `Scene ${issue.from_scene_index} → ${issue.to_scene_index}`
    const body = `
      <div class="map-object-info">
        <div class="map-detail-section"><div class="map-detail-label">检查结果</div><div class="map-detail-value">${esc(issue.message || this._continuityIssueLabel(issue.issue_type))}</div></div>
        <div class="map-detail-section"><div class="map-detail-label">Scene</div><div class="map-detail-value">${esc(sceneRange)}</div></div>
        ${issue.distance_hex == null ? "" : `<div class="map-detail-section"><div class="map-detail-label">地图距离</div><div class="map-detail-value">${esc(issue.distance_hex)} 格；未换算为叙事时间</div></div>`}
        <div class="map-detail-section"><div class="map-detail-label">来源证据</div><div class="map-detail-value">${evidence.length ? evidence.slice(0, 5).map((text) => `<p>${esc(text)}</p>`).join("") : `已保留 ${esc((issue.source_fact_ids || []).length)} 条来源事实`}</div></div>
      </div>
    `
    showModalHtml("空间连续性证据", body, [{ text: "关闭", class: "btn", handler: () => closeModal() }])
  },

  _showContinuityExplanationForm(issueKey) {
    const issue = this._findContinuityIssue(issueKey)
    const suggestion = issue?.suggested_observation
    if (!issue || !suggestion) return
    const form = `
      <p>${esc(issue.message || this._continuityIssueLabel(issue.issue_type))}</p>
      <div class="form-group">
        <label>作者解释</label>
        <textarea class="form-textarea" id="map-continuity-explanation" rows="4" placeholder="例如：角色使用了城内密道，因此未经过已封锁的桥。"></textarea>
      </div>
      <div class="form-group">
        <label>补充证据（可选）</label>
        <textarea class="form-textarea" id="map-continuity-evidence" rows="3" placeholder="填写相关正文或设定依据"></textarea>
      </div>
      <p class="map-muted-text">保存后只生成待处理候选，不会直接改写正式世界状态。</p>
    `
    showModalHtml("补充移动解释", form, [{
      text: "保存为待处理",
      class: "btn-primary",
      handler: async () => {
        const explanation = document.getElementById("map-continuity-explanation")?.value?.trim() || ""
        const evidence = document.getElementById("map-continuity-evidence")?.value?.trim() || ""
        if (!explanation) {
          toast("请先填写作者解释", "warning")
          return false
        }
        const payload = JSON.parse(JSON.stringify(suggestion))
        payload.review_state = "candidate"
        payload.value_json = {
          ...(payload.value_json || {}),
          schema_version: 1,
          type: "semantic",
          relation_type: "movement_explanation",
          summary: explanation,
        }
        payload.evidence_text = evidence || explanation
        await api.world.createMapObservation(this._activeMapId, payload, state.currentProjectId)
        closeModal()
        toast("移动解释已进入待处理，确认后才会成为正式事实", "success")
        this._timeline.includeCandidates = true
        await this._loadDynamicSummary({ force: true })
        return true
      },
    }])
  },

  _updateDynamicSummaryDom() {
    this._updateWorkspaceLayoutDom()
  },

  _updateWorkspaceLayoutDom() {
    const el = document.getElementById("map-dynamic-summary")
    if (el) el.innerHTML = this._renderDynamicSummary()
    const band = document.getElementById("map-semantic-band")
    if (band) band.innerHTML = this._renderSemanticBand()
  },

  _updateViewModeControlsDom() {
    const el = document.getElementById("map-view-controls")
    if (!el) return
    el.querySelectorAll("[data-view-mode]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.viewMode === this._viewMode)
    })
    const lowMotionInput = el.querySelector("[data-action='map-low-motion-toggle']")
    if (lowMotionInput) lowMotionInput.checked = this._lowMotion
    this._bindViewModeControls()
  },

  _bindViewModeControls() {
    document.querySelectorAll("[data-action='map-view-mode']").forEach((button) => {
      button.onclick = (event) => {
        event.preventDefault()
        event.stopPropagation()
        this._setViewMode(button.dataset.viewMode)
      }
    })
  },

  async _confirmObservation(id) {
    const item = this._dynamicObservation(id)
    if (item?.eligibility && !item.eligibility.can_confirm) {
      const missing = item.eligibility.missing_item_labels?.join("、") || "结构化字段"
      toast(`还不能采用，请先补全：${missing}`, "warning")
      return false
    }
    const name = item?.title || item?.target_name || "地图映射"
    return confirmAction(`采用地图映射“${name}”并写入当前有效事实？`, async () => {
      try {
        await api.world.confirmMapObservation(
          this._activeMapId,
          id,
          state.currentProjectId,
          item?.updated_at,
        )
        toast("地图事实已采用", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          this._applyObservationConflictLatest(latest, item)
          toast("该建议已更新；已加载服务器最新摘要，请核对后重试", "warning")
          return false
        }
        toast(`采用失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  async _ignoreObservation(id) {
    const item = this._dynamicObservation(id)
    const name = item?.title || item?.target_name || "地图映射"
    return confirmAction(`忽略地图映射「${name}」？`, async () => {
      try {
        await api.world.ignoreMapObservation(
          this._activeMapId,
          id,
          state.currentProjectId,
          item?.updated_at,
        )
        toast("地图映射已忽略", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          this._applyObservationConflictLatest(latest, item)
          toast("该建议已更新；已加载服务器最新摘要，请核对后重试", "warning")
          return false
        }
        toast(`忽略失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  _startPlayback() {
    const events = this._playback?.playback?.events || []
    if (!events.length) {
      toast("暂无可播放动态", "info")
      return
    }
    this._playback = {
      ...this._playback,
      playing: true,
      activeIndex: 0,
    }
    this._updateWorkspaceLayoutDom()
    this._syncPlaybackPathFocus()
    this._schedulePlaybackAdvance()
  },

  _stopPlayback() {
    this._playback = {
      ...this._playback,
      playing: false,
    }
    mapView.clearPathFocus()
    this._updateWorkspaceLayoutDom()
  },

  _syncPlaybackPathFocus() {
    const event = this._playback?.playback?.events?.[this._playback.activeIndex]
      || this._playback?.playback?.events?.[0]
    const anchor = event?.spatial_anchor || {}
    const pathId = anchor.path_id || event?.path_id || null
    if (!pathId) {
      mapView.clearPathFocus()
      return false
    }
    return mapView.focusPath(
      pathId,
      anchor.focus_layer_node_id || anchor.layer_node_id || event?.layer_node_id || null,
    )
  },

  _findDynamicItem(id) {
    const indexes = this._dynamicIndex()
    return indexes.byItemId.get(id) || indexes.playbackEventsById.get(id)
      || this._rebuildDynamicIndexes().byItemId.get(id)
      || this._dynamicIndexes.playbackEventsById.get(id)
  },

  _actionLabel(action) {
    return {
      confirm: "可采用",
      ignore: "可忽略",
      conflict: "可标记冲突",
      rollback: "可回滚",
      deprecated: "可废弃",
    }[action] || action
  },

  _mapStatusLabel(item = {}) {
    if (item.item_kind || item.review_state || item.fact_status) return mapAssetDisplay(item).label
    return {
      "待确认": "待处理",
      "候选": "待处理",
      "已确认": "已采用",
      "冲突": "待处理",
    }[item.status_label] || item.status_label || "待判断"
  },

  _showDynamicObjectInfo(id) {
    const item = this._findDynamicItem(id)
    if (!item) return
    const title = item.title || "地图对象"
    const display = mapAssetDisplay(item)
    const status = display.isHistory && item.status_label
      ? item.status_label
      : display.label
    const time = item.time_label || "时间未确定"
    const summary = item.change_summary || item.source_summary || "暂无来源摘要"
    const evidence = item.evidence_text || "未提供正文证据"
    const workflow = item.source_ref?.workflow
      || item.source_ref?.source
      || item.source_workflow
      || "来源工作流已记录"
    const confidence = item.confidence == null
      ? "未提供"
      : `${Math.round(Number(item.confidence) * 100)}%`
    const actions = this._dynamicObjectActions(item)
    const detailLine = [item.type_label, item.location_label, item.spatial_anchor_label]
      .filter(Boolean)
      .join(" · ")
    const body = `
      <div class="map-object-info">
        ${detailLine
          ? `<div class="map-detail-section">
              <div class="map-detail-label">对象</div>
              <div class="map-detail-value">${esc(detailLine)}</div>
            </div>`
          : ""}
        <div class="map-detail-section">
          <div class="map-detail-label">时间</div>
          <div class="map-detail-value">${esc(time)}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">状态</div>
          <div class="map-detail-value">${esc(status)}${item.normalization_state ? ` · ${esc(mapDynamicNormalizationLabel(item.normalization_state))}` : ""}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">来源</div>
          <div class="map-detail-value">${esc(summary)}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">证据</div>
          <div class="map-detail-value">${esc(evidence)}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">来源工作流</div>
          <div class="map-detail-value">${esc(workflow)}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">原始置信度</div>
          <div class="map-detail-value">${esc(confidence)}</div>
        </div>
      </div>
    `
    showModalHtml(esc(title), body, [
      {
        text: "修改",
        class: "btn-primary",
        handler: () => {
          closeModal()
          this._showDynamicEditForm(item)
        },
      },
      ...actions,
      {
        text: "复制诊断信息",
        class: "btn",
        handler: () => this._copyDynamicDiagnostic(item),
      },
      {
        text: "打开检查器",
        class: "btn",
        handler: () => {
          closeModal()
          this._openFocusedInspector(item.target_entity_id || null, item.item_id || item.event_id)
        },
      },
    ])
  },

  _showDynamicEditForm(item) {
    if (!item) return
    const isFact = item.item_kind === "fact"
    const statusValue = isFact ? (item.fact_status || "confirmed") : (item.review_state || "candidate")
    const targetEntities = (mapView.timelineEntityOptions?.() || [])
    const knownTargetIds = new Set(targetEntities.map((entity) => entity.id))
    const unknownTarget = item.target_entity_id && !knownTargetIds.has(item.target_entity_id)
      ? `<option value="${esc(item.target_entity_id)}" data-entity-type="${esc(item.target_entity_type || "")}" selected>当前已关联对象</option>`
      : ""
    const eligibility = item.eligibility || {}
    const observationFields = isFact ? "" : `
      <div class="form-group">
        <label>目标名称</label>
        <input class="form-input" id="map-object-edit-target-name" aria-label="目标名称" value="${esc(item.target_name || item.title || "")}" />
      </div>
      <div class="form-group">
        <label>关联对象</label>
        <select class="form-select" id="map-object-edit-target-entity" aria-label="关联对象">
          <option value="">未指定</option>
          ${unknownTarget}
          ${targetEntities.map((entity) => `<option value="${esc(entity.id)}" data-entity-type="${esc(entity.entityType || "")}" ${entity.id === item.target_entity_id ? "selected" : ""}>${esc(entity.name)} · ${esc(entity.entityType || "对象")}</option>`).join("")}
        </select>
      </div>
      <div class="map-observation-eligibility ${eligibility.can_confirm ? "is-ready" : "is-missing"}">
        ${eligibility.can_confirm
          ? "字段已完整，保存后可采用。"
          : `待补：${esc((eligibility.missing_item_labels || []).join("、") || "请补全结构化字段")}`}
      </div>
      <div class="map-object-readonly-context" role="note" aria-label="来源信息（只读）">
        <div><strong>时间：</strong>${esc(item.time_label || "时间未确定")}</div>
        <div><strong>位置：</strong>${esc(item.location_label || item.spatial_anchor_label || "位置未确定")}</div>
        <div><strong>证据：</strong>${esc(item.evidence_text || item.source_summary || "未提供正文证据")}</div>
        <div><strong>来源：</strong>${esc(item.source_ref?.workflow || item.source_ref?.source || item.source_workflow || "来源工作流已记录")}</div>
        <div><strong>原始置信度：</strong>${esc(item.confidence == null ? "未提供" : `${Math.round(Number(item.confidence) * 100)}%`)}</div>
      </div>
      ${this._renderTypedDynamicValueEditor(item)}
    `
    const formHtml = `
      <div class="form-group">
        <label>对象</label>
        <input class="form-input" value="${esc(item.title || "地图对象")}" disabled />
      </div>
      <div class="form-group">
        <label>展示状态</label>
        <select class="form-select" id="map-object-edit-status" aria-label="展示状态">
          ${isFact
            ? ["confirmed", "rolled_back", "deprecated"].map((value) => `<option value="${value}" ${value === statusValue ? "selected" : ""}>${esc(this._factStatusLabel(value))}</option>`).join("")
            : [
                ["candidate", "待处理"],
                ["ignored", "历史（已忽略）"],
                ["conflicted", "待处理 · 存在冲突"],
              ].map(([value, label]) => `<option value="${value}" ${value === statusValue ? "selected" : ""}>${esc(label)}</option>`).join("")}
        </select>
      </div>
      ${observationFields}
    `
    showModalHtml("修改地图对象", formHtml, [{
      text: "保存",
      class: "btn-primary",
      handler: async () => {
        const nextStatus = document.getElementById("map-object-edit-status")?.value
        if (isFact) {
          closeModal()
          await this._updateFactStatus(item.item_id, nextStatus)
        } else {
          let payload
          try {
            payload = this._readObservationEditPayload(nextStatus, item)
          } catch (err) {
            toast(err.message || "地图待处理项字段格式不正确", "error")
            return
          }
          await this._saveObservationEdit(item, payload)
        }
      },
    }])
    this._bindTypedDynamicValueEditor()
  },

  async _copyDynamicDiagnostic(item) {
    const text = formatMapDiagnosticInfo(item, { mapId: this._activeMapId })
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable")
      await navigator.clipboard.writeText(text)
      toast("诊断信息已复制", "success")
      return true
    } catch {
      toast("无法访问剪贴板，请检查浏览器权限", "warning")
      return false
    }
  },

  _renderTypedDynamicValueEditor(item) {
    const types = [
      ["location", "人物/对象位置"],
      ["route_state", "线路状态"],
      ["status", "对象状态"],
      ["boundary", "势力范围"],
      ["resource", "资源控制"],
      ["terrain", "地形变化"],
      ["crisis", "危机扩散"],
      ["semantic", "语义关联"],
    ]
    const supported = new Set(types.map(([value]) => value).filter(Boolean))
    const proposalValue = item.proposal_value
      || (item.value_json?.payload_kind === "proposal" ? item.value_json : null)
    const rawValue = item.normalized_value
      || (proposalValue ? this._proposalToTypedValue(item, proposalValue) : item.value_json)
      || {}
    const typedValue = rawValue.schema_version === 1 && supported.has(rawValue.type)
      ? rawValue
      : null
    if (!typedValue) {
      return `
        <section class="map-typed-dynamic-editor" role="note">
          <div class="map-typed-dynamic-heading"><strong>结构化动态</strong><span>旧版数据</span></div>
          <p class="map-legacy-dynamic-note">该记录仍使用旧版格式，本批只读保留；请等待后续结构化迁移后再编辑动态值。</p>
        </section>
      `
    }
    const selectedType = typedValue.type
    const isEventLocation = item.proposal_type === "event_location"
    const selectedTypeLabel = types.find(([value]) => value === selectedType)?.[1] || "结构化动态"
    const entitiesById = new Map()
    for (const entity of [
      ...(mapView.timelineEntityOptions?.() || []),
      ...(this._locations || []).map((location) => ({
        id: location.id,
        name: location.name,
        entityType: "location",
      })),
    ]) {
      if (entity?.id && entity?.name) entitiesById.set(entity.id, entity)
    }
    const entities = [...entitiesById.values()]
    const paths = mapView.timelinePathOptions?.() || []
    const knownEntityIds = new Set(entities.map((entry) => entry.id))
    const unknownRelatedOptions = (typedValue?.related_entity_ids || [])
      .filter((id) => !knownEntityIds.has(id))
      .map((id) => `<option value="${esc(id)}" selected>当前已关联对象</option>`)
      .join("")
    const optionList = (items, selected, emptyLabel) => {
      const values = new Set(items.map((entry) => entry.id))
      const unknown = selected && !values.has(selected)
        ? `<option value="${esc(selected)}" selected>当前已关联对象</option>`
        : ""
      return `
        <option value="">${esc(emptyLabel)}</option>
        ${unknown}
        ${items.map((entry) => `<option value="${esc(entry.id)}" ${entry.id === selected ? "selected" : ""}>${esc(entry.name)}</option>`).join("")}
      `
    }
    const entityOptions = (selected, emptyLabel = "请选择对象") => (
      optionList(entities, selected, emptyLabel)
    )
    const locationOptions = (selected) => optionList(
      entities.filter((entry) => entry.entityType === "location"),
      selected,
      "未指定地点",
    )
    const pathOptions = (selected) => optionList(paths, selected, "未指定线路")
    const hexText = (value) => (value?.hexes || [])
      .map((hex) => `${hex.hex_q},${hex.hex_r}`)
      .join("\n")
    const scalarType = typedValue?.type === "status"
      ? (typedValue.value === null
          ? "null"
          : typeof typedValue.value === "number"
            ? "number"
            : typeof typedValue.value === "boolean"
              ? "boolean"
              : "string")
      : "string"
    const fieldset = (type, content) => selectedType === type
      ? `<div class="map-typed-dynamic-fields" data-map-dynamic-fields="${type}">${content}</div>`
      : ""
    const normalizationState = item.normalization_state
      || (typedValue ? "typed" : "untyped")
    return `
      <section class="map-typed-dynamic-editor">
        <div class="map-typed-dynamic-heading">
          <strong>结构化动态</strong>
          <span>${esc(mapDynamicNormalizationLabel(normalizationState))}</span>
        </div>
        <p class="map-muted-text">类型：${esc(selectedTypeLabel)}。${proposalValue ? "这是未解析建议，请用选择器补全正式对象。" : "保存时继续由后端 schema 校验。"}</p>
        <input type="hidden" id="map-object-edit-value-type" value="${esc(selectedType)}" data-initial-type="${esc(selectedType)}" data-initialized="true" />
        ${fieldset("location", `
          <div class="form-group"><label for="map-typed-location-entity">所在地点</label><select class="form-select" id="map-typed-location-entity">${locationOptions(typedValue?.location_entity_id)}</select></div>
          ${isEventLocation ? "" : `<div class="form-group"><label for="map-typed-location-path">使用线路（可选）</label><select class="form-select" id="map-typed-location-path">${pathOptions(typedValue?.path_id)}</select></div>`}
          <div class="form-group"><label for="map-typed-location-mode">移动方式</label><select class="form-select" id="map-typed-location-mode">${["walk", "ride", "vehicle", "rail", "water", "flight", "teleport", "unknown"].map((value) => `<option value="${value}" ${(typedValue?.movement_mode || "unknown") === value ? "selected" : ""}>${esc({ walk: "步行", ride: "骑乘", vehicle: "载具", rail: "轨道", water: "水路", flight: "飞行", teleport: "传送", unknown: "未知" }[value])}</option>`).join("")}</select></div>
          <div class="form-group"><label for="map-typed-location-state">位置状态</label><input class="form-input" id="map-typed-location-state" maxlength="64" value="${esc(typedValue?.state || "present")}" /></div>
        `)}
        ${fieldset("route_state", `
          <div class="form-group"><label for="map-typed-route-path">线路</label><select class="form-select" id="map-typed-route-path">${pathOptions(typedValue?.path_id)}</select></div>
          <div class="form-group"><label for="map-typed-route-state">线路状态</label><select class="form-select" id="map-typed-route-state">${[["open", "开放"], ["restricted", "受限"], ["blocked", "阻断"]].map(([value, label]) => `<option value="${value}" ${(typedValue?.state || "open") === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
          <div class="form-group"><label for="map-typed-route-reason">原因（可选）</label><textarea class="form-textarea" id="map-typed-route-reason" rows="2" maxlength="1000">${esc(typedValue?.reason || "")}</textarea></div>
        `)}
        ${fieldset("status", `
          <div class="form-group"><label>状态字段</label><input class="form-input" id="map-typed-status-key" maxlength="128" value="${esc(typedValue?.field_key || "")}" placeholder="例如：戒备等级" /></div>
          <div class="map-typed-scalar-row">
            <div class="form-group"><label>值类型</label><select class="form-select" id="map-typed-status-value-type">${[["string", "文字"], ["number", "数字"], ["boolean", "是/否"], ["null", "未设置"]].map(([value, label]) => `<option value="${value}" ${scalarType === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
            <div class="form-group"><label>当前值</label><input class="form-input" id="map-typed-status-value" value="${esc(typedValue?.value ?? "")}" /></div>
          </div>
        `)}
        ${fieldset("boundary", `
          <div class="form-group"><label for="map-typed-boundary-controller">控制者</label><select class="form-select" id="map-typed-boundary-controller">${entityOptions(typedValue?.controller_entity_id || item.target_entity_id)}</select></div>
          <div class="form-group map-boundary-spatial-field"><label for="map-typed-boundary-hexes">范围格（每行 q,r）</label><textarea class="form-textarea" id="map-typed-boundary-hexes" rows="4" placeholder="2,3">${esc(hexText(typedValue))}</textarea></div>
          <p class="map-boundary-mobile-handoff">当前范围已保留；势力 hex 绘制与精修请在桌面端继续。</p>
        `)}
        ${fieldset("resource", `
          <div class="form-group"><label>资源名称/键</label><input class="form-input" id="map-typed-resource-key" maxlength="128" value="${esc(typedValue?.resource_key || "")}" /></div>
          <div class="form-group"><label>控制者（可选）</label><select class="form-select" id="map-typed-resource-controller">${entityOptions(typedValue?.controller_entity_id, "未指定控制者")}</select></div>
          <div class="map-typed-scalar-row"><div class="form-group"><label>状态（可选）</label><input class="form-input" id="map-typed-resource-status" maxlength="128" value="${esc(typedValue?.status || "")}" /></div><div class="form-group"><label>数量（可选）</label><input class="form-input" id="map-typed-resource-amount" type="number" step="any" value="${esc(typedValue?.amount ?? "")}" /></div></div>
        `)}
        ${fieldset("terrain", `
          <div class="form-group"><label>地形名称/键</label><input class="form-input" id="map-typed-terrain-key" maxlength="128" value="${esc(typedValue?.terrain_key || "")}" /></div>
          <div class="form-group"><label>地形状态</label><input class="form-input" id="map-typed-terrain-state" maxlength="128" value="${esc(typedValue?.state || "")}" /></div>
          <div class="form-group"><label>影响格（每行 q,r）</label><textarea class="form-textarea" id="map-typed-terrain-hexes" rows="4" placeholder="2,3">${esc(hexText(typedValue))}</textarea></div>
        `)}
        ${fieldset("crisis", `
          <div class="form-group"><label>危机名称/键</label><input class="form-input" id="map-typed-crisis-key" maxlength="128" value="${esc(typedValue?.crisis_key || "")}" /></div>
          <div class="form-group"><label>强度（0–5）</label><input class="form-input" id="map-typed-crisis-severity" type="number" min="0" max="5" step="1" value="${esc(typedValue?.severity ?? 0)}" /></div>
          <div class="form-group"><label>影响格（每行 q,r）</label><textarea class="form-textarea" id="map-typed-crisis-hexes" rows="4" placeholder="2,3">${esc(hexText(typedValue))}</textarea></div>
        `)}
        ${fieldset("semantic", `
          <div class="form-group"><label>关联类型</label><input class="form-input" id="map-typed-semantic-relation" maxlength="64" value="${esc(typedValue?.relation_type || "semantic_relation")}" /></div>
          <div class="form-group"><label>相关对象（可多选）</label><select class="form-select" id="map-typed-semantic-entities" multiple size="4">${unknownRelatedOptions}${entities.map((entry) => `<option value="${esc(entry.id)}" ${(typedValue?.related_entity_ids || []).includes(entry.id) ? "selected" : ""}>${esc(entry.name)}</option>`).join("")}</select></div>
          <div class="form-group"><label>关联说明（可选）</label><textarea class="form-textarea" id="map-typed-semantic-summary" rows="3" maxlength="2000">${esc(typedValue?.summary || "")}</textarea></div>
        `)}
      </section>
    `
  },

  _proposalToTypedValue(item, proposal) {
    const entities = mapView.timelineEntityOptions?.() || []
    const paths = mapView.timelinePathOptions?.() || []
    const entityByName = (name, allowedTypes = null) => entities.find((entity) => (
      entity.name === name && (!allowedTypes || allowedTypes.includes(entity.entityType))
    ))?.id || null
    if (["character_location", "event_location"].includes(proposal.proposal_type)) {
      return {
        schema_version: 1,
        type: "location",
        location_entity_id: entityByName(proposal.location_name, ["location"]),
        path_id: null,
        movement_mode: proposal.movement_mode || "unknown",
        state: proposal.state || (proposal.proposal_type === "event_location" ? "occurred" : "present"),
      }
    }
    if (proposal.proposal_type === "route_state") {
      return {
        schema_version: 1,
        type: "route_state",
        path_id: paths.find((path) => path.name === proposal.path_name)?.id || null,
        state: proposal.state || "open",
        reason: proposal.reason || null,
      }
    }
    if (proposal.proposal_type === "boundary") {
      return {
        schema_version: 1,
        type: "boundary",
        controller_entity_id: entityByName(proposal.controller_name, ["organization", "faction"])
          || item.target_entity_id
          || null,
        hexes: [],
      }
    }
    return proposal
  },

  _bindTypedDynamicValueEditor() {
    const select = document.getElementById("map-object-edit-value-type")
    if (!select) return false
    document.querySelectorAll(".map-typed-dynamic-editor select:not([multiple])").forEach((field) => {
      const declared = field.querySelector("option[selected]")
      if (declared) field.value = declared.value
    })
    if (select.dataset.initialized !== "true") {
      select.value = select.dataset.initialType || ""
      select.dataset.initialized = "true"
    }
    const sync = () => {
      document.querySelectorAll("[data-map-dynamic-fields]").forEach((fieldset) => {
        fieldset.hidden = fieldset.dataset.mapDynamicFields !== select.value
      })
    }
    select.onchange = sync
    sync()
    return true
  },

  _canonicalDynamicType(value) {
    const normalized = String(value || "").trim().toLowerCase().replaceAll("-", "_")
    return {
      movement: "location",
      position: "location",
      position_change: "location",
      journey: "location",
      route: "route_state",
      path_state: "route_state",
      state: "status",
      territory: "boundary",
      territory_change: "boundary",
      resource_control: "resource",
      terrain_change: "terrain",
      crisis_spread: "crisis",
      semantic_relation: "semantic",
      movement_explanation: "semantic",
    }[normalized] || normalized
  },

  _parseDynamicHexes(raw) {
    const byKey = new Map()
    for (const token of String(raw || "").split(/[\n;]+/).map((item) => item.trim()).filter(Boolean)) {
      const match = token.match(/^(\d+)\s*,\s*(\d+)$/)
      if (!match) throw new Error(`范围格“${token}”格式不正确，应为 q,r`)
      const hex = { hex_q: Number(match[1]), hex_r: Number(match[2]) }
      byKey.set(`${hex.hex_q},${hex.hex_r}`, hex)
      if (byKey.size > 20000) throw new Error("范围格一次最多 20,000 个")
    }
    return [...byKey.values()].sort((a, b) => a.hex_q - b.hex_q || a.hex_r - b.hex_r)
  },

  _readTypedDynamicValue() {
    const value = (id) => document.getElementById(id)?.value?.trim() || ""
    const optional = (id) => value(id) || null
    const required = (id, label) => {
      const result = value(id)
      if (!result) throw new Error(`请填写${label}`)
      return result
    }
    const typeSelect = document.getElementById("map-object-edit-value-type")
    const type = typeSelect?.dataset?.initialized === "true"
      ? value("map-object-edit-value-type")
      : (typeSelect?.dataset?.initialType || "")
    if (!type) return null
    if (type === "location") {
      return {
        schema_version: 1,
        type,
        location_entity_id: optional("map-typed-location-entity"),
        path_id: optional("map-typed-location-path"),
        movement_mode: value("map-typed-location-mode") || "unknown",
        state: required("map-typed-location-state", "位置状态"),
      }
    }
    if (type === "route_state") {
      return {
        schema_version: 1,
        type,
        path_id: required("map-typed-route-path", "线路"),
        state: value("map-typed-route-state") || "open",
        reason: optional("map-typed-route-reason"),
      }
    }
    if (type === "status") {
      const scalarType = value("map-typed-status-value-type") || "string"
      const raw = value("map-typed-status-value")
      let scalar = raw
      if (scalarType === "null") scalar = null
      if (scalarType === "boolean") {
        if (!["true", "false", "是", "否"].includes(raw.toLowerCase())) {
          throw new Error("状态值应填写 true/false 或 是/否")
        }
        scalar = ["true", "是"].includes(raw.toLowerCase())
      }
      if (scalarType === "number") {
        scalar = Number(raw)
        if (!raw || !Number.isFinite(scalar)) throw new Error("状态数字必须是有限数值")
      }
      return {
        schema_version: 1,
        type,
        field_key: required("map-typed-status-key", "状态字段"),
        value: scalar,
      }
    }
    if (type === "boundary") {
      return {
        schema_version: 1,
        type,
        controller_entity_id: required("map-typed-boundary-controller", "控制者"),
        hexes: this._parseDynamicHexes(value("map-typed-boundary-hexes")),
      }
    }
    if (type === "resource") {
      const amount = value("map-typed-resource-amount")
      const numericAmount = amount ? Number(amount) : null
      if (amount && !Number.isFinite(numericAmount)) throw new Error("资源数量必须是有限数值")
      return {
        schema_version: 1,
        type,
        resource_key: required("map-typed-resource-key", "资源名称/键"),
        controller_entity_id: optional("map-typed-resource-controller"),
        status: optional("map-typed-resource-status"),
        amount: numericAmount,
      }
    }
    if (type === "terrain") {
      return {
        schema_version: 1,
        type,
        terrain_key: required("map-typed-terrain-key", "地形名称/键"),
        state: required("map-typed-terrain-state", "地形状态"),
        hexes: this._parseDynamicHexes(value("map-typed-terrain-hexes")),
      }
    }
    if (type === "crisis") {
      const severity = Number(value("map-typed-crisis-severity"))
      if (!Number.isInteger(severity) || severity < 0 || severity > 5) {
        throw new Error("危机强度必须是 0–5 的整数")
      }
      return {
        schema_version: 1,
        type,
        crisis_key: required("map-typed-crisis-key", "危机名称/键"),
        severity,
        hexes: this._parseDynamicHexes(value("map-typed-crisis-hexes")),
      }
    }
    if (type === "semantic") {
      const related = [...(document.getElementById("map-typed-semantic-entities")?.selectedOptions || [])]
        .map((option) => option.value)
      if (related.length > 200) throw new Error("相关对象一次最多选择 200 个")
      return {
        schema_version: 1,
        type,
        relation_type: required("map-typed-semantic-relation", "关联类型"),
        related_entity_ids: [...new Set(related)].sort(),
        summary: optional("map-typed-semantic-summary"),
      }
    }
    throw new Error("不支持的结构化动态类型")
  },

  _readObservationEditPayload(reviewState, observation = null) {
    const value = (id) => document.getElementById(id)?.value?.trim() || ""
    const typedValue = this._readTypedDynamicValue()
    const targetSelect = document.getElementById("map-object-edit-target-entity")
    const selectedTarget = targetSelect?.selectedOptions?.[0]
    const payload = {
      expected_updated_at: observation?.updated_at,
      review_state: reviewState || "candidate",
      target_entity_id: targetSelect?.value || null,
      target_entity_type: selectedTarget?.dataset?.entityType || null,
      target_name: value("map-object-edit-target-name") || selectedTarget?.textContent?.split("·")[0]?.trim() || null,
    }
    if (typedValue) payload.value_json = typedValue
    return payload
  },

  _applyObservationConflictLatest(latest, capturedItem = null) {
    if (!latest?.id) return null
    const applyLatest = (entry) => {
      const entryId = entry?.item_id || entry?.id
      if (entryId !== latest.id) return entry
      Object.assign(entry, latest)
      entry.item_id ||= latest.id
      entry.item_kind ||= "observation"
      return entry
    }
    if (capturedItem) applyLatest(capturedItem)
    for (const entry of this._inbox?.items || []) applyLatest(entry)
    for (const entry of this._dynamicSummary?.observations || []) applyLatest(entry)
    for (const entry of this._dynamicSummary?.dashboard?.dynamic_queue || []) applyLatest(entry)
    this._rebuildDynamicIndexes()

    const body = document.getElementById("modal-body")
    if (body) {
      let summary = body.querySelector("#map-observation-conflict-summary")
      if (!summary) {
        summary = document.createElement("div")
        summary.id = "map-observation-conflict-summary"
        summary.className = "alert alert-warning"
        summary.setAttribute("role", "status")
        body.prepend(summary)
      }
      const missing = latest.eligibility?.missing_item_labels || []
      const stateLabel = this._reviewStateLabel(latest.review_state)
      summary.textContent = `服务器最新摘要：${stateLabel}${missing.length ? `；待补 ${missing.join("、")}` : "；字段完整"}。当前表单输入已保留。`
    }
    return capturedItem || this._dynamicObservation(latest.id)
  },

  async _saveObservationEdit(item, payload) {
    const requestPayload = {
      ...payload,
      expected_updated_at: payload.expected_updated_at || item.updated_at,
    }
    try {
      await api.world.updateMapObservationReview(
        this._activeMapId,
        item.item_id || item.id,
        state.currentProjectId,
        requestPayload,
      )
      closeModal()
      toast("地图待处理项已保存", "success")
      await this._loadDynamicSummary({ force: true })
      return true
    } catch (err) {
      const latest = err.body?.context?.latest
      if (err.status === 409 && latest) {
        this._applyObservationConflictLatest(latest, item)
        toast("该建议已被其他操作更新；当前表单未关闭，请核对后重试", "warning")
        return false
      }
      toast(`更新失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  _dynamicObjectActions(item) {
    if (item.item_kind === "observation") {
      return [
        {
          text: "采用",
          class: "btn-primary",
          handler: () => {
            closeModal()
            this._confirmObservation(item.item_id)
          },
        },
        {
          text: "忽略",
          class: "btn",
          handler: () => {
            closeModal()
            this._ignoreObservation(item.item_id)
          },
        },
        {
          text: "标记冲突",
          class: "btn",
          handler: () => {
            closeModal()
            this._markObservationConflict(item.item_id)
          },
        },
        {
          text: "更换地图",
          class: "btn",
          handler: () => {
            closeModal()
            this._showInboxAssignment(item.item_id, item)
          },
        },
        {
          text: "取消分配",
          class: "btn",
          handler: () => {
            closeModal()
            this._unassignObservation(item.item_id)
          },
        },
      ]
    }
    if (item.item_kind === "fact") {
      return [
        {
          text: "回滚",
          class: "btn",
          handler: () => {
            closeModal()
            this._updateFactStatus(item.item_id, "rolled_back")
          },
        },
        {
          text: "废弃",
          class: "btn",
          handler: () => {
            closeModal()
            this._updateFactStatus(item.item_id, "deprecated")
          },
        },
        {
          text: "恢复采用",
          class: "btn-primary",
          handler: () => {
            closeModal()
            this._updateFactStatus(item.item_id, "confirmed")
          },
        },
      ]
    }
    return []
  },

  async _markObservationConflict(id) {
    const item = this._dynamicObservation(id)
    const name = item?.title || item?.target_name || "地图映射"
    return confirmAction(`标记地图映射「${name}」为冲突？`, async () => {
      try {
        await api.world.updateMapObservationReview(
          this._activeMapId,
          id,
          state.currentProjectId,
          { expected_updated_at: item?.updated_at, review_state: "conflicted" },
        )
        toast("地图映射已标记为冲突", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          this._applyObservationConflictLatest(latest, item)
          toast("地图映射已更新，请核对最新摘要后重试", "warning")
          return false
        }
        toast(`标记失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  _reviewStateLabel(reviewState) {
    const state = typeof reviewState === "object" ? reviewState?.review_state : reviewState
    return {
      candidate: "待处理",
      ignored: "历史（已忽略）",
      conflicted: "待处理（存在冲突）",
    }[state] || state || "待处理"
  },

  async _updateObservationReview(id, reviewState) {
    const item = this._dynamicObservation(id)
    const name = item?.title || item?.target_name || "地图映射"
    const label = this._reviewStateLabel(reviewState)
    return confirmAction(`将地图映射「${name}」设为${label}？`, async () => {
      try {
        const payload = reviewState && typeof reviewState === "object"
          ? { ...reviewState }
          : { review_state: reviewState }
        if (!payload.expected_updated_at) payload.expected_updated_at = item?.updated_at
        await api.world.updateMapObservationReview(
          this._activeMapId,
          id,
          state.currentProjectId,
          payload,
        )
        toast("地图映射已更新", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          this._applyObservationConflictLatest(latest, item)
          toast("地图映射已更新，请核对最新摘要后重试", "warning")
          return false
        }
        toast(`更新失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  _unassignObservation(id) {
    const item = this._dynamicObservation(id)
    if (!item) return false
    const name = item.title || item.target_name || "地图待处理项"
    return confirmAction(`取消「${name}」的地图分配？它将回到项目级地图待处理。`, async () => {
      try {
        await api.world.assignProjectMapObservation(
          id,
          state.currentProjectId,
          null,
          item.updated_at,
        )
        toast("已取消分配，建议已回到地图待处理", "success")
        await Promise.all([
          this._loadDynamicSummary({ force: true }),
          this._loadData(),
        ])
        return true
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          this._applyObservationConflictLatest(latest, item)
          toast("地图归属已更新，请核对最新摘要后重试", "warning")
          return false
        }
        toast(`取消分配失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  async _updateFactStatus(id, factStatus) {
    const item = this._dynamicFact(id)
    const name = item?.title || item?.target_name || "地图事实"
    const label = this._factStatusLabel(factStatus)
    return confirmAction(`将地图事实「${name}」设为${label}？`, async () => {
      try {
        await api.world.updateMapFactStatus(this._activeMapId, id, state.currentProjectId, factStatus)
        toast(`地图事实已设为${label}`, "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        toast(`更新失败：${err.message || "未知错误"}`, "error")
      }
    })
  },

  _factStatusLabel(status) {
    return {
      confirmed: "已采用",
      rolled_back: "历史（已回滚）",
      deprecated: "历史（已废弃）",
    }[status] || "待判断"
  },

  async _openFocusedInspector(focusEntityId, dynamicItemId = null) {
    this._focusedDynamicItemId = dynamicItemId
    if (!focusEntityId) {
      await this._loadDynamicSummary({ force: true })
      const observation = dynamicItemId ? this._dynamicObservation(dynamicItemId) : null
      const fact = !observation && dynamicItemId ? this._dynamicFact(dynamicItemId) : null
      if (observation) mapView.selectInspectorObject("observation", observation)
      if (fact) mapView.selectInspectorObject("fact", fact)
      toast("检查器已在右侧显示", "info")
      return
    }
    this._focusEntityId = focusEntityId
    await this._loadDynamicSummary({ force: true })
    if (dynamicItemId) {
      const observation = this._dynamicObservation(dynamicItemId)
      const fact = observation ? null : this._dynamicFact(dynamicItemId)
      if (observation) mapView.selectInspectorObject("observation", observation)
      if (fact) mapView.selectInspectorObject("fact", fact)
    }
    toast("检查器已按对象聚焦", "info")
  },

  _candidateIdsForGroup(groupKey) {
    const ids = this._dynamicIndex().candidateIdsByGroup.get(groupKey)
    if (ids) return [...ids]
    return [...(this._rebuildDynamicIndexes().candidateIdsByGroup.get(groupKey) || [])]
  },

  async _batchReviewGroup(groupKey, action) {
    const ids = this._candidateIdsForGroup(groupKey)
    if (!ids.length) {
      toast("该分组暂无待处理项", "info")
      return
    }
    const batchIds = ids.slice(0, MAP_BATCH_ID_LIMIT)
    const batchItems = batchIds
      .map((id) => this._dynamicObservation(id) || this._findDynamicItem(id))
      .filter(Boolean)
    if (action === "confirm") {
      const blocked = batchItems.find((item) => item.eligibility && !item.eligibility.can_confirm)
      if (blocked) {
        toast(`分组中有待补全项：${(blocked.eligibility.missing_item_labels || []).join("、") || "请打开编辑"}`, "warning")
        return false
      }
    }
    const label = { confirm: "采用", ignore: "忽略", conflict: "标记冲突" }[action] || "处理"
    const batchNote = ids.length > batchIds.length
      ? `本次先${label} ${batchIds.length} 条（该分组共 ${ids.length} 条）`
      : `${label}该分组的 ${batchIds.length} 条地图待处理项`
    return confirmAction(`${batchNote}？`, async () => {
      try {
        const apiAction = {
          confirm: "confirm_observations",
          ignore: "ignore_observations",
          conflict: "mark_conflicted",
        }[action]
        await api.world.runMapBatchAction(this._activeMapId, state.currentProjectId, {
          action: apiAction,
          observation_items: batchItems.map((item) => ({
            observation_id: item.item_id || item.id,
            expected_updated_at: item.updated_at,
          })),
        })
        toast("批量修改已完成", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          const captured = batchItems.find((item) => (item.item_id || item.id) === latest.id)
          this._applyObservationConflictLatest(latest, captured)
          toast("批量修改遇到新版本；未写入部分结果，请核对最新摘要后重试", "warning")
          return false
        }
        toast(`批量修改失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  _schedulePlaybackAdvance() {
    const delay = this._lowMotion ? 1600 : 2200
    const timer = setTimeout(() => {
      this._pendingTimers.delete(timer)
      if (!this._playback?.playing) return
      const events = this._playback.playback?.events || []
      const nextIndex = this._playback.activeIndex + 1
      if (nextIndex >= events.length) {
        this._playback = { ...this._playback, playing: false }
        mapView.clearPathFocus()
      } else {
        this._playback = { ...this._playback, activeIndex: nextIndex }
        this._syncPlaybackPathFocus()
        this._schedulePlaybackAdvance()
      }
      this._updateWorkspaceLayoutDom()
    }, delay)
    this._pendingTimers.add(timer)
  },

  _bindEvents() {
    const root = document.getElementById("workspace-content")
    if (!root) return
    this._bindViewModeControls()
    const runAction = (fn) => {
      Promise.resolve()
        .then(fn)
        .catch((err) => toast(`操作失败：${err.message || "未知错误"}`, "error"))
    }
    root.onclick = (e) => {
      const target = e.target.closest("[data-action]")
      if (!target) return
      const action = target.dataset.action
      if (action === "map-open-recent") return runAction(() => this._openRecentMap())
      if (action === "map-open") return runAction(() => this._openMap(target.dataset.id, { viewMode: "live" }))
      if (action === "map-search-location") return runAction(() => this._openLocation(target.dataset.id))
      if (action === "map-quick-create") return runAction(() => this._openQuickCreate())
      if (action === "map-create-world") return runAction(() => this._showCreateWorldForm())
      if (action === "map-toggle-archived") {
        this._showArchivedMaps = !this._showArchivedMaps
        return runAction(() => router.renderCurrentView?.())
      }
      if (action === "map-archive-page") {
        this._archivedPage = Math.max(0, Number(target.dataset.page || 0))
        return runAction(() => router.renderCurrentView?.())
      }
      if (action === "map-archive") return runAction(() => this._archiveMap(target.dataset.id))
      if (action === "map-restore") return runAction(() => this._showRestoreMapForm(target.dataset.id))
      if (action === "map-inbox-assign") return runAction(() => this._showInboxAssignment(target.dataset.id))
      if (action === "map-inbox-ignore") return runAction(() => this._ignoreInboxObservation(target.dataset.id))
      if (action === "map-inbox-copy-diagnostic") {
        const item = (this._inbox?.items || []).find((entry) => entry.id === target.dataset.id)
        return runAction(() => this._copyDynamicDiagnostic(item))
      }
      if (action === "map-inbox-retry") {
        return runAction(async () => {
          await this._loadData()
          await router.renderCurrentView?.()
        })
      }
      if (action === "map-inbox-page") {
        this._inbox = { ...this._inbox, page: Math.max(0, Number(target.dataset.page || 0)) }
        return runAction(async () => {
          await this._loadData()
          await router.renderCurrentView?.()
        })
      }
      if (action === "map-confirm-observation") return runAction(() => this._confirmObservation(target.dataset.id))
      if (action === "map-ignore-observation") return runAction(() => this._ignoreObservation(target.dataset.id))
      if (action === "map-view-mode") return runAction(() => this._setViewMode(target.dataset.viewMode))
      if (action === "map-playback-start") return runAction(() => this._startPlayback())
      if (action === "map-playback-stop") return runAction(() => this._stopPlayback())
      if (action === "map-timeline-start") return runAction(() => this._startTimeline())
      if (action === "map-timeline-stop") return runAction(() => this._stopTimeline())
      if (action === "map-timeline-step") {
        return runAction(() => this._stepTimeline(Number(target.dataset.delta || 0)))
      }
      if (action === "map-timeline-retry") {
        return runAction(() => this._loadDynamicSummary({ force: true }))
      }
      if (action === "map-continuity-focus") {
        return runAction(() => this._focusContinuityIssue(target.dataset.issue, target.dataset.side))
      }
      if (action === "map-continuity-evidence") {
        return runAction(() => this._showContinuityEvidence(target.dataset.issue))
      }
      if (action === "map-continuity-open-entity") {
        state.selectedItem = target.dataset.entity
        return runAction(() => router.navigate("world", "objects"))
      }
      if (action === "map-continuity-explain") {
        return runAction(() => this._showContinuityExplanationForm(target.dataset.issue))
      }
      if (action === "map-batch-review") return runAction(() => this._batchReviewGroup(target.dataset.group, target.dataset.reviewAction))
      if (action === "map-toggle-history") {
        return runAction(() => this._toggleHistory())
      }
      if (action === "map-open-dynamic-item") {
        return runAction(() => this._showDynamicObjectInfo(target.dataset.id))
      }
      if (action === "map-overview") {
        return runAction(() => this._returnToOverview())
      }
    }
    root.onchange = (event) => {
      const target = event.target.closest?.("[data-action]")
      if (!target) return
      const action = target.dataset.action
      if (action === "map-timeline-scene-select" || action === "map-timeline-cursor") {
        return runAction(() => this._setTimelineScenePosition(Number(target.value)))
      }
      if (action === "map-timeline-speed") {
        this._timeline = {
          ...this._timeline,
          speedMs: Math.max(600, Number(target.value || 1600)),
          playing: false,
        }
        return this._updateDynamicSummaryDom()
      }
      if (action === "map-timeline-candidates") {
        return runAction(() => this._setTimelineCandidates(target.checked))
      }
      if (action === "map-timeline-track") {
        return this._setTimelineTrack(target.dataset.track, target.checked)
      }
      if (action === "map-inbox-filter") {
        const filter = target.dataset.filter
        this._inbox = {
          ...this._inbox,
          page: 0,
          filters: {
            ...(this._inbox?.filters || {}),
            [filter]: target.value,
          },
        }
        return runAction(async () => {
          await this._loadData()
          await router.renderCurrentView?.()
        })
      }
    }
    root.querySelectorAll("[data-action='map-layer-toggle']").forEach((input) => {
      input.onchange = () => this._setLayer(input.dataset.layer, input.checked)
    })
    root.querySelectorAll("[data-action='map-low-motion-toggle']").forEach((input) => {
      input.onchange = () => this._setLowMotion(input.checked)
    })
    const search = root.querySelector("#map-workspace-search")
    if (search) {
      search.oninput = () => {
        const results = this._search(search.value)
        const container = root.querySelector("#map-search-results")
        if (container) {
          container.innerHTML = results.map((r) =>
            `<button class="btn btn-sm" data-action="${r.type === "map" ? "map-open" : "map-search-location"}" data-id="${esc(r.id)}">${esc(r.name)}</button>`
          ).join("")
        }
      }
    }
  },

  _showInboxAssignment(observationId, assignedItem = null) {
    const item = assignedItem
      || (this._inbox?.items || []).find((entry) => entry.id === observationId)
    if (!item) return false
    const isReassignment = Boolean(assignedItem)
    if (!this._maps.length) {
      toast("请先创建一张地图，再分配待处理项", "warning")
      return false
    }
    const form = `
      <p>分配后将打开目标地图，并继续补全「${esc(item.target_name || this._proposalTypeLabel(item))}」。</p>
      <div class="form-group">
        <label>目标地图</label>
        <select class="form-select" id="map-inbox-assignment-map">
          ${this._maps.map((map) => `<option value="${esc(map.id)}" ${map.id === (item.map_id || this._activeMapId) ? "selected" : ""}>${esc(map.name)}</option>`).join("")}
        </select>
      </div>
    `
    showModalHtml(isReassignment ? "更换地图" : "分配地图待处理项", form, [{
      text: isReassignment ? "更换并继续" : "分配并继续",
      class: "btn-primary",
      handler: async () => {
        const mapId = document.getElementById("map-inbox-assignment-map")?.value
        if (!mapId) {
          toast("请选择目标地图", "warning")
          return false
        }
        try {
          await api.world.assignProjectMapObservation(
            item.id,
            state.currentProjectId,
            mapId,
            item.updated_at,
          )
          closeModal()
          this._removeProjectInboxItem(item.id)
          this._pendingObservationEditorId = item.id
          this._openMap(mapId, { viewMode: "dashboard" })
          toast(isReassignment ? "已更换地图，请继续核对并确认" : "已分配地图，请继续补全并确认", "success")
          return true
        } catch (err) {
          const latest = err.body?.context?.latest
          if (err.status === 409 && latest) {
            this._applyObservationConflictLatest(latest, item)
            toast("该建议已被其他操作更新，表单已保留，请核对后重试", "warning")
            return false
          }
          toast(`分配失败：${err.message || "未知错误"}`, "error")
          return false
        }
      },
    }])
    return true
  },

  _ignoreInboxObservation(observationId) {
    const item = (this._inbox?.items || []).find((entry) => entry.id === observationId)
    if (!item) return false
    return confirmAction(`忽略地图待处理项「${item.target_name || this._proposalTypeLabel(item)}」？`, async () => {
      try {
        await api.world.ignoreProjectMapObservation(
          item.id,
          state.currentProjectId,
          item.updated_at,
        )
        const pageChanged = this._removeProjectInboxItem(item.id)
        toast("地图待处理项已忽略", "success")
        if (pageChanged) await this._loadData()
        await router.renderCurrentView?.()
      } catch (err) {
        const latest = err.body?.context?.latest
        if (err.status === 409 && latest) {
          this._applyObservationConflictLatest(latest, item)
          toast("该建议已更新，请核对最新内容", "warning")
          return false
        }
        toast(`忽略失败：${err.message || "未知错误"}`, "error")
        return false
      }
    })
  },

  async _archiveMap(mapId) {
    const map = this._mapById.get(mapId)
    const impact = await api.world.getMapArchiveImpact(mapId, state.currentProjectId)
    const counts = impact.asset_counts || {}
    const totalAssets = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)
    const labels = {
      tiles: "底图格",
      location_bindings: "地点绑定",
      location_layouts: "地点布局",
      markers: "标记",
      territories: "领地格",
      terrain_layers: "覆盖图层",
      terrain_regions: "覆盖区域",
      terrain_patches: "覆盖格",
      terrain_bindings: "覆盖绑定",
      layer_nodes: "图层节点",
      observations: "待处理观察",
      facts: "地图事实",
    }
    const details = Object.entries(counts)
      .filter(([, value]) => Number(value || 0) > 0)
      .map(([key, value]) => `${labels[key] || key} ${Number(value)}`)
      .join("、")
    return confirmAction(
      `归档「${esc(map?.name || "该地图")}」及其 ${impact.map_count} 张地图？将一并隐藏 ${totalAssets} 个关联资产${details ? `（${details}）` : ""}；内容会保留，可从归档地图恢复。`,
      async () => {
        await api.world.archiveMap(mapId, state.currentProjectId)
        if (this._activeMapId === mapId) this._clearRecentMap()
        await this._loadData()
        toast("地图子树已归档", "success")
        router.refresh?.()
      },
      "归档子树",
    )
  },

  _showRestoreMapForm(mapId) {
    const map = this._archivedMaps.find((item) => item.id === mapId)
    if (!map) return
    const form = `
      <p>将恢复「${esc(map.name)}」及其完整子树。若同层已有同名地图，可只重命名恢复根。</p>
      <div class="form-group">
        <label>恢复根名称</label>
        <input class="form-input" id="map-restore-root-name" value="${esc(map.name)}" maxlength="255" />
      </div>
    `
    showModalHtml("恢复归档地图", form, [{
      text: "恢复子树",
      class: "btn-primary",
      handler: async () => {
        const rootName = document.getElementById("map-restore-root-name")?.value?.trim()
        try {
          await api.world.restoreMap(mapId, { root_name: rootName || map.name }, state.currentProjectId)
          closeModal()
          await this._loadData()
          toast("地图子树已恢复", "success")
          router.refresh?.()
        } catch (err) {
          toast(`恢复失败：${err.message || "未知错误"}`, "error")
          return false
        }
      },
    }])
  },

  async _openQuickCreate() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return null
    }
    try {
      await mapQuickCreateView.open({
        onCreated: async (map) => {
          await this._loadData()
          this._openMap(map.id, { viewMode: "live" })
        },
      })
      return true
    } catch (err) {
      toast(`快速创建地图失败：${err.message || "未知错误"}`, "error")
      return null
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
    showModalHtml("创建世界地图", formHtml, [{
      text: "创建",
      class: "btn-primary",
      handler: async () => {
        const name = document.getElementById("map-create-name")?.value.trim()
        if (!name) {
          toast("请输入地图名称", "warning")
          return
        }
        const [gridWidth, gridHeight] = (document.getElementById("map-create-size")?.value || "30,20")
          .split(",")
          .map(Number)
        const template = document.getElementById("map-create-template")?.value || "blank"
        try {
          const created = await api.world.createMap({
            name,
            map_type: "world",
            grid_width: gridWidth,
            grid_height: gridHeight,
            template,
          }, state.currentProjectId)
          closeModal()
          toast("世界地图已创建", "success")
          await this._loadData()
          this._openMap(created.id, { viewMode: "live" })
        } catch (err) {
          toast(`创建失败：${err.message || "未知错误"}`, "error")
        }
      },
    }])
  },
}

router.registerView("map", mapWorkspaceView)
window.mapWorkspaceView = mapWorkspaceView
export default mapWorkspaceView
