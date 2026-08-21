<script setup>
import TodayView from "../today/TodayView.vue"

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
})
</script>

<template>
  <div class="writing-home-view" data-writing-home="true">
    <TodayView v-bind="$props" />
  </div>
</template>
