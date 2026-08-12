<script setup>
/**
 * OutlineAnalysisResultCard — AI 大纲分析结果卡片。
 * 监听 outlineAnalysisManager.state；无结果时渲染空字符。
 * DOM 对齐 vanilla _renderOutlineAnalysisResult (L736-768) +
 * _outlineAnalysisContextSummary (L717-734)。
 *
 * 含"收起结果"按钮（data-action=dismiss-outline-analysis），
 * 由 shell 的 _bindEvents 或调用方注册事件处理。
 */
import { computed } from "vue"
import { outlineAnalysisManager, resetOutlineAnalysisState } from "./outlineWorkflowManagers.js"

const state = outlineAnalysisManager.state

const result = computed(() => state.result)
const summary = computed(() => result.value?.contextSummary || {})

const sectionItems = computed(() => {
  const sections = summary.value.sections || []
  return sections.map((section) => ({
    title: section.title || "",
    sourceText: section.sources?.length
      ? `：${section.sources.join("、")}${section.sourceCount > section.sources.length ? ` 等 ${section.sourceCount} 项` : ""}`
      : "",
  }))
})

const warningItems = computed(() => summary.value.warnings || [])

const hasContextDetails = computed(() => !!sectionItems.value.length || !!warningItems.value.length)

function dismissResult() {
  resetOutlineAnalysisState({ clearWorkflowState: true })
}
</script>

<template>
  <section
    v-if="result?.markdown"
    class="outline-analysis-result"
    aria-labelledby="outline-analysis-result-title"
  >
    <div class="section-header">
      <div>
        <h3 id="outline-analysis-result-title">AI 大纲分析</h3>
        <p class="form-hint">只读分析，不会写入或修改任何大纲资产。</p>
      </div>
      <button
        class="btn btn-sm btn-ghost"
        data-action="dismiss-outline-analysis"
        @click="dismissResult"
      >收起结果</button>
    </div>
    <details v-if="hasContextDetails" class="outline-analysis-context">
      <summary>本次已确认参考资料</summary>
      <ul v-if="sectionItems.length">
        <li v-for="(item, index) in sectionItems" :key="index"><strong>{{ item.title }}</strong>{{ item.sourceText }}</li>
      </ul>
      <template v-if="warningItems.length">
        <div class="form-hint">编译提示</div>
        <ul>
          <li v-for="(warning, index) in warningItems" :key="index">{{ warning }}</li>
        </ul>
      </template>
    </details>
    <pre class="generate-markdown-pre outline-analysis-markdown">{{ result.markdown }}</pre>
  </section>
</template>
