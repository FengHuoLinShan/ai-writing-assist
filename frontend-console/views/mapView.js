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
  hexToPixel,
  pixelToHex,
  floodFillTerrain,
  TERRAIN_COLORS,
} from "./mapHexRenderer.js"
import renderEditPanel, { updatePendingCount, updateBindingPendingCount, toggleToolSections } from "./mapEditPanel.js"
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import {
  mapState,
  resetMapState,
  stageTerrainChange,
  stageBindingChange,
  consumePendingChanges,
  
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
  /** 可绑定的 location 实体列表 */
  _locations: [],
  /** canvas 偏移（地图坐标原点到画布原点），用于平移 */
  _offset: { x: 0, y: 0 },
  /** 浏览模式 tooltip 防抖 timer */
  _tooltipDebounceTimer: null,
  /** Leaflet popup 实例 */
  _tooltipPopup: null,
  /** 拖拽绘制中是否已移动到新格（用于区分单击和拖拽） */
  _dragMoved: false,
  /** 当前侧边栏筛选模式 ("all" | "location") */
  _currentFilter: "all",

  // ============================================================
  // 生命周期：由 worldView 调用
  // ============================================================

  /**
   * 挂载到容器。worldView._renderMap 提供 #map-root 后调用。
   * @param {string} rootId
   */
  async mount(rootId) {
    if (!window.L) {
      const root = document.getElementById(rootId)
      if (root) root.innerHTML = `<div class="empty-state"><div class="empty-icon" style="color:var(--danger);">&#9888;</div><p>地图引擎加载失败</p><p style="color:var(--text-dim);font-size:12px;">Leaflet 未加载，请检查网络连接（ADR-0003）</p></div>`
      return
    }
    await this._loadMaps()
    this._render(rootId)
  },

  /** 退出时清理 Leaflet 实例 */
  unmount() {
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
    this._canvas = null
    this._ctx = null
    this._state = null
    if (this._keyHandler) {
      document.removeEventListener("keydown", this._keyHandler)
      this._keyHandler = null
    }
    resetMapState()
  },

  // ============================================================
  // 数据加载
  // ============================================================

  async _loadMaps() {
    if (!state.currentProjectId) {
      this._maps = []
      return
    }
    try {
      const data = await api.world.listMaps({ novel_id: state.currentProjectId })
      this._maps = data.items || []
    } catch {
      this._maps = []
    }
  },

  async _loadMapState(mapId) {
    try {
      this._state = await api.world.getMapState(mapId, state.currentProjectId)
      resetMapState()
      mapState.currentMapId = mapId
    } catch (err) {
      toast(`加载地图失败：${err.message}`, "error")
      this._state = null
    }
  },

  async _loadLocations() {
    try {
      const data = await api.world.listEntities({
        novel_id: state.currentProjectId,
        entity_type: "location",
        limit: 100,
      })
      this._locations = data.items || data || []
    } catch {
      this._locations = []
    }
  },

  // ============================================================
  // 渲染
  // ============================================================

  _render(rootId) {
    const root = document.getElementById(rootId)
    if (!root) return

    if (this._maps.length === 0 && !this._state) {
      // 空列表：显示创建入口
      root.innerHTML = this._renderEmpty()
      setTimeout(() => this._bindListEvents(), 0)
      return
    }

    if (!this._state) {
      // 有列表但未选地图：显示列表
      root.innerHTML = this._renderList()
      setTimeout(() => this._bindListEvents(), 0)
      return
    }

    // 已选地图：渲染地图视图
    root.innerHTML = this._renderMapShell()
    setTimeout(() => this._initLeaflet(), 0)
    setTimeout(() => this._bindMapEvents(), 0)
  },

  _renderEmpty() {
    return `
      <div class="map-toolbar">
        <button class="btn btn-primary" data-action="map-create-world">+ 创建世界地图</button>
      </div>
      <div class="empty-state">
        <div class="empty-icon">&#9744;</div>
        <p>暂无地图</p>
        <p style="color:var(--text-dim);font-size:12px;">创建第一张世界地图开始构建你的世界</p>
      </div>
    `
  },

  _renderList() {
    const rows = this._maps.map((m) => `
      <tr class="clickable" data-action="map-open" data-id="${esc(m.id)}">
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
      <table class="data-table">
        <thead><tr><th>名称</th><th>类型</th><th>尺寸</th><th>操作</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
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
      ? renderEditPanel({ locations: this._locations })
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
      <div class="map-filter-bar">
        <span class="badge badge-canonical map-filter active" data-action="map-filter" data-filter="all">全部</span>
        <span class="badge map-filter" data-action="map-filter" data-filter="location">地点</span>
      </div>
    `
  },

  _renderDetailPanel(q, r) {
    const binding = (this._state.location_bindings || []).find((b) => b.hex_q === q && b.hex_r === r && b.is_center)
    if (binding) {
      const loc = this._locations.find((l) => l.id === binding.location_entity_id)
      const name = loc ? loc.name : "未命名地点"
      const summary = loc && loc.summary ? loc.summary : "暂无摘要"
      const bindingCount = (this._state.location_bindings || []).filter(
        (b) => b.location_entity_id === binding.location_entity_id
      ).length
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
    const tile = (this._state.tiles || []).find((t) => t.hex_q === q && t.hex_r === r)
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
    this._canvas.width = container.clientWidth
    this._canvas.height = container.clientHeight
    this._canvas.style.position = "absolute"
    this._canvas.style.top = "0"
    this._canvas.style.left = "0"
    this._canvas.style.pointerEvents = "auto"
    this._canvas.style.zIndex = "400"
    container.getElementsByClassName("leaflet-overlay-pane")[0]?.appendChild(this._canvas)
    this._ctx = this._canvas.getContext("2d")

    // 初始偏移：把地图坐标原点放到容器左上偏移一点
    this._offset = { x: size * 2, y: size * 2 }
    this._redraw()

    // 平移/缩放时同步 canvas 变换
    this._leaflet.on("zoom move zoomend moveend", () => this._redraw())

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

  /** Leaflet 视口变换 → 计算 canvas 偏移/缩放，重绘 */
  _redraw() {
    if (!this._ctx || !this._canvas || !this._state) return
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
    drawTerrain(this._ctx, this._state.tiles, size, 0, 0)
    drawBindings(this._ctx, this._state.location_bindings, size, 0, 0, showBoundary)

    // 待应用变更叠加在基础地形之上
    drawPendingTerrain(this._ctx, mapState.pendingTerrainChanges, size, 0, 0)
    drawPendingBindings(this._ctx, mapState.pendingBindings, size, 0, 0)

    // 悬停高亮
    if (mapState.hoveredHex) {
      drawHoverHighlight(this._ctx, mapState.hoveredHex.hex_q, mapState.hoveredHex.hex_r, size, 0, 0)
    }

    // 浏览模式：绘制中心点标签（DOM marker）
    this._renderCenterLabels()

    this._ctx.restore()
  },

  /** 中心点标签用 DOM（便于显示文字），通过 data-action 委托点击 */
  _renderCenterLabels() {
    if (!this._leaflet || !this._state) return
    // 清理旧标签
    this._leaflet.eachLayer((layer) => {
      if (layer._isMapLabel) this._leaflet.removeLayer(layer)
    })
    if (mapState.mode === "edit") return // 编辑模式不显示标签

    const cfg = this._state.map
    const size = cfg.hex_size || 30
    for (const b of this._state.location_bindings) {
      if (!b.is_center) continue
      const [x, y] = hexToPixel(b.hex_q, b.hex_r, size)
      // latLng: CRS.Simple 中 y 是 lat，x 是 lng
      const latlng = window.L.latLng(y, x)
      const label = b.label_override || this._locationName(b.location_entity_id)
      const hasDetail = this._hasDetailMap(b.location_entity_id)
      const icon = window.L.divIcon({
        className: "map-center-marker",
        html: `<div class="map-center-label" data-action="map-click-center" data-id="${esc(b.location_entity_id)}">
                 <span class="map-center-name">${esc(label)}</span>
                 <span class="map-center-drill ${hasDetail ? "has-detail" : ""}">${hasDetail ? "▾" : "·"}</span>
               </div>`,
        iconSize: [80, 24],
        iconAnchor: [40, 12],
      })
      const marker = window.L.marker(latlng, { icon })
      marker._isMapLabel = true
      marker.addTo(this._leaflet)
    }
  },

  _locationName(entityId) {
    const loc = this._locations.find((l) => l.id === entityId)
    return loc ? loc.name : "未命名地点"
  },

  _hasDetailMap(entityId) {
    return this._maps.some(
      (m) => m.parent_entity_id === entityId
    )
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
    // 点击地点中心已在 _renderCenterLabels 的 data-action 处理
    // 这里处理点击无地点格 → 显示地形信息
    const tile = (this._state.tiles || []).find((t) => t.hex_q === q && t.hex_r === r)
    const binding = (this._state.location_bindings || []).find((b) => b.hex_q === q && b.hex_r === r)
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
      const t = (this._state.tiles || []).find((x) => x.hex_q === qq && x.hex_r === rr)
      return t ? t.terrain_type : null
    }
    const target = getTerrain(q, r)
    if (!target) return
    const changes = floodFillTerrain(q, r, target, terrain, getTerrain)
    for (const c of changes) stageTerrainChange(c.hex_q, c.hex_r, c.terrain_type)
    updatePendingCount(Object.keys(mapState.pendingTerrainChanges).length)
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
    const binding = (this._state.location_bindings || []).find((b) => b.hex_q === q && b.hex_r === r)
    const tile = (this._state.tiles || []).find((t) => t.hex_q === q && t.hex_r === r)
    if (binding) {
      const name = this._locationName(binding.location_entity_id)
      const centerTag = binding.is_center ? "（中心）" : ""
      return `<div class="map-tooltip-title">${esc(name)}${centerTag}</div><div class="map-tooltip-sub">${esc(tile ? tile.terrain_type : "")}</div>`
    }
    if (tile) {
      return `<div class="map-tooltip-title">${esc(tile.terrain_type)}</div><div class="map-tooltip-sub">q:${q}, r:${r}</div>`
    }
    return ""
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindListEvents() {
    bindWorkspaceClick(this, {
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
      "map-undo": () => this._undo(),
      "map-apply": () => this._applyAllChanges(),
      "map-save": () => this._saveAndExit(),
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
    this.unmount()
    await this._loadMapState(mapId)
    await this._loadLocations()
    this._render("map-root")
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

  async _enterEdit() {
    await this._loadLocations()
    this.unmount()
    mapState.mode = "edit"
    this._render("map-root")
  },

  _exitEdit() {
    mapState.pendingTerrainChanges = {}
    mapState.pendingBindings = {}
    updatePendingCount(0)
    updateBindingPendingCount(0)
    mapState.mode = "browse"
    this._render("map-root")
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
      await this._loadMapState(this._state.map.id)
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
    mapState.mode = "browse"
    this._render("map-root")
    toast("已保存", "success")
  },

  _onCenterClick(entityId) {
    // 点击中心点：有详图则下钻，无则提示创建
    if (this._hasDetailMap(entityId)) {
      const detail = this._maps.find((m) => m.parent_entity_id === entityId)
      if (detail) this._openMap(detail.id)
    } else {
      confirmAction(
        `为该地点创建详图？`,
        () => this._showCreateDetailForm(entityId),
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
    const loc = this._locations.find((l) => l.id === entityId)
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
            await api.world.generateMap(created.id, state.currentProjectId)
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
}

export default mapView
