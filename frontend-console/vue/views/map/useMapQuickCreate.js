import { reactive } from "vue"
import { applyLayoutResize } from "../../../views/mapGeoLayoutEngine.js"
import { getApi, getAppState, getConfirm, getToast } from "../../bridge/index.js"

const cloneLayouts = (items) => (items || []).map((item) => ({ ...item }))

export function useMapQuickCreate({ projectId, onCreated }) {
  const api = getApi()
  const toast = getToast()
  const confirm = getConfirm()
  const state = reactive({
    open: false, loading: false, saving: false, error: null,
    context: null, preview: null, activeLayouts: [], history: [], redo: [],
    selectedIds: new Set(), previousLayoutIds: new Set(), extraLocationIds: new Set(),
    includeCandidates: false, target: "world", parentEntityId: null, parentMapId: null,
    replaceMapId: null, mapType: "world", gridWidth: 40, gridHeight: 30,
    baseTemplate: "blank", mapName: "", mapNameTouched: false, generation: 0,
  })

  const owns = (token = state.generation) => state.open
    && token === state.generation
    && getAppState()?.currentProjectId === projectId

  function reset() {
    Object.assign(state, {
      loading: false, saving: false, error: null, context: null, preview: null,
      activeLayouts: [], history: [], redo: [], selectedIds: new Set(),
      previousLayoutIds: new Set(), extraLocationIds: new Set(), includeCandidates: false,
      target: "world", parentEntityId: null, parentMapId: null, replaceMapId: null,
      mapType: "world", gridWidth: 40, gridHeight: 30, baseTemplate: "blank",
      mapName: "", mapNameTouched: false,
    })
  }

  function close() { state.open = false; state.generation += 1 }

  function previewPayload() {
    return {
      target: state.target,
      parent_entity_id: state.parentEntityId,
      parent_map_id: state.parentMapId,
      replace_map_id: state.replaceMapId,
      map_type: state.replaceMapId ? undefined : state.mapType,
      grid_width: state.replaceMapId ? undefined : Number(state.gridWidth),
      grid_height: state.replaceMapId ? undefined : Number(state.gridHeight),
      base_template: state.baseTemplate,
      location_entity_ids: [...state.extraLocationIds],
      include_candidates: state.includeCandidates,
      include_markers: false,
    }
  }

  function isCandidate(layout) {
    const status = layout?.meta?.entity_status
    if (status && status !== "canonical") return true
    return (state.context?.candidate_locations || []).some((item) => item.id === layout?.location_entity_id)
  }

  function syncSelection(layouts) {
    const nextIds = new Set(layouts.map((item) => item.location_entity_id))
    const selected = new Set([...state.selectedIds].filter((id) => nextIds.has(id)))
    for (const layout of layouts) {
      const id = layout.location_entity_id
      if (!state.previousLayoutIds.has(id) && !isCandidate(layout)) selected.add(id)
    }
    state.selectedIds = selected
    state.previousLayoutIds = nextIds
  }

  async function loadContext(token = state.generation) {
    const context = await api.world.getMapQuickCreateContext(projectId, state.includeCandidates)
    if (!owns(token)) return false
    state.context = context
    return true
  }

  async function loadPreview(token = state.generation) {
    const preview = await api.world.previewQuickCreateMap(previewPayload(), projectId)
    if (!owns(token)) return false
    state.preview = preview
    if (!state.mapNameTouched) state.mapName = preview?.map?.name || ""
    state.gridWidth = Number(preview?.map?.grid_width || state.gridWidth)
    state.gridHeight = Number(preview?.map?.grid_height || state.gridHeight)
    state.mapType = preview?.map?.map_type || state.mapType
    const layouts = cloneLayouts(preview?.location_layouts)
    syncSelection(layouts)
    state.activeLayouts = layouts
    state.history = []
    state.redo = []
    return true
  }

  async function open() {
    reset()
    state.open = true
    state.loading = true
    const token = ++state.generation
    try {
      if (!(await loadContext(token))) return false
      if (!(await loadPreview(token))) return false
      return true
    } catch (error) {
      if (owns(token)) { state.error = error.message || "快速创建预览加载失败"; toast(`快速创建地图失败：${state.error}`, "error") }
      return false
    } finally {
      if (owns(token)) state.loading = false
    }
  }

  function snapshot() {
    return {
      context: state.context, preview: state.preview, activeLayouts: cloneLayouts(state.activeLayouts),
      history: state.history.map(cloneLayouts), redo: state.redo.map(cloneLayouts),
      selectedIds: new Set(state.selectedIds), previousLayoutIds: new Set(state.previousLayoutIds),
      extraLocationIds: new Set(state.extraLocationIds), includeCandidates: state.includeCandidates,
      target: state.target, parentEntityId: state.parentEntityId, parentMapId: state.parentMapId,
      replaceMapId: state.replaceMapId, mapType: state.mapType, gridWidth: state.gridWidth,
      gridHeight: state.gridHeight, baseTemplate: state.baseTemplate, mapName: state.mapName,
      mapNameTouched: state.mapNameTouched,
    }
  }

  function restore(value) { Object.assign(state, value) }

  async function reload(previous = snapshot(), { context = false } = {}) {
    state.loading = true
    const token = state.generation
    try {
      if (context && !(await loadContext(token))) return false
      return await loadPreview(token)
    } catch (error) {
      if (owns(token)) { restore(previous); toast(`快速创建预览刷新失败：${error.message || "未知错误"}`, "error") }
      return false
    } finally {
      if (owns(token)) state.loading = false
    }
  }

  async function setIncludeCandidates(value) { const previous = snapshot(); state.includeCandidates = Boolean(value); return reload(previous, { context: true }) }
  async function setTarget(value) {
    const previous = snapshot()
    state.target = value || "world"
    if (state.target === "world") { state.parentEntityId = null; state.parentMapId = null; state.mapType = "world" }
    else { state.parentEntityId ||= state.context?.locations?.[0]?.id || null; state.mapType = "region"; state.parentMapId = state.target === "drilldown" ? state.parentMapId || state.context?.existing_maps?.[0]?.id || null : null }
    return reload(previous)
  }
  async function changeSetting(field, value) { const previous = snapshot(); state[field] = value; return reload(previous) }
  function targetForMap(map) { return map?.parent_map_id ? "drilldown" : map?.parent_entity_id ? "detail" : "world" }
  async function setReplacement(id) {
    const previous = snapshot()
    state.replaceMapId = id || null
    const map = (state.context?.existing_maps || []).find((item) => item.id === id)
    if (map) {
      state.target = targetForMap(map); state.parentEntityId = map.parent_entity_id || null
      state.parentMapId = map.parent_map_id || null; state.mapType = map.map_type
      state.gridWidth = map.grid_width; state.gridHeight = map.grid_height
    }
    return reload(previous)
  }
  async function addExtraLocation(id) { if (!id) return false; const previous = snapshot(); state.extraLocationIds.add(id); return reload(previous) }

  function toggleSelection(id, selected) { const layout = state.activeLayouts.find((item) => item.location_entity_id === id); if (isCandidate(layout)) return; const next = new Set(state.selectedIds); selected ? next.add(id) : next.delete(id); state.selectedIds = next }
  function setAllSelected(value) { state.selectedIds = new Set(value ? state.activeLayouts.filter((item) => !isCandidate(item)).map((item) => item.location_entity_id) : []) }
  function pushHistory() { state.history.push(cloneLayouts(state.activeLayouts)); if (state.history.length > 50) state.history.shift(); state.redo = [] }
  function moveLocation(id, dq, dr) {
    pushHistory()
    const maxQ = Math.max(0, Number(state.preview?.map?.grid_width || state.gridWidth) - 1)
    const maxR = Math.max(0, Number(state.preview?.map?.grid_height || state.gridHeight) - 1)
    state.activeLayouts = state.activeLayouts.map((item) => item.location_entity_id === id ? { ...item, center_hex_q: Math.max(0, Math.min(maxQ, Number(item.center_hex_q) + dq)), center_hex_r: Math.max(0, Math.min(maxR, Number(item.center_hex_r) + dr)), layout_source: "user_drag" } : item)
  }
  function moveLocationTo(id, q, r) {
    const maxQ = Math.max(0, Number(state.preview?.map?.grid_width || state.gridWidth) - 1)
    const maxR = Math.max(0, Number(state.preview?.map?.grid_height || state.gridHeight) - 1)
    state.activeLayouts = state.activeLayouts.map((item) => item.location_entity_id === id ? { ...item, center_hex_q: Math.max(0, Math.min(maxQ, q)), center_hex_r: Math.max(0, Math.min(maxR, r)), layout_source: "user_drag" } : item)
  }
  function resizeLocation(id, direction) { pushHistory(); state.activeLayouts = applyLayoutResize(state.activeLayouts, id, direction) }
  function toggleLock(id) { pushHistory(); state.activeLayouts = state.activeLayouts.map((item) => item.location_entity_id === id ? { ...item, locked: !item.locked, layout_source: "user_lock" } : item) }
  function undo() { const previous = state.history.pop(); if (!previous) return; state.redo.push(cloneLayouts(state.activeLayouts)); state.activeLayouts = previous }
  function redo() { const next = state.redo.pop(); if (!next) return; state.history.push(cloneLayouts(state.activeLayouts)); state.activeLayouts = next }
  function locationName(id) { return [...(state.context?.locations || []), ...(state.context?.candidate_locations || [])].find((item) => item.id === id)?.name || "未命名地点" }

  async function submit() {
    if (!owns()) { toast("当前项目已切换，请返回原项目重新打开快速创建", "warning"); return false }
    const layouts = state.activeLayouts.filter((item) => state.selectedIds.has(item.location_entity_id))
    if (!layouts.length) { toast("请至少选择一个地点", "warning"); return false }
    if (state.replaceMapId && !confirm("将替换该地图的地点布局与快速创建事实；底图、覆盖层、标记和领地会保留。继续吗？")) return false
    const token = state.generation
    state.saving = true
    try {
      const created = await api.world.confirmQuickCreateMap({ ...previewPayload(), name: state.mapName.trim() || state.preview?.map?.name || undefined, layouts }, projectId)
      if (!owns(token)) { toast("地图已在原项目创建，当前项目已切换", "warning"); return false }
      await onCreated?.(created.map)
      close()
      toast("地图已快速创建", "success")
      return true
    } catch (error) {
      if (owns(token)) toast(`快速创建地图失败：${error.message || "未知错误"}`, "error")
      return false
    } finally { if (owns(token)) state.saving = false }
  }

  return { state, open, close, submit, previewPayload, isCandidate, setIncludeCandidates, setTarget, changeSetting, setReplacement, addExtraLocation, toggleSelection, setAllSelected, pushHistory, moveLocation, moveLocationTo, resizeLocation, toggleLock, undo, redo, locationName, targetForMap }
}
