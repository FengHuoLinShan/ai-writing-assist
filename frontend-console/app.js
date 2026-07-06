/**
 * 应用主入口 — 初始化所有子系统，绑定事件
 *
 * 作为单页应用的启动器，负责：
 * 1. 初始化状态管理
 * 2. 初始化路由
 * 3. 注册全局快捷键
 * 4. 绑定命令栏事件
 * 5. 检查后端连接状态
 * 6. 激活默认视图
 */

import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "./shared/workflowProgress.js"
import { renderWorkflowCard } from "./shared/progressRenderer.js"

const SMART_DEDUP_PAGE_SIZE = 6

const App = {
  /** @type {boolean} */
  _initialized: false,

  _smartDedupTaskId: null,
  _smartDedupProgress: null,
  _smartDedupPoller: null,
  _smartDedupSuggestionPage: 0,
  _smartDedupSuggestionDraft: {},

  /**
   * 初始化应用
   */
  async init() {
    if (this._initialized) return
    this._initialized = true

    // 绑定全局 UI 事件
    this._bindNavigation()
    this._bindCommandBar()
    this._bindKeyboard()
    this._bindModalClose()
    this._bindHelpClose()
    this._bindCommandBarDismiss()
    this._bindThemeToggle()

    // 主题初始化
    this._initTheme()

    // 从 localStorage 恢复项目选择
    this._restoreProjectState()
    this._bindGlobalActions()

    // 初始化路由（async，等待项目元数据同步完成后再渲染首屏）
    await router.initRouter()
    router.onNavigate(() => this._renderGlobalActions())
    this._recoverSmartDedupWorkflow()
    this._renderGlobalActions()

    // 检查后端连接
    this._checkBackendHealth()

    // 定期检查（每 30 秒）
    setInterval(() => this._checkBackendHealth(), 30000)

    console.log("小说结构化创作控制台 v2.0 已启动")
  },

  /**
   * 绑定导航菜单点击
   */
  _bindNavigation() {
    document.querySelectorAll(".nav-item[data-view]").forEach((el) => {
      el.addEventListener("click", async () => {
        const viewName = el.dataset.view
        const route = router.getRoute(viewName)
        const lastSub = router.getLastSubView(viewName)
        await router.navigate(viewName, lastSub || (route && route.subViews.length > 0 ? route.subViews[0] : null))
      })
    })

    // 帮助按钮
    document.querySelector(".nav-item.help")?.addEventListener("click", () => {
      this._showHelp()
    })
  },

  _bindGlobalActions() {
    document.getElementById("view-actions")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action]")
      if (!button) return
      const action = button.getAttribute("data-action")
      if (action === "start-smart-dedup") {
        this._startSmartDedupScan()
      } else if (action === "show-smart-dedup-progress") {
        this._showSmartDedupProgress()
      }
    })
  },

  _renderGlobalActions() {
    const actions = document.getElementById("view-actions")
    if (!actions) return
    if (!state.currentProjectId || state.currentView === "project") {
      actions.innerHTML = ""
      return
    }
    const running = this._smartDedupProgress && !this._smartDedupProgress.terminal
    const done = this._smartDedupProgress?.done
    const label = running ? "查看智能去重" : done ? "查看去重建议" : "智能去重"
    const action = running || done ? "show-smart-dedup-progress" : "start-smart-dedup"
    actions.innerHTML = `
      <button class="btn btn-sm ${running ? "btn-primary" : ""}" data-action="${action}">
        ${esc(label)}
      </button>
    `
  },

  updateWordcountDashboard({
    chapterIndex = null,
    chapterWords = 0,
    todayWords = 0,
    saveState = "saved",
  } = {}) {
    const chapterEl = document.getElementById("topbar-chapter")
    const wcEl = document.getElementById("topbar-wordcount")
    const chapterWcEl = document.getElementById("topbar-chapter-wc")
    const todayWcEl = document.getElementById("topbar-today-wc")
    const saveStateEl = document.getElementById("topbar-save-state")
    if (!chapterEl || !wcEl) return

    const visible = state.currentView === "writing" && state.currentProjectId && chapterIndex != null
    chapterEl.classList.toggle("hidden", !visible)
    wcEl.classList.toggle("hidden", !visible)
    if (!visible) return

    chapterEl.textContent = `第 ${chapterIndex} 章`
    if (chapterWcEl) chapterWcEl.textContent = Number(chapterWords || 0).toLocaleString()
    if (todayWcEl) todayWcEl.textContent = Number(todayWords || 0).toLocaleString()
    if (saveStateEl) {
      saveStateEl.className = `save-state ${saveState || "saved"}`
      saveStateEl.title = {
        saving: "保存中",
        unsaved: "未保存",
        saved: "已保存",
      }[saveState] || "保存状态"
    }
  },

  _recoverSmartDedupWorkflow() {
    const workflow = recoverActiveWorkflows(state.currentProjectId)
      .find((item) => item.workflowType === "smart_dedup_scan")
    if (!workflow?.taskId) return
    this._smartDedupTaskId = workflow.taskId
    this._smartDedupProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: "smart_dedup_scan",
      status: "running",
      meta: workflow.meta || {},
    }, "smart_dedup_scan")
    this._startSmartDedupPolling(workflow.taskId)
  },

  async _startSmartDedupScan() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    if (this._smartDedupProgress && !this._smartDedupProgress.terminal) {
      this._showSmartDedupProgress()
      return
    }
    try {
      this._smartDedupSuggestionPage = 0
      this._smartDedupSuggestionDraft = {}
      const result = await api.projects.startSmartDedupScan(state.currentProjectId, {})
      this._smartDedupTaskId = result.task_id
      this._smartDedupProgress = normalizeTaskProgress({
        ...result,
        task_type: "smart_dedup_scan",
      }, "smart_dedup_scan")
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "smart_dedup_scan",
        label: "智能去重扫描",
        projectId: state.currentProjectId,
        view: state.currentView,
      })
      toast("智能去重扫描已提交", "success")
      this._startSmartDedupPolling(result.task_id)
      this._renderGlobalActions()
    } catch (err) {
      toast(`智能去重启动失败：${err.message}`, "error")
    }
  },

  _startSmartDedupPolling(taskId) {
    this._stopSmartDedupPolling()
    this._smartDedupPoller = pollTaskProgress({
      taskId,
      workflowType: "smart_dedup_scan",
      apiClient: api,
      onUpdate: (progress) => {
        this._smartDedupProgress = progress
        this._renderGlobalActions()
      },
      onDone: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._smartDedupTaskId = null
        this._smartDedupProgress = progress
        toast("智能去重扫描完成", "success")
        this._renderGlobalActions()
        this._showSmartDedupSuggestions()
      },
      onFailed: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._smartDedupTaskId = null
        this._smartDedupProgress = progress
        toast(`智能去重扫描失败：${progress.errorMessage || "未知错误"}`, "error")
        this._renderGlobalActions()
      },
    })
  },

  _stopSmartDedupPolling() {
    if (this._smartDedupPoller?.stop) this._smartDedupPoller.stop()
    this._smartDedupPoller = null
  },

  _showSmartDedupProgress() {
    const progress = this._smartDedupProgress
    if (!progress) {
      this._startSmartDedupScan()
      return
    }
    if (progress.done) {
      this._showSmartDedupSuggestions()
      return
    }
    showModal("智能去重", renderWorkflowCard(progress, {
      title: "智能去重扫描",
      destinationLabel: "完成后可选择合并或软废弃重复资产",
      detailLevel: "detailed",
    }), [])
  },

  _showSmartDedupSuggestions(page = this._smartDedupSuggestionPage || 0) {
    const result = this._smartDedupProgress?.raw?.result || {}
    const suggestions = this._smartDedupSuggestions(result)
    if (!suggestions.length) {
      this._resetSmartDedupResult()
      showModal("智能去重", "<p>没有发现可处理的重复资产。</p>", [{
        text: "重新扫描",
        class: "btn-primary",
        handler: async () => this._startSmartDedupScan(),
      }])
      return
    }
    const totalPages = Math.max(1, Math.ceil(suggestions.length / SMART_DEDUP_PAGE_SIZE))
    this._smartDedupSuggestionPage = Math.max(0, Math.min(Number(page) || 0, totalPages - 1))
    const body = this._renderSmartDedupSuggestionsBody(
      result,
      suggestions,
      this._smartDedupSuggestionPage
    )
    showModal("智能去重建议", body, [{
      text: "应用选中建议",
      class: "btn-primary",
      handler: async () => this._applySmartDedupSuggestions(suggestions),
    }])
    this._bindSmartDedupSuggestionControls(suggestions)
  },

  _resetSmartDedupResult() {
    const taskId = this._smartDedupTaskId
      || this._smartDedupProgress?.taskId
      || this._smartDedupProgress?.id
    this._stopSmartDedupPolling()
    if (taskId) clearActiveWorkflow(taskId)
    this._smartDedupTaskId = null
    this._smartDedupProgress = null
    this._smartDedupSuggestionPage = 0
    this._smartDedupSuggestionDraft = {}
    this._renderGlobalActions()
  },

  _smartDedupSuggestions(result) {
    if (!result || typeof result !== "object") return []
    const raw = Array.isArray(result.suggestions) ? result.suggestions : []
    return raw
      .map((item) => this._normalizeSmartDedupSuggestion(item))
      .filter(Boolean)
  },

  _normalizeSmartDedupSuggestion(item) {
    if (!item || typeof item !== "object") return null
    const sourceId = item.source_asset_id || item.source_entity_id
    const targetId = item.target_asset_id || item.target_entity_id
    if (!sourceId || !targetId || sourceId === targetId) return null
    const evidence = Array.isArray(item.evidence_anchors)
      ? item.evidence_anchors.filter((anchor) => anchor && typeof anchor === "object")
      : []
    const normalized = {
      ...item,
      asset_type: item.asset_type || "world_entity",
      action: item.action || "needs_review",
      source_asset_id: String(sourceId),
      source_title: item.source_title || item.source_entity_name || String(sourceId),
      target_asset_id: String(targetId),
      target_title: item.target_title || item.target_entity_name || String(targetId),
      recommended_primary_asset_id: item.recommended_primary_asset_id
        || item.recommended_primary_entity_id
        || item.target_asset_id
        || item.target_entity_id,
      recommended_primary_title: item.recommended_primary_title
        || item.recommended_primary_entity_name
        || item.target_title
        || item.target_entity_name,
      evidence_anchors: evidence,
      requires_canonical_confirmation: Boolean(item.requires_canonical_confirmation),
      requires_manual_confirmation: Boolean(item.requires_manual_confirmation),
      risk_level: item.risk_level || null,
    }
    if (this._isHighRiskSmartDedupSuggestion(normalized)) {
      normalized.requires_manual_confirmation = true
      normalized.risk_level = normalized.risk_level || "high"
    }
    return normalized
  },

  _isHighRiskSmartDedupSuggestion(item) {
    if (!item || typeof item !== "object") return false
    if (item.risk_level === "high" || item.requires_manual_confirmation) return true
    const method = String(item.match_method || "").toLowerCase()
    const action = String(item.action || "")
    const sourceTitle = normalizeSmartDedupTitle(item.source_title)
    const targetTitle = normalizeSmartDedupTitle(item.target_title)
    return method.includes("alias")
      && ["merge", "alias_only"].includes(action)
      && sourceTitle
      && targetTitle
      && sourceTitle !== targetTitle
  },

  _renderSmartDedupSuggestionsBody(result, suggestions, page = 0) {
    const totalPages = Math.max(1, Math.ceil(suggestions.length / SMART_DEDUP_PAGE_SIZE))
    const currentPage = Math.max(0, Math.min(Number(page) || 0, totalPages - 1))
    const start = currentPage * SMART_DEDUP_PAGE_SIZE
    const visible = suggestions.slice(start, start + SMART_DEDUP_PAGE_SIZE)
    const rows = visible
      .map((item, offset) => this._renderSmartDedupSuggestion(item, start + offset))
      .join("")
    return `
      <div style="margin-bottom:12px;color:var(--text-dim);font-size:13px;">
        扫描 ${esc(result.total_assets_scanned || 0)} 个资产，
        发现 ${esc(result.suggestion_count || suggestions.length)} 条建议。
        第 ${esc(currentPage + 1)} / ${esc(totalPages)} 页。
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px;">
        <span style="font-size:12px;color:var(--text-muted);">
          本页 ${esc(start + 1)}-${esc(Math.min(start + visible.length, suggestions.length))} / ${esc(suggestions.length)}
        </span>
        <span style="display:flex;gap:6px;">
          <button type="button" class="btn btn-sm" data-smart-dedup-page="prev" ${currentPage <= 0 ? "disabled" : ""}>上一页</button>
          <button type="button" class="btn btn-sm" data-smart-dedup-page="next" ${currentPage >= totalPages - 1 ? "disabled" : ""}>下一页</button>
        </span>
      </div>
      ${rows}
    `
  },

  _bindSmartDedupSuggestionControls(suggestions) {
    document.querySelectorAll("[data-smart-dedup-page]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) return
        this._captureSmartDedupSuggestionDraft()
        const delta = button.getAttribute("data-smart-dedup-page") === "next" ? 1 : -1
        this._showSmartDedupSuggestions(this._smartDedupSuggestionPage + delta)
      })
    })
    const bindings = [
      ["[data-smart-dedup-primary-mode]", "change"],
      ["[data-smart-dedup-manual-primary]", "input"],
      ["[data-smart-dedup-index], [data-smart-dedup-canonical]", "change"],
    ]
    bindings.forEach(([selector, eventName]) => {
      document.querySelectorAll(selector).forEach((input) => {
        input.addEventListener(eventName, () => this._captureSmartDedupSuggestionDraft())
      })
    })
  },

  _renderSmartDedupSuggestion(item, index) {
    const actionLabel = {
      merge: "合并",
      alias_only: "登记别名",
      deprecate_duplicate: "废弃重复项",
      needs_review: "复核",
    }[item.action] || item.action || "复核"
    const assetLabel = {
      world_entity: "世界对象",
      plot_thread: "剧情线",
      outline_arc: "篇章纲",
      scene: "Scene",
      foreshadowing_plan: "伏笔",
      reveal_plan: "揭示",
    }[item.asset_type] || item.asset_type || "资产"
    const evidence = (item.evidence_anchors || [])
      .map((anchor) => anchor.snippet || anchor.reason || anchor.source_type || "")
      .filter(Boolean)
      .join(" / ")
    const draft = this._smartDedupDraftFor(index, item)
    const selected = draft.selected ? "checked" : ""
    const sourceTitle = item.source_title || item.source_asset_id || "左侧对象"
    const targetTitle = item.target_title || item.target_asset_id || "右侧对象"
    const recommended = this._recommendedSmartDedupPrimary(item)
    const primary = this._resolveSmartDedupPrimaryChoice(item, draft)
    const sourcePrimary = draft.primaryMode === "source" ? "checked" : ""
    const targetPrimary = draft.primaryMode === "target" ? "checked" : ""
    const manualPrimary = draft.primaryMode === "manual" ? "checked" : ""
    const operationText = {
      merge: `保留「${primary.primaryTitle}」，合并「${primary.duplicateTitle}」`,
      alias_only: `登记为别名：将「${primary.duplicateTitle}」登记到「${primary.primaryTitle}」`,
      deprecate_duplicate: `废弃「${primary.duplicateTitle}」，关联到「${primary.primaryTitle}」`,
      needs_review: "仅复核，不会直接应用",
    }[item.action] || "需要复核后处理"
    const riskNotice = this._isHighRiskSmartDedupSuggestion(item) ? `
      <div style="margin-top:8px;padding:8px;border:1px solid var(--warning);border-radius:var(--radius-md);color:var(--warning);font-size:12px;">
        高风险别名命中：默认不选中。确认这确实是同一对象后再手动勾选应用。
      </div>
    ` : ""
    const canonical = item.requires_canonical_confirmation ? `
      <label style="display:block;margin-top:6px;color:var(--warning);font-size:12px;">
        <input type="checkbox" data-smart-dedup-canonical="${esc(index)}" ${draft.allowCanonicalMerge ? "checked" : ""} />
        确认合并两个正史对象
      </label>
    ` : ""
    return `
      <article style="border:1px solid var(--border);border-radius:var(--radius-md);padding:10px;margin-bottom:10px;" data-smart-dedup-card="${esc(index)}">
        <label style="display:flex;gap:8px;align-items:flex-start;">
          <input type="checkbox" data-smart-dedup-index="${esc(index)}" ${selected} />
          <span>
            <strong>${esc(assetLabel)} · ${esc(actionLabel)}：</strong>
            ${esc(item.source_title || item.source_asset_id)} → ${esc(item.target_title || item.target_asset_id)}
          </span>
        </label>
        <div style="color:var(--text-dim);font-size:12px;margin-top:4px;">
          置信度 ${esc(item.confidence ?? "-")} · ${esc(item.match_method || "-")}
        </div>
        <p style="margin:6px 0 0;">${esc(item.reason || "无说明")}</p>
        <div style="margin-top:8px;padding:8px;border:1px solid var(--border-light);border-radius:var(--radius-md);background:var(--bg-alt);">
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">
            操作路径：${esc(operationText)}
          </div>
          <div style="font-size:12px;font-weight:600;margin-bottom:6px;">
            主体对象 <span style="font-weight:400;color:var(--accent);">推荐主体：${esc(recommended.title || recommended.id || "-")}</span>
          </div>
          <label style="display:block;font-size:12px;margin-bottom:4px;">
            <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="target" ${targetPrimary} />
            保留右侧：${esc(targetTitle)} <span style="color:var(--text-dim);">(${esc(item.target_asset_id || "-")})</span>
          </label>
          <label style="display:block;font-size:12px;margin-bottom:4px;">
            <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="source" ${sourcePrimary} />
            保留左侧：${esc(sourceTitle)} <span style="color:var(--text-dim);">(${esc(item.source_asset_id || "-")})</span>
          </label>
          <label style="display:block;font-size:12px;">
            <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="manual" ${manualPrimary} />
            手动主体 ID
            <input class="form-input" data-smart-dedup-manual-primary="${esc(index)}" value="${esc(draft.manualPrimaryId || "")}" placeholder="输入要保留/登记到的对象 ID" style="margin-top:4px;" />
          </label>
        </div>
        ${riskNotice}
        ${canonical}
        <details style="margin-top:6px;"><summary>证据</summary><p>${esc(evidence || "无")}</p></details>
      </article>
    `
  },

  _smartDedupDraftFor(index, item) {
    const existing = this._smartDedupSuggestionDraft[index] || {}
    const recommended = this._recommendedSmartDedupPrimary(item)
    let primaryMode = existing.primaryMode
    let manualPrimaryId = existing.manualPrimaryId || ""
    if (!primaryMode) {
      if (recommended.id && recommended.id === item.source_asset_id) {
        primaryMode = "source"
      } else if (recommended.id && recommended.id !== item.target_asset_id) {
        primaryMode = "manual"
        manualPrimaryId = recommended.id
      } else {
        primaryMode = "target"
      }
    }
    return {
      selected: existing.selected ?? (
        item.action !== "needs_review"
        && !this._isHighRiskSmartDedupSuggestion(item)
      ),
      primaryMode,
      manualPrimaryId,
      allowCanonicalMerge: Boolean(existing.allowCanonicalMerge),
    }
  },

  _recommendedSmartDedupPrimary(item) {
    const id = item.recommended_primary_asset_id
      || item.recommended_target_asset_id
      || item.primary_asset_id
      || item.target_asset_id
    const title = item.recommended_primary_title
      || item.recommended_target_title
      || item.primary_title
      || (id === item.source_asset_id ? item.source_title : item.target_title)
    return { id, title }
  },

  _resolveSmartDedupPrimaryChoice(item, draft) {
    const source = {
      id: item.source_asset_id,
      title: item.source_title || item.source_asset_id,
    }
    const target = {
      id: item.target_asset_id,
      title: item.target_title || item.target_asset_id,
    }
    const [primary, duplicate] = draft.primaryMode === "source"
      ? [source, target]
      : [target, source]
    if (draft.primaryMode === "manual" && draft.manualPrimaryId) {
      primary.id = draft.manualPrimaryId
      primary.title = draft.manualPrimaryId
    }
    return {
      primaryId: primary.id,
      primaryTitle: primary.title,
      duplicateId: duplicate.id,
      duplicateTitle: duplicate.title,
    }
  },

  _captureSmartDedupSuggestionDraft() {
    if (typeof document === "undefined") return
    document.querySelectorAll("[data-smart-dedup-index]").forEach((input) => {
      const index = Number(input.getAttribute("data-smart-dedup-index"))
      if (!Number.isFinite(index)) return
      const primary = document.querySelector(`input[name="smart-dedup-primary-${index}"]:checked`)
      const manual = document.querySelector(`[data-smart-dedup-manual-primary="${index}"]`)
      const canonical = document.querySelector(`[data-smart-dedup-canonical="${index}"]`)
      this._smartDedupSuggestionDraft[index] = {
        ...(this._smartDedupSuggestionDraft[index] || {}),
        selected: Boolean(input.checked),
        primaryMode: primary?.value || this._smartDedupSuggestionDraft[index]?.primaryMode,
        manualPrimaryId: manual?.value?.trim() || "",
        allowCanonicalMerge: Boolean(canonical?.checked),
      }
    })
  },

  _buildSmartDedupApplyItem(item, draft) {
    const primary = this._resolveSmartDedupPrimaryChoice(item, draft)
    if (!primary.primaryId || !primary.duplicateId) return null
    return {
      asset_type: item.asset_type,
      action: item.action,
      source_asset_id: primary.duplicateId,
      target_asset_id: primary.primaryId,
      alias: item.alias || primary.duplicateTitle,
      allow_canonical_merge: Boolean(draft.allowCanonicalMerge),
    }
  },

  async _applySmartDedupSuggestions(suggestions) {
    this._captureSmartDedupSuggestionDraft()
    const selected = suggestions
      .map((item, index) => ({
        index,
        item,
        draft: this._smartDedupDraftFor(index, item),
      }))
      .filter((entry) => entry.item)
      .filter((entry) => entry.draft.selected)
      .filter((entry) => ["merge", "alias_only", "deprecate_duplicate"].includes(entry.item.action))
    if (!selected.length) {
      toast("请选择可应用的建议", "warning")
      return
    }
    const payload = selected
      .map(({ item, draft }) => this._buildSmartDedupApplyItem(item, draft))
      .filter(Boolean)
    try {
      const applied = await api.projects.applySmartDedup(state.currentProjectId, {
        confirmed: true,
        suggestions: payload,
      })
      closeModal()
      toast(`已应用 ${applied.applied || 0} 条智能去重建议`, "success")
      this._resetSmartDedupResult()
      api.clearCache()
      router.refresh()
    } catch (err) {
      toast(err.message || "应用失败", "error")
    }
  },

  /**
   * 绑定命令栏事件
   */
  _bindCommandBar() {
    const input = document.getElementById("command-input")
    const hint = document.getElementById("command-hint")
    const bar = document.getElementById("command-bar")
    const suggestions = document.getElementById("command-suggestions")

    if (!input || !bar) return

    // 聚焦/失焦
    input.addEventListener("focus", () => {
      const prefix = input.value.startsWith("/") ? "/" : ":"
      state.mode = prefix === ":" ? "COMMAND" : "SEARCH"
      bar.classList.add("active")
    })

    input.addEventListener("blur", () => {
      if (!input.value) {
        this._hideCommandBar()
      }
    })

    // 回车执行
    input.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        e.preventDefault()
        const value = input.value.trim()
        input.value = ""
        this._hideCommandBar()

        if (value) {
          await commands.execute(value)
        }

        document.getElementById("workspace")?.focus()
        return
      }

      if (e.key === "Escape") {
        e.preventDefault()
        input.value = ""
        this._hideCommandBar()
        document.getElementById("workspace")?.focus()
        return
      }

      // 自动补全建议（Tab）
      if (e.key === "Tab") {
        e.preventDefault()
        const value = input.value.trim()
        if (value.startsWith(":")) {
          const prefix = value.slice(1)
          const suggestions = commands.getSuggestions(prefix)
          if (suggestions.length > 0) {
            input.value = `:${suggestions[0].name.slice(1)} `
          }
        }
      }

      // 实时提示
      if (e.key === "Backspace" || e.key.length === 1) {
        setTimeout(() => this._updateHint(input, hint, suggestions), 50)
      }
    })

    // 输入提示
    input.addEventListener("input", () => {
      this._updateHint(input, hint, suggestions)
    })
  },

  /**
   * 隐藏命令栏
   */
  _hideCommandBar() {
    state.mode = "NORMAL"
    const bar = document.getElementById("command-bar")
    const suggestions = document.getElementById("command-suggestions")
    if (bar) bar.classList.remove("active", "has-suggestions")
    if (suggestions) suggestions.replaceChildren()
  },

  /**
   * 点击外部关闭命令栏
   */
  _bindCommandBarDismiss() {
    document.addEventListener("click", (e) => {
      const bar = document.getElementById("command-bar")
      const input = document.getElementById("command-input")
      if (!bar || !input) return
      if (bar.classList.contains("active") && !bar.contains(e.target)) {
        input.value = ""
        this._hideCommandBar()
      }
    })
  },

  /**
   * 更新命令栏提示和建议
   */
  _updateHint(input, hint, suggestionsEl) {
    const bar = document.getElementById("command-bar")
    const value = input.value.trim()

    if (hint) {
      if (!value) {
        hint.textContent = ""
      } else if (value.startsWith(":")) {
        hint.textContent = "Tab 补全"
      } else if (value.startsWith("/")) {
        hint.textContent = "按 Enter 跳转 RAG 搜索"
      } else {
        hint.textContent = ""
      }
    }

    if (!suggestionsEl || !bar) return

    if (value.startsWith(":")) {
      const prefix = value.slice(1)
      const suggestions = commands.getSuggestions(prefix)
      if (suggestions.length > 0) {
        suggestionsEl.replaceChildren()
        for (const s of suggestions.slice(0, 6)) {
          const row = document.createElement("div")
          row.className = "suggestion"
          row.dataset.cmd = s.name
          const label = document.createElement("span")
          label.textContent = s.name
          if (s.description) {
            const desc = document.createElement("span")
            desc.style.color = "var(--text-tertiary)"
            desc.style.marginLeft = "8px"
            desc.style.fontSize = "12px"
            desc.textContent = s.description
            label.appendChild(desc)
          }
          const key = document.createElement("span")
          key.className = "suggestion-key"
          key.textContent = "Enter"
          row.append(label, key)
          row.addEventListener("mousedown", (e) => {
            e.preventDefault()
            const cmd = row.dataset.cmd
            if (cmd) {
              input.value = ""
              this._hideCommandBar()
              commands.execute(cmd)
            }
          })
          suggestionsEl.appendChild(row)
        }
        bar.classList.add("has-suggestions")
        return
      }
    }

    suggestionsEl.replaceChildren()
    bar.classList.remove("has-suggestions")
  },

  /**
   * 绑定全局快捷键
   */
  _bindKeyboard() {
    document.addEventListener("keydown", (e) => {
      // Ctrl+S / Cmd+S: 始终触发保存（即使在输入框中）
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        if (typeof window.writingView?._autosave === "function") {
          window.writingView._autosave()
        }
        return
      }

      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault()
        if (state.currentView === "writing" && typeof window.writingView?._toggleOutlineFloat === "function") {
          window.writingView._toggleOutlineFloat()
        }
        return
      }

      // 忽略输入框中的其他快捷键（除 Esc）
      const tag = e.target.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") {
          e.target.blur()
          state.mode = "NORMAL"
        }
        return
      }

      switch (e.key) {
        case "?":
          e.preventDefault()
          this._showHelp()
          break

        case ":":
          e.preventDefault()
          this._focusCommandBar(":")
          break

        case "/":
          e.preventDefault()
          this._focusCommandBar("/")
          break

        case "Escape":
          if (!document.getElementById("modal-overlay").classList.contains("hidden")) {
            closeModal()
          } else if (!document.getElementById("help-overlay").classList.contains("hidden")) {
            document.getElementById("help-overlay").classList.add("hidden")
          } else {
            if (state.currentSubView) {
              const route = router.getRoute(state.currentView)
              router.navigate(state.currentView, null)
            }
          }
          break

        case "n":
          this._triggerAction("new")
          break

        case "e":
          this._triggerAction("edit")
          break

        case "s":
          if (typeof window.writingView?._autosave === "function") {
            window.writingView._autosave()
          } else {
            this._triggerAction("save") || toast("没有可保存的内容", "info")
          }
          break

        case "g":
          this._triggerAction("generate")
          break

        case "x":
          this._triggerAction("delete")
          break

        case "j":
          e.preventDefault()
          this._moveSelection(1)
          break

        case "k":
          e.preventDefault()
          this._moveSelection(-1)
          break

        case "h":
          e.preventDefault()
          this._focusSidebar()
          break

        case "l":
          e.preventDefault()
          break

        case "Enter":
          this._triggerAction("select")
          break
      }
    })
  },

  /**
   * 聚焦命令栏
   * @param {string} [prefix] - 前缀
   */
  _focusCommandBar(prefix = ":") {
    const input = document.getElementById("command-input")
    const bar = document.getElementById("command-bar")
    if (!input || !bar) return

    input.value = prefix
    bar.classList.add("active")
    input.focus()
    state.mode = prefix === ":" ? "COMMAND" : "SEARCH"

    const len = input.value.length
    input.setSelectionRange(len, len)
  },

  /**
   * 触发视图中的操作按钮
   * @param {string} action
   */
  _triggerAction(action) {
    const btn = document.querySelector(`[data-action="${action}"]`)
    if (btn) {
      btn.click()
      return
    }

    const actions = document.getElementById("view-actions")
    if (actions) {
      const candidates = actions.querySelectorAll(".btn")
      const actionMap = {
        new: ["新建", "创建", "新增"],
        edit: ["编辑"],
        generate: ["生成"],
        review: ["复查"],
        confirm: ["确认"],
        ignore: ["忽略"],
        delete: ["删除", "废弃"],
        select: ["打开", "查看"],
      }
      const texts = actionMap[action] || []
      for (const b of candidates) {
        if (texts.some((t) => b.textContent.includes(t))) {
          b.click()
          return
        }
      }
    }
  },

  /**
   * 移动选中行
   * @param {number} direction - 1 向下, -1 向上
   */
  _moveSelection(direction) {
    const rows = document.querySelectorAll(".data-table tr.clickable, .data-table tr[data-id], .project-card[data-id], .list-row[data-id]")
    if (rows.length === 0) return

    let currentIdx = -1
    let currentId = null
    if (state.selectedItem) {
      currentId = state.selectedItem.id || state.selectedItem.value
    }

    rows.forEach((row, i) => {
      const rowId = row.dataset.id || row.dataset.value
      if (rowId && rowId === currentId) {
        currentIdx = i
      }
    })

    let nextIdx
    if (currentIdx < 0) {
      nextIdx = direction > 0 ? 0 : rows.length - 1
    } else {
      nextIdx = currentIdx + direction
      if (nextIdx < 0) nextIdx = rows.length - 1
      if (nextIdx >= rows.length) nextIdx = 0
    }

    rows.forEach((row) => row.classList.remove("selected"))
    rows[nextIdx].classList.add("selected")
    rows[nextIdx].scrollIntoView({ block: "nearest" })

    state.selectedItem = { id: rows[nextIdx].dataset.id || rows[nextIdx].dataset.value }
  },

  /**
   * 聚焦左侧导航
   */
  _focusSidebar() {
    const active = document.querySelector(".nav-item.active[data-view]")
    const target = active || document.querySelector(".nav-item[data-view]")
    if (target) {
      if (!target.hasAttribute("tabindex")) {
        target.setAttribute("tabindex", "-1")
      }
      target.focus()
    }
  },

  /**
   * 显示快捷键帮助
   */
  _showHelp() {
    document.getElementById("help-overlay")?.classList.remove("hidden")
  },

  /**
   * 绑定模态框关闭
   */
  _bindModalClose() {
    document.getElementById("modal-close")?.addEventListener("click", closeModal)
    document.getElementById("modal-overlay")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeModal()
    })
  },

  /**
   * 绑定帮助弹窗关闭
   */
  _bindHelpClose() {
    document.getElementById("help-close")?.addEventListener("click", () => {
      document.getElementById("help-overlay")?.classList.add("hidden")
    })
    document.getElementById("help-overlay")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) {
        document.getElementById("help-overlay")?.classList.add("hidden")
      }
    })
  },

  /**
   * 从 localStorage 恢复项目选择状态
   */
  _restoreProjectState() {
    try {
      const savedId = localStorage.getItem("novel_currentProjectId")
      if (savedId) {
        state.currentProjectId = savedId
      }
      const savedProject = localStorage.getItem("novel_currentProject")
      if (savedProject) {
        state.currentProject = JSON.parse(savedProject)
      }
    } catch {}
  },

  /**
   * 初始化主题（三主题系统）
   */
  _initTheme() {
    try {
      const saved = localStorage.getItem("novel_theme")
      // 旧主题值迁移映射
      const legacyMap = { light: "minimal", "dark-soft": "warm", paper: "warm" }
      const raw = saved || "minimal"
      const theme = legacyMap[raw] || raw
      document.documentElement.setAttribute("data-theme", theme)
    } catch {}
  },

  /**
   * 切换主题
   */
  _switchTheme(theme) {
    try {
      document.documentElement.setAttribute("data-theme", theme)
      localStorage.setItem("novel_theme", theme)
      const labels = { minimal: "现代极简", warm: "黄金时刻", dark: "午夜星河" }
      toast(`已切换至「${labels[theme] || theme}」主题`, "success")
    } catch {}
  },

  /**
   * 绑定主题切换按钮
   */
  _bindThemeToggle() {
    const btn = document.getElementById("theme-toggle")
    const menu = document.getElementById("theme-menu")
    if (!btn || !menu) return
    btn.addEventListener("click", (e) => {
      e.stopPropagation()
      menu.classList.toggle("hidden")
    })
    menu.querySelectorAll("[data-theme-value]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation()
        this._switchTheme(el.dataset.themeValue)
        menu.classList.add("hidden")
      })
    })
    document.addEventListener("click", () => menu.classList.add("hidden"))
  },

  /**
   * 检查后端健康状态
   */
  async _checkBackendHealth() {
    const connected = await api.healthCheck()
    state.backendConnected = connected
  },
}

// 页面加载完成后启动
document.addEventListener("DOMContentLoaded", () => {
  App.init()
})

function normalizeSmartDedupTitle(value) {
  return String(value || "").trim().toLowerCase()
}

window.App = App
export default App
