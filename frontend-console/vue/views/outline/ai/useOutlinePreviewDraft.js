import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import { getToast } from "../../../bridge/index.js"

const clone = (value) => JSON.parse(JSON.stringify(value))

export function useOutlinePreviewDraft({
  projectId,
  preview,
  target,
  collectionKey,
  storageNamespace,
  applying,
  applyError,
  manager,
  busyLabel,
}) {
  const toast = getToast()
  const draft = ref(null)
  const originalDraft = ref(null)
  const restored = ref(false)
  const savedAt = ref(null)
  const storageError = ref("")
  const validationErrors = ref([])
  const previewConflict = ref(false)
  const conflict = computed(() => previewConflict.value || applyError.value?.status === 409)
  let currentTaskId = null
  let currentProjectId = null
  let saveTimer = null
  let initializing = false

  const storageKey = (ownerProjectId, taskId) => (
    `${storageNamespace}:${encodeURIComponent(ownerProjectId)}:${encodeURIComponent(taskId)}`
  )
  const saveState = computed(() => {
    if (applying.value) return "正在采用…"
    if (storageError.value) return "本机暂存不可用"
    if (!savedAt.value) return "修改后会自动暂存在本机"
    const date = new Date(savedAt.value)
    return Number.isNaN(date.getTime())
      ? "修改已暂存在本机"
      : `修改已暂存在本机 · ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
  })

  function saveDraft() {
    if (!draft.value || !currentProjectId || !currentTaskId) return
    try {
      const saved = new Date().toISOString()
      localStorage.setItem(storageKey(currentProjectId, currentTaskId), JSON.stringify({
        version: 1,
        project_id: currentProjectId,
        source_task_id: currentTaskId,
        target,
        conflict: conflict.value,
        saved_at: saved,
        draft_structure: draft.value,
      }))
      savedAt.value = saved
      storageError.value = ""
    } catch {
      storageError.value = "浏览器未能保存这次修改；离开本页前请先采用，或稍后重试。"
    }
  }

  function clearDraft() {
    if (!currentProjectId || !currentTaskId) return
    try { localStorage.removeItem(storageKey(currentProjectId, currentTaskId)) } catch {}
    savedAt.value = null
    restored.value = false
  }

  function finishDraft() {
    clearDraft()
    currentProjectId = null
    currentTaskId = null
    draft.value = null
  }

  function restoreOriginalDraft() {
    initializing = true
    draft.value = clone(originalDraft.value)
    clearDraft()
    manager.state.applyError = null
    void nextTick(() => {
      initializing = false
      saveDraft()
    })
  }

  function initializeDraft() {
    saveDraft()
    clearTimeout(saveTimer)
    currentProjectId = projectId.value
    currentTaskId = preview.value?.sourceTaskId || null
    validationErrors.value = []
    manager.state.applyError = null
    previewConflict.value = false
    if (!preview.value || !currentTaskId) {
      draft.value = null
      originalDraft.value = null
      restored.value = false
      return
    }
    originalDraft.value = clone(preview.value.draftStructure)
    let saved = null
    try {
      saved = JSON.parse(localStorage.getItem(storageKey(projectId.value, currentTaskId)) || "null")
      if (
        saved?.project_id !== projectId.value
        || saved?.source_task_id !== currentTaskId
        || saved?.target !== target
        || !saved?.draft_structure
        || !Array.isArray(saved.draft_structure[collectionKey])
      ) saved = null
    } catch {
      saved = null
    }
    initializing = true
    draft.value = clone(saved?.draft_structure || originalDraft.value)
    restored.value = Boolean(saved)
    previewConflict.value = saved?.conflict === true
    savedAt.value = saved?.saved_at || null
    storageError.value = ""
    void nextTick(() => { initializing = false })
  }

  watch([projectId, () => preview.value?.sourceTaskId], initializeDraft, { immediate: true })
  watch(draft, () => {
    if (initializing || !draft.value || !currentTaskId) return
    validationErrors.value = []
    if (!conflict.value) manager.state.applyError = null
    clearTimeout(saveTimer)
    saveTimer = setTimeout(saveDraft, 250)
  }, { deep: true })
  watch(applyError, (error) => {
    if (error?.status !== 409) return
    previewConflict.value = true
    saveDraft()
  })

  useLeaveGuard(() => {
    saveDraft()
    if (!applying.value) return true
    toast(`正在采用${busyLabel}，请稍候`, "info")
    return false
  })
  onBeforeUnmount(() => {
    window.removeEventListener("beforeunload", saveDraft)
    clearTimeout(saveTimer)
    saveDraft()
  })
  onMounted(() => window.addEventListener("beforeunload", saveDraft))

  return {
    conflict,
    draft,
    finishDraft,
    originalDraft,
    restored,
    restoreOriginalDraft,
    saveDraft,
    saveState,
    storageError,
    validationErrors,
  }
}
