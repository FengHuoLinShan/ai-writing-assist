import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue"
import {
  getApi,
  getAppState,
  getConfirm,
  getConfirmAction,
  getRouter,
  getToast,
} from "../../bridge/index.js"
import { useLeaveGuard } from "../../composables/useLeaveGuard.js"
import { findCurrentScene } from "../../../shared/sceneLocator.js"
import { buildSceneAlerts } from "../../../views/writing/sceneAlerts.js"
import { buildVersionDiff } from "../../../views/writing/versionDiff.js"
import { buildMapUrl } from "../../../views/mapRouteContext.js"
import { applyToolsResult } from "../../../shared/writingToolsResult.js"
import { importAuthorizationPayload } from "../../../shared/importAuthorization.js"
import { sanitizeTaskErrorMessage } from "../../../shared/workflowProgress.js"
import { confirmAsync } from "../../../shared/confirmAsync.js"
import { createEditorController, substantiveWritingText } from "./controllers/editorController.js"
import { createWritingCommandController } from "./controllers/writingCommandController.js"
import { createDeepImportController } from "./controllers/deepImportController.js"
import { createConflictController } from "./controllers/conflictController.js"
import { openWritingMapQuickCreate } from "./controllers/mapQuickCreateBridge.js"
import { getWritingSession, rememberWritingLocation } from "./writingSession.js"

function normalizeChapters(data = {}) {
  const summaries = Array.isArray(data.chapters) ? data.chapters : []
  const indices = summaries.length
    ? summaries.map((item) => Number(item.chapter_index)).filter(Number.isInteger)
    : (data.chapter_indices || []).map(Number).filter(Number.isInteger)
  const chapters = {}
  for (const item of summaries) {
    chapters[item.chapter_index] = {
      ...item,
      title: item.title || "",
      word_count: Number(item.word_count || 0),
    }
  }
  for (const index of indices) {
    if (!chapters[index]) chapters[index] = { chapter_index: index, title: "", word_count: 0, status: "draft" }
  }
  return { chapterList: [...new Set(indices)].sort((a, b) => a - b), chapters }
}

export async function loadWritingProps() {
  const api = getApi()
  const state = getAppState()
  const router = getRouter()
  const projectId = state?.currentProjectId || null
  const query = new URLSearchParams(router?.getCurrentQuery?.()?.toString() || "")
  const result = {
    projectId,
    chapterList: [],
    chapters: {},
    scenes: [],
    chapterLoadError: null,
    authorPreferences: { dailyGoal: null, editorFont: "system", defaultFocusMode: false },
    requestedLocation: null,
  }
  if (!projectId || !api) return result

  const session = getWritingSession(projectId)
  const queryChapter = Number(query.get("chapter_index") || 0)
  const querySceneId = query.get("scene_id") || null
  result.requestedLocation = queryChapter > 0
    ? { chapter: queryChapter, draftId: query.get("draft_id") || null, sceneId: querySceneId }
    : session?.currentChapter
      ? {
          chapter: session.currentChapter,
          draftId: session.currentDraftId,
          sceneId: session.currentSceneId,
        }
      : state?.viewStates?.writing?.projectId === projectId
        ? {
            chapter: state.viewStates.writing.currentChapter,
            draftId: state.viewStates.writing.currentDraftId,
            sceneId: state.viewStates.writing.currentSceneId,
            versionNumber: state.viewStates.writing.currentVersionNumber,
            isReadonly: state.viewStates.writing.isReadonly,
          }
        : null

  const [chapterResult, scenesResult, prefsResult] = await Promise.allSettled([
    api.writing.listChapters(projectId),
    api.outline.listScenesOrdered(projectId),
    api.settings?.getEffectiveAuthorPrefs?.(projectId),
  ])
  if (chapterResult.status === "fulfilled") Object.assign(result, normalizeChapters(chapterResult.value))
  else result.chapterLoadError = chapterResult.reason?.message || "章节列表加载失败"
  if (scenesResult.status === "fulfilled") result.scenes = scenesResult.value || []
  if (prefsResult.status === "fulfilled" && prefsResult.value) {
    const unwrap = (value, fallback) => value && typeof value === "object" && "value" in value
      ? (value.value ?? fallback)
      : (value ?? fallback)
    result.authorPreferences = {
      dailyGoal: unwrap(prefsResult.value.daily_goal, null),
      editorFont: unwrap(prefsResult.value.editor_font, "system"),
      defaultFocusMode: Boolean(unwrap(prefsResult.value.default_focus_mode, false)),
    }
  }
  return result
}

export function useWritingWorkspace(props) {
  const api = getApi()
  const appState = getAppState()
  const router = getRouter()
  const toast = getToast()
  const confirm = getConfirm()
  const confirmAction = getConfirmAction()
  const confirmDialog = (message, confirmText) => confirmAsync(message, confirmText, { confirmAction })
  const projectId = props.projectId
  const chapterList = ref([...(props.chapterList || [])])
  const chapters = reactive({ ...(props.chapters || {}) })
  const scenes = ref([...(props.scenes || [])])
  const chapterLoadError = ref(props.chapterLoadError || null)
  const versions = ref([])
  const versionLoadError = ref(null)
  const selectedChapter = ref(null)
  const selectedSceneId = ref(null)
  const editorState = reactive({
    chapter: null,
    draftId: null,
    versionNumber: null,
    updatedAt: null,
    status: "draft",
    readonly: false,
    title: "",
    content: "",
    lastSavedTitle: "",
    lastSavedContent: "",
    cursorOffset: 0,
    saving: false,
    dirty: false,
    loadError: null,
  })
  const publishProgress = reactive({ active: false, taskId: null, phase: null, progress: null, message: "", retryable: false })
  const conflictState = reactive({ loading: false, latest: null, error: null })
  const conflictOptions = reactive({ open: false, includeCandidates: false })
  const conflictDialog = reactive({ open: false, check: null, busy: false, error: null, sourcePreview: null })
  const sceneState = reactive({ loading: false, mapSummary: null, error: null, alerts: [], people: [], location: null })
  const deepImportState = reactive({ taskId: null, projectId: null, progress: null })
  const deepAuditOpen = ref(false)
  const autoExtraction = reactive({ open: false, stage: "scenes", start: 1, end: 1, highQuality: false, busy: false })
  const outlineFloat = reactive({ open: false, loading: false, threads: [], error: null })
  const versionDialog = reactive({ open: false, diffOpen: false, leftId: null, rightId: null, diff: null, loading: false, error: null })
  const generationLoading = ref(false)
  const focusMode = ref(Boolean(props.authorPreferences?.defaultFocusMode))
  const forceDesktop = ref(false)
  const isNarrow = ref(typeof window !== "undefined" && window.innerWidth < 600)
  const disposed = ref(false)
  let selectionGeneration = 0
  let sceneGeneration = 0
  let publishGeneration = 0
  let versionDiffGeneration = 0
  let publishTimer = null
  let lastPublishPayload = null

  const inferredScene = computed(() => findCurrentScene({
    scenes: scenes.value,
    chapterIndex: selectedChapter.value,
    cursorOffset: editorState.cursorOffset,
  }))
  const currentScene = computed(() => (
    scenes.value.find((scene) => scene.id === selectedSceneId.value)
    || inferredScene.value
  ))
  const mobileMode = computed(() => isNarrow.value && !forceDesktop.value && selectedChapter.value && !editorState.readonly)
  const canEdit = computed(() => selectedChapter.value != null && !editorState.readonly)
  const activeVersions = computed(() => versions.value.filter((version) => (
    version.display_state
      ? version.display_state === "active"
      : !["candidate", "deprecated"].includes(version.status)
  )))
  const saveStatus = computed(() => {
    if (editorState.saving) return "正在保存"
    if (editorState.saveError) return "保存失败，已保留本地备份"
    if (editorState.readonly) return "只读"
    if (!editorState.dirty) return "已保存到工作稿"
    return substantiveWritingText(editorState.content) === substantiveWritingText(editorState.lastSavedContent)
      ? "排版修改已保留在本地"
      : "尚未保存"
  })

  const editor = createEditorController({
    api,
    toast,
    confirm,
    confirmDialog,
    getProjectId: () => projectId,
    getScenes: () => scenes.value,
    onChange: (value) => {
      Object.assign(editorState, value)
      if (value.chapter && chapters[value.chapter] && !["candidate", "deprecated"].includes(value.status)) {
        chapters[value.chapter] = {
          ...chapters[value.chapter],
          title: value.title,
          word_count: value.content.length,
          status: value.status,
        }
      }
      syncLegacyState()
      dispatchDashboardUpdate()
      refreshSceneAlerts()
    },
    onSceneChange: (sceneId) => {
      selectedSceneId.value = sceneId
      loadSceneContext()
    },
    onVersionChanged: async () => {
      if (!selectedChapter.value || getAppState()?.currentProjectId !== projectId) return
      await Promise.all([
        loadVersions(selectedChapter.value, selectionGeneration),
        reloadChapters(),
      ])
    },
  })

  const deepImport = createDeepImportController({
    api,
    toast,
    getProjectId: () => projectId,
    onChange: (value) => Object.assign(deepImportState, value),
    onDone: reloadChapters,
  })

  const conflictActions = createConflictController({
    api,
    toast,
    getProjectId: () => getAppState()?.currentProjectId === projectId ? projectId : null,
    getCheck: () => conflictDialog.check,
    onCheck: (check) => {
      conflictDialog.check = check
      conflictState.latest = check
      refreshSceneAlerts()
    },
  })

  async function applyCommandResult(result) {
    const view = {
      _chapterList: [...chapterList.value],
      _chapters: chapters,
      _scenes: scenes.value,
    }
    const action = applyToolsResult(result, view)
    chapterList.value = [...view._chapterList]
    scenes.value = [...view._scenes]
    if (action.selectChapter) return selectChapter(action.selectChapter, action.selectOptions || {})
    if (action.rerender) return loadSceneContext()
    await reloadChapters()
    return null
  }

  const commands = createWritingCommandController({
    api,
    toast,
    getProjectId: () => projectId,
    getChapter: () => selectedChapter.value,
    getScenes: () => scenes.value,
    editor,
    onResult: applyCommandResult,
    onLoadingChange: (value) => { generationLoading.value = Boolean(value) },
  })

  function syncLegacyState() {
    if (!appState) return
    const currentSceneId = currentScene.value?.id || null
    appState._chapterList = chapterList.value
    appState._chapters = chapters
    appState._scenes = scenes.value
    appState._currentChapter = selectedChapter.value
    appState._currentSceneId = currentSceneId
    appState._currentContent = editorState.content
    appState._currentTitle = editorState.title
    appState._currentDraftId = editorState.status === "candidate" ? null : editorState.draftId
    appState._currentSuggestionDraftId = editorState.status === "candidate" ? editorState.draftId : null
    appState._currentVersionNumber = editorState.versionNumber
    appState._currentUpdatedAt = editorState.updatedAt
    appState._isReadonly = editorState.readonly
    appState._cursorOffset = editorState.cursorOffset
    appState._focusMode = focusMode.value
    appState._forceDesktopMode = forceDesktop.value
    appState.viewStates = appState.viewStates || {}
    appState.viewStates.writing = {
      ...(appState.viewStates.writing || {}),
      projectId,
      currentChapter: selectedChapter.value,
      currentDraftId: editorState.draftId,
      currentVersionNumber: editorState.versionNumber,
      isReadonly: editorState.readonly,
      currentSceneId,
    }
    rememberWritingLocation(projectId, {
      currentChapter: selectedChapter.value,
      currentDraftId: editorState.draftId,
      currentSceneId,
    })
  }

  function dailyWordcount() {
    try {
      const today = new Date().toISOString().slice(0, 10)
      return Number(localStorage.getItem(`novel_daily_wc_${today}_${projectId || "global"}`) || 0) || 0
    } catch { return 0 }
  }

  function dispatchDashboardUpdate(chapterIndex = selectedChapter.value) {
    if (typeof window === "undefined") return
    window.dispatchEvent(new CustomEvent("writing:dashboard-update", {
      detail: {
        chapterIndex: chapterIndex == null ? null : Number(chapterIndex),
        chapterWords: chapterIndex == null ? 0 : editorState.content.length,
        todayWords: chapterIndex == null ? 0 : dailyWordcount() + editorState.content.length,
        saveState: chapterIndex == null ? "saved" : editorState.saving ? "saving" : editorState.dirty ? "unsaved" : "saved",
      },
    }))
  }

  async function loadVersions(chapter, generation) {
    versionLoadError.value = null
    try {
      const result = await api.writing.getVersionHistory(chapter, projectId)
      if (generation !== selectionGeneration || disposed.value || getAppState()?.currentProjectId !== projectId) return false
      versions.value = result?.versions || []
      return true
    } catch (err) {
      if (
        generation !== selectionGeneration
        || disposed.value
        || getAppState()?.currentProjectId !== projectId
      ) return false
      versions.value = []
      versionLoadError.value = err?.message || "版本历史加载失败"
      return false
    }
  }

  async function selectChapter(chapter, options = {}) {
    const next = Number(chapter) || null
    const generation = ++selectionGeneration
    if (selectedChapter.value && selectedChapter.value !== next) await editor.autosave()
    if (generation !== selectionGeneration || disposed.value) return false
    selectedChapter.value = next
    selectedSceneId.value = null
    versions.value = []
    if (!next) {
      await editor.loadChapter(null)
      syncLegacyState()
      return true
    }
    const [loaded] = await Promise.all([
      editor.loadChapter(next, options),
      loadVersions(next, generation),
    ])
    if (!loaded || generation !== selectionGeneration || disposed.value) return false
    const requestedScene = scenes.value.find((scene) => (
      scene.id === options.sceneId
      && (
        (scene.chapter_ids || []).includes(String(next))
        || (scene.scene_chunks || []).some((chunk) => (
          Number(chunk.chapter_index) === next
        ))
      )
    ))
    selectedSceneId.value = requestedScene?.id || inferredScene.value?.id || null
    syncLegacyState()
    await loadSceneContext()
    return true
  }

  async function reloadChapters() {
    try {
      const data = await api.writing.listChapters(projectId)
      if (disposed.value || getAppState()?.currentProjectId !== projectId) return false
      const normalized = normalizeChapters(data)
      chapterList.value = normalized.chapterList
      for (const key of Object.keys(chapters)) delete chapters[key]
      Object.assign(chapters, normalized.chapters)
      chapterLoadError.value = null
      return true
    } catch (err) {
      chapterLoadError.value = err?.message || "章节列表加载失败"
      return false
    }
  }

  async function createChapter() {
    const chapter = chapterList.value.length ? Math.max(...chapterList.value) + 1 : 1
    try {
      const draft = await api.writing.autosaveDraftOnly({
        novel_id: projectId,
        chapter_index: chapter,
        title: `第 ${chapter} 章`,
        content: "",
      })
      if (getAppState()?.currentProjectId !== projectId) return
      chapters[chapter] = { ...draft, chapter_index: chapter, word_count: 0 }
      chapterList.value = [...chapterList.value, chapter].sort((a, b) => a - b)
      await selectChapter(chapter, { draftId: draft.id })
    } catch (err) {
      toast(err?.message || "创建章节失败", "error")
    }
  }

  function openAutoExtraction(stage = "scenes") {
    autoExtraction.stage = stage
    autoExtraction.start = chapterList.value.length ? Math.min(...chapterList.value) : 1
    autoExtraction.end = chapterList.value.length ? Math.max(...chapterList.value) : 10
    autoExtraction.highQuality = false
    autoExtraction.open = true
  }

  async function submitAutoExtraction(force = false) {
    if (autoExtraction.busy) return
    const activeStatus = deepImportState.progress?.status || deepImportState.progress?.phase
    if (deepImportState.progress && !["done", "failed", "cancelled"].includes(activeStatus)) {
      toast("已有自动提取任务正在运行，请等待完成或先取消当前任务", "warning")
      return
    }
    if (Number(autoExtraction.end) < Number(autoExtraction.start)) {
      toast("结束章节必须 ≥ 起始章节", "warning")
      return
    }
    autoExtraction.busy = true
    const stageConfig = {
      deep: ["deep_import", "整理导入内容"],
      scenes: ["scene_auto_extraction", "从正文整理场景"],
      world_objects: ["world_object_auto_extraction", "整理人物、设定与关系"],
      plot_structure: ["plot_structure_auto_extraction", "从正文整理剧情线"],
    }[autoExtraction.stage] || ["scene_auto_extraction", "从正文整理场景"]
    try {
      const authorization = importAuthorizationPayload()
      const result = autoExtraction.stage === "deep"
        ? await api.imports.deepImport(
          projectId,
          Number(autoExtraction.start),
          Number(autoExtraction.end),
          force,
          autoExtraction.highQuality,
          authorization,
        )
        : await api.imports.startStage(
          autoExtraction.stage,
          projectId,
          Number(autoExtraction.start),
          Number(autoExtraction.end),
          force,
          autoExtraction.highQuality,
          authorization,
        )
      if (getAppState()?.currentProjectId !== projectId) return
      if (result?.requires_confirmation) {
        if (confirm(result.warning || "该操作会覆盖现有结果，确定继续？")) {
          autoExtraction.busy = false
          return submitAutoExtraction(true)
        }
        return
      }
      if (!result?.task_id) {
        toast(result?.message || "未启动自动提取", "warning")
        return
      }
      const returnedWorkflowType = result.workflow_type || stageConfig[0]
      const returnedLabel = {
        deep_import: "整理导入内容",
        scene_auto_extraction: "从正文整理场景",
        world_object_auto_extraction: "整理人物、设定与关系",
        plot_structure_auto_extraction: "从正文整理剧情线",
      }[returnedWorkflowType] || stageConfig[1]
      deepImport.startTask({
        taskId: result.task_id,
        workflowType: returnedWorkflowType,
        stage: result.stage || autoExtraction.stage,
        label: returnedLabel,
        startChapter: Number(autoExtraction.start),
        endChapter: Number(autoExtraction.end),
      })
      autoExtraction.open = false
      toast(
        result.reused_task ? `已连接到现有“${returnedLabel}”任务` : `${returnedLabel}已启动`,
        "success",
      )
    } catch (err) {
      toast(err?.message || "提交自动提取失败", "error")
    } finally {
      autoExtraction.busy = false
    }
  }

  async function switchVersion(draftId) {
    const version = versions.value.find((item) => item.id === draftId)
    if (!version || !selectedChapter.value) return
    const active = versions.value.filter((item) => item.display_state ? item.display_state === "active" : !["candidate", "deprecated"].includes(item.status))
    const latest = active[0] || active.reduce((best, item) => Number(item.version_number) > Number(best?.version_number || 0) ? item : best, null)
    await selectChapter(selectedChapter.value, {
      draftId,
      versionNumber: version.version_number,
      isReadonly: version.id !== latest?.id || ["candidate", "deprecated"].includes(version.status),
      restoreSourceVersion: version.id !== latest?.id && active.includes(version) ? version.version_number : null,
      restoreExpectedVersion: latest?.version_number || null,
      restoreExpectedUpdatedAt: latest?.updated_at || null,
    })
  }

  function openVersionHistory() {
    versionDialog.open = true
    versionDialog.diffOpen = false
    versionDialog.error = null
  }

  async function restoreVersion(version) {
    const active = versions.value.filter((item) => item.display_state ? item.display_state === "active" : !["candidate", "deprecated"].includes(item.status))
    if (!active.includes(version)) return
    const latest = active.reduce((best, item) => Number(item.version_number) > Number(best?.version_number || 0) ? item : best, null)
    if (version.id !== latest?.id) {
      const confirmed = await confirmDialog(`恢复至 v${version.version_number}？当前编辑器内容将丢失。`, "确认恢复")
      if (!confirmed) return
    }
    versionDialog.open = false
    await selectChapter(selectedChapter.value, {
      draftId: version.id,
      versionNumber: version.version_number,
      isReadonly: false,
      restoreSourceVersion: version.version_number,
      restoreExpectedVersion: latest?.version_number || null,
      restoreExpectedUpdatedAt: latest?.updated_at || null,
    })
  }

  async function deleteVersion(version) {
    const active = versions.value.filter((item) => item.display_state ? item.display_state === "active" : !["candidate", "deprecated"].includes(item.status))
    const latest = active.reduce((best, item) => Number(item.version_number) > Number(best?.version_number || 0) ? item : best, null)
    if (!active.includes(version) || active.length <= 1 || version.id === latest?.id) {
      toast("不能删除唯一版本、最新版本或只读历史", "warning")
      return
    }
    if (!confirm(`确定删除 v${version.version_number}？`)) return
    try {
      await api.writing.deleteDraft(version.id, projectId)
      await loadVersions(selectedChapter.value, selectionGeneration)
    } catch (err) {
      toast(err?.message || "删除版本失败", "error")
    }
  }

  async function compareVersions() {
    const candidates = versions.value.filter((item) => item.id)
    if (candidates.length < 2) return
    versionDialog.leftId ||= candidates[1]?.id || candidates[0].id
    versionDialog.rightId ||= candidates[0].id
    if (versionDialog.leftId === versionDialog.rightId) {
      versionDialog.error = "请选择两个不同版本"
      return
    }
    const token = ++versionDiffGeneration
    versionDialog.loading = true
    versionDialog.error = null
    try {
      const [left, right] = await Promise.all([
        api.writing.get(versionDialog.leftId, projectId),
        api.writing.get(versionDialog.rightId, projectId),
      ])
      if (token !== versionDiffGeneration || getAppState()?.currentProjectId !== projectId) return
      if ((left?.novel_id && left.novel_id !== projectId) || (right?.novel_id && right.novel_id !== projectId)) throw new Error("版本项目不匹配")
      versionDialog.diff = buildVersionDiff(left?.content || "", right?.content || "")
      versionDialog.diffOpen = true
    } catch (err) {
      if (
        token !== versionDiffGeneration
        || disposed.value
        || getAppState()?.currentProjectId !== projectId
      ) return
      versionDialog.error = err?.message || "版本比较失败"
    } finally {
      if (
        token === versionDiffGeneration
        && !disposed.value
        && getAppState()?.currentProjectId === projectId
      ) versionDialog.loading = false
    }
  }

  async function confirmBeforePublish() {
    let latest = null
    try {
      const result = await api.writing.listConflictChecks({
        novel_id: projectId,
        chapter_index: selectedChapter.value,
        scene_id: currentScene.value?.id || null,
        limit: 1,
      })
      if (disposed.value || getAppState()?.currentProjectId !== projectId) return false
      latest = result?.items?.[0] || null
    } catch (err) {
      if (disposed.value || getAppState()?.currentProjectId !== projectId) return false
      toast(`无法读取正式正文前的设定检查：${err?.message || "服务暂不可用"}。本次操作已停止，请稍后重试。`, "error")
      return false
    }
    if (!latest) {
      return confirmAsync(
        "当前章节还没有前后设定检查记录。可以继续设为正式正文，也可以先运行检查。",
        "继续设为正式正文",
        { confirmAction },
      )
    }
    const items = Array.isArray(latest.items) ? latest.items : []
    const openHighCount = items.length
      ? items.filter((item) => item.severity === "high" && item.status === "open").length
      : Number(latest.summary_json?.open_high_count || 0)
    if (openHighCount > 0) {
      return confirmAsync(
        `最近一次检查仍有 ${openHighCount} 个未处理的重要问题。确认继续设为正式正文？`,
        "继续设为正式正文",
        { confirmAction },
      )
    }
    return true
  }

  function buildPublishPayload() {
    return {
      novel_id: projectId,
      chapter_index: selectedChapter.value,
      scene_id: currentScene.value?.id || null,
      draft_id: editorState.draftId,
      expected_version: editorState.restoreSourceVersion
        ? (editorState.restoreExpectedVersion || editorState.versionNumber)
        : editorState.versionNumber,
      expected_updated_at: editorState.restoreSourceVersion
        ? (editorState.restoreExpectedUpdatedAt || editorState.updatedAt)
        : editorState.updatedAt,
      restore_source_version: editorState.restoreSourceVersion || null,
      title: editorState.title || `第 ${selectedChapter.value} 章`,
      content: editorState.content,
    }
  }

  async function submitPublish(payload, { retry = false } = {}) {
    if (!canEdit.value || !editorState.content.trim() || publishProgress.active) return
    const generation = ++publishGeneration
    lastPublishPayload = { ...payload }
    if (publishTimer) clearTimeout(publishTimer)
    publishTimer = null
    publishProgress.active = true
    publishProgress.retryable = false
    publishProgress.taskId = null
    publishProgress.phase = "running"
    publishProgress.progress = 0
    publishProgress.message = retry ? "正在重试正式正文后续整理..." : "正在设为正式正文..."
    try {
      const result = await api.writing.publish(payload)
      if (generation !== publishGeneration || disposed.value) return
      publishProgress.taskId = result?.task_id || null
      publishProgress.phase = result?.task_id ? "running" : "done"
      publishProgress.progress = result?.task_id ? 0 : 100
      publishProgress.message = result?.task_id ? "正在整理相关资料..." : "已设为正式正文"
      await reloadChapters()
      if (result?.new_version !== false && selectedChapter.value) {
        await selectChapter(selectedChapter.value)
      }
      toast(result?.new_version === false ? "正文无实质变化，已沿用当前正式正文" : "已设为正式正文", result?.new_version === false ? "info" : "success")
      if (result?.task_id) schedulePublishPoll(generation, result.task_id)
    } catch (err) {
      if (generation !== publishGeneration) return
      publishProgress.phase = "failed"
      publishProgress.message = sanitizeTaskErrorMessage(err?.message, "publish_chapter") || "未能设为正式正文。工作稿已保留，可手动重试。"
      publishProgress.retryable = true
      toast(publishProgress.message, "error")
    } finally {
      if (generation === publishGeneration && !publishProgress.taskId) publishProgress.active = false
    }
  }

  async function publish() {
    if (!canEdit.value || !editorState.content.trim() || publishProgress.active) return
    if (!(await confirmBeforePublish())) return
    await editor.autosave()
    if (disposed.value || getAppState()?.currentProjectId !== projectId) return
    return submitPublish(buildPublishPayload())
  }

  function retryPublish() {
    if (!lastPublishPayload || getAppState()?.currentProjectId !== projectId) return null
    return submitPublish({ ...lastPublishPayload }, { retry: true })
  }

  function dismissPublishError() {
    if (publishTimer) clearTimeout(publishTimer)
    publishTimer = null
    publishGeneration += 1
    Object.assign(publishProgress, { active: false, taskId: null, phase: null, progress: null, message: "", retryable: false })
  }

  function saveCurrent() {
    if (editorState.restoreSourceVersion) return publish()
    return editor.autosave()
  }

  function saveMobileNote() {
    return editor.autosave({ successMessage: "已保存到工作稿", createIfMissing: true })
  }

  function schedulePublishPoll(generation, taskId) {
    if (publishTimer) clearTimeout(publishTimer)
    publishTimer = setTimeout(async () => {
      if (generation !== publishGeneration || disposed.value || getAppState()?.currentProjectId !== projectId) return
      try {
        const task = await api.tasks.get(taskId, projectId)
        if (
          generation !== publishGeneration
          || disposed.value
          || getAppState()?.currentProjectId !== projectId
        ) return
        publishProgress.progress = task.progress == null ? null : Math.round(Number(task.progress) * (Number(task.progress) <= 1 ? 100 : 1))
        publishProgress.phase = task.status
        if (["done", "failed", "cancelled"].includes(task.status)) {
          publishProgress.active = false
          publishProgress.message = task.status === "done"
            ? "正式正文已就绪"
            : (sanitizeTaskErrorMessage(task.error_message || task.result?.error_message || task.result?.error, "publish_chapter") || `任务${task.status}`)
          publishProgress.retryable = task.status !== "done"
          publishProgress.taskId = null
          return
        }
      } catch {
        publishProgress.active = false
        publishProgress.phase = "failed"
        publishProgress.retryable = true
        publishProgress.taskId = null
        publishProgress.message = "正式正文的后续状态暂时无法读取。工作稿已保留，可手动重试。"
        return
      }
      schedulePublishPoll(generation, taskId)
    }, 2000)
  }

  function requestConflictCheck() {
    if (!canEdit.value || conflictState.loading) return
    conflictOptions.includeCandidates = false
    conflictOptions.open = true
  }

  async function runConflictCheck() {
    if (!canEdit.value || conflictState.loading) return
    conflictOptions.open = false
    conflictState.loading = true
    conflictState.error = null
    try {
      await editor.autosave()
      const check = await api.writing.createConflictCheck({
        novel_id: projectId,
        chapter_index: selectedChapter.value,
        scene_id: currentScene.value?.id || null,
        draft_id: editorState.draftId,
        version_number: editorState.versionNumber,
        content: editorState.content,
        include_candidates: conflictOptions.includeCandidates,
      })
      if (getAppState()?.currentProjectId !== projectId) return
      conflictState.latest = check
      refreshSceneAlerts()
      toast("冲突检查已完成", "success")
      openConflictDialog(check)
    } catch (err) {
      conflictState.error = err?.message || "冲突检查失败"
      toast(conflictState.error, "error")
    } finally {
      conflictState.loading = false
    }
  }

  function locateConflictItem(check, itemId) {
    const item = (check?.items || []).find((entry) => entry.id === itemId)
    const location = item?.location_json || {}
    const textRange = location.text_range || location
    if (!editor.selectRange(textRange.start, textRange.end ?? textRange.start)) {
      toast("该问题暂无正文定位", "info")
    }
  }

  function openConflictSource(check, itemId) {
    const item = (check?.items || []).find((entry) => entry.id === itemId)
    const location = item?.location_json || {}
    const target = location.open_target || {}
    if (target.kind === "text_range") return locateConflictItem(check, itemId)
    if (target.kind === "map_scene" || target.kind === "map_object" || item?.source_module === "world") return openMap(target)
    if (target.kind === "outline_scene" || item?.source_module === "outline") {
      const query = new URLSearchParams()
      if (target.scene_id) query.set("scene_id", target.scene_id)
      return router?.navigate?.("outline", "scenes", true, query)
    }
    if (target.kind === "memory_chapter") {
      const chapter = target.chapter_index || location.source?.chapter_index || "-"
      const character = target.character_id || location.source?.character_id || "-"
      conflictDialog.sourcePreview = {
        kind: "memory",
        title: "记忆来源",
        chapterIndex: chapter,
        characterId: character,
      }
      return
    }
    conflictDialog.sourcePreview = { kind: "unavailable", message: "该来源暂无可打开视图" }
  }

  async function refreshConflictCheck(checkId) {
    if (!checkId) return null
    try {
      const updated = await api.writing.getConflictCheck(checkId, projectId)
      if (getAppState()?.currentProjectId !== projectId) return null
      conflictState.latest = updated
      if (conflictDialog.open && (!conflictDialog.check?.id || conflictDialog.check.id === updated?.id)) {
        conflictDialog.check = updated
      }
      refreshSceneAlerts()
      return updated
    } catch (err) {
      toast(err?.message || "刷新检查记录失败", "error")
      return null
    }
  }

  async function openConflictDialog(value = conflictState.latest) {
    let check = value
    if (check?.id && !Array.isArray(check.items)) check = await refreshConflictCheck(check.id)
    if (!check) {
      toast("检查记录暂不可用", "warning")
      return
    }
    conflictDialog.check = check
    conflictDialog.error = null
    conflictDialog.sourcePreview = null
    conflictDialog.open = true
  }

  function closeConflictDialog() {
    if (conflictDialog.busy) return
    conflictDialog.open = false
    conflictDialog.sourcePreview = null
  }

  async function updateConflictStatus({ itemId, status }) {
    if (conflictDialog.busy) return
    conflictDialog.busy = true
    conflictDialog.error = null
    try {
      await conflictActions.updateStatus(itemId, status)
    } finally {
      conflictDialog.busy = false
    }
  }

  async function runConflictAiReview() {
    if (conflictDialog.busy) return
    conflictDialog.busy = true
    conflictDialog.error = null
    try {
      await conflictActions.runAiReview()
    } finally {
      conflictDialog.busy = false
    }
  }

  async function requestConflictSuggestion(itemId) {
    if (conflictDialog.busy) return
    conflictDialog.busy = true
    conflictDialog.error = null
    try {
      await conflictActions.requestSuggestion(itemId)
    } finally {
      conflictDialog.busy = false
    }
  }

  function applyConflictSuggestion({ text }) {
    if (!text) {
      toast("建议内容为空", "warning")
      return
    }
    editor.insertText(text)
    toast("AI 建议已采用到当前工作稿", "success")
  }

  function refreshSceneAlerts() {
    sceneState.alerts = buildSceneAlerts({
      scene: currentScene.value,
      chapterIndex: selectedChapter.value,
      content: editorState.content,
      mapSummary: sceneState.mapSummary,
      mapError: sceneState.error,
      latestCheck: conflictState.latest,
      checkError: conflictState.error,
      checkLoading: conflictState.loading,
      draftId: editorState.draftId,
      versionNumber: editorState.versionNumber,
      isDirty: editorState.dirty,
    })
  }

  async function loadSceneContext() {
    const scene = currentScene.value
    const generation = ++sceneGeneration
    sceneState.mapSummary = null
    sceneState.error = null
    sceneState.people = []
    sceneState.location = null
    refreshSceneAlerts()
    if (!scene?.id) return
    sceneState.loading = true
    try {
      const entityQuery = (entityType) => api.world.listEntities({
        novel_id: projectId,
        scene_id: scene.id,
        entity_type: entityType,
        display_state: "active",
        skip: 0,
        limit: 12,
      })
      const [mapResult, checkResult, peopleResult, locationResult] = await Promise.allSettled([
        api.world.getMapSceneSummary(projectId, scene.id),
        api.writing.listConflictChecks({ novel_id: projectId, chapter_index: selectedChapter.value, scene_id: scene.id, limit: 1 }),
        entityQuery("character"),
        entityQuery("location"),
      ])
      if (generation !== sceneGeneration || disposed.value || getAppState()?.currentProjectId !== projectId) return
      if (mapResult.status === "fulfilled") sceneState.mapSummary = mapResult.value
      else sceneState.error = mapResult.reason?.message || "地图摘要加载失败"
      if (checkResult.status === "fulfilled") {
        const candidate = checkResult.value?.items?.[0] || null
        const mismatch = candidate && (
          (candidate.novel_id && candidate.novel_id !== projectId)
          || (candidate.chapter_index != null && Number(candidate.chapter_index) !== Number(selectedChapter.value))
          || (candidate.scene_id && candidate.scene_id !== scene.id)
        )
        conflictState.latest = mismatch ? null : candidate
        conflictState.error = mismatch ? "最近校验身份不匹配，已安全忽略" : null
      } else conflictState.error = checkResult.reason?.message || "最近检查加载失败"
      const listItems = (value) => Array.isArray(value) ? value : (value?.items || [])
      const dedupe = (items) => {
        const seen = new Set()
        return items.filter((item) => {
          const key = item?.id || item?.entity_id || item?.name || item?.title
          if (!key || seen.has(key)) return false
          seen.add(key)
          return true
        })
      }
      sceneState.people = dedupe([
        ...(Array.isArray(scene.scene_characters) ? scene.scene_characters : []),
        ...(Array.isArray(sceneState.mapSummary?.characters) ? sceneState.mapSummary.characters : []),
        ...(peopleResult.status === "fulfilled" ? listItems(peopleResult.value) : []),
      ])
      sceneState.location = scene.primary_location || scene.location || sceneState.mapSummary?.primary_location
        || (locationResult.status === "fulfilled" ? listItems(locationResult.value)[0] : null)
    } finally {
      if (generation === sceneGeneration) {
        sceneState.loading = false
        refreshSceneAlerts()
      }
    }
  }

  function openMap(value = {}) {
    if (!projectId) return
    const provided = value && typeof value === "object" && !(value instanceof Event) ? value : {}
    const target = {
      ...(sceneState.mapSummary?.open_target || {}),
      ...provided,
    }
    if (target.fallback_message) toast(target.fallback_message, "warning")
    window.open(buildMapUrl({
      projectId,
      mapId: target.map_id || null,
      sceneId: target.scene_id || currentScene.value?.id || null,
      focusEntityId: target.entity_id || target.focus_entity_id || null,
      focusHexQ: target.focus_hex_q ?? null,
      focusHexR: target.focus_hex_r ?? null,
      focusPathId: target.focus_path_id || null,
      focusLayerNodeId: target.focus_layer_node_id || null,
      mode: target.mode || (target.map_id ? "live" : "overview"),
    }), "_blank", "noopener")
  }

  function navigateSceneWorkbench() {
    const query = new URLSearchParams()
    if (currentScene.value?.id) query.set("scene_id", currentScene.value.id)
    router?.navigate?.("outline", "scenes", true, query)
  }

  async function toggleOutlineFloat() {
    outlineFloat.open = !outlineFloat.open
    if (!outlineFloat.open || outlineFloat.threads.length) return
    outlineFloat.loading = true
    outlineFloat.error = null
    try {
      const result = await api.outline.listThreads(projectId, { limit: 50 })
      if (getAppState()?.currentProjectId !== projectId) return
      outlineFloat.threads = result?.items || result || []
    } catch (err) {
      outlineFloat.error = err?.message || "大纲加载失败"
    } finally {
      outlineFloat.loading = false
    }
  }

  async function runDeepImportNextStep() {
    const next = deepImportState.progress?.mapNextStep
    if (!next) return
    if (next.action === "review-locations") {
      const query = new URLSearchParams({ entity_type: "location", source: "deep_import" })
      if (next.workflow_id) query.set("workflow_id", next.workflow_id)
      router?.navigate?.("world", "review-objects", true, query)
      deepImport.dismiss()
      return
    }
    if (next.action === "quick-create") {
      await openWritingMapQuickCreate({
        projectId,
        onCreated: async (createdMap) => {
          let remaining = 0
          try {
            const inbox = await api.world.listProjectMapObservationInbox(projectId, { limit: 1 })
            if (getAppState()?.currentProjectId !== projectId) return false
            remaining = Number(inbox?.total || 0)
          } catch { /* 地图已创建，收件箱计数不应阻塞打开 */ }
          const mapUrl = buildMapUrl({ projectId, mapId: createdMap?.id || null, mode: createdMap?.id ? "dashboard" : "overview" })
          const opened = window.open(mapUrl, "_blank", "noopener")
          if (!opened) window.location.assign(mapUrl)
          toast(remaining > 0 ? `地图已创建，收件箱还有 ${remaining} 条待处理动态` : "地图已创建", "success")
          deepImport.dismiss()
          return true
        },
      })
      return
    }
    const opened = window.open(buildMapUrl({ projectId, mapId: next.map_id || null, mode: next.map_id ? "dashboard" : "overview" }), "_blank", "noopener")
    if (opened) deepImport.dismiss()
    else toast("浏览器阻止了新窗口，请允许后重试", "warning")
  }

  async function deleteChapters(selected = []) {
    const targets = [...new Set(selected.map(Number).filter((chapter) => chapterList.value.includes(chapter)))]
    if (!targets.length) return false
    if (!confirm(`确定删除选中的 ${targets.length} 个章节及其全部版本？此操作不可恢复。`)) return false
    const settled = await Promise.allSettled(targets.map((chapter) => api.writing.deleteChapter(chapter, projectId)))
    if (getAppState()?.currentProjectId !== projectId) return false
    const deleted = new Set(targets.filter((_chapter, index) => settled[index].status === "fulfilled"))
    for (const chapter of deleted) delete chapters[chapter]
    chapterList.value = chapterList.value.filter((chapter) => !deleted.has(chapter))
    if (deleted.has(selectedChapter.value)) await selectChapter(null)
    const failed = targets.length - deleted.size
    toast(failed ? `已删除 ${deleted.size} 章，${failed} 章删除失败` : `已删除 ${deleted.size} 个章节`, failed ? "warning" : "success")
    return failed === 0
  }

  function cancelDeepImport() {
    return confirmAction(
      "确认取消当前任务？已完成的阶段结果不会自动删除。",
      () => deepImport.cancel(),
      "确认取消",
    )
  }

  function abandonDeepImport() {
    return confirmAction(
      "确认放弃深度导入恢复？后端会清理或将已写入资产转入历史。",
      () => deepImport.abandon(),
      "确认放弃",
    )
  }

  function exportChapter() {
    if (!selectedChapter.value) return
    const title = editorState.title || `第 ${selectedChapter.value} 章`
    const blob = new Blob([`${title}\n\n${editorState.content}`], { type: "text/plain;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${title.replace(/[\\/:*?"<>|]/g, "")}.txt`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function toggleFocusMode() { focusMode.value = !focusMode.value }
  function switchDesktopMode() { forceDesktop.value = true }
  function attachEditor(elements) { editor.attach(elements) }
  function detachEditor() { editor.detach() }

  useLeaveGuard(() => {
    if (!editor.hasUnsavedChanges()) return true
    editor.persist()
    return confirm("当前正文有未保存修改，已保留本地暂存。确定离开写作台吗？")
  })

  function beforeUnload(event) {
    if (!editor.hasUnsavedChanges() || editorState.readonly) return
    editor.persist()
    event.preventDefault()
    event.returnValue = ""
  }

  function resize() { isNarrow.value = window.innerWidth < 600 }

  watch(focusMode, (active) => {
    document.body.classList.toggle("focus-mode-active", active)
    syncLegacyState()
  }, { immediate: true })
  watch(forceDesktop, (active) => document.body.classList.toggle("force-desktop", active), { immediate: true })

  onMounted(async () => {
    window.addEventListener("beforeunload", beforeUnload)
    window.addEventListener("resize", resize)
    await deepImport.recover()
    dispatchDashboardUpdate()
    const requested = props.requestedLocation
    if (requested?.chapter && chapterList.value.includes(Number(requested.chapter))) {
      await selectChapter(requested.chapter, {
        draftId: requested.draftId || null,
        versionNumber: requested.versionNumber,
        isReadonly: requested.isReadonly,
        sceneId: requested.sceneId,
      })
    }
  })

  onBeforeUnmount(() => {
    disposed.value = true
    selectionGeneration += 1
    sceneGeneration += 1
    publishGeneration += 1
    versionDiffGeneration += 1
    if (publishTimer) clearTimeout(publishTimer)
    publishTimer = null
    editor.dispose()
    commands.dispose()
    deepImport.dispose()
    conflictActions.dispose()
    window.removeEventListener("beforeunload", beforeUnload)
    window.removeEventListener("resize", resize)
    document.body.classList.remove("focus-mode-active", "force-desktop")
    dispatchDashboardUpdate(null)
    if (appState) {
      appState.viewStates = appState.viewStates || {}
      appState.viewStates.writing = {
        projectId,
        currentChapter: selectedChapter.value,
        currentDraftId: editorState.draftId,
        currentVersionNumber: editorState.versionNumber,
        isReadonly: editorState.readonly,
        currentSceneId: currentScene.value?.id || null,
      }
    }
  })

  return {
    projectId,
    chapterList,
    chapters,
    scenes,
    chapterLoadError,
    versions,
    versionLoadError,
    selectedChapter,
    selectedSceneId,
    currentScene,
    editorState,
    generationLoading,
    publishProgress,
    conflictState,
    conflictOptions,
    conflictDialog,
    sceneState,
    deepImportState,
    deepAuditOpen,
    autoExtraction,
    outlineFloat,
    versionDialog,
    focusMode,
    forceDesktop,
    mobileMode,
    canEdit,
    activeVersions,
    saveStatus,
    selectChapter,
    createChapter,
    deleteChapters,
    switchVersion,
    attachEditor,
    detachEditor,
    autosave: saveCurrent,
    saveMobileNote,
    checkpoint: editor.checkpoint,
    discardChanges: editor.discardChanges,
    adoptCandidate: editor.adoptCandidate,
    rejectCandidate: editor.rejectCandidate,
    insertText: editor.insertText,
    publish,
    retryPublish,
    dismissPublishError,
    generateDraft: commands.generateDraft,
    generateContinuation: commands.generateContinuation,
    generatePovDraft: commands.generatePovDraft,
    openAutoExtraction,
    submitAutoExtraction,
    cancelDeepImport,
    resumeDeepImport: deepImport.resume,
    abandonDeepImport,
    dismissDeepImport: deepImport.dismiss,
    retryDeepImportMapNext: deepImport.retryMapNextStep,
    runDeepImportNextStep,
    requestConflictCheck,
    runConflictCheck,
    openConflictDialog,
    closeConflictDialog,
    updateConflictStatus,
    runConflictAiReview,
    requestConflictSuggestion,
    applyConflictSuggestion,
    locateConflictItem: (itemId) => locateConflictItem(conflictDialog.check, itemId),
    openConflictSource: (itemId) => openConflictSource(conflictDialog.check, itemId),
    openVersionHistory,
    restoreVersion,
    deleteVersion,
    compareVersions,
    openMap,
    exportChapter,
    toggleFocusMode,
    toggleOutlineFloat,
    switchDesktopMode,
    navigateOutline: () => router?.navigate?.("outline", null),
    navigateSceneWorkbench,
  }
}
