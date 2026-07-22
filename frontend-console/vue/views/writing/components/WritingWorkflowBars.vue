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
      <div v-if="recoveryAttention" class="deep-import-recovery" role="status">
        <strong>自动提取需要恢复</strong>
        <span v-if="needsRecovery">可以继续原任务，或放弃恢复并由后端清理本次资产。</span>
        <span v-else>后端正在确认可用的恢复操作，请稍后刷新任务状态。</span>
      </div>
      <div class="workflow-progress__actions deep-import-recovery__actions">
        <button v-if="needsRecovery" class="btn btn-sm btn-primary" @click="$emit('resume')">继续</button>
        <button v-if="needsRecovery" class="btn btn-sm" @click="$emit('abandon')">放弃恢复</button>
        <button v-if="canCancel" class="btn btn-sm" @click="$emit('cancel')">取消任务</button>
        <button
          v-if="deepImport.progress.mapNextStep"
          class="btn btn-sm btn-primary"
          data-action="deep-import-map-next"
          @click="$emit('map-next')"
        >{{ mapNextLabel }}</button>
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
    v-if="showConflict && (conflict.latest || conflict.error)"
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
import {
  authorFacingDiagnosticText,
  authorFacingDiagnosticValue,
  formatAuthorFacingDiagnostic,
  phaseDisplayLabel,
} from "../../../components/progressUtils.js"

const props = defineProps({
  publish: { type: Object, required: true },
  conflict: { type: Object, required: true },
  deepImport: { type: Object, required: true },
  showConflict: { type: Boolean, default: true },
})
defineEmits(["cancel", "resume", "abandon", "dismiss", "map-next", "retry-map", "open-audit", "open-conflict", "retry-publish", "dismiss-publish"])

const terminal = computed(() => ["done", "failed", "cancelled"].includes(props.deepImport.progress?.status || props.deepImport.progress?.phase))
const needsRecovery = computed(() => {
  const actions = props.deepImport.progress?.availableActions || []
  return actions.includes("resume") && actions.includes("abandon")
})
const canCancel = computed(() => (
  !terminal.value
  && !needsRecovery.value
  && (props.deepImport.progress?.availableActions || []).includes("cancel")
))
const recoveryAttention = computed(() => Boolean(
  props.deepImport.progress?.recoveryRequired || needsRecovery.value,
))
const mapNextLabel = computed(() => {
  const next = props.deepImport.progress?.mapNextStep
  if (next?.action === "quick-create") return `一键创建地图（${next.count || 0} 个地点）`
  if (next?.action === "review-locations") return `先审核 ${next.count || 0} 个地点`
  return next?.count ? `查看地图收件箱（${next.count}）` : "查看地图收件箱"
})
const currentPositions = computed(() => {
  const value = props.deepImport.progress || {}
  return [
    ["阶段", value.currentPhase ? phaseDisplayLabel(value.currentPhase) : null],
    ["步骤", value.step ? phaseDisplayLabel(value.step) : null], ["轮次", value.currentRound],
    ["章节范围", value.currentChapterRange], ["章节", value.currentChapter], ["Scene", value.currentSceneCandidateId],
    ["窗口", value.currentWindow], ["操作", value.currentOperation], ["质量", value.qualityStatus],
  ].filter((entry) => entry[1] != null && entry[1] !== "").map(([label, value]) => [label, typeof value === "object" ? JSON.stringify(value) : String(value)])
})
const qualityEntries = computed(() => Object.entries(props.deepImport.progress?.qualityStats || {}).map(([key, value]) => [key, formatAuthorFacingDiagnostic(value)]))
const auditEntries = computed(() => {
  const progress = props.deepImport.progress || {}
  return [
    ...Object.entries(progress.assetSummary || {}).map(([key, value]) => [`资产·${key}`, String(value)]),
    ...Object.entries(progress.auditSummary || {}).map(([key, value]) => [`快照·${key}`, formatAuthorFacingDiagnostic(value)]),
    ...Object.entries(progress.phaseArtifacts || {}).map(([key, value]) => [`产物·${key}`, formatAuthorFacingDiagnostic(value)]),
    ...Object.entries(progress.diagnosticCounts || {}).map(([key, value]) => [`诊断·${key}`, String(value)]),
    ...(progress.acceptanceChecks || []).map((value, index) => [`验收·${index + 1}`, formatAuthorFacingDiagnostic(value)]),
    ...(progress.throttleReasons || []).map((value, index) => [`限流·${index + 1}`, formatAuthorFacingDiagnostic(value)]),
  ]
})
const hasAudit = computed(() => auditEntries.value.length > 0)

const normalizedDeepImportProgress = computed(() => {
  const value = props.deepImport.progress
  if (!value) return null

  const rawStatus = value.status || value.phase || "running"
  const status = ["done", "failed", "cancelled"].includes(rawStatus) ? rawStatus : "running"
  const workflowType = value.workflowType || "deep_import"
  const rawPhaseErrors = Array.isArray(value.phaseErrors) ? value.phaseErrors : []
  const phaseErrors = authorFacingDiagnosticValue(rawPhaseErrors)
  const phaseErrorText = phaseErrors
    .map((item) => item && (item.message || item.error || "部分步骤需要人工检查"))
    .filter(Boolean)
    .slice(0, 2)
    .join("；")
  const warnings = []
  if (value.qualityStatus === "partial" && !value.degraded) warnings.push("部分完成")
  if (value.degraded) {
    const reason = String(value.degradedReason || "").trim()
    const authorFacingReason = reason && !/^[a-z0-9_.:-]+$/i.test(reason)
      ? reason
      : "部分步骤已降级完成，请检查需要人工处理的结果"
    warnings.push(authorFacingReason)
  }
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
      ? authorFacingDiagnosticText(
        value.error || value.message || phaseErrorText || "自动提取失败",
        { fallbackForCode: true },
      )
      : null,
    available_actions: Array.isArray(value.availableActions) ? value.availableActions : [],
    lifecycle: value.lifecycle || {},
    result: {
      message: needsRecovery.value
        ? "自动提取中断，需要选择继续或放弃恢复"
        : structureRunning
          ? "正在生成剧情结构（耗时较长，请耐心等待）..."
          : authorFacingDiagnosticText(value.message || "自动提取中..."),
      summary: value.degraded
        ? "部分降级完成"
        : value.qualityStatus === "partial"
          ? "部分完成"
          : null,
      warnings,
      asset_summary: value.assetSummary || {},
      phase_artifacts: authorFacingDiagnosticValue(value.phaseArtifacts || {}),
      progress_events: value.progressEvents || [],
      acceptance_checks: value.acceptanceChecks || [],
      phase_timeline: value.phaseTimeline || [],
      diagnostic_counts: value.diagnosticCounts || {},
      phase_errors: rawPhaseErrors,
      current_phase: value.currentPhase || null,
      current_operation: value.currentOperation || null,
      recovery_required: recoveryAttention.value,
    },
  }, workflowType)
})

const attentionRequired = computed(() => Boolean(
  normalizedDeepImportProgress.value?.failed
  || recoveryAttention.value
  || props.deepImport.progress?.degraded
  || props.deepImport.progress?.qualityStatus === "partial"
  || props.deepImport.progress?.phase1aFallback
  || props.deepImport.progress?.phaseErrors?.length
  || props.deepImport.progress?.mapNextStep
  || props.deepImport.progress?.mapNextStepError,
))

const deepImportClassName = computed(() => (
  normalizedDeepImportProgress.value?.terminal ? "" : "deep-import-progress--alive"
))
</script>
