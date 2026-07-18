<!--
  WorldEvidenceSummary — 复核证据摘要块（vanilla _reviewEvidenceSummaryHtml
  的 Vue 化，worldView.js:2232-2258）。复制按钮走组件内 handler（等价 vanilla
  的 copy-review-diagnostic 委托），data-action/data-diagnostic 契约保留。
-->
<template>
  <div class="review-evidence-summary">
    <span>{{ evidence.summary }}</span>
    <blockquote v-if="evidence.quote">{{ evidence.quote }}</blockquote>
    <span v-else class="world-text-dim">无原文引用</span>
    <details>
      <summary>诊断信息</summary>
      <pre>{{ evidence.diagnostic }}</pre>
      <button class="btn btn-sm" data-action="copy-review-diagnostic" :data-diagnostic="evidence.diagnostic" @click.prevent="copy">复制诊断信息</button>
    </details>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { copyReviewDiagnostic, reviewEvidenceSummary } from "../logic/useWorldReview.js"

const props = defineProps({
  item: { type: Object, default: () => ({}) },
  kind: { type: String, default: "alias" },
  numericValue: { type: Number, default: null },
})

const evidence = computed(() => reviewEvidenceSummary(props.item, props.kind, props.numericValue))

function copy() {
  void copyReviewDiagnostic(evidence.value.diagnostic)
}
</script>
