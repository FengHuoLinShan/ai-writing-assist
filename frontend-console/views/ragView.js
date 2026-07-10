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
  _lastSearchPayload: null,
  _drawerRefs: [],

  async onEnter() {
    this._loading = true
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
    if (api.world?.listCharacters) {
      try {
        const result = await api.world.listCharacters({
          novel_id: state.currentProjectId,
          limit: 200,
        })
        this._characters = Array.isArray(result) ? result : (result?.items || [])
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
    if (this._abortController) {
      this._abortController.abort()
      this._abortController = null
    }
  },

  async render() {
    const subView = state.currentSubView || "search"
    let html = ""

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "search" ? "active" : ""}" data-action="nav-search">检索</span>
        <span class="subnav-item ${subView === "status" ? "active" : ""}" data-action="nav-status">索引维护</span>
      </div>
    `

    if (subView === "search") {
      html += this._renderSearch()
    } else {
      html += this._renderStatus()
    }

    setTimeout(() => this._bindEvents(), 0)
    return html
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
          <label>正文版本</label>
          <select class="form-input rag-rebuild-input" id="rag-rebuild-content-mode"><option value="canonical">已发布</option><option value="working">工作稿</option></select>
          <label>起始章节</label>
          <input class="form-input rag-rebuild-input" id="rag-rebuild-start" type="number" min="1" placeholder="起始" />
          <label>结束章节</label>
          <input class="form-input rag-rebuild-input" id="rag-rebuild-end" type="number" min="1" placeholder="结束" />
        </div>
        <button class="btn" data-action="rebuild-index">重建索引</button>
        <button class="btn" data-action="prewarm-rag">预热检索引擎</button>
        ${this._retryableEmbeddingCount > 0 ? `<button class="btn" data-action="retry-embeddings">重试失败向量</button>` : ""}
        <button class="btn" data-action="nav-search">返回检索</button>
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
      </details>
    `
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
        clearActiveWorkflow(taskId)
        this._updateRebuildProgressDOM()
      },
    })
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
    const characterOptions = (this._characters || []).map((item) => {
      const id = item.id || item.entity_id || ""
      return `<option value="${esc(id)}">${esc(item.name || "未命名人物")}</option>`
    }).join("")
    const sceneOptions = (this._scenes || []).map((item) => {
      const id = item.id || ""
      const title = item.title || `Scene ${item.scene_index ?? "-"}`
      const chapters = (item.chapter_ids || []).join("/")
      return `<option value="${esc(id)}">${esc(title)}${chapters ? ` · 第 ${esc(chapters)} 章` : ""}</option>`
    }).join("")
    return `
      <div class="card novel-search-panel">
        <div class="card-title">在小说中查找原文与设定证据</div>
        <div class="rag-search-form">
          <input class="form-input" id="rag-search-input" placeholder="输入原文、对象或结构关键词…" value="${esc(state.searchQuery || "")}" />
          <button class="btn btn-primary" data-action="do-search">检索</button>
        </div>
        <div class="novel-search-filters">
          <label>检索方式
            <select class="form-input" id="rag-search-kind">
              <option value="literal">字面搜索</option>
              <option value="smart">智能搜索</option>
            </select>
          </label>
          <label>正文版本
            <select class="form-input" id="rag-content-mode">
              <option value="canonical">已发布</option>
              <option value="working">最新工作稿</option>
            </select>
          </label>
          <label>可见视角
            <select class="form-input" id="rag-visibility-mode" data-action="visibility-change">
              <option value="author">作者</option>
              <option value="reader">读者</option>
              <option value="character">角色</option>
            </select>
          </label>
          <label>起始章 <input class="form-input" id="rag-chapter-from" type="number" min="1" placeholder="可选" /></label>
          <label>结束章 <input class="form-input" id="rag-chapter-to" type="number" min="1" placeholder="可选" /></label>
          <label id="rag-cutoff-field" hidden>可见截止章 <input class="form-input" id="rag-cutoff-chapter" type="number" min="1" /></label>
          <label id="rag-cutoff-scene-field" hidden>截止 Scene
            <select class="form-input" id="rag-cutoff-scene-id"><option value="">可选</option>${sceneOptions}</select>
          </label>
          <label id="rag-cutoff-offset-field" hidden>章内截止位置 <input class="form-input" id="rag-cutoff-offset" type="number" min="0" placeholder="可选字符偏移" /></label>
          <label id="rag-character-field" hidden>视角人物
            <select class="form-input" id="rag-character-id"><option value="">请选择</option>${characterOptions}</select>
          </label>
        </div>
        <div class="novel-search-scopes">
          <span>检索范围</span>
          <label><input type="checkbox" data-search-scope="manuscript" checked /> 正文</label>
          <label><input type="checkbox" data-search-scope="world" /> 世界对象</label>
          <label><input type="checkbox" data-search-scope="outline" /> 结构</label>
        </div>
      </div>
      <div id="rag-results">
        <div class="empty-state">
          <p class="rag-search-empty">输入关键词后搜索。</p>
        </div>
      </div>
    `
  },

  async _doSearch(query) {
    const results = document.getElementById("rag-results")
    if (!results || !query) return

    results.innerHTML = '<div class="loading">搜索中</div>'

    try {
      const payload = this._buildEvidencePayload(query)
      if (!payload) {
        results.innerHTML = '<div class="empty-state"><p class="rag-search-empty">请完善可见性条件</p></div>'
        return
      }
      this._lastSearchPayload = payload
      const options = { signal: this._ensureAbortController().signal }
      let data
      if (payload.search_kind === "literal" && api.context?.grepEvidence) {
        const { search_kind: _kind, query: pattern, scopes: _scopes, top_k: limit, ...rest } = payload
        data = await api.context.grepEvidence({ ...rest, pattern, limit }, options)
      } else if (api.context?.searchEvidence) {
        const { search_kind: _kind, ...request } = payload
        data = await api.context.searchEvidence(request, options)
      } else {
        throw new Error("证据检索接口不可用，已停止使用未校验的旧索引结果")
      }
      const rawHits = Array.isArray(data?.hits)
        ? data.hits
        : (Array.isArray(data?.chunks) ? data.chunks : (Array.isArray(data) ? data : []))
      this._searchHits = rawHits.map((item) => this._normalizeEvidenceHit(item))
      const warningHtml = this._renderSearchWarnings(data)
      if (this._searchHits.length === 0) {
        results.innerHTML = `${warningHtml}<div class="empty-state"><p class="rag-search-empty">未找到匹配结果</p></div>`
        return
      }

      let html = `<div class="rag-results-list">${warningHtml}`
      html += `<p class="rag-result-count">找到 ${this._searchHits.length} 条结果</p>`
      for (const [index, hit] of this._searchHits.entries()) {
        const score = hit.score || ""
        const mode = hit.source_ref?.content_mode === "working" ? "工作稿" : "已发布"
        const kind = { manuscript: "正文", world_object: "世界对象", outline_asset: "结构" }[hit.kind] || hit.kind
        html += `
          <article class="card rag-result-card">
            <div class="card-title rag-result-title">
              <span>${esc(hit.title || "检索结果")}</span>
              ${score ? `<span class="rag-result-score">${(score * 100).toFixed(0)}%</span>` : ""}
            </div>
            <p class="rag-result-text">${this._highlightSnippet(hit.snippet, query)}</p>
            <div class="card-meta">
              ${esc(kind)}
              ${hit.chapter_index ? ` · 第 ${esc(String(hit.chapter_index))} 章` : ""}
              ${hit.source_ref ? ` · ${mode} v${esc(String(hit.source_ref.version_number || "-"))}` : ""}
              ${hit.index_fresh === false ? " · 索引待更新" : ""}
              ${(hit.scene_refs || []).length ? ` · Scene ${esc(String(hit.scene_refs.length))}` : ""}
              ${(hit.object_refs || []).length ? ` · 对象 ${esc(String(hit.object_refs.length))}` : ""}
            </div>
            <div class="rag-result-actions">
              <button class="btn btn-sm" data-action="open-hit" data-hit-index="${index}">${hit.source_ref ? "阅读原文" : "查看对象"}</button>
              ${(hit.object_refs || []).length ? `<button class="btn btn-sm" data-action="trace-hit" data-hit-index="${index}">追踪证据</button>` : ""}
            </div>
          </article>
        `
      }
      html += '</div><aside id="rag-evidence-drawer" class="novel-evidence-drawer" hidden></aside>'
      results.innerHTML = html
    } catch (err) {
      results.innerHTML = `<div class="empty-state"><p class="rag-error-text">搜索失败：${esc(err.message)}</p></div>`
    }
  },

  _buildEvidencePayload(query) {
    const value = (id) => document.getElementById(id)?.value || ""
    const integer = (id) => {
      const parsed = Number(value(id))
      return Number.isInteger(parsed) && parsed >= 1 ? parsed : null
    }
    const mode = value("rag-visibility-mode") || "author"
    const cutoffChapter = integer("rag-cutoff-chapter")
    const cutoffOffsetValue = Number(value("rag-cutoff-offset"))
    const cutoffOffset = Number.isInteger(cutoffOffsetValue) && cutoffOffsetValue >= 0
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
      chapter_from: integer("rag-chapter-from"),
      chapter_to: integer("rag-chapter-to"),
      top_k: 12,
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
    }
  },

  _renderSearchWarnings(data = {}) {
    if (!data.degraded && !(data.warnings || []).length) return ""
    const warnings = (data.warnings || []).map((warning) => esc(warning)).join("<br>")
    return `
      <div class="card rag-result-card rag-status-warning-card">
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
    drawer.hidden = false
    drawer.innerHTML = '<div class="loading">读取中</div>'
    try {
      if (hit.source_ref) {
        const result = await api.context.readEvidence({
          novel_id: state.currentProjectId,
          content_mode: hit.source_ref.content_mode,
          visibility: this._visibilityFromLastSearch(),
          source_ref: hit.source_ref,
          before: 3,
          after: 3,
        }, { signal: this._ensureAbortController().signal })
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
          novel_id: state.currentProjectId,
          content_mode: this._lastSearchPayload?.content_mode || "canonical",
          visibility: this._visibilityFromLastSearch(),
          target_ref: hit.target_ref,
        }, { signal: this._ensureAbortController().signal })
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
      drawer.innerHTML = `<p class="rag-error-text">读取失败：${esc(err.message)}</p>`
    }
  },

  _renderDrawerRefs(refs) {
    if (!refs.length) return ""
    return `<div class="novel-evidence-links">${refs.map((ref, index) => {
      const isScene = ref.target_type === "outline_scene"
      const trace = isScene ? "" : `<button class="btn btn-sm" data-action="trace-drawer-ref" data-ref-index="${index}">查看对象证据</button>`
      const navigate = isScene
        ? `<button class="btn btn-sm" data-action="navigate-scene-ref" data-ref-index="${index}">跳转 Scene</button>`
        : (this._isWorldObjectRef(ref) ? `<button class="btn btn-sm" data-action="navigate-object-ref" data-ref-index="${index}">跳转世界对象</button>` : "")
      return trace + navigate
    }).join("")}</div>`
  },

  _isWorldObjectRef(ref) {
    return ["world_entity", "core_entity", "entity", "character"].includes(ref?.target_type)
  },

  async _navigateObjectRef(index) {
    const ref = this._drawerRefs[Number(index)]
    if (!ref?.target_id) return
    let label = ref.target_name || ref.name || ""
    if (!label && api.context?.inspectEvidence) {
      try {
        const result = await api.context.inspectEvidence({
          novel_id: state.currentProjectId,
          content_mode: this._lastSearchPayload?.content_mode || "canonical",
          visibility: this._visibilityFromLastSearch(),
          target_ref: ref,
        }, { signal: this._ensureAbortController().signal })
        label = result.item?.name || ""
      } catch {
        // A stable object jump is still possible by ID if inspection is unavailable.
      }
    }
    const query = new URLSearchParams()
    query.set("q", label || ref.target_id)
    router.navigate("world", "objects", true, query)
  },

  async _traceHit(index) {
    const hit = this._searchHits[Number(index)]
    const ref = hit?.object_refs?.[0] || hit?.target_ref
    if (!ref) return
    this._drawerRefs = [ref]
    await this._traceDrawerRef(0)
  },

  async _traceDrawerRef(index) {
    const ref = this._drawerRefs[Number(index)]
    const drawer = document.getElementById("rag-evidence-drawer")
    if (!ref || !drawer) return
    drawer.hidden = false
    drawer.innerHTML = '<div class="loading">追踪中</div>'
    try {
      const result = await api.context.traceEvidence({
        novel_id: state.currentProjectId,
        content_mode: this._lastSearchPayload?.content_mode || "canonical",
        visibility: this._visibilityFromLastSearch(),
        target_ref: ref,
        claim_path: ref.target_path || "",
      }, { signal: this._ensureAbortController().signal })
      drawer.innerHTML = `
        <div class="novel-evidence-drawer__header"><strong>证据链</strong><button class="btn btn-sm" data-action="close-drawer">关闭</button></div>
        ${(result.links || []).map((link) => `<article class="novel-evidence-trace"><p>${esc(link.read?.text || (link.status === "needs_review" ? "待人工定位原文" : ""))}</p><small>第 ${esc(String(link.source_ref?.chapter_index || "-"))} 章 · ${esc(link.precision || "range")}</small></article>`).join("") || '<p class="rag-search-empty">暂无当前视角可见的原文证据</p>'}
        ${(result.warnings || []).map((item) => `<p class="rag-diagnostics-warning">${esc(item)}</p>`).join("")}
      `
    } catch (err) {
      drawer.innerHTML = `<p class="rag-error-text">追踪失败：${esc(err.message)}</p>`
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
        this._rebuildInfo = "暂无可索引草稿"
        this._updateRebuildProgressDOM()
        toast("暂无可索引草稿", "info")
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
        if (e.key === "Enter") this._doSearch(searchInput.value)
      }
      searchInput.addEventListener("keydown", this._searchEnterHandler)
    }
    const visibilitySelect = document.getElementById("rag-visibility-mode")
    if (visibilitySelect) {
      visibilitySelect.onchange = () => this._toggleVisibilityFields(visibilitySelect.value)
      this._toggleVisibilityFields(visibilitySelect.value)
    }
    const searchKindSelect = document.getElementById("rag-search-kind")
    if (searchKindSelect) {
      searchKindSelect.onchange = () => this._toggleSearchScopes(searchKindSelect.value)
      this._toggleSearchScopes(searchKindSelect.value)
    }

    bindWorkspaceClick(this, {
      "nav-status": () => router.navigate("rag", "status"),
      "nav-search": () => router.navigate("rag", "search"),
      "do-search": () => {
        const val = document.getElementById("rag-search-input")?.value
        if (val) this._doSearch(val)
      },
      "open-hit": (_event, element) => this._openHit(element.dataset.hitIndex),
      "trace-hit": (_event, element) => this._traceHit(element.dataset.hitIndex),
      "trace-drawer-ref": (_event, element) => this._traceDrawerRef(element.dataset.refIndex),
      "navigate-scene-ref": (_event, element) => {
        const ref = this._drawerRefs[Number(element.dataset.refIndex)]
        if (ref?.target_id) router.navigate("scene", ref.target_id)
      },
      "navigate-object-ref": (_event, element) => this._navigateObjectRef(element.dataset.refIndex),
      "navigate-chapter-ref": (_event, element) => {
        const chapterIndex = Number(element.dataset.chapterIndex)
        if (!Number.isInteger(chapterIndex) || chapterIndex < 1) return
        state.viewStates.writing = {
          ...(state.viewStates.writing || {}),
          projectId: state.currentProjectId,
          currentChapter: chapterIndex,
          currentDraftId: null,
          currentVersionNumber: null,
          isReadonly: false,
        }
        router.navigate("writing")
      },
      "close-drawer": () => {
        const drawer = document.getElementById("rag-evidence-drawer")
        if (drawer) drawer.hidden = true
      },
      "rebuild-index": () => this._rebuildIndex(),
      "prewarm-rag": () => this._prewarm(),
      "retry-embeddings": () => this._retryEmbeddings(),
    })
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
}

router.registerView("rag", ragView)
window.ragView = ragView
export default ragView
