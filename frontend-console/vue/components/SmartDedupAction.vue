<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import {
  getSmartDedupActionState,
  onSmartDedupChanged,
  runSmartDedupAction,
} from "../bridge/index.js"

const root = ref(null)
const actionState = ref(getSmartDedupActionState())
const menuItem = ref(false)
let unsubscribe = null
const progress = computed(() => actionState.value.progress)
const running = computed(() => Boolean(progress.value && !progress.value.terminal))
const done = computed(() => Boolean(progress.value?.done))
const label = computed(() => running.value ? "查看智能去重" : done.value ? "查看去重建议" : "智能去重")
const action = computed(() => running.value || done.value ? "show-smart-dedup-progress" : "start-smart-dedup")

function refresh() {
  actionState.value = getSmartDedupActionState()
}

function run(event) {
  if (root.value?.closest(".workspace-drawer")) event.stopPropagation()
  runSmartDedupAction(action.value)
}

onMounted(() => {
  menuItem.value = Boolean(root.value?.closest('[role="menu"]'))
  unsubscribe = onSmartDedupChanged(refresh)
  refresh()
})
onBeforeUnmount(() => unsubscribe?.())
</script>

<template>
  <span ref="root" data-role="smart-dedup-action">
    <button
      v-if="actionState.available"
      type="button"
      class="btn btn-sm"
      :class="{ 'btn-primary': running }"
      :data-action="action"
      :role="menuItem ? 'menuitem' : undefined"
      :tabindex="menuItem ? -1 : undefined"
      @click="run"
    >{{ label }}</button>
  </span>
</template>
