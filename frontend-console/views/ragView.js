/**
 * RAG 检索视图
 *
 * 子标签：索引状态 | 搜索测试
 */
import { bindWorkspaceClick } from "../shared/viewHelper.js"

const ragView = {
  _totalChunks: null,
  _embeddingFailedCount: 0,
  _statusWarnings: [],
  _statusDegraded: false,
  _loading: true,
  _apiAvailable: false,

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
      this._totalChunks = data.total || 0
      this._embeddingFailedCount = data.embedding_failed_count || 0
      this._statusWarnings = data.warnings || []
      this._statusDegraded = Boolean(data.degraded)
      this._apiAvailable = true
    } catch {
      this._totalChunks = null
      this._embeddingFailedCount = 0
      this._statusWarnings = []
      this._statusDegraded = false
      this._apiAvailable = false
    }
    this._loading = false
  },

  onLeave() {},

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
            <div><strong style="font-size:24px;">${countDisplay}</strong><br><span style="color:var(--text-dim);font-size:12px;">总片段数</span></div>
            <div><strong style="font-size:24px;">${this._embeddingFailedCount}</strong><br><span style="color:var(--text-dim);font-size:12px;">降级片段</span></div>
            <div><span style="font-size:24px;">${statusBadge}</span></div>
          </div>
        </div>
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
      </div>
      <div style="margin-top:12px;display:flex;gap:8px;">
        <button class="btn" data-action="rebuild-index">重建索引</button>
        <button class="btn" data-action="nav-search">测试搜索</button>
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
      const result = await api.rag.rebuild({ novel_id: state.currentProjectId })
      if (result.total > 0) {
        toast("索引重建任务已提交", "success")
      } else {
        toast("暂无可索引草稿", "info")
      }
      for (const warning of (result.warnings || [])) {
        toast(warning, "warning")
      }
      await router.refresh()
    } catch (err) {
      toast(err.message || "重建失败", "error")
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
    })
  },
}

router.registerView("rag", ragView)
window.ragView = ragView
export default ragView
