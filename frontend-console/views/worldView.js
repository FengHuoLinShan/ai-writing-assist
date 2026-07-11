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
import { buildMapUrl } from "./mapRouteContext.js"
import worldBibleView from "./worldBibleView.js"

const WORLD_FILTER_DEFAULTS = {
  entity_type: "",
  display_state: "active",
  q: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  auto_ingested: "",
  skip: 0,
  limit: 20,
}

const WORLD_LIST_DEFAULTS = {
  skip: 0,
  limit: 20,
}

const WORLD_CANDIDATE_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
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
}

const WORLD_RELATION_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  relation_type: "",
  q: "",
  source_chapter_id: "",
  strength_min: "",
  strength_max: "",
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
]

const WORLD_CANDIDATE_QUERY_KEYS = [
  "suggested_action",
  "source",
  "workflow_id",
  "scene_index",
  "source_chapter_index",
  "confidence_min",
  "confidence_max",
]

const worldView = {
  /** @type {Array} */
  _entities: [],

  /** @type {Array} */
  _candidates: [],
  _candidateTotal: 0,

  /** @type {Array} */
  _batches: [],

  _relations: [],
  _relationTotal: 0,
  _relationFilters: { ...WORLD_RELATION_FILTER_DEFAULTS },
  _aliases: [],
  _aliasTotal: 0,
  _aliasFilters: { ...WORLD_ALIAS_FILTER_DEFAULTS },
  _candidateFilters: { ...WORLD_CANDIDATE_FILTER_DEFAULTS },
  _bulkSelections: {},

  _total: 0,
  _entitiesLoadError: null,

  _filters: { ...WORLD_FILTER_DEFAULTS },

  _advancedFiltersOpen: false,
  _objectViewMode: "table",

  _entityTypes: [
    { value: "character", label: "人物" },
    { value: "location", label: "地点" },
    { value: "faction", label: "组织" },
    { value: "item", label: "物品" },
    { value: "event", label: "事件" },
    { value: "rule", label: "规则" },
    { value: "power_system", label: "能力体系" },
    { value: "secret", label: "秘密" },
    { value: "legend", label: "传说" },
    { value: "resource", label: "资源" },
  ],

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

  async onEnter() {
    this._entities = []
    this._candidates = []
    this._candidateTotal = 0
    this._batches = []
    this._relations = []
    this._relationTotal = 0
    this._aliases = []
    this._aliasTotal = 0
    this._total = 0
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

    await this._loadEntities()
    await this._loadCandidates()

    try {
      if (state.currentProjectId) {
        this._batches = await api.world.listEntityBatches({ novel_id: state.currentProjectId })
      }
    } catch {
      this._batches = []
    }
  },

  _currentQuery() {
    const query = router.getCurrentQuery ? router.getCurrentQuery() : null
    return new URLSearchParams(query?.toString ? query.toString() : "")
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

  async _syncRouteQueryState(subView = state.currentSubView || "objects", { loadOnChange = false } = {}) {
    const query = this._currentQuery()
    const reviewSubView = this._normalizeReviewSubView(subView)
    if (subView === "objects") {
      const nextFilters = this._objectFiltersFromQuery(query)
      const nextMode = query.get("view") === "card" ? "card" : "table"
      const filtersChanged = !this._filtersEqual(this._filters, nextFilters, WORLD_OBJECT_QUERY_KEYS)
      const modeChanged = this._objectViewMode !== nextMode
      this._filters = nextFilters
      this._objectViewMode = nextMode
      if (this._hasAdvancedObjectFilters(nextFilters)) this._advancedFiltersOpen = true
      if (loadOnChange && filtersChanged) await this._loadEntities()
      return filtersChanged || modeChanged
    }
    if (reviewSubView === "review-objects") {
      const nextFilters = this._candidateFiltersFromQuery(query)
      const filtersChanged = !this._filtersEqual(this._candidateFilters, nextFilters, WORLD_CANDIDATE_QUERY_KEYS)
      this._candidateFilters = nextFilters
      if (loadOnChange && filtersChanged) await this._loadCandidates()
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

  _objectQueryFromState() {
    const query = new URLSearchParams()
    for (const key of WORLD_OBJECT_QUERY_KEYS) {
      this._setQueryValue(query, key, this._filters[key])
    }
    const page = Math.floor((this._filters.skip || 0) / this._filters.limit) + 1
    if (page > 1) query.set("page", String(page))
    if (this._objectViewMode === "card") query.set("view", "card")
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

  async _navigateWithQuery(subView, query) {
    await router.navigate("world", subView || state.currentSubView || "objects", true, query)
  },

  async _loadEntities() {
    this._entities = []
    this._total = 0
    this._entitiesLoadError = null
    if (!state.currentProjectId) return

    try {
      const params = {
        novel_id: state.currentProjectId,
        skip: this._filters.skip,
        limit: this._filters.limit,
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

      const data = await api.world.listEntities(params)
      this._entities = data.items || data || []
      this._total = data.total || this._entities.length
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
    if (!state.currentProjectId) return

    try {
      const params = {
        novel_id: state.currentProjectId,
        display_state: "review",
        skip: this._candidateFilters.skip,
        limit: this._candidateFilters.limit,
      }
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
    } catch {
      this._candidates = []
      this._candidateTotal = 0
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
    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
    this._stopAutoExtractPolling()
    this._stopFusionPolling()
    worldBibleView.onLeave()
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

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "objects" ? "active" : ""}" data-subview="objects" data-action="nav-objects">对象库</span>
        <span class="subnav-item ${reviewSubView ? "active" : ""}" data-subview="review-objects" data-action="nav-review">待处理</span>
        <span class="subnav-item ${subView === "relations" ? "active" : ""}" data-subview="relations" data-action="nav-relations">关系</span>
        <span class="subnav-item ${subView === "aliases" ? "active" : ""}" data-subview="aliases" data-action="nav-aliases">别名</span>
        <span class="subnav-item ${subView === "bible" ? "active" : ""}" data-subview="bible" data-action="nav-bible">世界书</span>
        <span class="subnav-item ${subView === "map" ? "active" : ""}" data-subview="map" data-action="nav-map">地图</span>
      </div>
    `

    if (subView === "objects") {
      html += this._renderEntityList()
    } else if (reviewSubView) {
      html += await this._renderReviewQueue(reviewSubView)
    } else if (subView === "relations") {
      html += await this._renderRelations()
    } else if (subView === "aliases") {
      html += await this._renderAliases()
    } else if (subView === "bible") {
      html += await worldBibleView.render()
    }

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  _normalizeReviewSubView(subView = state.currentSubView || "") {
    if (subView === "candidates") return "review-objects"
    if (["review-objects", "review-aliases", "review-relations"].includes(subView)) {
      return subView
    }
    return ""
  },

  async _renderReviewQueue(reviewSubView) {
    const tab = reviewSubView || "review-objects"
    const tabNav = `
      <div class="subnav subnav-secondary" style="margin-bottom:12px;">
        <span class="subnav-item ${tab === "review-objects" ? "active" : ""}" data-action="nav-review-objects">对象</span>
        <span class="subnav-item ${tab === "review-aliases" ? "active" : ""}" data-action="nav-review-aliases">别名</span>
        <span class="subnav-item ${tab === "review-relations" ? "active" : ""}" data-action="nav-review-relations">关系</span>
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
    if (this._entities.length === 0) {
      return `
        <div class="world-list-actions">
          <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
          <button class="btn" data-action="toggle-extract" style="margin-left:8px;">${this._autoExtractOpen ? "▾" : "▸"} 世界对象与别名/关系自动提取</button>
        </div>
        ${this._autoExtractOpen ? this._renderAutoExtractPanel("world_object_auto_extraction", "世界对象与别名/关系自动提取") : ""}
        ${this._renderFilters()}
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

    let html = `
      <div class="world-list-actions">
        <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
        <button class="btn" data-action="toggle-extract" style="margin-left:8px;">
          ${this._autoExtractOpen ? "▾" : "▸"} 世界对象与别名/关系自动提取
        </button>
      </div>
      ${this._autoExtractOpen ? this._renderAutoExtractPanel("world_object_auto_extraction", "世界对象与别名/关系自动提取") : ""}
      <div class="world-list-actions__secondary">
        <button class="btn btn-sm" data-action="nav-candidates">待处理（${this._candidateTotal || this._candidates.length}）</button>
      </div>
    `

    html += this._renderFilters()
    html += this._renderObjectViewToggle()

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
      <input class="form-input" id="filter-workflow-id" value="${esc(this._filters.workflow_id || "")}" placeholder="workflow_id" aria-label="Workflow ID 筛选" />
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
    return `
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
  },

  _renderObjectViewToggle() {
    return `
      <div class="world-object-view-toggle" aria-label="对象库视图">
        <button class="btn btn-sm ${this._objectViewMode === "table" ? "btn-primary" : ""}" data-action="set-object-view" data-view-mode="table">表格</button>
        <button class="btn btn-sm ${this._objectViewMode === "card" ? "btn-primary" : ""}" data-action="set-object-view" data-view-mode="card">卡片</button>
      </div>
    `
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
    const ids = entities.map((entity) => this._entityId(entity))
    reconcileBulkSelection(this, scope, ids)
    let html = `<table class="data-table table-card-list world-table--no-top-border">
      <thead>
        <tr>
          <th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前页对象")}</th>
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
          <td data-label="名称">${esc(e.name)}${isNew}</td>
          <td data-label="来源" class="world-table-cell--muted">${esc(sourceText[e.source] || e.source || "-")}</td>
          <td data-label="注意" class="${needsReview ? "world-table-cell--warning" : "world-table-cell--muted"}">${esc(attentionText)}</td>
          <td data-label="重要度">${esc(e.importance || e.importance_score || "-")}</td>
          <td data-label="摘要" class="world-table-cell--muted world-table-cell--ellipsis">${esc(e.summary || e.public_info || "-")}</td>
          <td data-label="操作">
            <div class="row-actions">
              ${reviewAction}
              ${isSuggestionShadow ? "" : `<button class="btn btn-sm btn-primary" data-action="edit-entity" data-id="${esc(id)}">编辑</button>`}
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
      { action: "review-entities", label: "批量标记已检查", className: "btn-primary" },
      { action: "promote-entities", label: "批量采用", className: "btn-primary" },
      { action: "delete-entities", label: "批量删除", className: "btn-danger" },
    ], { noun: "对象", hint: "仅作用于当前页选中对象" }) + html
    return html
  },

  _renderEntityCards(entities, { showNewBadge }) {
    const scope = "world-objects"
    const ids = entities.map((entity) => this._entityId(entity))
    reconcileBulkSelection(this, scope, ids)
    const cards = entities.map((entity) => this._renderEntityCard(entity, { showNewBadge })).join("")
    return renderBulkToolbar(this, scope, [
      { action: "review-entities", label: "批量标记已检查", className: "btn-primary" },
      { action: "promote-entities", label: "批量采用", className: "btn-primary" },
      { action: "delete-entities", label: "批量删除", className: "btn-danger" },
    ], { noun: "对象", hint: "仅作用于当前页选中对象" }) + `
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
          <span>重要度：${esc(entity.importance || entity.importance_score || "-")}</span>
        </div>
        <div class="world-object-card__actions">
          ${reviewAction}
          ${isSuggestionShadow ? "" : `<button class="btn btn-sm btn-primary" data-action="edit-entity" data-id="${esc(id)}">编辑</button>`}
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

  _renderCandidatesList({ reviewOnly = false } = {}) {
    if (this._candidates.length === 0) {
      return `
        ${reviewOnly ? this._renderCandidateReviewFilters() : ""}
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

    let html = `
      ${reviewOnly ? this._renderCandidateReviewFilters() : ""}
      <p class="world-list-description">
        以下内容尚未进入当前有效设定。请结合来源和证据决定采用、合并、设为别名或忽略。
      </p>
      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前待处理项")}</th>
            <th>名称</th>
            <th>类型</th>
            <th>重要度</th>
            <th>建议动作</th>
            <th>证据</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const c of this._candidates) {
      const id = c.id || c.entity_id
      const action = this._candidateAction(c)
      const targetName = this._candidateTargetName(c)
      let actionLabel = WORLD_SUGGESTED_ACTION_LABELS[action] || action
      if (targetName && ["link_to_existing", "alias_of_existing"].includes(action)) {
        actionLabel = `作为${targetName}别名`
      } else if (targetName && action === "merge_with_existing") {
        actionLabel = `合并到${targetName}`
      }
      const isTemporary = action === "temporary_only"
      const isSuggestionShadow = this._isSuggestionShadow(c)
      const canAccept = isSuggestionShadow || !["temporary_only", "ignore", "link_to_existing", "alias_of_existing", "merge_with_existing"].includes(action)
      const canAlias = isSuggestionShadow || ["link_to_existing", "alias_of_existing"].includes(action)
      const canMerge = isSuggestionShadow || action === "merge_with_existing"
      const meta = this._candidateMeta(c)
      html += `
        <tr data-id="${esc(id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, id, `选择 ${c.name || "待处理项"}`)}</td>
          <td data-label="名称">${esc(c.name)}</td>
          <td data-label="类型" class="world-table-cell--type">${esc(c.entity_type)}</td>
          <td data-label="重要度">${esc(c.importance || c.importance_score || "-")}</td>
          <td data-label="建议动作"><span class="candidate-action-badge candidate-action-badge--${esc(action)}">${esc(actionLabel)}</span></td>
          <td data-label="证据" style="max-width:220px;color:var(--text-dim);font-size:12px;">${this._inlineEvidenceHtml(meta)}</td>
          <td data-label="操作"><div class="row-actions">
            ${canAccept ? `<button class="btn btn-sm btn-primary" data-action="accept-candidate" data-id="${esc(id)}">采用</button>` : ""}
            ${isSuggestionShadow ? `<button class="btn btn-sm" data-action="edit-entity" data-id="${esc(id)}">编辑后采用</button>` : ""}
            ${canAlias ? `<button class="btn btn-sm btn-primary" data-action="resolve-candidate-alias" data-id="${esc(id)}" data-target-name="${esc(targetName)}">设为别名</button>` : ""}
            ${canMerge ? `<button class="btn btn-sm" data-action="merge-entity" data-id="${esc(id)}" data-target-name="${esc(targetName)}">合并到</button>` : ""}
            <button class="btn btn-sm ${isTemporary ? "" : "btn-danger"}" data-action="ignore-candidate" data-id="${esc(id)}">${isTemporary ? "设为临时" : "忽略"}</button>
          </div></td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html = renderBulkToolbar(this, scope, [
      { action: "accept-candidates", label: "批量采用", className: "btn-primary" },
      { action: "ignore-candidates", label: "批量忽略/设为临时", className: "btn-danger" },
    ], { noun: "待处理项", hint: "合并项仍需逐条选择目标对象" }) + html
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
    return `
      <div class="filter-bar" style="margin-bottom:12px;">
        <select class="form-select" id="review-candidate-action" aria-label="建议动作筛选">
          <option value="">全部动作</option>
          ${["create_new", "link_to_existing", "alias_of_existing", "merge_with_existing", "temporary_only", "ignore", "needs_user_decision"].map((value) => `<option value="${esc(value)}" ${this._candidateFilters.suggested_action === value ? "selected" : ""}>${esc(WORLD_SUGGESTED_ACTION_LABELS[value])}</option>`).join("")}
        </select>
        <input class="form-input" id="review-candidate-source" value="${esc(this._candidateFilters.source)}" placeholder="来源" />
        <input class="form-input" id="review-candidate-workflow" value="${esc(this._candidateFilters.workflow_id)}" placeholder="Workflow" />
        <input class="form-input" id="review-candidate-scene" value="${esc(this._candidateFilters.scene_index)}" placeholder="Scene" />
        <input class="form-input" id="review-candidate-chapter" value="${esc(this._candidateFilters.source_chapter_index)}" placeholder="章节" />
        <input class="form-input" id="review-candidate-confidence-min" value="${esc(this._candidateFilters.confidence_min)}" placeholder="最低置信度" />
        <input class="form-input" id="review-candidate-confidence-max" value="${esc(this._candidateFilters.confidence_max)}" placeholder="最高置信度" />
        <button class="btn btn-sm" data-action="apply-candidate-review-filters">筛选</button>
        <button class="btn btn-sm" data-action="reset-candidate-review-filters">清空</button>
      </div>
    `
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
    let html = `
      <p class="world-list-description">
        ${reviewOnly ? "处理 AI 抽取或导入提出、尚未采用的关系。" : "管理世界对象与人物之间的关系。"}
      </p>
      ${reviewOnly ? this._renderRelationReviewFilters() : `<div class="world-list-actions__secondary">
        <button class="btn btn-primary" data-action="create-relation">新建关系</button>
      </div>`}
    `
    if (!state.currentProjectId) return html + '<div class="empty-state"><p>请先选择项目。</p></div>'

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
      if (rels.length === 0) {
        return html + `<div class="empty-state"><p>${reviewOnly ? "没有待处理关系。" : "还没有建立人物关系。"}</p><p class="world-text-dim">关系网可以帮助你梳理角色之间的恩怨情仇。</p></div>`
      }
      const scope = "world-relations"
      const ids = rels.map((rel) => rel.id || rel.relationship_id).filter(Boolean)
      reconcileBulkSelection(this, scope, ids)
      html += renderBulkToolbar(this, scope, [
        { action: "review-relations", label: "批量采用", className: "btn-primary" },
        { action: "delete-relations", label: "批量删除", className: "btn-danger" },
      ], { noun: "关系" })
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

  _renderRelationReviewFilters() {
    return `
      <div class="filter-bar" style="margin-bottom:12px;">
        <input class="form-input" id="review-relation-q" value="${esc(this._relationFilters.q)}" placeholder="搜索关系/对象" />
        <input class="form-input" id="review-relation-type" value="${esc(this._relationFilters.relation_type)}" placeholder="关系类型" />
        <input class="form-input" id="review-relation-chapter" value="${esc(this._relationFilters.source_chapter_id)}" placeholder="章节 ID" />
        <input class="form-input" id="review-relation-strength-min" value="${esc(this._relationFilters.strength_min)}" placeholder="最低强度" />
        <button class="btn btn-sm" data-action="apply-relation-review-filters">筛选</button>
        <button class="btn btn-sm" data-action="reset-relation-review-filters">清空</button>
      </div>
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
      ${this._aliasEvidenceHtml({
        source_chapter_index: relation.source_chapter_id,
        confidence: relation.strength,
        quote: relation.quote,
      })}
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
    let html = `
      <p class="world-list-description">
        ${reviewOnly ? "处理尚未采用的别名。别名不独立创建对象。" : "管理世界对象的别名、称号和化名。别名不独立创建对象。"}
      </p>
      ${reviewOnly ? this._renderAliasReviewFilters() : `<div class="world-list-actions__secondary">
        <button class="btn btn-primary" data-action="create-alias">新建别名</button>
      </div>`}
    `
    if (!state.currentProjectId) return html + '<div class="empty-state"><p>请先选择项目。</p></div>'

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
      ], { noun: "别名" })
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

  _renderAliasReviewFilters() {
    return `
      <div class="filter-bar" style="margin-bottom:12px;">
        <input class="form-input" id="review-alias-q" value="${esc(this._aliasFilters.q)}" placeholder="搜索别名/对象" />
        <input class="form-input" id="review-alias-source" value="${esc(this._aliasFilters.source)}" placeholder="来源" />
        <input class="form-input" id="review-alias-workflow" value="${esc(this._aliasFilters.workflow_id)}" placeholder="Workflow" />
        <input class="form-input" id="review-alias-scene" value="${esc(this._aliasFilters.scene_index)}" placeholder="Scene" />
        <input class="form-input" id="review-alias-confidence-min" value="${esc(this._aliasFilters.confidence_min)}" placeholder="最低置信度" />
        <button class="btn btn-sm" data-action="apply-alias-review-filters">筛选</button>
        <button class="btn btn-sm" data-action="reset-alias-review-filters">清空</button>
      </div>
    `
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
    const types = [
      ["name", "名称"],
      ["title", "称号"],
      ["nickname", "昵称"],
      ["alias", "化名"],
      ["translation", "译名"],
      ["abbreviation", "简称"],
    ]
    return types
      .map(([value, label]) => `<option value="${esc(value)}" ${selected === value ? "selected" : ""}>${esc(label)}</option>`)
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
  },

  _aliasTargetCandidates(sourceId = "", selectedId = "", query = "") {
    const normalizedQuery = String(query || "").trim().toLowerCase()
    return (this._entities || [])
      .filter((item) => this._entityId(item) !== sourceId)
      .filter((item) => this._isAliasTargetEntity(item))
      .filter((item) => !normalizedQuery || String(item.name || "").toLowerCase().includes(normalizedQuery) || this._entityId(item) === selectedId)
      .slice(0, 20)
  },

  _bindAliasTargetSearch({ sourceId = "", selectedId = "" } = {}) {
    const button = document.getElementById("alias-target-search")
    const input = document.getElementById("alias-target-query")
    const select = document.getElementById("alias-target-id")
    if (!button || !input || !select) return
    button.onclick = async () => {
      try {
        const data = await api.world.listEntities({
          novel_id: state.currentProjectId,
          q: input.value || "",
          limit: 20,
        })
        const items = (data.items || data || [])
          .filter((item) => this._entityId(item) !== sourceId)
          .filter((item) => this._isAliasTargetEntity(item))
        select.innerHTML = this._mergeTargetOptionsHtml(items, selectedId)
      } catch (err) {
        toast(err.message || "搜索目标对象失败", "error")
      }
    }
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

  showAliasReviewEditForm(entityId, aliasText) {
    const alias = this._findAlias(entityId, aliasText)
    if (!alias) {
      toast("未找到目标别名", "error")
      return
    }
    const initialTargets = this._aliasTargetCandidates("", entityId, alias.entity_name || "")
    if (!initialTargets.find((item) => this._entityId(item) === entityId)) {
      initialTargets.unshift({
        id: entityId,
        name: alias.entity_name || entityId,
        entity_type: "-",
        status: "canonical",
      })
    }
    const formHtml = `
      <div class="form-group">
        <label>搜索目标对象</label>
        <div class="row-actions">
          <input class="form-input" id="alias-target-query" placeholder="输入目标对象名称" value="${esc(alias.entity_name || "")}" />
          <button class="btn btn-sm" id="alias-target-search" type="button">搜索</button>
        </div>
      </div>
      <div class="form-group">
        <label>目标对象 *</label>
        <select class="form-select" id="alias-target-id">${this._mergeTargetOptionsHtml(initialTargets, entityId)}</select>
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
    setTimeout(() => this._bindAliasTargetSearch({ selectedId: entityId }), 0)
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
    const initialTargets = this._aliasTargetCandidates(candidateId, targetId, targetName)
    const formHtml = `
      <p style="margin-bottom:10px;">将 <strong>${esc(candidate.name || "")}</strong> 登记为已有对象的别名。</p>
      <div class="form-group">
        <label>搜索目标对象</label>
        <div class="row-actions">
          <input class="form-input" id="alias-target-query" placeholder="输入目标对象名称" value="${esc(targetName)}" />
          <button class="btn btn-sm" id="alias-target-search" type="button">搜索</button>
        </div>
      </div>
      <div class="form-group">
        <label>目标对象 *</label>
        <select class="form-select" id="alias-target-id">${this._mergeTargetOptionsHtml(initialTargets, targetId)}</select>
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
    setTimeout(() => this._bindAliasTargetSearch({ sourceId: candidateId, selectedId: targetId }), 0)
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

  editEntity(id) {
    const entity = this._findEntity(id)
    if (!entity) return
    const suggestionId = this._suggestionId(entity)

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-entity-name" value="${esc(entity.name)}" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="edit-entity-type">
          ${this._entityTypes.map((t) => `<option value="${esc(t.value)}" ${entity.entity_type === t.value ? "selected" : ""}>${esc(t.label)}</option>`).join("")}
        </select>
      </div>
      <div class="form-group">
        <label>概要</label>
        <textarea class="form-textarea" id="edit-entity-summary" rows="3">${esc(entity.summary || "")}</textarea>
      </div>
    `

    showModalHtml(suggestionId ? "编辑后采用世界对象" : "编辑世界对象", formHtml, [
      {
        text: suggestionId ? "编辑后采用" : "保存",
        class: "btn-primary",
        handler: async () => {
          try {
            const payload = {
              name: document.getElementById("edit-entity-name")?.value,
              entity_type: document.getElementById("edit-entity-type")?.value,
              summary: document.getElementById("edit-entity-summary")?.value,
            }
            if (suggestionId) {
              await api.world.editAndConfirmSuggestion(
                suggestionId,
                payload,
                state.currentProjectId,
              )
            } else {
              await api.world.updateEntity(id, payload, state.currentProjectId)
            }
            toast(suggestionId ? "已编辑并采用" : "已保存", "success")
            router.refresh()
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
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
    this._filters = {
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
    await this._navigateWithQuery("objects", this._objectQueryFromState())
  },

  async _resetFilters() {
    this._filters = { ...WORLD_FILTER_DEFAULTS }
    this._objectViewMode = "table"
    this._advancedFiltersOpen = false
    await this._navigateWithQuery("objects", this._objectQueryFromState())
  },

  async _applyCandidateReviewFilters() {
    this._candidateFilters = {
      ...WORLD_CANDIDATE_FILTER_DEFAULTS,
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
    this._aliasFilters = {
      ...WORLD_ALIAS_FILTER_DEFAULTS,
      q: document.getElementById("review-alias-q")?.value?.trim() || "",
      source: document.getElementById("review-alias-source")?.value?.trim() || "",
      workflow_id: document.getElementById("review-alias-workflow")?.value?.trim() || "",
      scene_index: document.getElementById("review-alias-scene")?.value?.trim() || "",
      confidence_min: document.getElementById("review-alias-confidence-min")?.value?.trim() || "",
    }
    await router.refresh()
  },

  async _resetAliasReviewFilters() {
    this._aliasFilters = { ...WORLD_ALIAS_FILTER_DEFAULTS }
    await router.refresh()
  },

  async _applyRelationReviewFilters() {
    this._relationFilters = {
      ...WORLD_RELATION_FILTER_DEFAULTS,
      q: document.getElementById("review-relation-q")?.value?.trim() || "",
      relation_type: document.getElementById("review-relation-type")?.value?.trim() || "",
      source_chapter_id: document.getElementById("review-relation-chapter")?.value?.trim() || "",
      strength_min: document.getElementById("review-relation-strength-min")?.value?.trim() || "",
    }
    await router.refresh()
  },

  async _resetRelationReviewFilters() {
    this._relationFilters = { ...WORLD_RELATION_FILTER_DEFAULTS }
    await router.refresh()
  },

  async _changePage(delta) {
    const newSkip = this._filters.skip + delta * this._filters.limit
    if (newSkip < 0) return
    if (newSkip >= this._total) return
    this._filters.skip = newSkip
    await this._navigateWithQuery("objects", this._objectQueryFromState())
  },

  async _changeListPage(filters, total, loader, delta) {
    const newSkip = filters.skip + delta * filters.limit
    if (newSkip < 0) return
    if (newSkip >= total) return
    filters.skip = newSkip
    await loader()
    if (filters === this._candidateFilters) {
      await this._navigateWithQuery(state.currentSubView || "review-objects", this._candidateQueryFromState())
    } else {
      await router.refresh()
    }
  },

  async _changeCandidatePage(delta) {
    await this._changeListPage(this._candidateFilters, this._candidateTotal, () => this._loadCandidates(), delta)
  },

  async _changeRelationPage(delta) {
    await this._changeListPage(this._relationFilters, this._relationTotal, async () => {}, delta)
  },

  async _changeAliasPage(delta) {
    await this._changeListPage(this._aliasFilters, this._aliasTotal, async () => {}, delta)
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
      "nav-map": () => router.navigate("map", null),
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
      "toggle-extract": () => this._toggleAutoExtract(),
      "toggle-advanced-filters": () => this._toggleAdvancedFilters(),
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
      "edit-relation-review": (_e, _t, ctx) => ctx.id && this.showRelationReviewEditForm(ctx.id),
      "mark-relation-reviewed": (_e, _t, ctx) => ctx.id && this._markRelationReviewed(ctx.id),
      "mark-relation-unreviewed": (_e, _t, ctx) => ctx.id && this._markRelationUnreviewed(ctx.id),
      "delete-relation": (_e, _t, ctx) => ctx.id && this.deleteRelation(ctx.id),
      "create-alias": () => this.showAliasCreateForm(),
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
    if (scope === "world-aliases") return this._aliases.map((item) => this._aliasKey(item)).filter(Boolean)
    return []
  },

  _itemsForBulkScope(scope) {
    const selection = getBulkSelection(this, scope)
    if (scope === "world-objects") return selectedItemsFrom(this._entities, selection, (item) => this._entityId(item))
    if (scope === "world-candidates") return selectedItemsFrom(this._candidates, selection, (item) => this._entityId(item))
    if (scope === "world-relations") return selectedItemsFrom(this._relations, selection, (item) => item.id || item.relationship_id)
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
      const target = await api.world.getMapOpenTarget(state.currentProjectId, { focusEntityId: entityId })
      const url = buildMapUrl({
        projectId: state.currentProjectId,
        mapId: target.map_id,
        sceneId: target.scene_id,
        focusEntityId: target.focus_entity_id || entityId,
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

  _showCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-entity-name" placeholder="对象名称" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="create-entity-type">
          ${this._entityTypes.map((t) => `<option value="${esc(t.value)}">${esc(t.label)}</option>`).join("")}
        </select>
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
          const name = document.getElementById("create-entity-name")?.value
          if (!name) {
            toast("请输入名称", "warning")
            return
          }

          const payload = {
            name,
            entity_type: document.getElementById("create-entity-type")?.value || "item",
            summary: document.getElementById("create-entity-summary")?.value || "",
          }

          try {
            await api.world.createEntity(payload, state.currentProjectId)
            toast(`对象 "${name}" 已创建`, "success")
            router.refresh()
          } catch (err) {
            const detail = this._createConflictDetail(err)
            if (detail?.requires_confirmation) {
              const similar = this._formatSimilarEntities(detail.similar_entities)
                confirmAction(
                  `发现相似对象：${similar || "已有对象"}。是否仍要创建？`,
                  async () => {
                    try {
                      await api.world.createEntity({ ...payload, force_create: true }, state.currentProjectId)
                      toast(`对象 "${name}" 已创建`, "success")
                      router.refresh()
                    } catch (err2) {
                      toast(`创建失败：${err2.message}`, "error")
                    }
                  },
                  "强制创建",
                )
                return
            }
            toast(`创建失败：${err.message}`, "error")
          }
        },
      },
    ])
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
    const initialTargets = this._mergeTargetCandidates(entity, targetId, targetName)

    const formHtml = `
      <p style="margin-bottom:10px;">将 <strong>${esc(entity.name)}</strong> 合并到目标已采用对象。</p>
      <div class="form-group">
        <label>搜索目标对象</label>
        <div class="row-actions">
          <input class="form-input" id="merge-target-query" placeholder="输入目标对象名称" value="${esc(targetName)}" />
          <button class="btn btn-sm" id="merge-target-search" type="button">搜索</button>
        </div>
      </div>
      <div class="form-group">
        <label>选择目标对象 *</label>
        <select class="form-select" id="merge-target-id">
          ${this._mergeTargetOptionsHtml(initialTargets, targetId)}
        </select>
        <p style="font-size:12px;color:var(--text-muted);margin-top:6px;">显示名称、类型、状态和摘要；没有明确目标时请先搜索再选择。</p>
      </div>
    `
    showModalHtml("合并对象", formHtml, [{
      text: "合并",
      class: "btn-primary",
      handler: async () => {
        const targetId = document.getElementById("merge-target-id")?.value
        if (!targetId) { toast("请输入目标对象 ID", "warning"); return }
        try {
          await this._mergeEntity(candidateId, targetId)
        } catch (err) {
          toast(err.message || "合并失败", "error")
        }
      },
    }])
    setTimeout(() => this._bindMergeTargetSearch(entity, targetId), 0)
  },

  _mergeTargetCandidates(sourceEntity, targetId, targetName) {
    const sourceId = this._entityId(sourceEntity)
    const query = String(targetName || "").trim().toLowerCase()
    const items = this._entities
      .filter((item) => this._entityId(item) !== sourceId)
      .filter((item) => this._isMergeTargetEntity(item))
      .filter((item) => !query || String(item.name || "").toLowerCase().includes(query) || this._entityId(item) === targetId)
      .slice(0, 20)
    return items
  },

  _isMergeTargetEntity(entity) {
    return entity?.status === "canonical"
  },

  _mergeTargetOptionsHtml(items, selectedId = "") {
    if (!items.length) {
      return '<option value="">未找到目标对象，请搜索</option>'
    }
    return items.map((item) => {
      const id = this._entityId(item)
      const summary = item.summary || item.public_info || ""
      const label = `${item.name || "未命名"} · ${item.entity_type || "-"} · ${item.status || "-"}${summary ? ` · ${summary}` : ""}`
      return `<option value="${esc(id)}" ${id === selectedId ? "selected" : ""}>${esc(label)}</option>`
    }).join("")
  },

  _bindMergeTargetSearch(sourceEntity, selectedId = "") {
    const button = document.getElementById("merge-target-search")
    const input = document.getElementById("merge-target-query")
    const select = document.getElementById("merge-target-id")
    if (!button || !input || !select) return
    button.onclick = async () => {
      const query = input.value || ""
      try {
        const data = await api.world.listEntities({
          novel_id: state.currentProjectId,
          q: query,
          display_state: "active",
          limit: 20,
        })
        const sourceId = this._entityId(sourceEntity)
        const items = (data.items || data || [])
          .filter((item) => this._entityId(item) !== sourceId)
          .filter((item) => this._isMergeTargetEntity(item))
        select.innerHTML = this._mergeTargetOptionsHtml(items, selectedId)
      } catch (err) {
        toast(err.message || "搜索目标对象失败", "error")
      }
    }
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
          我理解这会合并两个已采用对象
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
        const payload = selected.map(({ item, card }) => ({
          action: item.action,
          source_entity_id: item.source_entity_id,
          target_entity_id: item.target_entity_id,
          alias: item.alias || item.source_entity_name,
          allow_canonical_merge: Boolean(card?.querySelector("[data-canonical-merge]")?.checked),
        }))
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
        if (!payload.target_id) { toast("请输入目标对象 ID", "warning"); return }
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
