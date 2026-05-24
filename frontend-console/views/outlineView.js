/**
 * 剧情结构视图
 */
const outlineView = {
  onLeave() {},

  async render() {
    const subView = _state.currentSubView || "threads"
    let html = ''

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-subview="threads" onclick="router.navigate('outline','threads')">剧情线</span>
        <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-subview="arcs" onclick="router.navigate('outline','arcs')">篇章纲</span>
        <span class="subnav-item ${subView === "chapters" ? "active" : ""}" data-subview="chapters" onclick="router.navigate('outline','chapters')">章节卡</span>
        <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-subview="foreshadowing" onclick="router.navigate('outline','foreshadowing')">伏笔计划</span>
        <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-subview="reveals" onclick="router.navigate('outline','reveals')">信息揭示</span>
      </div>
    `

    if (subView === "arcs") {
      html += `
        <div class="card">
          <div class="card-title">篇章纲：旧档案缺页篇</div>
          <div class="card-meta">范围：第 25-34 章</div>
          <div style="margin-top:8px;">
            <p><strong style="color:var(--accent);">目标</strong>：确认旧王都档案被人为替换</p>
            <p><strong style="color:var(--accent);">核心冲突</strong>：主角与女主想查档案，监察院阻止</p>
            <p><strong style="color:var(--accent);">入口钩子</strong>：女主发现编号连续但内容断裂</p>
            <p><strong style="color:var(--accent);">中点反转</strong>：找到的不是缺页，而是假页</p>
            <p><strong style="color:var(--accent);">高潮</strong>：主角用王印异常找到隐藏档案柜</p>
            <p><strong style="color:var(--accent);">下篇钩子</strong>：封条上出现女主家族印记</p>
          </div>
        </div>
      `
    } else if (subView === "chapters") {
      html += `
        <div class="empty-state">
          <div class="empty-icon">&#128196;</div>
          <p>章节卡</p>
          <p style="color:var(--text-dim);font-size:12px;">每章的结构化计划。</p>
          <div style="margin-top:8px;">
            <button class="btn btn-primary" onclick="toast('章节卡功能开发中', 'info')">生成章节卡</button>
          </div>
        </div>
      `
    } else if (subView === "foreshadowing") {
      html += `
        <div class="empty-state">
          <div class="empty-icon">&#128161;</div>
          <p>伏笔计划</p>
          <p style="color:var(--text-dim);font-size:12px;">管理伏笔的埋设、强化和收束计划。</p>
        </div>
      `
    } else if (subView === "reveals") {
      html += `
        <div class="empty-state">
          <div class="empty-icon">&#128065;</div>
          <p>信息揭示计划</p>
          <p style="color:var(--text-dim);font-size:12px;">管理隐藏真相的分阶段揭示。</p>
        </div>
      `
    } else {
      html += `
        <table class="data-table">
          <thead>
            <tr><th>类型</th><th>名称</th><th>当前阶段</th><th>计划回收</th></tr>
          </thead>
          <tbody>
            <tr><td style="color:var(--accent);">主线</td><td>旧王都真相线</td><td>暗示中</td><td>第 360 章</td></tr>
            <tr><td style="color:var(--info);">暗线</td><td>女主家族秘密线</td><td>推进中</td><td>第 180 章</td></tr>
            <tr><td style="color:var(--warning);">关系线</td><td>主角女主信任线</td><td>推进中</td><td>第 120 章</td></tr>
          </tbody>
        </table>
        <div style="margin-top:12px;">
          <button class="btn btn-primary">新建剧情线</button>
          <button class="btn" onclick="router.navigate('outline','arcs')">查看篇章纲</button>
          <button class="btn" onclick="router.navigate('outline','chapters')">查看章节卡</button>
        </div>
      `
    }

    return html
  },
}

router.registerView("outline", outlineView)
window.outlineView = outlineView
