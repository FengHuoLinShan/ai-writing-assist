<!--
  WorldSelectionInput — 批量选择复选框，DOM 契约对齐 shared/bulkSelection.js
  renderSelectionCell / renderSelectionHeader（label.selection-checkbox >
  input[data-action][data-scope]([data-id]) + span.sr-only）。
-->
<template>
  <label class="selection-checkbox" :title="label">
    <input
      type="checkbox"
      :data-action="mode === 'all' ? 'bulk-toggle-all' : 'bulk-toggle-one'"
      :data-scope="scope"
      :data-id="mode === 'one' ? id : undefined"
      :checked="checked"
      :disabled="disabled"
      :indeterminate.prop="indeterminate"
      :data-indeterminate="indeterminate ? 'true' : undefined"
      @click.stop
      @change="onChange"
    />
    <span class="sr-only">{{ label }}</span>
  </label>
</template>

<script setup>
import { computed } from "vue"
import {
  getBulkSelection,
  selectAllState,
  toggleAllBulkSelection,
  toggleBulkSelection,
} from "../logic/worldBulkSelection.js"

const props = defineProps({
  mode: { type: String, default: "one" }, // "one" | "all"
  scope: { type: String, required: true },
  id: { type: String, default: "" }, // mode=one
  ids: { type: Array, default: () => [] }, // mode=all
  label: { type: String, default: "选择" },
})

const checked = computed(() => {
  if (props.mode === "all") return selectAllState(props.scope, props.ids).checked
  return getBulkSelection(props.scope).has(String(props.id))
})

const indeterminate = computed(() => (
  props.mode === "all" ? selectAllState(props.scope, props.ids).indeterminate : false
))

const disabled = computed(() => (
  props.mode === "all" ? selectAllState(props.scope, props.ids).disabled : false
))

function onChange(event) {
  if (props.mode === "all") {
    toggleAllBulkSelection(props.scope, props.ids, event.target.checked)
  } else {
    toggleBulkSelection(props.scope, props.id, event.target.checked)
  }
}
</script>
