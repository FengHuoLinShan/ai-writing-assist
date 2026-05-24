/**
 * 长期记忆视图
 */
const memoryView = {
  async render() {
    const subView = _state.currentSubView || "records"
    let html = ''

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "records" ? "active" : ""}" data-subview="records" onclick="router.navigate('memory','records')">记忆记录</span>
        <span class="subnav-item ${subView === "proposals" ? "active" : ""}" data-subview="proposals" onclick="router.navigate('memory','proposals')">更新候选</span>
        <span class="subnav-item ${subView === "by_chapter" ? "active" : ""}" data-subview="by_chapter" onclick="router.navigate('memory','by_chapter')">按章节</span>
        <span class="subnav-item ${subView === "by_entity" ? "active" : ""}" data-subview="by_entity" onclick="router.navigate('memory','by_entity')">按对象</span>
      </div>
    `

    if (subView === "proposals") html += this._renderProposals()
    else html += this._renderRecords()

    return html
  },

  _renderRecords() {
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128203;</div>
        <p>长期记忆</p>
        <p style="color:var(--text-dim);font-size:12px;">记录小说推进过程中的状态变化。包括事件、角色状态变化、伏笔触发等。</p>
        <table class="data-table" style="margin-top:12px;">
          <thead>
            <tr><th>章节</th><th>类型</th><th>概要</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr><td colspan="4" style="text-align:center;color:var(--text-dim);">暂无记忆记录</td></tr>
          </tbody>
        </table>
      </div>
    `
  },

  onLeave() {},

  _renderProposals() {
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128221;</div>
        <p>状态更新候选</p>
        <p style="color:var(--text-dim);font-size:12px;">AI 检测到的状态变化候选，需要您确认后才能写入正史记忆库。</p>
        <div style="margin-top:8px;display:flex;gap:8px;justify-content:center;">
          <button class="btn btn-primary">确认全部</button>
          <button class="btn btn-warning">编辑后确认</button>
          <button class="btn btn-danger">拒绝</button>
        </div>
      </div>
    `
  },
}

router.registerView("memory", memoryView)
window.memoryView = memoryView
