<script setup>
import { computed, ref } from "vue"
import WorkflowProgressBody from "./WorkflowProgressBody.vue"
import {
  classesFor,
  collapseStorageKey,
  initialCardOpen,
  metaBits,
  persistStoredOpen,
} from "./progressUtils.js"

/**
 * 工作流进度卡 — shared/progressRenderer.js 的 Vue 组件化（ADR-0009 §4 禁 v-html）。
 * 覆盖 renderInlineProgress / renderWorkflowCard 两形态（variant="inline"|"card"），
 * DOM class/结构/折叠持久化（sessionStorage）契约与 vanilla 一致。
 * 操作区（重试按钮、去向提示）经默认 slot 注入，事件由调用方绑定。
 */
const props = defineProps({
  progress: { type: Object, required: true },
  variant: { type: String, default: "inline" },
  title: { type: String, default: "" },
  message: { type: String, default: "" },
  collapsible: { type: Boolean, default: true },
  className: { type: String, default: "" },
  detailLevel: { type: String, default: "" },
  showTaskId: { type: Boolean, default: true },
  elapsedText: { type: String, default: "" },
  defaultExpanded: { type: Boolean, default: undefined },
  attentionRequired: { type: Boolean, default: false },
  collapseStorageKeyOverride: { type: String, default: "" },
  detailsStorageKeyOverride: { type: String, default: "" },
})

const titleText = computed(() => props.title || props.progress.label || "")
const messageText = computed(() => props.message || props.progress.message || "")
const percent = computed(() => props.progress.percent ?? 0)

const rootClasses = computed(() => {
  const variantClass = props.variant === "card" ? "workflow-progress--card" : ""
  return classesFor(props.progress, `${variantClass} ${props.className}`.trim())
})

const cardKey = computed(() => collapseStorageKey(props.progress, {
  collapseStorageKey: props.collapseStorageKeyOverride || undefined,
}))

// 初始开合按 sessionStorage + fallback 计算一次；之后跟随用户操作（与 vanilla 渲染期计算语义一致）
const cardOpen = ref(initialCardOpen(props.progress, {
  defaultExpanded: props.defaultExpanded,
  attentionRequired: props.attentionRequired,
  collapseStorageKey: props.collapseStorageKeyOverride || undefined,
}))

function onCardToggle(event) {
  cardOpen.value = event.target.open
  persistStoredOpen(cardKey.value, cardOpen.value)
}

const meta = computed(() => metaBits(props.progress, {
  showTaskId: props.showTaskId,
  elapsedText: props.elapsedText,
}))
</script>

<template>
  <details
    v-if="collapsible"
    :class="rootClasses"
    :data-collapse-storage-key="cardKey || undefined"
    :open="cardOpen"
    @toggle="onCardToggle"
  >
    <summary class="workflow-progress__compact" :aria-label="`${cardOpen ? '收起' : '展开'}${titleText}进度`">
      <span class="workflow-progress__header">
        <span class="workflow-progress__title">{{ titleText }}</span>
        <span class="workflow-progress__status">{{ progress.statusLabel || "" }}</span>
      </span>
      <div v-if="progress.indeterminate" class="workflow-progress__bar" aria-hidden="true">
        <div class="workflow-progress__fill workflow-progress__fill--indeterminate"></div>
      </div>
      <div v-else class="workflow-progress__bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percent">
        <div class="workflow-progress__fill" :style="{ width: `${percent}%` }"></div>
      </div>
      <span v-if="meta.length" class="workflow-progress__meta">{{ meta.join(" · ") }}</span>
      <span class="workflow-progress__chevron" aria-hidden="true"></span>
    </summary>
    <WorkflowProgressBody
      :progress="progress"
      :message="messageText"
      :detail-level="detailLevel"
      :details-storage-key-override="detailsStorageKeyOverride"
    >
      <slot></slot>
    </WorkflowProgressBody>
  </details>

  <div v-else :class="[rootClasses, 'workflow-progress--expanded']">
    <div class="workflow-progress__compact">
      <span class="workflow-progress__header">
        <span class="workflow-progress__title">{{ titleText }}</span>
        <span class="workflow-progress__status">{{ progress.statusLabel || "" }}</span>
      </span>
      <div v-if="progress.indeterminate" class="workflow-progress__bar" aria-hidden="true">
        <div class="workflow-progress__fill workflow-progress__fill--indeterminate"></div>
      </div>
      <div v-else class="workflow-progress__bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percent">
        <div class="workflow-progress__fill" :style="{ width: `${percent}%` }"></div>
      </div>
      <span v-if="meta.length" class="workflow-progress__meta">{{ meta.join(" · ") }}</span>
    </div>
    <WorkflowProgressBody
      :progress="progress"
      :message="messageText"
      :detail-level="detailLevel"
      :details-storage-key-override="detailsStorageKeyOverride"
    >
      <slot></slot>
    </WorkflowProgressBody>
  </div>
</template>
