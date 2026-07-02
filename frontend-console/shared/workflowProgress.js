const ACTIVE_WORKFLOWS_KEY = "novel_active_workflows_v1"
const LEGACY_DEEP_IMPORT_KEY = "novel_deepImportTaskId"
const LEGACY_WORLD_EXTRACT_KEY = "novel_world_extract_task"

const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"])
const RUNNING_STATUSES = new Set(["pending", "running"])

const WORKFLOW_LABELS = {
  deep_import: "深度导入",
  scene_auto_extraction: "场景（scene）自动提取",
  scene_cross_chapter_detection: "跨章 Scene 识别",
  smart_dedup_scan: "智能去重扫描",
  world_object_auto_extraction: "世界对象与别名/关系自动提取",
  world_entity_fusion_suggestions: "世界对象 AI 合并建议",
  plot_structure_auto_extraction: "剧情线自动提取",
  publish_chapter: "发布正文",
  rag_reindex_novel: "重建 RAG 索引",
  rag_retry_embeddings: "重试失败向量",
  world_entity_extraction: "补抽世界对象",
  plot_structure_generate: "生成剧情结构",
  chapter_card_generation: "生成章节卡",
  writing_generate: "生成正文",
  plot_analysis: "剧情分析",
}

const STATUS_LABELS = {
  pending: "等待执行",
  running: "运行中",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
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

function inferDeepImportPercent(result) {
  const completedSteps = Array.isArray(result.completed_steps) ? result.completed_steps : []
  const knownSteps = ["extract_entities", "sync_characters", "generate_outline"]
  if (completedSteps.length > 0) {
    return clampPercent(completedSteps.length / knownSteps.length)
  }

  const batch = safeObject(result.batch_progress)
  const completed = Number(batch.completed || batch.completed_batches || 0)
  const total = Number(batch.total || batch.total_batches || 0)
  if (total > 0) return clampPercent(completed / total)

  return null
}

function inferMessage({ status, workflowType, result, meta, percent }) {
  if (result.message) return result.message
  if (meta.message) return meta.message
  if (status === "failed") return "任务失败"
  if (status === "cancelled") return "任务已取消"
  if (status === "done") return "任务完成"
  if (workflowType === "deep_import") {
    if (percent != null) return "深度导入处理中"
    return "深度导入已提交，等待处理"
  }
  if (workflowType === "scene_auto_extraction") return "正在自动提取场景"
  if (workflowType === "scene_cross_chapter_detection") return "正在识别跨章 Scene"
  if (workflowType === "smart_dedup_scan") return "正在扫描重复资产"
  if (workflowType === "world_object_auto_extraction") return "正在自动提取世界对象与别名/关系"
  if (workflowType === "world_entity_fusion_suggestions") return "正在生成世界对象合并建议"
  if (workflowType === "plot_structure_auto_extraction") return "正在自动提取剧情线"
  if (workflowType === "publish_chapter") {
    if (percent != null && percent < 50) return "正在存入 RAG 系统"
    return "正在创建历史状态"
  }
  if (workflowType === "rag_reindex_novel") return "正在逐章重建索引"
  if (workflowType === "rag_retry_embeddings") return "正在重试失败向量"
  if (workflowType === "world_entity_extraction") return "正在抽取世界对象"
  if (workflowType === "plot_structure_generate") return "正在生成剧情结构"
  if (workflowType === "chapter_card_generation") return "正在生成章节卡"
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
    if (result.embedding_failed_count) parts.push(`${result.embedding_failed_count} 个嵌入失败`)
    return parts.length ? parts.join("，") : null
  }
  if (workflowType === "rag_retry_embeddings") {
    const parts = []
    if (result.total != null) parts.push(`${result.total} 个片段`)
    if (result.succeeded != null) parts.push(`${result.succeeded} 个成功`)
    if (result.failed != null) parts.push(`${result.failed} 个失败`)
    return parts.length ? parts.join("，") : null
  }
  if (workflowType === "world_entity_extraction") {
    const parts = []
    if (result.total_created != null) parts.push(`新增 ${result.total_created}`)
    if (result.total_skipped != null) parts.push(`跳过 ${result.total_skipped}`)
    return parts.length ? parts.join("，") : null
  }
  if (workflowType === "scene_cross_chapter_detection") {
    if (result.suggestion_count != null) return `建议 ${result.suggestion_count} 条`
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
  if (workflowType === "deep_import") {
    if (result.summary) return result.summary
    const steps = Array.isArray(result.completed_steps) ? result.completed_steps.length : null
    return steps != null ? `已完成 ${steps} 个阶段` : null
  }
  if (
    workflowType === "scene_auto_extraction"
    || workflowType === "world_object_auto_extraction"
    || workflowType === "plot_structure_auto_extraction"
  ) {
    if (result.summary) return result.summary
    const steps = Array.isArray(result.completed_steps) ? result.completed_steps.length : null
    return steps != null ? `已完成 ${steps} 个阶段` : null
  }
  return result.summary || result.title || null
}

export function normalizeTaskProgress(task, workflowType = undefined) {
  const raw = safeObject(task)
  const result = safeObject(raw.result)
  const meta = safeObject(raw.meta)
  const type = workflowType || raw.task_type || meta.workflowType || meta.task_type || "task"
  const status = raw.status || "pending"
  let percent = clampPercent(raw.progress)

  if (percent == null && type === "deep_import") {
    percent = inferDeepImportPercent(result)
  }
  if (status === "done") percent = 100

  const hasPercent = percent != null
  const label = WORKFLOW_LABELS[type] || meta.label || "后台任务"
  const message = inferMessage({ status, workflowType: type, result, meta, percent })

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
    errorMessage: raw.error_message || result.error_message || result.error || null,
    warnings: collectWarnings(result, meta),
    resultSummary: buildResultSummary(result, type),
    phaseArtifacts: safeObject(result.phase_artifacts),
    progressEvents: safeArray(result.progress_events),
    acceptanceChecks: safeArray(result.acceptance_checks),
    phaseTimeline: safeArray(result.phase_timeline),
    diagnosticCounts: safeObject(result.diagnostic_counts),
    phaseErrors: safeArray(result.phase_errors),
    createdAt: raw.created_at || meta.createdAt || null,
    startedAt: raw.started_at || null,
    updatedAt: raw.updated_at || raw.heartbeat_at || null,
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
  const migrated = [...items]
  if (storage) {
    const deepImportTaskId = storage.getItem(LEGACY_DEEP_IMPORT_KEY)
    if (deepImportTaskId) {
      migrated.push({
        id: `${projectId || "global"}:deep_import:${deepImportTaskId}`,
        taskId: deepImportTaskId,
        workflowType: "deep_import",
        label: WORKFLOW_LABELS.deep_import,
        projectId,
        view: "writing",
        meta: { migratedFrom: LEGACY_DEEP_IMPORT_KEY },
        createdAt: nowIso(),
        updatedAt: nowIso(),
      })
      storage.removeItem(LEGACY_DEEP_IMPORT_KEY)
    }

    const worldExtractTaskId = storage.getItem(LEGACY_WORLD_EXTRACT_KEY)
    if (worldExtractTaskId) {
      migrated.push({
        id: `${projectId || "global"}:world_entity_extraction:${worldExtractTaskId}`,
        taskId: worldExtractTaskId,
        workflowType: "world_entity_extraction",
        label: WORKFLOW_LABELS.world_entity_extraction,
        projectId,
        view: "world",
        meta: { migratedFrom: LEGACY_WORLD_EXTRACT_KEY },
        createdAt: nowIso(),
        updatedAt: nowIso(),
      })
      storage.removeItem(LEGACY_WORLD_EXTRACT_KEY)
    }
  }

  const deduped = []
  const seen = new Set()
  for (const item of migrated) {
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
  intervalMs = 1500,
  apiClient = globalThis.api,
  onUpdate,
  onDone,
  onFailed,
} = {}) {
  if (!taskId) throw new Error("taskId is required")
  if (!apiClient?.tasks?.get) throw new Error("api.tasks.get is required")

  let stopped = false
  let timer = null

  const stop = () => {
    stopped = true
    if (timer) clearTimeout(timer)
    timer = null
  }

  const tick = async () => {
    if (stopped) return
    try {
      const task = await apiClient.tasks.get(taskId)
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
      const progress = normalizeTaskProgress({
        id: taskId,
        task_id: taskId,
        task_type: workflowType,
        status: "failed",
        error_message: err.message || "任务状态查询失败",
      }, workflowType)
      onUpdate?.(progress, null)
      stop()
      onFailed?.(progress, null)
      return
    }
    timer = setTimeout(tick, intervalMs)
  }

  tick()
  return { stop }
}

export const workflowProgressStorageKey = ACTIVE_WORKFLOWS_KEY
