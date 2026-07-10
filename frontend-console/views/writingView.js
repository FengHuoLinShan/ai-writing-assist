/**
 * 手动工作台 — Orchestrator
 *
 * 协调 writing/ 目录下的子模块，持有跨子模块共享状态，
 * 自身不实现具体业务逻辑。
 */
/* global state, api, toast, esc, showModal, showModalHtml, confirmAction, closeModal, router, App */
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import { confirmAsync } from "../shared/confirmAsync.js"
import { applyToolsResult } from "../shared/writingToolsResult.js"
import { buildMapUrl } from "./mapRouteContext.js"
import { createWritingSubModules } from "./writing/submodules.js"

const writingView = {
  // 跨子模块共享状态
  _currentChapter: null,
  _chapterList: [],
  _chapters: {},
  _scenes: [],
  _loading: true,
  _chapterListLoadError: null,
  _focusMode: false,
  _forceDesktopMode: false,
  _bulkSelections: {},
  _showBulkActions: false,

  // 子模块实例
  _chapterTree: null,
  _editor: null,
  _versions: null,
  _publish: null,
  _deepImportRecovery: null,
  _autoExtraction: null,
  _conflictCheck: null,
  _scenePanel: null,
  _outlineFloat: null,
  _focusModeManager: null,
  _tools: null,
  _mobileQuickNote: null,

  _beforeUnloadHandler: null,

  // ============================================================
  // 生命周期
  // ============================================================

  async onEnter() {
    this._initSubModules()
    this._resetSharedState()
    this._loading = true
    this._chapterListLoadError = null

    this._beforeUnloadHandler = (e) => {
      if (this._editor?.isReadonly?.()) return
      const currentContent = this._editor?.getContent?.()
      const lastSaved = this._editor?._lastSavedContent ?? null
      if (currentContent !== undefined && currentContent !== lastSaved && currentContent?.trim?.()) {
        e.preventDefault()
        e.returnValue = ""
      }
    }
    window.addEventListener("beforeunload", this._beforeUnloadHandler)

    try {
      await this._chapterTree.load()
      this._chapterList = this._chapterTree._getChapterList()
      this._chapters = this._chapterTree._getChapterMap()
      this._scenes = this._chapterTree._getScenes()
      this._chapterListLoadError = this._chapterTree._getLoadError()
      if (this._chapterListLoadError) {
        toast("章节列表加载失败，可稍后重试", "warning")
      }
      this._syncSharedStateToSubModules()
    } catch (err) {
      this._chapterList = []
      this._chapters = {}
      this._scenes = []
      this._chapterListLoadError = err?.message || "加载失败"
      toast("章节列表加载失败，可稍后重试", "warning")
    }

    const saved = state.viewStates.writing?.projectId === state.currentProjectId
      ? state.viewStates.writing
      : null
    if (saved?.currentChapter && this._chapterList.includes(saved.currentChapter)) {
      await this._selectChapter(saved.currentChapter, {
        draftId: saved.currentDraftId,
        versionNumber: saved.currentVersionNumber,
        isReadonly: saved.isReadonly,
        restoreSourceVersion: saved.restoreSourceVersion,
      })
    }

    try {
      await this._deepImportRecovery.recover()
    } catch {
      // 恢复任务失败不影响主界面
    }

    this._loading = false
  },

  onLeave() {
    if (this._beforeUnloadHandler) {
      window.removeEventListener("beforeunload", this._beforeUnloadHandler)
      this._beforeUnloadHandler = null
    }

    state.viewStates.writing = {
      projectId: state.currentProjectId,
      currentChapter: this._currentChapter,
      currentContent: this._editor?.getContent?.() ?? null,
      currentTitle: this._editor?.getTitle?.() ?? null,
      currentDraftId: this._editor?.getDraftId?.() ?? null,
      currentVersionNumber: this._editor?.getVersionNumber?.() ?? null,
      currentUpdatedAt: this._editor?.getUpdatedAt?.() ?? null,
      isReadonly: this._editor?.isReadonly?.() ?? false,
      restoreSourceVersion: this._editor?.getRestoreSourceVersion?.() ?? null,
    }

    this._disposeSubModules()
  },

  async onActivate() {
    this._bindEvents()
    const editorEl = document.getElementById("writing-editor")
    if (editorEl && this._currentChapter !== null) {
      editorEl.focus()
    }
    try {
      await this._deepImportRecovery.recover()
    } catch {
      // ignore
    }
  },

  onDeactivate() {
    const editorEl = document.getElementById("writing-editor")
    if (editorEl && this._editor) {
      this._editor.setState({ content: editorEl.value })
      if (!this._editor.isReadonly?.() && editorEl.value?.trim?.() && this._currentChapter) {
        this._editor.saveBackup(editorEl.value, this._editor.getTitle())
      }
    }
    const titleInput = document.getElementById("writing-title-input")
    if (titleInput && this._editor) {
      this._editor.setState({ title: titleInput.value })
    }
  },

  // ============================================================
  // 渲染
  // ============================================================

  async render() {
    if (this._loading) {
      return '<div class="empty-state"><p>章节数据加载中...</p></div>'
    }

    if (this._chapterListLoadError) {
      setTimeout(() => this._bindEvents(), 0)
      return `
        <div class="empty-state" role="alert">
          <div class="empty-icon writing-empty-icon--warning">&#9888;</div>
          <p>章节列表加载失败</p>
          <p class="writing-empty-hint">可稍后重试。错误信息：${esc(this._chapterListLoadError)}</p>
        </div>
        <div id="writing-deep-import-bar-container">${this._deepImportRecovery?.renderBar?.() ?? ""}</div>
      `
    }

    if (this._chapterList.length === 0) {
      setTimeout(() => this._bindEvents(), 0)
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128221;</div>
          <p>开始创作！</p>
          <p class="writing-empty-hint">
            点击下方按钮创建第一个章节，开始写作。
          </p>
          <div class="writing-empty-actions">
            <button class="btn btn-primary" data-action="new-chapter">+ 新建章节</button>
          </div>
        </div>
        <div id="writing-deep-import-bar-container">${this._deepImportRecovery?.renderBar?.() ?? ""}</div>
      `
    }

    if (this._mobileQuickNote?.shouldRender?.()) {
      setTimeout(() => this._bindEvents(), 0)
      return this._mobileQuickNote.render()
    }

    const html = `
      <p class="writing-view-hint">
        手动工作台 — 选择章节，撰写正文。
      </p>
      <div class="writing-workspace-layout">
        <div id="writing-tree-container">${this._chapterTree?.render?.() ?? ""}</div>
        <div id="writing-editor-container">
          ${this._editor?.render?.() ?? ""}
          <div id="writing-versions-container">${this._versions?.render?.() ?? ""}</div>
          ${this._tools?.renderToolsMenu?.(this._currentChapter !== null) ?? ""}
          <div id="writing-publish-bar-container">${this._publish?.renderBar?.() ?? ""}</div>
          <div id="writing-deep-import-bar-container">${this._deepImportRecovery?.renderBar?.() ?? ""}</div>
          ${this._conflictCheck?.renderStrip?.() ?? ""}
        </div>
        <div id="writing-panel-container">${this._scenePanel?.render?.() ?? ""}</div>
      </div>
      ${this._outlineFloat?.render?.() ?? ""}
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindEvents() {
    const treeContainer = document.getElementById("writing-tree-container")
    const editorContainer = document.getElementById("writing-editor-container")
    const panelContainer = document.getElementById("writing-panel-container")
    const versionsContainer = document.getElementById("writing-versions-container")
    const mobileNote = document.querySelector(".mobile-quick-note")

    if (treeContainer && this._chapterTree?.bindEvents) this._chapterTree.bindEvents(treeContainer)
    if (editorContainer) {
      if (this._editor?.bindEvents) this._editor.bindEvents(editorContainer)
      if (this._tools?.bindEvents) this._tools.bindEvents(editorContainer)
      if (this._conflictCheck?.bindEvents) this._conflictCheck.bindEvents(editorContainer)
    }
    if (versionsContainer && this._versions?.bindEvents) this._versions.bindEvents(versionsContainer)
    if (panelContainer && this._scenePanel?.bindEvents) this._scenePanel.bindEvents(panelContainer)
    if (mobileNote && this._mobileQuickNote?.bindEvents) this._mobileQuickNote.bindEvents(mobileNote.parentElement || document.body)

    bindWorkspaceClick(this, {
      "autosave": () => this._autosave(),
      "publish": () => this._handlePublish(),
      "toggle-focus-mode": () => this._toggleFocusMode(),
      "toggle-outline-float": () => this._toggleOutlineFloat(),
      "close-outline-float": () => this._closeOutlineFloat(),
      "ai-continue": () => this._editor?.aiContinue?.(),
      "switch-desktop-mode": () => this._switchDesktopMode(),
      "save-mobile-note": () => this._mobileQuickNote?.save?.(),
      "restore-from-version": () => this._versions?.restoreFromVersion?.(),
      "dismiss-publish-error": () => this._publish?.dismissError?.(),
      "run-conflict-check": () => this._runConflictCheck(),
      "auto-extract-stage": (e, t) => this._autoExtraction?.showForm?.(t.getAttribute("data-stage") || "scenes"),
      "deep-import": () => this._autoExtraction?.showDeepImportForm?.(),
      "open-map": (e, t) => {
        if (t.closest("#writing-panel-container")) return
        this._scenePanel?.openMap?.()
      },
      "dismiss-deep-import": () => this._deepImportRecovery?.dismiss?.(),
      "resume-deep-import": () => this._deepImportRecovery?.resume?.(),
      "abandon-deep-import": () => this._deepImportRecovery?.abandon?.(),
      "view-deep-import-audit": () => this._deepImportRecovery?.showAuditDetails?.(),
      "view-scene-preview": () => this._deepImportRecovery?.showScenePreview?.(),
      "discard-scene-preview": () => this._deepImportRecovery?.discardScenePreview?.(),
      "open-outline": () => router.navigate("outline", null),
      "open-scene-workbench": () => {
        const scene = this._scenePanel?.getCurrentScene?.()
        router.navigate("scene", scene?.id || null)
      },
      "extract-cards": () => this._autoExtraction?.extractChapterCards?.(),
      "insert-person": (e, t) => this._editor?.insertTextAtCursor?.(t.getAttribute("data-name") || ""),
    })
  },

  // ============================================================
  // 子模块初始化与销毁
  // ============================================================

  _initSubModules() {
    const modal = {
      showHtml: showModalHtml,
      showModalHtml,
      confirmAction,
      close: closeModal,
      closeModal,
    }
    Object.assign(this, createWritingSubModules(this, { state, api, toast, esc, modal, router }))
  },

  _disposeSubModules() {
    this._chapterTree?.dispose?.()
    this._editor?.dispose?.()
    this._versions?.dispose?.()
    this._publish?.dispose?.()
    this._deepImportRecovery?.dispose?.()
    this._autoExtraction?.dispose?.()
    this._conflictCheck?.dispose?.()
    this._scenePanel?.dispose?.()
    this._outlineFloat?.dispose?.()
    this._focusModeManager?.dispose?.()
    this._tools?.dispose?.()
    this._mobileQuickNote?.dispose?.()
  },

  _ensureSubModulesInitialized() {
    const injectedVersions = Array.isArray(this._versions) ? this._versions : null
    const hasAll = this._chapterTree?.render && this._editor?.render && this._versions?.render && this._tools?.renderToolsMenu
    if (!hasAll) {
      this._initSubModules()
    }
    if (injectedVersions && this._versions?.setVersions) {
      this._versions.setVersions(injectedVersions, this._currentChapter)
    }
  },

  _syncInjectedStateToSubModules() {
    if (this._chapterTree) {
      if (Object.prototype.hasOwnProperty.call(this, "_chapterList")) this._chapterTree._setChapterList(this._chapterList)
      if (Object.prototype.hasOwnProperty.call(this, "_chapters")) this._chapterTree._setChapters(this._chapters)
      if (Object.prototype.hasOwnProperty.call(this, "_scenes")) this._chapterTree._setScenes(this._scenes)
      if (Object.prototype.hasOwnProperty.call(this, "_currentChapter")) this._chapterTree._setCurrentChapter(this._currentChapter)
    }
    if (this._scenePanel && Object.prototype.hasOwnProperty.call(this, "_scenes")) {
      this._scenePanel.setScenes(this._scenes)
    }
    if (this._editor?.setState) {
      const patch = {}
      if (Object.prototype.hasOwnProperty.call(this, "_currentContent")) patch.content = this._currentContent
      if (Object.prototype.hasOwnProperty.call(this, "_currentTitle")) patch.title = this._currentTitle
      if (Object.prototype.hasOwnProperty.call(this, "_currentDraftId")) patch.draftId = this._currentDraftId
      if (Object.prototype.hasOwnProperty.call(this, "_currentVersionNumber")) patch.versionNumber = this._currentVersionNumber
      if (Object.prototype.hasOwnProperty.call(this, "_currentUpdatedAt")) patch.updatedAt = this._currentUpdatedAt
      if (Object.prototype.hasOwnProperty.call(this, "_isReadonly")) patch.isReadonly = this._isReadonly
      if (Object.prototype.hasOwnProperty.call(this, "_lastSavedContent")) patch.lastSavedContent = this._lastSavedContent
      if (Object.prototype.hasOwnProperty.call(this, "_restoreSourceVersion")) patch.restoreSourceVersion = this._restoreSourceVersion
      if (Object.prototype.hasOwnProperty.call(this, "_currentChapter")) patch.chapter = this._currentChapter
      if (Object.keys(patch).length > 0) {
        this._editor.setState(patch)
      }
      // 注入的编辑器状态只同步一次；后续以编辑器内部状态为准
      delete this._currentContent
      delete this._currentTitle
      delete this._currentDraftId
      delete this._currentVersionNumber
      delete this._currentUpdatedAt
      delete this._isReadonly
      delete this._lastSavedContent
      delete this._restoreSourceVersion
    }
  },

  _resetSharedState() {
    this._currentChapter = null
    this._chapterList = []
    this._chapters = {}
    this._scenes = []
    this._chapterListLoadError = null
    this._focusMode = this._focusModeManager?.isFocusMode?.() ?? false
    this._forceDesktopMode = this._focusModeManager?.isForceDesktopMode?.() ?? false
    this._bulkSelections = {}
    this._showBulkActions = false
  },

  _syncSharedStateToSubModules() {
    const editor = this._editor
    const scene = this._scenePanel?.getCurrentScene?.()
    state._chapterList = this._chapterList
    state._chapters = this._chapters
    state._scenes = this._scenes
    state._currentChapter = this._currentChapter
    state._currentSceneId = scene?.id || null
    state._currentContent = editor?.getContent?.() ?? null
    state._currentTitle = editor?.getTitle?.() ?? null
    const isSuggestionPreview = editor?.getDraftStatus?.() === "candidate"
    state._currentDraftId = isSuggestionPreview ? null : (editor?.getDraftId?.() ?? null)
    state._currentSuggestionDraftId = isSuggestionPreview ? (editor?.getDraftId?.() ?? null) : null
    state._currentVersionNumber = editor?.getVersionNumber?.() ?? null
    state._currentUpdatedAt = editor?.getUpdatedAt?.() ?? null
    state._isReadonly = editor?.isReadonly?.() ?? false
    state._cursorOffset = editor?.getCursorOffset?.() ?? 0
    state._focusMode = this._focusMode
    state._forceDesktopMode = this._forceDesktopMode

    this._chapterTree?._setCurrentChapter?.(this._currentChapter)
    this._chapterTree?._setCurrentSceneId?.(state._currentSceneId)
    this._chapterTree?._setChapters?.(this._chapters)
    this._chapterTree?._setScenes?.(this._scenes)
    this._chapterTree?._setChapterList?.(this._chapterList)
    this._chapterTree?._setBulkSelections?.(this._bulkSelections)
    this._chapterTree?._setShowBulkActions?.(this._showBulkActions)

    this._scenePanel?.setScenes?.(this._scenes)
    this._scenePanel?.setCursorOffset?.(state._cursorOffset)
  },

  _syncChapterMetaToTree(chapterIndex) {
    if (chapterIndex == null || !this._chapters[chapterIndex]) return
    const content = this._editor?.getContent?.() || ""
    const title = this._editor?.getTitle?.() || ""
    this._chapters[chapterIndex] = {
      ...this._chapters[chapterIndex],
      title,
      wordcount: content.length,
      word_count: content.length,
      status: this._editor?.getDraftStatus?.() || this._chapters[chapterIndex].status || "draft",
    }
    this._chapterTree?._setChapters?.(this._chapters)
  },

  // ============================================================
  // 章节选择
  // ============================================================

  async _selectChapter(chapterIndex, options = {}) {
    // 从章节树同步最新列表（例如新建章节后）
    if (this._chapterTree) {
      this._chapterList = this._chapterTree._getChapterList()
      this._chapters = this._chapterTree._getChapterMap()
      this._scenes = this._chapterTree._getScenes()
    }

    if (chapterIndex !== null && this._currentChapter === chapterIndex && !options.draftId) {
      await this._editor?.loadChapter?.(chapterIndex)
      await this._versions?.load?.(chapterIndex)
      this._syncChapterMetaToTree(chapterIndex)
      this._syncSharedStateToSubModules()
      await this._rerender()
      return
    }

    if (this._currentChapter !== null && chapterIndex !== null && this._editor) {
      await this._editor.autosave()
    }

    this._currentChapter = chapterIndex
    this._syncSharedStateToSubModules()

    if (chapterIndex === null) {
      delete state.viewStates.writing
      await this._rerender()
      return
    }

    delete state.viewStates.writing
    try {
      await this._editor?.loadChapter?.(chapterIndex, options)
      await this._versions?.load?.(chapterIndex)
      this._syncChapterMetaToTree(chapterIndex)
      this._scenePanel?.update?.(this._editor?.getCurrentSceneId?.(), chapterIndex)
      this._syncSharedStateToSubModules()
      await this._conflictCheck?.refresh?.(chapterIndex)
      this._editor?.updateWordcount?.()
      await this._rerender()
    } catch (err) {
      toast(err?.message || "加载章节失败", "error")
    }
  },

  async _selectScene(sceneId) {
    const scene = this._scenes.find((s) => s.id === sceneId)
    if (!scene) return
    const chIds = (scene.chapter_ids || [])
      .map((id) => parseInt(id, 10))
      .filter((n) => !Number.isNaN(n) && this._chapterList.includes(n))
    const firstChapter = chIds.length > 0 ? Math.min(...chIds) : null
    if (firstChapter) {
      await this._selectChapter(firstChapter)
    }
  },

  async _onBulkChange(scope) {
    this._chapterList = this._chapterTree._getChapterList()
    this._chapters = this._chapterTree._getChapterMap()
    this._bulkSelections = this._chapterTree._bulkSelections || {}
    this._showBulkActions = this._chapterTree._showBulkActions || false
    this._syncSharedStateToSubModules()
    await this._rerender()
  },

  // ============================================================
  // 编辑器 / 版本 / 发布 回调
  // ============================================================

  _onWordcountUpdate(stats) {
    this._syncChapterMetaToTree(this._currentChapter)
    this._syncSharedStateToSubModules()
    globalThis.App?.updateWordcountDashboard?.({
      chapterIndex: this._currentChapter,
      chapterWords: stats.chapterWords,
      todayWords: stats.todayWords,
      saveState: stats.saveState,
    })
  },

  async _onVersionSwitch(info) {
    await this._editor.loadChapter(this._currentChapter, {
      draftId: info.draftId,
      versionNumber: info.versionNumber,
      isReadonly: info.isReadonly,
      restoreSourceVersion: info.restoreSourceVersion,
    })
    this._syncSharedStateToSubModules()
    await this._rerender()
  },

  async _onPublished() {
    await this._chapterTree.load()
    this._chapterList = this._chapterTree._getChapterList()
    this._chapters = this._chapterTree._getChapterMap()
    this._scenes = this._chapterTree._getScenes()
    this._syncSharedStateToSubModules()
    if (this._currentChapter !== null) {
      await this._selectChapter(this._currentChapter)
    } else {
      await this._rerender()
    }
  },

  _onTaskStarted(taskInfo) {
    this._deepImportRecovery?.startTask?.(taskInfo)
  },

  async _onToolsRefresh(result) {
    const action = applyToolsResult(result, this)
    if (!action.selectChapter && !action.rerender) return
    this._syncSharedStateToSubModules()
    if (action.selectChapter) {
      this._selectChapter(action.selectChapter)
    } else if (action.rerender) {
      await this._rerender()
    }
  },

  // ============================================================
  // 写作操作
  // ============================================================

  async _autosave() {
    if (this._editor?.getRestoreSourceVersion?.()) {
      await this._handlePublish()
      return
    }
    await this._editor.autosave()
    this._syncChapterMetaToTree(this._currentChapter)
    this._syncSharedStateToSubModules()
  },

  async _confirmBeforePublish(chapterIndex, currentScene) {
    if (!state.currentProjectId || chapterIndex == null) return true
    let latest = null
    try {
      const result = await api.writing.listConflictChecks({
        novel_id: state.currentProjectId,
        chapter_index: chapterIndex,
        scene_id: currentScene?.id || null,
        limit: 1,
      })
      latest = result.items?.[0] || null
    } catch {
      return true
    }
    if (!latest) {
      return await confirmAsync(
        "当前章节还没有剧情设定冲突检查记录。可以继续发布，也可以先运行检查。",
        "继续发布",
      )
    }
    const latestItems = Array.isArray(latest.items) ? latest.items : []
    const openHighCount = latestItems.length
      ? latestItems.filter((item) => item.severity === "high" && item.status === "open").length
      : (latest.summary_json?.open_high_count ?? 0)
    if (openHighCount > 0) {
      return await confirmAsync(
        `最近一次检查仍有 ${openHighCount} 个未处理高严重度问题。确认继续发布？`,
        "继续发布",
      )
    }
    return true
  },

  async _handlePublish() {
    if (!state.currentProjectId || this._currentChapter === null) {
      toast("请先选择章节", "warning")
      return
    }
    if (this._editor?.isReadonly?.()) {
      toast("当前内容只读；待处理建议需先采用到工作稿", "warning")
      return
    }
    const content = this._editor.getContent().trim()
    if (!content) {
      toast("工作稿内容不能为空", "warning")
      return
    }
    const title = this._editor.getTitle() || `第 ${this._currentChapter} 章`
    const currentScene = this._scenePanel.getCurrentScene()

    const canPublish = await this._confirmBeforePublish(this._currentChapter, currentScene)
    if (!canPublish) return

    await this._publish.publish(
      content,
      title,
      this._currentChapter,
      this._editor.getDraftId(),
      currentScene,
    )
  },

  async _runConflictCheck() {
    if (!state.currentProjectId || this._currentChapter === null) {
      toast("请先选择章节", "warning")
      return
    }
    if (this._editor?.isReadonly?.()) {
      toast("当前内容只读；待处理建议不会作为工作稿检查", "warning")
      return
    }
    await this._editor.autosave()
    this._syncSharedStateToSubModules()
    await this._conflictCheck.run(this._currentChapter, () => this._editor.getContent())
    await this._rerender()
  },

  // ============================================================
  // 地图 / 大纲 / 工具
  // ============================================================

  _toggleFocusMode() {
    this._focusModeManager.toggle()
  },

  async _switchDesktopMode() {
    this._focusModeManager.switchDesktopMode()
  },

  _onSaveStatusChange(text) {
    const el = document.getElementById("writing-save-status")
    if (el) el.textContent = text || ""
  },

  _openMap(targetOrSceneId) {
    const projectId = state.currentProjectId
    if (!projectId) {
      toast("请先选择项目", "warning")
      return
    }
    const currentScene = this._scenePanel?.getCurrentScene?.()
    const target = targetOrSceneId && typeof targetOrSceneId === "object"
      ? targetOrSceneId
      : { scene_id: targetOrSceneId }
    const mapId = target.map_id || null
    const url = buildMapUrl({
      projectId,
      mapId,
      sceneId: target.scene_id || currentScene?.id,
      focusEntityId: target.focus_entity_id || null,
      mode: target.mode || (mapId ? "map" : "overview"),
    })
    window.open(url, "_blank", "noopener")
  },

  _onCockpitTabSwitch(tab) {
    this._scenePanel?.switchTab?.(tab)
  },

  async _toggleOutlineFloat() {
    await this._outlineFloat.toggle()
  },

  _closeOutlineFloat() {
    this._outlineFloat.close()
  },

  // ============================================================
  // 增量重渲染
  // ============================================================

  async _rerender() {
    const container = document.getElementById("workspace-content")
    if (!container) return

    this._ensureSubModulesInitialized()
    this._syncInjectedStateToSubModules()

    const treeEl = document.getElementById("writing-tree-container")
    const editorEl = document.getElementById("writing-editor")
    const hasSelection = this._currentChapter !== null
    const needsFullRender = !treeEl || (hasSelection && !editorEl) || (!hasSelection && editorEl)
    if (needsFullRender) {
      container.innerHTML = await this.render()
      return
    }

    if (treeEl && this._chapterTree?.render) treeEl.innerHTML = this._chapterTree.render()

    const panelEl = document.getElementById("writing-panel-container")
    if (panelEl && this._scenePanel?.render) panelEl.innerHTML = this._scenePanel.render()

    const versionsContainer = document.getElementById("writing-versions-container")
    if (versionsContainer && this._versions?.render) versionsContainer.innerHTML = this._versions.render()

    const publishBarEl = document.getElementById("writing-publish-bar-container")
    if (publishBarEl && this._publish?.renderBar) publishBarEl.innerHTML = this._publish.renderBar()

    const deepImportBarEl = document.getElementById("writing-deep-import-bar-container")
    if (deepImportBarEl && this._deepImportRecovery?.renderBar) deepImportBarEl.innerHTML = this._deepImportRecovery.renderBar()

    const conflictStripEl = document.getElementById("writing-conflict-strip")
    if (conflictStripEl && this._conflictCheck?.renderStrip) conflictStripEl.outerHTML = this._conflictCheck.renderStrip()

    if (this._editor?.updateMeta) this._editor.updateMeta(this._focusMode)
    this._bindEvents()
  },

  async _refreshVersions(chapterIndex) {
    this._currentChapter = chapterIndex
    this._syncInjectedStateToSubModules()
    await this._editor?.loadChapter?.(chapterIndex)
    await this._versions?.load?.(chapterIndex)
    this._syncChapterMetaToTree(chapterIndex)
    this._syncSharedStateToSubModules()
    await this._rerender()
  },
}

router.registerView("writing", writingView)
window.writingView = writingView
export default writingView
