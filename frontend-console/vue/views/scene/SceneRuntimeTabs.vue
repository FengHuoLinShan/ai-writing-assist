<template>
  <nav class="scene-runtime-tabs" aria-label="场景工作台分区" role="tablist">
    <button
      v-for="item in tabs"
      :key="item.id"
      type="button"
      class="scene-runtime-tab"
      :class="{ active: activeTab === item.id }"
      :data-action="`scene-runtime-tab-${item.id}`"
      :aria-selected="activeTab === item.id"
      :aria-controls="`scene-runtime-panel-${item.id}`"
      role="tab"
      @click="$emit('select', item.id)"
    >
      <span>{{ item.label }}</span>
      <small>{{ item.description }}</small>
    </button>
  </nav>
</template>

<script setup>
import { SCENE_RUNTIME_TABS } from "./sceneRuntimeSession.js"

defineProps({
  activeTab: { type: String, default: "management" },
})

defineEmits(["select"])

const tabs = SCENE_RUNTIME_TABS
</script>
