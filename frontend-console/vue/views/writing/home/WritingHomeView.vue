<script setup>
import TodayView from "../../today/TodayView.vue"
import AuthorTasksView from "./AuthorTasksView.vue"

defineProps({
  project: { type: Object, default: null },
  summary: { type: Object, default: null },
  workflows: { type: Array, default: () => [] },
  creativeContinuation: { type: Object, default: null },
  worldContinuations: { type: Array, default: () => [] },
  continuationWarning: { type: String, default: null },
  worldLoadError: { type: String, default: null },
  loadError: { type: String, default: null },
  onOpenAi: { type: Function, default: null },
  taskPanel: { type: Boolean, default: false },
  taskScope: { type: String, default: "today" },
  taskSource: { type: Object, default: null },
})
</script>

<template>
  <div class="writing-home-view" data-writing-home="true">
    <AuthorTasksView v-if="taskPanel && summary?.project_id" :project-id="summary.project_id" :scope="taskScope" :source="taskSource" />
    <TodayView v-else v-bind="$props" />
  </div>
</template>
