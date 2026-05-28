/**
 * 世界对象视图
 */
const worldView = {
  /** @type {Array} */
  _entities: [],

  /** @type {Array} */
  _candidates: [],

  /** AI 自动识别状态 */
  _autoExtractOpen: false,
  _autoExtractTaskId: null,
  _autoExtractStatus: "就绪",
  _autoExtractTimer: null,

  async onEnter() {
    this._entities = []
    this._candidates = []

    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }

    // 从 localStorage 恢复抽取任务
    const saved = localStorage.getItem("novel_world_extract_task")
    if (saved) {
      try {
        const { taskId, status } = JSON.parse(saved)
        if (taskId && status !== "done" && status !== "failed") {
          this._autoExtractTaskId = taskId
          this._autoExtractStatus = status || "运行中"
          this._pollAutoExtract(taskId)
        }
      } catch {}
    }

    try {
      if (_state.currentProjectId) {
        const data = await api.world.listEntities({ novel_id: _state.currentProjectId })
        this._entities = data.items || data || []
      }
    } catch {
      this._entities = []
    }

    try {
      if (_state.currentProjectId) {
        const data = await api.world.listCandidates({ novel_id: _state.currentProjectId, status: "pending" })
        this._candidates = data.items || data || []
      }
    } catch {
      this._candidates = []
    }
  },

  onLeave() {
    if (this._autoExtractTimer) {
      clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = null
    }
  },

  async render() {
    const subView = _state.currentSubView || "objects"
    let html = ''

    // 子标签导航
    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "objects" ? "active" : ""}" data-subview="objects" data-action="nav-objects">对象库</span>
        <span class="subnav-item ${subView === "candidates" ? "active" : ""}" data-subview="candidates" data-action="nav-candidates">候选清洗</span>
        <span class="subnav-item ${subView === "relations" ? "active" : ""}" data-subview="relations" data-action="nav-relations">关系</span>
        <span class="subnav-item ${subView === "aliases" ? "active" : ""}" data-subview="aliases" data-action="nav-aliases">别名</span>
      </div>
    `

    if (subView === "objects") {
      html += this._renderEntityList()
    } else if (subView === "candidates") {
      html += this._renderCandidatesList()
    } else if (subView === "relations") {
      html += await this._renderRelations()
    } else if (subView === "aliases") {
      html += await this._renderAliases()
    }

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  // ============================================================
  // AI 自动识别
  // ============================================================

  _toggleAutoExtract() {
    this._autoExtractOpen = !this._autoExtractOpen
    router.navigate("world", _state.currentSubView)
  },

  _renderAutoExtractPanel(taskType, label) {
    const statusLine = this._autoExtractTaskId
      ? `任务 ${this._autoExtractTaskId.slice(0, 8)}... — ${this._autoExtractStatus}`
      : `状态: ${this._autoExtractStatus}`
    return `
      <div style="border:1px solid var(--border);border-radius:4px;padding:10px;margin-bottom:12px;text-align:center;">
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px;">${label}</div>
        <div style="display:flex;gap:8px;justify-content:center;align-items:center;flex-wrap:wrap;">
          起始章 <input id="w-extract-start" type="number" min="1" value="1" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;" />
          结束章 <input id="w-extract-end" type="number" min="1" value="10" style="width:50px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:2px 6px;border-radius:3px;" />
          <button class="btn btn-sm btn-primary" data-action="submit-extract" data-type="${taskType}" ${this._autoExtractTaskId ? "disabled" : ""}>
            ${this._autoExtractTaskId ? "识别中..." : "开始识别"}
          </button>
        </div>
        <div id="w-extract-status" style="margin-top:4px;font-size:11px;color:var(--text-dim);">${statusLine}</div>
      </div>
    `
  },

  async _submitAutoExtract(taskType) {
    if (!_state.currentProjectId) { toast("请先选择项目", "warning"); return }
    const start = parseInt(document.getElementById("w-extract-start")?.value || "1", 10)
    const end = parseInt(document.getElementById("w-extract-end")?.value || "10", 10)
    if (start > end) { toast("起始章节不能大于结束章节", "warning"); return }

    try {
      const result = await api.tasks.submit(taskType, {
        novel_id: _state.currentProjectId,
        start_chapter: start,
        end_chapter: end,
      })
      this._autoExtractTaskId = result.task_id
      this._autoExtractStatus = "运行中"
      this._updateExtractStatusDOM()
      try { localStorage.setItem("novel_world_extract_task", JSON.stringify({ taskId: result.task_id, status: "running" })) } catch {}
      toast("识别任务已提交", "info")
      router.navigate("world", _state.currentSubView)

      // 启动轮询
      if (this._autoExtractTimer) clearInterval(this._autoExtractTimer)
      this._autoExtractTimer = setInterval(() => this._pollAutoExtract(result.task_id), 5000)
    } catch (err) {
      this._autoExtractStatus = `失败: ${err.message}`
      this._updateExtractStatusDOM()
      toast(err.message || "提交失败", "error")
    }
  },

  async _pollAutoExtract(taskId) {
    try {
      const data = await api.tasks.getStatus(taskId)
      this._autoExtractStatus = data.status || "未知"
      this._updateExtractStatusDOM()

      if (data.status === "done" || data.status === "failed" || data.status === "cancelled") {
        if (this._autoExtractTimer) {
          clearInterval(this._autoExtractTimer)
          this._autoExtractTimer = null
        }
        try { localStorage.removeItem("novel_world_extract_task") } catch {}
        if (data.status === "done") {
          toast("识别任务已完成，请查看候选清洗", "success")
        } else if (data.status === "failed") {
          toast(`识别任务失败: ${data.error_message || "未知错误"}`, "error")
        }
      }
    } catch {
      // 轮询失败不中断
    }
  },

  _updateExtractStatusDOM() {
    const el = document.getElementById("w-extract-status")
    if (el) {
      const prefix = this._autoExtractTaskId ? `任务 ${this._autoExtractTaskId.slice(0, 8)}... — ` : "状态: "
      el.textContent = prefix + this._autoExtractStatus
    }
  },

  _renderEntityList() {
    if (this._entities.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#127758;</div>
          <p>还没有世界对象。</p>
          <p>世界对象是小说世界中的核心创作资产，包括地点、组织、物品、事件等。</p>
          <div style="display:flex;gap:8px;justify-content:center;margin-top:8px;">
            <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
            <button class="btn" data-action="toggle-extract">${this._autoExtractOpen ? "▾" : "▸"} 自动识别</button>
          </div>
          ${this._autoExtractOpen ? this._renderAutoExtractPanel("world_entity_extraction", "从章节正文中识别世界对象候选") : ""}
        </div>
      `
    }

    let html = `
      <div style="text-align:center;margin-bottom:12px;">
        <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
        <button class="btn" data-action="toggle-extract" style="margin-left:8px;">
          ${this._autoExtractOpen ? "▾" : "▸"} 自动识别
        </button>
      </div>
      ${this._autoExtractOpen ? this._renderAutoExtractPanel("world_entity_extraction", "从章节正文中识别世界对象候选") : ""}
      <table class="data-table">
        <thead>
          <tr>
            <th>状态</th>
            <th>类型</th>
            <th>名称</th>
            <th>重要度</th>
            <th>摘要</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const e of this._entities) {
      const statusClass = `badge-${e.status || "canonical"}`
      const statusText = { canonical: "正史", draft: "草稿", candidate: "候选", deprecated: "废弃" }
      html += `
        <tr data-id="${esc(e.id || e.entity_id)}" class="clickable">
          <td><span class="badge ${statusClass}">${statusText[e.status] || esc(e.status)}</span></td>
          <td style="color:var(--accent-dim);font-family:var(--font-mono);font-size:12px;">${esc(e.entity_type || "-")}</td>
          <td>${esc(e.name)}</td>
          <td>${esc(e.importance || e.importance_score || "-")}</td>
          <td style="color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(e.summary || e.public_info || "-")}</td>
          <td>
            <button class="btn btn-sm" data-action="edit-entity" data-id="${esc(e.id || e.entity_id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-entity" data-id="${esc(e.id || e.entity_id)}">删除</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html += `
      <div style="margin-top:12px;text-align:center;">
        <button class="btn" data-action="nav-candidates">查看候选（${this._candidates.length}）</button>
      </div>
    `
    return html
  },

  _renderCandidatesList() {
    if (this._candidates.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128269;</div>
          <p>没有待处理的候选对象。</p>
          <p>AI 从文本中抽取的候选对象会出现在这里，你可以决定如何处置它们。</p>
          <div style="display:flex;gap:8px;justify-content:center;margin-top:8px;">
            <button class="btn" data-action="nav-generate">去生成中心创建候选</button>
          </div>
        </div>
      `
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        以下是从文本中抽取的候选对象。请检查并决定如何处理。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>重要度</th>
            <th>建议动作</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const c of this._candidates) {
      const actionMap = {
        create_new: "创建新对象",
        alias_of_existing: "作为别名",
        merge_with_existing: "合并到已有",
        temporary_only: "设为临时",
        ignore: "忽略",
        needs_user_decision: "需用户决定",
      }

      const isMergeCandidate = c.suggested_action === "alias_of_existing" || c.suggested_action === "merge_with_existing"

      html += `
        <tr data-id="${esc(c.id || c.candidate_id)}">
          <td>${esc(c.name)}</td>
          <td style="color:var(--accent-dim);font-family:var(--font-mono)">${esc(c.entity_type)}</td>
          <td>${esc(c.importance_score || c.importance || "-")}</td>
          <td style="color:var(--warning)">${esc(actionMap[c.suggested_action] || c.suggested_action)}</td>
          <td style="display:flex;gap:4px;flex-wrap:wrap;">
            <button class="btn btn-sm btn-primary" data-action="accept-candidate" data-id="${esc(c.id || c.candidate_id)}">确认</button>
            ${isMergeCandidate && c.suggested_existing_entity_name ? `
              <button class="btn btn-sm" data-action="merge-candidate" data-id="${esc(c.id || c.candidate_id)}" data-entity-id="${esc(c.suggested_existing_entity_id)}" data-entity-name="${esc(c.suggested_existing_entity_name)}">合并到</button>
            ` : ""}
            <button class="btn btn-sm btn-danger" data-action="ignore-candidate" data-id="${esc(c.id || c.candidate_id)}">忽略</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    return html
  },

  async mergeCandidate(candidateId, targetEntityId, targetName) {
    candidateId = candidateId || ""
    targetEntityId = targetEntityId || ""
    targetName = targetName || ""

    confirmAction(
      `将候选合并到「${esc(targetName)}」？\n\n候选名称会成为「${esc(targetName)}」的别名，概要等信息会追加合并。`,
      async () => {
        if (!_state.currentProjectId) {
          toast("请先选择项目", "warning")
          return
        }
        try {
          const result = await api.world.mergeCandidate(targetEntityId, candidateId, {
            novel_id: _state.currentProjectId,
          })
          toast(`已合并到「${esc(result.name || targetName)}」`, "success")
          router.navigate("world", "candidates")
        } catch (err) {
          toast(`合并失败：${err.message}`, "error")
        }
      },
      "确认合并"
    )
  },

  async _renderRelations() {
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        管理世界对象与人物之间的关系。
      </p>
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-relation">新建关系</button>
      </div>
    `
    if (!_state.currentProjectId) return html + '<div class="empty-state"><p>请先选择项目。</p></div>'

    try {
      const data = await api.world.listRelationships({ novel_id: _state.currentProjectId })
      const rels = data.items || data || []
      if (rels.length === 0) {
        return html + '<div class="empty-state"><p>暂无关系。</p></div>'
      }
      html += `
      <table class="data-table">
        <thead><tr><th>源对象</th><th>关系类型</th><th>目标对象</th><th>描述</th><th>操作</th></tr></thead>
        <tbody>
      `
      for (const r of rels) {
        html += `
        <tr data-id="${esc(r.id || r.relationship_id)}">
          <td style="color:var(--accent-dim);font-size:12px;">${esc(r.source_id || "").slice(0, 8)}...</td>
          <td><span class="badge badge-canonical">${esc(r.relation_type || "-")}</span></td>
          <td style="color:var(--accent-dim);font-size:12px;">${esc(r.target_id || "").slice(0, 8)}...</td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-dim);font-size:12px;">${esc(r.description || "")}</td>
          <td><button class="btn btn-sm btn-danger" data-action="delete-relation" data-id="${esc(r.id || r.relationship_id)}">删除</button></td>
        </tr>`
      }
      html += '</tbody></table>'
    } catch { html += '<div class="empty-state"><p>加载关系失败。</p></div>' }
    return html
  },

  showRelationCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>源对象 ID</label>
        <input class="form-input" id="rel-source" placeholder="对象 ID" />
      </div>
      <div class="form-group">
        <label>关系类型</label>
        <select class="form-select" id="rel-type">
          <option value="friend_of">朋友</option>
          <option value="enemy_of">敌人</option>
          <option value="ally_of">盟友</option>
          <option value="member_of">成员</option>
          <option value="leader_of">领导者</option>
          <option value="located_at">位于</option>
          <option value="contains">包含</option>
          <option value="related_to">相关</option>
        </select>
      </div>
      <div class="form-group">
        <label>目标对象 ID</label>
        <input class="form-input" id="rel-target" placeholder="对象 ID" />
      </div>
      <div class="form-group">
        <label>描述</label>
        <input class="form-input" id="rel-desc" placeholder="关系描述（可选）" />
      </div>
    `
    showModal("新建关系", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const src = document.getElementById("rel-source")?.value
        const tgt = document.getElementById("rel-target")?.value
        if (!src || !tgt) { toast("请输入源对象和目标对象 ID", "warning"); return }
        try {
          await api.world.createRelationship({
            source_id: src, source_type: "entity",
            target_id: tgt, target_type: "entity",
            relation_type: document.getElementById("rel-type")?.value || "related_to",
            description: document.getElementById("rel-desc")?.value || "",
          }, _state.currentProjectId)
          toast("关系已创建", "success")
          router.navigate("world", "relations")
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  deleteRelation(relId) {
    confirmAction("确定删除此关系？", async () => {
      try {
        await api.world.deleteRelationship(relId, { novel_id: _state.currentProjectId })
        toast("已删除", "success")
        router.navigate("world", "relations")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  async _renderAliases() {
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        管理世界对象的别名、称号和化名。别名不独立创建对象。
      </p>
      <div style="margin-bottom:8px;">
        <button class="btn btn-primary" data-action="create-alias">新建别名</button>
      </div>
    `
    if (!_state.currentProjectId) return html + '<div class="empty-state"><p>请先选择项目。</p></div>'

    try {
      const data = await api.world.listAliases({ novel_id: _state.currentProjectId })
      const aliases = data.items || data || []
      if (aliases.length === 0) {
        return html + '<div class="empty-state"><p>暂无别名。</p></div>'
      }
      const typeMap = { name: "名称", title: "称号", nickname: "昵称", alias: "化名", translation: "译名" }
      html += `
      <table class="data-table">
        <thead><tr><th>对象</th><th>别名</th><th>类型</th><th>置信度</th><th>操作</th></tr></thead>
        <tbody>
      `
      for (const a of aliases) {
        html += `
        <tr data-id="${esc(a.id || a.alias_id)}">
          <td style="color:var(--accent-dim);font-size:12px;">${esc(a.entity_id || "").slice(0, 8)}...</td>
          <td>${esc(a.alias)}</td>
          <td>${typeMap[a.alias_type] || esc(a.alias_type)}</td>
          <td>${a.confidence ? (a.confidence * 100).toFixed(0) + "%" : "-"}</td>
          <td><button class="btn btn-sm btn-danger" data-action="delete-alias" data-id="${esc(a.id || a.alias_id)}">删除</button></td>
        </tr>`
      }
      html += '</tbody></table>'
    } catch { html += '<div class="empty-state"><p>加载别名失败。</p></div>' }
    return html
  },

  showAliasCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>所属对象 ID</label>
        <input class="form-input" id="alias-entity" placeholder="对象 ID" />
      </div>
      <div class="form-group">
        <label>别名文本</label>
        <input class="form-input" id="alias-text" placeholder="别名" />
      </div>
      <div class="form-group">
        <label>别名类型</label>
        <select class="form-select" id="alias-type">
          <option value="name">名称</option>
          <option value="title">称号</option>
          <option value="nickname">昵称</option>
          <option value="alias">化名</option>
          <option value="translation">译名</option>
        </select>
      </div>
    `
    showModal("新建别名", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const eid = document.getElementById("alias-entity")?.value
        const text = document.getElementById("alias-text")?.value
        if (!eid || !text) { toast("请输入对象 ID 和别名", "warning"); return }
        try {
          await api.world.createAlias({
            novel_id: _state.currentProjectId,
            entity_id: eid, alias: text,
            alias_type: document.getElementById("alias-type")?.value || "name",
          })
          toast("别名已创建", "success")
          router.navigate("world", "aliases")
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  deleteAlias(aliasId) {
    confirmAction("确定删除此别名？", async () => {
      try {
        await api.world.deleteAlias(aliasId, { novel_id: _state.currentProjectId })
        toast("已删除", "success")
        router.navigate("world", "aliases")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  editEntity(id) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === id)
    if (!entity) return

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-entity-name" value="${esc(entity.name)}" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="edit-entity-type">
          <option value="location" ${entity.entity_type === "location" ? "selected" : ""}>地点</option>
          <option value="faction" ${entity.entity_type === "faction" ? "selected" : ""}>组织</option>
          <option value="item" ${entity.entity_type === "item" ? "selected" : ""}>物品</option>
          <option value="event" ${entity.entity_type === "event" ? "selected" : ""}>事件</option>
          <option value="character_ref" ${entity.entity_type === "character_ref" ? "selected" : ""}>人物引用</option>
        </select>
      </div>
      <div class="form-group">
        <label>概要</label>
        <textarea class="form-textarea" id="edit-entity-summary" rows="3">${esc(entity.summary || "")}</textarea>
      </div>
    `

    showModal("编辑世界对象", formHtml, [
      {
        text: "保存",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.world.updateEntity(id, {
              name: document.getElementById("edit-entity-name")?.value,
              entity_type: document.getElementById("edit-entity-type")?.value,
              summary: document.getElementById("edit-entity-summary")?.value,
            }, _state.currentProjectId)
            toast("已保存", "success")
            router.navigate("world", "objects")
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  deleteEntity(id) {
    confirmAction("确定要删除此世界对象吗？此操作不可撤销。", async () => {
      try {
        await api.world.deleteEntity(id, _state.currentProjectId)
        toast("已删除", "success")
        router.navigate("world", "objects")
      } catch (err) {
        toast(`删除失败：${err.message}`, "error")
      }
    }, "确认删除")
  },

  acceptCandidate(id) {
    const candidate = this._candidates.find((c) => (c.id || c.candidate_id) === id)
    if (!candidate) return

    const action = candidate.suggested_action || "create_new"
    const actionText = {
      create_new: "创建为新世界对象",
      alias_of_existing: `作为 "${candidate.suggested_existing_entity_name || "已有对象"}" 的别名`,
      merge_with_existing: `合并到 "${candidate.suggested_existing_entity_name || "已有对象"}"`,
    }

    confirmAction(
      `确认将 "${candidate.name}" 处理为：${actionText[action] || action}？`,
      async () => {
        try {
          await api.world.acceptCandidate(id, _state.currentProjectId)
          toast(`候选 "${candidate.name}" 已接受`, "success")
          router.navigate("world", "candidates")
        } catch (err) {
          toast(`处理失败：${err.message}`, "error")
        }
      },
      "确认"
    )
  },

  ignoreCandidate(id) {
    const candidate = this._candidates.find((c) => (c.id || c.candidate_id) === id)
    confirmAction(
      `确定忽略候选 "${candidate?.name || id}"？`,
      async () => {
        try {
          await api.world.confirmCandidate(id, { suggested_action: "ignore", status: "ignored" }, _state.currentProjectId)
          toast("已忽略", "success")
          router.navigate("world", "candidates")
        } catch (err) {
          toast(`操作失败：${err.message}`, "error")
        }
      },
      "忽略"
    )
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
        case "nav-objects": router.navigate("world", "objects"); break
        case "nav-candidates": router.navigate("world", "candidates"); break
        case "nav-relations": router.navigate("world", "relations"); break
        case "nav-aliases": router.navigate("world", "aliases"); break
        case "nav-generate": router.navigate("generate"); break
        case "toggle-extract": this._toggleAutoExtract(); break
        case "submit-extract": this._submitAutoExtract(t.getAttribute("data-type")); break
        case "edit-entity": if (id) this.editEntity(id); break
        case "delete-entity": if (id) this.deleteEntity(id); break
        case "accept-candidate": if (id) this.acceptCandidate(id); break
        case "merge-candidate": if (id) this.mergeCandidate(id, t.getAttribute("data-entity-id"), t.getAttribute("data-entity-name")); break
        case "ignore-candidate": if (id) this.ignoreCandidate(id); break
        case "create-relation": this.showRelationCreateForm(); break
        case "delete-relation": if (id) this.deleteRelation(id); break
        case "create-alias": this.showAliasCreateForm(); break
        case "delete-alias": if (id) this.deleteAlias(id); break
      }
    }
    content.addEventListener("click", this._clickHandler)

    document.getElementById("btn-new-entity")?.addEventListener("click", () => this._showCreateForm())
  },

  _showCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>名称 *</label>
        <input class="form-input" id="create-entity-name" placeholder="对象名称" />
      </div>
      <div class="form-group">
        <label>类型</label>
        <select class="form-select" id="create-entity-type">
          <option value="location">地点</option>
          <option value="faction">组织</option>
          <option value="item">物品</option>
          <option value="event">事件</option>
          <option value="rule">规则</option>
          <option value="power_system">能力体系</option>
          <option value="secret">秘密</option>
          <option value="legend">传说</option>
          <option value="resource">资源</option>
          <option value="character_ref">人物引用</option>
        </select>
      </div>
      <div class="form-group">
        <label>概要</label>
        <textarea class="form-textarea" id="create-entity-summary" rows="3" placeholder="简要描述"></textarea>
      </div>
    `

    showModal("新建世界对象", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          const name = document.getElementById("create-entity-name")?.value
          if (!name) {
            toast("请输入名称", "warning")
            return
          }

          try {
            await api.world.createEntity({
              name,
              entity_type: document.getElementById("create-entity-type")?.value || "item",
              summary: document.getElementById("create-entity-summary")?.value || "",
            }, _state.currentProjectId)
            toast(`对象 "${name}" 已创建`, "success")
            router.navigate("world", "objects")
          } catch (err) {
            toast(`创建失败：${err.message}`, "error")
          }
        },
      },
    ])
  },
}

router.registerView("world", worldView)
window.worldView = worldView


export default worldView
