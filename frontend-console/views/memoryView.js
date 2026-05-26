/**
 * 长期记忆视图
 *
 * 对应后端 memory_records + memory_update_proposals。
 */

const memoryView = {
  _records: [],
  _proposals: [],

  async onEnter() {
    this._records = []
    this._proposals = []
    await Promise.all([this._loadRecords(), this._loadProposals()])
  },

  async render() {
    const subView = _state.currentSubView || "records"

    setTimeout(() => {
      const content = document.getElementById("workspace-content")
      if (!content) return
      content.removeEventListener("click", this._clickHandler)
      this._clickHandler = (e) => {
        const target = e.target.closest("[data-action]")
        if (!target) return
        const action = target.getAttribute("data-action")
        const id = target.getAttribute("data-id")
        switch (action) {
          case "nav-records": router.navigate("memory", "records"); break
          case "nav-proposals": router.navigate("memory", "proposals"); break
          case "confirm-proposal": if (id) this.confirmProposal(id); break
          case "reject-proposal": if (id) this.rejectProposal(id); break
        }
      }
      content.addEventListener("click", this._clickHandler)
    }, 0)

    let html = ''
    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "records" ? "active" : ""}" data-action="nav-records">记忆记录</span>
        <span class="subnav-item ${subView === "proposals" ? "active" : ""}" data-action="nav-proposals">更新候选</span>
      </div>
    `
    if (subView === "proposals") html += await this._renderProposals()
    else html += await this._renderRecords()
    return html
  },

  async _loadRecords() {
    if (!_state.currentProjectId) return
    try {
      const data = await api.memory.listRecords({ novel_id: _state.currentProjectId })
      this._records = data.items || data || []
    } catch { this._records = [] }
  },

  async _loadProposals() {
    if (!_state.currentProjectId) return
    try {
      const data = await api.memory.listProposals(_state.currentProjectId)
      this._proposals = data.items || data || []
    } catch { this._proposals = [] }
  },

  async _renderRecords() {
    if (!_state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }
    if (this._records.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128203;</div>
          <p>暂无记忆记录。</p>
          <p style="color:var(--text-dim);font-size:12px;">记忆记录记录小说推进中的状态变化。</p>
        </div>
      `
    }
    const typeMap = {
      chapter_state: "章节状态", event: "事件", character_state: "角色状态",
      knowledge: "知识变化", foreshadowing: "伏笔状态", outline_drift: "大纲偏离",
    }
    let html = `<table class="data-table"><thead><tr><th>章节</th><th>类型</th><th>标题</th><th>摘要</th><th>状态</th></tr></thead><tbody>`
    for (const r of this._records) {
      html += `
        <tr>
          <td>${esc(r.chapter_index) || "-"}</td>
          <td><span class="badge badge-draft">${typeMap[r.memory_type] || esc(r.memory_type)}</span></td>
          <td>${esc(r.title || "")}</td>
          <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(r.summary || "")}</td>
          <td><span class="badge badge-${r.status || "canonical"}">${r.status === "canonical" ? "正史" : esc(r.status)}</span></td>
        </tr>`
    }
    html += '</tbody></table>'
    return html
  },

  async _renderProposals() {
    if (!_state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }
    if (this._proposals.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128221;</div>
          <p>没有待处理的更新候选。</p>
          <p style="color:var(--text-dim);font-size:12px;">AI 检测到的状态变化会出现在这里，供您确认。</p>
        </div>
      `
    }
    let html = `<table class="data-table"><thead><tr><th>类型</th><th>摘要</th><th>置信度</th><th>来源</th><th>操作</th></tr></thead><tbody>`
    for (const p of this._proposals) {
      html += `
        <tr data-id="${esc(p.id || p.proposal_id)}">
          <td><span class="badge badge-draft">${esc(p.proposal_type || p.memory_type || "-")}</span></td>
          <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(p.summary || p.reason || "")}</td>
          <td>${p.confidence ? (p.confidence * 100).toFixed(0) + "%" : "-"}</td>
          <td style="color:var(--text-dim);font-size:11px;">${esc((p.source_text_excerpt || "").slice(0, 50))}</td>
          <td style="display:flex;gap:4px;">
            <button class="btn btn-sm btn-primary" data-action="confirm-proposal" data-id="${esc(p.id || p.proposal_id)}">确认</button>
            <button class="btn btn-sm btn-danger" data-action="reject-proposal" data-id="${esc(p.id || p.proposal_id)}">拒绝</button>
          </td>
        </tr>`
    }
    html += '</tbody></table>'
    return html
  },

  async confirmProposal(proposalId) {
    try {
      await api.memory.confirmProposal(_state.currentProjectId, proposalId, {})
      toast("提案已确认", "success")
      router.navigate("memory", "proposals")
    } catch (err) { toast(err.message || "确认失败", "error") }
  },

  async rejectProposal(proposalId) {
    confirmAction("确定拒绝此提案？", async () => {
      try {
        await api.memory.rejectProposal(_state.currentProjectId, proposalId, "user")
        toast("已拒绝", "success")
        router.navigate("memory", "proposals")
      } catch (err) { toast(err.message || "操作失败", "error") }
    }, "拒绝")
  },
}

router.registerView("memory", memoryView)
window.memoryView = memoryView
export default memoryView
