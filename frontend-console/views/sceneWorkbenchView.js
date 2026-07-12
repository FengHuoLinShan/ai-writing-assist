import { bindWorkspaceClick, renderActionMenu, bindActionMenus } from "../shared/viewHelper.js"
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
  skip: 0,
  limit: 20,
}

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

const sceneWorkbenchView = {
  _loading: true,
  _workbench: null,
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

  async onEnter() {
    this._loading = true
    this._workbench = null
    this._total = 0
    this._selectedFusionSceneIds = new Set()
    this._fusionSuggestions = []
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
    this._stopAutoExtractPolling()
    this._mobileDetailOpen = false
  },

  async render() {
    if (this._loading) return '<div class="loading">加载中...</div>'
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
        <div class="scene-workbench-actions">
          <button class="btn btn-primary" data-action="scene-auto-extract">场景（scene）自动提取</button>
        </div>
        <div data-role="scene-auto-extract-progress">${this._renderAutoExtractProgress()}</div>
        ${this._renderFusionSuggestionQueue()}
        <div class="scene-workbench ${narrow ? "is-narrow" : ""}">
          <section class="scene-workbench__organize">
            ${this._renderManagementFilters()}
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
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  async _loadWorkbench() {
    if (!state.currentProjectId) return
    this._workbench = await api.outline.getSceneWorkbench(
      state.currentProjectId,
      this._routeSceneId(),
      this._sceneWorkbenchParams(),
    )
    this._total = Number(this._workbench?.total ?? this._workbench?.items?.length ?? 0) || 0
    const effectiveSkip = Number(this._workbench?.skip)
    if (Number.isInteger(effectiveSkip) && effectiveSkip >= 0) {
      this._filters.skip = effectiveSkip
    }
    const pendingSuggestions = Number(
      this._workbench?.fusion_suggestions?.pending_count || 0,
    )
    if (pendingSuggestions > 0 && api.outline.listFusionSuggestions) {
      const result = await api.outline.listFusionSuggestions(
        state.currentProjectId,
        { skip: 0, limit: 100 },
      )
      this._fusionSuggestions = Array.isArray(result?.items) ? result.items : []
    } else {
      this._fusionSuggestions = []
    }
  },

  _sceneWorkbenchParams() {
    const params = {
      skip: this._filters.skip,
      limit: this._filters.limit,
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
    return params
  },

  _renderManagementFilters() {
    const advancedFilters = this._advancedFiltersOpen ? `
      <label class="scene-filter-field scene-filter-field--wide">
        <span>Workflow</span>
        <input class="form-input" id="scene-filter-workflow-id" value="${esc(this._filters.workflow_id)}" placeholder="workflow_id" />
      </label>
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
              <span>#${esc(scene.scene_index ?? "-")}</span>
              <span>${esc(this._statusLabel(scene.status))}</span>
              <span>${esc(this._sourceLabel(scene.source))}</span>
              <span>${esc(item.chapter_range || "未关联章节")}</span>
            </div>
            <div class="scene-workbench-row__title">${esc(scene.title || "未命名 Scene")}</div>
            <div class="scene-workbench-row__summary">${esc(item.summary || scene.goal || "暂无目标")}</div>
          </button>
          <div class="scene-workbench-row__health">${health}</div>
        </div>
        <div class="scene-workbench-row__actions">
          ${this._renderContextAction(item)}
          ${contextAction.key === "edit" ? "" : `<button class="btn btn-sm scene-secondary-action" data-action="edit-workbench-scene" data-id="${esc(scene.id)}">编辑</button>`}
          ${renderActionMenu(`scene-actions-${esc(scene.id)}`, [
            { action: "open-writing-scene", label: "打开写作", data: { id: scene.id } },
            { action: "start-merge-scene", label: "合并", data: { id: scene.id } },
            { action: "start-split-scene", label: "拆分", data: { id: scene.id } },
            ...(this._sceneReviewState(item).reviewed
              ? [{ action: "mark-scene-unreviewed", label: "标记需检查", data: { id: scene.id } }]
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
          <div><strong>来源与注意</strong><span>${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))} · ${esc(reviewLabel)}</span></div>
          ${attentionLabels.length ? `<div><strong>待处理</strong><span>${esc(attentionLabels.join(" · "))}</span></div>` : ""}
        </section>
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
    return routeId || this._workbench?.selected_scene_id || this._workbench?.items?.[0]?.scene?.id || null
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
    const items = this._filteredItems()
    return items.find((item) => item.scene?.id === id) || items[0] || null
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
    const hash = embedded
      ? `#workbench/${encodeURIComponent(state.currentProjectId)}/outline/scenes?scene_id=${encodeURIComponent(sceneId)}`
      : `#workbench/${encodeURIComponent(state.currentProjectId)}/scene/${encodeURIComponent(sceneId)}`
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
    if (target) setTimeout(() => document.getElementById(target[1])?.focus(), 0)
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
    const sourceId = prompt("输入要合并进来的 Scene ID：")
    if (!sourceId) return
    await this._previewAndMerge(targetSceneId, [sourceId])
  },

  async _previewAndMerge(targetSceneId, sourceSceneIds) {
    const request = {
      target_scene_id: targetSceneId,
      source_scene_ids: sourceSceneIds,
    }
    const preview = await api.outline.previewSceneMerge(state.currentProjectId, request)
    showModalHtml("合并 Scene 影响预览", this._renderPreview(preview), [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认合并",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.mergeScenes(state.currentProjectId, {
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
        <div class="scene-picker-card__meta">${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))} · ${esc(this._sceneChapterLabel(scene))}</div>
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
          <div class="scene-picker-card__meta">${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))} · ${esc(this._sceneChapterLabel(scene))}</div>
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
    try {
      const preview = await api.outline.previewSceneFusion(state.currentProjectId, {
        source_scene_ids: sourceSceneIds,
        primary_scene_id: primarySceneId,
      })
      this._showFusionPreview(
        { ...preview, suggestion_id: suggestionId },
        sourceSceneIds,
      )
    } catch (err) {
      toast(err.message || "Scene 融合预览失败", "error")
    }
  },

  _showFusionPreview(preview, fallbackSourceIds) {
    const sourceSceneIds = preview?.source_scene_ids?.length
      ? preview.source_scene_ids
      : fallbackSourceIds
    this._activeDraftReview = preview || null
    showModalHtml("Scene AI 建议预览", this._renderDraftReview(preview), [
      {
        text: "保留原 Scene + 保存融合 Scene",
        class: "btn-primary",
        handler: () => this._saveFusionResult("keep_originals", sourceSceneIds),
      },
      {
        text: "保存融合 Scene，并废弃原 Scene",
        class: "btn-primary",
        handler: () => this._saveFusionResult("deprecate_originals", sourceSceneIds),
      },
      {
        text: "放弃融合结果",
        class: "btn-ghost",
        handler: () => this._saveFusionResult("discard", sourceSceneIds),
      },
      {
        text: "继续编辑融合结果后再保存",
        class: "btn-primary",
        handler: () => this._saveFusionResult("edit_then_save", sourceSceneIds),
      },
    ])
  },

  _renderDraftReview(preview) {
    const fused = preview?.draft_scene || preview?.fused_scene || preview?.preview_scene || {}
    const sourceIds = preview?.source_scene_ids || []
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    const conflicts = (preview?.conflicts || []).map((item) => `<li>${esc(item.message || item.field || "")}</li>`).join("")
    const refs = preview?.field_references || {}
    const row = (field, label, editorHtml) => {
      const fieldRefs = refs[field] || []
      const primaryRefs = fieldRefs.filter((item) => item.role === "primary")
      const otherRefs = fieldRefs.filter((item) => item.role !== "primary")
      const renderRef = (item) => `<div class="scene-draft-ref"><strong>${esc(item.title || item.scene_id)}</strong><p>${esc(this._formatDraftRefValue(item.value))}</p></div>`
      return `
        <div class="scene-draft-review-row">
          <div class="scene-draft-review-row__label">${esc(label)}</div>
          <div>${editorHtml}</div>
          <div>${primaryRefs.map(renderRef).join("") || '<span class="muted">无</span>'}</div>
          <div>${otherRefs.map(renderRef).join("") || '<span class="muted">无</span>'}</div>
        </div>
      `
    }
    return `
      <div class="scene-fusion-preview">
        <section class="scene-fusion-preview__meta">
          <div><strong>来源 Scene</strong><span>${esc(sourceIds.join(", "))}</span></div>
          ${preview?.primary_scene_id ? `<div><strong>主 Scene</strong><span>${esc(preview.primary_scene_id)}</span></div>` : ""}
          ${preview?.reason ? `<p>${esc(preview.reason)}</p>` : ""}
          ${warnings ? `<ul>${warnings}</ul>` : ""}
          ${conflicts ? `<ul>${conflicts}</ul>` : ""}
        </section>
        <div class="scene-draft-review-grid">
          <div class="scene-draft-review-head">字段</div>
          <div class="scene-draft-review-head">AI 建议</div>
          <div class="scene-draft-review-head">主 Scene 原值</div>
          <div class="scene-draft-review-head">其他 Scene 原值</div>
          ${row("title", "标题", `<input class="form-input" id="scene-fusion-title" value="${esc(fused.title || "")}" />`)}
          ${row("goal", "目标", `<textarea class="form-textarea" id="scene-fusion-goal" rows="3">${esc(fused.goal || "")}</textarea>`)}
          ${row("core_conflict", "核心冲突", `<textarea class="form-textarea" id="scene-fusion-conflict" rows="3">${esc(fused.core_conflict || "")}</textarea>`)}
          ${row("emotional_beat", "情感节奏", `<textarea class="form-textarea" id="scene-fusion-emotion" rows="3">${esc(fused.emotional_beat || "")}</textarea>`)}
          ${row("must_happen", "必须发生", `<textarea class="form-textarea" id="scene-fusion-must" rows="3">${esc(fused.must_happen || "")}</textarea>`)}
          ${row("must_not_happen", "禁止发生", `<textarea class="form-textarea" id="scene-fusion-must-not" rows="3">${esc(fused.must_not_happen || "")}</textarea>`)}
          ${row("chapter_ids", "章节 IDs", `<input class="form-input" id="scene-fusion-chapters" value="${esc((fused.chapter_ids || []).join(", "))}" />`)}
        </div>
      </div>
    `
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
      chapter_ids: chapters,
      structure_meta: {
        draft_review_mode: this._activeDraftReview?.mode || "fusion",
        primary_scene_id: this._activeDraftReview?.primary_scene_id || null,
        confidence: this._activeDraftReview?.confidence ?? null,
        draft_review_warnings: this._activeDraftReview?.warnings || [],
        draft_review_conflicts: this._activeDraftReview?.conflicts || [],
      },
    }
  },

  async _saveFusionResult(mode, sourceSceneIds) {
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
    } catch (err) {
      toast(err.message || "Scene 融合保存失败", "error")
    }
  },

  async _startSplit(sourceSceneId) {
    const raw = prompt("输入拆分起始章节：")
    const chapter = parseInt(raw || "", 10)
    if (!Number.isFinite(chapter)) return
    await this._previewAndSplit(sourceSceneId, chapter)
  },

  async _previewAndSplit(sourceSceneId, splitChapterIndex) {
    const request = {
      source_scene_id: sourceSceneId,
      split_chapter_index: splitChapterIndex,
    }
    const preview = await api.outline.previewSceneSplit(state.currentProjectId, request)
    showModalHtml("Scene AI 建议预览", this._renderSplitDraftReview(preview), [
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
    ])
  },

  _renderSplitDraftReview(preview) {
    const drafts = preview?.draft_scenes || []
    const sourceRefs = preview?.field_references || {}
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    const fields = [
      ["title", "标题"],
      ["goal", "目标"],
      ["core_conflict", "核心冲突"],
      ["emotional_beat", "情感节奏"],
      ["must_happen", "必须发生"],
      ["must_not_happen", "禁止发生"],
      ["chapter_ids", "章节 IDs"],
    ]
    const refValue = (field) => (sourceRefs[field] || [])
      .map((item) => `${item.title || item.scene_id}: ${this._formatDraftRefValue(item.value)}`)
      .join("；") || "无"
    const splitEditor = (draftIndex, field, value) => {
      const id = `scene-split-${draftIndex}-${field}`
      if (field === "chapter_ids") {
        return `<input class="form-input" id="${esc(id)}" value="${esc(this._formatDraftRefValue(value))}" readonly />`
      }
      return `<textarea class="form-textarea" id="${esc(id)}" rows="2">${esc(value || "")}</textarea>`
    }
    const rows = fields.map(([field, label]) => `
      <div class="scene-draft-review-row">
        <div class="scene-draft-review-row__label">${esc(label)}</div>
        <div>${esc(refValue(field))}</div>
        <div>${splitEditor(0, field, drafts[0]?.[field])}</div>
        <div>${splitEditor(1, field, drafts[1]?.[field])}</div>
      </div>
    `).join("")
    return `
      <div class="scene-fusion-preview">
        <section class="scene-fusion-preview__meta">
          <div><strong>操作</strong><span>AI 拆分建议</span></div>
          ${warnings ? `<ul>${warnings}</ul>` : ""}
        </section>
        <div class="scene-draft-review-grid">
          <div class="scene-draft-review-head">字段</div>
          <div class="scene-draft-review-head">原 Scene</div>
          <div class="scene-draft-review-head">建议 A</div>
          <div class="scene-draft-review-head">建议 B</div>
          ${rows}
        </div>
        ${this._renderPreview(preview)}
      </div>
    `
  },

  _readSplitDraftScenes() {
    const fields = ["title", "goal", "core_conflict", "emotional_beat", "must_happen", "must_not_happen", "narrative_tag"]
    return [0, 1].map((index) => {
      const draft = {}
      for (const field of fields) {
        const value = document.getElementById(`scene-split-${index}-${field}`)?.value?.trim()
        if (value) draft[field] = value
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

  _sourceLabel(source) {
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
      title: "场景（scene）自动提取",
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
    return `
      <div class="scene-fusion-queue" role="status">
        <div>
          <strong>${esc(count)} 条 Scene 融合建议待处理</strong>
          <span>高质量导入产生的低置信或冲突结果，刷新后仍可继续。</span>
        </div>
        <button class="btn btn-sm btn-primary" data-action="show-fusion-suggestions">逐条处理</button>
        <button class="btn btn-sm" data-action="dismiss-fusion-suggestions">全部忽略</button>
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
        toast("场景（scene）自动提取完成", "success")
        await this._refreshWorkbenchInPlace({ preserveScroll: true })
      },
      onFailed: async (progress) => {
        this._autoExtractProgress = progress
        toast(`场景（scene）自动提取失败: ${progress.errorMessage || "未知错误"}`, "error")
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
      "确认取消当前场景自动提取任务？已完成的阶段结果不会自动删除。",
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
      toast("当前场景自动提取任务已取消", "warning")
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
    showModalHtml("场景（scene）自动提取", formHtml, [{
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
        const confirmed = await new Promise((resolve) => {
          confirmAction(result.warning, () => resolve(true), "确认覆盖")
          setTimeout(() => {
            const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
            if (cancelBtn) cancelBtn.onclick = () => resolve(false)
          }, 50)
        })
        if (!confirmed) return
        await this._submitSceneAutoExtraction(start, end, highQuality, true)
        return
      }

      if (!result.task_id) {
        closeModal()
        toast(result.message || "场景（scene）自动提取未启动", "warning")
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
        label: "场景（scene）自动提取",
        projectId: state.currentProjectId,
        view: "scene",
        meta: { ...this._autoExtractMeta, highQuality },
      })
      closeModal()
      toast(`场景（scene）自动提取任务已提交：${result.task_id}`, "success")
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
    const rows = suggestions.map((item, index) => {
      const span = Array.isArray(item.chapter_span) ? item.chapter_span.join("-") : "-"
      const trace = (item.scan_trace || []).map((step) => `${step.action}: ${step.reason || ""}`).join(" / ")
      return `
        <label class="scene-fusion-suggestion">
          <input type="radio" name="fusion-suggestion" value="${esc(index)}" ${index === 0 ? "checked" : ""} />
          <strong>${esc(item.proposed_scene?.title || "Scene 融合建议")}</strong>
          <div class="scene-fusion-suggestion__meta">${esc(item.suggestion_kind || "-")} · 章节 ${esc(span)} · 置信度 ${esc(item.confidence ?? "-")} · ${esc(item.proposed_action || "")}</div>
          <p class="scene-fusion-suggestion__summary">${esc(item.reason || "无说明")}</p>
          <details class="scene-fusion-suggestion__trace"><summary>扫描轨迹</summary><p>${esc(trace || "无")}</p></details>
        </label>
      `
    }).join("")
    showModalHtml("Scene 融合建议", rows, [{
      text: "处理所选建议",
      class: "btn-primary",
      handler: async () => {
        const selected = document.querySelector('input[name="fusion-suggestion"]:checked')?.value
        const suggestion = suggestions[Number(selected || 0)]
        if (!suggestion) return
        closeModal()
        if (suggestion.proposed_action === "keep_separate") {
          this._confirmKeepSeparateSuggestion(suggestion)
          return
        }
        await this._showPrimaryScenePicker(
          suggestion.source_scene_ids || [],
          suggestion.id || null,
        )
      },
    }])
  },

  _confirmKeepSeparateSuggestion(suggestion) {
    if (!suggestion?.id) return
    showModalHtml("保持 Scene 分开", `
      <p>将确认这些 Scene 保持独立，并将该建议标记为已处理。这不会修改 Scene 内容。</p>
    `, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认保持分开",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.dismissFusionSuggestions(state.currentProjectId, {
              suggestion_ids: [suggestion.id],
              confirmed: true,
            })
            closeModal()
            toast("已确认 Scene 保持分开", "success")
            await this._refreshWorkbenchInPlace()
          } catch (err) {
            toast(err.message || "处理建议失败", "error")
          }
        },
      },
    ])
  },

  async _openFusionSuggestion(suggestionId) {
    if (!suggestionId) return this._showFusionSuggestions()
    const suggestion = this._fusionSuggestions.find((item) => item.id === suggestionId)
    if (!suggestion) {
      toast("该建议已变化，请刷新后重试", "warning")
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
    const ids = this._fusionSuggestions.map((item) => item.id).filter(Boolean)
    if (!ids.length) return
    showModalHtml("忽略 Scene 融合建议", `
      <p>将忽略 ${esc(ids.length)} 条建议。这不会修改任何 Scene。</p>
    `, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认忽略",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.dismissFusionSuggestions(state.currentProjectId, {
              suggestion_ids: ids,
              confirmed: true,
            })
            closeModal()
            toast(`已忽略 ${ids.length} 条建议`, "success")
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

  _bindEvents() {
    bindWorkspaceClick(this, {
      "nav-scenes": () => router.navigate("outline", "scenes"),
      "nav-threads": () => router.navigate("outline", "threads"),
      "nav-arcs": () => router.navigate("outline", "arcs"),
      "nav-foreshadowing": () => router.navigate("outline", "foreshadowing"),
      "nav-reveals": () => router.navigate("outline", "reveals"),
      "scene-auto-extract": () => this._showSceneAutoExtractForm(),
      "cancel-scene-auto-extract": () => this._cancelAutoExtractTask(),
      "dismiss-scene-auto-extract": () => this._dismissAutoExtractProgress(),
      "show-fusion-suggestions": () => this._showFusionSuggestions(),
      "dismiss-fusion-suggestions": () => this._dismissAllFusionSuggestions(),
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
        router.renderCurrentView()
      },
    })

    bindActionMenus()
  },
}

router.registerView("scene", sceneWorkbenchView)
window.sceneWorkbenchView = sceneWorkbenchView
export default sceneWorkbenchView
