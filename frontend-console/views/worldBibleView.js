/**
 * World Bible / Worldbuilding Workspace v1.
 */
import { pollTaskProgress } from "../shared/workflowProgress.js"

const PROJECTION_TYPE = "context_brief"

const worldBibleView = {
  _pages: [],
  _activePage: null,
  _suggestions: [],
  _conflicts: [],
  _task: null,
  _projectionPoller: null,
  _beforeUnloadBound: false,

  async render() {
    if (!state.currentProjectId) {
      return `<div class="empty-state"><p>请先选择项目</p></div>`
    }
    await this._load()
    return `
      <section class="world-bible-workspace">
        <div class="world-bible-layout" style="display:grid;grid-template-columns:minmax(180px,240px) minmax(0,1fr);gap:14px;">
          <aside class="panel" style="padding:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;">
              <h3 style="margin:0;font-size:16px;">World Bible</h3>
              <button class="btn btn-sm" data-action="bible-new-page">+</button>
            </div>
            ${this._renderPageNav()}
            <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;">
              <button class="btn btn-sm" data-action="bible-open-suggestions">创设建议</button>
              <button class="btn btn-sm" data-action="bible-open-conflicts">冲突检查</button>
            </div>
          </aside>
          <main class="panel" style="padding:14px;min-width:0;">
            ${this._renderActivePage()}
          </main>
        </div>
      </section>
    `
  },

  bindEvents() {
    if (!this._beforeUnloadBound) {
      window.addEventListener("beforeunload", () => this.onLeave())
      this._beforeUnloadBound = true
    }
    document.querySelectorAll("[data-bible-page-id]").forEach((node) => {
      node.addEventListener("click", () => {
        this._activePage = this._pages.find((page) => page.id === node.getAttribute("data-bible-page-id")) || null
        router.refresh()
      })
    })
    document.querySelector("[data-action='bible-new-page']")?.addEventListener("click", () => this._createPage())
    document.querySelector("[data-action='bible-save-page']")?.addEventListener("click", () => this._savePage())
    document.querySelector("[data-action='bible-refresh-projection']")?.addEventListener("click", () => this._refreshProjection(false))
    document.querySelector("[data-action='bible-force-refresh-projection']")?.addEventListener("click", () => this._refreshProjection(true))
    document.querySelector("[data-action='bible-open-suggestions']")?.addEventListener("click", () => this._openSuggestions())
    document.querySelector("[data-action='bible-open-conflicts']")?.addEventListener("click", () => this._openConflicts())
  },

  onLeave() {
    this._stopProjectionPolling()
  },

  async _load() {
    const data = await api.world.listBiblePages({ novel_id: state.currentProjectId })
    this._pages = data.items || []
    if (!this._activePage && this._pages.length) this._activePage = this._pages[0]
    if (this._activePage) {
      this._activePage = this._pages.find((page) => page.id === this._activePage.id) || this._activePage
      await this._restoreProjectionTask(this._activePage)
    }
  },

  _renderPageNav() {
    if (!this._pages.length) {
      return `<div style="color:var(--text-dim);font-size:13px;">暂无页面</div>`
    }
    return this._pages.map((page) => `
      <button class="btn btn-sm ${this._activePage?.id === page.id ? "btn-primary" : ""}"
        data-bible-page-id="${esc(page.id)}"
        style="display:block;width:100%;text-align:left;margin-bottom:6px;">
        ${esc(page.title)}
      </button>
    `).join("")
  },

  _renderActivePage() {
    const page = this._activePage
    if (!page) {
      return `<div class="empty-state"><p>创建一个世界书页面开始整理设定。</p></div>`
    }
    return `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px;">
        <div>
          <h2 style="margin:0 0 4px;font-size:20px;">${esc(page.title)}</h2>
          <div style="color:var(--text-dim);font-size:12px;">${esc(page.page_type)} · ${esc(page.status)}</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-sm btn-primary" data-action="bible-save-page">保存正文</button>
          <button class="btn btn-sm" data-action="bible-refresh-projection">刷新投影</button>
        </div>
      </div>
      <textarea class="form-textarea" id="bible-free-text" rows="16"
        style="width:100%;min-height:280px;">${esc(page.free_text || "")}</textarea>
      ${this._renderProjectionStatus(page)}
    `
  },

  _renderProjectionStatus(page) {
    const task = this._task
    const key = this._taskStorageKey(page)
    if (!task) {
      return `<div style="margin-top:10px;color:var(--text-dim);font-size:12px;">投影状态：未刷新 · ${esc(key)}</div>`
    }
    const retry = task.status === "failed" || task.status === "done"
      ? `<button class="btn btn-sm" data-action="bible-force-refresh-projection">强制重新刷新</button>`
      : ""
    return `
      <div style="margin-top:12px;border:1px solid var(--border);padding:10px;border-radius:6px;">
        <div style="font-size:12px;color:var(--text-dim);">投影任务：${esc(task.task_id || task.id || "")}</div>
        <div>状态：${esc(task.status || "pending")} · 进度 ${Math.round((task.progress || 0) * 100)}%</div>
        ${task.error_message ? `<div style="color:var(--danger);font-size:12px;">${esc(task.error_message)}</div>` : ""}
        ${retry}
      </div>
    `
  },

  async _createPage() {
    const formHtml = `
      <div class="form-group">
        <label>页面标题 *</label>
        <input class="form-input" id="bible-create-title" value="世界基本背景" />
      </div>
      <div class="form-group">
        <label>页面类型</label>
        <select class="form-select" id="bible-create-type">
          <option value="background">世界基本背景</option>
          <option value="species">种族</option>
          <option value="faction">势力</option>
          <option value="location">地点</option>
          <option value="rule">规则体系</option>
          <option value="item">重要物品</option>
          <option value="secret">秘密</option>
          <option value="custom">自定义</option>
        </select>
      </div>
    `
    showModal("新建世界书页面", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          const title = document.getElementById("bible-create-title")?.value?.trim()
          if (!title) {
            toast("请输入页面标题", "warning")
            return
          }
          try {
            const page = await api.world.createBiblePage({
              novel_id: state.currentProjectId,
              title,
              page_type: document.getElementById("bible-create-type")?.value || "custom",
              status: "draft",
            })
            this._activePage = page
            toast("页面已创建", "success")
            router.refresh()
          } catch (err) {
            toast(err.message || "创建页面失败", "error")
          }
        },
      },
    ])
  },

  async _savePage() {
    const page = this._activePage
    if (!page) return
    const freeText = document.getElementById("bible-free-text")?.value || ""
    try {
      this._activePage = await api.world.updateBiblePage(page.id, { free_text: freeText }, state.currentProjectId)
      toast("已保存，投影已标记为需要刷新", "success")
      router.refresh()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async _refreshProjection(force) {
    const page = this._activePage
    if (!page) return
    try {
      const result = await api.world.refreshBibleProjection(page.id, state.currentProjectId, PROJECTION_TYPE, force)
      localStorage.setItem(this._taskStorageKey(page), result.task_id)
      this._task = await api.tasks.get(result.task_id, state.currentProjectId)
      toast(result.existing ? "已有刷新任务正在运行" : "刷新任务已提交", "success")
      await router.refresh()
    } catch (err) {
      const apiError = window.errorLog?._lastApiError || null
      if (err.status === 409 || apiError?.status === 409) {
        if (window.errorLog) window.errorLog._lastApiError = null
        const finishedTaskId = this._extractFinishedTaskId(err, apiError)
        if (finishedTaskId) {
          localStorage.setItem(this._taskStorageKey(page), finishedTaskId)
          try {
            this._task = await api.tasks.get(finishedTaskId, state.currentProjectId)
          } catch {
            this._task = null
          }
        }
        this._task = {
          ...(this._task || {}),
          status: "done",
          error_message: "上次刷新已结束，可使用强制重新刷新。",
        }
        toast("上次刷新已结束，如需重跑请使用强制刷新", "warning")
        router.refresh()
      } else {
        toast(err.message || "刷新投影失败", "error")
      }
    }
  },

  async _restoreProjectionTask(page) {
    this._stopProjectionPolling()
    const taskId = localStorage.getItem(this._taskStorageKey(page))
    this._task = null
    if (!taskId) return
    try {
      const task = await api.tasks.get(taskId, state.currentProjectId)
      const meta = task.meta || {}
      if (
        meta.novel_id === state.currentProjectId
        && meta.page_id === page.id
        && meta.projection_type === PROJECTION_TYPE
      ) {
        this._task = task
        if (!this._isTerminalTask(task)) this._startProjectionPolling(taskId, page)
      }
    } catch {
      localStorage.removeItem(this._taskStorageKey(page))
    }
  },

  _isTerminalTask(task) {
    return ["done", "failed", "cancelled"].includes(task?.status)
  },

  _stopProjectionPolling() {
    if (this._projectionPoller?.stop) this._projectionPoller.stop()
    this._projectionPoller = null
  },

  _startProjectionPolling(taskId, page) {
    this._stopProjectionPolling()
    const novelId = state.currentProjectId
    this._projectionPoller = pollTaskProgress({
      taskId,
      workflowType: "world_bible_projection_refresh",
      apiClient: {
        tasks: {
          get: (id) => api.tasks.get(id, novelId),
        },
      },
      intervalMs: 800,
      onUpdate: (_progress, task) => {
        if (task) this._task = task
      },
      onDone: (_progress, task) => {
        this._projectionPoller = null
        if (task) this._task = task
        toast("世界书投影刷新完成", "success")
        router.renderCurrentView()
      },
      onFailed: (progress, task) => {
        this._projectionPoller = null
        if (task) this._task = task
        toast(`世界书投影刷新失败：${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
    if (page) localStorage.setItem(this._taskStorageKey(page), taskId)
  },

  _extractFinishedTaskId(err, apiError = null) {
    const message = `${err?.message || ""} ${apiError?.response || ""}`
    const match = message.match(/task_id:\s*([^；;\s]+)/)
    if (match?.[1]) return match[1].replace(/[",}]+$/, "")
    try {
      const parsed = JSON.parse(apiError?.response || "{}")
      return parsed?.detail?.task_id || null
    } catch {
      return null
    }
  },

  _taskStorageKey(page) {
    return `worldBibleProjection:${state.currentProjectId}:${page.id}:${PROJECTION_TYPE}`
  },

  async _openSuggestions() {
    try {
      const data = await api.world.listSuggestions({
        novel_id: state.currentProjectId,
        source_module: "imports",
        status: "pending",
      })
      this._suggestions = data.items || []
      const body = this._renderSuggestionsModal()
      showModal("创设建议", body, [])
      this._bindSuggestionModal()
    } catch (err) {
      toast(err.message || "加载建议失败", "error")
    }
  },

  _renderSuggestionsModal() {
    if (!this._suggestions.length) return `<div class="empty-state"><p>暂无待审核建议</p></div>`
    const base = this._suggestionBatchBase()
    return `
      <div style="max-height:60vh;overflow:auto;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;position:sticky;top:0;background:var(--surface);padding-bottom:10px;border-bottom:1px solid var(--border);">
          <div style="font-size:12px;color:var(--text-dim);">
            批量范围：${esc(base.review_group)} · ${esc(base.target_type)} · ${esc(base.action_schema)}
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button class="btn btn-sm btn-primary" data-action="bible-batch-confirm">批量确认</button>
            <button class="btn btn-sm" data-action="bible-batch-reject">批量拒绝</button>
          </div>
        </div>
        ${this._suggestions.map((item) => `
          <div style="border-bottom:1px solid var(--border);padding:10px 0;">
            ${this._renderSuggestionSelector(item, base)}
            <div style="font-weight:600;">${esc(item.review_group)} · ${esc(item.target_type)}</div>
            <div style="color:var(--text-dim);font-size:12px;">风险：${esc(item.risk_level)} · ${esc(item.action_schema)}</div>
            <pre style="white-space:pre-wrap;font-size:12px;">${esc(JSON.stringify(item.payload_json || {}, null, 2))}</pre>
            <button class="btn btn-sm btn-primary" data-bible-confirm-suggestion="${esc(item.id)}">确认</button>
            <button class="btn btn-sm" data-bible-reject-suggestion="${esc(item.id)}">拒绝</button>
          </div>
        `).join("")}
      </div>
    `
  },

  _bindSuggestionModal() {
    document.querySelector("[data-action='bible-batch-confirm']")?.addEventListener("click", () => this._decideSuggestionBatch(true))
    document.querySelector("[data-action='bible-batch-reject']")?.addEventListener("click", () => this._decideSuggestionBatch(false))
    document.querySelectorAll("[data-bible-confirm-suggestion]").forEach((node) => {
      node.addEventListener("click", () => this._decideSuggestion(node.getAttribute("data-bible-confirm-suggestion"), true))
    })
    document.querySelectorAll("[data-bible-reject-suggestion]").forEach((node) => {
      node.addEventListener("click", () => this._decideSuggestion(node.getAttribute("data-bible-reject-suggestion"), false))
    })
  },

  _suggestionBatchBase() {
    const first = this._suggestions[0] || {}
    return {
      review_group: first.review_group || "",
      target_type: first.target_type || "",
      action_schema: first.action_schema || "",
    }
  },

  _isSuggestionCompatible(item, base) {
    return item.review_group === base.review_group
      && item.target_type === base.target_type
      && item.action_schema === base.action_schema
  },

  _renderSuggestionSelector(item, base) {
    const compatible = this._isSuggestionCompatible(item, base)
    const reason = compatible ? "" : "只能批量处理同一分组、目标类型和动作结构的建议"
    return `
      <label style="display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:12px;color:var(--text-dim);">
        <input type="checkbox" data-bible-batch-suggestion="${esc(item.id)}" ${compatible ? "checked" : "disabled"}>
        ${compatible ? "已纳入批量操作" : esc(reason)}
      </label>
    `
  },

  async _decideSuggestionBatch(accepted) {
    const selected = Array.from(document.querySelectorAll("[data-bible-batch-suggestion]:checked"))
      .map((node) => node.getAttribute("data-bible-batch-suggestion"))
      .filter(Boolean)
    if (!selected.length) {
      toast("没有可批量处理的建议", "warning")
      return
    }
    let failed = 0
    for (const id of selected) {
      try {
        if (accepted) await api.world.confirmSuggestion(id, state.currentProjectId)
        else await api.world.rejectSuggestion(id, state.currentProjectId)
      } catch {
        failed += 1
      }
    }
    toast(failed ? `批量处理完成，${failed} 条失败` : "批量处理完成", failed ? "warning" : "success")
    await this._openSuggestions()
  },

  async _decideSuggestion(id, accepted) {
    try {
      if (accepted) await api.world.confirmSuggestion(id, state.currentProjectId)
      else await api.world.rejectSuggestion(id, state.currentProjectId)
      toast(accepted ? "建议已确认" : "建议已拒绝", "success")
      await this._openSuggestions()
    } catch (err) {
      toast(err.message || "处理建议失败", "error")
    }
  },

  async _openConflicts() {
    try {
      const data = await api.world.listWorldConflicts({ novel_id: state.currentProjectId, status: "pending" })
      this._conflicts = data.items || []
      const body = this._conflicts.length
        ? this._conflicts.map((item) => `<p>${esc(item.severity)} · ${esc(item.summary)}</p>`).join("")
        : `<div class="empty-state"><p>暂无冲突检查项</p></div>`
      showModal("冲突检查", body, [])
    } catch (err) {
      toast(err.message || "加载冲突失败", "error")
    }
  },
}

export default worldBibleView
