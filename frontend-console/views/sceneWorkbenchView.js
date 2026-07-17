import {
  bindActionMenus,
  bindWorkspaceClick,
  renderActionMenu,
  renderLoadingSkeleton,
} from "../shared/viewHelper.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"
import { structureAssetDisplay } from "../shared/assetDisplayState.js"
import { importAuthorizationNotice, importAuthorizationPayload } from "../shared/importAuthorization.js"
import { confirmAsync } from "../shared/confirmAsync.js"
import { renderWorkspaceRail, workspaceRailKey } from "../shared/workspaceRail.js"
import { createReferencePicker } from "../shared/referencePicker.js"

const HEALTH_ORDER = [
  ["unreviewed", "未复核"],
  ["unassigned", "未关联章节"],
  ["missing_setup", "缺设定"],
  ["needs_organize", "待整理"],
]

const STATUS_OPTIONS = [
  ["draft", "工作稿"],
  ["candidate", "待处理"],
  ["canonical", "已采用"],
  ["deprecated", "历史"],
]

const SOURCE_OPTIONS = [
  ["manual", "手动"],
  ["deep_import", "深度导入"],
  ["ai_generated", "AI 生成"],
  ["manual_fusion", "融合结果"],
]

const BOUNDARY_STATUS_OPTIONS = [
  ["uncertain", "边界不确定"],
]

const PHASE_OPTIONS = [
  ["phase1a_fallback", "Phase 1A fallback"],
  ["phase1b_fusion", "Phase 1B fusion"],
]

const CONFIDENCE_BAND_OPTIONS = [
  ["low", "低于 0.5"],
  ["medium", "0.5-0.8"],
  ["high", "0.8 以上"],
]

const SCENE_FILTER_DEFAULTS = {
  health: "",
  q: "",
  status: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  boundary_status: "",
  phase: "",
  phase1a_fallback: false,
  chapter_from: "",
  chapter_to: "",
  confidence_band: "",
  segment: "",
  skip: 0,
  limit: 20,
}
const FUSION_SUGGESTION_DISMISS_BATCH_SIZE = 100

const TAG_OPTIONS = [
  ["draft", "未标注"],
  ["hook", "钩子"],
  ["inciting_incident", "激励事件"],
  ["rising_action", "冲突升级"],
  ["climax", "阶段高潮"],
  ["valley", "低谷"],
  ["transition", "过渡"],
  ["payoff", "爽点"],
]

const DRAFT_REVIEW_FIELDS = [
  ["title", "标题"],
  ["goal", "目标"],
  ["core_conflict", "核心冲突"],
  ["emotional_beat", "情感节奏"],
  ["must_happen", "必须发生"],
  ["must_not_happen", "禁止发生"],
  ["narrative_tag", "叙事标签"],
  ["pov_character_id", "POV"],
  ["chapter_ids", "章节映射"],
]
const FUSION_DRAFT_REVIEW_FIELDS = [
  ...DRAFT_REVIEW_FIELDS.slice(0, 6),
  ["narrative_function", "叙事功能"],
  ...DRAFT_REVIEW_FIELDS.slice(6),
]

const sceneWorkbenchView = {
  _loading: true,
  _workbench: null,
  _fusionPreviewPending: false,
  _fusionPreviewProjectId: null,
  _fusionPreviewRequestSeq: 0,
  _fusionSavePending: false,
  _fusionSaveControls: [],
  _total: 0,
  _activeHealth: null,
  _filters: { ...SCENE_FILTER_DEFAULTS },
  _advancedFiltersOpen: false,
  _selectedFusionSceneIds: new Set(),
  _autoExtractTaskId: null,
  _autoExtractProgress: null,
  _autoExtractPoller: null,
  _autoExtractMeta: null,
  _autoExtractCancelPending: false,
  _fusionSuggestions: [],
  _activeDraftReview: null,
  _mobileDetailOpen: false,
  _selectedSceneIdValue: null,
  _viewMode: "hot",
  _mergeReferencePicker: null,
  _mergePreviewRequestGeneration: 0,

  async onEnter() {
    this._loading = true
    this._workbench = null
    this._total = 0
    this._selectedFusionSceneIds = new Set()
    this._fusionSuggestions = []
    this._viewMode = this._initialViewMode()
    this._selectedSceneIdValue = this._routeSceneId()
    if (this._selectedSceneIdValue) {
      this._filters = { ...SCENE_FILTER_DEFAULTS }
      this._activeHealth = null
    }
    this._mobileDetailOpen = Boolean(this._selectedSceneIdValue)
    if (!state.currentProjectId) {
      this._loading = false
      return
    }
    try {
      this._recoverAutoExtractWorkflow()
      await this._loadWorkbench()
      if (typeof window !== "undefined" && window.innerWidth < 720 && this._selectedSceneId()) {
        this._mobileDetailOpen = true
      }
    } catch (err) {
      toast(err.message || "场景工作台加载失败", "error")
      this._workbench = null
    } finally {
      this._loading = false
    }
  },

  onActivate() {
    this._bindEvents()
  },

  onLeave() {
    this._destroyMergeReferencePicker()
    this._mergePreviewRequestGeneration += 1
    this._stopAutoExtractPolling()
    this._mobileDetailOpen = false
  },

  async render() {
    if (this._loading) return renderLoadingSkeleton("场景工作台加载中...")
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目开始创作。</p></div>'
    }
    if (!this._workbench) {
      return '<div class="empty-state"><p>场景工作台暂不可用。</p></div>'
    }

    const selected = this._selectedSceneItem()
    const narrow = typeof window !== "undefined" && window.innerWidth < 720
    const showNarrowDetail = narrow && this._mobileDetailOpen && selected
    const detail = this._renderDetail(selected, narrow)
    const html = `
      <div class="scene-workbench-shell">
        <div data-role="scene-auto-extract-progress">${this._renderAutoExtractProgress()}</div>
        ${this._renderFusionSuggestionQueue()}
        <div class="scene-workbench ${narrow ? "is-narrow" : ""}">
          <section class="scene-workbench__organize">
            ${this._renderManagementFilters()}
            ${this._renderProgressFilters()}
            ${this._renderHealthFilters()}
            ${this._renderFusionToolbar()}
            ${this._renderSceneList()}
            ${this._renderPagination()}
          </section>
          ${narrow ? "" : renderWorkspaceRail({
            key: workspaceRailKey("scene-workbench", state.currentProjectId, "detail"),
            title: "Scene 详情",
            className: "scene-detail-rail workspace-rail--right",
            defaultOpen: true,
            content: `<aside class="scene-workbench__detail">${detail}</aside>`,
          })}
          ${showNarrowDetail ? `<div class="scene-workbench-drawer">${detail}</div>` : ""}
        </div>
      </div>
    `
    return html
  },

  onRendered() {
    this._bindEvents()
  },

  renderHeaderActions() {
    return `
      <div class="scene-workbench-actions" aria-label="Scene 工作台操作">
        ${this._renderViewModeToggle()}
        <button class="btn btn-sm btn-primary" data-action="ai-create-planned-scene">AI 创作细纲</button>
        <button class="btn btn-sm" data-action="scene-auto-extract">从正文提取 Scene</button>
        <span data-role="smart-dedup-action"></span>
      </div>
    `
  },

  selectedSceneIdForAi() {
    return this._selectedSceneId()
  },

  async _loadWorkbench() {
    if (!state.currentProjectId) return
    const selectedSceneId = this._routeSceneId()
    try {
      this._workbench = await api.outline.getSceneWorkbench(
        state.currentProjectId,
        selectedSceneId,
        this._sceneWorkbenchParams(),
      )
    } catch (err) {
      const canRecoverMissingSelection = selectedSceneId
        && state.currentView === "outline"
        && state.currentSubView === "scenes"
        && err?.status === 404
        && err?.detail === "Scene not found"
      if (!canRecoverMissingSelection) throw err
      this._clearEmbeddedSceneHistory()
      this._workbench = await api.outline.getSceneWorkbench(
        state.currentProjectId,
        null,
        this._sceneWorkbenchParams(),
      )
    }
    this._total = Number(this._workbench?.total ?? this._workbench?.items?.length ?? 0) || 0
    const effectiveSkip = Number(this._workbench?.skip)
    if (Number.isInteger(effectiveSkip) && effectiveSkip >= 0) {
      this._filters.skip = effectiveSkip
    }
    const pendingSuggestions = Number(
      this._workbench?.fusion_suggestions?.pending_count || 0,
    )
    if (pendingSuggestions > 0 && api.outline.listFusionSuggestions) {
      const suggestions = []
      const pageSize = 50
      let skip = 0
      let total = pendingSuggestions
      while (skip < total) {
        const result = await api.outline.listFusionSuggestions(
          state.currentProjectId,
          { skip, limit: pageSize },
        )
        const items = Array.isArray(result?.items) ? result.items : []
        suggestions.push(...items)
        total = Number(result?.total ?? total) || 0
        if (!items.length) break
        skip += items.length
      }
      this._fusionSuggestions = suggestions
    } else {
      this._fusionSuggestions = []
    }
  },

  _sceneWorkbenchParams() {
    const params = {
      skip: this._filters.skip,
      limit: this._filters.limit,
      view_mode: this._viewMode,
    }
    for (const key of [
      "health",
      "q",
      "status",
      "source",
      "workflow_id",
      "needs_review",
      "boundary_status",
      "phase",
      "chapter_from",
      "chapter_to",
      "confidence_band",
    ]) {
      const value = this._filters[key]
      if (value === "true") params[key] = true
      else if (value === "false") params[key] = false
      else if (value) params[key] = value
    }
    if (this._filters.phase1a_fallback) params.phase1a_fallback = true
    if (this._viewMode === "hot") {
      if (this._filters.segment) params.segment = this._filters.segment
      if (this._shouldAnchorLatest()) params.anchor = "latest"
    }
    return params
  },

  _sceneQuery() {
    if (typeof window !== "undefined") {
      const queryIndex = window.location.hash.indexOf("?")
      return new URLSearchParams(
        queryIndex >= 0 ? window.location.hash.slice(queryIndex + 1) : "",
      )
    }
    const query = router.getCurrentQuery?.()
    return new URLSearchParams(query?.toString ? query.toString() : "")
  },

  _modePreferenceKey() {
    return `novel_view_mode:${state.currentProjectId || "none"}:scene-workbench`
  },

  _initialViewMode() {
    const requested = this._sceneQuery().get("mode")
    if (requested === "normal" || requested === "hot") return requested
    try {
      const stored = localStorage.getItem(this._modePreferenceKey())
      if (stored === "normal" || stored === "hot") return stored
    } catch {
      // localStorage 不可用时使用热点默认值。
    }
    return "hot"
  },

  _rememberViewMode(mode) {
    try {
      localStorage.setItem(this._modePreferenceKey(), mode)
    } catch {
      // 偏好写入失败不阻断工作台。
    }
  },

  _hasManagementFilters() {
    return [
      "health", "q", "status", "source", "workflow_id", "needs_review",
      "boundary_status", "phase", "chapter_from", "chapter_to", "confidence_band",
    ].some((key) => Boolean(this._filters[key])) || Boolean(this._filters.phase1a_fallback)
  },

  _shouldAnchorLatest() {
    return this._viewMode === "hot"
      && !this._routeSceneId()
      && !this._filters.segment
      && Number(this._filters.skip || 0) === 0
      && !this._hasManagementFilters()
  },

  _renderViewModeToggle() {
    return `
      <span class="scene-view-mode-toggle" aria-label="Scene 检索模式">
        <button class="btn btn-sm ${this._viewMode === "normal" ? "btn-primary" : ""}" data-action="set-scene-view-mode" data-mode="normal">普通</button>
        <button class="btn btn-sm ${this._viewMode === "hot" ? "btn-primary" : ""}" data-action="set-scene-view-mode" data-mode="hot">热点</button>
      </span>
    `
  },

  _renderManagementFilters() {
    const advancedFilters = this._advancedFiltersOpen ? `
      <details class="scene-filter-field scene-filter-field--wide" ${this._filters.workflow_id ? "open" : ""}>
        <summary>诊断筛选${this._filters.workflow_id ? "（1）" : ""}</summary>
        <label>
          <span>Workflow 诊断 ID</span>
          <input class="form-input" id="scene-filter-workflow-id" data-diagnostic-field value="${esc(this._filters.workflow_id)}" placeholder="workflow_id" />
        </label>
      </details>
      ${this._filterSelect("scene-filter-boundary-status", "边界", this._filters.boundary_status, BOUNDARY_STATUS_OPTIONS, "全部边界")}
      ${this._filterSelect("scene-filter-phase", "阶段", this._filters.phase, PHASE_OPTIONS, "全部阶段")}
      ${this._filterSelect("scene-filter-confidence-band", "置信度", this._filters.confidence_band, CONFIDENCE_BAND_OPTIONS, "全部置信度")}
      <label class="scene-filter-checkbox">
        <input id="scene-filter-phase1a-fallback" type="checkbox" ${this._filters.phase1a_fallback ? "checked" : ""} />
        <span>Phase 1A fallback</span>
      </label>
    ` : ""
    return `
      <div class="scene-management-filters" aria-label="Scene 管理筛选">
        <label class="scene-filter-field scene-filter-field--wide">
          <span>搜索</span>
          <input class="form-input" id="scene-filter-q" value="${esc(this._filters.q)}" placeholder="标题 / 目标 / 冲突" />
        </label>
        <label class="scene-filter-field">
          <span>起始章</span>
          <input class="form-input" id="scene-filter-chapter-from" type="number" min="1" value="${esc(this._filters.chapter_from)}" />
        </label>
        <label class="scene-filter-field">
          <span>结束章</span>
          <input class="form-input" id="scene-filter-chapter-to" type="number" min="1" value="${esc(this._filters.chapter_to)}" />
        </label>
        ${this._filterSelect("scene-filter-status", "状态", this._filters.status, STATUS_OPTIONS, "全部状态")}
        ${this._filterSelect("scene-filter-source", "来源", this._filters.source, SOURCE_OPTIONS, "全部来源")}
        ${this._filterSelect("scene-filter-needs-review", "注意", this._filters.needs_review, [["true", "需要人工检查"], ["false", "无注意项"]], "全部注意原因")}
        <div class="scene-filter-actions">
          <button class="btn btn-sm" data-action="toggle-advanced-scene-filters">${this._advancedFiltersOpen ? "▾" : "▸"} 高级</button>
          <button class="btn btn-sm btn-primary" data-action="apply-scene-filters">应用</button>
          <button class="btn btn-sm" data-action="reset-scene-filters">重置</button>
        </div>
        ${advancedFilters}
      </div>
    `
  },

  _filterSelect(id, label, value, options, emptyLabel) {
    return `
      <label class="scene-filter-field">
        <span>${esc(label)}</span>
        <select class="form-select" id="${esc(id)}">
          <option value="">${esc(emptyLabel)}</option>
          ${options.map(([optionValue, optionLabel]) => `
            <option value="${esc(optionValue)}" ${optionValue === value ? "selected" : ""}>${esc(optionLabel)}</option>
          `).join("")}
        </select>
      </label>
    `
  },

  _renderHealthFilters() {
    const organizeBreakdown = this._workbench.health?.needs_organize?.breakdown || {}
    const hasOrganizeBreakdown = Object.values(organizeBreakdown).some((count) => Number(count) > 0)
    return `
      <div class="scene-health-bar">
        ${HEALTH_ORDER.map(([key, fallback]) => {
          const item = this._workbench.health?.[key] || { label: fallback, count: 0 }
          const breakdown = key === "needs_organize" ? item.breakdown || {} : {}
          const breakdownText = [
            breakdown.scene_structure ? `结构 ${breakdown.scene_structure}` : "",
            breakdown.source_mapping ? `定位 ${breakdown.source_mapping}` : "",
            breakdown.scene_fusion_suggestion ? `融合 ${breakdown.scene_fusion_suggestion}` : "",
          ].filter(Boolean).join(" · ")
          const activeHealth = this._filters.health || this._activeHealth
          const active = activeHealth === key ? "active" : ""
          return `
            <button class="scene-health-filter ${active}" data-action="filter-health" data-id="${esc(key)}">
              <span>${esc(this._healthLabel(key))}</span>
              <strong>${esc(item.count ?? 0)}</strong>
              ${breakdownText ? `<small>${esc(breakdownText)}</small>` : ""}
            </button>
          `
        }).join("")}
      </div>
      ${hasOrganizeBreakdown ? `
        <p class="scene-health-count-note" role="note">
          待整理总数按 Scene 去重；结构、正文定位和融合等原因可在同一 Scene 上重叠，原因数不能相加作为总数。
        </p>
      ` : ""}
    `
  },

  _renderProgressFilters() {
    if (this._viewMode !== "hot" || !this._workbench?.progress) return ""
    const progress = this._workbench.progress
    const items = [
      ["current", "当前", progress.current],
      ["upcoming", "后续", progress.upcoming],
      ["past", "已写过", progress.past],
      ["unassigned", "未定位", progress.unassigned],
    ]
    return `
      <section class="scene-progress-panel" aria-label="剧情进度">
        <div class="scene-progress-panel__heading">
          <strong>当前剧情定位</strong>
          <span>${progress.as_of_chapter == null ? "尚无有效章节" : `截至第 ${esc(progress.as_of_chapter)} 章`}</span>
        </div>
        <div class="scene-progress-bar">
          ${items.map(([key, label, count]) => `
            <button class="scene-progress-filter ${this._filters.segment === key ? "active" : ""}" data-action="filter-progress-segment" data-segment="${key}">
              <span>${label}</span><strong>${esc(count ?? 0)}</strong>
            </button>
          `).join("")}
        </div>
      </section>
    `
  },

  _renderSceneList() {
    const items = this._filteredItems()
    const selectedId = this._selectedSceneId()
    const rows = items.map((item) => this._renderSceneRow(item, selectedId)).join("")
    const unassigned = this._renderUnassignedChapters()
    if (!rows && !unassigned) {
      return '<div class="empty-state"><p>暂无需要整理的 Scene。</p></div>'
    }
    return `<div class="scene-workbench-list">${rows}${unassigned}</div>`
  },

  _renderPagination() {
    if (this._total <= this._filters.limit) return ""
    const currentPage = Math.floor(this._filters.skip / this._filters.limit) + 1
    const totalPages = Math.ceil(this._total / this._filters.limit)
    const prevDisabled = this._filters.skip <= 0 ? "disabled" : ""
    const nextDisabled = this._filters.skip + this._filters.limit >= this._total ? "disabled" : ""
    return `
      <div class="scene-workbench-pagination">
        <button class="btn btn-sm" data-action="prev-scene-page" ${prevDisabled}>上一页</button>
        <span>第 ${currentPage} / ${totalPages} 页，共 ${esc(this._total)} 条</span>
        <button class="btn btn-sm" data-action="next-scene-page" ${nextDisabled}>下一页</button>
      </div>
    `
  },

  _healthReasons(item) {
    return item?.health_details?.needs_organize || []
  },

  _contextAction(item, healthKey = null) {
    const scene = item?.scene || {}
    const health = item?.health || []
    const reasons = this._healthReasons(item)
    const reviewState = this._sceneReviewState(item)
    const display = structureAssetDisplay(scene)
    const suggestion = reasons.find((reason) => reason.code === "pending_scene_fusion_suggestion")
    const sourceMapping = reasons.find((reason) => [
      "source_mapping_chapter_only",
      "source_mapping_unresolved",
    ].includes(reason.code))
    const structure = reasons.find((reason) => [
      "manual_organize",
      "duplicate_chapter",
      "overlapping_span",
      "chunk_chapter_mismatch",
    ].includes(reason.code))
    const reviewAction = {
      key: "review",
      action: "context-review-scene",
      label: display.displayState === "active" ? "标记已检查" : "采用",
    }
    if (healthKey === "unreviewed") return reviewAction
    if (healthKey === "needs_organize") {
      if (suggestion) return {
        key: "suggestion",
        action: "context-open-fusion-suggestion",
        label: "查看融合建议",
        suggestionId: suggestion.suggestion_id,
      }
      if (sourceMapping) return {
        key: "source_mapping",
        action: "context-confirm-source-mapping",
        label: "确认章节定位",
        fingerprint: sourceMapping.fingerprint,
      }
      if (structure) return {
        key: "organize",
        action: "context-organize-mapping",
        label: "整理映射",
      }
    }
    if (healthKey === "unassigned") return {
      key: "assign",
      action: "context-assign-chapters",
      label: "关联章节",
    }
    if (healthKey === "missing_setup") return {
      key: "missing_setup",
      action: "context-complete-setup",
      label: "补全设定",
    }
    if (!healthKey && (
      health.includes("unreviewed")
      || reviewState.needsReview
      || display.displayState !== "active"
    )) return reviewAction
    if (!healthKey && suggestion) return this._contextAction(item, "needs_organize")
    if (!healthKey && sourceMapping) return this._contextAction(item, "needs_organize")
    if (!healthKey && structure) return this._contextAction(item, "needs_organize")
    if (!healthKey && health.includes("unassigned")) return this._contextAction(item, "unassigned")
    if (!healthKey && health.includes("missing_setup")) return this._contextAction(item, "missing_setup")
    return { key: "edit", action: "edit-workbench-scene", label: "编辑" }
  },

  _renderContextAction(item) {
    const sceneId = item?.scene?.id
    if (!sceneId) return ""
    const action = this._contextAction(item)
    const data = [
      `data-action="${esc(action.action)}"`,
      `data-id="${esc(sceneId)}"`,
      action.suggestionId ? `data-suggestion-id="${esc(action.suggestionId)}"` : "",
      action.fingerprint ? `data-fingerprint="${esc(action.fingerprint)}"` : "",
    ].filter(Boolean).join(" ")
    const primaryClass = action.key === "edit" ? "" : "btn-primary"
    return `<button class="btn btn-sm ${primaryClass} scene-context-action" ${data}>${esc(action.label)}</button>`
  },

  _spanSummaryLabel(summary) {
    const rangeLabel = String(summary?.range_label || "").trim()
    const mappingLabel = String(summary?.mapping_status_label || "").trim()
    if (rangeLabel && mappingLabel && !rangeLabel.includes(mappingLabel)) {
      return `${rangeLabel} · ${mappingLabel}`
    }
    if (rangeLabel) return rangeLabel
    const chapter = Number(summary?.chapter_index)
    return [
      Number.isInteger(chapter) && chapter > 0 ? `第 ${chapter} 章` : "",
      mappingLabel,
    ].filter(Boolean).join(" · ")
  },

  _overlapCounterpartLabel(detail) {
    return String(
      detail?.counterpart_scene_label
      || detail?.counterpart_scene_title
      || "未命名 Scene",
    ).trim() || "未命名 Scene"
  },

  _renderRowSpanSummary(item) {
    const summaries = Array.isArray(item?.span_summaries) ? item.span_summaries : []
    const labels = summaries.map((summary) => this._spanSummaryLabel(summary)).filter(Boolean)
    if (!labels.length) return ""
    const visible = labels.slice(0, 2).join("；")
    const remaining = labels.length > 2 ? `；另 ${labels.length - 2} 段` : ""
    return `<div class="scene-workbench-row__mapping" aria-label="Scene 正文范围">${esc(`${visible}${remaining}`)}</div>`
  },

  _renderRowOverlapSummary(item) {
    const details = Array.isArray(item?.overlap_details) ? item.overlap_details : []
    if (!details.length) return ""
    const first = details[0]
    const label = String(first?.range_label || "").trim()
      || `与「${this._overlapCounterpartLabel(first)}」的正文范围重叠`
    const remaining = details.length > 1 ? `；另 ${details.length - 1} 处` : ""
    return `<div class="scene-workbench-row__overlap" aria-label="Scene 正文范围重叠">${esc(`${label}${remaining}`)}</div>`
  },

  _renderOverlapShortcut(item) {
    const detail = Array.isArray(item?.overlap_details) ? item.overlap_details[0] : null
    if (!detail?.counterpart_scene_id) return ""
    const label = this._overlapCounterpartLabel(detail)
    return `<button class="btn btn-sm scene-overlap-shortcut" data-action="open-overlap-scene" data-id="${esc(detail.counterpart_scene_id)}">查看「${esc(label)}」</button>`
  },

  _renderSpanDetails(item) {
    const summaries = Array.isArray(item?.span_summaries) ? item.span_summaries : []
    if (!summaries.length) return ""
    const rows = summaries.map((summary) => {
      const label = this._spanSummaryLabel(summary)
      if (!label) return ""
      const anchor = String(summary?.anchor_excerpt || "").trim()
      return `
        <div class="scene-span-detail">
          <span>${esc(label)}</span>
          ${anchor ? `<small>原文摘要：${esc(anchor)}</small>` : ""}
        </div>
      `
    }).filter(Boolean).join("")
    if (!rows) return ""
    return `
      <section class="scene-detail-summary scene-detail-span-summaries" aria-label="Scene 正文范围">
        <div><strong>正文范围</strong><div class="scene-span-detail-list">${rows}</div></div>
      </section>
    `
  },

  _renderOverlapDetails(item) {
    const details = Array.isArray(item?.overlap_details) ? item.overlap_details : []
    if (!details.length) return ""
    const rows = details.map((detail) => {
      const counterpartLabel = this._overlapCounterpartLabel(detail)
      const chapter = Number(detail?.chapter_index)
      const chapterLabel = Number.isInteger(chapter) && chapter > 0 ? `第 ${chapter} 章 · ` : ""
      const rangeLabel = String(detail?.range_label || "").trim()
        || `${chapterLabel}与「${counterpartLabel}」重叠`
      return `
        <div class="scene-overlap-detail">
          <strong>${esc(rangeLabel)}</strong>
          <span>当前范围：${esc(`${chapterLabel}字符 ${detail.scene_start_offset}–${detail.scene_end_offset}`)}</span>
          <span>对方范围：${esc(`${chapterLabel}字符 ${detail.counterpart_start_offset}–${detail.counterpart_end_offset}`)}</span>
          <span>实际重叠：${esc(`${chapterLabel}字符 ${detail.overlap_start_offset}–${detail.overlap_end_offset}`)}</span>
          ${detail?.counterpart_scene_id ? `<button class="btn btn-sm" data-action="open-overlap-scene" data-id="${esc(detail.counterpart_scene_id)}">查看「${esc(counterpartLabel)}」</button>` : ""}
        </div>
      `
    }).join("")
    return `
      <section class="scene-detail-summary scene-detail-overlaps" aria-label="Scene 正文范围重叠">
        <div><strong>范围重叠</strong><div class="scene-overlap-detail-list">${rows}</div></div>
      </section>
    `
  },

  _renderSceneRow(item, selectedId) {
    const scene = item.scene || {}
    const selected = selectedId === scene.id ? "is-selected" : ""
    const fusionSelected = this._selectedFusionSceneIds.has(scene.id)
    const health = (item.health || []).map((key) => {
      const label = this._healthLabel(key)
      const action = this._contextAction(item, key)
      return `<button class="scene-health-chip" data-action="handle-scene-health" data-id="${esc(scene.id)}" data-health="${esc(key)}" title="${esc(action.label)}">${esc(label)}</button>`
    }).join("")
    const contextAction = this._contextAction(item)
    const segmentLabel = {
      current: "当前剧情",
      upcoming: "后续",
      past: "已写过",
      unassigned: "未定位",
    }[item.segment]
    return `
      <article class="scene-workbench-row ${selected}" data-id="${esc(scene.id)}">
        <label class="scene-fusion-select selection-checkbox" title="选择用于批量操作">
          <input
            type="checkbox"
            data-action="toggle-fusion-selection"
            data-id="${esc(scene.id)}"
            aria-label="选择用于批量操作"
            ${fusionSelected ? "checked" : ""}
          />
        </label>
        <div class="scene-workbench-row__content">
          <button class="scene-workbench-row__main" data-action="select-workbench-scene" data-id="${esc(scene.id)}">
            <div class="scene-workbench-row__meta">
              <span>#${esc(Number.isFinite(Number(scene.scene_index)) ? Number(scene.scene_index) + 1 : "-")}</span>
              <span>${esc(this._sceneStatusLabel(scene))}</span>
              <span>${esc(this._sourceLabel(scene))}</span>
              <span>${esc(item.chapter_range || "未关联章节")}</span>
              ${segmentLabel ? `<span class="scene-progress-chip scene-progress-chip--${esc(item.segment)}">${esc(segmentLabel)}</span>` : ""}
            </div>
            <div class="scene-workbench-row__title">${esc(scene.title || "未命名 Scene")}</div>
            <div class="scene-workbench-row__summary">${esc(item.summary || scene.goal || "暂无目标")}</div>
            ${this._renderRowSpanSummary(item)}
            ${this._renderRowOverlapSummary(item)}
          </button>
          <div class="scene-workbench-row__health">${health}</div>
        </div>
        <div class="scene-workbench-row__actions">
          ${this._renderContextAction(item)}
          ${this._renderOverlapShortcut(item)}
          ${contextAction.key === "edit" ? "" : `<button class="btn btn-sm scene-secondary-action" data-action="edit-workbench-scene" data-id="${esc(scene.id)}">编辑</button>`}
          ${renderActionMenu(`scene-actions-${esc(scene.id)}`, [
            { action: "open-writing-scene", label: "打开写作", data: { id: scene.id } },
            { action: "start-merge-scene", label: "合并", data: { id: scene.id } },
            { action: "start-split-scene", label: "拆分", data: { id: scene.id } },
            ...(this._sceneReviewState(item).reviewed
              ? [{ action: "mark-scene-unreviewed", label: "标记需检查", data: { id: scene.id } }]
              : []),
            ...(!structureAssetDisplay(scene).isHistory
              ? [{ action: "move-scene-to-history", label: "移入历史", data: { id: scene.id } }]
              : []),
          ])}
        </div>
      </article>
    `
  },

  _renderFusionToolbar() {
    const count = this._selectedFusionSceneIds.size
    const visibleSceneIds = this._visibleFusionSceneIds()
    const allVisibleSelected = visibleSceneIds.length > 0
      && visibleSceneIds.every((id) => this._selectedFusionSceneIds.has(id))
    const reviewItems = this._selectedSceneItems()
    const contextKinds = new Set(
      reviewItems.map((item) => this._contextAction(item).key),
    )
    const disabled = count < 2 ? "disabled" : ""
    const hint = count < 2 ? `再选 ${2 - count} 个即可融合` : "已可开始融合"
    const selectionLabel = allVisibleSelected ? "取消全选" : "全选当前列表"
    const selectionTitle = allVisibleSelected ? "取消选择当前列表中的 Scene" : "选择当前列表中的全部 Scene"
    const batchLabel = contextKinds.size !== 1
      ? "批量处理"
      : contextKinds.has("review")
        ? "采用选中项"
        : contextKinds.has("source_mapping")
          ? "确认选中项定位"
          : "批量处理"
    return `
      <div class="scene-fusion-toolbar" aria-label="Scene 批量操作">
        <div class="scene-fusion-toolbar__status">
          <strong>${esc(count)}</strong>
          <span>个 Scene 已选</span>
          <span class="scene-fusion-toolbar__hint">${esc(hint)}</span>
        </div>
        <button class="btn btn-sm" data-action="toggle-visible-fusion-selection" ${visibleSceneIds.length === 0 ? "disabled" : ""} title="${esc(selectionTitle)}">${esc(selectionLabel)}</button>
        <button class="btn btn-sm btn-primary" data-action="handle-selected-context-actions" ${count === 0 ? "disabled" : ""} title="按当前待办类型处理选中 Scene">
          ${esc(batchLabel)}
        </button>
        <button class="btn btn-sm" data-action="start-selected-merge" ${disabled} title="${count < 2 ? hint : "机械合并：目标 Scene 吸收其他 Scene"}">
          机械合并
        </button>
        <button class="btn btn-sm btn-primary" data-action="start-ai-fusion-draft" ${disabled} title="${count < 2 ? hint : "为选中的 Scene 生成 AI 融合建议"}">
          AI 融合建议
        </button>
      </div>
    `
  },

  _renderUnassignedChapters() {
    const chapters = this._workbench.unassigned_chapters || []
    if (!chapters.length && this._activeHealth !== "unassigned") return ""
    if (this._activeHealth && this._activeHealth !== "unassigned") return ""
    return chapters.map((chapter) => `
      <article class="scene-workbench-row scene-workbench-row--unassigned">
        <div class="scene-workbench-row__main">
          <div class="scene-workbench-row__meta"><span>未归类章节</span></div>
          <div class="scene-workbench-row__title">第 ${esc(chapter)} 章</div>
          <div class="scene-workbench-row__summary">尚未分配到 Scene</div>
        </div>
        <div class="scene-workbench-row__actions">
          <button class="btn btn-sm" data-action="assign-unassigned-chapter" data-chapter="${esc(chapter)}">分配 Scene</button>
        </div>
      </article>
    `).join("")
  },

  _renderDetail(item, narrow) {
    if (!item?.scene) {
      return '<div class="scene-detail-empty">选择一个 Scene 查看详情。</div>'
    }
    const scene = item.scene
    const close = narrow
      ? '<button class="btn btn-sm" data-action="close-scene-detail">关闭</button>'
      : ""
    const reviewState = this._sceneReviewState(item)
    const reviewLabel = reviewState.reviewed
      ? `已检查 · ${this._formatReviewTime(reviewState.reviewedAt)}`
      : (reviewState.needsReview ? "需要人工检查" : "无注意项")
    const attentionLabels = this._healthReasons(item).map((reason) => reason.label)
    const contextAction = this._contextAction(item)
    const replacementLinks = (scene.structure_meta?.replaced_by_scene_ids || [])
      .map((id, index) => `<button class="btn btn-sm" data-action="open-replacement-scene" data-id="${esc(id)}">替代 Scene ${esc(index + 1)}</button>`)
      .join("")
    return `
      <div class="scene-detail-panel">
        <div class="scene-detail-panel__head">
          <div>
            <div class="scene-detail-panel__eyebrow">Scene 详情</div>
            <h3>${esc(scene.title || "未命名 Scene")}</h3>
          </div>
          ${close}
        </div>
        <div class="scene-detail-grid">
          ${this._input("标题", "scene-detail-title", scene.title || "")}
          ${this._select("叙事标签", "scene-detail-tag", scene.narrative_tag || "draft", TAG_OPTIONS)}
          ${this._select("状态", "scene-detail-status", scene.status || "draft", STATUS_OPTIONS)}
          ${this._select("来源", "scene-detail-source", scene.source || "manual", SOURCE_OPTIONS)}
          ${this._textarea("目标", "scene-detail-goal", scene.goal || "")}
          ${this._textarea("核心冲突", "scene-detail-conflict", scene.core_conflict || "")}
          ${this._textarea("情感节奏", "scene-detail-emotion", scene.emotional_beat || "")}
          ${this._textarea("必须发生", "scene-detail-must", scene.must_happen || "")}
          ${this._textarea("禁止发生", "scene-detail-must-not", scene.must_not_happen || "")}
          ${this._input("POV", "scene-detail-pov", scene.pov_character_id || "")}
        </div>
        <section class="scene-detail-summary">
          <div><strong>章节映射</strong><span>${esc(item.chapter_range || "未关联章节")}</span></div>
          <div><strong>关联资产预览</strong><span>剧情线 / 伏笔 / 揭示 / 地图摘要将在整理预览中展示</span></div>
          <div><strong>来源与注意</strong><span>${esc(this._sourceLabel(scene))} · ${esc(this._sceneStatusLabel(scene))} · ${esc(reviewLabel)}</span></div>
          ${replacementLinks ? `<div><strong>替代结果</strong><span>${replacementLinks}</span></div>` : ""}
          ${attentionLabels.length ? `<div><strong>待处理</strong><span>${esc(attentionLabels.join(" · "))}</span></div>` : ""}
        </section>
        ${this._renderSpanDetails(item)}
        ${this._renderOverlapDetails(item)}
        <div class="scene-detail-actions">
          ${contextAction.key === "edit" ? "" : this._renderContextAction(item)}
          <button class="btn btn-primary" data-action="save-scene-detail" data-id="${esc(scene.id)}">保存</button>
          <button class="btn" data-action="start-merge-scene" data-id="${esc(scene.id)}">合并</button>
          <button class="btn" data-action="start-split-scene" data-id="${esc(scene.id)}">拆分</button>
        </div>
      </div>
    `
  },

  _input(label, id, value) {
    return `
      <label class="scene-detail-field">
        <span>${esc(label)}</span>
        <input class="form-input" id="${esc(id)}" value="${esc(value)}" />
      </label>
    `
  },

  _textarea(label, id, value) {
    return `
      <label class="scene-detail-field scene-detail-field--wide">
        <span>${esc(label)}</span>
        <textarea class="form-textarea" id="${esc(id)}" rows="3">${esc(value)}</textarea>
      </label>
    `
  },

  _select(label, id, value, options) {
    return `
      <label class="scene-detail-field">
        <span>${esc(label)}</span>
        <select class="form-select" id="${esc(id)}">
          ${options.map(([optionValue, optionLabel]) => `
            <option value="${esc(optionValue)}" ${optionValue === value ? "selected" : ""}>${esc(optionLabel)}</option>
          `).join("")}
        </select>
      </label>
    `
  },

  _filteredItems() {
    const items = this._workbench?.items || []
    if (this._filters.status) return items
    return items.filter((item) => !structureAssetDisplay(item.scene || {}).isHistory)
  },

  _selectedSceneId() {
    const embedded = state.currentView === "outline" && state.currentSubView === "scenes"
    const routeId = embedded ? this._routeSceneId() : state.currentSubView
    if (embedded) this._selectedSceneIdValue = routeId
    return routeId || null
  },

  _routeSceneId() {
    if (state.currentView !== "outline" || state.currentSubView !== "scenes") {
      return state.currentSubView || null
    }
    if (typeof window !== "undefined") {
      const queryIndex = window.location.hash.indexOf("?")
      const hashQuery = queryIndex >= 0 ? window.location.hash.slice(queryIndex + 1) : ""
      return new URLSearchParams(hashQuery).get("scene_id")
    }
    return router.getCurrentQuery?.()?.get("scene_id") || null
  },

  _selectedSceneItem() {
    const id = this._selectedSceneId()
    if (!id) return null
    const items = this._filteredItems()
    return items.find((item) => item.scene?.id === id) || null
  },

  _selectSceneInPlace(sceneId) {
    if (!sceneId) return
    const item = this._findSceneItem(sceneId)
    if (!item) return

    this._mobileDetailOpen = true
    if (state.currentView === "outline" && state.currentSubView === "scenes") {
      this._selectedSceneIdValue = sceneId
    } else {
      state.currentSubView = sceneId
    }
    this._pushSceneHistory(sceneId)
    this._syncSelectedSceneUi()
  },

  _pushSceneHistory(sceneId) {
    if (typeof window === "undefined" || !window.history || !state.currentProjectId) return
    const embedded = state.currentView === "outline" && state.currentSubView === "scenes"
    const query = this._sceneQuery()
    query.set("mode", this._viewMode)
    query.set("scene_id", sceneId)
    const hash = embedded
      ? `#workbench/${encodeURIComponent(state.currentProjectId)}/outline/scenes?${query.toString()}`
      : `#workbench/${encodeURIComponent(state.currentProjectId)}/scene/${encodeURIComponent(sceneId)}?mode=${encodeURIComponent(this._viewMode)}`
    if (window.location.hash === hash) return
    window.history.pushState(
      {
        view: embedded ? "outline" : "scene",
        subView: embedded ? "scenes" : sceneId,
        projectId: state.currentProjectId,
      },
      "",
      hash,
    )
  },

  _clearEmbeddedSceneHistory() {
    if (
      state.currentView !== "outline"
      || state.currentSubView !== "scenes"
      || typeof window === "undefined"
      || !window.history
      || !state.currentProjectId
    ) return
    const queryIndex = window.location.hash.indexOf("?")
    const query = new URLSearchParams(
      queryIndex >= 0 ? window.location.hash.slice(queryIndex + 1) : "",
    )
    query.delete("scene_id")
    const base = `#workbench/${encodeURIComponent(state.currentProjectId)}/outline/scenes`
    const hash = query.toString() ? `${base}?${query.toString()}` : base
    this._selectedSceneIdValue = null
    window.history.replaceState(
      { view: "outline", subView: "scenes", projectId: state.currentProjectId },
      "",
      hash,
    )
  },

  _syncSelectedSceneUi() {
    if (typeof document === "undefined") return
    const selectedId = this._selectedSceneId()
    document.querySelectorAll(".scene-workbench-row[data-id]").forEach((row) => {
      row.classList.toggle("is-selected", row.getAttribute("data-id") === selectedId)
    })

    const item = this._selectedSceneItem()
    const narrow = typeof window !== "undefined" && window.innerWidth < 720
    const detail = this._renderDetail(item, narrow)
    const detailEl = document.querySelector(".scene-workbench__detail")
    if (detailEl) detailEl.innerHTML = detail

    const drawer = document.querySelector(".scene-workbench-drawer")
    if (narrow && this._mobileDetailOpen && item) {
      if (drawer) {
        drawer.innerHTML = detail
      } else {
        document.querySelector(".scene-workbench")?.insertAdjacentHTML(
          "beforeend",
          `<div class="scene-workbench-drawer">${detail}</div>`,
        )
      }
    } else if (drawer) {
      drawer.remove()
    }
  },

  async _refreshWorkbenchInPlace({ preserveScroll = true } = {}) {
    const currentOrganize = typeof document !== "undefined"
      ? document.querySelector(".scene-workbench__organize")
      : null
    const scrollTop = preserveScroll && currentOrganize ? currentOrganize.scrollTop : 0

    await this._loadWorkbench()

    const currentQueue = typeof document !== "undefined"
      ? document.querySelector(".scene-fusion-queue")
      : null
    const queueHtml = this._renderFusionSuggestionQueue()
    if (currentQueue && queueHtml) currentQueue.outerHTML = queueHtml
    else if (currentQueue) currentQueue.remove()
    else if (queueHtml) {
      document.querySelector(".scene-workbench")?.insertAdjacentHTML(
        "beforebegin",
        queueHtml,
      )
    }

    const root = typeof document !== "undefined"
      ? document.querySelector(".scene-workbench")
      : null
    if (!root) {
      await router.refresh()
      return
    }

    const narrow = typeof window !== "undefined" && window.innerWidth < 720
    const item = this._selectedSceneItem()
    const detail = this._renderDetail(item, narrow)
    const showNarrowDetail = narrow && this._mobileDetailOpen && item
    root.className = `scene-workbench ${narrow ? "is-narrow" : ""}`
    root.innerHTML = `
      <section class="scene-workbench__organize">
        ${this._renderManagementFilters()}
        ${this._renderProgressFilters()}
        ${this._renderHealthFilters()}
        ${this._renderFusionToolbar()}
        ${this._renderSceneList()}
        ${this._renderPagination()}
      </section>
      ${narrow ? "" : renderWorkspaceRail({
        key: workspaceRailKey("scene-workbench", state.currentProjectId, "detail"),
        title: "Scene 详情",
        className: "scene-detail-rail workspace-rail--right",
        defaultOpen: true,
        content: `<aside class="scene-workbench__detail">${detail}</aside>`,
      })}
      ${showNarrowDetail ? `<div class="scene-workbench-drawer">${detail}</div>` : ""}
    `
    const nextOrganize = root.querySelector(".scene-workbench__organize")
    if (preserveScroll && nextOrganize) nextOrganize.scrollTop = scrollTop
    this._bindEvents()
  },

  _findScene(sceneId) {
    return (this._workbench?.items || []).find((item) => item.scene?.id === sceneId)?.scene || null
  },

  _findSceneItem(sceneId) {
    return (this._workbench?.items || []).find((item) => item.scene?.id === sceneId) || null
  },

  _sceneReviewState(item) {
    const meta = item?.scene?.structure_meta || {}
    const health = item?.health || []
    const reviewedAt = meta.reviewed_at || null
    return {
      reviewed: Boolean(reviewedAt),
      reviewedAt,
      needsReview: Boolean(meta.needs_review) || health.includes("unreviewed"),
    }
  },

  _formatReviewTime(value) {
    if (!value) return ""
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return String(value)
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
  },

  _visibleFusionSceneIds() {
    return this._filteredItems()
      .map((item) => item.scene?.id)
      .filter(Boolean)
  },

  _selectedSceneItems() {
    return Array.from(this._selectedFusionSceneIds)
      .map((sceneId) => this._findSceneItem(sceneId))
      .filter(Boolean)
  },

  _toggleFusionSelection(sceneId, selected) {
    if (!sceneId) return
    if (selected) this._selectedFusionSceneIds.add(sceneId)
    else this._selectedFusionSceneIds.delete(sceneId)
    this._syncFusionSelectionUi()
  },

  _selectVisibleFusionScenes() {
    for (const item of this._filteredItems()) {
      const id = item.scene?.id
      if (id) this._selectedFusionSceneIds.add(id)
    }
    this._syncFusionSelectionUi()
  },

  _toggleVisibleFusionSelection() {
    const visibleSceneIds = this._visibleFusionSceneIds()
    const allVisibleSelected = visibleSceneIds.length > 0
      && visibleSceneIds.every((id) => this._selectedFusionSceneIds.has(id))
    if (allVisibleSelected) {
      visibleSceneIds.forEach((id) => this._selectedFusionSceneIds.delete(id))
    } else {
      visibleSceneIds.forEach((id) => this._selectedFusionSceneIds.add(id))
    }
    this._syncFusionSelectionUi()
  },

  _clearFusionSelection() {
    this._selectedFusionSceneIds = new Set()
    this._syncFusionSelectionUi()
  },

  _syncFusionSelectionUi() {
    if (typeof document === "undefined") return
    const toolbar = document.querySelector(".scene-fusion-toolbar")
    if (toolbar) toolbar.outerHTML = this._renderFusionToolbar()
    document.querySelectorAll('input[data-action="toggle-fusion-selection"]').forEach((input) => {
      const id = input.getAttribute("data-id")
      input.checked = this._selectedFusionSceneIds.has(id)
    })
  },

  async _saveSceneDetails(sceneId) {
    const value = (id) => document.getElementById(id)?.value?.trim() || null
    try {
      await api.outline.updateScene(sceneId, state.currentProjectId, {
        title: value("scene-detail-title"),
        narrative_tag: value("scene-detail-tag") || "draft",
        status: value("scene-detail-status") || "draft",
        source: value("scene-detail-source") || "manual",
        goal: value("scene-detail-goal"),
        core_conflict: value("scene-detail-conflict"),
        emotional_beat: value("scene-detail-emotion"),
        must_happen: value("scene-detail-must"),
        must_not_happen: value("scene-detail-must-not"),
        pov_character_id: value("scene-detail-pov"),
      })
      toast("Scene 已保存", "success")
      await this._refreshWorkbenchInPlace()
    } catch (err) {
      toast(err.message || "保存 Scene 失败", "error")
    }
  },

  async _markSceneReviewed(sceneId) {
    const item = this._findSceneItem(sceneId)
    const scene = item?.scene
    if (!scene) {
      toast("未找到目标 Scene", "error")
      return
    }
    await api.outline.reviewSceneWorkbench(state.currentProjectId, {
      scene_ids: [sceneId],
      decision: "review",
    })
    await this._refreshWorkbenchInPlace()
    const remaining = this._findSceneItem(sceneId)?.health?.length || 0
    const doneLabel = structureAssetDisplay(scene).displayState === "active"
      ? "Scene 已标记为已检查"
      : "Scene 已采用"
    toast(
      remaining ? `${doneLabel}，仍有 ${remaining} 项待处理` : doneLabel,
      remaining ? "warning" : "success",
    )
  },

  async _reviewSelectedScenes() {
    const scenes = this._selectedSceneItems().map((item) => item.scene).filter(Boolean)
    if (!scenes.length) {
      toast("请先选择要处理的 Scene", "warning")
      return
    }

    await api.outline.reviewSceneWorkbench(state.currentProjectId, {
      scene_ids: scenes.map((scene) => scene.id),
      decision: "review",
    })
    this._selectedFusionSceneIds = new Set()
    toast(`已处理 ${scenes.length} 个 Scene`, "success")
    await this._refreshWorkbenchInPlace()
  },

  async _toggleSelectedSceneReview() {
    const selectedItems = this._selectedSceneItems()
    if (!selectedItems.length) {
      toast("请先选择要处理的 Scene", "warning")
      return
    }
    const allReviewed = selectedItems.every((item) => this._sceneReviewState(item).reviewed)
    if (allReviewed) {
      await this._unreviewSelectedScenes(selectedItems)
      return
    }
    await this._reviewSelectedScenes()
  },

  async _handleSelectedContextActions() {
    const items = this._selectedSceneItems()
    if (!items.length) {
      toast("请先选择要处理的 Scene", "warning")
      return
    }
    const grouped = new Map()
    for (const item of items) {
      const key = this._contextAction(item).key
      grouped.set(key, [...(grouped.get(key) || []), item])
    }
    if (grouped.size === 1 && grouped.has("review")) {
      return this._reviewSelectedScenes()
    }
    if (grouped.size === 1 && grouped.has("source_mapping")) {
      return this._confirmSelectedSourceMappings(grouped.get("source_mapping"))
    }
    const labels = {
      review: "采用 / 检查",
      suggestion: "跨章融合建议",
      source_mapping: "正文定位",
      organize: "映射整理",
      assign: "章节关联",
      missing_setup: "设定补全",
      edit: "普通编辑",
    }
    const html = Array.from(grouped.entries()).map(([key, values]) => `
      <div class="scene-batch-group">
        <strong>${esc(labels[key] || key)}</strong>
        <span>${esc(values.length)} 个 Scene</span>
      </div>
    `).join("")
    const buttons = [{ text: "取消", class: "", handler: () => closeModal() }]
    if (grouped.has("review")) buttons.push({
      text: "先处理采用项",
      class: "btn-primary",
      handler: async () => {
        this._selectedFusionSceneIds = new Set(
          grouped.get("review").map((item) => item.scene.id),
        )
        closeModal()
        await this._reviewSelectedScenes()
      },
    })
    if (grouped.has("source_mapping")) buttons.push({
      text: "先确认定位项",
      class: "btn-primary",
      handler: () => {
        closeModal()
        this._confirmSelectedSourceMappings(grouped.get("source_mapping"))
      },
    })
    showModalHtml("批量处理", html, buttons)
  },

  _confirmSelectedSourceMappings(items) {
    const requests = items.map((item) => {
      const action = this._contextAction(item)
      return {
        scene_id: item.scene.id,
        expected_fingerprint: action.fingerprint,
      }
    }).filter((item) => item.expected_fingerprint)
    if (!requests.length) return
    showModalHtml("批量确认章节级定位", `
      <p>将确认 ${esc(requests.length)} 个 Scene 只保留章节级定位。</p>
      <p class="writing-form-hint">这不会提升其证据精度。</p>
    `, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认定位",
        class: "btn-primary",
        handler: async () => {
          await api.outline.reviewSceneSourceMappings(state.currentProjectId, {
            items: requests,
            decision: "accept_chapter_only",
            confirmed: true,
          })
          closeModal()
          this._selectedFusionSceneIds = new Set()
          toast(`已确认 ${requests.length} 个 Scene 的章节定位`, "success")
          await this._refreshWorkbenchInPlace()
          return true
        },
      },
    ])
  },

  async _unreviewSelectedScenes(selectedItems = this._selectedSceneItems()) {
    const scenes = selectedItems.map((item) => item.scene).filter(Boolean)
    if (!scenes.length) {
      toast("未找到选中的 Scene", "error")
      return
    }

    await api.outline.reviewSceneWorkbench(state.currentProjectId, {
      scene_ids: scenes.map((scene) => scene.id),
      decision: "reopen",
    })
    this._selectedFusionSceneIds = new Set()
    toast(`已将 ${scenes.length} 个 Scene 标记为需要人工检查`, "success")
    await this._refreshWorkbenchInPlace()
  },

  async _markSceneUnreviewed(sceneId) {
    const item = this._findSceneItem(sceneId)
    const scene = item?.scene
    if (!scene) {
      toast("未找到目标 Scene", "error")
      return
    }
    await api.outline.reviewSceneWorkbench(state.currentProjectId, {
      scene_ids: [sceneId],
      decision: "reopen",
    })
    toast("Scene 已标记为需要人工检查", "success")
    await this._refreshWorkbenchInPlace()
  },

  async _moveSceneToHistory(sceneId) {
    const item = this._findSceneItem(sceneId)
    const scene = item?.scene
    if (!scene || structureAssetDisplay(scene).isHistory) {
      toast("未找到可移入历史的 Scene", "error")
      return false
    }
    const confirmed = await confirmAsync(
      `确认将“${scene.title || "未命名 Scene"}”移入历史？Scene 正文和追踪信息会保留，可通过“状态 → 历史”查看。`,
      "确认移入历史",
    )
    if (!confirmed) return false

    try {
      await api.outline.deleteScene(sceneId, state.currentProjectId)
    } catch (err) {
      toast(`移入历史失败：${err.message || "未知错误"}`, "error")
      return false
    }

    this._selectedFusionSceneIds.delete(sceneId)
    if (this._selectedSceneId() === sceneId) this._clearEmbeddedSceneHistory()
    toast("Scene 已移入历史", "success")
    await this._refreshWorkbenchInPlace()
    return true
  },

  async _handleSceneHealth(sceneId, healthKey) {
    const item = this._findSceneItem(sceneId)
    if (!item) return
    const action = this._contextAction(item, healthKey)
    await this._runContextAction(item, action)
  },

  async _runContextAction(item, action = this._contextAction(item)) {
    const sceneId = item?.scene?.id
    if (!sceneId) return
    if (action.key === "review") return this._markSceneReviewed(sceneId)
    if (action.key === "suggestion") {
      return this._openFusionSuggestion(action.suggestionId)
    }
    if (action.key === "source_mapping") {
      return this._confirmSourceMapping(sceneId, action.fingerprint)
    }
    if (action.key === "organize") return this._showOrganizeMapping(sceneId)
    if (action.key === "assign") return this._showAssignChapters(sceneId)
    if (action.key === "missing_setup") return this._focusMissingSetup(sceneId)
    this._selectSceneInPlace(sceneId)
  },

  _confirmSourceMapping(sceneId, fingerprint) {
    if (!fingerprint) {
      toast("正文定位已变化，请刷新后重试", "warning")
      return
    }
    const html = `
      <div class="scene-source-mapping-review">
        <p>确认后，该 Scene 仍只保留章节级定位。</p>
        <p class="writing-form-hint">这不会伪造正文 offset，也不会让 RAG 或上下文系统把它当作精确证据。</p>
      </div>
    `
    showModalHtml("确认章节级正文定位", html, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认仅按章节关联",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.reviewSceneSourceMappings(state.currentProjectId, {
              items: [{ scene_id: sceneId, expected_fingerprint: fingerprint }],
              decision: "accept_chapter_only",
              confirmed: true,
            })
            closeModal()
            toast("已确认章节级正文定位", "success")
            await this._refreshWorkbenchInPlace()
            return true
          } catch (err) {
            toast(err.message || "正文定位确认失败", "error")
            return false
          }
        },
      },
    ])
  },

  _showOrganizeMapping(sceneId) {
    showModalHtml("整理 Scene 映射", "<p>选择要处理的映射动作。</p>", [
      { text: "移动章节", class: "", handler: () => {
        closeModal()
        this._showAssignChapters(sceneId)
      } },
      { text: "合并", class: "", handler: () => {
        closeModal()
        this._startMerge(sceneId)
      } },
      { text: "拆分", class: "btn-primary", handler: () => {
        closeModal()
        this._startSplit(sceneId)
      } },
    ])
  },

  _showAssignChapters(sceneId) {
    const scene = this._findScene(sceneId)
    if (!scene) return
    const current = new Set((scene.chapter_ids || []).map(String))
    const available = [...new Set([
      ...current,
      ...(this._workbench?.unassigned_chapters || []).map(String),
    ])].sort((a, b) => Number(a) - Number(b))
    if (!available.length) {
      toast("当前没有可整理的章节", "info")
      return
    }
    const html = `
      <p class="writing-form-hint">取消勾选可将章节从当前 Scene 移出；勾选未关联章节可移入。</p>
      ${available.map((chapter) => `
      <label class="selection-checkbox">
        <input type="checkbox" name="scene-assign-chapter" value="${esc(chapter)}" ${current.has(String(chapter)) ? "checked" : ""} />
        <span>第 ${esc(chapter)} 章</span>
      </label>
      `).join("")}
    `
    showModalHtml("移动 / 关联章节", html, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "保存章节映射",
        class: "btn-primary",
        handler: async () => {
          const selected = Array.from(
            document.querySelectorAll('input[name="scene-assign-chapter"]:checked'),
          ).map((input) => String(input.value))
          const chapterIds = [...new Set(selected)].sort((a, b) => Number(a) - Number(b))
          await api.outline.updateSceneWorkbenchMapping(
            state.currentProjectId,
            sceneId,
            { chapter_ids: chapterIds },
          )
          closeModal()
          toast("章节映射已更新", "success")
          await this._refreshWorkbenchInPlace()
          return true
        },
      },
    ])
  },

  _focusMissingSetup(sceneId) {
    const scene = this._findScene(sceneId)
    if (!scene) return
    this._selectSceneInPlace(sceneId)
    const fields = [
      ["goal", "scene-detail-goal"],
      ["core_conflict", "scene-detail-conflict"],
      ["must_happen", "scene-detail-must"],
      ["must_not_happen", "scene-detail-must-not"],
    ]
    const target = fields.find(([field]) => !scene[field])
    if (target) document.getElementById(target[1])?.focus()
  },

  async _assignChapter(chapterIndex) {
    const scenes = this._filteredItems().map((item) => item.scene).filter(Boolean)
    if (!scenes.length) {
      toast("当前没有可关联的 Scene", "warning")
      return
    }
    const html = scenes.map((scene, index) => `
      <label class="scene-picker-card">
        <input type="radio" name="assign-target-scene" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""} />
        <strong>${esc(scene.title || "未命名 Scene")}</strong>
        <span>${esc(this._sceneChapterLabel(scene))}</span>
      </label>
    `).join("")
    showModalHtml(`分配第 ${chapterIndex} 章`, html, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认分配",
        class: "btn-primary",
        handler: async () => {
          const sceneId = document.querySelector('input[name="assign-target-scene"]:checked')?.value
          const scene = this._findScene(sceneId)
          if (!scene) return false
          const chapterIds = [...new Set([...(scene.chapter_ids || []), String(chapterIndex)])]
            .sort((a, b) => Number(a) - Number(b))
          await api.outline.updateSceneWorkbenchMapping(
            state.currentProjectId,
            sceneId,
            { chapter_ids: chapterIds },
          )
          closeModal()
          toast("章节已分配", "success")
          await this._refreshWorkbenchInPlace()
          return true
        },
      },
    ])
  },

  async _startMerge(targetSceneId) {
    this._destroyMergeReferencePicker()
    const ownerProjectId = state.currentProjectId
    const targetScene = this._findScene(targetSceneId)
    const body = `
      <p>选择要合并到<strong>「${esc(targetScene?.title || "当前 Scene")}」</strong>中的另一个 Scene。</p>
      <div id="scene-merge-reference-picker"></div>
      <p class="form-help">可按标题、目标或冲突搜索；历史 Scene 和当前 Scene 不会出现在结果中。</p>
    `
    showModalHtml("选择要合并的 Scene", body, [
      { text: "取消", class: "", handler: () => {
        this._destroyMergeReferencePicker()
        closeModal()
      } },
      {
        text: "预览合并影响",
        class: "btn-primary",
        handler: async () => {
          if (!ownerProjectId || state.currentProjectId !== ownerProjectId) {
            this._destroyMergeReferencePicker()
            closeModal()
            toast("项目已切换，请在当前项目重新选择 Scene", "warning")
            return false
          }
          const sourceId = this._mergeReferencePicker?.getRefs()?.[0]?.id
          if (!sourceId) {
            toast("请选择要合并的 Scene", "warning")
            return false
          }
          this._destroyMergeReferencePicker()
          closeModal()
          await this._previewAndMerge(targetSceneId, [sourceId], ownerProjectId)
          return false
        },
      },
    ], { size: "large" })
    const root = document.getElementById("scene-merge-reference-picker")
    if (!root) return
    this._mergeReferencePicker = createReferencePicker({
      root,
      projectId: ownerProjectId,
      sources: [{
        kind: "scene",
        label: "Scene",
        search: async (query, { projectId, limit }) => {
          if (state.currentProjectId !== ownerProjectId || projectId !== ownerProjectId) return []
          const data = await api.outline.getSceneWorkbench(projectId, null, {
            q: query || undefined,
            view_mode: "normal",
            skip: 0,
            limit,
          })
          return (data?.items || [])
            .map((entry) => entry.scene || entry)
            .filter((scene) => scene.id !== targetSceneId && scene.status !== "deprecated")
            .map((scene) => ({
              id: scene.id,
              label: scene.title || "未命名 Scene",
              description: [this._sceneChapterLabel(scene), scene.goal || scene.core_conflict].filter(Boolean).join(" · "),
              status: this._statusLabel(scene.status),
            }))
        },
      }],
      placeholder: "搜索 Scene 标题、目标或冲突",
    })
  },

  _destroyMergeReferencePicker() {
    this._mergeReferencePicker?.destroy?.()
    this._mergeReferencePicker = null
  },

  async _previewAndMerge(targetSceneId, sourceSceneIds, ownerProjectId = state.currentProjectId) {
    const requestGeneration = ++this._mergePreviewRequestGeneration
    const request = {
      target_scene_id: targetSceneId,
      source_scene_ids: sourceSceneIds,
    }
    const preview = await api.outline.previewSceneMerge(ownerProjectId, request)
    if (
      requestGeneration !== this._mergePreviewRequestGeneration
      || state.currentProjectId !== ownerProjectId
    ) return false
    showModalHtml("合并 Scene 影响预览", this._renderPreview(preview), [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认合并",
        class: "btn-primary",
        handler: async () => {
          if (
            requestGeneration !== this._mergePreviewRequestGeneration
            || state.currentProjectId !== ownerProjectId
          ) {
            closeModal()
            toast("项目已切换，未执行 Scene 合并", "warning")
            return false
          }
          try {
            await api.outline.mergeScenes(ownerProjectId, {
              ...request,
              confirmed: true,
            })
            toast("Scene 已合并", "success")
            closeModal()
            await router.refresh()
            return true
          } catch (err) {
            toast(`Scene 合并失败：${err.message || "未知错误"}`, "error")
            return false
          }
        },
      },
    ])
  },

  async _startManualFusion() {
    const sourceSceneIds = Array.from(this._selectedFusionSceneIds)
    if (sourceSceneIds.length < 2) {
      toast("请至少选择 2 个 Scene 再融合", "warning")
      return
    }
    await this._showPrimaryScenePicker(sourceSceneIds)
  },

  async _startSelectedMerge() {
    const sourceSceneIds = Array.from(this._selectedFusionSceneIds)
    if (sourceSceneIds.length < 2) {
      toast("请至少选择 2 个 Scene 再合并", "warning")
      return
    }
    this._showMergeTargetPicker(sourceSceneIds)
  },

  _showMergeTargetPicker(sourceSceneIds) {
    const scenes = sourceSceneIds
      .map((id) => this._findScene(id))
      .filter(Boolean)
    if (scenes.length < 2) {
      toast("请至少选择 2 个 Scene 再合并", "warning")
      return
    }
    const cards = scenes.map((scene, index) => `
      <label class="scene-primary-card scene-picker-card">
        <input type="radio" name="merge-target-scene-id" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""} />
        <strong>${esc(scene.title || "未命名 Scene")}</strong>
        <div class="scene-picker-card__meta">${esc(this._sourceLabel(scene))} · ${esc(this._statusLabel(scene.status))} · ${esc(this._sceneChapterLabel(scene))}</div>
        <p class="scene-picker-card__summary">${esc(scene.goal || scene.core_conflict || "暂无目标")}</p>
      </label>
    `).join("")
    showModalHtml("选择目标 Scene", cards, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "预览机械合并",
        class: "btn-primary",
        handler: async () => {
          const targetSceneId = document.querySelector('input[name="merge-target-scene-id"]:checked')?.value
          if (!targetSceneId) {
            toast("请选择目标 Scene", "warning")
            return
          }
          const sourceIds = sourceSceneIds.filter((id) => id !== targetSceneId)
          closeModal()
          await this._previewAndMerge(targetSceneId, sourceIds)
          return false
        },
      },
    ])
  },

  async _showPrimaryScenePicker(sourceSceneIds, suggestionId = null) {
    const scenes = (await Promise.all(sourceSceneIds.map(async (id) => {
      const visible = this._findScene(id)
      if (visible) return visible
      try {
        return await api.outline.getScene(id, state.currentProjectId)
      } catch {
        return null
      }
    }))).filter(Boolean)
    if (scenes.length < 2) {
      toast("请至少选择 2 个 Scene 再融合", "warning")
      return
    }
    const cards = scenes.map((scene, index) => {
      const meta = scene.structure_meta || {}
      const flags = [
        meta.needs_review ? "需要人工检查" : "",
        meta.phase1a_fallback ? "fallback" : "",
        meta.boundary_status ? `边界:${meta.boundary_status}` : "",
        meta.confidence != null ? `置信度:${meta.confidence}` : "",
      ].filter(Boolean)
      return `
        <label class="scene-primary-card scene-picker-card">
          <input type="radio" name="primary-scene-id" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""} />
          <strong>${esc(scene.title || "未命名 Scene")}</strong>
          <div class="scene-picker-card__meta">${esc(this._sourceLabel(scene))} · ${esc(this._statusLabel(scene.status))} · ${esc(this._sceneChapterLabel(scene))}</div>
          <p class="scene-picker-card__summary">${esc(scene.goal || scene.core_conflict || "暂无目标")}</p>
          ${flags.length ? `<div class="scene-picker-card__flags">${esc(flags.join(" · "))}</div>` : ""}
        </label>
      `
    }).join("")
    showModalHtml("选择主 Scene", cards, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "生成 AI 融合建议",
        class: "btn-primary",
        handler: async () => {
          const primarySceneId = document.querySelector('input[name="primary-scene-id"]:checked')?.value
          if (!primarySceneId) {
            toast("请选择主 Scene", "warning")
            return
          }
          closeModal()
          await this._previewFusionWithPrimary(
            sourceSceneIds,
            primarySceneId,
            suggestionId,
          )
          return false
        },
      },
    ])
  },

  async _previewFusionWithPrimary(sourceSceneIds, primarySceneId, suggestionId = null) {
    const projectId = state.currentProjectId
    if (this._fusionPreviewPending && this._fusionPreviewProjectId === projectId) return
    const requestSeq = this._fusionPreviewRequestSeq + 1
    this._fusionPreviewRequestSeq = requestSeq
    this._fusionPreviewPending = true
    this._fusionPreviewProjectId = projectId
    showModalHtml("AI 融合建议生成中", `
      <div class="loading" role="status">正在读取精确正文证据并生成结构化融合草稿…</div>
    `, [])
    try {
      const preview = await api.outline.previewSceneFusion(projectId, {
        source_scene_ids: sourceSceneIds,
        primary_scene_id: primarySceneId,
      })
      if (requestSeq !== this._fusionPreviewRequestSeq || state.currentProjectId !== projectId) {
        return
      }
      this._showFusionPreview(
        { ...preview, suggestion_id: suggestionId, request_project_id: projectId },
        sourceSceneIds,
      )
    } catch (err) {
      if (requestSeq === this._fusionPreviewRequestSeq && state.currentProjectId === projectId) {
        closeModal()
        toast(err.message || "Scene 融合预览失败", "error")
      }
    } finally {
      if (requestSeq === this._fusionPreviewRequestSeq) {
        this._fusionPreviewPending = false
        this._fusionPreviewProjectId = null
      }
    }
  },

  _showFusionPreview(preview, fallbackSourceIds) {
    const sourceSceneIds = preview?.source_scene_ids?.length
      ? [...preview.source_scene_ids]
      : [...(fallbackSourceIds || [])]
    const normalizedPreview = {
      ...(preview || {}),
      source_scene_ids: sourceSceneIds,
    }
    this._fusionSavePending = false
    this._fusionSaveControls = []
    this._activeDraftReview = normalizedPreview
    showModalHtml("Scene AI 建议预览", this._renderDraftReview(normalizedPreview), [
      {
        text: "关闭",
        class: "btn-ghost",
        handler: () => closeModal(),
      },
      {
        text: "放弃融合结果（标记不采用）",
        class: "btn-ghost",
        handler: () => this._saveFusionResult("discard", sourceSceneIds),
      },
      {
        text: "继续编辑融合结果后再保存",
        class: "btn-secondary",
        handler: () => this._saveFusionResult("edit_then_save", sourceSceneIds),
      },
      {
        text: `废弃 ${sourceSceneIds.length} 个原 Scene 并保存`,
        class: "btn-danger",
        handler: () => {
          this._showFusionDeprecationConfirmation()
          return false
        },
      },
      {
        text: "保留原 Scene + 保存融合 Scene",
        class: "btn-primary",
        handler: () => this._saveFusionResult("keep_originals", sourceSceneIds),
      },
    ], { size: "large" })
    this._bindDraftReviewModal({ sourceSceneIds })
  },

  _renderDraftReview(preview) {
    const fused = preview?.draft_scene || preview?.fused_scene || preview?.preview_scene || {}
    const refs = preview?.field_references || {}
    const semanticStatuses = fused?.structure_meta?.semantic_field_statuses || {}
    const conflicts = new Set((preview?.conflicts || []).map((item) => item.field).filter(Boolean))
    let differenceCount = 0
    const rows = FUSION_DRAFT_REVIEW_FIELDS.map(([field, label]) => {
      const fieldRefs = refs[field] || []
      const primaryRefs = fieldRefs.filter((item) => item.role === "primary")
      const otherRefs = fieldRefs.filter((item) => item.role !== "primary")
      const state = this._draftReviewDifferenceState(
        [fused[field]],
        fieldRefs,
        conflicts.has(field),
        field,
      )
      const semanticStatus = semanticStatuses[field] || ""
      const semanticStatusBadge = semanticStatus === "not_applicable"
        ? '<span class="scene-draft-review-badge">不适用</span>'
        : semanticStatus === "uncertain"
          ? '<span class="scene-draft-review-badge scene-draft-review-badge--warning">待复核</span>'
          : ""
      if (state.different) differenceCount += 1
      return `
        <tr class="scene-draft-review-row" data-difference="${state.different}" data-no-evidence="${state.noEvidence}">
          <th scope="row" class="scene-draft-review-row__label">
            <span>${esc(label)}</span>
            ${state.noEvidence ? '<span class="scene-draft-review-badge">无来源证据</span>' : ""}
            ${conflicts.has(field) ? '<span class="scene-draft-review-badge scene-draft-review-badge--warning">有冲突</span>' : ""}
            ${semanticStatusBadge}
          </th>
          <td data-label="AI 建议">${this._renderFusionDraftEditor(field, label, fused[field])}</td>
          <td data-label="主 Scene 原值">${this._renderDraftReviewReferences(primaryRefs)}</td>
          <td data-label="其他 Scene 原值">${this._renderDraftReviewReferences(otherRefs)}</td>
        </tr>
      `
    }).join("")
    return `
      <div class="scene-fusion-preview">
        ${this._renderDraftReviewMeta(preview, "AI 融合建议")}
        ${this._renderDraftReviewTable(
          ["字段", "AI 建议", "主 Scene 原值", "其他 Scene 原值"],
          rows,
          differenceCount,
          FUSION_DRAFT_REVIEW_FIELDS.length,
        )}
        ${this._renderFusionDeprecationConfirmation(preview)}
      </div>
    `
  },

  _renderFusionDraftEditor(field, label, value) {
    const ids = {
      title: "scene-fusion-title",
      goal: "scene-fusion-goal",
      core_conflict: "scene-fusion-conflict",
      emotional_beat: "scene-fusion-emotion",
      must_happen: "scene-fusion-must",
      must_not_happen: "scene-fusion-must-not",
      narrative_function: "scene-fusion-function",
      narrative_tag: "scene-fusion-narrative-tag",
      pov_character_id: "scene-fusion-pov",
      chapter_ids: "scene-fusion-chapters",
    }
    const id = ids[field]
    const labelHtml = `<label class="sr-only" for="${esc(id)}">${esc(label)} AI 建议</label>`
    if (field === "narrative_tag") {
      const tagValue = value || "draft"
      return `${labelHtml}<select class="form-select" id="${esc(id)}" data-initial-draft-value="${esc(tagValue)}">
        ${TAG_OPTIONS.map(([optionValue, optionLabel]) => `
          <option value="${esc(optionValue)}" ${optionValue === tagValue ? "selected" : ""}>${esc(optionLabel)}</option>
        `).join("")}
      </select>`
    }
    if (field === "chapter_ids") {
      const chapters = Array.isArray(value) ? value.join(", ") : this._formatDraftRefValue(value)
      return `${labelHtml}<input class="form-input" id="${esc(id)}" value="${esc(chapters)}" />`
    }
    if (field === "title" || field === "pov_character_id") {
      return `${labelHtml}<input class="form-input" id="${esc(id)}" value="${esc(value || "")}" />`
    }
    return `${labelHtml}<textarea class="form-textarea" id="${esc(id)}" rows="4">${esc(value || "")}</textarea>`
  },

  _renderDraftReviewTable(headers, rows, differenceCount, totalFields = DRAFT_REVIEW_FIELDS.length) {
    return `
      <section class="scene-draft-review-shell" aria-label="Scene 字段对比">
        <div class="scene-draft-review-toolbar">
          <label class="scene-draft-review-filter">
            <input type="checkbox" data-action="filter-draft-review-differences" />
            <span>仅看差异</span>
          </label>
          <span class="scene-draft-review-count" data-role="draft-review-count" data-difference-count="${differenceCount}">
            有变化 ${differenceCount} / 全部 ${totalFields}
          </span>
        </div>
        <p class="scene-draft-review-filter-note" data-role="draft-review-filter-note" hidden></p>
        <table class="scene-draft-review-grid">
          <thead>
            <tr>${headers.map((header) => `<th scope="col">${esc(header)}</th>`).join("")}</tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </section>
    `
  },

  _renderDraftReviewMeta(preview, operationLabel) {
    const summaries = preview?.source_scene_summaries || []
    const sourceIds = preview?.source_scene_ids || []
    const summaryById = new Map(summaries.map((item) => [String(item.id), item]))
    const sourceHtml = sourceIds.map((id) => {
      const item = summaryById.get(String(id)) || { id, title: id, chapter_range: "未关联章节" }
      const role = String(id) === String(preview?.primary_scene_id) ? "主 Scene" : "来源 Scene"
      return `<span class="scene-draft-review-source"><strong>${esc(role)}</strong> ${esc(item.title || item.id)} · ${esc(item.chapter_range || "未关联章节")}</span>`
    }).join("")
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    const conflicts = (preview?.conflicts || []).map((item) => `<li>${esc(item.message || item.field || "")}</li>`).join("")
    const basis = preview?.draft_scene?.structure_meta?.semantic_basis
      || preview?.fused_scene?.structure_meta?.semantic_basis
      || ""
    return `
      <section class="scene-fusion-preview__meta">
        <div><strong>操作</strong><span>${esc(operationLabel)}</span></div>
        ${sourceHtml ? `<div class="scene-draft-review-sources">${sourceHtml}</div>` : ""}
        ${preview?.reason ? `<p>${esc(preview.reason)}</p>` : ""}
        ${basis && basis !== preview?.reason ? `<p><strong>判断依据</strong> ${esc(basis)}</p>` : ""}
        ${warnings ? `<div class="scene-draft-review-notice"><strong>注意</strong><ul>${warnings}</ul></div>` : ""}
        ${conflicts ? `<div class="scene-draft-review-notice"><strong>字段冲突</strong><ul>${conflicts}</ul></div>` : ""}
      </section>
    `
  },

  _renderDraftReviewReferences(references) {
    if (!references.length) return '<span class="scene-draft-review-empty">无来源证据</span>'
    return references.map((item) => {
      const title = item.title || item.scene_id || "未命名 Scene"
      const value = this._formatDraftRefValue(item.value)
      if (value.length > 120) {
        const excerpt = `${value.slice(0, 80)}…`
        return `
          <details class="scene-draft-ref scene-draft-ref--long">
            <summary><strong>${esc(title)}</strong><span>${esc(excerpt)}</span></summary>
            <p>${esc(value)}</p>
          </details>
        `
      }
      return `<div class="scene-draft-ref"><strong>${esc(title)}</strong><p>${esc(value || "无")}</p></div>`
    }).join("")
  },

  _draftReviewDifferenceState(suggestedValues, references, hasConflict = false, field = "") {
    if (!references.length) return { different: false, noEvidence: true }
    const values = [
      ...suggestedValues,
      ...references.map((item) => item.value),
    ].map((value) => this._normalizeDraftReviewValue(value, field))
    return {
      different: hasConflict || new Set(values).size > 1,
      noEvidence: false,
    }
  },

  _normalizeDraftReviewValue(value, field = "") {
    if (field === "narrative_tag" && !this._formatDraftRefValue(value).trim()) return "draft"
    return this._formatDraftRefValue(value).trim()
  },

  _renderFusionDeprecationConfirmation(preview) {
    const summaries = preview?.source_scene_summaries || []
    const sourceIds = preview?.source_scene_ids || []
    const summaryById = new Map(summaries.map((item) => [String(item.id), item]))
    const sources = sourceIds.map((id) => summaryById.get(String(id)) || { id, title: id })
    return `
      <section class="scene-draft-deprecation-confirm" data-role="fusion-deprecation-confirm" role="alert" hidden>
        <strong>确认废弃 ${sources.length} 个原 Scene？</strong>
        <p>融合 Scene 保存后，下列原 Scene 将进入历史；当前表格中的编辑内容会保留。</p>
        <ul>${sources.map((item) => `<li>${esc(item.title || item.id)}</li>`).join("")}</ul>
        <div class="scene-draft-deprecation-actions">
          <button class="btn btn-ghost" type="button" data-action="cancel-fusion-deprecation">返回预览</button>
          <button class="btn btn-danger" type="button" data-action="confirm-fusion-deprecation">确认废弃 ${sources.length} 个原 Scene 并保存</button>
        </div>
      </section>
    `
  },

  _showFusionDeprecationConfirmation() {
    const section = document.querySelector('[data-role="fusion-deprecation-confirm"]')
    if (!section) return
    section.hidden = false
    section.scrollIntoView?.({ block: "nearest" })
    section.querySelector('[data-action="confirm-fusion-deprecation"]')?.focus()
  },

  _bindDraftReviewModal({ sourceSceneIds = [] } = {}) {
    const body = document.getElementById("modal-body")
    if (!body) return
    body.querySelectorAll("select[data-initial-draft-value]").forEach((select) => {
      select.value = select.dataset.initialDraftValue || ""
    })
    const filter = body.querySelector('[data-action="filter-draft-review-differences"]')
    const rows = Array.from(body.querySelectorAll(".scene-draft-review-row"))
    const note = body.querySelector('[data-role="draft-review-filter-note"]')
    const applyFilter = () => {
      const differenceOnly = Boolean(filter?.checked)
      let hiddenCount = 0
      rows.forEach((row) => {
        const keepVisible = row.dataset.difference === "true" || row.dataset.noEvidence === "true"
        row.hidden = differenceOnly && !keepVisible
        if (row.hidden) hiddenCount += 1
      })
      if (note) {
        note.hidden = !differenceOnly || hiddenCount === 0
        note.textContent = hiddenCount
          ? `已隐藏 ${hiddenCount} 个无差异字段；这些字段仍会随草稿保存。`
          : ""
      }
    }
    filter?.addEventListener("change", applyFilter)
    applyFilter()

    body.querySelector('[data-action="cancel-fusion-deprecation"]')?.addEventListener("click", () => {
      const section = body.querySelector('[data-role="fusion-deprecation-confirm"]')
      if (section) section.hidden = true
    })
    body.querySelector('[data-action="confirm-fusion-deprecation"]')?.addEventListener("click", async () => {
      await this._saveFusionResult("deprecate_originals", sourceSceneIds)
    })
  },

  _setFusionSavePending(pending) {
    this._fusionSavePending = pending
    if (pending) {
      this._fusionSaveControls = Array.from(document.querySelectorAll(
        "#modal-footer button, #modal-body [data-action='confirm-fusion-deprecation']",
      ))
    }
    this._fusionSaveControls.forEach((button) => {
      button.disabled = pending
      button.setAttribute("aria-disabled", String(pending))
    })
    if (!pending) this._fusionSaveControls = []
  },

  _formatDraftRefValue(value) {
    if (Array.isArray(value)) return value.map((item) => typeof item === "object" ? JSON.stringify(item) : String(item)).join("；")
    if (value && typeof value === "object") return JSON.stringify(value)
    return value == null ? "" : String(value)
  },

  _sceneChapterLabel(scene) {
    const chapterIds = scene?.chapter_ids || []
    if (!chapterIds.length) return "未关联章节"
    return chapterIds.map((id) => `第 ${String(id)} 章`).join(" / ")
  },

  _readFusionDraftFields() {
    const draft = this._activeDraftReview?.draft_scene || this._activeDraftReview?.fused_scene || {}
    const semanticMetaKeys = [
      "semantic_contract_version",
      "semantic_origin",
      "semantic_field_statuses",
      "semantic_basis",
      "semantic_uncertain_fields",
      "semantic_confidence",
      "semantic_preview_values",
      "narrative_function",
      "core_conflict_status",
    ]
    const inheritedSemanticMeta = Object.fromEntries(
      semanticMetaKeys
        .filter((key) => Object.prototype.hasOwnProperty.call(draft.structure_meta || {}, key))
        .map((key) => [key, draft.structure_meta[key]]),
    )
    const value = (id, fallback = null) => {
      const el = document.getElementById(id)
      if (!el) return fallback
      return el.value?.trim() || null
    }
    const chaptersText = value("scene-fusion-chapters", (draft.chapter_ids || []).join(", ")) || ""
    const chapters = chaptersText
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
    return {
      title: value("scene-fusion-title", draft.title || null),
      goal: value("scene-fusion-goal", draft.goal || null),
      core_conflict: value("scene-fusion-conflict", draft.core_conflict || null),
      emotional_beat: value("scene-fusion-emotion", draft.emotional_beat || null),
      must_happen: value("scene-fusion-must", draft.must_happen || null),
      must_not_happen: value("scene-fusion-must-not", draft.must_not_happen || null),
      narrative_function: value("scene-fusion-function", draft.narrative_function || null),
      narrative_tag: value("scene-fusion-narrative-tag", draft.narrative_tag || "draft") || "draft",
      pov_character_id: value("scene-fusion-pov", draft.pov_character_id || null),
      chapter_ids: chapters,
      structure_meta: {
        ...inheritedSemanticMeta,
        draft_review_mode: this._activeDraftReview?.mode || "fusion",
        primary_scene_id: this._activeDraftReview?.primary_scene_id || null,
        confidence: this._activeDraftReview?.confidence ?? null,
        draft_review_warnings: this._activeDraftReview?.warnings || [],
        draft_review_conflicts: this._activeDraftReview?.conflicts || [],
      },
    }
  },

  async _saveFusionResult(mode, sourceSceneIds) {
    if (this._fusionSavePending) return false
    if (
      this._activeDraftReview?.request_project_id
      && this._activeDraftReview.request_project_id !== state.currentProjectId
    ) {
      closeModal()
      toast("项目已切换，请在当前项目重新生成融合建议", "warning")
      return false
    }
    this._setFusionSavePending(true)
    const payload = {
      source_scene_ids: sourceSceneIds,
      primary_scene_id: this._activeDraftReview?.primary_scene_id || null,
      mode,
    }
    if (this._activeDraftReview?.suggestion_id) {
      payload.suggestion_id = this._activeDraftReview.suggestion_id
    }
    if (mode !== "discard") {
      payload.fused_scene = this._readFusionDraftFields()
    }
    try {
      const result = await api.outline.saveSceneFusion(state.currentProjectId, payload)
      this._selectedFusionSceneIds = new Set()
      toast(result?.status === "discarded" ? "融合结果已放弃" : "融合 Scene 已保存", "success")
      closeModal()
      await this._refreshWorkbenchInPlace()
      return true
    } catch (err) {
      toast(err.message || "Scene 融合保存失败", "error")
      return false
    } finally {
      this._setFusionSavePending(false)
    }
  },

  async _startSplit(sourceSceneId) {
    const scene = this._findScene(sourceSceneId)
    if (!scene) {
      toast("Scene 不存在或已变化，请刷新后重试", "warning")
      return false
    }
    const chapterIndices = [...new Set(
      (scene.chapter_ids || [])
        .map((chapterId) => Number(chapterId))
        .filter((chapterIndex) => Number.isInteger(chapterIndex) && chapterIndex > 0),
    )].sort((left, right) => left - right)
    if (chapterIndices.length < 2) {
      toast("该 Scene 至少需要关联两个章节才能按章节拆分", "info")
      return false
    }

    const partitionFor = (splitChapterIndex) => {
      const splitPosition = chapterIndices.indexOf(splitChapterIndex)
      if (splitPosition <= 0) return null
      return {
        retained: chapterIndices.slice(0, splitPosition),
        created: chapterIndices.slice(splitPosition),
      }
    }
    const chapterLabel = (indices) => indices.map((index) => `第 ${index} 章`).join("、")
    const defaultSplitChapter = chapterIndices[1]
    const options = chapterIndices.slice(1).map((chapterIndex) => {
      const partition = partitionFor(chapterIndex)
      return `
        <option value="${chapterIndex}" ${chapterIndex === defaultSplitChapter ? "selected" : ""}>
          从第 ${chapterIndex} 章起创建新 Scene（原 Scene 保留 ${esc(chapterLabel(partition.retained))}）
        </option>
      `
    }).join("")
    const defaultPartition = partitionFor(defaultSplitChapter)
    const html = `
      <div class="scene-split-setup">
        <p>当前 Scene：<strong>${esc(scene.title || "未命名 Scene")}</strong></p>
        <p class="writing-form-hint">当前关联章节：${esc(chapterLabel(chapterIndices))}</p>
        <label class="writing-form-field" for="scene-split-chapter-index">
          <span>新 Scene 的起始章节</span>
          <select id="scene-split-chapter-index" autofocus>${options}</select>
        </label>
        <div id="scene-split-partition" class="scene-split-impact-summary" aria-live="polite">
          <p><strong>保留在原 Scene：</strong>${esc(chapterLabel(defaultPartition.retained))}</p>
          <p><strong>进入新 Scene：</strong>${esc(chapterLabel(defaultPartition.created))}</p>
        </div>
        <p class="writing-form-hint">两侧章节互不重叠，并完整覆盖当前 Scene；下一步可编辑 AI 生成的两张 Scene 卡。</p>
        <p id="scene-split-setup-error" class="form-error" role="alert"></p>
      </div>
    `
    showModalHtml("拆分 Scene", html, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "生成拆分预览",
        class: "btn-primary",
        handler: async () => {
          const select = document.getElementById("scene-split-chapter-index")
          const error = document.getElementById("scene-split-setup-error")
          const splitChapterIndex = Number(select?.value)
          const partition = partitionFor(splitChapterIndex)
          if (!partition?.retained.length || !partition?.created.length) {
            if (error) error.textContent = "请选择能让原 Scene 和新 Scene 都保留章节的拆分边界。"
            return false
          }
          if (error) error.textContent = ""
          try {
            await this._previewAndSplit(sourceSceneId, splitChapterIndex)
            return true
          } catch (err) {
            if (error) error.textContent = err.message || "拆分预览生成失败，请稍后重试。"
            return false
          }
        },
      },
    ])

    const select = document.getElementById("scene-split-chapter-index")
    const partitionElement = document.getElementById("scene-split-partition")
    select?.addEventListener("change", () => {
      const partition = partitionFor(Number(select.value))
      if (!partitionElement || !partition) return
      partitionElement.innerHTML = `
        <p><strong>保留在原 Scene：</strong>${esc(chapterLabel(partition.retained))}</p>
        <p><strong>进入新 Scene：</strong>${esc(chapterLabel(partition.created))}</p>
      `
    })
    return true
  },

  async _previewAndSplit(sourceSceneId, splitChapterIndex) {
    const request = {
      source_scene_id: sourceSceneId,
      split_chapter_index: splitChapterIndex,
    }
    const preview = await api.outline.previewSceneSplit(state.currentProjectId, request)
    showModalHtml("Scene 拆分预览", this._renderSplitDraftReview(preview), [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认拆分",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.splitScene(state.currentProjectId, {
              ...request,
              draft_scenes: this._readSplitDraftScenes(),
              confirmed: true,
            })
            toast("Scene 已拆分", "success")
            closeModal()
            await router.refresh()
            return true
          } catch (err) {
            toast(`Scene 拆分失败：${err.message || "未知错误"}`, "error")
            return false
          }
        },
      },
    ], { size: "large" })
    this._bindDraftReviewModal()
  },

  _renderSplitDraftReview(preview) {
    const drafts = preview?.draft_scenes || []
    const sourceRefs = preview?.field_references || {}
    let differenceCount = 0
    const rows = DRAFT_REVIEW_FIELDS.map(([field, label]) => {
      const fieldRefs = sourceRefs[field] || []
      const state = this._draftReviewDifferenceState(
        [drafts[0]?.[field], drafts[1]?.[field]],
        fieldRefs,
        false,
        field,
      )
      if (state.different) differenceCount += 1
      return `
        <tr class="scene-draft-review-row" data-difference="${state.different}" data-no-evidence="${state.noEvidence}">
          <th scope="row" class="scene-draft-review-row__label">
            <span>${esc(label)}</span>
            ${state.noEvidence ? '<span class="scene-draft-review-badge">无来源证据</span>' : ""}
          </th>
          <td data-label="原 Scene">${this._renderDraftReviewReferences(fieldRefs)}</td>
          <td data-label="建议 A">${this._renderSplitDraftEditor(0, field, label, drafts[0]?.[field])}</td>
          <td data-label="建议 B">${this._renderSplitDraftEditor(1, field, label, drafts[1]?.[field])}</td>
        </tr>
      `
    }).join("")
    return `
      <div class="scene-fusion-preview">
        ${this._renderDraftReviewMeta(preview, "拆分草稿")}
        ${this._renderDraftReviewTable(
          ["字段", "原 Scene", "建议 A", "建议 B"],
          rows,
          differenceCount,
        )}
        ${this._renderSplitImpactSummary(preview)}
      </div>
    `
  },

  _renderSplitDraftEditor(draftIndex, field, label, value) {
    const id = `scene-split-${draftIndex}-${field}`
    const suffix = draftIndex === 0 ? "建议 A" : "建议 B"
    const labelHtml = `<label class="sr-only" for="${esc(id)}">${esc(label)} ${suffix}</label>`
    if (field === "narrative_tag") {
      const tagValue = value || "draft"
      return `${labelHtml}<select class="form-select" id="${esc(id)}" data-initial-draft-value="${esc(tagValue)}">
        ${TAG_OPTIONS.map(([optionValue, optionLabel]) => `
          <option value="${esc(optionValue)}" ${optionValue === tagValue ? "selected" : ""}>${esc(optionLabel)}</option>
        `).join("")}
      </select>`
    }
    if (field === "chapter_ids") {
      return `${labelHtml}<input class="form-input" id="${esc(id)}" value="${esc(this._formatDraftRefValue(value))}" readonly />`
    }
    if (field === "title" || field === "pov_character_id") {
      return `${labelHtml}<input class="form-input" id="${esc(id)}" value="${esc(value || "")}" data-initial-draft-value="${esc(value || "")}" />`
    }
    return `${labelHtml}<textarea class="form-textarea" id="${esc(id)}" rows="4" data-initial-draft-value="${esc(value || "")}">${esc(value || "")}</textarea>`
  },

  _renderSplitImpactSummary(preview) {
    const mapping = preview?.chapter_mapping_change || {}
    const fieldChanges = preview?.field_changes || {}
    const drafts = preview?.draft_scenes || []
    const mappingAfter = mapping.after || {}
    const mappingSummary = Object.entries(mappingAfter).map(([sceneId, chapterIds]) => {
      const chapters = Array.isArray(chapterIds) ? chapterIds : []
      return `${sceneId}: ${chapters.length ? chapters.map((id) => `第 ${id} 章`).join("、") : "无章节"}`
    }).join("；") || "以表格中的只读章节映射为准"
    const chunkCounts = drafts.map((draft) => Array.isArray(draft?.scene_chunks) ? draft.scene_chunks.length : 0)
    const technical = {
      chapter_mapping_change: mapping,
      field_changes: fieldChanges,
      scene_chunks: drafts.map((draft) => draft?.scene_chunks || []),
    }
    return `
      <section class="scene-split-impact-summary" aria-label="拆分影响摘要">
        <h3>影响摘要</h3>
        <dl>
          <div><dt>章节映射</dt><dd>${esc(mappingSummary)}</dd></div>
          <div><dt>字段变化</dt><dd>${esc(Object.keys(fieldChanges).length)} 项</dd></div>
          <div><dt>Scene 正文片段</dt><dd>建议 A ${esc(chunkCounts[0] || 0)} 段 · 建议 B ${esc(chunkCounts[1] || 0)} 段</dd></div>
          <div><dt>关联剧情线</dt><dd>${esc(preview?.related_threads?.count ?? 0)} 条</dd></div>
          <div><dt>关联伏笔 / 揭示</dt><dd>${esc(preview?.related_foreshadowing?.count ?? 0)} / ${esc(preview?.related_reveals?.count ?? 0)}</dd></div>
          <div><dt>地图摘要影响</dt><dd>${esc(preview?.map_summary_impact?.message || "无")}</dd></div>
        </dl>
        <details>
          <summary>技术详情</summary>
          <pre>${esc(JSON.stringify(technical, null, 2))}</pre>
        </details>
      </section>
    `
  },

  _readSplitDraftScenes() {
    const fields = [
      "title",
      "goal",
      "core_conflict",
      "emotional_beat",
      "must_happen",
      "must_not_happen",
      "narrative_tag",
      "pov_character_id",
    ]
    return [0, 1].map((index) => {
      const draft = {}
      for (const field of fields) {
        const input = document.getElementById(`scene-split-${index}-${field}`)
        if (!input) continue
        const value = input.value?.trim() || ""
        const initialValue = input.dataset.initialDraftValue?.trim() || ""
        if (field === "narrative_tag") {
          draft[field] = value || "draft"
        } else if (value || initialValue) {
          draft[field] = value || null
        }
      }
      return draft
    })
  },

  _renderPreview(preview) {
    const mapping = preview?.chapter_mapping_change || {}
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    return `
      <div class="scene-impact-preview">
        <div><strong>操作</strong><span>${esc(preview?.operation || "")}</span></div>
        <div><strong>章节映射变化</strong><pre>${esc(JSON.stringify(mapping, null, 2))}</pre></div>
        <div><strong>字段变化</strong><pre>${esc(JSON.stringify(preview?.field_changes || {}, null, 2))}</pre></div>
        <div><strong>关联剧情线</strong><span>${esc(preview?.related_threads?.count ?? 0)} 条</span></div>
        <div><strong>关联伏笔 / 揭示</strong><span>${esc(preview?.related_foreshadowing?.count ?? 0)} / ${esc(preview?.related_reveals?.count ?? 0)}</span></div>
        <div><strong>地图摘要影响</strong><span>${esc(preview?.map_summary_impact?.message || "无")}</span></div>
        ${warnings ? `<ul>${warnings}</ul>` : ""}
      </div>
    `
  },

  _openWritingForScene(scene) {
    const first = (scene.chapter_ids || []).find((id) => String(id).match(/^\d+$/))
    if (first) {
      state.viewStates = state.viewStates || {}
      state.viewStates.writing = {
        ...(state.viewStates.writing || {}),
        projectId: state.currentProjectId,
        currentChapter: parseInt(first, 10),
      }
    }
    router.navigate("writing", null)
  },

  _healthLabel(key) {
    const raw = this._workbench?.health?.[key]?.label || HEALTH_ORDER.find(([k]) => k === key)?.[1] || key
    return raw
  },

  _statusLabel(status) {
    return structureAssetDisplay({ status }).label
  },

  _sceneStatusLabel(scene) {
    if (scene?.status !== "deprecated") return this._statusLabel(scene?.status)
    const meta = scene.structure_meta || {}
    if (meta.deprecated_reason !== "scene_replacement") return "历史"
    const previous = meta.previous_status === "canonical" ? "原已采用" : "原工作稿"
    return `${previous} · 重复提取替换`
  },

  _sourceLabel(sceneOrSource) {
    const scene = sceneOrSource && typeof sceneOrSource === "object" ? sceneOrSource : null
    const source = scene ? scene.source : sceneOrSource
    const meta = scene?.structure_meta || {}
    if (meta.semantic_origin === "mechanical_fusion") {
      const original = Object.fromEntries(SOURCE_OPTIONS)[source] || source || "手动"
      return `${original} · 机械融合`
    }
    if (meta.fusion_kind === "llm_scene_workbench") return "AI 融合"
    return Object.fromEntries(SOURCE_OPTIONS)[source] || source || "手动"
  },

  async _applyManagementFilters() {
    const read = (id) => document.getElementById(id)?.value?.trim() || ""
    this._filters = {
      ...SCENE_FILTER_DEFAULTS,
      health: this._filters.health || this._activeHealth || "",
      q: read("scene-filter-q"),
      status: read("scene-filter-status"),
      source: read("scene-filter-source"),
      workflow_id: read("scene-filter-workflow-id"),
      needs_review: read("scene-filter-needs-review"),
      boundary_status: read("scene-filter-boundary-status"),
      phase: read("scene-filter-phase"),
      phase1a_fallback: Boolean(document.getElementById("scene-filter-phase1a-fallback")?.checked),
      chapter_from: read("scene-filter-chapter-from"),
      chapter_to: read("scene-filter-chapter-to"),
      confidence_band: read("scene-filter-confidence-band"),
      segment: this._filters.segment,
      skip: 0,
    }
    this._activeHealth = this._filters.health || null
    this._selectedFusionSceneIds = new Set()
    this._clearEmbeddedSceneHistory()
    await this._loadWorkbench()
    await router.refresh()
  },

  async _resetManagementFilters() {
    this._filters = { ...SCENE_FILTER_DEFAULTS }
    this._activeHealth = null
    this._advancedFiltersOpen = false
    this._selectedFusionSceneIds = new Set()
    this._clearEmbeddedSceneHistory()
    await this._loadWorkbench()
    await router.refresh()
  },

  async _toggleHealthFilter(health) {
    const nextHealth = this._filters.health === health ? "" : health
    this._filters = {
      ...this._filters,
      health: nextHealth,
      skip: 0,
    }
    this._activeHealth = nextHealth || null
    this._selectedFusionSceneIds = new Set()
    this._clearEmbeddedSceneHistory()
    await this._loadWorkbench()
    await router.refresh()
  },

  async _toggleProgressSegment(segment) {
    if (this._viewMode !== "hot") return
    this._filters = {
      ...this._filters,
      segment: this._filters.segment === segment ? "" : segment,
      skip: 0,
    }
    this._selectedFusionSceneIds = new Set()
    this._clearEmbeddedSceneHistory()
    await this._loadWorkbench()
    await router.refresh()
  },

  async _setViewMode(mode) {
    if (mode !== "normal" && mode !== "hot") return
    if (mode === this._viewMode) return
    this._viewMode = mode
    this._rememberViewMode(mode)
    this._filters = { ...this._filters, segment: "", skip: 0 }
    this._selectedFusionSceneIds = new Set()
    this._clearEmbeddedSceneHistory()
    const query = this._sceneQuery()
    query.delete("scene_id")
    query.set("mode", mode)
    if (state.currentView === "outline" && state.currentSubView === "scenes") {
      await router.navigate("outline", "scenes", true, query)
      return
    }
    await this._loadWorkbench()
    await router.refresh()
  },

  _toggleAdvancedFilters() {
    this._advancedFiltersOpen = !this._advancedFiltersOpen
    router.refresh()
  },

  async _changePage(delta) {
    const newSkip = this._filters.skip + delta * this._filters.limit
    if (newSkip < 0) return
    if (newSkip >= this._total) return
    this._filters.skip = newSkip
    this._selectedFusionSceneIds = new Set()
    this._clearEmbeddedSceneHistory()
    await this._loadWorkbench()
    await router.refresh()
  },

  _renderAutoExtractProgress() {
    if (!this._autoExtractProgress) return ""
    const rangeText = this._autoExtractMeta
      ? `范围: 章节 ${this._autoExtractMeta.start_chapter || 1}-${this._autoExtractMeta.end_chapter || 10}`
      : "范围: 所选章节"
    const dismissHtml = this._autoExtractProgress.failed
      || this._autoExtractProgress.cancelled
      || this._autoExtractProgress.done ? `
      <button class="btn btn-sm" data-action="dismiss-scene-auto-extract">关闭</button>
    ` : `<button class="btn btn-sm" data-action="cancel-scene-auto-extract" ${this._autoExtractCancelPending ? "disabled" : ""}>${this._autoExtractCancelPending ? "取消中..." : "取消任务"}</button>`
    return `<div class="scene-progress-card-wrap">${renderWorkflowCard(this._autoExtractProgress, {
      title: "从正文提取 Scene",
      destinationLabel: rangeText,
    })}${dismissHtml}</div>`
  },

  _updateProgressMount(role, html) {
    if (typeof document === "undefined") return
    const mount = document.querySelector(`[data-role="${role}"]`)
    if (!mount) return
    mount.innerHTML = html
    this._bindEvents()
  },

  _updateAutoExtractProgressDOM() {
    this._updateProgressMount(
      "scene-auto-extract-progress",
      this._renderAutoExtractProgress(),
    )
  },

  _renderFusionSuggestionQueue() {
    const count = Number(
      this._workbench?.fusion_suggestions?.pending_count
      || this._fusionSuggestions.length
      || 0,
    )
    if (!count) return ""
    const dismissibleCount = this._fusionSuggestions
      .filter((item) => item.suggestion_kind !== "replacement").length
    return `
      <div class="scene-fusion-queue" role="status">
        <div>
          <strong>${esc(count)} 条 Scene 建议待处理</strong>
          <span>包含融合决定或受保护 Scene 的替换审查，刷新后仍可继续。</span>
        </div>
        <button class="btn btn-sm btn-primary" data-action="show-fusion-suggestions">逐条处理</button>
        ${dismissibleCount ? '<button class="btn btn-sm" data-action="dismiss-fusion-suggestions">忽略融合建议</button>' : ""}
      </div>
    `
  },

  _stopAutoExtractPolling() {
    if (this._autoExtractPoller?.stop) this._autoExtractPoller.stop()
    this._autoExtractPoller = null
  },

  _startAutoExtractPolling(taskId) {
    this._stopAutoExtractPolling()
    this._autoExtractPoller = pollTaskProgress({
      taskId,
      workflowType: "scene_auto_extraction",
      novelId: state.currentProjectId,
      apiClient: api,
      onUpdate: (progress) => {
        this._autoExtractProgress = progress
        this._updateAutoExtractProgressDOM()
      },
      onDone: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._autoExtractTaskId = null
        this._autoExtractProgress = progress
        this._updateAutoExtractProgressDOM()
        toast("从正文提取 Scene 完成", "success")
        await this._refreshWorkbenchInPlace({ preserveScroll: true })
      },
      onFailed: async (progress) => {
        this._autoExtractProgress = progress
        toast(`从正文提取 Scene 失败: ${progress.errorMessage || "未知错误"}`, "error")
        this._updateAutoExtractProgressDOM()
      },
    })
  },

  _recoverAutoExtractWorkflow() {
    const workflow = recoverActiveWorkflows(state.currentProjectId)
      .find((item) => item.workflowType === "scene_auto_extraction")
    if (!workflow?.taskId) return
    this._autoExtractTaskId = workflow.taskId
    this._autoExtractCancelPending = false
    this._autoExtractMeta = {
      start_chapter: workflow.meta?.start_chapter ?? workflow.meta?.startChapter ?? 1,
      end_chapter: workflow.meta?.end_chapter ?? workflow.meta?.endChapter ?? 10,
    }
    this._autoExtractProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: "scene_auto_extraction",
      status: "running",
      meta: this._autoExtractMeta,
    }, "scene_auto_extraction")
    this._startAutoExtractPolling(workflow.taskId)
  },

  _dismissAutoExtractProgress() {
    this._stopAutoExtractPolling()
    clearActiveWorkflow(this._autoExtractTaskId)
    this._autoExtractTaskId = null
    this._autoExtractProgress = null
    this._autoExtractMeta = null
    this._autoExtractCancelPending = false
    this._updateAutoExtractProgressDOM()
  },

  async _cancelAutoExtractTask() {
    const taskId = this._autoExtractTaskId
    const novelId = state.currentProjectId
    if (!taskId || !novelId || this._autoExtractCancelPending) return false
    const confirmed = await confirmAsync(
      "确认取消当前正文 Scene 提取任务？已完成的阶段结果不会自动删除。",
      "确认取消",
    )
    if (!confirmed) return false

    this._stopAutoExtractPolling()
    this._autoExtractCancelPending = true
    this._updateAutoExtractProgressDOM()
    try {
      await api.tasks.cancel(taskId, novelId)
      this._autoExtractCancelPending = false
      this._autoExtractProgress = normalizeTaskProgress({
        task_id: taskId,
        task_type: "scene_auto_extraction",
        status: "cancelled",
        progress: this._autoExtractProgress?.percent,
        result: { message: "任务已取消" },
        meta: this._autoExtractMeta,
      }, "scene_auto_extraction")
      toast("当前正文 Scene 提取任务已取消", "warning")
      this._updateAutoExtractProgressDOM()
      return true
    } catch (err) {
      this._autoExtractCancelPending = false
      toast(err.message || "取消任务失败", "error")
      this._startAutoExtractPolling(taskId)
      return false
    }
  },

  _showSceneAutoExtractForm() {
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="scene-auto-extract-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="scene-auto-extract-end" type="number" min="1" value="10" />
      </div>
      <label class="scene-quality-option">
        <input id="scene-auto-extract-high-quality" type="checkbox" />
        更高质量 <span class="scene-quality-option__hint">最大推理 + Phase 1c 融合，约需 2 倍时间</span>
      </label>
      <p class="writing-form-hint" role="note">${esc(importAuthorizationNotice())}</p>
    `
    showModalHtml("从正文提取 Scene", formHtml, [{
      text: "确认并开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("scene-auto-extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("scene-auto-extract-end")?.value || "10", 10)
        const highQuality = !!document.getElementById("scene-auto-extract-high-quality")?.checked
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        await this._submitSceneAutoExtraction(start, end, highQuality)
      },
    }])
  },

  async _submitSceneAutoExtraction(start, end, highQuality = false, force = false) {
    try {
      const result = await api.imports.startStage(
        "scenes",
        state.currentProjectId,
        start,
        end,
        force,
        highQuality,
        importAuthorizationPayload(),
      )
      if (result.requires_confirmation) {
        const confirmed = await confirmAsync(result.warning, "确认覆盖")
        if (!confirmed) return
        await this._submitSceneAutoExtraction(start, end, highQuality, true)
        return
      }

      if (!result.task_id) {
        closeModal()
        toast(result.message || "从正文提取 Scene 未启动", "warning")
        return
      }

      this._autoExtractTaskId = result.task_id
      this._autoExtractCancelPending = false
      this._autoExtractMeta = { start_chapter: start, end_chapter: end }
      this._autoExtractProgress = normalizeTaskProgress({
        ...result,
        task_type: "scene_auto_extraction",
        meta: this._autoExtractMeta,
      }, "scene_auto_extraction")
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "scene_auto_extraction",
        label: "从正文提取 Scene",
        projectId: state.currentProjectId,
        view: "scene",
        meta: { ...this._autoExtractMeta, highQuality },
      })
      closeModal()
      toast(`从正文提取 Scene 任务已提交：${result.task_id}`, "success")
      this._startAutoExtractPolling(result.task_id)
      this._updateAutoExtractProgressDOM()
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  _showFusionSuggestions() {
    const suggestions = this._fusionSuggestions
    if (!suggestions.length) {
      toast("暂无 Scene 融合建议", "info")
      return
    }
    const renderSuggestion = (item, input) => {
      const span = Array.isArray(item.chapter_span) ? item.chapter_span.join("-") : "-"
      const trace = (item.scan_trace || []).map((step) => (
        item.suggestion_kind === "replacement"
          ? `第 ${step.chapter_index || "-"} 章：${step.mode || "重叠"}`
          : `${step.action}: ${step.reason || ""}`
      )).join(" / ")
      const replacementDrafts = item.proposed_scene?.draft_scenes || []
      const title = item.suggestion_kind === "replacement"
        ? `${replacementDrafts.length} 个新候选等待替换审查`
        : item.proposed_action === "keep_separate"
          ? "Scene 切分建议"
          : item.proposed_scene?.title || "Scene 融合建议"
      return `
        <label class="scene-fusion-suggestion">
          ${input}
          <strong>${esc(title)}</strong>
          <div class="scene-fusion-suggestion__meta">${esc(item.suggestion_kind || "-")} · 章节 ${esc(span)} · 置信度 ${esc(item.confidence ?? "-")} · ${esc(item.proposed_action || "")}</div>
          <p class="scene-fusion-suggestion__summary">${esc(item.reason || "无说明")}</p>
          <details class="scene-fusion-suggestion__trace"><summary>扫描轨迹</summary><p>${esc(trace || "无")}</p></details>
        </label>
      `
    }
    const keepSeparate = suggestions.filter((item) => (
      item.proposed_action === "keep_separate" && item.suggestion_kind !== "replacement"
    ))
    const reviewRequired = suggestions.filter((item) => !keepSeparate.includes(item))
    const keepRows = keepSeparate.map((item) => renderSuggestion(
      item,
      `<input type="checkbox" name="keep-separate-suggestion" value="${esc(item.id || "")}" />`,
    )).join("")
    const reviewRows = reviewRequired.map((item) => renderSuggestion(
      item,
      `<input type="radio" name="review-suggestion" value="${esc(item.id || "")}" />`,
    )).join("")
    const batchLimit = FUSION_SUGGESTION_DISMISS_BATCH_SIZE
    const body = `
      ${keepRows ? `
        <section class="scene-fusion-suggestion-group" aria-label="可批量确认保持分开">
          <div class="scene-fusion-suggestion-group__header">
            <div><strong>可批量确认保持分开</strong><p>只更新建议状态，不修改 Scene 内容。</p></div>
            <button type="button" class="btn btn-sm" id="select-all-keep-separate">全选本批</button>
          </div>
          ${keepSeparate.length > batchLimit ? `<p class="text-muted">每批最多确认 ${esc(batchLimit)} 条，完成后可继续处理余下建议。</p>` : ""}
          ${keepRows}
        </section>
      ` : ""}
      ${reviewRows ? `
        <section class="scene-fusion-suggestion-group" aria-label="需逐条审查">
          <div class="scene-fusion-suggestion-group__header"><div><strong>需逐条审查</strong><p>合并、替换和失败复核仍需逐条确认。</p></div></div>
          ${reviewRows}
        </section>
      ` : ""}
    `
    const buttons = []
    if (keepRows) {
      buttons.push({
        text: "确认所选保持分开",
        class: "",
        handler: () => this._prepareKeepSeparateBatch(keepSeparate),
      })
    }
    if (reviewRows) {
      buttons.push({
        text: "处理所选审查",
        class: "btn-primary",
        handler: async () => {
          const selectedId = document.querySelector('input[name="review-suggestion"]:checked')?.value
          const suggestion = reviewRequired.find((item) => item.id === selectedId)
          if (!suggestion) {
            toast("请先选择一条需逐条审查的建议", "warning")
            return false
          }
          if (suggestion.suggestion_kind === "replacement") {
            this._showReplacementSuggestion(suggestion)
            return false
          }
          await this._showPrimaryScenePicker(
            suggestion.source_scene_ids || [],
            suggestion.id || null,
          )
          return false
        },
      })
    }
    showModalHtml("Scene 融合建议", body, buttons)
    this._bindKeepSeparateSelectionLimit()
  },

  _bindKeepSeparateSelectionLimit() {
    if (typeof document === "undefined") return
    const selector = 'input[name="keep-separate-suggestion"]'
    const checkboxes = Array.from(document.querySelectorAll(selector))
    const selectedCount = () => checkboxes.filter((input) => input.checked).length
    checkboxes.forEach((input) => input.addEventListener("change", () => {
      if (input.checked && selectedCount() > FUSION_SUGGESTION_DISMISS_BATCH_SIZE) {
        input.checked = false
        toast(`每批最多确认 ${FUSION_SUGGESTION_DISMISS_BATCH_SIZE} 条建议`, "warning")
      }
    }))
    document.getElementById("select-all-keep-separate")?.addEventListener("click", () => {
      checkboxes.forEach((input, index) => {
        input.checked = index < FUSION_SUGGESTION_DISMISS_BATCH_SIZE
      })
    })
  },

  _prepareKeepSeparateBatch(keepSeparate) {
    const selectedIds = Array.from(
      document.querySelectorAll('input[name="keep-separate-suggestion"]:checked'),
    ).map((input) => input.value).filter(Boolean)
    const uniqueIds = [...new Set(selectedIds)]
    if (!uniqueIds.length) {
      toast("请先选择要确认保持分开的建议", "warning")
      return false
    }
    if (uniqueIds.length > FUSION_SUGGESTION_DISMISS_BATCH_SIZE) {
      toast(`每批最多确认 ${FUSION_SUGGESTION_DISMISS_BATCH_SIZE} 条建议`, "warning")
      return false
    }
    const knownIds = new Set(keepSeparate.map((item) => item.id).filter(Boolean))
    const validIds = uniqueIds.filter((id) => knownIds.has(id))
    if (validIds.length !== uniqueIds.length) {
      toast("建议列表已变化，请刷新后重试", "warning")
      return false
    }
    this._confirmKeepSeparateSuggestions(validIds)
    return false
  },

  _confirmKeepSeparateSuggestions(suggestionIds) {
    const ids = [...new Set(suggestionIds)].filter(Boolean)
    if (!ids.length) return false
    const confirmText = `确认 ${ids.length} 条保持分开`
    let pending = false
    showModalHtml("保持 Scene 分开", `
      <p>将确认 ${esc(ids.length)} 条建议中的 Scene 保持独立，并将这些建议标记为已处理。这不会修改 Scene 内容。</p>
    `, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: confirmText,
        class: "btn-primary",
        handler: async () => {
          if (pending) return false
          pending = true
          const confirmButton = Array.from(
            document.querySelectorAll("#modal-footer button"),
          ).find((button) => button.textContent === confirmText)
          if (confirmButton) {
            confirmButton.disabled = true
            confirmButton.textContent = "确认中..."
          }
          let result
          try {
            result = await api.outline.dismissFusionSuggestions(state.currentProjectId, {
              suggestion_ids: ids,
              confirmed: true,
            })
          } catch (err) {
            pending = false
            if (confirmButton) {
              confirmButton.disabled = false
              confirmButton.textContent = confirmText
            }
            toast(err.message || "处理建议失败", "error")
            return false
          }
          const rawDismissed = Number(result?.dismissed)
          const dismissed = Number.isFinite(rawDismissed) ? rawDismissed : ids.length
          try {
            await this._refreshWorkbenchInPlace()
          } catch (err) {
            toast(
              `已确认 ${dismissed} 条建议，但工作台刷新失败，请手动刷新`,
              "warning",
            )
            return true
          }
          toast(`已确认 ${dismissed} 条建议保持分开`, "success")
          return true
        },
      },
    ])
    return false
  },

  _confirmKeepSeparateSuggestion(suggestion) {
    if (!suggestion?.id) return false
    return this._confirmKeepSeparateSuggestions([suggestion.id])
  },

  async _openFusionSuggestion(suggestionId) {
    if (!suggestionId) return this._showFusionSuggestions()
    const suggestion = this._fusionSuggestions.find((item) => item.id === suggestionId)
    if (!suggestion) {
      toast("该建议已变化，请刷新后重试", "warning")
      return
    }
    if (suggestion.suggestion_kind === "replacement") {
      this._showReplacementSuggestion(suggestion)
      return
    }
    if (suggestion.proposed_action === "keep_separate") {
      this._confirmKeepSeparateSuggestion(suggestion)
      return
    }
    await this._showPrimaryScenePicker(
      suggestion.source_scene_ids || [],
      suggestion.id,
    )
  },

  _dismissAllFusionSuggestions() {
    const ids = this._fusionSuggestions
      .filter((item) => item.suggestion_kind !== "replacement")
      .map((item) => item.id)
      .filter(Boolean)
    if (!ids.length) return
    const batchIds = ids.slice(0, FUSION_SUGGESTION_DISMISS_BATCH_SIZE)
    const batchNote = ids.length > batchIds.length
      ? `本次先忽略 ${esc(batchIds.length)} 条，完成后可继续处理剩余 ${esc(ids.length - batchIds.length)} 条。`
      : `将忽略 ${esc(batchIds.length)} 条建议。`
    showModalHtml("忽略 Scene 融合建议", `
      <p>${batchNote}这不会修改任何 Scene。</p>
    `, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认忽略",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.dismissFusionSuggestions(state.currentProjectId, {
              suggestion_ids: batchIds,
              confirmed: true,
            })
            closeModal()
            toast(`已忽略 ${batchIds.length} 条建议`, "success")
            await this._refreshWorkbenchInPlace()
            return true
          } catch (err) {
            toast(err.message || "忽略建议失败", "error")
            return false
          }
        },
      },
    ])
  },

  _showReplacementSuggestion(suggestion) {
    if (!suggestion?.id) return
    const drafts = suggestion.proposed_scene?.draft_scenes || []
    const evidence = suggestion.proposed_scene?.overlap_evidence || suggestion.scan_trace || []
    const visibleSources = (suggestion.source_scene_ids || [])
      .map((id) => this._findScene(id))
      .filter(Boolean)
    const sources = visibleSources.length
      ? visibleSources
      : suggestion.proposed_scene?.source_scenes || []
    const sourceHtml = sources.map((scene) => `
      <article class="scene-draft-ref">
        <strong>${esc(scene.title || "未命名 Scene")}</strong>
        <p>${esc(this._sceneStatusLabel(scene))} · ${esc(this._sceneChapterLabel(scene))}</p>
      </article>
    `).join("") || '<p class="text-muted">原 Scene 已不在当前分页，采用时会重新校验。</p>'
    const fields = [
      ["title", "标题"],
      ["goal", "目标"],
      ["core_conflict", "冲突"],
      ["emotional_beat", "情绪"],
      ["must_happen", "必须发生"],
      ["must_not_happen", "不得发生"],
      ["narrative_tag", "叙事标签"],
    ]
    const draftHtml = drafts.map((draft, index) => `
      <article class="scene-replacement-draft" data-index="${esc(index)}">
        <h4>新候选 ${esc(index + 1)} · 章节 ${esc((draft.chapter_ids || []).join("、") || "-")}</h4>
        ${fields.map(([key, label]) => `
          <label class="scene-detail-field scene-detail-field--wide">
            <span>${esc(label)}</span>
            <textarea class="form-textarea" data-replacement-field="${esc(key)}" rows="${key === "title" || key === "narrative_tag" ? 1 : 2}">${esc(draft[key] || "")}</textarea>
          </label>
        `).join("")}
      </article>
    `).join("")
    const evidenceHtml = evidence.map((item) => (
      `<li>第 ${esc(item.chapter_index || "-")} 章 · ${esc(item.mode || "重叠")}</li>`
    )).join("")
    showModalHtml("Scene 替换审查", `
      <p>原 Scene 会继续作为有效资产，只有明确采用后才会进入历史。</p>
      <section><h4>受保护的原 Scene</h4>${sourceHtml}</section>
      <section><h4>新提取候选</h4>${draftHtml}</section>
      <details><summary>重叠依据</summary><ul>${evidenceHtml || "<li>章节范围重叠</li>"}</ul></details>
    `, [
      {
        text: "保留原 Scene",
        class: "",
        handler: async () => this._dismissReplacementSuggestion(suggestion),
      },
      {
        text: "采用新 Scene，旧 Scene 移入历史",
        class: "btn-primary",
        handler: async () => this._applyReplacementSuggestion(suggestion, false),
      },
      {
        text: "编辑后采用，旧 Scene 移入历史",
        class: "btn-primary",
        handler: async () => this._applyReplacementSuggestion(suggestion, true),
      },
    ])
  },

  _readReplacementDrafts() {
    return Array.from(document.querySelectorAll(".scene-replacement-draft")).map((card) => {
      const values = {}
      card.querySelectorAll("[data-replacement-field]").forEach((input) => {
        values[input.getAttribute("data-replacement-field")] = input.value
      })
      return values
    })
  },

  async _dismissReplacementSuggestion(suggestion) {
    try {
      await api.outline.dismissFusionSuggestions(state.currentProjectId, {
        suggestion_ids: [suggestion.id],
        confirmed: true,
      })
      closeModal()
      toast("已保留原 Scene", "success")
      await this._refreshWorkbenchInPlace()
      return true
    } catch (err) {
      toast(err.message || "处理替换建议失败", "error")
      return false
    }
  },

  async _applyReplacementSuggestion(suggestion, edited) {
    const sourceCount = suggestion?.source_scene_ids?.length || 0
    const draftCount = suggestion?.proposed_scene?.draft_scenes?.length || 0
    const sourceLabel = sourceCount ? `${sourceCount} 个原 Scene` : "原 Scene"
    const draftLabel = draftCount ? `${draftCount} 个新 Scene` : "新 Scene"
    const confirmed = await confirmAsync(
      `采用 ${draftLabel} 后，${sourceLabel} 将移入历史；正文和追踪信息会保留，世界对象和剧情结构不会自动重写。`,
      edited ? "确认编辑后采用" : "确认采用并移入历史",
    )
    if (!confirmed) return false
    try {
      const result = await api.outline.applySceneReplacement(state.currentProjectId, {
        suggestion_id: suggestion.id,
        decision: edited ? "edit_then_replace" : "replace",
        confirmed: true,
        ...(edited ? { draft_scenes: this._readReplacementDrafts() } : {}),
      })
      closeModal()
      const refresh = result?.downstream_refresh_required || []
      toast(
        refresh.length
          ? `新 Scene 已采用，旧 Scene 已移入历史；建议按需重跑：${refresh.join("、")}`
          : "新 Scene 已采用，旧 Scene 已移入历史",
        "success",
      )
      await this._refreshWorkbenchInPlace()
      return true
    } catch (err) {
      toast(err.message || "替换 Scene 失败", "error")
      return false
    }
  },

  async _openReplacementScene(sceneId) {
    if (!sceneId) return
    this._filters.status = ""
    this._filters.skip = 0
    this._pushSceneHistory(sceneId)
    await router.refresh()
  },

  async _openOverlapScene(sceneId) {
    if (!sceneId) return false
    if (this._findSceneItem(sceneId)) {
      this._selectSceneInPlace(sceneId)
      return true
    }
    this._filters = { ...SCENE_FILTER_DEFAULTS }
    this._activeHealth = null
    this._selectedFusionSceneIds.clear()
    const embedded = state.currentView === "outline" && state.currentSubView === "scenes"
    if (embedded) this._selectedSceneIdValue = sceneId
    else state.currentSubView = sceneId
    this._pushSceneHistory(sceneId)
    await router.refresh()
    return true
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "nav-scenes": () => router.navigate("outline", "scenes"),
      "nav-threads": () => router.navigate("outline", "threads"),
      "nav-arcs": () => router.navigate("outline", "arcs"),
      "ai-create-planned-scene": () => window.outlineView?._showOutlineLayerAiForm("planned_scene", this.selectedSceneIdForAi()),
      "view-outline-generate-preview": () => window.outlineView?._showOutlineGeneratePreview(),
      "scene-auto-extract": () => this._showSceneAutoExtractForm(),
      "cancel-scene-auto-extract": () => this._cancelAutoExtractTask(),
      "dismiss-scene-auto-extract": () => this._dismissAutoExtractProgress(),
      "show-fusion-suggestions": () => this._showFusionSuggestions(),
      "dismiss-fusion-suggestions": () => this._dismissAllFusionSuggestions(),
      "open-replacement-scene": (_e, _t, ctx) => this._openReplacementScene(ctx.id),
      "open-overlap-scene": (e, _t, ctx) => {
        e.stopPropagation()
        return this._openOverlapScene(ctx.id)
      },
      "handle-scene-health": (e, t, ctx) => {
        e.stopPropagation()
        return this._handleSceneHealth(ctx.id, t.getAttribute("data-health"))
      },
      "context-review-scene": (_e, _t, ctx) => this._markSceneReviewed(ctx.id),
      "context-open-fusion-suggestion": (_e, t) => (
        this._openFusionSuggestion(t.getAttribute("data-suggestion-id"))
      ),
      "context-confirm-source-mapping": (_e, t, ctx) => (
        this._confirmSourceMapping(ctx.id, t.getAttribute("data-fingerprint"))
      ),
      "context-organize-mapping": (_e, _t, ctx) => this._showOrganizeMapping(ctx.id),
      "context-assign-chapters": (_e, _t, ctx) => this._showAssignChapters(ctx.id),
      "context-complete-setup": (_e, _t, ctx) => this._focusMissingSetup(ctx.id),
      "filter-health": (_e, _t, ctx) => {
        this._toggleHealthFilter(ctx.id)
      },
      "filter-progress-segment": (_e, t) => this._toggleProgressSegment(t.getAttribute("data-segment")),
      "set-scene-view-mode": (_e, t) => this._setViewMode(t.getAttribute("data-mode")),
      "apply-scene-filters": () => this._applyManagementFilters(),
      "reset-scene-filters": () => this._resetManagementFilters(),
      "toggle-advanced-scene-filters": () => this._toggleAdvancedFilters(),
      "prev-scene-page": () => this._changePage(-1),
      "next-scene-page": () => this._changePage(1),
      "select-workbench-scene": (_e, _t, ctx) => {
        this._selectSceneInPlace(ctx.id)
      },
      "edit-workbench-scene": (_e, _t, ctx) => {
        this._selectSceneInPlace(ctx.id)
      },
      "organize-workbench-scene": (_e, _t, ctx) => ctx.id && this._startSplit(ctx.id),
      "open-writing-scene": (_e, _t, ctx) => {
        const scene = ctx.id ? this._findScene(ctx.id) : null
        if (scene) this._openWritingForScene(scene)
      },
      "assign-unassigned-chapter": (_e, _t, ctx) => ctx.chapter && this._assignChapter(ctx.chapter),
      "save-scene-detail": (_e, _t, ctx) => ctx.id && this._saveSceneDetails(ctx.id),
      "mark-scene-reviewed": (_e, _t, ctx) => ctx.id && this._markSceneReviewed(ctx.id),
      "mark-scene-unreviewed": (_e, _t, ctx) => ctx.id && this._markSceneUnreviewed(ctx.id),
      "move-scene-to-history": (_e, _t, ctx) => ctx.id && this._moveSceneToHistory(ctx.id),
      "toggle-fusion-selection": (e, t, ctx) => {
        e.stopPropagation()
        this._toggleFusionSelection(ctx.id, t.checked)
      },
      "select-visible-fusion-scenes": () => this._selectVisibleFusionScenes(),
      "toggle-visible-fusion-selection": () => this._toggleVisibleFusionSelection(),
      "clear-fusion-selection": () => this._clearFusionSelection(),
      "review-selected-scenes": () => this._toggleSelectedSceneReview(),
      "handle-selected-context-actions": () => this._handleSelectedContextActions(),
      "start-selected-merge": () => this._startSelectedMerge(),
      "start-ai-fusion-draft": () => this._startManualFusion(),
      "start-manual-fusion": () => this._startManualFusion(),
      "start-merge-scene": (_e, _t, ctx) => ctx.id && this._startMerge(ctx.id),
      "start-split-scene": (_e, _t, ctx) => ctx.id && this._startSplit(ctx.id),
      "close-scene-detail": () => {
        this._mobileDetailOpen = false
        this._clearEmbeddedSceneHistory()
        router.renderCurrentView()
      },
    })

    bindActionMenus()
  },
}

router.registerView("scene", sceneWorkbenchView)
window.sceneWorkbenchView = sceneWorkbenchView
export default sceneWorkbenchView
