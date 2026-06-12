/**
 * 大纲视图
 *
 * 子标签：场景卡 | 剧情线 | 篇章纲 | 伏笔 | 揭示
 */
import { bindWorkspaceClick } from "../shared/viewHelper.js"

const SCENE_ALLOWED_TAGS = new Set(["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"])
const ENTITY_ALLOWED_STATUSES = new Set(["canonical", "draft", "candidate", "deprecated"])
const FORESHADOWING_STATUSES = ["draft", "active", "resolved", "abandoned"]

const outlineView = {
  _threads: [],
  _arcs: [],
  _scenes: [],
  _foreshadowing: [],
  _reveals: [],
  _loading: true,

  async onEnter() {
    this._loading = true
    this._threads = []
    this._arcs = []
    this._foreshadowing = []
    this._reveals = []

    if (!state.currentProjectId) {
      this._loading = false
      return
    }

    const subView = state.currentSubView || "scenes"
    const fetchThreads = subView === "threads" || subView === "scenes"
    const fetchArcs = subView === "arcs"
    const fetchForeshadowing = subView === "foreshadowing"
    const fetchReveals = subView === "reveals"

    const promises = []
    if (fetchThreads) {
      promises.push(
        api.outline.listThreads(state.currentProjectId)
          .then((data) => { this._threads = data.items || data || [] })
          .catch(() => { this._threads = [] })
      )
    }
    if (fetchArcs) {
      promises.push(
        api.outline.listArcs(state.currentProjectId)
          .then((data) => { this._arcs = data.items || data || [] })
          .catch(() => { this._arcs = [] })
      )
    }
    if (subView === "scenes") {
      promises.push(
        api.outline.listScenes(state.currentProjectId)
          .then((data) => { this._scenes = data.items || data || [] })
          .catch(() => { this._scenes = [] })
      )
    }
    if (fetchForeshadowing) {
      promises.push(
        api.outline.listForeshadowing(state.currentProjectId)
          .then((data) => { this._foreshadowing = data.items || data || [] })
          .catch(() => { this._foreshadowing = [] })
      )
    }
    if (fetchReveals) {
      promises.push(
        api.outline.listReveals(state.currentProjectId)
          .then((data) => { this._reveals = data.items || data || [] })
          .catch(() => { this._reveals = [] })
      )
    }

    if (promises.length > 0) {
      await Promise.all(promises)
    }
    this._loading = false
  },

  onLeave() {},

  onActivate() {
    // KeepAlive 恢复后重新绑定事件（DOM 来自缓存，事件监听器可能丢失）
    this._bindEvents()
    const saved = state.viewStates && state.viewStates.outline
    if (saved && saved.scrollTop != null) {
      const container = document.querySelector("#workspace-content .subnav")
      if (container) {
        container.scrollTop = saved.scrollTop
      }
    }
  },

  onDeactivate() {
    // 保存滚动位置
    const container = document.querySelector("#workspace-content .subnav")
    if (container) {
      state.viewStates = state.viewStates || {}
      state.viewStates.outline = { scrollTop: container.scrollTop }
    }
  },

  async render() {
    const subView = state.currentSubView || "scenes"
    let html = ""

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "scenes" ? "active" : ""}" data-action="nav-scenes">场景卡</span>
        <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-action="nav-threads">剧情线</span>
        <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-action="nav-arcs">篇章纲</span>
        <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-action="nav-foreshadowing">伏笔</span>
        <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-action="nav-reveals">揭示</span>
      </div>
    `

    if (this._loading) {
      html += '<div class="loading">加载中...</div>'
    } else if (subView === "scenes") {
      html += this._renderScenes()
    } else if (subView === "threads") {
      html += this._renderThreads()
    } else if (subView === "arcs") {
      html += this._renderArcs()
    } else if (subView === "foreshadowing") {
      html += this._renderForeshadowing()
    } else if (subView === "reveals") {
      html += this._renderReveals()
    }

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  _renderScenes() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }

    let html = `
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-scene">新建 Scene</button>
        <button class="btn btn-sm" data-action="generate-structure">AI 生成结构</button>
      </div>
    `

    if (!this._scenes || this._scenes.length === 0) {
      return html + `
        <div class="empty-state">
          <div class="empty-icon">&#128209;</div>
          <p>暂无 Scene 卡。</p>
          <p style="color:var(--text-dim);font-size:12px;">Scene 是叙事结构的最小单元。通过深度导入自动生成，或手动创建。</p>
        </div>
      `
    }

    const sorted = [...this._scenes].sort(
      (a, b) => (a.scene_index || 0) - (b.scene_index || 0)
    )

    html += '<div class="scene-card-list">'
    const allowedTags = SCENE_ALLOWED_TAGS
    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const s of sorted) {
      const tagLabel = this._narrativeTagLabel(s.narrative_tag)
      const safeTag = allowedTags.has(s.narrative_tag) ? s.narrative_tag : "draft"
      const tagClass = `narrative-tag-${safeTag}`
      const sourceLabel = s.source === "deep_import" ? "AI导入"
        : s.source === "ai_generated" ? "AI生成" : "手动"
      const statusMap = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      const safeStatus = allowedStatuses.has(s.status) ? s.status : "draft"
      const statusClass = `badge-${safeStatus}`

      html += `
        <div class="scene-card" data-id="${esc(s.id)}">
          <div class="scene-card-header">
            <span class="scene-index">#${esc(s.scene_index)}</span>
            <span class="narrative-tag ${tagClass}">${esc(tagLabel)}</span>
            <span class="badge ${statusClass}">${statusMap[safeStatus] || esc(s.status)}</span>
            <span class="scene-source">${sourceLabel}</span>
          </div>
          <div class="scene-card-title">${esc(s.title || "未命名 Scene")}</div>
          ${s.goal ? `<div class="scene-card-field"><span class="field-label">目标</span>${esc(s.goal)}</div>` : ""}
          ${s.core_conflict ? `<div class="scene-card-field"><span class="field-label">冲突</span>${esc(s.core_conflict)}</div>` : ""}
          ${s.emotional_beat ? `<div class="scene-card-field"><span class="field-label">情感</span>${esc(s.emotional_beat)}</div>` : ""}
          <div class="scene-card-actions">
            <button class="btn btn-sm" data-action="move-scene-up" data-id="${esc(s.id)}">上移</button>
            <button class="btn btn-sm" data-action="move-scene-down" data-id="${esc(s.id)}">下移</button>
            <button class="btn btn-sm" data-action="edit-scene" data-id="${esc(s.id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-scene" data-id="${esc(s.id)}">删除</button>
          </div>
        </div>
      `
    }
    html += '</div>'
    return html
  },

  _narrativeTagLabel(tag) {
    const map = {
      inciting_incident: "激励事件",
      rising_action: "冲突升级",
      climax: "阶段高潮",
      valley: "低谷",
      transition: "过渡",
      hook: "钩子",
      payoff: "爽点",
      draft: "草稿",
    }
    return map[tag] || tag || "草稿"
  },

  _renderThreads() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }

    let html = `
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-thread">新建剧情线</button>
      </div>
    `

    if (this._threads.length === 0) {
      return html + `
        <div class="empty-state">
          <div class="empty-icon">&#128204;</div>
          <p>暂无剧情线。</p>
          <p style="color:var(--text-dim);font-size:12px;">剧情线表示故事中的主要叙事线索。</p>
        </div>
      `
    }

    html += `
      <table class="data-table">
        <thead>
          <tr>
            <th>状态</th>
            <th>名称</th>
            <th>类型</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const t of this._threads) {
      const statusMap = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      const safeStatus = allowedStatuses.has(t.status) ? t.status : "draft"
      const statusClass = `badge-${safeStatus}`
      html += `
        <tr data-id="${esc(t.id || t.thread_id)}">
          <td><span class="badge ${statusClass}">${statusMap[safeStatus] || esc(safeStatus)}</span></td>
          <td>${esc(t.name || t.title)}</td>
          <td style="color:var(--accent-dim);font-size:12px;">${esc(t.thread_type || "-")}</td>
          <td style="color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(t.description || t.summary || "-")}</td>
          <td>
            <button class="btn btn-sm" data-action="edit-thread" data-id="${esc(t.id || t.thread_id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-thread" data-id="${esc(t.id || t.thread_id)}">删除</button>
          </td>
        </tr>
      `
    }

    html += "</tbody></table>"
    return html
  },

  _renderArcs() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }

    let html = `
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-arc">新建篇章纲</button>
      </div>
    `

    if (this._arcs.length === 0) {
      return html + `
        <div class="empty-state">
          <div class="empty-icon">&#128218;</div>
          <p>暂无篇章纲。</p>
          <p style="color:var(--text-dim);font-size:12px;">篇章纲用于规划卷层级的叙事结构。</p>
        </div>
      `
    }

    html += `
      <table class="data-table">
        <thead>
          <tr>
            <th>状态</th>
            <th>名称</th>
            <th>章节范围</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const a of this._arcs) {
      const statusMap = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      const safeStatus = allowedStatuses.has(a.status) ? a.status : "draft"
      const statusClass = `badge-${safeStatus}`
      const range = a.start_chapter != null && a.end_chapter != null
        ? `${a.start_chapter}-${a.end_chapter}`
        : "-"
      html += `
        <tr data-id="${esc(a.id || a.arc_id)}">
          <td><span class="badge ${statusClass}">${statusMap[safeStatus] || esc(safeStatus)}</span></td>
          <td>${esc(a.name || a.title)}</td>
          <td style="font-family:var(--font-mono);font-size:12px;">${esc(range)}</td>
          <td style="color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(a.description || a.summary || "-")}</td>
          <td>
            <button class="btn btn-sm" data-action="edit-arc" data-id="${esc(a.id || a.arc_id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-arc" data-id="${esc(a.id || a.arc_id)}">删除</button>
          </td>
        </tr>
      `
    }

    html += "</tbody></table>"
    return html
  },

  _renderForeshadowing() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }

    if (this._foreshadowing.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128220;</div>
          <p>暂无伏笔计划。</p>
          <p style="color:var(--text-dim);font-size:12px;">伏笔是埋设在早期章节的线索，在后续章节揭示其真实含义。</p>
        </div>
      `
    }

    const statusLabels = { draft: "草稿", active: "激活", resolved: "已兑现", abandoned: "已废弃" }

    let html = '<table class="data-table"><thead><tr><th>状态</th><th>名称</th><th>摘要</th><th>种子章节</th><th>兑现章节</th><th>操作</th></tr></thead><tbody>'
    for (const f of this._foreshadowing) {
      const st = statusLabels[f.status] || f.status
      html += `<tr data-id="${esc(f.id)}">
        <td><span class="badge badge-${esc(f.status || "draft")}">${esc(st)}</span></td>
        <td>${esc(f.name)}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(f.summary || "-")}</td>
        <td style="font-family:var(--font-mono);font-size:12px;">${f.planned_seed_chapter != null ? esc(String(f.planned_seed_chapter)) : "-"}</td>
        <td style="font-family:var(--font-mono);font-size:12px;">${f.planned_payoff_chapter != null ? esc(String(f.planned_payoff_chapter)) : "-"}</td>
        <td>
          <select class="form-select foreshadowing-status-select" style="width:auto;font-size:12px;padding:2px 4px;" data-id="${esc(f.id)}">
            ${FORESHADOWING_STATUSES.map((s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${statusLabels[s] || s}</option>`).join("")}
          </select>
        </td>
      </tr>`
    }
    html += '</tbody></table>'
    return html
  },

  _renderReveals() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }

    if (this._reveals.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128065;</div>
          <p>暂无揭示计划。</p>
          <p style="color:var(--text-dim);font-size:12px;">揭示计划跟踪一个秘密如何分阶段向读者揭露。</p>
        </div>
      `
    }

    let html = '<table class="data-table"><thead><tr><th>状态</th><th>目标类型</th><th>秘密摘要</th><th>揭示阶段</th></tr></thead><tbody>'
    for (const r of this._reveals) {
      const stageCount = Array.isArray(r.reveal_stages) ? r.reveal_stages.length : 0
      html += `<tr data-id="${esc(r.id)}">
        <td><span class="badge badge-${esc(r.status || "draft")}">${esc(r.status || "draft")}</span></td>
        <td>${esc(r.target_type)}</td>
        <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(r.secret_summary)}</td>
        <td style="font-family:var(--font-mono);font-size:12px;">${stageCount} 阶段</td>
      </tr>`
    }
    html += '</tbody></table>'
    return html
  },

  _showCreateThreadForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-thread-name" placeholder="剧情线名称" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="create-thread-type">
          <option value="main">主线</option>
          <option value="sub">支线</option>
          <option value="background">暗线</option>
        </select>
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="create-thread-desc" rows="3" placeholder="剧情线描述"></textarea>
      </div>
    `
    showModal("新建剧情线", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const name = document.getElementById("create-thread-name")?.value
        if (!name) { toast("请输入名称", "warning"); return }
        try {
          await api.outline.createThread(state.currentProjectId, {
            name,
            thread_type: document.getElementById("create-thread-type")?.value || "main",
            description: document.getElementById("create-thread-desc")?.value || "",
          })
          toast("剧情线已创建", "success")
          router.refresh()
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _editThread(id) {
    const thread = this._threads.find((t) => (t.id || t.thread_id) === id)
    if (!thread) return

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-thread-name" value="${esc(thread.name || thread.title)}" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="edit-thread-type">
          <option value="main" ${(thread.thread_type || "main") === "main" ? "selected" : ""}>主线</option>
          <option value="sub" ${thread.thread_type === "sub" ? "selected" : ""}>支线</option>
          <option value="background" ${thread.thread_type === "background" ? "selected" : ""}>暗线</option>
        </select>
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="edit-thread-desc" rows="3">${esc(thread.description || thread.summary || "")}</textarea>
      </div>
    `
    showModal("编辑剧情线", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateThread(id, state.currentProjectId, {
            name: document.getElementById("edit-thread-name")?.value,
            thread_type: document.getElementById("edit-thread-type")?.value,
            description: document.getElementById("edit-thread-desc")?.value,
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _deleteThread(id) {
    confirmAction("确定删除此剧情线？", async () => {
      try {
        await api.outline.deleteThread(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  _showCreateArcForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-arc-name" placeholder="篇章纲名称" />
      </div>
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="create-arc-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="create-arc-end" type="number" min="1" value="10" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="create-arc-desc" rows="3" placeholder="篇章纲描述"></textarea>
      </div>
    `
    showModal("新建篇章纲", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const title = document.getElementById("create-arc-name")?.value
        if (!title) { toast("请输入名称", "warning"); return }
        try {
          await api.outline.createArc(state.currentProjectId, {
            title,
            start_chapter: parseInt(document.getElementById("create-arc-start")?.value || "1", 10),
            end_chapter: parseInt(document.getElementById("create-arc-end")?.value || "10", 10),
            arc_goal: document.getElementById("create-arc-desc")?.value || "",
          })
          toast("篇章纲已创建", "success")
          router.refresh()
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _editArc(id) {
    const arc = this._arcs.find((a) => (a.id || a.arc_id) === id)
    if (!arc) return

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-arc-name" value="${esc(arc.title || arc.name || "")}" />
      </div>
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="edit-arc-start" type="number" min="1" value="${arc.start_chapter || 1}" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="edit-arc-end" type="number" min="1" value="${arc.end_chapter || 10}" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <textarea class="form-textarea" id="edit-arc-desc" rows="3">${esc(arc.description || arc.summary || "")}</textarea>
      </div>
    `
    showModal("编辑篇章纲", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateArc(id, state.currentProjectId, {
            title: document.getElementById("edit-arc-name")?.value?.trim(),
            start_chapter: parseInt(document.getElementById("edit-arc-start")?.value || "1", 10),
            end_chapter: parseInt(document.getElementById("edit-arc-end")?.value || "10", 10),
            description: document.getElementById("edit-arc-desc")?.value?.trim(),
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _deleteArc(id) {
    confirmAction("确定删除此篇章纲？", async () => {
      try {
        await api.outline.deleteArc(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  _showCreateSceneForm() {
    const tagOptions = [
      { value: "draft", label: "草稿（默认）" },
      { value: "hook", label: "钩子" },
      { value: "inciting_incident", label: "激励事件" },
      { value: "rising_action", label: "冲突升级" },
      { value: "climax", label: "阶段高潮" },
      { value: "valley", label: "低谷" },
      { value: "transition", label: "过渡" },
      { value: "payoff", label: "爽点" },
    ]
    const tagSelectHtml = tagOptions.map(
      (o) => `<option value="${o.value}">${o.label}</option>`
    ).join("")

    const maxIdx = this._scenes && this._scenes.length > 0
      ? Math.max(...this._scenes.map((s) => s.scene_index || 0))
      : -1
    const nextIdx = maxIdx + 1

    const formHtml = `
      <div class="form-group">
        <label>序号</label>
        <input class="form-input" id="create-scene-index" type="number" value="${nextIdx}" min="0" />
      </div>
      <div class="form-group">
        <label>标题</label>
        <input class="form-input" id="create-scene-title" placeholder="Scene 标题" />
      </div>
      <div class="form-group">
        <label>叙事标签</label>
        <select class="form-select" id="create-scene-tag">${tagSelectHtml}</select>
      </div>
      <div class="form-group">
        <label>目标</label>
        <textarea class="form-textarea" id="create-scene-goal" rows="2" placeholder="此 Scene 要完成的叙事目标"></textarea>
      </div>
      <div class="form-group">
        <label>核心冲突</label>
        <textarea class="form-textarea" id="create-scene-conflict" rows="2" placeholder="核心冲突描述"></textarea>
      </div>
      <div class="form-group">
        <label>情感节奏</label>
        <input class="form-input" id="create-scene-emotion" placeholder="读者的情感走向" />
      </div>
      <div class="form-group">
        <label>必须发生</label>
        <textarea class="form-textarea" id="create-scene-must-happen" rows="2" placeholder="必须发生的事件"></textarea>
      </div>
      <div class="form-group">
        <label>禁止发生</label>
        <textarea class="form-textarea" id="create-scene-must-not" rows="2" placeholder="禁止发生的事件"></textarea>
      </div>
    `
    showModal("新建 Scene 卡", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        try {
          await api.outline.createScene(state.currentProjectId, {
            scene_index: parseInt(document.getElementById("create-scene-index")?.value || "0", 10),
            title: document.getElementById("create-scene-title")?.value?.trim() || null,
            narrative_tag: document.getElementById("create-scene-tag")?.value || "draft",
            goal: document.getElementById("create-scene-goal")?.value?.trim() || null,
            core_conflict: document.getElementById("create-scene-conflict")?.value?.trim() || null,
            emotional_beat: document.getElementById("create-scene-emotion")?.value?.trim() || null,
            must_happen: document.getElementById("create-scene-must-happen")?.value?.trim() || null,
            must_not_happen: document.getElementById("create-scene-must-not")?.value?.trim() || null,
            source: "manual",
            status: "draft",
          })
          toast("Scene 卡已创建", "success")
          router.refresh()
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  _editScene(id) {
    const scene = (this._scenes || []).find((s) => s.id === id)
    if (!scene) return

    const tags = ["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"]
    const tagLabels = { draft: "草稿", hook: "钩子", inciting_incident: "激励事件", rising_action: "冲突升级", climax: "阶段高潮", valley: "低谷", transition: "过渡", payoff: "爽点" }
    const tagSelectHtml = tags.map(
      (t) => `<option value="${t}" ${(scene.narrative_tag || "draft") === t ? "selected" : ""}>${tagLabels[t]}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>序号</label>
        <input class="form-input" id="edit-scene-index" type="number" value="${scene.scene_index || 0}" min="0" />
      </div>
      <div class="form-group">
        <label>标题</label>
        <input class="form-input" id="edit-scene-title" value="${esc(scene.title || "")}" />
      </div>
      <div class="form-group">
        <label>叙事标签</label>
        <select class="form-select" id="edit-scene-tag">${tagSelectHtml}</select>
      </div>
      <div class="form-group">
        <label>目标</label>
        <textarea class="form-textarea" id="edit-scene-goal" rows="2">${esc(scene.goal || "")}</textarea>
      </div>
      <div class="form-group">
        <label>核心冲突</label>
        <textarea class="form-textarea" id="edit-scene-conflict" rows="2">${esc(scene.core_conflict || "")}</textarea>
      </div>
      <div class="form-group">
        <label>情感节奏</label>
        <input class="form-input" id="edit-scene-emotion" value="${esc(scene.emotional_beat || "")}" />
      </div>
      <div class="form-group">
        <label>必须发生</label>
        <textarea class="form-textarea" id="edit-scene-must-happen" rows="2">${esc(scene.must_happen || "")}</textarea>
      </div>
      <div class="form-group">
        <label>禁止发生</label>
        <textarea class="form-textarea" id="edit-scene-must-not" rows="2">${esc(scene.must_not_happen || "")}</textarea>
      </div>
    `
    showModal("编辑 Scene 卡", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateScene(id, state.currentProjectId, {
            scene_index: parseInt(document.getElementById("edit-scene-index")?.value || "0", 10),
            title: document.getElementById("edit-scene-title")?.value?.trim() || null,
            narrative_tag: document.getElementById("edit-scene-tag")?.value || "draft",
            goal: document.getElementById("edit-scene-goal")?.value?.trim() || null,
            core_conflict: document.getElementById("edit-scene-conflict")?.value?.trim() || null,
            emotional_beat: document.getElementById("edit-scene-emotion")?.value?.trim() || null,
            must_happen: document.getElementById("edit-scene-must-happen")?.value?.trim() || null,
            must_not_happen: document.getElementById("edit-scene-must-not")?.value?.trim() || null,
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _deleteScene(id) {
    confirmAction("确定删除此 Scene 卡？删除后标记为 deprecated，正文保留。", async () => {
      try {
        await api.outline.deleteScene(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  async _reorderScenes(sceneIds) {
    try {
      await api.outline.reorderScenes(state.currentProjectId, sceneIds)
      toast("Scene 顺序已更新", "success")
      await this.onEnter?.()
      router.refresh()
    } catch (err) {
      toast(err.message || "操作失败", "error")
    }
  },

  async _generateStructure(startChapter, endChapter) {
    try {
      const result = await api.outline.generate(state.currentProjectId, startChapter, endChapter)
      toast("结构生成完成", "success")
      await this.onEnter?.()
      router.refresh()
      return result
    } catch (err) {
      toast(err.message || "操作失败", "error")
      throw err
    }
  },

  async _moveSceneUp(id) {
    const sorted = [...this._scenes].sort((a, b) => (a.scene_index || 0) - (b.scene_index || 0))
    const idx = sorted.findIndex((s) => s.id === id)
    if (idx <= 0) return
    ;[sorted[idx - 1], sorted[idx]] = [sorted[idx], sorted[idx - 1]]
    await this._reorderScenes(sorted.map((s) => s.id))
  },

  async _moveSceneDown(id) {
    const sorted = [...this._scenes].sort((a, b) => (a.scene_index || 0) - (b.scene_index || 0))
    const idx = sorted.findIndex((s) => s.id === id)
    if (idx < 0 || idx >= sorted.length - 1) return
    ;[sorted[idx], sorted[idx + 1]] = [sorted[idx + 1], sorted[idx]]
    await this._reorderScenes(sorted.map((s) => s.id))
  },

  _showGenerateStructureForm() {
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="generate-structure-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="generate-structure-end" type="number" min="1" value="10" />
      </div>
    `
    showModal("AI 生成剧情结构", formHtml, [{
      text: "生成", class: "btn-primary", handler: async () => {
        const start = parseInt(document.getElementById("generate-structure-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("generate-structure-end")?.value || "10", 10)
        if (end < start) { toast("结束章节不能小于起始章节", "warning"); return }
        try {
          await this._generateStructure(start, end)
        } catch (err) { toast(err.message || "生成失败", "error") }
      },
    }])
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "nav-scenes": () => router.navigate("outline", "scenes"),
      "nav-threads": () => router.navigate("outline", "threads"),
      "nav-arcs": () => router.navigate("outline", "arcs"),
      "nav-foreshadowing": () => router.navigate("outline", "foreshadowing"),
      "nav-reveals": () => router.navigate("outline", "reveals"),
      "create-thread": () => this._showCreateThreadForm(),
      "edit-thread": (_e, _t, ctx) => ctx.id && this._editThread(ctx.id),
      "delete-thread": (_e, _t, ctx) => ctx.id && this._deleteThread(ctx.id),
      "create-arc": () => this._showCreateArcForm(),
      "edit-arc": (_e, _t, ctx) => ctx.id && this._editArc(ctx.id),
      "delete-arc": (_e, _t, ctx) => ctx.id && this._deleteArc(ctx.id),
      "create-scene": () => this._showCreateSceneForm(),
      "generate-structure": () => this._showGenerateStructureForm(),
      "move-scene-up": (_e, _t, ctx) => ctx.id && this._moveSceneUp(ctx.id),
      "move-scene-down": (_e, _t, ctx) => ctx.id && this._moveSceneDown(ctx.id),
      "edit-scene": (_e, _t, ctx) => ctx.id && this._editScene(ctx.id),
      "delete-scene": (_e, _t, ctx) => ctx.id && this._deleteScene(ctx.id),
    })
    // 伏笔状态变更：change 事件委托
    document.querySelectorAll(".foreshadowing-status-select").forEach((sel) => {
      sel.onchange = async () => {
        const id = sel.dataset.id
        if (!id) return
        try {
          await api.outline.updateForeshadowing(id, state.currentProjectId, { status: sel.value })
          toast("伏笔状态已更新", "success")
          await this.onEnter()
        } catch (err) { toast(err.message || "更新失败", "error") }
      }
    })
  },
}

router.registerView("outline", outlineView)
window.outlineView = outlineView
export default outlineView