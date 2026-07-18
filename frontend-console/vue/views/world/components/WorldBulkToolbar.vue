<!--
  WorldBulkToolbar — 批量工具条，DOM 契约对齐 shared/bulkSelection.js
  renderBulkToolbar（.bulk-toolbar[data-scope] > __status + __actions + sr-only）。
-->
<template>
  <div class="bulk-toolbar" :data-scope="scope">
    <div class="bulk-toolbar__status">
      <span v-if="selectAllIds" class="bulk-toolbar__select-all">
        <WorldSelectionInput mode="all" :scope="scope" :ids="selectAllIds" :label="selectAllLabel" />
        <span>{{ selectAllLabel }}</span>
      </span>
      <strong>{{ count }}</strong>
      <span>{{ noun }}已选</span>
      <span v-if="hint" class="bulk-toolbar__hint">{{ hint }}</span>
    </div>
    <div class="bulk-toolbar__actions">
      <button
        v-for="action in actions"
        :key="action.action"
        class="btn btn-sm"
        :class="action.className || ''"
        data-action="bulk-run"
        :data-scope="scope"
        :data-bulk-action="action.action"
        :data-bulk-static-disabled="action.disabled ? 'true' : 'false'"
        :disabled="count === 0 || action.disabled"
        @click="$emit('run', action.action)"
      >{{ action.label }}</button>
      <button class="btn btn-sm" data-action="bulk-clear" :data-scope="scope" :disabled="count === 0" @click="clear">清空</button>
    </div>
    <span class="sr-only">{{ title }}</span>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { clearBulkSelection, getBulkSelection } from "../logic/worldBulkSelection.js"
import WorldSelectionInput from "./WorldSelectionInput.vue"

const props = defineProps({
  scope: { type: String, required: true },
  actions: { type: Array, default: () => [] }, // [{ action, label, className?, disabled? }]
  noun: { type: String, default: "项" },
  hint: { type: String, default: "" },
  selectAllIds: { type: Array, default: null },
  selectAllLabel: { type: String, default: "" },
})

defineEmits(["run"])

const count = computed(() => getBulkSelection(props.scope).size)
const title = computed(() => `已选择 ${count.value} ${props.noun}`)
const selectAllLabel = computed(() => props.selectAllLabel || `全选当前可见${props.noun}`)

function clear() {
  clearBulkSelection(props.scope)
}
</script>
