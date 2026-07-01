/**
 * 世界对象视图
 */
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { buildMapUrl } from "./mapRouteContext.js"

const WORLD_FILTER_DEFAULTS = {
  entity_type: "",
  status: "",
  q: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  auto_ingested: "",
  skip: 0,
  limit: 20,
}

const worldView = {
  /** @type {Array} */
  _entities: [],

  /** @type {Array} */
  _candidates: [],

  /** @type {Array} */
  _batches: [],

  _total: 0,

  _filters: { ...WORLD_FILTER_DEFAULTS },

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
    { value: "draft", label: "草稿" },
    { value: "candidate", label: "候选" },
    { value: "canonical", label: "正史" },
    { value: "deprecated", label: "废弃" },
    { value: "merged", label: "已合并" },
  ],

  /** AI 自动识别状态 */
  _autoExtractOpen: false,
  _autoExtractTaskId: null,
  _autoExtractStatus: "就绪",
  _autoExtractTimer: null,
  _autoExtractProgress: null,
  _autoExtractPoller: null,
  _autoExtractMeta: null,

  async onEnter() {
    this._entities = []
    this._candidates = []
    this._batches = []
    this._total = 0

    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
    this._stopAutoExtractPolling()

    this._recoverAutoExtractWorkflow()

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

  async _loadEntities() {
    this._entities = []
    this._total = 0
    if (!state.currentProjectId) return

    try {
      const params = {
        novel_id: state.currentProjectId,
        skip: this._filters.skip,
        limit: this._filters.limit,
      }
      if (this._filters.entity_type) params.entity_type = this._filters.entity_type
      if (this._filters.status) params.status = this._filters.status
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
    } catch {
      this._entities = []
      this._total = 0
    }
  },

  async _loadCandidates() {
    this._candidates = []
    if (!state.currentProjectId) return

    try {
      const data = await api.world.listEntities({
        novel_id: state.currentProjectId,
        status: "candidate",
        skip: 0,
        limit: 100,
      })
      this._candidates = data.items || data || []
    } catch {
      this._candidates = []
    }
  },

  async _reloadWorldLists() {
    await Promise.all([
      this._loadEntities(),
      this._loadCandidates(),
    ])
  },

  onLeave() {
    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
    this._stopAutoExtractPolling()
  },

  async render() {
    const subView = state.currentSubView || "objects"
    let html = ''

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "objects" ? "active" : ""}" data-subview="objects" data-action="nav-objects">对象库</span>
        <span class="subnav-item ${subView === "candidates" ? "active" : ""}" data-subview="candidates" data-action="nav-candidates">候选清洗</span>
        <span class="subnav-item ${subView === "relations" ? "active" : ""}" data-subview="relations" data-action="nav-relations">关系</span>
        <span class="subnav-item ${subView === "aliases" ? "active" : ""}" data-subview="aliases" data-action="nav-aliases">别名</span>
        <span class="subnav-item ${subView === "map" ? "active" : ""}" data-subview="map" data-action="nav-map">地图</span>
      </div>
    `

    if (subView === "objects") {
      html += this._renderEntityList()
    } else if (subView === "candidates") {
      html += this._renderCandidatesList()
    } else if (subView === "relations") {
      html += await this._renderRelations()
    } else if (subView === "aliases") {
      html += await this._renderAliases()
    } else if (subView === "map") {
      html += this._renderMap()
    }

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  /** 渲染地图子视图容器（mapView 命令式挂载到 #map-root） */
  _renderMap() {
    // 延迟导航，避免在当前 render 周期内递归触发路由渲染导致竞态
    setTimeout(() => router.navigate("map", null), 0)
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128506;</div>
        <p>正在打开地图</p>
        <p style="color:var(--text-dim);font-size:12px;">地图已升级为侧边栏一级功能。</p>
      </div>
    `
  },

  // ============================================================
  // AI 自动识别
  // ============================================================

  _toggleAutoExtract() {
    this._autoExtractOpen = !this._autoExtractOpen
    router.navigate("world", state.currentSubView)
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
        destinationLabel: `范围: ${rangeText}。完成后到候选清洗查看抽取结果。`,
      })
      : `<div id="w-extract-status" style="margin-top:4px;font-size:11px;color:var(--text-dim);">状态: ${esc(this._autoExtractStatus)}</div>`
    const secondaryButton = taskType === "world_entity_extraction"
      ? `<button class="btn btn-sm" data-action="submit-extract" data-type="world_alias_relation_extraction" ${isRunning ? "disabled" : ""}>补抽别名/关系</button>`
      : ""
    return `
      <div style="border:1px solid var(--border);border-radius:4px;padding:10px;margin-bottom:12px;text-align:center;">
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px;">${label}</div>
        <div style="display:flex;gap:8px;justify-content:center;align-items:center;flex-wrap:wrap;">
          起始章 <input id="w-extract-start" type="number" min="1" value="1" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;" />
          结束章 <input id="w-extract-end" type="number" min="1" value="10" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;" />
          <button class="btn btn-sm btn-primary" data-action="submit-extract" data-type="${taskType}" ${isRunning ? "disabled" : ""}>
            ${isRunning ? "识别中..." : "开始识别"}
          </button>
          ${secondaryButton}
        </div>
        <div id="w-extract-progress" style="margin-top:8px;">${progressHtml}</div>
      </div>
    `
  },

  async _submitAutoExtract(taskType) {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const start = parseInt(document.getElementById("w-extract-start")?.value || "1", 10)
    const end = parseInt(document.getElementById("w-extract-end")?.value || "10", 10)
    if (start > end) { toast("起始章节不能大于结束章节", "warning"); return }

    try {
      let result
      if (taskType === "world_alias_relation_extraction") {
        result = await api.world.extractAliasRelations({
          novel_id: state.currentProjectId,
          start_chapter: start,
          end_chapter: end,
        })
      } else {
        const confirmation = await confirmAiReference({
          novel_id: state.currentProjectId,
          action: "world.entities.extract",
          task: "世界对象补抽",
          scope: "chapter",
          chapter_index: start,
          include_pending_objects: true,
        })
        result = await api.world.extractEntities({
          novel_id: state.currentProjectId,
          context_confirmation_id: confirmation.id,
          start_chapter: start,
          end_chapter: end,
        })
      }
      this._autoExtractTaskId = result.task_id
      this._autoExtractStatus = "运行中"
      this._autoExtractMeta = { start_chapter: start, end_chapter: end }
      this._autoExtractProgress = normalizeTaskProgress({
        ...result,
        task_type: taskType,
        meta: this._autoExtractMeta,
      }, taskType)
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: taskType,
        projectId: state.currentProjectId,
        view: "world",
        meta: this._autoExtractMeta,
      })
      this._updateExtractStatusDOM()
      toast("识别任务已提交", "info")
      router.navigate("world", state.currentSubView)

      this._startAutoExtractPolling(result.task_id, taskType)
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
    const workflow = workflows.find((item) => item.workflowType === "world_entity_extraction" && item.view === "world")
      || workflows.find((item) => item.workflowType === "world_entity_extraction")
    if (!workflow?.taskId) return
    this._autoExtractTaskId = workflow.taskId
    this._autoExtractStatus = "运行中"
    this._autoExtractMeta = workflow.meta || this._autoExtractMeta || null
    this._autoExtractProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: "world_entity_extraction",
      status: "running",
      meta: workflow.meta || {},
    }, "world_entity_extraction")
    this._startAutoExtractPolling(workflow.taskId, "world_entity_extraction")
  },

  _stopAutoExtractPolling() {
    if (this._autoExtractPoller?.stop) this._autoExtractPoller.stop()
    this._autoExtractPoller = null
  },

  _startAutoExtractPolling(taskId, taskType = "world_entity_extraction") {
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
      const progress = normalizeTaskProgress(data, data.task_type || "world_entity_extraction")
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
      toast("识别任务已完成，请查看候选清洗", "success")
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
      const message = progress.cancelled ? "识别任务已取消" : `识别任务失败: ${progress.errorMessage || "未知错误"}`
      toast(message, progress.cancelled ? "warning" : "error")
    }
  },

  _updateExtractStatusDOM() {
    const progressEl = document.getElementById("w-extract-progress")
    if (progressEl && this._autoExtractProgress) {
      const rangeText = this._autoExtractMeta
        ? `范围: 章节 ${this._autoExtractMeta.start_chapter || 1}-${this._autoExtractMeta.end_chapter || 10}。完成后到候选清洗查看抽取结果。`
        : "完成后到候选清洗查看抽取结果。"
      progressEl.innerHTML = renderWorkflowCard(this._autoExtractProgress, {
        title: "从章节正文中识别世界对象",
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
        <div style="text-align:center;margin-bottom:12px;">
          <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
          <button class="btn" data-action="toggle-extract" style="margin-left:8px;">${this._autoExtractOpen ? "▾" : "▸"} 自动识别</button>
        </div>
        ${this._autoExtractOpen ? this._renderAutoExtractPanel("world_entity_extraction", "从章节正文中识别世界对象") : ""}
        ${this._renderFilters()}
        <div class="empty-state">
          <div class="empty-icon">&#127758;</div>
          <p>还没有世界对象。</p>
          <p>世界对象是小说世界中的核心创作资产，包括地点、组织、物品、事件等。</p>
        </div>
      `
    }

    let html = `
      <div style="text-align:center;margin-bottom:12px;">
        <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
        <button class="btn" data-action="toggle-extract" style="margin-left:8px;">
          ${this._autoExtractOpen ? "▾" : "▸"} 自动识别
        </button>
      </div>
      ${this._autoExtractOpen ? this._renderAutoExtractPanel("world_entity_extraction", "从章节正文中识别世界对象") : ""}
      <div style="margin-bottom:8px;text-align:center;">
        <button class="btn btn-sm" data-action="nav-candidates">候选清洗（${this._candidates.length}）</button>
      </div>
    `

    html += this._renderFilters()

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
        html += `<div style="margin-bottom:12px;">`
        html += `<details open style="border:1px solid var(--border);border-radius:4px;overflow:hidden;">`
        html += `<summary style="padding:6px 10px;background:var(--bg-alt);cursor:pointer;font-size:13px;font-weight:600;">
          <span style="color:var(--accent);">&#9733;</span> 自动入库 — ${this._formatBatchTime(this._batches[0]?.ingested_at)} — ${autoEntities.length} 个对象
        </summary>`
        html += this._renderEntityTable(autoEntities, { showNewBadge: true })
        html += `</details></div>`
      }

      // 渲染手动创建区
      if (manualEntities.length > 0) {
        html += `<details ${!autoEntities.length > 0 ? "open" : ""} style="border:1px solid var(--border);border-radius:4px;overflow:hidden;">`
        html += `<summary style="padding:6px 10px;background:var(--bg-alt);cursor:pointer;font-size:13px;font-weight:600;">
          其他对象 — ${manualEntities.length} 个
        </summary>`
        html += this._renderEntityTable(manualEntities, { showNewBadge: false })
        html += `</details>`
      }
    } else {
      // 没有自动入库记录，用普通表格
      html += this._renderEntityTable(this._entities, { showNewBadge: false })
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
      `<option value="">全部状态</option>`,
      ...this._statuses.map((s) => `<option value="${esc(s.value)}" ${this._filters.status === s.value ? "selected" : ""}>${esc(s.label)}</option>`),
    ].join("")
    const sourceOptions = [
      `<option value="">全部来源</option>`,
      `<option value="deep_import" ${this._filters.source === "deep_import" ? "selected" : ""}>深度导入</option>`,
      `<option value="manual" ${this._filters.source === "manual" ? "selected" : ""}>手动</option>`,
      `<option value="ai_generated" ${this._filters.source === "ai_generated" ? "selected" : ""}>AI 生成</option>`,
    ].join("")
    return `
      <div class="world-object-filters">
        <select class="form-select" id="filter-entity-type">${typeOptions}</select>
        <select class="form-select" id="filter-status">${statusOptions}</select>
        <select class="form-select" id="filter-source">${sourceOptions}</select>
        <input class="form-input" id="filter-workflow-id" value="${esc(this._filters.workflow_id || "")}" placeholder="workflow_id" />
        <select class="form-select" id="filter-needs-review">
          <option value="">全部复核</option>
          <option value="true" ${this._filters.needs_review === "true" ? "selected" : ""}>需复核</option>
          <option value="false" ${this._filters.needs_review === "false" ? "selected" : ""}>无需复核</option>
        </select>
        <select class="form-select" id="filter-auto-ingested">
          <option value="">全部入库方式</option>
          <option value="true" ${this._filters.auto_ingested === "true" ? "selected" : ""}>自动入库</option>
          <option value="false" ${this._filters.auto_ingested === "false" ? "selected" : ""}>非自动入库</option>
        </select>
        <input class="form-input world-object-filters__search" id="filter-q" type="search" placeholder="名称/别名搜索" value="${esc(this._filters.q)}" />
        <button class="btn btn-sm btn-primary" data-action="apply-filters">应用</button>
        <button class="btn btn-sm" data-action="reset-filters">重置</button>
      </div>
    `
  },

  _renderPagination() {
    if (this._total <= this._filters.limit) return ""
    const currentPage = Math.floor(this._filters.skip / this._filters.limit) + 1
    const totalPages = Math.ceil(this._total / this._filters.limit)
    const prevDisabled = this._filters.skip <= 0 ? "disabled" : ""
    const nextDisabled = this._filters.skip + this._filters.limit >= this._total ? "disabled" : ""
    return `
      <div style="display:flex;gap:8px;justify-content:center;align-items:center;margin-top:12px;">
        <button class="btn btn-sm" data-action="prev-page" ${prevDisabled}>上一页</button>
        <span style="font-size:12px;color:var(--text-dim);">第 ${currentPage} / ${totalPages} 页，共 ${this._total} 条</span>
        <button class="btn btn-sm" data-action="next-page" ${nextDisabled}>下一页</button>
      </div>
    `
  },

  _formatBatchTime(isoStr) {
    if (!isoStr) return ""
    try {
      const d = new Date(isoStr)
      const pad = (n) => String(n).padStart(2, "0")
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    } catch { return isoStr }
  },

  _renderEntityTable(entities, { showNewBadge }) {
    let html = `<table class="data-table" style="border-top:none;">
      <thead>
        <tr>
          <th>状态</th>
          <th>类型</th>
          <th>名称</th>
          <th>来源</th>
          <th>复核</th>
          <th>重要度</th>
          <th>摘要</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
    `

    for (const e of entities) {
      const statusClass = `badge-${e.status || "canonical"}`
      const statusText = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃", merged: "已合并" }
      const sourceText = { deep_import: "深度导入", manual: "手动", ai_generated: "AI 生成" }
      const reviewText = e.needs_review ? "需复核" : "已复核"
      const isNew = showNewBadge ? ' <span class="badge badge-new" style="font-size:10px;background:var(--accent);color:#fff;padding:1px 4px;border-radius:2px;">新</span>' : ""
      const isCharacter = (e.entity_type === "character" || e.entity_type === "character_ref")
      const canMerge = e.status === "draft" || e.status === "candidate"
      const canPromote = e.status === "draft" || e.status === "candidate"
      html += `
        <tr data-id="${esc(e.id || e.entity_id)}" class="clickable">
          <td><span class="badge ${statusClass}">${statusText[e.status] || esc(e.status)}</span></td>
          <td style="color:var(--accent-dim);font-family:var(--font-mono);font-size:12px;">${esc(e.entity_type || "-")}</td>
          <td>${esc(e.name)}${isNew}</td>
          <td style="color:var(--text-muted);font-size:12px;">${esc(sourceText[e.source] || e.source || "-")}</td>
          <td style="color:${e.needs_review ? "var(--warning)" : "var(--text-muted)"};font-size:12px;">${reviewText}</td>
          <td>${esc(e.importance || e.importance_score || "-")}</td>
          <td style="color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(e.summary || e.public_info || "-")}</td>
          <td>
            <button class="btn btn-sm" data-action="edit-entity" data-id="${esc(e.id || e.entity_id)}">编辑</button>
            <button class="btn btn-sm" data-action="open-entity-map" data-id="${esc(e.id || e.entity_id)}">打开地图</button>
            ${canPromote ? `<button class="btn btn-sm btn-primary" data-action="promote-entity" data-id="${esc(e.id || e.entity_id)}">提升为正史</button>` : ""}
            ${canMerge ? `<button class="btn btn-sm" data-action="merge-entity" data-id="${esc(e.id || e.entity_id)}">合并</button>` : ""}
            <button class="btn btn-sm" data-action="rollback-entity" data-id="${esc(e.id || e.entity_id)}">回滚</button>
            ${isCharacter ? `<button class="btn btn-sm" data-action="knowledge-entity" data-id="${esc(e.id || e.entity_id)}">知识</button>` : ""}
            <button class="btn btn-sm btn-danger" data-action="delete-entity" data-id="${esc(e.id || e.entity_id)}">删除</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    return html
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

  _renderCandidatesList() {
    if (this._candidates.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <p>没有待处理的候选对象。</p>
          <p>AI 从文本中抽取的候选对象会出现在这里，你可以决定如何处置它们。</p>
        </div>
      `
    }

    const actionMap = {
      create_new: "创建新对象",
      link_to_existing: "作为别名",
      alias_of_existing: "作为别名",
      merge_with_existing: "合并到已有",
      temporary_only: "设为临时",
      ignore: "忽略",
      needs_user_decision: "需用户决定",
    }
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        以下是从文本中抽取的候选对象。请检查并决定如何处理。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>重要度</th>
            <th>建议动作</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const c of this._candidates) {
      const id = c.id || c.entity_id
      const action = this._candidateAction(c)
      const targetName = this._candidateTargetName(c)
      let actionLabel = actionMap[action] || action
      if (targetName && ["link_to_existing", "alias_of_existing"].includes(action)) {
        actionLabel = `作为${targetName}别名`
      } else if (targetName && action === "merge_with_existing") {
        actionLabel = `合并到${targetName}`
      }
      const isTemporary = action === "temporary_only"
      const canAccept = !["temporary_only", "ignore", "link_to_existing", "alias_of_existing", "merge_with_existing"].includes(action)
      const canMerge = ["link_to_existing", "alias_of_existing", "merge_with_existing"].includes(action)
      html += `
        <tr data-id="${esc(id)}">
          <td>${esc(c.name)}</td>
          <td style="color:var(--accent-dim);font-family:var(--font-mono)">${esc(c.entity_type)}</td>
          <td>${esc(c.importance || c.importance_score || "-")}</td>
          <td style="color:var(--warning)">${esc(actionLabel)}</td>
          <td style="display:flex;gap:4px;flex-wrap:wrap;">
            ${canAccept ? `<button class="btn btn-sm btn-primary" data-action="accept-candidate" data-id="${esc(id)}">确认</button>` : ""}
            ${canMerge ? `<button class="btn btn-sm" data-action="merge-entity" data-id="${esc(id)}" data-target-name="${esc(targetName)}">合并到</button>` : ""}
            <button class="btn btn-sm ${isTemporary ? "" : "btn-danger"}" data-action="ignore-candidate" data-id="${esc(id)}">${isTemporary ? "设为临时" : "忽略"}</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    return html
  },

  async _renderRelations() {
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        管理世界对象与人物之间的关系。
      </p>
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-relation">新建关系</button>
      </div>
    `
    if (!state.currentProjectId) return html + '<div class="empty-state"><p>请先选择项目。</p></div>'

    try {
      const data = await api.world.listRelationships({ novel_id: state.currentProjectId })
      const rels = data.items || data || []
      if (rels.length === 0) {
        return html + '<div class="empty-state"><p>暂无关系。</p></div>'
      }
      html += `
      <table class="data-table">
        <thead><tr><th>源对象</th><th>关系类型</th><th>目标对象</th><th>状态</th><th>描述</th><th>操作</th></tr></thead>
        <tbody>
      `
      for (const r of rels) {
        const statusLabel = r.status === "candidate" ? "待确认" : "正史"
        const statusClass = r.status === "candidate" ? "badge-warning" : "badge-canonical"
        html += `
        <tr data-id="${esc(r.id || r.relationship_id)}">
          <td style="color:var(--accent-dim);font-size:12px;">${esc(r.source_id || "").slice(0, 8)}...</td>
          <td><span class="badge badge-canonical">${esc(r.relation_type || "-")}</span></td>
          <td style="color:var(--accent-dim);font-size:12px;">${esc(r.target_id || "").slice(0, 8)}...</td>
          <td><span class="badge ${statusClass}">${statusLabel}</span></td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(r.description || "")}</td>
          <td><button class="btn btn-sm btn-danger" data-action="delete-relation" data-id="${esc(r.id || r.relationship_id)}">删除</button></td>
        </tr>`
      }
      html += '</tbody></table>'
    } catch { html += '<div class="empty-state"><p>加载关系失败。</p></div>' }
    return html
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
    showModal("新建关系", formHtml, [{
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

  deleteRelation(relId) {
    confirmAction("确定删除此关系？", async () => {
      try {
        await api.world.deleteRelationship(relId, { novel_id: state.currentProjectId })
        toast("已删除", "success")
        router.navigate("world", "relations")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  async _renderAliases() {
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        管理世界对象的别名、称号和化名。别名不独立创建对象。
      </p>
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-alias">新建别名</button>
      </div>
    `
    if (!state.currentProjectId) return html + '<div class="empty-state"><p>请先选择项目。</p></div>'

    try {
      const data = await api.world.listAliases({ novel_id: state.currentProjectId })
      const aliases = data.items || data || []
      if (aliases.length === 0) {
        return html + '<div class="empty-state"><p>暂无别名。</p></div>'
      }
      const typeMap = { name: "名称", title: "称号", nickname: "昵称", alias: "化名", translation: "译名" }
      html += `
      <table class="data-table">
        <thead><tr><th>对象</th><th>别名</th><th>类型</th><th>状态</th><th>来源</th><th>置信度</th><th>操作</th></tr></thead>
        <tbody>
      `
      for (const a of aliases) {
        const statusLabel = a.status === "candidate" || a.needs_review ? "待确认" : "正史"
        const statusClass = statusLabel === "待确认" ? "badge-warning" : "badge-canonical"
        const sourceLabel = a.source === "deep_import" ? "深度导入" : (a.source || "-")
        html += `
        <tr data-id="${esc(a.id || a.alias_id)}">
          <td style="color:var(--accent-dim);font-size:12px;">${esc(a.entity_name || (a.entity_id || "").slice(0, 8) + "...")}</td>
          <td>${esc(a.alias)}</td>
          <td>${typeMap[a.alias_type] || esc(a.alias_type)}</td>
          <td><span class="badge ${statusClass}">${statusLabel}</span></td>
          <td>${esc(sourceLabel)}</td>
          <td>${a.confidence ? (a.confidence * 100).toFixed(0) + "%" : "-"}</td>
          <td><button class="btn btn-sm btn-danger" data-action="delete-alias" data-entity-id="${esc(a.entity_id)}" data-alias="${esc(a.alias)}">删除</button></td>
        </tr>`
      }
      html += '</tbody></table>'
    } catch { html += '<div class="empty-state"><p>加载别名失败。</p></div>' }
    return html
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
    showModal("新建别名", formHtml, [{
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

  editEntity(id) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === id)
    if (!entity) return

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

    showModal("编辑世界对象", formHtml, [
      {
        text: "保存",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.world.updateEntity(id, {
              name: document.getElementById("edit-entity-name")?.value,
              entity_type: document.getElementById("edit-entity-type")?.value,
              summary: document.getElementById("edit-entity-summary")?.value,
            }, state.currentProjectId)
            toast("已保存", "success")
            router.refresh()
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  deleteEntity(id) {
    confirmAction("确定要删除此世界对象吗？此操作不可撤销。", async () => {
      try {
        await api.world.deleteEntity(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) {
        toast(`删除失败：${err.message}`, "error")
      }
    }, "确认删除")
  },

  promoteEntity(id) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === id)
    if (!entity) return

    confirmAction(
      `确定将 "${esc(entity.name)}" 提升为正史吗？提升后将作为正式世界对象参与后续创作。`,
      async () => {
        try {
          await api.world.promoteEntity(id, state.currentProjectId)
          toast("已提升为正史", "success")
          router.refresh()
        } catch (err) {
          toast(`提升失败：${err.message}`, "error")
        }
      },
      "确认提升为正史",
    )
  },

  async acceptCandidate(id) {
    const candidate = this._candidates.find((c) => (c.id || c.entity_id) === id)
    if (!candidate) return

    confirmAction(
      `确定将 "${esc(candidate.name)}" 提升为正史吗？`,
      async () => {
        try {
          await api.world.promoteEntity(id, state.currentProjectId)
          toast(`候选 "${candidate.name}" 已确认`, "success")
          await this._reloadWorldLists()
          router.navigate("world", "candidates")
        } catch (err) {
          toast(`处理失败：${err.message}`, "error")
        }
      },
      "确认提升为正史",
    )
  },

  async ignoreCandidate(id) {
    const candidate = this._candidates.find((c) => (c.id || c.entity_id) === id)
    const isTemporary = this._candidateAction(candidate) === "temporary_only"
    confirmAction(
      isTemporary
        ? `将候选 "${candidate?.name || id}" 标记为临时并从候选清洗中移除？`
        : `确定忽略候选 "${candidate?.name || id}"？`,
      async () => {
        try {
          await api.world.updateEntity(id, { status: "ignored" }, state.currentProjectId)
          toast(isTemporary ? "已设为临时" : "已忽略", "success")
          await this._reloadWorldLists()
          router.navigate("world", "candidates")
        } catch (err) {
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

  async _applyFilters() {
    const entityType = document.getElementById("filter-entity-type")?.value || ""
    const status = document.getElementById("filter-status")?.value || ""
    const q = document.getElementById("filter-q")?.value || ""
    const source = document.getElementById("filter-source")?.value || ""
    const workflowId = document.getElementById("filter-workflow-id")?.value?.trim() || ""
    const needsReview = document.getElementById("filter-needs-review")?.value || ""
    const autoIngested = document.getElementById("filter-auto-ingested")?.value || ""
    this._filters = {
      ...WORLD_FILTER_DEFAULTS,
      entity_type: entityType,
      status,
      q,
      source,
      workflow_id: workflowId,
      needs_review: needsReview,
      auto_ingested: autoIngested,
      skip: 0,
    }
    await this._loadEntities()
    await router.refresh()
  },

  async _resetFilters() {
    this._filters = { ...WORLD_FILTER_DEFAULTS }
    await this._loadEntities()
    await router.refresh()
  },

  async _changePage(delta) {
    const newSkip = this._filters.skip + delta * this._filters.limit
    if (newSkip < 0) return
    if (newSkip >= this._total) return
    this._filters.skip = newSkip
    await this._loadEntities()
    await router.refresh()
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "nav-objects": () => router.navigate("world", "objects"),
      "nav-candidates": () => router.navigate("world", "candidates"),
      "nav-relations": () => router.navigate("world", "relations"),
      "nav-aliases": () => router.navigate("world", "aliases"),
      "nav-map": () => router.navigate("world", "map"),
      "nav-generate": () => router.navigate("generate"),
      "toggle-extract": () => this._toggleAutoExtract(),
      "submit-extract": (_e, t) => this._submitAutoExtract(t.getAttribute("data-type")),
      "edit-entity": (_e, _t, ctx) => ctx.id && this.editEntity(ctx.id),
      "open-entity-map": (_e, _t, ctx) => ctx.id && this._openEntityMap(ctx.id),
      "delete-entity": (_e, _t, ctx) => ctx.id && this.deleteEntity(ctx.id),
      "accept-candidate": (_e, _t, ctx) => ctx.id && this.acceptCandidate(ctx.id),
      "ignore-candidate": (_e, _t, ctx) => ctx.id && this.ignoreCandidate(ctx.id),
      "promote-entity": (_e, _t, ctx) => ctx.id && this.promoteEntity(ctx.id),
      "merge-entity": (_e, _t, ctx) => ctx.id && this.showMergeForm(ctx.id),
      "rollback-entity": (_e, _t, ctx) => ctx.id && this.showRollbackForm(ctx.id),
      "knowledge-entity": (_e, _t, ctx) => ctx.id && this.showKnowledgeForm(ctx.id),
      "create-relation": () => this.showRelationCreateForm(),
      "delete-relation": (_e, _t, ctx) => ctx.id && this.deleteRelation(ctx.id),
      "create-alias": () => this.showAliasCreateForm(),
      "delete-alias": (_e, t) => { const eid = t.getAttribute("data-entity-id"); const alias = t.getAttribute("data-alias"); if (eid && alias) this.deleteAlias(eid, alias) },
      "apply-filters": () => this._applyFilters(),
      "reset-filters": () => this._resetFilters(),
      "prev-page": () => this._changePage(-1),
      "next-page": () => this._changePage(1),
    })

    document.getElementById("btn-new-entity")?.addEventListener("click", () => this._showCreateForm())
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

    showModal("新建世界对象", formHtml, [
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
            if (err.status === 409 || (err.message && err.message.includes("409"))) {
              let detail = err.detail
              if (typeof detail === "string") {
                try { detail = JSON.parse(detail) } catch { /* keep string */ }
              }
              if (detail && detail.requires_confirmation) {
                const similar = (detail.similar_entities || []).map((s) => s.name).join(", ")
                confirmAction(
                  `发现相似对象：${similar}。是否仍要创建？`,
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
            }
            toast(`创建失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  // ============================================================
  // 合并、回滚与知识边界
  // ============================================================

  showMergeForm(candidateId) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === candidateId)
      || this._candidates.find((e) => (e.id || e.entity_id) === candidateId)
    if (!entity) return

    const formHtml = `
      <p style="margin-bottom:10px;">将 <strong>${esc(entity.name)}</strong> 合并到目标正史对象。</p>
      <div class="form-group">
        <label>目标对象 ID *</label>
        <input class="form-input" id="merge-target-id" placeholder="目标对象 ID" />
      </div>
    `
    showModal("合并对象", formHtml, [{
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
  },

  async _mergeEntity(candidateId, targetId) {
    try {
      await api.world.mergeEntity(candidateId, targetId, state.currentProjectId)
      toast("实体已合并", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "合并失败", "error")
    }
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
    showModal("回滚对象", formHtml, [{
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
    showModal("添加知识边界", formHtml, [{
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
