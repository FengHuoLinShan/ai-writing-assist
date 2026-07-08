/**
 * 地图快速创建 modal 控制器。
 */

import { applyLayoutResize } from "./mapGeoLayoutEngine.js"

const mapQuickCreateView = {
  _context: null,
  _preview: null,
  _activeLayouts: [],
  _layoutHistory: [],
  _selectedLocationIds: new Set(),
  _previousLayoutIds: new Set(),
  _includeCandidates: false,
  _target: "world",
  _onCreated: null,

  async open({ onCreated = null } = {}) {
    this._onCreated = onCreated
    this._includeCandidates = false
    this._activeLayouts = []
    this._layoutHistory = []
    this._selectedLocationIds = new Set()
    this._previousLayoutIds = new Set()
    this._target = "world"
    await this._loadContext()
    await this._loadPreview()
    this._showModal()
  },

  async setIncludeCandidates(enabled) {
    this._includeCandidates = Boolean(enabled)
    await this._loadContext()
    await this._loadPreview()
    this._updatePreviewDom()
  },

  async setTarget(target) {
    this._target = target || "world"
    await this._loadPreview()
    this._updatePreviewDom()
  },

  async _loadContext() {
    this._context = await api.world.getMapQuickCreateContext(
      state.currentProjectId,
      this._includeCandidates,
    )
  },

  async _loadPreview() {
    this._preview = await api.world.previewQuickCreateMap({
      target: this._target,
      include_candidates: this._includeCandidates,
      include_markers: false,
    }, state.currentProjectId)
    this._activeLayouts = this._computePreviewLayouts()
    this._syncSelectionForLayouts(this._activeLayouts)
    this._layoutHistory = []
  },

  _showModal() {
    showModalHtml("快速创建地图", this._render(), [{
      text: "创建",
      class: "btn-primary",
      handler: async () => this._confirm(),
    }])
    this._bindModalEvents()
  },

  _render() {
    const preview = this._preview || { location_layouts: [], warnings: [], map: {} }
    return `
      <div class="map-quick-create">
        <div class="form-group">
          <label>创建目标</label>
          <select class="form-select" id="map-quick-target">
            <option value="world" ${this._target === "world" ? "selected" : ""}>世界地图</option>
            <option value="detail" ${this._target === "detail" ? "selected" : ""}>地点详图</option>
            <option value="drilldown" ${this._target === "drilldown" ? "selected" : ""}>下钻地图</option>
          </select>
        </div>
        <label class="map-layer-toggle">
          <input type="checkbox" id="map-quick-include-candidates" ${this._includeCandidates ? "checked" : ""} />
          包含待确认候选
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
      if (!this._previousLayoutIds.has(id)) selected.add(id)
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

  _renderRows() {
    const layouts = this._activeLayouts || []
    const selectedIds = this._selectedLocationIds || new Set()
    return layouts.map((layout) => {
      const id = layout.location_entity_id
      const selected = selectedIds.has(id)
      const disabled = selected ? "" : "disabled"
      return `
      <tr class="${selected ? "" : "map-quick-row-unselected"}">
        <td>
          <input type="checkbox" data-action="map-quick-select" data-id="${esc(id)}" ${selected ? "checked" : ""} />
        </td>
        <td>${esc(this._locationName(layout.location_entity_id))}</td>
        <td>${layout.center_hex_q}, ${layout.center_hex_r}</td>
        <td>
          <button class="btn btn-sm" data-action="map-quick-radius" data-id="${esc(id)}" data-direction="decrease" ${disabled}>-</button>
          ${layout.occupy_radius}
          <button class="btn btn-sm" data-action="map-quick-radius" data-id="${esc(id)}" data-direction="increase" ${disabled}>+</button>
        </td>
        <td>${selected ? (layout.locked ? "已锁定" : "可调整") : "未选择"}</td>
        <td>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="-1" data-dr="0" ${disabled}>←</button>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="1" data-dr="0" ${disabled}>→</button>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="0" data-dr="-1" ${disabled}>↑</button>
          <button class="btn btn-sm" data-action="map-quick-move" data-id="${esc(id)}" data-dq="0" data-dr="1" ${disabled}>↓</button>
          <button class="btn btn-sm" data-action="map-quick-lock" data-id="${esc(id)}" ${disabled}>${layout.locked ? "解锁" : "锁定"}</button>
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
    const total = (this._activeLayouts || []).length
    const selectedCount = this._selectedCount()
    const allSelected = total > 0 && selectedCount === total
    return `
      ${warnings}
      <div class="map-toolbar">
        <button class="btn btn-sm" id="map-quick-undo" ${this._layoutHistory.length ? "" : "disabled"}>撤销</button>
        <span class="map-quick-meta">已选 ${selectedCount} / 共 ${total}</span>
      </div>
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
    const selectAll = document.getElementById("map-quick-select-all")
    if (selectAll) {
      const total = (this._activeLayouts || []).length
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
    this._syncCreateButton()
  },

  _updatePreviewDom() {
    const container = document.getElementById("map-quick-preview")
    if (!container) return
    container.innerHTML = this._renderPreviewTable()
    this._bindModalEvents()
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
      enabled ? (this._activeLayouts || []).map((layout) => layout.location_entity_id) : [],
    )
    this._updatePreviewDom()
  },

  _toggleSelection(locationId, selected) {
    const next = new Set(this._selectedLocationIds || [])
    if (selected) next.add(locationId)
    else next.delete(locationId)
    this._selectedLocationIds = next
    this._updatePreviewDom()
  },

  _pushHistory() {
    this._layoutHistory.push(this._activeLayouts.map((layout) => ({ ...layout })))
    if (this._layoutHistory.length > 50) this._layoutHistory.shift()
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
    this._activeLayouts = previous
    this._updatePreviewDom()
  },

  async _confirm() {
    const selectedLayouts = this._selectedLayouts()
    if (!selectedLayouts.length) {
      toast("请至少选择一个地点", "warning")
      this._syncCreateButton()
      return null
    }
    const created = await api.world.confirmQuickCreateMap({
      target: this._target,
      include_candidates: this._includeCandidates,
      include_markers: false,
      layouts: selectedLayouts,
    }, state.currentProjectId)
    closeModal()
    toast("地图已快速创建", "success")
    await this._onCreated?.(created.map)
    return created
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
