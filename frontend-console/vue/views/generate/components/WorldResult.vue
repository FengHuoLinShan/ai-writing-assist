<template>
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
import { sectionDiff } from "../logic/generateLogic.js"
import { buildPageProposalApplyPayload, capturePageProposalDraft, editorFromPageProposal, pageProposalDraftMatches } from "../pageProposalSession.js"

const props = defineProps({
  result: { type: Object, default: null },
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
