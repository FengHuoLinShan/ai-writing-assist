/**
 * 左侧章节树模块
 *
 * 负责：
 * 1. 加载章节列表与 Scene 列表
 * 2. 渲染普通章节树或按 Scene 分组的树
 * 3. 维护当前选中章节与批量选择状态
 * 4. 绑定树内点击事件并通过回调通知 orchestrator
 */
import {
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  renderBulkToolbar,
  runBulkAction,
  selectedItemsFrom,
  syncBulkSelectionUi,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../../shared/bulkSelection.js"
import { bindDelegation } from "../../shared/viewHelper.js"
import { confirmAsync } from "../../shared/confirmAsync.js"

export function createChapterTree({
  state,
  api,
  onSelect,
  onSceneSelect,
  onBulkChange,
  esc,
}) {
  const tree = {
    _state: state,
    _api: api,
    _onSelect: onSelect,
    _onSceneSelect: onSceneSelect,
    _onBulkChange: onBulkChange,
    _esc: esc,

    _chapterList: [],
    _chapters: {},
    _scenes: [],
    _chapterListLoadError: null,
    _currentChapter: null,
    _activeSceneId: null,
    _showBulkActions: false,
    _bulkSelections: {},

    async load() {
      this._chapterListLoadError = null
      if (!this._state.currentProjectId) {
        this._chapterList = []
        this._chapters = {}
        this._scenes = []
        return
      }

      try {
        const draftData = await this._api.writing.listChapters(this._state.currentProjectId)
        const chapterSummaries = Array.isArray(draftData.chapters) ? draftData.chapters : []
        const draftIndices = chapterSummaries.length > 0
          ? chapterSummaries.map((item) => item.chapter_index)
          : (draftData.chapter_indices || [])

        const chapters = {}
        for (const item of chapterSummaries) {
          const idx = item.chapter_index
          chapters[idx] = {
            title: item.title || "",
            draftCount: item.version_number || 0,
            wordcount: item.word_count || 0,
            word_count: item.word_count || 0,
            status: item.status || "draft",
            updated_at: item.updated_at || null,
          }
        }
        for (const idx of draftIndices) {
          if (!chapters[idx]) chapters[idx] = { draftCount: 0 }
        }

        this._chapters = chapters
        this._chapterList = [...draftIndices].sort((a, b) => a - b)

        try {
          this._scenes = await this._api.outline.listScenesOrdered(this._state.currentProjectId) || []
        } catch {
          this._scenes = []
        }
      } catch (err) {
        this._chapterList = []
        this._chapters = {}
        this._chapterListLoadError = err?.message || "加载失败"
      }
    },

    render() {
      if (this._chapterListLoadError) {
        return this._renderError()
      }
      if (this._chapterList.length === 0) {
        return this._renderEmpty()
      }
      return this._renderSceneTree()
    },

    bindEvents(container) {
      if (!container) return
      bindDelegation(this, container, "click", {
        "select-chapter": (_e, t) => this._selectChapter(parseInt(t.getAttribute("data-chapter"), 10)),
        "select-scene": (_e, t) => this._selectScene(t.getAttribute("data-scene-id")),
        "prev-chapter": () => this._switchChapter(-1),
        "next-chapter": () => this._switchChapter(1),
        "new-chapter": () => this.newChapter(),
        "delete-chapter": (_e, t) => this._deleteChapter(parseInt(t.getAttribute("data-chapter"), 10)),
        "toggle-bulk-actions": () => {
          this._showBulkActions = !this._showBulkActions
          this._notifyBulkChange()
        },
        "select-visible-chapters": () => {
          toggleAllBulkSelection(this, "writing-chapters", this._chapterList.map(String), true)
          this._syncBulkUi()
        },
        "bulk-toggle-one": (e, t) => {
          e.stopPropagation()
          toggleBulkSelection(this, t.getAttribute("data-scope"), t.getAttribute("data-id"), t.checked)
          this._syncBulkUi()
        },
        "bulk-clear": (_e, t) => {
          const scope = t.getAttribute("data-scope")
          clearBulkSelection(this, scope)
          this._syncBulkUi()
        },
        "bulk-run": (_e, t) => this._runBulkAction(t.getAttribute("data-bulk-action")),
        "toggle-scene-group": (_e, t) => this._toggleSceneGroup(t),
      })
    },

    getSelectedIds() {
      return Array.from(getBulkSelection(this, "writing-chapters")).map((id) => parseInt(id, 10))
    },

    clearSelection() {
      clearBulkSelection(this, "writing-chapters")
      this._showBulkActions = false
      this._notifyBulkChange()
    },

    getChapterList() {
      return this._chapterList
    },

    getLoadError() {
      return this._chapterListLoadError
    },

    getChapterMap() {
      return this._chapters
    },

    getScenes() {
      return this._scenes
    },

    setCurrentChapter(index) {
      this._currentChapter = index
    },

    setCurrentSceneId(sceneId) {
      this._activeSceneId = sceneId
    },

    setChapters(map) {
      this._chapters = map || {}
    },

    setScenes(scenes) {
      this._scenes = scenes || []
    },

    setChapterList(list) {
      this._chapterList = Array.isArray(list) ? [...list] : []
    },

    setBulkSelections(selections) {
      this._bulkSelections = selections || {}
    },

    setShowBulkActions(show) {
      this._showBulkActions = Boolean(show)
    },

    async newChapter() {
      const defaultIndex = this._chapterList.length > 0 ? Math.max(...this._chapterList) + 1 : 1
      const idx = defaultIndex
      if (!this._state.currentProjectId) return

      if (this._chapters[idx]) {
        this._selectChapter(idx)
        return
      }

      const defaultTitle = `第 ${idx} 章`
      let created = null
      try {
        created = await this._api.writing.autosaveDraftOnly({
          novel_id: this._state.currentProjectId,
          chapter_index: idx,
          title: defaultTitle,
          content: "",
        })
      } catch {
        return
      }

      this._chapters[idx] = {
        title: created.title || defaultTitle,
        draftCount: 1,
        wordcount: 0,
        word_count: 0,
        status: created.status || "draft",
        updated_at: created.updated_at || null,
      }
      this._chapterList.push(idx)
      this._chapterList.sort((a, b) => a - b)
      this._selectChapter(idx)
    },

    async deleteChapter(chapterIndex) {
      if (!this._state.currentProjectId) return false
      const confirmed = await confirmAsync(
        `确定删除第 ${chapterIndex} 章的全部版本？此操作不可恢复。`,
        "确认删除",
      )
      if (!confirmed) return false

      try {
        await this._api.writing.deleteChapter(chapterIndex, this._state.currentProjectId)
        delete this._chapters[chapterIndex]
        this._chapterList = this._chapterList.filter((i) => i !== chapterIndex)
        clearBulkSelection(this, "writing-chapters")

        const wasCurrent = this._currentChapter === chapterIndex
        if (wasCurrent) {
          this._currentChapter = null
          this._notifyBulkChange()
          if (this._onSelect) this._onSelect(null)
        } else {
          this._notifyBulkChange()
        }
        return true
      } catch {
        return false
      }
    },

    async runBulkAction(action) {
      return this._runBulkAction(action)
    },

    dispose() {
      this._chapterList = []
      this._chapters = {}
      this._scenes = []
      this._chapterListLoadError = null
      this._currentChapter = null
      this._activeSceneId = null
      this._showBulkActions = false
      this._bulkSelections = {}
    },

    // ============================================================
    // 渲染
    // ============================================================

    _renderError() {
      return `
        <div class="empty-state" role="alert">
          <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
          <p>章节列表加载失败</p>
          <p style="color:var(--text-dim);font-size:12px;">可稍后重试。错误信息：${this._esc(this._chapterListLoadError)}</p>
        </div>
      `
    },

    _renderEmpty() {
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
    },

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
        html += this._renderChapterRow(idx)
      }

      html += "</div></div>"
      return html
    },

    _renderSceneTree() {
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

      if (unassigned.length > 0) {
        const isExpanded = unassigned.includes(this._currentChapter)
        html += `
          <div class="scene-tree-node">
            <div class="scene-tree-scene" data-action="toggle-scene-group" style="cursor:pointer;padding:4px 4px;">
              <span class="toggle-icon">${isExpanded ? "▼" : "▶"}</span>
              <span style="color:var(--text-dim);font-size:12px;">未归类</span>
              <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${unassigned.length}章)</span>
            </div>
            <div class="scene-tree-chapters" style="display:${isExpanded ? "block" : "none"};margin-left:12px;">
        `
        for (const idx of unassigned) {
          html += this._renderChapterRow(idx)
        }
        html += "</div></div>"
      }

      for (const { scene, chapters } of sceneChapterMap) {
        if (chapters.length === 0 && unassigned.length === 0) continue
        const isCurrentScene = scene.id === this._activeSceneId
        const isExpanded = chapters.length > 0 || isCurrentScene || chapters.includes(this._currentChapter)

        html += `
          <div class="scene-tree-node">
            <div class="scene-tree-scene clickable" data-action="select-scene" data-scene-id="${this._esc(scene.id)}"
                 style="padding:4px 4px;border-radius:var(--radius-sm);${isCurrentScene ? "background:var(--hover-bg);" : ""}">
              <span class="toggle-icon">${isExpanded ? "▼" : "▶"}</span>
              <span style="font-size:13px;font-weight:${isCurrentScene ? "bold" : "normal"};">${this._esc(scene.title || "未命名")}</span>
              <span style="color:var(--text-dim);font-size:10px;margin-left:4px;">(${chapters.length}章)</span>
            </div>
            <div class="scene-tree-chapters" style="display:${isExpanded ? "block" : "none"};margin-left:12px;">
        `

        for (const idx of chapters) {
          html += this._renderChapterRow(idx)
        }

        html += "</div></div>"
      }

      html += "</div></div>"
      return html
    },

    _renderChapterRow(idx) {
      const isActive = idx === this._currentChapter
      const title = this._chapters[idx]?.title || ""
      const wordcount = this._chapterWordcount(idx)
      const label = `打开第 ${idx} 章${title ? `：${title}` : ""}，${wordcount} 字`
      return `
        <button type="button" class="chapter-row ${isActive ? "chapter-row--active" : ""}" data-action="select-chapter" data-chapter="${idx}" aria-label="${this._esc(label)}" aria-current="${isActive ? "true" : "false"}">
          <div class="chapter-row__status">
            <span class="chapter-status chapter-status--${this._esc(this._chapterStatus(idx))}" title="${this._esc(this._chapterStatusLabel(idx))}"></span>
          </div>
          <div class="chapter-row__info">
            <div class="chapter-row__title">
              <span class="chapter-number">第 ${idx} 章</span>
              ${title ? `<span class="chapter-title-text">${this._esc(title)}</span>` : ""}
            </div>
            <div class="chapter-row__meta">
              <span class="chapter-wc">${this._esc(wordcount)} 字</span>
            </div>
          </div>
        </button>
      `
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

    // ============================================================
    // 章节状态辅助
    // ============================================================

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
      const count = this._chapters[idx]?.wordcount || this._chapters[idx]?.word_count || 0
      return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
    },

    _currentSceneId() {
      return this._activeSceneId
    },

    // ============================================================
    // 事件处理
    // ============================================================

    _selectChapter(chapterIndex) {
      this._currentChapter = chapterIndex
      if (this._onSelect) this._onSelect(chapterIndex)
    },

    _selectScene(sceneId) {
      const scene = this._scenes.find((s) => s.id === sceneId)
      if (!scene) return

      const chIds = (scene.chapter_ids || []).map((id) => parseInt(id, 10)).filter((n) => !isNaN(n))
      const firstChapter = chIds.length > 0 ? Math.min(...chIds) : null

      if (firstChapter && this._chapters[firstChapter]) {
        this._currentChapter = firstChapter
        if (this._onSelect) this._onSelect(firstChapter)
      }
      if (this._onSceneSelect) this._onSceneSelect(sceneId)
    },

    _switchChapter(delta) {
      if (this._currentChapter == null || this._chapterList.length === 0) return
      const currentIndex = this._chapterList.indexOf(this._currentChapter)
      const nextIndex = currentIndex + delta
      if (nextIndex < 0 || nextIndex >= this._chapterList.length) return
      this._selectChapter(this._chapterList[nextIndex])
    },

    _toggleSceneGroup(t) {
      const chapters = t.parentElement.querySelector(".scene-tree-chapters")
      const icon = t.querySelector(".toggle-icon")
      if (chapters) {
        const isHidden = chapters.style.display === "none"
        chapters.style.display = isHidden ? "block" : "none"
        if (icon) icon.textContent = isHidden ? "▼" : "▶"
      }
    },

    async _runBulkAction(action) {
      if (action !== "delete-chapters") return
      const selected = selectedItemsFrom(
        this._chapterList.map((index) => ({ id: String(index), index })),
        getBulkSelection(this, "writing-chapters"),
      )
      if (!selected.length) return

      const confirmed = await new Promise((resolve) => {
        confirmAction(
          `确定删除选中的 ${selected.length} 个章节及其全部版本？此操作不可恢复。`,
          () => resolve(true),
          "确认删除",
        )
        setTimeout(() => {
          const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
          if (cancelBtn) cancelBtn.onclick = () => resolve(false)
        }, 50)
      })
      if (!confirmed) return

      const result = await runBulkAction(selected, async (item) => {
        await this._api.writing.deleteChapter(item.index, this._state.currentProjectId)
      })

      for (const item of result.success) {
        delete this._chapters[item.index]
      }
      const deleted = new Set(result.success.map((item) => item.index))
      this._chapterList = this._chapterList.filter((index) => !deleted.has(index))

      if (deleted.has(this._currentChapter)) {
        this._currentChapter = null
        if (this._onSelect) this._onSelect(null)
      }

      clearBulkSelection(this, "writing-chapters")
      this._notifyBulkChange()
    },

    _syncBulkUi() {
      syncBulkSelectionUi(this, "writing-chapters")
      this._notifyBulkChange()
    },

    _notifyBulkChange() {
      if (this._onBulkChange) this._onBulkChange("writing-chapters")
    },
  }

  return {
    load: () => tree.load(),
    render: () => tree.render(),
    bindEvents: (container) => tree.bindEvents(container),
    clearSelection: () => tree.clearSelection(),
    newChapter: () => tree.newChapter(),
    deleteChapter: (index) => tree.deleteChapter(index),
    runBulkAction: (action) => tree.runBulkAction(action),
    dispose: () => tree.dispose(),
    // orchestrator 专用状态同步方法
    _getChapterList: () => tree.getChapterList(),
    _getLoadError: () => tree.getLoadError(),
    _getChapterMap: () => tree.getChapterMap(),
    _getScenes: () => tree.getScenes(),
    _setCurrentChapter: (index) => tree.setCurrentChapter(index),
    _setCurrentSceneId: (sceneId) => tree.setCurrentSceneId(sceneId),
    _setChapters: (map) => tree.setChapters(map),
    _setScenes: (scenes) => tree.setScenes(scenes),
    _setChapterList: (list) => tree.setChapterList(list),
    _setBulkSelections: (selections) => tree.setBulkSelections(selections),
    _setShowBulkActions: (show) => tree.setShowBulkActions(show),
  }
}
