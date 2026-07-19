<!--
  OutlineBulkToolbar — 批量工具条，DOM 契约对齐 shared/bulkSelection.js
  renderBulkToolbar（.bulk-toolbar[data-scope] > __status(strong + noun已选)
  + __actions(bulk-run/bulk-clear) + sr-only title），实现同 WorldBulkToolbar，
  状态落 outlineBulkSelection。outline 的 vanilla 调用不使用 selectAll/hint。
-->
<template>
  <div class="bulk-toolbar" :data-scope="scope">
    <div class="bulk-toolbar__status">
      <strong>{{ count }}</strong>
      <span>{{ noun }}已选</span>
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
import { clearBulkSelection, getBulkSelection } from "../logic/outlineBulkSelection.js"

const props = defineProps({
  scope: { type: String, required: true },
  actions: { type: Array, default: () => [] }, // [{ action, label, className?, disabled? }]
  noun: { type: String, default: "项" },
})

defineEmits(["run"])

const count = computed(() => getBulkSelection(props.scope).size)
const title = computed(() => `已选择 ${count.value} ${props.noun}`)

function clear() {
  clearBulkSelection(props.scope)
}
</script>
