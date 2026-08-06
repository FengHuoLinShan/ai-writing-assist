<script setup>
/**
 * OutlineGenerateProgressCard — 当前层 AI 创作进度卡片。
 * 监听 outlineGenerateManager.state 自渲染；无任务时渲染空字符。
 * DOM 对齐 vanilla _renderOutlineGenerateProgress (L439-453)。
 */
import { computed } from "vue"
import { outlineGenerateManager } from "./outlineWorkflowManagers.js"
import { showOutlineGeneratePreview } from "./outlineAiOps.js"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"

const state = outlineGenerateManager.state

const rangeText = computed(() => {
  const meta = state.meta
  if (!meta) return "当前层创作"
  const modeLabel = meta.mode === "revise" ? "修订所选" : "新增设计"
  const chapterRange = meta.start_chapter
    ? ` · 第 ${meta.start_chapter}-${meta.end_chapter || meta.start_chapter} 章`
    : ""
  return `${modeLabel}${chapterRange}`
})

const titleText = computed(() => {
  return `${state.meta?.label || "当前层"}建议`
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
      <!-- 默认 slot：可追加操作区 -->
    </WorkflowProgressCard>
    <div
      v-if="state.preview"
      class="outline-preview-ready"
      role="status"
    >
      <span>建议尚未写入工作结构。请先检查和编辑，再明确采用。</span>
      <button
        class="btn btn-sm btn-primary"
        data-action="view-outline-generate-preview"
        @click="showOutlineGeneratePreview"
      >查看并采用</button>
    </div>
  </div>
</template>
