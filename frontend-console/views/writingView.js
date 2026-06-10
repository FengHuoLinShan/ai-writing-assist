/**
 * 手动工作台
 *
 * 左侧章节树 → 中间编辑器 → 版本管理。
 * 支持暂存、发布、版本切换、整章删除。
 */
import { bindWorkspaceClick } from "../shared/viewHelper.js"

const writingView = {
  _chapters: {},
  _chapterList: [],
  _currentChapter: null,
  _currentDraftId: null,
  _currentContent: null,
  _currentTitle: null,
  _currentVersionNumber: null,
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
      this._isReadonly = saved.isReadonly || false
      this._restoreSourceVersion = saved.restoreSourceVersion
    } else {
      this._currentChapter = null
      this._currentContent = null
      this._currentTitle = null
      this._currentDraftId = null
      this._currentVersionNumber = null
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

    this._loading = false

    if (saved && saved.currentChapter) {
      this._refreshVersions(saved.currentChapter)
      this._loadOutlineData(saved.currentChapter)
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
      `
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">
        手动工作台 — 选择章节，撰写正文。
      </p>
      <div style="display:grid;grid-template-columns:200px 1fr 260px;gap:12px;align-items:start;">
        ${this._renderSceneTree()}
        ${this._renderEditor()}
        ${this._renderScenePanel()}
      </div>
      ${this._renderPublishBar()}
      ${this._renderDeepImportBar()}
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  onLeave() {
    const editor = document.getElementById("writing-editor")
    state.viewStates.writing = {
      currentChapter: this._currentChapter,
      currentContent: editor ? editor.value : this._currentContent,
      currentTitle: this._currentTitle,
      currentDraftId: this._currentDraftId,
      currentVersionNumber: this._currentVersionNumber,
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

  onActivate() {
    // KeepAlive 恢复后重新绑定事件
    this._bindEvents()
    // 恢复编辑器焦点
    const editor = document.getElementById("writing-editor")
    if (editor && this._currentContent !== null) {
      editor.focus()
    }
  },

  onDeactivate() {
    // 保存当前编辑器内容到状态，避免缓存 DOM 与状态不一致
    const editor = document.getElementById("writing-editor")
    if (editor) {
      this._currentContent = editor.value
    }
    const titleInput = document.getElementById("writing-title-input")
    if (titleInput) {
      this._currentTitle = titleInput.value
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
          <div style="display:flex;align-items:center;gap:6px;">
            ${this._isReadonly ? `<button class="btn btn-primary" data-action="restore-from-version">基于此版本创建</button>` : ''}
            <button class="btn" data-action="autosave" id="btn-autosave" ${hasSelection && !this._isReadonly ? '' : 'disabled'}>暂存</button>
            <button class="btn btn-primary" data-action="publish" id="btn-publish" ${hasSelection && !this._isReadonly ? '' : 'disabled'}>发布</button>
            ${state.currentProjectId ? `<button class="btn btn-sm" data-action="deep-import" style="font-size:11px;color:var(--accent);">深度导入</button>` : ''}
          </div>
        </div>

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

  _renderVersionSelector() {
    if (!this._currentChapter || this._versions.length === 0) return ''

    const isLatest = this._currentVersionNumber === this._versions[0]?.version_number
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
    this._currentSceneId = null
    const scene = this._findCurrentScene()
    if (scene) {
      this._currentSceneId = scene.id
    }
  },

  _renderScenePanel() {
    const currentScene = this._findCurrentScene()

    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;font-size:12px;">
        <div style="font-size:13px;font-weight:bold;margin-bottom:8px;">当前 Scene</div>
    `

    if (currentScene) {
      const s = currentScene
      const tagLabels = {
        inciting_incident: "激励事件", rising_action: "冲突升级",
        climax: "阶段高潮", valley: "低谷", transition: "过渡",
        hook: "钩子", payoff: "爽点", draft: "草稿",
      }
      const tagLabel = tagLabels[s.narrative_tag] || s.narrative_tag || "草稿"
      const tagClass = `narrative-tag-${s.narrative_tag || "draft"}`

      html += `
        <div style="margin-bottom:10px;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
            <span style="font-family:var(--font-mono);font-size:14px;font-weight:600;">#${s.scene_index}</span>
            <span class="narrative-tag ${tagClass}">${tagLabel}</span>
          </div>
          <div style="font-size:14px;font-weight:500;margin-bottom:8px;">${esc(s.title || "未命名 Scene")}</div>
          ${s.goal ? `<div style="margin-bottom:6px;"><div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">目标</div><div style="color:var(--text);">${esc(s.goal)}</div></div>` : ''}
          ${s.core_conflict ? `<div style="margin-bottom:6px;"><div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">冲突</div><div style="color:var(--text);">${esc(s.core_conflict)}</div></div>` : ''}
          ${s.emotional_beat ? `<div style="margin-bottom:6px;"><div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">情感</div><div style="color:var(--text);">${esc(s.emotional_beat)}</div></div>` : ''}
          ${s.must_happen ? `<div style="margin-bottom:6px;"><div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">必须发生</div><div style="color:var(--text);">${esc(s.must_happen)}</div></div>` : ''}
          ${s.must_not_happen ? `<div style="margin-bottom:6px;"><div style="color:var(--text-dim);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;">禁止发生</div><div style="color:var(--text);">${esc(s.must_not_happen)}</div></div>` : ''}
        </div>
      `
    } else {
      html += `
        <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px;">
          当前章节未关联 Scene。${this._scenes.length > 0 ? '请选择左侧 Scene 节点。' : '请先在大纲视图中创建 Scene 卡。'}
        </div>
      `
    }

    html += `
      <hr style="border:none;border-top:1px solid var(--border);margin:8px 0;">
      <button class="btn btn-sm" data-action="open-outline" style="font-size:11px;width:100%;">管理大纲</button>
    `

    html += '</div>'
    return html
  },

  _renderPublishBar() {
    if (!this._publishProgress) return ''

    const progress = this._publishProgress
    const steps = [
      { key: "save", label: "写入草稿" },
      { key: "rag", label: "正在存入 RAG 系统..." },
      { key: "snapshot", label: "正在创建历史状态..." },
    ]

    let html = `
      <div style="position:fixed;bottom:0;left:0;right:0;background:var(--panel);border-top:1px solid var(--border);padding:8px 16px;z-index:100;font-size:12px;">
        <div style="display:flex;align-items:center;gap:8px;max-width:900px;margin:0 auto;">
          <span style="white-space:nowrap;">${progress.message || '发布中...'}</span>
          <div style="flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
            <div id="publish-bar-fill" style="height:100%;width:${Math.round(progress.step * 50)}%;background:var(--accent);transition:width 0.5s;"></div>
          </div>
    `

    if (progress.phase === "failed") {
      html += `<button class="btn btn-sm" data-action="dismiss-publish-error" style="font-size:11px;">关闭</button>`
    }

    html += '</div></div>'
    return html
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
    delete state.viewStates.writing
    this._currentChapter = chapterIndex
    this._currentDraftId = null
    this._currentContent = null
    this._currentTitle = null
    this._currentVersionNumber = null
    this._versions = []
    this._isReadonly = false
    this._restoreSourceVersion = null

    await Promise.all([
      this._refreshVersions(chapterIndex),
      this._loadOutlineData(chapterIndex),
    ])
    this._updateCurrentScene()
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
        this._currentContent = draftData.content || ''
        this._currentTitle = draftData.title || ''
        this._currentVersionNumber = latest.version_number
        this._isReadonly = false
      } else {
        this._currentDraftId = null
        this._currentContent = ''
        this._currentTitle = ''
        this._currentVersionNumber = null
        this._isReadonly = false
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

    this._currentChapter = idx
    this._currentDraftId = null
    this._currentContent = ''
    this._currentTitle = `第 ${idx} 章`
    this._currentVersionNumber = null
    this._versions = []
    this._isReadonly = false
    this._restoreSourceVersion = null

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
      const wordCount = v.word_count || (v.content ? v.content.length : 0)
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
    this._restoreSourceVersion = null

    await this._rerender()
    toast(`已基于 v${this._currentVersionNumber} 开始编辑，发布后将创建新版本`, "info")
  },

  // ============================================================
  // 暂存 & 发布
  // ============================================================

  async _autosave() {
    const editor = document.getElementById("writing-editor")
    const titleInput = document.getElementById("writing-title-input")
    if (!editor || !this._currentDraftId) return

    const content = editor.value
    const title = titleInput ? titleInput.value.trim() : ''

    try {
      const result = await api.writing.autosave(this._currentDraftId, { title, content }, state.currentProjectId)
      this._currentContent = content
      this._currentTitle = title
      this._currentVersionNumber = result.version_number

      if (this._chapters[this._currentChapter]) {
        this._chapters[this._currentChapter].title = title
      }
      toast("已暂存", "success")
    } catch (err) {
      toast(err.message || "暂存失败", "error")
    }
  },

  async _publish() {
    const editor = document.getElementById("writing-editor")
    const titleInput = document.getElementById("writing-title-input")
    if (!editor) return

    const content = editor.value.trim()
    if (!content) { toast("草稿内容不能为空", "warning"); return }
    const title = titleInput ? titleInput.value.trim() : `第 ${this._currentChapter} 章`

    const btnPublish = document.getElementById("btn-publish")
    const btnAutosave = document.getElementById("btn-autosave")
    if (btnPublish) btnPublish.disabled = true
    if (btnAutosave) btnAutosave.disabled = true

    try {
      const result = await api.writing.publish({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        title,
        content,
      })

      this._currentContent = content
      this._currentTitle = title

      if (this._chapters[this._currentChapter]) {
        this._chapters[this._currentChapter].title = title
      }

      if (result.task_id) {
        this._publishTaskId = result.task_id
        this._publishProgress = { phase: "running", step: 0, message: "正在存入 RAG 系统...", showModal: false }
        this._startPublishPolling()
      }

      await this._refreshVersions(this._currentChapter)
      await this._rerender()
      toast("已发布", "success")
    } catch (err) {
      toast(err.message || "发布失败", "error")
      if (btnPublish) btnPublish.disabled = false
      if (btnAutosave) btnAutosave.disabled = false
    }
  },

  _startPublishPolling() {
    if (this._publishTimer) clearInterval(this._publishTimer)
    const poll = async () => {
      if (!this._publishTaskId) { this._stopPublishPolling(); return }
      try {
        const task = await api.tasks.get(this._publishTaskId)

        if (task.progress !== undefined && task.progress !== null) {
          const p = parseFloat(task.progress)
          this._publishProgress.step = p
          this._publishProgress.phase = task.status
          if (p < 0.5) {
            this._publishProgress.message = "正在存入 RAG 系统..."
          } else if (p < 1.0) {
            this._publishProgress.message = "正在创建历史状态..."
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
        await this._rerender()
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
    const bar = document.getElementById("publish-bar-fill")
    if (bar && this._publishProgress) {
      bar.style.width = Math.round(this._publishProgress.step * 100) + "%"
    }
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

  async _submitDeepImport(startChapter, endChapter) {
    try {
      const result = await api.imports.deepImport(
        state.currentProjectId, startChapter, endChapter,
      )
      if (result.warning) {
        const confirmed = await new Promise((resolve) => {
          confirmAction(result.warning, () => resolve(true), "确认覆盖")
          // Add cancel handler
          setTimeout(() => {
            const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
            if (cancelBtn) cancelBtn.onclick = () => resolve(false)
          }, 50)
        })
        if (!confirmed) return
      }

      this._deepImportTaskId = result.task_id
      this._deepImportProgress = {
        phase: "running", step: "scene_segmentation",
        message: "正在切分 Scene...", percent: 0,
      }
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
        }

        if (task.status === "done" || result.phase === "done") {
          this._deepImportProgress.percent = 100
          this._deepImportProgress.phase = "done"
          this._stopDeepImportPolling()
          toast("深度导入完成！", "success")
          setTimeout(() => { this._deepImportProgress = null; this._rerender() }, 3000)
          return
        }
        if (task.status === "failed") {
          this._deepImportProgress.phase = "failed"
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
    this._deepImportTaskId = null
  },

  _renderDeepImportBar() {
    if (!this._deepImportProgress) return ""
    const p = this._deepImportProgress
    return `
      <div style="position:fixed;bottom:40px;left:0;right:0;background:var(--panel);border-top:1px solid var(--accent);padding:8px 16px;z-index:100;font-size:12px;">
        <div style="display:flex;align-items:center;gap:8px;max-width:900px;margin:0 auto;">
          <span style="white-space:nowrap;font-weight:500;">${esc(p.stepLabel || p.message || "深度导入中...")}</span>
          <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
            <div style="height:100%;width:${p.percent || 0}%;background:var(--accent);transition:width 0.5s;border-radius:3px;"></div>
          </div>
          <span style="font-family:var(--font-mono);font-size:11px;white-space:nowrap;">${p.percent || 0}%</span>
          ${p.degraded ? '<span style="color:var(--warning);font-size:10px;">(部分降级)</span>' : ""}
          ${p.phase === "failed" ? `<button class="btn btn-sm" data-action="dismiss-deep-import" style="font-size:11px;">关闭</button>` : ""}
        </div>
      </div>
    `
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
      "restore-from-version": () => this._restoreFromVersion(),
      "version-history": () => this._showVersionHistory(),
      "delete-version": () => this._deleteVersion(),
      "dismiss-publish-error": () => this._dismissPublishError(),
      "deep-import": () => this._showDeepImportForm(),
      "dismiss-deep-import": () => { this._deepImportProgress = null; this._rerender() },
      "open-outline": () => router.navigate("outline", null),
      "select-scene": (_e, t) => this._selectScene(t.getAttribute("data-scene-id")),
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
      titleInput.oninput = () => { this._currentTitle = titleInput.value }
    }
    const editorEl = document.getElementById("writing-editor")
    if (editorEl) {
      editorEl.oninput = () => { this._currentContent = editorEl.value }
    }
  },

  async _rerender() {
    const container = document.getElementById("workspace-content")
    if (container) {
      container.innerHTML = await this.render()
    }
  },
}

router.registerView("writing", writingView)
window.writingView = writingView
export default writingView
