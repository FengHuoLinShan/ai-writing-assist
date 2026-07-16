/**
 * 世界对象视图
 */
import {
  bulkResultMessage,
  clearAllBulkSelections,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  renderBulkToolbar,
  renderSelectionCell,
  renderSelectionHeader,
  runBulkAction,
  selectedItemsFrom,
  syncBulkSelectionUi,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../shared/bulkSelection.js"
import { bindWorkspaceClick, renderActionMenu, bindActionMenus } from "../shared/viewHelper.js"
import {
  displayStateBadgeClass,
  worldAssetDisplay,
} from "../shared/assetDisplayState.js"
import { importAuthorizationNotice, importAuthorizationPayload } from "../shared/importAuthorization.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"
import { createReferencePicker } from "../shared/referencePicker.js"
import { buildMapQuery, buildMapUrl } from "./mapRouteContext.js"
import worldBibleView from "./worldBibleView.js"

const WORLD_FILTER_DEFAULTS = {
  entity_type: "",
  display_state: "active",
  q: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  auto_ingested: "",
  focus: "",
  skip: 0,
  limit: 20,
}

const WORLD_LIST_DEFAULTS = {
  skip: 0,
  limit: 20,
}

const WORLD_CANDIDATE_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  entity_type: "",
  suggested_action: "",
  source: "",
  workflow_id: "",
  scene_index: "",
  source_chapter_index: "",
  confidence_min: "",
  confidence_max: "",
}

const WORLD_ALIAS_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  q: "",
  source: "",
  workflow_id: "",
  scene_index: "",
  source_chapter_index: "",
  confidence_min: "",
  confidence_max: "",
  has_quote: "",
  type_kind: "",
  multi_alias_only: "",
}

const WORLD_RELATION_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  relation_type: "",
  q: "",
  source_chapter_id: "",
  scene_index: "",
  source_chapter_index: "",
  strength_min: "",
  strength_max: "",
  has_quote: "",
  type_kind: "",
  multi_type_only: "",
}

const REVIEW_ALIAS_TYPE_FALLBACK = [
  ["name", "名称"], ["title", "称号"], ["nickname", "昵称"],
  ["alias", "别名"], ["translation", "译名"], ["abbreviation", "缩写"],
].map(([value, label]) => ({ value, label, category: "别名", synonyms: [] }))

const REVIEW_RELATION_TYPE_FALLBACK = [
  ["friend_of", "朋友"], ["enemy_of", "敌人"], ["ally_of", "盟友"],
  ["member_of", "成员"], ["leader_of", "领导者"], ["located_at", "位于"],
  ["contains", "包含"], ["related_to", "相关"],
].map(([value, label]) => ({ value, label, category: "常用", synonyms: [] }))

const WORLD_FILTER_PANEL_DEFAULTS = {
  objects: false,
  "review-objects": false,
  "review-aliases": false,
  "review-relations": false,
}

const WORLD_SUGGESTED_ACTION_LABELS = {
  create_new: "创建新对象",
  link_to_existing: "设为别名",
  alias_of_existing: "设为别名",
  merge_with_existing: "合并到已有对象",
  temporary_only: "设为临时",
  ignore: "忽略",
  needs_user_decision: "需要作者决定",
}

const WORLD_OBJECT_QUERY_KEYS = [
  "entity_type",
  "display_state",
  "q",
  "source",
  "workflow_id",
  "needs_review",
  "auto_ingested",
  "focus",
]

const CUSTOM_ENTITY_TYPE_SENTINEL = "__custom_entity_type__"
const SYSTEM_ENTITY_TYPE_FALLBACK = [
  ["character", "人物"], ["location", "地点"], ["faction", "势力/派系"],
  ["organization", "组织"], ["species", "种族"], ["group", "群体"],
  ["item", "物品"], ["object", "物体"], ["event", "事件"], ["rule", "规则"],
  ["power_system", "力量体系"], ["secret", "秘密/真相"], ["legend", "传说/神话"],
  ["resource", "资源/材料"], ["concept", "概念"], ["creature", "生物/怪物"],
  ["skill", "技能"], ["ability", "能力"], ["artifact", "神器/遗物"], ["other", "其他"],
].map(([value, label]) => ({ value, label, kind: "system" }))

const WORLD_CANDIDATE_QUERY_KEYS = [
  "entity_type",
  "suggested_action",
  "source",
  "workflow_id",
  "scene_index",
  "source_chapter_index",
  "confidence_min",
  "confidence_max",
]

const WORLD_ALIAS_QUERY_KEYS = [
  "q", "source", "workflow_id", "scene_index", "source_chapter_index",
  "confidence_min", "confidence_max", "has_quote", "type_kind", "multi_alias_only",
]

const WORLD_RELATION_QUERY_KEYS = [
  "q", "relation_type", "scene_index", "source_chapter_index", "strength_min",
  "strength_max", "has_quote", "type_kind", "multi_type_only",
]

const worldView = {
  /** @type {Array} */
  _entities: [],

  /** @type {Array} */
  _candidates: [],
  _candidateTotal: 0,
  _candidateLoadError: null,
  _referencePickers: [],

  /** @type {Array} */
  _batches: [],

  _relations: [],
  _relationGroups: [],
  _relationTotal: 0,
  _relationGroupTotal: 0,
  _relationFilters: { ...WORLD_RELATION_FILTER_DEFAULTS },
  _aliases: [],
  _aliasGroups: [],
  _aliasTotal: 0,
  _aliasGroupTotal: 0,
  _aliasFilters: { ...WORLD_ALIAS_FILTER_DEFAULTS },
  _candidateFilters: { ...WORLD_CANDIDATE_FILTER_DEFAULTS },
  _bulkSelections: {},
  _relationReviewDrafts: {},
  _aliasReviewDrafts: {},
  _relationReviewErrors: {},
  _aliasReviewErrors: {},
  _reviewCounts: { objects: 0, aliases: 0, relations: 0 },
  _reviewTypeCatalog: {
    custom_allowed: true,
    alias_types: REVIEW_ALIAS_TYPE_FALLBACK,
    relation_types: REVIEW_RELATION_TYPE_FALLBACK,
  },

  _total: 0,
  _entitiesLoadError: null,
  _rankingFacets: null,
  _rankingContext: null,

  _filters: { ...WORLD_FILTER_DEFAULTS },

  _advancedFiltersOpen: false,
  _filterPanelsOpen: { ...WORLD_FILTER_PANEL_DEFAULTS },
  _objectViewMode: "table",
  _discoveryMode: "hot",

  _entityTypes: [...SYSTEM_ENTITY_TYPE_FALLBACK],

  _statuses: [
    { value: "active", label: "已采用" },
    { value: "review", label: "待处理" },
    { value: "archived", label: "历史" },
  ],

  /** AI 自动识别状态 */
  _autoExtractOpen: false,
  _autoExtractTaskId: null,
  _autoExtractStatus: "就绪",
  _autoExtractTimer: null,
  _autoExtractProgress: null,
  _autoExtractPoller: null,
  _autoExtractMeta: null,
  _fusionTaskId: null,
  _fusionProgress: null,
  _fusionPoller: null,
  _lifecycleEpoch: 0,

  async onEnter() {
    this._entities = []
    this._candidates = []
    this._candidateTotal = 0
    this._batches = []
    this._relations = []
    this._relationGroups = []
    this._relationTotal = 0
    this._relationGroupTotal = 0
    this._aliases = []
    this._aliasGroups = []
    this._aliasTotal = 0
    this._aliasGroupTotal = 0
    this._total = 0
    this._rankingFacets = null
    this._rankingContext = null
    this._relationReviewDrafts = {}
    this._aliasReviewDrafts = {}
    this._relationReviewErrors = {}
    this._aliasReviewErrors = {}
    this._reviewCounts = { objects: 0, aliases: 0, relations: 0 }
    this._loadFilterPanelState()
    clearAllBulkSelections(this)

    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
    this._stopAutoExtractPolling()
    this._stopFusionPolling()

    await this._syncRouteQueryState(state.currentSubView || "objects", { loadOnChange: false })
    this._recoverAutoExtractWorkflow()
    this._recoverFusionWorkflow()
    this._eventsBound = false

    await this._loadEntityTypes()
    await this._loadReviewTypeCatalog()
    await this._loadEntities()
    await this._loadCandidates()
    await this._loadReviewCounts()

    try {
      if (state.currentProjectId) {
        this._batches = await api.world.listEntityBatches({ novel_id: state.currentProjectId })
      }
    } catch {
      this._batches = []
    }
  },

  async _loadEntityTypes() {
    this._entityTypes = [...SYSTEM_ENTITY_TYPE_FALLBACK]
    if (!state.currentProjectId) return
    try {
      const result = await api.world.listEntityTypes(state.currentProjectId)
      if (Array.isArray(result?.items) && result.items.length) {
        const byValue = new Map(
          SYSTEM_ENTITY_TYPE_FALLBACK.map((item) => [item.value, item]),
        )
        for (const item of result.items) byValue.set(item.value, item)
        this._entityTypes = Array.from(byValue.values())
      }
    } catch {
      toast("类型目录加载失败，暂时使用系统类型", "warning")
    }
  },

  async _loadReviewTypeCatalog() {
    this._reviewTypeCatalog = {
      custom_allowed: true,
      alias_types: REVIEW_ALIAS_TYPE_FALLBACK,
      relation_types: REVIEW_RELATION_TYPE_FALLBACK,
    }
    try {
      const catalog = await api.world.getReviewTypeCatalog()
      if (catalog?.alias_types?.length && catalog?.relation_types?.length) {
        this._reviewTypeCatalog = catalog
      }
    } catch {
      // 推荐目录不可用时保留开放字符串和本地常用项，不阻断复核。
    }
  },

  async _loadReviewCounts() {
    if (!state.currentProjectId) return
    try {
      const [objects, aliases, relations] = await Promise.all([
        api.world.listEntities({ novel_id: state.currentProjectId, display_state: "review", skip: 0, limit: 1 }),
        api.world.listAliases({ novel_id: state.currentProjectId, display_state: "review", skip: 0, limit: 1 }),
        api.world.listRelationships({ novel_id: state.currentProjectId, status: "candidate", skip: 0, limit: 1 }),
      ])
      this._reviewCounts = {
        objects: Number(objects?.total || 0),
        aliases: Number(aliases?.total || 0),
        relations: Number(relations?.total || 0),
      }
    } catch {
      this._reviewCounts = {
        objects: this._candidateTotal,
        aliases: this._aliasTotal,
        relations: this._relationTotal,
      }
    }
  },

  _entityTypesWithCurrent(currentType = "") {
    const items = [...this._entityTypes]
    if (currentType && !items.some((item) => item.value === currentType)) {
      items.push({ value: currentType, label: currentType, kind: "custom" })
    }
    return items
  },

  _entityTypeControlHtml(prefix, currentType = "") {
    const items = this._entityTypesWithCurrent(currentType)
    const renderOptions = (kind) => items
      .filter((item) => (item.kind || "system") === kind)
      .map((item) => `<option value="${esc(item.value)}" ${item.value === currentType ? "selected" : ""}>${esc(item.label)}</option>`)
      .join("")
    const systemOptions = renderOptions("system")
    const customOptions = renderOptions("custom")
    return `
      <select class="form-select" id="${prefix}-entity-type">
        <optgroup label="系统类型">${systemOptions}</optgroup>
        ${customOptions ? `<optgroup label="项目自定义类型">${customOptions}</optgroup>` : ""}
        <option value="${CUSTOM_ENTITY_TYPE_SENTINEL}">＋ 新建自定义类型…</option>
      </select>
      <div id="${prefix}-custom-type-wrap" hidden>
        <input class="form-input" id="${prefix}-custom-entity-type" maxlength="64" placeholder="例如：宗教/神祇" />
        <small>自定义类型使用通用对象档案，不自动获得地图、人物或事件等系统类型能力。</small>
      </div>
    `
  },

  _bindEntityTypeControl(prefix) {
    const select = document.getElementById(`${prefix}-entity-type`)
    const wrap = document.getElementById(`${prefix}-custom-type-wrap`)
    if (!select || !wrap) return
    const sync = () => { wrap.hidden = select.value !== CUSTOM_ENTITY_TYPE_SENTINEL }
    select.addEventListener("change", sync)
    sync()
  },

  _readEntityType(prefix) {
    const selected = document.getElementById(`${prefix}-entity-type`)?.value || ""
    if (selected !== CUSTOM_ENTITY_TYPE_SENTINEL) return selected
    return document.getElementById(`${prefix}-custom-entity-type`)?.value?.trim() || ""
  },

  _showEntityTypeBlocker(err, targetId) {
    if (err?.body?.error !== "entity_type_change_blocked") return false
    const blockers = Array.isArray(err.body?.context?.blockers) ? err.body.context.blockers : []
    const detail = blockers.map((item) => `${item.kind}（${item.count}）`).join("、")
    const target = document.getElementById(targetId)
    if (target) {
      target.textContent = `类型变更被阻止：${detail || err.body.detail || "仍有专属依赖"}`
      target.hidden = false
    }
    return true
  },

  _currentQuery() {
    const query = router.getCurrentQuery ? router.getCurrentQuery() : null
    return new URLSearchParams(query?.toString ? query.toString() : "")
  },

  _modePreferenceKey() {
    return `novel_view_mode:${state.currentProjectId || "none"}:world-objects`
  },

  _preferredDiscoveryMode() {
    try {
      const stored = localStorage.getItem(this._modePreferenceKey())
      if (stored === "normal" || stored === "hot") return stored
    } catch {
      // localStorage 不可用时使用产品默认值。
    }
    return "hot"
  },

  _rememberDiscoveryMode(mode) {
    try {
      localStorage.setItem(this._modePreferenceKey(), mode)
    } catch {
      // 偏好写入失败不阻断列表使用。
    }
  },

  _queryPageSkip(query, limit) {
    const page = Math.max(1, Number.parseInt(query.get("page") || "1", 10) || 1)
    return (page - 1) * limit
  },

  _filtersEqual(a, b, keys) {
    return keys.every((key) => String(a[key] ?? "") === String(b[key] ?? ""))
      && Number(a.skip || 0) === Number(b.skip || 0)
      && Number(a.limit || 0) === Number(b.limit || 0)
  },

  _objectFiltersFromQuery(query = this._currentQuery()) {
    const filters = { ...WORLD_FILTER_DEFAULTS }
    for (const key of WORLD_OBJECT_QUERY_KEYS) {
      filters[key] = query.get(key) || filters[key]
    }
    const legacyStatus = query.get("status") || ""
    if (!query.has("display_state") && legacyStatus) {
      if (["canonical", "active", "confirmed"].includes(legacyStatus)) filters.display_state = "active"
      else if (["deprecated", "merged", "ignored", "rolled_back"].includes(legacyStatus)) filters.display_state = "archived"
      else filters.display_state = "review"
    }
    filters.skip = this._queryPageSkip(query, filters.limit)
    return filters
  },

  _candidateFiltersFromQuery(query = this._currentQuery()) {
    const filters = { ...WORLD_CANDIDATE_FILTER_DEFAULTS }
    for (const key of WORLD_CANDIDATE_QUERY_KEYS) {
      filters[key] = query.get(key) || ""
    }
    filters.skip = this._queryPageSkip(query, filters.limit)
    return filters
  },

  _reviewFiltersFromQuery(defaults, keys, query = this._currentQuery()) {
    const filters = { ...defaults }
    for (const key of keys) filters[key] = query.get(key) || ""
    const requestedLimit = Number.parseInt(query.get("page_size") || "20", 10)
    filters.limit = requestedLimit === 50 ? 50 : 20
    filters.skip = this._queryPageSkip(query, filters.limit)
    return filters
  },

  async _syncRouteQueryState(subView = state.currentSubView || "objects", { loadOnChange = false } = {}) {
    const query = this._currentQuery()
    const reviewSubView = this._normalizeReviewSubView(subView)
    if (subView === "objects") {
      const nextFilters = this._objectFiltersFromQuery(query)
      const nextMode = query.get("view") === "card" ? "card" : "table"
      const requestedDiscoveryMode = query.get("mode")
      const nextDiscoveryMode = requestedDiscoveryMode === "normal" || requestedDiscoveryMode === "hot"
        ? requestedDiscoveryMode
        : this._preferredDiscoveryMode()
      if (nextDiscoveryMode === "normal") nextFilters.focus = ""
      const filtersChanged = !this._filtersEqual(this._filters, nextFilters, WORLD_OBJECT_QUERY_KEYS)
      const modeChanged = this._objectViewMode !== nextMode
      const discoveryModeChanged = this._discoveryMode !== nextDiscoveryMode
      this._filters = nextFilters
      this._objectViewMode = nextMode
      this._discoveryMode = nextDiscoveryMode
      if (this._hasAdvancedObjectFilters(nextFilters)) this._advancedFiltersOpen = true
      if (loadOnChange && (filtersChanged || discoveryModeChanged)) await this._loadEntities()
      return filtersChanged || modeChanged || discoveryModeChanged
    }
    if (reviewSubView === "review-objects") {
      const nextFilters = this._candidateFiltersFromQuery(query)
      const filtersChanged = !this._filtersEqual(this._candidateFilters, nextFilters, WORLD_CANDIDATE_QUERY_KEYS)
      this._candidateFilters = nextFilters
      if (loadOnChange && filtersChanged) await this._loadCandidates()
      return filtersChanged
    }
    if (reviewSubView === "review-aliases") {
      const nextFilters = this._reviewFiltersFromQuery(WORLD_ALIAS_FILTER_DEFAULTS, WORLD_ALIAS_QUERY_KEYS, query)
      const filtersChanged = !this._filtersEqual(this._aliasFilters, nextFilters, WORLD_ALIAS_QUERY_KEYS)
      this._aliasFilters = nextFilters
      return filtersChanged
    }
    if (reviewSubView === "review-relations") {
      const nextFilters = this._reviewFiltersFromQuery(WORLD_RELATION_FILTER_DEFAULTS, WORLD_RELATION_QUERY_KEYS, query)
      const filtersChanged = !this._filtersEqual(this._relationFilters, nextFilters, WORLD_RELATION_QUERY_KEYS)
      this._relationFilters = nextFilters
      return filtersChanged
    }
    return false
  },

  _hasAdvancedObjectFilters(filters) {
    return Boolean(
      filters.source
      || filters.workflow_id
      || filters.needs_review
      || filters.auto_ingested,
    )
  },

  _setQueryValue(query, key, value) {
    const normalized = String(value ?? "").trim()
    if (normalized) query.set(key, normalized)
  },

  _objectQueryFromState(filters = this._filters, viewMode = this._objectViewMode) {
    const query = new URLSearchParams()
    for (const key of WORLD_OBJECT_QUERY_KEYS) {
      this._setQueryValue(query, key, filters[key])
    }
    const page = Math.floor((filters.skip || 0) / filters.limit) + 1
    if (page > 1) query.set("page", String(page))
    if (viewMode === "card") query.set("view", "card")
    query.set("mode", this._discoveryMode)
    return query
  },

  _candidateQueryFromState() {
    const query = new URLSearchParams()
    for (const key of WORLD_CANDIDATE_QUERY_KEYS) {
      this._setQueryValue(query, key, this._candidateFilters[key])
    }
    const page = Math.floor((this._candidateFilters.skip || 0) / this._candidateFilters.limit) + 1
    if (page > 1) query.set("page", String(page))
    return query
  },

  _reviewQueryFromState(filters, keys) {
    const query = new URLSearchParams()
    for (const key of keys) this._setQueryValue(query, key, filters[key])
    const page = Math.floor((filters.skip || 0) / filters.limit) + 1
    if (page > 1) query.set("page", String(page))
    if (Number(filters.limit) === 50) query.set("page_size", "50")
    return query
  },

  async _navigateWithQuery(subView, query) {
    await router.navigate("world", subView || state.currentSubView || "objects", true, query)
  },

  async _loadEntities() {
    this._entities = []
    this._total = 0
    this._entitiesLoadError = null
    this._rankingFacets = null
    this._rankingContext = null
    if (!state.currentProjectId) return

    try {
      const params = {
        novel_id: state.currentProjectId,
        skip: this._filters.skip,
        limit: this._filters.limit,
        view_mode: this._discoveryMode,
      }
      if (this._filters.entity_type) params.entity_type = this._filters.entity_type
      params.display_state = this._filters.display_state || "active"
      if (this._filters.q) params.q = this._filters.q
      if (this._filters.source) params.source = this._filters.source
      if (this._filters.workflow_id) params.workflow_id = this._filters.workflow_id
      if (this._filters.needs_review === "true") params.needs_review = true
      if (this._filters.needs_review === "false") params.needs_review = false
      if (this._filters.auto_ingested === "true") params.auto_ingested = true
      if (this._filters.auto_ingested === "false") params.auto_ingested = false
      if (this._discoveryMode === "hot" && this._filters.focus) {
        params.focus = this._filters.focus
      }

      const data = await api.world.listEntities(params)
      this._entities = data.items || data || []
      this._total = data.total ?? this._entities.length
      this._rankingFacets = data.facets ?? null
      this._rankingContext = data.ranking_context ?? null
    } catch (err) {
      this._entities = []
      this._total = 0
      this._entitiesLoadError = err?.message || "加载失败"
      toast("世界对象加载失败，可稍后重试", "warning")
    }
  },

  async _loadCandidates() {
    this._candidates = []
    this._candidateTotal = 0
    this._candidateLoadError = null
    if (!state.currentProjectId) return

    try {
      const params = {
        novel_id: state.currentProjectId,
        display_state: "review",
        skip: this._candidateFilters.skip,
        limit: this._candidateFilters.limit,
      }
      if (this._candidateFilters.entity_type) params.entity_type = this._candidateFilters.entity_type
      if (this._candidateFilters.suggested_action) params.suggested_action = this._candidateFilters.suggested_action
      if (this._candidateFilters.source) params.source = this._candidateFilters.source
      if (this._candidateFilters.workflow_id) params.workflow_id = this._candidateFilters.workflow_id
      if (this._candidateFilters.scene_index != null && this._candidateFilters.scene_index !== "") params.scene_index = Number(this._candidateFilters.scene_index)
      if (this._candidateFilters.source_chapter_index != null && this._candidateFilters.source_chapter_index !== "") params.source_chapter_index = Number(this._candidateFilters.source_chapter_index)
      if (this._candidateFilters.confidence_min != null && this._candidateFilters.confidence_min !== "") params.confidence_min = Number(this._candidateFilters.confidence_min)
      if (this._candidateFilters.confidence_max != null && this._candidateFilters.confidence_max !== "") params.confidence_max = Number(this._candidateFilters.confidence_max)
      const data = await api.world.listEntities(params)
      this._candidates = this._uniqueEntitiesById(data.items || data || [])
      this._candidateTotal = Number(data.total ?? this._candidates.length) || 0
    } catch (err) {
      this._candidates = []
      this._candidateTotal = 0
      this._candidateLoadError = err?.message || "待处理对象加载失败"
      toast("待处理对象加载失败，可重试", "warning")
    }
  },

  async _reloadWorldLists() {
    await Promise.all([
      this._loadEntities(),
      this._loadCandidates(),
    ])
  },

  async _refreshCurrentSubViewInPlace({ preserveScroll = true } = {}) {
    const content = typeof document !== "undefined"
      ? document.getElementById("workspace-content")
      : null
    const scrollTop = preserveScroll && content ? content.scrollTop : 0
    const subView = state.currentSubView || "objects"

    if (subView === "objects") {
      await this._reloadWorldLists()
    } else if (this._normalizeReviewSubView(subView) === "review-objects") {
      await this._loadCandidates()
    }

    if (!content) {
      await router.refresh()
      return
    }

    content.innerHTML = await this.render()
    content.scrollTop = scrollTop
    this._bindEvents()
    content.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
  },

  async _rerenderCurrentSubViewInPlace({ preserveScroll = true } = {}) {
    const content = typeof document !== "undefined"
      ? document.getElementById("workspace-content")
      : null
    if (!content) return
    const scrollTop = preserveScroll ? content.scrollTop : 0
    content.innerHTML = await this.render()
    content.scrollTop = scrollTop
    this._bindEvents()
    content.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
  },

  async _removeCandidateOptimistically(id) {
    const snapshot = {
      candidates: [...this._candidates],
      candidateTotal: this._candidateTotal,
    }
    const before = this._candidates.length
    this._candidates = this._candidates.filter((item) => this._entityId(item) !== id)
    if (this._candidates.length !== before) {
      this._candidateTotal = Math.max(0, this._candidateTotal - 1)
      await this._rerenderCurrentSubViewInPlace()
    }
    return snapshot
  },

  async _restoreCandidateSnapshot(snapshot) {
    if (!snapshot) return
    this._candidates = snapshot.candidates
    this._candidateTotal = snapshot.candidateTotal
    await this._rerenderCurrentSubViewInPlace()
  },

  onLeave() {
    this._lifecycleEpoch += 1
    this._destroyReferencePickers()
    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
    this._stopAutoExtractPolling()
    this._stopFusionPolling()
    worldBibleView.onLeave()
  },

  canLeave() {
    if (state.currentSubView !== "bible") return true
    return worldBibleView.canLeave()
  },

  async render() {
    this._eventsBound = false
    const subView = state.currentSubView || "objects"
    const reviewSubView = this._normalizeReviewSubView(subView)
    await this._syncRouteQueryState(subView, { loadOnChange: true })
    if (this._lastRenderedSubView === "bible" && subView !== "bible") {
      worldBibleView.onLeave()
    }
    this._lastRenderedSubView = subView
    let html = ''

    // 先加载/生成子视图内容，确保标题计数在渲染 header 前已就绪
    let subViewHtml = ''
    if (subView === "objects") {
      subViewHtml = this._renderEntityList()
    } else if (reviewSubView) {
      subViewHtml = await this._renderReviewQueue(reviewSubView)
    } else if (subView === "relations") {
      subViewHtml = await this._renderRelations()
    } else if (subView === "aliases") {
      subViewHtml = await this._renderAliases()
    } else if (subView === "bible") {
      subViewHtml = await worldBibleView.render()
    }

    html += this._renderHeader(subView, reviewSubView)
    html += subViewHtml

    return html
  },

  onRendered() {
    this._bindEvents()
  },

  _normalizeReviewSubView(subView = state.currentSubView || "") {
    if (subView === "candidates") return "review-objects"
    if (["review-objects", "review-aliases", "review-relations"].includes(subView)) {
      return subView
    }
    return ""
  },

  _renderHeaderTitle(subView, reviewSubView) {
    if (subView === "objects") {
      return `<span class="view-header__title">世界对象 <span class="view-header__count">共 ${esc(this._total)} 个</span>${this._renderProjectChip()}</span>`
    }
    if (reviewSubView) {
      let title = "待处理对象"
      let count = this._candidateTotal
      if (reviewSubView === "review-aliases") {
        title = "待处理别名"
        count = this._aliasTotal
      } else if (reviewSubView === "review-relations") {
        title = "待处理关系"
        count = this._relationTotal
      }
      return `<span class="view-header__title">${esc(title)} <span class="view-header__count">共 ${esc(count)} 个</span>${this._renderProjectChip()}</span>`
    }
    if (subView === "relations") {
      return `<span class="view-header__title">关系 <span class="view-header__count">共 ${esc(this._relationTotal)} 个</span>${this._renderProjectChip()}</span>`
    }
    if (subView === "aliases") {
      return `<span class="view-header__title">别名 <span class="view-header__count">共 ${esc(this._aliasTotal)} 个</span>${this._renderProjectChip()}</span>`
    }
    return ""
  },

  _renderHeaderActions(subView, reviewSubView) {
    if (subView === "objects") {
      return `
        ${this._renderDiscoveryModeToggle()}
        <button class="btn btn-sm btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
        <button class="btn btn-sm" data-action="toggle-extract">${this._autoExtractOpen ? "▾" : "▸"} 自动提取</button>
        ${this._renderObjectViewToggle()}
      `
    }
    if (subView === "relations") {
      return `<button class="btn btn-sm btn-primary" data-action="create-relation">新建关系</button>`
    }
    if (subView === "aliases") {
      return `<button class="btn btn-sm btn-primary" data-action="create-alias">新建别名</button>`
    }
    return ""
  },

  _renderHeader(subView = state.currentSubView || "objects", reviewSubView = this._normalizeReviewSubView(subView)) {
    const reviewTotal = Object.values(this._reviewCounts || {}).reduce((sum, value) => sum + Number(value || 0), 0)
    return `
      <div class="view-header view-header--with-tabs world-toolbar">
        <div class="subnav">
          <span class="subnav-item ${subView === "objects" ? "active" : ""}" data-subview="objects" data-action="nav-objects">对象库</span>
          <span class="subnav-item ${reviewSubView ? "active" : ""}" data-subview="review-objects" data-action="nav-review">待处理 (${esc(reviewTotal)})</span>
          <span class="subnav-item ${subView === "relations" ? "active" : ""}" data-subview="relations" data-action="nav-relations">关系</span>
          <span class="subnav-item ${subView === "aliases" ? "active" : ""}" data-subview="aliases" data-action="nav-aliases">别名</span>
          <span class="subnav-item ${subView === "bible" ? "active" : ""}" data-subview="bible" data-action="nav-bible">世界书</span>
          <span class="subnav-item ${subView === "map" ? "active" : ""}" data-subview="map" data-action="nav-map">地图</span>
        </div>
        <div class="view-header__tail">
          ${this._renderHeaderTitle(subView, reviewSubView)}
          <div class="view-header__actions">
            ${this._renderHeaderActions(subView, reviewSubView)}
            <span data-role="smart-dedup-action"></span>
          </div>
        </div>
      </div>
    `
  },

  async _renderReviewQueue(reviewSubView) {
    const tab = reviewSubView || "review-objects"
    await this._loadReviewCounts()
    const counts = this._reviewCounts || {}
    const tabNav = `
      <div class="subnav subnav-secondary" style="margin-bottom:12px;">
        <span class="subnav-item ${tab === "review-objects" ? "active" : ""}" data-action="nav-review-objects">对象 (${esc(counts.objects || 0)})</span>
        <span class="subnav-item ${tab === "review-aliases" ? "active" : ""}" data-action="nav-review-aliases">别名 (${esc(counts.aliases || 0)})</span>
        <span class="subnav-item ${tab === "review-relations" ? "active" : ""}" data-action="nav-review-relations">关系 (${esc(counts.relations || 0)})</span>
      </div>
    `
    if (tab === "review-aliases") return tabNav + await this._renderAliases({ reviewOnly: true })
    if (tab === "review-relations") return tabNav + await this._renderRelations({ reviewOnly: true })
    return tabNav + this._renderCandidatesList({ reviewOnly: true })
  },

  // ============================================================
  // AI 自动识别
  // ============================================================

  _toggleAutoExtract() {
    this._autoExtractOpen = !this._autoExtractOpen
    router.refresh()
  },

  _renderAutoExtractPanel(taskType, label) {
    const isRunning = this._autoExtractTaskId
      && !this._autoExtractProgress?.terminal
      && !this._autoExtractProgress?.failed
    const rangeText = this._autoExtractMeta
      ? `章节 ${this._autoExtractMeta.start_chapter || 1}-${this._autoExtractMeta.end_chapter || 10}`
      : "章节 1-10"
    const progressHtml = this._autoExtractProgress
      ? renderWorkflowCard(this._autoExtractProgress, {
        title: label,
        destinationLabel: `范围: ${rangeText}。完成后查看世界对象、别名和待处理关系。`,
      })
      : `<div id="w-extract-status" class="world-extract-panel__status">状态: ${esc(this._autoExtractStatus)}</div>`
    return `
      <div class="world-extract-panel">
        <div class="world-extract-panel__label">${label}</div>
        <div class="world-extract-panel__controls">
          起始章 <input id="w-extract-start" type="number" min="1" value="1" class="world-extract-panel__input" />
          结束章 <input id="w-extract-end" type="number" min="1" value="10" class="world-extract-panel__input" />
          <button class="btn btn-sm btn-primary" data-action="submit-extract" data-type="${taskType}" ${isRunning ? "disabled" : ""}>
            ${isRunning ? "提取中..." : "确认并开始提取"}
          </button>
        </div>
        <p class="writing-form-hint" role="note">${esc(importAuthorizationNotice())}</p>
        <div id="w-extract-progress" class="world-extract-panel__progress">${progressHtml}</div>
      </div>
    `
  },

  async _submitAutoExtract(taskType) {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const start = parseInt(document.getElementById("w-extract-start")?.value || "1", 10)
    const end = parseInt(document.getElementById("w-extract-end")?.value || "10", 10)
    if (start > end) { toast("起始章节不能大于结束章节", "warning"); return }

    // worldView 面板只提供 world_objects 阶段；保留 taskType 参数便于后续扩展。
    const stage = taskType === "world_object_auto_extraction" ? "world_objects" : taskType
    try {
      const result = await api.imports.startStage(
        stage,
        state.currentProjectId,
        start,
        end,
        false,
        false,
        importAuthorizationPayload(),
      )
      this._autoExtractTaskId = result.task_id
      this._autoExtractStatus = "运行中"
      this._autoExtractMeta = { start_chapter: start, end_chapter: end }
      const workflowType = "world_object_auto_extraction"
      this._autoExtractProgress = normalizeTaskProgress({
        ...result,
        task_type: workflowType,
        meta: this._autoExtractMeta,
      }, workflowType)
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType,
        label: "世界对象与别名/关系自动提取",
        projectId: state.currentProjectId,
        view: "world",
        meta: this._autoExtractMeta,
      })
      this._updateExtractStatusDOM()
      toast("世界对象与别名/关系自动提取任务已提交", "info")
      router.navigate("world", state.currentSubView)

      this._startAutoExtractPolling(result.task_id, workflowType)
    } catch (err) {
      this._autoExtractStatus = `失败: ${err.message}`
      this._updateExtractStatusDOM()
      toast(err.message || "提交失败", "error")
    }
  },

  _normalizeLegacyAutoExtractStorage() {
    try {
      const saved = localStorage.getItem("novel_world_extract_task")
      if (!saved) return
      const parsed = JSON.parse(saved)
      if (parsed?.taskId) {
        this._autoExtractMeta = {
          start_chapter: parsed.start_chapter,
          end_chapter: parsed.end_chapter,
        }
        localStorage.setItem("novel_world_extract_task", parsed.taskId)
      }
    } catch {
      // Plain task-id legacy values are handled by recoverActiveWorkflows.
    }
  },

  _recoverAutoExtractWorkflow() {
    this._normalizeLegacyAutoExtractStorage()
    const workflows = recoverActiveWorkflows(state.currentProjectId)
    const workflow = workflows.find((item) => item.workflowType === "world_object_auto_extraction" && item.view === "world")
      || workflows.find((item) => item.workflowType === "world_object_auto_extraction")
      || workflows.find((item) => item.workflowType === "world_entity_extraction" && item.view === "world")
      || workflows.find((item) => item.workflowType === "world_entity_extraction")
    if (!workflow?.taskId) return
    const workflowType = workflow.workflowType || "world_object_auto_extraction"
    this._autoExtractTaskId = workflow.taskId
    this._autoExtractStatus = "运行中"
    this._autoExtractMeta = workflow.meta || this._autoExtractMeta || null
    this._autoExtractProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflowType)
    this._startAutoExtractPolling(workflow.taskId, workflowType)
  },

  _recoverFusionWorkflow() {
    const workflow = recoverActiveWorkflows(state.currentProjectId)
      .find((item) => item.workflowType === "world_entity_fusion_suggestions")
    if (!workflow?.taskId) return
    this._fusionTaskId = workflow.taskId
    this._fusionProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: "world_entity_fusion_suggestions",
      status: "running",
      meta: workflow.meta || {},
    }, "world_entity_fusion_suggestions")
    this._startFusionPolling(workflow.taskId)
  },

  _stopAutoExtractPolling() {
    if (this._autoExtractPoller?.stop) this._autoExtractPoller.stop()
    this._autoExtractPoller = null
  },

  _stopFusionPolling() {
    if (this._fusionPoller?.stop) this._fusionPoller.stop()
    this._fusionPoller = null
  },

  _renderFusionProgress() {
    if (!this._fusionProgress) return ""
    const result = this._fusionProgress.raw?.result || {}
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions : []
    const suggestionHtml = this._fusionProgress.done && suggestions.length ? `
      <div class="world-extract-panel__suggestion">
        <span class="world-text-dim">${esc(suggestions.length)} 条建议可查看</span>
        <button class="btn btn-sm btn-primary" data-action="show-entity-fusion-suggestions">查看建议</button>
      </div>
    ` : ""
    return `<div style="margin-bottom:12px;">${renderWorkflowCard(this._fusionProgress, {
      title: "世界对象 AI 合并建议",
      destinationLabel: "完成后可选择合并或登记别名",
    })}${suggestionHtml}</div>`
  },

  async _startEntityFusionSuggestions() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      const result = await api.world.createEntityFusionSuggestions({
        novel_id: state.currentProjectId,
        entity_type: this._filters.entity_type || undefined,
      })
      this._fusionTaskId = result.task_id
      this._fusionProgress = normalizeTaskProgress({
        ...result,
        task_type: "world_entity_fusion_suggestions",
      }, "world_entity_fusion_suggestions")
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "world_entity_fusion_suggestions",
        label: "世界对象 AI 合并建议",
        projectId: state.currentProjectId,
        view: "world",
      })
      toast("世界对象 AI 合并建议任务已提交", "success")
      this._startFusionPolling(result.task_id)
      router.renderCurrentView()
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  _startFusionPolling(taskId) {
    this._stopFusionPolling()
    this._fusionPoller = pollTaskProgress({
      taskId,
      workflowType: "world_entity_fusion_suggestions",
      apiClient: api,
      onUpdate: (progress) => {
        this._fusionProgress = progress
        router.renderCurrentView()
      },
      onDone: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._fusionTaskId = null
        this._fusionProgress = progress
        toast("世界对象 AI 合并建议已生成", "success")
        router.renderCurrentView()
      },
      onFailed: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._fusionTaskId = null
        this._fusionProgress = progress
        toast(`世界对象 AI 合并建议失败: ${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
  },

  _startAutoExtractPolling(taskId, taskType = "world_object_auto_extraction") {
    this._stopAutoExtractPolling()
    this._autoExtractPoller = pollTaskProgress({
      taskId,
      workflowType: taskType,
      apiClient: api,
      onUpdate: (progress) => {
        this._autoExtractProgress = progress
        this._autoExtractStatus = progress.statusLabel || progress.status || "运行中"
        this._updateExtractStatusDOM()
      },
      onDone: async (progress) => {
        await this._handleAutoExtractTerminal(progress)
      },
      onFailed: async (progress) => {
        await this._handleAutoExtractTerminal(progress)
      },
    })
  },

  async _pollAutoExtract(taskId) {
    try {
      const data = await api.tasks.get(taskId)
      const progress = normalizeTaskProgress(data, data.task_type || "world_object_auto_extraction")
      this._autoExtractProgress = progress
      this._autoExtractStatus = progress.statusLabel || data.status || "未知"
      this._updateExtractStatusDOM()

      if (progress.terminal) {
        await this._handleAutoExtractTerminal(progress)
      }
    } catch {
      // 轮询失败不中断
    }
  },

  async _handleAutoExtractTerminal(progress) {
    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
    this._stopAutoExtractPolling()
    clearActiveWorkflow(progress.taskId || this._autoExtractTaskId)
    try { localStorage.removeItem("novel_world_extract_task") } catch {}

    if (progress.done) {
      toast("世界对象与别名/关系自动提取已完成", "success")
      this._autoExtractTaskId = null
      await this._reloadWorldLists()
      try {
        if (state.currentProjectId) {
          this._batches = await api.world.listEntityBatches({ novel_id: state.currentProjectId })
        }
      } catch {}
      router.navigate("world", state.currentSubView)
      return
    }

    if (progress.failed || progress.cancelled) {
      this._autoExtractTaskId = null
      const message = progress.cancelled ? "提取任务已取消" : `提取任务失败: ${progress.errorMessage || "未知错误"}`
      toast(message, progress.cancelled ? "warning" : "error")
    }
  },

  _updateExtractStatusDOM() {
    const progressEl = document.getElementById("w-extract-progress")
    if (progressEl && this._autoExtractProgress) {
      const rangeText = this._autoExtractMeta
        ? `范围: 章节 ${this._autoExtractMeta.start_chapter || 1}-${this._autoExtractMeta.end_chapter || 10}。完成后查看世界对象、别名和待处理关系。`
        : "完成后查看世界对象、别名和待处理关系。"
      progressEl.innerHTML = renderWorkflowCard(this._autoExtractProgress, {
        title: "世界对象与别名/关系自动提取",
        destinationLabel: rangeText,
      })
      return
    }
    const el = document.getElementById("w-extract-status")
    if (el) {
      const prefix = this._autoExtractTaskId ? `任务 ${this._autoExtractTaskId.slice(0, 8)}... — ` : "状态: "
      el.textContent = prefix + this._autoExtractStatus
    }
  },

  _renderEntityList() {
    const extractLabel = "世界对象与别名/关系自动提取"
    const extractDrawer = this._autoExtractOpen
      ? `<div class="world-extract-drawer">${this._renderAutoExtractPanel("world_object_auto_extraction", extractLabel)}</div>`
      : ""

    const hotOverview = this._discoveryMode === "hot" ? this._renderHotOverview() : ""
    if (this._entities.length === 0) {
      return `${extractDrawer}${this._renderFilters()}
        ${hotOverview}
        ${this._entitiesLoadError ? `
          <div class="empty-state" role="alert">
            <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
            <p>世界对象加载失败</p>
            <p class="world-text-dim">可稍后重试。错误信息：${esc(this._entitiesLoadError)}</p>
          </div>
        ` : `
        <div class="empty-state">
          <div class="empty-icon">&#127758;</div>
          <p>还没有世界对象。</p>
          <p>世界对象是小说世界中的核心创作资产，包括地点、组织、物品、事件等。</p>
          <div class="actions">
            <button class="btn btn-primary" data-action="new">手动新建对象</button>
          </div>
        </div>
        `}
      `
    }

    let html = `${extractDrawer}`

    html += this._renderFilters()
    html += hotOverview

    if (this._discoveryMode === "hot") {
      html += this._renderEntityCollection(this._entities, { showNewBadge: false })
      html += this._renderPagination()
      return html
    }

    // 判断是否有自动入库批次
    const hasBatches = this._batches && this._batches.length > 0

    if (hasBatches) {
      // 收集所有自动入库实体的 ID
      const autoIngestedIds = new Set()
      const batchEntityIds = new Map() // entity_id -> { batch_id, ingested_at }
      for (const batch of this._batches) {
        for (const entity of (batch.entities || [])) {
          autoIngestedIds.add(entity.id)
          batchEntityIds.set(entity.id, {
            batch_id: batch.batch_id,
            ingested_at: batch.ingested_at,
          })
        }
      }

      // 分两组：自动入库 vs 手动/其他
      const autoEntities = []
      const manualEntities = []
      for (const e of this._entities) {
        const eid = e.id || e.entity_id
        if (autoIngestedIds.has(eid)) {
          autoEntities.push(e)
        } else {
          manualEntities.push(e)
        }
      }

      // 渲染自动入库批次折叠区
      if (autoEntities.length > 0) {
        html += `<div class="world-batch-group">`
        html += `<details open class="world-batch-group__details">`
        html += `<summary class="world-batch-group__summary">
          <span class="world-batch-group__star">&#9733;</span> 自动入库 — ${this._renderBatchTime(this._batches[0]?.ingested_at)} — ${autoEntities.length} 个对象
        </summary>`
        html += this._renderEntityCollection(autoEntities, { showNewBadge: true })
        html += `</details></div>`
      }

      // 渲染手动创建区
      if (manualEntities.length > 0) {
        html += `<div class="world-batch-group">`
        html += `<details ${autoEntities.length === 0 ? "open" : ""} class="world-batch-group__details">`
        html += `<summary class="world-batch-group__summary">
          其他对象 — ${manualEntities.length} 个
        </summary>`
        html += this._renderEntityCollection(manualEntities, { showNewBadge: false })
        html += `</details></div>`
      }
    } else {
      html += this._renderEntityCollection(this._entities, { showNewBadge: false })
    }

    html += this._renderPagination()
    return html
  },

  _renderFilters() {
    const typeOptions = [
      `<option value="">全部类型</option>`,
      ...this._entityTypes.map((t) => `<option value="${esc(t.value)}" ${this._filters.entity_type === t.value ? "selected" : ""}>${esc(t.label)}</option>`),
    ].join("")
    const statusOptions = [
      ...this._statuses.map((s) => `<option value="${esc(s.value)}" ${this._filters.display_state === s.value ? "selected" : ""}>${esc(s.label)}</option>`),
    ].join("")
    const sourceOptions = [
      `<option value="">全部来源</option>`,
      `<option value="deep_import" ${this._filters.source === "deep_import" ? "selected" : ""}>深度导入</option>`,
      `<option value="manual" ${this._filters.source === "manual" ? "selected" : ""}>手动</option>`,
      `<option value="ai_generated" ${this._filters.source === "ai_generated" ? "selected" : ""}>AI 生成</option>`,
    ].join("")
    const advancedFilters = this._advancedFiltersOpen ? `
      <select class="form-select" id="filter-source" aria-label="来源筛选">${sourceOptions}</select>
      <details class="world-diagnostic-filter" ${this._filters.workflow_id ? "open" : ""}>
        <summary>诊断筛选</summary>
        <input class="form-input" id="filter-workflow-id" data-diagnostic-field value="${esc(this._filters.workflow_id || "")}" placeholder="workflow_id" aria-label="Workflow ID 筛选" />
      </details>
      <select class="form-select" id="filter-needs-review" aria-label="注意原因筛选">
        <option value="">全部注意原因</option>
        <option value="true" ${this._filters.needs_review === "true" ? "selected" : ""}>需要人工检查</option>
        <option value="false" ${this._filters.needs_review === "false" ? "selected" : ""}>无注意项</option>
      </select>
      <select class="form-select" id="filter-auto-ingested" aria-label="入库方式筛选">
        <option value="">全部入库方式</option>
        <option value="true" ${this._filters.auto_ingested === "true" ? "selected" : ""}>自动入库</option>
        <option value="false" ${this._filters.auto_ingested === "false" ? "selected" : ""}>非自动入库</option>
      </select>
    ` : ""
    const content = `
      <div class="world-object-filters">
        <select class="form-select" id="filter-entity-type" aria-label="对象类型筛选">${typeOptions}</select>
        <select class="form-select" id="filter-display-state" aria-label="对象状态筛选">${statusOptions}</select>
        <input class="form-input world-object-filters__search" id="filter-q" type="search" placeholder="模糊搜索名称、别名或描述" value="${esc(this._filters.q)}" aria-label="模糊搜索名称、别名或描述" />
        <button class="btn btn-sm" data-action="toggle-advanced-filters">${this._advancedFiltersOpen ? "▾" : "▸"} 高级</button>
        <button class="btn btn-sm btn-primary" data-action="apply-filters">应用</button>
        <button class="btn btn-sm" data-action="reset-filters">重置</button>
        ${advancedFilters}
      </div>
    `
    return this._renderFilterPanel(
      "objects",
      content,
      this._filters.display_state !== "active"
        || WORLD_OBJECT_QUERY_KEYS.some((key) => key !== "display_state" && Boolean(this._filters[key])),
    )
  },

  _renderFilterPanel(key, content, hasActiveFilters = false) {
    const open = this._filterPanelsOpen?.[key] === true
    const panelId = `world-filter-panel-${key}`
    return `
      <section class="world-filter-panel" data-filter-panel="${esc(key)}">
        <button
          type="button"
          class="btn btn-sm world-filter-panel__toggle"
          data-action="toggle-filter-panel"
          data-filter-key="${esc(key)}"
          aria-expanded="${open ? "true" : "false"}"
          aria-controls="${esc(panelId)}"
        >
          <span aria-hidden="true">${open ? "▾" : "▸"}</span>
          <span data-filter-toggle-label>${open ? "收起筛选" : "展开筛选"}</span>
          ${hasActiveFilters ? '<span class="world-filter-panel__active">已筛选</span>' : ""}
        </button>
        <div id="${esc(panelId)}" class="world-filter-panel__body" ${open ? "" : "hidden"}>
          ${content}
        </div>
      </section>
    `
  },

  _renderObjectViewToggle() {
    return `
      <span class="world-object-view-toggle" aria-label="对象库视图">
        <button class="btn btn-sm ${this._objectViewMode === "table" ? "btn-primary" : ""}" data-action="set-object-view" data-view-mode="table">表格</button>
        <button class="btn btn-sm ${this._objectViewMode === "card" ? "btn-primary" : ""}" data-action="set-object-view" data-view-mode="card">卡片</button>
      </span>
    `
  },

  _renderDiscoveryModeToggle() {
    return `
      <span class="world-discovery-mode-toggle" aria-label="对象检索模式">
        <button class="btn btn-sm ${this._discoveryMode === "normal" ? "btn-primary" : ""}" data-action="set-discovery-mode" data-mode="normal">普通</button>
        <button class="btn btn-sm ${this._discoveryMode === "hot" ? "btn-primary" : ""}" data-action="set-discovery-mode" data-mode="hot">热点</button>
      </span>
    `
  },

  _renderHotOverview() {
    const facets = this._rankingFacets || {}
    const context = this._rankingContext || {}
    const statusLabel = {
      ready: `热点索引已覆盖 ${context.covered_chapters ?? 0} 章`,
      partial: `热点索引回填中：已覆盖 ${context.covered_chapters ?? 0} / ${context.total_chapters ?? 0} 章`,
      unavailable: "近期出场索引暂不可用，当前按长期重要性排序",
    }[context.status] || "正在读取热点概览"
    const chips = [
      ["important", "重要", facets.important ?? 0],
      ["hot", "近期热点", facets.hot ?? 0],
      ["other", "其他", facets.other ?? 0],
    ]
    const typeChips = (facets.by_type || []).slice(0, 8)
    return `
      <section class="world-hot-overview" aria-label="对象热点概览">
        <div class="world-hot-overview__facets">
          ${chips.map(([value, label, count]) => `
            <button class="world-hot-facet ${this._filters.focus === value ? "active" : ""}" data-action="set-hot-focus" data-focus="${value}">
              <span>${label}</span><strong>${esc(count)}</strong>
            </button>
          `).join("")}
        </div>
        ${typeChips.length ? `<div class="world-hot-overview__types" aria-label="对象类型聚合">
          ${typeChips.map((item) => `
            <button class="world-hot-type ${this._filters.entity_type === item.entity_type ? "active" : ""}" data-action="set-hot-type" data-entity-type="${esc(item.entity_type)}">
              ${esc(this._entityTypes.find((type) => type.value === item.entity_type)?.label || item.entity_type)} · ${esc(item.count)}
            </button>
          `).join("")}
        </div>` : ""}
        <p class="world-hot-overview__status" data-status="${esc(context.status || "unknown")}">${esc(statusLabel)}</p>
      </section>
    `
  },

  _renderRankingBadges(entity) {
    const ranking = entity.ranking
    if (!ranking) return ""
    const labels = (ranking.labels || []).map((label) => `
      <span class="badge ${label === "hot" ? "badge-warning" : "badge-info"}">${label === "hot" ? "近期热点" : "重要"}</span>
    `).join("")
    const last = ranking.last_appearance_chapter == null ? "无近期出场" : `最近第 ${ranking.last_appearance_chapter} 章`
    return `<span class="world-ranking-badges" title="综合分 ${esc(ranking.combined_score ?? 0)}；${esc(last)}">${labels}</span>`
  },

  _renderEntityCollection(entities, options) {
    return this._objectViewMode === "card"
      ? this._renderEntityCards(entities, options)
      : this._renderEntityTable(entities, options)
  },

  _renderPagination() {
    return this._renderPager({
      total: this._total,
      skip: this._filters.skip,
      limit: this._filters.limit,
      prevAction: "prev-page",
      nextAction: "next-page",
    })
  },

  _renderPager({ total, skip, limit, prevAction, nextAction }) {
    if (total <= limit) return ""
    const currentPage = Math.floor(skip / limit) + 1
    const totalPages = Math.ceil(total / limit)
    const prevDisabled = skip <= 0 ? "disabled" : ""
    const nextDisabled = skip + limit >= total ? "disabled" : ""
    return `
      <div class="world-pagination">
        <button class="btn btn-sm" data-action="${esc(prevAction)}" ${prevDisabled}>上一页</button>
        <span class="world-pagination__info">第 ${currentPage} / ${totalPages} 页，共 ${esc(total)} 条</span>
        <button class="btn btn-sm" data-action="${esc(nextAction)}" ${nextDisabled}>下一页</button>
      </div>
    `
  },

  _renderProjectChip() {
    const title = state.currentProject?.title || state.currentProject?.name
    if (!title) return ""
    return `<span class="view-toolbar__project" title="${esc(title)}">${esc(title)}</span>`
  },

  _formatBatchTime(isoStr) {
    if (!isoStr) return ""
    try {
      const d = new Date(isoStr)
      if (Number.isNaN(d.getTime())) return isoStr
      const now = new Date()
      const diffMs = now.getTime() - d.getTime()
      const pad = (n) => String(n).padStart(2, "0")
      const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
      if (diffMs >= 0 && diffMs < 60 * 1000) return "刚刚"
      if (diffMs >= 0 && diffMs < 60 * 60 * 1000) return `${Math.max(1, Math.floor(diffMs / (60 * 1000)))} 分钟前`
      if (diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000) return `${Math.max(1, Math.floor(diffMs / (60 * 60 * 1000)))} 小时前`
      const yesterday = new Date(now)
      yesterday.setDate(now.getDate() - 1)
      if (
        d.getFullYear() === yesterday.getFullYear()
        && d.getMonth() === yesterday.getMonth()
        && d.getDate() === yesterday.getDate()
      ) {
        return `昨天 ${time}`
      }
      if (d.getFullYear() === now.getFullYear()) {
        return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
      }
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
    } catch { return isoStr }
  },

  _formatBatchTimeFull(isoStr) {
    if (!isoStr) return ""
    try {
      const d = new Date(isoStr)
      if (Number.isNaN(d.getTime())) return isoStr
      const pad = (n) => String(n).padStart(2, "0")
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    } catch { return isoStr }
  },

  _isFreshBatch(isoStr) {
    if (!isoStr) return false
    const d = new Date(isoStr)
    if (Number.isNaN(d.getTime())) return false
    const diffMs = Date.now() - d.getTime()
    return diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000
  },

  _renderBatchTime(isoStr) {
    if (!isoStr) return ""
    const label = this._formatBatchTime(isoStr)
    const title = this._formatBatchTimeFull(isoStr)
    const freshDot = this._isFreshBatch(isoStr) ? `<span class="world-batch-fresh-dot" aria-label="新鲜入库"></span>` : ""
    return `<span class="world-batch-time" title="${esc(title)}">${freshDot}${esc(label)}</span>`
  },

  _renderEntityTable(entities, { showNewBadge }) {
    const scope = "world-objects"
    const visibleIds = this._visibleIdsForBulkScope(scope)
    reconcileBulkSelection(this, scope, visibleIds)
    let html = `<table class="data-table table-card-list world-table--no-top-border">
      <thead>
        <tr>
          <th class="selection-cell">${renderSelectionHeader(this, scope, visibleIds, "全选当前页对象")}</th>
          <th>状态</th>
          <th>类型</th>
          <th>名称</th>
          <th>来源</th>
          <th>注意</th>
          <th>重要度</th>
          <th>摘要</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
    `

    for (const e of entities) {
      const display = worldAssetDisplay({ ...e, status: e.status || "canonical" })
      const statusClass = displayStateBadgeClass(display.displayState)
      const sourceText = { deep_import: "深度导入", manual: "手动", ai_generated: "AI 生成" }
      const needsReview = this._entityNeedsReview(e)
      const attentionText = display.attentionReasons.join("、") || "—"
      const isNew = showNewBadge ? ' <span class="badge badge-new">新</span>' : ""
      const isCharacter = (e.entity_type === "character" || e.entity_type === "character_ref")
      const isSuggestionShadow = this._isSuggestionShadow(e)
      const canMerge = !isSuggestionShadow && (e.status === "draft" || e.status === "candidate")
      const canPromote = e.status === "draft" || e.status === "candidate"
      const id = this._entityId(e)
      const reviewAction = this._renderEntityReviewAction(e)
      html += `
        <tr data-id="${esc(id)}" class="clickable">
          <td class="selection-cell">${renderSelectionCell(this, scope, id, `选择 ${e.name || "对象"}`)}</td>
          <td data-label="状态"><span class="badge ${esc(statusClass)}">${esc(display.label)}</span></td>
          <td data-label="类型" class="world-table-cell--type">${esc(e.entity_type || "-")}</td>
          <td data-label="名称">${esc(e.name)}${isNew}${this._renderRankingBadges(e)}</td>
          <td data-label="来源" class="world-table-cell--muted">${esc(sourceText[e.source] || e.source || "-")}</td>
          <td data-label="注意" class="${needsReview ? "world-table-cell--warning" : "world-table-cell--muted"}">${esc(attentionText)}</td>
          <td data-label="重要度">${esc(e.importance ?? e.importance_score ?? "-")}</td>
          <td data-label="摘要" class="world-table-cell--muted world-table-cell--ellipsis">${esc(e.summary || e.public_info || "-")}</td>
          <td data-label="操作">
            <div class="row-actions">
              ${reviewAction}
              <button class="btn btn-sm btn-primary" data-action="edit-entity" data-id="${esc(id)}">${canPromote ? "编辑后采用" : "编辑"}</button>
              ${canMerge ? `<button class="btn btn-sm" data-action="merge-entity" data-id="${esc(id)}">合并</button>` : ""}
              ${renderActionMenu(`entity-actions-${esc(id)}`, [
                { action: "open-entity-map", label: "打开地图", data: { id } },
                ...(canPromote ? [{ action: "promote-entity", label: "采用", data: { id } }] : []),
                ...(!isSuggestionShadow ? [{ action: "rollback-entity", label: "回滚", data: { id } }] : []),
                ...(isCharacter ? [{ action: "knowledge-entity", label: "知识", data: { id } }] : []),
                { action: "delete-entity", label: isSuggestionShadow ? "忽略" : "删除", class: "danger", data: { id } },
              ])}
            </div>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html = renderBulkToolbar(this, scope, [
      ...(this._filters.display_state === "active" ? [
        { action: "fuse-entities", label: "融合", className: "btn-primary" },
        { action: "alias-entities", label: "标记为别名", className: "btn-primary" },
      ] : []),
      { action: "delete-entities", label: "批量删除", className: "btn-danger" },
    ], {
      noun: "对象",
      hint: "仅作用于当前页选中对象",
      selectAllIds: visibleIds,
      selectAllLabel: "全选当前页对象",
    }) + html
    return html
  },

  _renderEntityCards(entities, { showNewBadge }) {
    const scope = "world-objects"
    const visibleIds = this._visibleIdsForBulkScope(scope)
    reconcileBulkSelection(this, scope, visibleIds)
    const cards = entities.map((entity) => this._renderEntityCard(entity, { showNewBadge })).join("")
    return renderBulkToolbar(this, scope, [
      ...(this._filters.display_state === "active" ? [
        { action: "fuse-entities", label: "融合", className: "btn-primary" },
        { action: "alias-entities", label: "标记为别名", className: "btn-primary" },
      ] : []),
      { action: "delete-entities", label: "批量删除", className: "btn-danger" },
    ], {
      noun: "对象",
      hint: "仅作用于当前页选中对象",
      selectAllIds: visibleIds,
      selectAllLabel: "全选当前页对象",
    }) + `
      <div class="world-object-card-grid">
        ${cards}
      </div>
    `
  },

  _renderEntityCard(entity, { showNewBadge }) {
    const scope = "world-objects"
    const id = this._entityId(entity)
    const display = worldAssetDisplay({ ...entity, status: entity.status || "canonical" })
    const typeLabel = this._entityTypes.find((item) => item.value === entity.entity_type)?.label || entity.entity_type || "-"
    const statusClass = displayStateBadgeClass(display.displayState)
    const isNew = showNewBadge ? '<span class="badge badge-new">新</span>' : ""
    const isSuggestionShadow = this._isSuggestionShadow(entity)
    const canMerge = !isSuggestionShadow && (entity.status === "draft" || entity.status === "candidate")
    const canPromote = entity.status === "draft" || entity.status === "candidate"
    const isCharacter = entity.entity_type === "character" || entity.entity_type === "character_ref"
    const reviewAction = this._renderEntityReviewAction(entity)
    return `
      <article class="world-object-card" data-id="${esc(id)}">
        <div class="world-object-card__top">
          <div class="world-object-card__avatar" style="background:${esc(this._entityAvatarColor(entity))};">
            ${esc((entity.name || "?").slice(0, 1))}
          </div>
          <div class="world-object-card__identity">
            <h3>${esc(entity.name || "未命名对象")} ${isNew}</h3>
            <div class="world-object-card__meta">
              <span>${esc(typeLabel)}</span>
              <span class="badge ${esc(statusClass)}">${esc(display.label)}</span>
              ${this._renderRankingBadges(entity)}
            </div>
          </div>
          <div class="world-object-card__selection">
            ${renderSelectionCell(this, scope, id, `选择 ${entity.name || "对象"}`)}
          </div>
        </div>
        <p class="world-object-card__summary">${esc(entity.summary || entity.public_info || "暂无摘要")}</p>
        <div class="world-object-card__facts">
          <span>来源：${esc({ deep_import: "深度导入", manual: "手动", ai_generated: "AI 生成" }[entity.source] || entity.source || "-")}</span>
          ${display.attentionReasons.length ? `<span>注意：${esc(display.attentionReasons.join("、"))}</span>` : ""}
          <span>重要度：${esc(entity.importance ?? entity.importance_score ?? "-")}</span>
          ${entity.ranking ? `<span>综合分：${esc(entity.ranking.combined_score ?? 0)} · 近十二章 ${esc(entity.ranking.recent_12_chapter_occurrences ?? 0)} 次</span>` : ""}
        </div>
        <div class="world-object-card__actions">
          ${reviewAction}
          <button class="btn btn-sm btn-primary" data-action="edit-entity" data-id="${esc(id)}">${canPromote ? "编辑后采用" : "编辑"}</button>
          <button class="btn btn-sm" data-action="open-entity-map" data-id="${esc(id)}">地图</button>
          ${canMerge ? `<button class="btn btn-sm" data-action="merge-entity" data-id="${esc(id)}">合并</button>` : ""}
          ${renderActionMenu(`entity-card-actions-${esc(id)}`, [
            ...(canPromote ? [{ action: "promote-entity", label: "采用", data: { id } }] : []),
            ...(!isSuggestionShadow ? [{ action: "rollback-entity", label: "回滚", data: { id } }] : []),
            ...(isCharacter ? [{ action: "knowledge-entity", label: "知识", data: { id } }] : []),
            { action: "delete-entity", label: isSuggestionShadow ? "忽略" : "删除", class: "danger", data: { id } },
          ])}
        </div>
      </article>
    `
  },

  _entityAvatarColor(entity) {
    const source = `${entity?.entity_type || ""}:${entity?.name || ""}`
    let hash = 0
    for (let i = 0; i < source.length; i++) {
      hash = ((hash << 5) - hash) + source.charCodeAt(i)
      hash |= 0
    }
    const hue = Math.abs(hash) % 360
    return `hsl(${hue} 58% 38%)`
  },

  _entityId(entity) {
    return entity?.id || entity?.entity_id || ""
  },

  _suggestionId(entity) {
    const meta = entity?.content_json?._meta || {}
    if (!["draft", "candidate"].includes(entity?.status)) return ""
    if (meta.compatibility_shadow !== true) return ""
    return String(meta.suggestion_id || "")
  },

  _isSuggestionShadow(entity) {
    return Boolean(this._suggestionId(entity))
  },

  _uniqueEntitiesById(entities) {
    const seen = new Set()
    const unique = []
    for (const entity of entities || []) {
      const id = this._entityId(entity)
      if (!id || seen.has(id)) continue
      seen.add(id)
      unique.push(entity)
    }
    return unique
  },

  _renderEntityReviewAction(entity) {
    const id = this._entityId(entity)
    if (!id) return ""
    if (this._isSuggestionShadow(entity)) return ""
    if (this._entityNeedsReview(entity)) {
      return `<button class="btn btn-sm btn-primary" data-action="mark-entity-reviewed" data-id="${esc(id)}">标记已检查</button>`
    }
    return ""
  },

  _entityNeedsReview(entity) {
    return entity?.needs_review === true
      || entity?.content_json?._meta?.needs_review === true
  },

  _entityReviewContent(entity, reviewed, reviewedFrom = "world_objects") {
    const content = { ...(entity?.content_json || {}) }
    const meta = { ...(content._meta || {}) }
    if (reviewed) {
      meta.needs_review = false
      meta.reviewed_at = new Date().toISOString()
      meta.reviewed_by = "manual"
      meta.reviewed_from = reviewedFrom
    } else {
      meta.needs_review = true
      delete meta.reviewed_at
      delete meta.reviewed_by
      delete meta.reviewed_from
    }
    content._meta = meta
    return content
  },

  _findEntity(id) {
    return [...(this._entities || []), ...(this._candidates || [])]
      .find((entity) => this._entityId(entity) === id) || null
  },

  _candidateMeta(candidate) {
    return (candidate?.content_json || {})._meta || {}
  },

  _candidateAction(candidate) {
    return candidate?.suggested_action
      || this._candidateMeta(candidate).suggested_action
      || "create_new"
  },

  _candidateTargetName(candidate) {
    return candidate?.suggested_existing_entity_name
      || this._candidateMeta(candidate).suggested_existing_entity_name
      || ""
  },

  _candidateTargetId(candidate) {
    return candidate?.suggested_existing_entity_id
      || this._candidateMeta(candidate).suggested_existing_entity_id
      || ""
  },

  _isTargetedAliasCandidate(candidate) {
    const targetId = this._candidateTargetId(candidate)
    return ["link_to_existing", "alias_of_existing"].includes(
      this._candidateAction(candidate),
    ) && Boolean(targetId) && targetId !== this._entityId(candidate)
  },

  _candidateActionsHtml(candidate, { allowAlias = false, allowMerge = false } = {}) {
    const id = this._entityId(candidate)
    const action = this._candidateAction(candidate)
    const targetName = this._candidateTargetName(candidate)
    const isTemporary = action === "temporary_only"
    const isSuggestionShadow = this._isSuggestionShadow(candidate)
    const canAccept = isSuggestionShadow || ![
      "temporary_only",
      "ignore",
      "link_to_existing",
      "alias_of_existing",
      "merge_with_existing",
    ].includes(action)
    const canAlias = allowAlias || isSuggestionShadow
      || ["link_to_existing", "alias_of_existing"].includes(action)
    const canMerge = allowMerge || isSuggestionShadow || action === "merge_with_existing"
    return `
      ${canAccept ? `<button class="btn btn-sm btn-primary" data-action="accept-candidate" data-id="${esc(id)}">采用</button>` : ""}
      <button class="btn btn-sm" data-action="edit-entity" data-id="${esc(id)}">编辑后采用</button>
      ${canAlias ? `<button class="btn btn-sm btn-primary" data-action="resolve-candidate-alias" data-id="${esc(id)}" data-target-name="${esc(targetName)}">设为别名</button>` : ""}
      ${canMerge ? `<button class="btn btn-sm" data-action="merge-entity" data-id="${esc(id)}" data-target-name="${esc(targetName)}">合并到</button>` : ""}
      <button class="btn btn-sm ${isTemporary ? "" : "btn-danger"}" data-action="ignore-candidate" data-id="${esc(id)}">${isTemporary ? "设为临时" : "忽略"}</button>
    `
  },

  _normalizedCandidateName(candidate) {
    return String(candidate?.name || "")
      .normalize("NFKC")
      .toLocaleLowerCase("zh-CN")
      .replace(/[\s·•・._\-—–:：'’"“”()（）[\]【】]/g, "")
  },

  _candidateNamesAreSimilar(left, right) {
    if ((left?.entity_type || "") !== (right?.entity_type || "")) return false
    const a = this._normalizedCandidateName(left)
    const b = this._normalizedCandidateName(right)
    if (!a || !b) return false
    if (a === b) return true
    const shorter = a.length <= b.length ? a : b
    const longer = a.length > b.length ? a : b
    if (shorter.length >= 3 && longer.includes(shorter)) return true
    if (shorter.length < 3) return false
    const aPairs = new Set(Array.from({ length: a.length - 1 }, (_, index) => (
      a.slice(index, index + 2)
    )))
    const bPairs = new Set(Array.from({ length: b.length - 1 }, (_, index) => (
      b.slice(index, index + 2)
    )))
    const overlap = Array.from(aPairs).filter((pair) => bPairs.has(pair)).length
    return (2 * overlap) / (aPairs.size + bPairs.size) >= 0.72
  },

  _groupSimilarNameCandidates(candidates) {
    const groups = []
    const assigned = new Set()
    for (let index = 0; index < candidates.length; index += 1) {
      if (assigned.has(index)) continue
      const group = [candidates[index]]
      assigned.add(index)
      for (let other = index + 1; other < candidates.length; other += 1) {
        if (assigned.has(other)) continue
        if (group.some((item) => this._candidateNamesAreSimilar(item, candidates[other]))) {
          group.push(candidates[other])
          assigned.add(other)
        }
      }
      if (group.length > 1) groups.push(group)
    }
    return groups
  },

  _renderCandidateGroupItem(candidate, scope, badgeLabel, actionOptions = {}) {
    const id = this._entityId(candidate)
    return `
      <article class="world-candidate-alias-item" data-id="${esc(id)}">
        <div class="world-candidate-alias-item__identity">
          ${renderSelectionCell(this, scope, id, `选择 ${candidate.name || "待处理对象"}`)}
          <div>
            <strong>${esc(candidate.name || "未命名候选")}</strong>
            <span>${esc(candidate.entity_type || "-")}</span>
          </div>
          <span class="candidate-action-badge candidate-action-badge--alias_of_existing">${esc(badgeLabel)}</span>
        </div>
        <div class="world-candidate-alias-item__evidence">
          ${this._inlineEvidenceHtml(this._candidateMeta(candidate))}
        </div>
        <div class="row-actions">${this._candidateActionsHtml(candidate, actionOptions)}</div>
      </article>
    `
  },

  _renderTargetedAliasCandidateGroups(candidates, scope) {
    const groups = new Map()
    for (const candidate of candidates) {
      const targetId = this._candidateTargetId(candidate)
      const targetName = this._candidateTargetName(candidate)
      const key = targetId || `name:${targetName}`
      if (!groups.has(key)) groups.set(key, { targetId, targetName, candidates: [] })
      groups.get(key).candidates.push(candidate)
    }
    return `
      <div class="world-candidate-alias-groups" aria-label="建议设为别名的待处理对象">
        ${Array.from(groups.values()).map((group) => {
          const targetLabel = group.targetName
            || (group.targetId ? `${String(group.targetId).slice(0, 8)}...` : "未知对象")
          const groupIds = group.candidates.map((item) => this._entityId(item))
          return `
            <section class="world-candidate-alias-group" data-target-id="${esc(group.targetId)}">
              <header class="world-candidate-alias-group__header">
                <div>
                  <div class="world-candidate-alias-group__target">
                    <span class="badge badge-canonical">已有对象</span>
                    <strong>${esc(targetLabel)}</strong>
                  </div>
                  <p>以下 ${group.candidates.length} 个候选建议作为${esc(targetLabel)}别名</p>
                </div>
                <span class="world-candidate-alias-group__select-all">
                  ${renderSelectionHeader(this, scope, groupIds, `全选建议并入 ${targetLabel} 的条目`)}
                  <span>全选本组</span>
                </span>
              </header>
              <div class="world-candidate-alias-group__items">
                ${group.candidates.map((candidate) => (
                  this._renderCandidateGroupItem(candidate, scope, "建议别名")
                )).join("")}
              </div>
            </section>
          `
        }).join("")}
      </div>
    `
  },

  _renderSimilarNameCandidateGroups(groups, scope) {
    if (!groups.length) return ""
    return `
      <div class="world-candidate-alias-groups" aria-label="名称相似的待处理对象">
        ${groups.map((group) => {
          const groupIds = group.map((item) => this._entityId(item))
          const typeLabel = this._entityTypes.find((item) => (
            item.value === group[0]?.entity_type
          ))?.label || group[0]?.entity_type || "对象"
          return `
            <section class="world-candidate-alias-group world-candidate-similar-group">
              <header class="world-candidate-alias-group__header">
                <div>
                  <div class="world-candidate-alias-group__target">
                    <span class="badge badge-draft">名称相似</span>
                    <strong>${esc(typeLabel)}</strong>
                  </div>
                  <p>以下 ${group.length} 个待处理对象合并展示，请逐条决定采用、设为别名、合并或忽略</p>
                </div>
                <span class="world-candidate-alias-group__select-all">
                  ${renderSelectionHeader(this, scope, groupIds, "全选本组相似名称条目")}
                  <span>全选本组</span>
                </span>
              </header>
              <div class="world-candidate-alias-group__items">
                ${group.map((candidate) => (
                  this._renderCandidateGroupItem(
                    candidate,
                    scope,
                    "相似名称",
                    { allowAlias: true, allowMerge: true },
                  )
                )).join("")}
              </div>
            </section>
          `
        }).join("")}
      </div>
    `
  },

  _renderCandidatesList({ reviewOnly = false } = {}) {
    if (this._candidateLoadError && this._candidates.length === 0) {
      return `${reviewOnly ? this._renderCandidateReviewFilters() : ""}
        <div class="empty-state" role="alert">
          <div class="empty-icon">!</div>
          <p>${esc(this._candidateLoadError)}</p>
          <button class="btn btn-primary world-review-touch-target" data-action="retry-candidate-load">重试加载</button>
        </div>
      `
    }
    if (this._candidates.length === 0) {
      return `${reviewOnly ? this._renderCandidateReviewFilters() : ""}
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <p>没有待处理对象。</p>
          <p>AI 或导入提出、尚未采用的对象会出现在这里，你可以决定如何处置。</p>
        </div>
      `
    }
    const scope = "world-candidates"
    const ids = this._candidates.map((candidate) => this._entityId(candidate))
    reconcileBulkSelection(this, scope, ids)
    const targetedAliasCandidates = this._candidates.filter((candidate) => (
      this._isTargetedAliasCandidate(candidate)
    ))
    const aliasUngroupedCandidates = this._candidates.filter((candidate) => (
      !this._isTargetedAliasCandidate(candidate)
    ))
    const similarNameGroups = this._groupSimilarNameCandidates(aliasUngroupedCandidates)
    const similarNameIds = new Set(similarNameGroups.flat().map((item) => this._entityId(item)))
    const regularCandidates = aliasUngroupedCandidates.filter((candidate) => (
      !similarNameIds.has(this._entityId(candidate))
    ))
    const regularIds = regularCandidates.map((candidate) => this._entityId(candidate))

    let html = `${reviewOnly ? this._renderCandidateReviewFilters() : ""}
      <p class="world-list-description">
        以下内容尚未进入当前有效设定。请结合来源和证据决定采用、合并、设为别名或忽略。
      </p>
      ${targetedAliasCandidates.length
        ? this._renderTargetedAliasCandidateGroups(targetedAliasCandidates, scope)
        : ""}
      ${this._renderSimilarNameCandidateGroups(similarNameGroups, scope)}
      ${regularCandidates.length ? `
      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">${renderSelectionHeader(this, scope, regularIds, "全选普通待处理项")}</th>
            <th>名称</th>
            <th>类型</th>
            <th>重要度</th>
            <th>建议动作</th>
            <th>证据</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
      ` : ""}
    `

    for (const c of regularCandidates) {
      const id = c.id || c.entity_id
      const action = this._candidateAction(c)
      const targetName = this._candidateTargetName(c)
      let actionLabel = WORLD_SUGGESTED_ACTION_LABELS[action] || action
      if (targetName && ["link_to_existing", "alias_of_existing"].includes(action)) {
        actionLabel = `作为${targetName}别名`
      } else if (targetName && action === "merge_with_existing") {
        actionLabel = `合并到${targetName}`
      }
      const meta = this._candidateMeta(c)
      html += `
        <tr data-id="${esc(id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, id, `选择 ${c.name || "待处理项"}`)}</td>
          <td data-label="名称">${esc(c.name)}</td>
          <td data-label="类型" class="world-table-cell--type">${esc(c.entity_type)}</td>
          <td data-label="重要度">${esc(c.importance ?? c.importance_score ?? "-")}</td>
          <td data-label="建议动作"><span class="candidate-action-badge candidate-action-badge--${esc(action)}">${esc(actionLabel)}</span></td>
          <td data-label="证据" style="max-width:220px;color:var(--text-dim);font-size:12px;">${this._inlineEvidenceHtml(meta)}</td>
          <td data-label="操作"><div class="row-actions">${this._candidateActionsHtml(c)}</div></td>
        </tr>
      `
    }

    if (regularCandidates.length) html += '</tbody></table>'
    html = renderBulkToolbar(this, scope, [
      { action: "accept-candidates", label: "批量采用", className: "btn-primary" },
      { action: "ignore-candidates", label: "批量忽略/设为临时", className: "btn-danger" },
    ], {
      noun: "待处理项",
      hint: "合并项仍需逐条选择目标对象",
      selectAllIds: ids,
      selectAllLabel: "全选当前待处理项",
    }) + html
    html += this._renderPager({
      total: this._candidateTotal,
      skip: this._candidateFilters.skip,
      limit: this._candidateFilters.limit,
      prevAction: "prev-candidates-page",
      nextAction: "next-candidates-page",
    })
    return html
  },

  _renderCandidateReviewFilters() {
    const entityTypeOptions = [
      '<option value="">全部类型</option>',
      ...this._entityTypes.map((item) => (
        `<option value="${esc(item.value)}" ${this._candidateFilters.entity_type === item.value ? "selected" : ""}>${esc(item.label)}</option>`
      )),
    ].join("")
    const content = `
      <div class="filter-bar world-review-filters" style="margin-bottom:12px;">
        <select class="form-select" id="review-candidate-entity-type" aria-label="对象类型筛选">
          ${entityTypeOptions}
        </select>
        <select class="form-select" id="review-candidate-action" aria-label="建议动作筛选">
          <option value="">全部动作</option>
          ${["create_new", "link_to_existing", "alias_of_existing", "merge_with_existing", "temporary_only", "ignore", "needs_user_decision"].map((value) => `<option value="${esc(value)}" ${this._candidateFilters.suggested_action === value ? "selected" : ""}>${esc(WORLD_SUGGESTED_ACTION_LABELS[value])}</option>`).join("")}
        </select>
        <input class="form-input" id="review-candidate-source" value="${esc(this._candidateFilters.source)}" placeholder="来源" aria-label="来源筛选" />
        <details class="world-diagnostic-filter" ${this._candidateFilters.workflow_id ? "open" : ""}>
          <summary>诊断筛选</summary>
          <input class="form-input" id="review-candidate-workflow" data-diagnostic-field value="${esc(this._candidateFilters.workflow_id)}" placeholder="Workflow ID" aria-label="Workflow 诊断筛选" />
        </details>
        <input class="form-input" id="review-candidate-scene" value="${esc(this._candidateFilters.scene_index)}" placeholder="Scene" aria-label="Scene 序号筛选" />
        <input class="form-input" id="review-candidate-chapter" value="${esc(this._candidateFilters.source_chapter_index)}" placeholder="章节" aria-label="章节筛选" />
        <input class="form-input" id="review-candidate-confidence-min" value="${esc(this._candidateFilters.confidence_min)}" placeholder="最低置信度" aria-label="最低置信度" />
        <input class="form-input" id="review-candidate-confidence-max" value="${esc(this._candidateFilters.confidence_max)}" placeholder="最高置信度" aria-label="最高置信度" />
        <button class="btn btn-sm" data-action="apply-candidate-review-filters">筛选</button>
        <button class="btn btn-sm" data-action="reset-candidate-review-filters">清空</button>
      </div>
    `
    return this._renderFilterPanel(
      "review-objects",
      content,
      WORLD_CANDIDATE_QUERY_KEYS.some((key) => Boolean(this._candidateFilters[key])),
    )
  },

  _inlineEvidenceHtml(item = {}) {
    const evidence = [
      ["来源", item.source === "deep_import" ? "深度导入" : item.source],
      ["Workflow", item.workflow_id],
      ["章节", item.source_chapter_index],
      ["Scene", item.scene_index || item.scene_id],
      ["置信度", item.confidence != null ? `${(Number(item.confidence) * 100).toFixed(0)}%` : ""],
      ["引用", item.quote],
    ].filter(([, value]) => value != null && String(value).trim() !== "")
    if (!evidence.length) return "-"
    return evidence.map(([label, value]) => `<div><strong>${esc(label)}：</strong>${esc(value)}</div>`).join("")
  },

  async _renderRelations({ reviewOnly = false } = {}) {
    const description = `
      <p class="world-list-description">
        ${reviewOnly ? "处理 AI 抽取或导入提出、尚未采用的关系。" : "管理世界对象与人物之间的关系。"}
      </p>
    `
    if (!state.currentProjectId) return description + '<div class="empty-state"><p>请先选择项目。</p></div>'
    if (reviewOnly) return this._renderRelationReviewWorkspace(description)

    let html = description
    try {
      const params = {
        novel_id: state.currentProjectId,
        skip: this._relationFilters.skip,
        limit: this._relationFilters.limit,
      }
      params.status = reviewOnly ? "candidate" : "canonical"
      if (reviewOnly && this._relationFilters.relation_type) params.relation_type = this._relationFilters.relation_type
      if (reviewOnly && this._relationFilters.q) params.q = this._relationFilters.q
      if (reviewOnly && this._relationFilters.source_chapter_id) params.source_chapter_id = this._relationFilters.source_chapter_id
      if (reviewOnly && this._relationFilters.strength_min != null && this._relationFilters.strength_min !== "") params.strength_min = Number(this._relationFilters.strength_min)
      if (reviewOnly && this._relationFilters.strength_max != null && this._relationFilters.strength_max !== "") params.strength_max = Number(this._relationFilters.strength_max)
      const data = await api.world.listRelationships(params)
      const rels = data.items || data || []
      this._relations = rels
      this._relationTotal = Number(data.total ?? rels.length) || 0
      html = description + (reviewOnly ? this._renderRelationReviewFilters() : "")
      if (rels.length === 0) {
        return html + `<div class="empty-state"><p>${reviewOnly ? "没有待处理关系。" : "还没有建立人物关系。"}</p><p class="world-text-dim">关系网可以帮助你梳理角色之间的恩怨情仇。</p></div>`
      }
      const scope = "world-relations"
      const ids = rels.map((rel) => rel.id || rel.relationship_id).filter(Boolean)
      reconcileBulkSelection(this, scope, ids)
      html += renderBulkToolbar(this, scope, [
        { action: "review-relations", label: "批量采用", className: "btn-primary" },
        { action: "delete-relations", label: "批量删除", className: "btn-danger" },
      ], {
        noun: "关系",
        selectAllIds: ids,
        selectAllLabel: "全选当前关系",
      })
      html += `
      <table class="data-table">
        <thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前关系")}</th><th>源对象</th><th>关系类型</th><th>目标对象</th><th>状态</th><th>描述</th><th>证据</th><th>操作</th></tr></thead>
        <tbody>
      `
      for (const r of rels) {
        const id = r.id || r.relationship_id
        const display = worldAssetDisplay({ ...r, status: r.status || "canonical" })
        const statusLabel = display.label
        const statusClass = displayStateBadgeClass(display.displayState)
        const reviewAction = this._renderRelationReviewAction(r)
        const sourceName = r.source_name || r.source_entity_name || r.source?.name || (r.source_id ? `${String(r.source_id).slice(0, 8)}...` : "-")
        const targetName = r.target_name || r.target_entity_name || r.target?.name || (r.target_id ? `${String(r.target_id).slice(0, 8)}...` : "-")
        html += `
        <tr data-id="${esc(id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, id, "选择关系")}</td>
          <td class="world-table-cell--type">${esc(sourceName)}</td>
          <td><span class="badge badge-canonical">${esc(r.relation_type || "-")}</span></td>
          <td class="world-table-cell--type">${esc(targetName)}</td>
          <td><span class="badge ${statusClass}">${statusLabel}</span></td>
          <td class="world-table-cell--dim world-table-cell--ellipsis">${esc(r.description || "")}</td>
          <td class="world-table-cell--dim">${this._inlineRelationEvidenceHtml(r)}</td>
          <td>
            <div class="row-actions">
              ${reviewOnly && display.displayState === "review" ? `<button class="btn btn-sm btn-primary" data-action="edit-relation-review" data-id="${esc(id)}">编辑后采用</button>` : ""}
              ${reviewAction}
              <button class="btn btn-sm btn-danger" data-action="delete-relation" data-id="${esc(r.id || r.relationship_id)}">删除</button>
            </div>
          </td>
        </tr>`
      }
      html += '</tbody></table>'
      html += this._renderPager({
        total: this._relationTotal,
        skip: this._relationFilters.skip,
        limit: this._relationFilters.limit,
        prevAction: "prev-relations-page",
        nextAction: "next-relations-page",
      })
    } catch { html += '<div class="empty-state"><p>加载关系失败。</p></div>' }
    return html
  },

  async _renderRelationReviewWorkspace(description) {
    try {
      const filters = this._relationFilters
      const params = {
        novel_id: state.currentProjectId,
        skip: filters.skip,
        limit: filters.limit,
      }
      for (const key of ["q", "relation_type", "source_chapter_id", "scene_index", "source_chapter_index", "strength_min", "strength_max", "has_quote", "type_kind", "multi_type_only"]) {
        const value = filters[key]
        if (value === "" || value == null) continue
        if (["scene_index", "source_chapter_index", "strength_min", "strength_max"].includes(key)) params[key] = Number(value)
        else if (["has_quote", "multi_type_only"].includes(key)) params[key] = value === true || value === "true"
        else params[key] = value
      }
      const data = await api.world.listRelationReviewGroups(params)
      this._relationGroups = data.groups || []
      this._relations = this._relationGroups.flatMap((group) => group.members || [])
      this._relationTotal = Number(data.item_total || 0)
      this._relationGroupTotal = Number(data.group_total || 0)
      this._reviewCounts.relations = this._relationTotal
      const scope = "world-relation-groups"
      const ids = this._relationGroups.map((group) => group.group_id)
      reconcileBulkSelection(this, scope, ids)
      let html = description + this._renderRelationReviewFilters()
      if (!ids.length) {
        return html + '<div class="empty-state"><p>没有待处理关系。</p><p class="world-text-dim">筛选条件会保留；可以清空筛选查看全部队列。</p></div>'
      }
      html += renderBulkToolbar(this, scope, [
        { action: "apply-relation-decisions", label: "应用已准备决策", className: "btn-primary" },
        { action: "ignore-relation-groups", label: "整组忽略", className: "btn-danger" },
      ], {
        noun: "关系组",
        hint: "先在组内准备采用/归并决策；全选仅作用于当前页",
        selectAllIds: ids,
        selectAllLabel: "全选当前页关系组",
      })
      html += `<div class="review-group-list">${this._relationGroups.map((group) => this._renderRelationReviewGroup(group, scope)).join("")}</div>`
      html += this._renderPager({
        total: this._relationGroupTotal,
        skip: filters.skip,
        limit: filters.limit,
        prevAction: "prev-relations-page",
        nextAction: "next-relations-page",
      })
      return html
    } catch (err) {
      return description + `<div class="empty-state"><p>加载待处理关系失败。</p><p class="world-text-dim">${esc(err?.message || "请稍后重试")}</p></div>`
    }
  },

  _renderRelationReviewGroup(group, scope) {
    const draft = this._relationReviewDrafts[group.group_id]
    const reviewError = this._relationReviewErrors[group.group_id]
    const draftLabel = draft
      ? { accept: "已准备：独立采用", merge: "已准备：归并", ignore: "已准备：忽略" }[draft.action]
      : "尚未准备决策"
    const canonicalTypes = (group.canonical_relations || []).map((item) => item.relation_type)
    return `
      <section class="review-group-card" data-group-id="${esc(group.group_id)}">
        <header class="review-group-card__header">
          <div class="review-group-card__select">${renderSelectionCell(this, scope, group.group_id, `选择 ${group.source_name || "源对象"} 到 ${group.target_name || "目标对象"}`)}</div>
          <div class="review-group-card__title">
            <strong>${esc(group.source_name || "未命名对象")} → ${esc(group.target_name || "未命名对象")}</strong>
            <span>${esc(group.member_count)} 条候选 · ${esc(group.evidence_count || 0)} 条证据</span>
          </div>
          <span class="badge ${draft ? "badge-canonical" : "badge-candidate"}">${esc(draftLabel)}</span>
        </header>
        <div class="review-group-card__meta">
          <span>类型：${(group.type_variants || []).map((value) => `<code>${esc(this._reviewTypeLabel("relation", value))}</code>`).join("、")}</span>
          ${(group.scene_indices || []).length ? `<span>Scene ${(group.scene_indices || []).map(esc).join("、")}</span>` : ""}
          ${(group.source_chapter_indices || []).length ? `<span>章节 ${(group.source_chapter_indices || []).map(esc).join("、")}</span>` : ""}
          ${canonicalTypes.length ? `<span class="review-warning">已有正式关系：${canonicalTypes.map((value) => esc(this._reviewTypeLabel("relation", value))).join("、")}</span>` : ""}
        </div>
        ${group.reverse_candidate_count || (group.reverse_canonical_relations || []).length ? `
          <div class="review-reverse-hint">反向关联提示：${esc(group.target_name || "目标对象")} → ${esc(group.source_name || "源对象")}，
            ${esc(group.reverse_candidate_count || 0)} 条候选${(group.reverse_type_variants || []).length ? `（${(group.reverse_type_variants || []).map((value) => esc(this._reviewTypeLabel("relation", value))).join("、")}）` : ""}，
            ${esc((group.reverse_canonical_relations || []).length)} 条正式关系。反向记录不会自动归并。
          </div>
        ` : ""}
        ${reviewError ? `<div class="review-item-error" role="alert">${esc(reviewError)}</div>` : ""}
        <div class="review-group-card__members">
          ${(group.members || []).map((member) => `
            <article class="review-member-row">
              <div><strong>${esc(this._reviewTypeLabel("relation", member.relation_type))}</strong>${member.type_kind === "custom" ? '<span class="badge badge-draft">自定义</span>' : ""}</div>
              <div class="review-member-row__description">${esc(member.description || "暂无描述")}</div>
              ${this._reviewEvidenceSummaryHtml(member.evidence_summary || member, "relation", member.strength)}
            </article>
          `).join("")}
        </div>
        <footer class="review-group-card__actions">
          <button class="btn btn-sm btn-primary" data-action="prepare-relation-review" data-group-id="${esc(group.group_id)}">${draft ? "修改决策" : "处理本组"}</button>
        </footer>
      </section>
    `
  },

  _reviewTypeLabel(kind, value) {
    const items = kind === "alias" ? this._reviewTypeCatalog.alias_types : this._reviewTypeCatalog.relation_types
    const match = (items || []).find((item) => item.value === value)
    return match ? `${match.label} (${value})` : value || "-"
  },

  _reviewEvidenceSummaryHtml(item = {}, kind = "alias", numericValue = null) {
    const source = item.source === "deep_import" ? "深度导入" : item.source
    const summary = [
      source,
      item.scene_index != null ? `Scene ${item.scene_index}` : "",
      item.source_chapter_index != null ? `第 ${item.source_chapter_index} 章` : "",
      numericValue != null ? `${kind === "relation" ? "强度" : "置信度"} ${Math.round(Number(numericValue) * 100)}%` : "",
    ].filter(Boolean).join(" · ")
    const diagnostic = JSON.stringify({
      workflow_id: item.workflow_id || null,
      scene_id: item.scene_id || null,
      scene_index: item.scene_index ?? null,
      source_chapter_index: item.source_chapter_index ?? null,
      evidence_refs: item.evidence_refs || [],
    })
    return `
      <div class="review-evidence-summary">
        <span>${esc(summary || "无来源摘要")}</span>
        ${item.quote ? `<blockquote>${esc(item.quote)}</blockquote>` : '<span class="world-text-dim">无原文引用</span>'}
        <details>
          <summary>诊断信息</summary>
          <pre>${esc(diagnostic)}</pre>
          <button class="btn btn-sm" data-action="copy-review-diagnostic" data-diagnostic="${esc(diagnostic)}">复制诊断信息</button>
        </details>
      </div>
    `
  },

  _bindReviewDiagnosticCopyButtons(root = document) {
    root?.querySelectorAll?.('[data-action="copy-review-diagnostic"]').forEach((button) => {
      if (button.dataset.reviewDiagnosticBound === "true") return
      button.dataset.reviewDiagnosticBound = "true"
      button.addEventListener("click", async (event) => {
        event.preventDefault()
        try {
          await navigator.clipboard.writeText(button.getAttribute("data-diagnostic") || "{}")
          toast("诊断信息已复制", "success")
        } catch {
          toast("复制失败", "error")
        }
      })
    })
  },

  _renderRelationReviewFilters() {
    const content = `
      <div class="filter-bar" style="margin-bottom:12px;">
        <input class="form-input" id="review-relation-type" value="${esc(this._relationFilters.relation_type)}" placeholder="关系类型" />
        <input class="form-input" id="review-relation-scene" value="${esc(this._relationFilters.scene_index)}" placeholder="Scene 序号" />
        <input class="form-input" id="review-relation-source-chapter" value="${esc(this._relationFilters.source_chapter_index)}" placeholder="章节序号" />
        <input class="form-input" id="review-relation-strength-min" value="${esc(this._relationFilters.strength_min)}" placeholder="最低强度" />
        <select class="form-select" id="review-relation-type-kind">
          <option value="">全部类型</option>
          <option value="recommended" ${this._relationFilters.type_kind === "recommended" ? "selected" : ""}>推荐类型</option>
          <option value="custom" ${this._relationFilters.type_kind === "custom" ? "selected" : ""}>自定义类型</option>
        </select>
        <select class="form-select" id="review-relation-page-size">
          <option value="20" ${Number(this._relationFilters.limit) === 20 ? "selected" : ""}>每页 20 组</option>
          <option value="50" ${Number(this._relationFilters.limit) === 50 ? "selected" : ""}>每页 50 组</option>
        </select>
        <button class="btn btn-sm" data-action="apply-relation-review-filters">筛选</button>
        <button class="btn btn-sm" data-action="reset-relation-review-filters">清空</button>
      </div>
    `
    return `
      <div class="review-search-bar">
        <input class="form-input" id="review-relation-q" value="${esc(this._relationFilters.q)}" placeholder="搜索对象、关系类型或描述" aria-label="搜索待处理关系" />
        <button class="btn btn-sm btn-primary" data-action="apply-relation-review-filters">搜索</button>
      </div>
      <div class="review-quick-filters">
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="multi_type_only" data-filter-value="true">同对象对多类型</button>
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="type_kind" data-filter-value="custom">自定义类型</button>
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="has_quote" data-filter-value="false">缺少引用</button>
        <button class="btn btn-sm" data-action="set-relation-quick-filter" data-filter-key="strength_max" data-filter-value="0.69">低强度</button>
        <span class="review-scene-quick-filter"><input class="form-input" id="review-relation-scene-quick" value="${esc(this._relationFilters.scene_index)}" placeholder="Scene 序号" aria-label="快速按 Scene 筛选" /><button class="btn btn-sm" data-action="apply-relation-scene-quick">按 Scene 筛选</button></span>
      </div>
      ${this._renderReviewFilterChips("relation")}
      ${this._renderFilterPanel(
      "review-relations",
      content,
      ["relation_type", "scene_index", "source_chapter_index", "strength_min", "strength_max", "type_kind", "has_quote", "multi_type_only"]
        .some((key) => Boolean(this._relationFilters[key])),
      )}
    `
  },

  _inlineRelationEvidenceHtml(relation = {}) {
    const reviewMeta = relation.review_meta && typeof relation.review_meta === "object"
      ? relation.review_meta
      : {}
    const sceneLabel = [
      reviewMeta.scene_id,
      reviewMeta.scene_index != null ? `序号 ${reviewMeta.scene_index}` : "",
    ].filter(Boolean).join("（")
    const normalizedSceneLabel = sceneLabel && reviewMeta.scene_id && reviewMeta.scene_index != null
      ? `${sceneLabel}）`
      : sceneLabel
    const evidenceRefs = Array.isArray(reviewMeta.evidence_refs)
      ? reviewMeta.evidence_refs.map((ref) => {
        if (ref == null) return ""
        if (typeof ref !== "object") return String(ref)
        const refScene = ref.scene_id || (ref.scene_index != null ? `Scene ${ref.scene_index}` : "")
        const refChapter = ref.source_chapter_index != null ? `章节 ${ref.source_chapter_index}` : ""
        return [refScene, refChapter, ref.quote || ref.evidence || ""].filter(Boolean).join(" · ")
      }).filter(Boolean).join("；")
      : ""
    const evidence = [
      ["来源", reviewMeta.source === "deep_import" ? "深度导入" : reviewMeta.source],
      ["Workflow", reviewMeta.workflow_id],
      ["Scene", normalizedSceneLabel],
      ["章节", reviewMeta.source_chapter_index ?? relation.source_chapter_id],
      ["强度", relation.strength != null ? `${Math.round(Number(relation.strength) * 100)}%` : ""],
      ["引用", relation.quote || reviewMeta.quote],
      ["证据", evidenceRefs],
    ].filter(([, value]) => value != null && String(value).trim() !== "")
    if (!evidence.length) return "-"
    return evidence.map(([label, value]) => `<div><strong>${esc(label)}：</strong>${esc(value)}</div>`).join("")
  },

  showRelationCreateForm() {
    const entityOptions = this._entityOptionsHtml()
    const formHtml = `
      <div class="form-group">
        <label>源对象</label>
        <select class="form-select" id="rel-source"><option value="">请选择</option>${entityOptions}</select>
      </div>
      <div class="form-group">
        <label>关系类型</label>
        <select class="form-select" id="rel-type">
          <option value="friend_of">朋友</option>
          <option value="enemy_of">敌人</option>
          <option value="ally_of">盟友</option>
          <option value="member_of">成员</option>
          <option value="leader_of">领导者</option>
          <option value="located_at">位于</option>
          <option value="contains">包含</option>
          <option value="related_to">相关</option>
        </select>
      </div>
      <div class="form-group">
        <label>目标对象</label>
        <select class="form-select" id="rel-target"><option value="">请选择</option>${entityOptions}</select>
      </div>
      <div class="form-group">
        <label>描述</label>
        <input class="form-input" id="rel-desc" placeholder="关系描述（可选）" />
      </div>
    `
    showModalHtml("新建关系", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const src = document.getElementById("rel-source")?.value
        const tgt = document.getElementById("rel-target")?.value
        if (!src || !tgt) { toast("请选择源对象和目标对象", "warning"); return }
        try {
          await api.world.createRelationship({
            source_id: src, source_type: "entity",
            target_id: tgt, target_type: "entity",
            relation_type: document.getElementById("rel-type")?.value || "related_to",
            description: document.getElementById("rel-desc")?.value || "",
          }, state.currentProjectId)
          toast("关系已创建", "success")
          router.navigate("world", "relations")
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _reviewEntityOptionsHtml(items = [], selectedId = "") {
    const byId = new Map()
    for (const item of items) {
      const id = this._entityId(item)
      if (id) byId.set(id, item)
    }
    if (selectedId && !byId.has(selectedId)) {
      byId.set(selectedId, { id: selectedId, name: "当前对象", entity_type: "-", status: "canonical" })
    }
    return Array.from(byId.values()).map((item) => {
      const id = this._entityId(item)
      return `<option value="${esc(id)}" ${id === selectedId ? "selected" : ""}>${esc(item.name || "未命名对象")} · ${esc(item.entity_type || "-")} · ${esc(item.status || "-")}</option>`
    }).join("")
  },

  _bindReviewEntitySearch(prefix, selectedId = "") {
    const button = document.getElementById(`${prefix}-search`)
    const input = document.getElementById(`${prefix}-query`)
    const select = document.getElementById(`${prefix}-select`)
    if (!button || !input || !select) return
    button.onclick = async () => {
      try {
        const data = await api.world.listEntities({
          novel_id: state.currentProjectId,
          q: input.value || "",
          skip: 0,
          limit: 20,
        })
        const items = (data.items || data || []).filter((item) => (
          ["canonical", "draft", "candidate"].includes(item.status)
          && !item.content_json?._meta?.compatibility_shadow
        ))
        select.innerHTML = this._reviewEntityOptionsHtml(items, selectedId)
      } catch (err) {
        toast(err.message || "搜索对象失败", "error")
      }
    }
  },

  showRelationGroupReviewForm(groupId) {
    const group = this._relationGroups.find((item) => item.group_id === groupId)
    if (!group) return toast("未找到目标关系组", "error")
    const members = group.members || []
    const existingDraft = this._relationReviewDrafts[groupId]
    const primary = members.find((item) => item.id === existingDraft?.primary_relation_id) || members[0]
    const suggested = primary?.suggested_relation_type
    const defaultSelected = members.filter((item) => (
      (suggested && item.suggested_relation_type === suggested)
      || (!suggested && item.relation_type === primary?.relation_type)
    ))
    const selectedIds = new Set(existingDraft?.member_relation_ids || defaultSelected.map((item) => item.id))
    const defaultAction = existingDraft?.action || (selectedIds.size > 1 ? "merge" : "accept")
    const entitySeed = [
      { id: group.source_id, name: group.source_name, entity_type: "-", status: "canonical" },
      { id: group.target_id, name: group.target_name, entity_type: "-", status: "canonical" },
    ]
    const relationTypes = this._reviewTypeCatalog.relation_types || REVIEW_RELATION_TYPE_FALLBACK
    const suggestions = Array.from(new Set(members.map((item) => item.suggested_relation_type).filter(Boolean)))
    const body = `
      <div class="review-decision-layout">
        <div class="form-group">
          <label for="relation-review-action">处理方式</label>
          <select class="form-select" id="relation-review-action">
            <option value="accept" ${defaultAction === "accept" ? "selected" : ""}>独立采用一条</option>
            <option value="merge" ${defaultAction === "merge" ? "selected" : ""}>归并所选证据</option>
            <option value="ignore" ${defaultAction === "ignore" ? "selected" : ""}>忽略所选</option>
          </select>
        </div>
        <fieldset class="review-candidate-fieldset">
          <legend>选择参与本次决策的候选</legend>
          ${members.map((item) => `
            <label class="review-candidate-option">
              <input type="checkbox" name="relation-review-member" value="${esc(item.id)}" ${selectedIds.has(item.id) ? "checked" : ""} />
              <input type="radio" name="relation-review-primary" value="${esc(item.id)}" ${item.id === (existingDraft?.primary_relation_id || primary?.id) ? "checked" : ""} aria-label="设为主关系" />
              <span><strong>${esc(this._reviewTypeLabel("relation", item.relation_type))}</strong><small>${esc(item.description || item.evidence_summary?.quote || "无描述")}</small></span>
            </label>
          `).join("")}
          <p class="form-help">复选框决定处理范围；单选圆点决定归并后保留的主关系。</p>
        </fieldset>
        <div class="form-group">
          <label>源对象</label>
          <div class="review-search-control"><input class="form-input" id="relation-source-query" value="${esc(group.source_name || "")}" /><button class="btn btn-sm" id="relation-source-search" type="button">搜索</button></div>
          <select class="form-select" id="relation-source-select">${this._reviewEntityOptionsHtml(entitySeed, existingDraft?.source_id || group.source_id)}</select>
        </div>
        <div class="form-group">
          <label>目标对象</label>
          <div class="review-search-control"><input class="form-input" id="relation-target-query" value="${esc(group.target_name || "")}" /><button class="btn btn-sm" id="relation-target-search" type="button">搜索</button></div>
          <select class="form-select" id="relation-target-select">${this._reviewEntityOptionsHtml(entitySeed, existingDraft?.target_id || group.target_id)}</select>
        </div>
        <div class="form-group">
          <label for="relation-final-type">最终关系类型</label>
          <input class="form-input" id="relation-final-type" list="relation-review-type-list" value="${esc(existingDraft?.relation_type || primary?.relation_type || "")}" />
          <datalist id="relation-review-type-list">${relationTypes.map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join("")}</datalist>
          ${suggestions.length ? `<div class="review-suggestion-actions">${suggestions.map((value) => `<button class="btn btn-sm" type="button" data-relation-type-suggestion="${esc(value)}">使用建议：${esc(this._reviewTypeLabel("relation", value))}</button>`).join("")}</div>` : ""}
        </div>
        <div class="form-group"><label for="relation-final-description">描述</label><textarea class="form-textarea" id="relation-final-description" rows="3">${esc(existingDraft?.description ?? primary?.description ?? "")}</textarea></div>
        <div class="form-group"><label for="relation-final-strength">强度</label><input class="form-input" id="relation-final-strength" type="number" min="0" max="1" step="0.01" value="${esc(existingDraft?.strength ?? primary?.strength ?? 0.5)}" /></div>
        ${(group.canonical_relations || []).length ? `<div class="review-warning">采用相同端点和类型时会复用已有正式关系，不创建重复记录。</div>` : ""}
        <section class="review-result-preview" id="relation-review-preview" aria-live="polite"></section>
      </div>
    `
    showModalHtml("准备关系复核决策", body, [{
      text: "保存决策",
      class: "btn-primary",
      handler: async () => {
        const action = document.getElementById("relation-review-action")?.value || "accept"
        const selected = Array.from(document.querySelectorAll('input[name="relation-review-member"]:checked')).map((input) => input.value)
        const primaryId = document.querySelector('input[name="relation-review-primary"]:checked')?.value || ""
        if (!selected.length || (action === "accept" && selected.length !== 1) || (action === "merge" && selected.length < 2)) {
          toast(action === "merge" ? "归并至少需要选择两条关系" : "独立采用只能选择一条关系", "warning")
          return false
        }
        if (["accept", "merge"].includes(action) && !selected.includes(primaryId)) {
          toast("主关系必须在本次选择范围内", "warning")
          return false
        }
        const relationType = document.getElementById("relation-final-type")?.value?.trim() || ""
        if (["accept", "merge"].includes(action) && !relationType) {
          toast("请填写最终关系类型", "warning")
          return false
        }
        this._relationReviewDrafts[groupId] = {
          client_decision_id: groupId,
          action,
          group_id: groupId,
          member_relation_ids: selected,
          primary_relation_id: ["accept", "merge"].includes(action) ? primaryId : null,
          expected_execution_fingerprint: group.execution_fingerprint,
          ...(["accept", "merge"].includes(action) ? {
            source_id: document.getElementById("relation-source-select")?.value,
            target_id: document.getElementById("relation-target-select")?.value,
            relation_type: relationType,
            description: document.getElementById("relation-final-description")?.value?.trim() || "",
            strength: Number(document.getElementById("relation-final-strength")?.value || 0.5),
          } : {}),
        }
        delete this._relationReviewErrors[groupId]
        closeModal()
        await this._rerenderCurrentSubViewInPlace()
      },
    }], { size: "large" })
    this._bindReviewEntitySearch("relation-source", existingDraft?.source_id || group.source_id)
    this._bindReviewEntitySearch("relation-target", existingDraft?.target_id || group.target_id)
    const updatePreview = () => this._updateRelationReviewPreview(group)
    document.querySelectorAll("#relation-review-action, input[name='relation-review-member'], input[name='relation-review-primary'], #relation-source-select, #relation-target-select, #relation-final-type, #relation-final-description, #relation-final-strength").forEach((control) => {
      control.addEventListener("input", updatePreview)
      control.addEventListener("change", updatePreview)
    })
    document.querySelectorAll("[data-relation-type-suggestion]").forEach((button) => {
      button.onclick = () => {
        const input = document.getElementById("relation-final-type")
        if (input) input.value = button.getAttribute("data-relation-type-suggestion") || input.value
        updatePreview()
      }
    })
    updatePreview()
  },

  _updateRelationReviewPreview(group) {
    const preview = document.getElementById("relation-review-preview")
    if (!preview) return
    const action = document.getElementById("relation-review-action")?.value || "accept"
    const selectedIds = Array.from(document.querySelectorAll('input[name="relation-review-member"]:checked')).map((input) => input.value)
    if (action === "ignore") {
      preview.innerHTML = `<h4>处理结果预览</h4><p>将把 ${esc(selectedIds.length)} 条所选候选移入历史；未选中候选保持待处理。</p>`
      return
    }
    const sourceSelect = document.getElementById("relation-source-select")
    const targetSelect = document.getElementById("relation-target-select")
    const sourceId = sourceSelect?.value || ""
    const targetId = targetSelect?.value || ""
    const relationType = document.getElementById("relation-final-type")?.value?.trim() || ""
    const strength = document.getElementById("relation-final-strength")?.value || ""
    const description = document.getElementById("relation-final-description")?.value?.trim() || "无描述"
    const sourceLabel = sourceSelect?.selectedOptions?.[0]?.textContent || "未选择源对象"
    const targetLabel = targetSelect?.selectedOptions?.[0]?.textContent || "未选择目标对象"
    const canonical = (group.canonical_relations || []).find((item) => (
      item.source_id === sourceId && item.target_id === targetId && item.relation_type === relationType
    ))
    preview.innerHTML = `
      <h4>采用后结果预览</h4>
      <p><strong>${esc(sourceLabel)}</strong> → <strong>${esc(targetLabel)}</strong></p>
      <p>类型：${esc(this._reviewTypeLabel("relation", relationType))} · 强度：${esc(strength)} · 所选证据：${esc(selectedIds.length)} 条</p>
      <p>${esc(description)}</p>
      ${canonical ? `<p class="review-warning">将复用已有正式关系，关系 ID 只会记录在诊断与审计信息中。</p>` : `<p class="world-text-dim">将采用主关系作为正式关系；服务端提交前会再检查是否存在可复用关系。</p>`}
    `
  },

  showRelationReviewEditForm(relationId) {
    const relation = (this._relations || []).find((item) => (item.id || item.relationship_id) === relationId)
    if (!relation) {
      toast("未找到目标关系", "error")
      return
    }
    const formHtml = `
      <div class="form-group">
        <label>源对象</label>
        <select class="form-select" id="rel-review-source">${this._relationEntityOptionsHtml(relation.source_id)}</select>
      </div>
      <div class="form-group">
        <label>关系类型</label>
        <input class="form-input" id="rel-review-type" value="${esc(relation.relation_type || "")}" />
      </div>
      <div class="form-group">
        <label>目标对象</label>
        <select class="form-select" id="rel-review-target">${this._relationEntityOptionsHtml(relation.target_id)}</select>
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="rel-review-description" rows="3">${esc(relation.description || "")}</textarea>
      </div>
      <div class="form-group">
        <label>强度</label>
        <input class="form-input" id="rel-review-strength" type="number" min="0" max="1" step="0.01" value="${esc(relation.strength ?? 0.5)}" />
      </div>
      ${this._reviewEvidenceSummaryHtml({
        ...(relation.review_meta || {}),
        source_chapter_index: relation.review_meta?.source_chapter_index ?? relation.source_chapter_id,
        quote: relation.quote || relation.review_meta?.quote,
      }, "relation", relation.strength)}
    `
    showModalHtml("编辑后采用关系", formHtml, [{
      text: "采用", class: "btn-primary", handler: async () => {
        const sourceId = document.getElementById("rel-review-source")?.value || ""
        const targetId = document.getElementById("rel-review-target")?.value || ""
        const relationType = document.getElementById("rel-review-type")?.value?.trim() || ""
        if (!sourceId || !targetId || !relationType) {
          toast("请填写源对象、目标对象和关系类型", "warning")
          return
        }
        try {
          await api.world.reviewEditRelationship(relationId, {
            source_id: sourceId,
            target_id: targetId,
            relation_type: relationType,
            description: document.getElementById("rel-review-description")?.value?.trim() || "",
            strength: Number(document.getElementById("rel-review-strength")?.value || 0.5),
            confirm_review: true,
          }, state.currentProjectId)
          closeModal()
          toast("关系已采用", "success")
          await this._refreshCurrentSubViewInPlace()
        } catch (err) {
          toast(err.message || "采用关系失败", "error")
        }
      },
    }])
    this._bindReviewDiagnosticCopyButtons(document.getElementById("modal-body"))
  },

  deleteRelation(relId) {
    confirmAction("确定删除此关系？", async () => {
      try {
        await api.world.deleteRelationship(relId, { novel_id: state.currentProjectId })
        toast("已删除", "success")
        router.navigate("world", "relations")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  _renderRelationReviewAction(relation) {
    const id = relation?.id || relation?.relationship_id
    if (!id) return ""
    if (worldAssetDisplay({ ...relation, status: relation.status || "canonical" }).displayState === "review") {
      return `<button class="btn btn-sm btn-primary" data-action="mark-relation-reviewed" data-id="${esc(id)}">采用</button>`
    }
    return ""
  },

  async _renderAliases({ reviewOnly = false } = {}) {
    const description = `
      <p class="world-list-description">
        ${reviewOnly ? "处理尚未采用的别名。别名不独立创建对象。" : "管理世界对象的别名、称号和化名。别名不独立创建对象。"}
      </p>
    `
    if (!state.currentProjectId) return description + '<div class="empty-state"><p>请先选择项目。</p></div>'
    if (reviewOnly) return this._renderAliasReviewWorkspace(description)

    let html = description
    try {
      const params = {
        novel_id: state.currentProjectId,
        skip: this._aliasFilters.skip,
        limit: this._aliasFilters.limit,
      }
      params.display_state = reviewOnly ? "review" : "active"
      if (reviewOnly && this._aliasFilters.q) params.q = this._aliasFilters.q
      if (reviewOnly && this._aliasFilters.source) params.source = this._aliasFilters.source
      if (reviewOnly && this._aliasFilters.workflow_id) params.workflow_id = this._aliasFilters.workflow_id
      if (reviewOnly && this._aliasFilters.scene_index != null && this._aliasFilters.scene_index !== "") params.scene_index = Number(this._aliasFilters.scene_index)
      if (reviewOnly && this._aliasFilters.source_chapter_index != null && this._aliasFilters.source_chapter_index !== "") params.source_chapter_index = Number(this._aliasFilters.source_chapter_index)
      if (reviewOnly && this._aliasFilters.confidence_min != null && this._aliasFilters.confidence_min !== "") params.confidence_min = Number(this._aliasFilters.confidence_min)
      if (reviewOnly && this._aliasFilters.confidence_max != null && this._aliasFilters.confidence_max !== "") params.confidence_max = Number(this._aliasFilters.confidence_max)
      const data = await api.world.listAliases(params)
      const aliases = data.items || data || []
      this._aliases = aliases
      this._aliasTotal = Number(data.total ?? aliases.length) || 0
      html = description + (reviewOnly ? this._renderAliasReviewFilters() : "")
      if (aliases.length === 0) {
        return html + `<div class="empty-state"><p>${reviewOnly ? "没有待处理别名。" : "还没有设置别名。"}</p><p class="world-text-dim">别名可以帮助你管理角色的化名、称号和绰号。</p></div>`
      }
      const typeMap = { name: "名称", title: "称号", nickname: "昵称", alias: "化名", translation: "译名" }
      const scope = "world-aliases"
      const ids = aliases.map((alias) => this._aliasKey(alias)).filter(Boolean)
      reconcileBulkSelection(this, scope, ids)
      html += renderBulkToolbar(this, scope, [
        { action: "review-aliases", label: "批量采用", className: "btn-primary" },
        { action: "delete-aliases", label: "批量删除", className: "btn-danger" },
      ], {
        noun: "别名",
        selectAllIds: ids,
        selectAllLabel: "全选当前别名",
      })
      const aliasGroups = this._groupAliasesByEntity(aliases)
      html += `
      <table class="data-table">
        <thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前别名")}</th><th>对象</th><th>别名</th><th>类型</th><th>状态</th><th>来源</th><th>置信度</th><th>证据</th><th>操作</th></tr></thead>
        <tbody>
      `
      for (const group of aliasGroups) {
        group.aliases.forEach((a, index) => {
          const id = this._aliasKey(a)
          const display = worldAssetDisplay({
            ...a,
            status: a.status === "candidate" || a.needs_review
              ? "candidate"
              : (a.status || (a.display_state ? undefined : "canonical")),
          })
          const statusLabel = display.label
          const statusClass = displayStateBadgeClass(display.displayState)
          const sourceLabel = a.source === "deep_import" ? "深度导入" : (a.source || "-")
          const reviewAction = this._renderAliasReviewAction(a)
          html += `
        <tr data-id="${esc(id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, id, `选择别名 ${a.alias || ""}`)}</td>
          ${index === 0 ? `<td rowspan="${group.aliases.length}" class="world-table-cell--type" style="vertical-align:top;">
            <div>${esc(group.entityName)}</div>
            ${group.aliases.length > 1 ? `<div class="world-text-dim" style="margin-top:4px;">${group.aliases.length} 个别名</div>` : ""}
          </td>` : ""}
          <td>${esc(a.alias)}</td>
          <td>${typeMap[a.alias_type] || esc(a.alias_type)}</td>
          <td><span class="badge ${statusClass}">${statusLabel}</span></td>
          <td class="world-table-cell--muted">${esc(sourceLabel)}</td>
          <td>${a.confidence ? (a.confidence * 100).toFixed(0) + "%" : "-"}</td>
          <td style="max-width:220px;color:var(--text-dim);font-size:12px;">${this._inlineEvidenceHtml(a)}</td>
          <td>
            <div class="row-actions">
              ${reviewAction}
              ${a.managed_by_suggestion ? "" : `<button class="btn btn-sm btn-danger" data-action="delete-alias" data-entity-id="${esc(a.entity_id)}" data-alias="${esc(a.alias)}">删除</button>`}
            </div>
          </td>
        </tr>`
        })
      }
      html += '</tbody></table>'
      html += this._renderPager({
        total: this._aliasTotal,
        skip: this._aliasFilters.skip,
        limit: this._aliasFilters.limit,
        prevAction: "prev-aliases-page",
        nextAction: "next-aliases-page",
      })
    } catch { html += '<div class="empty-state"><p>加载别名失败。</p></div>' }
    return html
  },

  async _renderAliasReviewWorkspace(description) {
    try {
      const filters = this._aliasFilters
      const params = {
        novel_id: state.currentProjectId,
        skip: filters.skip,
        limit: filters.limit,
      }
      for (const key of ["q", "source", "workflow_id", "scene_index", "source_chapter_index", "confidence_min", "confidence_max", "has_quote", "type_kind", "multi_alias_only"]) {
        const value = filters[key]
        if (value === "" || value == null) continue
        if (["scene_index", "source_chapter_index", "confidence_min", "confidence_max"].includes(key)) params[key] = Number(value)
        else if (["has_quote", "multi_alias_only"].includes(key)) params[key] = value === true || value === "true"
        else params[key] = value
      }
      const data = await api.world.listAliasReviewGroups(params)
      this._aliasGroups = data.groups || []
      this._aliases = this._aliasGroups.flatMap((group) => group.members || [])
      this._aliasTotal = Number(data.item_total || 0)
      this._aliasGroupTotal = Number(data.group_total || 0)
      this._reviewCounts.aliases = this._aliasTotal
      const scope = "world-aliases"
      const ids = this._aliases
        .filter((item) => !item.managed_by_suggestion)
        .map((item) => this._aliasKey(item))
      reconcileBulkSelection(this, scope, ids)
      let html = description + this._renderAliasReviewFilters()
      if (!this._aliases.length) {
        return html + '<div class="empty-state"><p>没有待处理别名。</p><p class="world-text-dim">筛选条件会保留；可以清空筛选查看全部队列。</p></div>'
      }
      if (ids.length) {
        html += renderBulkToolbar(this, scope, [
          { action: "review-aliases-batch", label: "批量采用", className: "btn-primary" },
          { action: "ignore-aliases-batch", label: "批量忽略", className: "btn-danger" },
        ], {
          noun: "别名",
          hint: "未编辑条目会原样采用；全选仅作用于当前页",
          selectAllIds: ids,
          selectAllLabel: "全选当前页别名",
        })
      }
      html += `<div class="review-group-list">${this._aliasGroups.map((group) => this._renderAliasReviewGroup(group, scope)).join("")}</div>`
      html += this._renderPager({
        total: this._aliasGroupTotal,
        skip: filters.skip,
        limit: filters.limit,
        prevAction: "prev-aliases-page",
        nextAction: "next-aliases-page",
      })
      return html
    } catch (err) {
      return description + `<div class="empty-state"><p>加载待处理别名失败。</p><p class="world-text-dim">${esc(err?.message || "请稍后重试")}</p></div>`
    }
  },

  _renderAliasReviewGroup(group, scope) {
    const groupIds = (group.members || [])
      .filter((item) => !item.managed_by_suggestion)
      .map((item) => this._aliasKey(item))
    return `
      <section class="review-group-card" data-group-id="${esc(group.group_id)}">
        <header class="review-group-card__header">
          <div class="review-group-card__title">
            <strong>${esc(group.entity_name || "未命名对象")}</strong>
            <span>${esc(group.member_count)} 个待处理别名</span>
          </div>
          <label class="review-group-select-all">${renderSelectionHeader(this, scope, groupIds, `全选 ${group.entity_name || "对象"} 的别名`)}<span>全选本组</span></label>
        </header>
        <div class="review-group-card__members">
          ${(group.members || []).map((item) => {
            const key = this._aliasKey(item)
            const draft = this._aliasReviewDrafts[key]
            const reviewError = this._aliasReviewErrors[key]
            const managedBySuggestion = item.managed_by_suggestion === true
            return `
              <article class="review-member-row review-member-row--selectable">
                <div class="selection-cell">${managedBySuggestion ? "" : renderSelectionCell(this, scope, key, `选择别名 ${item.alias}`)}</div>
                <div class="review-member-row__main">
                  <div><strong>${esc(item.alias)}</strong> <span>${esc(this._reviewTypeLabel("alias", item.alias_type))}</span>${item.type_kind === "custom" ? '<span class="badge badge-draft">自定义</span>' : ""}${draft ? '<span class="badge badge-canonical">已编辑</span>' : ""}</div>
                  ${item.suggested_alias_type && item.suggested_alias_type !== item.alias_type ? `<div class="review-suggestion">建议类型：${esc(this._reviewTypeLabel("alias", item.suggested_alias_type))}（仅点击采用后才会修改）</div>` : ""}
                  ${this._reviewEvidenceSummaryHtml(item, "alias", item.confidence)}
                  ${reviewError ? `<div class="review-item-error" role="alert">${esc(reviewError)}</div>` : ""}
                </div>
                ${managedBySuggestion
                  ? '<span class="world-text-dim">随对象建议处理</span>'
                  : `<button class="btn btn-sm btn-primary" data-action="prepare-alias-review" data-entity-id="${esc(item.entity_id)}" data-alias="${esc(item.alias)}">编辑决策</button>`}
              </article>
            `
          }).join("")}
        </div>
      </section>
    `
  },

  _renderAliasReviewFilters() {
    const content = `
      <div class="filter-bar" style="margin-bottom:12px;">
        <input class="form-input" id="review-alias-source" value="${esc(this._aliasFilters.source)}" placeholder="来源" />
        <details class="world-diagnostic-filter" ${this._aliasFilters.workflow_id ? "open" : ""}>
          <summary>诊断筛选</summary>
          <input class="form-input" id="review-alias-workflow" data-diagnostic-field value="${esc(this._aliasFilters.workflow_id)}" placeholder="Workflow ID" />
        </details>
        <input class="form-input" id="review-alias-scene" value="${esc(this._aliasFilters.scene_index)}" placeholder="Scene" />
        <input class="form-input" id="review-alias-chapter" value="${esc(this._aliasFilters.source_chapter_index)}" placeholder="章节序号" />
        <input class="form-input" id="review-alias-confidence-min" value="${esc(this._aliasFilters.confidence_min)}" placeholder="最低置信度" />
        <select class="form-select" id="review-alias-type-kind">
          <option value="">全部类型</option>
          <option value="recommended" ${this._aliasFilters.type_kind === "recommended" ? "selected" : ""}>推荐类型</option>
          <option value="custom" ${this._aliasFilters.type_kind === "custom" ? "selected" : ""}>自定义类型</option>
        </select>
        <select class="form-select" id="review-alias-page-size">
          <option value="20" ${Number(this._aliasFilters.limit) === 20 ? "selected" : ""}>每页 20 组</option>
          <option value="50" ${Number(this._aliasFilters.limit) === 50 ? "selected" : ""}>每页 50 组</option>
        </select>
        <button class="btn btn-sm" data-action="apply-alias-review-filters">筛选</button>
        <button class="btn btn-sm" data-action="reset-alias-review-filters">清空</button>
      </div>
    `
    return `
      <div class="review-search-bar">
        <input class="form-input" id="review-alias-q" value="${esc(this._aliasFilters.q)}" placeholder="搜索别名、对象或引用" aria-label="搜索待处理别名" />
        <button class="btn btn-sm btn-primary" data-action="apply-alias-review-filters">搜索</button>
      </div>
      <div class="review-quick-filters">
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="multi_alias_only" data-filter-value="true">同对象多别名</button>
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="type_kind" data-filter-value="custom">自定义类型</button>
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="has_quote" data-filter-value="false">缺少引用</button>
        <button class="btn btn-sm" data-action="set-alias-quick-filter" data-filter-key="confidence_min" data-filter-value="0.95">高置信度</button>
      </div>
      ${this._renderReviewFilterChips("alias")}
      ${this._renderFilterPanel(
      "review-aliases",
      content,
      ["source", "workflow_id", "scene_index", "source_chapter_index", "confidence_min", "confidence_max", "has_quote", "type_kind", "multi_alias_only"]
        .some((key) => Boolean(this._aliasFilters[key])),
      )}
    `
  },

  _renderReviewFilterChips(kind) {
    const filters = kind === "alias" ? this._aliasFilters : this._relationFilters
    const labels = {
      q: "搜索", relation_type: "关系类型", source: "来源", workflow_id: "Workflow",
      scene_index: "Scene", source_chapter_index: "章节", confidence_min: "最低置信度",
      confidence_max: "最高置信度", strength_min: "最低强度", strength_max: "最高强度",
      has_quote: "引用", type_kind: "类型范围", multi_alias_only: "同对象多别名",
      multi_type_only: "同对象对多类型",
    }
    const chips = Object.entries(filters)
      .filter(([key, value]) => !["skip", "limit"].includes(key) && value !== "" && value != null && value !== false)
      .map(([key, value]) => {
        const display = key === "has_quote" ? (String(value) === "false" ? "缺少" : "有") : value
        return `<button class="review-filter-chip" data-action="remove-review-filter" data-filter-kind="${esc(kind)}" data-filter-key="${esc(key)}">${esc(labels[key] || key)}：${esc(display)} ×</button>`
      })
    return chips.length ? `<div class="review-filter-chips">${chips.join("")}</div>` : ""
  },

  _aliasKey(alias) {
    if (!alias) return ""
    return `${alias.entity_id || ""}::${alias.alias || ""}`
  },

  _renderAliasReviewAction(alias) {
    if (!alias?.entity_id || !alias?.alias) return ""
    if (alias.managed_by_suggestion) {
      return '<span class="world-text-dim">随对象建议处理</span>'
    }
    const attrs = `data-entity-id="${esc(alias.entity_id)}" data-alias="${esc(alias.alias)}"`
    const status = alias.status === "candidate" || alias.needs_review
      ? "candidate"
      : (alias.status || (alias.display_state ? undefined : "canonical"))
    if (worldAssetDisplay({ ...alias, status }).displayState === "review") {
      return `
        <button class="btn btn-sm btn-primary" data-action="edit-alias-review" ${attrs}>编辑后采用</button>
        <button class="btn btn-sm" data-action="mark-alias-reviewed" ${attrs}>采用</button>
      `
    }
    return ""
  },

  _groupAliasesByEntity(aliases) {
    const groups = []
    const byEntity = new Map()
    for (const alias of aliases || []) {
      const entityKey = alias.entity_id || alias.entity_name || "__unknown__"
      let group = byEntity.get(entityKey)
      if (!group) {
        group = {
          entityId: alias.entity_id || "",
          entityName: alias.entity_name || ((alias.entity_id || "").slice(0, 8) + "..."),
          aliases: [],
        }
        byEntity.set(entityKey, group)
        groups.push(group)
      }
      group.aliases.push(alias)
    }
    return groups
  },

  _aliasTypeOptionsHtml(selected = "alias") {
    const types = [...(this._reviewTypeCatalog.alias_types || REVIEW_ALIAS_TYPE_FALLBACK)]
    if (selected && !types.some((item) => item.value === selected)) {
      types.unshift({ value: selected, label: `保留原类型：${selected}`, category: "自定义" })
    }
    return types
      .map((item) => `<option value="${esc(item.value)}" ${selected === item.value ? "selected" : ""}>${esc(item.label)}${item.category === "自定义" ? "" : ` (${esc(item.value)})`}</option>`)
      .join("")
  },

  _findAlias(entityId, aliasText) {
    return (this._aliases || []).find((item) => item.entity_id === entityId && item.alias === aliasText) || null
  },

  _aliasEvidenceHtml(item = {}) {
    const evidence = [
      ["来源", item.source === "deep_import" ? "深度导入" : item.source],
      ["Workflow", item.workflow_id],
      ["章节", item.source_chapter_index],
      ["Scene", item.scene_id || item.scene_index],
      ["置信度", item.confidence != null ? `${(Number(item.confidence) * 100).toFixed(0)}%` : ""],
      ["引用", item.quote],
    ].filter(([, value]) => value != null && String(value).trim() !== "")
    if (!evidence.length) return ""
    return `
      <div class="form-group">
        <label>证据</label>
        <div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px;color:var(--text-muted);font-size:12px;">
          ${evidence.map(([label, value]) => `<div><strong>${esc(label)}：</strong>${esc(value)}</div>`).join("")}
        </div>
      </div>
    `
  },

  _isAliasTargetEntity(entity) {
    return ["draft", "canonical", "candidate"].includes(entity?.status)
      && !entity?.content_json?._meta?.compatibility_shadow
  },

  _destroyReferencePickers() {
    for (const picker of this._referencePickers || []) picker?.destroy?.()
    this._referencePickers = []
  },

  _entityReferenceItem(entity) {
    const display = worldAssetDisplay(entity)
    return {
      kind: "entity",
      id: this._entityId(entity),
      label: entity?.name || "未命名对象",
      description: [entity?.entity_type || "世界对象", entity?.summary || entity?.public_info].filter(Boolean).join(" · "),
      status: display.label,
      unavailable: display.isHistory,
    }
  },

  _mountEntityReferencePicker({
    rootId,
    inputId,
    sourceId = "",
    selectedId = "",
    selectedName = "",
    canonicalOnly = false,
  }) {
    const root = document.getElementById(rootId)
    const input = document.getElementById(inputId)
    if (!root || !input) return null
    this._destroyReferencePickers()
    const eligible = canonicalOnly
      ? (item) => this._isMergeTargetEntity(item)
      : (item) => this._isAliasTargetEntity(item)
    const source = {
      kind: "entity",
      label: "世界对象",
      search: async (query, { projectId, limit }) => {
        const data = await api.world.listEntities({
          novel_id: projectId,
          q: query || undefined,
          ...(canonicalOnly ? { display_state: "active" } : {}),
          skip: 0,
          limit,
        })
        return (data?.items || data || [])
          .filter((item) => this._entityId(item) !== sourceId)
          .filter(eligible)
          .map((item) => this._entityReferenceItem(item))
      },
      resolve: async (ids, { projectId }) => Promise.all(ids.map(async (id) => {
        try {
          const entity = await api.world.getEntity(id, projectId)
          if (this._entityId(entity) === sourceId || !eligible(entity)) {
            return { kind: "entity", id, label: entity?.name || "不可用引用", unavailable: true }
          }
          return this._entityReferenceItem(entity)
        } catch {
          return { kind: "entity", id, label: "不可用引用", unavailable: true }
        }
      })),
    }
    const selectedEntity = selectedId ? this._findEntity(selectedId) : null
    const initialItems = selectedId && selectedEntity && eligible(selectedEntity)
      ? [this._entityReferenceItem(selectedEntity)]
      : selectedId && selectedName
        ? [{ kind: "entity", id: selectedId, label: selectedName, description: "已选目标" }]
        : []
    const picker = createReferencePicker({
      root,
      projectId: state.currentProjectId,
      sources: [source],
      initialItems,
      placeholder: "按名称或别名搜索目标对象",
      onChange: (_items, refs) => {
        input.value = refs[0]?.id || ""
        input.dataset.referenceLabel = _items[0]?.label || ""
      },
    })
    if (selectedId && !initialItems.length) picker.resolve([{ kind: "entity", id: selectedId }])
    this._referencePickers.push(picker)
    return picker
  },

  showAliasCreateForm() {
    const entityOptions = this._entityOptionsHtml()
    const formHtml = `
      <div class="form-group">
        <label>所属对象</label>
        <select class="form-select" id="alias-entity"><option value="">请选择</option>${entityOptions}</select>
      </div>
      <div class="form-group">
        <label>别名文本</label>
        <input class="form-input" id="alias-text" placeholder="别名" />
      </div>
      <div class="form-group">
        <label>别名类型</label>
        <select class="form-select" id="alias-type">
          <option value="name">名称</option>
          <option value="title">称号</option>
          <option value="nickname">昵称</option>
          <option value="alias">化名</option>
          <option value="translation">译名</option>
        </select>
      </div>
    `
    showModalHtml("新建别名", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const eid = document.getElementById("alias-entity")?.value
        const text = document.getElementById("alias-text")?.value
        if (!eid || !text) { toast("请选择对象并输入别名", "warning"); return }
        try {
          await api.world.createAlias({
            entity_id: eid,
            alias: text,
            alias_type: document.getElementById("alias-type")?.value || "name",
          }, state.currentProjectId)
          toast("别名已创建", "success")
          router.navigate("world", "aliases")
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  deleteAlias(entityId, alias) {
    if (!entityId || !alias) {
      toast("参数错误：缺少实体 ID 或别名", "error")
      return
    }
    confirmAction(`确定删除别名 "${esc(alias)}"？`, async () => {
      try {
        await api.world.deleteAlias(entityId, alias, { novel_id: state.currentProjectId })
        toast("已删除", "success")
        router.navigate("world", "aliases")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, `确认删除别名 "${esc(alias)}"`)
  },

  showAliasReviewDecisionForm(entityId, aliasText) {
    const alias = this._findAlias(entityId, aliasText)
    if (!alias) return toast("未找到目标别名", "error")
    const key = this._aliasKey(alias)
    const draft = this._aliasReviewDrafts[key]
    const selectedTargetId = draft?.target_entity_id || entityId
    const suggested = alias.suggested_alias_type && alias.suggested_alias_type !== alias.alias_type
      ? `<button class="btn btn-sm" type="button" id="alias-use-type-suggestion">使用建议：${esc(this._reviewTypeLabel("alias", alias.suggested_alias_type))}</button>`
      : ""
    const body = `
      <div class="review-decision-layout">
      <div class="form-group"><label>目标对象</label><div id="alias-target-picker"></div><input type="hidden" id="alias-target-id" value="${esc(selectedTargetId)}" /></div>
      <div class="form-group"><label for="alias-edit-text">别名文本</label><input class="form-input" id="alias-edit-text" value="${esc(draft?.alias || alias.alias)}" /></div>
      <div class="form-group"><label for="alias-edit-type">别名类型</label><select class="form-select" id="alias-edit-type">${this._aliasTypeOptionsHtml(draft?.alias_type || alias.alias_type || "alias")}</select>${suggested}</div>
      ${this._reviewEvidenceSummaryHtml(alias, "alias", alias.confidence)}
      <p class="form-help">来源、Scene、引用和置信度只读；保存这里只准备决策，最后仍需批量确认。</p>
      </div>
    `
    showModalHtml("准备别名复核决策", body, [{
      text: "保存决策",
      class: "btn-primary",
      handler: async () => {
        const targetId = document.getElementById("alias-target-id")?.value || ""
        const text = document.getElementById("alias-edit-text")?.value?.trim() || ""
        const aliasType = document.getElementById("alias-edit-type")?.value || ""
        if (!targetId || !text || !aliasType) {
          toast("请选择目标对象并填写别名和类型", "warning")
          return false
        }
        this._aliasReviewDrafts[key] = {
          target_entity_id: targetId,
          alias: text,
          alias_type: aliasType,
        }
        delete this._aliasReviewErrors[key]
        closeModal()
        await this._rerenderCurrentSubViewInPlace()
      },
    }], { size: "large" })
    this._bindReviewDiagnosticCopyButtons(document.getElementById("modal-body"))
    this._mountEntityReferencePicker({
      rootId: "alias-target-picker",
      inputId: "alias-target-id",
      selectedId: selectedTargetId,
      selectedName: alias.entity_name || "当前对象",
    })
    const suggestionButton = document.getElementById("alias-use-type-suggestion")
    if (suggestionButton) {
      suggestionButton.onclick = () => {
        const select = document.getElementById("alias-edit-type")
        if (select) select.value = alias.suggested_alias_type
      }
    }
  },

  showAliasReviewEditForm(entityId, aliasText) {
    const alias = this._findAlias(entityId, aliasText)
    if (!alias) {
      toast("未找到目标别名", "error")
      return
    }
    const formHtml = `
      <div class="form-group">
        <label>目标对象 *</label>
        <div id="alias-target-picker"></div>
        <input type="hidden" id="alias-target-id" value="${esc(entityId)}" />
      </div>
      <div class="form-group">
        <label>别名文本 *</label>
        <input class="form-input" id="alias-edit-text" value="${esc(alias.alias || "")}" />
      </div>
      <div class="form-group">
        <label>别名类型</label>
        <select class="form-select" id="alias-edit-type">${this._aliasTypeOptionsHtml(alias.alias_type || "alias")}</select>
      </div>
      ${this._aliasEvidenceHtml(alias)}
    `
    showModalHtml("编辑后采用别名", formHtml, [{
      text: "保存并采用",
      class: "btn-primary",
      handler: async () => {
        const targetId = document.getElementById("alias-target-id")?.value
        const text = document.getElementById("alias-edit-text")?.value?.trim()
        const type = document.getElementById("alias-edit-type")?.value || "alias"
        if (!targetId || !text) {
          toast("请选择目标对象并输入别名", "warning")
          return
        }
        try {
          await api.world.editAlias(entityId, aliasText, {
            target_entity_id: targetId,
            alias: text,
            alias_type: type,
            confirm_review: true,
          }, { novel_id: state.currentProjectId })
          toast("别名已保存并采用", "success")
          await this._refreshCurrentSubViewInPlace()
        } catch (err) {
          toast(err.message || "保存失败", "error")
        }
      },
    }])
    this._mountEntityReferencePicker({
      rootId: "alias-target-picker",
      inputId: "alias-target-id",
      selectedId: entityId,
      selectedName: alias.entity_name || "当前对象",
    })
  },

  showResolveAliasForm(candidateId) {
    const candidate = this._candidates.find((item) => this._entityId(item) === candidateId)
    if (!candidate) {
      toast("未找到目标待处理项", "error")
      return
    }
    const suggestionId = this._suggestionId(candidate)
    const targetId = this._candidateTargetId(candidate)
    const targetName = this._candidateTargetName(candidate)
    const formHtml = `
      <p style="margin-bottom:10px;">将 <strong>${esc(candidate.name || "")}</strong> 登记为已有对象的别名。</p>
      <div class="form-group">
        <label>目标对象 *</label>
        <div id="alias-target-picker"></div>
        <input type="hidden" id="alias-target-id" value="${esc(targetId)}" />
      </div>
      <div class="form-group">
        <label>别名文本 *</label>
        <input class="form-input" id="alias-edit-text" value="${esc(candidate.name || "")}" />
      </div>
      <div class="form-group">
        <label>别名类型</label>
        <select class="form-select" id="alias-edit-type">${this._aliasTypeOptionsHtml("alias")}</select>
      </div>
      ${this._aliasEvidenceHtml(this._candidateMeta(candidate))}
    `
    showModalHtml("设为别名", formHtml, [{
      text: "设为别名",
      class: "btn-primary",
      handler: async () => {
        const selectedTargetId = document.getElementById("alias-target-id")?.value
        const text = document.getElementById("alias-edit-text")?.value?.trim()
        const type = document.getElementById("alias-edit-type")?.value || "alias"
        if (!selectedTargetId || !text) {
          toast("请选择目标对象并输入别名", "warning")
          return
        }
        try {
          const payload = {
            target_entity_id: selectedTargetId,
            alias: text,
            alias_type: type,
          }
          const result = suggestionId
            ? await api.world.resolveSuggestionAsAlias(
              suggestionId,
              payload,
              state.currentProjectId,
            )
            : await api.world.resolveEntityAsAlias(
              candidateId,
              payload,
              state.currentProjectId,
            )
          await this._refreshCandidatesAfterAffectedMutation(
            result?.result_ref_json || result,
          )
          toast("待处理项已设为别名", "success")
          router.navigate("world", "candidates")
        } catch (err) {
          toast(err.message || "设为别名失败", "error")
        }
      },
    }])
    this._mountEntityReferencePicker({
      rootId: "alias-target-picker",
      inputId: "alias-target-id",
      sourceId: candidateId,
      selectedId: targetId,
      selectedName: targetName,
    })
  },

  async _markEntityReviewed(id) {
    let entity = this._findEntity(id)
    try {
      const fetched = await api.world.getEntity(id, state.currentProjectId)
      if (fetched) entity = fetched
    } catch {
      // 列表数据足够完成检查标记；详情读取失败不阻断单项操作。
    }
    if (!entity) {
      toast("未找到目标世界对象", "error")
      return false
    }
    try {
      await api.world.updateEntity(id, {
        content_json: this._entityReviewContent(entity, true, "world_objects"),
      }, state.currentProjectId)
      toast("世界对象已标记为已检查", "success")
      await this._refreshCurrentSubViewInPlace()
      return true
    } catch (err) {
      toast(`世界对象检查状态更新失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async _markEntityUnreviewed(id) {
    let entity = this._findEntity(id)
    try {
      const fetched = await api.world.getEntity(id, state.currentProjectId)
      if (fetched) entity = fetched
    } catch {
      // 列表数据足够完成检查标记；详情读取失败不阻断单项操作。
    }
    if (!entity) {
      toast("未找到目标世界对象", "error")
      return false
    }
    try {
      await api.world.updateEntity(id, {
        content_json: this._entityReviewContent(entity, false, "world_objects"),
      }, state.currentProjectId)
      toast("世界对象已标记为需要人工检查", "success")
      await this._refreshCurrentSubViewInPlace()
      return true
    } catch (err) {
      toast(`世界对象检查状态更新失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async _markRelationReviewed(id) {
    try {
      await api.world.reviewEditRelationship(id, { confirm_review: true }, state.currentProjectId)
      toast("关系已采用", "success")
      await this._refreshCurrentSubViewInPlace()
      return true
    } catch (err) {
      toast(`关系采用失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async _markRelationUnreviewed(id) {
    try {
      await api.world.updateRelationship(id, { status: "candidate" }, state.currentProjectId)
      toast("关系已移回待处理", "success")
      await this._refreshCurrentSubViewInPlace()
      return true
    } catch (err) {
      toast(`关系移回待处理失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async _markAliasReviewed(entityId, alias) {
    try {
      await api.world.updateAlias(entityId, alias, {
        status: "canonical",
        needs_review: false,
        reviewed_at: new Date().toISOString(),
        reviewed_by: "manual",
        reviewed_from: "world_aliases",
      }, { novel_id: state.currentProjectId })
      toast("别名已采用", "success")
      await this._refreshCurrentSubViewInPlace()
      return true
    } catch (err) {
      toast(`别名采用失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async _markAliasUnreviewed(entityId, alias) {
    try {
      await api.world.updateAlias(entityId, alias, {
        status: "candidate",
        needs_review: true,
        reviewed_at: null,
        reviewed_by: null,
        reviewed_from: null,
      }, { novel_id: state.currentProjectId })
      toast("别名已移回待处理", "success")
      await this._refreshCurrentSubViewInPlace()
      return true
    } catch (err) {
      toast(`别名移回待处理失败：${err.message || "未知错误"}`, "error")
      return false
    }
  },

  async _finishEntityMutation(successMessage, lifecycleEpoch) {
    if (lifecycleEpoch !== this._lifecycleEpoch) return true
    try {
      const refreshed = await router.refresh()
      if (refreshed === false) throw new Error("当前页面未完成刷新")
    } catch (err) {
      if (lifecycleEpoch === this._lifecycleEpoch) {
        toast(`${successMessage}，但列表刷新失败：${err.message || "未知错误"}`, "warning")
      }
      return true
    }
    if (lifecycleEpoch === this._lifecycleEpoch) toast(successMessage, "success")
    return true
  },

  editEntity(id) {
    const entity = this._findEntity(id)
    if (!entity) return
    const suggestionId = this._suggestionId(entity)
    const isPending = ["draft", "candidate"].includes(entity.status)
    let submissionPending = false

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-entity-name" value="${esc(entity.name)}" />
      </div>
      <div class="form-group">
        <label>类型</label>
        ${this._entityTypeControlHtml("edit", entity.entity_type)}
      </div>
      <div class="form-group">
        <label>概要</label>
        <textarea class="form-textarea" id="edit-entity-summary" rows="3">${esc(entity.summary || "")}</textarea>
      </div>
      <div id="edit-entity-error" class="alert alert-error" hidden></div>
    `

    showModalHtml(isPending ? "编辑后采用世界对象" : "编辑世界对象", formHtml, [
      {
        text: isPending ? "编辑后采用" : "保存",
        class: "btn-primary",
        handler: async () => {
          if (submissionPending) return false
          const lifecycleEpoch = this._lifecycleEpoch
          const projectId = state.currentProjectId
          const payload = {
            name: document.getElementById("edit-entity-name")?.value,
            entity_type: this._readEntityType("edit"),
            summary: document.getElementById("edit-entity-summary")?.value,
          }
          if (!payload.entity_type) {
            const target = document.getElementById("edit-entity-error")
            if (target) {
              target.textContent = "请输入自定义类型名称"
              target.hidden = false
            }
            return false
          }
          if (!isPending && payload.entity_type !== entity.entity_type) {
            const confirmed = window.confirm(
              "更改类型会迁移对象档案；若仍有地图、人物或事件等专属依赖，保存将被阻止。是否继续？",
            )
            if (!confirmed) return false
          }
          submissionPending = true
          try {
            if (suggestionId) {
              await api.world.editAndConfirmSuggestion(
                suggestionId,
                payload,
                projectId,
              )
            } else if (isPending) {
              await api.world.promoteEntity(id, projectId, payload)
            } else {
              await api.world.updateEntity(id, payload, projectId)
            }
          } catch (err) {
            submissionPending = false
            if (lifecycleEpoch !== this._lifecycleEpoch) return true
            if (!this._showEntityTypeBlocker(err, "edit-entity-error")) {
              const target = document.getElementById("edit-entity-error")
              if (target) {
                target.textContent = `保存失败：${err.message || "未知错误"}`
                target.hidden = false
              }
            }
            return false
          }
          return this._finishEntityMutation(
            isPending ? "已编辑并采用" : "已保存",
            lifecycleEpoch,
          )
        },
      },
    ])
    this._bindEntityTypeControl("edit")
  },

  async _adoptEntity(entity) {
    const suggestionId = this._suggestionId(entity)
    if (suggestionId) {
      return api.world.confirmSuggestion(suggestionId, state.currentProjectId)
    }
    return api.world.promoteEntity(this._entityId(entity), state.currentProjectId)
  },

  async _ignoreEntity(entity) {
    const suggestionId = this._suggestionId(entity)
    if (suggestionId) {
      return api.world.rejectSuggestion(suggestionId, state.currentProjectId)
    }
    return api.world.updateEntity(
      this._entityId(entity),
      { status: "ignored" },
      state.currentProjectId,
    )
  },

  async _ignoreOrDeleteEntity(entity) {
    const suggestionId = this._suggestionId(entity)
    if (suggestionId) {
      return api.world.rejectSuggestion(suggestionId, state.currentProjectId)
    }
    return api.world.deleteEntity(this._entityId(entity), state.currentProjectId)
  },

  deleteEntity(id) {
    const entity = this._findEntity(id)
    const suggestionShadow = this._isSuggestionShadow(entity)
    const message = suggestionShadow
      ? `确定忽略待处理项“${esc(entity?.name || id)}”吗？`
      : "确定要删除此世界对象吗？此操作不可撤销。"
    confirmAction(message, async () => {
      try {
        await this._ignoreOrDeleteEntity(entity || { id })
        toast(suggestionShadow ? "已忽略" : "已删除", "success")
        router.refresh()
      } catch (err) {
        toast(`删除失败：${err.message}`, "error")
      }
    }, "确认删除")
  },

  promoteEntity(id) {
    const entity = this._findEntity(id)
    if (!entity) return

    confirmAction(
      `确定采用“${esc(entity.name)}”吗？采用后将作为当前有效世界设定参与后续创作。`,
      async () => {
        try {
          await this._adoptEntity(entity)
          toast("世界对象已采用", "success")
          router.refresh()
        } catch (err) {
          toast(`采用失败：${err.message}`, "error")
        }
      },
      "确认采用",
    )
  },

  async acceptCandidate(id) {
    const candidate = this._candidates.find((c) => (c.id || c.entity_id) === id)
    if (!candidate) return

    return confirmAction(
      `确定采用“${esc(candidate.name)}”吗？`,
      async () => {
        const snapshot = await this._removeCandidateOptimistically(id)
        try {
          await this._adoptEntity(candidate)
          toast(`“${candidate.name}”已采用`, "success")
          await this._reloadWorldLists()
          await this._navigateWithQuery(state.currentSubView || "candidates", this._candidateQueryFromState())
        } catch (err) {
          await this._restoreCandidateSnapshot(snapshot)
          toast(`处理失败：${err.message}`, "error")
        }
      },
      "确认采用",
    )
  },

  async ignoreCandidate(id) {
    const candidate = this._candidates.find((c) => (c.id || c.entity_id) === id)
    const isTemporary = this._candidateAction(candidate) === "temporary_only"
    return confirmAction(
      isTemporary
        ? `将“${candidate?.name || id}”标记为临时并从待处理中移除？`
        : `确定忽略待处理项“${candidate?.name || id}”？`,
      async () => {
        const snapshot = await this._removeCandidateOptimistically(id)
        try {
          await this._ignoreEntity(candidate)
          toast(isTemporary ? "已设为临时" : "已忽略", "success")
          await this._reloadWorldLists()
          await this._navigateWithQuery(state.currentSubView || "candidates", this._candidateQueryFromState())
        } catch (err) {
          await this._restoreCandidateSnapshot(snapshot)
          toast(`操作失败：${err.message}`, "error")
        }
      },
      isTemporary ? "设为临时" : "忽略",
    )
  },

  _entityOptionsHtml() {
    if (!this._entities || this._entities.length === 0) {
      return `<option value="">暂无对象</option>`
    }
    return this._entities
      .map((e) => {
        const id = e.id || e.entity_id
        const label = `${e.name} (${e.entity_type})`
        return `<option value="${esc(id)}">${esc(label)}</option>`
      })
      .join("")
  },

  _relationEntityOptionsHtml(selectedId = "") {
    const items = [...(this._entities || []), ...(this._candidates || [])]
      .filter((item) => !["merged", "ignored", "deprecated"].includes(item.status))
    const seen = new Set()
    const options = []
    for (const item of items) {
      const id = this._entityId(item)
      if (!id || seen.has(id)) continue
      seen.add(id)
      const label = `${item.name || id} (${item.entity_type || "-"})`
      options.push(`<option value="${esc(id)}" ${id === selectedId ? "selected" : ""}>${esc(label)}</option>`)
    }
    if (!seen.has(selectedId) && selectedId) {
      options.unshift(`<option value="${esc(selectedId)}" selected>${esc(selectedId)}</option>`)
    }
    return options.length ? options.join("") : `<option value="">暂无对象</option>`
  },

  async _applyFilters() {
    const entityType = document.getElementById("filter-entity-type")?.value || ""
    const displayState = document.getElementById("filter-display-state")?.value || "active"
    const q = document.getElementById("filter-q")?.value || ""
    const source = document.getElementById("filter-source")?.value || ""
    const workflowId = document.getElementById("filter-workflow-id")?.value?.trim() || ""
    const needsReview = document.getElementById("filter-needs-review")?.value || ""
    const autoIngested = document.getElementById("filter-auto-ingested")?.value || ""
    const nextFilters = {
      ...WORLD_FILTER_DEFAULTS,
      entity_type: entityType,
      display_state: displayState,
      q,
      source,
      workflow_id: workflowId,
      needs_review: needsReview,
      auto_ingested: autoIngested,
      skip: 0,
    }
    await this._navigateWithQuery("objects", this._objectQueryFromState(nextFilters))
  },

  async _resetFilters() {
    this._advancedFiltersOpen = false
    await this._navigateWithQuery(
      "objects",
      this._objectQueryFromState({ ...WORLD_FILTER_DEFAULTS }, "table"),
    )
  },

  async _setDiscoveryMode(mode) {
    if (mode !== "normal" && mode !== "hot") return
    if (mode === this._discoveryMode) return
    this._discoveryMode = mode
    this._rememberDiscoveryMode(mode)
    clearBulkSelection(this, "world-objects")
    const nextFilters = { ...this._filters, focus: "", skip: 0 }
    await this._navigateWithQuery("objects", this._objectQueryFromState(nextFilters))
  },

  async _setHotFocus(focus) {
    if (this._discoveryMode !== "hot") return
    const next = this._filters.focus === focus ? "" : focus
    const nextFilters = { ...this._filters, focus: next, skip: 0 }
    await this._navigateWithQuery("objects", this._objectQueryFromState(nextFilters))
  },

  async _setHotType(entityType) {
    if (this._discoveryMode !== "hot") return
    const nextFilters = {
      ...this._filters,
      entity_type: this._filters.entity_type === entityType ? "" : entityType,
      skip: 0,
    }
    await this._navigateWithQuery("objects", this._objectQueryFromState(nextFilters))
  },

  async _applyCandidateReviewFilters() {
    const entityTypeSelect = document.getElementById("review-candidate-entity-type")
    this._candidateFilters = {
      ...WORLD_CANDIDATE_FILTER_DEFAULTS,
      entity_type: entityTypeSelect
        ? entityTypeSelect.value
        : (this._candidateFilters.entity_type || ""),
      suggested_action: document.getElementById("review-candidate-action")?.value || "",
      source: document.getElementById("review-candidate-source")?.value?.trim() || "",
      workflow_id: document.getElementById("review-candidate-workflow")?.value?.trim() || "",
      scene_index: document.getElementById("review-candidate-scene")?.value?.trim() || "",
      source_chapter_index: document.getElementById("review-candidate-chapter")?.value?.trim() || "",
      confidence_min: document.getElementById("review-candidate-confidence-min")?.value?.trim() || "",
      confidence_max: document.getElementById("review-candidate-confidence-max")?.value?.trim() || "",
    }
    await this._navigateWithQuery(state.currentSubView || "review-objects", this._candidateQueryFromState())
  },

  async _resetCandidateReviewFilters() {
    this._candidateFilters = { ...WORLD_CANDIDATE_FILTER_DEFAULTS }
    await this._navigateWithQuery(state.currentSubView || "review-objects", this._candidateQueryFromState())
  },

  async _applyAliasReviewFilters() {
    const previousLimit = this._aliasFilters.limit
    this._aliasFilters = {
      ...WORLD_ALIAS_FILTER_DEFAULTS,
      q: document.getElementById("review-alias-q")?.value?.trim() || "",
      source: document.getElementById("review-alias-source")?.value?.trim() || "",
      workflow_id: document.getElementById("review-alias-workflow")?.value?.trim() || "",
      scene_index: document.getElementById("review-alias-scene")?.value?.trim() || "",
      source_chapter_index: document.getElementById("review-alias-chapter")?.value?.trim() || "",
      confidence_min: document.getElementById("review-alias-confidence-min")?.value?.trim() || "",
      type_kind: document.getElementById("review-alias-type-kind")?.value || "",
      has_quote: this._aliasFilters.has_quote,
      multi_alias_only: this._aliasFilters.multi_alias_only,
      limit: Number(document.getElementById("review-alias-page-size")?.value || previousLimit || 20),
    }
    await this._navigateWithQuery("review-aliases", this._reviewQueryFromState(this._aliasFilters, WORLD_ALIAS_QUERY_KEYS))
  },

  async _resetAliasReviewFilters() {
    this._aliasFilters = { ...WORLD_ALIAS_FILTER_DEFAULTS }
    await this._navigateWithQuery("review-aliases", this._reviewQueryFromState(this._aliasFilters, WORLD_ALIAS_QUERY_KEYS))
  },

  async _applyRelationReviewFilters() {
    const previousLimit = this._relationFilters.limit
    this._relationFilters = {
      ...WORLD_RELATION_FILTER_DEFAULTS,
      q: document.getElementById("review-relation-q")?.value?.trim() || "",
      relation_type: document.getElementById("review-relation-type")?.value?.trim() || "",
      scene_index: document.getElementById("review-relation-scene")?.value?.trim() || "",
      source_chapter_index: document.getElementById("review-relation-source-chapter")?.value?.trim() || "",
      strength_min: document.getElementById("review-relation-strength-min")?.value?.trim() || "",
      type_kind: document.getElementById("review-relation-type-kind")?.value || "",
      has_quote: this._relationFilters.has_quote,
      multi_type_only: this._relationFilters.multi_type_only,
      strength_max: this._relationFilters.strength_max,
      limit: Number(document.getElementById("review-relation-page-size")?.value || previousLimit || 20),
    }
    await this._navigateWithQuery("review-relations", this._reviewQueryFromState(this._relationFilters, WORLD_RELATION_QUERY_KEYS))
  },

  async _resetRelationReviewFilters() {
    this._relationFilters = { ...WORLD_RELATION_FILTER_DEFAULTS }
    await this._navigateWithQuery("review-relations", this._reviewQueryFromState(this._relationFilters, WORLD_RELATION_QUERY_KEYS))
  },

  async _setReviewQuickFilter(kind, key, value) {
    const filters = kind === "alias" ? this._aliasFilters : this._relationFilters
    filters[key] = value
    filters.skip = 0
    const keys = kind === "alias" ? WORLD_ALIAS_QUERY_KEYS : WORLD_RELATION_QUERY_KEYS
    await this._navigateWithQuery(`review-${kind === "alias" ? "aliases" : "relations"}`, this._reviewQueryFromState(filters, keys))
  },

  async _applyRelationSceneQuickFilter() {
    const value = document.getElementById("review-relation-scene-quick")?.value?.trim() || ""
    await this._setReviewQuickFilter("relation", "scene_index", value)
  },

  async _removeReviewFilter(kind, key) {
    const filters = kind === "alias" ? this._aliasFilters : this._relationFilters
    if (!(key in filters)) return
    filters[key] = ""
    filters.skip = 0
    const keys = kind === "alias" ? WORLD_ALIAS_QUERY_KEYS : WORLD_RELATION_QUERY_KEYS
    await this._navigateWithQuery(`review-${kind === "alias" ? "aliases" : "relations"}`, this._reviewQueryFromState(filters, keys))
  },

  async _changePage(delta) {
    const newSkip = this._filters.skip + delta * this._filters.limit
    if (newSkip < 0) return
    if (newSkip >= this._total) return
    const nextFilters = { ...this._filters, skip: newSkip }
    await this._navigateWithQuery("objects", this._objectQueryFromState(nextFilters))
  },

  async _changeListPage(filters, total, loader, delta) {
    const newSkip = filters.skip + delta * filters.limit
    if (newSkip < 0) return
    if (newSkip >= total) return
    filters.skip = newSkip
    await loader()
    if (filters === this._candidateFilters) {
      await this._navigateWithQuery(state.currentSubView || "review-objects", this._candidateQueryFromState())
    } else if (filters === this._aliasFilters) {
      const subView = state.currentSubView === "aliases" ? "aliases" : "review-aliases"
      await this._navigateWithQuery(subView, this._reviewQueryFromState(filters, WORLD_ALIAS_QUERY_KEYS))
    } else if (filters === this._relationFilters) {
      const subView = state.currentSubView === "relations" ? "relations" : "review-relations"
      await this._navigateWithQuery(subView, this._reviewQueryFromState(filters, WORLD_RELATION_QUERY_KEYS))
    } else {
      await router.refresh()
    }
  },

  async _changeCandidatePage(delta) {
    await this._changeListPage(this._candidateFilters, this._candidateTotal, () => this._loadCandidates(), delta)
  },

  async _changeRelationPage(delta) {
    await this._changeListPage(this._relationFilters, this._relationGroupTotal || this._relationTotal, async () => {}, delta)
  },

  async _changeAliasPage(delta) {
    await this._changeListPage(this._aliasFilters, this._aliasGroupTotal || this._aliasTotal, async () => {}, delta)
  },

  _bindEvents() {
    if (this._eventsBound) return
    bindWorkspaceClick(this, {
      "nav-objects": () => router.navigate("world", "objects"),
      "nav-candidates": () => router.navigate("world", "candidates"),
      "nav-review": () => router.navigate("world", "review-objects"),
      "nav-review-objects": () => router.navigate("world", "review-objects"),
      "nav-review-aliases": () => router.navigate("world", "review-aliases"),
      "nav-review-relations": () => router.navigate("world", "review-relations"),
      "nav-relations": () => router.navigate("world", "relations"),
      "nav-aliases": () => router.navigate("world", "aliases"),
      "nav-bible": () => router.navigate("world", "bible"),
      "nav-map": () => router.navigate("map", null, true, buildMapQuery({
        projectId: state.currentProjectId,
        mode: "overview",
      })),
      "nav-generate": () => router.navigate("generate"),
      "bulk-toggle-one": (e, t) => {
        e.stopPropagation()
        this._toggleBulkOne(t)
      },
      "bulk-toggle-all": (e, t) => {
        e.stopPropagation()
        this._toggleBulkAll(t)
      },
      "bulk-clear": (e, t) => {
        e.stopPropagation()
        this._clearBulkScope(t.getAttribute("data-scope"))
      },
      "bulk-run": (_e, t) => this._runBulkAction(t.getAttribute("data-scope"), t.getAttribute("data-bulk-action")),
      "set-object-view": (_e, t) => this._setObjectViewMode(t.getAttribute("data-view-mode")),
      "set-discovery-mode": (_e, t) => this._setDiscoveryMode(t.getAttribute("data-mode")),
      "set-hot-focus": (_e, t) => this._setHotFocus(t.getAttribute("data-focus")),
      "set-hot-type": (_e, t) => this._setHotType(t.getAttribute("data-entity-type")),
      "toggle-extract": () => this._toggleAutoExtract(),
      "toggle-advanced-filters": () => this._toggleAdvancedFilters(),
      "toggle-filter-panel": (_e, t) => this._toggleFilterPanel(t.getAttribute("data-filter-key"), t),
      "submit-extract": (_e, t) => this._submitAutoExtract(t.getAttribute("data-type")),
      "edit-entity": (_e, _t, ctx) => ctx.id && this.editEntity(ctx.id),
      "mark-entity-reviewed": (_e, _t, ctx) => ctx.id && this._markEntityReviewed(ctx.id),
      "mark-entity-unreviewed": (_e, _t, ctx) => ctx.id && this._markEntityUnreviewed(ctx.id),
      "open-entity-map": (_e, _t, ctx) => ctx.id && this._openEntityMap(ctx.id),
      "delete-entity": (_e, _t, ctx) => ctx.id && this.deleteEntity(ctx.id),
      "accept-candidate": (_e, _t, ctx) => ctx.id && this.acceptCandidate(ctx.id),
      "ignore-candidate": (_e, _t, ctx) => ctx.id && this.ignoreCandidate(ctx.id),
      "resolve-candidate-alias": (_e, _t, ctx) => ctx.id && this.showResolveAliasForm(ctx.id),
      "promote-entity": (_e, _t, ctx) => ctx.id && this.promoteEntity(ctx.id),
      "merge-entity": (_e, _t, ctx) => ctx.id && this.showMergeForm(ctx.id),
      "rollback-entity": (_e, _t, ctx) => ctx.id && this.showRollbackForm(ctx.id),
      "knowledge-entity": (_e, _t, ctx) => ctx.id && this.showKnowledgeForm(ctx.id),
      "create-relation": () => this.showRelationCreateForm(),
      "prepare-relation-review": (_e, t) => this.showRelationGroupReviewForm(t.getAttribute("data-group-id")),
      "edit-relation-review": (_e, _t, ctx) => ctx.id && this.showRelationReviewEditForm(ctx.id),
      "mark-relation-reviewed": (_e, _t, ctx) => ctx.id && this._markRelationReviewed(ctx.id),
      "mark-relation-unreviewed": (_e, _t, ctx) => ctx.id && this._markRelationUnreviewed(ctx.id),
      "delete-relation": (_e, _t, ctx) => ctx.id && this.deleteRelation(ctx.id),
      "create-alias": () => this.showAliasCreateForm(),
      "prepare-alias-review": (_e, t) => {
        const eid = t.getAttribute("data-entity-id")
        const alias = t.getAttribute("data-alias")
        if (eid && alias) this.showAliasReviewDecisionForm(eid, alias)
      },
      "set-relation-quick-filter": (_e, t) => this._setReviewQuickFilter("relation", t.getAttribute("data-filter-key"), t.getAttribute("data-filter-value")),
      "apply-relation-scene-quick": () => this._applyRelationSceneQuickFilter(),
      "set-alias-quick-filter": (_e, t) => this._setReviewQuickFilter("alias", t.getAttribute("data-filter-key"), t.getAttribute("data-filter-value")),
      "remove-review-filter": (_e, t) => this._removeReviewFilter(t.getAttribute("data-filter-kind"), t.getAttribute("data-filter-key")),
      "copy-review-diagnostic": async (_e, t) => {
        try {
          await navigator.clipboard.writeText(t.getAttribute("data-diagnostic") || "{}")
          toast("诊断信息已复制", "success")
        } catch {
          toast("复制失败", "error")
        }
      },
      "edit-alias-review": (_e, t) => {
        const eid = t.getAttribute("data-entity-id")
        const alias = t.getAttribute("data-alias")
        if (eid && alias) this.showAliasReviewEditForm(eid, alias)
      },
      "mark-alias-reviewed": (_e, t) => {
        const eid = t.getAttribute("data-entity-id")
        const alias = t.getAttribute("data-alias")
        if (eid && alias) this._markAliasReviewed(eid, alias)
      },
      "mark-alias-unreviewed": (_e, t) => {
        const eid = t.getAttribute("data-entity-id")
        const alias = t.getAttribute("data-alias")
        if (eid && alias) this._markAliasUnreviewed(eid, alias)
      },
      "delete-alias": (_e, t) => { const eid = t.getAttribute("data-entity-id"); const alias = t.getAttribute("data-alias"); if (eid && alias) this.deleteAlias(eid, alias) },
      "apply-filters": () => this._applyFilters(),
      "reset-filters": () => this._resetFilters(),
      "apply-candidate-review-filters": () => this._applyCandidateReviewFilters(),
      "reset-candidate-review-filters": () => this._resetCandidateReviewFilters(),
      "retry-candidate-load": () => this._refreshCurrentSubViewInPlace(),
      "apply-alias-review-filters": () => this._applyAliasReviewFilters(),
      "reset-alias-review-filters": () => this._resetAliasReviewFilters(),
      "apply-relation-review-filters": () => this._applyRelationReviewFilters(),
      "reset-relation-review-filters": () => this._resetRelationReviewFilters(),
      "prev-page": () => this._changePage(-1),
      "next-page": () => this._changePage(1),
      "prev-candidates-page": () => this._changeCandidatePage(-1),
      "next-candidates-page": () => this._changeCandidatePage(1),
      "prev-relations-page": () => this._changeRelationPage(-1),
      "next-relations-page": () => this._changeRelationPage(1),
      "prev-aliases-page": () => this._changeAliasPage(-1),
      "next-aliases-page": () => this._changeAliasPage(1),
    })

    bindActionMenus()
    if (state.currentSubView === "bible") worldBibleView.bindEvents()
    document.getElementById("btn-new-entity")?.addEventListener("click", () => this._showCreateForm())
    document.getElementById("filter-q")?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return
      event.preventDefault()
      this._applyFilters()
    })
    this._eventsBound = true
  },

  async _setObjectViewMode(mode) {
    this._objectViewMode = mode === "card" ? "card" : "table"
    await this._navigateWithQuery("objects", this._objectQueryFromState())
  },

  _visibleIdsForBulkScope(scope) {
    if (scope === "world-objects") return this._entities.map((item) => this._entityId(item)).filter(Boolean)
    if (scope === "world-candidates") return this._candidates.map((item) => this._entityId(item)).filter(Boolean)
    if (scope === "world-relations") return this._relations.map((item) => item.id || item.relationship_id).filter(Boolean)
    if (scope === "world-relation-groups") return this._relationGroups.map((item) => item.group_id).filter(Boolean)
    if (scope === "world-aliases") {
      return this._aliases
        .filter((item) => !item.managed_by_suggestion)
        .map((item) => this._aliasKey(item))
        .filter(Boolean)
    }
    return []
  },

  _itemsForBulkScope(scope) {
    const selection = getBulkSelection(this, scope)
    if (scope === "world-objects") return selectedItemsFrom(this._entities, selection, (item) => this._entityId(item))
    if (scope === "world-candidates") return selectedItemsFrom(this._candidates, selection, (item) => this._entityId(item))
    if (scope === "world-relations") return selectedItemsFrom(this._relations, selection, (item) => item.id || item.relationship_id)
    if (scope === "world-relation-groups") return selectedItemsFrom(this._relationGroups, selection, (item) => item.group_id)
    if (scope === "world-aliases") return selectedItemsFrom(this._aliases, selection, (item) => this._aliasKey(item))
    return []
  },

  _toggleBulkOne(input) {
    const scope = input.getAttribute("data-scope")
    const id = input.getAttribute("data-id")
    toggleBulkSelection(this, scope, id, input.checked)
    this._rerenderBulkSelection()
  },

  _toggleBulkAll(input) {
    const scope = input.getAttribute("data-scope")
    toggleAllBulkSelection(this, scope, this._visibleIdsForBulkScope(scope), input.checked)
    this._rerenderBulkSelection()
  },

  _toggleFilterPanel(key, button) {
    if (!key || !button) return
    if (!this._filterPanelsOpen) this._filterPanelsOpen = {}
    const open = button.getAttribute("aria-expanded") !== "true"
    this._filterPanelsOpen[key] = open
    this._saveFilterPanelState()
    button.setAttribute("aria-expanded", String(open))
    const panel = document.getElementById(button.getAttribute("aria-controls"))
    if (panel) panel.hidden = !open
    const icon = button.querySelector('[aria-hidden="true"]')
    if (icon) icon.textContent = open ? "▾" : "▸"
    const label = button.querySelector("[data-filter-toggle-label]")
    if (label) label.textContent = open ? "收起筛选" : "展开筛选"
  },

  _filterPanelStorageKey() {
    if (!state.currentProjectId) return null
    return `novel_world_filter_panels:${state.currentProjectId}`
  },

  _loadFilterPanelState() {
    this._filterPanelsOpen = { ...WORLD_FILTER_PANEL_DEFAULTS }
    const storageKey = this._filterPanelStorageKey()
    if (!storageKey) return
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null")
      if (!saved || typeof saved !== "object" || Array.isArray(saved)) return
      for (const key of Object.keys(WORLD_FILTER_PANEL_DEFAULTS)) {
        if (typeof saved[key] === "boolean") this._filterPanelsOpen[key] = saved[key]
      }
    } catch {
      try { localStorage.removeItem(storageKey) } catch {}
    }
  },

  _saveFilterPanelState() {
    const storageKey = this._filterPanelStorageKey()
    if (!storageKey) return
    try {
      const stateToSave = Object.fromEntries(
        Object.keys(WORLD_FILTER_PANEL_DEFAULTS).map((key) => [
          key,
          this._filterPanelsOpen?.[key] === true,
        ]),
      )
      localStorage.setItem(storageKey, JSON.stringify(stateToSave))
    } catch {
      // localStorage 不可用时保留当前会话内状态。
    }
  },

  _clearBulkScope(scope) {
    clearBulkSelection(this, scope)
    this._rerenderBulkSelection()
  },

  _rerenderBulkSelection() {
    syncBulkSelectionUi(this)
  },

  _runBulkAction(scope, action) {
    const items = this._itemsForBulkScope(scope)
    if (items.length === 0) {
      toast("请先选择要处理的项目", "warning")
      return
    }

    if (scope === "world-objects" && ["fuse-entities", "alias-entities"].includes(action)) {
      this._showBulkEntityResolution(action, items)
      return
    }
    if (scope === "world-relation-groups" && ["apply-relation-decisions", "ignore-relation-groups"].includes(action)) {
      this._applyRelationReviewBatch(items, action === "ignore-relation-groups")
      return
    }
    if (scope === "world-aliases" && ["review-aliases-batch", "ignore-aliases-batch"].includes(action)) {
      this._applyAliasReviewBatch(items, action === "ignore-aliases-batch" ? "ignore" : "accept")
      return
    }

    const labelByAction = {
      "promote-entities": "批量采用",
      "review-entities": "批量标记已检查",
      "delete-entities": "批量删除对象",
      "accept-candidates": "批量采用",
      "ignore-candidates": "批量忽略/设为临时",
      "review-relations": "批量采用关系",
      "delete-relations": "批量删除关系",
      "review-aliases": "批量采用别名",
      "delete-aliases": "批量删除别名",
    }
    const danger = action?.includes("delete") || action?.includes("ignore")
    confirmAction(
      `确定对选中的 ${items.length} 项执行「${labelByAction[action] || action}」吗？`,
      async () => {
        await this._executeBulkAction(scope, action, items)
      },
      danger ? "确认执行" : "确认",
    )
  },

  _reviewBatchToast(result, noun) {
    const succeeded = Number(result?.succeeded_count || 0)
    const stale = Number(result?.stale_count || 0)
    const failed = Number(result?.failed_count || 0)
    const message = `已处理 ${succeeded} 个${noun}${stale ? `，${stale} 个已过期` : ""}${failed ? `，${failed} 个失败` : ""}`
    toast(message, stale || failed ? "warning" : "success")
  },

  _reviewBatchItemError(item) {
    const prefix = item?.status === "stale" ? "已过期" : "处理失败"
    return `${prefix}：${item?.message || item?.error_code || "请刷新后重试"}`
  },

  async _advanceRelationReview(anchorIndex = 0) {
    if (!this._relationGroups.length && this._relationGroupTotal > 0 && this._relationFilters.skip > 0) {
      const content = document.getElementById("workspace-content")
      const scrollTop = content?.scrollTop || 0
      this._relationFilters.skip = Math.max(0, Math.floor((this._relationGroupTotal - 1) / this._relationFilters.limit) * this._relationFilters.limit)
      await router.replace("world", "review-relations", this._reviewQueryFromState(this._relationFilters, WORLD_RELATION_QUERY_KEYS))
      const liveContent = document.getElementById("workspace-content")
      if (liveContent) liveContent.scrollTop = scrollTop
    }
    const next = this._relationGroups[Math.min(anchorIndex, Math.max(0, this._relationGroups.length - 1))]
    if (next) this.showRelationGroupReviewForm(next.group_id)
  },

  async _advanceAliasReview(anchorIndex = 0) {
    if (!this._aliases.length && this._aliasGroupTotal > 0 && this._aliasFilters.skip > 0) {
      const content = document.getElementById("workspace-content")
      const scrollTop = content?.scrollTop || 0
      this._aliasFilters.skip = Math.max(0, Math.floor((this._aliasGroupTotal - 1) / this._aliasFilters.limit) * this._aliasFilters.limit)
      await router.replace("world", "review-aliases", this._reviewQueryFromState(this._aliasFilters, WORLD_ALIAS_QUERY_KEYS))
      const liveContent = document.getElementById("workspace-content")
      if (liveContent) liveContent.scrollTop = scrollTop
    }
    const next = this._aliases[Math.min(anchorIndex, Math.max(0, this._aliases.length - 1))]
    if (next) this.showAliasReviewDecisionForm(next.entity_id, next.alias)
  },

  _applyRelationReviewBatch(groups, ignoreAll = false) {
    const anchorIndex = Math.max(0, Math.min(...groups.map((group) => this._relationGroups.findIndex((item) => item.group_id === group.group_id)).filter((index) => index >= 0)))
    const decisions = []
    for (const group of groups) {
      if (ignoreAll) {
        decisions.push({
          client_decision_id: group.group_id,
          action: "ignore",
          group_id: group.group_id,
          member_relation_ids: (group.members || []).map((item) => item.id),
          expected_execution_fingerprint: group.execution_fingerprint,
        })
      } else if (this._relationReviewDrafts[group.group_id]) {
        decisions.push(this._relationReviewDrafts[group.group_id])
      }
    }
    if (!ignoreAll && decisions.length !== groups.length) {
      toast("所选关系组中仍有未准备决策的项目", "warning")
      return
    }
    const relationCount = decisions.reduce((sum, decision) => sum + (decision.member_relation_ids || []).length, 0)
    if (decisions.length > 20 || relationCount > 50) {
      toast(`单次最多处理 20 个关系决策、50 条所选关系；当前为 ${decisions.length} 个决策、${relationCount} 条关系。请减少选择后重试。`, "warning")
      return
    }
    confirmAction(
      ignoreAll
        ? `确定忽略所选 ${groups.length} 个关系组吗？候选会进入历史并保留审计。`
        : `确定应用所选 ${decisions.length} 个关系决策吗？请确认归并范围和最终类型。`,
      async () => {
        try {
          const result = await api.world.reviewRelationsBatch({ confirmed: true, decisions }, state.currentProjectId)
          const selection = getBulkSelection(this, "world-relation-groups")
          for (const item of result.results || []) {
            if (item.status === "success") {
              delete this._relationReviewDrafts[item.client_decision_id]
              delete this._relationReviewErrors[item.client_decision_id]
              selection.delete(item.client_decision_id)
            } else {
              this._relationReviewErrors[item.client_decision_id] = this._reviewBatchItemError(item)
            }
          }
          this._reviewBatchToast(result, "关系组")
          await this._refreshCurrentSubViewInPlace()
          await this._advanceRelationReview(anchorIndex)
        } catch (err) {
          for (const group of groups) this._relationReviewErrors[group.group_id] = err.message || "网络异常，请重试"
          toast(err.message || "关系批量复核失败，已保留当前决策草稿", "error")
          await this._rerenderCurrentSubViewInPlace()
        }
      },
      ignoreAll ? "确认忽略" : "确认应用",
    )
  },

  _applyAliasReviewBatch(items, action) {
    if (items.length > 50) {
      toast(`单次最多处理 50 条别名；当前已选 ${items.length} 条。请减少选择后重试。`, "warning")
      return
    }
    const anchorIndex = Math.max(0, Math.min(...items.map((item) => this._aliases.findIndex((current) => this._aliasKey(current) === this._aliasKey(item))).filter((index) => index >= 0)))
    const decisionKeys = new Map()
    const decisions = items.map((item, index) => {
      const key = this._aliasKey(item)
      const draft = this._aliasReviewDrafts[key] || {}
      const clientDecisionId = `alias-${index}-${String(item.entity_id || "").slice(0, 16)}`
      decisionKeys.set(clientDecisionId, key)
      return {
        client_decision_id: clientDecisionId,
        action,
        entity_id: item.entity_id,
        original_alias: item.alias,
        expected_execution_fingerprint: item.execution_fingerprint,
        ...(action === "accept" ? draft : {}),
      }
    })
    confirmAction(
      action === "ignore"
        ? `确定忽略所选 ${items.length} 个别名吗？条目会进入历史并保留证据。`
        : `确定采用所选 ${items.length} 个别名吗？未编辑条目会原样采用。`,
      async () => {
        try {
          const result = await api.world.reviewAliasesBatch({ confirmed: true, decisions }, state.currentProjectId)
          const selection = getBulkSelection(this, "world-aliases")
          for (const item of result.results || []) {
            const key = decisionKeys.get(item.client_decision_id)
            if (item.status === "success") {
              delete this._aliasReviewDrafts[key]
              delete this._aliasReviewErrors[key]
              selection.delete(key)
            } else if (key) {
              this._aliasReviewErrors[key] = this._reviewBatchItemError(item)
            }
          }
          this._reviewBatchToast(result, "别名")
          await this._refreshCurrentSubViewInPlace()
          await this._advanceAliasReview(anchorIndex)
        } catch (err) {
          for (const item of items) this._aliasReviewErrors[this._aliasKey(item)] = err.message || "网络异常，请重试"
          toast(err.message || "别名批量复核失败，已保留当前编辑草稿", "error")
          await this._rerenderCurrentSubViewInPlace()
        }
      },
      action === "ignore" ? "确认忽略" : "确认采用",
    )
  },

  _showBulkEntityResolution(action, items) {
    if (items.length < 2) {
      toast("请至少选择两个已采用对象", "warning")
      return
    }
    if (items.some((item) => item.status && item.status !== "canonical")) {
      toast("融合和标记为别名仅适用于已采用对象", "warning")
      return
    }
    const entityTypes = new Set(items.map((item) => item.entity_type).filter(Boolean))
    if (entityTypes.size > 1) {
      toast("请选择相同类型的对象", "warning")
      return
    }

    const operationLabel = action === "fuse-entities" ? "融合" : "标记为别名"
    const rows = items.map((item, index) => {
      const id = this._entityId(item)
      return `
        <label class="world-bulk-resolution-option">
          <input type="radio" name="world-bulk-target" value="${esc(id)}" ${index === 0 ? "checked" : ""} />
          <span><strong>${esc(item.name || id)}</strong><small>${esc(item.entity_type || "未分类")}</small></span>
        </label>
      `
    }).join("")
    const explanation = action === "fuse-entities"
      ? "其余对象的内容、别名和关系会融合到保留对象，来源对象进入历史态。"
      : "其余对象的名称会成为保留对象的别名，关系会迁移，但不会融合摘要等内容；来源对象进入历史态。"

    showModalHtml(`批量${operationLabel}`, `
      <p>${esc(explanation)}</p>
      <p class="form-help">请选择要保留的主对象：</p>
      <div class="world-bulk-resolution-list">${rows}</div>
    `, [{
      text: `确认${operationLabel}`,
      class: "btn-primary",
      handler: async () => {
        const targetId = document.querySelector('input[name="world-bulk-target"]:checked')?.value
        const target = items.find((item) => this._entityId(item) === targetId)
        if (!target) {
          toast("请选择要保留的主对象", "warning")
          return
        }
        const sources = items.filter((item) => this._entityId(item) !== targetId)
        const confirmationMessage = action === "fuse-entities"
          ? `确定将 ${sources.length} 个已采用对象融合到「${target.name || targetId}」吗？此操作会让来源对象进入历史态。`
          : `确定将 ${sources.length} 个已采用对象标记为「${target.name || targetId}」的别名吗？此操作会让来源对象进入历史态。`
        confirmAction(
          confirmationMessage,
          async () => {
            try {
              const result = await api.world.applyEntityFusionSuggestions({
                novel_id: state.currentProjectId,
                confirmed: true,
                suggestions: sources.map((source) => ({
                  action: action === "fuse-entities" ? "merge" : "alias_only",
                  source_entity_id: this._entityId(source),
                  target_entity_id: targetId,
                  alias: source.name || undefined,
                  allow_canonical_merge: action === "fuse-entities",
                  allow_canonical_alias: action === "alias-entities",
                })),
              })
              closeModal()
              const warningCount = Number(result.skipped || 0)
              toast(
                `已${operationLabel} ${result.applied || 0} 个对象${warningCount ? `，跳过 ${warningCount} 个` : ""}`,
                warningCount ? "warning" : "success",
              )
              clearBulkSelection(this, "world-objects")
              await this._refreshCurrentSubViewInPlace()
            } catch (err) {
              toast(err.message || `${operationLabel}失败`, "error")
            }
          },
          "确认执行",
        )
        return false
      },
    }], { size: "large" })
  },

  async _executeBulkAction(scope, action, items) {
    const label = {
      "promote-entities": "批量采用",
      "review-entities": "批量标记已检查",
      "delete-entities": "批量删除对象",
      "accept-candidates": "批量采用",
      "ignore-candidates": "批量忽略/设为临时",
      "review-relations": "批量采用关系",
      "delete-relations": "批量删除关系",
      "review-aliases": "批量采用别名",
      "delete-aliases": "批量删除别名",
    }[action] || "批量操作"

    let actionable = items
    if (action === "promote-entities") {
      actionable = items.filter((item) => item.status === "draft" || item.status === "candidate")
    } else if (action === "accept-candidates") {
      actionable = items.filter((item) => {
        const candidateAction = this._candidateAction(item)
        return this._isSuggestionShadow(item)
          || !["temporary_only", "ignore", "link_to_existing", "alias_of_existing", "merge_with_existing"].includes(candidateAction)
      })
    } else if (action === "review-entities") {
      actionable = items.filter((item) => !this._isSuggestionShadow(item))
    }

    if (actionable.length === 0) {
      toast("所选项目没有可执行的批量动作", "warning")
      return
    }

    const result = await runBulkAction(actionable, async (item) => {
      if (action === "promote-entities" || action === "accept-candidates") {
        await this._adoptEntity(item)
      } else if (action === "review-entities") {
        await api.world.updateEntity(this._entityId(item), {
          content_json: this._entityReviewContent(item, true, "world_objects_bulk"),
        }, state.currentProjectId)
      } else if (action === "delete-entities") {
        await this._ignoreOrDeleteEntity(item)
      } else if (action === "ignore-candidates") {
        await this._ignoreEntity(item)
      } else if (action === "delete-relations") {
        await api.world.deleteRelationship(item.id || item.relationship_id, { novel_id: state.currentProjectId })
      } else if (action === "review-relations") {
        await api.world.reviewEditRelationship(item.id || item.relationship_id, { confirm_review: true }, state.currentProjectId)
      } else if (action === "delete-aliases") {
        await api.world.deleteAlias(item.entity_id, item.alias, { novel_id: state.currentProjectId })
      } else if (action === "review-aliases") {
        await api.world.updateAlias(item.entity_id, item.alias, {
          status: "canonical",
          needs_review: false,
          reviewed_at: new Date().toISOString(),
          reviewed_by: "manual",
          reviewed_from: "world_aliases_bulk",
        }, { novel_id: state.currentProjectId })
      }
    })

    toast(bulkResultMessage(result, label, (item) => item.name || item.alias || item.relation_type || this._entityId(item)), result.failed.length ? "warning" : "success")
    clearBulkSelection(this, scope)
    await this._refreshCurrentSubViewInPlace()
  },

  _toggleAdvancedFilters() {
    this._advancedFiltersOpen = !this._advancedFiltersOpen
    router.refresh()
  },

  async _openEntityMap(entityId) {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      const entity = this._entities.find((item) => this._entityId(item) === entityId)
      const includeCandidates = entity?.status === "candidate" || entity?.status === "draft"
      const presence = await api.world.getEntityMapPresence(
        entityId,
        state.currentProjectId,
        includeCandidates,
      )
      const items = presence?.items || []
      const choices = items.flatMap((item) => (
        item.path_refs?.length
          ? item.path_refs.map((pathRef) => ({ ...item, _pathRef: pathRef }))
          : [item]
      ))
      if (choices.length === 1) {
        this._openEntityPresence(choices[0], entityId)
        return
      }
      if (choices.length > 1) {
        const roleLabels = {
          location: "地点",
          "marker.character": "人物标记",
          "marker.event": "事件标记",
          "marker.item": "物品标记",
          territory: "领地",
          terrain: "覆盖素材",
          "path.start": "线路起点",
          "path.end": "线路终点",
        }
        const body = `
          <div class="world-map-presence-list">
            ${choices.map((item, index) => `
              <button class="world-map-presence-row" data-map-presence-index="${index}">
                <strong>${esc(item.map_name)}${item._pathRef?.path_name ? ` · ${esc(item._pathRef.path_name)}` : ""}</strong>
                <span>${esc((item._pathRef?.roles || item.roles || []).map((role) => roleLabels[role] || role).join("、") || "地图位置")} · ${Number(item.binding_count || 0)} 个空间绑定</span>
                ${item.scene_index_min != null || item.scene_index_max != null
                  ? `<small>Scene ${esc(item.scene_index_min ?? "?")}–${esc(item.scene_index_max ?? "?")}</small>`
                  : ""}
              </button>
            `).join("")}
          </div>
        `
        showModalHtml("选择关联地图", body, [{ text: "取消", class: "btn", handler: closeModal }])
        document.querySelectorAll("[data-map-presence-index]").forEach((button) => {
          button.onclick = () => {
            closeModal()
            this._openEntityPresence(choices[Number(button.dataset.mapPresenceIndex)], entityId)
          }
        })
        return
      }
      const target = await api.world.getMapOpenTarget(state.currentProjectId, { focusEntityId: entityId })
      const url = buildMapUrl({
        projectId: state.currentProjectId,
        mapId: target.map_id,
        sceneId: target.scene_id,
        focusEntityId: target.focus_entity_id || entityId,
        focusPathId: target.focus_path_id,
        focusLayerNodeId: target.focus_layer_node_id,
        mode: target.mode || (target.map_id ? "dashboard" : "overview"),
      })
      if (target.fallback_message) {
        toast(target.fallback_message, "warning")
      }
      window.open(url, "_blank", "noopener")
    } catch (err) {
      toast(`打开地图失败：${err.message || "未知错误"}`, "error")
    }
  },

  _openEntityPresence(presence, entityId) {
    const target = presence?.open_target || {}
    const pathRef = presence?._pathRef || presence?.path_refs?.[0] || {}
    const focusesPath = Boolean(pathRef.path_id || target.focus_path_id)
    const url = buildMapUrl({
      projectId: state.currentProjectId,
      mapId: target.map_id || presence.map_id,
      sceneId: target.scene_id,
      focusEntityId: target.focus_entity_id || entityId,
      focusHexQ: focusesPath
        ? null
        : presence.representative_world_q ?? presence.representative_hex_q,
      focusHexR: focusesPath
        ? null
        : presence.representative_world_r ?? presence.representative_hex_r,
      focusPathId: pathRef.path_id || target.focus_path_id,
      focusLayerNodeId: pathRef.layer_node_id || target.focus_layer_node_id,
      mode: target.mode || "live",
    })
    window.open(url, "_blank", "noopener")
  },

  _showCreateForm() {
    let submissionPending = false
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-entity-name" placeholder="对象名称" />
      </div>
      <div class="form-group">
        <label>类型</label>
        ${this._entityTypeControlHtml("create", "character")}
      </div>
      <div class="form-group">
        <label>概要</label>
        <textarea class="form-textarea" id="create-entity-summary" rows="3" placeholder="简要描述"></textarea>
      </div>
    `

    showModalHtml("新建世界对象", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          if (submissionPending) return false
          const lifecycleEpoch = this._lifecycleEpoch
          const projectId = state.currentProjectId
          const name = document.getElementById("create-entity-name")?.value
          if (!name) {
            toast("请输入名称", "warning")
            return false
          }

          const payload = {
            name,
            entity_type: this._readEntityType("create"),
            summary: document.getElementById("create-entity-summary")?.value || "",
          }
          if (!payload.entity_type) {
            toast("请输入自定义类型名称", "warning")
            return false
          }

          submissionPending = true
          try {
            await api.world.createEntity(payload, projectId)
          } catch (err) {
            if (lifecycleEpoch !== this._lifecycleEpoch) return true
            const detail = this._createConflictDetail(err)
            if (detail?.requires_confirmation) {
              const similar = this._formatSimilarEntities(detail.similar_entities)
              let forceSubmissionPending = false
              confirmAction(
                `发现相似对象：${similar || "已有对象"}。是否仍要创建？`,
                async () => {
                  if (forceSubmissionPending) return false
                  if (lifecycleEpoch !== this._lifecycleEpoch) return true
                  forceSubmissionPending = true
                  try {
                    await api.world.createEntity({ ...payload, force_create: true }, projectId)
                  } catch (err2) {
                    forceSubmissionPending = false
                    if (lifecycleEpoch !== this._lifecycleEpoch) return true
                    toast(`创建失败：${err2.message}`, "error")
                    return false
                  }
                  return this._finishEntityMutation(
                    `对象 "${name}" 已创建`,
                    lifecycleEpoch,
                  )
                },
                "强制创建",
              )
              return false
            }
            submissionPending = false
            toast(`创建失败：${err.message}`, "error")
            return false
          }
          return this._finishEntityMutation(
            `对象 "${name}" 已创建`,
            lifecycleEpoch,
          )
        },
      },
    ])
    this._bindEntityTypeControl("create")
  },

  _createConflictDetail(err) {
    if (!err || !(err.status === 409 || (err.message && err.message.includes("409")))) {
      return null
    }
    let detail = err.detail ?? err.body?.detail ?? err.body?.message ?? null
    if (typeof detail === "string") {
      try { detail = JSON.parse(detail) } catch { /* keep string */ }
    }
    if (detail && typeof detail === "object" && detail.requires_confirmation) {
      return detail
    }
    return null
  },

  _formatSimilarEntities(entities) {
    if (!Array.isArray(entities)) return ""
    return entities
      .map((item) => {
        if (!item || typeof item !== "object") return String(item || "").trim()
        const name = item.name || item.title || item.id || "未命名对象"
        const type = item.entity_type || item.type
        const score = item.similarity_score ?? item.score ?? item.confidence
        const parts = [name]
        if (type) parts.push(type)
        if (score != null) parts.push(`相似度 ${score}`)
        return parts.join(" / ")
      })
      .filter(Boolean)
      .join("；")
  },

  // ============================================================
  // 合并、回滚与知识边界
  // ============================================================

  showMergeForm(candidateId) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === candidateId)
      || this._candidates.find((e) => (e.id || e.entity_id) === candidateId)
    if (!entity) return
    const targetId = this._candidateTargetId(entity)
    const targetName = this._candidateTargetName(entity)

    const formHtml = `
      <p style="margin-bottom:10px;">将 <strong>${esc(entity.name)}</strong> 合并到目标已采用对象。</p>
      <div class="form-group">
        <label>选择目标对象 *</label>
        <div id="merge-target-picker"></div>
        <input type="hidden" id="merge-target-id" value="${esc(targetId)}" />
        <p style="font-size:12px;color:var(--text-muted);margin-top:6px;">显示名称、类型、状态和摘要；没有明确目标时请先搜索再选择。</p>
      </div>
    `
    showModalHtml("合并对象", formHtml, [{
      text: "合并",
      class: "btn-primary",
      handler: async () => {
        const targetId = document.getElementById("merge-target-id")?.value
        if (!targetId) { toast("请选择目标对象", "warning"); return }
        const selectedLabel = document.getElementById("merge-target-id")?.dataset.referenceLabel
          || this._findEntity(targetId)?.name
          || "所选目标对象"
        this._destroyReferencePickers()
        confirmAction(
          `确定将「${entity.name || "当前对象"}」合并到「${selectedLabel}」吗？来源对象会进入历史态。`,
          () => this._mergeEntity(candidateId, targetId),
          "确认合并",
        )
        return false
      },
    }])
    this._mountEntityReferencePicker({
      rootId: "merge-target-picker",
      inputId: "merge-target-id",
      sourceId: this._entityId(entity),
      selectedId: targetId,
      selectedName: targetName,
      canonicalOnly: true,
    })
  },

  _isMergeTargetEntity(entity) {
    return entity?.status === "canonical"
  },

  async _mergeEntity(candidateId, targetId) {
    try {
      const candidate = this._findEntity(candidateId)
      const suggestionId = this._suggestionId(candidate)
      const result = suggestionId
        ? await api.world.mergeSuggestion(
          suggestionId,
          targetId,
          state.currentProjectId,
        )
        : await api.world.mergeEntity(candidateId, targetId, state.currentProjectId)
      await this._refreshCandidatesAfterAffectedMutation(
        result?.result_ref_json || result,
      )
      toast("实体已合并", "success")
      router.navigate("world", state.currentSubView || "candidates")
    } catch (err) {
      toast(err.message || "合并失败", "error")
    }
  },

  _affectedIdsFromMutationResult(result) {
    const ids = [
      ...(Array.isArray(result?.affected_ids) ? result.affected_ids : []),
      ...(Array.isArray(result?.merged_ids) ? result.merged_ids : []),
      result?.candidate_entity_id,
    ]
    return Array.from(new Set(ids.filter(Boolean).map(String)))
  },

  async _refreshCandidatesAfterAffectedMutation(result) {
    const affected = new Set(this._affectedIdsFromMutationResult(result))
    if (affected.size) {
      const before = this._candidates.length
      this._candidates = this._candidates.filter((item) => !affected.has(this._entityId(item)))
      const removed = before - this._candidates.length
      if (removed > 0) {
        this._candidateTotal = Math.max(0, this._candidateTotal - removed)
      }
    }
    await this._loadCandidates()
    await this._loadEntities()
  },

  _showEntityFusionSuggestions() {
    const result = this._fusionProgress?.raw?.result || {}
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions : []
    if (!suggestions.length) {
      toast("暂无合并建议", "info")
      return
    }
    const suggestionsByKey = new Map(suggestions.map((item) => [this._fusionSuggestionKey(item), item]))
    const rows = suggestions.map((item) => {
      const suggestionKey = this._fusionSuggestionKey(item)
      const actionLabel = item.action === "merge" ? "合并" : item.action === "alias_only" ? "登记别名" : "需要人工检查"
      const evidence = (item.evidence_anchors || []).map((anchor) => anchor.snippet || anchor.source_type || "").filter(Boolean).join(" / ")
      const canonical = item.requires_canonical_confirmation ? `
        <label style="display:block;margin-top:6px;color:var(--warning);font-size:12px;">
          <input type="checkbox" data-canonical-merge />
          ${item.action === "alias_only"
            ? "我理解这会将已采用来源对象转为目标对象的别名"
            : "我理解这会合并两个已采用对象"}
        </label>
      ` : ""
      return `
        <article class="world-fusion-suggestion-card" data-fusion-card="${esc(suggestionKey)}">
          <label style="display:flex;gap:8px;align-items:flex-start;">
            <input type="checkbox" data-fusion-key="${esc(suggestionKey)}" ${item.action === "needs_review" ? "" : "checked"} />
            <span>
              <strong>${esc(actionLabel)}：</strong>
              ${esc(item.source_entity_name)} → ${esc(item.target_entity_name)}
            </span>
          </label>
          <div style="color:var(--text-dim);font-size:12px;margin-top:4px;">
            ${esc(item.entity_type || "-")} · 置信度 ${esc(item.confidence ?? "-")} · ${esc(item.match_method || "-")}
          </div>
          <p style="margin:6px 0 0;">${esc(item.reason || "无说明")}</p>
          ${canonical}
          <details style="margin-top:6px;"><summary>证据</summary><p>${esc(evidence || "无")}</p></details>
        </article>
      `
    }).join("")
    showModalHtml("世界对象 AI 合并建议", rows, [{
      text: "应用选中建议",
      class: "btn-primary",
      handler: async () => {
        const selected = Array.from(document.querySelectorAll("[data-fusion-key]:checked"))
          .map((input) => {
            const key = input.getAttribute("data-fusion-key")
            const card = input.closest("[data-fusion-card]")
            return { item: suggestionsByKey.get(key), card }
          })
          .filter((entry) => entry.item)
          .filter((entry) => entry.item.action === "merge" || entry.item.action === "alias_only")
        if (!selected.length) {
          toast("请选择可应用的建议", "warning")
          return
        }
        const payload = selected.map(({ item, card }) => {
          const allowCanonical = Boolean(card?.querySelector("[data-canonical-merge]")?.checked)
          return {
            action: item.action,
            source_entity_id: item.source_entity_id,
            target_entity_id: item.target_entity_id,
            alias: item.alias || item.source_entity_name,
            allow_canonical_merge: item.action === "merge" && allowCanonical,
            allow_canonical_alias: item.action === "alias_only" && allowCanonical,
          }
        })
        try {
          const applied = await api.world.applyEntityFusionSuggestions({
            novel_id: state.currentProjectId,
            confirmed: true,
            suggestions: payload,
          })
          closeModal()
          toast(`已应用 ${applied.applied || 0} 条建议`, "success")
          await this._reloadWorldLists()
          router.refresh()
        } catch (err) {
          toast(err.message || "应用失败", "error")
        }
      },
    }], { size: "large" })
  },

  _fusionSuggestionKey(item) {
    return [
      item.action || "needs_review",
      item.source_entity_id || "",
      item.target_entity_id || "",
    ].map((part) => encodeURIComponent(String(part))).join("::")
  },

  showRollbackForm(entityId) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === entityId)
    if (!entity) return

    const formHtml = `
      <p style="margin-bottom:10px;">回滚 <strong>${esc(entity.name)}</strong> 到指定场景索引。</p>
      <div class="form-group">
        <label>目标场景索引 *</label>
        <input class="form-input" id="rollback-scene-index" type="number" min="0" value="0" />
      </div>
    `
    showModalHtml("回滚对象", formHtml, [{
      text: "回滚",
      class: "btn-primary",
      handler: async () => {
        const idx = parseInt(document.getElementById("rollback-scene-index")?.value || "0", 10)
        if (Number.isNaN(idx)) { toast("请输入有效的场景索引", "warning"); return }
        try {
          await this._rollbackEntity(entityId, idx)
        } catch (err) {
          toast(err.message || "回滚失败", "error")
        }
      },
    }])
  },

  async _rollbackEntity(entityId, targetSceneIndex) {
    try {
      const result = await api.world.rollbackEntity(entityId, targetSceneIndex, state.currentProjectId)
      toast((result.warnings || []).length ? "回滚完成，存在警告" : "回滚完成", (result.warnings || []).length ? "warning" : "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "回滚失败", "error")
    }
  },

  showKnowledgeForm(characterId) {
    const character = this._entities.find((e) => (e.id || e.entity_id) === characterId)
    if (!character) return

    const entityOptions = this._entityOptionsHtml()
    const formHtml = `
      <p style="margin-bottom:10px;">为 <strong>${esc(character.name)}</strong> 添加知识边界。</p>
      <div class="form-group">
        <label>目标对象 *</label>
        <select class="form-select" id="knowledge-target-id"><option value="">请选择</option>${entityOptions}</select>
      </div>
      <div class="form-group">
        <label>了解程度 *</label>
        <select class="form-select" id="knowledge-level">
          <option value="unknown">未知</option>
          <option value="rumor">传闻</option>
          <option value="partial">部分了解</option>
          <option value="full">完全了解</option>
          <option value="false_belief">错误认知</option>
        </select>
      </div>
      <div class="form-group">
        <label>已知内容</label>
        <textarea class="form-textarea" id="knowledge-content" rows="2" placeholder="角色知道什么"></textarea>
      </div>
      <div class="form-group">
        <label>误解内容（仅错误认知）</label>
        <textarea class="form-textarea" id="knowledge-misconception" rows="2" placeholder="角色的误解"></textarea>
      </div>
      <div class="form-group">
        <label>来源章节索引</label>
        <input class="form-input" id="knowledge-chapter" type="number" min="0" placeholder="可选" />
      </div>
    `
    showModalHtml("添加知识边界", formHtml, [{
      text: "添加",
      class: "btn-primary",
      handler: async () => {
        const payload = {
          character_id: characterId,
          target_id: document.getElementById("knowledge-target-id")?.value,
          target_type: "entity",
          knowledge_level: document.getElementById("knowledge-level")?.value,
          known_content: document.getElementById("knowledge-content")?.value || "",
          misconception: document.getElementById("knowledge-misconception")?.value || "",
          source_chapter_index: document.getElementById("knowledge-chapter")?.value
            ? parseInt(document.getElementById("knowledge-chapter").value, 10)
            : null,
        }
        if (!payload.target_id) { toast("请选择目标对象", "warning"); return }
        try {
          await this._createKnowledge(characterId, payload)
        } catch (err) {
          toast(err.message || "添加知识边界失败", "error")
        }
      },
    }])
  },

  async _createKnowledge(characterId, payload) {
    if (payload.knowledge_level === "false_belief" && !payload.misconception) {
      toast("错误认知必须填写误解内容", "warning")
      return
    }
    try {
      await api.world.createKnowledge(characterId, payload, state.currentProjectId)
      toast("知识边界已添加", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "添加知识边界失败", "error")
    }
  },
}

router.registerView("world", worldView)
window.worldView = worldView


export default worldView
