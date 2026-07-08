/**
 * 大纲视图
 *
 * 子标签：场景卡 | 剧情线 | 篇章纲 | 伏笔 | 揭示
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
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"

const SCENE_ALLOWED_TAGS = new Set(["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"])
const ENTITY_ALLOWED_STATUSES = new Set(["canonical", "draft", "candidate", "deprecated"])
const FORESHADOWING_STATUSES = ["draft", "planted", "triggered", "resolved", "abandoned"]
const REVEAL_STATUSES = ["draft", "planned", "revealed", "resolved", "abandoned"]

const FORESHADOWING_STATUS_LABELS = { draft: "草稿", planted: "已埋下", triggered: "已触发", resolved: "已兑现", abandoned: "已废弃" }
const REVEAL_STATUS_LABELS = { draft: "草稿", planned: "计划中", revealed: "已揭示", resolved: "已解决", abandoned: "已废弃" }
const STRUCTURE_FILTER_DEFAULTS = { status: "", source: "", workflow_id: "", needs_review: "", skip: 0, limit: 50 }
const STRUCTURE_SOURCE_OPTIONS = [
  ["deep_import", "深度导入"],
  ["manual", "手动"],
  ["ai_generated", "AI 生成"],
]

const outlineView = {
  _threads: [],
  _arcs: [],
  _scenes: [],
  _foreshadowing: [],
  _reveals: [],
  _loading: true,
  _generateOverlap: { threadCount: 0, arcCount: 0, rangeKey: "" },
  _structureFilters: {},
  _structureTotals: {
    threads: 0,
    arcs: 0,
    foreshadowing: 0,
    reveals: 0,
  },
  _plotAutoExtractTaskId: null,
  _plotAutoExtractProgress: null,
  _plotAutoExtractPoller: null,
  _plotAutoExtractMeta: null,
  _bulkSelections: {},

  async onEnter() {
    this._loading = true
    this._threads = []
    this._arcs = []
    this._foreshadowing = []
    this._reveals = []
    this._structureTotals = {
      threads: 0,
      arcs: 0,
      foreshadowing: 0,
      reveals: 0,
    }
    clearAllBulkSelections(this)

    if (!state.currentProjectId) {
      this._loading = false
      return
    }

    const subView = state.currentSubView || "threads"
    const fetchThreads = subView === "threads" || subView === "scenes"
    const fetchArcs = subView === "arcs"
    const fetchForeshadowing = subView === "foreshadowing"
    const fetchReveals = subView === "reveals"
    const filterParams = this._structureFilterParams(subView)

    const promises = []
    if (fetchThreads) {
      promises.push(
        api.outline.listThreads(state.currentProjectId, filterParams)
          .then((data) => {
            this._threads = data.items || data || []
            this._structureTotals.threads = Number(data.total ?? this._threads.length) || 0
          })
          .catch(() => { this._threads = []; this._structureTotals.threads = 0 })
      )
    }
    if (fetchArcs) {
      promises.push(
        api.outline.listArcs(state.currentProjectId, filterParams)
          .then((data) => {
            this._arcs = data.items || data || []
            this._structureTotals.arcs = Number(data.total ?? this._arcs.length) || 0
          })
          .catch(() => { this._arcs = []; this._structureTotals.arcs = 0 })
      )
    }
    if (fetchForeshadowing) {
      promises.push(
        api.outline.listForeshadowing(state.currentProjectId, filterParams)
          .then((data) => {
            this._foreshadowing = data.items || data || []
            this._structureTotals.foreshadowing = Number(data.total ?? this._foreshadowing.length) || 0
          })
          .catch(() => { this._foreshadowing = []; this._structureTotals.foreshadowing = 0 })
      )
    }
    if (fetchReveals) {
      promises.push(
        api.outline.listReveals(state.currentProjectId, filterParams)
          .then((data) => {
            this._reveals = data.items || data || []
            this._structureTotals.reveals = Number(data.total ?? this._reveals.length) || 0
          })
          .catch(() => { this._reveals = []; this._structureTotals.reveals = 0 })
      )
    }

    if (promises.length > 0) {
      await Promise.all(promises)
    }
    this._loading = false
  },

  onLeave() {
    this._stopPlotAutoExtractPolling()
  },

  onActivate() {
    // KeepAlive 恢复后重新绑定事件（DOM 来自缓存，事件监听器可能丢失）
    this._bindEvents()
    const saved = state.viewStates && state.viewStates.outline
    if (saved && saved.scrollTop != null) {
      const container = document.querySelector("#workspace-content .subnav")
      if (container) {
        container.scrollTop = saved.scrollTop
      }
    }
  },

  onDeactivate() {
    // 保存滚动位置
    const container = document.querySelector("#workspace-content .subnav")
    if (container) {
      state.viewStates = state.viewStates || {}
      state.viewStates.outline = { scrollTop: container.scrollTop }
    }
  },

  async _refreshCurrentSubViewInPlace({ preserveScroll = true } = {}) {
    const content = typeof document !== "undefined"
      ? document.getElementById("workspace-content")
      : null
    const scrollTop = preserveScroll && content ? content.scrollTop : 0

    await this.onEnter()

    if (!content) {
      router.refresh()
      return
    }

    content.innerHTML = await this.render()
    content.scrollTop = scrollTop
    this._bindEvents()
  },

  async render() {
    const subView = state.currentSubView || "threads"
    let html = ""

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "scenes" ? "active" : ""}" data-action="nav-scenes">场景工作台</span>
        <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-action="nav-threads">剧情线</span>
        <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-action="nav-arcs">篇章纲</span>
        <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-action="nav-foreshadowing">伏笔</span>
        <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-action="nav-reveals">揭示</span>
      </div>
    `

    if (this._loading) {
      html += '<div class="loading">加载中...</div>'
    } else if (subView === "scenes") {
      html += this._renderScenes()
    } else if (subView === "threads") {
      html += this._renderThreads()
    } else if (subView === "arcs") {
      html += this._renderArcs()
    } else if (subView === "foreshadowing") {
      html += this._renderForeshadowing()
    } else if (subView === "reveals") {
      html += this._renderReveals()
    }

    setTimeout(() => this._bindEvents(), 0)
    return this._renderPlotAutoExtractProgress() + html
  },

  _renderPlotAutoExtractProgress() {
    if (!this._plotAutoExtractProgress) return ""
    const rangeText = this._plotAutoExtractMeta
      ? `范围: 章节 ${this._plotAutoExtractMeta.start_chapter || 1}-${this._plotAutoExtractMeta.end_chapter || 10}`
      : "范围: 所选章节"
    return `<div class="outline-progress-card-wrap">${renderWorkflowCard(this._plotAutoExtractProgress, {
      title: "剧情线自动提取",
      destinationLabel: rangeText,
    })}</div>`
  },

  _stopPlotAutoExtractPolling() {
    if (this._plotAutoExtractPoller?.stop) this._plotAutoExtractPoller.stop()
    this._plotAutoExtractPoller = null
  },

  _startPlotAutoExtractPolling(taskId) {
    this._stopPlotAutoExtractPolling()
    this._plotAutoExtractPoller = pollTaskProgress({
      taskId,
      workflowType: "plot_structure_auto_extraction",
      apiClient: api,
      onUpdate: (progress) => {
        this._plotAutoExtractProgress = progress
        router.renderCurrentView()
      },
      onDone: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._plotAutoExtractTaskId = null
        toast("剧情线自动提取完成", "success")
        await this.onEnter?.()
        router.refresh()
      },
      onFailed: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._plotAutoExtractTaskId = null
        toast(`剧情线自动提取失败: ${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
  },

  _renderScenes() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128209;</div>
        <p>场景工作台已作为一级工作区</p>
        <p class="outline-empty-detail">这里保留旧路径兼容入口，点击后进入完整 Scene 管理。</p>
        <button class="btn btn-primary" data-action="open-scene-workbench">打开场景工作台</button>
      </div>
    `
  },

  _narrativeTagLabel(tag) {
    const map = {
      inciting_incident: "激励事件",
      rising_action: "冲突升级",
      climax: "阶段高潮",
      valley: "低谷",
      transition: "过渡",
      hook: "钩子",
      payoff: "爽点",
      draft: "草稿",
    }
    return map[tag] || tag || "草稿"
  },

  _structureFilterFor(subView = state.currentSubView || "threads") {
    if (!this._structureFilters[subView]) {
      this._structureFilters[subView] = { ...STRUCTURE_FILTER_DEFAULTS }
    }
    return this._structureFilters[subView]
  },

  _structureFilterParams(subView = state.currentSubView || "threads") {
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) {
      return {}
    }
    const filters = this._structureFilterFor(subView)
    const params = {
      skip: filters.skip,
      limit: filters.limit,
    }
    if (filters.status) params.status = filters.status
    if (filters.source) params.source = filters.source
    if (filters.workflow_id) params.workflow_id = filters.workflow_id
    if (filters.needs_review === "true") params.needs_review = true
    if (filters.needs_review === "false") params.needs_review = false
    return params
  },

  _structureStatusOptions(subView) {
    if (subView === "foreshadowing") {
      return FORESHADOWING_STATUSES.map((status) => [status, FORESHADOWING_STATUS_LABELS[status] || status])
    }
    if (subView === "reveals") {
      return REVEAL_STATUSES.map((status) => [status, REVEAL_STATUS_LABELS[status] || status])
    }
    return [
      ["canonical", "正史"],
      ["draft", "草稿"],
      ["candidate", "候选"],
      ["deprecated", "废弃"],
    ]
  },

  _renderStructureFilters(subView) {
    const filters = this._structureFilterFor(subView)
    return `
      <div class="scene-management-filters" aria-label="结构资产筛选">
        ${this._structureFilterSelect("outline-filter-status", "状态", filters.status, this._structureStatusOptions(subView), "全部状态")}
        ${this._structureFilterSelect("outline-filter-source", "来源", filters.source, STRUCTURE_SOURCE_OPTIONS, "全部来源")}
        <label class="scene-filter-field scene-filter-field--wide">
          <span>Workflow</span>
          <input class="form-input" id="outline-filter-workflow-id" value="${esc(filters.workflow_id)}" placeholder="workflow_id" />
        </label>
        ${this._structureFilterSelect("outline-filter-needs-review", "复核", filters.needs_review, [["true", "需复核"], ["false", "无需复核"]], "全部复核")}
        <div class="scene-filter-actions">
          <button class="btn btn-sm btn-primary" data-action="apply-outline-structure-filters">应用</button>
          <button class="btn btn-sm" data-action="reset-outline-structure-filters">重置</button>
        </div>
      </div>
    `
  },

  _renderStructurePagination(subView) {
    const filters = this._structureFilterFor(subView)
    const total = this._structureTotals[subView] || 0
    if (total <= filters.limit) return ""
    const currentPage = Math.floor(filters.skip / filters.limit) + 1
    const totalPages = Math.ceil(total / filters.limit)
    const prevDisabled = filters.skip <= 0 ? "disabled" : ""
    const nextDisabled = filters.skip + filters.limit >= total ? "disabled" : ""
    return `
      <div class="outline-structure-pagination">
        <button class="btn btn-sm" data-action="prev-outline-structure-page" ${prevDisabled}>上一页</button>
        <span class="outline-structure-pagination__info">第 ${currentPage} / ${totalPages} 页，共 ${esc(total)} 条</span>
        <button class="btn btn-sm" data-action="next-outline-structure-page" ${nextDisabled}>下一页</button>
      </div>
    `
  },

  _structureFilterSelect(id, label, value, options, emptyLabel) {
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

  _assetProvenance(asset) {
    return asset?.provenance_meta && typeof asset.provenance_meta === "object"
      ? asset.provenance_meta
      : {}
  },

  _renderStructureAssetBadges(asset) {
    const meta = this._assetProvenance(asset)
    const badges = []
    const source = meta.source || asset.source
    if (source === "deep_import") badges.push('<span class="badge badge-info">深度导入</span>')
    else if (source === "manual") badges.push('<span class="badge">手动</span>')
    else if (source) badges.push(`<span class="badge">${esc(source)}</span>`)
    if (meta.needs_review === true) badges.push('<span class="badge badge-warning">需复核</span>')
    if (meta.phase) badges.push(`<span class="badge">${esc(meta.phase)}</span>`)
    return badges.length ? `<div class="structure-asset-badges">${badges.join("")}</div>` : ""
  },

  _structureReviewState(asset) {
    const meta = this._assetProvenance(asset)
    return {
      reviewed: Boolean(meta.reviewed_at),
      needsReview: meta.needs_review === true,
    }
  },

  _renderThreadReviewAction(thread) {
    const id = thread?.id || thread?.thread_id
    if (!id) return ""
    const review = this._structureReviewState(thread)
    if (review.reviewed) {
      return `<button class="btn btn-sm" data-action="mark-thread-unreviewed" data-id="${esc(id)}">取消复核</button>`
    }
    const primary = review.needsReview ? "btn-primary" : ""
    return `<button class="btn btn-sm ${primary}" data-action="mark-thread-reviewed" data-id="${esc(id)}">复核通过</button>`
  },

  _reviewThreadPayload(thread, reviewedFrom) {
    const meta = {
      ...this._assetProvenance(thread),
      needs_review: false,
      reviewed_at: new Date().toISOString(),
      reviewed_by: "manual",
      reviewed_from: reviewedFrom,
    }
    if (!meta.review_previous_status && thread?.status && thread.status !== "canonical") {
      meta.review_previous_status = thread.status
    }
    return {
      status: "canonical",
      provenance_meta: meta,
    }
  },

  _unreviewThreadPayload(thread) {
    const meta = { ...this._assetProvenance(thread), needs_review: true }
    const restoreStatus = meta.review_previous_status || "draft"
    delete meta.reviewed_at
    delete meta.reviewed_by
    delete meta.reviewed_from
    delete meta.review_previous_status
    return {
      status: restoreStatus,
      provenance_meta: meta,
    }
  },

  _renderStructureEmptyState(kind, subView) {
    const filters = this._structureFilterFor(subView)
    const filteredDeepImport = filters.source === "deep_import" || Boolean(filters.workflow_id)
    const detail = filteredDeepImport
      ? "结构分析不完整或无匹配结果，可重新分析，或重置筛选查看其他结构资产。"
      : `${kind}用于整理深度导入和人工维护后的叙事结构。`
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128204;</div>
        <p>暂无${esc(kind)}。</p>
        <p class="outline-empty-detail">${esc(detail)}</p>
      </div>
    `
  },

  _renderPlotAutoExtractAction() {
    return `
      <button class="btn" data-action="plot-structure-auto-extract">剧情线自动提取</button>
    `
  },

  _threadDescription(thread) {
    return thread?.description || thread?.summary || thread?.visible_goal || thread?.hidden_truth || "-"
  },

  _arcDescription(arc) {
    return arc?.description || arc?.summary || arc?.arc_goal || arc?.core_conflict || "-"
  },

  _renderThreads() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = `
      <div class="outline-actions-bar">
        <button class="btn btn-primary" data-action="create-thread">新建剧情线</button>
        ${this._renderPlotAutoExtractAction()}
      </div>
      ${this._renderStructureFilters("threads")}
    `

    if (this._threads.length === 0) {
      return html + this._renderStructureEmptyState("剧情线", "threads")
    }
    const scope = "outline-threads"
    const ids = this._threads.map((item) => item.id || item.thread_id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)

    html += renderBulkToolbar(this, scope, [
      { action: "review-threads", label: "批量复核通过", className: "btn-primary" },
      { action: "delete-threads", label: "批量删除", className: "btn-danger" },
    ], { noun: "剧情线" }) + `
      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前剧情线")}</th>
            <th>状态</th>
            <th>名称</th>
            <th>类型</th>
            <th>标记</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const t of this._threads) {
      const statusMap = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      const safeStatus = allowedStatuses.has(t.status) ? t.status : "draft"
      const statusClass = `badge-${safeStatus}`
      html += `
        <tr class="outline-structure-row" data-id="${esc(t.id || t.thread_id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, t.id || t.thread_id, `选择 ${t.name || t.title || "剧情线"}`)}</td>
          <td data-label="状态"><span class="badge ${statusClass}">${statusMap[safeStatus] || esc(safeStatus)}</span></td>
          <td data-label="名称">${esc(t.name || t.title)}</td>
          <td data-label="类型" class="outline-asset-meta">${esc(t.thread_type || "-")}</td>
          <td data-label="标记">${this._renderStructureAssetBadges(t) || "-"}</td>
          <td data-label="描述" class="outline-asset-description">${esc(this._threadDescription(t))}</td>
          <td data-label="操作">
            ${this._renderThreadReviewAction(t)}
            <button class="btn btn-sm btn-primary" data-action="edit-thread" data-id="${esc(t.id || t.thread_id)}">编辑</button>
            ${renderActionMenu(`thread-actions-${esc(t.id || t.thread_id)}`, [
              { action: "delete-thread", label: "删除", class: "danger", data: { id: t.id || t.thread_id } },
            ])}
          </td>
        </tr>
      `
    }

    html += "</tbody></table>"
    html += this._renderStructurePagination("threads")
    return html
  },

  _renderArcs() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = `
      <div class="outline-actions-bar">
        <button class="btn btn-primary" data-action="create-arc">新建篇章纲</button>
        ${this._renderPlotAutoExtractAction()}
      </div>
      ${this._renderStructureFilters("arcs")}
    `

    if (this._arcs.length === 0) {
      return html + this._renderStructureEmptyState("篇章纲", "arcs")
    }
    const scope = "outline-arcs"
    const ids = this._arcs.map((item) => item.id || item.arc_id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)

    html += renderBulkToolbar(this, scope, [
      { action: "delete-arcs", label: "批量删除", className: "btn-danger" },
    ], { noun: "篇章纲" }) + `
      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前篇章纲")}</th>
            <th>状态</th>
            <th>名称</th>
            <th>章节范围</th>
            <th>标记</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const a of this._arcs) {
      const statusMap = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      const safeStatus = allowedStatuses.has(a.status) ? a.status : "draft"
      const statusClass = `badge-${safeStatus}`
      const range = a.start_chapter != null && a.end_chapter != null
        ? `${a.start_chapter}-${a.end_chapter}`
        : "-"
      html += `
        <tr class="outline-structure-row" data-id="${esc(a.id || a.arc_id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, a.id || a.arc_id, `选择 ${a.name || a.title || "篇章纲"}`)}</td>
          <td data-label="状态"><span class="badge ${statusClass}">${statusMap[safeStatus] || esc(safeStatus)}</span></td>
          <td data-label="名称">${esc(a.name || a.title)}</td>
          <td data-label="章节范围" class="outline-asset-mono">${esc(range)}</td>
          <td data-label="标记">${this._renderStructureAssetBadges(a) || "-"}</td>
          <td data-label="描述" class="outline-asset-description">${esc(this._arcDescription(a))}</td>
          <td data-label="操作">
            <button class="btn btn-sm btn-primary" data-action="edit-arc" data-id="${esc(a.id || a.arc_id)}">编辑</button>
            ${renderActionMenu(`arc-actions-${esc(a.id || a.arc_id)}`, [
              { action: "delete-arc", label: "删除", class: "danger", data: { id: a.id || a.arc_id } },
            ])}
          </td>
        </tr>
      `
    }

    html += "</tbody></table>"
    html += this._renderStructurePagination("arcs")
    return html
  },

  _renderForeshadowing() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = `
      <div class="outline-actions-bar">
        <button class="btn btn-primary" data-action="create-foreshadowing">新建伏笔</button>
        ${this._renderPlotAutoExtractAction()}
      </div>
      ${this._renderStructureFilters("foreshadowing")}
    `

    if (this._foreshadowing.length === 0) {
      return html + this._renderStructureEmptyState("伏笔", "foreshadowing")
    }

    const scope = "outline-foreshadowing"
    const ids = this._foreshadowing.map((item) => item.id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)
    let tableHtml = renderBulkToolbar(this, scope, [
      { action: "delete-foreshadowing", label: "批量删除", className: "btn-danger" },
    ], { noun: "伏笔" })
    tableHtml += `<table class="data-table table-card-list"><thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前伏笔")}</th><th>状态</th><th>描述</th><th>目标章节</th><th>标记</th><th>操作</th></tr></thead><tbody>`
    for (const f of this._foreshadowing) {
      const st = FORESHADOWING_STATUS_LABELS[f.status] || f.status
      const description = f.summary || f.name || "-"
      tableHtml += `<tr class="outline-structure-row" data-id="${esc(f.id)}">
        <td class="selection-cell">${renderSelectionCell(this, scope, f.id, `选择 ${description}`)}</td>
        <td data-label="状态"><span class="badge badge-${esc(f.status || "planted")}">${esc(st)}</span></td>
        <td data-label="描述" class="outline-asset-description">${esc(description)}</td>
        <td data-label="目标章节" class="outline-asset-mono">${f.planned_seed_chapter != null ? esc(String(f.planned_seed_chapter)) : "-"}</td>
        <td data-label="标记">${this._renderStructureAssetBadges(f) || "-"}</td>
        <td data-label="操作">
          <select class="form-select foreshadowing-status-select outline-status-select" data-id="${esc(f.id)}">
            ${FORESHADOWING_STATUSES.map((s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${FORESHADOWING_STATUS_LABELS[s] || s}</option>`).join("")}
          </select>
          <button class="btn btn-sm btn-primary" data-action="edit-foreshadowing" data-id="${esc(f.id)}">编辑</button>
          ${renderActionMenu(`foreshadowing-actions-${esc(f.id)}`, [
            { action: "delete-foreshadowing", label: "删除", class: "danger", data: { id: f.id } },
          ])}
        </td>
      </tr>`
    }
    tableHtml += '</tbody></table>'
    tableHtml += this._renderStructurePagination("foreshadowing")
    return html + tableHtml
  },

  _renderReveals() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = `
      <div class="outline-actions-bar">
        <button class="btn btn-primary" data-action="create-reveal">新建揭示</button>
        ${this._renderPlotAutoExtractAction()}
      </div>
      ${this._renderStructureFilters("reveals")}
    `

    if (this._reveals.length === 0) {
      return html + this._renderStructureEmptyState("揭示", "reveals")
    }

    const scope = "outline-reveals"
    const ids = this._reveals.map((item) => item.id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)
    html += renderBulkToolbar(this, scope, [
      { action: "delete-reveals", label: "批量删除", className: "btn-danger" },
    ], { noun: "揭示" })
    html += `<table class="data-table table-card-list"><thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前揭示")}</th><th>状态</th><th>描述</th><th>揭示章节</th><th>标记</th><th>操作</th></tr></thead><tbody>`
    for (const r of this._reveals) {
      const st = REVEAL_STATUS_LABELS[r.status] || r.status || "计划中"
      const revealChapter = (r.reveal_stages && r.reveal_stages[0] && r.reveal_stages[0].chapter_index) || "-"
      html += `<tr class="outline-structure-row" data-id="${esc(r.id)}">
        <td class="selection-cell">${renderSelectionCell(this, scope, r.id, "选择揭示")}</td>
        <td data-label="状态"><span class="badge badge-${esc(r.status || "planned")}">${esc(st)}</span></td>
        <td data-label="描述" class="outline-asset-description">${esc(r.secret_summary || "-")}</td>
        <td data-label="揭示章节" class="outline-asset-mono">${revealChapter !== "-" ? esc(String(revealChapter)) : "-"}</td>
        <td data-label="标记">${this._renderStructureAssetBadges(r) || "-"}</td>
        <td data-label="操作">
          <select class="form-select reveal-status-select outline-status-select" data-id="${esc(r.id)}">
            ${REVEAL_STATUSES.map((s) => `<option value="${s}" ${r.status === s ? "selected" : ""}>${REVEAL_STATUS_LABELS[s] || s}</option>`).join("")}
          </select>
          <button class="btn btn-sm btn-primary" data-action="edit-reveal" data-id="${esc(r.id)}">编辑</button>
          ${renderActionMenu(`reveal-actions-${esc(r.id)}`, [
            { action: "delete-reveal", label: "删除", class: "danger", data: { id: r.id } },
          ])}
        </td>
      </tr>`
    }
    html += '</tbody></table>'
    html += this._renderStructurePagination("reveals")
    return html
  },

  _showCreateForeshadowingForm() {
    const defaultChapter = this._guessLastChapter() || 1
    const statusOptions = FORESHADOWING_STATUSES.map(
      (s) => `<option value="${s}">${FORESHADOWING_STATUS_LABELS[s] || s}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="create-foreshadowing-description" rows="3" placeholder="伏笔描述"></textarea>
      </div>
      <div class="form-group">
        <label>目标章节</label>
        <input class="form-input" id="create-foreshadowing-target-chapter" type="number" min="1" value="${defaultChapter}" />
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="create-foreshadowing-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("新建伏笔", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const description = document.getElementById("create-foreshadowing-description")?.value?.trim()
        if (!description) { toast("请输入描述", "warning"); return }
        const targetChapter = parseInt(document.getElementById("create-foreshadowing-target-chapter")?.value || "1", 10)
        try {
          await api.outline.createForeshadowing(state.currentProjectId, {
            name: description,
            summary: description,
            planned_seed_chapter: Number.isInteger(targetChapter) && targetChapter >= 1 ? targetChapter : 1,
            status: document.getElementById("create-foreshadowing-status")?.value || "planted",
          })
          toast("伏笔已创建", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "创建失败", "error")
        }
      },
    }])
  },

  _editForeshadowing(id) {
    const f = this._foreshadowing.find((item) => item.id === id)
    if (!f) return

    const description = f.summary || f.name || ""
    const targetChapter = f.planned_seed_chapter || this._guessLastChapter() || 1
    const statusOptions = FORESHADOWING_STATUSES.map(
      (s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${FORESHADOWING_STATUS_LABELS[s] || s}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="edit-foreshadowing-description" rows="3">${esc(description)}</textarea>
      </div>
      <div class="form-group">
        <label>目标章节</label>
        <input class="form-input" id="edit-foreshadowing-target-chapter" type="number" min="1" value="${targetChapter}" />
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="edit-foreshadowing-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("编辑伏笔", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        const description = document.getElementById("edit-foreshadowing-description")?.value?.trim()
        if (!description) { toast("请输入描述", "warning"); return }
        const targetChapter = parseInt(document.getElementById("edit-foreshadowing-target-chapter")?.value || "1", 10)
        try {
          await api.outline.updateForeshadowing(id, state.currentProjectId, {
            name: description,
            summary: description,
            planned_seed_chapter: Number.isInteger(targetChapter) && targetChapter >= 1 ? targetChapter : 1,
            status: document.getElementById("edit-foreshadowing-status")?.value || "planted",
          })
          toast("伏笔已保存", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "保存失败", "error")
        }
      },
    }])
  },

  async _deleteForeshadowing(id) {
    confirmAction("确定删除此伏笔？", async () => {
      try {
        await api.outline.deleteForeshadowing(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) {
        toast(err.message || "删除失败", "error")
      }
    })
  },

  _showCreateRevealForm() {
    const defaultChapter = this._guessLastChapter() || 1
    const statusOptions = REVEAL_STATUSES.map(
      (s) => `<option value="${s}">${REVEAL_STATUS_LABELS[s] || s}</option>`
    ).join("")
    const foreshadowingOptions = this._buildForeshadowingOptions()

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="create-reveal-description" rows="3" placeholder="揭示的秘密"></textarea>
      </div>
      <div class="form-group">
        <label>揭示章节 *</label>
        <input class="form-input" id="create-reveal-chapter" type="number" min="1" value="${defaultChapter}" />
      </div>
      <div class="form-group">
        <label>关联伏笔（可选）</label>
        <select class="form-select" id="create-reveal-foreshadowing-id"><option value="">- 无 -</option>${foreshadowingOptions}</select>
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="create-reveal-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("新建揭示", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const description = document.getElementById("create-reveal-description")?.value?.trim()
        const chapterValue = document.getElementById("create-reveal-chapter")?.value
        if (!description) { toast("请输入描述", "warning"); return }
        const chapterIndex = parseInt(chapterValue || "1", 10)
        if (!Number.isInteger(chapterIndex) || chapterIndex < 1) {
          toast("揭示章节必须大于 0", "warning")
          return
        }
        try {
          await api.outline.createReveal(state.currentProjectId, {
            target_type: "world_entity",
            target_id: "00000000-0000-0000-0000-000000000000",
            secret_summary: description,
            reveal_stages: [{
              stage_index: 0,
              chapter_index: chapterIndex,
              reveal_content: description,
            }],
            status: document.getElementById("create-reveal-status")?.value || "planned",
          })
          toast("揭示已创建", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "创建失败", "error")
        }
      },
    }])
  },

  _editReveal(id) {
    const r = this._reveals.find((item) => item.id === id)
    if (!r) return

    const description = r.secret_summary || ""
    const revealChapter = (r.reveal_stages && r.reveal_stages[0] && r.reveal_stages[0].chapter_index) || this._guessLastChapter() || 1
    const statusOptions = REVEAL_STATUSES.map(
      (s) => `<option value="${s}" ${r.status === s ? "selected" : ""}>${REVEAL_STATUS_LABELS[s] || s}</option>`
    ).join("")
    const foreshadowingOptions = this._buildForeshadowingOptions()

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="edit-reveal-description" rows="3">${esc(description)}</textarea>
      </div>
      <div class="form-group">
        <label>揭示章节 *</label>
        <input class="form-input" id="edit-reveal-chapter" type="number" min="1" value="${revealChapter}" />
      </div>
      <div class="form-group">
        <label>关联伏笔（可选）</label>
        <select class="form-select" id="edit-reveal-foreshadowing-id"><option value="">- 无 -</option>${foreshadowingOptions}</select>
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="edit-reveal-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("编辑揭示", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        const description = document.getElementById("edit-reveal-description")?.value?.trim()
        const chapterValue = document.getElementById("edit-reveal-chapter")?.value
        if (!description) { toast("请输入描述", "warning"); return }
        const chapterIndex = parseInt(chapterValue || "1", 10)
        if (!Number.isInteger(chapterIndex) || chapterIndex < 1) {
          toast("揭示章节必须大于 0", "warning")
          return
        }
        try {
          await api.outline.updateReveal(id, state.currentProjectId, {
            secret_summary: description,
            reveal_stages: [{
              stage_index: 0,
              chapter_index: chapterIndex,
              reveal_content: description,
            }],
            status: document.getElementById("edit-reveal-status")?.value || "planned",
          })
          toast("揭示已保存", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "保存失败", "error")
        }
      },
    }])
  },

  async _deleteReveal(id) {
    confirmAction("确定删除此揭示？", async () => {
      try {
        await api.outline.deleteReveal(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) {
        toast(err.message || "删除失败", "error")
      }
    })
  },

  _guessLastChapter() {
    let maxChapter = 0
    for (const f of this._foreshadowing) {
      if (f.planned_seed_chapter > maxChapter) maxChapter = f.planned_seed_chapter
      if (f.planned_payoff_chapter > maxChapter) maxChapter = f.planned_payoff_chapter
    }
    for (const r of this._reveals) {
      if (r.reveal_stages) {
        for (const stage of r.reveal_stages) {
          if (stage.chapter_index > maxChapter) maxChapter = stage.chapter_index
        }
      }
    }
    for (const a of this._arcs) {
      if (a.end_chapter > maxChapter) maxChapter = a.end_chapter
      if (a.start_chapter > maxChapter) maxChapter = a.start_chapter
    }
    for (const t of this._threads) {
      if (t.planned_payoff_chapter > maxChapter) maxChapter = t.planned_payoff_chapter
      if (t.start_chapter > maxChapter) maxChapter = t.start_chapter
    }
    return maxChapter > 0 ? maxChapter : null
  },

  _buildForeshadowingOptions() {
    return this._foreshadowing.map(
      (f) => `<option value="${esc(f.id)}">${esc(f.summary || f.name || "未命名")}</option>`
    ).join("")
  },

  _showCreateThreadForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-thread-name" placeholder="剧情线名称" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="create-thread-type">
          <option value="main">主线</option>
          <option value="sub">支线</option>
          <option value="background">暗线</option>
        </select>
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="create-thread-desc" rows="3" placeholder="剧情线描述"></textarea>
      </div>
    `
    showModalHtml("新建剧情线", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const name = document.getElementById("create-thread-name")?.value
        if (!name) { toast("请输入名称", "warning"); return }
        try {
          await api.outline.createThread(state.currentProjectId, {
            name,
            thread_type: document.getElementById("create-thread-type")?.value || "main",
            summary: document.getElementById("create-thread-desc")?.value || "",
          })
          toast("剧情线已创建", "success")
          router.refresh()
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _editThread(id) {
    const thread = this._threads.find((t) => (t.id || t.thread_id) === id)
    if (!thread) return

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-thread-name" value="${esc(thread.name || thread.title)}" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="edit-thread-type">
          <option value="main" ${(thread.thread_type || "main") === "main" ? "selected" : ""}>主线</option>
          <option value="sub" ${thread.thread_type === "sub" ? "selected" : ""}>支线</option>
          <option value="background" ${thread.thread_type === "background" ? "selected" : ""}>暗线</option>
        </select>
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="edit-thread-desc" rows="3">${esc(this._threadDescription(thread) === "-" ? "" : this._threadDescription(thread))}</textarea>
      </div>
    `
    showModalHtml("编辑剧情线", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateThread(id, state.currentProjectId, {
            name: document.getElementById("edit-thread-name")?.value,
            thread_type: document.getElementById("edit-thread-type")?.value,
            summary: document.getElementById("edit-thread-desc")?.value,
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _findThread(id) {
    return this._threads.find((thread) => (thread.id || thread.thread_id) === id) || null
  },

  async _markThreadReviewed(id) {
    const thread = this._findThread(id)
    if (!thread) {
      toast("未找到目标剧情线", "error")
      return
    }
    await api.outline.updateThread(
      id,
      state.currentProjectId,
      this._reviewThreadPayload(thread, "outline_threads"),
    )
    toast("剧情线已标记为已复核", "success")
    await this._refreshCurrentSubViewInPlace()
  },

  async _markThreadUnreviewed(id) {
    const thread = this._findThread(id)
    if (!thread) {
      toast("未找到目标剧情线", "error")
      return
    }
    await api.outline.updateThread(
      id,
      state.currentProjectId,
      this._unreviewThreadPayload(thread),
    )
    toast("剧情线已标记为需复核", "success")
    await this._refreshCurrentSubViewInPlace()
  },

  _deleteThread(id) {
    confirmAction("确定删除此剧情线？", async () => {
      try {
        await api.outline.deleteThread(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  _showCreateArcForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-arc-name" placeholder="篇章纲名称" />
      </div>
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="create-arc-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="create-arc-end" type="number" min="1" value="10" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="create-arc-desc" rows="3" placeholder="篇章纲描述"></textarea>
      </div>
    `
    showModalHtml("新建篇章纲", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const title = document.getElementById("create-arc-name")?.value
        if (!title) { toast("请输入名称", "warning"); return }
        try {
          await api.outline.createArc(state.currentProjectId, {
            title,
            start_chapter: parseInt(document.getElementById("create-arc-start")?.value || "1", 10),
            end_chapter: parseInt(document.getElementById("create-arc-end")?.value || "10", 10),
            arc_goal: document.getElementById("create-arc-desc")?.value || "",
          })
          toast("篇章纲已创建", "success")
          router.refresh()
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _editArc(id) {
    const arc = this._arcs.find((a) => (a.id || a.arc_id) === id)
    if (!arc) return

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-arc-name" value="${esc(arc.title || arc.name || "")}" />
      </div>
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="edit-arc-start" type="number" min="1" value="${arc.start_chapter || 1}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="edit-arc-end" type="number" min="1" value="${arc.end_chapter || 10}" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="edit-arc-desc" rows="3">${esc(this._arcDescription(arc) === "-" ? "" : this._arcDescription(arc))}</textarea>
      </div>
    `
    showModalHtml("编辑篇章纲", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateArc(id, state.currentProjectId, {
            title: document.getElementById("edit-arc-name")?.value?.trim(),
            start_chapter: parseInt(document.getElementById("edit-arc-start")?.value || "1", 10),
            end_chapter: parseInt(document.getElementById("edit-arc-end")?.value || "10", 10),
            arc_goal: document.getElementById("edit-arc-desc")?.value?.trim(),
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _deleteArc(id) {
    confirmAction("确定删除此篇章纲？", async () => {
      try {
        await api.outline.deleteArc(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  _showCreateSceneForm() {
    const tagOptions = [
      { value: "draft", label: "草稿（默认）" },
      { value: "hook", label: "钩子" },
      { value: "inciting_incident", label: "激励事件" },
      { value: "rising_action", label: "冲突升级" },
      { value: "climax", label: "阶段高潮" },
      { value: "valley", label: "低谷" },
      { value: "transition", label: "过渡" },
      { value: "payoff", label: "爽点" },
    ]
    const tagSelectHtml = tagOptions.map(
      (o) => `<option value="${o.value}">${o.label}</option>`
    ).join("")

    const maxIdx = this._scenes && this._scenes.length > 0
      ? Math.max(...this._scenes.map((s) => s.scene_index || 0))
      : -1
    const nextIdx = maxIdx + 1

    const formHtml = `
      <div class="form-group">
        <label>序号</label>
        <input class="form-input" id="create-scene-index" type="number" value="${nextIdx}" min="0" />
      </div>
      <div class="form-group">
        <label>标题</label>
        <input class="form-input" id="create-scene-title" placeholder="Scene 标题" />
      </div>
      <div class="form-group">
        <label>叙事标签</label>
        <select class="form-select" id="create-scene-tag">${tagSelectHtml}</select>
      </div>
      <div class="form-group">
        <label>目标</label>
        <textarea class="form-textarea" id="create-scene-goal" rows="2" placeholder="此 Scene 要完成的叙事目标"></textarea>
      </div>
      <div class="form-group">
        <label>核心冲突</label>
        <textarea class="form-textarea" id="create-scene-conflict" rows="2" placeholder="核心冲突描述"></textarea>
      </div>
      <div class="form-group">
        <label>情感节奏</label>
        <input class="form-input" id="create-scene-emotion" placeholder="读者的情感走向" />
      </div>
      <div class="form-group">
        <label>必须发生</label>
        <textarea class="form-textarea" id="create-scene-must-happen" rows="2" placeholder="必须发生的事件"></textarea>
      </div>
      <div class="form-group">
        <label>禁止发生</label>
        <textarea class="form-textarea" id="create-scene-must-not" rows="2" placeholder="禁止发生的事件"></textarea>
      </div>
    `
    showModalHtml("新建 Scene 卡", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        try {
          await api.outline.createScene(state.currentProjectId, {
            scene_index: parseInt(document.getElementById("create-scene-index")?.value || "0", 10),
            title: document.getElementById("create-scene-title")?.value?.trim() || null,
            narrative_tag: document.getElementById("create-scene-tag")?.value || "draft",
            goal: document.getElementById("create-scene-goal")?.value?.trim() || null,
            core_conflict: document.getElementById("create-scene-conflict")?.value?.trim() || null,
            emotional_beat: document.getElementById("create-scene-emotion")?.value?.trim() || null,
            must_happen: document.getElementById("create-scene-must-happen")?.value?.trim() || null,
            must_not_happen: document.getElementById("create-scene-must-not")?.value?.trim() || null,
            source: "manual",
            status: "draft",
          })
          toast("Scene 卡已创建", "success")
          router.refresh()
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _editScene(id) {
    const scene = (this._scenes || []).find((s) => s.id === id)
    if (!scene) return

    const tags = ["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"]
    const tagLabels = { draft: "草稿", hook: "钩子", inciting_incident: "激励事件", rising_action: "冲突升级", climax: "阶段高潮", valley: "低谷", transition: "过渡", payoff: "爽点" }
    const tagSelectHtml = tags.map(
      (t) => `<option value="${t}" ${(scene.narrative_tag || "draft") === t ? "selected" : ""}>${tagLabels[t]}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>序号</label>
        <input class="form-input" id="edit-scene-index" type="number" value="${scene.scene_index || 0}" min="0" />
      </div>
      <div class="form-group">
        <label>标题</label>
        <input class="form-input" id="edit-scene-title" value="${esc(scene.title || "")}" />
      </div>
      <div class="form-group">
        <label>叙事标签</label>
        <select class="form-select" id="edit-scene-tag">${tagSelectHtml}</select>
      </div>
      <div class="form-group">
        <label>目标</label>
        <textarea class="form-textarea" id="edit-scene-goal" rows="2">${esc(scene.goal || "")}</textarea>
      </div>
      <div class="form-group">
        <label>核心冲突</label>
        <textarea class="form-textarea" id="edit-scene-conflict" rows="2">${esc(scene.core_conflict || "")}</textarea>
      </div>
      <div class="form-group">
        <label>情感节奏</label>
        <input class="form-input" id="edit-scene-emotion" value="${esc(scene.emotional_beat || "")}" />
      </div>
      <div class="form-group">
        <label>必须发生</label>
        <textarea class="form-textarea" id="edit-scene-must-happen" rows="2">${esc(scene.must_happen || "")}</textarea>
      </div>
      <div class="form-group">
        <label>禁止发生</label>
        <textarea class="form-textarea" id="edit-scene-must-not" rows="2">${esc(scene.must_not_happen || "")}</textarea>
      </div>
    `
    showModalHtml("编辑 Scene 卡", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateScene(id, state.currentProjectId, {
            scene_index: parseInt(document.getElementById("edit-scene-index")?.value || "0", 10),
            title: document.getElementById("edit-scene-title")?.value?.trim() || null,
            narrative_tag: document.getElementById("edit-scene-tag")?.value || "draft",
            goal: document.getElementById("edit-scene-goal")?.value?.trim() || null,
            core_conflict: document.getElementById("edit-scene-conflict")?.value?.trim() || null,
            emotional_beat: document.getElementById("edit-scene-emotion")?.value?.trim() || null,
            must_happen: document.getElementById("edit-scene-must-happen")?.value?.trim() || null,
            must_not_happen: document.getElementById("edit-scene-must-not")?.value?.trim() || null,
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _deleteScene(id) {
    confirmAction("确定删除此 Scene 卡？删除后标记为 deprecated，正文保留。", async () => {
      try {
        await api.outline.deleteScene(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  async _reorderScenes(sceneIds) {
    try {
      await api.outline.reorderScenes(state.currentProjectId, sceneIds)
      toast("Scene 顺序已更新", "success")
      await this.onEnter?.()
      router.refresh()
    } catch (err) {
      toast(err.message || "操作失败", "error")
    }
  },

  async _generateStructure(startChapter, endChapter) {
    try {
      const confirmation = await confirmAiReference({
        novel_id: state.currentProjectId,
        action: "outline.generate",
        task: "剧情结构生成",
        scope: "full",
        chapter_index: startChapter,
        include_pending_objects: true,
      })
      const result = await api.outline.generate({
        novel_id: state.currentProjectId,
        context_confirmation_id: confirmation.id,
        start_chapter: startChapter,
        end_chapter: endChapter,
      })
      toast("剧情结构生成任务已提交", "success")
      await this.onEnter?.()
      router.refresh()
      return result
    } catch (err) {
      toast(err.message || "操作失败", "error")
      throw err
    }
  },

  async _moveSceneUp(id) {
    const sorted = [...this._scenes].sort((a, b) => (a.scene_index || 0) - (b.scene_index || 0))
    const idx = sorted.findIndex((s) => s.id === id)
    if (idx <= 0) return
    ;[sorted[idx - 1], sorted[idx]] = [sorted[idx], sorted[idx - 1]]
    await this._reorderScenes(sorted.map((s) => s.id))
  },

  async _moveSceneDown(id) {
    const sorted = [...this._scenes].sort((a, b) => (a.scene_index || 0) - (b.scene_index || 0))
    const idx = sorted.findIndex((s) => s.id === id)
    if (idx < 0 || idx >= sorted.length - 1) return
    ;[sorted[idx], sorted[idx + 1]] = [sorted[idx + 1], sorted[idx]]
    await this._reorderScenes(sorted.map((s) => s.id))
  },

  _showPlotStructureAutoExtractForm() {
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="plot-auto-extract-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="plot-auto-extract-end" type="number" min="1" value="10" />
      </div>
    `
    showModalHtml("剧情线自动提取", formHtml, [{
      text: "开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("plot-auto-extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("plot-auto-extract-end")?.value || "10", 10)
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        try {
          const result = await api.imports.startStage("plot_structure", state.currentProjectId, start, end)
          this._plotAutoExtractTaskId = result.task_id
          this._plotAutoExtractMeta = { start_chapter: start, end_chapter: end }
          this._plotAutoExtractProgress = normalizeTaskProgress({
            ...result,
            task_type: "plot_structure_auto_extraction",
            meta: this._plotAutoExtractMeta,
          }, "plot_structure_auto_extraction")
          persistActiveWorkflow({
            taskId: result.task_id,
            workflowType: "plot_structure_auto_extraction",
            label: "剧情线自动提取",
            projectId: state.currentProjectId,
            view: "outline",
            meta: this._plotAutoExtractMeta,
          })
          closeModal()
          toast(`剧情线自动提取任务已提交：${result.task_id || ""}`, "success")
          this._startPlotAutoExtractPolling(result.task_id)
          router.renderCurrentView()
        } catch (err) {
          toast(err.message || "提交失败", "error")
        }
      },
    }])
  },

  _showGenerateStructureForm() {
    this._generateOverlap = { threadCount: 0, arcCount: 0, rangeKey: "" }
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="generate-structure-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="generate-structure-end" type="number" min="1" value="10" />
      </div>
      <div id="generate-structure-warning" class="form-group outline-generate-warning" style="display:none;"></div>
      <div id="generate-structure-confirm-row" class="form-group outline-generate-confirm-row" style="display:none;">
        <label class="outline-generate-confirm-label">
          <input type="checkbox" id="generate-structure-confirm" />
          <span>我已确认，继续生成</span>
        </label>
      </div>
    `
    showModalHtml("AI 生成剧情结构", formHtml, [{
      text: "生成", class: "btn-primary", handler: async () => {
        const start = parseInt(document.getElementById("generate-structure-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("generate-structure-end")?.value || "10", 10)
        if (end < start) { toast("结束章节不能小于起始章节", "warning"); return false }

        const overlap = this._generateOverlap || { threadCount: 0, arcCount: 0 }
        if (overlap.threadCount > 0 || overlap.arcCount > 0) {
          const confirmed = document.getElementById("generate-structure-confirm")?.checked
          if (!confirmed) {
            toast("目标范围已存在结构，请勾选确认后继续", "warning")
            return false
          }
        }

        try {
          await this._generateStructure(start, end)
          return true
        } catch {
          return false
        }
      },
    }])

    setTimeout(() => {
      this._bindGenerateOverlapCheck()
      const startEl = document.getElementById("generate-structure-start")
      const endEl = document.getElementById("generate-structure-end")
      const start = parseInt(startEl?.value || "1", 10)
      const end = parseInt(endEl?.value || "10", 10)
      if (Number.isInteger(start) && Number.isInteger(end)) {
        this._updateGenerateOverlapWarning(start, end)
      }
    }, 0)
  },

  _bindGenerateOverlapCheck() {
    const startEl = document.getElementById("generate-structure-start")
    const endEl = document.getElementById("generate-structure-end")
    if (!startEl || !endEl) return

    const update = () => {
      const start = parseInt(startEl.value || "1", 10)
      const end = parseInt(endEl.value || "10", 10)
      if (Number.isInteger(start) && Number.isInteger(end)) {
        this._updateGenerateOverlapWarning(start, end)
      }
    }

    startEl.addEventListener("input", update)
    endEl.addEventListener("input", update)
  },

  async _updateGenerateOverlapWarning(start, end) {
    const rangeKey = `${start}-${end}`
    if (this._generateOverlap && this._generateOverlap.rangeKey === rangeKey) {
      this._renderGenerateOverlapWarning()
      return
    }

    let threadCount = 0
    let arcCount = 0
    try {
      const [threads, arcs] = await Promise.all([
        api.outline.listThreads(state.currentProjectId),
        api.outline.listArcs(state.currentProjectId),
      ])
      const threadList = (threads && (threads.items || threads)) || []
      const arcList = (arcs && (arcs.items || arcs)) || []
      threadCount = this._countRangeOverlap(threadList, start, end, "start_chapter", "planned_payoff_chapter")
      arcCount = this._countRangeOverlap(arcList, start, end, "start_chapter", "end_chapter")
    } catch (err) {
      // 无法获取重叠数据时静默降级，不阻塞用户操作
      console.warn("检查生成范围重叠失败", err)
    }

    this._generateOverlap = { threadCount, arcCount, rangeKey }
    this._renderGenerateOverlapWarning()
  },

  _countRangeOverlap(items, start, end, startKey, endKey) {
    return items.filter((item) => {
      const s = item[startKey]
      const e = item[endKey]
      if (s == null && e == null) return false
      const itemStart = s != null ? s : e
      const itemEnd = e != null ? e : s
      return itemStart <= end && itemEnd >= start
    }).length
  },

  _renderGenerateOverlapWarning() {
    const warningEl = document.getElementById("generate-structure-warning")
    const confirmRow = document.getElementById("generate-structure-confirm-row")
    if (!warningEl || !confirmRow) return

    const { threadCount = 0, arcCount = 0 } = this._generateOverlap || {}
    if (threadCount > 0 || arcCount > 0) {
      warningEl.innerHTML = esc(`第 ${this._generateOverlap.rangeKey} 章已存在 ${threadCount} 条剧情线、${arcCount} 条篇章纲。继续生成将追加新结构，是否继续？`)
      warningEl.style.display = "block"
      confirmRow.style.display = "block"
    } else {
      warningEl.style.display = "none"
      warningEl.innerHTML = ""
      confirmRow.style.display = "none"
      const cb = document.getElementById("generate-structure-confirm")
      if (cb) cb.checked = false
    }
  },

  _applyStructureFilters() {
    const subView = state.currentSubView || "threads"
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return
    this._structureFilters[subView] = {
      ...this._structureFilterFor(subView),
      status: document.getElementById("outline-filter-status")?.value || "",
      source: document.getElementById("outline-filter-source")?.value || "",
      workflow_id: document.getElementById("outline-filter-workflow-id")?.value?.trim() || "",
      needs_review: document.getElementById("outline-filter-needs-review")?.value || "",
      skip: 0,
    }
    router.refresh()
  },

  _resetStructureFilters() {
    const subView = state.currentSubView || "threads"
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return
    this._structureFilters[subView] = { ...STRUCTURE_FILTER_DEFAULTS }
    router.refresh()
  },

  _changeStructurePage(delta) {
    const subView = state.currentSubView || "threads"
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return
    const filters = this._structureFilterFor(subView)
    const total = this._structureTotals[subView] || 0
    const newSkip = filters.skip + delta * filters.limit
    if (newSkip < 0) return
    if (newSkip >= total) return
    filters.skip = newSkip
    router.refresh()
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "nav-scenes": () => router.navigate("outline", "scenes"),
      "nav-threads": () => router.navigate("outline", "threads"),
      "nav-arcs": () => router.navigate("outline", "arcs"),
      "nav-foreshadowing": () => router.navigate("outline", "foreshadowing"),
      "nav-reveals": () => router.navigate("outline", "reveals"),
      "open-scene-workbench": () => router.navigate("scene", null),
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
      "create-thread": () => this._showCreateThreadForm(),
      "edit-thread": (_e, _t, ctx) => ctx.id && this._editThread(ctx.id),
      "mark-thread-reviewed": (_e, _t, ctx) => ctx.id && this._markThreadReviewed(ctx.id),
      "mark-thread-unreviewed": (_e, _t, ctx) => ctx.id && this._markThreadUnreviewed(ctx.id),
      "delete-thread": (_e, _t, ctx) => ctx.id && this._deleteThread(ctx.id),
      "create-arc": () => this._showCreateArcForm(),
      "edit-arc": (_e, _t, ctx) => ctx.id && this._editArc(ctx.id),
      "delete-arc": (_e, _t, ctx) => ctx.id && this._deleteArc(ctx.id),
      "create-scene": () => this._showCreateSceneForm(),
      "generate-structure": () => this._showGenerateStructureForm(),
      "plot-structure-auto-extract": () => this._showPlotStructureAutoExtractForm(),
      "move-scene-up": (_e, _t, ctx) => ctx.id && this._moveSceneUp(ctx.id),
      "move-scene-down": (_e, _t, ctx) => ctx.id && this._moveSceneDown(ctx.id),
      "edit-scene": (_e, _t, ctx) => ctx.id && this._editScene(ctx.id),
      "delete-scene": (_e, _t, ctx) => ctx.id && this._deleteScene(ctx.id),
      "create-foreshadowing": () => this._showCreateForeshadowingForm(),
      "edit-foreshadowing": (_e, _t, ctx) => ctx.id && this._editForeshadowing(ctx.id),
      "delete-foreshadowing": (_e, _t, ctx) => ctx.id && this._deleteForeshadowing(ctx.id),
      "create-reveal": () => this._showCreateRevealForm(),
      "edit-reveal": (_e, _t, ctx) => ctx.id && this._editReveal(ctx.id),
      "delete-reveal": (_e, _t, ctx) => ctx.id && this._deleteReveal(ctx.id),
      "apply-outline-structure-filters": () => this._applyStructureFilters(),
      "reset-outline-structure-filters": () => this._resetStructureFilters(),
      "prev-outline-structure-page": () => this._changeStructurePage(-1),
      "next-outline-structure-page": () => this._changeStructurePage(1),
    })

    bindActionMenus()

    // 伏笔状态变更：change 事件委托
    document.querySelectorAll(".foreshadowing-status-select").forEach((sel) => {
      sel.onchange = async () => {
        const id = sel.dataset.id
        if (!id) return
        try {
          await api.outline.updateForeshadowing(id, state.currentProjectId, { status: sel.value })
          toast("伏笔状态已更新", "success")
          await this.onEnter()
        } catch (err) { toast(err.message || "更新失败", "error") }
      }
    })
    // 揭示状态变更
    document.querySelectorAll(".reveal-status-select").forEach((sel) => {
      sel.onchange = async () => {
        const id = sel.dataset.id
        if (!id) return
        try {
          await api.outline.updateReveal(id, state.currentProjectId, { status: sel.value })
          toast("揭示状态已更新", "success")
          await this.onEnter()
        } catch (err) { toast(err.message || "更新失败", "error") }
      }
    })
  },

  _visibleIdsForBulkScope(scope) {
    if (scope === "outline-threads") return this._threads.map((item) => item.id || item.thread_id).filter(Boolean)
    if (scope === "outline-arcs") return this._arcs.map((item) => item.id || item.arc_id).filter(Boolean)
    if (scope === "outline-foreshadowing") return this._foreshadowing.map((item) => item.id).filter(Boolean)
    if (scope === "outline-reveals") return this._reveals.map((item) => item.id).filter(Boolean)
    return []
  },

  _itemsForBulkScope(scope) {
    const selection = getBulkSelection(this, scope)
    if (scope === "outline-threads") return selectedItemsFrom(this._threads, selection, (item) => item.id || item.thread_id)
    if (scope === "outline-arcs") return selectedItemsFrom(this._arcs, selection, (item) => item.id || item.arc_id)
    if (scope === "outline-foreshadowing") return selectedItemsFrom(this._foreshadowing, selection)
    if (scope === "outline-reveals") return selectedItemsFrom(this._reveals, selection)
    return []
  },

  _toggleBulkOne(input) {
    toggleBulkSelection(this, input.getAttribute("data-scope"), input.getAttribute("data-id"), input.checked)
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
    if (!items.length) {
      toast("请先选择要处理的项目", "warning")
      return
    }
    const labels = {
      "delete-threads": "批量删除剧情线",
      "review-threads": "批量复核剧情线",
      "delete-arcs": "批量删除篇章纲",
      "delete-foreshadowing": "批量删除伏笔",
      "delete-reveals": "批量删除揭示",
    }
    const confirmText = action === "review-threads" ? "确认复核" : "确认删除"
    confirmAction(`确定对选中的 ${items.length} 项执行「${labels[action] || "批量删除"}」吗？`, async () => {
      await this._executeBulkAction(scope, action, items)
    }, confirmText)
  },

  async _executeBulkAction(scope, action, items) {
    const labels = {
      "delete-threads": "批量删除剧情线",
      "review-threads": "批量复核剧情线",
      "delete-arcs": "批量删除篇章纲",
      "delete-foreshadowing": "批量删除伏笔",
      "delete-reveals": "批量删除揭示",
    }
    const result = await runBulkAction(items, async (item) => {
      if (action === "delete-threads") await api.outline.deleteThread(item.id || item.thread_id, state.currentProjectId)
      else if (action === "review-threads") {
        await api.outline.updateThread(
          item.id || item.thread_id,
          state.currentProjectId,
          this._reviewThreadPayload(item, "outline_threads_bulk"),
        )
      }
      else if (action === "delete-arcs") await api.outline.deleteArc(item.id || item.arc_id, state.currentProjectId)
      else if (action === "delete-foreshadowing") await api.outline.deleteForeshadowing(item.id, state.currentProjectId)
      else if (action === "delete-reveals") await api.outline.deleteReveal(item.id, state.currentProjectId)
    })
    toast(bulkResultMessage(result, labels[action] || "批量删除", (item) => item.name || item.title || item.summary || item.secret_summary || item.id), result.failed.length ? "warning" : "success")
    clearBulkSelection(this, scope)
    await this._refreshCurrentSubViewInPlace()
  },
}

router.registerView("outline", outlineView)
window.outlineView = outlineView
export default outlineView
