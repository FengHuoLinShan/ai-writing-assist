/**
 * RAG 检索视图
 */
const ragView = {
  onLeave() {},

  async render() {
    const subView = _state.currentSubView || "status"
    let html = ''

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "status" ? "active" : ""}" data-subview="status" onclick="router.navigate('rag','status')">索引状态</span>
        <span class="subnav-item ${subView === "search" ? "active" : ""}" data-subview="search" onclick="router.navigate('rag','search')">搜索测试</span>
      </div>
    `

    if (subView === "search") {
      html += `
        <div class="form-group">
          <label>搜索关键词</label>
          <div style="display:flex;gap:8px;">
            <input class="form-input" id="rag-search-input" placeholder="输入搜索关键词..." value="${_state.searchQuery || ""}" style="flex:1;" />
            <button class="btn btn-primary" id="btn-rag-search">搜索</button>
          </div>
        </div>
        <div id="rag-results">
          <div class="empty-state">
            <p style="color:var(--text-dim);font-size:12px;">输入关键词后按 Enter 搜索。</p>
          </div>
        </div>
      `

      setTimeout(() => {
        const input = document.getElementById("rag-search-input")
        const btn = document.getElementById("btn-rag-search")
        if (input && _state.searchQuery) {
          ragView._doSearch(_state.searchQuery)
        }
        if (input) {
          input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") ragView._doSearch(input.value)
          })
        }
        if (btn) {
          btn.addEventListener("click", () => {
            const val = document.getElementById("rag-search-input")?.value
            if (val) ragView._doSearch(val)
          })
        }
      }, 0)
    } else {
      html += `
        <table class="data-table">
          <thead>
            <tr><th>来源类型</th><th>总数量</th><th>已索引</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr><td>世界对象</td><td>-</td><td>-</td><td><span class="badge badge-canonical">正常</span></td></tr>
            <tr><td>人物档案</td><td>-</td><td>-</td><td><span class="badge badge-canonical">正常</span></td></tr>
            <tr><td>长期记忆</td><td>-</td><td>-</td><td><span class="badge badge-canonical">正常</span></td></tr>
            <tr><td>剧情结构</td><td>-</td><td>-</td><td><span class="badge badge-canonical">正常</span></td></tr>
          </tbody>
        </table>
        <div style="margin-top:12px;">
          <button class="btn btn-warning" onclick="toast('正在重建索引...', 'info')">重建索引</button>
          <button class="btn" onclick="router.navigate('rag','search')">测试搜索</button>
        </div>
      `
    }

    return html
  },

  async _doSearch(query) {
    const results = document.getElementById("rag-results")
    if (!results || !query) return

    results.innerHTML = '<div class="loading">搜索中</div>'

    try {
      const data = await api.rag.search({
        novel_id: _state.currentProjectId,
        query,
        top_k: 8,
      })

      const chunks = data.chunks || data || []
      if (chunks.length === 0) {
        results.innerHTML = '<div class="empty-state"><p style="color:var(--text-dim);">未找到匹配结果</p></div>'
        return
      }

      let html = '<div style="margin-top:12px;">'
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
            <div class="card-meta">${chunk.chapter_index ? `第 ${chunk.chapter_index} 章` : ""}</div>
          </div>
        `
      }

      html += "</div>"
      results.innerHTML = html
    } catch (err) {
      results.innerHTML = `<div class="empty-state"><p style="color:var(--danger);">搜索失败：${esc(err.message)}</p></div>`
    }
  },
}

router.registerView("rag", ragView)
window.ragView = ragView
