/**
 * RAG 检索视图
 *
 * 子标签：索引状态 | 搜索测试
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

  async onEnter() {
    this._loading = true
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
        this._prewarm({ background: true })
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
  },

  onLeave() {
    this._stopRebuildPolling()
  },

  async render() {
    const subView = state.currentSubView || "status"
    let html = ""

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "status" ? "active" : ""}" data-action="nav-status">索引状态</span>
        <span class="subnav-item ${subView === "search" ? "active" : ""}" data-action="nav-search">搜索测试</span>
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

    if (!this._apiAvailable && this._totalChunks === null && !this._loading) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <p>后端未连接</p>
          <p style="color:var(--text-dim);font-size:12px;">请确认后端已启动并连接数据库。</p>
        </div>
      `
    }

    return `
      <div style="margin-bottom:8px;">
        <div class="card" style="margin-bottom:8px;">
          <div class="card-title">RAG 索引概览</div>
          <div style="display:flex;gap:16px;margin-top:8px;">
            <div><strong style="font-size:24px;">${statusBadge}</strong><br><span style="color:var(--text-dim);font-size:12px;">索引是否可用</span></div>
            <div><strong style="font-size:24px;">${countDisplay}</strong><br><span style="color:var(--text-dim);font-size:12px;">已索引章节片段</span></div>
            <div><strong style="font-size:24px;">${this._embeddingFailedCount}</strong><br><span style="color:var(--text-dim);font-size:12px;">降级片段</span></div>
          </div>
        </div>
        <div id="rag-diagnostics">${this._renderDiagnostics()}</div>
        ${this._statusDegraded ? `
          <div class="card" style="margin-bottom:8px;border-color:var(--warning);">
            <div class="card-title" style="font-size:12px;color:var(--warning);">索引不完整</div>
            <p style="font-size:12px;color:var(--text-muted);">${esc((this._statusWarnings || []).join("；") || "部分索引已降级，抽取结果可能不准确。")}</p>
          </div>
        ` : ""}
        ${!this._loading && this._totalChunks === 0 ? `
          <div class="empty-state">
            <div class="empty-icon">&#128194;</div>
            <p>暂无索引数据</p>
            <p style="color:var(--text-dim);font-size:12px;">请先导入正文草稿，然后使用剧情结构提取或深度导入创建索引。</p>
          </div>
        ` : ""}
        <div id="rag-rebuild-progress">${this._renderRebuildProgress()}</div>
        ${this._renderChunkList()}
      </div>
      <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <div style="display:flex;gap:8px;align-items:center;">
          <label style="font-size:12px;color:var(--text-dim);">起始章节</label>
          <input class="form-input" id="rag-rebuild-start" type="number" min="1" placeholder="起始" style="width:70px;" />
          <label style="font-size:12px;color:var(--text-dim);">结束章节</label>
          <input class="form-input" id="rag-rebuild-end" type="number" min="1" placeholder="结束" style="width:70px;" />
        </div>
        <button class="btn" data-action="rebuild-index">重建索引</button>
        <button class="btn" data-action="prewarm-rag">预热检索引擎</button>
        ${this._retryableEmbeddingCount > 0 ? `<button class="btn" data-action="retry-embeddings">重试失败向量</button>` : ""}
        <button class="btn" data-action="nav-search">测试搜索</button>
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
      <p style="margin-top:6px;font-size:12px;color:var(--warning);">${esc(this._prewarmWarning)}</p>
    ` : ""
    return `
      <details class="card rag-diagnostics-card" style="margin-bottom:8px;" ${this._embeddingDimensionMismatch || this._prewarmWarning ? "open" : ""}>
        <summary class="card-title">技术诊断详情</summary>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin-top:8px;font-size:12px;">
          <div><strong>${esc(String(actualDim))}</strong><br><span style="color:var(--text-dim);">实际维度</span></div>
          <div><strong>${esc(String(configuredDim))}</strong><br><span style="color:var(--text-dim);">配置维度</span></div>
          <div><strong>${esc(runtimeLabel)}</strong><br><span style="color:var(--text-dim);">worker</span></div>
          <div><strong>${esc(avg)}</strong><br><span style="color:var(--text-dim);">平均检索</span></div>
          <div><strong>${esc(embeddingAvg)}</strong><br><span style="color:var(--text-dim);">embedding</span></div>
          <div><strong>${esc(degradedRate)}</strong><br><span style="color:var(--text-dim);">降级率</span></div>
          <div><strong>${esc(String(this._retryableEmbeddingCount || 0))}</strong><br><span style="color:var(--text-dim);">可重试</span></div>
          <div><strong>${esc(cacheText)}</strong><br><span style="color:var(--text-dim);">缓存命中/未命中</span></div>
        </div>
        ${this._embeddingDimensionMismatch ? `<p style="margin-top:6px;font-size:12px;color:var(--warning);">向量维度配置漂移，请同步配置后重启后端。</p>` : ""}
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

  async _prewarm() {
    this._prewarmState = "running"
    this._prewarmWarning = ""
    this._updateDiagnosticsDOM()
    try {
      const result = await api.rag.prewarm()
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
    this._updateDiagnosticsDOM()
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
          <p style="color:var(--text-dim);font-size:12px;">${esc(this._rebuildInfo)}</p>
        </div>
      `
    }
    return ""
  },

  _updateRebuildProgressDOM() {
    const el = document.getElementById("rag-rebuild-progress")
    if (el) el.innerHTML = this._renderRebuildProgress()
  },

  _applyRagRebuildResult(result = {}) {
    if (result.total_chapters != null) this._totalChunks = result.chunks_created || this._totalChunks
    if (result.embedding_failed_count != null) this._embeddingFailedCount = result.embedding_failed_count
    if (Array.isArray(result.warnings)) {
      this._statusWarnings = result.warnings
      this._statusDegraded = result.warnings.length > 0 || Boolean(result.embedding_failed_count)
    }
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
        if (workflowType === "rag_retry_embeddings") {
          this._retryableEmbeddingCount = result.remaining_retryable_count ?? result.failed ?? 0
          this._embeddingFailedCount = result.remaining_retryable_count ?? result.failed ?? 0
          this._refreshStatusFromServer()
        } else {
          this._applyRagRebuildResult(result)
        }
        clearActiveWorkflow(taskId)
        this._updateRebuildProgressDOM()
        this._updateDiagnosticsDOM()
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
        <div class="card" style="margin-top:8px;">
          <div class="card-title">最近片段</div>
          <p style="font-size:12px;color:var(--text-dim);">暂无片段数据</p>
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
          <td style="max-width:200px;" title="${esc(plainText)}">${preview}</td>
        </tr>
      `
    }

    return `
      <div class="card" style="margin-top:8px;">
        <div class="card-title">最近片段</div>
        <div style="overflow-x:auto;">
          <table style="width:100%;font-size:12px;border-collapse:collapse;">
            <thead>
              <tr style="text-align:left;color:var(--text-dim);">
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
    return `
      <div class="form-group">
        <label>搜索关键词</label>
        <div style="display:flex;gap:8px;">
          <input class="form-input" id="rag-search-input" placeholder="输入搜索关键词..." value="${esc(state.searchQuery || "")}" style="flex:1;" />
          <button class="btn btn-primary" data-action="do-search">搜索</button>
        </div>
      </div>
      <div id="rag-results">
        <div class="empty-state">
          <p style="color:var(--text-dim);font-size:12px;">输入关键词后搜索。</p>
        </div>
      </div>
    `
  },

  async _doSearch(query) {
    const results = document.getElementById("rag-results")
    if (!results || !query) return

    results.innerHTML = '<div class="loading">搜索中</div>'

    try {
      const data = await api.rag.search({ query, top_k: 8, mode: "search" }, state.currentProjectId)
      const chunks = data.chunks || data || []
      if (chunks.length === 0) {
        results.innerHTML = '<div class="empty-state"><p style="color:var(--text-dim);">未找到匹配结果</p></div>'
        return
      }

      let html = '<div style="margin-top:12px;">'
      if (data.degraded || (data.warnings || []).length > 0) {
        const warnings = (data.warnings || []).map((w) => esc(w)).join("<br>")
        html += `
          <div class="card" style="margin-bottom:8px;border-color:var(--warning);">
            <div class="card-title" style="font-size:12px;color:var(--warning);">本次结果可能不准确</div>
            <p style="font-size:12px;color:var(--text-muted);">${warnings || "检索已降级，请检查索引任务结果。"}</p>
          </div>
        `
      }
      html += `<p style="color:var(--text-muted);font-size:12px;margin-bottom:8px;">找到 ${chunks.length} 条结果</p>`
      for (const chunk of chunks) {
        const sourceType = esc(chunk.source_type || "unknown")
        const text = esc(chunk.text || chunk.summary || chunk.content || "")
        const score = chunk.similarity || chunk.score || ""
        const truncated = text.length > 200 ? text.substring(0, 200) + "..." : text
        html += `
          <div class="card" style="margin-bottom:8px;">
            <div class="card-title" style="font-size:12px;">
              来源：${sourceType}
              ${score ? `<span style="float:right;color:var(--accent);">${(score * 100).toFixed(0)}%</span>` : ""}
            </div>
            <p style="font-size:12px;color:var(--text);">${truncated}</p>
            <div class="card-meta">${chunk.chapter_index ? `第 ${esc(String(chunk.chapter_index))} 章` : ""}</div>
          </div>
        `
      }
      html += "</div>"
      results.innerHTML = html
    } catch (err) {
      results.innerHTML = `<div class="empty-state"><p style="color:var(--danger);">搜索失败：${esc(err.message)}</p></div>`
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
      const startInput = document.getElementById("rag-rebuild-start")
      const endInput = document.getElementById("rag-rebuild-end")
      const startChapter = startInput ? Number(startInput.value) : NaN
      const endChapter = endInput ? Number(endInput.value) : NaN
      if (!Number.isNaN(startChapter) && !Number.isNaN(endChapter) && startChapter >= 1 && endChapter >= 1 && startChapter <= endChapter) {
        payload.start_chapter = startChapter
        payload.end_chapter = endChapter
      }
      const result = await api.rag.rebuild(payload)
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
      })
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

    bindWorkspaceClick(this, {
      "nav-status": () => router.navigate("rag", "status"),
      "nav-search": () => router.navigate("rag", "search"),
      "do-search": () => {
        const val = document.getElementById("rag-search-input")?.value
        if (val) this._doSearch(val)
      },
      "rebuild-index": () => this._rebuildIndex(),
      "prewarm-rag": () => this._prewarm(),
      "retry-embeddings": () => this._retryEmbeddings(),
    })
  },
}

router.registerView("rag", ragView)
window.ragView = ragView
export default ragView
