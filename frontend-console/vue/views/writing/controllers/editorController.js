import {
  clearWritingPointerDraft,
  readChapterSnapshot,
  readWritingPointer,
  rememberChapterSnapshot,
  rememberWritingLocation,
} from "../writingSession.js"

export function substantiveWritingText(text) {
  return String(text || "").replace(/\s/gu, "")
}

function activeVersion(version) {
  if (!version) return false
  if (version.display_state) return version.display_state === "active"
  return !["candidate", "deprecated"].includes(version.status)
}

function backupKey(projectId, chapter) {
  return `draft_backup_${projectId}_${chapter}`
}

/**
 * Headless editor controller. It never renders HTML and never queries global
 * selectors. The SFC owns the DOM and explicitly attaches its element refs.
 */
export function createEditorController({
  api,
  toast = () => {},
  confirm = () => true,
  confirmDialog = async (message) => confirm(message),
  getProjectId,
  onChange = () => {},
  onVersionChanged = async () => {},
}) {
  const state = {
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
    restoreSourceVersion: null,
    restoreExpectedVersion: null,
    restoreExpectedUpdatedAt: null,
    provenanceJson: null,
    saving: false,
    saveError: null,
    loadError: null,
  }
  let elements = { title: null, editor: null }
  let autosaveTimer = null
  let cursorTimer = null
  let selectionHandler = null
  let keyupHandler = null
  let loadGeneration = 0
  let lifecycleGeneration = 0
  let editRevision = 0
  let savePromise = null
  let disposed = false
  let pendingCursorRestore = false

  function captureCommandOwner() {
    return {
      lifecycle: lifecycleGeneration,
      load: loadGeneration,
      projectId: getProjectId(),
      chapter: state.chapter,
      draftId: state.draftId,
      editRevision,
      title: state.title,
      content: state.content,
      versionNumber: state.versionNumber,
      updatedAt: state.updatedAt,
    }
  }

  function ownsCommand(owner) {
    return !disposed
      && owner.lifecycle === lifecycleGeneration
      && owner.load === loadGeneration
      && owner.projectId === getProjectId()
      && owner.chapter === state.chapter
      && owner.draftId === state.draftId
      && owner.editRevision === editRevision
  }

  function ownsCommandTarget(owner) {
    return !disposed
      && owner.lifecycle === lifecycleGeneration
      && owner.load === loadGeneration
      && owner.projectId === getProjectId()
      && owner.chapter === state.chapter
      && owner.draftId === state.draftId
  }

  function dirty() {
    return state.title !== state.lastSavedTitle || state.content !== state.lastSavedContent
  }

  function snapshot() {
    return { ...state, dirty: dirty() }
  }

  function emit() {
    const value = snapshot()
    if (state.chapter) {
      rememberChapterSnapshot(getProjectId(), value)
      rememberWritingLocation(getProjectId(), {
        currentChapter: state.chapter,
        currentDraftId: state.draftId,
        draftVersion: state.versionNumber,
        draftUpdatedAt: state.updatedAt,
      })
    }
    onChange(value)
  }

  async function refreshVersions(result) {
    try {
      await onVersionChanged(result)
    } catch {
      toast("操作已完成，但版本列表暂时未刷新", "warning")
    }
  }

  function syncElements() {
    if (elements.title && elements.title.value !== state.title) elements.title.value = state.title
    if (elements.editor && elements.editor.value !== state.content) elements.editor.value = state.content
    if (elements.editor) elements.editor.readOnly = state.readonly
    if (elements.editor && pendingCursorRestore) {
      const offset = Math.min(Math.max(0, state.cursorOffset), elements.editor.value.length)
      elements.editor.setSelectionRange(offset, offset)
      pendingCursorRestore = false
    }
  }

  function saveBackup() {
    const projectId = getProjectId()
    if (!projectId || !state.chapter) return
    try {
      localStorage.setItem(backupKey(projectId, state.chapter), JSON.stringify({
        project_id: projectId,
        chapter_index: state.chapter,
        draft_id: state.draftId,
        title: state.title,
        content: state.content,
        timestamp: Date.now(),
      }))
    } catch {
      // Storage exhaustion must not block typing.
    }
  }

  function clearBackup() {
    const projectId = getProjectId()
    if (!projectId || !state.chapter) return
    try { localStorage.removeItem(backupKey(projectId, state.chapter)) } catch { /* noop */ }
  }

  function restoreSession(projectId, chapter) {
    const saved = readChapterSnapshot(projectId, chapter)
    if (!saved?.dirty || saved.projectId !== projectId) return false
    // A session snapshot may only overlay the same working draft. This avoids
    // applying project/chapter-local text to a newly selected historical draft.
    if (saved.draftId && state.draftId && saved.draftId !== state.draftId) return false
    if (!saved.draftId && state.draftId) {
      if (saved.title) state.title = saved.title
      state.content = saved.content
      return true
    }
    Object.assign(state, saved, { chapter })
    return true
  }

  function restoreCursor(projectId, chapter, draftIdentity) {
    const pointer = readWritingPointer(projectId)
    if (
      pointer?.chapter !== Number(chapter)
      || !pointer.draftId
      || pointer.draftId !== draftIdentity.id
      || pointer.draftVersion !== draftIdentity.version
      || pointer.draftUpdatedAt !== draftIdentity.updatedAt
    ) return false
    state.cursorOffset = Math.min(pointer.cursorOffset, state.content.length)
    pendingCursorRestore = true
    return true
  }

  function restoreBackup(projectId, chapter) {
    try {
      const raw = localStorage.getItem(backupKey(projectId, chapter))
      if (!raw) return false
      const saved = JSON.parse(raw)
      if (saved.project_id && saved.project_id !== projectId) return false
      if (Number(saved.chapter_index) !== Number(chapter)) return false
      if (saved.content === state.content && String(saved.title || "") === state.title) return false
      if (!confirm(`检测到本地暂存的第 ${chapter} 章内容，是否恢复？`)) return false
      state.content = String(saved.content || "")
      state.title = String(saved.title || "")
      editRevision += 1
      return true
    } catch {
      return false
    }
  }

  function applyDraft(draft = {}, options = {}) {
    state.draftId = draft.id || null
    state.versionNumber = options.versionNumber ?? draft.version_number ?? null
    state.updatedAt = draft.updated_at || null
    state.status = draft.status || "draft"
    state.readonly = ["candidate", "deprecated"].includes(state.status) || options.isReadonly === true
    state.title = String(draft.title || "")
    state.content = String(draft.content || "")
    state.lastSavedTitle = state.title
    state.lastSavedContent = state.content
    state.restoreSourceVersion = options.restoreSourceVersion ?? null
    state.restoreExpectedVersion = options.restoreExpectedVersion ?? null
    state.restoreExpectedUpdatedAt = options.restoreExpectedUpdatedAt || null
    state.provenanceJson = draft.provenance_json || null
    state.saveError = null
  }

  function applyAutosaveMetadata(draft = {}, savedContent, savedTitle) {
    state.draftId = draft.id || state.draftId
    state.versionNumber = draft.version_number ?? state.versionNumber
    state.updatedAt = draft.updated_at || state.updatedAt
    state.status = draft.status || state.status
    state.readonly = ["candidate", "deprecated"].includes(state.status)
    state.provenanceJson = draft.provenance_json || null
    state.lastSavedContent = savedContent
    state.lastSavedTitle = savedTitle
  }

  async function loadChapter(chapter, options = {}) {
    const generation = ++loadGeneration
    const lifecycle = lifecycleGeneration
    const projectId = getProjectId()
    state.chapter = Number(chapter) || null
    state.cursorOffset = 0
    state.loadError = null
    if (!projectId || !state.chapter) {
      emit()
      return false
    }
    try {
      let draft = null
      if (options.draftId) {
        try {
          draft = await api.writing.get(options.draftId, projectId)
        } catch (error) {
          if (options.allowMissingPointerFallback !== true || Number(error?.status) !== 404) throw error
          clearWritingPointerDraft(projectId)
          const history = await api.writing.getVersionHistory(state.chapter, projectId)
          const latest = (history?.versions || []).find(activeVersion)
          if (latest) draft = await api.writing.get(latest.id, projectId)
        }
      } else {
        const history = await api.writing.getVersionHistory(state.chapter, projectId)
        if (generation !== loadGeneration || lifecycle !== lifecycleGeneration || projectId !== getProjectId()) return false
        const latest = (history?.versions || []).find(activeVersion)
        if (latest) draft = await api.writing.get(latest.id, projectId)
      }
      if (generation !== loadGeneration || lifecycle !== lifecycleGeneration || projectId !== getProjectId()) return false
      if (draft?.novel_id && draft.novel_id !== projectId) throw new Error("工作稿项目不匹配")
      if (draft) applyDraft(draft, options)
      else applyDraft({ title: `第 ${state.chapter} 章`, content: "", status: "draft" })
      const loadedDraftIdentity = {
        id: state.draftId,
        version: state.versionNumber,
        updatedAt: state.updatedAt,
      }
      if (!options.draftId && !restoreSession(projectId, state.chapter)) restoreBackup(projectId, state.chapter)
      restoreCursor(projectId, state.chapter, loadedDraftIdentity)
      syncElements()
      emit()
      return true
    } catch (err) {
      if (generation !== loadGeneration || lifecycle !== lifecycleGeneration || projectId !== getProjectId()) return false
      state.loadError = err?.message || "加载工作稿失败"
      toast(state.loadError, "error")
      emit()
      return false
    }
  }

  function scheduleAutosave() {
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => {
      autosaveTimer = null
      autosave()
    }, 3000)
  }

  function handleInput() {
    if (state.readonly) return
    state.title = elements.title?.value ?? state.title
    state.content = elements.editor?.value ?? state.content
    editRevision += 1
    saveBackup()
    emit()
    scheduleAutosave()
  }

  function updateCursor() {
    if (!elements.editor || document.activeElement !== elements.editor) return
    state.cursorOffset = elements.editor.selectionStart || 0
    emit()
  }

  function attach({ title, editor }) {
    detach()
    elements = { title: title || null, editor: editor || null }
    syncElements()
    elements.title?.addEventListener("input", handleInput)
    elements.editor?.addEventListener("input", handleInput)
    elements.editor?.addEventListener("click", updateCursor)
    keyupHandler = () => {
      if (cursorTimer) clearTimeout(cursorTimer)
      cursorTimer = setTimeout(updateCursor, 150)
    }
    elements.editor?.addEventListener("keyup", keyupHandler)
    selectionHandler = updateCursor
    document.addEventListener("selectionchange", selectionHandler)
  }

  function detach() {
    if (elements.title) elements.title.removeEventListener("input", handleInput)
    if (elements.editor) {
      elements.editor.removeEventListener("input", handleInput)
      elements.editor.removeEventListener("click", updateCursor)
      if (keyupHandler) elements.editor.removeEventListener("keyup", keyupHandler)
    }
    if (selectionHandler) document.removeEventListener("selectionchange", selectionHandler)
    selectionHandler = null
    keyupHandler = null
    if (cursorTimer) clearTimeout(cursorTimer)
    cursorTimer = null
    elements = { title: null, editor: null }
  }

  async function autosave({ successMessage = "已保存到工作稿", createIfMissing = false } = {}) {
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = null
    if (state.saving && !savePromise) {
      scheduleAutosave()
      return null
    }
    if (savePromise) {
      await savePromise
      if (dirty()) return autosave({ successMessage, createIfMissing })
      return null
    }
    if (!state.chapter || state.readonly || state.status === "candidate") return null
    if (!state.draftId && !createIfMissing) return null
    if (!dirty()) return null
    if (substantiveWritingText(state.content) === substantiveWritingText(state.lastSavedContent)) {
      emit()
      return null
    }
    const projectId = getProjectId()
    const chapter = state.chapter
    const lifecycle = lifecycleGeneration
    const requestRevision = editRevision
    const savedContent = state.content
    const savedTitle = state.title
    state.saving = true
    emit()
    const request = state.draftId
      ? api.writing.autosave(state.draftId, {
        title: savedTitle,
        content: savedContent,
        expected_version: state.versionNumber,
        expected_updated_at: state.updatedAt,
      }, projectId)
      : api.writing.autosaveDraftOnly({
        novel_id: projectId,
        chapter_index: chapter,
        title: savedTitle || `第 ${chapter} 章`,
        content: savedContent,
      })
    savePromise = request.then((result) => {
      if (disposed || lifecycle !== lifecycleGeneration || projectId !== getProjectId() || chapter !== state.chapter) return null
      const changedDraft = Boolean(result?.id && result.id !== state.draftId)
      const hasNewerEdits = requestRevision !== editRevision
      const keepsLocalFormatting = (
        changedDraft
        && result?.status === "published"
        && substantiveWritingText(savedContent) === substantiveWritingText(result?.content)
        && (savedContent !== String(result?.content || "") || savedTitle !== String(result?.title || ""))
      )
      if (hasNewerEdits) {
        applyAutosaveMetadata(result, savedContent, savedTitle)
      } else {
        applyDraft({ title: savedTitle, content: savedContent, ...result }, { isReadonly: false })
        if (keepsLocalFormatting) {
          state.content = savedContent
          state.title = savedTitle
        }
        syncElements()
      }
      if (hasNewerEdits || keepsLocalFormatting) saveBackup()
      else clearBackup()
      state.saveError = null
      emit()
      if (keepsLocalFormatting && !hasNewerEdits) {
        toast("已回到上一版；排版或标题修改仅保存在本地", "info")
      } else if (!hasNewerEdits) {
        toast(successMessage, "success")
      }
      if (changedDraft) return refreshVersions(result).then(() => result)
      return result
    }).catch((err) => {
      if (lifecycle === lifecycleGeneration && projectId === getProjectId()) {
        state.saveError = err?.message || "保存失败，已保留本地备份"
        toast(state.saveError, "error")
      }
      return null
    }).finally(() => {
      if (lifecycle === lifecycleGeneration) {
        state.saving = false
        savePromise = null
        emit()
      }
    })
    return savePromise
  }

  async function checkpoint() {
    if (!state.draftId || state.readonly || state.saving) return null
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = null
    const owner = captureCommandOwner()
    let force = false
    if (state.provenanceJson?.version_origin !== "auto"
      && substantiveWritingText(state.content) === substantiveWritingText(state.lastSavedContent)) {
      force = await confirmDialog("正文没有实质变化。仍要强制保存一个新版本吗？", "保存新版本")
      if (!force) {
        if (dirty()) scheduleAutosave()
        return null
      }
    }
    if (!ownsCommand(owner)) {
      if (!disposed && dirty()) scheduleAutosave()
      return null
    }
    state.saving = true
    emit()
    try {
      const result = await api.writing.checkpoint(owner.draftId, {
        title: owner.title,
        content: owner.content,
        expected_version: owner.versionNumber,
        expected_updated_at: owner.updatedAt,
        force,
      }, owner.projectId)
      if (!ownsCommandTarget(owner)) return null
      const hasNewerEdits = owner.editRevision !== editRevision
      if (hasNewerEdits) {
        applyAutosaveMetadata(result, owner.content, owner.title)
        state.saveError = null
      }
      else {
        applyDraft(result, { isReadonly: false })
        clearBackup()
        syncElements()
      }
      if (hasNewerEdits) saveBackup()
      emit()
      toast(hasNewerEdits ? "已保存为新版本；之后的输入仍待保存" : "已保存为新版本", "success")
      await refreshVersions(result)
      return result
    } catch (err) {
      if (!ownsCommandTarget(owner)) return null
      toast(err?.message || "保存新版本失败", "error")
      return null
    } finally {
      if (!disposed && owner.lifecycle === lifecycleGeneration) {
        state.saving = false
        emit()
        if (dirty()) scheduleAutosave()
      }
    }
  }

  async function discardChanges() {
    if (!state.draftId || state.readonly || state.status !== "draft" || state.saving) return null
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = null
    const owner = captureCommandOwner()
    if (!(await confirmDialog("放弃当前未发布更改并回到上一版？", "放弃更改"))) {
      if (dirty()) scheduleAutosave()
      return null
    }
    if (!ownsCommand(owner)) {
      if (!disposed && dirty()) scheduleAutosave()
      return null
    }
    state.saving = true
    emit()
    try {
      const result = await api.writing.discard(owner.draftId, owner.projectId, {
        expected_version: owner.versionNumber,
        expected_updated_at: owner.updatedAt,
      })
      if (!ownsCommandTarget(owner)) return null
      const hasNewerEdits = owner.editRevision !== editRevision
      if (hasNewerEdits) {
        applyAutosaveMetadata(result, result.content, result.title)
        state.saveError = null
        saveBackup()
      } else {
        applyDraft(result, { isReadonly: false })
        clearBackup()
        syncElements()
      }
      emit()
      toast(hasNewerEdits ? "已回到上一版；之后的输入仍待保存" : "已回到上一版", "success")
      await refreshVersions(result)
      return result
    } catch (err) {
      if (!ownsCommandTarget(owner)) return null
      toast(err?.message || "放弃更改失败", "error")
      return null
    } finally {
      if (!disposed && owner.lifecycle === lifecycleGeneration) {
        state.saving = false
        emit()
        if (dirty()) scheduleAutosave()
      }
    }
  }

  async function adoptCandidate() {
    if (state.status !== "candidate" || !state.draftId) return null
    const owner = captureCommandOwner()
    if (!confirm("采用后，这份建议会成为新的未发布工作稿。是否继续？")) return null
    if (!ownsCommand(owner)) return null
    try {
      const response = await api.writing.adoptDraftCandidate(owner.draftId, owner.projectId)
      if (!ownsCommand(owner)) return null
      const result = response?.draft || response
      applyDraft(result, { isReadonly: false })
      syncElements()
      emit()
      toast("已采用到工作稿", "success")
      return result
    } catch (err) {
      if (!ownsCommand(owner)) return null
      toast(err?.message || "采用到工作稿失败", "error")
      return null
    }
  }

  async function rejectCandidate() {
    if (state.status !== "candidate" || !state.draftId) return false
    const owner = captureCommandOwner()
    if (!confirm("拒绝后建议会保留在版本历史中。是否继续？")) return false
    if (!ownsCommand(owner)) return false
    try {
      await api.writing.deleteDraft(owner.draftId, owner.projectId)
      if (!ownsCommand(owner)) return false
      toast("已拒绝 AI 建议", "success")
      return true
    } catch (err) {
      if (!ownsCommand(owner)) return false
      toast(err?.message || "拒绝建议失败", "error")
      return false
    }
  }

  function insertText(text) {
    if (!elements.editor || state.readonly || !text) return
    const start = elements.editor.selectionStart || 0
    const end = elements.editor.selectionEnd || start
    elements.editor.setRangeText(text, start, end, "end")
    handleInput()
    elements.editor.focus()
  }

  function selectRange(start, end = start) {
    if (!elements.editor || !Number.isFinite(Number(start))) return false
    const safeStart = Math.max(0, Math.min(state.content.length, Number(start)))
    const safeEnd = Math.max(safeStart, Math.min(state.content.length, Number(end)))
    elements.editor.focus()
    elements.editor.setSelectionRange(safeStart, safeEnd)
    state.cursorOffset = safeStart
    emit()
    return true
  }

  function persist() {
    if (elements.title) state.title = elements.title.value
    if (elements.editor) state.content = elements.editor.value
    if (dirty()) saveBackup()
    emit()
  }

  function dispose() {
    persist()
    disposed = true
    lifecycleGeneration += 1
    loadGeneration += 1
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = null
    detach()
  }

  emit()
  return {
    attach,
    detach,
    loadChapter,
    autosave,
    checkpoint,
    discardChanges,
    adoptCandidate,
    rejectCandidate,
    insertText,
    selectRange,
    persist,
    dispose,
    snapshot,
    getContent: () => state.content,
    getLoadedContent: () => state.lastSavedContent,
    getTitle: () => state.title,
    getDraftId: () => state.draftId,
    getStatus: () => state.status,
    getProvenance: () => state.provenanceJson || {},
    getCursorOffset: () => state.cursorOffset,
    isReadonly: () => state.readonly,
    setState: (patch = {}) => {
      Object.assign(state, patch)
      syncElements()
      emit()
    },
    hasUnsavedChanges: dirty,
  }
}
