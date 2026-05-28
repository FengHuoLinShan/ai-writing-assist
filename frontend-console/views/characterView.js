/**
 * 人物档案视图
 *
 * 子标签：人物列表 | 人物档案 | 知识边界
 */
const characterView = {
  /** @type {Array} 人物列表 */
  _characters: [],

  /** @type {Array} 当前选中人物的知识边界 */
  _characterKnowledge: [],

  /** @type {boolean} API 是否可用 */
  _apiAvailable: false,

  /**
   * 进入视图时加载人物列表
   */
  async onEnter() {
    if (!_state.currentProjectId) {
      this._characters = []
      _state.selectedItem = null
      return
    }

    try {
      const data = await api.character.list({ novel_id: _state.currentProjectId })
      this._characters = data.items || data || []
      this._apiAvailable = true
    } catch {
      this._apiAvailable = false
      this._characters = []
    }

    if (!_state.currentSubView || _state.currentSubView === "list") {
      _state.selectedItem = null
    }
  },

  /**
   * 渲染主视图
   */
  async render() {
    const subView = _state.currentSubView || "list"
    let html = ''

    html += `
      <div class="subnav">
        <span class="subnav-item ${subView === "list" ? "active" : ""}" data-subview="list" data-action="nav-list">人物列表</span>
        <span class="subnav-item ${subView === "detail" ? "active" : ""}" data-subview="detail" data-action="nav-detail">人物档案</span>
        <span class="subnav-item ${subView === "knowledge" ? "active" : ""}" data-subview="knowledge" data-action="nav-knowledge">知识边界</span>
      </div>
    `

    if (subView === "detail") html += this._renderDetail()
    else if (subView === "knowledge") html += this._renderKnowledge()
    else html += this._renderList()

    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  // ============================================================
  // 人物列表
  // ============================================================

  _renderList() {
    if (!this._apiAvailable) {
      return `
        <div class="empty-state">
          <div class="empty-icon" style="color:var(--warning);">&#9888;</div>
          <p>无法连接到后端服务</p>
          <p style="color:var(--text-dim);font-size:12px;">请确认后端已启动，然后刷新页面。</p>
          <div style="margin-top:8px;">
            <button class="btn" data-action="nav-list">重试</button>
          </div>
        </div>
      `
    }

    if (this._characters.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128100;</div>
          <p>还没有人物档案。</p>
          <p>记录小说中的主要人物、配角的档案和当前状态。</p>
          <div style="margin-top:8px;">
            <button class="btn btn-primary" data-action="new" id="btn-new-character">新建人物</button>
            <span style="color:var(--text-dim);font-size:11px;">人物抽取已合并到「世界对象 → 自动识别」</span>
          </div>
        </div>
      `
    }

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        点击人物名称可查看完整档案。共 ${this._characters.length} 个人物。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>定位</th>
            <th>当前目标</th>
            <th>当前状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const c of this._characters) {
      const charId = c.id || c.character_id
      html += `
        <tr data-id="${esc(charId)}" class="clickable" data-action="select-character">
          <td><strong>${esc(c.name)}</strong></td>
          <td>${esc(c.role || "-")}</td>
          <td style="color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(c.current_goal || "-")}</td>
          <td>${esc(c.current_state || c.current_emotion || "-")}</td>
          <td>
            <button class="btn btn-sm" data-action="select-character" data-id="${esc(charId)}">查看</button>
            <button class="btn btn-sm" data-action="edit-character" data-id="${esc(charId)}">编辑</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    html += `
      <div style="margin-top:12px;text-align:center;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
        <button class="btn btn-primary" data-action="new" id="btn-new-character">新建人物</button>
        <button class="btn" id="btn-extract-all" data-action="extract-all">全部更新</button>
        <span style="color:var(--text-dim);font-size:11px;">人物抽取已合并到「世界对象 → 自动识别」</span>
      </div>`
    return html
  },

  /**
   * 选中人物 — 更新状态并切换到档案子标签
   */
  async _selectCharacter(charId) {
    const character = this._characters.find((c) => (c.id || c.character_id) === charId)
    if (!character) return

    _state.selectedItem = character

    router.navigate("character", "detail")

    if (_state.currentProjectId) {
      try {
        const full = await api.character.get(charId, _state.currentProjectId)
        if (full) {
          Object.assign(character, full)
          _state.selectedItem = character
          const content = document.getElementById("workspace-content")
          if (content && _state.currentView === "character" && _state.currentSubView === "detail") {
            const detailHtml = this._renderDetail()
            const detailArea = content.querySelector(".subnav")
            if (detailArea) {
              const existing = detailArea.nextSibling
              while (existing && existing.nextSibling) {
                content.removeChild(content.lastChild)
              }
              detailArea.insertAdjacentHTML("afterend", detailHtml)
            }
          }
        }
      } catch {
        // API 失败时使用列表数据降级
      }
    }

    _state.rightPanel = {
      title: character.name,
      type: "character",
      content: `
        <div class="help-section">
          <h4>${esc(character.name)}</h4>
          <p>定位：${character.role || "未设定"}</p>
          <p>当前目标：${character.current_goal || "-"}</p>
          <p>当前状态：${character.current_state || "-"}</p>
          <p>语言风格：${character.voice_style || "-"}</p>
          <hr style="border-color:var(--border);margin:8px 0;">
          <p style="color:var(--text-dim);font-size:12px;">
            <a style="cursor:pointer;color:var(--accent);" data-action="nav-detail">查看完整档案</a><br>
            <a style="cursor:pointer;color:var(--accent);" data-action="nav-knowledge">查看知识边界</a>
          </p>
        </div>
      `,
    }
  },

  // ============================================================
  // 人物档案详情（修复：现在渲染在主工作区）
  // ============================================================

  _renderDetail() {
    const character = _state.selectedItem

    if (!character) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128100;</div>
          <p>未选择人物</p>
          <p style="color:var(--text-dim);font-size:12px;">
            请先在
            <a style="cursor:pointer;color:var(--accent);" data-action="nav-list">人物列表</a>
            中选择一个角色，然后在此查看完整档案。
          </p>
          <div style="margin-top:8px;">
            <button class="btn btn-primary" data-action="nav-list">前往人物列表</button>
          </div>
        </div>
      `
    }

    const charId = character.id || character.character_id

    // 将 desire/fear 等可能的 null 转为占位符
    const fields = [
      { label: "欲望", value: character.desire, icon: "🎯", color: "var(--accent)" },
      { label: "恐惧", value: character.fear, icon: "😨", color: "var(--warning)" },
      { label: "秘密", value: character.secret, icon: "🔒", color: "var(--danger)" },
      { label: "弱点", value: character.weakness, icon: "💔", color: "var(--text-muted)" },
      { label: "当前目标", value: character.current_goal, icon: "🎯", color: "var(--accent)" },
      { label: "当前状态", value: character.current_state, icon: "📌", color: "var(--info)" },
      { label: "当前情绪", value: character.current_emotion, icon: "💭", color: "var(--text)" },
      { label: "立场", value: character.stance, icon: "⚖️", color: "var(--text)" },
      { label: "语言风格", value: character.voice_style, icon: "🎙️", color: "var(--accent-dim)" },
      { label: "行为边界", value: character.behavior_rules, icon: "🚧", color: "var(--warning)", isArray: true },
    ]

    let html = `
      <div style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <h3 style="margin:0;color:var(--text);font-size:20px;">${character.name}</h3>
            <p style="color:var(--text-muted);margin:4px 0 0 0;font-size:13px;">
              ${character.role || "未设定定位"}
              ${character.appearance ? " | " + character.appearance.substring(0, 30) + (character.appearance.length > 30 ? "..." : "") : ""}
            </p>
          </div>
          <div>
            <button class="btn btn-primary" id="btn-edit-character" data-action="edit-character" data-id="${esc(charId)}">编辑档案</button>
            <button class="btn" id="btn-extract-single" data-action="extract-character" data-id="${esc(charId)}">提取档案</button>
            <button class="btn" data-action="nav-knowledge">知识边界</button>
          </div>
        </div>
        <hr style="border-color:var(--border);margin:12px 0;">
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
    `

    for (const field of fields) {
      let displayValue = "-"
      if (field.value) {
        if (field.isArray) {
          const rules = Array.isArray(field.value) ? field.value : []
          displayValue = rules.length > 0
            ? rules.map((r) => `&#8226; ${r}`).join("<br>")
            : "无特殊限制"
        } else {
          displayValue = String(field.value)
        }
      }

      html += `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:12px;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
            <span>${field.icon}</span>
            <strong style="color:${field.color};font-size:13px;">${field.label}</strong>
          </div>
          <p style="color:var(--text);margin:0;font-size:13px;line-height:1.5;">${displayValue}</p>
        </div>
      `
    }

    html += `
      </div>

      <div style="margin-top:16px;background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:12px;">
        <strong style="color:var(--text-muted);font-size:12px;">关系摘要</strong>
        <p style="color:var(--text);margin:4px 0 0 0;font-size:13px;">${character.relationship_summary || "暂无关系记录"}</p>
      </div>
    `

    // AI 建议区域
    const suggestions = (character.meta && character.meta.ai_suggestions) || {}
    const suggestionKeys = Object.keys(suggestions)
    if (suggestionKeys.length > 0) {
      const fieldLabelMap = {
        role: "定位", desire: "欲望", fear: "恐惧", secret: "秘密",
        weakness: "弱点", current_goal: "当前目标", current_state: "当前状态",
        current_emotion: "当前情绪", stance: "立场", voice_style: "语言风格",
      }
      html += `
        <div style="margin-top:16px;border:1px solid var(--warning);border-radius:4px;padding:12px;background:rgba(255,193,7,0.05);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <span style="font-weight:bold;font-size:13px;color:var(--warning);">💡 AI 建议（${suggestionKeys.length} 个字段）</span>
            <div>
              <button class="btn btn-sm" style="border-color:var(--warning);color:var(--warning);" data-action="apply-all-suggestions">全部采纳</button>
            </div>
          </div>
      `
      for (const field of suggestionKeys) {
        const label = fieldLabelMap[field] || field
        const original = character[field] || "-"
        const suggested = suggestions[field]
        html += `
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:10px;margin-bottom:6px;">
            <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px;">
              <strong style="color:var(--warning);">${label}</strong>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
              <div style="font-size:12px;">
                <span style="color:var(--text-dim);">原文：</span>
                <span style="color:var(--text-muted);">${esc(String(original).substring(0, 100))}</span>
              </div>
              <div style="font-size:12px;">
                <span style="color:var(--accent);">建议：</span>
                <span style="color:var(--text);">${esc(String(suggested).substring(0, 100))}</span>
              </div>
            </div>
            <div style="margin-top:6px;display:flex;gap:6px;justify-content:flex-end;">
              <button class="btn btn-sm" style="font-size:10px;border-color:var(--accent);color:var(--accent);" data-action="apply-suggestion" data-field="${field}">采纳</button>
              <button class="btn btn-sm" style="font-size:10px;" data-action="reject-suggestion" data-field="${field}">忽略</button>
            </div>
          </div>
        `
      }
      html += `</div>`
    }

    return html
  },

  // ============================================================
  // 知识边界（修复：现在从 API 加载 + 渲染表格）
  // ============================================================

  async _renderKnowledge() {
    const character = _state.selectedItem

    if (!character) {
      return `
        <div class="empty-state">
          <div class="empty-icon">&#128214;</div>
          <p>未选择人物</p>
          <p style="color:var(--text-dim);font-size:12px;">
            请先在
            <a style="cursor:pointer;color:var(--accent);" data-action="nav-list">人物列表</a>
            中选择一个角色，然后在此查看其知识边界。
          </p>
          <div style="margin-top:8px;">
            <button class="btn btn-primary" data-action="nav-list">前往人物列表</button>
          </div>
        </div>
      `
    }

    // 加载知识边界数据
    let knowledges = []
    try {
      const charId = character.id || character.character_id
      const data = await api.character.listKnowledge(charId, _state.currentProjectId)
      knowledges = data.items || data || []
      this._characterKnowledge = knowledges
    } catch {
      // API 不可用时使用演示数据
      this._characterKnowledge = [
        {
          id: "k1",
          target_type: "location",
          target_name: "旧王都焚毁事件",
          knowledge_level: "partial",
          known_content: "官方档案存在缺页",
          misconception: "",
        },
        {
          id: "k2",
          target_type: "item",
          target_name: "残缺王印",
          knowledge_level: "rumor",
          known_content: "知道主角持有异常物品",
          misconception: "以为是普通古物",
        },
        {
          id: "k3",
          target_type: "secret",
          target_name: "家族旧印",
          knowledge_level: "unknown",
          known_content: "",
          misconception: "",
        },
        {
          id: "k4",
          target_type: "organization",
          target_name: "监察院",
          knowledge_level: "full",
          known_content: "监察院的公开组织结构和部分机密权限",
          misconception: "",
        },
      ]
      knowledges = this._characterKnowledge
    }

    const levelMap = {
      unknown: { label: "不知道", color: "var(--text-dim)" },
      rumor: { label: "传闻", color: "var(--warning)" },
      partial: { label: "部分知道", color: "var(--info)" },
      full: { label: "完全知道", color: "var(--accent)" },
      false_belief: { label: "错误认知", color: "var(--danger)" },
    }

    let html = `
      <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <h4 style="margin:0;color:var(--text);">${character.name} 的知识边界</h4>
            <p style="color:var(--text-dim);font-size:12px;margin:4px 0 0 0;">
              该角色知道什么、不知道什么、误解什么。
              用于防止角色知道作者才知道的信息。
            </p>
          </div>
          <button class="btn" data-action="add-knowledge">添加知识</button>
        </div>
      </div>
    `

    if (knowledges.length === 0) {
      html += `
        <div class="empty-state">
          <div class="empty-icon">&#128214;</div>
          <p>${character.name} 暂无知识边界记录</p>
          <p style="color:var(--text-dim);font-size:12px;">可以手动添加或通过状态抽取自动生成。</p>
          <div style="margin-top:8px;"><button class="btn btn-primary" data-action="add-knowledge">添加知识</button></div>
        </div>
      `
      return html
    }

    html += `
      <table class="data-table">
        <thead>
          <tr>
            <th>目标对象</th>
            <th>知识等级</th>
            <th>已知内容</th>
            <th>误解</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    for (const k of knowledges) {
      const level = levelMap[k.knowledge_level] || { label: k.knowledge_level, color: "var(--text-muted)" }
      const targetName = k.target_name || k.target_id || k.target_id || "-"

      html += `
        <tr>
          <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            <span style="color:var(--text-dim);font-size:11px;">${k.target_type || ""}</span>
            <span>${targetName}</span>
          </td>
          <td><span class="badge" style="background:${level.color};color:var(--bg);">${level.label}</span></td>
          <td style="color:var(--text-muted);max-width:200px;">${k.known_content || "-"}</td>
          <td style="color:var(--danger);max-width:150px;">${k.misconception || "-"}</td>
          <td>
            <button class="btn btn-sm" data-action="edit-knowledge" data-id="${esc(k.id || k.knowledge_id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-knowledge" data-id="${esc(k.id || k.knowledge_id)}">删除</button>
          </td>
        </tr>
      `
    }

    html += '</tbody></table>'
    return html
  },

  // ============================================================
  // 编辑人物（修复：现在有完整表单和 API 调用）
  // ============================================================

  _editCharacter(charId) {
    const character = this._characters.find((c) => (c.id || c.character_id) === charId)
    if (!character) {
      toast("未找到人物数据", "error")
      return
    }

    const behaviorRulesStr = Array.isArray(character.behavior_rules)
      ? character.behavior_rules.join("\n")
      : (character.behavior_rules || "")

    const formHtml = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>姓名 *</label>
          <input class="form-input" id="edit-char-name" value="${character.name || ""}" />
        </div>
        <div class="form-group">
          <label>定位</label>
          <select class="form-select" id="edit-char-role">
            <option value="">选择定位</option>
            <option value="protagonist" ${character.role === "protagonist" ? "selected" : ""}>主角</option>
            <option value="heroine" ${character.role === "heroine" ? "selected" : ""}>女主</option>
            <option value="antagonist" ${character.role === "antagonist" ? "selected" : ""}>反派</option>
            <option value="support" ${character.role === "support" ? "selected" : ""}>配角</option>
            <option value="mentor" ${character.role === "mentor" ? "selected" : ""}>导师</option>
            <option value="other" ${character.role === "other" ? "selected" : ""}>其他</option>
          </select>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>欲望</label>
          <textarea class="form-textarea" id="edit-char-desire" rows="2">${character.desire || ""}</textarea>
        </div>
        <div class="form-group">
          <label>恐惧</label>
          <textarea class="form-textarea" id="edit-char-fear" rows="2">${character.fear || ""}</textarea>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>秘密</label>
          <textarea class="form-textarea" id="edit-char-secret" rows="2">${character.secret || ""}</textarea>
        </div>
        <div class="form-group">
          <label>弱点</label>
          <textarea class="form-textarea" id="edit-char-weakness" rows="2">${character.weakness || ""}</textarea>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>当前目标</label>
          <textarea class="form-textarea" id="edit-char-goal" rows="2">${character.current_goal || ""}</textarea>
        </div>
        <div class="form-group">
          <label>当前状态</label>
          <textarea class="form-textarea" id="edit-char-state" rows="2">${character.current_state || ""}</textarea>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>当前情绪</label>
          <input class="form-input" id="edit-char-emotion" value="${character.current_emotion || ""}" />
        </div>
        <div class="form-group">
          <label>立场</label>
          <input class="form-input" id="edit-char-stance" value="${character.stance || ""}" />
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>语言风格</label>
          <input class="form-input" id="edit-char-voice" value="${character.voice_style || ""}" placeholder="如：冷静克制、辛辣讽刺" />
        </div>
        <div class="form-group">
          <label>行为规则（每行一条）</label>
          <textarea class="form-textarea" id="edit-char-rules" rows="2" placeholder="每行一条行为边界规则">${behaviorRulesStr}</textarea>
        </div>
      </div>
    `

    showModal(`编辑人物：${character.name}`, formHtml, [
      {
        text: "保存",
        class: "btn-primary",
        handler: async () => {
          const data = {
            name: document.getElementById("edit-char-name")?.value,
            role: document.getElementById("edit-char-role")?.value || "",
            desire: document.getElementById("edit-char-desire")?.value || "",
            fear: document.getElementById("edit-char-fear")?.value || "",
            secret: document.getElementById("edit-char-secret")?.value || "",
            weakness: document.getElementById("edit-char-weakness")?.value || "",
            current_goal: document.getElementById("edit-char-goal")?.value || "",
            current_state: document.getElementById("edit-char-state")?.value || "",
            current_emotion: document.getElementById("edit-char-emotion")?.value || "",
            stance: document.getElementById("edit-char-stance")?.value || "",
            voice_style: document.getElementById("edit-char-voice")?.value || "",
            behavior_rules: (document.getElementById("edit-char-rules")?.value || "")
              .split("\n")
              .map((l) => l.trim())
              .filter((l) => l),
          }

          try {
            await api.character.update(charId, data, _state.currentProjectId)
            // 更新本地缓存
            const idx = this._characters.findIndex((c) => (c.id || c.character_id) === charId)
            if (idx >= 0) {
              this._characters[idx] = { ...this._characters[idx], ...data }
            }
            // 如果当前选中的就是此人，同步更新 selectedItem
            if (_state.selectedItem && (_state.selectedItem.id || _state.selectedItem.character_id) === charId) {
              _state.selectedItem = { ..._state.selectedItem, ...data }
            }
            toast(`人物 "${data.name}" 已保存`, "success")
            router.navigate("character", "detail")
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  // ============================================================
  // 知识边界编辑（新增）
  // ============================================================

  _editKnowledge(knowledgeId) {
    const knowledge = this._characterKnowledge.find(
      (k) => (k.id || k.knowledge_id) === knowledgeId
    )
    if (!knowledge) {
      toast("未找到知识记录", "error")
      return
    }

    const formHtml = `
      <div class="form-group">
        <label>目标对象</label>
        <input class="form-input" id="edit-know-target" value="${knowledge.target_name || knowledge.target_id || ""}" />
      </div>
      <div class="form-group">
        <label>知识等级</label>
        <select class="form-select" id="edit-know-level">
          <option value="unknown" ${knowledge.knowledge_level === "unknown" ? "selected" : ""}>不知道</option>
          <option value="rumor" ${knowledge.knowledge_level === "rumor" ? "selected" : ""}>传闻</option>
          <option value="partial" ${knowledge.knowledge_level === "partial" ? "selected" : ""}>部分知道</option>
          <option value="full" ${knowledge.knowledge_level === "full" ? "selected" : ""}>完全知道</option>
          <option value="false_belief" ${knowledge.knowledge_level === "false_belief" ? "selected" : ""}>错误认知</option>
        </select>
      </div>
      <div class="form-group">
        <label>已知内容</label>
        <textarea class="form-textarea" id="edit-know-content" rows="2">${knowledge.known_content || ""}</textarea>
      </div>
      <div class="form-group">
        <label>误解内容</label>
        <textarea class="form-textarea" id="edit-know-misconception" rows="2">${knowledge.misconception || ""}</textarea>
      </div>
    `

    showModal("编辑知识边界", formHtml, [
      {
        text: "保存",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.character.updateKnowledge(knowledge.id || knowledge.knowledge_id, {
              knowledge_level: document.getElementById("edit-know-level")?.value || "unknown",
              known_content: document.getElementById("edit-know-content")?.value || "",
              misconception: document.getElementById("edit-know-misconception")?.value || "",
            }, _state.currentProjectId)
            toast("已保存", "success")
            router.navigate("character", "detail")
          } catch (err) { toast(err.message || "保存失败", "error") }
        },
      },
    ])
  },

  /**
   * 添加知识边界
   */
  _addKnowledge() {
    const character = _state.selectedItem
    if (!character) {
      toast("请先选择人物", "warning")
      return
    }

    const formHtml = `
      <div class="form-group">
        <label>目标对象 ID</label>
        <input class="form-input" id="new-know-target" placeholder="选择或粘贴目标对象 ID" />
      </div>
      <div class="form-group">
        <label>目标类型</label>
        <select class="form-select" id="new-know-type">
          <option value="entity">世界对象</option>
          <option value="character">人物</option>
          <option value="location">地点</option>
          <option value="item">物品</option>
          <option value="secret">秘密</option>
          <option value="event">事件</option>
        </select>
      </div>
      <div class="form-group">
        <label>知识等级</label>
        <select class="form-select" id="new-know-level">
          <option value="unknown">不知道</option>
          <option value="rumor">传闻</option>
          <option value="partial">部分知道</option>
          <option value="full">完全知道</option>
          <option value="false_belief">错误认知</option>
        </select>
      </div>
      <div class="form-group">
        <label>已知内容</label>
        <textarea class="form-textarea" id="new-know-content" rows="2"></textarea>
      </div>
      <div class="form-group">
        <label>误解内容</label>
        <textarea class="form-textarea" id="new-know-misconception" rows="2"></textarea>
      </div>
    `

    showModal("添加知识边界", formHtml, [
      {
        text: "添加",
        class: "btn-primary",
        handler: async () => {
          const charId = character.id || character.character_id
          if (!charId) { toast("人物 ID 缺失", "error"); return }
          try {
            await api.character.createKnowledge(charId, {
              target_type: document.getElementById("new-know-type")?.value || "entity",
              target_id: document.getElementById("new-know-target")?.value || "",
              knowledge_level: document.getElementById("new-know-level")?.value || "unknown",
              known_content: document.getElementById("new-know-content")?.value || "",
              misconception: document.getElementById("new-know-misconception")?.value || "",
            }, _state.currentProjectId)
            toast("已添加", "success")
            router.navigate("character", "detail")
          } catch (err) { toast(err.message || "添加失败", "error") }
        },
      },
    ])
  },

  _deleteKnowledge(knowledgeId) {
    confirmAction("确定删除此知识记录？", async () => {
      try {
        await api.character.deleteKnowledge(knowledgeId, _state.currentProjectId)
        toast("已删除", "success")
        router.navigate("character", "detail")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },

  // ============================================================
  // 新建人物
  // ============================================================

  _showCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>姓名 *</label>
        <input class="form-input" id="create-char-name" placeholder="人物姓名" />
      </div>
      <div class="form-group">
        <label>定位</label>
        <select class="form-select" id="create-char-role">
          <option value="">选择定位</option>
          <option value="protagonist">主角</option>
          <option value="heroine">女主</option>
          <option value="antagonist">反派</option>
          <option value="support">配角</option>
          <option value="mentor">导师</option>
          <option value="other">其他</option>
        </select>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div class="form-group">
          <label>欲望</label>
          <textarea class="form-textarea" id="create-char-desire" rows="2" placeholder="最深层的欲望"></textarea>
        </div>
        <div class="form-group">
          <label>恐惧</label>
          <textarea class="form-textarea" id="create-char-fear" rows="2" placeholder="最恐惧的事情"></textarea>
        </div>
      </div>
      <div class="form-group">
        <label>语言风格</label>
        <input class="form-input" id="create-char-voice" placeholder="如：冷静克制、辛辣讽刺" />
      </div>
    `

    showModal("新建人物", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          const name = document.getElementById("create-char-name")?.value
          if (!name) { toast("请输入姓名", "warning"); return }

          try {
            await api.character.create({
              novel_id: _state.currentProjectId,
              name,
              role: document.getElementById("create-char-role")?.value || "",
              desire: document.getElementById("create-char-desire")?.value || "",
              fear: document.getElementById("create-char-fear")?.value || "",
              voice_style: document.getElementById("create-char-voice")?.value || "",
            })
            toast(`人物 "${name}" 已创建`, "success")
            router.navigate("character", "list")
          } catch (err) {
            toast(`创建失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  // ============================================================
  // 事件绑定
  // ============================================================

  _bindEvents() {
    const content = document.getElementById("workspace-content")
    if (!content) return
    content.removeEventListener("click", this._clickHandler)
    this._clickHandler = (e) => {
      const t = e.target.closest("[data-action]")
      if (!t) return
      const a = t.getAttribute("data-action")
      const id = t.getAttribute("data-id") || t.closest("[data-id]")?.getAttribute("data-id")
      switch (a) {
        case "nav-list": router.navigate("character", "list"); break
        case "nav-detail": router.navigate("character", "detail"); break
        case "nav-knowledge": router.navigate("character", "knowledge"); break
        case "select-character": if (id) this._selectCharacter(id); break
        case "edit-character": if (id) this._editCharacter(id); break
        case "extract-character": if (id) this._extractCharacter(id); break
        case "extract-all": this._extractAll(); break
        case "apply-all-suggestions": this._applyAllSuggestions(); break
        case "apply-suggestion": this._applySuggestion(t.getAttribute("data-field")); break
        case "reject-suggestion": this._rejectSuggestion(t.getAttribute("data-field")); break
        case "add-knowledge": this._addKnowledge(); break
        case "edit-knowledge": if (id) this._editKnowledge(id); break
        case "delete-knowledge": if (id) this._deleteKnowledge(id); break
      }
    }
    content.addEventListener("click", this._clickHandler)

    document.getElementById("btn-new-character")?.addEventListener("click", () => this._showCreateForm())
  },

  // ============================================================
  // AI 抽取
  // ============================================================

  async _extractAll() {
    if (!_state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      const result = await api.character.extractAll(_state.currentProjectId)
      const tasks = Array.isArray(result) ? result : []
      toast(`已提交 ${tasks.length} 个人物的抽取任务`, "success")
      // 启动轮询检查任务完成
      this._pollExtractionTasks(tasks.map((t) => t.task_id))
    } catch (err) {
      toast("提交失败: " + (err.message || err), "error")
    }
  },

  async _extractCharacter(charId) {
    if (!_state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      const result = await api.character.extract(charId, _state.currentProjectId)
      toast("抽取任务已提交", "success")
      this._pollExtractionTasks([result.task_id], (tasks) => this._refreshSuggestions(charId, tasks?.[0]?.result))
    } catch (err) {
      toast("提交失败: " + (err.message || err), "error")
    }
  },

  /** 轮询抽取任务完成 */
  _pollExtractionTasks(taskIds, onDone) {
    let attempts = 0
    const maxAttempts = 60
    this._pollTimer = setInterval(async () => {
      attempts++
      const remaining = []
      const taskStates = []
      for (const tid of taskIds) {
        try {
          const data = await api.tasks.getStatus(tid)
          taskStates.push(data)
          if (data.status !== "done" && data.status !== "failed") {
            remaining.push(tid)
          }
        } catch {
          remaining.push(tid)
        }
      }
      if (remaining.length === 0 || attempts >= maxAttempts) {
        clearInterval(this._pollTimer)
        this._pollTimer = null
        if (remaining.length === 0) {
          const failedTask = taskStates.find((task) =>
            task.status === "failed" || task.result?.status === "llm_failed"
          )
          if (failedTask) {
            const message = failedTask.error_message || failedTask.result?.error || "请查看任务详情"
            toast(`人物抽取失败：${message}`, "error")
            return
          }

          await this._refreshCharacterList()
          if (onDone) {
            await onDone(taskStates)
          } else {
            const allNoChunks = taskStates.length > 0 && taskStates.every((task) => task.result?.status === "no_chunks")
            if (allNoChunks) {
              toast("人物抽取完成，但没有找到可提取的相关正文片段", "warning")
            } else {
              toast("人物抽取完成", "success")
            }
          }
        } else {
          toast("人物抽取仍在处理中，请稍后刷新查看结果", "warning")
        }
      }
    }, 5000)
  },

  async _refreshCharacterList() {
    if (!_state.currentProjectId) return
    try {
      const data = await api.character.list({ novel_id: _state.currentProjectId })
      this._characters = data.items || data || []
      if (_state.selectedItem) {
        const selId = _state.selectedItem.id || _state.selectedItem.character_id
        const synced = this._characters.find((c) => (c.id || c.character_id) === selId)
        if (synced) _state.selectedItem = synced
      }
    } catch {
      // 静默处理
    }
  },

  /** 刷新当前角色的 AI 建议 */
  async _refreshSuggestions(charId, taskResult = null) {
    const character = this._characters.find((c) => (c.id || c.character_id) === charId)
    if (!character || !_state.currentProjectId) return { suggestionCount: 0 }
    try {
      for (const warning of (taskResult?.warnings || [])) {
        toast(warning, "warning")
      }
      const data = await api.character.getSuggestions(charId, _state.currentProjectId)
      const suggestions = (data && data.suggestions) || {}
      const suggestionKeys = Object.keys(suggestions)
      if (suggestionKeys.length > 0) {
        // 更新本地缓存
        if (!character.meta) character.meta = {}
        character.meta.ai_suggestions = suggestions
        character.meta.ai_suggestions_at = data.updated_at
        // 如果当前在看的就是这个角色，刷新显示
        if (_state.selectedItem && (_state.selectedItem.id || _state.selectedItem.character_id) === charId) {
          _state.selectedItem = character
          router.navigate("character", "detail", false)
        }
        toast("AI 建议已就绪，可在档案中查看", "info")
        return { suggestionCount: suggestionKeys.length }
      }

      if (taskResult?.status === "no_chunks") {
        toast("人物抽取完成，但没有找到可提取的相关正文片段", "warning")
      } else if (taskResult?.status === "llm_failed") {
        toast(`人物抽取失败：${taskResult.error || "LLM 调用失败"}`, "error")
      } else {
        toast("人物抽取完成，但未提取到新的 AI 建议", "info")
      }
      return { suggestionCount: 0 }
    } catch (err) {
      toast("抽取完成，但刷新 AI 建议失败: " + (err.message || err), "warning")
      return { suggestionCount: 0, error: err }
    }
  },

  _syncAfterApply(character, updated) {
    if (!updated) return
    const charId = character.id || character.character_id
    Object.assign(character, updated)
    if (!character.meta) character.meta = {}
    const remaining = updated.meta?.ai_suggestions
    if (remaining && Object.keys(remaining).length > 0) {
      character.meta.ai_suggestions = remaining
    } else {
      delete character.meta.ai_suggestions
      delete character.meta.ai_suggestions_at
    }
    const idx = this._characters.findIndex((c) => (c.id || c.character_id) === charId)
    if (idx >= 0) {
      this._characters[idx] = { ...this._characters[idx], ...updated }
    }
  },

  async _applyAllSuggestions() {
    const character = _state.selectedItem
    if (!character) return
    const charId = character.id || character.character_id
    const suggestions = (character.meta && character.meta.ai_suggestions) || {}
    const fields = Object.keys(suggestions)
    if (fields.length === 0) {
      toast("没有待应用的 AI 建议", "info")
      return
    }
    try {
      const updated = await api.character.applySuggestions(charId, _state.currentProjectId, fields)
      this._syncAfterApply(character, updated)
      toast(`已应用 ${fields.length} 个字段的 AI 建议`, "success")
      router.navigate("character", "detail", false)
    } catch (err) {
      toast("应用失败: " + (err.message || err), "error")
    }
  },

  async _applySuggestion(field) {
    const character = _state.selectedItem
    if (!character) return
    const charId = character.id || character.character_id
    try {
      const updated = await api.character.applySuggestions(charId, _state.currentProjectId, [field])
      this._syncAfterApply(character, updated)
      toast(`已应用「${field}」建议`, "success")
      router.navigate("character", "detail", false)
    } catch (err) {
      toast("应用失败: " + (err.message || err), "error")
    }
  },

  /** 拒绝单个字段的 AI 建议（从 meta 中移除） */
  async _rejectSuggestion(field) {
    const character = _state.selectedItem
    if (!character) return
    const charId = character.id || character.character_id
    try {
      const data = await api.character.getSuggestions(charId, _state.currentProjectId)
      const remaining = { ...(data.suggestions || {}) }
      delete remaining[field]
      await api.character.update(charId, {
        meta: {
          ...(character.meta || {}),
          ai_suggestions: remaining,
          ...(Object.keys(remaining).length === 0 ? { ai_suggestions_at: null } : {}),
        },
      }, _state.currentProjectId)
      if (character.meta) {
        character.meta.ai_suggestions = remaining
        if (Object.keys(remaining).length === 0) delete character.meta.ai_suggestions_at
      }
      const idx = this._characters.findIndex((c) => (c.id || c.character_id) === charId)
      if (idx >= 0 && character.meta) {
        this._characters[idx].meta = { ...character.meta }
      }
      toast("已忽略该建议", "info")
      router.navigate("character", "detail", false)
    } catch (err) {
      toast("操作失败: " + (err.message || err), "error")
    }
  },

  onLeave() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer)
      this._pollTimer = null
    }
    this._characterKnowledge = []
  },
}

router.registerView("character", characterView)
window.characterView = characterView


export default characterView
