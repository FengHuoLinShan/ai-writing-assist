import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  shallowRef,
} from "vue"
import {
  getApi,
  getAppState,
  getCloseModal,
  getEsc,
  getRouter,
  getShowModalHtml,
  getToast,
} from "../../bridge/index.js"
import { confirmAsync } from "../../../shared/confirmAsync.js"
import {
  importAuthorizationNotice,
  importAuthorizationPayload,
} from "../../../shared/importAuthorization.js"
import { structureAssetDisplay } from "../../../shared/assetDisplayState.js"
import { sceneAutoExtractManager } from "./sceneAutoExtractManager.js"
import { createSceneModalController } from "./sceneModalController.js"
import {
  HEALTH_ORDER,
  SCENE_FILTER_DEFAULTS,
  filteredSceneItems,
  healthReasons,
  rememberSceneMode,
  sceneContextAction,
  sceneQuery,
  sceneReviewState,
  sceneSession,
  sceneWorkbenchParams,
} from "./sceneModel.js"

function currentHashQuery() {
  if (typeof window === "undefined") return sceneQuery()
  const index = window.location.hash.indexOf("?")
  return new URLSearchParams(index >= 0 ? window.location.hash.slice(index + 1) : "")
}

function commitSceneHash(projectId, query, mode = "replace") {
  if (typeof window === "undefined" || !window.history) return
  const base = `#workbench/${encodeURIComponent(projectId)}/outline/scenes`
  const hash = query.toString() ? `${base}?${query.toString()}` : base
  const method = mode === "push" ? "pushState" : "replaceState"
  window.history[method]({ view: "outline", subView: "scenes", projectId }, "", hash)
}

export function useSceneWorkbench(props) {
  const api = getApi()
  const router = getRouter()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const esc = getEsc()
  const projectId = props.projectId
  const session = sceneSession(projectId)

  const workbench = shallowRef(props.workbench || null)
  const fusionSuggestions = shallowRef([...(props.fusionSuggestions || [])])
  const viewMode = ref(props.viewMode || "hot")
  const selectedSceneId = ref(props.selectedSceneId || null)
  const filters = reactive({ ...SCENE_FILTER_DEFAULTS, ...(props.sceneFilters || {}) })
  const filterForm = reactive({ ...filters })
  const activeHealth = ref(props.activeHealth || null)
  const advancedFiltersOpen = ref(Boolean(props.advancedFiltersOpen))
  const selectedIds = shallowRef(new Set())
  const mobileDetailOpen = ref(Boolean(selectedSceneId.value))
  const narrow = ref(typeof window !== "undefined" && window.innerWidth < 720)
  const loading = ref(false)
  const loadError = ref(props.sceneLoadError || null)
  const requestGeneration = ref(0)
  let disposed = false

  const total = computed(() => Number(workbench.value?.total ?? workbench.value?.items?.length ?? 0) || 0)
  const items = computed(() => filteredSceneItems(workbench.value, filters))
  const selectedItem = computed(() => items.value.find((item) => item.scene?.id === selectedSceneId.value) || null)
  const visibleIds = computed(() => items.value.map((item) => item.scene?.id).filter(Boolean))
  const allVisibleSelected = computed(() => visibleIds.value.length > 0 && visibleIds.value.every((id) => selectedIds.value.has(id)))
  const selectedItems = computed(() => Array.from(selectedIds.value).map((id) => workbench.value?.items?.find((item) => item.scene?.id === id)).filter(Boolean))
  const pendingSuggestionCount = computed(() => Number(workbench.value?.fusion_suggestions?.pending_count || fusionSuggestions.value.length || 0))
  const dismissibleSuggestionCount = computed(() => fusionSuggestions.value.filter((item) => item.suggestion_kind !== "replacement").length)
  const autoExtractionBusy = computed(() => (
    sceneAutoExtractManager.state.submitting
    || Boolean(
      sceneAutoExtractManager.state.taskId
      && sceneAutoExtractManager.state.progress
      && !sceneAutoExtractManager.state.progress.terminal
    )
  ))

  function owned(generation = requestGeneration.value) {
    const state = getAppState()
    return !disposed
      && generation === requestGeneration.value
      && state?.currentProjectId === projectId
      && state?.currentView === "outline"
      && state?.currentSubView === "scenes"
  }

  function syncSession() {
    session.filters = { ...filters }
    session.activeHealth = activeHealth.value
    session.advancedFiltersOpen = advancedFiltersOpen.value
  }

  async function loadSuggestions(pending) {
    if (!(pending > 0) || !api.outline.listFusionSuggestions) return []
    const result = []
    let skip = 0
    let totalCount = pending
    while (skip < totalCount) {
      const response = await api.outline.listFusionSuggestions(projectId, { skip, limit: 50 })
      const batch = Array.isArray(response?.items) ? response.items : []
      result.push(...batch)
      totalCount = Number(response?.total ?? totalCount) || 0
      if (!batch.length) break
      skip += batch.length
    }
    return result
  }

  async function refresh({ preserveSelection = true } = {}) {
    const generation = ++requestGeneration.value
    loading.value = true
    loadError.value = null
    const routeSelection = preserveSelection ? selectedSceneId.value : null
    try {
      const next = await api.outline.getSceneWorkbench(
        projectId,
        routeSelection,
        sceneWorkbenchParams({ filters, viewMode: viewMode.value, selectedSceneId: routeSelection }),
      )
      if (!owned(generation)) return false
      workbench.value = next
      const effectiveSkip = Number(next?.skip)
      if (Number.isInteger(effectiveSkip) && effectiveSkip >= 0) filters.skip = effectiveSkip
      fusionSuggestions.value = await loadSuggestions(Number(next?.fusion_suggestions?.pending_count || 0))
      if (!owned(generation)) return false
      if (selectedSceneId.value && !next?.items?.some((item) => item.scene?.id === selectedSceneId.value)) {
        const nextSelected = next?.selected_scene_id || null
        if (nextSelected && next?.items?.some((item) => item.scene?.id === nextSelected)) {
          selectScene(nextSelected, "replace")
        } else {
          clearSelectedScene()
        }
      }
      syncSession()
      return true
    } catch (err) {
      if (!owned(generation)) return false
      if (routeSelection && err?.status === 404 && err?.detail === "Scene not found") {
        clearSelectedScene()
        return refresh({ preserveSelection: false })
      }
      loadError.value = err.message || "场景工作台加载失败"
      toast(loadError.value, "error")
      return false
    } finally {
      if (owned(generation)) loading.value = false
    }
  }

  function clearSelectedScene() {
    selectedSceneId.value = null
    mobileDetailOpen.value = false
    const query = currentHashQuery()
    query.delete("scene_id")
    commitSceneHash(projectId, query, "replace")
  }

  function selectScene(sceneId, historyMode = "push") {
    if (!sceneId || !workbench.value?.items?.some((item) => item.scene?.id === sceneId)) return false
    selectedSceneId.value = sceneId
    mobileDetailOpen.value = true
    const query = currentHashQuery()
    query.set("mode", viewMode.value)
    query.set("scene_id", sceneId)
    commitSceneHash(projectId, query, historyMode)
    return true
  }

  function clearSelection() {
    selectedIds.value = new Set()
  }

  function toggleSelection(sceneId, checked) {
    const next = new Set(selectedIds.value)
    if (checked) next.add(sceneId)
    else next.delete(sceneId)
    selectedIds.value = next
  }

  function toggleVisibleSelection() {
    const next = new Set(selectedIds.value)
    if (allVisibleSelected.value) visibleIds.value.forEach((id) => next.delete(id))
    else visibleIds.value.forEach((id) => next.add(id))
    selectedIds.value = next
  }

  const modalController = createSceneModalController({
    projectId,
    getItems: () => workbench.value?.items || [],
    getSuggestions: () => fusionSuggestions.value,
    refresh,
    selectScene,
    clearSelection,
  })

  async function applyFilters() {
    Object.assign(filters, SCENE_FILTER_DEFAULTS, filterForm, {
      health: filters.health || activeHealth.value || "",
      segment: filters.segment,
      skip: 0,
    })
    activeHealth.value = filters.health || null
    clearSelection()
    clearSelectedScene()
    syncSession()
    await refresh({ preserveSelection: false })
  }

  async function resetFilters() {
    Object.assign(filters, SCENE_FILTER_DEFAULTS)
    Object.assign(filterForm, SCENE_FILTER_DEFAULTS)
    activeHealth.value = null
    advancedFiltersOpen.value = false
    clearSelection()
    clearSelectedScene()
    syncSession()
    await refresh({ preserveSelection: false })
  }

  async function toggleHealth(health) {
    filters.health = filters.health === health ? "" : health
    filterForm.health = filters.health
    filters.skip = 0
    activeHealth.value = filters.health || null
    clearSelection()
    clearSelectedScene()
    syncSession()
    await refresh({ preserveSelection: false })
  }

  async function toggleSegment(segment) {
    if (viewMode.value !== "hot") return
    filters.segment = filters.segment === segment ? "" : segment
    filters.skip = 0
    clearSelection()
    clearSelectedScene()
    syncSession()
    await refresh({ preserveSelection: false })
  }

  async function setViewMode(mode) {
    if (!["normal", "hot"].includes(mode) || mode === viewMode.value) return
    viewMode.value = mode
    rememberSceneMode(projectId, mode)
    filters.segment = ""
    filters.skip = 0
    clearSelection()
    clearSelectedScene()
    syncSession()
    const query = new URLSearchParams()
    query.set("mode", mode)
    await router.navigate("outline", "scenes", true, query)
  }

  async function changePage(delta) {
    const next = Number(filters.skip || 0) + delta * Number(filters.limit || 20)
    if (next < 0 || next >= total.value) return
    filters.skip = next
    clearSelection()
    clearSelectedScene()
    syncSession()
    await refresh({ preserveSelection: false })
  }

  function toggleAdvanced() {
    advancedFiltersOpen.value = !advancedFiltersOpen.value
    syncSession()
  }

  function healthLabel(key) {
    return workbench.value?.health?.[key]?.label || HEALTH_ORDER.find(([item]) => item === key)?.[1] || key
  }

  async function reviewScenes(sceneIds, decision = "review") {
    if (!sceneIds.length) {
      toast("请先选择要处理的 Scene", "warning")
      return false
    }
    try {
      await api.outline.reviewSceneWorkbench(projectId, { scene_ids: sceneIds, decision })
      clearSelection()
      toast(decision === "review" ? `已处理 ${sceneIds.length} 个 Scene` : `已将 ${sceneIds.length} 个 Scene 标记为需要人工检查`, "success")
      await refresh()
      return true
    } catch (err) {
      toast(err.message || "Scene 复核失败", "error")
      return false
    }
  }

  async function runContextAction(item, action = sceneContextAction(item)) {
    const sceneId = item?.scene?.id
    if (!sceneId) return
    if (action.key === "review") return reviewScenes([sceneId])
    if (action.key === "suggestion") return modalController.showSuggestions(action.suggestionId)
    if (action.key === "source_mapping") return modalController.confirmSourceMapping(sceneId, action.fingerprint)
    if (action.key === "organize") return modalController.organizeMapping(sceneId, workbench.value?.unassigned_chapters || [])
    if (action.key === "assign") return modalController.showAssignChapters(sceneId, workbench.value?.unassigned_chapters || [])
    if (action.key === "missing_setup") {
      selectScene(sceneId)
      await nextTick()
      const fieldMap = [
        ["goal", "scene-detail-goal"],
        ["core_conflict", "scene-detail-conflict"],
        ["must_happen", "scene-detail-must"],
        ["must_not_happen", "scene-detail-must-not"],
      ]
      const target = fieldMap.find(([field]) => !item.scene?.[field])
      if (target) document.getElementById(target[1])?.focus()
      return
    }
    selectScene(sceneId)
  }

  async function runSelectedContextActions() {
    if (!selectedItems.value.length) {
      toast("请先选择要处理的 Scene", "warning")
      return
    }
    const actions = selectedItems.value.map((item) => sceneContextAction(item))
    if (actions.every((item) => item.key === "review")) return reviewScenes(selectedItems.value.map((item) => item.scene.id))
    if (actions.every((item) => item.key === "source_mapping")) {
      const requests = selectedItems.value.map((item, index) => ({ scene_id: item.scene.id, expected_fingerprint: actions[index].fingerprint })).filter((item) => item.expected_fingerprint)
      if (!requests.length) return
      showModalHtml("批量确认章节级定位", `<p>将确认 ${esc(requests.length)} 个 Scene 只保留章节级定位。</p>`, [
        { text: "取消", class: "", handler: closeModal },
        { text: "确认定位", class: "btn-primary", handler: async () => {
          await api.outline.reviewSceneSourceMappings(projectId, { items: requests, decision: "accept_chapter_only", confirmed: true })
          closeModal(); clearSelection(); await refresh(); return true
        } },
      ])
      return
    }
    showModalHtml("批量处理", "<p>选中的 Scene 包含不同待办类型，请分组处理或缩小选择范围。</p>", [{ text: "关闭", class: "", handler: closeModal }])
  }

  async function saveScene(sceneId, draft) {
    try {
      await api.outline.updateScene(sceneId, projectId, {
        title: draft.title?.trim() || null,
        narrative_tag: draft.narrative_tag || "draft",
        status: draft.status || "draft",
        source: draft.source || "manual",
        goal: draft.goal?.trim() || null,
        core_conflict: draft.core_conflict?.trim() || null,
        emotional_beat: draft.emotional_beat?.trim() || null,
        must_happen: draft.must_happen?.trim() || null,
        must_not_happen: draft.must_not_happen?.trim() || null,
        pov_character_id: draft.pov_character_id?.trim() || null,
      })
      toast("Scene 已保存", "success")
      await refresh()
      return true
    } catch (err) {
      toast(err.message || "保存 Scene 失败", "error")
      return false
    }
  }

  async function moveToHistory(sceneId) {
    const scene = workbench.value?.items?.find((item) => item.scene?.id === sceneId)?.scene
    if (!scene || structureAssetDisplay(scene).isHistory) return false
    const confirmed = await confirmAsync(`确认将“${scene.title || "未命名 Scene"}”移入历史？Scene 正文和追踪信息会保留，可通过“状态 → 历史”查看。`, "确认移入历史")
    if (!confirmed) return false
    try {
      await api.outline.deleteScene(sceneId, projectId)
      const next = new Set(selectedIds.value); next.delete(sceneId); selectedIds.value = next
      if (selectedSceneId.value === sceneId) clearSelectedScene()
      toast("Scene 已移入历史", "success")
      await refresh({ preserveSelection: false })
      return true
    } catch (err) {
      toast(`移入历史失败：${err.message || "未知错误"}`, "error")
      return false
    }
  }

  function openWriting(scene) {
    const first = (scene?.chapter_ids || []).find((id) => /^\d+$/.test(String(id)))
    const state = getAppState()
    if (first && state) {
      state.viewStates = state.viewStates || {}
      state.viewStates.writing = { ...(state.viewStates.writing || {}), projectId, currentChapter: Number(first) }
    }
    router.navigate("writing", null)
  }

  async function openOverlap(sceneId) {
    if (!sceneId) return false
    if (workbench.value?.items?.some((item) => item.scene?.id === sceneId)) return selectScene(sceneId)
    Object.assign(filters, SCENE_FILTER_DEFAULTS)
    Object.assign(filterForm, SCENE_FILTER_DEFAULTS)
    activeHealth.value = null
    clearSelection()
    selectedSceneId.value = sceneId
    const query = currentHashQuery(); query.set("mode", viewMode.value); query.set("scene_id", sceneId)
    commitSceneHash(projectId, query, "push")
    syncSession()
    return refresh()
  }

  function showAutoExtractForm() {
    if (autoExtractionBusy.value) {
      toast("正文 Scene 提取任务正在处理", "info")
      return
    }
    showModalHtml("从正文提取 Scene", `
      <div class="form-group"><label>起始章节</label><input class="form-input" id="scene-auto-extract-start" type="number" min="1" value="1" /></div>
      <div class="form-group"><label>结束章节</label><input class="form-input" id="scene-auto-extract-end" type="number" min="1" value="10" /></div>
      <label class="scene-quality-option"><input id="scene-auto-extract-high-quality" type="checkbox" />更高质量 <span class="scene-quality-option__hint">最大推理 + Phase 1c 融合，约需 2 倍时间</span></label>
      <p class="writing-form-hint" role="note">${esc(importAuthorizationNotice())}</p>`, [{
      text: "确认并开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = Number(document.getElementById("scene-auto-extract-start")?.value || 1)
        const end = Number(document.getElementById("scene-auto-extract-end")?.value || 10)
        const highQuality = Boolean(document.getElementById("scene-auto-extract-high-quality")?.checked)
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return false }
        return submitAutoExtraction(start, end, highQuality)
      },
    }])
  }

  async function submitAutoExtraction(
    start,
    end,
    highQuality = false,
    ownerGeneration = requestGeneration.value,
  ) {
    if (!owned(ownerGeneration)) return false
    const submission = sceneAutoExtractManager.beginSubmission(projectId)
    if (!submission) {
      toast("正文 Scene 提取任务正在处理", "info")
      return false
    }
    try {
      return await submitAutoExtractionAttempt(start, end, highQuality, false, ownerGeneration)
    } finally {
      sceneAutoExtractManager.endSubmission(submission)
    }
  }

  async function submitAutoExtractionAttempt(
    start,
    end,
    highQuality,
    force,
    ownerGeneration,
  ) {
    try {
      const result = await api.imports.startStage("scenes", projectId, start, end, force, highQuality, importAuthorizationPayload())
      if (!owned(ownerGeneration)) return false
      if (result?.requires_confirmation) {
        const confirmed = await confirmAsync(result.warning, "确认覆盖")
        if (!owned(ownerGeneration)) return false
        if (!confirmed) return false
        return submitAutoExtractionAttempt(start, end, highQuality, true, ownerGeneration)
      }
      if (!result?.task_id) {
        closeModal(); toast(result?.message || "从正文提取 Scene 未启动", "warning"); return false
      }
      sceneAutoExtractManager.adopt(result, { start_chapter: start, end_chapter: end, highQuality }, projectId)
      closeModal()
      toast(`从正文提取 Scene 任务已提交：${result.task_id}`, "success")
      return true
    } catch (err) {
      if (owned(ownerGeneration)) toast(err.message || "提交失败", "error")
      return false
    }
  }

  async function cancelAutoExtraction() {
    const confirmed = await confirmAsync("确认取消当前正文 Scene 提取任务？已完成的阶段结果不会自动删除。", "确认取消")
    if (!confirmed) return false
    try {
      await sceneAutoExtractManager.cancel(projectId)
      toast("当前正文 Scene 提取任务已取消", "warning")
      return true
    } catch (err) {
      toast(err.message || "取消任务失败", "error")
      return false
    }
  }

  function dismissAutoExtraction() {
    sceneAutoExtractManager.dismiss(projectId)
  }

  function onResize() {
    narrow.value = window.innerWidth < 720
  }

  const offTerminal = sceneAutoExtractManager.subscribeTerminal(async (progress) => {
    if (owned() && progress.done) await refresh()
  })

  onMounted(() => {
    sceneAutoExtractManager.recover(projectId)
    window.addEventListener("resize", onResize)
    document.querySelector(".outline-scene-layout > .subnav")?.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
  })

  onBeforeUnmount(() => {
    disposed = true
    requestGeneration.value += 1
    offTerminal()
    sceneAutoExtractManager.stop()
    modalController.dispose()
    window.removeEventListener("resize", onResize)
  })

  return {
    activeHealth,
    advancedFiltersOpen,
    allVisibleSelected,
    autoExtractionBusy,
    applyFilters,
    cancelAutoExtraction,
    changePage,
    clearSelectedScene,
    dismissAutoExtraction,
    dismissibleSuggestionCount,
    filterForm,
    filters,
    fusionSuggestions,
    healthLabel,
    healthReasons,
    items,
    loadError,
    loading,
    mobileDetailOpen,
    modalController,
    moveToHistory,
    narrow,
    openOverlap,
    openWriting,
    pendingSuggestionCount,
    refresh,
    resetFilters,
    reviewScenes,
    runContextAction,
    runSelectedContextActions,
    saveScene,
    sceneContextAction,
    sceneReviewState,
    selectScene,
    selectedIds,
    selectedItem,
    selectedItems,
    setViewMode,
    showAutoExtractForm,
    toggleAdvanced,
    toggleHealth,
    toggleSegment,
    toggleSelection,
    toggleVisibleSelection,
    total,
    viewMode,
    visibleIds,
    workbench,
  }
}
