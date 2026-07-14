/**
 * 地图快速创建 modal 控制器。
 */

import { applyLayoutResize } from "./mapGeoLayoutEngine.js"

const mapQuickCreateView = {
  _context: null,
  _preview: null,
  _activeLayouts: [],
  _layoutHistory: [],
  _layoutRedo: [],
  _selectedLocationIds: new Set(),
  _previousLayoutIds: new Set(),
  _includeCandidates: false,
  _target: "world",
  _parentEntityId: null,
  _parentMapId: null,
  _replaceMapId: null,
  _extraLocationIds: new Set(),
  _mapType: "world",
  _gridWidth: 40,
  _gridHeight: 30,
  _baseTemplate: "blank",
  _dragLocationId: null,
  _onCreated: null,

  async open({ onCreated = null } = {}) {
    this._onCreated = onCreated
    this._includeCandidates = false
    this._activeLayouts = []
    this._layoutHistory = []
    this._layoutRedo = []
    this._selectedLocationIds = new Set()
    this._previousLayoutIds = new Set()
    this._target = "world"
    this._parentEntityId = null
    this._parentMapId = null
    this._replaceMapId = null
    this._extraLocationIds = new Set()
    this._mapType = "world"
    this._gridWidth = 40
    this._gridHeight = 30
    this._baseTemplate = "blank"
    await this._loadContext()
    await this._loadPreview()
    this._showModal()
  },

  async setIncludeCandidates(enabled) {
    const previous = this._snapshotPreviewState()
    this._includeCandidates = Boolean(enabled)
    try {
      await this._loadContext()
      await this._loadPreview()
      this._updateModalDom()
      return true
    } catch (err) {
      this._restorePreviewState(previous)
      this._updateModalDom()
      toast(`快速创建预览刷新失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async setTarget(target) {
    const previous = this._snapshotPreviewState()
    this._target = target || "world"
    if (this._target === "world") {
      this._parentEntityId = null
      this._parentMapId = null
      this._mapType = "world"
    } else {
      this._parentEntityId ||= this._context?.locations?.[0]?.id || null
      this._mapType = "region"
      if (this._target === "drilldown") {
        this._parentMapId ||= this._context?.existing_maps?.[0]?.id || null
      } else {
        this._parentMapId = null
      }
    }
    try {
      await this._loadPreview()
      this._updateModalDom()
      return true
    } catch (err) {
      this._restorePreviewState(previous)
      this._updateModalDom()
      toast(`快速创建预览刷新失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  _snapshotPreviewState() {
    return {
      context: this._context,
      preview: this._preview,
      activeLayouts: this._activeLayouts.map((layout) => ({ ...layout })),
      layoutHistory: this._layoutHistory.map((entry) => entry.map((layout) => ({ ...layout }))),
      layoutRedo: this._layoutRedo.map((entry) => entry.map((layout) => ({ ...layout }))),
      selectedLocationIds: new Set(this._selectedLocationIds),
      previousLayoutIds: new Set(this._previousLayoutIds),
      includeCandidates: this._includeCandidates,
      target: this._target,
      parentEntityId: this._parentEntityId,
      parentMapId: this._parentMapId,
      replaceMapId: this._replaceMapId,
      extraLocationIds: new Set(this._extraLocationIds),
      mapType: this._mapType,
      gridWidth: this._gridWidth,
      gridHeight: this._gridHeight,
      baseTemplate: this._baseTemplate,
    }
  },

  _restorePreviewState(snapshot) {
    this._context = snapshot.context
    this._preview = snapshot.preview
    this._activeLayouts = snapshot.activeLayouts
    this._layoutHistory = snapshot.layoutHistory
    this._layoutRedo = snapshot.layoutRedo
    this._selectedLocationIds = snapshot.selectedLocationIds
    this._previousLayoutIds = snapshot.previousLayoutIds
    this._includeCandidates = snapshot.includeCandidates
    this._target = snapshot.target
    this._parentEntityId = snapshot.parentEntityId
    this._parentMapId = snapshot.parentMapId
    this._replaceMapId = snapshot.replaceMapId
    this._extraLocationIds = snapshot.extraLocationIds
    this._mapType = snapshot.mapType
    this._gridWidth = snapshot.gridWidth
    this._gridHeight = snapshot.gridHeight
    this._baseTemplate = snapshot.baseTemplate
  },

  async _loadContext() {
    this._context = await api.world.getMapQuickCreateContext(
      state.currentProjectId,
      this._includeCandidates,
    )
  },

  async _loadPreview() {
    this._preview = await api.world.previewQuickCreateMap(this._previewPayload(), state.currentProjectId)
    this._gridWidth = Number(this._preview?.map?.grid_width || this._gridWidth)
    this._gridHeight = Number(this._preview?.map?.grid_height || this._gridHeight)
    this._mapType = this._preview?.map?.map_type || this._mapType
    this._activeLayouts = this._computePreviewLayouts()
    this._syncSelectionForLayouts(this._activeLayouts)
    this._layoutHistory = []
    this._layoutRedo = []
  },

  _previewPayload() {
    return {
      target: this._target,
      parent_entity_id: this._parentEntityId,
      parent_map_id: this._parentMapId,
      replace_map_id: this._replaceMapId,
      map_type: this._replaceMapId ? undefined : this._mapType,
      grid_width: this._replaceMapId ? undefined : Number(this._gridWidth),
      grid_height: this._replaceMapId ? undefined : Number(this._gridHeight),
      base_template: this._baseTemplate,
      location_entity_ids: [...this._extraLocationIds],
      include_candidates: this._includeCandidates,
      include_markers: false,
    }
  },

  _showModal() {
    showModalHtml("快速创建地图", this._render(), [{
      text: "创建",
      class: "btn-primary",
      handler: async () => this._confirm(),
    }])
    this._bindModalEvents()
    this._drawCanvas()
  },

  _render() {
    const preview = this._preview || { location_layouts: [], warnings: [], map: {} }
    const locations = this._context?.locations || []
    const maps = this._context?.existing_maps || []
    const parentOptions = locations.map((location) => (
      `<option value="${esc(location.id)}" ${this._parentEntityId === location.id ? "selected" : ""}>${esc(location.name)}</option>`
    )).join("")
    const mapOptions = maps.map((map) => (
      `<option value="${esc(map.id)}" ${this._parentMapId === map.id ? "selected" : ""}>${esc(map.name)}</option>`
    )).join("")
    const replaceOptions = maps.map((map) => (
      `<option value="${esc(map.id)}" ${this._replaceMapId === map.id ? "selected" : ""}>替换：${esc(map.name)}（${map.grid_width}×${map.grid_height}）</option>`
    )).join("")
    const activeIds = new Set((this._activeLayouts || []).map((layout) => layout.location_entity_id))
    const extraOptions = locations.filter((location) => !activeIds.has(location.id)).map((location) => (
      `<option value="${esc(location.id)}">${esc(location.name)}</option>`
    )).join("")
    return `
      <div class="map-quick-create">
        <div class="map-quick-settings">
          <div class="form-group">
            <label>创建目标</label>
            <select class="form-select" id="map-quick-target" ${this._replaceMapId ? "disabled" : ""}>
              <option value="world" ${this._target === "world" ? "selected" : ""}>世界地图</option>
              <option value="detail" ${this._target === "detail" ? "selected" : ""}>地点详图</option>
              <option value="drilldown" ${this._target === "drilldown" ? "selected" : ""}>下钻地图</option>
            </select>
          </div>
          ${this._target !== "world" ? `
            <div class="form-group"><label>父地点</label><select class="form-select" id="map-quick-parent-entity" ${this._replaceMapId ? "disabled" : ""}><option value="">请选择</option>${parentOptions}</select></div>
          ` : ""}
          ${this._target === "drilldown" ? `
            <div class="form-group"><label>父地图</label><select class="form-select" id="map-quick-parent-map" ${this._replaceMapId ? "disabled" : ""}><option value="">请选择</option>${mapOptions}</select></div>
          ` : ""}
          <div class="form-group"><label>创建方式</label><select class="form-select" id="map-quick-replace"><option value="">创建新地图</option>${replaceOptions}</select></div>
          <div class="form-group"><label>地图名称</label><input class="form-input" id="map-quick-name" value="${esc(preview.map?.name || "")}" ${this._replaceMapId ? "disabled" : ""}/></div>
          <div class="form-group"><label>地图类型</label><select class="form-select" id="map-quick-type" ${this._replaceMapId ? "disabled" : ""}>
            ${["world", "city", "region", "dungeon"].map((type) => `<option value="${type}" ${this._mapType === type ? "selected" : ""}>${type}</option>`).join("")}
          </select></div>
          <div class="form-group"><label>网格</label><div class="map-quick-grid-inputs"><input class="form-input" id="map-quick-width" type="number" min="1" max="200" value="${this._gridWidth}" ${this._replaceMapId ? "disabled" : ""}/><span>×</span><input class="form-input" id="map-quick-height" type="number" min="1" max="200" value="${this._gridHeight}" ${this._replaceMapId ? "disabled" : ""}/></div></div>
          <div class="form-group"><label>底图模板</label><select class="form-select" id="map-quick-template" ${this._replaceMapId ? "disabled" : ""}><option value="blank" ${this._baseTemplate === "blank" ? "selected" : ""}>空白</option><option value="continent" ${this._baseTemplate === "continent" ? "selected" : ""}>大陆</option><option value="islands" ${this._baseTemplate === "islands" ? "selected" : ""}>群岛</option></select></div>
          <div class="form-group"><label>添加其他已采用地点</label><input class="form-input" id="map-quick-extra-search" type="search" placeholder="搜索地点名称" ${extraOptions ? "" : "disabled"}/><div class="map-quick-extra-row"><select class="form-select" id="map-quick-extra"><option value="">选择地点...</option>${extraOptions}</select><button class="btn btn-sm" id="map-quick-extra-add" ${extraOptions ? "" : "disabled"}>添加</button></div></div>
        </div>
        <label class="map-layer-toggle">
          <input type="checkbox" id="map-quick-include-candidates" ${this._includeCandidates ? "checked" : ""} />
          包含待处理地点
        </label>
        <div id="map-quick-preview">
          ${this._renderPreviewTable()}
        </div>
      </div>
    `
  },

  _computePreviewLayouts() {
    const preview = this._preview || { location_layouts: [], map: {} }
    return (preview.location_layouts || []).map((layout) => ({ ...layout }))
  },

  _syncSelectionForLayouts(layouts) {
    const nextIds = new Set((layouts || []).map((layout) => layout.location_entity_id))
    const selected = new Set()
    for (const id of this._selectedLocationIds || []) {
      if (nextIds.has(id)) selected.add(id)
    }
    for (const id of nextIds) {
      const layout = (layouts || []).find((item) => item.location_entity_id === id)
      if (!this._previousLayoutIds.has(id) && !this._isCandidateLayout(layout)) selected.add(id)
    }
    this._selectedLocationIds = selected
    this._previousLayoutIds = nextIds
  },

  _selectedLayouts() {
    const selected = this._selectedLocationIds || new Set()
    return (this._activeLayouts || []).filter((layout) => (
      selected.has(layout.location_entity_id)
    ))
  },

  _selectedCount() {
    return this._selectedLayouts().length
  },

  _isCandidateLayout(layout) {
    if (!layout) return false
    const status = layout.meta?.entity_status
    if (status && status !== "canonical") return true
    return (this._context?.candidate_locations || []).some(
      (location) => location.id === layout.location_entity_id,
    )
  },

  _renderRows() {
    const layouts = this._activeLayouts || []
    const selectedIds = this._selectedLocationIds || new Set()
    return layouts.map((layout) => {
      const id = layout.location_entity_id
      const candidate = this._isCandidateLayout(layout)
      const selected = !candidate && selectedIds.has(id)
      const disabled = selected && !layout.locked ? "" : "disabled"
      const lockDisabled = selected ? "" : "disabled"
      return `
      <tr class="${selected ? "" : "map-quick-row-unselected"} ${candidate ? "is-candidate" : ""}">
        <td>
          <input type="checkbox" data-action="map-quick-select" data-id="${esc(id)}" ${selected ? "checked" : ""} ${candidate ? "disabled" : ""}/>
        </td>
        <td>${esc(this._locationName(layout.location_entity_id))}</td>
        <td>${layout.center_hex_q}, ${layout.center_hex_r}</td>
        <td>
          <button class="btn btn-sm" data-action="map-quick-radius" data-id="${esc(id)}" data-direction="decrease" ${disabled}>-</button>
          ${layout.occupy_radius}
          <button class="btn btn-sm" data-action="map-quick-radius" data-id="${esc(id)}" data-direction="increase" ${disabled}>+</button>
        </td>
        <td>${candidate ? "待处理 · 只读预览" : selected ? (layout.locked ? "已锁定" : "可拖动") : "未选择"}</td>
        <td>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="-1" data-dr="0" ${disabled}>←</button>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="1" data-dr="0" ${disabled}>→</button>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="0" data-dr="-1" ${disabled}>↑</button>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="0" data-dr="1" ${disabled}>↓</button>
          <button class="btn btn-sm" data-action="map-quick-lock" data-id="${esc(id)}" ${lockDisabled}>${layout.locked ? "解锁" : "锁定"}</button>
        </td>
      </tr>
    `
    }).join("")
  },

  _renderPreviewTable() {
    const warnings = (this._preview?.warnings || []).map((warning) => (
      `<div class="alert alert-warning">${esc(warning)}</div>`
    )).join("")
    const rows = this._renderRows()
    const placeableLayouts = (this._activeLayouts || []).filter((layout) => !this._isCandidateLayout(layout))
    const total = placeableLayouts.length
    const selectedCount = this._selectedCount()
    const allSelected = total > 0 && selectedCount === total
    return `
      ${warnings}
      <div class="view-header map-toolbar">
        <div class="view-header__title">快速放置</div>
        <div class="view-header__actions">
          <button class="btn btn-sm" id="map-quick-undo" ${this._layoutHistory.length ? "" : "disabled"}>撤销</button>
          <button class="btn btn-sm" id="map-quick-redo" ${this._layoutRedo.length ? "" : "disabled"}>重做</button>
          <span class="view-header__count">已选 ${selectedCount} / 共 ${total}</span>
        </div>
      </div>
      <div class="map-quick-canvas-wrap"><canvas id="map-quick-canvas" class="map-quick-canvas" width="920" height="420" aria-label="地点布局画布"></canvas><p class="map-quick-meta">拖动已采用地点调整中心格；待处理地点仅供预览。</p></div>
      <table class="data-table">
        <thead><tr>
          <th><input type="checkbox" id="map-quick-select-all" ${allSelected ? "checked" : ""} ${total ? "" : "disabled"} /></th>
          <th>地点</th><th>位置</th><th>半径</th><th>状态</th><th>调整</th>
        </tr></thead>
        <tbody>${rows || `<tr><td colspan="6">暂无可放置地点</td></tr>`}</tbody>
      </table>
    `
  },

  _bindModalEvents() {
    const candidate = document.getElementById("map-quick-include-candidates")
    if (candidate) {
      candidate.onchange = () => this.setIncludeCandidates(candidate.checked)
    }
    const target = document.getElementById("map-quick-target")
    if (target) {
      target.onchange = () => this.setTarget(target.value)
    }
    const parentEntity = document.getElementById("map-quick-parent-entity")
    if (parentEntity) parentEntity.onchange = () => this._changeSetting("_parentEntityId", parentEntity.value || null)
    const parentMap = document.getElementById("map-quick-parent-map")
    if (parentMap) parentMap.onchange = () => this._changeSetting("_parentMapId", parentMap.value || null)
    const replace = document.getElementById("map-quick-replace")
    if (replace) replace.onchange = async () => {
      const previous = this._snapshotPreviewState()
      const map = (this._context?.existing_maps || []).find((item) => item.id === replace.value)
      this._replaceMapId = replace.value || null
      if (map) {
        this._target = this._targetForExistingMap(map)
        this._parentEntityId = map.parent_entity_id || null
        this._parentMapId = map.parent_map_id || null
        this._mapType = map.map_type
        this._gridWidth = map.grid_width
        this._gridHeight = map.grid_height
      }
      await this._reloadSettingsPreview(previous)
    }
    const mapType = document.getElementById("map-quick-type")
    if (mapType) mapType.onchange = () => this._changeSetting("_mapType", mapType.value)
    const width = document.getElementById("map-quick-width")
    const height = document.getElementById("map-quick-height")
    if (width) width.onchange = () => this._changeSetting("_gridWidth", Number(width.value))
    if (height) height.onchange = () => this._changeSetting("_gridHeight", Number(height.value))
    const template = document.getElementById("map-quick-template")
    if (template) template.onchange = () => this._changeSetting("_baseTemplate", template.value)
    const extraAdd = document.getElementById("map-quick-extra-add")
    const extraSearch = document.getElementById("map-quick-extra-search")
    if (extraSearch) extraSearch.oninput = () => {
      const select = document.getElementById("map-quick-extra")
      const query = extraSearch.value.trim().toLocaleLowerCase()
      for (const option of Array.from(select?.options || []).slice(1)) {
        option.hidden = Boolean(query) && !option.textContent.toLocaleLowerCase().includes(query)
      }
      if (select?.selectedOptions?.[0]?.hidden) select.value = ""
    }
    if (extraAdd) extraAdd.onclick = async () => {
      const select = document.getElementById("map-quick-extra")
      if (!select?.value) return
      const previous = this._snapshotPreviewState()
      this._extraLocationIds.add(select.value)
      await this._reloadSettingsPreview(previous)
    }
    const selectAll = document.getElementById("map-quick-select-all")
    if (selectAll) {
      const total = (this._activeLayouts || []).filter((layout) => !this._isCandidateLayout(layout)).length
      const selectedCount = this._selectedCount()
      selectAll.indeterminate = selectedCount > 0 && selectedCount < total
      selectAll.onchange = () => this._setAllSelected(selectAll.checked)
    }
    document.querySelectorAll("[data-action='map-quick-select']").forEach((checkbox) => {
      checkbox.onchange = () => this._toggleSelection(
        checkbox.dataset.id,
        checkbox.checked,
      )
    })
    document.querySelectorAll("[data-action='map-quick-radius']").forEach((button) => {
      button.onclick = () => this._resizeLocation(
        button.dataset.id,
        button.dataset.direction,
      )
    })
    document.querySelectorAll("[data-action='map-quick-move']").forEach((button) => {
      button.onclick = () => this._moveLocation(
        button.dataset.id,
        Number(button.dataset.dq),
        Number(button.dataset.dr),
      )
    })
    document.querySelectorAll("[data-action='map-quick-lock']").forEach((button) => {
      button.onclick = () => this._toggleLock(button.dataset.id)
    })
    const undo = document.getElementById("map-quick-undo")
    if (undo) undo.onclick = () => this._undoLayout()
    const redo = document.getElementById("map-quick-redo")
    if (redo) redo.onclick = () => this._redoLayout()
    this._bindCanvasEvents()
    this._syncCreateButton()
  },

  _targetForExistingMap(map) {
    if (map?.parent_map_id) return "drilldown"
    if (map?.parent_entity_id) return "detail"
    return "world"
  },

  _updatePreviewDom() {
    const container = document.getElementById("map-quick-preview")
    if (!container) return
    container.innerHTML = this._renderPreviewTable()
    this._bindModalEvents()
    this._drawCanvas()
  },

  _updateModalDom() {
    const container = document.querySelector(".map-quick-create")
    if (!container) return
    container.outerHTML = this._render()
    this._bindModalEvents()
    this._drawCanvas()
  },

  async _changeSetting(field, value) {
    const previous = this._snapshotPreviewState()
    this[field] = value
    return this._reloadSettingsPreview(previous)
  },

  async _reloadSettingsPreview(previous = this._snapshotPreviewState()) {
    try {
      await this._loadPreview()
      this._updateModalDom()
      return true
    } catch (err) {
      this._restorePreviewState(previous)
      this._updateModalDom()
      toast(`快速创建预览刷新失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  _syncCreateButton() {
    const footer = document.getElementById("modal-footer")
    if (!footer) return
    const createButton = Array.from(footer.querySelectorAll("button")).find(
      (button) => button.textContent === "创建",
    )
    if (!createButton) return
    const disabled = this._selectedCount() === 0
    createButton.disabled = disabled
    createButton.title = disabled ? "请至少选择一个地点" : ""
  },

  _setAllSelected(enabled) {
    this._selectedLocationIds = new Set(
      enabled
        ? (this._activeLayouts || [])
          .filter((layout) => !this._isCandidateLayout(layout))
          .map((layout) => layout.location_entity_id)
        : [],
    )
    this._updatePreviewDom()
  },

  _toggleSelection(locationId, selected) {
    const layout = (this._activeLayouts || []).find((item) => item.location_entity_id === locationId)
    if (this._isCandidateLayout(layout)) return
    const next = new Set(this._selectedLocationIds || [])
    if (selected) next.add(locationId)
    else next.delete(locationId)
    this._selectedLocationIds = next
    this._updatePreviewDom()
  },

  _pushHistory() {
    this._layoutHistory.push(this._activeLayouts.map((layout) => ({ ...layout })))
    if (this._layoutHistory.length > 50) this._layoutHistory.shift()
    this._layoutRedo = []
  },

  _resizeLocation(locationId, direction) {
    this._pushHistory()
    this._activeLayouts = applyLayoutResize(
      this._activeLayouts,
      locationId,
      direction,
    )
    this._updatePreviewDom()
  },

  _moveLocation(locationId, dq, dr) {
    const grid = this._preview?.map || {}
    const maxQ = Math.max(0, Number(grid.grid_width || 40) - 1)
    const maxR = Math.max(0, Number(grid.grid_height || 30) - 1)
    this._pushHistory()
    this._activeLayouts = this._activeLayouts.map((layout) => {
      if (layout.location_entity_id !== locationId) return layout
      return {
        ...layout,
        center_hex_q: Math.max(0, Math.min(maxQ, Number(layout.center_hex_q) + dq)),
        center_hex_r: Math.max(0, Math.min(maxR, Number(layout.center_hex_r) + dr)),
        layout_source: "user_drag",
      }
    })
    this._updatePreviewDom()
  },

  _toggleLock(locationId) {
    this._pushHistory()
    this._activeLayouts = this._activeLayouts.map((layout) => {
      if (layout.location_entity_id !== locationId) return layout
      return { ...layout, locked: !layout.locked, layout_source: "user_lock" }
    })
    this._updatePreviewDom()
  },

  _undoLayout() {
    const previous = this._layoutHistory.pop()
    if (!previous) return
    this._layoutRedo.push(this._activeLayouts.map((layout) => ({ ...layout })))
    this._activeLayouts = previous
    this._updatePreviewDom()
  },

  _redoLayout() {
    const next = this._layoutRedo.pop()
    if (!next) return
    this._layoutHistory.push(this._activeLayouts.map((layout) => ({ ...layout })))
    this._activeLayouts = next
    this._updatePreviewDom()
  },

  _drawCanvas() {
    const canvas = document.getElementById("map-quick-canvas")
    if (!canvas) return
    let ctx = null
    try {
      ctx = canvas.getContext("2d")
    } catch {
      return
    }
    if (!ctx) return
    const ratio = window.devicePixelRatio || 1
    const width = Math.max(320, canvas.clientWidth || 920)
    const height = Math.max(240, canvas.clientHeight || 420)
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio)
      canvas.height = Math.round(height * ratio)
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = "#111827"
    ctx.fillRect(0, 0, width, height)
    ctx.strokeStyle = "rgba(148,163,184,.18)"
    ctx.lineWidth = 1
    const gridWidth = Math.max(1, Number(this._preview?.map?.grid_width || this._gridWidth))
    const gridHeight = Math.max(1, Number(this._preview?.map?.grid_height || this._gridHeight))
    const qStep = Math.max(1, Math.ceil(gridWidth / 24))
    const rStep = Math.max(1, Math.ceil(gridHeight / 16))
    for (let q = 0; q < gridWidth; q += qStep) {
      const point = this._layoutCanvasPoint(canvas, q, 0)
      ctx.beginPath()
      ctx.moveTo(point.x, 18)
      ctx.lineTo(point.x, height - 18)
      ctx.stroke()
    }
    for (let r = 0; r < gridHeight; r += rStep) {
      const point = this._layoutCanvasPoint(canvas, 0, r)
      ctx.beginPath()
      ctx.moveTo(24, point.y)
      ctx.lineTo(width - 24, point.y)
      ctx.stroke()
    }
    for (const layout of this._activeLayouts || []) {
      const point = this._layoutCanvasPoint(
        canvas,
        layout.center_hex_q,
        layout.center_hex_r,
      )
      const candidate = this._isCandidateLayout(layout)
      const selected = this._selectedLocationIds.has(layout.location_entity_id)
      ctx.beginPath()
      ctx.arc(point.x, point.y, candidate ? 11 : 14, 0, Math.PI * 2)
      ctx.fillStyle = candidate ? "#64748b" : selected ? "#38bdf8" : "#334155"
      ctx.fill()
      ctx.strokeStyle = layout.locked ? "#f59e0b" : candidate ? "#94a3b8" : "#e2e8f0"
      ctx.lineWidth = layout.locked ? 3 : 1.5
      ctx.stroke()
      ctx.font = "12px sans-serif"
      ctx.textAlign = "center"
      ctx.fillStyle = "#f8fafc"
      ctx.fillText(this._locationName(layout.location_entity_id), point.x, point.y - 20)
    }
  },

  _layoutCanvasPoint(canvas, q, r) {
    const width = Math.max(320, canvas.clientWidth || 920)
    const height = Math.max(240, canvas.clientHeight || 420)
    const gridWidth = Math.max(1, Number(this._preview?.map?.grid_width || this._gridWidth))
    const gridHeight = Math.max(1, Number(this._preview?.map?.grid_height || this._gridHeight))
    return {
      x: 24 + (Number(q) / Math.max(1, gridWidth - 1)) * (width - 48),
      y: 24 + (Number(r) / Math.max(1, gridHeight - 1)) * (height - 48),
    }
  },

  _canvasEventToHex(canvas, event) {
    const rect = canvas.getBoundingClientRect()
    const width = Math.max(320, rect.width || canvas.clientWidth || 920)
    const height = Math.max(240, rect.height || canvas.clientHeight || 420)
    const gridWidth = Math.max(1, Number(this._preview?.map?.grid_width || this._gridWidth))
    const gridHeight = Math.max(1, Number(this._preview?.map?.grid_height || this._gridHeight))
    const x = Math.max(24, Math.min(width - 24, event.clientX - rect.left))
    const y = Math.max(24, Math.min(height - 24, event.clientY - rect.top))
    return [
      Math.round(((x - 24) / Math.max(1, width - 48)) * (gridWidth - 1)),
      Math.round(((y - 24) / Math.max(1, height - 48)) * (gridHeight - 1)),
    ]
  },

  _bindCanvasEvents() {
    const canvas = document.getElementById("map-quick-canvas")
    if (!canvas) return
    canvas.onpointerdown = (event) => {
      const rect = canvas.getBoundingClientRect()
      const hit = (this._activeLayouts || []).find((layout) => {
        if (layout.locked || this._isCandidateLayout(layout)) return false
        if (!this._selectedLocationIds.has(layout.location_entity_id)) return false
        const point = this._layoutCanvasPoint(canvas, layout.center_hex_q, layout.center_hex_r)
        return Math.hypot(event.clientX - rect.left - point.x, event.clientY - rect.top - point.y) <= 24
      })
      if (!hit) return
      this._pushHistory()
      this._dragLocationId = hit.location_entity_id
      canvas.setPointerCapture?.(event.pointerId)
      event.preventDefault()
    }
    canvas.onpointermove = (event) => {
      if (!this._dragLocationId) return
      const [q, r] = this._canvasEventToHex(canvas, event)
      this._activeLayouts = this._activeLayouts.map((layout) => (
        layout.location_entity_id === this._dragLocationId
          ? { ...layout, center_hex_q: q, center_hex_r: r, layout_source: "user_drag" }
          : layout
      ))
      this._drawCanvas()
    }
    const finish = (event) => {
      if (!this._dragLocationId) return
      canvas.releasePointerCapture?.(event.pointerId)
      this._dragLocationId = null
      this._updatePreviewDom()
    }
    canvas.onpointerup = finish
    canvas.onpointercancel = finish
  },

  async _confirm() {
    const selectedLayouts = this._selectedLayouts()
    if (!selectedLayouts.length) {
      toast("请至少选择一个地点", "warning")
      this._syncCreateButton()
      return false
    }
    if (
      this._replaceMapId
      && typeof window.confirm === "function"
      && !window.confirm("将替换该地图的地点布局与快速创建事实；底图、覆盖层、标记和领地会保留。继续吗？")
    ) {
      return false
    }
    try {
      const nameInput = document.getElementById("map-quick-name")
      const created = await api.world.confirmQuickCreateMap({
        ...this._previewPayload(),
        name: nameInput?.value?.trim() || this._preview?.map?.name || undefined,
        layouts: selectedLayouts,
      }, state.currentProjectId)
      toast("地图已快速创建", "success")
      await this._onCreated?.(created.map)
      return created
    } catch (err) {
      toast(`快速创建地图失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  _locationName(locationId) {
    const all = [
      ...(this._context?.locations || []),
      ...(this._context?.candidate_locations || []),
    ]
    return all.find((location) => location.id === locationId)?.name || "未命名地点"
  },
}

export default mapQuickCreateView
