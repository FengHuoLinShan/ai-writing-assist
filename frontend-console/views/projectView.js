/**
 * 项目视图
 */
const projectView = {
  /** @type {Array} 导入记录 */
  _importRecords: [],

  /** @type {boolean} 是否正在上传 */
  _importUploading: false,

  /** @type {boolean} 导入区折叠状态 */
  _importSectionOpen: false,

  async render() {
    const projects = _state.projects
    let html = ''

    if (projects.length === 0) {
      html = `
        <div class="empty-state">
          <div class="empty-icon">&#128214;</div>
          <p>还没有小说项目。</p>
          <p>你可以：</p>
          <div style="display:flex;gap:8px;justify-content:center;margin-top:8px;">
            <button class="btn btn-primary" data-action="new" id="btn-create-project">新建项目</button>
            <button class="btn" onclick="projectView.importFile()">导入小说</button>
          </div>
        </div>
      `
    } else {
      html += `
        <table class="data-table">
          <thead>
            <tr>
              <th>状态</th>
              <th>标题</th>
              <th>题材</th>
              <th>当前阶段</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
      `
      for (const p of projects) {
        const status = p.status || "active"
        const statusClass = status === "active" || status === "canonical" ? "badge-canonical" : "badge-draft"
        html += `
          <tr data-id="${esc(p.id)}" class="clickable" onclick="projectView.openProject('${esc(p.id)}')">
            <td><span class="badge ${statusClass}">${status === "canonical" ? "正史" : "草稿"}</span></td>
            <td>${esc(p.title || p.name || "未命名项目")}</td>
            <td>${esc(p.genre || "-")}</td>
            <td>${esc(p.current_stage || "-")}</td>
            <td>${p.updated_at ? new Date(p.updated_at).toLocaleDateString("zh-CN") : "-"}</td>
            <td>
              <button class="btn btn-sm" onclick="event.stopPropagation();projectView.editProject('${esc(p.id)}')">编辑</button>
              <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();projectView.deleteProject('${esc(p.id)}')" style="margin-left:4px;">删除</button>
            </td>
          </tr>
        `
      }
      html += '</tbody></table>'
      html += `
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary" data-action="new" id="btn-create-project">新建项目</button>
          <button class="btn" id="btn-import-file" onclick="projectView.importFile()">导入小说</button>
          <button class="btn" onclick="projectView._toggleImportSection()">${this._importSectionOpen ? "▾" : "▸"} 导入到当前项目</button>
        </div>
        ${this._importSectionOpen ? this._renderImportSection() : ""}
      `
    }

    // 绑定事件
    setTimeout(() => {
      document.getElementById("btn-create-project")?.addEventListener("click", () => projectView.showCreateForm())
    }, 0)

    return html
  },

  async onEnter() {
    // 加载项目列表
    try {
      const data = await api.projects.list()
      _state.projects = data.items || data || []
      // 自动选中之前保存的项目
      if (_state.currentProjectId) {
        const match = _state.projects.find(p => p.id === _state.currentProjectId)
        if (match) {
          _state.currentProject = match
        } else {
          // 保存的项目已被删除，清除状态
          _state.currentProjectId = null
          _state.currentProject = null
        }
      }
    } catch {
      // 后端不可用时使用空列表
      _state.projects = []
    }
  },

  openProject(id) {
    const project = _state.projects.find((p) => p.id === id)
    if (project) {
      _state.currentProjectId = id
      _state.currentProject = project
      toast(`已切换到项目：${project.title || project.name}`, "success")
      // 切换到世界对象页
      router.navigate("world", "objects")
    }
  },

  editProject(id) {
    const project = _state.projects.find((p) => p.id === id)
    if (!project) return

    const formHtml = `
      <div class="form-group">
        <label>项目名称</label>
        <input class="form-input" id="edit-title" value="${project.title || project.name || ""}" />
      </div>
      <div class="form-group">
        <label>题材</label>
        <input class="form-input" id="edit-genre" value="${project.genre || ""}" />
      </div>
      <div class="form-group">
        <label>创作阶段</label>
        <select class="form-select" id="edit-stage">
          <option value="world_building" ${project.current_stage === "world_building" ? "selected" : ""}>世界构建中</option>
          <option value="outlining" ${project.current_stage === "outlining" ? "selected" : ""}>大纲规划中</option>
          <option value="writing" ${project.current_stage === "writing" ? "selected" : ""}>正文写作中</option>
          <option value="revising" ${project.current_stage === "revising" ? "selected" : ""}>修订中</option>
        </select>
      </div>
    `

    showModal("编辑项目", formHtml, [
      {
        text: "保存",
        class: "btn-primary",
        handler: async () => {
          const title = document.getElementById("edit-title")?.value
          const genre = document.getElementById("edit-genre")?.value
          const stage = document.getElementById("edit-stage")?.value

          try {
            await api.projects.update(id, {
              title: title || project.title,
              genre: genre || project.genre,
              current_stage: stage,
            })
            toast("项目已更新", "success")
            router.navigate("project")
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  /** 删除项目（二次确认） */
  deleteProject(id) {
    const project = _state.projects.find((p) => p.id === id)
    if (!project) return
    const name = project.title || project.name || "未命名"
    confirmAction(`确定要删除项目「${esc(name)}」吗？\n此操作不可恢复，所有关联数据（世界对象、人物、剧情等）将被一并删除。`, async () => {
      try {
        await api.projects.remove(id)
        toast(`项目「${name}」已删除`, "success")
        // 如果删除的是当前项目，清除选中状态
        if (_state.currentProjectId === id) {
          _state.currentProjectId = null
          _state.currentProject = null
        }
        router.navigate("project")
      } catch (err) {
        toast(`删除失败：${err.message}`, "error")
      }
    }, "确认删除")
  },

  showCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>项目名称 *</label>
        <input class="form-input" id="create-title" placeholder="输入小说名称" />
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>题材</label>
          <select class="form-select" id="create-genre">
            <option value="">选择题材</option>
            <option value="fantasy">奇幻</option>
            <option value="scifi">科幻</option>
            <option value="mystery">悬疑</option>
            <option value="romance">言情</option>
            <option value="wuxia">武侠</option>
            <option value="xianxia">仙侠</option>
            <option value="horror">恐怖</option>
            <option value="historical">历史</option>
            <option value="other">其他</option>
          </select>
        </div>
        <div class="form-group">
          <label>语言</label>
          <select class="form-select" id="create-language">
            <option value="zh" selected>中文</option>
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>基调</label>
        <input class="form-input" id="create-tone" placeholder="如：黑暗、幽默、写实" />
      </div>
    `

    showModal("新建项目", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          const title = document.getElementById("create-title")?.value
          if (!title) {
            toast("请输入项目名称", "warning")
            return
          }

          try {
            const project = await api.projects.create({
              title,
              genre: document.getElementById("create-genre")?.value || "",
              tone: document.getElementById("create-tone")?.value || "",
              language: "zh",
            })
            toast(`项目 "${title}" 已创建`, "success")
            _state.currentProjectId = project.id
            _state.currentProject = project
            router.navigate("world", "objects")
          } catch (err) {
            toast(`创建失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  /** 导入小说文件：选文件 → 自动建项目 → 解析入库 */
  importFile() {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".txt,.epub,.html,.htm,.mobi,.azw3"
    input.onchange = async () => {
      if (!input.files || !input.files[0]) return
      const file = input.files[0]

      try {
        // 1. 从文件名生成项目标题
        const projectName = file.name.replace(/\.[^.]+$/, "").trim() || "未命名小说"

        // 2. 创建项目
        const project = await api.projects.create({
          title: projectName,
          genre: "",
          tone: "",
          language: "zh",
        })
        _state.currentProjectId = project.id
        _state.currentProject = project
        // 刷新项目列表
        const data = await api.projects.list()
        _state.projects = data.items || data || []

        // 3. 上传并导入
        const result = await api.imports.upload(project.id, file)
        toast(`项目「${projectName}」已创建，导入 ${result.imported_chapters} 章`, "success")
      } catch (err) {
        toast(err.message || "导入失败", "error")
      }
    }
    input.click()
  },

  // ============================================================
  // 导入区（上传到当前项目）
  // ============================================================

  _toggleImportSection() {
    this._importSectionOpen = !this._importSectionOpen
    router.navigate("project")
  },

  _renderImportSection() {
    const hasProject = !!_state.currentProjectId
    return `
      <div style="border:1px solid var(--border);border-radius:4px;padding:12px;margin-top:12px;">
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">
          将小说文件导入到当前选中的项目。
          ${hasProject ? `当前项目：<strong>${esc(_state.currentProject?.title || "")}</strong>` : '<span style="color:var(--warning);">请先点击项目行选择项目</span>'}
        </div>
        <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
          <div style="flex:1;min-width:200px;">
            <label style="display:block;font-size:11px;color:var(--text-dim);margin-bottom:4px;">选择文件（txt/epub/html/mobi）</label>
            <input type="file" id="pv-import-file" accept=".txt,.epub,.html,.htm,.mobi,.azw3" style="width:100%;color:var(--text);font-size:12px;" ${!hasProject ? "disabled" : ""} />
          </div>
          <button class="btn btn-primary" onclick="projectView._uploadFile()" ${this._importUploading || !hasProject ? "disabled" : ""}>
            ${this._importUploading ? "上传中..." : "上传并导入"}
          </button>
        </div>
        <div id="pv-import-history" style="margin-top:8px;"></div>
      </div>
    `
  },

  async _loadImportRecords() {
    if (!_state.currentProjectId) { this._importRecords = []; return }
    try {
      const data = await api.imports.list({ novel_id: _state.currentProjectId })
      this._importRecords = data.items || []
    } catch { this._importRecords = [] }
  },

  async _renderImportHistory() {
    const container = document.getElementById("pv-import-history")
    if (!container) return
    await this._loadImportRecords()
    if (this._importRecords.length === 0) {
      container.innerHTML = '<p style="color:var(--text-dim);font-size:12px;padding:8px;">暂无导入记录。</p>'
      return
    }
    let html = '<table class="data-table" style="font-size:12px;"><thead><tr><th>文件名</th><th>类型</th><th>章节</th><th>状态</th><th>时间</th></tr></thead><tbody>'
    for (const r of this._importRecords) {
      const statusMap = { done: "完成", processing: "处理中", failed: "失败", pending: "等待" }
      const time = r.created_at ? new Date(r.created_at).toLocaleString("zh-CN") : ""
      html += `<tr>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(r.file_name)}</td>
        <td style="color:var(--accent-dim);">${r.file_type}</td>
        <td>${r.imported_chapters || 0}/${r.total_chapters || 0}</td>
        <td><span class="badge badge-${r.status || "pending"}">${statusMap[r.status] || r.status}</span></td>
        <td style="color:var(--text-dim);font-size:11px;">${time}</td>
      </tr>`
    }
    html += '</tbody></table>'
    container.innerHTML = html
  },

  async _uploadFile() {
    const input = document.getElementById("pv-import-file")
    const btn = document.querySelector('[onclick="projectView._uploadFile()"]')
    if (!input || !input.files || input.files.length === 0) {
      toast("请先选择文件", "warning"); return
    }
    if (!_state.currentProjectId) {
      toast("请先点击项目行选择项目", "warning"); return
    }
    this._importUploading = true
    if (btn) btn.textContent = "上传中..."
    try {
      const result = await api.imports.upload(_state.currentProjectId, input.files[0])
      toast(`导入完成：${result.imported_chapters} 章`, "success")
      input.value = ""
      this._renderImportHistory()
    } catch (err) {
      toast(err.message || "导入失败", "error")
    } finally {
      this._importUploading = false
      if (btn) btn.textContent = "上传并导入"
    }
  },
}

router.registerView("project", projectView)
window.projectView = projectView
