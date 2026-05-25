/**
 * 剧情结构视图
 *
 * 子标签：剧情线 | 篇章纲 | 章节卡 | 伏笔计划 | 信息揭示
 * 后端 5 组 CRUD 全部覆盖。
 */
const outlineView = {
  _threads: [],
  _arcs: [],
  _chapters: [],
  _foreshadowing: [],
  _reveals: [],

  async onEnter() {
    await Promise.all([
      this._loadThreads(), this._loadArcs(),
      this._loadChapters(), this._loadForeshadowing(), this._loadReveals(),
    ])
  },

  async render() {
    const subView = _state.currentSubView || "threads"
    let html = `
      <div class="subnav">
        <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-subview="threads" onclick="router.navigate('outline','threads')">剧情线</span>
        <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-subview="arcs" onclick="router.navigate('outline','arcs')">篇章纲</span>
        <span class="subnav-item ${subView === "chapters" ? "active" : ""}" data-subview="chapters" onclick="router.navigate('outline','chapters')">章节卡</span>
        <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-subview="foreshadowing" onclick="router.navigate('outline','foreshadowing')">伏笔计划</span>
        <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-subview="reveals" onclick="router.navigate('outline','reveals')">信息揭示</span>
      </div>`
    if (subView === "threads") html += await this._renderThreads()
    else if (subView === "arcs") html += await this._renderArcs()
    else if (subView === "chapters") html += await this._renderChapters()
    else if (subView === "foreshadowing") html += await this._renderForeshadowing()
    else if (subView === "reveals") html += await this._renderReveals()
    return html
  },

  async _loadThreads() {
    if (!_state.currentProjectId) { this._threads = []; return }
    try { const d = await api.outline.listThreads({ novel_id: _state.currentProjectId }); this._threads = d.items || d || [] }
    catch { this._threads = [] }
  },
  async _loadArcs() {
    if (!_state.currentProjectId) { this._arcs = []; return }
    try { const d = await api.outline.listArcs({ novel_id: _state.currentProjectId }); this._arcs = d.items || d || [] }
    catch { this._arcs = [] }
  },
  async _loadChapters() {
    if (!_state.currentProjectId) { this._chapters = []; return }
    try { const d = await api.outline.listChapterCards({ novel_id: _state.currentProjectId }); this._chapters = d.items || d || [] }
    catch { this._chapters = [] }
  },
  async _loadForeshadowing() {
    if (!_state.currentProjectId) { this._foreshadowing = []; return }
    try { const d = await api.outline.listForeshadowing({ novel_id: _state.currentProjectId }); this._foreshadowing = d.items || d || [] }
    catch { this._foreshadowing = [] }
  },
  async _loadReveals() {
    if (!_state.currentProjectId) { this._reveals = []; return }
    try { const d = await api.outline.listReveals({ novel_id: _state.currentProjectId }); this._reveals = d.items || d || [] }
    catch { this._reveals = [] }
  },

  // ============ 剧情线 ============

  async _renderThreads() {
    if (!_state.currentProjectId) return empty("请先选择项目。")
    const typeMap = { main: "主线", secondary: "支线", hidden: "暗线", relationship: "关系线", villain: "反派线", foreshadowing: "伏笔线" }
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">管理主线、支线、暗线等剧情线。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" onclick="outlineView._createThread()">新建剧情线</button></div>`
    if (!this._threads.length) return html + empty("暂无剧情线。")
    html += `<table class="data-table"><thead><tr><th>类型</th><th>名称</th><th>阶段</th><th>回收章节</th><th>操作</th></tr></thead><tbody>`
    for (const t of this._threads) {
      html += `<tr data-id="${esc(t.id || t.thread_id)}">
        <td><span class="badge badge-draft">${typeMap[t.thread_type] || esc(t.thread_type)}</span></td>
        <td><strong>${esc(t.name)}</strong></td>
        <td style="color:var(--text-dim);font-size:12px;">${esc(t.current_stage || "-")}</td>
        <td>${t.planned_payoff_chapter ? "第" + t.planned_payoff_chapter + "章" : "-"}</td>
        <td><button class="btn btn-sm btn-danger" onclick="outlineView._deleteThread('${esc(t.id || t.thread_id)}')">删除</button></td>
      </tr>`
    }
    html += `</tbody></table>`
    return html
  },

  _createThread() {
    const formHtml = `
      <div class="form-group"><label>名称 *</label><input class="form-input" id="th-name" /></div>
      <div class="form-group"><label>类型</label>
        <select class="form-select" id="th-type">
          <option value="main">主线</option><option value="secondary">支线</option>
          <option value="hidden">暗线</option><option value="relationship">关系线</option>
          <option value="villain">反派线</option><option value="foreshadowing">伏笔线</option>
        </select>
      </div>
      <div class="form-group"><label>概要</label><textarea class="form-textarea" id="th-summary" rows="2"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label>起始章节</label><input class="form-input" id="th-start" type="number" min="1" /></div>
        <div class="form-group"><label>计划回收章节</label><input class="form-input" id="th-end" type="number" min="1" /></div>
      </div>`
    showModal("新建剧情线", formHtml, [{ text: "创建", class: "btn-primary", handler: async () => {
      const name = document.getElementById("th-name")?.value
      if (!name) { toast("请输入名称", "warning"); return }
      await api.outline.createThread({ novel_id: _state.currentProjectId, name,
        thread_type: document.getElementById("th-type")?.value || "main",
        summary: document.getElementById("th-summary")?.value || "",
        start_chapter: parseInt(document.getElementById("th-start")?.value) || undefined,
        planned_payoff_chapter: parseInt(document.getElementById("th-end")?.value) || undefined,
      }); toast("已创建", "success"); router.navigate("outline", "threads")
    } }])
  },

  _deleteThread(id) {
    confirmAction("确定删除此剧情线？", async () => {
      try { await api.outline.deleteThread(id, { novel_id: _state.currentProjectId }); toast("已删除", "success"); router.navigate("outline", "threads") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============ 篇章纲 ============

  async _renderArcs() {
    if (!_state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">8-15 章的小剧情闭环。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" onclick="outlineView._createArc()">新建篇章纲</button></div>`
    if (!this._arcs.length) return html + empty("暂无篇章纲。")
    for (const a of this._arcs) {
      html += `<div class="card" style="margin-bottom:8px;">
        <div class="card-title">${esc(a.title)} <span style="font-size:11px;color:var(--text-dim);">(${a.start_chapter || "?"}-${a.end_chapter || "?"}章)</span></div>
        <div style="font-size:12px;margin-top:4px;">
          <span style="color:var(--accent);">目标</span>：${esc(a.arc_goal || "-")}<br>
          <span style="color:var(--warning);">冲突</span>：${esc(a.core_conflict || "-")}<br>
          <span style="color:var(--info);">高潮</span>：${esc(a.climax || "-")}
        </div>
        <div style="margin-top:6px;"><button class="btn btn-sm btn-danger" onclick="outlineView._deleteArc('${esc(a.id || a.arc_id)}')">删除</button></div>
      </div>`
    }
    return html
  },

  _createArc() {
    const formHtml = `
      <div class="form-group"><label>标题 *</label><input class="form-input" id="arc-title" /></div>
      <div class="form-row">
        <div class="form-group"><label>起始章</label><input class="form-input" id="arc-start" type="number" min="1" /></div>
        <div class="form-group"><label>结束章</label><input class="form-input" id="arc-end" type="number" min="1" /></div>
      </div>
      <div class="form-group"><label>篇章目标</label><textarea class="form-textarea" id="arc-goal" rows="2"></textarea></div>
      <div class="form-group"><label>核心冲突</label><textarea class="form-textarea" id="arc-conflict" rows="2"></textarea></div>
      <div class="form-group"><label>入口钩子</label><input class="form-input" id="arc-hook" /></div>
      <div class="form-group"><label>高潮</label><textarea class="form-textarea" id="arc-climax" rows="2"></textarea></div>`
    showModal("新建篇章纲", formHtml, [{ text: "创建", class: "btn-primary", handler: async () => {
      const title = document.getElementById("arc-title")?.value
      if (!title) { toast("请输入标题", "warning"); return }
      await api.outline.createArc({ novel_id: _state.currentProjectId, title,
        start_chapter: parseInt(document.getElementById("arc-start")?.value) || undefined,
        end_chapter: parseInt(document.getElementById("arc-end")?.value) || undefined,
        arc_goal: document.getElementById("arc-goal")?.value || "",
        core_conflict: document.getElementById("arc-conflict")?.value || "",
        entry_hook: document.getElementById("arc-hook")?.value || "",
        climax: document.getElementById("arc-climax")?.value || "",
      }); toast("已创建", "success"); router.navigate("outline", "arcs")
    } }])
  },

  _deleteArc(id) {
    confirmAction("确定删除此篇章纲？", async () => {
      try { await api.outline.deleteArc(id, { novel_id: _state.currentProjectId }); toast("已删除", "success"); router.navigate("outline", "arcs") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============ 章节卡 ============

  async _renderChapters() {
    if (!_state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">每章的结构化计划：目标、冲突、禁止事项、钩子。</p>
      <div style="margin-bottom:8px;display:flex;gap:8px;">
        <button class="btn btn-primary" onclick="outlineView._createChapter()">新建章节卡</button>
      </div>`
    if (!this._chapters.length) return html + empty("暂无章节卡。")
    html += `<table class="data-table"><thead><tr><th>章</th><th>标题</th><th>目标</th><th>冲突</th><th>状态</th><th>操作</th></tr></thead><tbody>`
    for (const c of this._chapters) {
      html += `<tr class="clickable" onclick="outlineView._viewChapter('${esc(c.id || c.card_id)}')">
        <td>${c.chapter_index || "-"}</td>
        <td><strong>${esc(c.title || "")}</strong></td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(c.chapter_goal || "")}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(c.main_conflict || "")}</td>
        <td><span class="badge badge-${c.status || "draft"}">${esc(c.status || "draft")}</span></td>
        <td><button class="btn btn-sm btn-danger" onclick="event.stopPropagation();outlineView._deleteChapter('${esc(c.id || c.card_id)}')">删除</button></td>
      </tr>`
    }
    html += `</tbody></table>`
    return html
  },

  _createChapter() {
    const formHtml = `
      <div class="form-row">
        <div class="form-group"><label>章节序号 *</label><input class="form-input" id="ch-index" type="number" min="1" value="${this._chapters.length + 1}" /></div>
        <div class="form-group"><label>标题</label><input class="form-input" id="ch-title" /></div>
      </div>
      <div class="form-group"><label>核心目标</label><textarea class="form-textarea" id="ch-goal" rows="2"></textarea></div>
      <div class="form-group"><label>主要冲突</label><textarea class="form-textarea" id="ch-conflict" rows="2"></textarea></div>
      <div class="form-group"><label>尾钩</label><textarea class="form-textarea" id="ch-hook" rows="1"></textarea></div>`
    showModal("新建章节卡", formHtml, [{ text: "创建", class: "btn-primary", handler: async () => {
      const idx = parseInt(document.getElementById("ch-index")?.value)
      if (!idx) { toast("请输入章节序号", "warning"); return }
      await api.outline.createChapterCard({ novel_id: _state.currentProjectId,
        chapter_index: idx, title: document.getElementById("ch-title")?.value || "",
        chapter_goal: document.getElementById("ch-goal")?.value || "",
        main_conflict: document.getElementById("ch-conflict")?.value || "",
        ending_hook: document.getElementById("ch-hook")?.value || "",
      }); toast("已创建", "success"); router.navigate("outline", "chapters")
    } }])
  },

  async _viewChapter(cardId) {
    try {
      const c = await api.outline.getChapterCard(cardId)
      const body = `
        <p><strong>章节：</strong>${c.chapter_index || "-"}</p>
        <p><strong>标题：</strong>${esc(c.title || "-")}</p>
        <p><strong>目标：</strong>${esc(c.chapter_goal || "-")}</p>
        <p><strong>冲突：</strong>${esc(c.main_conflict || "-")}</p>
        <p><strong>尾钩：</strong>${esc(c.ending_hook || "-")}</p>
        ${c.scene_cards?.length ? `<p><strong>场景卡：</strong>${c.scene_cards.length} 个</p>` : ""}
        ${c.must_not_happen?.length ? `<p style="color:var(--danger);"><strong>禁止事项：</strong>${esc(c.must_not_happen.join("；"))}</p>` : ""}`
      showModal("章节卡详情", body, [{ text: "关闭", handler: () => {} }])
    } catch (e) { toast(e.message || "加载失败", "error") }
  },

  _deleteChapter(id) {
    confirmAction("确定删除此章节卡？", async () => {
      try { await api.outline.deleteChapterCard(id, { novel_id: _state.currentProjectId }); toast("已删除", "success"); router.navigate("outline", "chapters") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============ 伏笔计划 ============

  async _renderForeshadowing() {
    if (!_state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">管理伏笔的埋设、强化和收束计划。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" onclick="outlineView._createForeshadowing()">新建伏笔</button></div>`
    if (!this._foreshadowing.length) return html + empty("暂无伏笔计划。")
    html += `<table class="data-table"><thead><tr><th>名称</th><th>埋设章</th><th>收束章</th><th>状态</th><th>操作</th></tr></thead><tbody>`
    for (const f of this._foreshadowing) {
      html += `<tr data-id="${esc(f.id || f.foreshadow_id)}">
        <td><strong>${esc(f.name)}</strong></td>
        <td>${f.planned_seed_chapter ? "第" + f.planned_seed_chapter + "章" : "-"}</td>
        <td>${f.planned_payoff_chapter ? "第" + f.planned_payoff_chapter + "章" : "-"}</td>
        <td><span class="badge badge-draft">${esc(f.status || "draft")}</span></td>
        <td><button class="btn btn-sm btn-danger" onclick="outlineView._deleteForeshadowing('${esc(f.id || f.foreshadow_id)}')">删除</button></td>
      </tr>`
    }
    html += `</tbody></table>`
    return html
  },

  _createForeshadowing() {
    const formHtml = `
      <div class="form-group"><label>伏笔名称 *</label><input class="form-input" id="fs-name" /></div>
      <div class="form-group"><label>概要</label><textarea class="form-textarea" id="fs-summary" rows="2"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label>表面含义</label><input class="form-input" id="fs-surface" /></div>
        <div class="form-group"><label>隐藏含义</label><input class="form-input" id="fs-hidden" /></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>埋设章节</label><input class="form-input" id="fs-seed" type="number" min="1" /></div>
        <div class="form-group"><label>收束章节</label><input class="form-input" id="fs-payoff" type="number" min="1" /></div>
      </div>`
    showModal("新建伏笔", formHtml, [{ text: "创建", class: "btn-primary", handler: async () => {
      const name = document.getElementById("fs-name")?.value
      if (!name) { toast("请输入名称", "warning"); return }
      await api.outline.createForeshadowing({ novel_id: _state.currentProjectId, name,
        summary: document.getElementById("fs-summary")?.value || "",
        surface_meaning: document.getElementById("fs-surface")?.value || "",
        hidden_meaning: document.getElementById("fs-hidden")?.value || "",
        planned_seed_chapter: parseInt(document.getElementById("fs-seed")?.value) || undefined,
        planned_payoff_chapter: parseInt(document.getElementById("fs-payoff")?.value) || undefined,
      }); toast("已创建", "success"); router.navigate("outline", "foreshadowing")
    } }])
  },

  _deleteForeshadowing(id) {
    confirmAction("确定删除此伏笔？", async () => {
      try { await api.outline.deleteForeshadowing(id, { novel_id: _state.currentProjectId }); toast("已删除", "success"); router.navigate("outline", "foreshadowing") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============ 信息揭示 ============

  async _renderReveals() {
    if (!_state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">管理隐藏真相的分阶段揭示计划。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" onclick="outlineView._createReveal()">新建揭示计划</button></div>`
    if (!this._reveals.length) return html + empty("暂无揭示计划。")
    html += `<table class="data-table"><thead><tr><th>目标</th><th>秘密摘要</th><th>揭示阶段</th><th>状态</th><th>操作</th></tr></thead><tbody>`
    for (const r of this._reveals) {
      const stages = r.reveal_stages?.length || 0
      html += `<tr data-id="${esc(r.id || r.reveal_id)}">
        <td style="font-size:12px;">${esc(r.target_type || "")}:${esc(r.target_id || "").slice(0, 8)}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--text-dim);">${esc(r.secret_summary || "")}</td>
        <td>${stages} 个阶段</td>
        <td><span class="badge badge-draft">${esc(r.status || "draft")}</span></td>
        <td><button class="btn btn-sm btn-danger" onclick="outlineView._deleteReveal('${esc(r.id || r.reveal_id)}')">删除</button></td>
      </tr>`
    }
    html += `</tbody></table>`
    return html
  },

  _createReveal() {
    const formHtml = `
      <div class="form-group"><label>目标类型</label>
        <select class="form-select" id="rv-type">
          <option value="world_entity">世界对象</option>
          <option value="character">人物</option>
          <option value="secret">秘密</option>
        </select>
      </div>
      <div class="form-group"><label>目标 ID</label><input class="form-input" id="rv-target" placeholder="对象 UUID" /></div>
      <div class="form-group"><label>秘密概要</label><textarea class="form-textarea" id="rv-secret" rows="2"></textarea></div>`
    showModal("新建揭示计划", formHtml, [{ text: "创建", class: "btn-primary", handler: async () => {
      const targetId = document.getElementById("rv-target")?.value
      if (!targetId) { toast("请输入目标 ID", "warning"); return }
      await api.outline.createReveal({ novel_id: _state.currentProjectId,
        target_type: document.getElementById("rv-type")?.value || "world_entity",
        target_id: targetId,
        secret_summary: document.getElementById("rv-secret")?.value || "",
      }); toast("已创建", "success"); router.navigate("outline", "reveals")
    } }])
  },

  _deleteReveal(id) {
    confirmAction("确定删除此揭示计划？", async () => {
      try { await api.outline.deleteReveal(id, { novel_id: _state.currentProjectId }); toast("已删除", "success"); router.navigate("outline", "reveals") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },
}

function empty(msg) { return `<div class="empty-state"><p>${msg}</p></div>` }

router.registerView("outline", outlineView)
window.outlineView = outlineView
