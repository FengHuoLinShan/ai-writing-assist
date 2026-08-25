<script setup>
import { computed } from "vue"
import WorkflowProgressCard from "../../components/WorkflowProgressCard.vue"
import { sceneAutoExtractManager } from "./sceneAutoExtractManager.js"

defineEmits(["cancel", "dismiss"])

const state = sceneAutoExtractManager.state
const rangeText = computed(() => state.meta
  ? `范围：第 ${state.meta.start_chapter || 1}–${state.meta.end_chapter || 10} 章`
  : "范围：所选章节")
const terminal = computed(() => Boolean(
  state.progress?.failed || state.progress?.cancelled || state.progress?.done,
))
</script>

<template>
  <div v-if="state.progress" class="scene-progress-card-wrap" data-role="scene-auto-extract-progress">
    <WorkflowProgressCard
      :progress="state.progress"
      title="从正文整理场景"
      :message="state.progress.message || ''"
      :collapsible="true"
      :show-task-id="false"
    >
      <p class="workflow-progress__destination">{{ rangeText }}</p>
      <div class="workflow-progress__actions">
        <button
          v-if="terminal"
          class="btn btn-sm"
          data-action="dismiss-scene-auto-extract"
          @click="$emit('dismiss')"
        >关闭</button>
        <button
          v-else
          class="btn btn-sm"
          data-action="cancel-scene-auto-extract"
          :disabled="state.cancelPending"
          @click="$emit('cancel')"
        >{{ state.cancelPending ? "取消中..." : "取消任务" }}</button>
      </div>
    </WorkflowProgressCard>
  </div>
</template>
