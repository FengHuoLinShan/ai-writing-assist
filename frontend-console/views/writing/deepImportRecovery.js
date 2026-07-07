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
  if (phase === "scene_commit") return 35
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
}) {
  const projectState = state
  const modalApi = modal
  const escapeHtml = esc

  let taskId = null
  let progress = null
  let timer = null
  let pollFailures = 0

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function getState() {
    return {
      taskId,
      progress: progress ? { ...progress } : null,
      polling: Boolean(timer),
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
    return Boolean(p?.recoveryRequired || p?.interrupted || p?.recoverable)
  }

  function buildProgressFromTask(task, result = {}, percent = null, stepLabel = "") {
    const recoverySummary = result.recovery_summary || result.recoverySummary || {}
    return {
      phase: result.phase || task?.status || "running",
      workflowType: result.workflow_type || task?.task_type || "deep_import",
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
      degradedReason: result.degraded_reason || "",
      phase1aFallback: result.phase1a_fallback || false,
      recoverySummary,
      interrupted: result.interrupted || false,
      recoverable: result.recoverable || false,
      recoveryRequired: result.recovery_required || false,
    }
  }

  function normalizeProgress() {
    const p = progress || {}
    const needsRecovery = hasRecoveryPrompt(p)
    const status = needsRecovery
      ? "running"
      : p.phase === "failed"
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
      },
    }, p.workflowType || "deep_import")
  }

  async function recover() {
    const pid = currentProjectId()
    if (!pid) return

    const supportedTypes = new Set(["deep_import", ...AUTO_EXTRACTION_WORKFLOW_TYPES])
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
      const task = await api.tasks.get(recoveredTaskId)
      if (!task || task.status === "done" || task.status === "failed" || task.status === "cancelled") {
        if (task) {
          const result = task.result || {}
          const workflowType = result.workflow_type || task.task_type || workflow?.workflowType || "deep_import"
          const stage = result.stage || workflow?.meta?.stage || stageFromWorkflowType(workflowType)
          const label = workflow?.label || stageConfig(stage).label
          const recoveryProgress = buildProgressFromTask(
            task, result, task.status === "failed" ? 0 : 100, "",
          )
          if (hasRecoveryPrompt(recoveryProgress)) {
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
            percent: isFailed ? 0 : 100,
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
        clearWorkflow(recoveredTaskId)
        notifyStatus()
        return
      }
      taskId = recoveredTaskId
      const result = task.result || {}
      const workflowType = result.workflow_type || task.task_type || workflow?.workflowType || "deep_import"
      const stage = result.stage || workflow?.meta?.stage || stageFromWorkflowType(workflowType)
      const label = workflow?.label || stageConfig(stage).label
      const recoveredPercent = computeDeepImportPercent(task, result)
      const recoveredStepLabel = workflowType === "deep_import"
        ? computeDeepImportStepLabel(result, label)
        : (result.current_step ? `Phase: ${result.current_step}` : label)
      progress = {
        ...buildProgressFromTask(task, result, recoveredPercent, ""),
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
      startPolling()
    } catch {
      clearWorkflow(recoveredTaskId)
      notifyStatus()
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
    if (!newTaskId) return
    const config = stageConfig(stage || "scenes")
    taskId = newTaskId
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
      meta: { startChapter, endChapter, stage: stage || "scenes", highQuality },
    })
    notifyStatus()
    startPolling()
  }

  function startPolling() {
    pausePolling()
    const capturedProjectId = currentProjectId()
    const capturedTaskId = taskId
    const poll = async () => {
      if (!taskId || taskId !== capturedTaskId) {
        stopPolling()
        return
      }
      try {
        const task = await api.tasks.get(taskId)
        const result = task.result || {}
        const steps = result.completed_steps || []
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

        if (currentProjectId() !== capturedProjectId) {
          stopPolling()
          return
        }

        if (hasRecoveryPrompt(progress)) {
          pausePolling()
          notifyPrompt()
          notifyStatus()
          return
        }

        if (task.status === "done" || result.phase === "done") {
          progress.percent = 100
          progress.phase = "done"
          stopPolling()
          if (progress.qualityStatus === "partial") {
            toast?.(`${currentLabel}部分完成，请查看降级原因`, "warning")
          } else {
            toast?.(`${currentLabel}完成！`, "success")
          }
          api.clearCache?.()
          setTimeout(() => {
            progress = null
            onDone?.()
          }, 1500)
          return
        }
        if (task.status === "failed") {
          progress.phase = "failed"
          progress.phaseError = (
            result.phase_error || result.error || task.error_message || progress.message
          )
          stopPolling()
          toast?.(`${currentLabel}失败`, "error")
          setTimeout(() => {
            progress = null
            notifyStatus()
          }, 5000)
          return
        }
        notifyStatus()
        pollFailures = 0
      } catch (err) {
        pollFailures += 1
        if (pollFailures >= 5) {
          stopPolling()
          toast?.(`自动提取状态轮询连续失败 ${pollFailures} 次，已停止。请刷新后重试。`, "error")
        }
      }
    }
    pollFailures = 0
    timer = setInterval(poll, 3000)
  }

  function pausePolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function stopPolling() {
    pausePolling()
    const capturedTaskId = taskId
    taskId = null
    clearWorkflow(capturedTaskId)
  }

  function clearWorkflow(id) {
    clearActiveWorkflow(id)
    try { localStorage.removeItem("novel_deepImportTaskId") } catch {} // eslint-disable-line no-empty
  }

  function renderCurrentPosition() {
    const p = progress || {}
    const fields = [
      ["阶段", p.currentPhase],
      ["Round", p.currentRound],
      ["章节范围", p.currentChapterRange],
      ["当前章节", p.currentChapter],
      ["Scene candidate", p.currentSceneCandidateId],
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
      needs_review_scene_count: "待复核",
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
      deprecated_scenes: "已废弃 Scene",
      committed_entities: "已写入实体",
      deprecated_entities: "已废弃实体",
      pending_scene_candidates: "待处理候选",
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
          <button class="btn btn-sm btn-primary" data-action="resume-deep-import" style="font-size:11px;">继续</button>
          <button class="btn btn-sm" data-action="abandon-deep-import" style="font-size:11px;">放弃恢复</button>
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
        <span style="font-size:11px;color:var(--text-dim);margin-right:8px;">
          快照健康摘要：共 ${total} 条 · 成功 ${succeeded} · 失败 ${failed}${runningText}${staleText}
        </span>
        <button class="btn btn-sm" data-action="view-deep-import-audit" style="font-size:11px;">查看快照状态</button>
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
      <span style="font-size:11px;color:var(--text-dim);margin-right:8px;">
        快照健康摘要：共 ${total} 条 · 成功 ${succeeded} · 失败 ${failed}${escapeHtml(failedSceneText)}
      </span>
      <button class="btn btn-sm" data-action="view-deep-import-audit" style="font-size:11px;">查看快照状态</button>
    `
  }

  function renderBar() {
    if (!progress) return ""
    const normalized = normalizeProgress()
    const actionsHtml = normalized.failed
      ? `<button class="btn btn-sm" data-action="dismiss-deep-import" style="font-size:11px;">关闭</button>`
      : ""
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
      actionsHtml: [
        currentPositionHtml,
        qualityStatsHtml,
        recoveryHtml,
        renderAuditSummary(),
        actionsHtml,
      ].filter(Boolean).join(""),
    })
  }

  function updateBar(container) {
    if (!container) return
    container.innerHTML = renderBar()
  }

  async function resume() {
    const currentTaskId = taskId
    if (!currentTaskId) return
    try {
      const response = await api.imports.resumeDeepImport(currentTaskId)
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
      toast?.(err.message || "继续恢复失败", "error")
    }
  }

  async function abandon() {
    const currentTaskId = taskId
    if (!currentTaskId) return Promise.resolve()
    let confirmedWork = Promise.resolve()
    const message = "确认放弃深度导入恢复？后端会删除/废弃已写入的 Scene/实体，并停止继续恢复。"
    modalApi.confirmAction(message, () => {
      confirmedWork = (async () => {
        try {
          const response = await api.imports.abandonDeepImport(currentTaskId)
          const summary = response?.cleanup_summary || response?.cleanupSummary || {}
          const scenes = summary.deprecated_scenes ?? summary.scenes ?? 0
          const entities = summary.deprecated_entities ?? summary.entities ?? 0
          progress = null
          taskId = null
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

  function dismiss() {
    pausePolling()
    const capturedTaskId = taskId
    progress = null
    taskId = null
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
        ? `<div style="color:var(--warning);font-size:11px;margin-top:8px;">最近失败：${escapeHtml(latestFailure.phase || "unknown")} · ${escapeHtml(latestFailure.error_kind || "failed")}</div>`
        : ""
      const retainedHtml = summary.retained_rendered_context_count
        ? `<div style="color:var(--text-dim);font-size:11px;margin-top:8px;">完整上下文保留：${summary.retained_rendered_context_count} 条</div>`
        : ""
      const rows = Object.entries(byPhase)
        .filter(([, item]) => item && typeof item === "object")
        .map(([phase, item]) => `
          <div style="padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="font-weight:600;margin-bottom:4px;">${escapeHtml(phaseLabels[phase] || phase)}</div>
            <div style="font-size:12px;color:var(--text-dim);">
              快照 ${(item.running || 0) + (item.succeeded || 0) + (item.failed || 0)} 条 · 成功 ${item.succeeded || 0} · 失败 ${item.failed || 0} · 运行中 ${item.running || 0}
            </div>
          </div>
        `).join("")
      modalApi.showModalHtml(
        "深度导入快照状态",
        rows || failureHtml || retainedHtml
          ? `${rows}${failureHtml}${retainedHtml}`
          : '<p style="color:var(--text-dim);">暂无快照健康摘要</p>',
      )
      return
    }
    const rows = Object.entries(summary)
      .filter(([, item]) => item && typeof item === "object")
      .map(([phase, item]) => {
        const failedScenes = Array.isArray(item.failed_scenes) && item.failed_scenes.length > 0
          ? `<div style="color:var(--warning);font-size:11px;margin-top:4px;">失败 Scene：${escapeHtml(item.failed_scenes.join(", "))}</div>`
          : ""
        const retention = item.retained_rendered_context_count
          ? `<div style="color:var(--text-dim);font-size:11px;margin-top:4px;">完整上下文保留：${item.retained_rendered_context_count} 条</div>`
          : ""
        return `
          <div style="padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="font-weight:600;margin-bottom:4px;">${escapeHtml(phaseLabels[phase] || phase)}</div>
            <div style="font-size:12px;color:var(--text-dim);">
              快照 ${item.snapshot_count || 0} 条 · 成功 ${item.succeeded || 0} · 失败 ${item.failed || 0}
            </div>
            ${failedScenes}
            ${retention}
          </div>
        `
      }).join("")
    modalApi.showModalHtml("深度导入快照状态", rows || '<p style="color:var(--text-dim);">暂无快照健康摘要</p>')
  }

  function dispose() {
    pausePolling()
  }

  return {
    recover,
    renderBar,
    updateBar,
    renderRecoveryPrompt,
    resume,
    abandon,
    showAuditDetails,
    dismiss,
    dispose,
    getState,
    startTask,
  }
}
