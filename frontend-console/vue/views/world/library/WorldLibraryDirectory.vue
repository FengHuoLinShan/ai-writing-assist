<script setup>
import { computed } from "vue"

const props = defineProps({
  filters: { type: Object, default: () => ({}) },
  types: { type: Array, default: () => [] },
  workingCount: { type: Number, default: 0 },
})
const emit = defineEmits(["select"])

const selectedKey = computed(() => {
  if (props.filters.state === "working") return "working"
  if (props.filters.type) return `type:${props.filters.type}`
  return "all"
})

function selectKey(key) {
  if (key === "working") emit("select", { state: "working", type: "", kind: "page" })
  else if (key.startsWith("type:")) emit("select", { state: "", type: key.slice(5), kind: "all" })
  else emit("select", { state: "", type: "", kind: "all" })
}
</script>

<template>
  <aside class="world-library-directory" aria-label="资料目录">
    <label class="world-library-directory__mobile">
      <span>资料目录</span>
      <select :value="selectedKey" @change="selectKey($event.target.value)">
        <option value="all">全部资料</option>
        <option value="working">工作稿{{ workingCount ? `（${workingCount}）` : '' }}</option>
        <option v-for="type in types" :key="type.value" :value="`type:${type.value}`">{{ type.label }}</option>
      </select>
    </label>
    <nav class="world-library-directory__desktop" aria-label="资料分组">
      <strong>资料目录</strong>
      <button type="button" :aria-current="selectedKey === 'all' ? 'page' : undefined" @click="selectKey('all')">全部资料</button>
      <button type="button" :aria-current="selectedKey === 'working' ? 'page' : undefined" @click="selectKey('working')">
        <span>工作稿</span><span v-if="workingCount">{{ workingCount }}</span>
      </button>
      <span v-if="types.length" class="world-library-directory__label">按类型</span>
      <button v-for="type in types" :key="type.value" type="button" :aria-current="selectedKey === `type:${type.value}` ? 'page' : undefined" @click="selectKey(`type:${type.value}`)">
        {{ type.label }}
      </button>
    </nav>
  </aside>
</template>

<style scoped>
.world-library-directory { min-width: 0; }
.world-library-directory__mobile { display: none; }
.world-library-directory__desktop { position: sticky; top: 12px; display: grid; gap: 4px; }
.world-library-directory__desktop strong { padding: 8px 10px; }
.world-library-directory__desktop button { display: flex; min-height: 38px; width: 100%; align-items: center; justify-content: space-between; border: 0; border-radius: var(--radius-sm); padding: 8px 10px; color: var(--text-secondary); background: transparent; text-align: left; cursor: pointer; }
.world-library-directory__desktop button:hover, .world-library-directory__desktop button[aria-current="page"] { color: var(--text-primary); background: var(--bg-hover); }
.world-library-directory__desktop button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-library-directory__label { padding: 14px 10px 4px; color: var(--text-muted); font-size: 12px; }
@media (max-width: 760px) {
  .world-library-directory__desktop { display: none; }
  .world-library-directory__mobile { display: grid; gap: 6px; }
  .world-library-directory__mobile select { min-height: 44px; width: 100%; }
}
</style>
