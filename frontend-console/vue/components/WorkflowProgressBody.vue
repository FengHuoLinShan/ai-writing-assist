<script setup>
import { computed, ref, watch } from "vue"
import {
  artifactItems,
  checkItems,
  detailsStorageKey,
  diagnosticItems,
  errorItems,
  eventItems,
  hasAssetSummary,
  initialDetailsOpen,
  persistStoredOpen,
  timelineItems,
  warningItems,
} from "./progressUtils.js"

/** 进度卡正文（message/summary/artifacts/详细进度/error/warnings + 操作槽）。 */
const props = defineProps({
  progress: { type: Object, required: true },
  message: { type: String, default: "" },
  detailLevel: { type: String, default: "" },
  detailsStorageKeyOverride: { type: String, default: "" },
})

const detailsOptions = () => ({
  detailLevel: props.detailLevel,
  detailsStorageKey: props.detailsStorageKeyOverride || undefined,
})

const detailsKey = computed(() => detailsStorageKey(props.progress, detailsOptions()))
const detailsOpen = ref(initialDetailsOpen(props.progress, detailsOptions()))

// 任务切换（新 taskId → 新存储键）时按 vanilla 渲染期语义重算开合
watch(() => props.progress?.taskId, () => {
  detailsOpen.value = initialDetailsOpen(props.progress, detailsOptions())
})

function onDetailsToggle(event) {
  detailsOpen.value = event.target.open
  persistStoredOpen(detailsKey.value, detailsOpen.value)
}

const messageText = computed(() => props.message || props.progress.message || "")
const warnings = computed(() => warningItems(props.progress.warnings))
const artifacts = computed(() => artifactItems(props.progress.phaseArtifacts))
const timeline = computed(() => timelineItems(props.progress.phaseTimeline))
const events = computed(() => eventItems(props.progress.progressEvents))
const checks = computed(() => checkItems(props.progress.acceptanceChecks))
const errors = computed(() => errorItems(props.progress.phaseErrors))
const diagnostics = computed(() => diagnosticItems(props.progress))
const hasDetailed = computed(() => (
  timeline.value.length || events.value.length || checks.value.length
  || errors.value.length || diagnostics.value.length
))
</script>

<template>
  <div class="workflow-progress__body">
    <div v-if="messageText" class="workflow-progress__message">{{ messageText }}</div>
    <div v-if="progress.resultSummary" class="workflow-progress__summary">{{ progress.resultSummary }}</div>
    <div v-if="hasAssetSummary(progress.assetSummary)" class="workflow-progress__asset-summary" aria-label="资产处理结果">
      <span>已采用 {{ Number(progress.assetSummary.adopted || 0) }}</span>
      <span>待处理 {{ Number(progress.assetSummary.review || 0) }}</span>
      <span>未采用 {{ Number(progress.assetSummary.not_adopted || 0) }}</span>
    </div>
    <ul v-if="artifacts.length" class="workflow-progress__artifacts">
      <li v-for="item in artifacts" :key="item.phase">{{ item.label }}：{{ item.status }}{{ item.detail }}</li>
    </ul>
    <details
      v-if="hasDetailed"
      class="workflow-progress__details"
      :data-details-storage-key="detailsKey || undefined"
      :open="detailsOpen"
      @toggle="onDetailsToggle"
    >
      <summary>详细进度</summary>
      <section v-if="timeline.length" class="workflow-progress__detail-section">
        <h4>阶段时间线</h4>
        <ul>
          <li v-for="(item, index) in timeline" :key="index">{{ item.phase }}：{{ item.detail }}</li>
        </ul>
      </section>
      <section v-if="events.length" class="workflow-progress__detail-section">
        <h4>事件</h4>
        <ul>
          <li v-for="(item, index) in events" :key="index" :class="`workflow-progress__event workflow-progress__event--${item.level}`">
            <div>{{ item.label }}</div>
            <div v-if="item.message">{{ item.message }}</div>
            <div v-if="item.details.length" class="workflow-progress__details-kv">
              <span v-for="kv in item.details" :key="kv.key" class="workflow-progress__kv"><b>{{ kv.key }}</b>: {{ kv.text }}</span>
            </div>
          </li>
        </ul>
      </section>
      <section v-if="checks.length" class="workflow-progress__detail-section">
        <h4>门禁检查</h4>
        <ul>
          <li v-for="(item, index) in checks" :key="index" :class="item.ok ? 'workflow-progress__check' : 'workflow-progress__check workflow-progress__check--failed'">
            <div>{{ item.label }}：{{ item.ok ? "通过" : "未通过" }}</div>
            <div v-if="item.message">{{ item.message }}</div>
            <div v-if="item.details.length" class="workflow-progress__details-kv">
              <span v-for="kv in item.details" :key="kv.key" class="workflow-progress__kv"><b>{{ kv.key }}</b>: {{ kv.text }}</span>
            </div>
          </li>
        </ul>
      </section>
      <section v-if="errors.length" class="workflow-progress__detail-section">
        <h4>错误与降级</h4>
        <ul>
          <li v-for="(item, index) in errors" :key="index">{{ item.phase }}：{{ item.kind }} · {{ item.message }}</li>
        </ul>
      </section>
      <section v-if="diagnostics.length" class="workflow-progress__detail-section">
        <h4>诊断摘要</h4>
        <div class="workflow-progress__details-kv">
          <span v-for="kv in diagnostics" :key="kv.key" class="workflow-progress__kv"><b>{{ kv.key }}</b>: {{ kv.text }}</span>
        </div>
      </section>
    </details>
    <div v-if="progress.errorMessage" class="workflow-progress__error">{{ progress.errorMessage }}</div>
    <ul v-if="warnings.length" class="workflow-progress__warnings">
      <li v-for="(warning, index) in warnings" :key="index">{{ warning }}</li>
    </ul>
    <slot></slot>
  </div>
</template>
