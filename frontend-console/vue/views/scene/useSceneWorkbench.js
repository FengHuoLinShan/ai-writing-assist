import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  shallowRef,
  watch,
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
  commitSceneRouteQuery,
  filteredSceneItems,
  healthReasons,
  persistSceneSession,
  rememberSceneMode,
  sceneContextAction,
  sceneQuery,
  sceneReviewState,
  sceneSession,
  sceneWorkbenchParams,
} from "./sceneModel.js"

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
  const filterForm = reactive({ ...filters, ...(session.filterDraft || {}) })
  const activeHealth = ref(props.activeHealth || null)
  const advancedFiltersOpen = ref(Boolean(props.advancedFiltersOpen))
  const selectedIds = shallowRef(new Set())
  const mobileDetailOpen = ref(Boolean(selectedSceneId.value))
  const narrow = ref(typeof window !== "undefined" && window.innerWidth <= 760)
  const loading = ref(false)
  const loadError = ref(props.sceneLoadError || null)
  const savingSceneId = ref(null)
  const sceneSaveError = ref(null)
  const fusionTask = reactive({ taskId: null, meta: null, progress: null, preview: null })
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
    session.filterDraft = { ...filterForm }
    session.activeHealth = activeHealth.value
    session.advancedFiltersOpen = advancedFiltersOpen.value
    persistSceneSession(projectId, session)
  }
  watch(filterForm, syncSession, { deep: true, flush: "sync" })

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
    sceneSaveError.value = null
    const query = sceneQuery()
    query.delete("scene_id")
    commitSceneRouteQuery(projectId, query)
  }

  function selectScene(sceneId, historyMode = "push") {
    if (!sceneId || !workbench.value?.items?.some((item) => item.scene?.id === sceneId)) return false
    if (selectedSceneId.value !== sceneId) sceneSaveError.value = null
    selectedSceneId.value = sceneId
    mobileDetailOpen.value = true
    const query = sceneQuery()
    query.set("mode", viewMode.value)
    query.set("scene_id", sceneId)
    commitSceneRouteQuery(projectId, query, historyMode)
    return true
  }

  function clearSelection() {
    selectedIds.value = new Set()
  }

  function removeSelection(sceneIds) {
    const next = new Set(selectedIds.value)
    sceneIds.forEach((id) => next.delete(id))
    selectedIds.value = next
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
    removeSelection,
    ignoreStructure: (sceneIds) => reviewScenes(sceneIds, "ignore_structure"),
    fusionTask,
  })

  async function applyFilters() {
    Object.assign(filters, SCENE_FILTER_DEFAULTS, filterForm, {
      health: filters.health || activeHealth.value || "",
      segment: filters.segment,
      skip: 0,
    })
    activeHealth.value = filters.health || null
    Object.assign(filterForm, filters)
    clearSelection()
    clearSelectedScene()
    syncSession()
    return refresh({ preserveSelection: false })
  }

  async function resetFilters() {
    Object.assign(filters, SCENE_FILTER_DEFAULTS)
    Object.assign(filterForm, SCENE_FILTER_DEFAULTS)
    activeHealth.value = null
    advancedFiltersOpen.value = false
    clearSelection()
    clearSelectedScene()
    syncSession()
    return refresh({ preserveSelection: false })
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
    filterForm.segment = filters.segment
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
    filterForm.segment = ""
    filters.skip = 0
    clearSelection()
    clearSelectedScene()
    syncSession()
    const query = sceneQuery()
    query.set("mode", mode)
    query.delete("scene_id")
    commitSceneRouteQuery(projectId, query, "push")
    await refresh({ preserveSelection: false })
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
      toast("请先选择要处理的场景", "warning")
      return false
    }
    try {
      await api.outline.reviewSceneWorkbench(projectId, { scene_ids: sceneIds, decision })
      removeSelection(sceneIds)
      const messages = {
        review: `已处理 ${sceneIds.length} 个场景`,
        reopen: `已将 ${sceneIds.length} 个场景标记为需要人工检查`,
        ignore_structure: "已标记为无需整理，可从场景更多菜单恢复",
        restore_structure: "已恢复整理提醒",
      }
      toast(messages[decision] || "场景检查已更新", "success")
      await refresh()
      return true
    } catch (err) {
      toast(err.message || "场景检查失败", "error")
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
      await nextTick()
      const fieldMap = [
        ["goal", "scene-detail-goal"],
        ["core_conflict", "scene-detail-core_conflict"],
        ["must_happen", "scene-detail-must_happen"],
        ["must_not_happen", "scene-detail-must_not_happen"],
      ]
      const target = fieldMap.find(([field]) => !item.scene?.[field])
      if (target) document.getElementById(target[1])?.focus()
      return
    }
    selectScene(sceneId)
  }

  async function runSelectedContextActions() {
    if (!selectedItems.value.length) {
      toast("请先选择要处理的场景", "warning")
      return
    }
    const groups = new Map()
    selectedItems.value.forEach((item) => {
      const action = sceneContextAction(item)
      if (!groups.has(action.key)) groups.set(action.key, [])
      groups.get(action.key).push({ item, action })
    })
    if (selectedItems.value.length === 1) return runContextAction(selectedItems.value[0])
    if (groups.size === 1) return runActionGroup(groups.values().next().value)

    const entries = Array.from(groups.values())
    showModalHtml("按待办类型处理", `<p>已按当前主要待办分组，每次处理一组；其他选中项会保留。</p><ul>${entries.map((group) => `<li><strong>${esc(actionGroupLabel(group[0].action.key))}</strong>：${esc(group.length)} 个</li>`).join("")}</ul>`, [
      { text: "关闭", class: "", handler: closeModal },
      ...entries.map((group) => ({
        text: `${actionGroupLabel(group[0].action.key)}（${group.length}）`,
        class: "btn-primary",
        handler: () => { closeModal(); return runActionGroup(group) },
      })),
    ])
  }

  function actionGroupLabel(key) {
    return {
      review: "采用 / 标记已检查",
      source_mapping: "确认章节定位",
      organize: "整理映射",
      suggestion: "逐项处理融合建议",
      assign: "逐项关联章节",
      missing_setup: "逐项补全设定",
      edit: "逐项编辑",
    }[key] || "处理"
  }

  function confirmSourceMappingGroup(group) {
    const requests = group.map(({ item, action }) => ({ scene_id: item.scene.id, expected_fingerprint: action.fingerprint })).filter((item) => item.expected_fingerprint)
    if (!requests.length) return false
    showModalHtml("批量确认章节级定位", `<p>将确认 ${esc(requests.length)} 个场景只保留章节级定位。</p>`, [
      { text: "取消", class: "", handler: closeModal },
      { text: "确认定位", class: "btn-primary", handler: async () => {
        try {
          await api.outline.reviewSceneSourceMappings(projectId, { items: requests, decision: "accept_chapter_only", confirmed: true })
          closeModal()
          removeSelection(requests.map((item) => item.scene_id))
          toast(`已确认 ${requests.length} 个场景的章节定位`, "success")
          await refresh()
          return true
        } catch (err) {
          toast(err.message || "正文定位确认失败", "error")
          return false
        }
      } },
    ])
    return true
  }

  function organizeGroup(group) {
    const sceneIds = group.map(({ item }) => item.scene.id)
    showModalHtml("批量整理场景", `<p>已选 ${esc(sceneIds.length)} 个结构待整理场景。可从第一项开始逐项整理，或将这一组标记为无需整理。</p>`, [
      { text: "取消", class: "", handler: closeModal },
      { text: "逐项整理", class: "", handler: () => { closeModal(); return runContextAction(group[0].item, group[0].action) } },
      { text: "标记选中项无需整理", class: "btn-primary", handler: async () => {
        const updated = await reviewScenes(sceneIds, "ignore_structure")
        if (updated) closeModal()
        return updated
      } },
    ])
    return true
  }

  function runActionGroup(group) {
    const key = group[0]?.action?.key
    if (key === "review") return reviewScenes(group.map(({ item }) => item.scene.id))
    if (key === "source_mapping") return confirmSourceMappingGroup(group)
    if (key === "organize") return organizeGroup(group)
    return runContextAction(group[0].item, group[0].action)
  }

  async function saveScene(sceneId, draft) {
    if (!sceneId || savingSceneId.value) return false
    savingSceneId.value = sceneId
    sceneSaveError.value = null
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
      if (!owned()) return false
      removeSelection([sceneId])
      toast("场景已保存", "success")
      await refresh()
      return true
    } catch (err) {
      if (!owned()) return false
      sceneSaveError.value = err.message || "保存场景失败"
      toast(sceneSaveError.value, "error")
      return false
    } finally {
      if (savingSceneId.value === sceneId) savingSceneId.value = null
    }
  }

  async function moveToHistory(sceneId) {
    const scene = workbench.value?.items?.find((item) => item.scene?.id === sceneId)?.scene
    if (!scene || structureAssetDisplay(scene).isHistory) return false
    const confirmed = await confirmAsync(`确认将“${scene.title || "未命名场景"}”移入历史？场景正文和追踪信息会保留，可通过“状态 → 历史”查看。`, "确认移入历史")
    if (!confirmed) return false
    try {
      await api.outline.deleteScene(sceneId, projectId)
      const next = new Set(selectedIds.value); next.delete(sceneId); selectedIds.value = next
      if (selectedSceneId.value === sceneId) clearSelectedScene()
      toast("场景已移入历史", "success")
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
    const query = new URLSearchParams()
    if (first) query.set("chapter_index", String(first))
    if (scene?.id) query.set("scene_id", String(scene.id))
    router.navigate("writing", null, true, query)
  }

  async function openOverlap(sceneId) {
    if (!sceneId) return false
    if (workbench.value?.items?.some((item) => item.scene?.id === sceneId)) return selectScene(sceneId)
    Object.assign(filters, SCENE_FILTER_DEFAULTS)
    Object.assign(filterForm, SCENE_FILTER_DEFAULTS)
    activeHealth.value = null
    clearSelection()
    selectedSceneId.value = sceneId
    const query = sceneQuery(); query.set("mode", viewMode.value); query.set("scene_id", sceneId)
    commitSceneRouteQuery(projectId, query, "push")
    syncSession()
    return refresh()
  }

  function showAutoExtractForm() {
    if (autoExtractionBusy.value) {
      toast("正文场景整理正在进行", "info")
      return
    }
    showModalHtml("从正文整理场景", `
      <div class="form-group"><label>起始章节</label><input class="form-input" id="scene-auto-extract-start" type="number" min="1" value="1" /></div>
      <div class="form-group"><label>结束章节</label><input class="form-input" id="scene-auto-extract-end" type="number" min="1" value="10" /></div>
      <label class="scene-quality-option"><input id="scene-auto-extract-high-quality" type="checkbox" />更高质量 <span class="scene-quality-option__hint">增加推理与融合步骤，约需 2 倍时间</span></label>
      <p class="writing-form-hint" role="note">${esc(importAuthorizationNotice())}</p>`, [{
      text: "确认并开始整理",
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
      toast("正文场景整理正在进行", "info")
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
        const warning = String(result.warning || "已有场景资料，确认覆盖才会继续。").replace(/\s*\bScene\b/g, "场景")
        const confirmed = await confirmAsync(warning, "确认覆盖")
        if (!owned(ownerGeneration)) return false
        if (!confirmed) return false
        return submitAutoExtractionAttempt(start, end, highQuality, true, ownerGeneration)
      }
      if (!result?.task_id) {
        closeModal(); toast(result?.message || "正文场景整理未能开始", "warning"); return false
      }
      sceneAutoExtractManager.adopt(result, { start_chapter: start, end_chapter: end, highQuality }, projectId)
      closeModal()
      toast("已开始从正文整理场景", "success")
      return true
    } catch (err) {
      if (owned(ownerGeneration)) toast(err.message || "提交失败", "error")
      return false
    }
  }

  async function cancelAutoExtraction() {
    const confirmed = await confirmAsync("确认取消当前正文场景整理？已完成的阶段结果不会自动删除。", "确认取消")
    if (!confirmed) return false
    try {
      await sceneAutoExtractManager.cancel(projectId)
      toast("当前正文场景整理已取消", "warning")
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
    narrow.value = window.innerWidth <= 760
  }

  const offTerminal = sceneAutoExtractManager.subscribeTerminal(async (progress) => {
    if (owned() && progress.done) await refresh()
  })

  onMounted(() => {
    sceneAutoExtractManager.recover(projectId)
    modalController.recoverFusionTask()
    if (
      props.focusedSuggestionId
      && fusionSuggestions.value.some((item) => item.id === props.focusedSuggestionId)
    ) {
      modalController.showSuggestions(props.focusedSuggestionId)
    }
    window.addEventListener("resize", onResize)
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
    clearSelection,
    dismissAutoExtraction,
    dismissibleSuggestionCount,
    filterForm,
    filters,
    fusionSuggestions,
    fusionTask,
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
    savingSceneId,
    sceneSaveError,
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
