/**
 * World Bible / Worldbuilding Workspace v1.
 */
import { pollTaskProgress } from "../shared/workflowProgress.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../shared/assetDisplayState.js"
import { renderWorkspaceRail, workspaceRailKey } from "../shared/workspaceRail.js"

const PROJECTION_TYPE = "context_brief"
const BIBLE_AI_MESSAGE_LIMIT = 40
const BIBLE_AI_SELECTED_CHAPTER_LIMIT = 20
const BIBLE_AI_TEMPLATES = [
  { id: "builtin:none", label: "不带模板" },
  { id: "builtin:character", label: "人物" },
  { id: "builtin:event", label: "事件" },
  { id: "builtin:item", label: "物品" },
  { id: "builtin:location", label: "地点" },
  { id: "builtin:faction", label: "组织" },
  { id: "builtin:rule", label: "规则设定" },
]
const BIBLE_AI_TARGETS = [
  { value: "chat", label: "只聊天" },
  { value: "page_patch", label: "补写当前页" },
  { value: "new_page", label: "新建世界书页" },
  { value: "world_object_draft", label: "世界对象建议" },
]
const BIBLE_DISPLAY_MODES = new Set(["editor", "gallery", "filter"])
const BIBLE_PAGE_TYPES = {
  background: { label: "背景", title: "世界基本背景", desc: "世界观、历史和基础设定", color: "#6366f1", symbol: "BG" },
  species: { label: "种族", title: "种族", desc: "种族、生物和特殊生命体", color: "#dc2626", symbol: "SP" },
  faction: { label: "势力", title: "势力", desc: "组织、阵营和权力结构", color: "#d97706", symbol: "FA" },
  location: { label: "地点", title: "地点", desc: "城市、地理和关键场景", color: "#16a34a", symbol: "LO" },
  rule: { label: "规则", title: "规则体系", desc: "法则、能力体系和限制", color: "#475569", symbol: "RU" },
  item: { label: "物品", title: "重要物品", desc: "装备、资源和关键道具", color: "#9333ea", symbol: "IT" },
  secret: { label: "秘密", title: "秘密", desc: "伏笔、真相和隐藏信息", color: "#7c3aed", symbol: "SE" },
  custom: { label: "自定义", title: "自定义", desc: "尚未归入固定类别的设定", color: "#6b7280", symbol: "CU" },
}
const BIBLE_FALLBACK_TYPE = {
  label: "其他",
  title: "其他",
  desc: "未识别类别的世界书页面",
  color: "#64748b",
  symbol: "OT",
}

const worldBibleView = {
  _pages: [],
  _categories: [],
  _drafts: [],
  _activePage: null,
  _activeDraft: null,
  _synopsis: null,
  _synopsisTask: null,
  _synopsisPoller: null,
  _suggestions: [],
  _conflicts: [],
  _task: null,
  _projectionConflictHint: null,
  _projectionPoller: null,
  _projectionRetryPending: false,
  _beforeUnloadBound: false,
  _aiOpen: false,
  _aiMessages: [],
  _aiOutputTarget: "chat",
  _aiTemplateId: "builtin:none",
  _aiQualityMode: "fast",
  _aiSelectedChapters: "",
  _aiIncludeSynopsis: true,
  _aiResult: null,
  _displayMode: "editor",
  _activeCategory: "all",
  _galleryCategory: null,
  _suggestionBatchKey: null,

  async render() {
    if (!state.currentProjectId) {
      return `<div class="empty-state"><p>请先选择项目</p></div>`
    }
    this._restoreDisplayPreferences()
    await this._load()
    return `
      <section class="world-bible-workspace">
        ${this._renderToolbar()}
        ${this._renderDisplayMode()}
      </section>
    `
  },

  bindEvents() {
    if (!this._beforeUnloadBound) {
      window.addEventListener("beforeunload", () => this.onLeave())
      this._beforeUnloadBound = true
    }
    // 优先绑定到本视图渲染的根节点，这样 re-render 时旧的委托监听器会随旧 DOM 一起消失，
    // 同时支持直接 innerHTML 替换的测试环境。
    const container = document.querySelector(".world-bible-workspace")
      || document.getElementById("workspace-content")
      || document.body
    if (!container) return
    if (this._bibleClickHandler && this._bibleClickContainer) {
      this._bibleClickContainer.removeEventListener("click", this._bibleClickHandler)
    }
    this._bibleClickHandler = (e) => {
      const draftNode = e.target.closest("[data-bible-draft-id]")
      if (draftNode) {
        this._openDraft(draftNode.getAttribute("data-bible-draft-id"))
        return
      }
      const pageNode = e.target.closest("[data-bible-page-id]")
      if (pageNode) {
        this._activePage = this._pages.find((page) => page.id === pageNode.getAttribute("data-bible-page-id")) || null
        this._activeDraft = this._draftForPage(this._activePage?.id)
        router.refresh()
        return
      }
      const actionNode = e.target.closest("[data-action]")
      if (!actionNode) return
      const action = actionNode.getAttribute("data-action")
      if (action === "bible-new-page") this._createPage()
      else if (action === "bible-save-page") this._savePage()
      else if (action === "bible-publish-page") this._publishDraft()
      else if (action === "bible-discard-draft") this._discardDraft()
      else if (action === "bible-manage-categories") this._openCategoryManager()
      else if (action === "bible-refresh-synopsis") this._refreshSynopsis()
      else if (action === "bible-toggle-synopsis-auto") this._toggleSynopsisAuto()
      else if (action === "bible-synopsis-history") this._openSynopsisHistory()
      else if (action === "bible-unpin-synopsis") this._unpinSynopsis()
      else if (action === "bible-page-history") this._openPageHistory()
      else if (action === "bible-archive-page") this._archivePage()
      else if (action === "bible-open-asset-ref") this._openAssetRef(
        actionNode.getAttribute("data-ref-type"),
        actionNode.getAttribute("data-ref-id"),
      )
      else if (action === "bible-refresh-projection") this._refreshProjection(false)
      else if (action === "bible-force-refresh-projection") this._refreshProjection(true)
      else if (action === "bible-retry-projection") this._retryProjectionTask()
      else if (action === "bible-open-suggestions") this._openSuggestions()
      else if (action === "bible-open-conflicts") this._openConflicts()
      else if (action === "bible-toggle-ai") this._toggleAi()
      else if (action === "bible-ai-send") this._runAi("chat")
      else if (action === "bible-ai-generate") this._runAi()
      else if (action === "bible-set-display-mode") this._setDisplayMode(actionNode.getAttribute("data-mode"))
      else if (action === "bible-set-category") this._setActiveCategory(actionNode.getAttribute("data-category"))
      else if (action === "bible-gallery-open") this._openGalleryCategory(actionNode.getAttribute("data-category"))
      else if (action === "bible-gallery-back") this._backToGalleryHome()
      else if (action === "bible-open-page-card") this._openPageCard(actionNode.getAttribute("data-page-id"))
    }
    this._bibleClickContainer = container
    container.addEventListener("click", this._bibleClickHandler)
    container.querySelector("#bible-ai-output-target")?.addEventListener("change", (event) => {
      this._aiOutputTarget = event.target.value || "chat"
    })
    container.querySelector("#bible-ai-template")?.addEventListener("change", (event) => {
      this._aiTemplateId = event.target.value || "builtin:none"
    })
    container.querySelector("#bible-ai-quality-pro")?.addEventListener("change", (event) => {
      this._aiQualityMode = event.target.checked ? "pro" : "fast"
    })
    container.querySelector("#bible-ai-chapters")?.addEventListener("input", (event) => {
      this._aiSelectedChapters = event.target.value || ""
    })
    container.querySelector("#bible-ai-include-synopsis")?.addEventListener("change", (event) => {
      this._aiIncludeSynopsis = Boolean(event.target.checked)
    })
  },

  onLeave() {
    this._stopProjectionPolling()
    this._stopSynopsisPolling()
  },

  async _load() {
    const [data, categories, drafts, synopsis] = await Promise.all([
      api.world.listBiblePages({ novel_id: state.currentProjectId }),
      // Archived categories remain visible in the manager and keep their display
      // metadata for historical pages, but are filtered out of new selections.
      api.world.listBibleCategories(state.currentProjectId, true),
      api.world.listBibleDrafts(state.currentProjectId),
      api.world.getBibleSynopsis(state.currentProjectId),
    ])
    this._pages = data.items || []
    this._categories = categories?.items || []
    this._drafts = drafts?.items || []
    this._synopsis = synopsis || null
    if (this._synopsis?.active_task_id && !this._synopsisPoller) {
      this._synopsisTask = {
        task_id: this._synopsis.active_task_id,
        status: "running",
      }
      this._startSynopsisPolling(this._synopsis.active_task_id)
    }
    if (!this._activePage && !this._activeDraft && this._pages.length) {
      this._activePage = this._pages[0]
    }
    if (this._activePage) {
      this._activePage = this._pages.find((page) => page.id === this._activePage.id) || this._activePage
      this._activeDraft = this._draftForPage(this._activePage.id)
      await this._restoreProjectionTask(this._activePage)
    } else if (!this._activeDraft) {
      this._activeDraft = this._drafts.find((item) => !item.page_id) || null
    }
  },

  _renderPageNav() {
    const newDrafts = this._drafts.filter((item) => !item.page_id)
    if (!this._pages.length && !newDrafts.length) {
      return `<div class="world-bible-empty-hint">暂无页面</div>`
    }
    return `<div class="world-bible-page-nav">
      ${newDrafts.map((draft) => `
        <button class="btn btn-sm world-bible-page-btn ${this._activeDraft?.id === draft.id ? "btn-primary" : ""}"
          data-bible-draft-id="${esc(draft.id)}">
          ${esc(draft.title)} <span class="badge">工作稿</span>
        </button>
      `).join("")}
      ${this._pages.map((page) => `
      <button class="btn btn-sm world-bible-page-btn ${this._activePage?.id === page.id ? "btn-primary" : ""}"
        data-bible-page-id="${esc(page.id)}">
        ${esc(page.title)}${this._draftForPage(page.id) ? ` <span class="badge">工作稿</span>` : ""}
      </button>
    `).join("")}</div>`
  },

  _renderToolbar() {
    const modeLabels = { editor: "编辑", gallery: "图鉴", filter: "筛选" }
    return `
      <div class="view-header world-bible-toolbar">
        <div class="view-header__title">
          世界书
          <span class="view-header__count">${esc(this._pages.length)} 个页面</span>
        </div>
        <div class="view-header__actions">
          <span class="world-bible-toolbar__modes" aria-label="世界书展示模式">
            ${Object.entries(modeLabels).map(([mode, label]) => `
              <button class="btn btn-sm ${this._displayMode === mode ? "btn-primary" : ""}"
                data-action="bible-set-display-mode" data-mode="${esc(mode)}">${esc(label)}</button>
            `).join("")}
          </span>
          <button class="btn btn-sm btn-primary" data-action="bible-new-page">新建页面</button>
          <button class="btn btn-sm" data-action="bible-manage-categories">管理分类</button>
          <button class="btn btn-sm" data-action="bible-open-suggestions">创设建议</button>
          <button class="btn btn-sm" data-action="bible-open-conflicts">冲突检查</button>
        </div>
      </div>
    `
  },

  _renderDisplayMode() {
    if (this._displayMode === "gallery") return this._renderGalleryMode()
    if (this._displayMode === "filter") return this._renderFilterMode()
    return this._renderEditorMode()
  },

  _renderEditorMode() {
    return `
      ${this._renderSynopsisPanel()}
      <div class="world-bible-layout">
        ${renderWorkspaceRail({
          key: workspaceRailKey("world-bible", state.currentProjectId, "pages"),
          title: "页面",
          className: "world-bible-nav-rail workspace-rail--left",
          defaultOpen: typeof window === "undefined" || window.innerWidth > 760,
          content: `<aside class="panel world-bible-page-nav"><div class="world-bible-page-nav__heading">页面</div>${this._renderPageNav()}</aside>`,
        })}
        <main class="panel world-bible-editor-panel">
          ${this._renderActivePage()}
        </main>
      </div>
    `
  },

  _renderGalleryMode() {
    if (!this._pages.length) {
      return `<div class="panel world-bible-gallery"><div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div></div>`
    }
    if (this._galleryCategory) return this._renderGalleryCategoryPage(this._galleryCategory)
    return `
      <div class="panel world-bible-gallery">
        <div class="world-bible-gallery__hero">
          <h2>世界书图鉴</h2>
          <p>选择分类查看该类型的页面卡。</p>
        </div>
        <div class="world-bible-category-grid">
          ${this._categoryItems(true).map((item, index) => this._renderCategoryCard(item, {
            action: "bible-gallery-open",
            active: false,
            index,
          })).join("")}
        </div>
      </div>
    `
  },

  _renderGalleryCategoryPage(category) {
    const items = this._pagesForCategory(category)
    const meta = this._typeMeta(category)
    return `
      <div class="panel world-bible-gallery">
        <div class="world-bible-category-header" style="--world-bible-type-color:${esc(meta.color)};">
          <button class="btn btn-sm" data-action="bible-gallery-back">返回图鉴首页</button>
          <div class="world-bible-category-icon">${esc(meta.symbol)}</div>
          <div>
            <h2>${esc(meta.title)} <span>(${esc(items.length)})</span></h2>
            <p>${esc(meta.desc)}</p>
          </div>
        </div>
        ${this._renderPageCardGrid(items)}
      </div>
    `
  },

  _renderFilterMode() {
    if (!this._pages.length) {
      return `<div class="panel world-bible-filter"><div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div></div>`
    }
    const items = this._pagesForCategory(this._activeCategory)
    const title = this._activeCategory === "all" ? "全部页面" : this._typeMeta(this._activeCategory).title
    return `
      <div class="panel world-bible-filter">
        <div class="world-bible-section-title">页面分类</div>
        <div class="world-bible-category-grid">
          ${this._categoryItems(true).map((item, index) => this._renderCategoryCard(item, {
            action: "bible-set-category",
            active: item.type === this._activeCategory,
            index,
          })).join("")}
        </div>
        <div class="world-bible-section-title">${esc(title)} <span>${esc(items.length)} 个页面</span></div>
        ${this._renderPageCardGrid(items)}
      </div>
    `
  },

  _renderCategoryCard(item, { action, active, index }) {
    const meta = item.meta
    return `
      <button class="world-bible-category-card ${active ? "is-active" : ""}"
        type="button"
        data-action="${esc(action)}"
        data-category="${esc(item.type)}"
        style="--world-bible-type-color:${esc(meta.color)};animation-delay:${index * 0.03}s;">
        <span class="world-bible-category-card__band"></span>
        <span class="world-bible-category-card__icon">${esc(meta.symbol)}</span>
        <span class="world-bible-category-card__name">${esc(meta.title)}</span>
        <span class="world-bible-category-card__desc">${esc(meta.desc)}</span>
        <span class="world-bible-category-card__count">${esc(item.count)} 个页面</span>
      </button>
    `
  },

  _renderPageCardGrid(pages) {
    if (!pages.length) {
      return `<div class="empty-state"><p>这个分类下还没有世界书页面。</p></div>`
    }
    return `
      <div class="world-bible-page-card-grid">
        ${pages.map((page) => this._renderPageCard(page)).join("")}
      </div>
    `
  },

  _renderPageCard(page) {
    const meta = this._typeMeta(page.page_type)
    const display = worldAssetDisplay(page)
    const statusClass = displayStateBadgeClass(display.displayState)
    return `
      <article class="world-bible-page-card" style="--world-bible-type-color:${esc(meta.color)};">
        <div class="world-bible-page-card__band"></div>
        <div class="world-bible-page-card__head">
          <div class="world-bible-page-card__icon">${esc(meta.symbol)}</div>
          <div class="world-bible-page-card__title">
            <h3>${esc(page.title || "未命名页面")}</h3>
            <div class="world-bible-page-card__meta">
              <span>${esc(meta.title)}</span>
              <span class="badge ${esc(statusClass)}">${esc(display.label)}</span>
            </div>
          </div>
        </div>
        <p class="world-bible-page-card__summary">${esc(this._pageExcerpt(page))}</p>
        <div class="world-bible-page-card__footer">
          <span>${this._task?.meta?.page_id === page.id ? `投影：${esc(this._task.status || "pending")}` : "投影：按页查看"}</span>
        </div>
        <div class="world-bible-page-card__actions">
          <button class="btn btn-sm btn-primary" data-action="bible-open-page-card" data-page-id="${esc(page.id)}">打开编辑</button>
        </div>
      </article>
    `
  },

  _typeMeta(type) {
    const category = this._categories.find((item) => item.category_key === type)
    if (category) {
      return {
        label: category.name,
        title: category.name,
        desc: category.description || "项目自定义世界书分类",
        color: category.color || "#64748b",
        symbol: category.icon || String(category.name || type).slice(0, 2),
      }
    }
    return BIBLE_PAGE_TYPES[type] || {
      ...BIBLE_FALLBACK_TYPE,
      title: type || BIBLE_FALLBACK_TYPE.title,
      label: type || BIBLE_FALLBACK_TYPE.label,
    }
  },

  _statusLabel(status) {
    return worldAssetDisplay({ status }).label
  },

  _pageExcerpt(page) {
    const text = String(page?.free_text || "").replace(/\s+/g, " ").trim()
    if (!text) return "暂无正文摘要"
    return text.length > 120 ? `${text.slice(0, 120)}...` : text
  },

  _categoryItems(includeAll = false) {
    const counts = new Map()
    for (const page of this._pages) {
      const type = page.page_type || "custom"
      counts.set(type, (counts.get(type) || 0) + 1)
    }
    const activeCategories = this._categories.filter((item) => item.status !== "archived")
    const knownKeys = new Set(activeCategories.map((item) => item.category_key))
    const known = activeCategories.map((item) => ({
      type: item.category_key,
      count: counts.get(item.category_key) || 0,
      meta: this._typeMeta(item.category_key),
    }))
    const unknown = Array.from(counts.entries())
      .filter(([type]) => !knownKeys.has(type))
      .sort(([a], [b]) => String(a).localeCompare(String(b)))
      .map(([type, count]) => ({ type, count, meta: this._typeMeta(type) }))
    const items = [...known, ...unknown]
    if (!includeAll) return items
    return [{
      type: "all",
      count: this._pages.length,
      meta: { label: "全部", title: "全部", desc: "查看所有世界书页面", color: "#6366f1", symbol: "ALL" },
    }, ...items]
  },

  _pagesForCategory(category) {
    if (!category || category === "all") return this._pages
    return this._pages.filter((page) => (page.page_type || "custom") === category)
  },

  _draftForPage(pageId) {
    if (!pageId) return null
    return this._drafts.find((item) => item.page_id === pageId) || null
  },

  _openDraft(draftId) {
    const draft = this._drafts.find((item) => item.id === draftId)
    if (!draft) return
    this._activeDraft = draft
    this._activePage = draft.page_id
      ? this._pages.find((item) => item.id === draft.page_id) || null
      : null
    this._displayMode = "editor"
    router.refresh()
  },

  _categoryOptions(selected) {
    const categories = this._categories.length
      ? this._categories.filter((item) => item.status !== "archived" || item.category_key === selected)
      : Object.keys(BIBLE_PAGE_TYPES)
        .filter((key) => key !== "item")
        .map((key) => ({ category_key: key, name: BIBLE_PAGE_TYPES[key].title }))
    if (selected && !categories.some((item) => item.category_key === selected)) {
      categories.push({ category_key: selected, name: `${selected}（历史类别）` })
    }
    return categories.map((item) => `
      <option value="${esc(item.category_key)}" ${item.category_key === selected ? "selected" : ""}>${esc(item.name)}</option>
    `).join("")
  },

  _formatAssetRefs(refs) {
    return (Array.isArray(refs) ? refs : []).map((ref) => {
      const type = ref.type || ref.source_type || ref.target_type || ""
      const id = ref.id || ref.source_id || ref.target_id || ""
      return type && id ? `${type}:${id}` : ""
    }).filter(Boolean).join("\n")
  },

  _parseAssetRefs(value) {
    return String(value || "").split(/\n+/).map((line) => line.trim()).filter(Boolean).map((line) => {
      const separator = line.indexOf(":")
      if (separator < 1 || separator === line.length - 1) {
        throw new Error(`无效资产引用：${line}`)
      }
      return { type: line.slice(0, separator).trim(), id: line.slice(separator + 1).trim() }
    })
  },

  _renderAssetRefCards(refs) {
    const items = Array.isArray(refs) ? refs : []
    if (!items.length) return ""
    return `
      <div class="world-bible-suggestion-list">
        ${items.map((ref) => {
          const type = ref.type || ref.source_type || ref.target_type || ""
          const id = ref.id || ref.source_id || ref.target_id || ""
          return `
            <div class="world-bible-suggestion-item">
              <span class="badge">${esc(type)}</span> ${esc(id)}
              <button class="btn btn-sm" data-action="bible-open-asset-ref"
                data-ref-type="${esc(type)}" data-ref-id="${esc(id)}">跳转编辑</button>
            </div>
          `
        }).join("")}
      </div>
    `
  },

  _openAssetRef(type, id) {
    if (["world_bible_page", "page"].includes(type)) {
      this._openPageCard(id)
      return
    }
    if (["relation", "entity_relation"].includes(type)) {
      router.navigate("world", "relations")
      return
    }
    if (type === "map_fact") {
      router.navigate("map", null)
      return
    }
    if (["core_entity", "entity", "profile", "event"].includes(type)) {
      router.navigate("world", "objects")
      return
    }
    toast("该引用类型暂无可用的编辑入口", "warning")
  },

  _renderSynopsisPanel() {
    const synopsis = this._synopsis
    const revision = synopsis?.current_revision
    const coverage = revision?.coverage_json || {}
    const status = synopsis?.status || "missing"
    return `
      <section class="panel world-bible-synopsis-panel">
        <div class="world-bible-panel__header">
          <div>
            <h2>世界观简介 <span class="badge">作者模式 · P1</span></h2>
            <div class="world-bible-page-meta">只读 LLM 派生资料；不会替代确定性的 World Core Brief。</div>
          </div>
          <div class="world-bible-panel__actions">
            <button class="btn btn-sm btn-primary" data-action="bible-refresh-synopsis"
              ${synopsis?.pinned ? 'disabled title="请先取消固定"' : ""}>刷新简介</button>
            <button class="btn btn-sm" data-action="bible-synopsis-history">版本历史</button>
            <button class="btn btn-sm" data-action="bible-toggle-synopsis-auto">${synopsis?.auto_refresh_enabled ? "关闭自动维护" : "启用自动维护"}</button>
            ${synopsis?.pinned ? `<button class="btn btn-sm" data-action="bible-unpin-synopsis">取消固定并刷新</button>` : ""}
          </div>
        </div>
        <div class="world-bible-page-meta">
          状态：${esc(status)}${revision ? ` · v${esc(revision.version_number)} · ${esc(revision.token_estimate)} tokens` : ""}
          ${coverage.source_count != null ? ` · 覆盖 ${esc(coverage.source_count)} 个来源` : ""}
          ${this._synopsisTask ? ` · 刷新任务 ${esc(this._synopsisTask.task_id || "")}` : ""}
        </div>
        ${revision?.rendered_text
          ? `<pre class="generate-markdown-pre">${esc(revision.rendered_text)}</pre>`
          : `<div class="world-bible-empty-hint">尚无成功版本；生成中心启用时会使用有界确定性降级资料。</div>`}
        ${(synopsis?.warnings || []).map((item) => `<div class="world-bible-projection-status__hint">${esc(item)}</div>`).join("")}
      </section>
    `
  },

  _displayPreferenceKey(name) {
    return `worldBible:${state.currentProjectId}:${name}`
  },

  _restoreDisplayPreferences() {
    try {
      const storedMode = localStorage.getItem(this._displayPreferenceKey("displayMode"))
      this._displayMode = BIBLE_DISPLAY_MODES.has(storedMode) ? storedMode : "editor"
      this._activeCategory = localStorage.getItem(this._displayPreferenceKey("activeCategory")) || "all"
    } catch {
      this._displayMode = "editor"
      this._activeCategory = "all"
    }
    if (!this._activeCategory) this._activeCategory = "all"
  },

  _persistDisplayPreference(name, value) {
    try {
      localStorage.setItem(this._displayPreferenceKey(name), value)
    } catch {}
  },

  _setDisplayMode(mode) {
    if (!BIBLE_DISPLAY_MODES.has(mode)) mode = "editor"
    this._displayMode = mode
    if (mode !== "gallery") this._galleryCategory = null
    this._persistDisplayPreference("displayMode", mode)
    router.refresh()
  },

  _setActiveCategory(category) {
    this._activeCategory = category || "all"
    this._persistDisplayPreference("activeCategory", this._activeCategory)
    router.refresh()
  },

  _openGalleryCategory(category) {
    this._galleryCategory = category || "all"
    router.refresh()
  },

  _backToGalleryHome() {
    this._galleryCategory = null
    router.refresh()
  },

  _openPageCard(pageId) {
    const page = this._pages.find((item) => item.id === pageId)
    if (page) {
      this._activePage = page
      // Do not let an unrelated new-page draft leak into the selected page editor.
      this._activeDraft = this._draftForPage(page.id)
    }
    this._displayMode = "editor"
    this._galleryCategory = null
    this._persistDisplayPreference("displayMode", "editor")
    router.refresh()
  },

  _renderActivePage() {
    const page = this._activePage
    const draft = this._activeDraft || this._draftForPage(page?.id)
    const source = draft || page
    if (!source) {
      return `<div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div>`
    }
    const isWorking = Boolean(draft)
    const showAi = this._aiOpen && Boolean(page?.id)
    return `
      <div class="world-bible-panel__header">
        <div>
          <h2>${esc(source.title)}</h2>
          <div class="world-bible-page-meta">${esc(source.page_type)} · ${isWorking ? "工作稿" : esc(worldAssetDisplay(page).label)}</div>
        </div>
        <div class="world-bible-panel__actions">
          ${page?.id ? `<button class="btn btn-sm" data-action="bible-toggle-ai">${this._aiOpen ? "收起 AI" : "AI 创建/整理"}</button>` : ""}
          <button class="btn btn-sm" data-action="bible-save-page">保存工作稿</button>
          ${isWorking ? `<button class="btn btn-sm btn-primary" data-action="bible-publish-page">发布</button>` : ""}
          ${isWorking ? `<button class="btn btn-sm" data-action="bible-discard-draft">丢弃工作稿</button>` : ""}
          ${page?.id ? `<button class="btn btn-sm" data-action="bible-page-history">版本历史</button>` : ""}
          ${page?.id && !isWorking && page.status !== "archived" ? `<button class="btn btn-sm" data-action="bible-archive-page">归档页面</button>` : ""}
          ${page?.id ? `<button class="btn btn-sm" data-action="bible-refresh-projection">刷新投影</button>` : ""}
        </div>
      </div>
      <div class="world-bible-editor-layout${showAi ? " world-bible-editor-layout--with-ai" : ""}">
        <div>
          <div class="generate-form-grid">
            <label>标题
              <input class="form-input" id="bible-title" value="${esc(source.title || "")}" maxlength="255" />
            </label>
            <label>类别
              <select class="form-select" id="bible-page-type">${this._categoryOptions(source.page_type)}</select>
            </label>
            <label>排序
              <input class="form-input" id="bible-sort-order" type="number" value="${esc(source.sort_order || 0)}" />
            </label>
          </div>
          <textarea class="form-textarea world-bible-editor" id="bible-free-text" rows="16">${esc(source.free_text || "")}</textarea>
          <label class="bible-ai-field">关联资产（每行 type:id；世界书只保存引用，不内联修改资产）
            <textarea class="form-textarea" id="bible-asset-refs" rows="3">${esc(this._formatAssetRefs(source.linked_asset_refs_json))}</textarea>
          </label>
          ${this._renderAssetRefCards(source.linked_asset_refs_json)}
          ${page?.id ? this._renderProjectionStatus(page) : ""}
        </div>
        ${showAi ? this._renderAiSidebar(source) : ""}
      </div>
    `
  },

  _renderAiSidebar(page) {
    return `
      <aside class="bible-ai-sidebar">
        <div>
          <div class="bible-ai-sidebar__title">AI 创建/整理</div>
            <div class="bible-ai-sidebar__hint">生成结果会先进入待处理建议；页面建议需编辑并应用到工作稿，世界对象仍需明确采用。</div>
        </div>
        <div class="bible-ai-chip-row">
          <span class="badge">当前页：${esc(page.title)}</span>
          <span class="badge">页面正文来源</span>
        </div>
        <label class="bible-ai-field">输出目标
          <select id="bible-ai-output-target" class="form-select">
            ${BIBLE_AI_TARGETS.map((target) => `
              <option value="${esc(target.value)}" ${this._aiOutputTarget === target.value ? "selected" : ""}>${esc(target.label)}</option>
            `).join("")}
          </select>
        </label>
        <label class="bible-ai-field">模板
          <select id="bible-ai-template" class="form-select">
            ${BIBLE_AI_TEMPLATES.map((template) => `
              <option value="${esc(template.id)}" ${this._aiTemplateId === template.id ? "selected" : ""}>${esc(template.label)}</option>
            `).join("")}
          </select>
        </label>
        <label class="bible-ai-field">附带正文（章节序号，用逗号分隔，最多 20 章）
          <input id="bible-ai-chapters" class="form-input" value="${esc(this._aiSelectedChapters)}" placeholder="例如：1,2,5" />
        </label>
        <div class="bible-ai-sidebar__hint">长对话会保留在页面中，每次请求只发送最近 40 条消息。</div>
        <label class="bible-ai-toggle">
          <input id="bible-ai-quality-pro" type="checkbox" ${this._aiQualityMode === "pro" ? "checked" : ""} />
          高质量
        </label>
        <label class="bible-ai-toggle">
          <input id="bible-ai-include-synopsis" type="checkbox" ${this._aiIncludeSynopsis ? "checked" : ""} />
          使用当前世界观简介
        </label>
        <div class="bible-ai-messages">
          ${this._aiMessages.length ? this._aiMessages.map((message) => `
            <div class="bible-ai-message ${message.role === "assistant" ? "bible-ai-message--assistant" : "bible-ai-message--user"}">
              <strong>${message.role === "assistant" ? "AI" : "我"}：</strong>${esc(message.content)}
            </div>
          `).join("") : `<div class="bible-ai-empty">还没有对话。</div>`}
        </div>
        <textarea class="form-textarea" id="bible-ai-input" rows="3" placeholder="和 AI 讨论当前世界书页面，或说明想生成什么。"></textarea>
        <div class="bible-ai-actions">
          <button class="btn btn-sm" data-action="bible-ai-send">发送</button>
          <button class="btn btn-sm btn-primary" data-action="bible-ai-generate">生成建议</button>
        </div>
        <div id="bible-ai-result" class="bible-ai-result">
          ${this._renderAiResult()}
        </div>
      </aside>
    `
  },

  _renderAiResult() {
    const result = this._aiResult
    if (!result) return "当前页正文会作为带来源标记的 AI 参考资料。"
    if (result.error) return `<span class="bible-ai-result-error">${esc(result.error)}</span>`
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions : []
    const usage = result.context_usage
      ? `<div class="bible-ai-sidebar__hint">本次上下文：${esc(result.context_usage.status || "unknown")}${result.context_usage.revision_id ? ` · revision ${esc(result.context_usage.revision_id)}` : ""}${result.context_usage.fallback ? " · 确定性降级" : ""}</div>`
      : ""
    if (suggestions.length) {
      return `${usage}${suggestions.map((item) => `
        <div class="bible-ai-result-card">
          <div class="bible-ai-result-card__title">${esc(item.title || this._targetTypeLabel(item.target_type))}</div>
          <div>${esc(this._targetTypeLabel(item.target_type))} · 风险 ${esc(item.risk_level || "medium")}</div>
          ${item.summary ? `<div>${esc(item.summary)}</div>` : ""}
        </div>
      `).join("")}`
    }
    return result.reply ? `${usage}<div class="bible-ai-reply">${esc(result.reply)}</div>` : `${usage}已完成。`
  },

  _renderProjectionStatus(page) {
    const task = this._task
    const key = this._taskStorageKey(page)
    if (!task) {
      return `<div class="world-bible-empty-hint world-bible-empty-hint--projection">投影状态：未刷新 · ${esc(key)}</div>`
    }
    const retry = task.status === "failed" || task.status === "done"
      ? `<button class="btn btn-sm" data-action="bible-force-refresh-projection">强制重新刷新</button>`
      : ""
    const retryTask = task.status === "failed" && task.available_actions?.includes("retry")
      ? `<button class="btn btn-sm" data-action="bible-retry-projection" ${this._projectionRetryPending ? "disabled" : ""}>${this._projectionRetryPending ? "重试中..." : "重试任务"}</button>`
      : ""
    const hintHtml = this._projectionConflictHint
      ? `<div class="world-bible-projection-status__hint">${esc(this._projectionConflictHint)}</div>`
      : ""
    return `
      <div class="world-bible-projection-status">
        <div class="world-bible-projection-status__task">投影任务：${esc(task.task_id || task.id || "")}</div>
        <div>状态：${esc(task.status || "pending")} · 进度 ${Math.round((task.progress || 0) * 100)}%</div>
        ${task.error_message ? `<div class="world-bible-projection-status__error">${esc(task.error_message)}</div>` : ""}
        ${hintHtml}
        ${retryTask}
        ${retry}
      </div>
    `
  },

  async _retryProjectionTask() {
    const taskId = this._task?.task_id || this._task?.id
    const page = this._activePage
    if (
      !taskId
      || !page
      || this._projectionRetryPending
      || !this._task?.available_actions?.includes("retry")
    ) return false
    this._projectionRetryPending = true
    router.renderCurrentView()
    try {
      const result = await api.tasks.retry(taskId, state.currentProjectId)
      this._task = {
        ...this._task,
        ...result,
        task_id: taskId,
        status: result.status || "pending",
        error_message: null,
        available_actions: ["cancel"],
      }
      this._projectionRetryPending = false
      this._projectionConflictHint = null
      this._startProjectionPolling(taskId, page)
      toast("投影刷新任务已重新加入队列", "success")
      router.renderCurrentView()
      return true
    } catch (err) {
      this._projectionRetryPending = false
      toast(err.message || "重试投影刷新失败", "error")
      router.renderCurrentView()
      return false
    }
  },

  async _createPage() {
    const formHtml = `
      <div class="form-group">
        <label>页面标题 *</label>
        <input class="form-input" id="bible-create-title" value="世界基本背景" />
      </div>
      <div class="form-group">
        <label>页面类型</label>
        <select class="form-select" id="bible-create-type">
          ${this._categoryOptions("background")}
        </select>
      </div>
    `
    showModalHtml("新建世界书页面", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          const title = document.getElementById("bible-create-title")?.value?.trim()
          if (!title) {
            toast("请输入页面标题", "warning")
            return
          }
          try {
            const draft = await api.world.createBibleDraft({
              novel_id: state.currentProjectId,
              title,
              page_type: document.getElementById("bible-create-type")?.value || "custom",
            })
            this._activeDraft = draft
            this._activePage = null
            this._drafts = [draft, ...this._drafts]
            this._displayMode = "editor"
            this._galleryCategory = null
            this._persistDisplayPreference("displayMode", "editor")
            toast("工作稿已创建；发布后才进入世界观简介来源", "success")
            router.refresh()
          } catch (err) {
            toast(err.message || "创建页面失败", "error")
          }
        },
      },
    ])
  },

  async _savePage() {
    const page = this._activePage
    let draft = this._activeDraft || this._draftForPage(page?.id)
    if (!page && !draft) return
    try {
      if (!draft) {
        draft = await api.world.createBibleDraft({
          novel_id: state.currentProjectId,
          page_id: page.id,
        })
      }
      const payload = this._readDraftEditor()
      draft = await api.world.updateBibleDraft(draft.id, payload, state.currentProjectId)
      this._activeDraft = draft
      this._drafts = [draft, ...this._drafts.filter((item) => item.id !== draft.id)]
      toast("工作稿已保存；正式页面尚未变化", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  _readDraftEditor() {
    const title = document.getElementById("bible-title")?.value?.trim() || ""
    if (!title) throw new Error("标题不能为空")
    return {
      title,
      page_type: document.getElementById("bible-page-type")?.value || "custom",
      free_text: document.getElementById("bible-free-text")?.value || "",
      sort_order: Number(document.getElementById("bible-sort-order")?.value || 0),
      linked_asset_refs_json: this._parseAssetRefs(
        document.getElementById("bible-asset-refs")?.value || "",
      ),
    }
  },

  async _publishDraft() {
    let draft = this._activeDraft || this._draftForPage(this._activePage?.id)
    if (!draft) return
    try {
      draft = await api.world.updateBibleDraft(
        draft.id,
        this._readDraftEditor(),
        state.currentProjectId,
      )
      // The save succeeded even if the following publish CAS fails. Keep the
      // returned server snapshot locally so the conflict UI never suggests that
      // an older draft is the version preserved by the backend.
      this._activeDraft = draft
      this._drafts = [draft, ...this._drafts.filter((item) => item.id !== draft.id)]
      const page = await api.world.publishBibleDraft(draft.id, state.currentProjectId)
      this._activeDraft = null
      this._activePage = page
      this._drafts = this._drafts.filter((item) => item.id !== draft.id)
      toast("页面已发布，世界观简介已标记为需要刷新", "success")
      router.refresh()
    } catch (err) {
      const message = err.status === 409
        ? "发布冲突：正式页已变化。工作稿已保留，请重新核对后发布。"
        : err.message || "发布失败"
      toast(message, "error")
    }
  },

  _discardDraft() {
    const draft = this._activeDraft || this._draftForPage(this._activePage?.id)
    if (!draft) return
    return confirmAction("丢弃这个工作稿？正式页面和历史版本不会受影响。", async () => {
      try {
        await api.world.discardBibleDraft(draft.id, state.currentProjectId)
        this._drafts = this._drafts.filter((item) => item.id !== draft.id)
        this._activeDraft = null
        if (!draft.page_id) this._activePage = this._pages[0] || null
        toast("工作稿已丢弃", "success")
        router.refresh()
      } catch (err) {
        toast(err.message || "丢弃工作稿失败", "error")
      }
    })
  },

  async _openPageHistory() {
    const page = this._activePage
    if (!page?.id) return
    try {
      const revisions = await api.world.listBiblePageRevisions(
        page.id,
        state.currentProjectId,
      )
      const body = revisions.length ? revisions.map((item) => `
        <article class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${esc(item.revision_reason)}
          <pre class="generate-markdown-pre">${esc(String(item.snapshot_json?.free_text || "").slice(0, 1200))}</pre>
          <button class="btn btn-sm" data-bible-page-restore="${esc(item.version_number)}">恢复为工作稿</button>
        </article>
      `).join("") : `<div class="empty-state"><p>暂无页面版本</p></div>`
      showModalHtml("世界书页面版本", body, [], { size: "large" })
      document.querySelectorAll("[data-bible-page-restore]").forEach((button) => {
        button.addEventListener("click", () => this._restorePageRevision(
          Number(button.getAttribute("data-bible-page-restore")),
        ))
      })
    } catch (err) {
      toast(err.message || "加载页面历史失败", "error")
    }
  },

  async _restorePageRevision(version) {
    const page = this._activePage
    if (!page?.id || !version) return
    try {
      const draft = await api.world.restoreBiblePageRevision(
        page.id,
        version,
        state.currentProjectId,
      )
      closeModal()
      this._drafts = [draft, ...this._drafts.filter((item) => item.id !== draft.id)]
      this._activeDraft = draft
      toast("旧版本已恢复为工作稿，再次发布后才会生效", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "恢复页面版本失败", "error")
    }
  },

  _archivePage() {
    const page = this._activePage
    if (!page?.id || this._draftForPage(page.id)) return
    return confirmAction("归档此已发布页面？历史版本会保留，且页面将不再进入世界观简介。", async () => {
      try {
        const updated = await api.world.updateBiblePage(
          page.id,
          { status: "archived" },
          state.currentProjectId,
        )
        this._activePage = updated
        toast("页面已归档", "success")
        await this._load()
        router.refresh()
      } catch (err) {
        toast(err.message || "归档页面失败", "error")
      }
    })
  },

  _openCategoryManager() {
    const custom = this._categories.filter((item) => !item.builtin)
    const body = `
      <div class="world-bible-suggestion-list">
        ${custom.length ? custom.map((item) => `
          <div class="world-bible-suggestion-item">
            <strong>${esc(item.name)}</strong> · ${esc(item.category_key)} · ${esc(item.status)}
            <div class="world-bible-suggestion-item__actions">
              <button class="btn btn-sm" data-bible-category-edit="${esc(item.id)}">编辑</button>
              ${item.status !== "archived"
                ? `<button class="btn btn-sm" data-bible-category-archive="${esc(item.id)}">归档</button>`
                : `<button class="btn btn-sm" data-bible-category-restore="${esc(item.id)}">恢复</button>`}
            </div>
          </div>
        `).join("") : `<div class="world-bible-empty-hint">尚无自定义类别</div>`}
        <div class="form-group"><label>类别键（创建后不可修改）</label><input class="form-input" id="bible-category-key" placeholder="technology" /></div>
        <div class="form-group"><label>名称</label><input class="form-input" id="bible-category-name" placeholder="技术体系" /></div>
        <div class="form-group"><label>说明</label><input class="form-input" id="bible-category-description" /></div>
        <div class="form-group"><label>颜色</label><input class="form-input" id="bible-category-color" value="#64748B" /></div>
        <div class="form-group"><label>图标短文本</label><input class="form-input" id="bible-category-icon" maxlength="16" /></div>
        <div class="form-group"><label>排序</label><input class="form-input" id="bible-category-order" type="number" value="100" /></div>
      </div>
    `
    showModalHtml("管理世界书类别", body, [{
      text: "创建类别",
      class: "btn-primary",
      handler: () => this._createCategoryFromModal(),
    }], { size: "large" })
    document.querySelectorAll("[data-bible-category-edit]").forEach((button) => {
      button.addEventListener("click", () => this._editCategory(
        button.getAttribute("data-bible-category-edit"),
      ))
    })
    document.querySelectorAll("[data-bible-category-archive]").forEach((button) => {
      button.addEventListener("click", () => this._archiveCategory(
        button.getAttribute("data-bible-category-archive"),
      ))
    })
    document.querySelectorAll("[data-bible-category-restore]").forEach((button) => {
      button.addEventListener("click", () => this._restoreCategory(
        button.getAttribute("data-bible-category-restore"),
      ))
    })
  },

  _editCategory(categoryId) {
    const item = this._categories.find((category) => category.id === categoryId)
    if (!item || item.builtin) return
    const body = `
      <p class="world-bible-empty-hint">稳定键 ${esc(item.category_key)} 创建后不可修改。</p>
      <div class="form-group"><label>名称</label><input class="form-input" id="bible-category-edit-name" value="${esc(item.name)}" /></div>
      <div class="form-group"><label>说明</label><input class="form-input" id="bible-category-edit-description" value="${esc(item.description || "")}" /></div>
      <div class="form-group"><label>颜色</label><input class="form-input" id="bible-category-edit-color" value="${esc(item.color || "#64748B")}" /></div>
      <div class="form-group"><label>图标短文本</label><input class="form-input" id="bible-category-edit-icon" maxlength="16" value="${esc(item.icon || "")}" /></div>
      <div class="form-group"><label>排序</label><input class="form-input" id="bible-category-edit-order" type="number" value="${esc(item.sort_order || 0)}" /></div>
    `
    showModalHtml("编辑世界书类别", body, [{
      text: "保存",
      class: "btn-primary",
      handler: () => this._saveCategory(categoryId),
    }])
  },

  async _saveCategory(categoryId) {
    const name = document.getElementById("bible-category-edit-name")?.value?.trim() || ""
    if (!name) {
      toast("类别名称不能为空", "warning")
      return
    }
    try {
      await api.world.updateBibleCategory(categoryId, {
        name,
        description: document.getElementById("bible-category-edit-description")?.value || null,
        color: document.getElementById("bible-category-edit-color")?.value || "#64748B",
        icon: document.getElementById("bible-category-edit-icon")?.value || "",
        sort_order: Number(document.getElementById("bible-category-edit-order")?.value || 0),
      }, state.currentProjectId)
      closeModal()
      toast("类别已更新", "success")
      await this._load()
      router.refresh()
    } catch (err) {
      toast(err.message || "更新类别失败", "error")
    }
  },

  _archiveCategory(categoryId) {
    return confirmAction("归档该类别？现有页面不会删除，但不能再将工作稿切换到该类别。", async () => {
      try {
        await api.world.updateBibleCategory(
          categoryId,
          { status: "archived" },
          state.currentProjectId,
        )
        closeModal()
        toast("类别已归档，现有页面已保留", "success")
        await this._load()
        router.refresh()
      } catch (err) {
        toast(err.message || "归档类别失败", "error")
      }
    })
  },

  async _restoreCategory(categoryId) {
    try {
      await api.world.updateBibleCategory(
        categoryId,
        { status: "active" },
        state.currentProjectId,
      )
      closeModal()
      toast("类别已恢复，可重新用于工作稿", "success")
      await this._load()
      router.refresh()
    } catch (err) {
      toast(err.message || "恢复类别失败", "error")
    }
  },

  async _createCategoryFromModal() {
    const categoryKey = document.getElementById("bible-category-key")?.value?.trim() || ""
    const name = document.getElementById("bible-category-name")?.value?.trim() || ""
    if (!categoryKey || !name) {
      toast("请填写类别键和名称", "warning")
      return
    }
    try {
      await api.world.createBibleCategory({
        novel_id: state.currentProjectId,
        category_key: categoryKey,
        name,
        description: document.getElementById("bible-category-description")?.value || null,
        color: document.getElementById("bible-category-color")?.value || "#64748B",
        icon: document.getElementById("bible-category-icon")?.value || "",
        sort_order: Number(document.getElementById("bible-category-order")?.value || 100),
      })
      closeModal()
      toast("类别已创建；类别键后续不可修改", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "创建类别失败", "error")
    }
  },

  async _refreshSynopsis() {
    if (this._synopsis?.pinned) {
      toast("当前固定在历史版本；请先“取消固定并刷新”", "warning")
      return false
    }
    try {
      this._synopsisTask = await api.world.refreshBibleSynopsis(state.currentProjectId)
      toast(this._synopsisTask.existing ? "已有简介刷新任务在运行" : "简介刷新任务已提交", "success")
      this._startSynopsisPolling(this._synopsisTask.task_id)
      router.refresh()
    } catch (err) {
      toast(err.message || "刷新世界观简介失败", "error")
    }
  },

  _stopSynopsisPolling() {
    if (this._synopsisPoller?.stop) this._synopsisPoller.stop()
    this._synopsisPoller = null
  },

  _startSynopsisPolling(taskId) {
    if (!taskId) return
    this._stopSynopsisPolling()
    const novelId = state.currentProjectId
    this._synopsisPoller = pollTaskProgress({
      taskId,
      workflowType: "world_bible_synopsis_refresh",
      apiClient: {
        tasks: {
          get: (id) => api.tasks.get(id, novelId),
        },
      },
      intervalMs: 800,
      onUpdate: (_progress, task) => {
        if (task) this._synopsisTask = { ...task, task_id: task.id || task.task_id }
      },
      onDone: async () => {
        this._synopsisPoller = null
        this._synopsisTask = { task_id: taskId, status: "done" }
        this._synopsis = await api.world.getBibleSynopsis(novelId)
        toast("世界观简介已刷新", "success")
        router.renderCurrentView()
      },
      onFailed: async (progress) => {
        this._synopsisPoller = null
        this._synopsisTask = { task_id: taskId, status: "failed" }
        this._synopsis = await api.world.getBibleSynopsis(novelId)
        toast(`世界观简介刷新失败：${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
  },

  async _toggleSynopsisAuto() {
    try {
      this._synopsis = await api.world.setBibleSynopsisAutoRefresh(
        state.currentProjectId,
        !this._synopsis?.auto_refresh_enabled,
      )
      toast(this._synopsis.auto_refresh_enabled ? "已授权自动维护世界观简介" : "已关闭自动维护", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "更新自动维护授权失败", "error")
    }
  },

  async _openSynopsisHistory() {
    try {
      const data = await api.world.listBibleSynopsisRevisions(state.currentProjectId)
      const items = data.items || []
      const body = items.length ? items.map((item) => `
        <article class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${esc(item.status)} · ${esc(item.token_estimate)} tokens
          <pre class="generate-markdown-pre">${esc(String(item.rendered_text || "").slice(0, 1200))}</pre>
          <button class="btn btn-sm" data-synopsis-restore="${esc(item.id)}">恢复并固定此版本</button>
        </article>
      `).join("") : `<div class="empty-state"><p>暂无简介版本</p></div>`
      showModalHtml("世界观简介版本", body, [], { size: "large" })
      document.querySelectorAll("[data-synopsis-restore]").forEach((button) => {
        button.addEventListener("click", () => this._restoreSynopsis(button.getAttribute("data-synopsis-restore")))
      })
    } catch (err) {
      toast(err.message || "加载简介历史失败", "error")
    }
  },

  async _restoreSynopsis(revisionId) {
    try {
      this._synopsis = await api.world.restoreBibleSynopsisRevision(revisionId, state.currentProjectId)
      closeModal()
      toast("已恢复并固定旧版本；自动晋升暂停", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "恢复简介版本失败", "error")
    }
  },

  async _unpinSynopsis() {
    try {
      this._synopsis = await api.world.unpinBibleSynopsis(state.currentProjectId)
      // unpin may enqueue automatically when authorization is enabled. Requesting
      // refresh here is idempotent and also fulfils the explicit manual workflow.
      this._synopsisTask = await api.world.refreshBibleSynopsis(state.currentProjectId)
      this._startSynopsisPolling(this._synopsisTask.task_id)
      toast(this._synopsisTask.existing ? "已取消固定，刷新任务正在运行" : "已取消固定并提交刷新", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "取消固定失败", "error")
    }
  },

  _toggleAi() {
    this._aiOpen = !this._aiOpen
    router.refresh()
  },

  async _runAi(forcedTarget = null) {
    const page = this._activePage
    if (!page) return
    const selectedChapterIndices = this._selectedChapterIndices()
    if (selectedChapterIndices.length > BIBLE_AI_SELECTED_CHAPTER_LIMIT) {
      toast(`每次最多附带 ${BIBLE_AI_SELECTED_CHAPTER_LIMIT} 章正文`, "warning")
      return false
    }
    const input = document.getElementById("bible-ai-input")
    const text = input?.value?.trim() || ""
    if (text) {
      this._aiMessages.push({ role: "user", content: text })
      if (input) input.value = ""
    }
    const outputTarget = forcedTarget || this._aiOutputTarget || "chat"
    if (!this._aiMessages.length && outputTarget === "chat") {
      toast("请输入要聊的内容", "warning")
      return
    }
    this._aiResult = { reply: "正在生成..." }
    router.refresh()
    try {
      const response = await api.world.generateBiblePageAi(
        page.id,
        {
          output_target: outputTarget,
          messages: this._aiMessages.slice(-BIBLE_AI_MESSAGE_LIMIT),
          selected_chapter_indices: selectedChapterIndices,
          quality_mode: this._aiQualityMode,
          template_id: this._aiTemplateId,
          template_version: 1,
          template_variables: {},
          include_current_page: true,
          include_world_synopsis: this._aiIncludeSynopsis,
        },
        state.currentProjectId,
      )
      if (response.reply) this._aiMessages.push({ role: "assistant", content: response.reply })
      this._aiResult = response
      toast(outputTarget === "chat" ? "AI 已回复" : "建议已生成；页面建议编辑后只会写入工作稿", "success")
      router.refresh()
    } catch (err) {
      this._aiResult = { error: err.message || "生成失败" }
      toast(err.message || "生成失败", "error")
      router.refresh()
    }
  },

  _selectedChapterIndices() {
    const values = String(this._aiSelectedChapters || "")
      .split(/[,\s，]+/)
      .map((item) => Number(item.trim()))
      .filter((value) => Number.isInteger(value) && value > 0)
    return [...new Set(values)]
  },

  async _refreshProjection(force) {
    const page = this._activePage
    if (!page) return
    try {
      const result = await api.world.refreshBibleProjection(page.id, state.currentProjectId, PROJECTION_TYPE, force)
      localStorage.setItem(this._taskStorageKey(page), result.task_id)
      this._task = await api.tasks.get(result.task_id, state.currentProjectId)
      this._projectionConflictHint = null
      toast(result.existing ? "已有刷新任务正在运行" : "刷新任务已提交", "success")
      await router.refresh()
    } catch (err) {
      const apiError = window.errorLog?._lastApiError || null
      if (err.status === 409 || apiError?.status === 409) {
        if (window.errorLog) window.errorLog._lastApiError = null
        const finishedTaskId = this._extractFinishedTaskId(err, apiError)
        if (finishedTaskId) {
          localStorage.setItem(this._taskStorageKey(page), finishedTaskId)
          try {
            this._task = await api.tasks.get(finishedTaskId, state.currentProjectId)
          } catch {
            this._task = null
          }
        }
        this._projectionConflictHint = "上次刷新已结束，可使用强制重新刷新。"
        toast("上次刷新已结束，如需重跑请使用强制刷新", "warning")
        router.refresh()
      } else {
        toast(this._projectionRefreshErrorMessage(err), "error")
      }
    }
  },

  _projectionRefreshErrorMessage(err) {
    const message = err?.message || ""
    if (message.includes("No handler registered") || message.includes("world_bible_projection_refresh")) {
      return "投影刷新任务暂不可用，请确认后端 worker 已更新并重启后重试"
    }
    return message || "刷新投影失败"
  },

  async _restoreProjectionTask(page) {
    this._stopProjectionPolling()
    const taskId = localStorage.getItem(this._taskStorageKey(page))
    this._task = null
    if (!taskId) return
    try {
      const task = await api.tasks.get(taskId, state.currentProjectId)
      const meta = task.meta || {}
      if (
        meta.novel_id === state.currentProjectId
        && meta.page_id === page.id
        && meta.projection_type === PROJECTION_TYPE
      ) {
        this._task = task
        if (!this._isTerminalTask(task)) this._startProjectionPolling(taskId, page)
      }
    } catch {
      localStorage.removeItem(this._taskStorageKey(page))
    }
  },

  _isTerminalTask(task) {
    return ["done", "failed", "cancelled"].includes(task?.status)
  },

  _stopProjectionPolling() {
    if (this._projectionPoller?.stop) this._projectionPoller.stop()
    this._projectionPoller = null
  },

  _startProjectionPolling(taskId, page) {
    this._stopProjectionPolling()
    const novelId = state.currentProjectId
    this._projectionPoller = pollTaskProgress({
      taskId,
      workflowType: "world_bible_projection_refresh",
      apiClient: {
        tasks: {
          get: (id) => api.tasks.get(id, novelId),
        },
      },
      intervalMs: 800,
      onUpdate: (_progress, task) => {
        if (task) this._task = task
      },
      onDone: (_progress, task) => {
        this._projectionPoller = null
        if (task) this._task = task
        toast("世界书投影刷新完成", "success")
        router.renderCurrentView()
      },
      onFailed: (progress, task) => {
        this._projectionPoller = null
        if (task) this._task = task
        toast(`世界书投影刷新失败：${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
    if (page) localStorage.setItem(this._taskStorageKey(page), taskId)
  },

  _extractFinishedTaskId(err, apiError = null) {
    const message = `${err?.message || ""} ${apiError?.response || ""}`
    const match = message.match(/task_id:\s*([^；;\s]+)/)
    if (match?.[1]) return match[1].replace(/[",}]+$/, "")
    try {
      const parsed = JSON.parse(apiError?.response || "{}")
      return parsed?.detail?.task_id || null
    } catch {
      return null
    }
  },

  _taskStorageKey(page) {
    return `worldBibleProjection:${state.currentProjectId}:${page.id}:${PROJECTION_TYPE}`
  },

  async _openSuggestions() {
    try {
      const data = await api.world.listSuggestions({
        novel_id: state.currentProjectId,
        source_module: "world_bible",
        status: "pending",
      })
      this._suggestions = data.items || []
      this._suggestionBatchKey = this._suggestions[0] ? this._suggestionGroupKey(this._suggestions[0]) : null
      const body = this._renderSuggestionsModal()
      showModalHtml("创设建议", body, [], { size: "large" })
      this._bindSuggestionModal()
    } catch (err) {
      toast(err.message || "加载建议失败", "error")
    }
  },

  _renderSuggestionsModal() {
    if (!this._suggestions.length) return `<div class="empty-state"><p>暂无待处理建议</p></div>`
    const base = this._suggestionBatchBase()
    return `
      <div class="world-bible-suggestion-list">
        <div class="world-bible-suggestion-header">
          <div class="world-bible-suggestion-meta" data-bible-batch-meta>
            批量范围：${esc(base.review_group)} · ${esc(base.target_type)} · ${esc(base.action_schema)}
          </div>
          <div class="world-bible-suggestion-actions">
            <button class="btn btn-sm btn-primary" data-action="bible-batch-confirm">批量采用</button>
            <button class="btn btn-sm" data-action="bible-batch-reject">批量忽略</button>
          </div>
        </div>
        ${this._suggestions.map((item) => `
          <div class="world-bible-suggestion-item">
            ${this._renderSuggestionSelector(item, base)}
            <div class="world-bible-suggestion-title">${esc(this._suggestionTitle(item))}</div>
            <div class="world-bible-suggestion-risk">风险：${esc(item.risk_level)} · ${esc(item.action_schema)}</div>
            ${this._renderSuggestionPreview(item)}
            <div class="world-bible-suggestion-item__actions">
              ${this._isWorldBiblePageSuggestion(item)
                ? `<button class="btn btn-sm btn-primary" data-bible-edit-suggestion="${esc(item.id)}">编辑并应用到工作稿</button>`
                : `<button class="btn btn-sm btn-primary" data-bible-confirm-suggestion="${esc(item.id)}">采用</button>`}
              <button class="btn btn-sm" data-bible-reject-suggestion="${esc(item.id)}">忽略</button>
            </div>
          </div>
        `).join("")}
      </div>
    `
  },

  _bindSuggestionModal() {
    document.querySelector("[data-action='bible-batch-confirm']")?.addEventListener("click", () => this._decideSuggestionBatch(true))
    document.querySelector("[data-action='bible-batch-reject']")?.addEventListener("click", () => this._decideSuggestionBatch(false))
    document.querySelectorAll("[data-bible-confirm-suggestion]").forEach((node) => {
      node.addEventListener("click", () => this._decideSuggestion(node.getAttribute("data-bible-confirm-suggestion"), true))
    })
    document.querySelectorAll("[data-bible-edit-suggestion]").forEach((node) => {
      node.addEventListener("click", () => {
        const item = this._suggestions.find((entry) => entry.id === node.getAttribute("data-bible-edit-suggestion"))
        if (item) this._editSuggestionIntoDraft(item)
      })
    })
    document.querySelectorAll("[data-bible-reject-suggestion]").forEach((node) => {
      node.addEventListener("click", () => this._decideSuggestion(node.getAttribute("data-bible-reject-suggestion"), false))
    })
    document.querySelectorAll("[data-bible-batch-suggestion]").forEach((node) => {
      node.addEventListener("change", () => {
        if (!node.checked) return
        const item = this._suggestions.find((entry) => entry.id === node.getAttribute("data-bible-batch-suggestion"))
        if (!item) return
        this._suggestionBatchKey = this._suggestionGroupKey(item)
        this._syncSuggestionBatchSelection()
      })
    })
  },

  _suggestionBatchBase() {
    const selected = this._suggestions.find((item) => this._suggestionGroupKey(item) === this._suggestionBatchKey)
    const first = selected || this._suggestions[0] || {}
    return {
      review_group: first.review_group || "",
      target_type: first.target_type || "",
      action_schema: first.action_schema || "",
    }
  },

  _suggestionGroupKey(item = {}) {
    return [
      item.review_group || "",
      item.target_type || "",
      item.action_schema || "",
    ].join("::")
  },

  _isSuggestionCompatible(item, base) {
    return item.review_group === base.review_group
      && item.target_type === base.target_type
      && item.action_schema === base.action_schema
  },

  _renderSuggestionSelector(item, base) {
    const compatible = this._isSuggestionCompatible(item, base)
    return `
      <label class="world-bible-suggestion-selector">
        <input type="checkbox" data-bible-batch-suggestion="${esc(item.id)}" ${compatible ? "checked" : ""}>
        <span data-bible-batch-label="${esc(item.id)}">${compatible ? "已纳入批量操作" : "选择此组进行批量操作"}</span>
      </label>
    `
  },

  _syncSuggestionBatchSelection() {
    const base = this._suggestionBatchBase()
    const meta = document.querySelector("[data-bible-batch-meta]")
    if (meta) {
      meta.textContent = `批量范围：${base.review_group} · ${base.target_type} · ${base.action_schema}`
    }
    document.querySelectorAll("[data-bible-batch-suggestion]").forEach((node) => {
      const item = this._suggestions.find((entry) => entry.id === node.getAttribute("data-bible-batch-suggestion"))
      const compatible = item ? this._isSuggestionCompatible(item, base) : false
      node.checked = compatible
      const label = node.closest(".world-bible-suggestion-selector")?.querySelector("[data-bible-batch-label]")
      if (label) label.textContent = compatible ? "已纳入批量操作" : "选择此组进行批量操作"
    })
  },

  _suggestionTitle(item) {
    const payload = item.payload_json || {}
    return payload.title || payload.name || this._targetTypeLabel(item.target_type)
  },

  _targetTypeLabel(targetType) {
    return {
      world_bible_page_patch: "补写当前页",
      world_bible_page: "新建世界书页",
      core_entity_draft: "世界对象建议",
      profile_field: "档案字段",
    }[targetType] || targetType || "创设建议"
  },

  _isWorldBiblePageSuggestion(item) {
    return ["world_bible_page_patch", "world_bible_page"].includes(item?.target_type)
  },

  _editSuggestionIntoDraft(item) {
    const payload = item.payload_json || {}
    const isPatch = item.target_type === "world_bible_page_patch"
    const body = `
      ${isPatch ? "" : `<div class="form-group"><label>标题</label><input class="form-input" id="bible-suggestion-title" value="${esc(payload.title || "")}" /></div>`}
      ${isPatch ? "" : `<div class="form-group"><label>类别</label><select class="form-select" id="bible-suggestion-type">${this._categoryOptions(payload.page_type || "custom")}</select></div>`}
      <div class="form-group">
        <label>${isPatch ? "追加正文" : "页面正文"}</label>
        <textarea class="form-textarea" id="bible-suggestion-text" rows="12">${esc(isPatch ? payload.append_text || "" : payload.free_text || "")}</textarea>
      </div>
      <p class="world-bible-empty-hint">应用只写入工作稿；发布前仍可继续编辑或丢弃。</p>
    `
    showModalHtml("编辑创设建议", body, [{
      text: "应用到工作稿",
      class: "btn-primary",
      handler: () => this._applyEditedSuggestion(item),
    }], { size: "large" })
  },

  async _applyEditedSuggestion(item) {
    const isPatch = item.target_type === "world_bible_page_patch"
    const text = document.getElementById("bible-suggestion-text")?.value || ""
    try {
      const result = await api.world.applySuggestionToBibleDraft(
        item.id,
        isPatch
          ? { append_text: text }
          : {
              title: document.getElementById("bible-suggestion-title")?.value?.trim() || "",
              page_type: document.getElementById("bible-suggestion-type")?.value || "custom",
              free_text: text,
            },
        state.currentProjectId,
      )
      closeModal()
      toast("建议已应用到工作稿；正式页面尚未变化", "success")
      await this._load()
      const draftId = result?.result_ref_json?.id
      if (draftId) this._openDraft(draftId)
    } catch (err) {
      toast(err.message || "应用建议失败", "error")
    }
  },

  _renderSuggestionPreview(item) {
    const payload = item.payload_json || {}
    const excerpt = payload.append_text || payload.free_text || payload.summary || payload.public_info || ""
    const refs = Array.isArray(payload.source_refs) ? payload.source_refs : []
    return `
      <div class="world-bible-suggestion-preview">
        ${esc(String(excerpt).slice(0, 320))}
      </div>
      ${refs.length ? `
        <div class="world-bible-suggestion-refs">
          ${refs.map((ref) => `<span class="badge">${esc(ref.title || ref.source_type || "来源")}</span>`).join("")}
        </div>
      ` : ""}
    `
  },

  async _decideSuggestionBatch(accepted) {
    const selected = Array.from(document.querySelectorAll("[data-bible-batch-suggestion]:checked"))
      .map((node) => node.getAttribute("data-bible-batch-suggestion"))
      .filter(Boolean)
    if (!selected.length) {
      toast("没有可批量处理的建议", "warning")
      return
    }
    const selectedItems = selected
      .map((id) => this._suggestions.find((item) => item.id === id))
      .filter(Boolean)
    const base = selectedItems[0] ? {
      review_group: selectedItems[0].review_group,
      target_type: selectedItems[0].target_type,
      action_schema: selectedItems[0].action_schema,
    } : null
    if (!base || selectedItems.some((item) => !this._isSuggestionCompatible(item, base))) {
      toast("选中的建议类型不一致，请分别处理", "warning")
      return
    }
    if (accepted && selectedItems.some((item) => this._isWorldBiblePageSuggestion(item))) {
      toast("页面建议需要逐条编辑并应用到工作稿", "warning")
      return
    }
    let failed = 0
    for (const id of selected) {
      try {
        if (accepted) await api.world.confirmSuggestion(id, state.currentProjectId)
        else await api.world.rejectSuggestion(id, state.currentProjectId)
      } catch {
        failed += 1
      }
    }
    toast(failed ? `批量处理完成，${failed} 条失败` : "批量处理完成", failed ? "warning" : "success")
    await this._openSuggestions()
  },

  async _decideSuggestion(id, accepted) {
    try {
      const item = this._suggestions.find((entry) => entry.id === id)
      if (accepted && this._isWorldBiblePageSuggestion(item)) {
        this._editSuggestionIntoDraft(item)
        return
      }
      if (accepted) await api.world.confirmSuggestion(id, state.currentProjectId)
      else await api.world.rejectSuggestion(id, state.currentProjectId)
      toast(accepted ? "建议已采用" : "建议已忽略", "success")
      if (accepted) {
        await this._load()
        router.refresh()
      }
      await this._openSuggestions()
    } catch (err) {
      toast(err.message || "处理建议失败", "error")
    }
  },

  async _openConflicts() {
    try {
      const data = await api.world.listWorldConflicts({ novel_id: state.currentProjectId, status: "pending" })
      this._conflicts = data.items || []
      const body = this._conflicts.length
        ? this._conflicts.map((item) => `<p class="world-bible-conflict-item">${esc(item.severity)} · ${esc(item.summary)}</p>`).join("")
        : `<div class="empty-state"><p>暂无冲突检查项</p></div>`
      showModalHtml("冲突检查", body, [])
    } catch (err) {
      toast(err.message || "加载冲突失败", "error")
    }
  },
}

export default worldBibleView
