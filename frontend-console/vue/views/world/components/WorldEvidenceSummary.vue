<!--
  WorldEvidenceSummary — 复核证据摘要块（vanilla _reviewEvidenceSummaryHtml
  的 Vue 化，worldView.js:2232-2258）。复制按钮走组件内 handler（等价 vanilla
  的 copy-review-diagnostic 委托），data-action/data-diagnostic 契约保留。
-->
<template>
  <div class="review-evidence-summary">
    <span>{{ evidence.summary }}</span>
    <p v-if="missingAliasEvidence" class="review-warning">名称归属依据待核对：目前缺少可定位的支持原文，模型置信度不能代替证据。</p>
    <template v-if="showActions && kind === 'alias'">
      <button v-if="sourceRef" type="button" class="btn btn-sm" :disabled="reading" @click="readSource">{{ reading ? '正在读取…' : `打开第 ${sourceRef.chapter_index} 章依据` }}</button>
      <button type="button" class="btn btn-sm" @click="findSource">查找名称原文</button>
      <p v-if="sourceError" role="alert">{{ sourceError }}</p>
      <section v-if="sourcePreview" aria-label="名称归属原文"><strong>{{ sourcePreview.title }}</strong><blockquote>{{ sourcePreview.text }}</blockquote><button type="button" class="btn btn-sm" @click="clearSource">关闭原文</button></section>
    </template>
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
import { getApi, getAppState, getRouter } from "../../../bridge/index.js"
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { copyReviewDiagnostic, reviewEvidenceSummary } from "../logic/useWorldReview.js"

const props = defineProps({
  showActions: { type: Boolean, default: false },
  item: { type: Object, default: () => ({}) },
  kind: { type: String, default: "alias" },
  numericValue: { type: Number, default: null },
})

const sourceRef = computed(() => props.item.source_ref || (props.item.evidence_refs || []).map(item => item.source_ref || item).find(item => item?.draft_id && item?.range_hash) || null)
const sourcePreview = ref(null), sourceError = ref(''), reading = ref(false)
let sourceEpoch = 0
function clearSource() { sourceEpoch += 1; sourcePreview.value = null; sourceError.value = ''; reading.value = false }
watch(() => props.item, clearSource)
onBeforeUnmount(clearSource)
async function readSource() {
  const reference = sourceRef.value, projectId = getAppState()?.currentProjectId, token = ++sourceEpoch
  if (!reference || !projectId) return
  reading.value = true; sourceError.value = ''; sourcePreview.value = null
  try {
    const result = await getApi().context.readEvidence({ novel_id: projectId, content_mode: reference.content_mode || 'canonical', visibility: { mode: 'author' }, source_ref: reference, before: 0, after: 0 })
    if (token !== sourceEpoch || projectId !== getAppState()?.currentProjectId) return
    sourcePreview.value = result
  } catch (error) { if (token === sourceEpoch && projectId === getAppState()?.currentProjectId) sourceError.value = [400,404,409,422].includes(error.status) ? '引用版本已变化或定位不完整，请重新查找名称原文。' : '原文暂时无法读取，请重试。' }
  finally { if (token === sourceEpoch) reading.value = false }
}
const missingAliasEvidence = computed(() => props.kind === "alias" && (!sourceRef.value || !String(props.item.quote || "").includes(props.item.alias || "")))
function findSource() { getRouter().navigate('rag', null, true, new URLSearchParams({ q: props.item.alias || props.item.name || '', search_kind: 'literal' })) }
const evidence = computed(() => reviewEvidenceSummary(props.item, props.kind, missingAliasEvidence.value ? null : props.numericValue))

function copy() {
  void copyReviewDiagnostic(evidence.value.diagnostic)
}
</script>
