import {
  clearActiveWorkflow,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"

const SUPPORTED = new Set([
  "deep_import",
  "chapter_card_generation",
  "scene_auto_extraction",
  "world_object_auto_extraction",
  "plot_structure_auto_extraction",
])

const POLL_INTERVAL_MS = 3000
const POLL_RETRY_DELAYS_MS = [3000, 6000, 12000, 24000, 30000]

function taskPercent(task, result) {
  const raw = typeof task.progress === "number" ? task.progress : NaN
  if (Number.isFinite(raw)) return Math.round(raw * (raw <= 1 ? 100 : 1))
  const phase = result.current_phase || ""
  const phase1Done = Number(result.phase1_completed_batches || 0)
  const phase1Total = Number(result.phase1_total_batches || 0)
  const phase2Done = Number(result.phase2_completed_scenes || 0)
  const phase2Total = Number(result.phase2_total_scenes || 0)
  if (phase === "phase0_plan") return phase1Total ? Math.min(10, Math.round((phase1Done / phase1Total) * 10)) : 5
  if (phase === "phase1a_scene_slicing") return phase1Total ? 10 + Math.min(10, Math.round((phase1Done / phase1Total) * 10)) : 15
  if (phase === "phase1b_enrichment") return phase1Total ? 20 + Math.min(10, Math.round((phase1Done / phase1Total) * 10)) : 25
  if (phase === "scene_commit") return 30
  if (phase === "entity_extraction") return phase2Total ? 40 + Math.min(40, Math.round((phase2Done / phase2Total) * 40)) : 50
  if (phase === "structure_analysis") return 80
  return result.phase === "done" || task.status === "done" ? 100 : null
}

export function createDeepImportController({ api, toast, getProjectId, onChange, onDone }) {
  let taskId = null
  let projectId = null
  let progress = null
  let timer = null
  let pollFailures = 0
  let generation = 0
  let disposed = false

  function emit() { onChange({ taskId, projectId, progress: progress ? { ...progress } : null }) }
  function stop() {
    generation += 1
    if (timer) clearTimeout(timer)
    timer = null
    pollFailures = 0
  }

  function operationSnapshot() {
    return {
      taskId,
      projectId,
      generation,
    }
  }

  function operationIsCurrent(snapshot) {
    return Boolean(
      !disposed
      && snapshot.taskId
      && taskId === snapshot.taskId
      && projectId === snapshot.projectId
      && generation === snapshot.generation
      && getProjectId() === snapshot.projectId,
    )
  }

  function fromTask(task = {}, workflow = {}) {
    const result = task.result || {}
    return {
      phase: result.phase || task.status || "running",
      status: task.status || "running",
      workflowType: result.workflow_type || task.task_type || workflow.workflowType || "deep_import",
      label: workflow.label || result.label || "自动提取",
      message: result.message || task.error_message || task.status || "处理中...",
      percent: taskPercent(task, result),
      availableActions: Array.isArray(task.available_actions) ? task.available_actions : [],
      workflowId: result.workflow_id || workflow.meta?.workflow_id || null,
      step: result.current_step || null,
      currentPhase: result.current_phase || null,
      currentRound: result.current_round ?? null,
      currentChapterRange: result.current_chapter_range || null,
      currentChapter: result.current_chapter ?? null,
      currentSceneCandidateId: result.current_scene_candidate_id || null,
      currentWindow: result.current_window || null,
      currentOperation: result.current_operation || null,
      currentItem: result.current_item || {},
      qualityStatus: result.quality_status || null,
      qualityStats: result.quality_stats || {},
      qualityRerun: result.quality_rerun || {},
      degraded: Boolean(result.degraded),
      degradedReason: result.degraded_reason || null,
      degradedBatches: result.degraded_batches || [],
      phase1aFallback: Boolean(result.phase1a_fallback),
      assetSummary: result.asset_summary || {},
      auditSummary: result.snapshot_health_summary || result.audit_summary || {},
      phaseArtifacts: result.phase_artifacts || {},
      progressEvents: result.progress_events || [],
      phaseTimeline: result.phase_timeline || [],
      acceptanceChecks: result.acceptance_checks || [],
      diagnosticCounts: result.diagnostic_counts || {},
      throttleReasons: result.phase2_throttle_reasons || [],
      phaseErrors: result.phase_errors || [],
      recoverySummary: result.recovery_summary || {},
      lifecycle: task.lifecycle || {},
      mapNextStep: result.map_next_step || null,
      recoveryRequired: Boolean(
        task.lifecycle?.recovery_required
        || result.recovery_required
        || result.interrupted
        || result.recoverable,
      ),
      error: result.error || task.error_message || null,
    }
  }

  async function prepareMapNextStep(token) {
    if (!progress || progress.workflowType !== "deep_import" || progress.status !== "done" || token !== generation) return
    try {
      const context = await api.world.getMapQuickCreateContext(projectId, true)
      if (disposed || token !== generation || getProjectId() !== projectId) return
      const maps = context?.existing_maps || []
      const locations = context?.locations || []
      const candidates = context?.candidate_locations || []
      if (maps.length) {
        let count = 0
        try {
          const inbox = await api.world.listProjectMapObservationInbox(projectId, { limit: 1 })
          if (disposed || token !== generation || getProjectId() !== projectId) return
          count = Number(inbox?.total || 0)
        } catch { /* 地图下一步是增强信息，不影响导入完成态 */ }
        progress = { ...progress, mapNextStep: { action: "inbox", count, workflow_id: progress.workflowId } }
      } else if (locations.length) {
        progress = { ...progress, mapNextStep: { action: "quick-create", count: locations.length, workflow_id: progress.workflowId } }
      } else if (candidates.length) {
        progress = { ...progress, mapNextStep: { action: "review-locations", count: candidates.length, workflow_id: progress.workflowId } }
      }
      emit()
    } catch (err) {
      if (disposed || token !== generation || getProjectId() !== projectId) return
      progress = { ...progress, mapNextStepError: err?.message || "地图下一步加载失败" }
      emit()
    }
  }

  function retryMapNextStep() {
    if (!progress || progress.status !== "done") return null
    progress = { ...progress, mapNextStepError: null }
    emit()
    return prepareMapNextStep(generation)
  }

  function schedule(token, delayMs = POLL_INTERVAL_MS) {
    timer = setTimeout(() => poll(token), delayMs)
  }

  async function poll(token = generation) {
    if (disposed || token !== generation || !taskId || getProjectId() !== projectId) return
    const requestedTaskId = taskId
    const requestedProjectId = projectId
    let nextDelay = POLL_INTERVAL_MS
    try {
      const task = await api.tasks.get(requestedTaskId, requestedProjectId)
      if (
        disposed
        || token !== generation
        || taskId !== requestedTaskId
        || projectId !== requestedProjectId
        || getProjectId() !== requestedProjectId
      ) return
      pollFailures = 0
      progress = fromTask(task, { label: progress?.label, workflowType: progress?.workflowType })
      emit()
      if (["done", "failed", "cancelled"].includes(task.status)) {
        if (task.status === "done") {
          await onDone?.()
          await prepareMapNextStep(token)
        }
        return
      }
    } catch (err) {
      if (
        disposed
        || token !== generation
        || taskId !== requestedTaskId
        || projectId !== requestedProjectId
        || getProjectId() !== requestedProjectId
      ) return
      if (err?.status === 404) {
        clearActiveWorkflow(requestedTaskId)
        taskId = null
        progress = null
        emit()
        return
      }
      pollFailures += 1
      nextDelay = POLL_RETRY_DELAYS_MS[
        Math.min(pollFailures - 1, POLL_RETRY_DELAYS_MS.length - 1)
      ]
      progress = { ...(progress || {}), message: "任务状态暂不可用，正在重试..." }
      emit()
    }
    schedule(token, nextDelay)
  }

  function startTask(info = {}) {
    const previousTaskId = taskId
    const previousTerminal = ["done", "failed", "cancelled"].includes(
      progress?.status || progress?.phase,
    )
    stop()
    disposed = false
    if (previousTerminal && previousTaskId && previousTaskId !== info.taskId) {
      clearActiveWorkflow(previousTaskId)
    }
    taskId = info.taskId
    projectId = getProjectId()
    progress = {
      phase: "running",
      status: "running",
      workflowType: info.workflowType || "deep_import",
      label: info.label || "自动提取",
      message: "任务已提交，正在处理...",
      percent: 0,
      availableActions: [],
    }
    persistActiveWorkflow({
      taskId,
      projectId,
      workflowType: info.workflowType || "deep_import",
      label: progress.label,
      view: "writing",
      meta: { stage: info.stage, startChapter: info.startChapter, endChapter: info.endChapter },
    })
    emit()
    poll(generation)
  }

  async function recover() {
    disposed = false
    stop()
    projectId = getProjectId()
    const supported = recoverActiveWorkflows(projectId)
      .filter((item) => SUPPORTED.has(item.workflowType))
    // persistActiveWorkflow 会把最新提交移动到数组末尾。恢复最新任务，避免旧失败
    // 记录遮住作者刚提交、仍在后台执行的新任务。
    const workflow = supported[supported.length - 1]
    if (!workflow?.taskId) return
    taskId = workflow.taskId
    progress = { phase: "running", status: "running", workflowType: workflow.workflowType, label: workflow.label || "自动提取", message: "正在恢复任务...", percent: null }
    emit()
    await poll(generation)
  }

  async function cancel() {
    if (!taskId || !projectId) return false
    const snapshot = operationSnapshot()
    try {
      await api.tasks.cancel(snapshot.taskId, snapshot.projectId)
      if (!operationIsCurrent(snapshot)) return true
      stop()
      progress = { ...(progress || {}), phase: "cancelled", status: "cancelled", message: "任务已取消" }
      emit()
      return true
    } catch (err) {
      toast(err?.message || "取消任务失败", "error")
      return false
    }
  }

  async function resume() {
    if (!taskId) return false
    const snapshot = operationSnapshot()
    try {
      const result = await api.imports.resumeDeepImport(snapshot.taskId)
      if (!operationIsCurrent(snapshot)) return true
      taskId = result?.task_id || snapshot.taskId
      progress = { ...(progress || {}), phase: "running", status: "running", message: "任务已继续" }
      emit()
      poll(generation)
      return true
    } catch (err) {
      toast(err?.message || "继续恢复失败", "error")
      return false
    }
  }

  async function abandon() {
    if (!taskId) return false
    const snapshot = operationSnapshot()
    try {
      await api.imports.abandonDeepImport(snapshot.taskId)
      clearActiveWorkflow(snapshot.taskId)
      if (!operationIsCurrent(snapshot)) return true
      stop()
      taskId = null
      progress = null
      emit()
      return true
    } catch (err) {
      toast(err?.message || "放弃恢复失败", "error")
      return false
    }
  }

  function dismiss() {
    if (taskId) clearActiveWorkflow(taskId)
    stop()
    taskId = null
    progress = null
    emit()
  }

  function dispose() {
    disposed = true
    stop()
  }

  return { startTask, recover, cancel, resume, abandon, dismiss, retryMapNextStep, dispose }
}
