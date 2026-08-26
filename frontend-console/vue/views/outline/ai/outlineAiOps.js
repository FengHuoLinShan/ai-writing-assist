/**
 * outlineAiOps — outline 视图 AI 工作流的表单/操作函数。
 *
 * Lane D1（arcs/threads tabs）通过以下固定签名导入：
 *   showOutlineLayerAiForm(target, { selectedIds } = {})
 *   showOutlineAnalysisForm()
 *   showPlotStructureAutoExtractForm()
 *
 * 配套导出供卡片组件/编排方调用：
 *   showOutlineGeneratePreview / applyOutlineGeneratePreview
 *   cancelOutlineAnalysisTask
 *   generateOutlineLayer / analyzeOutline
 *
 * 所有模态经 bridge showModalHtml/confirmAction 展示；
 * 表单字段通过 DOM id 读取（遵循共享模态框契约，内容仍为已转义 HTML 字符串）。
 * 提交后 adopt 结果到对应的模块级管理器。
 */
import { getApi, getAppState, getRouteQuery, getRouter, getToast, getShowModalHtml, getCloseModal, getConfirmAction, getEsc } from "../../../bridge/index.js"
import { clearActiveWorkflow, createOperationId, normalizeTaskProgress, persistActiveWorkflow } from "../../../../shared/workflowProgress.js"
import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import { importAuthorizationNotice, importAuthorizationPayload } from "../../../../shared/importAuthorization.js"
import { getBulkSelection } from "../logic/outlineBulkSelection.js"
import {
  outlineGenerateManager,
  outlineAnalysisManager,
  plotAutoExtractManager,
  resetOutlineAnalysisState,
  clearOutlineGenerateWorkflowsForTarget,
  outlineAnalysisContextSummary,
  plotAutoExtractLabel,
} from "./outlineWorkflowManagers.js"

// ─── P20 结构层级标签 ─────────────────────────────────
const P20_TARGET_LABELS = {
  plot_thread: "剧情线",
  outline_arc: "篇章",
  planned_scene: "细纲",
}
let outlineAnalysisSubmissionGeneration = 0

// ═════════════════════════════════════════════════════════════════════════
// 内部辅助
// ═════════════════════════════════════════════════════════════════════════

function getBridge() {
  return {
    api: getApi(),
    state: getAppState(),
    router: getRouter(),
    toast: getToast(),
    showModalHtml: getShowModalHtml(),
    closeModal: getCloseModal(),
    confirmAction: getConfirmAction(),
    esc: getEsc(),
  }
}

/** 获取当前 subView 的 multi-selection（同步 vanilla _selectedIdsForP20）。 */
function selectedIdsForP20(target) {
  const scope = target === "plot_thread"
    ? "outline-threads"
    : target === "outline_arc"
      ? "outline-arcs"
      : null
  return scope ? Array.from(getBulkSelection(scope)) : []
}

// ═════════════════════════════════════════════════════════════════════════
// P20 当前层 AI 创作（outline generate）
// ═════════════════════════════════════════════════════════════════════════

/**
 * 显示当前层 AI 创作表单（lane C/D1 入口）。
 * 签名固定：showOutlineLayerAiForm(target, { selectedIds } = {})
 *
 * 对应 vanilla _showOutlineLayerAiForm (L2510-2569)。
 */
export async function showOutlineLayerAiForm(target, { selectedIds } = {}) {
  const { api, state, toast, showModalHtml, esc, router } = getBridge()
  const label = P20_TARGET_LABELS[target]
  if (!label) return
  const projectId = state?.currentProjectId
  if (!projectId) return

  let currentOutline
  try {
    currentOutline = await api.outline.getStoryOutline(projectId)
  } catch (err) {
    toast(err.message || "无法检查故事总览", "error")
    return
  }
  if (state?.currentProjectId !== projectId) return
  if (!currentOutline?.current_revision_id || !currentOutline?.revision) {
    toast("请先在“故事总览”页创建并采用当前版本", "warning")
    router?.navigate?.("outline", "story-outline")
    return
  }

  const ids = selectedIds || selectedIdsForP20(target) || []
  const defaultMode = ids.length ? "revise" : "create"
  const selectionHint = ids.length
    ? `当前已明确选择 ${ids.length} 个${label}；“修订所选”只会原位更新这些资产。`
    : `当前未选择${label}；如需修订，请先在页面明确选择目标。`

  const formHtml = `
    <div class="form-group">
      <label>创作方式</label>
      <select class="form-select" id="outline-layer-mode">
        <option value="create" ${defaultMode === "create" ? "selected" : ""}>新增设计</option>
        <option value="revise" ${defaultMode === "revise" ? "selected" : ""}>修订所选</option>
      </select>
      <p class="writing-form-hint">${esc(selectionHint)}</p>
    </div>
    <div class="form-group">
      <label>作者指令</label>
      <textarea class="form-textarea" id="outline-layer-instruction" rows="7" placeholder="说明这次希望创作或修订什么，以及你在意的方向。"></textarea>
    </div>
    <div class="outline-preview-fields">
      <label>计划起始章节（可选）<input class="form-input" id="outline-layer-start" type="number" min="1" /></label>
      <label>计划结束章节（可选）<input class="form-input" id="outline-layer-end" type="number" min="1" /></label>
    </div>
    <div class="outline-generate-warning"><strong>范围提示</strong><p>新增设计允许与已有资产并行，生成后的预览会明确列出重叠；修订采用前会重新校验总纲、所选资产和全部上下文。</p></div>
    <p class="writing-form-hint" role="note">模型只创作当前层；其他层、人物、物品和信息推进仅作为已确认上下文。结果不会自动写入。</p>
  `

  showModalHtml(`AI 创作${label}`, formHtml, [{
    text: "生成建议", class: "btn-primary", handler: async () => {
      const mode = document.getElementById("outline-layer-mode")?.value || "create"
      const instruction = document.getElementById("outline-layer-instruction")?.value?.trim() || ""
      const startRaw = document.getElementById("outline-layer-start")?.value || ""
      const endRaw = document.getElementById("outline-layer-end")?.value || ""
      const start = startRaw ? Number(startRaw) : null
      const end = endRaw ? Number(endRaw) : null
      if (!instruction) { toast("请填写作者指令", "warning"); return false }
      if (mode === "revise" && !ids.length) { toast(`请先明确选择要修订的${label}`, "warning"); return false }
      if ((start != null && !Number.isInteger(start)) || (end != null && !Number.isInteger(end))) { toast("章节范围必须是正整数", "warning"); return false }
      if (start != null && end != null && end < start) { toast("结束章节不能小于起始章节", "warning"); return false }
      try {
        await generateOutlineLayer({ target, mode, instruction, selectedIds: ids, startChapter: start, endChapter: end })
        return true
      } catch {
        return false
      }
    },
  }])
}

/**
 * 提交 P20 当前层 AI 创作任务。
 * 对应 vanilla _generateOutlineLayer (L2171-2234)。
 */
export async function generateOutlineLayer({ target, mode, instruction, selectedIds, startChapter, endChapter }) {
  const { api, state, toast } = getBridge()
  const projectId = state?.currentProjectId
  if (!projectId) { toast("请先选择项目", "warning"); return }
  let operationId = null
  try {
    const label = P20_TARGET_LABELS[target]
    const selectionContext = target === "plot_thread"
      ? { thread_ids: selectedIds }
      : target === "outline_arc"
        ? { arc_id: selectedIds?.[0] || null }
        : { scene_id: selectedIds?.[0] || null }
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "outline.generate",
      task: `AI 创作${label}`,
      scope: "full",
      chapter_index: startChapter,
      budget_tokens: 0,
      include_pending_objects: false,
      ...selectionContext,
    })
    if (state?.currentProjectId !== projectId) throw new Error("项目已切换，请在当前项目重新发起创作")
    operationId = createOperationId()
    const meta = {
      start_chapter: startChapter,
      end_chapter: endChapter,
      context_confirmation_id: confirmation.id,
      target,
      mode,
      label,
    }
    persistActiveWorkflow({ taskId: operationId, workflowType: "outline_generate", label: `${label}建议`, projectId, view: "outline", meta })
    const result = await api.outline.generate({
      contract_version: "outline_layer_v2",
      novel_id: projectId,
      context_confirmation_id: confirmation.id,
      target,
      mode,
      instruction,
      selected_thread_ids: target === "plot_thread" ? (selectedIds || []) : [],
      selected_arc_ids: target === "outline_arc" ? (selectedIds || []) : [],
      selected_scene_ids: target === "planned_scene" ? (selectedIds || []) : [],
      start_chapter: startChapter,
      end_chapter: endChapter,
      operation_id: operationId,
    })
    if (!result?.task_id) throw new Error("内容生成未能开始，请稍后重试")
    clearActiveWorkflow(operationId)

    if (state?.currentProjectId !== projectId) {
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "outline_generate",
        label: `${label}建议`,
        projectId,
        view: "outline",
        meta,
      })
      return result
    }
    outlineGenerateManager.adopt(result, meta)
    // 覆盖 preview 为 null（新任务开始，旧预览作废）
    outlineGenerateManager.state.preview = null
    toast(`${label}建议生成任务已提交`, "success")
    return result
  } catch (err) {
    if (operationId) clearActiveWorkflow(operationId)
    if (err?.message === "已取消 AI 参考资料确认") throw err
    toast(err.message || "操作失败", "error")
    throw err
  }
}

/** 进入当前层建议的可刷新审阅页。 */
export function showOutlineGeneratePreview() {
  const { toast, router } = getBridge()
  const preview = outlineGenerateManager.state.preview
  if (!preview) {
    toast("当前没有可采用的当前层建议", "warning")
    return
  }
  const subView = { plot_thread: "threads", outline_arc: "arcs", planned_scene: "scenes" }[preview.target]
  if (!subView) {
    toast("这份结构建议暂时无法打开，请重新生成", "warning")
    return
  }
  const query = getRouteQuery()
  query.set("review", "ai")
  router?.navigate?.("outline", subView, true, query)
}

/** 采用结构化审阅页提交的当前层建议。 */
export async function applyOutlineGeneratePreview(editedDraft) {
  const { api, state, toast } = getBridge()
  const preview = outlineGenerateManager.state.preview
  if (!preview || !editedDraft) return false
  const owner = {
    projectId: state?.currentProjectId,
    view: state?.currentView,
    subView: state?.currentSubView,
    preview,
  }
  const ownsResult = () => Boolean(
    state?.currentProjectId === owner.projectId
    && state?.currentView === owner.view
    && state?.currentSubView === owner.subView
    && outlineGenerateManager.state.preview === owner.preview
  )
  try {
    outlineGenerateManager.state.applyError = null
    const response = await api.outline.applyStructurePreview({
      novel_id: owner.projectId,
      context_confirmation_id: preview.contextConfirmationId,
      source_task_id: preview.sourceTaskId,
      draft_structure: editedDraft,
      confirmed: true,
    })
    if (!ownsResult()) return true
    const appliedTarget = response?.target || preview.target || outlineGenerateManager.state.meta?.target || "plot_thread"
    clearOutlineGenerateWorkflowsForTarget(appliedTarget)

    const counts = [
      response?.total_threads != null ? `剧情线 ${response.total_threads}` : "",
      response?.total_arcs != null ? `篇章 ${response.total_arcs}` : "",
      response?.total_scenes != null ? `场景 ${response.total_scenes}` : "",
    ].filter(Boolean).join(" · ")
    toast(`${P20_TARGET_LABELS[response?.target] || "结构"}已采用${counts ? `：${counts}` : ""}`, "success")
    return response
  } catch (err) {
    if (!ownsResult()) return true
    outlineGenerateManager.state.applyError = {
      status: Number(err?.status || err?.response?.status) || null,
      message: err.message || "采用失败",
    }
    toast(err.message || "采用失败", "error")
    return false
  }
}

// ═════════════════════════════════════════════════════════════════════════
// Outline Analysis
// ═════════════════════════════════════════════════════════════════════════

/**
 * 显示"AI 分析大纲"表单。
 * 对应 vanilla _showOutlineAnalysisForm (L2371-2426)。
 */
export function showOutlineAnalysisForm() {
  const { toast, showModalHtml, esc } = getBridge()
  const s = outlineAnalysisManager.state
  if (s.submitting || (s.progress && !s.progress.terminal)) {
    toast("已有大纲分析任务正在处理", "info")
    return
  }
  const startValue = s.meta?.start_chapter || 1
  const endValue = s.meta?.end_chapter || 10
  const formHtml = `
    <div class="form-group">
      <label for="outline-analysis-instruction">你想让 AI 帮你判断什么？（可选）</label>
      <textarea class="form-textarea" id="outline-analysis-instruction" rows="4" placeholder="例如：主角在第 6 章的选择是否真正推动了主线？"></textarea>
      <p class="form-hint">不填写时，AI 会自行识别最值得作者处理的结构关系。</p>
    </div>
    <div class="form-grid form-grid--2">
      <div class="form-group">
        <label for="outline-analysis-start">起始章节</label>
        <input class="form-input" id="outline-analysis-start" type="number" min="1" value="${esc(String(startValue))}" />
      </div>
      <div class="form-group">
        <label for="outline-analysis-end">结束章节</label>
        <input class="form-input" id="outline-analysis-end" type="number" min="1" value="${esc(String(endValue))}" />
      </div>
    </div>
    <p class="writing-form-hint" role="note">下一步会先展示本范围内的场景、剧情线、篇章、伏笔与揭示，以及相关人物和物品，确认后才提交分析。结果只读，不会直接修改故事结构。</p>
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
        await analyzeOutline({ instruction, startChapter: start, endChapter: end })
        return true
      } catch {
        return false
      }
    },
  }])
}

/**
 * 提交 AI 分析大纲任务。
 * 对应 vanilla _analyzeOutline (L2236-2322)。
 */
export async function analyzeOutline({ instruction, startChapter, endChapter }) {
  const { api, state, toast } = getBridge()
  const s = outlineAnalysisManager.state

  if (s.submitting) throw new Error("大纲分析正在提交，请稍候")
  if (s.progress && !s.progress.terminal) throw new Error("已有大纲分析任务在运行，请先取消或等待完成")

  const projectId = state?.currentProjectId
  if (!projectId) throw new Error("请先选择项目")
  const submissionGeneration = ++outlineAnalysisSubmissionGeneration
  s.submitting = true
  s.ownerProjectId = projectId

  const requestText = String(instruction || "").trim()
  const tabLabel = {
    threads: "剧情线",
    arcs: "篇章",
    foreshadowing: "伏笔",
    reveals: "揭示",
  }[state?.currentSubView || ""] || "大纲"
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
    if (state?.currentProjectId !== projectId) throw new Error("项目已切换，请在当前项目重新发起分析")

    const confirmedStart = Number(confirmation?.compile_options?.chapter_index || startChapter)
    const confirmedEnd = Number(confirmation?.compile_options?.visible_until_chapter || endChapter)
    const operationId = createOperationId()
    const analysisMeta = {
      project_id: projectId,
      start_chapter: confirmedStart,
      end_chapter: confirmedEnd,
      instruction: requestText,
      context_confirmation_id: confirmation.id,
      context_summary: outlineAnalysisContextSummary(confirmation),
    }
    persistActiveWorkflow({ taskId: operationId, workflowType: "outline_analyze", label: "AI 大纲分析", projectId, view: "outline", meta: analysisMeta })
    const result = await api.outline.analyze({
      novel_id: projectId,
      context_confirmation_id: confirmation.id,
      start_chapter: confirmedStart,
      end_chapter: confirmedEnd,
      operation_id: operationId,
    })
    if (!result?.task_id) throw new Error("分析未能开始，请稍后重试")


    if (state?.currentProjectId === projectId) {
      resetOutlineAnalysisState({ clearWorkflowState: true })
    }
    persistActiveWorkflow({
      taskId: result.task_id,
      workflowType: "outline_analyze",
      label: "AI 大纲分析",
      projectId,
      view: "outline",
      meta: analysisMeta,
    })
    if (state?.currentProjectId !== projectId) return result

    // 让 manager adopt（接管轮询）
    outlineAnalysisManager.adopt(result, analysisMeta)
    toast("大纲分析任务已提交", "success")
    return result
  } catch (err) {
    if (err?.message === "已取消 AI 参考资料确认") throw err
    toast(err.message || "操作失败", "error")
    throw err
  } finally {
    if (submissionGeneration === outlineAnalysisSubmissionGeneration) {
      s.submitting = false
    }
  }
}

/**
 * 取消当前大纲分析任务。
 * 对应 vanilla _cancelOutlineAnalysisTask (L2324-2368)。
 */
export async function cancelOutlineAnalysisTask() {
  const { api, state, toast, confirmAction } = getBridge()
  const s = outlineAnalysisManager.state
  const taskId = s.taskId
  const projectId = s.meta?.project_id || state?.currentProjectId
  if (!taskId || !projectId) return false

  // 使用原生 confirm（由 bridge.confirmAction 封装）
  return new Promise((resolve) => {
    const handler = async () => {
      outlineAnalysisManager.stop()
      try {
        await api.tasks.cancel(taskId, projectId)
        if (
          outlineAnalysisManager.state.taskId !== taskId
          || (outlineAnalysisManager.state.meta?.project_id || state?.currentProjectId) !== projectId
        ) { resolve(true); return }
        // 更新状态为 cancelled
        outlineAnalysisManager.state.progress = normalizeTaskProgress({
          task_id: taskId,
          task_type: "outline_analyze",
          status: "cancelled",
          result: { message: "任务已取消" },
          meta: outlineAnalysisManager.state.meta,
        }, "outline_analyze")
        await outlineAnalysisManager.stop()
        toast("当前大纲分析任务已取消", "warning")
        resolve(true)
      } catch (err) {
        if (
          outlineAnalysisManager.state.taskId === taskId
          && (outlineAnalysisManager.state.meta?.project_id || state?.currentProjectId) === projectId
        ) {
          // 取消失败，恢复轮询
          outlineAnalysisManager.adopt(
            { task_id: taskId, status: "running" },
            outlineAnalysisManager.state.meta,
          )
        }
        toast(err.message || "取消任务失败", "error")
        resolve(false)
      }
    }
    confirmAction("确认取消当前大纲分析任务？已返回的只读结果不会被修改。", handler, "确认取消")
  })
}

// ═════════════════════════════════════════════════════════════════════════
// Plot Structure Auto Extraction
// ═════════════════════════════════════════════════════════════════════════

/**
 * 显示"从正文提取剧情线/篇章"表单。
 * 对应 vanilla _showPlotStructureAutoExtractForm (L2444-2502)。
 */
export function showPlotStructureAutoExtractForm() {
  const { toast, showModalHtml, closeModal, esc } = getBridge()
  if (
    plotAutoExtractManager.state.submitting
    || (plotAutoExtractManager.state.progress && !plotAutoExtractManager.state.progress.terminal)
  ) {
    toast("正文结构提取任务正在处理", "info")
    return
  }
  const actionLabel = plotAutoExtractLabel()
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
      const start = Number(document.getElementById("plot-auto-extract-start")?.value)
      const end = Number(document.getElementById("plot-auto-extract-end")?.value)
      if (!Number.isInteger(start) || start < 1 || !Number.isInteger(end) || end < 1) {
        toast("章节范围必须是正整数", "warning")
        return false
      }
      if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return false }
      const appState = getAppState()
      const projectId = appState?.currentProjectId
      if (!projectId) {
        toast("请先选择项目", "warning")
        return false
      }
      const submission = plotAutoExtractManager.beginSubmission(projectId)
      if (!submission) {
        toast("正文结构提取任务正在处理", "info")
        return false
      }
      try {
        const api = getApi()
        const result = await api.imports.startStage(
          "plot_structure",
          projectId,
          start,
          end,
          false,
          false,
          importAuthorizationPayload(),
        )
        const actionLabelFinal = plotAutoExtractLabel()
        const meta = {
          project_id: projectId,
          start_chapter: start,
          end_chapter: end,
          label: actionLabelFinal,
        }
        const adopted = plotAutoExtractManager.adopt(result, meta, projectId)
        if (adopted) {
          closeModal()
          toast(`${actionLabelFinal}任务已提交`, "success")
        }
        return true
      } catch (err) {
        if (getAppState()?.currentProjectId === projectId) {
          toast(err.message || "提交失败", "error")
        }
        return false
      } finally {
        plotAutoExtractManager.endSubmission(submission)
      }
    },
  }])
}
