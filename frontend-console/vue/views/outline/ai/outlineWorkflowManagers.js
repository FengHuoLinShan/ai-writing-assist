/**
 * outlineWorkflowManagers — outline 视图三条 AI 工作流轮询线的模块级管理器。
 *
 * 每条线由 Vue 内部共享的 createWorkflowManager 工厂创建，状态为 reactive 供组件自渲染。
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
import { getApi, getAppState, getRouter, getToast } from "../../../bridge/index.js"
import {
  clearActiveWorkflow,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"
import { createWorkflowManager } from "../../../shared/workflowManager.js"

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

function refreshPlotStructureIfActive(ownerProjectId) {
  const appState = getAppState()
  if (appState?.currentView !== "outline") return
  if (!ownerProjectId || appState.currentProjectId !== ownerProjectId) return
  if (!["threads", "arcs"].includes(appState.currentSubView)) return
  const router = getRouter()
  router?.refresh?.()
}

// ─── Outline Generate Manager ────────────────────────────────────────────

/**
 * 当前层 AI 创作（P20）管理器。
 * 额外管理 preview 状态，onDone 不自动清除 workflow（预览未生效时保留持久化）。
 */
export const outlineGenerateManager = createWorkflowManager({
  workflowType: "outline_generate",
  label: "当前层建议",
  view: "outline",
  clearOnDone: false,
  matchesActiveScope: (state) => {
    const currentTarget = P20_TARGET_BY_SUBVIEW[getAppState()?.currentSubView || "threads"] || null
    const activeTarget = state.preview?.target || state.meta?.target || "plot_thread"
    return activeTarget === currentTarget
  },
  onScopeReset: (state) => { state.preview = null },
  skipRecover: (state, scopeMatches) => state.preview && scopeMatches,
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
export const outlineAnalysisManager = createWorkflowManager({
  workflowType: "outline_analyze",
  label: "AI 大纲分析",
  view: "outline",
  pollNovelId: (state) => state.meta?.project_id || null,
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
export const plotAutoExtractManager = createWorkflowManager({
  workflowType: "plot_structure_auto_extraction",
  label: "剧情线自动提取",
  view: "outline",
  matchRecovered: (workflows) => (
    workflows.find((item) => item.workflowType === "plot_structure_auto_extraction" && item.view === "outline")
    || workflows.find((item) => item.workflowType === "plot_structure_auto_extraction")
  ),
  onTerminal: async (progress, _state, _task, ownerProjectId) => {
    const toast = getToast()
    if (progress.done) {
      toast(`${progress.label || "剧情线自动提取"}完成`, "success")
      refreshPlotStructureIfActive(ownerProjectId)
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
