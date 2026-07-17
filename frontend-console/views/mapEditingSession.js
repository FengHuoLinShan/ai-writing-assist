/**
 * 地图视觉编辑会话。
 *
 * 后端仍拥有地图资产与 editor_revision；本模块只拥有浏览器内的草稿、
 * 分层 Undo/Redo、一次 apply 的冻结范围，以及成功/冲突后的会话状态转换。
 * Canvas/Leaflet 渲染和后端命令内容仍由 mapView 负责。
 */

export const DEFAULT_MAP_EDITOR_LIMITS = Object.freeze({
  commandCount: 200,
  terrainTiles: 10000,
  locationItems: 2000,
  locationBindingHexes: 5000,
  terrainRegions: 200,
  terrainPatches: 20000,
  territoryHexes: 5000,
  layerNodes: 500,
  pathNodes: 500,
  pathBatchNodes: 2000,
})

function clone(value) {
  if (value == null) return value
  return JSON.parse(JSON.stringify(value))
}

function emptyTerritoryDraft() {
  return { add: {}, remove: {} }
}

export class MapEditingSession {
  constructor(state, { limits = DEFAULT_MAP_EDITOR_LIMITS } = {}) {
    this.state = state
    this.limits = { ...DEFAULT_MAP_EDITOR_LIMITS, ...limits }
    this.mapId = null
    this.baselineRevision = 0
    this._attemptSequence = 0
    this._activeAttemptId = null
  }

  syncBaseline(mapId, revision) {
    this.mapId = mapId || null
    this.baselineRevision = Number(revision || 0)
  }

  resetBaseline() {
    this.mapId = null
    this.baselineRevision = 0
    this._activeAttemptId = null
  }

  isApplying() {
    return this._activeAttemptId !== null
  }

  hasDraftChanges() {
    const state = this.state
    return Boolean(
      Object.keys(state.pendingTerrainChanges || {}).length
      || Object.keys(state.pendingBindings || {}).length
      || Object.keys(state.pendingLocationLayouts || {}).length
      || state.pendingTerrainOverlay
      || (state.pendingTerrainLayerDeletes || []).length
      || Object.keys(state.pendingMarkerChanges || {}).length
      || state.pendingLayerTree
      || Object.keys(state.pendingPathChanges || {}).length
      || Object.keys(state.pendingPathLayerChanges || {}).length
      || Object.keys(state.pendingTerritoryChanges?.add || {}).length
      || Object.keys(state.pendingTerritoryChanges?.remove || {}).length,
    )
  }

  draftChangeCount(layer = this.state.editorLayer) {
    const state = this.state
    const counts = {
      location: Object.keys(state.pendingBindings || {}).length
        + Object.keys(state.pendingLocationLayouts || {}).length,
      baseTerrain: Object.keys(state.pendingTerrainChanges || {}).length,
      terrainOverlay: (state.pendingTerrainLayerDeletes || []).length
        + (state.pendingTerrainOverlay
          ? (state.pendingTerrainOverlay.patches || []).length
            + (state.pendingTerrainOverlay.regions || []).length
            + Number(Boolean(state.pendingTerrainOverlay.layerCreate))
            + Number(Boolean(state.pendingTerrainOverlay.layerUpdate))
          : 0),
      marker: Object.keys(state.pendingMarkerChanges || {}).length,
      layerTree: Number(Boolean(state.pendingLayerTree)),
      path: Object.keys(state.pendingPathChanges || {}).length
        + Object.keys(state.pendingPathLayerChanges || {}).length,
      territory: Object.keys(state.pendingTerritoryChanges?.add || {}).length
        + Object.keys(state.pendingTerritoryChanges?.remove || {}).length,
    }
    if (Object.prototype.hasOwnProperty.call(counts, layer)) return counts[layer]
    return Object.values(counts).reduce((sum, count) => sum + count, 0)
  }

  recordCommand(layer, command) {
    const key = layer || this.state.editorLayer || "none"
    if (!this.state.editorHistory[key]) this.state.editorHistory[key] = []
    this.state.editorHistory[key].push(clone(command))
    if (this.state.editorHistory[key].length > 50) {
      this.state.editorHistory[key].shift()
    }
    this.state.editorRedo[key] = []
  }

  undo(layer = this.state.editorLayer) {
    const history = this.state.editorHistory[layer] || []
    const command = history.pop() || null
    if (command) {
      if (!this.state.editorRedo[layer]) this.state.editorRedo[layer] = []
      this.state.editorRedo[layer].push(command)
    }
    return command
  }

  redo(layer = this.state.editorLayer) {
    const redo = this.state.editorRedo[layer] || []
    const command = redo.pop() || null
    if (command) {
      if (!this.state.editorHistory[layer]) this.state.editorHistory[layer] = []
      this.state.editorHistory[layer].push(command)
    }
    return command
  }

  snapshotActiveDraft(layer = this.state.editorLayer) {
    const state = this.state
    if (layer === "terrainOverlay") return clone(state.pendingTerrainOverlay)
    if (layer === "location") {
      return clone({
        layouts: state.pendingLocationLayouts || {},
        bindings: state.pendingBindings || {},
      })
    }
    if (layer === "baseTerrain") return clone(state.pendingTerrainChanges || {})
    if (layer === "territory") {
      return clone(state.pendingTerritoryChanges || emptyTerritoryDraft())
    }
    if (layer === "path") {
      return clone({
        paths: state.pendingPathChanges || {},
        layers: state.pendingPathLayerChanges || {},
        selectedPathLayerId: state.selectedPathLayerId,
        selectedPathId: state.selectedPathId,
      })
    }
    return null
  }

  restoreActiveDraft(snapshot, layer = this.state.editorLayer) {
    const state = this.state
    const value = clone(snapshot)
    if (layer === "terrainOverlay") {
      state.pendingTerrainOverlay = value
    } else if (layer === "location") {
      state.pendingLocationLayouts = value?.layouts || {}
      state.pendingBindings = value?.bindings || {}
    } else if (layer === "baseTerrain") {
      state.pendingTerrainChanges = value || {}
    } else if (layer === "territory") {
      state.pendingTerritoryChanges = value || emptyTerritoryDraft()
    } else if (layer === "path") {
      state.pendingPathChanges = value?.paths || {}
      state.pendingPathLayerChanges = value?.layers || {}
      state.selectedPathLayerId = value?.selectedPathLayerId || null
      state.selectedPathId = value?.selectedPathId || null
    }
    return {
      layer,
      terrainPendingCount: Object.keys(state.pendingTerrainChanges || {}).length,
      bindingPendingCount: Object.keys(state.pendingBindings || {}).length,
    }
  }

  snapshotForReload() {
    const state = this.state
    return clone({
      mode: state.mode,
      activeTool: state.activeTool,
      editorLayer: state.editorLayer,
      selectedTerrain: state.selectedTerrain,
      selectedLocationEntityId: state.selectedLocationEntityId,
      bindCenterMode: state.bindCenterMode,
      selectedMarkerType: state.selectedMarkerType,
      selectedMarkerEntityId: state.selectedMarkerEntityId,
      selectedMarkerLabel: state.selectedMarkerLabel,
      selectedFactionId: state.selectedFactionId,
      pendingTerrainChanges: state.pendingTerrainChanges,
      pendingBindings: state.pendingBindings,
      pendingLocationLayouts: state.pendingLocationLayouts,
      pendingTerrainOverlay: state.pendingTerrainOverlay,
      pendingTerrainLayerDeletes: state.pendingTerrainLayerDeletes,
      pendingMarkerChanges: state.pendingMarkerChanges,
      pendingLayerTree: state.pendingLayerTree,
      layerTreeBaselineStale: state.layerTreeBaselineStale,
      pendingPathChanges: state.pendingPathChanges,
      pendingPathLayerChanges: state.pendingPathLayerChanges,
      selectedPathLayerId: state.selectedPathLayerId,
      selectedPathId: state.selectedPathId,
      selectedPathNodeIndex: state.selectedPathNodeIndex,
      selectedPathType: state.selectedPathType,
      pathTool: state.pathTool,
      selectedTerrainLayerId: state.selectedTerrainLayerId,
      selectedTerrainAssetKey: state.selectedTerrainAssetKey,
      selectedTerrainPreset: state.selectedTerrainPreset,
      overlayBrushSize: state.overlayBrushSize,
      overlayTool: state.overlayTool,
      territoryEraseMode: state.territoryEraseMode,
      pendingTerritoryChanges: state.pendingTerritoryChanges,
      editorHistory: state.editorHistory,
      editorRedo: state.editorRedo,
    })
  }

  restoreAfterReload(snapshot, { preserveMarkers = true } = {}) {
    if (!snapshot) return
    const state = this.state
    const restored = clone(snapshot)
    for (const [key, value] of Object.entries(restored)) {
      if (key === "pendingMarkerChanges" && !preserveMarkers) continue
      state[key] = value
    }
    if (!preserveMarkers) state.pendingMarkerChanges = {}
  }

  discardDrafts() {
    const state = this.state
    state.pendingTerrainChanges = {}
    state.pendingBindings = {}
    state.pendingLocationLayouts = {}
    state.pendingTerrainOverlay = null
    state.pendingTerrainLayerDeletes = []
    state.pendingMarkerChanges = {}
    state.pendingLayerTree = null
    state.layerTreeBaselineStale = false
    state.pendingTerritoryChanges = emptyTerritoryDraft()
    state.pendingPathChanges = {}
    state.pendingPathLayerChanges = {}
    state.editorHistory = {}
    state.editorRedo = {}
  }

  validateCommands(commands) {
    const limits = this.limits
    if (commands.length > limits.commandCount) {
      return `单次最多应用 ${limits.commandCount} 个编辑命令，请减少本次变更`
    }
    let changedPathNodes = 0
    for (const command of commands) {
      if (command.type === "base_terrain_replace" && command.changes.length > limits.terrainTiles) {
        return `单次最多应用 ${limits.terrainTiles} 个地形变更，请撤销部分变更后分批保存`
      }
      if (command.type === "location_layout_replace" && command.layouts.length > limits.locationItems) {
        return `单次最多应用 ${limits.locationItems} 个地点布局，请减少本次变更`
      }
      if (command.type === "location_binding_replace") {
        if (command.items.length > limits.locationItems) {
          return `单次最多应用 ${limits.locationItems} 个地点绑定组，请减少本次变更`
        }
        if (command.items.some((item) => item.hexes.length > limits.locationBindingHexes)) {
          return `单个地点单次最多绑定 ${limits.locationBindingHexes} 个地图格，请减少选中范围`
        }
      }
      if (command.type === "terrain_patch_replace") {
        if (command.data.regions.length > limits.terrainRegions) {
          return `单个覆盖图层最多包含 ${limits.terrainRegions} 个区域，请减少本次变更`
        }
        if (command.data.patches.length > limits.terrainPatches) {
          return `单个覆盖图层最多包含 ${limits.terrainPatches} 个覆盖格，请减少本次变更`
        }
      }
      if (command.type === "territory_replace" && command.hexes.length > limits.territoryHexes) {
        return `单个阵营单次最多应用 ${limits.territoryHexes} 个领地格，请减少选中范围`
      }
      if (["path_create", "path_update"].includes(command.type) && command.data.nodes) {
        changedPathNodes += command.data.nodes.length
        if (command.data.nodes.length > limits.pathNodes) {
          return `每条线路最多包含 ${limits.pathNodes} 个节点`
        }
      }
      if (command.type === "layer_tree_replace") {
        if (!command.nodes.length) return "图层树至少需要保留一个图层节点"
        if (command.nodes.length > limits.layerNodes) {
          return `图层树最多包含 ${limits.layerNodes} 个节点，请减少本次变更`
        }
      }
    }
    if (changedPathNodes > limits.pathBatchNodes) {
      return `单批最多变更 ${limits.pathBatchNodes} 个线路节点，请分批保存`
    }
    return null
  }

  beginApply(commands, { onlyLayer = false, onlyLayerTree = false } = {}) {
    if (this.isApplying()) {
      return {
        validationError: "地图编辑正在应用，请等待当前请求完成",
        attempt: null,
      }
    }
    const frozenCommands = clone(commands || [])
    const validationError = this.validateCommands(frozenCommands)
    if (validationError) return { validationError, attempt: null }
    const scope = Object.freeze({
      onlyLayer: Boolean(onlyLayer),
      onlyLayerTree: Boolean(onlyLayerTree),
      activeLayer: this.state.editorLayer,
    })
    const attempt = Object.freeze({
      id: ++this._attemptSequence,
      mapId: this.mapId,
      expectedRevision: this.baselineRevision,
      commands: frozenCommands,
      scope,
      submittedDrafts: this._snapshotApplyScope(scope),
    })
    this._activeAttemptId = attempt.id
    return { validationError: null, attempt }
  }

  requestFor(attempt) {
    return {
      expected_revision: attempt.expectedRevision,
      commands: attempt.commands,
    }
  }

  commitApply(attempt, result = {}) {
    if (!this._isCurrentAttempt(attempt)) return false
    this.baselineRevision = Number(
      result.editor_revision ?? this.baselineRevision,
    )
    this.reconcileClientIds(result.client_id_map || {})
    const transition = this.clearAppliedDrafts(
      attempt.scope,
      attempt.submittedDrafts,
    )
    this._activeAttemptId = null
    return { committed: true, ...transition }
  }

  markConflict(attempt, currentRevision) {
    if (!this._isCurrentAttempt(attempt)) return false
    this.baselineRevision = Number(currentRevision ?? this.baselineRevision)
    if (this.state.pendingLayerTree) this.state.layerTreeBaselineStale = true
    this._activeAttemptId = null
    return true
  }

  cancelApply(attempt) {
    if (this._isCurrentAttempt(attempt)) this._activeAttemptId = null
  }

  reconcileClientIds(clientIdMap = {}) {
    const state = this.state
    state.selectedTerrainLayerId = clientIdMap[state.selectedTerrainLayerId]
      || state.selectedTerrainLayerId
    state.selectedPathLayerId = clientIdMap[state.selectedPathLayerId]
      || state.selectedPathLayerId
    state.selectedPathId = clientIdMap[state.selectedPathId] || state.selectedPathId
  }

  clearAppliedDrafts(scope = {}, submittedDrafts = null) {
    const state = this.state
    const active = scope.activeLayer || state.editorLayer
    const onlyLayer = Boolean(scope.onlyLayer)
    const onlyLayerTree = Boolean(scope.onlyLayerTree)
    const included = (layer) => !onlyLayerTree && (!onlyLayer || active === layer)
    const clearedLayers = []
    const preservedLayers = []
    const clear = (layer) => {
      if (!included(layer)) return false
      const unchanged = !submittedDrafts
        || JSON.stringify(this._snapshotLayerDraft(layer))
          === JSON.stringify(submittedDrafts[layer])
      if (unchanged) clearedLayers.push(layer)
      else preservedLayers.push(layer)
      return unchanged
    }
    if (clear("baseTerrain")) state.pendingTerrainChanges = {}
    if (clear("location")) {
      state.pendingBindings = {}
      state.pendingLocationLayouts = {}
    }
    if (clear("terrainOverlay")) {
      state.pendingTerrainOverlay = null
      state.pendingTerrainLayerDeletes = []
    }
    if (clear("marker")) state.pendingMarkerChanges = {}
    if (clear("territory")) state.pendingTerritoryChanges = emptyTerritoryDraft()
    if (clear("path")) {
      state.pendingPathChanges = {}
      state.pendingPathLayerChanges = {}
    }
    const includesLayerTree = onlyLayerTree || !onlyLayer
    const clearLayerTree = includesLayerTree && (
      !submittedDrafts
      || JSON.stringify(this._snapshotLayerDraft("layerTree"))
        === JSON.stringify(submittedDrafts.layerTree)
    )
    if (includesLayerTree) {
      if (clearLayerTree) clearedLayers.push("layerTree")
      else preservedLayers.push("layerTree")
    }
    if (clearLayerTree) {
      state.pendingLayerTree = null
      state.layerTreeBaselineStale = false
    }
    for (const layer of clearedLayers) {
      delete state.editorHistory[layer]
      delete state.editorRedo[layer]
    }
    return { clearedLayers, preservedLayers }
  }

  _snapshotApplyScope(scope) {
    const snapshot = {}
    for (const layer of [
      "baseTerrain",
      "location",
      "terrainOverlay",
      "marker",
      "territory",
      "path",
    ]) {
      if (!scope.onlyLayerTree && (!scope.onlyLayer || scope.activeLayer === layer)) {
        snapshot[layer] = this._snapshotLayerDraft(layer)
      }
    }
    if (scope.onlyLayerTree || !scope.onlyLayer) {
      snapshot.layerTree = this._snapshotLayerDraft("layerTree")
    }
    return clone(snapshot)
  }

  _snapshotLayerDraft(layer) {
    const state = this.state
    if (layer === "baseTerrain") return clone(state.pendingTerrainChanges || {})
    if (layer === "location") {
      return clone({
        bindings: state.pendingBindings || {},
        layouts: state.pendingLocationLayouts || {},
      })
    }
    if (layer === "terrainOverlay") {
      return clone({
        overlay: state.pendingTerrainOverlay,
        deletes: state.pendingTerrainLayerDeletes || [],
      })
    }
    if (layer === "marker") return clone(state.pendingMarkerChanges || {})
    if (layer === "territory") {
      return clone(state.pendingTerritoryChanges || emptyTerritoryDraft())
    }
    if (layer === "path") {
      return clone({
        paths: state.pendingPathChanges || {},
        layers: state.pendingPathLayerChanges || {},
      })
    }
    if (layer === "layerTree") return clone(state.pendingLayerTree)
    return null
  }

  _isCurrentAttempt(attempt) {
    return Boolean(
      attempt
      && attempt.id === this._activeAttemptId
      && attempt.mapId === this.mapId,
    )
  }
}
