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

  /** 提取任务状态：{ taskId, status, message } */
  _extractionTasks: {
    world: { taskId: null, status: "idle", message: "" },
    plot: { taskId: null, status: "idle", message: "" },
    cards: { taskId: null, status: "idle", message: "" },
  },
  _extractionTimer: null,

  async onEnter() {
    const hasRunning = Object.values(this._extractionTasks).some((t) => t.status === "running")
    if (!hasRunning && this._extractionTimer) { clearInterval(this._extractionTimer); this._extractionTimer = null }
    await Promise.all([
      this._loadThreads(), this._loadArcs(),
      this._loadChapters(), this._loadForeshadowing(), this._loadReveals(),
    ])
  },

  onLeave() {
    if (this._extractionTimer) {
      clearInterval(this._extractionTimer)
      this._extractionTimer = null
    }
  },

  async render() {
    const subView = state.currentSubView || "threads"
    let html = `
      <div class="subnav">
        <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-subview="threads" data-action="nav-threads">剧情线</span>
        <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-subview="arcs" data-action="nav-arcs">篇章纲</span>
        <span class="subnav-item ${subView === "chapters" ? "active" : ""}" data-subview="chapters" data-action="nav-chapters">章节卡</span>
        <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-subview="foreshadowing" data-action="nav-foreshadowing">伏笔计划</span>
        <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-subview="reveals" data-action="nav-reveals">信息揭示</span>
      </div>`
    html += this._renderExtractionPanel()
    if (subView === "threads") html += await this._renderThreads()
    else if (subView === "arcs") html += await this._renderArcs()
    else if (subView === "chapters") html += await this._renderChapters()
    else if (subView === "foreshadowing") html += await this._renderForeshadowing()
    else if (subView === "reveals") html += await this._renderReveals()
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  async _loadThreads() {
    if (!state.currentProjectId) { this._threads = []; return }
    try { const d = await api.outline.listThreads({ novel_id: state.currentProjectId }); this._threads = d.items || d || [] }
    catch { this._threads = [] }
  },
  async _loadArcs() {
    if (!state.currentProjectId) { this._arcs = []; return }
    try { const d = await api.outline.listArcs({ novel_id: state.currentProjectId }); this._arcs = d.items || d || [] }
    catch { this._arcs = [] }
  },
  async _loadChapters() {
    if (!state.currentProjectId) { this._chapters = []; return }
    try { const d = await api.outline.listChapterCards({ novel_id: state.currentProjectId }); this._chapters = d.items || d || [] }
    catch { this._chapters = [] }
  },
  async _loadForeshadowing() {
    if (!state.currentProjectId) { this._foreshadowing = []; return }
    try { const d = await api.outline.listForeshadowing({ novel_id: state.currentProjectId }); this._foreshadowing = d.items || d || [] }
    catch { this._foreshadowing = [] }
  },
  async _loadReveals() {
    if (!state.currentProjectId) { this._reveals = []; return }
    try { const d = await api.outline.listReveals({ novel_id: state.currentProjectId }); this._reveals = d.items || d || [] }
    catch { this._reveals = [] }
  },

  // ============ 剧情线 ============

  async _renderThreads() {
    if (!state.currentProjectId) return empty("请先选择项目。")
    const typeMap = { main: "主线", secondary: "支线", hidden: "暗线", relationship: "关系线", villain: "反派线", foreshadowing: "伏笔线" }
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">管理主线、支线、暗线等剧情线。</p>
      <div style="text-align:center;margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-thread">新建剧情线</button>
      </div>`
    if (!this._threads.length) return html + empty("暂无剧情线。")
    html += `<table class="data-table"><thead><tr><th>类型</th><th>名称</th><th>阶段</th><th>回收章节</th><th>操作</th></tr></thead><tbody>`
    for (const t of this._threads) {
      html += `<tr data-id="${esc(t.id || t.thread_id)}">
        <td><span class="badge badge-draft">${typeMap[t.thread_type] || esc(t.thread_type)}</span></td>
        <td><strong>${esc(t.name)}</strong></td>
        <td style="color:var(--text-dim);font-size:12px;">${esc(t.current_stage || "-")}</td>
        <td>${t.planned_payoff_chapter ? "第" + t.planned_payoff_chapter + "章" : "-"}</td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-thread" data-id="${esc(t.id || t.thread_id)}">删除</button></td>
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
      try {
        await api.outline.createThread({ name,
          thread_type: document.getElementById("th-type")?.value || "main",
          summary: document.getElementById("th-summary")?.value || "",
          start_chapter: parseInt(document.getElementById("th-start")?.value) || undefined,
          planned_payoff_chapter: parseInt(document.getElementById("th-end")?.value) || undefined,
        }, state.currentProjectId)
        toast("已创建", "success")
        await this._loadThreads()
        router.navigate("outline", "threads")
      } catch (err) { toast(err.message || "操作失败", "error") }
    } }])
  },

  _deleteThread(id) {
    confirmAction("确定删除此剧情线？", async () => {
      try { await api.outline.deleteThread(id, { novel_id: state.currentProjectId }); toast("已删除", "success"); await this._loadThreads(); router.navigate("outline", "threads") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============================================================
  // 统一提取面板
  // ============================================================

  _renderExtractionPanel() {
    const steps = [
      {
        key: "world",
        label: "1. 世界对象抽取",
        desc: "从正文识别地点、组织、物品、人物等世界对象候选",
        taskType: "world_entity_extraction",
      },
      {
        key: "plot",
        label: "2. 剧情线/篇章纲生成",
        desc: "基于正文分析生成剧情线和篇章结构",
        taskType: "plot_structure_generate",
      },
      {
        key: "cards",
        label: "3. 章节卡提取",
        desc: "逐章提取核心目标、主要冲突、场景细纲等",
        taskType: "chapter_card_extraction",
      },
    ]

    let html = `
      <details open style="border:1px solid var(--border);border-radius:4px;padding:8px 10px;margin-bottom:12px;font-size:12px;">
        <summary style="cursor:pointer;font-weight:bold;color:var(--text);">📥 剧情结构提取</summary>
        <div style="margin-top:6px;">
          <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
            <span style="color:var(--text-dim);">章节：</span>
            <input type="number" id="ext-start" min="1" value="1" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;" />
            <span style="color:var(--text-dim);">~</span>
            <input type="number" id="ext-end" min="1" value="10" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;" />
          </div>
    `

    for (const step of steps) {
      const s = this._extractionTasks[step.key]
      const isRunning = s.status === "running"
      const isDone = s.status === "done"
      const isFailed = s.status === "failed"
      const icon = isRunning ? "⏳" : isDone ? "✅" : isFailed ? "❌" : "☐"
      const btnLabel = isRunning ? "运行中..." : "开始"

      html += `
        <div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-top:1px solid var(--border);">
          <span style="font-size:11px;${isRunning ? 'color:var(--accent);' : isDone ? 'color:var(--text-dim);' : 'color:var(--text);'}">${icon} ${step.label}</span>
          <span style="font-size:10px;color:var(--text-dim);flex:1;">${step.desc}</span>
          <button class="btn btn-sm" data-action="submit-extraction" data-key="${step.key}" data-task-type="${step.taskType}"
            ${isRunning ? 'disabled' : ''} style="font-size:10px;white-space:nowrap;">${btnLabel}</button>
          ${s.message ? `<span style="font-size:10px;color:var(--text-dim);">${s.message}</span>` : ""}
        </div>
      `
    }

    html += '</div></details>'
    return html
  },

  async _submitExtraction(stepKey, taskType) {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const start = parseInt(document.getElementById("ext-start")?.value || "1", 10)
    const end = parseInt(document.getElementById("ext-end")?.value || "10", 10)
    if (start > end) { toast("起始章节不能大于结束章节", "warning"); return }

    // 步骤 3（章节卡）需要跳过确认
    if (stepKey === "cards") {
      this._submitChapterCardExtraction()
      return
    }

    try {
      const result = await api.tasks.submit(taskType, {
        novel_id: state.currentProjectId, start_chapter: start, end_chapter: end,
      })
      this._extractionTasks[stepKey] = { taskId: result.task_id, status: "running", message: "" }
      toast("任务已提交", "info")
      router.navigate("outline", state.currentSubView)

      // 启动共享轮询
      this._startPolling()
    } catch (err) {
      this._extractionTasks[stepKey] = { taskId: null, status: "failed", message: err.message }
      router.navigate("outline", state.currentSubView)
      toast(err.message || "提交失败", "error")
    }
  },

  _startPolling() {
    if (this._extractionTimer) return  // 已有轮询
    this._extractionTimer = setInterval(() => this._pollExtractionTasks(), 3000)
  },

  async _pollExtractionTasks() {
    const running = Object.entries(this._extractionTasks).filter(([, v]) => v.status === "running")
    if (running.length === 0) {
      clearInterval(this._extractionTimer)
      this._extractionTimer = null
      return
    }

    for (const [key, task] of running) {
      try {
        const data = await api.tasks.getStatus(task.taskId)
        if (data.status === "done") {
          this._extractionTasks[key] = { ...task, status: "done", message: "完成" }
          toast(`步骤完成：${key === "world" ? "世界对象抽取" : key === "plot" ? "剧情结构生成" : "章节卡提取"}`, "success")
        } else if (data.status === "failed") {
          this._extractionTasks[key] = { ...task, status: "failed", message: data.error_message || "失败" }
          toast(`步骤失败：${data.error_message || "未知错误"}`, "error")
        } else if (data.status === "cancelled") {
          this._extractionTasks[key] = { ...task, status: "idle", message: "已取消" }
        }
        // running 状态不更新 — 下次轮询再检查
      } catch {
        // 轮询失败，静默重试
      }
    }
  },

  // ============ 篇章纲 ============

  async _renderArcs() {
    if (!state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">8-15 章的小剧情闭环。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" data-action="create-arc">新建篇章纲</button></div>`
    if (!this._arcs.length) return html + empty("暂无篇章纲。")
    for (const a of this._arcs) {
      html += `<div class="card" style="margin-bottom:8px;">
        <div class="card-title">${esc(a.title)} <span style="font-size:11px;color:var(--text-dim);">(${a.start_chapter || "?"}-${a.end_chapter || "?"}章)</span></div>
        <div style="font-size:12px;margin-top:4px;">
          <span style="color:var(--accent);">目标</span>：${esc(a.arc_goal || "-")}<br>
          <span style="color:var(--warning);">冲突</span>：${esc(a.core_conflict || "-")}<br>
          <span style="color:var(--info);">高潮</span>：${esc(a.climax || "-")}
        </div>
        <div style="margin-top:6px;"><button class="btn btn-sm btn-danger" data-action="delete-arc" data-id="${esc(a.id || a.arc_id)}">删除</button></div>
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
      <div class="form-group"><label>高潮</label><textarea class="form-textarea" id="arc-climax" rows="2"></textarea></div>
      <div class="form-group"><label>结果 *</label><textarea class="form-textarea" id="arc-result" rows="2"></textarea></div>`
    showModal("新建篇章纲", formHtml, [{ text: "创建", class: "btn-primary", handler: async () => {
      const title = document.getElementById("arc-title")?.value
      if (!title) { toast("请输入标题", "warning"); return }
      const result = document.getElementById("arc-result")?.value
      if (!result) { toast("请输入结果", "warning"); return }
      try {
        await api.outline.createArc({ title,
          start_chapter: parseInt(document.getElementById("arc-start")?.value) || undefined,
          end_chapter: parseInt(document.getElementById("arc-end")?.value) || undefined,
          arc_goal: document.getElementById("arc-goal")?.value || "",
          core_conflict: document.getElementById("arc-conflict")?.value || "",
          entry_hook: document.getElementById("arc-hook")?.value || "",
          climax: document.getElementById("arc-climax")?.value || "",
          result,
        }, state.currentProjectId)
        toast("已创建", "success")
        await this._loadArcs()
        router.navigate("outline", "arcs")
      } catch (err) { toast(err.message || "操作失败", "error") }
    } }])
  },

  _deleteArc(id) {
    confirmAction("确定删除此篇章纲？", async () => {
      try { await api.outline.deleteArc(id, { novel_id: state.currentProjectId }); toast("已删除", "success"); await this._loadArcs(); router.navigate("outline", "arcs") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============ 章节卡 ============

  async _renderChapters() {
    if (!state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">每章的结构化计划：目标、冲突、禁止事项、钩子。</p>
      <div style="margin-bottom:8px;display:flex;gap:8px;">
        <button class="btn btn-primary" data-action="create-chapter">新建章节卡</button>
        <button class="btn" data-action="submit-card-extraction">从正文提取</button>
      </div>`
    if (!this._chapters.length) return html + empty("暂无章节卡。")
    const statusLabels = { draft: "草稿", candidate: "候选", canonical: "正史", deprecated: "废弃" }
    html += `<table class="data-table"><thead><tr><th>章</th><th>标题</th><th>目标</th><th>冲突</th><th>状态</th><th>操作</th></tr></thead><tbody>`
    for (const c of this._chapters) {
      const isCandidate = c.status === "candidate"
      html += `<tr class="clickable" data-action="view-chapter" data-id="${esc(c.id || c.card_id)}">
        <td>${c.chapter_index || "-"}</td>
        <td><strong>${esc(c.title || "")}</strong></td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(c.chapter_goal || "")}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(c.main_conflict || "")}</td>
        <td><span class="badge badge-${c.status || "draft"}">${statusLabels[c.status] || c.status || "draft"}</span></td>
        <td>
          ${isCandidate ? `<button class="btn btn-sm btn-success" data-action="confirm-chapter" data-id="${esc(c.id || c.card_id)}" data-title="${esc(c.title || "")}" style="font-size:10px;">确认</button>` : ""}
          <button class="btn btn-sm" data-action="edit-chapter" data-id="${esc(c.id || c.card_id)}" style="font-size:10px;">编辑</button>
          <button class="btn btn-sm btn-danger" data-action="delete-chapter" data-id="${esc(c.id || c.card_id)}" style="font-size:10px;">删除</button>
        </td>
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
      try {
        await api.outline.createChapterCard({
          chapter_index: idx, title: document.getElementById("ch-title")?.value || "",
          chapter_goal: document.getElementById("ch-goal")?.value || "",
          main_conflict: document.getElementById("ch-conflict")?.value || "",
          ending_hook: document.getElementById("ch-hook")?.value || "",
        }, state.currentProjectId)
        toast("已创建", "success")
        await this._loadChapters()
        router.navigate("outline", "chapters")
      } catch (err) { toast(err.message || "操作失败", "error") }
    } }])
  },

  async _viewChapter(cardId) {
    try {
      const c = await api.outline.getChapterCard(cardId, state.currentProjectId)
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

  _confirmChapter(cardId, title) {
    confirmAction(`确认将「${title}」标记为正史？`, async () => {
      try {
        await api.outline.updateChapterCard(cardId, { status: "canonical" }, state.currentProjectId)
        toast(`「${title}」已确认`, "success")
        await this._loadChapters()
        router.navigate("outline", "chapters")
      } catch (e) { toast(e.message || "确认失败", "error") }
    }, "确认")
  },

  async _editChapter(cardId) {
    let card
    try { card = await api.outline.getChapterCard(cardId, state.currentProjectId) }
    catch { toast("无法加载章节卡数据", "error"); return }

    const formHtml = `
      <div class="form-group"><label>标题</label><input class="form-input" id="edit-ch-title" value="${esc(card.title || "")}" /></div>
      <div class="form-group"><label>核心目标</label><textarea class="form-textarea" id="edit-ch-goal" rows="2">${esc(card.chapter_goal || "")}</textarea></div>
      <div class="form-group"><label>主要冲突</label><textarea class="form-textarea" id="edit-ch-conflict" rows="2">${esc(card.main_conflict || "")}</textarea></div>
      <div class="form-group"><label>情绪基调</label><input class="form-input" id="edit-ch-emotion" value="${esc(card.emotional_point || "")}" /></div>
      <div class="form-group"><label>尾钩</label><textarea class="form-textarea" id="edit-ch-hook" rows="1">${esc(card.ending_hook || "")}</textarea></div>
      <div class="form-group"><label>必发生事件（每行一条）</label><textarea class="form-textarea" id="edit-ch-must" rows="2">${(card.must_happen || []).join("\n")}</textarea></div>
      <div class="form-group"><label>不能发生事件（每行一条）</label><textarea class="form-textarea" id="edit-ch-not" rows="2">${(card.must_not_happen || []).join("\n")}</textarea></div>
      <div class="form-group"><label>场景细纲（JSON）</label><textarea class="form-textarea" id="edit-ch-scenes" rows="3">${JSON.stringify(card.scene_cards || [])}</textarea></div>
    `
    showModal(`编辑章节卡 — 第${card.chapter_index}章`, formHtml, [
      { text: "取消", handler: () => closeModal() },
      {
        text: "保存", class: "btn-primary",
        handler: async () => {
          const data = {
            title: document.getElementById("edit-ch-title")?.value || "",
            chapter_goal: document.getElementById("edit-ch-goal")?.value || "",
            main_conflict: document.getElementById("edit-ch-conflict")?.value || "",
            emotional_point: document.getElementById("edit-ch-emotion")?.value || "",
            ending_hook: document.getElementById("edit-ch-hook")?.value || "",
            must_happen: (document.getElementById("edit-ch-must")?.value || "").split("\n").map(l => l.trim()).filter(Boolean),
            must_not_happen: (document.getElementById("edit-ch-not")?.value || "").split("\n").map(l => l.trim()).filter(Boolean),
          }
          let scenes = card.scene_cards || []
          try {
            scenes = JSON.parse(document.getElementById("edit-ch-scenes")?.value || "[]")
          } catch {}
          data.scene_cards = scenes

          try {
            await api.outline.updateChapterCard(cardId, data, state.currentProjectId)
            toast("已保存", "success")
            await this._loadChapters()
            router.navigate("outline", "chapters")
          } catch (err) { toast(err.message || "保存失败", "error") }
        },
      },
    ])
  },

  _deleteChapter(id) {
    confirmAction("确定删除此章节卡？", async () => {
      try { await api.outline.deleteChapterCard(id, { novel_id: state.currentProjectId }); toast("已删除", "success"); await this._loadChapters(); router.navigate("outline", "chapters") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  async _submitChapterCardExtraction() {
    if (!state.currentProjectId) { toast("请先选择项目", "warning"); return }

    const formHtml = `
      <div class="form-row">
        <div class="form-group">
          <label>起始章节</label>
          <input class="form-input" id="ext-ch-start" type="number" min="1" value="1" />
        </div>
        <div class="form-group">
          <label>结束章节</label>
          <input class="form-input" id="ext-ch-end" type="number" min="1" value="10" />
        </div>
      </div>
    `
    showModal("提取章节卡", formHtml, [
      { text: "取消", handler: () => closeModal() },
      {
        text: "确认", class: "btn-primary",
        handler: async () => {
          const chStart = parseInt(document.getElementById("ext-ch-start")?.value || "1", 10)
          const chEnd = parseInt(document.getElementById("ext-ch-end")?.value || "10", 10)
          if (chEnd < chStart) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
          closeModal()
          await this._doChapterCardExtraction(chStart, chEnd)
        },
      },
    ])
  },

  async _doChapterCardExtraction(chStart, chEnd) {
    let existingCards = []
    try {
      const data = await api.outline.listChapterCards({
        novel_id: state.currentProjectId, limit: 50,
      })
      existingCards = data.items || []
    } catch {
      toast("无法加载章节卡信息", "error")
      return
    }

    const skipped = existingCards.filter((c) => c.chapter_index >= chStart && c.chapter_index <= chEnd)
    const extractList = []
    for (let i = chStart; i <= chEnd; i++) {
      if (!skipped.find((c) => c.chapter_index === i)) {
        extractList.push(i)
      }
    }

    if (extractList.length === 0) {
      toast("所选范围内所有章节已有章节卡，无需提取", "info")
      return
    }

    let modalHtml = `
      <div style="font-size:13px;">
        <p style="margin-bottom:8px;">将提取以下 <strong>${extractList.length}</strong> 章：</p>
        <div style="max-height:200px;overflow-y:auto;background:var(--panel);padding:8px;border-radius:4px;margin-bottom:8px;">
    `
    for (const idx of extractList) {
      modalHtml += `<div style="font-size:12px;padding:2px 0;">✅ 第 ${idx} 章</div>`
    }
    if (skipped.length > 0) {
      modalHtml += `
        <p style="margin-top:8px;color:var(--text-dim);">已跳过 <strong>${skipped.length}</strong> 章（已有章节卡）：</p>
      `
      for (const c of skipped) {
        modalHtml += `<div style="font-size:11px;color:var(--text-dim);padding:2px 0;">⏭ 第 ${c.chapter_index} 章 — ${esc(c.title || "")}</div>`
      }
    }
    modalHtml += `</div>
      <p style="color:var(--text-dim);font-size:11px;">提取结果将保存为「候选」状态，请审核确认。</p>
    `

    const start = chStart; const end = chEnd
    showModal("确认提取章节卡", modalHtml, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认提取", class: "btn-primary",
        handler: async () => {
          closeModal()
          try {
            await api.tasks.submit("chapter_card_extraction", {
              novel_id: state.currentProjectId, start_chapter: start, end_chapter: end,
            })
            toast("章节卡提取任务已提交，请稍后刷新查看", "success")
          } catch (err) {
            toast(err.message || "提交失败", "error")
          }
        },
      },
    ])
  },

  // ============ 伏笔计划 ============

  async _renderForeshadowing() {
    if (!state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">管理伏笔的埋设、强化和收束计划。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" data-action="create-foreshadowing">新建伏笔</button></div>`
    if (!this._foreshadowing.length) return html + empty("暂无伏笔计划。")
    html += `<table class="data-table"><thead><tr><th>名称</th><th>埋设章</th><th>收束章</th><th>状态</th><th>操作</th></tr></thead><tbody>`
    for (const f of this._foreshadowing) {
      html += `<tr data-id="${esc(f.id || f.foreshadow_id)}">
        <td><strong>${esc(f.name)}</strong></td>
        <td>${f.planned_seed_chapter ? "第" + f.planned_seed_chapter + "章" : "-"}</td>
        <td>${f.planned_payoff_chapter ? "第" + f.planned_payoff_chapter + "章" : "-"}</td>
        <td><span class="badge badge-draft">${esc(f.status || "draft")}</span></td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-foreshadowing" data-id="${esc(f.id || f.foreshadow_id)}">删除</button></td>
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
      try {
        await api.outline.createForeshadowing({ name,
          summary: document.getElementById("fs-summary")?.value || "",
          surface_meaning: document.getElementById("fs-surface")?.value || "",
          hidden_meaning: document.getElementById("fs-hidden")?.value || "",
          planned_seed_chapter: parseInt(document.getElementById("fs-seed")?.value) || undefined,
          planned_payoff_chapter: parseInt(document.getElementById("fs-payoff")?.value) || undefined,
        }, state.currentProjectId)
        toast("已创建", "success")
        await this._loadForeshadowing()
        router.navigate("outline", "foreshadowing")
      } catch (err) { toast(err.message || "操作失败", "error") }
    } }])
  },

  _deleteForeshadowing(id) {
    confirmAction("确定删除此伏笔？", async () => {
      try { await api.outline.deleteForeshadowing(id, { novel_id: state.currentProjectId }); toast("已删除", "success"); await this._loadForeshadowing(); router.navigate("outline", "foreshadowing") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============ 信息揭示 ============

  async _renderReveals() {
    if (!state.currentProjectId) return empty("请先选择项目。")
    let html = `<p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">管理隐藏真相的分阶段揭示计划。</p>
      <div style="margin-bottom:8px;"><button class="btn btn-primary" data-action="create-reveal">新建揭示计划</button></div>`
    if (!this._reveals.length) return html + empty("暂无揭示计划。")
    html += `<table class="data-table"><thead><tr><th>目标</th><th>秘密摘要</th><th>揭示阶段</th><th>状态</th><th>操作</th></tr></thead><tbody>`
    for (const r of this._reveals) {
      const stages = r.reveal_stages?.length || 0
      html += `<tr data-id="${esc(r.id || r.reveal_id)}">
        <td style="font-size:12px;">${esc(r.target_type || "")}:${esc(r.target_id || "").slice(0, 8)}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--text-dim);">${esc(r.secret_summary || "")}</td>
        <td>${stages} 个阶段</td>
        <td><span class="badge badge-draft">${esc(r.status || "draft")}</span></td>
        <td><button class="btn btn-sm btn-danger" data-action="delete-reveal" data-id="${esc(r.id || r.reveal_id)}">删除</button></td>
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
      try {
        await api.outline.createReveal({
          target_type: document.getElementById("rv-type")?.value || "world_entity",
          target_id: targetId,
          secret_summary: document.getElementById("rv-secret")?.value || "",
        }, state.currentProjectId)
        toast("已创建", "success")
        await this._loadReveals()
        router.navigate("outline", "reveals")
      } catch (err) { toast(err.message || "操作失败", "error") }
    } }])
  },

  _deleteReveal(id) {
    confirmAction("确定删除此揭示计划？", async () => {
      try { await api.outline.deleteReveal(id, { novel_id: state.currentProjectId }); toast("已删除", "success"); await this._loadReveals(); router.navigate("outline", "reveals") }
      catch (e) { toast(e.message || "删除失败", "error") }
    }, "确认删除")
  },

  _bindEvents() {
    const content = document.getElementById("workspace-content")
    if (!content) return
    content.removeEventListener("click", this._clickHandler)
    this._clickHandler = (e) => {
      const t = e.target.closest("[data-action]")
      if (!t) return
      const a = t.getAttribute("data-action")
      const id = t.getAttribute("data-id")
      switch (a) {
        case "nav-threads": router.navigate("outline", "threads"); break
        case "nav-arcs": router.navigate("outline", "arcs"); break
        case "nav-chapters": router.navigate("outline", "chapters"); break
        case "nav-foreshadowing": router.navigate("outline", "foreshadowing"); break
        case "nav-reveals": router.navigate("outline", "reveals"); break
        case "create-thread": this._createThread(); break
        case "delete-thread": if (id) this._deleteThread(id); break
        case "create-arc": this._createArc(); break
        case "delete-arc": if (id) this._deleteArc(id); break
        case "create-chapter": this._createChapter(); break
        case "delete-chapter": if (id) this._deleteChapter(id); break
        case "view-chapter": if (id) this._viewChapter(id); break
        case "edit-chapter": if (id) this._editChapter(id); break
        case "confirm-chapter": if (id) this._confirmChapter(id, t.getAttribute("data-title")); break
        case "submit-card-extraction": this._submitChapterCardExtraction(); break
        case "submit-extraction": this._submitExtraction(t.getAttribute("data-key"), t.getAttribute("data-task-type")); break
        case "create-foreshadowing": this._createForeshadowing(); break
        case "delete-foreshadowing": if (id) this._deleteForeshadowing(id); break
        case "create-reveal": this._createReveal(); break
        case "delete-reveal": if (id) this._deleteReveal(id); break
      }
    }
    content.addEventListener("click", this._clickHandler)
  },
}

function empty(msg) { return `<div class="empty-state"><p>${msg}</p></div>` }

router.registerView("outline", outlineView)
window.outlineView = outlineView


export default outlineView
