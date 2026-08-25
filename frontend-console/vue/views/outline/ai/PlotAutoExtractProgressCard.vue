<script setup>
/**
 * PlotAutoExtractProgressCard — 剧情线/篇章自动提取进度卡片。
 * 监听 plotAutoExtractManager.state 自渲染；无任务时渲染空字符。
 * DOM 对齐 vanilla _renderPlotAutoExtractProgress (L770-779)。
 */
import { computed } from "vue"
import { plotAutoExtractManager } from "./outlineWorkflowManagers.js"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"

const state = plotAutoExtractManager.state

const rangeText = computed(() => {
  const meta = state.meta
  return meta
    ? `范围：第 ${meta.start_chapter || 1}–${meta.end_chapter || 10} 章`
    : "范围：所选章节"
})

const titleText = computed(() => {
  return state.meta?.label || "剧情线自动提取"
})

const hasContent = computed(() => !!state.progress)
</script>

<template>
  <div v-if="hasContent" class="outline-progress-card-wrap">
    <WorkflowProgressCard
      :progress="state.progress"
      :title="titleText"
      :message="''"
      :collapsible="true"
      :className="'outline-progress-mini'"
      :showTaskId="false"
    >
      <p class="workflow-progress__destination">{{ rangeText }}</p>
    </WorkflowProgressCard>
  </div>
</template>
