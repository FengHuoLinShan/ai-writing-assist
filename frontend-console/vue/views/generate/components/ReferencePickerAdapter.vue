<template><div ref="root"></div></template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import { createReferencePicker } from "../../../../shared/referencePicker.js"

const props = defineProps({
  projectId: { type: String, required: true },
  sources: { type: Array, required: true },
  modelValue: { type: Array, default: () => [] },
  mode: { type: String, default: "single" },
  maxItems: { type: Number, default: 1 },
  placeholder: { type: String, default: "按名称搜索" },
})
const emit = defineEmits(["update:modelValue"])
const root = ref(null)
let picker = null
let syncing = false

function refsFor(ids) {
  const kind = props.sources[0]?.kind || "reference"
  return (ids || []).map((id) => ({ kind, id }))
}

onMounted(() => {
  picker = createReferencePicker({
    root: root.value,
    projectId: props.projectId,
    sources: props.sources,
    mode: props.mode,
    maxItems: props.maxItems,
    placeholder: props.placeholder,
    onChange(_items, refs) {
      if (syncing) return
      emit("update:modelValue", refs.map((item) => item.id))
    },
  })
  if (props.modelValue.length) picker.resolve(refsFor(props.modelValue))
})

watch(() => props.modelValue, async (next, previous) => {
  if (!picker || JSON.stringify(next) === JSON.stringify(previous)) return
  syncing = true
  try {
    picker.setItems?.([], { notifyChange: false })
    if (next?.length) await picker.resolve(refsFor(next))
  } finally {
    syncing = false
  }
}, { deep: true })

onBeforeUnmount(() => {
  picker?.destroy?.()
  picker = null
})
</script>
