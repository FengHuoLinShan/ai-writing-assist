/**
 * 项目视图
 *
 * ES Module — export default 供测试 import。
 * 生产环境通过 index.html 的 <script type="module"> 加载。
 */

import {
  bulkResultMessage,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  renderBulkToolbar,
  renderSelectionCell,
  runBulkAction,
  selectedItemsFrom,
  syncBulkSelectionUi,
  toggleBulkSelection,
} from "../shared/bulkSelection.js"
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import { renderInlineProgress } from "../shared/progressRenderer.js"

const projectView = {
  /** @type {Array} 导入记录 */
  _importRecords: [],

  /** @type {boolean} 是否正在上传 */
  _importUploading: false,

  /** @type {boolean} 导入区折叠状态 */
  _importSectionOpen: false,

  /** @type {object|null} 项目导入上传进度 */
  _uploadProgress: null,
  _bulkSelections: {},

  async render() {
    const projects = [...state.projects].sort((a, b) => this._projectActivityMs(b) - this._projectActivityMs(a))
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
          <div class="project-header__top">
            <button class="btn btn-ghost btn-sm" data-action="recycle-bin">回收站</button>
          </div>
          <p>选择一个项目继续创作，或创建新项目。</p>
          <div class="divider"></div>
        </div>
        ${this._renderProjectBulkToolbar(projects)}
        <div class="project-grid">
      `

      for (let i = 0; i < projects.length; i++) {
        const p = projects[i]
        const status = p.status || "active"
        const isCanonical = status === "active" || status === "canonical"
        const created = p.created_at ? new Date(p.created_at).toLocaleDateString("zh-CN") : ""
        const stats = this._projectStats(p)
        const activeTime = this._projectActivityTime(p)
        html += `
          <div class="project-card ${i === 0 ? "featured" : ""}" data-id="${esc(p.id)}" data-action="open-project">
            <div class="project-card-selection" data-action="noop">
              ${renderSelectionCell(this, "project-cards", p.id, `选择 ${p.title || p.name || "项目"}`)}
            </div>
            <div class="project-status">
              <span class="status-dot ${isCanonical ? "canonical" : "draft"}"></span>
              <span class="pill ${isCanonical ? "pill-success" : "pill-warning"}">${isCanonical ? "进行中" : "已归档"}</span>
            </div>
            <div class="project-title">${esc(p.title || p.name || "未命名项目")}</div>
            <div class="project-tags">
              ${p.genre ? `<span class="pill">${esc(p.genre)}</span>` : ""}
              ${p.current_stage ? `<span class="pill">${esc(this._stageLabel(p.current_stage))}</span>` : ""}
            </div>
            <div class="project-desc">${esc(p.tone || p.description || "暂无描述")}</div>
            <div class="project-stats" aria-label="项目统计">
              <span title="${esc(stats.wordCountTitle)}"><strong>${esc(stats.wordCountText)}</strong> 字</span>
              <span title="${esc(stats.chapterCountTitle)}"><strong>${esc(stats.chapterCountText)}</strong> 章</span>
              <span title="${esc(activeTime.full)}">${esc(activeTime.relative)}</span>
            </div>
            <div class="project-meta">
              ${created ? `创建于 ${created}` : "刚刚创建"}
            </div>
            <div class="project-card__actions">
              <button class="btn btn-sm btn-primary" data-action="continue-writing" data-id="${esc(p.id)}">继续写作</button>
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
        <div class="project-import-section">
          <button class="btn btn-ghost btn-sm" data-action="toggle-import">
            ${this._importSectionOpen ? "收起导入" : "导入小说到当前项目"}
          </button>
          ${this._importSectionOpen ? this._renderImportSection() : ""}
        </div>
        <div class="import-list">
          <div class="import-list-header">导入记录</div>
          <div id="import-list-body">
            <p class="project-import-list__status">加载中...</p>
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

  _renderProjectBulkToolbar(projects) {
    const ids = projects.map((project) => project.id).filter(Boolean)
    reconcileBulkSelection(this, "project-cards", ids)
    return `
      <div class="row-actions project-bulk-toolbar__select">
        <button class="btn btn-sm" data-action="select-visible-projects" ${ids.length === 0 ? "disabled" : ""}>全选当前项目</button>
      </div>
    ` + renderBulkToolbar(this, "project-cards", [
      { action: "delete-projects", label: "批量移入回收站", className: "btn-danger" },
    ], { noun: "项目", hint: "只处理当前可见项目" })
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

  _projectStats(project) {
    const stats = project.stats || project.statistics || {}
    const wordCount = project.total_words
      ?? project.word_count
      ?? project.total_word_count
      ?? stats.total_words
      ?? stats.word_count
      ?? null
    const chapterCount = project.chapter_count
      ?? project.total_chapters
      ?? stats.chapter_count
      ?? stats.total_chapters
      ?? null
    return {
      wordCount: Number(wordCount) || 0,
      chapterCount: Number(chapterCount) || 0,
      wordCountText: wordCount === null || wordCount === undefined ? "待接入" : this._formatNumber(wordCount),
      chapterCountText: chapterCount === null || chapterCount === undefined ? "待接入" : this._formatNumber(chapterCount),
      wordCountTitle: wordCount === null || wordCount === undefined ? "统计接入后显示总字数" : "总字数",
      chapterCountTitle: chapterCount === null || chapterCount === undefined ? "统计接入后显示章节数" : "章节数",
    }
  },

  _formatNumber(value) {
    return (Number(value) || 0).toLocaleString("zh-CN")
  },

  _projectActivityTime(project) {
    const raw = project.last_active_at || project.updated_at || project.created_at
    if (!raw) return { relative: "暂无活跃", full: "暂无活跃时间" }
    const date = new Date(raw)
    if (Number.isNaN(date.getTime())) return { relative: "暂无活跃", full: String(raw) }
    return {
      relative: this._formatRelativeTime(date),
      full: date.toLocaleString("zh-CN"),
    }
  },

  _projectActivityMs(project) {
    const raw = project.last_active_at || project.updated_at || project.created_at
    if (!raw) return 0
    const time = new Date(raw).getTime()
    return Number.isNaN(time) ? 0 : time
  },

  _formatRelativeTime(value) {
    const date = value instanceof Date ? value : new Date(value)
    if (Number.isNaN(date.getTime())) return "暂无活跃"
    const diffMs = Date.now() - date.getTime()
    if (diffMs < 0) return "刚刚活跃"
    const minute = 60 * 1000
    const hour = 60 * minute
    const day = 24 * hour
    if (diffMs < minute) return "刚刚活跃"
    if (diffMs < hour) return `${Math.floor(diffMs / minute)} 分钟前活跃`
    if (diffMs < day) return `${Math.floor(diffMs / hour)} 小时前活跃`
    if (diffMs < 7 * day) return `${Math.floor(diffMs / day)} 天前活跃`
    return date.toLocaleDateString("zh-CN")
  },

  _bindEvents() {
    document.getElementById("btn-create-project")?.addEventListener("click", (e) => {
      e.stopPropagation()
      this.showCreateForm()
    })
    this._bindCardDelegation()
    this._bindImportButtons()
  },

  _bindCardDelegation() {
    bindWorkspaceClick(this, {
      "open-project": (_e, _t, ctx) => ctx.id && this.openProject(ctx.id),
      "noop": (e) => e.stopPropagation(),
      "bulk-toggle-one": (e, t) => {
        e.stopPropagation()
        toggleBulkSelection(this, t.getAttribute("data-scope"), t.getAttribute("data-id"), t.checked)
        syncBulkSelectionUi(this, t.getAttribute("data-scope"))
      },
      "bulk-clear": (_e, t) => {
        const scope = t.getAttribute("data-scope")
        clearBulkSelection(this, scope)
        syncBulkSelectionUi(this, scope)
      },
      "bulk-run": (_e, t) => this._runProjectBulkAction(t.getAttribute("data-bulk-action")),
      "select-visible-projects": () => {
        for (const project of state.projects) toggleBulkSelection(this, "project-cards", project.id, true)
        syncBulkSelectionUi(this, "project-cards")
      },
      "continue-writing": (_e, _t, ctx) => ctx.id && this.openProject(ctx.id),
      "edit-project": (_e, _t, ctx) => ctx.id && this.editProject(ctx.id),
      "delete-project": (_e, _t, ctx) => ctx.id && this.deleteProject(ctx.id),
      "new": () => this.showCreateForm(),
      "import": () => this.importFile(),
      "toggle-import": () => this._toggleImportSection(),
      "upload-file": () => this._uploadFile(),
      "recycle-bin": () => this.showRecycleBin(),
    })
  },

  _runProjectBulkAction(action) {
    if (action !== "delete-projects") return
    const items = selectedItemsFrom(state.projects, getBulkSelection(this, "project-cards"))
    if (!items.length) {
      toast("请先选择项目", "warning")
      return
    }
    return confirmAction(`确定将选中的 ${items.length} 个项目移入回收站吗？`, async () => {
      const result = await runBulkAction(items, async (project) => {
        await api.projects.remove(project.id)
      })
      toast(bulkResultMessage(result, "批量移入回收站", (item) => item.title || item.name || item.id), result.failed.length ? "warning" : "success")
      clearBulkSelection(this, "project-cards")
      await this.onEnter()
      router.refresh()
    }, "移入回收站")
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
          this._clearCurrentProjectSelection()
        }
      }
    } catch {
      state.projects = []
    }
  },

  _clearCurrentProjectSelection() {
    state.currentProjectId = null
    state.currentProject = null
    delete state.viewStates.writing
    try {
      localStorage.removeItem("novel_currentProjectId")
      localStorage.removeItem("novel_currentProject")
    } catch {}
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

    showModalHtml("编辑项目", formHtml, [
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
            this._clearCurrentProjectSelection()
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
        showModalHtml("回收站", "<p>回收站为空。</p>")
        return
      }
      let listHtml = `
        <div class="bulk-toolbar">
          <div class="bulk-toolbar__status"><span>回收站项目</span></div>
          <div class="bulk-toolbar__actions">
            <button class="btn btn-sm" id="recycle-select-all">全选当前列表</button>
            <button class="btn btn-sm btn-primary" id="recycle-bulk-restore">批量恢复</button>
            <button class="btn btn-sm btn-danger" id="recycle-bulk-delete">批量永久删除</button>
          </div>
        </div>
        <div class="recycle-bin__list">
      `
      for (const p of items) {
        const name = p.title || p.name || "未命名"
        const deletedDate = p.deleted_at
          ? new Date(p.deleted_at).toLocaleDateString("zh-CN")
          : ""
        listHtml += `
          <div class="recycle-bin__item">
            <label class="selection-checkbox" title="选择 ${esc(name)}">
              <input type="checkbox" class="recycle-project-checkbox" data-id="${esc(p.id)}" />
              <span class="sr-only">选择 ${esc(name)}</span>
            </label>
            <div class="recycle-bin__item-info">
              <div class="recycle-bin__item-name">${esc(name)}</div>
              <div class="recycle-bin__item-date">删除于 ${deletedDate}</div>
            </div>
            <div class="recycle-bin__item-actions">
              <button class="btn btn-sm btn-primary restore-project-btn" data-id="${esc(p.id)}">恢复</button>
              <button class="btn btn-sm btn-danger perm-delete-project-btn" data-id="${esc(p.id)}">永久删除</button>
            </div>
          </div>
        `
      }
      listHtml += "</div>"
      showModalHtml("回收站", listHtml)

      setTimeout(() => {
        const selectedRecycleProjects = () => {
          const ids = new Set(Array.from(document.querySelectorAll(".recycle-project-checkbox:checked")).map((input) => input.dataset.id))
          return items.filter((item) => ids.has(item.id))
        }
        document.getElementById("recycle-select-all")?.addEventListener("click", () => {
          document.querySelectorAll(".recycle-project-checkbox").forEach((input) => { input.checked = true })
        })
        document.getElementById("recycle-bulk-restore")?.addEventListener("click", async () => {
          const selected = selectedRecycleProjects()
          if (!selected.length) { toast("请先选择项目", "warning"); return }
          try {
            const result = await runBulkAction(selected, async (project) => api.projects.restore(project.id))
            if (result.failed.length && result.success.length === 0) {
              toast(`批量恢复失败：${result.failed[0]?.error?.message || "未知错误"}`, "error")
            } else {
              toast(bulkResultMessage(result, "批量恢复项目", (item) => item.title || item.name || item.id), result.failed.length ? "warning" : "success")
            }
            router.refresh()
            this.showRecycleBin()
          } catch (err) {
            toast(`批量恢复失败：${err.message || "未知错误"}`, "error")
          }
        })
        document.getElementById("recycle-bulk-delete")?.addEventListener("click", () => {
          const selected = selectedRecycleProjects()
          if (!selected.length) { toast("请先选择项目", "warning"); return }
          confirmAction(`确定永久删除选中的 ${selected.length} 个项目？此操作不可恢复。`, async () => {
            try {
              const result = await runBulkAction(selected, async (project) => api.projects.permanentDelete(project.id))
              if (result.failed.length && result.success.length === 0) {
                toast(`批量永久删除失败：${result.failed[0]?.error?.message || "未知错误"}`, "error")
              } else {
                toast(bulkResultMessage(result, "批量永久删除项目", (item) => item.title || item.name || item.id), result.failed.length ? "warning" : "success")
              }
              if (!result.failed.length) this.showRecycleBin()
              return result.failed.length ? false : true
            } catch (err) {
              toast(`批量永久删除失败：${err.message || "未知错误"}`, "error")
              return false
            }
          }, "永久删除")
        })
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
                  return true
                } catch (err) {
                  toast(`永久删除失败：${err.message || "未知错误"}`, "error")
                  return false
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

    showModalHtml("新建项目", formHtml, [
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
        toast(`项目「${projectName}」已创建，共解析 ${result.total_chapters || 0} 章，已保存 ${result.imported_chapters || 0} 章为章节工作稿`, "success")
        api.clearCache()
        await router.navigate("writing")
        await router.refresh()
        if (result.imported_chapters > 0) {
          confirmAction(
            `已导入 ${result.imported_chapters} 章，是否启动深度导入第一阶段（scene）？`,
            async () => {
              await writingView._submitDeepImport(1, result.imported_chapters)
            },
            "启动深度导入第一阶段（scene）",
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
      <div class="project-import-panel">
        <div class="project-import-panel__hint">
          将小说文件导入到当前选中的项目。
          ${hasProject ? `当前项目：<strong>${esc(state.currentProject?.title || "")}</strong>` : '<span class="project-import-panel__hint-warning">请先点击项目行选择项目</span>'}
        </div>
        <div class="project-import-panel__form">
          <div class="project-import-panel__field">
            <label class="project-import-panel__label">选择文件（txt/epub/html/mobi）</label>
            <input type="file" id="pv-import-file" class="project-import-panel__input" accept=".txt,.epub,.html,.htm,.mobi,.azw3" ${!hasProject ? "disabled" : ""} />
          </div>
          <button class="btn btn-primary" data-action="upload-file" ${this._importUploading || !hasProject ? "disabled" : ""}>
            ${this._importUploading ? "上传中..." : "上传并导入"}
          </button>
        </div>
        <div id="pv-upload-progress" class="project-import-panel__progress">${this._renderUploadProgress()}</div>
        <div id="pv-import-history" class="project-import-panel__history"></div>
      </div>
    `
  },

  _renderUploadProgress() {
    if (!this._uploadProgress) return ""
    const stage = this._uploadProgress.stage || "上传文件"
    const percent = Math.max(0, Math.min(100, Math.round(this._uploadProgress.percent || 0)))
    return renderInlineProgress({
      label: "导入小说",
      message: this._uploadProgress.message || stage,
      status: "running",
      statusLabel: stage,
      percent,
      hasPercent: true,
      indeterminate: false,
      warnings: [],
    }, {
      showTaskId: false,
    })
  },

  _setUploadProgress(stage, percent, message) {
    this._uploadProgress = { stage, percent, message }
    const container = document.getElementById("pv-upload-progress")
    if (container) container.innerHTML = this._renderUploadProgress()
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
      container.innerHTML = '<p class="project-import-list__empty">暂无导入记录。</p>'
      return
    }
    let html = ''
    for (const r of this._importRecords) {
      const statusMap = { done: "完成", processing: "处理中", failed: "失败", pending: "等待" }
      const statusClass = { done: "pill-success", processing: "pill-warning", failed: "pill-error", pending: "" }
      const time = r.created_at ? new Date(r.created_at).toLocaleString("zh-CN") : ""
      html += `<div class="import-list-item">
        <span class="status-dot ${r.status === "done" ? "success" : r.status === "failed" ? "error" : r.status === "processing" ? "warning" : "info"}"></span>
        <span class="project-import-list__item-name">${esc(r.file_name)}</span>
        <span class="pill ${statusClass[r.status] || ""}">${esc(statusMap[r.status] || r.status || "")}</span>
        <span class="project-import-list__item-chapters">成功 ${r.imported_chapters || 0} / 共 ${r.total_chapters || 0} 章</span>
        <span class="project-import-list__item-time">${time}</span>
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
    this._uploadProgress = null
    if (btn) {
      btn.disabled = true
      btn.textContent = "上传中 0%"
    }
    this._setUploadProgress("上传文件", 0, "正在上传文件...")

    try {
      const result = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        const formData = new FormData()
        formData.append("file", file)
        formData.append("novel_id", state.currentProjectId)

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100)
            if (btn) btn.textContent = `上传中 ${percent}%`
            this._setUploadProgress("上传文件", percent, `正在上传文件 ${percent}%`)
            if (percent >= 100) {
              this._setUploadProgress("解析章节", 100, "文件已上传，正在解析章节...")
            }
          }
        }

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            this._setUploadProgress("解析章节", 100, "章节解析完成")
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
        xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest")
        const accessToken = typeof sessionStorage !== "undefined"
          ? sessionStorage.getItem("novel_app_access_token")
          : null
        if (accessToken) {
          xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`)
        }
        xhr.send(formData)
      })

      toast(`导入完成：共解析 ${result.total_chapters || 0} 章，已保存 ${result.imported_chapters || 0} 章为章节工作稿`, "success")
      api.clearCache()
      this._setUploadProgress("刷新项目", 100, "正在刷新项目...")
      await router.navigate("writing")
      await router.refresh()
      input.value = ""
      this._renderImportHistory()
      if (result.imported_chapters > 0) {
        confirmAction(
          `已导入 ${result.imported_chapters} 章，是否启动深度导入第一阶段（scene）？`,
          async () => {
            await writingView._submitDeepImport(1, result.imported_chapters)
          },
          "启动深度导入第一阶段（scene）",
        )
      }
    } catch (err) {
      toast(err.message || "导入失败", "error")
      api.clearCache()
      await this._renderImportHistory()
    } finally {
      this._importUploading = false
      this._uploadProgress = null
      if (btn) {
        btn.textContent = "上传并导入"
        btn.disabled = !state.currentProjectId
      }
      const progressBar = document.getElementById("pv-upload-progress")
      if (progressBar) progressBar.innerHTML = ""
    }
  },
}

router.registerView("project", projectView)
window.projectView = projectView
export default projectView
