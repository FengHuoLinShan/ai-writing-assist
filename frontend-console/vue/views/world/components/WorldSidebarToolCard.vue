<script setup>
const sidebarTarget = typeof document !== "undefined" && document.getElementById("sidebar-context-slot") ? "#sidebar-context-slot" : ""
defineProps({
  title: { type: String, default: "动态工具区" },
  actions: { type: Array, default: () => [] },
  showSmartDedup: { type: Boolean, default: false },
})
const emit = defineEmits(["select"])
</script>

<template>
  <Teleport v-if="sidebarTarget" :to="sidebarTarget">
    <section class="world-sidebar-tools" :aria-label="title">
      <strong>{{ title }}</strong>
      <button
        v-for="action in actions"
        :key="action.key"
        type="button"
        class="world-sidebar-tools__action"
        :class="{ 'is-primary': action.primary }"
        :disabled="action.disabled"
        :data-action="action.dataAction || `world-tool-${action.key}`"
        @click="emit('select', action.key)"
      >
        <span>{{ action.label }}</span><span v-if="action.badge" class="today-count">{{ action.badge }}</span>
      </button>
      <span v-if="showSmartDedup" data-role="smart-dedup-action"></span>
    </section>
  </Teleport>
  <details class="world-sidebar-tools-mobile">
    <summary class="btn btn-sm">资料工具</summary>
    <div class="world-sidebar-tools-mobile__panel">
      <button
        v-for="action in actions"
        :key="`mobile-${action.key}`"
        type="button"
        class="btn"
        :class="{ 'btn-primary': action.primary }"
        :disabled="action.disabled"
        :data-action="action.dataAction || `world-tool-${action.key}`"
        @click="emit('select', action.key)"
      >{{ action.label }}<span v-if="action.badge" class="today-count">{{ action.badge }}</span></button>
      <span v-if="showSmartDedup" data-role="smart-dedup-action"></span>
    </div>
  </details>
</template>

<style scoped>
.world-sidebar-tools { display: grid; gap: 7px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-base); }
.world-sidebar-tools > strong { padding: 2px 4px 5px; color: var(--text-secondary); font-size: var(--text-xs); }
.world-sidebar-tools__action { display: flex; min-height: 40px; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 7px 10px; background: var(--bg-panel); color: var(--text-primary); text-align: left; cursor: pointer; }
.world-sidebar-tools__action:hover { border-color: var(--accent); background: var(--bg-hover); }
.world-sidebar-tools__action:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-sidebar-tools__action.is-primary { border-color: var(--accent); background: var(--accent); color: #fff; }
.world-sidebar-tools :deep([data-role="smart-dedup-action"] .btn) { width: 100%; min-height: 40px; }
.world-sidebar-tools-mobile { display: none; margin-bottom: 14px; }
.world-sidebar-tools-mobile > summary { min-height: 44px; list-style: none; }
.world-sidebar-tools-mobile > summary::-webkit-details-marker { display: none; }
.world-sidebar-tools-mobile__panel { display: grid; gap: 8px; margin-top: 8px; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-panel); }
.world-sidebar-tools-mobile__panel .btn { min-height: 44px; justify-content: space-between; }
@media (max-width: 760px) {
  .world-sidebar-tools-mobile { display: block; }
}
</style>
