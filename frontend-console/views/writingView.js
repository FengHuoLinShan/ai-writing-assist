/**
 * 手动工作台
 *
 * 左侧章节树 → 中间编辑器 → 右侧细纲面板。
 * 支持草稿版本管理、状态流转、章节卡关联查看。
 */
const writingView = {
  /** @type {Object<number, {hasCard, hasDraft, cardTitle, cardStatus}>} */
  _chapters: {},

  /** @type {number[]} 排序后的章节索引列表 */
  _chapterList: [],

  /** @type {number|null} 当前选中的章节索引 */
  _currentChapter: null,

  /** @type {string|null} 当前草稿 ID */
  _currentDraftId: null,

  /** @type {string|null} 当前草稿内容（编辑器中的文本） */
  _currentContent: null,

  /** @type {string|null} 当前草稿状态 */
  _currentDraftStatus: null,

  /** @type {number|null} 当前草稿版本号 */
  _currentDraftVersion: null,

  /** @type {Object|null} 当前章节卡数据 */
  _currentCard: null,

  /** @type {boolean} 加载状态 */
  _loading: true,

  /** @type {Object} 提取任务状态 */
  _extractionTasks: {},
  _extractionTimer: null,
  _extractionMessage: "",

  // ── 深度导入流水线 ──
  _deepImportTaskId: null,
  _deepImportPhase: "idle",
  _deepImportMessage: "",
  _deepImportProgress: 0,
  _deepImportCompleted: [],
  _deepImportTimer: null,

  // ============================================================
  // 生命周期
  // ============================================================

  async onEnter() {
    const saved = state.viewStates.writing

    if (saved) {
      // 恢复保存的编辑状态（不重新加载服务器草稿）
      this._currentChapter = saved.currentChapter
      this._currentContent = saved.currentContent
      this._currentDraftId = saved.currentDraftId
      this._currentDraftStatus = saved.currentDraftStatus
      this._currentDraftVersion = null
      this._currentCard = null
      this._loading = true
      this._chapters = {}
      this._chapterList = []
    } else {
      // 无保存状态，完全重置
      this._currentChapter = null
      this._currentContent = null
      this._currentDraftId = null
      this._currentDraftStatus = null
      this._currentDraftVersion = null
      this._currentCard = null
      this._loading = true
      this._chapters = {}
      this._chapterList = []
    }
    this._deepImportTimer = null

    // 清理提取轮询（仅当无运行中任务时）
    const hasRunning = Object.values(this._extractionTasks).some((t) => t.status === "running")
    if (!hasRunning && this._extractionTimer) {
      clearInterval(this._extractionTimer)
      this._extractionTimer = null
    }

    if (!state.currentProjectId) {
      this._loading = false
      return
    }

    // 并行获取章节卡 + 有草稿的章节索引（始终刷新）
    try {
      const [cardData, draftData] = await Promise.all([
        api.outline.listChapterCards({ novel_id: state.currentProjectId, limit: 50 }),
        api.writing.listChapters(state.currentProjectId),
      ])

      const cards = cardData.items || []
      const draftIndices = draftData.chapter_indices || []

      const allIndices = new Set([
        ...cards.map((c) => c.chapter_index),
        ...draftIndices,
      ])

      for (const idx of allIndices) {
        const card = cards.find((c) => c.chapter_index === idx)
        this._chapters[idx] = {
          hasCard: !!card,
          hasDraft: draftIndices.includes(idx),
          cardTitle: card?.title || null,
          cardStatus: card?.status || null,
        }
      }

      this._chapterList = [...allIndices].sort((a, b) => a - b)
    } catch {
      // 加载失败时显示空列表
    }

    this._loading = false

    // 恢复保存状态后异步加载章节卡（不阻塞渲染）
    if (saved && saved.currentChapter) {
      this._loadChapterCard(saved.currentChapter)
    }

    // 从 localStorage 恢复深度导入任务
    const deepImportSaved = localStorage.getItem("novel_deep_import_task")
    if (deepImportSaved) {
      try {
        const parsed = JSON.parse(deepImportSaved)
        if (parsed.taskId && parsed.projectId === state.currentProjectId) {
          this._deepImportTaskId = parsed.taskId
          this._pollDeepImportTask()
        } else {
          localStorage.removeItem("novel_deep_import_task")
        }
      } catch {
        localStorage.removeItem("novel_deep_import_task")
      }
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
          <p>暂无章节</p>
          <p style="color:var(--text-dim);font-size:12px;">
            请先在「剧情结构 → 章节卡」中创建章节卡，或上传/导入正文草稿。
          </p>
          <div style="margin-top:8px;">
            <button class="btn btn-primary" data-action="nav-chapters">前往章节卡</button>
          </div>
        </div>
      `
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">
        手动工作台 — 逐章书写正文，左侧选章，右侧查看细纲。
      </p>
      <div style="display:grid;grid-template-columns:250px 1fr 300px;gap:12px;align-items:start;">
        ${this._renderChapterTree()}
        ${this._renderEditor()}
        ${this._renderSidePanel()}
      </div>
      ${this._renderExtractionPanel()}
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  onLeave() {
    // 保存当前编辑状态
    state.viewStates.writing = {
      currentChapter: this._currentChapter,
      currentContent: this._currentContent,
      currentDraftId: this._currentDraftId,
      currentDraftStatus: this._currentDraftStatus,
    }
    if (this._deepImportTimer) {
      clearInterval(this._deepImportTimer)
      this._deepImportTimer = null
    }
    if (this._extractionTimer) {
      clearInterval(this._extractionTimer)
      this._extractionTimer = null
    }
  },

  // ============================================================
  // 左侧：章节树
  // ============================================================

  _renderChapterTree() {
    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;">
        <div class="card-title" style="display:flex;justify-content:space-between;align-items:center;">
          <span>章节（${this._chapterList.length}）</span>
        </div>
        <div style="margin-top:4px;">
    `

    for (const idx of this._chapterList) {
      const ch = this._chapters[idx]
      const isActive = idx === this._currentChapter
      const badges = []
      if (ch.hasDraft) badges.push('<span class="badge badge-draft" style="font-size:10px;">草稿</span>')
      if (ch.hasCard) badges.push('<span class="badge badge-card" style="font-size:10px;">章节卡</span>')

      html += `
        <div class="clickable chapter-item ${isActive ? 'active' : ''}"
             style="padding:8px 10px;border-left:3px solid ${isActive ? 'var(--accent)' : 'transparent'};margin-bottom:2px;background:${isActive ? 'var(--hover-bg)' : 'transparent'};border-radius:0 4px 4px 0;"
             data-action="select-chapter" data-chapter="${idx}">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:4px;flex-wrap:wrap;">
            <strong style="font-size:13px;">第 ${idx} 章</strong>
            <span style="display:flex;gap:3px;">${badges.join('')}</span>
          </div>
          ${ch.cardTitle ? `<div style="color:var(--text-dim);font-size:11px;margin-top:2px;">${esc(ch.cardTitle)}</div>` : ''}
        </div>
      `
    }

    html += '</div></div>'
    return html
  },

  // ============================================================
  // 中间：编辑器
  // ============================================================

  _renderEditor() {
    const hasSelection = this._currentChapter !== null
    const title = hasSelection ? `第 ${this._currentChapter} 章` : "选择章节开始编辑"
    const statusText = hasSelection
      ? (this._currentDraftVersion
          ? `v${this._currentDraftVersion} · ${this._currentDraftStatus || "draft"} · ${this._currentDraftUpdatedAt || ""}`
          : "新草稿")
      : ""

    const wordCount = this._currentContent
      ? this._currentContent.replace(/\s/g, "").length + " 字"
      : ""

    const statusLabels = { draft: "草稿", candidate: "候选", canonical: "正史", deprecated: "废弃" }
    const statusColors = { draft: "var(--text-dim)", candidate: "var(--warning)", canonical: "var(--accent)", deprecated: "var(--danger)" }
    const currentStatusLabel = statusLabels[this._currentDraftStatus] || this._currentDraftStatus || ""

    const statusActions = []
    if (this._currentDraftStatus === "draft") {
      statusActions.push({ status: "candidate", label: "标记为候选" })
    } else if (this._currentDraftStatus === "candidate") {
      statusActions.push({ status: "canonical", label: "标记为正史" })
      statusActions.push({ status: "draft", label: "返回草稿" })
    } else if (this._currentDraftStatus === "canonical") {
      statusActions.push({ status: "draft", label: "返回草稿" })
    }

    let html = `
      <div>
        <div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;">
          <div>
            <span id="writing-chapter-title" style="font-size:14px;font-weight:bold;">${title}</span>
            <span id="writing-draft-status" style="color:var(--text-dim);font-size:11px;margin-left:8px;">${esc(statusText)}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            ${currentStatusLabel ? `<span class="badge" style="background:${statusColors[this._currentDraftStatus] || 'var(--text-dim)'};color:var(--bg);font-size:10px;">${currentStatusLabel}</span>` : ''}
            <span style="color:var(--text-dim);font-size:11px;" id="writing-word-count">${wordCount}</span>
          </div>
        </div>

        <textarea id="writing-editor" style="
          width:100%;height:400px;background:var(--bg);color:var(--text);
          border:1px solid var(--border);border-radius:4px;padding:12px;
          font-family:var(--font-mono);font-size:13px;line-height:1.8;
          resize:vertical;
        " placeholder="${hasSelection ? '在此书写正文...' : '请从左侧选择章节'}" ${hasSelection ? '' : 'disabled'}>${this._currentContent ? esc(this._currentContent) : ''}</textarea>

        <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
          <button class="btn btn-primary" id="btn-save-draft" data-action="save-draft" ${hasSelection ? '' : 'disabled'}>保存草稿</button>
          <button class="btn" id="btn-save-analyze-geo" data-action="save-analyze-geo" ${hasSelection ? '' : 'disabled'}>💾 保存并分析地缘</button>
          <button class="btn" id="btn-prev-chapter" data-action="prev-chapter" ${this._hasPrev() ? '' : 'disabled'}>上一章</button>
          <button class="btn" id="btn-next-chapter" data-action="next-chapter" ${this._hasNext() ? '' : 'disabled'}>下一章</button>
          <button class="btn" data-action="export-draft" ${hasSelection ? '' : 'disabled'}>导出本章</button>
          <span style="flex:1;"></span>
          ${statusActions.map((a) =>
            `<button class="btn btn-sm" data-action="update-status" data-status="${a.status}" style="font-size:11px;">${a.label}</button>`
          ).join("")}
          ${this._currentChapter !== null
            ? `<button class="btn btn-sm" data-action="show-version-history" style="font-size:11px;">查看版本历史</button>`
            : ""}
        </div>
      </div>
    `
    return html
  },

  _hasPrev() {
    if (this._currentChapter === null) return false
    const i = this._chapterList.indexOf(this._currentChapter)
    return i > 0
  },

  _hasNext() {
    if (this._currentChapter === null) return false
    const i = this._chapterList.indexOf(this._currentChapter)
    return i < this._chapterList.length - 1
  },

  _prevChapter() {
    const i = this._chapterList.indexOf(this._currentChapter)
    if (i > 0) this._selectChapter(this._chapterList[i - 1])
  },

  _nextChapter() {
    const i = this._chapterList.indexOf(this._currentChapter)
    if (i < this._chapterList.length - 1) this._selectChapter(this._chapterList[i + 1])
  },

  // ============================================================
  // 右侧：细纲面板 + 深度导入
  // ============================================================

  _renderSidePanel() {
    const hasCard = this._currentCard !== null

    let html = `
      <div class="card" style="max-height:600px;overflow-y:auto;">
        <div class="card-title" style="font-size:13px;">
          ${hasCard ? `📋 ${esc(this._currentCard.title || `第${this._currentChapter}章`)}` : "📋 细纲"}
        </div>
        <div style="margin-top:8px;">
    `

    if (hasCard) {
      const card = this._currentCard
      // 核心字段（默认展开）
      html += this._cardSection("🎯 核心目标", card.chapter_goal, true)
      html += this._cardSection("⚔️ 主要冲突", card.main_conflict, true)

      // 场景细纲
      const scenes = Array.isArray(card.scene_cards) ? card.scene_cards : []
      html += `
        <details open style="margin-bottom:6px;">
          <summary style="cursor:pointer;font-size:12px;font-weight:bold;color:var(--text);">🎬 场景细纲（${scenes.length}）</summary>
          <div style="margin-top:4px;padding-left:8px;">
      `
      if (scenes.length > 0) {
        for (let i = 0; i < scenes.length; i++) {
          const s = scenes[i]
          html += `<div style="font-size:11px;color:var(--text);margin-bottom:4px;padding:4px 6px;background:var(--panel);border-radius:3px;">
            <strong>${i + 1}.</strong> ${esc(s.summary || s.description || s.scene_summary || JSON.stringify(s))}
          </div>`
        }
      } else {
        html += `<div style="font-size:11px;color:var(--text-dim);">暂无场景细纲</div>`
      }
      html += '</div></details>'

      // 折叠字段
      html += this._cardCollapsible("尾钩", card.ending_hook)
      html += this._cardCollapsible("情绪基调", card.emotional_point)
      html += this._cardCollapsible("必发生事件", card.must_happen)
      html += this._cardCollapsible("不能发生事件", card.must_not_happen)
      html += this._cardCollapsible("剧情功能", card.plot_function)
      html += this._cardCollapsible("隐藏进展", card.hidden_progress)
      html += this._cardCollapsible("幕外进展", card.offscreen_progress)
    } else {
      html += `
        <div style="font-size:12px;color:var(--text-dim);text-align:center;padding:20px 0;">
          ${this._currentChapter !== null
            ? '暂无章节卡。<br>可在「剧情结构 → 章节卡」中创建。'
            : '请从左侧选择章节'}
        </div>
      `
    }

    html += '</div></div>'
    return html
  },

  _renderExtractionPanel() {
    return `
      <div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <div class="card" style="font-size:11px;">
          <div class="card-title" style="font-size:12px;">📥 剧情结构提取</div>
          <div style="margin-top:6px;">
            <div style="display:flex;gap:4px;align-items:center;margin-bottom:6px;">
              <span style="color:var(--text-dim);">章节：</span>
              <input type="number" id="writing-ext-start" min="1" value="1" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:11px;" />
              <span style="color:var(--text-dim);font-size:11px;">~</span>
              <input type="number" id="writing-ext-end" min="1" value="10" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:11px;" />
            </div>
            ${this._renderExtractionSteps()}
          </div>
        </div>
        <div class="card" style="font-size:11px;">
          <div class="card-title" style="font-size:12px;">🔗 深度导入（三步流水线）</div>
          <div id="deep-import-panel" style="margin-top:6px;">
            <div style="display:flex;gap:4px;align-items:center;">
              <span style="color:var(--text-dim);">章节：</span>
              <input type="number" id="deep-import-start" min="1" value="1" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:11px;" />
              <span style="color:var(--text-dim);font-size:11px;">~</span>
              <input type="number" id="deep-import-end" min="1" value="10" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:11px;" />
              <button class="btn btn-sm btn-primary" data-action="submit-deep-import" id="btn-deep-import-start" style="margin-left:4px;">开始</button>
            </div>
            <div id="deep-import-progress" style="display:none;margin-top:6px;">
              <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
                <div id="deep-import-bar" style="height:100%;width:0%;background:var(--accent);transition:width 0.5s;"></div>
              </div>
              <p id="deep-import-status" style="color:var(--text-dim);font-size:10px;margin-top:3px;"></p>
              <div id="deep-import-steps" style="margin-top:4px;font-size:10px;">
                <div id="step-extract_world" class="deep-step"><span class="step-icon">☐</span> 1. 世界对象抽取<span class="step-action" style="display:none;"></span></div>
                <div id="step-sync_characters" class="deep-step" style="margin-top:2px;"><span class="step-icon">☐</span> 2. 同步人物档案</div>
                <div id="step-generate_plot" class="deep-step" style="margin-top:2px;"><span class="step-icon">☐</span> 3. 剧情结构生成</div>
              </div>
              <div id="deep-import-actions" style="margin-top:4px;display:none;">
                <button class="btn btn-sm" data-action="goto-review" id="btn-deep-goto-review">前往审查</button>
                <button class="btn btn-sm btn-primary" data-action="resume-deep-import" id="btn-deep-resume" style="display:none;">继续深度导入</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `
  },

  _renderExtractionSteps() {
    const steps = [
      { key: "world", label: "世界对象抽取", taskType: "world_entity_extraction" },
      { key: "plot", label: "剧情线/篇章纲生成", taskType: "plot_structure_generate" },
      { key: "cards", label: "章节卡提取", taskType: "chapter_card_extraction" },
    ]

    let html = ""
    for (const step of steps) {
      const s = this._extractionTasks[step.key] || { status: "idle", message: "" }
      const isRunning = s.status === "running"
      const isDone = s.status === "done"
      const icon = isRunning ? "⏳" : isDone ? "✅" : "☐"

      html += `
        <div style="display:flex;align-items:center;gap:6px;padding:3px 0;border-top:1px solid var(--border);">
          <span style="font-size:11px;${isRunning ? 'color:var(--accent);' : ''}">${icon} ${step.label}</span>
          <span style="flex:1;"></span>
          <button class="btn btn-sm" data-action="submit-writing-extraction" data-key="${step.key}" data-task-type="${step.taskType}"
            ${isRunning ? 'disabled' : ''} style="font-size:10px;">
            ${isRunning ? "运行中..." : isDone ? "已完成" : "开始"}
          </button>
        </div>
      `
    }

    if (this._extractionMessage) {
      html += `<p style="font-size:10px;color:var(--text-dim);margin-top:4px;">${this._extractionMessage}</p>`
    }

    return html
  },

  _cardSection(label, value, isOpen) {
    if (!value && value !== 0) return ""
    const display = Array.isArray(value) ? value.join("、") : String(value)
    return `
      <details ${isOpen ? 'open' : ''} style="margin-bottom:4px;">
        <summary style="cursor:pointer;font-size:12px;font-weight:bold;color:var(--text);">${label}</summary>
        <p style="margin:4px 0 0 8px;font-size:11px;color:var(--text-muted);line-height:1.5;">${esc(display)}</p>
      </details>
    `
  },

  _cardCollapsible(label, value) {
    if (!value && !Array.isArray(value)) return ""
    const display = Array.isArray(value)
      ? (value.length > 0 ? value.map((v) => `• ${typeof v === "object" ? JSON.stringify(v) : v}`).join("<br>") : "无")
      : String(value)
    return `
      <details style="margin-bottom:2px;">
        <summary style="cursor:pointer;font-size:11px;color:var(--text-dim);">${label}</summary>
        <p style="margin:2px 0 0 8px;font-size:11px;color:var(--text-muted);line-height:1.4;">${esc(display)}</p>
      </details>
    `
  },

  // ============================================================
  // 章节选择
  // ============================================================

  async _selectChapter(chapterIndex) {
    // 用户主动切换章节，清除已保存的编辑状态
    delete state.viewStates.writing
    this._currentChapter = chapterIndex
    this._currentContent = null
    this._currentDraftId = null
    this._currentDraftStatus = null
    this._currentDraftVersion = null
    this._currentDraftUpdatedAt = null
    this._currentCard = null

    // 渲染骨架（细纲面板显示"加载中"）
    let content = document.getElementById("workspace-content")
    if (content) {
      const html = await this.render()
      content.innerHTML = html
    }

    // 并行加载草稿 + 章节卡，加载完成后重新渲染
    await Promise.all([
      this._loadDraft(chapterIndex),
      this._loadChapterCard(chapterIndex),
    ])

    content = document.getElementById("workspace-content")
    if (content) {
      const html = await this.render()
      content.innerHTML = html
      // 恢复编辑器内容（render 创建了新 textarea）
      const editor = document.getElementById("writing-editor")
      if (editor && this._currentContent) editor.value = this._currentContent
    }
  },

  async _loadDraft(chapterIndex) {
    if (!state.currentProjectId) return
    try {
      const data = await api.writing.getDraft(chapterIndex, state.currentProjectId)
      if (data && (data.content || data.summary)) {
        this._currentContent = data.content || data.summary || ""
        this._currentDraftId = data.id
        this._currentDraftStatus = data.status || "draft"
        this._currentDraftVersion = data.version_number || 1
        this._currentDraftUpdatedAt = data.updated_at
          ? new Date(data.updated_at).toLocaleString("zh-CN")
          : ""

        const editor = document.getElementById("writing-editor")
        if (editor) editor.value = this._currentContent
        this._updateStatusDisplay()
      }
    } catch {
      // 无草稿，保持新草稿状态
    }
  },

  async _loadChapterCard(chapterIndex) {
    if (!state.currentProjectId) return
    try {
      const card = await api.outline.getChapterCardByIndex(chapterIndex, state.currentProjectId)
      if (card) {
        this._currentCard = card
        // 刷新右侧面板
        const sidePanel = document.querySelector(".card:last-child")
        if (sidePanel && sidePanel.parentElement) {
          // 本版本简单全量重绘右侧
        }
      }
    } catch {
      this._currentCard = null
    }
  },

  _updateStatusDisplay() {
    const statusEl = document.getElementById("writing-draft-status")
    if (statusEl && this._currentDraftVersion) {
      statusEl.textContent = `v${this._currentDraftVersion} · ${this._currentDraftStatus || "draft"} · ${this._currentDraftUpdatedAt || ""}`
    }
    const countEl = document.getElementById("writing-word-count")
    if (countEl && this._currentContent) {
      countEl.textContent = this._currentContent.replace(/\s/g, "").length + " 字"
    }
  },

  // ============================================================
  // 草稿操作
  // ============================================================

  async saveDraft() {
    const editor = document.getElementById("writing-editor")
    if (!editor || !this._currentChapter) return

    const content = editor.value.trim()
    if (!content) {
      toast("草稿内容不能为空", "warning")
      return
    }

    try {
      const result = await api.writing.saveDraft({
        novel_id: state.currentProjectId,
        chapter_index: this._currentChapter,
        title: `第${this._currentChapter}章`,
        content: content,
      })
      this._currentContent = content
      this._currentDraftId = result.id
      this._currentDraftStatus = result.status || "draft"
      this._currentDraftVersion = result.version_number || 1
      this._currentDraftUpdatedAt = result.updated_at
        ? new Date(result.updated_at).toLocaleString("zh-CN")
        : ""

      if (!this._chapters[this._currentChapter]) {
        this._chapters[this._currentChapter] = { hasCard: false, hasDraft: true, cardTitle: null, cardStatus: null }
      }
      this._chapters[this._currentChapter].hasDraft = true
      if (!this._chapterList.includes(this._currentChapter)) {
        this._chapterList.push(this._currentChapter)
        this._chapterList.sort((a, b) => a - b)
      }

      delete state.viewStates.writing

      this._updateStatusDisplay()
      toast("草稿已保存", "success")
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async _saveAndAnalyze() {
    const editor = document.getElementById("writing-editor")
    if (!editor || !this._currentChapter) return

    const content = editor.value.trim()
    if (!content) {
      toast("草稿内容不能为空", "warning")
      return
    }

    const btn = document.getElementById("btn-save-analyze-geo")
    if (btn) btn.disabled = true

    try {
      const result = await api.writing.saveAndAnalyze(
        state.currentProjectId,
        this._currentChapter,
        content,
      )
      this._currentContent = content
      if (result.draft) {
        this._currentDraftId = result.draft.id
        this._currentDraftStatus = result.draft.status || "draft"
        this._currentDraftVersion = result.draft.version_number || 1
        this._currentDraftUpdatedAt = result.draft.updated_at
          ? new Date(result.draft.updated_at).toLocaleString("zh-CN")
          : ""
      }

      if (!this._chapters[this._currentChapter]) {
        this._chapters[this._currentChapter] = { hasCard: false, hasDraft: true, cardTitle: null, cardStatus: null }
      }
      this._chapters[this._currentChapter].hasDraft = true
      if (!this._chapterList.includes(this._currentChapter)) {
        this._chapterList.push(this._currentChapter)
        this._chapterList.sort((a, b) => a - b)
      }

      delete state.viewStates.writing

      if (result.proposal_created) {
        state.pending_proposals_count = (state.pending_proposals_count || 0) + 1
      }

      this._updateStatusDisplay()
      toast("草稿已保存" + (result.proposal_created ? "，AI 已提取地缘变动" : ""), "success")
    } catch (err) {
      toast(err.message || "保存并分析失败", "error")
    } finally {
      if (btn) btn.disabled = false
    }
  },

  _exportDraft() {
    const editor = document.getElementById("writing-editor")
    const content = editor ? editor.value.trim() : ""
    if (!content) {
      toast("当前章节没有草稿内容", "warning")
      return
    }
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `第${this._currentChapter}章.md`
    a.click()
    URL.revokeObjectURL(a.href)
    toast("草稿已导出", "success")
  },

  async _updateDraftStatus(newStatus) {
    if (!this._currentDraftId) {
      toast("请先保存草稿", "warning")
      return
    }
    try {
      await api.writing.updateDraftStatus(this._currentDraftId, newStatus, state.currentProjectId)
      this._currentDraftStatus = newStatus
      this._updateStatusDisplay()
      toast(`状态已更新为：${newStatus}`, "success")
    } catch (err) {
      toast(err.message || "状态更新失败", "error")
    }
  },

  // ============================================================
  // 版本历史
  // ============================================================

  async _showVersionHistory() {
    if (!this._currentChapter || !state.currentProjectId) return

    let versions = []
    try {
      const data = await api.writing.getVersionHistory(this._currentChapter, state.currentProjectId)
      versions = data.versions || []
    } catch {
      toast("无法加载版本历史", "error")
      return
    }

    if (versions.length === 0) {
      toast("该章节暂无历史版本", "info")
      return
    }

    const statusLabels = { draft: "草稿", candidate: "候选", canonical: "正史", deprecated: "废弃" }

    let tableHtml = `
      <table class="data-table" style="width:100%;">
        <thead><tr><th>版本</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
        <tbody>
    `

    for (const v of versions) {
      const label = statusLabels[v.status] || v.status
      tableHtml += `
        <tr>
          <td><strong>v${v.version_number}</strong></td>
          <td><span class="badge" style="font-size:10px;">${label}</span></td>
          <td style="font-size:11px;color:var(--text-dim);">${v.updated_at ? new Date(v.updated_at).toLocaleString("zh-CN") : "-"}</td>
          <td><button class="btn btn-sm" data-action="restore-version" data-id="${esc(v.id)}">恢复到此处</button></td>
        </tr>
      `
    }

    tableHtml += '</tbody></table>'

    showModal(`版本历史 — 第 ${this._currentChapter} 章（共 ${versions.length} 个版本）`, tableHtml)
  },

  _restoreVersion(versionId) {
    // 简化：通过 API 获取版本内容，填入编辑器
    closeModal()
    toast("版本恢复功能开发中", "info")
  },

  // ============================================================
  // ============================================================
  // 统一提取
  // ============================================================

  async _submitWritingExtraction(stepKey, taskType) {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const start = parseInt(document.getElementById("writing-ext-start")?.value || "1", 10)
    const end = parseInt(document.getElementById("writing-ext-end")?.value || "10", 10)
    if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }

    // 章节卡提取走确认弹窗
    if (stepKey === "cards") {
      this._submitChapterCardExtraction()
      return
    }

    try {
      const result = await api.tasks.submit(taskType, {
        novel_id: state.currentProjectId, start_chapter: start, end_chapter: end,
      })
      this._extractionTasks[stepKey] = { taskId: result.task_id, status: "running", message: "" }
      this._extractionMessage = `${stepKey === "world" ? "世界对象" : "剧情结构"}抽取任务已提交`
      toast("任务已提交", "info")

      // 启动共享轮询
      if (!this._extractionTimer) {
        this._extractionTimer = setInterval(() => this._pollWritingExtraction(), 3000)
      }
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  async _pollWritingExtraction() {
    const running = Object.entries(this._extractionTasks).filter(([, v]) => v.status === "running")
    if (running.length === 0) {
      clearInterval(this._extractionTimer)
      this._extractionTimer = null
      return
    }

    for (const [key, task] of running) {
      try {
        const data = await api.tasks.getStatus(task.taskId)
        if (data.status === "done") {
          this._extractionTasks[key] = { ...task, status: "done", message: "完成" }
          this._extractionMessage = `步骤完成：${key === "world" ? "世界对象抽取" : "剧情结构生成"}`
          toast(this._extractionMessage, "success")
        } else if (data.status === "failed") {
          this._extractionTasks[key] = { ...task, status: "failed", message: data.error_message || "失败" }
          toast(`步骤失败：${data.error_message || "未知错误"}`, "error")
        } else if (data.status === "cancelled") {
          this._extractionTasks[key] = { ...task, status: "idle", message: "" }
        }
      } catch { /* 静默重试 */ }
    }
  },

  // ============================================================
  // 章节卡提取
  // ============================================================

  async _submitChapterCardExtraction() {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }

    const chStart = parseInt(document.getElementById("writing-ext-start")?.value || "1", 10)
    const chEnd = parseInt(document.getElementById("writing-ext-end")?.value || "10", 10)
    if (chEnd < chStart) { toast("结束章节必须 ≥ 起始章节", "warning"); return }

    // 查已有章节卡
    let existingCards = []
    try {
      const data = await api.outline.listChapterCards({
        novel_id: state.currentProjectId,
        limit: 50,
      })
      existingCards = data.items || []
    } catch {
      toast("无法加载章节卡信息", "error")
      return
    }

    // 构建跳过信息
    const skipped = existingCards.filter((c) => c.chapter_index >= chStart && c.chapter_index <= chEnd)
    const extractList = []
    for (let i = chStart; i <= chEnd; i++) {
      if (!skipped.find((c) => c.chapter_index === i)) {
        extractList.push(i)
      }
    }

    if (extractList.length === 0) {
      toast("所选范围内所有章节已有章节卡，无需提取", "info")
      return
    }

    // showModal 确认
    let modalHtml = `
      <div style="font-size:13px;">
        <p style="margin-bottom:8px;">将提取以下 <strong>${extractList.length}</strong> 章：</p>
        <div style="max-height:200px;overflow-y:auto;background:var(--panel);padding:8px;border-radius:4px;margin-bottom:8px;">
    `
    for (const idx of extractList) {
      modalHtml += `<div style="font-size:12px;padding:2px 0;">✅ 第 ${idx} 章</div>`
    }

    if (skipped.length > 0) {
      modalHtml += `
        <p style="margin-top:8px;color:var(--text-dim);">已跳过 <strong>${skipped.length}</strong> 章（已有章节卡）：</p>
      `
      for (const c of skipped) {
        modalHtml += `<div style="font-size:11px;color:var(--text-dim);padding:2px 0;">⏭ 第 ${c.chapter_index} 章 — ${esc(c.title || "")}</div>`
      }
    }

    modalHtml += `</div>
      <p style="color:var(--text-dim);font-size:11px;">提取结果将保存为「候选」状态，请在章节卡视图中审核确认。</p>
    `

    const start = chStart
    const end = chEnd

    showModal("确认提取章节卡", modalHtml, [
      {
        text: "取消",
        class: "",
        handler: () => closeModal(),
      },
      {
        text: "确认提取",
        class: "btn-primary",
        handler: async () => {
          closeModal()
          try {
            await api.tasks.submit("chapter_card_extraction", {
              novel_id: state.currentProjectId,
              start_chapter: start,
              end_chapter: end,
            })
            toast("章节卡提取任务已提交，请稍后刷新查看", "success")
          } catch (err) {
            toast(err.message || "提交失败", "error")
          }
        },
      },
    ])
  },

  // 深度导入流水线（保持不变）
  // ============================================================

  async _submitDeepImport() {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const chStart = parseInt(document.getElementById("deep-import-start")?.value || "1", 10)
    const chEnd = parseInt(document.getElementById("deep-import-end")?.value || "10", 10)
    if (chEnd < chStart) { toast("结束章节必须 ≥ 起始章节", "warning"); return }

    try {
      const result = await api.imports.deepImport(state.currentProjectId, chStart, chEnd)
      this._deepImportTaskId = result.task_id
      this._deepImportPhase = "pending"
      this._deepImportCompleted = []
      this._deepImportProgress = 10

      localStorage.setItem("novel_deep_import_task", JSON.stringify({
        taskId: result.task_id,
        projectId: state.currentProjectId,
        startChapter: chStart,
        endChapter: chEnd,
      }))

      this._updateDeepImportUI()
      toast("深度导入任务已提交", "success")
      this._pollDeepImportTask()
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  async _resumeDeepImport() {
    if (!this._deepImportTaskId) return
    try {
      const result = await api.imports.resumeDeepImport(this._deepImportTaskId)
      this._deepImportTaskId = result.task_id
      const saved = localStorage.getItem("novel_deep_import_task")
      if (saved) {
        const parsed = JSON.parse(saved)
        parsed.taskId = result.task_id
        localStorage.setItem("novel_deep_import_task", JSON.stringify(parsed))
      }
      this._deepImportPhase = "running"
      this._updateDeepImportUI()
      toast("继续深度导入任务已提交", "success")
      this._pollDeepImportTask()
    } catch (err) {
      toast(err.message || "继续失败", "error")
    }
  },

  async _pollDeepImportTask() {
    if (!this._deepImportTaskId) return
    if (this._deepImportTimer) clearInterval(this._deepImportTimer)

    const poll = async () => {
      if (!this._deepImportTaskId) return
      try {
        const task = await api.tasks.get(this._deepImportTaskId)
        this._updateFromTask(task)
      } catch {
        if (this._deepImportTimer) {
          clearInterval(this._deepImportTimer)
          this._deepImportTimer = null
        }
      }
    }

    await poll()
    this._deepImportTimer = setInterval(poll, 3000)
  },

  _updateFromTask(task) {
    const result = task.result || {}
    this._deepImportPhase = result.phase || task.status
    this._deepImportCompleted = result.completed_steps || []
    this._deepImportMessage = result.message || ""

    const completed = this._deepImportCompleted.length
    this._deepImportProgress = Math.round((completed / 3) * 100)

    if (task.status === "done" && this._deepImportPhase === "awaiting_review") {
      this._deepImportProgress = 33
    } else if (task.status === "done" && this._deepImportPhase === "done") {
      this._deepImportProgress = 100
      if (this._deepImportTimer) { clearInterval(this._deepImportTimer); this._deepImportTimer = null }
      localStorage.removeItem("novel_deep_import_task")
      toast("深度导入全部完成！", "success")
    } else if (task.status === "failed") {
      this._deepImportPhase = "failed"
      this._deepImportMessage = task.error_message || "任务失败"
      if (this._deepImportTimer) { clearInterval(this._deepImportTimer); this._deepImportTimer = null }
      toast(`深度导入失败: ${this._deepImportMessage}`, "error")
    }

    this._updateDeepImportUI()
  },

  _updateDeepImportUI() {
    const panel = document.getElementById("deep-import-panel")
    if (!panel) return
    const progressDiv = document.getElementById("deep-import-progress")
    const bar = document.getElementById("deep-import-bar")
    const statusEl = document.getElementById("deep-import-status")
    const actionsDiv = document.getElementById("deep-import-actions")
    const gotoBtn = document.getElementById("btn-deep-goto-review")
    const resumeBtn = document.getElementById("btn-deep-resume")
    const startBtn = document.getElementById("btn-deep-import-start")

    if (!progressDiv || !bar || !statusEl) return

    if (startBtn) {
      startBtn.style.display = (this._deepImportPhase === "idle" || this._deepImportPhase === "done" || this._deepImportPhase === "failed") ? "inline-block" : "none"
    }
    progressDiv.style.display = "block"
    bar.style.width = this._deepImportProgress + "%"
    statusEl.textContent = this._deepImportMessage || this._deepImportPhase

    ;["extract_world", "sync_characters", "generate_plot"].forEach((step) => this._updateStepUI(step))

    if (actionsDiv) {
      if (this._deepImportPhase === "awaiting_review") {
        actionsDiv.style.display = "block"
        if (gotoBtn) gotoBtn.style.display = "inline-block"
        if (resumeBtn) resumeBtn.style.display = "inline-block"
      } else if (this._deepImportPhase === "done") {
        actionsDiv.style.display = "none"
      } else if (this._deepImportPhase === "failed") {
        actionsDiv.style.display = "block"
        if (gotoBtn) gotoBtn.style.display = "none"
        if (resumeBtn) resumeBtn.style.display = "none"
      } else {
        actionsDiv.style.display = "none"
      }
    }
  },

  _updateStepUI(stepName) {
    const stepEl = document.getElementById("step-" + stepName)
    if (!stepEl) return
    const icon = stepEl.querySelector(".step-icon")
    if (!icon) return
    if (this._deepImportCompleted.includes(stepName)) {
      icon.textContent = "✅"
      stepEl.style.color = stepName === "extract_world" && this._deepImportPhase === "awaiting_review" ? "var(--accent)" : "var(--text-dim)"
    } else if (this._deepImportPhase === "running") {
      icon.textContent = "⏳"
      stepEl.style.color = "var(--accent)"
    } else {
      icon.textContent = "☐"
      stepEl.style.color = "var(--text-dim)"
    }
  },

  _gotoReview() {
    router.navigate("world", "candidates")
    toast("请在「候选清洗」中审查并确认候选对象", "info")
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindEvents() {
    const content = document.getElementById("workspace-content")
    if (!content) return
    content.removeEventListener("click", this._clickHandler)
    this._clickHandler = (e) => {
      const t = e.target.closest("[data-action]")
      if (!t) return
      const a = t.getAttribute("data-action")
      const id = t.getAttribute("data-id")
      switch (a) {
        case "save-draft": this.saveDraft(); break
        case "save-analyze-geo": this._saveAndAnalyze(); break
        case "prev-chapter": this._prevChapter(); break
        case "next-chapter": this._nextChapter(); break
        case "export-draft": this._exportDraft(); break
        case "update-status": this._updateDraftStatus(t.getAttribute("data-status")); break
        case "show-version-history": this._showVersionHistory(); break
        case "select-chapter": this._selectChapter(parseInt(t.getAttribute("data-chapter"), 10)); break
        case "nav-chapters": router.navigate("outline", "chapters"); break
        case "submit-deep-import": this._submitDeepImport(); break
        case "goto-review": this._gotoReview(); break
        case "resume-deep-import": this._resumeDeepImport(); break
        case "submit-writing-extraction": this._submitWritingExtraction(t.getAttribute("data-key"), t.getAttribute("data-task-type")); break
        case "restore-version": if (id) this._restoreVersion(id); break
      }
    }
    content.addEventListener("click", this._clickHandler)
  },
}

// 注册视图
router.registerView("writing", writingView)


export default writingView
