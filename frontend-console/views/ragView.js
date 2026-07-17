/**
 * 小说检索视图
 *
 * 子标签：检索 | 索引维护
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

const CHARACTER_PAGE_SIZE = 50
const RAG_RESULT_PAGE_SIZE = 20
const RAG_RESULT_FETCH_LIMIT = 100
const RAG_SEARCH_SCOPES = Object.freeze(["manuscript", "world", "outline"])

const ragView = {
  _totalChunks: null,
  _embeddingFailedCount: 0,
  _embeddingDim: null,
  _configuredEmbeddingDim: null,
  _indexedEmbeddingDim: null,
  _embeddingDimensionMismatch: false,
  _embeddingRuntime: { started: false, healthy: false, cache_stats: {} },
  _metrics: null,
  _retryableEmbeddingCount: 0,
  _prewarmState: "idle",
  _prewarmWarning: "",
  _statusWarnings: [],
  _statusDegraded: false,
  _statusItems: [],
  _loading: true,
  _apiAvailable: false,
  _rebuildProgress: null,
  _rebuildInfo: null,
  _rebuildPoller: null,
  _abortController: null,
  _indexFreshness: {},
  _characters: [],
  _scenes: [],
  _searchHits: [],
  _searchVisibleCount: 0,
  _searchTotal: 0,
  _searchResultMeta: null,
  _searchQuery: "",
  _searchAbortController: null,
  _searchGeneration: 0,
  _drawerAbortController: null,
  _drawerGeneration: 0,
  _lastExecutedRouteSignature: "",
  _lastSearchPayload: null,
  _drawerRefs: [],
  _evidenceHealth: null,
  _retrievalTraces: [],
  _retrievalTracesState: "idle",
  _retrievalTracesError: "",
  _taskRetryPending: false,

  async onEnter() {
    this._loading = true
    this._taskRetryPending = false
    this._resetSearchState()
    if (this._abortController) this._abortController.abort()
    this._abortController = new AbortController()
    if (!state.currentProjectId) {
      this._totalChunks = null
      this._apiAvailable = false
      this._loading = false
      return
    }
    try {
      const data = await api.rag.status(state.currentProjectId)
      this._applyStatus(data)
      this._apiAvailable = true
      this._refreshMetrics()
      if (this._totalChunks > 0 && !this._embeddingRuntime?.healthy) {
        this._prewarm({ background: true, signal: this._abortController?.signal })
      }
    } catch {
      this._totalChunks = null
      this._embeddingFailedCount = 0
      this._embeddingDim = null
      this._configuredEmbeddingDim = null
      this._indexedEmbeddingDim = null
      this._embeddingDimensionMismatch = false
      this._embeddingRuntime = { started: false, healthy: false, cache_stats: {} }
      this._metrics = null
      this._retryableEmbeddingCount = 0
      this._prewarmState = "idle"
      this._prewarmWarning = ""
      this._statusWarnings = []
      this._statusDegraded = false
      this._statusItems = []
      this._apiAvailable = false
    }
    this._evidenceHealth = null
    this._retrievalTraces = []
    this._retrievalTracesState = "idle"
    this._retrievalTracesError = ""
    if (api.context?.evidenceHealth) {
      try {
        this._evidenceHealth = await api.context.evidenceHealth(
          state.currentProjectId,
          "canonical",
          24,
        )
      } catch {
        this._evidenceHealth = null
      }
    }
    if (api.world?.listCharacters) {
      try {
        this._characters = await this._loadAllCharacters(state.currentProjectId)
      } catch {
        this._characters = []
      }
    }
    if (api.outline?.listScenesOrdered) {
      try {
        const result = await api.outline.listScenesOrdered(state.currentProjectId)
        this._scenes = Array.isArray(result) ? result : (result?.items || [])
      } catch {
        this._scenes = []
      }
    }
    this._recoverRebuildWorkflow()
    this._loading = false
  },

  async _loadAllCharacters(novelId) {
    const characters = []
    let skip = 0
    while (true) {
      const result = await api.world.listCharacters({
        novel_id: novelId,
        skip,
        limit: CHARACTER_PAGE_SIZE,
      })
      const page = Array.isArray(result) ? result : (result?.items || [])
      characters.push(...page)
      const total = Number(result?.total)
      if (
        !Number.isFinite(total)
        || characters.length >= total
        || page.length < CHARACTER_PAGE_SIZE
      ) {
        return characters
      }
      skip += page.length
    }
  },

  _applyStatus(data = {}) {
    this._totalChunks = data.total || 0
    this._embeddingFailedCount = data.embedding_failed_count || 0
    this._embeddingDim = data.embedding_dim ?? null
    this._configuredEmbeddingDim = data.configured_embedding_dim ?? null
    this._indexedEmbeddingDim = data.indexed_embedding_dim ?? null
    this._embeddingDimensionMismatch = Boolean(data.embedding_dimension_mismatch)
    this._embeddingRuntime = data.embedding_runtime || { started: false, healthy: false, cache_stats: {} }
    this._retryableEmbeddingCount = data.retryable_embedding_count || 0
    this._statusWarnings = data.warnings || []
    this._statusDegraded = Boolean(data.degraded)
    this._statusItems = data.items || []
    this._indexFreshness = data.index_freshness?.by_content_mode || {}
  },

  onLeave() {
    this._stopRebuildPolling()
    this._cancelActiveSearch()
    this._cancelActiveDrawer()
    this._searchGeneration += 1
    this._lastExecutedRouteSignature = ""
    if (this._abortController) {
      this._abortController.abort()
      this._abortController = null
    }
  },

  _renderHeaderActions(subView) {
    if (subView === "search") {
      return ""
    }
    return `
      <button class="btn btn-sm" data-action="rebuild-index">重建索引</button>
      <button class="btn btn-sm" data-action="prewarm-rag">预热检索引擎</button>
      ${this._retryableEmbeddingCount > 0 ? `<button class="btn btn-sm" data-action="retry-embeddings">重试失败向量</button>` : ""}
    `
  },

  _renderHeader(subView = state.currentSubView || "search") {
    return `
      <div class="view-header view-header--with-tabs">
        <div class="subnav">
          <span class="subnav-item ${subView === "search" ? "active" : ""}" data-action="nav-search">检索</span>
          <span class="subnav-item ${subView === "status" ? "active" : ""}" data-action="nav-status">索引维护</span>
        </div>
        <div class="view-header__actions">
          ${this._renderHeaderActions(subView)}
        </div>
      </div>
    `
  },

  async render() {
    const subView = state.currentSubView || "search"
    let html = ""

    html += this._renderHeader(subView)

    if (subView === "search") {
      html += this._renderSearch()
    } else {
      html += this._renderStatus()
    }

    return html
  },

  onRendered() {
    this._bindEvents()
    this._restoreSearchFromRoute()
  },

  _renderStatus() {
    const statusBadge = this._apiAvailable
      ? '<span class="badge badge-canonical">正常</span>'
      : '<span class="badge badge-draft">未连接</span>'
    const countDisplay = this._totalChunks !== null ? String(this._totalChunks) : "-"
    const canonicalFreshness = this._indexFreshness?.canonical || {}
    const workingFreshness = this._indexFreshness?.working || {}

    if (!this._apiAvailable && this._totalChunks === null && !this._loading) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <p>与服务器连接断开</p>
          <p class="rag-empty-copy">请检查网络或刷新页面，后端服务可能尚未启动。</p>
        </div>
      `
    }

    return `
      <div class="rag-status-stack">
        <div class="card rag-status-card">
        <div class="card-title">小说检索索引概览</div>
          <div class="rag-status-metrics">
            <div class="rag-status-metric"><strong class="rag-status-value">${statusBadge}</strong><br><span class="rag-status-label">索引是否可用</span></div>
            <div class="rag-status-metric"><strong class="rag-status-value">${esc(countDisplay)}</strong><br><span class="rag-status-label">已索引章节片段</span></div>
            <div class="rag-status-metric"><strong class="rag-status-value">${esc(String(this._embeddingFailedCount))}</strong><br><span class="rag-status-label">降级片段</span></div>
            <div class="rag-status-metric"><strong class="rag-status-value">${esc(String(canonicalFreshness.fresh ?? 0))}/${esc(String(canonicalFreshness.total ?? 0))}</strong><br><span class="rag-status-label">已发布索引新鲜度</span></div>
            <div class="rag-status-metric"><strong class="rag-status-value">${esc(String(workingFreshness.fresh ?? 0))}/${esc(String(workingFreshness.total ?? 0))}</strong><br><span class="rag-status-label">工作稿索引新鲜度</span></div>
          </div>
        </div>
        ${this._renderEvidenceHealth()}
        <div id="rag-diagnostics">${this._renderDiagnostics()}</div>
        ${this._statusDegraded ? `
          <div class="card rag-status-card rag-status-warning-card">
            <div class="card-title rag-status-warning-title">索引不完整</div>
            <p class="rag-empty-copy">${esc((this._statusWarnings || []).join("；") || "部分索引已降级，抽取结果可能不准确。")}</p>
          </div>
        ` : ""}
        ${!this._loading && this._totalChunks === 0 ? `
          <div class="empty-state">
            <div class="empty-icon">&#128194;</div>
            <p>还没有检索数据</p>
            <p class="rag-empty-copy">导入正文后，系统会自动分析内容并建立检索索引。</p>
          </div>
        ` : ""}
        <div id="rag-rebuild-progress">${this._renderRebuildProgress()}</div>
        ${this._renderChunkList()}
      </div>
      <div class="rag-rebuild-form">
        <div class="rag-rebuild-range">
          <label for="rag-rebuild-content-mode">正文版本</label>
          <select class="form-input rag-rebuild-input" id="rag-rebuild-content-mode"><option value="canonical">已发布</option><option value="working">工作稿</option></select>
          <label for="rag-rebuild-start">起始章节</label>
          <input class="form-input rag-rebuild-input" id="rag-rebuild-start" type="number" min="1" placeholder="起始" />
          <label for="rag-rebuild-end">结束章节</label>
          <input class="form-input rag-rebuild-input" id="rag-rebuild-end" type="number" min="1" placeholder="结束" />
        </div>
        <button class="btn" data-action="nav-search">返回检索</button>
      </div>
    `
  },

  _renderEvidenceHealth() {
    const health = this._evidenceHealth
    if (!health) return ""
    const stateLabels = {
      healthy: "健康",
      degraded: "需要处理",
      insufficient_data: "数据不足",
    }
    const scene = health.scene_span_coverage || {}
    const mapping = health.rag_mapping_coverage || {}
    const retrieval = health.retrieval_summary || {}
    const percent = (value) => value == null ? "-" : `${Math.round(value * 100)}%`
    const reasons = Array.isArray(health.health_reasons)
      ? health.health_reasons.join("；")
      : ""
    return `
      <div class="card rag-status-card ${health.health_state === "degraded" ? "rag-status-warning-card" : ""}">
        <div class="card-title">创作证据健康</div>
        <div class="rag-status-metrics">
          <div class="rag-status-metric"><strong class="rag-status-value">${esc(stateLabels[health.health_state] || health.health_state)}</strong><br><span class="rag-status-label">24 小时健康状态</span></div>
          <div class="rag-status-metric"><strong class="rag-status-value">${esc(percent(scene.precise_span_rate))}</strong><br><span class="rag-status-label">Scene 精确定位</span></div>
          <div class="rag-status-metric"><strong class="rag-status-value">${esc(percent(mapping.eligible_mapping_rate))}</strong><br><span class="rag-status-label">应映射片段覆盖</span></div>
          <div class="rag-status-metric"><strong class="rag-status-value">${esc(String(retrieval.query_count ?? 0))}</strong><br><span class="rag-status-label">近期 context 检索</span></div>
          <div class="rag-status-metric"><strong class="rag-status-value">${esc(String(retrieval.empty_count ?? 0))}</strong><br><span class="rag-status-label">空证据运行</span></div>
        </div>
        ${reasons ? `<p class="rag-empty-copy">原因：${esc(reasons)}</p>` : ""}
      </div>
    `
  },

  _renderDiagnostics() {
    const runtime = this._embeddingRuntime || {}
    const metrics = this._metrics || {}
    const runtimeLabel = this._prewarmState === "running"
      ? "预热中"
      : this._prewarmState === "failed"
        ? "失败"
        : runtime.healthy
          ? "ready"
          : runtime.started
            ? "未就绪"
            : "未启动"
    const actualDim = this._indexedEmbeddingDim ?? this._embeddingDim ?? "-"
    const configuredDim = this._configuredEmbeddingDim ?? "-"
    const avg = metrics.avg_latency_ms != null ? `${metrics.avg_latency_ms}ms` : "-"
    const embeddingAvg = metrics.embedding_avg_ms != null ? `${metrics.embedding_avg_ms}ms` : "-"
    const degradedRate = metrics.degraded_rate != null ? `${Math.round(metrics.degraded_rate * 100)}%` : "-"
    const cacheStats = runtime.cache_stats || {}
    const cacheText = cacheStats.hits != null ? `${cacheStats.hits}/${cacheStats.misses || 0}` : "-"
    const warning = this._prewarmWarning ? `
      <p class="rag-diagnostics-warning">${esc(this._prewarmWarning)}</p>
    ` : ""
    return `
      <details class="card rag-diagnostics-card" ${this._embeddingDimensionMismatch || this._prewarmWarning ? "open" : ""}>
        <summary class="card-title">技术诊断详情</summary>
        <div class="rag-diagnostics-grid">
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(String(actualDim))}</strong><br><span class="rag-diagnostics-label">实际维度</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(String(configuredDim))}</strong><br><span class="rag-diagnostics-label">配置维度</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(runtimeLabel)}</strong><br><span class="rag-diagnostics-label">worker</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(avg)}</strong><br><span class="rag-diagnostics-label">平均检索</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(embeddingAvg)}</strong><br><span class="rag-diagnostics-label">embedding</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(degradedRate)}</strong><br><span class="rag-diagnostics-label">降级率</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(String(this._retryableEmbeddingCount || 0))}</strong><br><span class="rag-diagnostics-label">可重试</span></div>
          <div class="rag-status-metric"><strong class="rag-diagnostics-value">${esc(cacheText)}</strong><br><span class="rag-diagnostics-label">缓存命中/未命中</span></div>
        </div>
        ${this._embeddingDimensionMismatch ? `<p class="rag-diagnostics-warning">向量维度配置漂移，请同步配置后重启后端。</p>` : ""}
        ${warning}
        <div class="rag-retrieval-traces">
          <button class="btn btn-sm" data-action="load-retrieval-traces" ${this._retrievalTracesState === "loading" ? "disabled" : ""}>
            ${this._retrievalTracesState === "loading" ? "加载中..." : this._retrievalTracesState === "loaded" ? "刷新近期检索记录" : "查看近期检索记录"}
          </button>
          ${this._renderRetrievalTraces()}
        </div>
      </details>
    `
  },

  _renderRetrievalTraces() {
    if (this._retrievalTracesState === "idle") return ""
    if (this._retrievalTracesState === "loading") {
      return '<p class="rag-empty-copy">正在加载隐私安全的检索摘要…</p>'
    }
    if (this._retrievalTracesState === "error") {
      return `<p class="rag-diagnostics-warning">检索记录加载失败：${esc(this._retrievalTracesError || "未知错误")}</p>`
    }
    if (!this._retrievalTraces.length) {
      return '<p class="rag-empty-copy">暂无近期检索记录。</p>'
    }
    return `
      <div class="rag-retrieval-trace-list" aria-label="近期检索记录">
        ${this._retrievalTraces.map((trace) => {
          const dropped = Object.values(trace.drop_counts || {})
            .reduce((sum, value) => sum + (Number(value) || 0), 0)
          const time = trace.created_at ? new Date(trace.created_at).toLocaleString("zh-CN") : "-"
          return `
            <article class="rag-retrieval-trace">
              <div><strong>${esc(trace.retrieval_purpose || trace.consumer_action || "context")}</strong> · ${esc(trace.content_mode || "-")} · ${esc(time)}</div>
              <div class="rag-empty-copy">候选 ${esc(String(trace.candidate_count ?? 0))} · 去重 ${esc(String(trace.unique_count ?? 0))} · 回读 ${esc(String(trace.hydrated_count ?? 0))} · 丢弃 ${esc(String(dropped))}</div>
              ${trace.safe_empty_reason ? `<div class="rag-diagnostics-warning">空证据原因：${esc(trace.safe_empty_reason)}</div>` : ""}
              ${(trace.warning_codes || []).length ? `<div class="rag-diagnostics-warning">警告：${esc(trace.warning_codes.join("、"))}</div>` : ""}
            </article>
          `
        }).join("")}
      </div>
    `
  },

  async _loadRetrievalTraces() {
    if (!state.currentProjectId || this._retrievalTracesState === "loading") return
    this._retrievalTracesState = "loading"
    this._retrievalTracesError = ""
    this._updateDiagnosticsDOM()
    try {
      const result = await api.context.listRetrievalTraces(state.currentProjectId, {
        content_mode: "canonical",
        limit: 20,
      })
      this._retrievalTraces = Array.isArray(result) ? result : (result?.items || [])
      this._retrievalTracesState = "loaded"
    } catch (err) {
      this._retrievalTraces = []
      this._retrievalTracesState = "error"
      this._retrievalTracesError = err.message || "未知错误"
    }
    this._updateDiagnosticsDOM()
  },

  _updateDiagnosticsDOM() {
    const el = document.getElementById("rag-diagnostics")
    if (el) el.innerHTML = this._renderDiagnostics()
  },

  async _refreshMetrics() {
    if (!api.rag.metrics) return
    try {
      const data = await api.rag.metrics()
      this._metrics = data.metrics || null
      if (data.embedding_runtime) this._embeddingRuntime = data.embedding_runtime
      this._updateDiagnosticsDOM()
    } catch {
      // Metrics are diagnostic only; status remains useful without them.
    }
  },

  async _refreshStatusFromServer() {
    if (!state.currentProjectId) return
    try {
      const data = await api.rag.status(state.currentProjectId)
      this._applyStatus(data)
      this._apiAvailable = true
      this._updateDiagnosticsDOM()
    } catch {
      // Retry/rebuild completion remains visible even if the status refresh fails.
    }
  },

  async _prewarm(options = {}) {
    this._prewarmState = "running"
    this._prewarmWarning = ""
    if (!options.background) {
      this._updateDiagnosticsDOM()
    }
    try {
      const result = await api.rag.prewarm({ signal: options.signal })
      this._prewarmState = result.status === "ready" ? "ready" : "failed"
      this._prewarmWarning = result.warning || ""
      this._embeddingDim = result.embedding_dim ?? this._embeddingDim
      this._embeddingRuntime = {
        ...(this._embeddingRuntime || {}),
        started: true,
        healthy: result.status === "ready",
        cache_stats: result.cache_stats || {},
      }
    } catch (err) {
      this._prewarmState = "failed"
      this._prewarmWarning = err.message || "预热失败"
    }
    if (!options.background) {
      this._updateDiagnosticsDOM()
    }
  },

  _ensureAbortController() {
    if (!this._abortController) {
      this._abortController = new AbortController()
    }
    return this._abortController
  },

  _stopRebuildPolling() {
    if (this._rebuildPoller?.stop) this._rebuildPoller.stop()
    this._rebuildPoller = null
  },

  _renderRebuildProgress() {
    if (this._rebuildProgress) {
      return renderWorkflowCard(this._rebuildProgress, {
        title: "重建 RAG 索引",
        destinationLabel: "完成后本页索引概览会更新，可继续测试搜索。",
        enableRetry: true,
        retryPending: this._taskRetryPending,
      })
    }
    if (this._rebuildInfo) {
      return `
        <div class="empty-state">
          <p class="rag-empty-copy">${esc(this._rebuildInfo)}</p>
        </div>
      `
    }
    return ""
  },

  _updateRebuildProgressDOM() {
    const el = document.getElementById("rag-rebuild-progress")
    if (el) el.innerHTML = this._renderRebuildProgress()
  },

  async _applyRagRebuildResult(result = {}) {
    if (result.chunks_created != null) {
      this._totalChunks = result.chunks_created
    } else if (result.total_chapters != null) {
      this._totalChunks = null
      await this._refreshStatusFromServer()
    }
    if (result.embedding_failed_count != null) this._embeddingFailedCount = result.embedding_failed_count
    if (Array.isArray(result.warnings)) {
      this._statusWarnings = result.warnings
      this._statusDegraded = result.warnings.length > 0 || Boolean(result.embedding_failed_count)
    }
  },

  async _handleRebuildDone(taskId, workflowType, result = {}) {
    if (workflowType === "rag_retry_embeddings") {
      this._retryableEmbeddingCount = result.remaining_retryable_count ?? result.failed ?? 0
      this._embeddingFailedCount = result.remaining_retryable_count ?? result.failed ?? 0
      await this._refreshStatusFromServer()
    } else {
      await this._applyRagRebuildResult(result)
    }
    clearActiveWorkflow(taskId)
    this._updateRebuildProgressDOM()
    this._updateDiagnosticsDOM()
  },

  _startRebuildPolling(taskId, workflowType = "rag_reindex_novel") {
    this._stopRebuildPolling()
    this._rebuildPoller = pollTaskProgress({
      taskId,
      workflowType,
      apiClient: api,
      onUpdate: (progress) => {
        this._rebuildProgress = progress
        this._rebuildInfo = null
        this._updateRebuildProgressDOM()
      },
      onDone: (progress, task) => {
        const result = task?.result || progress.raw?.result || {}
        this._handleRebuildDone(taskId, workflowType, result)
      },
      onFailed: () => {
        this._updateRebuildProgressDOM()
      },
    })
  },

  async _retryFailedTask() {
    const progress = this._rebuildProgress
    const taskId = progress?.taskId
    if (
      !taskId
      || !state.currentProjectId
      || this._taskRetryPending
      || !progress.availableActions?.includes("retry")
    ) return false
    this._taskRetryPending = true
    this._updateRebuildProgressDOM()
    try {
      const result = await api.tasks.retry(taskId, state.currentProjectId)
      const workflowType = progress.workflowType || progress.taskType || "rag_reindex_novel"
      this._rebuildProgress = normalizeTaskProgress({
        ...progress.raw,
        ...result,
        task_id: taskId,
        task_type: workflowType,
        status: result.status || "pending",
        error_message: null,
        result: {
          ...(progress.raw?.result || {}),
          error: null,
          error_message: null,
        },
        available_actions: ["cancel"],
      }, workflowType)
      this._taskRetryPending = false
      this._updateRebuildProgressDOM()
      this._startRebuildPolling(taskId, workflowType)
      toast("任务已重新加入队列", "success")
      return true
    } catch (err) {
      this._taskRetryPending = false
      this._updateRebuildProgressDOM()
      toast(err.message || "重试任务失败", "error")
      return false
    }
  },

  _recoverRebuildWorkflow() {
    if (!state.currentProjectId || this._rebuildPoller) return
    const workflows = recoverActiveWorkflows(state.currentProjectId)
    const ragWorkflowTypes = new Set(["rag_reindex_novel", "rag_retry_embeddings"])
    const workflow = workflows.find((item) => ragWorkflowTypes.has(item.workflowType) && item.view === "rag")
      || workflows.find((item) => ragWorkflowTypes.has(item.workflowType))
    if (!workflow?.taskId) return
    const workflowType = workflow.workflowType || "rag_reindex_novel"
    this._rebuildInfo = null
    this._rebuildProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflowType)
    this._startRebuildPolling(workflow.taskId, workflowType)
  },

  _renderChunkList() {
    const items = this._statusItems || []
    if (items.length === 0) {
      return `
        <div class="card rag-chunk-list-card">
          <div class="card-title">最近片段</div>
          <p class="rag-empty-copy">暂无片段数据</p>
        </div>
      `
    }

    let rows = ""
    for (const item of items) {
      const plainText = item.text || item.summary || ""
      const preview = plainText.length > 120 ? esc(plainText.substring(0, 120) + "...") : esc(plainText)
      const entityCount = (item.entity_ids || []).length
      const characterCount = (item.character_ids || []).length
      const threadCount = (item.thread_ids || []).length
      const sceneCount = item.scene_id ? 1 : 0

      rows += `
        <tr>
          <td>${esc(String(item.chunk_index ?? "-"))}</td>
          <td>${esc(String(item.chapter_index ?? "-"))}</td>
          <td>${esc(String(item.char_count ?? "-"))}</td>
          <td>${esc(item.embedding_status || "-")}</td>
          <td>${entityCount}</td>
          <td>${characterCount}</td>
          <td>${threadCount}</td>
          <td>${sceneCount}</td>
          <td class="rag-chunk-preview" title="${esc(plainText)}">${preview}</td>
        </tr>
      `
    }

    return `
      <div class="card rag-chunk-list-card">
        <div class="card-title">最近片段</div>
        <div class="rag-chunk-table-wrap">
          <table class="data-table rag-chunk-table">
            <thead>
              <tr>
                <th>片段</th>
                <th>章节</th>
                <th>字数</th>
                <th>状态</th>
                <th>实体</th>
                <th>人物</th>
                <th>线索</th>
                <th>场景</th>
                <th>预览</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `
  },

  _renderSearch() {
    const routeState = this._searchRouteState()
    const advancedSummary = this._advancedFilterSummary(routeState)
    const advancedOpen = advancedSummary.length > 0
    const characterOptions = (this._characters || []).map((item) => {
      const id = item.id || item.entity_id || ""
      const selected = routeState.characterId === id ? " selected" : ""
      return `<option value="${esc(id)}"${selected}>${esc(item.name || "未命名人物")}</option>`
    }).join("")
    const sceneOptions = (this._scenes || []).map((item) => {
      const id = item.id || ""
      const title = item.title || `Scene ${item.scene_index ?? "-"}`
      const chapters = (item.chapter_ids || []).join("/")
      const selected = routeState.cutoffSceneId === id ? " selected" : ""
      return `<option value="${esc(id)}"${selected}>${esc(title)}${chapters ? ` · 第 ${esc(chapters)} 章` : ""}</option>`
    }).join("")
    const selected = (value, expected) => value === expected ? " selected" : ""
    const checked = (value) => value ? " checked" : ""
    return `
      <div class="card novel-search-panel">
        <div class="card-title">查找小说资料</div>
        <p class="rag-empty-copy">回查人物、场景、设定和原文出处，为当前创作核对事实。</p>
        <div class="rag-search-form">
          <input class="form-input" id="rag-search-input" aria-label="检索关键词" placeholder="输入原文、对象或结构关键词…" value="${esc(routeState.query)}" />
          <button class="btn btn-primary" data-action="do-search">检索</button>
        </div>
        <div class="novel-search-filters">
          <label>检索方式
            <select class="form-input" id="rag-search-kind">
              <option value="smart"${selected(routeState.searchKind, "smart")}>智能搜索</option>
              <option value="literal"${selected(routeState.searchKind, "literal")}>字面搜索</option>
            </select>
          </label>
          <label>正文版本
            <select class="form-input" id="rag-content-mode">
              <option value="canonical"${selected(routeState.contentMode, "canonical")}>已发布</option>
              <option value="working"${selected(routeState.contentMode, "working")}>最新工作稿</option>
            </select>
          </label>
        </div>
        <p class="rag-search-kind-help" id="rag-search-kind-help">
          智能搜索：按语义相关性查找，并把同一章的相关片段聚合显示。
        </p>
        <details class="rag-advanced-filters" data-role="rag-advanced-filters"${advancedOpen ? " open" : ""}>
          <summary>
            <span>高级筛选</span>
            <span data-role="rag-advanced-summary">${advancedSummary.length ? ` · ${esc(advancedSummary.join("、"))}` : ""}</span>
          </summary>
          <div class="novel-search-filters">
            <label>可见视角
              <select class="form-input" id="rag-visibility-mode" data-rag-advanced-filter>
                <option value="author"${selected(routeState.visibilityMode, "author")}>作者</option>
                <option value="reader"${selected(routeState.visibilityMode, "reader")}>读者</option>
                <option value="character"${selected(routeState.visibilityMode, "character")}>角色</option>
              </select>
            </label>
            <label>起始章 <input class="form-input" id="rag-chapter-from" data-rag-advanced-filter type="number" min="1" placeholder="可选" value="${esc(routeState.chapterFrom || "")}" /></label>
            <label>结束章 <input class="form-input" id="rag-chapter-to" data-rag-advanced-filter type="number" min="1" placeholder="可选" value="${esc(routeState.chapterTo || "")}" /></label>
            <label id="rag-cutoff-field" hidden>可见截止章 <input class="form-input" id="rag-cutoff-chapter" data-rag-advanced-filter type="number" min="1" value="${esc(routeState.cutoffChapter || "")}" /></label>
            <label id="rag-cutoff-scene-field" hidden>截止 Scene
              <select class="form-input" id="rag-cutoff-scene-id" data-rag-advanced-filter><option value="">可选</option>${sceneOptions}</select>
            </label>
            <label id="rag-cutoff-offset-field" hidden>章内截止位置 <input class="form-input" id="rag-cutoff-offset" data-rag-advanced-filter type="number" min="0" placeholder="可选字符偏移" value="${esc(routeState.cutoffOffset ?? "")}" /></label>
            <label id="rag-character-field" hidden>视角人物
              <select class="form-input" id="rag-character-id" data-rag-advanced-filter><option value="">请选择</option>${characterOptions}</select>
            </label>
          </div>
          <div class="novel-search-scopes">
            <span>检索范围</span>
            <label><input type="checkbox" data-search-scope="manuscript" data-rag-advanced-filter${checked(routeState.scopes.includes("manuscript"))} /> 正文</label>
            <label><input type="checkbox" data-search-scope="world" data-rag-advanced-filter${checked(routeState.scopes.includes("world"))} /> 世界对象</label>
            <label><input type="checkbox" data-search-scope="outline" data-rag-advanced-filter${checked(routeState.scopes.includes("outline"))} /> 结构</label>
            <label title="待处理内容尚未采用，纳入后需人工检查">
              <input type="checkbox" id="rag-include-pending" data-rag-advanced-filter${checked(routeState.includePending)} /> 包含待处理世界对象
            </label>
          </div>
        </details>
      </div>
      <div id="rag-results">
        <div class="empty-state">
          <p class="rag-search-empty">输入关键词后搜索。</p>
        </div>
      </div>
    `
  },

  _resetSearchState() {
    this._cancelActiveSearch()
    this._cancelActiveDrawer()
    this._searchGeneration += 1
    this._searchHits = []
    this._searchVisibleCount = 0
    this._searchTotal = 0
    this._searchResultMeta = null
    this._searchQuery = ""
    this._lastSearchPayload = null
    this._lastExecutedRouteSignature = ""
    this._drawerRefs = []
  },

  _advancedFilterSummary(filterState = {}) {
    const summary = []
    const chapterFrom = Number(filterState.chapterFrom) || null
    const chapterTo = Number(filterState.chapterTo) || null
    if (chapterFrom && chapterTo) summary.push(`第 ${chapterFrom}–${chapterTo} 章`)
    else if (chapterFrom) summary.push(`第 ${chapterFrom} 章起`)
    else if (chapterTo) summary.push(`截至第 ${chapterTo} 章`)

    const visibilityMode = filterState.visibilityMode || "author"
    if (visibilityMode === "reader") summary.push("读者视角")
    if (visibilityMode === "character") {
      const character = (this._characters || []).find((item) => (
        (item.id || item.entity_id) === filterState.characterId
      ))
      summary.push(character?.name ? `角色视角：${character.name}` : "角色视角")
    }
    if (filterState.cutoffChapter) summary.push(`可见至第 ${filterState.cutoffChapter} 章`)
    if (filterState.cutoffSceneId) {
      const scene = (this._scenes || []).find((item) => item.id === filterState.cutoffSceneId)
      summary.push(scene?.title ? `可见至 ${scene.title}` : "已设置 Scene 截止点")
    }
    if (filterState.cutoffOffset != null && filterState.cutoffOffset !== "") {
      summary.push(`章内位置 ${filterState.cutoffOffset}`)
    }

    const scopes = Array.isArray(filterState.scopes) ? filterState.scopes : ["manuscript"]
    if (scopes.length !== 1 || scopes[0] !== "manuscript") {
      const labels = { manuscript: "正文", world: "世界对象", outline: "结构" }
      summary.push(`范围：${scopes.map((scope) => labels[scope] || scope).join("、")}`)
    }
    if (filterState.includePending) summary.push("含待处理对象")
    return summary
  },

  _advancedFilterStateFromForm() {
    const value = (id) => document.getElementById(id)?.value || ""
    const scopes = [...document.querySelectorAll("[data-search-scope]:checked")]
      .map((item) => item.dataset.searchScope)
    return {
      visibilityMode: value("rag-visibility-mode") || "author",
      chapterFrom: value("rag-chapter-from"),
      chapterTo: value("rag-chapter-to"),
      cutoffChapter: value("rag-cutoff-chapter"),
      cutoffSceneId: value("rag-cutoff-scene-id"),
      cutoffOffset: value("rag-cutoff-offset"),
      characterId: value("rag-character-id"),
      scopes: scopes.length ? scopes : ["manuscript"],
      includePending: Boolean(document.getElementById("rag-include-pending")?.checked),
    }
  },

  _refreshAdvancedFilterSummary() {
    const summaryNode = document.querySelector('[data-role="rag-advanced-summary"]')
    const details = document.querySelector('[data-role="rag-advanced-filters"]')
    if (!summaryNode || !details) return
    const summary = this._advancedFilterSummary(this._advancedFilterStateFromForm())
    summaryNode.textContent = summary.length ? ` · ${summary.join("、")}` : ""
    if (summary.length) details.open = true
  },

  _cancelActiveSearch() {
    if (!this._searchAbortController) return
    this._searchAbortController.abort()
    this._searchAbortController = null
  },

  _cancelActiveDrawer() {
    if (this._drawerAbortController) this._drawerAbortController.abort()
    this._drawerAbortController = null
    this._drawerGeneration += 1
  },

  _beginDrawerRequest(drawer = document.getElementById("rag-evidence-drawer")) {
    this._cancelActiveDrawer()
    const controller = new AbortController()
    const request = {
      controller,
      drawer,
      generation: this._drawerGeneration,
      projectId: state.currentProjectId,
    }
    this._drawerAbortController = controller
    return request
  },

  _isDrawerRequestCurrent(request) {
    return Boolean(
      request
      && !request.controller.signal.aborted
      && request.generation === this._drawerGeneration
      && request.projectId === state.currentProjectId
      && (
        request.drawer == null
        || (
          request.drawer.isConnected
          && request.drawer === document.getElementById("rag-evidence-drawer")
        )
      )
    )
  },

  _searchRouteState() {
    const current = router.getCurrentQuery ? router.getCurrentQuery() : new URLSearchParams()
    const query = new URLSearchParams(current?.toString ? current.toString() : "")
    const positiveInteger = (name) => {
      const value = Number(query.get(name))
      return Number.isInteger(value) && value >= 1 ? value : null
    }
    const nonNegativeInteger = (name) => {
      const raw = query.get(name)
      if (raw == null || raw === "") return null
      const value = Number(raw)
      return Number.isInteger(value) && value >= 0 ? value : null
    }
    const rawScopes = query.getAll("scope").filter(
      (scope) => RAG_SEARCH_SCOPES.includes(scope),
    )
    return {
      query: query.get("q") || "",
      searchKind: query.get("kind") === "literal" ? "literal" : "smart",
      contentMode: query.get("content_mode") === "working" ? "working" : "canonical",
      visibilityMode: ["reader", "character"].includes(query.get("visibility"))
        ? query.get("visibility")
        : "author",
      chapterFrom: positiveInteger("chapter_from"),
      chapterTo: positiveInteger("chapter_to"),
      cutoffChapter: positiveInteger("cutoff_chapter"),
      cutoffSceneId: query.get("cutoff_scene_id") || "",
      cutoffOffset: nonNegativeInteger("cutoff_offset"),
      characterId: query.get("character_id") || "",
      scopes: rawScopes.length ? [...new Set(rawScopes)] : ["manuscript"],
      includePending: query.get("include_pending") === "1",
      signature: query.toString(),
    }
  },

  _searchRouteQuery(query) {
    const payload = this._buildEvidencePayload(query)
    if (!payload) return null
    const route = new URLSearchParams()
    route.set("q", query)
    route.set("kind", payload.search_kind)
    route.set("content_mode", payload.content_mode)
    route.set("visibility", payload.visibility.mode)
    for (const scope of payload.scopes) route.append("scope", scope)
    if (payload.chapter_from != null) route.set("chapter_from", String(payload.chapter_from))
    if (payload.chapter_to != null) route.set("chapter_to", String(payload.chapter_to))
    if (payload.visibility.cutoff_chapter != null) {
      route.set("cutoff_chapter", String(payload.visibility.cutoff_chapter))
    }
    if (payload.visibility.cutoff_scene_id) {
      route.set("cutoff_scene_id", payload.visibility.cutoff_scene_id)
    }
    if (payload.visibility.cutoff_offset != null) {
      route.set("cutoff_offset", String(payload.visibility.cutoff_offset))
    }
    if (payload.visibility.character_id) {
      route.set("character_id", payload.visibility.character_id)
    }
    if (payload.include_pending_objects) route.set("include_pending", "1")
    return route
  },

  async _submitSearchFromForm() {
    const query = document.getElementById("rag-search-input")?.value?.trim() || ""
    if (!query) return
    const route = this._searchRouteQuery(query)
    if (!route) return
    const signature = route.toString()
    state.searchQuery = query
    if (router.getCurrentQuery?.().toString() === signature) {
      this._lastExecutedRouteSignature = signature
      await this._doSearch(query, { routeSignature: signature })
      return
    }
    await router.navigate("rag", "search", true, route)
  },

  _restoreSearchFromRoute() {
    if (state.currentView !== "rag" || state.currentSubView !== "search") return
    const routeState = this._searchRouteState()
    if (!routeState.query) {
      this._resetSearchState()
      state.searchQuery = ""
      const input = document.getElementById("rag-search-input")
      if (input) input.value = ""
      return
    }
    if (routeState.signature === this._lastExecutedRouteSignature) return
    this._lastExecutedRouteSignature = routeState.signature
    state.searchQuery = routeState.query
    void this._doSearch(routeState.query, { routeSignature: routeState.signature })
  },

  async _doSearch(query, { routeSignature = "" } = {}) {
    const results = document.getElementById("rag-results")
    if (!results || !query) return

    this._cancelActiveSearch()
    const controller = new AbortController()
    const generation = ++this._searchGeneration
    const projectId = state.currentProjectId
    this._searchAbortController = controller
    this._searchQuery = query
    if (routeSignature) this._lastExecutedRouteSignature = routeSignature
    results.innerHTML = '<div class="loading">搜索中</div>'

    try {
      const payload = this._buildEvidencePayload(query)
      if (!payload) {
        results.innerHTML = '<div class="empty-state"><p class="rag-search-empty">请完善可见性条件</p></div>'
        return
      }
      this._lastSearchPayload = payload
      const options = { signal: controller.signal }
      let data
      if (payload.search_kind === "literal" && api.context?.grepEvidence) {
        const {
          search_kind: _kind,
          query: pattern,
          scopes: _scopes,
          include_pending_objects: _pending,
          top_k: limit,
          ...rest
        } = payload
        data = await api.context.grepEvidence({
          ...rest,
          pattern,
          limit,
          group_by_chapter: true,
        }, options)
      } else if (api.context?.searchEvidence) {
        const { search_kind: _kind, ...request } = payload
        data = await api.context.searchEvidence(request, options)
      } else {
        throw new Error("证据检索接口不可用，已停止使用未校验的旧索引结果")
      }
      if (
        controller.signal.aborted
        || generation !== this._searchGeneration
        || projectId !== state.currentProjectId
      ) return
      const rawHits = Array.isArray(data?.hits)
        ? data.hits
        : (Array.isArray(data?.chunks) ? data.chunks : (Array.isArray(data) ? data : []))
      this._searchHits = rawHits.map((item) => this._normalizeEvidenceHit(item))
      this._searchVisibleCount = Math.min(RAG_RESULT_PAGE_SIZE, this._searchHits.length)
      this._searchTotal = Number.isFinite(Number(data?.total))
        ? Math.max(this._searchHits.length, Number(data.total))
        : this._searchHits.length
      this._searchResultMeta = data || {}
      this._searchQuery = query
      this._renderSearchResults()
    } catch (err) {
      if (
        controller.signal.aborted
        || generation !== this._searchGeneration
        || projectId !== state.currentProjectId
        || err?.name === "AbortError"
      ) return
      results.innerHTML = this._renderSearchError(err)
    } finally {
      if (this._searchAbortController === controller) this._searchAbortController = null
    }
  },

  _renderSearchError(error) {
    const message = String(error?.message || "").toLowerCase()
    const status = Number(error?.status || error?.statusCode)
    const timeout = message.includes("超时") || message.includes("timeout")
    const missingInterface = message.includes("证据检索接口不可用")
    const unavailable = [502, 503, 504].includes(status)
      || message.includes("network")
      || message.includes("网络")
      || message.includes("暂时不可用")
    const reason = missingInterface
      ? "证据检索接口不可用，本次未展示未经校验的旧索引结果。"
      : (timeout
          ? "请求等待时间过长，可能是索引繁忙或连接暂时不可用。"
          : (unavailable
              ? "检索服务暂时不可用，可以稍后重试。"
              : "本次检索请求未能完成，可以使用原条件重试。"))
    const searchKind = document.getElementById("rag-search-kind")?.value
      || this._lastSearchPayload?.search_kind
      || "smart"
    return `
      <section class="card rag-search-error" role="alert">
        <div class="card-title">暂时无法完成检索</div>
        <p class="rag-error-text">${esc(reason)}</p>
        <p class="rag-empty-copy">关键词和筛选条件已保留，失败不会被记作空结果。</p>
        <div class="rag-result-actions">
          <button class="btn btn-primary" data-action="retry-search">重试</button>
          ${searchKind === "literal" ? "" : '<button class="btn" data-action="retry-literal-search">切换字面搜索重试</button>'}
        </div>
      </section>
    `
  },

  async _retrySearch({ literal = false } = {}) {
    const input = document.getElementById("rag-search-input")
    const query = input?.value?.trim()
      || this._lastSearchPayload?.query
      || this._searchQuery
      || this._searchRouteState().query
    if (!query) return
    if (literal) {
      const searchKind = document.getElementById("rag-search-kind")
      if (searchKind) searchKind.value = "literal"
      this._toggleSearchScopes("literal")
      this._updateSearchKindHelp("literal")
      this._refreshAdvancedFilterSummary()
    }
    return this._submitSearchFromForm()
  },

  _renderSearchResults() {
    const results = document.getElementById("rag-results")
    if (!results) return
    const warningHtml = this._renderSearchWarnings(this._searchResultMeta || {})
    if (this._searchHits.length === 0) {
      results.innerHTML = `${warningHtml}<div class="empty-state"><p class="rag-search-empty">未找到匹配结果</p></div>`
      return
    }

    const visibleHits = this._searchHits.slice(0, this._searchVisibleCount)
    let html = `<div class="rag-results-list">${warningHtml}`
    const chapterResultCount = this._searchHits.filter((hit) => hit.chapter_index).length
    const resultLabel = chapterResultCount === this._searchHits.length ? "个章节结果" : "条结果"
    html += `<p class="rag-result-count">找到 ${esc(String(this._searchTotal))} ${resultLabel} · 已显示 ${esc(String(visibleHits.length))}</p>`
    for (const [index, hit] of visibleHits.entries()) {
      const score = hit.score || ""
      const mode = hit.source_ref?.content_mode === "working" ? "工作稿" : "已发布"
      const kind = { manuscript: "正文", world_object: "世界对象", outline_asset: "结构" }[hit.kind] || hit.kind
      html += `
        <article class="card rag-result-card">
          <div class="card-title rag-result-title">
            <span>${esc(hit.title || "检索结果")}</span>
            ${score ? `<span class="rag-result-score">${(score * 100).toFixed(0)}%</span>` : ""}
          </div>
          <p class="rag-result-text">${this._highlightSnippet(hit.snippet, this._searchQuery)}</p>
          <div class="card-meta">
            ${esc(kind)}
            ${hit.chapter_index ? ` · 第 ${esc(String(hit.chapter_index))} 章` : ""}
            ${hit.match_count > 1 ? ` · ${hit.match_basis === "occurrence" ? `本章 ${esc(String(hit.match_count))} 处命中` : `聚合 ${esc(String(hit.match_count))} 个相关片段`}` : ""}
            ${hit.source_ref ? ` · ${mode} v${esc(String(hit.source_ref.version_number || "-"))}` : ""}
            ${hit.index_fresh === false ? " · 索引待更新" : ""}
            ${(hit.scene_refs || []).length ? ` · Scene ${esc(String(hit.scene_refs.length))}` : ""}
            ${(hit.object_refs || []).length ? ` · 对象 ${esc(String(hit.object_refs.length))}` : ""}
          </div>
          <div class="rag-result-actions">
            <button class="btn btn-sm" data-action="open-hit" data-hit-index="${index}">${hit.source_ref ? "阅读原文" : "查看对象"}</button>
          </div>
        </article>
      `
    }
    const remaining = Math.max(0, this._searchHits.length - visibleHits.length)
    if (remaining > 0) {
      html += `
        <div class="rag-load-more">
          <button class="btn" data-action="load-more-results">加载更多</button>
          <span>还有 ${esc(String(remaining))} 条已获取结果</span>
        </div>
      `
    } else if (this._searchTotal > this._searchHits.length) {
      html += `<p class="rag-search-limit-note">已显示本次返回的 ${esc(String(this._searchHits.length))} 条结果；可缩小章节或检索范围继续查找。</p>`
    }
    html += '</div><aside id="rag-evidence-drawer" class="novel-evidence-drawer" hidden></aside>'
    results.innerHTML = html
  },

  _loadMoreSearchResults() {
    this._searchVisibleCount = Math.min(
      this._searchHits.length,
      this._searchVisibleCount + RAG_RESULT_PAGE_SIZE,
    )
    this._renderSearchResults()
  },

  _buildEvidencePayload(query) {
    const value = (id) => document.getElementById(id)?.value || ""
    const integer = (id) => {
      const parsed = Number(value(id))
      return Number.isInteger(parsed) && parsed >= 1 ? parsed : null
    }
    const mode = value("rag-visibility-mode") || "author"
    const cutoffChapter = integer("rag-cutoff-chapter")
    const cutoffOffsetRaw = value("rag-cutoff-offset").trim()
    const cutoffOffsetValue = Number(cutoffOffsetRaw)
    const cutoffOffset = cutoffOffsetRaw
      && Number.isInteger(cutoffOffsetValue)
      && cutoffOffsetValue >= 0
      ? cutoffOffsetValue
      : null
    const characterId = value("rag-character-id") || null
    if ((mode === "reader" || mode === "character") && cutoffChapter == null) {
      toast("读者/角色视角必须设置可见截止章", "warning")
      return null
    }
    if (mode === "character" && !characterId) {
      toast("角色视角必须选择人物", "warning")
      return null
    }
    const scopes = [...document.querySelectorAll("[data-search-scope]:checked")]
      .map((item) => item.dataset.searchScope)
    return {
      novel_id: state.currentProjectId,
      query,
      search_kind: value("rag-search-kind") || "smart",
      content_mode: value("rag-content-mode") || "canonical",
      visibility: {
        mode,
        cutoff_chapter: cutoffChapter,
        cutoff_scene_id: value("rag-cutoff-scene-id") || null,
        cutoff_offset: cutoffOffset,
        character_id: characterId,
      },
      scopes: scopes.length ? scopes : ["manuscript"],
      include_pending_objects: Boolean(document.getElementById("rag-include-pending")?.checked),
      chapter_from: integer("rag-chapter-from"),
      chapter_to: integer("rag-chapter-to"),
      top_k: RAG_RESULT_FETCH_LIMIT,
    }
  },

  _normalizeEvidenceHit(item = {}) {
    return {
      ...item,
      kind: item.kind || (item.source_type === "chapter_text" ? "manuscript" : item.source_type || "unknown"),
      title: item.title || (item.chapter_index ? `第 ${item.chapter_index} 章` : `来源：${item.source_type || "unknown"}`),
      snippet: item.snippet || item.text || item.summary || item.content || "",
      score: item.score ?? item.similarity ?? null,
      scene_refs: item.scene_refs || [],
      object_refs: item.object_refs || [],
      index_fresh: item.index_fresh !== false,
      match_count: Number(item.match_count) > 0 ? Number(item.match_count) : 1,
      match_basis: item.match_basis === "occurrence" ? "occurrence" : "chunk",
    }
  },

  _renderSearchWarnings(data = {}) {
    if (!data.degraded && !(data.warnings || []).length) return ""
    const warnings = (data.warnings || []).map((warning) => esc(warning)).join("<br>")
    return `
      <div class="card rag-search-warning rag-status-warning-card">
        <div class="card-title rag-status-warning-title">本次结果可能不准确</div>
        <p class="rag-empty-copy">${warnings || "检索已降级，请检查索引任务结果。"}</p>
      </div>
    `
  },

  _highlightSnippet(text, query) {
    const source = String(text || "").slice(0, 500)
    const needle = String(query || "")
    if (!needle) return esc(source)
    const index = source.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase())
    if (index < 0) return esc(source)
    return `${esc(source.slice(0, index))}<mark>${esc(source.slice(index, index + needle.length))}</mark>${esc(source.slice(index + needle.length))}`
  },

  _visibilityFromLastSearch() {
    return this._lastSearchPayload?.visibility || { mode: "author" }
  },

  async _openHit(index) {
    const hit = this._searchHits[Number(index)]
    const drawer = document.getElementById("rag-evidence-drawer")
    if (!hit || !drawer) return
    const request = this._beginDrawerRequest(drawer)
    drawer.hidden = false
    drawer.innerHTML = '<div class="loading">读取中</div>'
    try {
      if (hit.source_ref) {
        const result = await api.context.readEvidence({
          novel_id: request.projectId,
          content_mode: hit.source_ref.content_mode,
          visibility: this._visibilityFromLastSearch(),
          source_ref: hit.source_ref,
          before: 3,
          after: 3,
        }, { signal: request.controller.signal })
        if (!this._isDrawerRequestCurrent(request)) return
        this._drawerRefs = [...(result.scene_refs || []), ...(result.object_refs || [])]
        const text = String(result.text || "")
        const start = Math.max(0, Number(result.highlight_start) || 0)
        const end = Math.max(start, Number(result.highlight_end) || start)
        drawer.innerHTML = `
          <div class="novel-evidence-drawer__header"><strong>${esc(result.title || "原文")}</strong><button class="btn btn-sm" data-action="close-drawer">关闭</button></div>
          <p class="novel-evidence-source-meta">第 ${esc(String(result.source_ref?.chapter_index || "-"))} 章 · v${esc(String(result.source_ref?.version_number || "-"))}</p>
          <div class="novel-evidence-text">${esc(text.slice(0, start))}<mark>${esc(text.slice(start, end))}</mark>${esc(text.slice(end))}</div>
          <button class="btn btn-sm" data-action="navigate-chapter-ref" data-chapter-index="${esc(String(result.source_ref?.chapter_index || ""))}">跳转章节</button>
          ${this._renderDrawerRefs(this._drawerRefs)}
          ${(result.warnings || []).map((item) => `<p class="rag-diagnostics-warning">${esc(item)}</p>`).join("")}
        `
      } else if (hit.target_ref) {
        const result = await api.context.inspectEvidence({
          novel_id: request.projectId,
          content_mode: this._lastSearchPayload?.content_mode || "canonical",
          visibility: this._visibilityFromLastSearch(),
          target_ref: hit.target_ref,
        }, { signal: request.controller.signal })
        if (!this._isDrawerRequestCurrent(request)) return
        this._drawerRefs = [{ ...hit.target_ref, target_name: hit.title || "" }]
        drawer.innerHTML = `
          <div class="novel-evidence-drawer__header"><strong>${esc(hit.title)}</strong><button class="btn btn-sm" data-action="close-drawer">关闭</button></div>
          <pre class="novel-evidence-object">${esc(JSON.stringify(result.item || {}, null, 2))}</pre>
          <button class="btn btn-sm" data-action="trace-drawer-ref" data-ref-index="0">追踪原文证据（${esc(String(result.evidence_count || 0))}）</button>
          ${this._isWorldObjectRef(hit.target_ref) ? '<button class="btn btn-sm" data-action="navigate-object-ref" data-ref-index="0">跳转世界对象</button>' : ""}
          ${(result.warnings || []).map((item) => `<p class="rag-diagnostics-warning">${esc(item)}</p>`).join("")}
        `
      }
    } catch (err) {
      if (!this._isDrawerRequestCurrent(request) || err?.name === "AbortError") return
      drawer.innerHTML = `<p class="rag-error-text">读取失败：${esc(err.message)}</p>`
    } finally {
      if (this._drawerAbortController === request.controller) this._drawerAbortController = null
    }
  },

  _renderDrawerRefs(refs) {
    if (!refs.length) return ""
    return `<div class="novel-evidence-links">${refs.map((ref, index) => {
      const isScene = ref.target_type === "outline_scene"
      const ordinal = index + 1
      const fallbackLabel = isScene ? `Scene ${ordinal}` : `关联对象 ${ordinal}`
      const label = ref.target_name || ref.name || fallbackLabel
      const trace = isScene ? "" : `<button class="btn btn-sm" data-action="trace-drawer-ref" data-ref-index="${index}">查看${esc(label)}的证据</button>`
      const navigate = isScene
        ? `<button class="btn btn-sm" data-action="navigate-scene-ref" data-ref-index="${index}">跳转 ${esc(label)}</button>`
        : (this._isWorldObjectRef(ref) ? `<button class="btn btn-sm" data-action="navigate-object-ref" data-ref-index="${index}">跳转${esc(label)}</button>` : "")
      return trace + navigate
    }).join("")}</div>`
  },

  _isWorldObjectRef(ref) {
    return ["world_entity", "core_entity", "entity", "character"].includes(ref?.target_type)
  },

  async _navigateObjectRef(index) {
    const ref = this._drawerRefs[Number(index)]
    if (!ref?.target_id) return
    const request = this._beginDrawerRequest()
    let label = ref.target_name || ref.name || ""
    if (!label && api.context?.inspectEvidence) {
      try {
        const result = await api.context.inspectEvidence({
          novel_id: request.projectId,
          content_mode: this._lastSearchPayload?.content_mode || "canonical",
          visibility: this._visibilityFromLastSearch(),
          target_ref: ref,
        }, { signal: request.controller.signal })
        if (!this._isDrawerRequestCurrent(request)) return
        label = result.item?.name || ""
      } catch (err) {
        if (!this._isDrawerRequestCurrent(request) || err?.name === "AbortError") return
        // A stable object jump is still possible by ID if inspection is unavailable.
      }
    }
    if (!this._isDrawerRequestCurrent(request)) return
    const query = new URLSearchParams()
    query.set("q", label || ref.target_id)
    router.navigate("world", "objects", true, query)
    if (this._drawerAbortController === request.controller) this._drawerAbortController = null
  },

  _navigateChapterRef(value) {
    const chapterIndex = Number(value)
    if (!Number.isInteger(chapterIndex) || chapterIndex < 1) return
    state.viewStates.writing = {
      ...(state.viewStates.writing || {}),
      projectId: state.currentProjectId,
      currentChapter: chapterIndex,
      currentDraftId: null,
      currentVersionNumber: null,
      isReadonly: false,
    }
    router.navigate(
      "writing",
      null,
      true,
      new URLSearchParams({ chapter_index: String(chapterIndex) }),
    )
  },

  async _traceDrawerRef(index) {
    const ref = this._drawerRefs[Number(index)]
    const drawer = document.getElementById("rag-evidence-drawer")
    if (!ref || !drawer) return
    const request = this._beginDrawerRequest(drawer)
    drawer.hidden = false
    drawer.innerHTML = '<div class="loading">追踪中</div>'
    try {
      const result = await api.context.traceEvidence({
        novel_id: request.projectId,
        content_mode: this._lastSearchPayload?.content_mode || "canonical",
        visibility: this._visibilityFromLastSearch(),
        target_ref: ref,
        claim_path: ref.target_path || "",
      }, { signal: request.controller.signal })
      if (!this._isDrawerRequestCurrent(request)) return
      const label = ref.target_name || ref.name || `关联对象 ${Number(index) + 1}`
      drawer.innerHTML = `
        <div class="novel-evidence-drawer__header"><strong>${esc(label)}的对象证据</strong><button class="btn btn-sm" data-action="close-drawer">关闭</button></div>
        ${(result.links || []).map((link) => `<article class="novel-evidence-trace"><p>${esc(link.read?.text || (link.status === "needs_review" ? "待人工定位原文" : ""))}</p><small>第 ${esc(String(link.source_ref?.chapter_index || "-"))} 章 · ${esc(link.precision || "range")}</small></article>`).join("") || '<p class="rag-search-empty">该对象暂未建立当前视角可见的原文证据；本次检索命中的原文仍可从结果卡“阅读原文”查看。</p>'}
        ${(result.warnings || []).map((item) => `<p class="rag-diagnostics-warning">${esc(item)}</p>`).join("")}
      `
    } catch (err) {
      if (!this._isDrawerRequestCurrent(request) || err?.name === "AbortError") return
      drawer.innerHTML = `<p class="rag-error-text">追踪失败：${esc(err.message)}</p>`
    } finally {
      if (this._drawerAbortController === request.controller) this._drawerAbortController = null
    }
  },

  async _rebuildIndex() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      toast("正在重建索引...", "info")
      const payload = { novel_id: state.currentProjectId }
      const contentModeInput = document.getElementById("rag-rebuild-content-mode")
      if (contentModeInput?.value) payload.content_mode = contentModeInput.value
      const startInput = document.getElementById("rag-rebuild-start")
      const endInput = document.getElementById("rag-rebuild-end")
      const startChapter = startInput ? Number(startInput.value) : NaN
      const endChapter = endInput ? Number(endInput.value) : NaN
      if (!Number.isNaN(startChapter) && !Number.isNaN(endChapter) && startChapter >= 1 && endChapter >= 1 && startChapter <= endChapter) {
        payload.start_chapter = startChapter
        payload.end_chapter = endChapter
      }
      const result = await api.rag.rebuild(payload, { signal: this._ensureAbortController().signal })
      api.clearCache()
      if (result.task_id) {
        this._rebuildInfo = null
        this._rebuildProgress = normalizeTaskProgress({
          ...result,
          task_type: "rag_reindex_novel",
        }, "rag_reindex_novel")
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "rag_reindex_novel",
          projectId: state.currentProjectId,
          view: "rag",
          meta: { start_chapter: payload.start_chapter, end_chapter: payload.end_chapter },
        })
        this._updateRebuildProgressDOM()
        this._startRebuildPolling(result.task_id)
        toast("索引重建任务已提交", "success")
      } else if (result.total > 0 || (result.task_ids || []).length > 0) {
        this._rebuildInfo = "索引重建请求已处理。"
        this._rebuildProgress = null
        this._updateRebuildProgressDOM()
        toast("索引重建任务已提交", "success")
      } else {
        this._rebuildProgress = null
        this._rebuildInfo = "暂无可索引工作稿"
        this._updateRebuildProgressDOM()
        toast("暂无可索引工作稿", "info")
      }
      for (const warning of (result.warnings || [])) {
        toast(warning, "warning")
      }
    } catch (err) {
      toast(err.message || "重建失败", "error")
    }
  },

  async _retryEmbeddings() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    if (!this._retryableEmbeddingCount) {
      toast("暂无可重试的失败向量", "info")
      return
    }
    try {
      const result = await api.rag.retryEmbeddings({
        novel_id: state.currentProjectId,
        statuses: ["failed", "pending_vectorization"],
      }, { signal: this._ensureAbortController().signal })
      api.clearCache()
      if (result.task_id) {
        this._rebuildInfo = null
        this._rebuildProgress = normalizeTaskProgress({
          ...result,
          task_type: "rag_retry_embeddings",
        }, "rag_retry_embeddings")
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "rag_retry_embeddings",
          projectId: state.currentProjectId,
          view: "rag",
        })
        this._updateRebuildProgressDOM()
        this._startRebuildPolling(result.task_id, "rag_retry_embeddings")
        toast("失败向量重试任务已提交", "success")
      }
    } catch (err) {
      toast(err.message || "重试失败", "error")
    }
  },

  _bindEvents() {
    // 搜索输入框的 Enter 快捷键
    const searchInput = document.getElementById("rag-search-input")
    if (searchInput) {
      searchInput.removeEventListener("keydown", this._searchEnterHandler)
      this._searchEnterHandler = (e) => {
        if (e.key === "Enter") void this._submitSearchFromForm()
      }
      searchInput.addEventListener("keydown", this._searchEnterHandler)
    }
    const visibilitySelect = document.getElementById("rag-visibility-mode")
    if (visibilitySelect) {
      visibilitySelect.onchange = () => {
        this._toggleVisibilityFields(visibilitySelect.value)
        this._refreshAdvancedFilterSummary()
      }
      this._toggleVisibilityFields(visibilitySelect.value)
    }
    const searchKindSelect = document.getElementById("rag-search-kind")
    if (searchKindSelect) {
      searchKindSelect.onchange = () => {
        this._toggleSearchScopes(searchKindSelect.value)
        this._updateSearchKindHelp(searchKindSelect.value)
        this._refreshAdvancedFilterSummary()
      }
      this._toggleSearchScopes(searchKindSelect.value)
      this._updateSearchKindHelp(searchKindSelect.value)
    }

    bindWorkspaceClick(this, {
      "nav-status": () => router.navigate("rag", "status"),
      "nav-search": () => router.navigate("rag", "search"),
      "do-search": () => this._submitSearchFromForm(),
      "retry-search": () => this._retrySearch(),
      "retry-literal-search": () => this._retrySearch({ literal: true }),
      "load-more-results": () => this._loadMoreSearchResults(),
      "open-hit": (_event, element) => this._openHit(element.dataset.hitIndex),
      "trace-drawer-ref": (_event, element) => this._traceDrawerRef(element.dataset.refIndex),
      "navigate-scene-ref": (_event, element) => {
        const ref = this._drawerRefs[Number(element.dataset.refIndex)]
        if (ref?.target_id) router.navigate("scene", ref.target_id)
      },
      "navigate-object-ref": (_event, element) => this._navigateObjectRef(element.dataset.refIndex),
      "navigate-chapter-ref": (_event, element) => this._navigateChapterRef(element.dataset.chapterIndex),
      "close-drawer": () => {
        this._cancelActiveDrawer()
        const drawer = document.getElementById("rag-evidence-drawer")
        if (drawer) drawer.hidden = true
      },
      "rebuild-index": () => this._rebuildIndex(),
      "prewarm-rag": () => this._prewarm(),
      "retry-embeddings": () => this._retryEmbeddings(),
      "retry-task": () => this._retryFailedTask(),
      "load-retrieval-traces": () => this._loadRetrievalTraces(),
    })

    for (const input of document.querySelectorAll("[data-rag-advanced-filter]")) {
      if (input === visibilitySelect) continue
      input.addEventListener("change", () => this._refreshAdvancedFilterSummary())
      if (input.matches('input[type="number"]')) {
        input.addEventListener("input", () => this._refreshAdvancedFilterSummary())
      }
    }
    this._refreshAdvancedFilterSummary()
  },

  _toggleVisibilityFields(mode) {
    const cutoff = document.getElementById("rag-cutoff-field")
    const cutoffScene = document.getElementById("rag-cutoff-scene-field")
    const cutoffOffset = document.getElementById("rag-cutoff-offset-field")
    const character = document.getElementById("rag-character-field")
    if (cutoff) cutoff.hidden = mode === "author"
    if (cutoffScene) cutoffScene.hidden = mode === "author"
    if (cutoffOffset) cutoffOffset.hidden = mode === "author"
    if (character) character.hidden = mode !== "character"
  },

  _toggleSearchScopes(searchKind) {
    const literal = searchKind === "literal"
    for (const input of document.querySelectorAll("[data-search-scope]")) {
      const manuscript = input.dataset.searchScope === "manuscript"
      input.disabled = literal && !manuscript
      if (literal) input.checked = manuscript
    }
  },

  _updateSearchKindHelp(searchKind) {
    const help = document.getElementById("rag-search-kind-help")
    if (!help) return
    help.textContent = searchKind === "literal"
      ? "字面搜索：查找完全相同的文字，并按章节汇总该章的全部出现位置。"
      : "智能搜索：按语义相关性查找，并把同一章的相关片段聚合显示。"
  },
}

router.registerView("rag", ragView)
window.ragView = ragView
export default ragView
