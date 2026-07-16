/**
 * 大纲视图
 *
 * 子标签：小说总纲 | 篇章纲 | 剧情线 | 场景卡 | 伏笔 | 揭示
 */
import {
  bulkResultMessage,
  clearAllBulkSelections,
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  renderBulkToolbar,
  renderSelectionCell,
  renderSelectionHeader,
  runBulkAction,
  selectedItemsFrom,
  syncBulkSelectionUi,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../shared/bulkSelection.js"
import {
  bindActionMenus,
  bindWorkspaceClick,
  renderActionMenu,
  renderLoadingSkeleton,
} from "../shared/viewHelper.js"
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { confirmAsync } from "../shared/confirmAsync.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"
import sceneWorkbenchView from "./sceneWorkbenchView.js"
import {
  assetAttentionReasons,
  displayStateBadgeClass,
  structureAssetDisplay,
} from "../shared/assetDisplayState.js"
import { importAuthorizationNotice, importAuthorizationPayload } from "../shared/importAuthorization.js"
import storyOutlineView from "./storyOutlineView.js"

const SCENE_ALLOWED_TAGS = new Set(["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"])
const ENTITY_ALLOWED_STATUSES = new Set(["canonical", "draft", "candidate", "deprecated"])
const FORESHADOWING_STATUSES = ["draft", "planted", "triggered", "resolved", "abandoned"]
const REVEAL_STATUSES = ["draft", "planned", "revealed", "resolved", "abandoned"]

const FORESHADOWING_STATUS_LABELS = { draft: "工作稿", planted: "已埋下", triggered: "已触发", resolved: "已兑现", abandoned: "历史" }
const REVEAL_STATUS_LABELS = { draft: "工作稿", planned: "计划中", revealed: "已揭示", resolved: "已解决", abandoned: "历史" }
const STRUCTURE_FILTER_DEFAULTS = { status: "", source: "", workflow_id: "", needs_review: "", skip: 0, limit: 50 }
const STRUCTURE_SOURCE_OPTIONS = [
  ["deep_import", "深度导入"],
  ["manual", "手动"],
  ["ai_generated", "AI 生成"],
]

const OUTLINE_PREVIEW_SECTIONS = [
  {
    key: "threads",
    label: "剧情线",
    fields: [
      ["name", "名称", "text"],
      ["summary", "摘要", "textarea"],
      ["visible_goal", "表层目标", "textarea"],
      ["hidden_truth", "隐藏真相", "textarea"],
      ["start_chapter", "起始章节", "number"],
      ["planned_payoff_chapter", "计划收束章节", "number"],
    ],
  },
  {
    key: "arcs",
    label: "篇章纲",
    fields: [
      ["title", "标题", "text"],
      ["arc_goal", "篇章目标", "textarea"],
      ["core_conflict", "核心冲突", "textarea"],
      ["start_chapter", "起始章节", "number"],
      ["end_chapter", "结束章节", "number"],
    ],
  },
  {
    key: "scenes",
    label: "Scene",
    fields: [
      ["title", "标题", "text"],
      ["goal", "目标", "textarea"],
      ["core_conflict", "核心冲突", "textarea"],
      ["must_happen", "必须发生", "textarea"],
      ["must_not_happen", "禁止发生", "textarea"],
      ["chapter_start", "起始章节", "number"],
      ["chapter_end", "结束章节", "number"],
    ],
  },
  {
    key: "foreshadowing_plans",
    label: "伏笔",
    fields: [
      ["name", "名称", "text"],
      ["summary", "摘要", "textarea"],
      ["planned_seed_chapter", "计划埋下章节", "number"],
      ["planned_payoff_chapter", "计划兑现章节", "number"],
    ],
  },
  {
    key: "reveal_plans",
    label: "揭示",
    fields: [
      ["target_name", "揭示对象", "text"],
      ["secret_summary", "秘密摘要", "textarea"],
    ],
  },
  {
    key: "offscreen_progress",
    label: "幕后进展",
    fields: [
      ["thread_name", "关联剧情线", "text"],
      ["offscreen_description", "幕后进展", "textarea"],
    ],
  },
  {
    key: "risks",
    label: "风险",
    fields: [
      ["risk_type", "风险类型", "text"],
      ["description", "说明", "textarea"],
    ],
  },
  {
    key: "questions_for_user",
    label: "待作者决定",
    fields: [
      ["question", "问题", "textarea"],
      ["context", "背景", "textarea"],
    ],
  },
]

const outlineView = {
  _threads: [],
  _arcs: [],
  _scenes: [],
  _foreshadowing: [],
  _reveals: [],
  _loading: true,
  _generateOverlap: { threadCount: 0, arcCount: 0, rangeKey: "" },
  _structureFilters: {},
  _structureTotals: {
    threads: 0,
    arcs: 0,
    foreshadowing: 0,
    reveals: 0,
  },
  _structureLoadErrors: {},
  _structureLoadRequestId: 0,
  _plotAutoExtractTaskId: null,
  _plotAutoExtractProgress: null,
  _plotAutoExtractPoller: null,
  _plotAutoExtractMeta: null,
  _outlineGenerateTaskId: null,
  _outlineGenerateProgress: null,
  _outlineGeneratePoller: null,
  _outlineGenerateMeta: null,
  _outlineGeneratePreview: null,
  _outlineAnalysisTaskId: null,
  _outlineAnalysisProgress: null,
  _outlineAnalysisPoller: null,
  _outlineAnalysisMeta: null,
  _outlineAnalysisResult: null,
  _outlineAnalysisCancelPending: false,
  _outlineAnalysisSubmitting: false,
  _bulkSelections: {},
  _sceneWorkbenchActive: false,
  _storyOutlineActive: false,

  async onEnter() {
    const loadRequestId = ++this._structureLoadRequestId
    const isCurrentLoad = () => loadRequestId === this._structureLoadRequestId
    this._syncOutlineAnalysisProject()
    this._loading = true
    this._threads = []
    this._arcs = []
    this._foreshadowing = []
    this._reveals = []
    this._structureTotals = {
      threads: 0,
      arcs: 0,
      foreshadowing: 0,
      reveals: 0,
    }
    clearAllBulkSelections(this)

    const subView = state.currentSubView || "story-outline"
    delete this._structureLoadErrors[subView]
    if (subView === "scenes") {
      if (this._storyOutlineActive) {
        storyOutlineView.onLeave()
        this._storyOutlineActive = false
      }
      this._sceneWorkbenchActive = true
      this._loading = false
      await sceneWorkbenchView.onEnter()
      return
    }
    if (this._sceneWorkbenchActive) {
      sceneWorkbenchView.onLeave()
      this._sceneWorkbenchActive = false
    }
    if (subView === "story-outline") {
      this._storyOutlineActive = true
      this._loading = false
      await storyOutlineView.onEnter()
      return
    }
    if (this._storyOutlineActive) {
      storyOutlineView.onLeave()
      this._storyOutlineActive = false
    }

    if (!state.currentProjectId) {
      this._loading = false
      return
    }

    const fetchThreads = subView === "threads"
    const fetchArcs = subView === "arcs"
    const fetchForeshadowing = subView === "foreshadowing"
    const fetchReveals = subView === "reveals"
    const filterParams = this._structureFilterParams(subView)

    const promises = []
    if (fetchThreads) {
      promises.push(
        api.outline.listThreads(state.currentProjectId, filterParams)
          .then((data) => {
            if (!isCurrentLoad()) return
            const items = data.items || data || []
            this._threads = items
            this._structureTotals.threads = Number(data.total ?? this._threads.length) || 0
          })
          .catch((err) => {
            if (!isCurrentLoad()) return
            this._threads = []
            this._structureTotals.threads = 0
            this._setStructureLoadError("threads", err)
          })
      )
    }
    if (fetchArcs) {
      promises.push(
        api.outline.listArcs(state.currentProjectId, filterParams)
          .then((data) => {
            if (!isCurrentLoad()) return
            const items = data.items || data || []
            this._arcs = items
            this._structureTotals.arcs = Number(data.total ?? this._arcs.length) || 0
          })
          .catch((err) => {
            if (!isCurrentLoad()) return
            this._arcs = []
            this._structureTotals.arcs = 0
            this._setStructureLoadError("arcs", err)
          })
      )
    }
    if (fetchForeshadowing) {
      promises.push(
        api.outline.listForeshadowing(state.currentProjectId, filterParams)
          .then((data) => {
            if (!isCurrentLoad()) return
            const items = data.items || data || []
            this._foreshadowing = items
            this._structureTotals.foreshadowing = Number(data.total ?? this._foreshadowing.length) || 0
          })
          .catch((err) => {
            if (!isCurrentLoad()) return
            this._foreshadowing = []
            this._structureTotals.foreshadowing = 0
            this._setStructureLoadError("foreshadowing", err)
          })
      )
    }
    if (fetchReveals) {
      promises.push(
        api.outline.listReveals(state.currentProjectId, filterParams)
          .then((data) => {
            if (!isCurrentLoad()) return
            const items = data.items || data || []
            this._reveals = items
            this._structureTotals.reveals = Number(data.total ?? this._reveals.length) || 0
          })
          .catch((err) => {
            if (!isCurrentLoad()) return
            this._reveals = []
            this._structureTotals.reveals = 0
            this._setStructureLoadError("reveals", err)
          })
      )
    }

    if (promises.length > 0) {
      await Promise.all(promises)
    }
    if (!isCurrentLoad()) return
    this._recoverOutlineGenerateWorkflow()
    this._recoverOutlineAnalysisWorkflow()
    this._loading = false
  },

  onLeave() {
    // 使离开视图后才完成的结构请求失效，避免旧结果恢复轮询或污染下次进入时的状态。
    this._structureLoadRequestId += 1
    this._stopPlotAutoExtractPolling()
    this._stopOutlineGeneratePolling()
    this._stopOutlineAnalysisPolling()
    if (this._sceneWorkbenchActive) {
      sceneWorkbenchView.onLeave()
      this._sceneWorkbenchActive = false
    }
    if (this._storyOutlineActive) {
      storyOutlineView.onLeave()
      this._storyOutlineActive = false
    }
  },

  onActivate() {
    // KeepAlive 恢复后重新绑定事件（DOM 来自缓存，事件监听器可能丢失）
    this._syncOutlineAnalysisProject()
    if (state.currentSubView === "scenes") {
      this._sceneWorkbenchActive = true
      sceneWorkbenchView.onActivate()
    } else if (state.currentSubView === "story-outline") {
      this._storyOutlineActive = true
      storyOutlineView.onActivate()
    } else {
      this._recoverOutlineAnalysisWorkflow()
      this._bindEvents()
    }
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
    if (this._storyOutlineActive) storyOutlineView.onDeactivate()
  },

  async _refreshCurrentSubViewInPlace({ preserveScroll = true } = {}) {
    const content = typeof document !== "undefined"
      ? document.getElementById("workspace-content")
      : null
    const scrollTop = preserveScroll && content ? content.scrollTop : 0

    await this.onEnter()

    if (!content) {
      router.refresh()
      return
    }

    content.innerHTML = await this.render()
    content.scrollTop = scrollTop
    this._bindEvents()
    content.dispatchEvent(new Event("workspace:content-rendered", { bubbles: true }))
  },

  _renderOutlineHeaderTitle(subView) {
    if (subView === "story-outline") return `小说总纲${this._renderProjectChip()}`
    if (subView === "threads") return `剧情线 <span class="view-header__count">共 ${esc(this._structureTotals.threads)} 个</span>${this._renderProjectChip()}`
    if (subView === "arcs") return `篇章纲 <span class="view-header__count">共 ${esc(this._structureTotals.arcs)} 个</span>${this._renderProjectChip()}`
    if (subView === "foreshadowing") return `伏笔 <span class="view-header__count">共 ${esc(this._structureTotals.foreshadowing)} 个</span>${this._renderProjectChip()}`
    if (subView === "reveals") return `揭示 <span class="view-header__count">共 ${esc(this._structureTotals.reveals)} 个</span>${this._renderProjectChip()}`
    return ""
  },

  _renderOutlineHeaderActions(subView) {
    const plotAutoExtract = this._renderPlotAutoExtractAction(subView)
    const analysisBusy = Boolean(
      this._outlineAnalysisSubmitting
      || (this._outlineAnalysisProgress && !this._outlineAnalysisProgress.terminal),
    )
    const analyzeOutline = `<button class="btn btn-sm" data-action="analyze-outline" ${analysisBusy ? "disabled" : ""}>${analysisBusy ? "AI 分析中" : "AI 分析大纲"}</button>`
    if (subView === "threads") {
      return `
        <button class="btn btn-sm btn-primary" data-action="create-thread">新建剧情线</button>
        ${analyzeOutline}
        ${plotAutoExtract}
      `
    }
    if (subView === "arcs") {
      return `
        <button class="btn btn-sm btn-primary" data-action="create-arc">新建篇章纲</button>
        ${analyzeOutline}
        ${plotAutoExtract}
      `
    }
    if (subView === "foreshadowing") {
      return `
        <button class="btn btn-sm btn-primary" data-action="create-foreshadowing">新建伏笔</button>
        ${analyzeOutline}
        ${plotAutoExtract}
      `
    }
    if (subView === "reveals") {
      return `
        <button class="btn btn-sm btn-primary" data-action="create-reveal">新建揭示</button>
        ${analyzeOutline}
        ${plotAutoExtract}
      `
    }
    return ""
  },

  _renderOutlineHeader(subView = state.currentSubView || "story-outline") {
    if (subView === "scenes") {
      return `
        <div class="subnav">
          <span class="subnav-item ${subView === "story-outline" ? "active" : ""}" data-action="nav-story-outline">小说总纲</span>
          <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-action="nav-arcs">篇章纲</span>
          <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-action="nav-threads">剧情线</span>
          <span class="subnav-item ${subView === "scenes" ? "active" : ""}" data-action="nav-scenes">场景工作台</span>
          <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-action="nav-foreshadowing">伏笔</span>
          <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-action="nav-reveals">揭示</span>
          ${sceneWorkbenchView.renderHeaderActions()}
        </div>
      `
    }
    return `
      <div class="view-header view-header--with-tabs outline-toolbar">
        <div class="subnav">
          <span class="subnav-item ${subView === "story-outline" ? "active" : ""}" data-action="nav-story-outline">小说总纲</span>
          <span class="subnav-item ${subView === "arcs" ? "active" : ""}" data-action="nav-arcs">篇章纲</span>
          <span class="subnav-item ${subView === "threads" ? "active" : ""}" data-action="nav-threads">剧情线</span>
          <span class="subnav-item ${subView === "scenes" ? "active" : ""}" data-action="nav-scenes">场景工作台</span>
          <span class="subnav-item ${subView === "foreshadowing" ? "active" : ""}" data-action="nav-foreshadowing">伏笔</span>
          <span class="subnav-item ${subView === "reveals" ? "active" : ""}" data-action="nav-reveals">揭示</span>
        </div>
        <div class="view-header__tail">
          <span class="view-header__title">${this._renderOutlineHeaderTitle(subView)}</span>
          <div class="view-header__actions">
            ${this._renderOutlineHeaderActions(subView)}
            <span data-role="smart-dedup-action"></span>
          </div>
        </div>
      </div>
    `
  },

  async render() {
    this._syncOutlineAnalysisProject()
    const subView = state.currentSubView || "story-outline"
    let html = ""

    html += this._renderOutlineHeader(subView)

    if (subView === "scenes") {
      html += await sceneWorkbenchView.render()
    } else if (subView === "story-outline") {
      html += await storyOutlineView.render()
    } else if (this._loading) {
      html += renderLoadingSkeleton("大纲数据加载中...")
    } else if (this._structureLoadErrors[subView]) {
      html += this._renderStructureLoadError(subView)
    } else if (subView === "threads") {
      html += this._renderThreads()
    } else if (subView === "arcs") {
      html += this._renderArcs()
    } else if (subView === "foreshadowing") {
      html += this._renderForeshadowing()
    } else if (subView === "reveals") {
      html += this._renderReveals()
    }

    if (subView === "scenes") return `<div class="outline-scene-layout">${html}</div>`
    return html
  },

  onRendered() {
    if (state.currentSubView === "scenes") {
      sceneWorkbenchView.onRendered()
    } else if (state.currentSubView === "story-outline") {
      storyOutlineView.onRendered()
    } else {
      this._bindEvents()
    }
  },

  _renderOutlineGenerateProgress() {
    if (!this._outlineGenerateProgress) return ""
    const rangeText = this._outlineGenerateMeta
      ? `范围: 章节 ${this._outlineGenerateMeta.start_chapter || 1}-${this._outlineGenerateMeta.end_chapter || 10}`
      : "范围: 所选章节"
    const reviewAction = this._outlineGeneratePreview
      ? `<div class="outline-preview-ready" role="status">
          <span>建议尚未写入工作结构。请先检查和编辑，再明确采用。</span>
          <button class="btn btn-sm btn-primary" data-action="view-outline-generate-preview">查看并采用</button>
        </div>`
      : ""
    return `<div class="outline-progress-card-wrap">${renderWorkflowCard(this._outlineGenerateProgress, {
      title: "剧情结构建议",
      destinationLabel: rangeText,
    })}${reviewAction}</div>`
  },

  _stopOutlineGeneratePolling() {
    if (this._outlineGeneratePoller?.stop) this._outlineGeneratePoller.stop()
    this._outlineGeneratePoller = null
  },

  _recoverOutlineGenerateWorkflow() {
    if (!state.currentProjectId || this._outlineGeneratePreview || this._outlineGeneratePoller) return
    const workflow = recoverActiveWorkflows(state.currentProjectId)
      .find((item) => item.workflowType === "outline_generate")
    if (!workflow?.taskId) return
    this._outlineGenerateTaskId = workflow.taskId
    this._outlineGenerateMeta = { ...(workflow.meta || {}) }
    this._outlineGenerateProgress = this._outlineGenerateProgress || normalizeTaskProgress({
      id: workflow.taskId,
      task_id: workflow.taskId,
      task_type: "outline_generate",
      status: "pending",
      meta: workflow.meta || {},
    }, "outline_generate")
    this._startOutlineGeneratePolling(workflow.taskId)
  },

  _startOutlineGeneratePolling(taskId) {
    this._stopOutlineGeneratePolling()
    this._outlineGeneratePoller = pollTaskProgress({
      taskId,
      workflowType: "outline_generate",
      apiClient: api,
      onUpdate: (progress) => {
        this._outlineGenerateProgress = progress
        router.renderCurrentView()
      },
      onDone: (progress, task) => {
        this._outlineGeneratePoller = null
        this._outlineGenerateProgress = progress
        const preview = this._captureOutlineGeneratePreview(task, progress)
        if (preview) {
          toast("剧情结构建议已生成，请检查后再采用", "info")
        } else {
          clearActiveWorkflow(progress.taskId || taskId)
          this._outlineGenerateTaskId = null
          toast("剧情结构生成完成，但没有可采用的建议", "info")
        }
        router.renderCurrentView()
      },
      onFailed: (progress) => {
        this._outlineGeneratePoller = null
        this._outlineGenerateProgress = progress
        clearActiveWorkflow(progress.taskId || taskId)
        this._outlineGenerateTaskId = null
        toast(`剧情结构建议生成失败: ${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
  },

  _captureOutlineGeneratePreview(task, progress = this._outlineGenerateProgress) {
    if (task?.task_type && task.task_type !== "outline_generate") {
      this._outlineGeneratePreview = null
      return null
    }
    const result = task?.result || progress?.raw?.result || {}
    if (result.apply_status === "applied" || result.requires_apply !== true || !result.draft_structure) {
      this._outlineGeneratePreview = null
      return null
    }
    const sourceTaskId = result.source_task_id || task?.task_id || task?.id || progress?.taskId || this._outlineGenerateTaskId
    const contextConfirmationId = result.context_confirmation_id || this._outlineGenerateMeta?.context_confirmation_id
    if (!sourceTaskId || !contextConfirmationId) {
      this._outlineGeneratePreview = null
      return null
    }
    this._outlineGenerateTaskId = sourceTaskId
    this._outlineGeneratePreview = {
      sourceTaskId,
      contextConfirmationId,
      draftStructure: JSON.parse(JSON.stringify(result.draft_structure)),
      warnings: Array.isArray(result.warnings) ? result.warnings : [],
    }
    return this._outlineGeneratePreview
  },

  _resetOutlineGenerateState() {
    this._stopOutlineGeneratePolling()
    this._outlineGenerateTaskId = null
    this._outlineGenerateProgress = null
    this._outlineGenerateMeta = null
    this._outlineGeneratePreview = null
  },

  _stopOutlineAnalysisPolling() {
    if (this._outlineAnalysisPoller?.stop) this._outlineAnalysisPoller.stop()
    this._outlineAnalysisPoller = null
  },

  _syncOutlineAnalysisProject() {
    const analysisProjectId = this._outlineAnalysisMeta?.project_id
    if (analysisProjectId && analysisProjectId !== state.currentProjectId) {
      this._resetOutlineAnalysisState({ clearWorkflow: false })
    }
  },

  _recoverOutlineAnalysisWorkflow() {
    if (!state.currentProjectId || this._outlineAnalysisResult || this._outlineAnalysisPoller) return
    const workflows = recoverActiveWorkflows(state.currentProjectId)
      .filter((item) => (
        item.workflowType === "outline_analyze"
        && item.projectId === state.currentProjectId
      ))
      .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))
    const workflow = workflows[0]
    if (!workflow?.taskId) return
    this._outlineAnalysisTaskId = workflow.taskId
    this._outlineAnalysisMeta = {
      ...(workflow.meta || {}),
      project_id: workflow.projectId || state.currentProjectId,
    }
    this._outlineAnalysisProgress = this._outlineAnalysisProgress || normalizeTaskProgress({
      id: workflow.taskId,
      task_id: workflow.taskId,
      task_type: "outline_analyze",
      status: "pending",
      meta: workflow.meta || {},
    }, "outline_analyze")
    this._startOutlineAnalysisPolling(
      workflow.taskId,
      this._outlineAnalysisMeta.project_id,
    )
  },

  _startOutlineAnalysisPolling(taskId, projectId = state.currentProjectId) {
    this._stopOutlineAnalysisPolling()
    this._outlineAnalysisPoller = pollTaskProgress({
      taskId,
      workflowType: "outline_analyze",
      novelId: projectId,
      apiClient: api,
      onUpdate: (progress) => {
        if (
          this._outlineAnalysisTaskId !== taskId
          || this._outlineAnalysisMeta?.project_id !== projectId
        ) return
        this._outlineAnalysisProgress = progress
        if (state.currentProjectId === projectId) router.renderCurrentView()
      },
      onDone: (progress, task) => {
        if (
          this._outlineAnalysisTaskId !== taskId
          || this._outlineAnalysisMeta?.project_id !== projectId
        ) return
        this._outlineAnalysisPoller = null
        this._outlineAnalysisCancelPending = false
        this._outlineAnalysisProgress = progress
        const analysis = task?.result?.analysis ?? progress?.raw?.result?.analysis
        if (typeof analysis === "string" && analysis.trim()) {
          this._outlineAnalysisResult = {
            markdown: analysis,
            contextSummary: this._outlineAnalysisMeta?.context_summary || {},
          }
          toast("大纲分析已完成", "success")
        } else {
          clearActiveWorkflow(progress.taskId || taskId)
          this._outlineAnalysisTaskId = null
          toast("大纲分析完成，但没有返回可展示的内容", "info")
        }
        if (state.currentProjectId === projectId) router.renderCurrentView()
      },
      onFailed: (progress) => {
        if (
          this._outlineAnalysisTaskId !== taskId
          || this._outlineAnalysisMeta?.project_id !== projectId
        ) return
        this._outlineAnalysisPoller = null
        this._outlineAnalysisCancelPending = false
        this._outlineAnalysisProgress = progress
        if (state.currentProjectId === projectId) {
          if (progress.cancelled) {
            toast("大纲分析任务已取消", "warning")
          } else {
            toast(`大纲分析失败: ${progress.errorMessage || "未知错误"}`, "error")
          }
          router.renderCurrentView()
        }
      },
    })
  },

  _resetOutlineAnalysisState({ clearWorkflow = true } = {}) {
    this._stopOutlineAnalysisPolling()
    if (clearWorkflow && this._outlineAnalysisTaskId) {
      clearActiveWorkflow(this._outlineAnalysisTaskId)
    }
    this._outlineAnalysisTaskId = null
    this._outlineAnalysisProgress = null
    this._outlineAnalysisMeta = null
    this._outlineAnalysisResult = null
    this._outlineAnalysisCancelPending = false
  },

  _outlineAnalysisContextSummary(confirmation) {
    const sections = Array.isArray(confirmation?.sections)
      ? confirmation.sections.map((section) => ({
        key: String(section?.key || ""),
        title: String(section?.title || section?.key || "参考资料"),
        sources: Array.isArray(section?.sources)
          ? section.sources.slice(0, 6).map((source) => String(source?.label || source?.id || "")).filter(Boolean)
          : [],
        sourceCount: Array.isArray(section?.sources) ? section.sources.length : 0,
      }))
      : []
    return {
      sections,
      warnings: Array.isArray(confirmation?.warnings)
        ? confirmation.warnings.map((warning) => String(warning))
        : [],
    }
  },

  _renderOutlineAnalysisResult() {
    if (!this._outlineAnalysisResult?.markdown) return ""
    const summary = this._outlineAnalysisResult.contextSummary || {}
    const sectionItems = (summary.sections || []).map((section) => {
      const sourceText = section.sources?.length
        ? `：${section.sources.join("、")}${section.sourceCount > section.sources.length ? ` 等 ${section.sourceCount} 项` : ""}`
        : ""
      return `<li><strong>${esc(section.title)}</strong>${esc(sourceText)}</li>`
    }).join("")
    const warningItems = (summary.warnings || [])
      .map((warning) => `<li>${esc(warning)}</li>`)
      .join("")
    const contextDetails = sectionItems || warningItems
      ? `<details class="outline-analysis-context">
          <summary>本次已确认参考资料</summary>
          ${sectionItems ? `<ul>${sectionItems}</ul>` : ""}
          ${warningItems ? `<div class="form-hint">编译提示</div><ul>${warningItems}</ul>` : ""}
        </details>`
      : ""
    return `
      <section class="outline-analysis-result" aria-labelledby="outline-analysis-result-title">
        <div class="section-header">
          <div>
            <h3 id="outline-analysis-result-title">AI 大纲分析</h3>
            <p class="form-hint">只读分析，不会写入或修改任何大纲资产。</p>
          </div>
          <button class="btn btn-sm btn-ghost" data-action="dismiss-outline-analysis">收起结果</button>
        </div>
        ${contextDetails}
        <pre class="generate-markdown-pre outline-analysis-markdown">${esc(this._outlineAnalysisResult.markdown)}</pre>
      </section>
    `
  },

  _renderPlotAutoExtractProgress() {
    if (!this._plotAutoExtractProgress) return ""
    const rangeText = this._plotAutoExtractMeta
      ? `范围: 章节 ${this._plotAutoExtractMeta.start_chapter || 1}-${this._plotAutoExtractMeta.end_chapter || 10}`
      : "范围: 所选章节"
    return `<div class="outline-progress-card-wrap">${renderWorkflowCard(this._plotAutoExtractProgress, {
      title: this._plotAutoExtractMeta?.label || "剧情线自动提取",
      destinationLabel: rangeText,
    })}</div>`
  },

  _stopPlotAutoExtractPolling() {
    if (this._plotAutoExtractPoller?.stop) this._plotAutoExtractPoller.stop()
    this._plotAutoExtractPoller = null
  },

  _startPlotAutoExtractPolling(taskId) {
    this._stopPlotAutoExtractPolling()
    this._plotAutoExtractPoller = pollTaskProgress({
      taskId,
      workflowType: "plot_structure_auto_extraction",
      apiClient: api,
      onUpdate: (progress) => {
        this._plotAutoExtractProgress = progress
        router.renderCurrentView()
      },
      onDone: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._plotAutoExtractTaskId = null
        toast(`${this._plotAutoExtractMeta?.label || "剧情线自动提取"}完成`, "success")
        await this.onEnter?.()
        router.refresh()
      },
      onFailed: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._plotAutoExtractTaskId = null
        toast(`${this._plotAutoExtractMeta?.label || "剧情线自动提取"}失败: ${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
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
      draft: "未标注",
    }
    return map[tag] || tag || "未标注"
  },

  _structureFilterFor(subView = state.currentSubView || "threads") {
    if (!this._structureFilters[subView]) {
      this._structureFilters[subView] = { ...STRUCTURE_FILTER_DEFAULTS }
    }
    return this._structureFilters[subView]
  },

  _structureFilterParams(subView = state.currentSubView || "threads") {
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) {
      return {}
    }
    const filters = this._structureFilterFor(subView)
    const params = {
      skip: filters.skip,
      limit: filters.limit,
    }
    if (filters.status) params.status = filters.status
    if (filters.source) params.source = filters.source
    if (filters.workflow_id) params.workflow_id = filters.workflow_id
    if (filters.needs_review === "true") params.needs_review = true
    if (filters.needs_review === "false") params.needs_review = false
    return params
  },

  _structureStatusOptions(subView) {
    if (subView === "foreshadowing") {
      return FORESHADOWING_STATUSES.map((status) => [status, FORESHADOWING_STATUS_LABELS[status] || status])
    }
    if (subView === "reveals") {
      return REVEAL_STATUSES.map((status) => [status, REVEAL_STATUS_LABELS[status] || status])
    }
    return [
      ["canonical", "已采用"],
      ["draft", "工作稿"],
      ["candidate", "待处理"],
      ["deprecated", "历史"],
    ]
  },

  _renderStructureFilters(subView) {
    const filters = this._structureFilterFor(subView)
    const workflowFilterActive = Boolean(filters.workflow_id)
    return `
      <div class="scene-management-filters" aria-label="结构资产筛选">
        ${this._structureFilterSelect("outline-filter-status", "状态", filters.status, this._structureStatusOptions(subView), "全部状态")}
        ${this._structureFilterSelect("outline-filter-source", "来源", filters.source, STRUCTURE_SOURCE_OPTIONS, "全部来源")}
        ${this._structureFilterSelect("outline-filter-needs-review", "注意", filters.needs_review, [["true", "需要人工检查"], ["false", "无注意项"]], "全部注意原因")}
        <details class="outline-structure-diagnostic-filters" ${workflowFilterActive ? "open" : ""}>
          <summary>诊断筛选${workflowFilterActive ? "（1）" : ""}</summary>
          <label class="scene-filter-field scene-filter-field--wide">
            <span>Workflow 诊断 ID</span>
            <input class="form-input" id="outline-filter-workflow-id" data-diagnostic-field value="${esc(filters.workflow_id)}" placeholder="按 workflow_id 精确筛选" />
          </label>
        </details>
        <div class="scene-filter-actions">
          <button class="btn btn-sm btn-primary" data-action="apply-outline-structure-filters">应用</button>
          <button class="btn btn-sm" data-action="reset-outline-structure-filters">重置</button>
        </div>
      </div>
    `
  },

  _renderStructurePagination(subView) {
    const filters = this._structureFilterFor(subView)
    const total = this._structureTotals[subView] || 0
    if (total <= filters.limit) return ""
    const currentPage = Math.floor(filters.skip / filters.limit) + 1
    const totalPages = Math.ceil(total / filters.limit)
    const prevDisabled = filters.skip <= 0 ? "disabled" : ""
    const nextDisabled = filters.skip + filters.limit >= total ? "disabled" : ""
    return `
      <div class="outline-structure-pagination">
        <button class="btn btn-sm" data-action="prev-outline-structure-page" ${prevDisabled}>上一页</button>
        <span class="outline-structure-pagination__info">第 ${currentPage} / ${totalPages} 页，共 ${esc(total)} 条</span>
        <button class="btn btn-sm" data-action="next-outline-structure-page" ${nextDisabled}>下一页</button>
      </div>
    `
  },

  _structureFilterSelect(id, label, value, options, emptyLabel) {
    return `
      <label class="scene-filter-field">
        <span>${esc(label)}</span>
        <select class="form-select" id="${esc(id)}">
          <option value="">${esc(emptyLabel)}</option>
          ${options.map(([optionValue, optionLabel]) => `
            <option value="${esc(optionValue)}" ${optionValue === value ? "selected" : ""}>${esc(optionLabel)}</option>
          `).join("")}
        </select>
      </label>
    `
  },

  _assetProvenance(asset) {
    return asset?.provenance_meta && typeof asset.provenance_meta === "object"
      ? asset.provenance_meta
      : {}
  },

  _renderStructureAssetBadges(asset) {
    const meta = this._assetProvenance(asset)
    const badges = []
    const source = meta.source || asset.source
    if (source === "deep_import") badges.push('<span class="badge badge-info">深度导入</span>')
    else if (source === "manual") badges.push('<span class="badge">手动</span>')
    else if (source) badges.push(`<span class="badge">${esc(source)}</span>`)
    for (const reason of assetAttentionReasons(asset)) {
      badges.push(`<span class="badge badge-warning">${esc(reason)}</span>`)
    }
    if (meta.phase) badges.push(`<span class="badge">${esc(meta.phase)}</span>`)
    return badges.length ? `<div class="structure-asset-badges">${badges.join("")}</div>` : ""
  },

  _structureReviewState(asset) {
    const meta = this._assetProvenance(asset)
    return {
      reviewed: Boolean(meta.reviewed_at),
      needsReview: meta.needs_review === true,
    }
  },

  _renderThreadReviewAction(thread) {
    const id = thread?.id || thread?.thread_id
    if (!id) return ""
    const review = this._structureReviewState(thread)
    if (review.reviewed) return ""
    const display = structureAssetDisplay(thread)
    if (display.displayState === "active" && !review.needsReview) return ""
    const primary = review.needsReview ? "btn-primary" : ""
    const label = display.displayState === "active" ? "标记已检查" : "采用"
    return `<button class="btn btn-sm ${primary}" data-action="mark-thread-reviewed" data-id="${esc(id)}">${label}</button>`
  },

  _reviewThreadPayload(thread, reviewedFrom) {
    const meta = {
      ...this._assetProvenance(thread),
      needs_review: false,
      reviewed_at: new Date().toISOString(),
      reviewed_by: "manual",
      reviewed_from: reviewedFrom,
    }
    if (!meta.review_previous_status && thread?.status && thread.status !== "canonical") {
      meta.review_previous_status = thread.status
    }
    return {
      status: "canonical",
      provenance_meta: meta,
    }
  },

  _unreviewThreadPayload(thread) {
    const meta = { ...this._assetProvenance(thread), needs_review: true }
    const restoreStatus = meta.review_previous_status || "draft"
    delete meta.reviewed_at
    delete meta.reviewed_by
    delete meta.reviewed_from
    delete meta.review_previous_status
    return {
      status: restoreStatus,
      provenance_meta: meta,
    }
  },

  _renderStructureEmptyState(kind, subView) {
    const filters = this._structureFilterFor(subView)
    const filteredDeepImport = filters.source === "deep_import" || Boolean(filters.workflow_id)
    const detail = filteredDeepImport
      ? "结构分析不完整或无匹配结果，可重新分析，或重置筛选查看其他结构资产。"
      : `${kind}用于整理深度导入和人工维护后的叙事结构。`
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128204;</div>
        <p>暂无${esc(kind)}。</p>
        <p class="outline-empty-detail">${esc(detail)}</p>
        <button class="btn btn-sm btn-primary" data-action="nav-scenes">从已采用 Scene 开始整理</button>
      </div>
    `
  },

  _setStructureLoadError(subView, err) {
    const labels = {
      threads: "剧情线",
      arcs: "篇章纲",
      foreshadowing: "伏笔",
      reveals: "揭示",
    }
    const message = typeof err?.message === "string" ? err.message.trim() : ""
    this._structureLoadErrors[subView] = message || `${labels[subView] || "结构数据"}加载失败`
  },

  _renderStructureLoadError(subView) {
    return `
      <div class="empty-state" role="alert">
        <div class="empty-icon">!</div>
        <p>加载失败</p>
        <p class="outline-empty-detail">${esc(this._structureLoadErrors[subView])}</p>
        <button class="btn btn-sm" data-action="retry-outline-load">重新加载</button>
      </div>
    `
  },

  _renderProjectChip() {
    const title = state.currentProject?.title || state.currentProject?.name
    if (!title) return ""
    return `<span class="view-toolbar__project" title="${esc(title)}">${esc(title)}</span>`
  },

  _plotAutoExtractLabel(subView = state.currentSubView || "threads") {
    return subView === "arcs" ? "篇章纲自动提取" : "剧情线自动提取"
  },

  _renderPlotAutoExtractAction(subView = state.currentSubView || "threads") {
    return `
      <button class="btn btn-sm" data-action="plot-structure-auto-extract">${esc(this._plotAutoExtractLabel(subView))}</button>
    `
  },

  _renderOutlineProgressStatus() {
    const parts = []
    if (this._outlineAnalysisProgress) {
      const rangeText = this._outlineAnalysisMeta
        ? `范围: 章节 ${this._outlineAnalysisMeta.start_chapter || 1}-${this._outlineAnalysisMeta.end_chapter || this._outlineAnalysisMeta.start_chapter || 1}`
        : "范围: 所选章节"
      const card = renderWorkflowCard(this._outlineAnalysisProgress, {
        title: "AI 大纲分析",
        destinationLabel: rangeText,
        className: "outline-progress-mini",
        actionsHtml: (
          !this._outlineAnalysisProgress.terminal
          && this._outlineAnalysisProgress.availableActions?.includes("cancel")
        )
          ? `<div class="workflow-progress__actions"><button class="btn btn-sm btn-ghost" data-action="cancel-outline-analysis" ${this._outlineAnalysisCancelPending ? "disabled" : ""}>${this._outlineAnalysisCancelPending ? "取消中..." : "取消任务"}</button></div>`
          : "",
      })
      const dismiss = this._outlineAnalysisProgress.terminal && !this._outlineAnalysisResult
        ? '<button class="btn btn-sm btn-ghost" data-action="dismiss-outline-analysis">关闭任务</button>'
        : ""
      parts.push(`<div class="outline-analysis-progress">${card}${dismiss}</div>`)
    }
    if (this._outlineGenerateProgress) {
      const rangeText = this._outlineGenerateMeta
        ? `范围: 章节 ${this._outlineGenerateMeta.start_chapter || 1}-${this._outlineGenerateMeta.end_chapter || 10}`
        : "范围: 所选章节"
      parts.push(renderWorkflowCard(this._outlineGenerateProgress, {
        title: "剧情结构建议",
        destinationLabel: rangeText,
        className: "outline-progress-mini",
      }))
    }
    if (this._plotAutoExtractProgress) {
      const rangeText = this._plotAutoExtractMeta
        ? `范围: 章节 ${this._plotAutoExtractMeta.start_chapter || 1}-${this._plotAutoExtractMeta.end_chapter || 10}`
        : "范围: 所选章节"
      parts.push(renderWorkflowCard(this._plotAutoExtractProgress, {
        title: this._plotAutoExtractMeta?.label || "剧情线自动提取",
        destinationLabel: rangeText,
        className: "outline-progress-mini",
      }))
    }
    return parts.join("")
  },

  _renderOutlineToolbar() {
    const status = this._renderOutlineProgressStatus()
    const result = this._renderOutlineAnalysisResult()
    return `${status ? `<div class="outline-toolbar-status">${status}</div>` : ""}${result}`
  },

  _threadDescription(thread) {
    return thread?.description || thread?.summary || thread?.visible_goal || thread?.hidden_truth || "-"
  },

  _arcDescription(arc) {
    return arc?.description || arc?.summary || arc?.arc_goal || arc?.core_conflict || "-"
  },

  _renderThreads() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = this._renderOutlineToolbar() + this._renderStructureFilters("threads")

    if (this._threads.length === 0) {
      return html + this._renderStructureEmptyState("剧情线", "threads")
    }
    const scope = "outline-threads"
    const ids = this._threads.map((item) => item.id || item.thread_id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)

    html += renderBulkToolbar(this, scope, [
      { action: "review-threads", label: "批量采用 / 标记已检查", className: "btn-primary" },
      { action: "delete-threads", label: "批量删除", className: "btn-danger" },
    ], { noun: "剧情线" }) + `
      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前剧情线")}</th>
            <th>状态</th>
            <th>名称</th>
            <th>类型</th>
            <th>标记</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const t of this._threads) {
      const safeStatus = allowedStatuses.has(t.status) ? t.status : "draft"
      const display = structureAssetDisplay({ ...t, status: safeStatus })
      const statusClass = displayStateBadgeClass(display.displayState)
      html += `
        <tr class="outline-structure-row" data-id="${esc(t.id || t.thread_id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, t.id || t.thread_id, `选择 ${t.name || t.title || "剧情线"}`)}</td>
          <td data-label="状态"><span class="badge ${statusClass}">${esc(display.label)}</span></td>
          <td data-label="名称">${esc(t.name || t.title)}</td>
          <td data-label="类型" class="outline-asset-meta">${esc(t.thread_type || "-")}</td>
          <td data-label="标记">${this._renderStructureAssetBadges(t) || "-"}</td>
          <td data-label="描述" class="outline-asset-description">${esc(this._threadDescription(t))}</td>
          <td data-label="操作">
            ${this._renderThreadReviewAction(t)}
            <button class="btn btn-sm btn-primary" data-action="edit-thread" data-id="${esc(t.id || t.thread_id)}">编辑</button>
            ${renderActionMenu(`thread-actions-${esc(t.id || t.thread_id)}`, [
              { action: "delete-thread", label: "删除", class: "danger", data: { id: t.id || t.thread_id } },
            ])}
          </td>
        </tr>
      `
    }

    html += "</tbody></table>"
    html += this._renderStructurePagination("threads")
    return html
  },

  _renderArcs() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = this._renderOutlineToolbar() + this._renderStructureFilters("arcs")

    if (this._arcs.length === 0) {
      return html + this._renderStructureEmptyState("篇章纲", "arcs")
    }
    const scope = "outline-arcs"
    const ids = this._arcs.map((item) => item.id || item.arc_id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)

    html += renderBulkToolbar(this, scope, [
      { action: "delete-arcs", label: "批量删除", className: "btn-danger" },
    ], { noun: "篇章纲" }) + `
      <table class="data-table table-card-list">
        <thead>
          <tr>
            <th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前篇章纲")}</th>
            <th>状态</th>
            <th>名称</th>
            <th>章节范围</th>
            <th>标记</th>
            <th>描述</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
    `

    const allowedStatuses = ENTITY_ALLOWED_STATUSES

    for (const a of this._arcs) {
      const safeStatus = allowedStatuses.has(a.status) ? a.status : "draft"
      const display = structureAssetDisplay({ ...a, status: safeStatus })
      const statusClass = displayStateBadgeClass(display.displayState)
      const range = a.start_chapter != null && a.end_chapter != null
        ? `${a.start_chapter}-${a.end_chapter}`
        : "-"
      html += `
        <tr class="outline-structure-row" data-id="${esc(a.id || a.arc_id)}">
          <td class="selection-cell">${renderSelectionCell(this, scope, a.id || a.arc_id, `选择 ${a.name || a.title || "篇章纲"}`)}</td>
          <td data-label="状态"><span class="badge ${statusClass}">${esc(display.label)}</span></td>
          <td data-label="名称">${esc(a.name || a.title)}</td>
          <td data-label="章节范围" class="outline-asset-mono">${esc(range)}</td>
          <td data-label="标记">${this._renderStructureAssetBadges(a) || "-"}</td>
          <td data-label="描述" class="outline-asset-description">${esc(this._arcDescription(a))}</td>
          <td data-label="操作">
            <button class="btn btn-sm btn-primary" data-action="edit-arc" data-id="${esc(a.id || a.arc_id)}">编辑</button>
            ${renderActionMenu(`arc-actions-${esc(a.id || a.arc_id)}`, [
              { action: "delete-arc", label: "删除", class: "danger", data: { id: a.id || a.arc_id } },
            ])}
          </td>
        </tr>
      `
    }

    html += "</tbody></table>"
    html += this._renderStructurePagination("arcs")
    return html
  },

  _renderForeshadowing() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = this._renderOutlineToolbar() + this._renderStructureFilters("foreshadowing")

    if (this._foreshadowing.length === 0) {
      return html + this._renderStructureEmptyState("伏笔", "foreshadowing")
    }

    const scope = "outline-foreshadowing"
    const ids = this._foreshadowing.map((item) => item.id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)
    let tableHtml = renderBulkToolbar(this, scope, [
      { action: "delete-foreshadowing", label: "批量删除", className: "btn-danger" },
    ], { noun: "伏笔" })
    tableHtml += `<table class="data-table table-card-list"><thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前伏笔")}</th><th>状态</th><th>描述</th><th>目标章节</th><th>标记</th><th>操作</th></tr></thead><tbody>`
    for (const f of this._foreshadowing) {
      const st = FORESHADOWING_STATUS_LABELS[f.status] || f.status
      const description = f.summary || f.name || "-"
      tableHtml += `<tr class="outline-structure-row" data-id="${esc(f.id)}">
        <td class="selection-cell">${renderSelectionCell(this, scope, f.id, `选择 ${description}`)}</td>
        <td data-label="状态"><span class="badge badge-${esc(f.status || "planted")}">${esc(st)}</span></td>
        <td data-label="描述" class="outline-asset-description">${esc(description)}</td>
        <td data-label="目标章节" class="outline-asset-mono">${f.planned_seed_chapter != null ? esc(String(f.planned_seed_chapter)) : "-"}</td>
        <td data-label="标记">${this._renderStructureAssetBadges(f) || "-"}</td>
        <td data-label="操作">
          <select class="form-select foreshadowing-status-select outline-status-select" data-id="${esc(f.id)}">
            ${FORESHADOWING_STATUSES.map((s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${FORESHADOWING_STATUS_LABELS[s] || s}</option>`).join("")}
          </select>
          <button class="btn btn-sm btn-primary" data-action="edit-foreshadowing" data-id="${esc(f.id)}">编辑</button>
          ${renderActionMenu(`foreshadowing-actions-${esc(f.id)}`, [
            { action: "delete-foreshadowing", label: "删除", class: "danger", data: { id: f.id } },
          ])}
        </td>
      </tr>`
    }
    tableHtml += '</tbody></table>'
    tableHtml += this._renderStructurePagination("foreshadowing")
    return html + tableHtml
  },

  _renderReveals() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目，或创建一个新项目开始。</p></div>'
    }

    let html = this._renderOutlineToolbar() + this._renderStructureFilters("reveals")

    if (this._reveals.length === 0) {
      return html + this._renderStructureEmptyState("揭示", "reveals")
    }

    const scope = "outline-reveals"
    const ids = this._reveals.map((item) => item.id).filter(Boolean)
    reconcileBulkSelection(this, scope, ids)
    html += renderBulkToolbar(this, scope, [
      { action: "delete-reveals", label: "批量删除", className: "btn-danger" },
    ], { noun: "揭示" })
    html += `<table class="data-table table-card-list"><thead><tr><th class="selection-cell">${renderSelectionHeader(this, scope, ids, "全选当前揭示")}</th><th>状态</th><th>描述</th><th>揭示章节</th><th>标记</th><th>操作</th></tr></thead><tbody>`
    for (const r of this._reveals) {
      const st = REVEAL_STATUS_LABELS[r.status] || r.status || "计划中"
      const revealChapter = (r.reveal_stages && r.reveal_stages[0] && r.reveal_stages[0].chapter_index) || "-"
      html += `<tr class="outline-structure-row" data-id="${esc(r.id)}">
        <td class="selection-cell">${renderSelectionCell(this, scope, r.id, "选择揭示")}</td>
        <td data-label="状态"><span class="badge badge-${esc(r.status || "planned")}">${esc(st)}</span></td>
        <td data-label="描述" class="outline-asset-description">${esc(r.secret_summary || "-")}</td>
        <td data-label="揭示章节" class="outline-asset-mono">${revealChapter !== "-" ? esc(String(revealChapter)) : "-"}</td>
        <td data-label="标记">${this._renderStructureAssetBadges(r) || "-"}</td>
        <td data-label="操作">
          <select class="form-select reveal-status-select outline-status-select" data-id="${esc(r.id)}">
            ${REVEAL_STATUSES.map((s) => `<option value="${s}" ${r.status === s ? "selected" : ""}>${REVEAL_STATUS_LABELS[s] || s}</option>`).join("")}
          </select>
          <button class="btn btn-sm btn-primary" data-action="edit-reveal" data-id="${esc(r.id)}">编辑</button>
          ${renderActionMenu(`reveal-actions-${esc(r.id)}`, [
            { action: "delete-reveal", label: "删除", class: "danger", data: { id: r.id } },
          ])}
        </td>
      </tr>`
    }
    html += '</tbody></table>'
    html += this._renderStructurePagination("reveals")
    return html
  },

  _showCreateForeshadowingForm() {
    const defaultChapter = this._guessLastChapter() || 1
    const statusOptions = FORESHADOWING_STATUSES.map(
      (s) => `<option value="${s}">${FORESHADOWING_STATUS_LABELS[s] || s}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="create-foreshadowing-description" rows="3" placeholder="伏笔描述"></textarea>
      </div>
      <div class="form-group">
        <label>目标章节</label>
        <input class="form-input" id="create-foreshadowing-target-chapter" type="number" min="1" value="${defaultChapter}" />
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="create-foreshadowing-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("新建伏笔", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const description = document.getElementById("create-foreshadowing-description")?.value?.trim()
        if (!description) { toast("请输入描述", "warning"); return }
        const targetChapter = parseInt(document.getElementById("create-foreshadowing-target-chapter")?.value || "1", 10)
        try {
          await api.outline.createForeshadowing(state.currentProjectId, {
            name: description,
            summary: description,
            planned_seed_chapter: Number.isInteger(targetChapter) && targetChapter >= 1 ? targetChapter : 1,
            status: document.getElementById("create-foreshadowing-status")?.value || "planted",
          })
          toast("伏笔已创建", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "创建失败", "error")
        }
      },
    }])
  },

  _editForeshadowing(id) {
    const f = this._foreshadowing.find((item) => item.id === id)
    if (!f) return

    const description = f.summary || f.name || ""
    const targetChapter = f.planned_seed_chapter || this._guessLastChapter() || 1
    const statusOptions = FORESHADOWING_STATUSES.map(
      (s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${FORESHADOWING_STATUS_LABELS[s] || s}</option>`
    ).join("")

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="edit-foreshadowing-description" rows="3">${esc(description)}</textarea>
      </div>
      <div class="form-group">
        <label>目标章节</label>
        <input class="form-input" id="edit-foreshadowing-target-chapter" type="number" min="1" value="${targetChapter}" />
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="edit-foreshadowing-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("编辑伏笔", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        const description = document.getElementById("edit-foreshadowing-description")?.value?.trim()
        if (!description) { toast("请输入描述", "warning"); return }
        const targetChapter = parseInt(document.getElementById("edit-foreshadowing-target-chapter")?.value || "1", 10)
        try {
          await api.outline.updateForeshadowing(id, state.currentProjectId, {
            name: description,
            summary: description,
            planned_seed_chapter: Number.isInteger(targetChapter) && targetChapter >= 1 ? targetChapter : 1,
            status: document.getElementById("edit-foreshadowing-status")?.value || "planted",
          })
          toast("伏笔已保存", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "保存失败", "error")
        }
      },
    }])
  },

  async _deleteForeshadowing(id) {
    confirmAction("确定删除此伏笔？", async () => {
      try {
        await api.outline.deleteForeshadowing(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) {
        toast(err.message || "删除失败", "error")
      }
    })
  },

  _showCreateRevealForm() {
    const defaultChapter = this._guessLastChapter() || 1
    const statusOptions = REVEAL_STATUSES.map(
      (s) => `<option value="${s}">${REVEAL_STATUS_LABELS[s] || s}</option>`
    ).join("")
    const foreshadowingOptions = this._buildForeshadowingOptions()

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="create-reveal-description" rows="3" placeholder="揭示的秘密"></textarea>
      </div>
      <div class="form-group">
        <label>揭示章节 *</label>
        <input class="form-input" id="create-reveal-chapter" type="number" min="1" value="${defaultChapter}" />
      </div>
      <div class="form-group">
        <label>关联伏笔（可选）</label>
        <select class="form-select" id="create-reveal-foreshadowing-id"><option value="">- 无 -</option>${foreshadowingOptions}</select>
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="create-reveal-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("新建揭示", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const description = document.getElementById("create-reveal-description")?.value?.trim()
        const chapterValue = document.getElementById("create-reveal-chapter")?.value
        if (!description) { toast("请输入描述", "warning"); return }
        const chapterIndex = parseInt(chapterValue || "1", 10)
        if (!Number.isInteger(chapterIndex) || chapterIndex < 1) {
          toast("揭示章节必须大于 0", "warning")
          return
        }
        try {
          await api.outline.createReveal(state.currentProjectId, {
            target_type: "world_entity",
            target_id: "00000000-0000-0000-0000-000000000000",
            secret_summary: description,
            reveal_stages: [{
              stage_index: 0,
              chapter_index: chapterIndex,
              reveal_content: description,
            }],
            status: document.getElementById("create-reveal-status")?.value || "planned",
          })
          toast("揭示已创建", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "创建失败", "error")
        }
      },
    }])
  },

  _editReveal(id) {
    const r = this._reveals.find((item) => item.id === id)
    if (!r) return

    const description = r.secret_summary || ""
    const revealChapter = (r.reveal_stages && r.reveal_stages[0] && r.reveal_stages[0].chapter_index) || this._guessLastChapter() || 1
    const statusOptions = REVEAL_STATUSES.map(
      (s) => `<option value="${s}" ${r.status === s ? "selected" : ""}>${REVEAL_STATUS_LABELS[s] || s}</option>`
    ).join("")
    const foreshadowingOptions = this._buildForeshadowingOptions()

    const formHtml = `
      <div class="form-group">
        <label>描述 *</label>
        <textarea class="form-textarea" id="edit-reveal-description" rows="3">${esc(description)}</textarea>
      </div>
      <div class="form-group">
        <label>揭示章节 *</label>
        <input class="form-input" id="edit-reveal-chapter" type="number" min="1" value="${revealChapter}" />
      </div>
      <div class="form-group">
        <label>关联伏笔（可选）</label>
        <select class="form-select" id="edit-reveal-foreshadowing-id"><option value="">- 无 -</option>${foreshadowingOptions}</select>
      </div>
      <div class="form-group">
        <label>状态</label>
        <select class="form-select" id="edit-reveal-status">${statusOptions}</select>
      </div>
    `
    showModalHtml("编辑揭示", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        const description = document.getElementById("edit-reveal-description")?.value?.trim()
        const chapterValue = document.getElementById("edit-reveal-chapter")?.value
        if (!description) { toast("请输入描述", "warning"); return }
        const chapterIndex = parseInt(chapterValue || "1", 10)
        if (!Number.isInteger(chapterIndex) || chapterIndex < 1) {
          toast("揭示章节必须大于 0", "warning")
          return
        }
        try {
          await api.outline.updateReveal(id, state.currentProjectId, {
            secret_summary: description,
            reveal_stages: [{
              stage_index: 0,
              chapter_index: chapterIndex,
              reveal_content: description,
            }],
            status: document.getElementById("edit-reveal-status")?.value || "planned",
          })
          toast("揭示已保存", "success")
          router.refresh()
        } catch (err) {
          toast(err.message || "保存失败", "error")
        }
      },
    }])
  },

  async _deleteReveal(id) {
    confirmAction("确定删除此揭示？", async () => {
      try {
        await api.outline.deleteReveal(id, state.currentProjectId)
        toast("已删除", "success")
        router.refresh()
      } catch (err) {
        toast(err.message || "删除失败", "error")
      }
    })
  },

  _guessLastChapter() {
    let maxChapter = 0
    for (const f of this._foreshadowing) {
      if (f.planned_seed_chapter > maxChapter) maxChapter = f.planned_seed_chapter
      if (f.planned_payoff_chapter > maxChapter) maxChapter = f.planned_payoff_chapter
    }
    for (const r of this._reveals) {
      if (r.reveal_stages) {
        for (const stage of r.reveal_stages) {
          if (stage.chapter_index > maxChapter) maxChapter = stage.chapter_index
        }
      }
    }
    for (const a of this._arcs) {
      if (a.end_chapter > maxChapter) maxChapter = a.end_chapter
      if (a.start_chapter > maxChapter) maxChapter = a.start_chapter
    }
    for (const t of this._threads) {
      if (t.planned_payoff_chapter > maxChapter) maxChapter = t.planned_payoff_chapter
      if (t.start_chapter > maxChapter) maxChapter = t.start_chapter
    }
    return maxChapter > 0 ? maxChapter : null
  },

  _buildForeshadowingOptions() {
    return this._foreshadowing.map(
      (f) => `<option value="${esc(f.id)}">${esc(f.summary || f.name || "未命名")}</option>`
    ).join("")
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
    showModalHtml("新建剧情线", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const name = document.getElementById("create-thread-name")?.value
        if (!name) { toast("请输入名称", "warning"); return }
        try {
          await api.outline.createThread(state.currentProjectId, {
            name,
            thread_type: document.getElementById("create-thread-type")?.value || "main",
            summary: document.getElementById("create-thread-desc")?.value || "",
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
        <textarea class="form-textarea" id="edit-thread-desc" rows="3">${esc(this._threadDescription(thread) === "-" ? "" : this._threadDescription(thread))}</textarea>
      </div>
    `
    showModalHtml("编辑剧情线", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateThread(id, state.currentProjectId, {
            name: document.getElementById("edit-thread-name")?.value,
            thread_type: document.getElementById("edit-thread-type")?.value,
            summary: document.getElementById("edit-thread-desc")?.value,
          })
          toast("已保存", "success")
          router.refresh()
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  _findThread(id) {
    return this._threads.find((thread) => (thread.id || thread.thread_id) === id) || null
  },

  async _markThreadReviewed(id) {
    const thread = this._findThread(id)
    if (!thread) {
      toast("未找到目标剧情线", "error")
      return
    }
    await api.outline.updateThread(
      id,
      state.currentProjectId,
      this._reviewThreadPayload(thread, "outline_threads"),
    )
    toast(structureAssetDisplay(thread).displayState === "active" ? "剧情线已标记为已检查" : "剧情线已采用", "success")
    await this._refreshCurrentSubViewInPlace()
  },

  async _markThreadUnreviewed(id) {
    const thread = this._findThread(id)
    if (!thread) {
      toast("未找到目标剧情线", "error")
      return
    }
    await api.outline.updateThread(
      id,
      state.currentProjectId,
      this._unreviewThreadPayload(thread),
    )
    toast("剧情线已标记为需要人工检查", "success")
    await this._refreshCurrentSubViewInPlace()
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
    showModalHtml("新建篇章纲", formHtml, [{
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
        <textarea class="form-textarea" id="edit-arc-desc" rows="3">${esc(this._arcDescription(arc) === "-" ? "" : this._arcDescription(arc))}</textarea>
      </div>
    `
    showModalHtml("编辑篇章纲", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.outline.updateArc(id, state.currentProjectId, {
            title: document.getElementById("edit-arc-name")?.value?.trim(),
            start_chapter: parseInt(document.getElementById("edit-arc-start")?.value || "1", 10),
            end_chapter: parseInt(document.getElementById("edit-arc-end")?.value || "10", 10),
            arc_goal: document.getElementById("edit-arc-desc")?.value?.trim(),
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
      { value: "draft", label: "未标注（默认）" },
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
    showModalHtml("新建 Scene 卡", formHtml, [{
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
    const tagLabels = { draft: "未标注", hook: "钩子", inciting_incident: "激励事件", rising_action: "冲突升级", climax: "阶段高潮", valley: "低谷", transition: "过渡", payoff: "爽点" }
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
    showModalHtml("编辑 Scene 卡", formHtml, [{
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

  _renderOutlineGeneratePreviewField(sectionKey, index, field) {
    const [fieldKey, label, type] = field
    const item = this._outlineGeneratePreview?.draftStructure?.[sectionKey]?.[index] || {}
    const value = item[fieldKey] ?? ""
    const attrs = `data-outline-preview-key="${esc(sectionKey)}" data-outline-preview-index="${esc(index)}" data-outline-preview-field="${esc(fieldKey)}" data-outline-preview-type="${esc(type)}"`
    if (type === "textarea") {
      return `<label>${esc(label)}<textarea class="form-textarea" rows="2" ${attrs}>${esc(value)}</textarea></label>`
    }
    return `<label>${esc(label)}<input class="form-input" type="${type === "number" ? "number" : "text"}" value="${esc(value)}" ${attrs} /></label>`
  },

  _renderOutlineGeneratePreviewSection(section, sectionIndex) {
    const items = this._outlineGeneratePreview?.draftStructure?.[section.key] || []
    if (!items.length) return ""
    return `
      <details class="outline-preview-section" ${sectionIndex < 3 ? "open" : ""}>
        <summary>${esc(section.label)}（${esc(items.length)}）</summary>
        <div class="outline-preview-items">
          ${items.map((item, index) => {
            const title = item.name || item.title || item.target_name || item.thread_name || item.risk_type || item.question || `${section.label} ${index + 1}`
            return `<section class="outline-preview-item">
              <h4>${esc(title)}</h4>
              <div class="outline-preview-fields">
                ${section.fields.map((field) => this._renderOutlineGeneratePreviewField(section.key, index, field)).join("")}
              </div>
            </section>`
          }).join("")}
        </div>
      </details>
    `
  },

  _outlinePreviewAttentionText(item) {
    if (typeof item === "string") return item
    if (!item || typeof item !== "object") return String(item ?? "")
    return item.summary || item.description || item.question || item.title || item.name || "有一项需要作者判断"
  },

  _renderOutlineGeneratePreview() {
    const preview = this._outlineGeneratePreview
    if (!preview) return ""
    const draft = preview.draftStructure || {}
    const counts = OUTLINE_PREVIEW_SECTIONS
      .map((section) => [section.label, Array.isArray(draft[section.key]) ? draft[section.key].length : 0])
      .filter(([, count]) => count > 0)
    const attentionItems = [
      ...(preview.warnings || []),
      ...(Array.isArray(draft.uncertain_items) ? draft.uncertain_items.map((item) => this._outlinePreviewAttentionText(item)) : []),
    ].filter(Boolean)
    return `
      <div class="outline-generate-preview">
        <div class="outline-preview-notice">
          <strong>待处理建议</strong>
          <p>这里的内容尚未写入工作结构。你可以先修改，再点击“采用到工作结构”。</p>
          <p>${counts.length ? counts.map(([label, count]) => `${esc(label)} ${esc(count)}`).join(" · ") : "没有结构条目"}</p>
        </div>
        ${attentionItems.length ? `<section class="outline-preview-attention"><h4>需要注意</h4><ul>${attentionItems.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></section>` : ""}
        ${OUTLINE_PREVIEW_SECTIONS.map((section, index) => this._renderOutlineGeneratePreviewSection(section, index)).join("")}
      </div>
    `
  },

  _showOutlineGeneratePreview() {
    if (!this._outlineGeneratePreview) {
      toast("当前没有可采用的剧情结构建议", "warning")
      return
    }
    showModalHtml("剧情结构建议预览", this._renderOutlineGeneratePreview(), [
      {
        text: "采用到工作结构",
        class: "btn-primary",
        handler: () => this._applyOutlineGeneratePreview(),
      },
      { text: "关闭", class: "btn-ghost", handler: closeModal },
    ], { size: "full" })
  },

  _collectEditedOutlineGeneratePreview() {
    const draft = JSON.parse(JSON.stringify(this._outlineGeneratePreview?.draftStructure || {}))
    document.querySelectorAll("[data-outline-preview-key]").forEach((field) => {
      const key = field.dataset.outlinePreviewKey
      const index = Number(field.dataset.outlinePreviewIndex)
      const fieldKey = field.dataset.outlinePreviewField
      if (!Array.isArray(draft[key]) || !draft[key][index] || !fieldKey) return
      if (field.dataset.outlinePreviewType === "number") {
        const raw = field.value.trim()
        const number = raw === "" ? null : Number(raw)
        if (number !== null && (!Number.isInteger(number) || number < 1)) {
          throw new Error("章节编号必须是正整数")
        }
        draft[key][index][fieldKey] = number
      } else {
        draft[key][index][fieldKey] = field.value.trim()
      }
    })
    return draft
  },

  async _applyOutlineGeneratePreview() {
    const preview = this._outlineGeneratePreview
    if (!preview) return false
    try {
      const response = await api.outline.applyStructurePreview({
        novel_id: state.currentProjectId,
        context_confirmation_id: preview.contextConfirmationId,
        source_task_id: preview.sourceTaskId,
        draft_structure: this._collectEditedOutlineGeneratePreview(),
        confirmed: true,
      })
      clearActiveWorkflow(preview.sourceTaskId)
      this._resetOutlineGenerateState()
      const counts = [
        response?.total_threads != null ? `剧情线 ${response.total_threads}` : "",
        response?.total_arcs != null ? `篇章纲 ${response.total_arcs}` : "",
        response?.total_scenes != null ? `Scene ${response.total_scenes}` : "",
      ].filter(Boolean).join(" · ")
      toast(`剧情结构已采用${counts ? `：${counts}` : ""}`, "success")
      await this.onEnter()
      router.refresh()
      return response
    } catch (err) {
      toast(err.message || "采用失败", "error")
      return false
    }
  },

  async _generateStructure(startChapter, endChapter) {
    try {
      const confirmation = await confirmAiReference({
        novel_id: state.currentProjectId,
        action: "outline.generate",
        task: "剧情结构生成",
        scope: "full",
        chapter_index: startChapter,
        include_pending_objects: false,
      })
      const result = await api.outline.generate({
        novel_id: state.currentProjectId,
        context_confirmation_id: confirmation.id,
        start_chapter: startChapter,
        end_chapter: endChapter,
      })
      if (!result?.task_id) throw new Error("生成任务未返回任务编号")
      this._outlineGenerateTaskId = result.task_id
      this._outlineGenerateMeta = {
        start_chapter: startChapter,
        end_chapter: endChapter,
        context_confirmation_id: confirmation.id,
      }
      this._outlineGeneratePreview = null
      this._outlineGenerateProgress = normalizeTaskProgress({
        ...result,
        task_type: "outline_generate",
        meta: this._outlineGenerateMeta,
      }, "outline_generate")
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "outline_generate",
        label: "剧情结构建议",
        projectId: state.currentProjectId,
        view: "outline",
        meta: this._outlineGenerateMeta,
      })
      toast("剧情结构建议生成任务已提交", "success")
      this._startOutlineGeneratePolling(result.task_id)
      router.renderCurrentView()
      return result
    } catch (err) {
      toast(err.message || "操作失败", "error")
      throw err
    }
  },

  async _analyzeOutline({ instruction, startChapter, endChapter }) {
    if (this._outlineAnalysisSubmitting) {
      throw new Error("大纲分析正在提交，请稍候")
    }
    if (this._outlineAnalysisProgress && !this._outlineAnalysisProgress.terminal) {
      throw new Error("已有大纲分析任务在运行，请先取消或等待完成")
    }
    this._outlineAnalysisSubmitting = true
    const projectId = state.currentProjectId
    if (!projectId) {
      this._outlineAnalysisSubmitting = false
      throw new Error("请先选择项目")
    }
    const requestText = String(instruction || "").trim()
    const tabLabel = {
      threads: "剧情线",
      arcs: "篇章纲",
      foreshadowing: "伏笔",
      reveals: "揭示",
    }[state.currentSubView] || "大纲"
    const task = requestText
      ? `分析章节 ${startChapter}-${endChapter} 的${tabLabel}结构。作者目标：${requestText}`
      : `分析章节 ${startChapter}-${endChapter} 的${tabLabel}结构，找出最影响后续创作的结构判断。`
    try {
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "outline.analyze",
        task,
        scope: "full",
        chapter_index: startChapter,
        visible_until_chapter: endChapter,
        budget_tokens: 12000,
        context_mode: "working",
        include_pending_objects: false,
        lock_scope: true,
        lock_chapter: true,
      })
      if (state.currentProjectId !== projectId) {
        throw new Error("项目已切换，请在当前项目重新发起分析")
      }
      const confirmedStart = Number(confirmation?.compile_options?.chapter_index || startChapter)
      const confirmedEnd = Number(confirmation?.compile_options?.visible_until_chapter || endChapter)
      const result = await api.outline.analyze({
        novel_id: projectId,
        context_confirmation_id: confirmation.id,
        start_chapter: confirmedStart,
        end_chapter: confirmedEnd,
      })
      if (!result?.task_id) throw new Error("分析任务未返回任务编号")
      const analysisMeta = {
        project_id: projectId,
        start_chapter: confirmedStart,
        end_chapter: confirmedEnd,
        instruction: requestText,
        context_confirmation_id: confirmation.id,
        context_summary: this._outlineAnalysisContextSummary(confirmation),
      }
      if (state.currentProjectId === projectId) {
        this._resetOutlineAnalysisState({ clearWorkflow: true })
      }
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "outline_analyze",
        label: "AI 大纲分析",
        projectId,
        view: "outline",
        meta: analysisMeta,
      })
      if (state.currentProjectId !== projectId) return result
      this._outlineAnalysisTaskId = result.task_id
      this._outlineAnalysisMeta = analysisMeta
      this._outlineAnalysisProgress = normalizeTaskProgress({
        ...result,
        task_type: "outline_analyze",
        meta: this._outlineAnalysisMeta,
      }, "outline_analyze")
      toast("大纲分析任务已提交", "success")
      this._startOutlineAnalysisPolling(result.task_id, projectId)
      router.renderCurrentView()
      return result
    } catch (err) {
      toast(err.message || "操作失败", "error")
      throw err
    } finally {
      this._outlineAnalysisSubmitting = false
    }
  },

  async _cancelOutlineAnalysisTask() {
    const taskId = this._outlineAnalysisTaskId
    const projectId = this._outlineAnalysisMeta?.project_id
    if (!taskId || !projectId || this._outlineAnalysisCancelPending) return false
    const confirmed = await confirmAsync(
      "确认取消当前大纲分析任务？已返回的只读结果不会被修改。",
      "确认取消",
    )
    if (!confirmed) return false

    this._stopOutlineAnalysisPolling()
    this._outlineAnalysisCancelPending = true
    if (state.currentProjectId === projectId) router.renderCurrentView()
    try {
      await api.tasks.cancel(taskId, projectId)
      if (
        this._outlineAnalysisTaskId !== taskId
        || this._outlineAnalysisMeta?.project_id !== projectId
      ) return true
      this._outlineAnalysisCancelPending = false
      this._outlineAnalysisProgress = normalizeTaskProgress({
        task_id: taskId,
        task_type: "outline_analyze",
        status: "cancelled",
        result: { message: "任务已取消" },
        meta: this._outlineAnalysisMeta,
      }, "outline_analyze")
      if (state.currentProjectId === projectId) {
        toast("当前大纲分析任务已取消", "warning")
        router.renderCurrentView()
      }
      return true
    } catch (err) {
      if (
        this._outlineAnalysisTaskId === taskId
        && this._outlineAnalysisMeta?.project_id === projectId
      ) {
        this._outlineAnalysisCancelPending = false
        this._startOutlineAnalysisPolling(taskId, projectId)
      }
      if (state.currentProjectId === projectId) {
        toast(err.message || "取消任务失败", "error")
      }
      return false
    }
  },

  _showOutlineAnalysisForm() {
    if (
      this._outlineAnalysisSubmitting
      || (this._outlineAnalysisProgress && !this._outlineAnalysisProgress.terminal)
    ) {
      toast("已有大纲分析任务正在处理", "info")
      return
    }
    const startValue = this._outlineAnalysisMeta?.start_chapter || 1
    const endValue = this._outlineAnalysisMeta?.end_chapter || 10
    const formHtml = `
      <div class="form-group">
        <label for="outline-analysis-instruction">你想让 AI 帮你判断什么？（可选）</label>
        <textarea class="form-textarea" id="outline-analysis-instruction" rows="4" placeholder="例如：主角在第 6 章的选择是否真正推动了主线？"></textarea>
        <p class="form-hint">不填写时，AI 会自行识别最值得作者处理的结构关系。</p>
      </div>
      <div class="form-grid form-grid--2">
        <div class="form-group">
          <label for="outline-analysis-start">起始章节</label>
          <input class="form-input" id="outline-analysis-start" type="number" min="1" value="${esc(startValue)}" />
        </div>
        <div class="form-group">
          <label for="outline-analysis-end">结束章节</label>
          <input class="form-input" id="outline-analysis-end" type="number" min="1" value="${esc(endValue)}" />
        </div>
      </div>
      <p class="writing-form-hint" role="note">下一步会先展示本范围内的 Scene、剧情线、篇章、伏笔/揭示，以及相关人物和物品，确认后才提交分析。结果只读，不会直接修改大纲。</p>
    `
    showModalHtml("AI 分析大纲", formHtml, [{
      text: "检查参考资料并分析",
      class: "btn-primary",
      handler: async () => {
        const start = Number.parseInt(document.getElementById("outline-analysis-start")?.value || "", 10)
        const end = Number.parseInt(document.getElementById("outline-analysis-end")?.value || "", 10)
        const instruction = document.getElementById("outline-analysis-instruction")?.value || ""
        if (!Number.isInteger(start) || start < 1 || !Number.isInteger(end) || end < 1) {
          toast("章节编号必须是正整数", "warning")
          return false
        }
        if (end < start) {
          toast("结束章节不能小于起始章节", "warning")
          return false
        }
        try {
          await this._analyzeOutline({
            instruction,
            startChapter: start,
            endChapter: end,
          })
          return true
        } catch {
          return false
        }
      },
    }])
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

  _showPlotStructureAutoExtractForm() {
    const actionLabel = this._plotAutoExtractLabel()
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="plot-auto-extract-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="plot-auto-extract-end" type="number" min="1" value="10" />
      </div>
      <p class="writing-form-hint" role="note">${esc(importAuthorizationNotice())}</p>
    `
    showModalHtml(actionLabel, formHtml, [{
      text: "确认并开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("plot-auto-extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("plot-auto-extract-end")?.value || "10", 10)
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        try {
          const result = await api.imports.startStage(
            "plot_structure",
            state.currentProjectId,
            start,
            end,
            false,
            false,
            importAuthorizationPayload(),
          )
          this._plotAutoExtractTaskId = result.task_id
          this._plotAutoExtractMeta = {
            start_chapter: start,
            end_chapter: end,
            label: actionLabel,
          }
          this._plotAutoExtractProgress = normalizeTaskProgress({
            ...result,
            task_type: "plot_structure_auto_extraction",
            meta: this._plotAutoExtractMeta,
          }, "plot_structure_auto_extraction")
          persistActiveWorkflow({
            taskId: result.task_id,
            workflowType: "plot_structure_auto_extraction",
            label: actionLabel,
            projectId: state.currentProjectId,
            view: "outline",
            meta: this._plotAutoExtractMeta,
          })
          closeModal()
          toast(`${actionLabel}任务已提交：${result.task_id || ""}`, "success")
          this._startPlotAutoExtractPolling(result.task_id)
          router.renderCurrentView()
        } catch (err) {
          toast(err.message || "提交失败", "error")
        }
      },
    }])
  },

  _showGenerateStructureForm() {
    this._generateOverlap = { threadCount: 0, arcCount: 0, rangeKey: "" }
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="generate-structure-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="generate-structure-end" type="number" min="1" value="10" />
      </div>
      <div id="generate-structure-warning" class="form-group outline-generate-warning" style="display:none;"></div>
      <p class="writing-form-hint" role="note">生成结果先作为待处理建议预览，不会直接写入剧情线、篇章纲或 Scene；检查并明确采用后才进入工作结构。</p>
      <div id="generate-structure-confirm-row" class="form-group outline-generate-confirm-row" style="display:none;">
        <label class="outline-generate-confirm-label">
          <input type="checkbox" id="generate-structure-confirm" />
          <span>我已确认，继续生成</span>
        </label>
      </div>
    `
    showModalHtml("AI 生成剧情结构", formHtml, [{
      text: "生成建议", class: "btn-primary", handler: async () => {
        const start = parseInt(document.getElementById("generate-structure-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("generate-structure-end")?.value || "10", 10)
        if (end < start) { toast("结束章节不能小于起始章节", "warning"); return false }

        const overlap = this._generateOverlap || { threadCount: 0, arcCount: 0 }
        if (overlap.threadCount > 0 || overlap.arcCount > 0) {
          const confirmed = document.getElementById("generate-structure-confirm")?.checked
          if (!confirmed) {
            toast("目标范围已存在结构，请勾选确认后继续", "warning")
            return false
          }
        }

        try {
          await this._generateStructure(start, end)
          return true
        } catch {
          return false
        }
      },
    }])

    this._bindGenerateOverlapCheck()
    const startEl = document.getElementById("generate-structure-start")
    const endEl = document.getElementById("generate-structure-end")
    const start = parseInt(startEl?.value || "1", 10)
    const end = parseInt(endEl?.value || "10", 10)
    if (Number.isInteger(start) && Number.isInteger(end)) {
      this._updateGenerateOverlapWarning(start, end)
    }
  },

  _bindGenerateOverlapCheck() {
    const startEl = document.getElementById("generate-structure-start")
    const endEl = document.getElementById("generate-structure-end")
    if (!startEl || !endEl) return

    const update = () => {
      const start = parseInt(startEl.value || "1", 10)
      const end = parseInt(endEl.value || "10", 10)
      if (Number.isInteger(start) && Number.isInteger(end)) {
        this._updateGenerateOverlapWarning(start, end)
      }
    }

    startEl.addEventListener("input", update)
    endEl.addEventListener("input", update)
  },

  async _updateGenerateOverlapWarning(start, end) {
    const rangeKey = `${start}-${end}`
    if (this._generateOverlap && this._generateOverlap.rangeKey === rangeKey) {
      this._renderGenerateOverlapWarning()
      return
    }

    let threadCount = 0
    let arcCount = 0
    try {
      const [threads, arcs] = await Promise.all([
        api.outline.listThreads(state.currentProjectId),
        api.outline.listArcs(state.currentProjectId),
      ])
      const threadList = (threads && (threads.items || threads)) || []
      const arcList = (arcs && (arcs.items || arcs)) || []
      threadCount = this._countRangeOverlap(threadList, start, end, "start_chapter", "planned_payoff_chapter")
      arcCount = this._countRangeOverlap(arcList, start, end, "start_chapter", "end_chapter")
    } catch (err) {
      // 无法获取重叠数据时静默降级，不阻塞用户操作
      console.warn("检查生成范围重叠失败", err)
    }

    this._generateOverlap = { threadCount, arcCount, rangeKey }
    this._renderGenerateOverlapWarning()
  },

  _countRangeOverlap(items, start, end, startKey, endKey) {
    return items.filter((item) => {
      if (item.status === "deprecated") return false
      const s = item[startKey]
      const e = item[endKey]
      if (s == null && e == null) return false
      const itemStart = s != null ? s : e
      const itemEnd = e != null ? e : s
      return itemStart <= end && itemEnd >= start
    }).length
  },

  _renderGenerateOverlapWarning() {
    const warningEl = document.getElementById("generate-structure-warning")
    const confirmRow = document.getElementById("generate-structure-confirm-row")
    if (!warningEl || !confirmRow) return

    const { threadCount = 0, arcCount = 0 } = this._generateOverlap || {}
    if (threadCount > 0 || arcCount > 0) {
      warningEl.innerHTML = esc(`第 ${this._generateOverlap.rangeKey} 章已存在 ${threadCount} 条剧情线、${arcCount} 条篇章纲。继续生成将追加新结构，是否继续？`)
      warningEl.style.display = "block"
      confirmRow.style.display = "block"
    } else {
      warningEl.style.display = "none"
      warningEl.innerHTML = ""
      confirmRow.style.display = "none"
      const cb = document.getElementById("generate-structure-confirm")
      if (cb) cb.checked = false
    }
  },

  _applyStructureFilters() {
    const subView = state.currentSubView || "threads"
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return
    this._structureFilters[subView] = {
      ...this._structureFilterFor(subView),
      status: document.getElementById("outline-filter-status")?.value || "",
      source: document.getElementById("outline-filter-source")?.value || "",
      workflow_id: document.getElementById("outline-filter-workflow-id")?.value?.trim() || "",
      needs_review: document.getElementById("outline-filter-needs-review")?.value || "",
      skip: 0,
    }
    router.refresh()
  },

  _resetStructureFilters() {
    const subView = state.currentSubView || "threads"
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return
    this._structureFilters[subView] = { ...STRUCTURE_FILTER_DEFAULTS }
    router.refresh()
  },

  _changeStructurePage(delta) {
    const subView = state.currentSubView || "threads"
    if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return
    const filters = this._structureFilterFor(subView)
    const total = this._structureTotals[subView] || 0
    const newSkip = filters.skip + delta * filters.limit
    if (newSkip < 0) return
    if (newSkip >= total) return
    filters.skip = newSkip
    router.refresh()
  },

  _bindEvents() {
    if (state.currentSubView === "scenes") {
      sceneWorkbenchView._bindEvents()
      return
    }
    if (state.currentSubView === "story-outline") {
      storyOutlineView._bindEvents()
      return
    }
    bindWorkspaceClick(this, {
      "nav-story-outline": () => router.navigate("outline", "story-outline"),
      "nav-scenes": () => router.navigate("outline", "scenes"),
      "nav-threads": () => router.navigate("outline", "threads"),
      "nav-arcs": () => router.navigate("outline", "arcs"),
      "nav-foreshadowing": () => router.navigate("outline", "foreshadowing"),
      "nav-reveals": () => router.navigate("outline", "reveals"),
      "retry-outline-load": async (_e, target) => {
        target.disabled = true
        target.textContent = "重新加载中..."
        try {
          await router.refresh()
        } catch (err) {
          target.disabled = false
          target.textContent = "重新加载"
          throw err
        }
      },
      "bulk-toggle-one": (e, t) => {
        e.stopPropagation()
        this._toggleBulkOne(t)
      },
      "bulk-toggle-all": (e, t) => {
        e.stopPropagation()
        this._toggleBulkAll(t)
      },
      "bulk-clear": (e, t) => {
        e.stopPropagation()
        this._clearBulkScope(t.getAttribute("data-scope"))
      },
      "bulk-run": (_e, t) => this._runBulkAction(t.getAttribute("data-scope"), t.getAttribute("data-bulk-action")),
      "create-thread": () => this._showCreateThreadForm(),
      "edit-thread": (_e, _t, ctx) => ctx.id && this._editThread(ctx.id),
      "mark-thread-reviewed": (_e, _t, ctx) => ctx.id && this._markThreadReviewed(ctx.id),
      "mark-thread-unreviewed": (_e, _t, ctx) => ctx.id && this._markThreadUnreviewed(ctx.id),
      "delete-thread": (_e, _t, ctx) => ctx.id && this._deleteThread(ctx.id),
      "create-arc": () => this._showCreateArcForm(),
      "edit-arc": (_e, _t, ctx) => ctx.id && this._editArc(ctx.id),
      "delete-arc": (_e, _t, ctx) => ctx.id && this._deleteArc(ctx.id),
      "create-scene": () => this._showCreateSceneForm(),
      "generate-structure": () => this._showGenerateStructureForm(),
      "analyze-outline": () => this._showOutlineAnalysisForm(),
      "cancel-outline-analysis": () => this._cancelOutlineAnalysisTask(),
      "dismiss-outline-analysis": () => {
        this._resetOutlineAnalysisState({ clearWorkflow: true })
        router.renderCurrentView()
      },
      "view-outline-generate-preview": () => this._showOutlineGeneratePreview(),
      "plot-structure-auto-extract": () => this._showPlotStructureAutoExtractForm(),
      "move-scene-up": (_e, _t, ctx) => ctx.id && this._moveSceneUp(ctx.id),
      "move-scene-down": (_e, _t, ctx) => ctx.id && this._moveSceneDown(ctx.id),
      "edit-scene": (_e, _t, ctx) => ctx.id && this._editScene(ctx.id),
      "delete-scene": (_e, _t, ctx) => ctx.id && this._deleteScene(ctx.id),
      "create-foreshadowing": () => this._showCreateForeshadowingForm(),
      "edit-foreshadowing": (_e, _t, ctx) => ctx.id && this._editForeshadowing(ctx.id),
      "delete-foreshadowing": (_e, _t, ctx) => ctx.id && this._deleteForeshadowing(ctx.id),
      "create-reveal": () => this._showCreateRevealForm(),
      "edit-reveal": (_e, _t, ctx) => ctx.id && this._editReveal(ctx.id),
      "delete-reveal": (_e, _t, ctx) => ctx.id && this._deleteReveal(ctx.id),
      "apply-outline-structure-filters": () => this._applyStructureFilters(),
      "reset-outline-structure-filters": () => this._resetStructureFilters(),
      "prev-outline-structure-page": () => this._changeStructurePage(-1),
      "next-outline-structure-page": () => this._changeStructurePage(1),
    })

    bindActionMenus()

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
    // 揭示状态变更
    document.querySelectorAll(".reveal-status-select").forEach((sel) => {
      sel.onchange = async () => {
        const id = sel.dataset.id
        if (!id) return
        try {
          await api.outline.updateReveal(id, state.currentProjectId, { status: sel.value })
          toast("揭示状态已更新", "success")
          await this.onEnter()
        } catch (err) { toast(err.message || "更新失败", "error") }
      }
    })
  },

  _visibleIdsForBulkScope(scope) {
    if (scope === "outline-threads") return this._threads.map((item) => item.id || item.thread_id).filter(Boolean)
    if (scope === "outline-arcs") return this._arcs.map((item) => item.id || item.arc_id).filter(Boolean)
    if (scope === "outline-foreshadowing") return this._foreshadowing.map((item) => item.id).filter(Boolean)
    if (scope === "outline-reveals") return this._reveals.map((item) => item.id).filter(Boolean)
    return []
  },

  _itemsForBulkScope(scope) {
    const selection = getBulkSelection(this, scope)
    if (scope === "outline-threads") return selectedItemsFrom(this._threads, selection, (item) => item.id || item.thread_id)
    if (scope === "outline-arcs") return selectedItemsFrom(this._arcs, selection, (item) => item.id || item.arc_id)
    if (scope === "outline-foreshadowing") return selectedItemsFrom(this._foreshadowing, selection)
    if (scope === "outline-reveals") return selectedItemsFrom(this._reveals, selection)
    return []
  },

  _toggleBulkOne(input) {
    toggleBulkSelection(this, input.getAttribute("data-scope"), input.getAttribute("data-id"), input.checked)
    this._rerenderBulkSelection()
  },

  _toggleBulkAll(input) {
    const scope = input.getAttribute("data-scope")
    toggleAllBulkSelection(this, scope, this._visibleIdsForBulkScope(scope), input.checked)
    this._rerenderBulkSelection()
  },

  _clearBulkScope(scope) {
    clearBulkSelection(this, scope)
    this._rerenderBulkSelection()
  },

  _rerenderBulkSelection() {
    syncBulkSelectionUi(this)
  },

  _runBulkAction(scope, action) {
    const items = this._itemsForBulkScope(scope)
    if (!items.length) {
      toast("请先选择要处理的项目", "warning")
      return
    }
    const labels = {
      "delete-threads": "批量删除剧情线",
      "review-threads": "批量采用 / 标记已检查",
      "delete-arcs": "批量删除篇章纲",
      "delete-foreshadowing": "批量删除伏笔",
      "delete-reveals": "批量删除揭示",
    }
    const confirmText = action === "review-threads" ? "确认处理" : "确认删除"
    confirmAction(`确定对选中的 ${items.length} 项执行「${labels[action] || "批量删除"}」吗？`, async () => {
      await this._executeBulkAction(scope, action, items)
    }, confirmText)
  },

  async _executeBulkAction(scope, action, items) {
    const labels = {
      "delete-threads": "批量删除剧情线",
      "review-threads": "批量采用 / 标记已检查",
      "delete-arcs": "批量删除篇章纲",
      "delete-foreshadowing": "批量删除伏笔",
      "delete-reveals": "批量删除揭示",
    }
    const result = await runBulkAction(items, async (item) => {
      if (action === "delete-threads") await api.outline.deleteThread(item.id || item.thread_id, state.currentProjectId)
      else if (action === "review-threads") {
        await api.outline.updateThread(
          item.id || item.thread_id,
          state.currentProjectId,
          this._reviewThreadPayload(item, "outline_threads_bulk"),
        )
      }
      else if (action === "delete-arcs") await api.outline.deleteArc(item.id || item.arc_id, state.currentProjectId)
      else if (action === "delete-foreshadowing") await api.outline.deleteForeshadowing(item.id, state.currentProjectId)
      else if (action === "delete-reveals") await api.outline.deleteReveal(item.id, state.currentProjectId)
    })
    toast(bulkResultMessage(result, labels[action] || "批量删除", (item) => item.name || item.title || item.summary || item.secret_summary || item.id), result.failed.length ? "warning" : "success")
    clearBulkSelection(this, scope)
    await this._refreshCurrentSubViewInPlace()
  },
}

router.registerView("outline", outlineView)
window.outlineView = outlineView
export default outlineView
