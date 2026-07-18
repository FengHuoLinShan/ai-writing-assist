<!--
  WorldFilterPanel — 筛选面板外壳（vanilla _renderFilterPanel 1269-1291 的 Vue 化）。
  开合状态落 worldSession.filterPanelsOpen 并持久化 localStorage。
-->
<template>
  <section class="world-filter-panel" :data-filter-panel="panelKey">
    <button
      type="button"
      class="btn btn-sm world-filter-panel__toggle"
      data-action="toggle-filter-panel"
      :data-filter-key="panelKey"
      :aria-expanded="open ? 'true' : 'false'"
      :aria-controls="`world-filter-panel-${panelKey}`"
      @click="toggle"
    >
      <span aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
      <span data-filter-toggle-label>{{ open ? "收起筛选" : "展开筛选" }}</span>
      <span v-if="hasActiveFilters" class="world-filter-panel__active">已筛选</span>
    </button>
    <div :id="`world-filter-panel-${panelKey}`" class="world-filter-panel__body" :hidden="!open">
      <slot></slot>
    </div>
  </section>
</template>

<script setup>
import { computed } from "vue"
import { worldSession as session, saveFilterPanelState } from "../worldSession.js"

const props = defineProps({
  panelKey: { type: String, required: true },
  hasActiveFilters: { type: Boolean, default: false },
  projectId: { type: String, default: null },
})

const open = computed(() => session.filterPanelsOpen?.[props.panelKey] === true)

function toggle() {
  session.filterPanelsOpen = { ...session.filterPanelsOpen, [props.panelKey]: !open.value }
  saveFilterPanelState(props.projectId)
}
</script>
