/**
 * 手动工作台
 *
 * 左侧章节树 → 中间编辑器 → 版本管理。
 * 支持暂存、发布、版本切换、整章删除。
 */
import {
  bulkResultMessage,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  renderBulkToolbar,
  renderSelectionCell,
  runBulkAction,
  selectedItemsFrom,
  syncBulkSelectionUi,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../shared/bulkSelection.js"
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import { renderFixedProgress } from "../shared/progressRenderer.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
  sanitizeTaskErrorMessage,
} from "../shared/workflowProgress.js"
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { buildMapUrl } from "./mapRouteContext.js"
import { renderSceneCockpitPanel, saveSceneCockpitOrder } from "./sceneCockpitPanel.js"
import { showWritingConflictModal } from "./writingConflictModal.js"

const AUTO_EXTRACTION_STAGES = {
  scenes: {
    taskType: "scene_auto_extraction",
    label: "场景（scene）自动提取",
    initialStep: "scene_segmentation",
    initialMessage: "正在提取场景...",
  },
  world_objects: {
    taskType: "world_object_auto_extraction",
    label: "世界对象与别名/关系自动提取",
    initialStep: "entity_extraction",
    initialMessage: "正在提取世界对象与别名/关系...",
  },
  plot_structure: {
    taskType: "plot_structure_auto_extraction",
    label: "剧情线自动提取",
    initialStep: "structure_analysis",
    initialMessage: "正在提取剧情线...",
  },
}

const writingView = {
  _chapters: {},
  _chapterList: [],
  _chapterListLoadError: null,
  _currentChapter: null,
  _currentDraftId: null,
  _currentContent: null,
  _currentTitle: null,
  _currentVersionNumber: null,
  _currentUpdatedAt: null,
  _versions: [],
  _isReadonly: false,
  _restoreSourceVersion: null,
  _publishTaskId: null,
  _publishProgress: null,
  _lastPublishStatus: null,
  _loading: true,
  _publishTimer: null,
  _errorModalVisible: false,
  _outlineThreads: [],
  _outlineArc: null,
  _deepImportTaskId: null,
  _deepImportProgress: null,
  _deepImportTimer: null,
  _deepImportPollFailures: 0,
  _scenes: [],
  _currentSceneId: null,
  _cursorOffset: 0,
  _boundSelectionChange: null,
  _cursorDebounceTimer: null,
  _autoSaveTimer: null,
  _autoSaving: false,
  _currentSavePromise: null,
  _lastSavedContent: null,
  _beforeUnloadHandler: null,
  _sceneMapSummary: null,
  _sceneMapSummaryError: null,
  _sceneMapSummarySceneId: null,
  _sceneMapSummaryPendingSceneId: null,
  _sceneMapSummaryLoading: false,
  _conflictChecks: [],
  _latestConflictCheck: null,
  _checkingConflicts: false,
  _bulkSelections: {},
  _focusMode: false,
  _forceDesktopMode: false,
  _showBulkActions: false,

  _autoExtractionWorkflowTypes() {
    return Object.values(AUTO_EXTRACTION_STAGES).map((item) => item.taskType)
  },

  _stageConfig(stage) {
    return AUTO_EXTRACTION_STAGES[stage] || AUTO_EXTRACTION_STAGES.scenes
  },

  _stageFromWorkflowType(workflowType) {
    return Object.entries(AUTO_EXTRACTION_STAGES)
      .find(([, config]) => config.taskType === workflowType)?.[0] || "scenes"
  },

  // ============================================================
  // 生命周期
  // ============================================================

  async onEnter() {
    const saved = state.viewStates.writing?.projectId === state.currentProjectId
      ? state.viewStates.writing
      : null
    if (saved) {
      this._currentChapter = saved.currentChapter
      this._currentContent = saved.currentContent
      this._currentTitle = saved.currentTitle
      this._currentDraftId = saved.currentDraftId
      this._currentVersionNumber = saved.currentVersionNumber
      this._currentUpdatedAt = saved.currentUpdatedAt || null
      this._isReadonly = saved.isReadonly || false
      this._restoreSourceVersion = saved.restoreSourceVersion
    } else {
      this._currentChapter = null
      this._currentContent = null
      this._currentTitle = null
      this._currentDraftId = null
      this._currentVersionNumber = null
      this._currentUpdatedAt = null
      this._isReadonly = false
      this._restoreSourceVersion = null
    }
    this._chapters = {}
    this._chapterList = []
    this._chapterListLoadError = null
    this._versions = []
    this._publishTaskId = null
    this._publishProgress = null
    this._lastPublishStatus = null
    this._errorModalVisible = false
    this._loading = true
    this._publishTimer = null
    this._outlineThreads = []
    this._outlineArc = null
    this._autoSaveTimer = null
    this._autoSaving = false
    this._lastSavedContent = null
    this._sceneMapSummary = null
    this._sceneMapSummaryError = null
    this._sceneMapSummarySceneId = null
    this._sceneMapSummaryPendingSceneId = null
    this._sceneMapSummaryLoading = false
    this._conflictChecks = []
    this._latestConflictCheck = null
    this._checkingConflicts = false
    this._focusMode = this._getFocusDefault()
    this._forceDesktopMode = false

    // beforeunload 处理：有未保存内容时弹出确认
    this._beforeUnloadHandler = (e) => {
      const editor = document.getElementById("writing-editor")
      if (!editor || this._isReadonly) return
      const currentContent = editor.value
      if (currentContent !== this._lastSavedContent && currentContent.trim()) {
        e.preventDefault()
        e.returnValue = ""
      }
    }
    window.addEventListener("beforeunload", this._beforeUnloadHandler)

    if (!state.currentProjectId) {
      this._loading = false
      return
    }

    try {
      const draftData = await api.writing.listChapters(state.currentProjectId)
      const chapterSummaries = Array.isArray(draftData.chapters) ? draftData.chapters : []
      const draftIndices = chapterSummaries.length > 0
        ? chapterSummaries.map((item) => item.chapter_index)
        : (draftData.chapter_indices || [])
      for (const item of chapterSummaries) {
        const idx = item.chapter_index
        this._chapters[idx] = {
          title: item.title || "",
          draftCount: item.version_number || 0,
          wordcount: item.word_count || 0,
          word_count: item.word_count || 0,
          status: item.status || "draft",
          updated_at: item.updated_at || null,
        }
      }
      for (const idx of draftIndices) {
        if (!this._chapters[idx]) this._chapters[idx] = { draftCount: 0 }
      }
      this._chapterList = [...draftIndices].sort((a, b) => a - b)

      // 加载 Scene 数据
      try {
        this._scenes = await api.outline.listScenesOrdered(state.currentProjectId) || []
      } catch {
        this._scenes = []
      }
    } catch (err) {
      this._chapterList = []
      this._chapterListLoadError = err?.message || "加载失败"
      toast("章节列表加载失败，可稍后重试", "warning")
    }

    try {
      if (saved && saved.currentChapter) {
        await Promise.all([
          this._refreshVersions(saved.currentChapter),
          this._loadOutlineData(saved.currentChapter),
        ])
      }
    } finally {
      this._loading = false
    }

    // 恢复持久化的深度导入任务进度
    await this._recoverDeepImportTask()
  },

  async _recoverDeepImportTask() {
    let workflow = null
    try {
      const supportedTypes = new Set([
        "deep_import",
        ...this._autoExtractionWorkflowTypes(),
      ])
      workflow = recoverActiveWorkflows(state.currentProjectId)
        .find((item) => supportedTypes.has(item.workflowType))
    } catch {
      workflow = null
    }
    const taskId = workflow?.taskId
    if (!taskId) return
    try {
      const task = await api.tasks.get(taskId)
      if (!task || task.status === "done" || task.status === "failed" || task.status === "cancelled") {
        if (task) {
          const result = task.result || {}
          const workflowType = result.workflow_type || task.task_type || workflow?.workflowType || "deep_import"
          const stage = result.stage || workflow?.meta?.stage || this._stageFromWorkflowType(workflowType)
          const label = workflow?.label || this._stageConfig(stage).label
          const recoveryProgress = this._buildDeepImportProgressFromTask(
            task, result, task.status === "failed" ? 0 : 100, "",
          )
          if (this._hasDeepImportRecoveryPrompt(recoveryProgress)) {
            this._deepImportTaskId = taskId
            this._deepImportProgress = { ...recoveryProgress, workflowType, stage, label }
            await this._rerender()
            return
          }
          const isFailed = task.status === "failed"
          this._deepImportTaskId = taskId
          this._deepImportProgress = {
            ...recoveryProgress,
            workflowType,
            stage,
            label,
            phase: isFailed ? "failed" : task.status === "cancelled" ? "cancelled" : "done",
            step: result.current_step || "",
            message: result.message || (isFailed ? `${label}失败` : `${label}完成`),
            percent: isFailed ? 0 : 100,
            stepLabel: isFailed ? "失败" : task.status === "cancelled" ? "已取消" : "完成",
            degraded: result.degraded || false,
            degradedBatches: result.degraded_batches || [],
            phaseError: result.phase_error || result.error || task.error_message || "",
            phaseErrors: result.phase_errors || [],
            qualityStatus: result.quality_status || (result.degraded ? "partial" : "complete"),
            auditSummary: result.audit_summary || result.auditSummary || {},
            snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary || result.audit_summary || result.auditSummary || {},
          }
        }
        this._clearDeepImportWorkflow(taskId)
        await this._rerender()
        return
      }
      // 仍在运行中，恢复轮询
      this._deepImportTaskId = taskId
      const result = task.result || {}
      const workflowType = result.workflow_type || task.task_type || workflow?.workflowType || "deep_import"
      const stage = result.stage || workflow?.meta?.stage || this._stageFromWorkflowType(workflowType)
      this._deepImportProgress = {
        ...this._buildDeepImportProgressFromTask(task, result, result.phase === "running" ? 50 : 0, ""),
        workflowType,
        stage,
        label: workflow?.label || this._stageConfig(stage).label,
        phase: result.phase || "running",
        step: result.current_step || "",
        message: result.message || `${workflow?.label || this._stageConfig(stage).label}中...`,
        percent: result.phase === "running" ? 50 : 0,
        stepLabel: result.current_step ? `Phase: ${result.current_step}` : "恢复进度中...",
        degraded: result.degraded || false,
        degradedBatches: result.degraded_batches || [],
        phaseError: result.phase_error || result.error || task.error_message || "",
        phaseErrors: result.phase_errors || [],
        qualityStatus: result.quality_status || (result.degraded ? "partial" : "pending"),
        auditSummary: result.audit_summary || result.auditSummary || {},
        snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary || result.audit_summary || result.auditSummary || {},
      }
      await this._rerender()
      if (this._hasDeepImportRecoveryPrompt(this._deepImportProgress)) return
      this._startDeepImportPolling()
    } catch {
      this._clearDeepImportWorkflow(taskId)
      await this._rerender()
    }
  },

  async render() {
    if (this._loading) {
      return '<div class="empty-state"><p>章节数据加载中...</p></div>'
    }

    if (this._chapterListLoadError) {
      return `
        <div class="empty-state" role="alert">
          <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
          <p>章节列表加载失败</p>
          <p style="color:var(--text-dim);font-size:12px;">可稍后重试。错误信息：${esc(this._chapterListLoadError)}</p>
        </div>
        <div id="writing-deep-import-bar-container">${this._renderDeepImportBar()}</div>
      `
    }

    if (this._chapterList.length === 0) {
      setTimeout(() => this._bindEvents(), 0)
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128221;</div>
          <p>开始创作！</p>
          <p style="color:var(--text-dim);font-size:12px;">
            点击下方按钮创建第一个章节，开始写作。
          </p>
          <div style="margin-top:12px;">
            <button class="btn btn-primary" data-action="new-chapter">+ 新建章节</button>
          </div>
        </div>
        <div id="writing-deep-import-bar-container">${this._renderDeepImportBar()}</div>
      `
    }

    if (this._shouldRenderMobileQuickNote()) {
      setTimeout(() => this._bindEvents(), 0)
      return this._renderMobileQuickNote()
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">
        手动工作台 — 选择章节，撰写正文。
      </p>
      <div class="writing-workspace-layout">
        <div id="writing-tree-container">${this._renderSceneTree()}</div>
        <div id="writing-editor-container">${this._renderEditor()}</div>
        <div id="writing-panel-container">${this._renderScenePanel()}</div>
      </div>
      <div id="outline-float-panel" class="outline-float-panel hidden">
        <div class="outline-float-header">
          <span>大纲</span>
          <button class="btn-icon" data-action="close-outline-float" title="关闭大纲浮窗">&times;</button>
        </div>
        <div class="outline-float-body" id="outline-float-body">
          <p class="muted">加载中...</p>
        </div>
      </div>
      <div id="writing-publish-bar-container">${this._renderPublishBar()}</div>
      <div id="writing-deep-import-bar-container">${this._renderDeepImportBar()}</div>
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  onLeave() {
    this._clearAutoSaveTimer()
    this._clearCursorDebounceTimer()
    if (this._beforeUnloadHandler) {
      window.removeEventListener("beforeunload", this._beforeUnloadHandler)
      this._beforeUnloadHandler = null
    }
    const editor = document.getElementById("writing-editor")
    state.viewStates.writing = {
      projectId: state.currentProjectId,
      currentChapter: this._currentChapter,
      currentContent: editor ? editor.value : this._currentContent,
      currentTitle: this._currentTitle,
      currentDraftId: this._currentDraftId,
      currentVersionNumber: this._currentVersionNumber,
      currentUpdatedAt: this._currentUpdatedAt,
      isReadonly: this._isReadonly,
      restoreSourceVersion: this._restoreSourceVersion,
    }
    if (this._publishTimer) {
      clearInterval(this._publishTimer)
      this._publishTimer = null
    }
    if (this._deepImportTimer) {
      clearInterval(this._deepImportTimer)
      this._deepImportTimer = null
    }
  },

  async onActivate() {
    // KeepAlive 恢复后重新绑定事件
    this._bindEvents()
    // 恢复编辑器焦点
    const editor = document.getElementById("writing-editor")
    if (editor && this._currentContent !== null) {
      editor.focus()
    }
    // KeepAlive 切回时同样需要恢复深度导入进度，等待完成以避免生命周期竞态
    await this._recoverDeepImportTask()
  },

  onDeactivate() {
    this._clearAutoSaveTimer()
    // 保存当前编辑器内容到状态，避免缓存 DOM 与状态不一致
    const editor = document.getElementById("writing-editor")
    if (editor) {
      this._currentContent = editor.value
      // 写入 localStorage 后备
      if (editor.value.trim() && this._currentChapter) {
        this._saveBackup(editor.value, this._currentTitle || "")
      }
    }
    const titleInput = document.getElementById("writing-title-input")
    if (titleInput) {
      this._currentTitle = titleInput.value
    }
  },

  _shouldRenderMobileQuickNote() {
    return typeof window !== "undefined"
      && window.innerWidth < 600
      && this._currentChapter !== null
      && !this._forceDesktopMode
      && !document.body.classList.contains("force-desktop")
  },

  _renderMobileQuickNote() {
    const currentText = this._currentContent || ""
    return `
      <div class="mobile-quick-note">
        <div class="mobile-note-header">
          <span class="mobile-note-chapter">第 ${esc(this._currentChapter)} 章</span>
          <span class="mobile-note-wc" id="mobile-note-wc">${esc(currentText.length.toLocaleString())} 字</span>
        </div>
        <textarea id="mobile-note-editor" class="mobile-note-editor" placeholder="在此记录灵感...">${esc(currentText)}</textarea>
        <div class="mobile-note-actions">
          <button class="btn btn-primary" data-action="save-mobile-note">保存为草稿</button>
          <button class="btn btn-ghost" data-action="switch-desktop-mode">完整编辑器</button>
        </div>
      </div>
    `
  },

  async _saveMobileNote() {
    const editor = document.getElementById("mobile-note-editor")
    if (!editor || this._currentChapter == null) return
    this._currentContent = editor.value
    const title = this._currentTitle || `第 ${this._currentChapter} 章`
    try {
      if (this._currentDraftId) {
        const result = await api.writing.autosave(
          this._currentDraftId,
          {
            title,
            content: editor.value,
            expected_version: this._currentVersionNumber,
            expected_updated_at: this._currentUpdatedAt,
          },
          state.currentProjectId,
        )
        this._currentVersionNumber = result.version_number
        this._currentUpdatedAt = result.updated_at || this._currentUpdatedAt
      } else {
        const created = await api.writing.autosaveDraftOnly({
          novel_id: state.currentProjectId,
          chapter_index: this._currentChapter,
          title,
          content: editor.value,
        })
        this._currentDraftId = created.id
        this._currentVersionNumber = created.version_number
        this._currentUpdatedAt = created.updated_at || null
      }
      this._currentTitle = title
      this._lastSavedContent = editor.value
      this._saveBackup(null, null)
      toast("已保存到草稿", "success")
    } catch (err) {
      this._saveBackup(editor.value, title)
      toast(err.message || "移动记录保存失败，已保留本地暂存", "error")
    }
  },

  async _aiContinue() {
    const panel = document.getElementById("ai-suggestion-panel")
    if (!panel) return
    panel.classList.remove("hidden")
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;padding:12px 16px;color:var(--text-dim);font-size:13px;">
        <span class="spinner" style="display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin 1s linear infinite;"></span>
        AI 正在分析上下文...
      </div>
    `
    setTimeout(() => {
      panel.classList.add("hidden")
      toast("AI 续写功能即将上线，敬请期待 🚀", "info")
    }, 2000)
  },

  _exportChapter() {
    const title = this._currentTitle || `第 ${this._currentChapter} 章`
    const content = this._currentContent || ""
    const text = `${title}\n\n${content}`
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${title.replace(/[\\/:*?"<>|]/g, "")}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast(`已导出「${title}」`, "success")
  },

  async _switchDesktopMode() {
    this._forceDesktopMode = true
    document.body.classList.add("force-desktop")
    await this._rerender()
  },

  // ============================================================
  // 保存辅助方法
  // ============================================================

  /** 导航离开前保存当前编辑内容 */
  async _saveBeforeNavigate() {
    this._clearAutoSaveTimer()
    if (this._currentSavePromise) {
      await this._currentSavePromise
      return
    }
    const editor = document.getElementById("writing-editor")
    if (!editor || !this._currentChapter || this._isReadonly) return

    const content = editor.value
    const titleInput = document.getElementById("writing-title-input")
    const title = titleInput ? titleInput.value.trim() : ""

    if (this._currentDraftId) {
      try {
        const result = await api.writing.autosave(
          this._currentDraftId,
          {
            title,
            content,
            expected_version: this._currentVersionNumber,
            expected_updated_at: this._currentUpdatedAt,
          },
          state.currentProjectId,
        )
        this._currentContent = content
        this._currentTitle = title
        this._currentVersionNumber = result.version_number
        this._currentUpdatedAt = result.updated_at || this._currentUpdatedAt
        this._lastSavedContent = content
        this._saveBackup(null, null) // 清除 localStorage 后备
      } catch (err) {
        this._saveBackup(content, title)
        if (err.status === 409) {
          toast("该章节已被其他会话更新，请刷新后重新编辑", "error")
        } else {
          toast("保存失败，内容已暂存到本地", "warning")
        }
      }
    } else if (content.trim()) {
      this._saveBackup(content, title)
    }
  },

  /** 清除自动保存计时器 */
  _clearAutoSaveTimer() {
    if (this._autoSaveTimer) {
      clearTimeout(this._autoSaveTimer)
      this._autoSaveTimer = null
    }
  },

  /** 清除光标场景面板防抖计时器 */
  _clearCursorDebounceTimer() {
    if (this._cursorDebounceTimer) {
      clearTimeout(this._cursorDebounceTimer)
      this._cursorDebounceTimer = null
    }
  },

  /** 当前保存状态文案 */
  _saveStatusText() {
    if (this._autoSaving) return "保存中..."
    if (this._isReadonly || this._currentChapter === null) return ""
    const editor = typeof document !== "undefined" ? document.getElementById("writing-editor") : null
    const currentContent = editor ? editor.value : this._currentContent
    if (currentContent !== undefined && currentContent !== this._lastSavedContent) return "未保存"
    if (this._lastPublishStatus) return this._lastPublishStatus
    if (this._chapterStatus(this._currentChapter) === "published") return "已发布"
    return this._lastSavedContent !== null ? "已保存" : ""
  },

  /** 更新保存状态显示 */
  _updateSaveStatus() {
    const el = document.getElementById("writing-save-status")
    if (el) el.textContent = this._saveStatusText()
    this._updateTopbarWordcount()
  },

  _updateTopbarWordcount() {
    const editor = typeof document !== "undefined" ? document.getElementById("writing-editor") : null
    const content = editor ? editor.value : (this._currentContent || "")
    globalThis.App?.updateWordcountDashboard?.({
      chapterIndex: this._currentChapter,
      chapterWords: content.length,
      todayWords: this._getDailyWordcount() + content.length,
      saveState: this._saveStateForDashboard(),
    })
  },

  /** 安排自动保存（3 秒防抖） */
  _scheduleAutoSave() {
    this._clearAutoSaveTimer()
    this._updateSaveStatus()
    this._autoSaveTimer = setTimeout(() => {
      this._autoSaveTimer = null
      this._autosave()
    }, 3000)
  },

  /** localStorage 后备保存 */
  _saveBackup(content, title) {
    if (!state.currentProjectId || !this._currentChapter) return
    const key = `draft_backup_${state.currentProjectId}_${this._currentChapter}`
    if (!content) {
      localStorage.removeItem(key)
      return
    }
    try {
      localStorage.setItem(key, JSON.stringify({
        content, title: title || "",
        chapter_index: this._currentChapter,
        timestamp: Date.now(),
      }))
    } catch {
      // localStorage 满了，忽略
    }
  },

  /** 从 localStorage 加载后备内容 */
  _loadBackup(chapterIndex) {
    if (!state.currentProjectId) return null
    const key = `draft_backup_${state.currentProjectId}_${chapterIndex}`
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return null
      return JSON.parse(raw)
    } catch {
      return null
    }
  },

  async _maybeRestoreBackup(chapterIndex) {
    const backup = this._loadBackup(chapterIndex)
    if (!backup || !backup.content) return false

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
    this._currentContent = backup.content
    this._currentTitle = backup.title || ""
    return true
  },

  // ============================================================
  // 左侧：章节树
  // ============================================================

  _renderChapterTree() {
    reconcileBulkSelection(this, "writing-chapters", this._chapterList.map(String))
    let html = `
      <div class="card chapter-tree-card">
        <div class="chapter-tree-header">
          <span class="chapter-tree-title">章节（${this._chapterList.length}）</span>
          <div class="chapter-tree-actions">
            <button class="btn btn-sm" data-action="prev-chapter" title="上一章">&#8592;</button>
            <button class="btn btn-sm" data-action="next-chapter" title="下一章">&#8594;</button>
            <button class="btn btn-sm" data-action="new-chapter">+ 新建</button>
          </div>
        </div>
        <div style="margin-top:6px;">
    `

    for (const idx of this._chapterList) {
      const isActive = idx === this._currentChapter
      html += this._renderChapterRow(idx)
    }

    html += '</div></div>'
    return html
  },

  // ============================================================
  // 左侧：Scene 树（替换原章节树）
  // ============================================================

  _renderSceneTree() {
    // 无 Scene 时退回到普通章节树，避免所有章节被折叠在“未归类”中不可见
    if (this._scenes.length === 0) {
      return this._renderChapterTree()
    }

    const assignedChapters = new Set()
    const sceneChapterMap = this._scenes.map((s) => {
      const chIds = (s.chapter_ids || []).map((id) => {
        const num = parseInt(id, 10)
        if (!isNaN(num) && this._chapters[num]) {
          assignedChapters.add(num)
          return num
        }
        return null
      }).filter(Boolean)
      return { scene: s, chapters: chIds }
    })

    const unassigned = this._chapterList.filter((idx) => !assignedChapters.has(idx))
    reconcileBulkSelection(this, "writing-chapters", this._chapterList.map(String))

    let html = `
      <div class="card chapter-tree-card">
        <div class="chapter-tree-header">
          <span class="chapter-tree-title">章节</span>
          <div class="chapter-tree-actions">
            <button class="btn btn-sm" data-action="prev-chapter" title="上一章">&#8592;</button>
            <button class="btn btn-sm" data-action="next-chapter" title="下一章">&#8594;</button>
            <button class="btn btn-sm" data-action="new-chapter">+ 新建</button>
          </div>
        </div>
        <div style="margin-top:6px;">
    `

    // 未归类章节
    if (unassigned.length > 0) {
      const isExpanded = unassigned.includes(this._currentChapter)
      html += `
        <div class="scene-tree-node">
          <div class="scene-tree-scene" data-action="toggle-scene-group" style="cursor:pointer;padding:4px 4px;">
            <span class="toggle-icon">${isExpanded ? '▼' : '▶'}</span>
            <span style="color:var(--text-dim);font-size:12px;">未归类</span>
            <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${unassigned.length}章)</span>
          </div>
          <div class="scene-tree-chapters" style="display:${isExpanded ? 'block' : 'none'};margin-left:12px;">
      `
      for (const idx of unassigned) {
        html += this._renderChapterRow(idx)
      }
      html += '</div></div>'
    }

    // Scene 节点。真实写作页 reload 后作者需要能直接点击章节行；含章节的
    // Scene 默认展开，避免按钮存在于隐藏父容器中而变成 0x0。
    for (const { scene, chapters } of sceneChapterMap) {
      if (chapters.length === 0 && unassigned.length === 0) continue
      const isCurrentScene = scene.id === this._currentSceneId
      const isExpanded = chapters.length > 0 || isCurrentScene || chapters.includes(this._currentChapter)

      html += `
        <div class="scene-tree-node">
          <div class="scene-tree-scene clickable" data-action="select-scene" data-scene-id="${esc(scene.id)}"
               style="padding:4px 4px;border-radius:var(--radius-sm);${isCurrentScene ? 'background:var(--hover-bg);' : ''}">
            <span class="toggle-icon">${isExpanded ? '▼' : '▶'}</span>
            <span style="font-size:13px;font-weight:${isCurrentScene ? 'bold' : 'normal'};">${esc(scene.title || '未命名')}</span>
            <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${chapters.length}章)</span>
          </div>
          <div class="scene-tree-chapters" style="display:${isExpanded ? 'block' : 'none'};margin-left:12px;">
      `

      for (const idx of chapters) {
        html += this._renderChapterRow(idx)
      }

      html += '</div></div>'
    }

    html += '</div></div>'
    return html
  },

  _renderChapterRow(idx) {
    const isActive = idx === this._currentChapter
    const title = this._chapters[idx]?.title || ""
    const wordcount = this._chapterWordcount(idx)
    const label = `打开第 ${idx} 章${title ? `：${title}` : ""}，${wordcount} 字`
    return `
      <button type="button" class="chapter-row ${isActive ? "chapter-row--active" : ""}" data-action="select-chapter" data-chapter="${idx}" aria-label="${esc(label)}" aria-current="${isActive ? "true" : "false"}">
        <div class="chapter-row__status">
          <span class="chapter-status chapter-status--${esc(this._chapterStatus(idx))}" title="${esc(this._chapterStatusLabel(idx))}"></span>
        </div>
        <div class="chapter-row__info">
          <div class="chapter-row__title">
            <span class="chapter-number">第 ${idx} 章</span>
            ${title ? `<span class="chapter-title-text">${esc(title)}</span>` : ""}
          </div>
          <div class="chapter-row__meta">
            <span class="chapter-wc">${esc(wordcount)} 字</span>
          </div>
        </div>
      </button>
    `
  },

  _chapterStatus(idx) {
    const chapter = this._chapters[idx]
    if (!chapter) return "empty"
    if (chapter.published || chapter.status === "published") return "published"
    if ((chapter.draftCount || 0) > 0 || chapter.title) return "draft"
    return "empty"
  },

  _chapterStatusLabel(idx) {
    return { empty: "未写", draft: "草稿", published: "已发布" }[this._chapterStatus(idx)] || "未知"
  },

  _chapterWordcount(idx) {
    if (idx === this._currentChapter) {
      const editor = typeof document !== "undefined" ? document.getElementById("writing-editor") : null
      const content = editor ? editor.value : (this._currentContent || "")
      return String(content.length || this._chapters[idx]?.wordcount || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
    }
    const count = this._chapters[idx]?.wordcount || this._chapters[idx]?.word_count || 0
    return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  },

  _renderChapterBulkToolbar() {
    if (!this._showBulkActions) {
      return `<div style="margin:4px 0;text-align:right;"><button class="btn btn-sm btn-ghost" data-action="toggle-bulk-actions" title="批量管理">管理 ▾</button></div>`
    }
    return `
      <div class="row-actions" style="margin:8px 0;">
        <button class="btn btn-sm btn-ghost" data-action="toggle-bulk-actions">收起管理 ▴</button>
        <button class="btn btn-sm" data-action="select-visible-chapters" ${this._chapterList.length === 0 ? "disabled" : ""}>全选当前章节</button>
      </div>
    ` + renderBulkToolbar(this, "writing-chapters", [
      { action: "delete-chapters", label: "批量删除章节", className: "btn-danger" },
    ], { noun: "章节", hint: "只删除当前可见章节" })
  },

  _switchChapter(delta) {
    if (this._currentChapter == null || this._chapterList.length === 0) return
    const currentIndex = this._chapterList.indexOf(this._currentChapter)
    const nextIndex = currentIndex + delta
    if (nextIndex < 0 || nextIndex >= this._chapterList.length) return
    this._selectChapter(this._chapterList[nextIndex])
  },

  // ============================================================
  // 中间：编辑器
  // ============================================================

  _renderEditor() {
    const hasSelection = this._currentChapter !== null
    const versionInfo = this._currentVersionNumber ? `v${this._currentVersionNumber}` : ''
    const readOnlyLabel = this._isReadonly ? '（只读）' : ''
    const draftLabel = this._currentDraftId ? `${versionInfo} ${readOnlyLabel}` : ''
    const saveStatus = this._saveStatusText()
    const disabledReason = hasSelection ? "当前版本只读，需基于此版本创建后再编辑" : "请先选择章节"

    let html = `
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span id="writing-chapter-title" style="font-size:14px;font-weight:bold;">
              ${hasSelection ? `第 ${this._currentChapter} 章` : '选择章节开始编辑'}
            </span>
            <span id="writing-version-info" class="writing-version-badge">${esc(draftLabel || "未选择版本")}</span>
            <span id="writing-save-status" class="writing-save-badge">${esc(saveStatus)}</span>
          </div>
          <div class="writing-editor-buttons" id="writing-editor-buttons">
            ${this._isReadonly ? `<button class="btn btn-primary" data-action="restore-from-version">基于此版本创建</button>` : ''}
            <button class="btn" data-action="autosave" id="btn-autosave" ${hasSelection && !this._isReadonly ? '' : 'disabled'} title="${hasSelection && !this._isReadonly ? "暂存当前编辑内容" : esc(disabledReason)}">${this._restoreSourceVersion ? '发布为新版本' : '暂存'}</button>
            <button class="btn btn-primary" data-action="publish" id="btn-publish" ${hasSelection && !this._isReadonly ? '' : 'disabled'} title="${hasSelection && !this._isReadonly ? "发布当前章节版本" : esc(disabledReason)}">发布</button>
            <button class="btn btn-primary" data-action="run-conflict-check" id="btn-conflict-check" ${hasSelection && !this._isReadonly && !this._checkingConflicts ? '' : 'disabled'} title="${this._checkingConflicts ? "冲突检查正在运行" : hasSelection && !this._isReadonly ? "检查当前章节设定冲突" : esc(disabledReason)}">剧情设定冲突检查</button>
            <button class="btn btn-sm btn-ghost" data-action="ai-continue" title="AI 续写：基于当前上下文生成后续内容">AI 续写</button>
            <button class="btn btn-sm btn-ghost" data-action="export-chapter" title="导出当前章节为 .txt">导出</button>
            <button class="btn btn-sm btn-ghost" data-action="toggle-outline-float" ${hasSelection ? "" : "disabled"} title="大纲浮窗 (Ctrl+Shift+O)">大纲</button>
            <button class="btn btn-sm" data-action="toggle-focus-mode" ${hasSelection ? "" : "disabled"} title="专注模式（隐藏两侧面板）">${this._focusMode ? "退出专注" : "专注模式"}</button>
            ${this._renderEditorToolsMenu(hasSelection)}
          </div>
        </div>

        ${this._renderConflictCheckStrip()}

        ${this._renderVersionSelector()}
    `

    if (hasSelection) {
      html += `
        <input id="writing-title-input" type="text" value="${esc(this._currentTitle || '')}" placeholder="章节标题" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:6px 10px;border-radius:var(--radius-sm);font-size:13px;margin-bottom:6px;" ${this._isReadonly ? 'readonly' : ''} />

        <textarea id="writing-editor" class="novel-editor ${this._focusMode ? "novel-editor--focus" : ""}"
          placeholder="在此书写正文..." ${this._isReadonly ? 'readonly' : ''}>${this._currentContent ? esc(this._currentContent) : ''}</textarea>
        ${this._renderWordcountBar()}
        <div id="ai-suggestion-panel" class="ai-suggestion-panel hidden" aria-live="polite"></div>
      `
    } else {
      html += `
        <div style="text-align:center;padding:40px 0;color:var(--text-dim);font-size:13px;">
          请从左侧选择章节
        </div>
      `
    }

    html += '</div>'
    return html
  },

  _renderWordcountBar() {
    const chars = (this._currentContent || "").length
    const paragraphs = this._paragraphCount(this._currentContent || "")
    const readTime = this._readTimeMinutes(chars)
    const dailyGoal = this._getDailyGoal()
    const daily = this._getDailyWordcount() + chars
    const dailyPercent = dailyGoal > 0 ? Math.min(100, Math.round((daily / dailyGoal) * 100)) : 0
    const chapterGoal = this._getChapterGoal()
    const chapterPercent = chapterGoal > 0 ? Math.min(100, Math.round((chars / chapterGoal) * 100)) : 0
    let chapterGoalColor = "var(--text-secondary)"
    if (chapterPercent >= 100) chapterGoalColor = "var(--success, #22c55e)"
    else if (chapterPercent >= 80) chapterGoalColor = "var(--warning, #f59e0b)"
    return `
      <div class="writing-wordcount-bar" id="writing-wordcount-bar">
        <div class="wc-bar-left">
          <span id="wc-chapter" style="color:${chapterGoalColor};">${esc(chars.toLocaleString())}</span> / ${esc(chapterGoal.toLocaleString())} 字
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
  },

  _paragraphCount(text) {
    return (text || "").split(/\n{2,}/).filter((part) => part.trim()).length
  },

  _readTimeMinutes(chars) {
    return Math.max(1, Math.ceil((chars || 0) / 300))
  },

  _getDailyWordcount() {
    try {
      const today = new Date().toISOString().slice(0, 10)
      const key = `novel_daily_wc_${today}_${state.currentProjectId || "global"}`
      return Number(localStorage.getItem(key) || 0) || 0
    } catch {
      return 0
    }
  },

  _getDailyGoal() {
    try {
      const projectPrefs = this._loadAuthorPreferences()
      return Number(projectPrefs.dailyGoal || localStorage.getItem("novel_daily_goal") || 4000) || 4000
    } catch {
      return 4000
    }
  },

  _getChapterGoal() {
    try {
      const projectPrefs = this._loadAuthorPreferences()
      return Number(projectPrefs.chapterGoal || localStorage.getItem("novel_chapter_goal") || 3000) || 3000
    } catch {
      return 3000
    }
  },

  _getFocusDefault() {
    try {
      const projectPrefs = this._loadAuthorPreferences()
      if (typeof projectPrefs.defaultFocusMode === "boolean") return projectPrefs.defaultFocusMode
      return localStorage.getItem("novel_focus_default") === "1"
    } catch {
      return false
    }
  },

  _loadAuthorPreferences() {
    try {
      const raw = localStorage.getItem(`novel_author_preferences:${state.currentProjectId || "global"}`)
      return raw ? JSON.parse(raw) : {}
    } catch {
      return {}
    }
  },

  _saveStateForDashboard() {
    if (this._autoSaving) return "saving"
    return this._saveStatusText() === "未保存" ? "unsaved" : "saved"
  },

  _updateWordcount() {
    const editor = document.getElementById("writing-editor")
    if (!editor) return
    const text = editor.value || ""
    const chars = text.length
    const paragraphs = this._paragraphCount(text)
    const readTime = this._readTimeMinutes(chars)
    const dailyGoal = this._getDailyGoal()
    const daily = this._getDailyWordcount() + chars
    const percent = dailyGoal > 0 ? Math.min(100, (daily / dailyGoal) * 100) : 0

    const setText = (id, value) => {
      const el = document.getElementById(id)
      if (el) el.textContent = value
    }
    setText("wc-chapter", chars.toLocaleString())
    setText("wc-paragraphs", String(paragraphs))
    setText("wc-readtime", String(readTime))
    setText("wc-daily", `${daily.toLocaleString()} / ${dailyGoal.toLocaleString()}`)
    const fill = document.getElementById("wc-goal-fill")
    if (fill) fill.style.width = `${percent}%`

    const chapterGoal = this._getChapterGoal()
    const chapterPercent = chapterGoal > 0 ? Math.min(100, Math.round((chars / chapterGoal) * 100)) : 0
    const chapterEl = document.getElementById("wc-chapter")
    if (chapterEl) {
      chapterEl.textContent = chars.toLocaleString()
      if (chapterPercent >= 100) chapterEl.style.color = "var(--success, #22c55e)"
      else if (chapterPercent >= 80) chapterEl.style.color = "var(--warning, #f59e0b)"
      else chapterEl.style.color = ""
    }

    globalThis.App?.updateWordcountDashboard?.({
      chapterIndex: this._currentChapter,
      chapterWords: chars,
      todayWords: daily,
      saveState: this._saveStateForDashboard(),
    })
    this._updateSaveStatus()
  },

  _toggleFocusMode() {
    this._focusMode = !this._focusMode
    const editor = document.getElementById("writing-editor")
    document.body.classList.toggle("focus-mode-active", this._focusMode)
    editor?.classList.toggle("novel-editor--focus", this._focusMode)
    for (const id of ["writing-tree-container", "writing-panel-container", "sidebar"]) {
      document.getElementById(id)?.classList.toggle("focus-hidden", this._focusMode)
    }
    editor?.focus()
    this._updateEditorMeta()
  },

  async _toggleOutlineFloat() {
    const panel = document.getElementById("outline-float-panel")
    if (!panel) return
    const opening = panel.classList.contains("hidden")
    panel.classList.toggle("hidden", !opening)
    document.body.classList.toggle("outline-float-open", opening)
    if (opening) await this._loadOutlineFloat()
  },

  _closeOutlineFloat() {
    document.getElementById("outline-float-panel")?.classList.add("hidden")
    document.body.classList.remove("outline-float-open")
  },

  async _loadOutlineFloat() {
    const body = document.getElementById("outline-float-body")
    if (!body || !state.currentProjectId) return
    try {
      const response = await api.outline.listThreads(state.currentProjectId, { limit: 50 })
      const threads = response.items || response || []
      body.innerHTML = threads.length ? `
        <div class="outline-float-list">
          ${threads.map((thread) => `
            <article class="outline-float-item">
              <div class="outline-float-title">${esc(thread.title || thread.name || "未命名剧情线")}</div>
              <div class="outline-float-chapters">
                ${(thread.chapter_ids || thread.chapters || []).map((chapter) => `
                  <button class="outline-float-chapter ${String(chapter) === String(this._currentChapter) ? "current" : ""}"
                    data-action="select-chapter" data-chapter="${esc(chapter)}">${esc(chapter)}</button>
                `).join("") || '<span class="muted">暂无章节映射</span>'}
              </div>
            </article>
          `).join("")}
        </div>
      ` : '<p class="muted">暂无大纲条目</p>'
    } catch {
      body.innerHTML = '<p class="muted">大纲加载失败</p>'
    }
  },

  _renderEditorToolsMenu(hasSelection) {
    const disabled = hasSelection && !this._isReadonly ? "" : "disabled"
    const disabledTitle = hasSelection ? "当前版本只读，需基于此版本创建后再使用" : "请先选择章节"
    return `
      <details class="writing-tools-menu">
        <summary class="btn btn-sm">AI 工具</summary>
        <div class="writing-tools-menu__body">
          <div class="writing-tools-menu__group">
            <strong>生成</strong>
            <button class="btn btn-sm" data-action="ai-generate-draft" ${disabled} title="${disabled ? esc(disabledTitle) : "基于上下文生成当前章节草稿"}">AI 生成草稿</button>
          </div>
          ${state.currentProjectId ? `<div class="writing-tools-menu__group">
            <strong>提取</strong>
            <button class="btn btn-sm" data-action="auto-extract-stage" data-stage="scenes">场景（scene）自动提取</button>
            <button class="btn btn-sm" data-action="auto-extract-stage" data-stage="world_objects">世界对象与别名/关系自动提取</button>
            <button class="btn btn-sm" data-action="auto-extract-stage" data-stage="plot_structure">剧情线自动提取</button>
            ${this._chapterList.length > 0 ? `<button class="btn btn-sm" data-action="extract-cards">AI 提取章节卡</button>` : ""}
          </div>` : ""}
          <div class="writing-tools-menu__group">
            <strong>检查</strong>
            <span class="writing-tools-menu__hint">剧情设定冲突检查在编辑器顶部执行。</span>
            ${this._findCurrentScene() && this._currentChapter ? `<button class="btn btn-sm" data-action="split-scene">断章至此</button>` : ""}
          </div>
          ${state.currentProjectId ? `<div class="writing-tools-menu__group">
            <strong>地图</strong>
            <button class="btn btn-sm" data-action="open-map">打开地图</button>
          </div>` : ""}
        </div>
      </details>
    `
  },

  _renderConflictCheckStrip() {
    if (!this._currentChapter) return ""
    const latest = this._latestConflictCheck || this._conflictChecks[0]
    const history = this._conflictChecks.slice(1)
    const latestHtml = latest
      ? `<button class="writing-conflict-latest" data-action="open-conflict-check" data-check-id="${esc(latest.id)}">
          ${esc(this._formatConflictCheckSummary(latest))}
        </button>`
      : '<span class="writing-conflict-empty-inline">暂无检查记录</span>'
    const historyHtml = history.length
      ? `
        <details class="writing-conflict-history">
          <summary>历史 ▾</summary>
          <div class="writing-conflict-history__list">
            ${history.map((item) => `
              <button data-action="open-conflict-check" data-check-id="${esc(item.id)}">
                ${esc(this._formatConflictCheckSummary(item))}
              </button>
            `).join("")}
          </div>
        </details>
      `
      : ""
    return `
      <div class="writing-conflict-strip" id="writing-conflict-strip">
        ${latestHtml}
        ${historyHtml}
      </div>
    `
  },

  _formatConflictCheckSummary(check) {
    const created = check?.created_at ? new Date(check.created_at) : null
    const time = created && !Number.isNaN(created.getTime())
      ? created.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
      : "刚刚"
    const total = check?.summary_json?.total ?? (check?.items || []).length
    return `${time} · 发现 ${total} 个冲突`
  },

  _renderVersionSelector() {
    if (!this._currentChapter || this._versions.length === 0) return ''

    let html = `
      <div style="margin-bottom:8px;display:flex;align-items:center;gap:6px;font-size:12px;">
        <span style="color:var(--text-dim);">版本：</span>
        <select id="version-selector" style="background:var(--bg);color:var(--text);border:1px solid var(--border);padding:3px 6px;border-radius:var(--radius-sm);font-size:12px;">
    `

    for (const v of this._versions) {
      const selected = v.version_number === this._currentVersionNumber
      const isCurLatest = v.version_number === this._versions[0]?.version_number
      html += `<option value="${esc(v.id)}" data-version="${esc(v.version_number)}" data-latest="${isCurLatest ? 1 : 0}" ${selected ? 'selected' : ''}>v${esc(v.version_number)}${isCurLatest ? ' (最新)' : ''}</option>`
    }

    html += `
        </select>
        <button class="btn btn-sm" data-action="version-history" title="版本历史" style="font-size:11px;">历史</button>
        <button class="btn btn-sm" id="btn-delete-version" data-action="delete-version" title="删除当前版本" style="font-size:11px;color:var(--danger);margin-left:4px;">🗑</button>
        <span id="publish-status-dot" style="display:none;width:8px;height:8px;border-radius:50%;background:var(--accent);margin-left:4px;" title="发布任务进行中"></span>
      </div>
    `
    return html
  },

  // ============================================================
  // 右侧：Scene 面板
  // ============================================================

  _findCurrentScene() {
    if (!this._currentChapter || !this._scenes.length) return null
    const chStr = String(this._currentChapter)
    const offset = this._cursorOffset || 0
    const byOffset = this._scenes.find((s) =>
      (s.scene_chunks || []).some((c) =>
        String(c.chapter_index) === chStr &&
        Number(c.start_pos || 0) <= offset &&
        offset < Number(c.end_pos || 0)
      )
    )
    if (byOffset) return byOffset
    const exact = this._scenes.find((s) =>
      (s.chapter_ids || []).includes(chStr)
    )
    if (exact) return exact
    const byChunk = this._scenes.find((s) =>
      (s.scene_chunks || []).some((c) => String(c.chapter_index) === chStr)
    )
    return byChunk || null
  },

  _updateCurrentScene() {
    const scene = this._findCurrentScene()
    const nextSceneId = scene?.id || null
    if (nextSceneId !== this._currentSceneId) {
      this._sceneMapSummary = null
      this._sceneMapSummaryError = null
      this._sceneMapSummarySceneId = null
      this._sceneMapSummaryPendingSceneId = null
      this._sceneMapSummaryLoading = false
    }
    this._currentSceneId = nextSceneId
  },

  _renderScenePanel() {
    const currentScene = this._findCurrentScene()
    this._scheduleSceneMapSummaryLoad(currentScene)
    return renderSceneCockpitPanel({
      projectId: state.currentProjectId,
      scene: currentScene,
      mapSummaryHtml: this._renderMapSummary(currentScene),
      compact: typeof window !== "undefined" && window.innerHeight < 760,
    })
  },

  _renderMapSummary(currentScene) {
    if (!state.currentProjectId) return ""
    const emptyText = currentScene ? "当前 Scene 暂无地图位置" : "当前章节未关联地图 Scene"
    if (this._sceneMapSummaryError) {
      return `
        <div class="writing-map-summary">
          <div style="font-size:12px;font-weight:600;margin-bottom:6px;">地图摘要</div>
          <div style="color:var(--warning);font-size:11px;">${esc(this._sceneMapSummaryError)}</div>
        </div>
      `
    }
    if (this._sceneMapSummaryLoading && !this._sceneMapSummary) {
      return `
        <div class="writing-map-summary">
          <div style="font-size:12px;font-weight:600;margin-bottom:6px;">地图摘要</div>
          <div style="color:var(--text-dim);font-size:11px;">地图摘要加载中...</div>
        </div>
      `
    }
    const summary = this._sceneMapSummary
    if (!summary) {
      return `
        <div class="writing-map-summary">
          <div style="font-size:12px;font-weight:600;margin-bottom:6px;">地图摘要</div>
          <div style="color:var(--text-dim);font-size:11px;">${esc(emptyText)}</div>
        </div>
      `
    }
    const location = summary.primary_location?.name || "未绑定地点"
    const row = (label, items) => {
      const names = (items || []).map((item) => item.name).filter(Boolean)
      if (!names.length) return ""
      return `
        <div style="margin-top:4px;">
          <span style="color:var(--text-dim);">${esc(label)}：</span>${esc(names.slice(0, 3).join("、"))}
        </div>
      `
    }
    const warnings = (summary.warnings || []).map((warning) => `
      <div style="margin-top:4px;color:var(--warning);">${esc(this._mapWarningMessage(warning))}</div>
    `).join("")
    const risks = (summary.risks || []).map((risk) => `
      <div style="margin-top:4px;color:var(--warning);">${esc(this._mapWarningMessage(risk))}</div>
    `).join("")
    return `
      <div class="writing-map-summary">
        <div style="font-size:12px;font-weight:600;margin-bottom:6px;">地图摘要</div>
        <div><span style="color:var(--text-dim);">地点：</span>${esc(location)}</div>
        ${row("人物", summary.characters)}
        ${row("事件", summary.events)}
        ${row("势力", summary.factions)}
        ${row("危机", summary.crises)}
        ${risks}
        ${warnings}
        <div style="margin-top:8px;">
          <button class="btn btn-sm" data-action="open-map">打开地图</button>
        </div>
      </div>
    `
  },

  _mapWarningMessage(warning) {
    if (typeof warning === "string") return warning
    if (!warning || typeof warning !== "object") return ""
    if (warning.message) return warning.message
    const messages = {
      scene_without_map_context: "当前 Scene 暂无地图上下文",
      scene_without_location: "当前 Scene 暂无主地点",
      character_cross_map: "人物上一场在其他地图，需确认移动合理性",
    }
    return messages[warning.code] || "地图空间连续性需复核"
  },

  _scheduleSceneMapSummaryLoad(currentScene) {
    if (!state.currentProjectId || !currentScene?.id) return
    // 当前场景已有结果或已有正在进行的同场景请求，避免重复调度
    if (this._sceneMapSummarySceneId === currentScene.id) return
    if (this._sceneMapSummaryPendingSceneId === currentScene.id) return
    this._sceneMapSummaryPendingSceneId = currentScene.id
    this._sceneMapSummaryLoading = true
    setTimeout(async () => {
      await this._loadCurrentSceneMapSummary(currentScene)
      // 用户切换 Scene 后避免用旧结果重新渲染
      if (this._currentSceneId !== currentScene.id) return
      const panelEl = document.getElementById("writing-panel-container")
      if (panelEl) {
        panelEl.innerHTML = this._renderScenePanel()
        this._bindEvents()
      }
    }, 0)
  },

  async _loadCurrentSceneMapSummary(scene) {
    if (!state.currentProjectId || !scene?.id) {
      this._sceneMapSummary = null
      this._sceneMapSummaryError = null
      this._sceneMapSummarySceneId = null
      this._sceneMapSummaryPendingSceneId = null
      this._sceneMapSummaryLoading = false
      return null
    }
    this._sceneMapSummaryError = null
    this._sceneMapSummaryLoading = true
    const isStillCurrent = () => this._currentSceneId === scene.id
    const isActiveRequest = () => this._sceneMapSummaryPendingSceneId === scene.id ||
      this._sceneMapSummaryPendingSceneId === null
    try {
      const summary = await api.world.getMapSceneSummary(state.currentProjectId, scene.id)
      if (!isStillCurrent() || !isActiveRequest()) return null
      this._sceneMapSummary = summary
      this._sceneMapSummaryError = null
      this._sceneMapSummarySceneId = scene.id
      return summary
    } catch {
      if (!isStillCurrent() || !isActiveRequest()) return null
      this._sceneMapSummary = null
      this._sceneMapSummaryError = "地图摘要暂不可用"
      this._sceneMapSummarySceneId = scene.id
      toast("地图摘要暂不可用", "warning")
      return null
    } finally {
      if (isActiveRequest()) {
        this._sceneMapSummaryLoading = false
        this._sceneMapSummaryPendingSceneId = null
      }
    }
  },

  _openMapForCurrentScene() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    const currentScene = this._findCurrentScene()
    const target = this._sceneMapSummary?.open_target || {}
    const mode = target.mode || (target.map_id ? "map" : "recent")
    const url = buildMapUrl({
      projectId: state.currentProjectId,
      mapId: target.map_id,
      sceneId: target.scene_id || currentScene?.id,
      focusEntityId: target.focus_entity_id,
      mode,
    })
    if (target.fallback_message) {
      toast(target.fallback_message, "warning")
    }
    window.open(url, "_blank", "noopener")
  },

  _renderPublishBar() {
    if (!this._publishProgress) return ''

    const progress = this._normalizePublishProgress()
    const actionsHtml = progress.failed
      ? `<button class="btn btn-sm" data-action="dismiss-publish-error" style="font-size:11px;">关闭</button>`
      : ""

    return renderFixedProgress(progress, {
      title: "发布正文",
      message: progress.message,
      showTaskId: false,
      actionsHtml,
    })
  },

  _normalizePublishProgress() {
    const p = this._publishProgress || {}
    const status = p.phase === "failed" ? "failed" : p.phase === "done" ? "done" : "running"
    return normalizeTaskProgress({
      task_id: this._publishTaskId || "publish_chapter",
      task_type: "publish_chapter",
      status,
      progress: typeof p.step === "number" ? p.step : 0,
      error_message: status === "failed" ? p.message : null,
      result: {
        message: p.message || "发布中...",
      },
    }, "publish_chapter")
  },

  // ============================================================
  // 章节操作
  // ============================================================

  async _loadOutlineData(chapterIndex) {
    if (!state.currentProjectId) return
    try {
      const [threadsRes, arcsRes] = await Promise.all([
        api.outline.listThreads(state.currentProjectId).catch(() => ({ items: [] })),
        api.outline.listArcs(state.currentProjectId).catch(() => ({ items: [] })),
      ])
      this._outlineThreads = (threadsRes && threadsRes.items) || []
      if (arcsRes && arcsRes.items) {
        const arcs = arcsRes.items
        this._outlineArc = arcs.find(a => a.start_chapter <= chapterIndex && a.end_chapter >= chapterIndex) || null
      } else {
        this._outlineArc = null
      }
    } catch {
      this._outlineThreads = []
      this._outlineArc = null
    }
  },

  async _selectChapter(chapterIndex) {
    // 点击同一章节：刷新内容
    if (this._currentChapter === chapterIndex && this._currentDraftId) {
      await this._refreshVersions(chapterIndex)
      await this._rerender()
      return
    }

    // 切换前保存当前内容
    await this._saveBeforeNavigate()

    delete state.viewStates.writing
    this._currentChapter = chapterIndex
    this._currentDraftId = null
    this._currentContent = null
    this._currentTitle = null
    this._currentVersionNumber = null
    this._currentUpdatedAt = null
    this._versions = []
    this._isReadonly = false
    this._restoreSourceVersion = null
    this._lastPublishStatus = null
    this._cursorOffset = 0

    await Promise.all([
      this._refreshVersions(chapterIndex),
      this._loadOutlineData(chapterIndex),
    ])
    this._updateCurrentScene()
    await this._refreshConflictChecks()
    await this._rerender()
  },

  async _refreshVersions(chapterIndex) {
    try {
      const history = await api.writing.getVersionHistory(chapterIndex, state.currentProjectId)
      this._versions = history.versions || []
      if (this._versions.length > 0) {
        const latest = this._versions[0]
        const draftData = await api.writing.get(latest.id, state.currentProjectId)
        const wordCount = latest.word_count || (draftData.content || "").length
        this._chapters[chapterIndex] = {
          title: draftData.title || latest.title || "",
          draftCount: this._versions.length,
          wordcount: wordCount,
          word_count: wordCount,
          status: draftData.status || "draft",
          updated_at: draftData.updated_at || latest.updated_at || null,
        }
        this._currentDraftId = draftData.id
        this._currentContent = draftData.content || ""
        this._currentTitle = draftData.title || ""
        this._currentVersionNumber = latest.version_number
        this._currentUpdatedAt = draftData.updated_at || null
        this._lastSavedContent = draftData.content || ""
        this._isReadonly = false
        this._lastPublishStatus = draftData.status === "published" ? "已发布" : null
      } else {
        this._currentDraftId = null
        this._currentContent = ""
        this._currentTitle = ""
        this._currentVersionNumber = null
        this._currentUpdatedAt = null
        this._lastSavedContent = null
        this._lastPublishStatus = null
        this._isReadonly = false

        await this._maybeRestoreBackup(chapterIndex)
      }
    } catch {
      this._versions = []
      this._currentDraftId = null
      this._currentContent = ""
      this._currentTitle = ""
      this._currentVersionNumber = null
      this._currentUpdatedAt = null
      this._lastSavedContent = null
      this._lastPublishStatus = null
      this._isReadonly = false
      await this._maybeRestoreBackup(chapterIndex)
    }
  },

  async _newChapter() {
    const defaultIndex = this._chapterList.length > 0 ? Math.max(...this._chapterList) + 1 : 1
    const idx = defaultIndex
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }

    if (this._chapters[idx]) {
      await this._selectChapter(idx)
      return
    }

    // 保存当前章节内容
    await this._saveBeforeNavigate()

    const defaultTitle = `第 ${idx} 章`
    let created = null
    try {
      created = await api.writing.autosaveDraftOnly({
        novel_id: state.currentProjectId,
        chapter_index: idx,
        title: defaultTitle,
        content: "",
      })
    } catch (err) {
      toast(err.message || "创建章节失败", "error")
      return
    }

    this._currentChapter = idx
    this._currentDraftId = created.id || null
    this._currentContent = created.content || ""
    this._currentTitle = created.title || defaultTitle
    this._currentVersionNumber = created.version_number || 1
    this._currentUpdatedAt = created.updated_at || null
    this._versions = [created]
    this._isReadonly = false
    this._restoreSourceVersion = null
    this._cursorOffset = 0
    this._lastSavedContent = created.content || ""

    this._chapters[idx] = {
      title: this._currentTitle,
      draftCount: 1,
      wordcount: 0,
      word_count: 0,
      status: created.status || "draft",
      updated_at: created.updated_at || null,
    }
    this._chapterList.push(idx)
    this._chapterList.sort((a, b) => a - b)

    await this._loadOutlineData(idx)
    this._updateCurrentScene()
    await this._rerender()
    toast(`已创建第 ${idx} 章`, "success")
  },

  // ============================================================
  // 版本切换
  // ============================================================

  async _switchVersion(draftId, versionNumber, isLatest) {
    try {
      const draftData = await api.writing.get(draftId, state.currentProjectId)
      this._currentDraftId = draftData.id
      this._currentTitle = draftData.title || ''
      this._currentVersionNumber = versionNumber
      this._currentUpdatedAt = draftData.updated_at || null
      this._cursorOffset = 0

      if (isLatest) {
        this._isReadonly = false
        this._restoreSourceVersion = null
        this._currentContent = draftData.content || ''
      } else {
        this._isReadonly = true
        this._restoreSourceVersion = versionNumber
        this._currentContent = draftData.content || ''
      }

      await this._rerender()
    } catch (err) {
      toast("切换版本失败：" + (err.message || "未知错误"), "error")
    }
  },

  _showVersionHistory() {
    if (!this._currentChapter || this._versions.length === 0) {
      toast("该章节暂无历史版本", "info")
      return
    }
    const latestVersion = this._versions[0]?.version_number
    let listHtml = '<div style="max-height:400px;overflow-y:auto;">'
    for (const v of this._versions) {
      const isLatest = v.version_number === latestVersion
      const wordCount = v.word_count || 0
      const created = v.created_at ? new Date(v.created_at).toLocaleDateString("zh-CN") : ""
      const isCurrent = v.version_number === this._currentVersionNumber
      listHtml += `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-dim);${isCurrent ? 'background:var(--hover-bg);border-radius:var(--radius-sm);padding:8px;' : ''}">
          <div>
            <span style="font-weight:500;">v${esc(v.version_number)}</span>
            ${isLatest ? ' <span class="badge badge-canonical">最新</span>' : ''}
            ${isCurrent ? ' <span style="color:var(--accent);font-size:11px;">当前</span>' : ''}
            <div style="font-size:11px;color:var(--text-dim);">${created} · ${wordCount} 字</div>
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-sm version-preview-btn" data-draft-id="${esc(v.id)}" data-version="${esc(v.version_number)}" data-is-latest="${isLatest ? 1 : 0}">预览</button>
            ${!isCurrent ? `<button class="btn btn-sm version-restore-btn" data-draft-id="${esc(v.id)}" data-version="${esc(v.version_number)}" data-is-latest="${isLatest ? 1 : 0}">恢复</button>` : ''}
          </div>
        </div>
      `
    }
    listHtml += "</div>"
    showModalHtml(`第 ${this._currentChapter} 章 — 版本历史 (${this._versions.length})`, listHtml)

    setTimeout(() => {
      document.querySelectorAll(".version-preview-btn").forEach((btn) => {
        btn.onclick = () => {
          const draftId = btn.dataset.draftId
          const versionNumber = parseInt(btn.dataset.version, 10)
          const isLatest = btn.dataset.isLatest === "1"
          closeModal()
          this._switchVersion(draftId, versionNumber, isLatest)
        }
      })
      document.querySelectorAll(".version-restore-btn").forEach((btn) => {
        btn.onclick = () => {
          const draftId = btn.dataset.draftId
          const versionNumber = parseInt(btn.dataset.version, 10)
          const isLatest = btn.dataset.isLatest === "1"
          closeModal()
          confirmAction(`恢复至 v${versionNumber}？当前编辑器内容将丢失。`, () => {
            this._switchVersion(draftId, versionNumber, isLatest)
            if (isLatest) {
              this._isReadonly = false
              this._restoreSourceVersion = null
              this._rerender()
              toast(`已恢复至 v${versionNumber}`, "success")
            }
          }, "确认恢复")
        }
      })
    }, 100)
  },

  async _restoreFromVersion() {
    if (!this._restoreSourceVersion) return

    this._isReadonly = false
    this._cursorOffset = 0
    // 不清除 _restoreSourceVersion — 用于 _autosave 判断走 POST 而非 PUT

    await this._rerender()
    toast(`已基于 v${this._currentVersionNumber} 开始编辑，保存时将创建新版本`, "info")
  },

  // ============================================================
  // 暂存 & 发布
  // ============================================================

  async _autosave() {
    this._clearAutoSaveTimer()
    const editor = document.getElementById("writing-editor")
    const titleInput = document.getElementById("writing-title-input")
    if (!editor || this._currentSavePromise) return

    // 从历史版本恢复后编辑：走发布流程（POST 创建新版本），不覆盖旧版本
    if (this._restoreSourceVersion) {
      const publishPromise = this._publish()
      this._currentSavePromise = publishPromise
      this._autoSaving = true
      try {
        return await publishPromise
      } catch (err) {
        toast(err.message || "发布失败", "error")
      } finally {
        this._autoSaving = false
        this._currentSavePromise = null
        this._updateSaveStatus()
      }
      return
    }

    if (!this._currentDraftId) {
      return
    }

    const content = editor.value
    const title = titleInput ? titleInput.value.trim() : ""

    const savePromise = (async () => {
      try {
        const result = await api.writing.autosave(
          this._currentDraftId,
          {
            title,
            content,
            expected_version: this._currentVersionNumber,
            expected_updated_at: this._currentUpdatedAt,
          },
          state.currentProjectId,
        )
        this._currentContent = content
        this._currentTitle = title
        this._currentVersionNumber = result.version_number
        this._currentUpdatedAt = result.updated_at || this._currentUpdatedAt
        this._lastSavedContent = content
        this._lastPublishStatus = null
        this._saveBackup(null, null)

        if (this._chapters[this._currentChapter]) {
          this._chapters[this._currentChapter].title = title
        }
        toast("已暂存", "success")
      } catch (err) {
        if (err.status === 409) {
          toast("该章节已被其他会话更新，请刷新后重新编辑", "error")
        } else {
          toast(err.message || "暂存失败", "error")
        }
      } finally {
        this._autoSaving = false
        this._updateSaveStatus()
      }
    })()
    this._currentSavePromise = savePromise
    this._autoSaving = true
    try {
      await savePromise
    } finally {
      this._currentSavePromise = null
    }
  },

  async _saveDraftForConflictCheck() {
    this._clearAutoSaveTimer()
    if (this._currentSavePromise) {
      await this._currentSavePromise
      return {
        id: this._currentDraftId,
        version_number: this._currentVersionNumber,
        updated_at: this._currentUpdatedAt,
      }
    }
    const editor = document.getElementById("writing-editor")
    const titleInput = document.getElementById("writing-title-input")
    if (!editor || !this._currentChapter) throw new Error("请先选择章节")
    const content = editor.value
    const title = titleInput ? titleInput.value.trim() : ""
    if (this._currentDraftId) {
      const result = await api.writing.autosave(
        this._currentDraftId,
        {
          title,
          content,
          expected_version: this._currentVersionNumber,
          expected_updated_at: this._currentUpdatedAt,
        },
        state.currentProjectId,
      )
      this._currentContent = content
      this._currentTitle = title
      this._currentVersionNumber = result.version_number
      this._currentUpdatedAt = result.updated_at || this._currentUpdatedAt
      this._lastSavedContent = content
      return result
    }
    const created = await api.writing.autosaveDraftOnly({
      novel_id: state.currentProjectId,
      chapter_index: this._currentChapter,
      title: title || `第 ${this._currentChapter} 章`,
      content,
    })
    this._currentDraftId = created.id
    this._currentContent = content
    this._currentTitle = created.title || title
    this._currentVersionNumber = created.version_number
    this._currentUpdatedAt = created.updated_at || null
    this._lastSavedContent = content
    return created
  },

  async _runConflictCheck() {
    if (this._checkingConflicts) return
    if (!state.currentProjectId || !this._currentChapter) {
      toast("请先选择章节", "warning")
      return
    }
    const editor = document.getElementById("writing-editor")
    if (!editor) return
    this._checkingConflicts = true
    try {
      const options = await this._confirmConflictCheckOptions()
      if (!options) return
      await this._saveDraftForConflictCheck()
      const currentScene = this._findCurrentScene()
      const check = await api.writing.createConflictCheck({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        scene_id: currentScene?.id || null,
        draft_id: this._currentDraftId,
        version_number: this._currentVersionNumber,
        content: editor.value,
        include_candidates: options.includeCandidates,
      })
      await this._refreshConflictChecks()
      this._openConflictCheck(check)
      await this._rerender()
    } catch (err) {
      toast(err.message || "剧情设定冲突检查失败", "error")
    } finally {
      this._checkingConflicts = false
    }
  },

  _confirmConflictCheckOptions() {
    return new Promise((resolve) => {
      let settled = false
      let observer = null
      const modalClose = document.getElementById("modal-close")
      const modalOverlay = document.getElementById("modal-overlay")
      const cleanup = () => {
        modalClose?.removeEventListener("click", onCloseClick)
        modalOverlay?.removeEventListener("click", onOverlayClick)
        document.removeEventListener("keydown", onKeyDown, true)
        observer?.disconnect()
      }
      const settle = (value) => {
        if (settled) return
        settled = true
        cleanup()
        resolve(value)
      }
      const cancel = () => {
        closeModal()
        settle(null)
      }
      const onCloseClick = cancel
      const onOverlayClick = (event) => {
        if (event.target === event.currentTarget) cancel()
      }
      const onKeyDown = (event) => {
        if (event.key === "Escape") {
          cancel()
        }
      }
      const body = `
        <div class="writing-conflict-options">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;">
            <input id="writing-conflict-include-candidates" type="checkbox" />
            <span>包含待确认对象</span>
          </label>
          <p style="margin:8px 0 0;color:var(--text-muted);font-size:12px;line-height:1.6;">
            包含后，依赖待确认对象的检查结果会标记为需复核；不会修改正文、Scene、地图或正史。
          </p>
        </div>
      `
      showModalHtml("剧情设定冲突检查", body, [
        {
          text: "取消",
          class: "btn-ghost",
          handler: cancel,
        },
        {
          text: "开始检查",
          class: "btn-primary",
          handler: () => {
            const checkbox = document.getElementById("writing-conflict-include-candidates")
            closeModal()
            settle({ includeCandidates: Boolean(checkbox?.checked) })
          },
        },
      ])
      modalClose?.addEventListener("click", onCloseClick)
      modalOverlay?.addEventListener("click", onOverlayClick)
      document.addEventListener("keydown", onKeyDown, true)
      if (modalOverlay && typeof MutationObserver !== "undefined") {
        observer = new MutationObserver(() => {
          if (modalOverlay.classList.contains("hidden")) settle(null)
        })
        observer.observe(modalOverlay, { attributes: true, attributeFilter: ["class"] })
      }
    })
  },

  async _refreshConflictChecks() {
    if (!state.currentProjectId || !this._currentChapter) {
      this._conflictChecks = []
      this._latestConflictCheck = null
      return
    }
    try {
      const currentScene = this._findCurrentScene()
      const result = await api.writing.listConflictChecks({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        scene_id: currentScene?.id || null,
        limit: 10,
      })
      this._conflictChecks = result.items || []
      this._latestConflictCheck = this._conflictChecks[0] || null
    } catch {
      this._conflictChecks = []
      this._latestConflictCheck = null
    }
  },

  _openConflictCheck(checkOrId) {
    const check = typeof checkOrId === "string"
      ? this._conflictChecks.find((item) => item.id === checkOrId)
      : checkOrId
    if (!check) {
      toast("检查记录暂不可用", "warning")
      return
    }
    showWritingConflictModal({
      check,
      novelId: state.currentProjectId,
      onStatusChanged: async () => {
        await this._refreshConflictChecks()
        await this._rerender()
      },
      onAiReviewComplete: async (updatedCheck) => {
        await this._refreshConflictChecks()
        await this._rerender()
        const refreshed = this._conflictChecks.find((item) => item.id === updatedCheck?.id) || updatedCheck
        if (refreshed) this._openConflictCheck(refreshed)
      },
      onSuggestionComplete: async (updatedItem) => {
        await this._refreshConflictChecks()
        await this._rerender()
        const refreshed = this._conflictChecks.find((item) => item.id === updatedItem?.check_id) || check
        if (refreshed) this._openConflictCheck(refreshed)
      },
      onApplySuggestion: (_itemId, text) => {
        this._insertTextAtCursor(text)
        toast("AI 建议草稿已插入当前正文", "success")
      },
      onLocate: (itemId) => this._locateConflictItem(check, itemId),
      onOpenSource: (itemId) => this._openConflictSource(check, itemId),
    })
  },

  _locateConflictItem(check, itemId) {
    const item = (check.items || []).find((entry) => entry.id === itemId)
    const editor = document.getElementById("writing-editor")
    const location = item?.location_json || {}
    const textRange = location.text_range || location
    if (!editor || typeof textRange.start !== "number") {
      toast("该问题暂无正文定位", "info")
      return
    }
    editor.focus()
    editor.setSelectionRange(textRange.start, textRange.end || textRange.start)
  },

  _openConflictSource(check, itemId) {
    const item = (check.items || []).find((entry) => entry.id === itemId)
    const location = item?.location_json || {}
    const openTarget = location.open_target || {}
    const openTargetKind = openTarget.kind
    if (openTargetKind === "text_range") {
      this._locateConflictItem(check, itemId)
      return
    }
    if (openTargetKind === "map_scene" || openTargetKind === "map_object") {
      this._openMapForCurrentScene()
      return
    }
    if (openTargetKind === "outline_scene") {
      router.navigate("outline", null)
      const hint = location.source?.label || openTarget.scene_id || "Scene"
      toast(`已打开大纲：${hint}`, "info")
      return
    }
    if (openTargetKind === "memory_chapter") {
      const chapterIndex = openTarget.chapter_index || location.source?.chapter_index || "-"
      const characterId = openTarget.character_id || location.source?.character_id || "-"
      showModalHtml("记忆来源", `
        <div class="writing-conflict-source-modal">
          <p><strong>章节</strong>：第 ${esc(chapterIndex)} 章</p>
          <p><strong>角色</strong>：${esc(characterId)}</p>
        </div>
      `, [{ text: "关闭", class: "btn-ghost", handler: closeModal }])
      return
    }
    if (item?.source_module === "world") {
      this._openMapForCurrentScene()
      return
    }
    if (item?.source_module === "outline") {
      router.navigate("outline", null)
      return
    }
    toast("该来源暂无可打开视图", "info")
  },

  async _publish() {
    if (this._publishProgress?.phase === "running" || this._publishTaskId) {
      toast("发布任务正在进行中", "info")
      return
    }

    const editor = document.getElementById("writing-editor")
    const titleInput = document.getElementById("writing-title-input")
    if (!editor) return

    const content = editor.value.trim()
    if (!content) { toast("草稿内容不能为空", "warning"); return }
    const title = titleInput ? titleInput.value.trim() : `第 ${this._currentChapter} 章`
    const currentScene = this._findCurrentScene()
    const canPublish = await this._confirmBeforePublish(currentScene)
    if (!canPublish) return

    const btnPublish = document.getElementById("btn-publish")
    const btnAutosave = document.getElementById("btn-autosave")
    if (btnPublish) btnPublish.disabled = true
    if (btnAutosave) btnAutosave.disabled = true

    try {
      const result = await api.writing.publish({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        scene_id: currentScene?.id || null,
        title,
        content,
      })

      this._currentContent = content
      this._currentTitle = title

      if (this._chapters[this._currentChapter]) {
        this._chapters[this._currentChapter].title = title
        this._chapters[this._currentChapter].status = result.draft?.status || "published"
        this._chapters[this._currentChapter].wordcount = content.length
        this._chapters[this._currentChapter].word_count = content.length
      }

      // 直接从发布结果获取 draftId，避免 _refreshVersions 偶发返回空版本
      const createdDraftId = result.draft?.id || null

      if (result.task_id) {
        this._publishTaskId = result.task_id
        this._publishProgress = { phase: "running", step: 0, message: "正在存入 RAG 系统...", showModal: false }
        this._startPublishPolling()
      }

      this._restoreSourceVersion = null
      this._lastSavedContent = content
      this._lastPublishStatus = "发布成功"
      await this._refreshVersions(this._currentChapter)
      this._lastPublishStatus = "发布成功"
      // 若 _refreshVersions 因竞态未设置 draftId，回退到发布结果
      if (!this._currentDraftId && createdDraftId) {
        this._currentDraftId = createdDraftId
        this._currentVersionNumber = result.draft?.version_number || 1
        this._currentUpdatedAt = result.draft?.updated_at || null
      }
      await this._rerender()
      toast("已发布", "success")
    } catch (err) {
      toast(err.message || "发布失败", "error")
      if (btnPublish) btnPublish.disabled = false
      if (btnAutosave) btnAutosave.disabled = false
    }
  },

  async _confirmBeforePublish(currentScene) {
    if (!state.currentProjectId || !this._currentChapter) return true
    let latest = null
    try {
      const result = await api.writing.listConflictChecks({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        scene_id: currentScene?.id || null,
        limit: 1,
      })
      latest = result.items?.[0] || null
    } catch {
      return true
    }
    if (!latest) {
      return await this._confirmAsync(
        "当前章节还没有剧情设定冲突检查记录。可以继续发布，也可以先运行检查。",
        "继续发布",
      )
    }
    const latestItems = Array.isArray(latest.items) ? latest.items : []
    const openHighCount = latestItems.length
      ? latestItems.filter((item) => item.severity === "high" && item.status === "open").length
      : (latest.summary_json?.open_high_count ?? 0)
    if (openHighCount > 0) {
      return await this._confirmAsync(
        `最近一次检查仍有 ${openHighCount} 个未处理高严重度问题。确认继续发布？`,
        "继续发布",
      )
    }
    return true
  },

  _confirmAsync(message, confirmText) {
    return new Promise((resolve) => {
      let settled = false
      const settle = (value) => {
        if (settled) return
        settled = true
        cleanup()
        resolve(value)
      }
      const onConfirm = () => settle(true)
      const onCancel = () => settle(false)

      const modalClose = document.getElementById("modal-close")
      const modalOverlay = document.getElementById("modal-overlay")
      const onCloseClick = onCancel
      const onOverlayClick = (event) => {
        if (event.target === event.currentTarget) onCancel()
      }
      const onKeyDown = (event) => {
        if (event.key === "Escape") onCancel()
      }
      let observer = null
      const cleanup = () => {
        modalClose?.removeEventListener("click", onCloseClick)
        modalOverlay?.removeEventListener("click", onOverlayClick)
        document.removeEventListener("keydown", onKeyDown, true)
        observer?.disconnect()
      }

      confirmAction(message, onConfirm, confirmText)
      setTimeout(() => {
        const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
        if (cancelBtn) cancelBtn.onclick = onCancel
      }, 50)

      modalClose?.addEventListener("click", onCloseClick)
      modalOverlay?.addEventListener("click", onOverlayClick)
      document.addEventListener("keydown", onKeyDown, true)
      if (modalOverlay && typeof MutationObserver !== "undefined") {
        observer = new MutationObserver(() => {
          if (modalOverlay.classList.contains("hidden")) onCancel()
        })
        observer.observe(modalOverlay, { attributes: true, attributeFilter: ["class"] })
      }
    })
  },

  _startPublishPolling() {
    if (this._publishTimer) clearInterval(this._publishTimer)
    const poll = async () => {
      if (!this._publishTaskId) { this._stopPublishPolling(); return }
      try {
        const task = await api.tasks.get(this._publishTaskId, state.currentProjectId)
        let needRerender = false

        if (task.progress !== undefined && task.progress !== null) {
          const p = parseFloat(task.progress)
          if (this._publishProgress.step !== p || this._publishProgress.phase !== task.status) {
            this._publishProgress.step = p
            this._publishProgress.phase = task.status
            if (p < 0.5) {
              this._publishProgress.message = "正在存入 RAG 系统..."
            } else if (p < 1.0) {
              this._publishProgress.message = "正在创建历史状态..."
            }
            needRerender = true
          }
        }

        if (task.status === "done" && this._publishProgress) {
          this._publishProgress.step = 1
          this._publishProgress.phase = "done"
          this._publishProgress.message = "发布完成"
          this._lastPublishStatus = "发布成功"
          this._updatePublishBar()
          this._stopPublishPolling()
          setTimeout(() => { this._publishProgress = null; this._rerender() }, 3000)
          return
        }

        if (task.status === "failed") {
          this._publishProgress.phase = "failed"
          const errMsg = sanitizeTaskErrorMessage(
            task.error_message || task.result?.error_message || task.result?.error,
            "publish_chapter",
          ) || "发布任务失败。草稿已保存，请稍后重试。"
          this._publishProgress.message = errMsg
          this._publishProgress.showModal = true
          this._updatePublishBar()
          this._stopPublishPolling()
          this._showPublishErrorModal(errMsg)
          return
        }

        this._updatePublishBar()
        if (needRerender) {
          await this._rerender()
        }
      } catch (err) {
        if (this._publishProgress) {
          const errMsg = sanitizeTaskErrorMessage(
            err?.message || "发布状态查询失败。草稿已保存，请稍后重试。",
            "publish_chapter",
          ) || "发布状态查询失败。草稿已保存，请稍后重试。"
          this._publishProgress.phase = "failed"
          this._publishProgress.message = errMsg
          this._publishProgress.showModal = true
          this._updatePublishBar()
          this._showPublishErrorModal(errMsg)
        }
        this._stopPublishPolling()
      }
    }
    poll()
    this._publishTimer = setInterval(poll, 2000)
  },

  _stopPublishPolling() {
    if (this._publishTimer) { clearInterval(this._publishTimer); this._publishTimer = null }
    this._publishTaskId = null
    const dot = document.getElementById("publish-status-dot")
    if (dot) dot.style.display = "none"
  },

  _updatePublishBar() {
    const publishBarEl = document.getElementById("writing-publish-bar-container")
    if (publishBarEl) publishBarEl.innerHTML = this._renderPublishBar()
    const dot = document.getElementById("publish-status-dot")
    if (dot && this._publishProgress && this._publishProgress.phase === "running") {
      dot.style.display = "inline-block"
    }
  },

  _showPublishErrorModal(msg) {
    this._errorModalVisible = true
    showModalHtml("发布失败", `
      <p>${esc(msg)}</p>
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">草稿已保存成功。您可以手动重试失败的步骤。</p>
      <div style="margin-top:12px;display:flex;gap:6px;justify-content:flex-end;">
        <button class="btn" onclick="closeModal()">关闭</button>
        <button class="btn btn-primary" id="btn-retry-failed">手动重试</button>
      </div>
    `)
    setTimeout(() => {
      const retryBtn = document.getElementById("btn-retry-failed")
      if (retryBtn) retryBtn.onclick = () => { closeModal(); this._retryPublish() }
    }, 100)
  },

  async _retryPublish() {
    if (!this._currentChapter) return
    this._publishTaskId = null
    this._publishProgress = { phase: "running", step: 0, message: "正在重试...", showModal: false }
    // 重新入队发布任务
    try {
      const result = await api.writing.publish({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        title: this._currentTitle || '',
        content: this._currentContent || '',
      })
      if (result.task_id) {
        this._publishTaskId = result.task_id
        this._startPublishPolling()
      }
      await this._rerender()
    } catch (err) {
      toast(err.message || "重试失败", "error")
      this._publishProgress = null
    }
  },

  _dismissPublishError() {
    this._publishProgress = null
    this._publishTaskId = null
    this._stopPublishPolling()
    this._rerender()
  },

  // ============================================================
  // 删除操作
  // ============================================================

  async _deleteVersion() {
    if (!this._currentDraftId || !this._currentChapter) return
    if (this._versions.length <= 1) {
      toast("不能删除唯一版本", "warning")
      return
    }

    const latestVer = this._versions[0]?.version_number
    if (this._currentVersionNumber === latestVer) {
      toast("不能删除最新版本", "warning")
      return
    }

    if (!confirm(`确定删除第 ${this._currentChapter} 章 v${this._currentVersionNumber}？`)) return

    try {
      await api.writing.deleteDraft(this._currentDraftId, state.currentProjectId)
      toast("版本已删除", "success")
      await this._refreshVersions(this._currentChapter)
      if (this._versions.length > 0) {
        const latest = this._versions[0]
        await this._switchVersion(latest.id, latest.version_number, true)
      }
      await this._rerender()
    } catch (err) {
      toast(err.message || "删除失败", "error")
    }
  },

  async _deleteChapter(chapterIndex) {
    if (!confirm(`确定删除第 ${chapterIndex} 章的全部版本？此操作不可恢复。`)) return

    try {
      await api.writing.deleteChapter(chapterIndex, state.currentProjectId)
      toast(`第 ${chapterIndex} 章已删除`, "success")
      delete this._chapters[chapterIndex]
      this._chapterList = this._chapterList.filter((i) => i !== chapterIndex)

      if (this._currentChapter === chapterIndex) {
        this._currentChapter = null
        this._currentDraftId = null
        this._currentContent = null
        this._currentTitle = null
        this._versions = []
        delete state.viewStates.writing
      }

      await this._rerender()
    } catch (err) {
      toast(err.message || "删除失败", "error")
    }
  },

  _runChapterBulkAction(action) {
    if (action !== "delete-chapters") return
    const selected = selectedItemsFrom(
      this._chapterList.map((index) => ({ id: String(index), index })),
      getBulkSelection(this, "writing-chapters"),
    )
    if (!selected.length) {
      toast("请先选择章节", "warning")
      return
    }
    return confirmAction(`确定删除选中的 ${selected.length} 个章节及其全部版本？此操作不可恢复。`, async () => {
      const result = await runBulkAction(selected, async (item) => {
        await api.writing.deleteChapter(item.index, state.currentProjectId)
      })
      for (const item of result.success) {
        delete this._chapters[item.index]
      }
      const deleted = new Set(result.success.map((item) => item.index))
      this._chapterList = this._chapterList.filter((index) => !deleted.has(index))
      if (deleted.has(this._currentChapter)) {
        this._currentChapter = null
        this._currentDraftId = null
        this._currentContent = null
        this._currentTitle = null
        this._versions = []
        delete state.viewStates.writing
      }
      clearBulkSelection(this, "writing-chapters")
      toast(bulkResultMessage(result, "批量删除章节", (item) => `第 ${item.index} 章`), result.failed.length ? "warning" : "success")
      await this._rerender()
    }, "确认删除")
  },

  // ============================================================
  // Scene 导航
  // ============================================================

  _selectScene(sceneId) {
    this._currentSceneId = sceneId
    const scene = this._scenes.find((s) => s.id === sceneId)
    if (!scene) return

    const chIds = (scene.chapter_ids || []).map((id) => parseInt(id, 10)).filter((n) => !isNaN(n))
    const firstChapter = chIds.length > 0 ? Math.min(...chIds) : null

    if (firstChapter && this._chapters[firstChapter]) {
      this._selectChapter(firstChapter)
    } else {
      this._currentChapter = null
      this._rerender()
    }
  },

  async _showSplitSceneForm() {
    if (!this._currentChapter) { toast("请先选择章节", "warning"); return }
    const currentScene = this._findCurrentScene()
    if (!currentScene) { toast("当前章节未关联 Scene", "warning"); return }

    const editor = document.getElementById("writing-editor")
    const cursorPos = editor ? (editor.selectionStart || 0) : 0
    const contentLength = editor ? (editor.value || "").length : 0

    if (contentLength < 2) {
      toast("当前章节内容太短，无法断章", "warning")
      return
    }

    const html = `
      <div class="form-group">
        <label>断章位置（字符 offset）</label>
        <input class="form-input" id="split-pos" type="number" min="1" max="${Math.max(1, contentLength - 1)}" value="${cursorPos}" />
      </div>
      <div class="form-group">
        <label>当前 Scene：${esc(currentScene.title || "未命名")}</label>
      </div>
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">
        从当前章节的指定 offset 处切分为新章节，并同步更新 Scene chunk。
      </p>
    `
    showModalHtml("断章", html, [{
      text: "确认断章", class: "btn-primary",
      handler: async () => {
        const splitPos = parseInt(document.getElementById("split-pos")?.value || "", 10)
        if (!splitPos || splitPos < 1) { toast("请输入有效的断章位置", "warning"); return }
        if (splitPos >= contentLength) { toast("断章位置必须小于正文长度", "warning"); return }
        closeModal()
        await this._doSplitScene(splitPos, currentScene)
      },
    }])
  },

  async _doSplitScene(splitPos, currentScene, retried = false) {
    try {
      // 确保当前章节的最新草稿已加载，避免注入状态或缓存导致 draft id 不一致
      const latestDraftId = this._versions[0]?.id
      const hasLatestDraft = latestDraftId && latestDraftId === this._currentDraftId
      if (!hasLatestDraft && this._currentChapter && !retried) {
        await this._selectChapter(this._currentChapter)
        return this._doSplitScene(splitPos, currentScene, true)
      }

      await this._saveBeforeNavigate()
      const editor = document.getElementById("writing-editor")
      if (editor && this._currentContent !== editor.value) {
        this._currentContent = editor.value
      }

      const result = await api.writing.splitChapter(
        this._currentChapter,
        { split_pos: splitPos, source_scene_id: currentScene.id },
        state.currentProjectId,
      )
      this._scenes = result.scenes || this._scenes
      this._chapters[result.source_chapter_index] = {
        title: result.source_draft?.title,
        draftCount: (this._chapters[result.source_chapter_index]?.draftCount || 0) + 1,
      }
      this._chapters[result.new_chapter_index] = {
        title: result.new_draft?.title,
        draftCount: 1,
      }
      this._chapterList = [...new Set([...this._chapterList, result.new_chapter_index])].sort((a, b) => a - b)
      this._currentChapter = result.new_chapter_index
      this._currentDraftId = result.new_draft.id
      this._currentContent = result.new_draft.content || ""
      this._currentTitle = result.new_draft.title || ""
      this._currentVersionNumber = result.new_draft.version_number
      this._currentUpdatedAt = result.new_draft.updated_at || null
      toast("断章完成", "success")
      await this._rerender()
    } catch (err) {
      toast(err.message || "断章失败", "error")
    }
  },

  async _extractChapterCards() {
    if (!this._chapterList.length) { toast("没有可分析的章节", "warning"); return }
    const firstCh = this._chapterList[0]
    const lastCh = this._chapterList[this._chapterList.length - 1]
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="extract-start" type="number" min="1" value="${firstCh}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="extract-end" type="number" min="1" value="${lastCh}" />
      </div>
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">
        调用 AI 分析章节内容，生成 Scene 卡（场景目标、冲突、情感节奏等）。
      </p>
    `
    showModalHtml("AI 提取章节卡", formHtml, [{
      text: "开始提取", class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("extract-end")?.value || "10", 10)
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        closeModal()
        try {
          const confirmation = await confirmAiReference({
            novel_id: state.currentProjectId,
            action: "outline.chapter_scenes.extract",
            task: "章节/Scene 卡提取",
            scope: "chapter",
            chapter_index: start,
            include_pending_objects: true,
          })
          toast("章节/Scene 卡提取任务已提交", "info")
          await api.outline.extractChapterScenes({
            novel_id: state.currentProjectId,
            context_confirmation_id: confirmation.id,
            chapter_index: start,
            start_chapter: start,
            end_chapter: end,
          })
          this._scenes = await api.outline.listScenesOrdered(state.currentProjectId) || []
          toast("章节/Scene 卡提取已进入后台", "success")
          await this._rerender()
        } catch (err) {
          toast(err.message || "提取失败", "error")
        }
      },
    }])
  },

  async _generateDraft() {
    if (!state.currentProjectId || !this._currentChapter) {
      toast("请先选择章节", "warning")
      return
    }
    try {
      const confirmation = await confirmAiReference({
        novel_id: state.currentProjectId,
        action: "writing.generate",
        task: "生成正文候选草稿",
        scope: "chapter",
        chapter_index: this._currentChapter,
        include_pending_objects: true,
      })
      const result = await api.writing.generate({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        title: this._currentTitle || `第 ${this._currentChapter} 章`,
        instruction: confirmation.user_note || "",
        context_confirmation_id: confirmation.id,
      })
      toast(`AI 生成草稿任务已提交：${result.task_id || result.id || ""}`, "success")
    } catch (err) {
      if (err.message && err.message.includes("取消")) return
      toast(err.message || "AI 生成草稿失败", "error")
    }
  },

  // ============================================================
  // 深度导入
  // ============================================================

  _showAutoExtractionForm(stage = "scenes") {
    const config = this._stageConfig(stage)
    const lastChapter = this._chapterList.length > 0
      ? Math.max(...this._chapterList) : 10
    const firstChapter = this._chapterList.length > 0
      ? Math.min(...this._chapterList) : 1
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="auto-extract-start" type="number" min="1" value="${firstChapter}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="auto-extract-end" type="number" min="1" value="${lastChapter}" />
      </div>
      ${stage === "scenes" ? `
        <label style="display:flex;gap:8px;align-items:center;font-size:12px;color:var(--text-body);margin-top:8px;">
          <input id="auto-extract-high-quality" type="checkbox" />
          更高质量 <span style="color:var(--text-dim);">需要标准提取约8倍时间</span>
        </label>
      ` : ""}
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">
        ${esc(config.label)}会在所选章节范围内创建或补充对应结构资产。
      </p>
    `
    showModalHtml(config.label, formHtml, [{
      text: "开始提取", class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("auto-extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("auto-extract-end")?.value || "10", 10)
        const highQuality = !!document.getElementById("auto-extract-high-quality")?.checked
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        closeModal()
        await this._submitAutoExtractionStage(stage, start, end, false, highQuality)
      },
    }])
  },

  _showDeepImportForm() {
    this._showAutoExtractionForm("scenes")
  },

  async _submitAutoExtractionStage(stage, startChapter, endChapter, force = false, highQuality = false) {
    const config = this._stageConfig(stage)
    try {
      const result = await api.imports.startStage(
        stage, state.currentProjectId, startChapter, endChapter, force, highQuality,
      )
      if (result.requires_confirmation) {
        const confirmed = await new Promise((resolve) => {
          confirmAction(result.warning, () => resolve(true), "确认覆盖")
          // Add cancel handler
          setTimeout(() => {
            const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
            if (cancelBtn) cancelBtn.onclick = () => resolve(false)
          }, 50)
        })
        if (!confirmed) return
        await this._submitAutoExtractionStage(stage, startChapter, endChapter, true, highQuality)
        return
      }

      if (!result.task_id) {
        toast(result.message || `${config.label}未启动`, "warning")
        return
      }

      this._deepImportTaskId = result.task_id
      this._deepImportProgress = {
        workflowType: config.taskType,
        stage,
        label: config.label,
        phase: "running", step: config.initialStep,
        message: config.initialMessage, percent: 0,
        degraded: false, degradedBatches: [], phaseError: "",
        phaseErrors: [], qualityStatus: "pending", auditSummary: {}, snapshotHealthSummary: {},
      }
      this._persistDeepImportWorkflow(
        result.task_id,
        startChapter,
        endChapter,
        stage,
        highQuality,
      )
      toast(`${config.label}已启动`, "success")
      await this._rerender()
      this._startDeepImportPolling()
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  async _submitDeepImport(startChapter, endChapter, force = false, highQuality = false) {
    return this._submitAutoExtractionStage(
      "scenes",
      startChapter,
      endChapter,
      force,
      highQuality,
    )
  },

  _startDeepImportPolling() {
    if (this._deepImportTimer) clearInterval(this._deepImportTimer)
    const poll = async () => {
      if (!this._deepImportTaskId) { this._stopDeepImportPolling(); return }
      try {
        const task = await api.tasks.get(this._deepImportTaskId)
        const result = task.result || {}
        const steps = result.completed_steps || []
        const workflowType = result.workflow_type || task.task_type || this._deepImportProgress?.workflowType || "deep_import"
        const stage = result.stage || this._deepImportProgress?.stage || this._stageFromWorkflowType(workflowType)
        const label = this._deepImportProgress?.label || this._stageConfig(stage).label

        let percent = typeof task.progress === "number"
          ? (task.progress <= 1 ? Math.round(task.progress * 100) : Math.round(task.progress))
          : 0
        let stepLabel = ""
        if (workflowType !== "deep_import") {
          if (task.status === "done" || result.phase === "done") percent = 100
          stepLabel = result.current_step ? `Phase: ${result.current_step}` : label
        } else if (!steps.includes("scene_segmentation")) {
          stepLabel = "Phase 1/3: Scene 切分"
          percent = Math.min(40, (result.phase1_completed_batches || 0) * 8)
        } else if (!steps.includes("entity_extraction")) {
          stepLabel = "Phase 2/3: 实体提取"
          percent = 40 + Math.min(40, (result.phase2_completed_scenes || 0) * 4)
        } else if (!steps.includes("structure_analysis")) {
          stepLabel = "Phase 3/3: 结构分析"
          percent = 80
        } else {
          stepLabel = "完成"
          percent = 100
        }

        this._deepImportProgress = {
          ...this._buildDeepImportProgressFromTask(task, result, percent, stepLabel),
          workflowType,
          stage,
          label,
          phase: result.phase || task.status,
          step: result.current_step || "",
          message: result.message || task.status,
          percent,
          stepLabel,
          degraded: result.degraded || false,
          degradedBatches: result.degraded_batches || [],
          phaseError: result.phase_error || result.error || task.error_message || "",
          phaseErrors: result.phase_errors || [],
          qualityStatus: result.quality_status || (result.degraded ? "partial" : "pending"),
          auditSummary: result.audit_summary || result.auditSummary || {},
          snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary || result.audit_summary || result.auditSummary || {},
        }

        if (this._hasDeepImportRecoveryPrompt(this._deepImportProgress)) {
          this._pauseDeepImportPolling()
          await this._rerender()
          return
        }

        if (task.status === "done" || result.phase === "done") {
          this._deepImportProgress.percent = 100
          this._deepImportProgress.phase = "done"
          this._stopDeepImportPolling()
          if (this._deepImportProgress.qualityStatus === "partial") {
            toast(`${label}部分完成，请查看降级原因`, "warning")
          } else {
            toast(`${label}完成！`, "success")
          }
          // 深度导入会创建 / 更新 Scene，需要清空 API 缓存和视图 DOM 缓存，
          // 否则 KeepAlive 视图会显示旧数据（看不到新生成的 Scene）。
          api.clearCache()
          setTimeout(() => {
            this._deepImportProgress = null
            router.refresh()
          }, 1500)
          return
        }
        if (task.status === "failed") {
          this._deepImportProgress.phase = "failed"
          this._deepImportProgress.phaseError = (
            result.phase_error || result.error || task.error_message || this._deepImportProgress.message
          )
          this._stopDeepImportPolling()
          toast(`${label}失败`, "error")
          setTimeout(() => { this._deepImportProgress = null; this._rerender() }, 5000)
          return
        }
        await this._rerender()
        this._deepImportPollFailures = 0
      } catch (err) {
        this._deepImportPollFailures += 1
        if (this._deepImportPollFailures >= 5) {
          this._stopDeepImportPolling()
          toast(`自动提取状态轮询连续失败 ${this._deepImportPollFailures} 次，已停止。请刷新后重试。`, "error")
        }
      }
    }
    this._deepImportPollFailures = 0
    this._deepImportTimer = setInterval(poll, 3000)
  },

  _stopDeepImportPolling() {
    if (this._deepImportTimer) { clearInterval(this._deepImportTimer); this._deepImportTimer = null }
    const taskId = this._deepImportTaskId
    this._deepImportTaskId = null
    this._clearDeepImportWorkflow(taskId)
  },

  _pauseDeepImportPolling() {
    if (this._deepImportTimer) {
      clearInterval(this._deepImportTimer)
      this._deepImportTimer = null
    }
  },

  _renderDeepImportBar() {
    if (!this._deepImportProgress) return ""
    const progress = this._normalizeDeepImportProgress()
    const actionsHtml = progress.failed
      ? `<button class="btn btn-sm" data-action="dismiss-deep-import" style="font-size:11px;">关闭</button>`
      : ""
    const recoveryHtml = this._renderDeepImportRecoveryPrompt()
    const currentPositionHtml = this._renderDeepImportCurrentPosition()
    const qualityStatsHtml = this._renderDeepImportQualityStats()
    const aliveClass = progress.terminal ? "" : "deep-import-progress--alive"
    return renderFixedProgress(progress, {
      offset: 40,
      title: progress.label || this._deepImportProgress?.label || "自动提取",
      message: progress.message,
      showTaskId: false,
      className: aliveClass,
      actionsHtml: [
        currentPositionHtml,
        qualityStatsHtml,
        recoveryHtml,
        this._renderDeepImportAuditSummary(),
        actionsHtml,
      ].filter(Boolean).join(""),
    })
  },

  _renderDeepImportCurrentPosition() {
    const p = this._deepImportProgress || {}
    const fields = [
      ["阶段", p.currentPhase],
      ["Round", p.currentRound],
      ["章节范围", p.currentChapterRange],
      ["当前章节", p.currentChapter],
      ["Scene candidate", p.currentSceneCandidateId],
      ["窗口", p.currentWindow],
      ["操作", p.currentOperation],
      ["当前项", p.currentItem?.kind],
      ["进度", p.currentItem?.total ? `${p.currentItem.completed || 0}/${p.currentItem.total}` : ""],
    ].filter(([, value]) => value !== null && value !== undefined && value !== "")
    if (fields.length === 0) return ""
    return `
      <div class="deep-import-current-position">
        ${fields.map(([label, value]) => `
          <span class="deep-import-current-position__item">${esc(label)}：${esc(value)}</span>
        `).join("")}
      </div>
    `
  },

  _renderDeepImportQualityStats() {
    const p = this._deepImportProgress || {}
    const stats = p.qualityStats && typeof p.qualityStats === "object"
      ? p.qualityStats
      : {}
    const currentKey = p.currentPhase && stats[p.currentPhase]
      ? p.currentPhase
      : this._pickDeepImportQualityStatsKey(stats)
    const currentStats = currentKey ? stats[currentKey] : null
    if (!currentStats || typeof currentStats !== "object") return ""

    const statLabels = {
      total_batches: "请求数",
      total_windows: "窗口数",
      completed_batches: "已完成",
      completed_windows: "已完成",
      success: "成功",
      failed: "失败",
      final_422: "422",
      final_422_batches: "422",
      timeout: "timeout",
      schema_error: "schema",
      empty_result: "空结果",
      fallback_scene_count: "fallback Scene",
      fused_scene_count: "融合 Scene",
      needs_review_scene_count: "待复核",
    }
    const orderedKeys = [
      "total_batches",
      "total_windows",
      "completed_batches",
      "completed_windows",
      "success",
      "failed",
      "final_422",
      "final_422_batches",
      "timeout",
      "schema_error",
      "empty_result",
      "fallback_scene_count",
      "fused_scene_count",
      "needs_review_scene_count",
    ]
    const items = orderedKeys
      .filter((key) => currentStats[key] !== undefined && currentStats[key] !== null)
      .map((key) => {
        return `<span class="deep-import-current-position__item">${esc(statLabels[key] || key)}：${esc(currentStats[key])}</span>`
      })
    const rate = currentStats.final_422_rate
    if (rate !== undefined && rate !== null) {
      const percent = Number(rate) <= 1 ? Number(rate) * 100 : Number(rate)
      items.push(`<span class="deep-import-current-position__item">422 率：${esc(`${percent.toFixed(0)}%`)}</span>`)
    }
    if (items.length === 0) return ""
    return `
      <div class="deep-import-current-position" aria-label="深度导入质量统计">
        ${items.join("")}
      </div>
    `
  },

  _pickDeepImportQualityStatsKey(stats) {
    for (const key of ["phase1b", "phase1a", "phase0", "scene_commit"]) {
      if (stats[key]) return key
    }
    return Object.keys(stats)[0] || null
  },

  _renderDeepImportRecoveryPrompt() {
    const p = this._deepImportProgress || {}
    if (!this._hasDeepImportRecoveryPrompt(p)) return ""
    const summary = p.recoverySummary && typeof p.recoverySummary === "object"
      ? p.recoverySummary
      : {}
    const summaryLabels = {
      last_checkpoint: "检查点",
      current_phase: "阶段",
      current_chapter: "当前章节",
      current_chapter_range: "章节范围",
      committed_scenes: "已写入 Scene",
      deprecated_scenes: "已废弃 Scene",
      committed_entities: "已写入实体",
      deprecated_entities: "已废弃实体",
      pending_scene_candidates: "待处理候选",
    }
    const summaryItems = Object.entries(summary)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .slice(0, 6)
      .map(([key, value]) => {
        const label = summaryLabels[key] || key
        return `<span class="deep-import-recovery__meta-item">${esc(label)}：${esc(value)}</span>`
      })
      .join("")
    return `
      <div class="deep-import-recovery" role="status">
        <div class="deep-import-recovery__body">
          <strong>自动提取需要恢复</strong>
          <span>检测到任务中断。可以继续原任务，或放弃恢复并交给后端清理本次自动写入资产。</span>
        </div>
        ${summaryItems ? `<div class="deep-import-recovery__meta">${summaryItems}</div>` : ""}
        <div class="deep-import-recovery__actions">
          <button class="btn btn-sm btn-primary" data-action="resume-deep-import" style="font-size:11px;">继续</button>
          <button class="btn btn-sm" data-action="abandon-deep-import" style="font-size:11px;">放弃恢复</button>
        </div>
      </div>
    `
  },

  _renderDeepImportAuditSummary() {
    const summary = this._deepImportProgress?.snapshotHealthSummary
      || this._deepImportProgress?.auditSummary
      || {}
    if (summary && typeof summary.total_snapshots === "number") {
      const byStatus = summary.by_status || {}
      const total = summary.total_snapshots || 0
      if (total <= 0) return ""
      const succeeded = byStatus.succeeded || 0
      const failed = byStatus.failed || 0
      const running = byStatus.running || 0
      const stale = summary.stale_running_count || 0
      const runningText = running > 0 ? ` · 运行中 ${running}` : ""
      const staleText = stale > 0 ? ` · 超时 ${stale}` : ""
      return `
        <span style="font-size:11px;color:var(--text-dim);margin-right:8px;">
          快照健康摘要：共 ${total} 条 · 成功 ${succeeded} · 失败 ${failed}${runningText}${staleText}
        </span>
        <button class="btn btn-sm" data-action="view-deep-import-audit" style="font-size:11px;">查看快照状态</button>
      `
    }

    const phaseSummaries = Object.values(summary).filter((item) => item && typeof item === "object")
    if (phaseSummaries.length === 0) return ""
    const total = phaseSummaries.reduce((sum, item) => sum + (item.snapshot_count || 0), 0)
    if (total <= 0) return ""
    const succeeded = phaseSummaries.reduce((sum, item) => sum + (item.succeeded || 0), 0)
    const failed = phaseSummaries.reduce((sum, item) => sum + (item.failed || 0), 0)
    const failedScenes = phaseSummaries
      .flatMap((item) => Array.isArray(item.failed_scenes) ? item.failed_scenes : [])
      .filter((item) => item !== null && item !== undefined)
    const failedSceneText = failedScenes.length > 0 ? ` · 失败 Scene：${failedScenes.join(", ")}` : ""
    return `
      <span style="font-size:11px;color:var(--text-dim);margin-right:8px;">
        快照健康摘要：共 ${total} 条 · 成功 ${succeeded} · 失败 ${failed}${esc(failedSceneText)}
      </span>
      <button class="btn btn-sm" data-action="view-deep-import-audit" style="font-size:11px;">查看快照状态</button>
    `
  },

  _normalizeDeepImportProgress() {
    const p = this._deepImportProgress || {}
    const needsRecovery = this._hasDeepImportRecoveryPrompt(p)
    const status = needsRecovery
      ? "running"
      : p.phase === "failed"
        ? "failed"
        : p.phase === "done"
          ? "done"
          : p.phase === "cancelled"
            ? "cancelled"
            : "running"
    const degradedBatches = Array.isArray(p.degradedBatches) ? p.degradedBatches : []
    const phaseErrors = Array.isArray(p.phaseErrors) ? p.phaseErrors : []
    const phaseErrorText = phaseErrors
      .map((item) => item && (item.message || item.error_kind || item.phase || item.error))
      .filter(Boolean)
      .slice(0, 2)
      .join("；")
    const isPartial = p.qualityStatus === "partial"
    const warnings = []
    if (isPartial && !p.degraded) warnings.push("部分完成")
    if (p.degraded) warnings.push("部分批次降级完成")
    if (degradedBatches.length > 0) warnings.push(`降级批次：${degradedBatches.join(", ")}`)
    if (p.phaseError && status !== "failed") warnings.push(`阶段错误：${p.phaseError}`)
    if (phaseErrorText && status !== "failed") warnings.push(`阶段错误：${phaseErrorText}`)
    if (p.phase1aFallback) warnings.push("自动整理失败，已使用质量补强结果继续导入")

    return normalizeTaskProgress({
      task_id: this._deepImportTaskId || "deep_import",
      task_type: p.workflowType || "deep_import",
      status,
      progress: typeof p.percent === "number" ? p.percent : null,
      error_message: status === "failed" ? (p.message || p.phaseError || phaseErrorText || "自动提取失败") : null,
      result: {
        message: needsRecovery
          ? "自动提取中断，需要选择继续或放弃恢复"
          : p.stepLabel || p.message || "自动提取中...",
        warnings,
        summary: isPartial ? "部分完成" : p.degraded ? "部分降级完成" : null,
      },
    }, p.workflowType || "deep_import")
  },

  _buildDeepImportProgressFromTask(task, result = {}, percent = null, stepLabel = "") {
    const recoverySummary = result.recovery_summary || result.recoverySummary || {}
    return {
      phase: result.phase || task?.status || "running",
      workflowType: result.workflow_type || task?.task_type || "deep_import",
      stage: result.stage || null,
      label: result.stage ? this._stageConfig(result.stage).label : null,
      step: result.current_step || "",
      message: result.message || task?.status || "自动提取中...",
      percent,
      stepLabel,
      degraded: result.degraded || false,
      degradedBatches: result.degraded_batches || [],
      phaseError: result.phase_error || result.error || task?.error_message || "",
      phaseErrors: result.phase_errors || [],
      qualityStatus: result.quality_status || (result.degraded ? "partial" : "pending"),
      auditSummary: result.audit_summary || result.auditSummary || {},
      snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary || result.audit_summary || result.auditSummary || {},
      currentPhase: result.current_phase || null,
      currentRound: result.current_round || null,
      currentChapterRange: result.current_chapter_range || null,
      currentChapter: result.current_chapter ?? null,
      currentSceneCandidateId: result.current_scene_candidate_id || null,
      currentWindow: result.current_window || null,
      currentOperation: result.current_operation || null,
      currentItem: result.current_item || {},
      qualityStats: result.quality_stats || {},
      degradedReason: result.degraded_reason || "",
      phase1aFallback: result.phase1a_fallback || false,
      recoverySummary,
      interrupted: result.interrupted || false,
      recoverable: result.recoverable || false,
      recoveryRequired: result.recovery_required || false,
    }
  },

  _hasDeepImportRecoveryPrompt(progress = this._deepImportProgress) {
    return Boolean(progress?.recoveryRequired || progress?.interrupted || progress?.recoverable)
  },

  async _resumeDeepImportRecovery() {
    const taskId = this._deepImportTaskId
    if (!taskId) return
    try {
      const response = await api.imports.resumeDeepImport(taskId)
      const result = response?.result || {}
      this._deepImportTaskId = response?.task_id || taskId
      this._deepImportProgress = {
        ...this._buildDeepImportProgressFromTask(
          { status: response?.status || "running" },
          result,
          this._deepImportProgress?.percent ?? null,
          this._deepImportProgress?.stepLabel || "恢复进度中...",
        ),
        recoveryRequired: false,
        interrupted: false,
        recoverable: false,
      }
      this._startDeepImportPolling()
      await this._rerender()
      toast("已继续深度导入恢复", "success")
    } catch (err) {
      toast(err.message || "继续恢复失败", "error")
    }
  },

  async _abandonDeepImportRecovery() {
    const taskId = this._deepImportTaskId
    if (!taskId) return
    let confirmedWork = Promise.resolve()
    const message = "确认放弃深度导入恢复？后端会删除/废弃已写入的 Scene/实体，并停止继续恢复。"
    confirmAction(message, () => {
      confirmedWork = (async () => {
        try {
          const response = await api.imports.abandonDeepImport(taskId)
          const summary = response?.cleanup_summary || response?.cleanupSummary || {}
          const scenes = summary.deprecated_scenes ?? summary.scenes ?? 0
          const entities = summary.deprecated_entities ?? summary.entities ?? 0
          this._deepImportProgress = null
          this._deepImportTaskId = null
          this._clearDeepImportWorkflow(taskId)
          await this._rerender()
          toast(`已放弃恢复：Scene ${scenes} 个，实体 ${entities} 个`, "success")
        } catch (err) {
          toast(err.message || "放弃恢复失败", "error")
        }
      })()
    }, "确认放弃")
    return confirmedWork
  },

  _persistDeepImportWorkflow(
    taskId,
    startChapter,
    endChapter,
    stage = "scenes",
    highQuality = false,
  ) {
    const config = this._stageConfig(stage)
    persistActiveWorkflow({
      taskId,
      workflowType: config.taskType,
      label: config.label,
      projectId: state.currentProjectId,
      view: "writing",
      meta: { startChapter, endChapter, stage, highQuality },
    })
  },

  _clearDeepImportWorkflow(taskId) {
    clearActiveWorkflow(taskId)
    try { localStorage.removeItem("novel_deepImportTaskId") } catch {} // eslint-disable-line no-empty
  },

  _dismissDeepImport() {
    const taskId = this._deepImportTaskId
    this._deepImportProgress = null
    this._deepImportTaskId = null
    this._clearDeepImportWorkflow(taskId)
    this._rerender()
  },

  _showDeepImportAuditDetails() {
    const summary = this._deepImportProgress?.snapshotHealthSummary
      || this._deepImportProgress?.auditSummary
      || {}
    const phaseLabels = {
      entity_extraction: "Phase 2 实体提取",
      structure_analysis: "Phase 3 结构分析",
    }
    if (summary && typeof summary.total_snapshots === "number") {
      const byPhase = summary.by_phase || {}
      const latestFailure = summary.latest_failure
      const failureHtml = latestFailure
        ? `<div style="color:var(--warning);font-size:11px;margin-top:8px;">最近失败：${esc(latestFailure.phase || "unknown")} · ${esc(latestFailure.error_kind || "failed")}</div>`
        : ""
      const retainedHtml = summary.retained_rendered_context_count
        ? `<div style="color:var(--text-dim);font-size:11px;margin-top:8px;">完整上下文保留：${summary.retained_rendered_context_count} 条</div>`
        : ""
      const rows = Object.entries(byPhase)
        .filter(([, item]) => item && typeof item === "object")
        .map(([phase, item]) => `
          <div style="padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="font-weight:600;margin-bottom:4px;">${esc(phaseLabels[phase] || phase)}</div>
            <div style="font-size:12px;color:var(--text-dim);">
              快照 ${(item.running || 0) + (item.succeeded || 0) + (item.failed || 0)} 条 · 成功 ${item.succeeded || 0} · 失败 ${item.failed || 0} · 运行中 ${item.running || 0}
            </div>
          </div>
        `).join("")
      showModalHtml(
        "深度导入快照状态",
        rows || failureHtml || retainedHtml
          ? `${rows}${failureHtml}${retainedHtml}`
          : '<p style="color:var(--text-dim);">暂无快照健康摘要</p>'
      )
      return
    }
    const rows = Object.entries(summary)
      .filter(([, item]) => item && typeof item === "object")
      .map(([phase, item]) => {
        const failedScenes = Array.isArray(item.failed_scenes) && item.failed_scenes.length > 0
          ? `<div style="color:var(--warning);font-size:11px;margin-top:4px;">失败 Scene：${esc(item.failed_scenes.join(", "))}</div>`
          : ""
        const retention = item.retained_rendered_context_count
          ? `<div style="color:var(--text-dim);font-size:11px;margin-top:4px;">完整上下文保留：${item.retained_rendered_context_count} 条</div>`
          : ""
        return `
          <div style="padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="font-weight:600;margin-bottom:4px;">${esc(phaseLabels[phase] || phase)}</div>
            <div style="font-size:12px;color:var(--text-dim);">
              快照 ${item.snapshot_count || 0} 条 · 成功 ${item.succeeded || 0} · 失败 ${item.failed || 0}
            </div>
            ${failedScenes}
            ${retention}
          </div>
        `
      }).join("")
    showModalHtml("深度导入快照状态", rows || '<p style="color:var(--text-dim);">暂无快照健康摘要</p>')
  },

  _bindCockpitDrag() {
    const panel = document.querySelector(".scene-cockpit")
    if (!panel || !state.currentProjectId) return
    let draggingKey = null
    panel.querySelectorAll(".scene-cockpit-module").forEach((module) => {
      module.ondragstart = (event) => {
        draggingKey = module.getAttribute("data-cockpit-module")
        event.dataTransfer?.setData("text/plain", draggingKey || "")
      }
      module.ondragover = (event) => event.preventDefault()
      module.ondrop = (event) => {
        event.preventDefault()
        const targetKey = module.getAttribute("data-cockpit-module")
        if (!draggingKey || !targetKey || draggingKey === targetKey) return
        const modules = [...panel.querySelectorAll(".scene-cockpit-module")]
        const order = modules.map((el) => el.getAttribute("data-cockpit-module"))
        const from = order.indexOf(draggingKey)
        const to = order.indexOf(targetKey)
        if (from < 0 || to < 0) return
        order.splice(to, 0, order.splice(from, 1)[0])
        saveSceneCockpitOrder(state.currentProjectId, order.filter(Boolean))
        this._rerender()
      }
    })
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindEvents() {
    bindWorkspaceClick(this, {
      "select-chapter": (_e, t) => this._selectChapter(parseInt(t.getAttribute("data-chapter"), 10)),
      "bulk-toggle-one": (e, t) => {
        e.stopPropagation()
        toggleBulkSelection(this, t.getAttribute("data-scope"), t.getAttribute("data-id"), t.checked)
        syncBulkSelectionUi(this, t.getAttribute("data-scope"))
      },
      "bulk-clear": (_e, t) => {
        const scope = t.getAttribute("data-scope")
        clearBulkSelection(this, scope)
        syncBulkSelectionUi(this, scope)
      },
      "bulk-run": (_e, t) => this._runChapterBulkAction(t.getAttribute("data-bulk-action")),
      "select-visible-chapters": () => {
        toggleAllBulkSelection(this, "writing-chapters", this._chapterList.map(String), true)
        syncBulkSelectionUi(this, "writing-chapters")
      },
      "toggle-bulk-actions": () => { this._showBulkActions = !this._showBulkActions; this._rerender() },
      "next-chapter": () => this._switchChapter(1),
      "new-chapter": () => this._newChapter(),
      "delete-chapter": (_e, t) => this._deleteChapter(parseInt(t.getAttribute("data-chapter"), 10)),
      "autosave": () => this._autosave(),
      "publish": () => this._publish(),
      "toggle-focus-mode": () => this._toggleFocusMode(),
      "toggle-outline-float": () => this._toggleOutlineFloat(),
      "close-outline-float": () => this._closeOutlineFloat(),
      "ai-continue": () => this._aiContinue(),
      "export-chapter": () => this._exportChapter(),
      "save-mobile-note": () => this._saveMobileNote(),
      "switch-desktop-mode": () => this._switchDesktopMode(),
      "ai-generate-draft": () => this._generateDraft(),
      "restore-from-version": () => this._restoreFromVersion(),
      "version-history": () => this._showVersionHistory(),
      "delete-version": () => this._deleteVersion(),
      "dismiss-publish-error": () => this._dismissPublishError(),
      "run-conflict-check": () => this._runConflictCheck(),
      "open-conflict-check": (_e, t) => this._openConflictCheck(t.getAttribute("data-check-id")),
      "auto-extract-stage": (_e, t) => this._showAutoExtractionForm(t.getAttribute("data-stage") || "scenes"),
      "deep-import": () => this._showDeepImportForm(),
      "open-map": () => this._openMapForCurrentScene(),
      "dismiss-deep-import": () => this._dismissDeepImport(),
      "resume-deep-import": () => this._resumeDeepImportRecovery(),
      "abandon-deep-import": () => this._abandonDeepImportRecovery(),
      "view-deep-import-audit": () => this._showDeepImportAuditDetails(),
      "open-outline": () => router.navigate("outline", null),
      "open-scene-workbench": () => {
        const scene = this._findCurrentScene()
        router.navigate("scene", scene?.id || null)
      },
      "split-scene": () => this._showSplitSceneForm(),
      "extract-cards": () => this._extractChapterCards(),
      "select-scene": (_e, t) => this._selectScene(t.getAttribute("data-scene-id")),
      "toggle-cockpit-module": (_e, t) => {
        const module = t.closest(".scene-cockpit-module")
        if (module) module.classList.toggle("is-collapsed")
      },
      "switch-cockpit-tab": (_e, t) => this._switchCockpitTab(t.getAttribute("data-tab")),
      "insert-person": (_e, t) => this._insertTextAtCursor(t.getAttribute("data-name") || ""),
      "toggle-scene-group": (_e, t) => {
        const chapters = t.parentElement.querySelector(".scene-tree-chapters")
        const icon = t.querySelector(".toggle-icon")
        if (chapters) {
          const isHidden = chapters.style.display === "none"
          chapters.style.display = isHidden ? "block" : "none"
          if (icon) icon.textContent = isHidden ? "▼" : "▶"
        }
      },
    })

    this._bindCockpitDrag()

    const versionSelector = document.getElementById("version-selector")
    if (versionSelector) {
      versionSelector.onchange = () => {
        const opt = versionSelector.options[versionSelector.selectedIndex]
        const draftId = opt.value
        const versionNumber = parseInt(opt.getAttribute("data-version"), 10)
        const isLatest = opt.getAttribute("data-latest") === "1"
        this._switchVersion(draftId, versionNumber, isLatest)
      }
    }

    const titleInput = document.getElementById("writing-title-input")
    if (titleInput) {
      titleInput.oninput = () => { this._currentTitle = titleInput.value; this._scheduleAutoSave() }
    }
    const editorEl = document.getElementById("writing-editor")
    if (editorEl) {
      this._clearCursorDebounceTimer()
      editorEl.oninput = () => {
        this._currentContent = editorEl.value
        this._updateWordcount()
        this._scheduleAutoSave()
      }
      editorEl.onclick = null
      editorEl.onkeyup = null
      document.removeEventListener("selectionchange", this._boundSelectionChange)
      const updateCursorScene = () => {
        if (document.activeElement !== editorEl) return
        this._cursorOffset = editorEl.selectionStart || 0
        this._updateCurrentScene()
        this._clearCursorDebounceTimer()
        const panelEl = document.getElementById("writing-panel-container")
        if (panelEl) panelEl.innerHTML = this._renderScenePanel()
      }
      this._boundSelectionChange = updateCursorScene
      editorEl.onclick = updateCursorScene
      document.addEventListener("selectionchange", updateCursorScene)
      editorEl.onkeyup = () => {
        this._clearCursorDebounceTimer()
        this._cursorDebounceTimer = setTimeout(updateCursorScene, 150)
      }
    }

    const mobileEditor = document.getElementById("mobile-note-editor")
    if (mobileEditor) {
      mobileEditor.oninput = () => {
        const count = mobileEditor.value.length
        const countEl = document.getElementById("mobile-note-wc")
        if (countEl) countEl.textContent = `${count.toLocaleString()} 字`
      }
    }
  },

  _switchCockpitTab(tab) {
    if (!tab) return
    document.querySelectorAll(".cockpit-tab").forEach((item) => {
      item.classList.toggle("active", item.getAttribute("data-tab") === tab)
    })
    document.querySelectorAll(".cockpit-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.getAttribute("data-panel") !== tab)
    })
  },

  _insertTextAtCursor(text) {
    if (!text) return
    const editor = document.getElementById("writing-editor")
    if (!editor || this._isReadonly) return
    const start = editor.selectionStart || 0
    const end = editor.selectionEnd || start
    editor.value = `${editor.value.slice(0, start)}${text}${editor.value.slice(end)}`
    editor.selectionStart = editor.selectionEnd = start + text.length
    this._currentContent = editor.value
    this._updateWordcount()
    this._scheduleAutoSave()
    editor.focus()
  },

  async _rerender() {
    const container = document.getElementById("workspace-content")
    if (!container) return

    // 首次渲染或结构变更（如从空状态切换到有章节、或选中章节后需要创建编辑器）：全量替换
    const treeEl = document.getElementById("writing-tree-container")
    const editorEl = document.getElementById("writing-editor")
    const hasSelection = this._currentChapter !== null
    const needsFullRender = !treeEl || (hasSelection && !editorEl) || (!hasSelection && editorEl)
    if (needsFullRender) {
      container.innerHTML = await this.render()
      return
    }

    // 增量更新：只替换非编辑器区域，保留 textarea 状态
    treeEl.innerHTML = this._renderSceneTree()

    const panelEl = document.getElementById("writing-panel-container")
    if (panelEl) panelEl.innerHTML = this._renderScenePanel()

    const publishBarEl = document.getElementById("writing-publish-bar-container")
    if (publishBarEl) publishBarEl.innerHTML = this._renderPublishBar()

    const deepImportBarEl = document.getElementById("writing-deep-import-bar-container")
    if (deepImportBarEl) deepImportBarEl.innerHTML = this._renderDeepImportBar()

    const conflictStripEl = document.getElementById("writing-conflict-strip")
    if (conflictStripEl) conflictStripEl.outerHTML = this._renderConflictCheckStrip()

    // 更新编辑器元信息（版本号、按钮、只读状态等），但保留 textarea 内容
    this._updateEditorMeta()

    this._bindEvents()
  },

  /** 局部更新编辑器元信息，不触碰 textarea */
  _updateEditorMeta() {
    const versionInfo = document.getElementById("writing-version-info")
    const versionLabel = this._currentVersionNumber ? `v${this._currentVersionNumber}` : ""
    const readOnlyLabel = this._isReadonly ? "（只读）" : ""
    if (versionInfo) versionInfo.textContent = `${versionLabel} ${readOnlyLabel}`

    this._updateSaveStatus()

    const chapterTitle = document.getElementById("writing-chapter-title")
    if (chapterTitle && this._currentChapter) {
      chapterTitle.textContent = `第 ${this._currentChapter} 章`
    }

    // 同步 textarea 内容（首次渲染时 textarea 可能为空）
    const editorEl = document.getElementById("writing-editor")
    if (editorEl && this._currentContent !== null && editorEl.value !== this._currentContent) {
      editorEl.value = this._currentContent
      this._lastSavedContent = this._currentContent
    }
    // 同步标题输入
    const titleInputEl = document.getElementById("writing-title-input")
    if (titleInputEl && this._currentTitle !== null && titleInputEl.value !== this._currentTitle) {
      titleInputEl.value = this._currentTitle
    }

    // 更新版本选择器
    const versionSelector = document.getElementById("version-selector")
    if (versionSelector) {
      versionSelector.innerHTML = ""
      for (const v of this._versions) {
        const selected = v.version_number === this._currentVersionNumber
        const isCurLatest = v.version_number === this._versions[0]?.version_number
        const opt = document.createElement("option")
        opt.value = v.id
        opt.setAttribute("data-version", v.version_number)
        opt.setAttribute("data-latest", isCurLatest ? "1" : "0")
        opt.selected = selected
        opt.textContent = `v${v.version_number}${isCurLatest ? " (最新)" : ""}`
        versionSelector.appendChild(opt)
      }
      versionSelector.onchange = () => {
        const opt = versionSelector.options[versionSelector.selectedIndex]
        const draftId = opt.value
        const vn = parseInt(opt.getAttribute("data-version"), 10)
        const isLat = opt.getAttribute("data-latest") === "1"
        this._switchVersion(draftId, vn, isLat)
      }
    }

    // 更新只读状态相关按钮
    const restoreBtn = document.getElementById("btn-restore-from-version")
    if (this._isReadonly) {
      if (!restoreBtn) {
        const btnContainer = document.getElementById("writing-editor-buttons")
        if (btnContainer) {
          const btn = document.createElement("button")
          btn.className = "btn btn-primary"
          btn.id = "btn-restore-from-version"
          btn.setAttribute("data-action", "restore-from-version")
          btn.textContent = "基于此版本创建"
          btn.onclick = () => this._restoreFromVersion()
          btnContainer.insertBefore(btn, btnContainer.firstChild)
        }
      }
    } else if (restoreBtn) {
      restoreBtn.remove()
    }

    const btnAutosave = document.getElementById("btn-autosave")
    if (btnAutosave) {
      const hasSelection = this._currentChapter !== null
      btnAutosave.disabled = !(hasSelection && !this._isReadonly)
      btnAutosave.textContent = this._restoreSourceVersion ? "发布为新版本" : "暂存"
    }

    const btnPublish = document.getElementById("btn-publish")
    if (btnPublish) {
      const hasSelection = this._currentChapter !== null
      btnPublish.disabled = !(hasSelection && !this._isReadonly)
    }

    const focusBtn = document.querySelector('[data-action="toggle-focus-mode"]')
    if (focusBtn) focusBtn.textContent = this._focusMode ? "退出专注" : "专注模式"

    const editorElForFocus = document.getElementById("writing-editor")
    editorElForFocus?.classList.toggle("novel-editor--focus", this._focusMode)
  },
}

router.registerView("writing", writingView)
window.writingView = writingView
export default writingView
