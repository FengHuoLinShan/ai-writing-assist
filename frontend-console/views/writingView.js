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
    this._currentChapter = null
    this._currentContent = null
    this._currentDraftId = null
    this._currentDraftStatus = null
    this._currentDraftVersion = null
    this._currentCard = null
    this._loading = true
    this._chapters = {}
    this._chapterList = []
    this._deepImportTimer = null

    if (!_state.currentProjectId) {
      this._loading = false
      return
    }

    // 并行获取章节卡 + 有草稿的章节索引
    try {
      const [cardData, draftData] = await Promise.all([
        api.outline.listChapterCards({ novel_id: _state.currentProjectId, limit: 999 }),
        api.writing.listChapters(_state.currentProjectId),
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

    // 从 localStorage 恢复深度导入任务
    const saved = localStorage.getItem("novel_deep_import_task")
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        if (parsed.taskId && parsed.projectId === _state.currentProjectId) {
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
            <button class="btn btn-primary" onclick="router.navigate('outline','chapters')">前往章节卡</button>
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
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  onLeave() {
    if (this._deepImportTimer) {
      clearInterval(this._deepImportTimer)
      this._deepImportTimer = null
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
             onclick="writingView._selectChapter(${idx})">
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
        " placeholder="${hasSelection ? '在此书写正文...' : '请从左侧选择章节'}" ${hasSelection ? '' : 'disabled'}></textarea>

        <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
          <button class="btn btn-primary" id="btn-save-draft" onclick="writingView.saveDraft()" ${hasSelection ? '' : 'disabled'}>保存草稿</button>
          <button class="btn" id="btn-prev-chapter" onclick="writingView._prevChapter()" ${this._hasPrev() ? '' : 'disabled'}>上一章</button>
          <button class="btn" id="btn-next-chapter" onclick="writingView._nextChapter()" ${this._hasNext() ? '' : 'disabled'}>下一章</button>
          <button class="btn" onclick="writingView._exportDraft()" ${hasSelection ? '' : 'disabled'}>导出本章</button>
          <span style="flex:1;"></span>
          ${statusActions.map((a) =>
            `<button class="btn btn-sm" onclick="writingView._updateDraftStatus('${a.status}')" style="font-size:11px;">${a.label}</button>`
          ).join("")}
          ${this._currentChapter !== null
            ? `<button class="btn btn-sm" onclick="writingView._showVersionHistory()" style="font-size:11px;">查看版本历史</button>`
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
      html += this._cardCollapsible("尾钩", card.ending_hook)
    } else {
      html += `
        <div style="font-size:12px;color:var(--text-dim);text-align:center;padding:20px 0;">
          ${this._currentChapter !== null
            ? '暂无章节卡。<br>可在「剧情结构 → 章节卡」中创建。'
            : '请从左侧选择章节'}
        </div>
      `
    }

    html += '</div>'

    // ── 深度导入流水线 ──
    html += `
      <hr style="border-color:var(--border);margin:8px 0;">
      <div style="font-size:11px;">
        <details>
          <summary style="cursor:pointer;font-weight:bold;color:var(--text-dim);">📥 深度导入</summary>
          <div id="deep-import-panel" style="margin-top:6px;">
            <div style="display:flex;gap:4px;align-items:center;">
              <input type="number" id="deep-import-start" min="1" value="1" style="width:40px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:11px;" />
              <span style="color:var(--text-dim);font-size:11px;">~</span>
              <input type="number" id="deep-import-end" min="1" value="10" style="width:40px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:11px;" />
              <button class="btn btn-sm btn-primary" onclick="writingView._submitDeepImport()" id="btn-deep-import-start">开始</button>
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
                <button class="btn btn-sm" onclick="writingView._gotoReview()" id="btn-deep-goto-review">前往审查</button>
                <button class="btn btn-sm btn-primary" onclick="writingView._resumeDeepImport()" id="btn-deep-resume" style="display:none;">继续深度导入</button>
              </div>
            </div>
          </div>
        </details>
      </div>
    `

    // ── 章节卡提取 ──
    html += `
      <hr style="border-color:var(--border);margin:6px 0;">
      <div style="font-size:11px;">
        <details>
          <summary style="cursor:pointer;font-weight:bold;color:var(--text-dim);">📇 从正文提取章节卡</summary>
          <div style="margin-top:6px;">
            <div style="display:flex;gap:4px;align-items:center;">
              <input type="number" id="card-extract-start" min="1" value="1" style="width:40px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:11px;" />
              <span style="color:var(--text-dim);font-size:11px;">~</span>
              <input type="number" id="card-extract-end" min="1" value="10" style="width:40px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 4px;border-radius:3px;font-size:11px;" />
              <button class="btn btn-sm btn-primary" onclick="writingView._submitChapterCardExtraction()">提取</button>
            </div>
            <p style="color:var(--text-dim);font-size:10px;margin-top:4px;">
              逐章调用 LLM 从正文提取章节卡字段。已有关键卡的章节跳过。
            </p>
          </div>
        </details>
      </div>
    `

    html += '</div>'
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
    this._currentChapter = chapterIndex
    this._currentContent = null
    this._currentDraftId = null
    this._currentDraftStatus = null
    this._currentDraftVersion = null
    this._currentDraftUpdatedAt = null
    this._currentCard = null

    // 重新渲染（简化：全量）
    const content = document.getElementById("workspace-content")
    if (content) {
      const html = await this.render()
      content.innerHTML = html
    }

    // 加载草稿
    this._loadDraft(chapterIndex)

    // 加载章节卡
    this._loadChapterCard(chapterIndex)
  },

  async _loadDraft(chapterIndex) {
    if (!_state.currentProjectId) return
    try {
      const data = await api.writing.getDraft(chapterIndex, _state.currentProjectId)
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
    if (!_state.currentProjectId) return
    try {
      const card = await api.outline.getChapterCardByIndex(chapterIndex, _state.currentProjectId)
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
        novel_id: _state.currentProjectId,
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

      // 更新章节树标记
      if (!this._chapters[this._currentChapter]) {
        this._chapters[this._currentChapter] = { hasCard: false, hasDraft: true, cardTitle: null, cardStatus: null }
      }
      this._chapters[this._currentChapter].hasDraft = true
      if (!this._chapterList.includes(this._currentChapter)) {
        this._chapterList.push(this._currentChapter)
        this._chapterList.sort((a, b) => a - b)
      }

      this._updateStatusDisplay()
      toast("草稿已保存", "success")
    } catch (err) {
      toast(err.message || "保存失败", "error")
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
      await api.writing.updateDraftStatus(this._currentDraftId, newStatus, _state.currentProjectId)
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
    if (!this._currentChapter || !_state.currentProjectId) return

    let versions = []
    try {
      const data = await api.writing.getVersionHistory(this._currentChapter, _state.currentProjectId)
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
          <td><button class="btn btn-sm" onclick="writingView._restoreVersion('${esc(v.id)}')">恢复到此处</button></td>
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
  // 章节卡提取
  // ============================================================

  async _submitChapterCardExtraction() {
    if (!_state.currentProjectId) { toast("请先选择项目", "warning"); return }

    const chStart = parseInt(document.getElementById("card-extract-start")?.value || "1", 10)
    const chEnd = parseInt(document.getElementById("card-extract-end")?.value || "10", 10)
    if (chEnd < chStart) { toast("结束章节必须 ≥ 起始章节", "warning"); return }

    // 查已有章节卡
    let existingCards = []
    try {
      const data = await api.outline.listChapterCards({
        novel_id: _state.currentProjectId,
        limit: 999,
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
              novel_id: _state.currentProjectId,
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
    if (!_state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const chStart = parseInt(document.getElementById("deep-import-start")?.value || "1", 10)
    const chEnd = parseInt(document.getElementById("deep-import-end")?.value || "10", 10)
    if (chEnd < chStart) { toast("结束章节必须 ≥ 起始章节", "warning"); return }

    try {
      const result = await api.imports.deepImport(_state.currentProjectId, chStart, chEnd)
      this._deepImportTaskId = result.task_id
      this._deepImportPhase = "pending"
      this._deepImportCompleted = []
      this._deepImportProgress = 10

      localStorage.setItem("novel_deep_import_task", JSON.stringify({
        taskId: result.task_id,
        projectId: _state.currentProjectId,
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
    router.navigate("world", "objects")
    toast("请在「对象库」中审查并确认候选对象", "info")
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindEvents() {
    // Ctrl+S 保存由 app.js 全局处理
  },
}

// 注册视图
router.registerView("writing", writingView)
