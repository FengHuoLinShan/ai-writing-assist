/**
 * 世界对象视图
 */
const worldView = {
  /** @type {Array} */
  _entities: [],

  /** @type {Array} */
  _candidates: [],

  async render() {
    const subView = _state.currentSubView || "objects"
    let html = ''

    // 子标签导航
    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "objects" ? "active" : ""}" data-subview="objects" onclick="router.navigate('world','objects')">对象库</span>
        <span class="subnav-item ${subView === "candidates" ? "active" : ""}" data-subview="candidates" onclick="router.navigate('world','candidates')">候选清洗</span>
        <span class="subnav-item ${subView === "relations" ? "active" : ""}" data-subview="relations" onclick="router.navigate('world','relations')">关系</span>
        <span class="subnav-item ${subView === "aliases" ? "active" : ""}" data-subview="aliases" onclick="router.navigate('world','aliases')">别名</span>
      </div>
    `

    if (subView === "objects") {
      html += this._renderEntityList()
    } else if (subView === "candidates") {
      html += this._renderCandidatesList()
    } else if (subView === "relations") {
      html += this._renderRelations()
    } else if (subView === "aliases") {
      html += this._renderAliases()
    }

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  async onEnter() {
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
        const data = await api.world.listCandidates({ novel_id: _state.currentProjectId })
        this._candidates = data.items || data || []
      }
    } catch {
      this._candidates = []
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
          </div>
        </div>
      `
    }

    let html = `
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
        <tr data-id="${e.id || e.entity_id}" class="clickable">
          <td><span class="badge ${statusClass}">${statusText[e.status] || e.status}</span></td>
          <td style="color:var(--accent-dim);font-family:var(--font-mono);font-size:12px;">${e.entity_type || "-"}</td>
          <td>${e.name}</td>
          <td>${e.importance || e.importance_score || "-"}</td>
          <td style="color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${e.summary || e.public_info || "-"}</td>
          <td>
            <button class="btn btn-sm" onclick="event.stopPropagation();worldView.editEntity('${esc(e.id || e.entity_id)}')">编辑</button>
            <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();worldView.deleteEntity('${esc(e.id || e.entity_id)}')">删除</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html += `
      <div style="margin-top:12px;display:flex;gap:8px;">
        <button class="btn btn-primary" data-action="new" id="btn-new-entity">新建对象</button>
        <button class="btn" onclick="router.navigate('world','candidates')">查看候选（${this._candidates.length}）</button>
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
            <button class="btn" onclick="router.navigate('generate')">去生成中心创建候选</button>
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

      html += `
        <tr data-id="${c.id || c.candidate_id}">
          <td>${c.name}</td>
          <td style="color:var(--accent-dim);font-family:var(--font-mono)">${c.entity_type}</td>
          <td>${c.importance_score || c.importance || "-"}</td>
          <td style="color:var(--warning)">${actionMap[c.suggested_action] || c.suggested_action}</td>
          <td>
            <button class="btn btn-sm btn-primary" onclick="worldView.acceptCandidate('${esc(c.id || c.candidate_id)}')">确认</button>
            <button class="btn btn-sm btn-danger" onclick="worldView.ignoreCandidate('${esc(c.id || c.candidate_id)}')">忽略</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    return html
  },

  _renderRelations() {
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128279;</div>
        <p>关系管理</p>
        <p style="color:var(--text-dim);font-size:12px;">在此管理世界对象之间的关系。</p>
        <div style="margin-top:8px;">
          <button class="btn" onclick="toast('关系管理功能开发中', 'info')">新建关系</button>
        </div>
      </div>
    `
  },

  _renderAliases() {
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128212;</div>
        <p>别名管理</p>
        <p style="color:var(--text-dim);font-size:12px;">管理世界对象的别名、称号和化名。</p>
      </div>
    `
  },

  editEntity(id) {
    const entity = this._entities.find((e) => (e.id || e.entity_id) === id)
    if (!entity) return

    const formHtml = `
      <div class="form-group">
        <label>名称</label>
        <input class="form-input" id="edit-entity-name" value="${entity.name}" />
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
        <textarea class="form-textarea" id="edit-entity-summary" rows="3">${entity.summary || ""}</textarea>
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
            })
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
        await api.world.deleteEntity(id)
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
          await api.world.confirmCandidate(id, { suggested_action: action })
          toast(`候选 "${candidate.name}" 已处理`, "success")
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
          await api.world.confirmCandidate(id, { suggested_action: "ignore" })
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
              novel_id: _state.currentProjectId,
              name,
              entity_type: document.getElementById("create-entity-type")?.value || "item",
              summary: document.getElementById("create-entity-summary")?.value || "",
            })
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
