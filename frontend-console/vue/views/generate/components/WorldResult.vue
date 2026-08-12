<template>
  <div v-if="result && revisionLink?.predecessor_suggestion_id" class="generate-revision-lineage" data-state="revision-lineage">
    <strong>上一版 → 当前版</strong>
    <span>上一版已封存，只能处理当前版。</span>
  </div>
  <details v-if="result && decision" class="generate-author-decisions" data-section="author-decision-summary">
    <summary>AI 本次理解<span v-if="decision.needsReview"> · 请核对</span></summary>
    <dl>
      <template v-for="row in decision.rows" :key="row.label">
        <dt>{{ row.label }}</dt>
        <dd><ul><li v-for="item in row.items" :key="item">{{ item }}</li></ul></dd>
      </template>
    </dl>
    <p>如果理解有偏差，请在对话中明确纠正后修订此版。</p>
  </details>
  <p v-else-if="result" class="generate-empty-copy" data-state="missing-author-decision-summary">本次生成未保存决定摘要。</p>
  <details v-if="result && revisionLink?.predecessor_suggestion_id" class="generate-revision-compare" data-section="revision-comparison" open>
    <summary>关键变化</summary>
    <dl v-if="revisionChanges.length">
      <template v-for="change in revisionChanges" :key="change.label">
        <dt>{{ change.label }}</dt>
        <dd><del>{{ change.before || '未填写' }}</del><span aria-hidden="true"> → </span><ins>{{ change.after || '未填写' }}</ins></dd>
      </template>
    </dl>
    <p v-else>{{ previousResult ? '关键字段没有变化，可继续核对完整提案。' : '上一版仍保留在服务器历史记录中。' }}</p>
  </details>
  <p v-if="!result" class="generate-empty-copy">对话不写业务数据。生成后只会创建待处理建议；世界书提案应用后也只进入工作稿。</p>
  <div v-else-if="result.kind === 'core_entity'" class="generate-result-card">
    <div class="generate-result-title">{{ entityContent.name || entityContent.title || '未命名对象' }}</div>
    <div class="generate-result-meta">{{ entityContent.entity_type || result.suggestion?.target_type || '-' }} · 待处理</div>
    <p class="generate-result-summary">{{ entityContent.summary || entityContent.public_info || '世界对象建议已进入待处理。' }}</p>
    <div class="generate-result-actions">
      <button class="btn btn-sm btn-primary" data-action="open-generated-destination" @click="$emit('open-review')">前往待处理</button>
      <button class="btn btn-sm" data-action="continue-chat" @click="$emit('continue-chat')">继续聊</button>
      <button class="btn btn-sm" data-action="generate-another" @click="$emit('clear')">再生成一个</button>
      <button v-if="contextUsage" class="btn btn-sm" data-action="view-generation-context" @click="$emit('view-context')">查看本次上下文</button>
    </div>
  </div>
  <div
    v-else
    class="generate-result-card generate-page-result"
    :inert="busy || undefined"
    :aria-busy="busy"
  >
    <div class="generate-result-title">{{ page.title || '未命名页面' }}</div>
    <div class="generate-result-meta">{{ page.page_type || 'custom' }} · {{ summary }}</div>
    <p v-if="proposal.design_rationale" class="generate-result-summary">{{ proposal.design_rationale }}</p>
    <div v-if="proposal.review_notes?.length" class="generate-page-review-notes">
      <span v-for="note in proposal.review_notes" :key="note" class="badge">{{ note }}</span>
    </div>
    <div class="generate-page-section-diff">
      <strong>分区变更</strong>
      <template v-if="changes.length">
        <div v-for="(change, index) in changes" :key="`${change.section?.section_id || index}:${change.kind}`" class="generate-page-section-diff__item">
          <span class="badge">{{ change.kind }}</span>
          <span>{{ change.section?.title || change.section?.section_id || '未命名分区' }}</span>
          <span v-if="change.fields.length" class="generate-empty-copy">{{ change.fields.join('、') }}</span>
        </div>
      </template>
      <p v-else class="generate-empty-copy">分区内容无实质变更。</p>
    </div>
    <p v-if="recovered" class="generate-template-warning" data-state="recovered-page-proposal">已恢复上次未应用的提案编辑。</p>
    <label>标题<input id="generate-page-title" v-model="editor.title" class="form-input" @input="markDirty" /></label>
    <label>类别
      <select id="generate-page-type" v-model="editor.pageType" class="form-select" @change="markDirty">
        <option v-for="category in categories" :key="category.category_key" :value="category.category_key">{{ category.name || category.category_key }}</option>
      </select>
    </label>
    <label>页面概览<textarea id="generate-page-free-text" v-model="editor.freeText" class="form-textarea" rows="6" @input="markDirty" /></label>
    <details class="generate-advanced-data-editor" data-section="advanced-page-data">
      <summary>高级数据编辑（可选）</summary>
      <label>完整 sections JSON<textarea id="generate-page-sections" v-model="editor.sectionsText" class="form-textarea generate-json-editor" rows="12" @input="markDirty" /></label>
      <label>资产关联 JSON<textarea id="generate-page-assets" v-model="editor.assetsText" class="form-textarea generate-json-editor" rows="6" @input="markDirty" /></label>
    </details>
    <p v-if="jsonError" class="generate-error-text">{{ jsonError }}</p>
    <div class="generate-result-actions">
      <button class="btn btn-sm btn-primary" data-action="apply-world-page-draft" :disabled="busy" @click="apply">应用到工作稿</button>
      <button class="btn btn-sm" data-action="continue-chat" @click="$emit('continue-chat')">继续聊</button>
      <button class="btn btn-sm" data-action="generate-another" @click="$emit('clear')">重新生成</button>
      <button v-if="contextUsage" class="btn btn-sm" data-action="view-generation-context" @click="$emit('view-context')">查看本次上下文</button>
    </div>
    <p class="generate-empty-copy">应用只更新或创建服务器工作稿，不会发布 canonical 页面。</p>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { authorDecisionPresentation, sectionDiff } from "../logic/generateLogic.js"
import { buildPageProposalApplyPayload, capturePageProposalDraft, editorFromPageProposal, pageProposalDraftMatches } from "../pageProposalSession.js"

const props = defineProps({
  result: { type: Object, default: null },
  previousResult: { type: Object, default: null },
  baseline: { type: Object, default: null },
  categories: { type: Array, default: () => [] },
  contextUsage: { type: Object, default: null },
  proposalDraft: { type: Object, default: null },
  proposalResetToken: { type: Number, default: 0 },
  recovered: Boolean,
  busy: Boolean,
})
const emit = defineEmits(["apply", "dirty", "proposal-edit", "clear", "continue-chat", "open-review", "view-context"])
const editor = reactive(editorFromPageProposal(null))
const jsonError = ref("")

function reset() {
  const restored = pageProposalDraftMatches(props.result, props.proposalDraft)
  Object.assign(editor, restored?.editor || editorFromPageProposal(props.result))
  jsonError.value = ""
}
watch(() => props.result, reset, { immediate: true })
watch(() => props.proposalResetToken, reset)

const proposal = computed(() => props.result?.proposal || {})
const page = computed(() => proposal.value.page || {})
const entityContent = computed(() => props.result?.suggestion?.payload_json || props.result?.proposal || props.result?.suggestion || {})
const decision = computed(() => authorDecisionPresentation(props.result?.suggestion?.decision_state || props.result?.decision_state))
const revisionLink = computed(() => props.result?.suggestion?.revision_link || null)
const revisionChanges = computed(() => {
  if (!props.previousResult) return []
  const previous = props.previousResult.kind === "core_entity"
    ? props.previousResult.suggestion?.payload_json || props.previousResult.proposal || {}
    : props.previousResult.proposal?.page || {}
  const current = props.result?.kind === "core_entity"
    ? props.result?.suggestion?.payload_json || props.result?.proposal || {}
    : props.result?.proposal?.page || {}
  const fields = props.result?.kind === "core_entity"
    ? [["名称", "name"], ["类型", "entity_type"], ["摘要", "summary"]]
    : [["标题", "title"], ["类别", "page_type"], ["页面概览", "free_text"]]
  return fields.flatMap(([label, key]) => {
    const before = String(previous?.[key] || "").slice(0, 180)
    const after = String(current?.[key] || "").slice(0, 180)
    return before === after ? [] : [{ label, before, after }]
  })
})
const previousSections = computed(() => Array.isArray(props.baseline?.sections_json) ? props.baseline.sections_json : [])
const nextSections = computed(() => Array.isArray(page.value.sections_json) ? page.value.sections_json : [])
const changes = computed(() => sectionDiff(previousSections.value, nextSections.value))
const summary = computed(() => proposal.value.operation === "create_new"
  ? `新建页面 · ${nextSections.value.length} 个章节`
  : `标题${props.baseline?.title === page.value.title ? "保留" : "已重构"} · 章节 ${previousSections.value.length} → ${nextSections.value.length}`)

function markDirty() {
  emit("dirty", true)
  emit("proposal-edit", capturePageProposalDraft(props.result, editor))
}
function apply() {
  try {
    jsonError.value = ""
    emit("apply", buildPageProposalApplyPayload(editor))
  } catch {
    jsonError.value = "sections 或资产关联不是有效 JSON"
  }
}
</script>

<style scoped>
.generate-author-decisions,.generate-revision-compare{margin:0 0 10px;border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 10px;color:var(--text);font-size:12px}.generate-author-decisions summary,.generate-revision-compare summary{cursor:pointer;font-weight:600}.generate-author-decisions dl,.generate-revision-compare dl{display:grid;grid-template-columns:minmax(90px,auto) minmax(0,1fr);gap:6px 12px;margin:10px 0}.generate-author-decisions dt,.generate-revision-compare dt{color:var(--text-muted);font-weight:600}.generate-author-decisions dd,.generate-author-decisions ul,.generate-revision-compare dd{margin:0;padding:0}.generate-author-decisions ul{display:grid;gap:3px;list-style-position:inside}.generate-author-decisions p,.generate-revision-compare p{margin:8px 0 0;color:var(--text-dim)}.generate-revision-lineage{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;padding:7px 9px;border:1px solid var(--accent);border-radius:var(--radius-sm);font-size:12px}.generate-revision-lineage span{color:var(--text-dim)}.generate-revision-compare dd{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:5px}.generate-revision-compare del{color:var(--text-dim)}.generate-revision-compare ins{text-decoration:none;color:var(--text)}
@media(max-width:600px){.generate-author-decisions dl,.generate-revision-compare dl{grid-template-columns:1fr;gap:3px}.generate-author-decisions dd,.generate-revision-compare dd{margin-bottom:5px}.generate-revision-lineage{align-items:flex-start;flex-direction:column}}
</style>
