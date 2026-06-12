/**
 * 项目视图
 *
 * ES Module — export default 供测试 import。
 * 生产环境通过 index.html 的 <script type="module"> 加载。
 */

import { bindWorkspaceClick } from "../shared/viewHelper.js"

const projectView = {
  /** @type {Array} 导入记录 */
  _importRecords: [],

  /** @type {boolean} 是否正在上传 */
  _importUploading: false,

  /** @type {boolean} 导入区折叠状态 */
  _importSectionOpen: false,

  async render() {
    const projects = state.projects
    let html = ''

    if (projects.length === 0) {
      html = `
        <div class="empty-state">
          <div class="empty-icon">&#128214;</div>
          <h2>开始你的第一部小说</h2>
          <p>创建项目，导入正文，让 AI 协助你构建世界观与剧情。</p>
          <div class="actions">
            <button class="btn btn-primary" data-action="new" id="btn-create-project">新建项目</button>
            <button class="btn btn-ghost" data-action="import">导入小说</button>
          </div>
        </div>
      `
    } else {
      html += `
        <div class="project-header">
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <button class="btn btn-ghost btn-sm" data-action="recycle-bin" style="font-size:12px;">回收站</button>
          </div>
          <p>选择一个项目继续创作，或创建新项目。</p>
          <div class="divider"></div>
        </div>
        <div class="project-grid">
      `

      for (let i = 0; i < projects.length; i++) {
        const p = projects[i]
        const status = p.status || "active"
        const isCanonical = status === "active" || status === "canonical"
        const created = p.created_at ? new Date(p.created_at).toLocaleDateString("zh-CN") : ""
        html += `
          <div class="project-card ${i === 0 ? "featured" : ""}" data-id="${esc(p.id)}" data-action="open-project">
            <div class="project-status">
              <span class="status-dot ${isCanonical ? "canonical" : "draft"}"></span>
              <span class="pill ${isCanonical ? "pill-success" : "pill-warning"}">${status === "canonical" ? "正史" : "草稿"}</span>
            </div>
            <div class="project-title">${esc(p.title || p.name || "未命名项目")}</div>
            <div class="project-tags">
              ${p.genre ? `<span class="pill">${esc(p.genre)}</span>` : ""}
              ${p.current_stage ? `<span class="pill">${esc(this._stageLabel(p.current_stage))}</span>` : ""}
            </div>
            <div class="project-desc">${esc(p.tone || p.description || "暂无描述")}</div>
            <div class="project-meta">
              ${created ? `创建于 ${created}` : "刚刚创建"}
            </div>
            <div class="project-actions" style="margin-top:12px;display:flex;gap:8px;opacity:0;transition:opacity .15s;">
              <button class="btn btn-sm btn-ghost" data-action="edit-project" data-id="${esc(p.id)}">编辑</button>
              <button class="btn btn-sm btn-danger" data-action="delete-project" data-id="${esc(p.id)}">删除</button>
            </div>
          </div>
        `
      }

      html += `
          <div class="project-card project-card-placeholder" data-action="new" id="btn-create-project">
            <div class="plus">+</div>
            <div class="label">创建新项目</div>
          </div>
        </div>
      `

      html += `
        <div style="margin-top:16px;">
          <button class="btn btn-ghost btn-sm" data-action="toggle-import">
            ${this._importSectionOpen ? "收起导入" : "导入小说到当前项目"}
          </button>
          ${this._importSectionOpen ? this._renderImportSection() : ""}
        </div>
        <div class="import-list">
          <div class="import-list-header">导入记录</div>
          <div id="import-list-body">
            <p style="color:var(--text-tertiary);font-size:13px;">加载中...</p>
          </div>
        </div>
      `
    }

    setTimeout(() => this._bindEvents(), 0)
    if (state.projects.length > 0) {
      setTimeout(() => this._renderImportHistory(), 0)
    }

    return html
  },

  _stageLabel(stage) {
    const map = {
      world_building: "世界构建",
      outlining: "大纲规划",
      writing: "正文写作",
      revising: "修订中",
    }
    return map[stage] || stage
  },

  _bindEvents() {
    document.getElementById("btn-create-project")?.addEventListener("click", (e) => {
      e.stopPropagation()
      this.showCreateForm()
    })
    this._bindCardDelegation()
    this._bindImportButtons()

    // 卡片 hover 时显示操作按钮
    document.querySelectorAll(".project-card[data-id]").forEach((card) => {
      card.addEventListener("mouseenter", () => {
        const actions = card.querySelector(".project-actions")
        if (actions) actions.style.opacity = "1"
      })
      card.addEventListener("mouseleave", () => {
        const actions = card.querySelector(".project-actions")
        if (actions) actions.style.opacity = "0"
      })
    })
  },

  _bindCardDelegation() {
    bindWorkspaceClick(this, {
      "open-project": (_e, _t, ctx) => ctx.id && this.openProject(ctx.id),
      "edit-project": (_e, _t, ctx) => ctx.id && this.editProject(ctx.id),
      "delete-project": (_e, _t, ctx) => ctx.id && this.deleteProject(ctx.id),
      "new": () => this.showCreateForm(),
      "import": () => this.importFile(),
      "toggle-import": () => this._toggleImportSection(),
      "upload-file": () => this._uploadFile(),
      "recycle-bin": () => this.showRecycleBin(),
    })
  },

  _bindImportButtons() {
    document.getElementById("btn-import-file")?.addEventListener("click", () => this.importFile())
  },

  async onEnter() {
    try {
      const data = await api.projects.list()
      state.projects = data.items || data || []
      if (state.currentProjectId) {
        const match = state.projects.find(p => p.id === state.currentProjectId)
        if (match) {
          state.currentProject = match
        } else {
          state.currentProjectId = null
          state.currentProject = null
        }
      }
    } catch {
      state.projects = []
    }
  },

  openProject(id) {
    const project = state.projects.find((p) => p.id === id)
    if (project) {
      state.currentProjectId = id
      state.currentProject = project
      toast(`已切换到项目：${project.title || project.name}`, "success")
      router.navigate("writing")
    }
  },

  editProject(id) {
    const project = state.projects.find((p) => p.id === id)
    if (!project) return

    const formHtml = `
      <div class="form-group">
        <label>项目标题</label>
        <input class="form-input" id="edit-title" value="${esc(project.title || project.name || "")}" />
      </div>
      <div class="form-group">
        <label>题材</label>
        <input class="form-input" id="edit-genre" value="${esc(project.genre || "")}" />
      </div>
      <div class="form-group">
        <label>风格基调</label>
        <input class="form-input" id="edit-tone" value="${esc(project.tone || "")}" placeholder="如：黑暗、幽默、写实" />
      </div>
      <div class="form-group">
        <label>目标规模</label>
        <select class="form-select" id="edit-target-length">
          <option value="">未设置</option>
          <option value="short" ${project.target_length === "short" ? "selected" : ""}>短篇</option>
          <option value="medium" ${project.target_length === "medium" ? "selected" : ""}>中篇</option>
          <option value="novel" ${project.target_length === "novel" ? "selected" : ""}>长篇</option>
          <option value="epic" ${project.target_length === "epic" ? "selected" : ""}>史诗</option>
        </select>
      </div>
      <div class="form-group">
        <label>创作阶段</label>
        <select class="form-select" id="edit-stage">
          <option value="">未设置</option>
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
          const tone = document.getElementById("edit-tone")?.value
          const targetLength = document.getElementById("edit-target-length")?.value
          const stage = document.getElementById("edit-stage")?.value

          if (!title) {
            toast("请输入项目标题", "warning")
            return
          }

          const payload = {
            title,
            genre: genre || null,
            tone: tone || null,
            target_length: targetLength || null,
            current_stage: stage || null,
          }

          try {
            const updated = await api.projects.update(id, payload)
            const idx = state.projects.findIndex((p) => p.id === id)
            if (idx >= 0) {
              state.projects[idx] = { ...state.projects[idx], ...updated }
            }
            if (state.currentProjectId === id) {
              state.currentProject = { ...state.currentProject, ...updated }
            }
            toast("项目已更新", "success")
            closeModal()
          } catch (err) {
            toast(`保存失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  deleteProject(id) {
    const project = state.projects.find((p) => p.id === id)
    if (!project) return
    const name = project.title || project.name || "未命名"
    confirmAction(
      `确定要删除项目「${esc(name)}」吗？删除后可在回收站中恢复。`,
      async () => {
        try {
          await api.projects.remove(id)
          toast(`项目「${name}」已移至回收站`, "success")
          if (state.currentProjectId === id) {
            state.currentProjectId = null
            state.currentProject = null
          }
          router.refresh()
        } catch (err) {
          toast(`删除失败：${err.message}`, "error")
        }
      },
      "移至回收站",
    )
  },

  async showRecycleBin() {
    try {
      const data = await api.projects.listDeleted()
      const items = data.items || data || []
      if (items.length === 0) {
        showModal("回收站", "<p>回收站为空。</p>")
        return
      }
      let listHtml = '<div style="max-height:400px;overflow-y:auto;">'
      for (const p of items) {
        const name = p.title || p.name || "未命名"
        const deletedDate = p.deleted_at
          ? new Date(p.deleted_at).toLocaleDateString("zh-CN")
          : ""
        listHtml += `
          <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-dim);">
            <div>
              <div style="font-weight:500;">${esc(name)}</div>
              <div style="font-size:11px;color:var(--text-dim);">删除于 ${deletedDate}</div>
            </div>
            <div style="display:flex;gap:6px;">
              <button class="btn btn-sm btn-primary restore-project-btn" data-id="${esc(p.id)}">恢复</button>
              <button class="btn btn-sm btn-danger perm-delete-project-btn" data-id="${esc(p.id)}">永久删除</button>
            </div>
          </div>
        `
      }
      listHtml += "</div>"
      showModal("回收站", listHtml)

      setTimeout(() => {
        document.querySelectorAll(".restore-project-btn").forEach((btn) => {
          btn.onclick = async () => {
            try {
              await api.projects.restore(btn.dataset.id)
              toast("项目已恢复", "success")
              router.refresh()
              this.showRecycleBin()
            } catch (err) {
              toast(`恢复失败：${err.message}`, "error")
            }
          }
        })
        document.querySelectorAll(".perm-delete-project-btn").forEach((btn) => {
          btn.onclick = () => {
            const pid = btn.dataset.id
            confirmAction(
              "确定永久删除此项目？此操作不可恢复，所有关联数据将被级联删除。",
              async () => {
                try {
                  await api.projects.permanentDelete(pid)
                  toast("项目已永久删除", "success")
                  this.showRecycleBin()
                } catch (err) {
                  toast(`删除失败：${err.message}`, "error")
                }
              },
              "永久删除",
            )
          }
        })
      }, 100)
    } catch (err) {
      toast(`加载回收站失败：${err.message}`, "error")
    }
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
            toast("请输入项目标题", "warning")
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
            state.currentProjectId = project.id
            state.currentProject = project
            router.navigate("writing")
          } catch (err) {
            toast(`创建失败：${err.message}`, "error")
          }
        },
      },
    ])
  },

  importFile() {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".txt,.epub,.html,.htm,.mobi,.azw3"
    input.onchange = async () => {
      if (!input.files || !input.files[0]) return
      const file = input.files[0]

      try {
        const projectName = file.name.replace(/\.[^.]+$/, "").trim() || "未命名小说"
        const project = await api.projects.create({
          title: projectName,
          genre: "",
          tone: "",
          language: "zh",
        })
        state.currentProjectId = project.id
        state.currentProject = project
        const data = await api.projects.list()
        state.projects = data.items || data || []

        const result = await api.imports.upload(project.id, file)
        toast(`项目「${projectName}」已创建，导入 ${result.imported_chapters} 章`, "success")
        api.clearCache()
        await router.navigate("writing")
        await router.refresh()
        if (result.imported_chapters > 0) {
          confirmAction(
            `已导入 ${result.imported_chapters} 章，是否启动深度导入？`,
            async () => {
              await writingView._submitDeepImport(1, result.imported_chapters)
            },
            "启动深度导入",
          )
        }
      } catch (err) {
        const detail = err.message || "导入失败"
        toast(detail.includes("格式") || detail.includes("大小") || detail.includes("限制") ? detail : `导入失败：${detail}`, "error")
      }
    }
    input.click()
  },

  _toggleImportSection() {
    this._importSectionOpen = !this._importSectionOpen
    router.navigate("project")
  },

  _renderImportSection() {
    const hasProject = !!state.currentProjectId
    return `
      <div style="border:1px solid var(--text-quaternary);border-radius:8px;padding:16px;margin-top:16px;background:var(--bg-panel);">
        <div style="font-size:13px;color:var(--text-secondary);margin-bottom:12px;">
          将小说文件导入到当前选中的项目。
          ${hasProject ? `当前项目：<strong>${esc(state.currentProject?.title || "")}</strong>` : '<span style="color:var(--warning);">请先点击项目行选择项目</span>'}
        </div>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;">
          <div style="flex:1;min-width:200px;">
            <label style="display:block;font-size:12px;color:var(--text-secondary);margin-bottom:6px;">选择文件（txt/epub/html/mobi）</label>
            <input type="file" id="pv-import-file" accept=".txt,.epub,.html,.htm,.mobi,.azw3" style="width:100%;color:var(--text-body);font-size:13px;" ${!hasProject ? "disabled" : ""} />
          </div>
          <button class="btn btn-primary" data-action="upload-file" ${this._importUploading || !hasProject ? "disabled" : ""}>
            ${this._importUploading ? "上传中..." : "上传并导入"}
          </button>
          <div id="pv-upload-progress" style="display:none;margin-top:8px;height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
            <div id="pv-upload-bar-fill" style="height:100%;width:0%;background:var(--accent);transition:width 0.2s;border-radius:3px;"></div>
          </div>
        </div>
        <div id="pv-import-history" style="margin-top:12px;"></div>
      </div>
    `
  },

  async _loadImportRecords() {
    if (!state.currentProjectId) { this._importRecords = []; return }
    try {
      const data = await api.imports.list({ novel_id: state.currentProjectId })
      this._importRecords = data.items || []
    } catch { this._importRecords = [] }
  },

  async _renderImportHistory() {
    const container = document.getElementById("import-list-body")
    if (!container) return
    await this._loadImportRecords()
    if (this._importRecords.length === 0) {
      container.innerHTML = '<p style="color:var(--text-tertiary);font-size:13px;padding:8px 0;">暂无导入记录。</p>'
      return
    }
    let html = ''
    for (const r of this._importRecords) {
      const statusMap = { done: "完成", processing: "处理中", failed: "失败", pending: "等待" }
      const statusClass = { done: "pill-success", processing: "pill-warning", failed: "pill-error", pending: "" }
      const time = r.created_at ? new Date(r.created_at).toLocaleString("zh-CN") : ""
      html += `<div class="import-list-item">
        <span class="status-dot ${r.status === "done" ? "success" : r.status === "failed" ? "error" : r.status === "processing" ? "warning" : "info"}"></span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-body);">${esc(r.file_name)}</span>
        <span class="pill ${statusClass[r.status] || ""}">${statusMap[r.status] || r.status}</span>
        <span style="color:var(--text-secondary);font-size:12px;">${r.imported_chapters || 0}/${r.total_chapters || 0} 章</span>
        <span style="color:var(--text-tertiary);font-size:12px;font-family:var(--font-mono);">${time}</span>
      </div>`
    }
    container.innerHTML = html
  },

  async _uploadFile() {
    const input = document.getElementById("pv-import-file")
    const btn = document.querySelector("[data-action='upload-file']")
    if (!input || !input.files || input.files.length === 0) {
      toast("请先选择文件", "warning"); return
    }
    if (!state.currentProjectId) {
      toast("请先点击项目行选择项目", "warning"); return
    }
    const file = input.files[0]
    const MAX_FILE_SIZE = 50 * 1024 * 1024
    if (file.size > MAX_FILE_SIZE) {
      toast("文件大小超过限制（最大 50MB）", "error"); return
    }
    this._importUploading = true
    this._uploadProgress = 0
    if (btn) btn.textContent = "上传中 0%"

    // Show progress bar
    const progressBar = document.getElementById("pv-upload-progress")
    if (progressBar) progressBar.style.display = "block"

    try {
      const result = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        const formData = new FormData()
        formData.append("file", file)
        formData.append("novel_id", state.currentProjectId)

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            this._uploadProgress = Math.round((e.loaded / e.total) * 100)
            if (btn) btn.textContent = `上传中 ${this._uploadProgress}%`
            const fill = document.getElementById("pv-upload-bar-fill")
            if (fill) fill.style.width = this._uploadProgress + "%"
          }
        }

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText))
          } else {
            try {
              const err = JSON.parse(xhr.responseText)
              reject(new Error(err.detail || "上传失败"))
            } catch { reject(new Error("上传失败")) }
          }
        }
        xhr.onerror = () => reject(new Error("网络错误"))
        xhr.open("POST", (typeof API_HOST !== "undefined" ? API_HOST : "http://localhost:8000") + "/api/imports/upload")
        xhr.send(formData)
      })

      toast(`导入完成：${result.imported_chapters} 章`, "success")
      api.clearCache()
      await router.navigate("writing")
      await router.refresh()
      input.value = ""
      this._renderImportHistory()
      if (result.imported_chapters > 0) {
        confirmAction(
          `已导入 ${result.imported_chapters} 章，是否启动深度导入？`,
          async () => {
            await writingView._submitDeepImport(1, result.imported_chapters)
          },
          "启动深度导入",
        )
      }
    } catch (err) {
      toast(err.message || "导入失败", "error")
      api.clearCache()
      await this._renderImportHistory()
    } finally {
      this._importUploading = false
      this._uploadProgress = null
      if (btn) btn.textContent = "上传并导入"
      const progressBar = document.getElementById("pv-upload-progress")
      if (progressBar) progressBar.style.display = "none"
    }
  },
}

router.registerView("project", projectView)
window.projectView = projectView
export default projectView
