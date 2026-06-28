/**
 * 地图一级工作台。
 */
import mapView from "./mapView.js"
import { parseMapRouteContext } from "./mapRouteContext.js"

const RECENT_PREFIX = "novel_map_recent:"

const DEFAULT_LAYERS = {
  terrain: true,
  locations: true,
  markers: true,
  events: true,
  items: true,
  territories: true,
}

const mapWorkspaceView = {
  _maps: [],
  _locations: [],
  _mode: "overview",
  _message: null,
  _activeMapId: null,
  _activeSceneId: null,
  _focusEntityId: null,
  _layers: { ...DEFAULT_LAYERS },
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
    if (context.mode === "map" && context.mapId) {
      this._mode = "map"
      this._activeMapId = context.mapId
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
    } else if (context.mode === "recent") {
      this._activeSceneId = context.sceneId
      this._focusEntityId = context.focusEntityId
      this._defer(() => this._openRecentMap())
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
      return
    }
    const [maps, locations] = await Promise.all([
      api.world.listMaps({ novel_id: state.currentProjectId }).catch(() => ({ items: [] })),
      this._listAllLocations().catch(() => []),
    ])
    this._maps = maps.items || maps || []
    this._locations = locations.items || locations || []
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

  async _openRecentMap() {
    const recent = this._getRecentMap()
    if (!recent?.mapId) {
      this._message = "最近地图不可用，已返回地图总览"
      toast(this._message, "warning")
      this._mode = "overview"
      router.refresh?.()
      return
    }
    try {
      const map = await api.world.getMap(recent.mapId, state.currentProjectId)
      this._openMap(map.id, {
        sceneId: this._activeSceneId,
        focusEntityId: this._focusEntityId,
      })
      this._saveRecentMap(map)
    } catch {
      this._clearRecentMap()
      this._message = "最近地图不可用，已返回地图总览"
      toast(this._message, "warning")
      this._mode = "overview"
      router.refresh?.()
    }
  },

  _openMap(mapId, { sceneId = null, focusEntityId = null } = {}) {
    this._mode = "map"
    this._activeMapId = mapId
    this._activeSceneId = sceneId
    this._focusEntityId = focusEntityId
    const map = this._maps.find((m) => m.id === mapId)
    if (map) this._saveRecentMap(map)
    router.refresh?.()
  },

  _openLocation(locationId) {
    const detailMap = this._maps.find((m) => m.parent_entity_id === locationId)
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
    const children = this._maps.filter((m) => (m.parent_map_id || null) === parentId)
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
          ${this._renderLayerToggles()}
        </div>
        <div id="map-root" class="map-root"></div>
      </div>
    `
  },

  _mountMap() {
    mapView.mount("map-root", {
      mapId: this._activeMapId,
      sceneId: this._activeSceneId,
      focusEntityId: this._focusEntityId,
      mode: this._activeMapId ? "map" : "overview",
      layers: this._layers,
      onMapOpened: (map) => this._saveRecentMap(map),
    })
    this._bindEvents()
  },

  _bindEvents() {
    const root = document.getElementById("workspace-content")
    if (!root) return
    root.onclick = (e) => {
      const target = e.target.closest("[data-action]")
      if (!target) return
      const action = target.dataset.action
      if (action === "map-open-recent") this._openRecentMap()
      if (action === "map-open") this._openMap(target.dataset.id)
      if (action === "map-search-location") this._openLocation(target.dataset.id)
      if (action === "map-create-world") this._showCreateWorldForm()
      if (action === "map-overview") {
        this._mode = "overview"
        this._activeMapId = null
        mapView.unmount()
        router.refresh?.()
      }
    }
    root.querySelectorAll("[data-action='map-layer-toggle']").forEach((input) => {
      input.onchange = () => this._setLayer(input.dataset.layer, input.checked)
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
          this._openMap(created.id)
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
