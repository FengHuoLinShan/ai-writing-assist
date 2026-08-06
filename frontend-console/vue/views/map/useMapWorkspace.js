import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef } from "vue"
import { getApi, getAppState, getCloseModal, getConfirmAction, getEsc, getRouter, getShowModalHtml, getToast } from "../../bridge/index.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { buildMapQuery } from "../../../views/mapRouteContext.js"
import { mapAssetDisplay } from "../../../shared/assetDisplayState.js"
import { confirmAsync } from "../../../shared/confirmAsync.js"
import {
  createMapTimelineState,
  normalizeMapStateAtResponse,
  normalizeMapTimelineResponse,
} from "../../../views/mapTimelineProjection.js"
import {
  ARCHIVED_PAGE_SIZE,
  DEFAULT_MAP_LAYERS,
  MAP_BATCH_ID_LIMIT,
  MAP_INBOX_PAGE_SIZE,
  clearRecentMap,
  createMapInboxFilters,
  filterInboxItems,
  listItems,
  mapSceneLabel,
  mapSourceText,
  readRecentMap,
  saveRecentMap,
} from "./mapModel.js"
import { createMapModalController } from "./mapModalController.js"
import { useMapQuickCreate } from "./useMapQuickCreate.js"
import { useMapDynamicEditor } from "./useMapDynamicEditor.js"
import { useMapEnrichment } from "./useMapEnrichment.js"

function emptySummary() {
  return { loading: false, loaded: false, dashboard: null, observations: [], facts: [], historyItems: [], historyLoaded: false, historyLoading: false, error: null }
}

// “分配并继续”会导航到目标地图并重建 Vue island。仅在当前 JS 会话中
// 跨这一次路由交接保留待打开的 observation，不把业务内容写入持久存储。
const pendingObservationEditors = new Map()

function itemId(item) { return item?.item_id || item?.id || item?.event_id || null }

export function useMapWorkspace(props) {
  const api = getApi()
  const router = getRouter()
  const appState = getAppState()
  const toast = getToast()
  const confirmAction = getConfirmAction()
  const esc = getEsc()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const projectId = props.projectId
  const maps = shallowRef([...(props.maps || [])])
  const archivedMaps = shallowRef([...(props.archivedMaps || [])])
  const locations = shallowRef([...(props.locations || [])])
  const inbox = reactive({
    loading: false,
    items: [...(props.inbox?.items || [])],
    total: Number(props.inbox?.total || 0),
    hasMore: Boolean(props.inbox?.hasMore),
    error: props.inbox?.error || null,
    page: Number(props.inbox?.page || 0),
    filters: { ...createMapInboxFilters(), ...(props.inbox?.filters || {}) },
  })
  const route = props.route || {}
  const mode = ref(route.mapId && !["overview", "recent"].includes(route.mode) ? "map" : "overview")
  const activeMapId = ref(mode.value === "map" ? route.mapId : null)
  const activeSceneId = ref(route.sceneId || null)
  const focusEntityId = ref(route.focusEntityId || null)
  const focusHexQ = ref(route.focusHexQ ?? null)
  const focusHexR = ref(route.focusHexR ?? null)
  const focusPathId = ref(route.focusPathId || null)
  const focusLayerNodeId = ref(route.focusLayerNodeId || null)
  const focusedDynamicItemId = ref(null)
  const viewMode = ref(["dashboard", "live", "lens"].includes(route.mode) ? route.mode : "dashboard")
  const lowMotion = ref(false)
  const layers = reactive({ ...DEFAULT_MAP_LAYERS })
  const editingState = reactive({ editing: false, dirty: false, editorLayer: "none" })
  const showArchived = ref(false)
  const archivedPage = ref(0)
  const searchQuery = ref("")
  const message = ref(null)
  const showHistory = ref(false)
  const recentRevision = ref(0)
  const dynamicSummary = reactive(emptySummary())
  const playback = reactive({ loading: false, loaded: false, playback: null, error: null, playing: false, activeIndex: 0 })
  const timeline = reactive(createMapTimelineState())
  const viewport = ref(null)
  const dynamicEditorEntities = shallowRef([])
  const dynamicGeneration = ref(0)
  const timelineGeneration = ref(0)
  let disposed = false
  let playbackTimer = null
  let timelineTimer = null
  let editorEntitiesPromise = null
  let factConfirmationGeneration = 0

  const activeMap = computed(() => maps.value.find((item) => item.id === activeMapId.value) || null)
  const recentMap = computed(() => { recentRevision.value; return readRecentMap(projectId) })
  const searchResults = computed(() => {
    const query = searchQuery.value.trim().toLowerCase()
    if (!query) return []
    return [
      ...maps.value.filter((item) => (item.name || "").toLowerCase().includes(query)).map((item) => ({ type: "map", id: item.id, name: item.name })),
      ...locations.value.filter((item) => (item.name || "").toLowerCase().includes(query)).map((item) => ({ type: "location", id: item.id, name: item.name })),
    ]
  })
  const mapByParent = computed(() => {
    const result = new Map()
    for (const map of maps.value) {
      const parent = map.parent_map_id || null
      if (!result.has(parent)) result.set(parent, [])
      result.get(parent).push(map)
    }
    return result
  })
  const inboxItems = computed(() => filterInboxItems(inbox.items, inbox.filters))
  const archivedRoots = computed(() => {
    const ids = new Set(archivedMaps.value.map((item) => item.id))
    return archivedMaps.value.filter((item) => !item.parent_map_id || !ids.has(item.parent_map_id))
  })
  const archivedPageCount = computed(() => Math.max(1, Math.ceil(archivedRoots.value.length / ARCHIVED_PAGE_SIZE)))
  const visibleArchivedMaps = computed(() => archivedRoots.value.slice(archivedPage.value * ARCHIVED_PAGE_SIZE, (archivedPage.value + 1) * ARCHIVED_PAGE_SIZE))
  const dashboardQueue = computed(() => dynamicSummary.dashboard?.dynamic_queue || [])
  const mergedDashboardQueue = computed(() => dashboardQueue.value.map((item) => {
      if (item.item_kind !== "observation") return item
      const fresh = dynamicSummary.observations.find((entry) => String(itemId(entry)) === String(itemId(item)))
      return fresh ? { ...item, ...fresh } : item
    }))
  const activeQueue = computed(() => mergedDashboardQueue.value.filter(
    (item) => !mapAssetDisplay(item).isHistory,
  ))
  const historyQueue = computed(() => {
    const result = new Map()
    for (const item of [
      ...mergedDashboardQueue.value.filter((entry) => mapAssetDisplay(entry).isHistory),
      ...dynamicSummary.historyItems,
    ]) {
      result.set(`${item.item_kind || "item"}:${itemId(item) || result.size}`, item)
    }
    return [...result.values()]
  })
  const observationById = computed(() => new Map(dynamicSummary.observations.flatMap((item) => [[String(itemId(item)), item], [String(item.id || ""), item]])))
  const factById = computed(() => new Map(dynamicSummary.facts.flatMap((item) => [[String(itemId(item)), item], [String(item.id || ""), item]])))
  const currentTimelineScene = computed(() => timeline.data?.scenes?.[timeline.activeIndex] || null)
  const activeSceneLabel = computed(() => {
    const scene = (timeline.data?.scenes || []).find((item) => item.scene_id === activeSceneId.value)
    if (scene?.scene_index != null) return mapSceneLabel(scene.scene_index)
    const queueItem = dashboardQueue.value.find(
      (item) => item.scene_id === activeSceneId.value || item.source_scene_id === activeSceneId.value,
    )
    return queueItem?.time_label || (activeSceneId.value ? "当前场景" : "当前正式世界状态")
  })
  const currentLiveFacts = computed(() => activeQueue.value.filter((item) => (
    item.item_kind === "fact"
    && (!activeSceneId.value || item.scene_id === activeSceneId.value || item.source_scene_id === activeSceneId.value)
  )))
  function dynamicItemRelatedToEntity(item, entityId) {
    if (!item || !entityId) return false
    return [
      item.target_entity_id,
      item.entity_id,
      item.location_entity_id,
      item.faction_entity_id,
      ...(Array.isArray(item.related_entity_ids) ? item.related_entity_ids : []),
      ...(Array.isArray(item.normalized_value?.related_entity_ids)
        ? item.normalized_value.related_entity_ids
        : []),
    ].filter(Boolean).includes(entityId)
  }
  const lensHasFocus = computed(() => Boolean(
    focusEntityId.value || focusedDynamicItemId.value || activeSceneId.value,
  ))
  const lensContextItems = computed(() => {
    const timelineItems = dynamicSummary.dashboard?.inspector?.timeline || []
    if (timelineItems.length) return timelineItems
    return activeQueue.value.filter((item) => (
      (focusEntityId.value && dynamicItemRelatedToEntity(item, focusEntityId.value))
      || (activeSceneId.value && (
        item.scene_id === activeSceneId.value || item.source_scene_id === activeSceneId.value
      ))
    ))
  })
  const lensFocusableItems = computed(() => {
    const seen = new Set()
    return activeQueue.value.filter((item) => {
      const id = item.target_entity_id
      if (!id || seen.has(id)) return false
      seen.add(id)
      return true
    }).slice(0, 6)
  })
  const timelineProjection = computed(() => {
    if (!timeline.data || timeline.sceneIndex == null || timeline.stateError) return null
    return {
      projectionToken: timeline.stateAt?.projection_token || timeline.data?.projection_token || `vue-map-${timeline.sceneIndex}`,
      sceneIndex: timeline.sceneIndex,
      stateItems: timeline.stateAt?.items || [],
      conflicts: timeline.stateAt?.conflicts || [],
      deltas: timeline.data?.deltas || [],
      candidates: timeline.data?.candidates || [],
      includeCandidates: Boolean(timeline.includeCandidates),
      selectedTracks: { ...timeline.selectedTracks },
      lowMotion: lowMotion.value,
    }
  })

  function owned(token = dynamicGeneration.value) {
    return !disposed && token === dynamicGeneration.value
      && appState?.currentProjectId === projectId
      && appState?.currentView === "map"
  }

  function routeQuery(overrides = {}) {
    const mapId = Object.hasOwn(overrides, "mapId") ? overrides.mapId : activeMapId.value
    return buildMapQuery({
      projectId,
      mapId,
      sceneId: Object.hasOwn(overrides, "sceneId") ? overrides.sceneId : activeSceneId.value,
      focusEntityId: Object.hasOwn(overrides, "focusEntityId") ? overrides.focusEntityId : focusEntityId.value,
      focusHexQ: Object.hasOwn(overrides, "focusHexQ") ? overrides.focusHexQ : focusHexQ.value,
      focusHexR: Object.hasOwn(overrides, "focusHexR") ? overrides.focusHexR : focusHexR.value,
      focusPathId: Object.hasOwn(overrides, "focusPathId") ? overrides.focusPathId : focusPathId.value,
      focusLayerNodeId: Object.hasOwn(overrides, "focusLayerNodeId") ? overrides.focusLayerNodeId : focusLayerNodeId.value,
      mode: overrides.mode || (mapId ? viewMode.value : "overview"),
    })
  }

  function navigateRoute(overrides = {}, replace = false) {
    const query = routeQuery(overrides)
    if (replace && typeof router?.replace === "function") return router.replace("map", null, query)
    return router?.navigate?.("map", null, true, query)
  }

  async function listAll(fetchPage, limit) {
    const output = []
    let skip = 0
    while (true) {
      const page = listItems(await fetchPage(skip, limit))
      output.push(...page)
      if (!page.length || page.length < limit) return output
      skip += page.length
    }
  }

  async function loadDynamicEditorEntities() {
    if (dynamicEditorEntities.value.length) return dynamicEditorEntities.value
    if (!editorEntitiesPromise) {
      editorEntitiesPromise = listAll(
        (skip, limit) => api.world.listEntities({ novel_id: projectId, display_state: "active", skip, limit }),
        50,
      ).then((items) => items.map((item) => ({
        id: item.id,
        name: item.name,
        entityType: item.entity_type || null,
      }))).finally(() => { editorEntitiesPromise = null })
    }
    const items = await editorEntitiesPromise
    if (!disposed && appState?.currentProjectId === projectId) dynamicEditorEntities.value = items
    return dynamicEditorEntities.value
  }

  async function reloadCatalog() {
    const token = dynamicGeneration.value
    const [nextMaps, nextArchived, nextLocations] = await Promise.all([
      listAll((skip, limit) => api.world.listMaps({ novel_id: projectId, status: "active", skip, limit }), 500),
      listAll((skip, limit) => api.world.listMaps({ novel_id: projectId, status: "archived", skip, limit }), 500),
      listAll((skip, limit) => api.world.listEntities({ novel_id: projectId, entity_type: "location", skip, limit }), 50),
    ])
    if (!owned(token)) return false
    maps.value = nextMaps
    archivedMaps.value = nextArchived
    locations.value = nextLocations
    return true
  }

  async function loadInbox() {
    const token = dynamicGeneration.value
    inbox.loading = true
    inbox.error = null
    try {
      const response = await api.world.listProjectMapObservationInbox(projectId, { ...inbox.filters, skip: inbox.page * MAP_INBOX_PAGE_SIZE, limit: MAP_INBOX_PAGE_SIZE })
      if (!owned(token)) return false
      inbox.items = listItems(response)
      inbox.total = Number(response?.total || 0)
      inbox.hasMore = Boolean(response?.has_more)
      const lastPage = Math.max(0, Math.ceil(inbox.total / MAP_INBOX_PAGE_SIZE) - 1)
      if (inbox.page > lastPage) { inbox.page = lastPage; return loadInbox() }
      return true
    } catch (error) {
      if (owned(token)) inbox.error = error.message || "地图收件箱加载失败"
      return false
    } finally {
      if (owned(token)) inbox.loading = false
    }
  }

  function resetDynamic() {
    Object.assign(dynamicSummary, emptySummary())
    Object.assign(playback, { loading: false, loaded: false, playback: null, error: null, playing: false, activeIndex: 0 })
    const preferences = { includeCandidates: timeline.includeCandidates, speedMs: timeline.speedMs, selectedTracks: { ...timeline.selectedTracks } }
    Object.assign(timeline, createMapTimelineState(), preferences)
  }

  async function loadTimelineState(sceneIndex) {
    if (!activeMapId.value || sceneIndex == null) return false
    const token = ++timelineGeneration.value
    timeline.sceneIndex = Number(sceneIndex)
    timeline.stateLoading = true
    timeline.stateError = null
    try {
      const response = await api.world.getMapStateAt(activeMapId.value, projectId, Number(sceneIndex), { focusEntityId: focusEntityId.value, limit: 500 })
      if (disposed || token !== timelineGeneration.value || appState?.currentProjectId !== projectId || timeline.sceneIndex !== Number(sceneIndex)) return false
      timeline.stateAt = normalizeMapStateAtResponse(response)
      timeline.stateLoading = false
      return true
    } catch (error) {
      if (token === timelineGeneration.value) {
        timeline.stateAt = null
        timeline.stateLoading = false
        timeline.stateError = error.message || "场景正式状态暂不可用"
      }
      return false
    }
  }

  async function loadDynamic({ force = false } = {}) {
    if (disposed || !activeMapId.value) return false
    if (!force && dynamicSummary.loaded && !dynamicSummary.error) return true
    const token = ++dynamicGeneration.value
    const mapId = activeMapId.value
    const sceneId = activeSceneId.value
    const entityId = focusEntityId.value
    Object.assign(dynamicSummary, emptySummary(), { loading: true })
    Object.assign(playback, { loading: true, loaded: false, playback: null, error: null, playing: false, activeIndex: 0 })
    timeline.loading = true
    try {
      const [dashboard, playbackData, timelineResult, observationPage] = await Promise.all([
        api.world.getMapDashboard(mapId, projectId, sceneId, entityId, focusedDynamicItemId.value),
        api.world.getMapPlayback(mapId, projectId, sceneId, entityId, true),
        Promise.resolve(api.world.getMapTimeline(mapId, projectId, { focusEntityId: entityId, includeCandidates: timeline.includeCandidates || undefined, limit: 500 })).then((data) => ({ data })).catch((error) => ({ error })),
        api.world.listMapObservations(mapId, projectId, null),
      ])
      if (!owned(token) || activeMapId.value !== mapId || activeSceneId.value !== sceneId || focusEntityId.value !== entityId) return false
      const queueObservations = new Map((dashboard?.dynamic_queue || []).filter((item) => item.item_kind === "observation").map((item) => [String(itemId(item)), item]))
      for (const item of listItems(observationPage)) {
        const id = String(itemId(item))
        queueObservations.set(id, { ...(queueObservations.get(id) || {}), ...item })
      }
      Object.assign(dynamicSummary, {
        loading: false, loaded: true, dashboard,
        observations: [...queueObservations.values()].map((item) => ({ ...item, item_id: itemId(item), item_kind: "observation", title: item.target_name || item.title || item.dynamic_type || "地图待处理项" })),
        facts: (dashboard?.dynamic_queue || []).filter((item) => item.item_kind === "fact"),
        historyItems: [], historyLoaded: false, historyLoading: false, error: null,
      })
      consumePendingObservationEditor()
      Object.assign(playback, { loading: false, loaded: true, playback: playbackData, error: null, playing: false, activeIndex: 0 })
      if (timelineResult.data) {
        const data = normalizeMapTimelineResponse(timelineResult.data)
        let index = data.scenes.findIndex((item) => item.scene_index === timeline.sceneIndex)
        if (index < 0) index = Math.max(0, data.scenes.length - 1)
        Object.assign(timeline, { loading: false, loaded: true, error: null, data, activeIndex: index, sceneIndex: data.scenes[index]?.scene_index ?? null, playing: false })
        if (timeline.sceneIndex != null) await loadTimelineState(timeline.sceneIndex)
      } else Object.assign(timeline, { loading: false, loaded: true, error: timelineResult.error?.message || "场景时间轴暂不可用", data: null, playing: false })
      return true
    } catch (error) {
      if (!owned(token)) return false
      Object.assign(dynamicSummary, emptySummary(), { loaded: true, error: "地图动态事实暂不可用" })
      Object.assign(playback, { loading: false, loaded: true, playback: null, error: "世界动态播放暂不可用", playing: false, activeIndex: 0 })
      Object.assign(timeline, { loading: false, loaded: true, error: "场景时间轴暂不可用", data: null, playing: false })
      toast(`地图动态事实暂不可用：${error.message || "加载失败"}`, "warning")
      return false
    }
  }

  async function openMap(mapId, options = {}) {
    if (mode.value === "map" && viewport.value?.canLeave?.() === false) return false
    mode.value = "map"
    activeMapId.value = mapId
    activeSceneId.value = options.sceneId ?? null
    focusEntityId.value = options.focusEntityId ?? null
    focusHexQ.value = options.focusHexQ ?? null
    focusHexR.value = options.focusHexR ?? null
    focusPathId.value = options.focusPathId ?? null
    focusLayerNodeId.value = options.focusLayerNodeId ?? null
    if (["dashboard", "live", "lens"].includes(options.viewMode)) viewMode.value = options.viewMode
    const map = maps.value.find((item) => item.id === mapId)
    if (map) { saveRecentMap(projectId, map); recentRevision.value += 1 }
    resetDynamic()
    const navigated = await navigateRoute({}, options.replace === true)
    if (navigated === false) return false
    if (disposed) return options.quickCreateHandoff
      ? { kind: "map-quick-create-route-handoff", projectId }
      : true
    await loadDynamic({ force: true })
    return true
  }

  async function openRecent() {
    const recent = readRecentMap(projectId)
    if (recent?.mapId) {
      try {
        const map = await api.world.getMap(recent.mapId, projectId)
        return openMap(map.id, { viewMode: activeSceneId.value || focusEntityId.value ? "live" : "dashboard", replace: true })
      } catch {
        clearRecentMap(projectId)
        recentRevision.value += 1
      }
    }
    try {
      const target = await api.world.getMapOpenTarget(projectId, { sceneId: activeSceneId.value, focusEntityId: focusEntityId.value })
      if (target?.fallback_message) toast(target.fallback_message, "warning")
      if (target?.map_id) return openMap(target.map_id, { sceneId: target.scene_id, focusEntityId: target.focus_entity_id, focusPathId: target.focus_path_id, focusLayerNodeId: target.focus_layer_node_id, viewMode: target.mode || "dashboard", replace: true })
    } catch {}
    message.value = "最近地图不可用，已返回地图总览"
    toast(message.value, "warning")
    return false
  }

  async function returnOverview() {
    if (viewport.value?.canLeave?.() === false) return false
    mode.value = "overview"
    activeMapId.value = null
    activeSceneId.value = null
    focusEntityId.value = null
    focusPathId.value = null
    focusLayerNodeId.value = null
    resetDynamic()
    await navigateRoute({ mapId: null, sceneId: null, focusEntityId: null, focusPathId: null, focusLayerNodeId: null, mode: "overview" })
    return true
  }

  function setViewMode(next) {
    if (!["dashboard", "live", "lens"].includes(next)) return false
    viewMode.value = next
    navigateRoute({ mode: next }, true)
    return true
  }

  function setLayer(layer, visible) { if (layer in layers) layers[layer] = Boolean(visible) }
  function setLowMotion(value) { lowMotion.value = Boolean(value) }
  async function openLocation(locationId) {
    const map = maps.value.find((item) => item.parent_entity_id === locationId) || maps.value[0]
    if (!map) { toast("该地点尚未绑定地图", "warning"); return false }
    return openMap(map.id, { focusEntityId: locationId, viewMode: "live" })
  }

  async function setTimelinePosition(position, { fromPlayback = false } = {}) {
    const scenes = timeline.data?.scenes || []
    if (!scenes.length) return false
    const next = Math.max(0, Math.min(Number(position) || 0, scenes.length - 1))
    timeline.activeIndex = next
    timeline.sceneIndex = scenes[next].scene_index
    timeline.stateAt = null
    timeline.stateError = null
    if (!fromPlayback) timeline.playing = false
    viewport.value?.clearPathFocus?.()
    return loadTimelineState(timeline.sceneIndex)
  }

  function stopTimeline() { timeline.playing = false; clearTimeout(timelineTimer); timelineTimer = null }
  async function stepTimeline(delta, fromPlayback = false) {
    const next = timeline.activeIndex + Number(delta || 0)
    if (next < 0 || next >= (timeline.data?.scenes || []).length) { if (fromPlayback) stopTimeline(); return false }
    return setTimelinePosition(next, { fromPlayback })
  }
  function scheduleTimeline() {
    clearTimeout(timelineTimer)
    timelineTimer = setTimeout(async () => {
      if (!timeline.playing || editingState.editing) return
      const moved = await stepTimeline(1, true)
      if (moved && timeline.playing) scheduleTimeline()
    }, Math.max(600, Number(timeline.speedMs || 1600)))
  }
  async function startTimeline() {
    if (editingState.editing) { toast("请先结束地图编辑，再播放故事时间轴", "info"); return false }
    const scenes = timeline.data?.scenes || []
    if (!scenes.length) return startPlayback()
    if (timeline.activeIndex >= scenes.length - 1) await setTimelinePosition(0, { fromPlayback: true })
    timeline.playing = true
    scheduleTimeline()
    return true
  }
  async function setTimelineCandidates(value) { timeline.includeCandidates = Boolean(value); timeline.playing = false; return loadDynamic({ force: true }) }
  function setTimelineTrack(track, value) { if (track in timeline.selectedTracks) { timeline.selectedTracks[track] = Boolean(value); timeline.playing = false } }

  function stopPlayback({ clearFocus = true } = {}) {
    playback.playing = false
    clearTimeout(playbackTimer)
    playbackTimer = null
    if (clearFocus) viewport.value?.clearPathFocus?.()
  }
  function focusPlayback() {
    const event = playback.playback?.events?.[playback.activeIndex]
    const anchor = event?.spatial_anchor || {}
    const pathId = anchor.path_id || event?.path_id
    if (pathId) viewport.value?.focusPath?.(pathId, anchor.focus_layer_node_id || anchor.layer_node_id || event?.layer_node_id || null)
    else viewport.value?.clearPathFocus?.()
  }
  function schedulePlayback() {
    clearTimeout(playbackTimer)
    playbackTimer = setTimeout(() => {
      if (!playback.playing) return
      const events = playback.playback?.events || []
      if (playback.activeIndex >= events.length - 1) return stopPlayback()
      playback.activeIndex += 1
      focusPlayback()
      schedulePlayback()
    }, lowMotion.value ? 1600 : 2200)
  }
  function startPlayback() {
    if (!(playback.playback?.events || []).length) { toast("暂无可播放动态", "info"); return false }
    playback.activeIndex = 0; playback.playing = true; focusPlayback(); schedulePlayback(); return true
  }

  function applyLatest(latest, captured = null) {
    if (!latest?.id) return
    const patch = (item) => { if (String(itemId(item)) === String(latest.id)) Object.assign(item, latest) }
    if (captured) patch(captured)
    inbox.items.forEach(patch); dynamicSummary.observations.forEach(patch); dashboardQueue.value.forEach(patch)
  }
  function handleConflict(error, item, message) {
    const latest = error?.body?.context?.latest
    if (error?.status !== 409 || !latest) return false
    applyLatest(latest, item)
    toast(message, "warning")
    return true
  }

  function confirmObservation(item) {
    if (item?.eligibility && !item.eligibility.can_confirm) { toast(`还不能采用，请先补全：${(item.eligibility.missing_item_labels || []).join("、") || "结构化字段"}`, "warning"); return false }
    return confirmAction(`采用地图映射「${item.title || item.target_name || "地图映射"}」并写入当前有效事实？`, async () => {
      try { await api.world.confirmMapObservation(activeMapId.value, itemId(item), projectId, item.updated_at); toast("地图事实已采用", "success"); return loadDynamic({ force: true }) }
      catch (error) { if (!handleConflict(error, item, "该建议已更新；已加载服务器最新摘要，请核对后重试")) toast(`采用失败：${error.message || "未知错误"}`, "error"); return false }
    })
  }
  function ignoreObservation(item) {
    return confirmAction(`忽略地图映射「${item.title || item.target_name || "地图映射"}」？`, async () => {
      try { await api.world.ignoreMapObservation(activeMapId.value, itemId(item), projectId, item.updated_at); toast("地图映射已忽略", "success"); return loadDynamic({ force: true }) }
      catch (error) { if (!handleConflict(error, item, "该建议已更新；请核对后重试")) toast(`忽略失败：${error.message || "未知错误"}`, "error"); return false }
    })
  }
  async function conflictObservation(item) { return saveObservation(item, { expected_updated_at: item.updated_at, review_state: "conflicted" }, "地图映射已标记为冲突") }
  async function saveObservation(item, payload, successMessage = "地图待处理项已保存") {
    try { await api.world.updateMapObservationReview(activeMapId.value, itemId(item), projectId, { ...payload, expected_updated_at: payload.expected_updated_at || item.updated_at }); toast(successMessage, "success"); await loadDynamic({ force: true }); return true }
    catch (error) { if (!handleConflict(error, item, "该建议已被其他操作更新；当前表单未关闭，请核对后重试")) toast(`更新失败：${error.message || "未知错误"}`, "error"); return false }
  }
  async function updateFact(item, status) {
    const mapId = activeMapId.value
    const factId = itemId(item)
    const dynamicToken = dynamicGeneration.value
    const confirmationToken = ++factConfirmationGeneration
    const ownsFactUpdate = () => confirmationToken === factConfirmationGeneration
      && activeMapId.value === mapId
      && owned(dynamicToken)
    const confirmed = await confirmAsync(`将地图事实「${item.title || item.target_name || "地图事实"}」更新状态？`, "确认", { confirmAction })
    if (!confirmed || !ownsFactUpdate()) return false
    try {
      await api.world.updateMapFactStatus(mapId, factId, projectId, status)
      if (!ownsFactUpdate()) return false
      toast("地图事实已更新", "success")
      await loadDynamic({ force: true })
      return true
    } catch (error) {
      if (ownsFactUpdate()) toast(`更新失败：${error.message || "未知错误"}`, "error")
      return false
    }
  }
  function unassignObservation(item) {
    return confirmAction(`取消「${item.title || item.target_name || "地图待处理项"}」的地图分配？它将回到项目级地图待处理。`, async () => {
      try { await api.world.assignProjectMapObservation(itemId(item), projectId, null, item.updated_at); toast("已取消分配", "success"); await Promise.all([loadDynamic({ force: true }), loadInbox()]); return true }
      catch (error) { if (!handleConflict(error, item, "地图归属已更新，请核对后重试")) toast(`取消分配失败：${error.message || "未知错误"}`, "error"); return false }
    })
  }
  async function assignObservation(item, mapId) {
    try {
      await api.world.assignProjectMapObservation(item.id, projectId, mapId, item.updated_at)
      inbox.items = inbox.items.filter((entry) => entry.id !== item.id)
      inbox.total = Math.max(0, inbox.total - 1)
      pendingObservationEditors.set(projectId, { mapId, item })
      toast("已分配地图，请继续补全并确认", "success")
      const opened = await openMap(mapId, { viewMode: "dashboard" })
      if (!opened) pendingObservationEditors.delete(projectId)
      return opened
    } catch (error) { pendingObservationEditors.delete(projectId); if (!handleConflict(error, item, "该建议已被其他操作更新，请核对后重试")) toast(`分配失败：${error.message || "未知错误"}`, "error"); return false }
  }
  function ignoreInbox(item) {
    return confirmAction(`忽略地图待处理项「${item.target_name || item.dynamic_type || "地图建议"}」？`, async () => {
      try { await api.world.ignoreProjectMapObservation(item.id, projectId, item.updated_at); inbox.items = inbox.items.filter((entry) => entry.id !== item.id); inbox.total = Math.max(0, inbox.total - 1); toast("地图待处理项已忽略", "success"); return true }
      catch (error) { if (!handleConflict(error, item, "该建议已更新，请核对最新内容")) toast(`忽略失败：${error.message || "未知错误"}`, "error"); return false }
    })
  }
  async function batchReview(group, action) {
    const fallbackIds = dynamicSummary.observations.filter((item) => (
      (item.object_type || item.dynamic_type || "unknown") === group.group_key
      && mapAssetDisplay(item).displayState === "review"
    )).map(itemId)
    const ids = (group.observation_ids || group.item_ids || fallbackIds).slice(0, MAP_BATCH_ID_LIMIT)
    const items = ids.map((id) => observationById.value.get(String(id))).filter(Boolean)
    if (!items.length) { toast("该分组暂无待处理项", "info"); return false }
    if (action === "confirm" && items.some((item) => item.eligibility && !item.eligibility.can_confirm)) { toast("分组中有待补全项，请先打开编辑", "warning"); return false }
    const apiAction = { confirm: "confirm_observations", ignore: "ignore_observations", conflict: "mark_conflicted" }[action]
    return confirmAction(`确定批量处理 ${items.length} 条地图待处理项？`, async () => {
      try { await api.world.runMapBatchAction(activeMapId.value, projectId, { action: apiAction, observation_items: items.map((item) => ({ observation_id: itemId(item), expected_updated_at: item.updated_at })) }); toast("批量修改已完成", "success"); return loadDynamic({ force: true }) }
      catch (error) { const latest = error?.body?.context?.latest; if (error?.status === 409 && latest) applyLatest(latest, items.find((item) => String(itemId(item)) === String(latest.id))); toast(error?.status === 409 ? "批量修改遇到新版本，请核对后重试" : `批量修改失败：${error.message || "未知错误"}`, error?.status === 409 ? "warning" : "error"); return false }
    })
  }

  async function toggleHistory() {
    if (showHistory.value) { showHistory.value = false; return true }
    if (!dynamicSummary.historyLoaded) {
      dynamicSummary.historyLoading = true
      try {
        const [observations, rolledBack, deprecated] = await Promise.all([
          api.world.listMapObservations(activeMapId.value, projectId, "ignored"),
          api.world.listMapFacts(activeMapId.value, projectId, "rolled_back"),
          api.world.listMapFacts(activeMapId.value, projectId, "deprecated"),
        ])
        const facts = new Map([...listItems(rolledBack), ...listItems(deprecated)].map((item) => [itemId(item), item]))
        dynamicSummary.historyItems = [
          ...listItems(observations).map((item) => ({ ...item, item_id: itemId(item), item_kind: "observation", title: item.target_name || item.dynamic_type || "历史地图记录" })),
          ...[...facts.values()].map((item) => ({ ...item, item_id: itemId(item), item_kind: "fact", title: item.target_name || item.dynamic_type || "历史地图记录" })),
        ]
        dynamicSummary.observations.push(...dynamicSummary.historyItems.filter((item) => item.item_kind === "observation"))
        dynamicSummary.facts.push(...dynamicSummary.historyItems.filter((item) => item.item_kind === "fact"))
        dynamicSummary.historyLoaded = true
      } catch (error) { toast(`历史记录加载失败：${error.message || "未知错误"}`, "warning"); return false }
      finally { dynamicSummary.historyLoading = false }
    }
    showHistory.value = true
    return true
  }

  async function archiveMap(map) {
    const impact = await api.world.getMapArchiveImpact(map.id, projectId)
    return confirmAction(`归档「${map.name || "该地图"}」及其 ${impact.map_count || 1} 张地图？内容会保留，可从归档地图恢复。`, async () => {
      try { await api.world.archiveMap(map.id, projectId); if (activeMapId.value === map.id) clearRecentMap(projectId); await reloadCatalog(); toast("地图子树已归档", "success"); return true }
      catch (error) { toast(`归档失败：${error.message || "未知错误"}`, "error"); return false }
    }, "归档子树")
  }
  async function restoreMap(map, rootName) { try { await api.world.restoreMap(map.id, { root_name: rootName || map.name }, projectId); await reloadCatalog(); toast("地图子树已恢复", "success"); return true } catch (error) { toast(`恢复失败：${error.message || "未知错误"}`, "error"); return false } }

  async function showVisualHistory() {
    if (!activeMapId.value || editingState.dirty) {
      toast("请先应用或撤销当前地图草稿，再查看编辑历史", "warning")
      return false
    }
    let response
    try {
      response = await api.world.listMapVisualRevisions(activeMapId.value, projectId, {
        limit: 50,
      })
    } catch (error) {
      toast(`编辑历史加载失败：${error.message || "未知错误"}`, "warning")
      return false
    }
    const items = listItems(response)
    if (!items.length) {
      toast("这张地图还没有已提交的编辑历史", "info")
      return false
    }
    const currentRevision = Math.max(...items.map((item) => Number(item.revision_number || 0)))
    const restorable = items.filter((item) => Number(item.revision_number) < currentRevision)
    if (!restorable.length) {
      toast("这张地图还没有可恢复的较早版本", "info")
      return false
    }
    const operationLabel = (operation) => ({
      baseline: "初始状态",
      editor_apply: "地图编辑",
      revision_restore: "历史恢复",
      marker_archive: "归档标记",
      marker_restore: "恢复标记",
      terrain_layer_archive: "归档地形图层",
      terrain_layer_restore: "恢复地形图层",
      config_update: "地图设置",
      legacy_edit: "地图调整",
    })[operation] || "地图调整"
    const rows = restorable.map((item, index) => {
      const changed = Array.isArray(item.forward_changes) ? item.forward_changes.length : 0
      const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : "时间未知"
      return `<label class="map-archived-row"><input type="radio" name="map-visual-revision" value="${esc(item.revision_number)}" ${index === 0 ? "checked" : ""} /><span><strong>版本 ${esc(item.revision_number)} · ${esc(operationLabel(item.operation))}</strong><small>${esc(createdAt)} · ${changed} 项变更</small></span></label>`
    }).join("")
    showModalHtml(
      "地图编辑历史",
      `<p class="map-muted-text">恢复会把画布回到所选版本，并保留当前版本，之后仍可再次恢复。</p><div class="map-archived-list">${rows}</div>`,
      [{
        text: "恢复所选版本",
        class: "btn-primary",
        handler: async () => {
          const selected = document.querySelector('input[name="map-visual-revision"]:checked')?.value
          if (selected == null) {
            toast("请选择要恢复的版本", "warning")
            return false
          }
          try {
            await api.world.restoreMapVisualRevision(
              activeMapId.value,
              Number(selected),
              currentRevision,
              projectId,
            )
            closeModal()
            await reloadCatalog()
            await viewport.value?.remount?.()
            await loadDynamic({ force: true })
            toast(`地图已恢复到版本 ${selected}，当前版本已保留`, "success")
            return true
          } catch (error) {
            if (error?.status === 409) {
              toast("地图已有新版本，请重新打开编辑历史后再恢复", "warning")
            } else {
              toast(`恢复失败：${error.message || "未知错误"}`, "error")
            }
            return false
          }
        },
      }],
      { size: "large" },
    )
    return true
  }

  async function focusInspector(item) {
    focusedDynamicItemId.value = itemId(item)
    if (item.target_entity_id) focusEntityId.value = item.target_entity_id
    await loadDynamic({ force: true })
    viewport.value?.selectInspectorObject?.(item.item_kind, item)
    toast("检查器已在右侧显示", "info")
  }
  async function focusEntityInLens(entityId) {
    if (!entityId || !activeMapId.value) return false
    focusEntityId.value = entityId
    focusedDynamicItemId.value = null
    viewMode.value = "lens"
    await navigateRoute({ focusEntityId: entityId, mode: "lens" }, true)
    if (disposed) return true
    await loadDynamic({ force: true })
    if (owned()) toast("已进入该对象的叙事透镜", "info")
    return owned()
  }
  async function clearLensFocus() {
    if (!activeMapId.value) return false
    focusEntityId.value = null
    focusedDynamicItemId.value = null
    await navigateRoute({ focusEntityId: null, mode: viewMode.value }, true)
    if (disposed) return true
    await loadDynamic({ force: true })
    return owned()
  }
  async function openDynamicItemById(dynamicItemId) {
    const item = activeQueue.value.find(
      (entry) => String(itemId(entry)) === String(dynamicItemId),
    )
    if (item) {
      modalController.showDynamicItem(item)
      return true
    }
    focusedDynamicItemId.value = dynamicItemId || null
    await loadDynamic({ force: true })
    return owned()
  }
  function continuityAnchor(issue, side) {
    const factIds = new Set(issue?.source_fact_ids || [])
    const deltas = (timeline.data?.deltas || []).filter((delta) => (delta.source_fact_ids || []).some((id) => factIds.has(id)))
    const delta = side === "from" ? deltas[0] : deltas.at(-1)
    return (side === "from" ? delta?.spatial_anchor_before : delta?.spatial_anchor_after)
      || (side === "from" ? issue?.suggested_observation?.source_ref?.from_spatial_anchor : issue?.suggested_observation?.spatial_anchor)
      || null
  }
  function continuityFocus(issue, side) {
    const anchor = continuityAnchor(issue, side)
    const paths = issue?.path_ids || []
    const pathId = paths[side === "from" ? 0 : paths.length - 1]
    const focused = (pathId && viewport.value?.focusPath?.(pathId)) || (anchor && viewport.value?.focusTimelineAnchor?.(anchor))
    if (!focused) { toast("该端点尚无可定位的地图锚点", "info"); return false }
    toast(side === "from" ? "已定位移动起点" : "已定位移动终点", "info")
    return true
  }
  function continuityEvidence(issue) {
    const evidence = (issue?.source_fact_ids || []).map((id) => factById.value.get(String(id))).filter(Boolean).map((item) => item.evidence_text || item.source_summary).filter(Boolean)
    const sceneRange = `${mapSceneLabel(issue?.from_scene_index)} → ${mapSceneLabel(issue?.to_scene_index)}`
    showModalHtml("空间连续性证据", `<div class="map-object-info"><div class="map-detail-section"><div class="map-detail-label">检查结果</div><div class="map-detail-value">${esc(issue?.message || "空间连续性待核对")}</div></div><div class="map-detail-section"><div class="map-detail-label">场景</div><div class="map-detail-value">${esc(sceneRange)}</div></div><div class="map-detail-section"><div class="map-detail-label">来源证据</div><div class="map-detail-value">${evidence.length ? evidence.slice(0, 5).map((text) => `<p>${esc(mapSourceText(text))}</p>`).join("") : `已保留 ${esc((issue?.source_fact_ids || []).length)} 条来源事实`}</div></div></div>`, [{ text: "关闭", class: "", handler: closeModal }])
  }
  function continuityExplain(issue) {
    const suggestion = issue?.suggested_observation
    if (!suggestion) return false
    showModalHtml("补充移动解释", `<p>${esc(issue.message || "空间连续性待核对")}</p><div class="form-group"><label>作者解释</label><textarea class="form-textarea" id="map-continuity-explanation" rows="4"></textarea></div><div class="form-group"><label>补充证据（可选）</label><textarea class="form-textarea" id="map-continuity-evidence" rows="3"></textarea></div><p class="map-muted-text">保存后只生成待处理候选，不会直接改写正式世界状态。</p>`, [{
      text: "保存为待处理", class: "btn-primary", handler: async () => {
        const explanation = document.getElementById("map-continuity-explanation")?.value?.trim() || ""
        const evidence = document.getElementById("map-continuity-evidence")?.value?.trim() || ""
        if (!explanation) { toast("请先填写作者解释", "warning"); return false }
        const payload = structuredClone(suggestion)
        payload.review_state = "candidate"
        payload.value_json = { ...(payload.value_json || {}), schema_version: 1, type: "semantic", relation_type: "movement_explanation", summary: explanation }
        payload.evidence_text = evidence || explanation
        try { await api.world.createMapObservation(activeMapId.value, payload, projectId); closeModal(); toast("移动解释已进入待处理，确认后才会成为正式事实", "success"); timeline.includeCandidates = true; await loadDynamic({ force: true }); return true }
        catch (error) { toast(`保存失败：${error.message || "未知错误"}`, "error"); return false }
      },
    }])
    return true
  }
  function onEditingChange(next = {}) {
    editingState.editing = Boolean(next.editing); editingState.dirty = Boolean(next.dirty); editingState.editorLayer = next.editorLayer || "none"
    if (editingState.editing) {
      stopTimeline()
      stopPlayback({ clearFocus: playback.playing })
    }
  }

  const dynamicEditor = useMapDynamicEditor({
    projectId,
    getViewport: () => viewport.value,
    getEntities: () => dynamicEditorEntities.value,
    getLocations: () => locations.value,
    getSpatialContext: () => viewport.value?.spatialContext?.() || null,
    onSaveObservation: saveObservation,
    onFactStatus: updateFact,
  })

  async function openQuickCreatedMap(map) {
    if (disposed || appState?.currentProjectId !== projectId) return false
    const catalogReloaded = await reloadCatalog()
    // A project navigation can replace this island while the catalog request
    // is in flight.  Never let its continuation select or navigate in the
    // successor project.
    if (!catalogReloaded || disposed || appState?.currentProjectId !== projectId) return false
    return openMap(map.id, { viewMode: "live", quickCreateHandoff: true })
  }

  async function consumePendingObservationEditor() {
    const pending = pendingObservationEditors.get(projectId)
    if (!pending || pending.mapId !== activeMapId.value || !dynamicSummary.loaded || !viewport.value) return false
    await loadDynamicEditorEntities()
    if (disposed || appState?.currentProjectId !== projectId || pendingObservationEditors.get(projectId) !== pending) return false
    const item = dynamicSummary.observations.find((entry) => String(itemId(entry)) === String(pending.item.id))
      || { ...pending.item, map_id: pending.mapId }
    pendingObservationEditors.delete(projectId)
    dynamicEditor.open(item)
    return true
  }
  const modalController = createMapModalController({
    projectId,
    getMaps: () => maps.value,
    getArchivedMaps: () => archivedMaps.value,
    getActiveMapId: () => activeMapId.value,
    onCreated: async (map) => { await reloadCatalog(); return openMap(map.id, { viewMode: "live" }) },
    onAssigned: assignObservation,
    onRestored: restoreMap,
    onFactStatus: updateFact,
    onConfirmObservation: confirmObservation,
    onIgnoreObservation: ignoreObservation,
    onConflictObservation: conflictObservation,
    onUnassignObservation: unassignObservation,
    onFocusInspector: focusInspector,
    onEditItem: dynamicEditor.open,
  })
  const quickCreate = useMapQuickCreate({
    projectId,
    onCreated: openQuickCreatedMap,
  })
  const enrichment = useMapEnrichment({
    projectId,
    onDone: async () => {
      await Promise.all([reloadCatalog(), loadInbox()])
      if (activeMapId.value) await loadDynamic({ force: true })
    },
  })

  const viewportContext = computed(() => ({
    projectId, mapId: activeMapId.value, sceneId: activeSceneId.value,
    focusEntityId: focusEntityId.value, focusHexQ: focusHexQ.value, focusHexR: focusHexR.value,
    focusPathId: focusPathId.value, focusLayerNodeId: focusLayerNodeId.value,
    viewMode: viewMode.value, lowMotion: lowMotion.value, mode: "map", layers: { ...layers },
    onMapOpened: (map) => saveRecentMap(projectId, map),
    onEditingChange,
    onOpenMap: async (mapId) => {
      if (!maps.value.some((item) => item.id === mapId)) await reloadCatalog()
      return openMap(mapId, { viewMode: "live" })
    },
    onBackOverview: returnOverview,
    onSceneChange: async (sceneId) => { activeSceneId.value = sceneId || null; await navigateRoute({ sceneId: activeSceneId.value }, true); if (disposed) return true; return loadDynamic({ force: true }) },
    onLayerFocusChange: (id) => { focusLayerNodeId.value = id || null; navigateRoute({ focusLayerNodeId: focusLayerNodeId.value }, true) },
    onOpenEntity: (id) => { appState.selectedItem = id; router?.navigate?.("world", "objects") },
    onFocusEntity: focusEntityInLens,
    onOpenDynamicItem: openDynamicItemById,
  }))

  async function initializeRoute() {
    if (mode.value === "map" && activeMapId.value) return loadDynamic({ force: true })
    if (route.mode === "recent" || (route.mode !== "overview" && (route.sceneId || route.focusEntityId))) return openRecent()
    return true
  }

  useLeaveGuard(() => viewport.value?.canLeave?.() !== false)
  const beforeUnload = (event) => { if (!editingState.dirty) return; event.preventDefault(); event.returnValue = "" }
  onMounted(() => {
    window.addEventListener("beforeunload", beforeUnload)
    const rememberedMap = readRecentMap(projectId)
    if (rememberedMap?.mapId && !maps.value.some((item) => item.id === rememberedMap.mapId)) {
      clearRecentMap(projectId)
      recentRevision.value += 1
    }
    enrichment.recover()
    void initializeRoute()
  })
  onBeforeUnmount(() => {
    disposed = true; dynamicGeneration.value += 1; timelineGeneration.value += 1
    window.removeEventListener("beforeunload", beforeUnload); stopTimeline(); stopPlayback(); modalController.dispose(); quickCreate.close(); dynamicEditor.close(); enrichment.dispose()
  })

  return {
    activeMap, activeMapId, activeQueue, activeSceneId, activeSceneLabel, archiveMap, archivedPage, archivedPageCount,
    archivedMaps, batchReview, confirmObservation, currentTimelineScene, dashboardQueue,
    clearLensFocus, consumePendingObservationEditor, continuityEvidence, continuityExplain, continuityFocus, currentLiveFacts, dynamicEditor, dynamicSummary, editingState, enrichment, factById, focusEntityId, focusEntityInLens, historyQueue, ignoreInbox, ignoreObservation,
    inbox, inboxItems, layers, lensContextItems, lensFocusableItems, lensHasFocus, loadDynamic, loadInbox, locations, lowMotion, mapByParent,
    maps, message, modalController, mode, openLocation, openMap, openRecent, playback,
    projectId, quickCreate, recentMap, reloadCatalog, returnOverview, searchQuery, searchResults,
    setLayer, setLowMotion, setTimelineCandidates, setTimelinePosition, setTimelineTrack,
    setViewMode, showArchived, showHistory, showVisualHistory, startPlayback, startTimeline, stepTimeline,
    stopPlayback, stopTimeline, timeline, timelineProjection, toggleHistory, updateFact,
    viewMode, viewport, viewportContext, visibleArchivedMaps,
  }
}
