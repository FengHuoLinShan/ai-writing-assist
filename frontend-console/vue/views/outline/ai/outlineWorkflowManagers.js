/**
 * outlineWorkflowManagers — outline 视图三条 AI 工作流轮询线的模块级管理器。
 *
 * 每条线由 createOutlineWorkflowManager 工厂创建，状态为 reactive 供 Vue 组件自渲染。
 *
 * 生命周期遵循 island 路由契约：
 * - island load() → recover(projectId)（localStorage 恢复未终结任务）；
 * - island onLeave → stop()；
 * - 终态经 onTerminal 处理：generate 保留预览（不自动清除 workflow）、分析显示结果、
 *   提取完成触发 router.refresh()。
 *
 * 与 world workflowManagers.js 的关键差异：
 * - outlineGenerate 需管理 preview 状态与按 target 清理持久化；
 * - outlineAnalysis 使用 novelId 参数轮询、支持显式取消；
 * - plotAutoExtract 简单提交→轮询→终态刷新。
 */
import { reactive } from "vue"
import { getApi, getAppState, getRouter, getToast } from "../../../bridge/index.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"

// ─── P20 结构层级映射 ─────────────────────────────────
const P20_TARGET_LABELS = {
  plot_thread: "剧情线",
  outline_arc: "篇章",
  planned_scene: "细纲",
}
const P20_TARGET_BY_SUBVIEW = {
  threads: "plot_thread",
  arcs: "outline_arc",
  scenes: "planned_scene",
}

function refreshOutlineIfActive() {
  const appState = getAppState()
  if (appState?.currentView !== "outline") return
  const router = getRouter()
  router?.refresh?.()
}

// ─── 通用工厂 ────────────────────────────────────────────────────────────

/**
 * 创建一条轮廓工作流的管理器。
 *
 * @param {object} config
 * @param {string} config.workflowType      — 异步任务类型
 * @param {string} config.label             — 默认标题
 * @param {Function} config.matchRecovered  — (workflows) => workflow|null
 * @param {Function} config.onTerminal      — async (progress, state) => …
 * @param {Function} config.onUpdate        — (progress) => … 可选额外更新回调
 * @param {boolean} config.useNovelId       — 轮询传 novelId（分析用）
 * @param {boolean} config.clearOnDone       — done 时是否立即清理持久化工作流
 * @param {Function} config.matchesActiveScope — 当前项目/子视图是否仍拥有内存任务
 * @param {Function} config.onScopeReset       — 跨 scope 时清理扩展状态
 * @returns {{ state, workflowType, label, adopt, recover, stop }}
 */
function createOutlineWorkflowManager({
  workflowType,
  label,
  matchRecovered,
  onTerminal,
  onUpdate,
  useNovelId = false,
  clearOnDone = true,
  matchesActiveScope = null,
  onScopeReset = null,
}) {
  const state = reactive({
    taskId: null,
    status: "就绪",
    meta: null,
    progress: null,
    ownerProjectId: null,
    submitting: false,
  })
  let poller = null
  let submissionGeneration = 0

  function stop() {
    if (poller?.stop) poller.stop()
    poller = null
  }

  function resetMemoryScope() {
    submissionGeneration += 1
    stop()
    state.taskId = null
    state.status = "就绪"
    state.meta = null
    state.progress = null
    state.ownerProjectId = null
    state.submitting = false
    onScopeReset?.(state)
  }

  function beginSubmission(projectId) {
    if (
      !projectId
      || state.submitting
      || (state.taskId && state.progress && !state.progress.terminal)
    ) return null
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    const token = { generation: ++submissionGeneration, projectId }
    state.ownerProjectId = projectId
    state.submitting = true
    return token
  }

  function endSubmission(token) {
    if (!token || token.generation !== submissionGeneration) return
    state.submitting = false
  }

  async function handleTerminal(progress, task = null) {
    stop()
    if (!progress.done || clearOnDone) {
      clearActiveWorkflow(progress.taskId || state.taskId)
      state.taskId = null
    }
    state.progress = progress
    await onTerminal?.(progress, state, task)
  }

  function startPolling(taskId, novelId = null) {
    stop()
    const api = getApi()
    const opts = {
      taskId,
      workflowType,
      apiClient: api,
      onUpdate: (progress) => {
        state.progress = progress
        state.status = progress.statusLabel || progress.status || "运行中"
        onUpdate?.(progress)
      },
      onDone: (progress, task) => { void handleTerminal(progress, task) },
      onFailed: (progress, task) => { void handleTerminal(progress, task) },
    }
    if (useNovelId && novelId) opts.novelId = novelId
    poller = pollTaskProgress(opts)
  }

  /** 提交成功后接管任务：写 localStorage 并开始轮询。 */
  function adopt(result, meta = null, projectId = getAppState()?.currentProjectId || null) {
    if (!result?.task_id || !projectId) return false
    persistActiveWorkflow({
      taskId: result.task_id,
      workflowType,
      label,
      projectId,
      view: "outline",
      meta: meta || undefined,
    })
    if (getAppState()?.currentProjectId !== projectId) return false
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    state.taskId = result.task_id
    state.status = "运行中"
    state.meta = meta || state.meta || null
    state.ownerProjectId = projectId
    state.progress = normalizeTaskProgress({
      ...result,
      task_type: workflowType,
      meta: state.meta || {},
    }, workflowType)
    startPolling(result.task_id, state.meta?.project_id || null)
    return state
  }

  /** island load() 调用：从 localStorage 恢复未终结任务。 */
  function recover(projectId) {
    if (!projectId) {
      resetMemoryScope()
      return
    }
    const scopeMatches = (
      (!state.ownerProjectId || state.ownerProjectId === projectId)
      && (!matchesActiveScope || matchesActiveScope(state, projectId))
    )
    if (state.ownerProjectId && !scopeMatches) resetMemoryScope()
    if (state.taskId && state.progress && !state.progress.terminal && scopeMatches) return
    if (state.preview && scopeMatches) return
    const workflow = matchRecovered(recoverActiveWorkflows(projectId))
    if (!workflow?.taskId) return
    state.taskId = workflow.taskId
    state.status = "运行中"
    state.meta = workflow.meta || state.meta || null
    state.ownerProjectId = projectId
    state.progress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflow.workflowType || workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflow.workflowType || workflowType)
    startPolling(workflow.taskId, state.meta?.project_id || null)
  }

  return {
    state,
    workflowType,
    label,
    adopt,
    recover,
    stop,
    resetMemoryScope,
    beginSubmission,
    endSubmission,
  }
}

// ─── Outline Generate Manager ────────────────────────────────────────────

/**
 * 当前层 AI 创作（P20）管理器。
 * 额外管理 preview 状态，onDone 不自动清除 workflow（预览未生效时保留持久化）。
 */
export const outlineGenerateManager = createOutlineWorkflowManager({
  workflowType: "outline_generate",
  label: "当前层建议",
  clearOnDone: false,
  matchesActiveScope: (state) => {
    const currentTarget = P20_TARGET_BY_SUBVIEW[getAppState()?.currentSubView || "threads"] || null
    const activeTarget = state.preview?.target || state.meta?.target || "plot_thread"
    return activeTarget === currentTarget
  },
  onScopeReset: (state) => { state.preview = null },
  matchRecovered: (workflows) => {
    const appState = getAppState()
    const currentTarget = P20_TARGET_BY_SUBVIEW[appState?.currentSubView || "threads"] || null
    return workflows
      .filter((item) => item.workflowType === "outline_generate")
      .reduce((latest, item) => {
        const target = item.meta?.target
        const matches = target
          ? target === currentTarget
          : currentTarget === "plot_thread"
        if (!matches) return latest
        if (!latest) return item
        const latestTime = Date.parse(latest.updatedAt || latest.createdAt || "") || 0
        const itemTime = Date.parse(item.updatedAt || item.createdAt || "") || 0
        return itemTime >= latestTime ? item : latest
      }, null)
  },
  onTerminal: async (progress, state, task) => {
    const toast = getToast()
    if (progress.failed || progress.cancelled) {
      toast(progress.cancelled
        ? "当前层建议生成已取消"
        : `${state.meta?.label || "当前层"}建议生成失败: ${progress.errorMessage || "未知错误"}`,
      progress.cancelled ? "warning" : "error")
      return
    }
    const preview = captureOutlineGeneratePreview(task, progress)
    if (preview) {
      toast(`${P20_TARGET_LABELS[preview.target] || "结构"}建议已生成，请检查后再采用`, "info")
      return
    }
    clearActiveWorkflow(progress.taskId || state.taskId)
    state.taskId = null
    toast("当前层创作完成，但没有可采用的建议", "info")
  },
})

/**
 * 从任务结果捕获 outline generate preview。
 * 签名同 vanilla _captureOutlineGeneratePreview (L545-572)。
 * 返回 preview 对象或 null，并更新 state.preview。
 */
export function captureOutlineGeneratePreview(task, progress) {
  const state = outlineGenerateManager.state
  if (task?.task_type && task.task_type !== "outline_generate") {
    state.preview = null
    return null
  }
  const result = task?.result || progress?.raw?.result || {}
  if (result.apply_status === "applied" || result.requires_apply !== true || !result.draft_structure) {
    state.preview = null
    return null
  }
  const sourceTaskId = result.source_task_id || task?.task_id || task?.id || progress?.taskId || state.taskId
  const contextConfirmationId = result.context_confirmation_id || state.meta?.context_confirmation_id
  if (!sourceTaskId || !contextConfirmationId) {
    state.preview = null
    return null
  }
  state.taskId = sourceTaskId
  state.preview = {
    sourceTaskId,
    contextConfirmationId,
    draftStructure: JSON.parse(JSON.stringify(result.draft_structure)),
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
    target: result.target || state.meta?.target,
    mode: result.mode || state.meta?.mode,
    overlap: result.overlap || {},
  }
  return state.preview
}

/** 重置 outline generate 全部状态（stop polling + 清所有字段）。 */
export function resetOutlineGenerateState() {
  const manager = outlineGenerateManager
  manager.stop()
  const s = manager.state
  s.taskId = null
  s.status = "就绪"
  s.meta = null
  s.progress = null
  s.preview = null
  s.ownerProjectId = null
  s.submitting = false
}

/** 清理指定 target 的全部持久化 outline_generate workflow。 */
export function clearOutlineGenerateWorkflowsForTarget(target) {
  if (!target) return
  const appState = getAppState()
  for (const workflow of recoverActiveWorkflows(appState?.currentProjectId)) {
    if (workflow.workflowType !== "outline_generate") continue
    const workflowTarget = workflow.meta?.target || "plot_thread"
    if (workflowTarget === target) clearActiveWorkflow(workflow.taskId || workflow.id)
  }
}

// ─── Outline Analysis Manager ────────────────────────────────────────────

/**
 * AI 分析大纲管理器。
 * 轮询使用 novelId 参数，支持显式取消。终态时保存分析结果到 state.result。
 */
export const outlineAnalysisManager = createOutlineWorkflowManager({
  workflowType: "outline_analyze",
  label: "AI 大纲分析",
  useNovelId: true,
  onScopeReset: (state) => { state.result = null },
  matchRecovered: (workflows) => {
    const appState = getAppState()
    return workflows
      .filter((item) => (
        item.workflowType === "outline_analyze"
        && item.projectId === appState?.currentProjectId
      ))
      .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0] || null
  },
  onTerminal: async (progress) => {
    const toast = getToast()
    const state = outlineAnalysisManager.state
    if (progress.done) {
      const analysis = progress?.raw?.result?.analysis
      if (typeof analysis === "string" && analysis.trim()) {
        state.result = {
          markdown: analysis,
          contextSummary: state.meta?.context_summary || {},
        }
        toast("大纲分析已完成", "success")
      } else {
        clearActiveWorkflow(progress.taskId)
        state.taskId = null
        toast("大纲分析完成，但没有返回可展示的内容", "info")
      }
      return
    }
    if (progress.failed || progress.cancelled) {
      state.result = null
      if (progress.cancelled) {
        toast("大纲分析任务已取消", "warning")
      } else {
        toast(`大纲分析失败: ${progress.errorMessage || "未知错误"}`, "error")
      }
    }
  },
})

/** 重置 outline analysis 状态。 */
export function resetOutlineAnalysisState({ clearWorkflowState = true } = {}) {
  const manager = outlineAnalysisManager
  manager.stop()
  const s = manager.state
  if (clearWorkflowState && s.taskId) {
    clearActiveWorkflow(s.taskId)
  }
  s.taskId = null
  s.status = "就绪"
  s.meta = null
  s.progress = null
  s.result = null
  s.ownerProjectId = null
  s.submitting = false
}

/**
 * 提取上下文摘要（对应 vanilla _outlineAnalysisContextSummary L717-734）。
 */
export function outlineAnalysisContextSummary(confirmation) {
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
}

// ─── Plot Auto Extract Manager ───────────────────────────────────────────

/**
 * 剧情线/篇章自动提取管理器。
 * 终态完成触发 router.refresh()（等价 vanilla onEnter + refresh）。
 */
export const plotAutoExtractManager = createOutlineWorkflowManager({
  workflowType: "plot_structure_auto_extraction",
  label: "剧情线自动提取",
  matchRecovered: (workflows) => (
    workflows.find((item) => item.workflowType === "plot_structure_auto_extraction" && item.view === "outline")
    || workflows.find((item) => item.workflowType === "plot_structure_auto_extraction")
  ),
  onTerminal: async (progress) => {
    const toast = getToast()
    if (progress.done) {
      toast(`${progress.label || "剧情线自动提取"}完成`, "success")
      refreshOutlineIfActive()
      return
    }
    if (progress.failed || progress.cancelled) {
      toast(`${progress.label || "剧情线自动提取"}${progress.cancelled ? "已取消" : `失败: ${progress.errorMessage || "未知错误"}`}`, progress.cancelled ? "warning" : "error")
    }
  },
})

/** 基于 currentSubView 返回提取动作标签（对应 vanilla _plotAutoExtractLabel L1070-1072）。 */
export function plotAutoExtractLabel(subView) {
  const s = subView || getAppState()?.currentSubView || "threads"
  return s === "arcs" ? "从正文提取篇章" : "从正文提取剧情线"
}

// ─── 当前 P20 target 辅助 ────────────────────────────────────────────────

/** 返回当前 subView 对应的 P20 target。 */
export function currentP20Target() {
  const appState = getAppState()
  return P20_TARGET_BY_SUBVIEW[appState?.currentSubView || "threads"] || null
}
