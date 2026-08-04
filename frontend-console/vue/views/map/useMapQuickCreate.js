import { reactive, toRaw } from "vue"
import { applyLayoutResize } from "../../../views/mapGeoLayoutEngine.js"
import { getApi, getAppState, getConfirm, getToast } from "../../bridge/index.js"

const cloneLayouts = (items) => (items || []).map((item) => ({ ...item }))
const cloneData = (value) => value == null ? value : structuredClone(toRaw(value))
const isRouteHandoff = (value, projectId) => value?.kind === "map-quick-create-route-handoff"
  && value.projectId === projectId

export function useMapQuickCreate({ projectId, onCreated }) {
  const api = getApi()
  const toast = getToast()
  const confirm = getConfirm()
  let committedBaseline = null
  const state = reactive({
    open: false, loading: false, saving: false, error: null,
    context: null, preview: null, activeLayouts: [], history: [], redo: [],
    selectedIds: new Set(), previousLayoutIds: new Set(), extraLocationIds: new Set(),
    includeCandidates: false, target: "world", parentEntityId: null, parentMapId: null,
    replaceMapId: null, mapType: "world", gridWidth: 40, gridHeight: 30,
    baseTemplate: "blank", mapName: "", mapNameTouched: false, generation: 0, requestGeneration: 0,
  })

  const owns = (token = state.generation, request = state.requestGeneration) => state.open
    && token === state.generation
    && request === state.requestGeneration
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

  function close() { state.open = false; state.saving = false; state.generation += 1; state.requestGeneration += 1 }

  function previewPayload(source = state) {
    return {
      target: source.target,
      parent_entity_id: source.parentEntityId,
      parent_map_id: source.parentMapId,
      replace_map_id: source.replaceMapId,
      map_type: source.replaceMapId ? undefined : source.mapType,
      grid_width: source.replaceMapId ? undefined : Number(source.gridWidth),
      grid_height: source.replaceMapId ? undefined : Number(source.gridHeight),
      base_template: source.baseTemplate,
      location_entity_ids: [...source.extraLocationIds],
      include_candidates: source.includeCandidates,
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

  async function loadContext(token = state.generation, request = state.requestGeneration, includeCandidates = state.includeCandidates) {
    const context = await api.world.getMapQuickCreateContext(projectId, includeCandidates)
    if (!owns(token, request)) return false
    state.context = context
    return true
  }

  async function loadPreview(token = state.generation, request = state.requestGeneration, intent = snapshot()) {
    const preview = await api.world.previewQuickCreateMap(previewPayload(intent), projectId)
    if (!owns(token, request)) return false
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
    committedBaseline = null
    state.open = true
    state.loading = true
    const token = ++state.generation
    const request = ++state.requestGeneration
    try {
      const intent = snapshot()
      if (!(await loadContext(token, request, intent.includeCandidates))) return false
      if (!(await loadPreview(token, request, intent))) return false
      committedBaseline = snapshot()
      return true
    } catch (error) {
      if (owns(token, request)) { state.error = error.message || "快速创建预览加载失败"; toast(`快速创建地图失败：${state.error}`, "error") }
      return false
    } finally {
      if (owns(token, request)) state.loading = false
    }
  }

  function snapshot() {
    return {
      context: cloneData(state.context), preview: cloneData(state.preview), activeLayouts: cloneLayouts(state.activeLayouts),
      history: state.history.map(cloneLayouts), redo: state.redo.map(cloneLayouts),
      selectedIds: new Set(state.selectedIds), previousLayoutIds: new Set(state.previousLayoutIds),
      extraLocationIds: new Set(state.extraLocationIds), includeCandidates: state.includeCandidates,
      target: state.target, parentEntityId: state.parentEntityId, parentMapId: state.parentMapId,
      replaceMapId: state.replaceMapId, mapType: state.mapType, gridWidth: state.gridWidth,
      gridHeight: state.gridHeight, baseTemplate: state.baseTemplate, mapName: state.mapName,
      mapNameTouched: state.mapNameTouched,
    }
  }

  function cloneSnapshot(value) {
    return {
      ...value,
      context: cloneData(value.context), preview: cloneData(value.preview), activeLayouts: cloneLayouts(value.activeLayouts),
      history: value.history.map(cloneLayouts), redo: value.redo.map(cloneLayouts),
      selectedIds: new Set(value.selectedIds), previousLayoutIds: new Set(value.previousLayoutIds),
      extraLocationIds: new Set(value.extraLocationIds),
    }
  }

  function restore(value) { Object.assign(state, value) }

  function restoreCommittedBaseline() {
    if (!committedBaseline) return
    // Naming is synchronous author input, not preview output.  Keep a draft
    // typed while a request was in flight even when the preview rolls back.
    const draft = { mapName: state.mapName, mapNameTouched: state.mapNameTouched }
    restore(cloneSnapshot(committedBaseline))
    Object.assign(state, draft)
  }

  async function reload() {
    state.loading = true
    const token = state.generation
    const request = ++state.requestGeneration
    const intent = snapshot()
    try {
      // Context and preview are a single committed view.  Always obtain both
      // from this request snapshot so a newer setting request cannot pair its
      // preview with an older include-candidates context.
      if (!(await loadContext(token, request, intent.includeCandidates))) return false
      if (!(await loadPreview(token, request, intent))) return false
      committedBaseline = snapshot()
      return true
    } catch (error) {
      if (owns(token, request)) { restoreCommittedBaseline(); toast(`快速创建预览刷新失败：${error.message || "未知错误"}`, "error") }
      return false
    } finally {
      if (owns(token, request)) state.loading = false
    }
  }

  async function setIncludeCandidates(value) { state.includeCandidates = Boolean(value); return reload() }
  async function setTarget(value) {
    state.target = value || "world"
    if (state.target === "world") { state.parentEntityId = null; state.parentMapId = null; state.mapType = "world" }
    else { state.parentEntityId ||= state.context?.locations?.[0]?.id || null; state.mapType = "region"; state.parentMapId = state.target === "drilldown" ? state.parentMapId || state.context?.existing_maps?.[0]?.id || null : null }
    return reload()
  }
  async function changeSetting(field, value) { state[field] = value; return reload() }
  function targetForMap(map) { return map?.parent_map_id ? "drilldown" : map?.parent_entity_id ? "detail" : "world" }
  async function setReplacement(id) {
    state.replaceMapId = id || null
    const map = (state.context?.existing_maps || []).find((item) => item.id === id)
    if (map) {
      state.target = targetForMap(map); state.parentEntityId = map.parent_entity_id || null
      state.parentMapId = map.parent_map_id || null; state.mapType = map.map_type
      state.gridWidth = map.grid_width; state.gridHeight = map.grid_height
    }
    return reload()
  }
  async function addExtraLocation(id) { if (!id) return false; state.extraLocationIds.add(id); return reload() }

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
    if (state.saving) return false
    if (!owns()) { toast("当前项目已切换，请返回原项目重新打开快速创建", "warning"); return false }
    const layouts = state.activeLayouts.filter((item) => state.selectedIds.has(item.location_entity_id))
    if (!layouts.length) { toast("请至少选择一个地点", "warning"); return false }
    if (state.replaceMapId && !confirm("将替换该地图的地点布局与快速创建事实；底图、覆盖层、标记和领地会保留。继续吗？")) return false
    const token = state.generation
    const request = state.requestGeneration
    let committed = false
    state.saving = true
    try {
      const created = await api.world.confirmQuickCreateMap({ ...previewPayload(), name: state.mapName.trim() || state.preview?.map?.name || undefined, layouts }, projectId)
      committed = true
      if (!owns(token, request)) return false
      try {
        const continued = await onCreated?.(created.map)
        if (continued === false) throw new Error("workspace continuation declined")
        if (!owns(token, request) && isRouteHandoff(continued, projectId) && getAppState()?.currentProjectId === projectId) {
          toast("地图已快速创建", "success")
          return true
        }
      }
      catch (error) {
        // The API response is the commit point.  Do not leave the form usable
        // after a downstream catalog/navigation failure, otherwise the author
        // can accidentally submit the same creation again.
        if (owns(token, request)) {
          state.error = "地图已创建，但工作区刷新或打开失败。请从地图列表继续。"
          close()
          toast(state.error, "warning")
        }
        return false
      }
      if (!owns(token, request)) return false
      close()
      toast("地图已快速创建", "success")
      return true
    } catch (error) {
      if (owns(token, request) && !committed) toast(`快速创建地图失败：${error.message || "未知错误"}`, "error")
      return false
    } finally { if (owns(token, request)) state.saving = false }
  }

  return { state, open, close, submit, previewPayload, isCandidate, setIncludeCandidates, setTarget, changeSetting, setReplacement, addExtraLocation, toggleSelection, setAllSelected, pushHistory, moveLocation, moveLocationTo, resizeLocation, toggleLock, undo, redo, locationName, targetForMap }
}
