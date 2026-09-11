<template>
  <div v-if="pairs.length">
    <div v-for="[label, value] in visiblePairs" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
    <details v-if="quote" :open="expanded" @click.stop>
      <summary>查看原文依据</summary>
      <blockquote class="world-inline-evidence-quote">{{ quote }}</blockquote>
    </details>
    <details v-if="diagnosticPairs.length" @click.stop>
      <summary>诊断信息</summary>
      <div v-for="[label, value] in diagnosticPairs" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
    </details>
  </div>
  <template v-else>-</template>
</template>

<script setup>
import { computed } from "vue"
const props = defineProps({ expanded: { type: Boolean, default: false }, pairs: { type: Array, default: () => [] } })
const isDiagnostic = ([label, value]) => label === "处理批次" || (label === "场景" && !Number.isInteger(Number(value)))
const diagnosticPairs = computed(() => props.pairs.filter(isDiagnostic))
const visiblePairs = computed(() => props.pairs.filter(pair => !isDiagnostic(pair) && pair[0] !== "引用"))
const quote = computed(() => props.pairs.find(([label]) => label === "引用")?.[1] || "")
</script>

<style scoped>
summary { cursor: pointer; min-height: 44px; padding-block: 10px; box-sizing: border-box; }
.world-inline-evidence-quote { white-space: pre-wrap; overflow-wrap: anywhere; margin-inline: 0; }
</style>
