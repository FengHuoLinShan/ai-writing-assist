<!--
  WorldInlineEvidence — 证据键值对列表（vanilla _inlineEvidenceHtml 的 Vue 化；
  空时渲染 "-"）。
-->
<template>
  <div v-if="pairs.length">
    <div v-for="[label, value] in pairs" :key="label"><strong>{{ label }}：</strong>{{ value }}</div>
  </div>
  <template v-else>-</template>
</template>

<script setup>
defineProps({
  pairs: { type: Array, default: () => [] },
})
</script>
