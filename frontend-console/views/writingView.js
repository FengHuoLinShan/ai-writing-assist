/**
 * 手动工作台
 *
 * 左侧章节树 → 中间编辑器 → 版本管理。
 * 支持暂存、发布、版本切换、整章删除。
 */
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import { renderFixedProgress } from "../shared/progressRenderer.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { buildMapUrl } from "./mapRouteContext.js"
import { renderSceneCockpitPanel, saveSceneCockpitOrder } from "./sceneCockpitPanel.js"
import { showWritingConflictModal } from "./writingConflictModal.js"

const writingView = {
  _chapters: {},
  _chapterList: [],
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
  _loading: true,
  _publishTimer: null,
  _errorModalVisible: false,
  _outlineThreads: [],
  _outlineArc: null,
  _deepImportTaskId: null,
  _deepImportProgress: null,
  _deepImportTimer: null,
  _scenes: [],
  _currentSceneId: null,
  _cursorOffset: 0,
  _boundSelectionChange: null,
  _cursorDebounceTimer: null,
  _autoSaveTimer: null,
  _autoSaving: false,
  _lastSavedContent: null,
  _beforeUnloadHandler: null,
  _sceneMapSummary: null,
  _sceneMapSummaryError: null,
  _sceneMapSummarySceneId: null,
  _sceneMapSummaryLoading: false,
  _conflictChecks: [],
  _latestConflictCheck: null,
  _checkingConflicts: false,

  // ============================================================
  // 生命周期
  // ============================================================

  async onEnter() {
    const saved = state.viewStates.writing
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
    this._versions = []
    this._publishTaskId = null
    this._publishProgress = null
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
    this._sceneMapSummaryLoading = false
    this._conflictChecks = []
    this._latestConflictCheck = null
    this._checkingConflicts = false

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
      const draftIndices = draftData.chapter_indices || []
      for (const idx of draftIndices) {
        this._chapters[idx] = { draftCount: 0 }
      }
      this._chapterList = [...draftIndices].sort((a, b) => a - b)

      // 加载 Scene 数据
      try {
        this._scenes = await api.outline.listScenesOrdered(state.currentProjectId) || []
      } catch {
        this._scenes = []
      }
    } catch {
      this._chapterList = []
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
      workflow = recoverActiveWorkflows(state.currentProjectId)
        .find((item) => item.workflowType === "deep_import")
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
          const isFailed = task.status === "failed"
          this._deepImportTaskId = taskId
          this._deepImportProgress = {
            phase: isFailed ? "failed" : task.status === "cancelled" ? "cancelled" : "done",
            step: result.current_step || "",
            message: result.message || (isFailed ? "导入失败" : "导入完成"),
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
      this._deepImportProgress = {
        phase: result.phase || "running",
        step: result.current_step || "",
        message: result.message || "深度导入中...",
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
      this._startDeepImportPolling()
    } catch {
      this._clearDeepImportWorkflow(taskId)
      await this._rerender()
    }
  },

  async render() {
    if (this._loading) {
      return '<div class="empty-state"><p>加载中...</p></div>'
    }

    if (this._chapterList.length === 0) {
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

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">
        手动工作台 — 选择章节，撰写正文。
      </p>
      <div class="writing-workspace-layout">
        <div id="writing-tree-container">${this._renderSceneTree()}</div>
        <div id="writing-editor-container">${this._renderEditor()}</div>
        <div id="writing-panel-container">${this._renderScenePanel()}</div>
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

  // ============================================================
  // 保存辅助方法
  // ============================================================

  /** 导航离开前保存当前编辑内容 */
  async _saveBeforeNavigate() {
    this._clearAutoSaveTimer()
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

  /** 安排自动保存（3 秒防抖） */
  _scheduleAutoSave() {
    this._clearAutoSaveTimer()
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

  // ============================================================
  // 左侧：章节树
  // ============================================================

  _renderChapterTree() {
    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:13px;font-weight:bold;">章节（${this._chapterList.length}）</span>
          <button class="btn btn-sm" data-action="new-chapter" style="font-size:11px;">+ 新建</button>
        </div>
        <div style="margin-top:6px;">
    `

    for (const idx of this._chapterList) {
      const isActive = idx === this._currentChapter
      html += `
        <div style="display:flex;align-items:center;padding:6px 8px;border-left:3px solid ${isActive ? 'var(--accent)' : 'transparent'};margin-bottom:2px;background:${isActive ? 'var(--hover-bg)' : 'transparent'};border-radius:0 4px 4px 0;">
          <div class="clickable" data-action="select-chapter" data-chapter="${idx}" style="flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            <strong>第 ${idx} 章</strong>
            ${this._chapters[idx].title ? `<span style="color:var(--text-dim);font-size:11px;margin-left:6px;">${esc(this._chapters[idx].title)}</span>` : ''}
          </div>
          <button class="btn btn-sm" data-action="delete-chapter" data-chapter="${idx}" title="删除整章" style="font-size:11px;color:var(--danger);margin-left:4px;">✕</button>
        </div>
      `
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

    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:13px;font-weight:bold;">Scene 树</span>
          <button class="btn btn-sm" data-action="new-chapter" style="font-size:11px;">+ 新建章</button>
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

    // Scene 节点
    for (const { scene, chapters } of sceneChapterMap) {
      if (chapters.length === 0 && unassigned.length === 0) continue
      const isCurrentScene = scene.id === this._currentSceneId
      const isExpanded = isCurrentScene || chapters.includes(this._currentChapter)

      html += `
        <div class="scene-tree-node">
          <div class="scene-tree-scene clickable" data-action="select-scene" data-scene-id="${esc(scene.id)}"
               style="padding:4px 4px;border-radius:4px;${isCurrentScene ? 'background:var(--hover-bg);' : ''}">
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
    return `
      <div style="display:flex;align-items:center;padding:4px 6px;border-left:3px solid ${isActive ? 'var(--accent)' : 'transparent'};margin-bottom:1px;background:${isActive ? 'var(--hover-bg)' : 'transparent'};border-radius:0 4px 4px 0;}">
        <div class="clickable" data-action="select-chapter" data-chapter="${idx}" style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          第 ${idx} 章
          ${this._chapters[idx] && this._chapters[idx].title ? `<span style="color:var(--text-dim);font-size:10px;margin-left:4px;">${esc(this._chapters[idx].title)}</span>` : ''}
        </div>
        <button class="btn btn-sm" data-action="delete-chapter" data-chapter="${idx}" title="删除整章" style="font-size:10px;color:var(--danger);margin-left:2px;">✕</button>
      </div>
    `
  },

  // ============================================================
  // 中间：编辑器
  // ============================================================

  _renderEditor() {
    const hasSelection = this._currentChapter !== null
    const versionInfo = this._currentVersionNumber ? `v${this._currentVersionNumber}` : ''
    const readOnlyLabel = this._isReadonly ? '（只读）' : ''
    const draftLabel = this._currentDraftId ? `${versionInfo} ${readOnlyLabel}` : ''

    let html = `
      <div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span id="writing-chapter-title" style="font-size:14px;font-weight:bold;">
              ${hasSelection ? `第 ${this._currentChapter} 章` : '选择章节开始编辑'}
            </span>
            <span id="writing-version-info" style="color:var(--text-dim);font-size:11px;">${esc(draftLabel)}</span>
          </div>
          <div class="writing-editor-buttons" id="writing-editor-buttons">
            ${this._isReadonly ? `<button class="btn btn-primary" data-action="restore-from-version">基于此版本创建</button>` : ''}
            <button class="btn" data-action="autosave" id="btn-autosave" ${hasSelection && !this._isReadonly ? '' : 'disabled'}>${this._restoreSourceVersion ? '发布为新版本' : '暂存'}</button>
            <button class="btn btn-primary" data-action="publish" id="btn-publish" ${hasSelection && !this._isReadonly ? '' : 'disabled'}>发布</button>
            <button class="btn btn-primary" data-action="run-conflict-check" id="btn-conflict-check" ${hasSelection && !this._isReadonly ? '' : 'disabled'}>剧情设定冲突检查</button>
            ${this._renderEditorToolsMenu(hasSelection)}
          </div>
        </div>

        ${this._renderConflictCheckStrip()}

        ${this._renderVersionSelector()}
    `

    if (hasSelection) {
      html += `
        <input id="writing-title-input" type="text" value="${esc(this._currentTitle || '')}" placeholder="章节标题" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:13px;margin-bottom:6px;" ${this._isReadonly ? 'readonly' : ''} />

        <textarea id="writing-editor" style="
          width:100%;height:450px;background:var(--bg);color:var(--text);
          border:1px solid var(--border);border-radius:4px;padding:12px;
          font-family:var(--font-mono);font-size:13px;line-height:1.8;
          resize:vertical;
        " placeholder="在此书写正文..." ${this._isReadonly ? 'readonly' : ''}>${this._currentContent ? esc(this._currentContent) : ''}</textarea>
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

  _renderEditorToolsMenu(hasSelection) {
    const disabled = hasSelection && !this._isReadonly ? "" : "disabled"
    return `
      <details class="writing-tools-menu">
        <summary class="btn btn-sm">AI 工具 · 待定</summary>
        <div class="writing-tools-menu__body">
          <button class="btn btn-sm" data-action="ai-generate-draft" ${disabled}>AI 生成草稿</button>
          ${state.currentProjectId ? `<button class="btn btn-sm" data-action="open-map">打开地图</button>` : ""}
          ${state.currentProjectId ? `<button class="btn btn-sm" data-action="deep-import">深度导入</button>` : ""}
          ${this._findCurrentScene() && this._currentChapter ? `<button class="btn btn-sm" data-action="split-scene">断章至此</button>` : ""}
          ${this._chapterList.length > 0 ? `<button class="btn btn-sm" data-action="extract-cards">AI 提取章节卡</button>` : ""}
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
        <select id="version-selector" style="background:var(--bg);color:var(--text);border:1px solid var(--border);padding:3px 6px;border-radius:3px;font-size:12px;">
    `

    for (const v of this._versions) {
      const selected = v.version_number === this._currentVersionNumber
      const isCurLatest = v.version_number === this._versions[0]?.version_number
      html += `<option value="${v.id}" data-version="${v.version_number}" data-latest="${isCurLatest ? 1 : 0}" ${selected ? 'selected' : ''}>v${v.version_number}${isCurLatest ? ' (最新)' : ''}</option>`
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
    if (this._sceneMapSummarySceneId === currentScene.id &&
        (this._sceneMapSummary || this._sceneMapSummaryError || this._sceneMapSummaryLoading)) {
      return
    }
    this._sceneMapSummarySceneId = currentScene.id
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
      this._sceneMapSummaryLoading = false
      return null
    }
    this._sceneMapSummarySceneId = scene.id
    this._sceneMapSummaryError = null
    this._sceneMapSummaryLoading = true
    const isStale = () => this._currentSceneId && this._currentSceneId !== scene.id
    const isActiveRequest = () => this._sceneMapSummarySceneId === scene.id
    try {
      const summary = await api.world.getMapSceneSummary(state.currentProjectId, scene.id)
      if (isStale()) return null
      this._sceneMapSummary = summary
      this._sceneMapSummaryError = null
      return summary
    } catch {
      if (isStale()) return null
      this._sceneMapSummary = null
      this._sceneMapSummaryError = "地图摘要暂不可用"
      toast("地图摘要暂不可用", "warning")
      return null
    } finally {
      if (isActiveRequest()) {
        this._sceneMapSummaryLoading = false
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
        this._chapters[chapterIndex] = {
          title: this._versions[0].title,
          draftCount: this._versions.length,
        }
        const latest = this._versions[0]
        const draftData = await api.writing.get(latest.id, state.currentProjectId)
        this._currentDraftId = draftData.id
        this._currentContent = draftData.content || ""
        this._currentTitle = draftData.title || ""
        this._currentVersionNumber = latest.version_number
        this._currentUpdatedAt = draftData.updated_at || null
        this._lastSavedContent = draftData.content || ""
        this._isReadonly = false
      } else {
        this._currentDraftId = null
        this._currentContent = ""
        this._currentTitle = ""
        this._currentVersionNumber = null
        this._currentUpdatedAt = null
        this._lastSavedContent = null
        this._isReadonly = false

        // 检查 localStorage 后备（仅在首次加载且无服务端版本时）
        const backup = this._loadBackup(chapterIndex)
        if (backup && backup.content) {
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
          if (confirmed) {
            this._currentContent = backup.content
            this._currentTitle = backup.title || ""
          }
        }
      }
    } catch {
      this._versions = []
    }
  },

  async _newChapter() {
    const input = prompt("请输入章节号（1-N）：", (this._chapterList.length > 0 ? Math.max(...this._chapterList) + 1 : 1).toString())
    if (!input) return
    const idx = parseInt(input, 10)
    if (isNaN(idx) || idx < 1) { toast("请输入有效的章节号（≥1）", "warning"); return }

    // 保存当前章节内容
    await this._saveBeforeNavigate()

    this._currentChapter = idx
    this._currentDraftId = null
    this._currentContent = ''
    this._currentTitle = `第 ${idx} 章`
    this._currentVersionNumber = null
    this._currentUpdatedAt = null
    this._versions = []
    this._isReadonly = false
    this._restoreSourceVersion = null
    this._cursorOffset = 0

    if (!this._chapters[idx]) {
      this._chapters[idx] = { title: null, draftCount: 0 }
      this._chapterList.push(idx)
      this._chapterList.sort((a, b) => a - b)
    }

    await this._rerender()
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
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-dim);${isCurrent ? 'background:var(--hover-bg);border-radius:4px;padding:8px;' : ''}">
          <div>
            <span style="font-weight:500;">v${v.version_number}</span>
            ${isLatest ? ' <span class="badge badge-canonical">最新</span>' : ''}
            ${isCurrent ? ' <span style="color:var(--accent);font-size:11px;">当前</span>' : ''}
            <div style="font-size:11px;color:var(--text-dim);">${created} · ${wordCount} 字</div>
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-sm version-preview-btn" data-draft-id="${esc(v.id)}" data-version="${v.version_number}" data-is-latest="${isLatest ? 1 : 0}">预览</button>
            ${!isCurrent ? `<button class="btn btn-sm version-restore-btn" data-draft-id="${esc(v.id)}" data-version="${v.version_number}" data-is-latest="${isLatest ? 1 : 0}">恢复</button>` : ''}
          </div>
        </div>
      `
    }
    listHtml += "</div>"
    showModal(`第 ${this._currentChapter} 章 — 版本历史 (${this._versions.length})`, listHtml)

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
    if (!editor || this._autoSaving) return

    // 从历史版本恢复后编辑：走发布流程（POST 创建新版本），不覆盖旧版本
    if (this._restoreSourceVersion) {
      return this._publish()
    }

    if (!this._currentDraftId) return

    this._autoSaving = true
    const content = editor.value
    const title = titleInput ? titleInput.value.trim() : ""

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
    }
  },

  async _saveDraftForConflictCheck() {
    this._clearAutoSaveTimer()
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
    if (!state.currentProjectId || !this._currentChapter) {
      toast("请先选择章节", "warning")
      return
    }
    const editor = document.getElementById("writing-editor")
    if (!editor) return
    this._checkingConflicts = true
    try {
      await this._saveDraftForConflictCheck()
      const currentScene = this._findCurrentScene()
      const check = await api.writing.createConflictCheck({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        scene_id: currentScene?.id || null,
        draft_id: this._currentDraftId,
        version_number: this._currentVersionNumber,
        content: editor.value,
        include_candidates: false,
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
      }

      // 直接从发布结果获取 draftId，避免 _refreshVersions 偶发返回空版本
      const createdDraftId = result.draft?.id || null

      if (result.task_id) {
        this._publishTaskId = result.task_id
        this._publishProgress = { phase: "running", step: 0, message: "正在存入 RAG 系统...", showModal: false }
        this._startPublishPolling()
      }

      this._restoreSourceVersion = null
      await this._refreshVersions(this._currentChapter)
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
      confirmAction(message, () => resolve(true), confirmText)
      setTimeout(() => {
        const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
        if (cancelBtn) cancelBtn.onclick = () => resolve(false)
      }, 50)
    })
  },

  _startPublishPolling() {
    if (this._publishTimer) clearInterval(this._publishTimer)
    const poll = async () => {
      if (!this._publishTaskId) { this._stopPublishPolling(); return }
      try {
        const task = await api.tasks.get(this._publishTaskId)
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

        if (task.status === "done" && this._publishProgress && this._publishProgress.step >= 0.99) {
          this._publishProgress.step = 1
          this._publishProgress.phase = "done"
          this._publishProgress.message = "发布完成"
          this._updatePublishBar()
          this._stopPublishPolling()
          setTimeout(() => { this._publishProgress = null; this._rerender() }, 3000)
          return
        }

        if (task.status === "failed") {
          this._publishProgress.phase = "failed"
          const errMsg = task.error_message || "发布任务失败"
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
      } catch {
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
    showModal("发布失败", `
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
    showModal("断章", html, [{
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
    showModal("AI 提取章节卡", formHtml, [{
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

  _showDeepImportForm() {
    const lastChapter = this._chapterList.length > 0
      ? Math.max(...this._chapterList) : 10
    const firstChapter = this._chapterList.length > 0
      ? Math.min(...this._chapterList) : 1
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="deep-import-start" type="number" min="1" value="${firstChapter}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="deep-import-end" type="number" min="1" value="${lastChapter}" />
      </div>
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">
        自动执行三阶段：Scene 切分 → 实体提取 → 结构分析
      </p>
    `
    showModal("深度导入", formHtml, [{
      text: "开始导入", class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("deep-import-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("deep-import-end")?.value || "10", 10)
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        closeModal()
        await this._submitDeepImport(start, end)
      },
    }])
  },

  async _submitDeepImport(startChapter, endChapter, force = false) {
    try {
      const result = await api.imports.deepImport(
        state.currentProjectId, startChapter, endChapter, force,
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
        await this._submitDeepImport(startChapter, endChapter, true)
        return
      }

      if (!result.task_id) {
        toast(result.message || "深度导入未启动", "warning")
        return
      }

      this._deepImportTaskId = result.task_id
      this._deepImportProgress = {
        phase: "running", step: "scene_segmentation",
        message: "正在切分 Scene...", percent: 0,
        degraded: false, degradedBatches: [], phaseError: "",
        phaseErrors: [], qualityStatus: "pending", auditSummary: {}, snapshotHealthSummary: {},
      }
      this._persistDeepImportWorkflow(result.task_id, startChapter, endChapter)
      // 保留 legacy key，shared workflow recovery 会迁移旧刷新状态。
      try { localStorage.setItem("novel_deepImportTaskId", result.task_id) } catch {} // eslint-disable-line no-empty
      toast("深度导入已启动", "success")
      await this._rerender()
      this._startDeepImportPolling()
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  _startDeepImportPolling() {
    if (this._deepImportTimer) clearInterval(this._deepImportTimer)
    const poll = async () => {
      if (!this._deepImportTaskId) { this._stopDeepImportPolling(); return }
      try {
        const task = await api.tasks.get(this._deepImportTaskId)
        const result = task.result || {}
        const steps = result.completed_steps || []

        // 计算三阶段进度
        let percent = 0
        let stepLabel = ""
        if (steps.includes("scene_segmentation")) {
          percent = steps.includes("entity_extraction")
            ? (steps.includes("structure_analysis") ? 100 : 80)
            : 40
        }
        if (!steps.includes("scene_segmentation")) {
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

        if (task.status === "done" || result.phase === "done") {
          this._deepImportProgress.percent = 100
          this._deepImportProgress.phase = "done"
          this._stopDeepImportPolling()
          if (this._deepImportProgress.qualityStatus === "partial") {
            toast("深度导入部分完成，请查看降级原因", "warning")
          } else {
            toast("深度导入完成！", "success")
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
          toast("深度导入失败", "error")
          setTimeout(() => { this._deepImportProgress = null; this._rerender() }, 5000)
          return
        }
        await this._rerender()
      } catch {
        // polling error, ignore
      }
    }
    poll()
    this._deepImportTimer = setInterval(poll, 3000)
  },

  _stopDeepImportPolling() {
    if (this._deepImportTimer) { clearInterval(this._deepImportTimer); this._deepImportTimer = null }
    const taskId = this._deepImportTaskId
    this._deepImportTaskId = null
    this._clearDeepImportWorkflow(taskId)
  },

  _renderDeepImportBar() {
    if (!this._deepImportProgress) return ""
    const progress = this._normalizeDeepImportProgress()
    const actionsHtml = progress.failed
      ? `<button class="btn btn-sm" data-action="dismiss-deep-import" style="font-size:11px;">关闭</button>`
      : ""
    return renderFixedProgress(progress, {
      offset: 40,
      title: "深度导入",
      message: progress.message,
      showTaskId: false,
      actionsHtml: [this._renderDeepImportAuditSummary(), actionsHtml].filter(Boolean).join(""),
    })
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
    const status = p.phase === "failed"
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

    return normalizeTaskProgress({
      task_id: this._deepImportTaskId || "deep_import",
      task_type: "deep_import",
      status,
      progress: typeof p.percent === "number" ? p.percent : null,
      error_message: status === "failed" ? (p.phaseError || phaseErrorText || p.message || "深度导入失败") : null,
      result: {
        message: p.stepLabel || p.message || "深度导入中...",
        warnings,
        summary: isPartial ? "部分完成" : p.degraded ? "部分降级完成" : null,
      },
    }, "deep_import")
  },

  _persistDeepImportWorkflow(taskId, startChapter, endChapter) {
    persistActiveWorkflow({
      taskId,
      workflowType: "deep_import",
      label: "深度导入",
      projectId: state.currentProjectId,
      view: "writing",
      meta: { startChapter, endChapter },
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
      showModal(
        "深度导入快照状态",
        rows || failureHtml || retainedHtml
          ? `${rows}${failureHtml}${retainedHtml}`
          : '<p style="color:var(--text-dim);">暂无快照健康摘要</p>',
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
    showModal("深度导入快照状态", rows || '<p style="color:var(--text-dim);">暂无快照健康摘要</p>')
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
      "new-chapter": () => this._newChapter(),
      "delete-chapter": (_e, t) => this._deleteChapter(parseInt(t.getAttribute("data-chapter"), 10)),
      "autosave": () => this._autosave(),
      "publish": () => this._publish(),
      "ai-generate-draft": () => this._generateDraft(),
      "restore-from-version": () => this._restoreFromVersion(),
      "version-history": () => this._showVersionHistory(),
      "delete-version": () => this._deleteVersion(),
      "dismiss-publish-error": () => this._dismissPublishError(),
      "run-conflict-check": () => this._runConflictCheck(),
      "open-conflict-check": (_e, t) => this._openConflictCheck(t.getAttribute("data-check-id")),
      "deep-import": () => this._showDeepImportForm(),
      "open-map": () => this._openMapForCurrentScene(),
      "dismiss-deep-import": () => this._dismissDeepImport(),
      "view-deep-import-audit": () => this._showDeepImportAuditDetails(),
      "open-outline": () => router.navigate("outline", null),
      "split-scene": () => this._showSplitSceneForm(),
      "extract-cards": () => this._extractChapterCards(),
      "select-scene": (_e, t) => this._selectScene(t.getAttribute("data-scene-id")),
      "toggle-cockpit-module": (_e, t) => {
        const module = t.closest(".scene-cockpit-module")
        if (module) module.classList.toggle("is-collapsed")
      },
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
  },
}

router.registerView("writing", writingView)
window.writingView = writingView
export default writingView
