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
let syncGeneration = 0

function refsFor(ids) {
  const kind = props.sources[0]?.kind || "reference"
  return (ids || []).map((id) => ({ kind, id }))
}

async function mountPicker() {
  ++syncGeneration
  syncing = false
  picker?.destroy?.()
  const mountedPicker = createReferencePicker({
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
  picker = mountedPicker
  await syncPickerItems(props.modelValue, mountedPicker)
}

async function syncPickerItems(ids, target = picker) {
  if (!target) return
  const generation = ++syncGeneration
  syncing = true
  try {
    target.setItems?.([], { notifyChange: false })
    if (ids?.length) await target.resolve(refsFor(ids))
  } finally {
    if (generation === syncGeneration && target === picker) syncing = false
  }
}

onMounted(() => { void mountPicker() })

watch(() => props.projectId, () => { void mountPicker() })

watch(() => props.modelValue, async (next, previous) => {
  if (!picker || JSON.stringify(next) === JSON.stringify(previous)) return
  await syncPickerItems(next)
}, { deep: true })

onBeforeUnmount(() => {
  syncGeneration += 1
  picker?.destroy?.()
  picker = null
})
</script>
