<script setup>
/**
 * OutlineAnalysisProgressCard — AI 大纲分析任务进度卡片。
 * 监听 outlineAnalysisManager.state；无任务时渲染空字符。
 * 使用共享 WorkflowProgressCard 呈现 analysis 任务状态。
 */
import { computed, ref } from "vue"
import { outlineAnalysisManager, resetOutlineAnalysisState } from "./outlineWorkflowManagers.js"
import { cancelOutlineAnalysisTask } from "./outlineAiOps.js"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"

const state = outlineAnalysisManager.state
const cancelPending = ref(false)

const rangeText = computed(() => {
  const meta = state.meta
  if (!meta) return "范围：所选章节"
  const start = meta.start_chapter || 1
  const end = meta.end_chapter || start
  return `范围：第 ${start}–${end} 章`
})

const canCancel = computed(() => (
  !state.progress?.terminal
  && (state.progress?.availableActions || state.progress?.available_actions || []).includes("cancel")
))

const showDismiss = computed(() => Boolean(state.progress?.terminal && !state.result))

async function cancel() {
  if (cancelPending.value) return
  cancelPending.value = true
  try {
    await cancelOutlineAnalysisTask()
  } finally {
    cancelPending.value = false
  }
}

function dismiss() {
  resetOutlineAnalysisState({ clearWorkflowState: true })
}
</script>

<template>
  <div v-if="state.progress" class="outline-analysis-progress">
    <WorkflowProgressCard
      :progress="state.progress"
      title="AI 大纲分析"
      :message="rangeText"
      :collapsible="true"
      :className="'outline-progress-mini'"
      :showTaskId="false"
    >
      <div v-if="canCancel || showDismiss" class="workflow-progress__actions">
        <button v-if="canCancel" class="btn btn-sm btn-ghost" data-action="cancel-outline-analysis" :disabled="cancelPending" @click="cancel">{{ cancelPending ? "取消中..." : "取消任务" }}</button>
        <button v-if="showDismiss" class="btn btn-sm btn-ghost" data-action="dismiss-outline-analysis" @click="dismiss">关闭任务</button>
      </div>
    </WorkflowProgressCard>
  </div>
</template>
