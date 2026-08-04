<template>
  <div v-if="open" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <div ref="dialogRef" class="modal-content modal-content--wide" role="dialog" aria-modal="true" aria-label="深度导入快照状态" aria-labelledby="deep-import-audit-dialog-label" tabindex="-1">
      <span id="deep-import-audit-dialog-label" class="sr-only">深度导入快照状态</span>
      <div class="modal-header">
        <h3 id="deep-import-audit-dialog-heading">深度导入快照与质量审计</h3>
        <button type="button" class="btn-icon" aria-label="关闭" @click="requestClose">×</button>
      </div>
      <div class="modal-body writing-audit-details">
        <p v-if="!progress" class="muted">暂无审计信息</p>
        <template v-else>
          <section v-for="section in sections" :key="section.key" class="writing-audit-section">
            <h4>{{ section.label }}</h4>
            <p v-if="!section.entries.length" class="muted">暂无</p>
            <dl v-else class="writing-audit-grid">
              <template v-for="entry in section.entries" :key="entry[0]">
                <dt>{{ entry[0] }}</dt><dd>{{ entry[1] }}</dd>
              </template>
            </dl>
          </section>
          <section class="writing-audit-section">
            <h4>验收检查</h4>
            <p v-if="!progress.acceptanceChecks?.length" class="muted">暂无</p>
            <ol v-else>
              <li v-for="(check, index) in progress.acceptanceChecks" :key="check.id || check.name || index">{{ formatValue(check) }}</li>
            </ol>
          </section>
          <section class="writing-audit-section">
            <h4>限流与阶段错误</h4>
            <ul v-if="combinedWarnings.length">
              <li v-for="(warning, index) in combinedWarnings" :key="index">{{ formatValue(warning) }}</li>
            </ul>
            <p v-else class="muted">暂无</p>
          </section>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { formatAuthorFacingDiagnostic } from "../../../components/progressUtils.js"
import { useModalDialog } from "../../../composables/useModalDialog.js"

const props = defineProps({ open: Boolean, progress: { type: Object, default: null } })
const emit = defineEmits(["close"])
const requestClose = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.open, requestClose })

function formatValue(value) {
  return formatAuthorFacingDiagnostic(value)
}
const entries = (value) => Object.entries(value || {}).map(([key, item]) => [key, formatValue(item)])
const sections = computed(() => [
  { key: "assets", label: "资产摘要", entries: entries(props.progress?.assetSummary) },
  { key: "quality", label: "质量统计", entries: entries(props.progress?.qualityStats) },
  { key: "rerun", label: "质量重跑", entries: entries(props.progress?.qualityRerun) },
  { key: "artifacts", label: "阶段产物", entries: entries(props.progress?.phaseArtifacts) },
  { key: "diagnostics", label: "诊断计数", entries: entries(props.progress?.diagnosticCounts) },
  { key: "snapshot", label: "快照健康", entries: entries(props.progress?.auditSummary) },
  { key: "recovery", label: "恢复摘要", entries: entries(props.progress?.recoverySummary) },
  { key: "lifecycle", label: "任务生命周期", entries: entries(props.progress?.lifecycle) },
])
const combinedWarnings = computed(() => [
  ...(props.progress?.throttleReasons || []),
  ...(props.progress?.phaseErrors || []),
  ...(props.progress?.degradedBatches || []).map((batch) => ({ degraded_batch: batch })),
])
</script>
