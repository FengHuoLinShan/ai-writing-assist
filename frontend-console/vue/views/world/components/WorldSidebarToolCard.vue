<script setup>
import WorkspaceToolCard from "../../../components/WorkspaceToolCard.vue"
import SmartDedupAction from "../../../components/SmartDedupAction.vue"
defineProps({
  title: { type: String, default: "资料工具" },
  actions: { type: Array, default: () => [] },
  showSmartDedup: { type: Boolean, default: false },
})
defineEmits(["select"])
</script>
<template>
  <WorkspaceToolCard class="world-sidebar-tools" :title="title" :actions="actions" action-prefix="world-tool" @select="$emit('select', $event)">
    <SmartDedupAction v-if="showSmartDedup" />
  </WorkspaceToolCard>
</template>
