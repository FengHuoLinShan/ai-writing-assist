import { authorFacingStateText } from "./assetDisplayState.js"

const ACTIVE_WORKFLOWS_KEY = "novel_active_workflows_v1"

const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"])
const RUNNING_STATUSES = new Set(["pending", "running"])

export const TASK_CANCELLED_MESSAGE = "已停止后续处理，不会再排下一步；已保存的阶段结果仍保留。正在结束的远程请求可能不会瞬时断开。"

const WORKFLOW_LABELS = {
  deep_import: "深度导入",
  scene_auto_extraction: "从正文整理场景",
  smart_dedup_scan: "智能去重扫描",
  world_object_auto_extraction: "整理人物、设定与关系",
  world_entity_fusion_suggestions: "世界对象 AI 合并建议",
  plot_structure_auto_extraction: "从正文整理剧情线",
  map_observation_enrichment: "补充地图资料",
  publish_chapter: "设为正式正文",
  rag_reindex_novel: "修复查找资料",
  rag_retry_embeddings: "修复查找资料",
  plot_structure_generate: "生成剧情结构",
  outline_generate: "生成剧情结构",
  story_outline_generate: "AI 故事总览",
  outline_analyze: "AI 分析大纲",
  chapter_card_generation: "生成章节卡",
  chapter_scene_generate: "生成章节与场景结构",
  writing_generate: "生成正文",
  plot_analysis: "剧情分析",
}

const STATUS_LABELS = {
  pending: "等待执行",
  running: "运行中",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
  unknown: "状态未知",
}

const PHASE_MESSAGE_LABELS = {
  entity_extraction: "正在按场景提取人物、设定与关系",
  structure_analysis: "正在提取剧情结构",
}

const SCENE_PHASE_LABELS = {
  phase0_plan: { technical: "阶段 1", label: "规划场景范围" },
  phase1a_scene_slicing: { technical: "阶段 2", label: "划分场景边界" },
  phase1b_enrichment: { technical: "阶段 3", label: "补充场景资料" },
  phase1c_scene_fusion: { technical: "阶段 4", label: "整理相邻场景" },
  scene_commit: { technical: "最后一步", label: "保存整理结果" },
}

function scenePhaseMessage(result) {
  const phase = SCENE_PHASE_LABELS[result.current_phase]
  if (!phase) return null
  const prefix = `${phase.technical} · ${phase.label}`
  const item = safeObject(result.current_item)
  if (result.current_phase === "phase0_plan") {
    return `${prefix}｜正在准备章节窗口`
  }
  if (result.current_phase === "phase1a_scene_slicing") {
    const unit = item.completed != null && item.total
      ? `窗口 ${item.completed}/${item.total}`
      : "正在划分场景边界"
    return `${prefix}｜${unit}`
  }
  if (result.current_phase === "phase1b_enrichment") {
    const unit = item.completed != null && item.total
      ? `场景 ${item.completed}/${item.total}`
      : "正在补全叙事字段"
    return `${prefix}｜${unit}`
  }
  if (result.current_phase === "phase1c_scene_fusion") {
    const unit = item.completed != null && item.total
      ? `边界 ${item.completed}/${item.total}`
      : "正在检查相邻场景"
    return `${prefix}｜${unit}`
  }
  const count = item.count
    ?? safeObject(safeObject(result.phase_artifacts).phase1b_enrichment).counts?.candidate_count
  return `${prefix}｜${count != null ? `正在保存 ${count} 个场景` : "正在保存场景"}`
}

function scenePhaseSummary(result) {
  const timeline = safeArray(result.phase_timeline)
  const completed = [...new Set(timeline
    .filter((item) => item && ["completed", "degraded"].includes(item.status))
    .map((item) => SCENE_PHASE_LABELS[item.phase]?.technical)
    .filter(Boolean))]
  return completed.length ? `已完成 ${completed.join("、")}` : null
}

function nowIso() {
  return new Date().toISOString()
}

function safeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {}
}

function safeArray(value) {
  return Array.isArray(value) ? value : []
}

function readStorage(storage = globalThis.localStorage) {
  if (!storage) return []
  try {
    const parsed = JSON.parse(storage.getItem(ACTIVE_WORKFLOWS_KEY) || "[]")
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeStorage(items, storage = globalThis.localStorage) {
  if (!storage) return
  storage.setItem(ACTIVE_WORKFLOWS_KEY, JSON.stringify(items))
}

function workflowIdFor(workflow) {
  const projectId = workflow.projectId || workflow.novel_id || "global"
  const workflowType = workflow.workflowType || workflow.taskType || "task"
  const taskId = workflow.taskId || workflow.task_id || workflow.id
  return `${projectId}:${workflowType}:${taskId}`
}

function clampPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return null
  const scaled = value <= 1 ? value * 100 : value
  return Math.max(0, Math.min(100, Math.round(scaled)))
}

function inferMessage({ status, workflowType, result, meta, percent }) {
  if (status === "failed") return "任务失败"
  if (status === "cancelled") return TASK_CANCELLED_MESSAGE
  if (status === "done") return result.message || "任务完成"
  if (RUNNING_STATUSES.has(status)) {
    if (workflowType === "scene_auto_extraction") {
      const sceneMessage = scenePhaseMessage(result)
      if (sceneMessage) return sceneMessage
    }
    const phaseLabel = PHASE_MESSAGE_LABELS[result.current_phase]
    if (phaseLabel) return phaseLabel
  }
  if (result.message) return result.message
  if (meta.message) return meta.message
  if (workflowType === "deep_import") {
    if (percent != null) return "深度导入处理中"
    return "深度导入已提交，等待处理"
  }
  if (workflowType === "scene_auto_extraction") return "正在自动提取场景"
  if (workflowType === "smart_dedup_scan") return "正在扫描重复资产"
  if (workflowType === "world_object_auto_extraction") return "正在自动提取世界对象与别名/关系"
  if (workflowType === "world_entity_fusion_suggestions") return "正在生成世界对象合并建议"
  if (workflowType === "map_observation_enrichment") return "正在从既有场景补充地图资料"
  if (workflowType === "plot_structure_auto_extraction") return "正在自动提取剧情线"
  if (workflowType === "publish_chapter") {
    if (percent != null && percent < 50) return "正在存入 RAG 系统"
    return "正在创建历史状态"
  }
  if (workflowType === "rag_reindex_novel") return "正在逐章重建索引"
  if (workflowType === "rag_retry_embeddings") return "正在修复查找资料"
  if (workflowType === "plot_structure_generate" || workflowType === "outline_generate") return "正在生成剧情结构"
  if (workflowType === "outline_analyze") return "正在分析大纲结构"
  if (workflowType === "story_outline_generate") return "正在生成故事总览预览"
  if (
    workflowType === "chapter_card_generation"
    || workflowType === "chapter_scene_generate"
  ) return "正在生成章节与场景结构"
  if (workflowType === "writing_generate") return "正在生成正文"
  if (workflowType === "plot_analysis") return "正在分析剧情"
  return RUNNING_STATUSES.has(status) ? "任务运行中" : STATUS_LABELS[status] || "任务状态未知"
}

function collectWarnings(result, meta) {
  const warnings = []
  for (const source of [result.warnings, meta.warnings]) {
    if (Array.isArray(source)) warnings.push(...source.filter(Boolean))
  }
  const artifacts = safeObject(result.phase_artifacts)
  for (const [phase, artifact] of Object.entries(artifacts)) {
    const coverage = safeObject(artifact?.coverage)
    const repair = safeObject(artifact?.repair)
    const missing = Array.isArray(coverage.missing_chapters) ? coverage.missing_chapters : []
    if (missing.length > 0) warnings.push(`${phase} 缺少章节：${missing.slice(0, 8).join(", ")}`)
    if ((repair.attempts || 0) > 0) warnings.push(`${phase} 已尝试修复 ${repair.attempts} 次`)
    if (artifact?.status === "degraded") warnings.push(`${phase} 降级完成`)
  }
  for (const check of safeArray(result.acceptance_checks)) {
    if (!check || check.ok !== false) continue
    const phase = check.phase ? `${check.phase} ` : ""
    const message = check.message || check.name || "门禁未通过"
    warnings.push(`${phase}${message}`)
  }
  return warnings
}

function buildResultSummary(result, workflowType) {
  if (!result || typeof result !== "object") return null
  if (workflowType === "rag_reindex_novel") {
    const parts = []
    if (result.total_chapters != null) parts.push(`${result.total_chapters} 章`)
    if (result.chunks_created != null) parts.push(`${result.chunks_created} 个片段`)
    if (result.embedding_failed_count) parts.push(`${result.embedding_failed_count} 项资料仍待修复`)
    return parts.length ? parts.join("，") : null
  }
  if (workflowType === "rag_retry_embeddings") {
    const parts = []
    if (result.total != null) parts.push(`${result.total} 个片段`)
    if (result.succeeded != null) parts.push(`${result.succeeded} 个成功`)
    if (result.failed != null) parts.push(`${result.failed} 个失败`)
    return parts.length ? parts.join("，") : null
  }
  if (workflowType === "plot_structure_generate" || workflowType === "outline_generate") {
    const parts = []
    if (result.total_threads != null) parts.push(`剧情线 ${result.total_threads}`)
    if (result.total_arcs != null) parts.push(`篇章纲 ${result.total_arcs}`)
    if (result.total_scenes != null) parts.push(`场景 ${result.total_scenes}`)
    return parts.length ? parts.join("，") : result.summary || null
  }
  if (workflowType === "chapter_scene_generate") {
    if (result.total_scenes != null) return `场景 ${result.total_scenes}`
    return result.summary || null
  }
  if (workflowType === "smart_dedup_scan") {
    const parts = []
    if (result.total_assets_scanned != null) parts.push(`扫描 ${result.total_assets_scanned}`)
    if (result.suggestion_count != null) parts.push(`建议 ${result.suggestion_count}`)
    if (result.estimated_duplicate_count != null) parts.push(`疑似重复 ${result.estimated_duplicate_count}`)
    return parts.length ? parts.join("，") : result.summary || null
  }
  if (workflowType === "world_entity_fusion_suggestions") {
    if (result.suggestion_count != null) return `建议 ${result.suggestion_count} 条`
    return result.summary || null
  }
  if (workflowType === "map_observation_enrichment") {
    const parts = []
    if (result.scene_count != null) parts.push(`检查 ${result.scene_count} 个场景`)
    if (result.candidate_created_count != null) parts.push(`新增候选 ${result.candidate_created_count} 条`)
    if (result.candidate_reused_count) parts.push(`复用候选 ${result.candidate_reused_count} 条`)
    if (result.uncertain_count) parts.push(`待判定 ${result.uncertain_count} 条`)
    return parts.length ? parts.join("，") : result.summary || null
  }
  if (workflowType === "deep_import") {
    if (result.summary) return result.summary
    const steps = Array.isArray(result.completed_steps) ? result.completed_steps.length : null
    return steps != null ? `已完成 ${steps} 个阶段` : null
  }
  if (workflowType === "scene_auto_extraction") {
    if (result.summary) return result.summary
    return scenePhaseSummary(result)
  }
  if (
    workflowType === "world_object_auto_extraction"
    || workflowType === "plot_structure_auto_extraction"
  ) {
    if (result.summary) return result.summary
    const steps = Array.isArray(result.completed_steps) ? result.completed_steps.length : null
    return steps != null ? `已完成 ${steps} 个阶段` : null
  }
  return result.summary || result.title || null
}

export function sanitizeTaskErrorMessage(message, workflowType = "task") {
  const text = typeof message === "string" ? message.trim() : ""
  if (!text) return null
  const technicalMarkers = [
    "DBAPIError",
    "SQLAlchemy",
    "asyncpg.",
    "InFailedSQLTransactionError",
    "current transaction is aborted",
    "[SQL:",
    "UPDATE async_tasks",
    "Traceback",
  ]
  const importTechnicalMarkers = ["psycopg", "stack trace"]
  const isImportTechnicalError = workflowType === "import"
    && [...technicalMarkers, ...importTechnicalMarkers].some(
      (marker) => text.toLowerCase().includes(marker.toLowerCase()),
    )
  if (technicalMarkers.some((marker) => text.includes(marker)) || isImportTechnicalError) {
    if (workflowType === "publish_chapter") {
      return "发布失败。工作稿已保存，请稍后重试。"
    }
    if (workflowType === "import") {
      return "导入失败，请检查文件后重试。"
    }
    return "后台任务失败，请稍后重试。"
  }
  return text
}

export function normalizeTaskProgress(task, workflowType = undefined) {
  const raw = safeObject(task)
  const result = safeObject(raw.result)
  const meta = safeObject(raw.meta)
  const type = workflowType || raw.task_type || meta.workflowType || meta.task_type || "task"
  const status = raw.status || "pending"
  let percent = clampPercent(raw.progress)

  if (status === "done") percent = 100

  if (
    type === "scene_auto_extraction"
    && RUNNING_STATUSES.has(status)
    && (!result.current_phase || result.current_phase === "phase0_plan")
  ) percent = null

  const hasPercent = percent != null
  const label = WORKFLOW_LABELS[type] || meta.label || "后台任务"
  const message = authorFacingStateText(inferMessage({ status, workflowType: type, result, meta, percent }))

  const rawErrorMessage = status === "failed" || status === "unknown"
    ? raw.error_message || result.error_message || result.error || null
    : null
  const lifecycle = safeObject(raw.lifecycle)
  const recoveryRequired = Boolean(
    lifecycle.recovery_required
    || result.recovery_required
    || meta.recovery_required,
  )
  const availableActions = Array.isArray(raw.available_actions)
    ? raw.available_actions.filter(Boolean)
    : recoveryRequired
      ? ["resume", "abandon"]
      : status === "failed"
        ? ["dismiss"]
        : RUNNING_STATUSES.has(status)
          ? ["cancel"]
          : ["dismiss"]

  return {
    id: raw.id || raw.task_id || meta.task_id || null,
    taskId: raw.task_id || raw.id || meta.task_id || null,
    taskType: raw.task_type || meta.task_type || type,
    workflowType: type,
    label,
    status,
    statusLabel: STATUS_LABELS[status] || status,
    message,
    percent,
    hasPercent,
    indeterminate: RUNNING_STATUSES.has(status) && !hasPercent,
    done: status === "done",
    failed: status === "failed",
    cancelled: status === "cancelled",
    terminal: TERMINAL_STATUSES.has(status),
    stateUnknown: status === "unknown",
    errorMessage: sanitizeTaskErrorMessage(rawErrorMessage, type),
    warnings: collectWarnings(result, meta).map(authorFacingStateText),
    resultSummary: authorFacingStateText(buildResultSummary(result, type)),
    assetSummary: safeObject(result.asset_summary || result.assetSummary),
    phaseArtifacts: safeObject(result.phase_artifacts),
    progressEvents: safeArray(result.progress_events),
    acceptanceChecks: safeArray(result.acceptance_checks),
    phaseTimeline: safeArray(result.phase_timeline),
    diagnosticCounts: safeObject(result.diagnostic_counts),
    phaseErrors: safeArray(result.phase_errors),
    currentPhase: result.current_phase || null,
    currentOperation: result.current_operation || null,
    createdAt: raw.created_at || meta.createdAt || null,
    startedAt: raw.started_at || null,
    updatedAt: raw.updated_at || raw.heartbeat_at || null,
    heartbeatAt: raw.heartbeat_at || null,
    attempt: Number.isFinite(raw.attempt) ? raw.attempt : 0,
    maxAttempts: Number.isFinite(raw.max_attempts) ? raw.max_attempts : 1,
    stale: Boolean(raw.stale),
    lifecycle,
    recoveryRequired,
    availableActions,
    raw,
  }
}

export function persistActiveWorkflow(workflow, storage = globalThis.localStorage) {
  if (!workflow || !(workflow.taskId || workflow.task_id || workflow.id)) return null
  const normalized = {
    id: workflow.id || workflowIdFor(workflow),
    taskId: workflow.taskId || workflow.task_id || workflow.id,
    workflowType: workflow.workflowType || workflow.taskType || workflow.task_type || "task",
    label: workflow.label || null,
    projectId: workflow.projectId || workflow.novel_id || null,
    view: workflow.view || null,
    meta: safeObject(workflow.meta),
    createdAt: workflow.createdAt || nowIso(),
    updatedAt: nowIso(),
  }
  const items = readStorage(storage).filter((item) => item.id !== normalized.id)
  items.push(normalized)
  writeStorage(items, storage)
  return normalized
}

export function clearActiveWorkflow(idOrTaskId, storage = globalThis.localStorage) {
  if (!idOrTaskId || !storage) return
  const items = readStorage(storage).filter((item) => (
    item.id !== idOrTaskId && item.taskId !== idOrTaskId && item.task_id !== idOrTaskId
  ))
  writeStorage(items, storage)
}

export function recoverActiveWorkflows(projectId = null, storage = globalThis.localStorage) {
  const items = readStorage(storage)

  const deduped = []
  const seen = new Set()
  for (const item of items) {
    const id = item.id || workflowIdFor(item)
    if (!item.taskId || seen.has(id)) continue
    seen.add(id)
    deduped.push({ ...item, id })
  }
  writeStorage(deduped, storage)

  return projectId
    ? deduped.filter((item) => !item.projectId || item.projectId === projectId)
    : deduped
}

export function pollTaskProgress({
  taskId,
  workflowType,
  novelId = null,
  intervalMs = 1500,
  apiClient = globalThis.api,
  pauseWhenHidden = true,
  onUpdate,
  onDone,
  onFailed,
} = {}) {
  if (!taskId) throw new Error("taskId is required")
  if (!apiClient?.tasks?.get) throw new Error("api.tasks.get is required")

  let stopped = false
  let timer = null
  let inFlight = false
  const visibilityDoc = typeof document !== "undefined" ? document : null
  const canPauseForVisibility = Boolean(
    pauseWhenHidden
    && visibilityDoc
    && typeof visibilityDoc.addEventListener === "function"
    && typeof visibilityDoc.removeEventListener === "function",
  )

  const isHidden = () => canPauseForVisibility && visibilityDoc.visibilityState === "hidden"

  const clearTimer = () => {
    if (timer) clearTimeout(timer)
    timer = null
  }

  const scheduleNext = () => {
    if (stopped || isHidden()) return
    clearTimer()
    timer = setTimeout(tick, intervalMs)
  }

  const handleVisibilityChange = () => {
    if (stopped) return
    if (isHidden()) {
      clearTimer()
      return
    }
    clearTimer()
    tick()
  }

  const stop = () => {
    stopped = true
    clearTimer()
    if (canPauseForVisibility) {
      visibilityDoc.removeEventListener("visibilitychange", handleVisibilityChange)
    }
  }

  const tick = async () => {
    if (stopped || inFlight) return
    if (isHidden()) {
      clearTimer()
      return
    }
    inFlight = true
    try {
      const task = novelId
        ? await apiClient.tasks.get(taskId, novelId)
        : await apiClient.tasks.get(taskId)
      if (stopped) return
      const progress = normalizeTaskProgress(task, workflowType)
      onUpdate?.(progress, task)
      if (progress.done) {
        stop()
        onDone?.(progress, task)
        return
      }
      if (progress.failed || progress.cancelled) {
        stop()
        onFailed?.(progress, task)
        return
      }
    } catch (err) {
      if (stopped) return
      const progress = normalizeTaskProgress({
        id: taskId,
        task_id: taskId,
        task_type: workflowType,
        status: "unknown",
        error_message: err.message || "任务状态查询失败",
      }, workflowType)
      onUpdate?.(progress, null)
    } finally {
      inFlight = false
    }
    scheduleNext()
  }

  if (canPauseForVisibility) {
    visibilityDoc.addEventListener("visibilitychange", handleVisibilityChange)
  }
  tick()
  return { stop }
}

export const workflowProgressStorageKey = ACTIVE_WORKFLOWS_KEY
