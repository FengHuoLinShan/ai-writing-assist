/**
 * World Bible / Worldbuilding Workspace v1.
 */
import { pollTaskProgress } from "../shared/workflowProgress.js"

const PROJECTION_TYPE = "context_brief"
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
  { value: "world_object_draft", label: "世界对象草稿" },
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
  _activePage: null,
  _suggestions: [],
  _conflicts: [],
  _task: null,
  _projectionConflictHint: null,
  _projectionPoller: null,
  _beforeUnloadBound: false,
  _aiOpen: false,
  _aiMessages: [],
  _aiOutputTarget: "chat",
  _aiTemplateId: "builtin:none",
  _aiQualityMode: "fast",
  _aiSelectedChapters: "",
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
      const pageNode = e.target.closest("[data-bible-page-id]")
      if (pageNode) {
        this._activePage = this._pages.find((page) => page.id === pageNode.getAttribute("data-bible-page-id")) || null
        router.refresh()
        return
      }
      const actionNode = e.target.closest("[data-action]")
      if (!actionNode) return
      const action = actionNode.getAttribute("data-action")
      if (action === "bible-new-page") this._createPage()
      else if (action === "bible-save-page") this._savePage()
      else if (action === "bible-refresh-projection") this._refreshProjection(false)
      else if (action === "bible-force-refresh-projection") this._refreshProjection(true)
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
  },

  onLeave() {
    this._stopProjectionPolling()
  },

  async _load() {
    const data = await api.world.listBiblePages({ novel_id: state.currentProjectId })
    this._pages = data.items || []
    if (!this._activePage && this._pages.length) this._activePage = this._pages[0]
    if (this._activePage) {
      this._activePage = this._pages.find((page) => page.id === this._activePage.id) || this._activePage
      await this._restoreProjectionTask(this._activePage)
    }
  },

  _renderPageNav() {
    if (!this._pages.length) {
      return `<div class="world-bible-empty-hint">暂无页面</div>`
    }
    return `<div class="world-bible-page-nav">${this._pages.map((page) => `
      <button class="btn btn-sm world-bible-page-btn ${this._activePage?.id === page.id ? "btn-primary" : ""}"
        data-bible-page-id="${esc(page.id)}">
        ${esc(page.title)}
      </button>
    `).join("")}</div>`
  },

  _renderToolbar() {
    const modeLabels = { editor: "编辑", gallery: "图鉴", filter: "筛选" }
    return `
      <div class="world-bible-toolbar">
        <div class="world-bible-toolbar__title">
          <h3>World Bible</h3>
          <span>${esc(this._pages.length)} 个页面</span>
        </div>
        <div class="world-bible-toolbar__modes" aria-label="世界书展示模式">
          ${Object.entries(modeLabels).map(([mode, label]) => `
            <button class="btn btn-sm ${this._displayMode === mode ? "btn-primary" : ""}"
              data-action="bible-set-display-mode" data-mode="${esc(mode)}">${esc(label)}</button>
          `).join("")}
        </div>
        <div class="world-bible-toolbar__actions">
          <button class="btn btn-sm btn-primary" data-action="bible-new-page">新建页面</button>
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
      <div class="world-bible-layout">
        <aside class="panel world-bible-page-nav">
          <div class="world-bible-page-nav__heading">页面</div>
          ${this._renderPageNav()}
        </aside>
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
    const statusClass = `badge-${page.status || "draft"}`
    return `
      <article class="world-bible-page-card" style="--world-bible-type-color:${esc(meta.color)};">
        <div class="world-bible-page-card__band"></div>
        <div class="world-bible-page-card__head">
          <div class="world-bible-page-card__icon">${esc(meta.symbol)}</div>
          <div class="world-bible-page-card__title">
            <h3>${esc(page.title || "未命名页面")}</h3>
            <div class="world-bible-page-card__meta">
              <span>${esc(meta.title)}</span>
              <span class="badge ${esc(statusClass)}">${esc(this._statusLabel(page.status))}</span>
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
    return BIBLE_PAGE_TYPES[type] || {
      ...BIBLE_FALLBACK_TYPE,
      title: type || BIBLE_FALLBACK_TYPE.title,
      label: type || BIBLE_FALLBACK_TYPE.label,
    }
  },

  _statusLabel(status) {
    return {
      canonical: "正史",
      draft: "草稿",
      candidate: "候选",
      deprecated: "废弃",
      pending: "待处理",
      done: "完成",
      failed: "失败",
    }[status] || status || "草稿"
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
    const known = Object.keys(BIBLE_PAGE_TYPES)
      .filter((type) => counts.has(type))
      .map((type) => ({ type, count: counts.get(type), meta: this._typeMeta(type) }))
    const unknown = Array.from(counts.entries())
      .filter(([type]) => !BIBLE_PAGE_TYPES[type])
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
    if (page) this._activePage = page
    this._displayMode = "editor"
    this._galleryCategory = null
    this._persistDisplayPreference("displayMode", "editor")
    router.refresh()
  },

  _renderActivePage() {
    const page = this._activePage
    if (!page) {
      return `<div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div>`
    }
    return `
      <div class="world-bible-panel__header">
        <div>
          <h2>${esc(page.title)}</h2>
          <div class="world-bible-page-meta">${esc(page.page_type)} · ${esc(page.status)}</div>
        </div>
        <div class="world-bible-panel__actions">
          <button class="btn btn-sm" data-action="bible-toggle-ai">${this._aiOpen ? "收起 AI" : "AI 创建/整理"}</button>
          <button class="btn btn-sm btn-primary" data-action="bible-save-page">保存正文</button>
          <button class="btn btn-sm" data-action="bible-refresh-projection">刷新投影</button>
        </div>
      </div>
      <div class="world-bible-editor-layout${this._aiOpen ? " world-bible-editor-layout--with-ai" : ""}">
        <div>
          <textarea class="form-textarea world-bible-editor" id="bible-free-text" rows="16">${esc(page.free_text || "")}</textarea>
          ${this._renderProjectionStatus(page)}
        </div>
        ${this._aiOpen ? this._renderAiSidebar(page) : ""}
      </div>
    `
  },

  _renderAiSidebar(page) {
    return `
      <aside class="bible-ai-sidebar">
        <div>
          <div class="bible-ai-sidebar__title">AI 创建/整理</div>
          <div class="bible-ai-sidebar__hint">生成结果会先进入创设建议，确认后才写入页面或对象草稿。</div>
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
        <label class="bible-ai-field">附带正文（章节序号，用逗号分隔）
          <input id="bible-ai-chapters" class="form-input" value="${esc(this._aiSelectedChapters)}" placeholder="例如：1,2,5" />
        </label>
        <label class="bible-ai-toggle">
          <input id="bible-ai-quality-pro" type="checkbox" ${this._aiQualityMode === "pro" ? "checked" : ""} />
          高质量
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
    if (suggestions.length) {
      return suggestions.map((item) => `
        <div class="bible-ai-result-card">
          <div class="bible-ai-result-card__title">${esc(item.title || this._targetTypeLabel(item.target_type))}</div>
          <div>${esc(this._targetTypeLabel(item.target_type))} · 风险 ${esc(item.risk_level || "medium")}</div>
          ${item.summary ? `<div>${esc(item.summary)}</div>` : ""}
        </div>
      `).join("")
    }
    return result.reply ? `<div class="bible-ai-reply">${esc(result.reply)}</div>` : "已完成。"
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
    const hintHtml = this._projectionConflictHint
      ? `<div class="world-bible-projection-status__hint">${esc(this._projectionConflictHint)}</div>`
      : ""
    return `
      <div class="world-bible-projection-status">
        <div class="world-bible-projection-status__task">投影任务：${esc(task.task_id || task.id || "")}</div>
        <div>状态：${esc(task.status || "pending")} · 进度 ${Math.round((task.progress || 0) * 100)}%</div>
        ${task.error_message ? `<div class="world-bible-projection-status__error">${esc(task.error_message)}</div>` : ""}
        ${hintHtml}
        ${retry}
      </div>
    `
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
          <option value="background">世界基本背景</option>
          <option value="species">种族</option>
          <option value="faction">势力</option>
          <option value="location">地点</option>
          <option value="rule">规则体系</option>
          <option value="item">重要物品</option>
          <option value="secret">秘密</option>
          <option value="custom">自定义</option>
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
            const page = await api.world.createBiblePage({
              novel_id: state.currentProjectId,
              title,
              page_type: document.getElementById("bible-create-type")?.value || "custom",
              status: "draft",
            })
            this._activePage = page
            this._displayMode = "editor"
            this._galleryCategory = null
            this._persistDisplayPreference("displayMode", "editor")
            toast("页面已创建", "success")
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
    if (!page) return
    const freeText = document.getElementById("bible-free-text")?.value || ""
    try {
      this._activePage = await api.world.updateBiblePage(page.id, { free_text: freeText }, state.currentProjectId)
      toast("已保存，投影已标记为需要刷新", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  _toggleAi() {
    this._aiOpen = !this._aiOpen
    router.refresh()
  },

  async _runAi(forcedTarget = null) {
    const page = this._activePage
    if (!page) return
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
          messages: this._aiMessages,
          selected_chapter_indices: this._selectedChapterIndices(),
          quality_mode: this._aiQualityMode,
          template_id: this._aiTemplateId,
          template_version: 1,
          template_variables: {},
          include_current_page: true,
        },
        state.currentProjectId,
      )
      if (response.reply) this._aiMessages.push({ role: "assistant", content: response.reply })
      this._aiResult = response
      toast(outputTarget === "chat" ? "AI 已回复" : "建议已生成，确认后才会写入", "success")
      router.refresh()
    } catch (err) {
      this._aiResult = { error: err.message || "生成失败" }
      toast(err.message || "生成失败", "error")
      router.refresh()
    }
  },

  _selectedChapterIndices() {
    return String(this._aiSelectedChapters || "")
      .split(/[,\s，]+/)
      .map((item) => Number(item.trim()))
      .filter((value) => Number.isInteger(value) && value > 0)
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
    if (!this._suggestions.length) return `<div class="empty-state"><p>暂无待审核建议</p></div>`
    const base = this._suggestionBatchBase()
    return `
      <div class="world-bible-suggestion-list">
        <div class="world-bible-suggestion-header">
          <div class="world-bible-suggestion-meta" data-bible-batch-meta>
            批量范围：${esc(base.review_group)} · ${esc(base.target_type)} · ${esc(base.action_schema)}
          </div>
          <div class="world-bible-suggestion-actions">
            <button class="btn btn-sm btn-primary" data-action="bible-batch-confirm">批量确认</button>
            <button class="btn btn-sm" data-action="bible-batch-reject">批量拒绝</button>
          </div>
        </div>
        ${this._suggestions.map((item) => `
          <div class="world-bible-suggestion-item">
            ${this._renderSuggestionSelector(item, base)}
            <div class="world-bible-suggestion-title">${esc(this._suggestionTitle(item))}</div>
            <div class="world-bible-suggestion-risk">风险：${esc(item.risk_level)} · ${esc(item.action_schema)}</div>
            ${this._renderSuggestionPreview(item)}
            <div class="world-bible-suggestion-item__actions">
              <button class="btn btn-sm btn-primary" data-bible-confirm-suggestion="${esc(item.id)}">确认</button>
              <button class="btn btn-sm" data-bible-reject-suggestion="${esc(item.id)}">拒绝</button>
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
      core_entity_draft: "世界对象草稿",
      profile_field: "档案字段",
    }[targetType] || targetType || "创设建议"
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
      if (accepted) await api.world.confirmSuggestion(id, state.currentProjectId)
      else await api.world.rejectSuggestion(id, state.currentProjectId)
      toast(accepted ? "建议已确认" : "建议已拒绝", "success")
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
