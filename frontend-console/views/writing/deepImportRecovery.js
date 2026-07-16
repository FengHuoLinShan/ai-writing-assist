import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../shared/workflowProgress.js"
import { renderFixedProgress } from "../../shared/progressRenderer.js"

const AUTO_EXTRACTION_STAGES = {
  scenes: {
    taskType: "scene_auto_extraction",
    label: "场景（scene）自动提取",
    initialStep: "scene_segmentation",
    initialMessage: "正在提取场景...",
  },
  world_objects: {
    taskType: "world_object_auto_extraction",
    label: "世界对象与别名/关系自动提取",
    initialStep: "entity_extraction",
    initialMessage: "正在提取世界对象与别名/关系...",
  },
  plot_structure: {
    taskType: "plot_structure_auto_extraction",
    label: "剧情线自动提取",
    initialStep: "structure_analysis",
    initialMessage: "正在提取剧情线...",
  },
}

const AUTO_EXTRACTION_WORKFLOW_TYPES = Object.values(AUTO_EXTRACTION_STAGES).map((item) => item.taskType)

function stageConfig(stage) {
  return AUTO_EXTRACTION_STAGES[stage] || AUTO_EXTRACTION_STAGES.scenes
}

function stageFromWorkflowType(workflowType) {
  return Object.entries(AUTO_EXTRACTION_STAGES)
    .find(([, config]) => config.taskType === workflowType)?.[0] || "scenes"
}

function computeDeepImportPercent(task, result) {
  if (typeof task.progress === "number") {
    return task.progress <= 1
      ? Math.round(task.progress * 100)
      : Math.round(task.progress)
  }
  const phase = result.current_phase || ""
  const p1Completed = Number(result.phase1_completed_batches || 0)
  const p1Total = Number(result.phase1_total_batches || 0)
  const p2Completed = Number(result.phase2_completed_scenes || 0)
  const p2Total = Number(result.phase2_total_scenes || 0)
  if (phase === "phase0_plan") {
    return p1Total > 0 ? Math.min(10, Math.round((p1Completed / p1Total) * 10)) : 5
  }
  if (phase === "phase1a_scene_slicing") {
    return p1Total > 0 ? 10 + Math.min(10, Math.round((p1Completed / p1Total) * 10)) : 15
  }
  if (phase === "phase1b_enrichment") {
    return p1Total > 0 ? 20 + Math.min(10, Math.round((p1Completed / p1Total) * 10)) : 25
  }
  if (phase === "scene_commit") return 30
  if (phase === "entity_extraction") {
    return p2Total > 0 ? 40 + Math.min(40, Math.round((p2Completed / p2Total) * 40)) : 50
  }
  if (phase === "structure_analysis") return 80
  if (result.phase === "done" || task.status === "done") return 100
  return 0
}

function computeDeepImportStepLabel(result, currentLabel) {
  const phase = result.current_phase || ""
  if (phase === "phase0_plan") return "Phase 0/3: Scene 规划"
  if (phase === "phase1a_scene_slicing") return "Phase 1/3: Scene 切分"
  if (phase === "phase1b_enrichment") return "Phase 1/3: Scene 补全"
  if (phase === "scene_commit") return "Phase 1/3: Scene 写入"
  if (phase === "entity_extraction") return "Phase 2/3: 实体提取"
  if (phase === "structure_analysis") return "Phase 3/3: 结构分析"
  if (result.current_step) return `Phase: ${result.current_step}`
  return currentLabel
}

export function createDeepImportRecovery({
  state,
  api,
  toast,
  modal,
  esc,
  onPrompt,
  onStatusChange,
  onDone,
  mapNextStep = {},
}) {
  const projectState = state
  const modalApi = modal
  const escapeHtml = esc

  let taskId = null
  let progress = null
  let timer = null
  let completionTimer = null
  let pollFailures = 0
  let pollingGeneration = 0
  let pollingActive = false
  let taskProjectId = null
  let cancelPending = false
  let disposed = false
  let lifecycleGeneration = 0

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function getState() {
    return {
      taskId,
      progress: progress ? { ...progress } : null,
      polling: pollingActive,
      pollFailures,
    }
  }

  function notifyStatus() {
    onStatusChange?.(progress ? { ...progress } : null)
  }

  function notifyPrompt() {
    if (hasRecoveryPrompt(progress)) {
      onPrompt?.(progress ? { ...progress } : null)
    }
  }

  function hasRecoveryPrompt(p = progress) {
    if (p?.phase === "done" || p?.phase === "cancelled") return false
    const actions = Array.isArray(p?.availableActions) ? p.availableActions : []
    return Boolean(
      (actions.includes("resume") && actions.includes("abandon"))
      || p?.recoveryRequired
      || p?.interrupted
      || p?.recoverable,
    )
  }

  function buildProgressFromTask(task, result = {}, percent = null, stepLabel = "") {
    const recoverySummary = result.recovery_summary || result.recoverySummary || {}
    const hasActionContract = Array.isArray(task?.available_actions)
    const availableActions = hasActionContract ? task.available_actions : []
    const contractRecovery = availableActions.includes("resume")
      && availableActions.includes("abandon")
    return {
      phase: result.phase || task?.status || "running",
      workflowType: result.workflow_type || task?.task_type || "deep_import",
      workflowId: result.workflow_id
        || task?.meta?.workflow_id
        || progress?.workflowId
        || taskId
        || null,
      stage: result.stage || null,
      label: result.stage ? stageConfig(result.stage).label : null,
      step: result.current_step || "",
      message: result.message || task?.status || "自动提取中...",
      percent,
      stepLabel,
      degraded: result.degraded || false,
      degradedBatches: result.degraded_batches || [],
      phaseError: result.phase_error || result.error || task?.error_message || "",
      phaseErrors: result.phase_errors || [],
      qualityStatus: result.quality_status || (result.degraded ? "partial" : "pending"),
      auditSummary: result.audit_summary || result.auditSummary || {},
      snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary
        || result.audit_summary || result.auditSummary || {},
      currentPhase: result.current_phase || null,
      currentRound: result.current_round || null,
      currentChapterRange: result.current_chapter_range || null,
      currentChapter: result.current_chapter ?? null,
      currentSceneCandidateId: result.current_scene_candidate_id || null,
      currentWindow: result.current_window || null,
      currentOperation: result.current_operation || null,
      currentItem: result.current_item || {},
      qualityStats: result.quality_stats || {},
      assetSummary: result.asset_summary || result.assetSummary || {},
      phaseArtifacts: result.phase_artifacts || {},
      acceptanceChecks: result.acceptance_checks || [],
      diagnosticCounts: result.diagnostic_counts || {},
      throttleReasons: result.phase2_throttle_reasons || [],
      qualityRerun: result.quality_rerun || {},
      degradedReason: result.degraded_reason || "",
      phase1aFallback: result.phase1a_fallback || false,
      recoverySummary,
      interrupted: hasActionContract ? contractRecovery : (result.interrupted || false),
      recoverable: hasActionContract ? contractRecovery : (result.recoverable || false),
      recoveryRequired: hasActionContract
        ? contractRecovery
        : (result.recovery_required || false),
      lifecycle: task?.lifecycle || {},
      availableActions,
    }
  }

  function lifecycleContextIsCurrent(generation, projectId) {
    return !disposed
      && generation === lifecycleGeneration
      && currentProjectId() === projectId
  }

  function lifecycleIsCurrent(generation, projectId, expectedTaskId = taskId) {
    return lifecycleContextIsCurrent(generation, projectId)
      && taskId === expectedTaskId
  }

  async function prepareMapNextStep(projectId = taskProjectId || currentProjectId()) {
    if (progress?.workflowType !== "deep_import" || progress?.phase !== "done" || !projectId) {
      return null
    }
    const generation = lifecycleGeneration
    const expectedTaskId = taskId
    const workflowId = progress.workflowId || expectedTaskId || null
    try {
      const context = await api.world.getMapQuickCreateContext(projectId, true)
      if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return null
      const existingMaps = Array.isArray(context?.existing_maps) ? context.existing_maps : []
      const locations = Array.isArray(context?.locations) ? context.locations : []
      const candidateLocations = Array.isArray(context?.candidate_locations)
        ? context.candidate_locations
        : []
      let next = null
      if (existingMaps.length > 0) {
        let observationCount = 0
        try {
          const inbox = await api.world.listProjectMapObservationInbox(projectId, { limit: 1 })
          if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return null
          observationCount = Number(inbox?.total || 0)
        } catch {
          if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return null
          observationCount = 0
        }
        next = { action: "inbox", count: observationCount, projectId, workflowId }
      } else if (locations.length > 0) {
        next = { action: "quick-create", count: locations.length, projectId, workflowId }
      } else if (candidateLocations.length > 0) {
        let candidateCount = candidateLocations.length
        if (workflowId && typeof api.world.listEntities === "function") {
          const response = await api.world.listEntities({
            novel_id: projectId,
            display_state: "review",
            entity_type: "location",
            source: "deep_import",
            workflow_id: workflowId,
            skip: 0,
            limit: 1,
          })
          if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return null
          candidateCount = Number(response?.total ?? response?.items?.length ?? 0)
        }
        if (candidateCount > 0) {
          next = {
            action: "review-locations",
            count: candidateCount,
            projectId,
            workflowId,
          }
        }
      }
      progress = { ...progress, mapNextStep: next, mapNextStepError: "" }
      notifyStatus()
      return next
    } catch (err) {
      if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return null
      progress = {
        ...progress,
        mapNextStep: null,
        mapNextStepError: err?.message || "地图下一步加载失败",
      }
      notifyStatus()
      return null
    }
  }

  function normalizeProgress() {
    const p = progress || {}
    const needsRecovery = hasRecoveryPrompt(p)
    const status = p.phase === "failed"
        ? "failed"
        : p.phase === "done"
          ? "done"
          : p.phase === "cancelled"
            ? "cancelled"
            : "running"
    const degradedBatches = Array.isArray(p.degradedBatches) ? p.degradedBatches : []
    const phaseErrors = Array.isArray(p.phaseErrors) ? p.phaseErrors : []
    const phaseErrorText = phaseErrors
      .map((item) => item && (item.message || item.error_kind || item.phase || item.error))
      .filter(Boolean)
      .slice(0, 2)
      .join("；")
    const isPartial = p.qualityStatus === "partial"
    const warnings = []
    if (isPartial && !p.degraded) warnings.push("部分完成")
    if (p.degraded) warnings.push("部分批次降级完成")
    if (degradedBatches.length > 0) warnings.push(`降级批次：${degradedBatches.join(", ")}`)
    if (p.phaseError && status !== "failed") warnings.push(`阶段错误：${p.phaseError}`)
    if (phaseErrorText && status !== "failed") warnings.push(`阶段错误：${phaseErrorText}`)
    if (p.phase1aFallback) warnings.push("自动整理失败，已使用质量补强结果继续导入")

    const isStructureRunning = (
      p.currentPhase === "structure_analysis" && status === "running"
    )
    const progressValue = isStructureRunning
      ? null
      : (typeof p.percent === "number" ? p.percent : null)

    return normalizeTaskProgress({
      task_id: taskId || "deep_import",
      task_type: p.workflowType || "deep_import",
      status,
      progress: progressValue,
      error_message: status === "failed"
        ? (p.message || p.phaseError || phaseErrorText || "自动提取失败")
        : null,
      result: {
        message: needsRecovery
          ? "自动提取中断，需要选择继续或放弃恢复"
          : isStructureRunning
            ? "正在生成剧情结构（耗时较长，请耐心等待）..."
            : p.stepLabel || p.message || "自动提取中...",
        warnings,
        summary: isPartial ? "部分完成" : p.degraded ? "部分降级完成" : null,
        phase_artifacts: p.phaseArtifacts || {},
        acceptance_checks: p.acceptanceChecks || [],
        diagnostic_counts: p.diagnosticCounts || {},
        phase2_throttle_reasons: p.throttleReasons || [],
        quality_rerun: p.qualityRerun || {},
        asset_summary: p.assetSummary || {},
      },
    }, p.workflowType || "deep_import")
  }

  async function recover() {
    disposed = false
    lifecycleGeneration += 1
    const recoverGeneration = lifecycleGeneration
    const pid = currentProjectId()
    if (!pid) return

    const supportedTypes = new Set([
      "deep_import",
      "chapter_card_generation",
      ...AUTO_EXTRACTION_WORKFLOW_TYPES,
    ])
    let workflow = null
    try {
      workflow = recoverActiveWorkflows(pid)
        .find((item) => supportedTypes.has(item.workflowType))
    } catch {
      workflow = null
    }
    const recoveredTaskId = workflow?.taskId
    if (!recoveredTaskId) return

    try {
      const recoveredProjectId = workflow?.projectId || pid
      taskProjectId = recoveredProjectId
      const task = await api.tasks.get(recoveredTaskId, recoveredProjectId)
      if (!lifecycleContextIsCurrent(recoverGeneration, recoveredProjectId)) return
      if (!task || task.status === "done" || task.status === "failed" || task.status === "cancelled") {
        if (task) {
          const result = task.result || {}
          const workflowType = result.workflow_type || task.task_type || workflow?.workflowType || "deep_import"
          const stage = result.stage || workflow?.meta?.stage || stageFromWorkflowType(workflowType)
          const label = workflow?.label || stageConfig(stage).label
          const terminalPercent = computeDeepImportPercent(task, result)
          const recoveryProgress = buildProgressFromTask(
            task, result, task.status === "done" ? 100 : terminalPercent, "",
          )
          if (task.status !== "done" && hasRecoveryPrompt(recoveryProgress)) {
            taskId = recoveredTaskId
            progress = { ...recoveryProgress, workflowType, stage, label }
            notifyPrompt()
            notifyStatus()
            return
          }
          const isFailed = task.status === "failed"
          taskId = recoveredTaskId
          progress = {
            ...recoveryProgress,
            workflowType,
            stage,
            label,
            phase: isFailed ? "failed" : task.status === "cancelled" ? "cancelled" : "done",
            step: result.current_step || "",
            message: result.message || (isFailed ? `${label}失败` : `${label}完成`),
            percent: task.status === "done" ? 100 : terminalPercent,
            stepLabel: isFailed ? "失败" : task.status === "cancelled" ? "已取消" : "完成",
            degraded: result.degraded || false,
            degradedBatches: result.degraded_batches || [],
            phaseError: result.phase_error || result.error || task.error_message || "",
            phaseErrors: result.phase_errors || [],
            qualityStatus: result.quality_status || (result.degraded ? "partial" : "complete"),
            auditSummary: result.audit_summary || result.auditSummary || {},
            snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary
              || result.audit_summary || result.auditSummary || {},
          }
        }
        if (progress?.phase === "done") {
          const nextStep = await prepareMapNextStep(recoveredProjectId)
          if (!lifecycleIsCurrent(
            recoverGeneration,
            recoveredProjectId,
            recoveredTaskId,
          )) return
          if (!nextStep && !progress?.mapNextStepError) {
            clearWorkflow(recoveredTaskId)
          }
        }
        notifyStatus()
        return
      }
      taskId = recoveredTaskId
      taskProjectId = recoveredProjectId
      const result = task.result || {}
      const workflowType = result.workflow_type || task.task_type || workflow?.workflowType || "deep_import"
      const stage = result.stage || workflow?.meta?.stage || stageFromWorkflowType(workflowType)
      const label = workflow?.label || stageConfig(stage).label
      const recoveredPercent = computeDeepImportPercent(task, result)
      const recoveredStepLabel = workflowType === "deep_import"
        ? computeDeepImportStepLabel(result, label)
        : (result.current_step ? `Phase: ${result.current_step}` : label)
      const recoveredProgress = buildProgressFromTask(task, result, recoveredPercent, "")
      progress = {
        ...recoveredProgress,
        workflowType,
        stage,
        label,
        phase: result.phase || "running",
        step: result.current_step || "",
        message: result.message || `${label}中...`,
        percent: recoveredPercent,
        stepLabel: recoveredStepLabel,
        degraded: result.degraded || false,
        degradedBatches: result.degraded_batches || [],
        phaseError: result.phase_error || result.error || task.error_message || "",
        phaseErrors: result.phase_errors || [],
        qualityStatus: result.quality_status || (result.degraded ? "partial" : "pending"),
        auditSummary: result.audit_summary || result.auditSummary || {},
        snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary
          || result.audit_summary || result.auditSummary || {},
      }
      notifyStatus()
      if (hasRecoveryPrompt(progress)) {
        notifyPrompt()
        return
      }
      startPolling(workflow?.projectId || pid, false)
    } catch (err) {
      if (!lifecycleContextIsCurrent(recoverGeneration, workflow?.projectId || pid)) {
        return
      }
      if (err?.status === 404) {
        pausePolling()
        clearWorkflow(recoveredTaskId)
        taskId = null
        taskProjectId = null
        progress = null
        notifyStatus()
        return
      }
      taskId = recoveredTaskId
      taskProjectId = workflow?.projectId || pid
      progress = {
        workflowType: workflow?.workflowType || "deep_import",
        stage: workflow?.meta?.stage || stageFromWorkflowType(workflow?.workflowType),
        label: workflow?.label || "深度导入",
        phase: "running",
        step: "",
        message: "任务状态查询暂时不可用，正在重试...",
        percent: null,
        degraded: false,
        degradedBatches: [],
        phaseError: "",
        phaseErrors: [],
        qualityStatus: "pending",
        auditSummary: {},
        snapshotHealthSummary: {},
      }
      notifyStatus()
      startPolling(workflow?.projectId || pid, false)
    }
  }

  function startTask({
    taskId: newTaskId,
    workflowType,
    stage,
    label,
    startChapter,
    endChapter,
    highQuality = false,
  }) {
    disposed = false
    if (!newTaskId) return
    lifecycleGeneration += 1
    clearCompletionTimer()
    const config = stageConfig(stage || "scenes")
    taskId = newTaskId
    taskProjectId = currentProjectId()
    cancelPending = false
    progress = {
      workflowType: workflowType || config.taskType,
      stage: stage || "scenes",
      label: label || config.label,
      phase: "running",
      step: config.initialStep,
      message: config.initialMessage,
      percent: 0,
      degraded: false,
      degradedBatches: [],
      phaseError: "",
      phaseErrors: [],
      qualityStatus: "pending",
      auditSummary: {},
      snapshotHealthSummary: {},
    }
    persistActiveWorkflow({
      taskId: newTaskId,
      workflowType: workflowType || config.taskType,
      label: label || config.label,
      projectId: currentProjectId(),
      view: "writing",
      meta: {
        startChapter,
        endChapter,
        stage: stage || "scenes",
        highQuality,
      },
    })
    notifyStatus()
    startPolling(currentProjectId())
  }

  function startPolling(projectId = currentProjectId(), immediate = true) {
    pausePolling()
    pollingActive = true
    const generation = pollingGeneration
    const lifecycle = lifecycleGeneration
    const capturedProjectId = projectId
    const capturedTaskId = taskId
    let inFlight = false

    const scheduleNext = (delayMs) => {
      if (
        generation !== pollingGeneration
        || lifecycle !== lifecycleGeneration
        || disposed
        || !taskId
        || taskId !== capturedTaskId
        || currentProjectId() !== capturedProjectId
      ) {
        return
      }
      timer = setTimeout(poll, delayMs)
    }

    const poll = async () => {
      if (!taskId || taskId !== capturedTaskId) {
        pausePolling()
        return
      }
      if (currentProjectId() !== capturedProjectId || inFlight) {
        pausePolling()
        return
      }
      inFlight = true
      let nextDelay = null
      try {
        const task = await api.tasks.get(capturedTaskId, capturedProjectId)
        if (
          disposed
          || lifecycle !== lifecycleGeneration
          || generation !== pollingGeneration
          || taskId !== capturedTaskId
          || currentProjectId() !== capturedProjectId
        ) return
        const result = task.result || {}
        const currentWorkflowType = result.workflow_type || task.task_type
          || progress?.workflowType || "deep_import"
        const currentStage = result.stage || progress?.stage || stageFromWorkflowType(currentWorkflowType)
        const currentLabel = progress?.label || stageConfig(currentStage).label

        let percent = computeDeepImportPercent(task, result)
        let stepLabel = ""
        if (currentWorkflowType !== "deep_import") {
          if (task.status === "done" || result.phase === "done") percent = 100
          stepLabel = result.current_step ? `Phase: ${result.current_step}` : currentLabel
        } else {
          stepLabel = computeDeepImportStepLabel(result, currentLabel)
          if (task.status === "done" || result.phase === "done") percent = 100
        }

        progress = {
          ...buildProgressFromTask(task, result, percent, stepLabel),
          workflowType: currentWorkflowType,
          stage: currentStage,
          label: currentLabel,
          phase: result.phase || task.status,
          step: result.current_step || "",
          message: result.message || task.status,
          percent,
          stepLabel,
          degraded: result.degraded || false,
          degradedBatches: result.degraded_batches || [],
          phaseError: result.phase_error || result.error || task.error_message || "",
          phaseErrors: result.phase_errors || [],
          qualityStatus: result.quality_status || (result.degraded ? "partial" : "pending"),
          auditSummary: result.audit_summary || result.auditSummary || {},
          snapshotHealthSummary: result.snapshot_health_summary || result.snapshotHealthSummary
            || result.audit_summary || result.auditSummary || {},
        }

        if (task.status === "done" || result.phase === "done") {
          progress.percent = 100
          progress.phase = "done"
          pausePolling()
          if (progress.qualityStatus === "partial") {
            toast?.(`${currentLabel}部分完成，请查看降级原因`, "warning")
          } else {
            toast?.(`${currentLabel}完成！`, "success")
          }
          api.clearCache?.()
          const nextStep = await prepareMapNextStep(capturedProjectId)
          if (!lifecycleIsCurrent(lifecycle, capturedProjectId, capturedTaskId)) return
          if (nextStep || progress?.mapNextStepError) {
            await onDone?.()
          } else {
            clearWorkflow(capturedTaskId)
            taskId = null
            taskProjectId = null
            completionTimer = setTimeout(() => {
              completionTimer = null
              progress = null
              onDone?.()
            }, 1500)
          }
          return
        }
        if (hasRecoveryPrompt(progress)) {
          pausePolling()
          notifyPrompt()
          notifyStatus()
          return
        }
        if (task.status === "failed") {
          progress.phase = "failed"
          progress.phaseError = (
            result.phase_error || result.error || task.error_message || progress.message
          )
          pausePolling()
          toast?.(`${currentLabel}失败`, "error")
          notifyStatus()
          return
        }
        if (task.status === "cancelled") {
          progress.phase = "cancelled"
          pausePolling()
          toast?.(`${currentLabel}已取消`, "warning")
          notifyStatus()
          return
        }
        notifyStatus()
        pollFailures = 0
        nextDelay = 3000
      } catch (err) {
        if (
          disposed
          || lifecycle !== lifecycleGeneration
          || taskId !== capturedTaskId
          || currentProjectId() !== capturedProjectId
        ) return
        if (err?.status === 404) {
          pausePolling()
          clearWorkflow(capturedTaskId)
          taskId = null
          taskProjectId = null
          progress = null
          notifyStatus()
          toast?.("自动提取任务不存在，已清除本地恢复记录。", "warning")
          return
        }
        pollFailures += 1
        progress = {
          ...(progress || {}),
          message: `任务状态查询暂时不可用，正在重试（${pollFailures}）...`,
        }
        notifyStatus()
        const delays = [3000, 6000, 12000, 24000, 30000]
        nextDelay = delays[Math.min(pollFailures - 1, delays.length - 1)]
      } finally {
        inFlight = false
        if (nextDelay !== null) scheduleNext(nextDelay)
      }
    }
    pollFailures = 0
    if (immediate) poll()
    else scheduleNext(3000)
  }

  function pausePolling() {
    pollingGeneration += 1
    pollingActive = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function clearCompletionTimer() {
    if (completionTimer) {
      clearTimeout(completionTimer)
      completionTimer = null
    }
  }

  function clearWorkflow(id) {
    clearActiveWorkflow(id)
  }

  function renderCurrentPosition() {
    const p = progress || {}
    const fields = [
      ["阶段", p.currentPhase],
      ["Round", p.currentRound],
      ["章节范围", p.currentChapterRange],
      ["当前章节", p.currentChapter],
      ["当前 Scene 建议", p.currentSceneCandidateId],
      ["窗口", p.currentWindow],
      ["操作", p.currentOperation],
      ["当前项", p.currentItem?.kind],
      ["进度", p.currentItem?.total ? `${p.currentItem.completed || 0}/${p.currentItem.total}` : ""],
    ].filter(([, value]) => value !== null && value !== undefined && value !== "")
    if (fields.length === 0) return ""
    return `
      <div class="deep-import-current-position">
        ${fields.map(([label, value]) => `
          <span class="deep-import-current-position__item">${escapeHtml(label)}：${escapeHtml(value)}</span>
        `).join("")}
      </div>
    `
  }

  function renderQualityStats() {
    const p = progress || {}
    const stats = p.qualityStats && typeof p.qualityStats === "object"
      ? p.qualityStats
      : {}
    const currentKey = p.currentPhase && stats[p.currentPhase]
      ? p.currentPhase
      : pickQualityStatsKey(stats)
    const currentStats = currentKey ? stats[currentKey] : null
    if (!currentStats || typeof currentStats !== "object") return ""

    const statLabels = {
      total_batches: "请求数",
      total_windows: "窗口数",
      completed_batches: "已完成",
      completed_windows: "已完成",
      success: "成功",
      failed: "失败",
      final_422: "422",
      final_422_batches: "422",
      timeout: "timeout",
      schema_error: "schema",
      empty_result: "空结果",
      fallback_scene_count: "fallback Scene",
      fused_scene_count: "融合 Scene",
      needs_review_scene_count: "需要人工检查",
    }
    const orderedKeys = [
      "total_batches",
      "total_windows",
      "completed_batches",
      "completed_windows",
      "success",
      "failed",
      "final_422",
      "final_422_batches",
      "timeout",
      "schema_error",
      "empty_result",
      "fallback_scene_count",
      "fused_scene_count",
      "needs_review_scene_count",
    ]
    const items = orderedKeys
      .filter((key) => currentStats[key] !== undefined && currentStats[key] !== null)
      .map((key) => {
        return `<span class="deep-import-current-position__item">${escapeHtml(statLabels[key] || key)}：${escapeHtml(currentStats[key])}</span>`
      })
    const rate = currentStats.final_422_rate
    if (rate !== undefined && rate !== null) {
      const percent = Number(rate) <= 1 ? Number(rate) * 100 : Number(rate)
      items.push(`<span class="deep-import-current-position__item">422 率：${escapeHtml(`${percent.toFixed(0)}%`)}</span>`)
    }
    if (items.length === 0) return ""
    return `
      <div class="deep-import-current-position" aria-label="深度导入质量统计">
        ${items.join("")}
      </div>
    `
  }

  function pickQualityStatsKey(stats) {
    for (const key of ["phase1b", "phase1a", "phase0", "scene_commit"]) {
      if (stats[key]) return key
    }
    return Object.keys(stats)[0] || null
  }

  function renderRecoveryPrompt() {
    const p = progress || {}
    if (!hasRecoveryPrompt(p)) return ""
    const summary = p.recoverySummary && typeof p.recoverySummary === "object"
      ? p.recoverySummary
      : {}
    const summaryLabels = {
      last_checkpoint: "检查点",
      current_phase: "阶段",
      current_chapter: "当前章节",
      current_chapter_range: "章节范围",
      committed_scenes: "已写入 Scene",
      deprecated_scenes: "历史 Scene",
      committed_entities: "已写入实体",
      deprecated_entities: "历史实体",
      pending_scene_candidates: "待处理 Scene",
    }
    const summaryItems = Object.entries(summary)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .slice(0, 6)
      .map(([key, value]) => {
        const label = summaryLabels[key] || key
        return `<span class="deep-import-recovery__meta-item">${escapeHtml(label)}：${escapeHtml(value)}</span>`
      })
      .join("")
    return `
      <div class="deep-import-recovery" role="status">
        <div class="deep-import-recovery__body">
          <strong>自动提取需要恢复</strong>
          <span>检测到任务中断。可以继续原任务，或放弃恢复并交给后端清理本次自动写入资产。</span>
        </div>
        ${summaryItems ? `<div class="deep-import-recovery__meta">${summaryItems}</div>` : ""}
        <div class="deep-import-recovery__actions">
          <button class="btn btn-sm btn-primary writing-deep-import-btn" data-action="resume-deep-import">继续</button>
          <button class="btn btn-sm writing-deep-import-btn" data-action="abandon-deep-import">放弃恢复</button>
        </div>
      </div>
    `
  }

  function renderAuditSummary() {
    const summary = progress?.snapshotHealthSummary
      || progress?.auditSummary
      || {}
    if (summary && typeof summary.total_snapshots === "number") {
      const byStatus = summary.by_status || {}
      const total = summary.total_snapshots || 0
      if (total <= 0) return ""
      const succeeded = byStatus.succeeded || 0
      const failed = byStatus.failed || 0
      const running = byStatus.running || 0
      const stale = summary.stale_running_count || 0
      const runningText = running > 0 ? ` · 运行中 ${running}` : ""
      const staleText = stale > 0 ? ` · 超时 ${stale}` : ""
      return `
        <span class="writing-audit-summary">
          快照健康摘要：共 ${total} 条 · 成功 ${succeeded} · 失败 ${failed}${runningText}${staleText}
        </span>
        <button class="btn btn-sm writing-deep-import-btn" data-action="view-deep-import-audit">查看快照状态</button>
      `
    }

    const phaseSummaries = Object.values(summary).filter((item) => item && typeof item === "object")
    if (phaseSummaries.length === 0) return ""
    const total = phaseSummaries.reduce((sum, item) => sum + (item.snapshot_count || 0), 0)
    if (total <= 0) return ""
    const succeeded = phaseSummaries.reduce((sum, item) => sum + (item.succeeded || 0), 0)
    const failed = phaseSummaries.reduce((sum, item) => sum + (item.failed || 0), 0)
    const failedScenes = phaseSummaries
      .flatMap((item) => Array.isArray(item.failed_scenes) ? item.failed_scenes : [])
      .filter((item) => item !== null && item !== undefined)
    const failedSceneText = failedScenes.length > 0 ? ` · 失败 Scene：${failedScenes.join(", ")}` : ""
    return `
      <span class="writing-audit-summary">
        快照健康摘要：共 ${total} 条 · 成功 ${succeeded} · 失败 ${failed}${escapeHtml(failedSceneText)}
      </span>
      <button class="btn btn-sm writing-deep-import-btn" data-action="view-deep-import-audit">查看快照状态</button>
    `
  }

  function renderBar() {
    if (!progress) return ""
    const normalized = normalizeProgress()
    const actionsHtml = normalized.failed || normalized.cancelled || progress?.phase === "done"
      ? `<button class="btn btn-sm writing-deep-import-btn" data-action="dismiss-deep-import">关闭</button>`
      : `<button class="btn btn-sm writing-deep-import-btn" data-action="cancel-deep-import" ${cancelPending ? "disabled" : ""}>${cancelPending ? "取消中..." : "取消任务"}</button>`
    const recoveryHtml = renderRecoveryPrompt()
    const currentPositionHtml = renderCurrentPosition()
    const qualityStatsHtml = renderQualityStats()
    const aliveClass = normalized.terminal ? "" : "deep-import-progress--alive"
    return renderFixedProgress(normalized, {
      offset: 40,
      title: normalized.label || progress?.label || "自动提取",
      message: normalized.message,
      showTaskId: false,
      className: aliveClass,
      attentionRequired: Boolean(
        normalized.failed
        || progress?.recoveryRequired
        || progress?.mapNextStep,
      ),
      actionsHtml: [
        currentPositionHtml,
        qualityStatsHtml,
        recoveryHtml,
        renderMapNextStep(),
        renderAuditSummary(),
        actionsHtml,
      ].filter(Boolean).join(""),
    })
  }

  function renderMapNextStep() {
    const next = progress?.mapNextStep
    if (!next && progress?.mapNextStepError) {
      return `
        <div class="deep-import-recovery__actions" aria-label="地图下一步加载失败">
          <span class="writing-empty-hint">地图下一步暂时无法加载：${escapeHtml(progress.mapNextStepError)}</span>
          <button class="btn btn-sm btn-primary writing-deep-import-btn" data-action="retry-deep-import-map-next">
            重试
          </button>
        </div>
      `
    }
    if (!next) return ""
    const labels = {
      "quick-create": `一键创建地图（${next.count} 个地点）`,
      "review-locations": `先审核 ${next.count} 个地点`,
      inbox: next.count > 0 ? `查看地图收件箱（${next.count}）` : "查看地图收件箱",
    }
    return `
      <div class="deep-import-recovery__actions" aria-label="深度导入地图下一步">
        <span class="writing-empty-hint">地图资料已就绪，建议下一步：</span>
        <button class="btn btn-sm btn-primary writing-deep-import-btn" data-action="deep-import-map-next">
          ${escapeHtml(labels[next.action] || "查看地图")}
        </button>
      </div>
    `
  }

  async function runMapNextStep() {
    const next = progress?.mapNextStep
    if (!next) return false
    const generation = lifecycleGeneration
    const expectedTaskId = taskId
    const projectId = next.projectId || taskProjectId || currentProjectId()
    if (projectId && currentProjectId() !== projectId) {
      toast?.("当前项目已切换，请返回原项目继续", "warning")
      return false
    }
    try {
      if (next.action === "quick-create") {
        const opened = await mapNextStep.openQuickCreate?.(next)
        if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return false
        return opened !== false
      }
      if (next.action === "review-locations") {
        const opened = await mapNextStep.openReviewLocations?.({
          ...next,
          workflowId: next.workflowId || progress.workflowId,
        })
        if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return false
        if (opened === false) return false
        dismiss()
        return true
      }
      const opened = await mapNextStep.openInbox?.(next)
      if (!lifecycleIsCurrent(generation, projectId, expectedTaskId)) return false
      if (opened === false) return false
      dismiss()
      return true
    } catch (err) {
      toast?.(err?.message || "地图下一步打开失败，可重试", "error")
      return false
    }
  }

  function completeMapNextStep(expectedNext) {
    if (
      !expectedNext
      || progress?.mapNextStep !== expectedNext
      || (expectedNext.projectId && currentProjectId() !== expectedNext.projectId)
    ) {
      return false
    }
    dismiss()
    return true
  }

  async function retryMapNextStep() {
    return prepareMapNextStep(taskProjectId || currentProjectId())
  }

  function updateBar(container) {
    if (!container) return
    container.innerHTML = renderBar()
  }

  async function resume() {
    const currentTaskId = taskId
    if (!currentTaskId) return
    disposed = false
    lifecycleGeneration += 1
    const generation = lifecycleGeneration
    const projectId = taskProjectId || currentProjectId()
    try {
      const response = await api.imports.resumeDeepImport(currentTaskId)
      if (!lifecycleIsCurrent(generation, projectId, currentTaskId)) return
      const result = response?.result || {}
      taskId = response?.task_id || currentTaskId
      progress = {
        ...buildProgressFromTask(
          { status: response?.status || "running" },
          result,
          progress?.percent ?? null,
          progress?.stepLabel || "恢复进度中...",
        ),
        recoveryRequired: false,
        interrupted: false,
        recoverable: false,
      }
      startPolling()
      notifyStatus()
      toast?.("已继续深度导入恢复", "success")
    } catch (err) {
      if (!lifecycleIsCurrent(generation, projectId, currentTaskId)) return
      toast?.(err.message || "继续恢复失败", "error")
    }
  }

  async function abandon() {
    const currentTaskId = taskId
    if (!currentTaskId) return Promise.resolve()
    let confirmedWork = Promise.resolve()
    const message = "确认放弃深度导入恢复？后端会清理或将已写入的 Scene/实体转入历史，并停止继续恢复。"
    modalApi.confirmAction(message, () => {
      confirmedWork = (async () => {
        try {
          const response = await api.imports.abandonDeepImport(currentTaskId)
          const summary = response?.cleanup_summary || response?.cleanupSummary || {}
          const scenes = summary.deprecated_scenes ?? summary.scenes ?? 0
          const entities = summary.deprecated_entities ?? summary.entities ?? 0
          progress = null
          taskId = null
          taskProjectId = null
          cancelPending = false
          clearWorkflow(currentTaskId)
          notifyStatus()
          toast?.(`已放弃恢复：Scene ${scenes} 个，实体 ${entities} 个`, "success")
        } catch (err) {
          toast?.(err.message || "放弃恢复失败", "error")
        }
      })()
    }, "确认放弃")
    return confirmedWork
  }

  async function cancel() {
    const currentTaskId = taskId
    const projectId = taskProjectId || currentProjectId()
    if (!currentTaskId || !projectId || cancelPending) return Promise.resolve(false)
    if (["done", "failed", "cancelled"].includes(progress?.phase)) return Promise.resolve(false)

    let confirmedWork = Promise.resolve(false)
    modalApi.confirmAction("确认取消当前任务？已完成的阶段结果不会自动删除。", () => {
      confirmedWork = (async () => {
        pausePolling()
        cancelPending = true
        notifyStatus()
        try {
          await api.tasks.cancel(currentTaskId, projectId)
          cancelPending = false
          progress = {
            ...(progress || {}),
            phase: "cancelled",
            message: "任务已取消",
            stepLabel: "已取消",
          }
          notifyStatus()
          toast?.("当前任务已取消", "warning")
          return true
        } catch (err) {
          cancelPending = false
          notifyStatus()
          toast?.(err.message || "取消任务失败", "error")
          startPolling(projectId)
          return false
        }
      })()
    }, "确认取消")
    return confirmedWork
  }

  function dismiss() {
    lifecycleGeneration += 1
    pausePolling()
    clearCompletionTimer()
    const capturedTaskId = taskId
    progress = null
    taskId = null
    taskProjectId = null
    cancelPending = false
    clearWorkflow(capturedTaskId)
    notifyStatus()
  }

  function showAuditDetails() {
    const summary = progress?.snapshotHealthSummary
      || progress?.auditSummary
      || {}
    const phaseLabels = {
      entity_extraction: "Phase 2 实体提取",
      structure_analysis: "Phase 3 结构分析",
    }
    if (summary && typeof summary.total_snapshots === "number") {
      const byPhase = summary.by_phase || {}
      const latestFailure = summary.latest_failure
      const failureHtml = latestFailure
        ? `<div class="writing-audit-warning writing-audit-warning--spaced">最近失败：${escapeHtml(latestFailure.phase || "unknown")} · ${escapeHtml(latestFailure.error_kind || "failed")}</div>`
        : ""
      const retainedHtml = summary.retained_rendered_context_count
        ? `<div class="writing-audit-retention writing-audit-retention--spaced">完整上下文保留：${summary.retained_rendered_context_count} 条</div>`
        : ""
      const rows = Object.entries(byPhase)
        .filter(([, item]) => item && typeof item === "object")
        .map(([phase, item]) => `
          <div class="writing-audit-row">
            <div class="writing-audit-title">${escapeHtml(phaseLabels[phase] || phase)}</div>
            <div class="writing-audit-meta">
              快照 ${(item.running || 0) + (item.succeeded || 0) + (item.failed || 0)} 条 · 成功 ${item.succeeded || 0} · 失败 ${item.failed || 0} · 运行中 ${item.running || 0}
            </div>
          </div>
        `).join("")
      modalApi.showModalHtml(
        "深度导入快照状态",
        rows || failureHtml || retainedHtml
          ? `${rows}${failureHtml}${retainedHtml}`
          : '<p class="writing-empty-hint">暂无快照健康摘要</p>',
      )
      return
    }
    const rows = Object.entries(summary)
      .filter(([, item]) => item && typeof item === "object")
      .map(([phase, item]) => {
        const failedScenes = Array.isArray(item.failed_scenes) && item.failed_scenes.length > 0
          ? `<div class="writing-audit-warning">失败 Scene：${escapeHtml(item.failed_scenes.join(", "))}</div>`
          : ""
        const retention = item.retained_rendered_context_count
          ? `<div class="writing-audit-retention">完整上下文保留：${item.retained_rendered_context_count} 条</div>`
          : ""
        return `
          <div class="writing-audit-row">
            <div class="writing-audit-title">${escapeHtml(phaseLabels[phase] || phase)}</div>
            <div class="writing-audit-meta">
              快照 ${item.snapshot_count || 0} 条 · 成功 ${item.succeeded || 0} · 失败 ${item.failed || 0}
            </div>
            ${failedScenes}
            ${retention}
          </div>
        `
      }).join("")
    modalApi.showModalHtml("深度导入快照状态", rows || '<p class="writing-empty-hint">暂无快照健康摘要</p>')
  }

  function dispose() {
    disposed = true
    lifecycleGeneration += 1
    pausePolling()
    clearCompletionTimer()
  }

  return {
    recover,
    renderBar,
    updateBar,
    renderRecoveryPrompt,
    resume,
    abandon,
    cancel,
    showAuditDetails,
    runMapNextStep,
    completeMapNextStep,
    retryMapNextStep,
    dismiss,
    dispose,
    getState,
    startTask,
  }
}
