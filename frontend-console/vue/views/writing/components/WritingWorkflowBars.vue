<template>
  <div v-if="publish.active || publish.phase" id="writing-publish-bar-container" class="workflow-progress-card writing-publish-progress">
    <div class="workflow-progress-card__title">发布正文</div>
    <div class="workflow-progress-card__message">{{ publish.message }}</div>
    <progress v-if="publish.progress != null" max="100" :value="publish.progress" />
    <div v-if="publish.retryable" class="writing-publish-actions">
      <span class="writing-publish-error">工作稿已保留成功。您可以手动重试失败的步骤。</span>
      <button class="btn btn-sm" @click="$emit('dismiss-publish')">关闭</button>
      <button class="btn btn-sm btn-primary" @click="$emit('retry-publish')">手动重试</button>
    </div>
  </div>
  <section v-if="normalizedDeepImportProgress" id="writing-deep-import-bar-container" aria-live="polite">
    <WorkflowProgressCard
      :progress="normalizedDeepImportProgress"
      variant="card"
      :title="deepImport.progress.label || normalizedDeepImportProgress.label || '自动提取'"
      :class-name="deepImportClassName"
      :attention-required="attentionRequired"
      :show-task-id="false"
    >
      <div v-if="currentPositions.length" class="deep-import-current-position">
        <span
          v-for="entry in currentPositions"
          :key="entry[0]"
          class="deep-import-current-position__item"
          :data-diagnostic-field="entry[0] === 'Scene' ? '' : undefined"
        >{{ entry[0] }}：{{ entry[1] }}</span>
      </div>
      <div v-if="qualityEntries.length" class="deep-import-current-position" aria-label="深度导入质量统计">
        <span v-for="entry in qualityEntries" :key="entry[0]" class="deep-import-current-position__item">{{ entry[0] }}：{{ entry[1] }}</span>
      </div>
      <div v-if="needsRecovery" class="deep-import-recovery" role="status">
        <strong>自动提取需要恢复</strong>
        <span>可以继续原任务，或放弃恢复并由后端清理本次资产。</span>
      </div>
      <div class="workflow-progress__actions deep-import-recovery__actions">
        <button v-if="needsRecovery" class="btn btn-sm btn-primary" @click="$emit('resume')">继续</button>
        <button v-if="needsRecovery" class="btn btn-sm" @click="$emit('abandon')">放弃恢复</button>
        <button v-if="!terminal && !needsRecovery" class="btn btn-sm" @click="$emit('cancel')">取消任务</button>
        <button v-if="deepImport.progress.mapNextStep" class="btn btn-sm btn-primary" @click="$emit('map-next')">{{ mapNextLabel }}</button>
        <template v-if="deepImport.progress.mapNextStepError">
          <span class="writing-empty-hint">地图下一步暂时无法加载：{{ deepImport.progress.mapNextStepError }}</span>
          <button class="btn btn-sm btn-primary" @click="$emit('retry-map')">重试</button>
        </template>
        <button v-if="hasAudit" class="btn btn-sm" @click="$emit('open-audit')">查看快照状态</button>
        <button v-if="terminal" class="btn btn-sm" @click="$emit('dismiss')">关闭</button>
      </div>
    </WorkflowProgressCard>
  </section>
  <div
    v-if="conflict.latest || conflict.error"
    id="writing-conflict-strip"
    class="writing-conflict-strip"
    :role="conflict.latest ? 'button' : 'status'"
    :tabindex="conflict.latest ? 0 : null"
    @click="conflict.latest && $emit('open-conflict')"
    @keydown.enter="conflict.latest && $emit('open-conflict')"
  >
    <strong>{{ conflict.error ? '最近检查加载失败' : '最近冲突检查' }}</strong>
    <span>{{ conflict.error || conflict.latest?.summary_json?.message || conflict.latest?.status || '已完成' }}</span>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { normalizeTaskProgress } from "../../../../shared/workflowProgress.js"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"

const props = defineProps({
  publish: { type: Object, required: true },
  conflict: { type: Object, required: true },
  deepImport: { type: Object, required: true },
})
defineEmits(["cancel", "resume", "abandon", "dismiss", "map-next", "retry-map", "open-audit", "open-conflict", "retry-publish", "dismiss-publish"])

const terminal = computed(() => ["done", "failed", "cancelled"].includes(props.deepImport.progress?.status || props.deepImport.progress?.phase))
const needsRecovery = computed(() => {
  const value = props.deepImport.progress
  const actions = value?.availableActions || []
  return Boolean(value?.recoveryRequired || (actions.includes("resume") && actions.includes("abandon")))
})
const mapNextLabel = computed(() => {
  const next = props.deepImport.progress?.mapNextStep
  if (next?.action === "quick-create") return `一键创建地图（${next.count || 0} 个地点）`
  if (next?.action === "review-locations") return `先审核 ${next.count || 0} 个地点`
  return next?.count ? `查看地图收件箱（${next.count}）` : "查看地图收件箱"
})
const currentPositions = computed(() => {
  const value = props.deepImport.progress || {}
  return [
    ["阶段", value.currentPhase], ["步骤", value.step], ["轮次", value.currentRound],
    ["章节范围", value.currentChapterRange], ["章节", value.currentChapter], ["Scene", value.currentSceneCandidateId],
    ["窗口", value.currentWindow], ["操作", value.currentOperation], ["质量", value.qualityStatus],
  ].filter((entry) => entry[1] != null && entry[1] !== "").map(([label, value]) => [label, typeof value === "object" ? JSON.stringify(value) : String(value)])
})
const qualityEntries = computed(() => Object.entries(props.deepImport.progress?.qualityStats || {}).map(([key, value]) => [key, typeof value === "object" ? JSON.stringify(value) : String(value)]))
const auditEntries = computed(() => {
  const progress = props.deepImport.progress || {}
  return [
    ...Object.entries(progress.assetSummary || {}).map(([key, value]) => [`资产·${key}`, String(value)]),
    ...Object.entries(progress.auditSummary || {}).map(([key, value]) => [`快照·${key}`, typeof value === "object" ? JSON.stringify(value) : String(value)]),
    ...Object.entries(progress.phaseArtifacts || {}).map(([key, value]) => [`产物·${key}`, typeof value === "object" ? JSON.stringify(value) : String(value)]),
    ...Object.entries(progress.diagnosticCounts || {}).map(([key, value]) => [`诊断·${key}`, String(value)]),
    ...(progress.acceptanceChecks || []).map((value, index) => [`验收·${index + 1}`, typeof value === "object" ? JSON.stringify(value) : String(value)]),
    ...(progress.throttleReasons || []).map((value, index) => [`限流·${index + 1}`, typeof value === "object" ? JSON.stringify(value) : String(value)]),
  ]
})
const hasAudit = computed(() => auditEntries.value.length > 0)

const normalizedDeepImportProgress = computed(() => {
  const value = props.deepImport.progress
  if (!value) return null

  const rawStatus = value.status || value.phase || "running"
  const status = ["done", "failed", "cancelled"].includes(rawStatus) ? rawStatus : "running"
  const workflowType = value.workflowType || "deep_import"
  const phaseErrors = Array.isArray(value.phaseErrors) ? value.phaseErrors : []
  const phaseErrorText = phaseErrors
    .map((item) => item && (item.message || item.error_kind || item.phase || item.error))
    .filter(Boolean)
    .slice(0, 2)
    .join("；")
  const warnings = []
  if (value.qualityStatus === "partial" && !value.degraded) warnings.push("部分完成")
  if (value.degraded) warnings.push(value.degradedReason || "部分批次降级完成")
  if (Array.isArray(value.degradedBatches) && value.degradedBatches.length) {
    warnings.push(`降级批次：${value.degradedBatches.join(", ")}`)
  }
  if (value.phase1aFallback) warnings.push("自动整理失败，已使用质量补强结果继续导入")
  if (value.error && status !== "failed") warnings.push(value.error)
  if (phaseErrorText && status !== "failed") warnings.push(`阶段错误：${phaseErrorText}`)

  const structureRunning = status === "running" && value.currentPhase === "structure_analysis"
  const numericPercent = typeof value.percent === "number" && Number.isFinite(value.percent)
    ? value.percent
    : null

  return normalizeTaskProgress({
    task_id: props.deepImport.taskId || value.taskId || null,
    task_type: workflowType,
    status,
    // deepImportController 已把后端 0..1 比例换算成 0..100；共享 normalizer
    // 接收的是后端比例语义，因此在这里换回比例，避免 1% 被误判成 100%。
    progress: structureRunning || numericPercent == null ? null : numericPercent / 100,
    error_message: status === "failed"
      ? (value.error || value.message || phaseErrorText || "自动提取失败")
      : null,
    available_actions: Array.isArray(value.availableActions) ? value.availableActions : [],
    lifecycle: value.lifecycle || {},
    result: {
      message: needsRecovery.value
        ? "自动提取中断，需要选择继续或放弃恢复"
        : structureRunning
          ? "正在生成剧情结构（耗时较长，请耐心等待）..."
          : value.message || "自动提取中...",
      summary: value.qualityStatus === "partial"
        ? "部分完成"
        : value.degraded
          ? "部分降级完成"
          : null,
      warnings,
      asset_summary: value.assetSummary || {},
      phase_artifacts: value.phaseArtifacts || {},
      progress_events: value.progressEvents || [],
      acceptance_checks: value.acceptanceChecks || [],
      phase_timeline: value.phaseTimeline || [],
      diagnostic_counts: value.diagnosticCounts || {},
      phase_errors: phaseErrors,
      current_phase: value.currentPhase || null,
      current_operation: value.currentOperation || null,
      recovery_required: needsRecovery.value,
    },
  }, workflowType)
})

const attentionRequired = computed(() => Boolean(
  normalizedDeepImportProgress.value?.failed
  || needsRecovery.value
  || props.deepImport.progress?.mapNextStep
  || props.deepImport.progress?.mapNextStepError,
))

const deepImportClassName = computed(() => (
  normalizedDeepImportProgress.value?.terminal ? "" : "deep-import-progress--alive"
))
</script>
