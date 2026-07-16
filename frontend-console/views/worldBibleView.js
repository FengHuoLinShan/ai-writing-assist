/**
 * World Bible / Worldbuilding Workspace v1.
 */
import { pollTaskProgress } from "../shared/workflowProgress.js"
import { displayStateBadgeClass, worldAssetDisplay } from "../shared/assetDisplayState.js"
import { renderWorkspaceRail, workspaceRailKey } from "../shared/workspaceRail.js"
import { buildMapQuery } from "./mapRouteContext.js"
import { createReferencePicker } from "../shared/referencePicker.js"

const PROJECTION_TYPE = "context_brief"
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
  _pageTemplates: [],
  _activationProfiles: [],
  _activeActivationProfileId: null,
  _activationTrace: null,
  _synopsisTask: null,
  _synopsisPoller: null,
  _synopsisTerminalTaskId: null,
  _suggestions: [],
  _conflicts: [],
  _task: null,
  _projectionConflictHint: null,
  _projectionPoller: null,
  _projectionRetryPending: false,
  _beforeUnloadBound: false,
  _displayMode: "editor",
  _activeCategory: "all",
  _galleryCategory: null,
  _suggestionBatchKey: null,
  _editorBaseline: null,
  _editorBaselineKey: null,
  _assetRefPicker: null,
  _activationTargetPicker: null,
  _assetRefWireRefs: [],

  async render() {
    if (!state.currentProjectId) {
      return `<div class="empty-state"><p>请先选择项目</p></div>`
    }
    this._restoreDisplayPreferences()
    await this._load()
    this._resetEditorBaseline()
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
        if (!this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并切换页面吗？")) return
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
      else if (action === "bible-manage-page-templates") this._openPageTemplateManager()
      else if (action === "bible-apply-page-template") this._applySelectedPageTemplate()
      else if (action === "bible-section-add") this._addSection()
      else if (action === "bible-section-remove") this._removeSection(actionNode)
      else if (action === "bible-section-up") this._moveSection(actionNode, -1)
      else if (action === "bible-section-down") this._moveSection(actionNode, 1)
      else if (action === "bible-activation-new") this._openActivationProfileEditor()
      else if (action === "bible-activation-edit") this._openActivationProfileEditor(this._activeActivationProfile())
      else if (action === "bible-activation-publish") this._publishActivationProfile()
      else if (action === "bible-activation-dry-run") this._dryRunActivationProfile()
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
      else if (action === "bible-improve-with-ai") this._openInGenerationCenter()
      else if (action === "bible-set-display-mode") this._setDisplayMode(actionNode.getAttribute("data-mode"))
      else if (action === "bible-set-category") this._setActiveCategory(actionNode.getAttribute("data-category"))
      else if (action === "bible-gallery-open") this._openGalleryCategory(actionNode.getAttribute("data-category"))
      else if (action === "bible-gallery-back") this._backToGalleryHome()
      else if (action === "bible-open-page-card") this._openPageCard(actionNode.getAttribute("data-page-id"))
    }
    this._bibleClickContainer = container
    container.addEventListener("click", this._bibleClickHandler)
    container.querySelector("#bible-activation-profile")?.addEventListener("change", (event) => {
      this._activeActivationProfileId = event.target.value || null
      this._activationTrace = null
      router.renderCurrentView()
    })
    this._mountAssetRefPicker()
  },

  onLeave() {
    this._assetRefPicker?.destroy?.()
    this._assetRefPicker = null
    this._activationTargetPicker?.destroy?.()
    this._activationTargetPicker = null
    this._stopProjectionPolling()
    this._stopSynopsisPolling()
  },

  canLeave() {
    return this._confirmDiscardEditorChanges("当前世界书页面有未保存修改，确定放弃并离开吗？")
  },

  async _load() {
    const [data, categories, drafts, synopsis, pageTemplates, activationProfiles] = await Promise.all([
      api.world.listBiblePages({ novel_id: state.currentProjectId }),
      // Archived categories remain visible in the manager and keep their display
      // metadata for historical pages, but are filtered out of new selections.
      api.world.listBibleCategories(state.currentProjectId, true),
      api.world.listBibleDrafts(state.currentProjectId),
      api.world.getBibleSynopsis(state.currentProjectId),
      api.world.listBiblePageTemplates
        ? api.world.listBiblePageTemplates(state.currentProjectId)
        : Promise.resolve({ items: [] }),
      api.context.listActivationProfiles
        ? api.context.listActivationProfiles(state.currentProjectId, true)
        : Promise.resolve({ items: [] }),
    ])
    this._pages = data.items || []
    this._categories = categories?.items || []
    this._drafts = drafts?.items || []
    this._synopsis = synopsis || null
    this._pageTemplates = pageTemplates?.items || []
    this._activationProfiles = activationProfiles?.items || []
    const routeQuery = router.getCurrentQuery?.() || new URLSearchParams()
    const requestedDraftId = routeQuery.get("draft_id")
    const requestedPageId = routeQuery.get("page_id")
    if (requestedDraftId) {
      const requestedDraft = this._drafts.find((item) => item.id === requestedDraftId)
      if (requestedDraft) {
        this._activeDraft = requestedDraft
        this._activePage = requestedDraft.page_id
          ? this._pages.find((item) => item.id === requestedDraft.page_id) || null
          : null
      }
    } else if (requestedPageId) {
      const requestedPage = this._pages.find((item) => item.id === requestedPageId)
      if (requestedPage) {
        this._activePage = requestedPage
        this._activeDraft = this._draftForPage(requestedPage.id)
      }
    }
    if (!this._activeActivationProfileId && this._activationProfiles.length) {
      this._activeActivationProfileId = this._activationProfiles[0].id
    }
    if (
      this._synopsis?.active_task_id
      && this._synopsis.active_task_id !== this._synopsisTerminalTaskId
      && !this._synopsisPoller
    ) {
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
          <button class="btn btn-sm" data-action="bible-manage-page-templates">页面模板</button>
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
        ${this._renderActivationInspector()}
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

  _taskStatusLabel(status) {
    return {
      missing: "尚未生成",
      pending: "等待处理",
      queued: "等待处理",
      running: "生成中",
      done: "已完成",
      success: "已完成",
      fresh: "已更新",
      degraded: "降级版本",
      refreshing: "生成中",
      failed: "生成失败",
      cancelled: "已取消",
      stale: "需要刷新",
    }[status] || "状态未知"
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
    if (!this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并切换工作稿吗？")) return
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
    return JSON.stringify(Array.isArray(refs) ? refs : [])
  },

  _assetRefType(ref) {
    return ref?.type || ref?.source_type || ref?.target_type || ""
  },

  _assetRefId(ref) {
    return ref?.id || ref?.source_id || ref?.target_id || ""
  },

  _parseAssetRefs(value) {
    const raw = String(value || "").trim()
    if (!raw) return []
    if (raw.startsWith("[")) {
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
        throw new Error("无效资产引用")
      }
      return parsed.map((item) => ({ ...item }))
    }
    return raw.split(/\n+/).map((line) => line.trim()).filter(Boolean).map((line) => {
      const separator = line.indexOf(":")
      if (separator < 1 || separator === line.length - 1) {
        throw new Error(`无效资产引用：${line}`)
      }
      return { type: line.slice(0, separator).trim(), id: line.slice(separator + 1).trim() }
    })
  },

  _canonicalAssetRefType(type) {
    if (["core_entity", "entity", "profile", "event"].includes(type)) return "core_entity"
    if (["relation", "entity_relation"].includes(type)) return "entity_relation"
    if (["world_bible_page", "page"].includes(type)) return "world_bible_page"
    return type
  },

  _entityAssetRefItem(item) {
    const display = worldAssetDisplay(item)
    const adopted = item?.status === "canonical"
    return {
      kind: "core_entity",
      id: item?.id || item?.entity_id,
      label: item?.name || "未命名对象",
      description: [item?.entity_type || "世界对象", item?.summary || item?.description].filter(Boolean).join(" · "),
      status: display.label,
      unavailable: !adopted || display.isHistory || Boolean(item?.unavailable),
    }
  },

  _relationAssetRefItem(item) {
    const sourceName = item?.source_name || item?.source_entity_name || item?.source?.name
    const targetName = item?.target_name || item?.target_entity_name || item?.target?.name
    return {
      kind: "entity_relation",
      id: item?.id || item?.relationship_id,
      label: sourceName && targetName ? `${sourceName} → ${targetName}` : "未命名关系",
      description: [item?.relation_type || "关系", item?.description].filter(Boolean).join(" · "),
      status: "已采用",
    }
  },

  _pageAssetRefItem(item) {
    const display = worldAssetDisplay(item)
    const published = ["canonical", "confirmed"].includes(item?.status)
    return {
      kind: "world_bible_page",
      id: item?.id,
      label: item?.title || "未命名世界书页面",
      description: this._typeMeta(item?.page_type).label,
      status: display.isHistory ? "历史" : "已发布",
      unavailable: !published || display.isHistory || Boolean(item?.unavailable),
    }
  },

  _mapFactAssetRefItem(item, mapName = "") {
    const typeLabels = {
      location: "人物/事件位置",
      route_state: "线路状态",
      boundary: "势力范围",
      state: "状态变化",
    }
    return {
      kind: "map_fact",
      id: item?.id,
      label: item?.target_name || typeLabels[item?.dynamic_type] || "地图事实",
      description: [mapName, typeLabels[item?.dynamic_type] || item?.dynamic_type, item?.scene_index ? `Scene ${item.scene_index}` : ""].filter(Boolean).join(" · "),
      status: "已采用",
    }
  },

  async _loadMapFactAssetRefs(query = "", wantedIds = null, projectId = "") {
    const ownerProjectId = String(projectId || "")
    if (!ownerProjectId) return []
    const mapsData = await api.world.listMaps({ novel_id: ownerProjectId, status: "active", skip: 0, limit: 50 })
    const maps = Array.isArray(mapsData) ? mapsData : (mapsData?.items || [])
    const pages = await Promise.all(maps.map(async (map) => {
      try {
        const facts = await api.world.listMapFacts(map.id, ownerProjectId, "confirmed")
        return (Array.isArray(facts) ? facts : (facts?.items || []))
          .map((item) => this._mapFactAssetRefItem(item, map.name || "未命名地图"))
      } catch {
        return []
      }
    }))
    const wanted = wantedIds ? new Set(wantedIds.map(String)) : null
    const needle = String(query || "").toLowerCase()
    const matched = pages.flat().filter((item) => {
      if (wanted) return wanted.has(String(item.id))
      return !needle || [item.label, item.description].some((value) => String(value || "").toLowerCase().includes(needle))
    })
    return wanted ? matched : matched.slice(0, 20)
  },

  _assetRefSources() {
    return [
      {
        kind: "core_entity",
        label: "世界对象",
        search: async (query, { projectId, limit }) => {
          const data = await api.world.listEntities({
            novel_id: projectId,
            display_state: "active",
            q: query || undefined,
            skip: 0,
            limit,
          })
          return (data?.items || [])
            .filter((item) => item?.status === "canonical")
            .map((item) => this._entityAssetRefItem(item))
        },
        resolve: async (ids, { projectId }) => Promise.all(ids.map(async (id) => {
          try {
            return this._entityAssetRefItem(await api.world.getEntity(id, projectId))
          } catch {
            return { kind: "core_entity", id, label: "不可用引用", unavailable: true }
          }
        })),
      },
      {
        kind: "entity_relation",
        label: "关系",
        search: async (query, { projectId, limit }) => {
          const data = await api.world.listRelationships({
            novel_id: projectId,
            status: "canonical",
            q: query || undefined,
            skip: 0,
            limit,
          })
          return (data?.items || data || []).map((item) => this._relationAssetRefItem(item))
        },
        resolve: async (ids, { projectId }) => {
          const data = await api.world.listRelationships({ novel_id: projectId, status: "canonical", skip: 0, limit: 100 })
          const wanted = new Set(ids.map(String))
          return (data?.items || data || []).filter((item) => wanted.has(String(item.id || item.relationship_id))).map((item) => this._relationAssetRefItem(item))
        },
      },
      {
        kind: "map_fact",
        label: "地图事实",
        search: (query, { projectId }) => this._loadMapFactAssetRefs(query, null, projectId),
        resolve: (ids, { projectId }) => this._loadMapFactAssetRefs("", ids, projectId),
      },
      {
        kind: "world_bible_page",
        label: "世界书页面",
        search: async (query) => {
          const needle = String(query || "").toLowerCase()
          return this._pages
            .filter((page) => ["canonical", "confirmed"].includes(page.status))
            .filter((page) => !needle || String(page.title || "").toLowerCase().includes(needle))
            .slice(0, 20)
            .map((page) => this._pageAssetRefItem(page))
        },
        resolve: async (ids, { projectId }) => Promise.all(ids.map(async (id) => {
          const loaded = this._pages.find((page) => page.id === id)
          if (loaded) return this._pageAssetRefItem(loaded)
          try {
            return this._pageAssetRefItem(await api.world.getBiblePage(id, projectId))
          } catch {
            return { kind: "world_bible_page", id, label: "不可用引用", unavailable: true }
          }
        })),
      },
    ]
  },

  _mountAssetRefPicker() {
    const root = document.getElementById("bible-asset-ref-picker")
    if (!root) return
    this._assetRefPicker?.destroy?.()
    const input = document.getElementById("bible-asset-refs")
    let wireRefs = []
    try {
      wireRefs = this._parseAssetRefs(input?.value || "")
    } catch {
      wireRefs = []
    }
    this._assetRefWireRefs = wireRefs.map((item) => ({ ...item }))
    this._assetRefPicker = createReferencePicker({
      root,
      projectId: state.currentProjectId,
      sources: this._assetRefSources(),
      mode: "multiple",
      maxItems: 50,
      placeholder: "按名称搜索关联资产",
      onOpen: (item) => this._openAssetRef(item.kind, item.id),
      onChange: (_items, refs) => {
        const nextWireRefs = refs.flatMap((ref) => {
          const originals = this._assetRefWireRefs.filter((item) => (
            this._assetRefId(item) === ref.id
            && this._canonicalAssetRefType(this._assetRefType(item)) === ref.kind
          ))
          return originals.length
            ? originals.map((item) => ({ ...item }))
            : [{ type: ref.kind, id: ref.id }]
        })
        this._assetRefWireRefs = nextWireRefs
        if (input) input.value = this._formatAssetRefs(nextWireRefs)
      },
    })
    const canonicalRefs = wireRefs.map((ref) => ({
      kind: this._canonicalAssetRefType(this._assetRefType(ref)),
      id: this._assetRefId(ref),
    })).filter((ref) => ref.kind && ref.id)
    void this._assetRefPicker.resolve(canonicalRefs)
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
      router.navigate("map", null, true, buildMapQuery({
        projectId: state.currentProjectId,
        mode: "overview",
      }))
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
            <div class="world-bible-page-meta">只读 AI 派生资料；不会替代确定性的核心世界设定摘要。</div>
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
          状态：${esc(this._taskStatusLabel(status))}${revision ? ` · v${esc(revision.version_number)} · 约 ${esc(revision.token_estimate)} 词元` : ""}
          ${coverage.source_count != null ? ` · 覆盖 ${esc(coverage.source_count)} 个来源` : ""}
        </div>
        ${revision?.rendered_text
          ? `<pre class="generate-markdown-pre">${esc(revision.rendered_text)}</pre>`
          : `<div class="world-bible-empty-hint">尚无成功版本；生成中心启用时会使用有界确定性降级资料。</div>`}
        ${(this._synopsisTask || (synopsis?.warnings || []).length) ? `<details class="world-bible-diagnostics">
          <summary>诊断信息</summary>
          ${this._synopsisTask ? `<div>任务 ID：${esc(this._synopsisTask.task_id || "未提供")}</div>` : ""}
          ${(synopsis?.warnings || []).map((item) => `<div class="world-bible-projection-status__hint">${esc(item)}</div>`).join("")}
        </details>` : ""}
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
    if (mode !== this._displayMode
      && !this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并切换视图吗？")) return
    this._displayMode = mode
    if (mode !== "gallery") this._galleryCategory = null
    this._persistDisplayPreference("displayMode", mode)
    router.refresh()
  },

  _setActiveCategory(category) {
    if (!this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并切换分类吗？")) return
    this._activeCategory = category || "all"
    this._persistDisplayPreference("activeCategory", this._activeCategory)
    router.refresh()
  },

  _openGalleryCategory(category) {
    if (!this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并打开图鉴吗？")) return
    this._galleryCategory = category || "all"
    router.refresh()
  },

  _backToGalleryHome() {
    if (!this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并返回图鉴吗？")) return
    this._galleryCategory = null
    router.refresh()
  },

  _openPageCard(pageId) {
    const page = this._pages.find((item) => item.id === pageId)
    if (page && !this._confirmDiscardEditorChanges("当前页面有未保存修改，确定放弃并打开其他页面吗？")) return
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
    const canPublish = page?.status !== "archived"
    return `
      <div class="world-bible-source-notice" role="note">
        资料页，不是事实源。正式设定请编辑对应世界对象；AI 建议不会自动发布。
      </div>
      <div class="world-bible-panel__header">
        <div>
          <h2>${esc(source.title)}</h2>
          <div class="world-bible-page-meta">${esc(this._typeMeta(source.page_type).label)} · ${isWorking ? "工作稿" : esc(worldAssetDisplay(page).label)}</div>
        </div>
        <div class="world-bible-panel__actions">
          ${page?.id ? `<button class="btn btn-sm" data-action="bible-improve-with-ai">用 AI 完善此页</button>` : ""}
          <button class="btn btn-sm" data-action="bible-save-page">保存工作稿</button>
          ${canPublish ? `<button class="btn btn-sm btn-primary" data-action="bible-publish-page">保存并发布</button>` : ""}
          ${isWorking ? `<button class="btn btn-sm" data-action="bible-discard-draft">丢弃工作稿</button>` : ""}
          ${page?.id ? `<button class="btn btn-sm" data-action="bible-page-history">版本历史</button>` : ""}
          ${page?.id && !isWorking && page.status !== "archived" ? `<button class="btn btn-sm" data-action="bible-archive-page">归档页面</button>` : ""}
          ${page?.id ? `<button class="btn btn-sm" data-action="bible-refresh-projection">刷新投影</button>` : ""}
        </div>
      </div>
      <div class="world-bible-editor-layout">
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
            <label>页面模板
              <select class="form-select" id="bible-page-template">
                <option value="">空白页</option>
                ${this._pageTemplates.map((template) => `
                  <option value="${esc(template.template_key)}" ${source.template_key === template.template_key ? "selected" : ""}>
                    ${esc(template.name)} · v${esc(template.version_number)}${template.builtin ? " · 内置" : ""}
                  </option>
                `).join("")}
              </select>
            </label>
          </div>
          <div class="world-bible-template-actions">
            <button class="btn btn-sm" data-action="bible-apply-page-template">应用模板到工作稿</button>
            ${source.template_key ? `<span class="badge">${esc(source.template_key)} · v${esc(source.template_version || 1)}</span>` : ""}
          </div>
          <label class="bible-ai-field">页面概览
            <textarea class="form-textarea world-bible-editor" id="bible-free-text" rows="8">${esc(source.free_text || "")}</textarea>
          </label>
          ${this._renderSectionEditor(source.sections_json)}
          <label class="bible-ai-field">关联资产
            <span class="world-bible-page-meta">按名称选择已采用的对象、关系、地图事实或已发布页面；这里只保存引用，不内联修改资产。</span>
            <div id="bible-asset-ref-picker"></div>
            <textarea id="bible-asset-refs" hidden>${esc(this._formatAssetRefs(source.linked_asset_refs_json))}</textarea>
          </label>
          ${page?.id ? this._renderProjectionStatus(page) : ""}
        </div>
      </div>
    `
  },

  _renderSectionEditor(sections) {
    const items = Array.isArray(sections) ? [...sections] : []
    items.sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0)
      || String(a.section_id || "").localeCompare(String(b.section_id || "")))
    return `
      <section class="world-bible-sections">
        <div class="world-bible-sections__header">
          <div>
            <strong>页面分区</strong>
            <div class="world-bible-page-meta">分区 ID 在发布与恢复时保持稳定，用于 diff 和来源定位。</div>
          </div>
          <button class="btn btn-sm" data-action="bible-section-add">新增分区</button>
        </div>
        <div class="world-bible-section-list">
          ${items.length ? items.map((section, index) => this._renderSectionCard(section, index)).join("")
            : `<div class="world-bible-empty-hint">暂无分区；旧页面可继续只使用概览。</div>`}
        </div>
      </section>
    `
  },

  _renderSectionCard(section, index) {
    return `
      <article class="world-bible-section-editor" data-section-index="${index}" data-section-id="${esc(section.section_id)}">
        <div class="world-bible-section-editor__toolbar">
          <span class="badge">${esc(section.section_id)}</span>
          <span class="world-bible-section-editor__actions">
            <button class="btn btn-sm" data-action="bible-section-up" aria-label="上移分区">↑</button>
            <button class="btn btn-sm" data-action="bible-section-down" aria-label="下移分区">↓</button>
            <button class="btn btn-sm" data-action="bible-section-remove">移除</button>
          </span>
        </div>
        <div class="generate-form-grid">
          <label>标题<input class="form-input" data-section-field="title" maxlength="120" value="${esc(section.title || "未命名分区")}" /></label>
          <label>类型<select class="form-select" data-section-field="section_type">
            ${["markdown", "checklist", "asset_collection"].map((type) => `<option value="${type}" ${section.section_type === type ? "selected" : ""}>${type}</option>`).join("")}
          </select></label>
          <label>敏感度<select class="form-select" data-section-field="sensitivity_hint">
            ${["author_safe", "author_only", "public_baseline"].map((value) => `<option value="${value}" ${section.sensitivity_hint === value ? "selected" : ""}>${value}</option>`).join("")}
          </select></label>
          <label>投影<select class="form-select" data-section-field="projection_policy">
            ${["eligible", "excluded"].map((value) => `<option value="${value}" ${section.projection_policy === value ? "selected" : ""}>${value}</option>`).join("")}
          </select></label>
        </div>
        <label class="bible-ai-field">分区正文
          <textarea class="form-textarea" data-section-field="body_markdown" rows="6">${esc(section.body_markdown || "")}</textarea>
        </label>
        <label class="bible-ai-field">局部引用 hash（每行一个，必须来自页面级引用）
          <textarea class="form-textarea" data-section-field="linked_asset_ref_hashes" rows="2">${esc((section.linked_asset_ref_hashes || []).join("\n"))}</textarea>
        </label>
      </article>
    `
  },

  _activeActivationProfile() {
    return this._activationProfiles.find((item) => item.id === this._activeActivationProfileId) || null
  },

  _renderActivationInspector() {
    const profile = this._activeActivationProfile()
    return `
      <aside class="panel world-bible-inspector">
        <div class="world-bible-inspector__header">
          <div>
            <strong>AI 参考规则</strong>
            <div class="world-bible-page-meta">资料发布与规则发布相互独立。</div>
          </div>
          <button class="btn btn-sm" data-action="bible-activation-new">新建</button>
        </div>
        <label class="bible-ai-field">Activation Profile
          <select class="form-select" id="bible-activation-profile">
            <option value="">未选择</option>
            ${this._activationProfiles.map((item) => `
              <option value="${esc(item.id)}" ${item.id === this._activeActivationProfileId ? "selected" : ""}>
                ${esc(item.name)} · v${esc(item.version_number)} · ${esc(item.status)}
              </option>
            `).join("")}
          </select>
        </label>
        ${profile ? `
          <div class="world-bible-profile-summary">
            <div><span class="badge">${esc(profile.status)}</span> ${esc(profile.profile_key)}</div>
            <div>${esc(profile.rules_json?.length || 0)} 条规则 · ${esc((profile.applicable_actions_json || []).join("、"))}</div>
          </div>
          <div class="world-bible-inspector__actions">
            <button class="btn btn-sm" data-action="bible-activation-edit">编辑工作稿</button>
            <button class="btn btn-sm btn-primary" data-action="bible-activation-publish" ${profile.status === "archived" ? "disabled" : ""}>发布规则</button>
          </div>
          <label class="bible-ai-field">Dry-run 任务文本
            <textarea class="form-textarea" id="bible-activation-task" rows="4" placeholder="例如：描写北境商队使用银币"></textarea>
          </label>
          <button class="btn btn-sm" data-action="bible-activation-dry-run">执行 Dry-run</button>
        ` : `<div class="world-bible-empty-hint">创建或选择 Profile 后，可配置正向词、排除词和固定资料目标。</div>`}
        ${this._renderActivationTrace()}
      </aside>
    `
  },

  _renderActivationTrace() {
    const trace = this._activationTrace
    if (!trace) return ""
    const included = Array.isArray(trace.items) ? trace.items : []
    const excluded = Array.isArray(trace.excluded_items) ? trace.excluded_items : []
    return `
      <div class="world-bible-activation-trace">
        <div class="world-bible-section-title">本次参考资料</div>
        ${(trace.rule_evaluations || []).map((item) => `
          <div class="world-bible-trace-rule ${item.matched ? "is-matched" : ""}">
            ${esc(item.rule_id)} · ${item.matched ? "命中" : "未命中"} · ${esc(item.candidate_count || 0)} 个候选
            ${(item.blocked_clauses || []).length ? `<div>${esc(item.blocked_clauses.join("、"))}</div>` : ""}
          </div>
        `).join("")}
        <div class="world-bible-trace-group"><strong>已加入 (${esc(included.length)})</strong>
          ${included.map((item) => this._renderActivationTraceItem(item)).join("") || `<div class="world-bible-empty-hint">无</div>`}
        </div>
        <div class="world-bible-trace-group"><strong>被排除 / 裁剪 (${esc(excluded.length)})</strong>
          ${excluded.map((item) => this._renderActivationTraceItem(item)).join("") || `<div class="world-bible-empty-hint">无</div>`}
        </div>
        ${(trace.warnings || []).map((warning) => `<div class="world-bible-projection-status__hint">${esc(warning)}</div>`).join("")}
      </div>
    `
  },

  _renderActivationTraceItem(item) {
    return `
      <div class="world-bible-trace-item">
        <strong>${esc(item.label || item.target?.target_id || "未知目标")}</strong>
        <div>${esc(item.activation_reason || item.source || "")} · ${esc(item.token_after ?? item.token_before ?? 0)} tokens</div>
        ${item.excluded_reason ? `<span class="badge">${esc(item.excluded_reason)}</span>` : ""}
      </div>
    `
  },

  _openActivationProfileEditor(profile = null) {
    const rule = profile?.rules_json?.[0] || null
    const target = rule?.select?.target_refs?.[0]
      || (this._activePage?.id ? { target_type: "world_bible_page", target_id: this._activePage.id } : {})
    const body = `
      <p class="world-bible-empty-hint">简单模式只支持确定性词匹配、固定 TargetRef、优先级和预算；不支持 regex、随机、Prompt role 或递归。</p>
      <div class="form-group"><label>Profile key</label><input class="form-input" id="bible-profile-key" value="${esc(profile?.profile_key || "writing.world_bible")}" ${profile ? "disabled" : ""} /></div>
      <div class="form-group"><label>名称</label><input class="form-input" id="bible-profile-name" value="${esc(profile?.name || "场景写作世界资料")}" /></div>
      <div class="form-group"><label>适用操作</label><input class="form-input" id="bible-profile-action" value="${esc(profile?.applicable_actions_json?.[0] || "writing.generate")}" /></div>
      <div class="form-group"><label>规则名称</label><input class="form-input" id="bible-rule-name" value="${esc(rule?.name || "命中关键词时加入资料")}" /></div>
      <div class="form-group"><label>正向词（逗号分隔）</label><input class="form-input" id="bible-rule-positive" value="${esc((rule?.match?.positive_terms || []).join(","))}" /></div>
      <div class="form-group"><label>排除词（逗号分隔）</label><input class="form-input" id="bible-rule-negative" value="${esc((rule?.match?.negative_terms || []).join(","))}" /></div>
      <div class="form-group">
        <label>固定资料目标</label>
        <div id="bible-rule-target-picker"></div>
        <input type="hidden" id="bible-rule-target" value="${esc(target?.target_type && target?.target_id ? `${target.target_type}:${target.target_id}` : "")}" />
        <p class="form-help">只可选择已采用的世界对象或已发布的世界书页面。</p>
      </div>
      <div class="generate-form-grid">
        <label>优先级<input class="form-input" id="bible-rule-priority" type="number" min="0" max="1000" value="${esc(rule?.rank?.priority ?? 700)}" /></label>
        <label>Top-K<input class="form-input" id="bible-rule-top-k" type="number" min="1" max="256" value="${esc(rule?.rank?.top_k ?? 12)}" /></label>
        <label>Token cap<input class="form-input" id="bible-rule-token-cap" type="number" min="64" max="32000" value="${esc(rule?.rank?.token_cap ?? 1200)}" /></label>
      </div>
    `
    showModalHtml(profile ? "编辑 AI 参考规则工作稿" : "新建 AI 参考规则", body, [{
      text: "保存工作稿",
      class: "btn-primary",
      handler: () => this._saveActivationProfileEditor(profile),
    }], { size: "large" })
    this._mountActivationTargetPicker(target)
  },

  _mountActivationTargetPicker(target) {
    const root = document.getElementById("bible-rule-target-picker")
    if (!root) return
    this._activationTargetPicker?.destroy?.()
    const input = document.getElementById("bible-rule-target")
    this._activationTargetPicker = createReferencePicker({
      root,
      projectId: state.currentProjectId,
      sources: this._assetRefSources().filter((source) => (
        source.kind === "core_entity" || source.kind === "world_bible_page"
      )),
      placeholder: "按名称搜索资料目标",
      onChange: (_items, refs) => {
        if (input) input.value = refs[0] ? `${refs[0].kind}:${refs[0].id}` : ""
      },
    })
    if (target?.target_id) {
      this._activationTargetPicker.resolve([{
        kind: this._canonicalAssetRefType(target.target_type),
        id: target.target_id,
      }])
    }
  },

  async _saveActivationProfileEditor(profile) {
    const splitTerms = (id) => String(document.getElementById(id)?.value || "")
      .split(/[,，\n]+/).map((value) => value.trim()).filter(Boolean)
    const action = document.getElementById("bible-profile-action")?.value?.trim() || ""
    const positive = splitTerms("bible-rule-positive")
    const rawTarget = document.getElementById("bible-rule-target")?.value?.trim() || ""
    const separator = rawTarget.indexOf(":")
    if (!action || !positive.length || separator < 1) {
      toast("请填写适用操作、至少一个正向词和有效资料目标", "warning")
      return
    }
    const rule = {
      rule_id: profile?.rules_json?.[0]?.rule_id || `rule_${Date.now().toString(36)}`,
      name: document.getElementById("bible-rule-name")?.value?.trim() || "资料规则",
      enabled: true,
      scope: { actions: [action], modes: ["author_safe", "author_full"], match_sources: ["task_text", "current_scene_text", "explicit_focus"] },
      match: { positive_terms: positive, negative_terms: splitTerms("bible-rule-negative"), positive_logic: "any", negative_logic: "any", mode: "normalized_substring" },
      select: {
        target_refs: [{ target_type: rawTarget.slice(0, separator).trim(), target_id: rawTarget.slice(separator + 1).trim(), target_path: "" }],
        expand_page_links: true,
        relation_types: [],
        max_depth: 1,
      },
      rank: {
        priority: Number(document.getElementById("bible-rule-priority")?.value || 700),
        top_k: Number(document.getElementById("bible-rule-top-k")?.value || 12),
        token_cap: Number(document.getElementById("bible-rule-token-cap")?.value || 1200),
      },
    }
    try {
      const name = document.getElementById("bible-profile-name")?.value?.trim() || "AI 参考规则"
      const saved = profile
        ? await api.context.updateActivationProfile(profile.id, {
          base_version_number: profile.version_number,
          name,
          applicable_actions_json: [action],
          rules_json: [rule],
        }, state.currentProjectId)
        : await api.context.createActivationProfile({
          novel_id: state.currentProjectId,
          profile_key: document.getElementById("bible-profile-key")?.value?.trim() || "",
          name,
          applicable_actions_json: [action],
          rules_json: [rule],
        })
      closeModal()
      this._activationTargetPicker?.destroy?.()
      this._activationTargetPicker = null
      this._activeActivationProfileId = saved.id
      this._activationTrace = null
      toast("规则工作稿已保存；发布前不会影响真实调用", "success")
      await this._load()
      router.refresh()
    } catch (err) {
      toast(err.message || "保存规则失败", "error")
    }
  },

  _publishActivationProfile() {
    const profile = this._activeActivationProfile()
    if (!profile) return
    return confirmAction("发布此 Activation Profile？后续显式启用它的 AI 调用将固定使用该 revision。", async () => {
      try {
        const saved = await api.context.publishActivationProfile(profile.id, {
          base_version_number: profile.version_number,
          revision_reason: "manual_publish",
        }, state.currentProjectId)
        this._activeActivationProfileId = saved.id
        toast("AI 参考规则已发布", "success")
        await this._load()
        router.refresh()
      } catch (err) {
        toast(err.message || "发布规则失败", "error")
      }
    })
  },

  async _dryRunActivationProfile() {
    const profile = this._activeActivationProfile()
    if (!profile) return
    try {
      this._activationTrace = await api.context.previewActivationProfile({
        novel_id: state.currentProjectId,
        profile_id: profile.id,
        action: profile.applicable_actions_json?.[0] || "writing.generate",
        reveal_mode: "author_safe",
        task_text: document.getElementById("bible-activation-task")?.value || "",
        entity_ids: [],
        top_k: 64,
        depth: 2,
      })
      router.renderCurrentView()
    } catch (err) {
      toast(err.message || "Dry-run 失败", "error")
    }
  },

  _renderProjectionStatus(page) {
    const task = this._task
    const key = this._taskStorageKey(page)
    if (!task) {
      return `<div class="world-bible-empty-hint world-bible-empty-hint--projection">
        <div>上下文摘要尚未刷新。</div>
        <details class="world-bible-diagnostics">
          <summary>诊断信息</summary>
          <div>本地恢复键：${esc(key)}</div>
        </details>
      </div>`
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
        <div>上下文摘要：${esc(this._taskStatusLabel(task.status || "pending"))} · 进度 ${Math.round((task.progress || 0) * 100)}%</div>
        ${task.error_message ? `<div class="world-bible-projection-status__error">${esc(task.error_message)}</div>` : ""}
        ${hintHtml}
        ${retryTask}
        ${retry}
        <details class="world-bible-diagnostics">
          <summary>诊断信息</summary>
          <div>任务 ID：${esc(task.task_id || task.id || "未提供")}</div>
          <div>原始状态：${esc(task.status || "pending")}</div>
        </details>
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
      <div class="form-group">
        <label>页面模板</label>
        <select class="form-select" id="bible-create-template">
          <option value="">空白页</option>
          ${this._pageTemplates.map((template) => `<option value="${esc(template.template_key)}">${esc(template.name)} · v${esc(template.version_number)}</option>`).join("")}
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
            const templateKey = document.getElementById("bible-create-template")?.value || ""
            const template = this._pageTemplates.find((item) => item.template_key === templateKey)
            const createPayload = {
              novel_id: state.currentProjectId,
              title,
              page_type: document.getElementById("bible-create-type")?.value || "custom",
            }
            if (templateKey) {
              createPayload.template_key = templateKey
              createPayload.template_version = template?.version_number || 1
            }
            const draft = await api.world.createBibleDraft(createPayload)
            this._activeDraft = templateKey
              ? await api.world.applyBiblePageTemplate(draft.id, {
                template_key: templateKey,
                template_version: template?.version_number || 1,
                replace_sections: true,
              }, state.currentProjectId)
              : draft
            this._activePage = null
            this._drafts = [this._activeDraft, ...this._drafts]
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

  async _savePage({ refresh = true } = {}) {
    const page = this._activePage
    let draft = this._activeDraft || this._draftForPage(page?.id)
    if (!page && !draft) return false
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
      this._setEditorBaseline(draft)
      toast("工作稿已保存；正式页面尚未变化", "success")
      if (refresh) router.refresh()
      return true
    } catch (err) {
      toast(err.message || "保存失败", "error")
      return false
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
      sections_json: this._readSections(),
    }
  },

  _readSections() {
    return Array.from(document.querySelectorAll(".world-bible-section-editor")).map((node, index) => {
      const field = (name) => node.querySelector(`[data-section-field="${name}"]`)
      const title = field("title")?.value?.trim() || ""
      if (!title) throw new Error(`第 ${index + 1} 个分区标题不能为空`)
      return {
        section_id: node.getAttribute("data-section-id"),
        section_type: field("section_type")?.value || "markdown",
        title,
        body_markdown: field("body_markdown")?.value || "",
        sort_order: (index + 1) * 10,
        linked_asset_ref_hashes: String(field("linked_asset_ref_hashes")?.value || "")
          .split(/\n+/).map((value) => value.trim()).filter(Boolean),
        projection_policy: field("projection_policy")?.value || "eligible",
        sensitivity_hint: field("sensitivity_hint")?.value || "author_safe",
      }
    })
  },

  _captureSectionsFromDom() {
    const source = this._activeDraft || this._activePage
    if (!source) return []
    const title = document.getElementById("bible-title")
    const pageType = document.getElementById("bible-page-type")
    const freeText = document.getElementById("bible-free-text")
    const sortOrder = document.getElementById("bible-sort-order")
    const assetRefs = document.getElementById("bible-asset-refs")
    if (title) source.title = title.value
    if (pageType) source.page_type = pageType.value
    if (freeText) source.free_text = freeText.value
    if (sortOrder) source.sort_order = Number(sortOrder.value || 0)
    if (assetRefs) {
      try {
        source.linked_asset_refs_json = this._parseAssetRefs(assetRefs.value || "")
      } catch (err) {
        toast(err.message || "读取页面引用失败", "error")
      }
    }
    try {
      source.sections_json = this._readSections()
    } catch (err) {
      toast(err.message || "读取分区失败", "error")
    }
    return source.sections_json || []
  },

  _rerenderSectionEditor(source) {
    const current = document.querySelector(".world-bible-sections")
    if (!current || !source) return false
    const wrapper = document.createElement("div")
    wrapper.innerHTML = this._renderSectionEditor(source.sections_json)
    const next = wrapper.firstElementChild
    if (!next) return false
    current.replaceWith(next)
    return true
  },

  _addSection() {
    const source = this._activeDraft || this._activePage
    if (!source) return
    const sections = [...this._captureSectionsFromDom()]
    const used = new Set(sections.map((item) => item.section_id))
    let id = `section_${Date.now().toString(36)}`
    let suffix = 1
    while (used.has(id)) id = `section_${Date.now().toString(36)}_${suffix++}`
    sections.push({
      section_id: id,
      section_type: "markdown",
      title: "新分区",
      body_markdown: "",
      sort_order: (sections.length + 1) * 10,
      linked_asset_ref_hashes: [],
      projection_policy: "eligible",
      sensitivity_hint: "author_safe",
    })
    source.sections_json = sections
    this._rerenderSectionEditor(source)
  },

  _removeSection(actionNode) {
    const source = this._activeDraft || this._activePage
    const card = actionNode.closest(".world-bible-section-editor")
    if (!source || !card) return
    const id = card.getAttribute("data-section-id")
    source.sections_json = this._captureSectionsFromDom().filter((item) => item.section_id !== id)
    this._rerenderSectionEditor(source)
  },

  _moveSection(actionNode, direction) {
    const source = this._activeDraft || this._activePage
    const card = actionNode.closest(".world-bible-section-editor")
    if (!source || !card) return
    const sections = [...this._captureSectionsFromDom()]
    const index = sections.findIndex((item) => item.section_id === card.getAttribute("data-section-id"))
    const next = index + direction
    if (index < 0 || next < 0 || next >= sections.length) return
    const current = sections[index]
    sections[index] = sections[next]
    sections[next] = current
    source.sections_json = sections.map((item, order) => ({ ...item, sort_order: (order + 1) * 10 }))
    this._rerenderSectionEditor(source)
  },

  async _applySelectedPageTemplate() {
    const templateKey = document.getElementById("bible-page-template")?.value || ""
    if (!templateKey) {
      toast("请选择页面模板", "warning")
      return
    }
    try {
      let draft = this._activeDraft || this._draftForPage(this._activePage?.id)
      if (!draft && this._activePage) {
        draft = await api.world.createBibleDraft({
          novel_id: state.currentProjectId,
          page_id: this._activePage.id,
        })
      }
      if (!draft) return
      const selected = this._pageTemplates.find((item) => item.template_key === templateKey)
      draft = await api.world.applyBiblePageTemplate(draft.id, {
        template_key: templateKey,
        template_version: selected?.version_number || 1,
        replace_sections: false,
      }, state.currentProjectId)
      this._activeDraft = draft
      this._drafts = [draft, ...this._drafts.filter((item) => item.id !== draft.id)]
      toast("模板已生成工作稿分区；发布前可继续编辑", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "应用模板失败", "error")
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

  _openPageTemplateManager() {
    const custom = this._pageTemplates.filter((item) => !item.builtin)
    const body = `
      <p class="world-bible-empty-hint">页面模板只定义分区布局和默认值，不保存 Prompt、provider、工具或脚本。</p>
      <div class="world-bible-suggestion-list">
        ${this._pageTemplates.map((item) => `
          <div class="world-bible-suggestion-item">
            <div><strong>${esc(item.name)}</strong> · ${esc(item.template_key)} · v${esc(item.version_number)} ${item.builtin ? "· 内置" : `· ${esc(item.status)}`}</div>
            ${item.builtin ? "" : `<div class="world-bible-suggestion-item__actions">
              <button class="btn btn-sm" data-page-template-rename="${esc(item.id)}">编辑</button>
              <button class="btn btn-sm" data-page-template-history="${esc(item.id)}">历史</button>
            </div>`}
          </div>
        `).join("")}
      </div>
      <hr />
      <div class="form-group"><label>模板 key</label><input class="form-input" id="bible-template-key" placeholder="trade_guide" /></div>
      <div class="form-group"><label>名称</label><input class="form-input" id="bible-template-name" placeholder="贸易资料页" /></div>
      <div class="form-group"><label>默认分区标题</label><input class="form-input" id="bible-template-section-title" placeholder="货币与交换" /></div>
    `
    showModalHtml("页面模板", body, [{
      text: "创建自定义模板",
      class: "btn-primary",
      handler: () => this._createPageTemplateFromModal(),
    }], { size: "large" })
    if (!custom.length) return
    document.querySelectorAll("[data-page-template-rename]").forEach((button) => {
      button.addEventListener("click", () => this._editPageTemplate(button.getAttribute("data-page-template-rename")))
    })
    document.querySelectorAll("[data-page-template-history]").forEach((button) => {
      button.addEventListener("click", () => this._openPageTemplateHistory(button.getAttribute("data-page-template-history")))
    })
  },

  async _createPageTemplateFromModal() {
    const key = document.getElementById("bible-template-key")?.value?.trim() || ""
    const name = document.getElementById("bible-template-name")?.value?.trim() || ""
    const title = document.getElementById("bible-template-section-title")?.value?.trim() || ""
    if (!key || !name || !title) {
      toast("请填写模板 key、名称和默认分区标题", "warning")
      return
    }
    try {
      await api.world.createBiblePageTemplate({
        novel_id: state.currentProjectId,
        template_key: key,
        name,
        default_sections_json: [{
          section_id: `section_${Date.now().toString(36)}`,
          section_type: "markdown",
          title,
          body_markdown: "",
          sort_order: 10,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        }],
      })
      closeModal()
      toast("页面模板已创建", "success")
      await this._load()
      router.refresh()
    } catch (err) {
      toast(err.message || "创建模板失败", "error")
    }
  },

  _editPageTemplate(templateId) {
    const template = this._pageTemplates.find((item) => item.id === templateId && !item.builtin)
    if (!template) return
    const body = `
      <p class="world-bible-empty-hint">稳定键 ${esc(template.template_key)} 不可修改。升级模板不会自动改写已发布页面。</p>
      <div class="form-group"><label>名称</label><input class="form-input" id="bible-template-edit-name" value="${esc(template.name)}" /></div>
      <div class="form-group"><label>说明</label><textarea class="form-textarea" id="bible-template-edit-description" rows="3">${esc(template.description || "")}</textarea></div>
      <label class="bible-ai-toggle"><input id="bible-template-edit-archived" type="checkbox" ${template.status === "archived" ? "checked" : ""} /> 归档模板</label>
    `
    showModalHtml("编辑页面模板", body, [{
      text: "保存新版本",
      class: "btn-primary",
      handler: async () => {
        try {
          await api.world.updateBiblePageTemplate(template.id, {
            base_version_number: template.version_number,
            name: document.getElementById("bible-template-edit-name")?.value?.trim() || template.name,
            description: document.getElementById("bible-template-edit-description")?.value || null,
            status: document.getElementById("bible-template-edit-archived")?.checked ? "archived" : "active",
          }, state.currentProjectId)
          closeModal()
          toast("模板新版本已保存", "success")
          await this._load()
          router.refresh()
        } catch (err) {
          toast(err.message || "更新模板失败", "error")
        }
      },
    }])
  },

  async _openPageTemplateHistory(templateId) {
    const template = this._pageTemplates.find((item) => item.id === templateId)
    if (!template || template.builtin) return
    try {
      const revisions = await api.world.listBiblePageTemplateRevisions(template.id, state.currentProjectId)
      const body = revisions.map((item) => `
        <div class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${esc(item.revision_reason)} · ${esc(item.content_hash.slice(0, 12))}
          <button class="btn btn-sm" data-template-restore-version="${esc(item.version_number)}">恢复为新版本</button>
        </div>
      `).join("") || `<div class="world-bible-empty-hint">暂无历史</div>`
      showModalHtml("模板历史", body, [], { size: "large" })
      document.querySelectorAll("[data-template-restore-version]").forEach((button) => {
        button.addEventListener("click", async () => {
          try {
            await api.world.restoreBiblePageTemplateRevision(
              template.id,
              Number(button.getAttribute("data-template-restore-version")),
              state.currentProjectId,
            )
            closeModal()
            toast("历史模板已恢复为新版本", "success")
            await this._load()
            router.refresh()
          } catch (err) {
            toast(err.message || "恢复模板失败", "error")
          }
        })
      })
    } catch (err) {
      toast(err.message || "加载模板历史失败", "error")
    }
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
      this._synopsisTerminalTaskId = null
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
        this._synopsisTerminalTaskId = taskId
        this._synopsisTask = { task_id: taskId, status: "done" }
        this._synopsis = await api.world.getBibleSynopsis(novelId)
        toast("世界观简介已刷新", "success")
        router.renderCurrentView()
      },
      onFailed: async (progress) => {
        this._synopsisPoller = null
        this._synopsisTerminalTaskId = taskId
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
      if (this._synopsis?.active_task_id) this._synopsisTerminalTaskId = null
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
      this._synopsisTerminalTaskId = null
      this._startSynopsisPolling(this._synopsisTask.task_id)
      toast(this._synopsisTask.existing ? "已取消固定，刷新任务正在运行" : "已取消固定并提交刷新", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "取消固定失败", "error")
    }
  },

  _openInGenerationCenter() {
    const page = this._activePage
    if (!page?.id) return false
    const proceed = () => {
      const query = new URLSearchParams({
        tab: "world",
        source_page_id: page.id,
        target: "world_bible_page",
      })
      router.navigate("generate", null, true, query)
      return true
    }
    if (!this._editorHasUnsavedChanges()) return proceed()
    showModalHtml(
      "保存后进入生成中心",
      `<p>当前页面有未保存修改。生成中心只从服务器读取页面与工作稿，请先保存。</p>`,
      [
        { text: "取消", class: "btn-ghost", handler: closeModal },
        {
          text: "保存并继续",
          class: "btn-primary",
          handler: async () => {
            const saved = await this._savePage({ refresh: false })
            if (!saved) return false
            closeModal()
            return proceed()
          },
        },
      ],
    )
    return false
  },

  _editorHasUnsavedChanges() {
    const source = this._activeDraft || this._activePage
    if (!source || !document.getElementById("bible-title")) return false
    try {
      const current = this._normalizeEditorPayload(this._readDraftEditor())
      const baseline = this._editorBaselineKey === this._editorSourceKey(source)
        ? this._editorBaseline
        : this._normalizeEditorPayload(this._editorPayloadFromSource(source))
      return JSON.stringify(current) !== JSON.stringify(baseline)
    } catch {
      return true
    }
  },

  _confirmDiscardEditorChanges(message) {
    if (!this._editorHasUnsavedChanges()) return true
    if (typeof window.confirm !== "function") return false
    return window.confirm(message)
  },

  _editorSourceKey(source = this._activeDraft || this._activePage) {
    if (!source) return null
    if (source.id && (Object.prototype.hasOwnProperty.call(source, "page_id") || source.base_version_number != null)) {
      return `draft:${source.id}:${source.updated_at || ""}`
    }
    return `page:${source.id || ""}:${source.version_number || 0}`
  },

  _editorPayloadFromSource(source) {
    return {
      title: source?.title || "",
      page_type: source?.page_type || "custom",
      free_text: source?.free_text || "",
      sort_order: Number(source?.sort_order || 0),
      linked_asset_refs_json: source?.linked_asset_refs_json || [],
      sections_json: source?.sections_json || [],
    }
  },

  _normalizeEditorPayload(payload = {}) {
    const sections = Array.isArray(payload.sections_json) ? [...payload.sections_json] : []
    sections.sort((left, right) => Number(left?.sort_order || 0) - Number(right?.sort_order || 0)
      || String(left?.section_id || "").localeCompare(String(right?.section_id || "")))
    return {
      title: String(payload.title || ""),
      page_type: String(payload.page_type || "custom"),
      free_text: String(payload.free_text || ""),
      sort_order: Number(payload.sort_order || 0),
      linked_asset_refs_json: Array.isArray(payload.linked_asset_refs_json)
        ? payload.linked_asset_refs_json
        : [],
      sections_json: sections.map((item, index) => ({
        section_id: item?.section_id || "",
        section_type: item?.section_type || "markdown",
        title: item?.title || "",
        body_markdown: item?.body_markdown || "",
        sort_order: (index + 1) * 10,
        linked_asset_ref_hashes: Array.isArray(item?.linked_asset_ref_hashes)
          ? item.linked_asset_ref_hashes
          : [],
        projection_policy: item?.projection_policy || "eligible",
        sensitivity_hint: item?.sensitivity_hint || "author_safe",
      })),
    }
  },

  _setEditorBaseline(source) {
    this._editorBaselineKey = this._editorSourceKey(source)
    this._editorBaseline = source
      ? this._normalizeEditorPayload(this._editorPayloadFromSource(source))
      : null
  },

  _resetEditorBaseline() {
    this._setEditorBaseline(this._activeDraft || this._activePage)
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
        source_module: "world",
        review_group: "generation_center",
        status: "pending",
      })
      this._suggestions = (data.items || []).filter((item) => (
        item.target_type === "world_bible_page_draft"
      ))
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
    return payload.page?.title || payload.name || this._targetTypeLabel(item.target_type)
  },

  _targetTypeLabel(targetType) {
    return {
      world_bible_page_draft: "世界书整页提案",
      core_entity_draft: "世界对象建议",
      profile_field: "档案字段",
    }[targetType] || targetType || "创设建议"
  },

  _isWorldBiblePageSuggestion(item) {
    return item?.target_type === "world_bible_page_draft"
  },

  _editSuggestionIntoDraft(item) {
    const payload = item.payload_json || {}
    const page = payload.page || {}
    const body = `
      <div class="form-group"><label>标题</label><input class="form-input" id="bible-suggestion-title" value="${esc(page.title || "")}" /></div>
      <div class="form-group"><label>类别</label><select class="form-select" id="bible-suggestion-type">${this._categoryOptions(page.page_type || "custom")}</select></div>
      <div class="form-group">
        <label>页面概览</label>
        <textarea class="form-textarea" id="bible-suggestion-text" rows="8">${esc(page.free_text || "")}</textarea>
      </div>
      <div class="form-group"><label>完整 sections JSON</label><textarea class="form-textarea" id="bible-suggestion-sections" rows="12">${esc(JSON.stringify(page.sections_json || [], null, 2))}</textarea></div>
      <div class="form-group"><label>资产关联 JSON</label><textarea class="form-textarea" id="bible-suggestion-assets" rows="6">${esc(JSON.stringify(page.linked_asset_refs_json || [], null, 2))}</textarea></div>
      <p class="world-bible-empty-hint">应用只写入工作稿；发布前仍可继续编辑或丢弃。</p>
    `
    showModalHtml("编辑创设建议", body, [{
      text: "应用到工作稿",
      class: "btn-primary",
      handler: () => this._applyEditedSuggestion(item),
    }], { size: "large" })
  },

  async _applyEditedSuggestion(item) {
    const text = document.getElementById("bible-suggestion-text")?.value || ""
    let sections
    let assets
    try {
      sections = JSON.parse(
        document.getElementById("bible-suggestion-sections")?.value || "[]",
      )
      assets = JSON.parse(
        document.getElementById("bible-suggestion-assets")?.value || "[]",
      )
    } catch {
      toast("sections 或资产关联不是有效 JSON", "warning")
      return
    }
    try {
      const originalPage = item.payload_json?.page || {}
      const result = await api.generate.applyWorldPageDraft(
        item.id,
        {
          page: {
            ...originalPage,
            title: document.getElementById("bible-suggestion-title")?.value?.trim() || "",
            page_type: document.getElementById("bible-suggestion-type")?.value || "custom",
            free_text: text,
            sections_json: sections,
            linked_asset_refs_json: assets,
          },
        },
        state.currentProjectId,
      )
      closeModal()
      toast("建议已应用到工作稿；正式页面尚未变化", "success")
      await this._load()
      const draftId = result?.draft?.id
      if (draftId) this._openDraft(draftId)
    } catch (err) {
      if (err?.status === 409) {
        toast("来源工作稿已变更，本次提案未覆盖新修改。请重新生成。", "warning")
      } else {
        toast(err.message || "应用建议失败", "error")
      }
    }
  },

  _renderSuggestionPreview(item) {
    const payload = item.payload_json || {}
    const excerpt = payload.page?.free_text || payload.summary || payload.public_info || ""
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
