/**
 * 草稿导出视图
 *
 * 承载手写正文草稿，关联章节卡，版本管理，导出创作包。
 */
const writingView = {
  /** @type {Array} 草稿列表 */
  _drafts: [],

  /** @type {number|null} 当前选中的章节 */
  _currentChapter: null,

  /** @type {string|null} 当前草稿内容 */
  _currentContent: null,

  async onEnter() {
    this._drafts = []
    this._currentChapter = null
    this._currentContent = null
  },

  async render() {
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        承载手写正文草稿，管理版本，导出结构化创作包。
        选择一个章节开始编辑，或直接在下方书写。
      </p>

      <div style="display:grid;grid-template-columns:280px 1fr 200px;gap:12px;">
        <!-- 左侧：章节导航 -->
        <div class="card" style="max-height:500px;overflow-y:auto;">
          <div class="card-title" style="display:flex;justify-content:space-between;align-items:center;">
            <span>章节</span>
            <input type="number" id="writing-chapter-input" min="1" placeholder="跳转" style="width:60px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;font-size:12px;" />
          </div>
          <div style="margin-top:8px;">
            <div class="clickable" style="padding:6px 8px;border-left:2px solid transparent;margin-bottom:2px;" onclick="writingView._selectChapter(1)">
              <strong>第 1 章</strong>  <span style="color:var(--text-dim);font-size:11px;">开端</span>
            </div>
            <div class="clickable" style="padding:6px 8px;border-left:2px solid transparent;margin-bottom:2px;" onclick="writingView._selectChapter(25)">
              <strong>第 25 章</strong>  <span style="color:var(--text-dim);font-size:11px;">旧档案篇</span>
            </div>
            <div class="clickable" style="padding:6px 8px;border-left:2px solid transparent;margin-bottom:2px;" onclick="writingView._selectChapter(27)">
              <strong>第 27 章</strong>  <span style="color:var(--text-dim);font-size:11px;">缺页档案</span>
            </div>
          </div>
          <div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);">
            <button class="btn btn-sm" onclick="writingView._selectChapter(parseInt(document.getElementById('writing-chapter-input')?.value || 1, 10))">跳转</button>
          </div>
        </div>

        <!-- 中间：编辑器 -->
        <div>
          <div style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
            <span id="writing-chapter-title" style="color:var(--text);font-size:14px;font-weight:bold;">选择章节开始编辑</span>
            <span id="writing-draft-status" style="color:var(--text-dim);font-size:11px;"></span>
          </div>
          <textarea id="writing-editor" style="
            width:100%;height:400px;background:var(--bg);color:var(--text);
            border:1px solid var(--border);border-radius:4px;padding:12px;
            font-family:var(--font-mono);font-size:13px;line-height:1.8;
            resize:vertical;
          " placeholder="在此书写正文..." disabled></textarea>
          <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
            <button class="btn btn-primary" id="btn-save-draft" onclick="writingView.saveDraft()" disabled>保存草稿</button>
            <button class="btn" id="btn-load-card" onclick="writingView._loadChapterCard()" disabled>关联章节卡</button>
            <button class="btn" onclick="writingView._extractMemory()" disabled>抽取状态更新</button>
            <span style="flex:1;"></span>
            <button class="btn" onclick="writingView._exportDraft()" disabled>导出本章</button>
          </div>
        </div>

        <!-- 右侧：导出工具 -->
        <div class="card">
          <div class="card-title">导出创作包</div>
          <div style="margin-top:8px;display:flex;flex-direction:column;gap:6px;">
            <button class="btn btn-sm" onclick="writingView._export('world')">导出世界设定</button>
            <button class="btn btn-sm" onclick="writingView._export('characters')">导出人物档案</button>
            <button class="btn btn-sm" onclick="writingView._export('arcs')">导出篇章纲</button>
            <button class="btn btn-sm" onclick="writingView._export('chapters')">导出章节卡</button>
            <button class="btn btn-sm" onclick="writingView._export('context')">导出上下文包</button>
            <hr style="border-color:var(--border);margin:6px 0;">
            <button class="btn btn-sm btn-warning" onclick="writingView._export('full')">导出完整创作包</button>
          </div>
          <div style="margin-top:12px;padding-top:8px;border-top:1px solid var(--border);">
            <p style="color:var(--text-dim);font-size:11px;">
              <strong>导出格式</strong><br>
              所有导出为 Markdown 文件。<br>
              完整创作包包含全部结构化资产。
            </p>
          </div>
        </div>
      </div>
    `
    return html
  },

  _selectChapter(chapterIndex) {
    this._currentChapter = chapterIndex
    const titleEl = document.getElementById("writing-chapter-title")
    const editor = document.getElementById("writing-editor")
    const saveBtn = document.getElementById("btn-save-draft")
    const cardBtn = document.getElementById("btn-load-card")
    const statusEl = document.getElementById("writing-draft-status")

    if (titleEl) titleEl.textContent = `第 ${chapterIndex} 章`
    if (editor) {
      editor.disabled = false
      editor.value = this._currentContent || ""
      editor.focus()
    }
    if (saveBtn) saveBtn.disabled = false
    if (cardBtn) cardBtn.disabled = false
    if (statusEl) {
      statusEl.textContent = this._currentContent ? "已修改" : "新草稿"
    }

    // 尝试从后端加载已有草稿
    this._loadDraft(chapterIndex)

    // 更新右侧信息栏
    _state.rightPanel = {
      title: `第 ${chapterIndex} 章`,
      type: "writing",
      content: `
        <div class="help-section">
          <h4>第 ${chapterIndex} 章</h4>
          <p style="color:var(--text-dim);font-size:12px;">
            在此书写正文草稿。草稿按版本管理，每次保存自动递增版本号。
          </p>
          <hr style="border-color:var(--border);margin:8px 0;">
          <p style="font-size:12px;">
            <strong>操作说明</strong><br>
            <kbd>Ctrl+S</kbd> 保存草稿<br>
            <kbd>Ctrl+Enter</kbd> 保存并关闭
          </p>
        </div>
      `,
    }
  },

  async _loadDraft(chapterIndex) {
    if (!_state.currentProjectId) return
    try {
      const data = await api.writing.getDraft(chapterIndex, _state.currentProjectId)
      if (data && (data.content || data.summary)) {
        const editor = document.getElementById("writing-editor")
        if (editor) {
          this._currentContent = data.content || data.summary || ""
          editor.value = this._currentContent
        }
        const statusEl = document.getElementById("writing-draft-status")
        if (statusEl) {
          statusEl.textContent = `v${data.version_number || 1} · ${data.updated_at ? new Date(data.updated_at).toLocaleString("zh-CN") : ""}`
        }
      }
    } catch {
      // 没有草稿也不报错
    }
  },

  async saveDraft() {
    const editor = document.getElementById("writing-editor")
    if (!editor || !this._currentChapter) {
      toast("请先选择章节", "warning")
      return
    }

    const content = editor.value
    if (!content.trim()) {
      toast("草稿内容为空", "warning")
      return
    }

    try {
      await api.writing.saveDraft({
        novel_id: _state.currentProjectId,
        chapter_index: this._currentChapter,
        content,
        title: `第 ${this._currentChapter} 章`,
      })
      this._currentContent = content
      toast(`第 ${this._currentChapter} 章草稿已保存`, "success")
      const statusEl = document.getElementById("writing-draft-status")
      if (statusEl) statusEl.textContent = "已保存 · " + new Date().toLocaleString("zh-CN")
    } catch (err) {
      toast(`保存失败：${err.message}`, "error")
    }
  },

  _loadChapterCard() {
    if (!this._currentChapter) return
    toast(`正在加载第 ${this._currentChapter} 章的章节卡...`, "info")
    // 可以跳转到 outline 视图查看
    router.navigate("outline", "chapters")
  },

  _extractMemory() {
    if (!this._currentChapter) return
    toast("状态抽取功能开发中", "info")
  },

  _exportDraft() {
    const editor = document.getElementById("writing-editor")
    if (!editor || !editor.value.trim() || !this._currentChapter) {
      toast("没有可导出的内容", "warning")
      return
    }

    const content = `# 第 ${this._currentChapter} 章\n\n${editor.value}`
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `chapter-${String(this._currentChapter).padStart(3, "0")}.md`
    a.click()
    URL.revokeObjectURL(url)
    toast(`第 ${this._currentChapter} 章已导出`, "success")
  },

  _export(type) {
    const typeNames = {
      world: "世界设定",
      characters: "人物档案",
      arcs: "篇章纲",
      chapters: "章节卡",
      context: "上下文包",
      full: "完整创作包",
    }

    const content = `# ${typeNames[type] || type}\n\n从小说项目"${_state.currentProject?.title || "未命名"}"导出\n导出时间：${new Date().toLocaleString("zh-CN")}\n\n---\n\n此功能需要后端支持。`
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `export-${type}-${Date.now()}.md`
    a.click()
    URL.revokeObjectURL(url)
    toast(`${typeNames[type] || type} 已导出`, "success")
  },
}

router.registerView("writing", writingView)
window.writingView = writingView
