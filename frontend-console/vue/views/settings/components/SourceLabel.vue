<script setup>
import { computed } from "vue"
import { formatSourceValue, sourceLabelClass, sourceLabelText } from "../logic/sourceLabel.js"

const props = defineProps({
  source: { type: String, default: "" },
  value: { type: [String, Number, Boolean, Object, Array], default: null },
})

const label = computed(() => sourceLabelText(props.source))
const cls = computed(() => sourceLabelClass(props.source))
const valStr = computed(() => formatSourceValue(props.value))
</script>

<!-- 两节点 fragment：与 vanilla renderSourceLabel 的输出一致（span 与 small 之间无空白文本节点） -->
<template>
  <span :class="cls">{{ label }}</span><small class="source-value">{{ valStr }}</small>
</template>
