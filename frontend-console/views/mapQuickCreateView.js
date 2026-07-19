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
  _selectionOverrides: new Map(),
  _selectionTarget: null,
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
  _mapName: "",
  _mapNameTouched: false,
  _scopeFilter: "all",
  _parentFilter: "all",
  _detailFilter: "all",
  _filterQuery: "",
  _dragLocationId: null,
  _onCreated: null,
  _projectId: null,
  _openGeneration: 0,

  async open({ onCreated = null, projectId = null } = {}) {
    const frozenProjectId = projectId || state.currentProjectId
    if (!frozenProjectId || state.currentProjectId !== frozenProjectId) return false
    this._openGeneration += 1
    const generation = this._openGeneration
    this._projectId = frozenProjectId
    this._onCreated = onCreated
    this._includeCandidates = false
    this._activeLayouts = []
    this._layoutHistory = []
    this._layoutRedo = []
    this._selectedLocationIds = new Set()
    this._previousLayoutIds = new Set()
    this._selectionOverrides = new Map()
    this._selectionTarget = null
    this._target = "world"
    this._parentEntityId = null
    this._parentMapId = null
    this._replaceMapId = null
    this._extraLocationIds = new Set()
    this._mapType = "world"
    this._gridWidth = 40
    this._gridHeight = 30
    this._baseTemplate = "blank"
    this._mapName = ""
    this._mapNameTouched = false
    this._scopeFilter = "all"
    this._parentFilter = "all"
    this._detailFilter = "all"
    this._filterQuery = ""
    await this._loadContext()
    if (!this._isCurrentOpen(generation, frozenProjectId)) return false
    await this._loadPreview()
    if (!this._isCurrentOpen(generation, frozenProjectId)) return false
    this._showModal()
    return true
  },

  _isCurrentOpen(generation = this._openGeneration, projectId = this._projectId) {
    return Boolean(
      projectId
      && generation === this._openGeneration
      && this._projectId === projectId
      && state.currentProjectId === projectId
    )
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
    this._captureMapName()
    return {
      context: this._context,
      preview: this._preview,
      activeLayouts: this._activeLayouts.map((layout) => ({ ...layout })),
      layoutHistory: this._layoutHistory.map((entry) => entry.map((layout) => ({ ...layout }))),
      layoutRedo: this._layoutRedo.map((entry) => entry.map((layout) => ({ ...layout }))),
      selectedLocationIds: new Set(this._selectedLocationIds),
      previousLayoutIds: new Set(this._previousLayoutIds),
      selectionOverrides: new Map(this._selectionOverrides),
      selectionTarget: this._selectionTarget,
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
      mapName: this._mapName,
      mapNameTouched: this._mapNameTouched,
      scopeFilter: this._scopeFilter,
      parentFilter: this._parentFilter,
      detailFilter: this._detailFilter,
      filterQuery: this._filterQuery,
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
    this._selectionOverrides = snapshot.selectionOverrides || new Map()
    this._selectionTarget = snapshot.selectionTarget ?? null
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
    this._mapName = snapshot.mapName
    this._mapNameTouched = snapshot.mapNameTouched
    this._scopeFilter = snapshot.scopeFilter || "all"
    this._parentFilter = snapshot.parentFilter || "all"
    this._detailFilter = snapshot.detailFilter || "all"
    this._filterQuery = snapshot.filterQuery || ""
  },

  async _loadContext() {
    const projectId = this._projectId || state.currentProjectId
    const generation = this._openGeneration
    if (!this._isCurrentOpen(generation, projectId)) {
      throw new Error("当前项目已切换")
    }
    const context = await api.world.getMapQuickCreateContext(
      projectId,
      this._includeCandidates,
    )
    if (!this._isCurrentOpen(generation, projectId)) {
      throw new Error("当前项目已切换")
    }
    this._context = context
  },

  async _loadPreview() {
    const projectId = this._projectId || state.currentProjectId
    const generation = this._openGeneration
    if (!this._isCurrentOpen(generation, projectId)) {
      throw new Error("当前项目已切换")
    }
    const preview = await api.world.previewQuickCreateMap(
      this._previewPayload(),
      projectId,
    )
    if (!this._isCurrentOpen(generation, projectId)) {
      throw new Error("当前项目已切换")
    }
    this._preview = preview
    if (!this._mapNameTouched) {
      this._mapName = this._preview?.map?.name || ""
    }
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
      `<option value="${esc(location.id)}">${esc(location.name)} · ${esc(location.map_scope?.label || "尺度待判断")}</option>`
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
          <div class="form-group"><label>地图名称</label><input class="form-input" id="map-quick-name" value="${esc(this._mapName || preview.map?.name || "")}" ${this._replaceMapId ? "disabled" : ""}/></div>
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
    const targetChanged = this._selectionTarget !== this._target
    const selected = new Set()
    for (const id of nextIds) {
      const layout = (layouts || []).find((item) => item.location_entity_id === id)
      if (this._isCandidateLayout(layout)) continue
      if (this._selectionOverrides.has(id)) {
        if (this._selectionOverrides.get(id)) selected.add(id)
        continue
      }
      if (targetChanged || !this._previousLayoutIds.has(id)) {
        if (this._isRecommendedForTarget(id)) selected.add(id)
        continue
      }
      if (this._selectedLocationIds.has(id)) selected.add(id)
    }
    this._selectedLocationIds = selected
    this._previousLayoutIds = nextIds
    this._selectionTarget = this._target
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

  _locationRecord(locationId) {
    return [
      ...(this._context?.locations || []),
      ...(this._context?.candidate_locations || []),
    ].find((location) => location.id === locationId) || null
  },

  _locationScope(locationId) {
    return this._locationRecord(locationId)?.map_scope || {
      key: "unknown",
      label: "尺度待判断",
      recommended_targets: ["world", "detail", "drilldown"],
    }
  },

  _isRecommendedForTarget(locationId) {
    const targets = this._locationScope(locationId).recommended_targets || []
    return targets.includes(this._target)
  },

  _visibleLayouts() {
    const query = String(this._filterQuery || "").trim().toLocaleLowerCase()
    return (this._activeLayouts || []).filter((layout) => {
      const location = this._locationRecord(layout.location_entity_id) || {}
      const scope = this._locationScope(layout.location_entity_id)
      if (query && !String(location.name || "").toLocaleLowerCase().includes(query)) {
        return false
      }
      if (this._scopeFilter !== "all" && scope.key !== this._scopeFilter) return false
      const parents = location.parent_locations || []
      if (this._parentFilter === "root" && parents.length) return false
      if (
        !["all", "root"].includes(this._parentFilter)
        && !parents.some((parent) => parent.id === this._parentFilter)
      ) return false
      if (this._detailFilter === "with" && !location.has_detail_map) return false
      if (this._detailFilter === "without" && location.has_detail_map) return false
      return true
    })
  },

  _splitRecommendations() {
    if (this._target !== "world") return []
    return (this._activeLayouts || [])
      .filter((layout) => !this._isCandidateLayout(layout))
      .map((layout) => this._locationRecord(layout.location_entity_id))
      .filter((location) => (
        location
        && !this._isRecommendedForTarget(location.id)
        && !location.has_detail_map
      ))
  },

  _renderRows() {
    const layouts = this._visibleLayouts()
    const selectedIds = this._selectedLocationIds || new Set()
    return layouts.map((layout) => {
      const id = layout.location_entity_id
      const candidate = this._isCandidateLayout(layout)
      const location = this._locationRecord(id) || {}
      const scope = this._locationScope(id)
      const parentLabel = (location.parent_locations || []).map((parent) => parent.name).join("、") || "未设父地点"
      const selected = !candidate && selectedIds.has(id)
      const disabled = selected && !layout.locked ? "" : "disabled"
      const lockDisabled = selected ? "" : "disabled"
      return `
      <tr class="${selected ? "" : "map-quick-row-unselected"} ${candidate ? "is-candidate" : ""}">
        <td>
          <input type="checkbox" data-action="map-quick-select" data-id="${esc(id)}" ${selected ? "checked" : ""} ${candidate ? "disabled" : ""}/>
        </td>
        <td>${esc(this._locationName(layout.location_entity_id))}</td>
        <td><span class="map-quick-scope-badge" data-scope="${esc(scope.key)}">${esc(scope.label)}</span><small>${esc(parentLabel)}${location.has_detail_map ? " · 已有详图" : ""}</small></td>
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
    const visibleLayouts = this._visibleLayouts().filter((layout) => !this._isCandidateLayout(layout))
    const total = placeableLayouts.length
    const selectedCount = this._selectedCount()
    const visibleSelectedCount = visibleLayouts.filter(
      (layout) => this._selectedLocationIds.has(layout.location_entity_id),
    ).length
    const allSelected = visibleLayouts.length > 0 && visibleSelectedCount === visibleLayouts.length
    const scopeOptions = [
      ["all", "全部尺度"],
      ["world", "世界级"],
      ["region", "区域级"],
      ["settlement", "城市/聚落"],
      ["site", "地点/建筑"],
      ["interior", "室内/地下"],
      ["nonphysical", "非物理空间"],
      ["unknown", "尺度待判断"],
    ]
    const parentOptions = new Map()
    for (const location of this._context?.locations || []) {
      for (const parent of location.parent_locations || []) parentOptions.set(parent.id, parent.name)
    }
    const splitRecommendations = this._splitRecommendations()
    const splitNames = splitRecommendations.slice(0, 5).map((location) => location.name).join("、")
    return `
      ${warnings}
      ${splitRecommendations.length ? `<div class="alert alert-info">世界图已默认取消选择 ${splitRecommendations.length} 个建筑或室内地点。建议拆分详图：${esc(splitNames)}${splitRecommendations.length > 5 ? ` 等 ${splitRecommendations.length} 个地点` : ""}。</div>` : ""}
      <div class="view-header map-toolbar">
        <div class="view-header__title">快速放置</div>
        <div class="view-header__actions">
          <button class="btn btn-sm" id="map-quick-undo" ${this._layoutHistory.length ? "" : "disabled"}>撤销</button>
          <button class="btn btn-sm" id="map-quick-redo" ${this._layoutRedo.length ? "" : "disabled"}>重做</button>
          <span class="view-header__count">已选 ${selectedCount} / 共 ${total}${visibleLayouts.length !== total ? ` · 当前筛选 ${visibleLayouts.length}` : ""}</span>
        </div>
      </div>
      <div class="map-quick-filters">
        <input class="form-input" id="map-quick-filter-query" type="search" value="${esc(this._filterQuery)}" placeholder="搜索地点名称" />
        <select class="form-select" id="map-quick-filter-scope">${scopeOptions.map(([value, label]) => `<option value="${value}" ${this._scopeFilter === value ? "selected" : ""}>${label}</option>`).join("")}</select>
        <select class="form-select" id="map-quick-filter-parent"><option value="all">全部父地点</option><option value="root" ${this._parentFilter === "root" ? "selected" : ""}>未设父地点</option>${[...parentOptions.entries()].sort((a, b) => a[1].localeCompare(b[1], "zh-CN")).map(([id, name]) => `<option value="${esc(id)}" ${this._parentFilter === id ? "selected" : ""}>${esc(name)}</option>`).join("")}</select>
        <select class="form-select" id="map-quick-filter-detail"><option value="all">全部详图状态</option><option value="with" ${this._detailFilter === "with" ? "selected" : ""}>已有详图</option><option value="without" ${this._detailFilter === "without" ? "selected" : ""}>尚无详图</option></select>
      </div>
      <div class="map-quick-canvas-wrap"><canvas id="map-quick-canvas" class="map-quick-canvas" width="920" height="420" aria-label="地点布局画布"></canvas><p class="map-quick-meta">拖动已采用地点调整中心格；待处理地点仅供预览。</p></div>
      <table class="data-table">
        <thead><tr>
          <th><input type="checkbox" id="map-quick-select-all" ${allSelected ? "checked" : ""} ${visibleLayouts.length ? "" : "disabled"} /></th>
          <th>地点</th><th>尺度与父地点</th><th>位置</th><th>半径</th><th>状态</th><th>调整</th>
        </tr></thead>
        <tbody>${rows || `<tr><td colspan="7">当前筛选下暂无可放置地点</td></tr>`}</tbody>
      </table>
    `
  },

  _bindModalEvents() {
    const mapName = document.getElementById("map-quick-name")
    if (mapName) {
      mapName.oninput = () => {
        this._mapName = mapName.value
        this._mapNameTouched = true
      }
    }
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
    const filterQuery = document.getElementById("map-quick-filter-query")
    if (filterQuery) filterQuery.onchange = () => {
      this._filterQuery = filterQuery.value
      this._updatePreviewDom()
    }
    const scopeFilter = document.getElementById("map-quick-filter-scope")
    if (scopeFilter) scopeFilter.onchange = () => {
      this._scopeFilter = scopeFilter.value
      this._updatePreviewDom()
    }
    const parentFilter = document.getElementById("map-quick-filter-parent")
    if (parentFilter) parentFilter.onchange = () => {
      this._parentFilter = parentFilter.value
      this._updatePreviewDom()
    }
    const detailFilter = document.getElementById("map-quick-filter-detail")
    if (detailFilter) detailFilter.onchange = () => {
      this._detailFilter = detailFilter.value
      this._updatePreviewDom()
    }
    const selectAll = document.getElementById("map-quick-select-all")
    if (selectAll) {
      const visible = this._visibleLayouts().filter((layout) => !this._isCandidateLayout(layout))
      const selectedCount = visible.filter(
        (layout) => this._selectedLocationIds.has(layout.location_entity_id),
      ).length
      selectAll.indeterminate = selectedCount > 0 && selectedCount < visible.length
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

  _captureMapName() {
    const input = document.getElementById("map-quick-name")
    if (!input || input.value === this._mapName) return
    this._mapName = input.value
    this._mapNameTouched = true
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
    const next = new Set(this._selectedLocationIds || [])
    for (const layout of this._visibleLayouts()) {
      if (this._isCandidateLayout(layout)) continue
      this._selectionOverrides.set(layout.location_entity_id, Boolean(enabled))
      if (enabled) next.add(layout.location_entity_id)
      else next.delete(layout.location_entity_id)
    }
    this._selectedLocationIds = next
    this._updatePreviewDom()
  },

  _toggleSelection(locationId, selected) {
    const layout = (this._activeLayouts || []).find((item) => item.location_entity_id === locationId)
    if (this._isCandidateLayout(layout)) return
    const next = new Set(this._selectedLocationIds || [])
    this._selectionOverrides.set(locationId, Boolean(selected))
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
    for (const layout of this._visibleLayouts()) {
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
      const hit = this._visibleLayouts().find((layout) => {
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
    const projectId = this._projectId || state.currentProjectId
    const generation = this._openGeneration
    if (!this._isCurrentOpen(generation, projectId)) {
      toast("当前项目已切换，请返回原项目重新打开快速创建", "warning")
      return false
    }
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
        name: nameInput?.value?.trim() || this._mapName?.trim() || this._preview?.map?.name || undefined,
        layouts: selectedLayouts,
      }, projectId)
      if (!this._isCurrentOpen(generation, projectId)) {
        toast("地图已在原项目创建，当前项目已切换", "warning")
        return false
      }
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
