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
  <div v-else class="generate-result-card generate-page-result">
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
    <label>标题<input id="generate-page-title" v-model="draft.title" class="form-input" @input="markDirty" /></label>
    <label>类别
      <select id="generate-page-type" v-model="draft.page_type" class="form-select" @change="markDirty">
        <option v-for="category in categories" :key="category.category_key" :value="category.category_key">{{ category.name || category.category_key }}</option>
      </select>
    </label>
    <label>页面概览<textarea id="generate-page-free-text" v-model="draft.free_text" class="form-textarea" rows="6" @input="markDirty" /></label>
    <label>完整 sections JSON<textarea id="generate-page-sections" v-model="sectionsText" class="form-textarea generate-json-editor" rows="12" @input="markDirty" /></label>
    <label>资产关联 JSON<textarea id="generate-page-assets" v-model="assetsText" class="form-textarea generate-json-editor" rows="6" @input="markDirty" /></label>
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

const props = defineProps({
  result: { type: Object, default: null },
  baseline: { type: Object, default: null },
  categories: { type: Array, default: () => [] },
  contextUsage: { type: Object, default: null },
  busy: Boolean,
})
const emit = defineEmits(["apply", "dirty", "clear", "continue-chat", "open-review", "view-context"])
const draft = reactive({ title: "", page_type: "custom", free_text: "" })
const sectionsText = ref("[]")
const assetsText = ref("[]")
const jsonError = ref("")

function reset() {
  const page = props.result?.proposal?.page || {}
  draft.title = page.title || ""
  draft.page_type = page.page_type || "custom"
  draft.free_text = page.free_text || ""
  sectionsText.value = JSON.stringify(page.sections_json || [], null, 2)
  assetsText.value = JSON.stringify(page.linked_asset_refs_json || [], null, 2)
  jsonError.value = ""
}
watch(() => props.result, reset, { immediate: true })

const proposal = computed(() => props.result?.proposal || {})
const page = computed(() => proposal.value.page || {})
const entityContent = computed(() => props.result?.suggestion?.payload_json || props.result?.proposal || props.result?.suggestion || {})
const previousSections = computed(() => Array.isArray(props.baseline?.sections_json) ? props.baseline.sections_json : [])
const nextSections = computed(() => Array.isArray(page.value.sections_json) ? page.value.sections_json : [])
const changes = computed(() => sectionDiff(previousSections.value, nextSections.value))
const summary = computed(() => proposal.value.operation === "create_new"
  ? `新建页面 · ${nextSections.value.length} 个章节`
  : `标题${props.baseline?.title === page.value.title ? "保留" : "已重构"} · 章节 ${previousSections.value.length} → ${nextSections.value.length}`)

function markDirty() { emit("dirty", true) }
function apply() {
  try {
    const sections = JSON.parse(sectionsText.value || "[]")
    const assets = JSON.parse(assetsText.value || "[]")
    jsonError.value = ""
    emit("apply", { page: { ...draft, sections_json: sections, linked_asset_refs_json: assets } })
  } catch {
    jsonError.value = "sections 或资产关联不是有效 JSON"
  }
}
</script>
