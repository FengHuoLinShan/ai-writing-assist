/**
 * 时间线视图
 */
const timelineView = {
  onLeave() {},

  async render() {
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128339;</div>
        <p>轻量时间线</p>
        <p style="color:var(--text-dim);font-size:12px;">维护事件顺序，防止剧情冲突和提前揭示。</p>
        <table class="data-table" style="margin-top:12px;max-width:600px;">
          <thead>
            <tr><th>顺序</th><th>章节</th><th>事件</th><th>可见性</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr><td colspan="5" style="text-align:center;color:var(--text-dim);">暂无时间线事件</td></tr>
          </tbody>
        </table>
        <div style="margin-top:12px;">
          <button class="btn btn-primary" onclick="toast('时间线功能开发中', 'info')">新建事件</button>
          <button class="btn btn-warning" onclick="toast('冲突检查功能开发中', 'info')">冲突检查</button>
        </div>
      </div>
    `
  },
}

router.registerView("timeline", timelineView)
window.timelineView = timelineView
