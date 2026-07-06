/**
 * 地图一级工作台。
 */
import mapView from "./mapView.js"
import { buildMapLayout } from "./mapLayoutEngine.js"
import mapQuickCreateView from "./mapQuickCreateView.js"
import { parseMapRouteContext } from "./mapRouteContext.js"

const RECENT_PREFIX = "novel_map_recent:"

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
  _locations: [],
  _mapById: new Map(),
  _detailMapByLocationId: new Map(),
  _mapsByParentId: new Map(),
  _mode: "overview",
  _message: null,
  _activeMapId: null,
  _activeSceneId: null,
  _focusEntityId: null,
  _focusedDynamicItemId: null,
  _viewMode: "dashboard",
  _lowMotion: false,
  _layers: { ...DEFAULT_LAYERS },
  _dynamicSummary: {
    mapId: null,
    loading: false,
    loaded: false,
    dashboard: null,
    observations: [],
    facts: [],
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
  _dynamicIndexes: createDynamicIndexes(),
  _pendingTimers: new Set(),

  async onEnter() {
    await this._loadData()
  },

  onLeave() {
    this._clearPendingTimers()
    mapView.unmount()
  },

  async render() {
    this._clearPendingTimers()
    const context = parseMapRouteContext()
    if (context.projectId && !state.currentProjectId) {
      state.currentProjectId = context.projectId
    }
    if (context.mapId && context.mode !== "recent" && context.mode !== "overview") {
      this._mode = "map"
      this._activeMapId = context.mapId
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      this._viewMode = this._normalizeViewMode(context.mode)
    } else if (context.mode === "recent") {
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      if (!(this._mode === "map" && this._activeMapId)) {
        const preferredViewMode = context.sceneId || context.focusEntityId ? "live" : null
        this._defer(() => this._openRecentMap({ viewMode: preferredViewMode }))
      }
    } else if (context.projectId && !context.mapId && !this._activeMapId) {
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      this._defer(() => this._openDefaultTarget())
    }

    if (this._mode === "map" && this._activeMapId) {
      const html = this._renderMapWorkspace()
      this._defer(() => this._mountMap())
      return html
    }
    const html = this._renderOverview()
    this._defer(() => this._bindEvents())
    return html
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
    if (!state.currentProjectId) {
      this._maps = []
      this._locations = []
      this._rebuildMapIndexes()
      return
    }
    const [maps, locations] = await Promise.all([
      api.world.listMaps({ novel_id: state.currentProjectId }).catch(() => ({ items: [] })),
      this._listAllLocations().catch(() => []),
    ])
    this._maps = maps.items || maps || []
    this._locations = locations.items || locations || []
    this._rebuildMapIndexes()
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

  async _listAllLocations() {
    const all = []
    const limit = 50
    let skip = 0
    while (true) {
      const data = await api.world.listEntities({
        novel_id: state.currentProjectId,
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
    router.refresh?.()
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
      this._openMap(map.id, options)
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
        this._openMap(target.map_id, {
          sceneId: target.scene_id || this._activeSceneId,
          focusEntityId: target.focus_entity_id || this._focusEntityId,
          viewMode: preferredViewMode || target.mode || "dashboard",
        })
      }
    } catch {
      if (fallbackToRecent) {
        await this._openRecentMap({ fallbackToDefault: false })
      } else {
        this._showOverviewFallback("地图打开目标不可用，已返回地图总览")
      }
    }
  },

  _openMap(mapId, { sceneId = null, focusEntityId = null, viewMode = null } = {}) {
    this._mode = "map"
    this._activeMapId = mapId
    this._activeSceneId = sceneId
    this._focusEntityId = focusEntityId
    if (viewMode) this._viewMode = this._normalizeViewMode(viewMode)
    this._resetDynamicSummary()
    this._ensureMapIndexes()
    const map = this._mapById.get(mapId)
    if (map) this._saveRecentMap(map)
    router.refresh?.()
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
    this._viewMode = viewMode
    if (this._mode === "map") {
      mapView._mountContext = {
        ...(mapView._mountContext || {}),
        viewMode: this._viewMode,
        lowMotion: this._lowMotion,
      }
      mapView._redraw?.()
      this._updateViewModeControlsDom()
      this._updateWorkspaceLayoutDom()
    }
  },

  _setLowMotion(enabled) {
    this._lowMotion = Boolean(enabled)
    if (this._mode === "map") {
      mapView._mountContext = {
        ...(mapView._mountContext || {}),
        viewMode: this._viewMode,
        lowMotion: this._lowMotion,
      }
      this._updateWorkspaceLayoutDom()
    }
  },

  _resetDynamicSummary(mapId = null) {
    this._focusedDynamicItemId = null
    this._dynamicSummary = {
      mapId,
      sceneId: this._activeSceneId,
      focusEntityId: this._focusEntityId,
      focusedDynamicItemId: this._focusedDynamicItemId,
      loading: false,
      loaded: false,
      dashboard: null,
      observations: [],
      facts: [],
      error: null,
    }
    this._dynamicIndexes = createDynamicIndexes()
    this._resetPlayback()
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
        <div class="map-toolbar">
          <button class="btn btn-primary" data-action="map-open-recent">
            打开最近地图
          </button>
          <button class="btn btn-primary" data-action="map-quick-create">快速创建</button>
          <button class="btn" data-action="map-create-world">创建世界地图</button>
          <input class="form-input" id="map-workspace-search" placeholder="搜索地图或地点" />
        </div>
        ${message}
        <div class="map-overview-grid">
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
        </div>
        <div id="map-search-results"></div>
      </div>
    `
  },

  _renderMapTree(parentId = null) {
    this._ensureMapIndexes()
    const children = this._mapsByParentId.get(parentId) || []
    if (!children.length) return parentId ? "" : `<p class="muted">暂无地图</p>`
    return `
      <ul class="map-tree">
        ${children.map((m) => `
          <li>
            <button class="link-button" data-action="map-open" data-id="${esc(m.id)}">
              ${esc(m.name)}
            </button>
            ${this._renderMapTree(m.id)}
          </li>
        `).join("")}
      </ul>
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
      candidate: "待确认",
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
    return `
      <div class="map-workspace map-workspace-active">
        <div class="map-toolbar">
          <button class="btn" data-action="map-overview">返回总览</button>
          <button class="btn btn-sm btn-primary" data-action="map-quick-create">快速创建</button>
          ${this._renderViewModeControls()}
          ${this._renderLayerToggles()}
        </div>
        <div class="map-workspace-body">
          <main class="map-workspace-main">
            <div id="map-semantic-band" class="map-semantic-band">
              ${this._renderSemanticBand()}
            </div>
            <div id="map-root" class="map-root"></div>
          </main>
          <aside id="map-dynamic-summary" class="map-dynamic-panel">
            ${this._renderDynamicSummary()}
          </aside>
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
      return `<p class="muted">正在加载世界动态...</p>`
    }
    if (summary.error) {
      return `<div class="alert alert-warning">${esc(summary.error)}</div>`
    }
    const dashboard = summary.dashboard
    if (!dashboard) {
      return `<p class="muted">暂无世界动态</p>`
    }
    const queue = dashboard.dynamic_queue || []
    const inspector = this._focusedInspector(dashboard)
    const candidateCount = queue.filter((item) => item.item_kind === "observation" && item.review_state === "candidate").length
    const factCount = queue.filter((item) => item.item_kind === "fact").length
    return `
      <div class="map-dynamic-header">
        <h3>${esc(dashboard.title || "世界动态总控台")}</h3>
        <span>${candidateCount} 待确认 · ${factCount} 已确认</span>
      </div>
      ${this._renderFirstVisualLayer(dashboard.first_visual_layer || {})}
      ${this._renderPlaybackPanel()}
      ${queue.length
        ? `<div class="map-dynamic-section">
            <h4>动态队列</h4>
            ${queue.slice(0, 8).map((item) => this._renderQueueItem(item)).join("")}
          </div>`
        : `<p class="muted">暂无动态队列</p>`}
      ${this._renderInspector(inspector)}
      ${this._renderBatchGroups(dashboard.batch_groups || [])}
    `
  },

  _renderFirstVisualLayer(layer) {
    const risks = layer.top_risks || []
    const characters = layer.main_characters || []
    return `
      <section class="map-dashboard-priority">
        <div>
          <span>主线危机</span>
          <strong>${esc(layer.main_crisis || "暂无主线危机")}</strong>
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
    const canReview = item.item_kind === "observation" && item.review_state === "candidate"
    const riskClass = item.risk_level === "danger" ? " is-danger" : item.risk_level === "warning" ? " is-warning" : ""
    return `
      <article class="map-dynamic-item${riskClass}" data-action="map-open-dynamic-item" data-id="${esc(item.item_id)}">
        <div class="map-dynamic-title">${esc(item.title || "地图事实")}</div>
        <div class="map-dynamic-meta">
          ${esc(item.time_label || "时间待确认")} · ${esc(item.status_label || "待判断")}
          ${item.confidence !== null && item.confidence !== undefined ? ` · 置信度 ${Math.round(item.confidence * 100)}%` : ""}
        </div>
        <div class="map-dynamic-source">${esc(item.source_summary || "来源待确认")}</div>
        ${canReview
          ? `<div class="map-dynamic-actions">
              <button class="btn btn-sm btn-primary" data-action="map-confirm-observation" data-id="${esc(item.item_id)}">确认</button>
              <button class="btn btn-sm" data-action="map-ignore-observation" data-id="${esc(item.item_id)}">忽略</button>
            </div>`
          : ""}
      </article>
    `
  },

  _renderInspector(inspector) {
    if (!inspector) return ""
    const candidates = inspector.ai_candidates || []
    const facts = inspector.map_facts || []
    const conflicts = inspector.conflicts || []
    const evidence = inspector.source_evidence || []
    const timeline = inspector.timeline || []
    const actions = inspector.available_actions || []
    return `
      <div class="map-dynamic-section map-inspector">
        <h4>检查器</h4>
        <article class="map-dynamic-item">
          <div class="map-dynamic-title">${esc(inspector.title || "暂无世界动态")}</div>
          <div class="map-dynamic-meta">${esc(inspector.status_label || "待判断")}</div>
          ${inspector.type_label || inspector.location_label || inspector.spatial_anchor_label
            ? `<div class="map-dynamic-meta">
                ${[inspector.type_label, inspector.location_label, inspector.spatial_anchor_label].filter(Boolean).map((text) => esc(text)).join(" · ")}
              </div>`
            : ""}
          <div class="map-dynamic-source">${esc(inspector.summary || "")}</div>
          <div class="map-inspector-counts">
            <span>候选 ${candidates.length}</span>
            <span>事实 ${facts.length}</span>
            <span>冲突 ${conflicts.length}</span>
          </div>
          ${evidence.length
            ? `<ul class="map-evidence-list">${evidence.slice(0, 3).map((text) => `<li>${esc(text)}</li>`).join("")}</ul>`
            : ""}
          ${timeline.length
            ? `<div class="map-inspector-timeline">
                ${timeline.slice(0, 4).map((item) => `
                  <button class="link-button" data-action="map-open-dynamic-item" data-id="${esc(item.item_id)}">
                    ${esc(item.time_label || "时间待确认")} · ${esc(item.title || "地图对象")}
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
    const queue = this._dynamicSummary?.dashboard?.dynamic_queue || []
    for (const item of queue) {
      if (item.item_id) indexes.byItemId.set(item.item_id, item)
      if (item.id) indexes.byItemId.set(item.id, item)
      const objectKey = this._dynamicObjectKey(item)
      if (!indexes.queueByObjectKey.has(objectKey)) {
        indexes.queueByObjectKey.set(objectKey, [])
      }
      indexes.queueByObjectKey.get(objectKey).push(item)
      const groupKey = item.object_type || item.dynamic_type || "unknown"
      if (item.item_kind === "observation" && item.review_state === "candidate") {
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
            <small>${group.candidate_count} 待确认 · ${group.confirmed_count} 已确认</small>
            ${this._renderBatchTimeGroups(group.time_groups || [])}
            <div class="map-batch-actions">
              ${this._renderBatchButton(group, "confirm", "确认候选")}
              ${this._renderBatchButton(group, "ignore", "忽略候选")}
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
          <small>${esc(timeGroup.time_label || "时间待确认")} · ${esc(timeGroup.candidate_count || 0)} 待确认 · ${esc(timeGroup.confirmed_count || 0)} 已确认</small>
        `).join("")}
      </div>
    `
  },

  _renderBatchButton(group, action, label) {
    const disabled = group.candidate_count > 0 ? "" : "disabled"
    return `<button class="btn btn-sm" data-action="map-batch-review" data-group="${esc(group.group_key)}" data-review-action="${esc(action)}" ${disabled}>${esc(group.candidate_count > 0 ? label : "无待处理候选")}</button>`
  },

  _renderPlaybackPanel() {
    const playbackState = this._playback || {}
    if (playbackState.loading) {
      return `<div class="map-dynamic-section"><h4>电影化播放</h4><p class="muted">正在加载播放事件...</p></div>`
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
          : `<p class="muted">暂无可播放动态</p>`}
        ${active
          ? `<article class="map-dynamic-item ${active.risk_level === "danger" ? "is-danger" : active.risk_level === "warning" ? "is-warning" : ""}" data-action="map-open-dynamic-item" data-id="${esc(active.event_id)}">
              <div class="map-dynamic-title">${esc(active.title)}</div>
              <div class="map-dynamic-meta">${esc(active.time_label)} · ${esc(active.status_label)}</div>
              <div class="map-dynamic-source">${esc(active.change_summary || active.source_summary || "")}</div>
            </article>`
          : ""}
      </div>
    `
  },

  _mountMap() {
    mapView.unmount()
    mapView.mount("map-root", {
      mapId: this._activeMapId,
      sceneId: this._activeSceneId,
      focusEntityId: this._focusEntityId,
      viewMode: this._viewMode,
      lowMotion: this._lowMotion,
      mode: this._activeMapId ? "map" : "overview",
      layers: this._layers,
      onMapOpened: (map) => this._saveRecentMap(map),
    })
    this._loadDynamicSummary()
    this._bindEvents()
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
    const mapId = this._activeMapId
    const sceneId = this._activeSceneId
    const focusEntityId = this._focusEntityId
    const focusedDynamicItemId = this._focusedDynamicItemId
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
    this._updateDynamicSummaryDom()
    try {
      const [dashboard, playback] = await Promise.all([
        api.world.getMapDashboard(
          mapId,
          state.currentProjectId,
          sceneId,
          focusEntityId,
          focusedDynamicItemId,
        ),
        api.world.getMapPlayback(
          mapId,
          state.currentProjectId,
          sceneId,
          focusEntityId,
          true,
        ),
      ])
      if (this._activeMapId !== mapId) return
      this._dynamicSummary = {
        mapId,
        sceneId,
        focusEntityId,
        focusedDynamicItemId,
        loading: false,
        loaded: true,
        dashboard,
        observations: (dashboard.dynamic_queue || [])
          .filter((item) => item.item_kind === "observation"),
        facts: (dashboard.dynamic_queue || [])
          .filter((item) => item.item_kind === "fact"),
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
      this._rebuildDynamicIndexes()
    } catch (err) {
      if (this._activeMapId !== mapId) return
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
      this._rebuildDynamicIndexes()
      toast(`地图动态事实暂不可用：${err.message || "加载失败"}`, "warning")
    }
    this._updateDynamicSummaryDom()
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
    const name = item?.title || item?.target_name || "地图映射"
    return confirmAction(`确认地图映射「${name}」为正式事实？`, async () => {
      try {
        await api.world.confirmMapObservation(this._activeMapId, id, state.currentProjectId)
        toast("地图事实已确认", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        toast(`确认失败：${err.message || "未知错误"}`, "error")
      }
    })
  },

  async _ignoreObservation(id) {
    const item = this._dynamicObservation(id)
    const name = item?.title || item?.target_name || "地图映射"
    return confirmAction(`忽略地图映射「${name}」？`, async () => {
      try {
        await api.world.ignoreMapObservation(this._activeMapId, id, state.currentProjectId)
        toast("地图映射已忽略", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        toast(`忽略失败：${err.message || "未知错误"}`, "error")
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
    this._schedulePlaybackAdvance()
  },

  _stopPlayback() {
    this._playback = {
      ...this._playback,
      playing: false,
    }
    this._updateWorkspaceLayoutDom()
  },

  _findDynamicItem(id) {
    const indexes = this._dynamicIndex()
    return indexes.byItemId.get(id) || indexes.playbackEventsById.get(id)
      || this._rebuildDynamicIndexes().byItemId.get(id)
      || this._dynamicIndexes.playbackEventsById.get(id)
  },

  _actionLabel(action) {
    return {
      confirm: "可确认",
      ignore: "可忽略",
      conflict: "可标记冲突",
      rollback: "可回滚",
      deprecated: "可废弃",
    }[action] || action
  },

  _showDynamicObjectInfo(id) {
    const item = this._findDynamicItem(id)
    if (!item) return
    const title = item.title || "地图对象"
    const status = item.status_label || "待判断"
    const time = item.time_label || "时间待确认"
    const summary = item.change_summary || item.source_summary || "暂无来源摘要"
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
          <div class="map-detail-value">${esc(status)}</div>
        </div>
        <div class="map-detail-section">
          <div class="map-detail-label">来源</div>
          <div class="map-detail-value">${esc(summary)}</div>
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
    const jsonValue = (value) => esc(JSON.stringify(value || {}, null, 2))
    const observationFields = isFact ? "" : `
      <div class="form-group">
        <label>目标名称</label>
        <input class="form-input" id="map-object-edit-target-name" value="${esc(item.target_name || item.title || "")}" />
      </div>
      <div class="form-group">
        <label>目标类型</label>
        <input class="form-input" id="map-object-edit-target-type" value="${esc(item.target_entity_type || item.object_type || "")}" />
      </div>
      <div class="form-group">
        <label>动态类型</label>
        <input class="form-input" id="map-object-edit-dynamic-type" value="${esc(item.dynamic_type || item.object_type || "")}" />
      </div>
      <div class="form-group">
        <label>置信度</label>
        <input class="form-input" id="map-object-edit-confidence" type="number" min="0" max="1" step="0.01" value="${esc(item.confidence ?? "")}" />
      </div>
      <div class="form-group">
        <label>时间锚点 JSON</label>
        <textarea class="form-textarea" id="map-object-edit-time-anchor" rows="3">${jsonValue(item.time_anchor)}</textarea>
      </div>
      <div class="form-group">
        <label>空间锚点 JSON</label>
        <textarea class="form-textarea" id="map-object-edit-spatial-anchor" rows="3">${jsonValue(item.spatial_anchor)}</textarea>
      </div>
      <div class="form-group">
        <label>字段差异 JSON</label>
        <textarea class="form-textarea" id="map-object-edit-value-json" rows="4">${jsonValue(item.value_json)}</textarea>
      </div>
      <div class="form-group">
        <label>来源引用 JSON</label>
        <textarea class="form-textarea" id="map-object-edit-source-ref" rows="3">${jsonValue(item.source_ref)}</textarea>
      </div>
      <div class="form-group">
        <label>证据文本</label>
        <textarea class="form-textarea" id="map-object-edit-evidence" rows="3">${esc(item.evidence_text || item.source_summary || "")}</textarea>
      </div>
    `
    const formHtml = `
      <div class="form-group">
        <label>对象</label>
        <input class="form-input" value="${esc(item.title || "地图对象")}" disabled />
      </div>
      <div class="form-group">
        <label>${isFact ? "事实状态" : "候选状态"}</label>
        <select class="form-select" id="map-object-edit-status">
          ${isFact
            ? ["confirmed", "rolled_back", "deprecated"].map((value) => `<option value="${value}" ${value === statusValue ? "selected" : ""}>${esc(this._factStatusLabel(value))}</option>`).join("")
            : [
                ["candidate", "待确认"],
                ["ignored", "已忽略"],
                ["conflicted", "冲突"],
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
            payload = this._readObservationEditPayload(nextStatus)
          } catch (err) {
            toast(err.message || "地图候选字段格式不正确", "error")
            return
          }
          closeModal()
          await this._updateObservationReview(item.item_id, payload)
        }
      },
    }])
  },

  _readObservationEditPayload(reviewState) {
    const value = (id) => document.getElementById(id)?.value?.trim() || ""
    const payload = {
      review_state: reviewState || "candidate",
      target_name: value("map-object-edit-target-name") || null,
      target_entity_type: value("map-object-edit-target-type") || null,
      dynamic_type: value("map-object-edit-dynamic-type") || "state_change",
      time_anchor: this._readJsonField("map-object-edit-time-anchor"),
      spatial_anchor: this._readJsonField("map-object-edit-spatial-anchor"),
      value_json: this._readJsonField("map-object-edit-value-json"),
      source_ref: this._readJsonField("map-object-edit-source-ref"),
      evidence_text: value("map-object-edit-evidence") || null,
    }
    const confidence = value("map-object-edit-confidence")
    if (confidence !== "") payload.confidence = Number(confidence)
    return payload
  },

  _readJsonField(id) {
    const raw = document.getElementById(id)?.value?.trim()
    if (!raw) return {}
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed
    } catch {
      // handled below with a field-specific error
    }
    throw new Error(`${id} 必须是 JSON 对象`)
  },

  _dynamicObjectActions(item) {
    if (item.item_kind === "observation") {
      return [
        {
          text: "确认",
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
          text: "恢复确认",
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
        await api.world.updateMapObservationReview(this._activeMapId, id, state.currentProjectId, "conflicted")
        toast("地图映射已标记为冲突", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        toast(`标记失败：${err.message || "未知错误"}`, "error")
      }
    })
  },

  _reviewStateLabel(reviewState) {
    const state = typeof reviewState === "object" ? reviewState?.review_state : reviewState
    return {
      candidate: "待确认",
      ignored: "已忽略",
      conflicted: "冲突",
    }[state] || state || "待确认"
  },

  async _updateObservationReview(id, reviewState) {
    const item = this._dynamicObservation(id)
    const name = item?.title || item?.target_name || "地图映射"
    const label = this._reviewStateLabel(reviewState)
    return confirmAction(`将地图映射「${name}」设为${label}？`, async () => {
      try {
        await api.world.updateMapObservationReview(this._activeMapId, id, state.currentProjectId, reviewState)
        toast("地图映射已更新", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        toast(`更新失败：${err.message || "未知错误"}`, "error")
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
      confirmed: "已确认",
      rolled_back: "已回滚",
      deprecated: "已废弃",
    }[status] || "待判断"
  },

  async _openFocusedInspector(focusEntityId, dynamicItemId = null) {
    this._focusedDynamicItemId = dynamicItemId
    if (!focusEntityId) {
      await this._loadDynamicSummary({ force: true })
      toast("检查器已在右侧显示", "info")
      return
    }
    this._focusEntityId = focusEntityId
    await this._loadDynamicSummary({ force: true })
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
      toast("该分组暂无待处理候选", "info")
      return
    }
    const label = { confirm: "确认", ignore: "忽略", conflict: "标记冲突" }[action] || "处理"
    return confirmAction(`${label}该分组的 ${ids.length} 条地图候选？`, async () => {
      try {
        const apiAction = {
          confirm: "confirm_observations",
          ignore: "ignore_observations",
          conflict: "mark_conflicted",
        }[action]
        await api.world.runMapBatchAction(this._activeMapId, state.currentProjectId, {
          action: apiAction,
          observation_ids: ids,
        })
        toast("批量修改已完成", "success")
        await this._loadDynamicSummary({ force: true })
      } catch (err) {
        toast(`批量修改失败：${err.message || "未知错误"}`, "error")
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
      } else {
        this._playback = { ...this._playback, activeIndex: nextIndex }
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
    root.onclick = (e) => {
      const target = e.target.closest("[data-action]")
      if (!target) return
      const action = target.dataset.action
      if (action === "map-open-recent") this._openRecentMap()
      if (action === "map-open") this._openMap(target.dataset.id, { viewMode: "live" })
      if (action === "map-search-location") this._openLocation(target.dataset.id)
      if (action === "map-quick-create") this._openQuickCreate()
      if (action === "map-create-world") this._showCreateWorldForm()
      if (action === "map-confirm-observation") this._confirmObservation(target.dataset.id)
      if (action === "map-ignore-observation") this._ignoreObservation(target.dataset.id)
      if (action === "map-view-mode") this._setViewMode(target.dataset.viewMode)
      if (action === "map-playback-start") this._startPlayback()
      if (action === "map-playback-stop") this._stopPlayback()
      if (action === "map-batch-review") this._batchReviewGroup(target.dataset.group, target.dataset.reviewAction)
      if (action === "map-open-dynamic-item") {
        this._showDynamicObjectInfo(target.dataset.id)
      }
      if (action === "map-overview") {
        this._mode = "overview"
        this._activeMapId = null
        this._resetDynamicSummary()
        mapView.unmount()
        router.refresh?.()
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

  async _openQuickCreate() {
    await mapQuickCreateView.open({
      onCreated: async (map) => {
        await this._loadData()
        this._openMap(map.id, { viewMode: "live" })
      },
    })
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
