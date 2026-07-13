/**
 * 写作台编辑器子模块
 *
 * 负责：
 * 1. 章节正文/标题的加载与状态管理
 * 2. 编辑器 HTML 渲染与事件绑定
 * 3. 自动保存、字数统计、光标所在 Scene 检测
 *
 * 不直接操作全局状态，所有跨模块通信通过构造函数传入的回调完成。
 */

import { findCurrentScene as locateCurrentScene } from "../../shared/sceneLocator.js"
import { writingAssetDisplay } from "../../shared/assetDisplayState.js"
import { confirmAsync } from "../../shared/confirmAsync.js"

export function substantiveWritingText(text) {
  return String(text || "").replace(/\s/gu, "")
}

/**
 * @param {Object} deps
 * @param {Object} deps.state - orchestrator 持有的共享状态（含 currentProjectId、_scenes、_chapters、_focusMode 等）
 * @param {Object} deps.api
 * @param {Function} deps.toast
 * @param {Function} [deps.onWordcountUpdate] - (stats) => void，stats: { chapterWords, todayWords, saveState }
 * @param {Function} [deps.onSaveStatusChange] - (text) => void
 * @param {Function} [deps.onSceneChange] - (sceneId) => void
 * @param {Function} [deps.onDraftAdopted] - (draft) => void
 */
export function createEditor({ state, api, toast, onWordcountUpdate, onSaveStatusChange, onSceneChange, onDraftAdopted, onVersionChanged }) {
  const editor = {
    // 当前编辑器状态
    _currentChapter: null,
    _currentDraftId: null,
    _currentContent: null,
    _currentTitle: null,
    _currentVersionNumber: null,
    _currentUpdatedAt: null,
    _lastSavedContent: null,
    _isReadonly: false,
    _restoreSourceVersion: null,
    _restoreExpectedVersion: null,
    _restoreExpectedUpdatedAt: null,
    _lastPublishStatus: null,
    _draftStatus: "draft",
    _currentProvenanceJson: null,

    // 自动保存与光标防抖
    _autoSaveTimer: null,
    _autoSaving: false,
    _currentSavePromise: null,
    _editRevision: 0,
    _cursorDebounceTimer: null,
    _cursorOffset: 0,
    _boundSelectionChange: null,
    _lastSceneId: null,
  }

  // ============================================================
  // 公共 API
  // ============================================================

  /**
   * 加载章节内容
   * @param {number} chapterIndex
   * @param {Object} [options={}]
   * @param {string} [options.draftId]
   * @param {number} [options.versionNumber]
   * @param {boolean} [options.isReadonly]
   * @param {number} [options.restoreSourceVersion]
   * @param {number} [options.restoreExpectedVersion]
   * @param {string} [options.restoreExpectedUpdatedAt]
   */
  async function loadChapter(chapterIndex, options = {}) {
    editor._currentChapter = chapterIndex
    editor._cursorOffset = 0
    editor._lastSceneId = null

    if (options.draftId) {
      await _loadDraft(options.draftId, options)
    } else {
      await _loadLatestDraft(chapterIndex)
    }

    _notifyWordcountUpdate()
  }

  function render() {
    return _renderEditor()
  }

  function bindEvents(container) {
    const titleInput = container.querySelector("#writing-title-input")
    if (titleInput) {
      titleInput.oninput = () => {
        editor._editRevision += 1
        editor._currentTitle = titleInput.value
        _saveBackup(getContent(), titleInput.value)
        _scheduleAutoSave()
      }
    }

    const editorEl = container.querySelector("#writing-editor")
    if (editorEl) {
      _clearCursorDebounceTimer()
      editorEl.oninput = () => {
        editor._editRevision += 1
        editor._currentContent = editorEl.value
        _saveBackup(editorEl.value, getTitle())
        updateWordcount()
        _scheduleAutoSave()
      }
      editorEl.onclick = null
      editorEl.onkeyup = null
      if (editor._boundSelectionChange) {
        document.removeEventListener("selectionchange", editor._boundSelectionChange)
      }

      const updateCursorScene = () => {
        if (document.activeElement !== editorEl) return
        editor._cursorOffset = editorEl.selectionStart || 0
        const scene = _findCurrentScene()
        const sceneId = scene?.id || null
        if (onSceneChange && sceneId !== editor._lastSceneId) {
          editor._lastSceneId = sceneId
          onSceneChange(sceneId)
        }
      }

      editor._boundSelectionChange = updateCursorScene
      editorEl.onclick = updateCursorScene
      document.addEventListener("selectionchange", updateCursorScene)
      editorEl.onkeyup = () => {
        _clearCursorDebounceTimer()
        editor._cursorDebounceTimer = setTimeout(updateCursorScene, 150)
      }
    }

    container.querySelectorAll('[data-action="adopt-draft-candidate"]').forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true
        try {
          await adoptDraftCandidate()
        } finally {
          if (editor._draftStatus === "candidate") btn.disabled = false
        }
      })
    })
  }

  async function adoptDraftCandidate() {
    if (!editor._currentDraftId || editor._draftStatus !== "candidate") return null
    try {
      const response = await api.writing.adoptDraftCandidate(editor._currentDraftId, state.currentProjectId)
      const draft = response?.draft || response
      _applyDraft(draft, { isReadonly: false })
      toast("已采用到工作稿", "success")
      _notifyWordcountUpdate()
      if (onDraftAdopted) await onDraftAdopted(draft)
      return draft
    } catch (err) {
      toast(err.message || "采用到工作稿失败", "error")
      return null
    }
  }

  async function autosave() {
    _clearAutoSaveTimer()
    if (editor._currentSavePromise) {
      const pendingSave = editor._currentSavePromise
      await pendingSave
      if (editor._currentSavePromise === pendingSave) {
        editor._currentSavePromise = null
      }
      return autosave()
    }
    if (!editor._currentChapter) return
    if (editor._isReadonly || editor._draftStatus === "candidate") return

    // 无 draftId 时无法自动保存；由 orchestrator 决定是否需要创建新草稿
    if (!editor._currentDraftId) return

    const content = getContent()
    const title = getTitle()
    const requestRevision = editor._editRevision
    if (substantiveWritingText(content) === substantiveWritingText(editor._lastSavedContent)) {
      _updateSaveStatus()
      return
    }

    const savePromise = (async () => {
      try {
        editor._autoSaving = true
        const result = await api.writing.autosave(
          editor._currentDraftId,
          {
            title,
            content,
            expected_version: editor._currentVersionNumber,
            expected_updated_at: editor._currentUpdatedAt,
          },
          state.currentProjectId,
        )
        const changedDraft = result.id && result.id !== editor._currentDraftId
        const hasNewerEdits = editor._editRevision !== requestRevision
        const keepsLocalFormatting = (
          changedDraft
          && result.status === "published"
          && substantiveWritingText(content) === substantiveWritingText(result.content)
          && (content !== (result.content || "") || title !== (result.title || ""))
        )
        if (hasNewerEdits) {
          _applyAutosaveMetadata(result, content)
        } else {
          _applyDraft(result, { isReadonly: false })
        }
        if (keepsLocalFormatting && !hasNewerEdits) {
          editor._currentContent = content
          editor._currentTitle = title
        }
        state._currentDraftId = editor._currentDraftId
        editor._lastPublishStatus = null
        if (hasNewerEdits) {
          _saveBackup(getContent(), getTitle())
        } else if (keepsLocalFormatting) {
          _saveBackup(content, title)
          toast("已回到上一版；排版或标题修改仅保存在本地", "info")
        } else {
          _saveBackup(null, null)
          toast("已暂存", "success")
        }
        if (changedDraft && onVersionChanged) await onVersionChanged(result)
      } catch (err) {
        _saveBackup(content, title)
        if (err.status === 409) {
          toast("该章节已被其他会话更新，请刷新后重新编辑", "error")
        } else {
          toast(err.message || "暂存失败", "error")
        }
      } finally {
        editor._autoSaving = false
        _updateSaveStatus()
      }
    })()

    editor._currentSavePromise = savePromise
    try {
      await savePromise
    } finally {
      editor._currentSavePromise = null
    }
  }

  async function checkpoint() {
    if (!editor._currentDraftId || editor._isReadonly || editor._draftStatus === "candidate") return null
    const content = getContent()
    const title = getTitle()
    const origin = editor._currentProvenanceJson?.version_origin
    let force = false
    if (origin !== "auto" && substantiveWritingText(content) === substantiveWritingText(editor._lastSavedContent)) {
      force = await confirmAsync("正文没有实质变化。仍要强制保存一个新版本吗？", "保存新版本")
      if (!force) return null
    }
    try {
      const result = await api.writing.checkpoint(editor._currentDraftId, {
        title,
        content,
        expected_version: editor._currentVersionNumber,
        expected_updated_at: editor._currentUpdatedAt,
        force,
      }, state.currentProjectId)
      _applyDraft(result, { isReadonly: false })
      state._currentDraftId = editor._currentDraftId
      _saveBackup(null, null)
      toast("已保存为新版本", "success")
      if (onVersionChanged) await onVersionChanged(result)
      return result
    } catch (err) {
      toast(err.message || "保存新版本失败", "error")
      return null
    }
  }

  async function discardChanges() {
    if (!editor._currentDraftId || editor._draftStatus !== "draft") return null
    const confirmed = await confirmAsync("放弃当前未发布更改并回到上一版？", "放弃更改")
    if (!confirmed) return null
    try {
      const result = await api.writing.discard(editor._currentDraftId, state.currentProjectId, {
        expected_version: editor._currentVersionNumber,
        expected_updated_at: editor._currentUpdatedAt,
      })
      _applyDraft(result, { isReadonly: false })
      state._currentDraftId = editor._currentDraftId
      _saveBackup(null, null)
      toast("已回到上一版", "success")
      if (onVersionChanged) await onVersionChanged(result)
      return result
    } catch (err) {
      toast(err.message || "放弃更改失败", "error")
      return null
    }
  }

  function getContent() {
    const editorEl = typeof document !== "undefined" ? document.getElementById("writing-editor") : null
    return editorEl ? editorEl.value : (editor._currentContent || "")
  }

  function getTitle() {
    const titleInput = typeof document !== "undefined" ? document.getElementById("writing-title-input") : null
    return titleInput ? titleInput.value.trim() : (editor._currentTitle || "")
  }

  function getCurrentSceneId() {
    const scene = _findCurrentScene()
    return scene?.id || null
  }

  function setReadonly(readonly) {
    editor._isReadonly = ["candidate", "deprecated"].includes(editor._draftStatus) || Boolean(readonly)
  }

  function setPublishStatus(text) {
    editor._lastPublishStatus = text || null
    _updateSaveStatus()
  }

  function insertTextAtCursor(text) {
    if (!text) return
    const el = document.getElementById("writing-editor")
    if (!el || editor._isReadonly) return
    const start = el.selectionStart || 0
    const end = el.selectionEnd || start
    el.value = `${el.value.slice(0, start)}${text}${el.value.slice(end)}`
    el.selectionStart = el.selectionEnd = start + text.length
    editor._editRevision += 1
    editor._currentContent = el.value
    _saveBackup(el.value, getTitle())
    updateWordcount()
    _scheduleAutoSave()
    el.focus()
  }

  function getCursorOffset() {
    const el = document.getElementById("writing-editor")
    return el ? (el.selectionStart || 0) : editor._cursorOffset
  }

  function getDraftId() {
    return editor._currentDraftId
  }

  function getVersionNumber() {
    return editor._currentVersionNumber
  }

  function getUpdatedAt() {
    return editor._currentUpdatedAt
  }

  function getRestoreSourceVersion() {
    return editor._restoreSourceVersion
  }

  function getRestoreExpectedVersion() {
    return editor._restoreExpectedVersion
  }

  function getRestoreExpectedUpdatedAt() {
    return editor._restoreExpectedUpdatedAt
  }

  function getDraftStatus() {
    return editor._draftStatus
  }

  function isReadonly() {
    return editor._isReadonly
  }

  function saveBackup(content, title) {
    _saveBackup(content, title)
  }

  function setState(patch = {}) {
    if (patch.draftId !== undefined) editor._currentDraftId = patch.draftId
    if (patch.versionNumber !== undefined) editor._currentVersionNumber = patch.versionNumber
    if (patch.updatedAt !== undefined) editor._currentUpdatedAt = patch.updatedAt
    if (patch.content !== undefined) editor._currentContent = patch.content
    if (patch.title !== undefined) editor._currentTitle = patch.title
    if (patch.isReadonly !== undefined) editor._isReadonly = Boolean(patch.isReadonly)
    if (patch.restoreSourceVersion !== undefined) editor._restoreSourceVersion = patch.restoreSourceVersion || null
    if (patch.restoreExpectedVersion !== undefined) editor._restoreExpectedVersion = patch.restoreExpectedVersion || null
    if (patch.restoreExpectedUpdatedAt !== undefined) editor._restoreExpectedUpdatedAt = patch.restoreExpectedUpdatedAt || null
    if (patch.lastPublishStatus !== undefined) editor._lastPublishStatus = patch.lastPublishStatus || null
    if (patch.draftStatus !== undefined) editor._draftStatus = patch.draftStatus || "draft"
    if (patch.lastSavedContent !== undefined) editor._lastSavedContent = patch.lastSavedContent
    if (patch.chapter !== undefined) editor._currentChapter = patch.chapter
    if (patch.provenanceJson !== undefined) editor._currentProvenanceJson = patch.provenanceJson || null
    if (["candidate", "deprecated"].includes(editor._draftStatus)) editor._isReadonly = true
    _notifyWordcountUpdate()
    _updateSaveStatus()
  }

  function updateWordcount() {
    const editorEl = typeof document !== "undefined" ? document.getElementById("writing-editor") : null
    const text = editorEl ? editorEl.value : (editor._currentContent || "")
    const chars = text.length
    const paragraphs = _paragraphCount(text)
    const readTime = _readTimeMinutes(chars)
    const dailyGoal = _getDailyGoal()
    const daily = _getDailyWordcount() + chars
    const dailyPercent = dailyGoal > 0 ? Math.min(100, (daily / dailyGoal) * 100) : 0
    const chapterGoal = _getChapterGoal()
    const chapterPercent = chapterGoal > 0 ? Math.min(100, Math.round((chars / chapterGoal) * 100)) : 0

    const setText = (id, value) => {
      const el = document.getElementById(id)
      if (el) el.textContent = value
    }
    setText("wc-chapter", chars.toLocaleString())
    setText("wc-paragraphs", String(paragraphs))
    setText("wc-readtime", String(readTime))
    setText("wc-daily", `${daily.toLocaleString()} / ${dailyGoal.toLocaleString()}`)

    const fill = document.getElementById("wc-goal-fill")
    if (fill) fill.style.width = `${dailyPercent}%`

    const chapterEl = document.getElementById("wc-chapter")
    if (chapterEl) {
      if (chapterPercent >= 100) chapterEl.style.color = "var(--success, #22c55e)"
      else if (chapterPercent >= 80) chapterEl.style.color = "var(--warning, #f59e0b)"
      else chapterEl.style.color = ""
    }

    _notifyWordcountUpdate()
    _updateSaveStatus()
  }

  function updateMeta(focusMode = false) {
    const versionInfo = document.getElementById("writing-version-info")
    const versionLabel = editor._currentVersionNumber ? `v${editor._currentVersionNumber}` : ""
    const readOnlyLabel = editor._isReadonly ? "（只读）" : ""
    const draftLabel = editor._currentDraftId
      ? writingAssetDisplay({ status: editor._draftStatus }).label
      : ""
    if (versionInfo) {
      versionInfo.textContent = [versionLabel, draftLabel, readOnlyLabel].filter(Boolean).join(" · ") || "未选择版本"
    }

    const chapterTitle = document.getElementById("writing-chapter-title")
    if (chapterTitle && editor._currentChapter !== null) {
      chapterTitle.textContent = `第 ${editor._currentChapter} 章`
    }

    const editorEl = document.getElementById("writing-editor")
    if (editorEl) {
      if (editor._currentContent !== null && editorEl.value !== editor._currentContent) {
        editorEl.value = editor._currentContent
      }
      editorEl.readOnly = editor._isReadonly
    }

    const titleInput = document.getElementById("writing-title-input")
    if (titleInput) {
      if (editor._currentTitle !== null && titleInput.value !== editor._currentTitle) {
        titleInput.value = editor._currentTitle
      }
      titleInput.readOnly = editor._isReadonly
    }

    const btnAutosave = document.getElementById("btn-autosave")
    if (btnAutosave) {
      btnAutosave.disabled = !(editor._currentChapter !== null && !editor._isReadonly)
      btnAutosave.textContent = editor._restoreSourceVersion ? "发布为新版本" : "暂存"
    }

    const btnPublish = document.getElementById("btn-publish")
    if (btnPublish) {
      btnPublish.disabled = !(editor._currentChapter !== null && !editor._isReadonly)
    }

    const buttonsContainer = document.getElementById("writing-editor-buttons")
    if (buttonsContainer) {
      const existingRestore = buttonsContainer.querySelector('[data-action="restore-from-version"]')
      if (editor._isReadonly && !["candidate", "deprecated"].includes(editor._draftStatus) && !existingRestore) {
        const restoreBtn = document.createElement("button")
        restoreBtn.className = "btn btn-primary"
        restoreBtn.setAttribute("data-action", "restore-from-version")
        restoreBtn.textContent = "基于此版本创建"
        buttonsContainer.insertBefore(restoreBtn, buttonsContainer.firstChild)
      } else if ((!editor._isReadonly || ["candidate", "deprecated"].includes(editor._draftStatus)) && existingRestore) {
        existingRestore.remove()
      }

      const existingDiscard = buttonsContainer.querySelector('[data-action="discard-writing-changes"]')
      const canDiscard = editor._draftStatus === "draft" && editor._currentVersionNumber > 1
      if (canDiscard && !existingDiscard) {
        const discardBtn = document.createElement("button")
        discardBtn.className = "btn btn-ghost"
        discardBtn.setAttribute("data-action", "discard-writing-changes")
        discardBtn.textContent = "放弃未发布更改"
        const publishBtn = buttonsContainer.querySelector('[data-action="publish"]')
        buttonsContainer.insertBefore(discardBtn, publishBtn)
      } else if (!canDiscard && existingDiscard) {
        existingDiscard.remove()
      }
    }

    const focusBtn = document.querySelector('[data-action="toggle-focus-mode"]')
    if (focusBtn) focusBtn.textContent = focusMode ? "退出专注" : "专注模式"

    editorEl?.classList.toggle("novel-editor--focus", focusMode)
  }

  function saveStatusText() {
    if (editor._autoSaving) return "保存中..."
    if (editor._isReadonly || editor._currentChapter === null) return ""
    const currentContent = getContent()
    if (currentContent !== undefined && currentContent !== editor._lastSavedContent) {
      if (substantiveWritingText(currentContent) === substantiveWritingText(editor._lastSavedContent)) return "仅本地修改"
      return "未保存"
    }
    if (editor._lastPublishStatus) return editor._lastPublishStatus
    if (_chapterStatus(editor._currentChapter) === "published") return "已发布"
    return editor._lastSavedContent !== null ? "已保存" : ""
  }

  function _saveBadgeClass(status) {
    if (status === "未保存" || status === "仅本地修改") return "writing-save-badge--unsaved"
    if (status === "已保存" || status === "发布成功" || status === "已发布") return "writing-save-badge--saved"
    return ""
  }

  function aiContinue() {
    const panel = document.getElementById("ai-suggestion-panel")
    if (!panel) return
    panel.classList.remove("hidden")
    panel.innerHTML = `
      <div class="writing-ai-loading">
        <span class="writing-spinner"></span>
        AI 正在分析上下文...
      </div>
    `
    setTimeout(() => {
      panel.classList.add("hidden")
      toast("AI 续写功能即将上线，敬请期待 🚀", "info")
    }, 2000)
  }

  function dispose() {
    _clearAutoSaveTimer()
    _clearCursorDebounceTimer()
    if (editor._boundSelectionChange) {
      document.removeEventListener("selectionchange", editor._boundSelectionChange)
      editor._boundSelectionChange = null
    }
  }

  // ============================================================
  // 渲染
  // ============================================================

  function _renderEditor() {
    const hasSelection = editor._currentChapter !== null
    const versionInfo = editor._currentVersionNumber ? `v${editor._currentVersionNumber}` : ""
    const readOnlyLabel = editor._isReadonly ? "（只读）" : ""
    const draftDisplay = writingAssetDisplay({ status: editor._draftStatus })
    const draftLabel = editor._currentDraftId ? `${versionInfo} · ${draftDisplay.label} ${readOnlyLabel}` : ""
    const saveStatus = saveStatusText()
    const disabledReason = hasSelection
      ? (editor._draftStatus === "candidate" ? "待处理建议只读，请先采用到工作稿" : "当前版本只读，需基于此版本创建后再编辑")
      : "请先选择章节"
    const focusMode = Boolean(state._focusMode)

    const saveBadgeClass = _saveBadgeClass(saveStatus)

    let html = `
      <div>
        <div class="writing-editor-header">
          <div class="writing-editor-title-group">
            <span id="writing-chapter-title" class="writing-editor-chapter-title">
              ${hasSelection ? `第 ${editor._currentChapter} 章` : "选择章节开始编辑"}
            </span>
            <span id="writing-version-info" class="writing-version-badge">${esc(draftLabel || "未选择版本")}</span>
            <span id="writing-save-status" class="writing-save-badge ${esc(saveBadgeClass)}">${esc(saveStatus)}</span>
          </div>
          <div class="writing-editor-buttons" id="writing-editor-buttons">
            ${editor._isReadonly && !["candidate", "deprecated"].includes(editor._draftStatus) ? `<button class="btn btn-primary" data-action="restore-from-version">基于此版本创建</button>` : ""}
            <button class="btn" data-action="autosave" id="btn-autosave" ${hasSelection && !editor._isReadonly ? "" : "disabled"} title="${hasSelection && !editor._isReadonly ? "暂存实质性正文修改" : esc(disabledReason)}">暂存</button>
            <button class="btn" data-action="checkpoint-version" id="btn-checkpoint-version" ${hasSelection && !editor._isReadonly ? "" : "disabled"} title="显式保存一个未发布版本">保存为新版本</button>
            ${editor._draftStatus === "draft" && editor._currentVersionNumber > 1 ? '<button class="btn btn-ghost" data-action="discard-writing-changes">放弃未发布更改</button>' : ""}
            <button class="btn btn-primary" data-action="publish" id="btn-publish" ${hasSelection && !editor._isReadonly ? "" : "disabled"} title="${hasSelection && !editor._isReadonly ? "发布当前章节版本" : esc(disabledReason)}">发布</button>
            <button class="btn btn-primary" data-action="run-conflict-check" id="btn-conflict-check" ${hasSelection && !editor._isReadonly ? "" : "disabled"}>剧情设定冲突检查</button>
            <button class="btn btn-sm btn-ghost" data-action="ai-continue" title="AI 续写：基于当前上下文生成后续内容">AI 续写</button>
            <button class="btn btn-sm btn-ghost" data-action="export-chapter" title="导出当前章节为 .txt">导出</button>
            <button class="btn btn-sm btn-ghost" data-action="toggle-outline-float" ${hasSelection ? "" : "disabled"} title="大纲浮窗 (Ctrl+Shift+O)">大纲</button>
            <button class="btn btn-sm" data-action="toggle-focus-mode" ${hasSelection ? "" : "disabled"} title="专注模式（隐藏两侧面板）">${focusMode ? "退出专注" : "专注模式"}</button>
          </div>
        </div>
    `

    if (hasSelection) {
      html += `
        <input id="writing-title-input" class="writing-title-input" type="text" value="${esc(editor._currentTitle || "")}" placeholder="章节标题" ${editor._isReadonly ? "readonly" : ""} />

        <textarea id="writing-editor" class="novel-editor ${focusMode ? "novel-editor--focus" : ""}"
          placeholder="在此书写正文..." ${editor._isReadonly ? "readonly" : ""}>${editor._currentContent ? esc(editor._currentContent) : ""}</textarea>
        ${_renderWordcountBar()}
        ${_renderPovCandidatePanel()}
        <div id="ai-suggestion-panel" class="ai-suggestion-panel hidden" aria-live="polite"></div>
      `
    } else {
      html += `
        <div class="writing-editor-empty">
          请从左侧选择章节
        </div>
      `
    }

    html += "</div>"
    return html
  }

  function _renderWordcountBar() {
    const chars = (editor._currentContent || "").length
    const paragraphs = _paragraphCount(editor._currentContent || "")
    const readTime = _readTimeMinutes(chars)
    const dailyGoal = _getDailyGoal()
    const daily = _getDailyWordcount() + chars
    const dailyPercent = dailyGoal > 0 ? Math.min(100, Math.round((daily / dailyGoal) * 100)) : 0
    const chapterGoal = _getChapterGoal()
    const chapterPercent = chapterGoal > 0 ? Math.min(100, Math.round((chars / chapterGoal) * 100)) : 0
    let chapterGoalColor = "var(--text-secondary)"
    if (chapterPercent >= 100) chapterGoalColor = "var(--success, #22c55e)"
    else if (chapterPercent >= 80) chapterGoalColor = "var(--warning, #f59e0b)"

    return `
      <div class="writing-wordcount-bar" id="writing-wordcount-bar">
        <div class="wc-bar-left">
          <span id="wc-chapter" style="color:${esc(chapterGoalColor)};">${esc(chars.toLocaleString())}</span> / ${esc(chapterGoal.toLocaleString())} 字
          <span class="wc-divider">|</span>
          <span id="wc-paragraphs">${esc(paragraphs)}</span> 段落
          <span class="wc-divider">|</span>
          预计阅读 <span id="wc-readtime">${esc(readTime)}</span> 分钟
        </div>
        <div class="wc-bar-right">
          <div class="wc-daily-goal">
            <span class="wc-goal-label">今日</span>
            <div class="wc-goal-progress">
              <div class="wc-goal-fill" id="wc-goal-fill" style="width:${esc(dailyPercent)}%"></div>
            </div>
            <span id="wc-daily">${esc(daily.toLocaleString())} / ${esc(dailyGoal.toLocaleString())}</span>
          </div>
        </div>
      </div>
    `
  }

  function _renderPovCandidatePanel() {
    const provenance = editor._currentProvenanceJson || {}
    const validation = provenance.pov_validation || null
    const povView = provenance.pov_view || null
    const isPov = provenance.generation_profile === "pov_character" || povView || validation
    if (!isPov) return ""

    const status = validation?.status || "not_applicable"
    const statusMeta = _povValidationStatusMeta(status)
    const isPending = editor._draftStatus === "candidate"
    const fields = [
      ["perception", "感知"],
      ["interpretation", "判断 / 误解"],
      ["inner_monologue", "内心"],
      ["true_intention", "真实意图"],
      ["action", "动作"],
      ["expression", "神态"],
      ["subtext", "潜台词"],
      ["unsaid", "未说出口"],
    ]
    const fieldHtml = povView
      ? fields
        .filter(([key]) => povView[key])
        .map(([key, label]) => `
          <div class="writing-pov-field">
            <div class="writing-pov-field-label">${esc(label)}</div>
            <div class="writing-pov-field-value">${esc(povView[key])}</div>
          </div>
        `)
        .join("")
      : `<div class="writing-pov-warnings">结构化角色视角解析失败，已保留原始建议文本。</div>`
    const dialogueHtml = _renderPovDialogueCandidates(povView?.dialogue_candidates)
    const warnings = Array.isArray(validation?.warnings) ? validation.warnings : []
    const findings = Array.isArray(validation?.findings) ? validation.findings : []
    const findingsHtml = findings.length
      ? `<ul class="writing-pov-findings">
          ${findings.slice(0, 5).map((item) => `
            <li>
              ${esc(item.field_path || item.rule || "pov_view")}：
              ${esc(item.generated_excerpt || "疑似越权片段")}
              <span class="writing-pov-field-label">（${esc(item.source_label || "已过滤来源")}）</span>
            </li>
          `).join("")}
        </ul>`
      : ""
    const warningsHtml = warnings.length
      ? `<div class="writing-pov-warnings">${warnings.map((item) => esc(item)).join(" · ")}</div>`
      : ""
    const adoptButton = isPending
      ? `<button class="btn btn-sm ${status === "failed" ? "btn-danger" : "btn-primary"}" data-action="adopt-draft-candidate" type="button">${status === "failed" ? "确认风险并采用到工作稿" : "采用到工作稿"}</button>`
      : ""

    return `
      <section class="pov-candidate-panel writing-pov-panel">
        <div class="writing-pov-header">
          <div>
            <div class="writing-pov-title">${isPending ? "角色视角建议预览" : "角色视角诊断"}</div>
            <div class="writing-pov-subtitle">${isPending ? "该建议尚未进入工作稿，请检查风险后决定是否采用。" : "当前内容已进入工作稿，以下诊断用于提示写作风险。"}</div>
          </div>
          <span class="writing-pov-status" style="color:${esc(statusMeta.color)};">${esc(statusMeta.label)}</span>
        </div>
        <div class="writing-pov-alert" style="border-color:${esc(statusMeta.color)};">
          ${esc(statusMeta.message)}
          ${adoptButton}
          ${findingsHtml}
          ${warningsHtml}
        </div>
        <div class="writing-pov-grid">
          ${fieldHtml}
        </div>
        ${dialogueHtml}
      </section>
    `
  }

  function _renderPovDialogueCandidates(candidates) {
    if (!Array.isArray(candidates) || candidates.length === 0) return ""
    return `
      <div class="writing-pov-dialogue">
        <div class="writing-pov-dialogue-label">台词建议</div>
        <div class="writing-pov-dialogue-list">
          ${candidates.slice(0, 4).map((item) => `
            <div class="writing-pov-dialogue-item">
              <div>${esc(item?.line || item || "")}</div>
              ${item?.tone || item?.subtext ? `<div class="writing-pov-dialogue-meta">${esc([item.tone, item.subtext].filter(Boolean).join(" · "))}</div>` : ""}
            </div>
          `).join("")}
        </div>
      </div>
    `
  }

  function _povValidationStatusMeta(status) {
    if (status === "failed") {
      return {
        color: "var(--danger, #ef4444)",
        label: "高风险",
        message: "该建议可能使用了 POV 角色当前不知道的信息。不会自动进入工作稿；采用前必须人工检查。",
      }
    }
    if (status === "warning") {
      return {
        color: "var(--warning, #f59e0b)",
        label: "有警告",
        message: "该建议存在角色视角风险提示，采用前建议检查。",
      }
    }
    if (status === "passed") {
      return {
        color: "var(--success, #22c55e)",
        label: "未发现明显越权",
        message: "deterministic 检查未发现明显越权；这不代表绝对无泄漏。",
      }
    }
    return {
      color: "var(--text-dim)",
      label: "未检查",
      message: "该建议没有可用的角色视角诊断结果。",
    }
  }

  // ============================================================
  // 加载与保存
  // ============================================================

  async function _loadLatestDraft(chapterIndex) {
    editor._currentDraftId = null
    editor._currentContent = ""
    editor._currentTitle = ""
    editor._currentVersionNumber = null
    editor._currentUpdatedAt = null
    editor._lastSavedContent = null
    editor._isReadonly = false
    editor._restoreSourceVersion = null
    editor._restoreExpectedVersion = null
    editor._restoreExpectedUpdatedAt = null
    editor._lastPublishStatus = null
    editor._currentProvenanceJson = null

    try {
      const history = await api.writing.getVersionHistory(chapterIndex, state.currentProjectId)
      const versions = history.versions || []
      const latest = versions.find((version) => version.display_state
        ? version.display_state === "active"
        : !["candidate", "deprecated"].includes(version.status))
      if (latest) {
        const draftData = await api.writing.get(latest.id, state.currentProjectId)
        _applyDraft(draftData, { isReadonly: false })
        await _maybeRestoreBackup(chapterIndex)
        return
      }
    } catch {
      // 失败时退回到空草稿，并尝试本地备份恢复
    }

    // 无历史版本时尝试恢复本地备份
    const restored = await _maybeRestoreBackup(chapterIndex)
    if (!restored) {
      editor._currentContent = ""
      editor._currentTitle = ""
    }
  }

  async function _loadDraft(draftId, options = {}) {
    try {
      const draftData = await api.writing.get(draftId, state.currentProjectId)
      _applyDraft(draftData, options)
    } catch (err) {
      toast("加载工作稿失败：" + (err.message || "未知错误"), "error")
      editor._currentContent = ""
      editor._currentTitle = ""
    }
  }

  function _applyDraft(draftData, options = {}) {
    editor._currentDraftId = draftData.id || null
    editor._currentTitle = draftData.title || ""
    editor._currentContent = draftData.content || ""
    editor._currentVersionNumber = options.versionNumber ?? draftData.version_number ?? null
    editor._currentUpdatedAt = draftData.updated_at || null
    editor._lastSavedContent = draftData.content || ""
    editor._isReadonly = ["candidate", "deprecated"].includes(draftData.status) || Boolean(options.isReadonly)
    editor._restoreSourceVersion = options.restoreSourceVersion || null
    editor._restoreExpectedVersion = options.restoreExpectedVersion || null
    editor._restoreExpectedUpdatedAt = options.restoreExpectedUpdatedAt || null
    editor._draftStatus = draftData.status || "draft"
    editor._lastPublishStatus = draftData.status === "published" ? "发布成功" : null
    editor._currentProvenanceJson = draftData.provenance_json || null
  }

  function _applyAutosaveMetadata(draftData, savedContent) {
    editor._currentDraftId = draftData.id || editor._currentDraftId
    editor._currentVersionNumber = draftData.version_number ?? editor._currentVersionNumber
    editor._currentUpdatedAt = draftData.updated_at || editor._currentUpdatedAt
    editor._lastSavedContent = savedContent
    editor._isReadonly = ["candidate", "deprecated"].includes(draftData.status)
    editor._draftStatus = draftData.status || editor._draftStatus
    editor._lastPublishStatus = draftData.status === "published" ? "发布成功" : null
    editor._currentProvenanceJson = draftData.provenance_json || null
  }

  async function _maybeRestoreBackup(chapterIndex) {
    const backup = _loadBackup(chapterIndex)
    if (!backup || (backup.content === undefined && backup.title === undefined)) return false
    if (backup.content === editor._currentContent && (backup.title || "") === editor._currentTitle) return false

    const age = ((Date.now() - (backup.timestamp || 0)) / 1000 / 60).toFixed(0)
    const confirmed = await new Promise((resolve) => {
      confirmAction(
        `检测到本地暂存的第 ${chapterIndex} 章内容（${age} 分钟前）。是否恢复？`,
        () => resolve(true),
        "恢复本地内容",
      )
      setTimeout(() => {
        const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
        if (cancelBtn) cancelBtn.onclick = () => resolve(false)
      }, 50)
    })

    if (!confirmed) return false
    editor._currentContent = backup.content
    editor._currentTitle = backup.title || ""
    editor._editRevision += 1
    return true
  }

  function _saveBackup(content, title) {
    if (!state.currentProjectId || !editor._currentChapter) return
    const key = `draft_backup_${state.currentProjectId}_${editor._currentChapter}`
    if (content === null) {
      localStorage.removeItem(key)
      return
    }
    try {
      localStorage.setItem(key, JSON.stringify({
        content,
        title: title || "",
        chapter_index: editor._currentChapter,
        timestamp: Date.now(),
      }))
    } catch {
      // localStorage 满了，忽略
    }
  }

  function _loadBackup(chapterIndex) {
    if (!state.currentProjectId) return null
    const key = `draft_backup_${state.currentProjectId}_${chapterIndex}`
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return null
      return JSON.parse(raw)
    } catch {
      return null
    }
  }

  function _scheduleAutoSave() {
    _clearAutoSaveTimer()
    _updateSaveStatus()
    editor._autoSaveTimer = setTimeout(() => {
      editor._autoSaveTimer = null
      autosave()
    }, 3000)
  }

  function _clearAutoSaveTimer() {
    if (editor._autoSaveTimer) {
      clearTimeout(editor._autoSaveTimer)
      editor._autoSaveTimer = null
    }
  }

  function _clearCursorDebounceTimer() {
    if (editor._cursorDebounceTimer) {
      clearTimeout(editor._cursorDebounceTimer)
      editor._cursorDebounceTimer = null
    }
  }

  function _updateSaveStatus() {
    const status = saveStatusText()
    if (typeof onSaveStatusChange === "function") onSaveStatusChange(status)
    const badge = typeof document !== "undefined" ? document.getElementById("writing-save-status") : null
    if (badge) {
      badge.textContent = status || ""
      badge.className = `writing-save-badge ${_saveBadgeClass(status)}`.trim()
    }
  }

  function _notifyWordcountUpdate() {
    if (typeof onWordcountUpdate !== "function") return
    const chars = (editor._currentContent || "").length
    onWordcountUpdate({
      chapterWords: chars,
      todayWords: _getDailyWordcount() + chars,
      saveState: _saveStateForDashboard(),
    })
  }

  function _saveStateForDashboard() {
    if (editor._autoSaving) return "saving"
    return ["未保存", "仅本地修改"].includes(saveStatusText()) ? "unsaved" : "saved"
  }

  // ============================================================
  // 字数与目标
  // ============================================================

  function _paragraphCount(text) {
    return (text || "").split(/\n{2,}/).filter((part) => part.trim()).length
  }

  function _readTimeMinutes(chars) {
    return Math.max(1, Math.ceil((chars || 0) / 300))
  }

  function _getDailyWordcount() {
    try {
      const today = new Date().toISOString().slice(0, 10)
      const key = `novel_daily_wc_${today}_${state.currentProjectId || "global"}`
      return Number(localStorage.getItem(key) || 0) || 0
    } catch {
      return 0
    }
  }

  function _getDailyGoal() {
    try {
      const projectPrefs = _loadAuthorPreferences()
      return Number(projectPrefs.dailyGoal || localStorage.getItem("novel_daily_goal") || 4000) || 4000
    } catch {
      return 4000
    }
  }

  function _getChapterGoal() {
    try {
      const projectPrefs = _loadAuthorPreferences()
      return Number(projectPrefs.chapterGoal || localStorage.getItem("novel_chapter_goal") || 3000) || 3000
    } catch {
      return 3000
    }
  }

  function _loadAuthorPreferences() {
    try {
      const raw = localStorage.getItem(`novel_author_preferences:${state.currentProjectId || "global"}`)
      return raw ? JSON.parse(raw) : {}
    } catch {
      return {}
    }
  }

  // ============================================================
  // Scene 检测
  // ============================================================

  function _findCurrentScene() {
    return locateCurrentScene({
      scenes: state._scenes,
      chapterIndex: editor._currentChapter,
      cursorOffset: editor._cursorOffset,
    })
  }

  function _chapterStatus(idx) {
    const chapters = state._chapters || {}
    const chapter = chapters[idx]
    if (!chapter) return "empty"
    if (chapter.published || chapter.status === "published") return "published"
    if ((chapter.draftCount || 0) > 0 || chapter.title) return "draft"
    return "empty"
  }

  // ============================================================
  // 公共 API 组装
  // ============================================================

  return {
    loadChapter,
    adoptDraftCandidate,
    render,
    bindEvents,
    autosave,
    checkpoint,
    discardChanges,
    getContent,
    getTitle,
    getCurrentSceneId,
    getCursorOffset,
    getDraftId,
    getVersionNumber,
    getUpdatedAt,
    getRestoreSourceVersion,
    getRestoreExpectedVersion,
    getRestoreExpectedUpdatedAt,
    getDraftStatus,
    isReadonly,
    insertTextAtCursor,
    saveBackup,
    setReadonly,
    setPublishStatus,
    setState,
    updateWordcount,
    updateMeta,
    saveStatusText,
    aiContinue,
    dispose,
  }
}
