<script setup>
import WorldEvidenceSummary from "./WorldEvidenceSummary.vue"
import { computed, onBeforeUnmount, reactive, watch } from 'vue'
import { getApi, getAppState } from '../../../bridge/index.js'
import { aliasKey, prepareAliasReviewDecision, prepareRelationReviewDecision, persistAliasReviewDecision, persistRelationReviewDecision } from '../logic/useWorldReview.js'
import { catalogKindItems, catalogTypeItems } from '../logic/worldTypeCatalog.js'
import { toggleBulkSelection } from '../logic/worldBulkSelection.js'
const props = defineProps({ kind: { type: String, required: true }, items: { type: Array, required: true }, catalog: { type: Object, default: () => ({}) } })
const rows = reactive({})
let alive = true
const keyOf = item => props.kind === 'alias' ? aliasKey(item) : item.group_id
const kinds = computed(() => catalogKindItems(props.catalog, props.kind))
const types = computed(() => catalogTypeItems(props.catalog, props.kind))
watch(() => props.items, items => {
  for (const item of items) {
    const key = keyOf(item)
    if (rows[key]?.fingerprint === item.execution_fingerprint) continue
    const prepared = props.kind === 'alias' ? prepareAliasReviewDecision(item) : prepareRelationReviewDecision(item)
    rows[key] = { draft: prepared.draft, fingerprint: item.execution_fingerprint, reviewed: false, query: '', matches: [], error: '', request: 0 }
  }
}, { immediate: true })
function changed(item) {
  const row = rows[keyOf(item)]
  row.reviewed = false
  if (row.draft) row.draft._kind_explicit = true
  toggleBulkSelection(props.kind === 'alias' ? 'world-aliases' : 'world-relation-groups', keyOf(item), false)
  if (row.draft) (props.kind === 'alias' ? persistAliasReviewDecision : persistRelationReviewDecision)(item, row.draft)
}
function confirmRow(item) {
  const row = rows[keyOf(item)], draft = row.draft
  if (!draft || !draft[`${props.kind}_kind`] || !draft[`${props.kind}_type`] || (props.kind === 'alias' ? !draft.target_entity_id || !draft.alias : !draft.source_id || !draft.target_id || draft.source_id === draft.target_id)) { row.error = '请先补齐归属、方向和分类'; return }
  row.error = ''; changed(item); row.reviewed = true
  toggleBulkSelection(props.kind === 'alias' ? 'world-aliases' : 'world-relation-groups', keyOf(item), true)
}
function swap(item) { const draft = rows[keyOf(item)].draft; [draft.source_id, draft.target_id] = [draft.target_id, draft.source_id]; changed(item) }
async function search(item) {
  const row = rows[keyOf(item)], token = ++row.request, projectId = getAppState()?.currentProjectId
  row.error = ''
  try {
    const result = await getApi().world.listEntities({ novel_id: projectId, q: row.query, limit: 20 })
    if (alive && token === row.request && getAppState()?.currentProjectId === projectId) row.matches = (result.items || result || []).filter(item => ['draft', 'candidate', 'canonical'].includes(item.status))
  } catch (err) { if (alive && token === row.request) row.error = err.message || '搜索失败，请重试' }
}
onBeforeUnmount(() => { alive = false })
</script>
<template>
  <details class="review-batch"><summary>就地批量核对（{{ items.length }} 项）</summary><p>逐行核对后勾入本次处理，再使用上方“应用已准备决策”。归并关系时仍需确认影响范围。</p>
    <article v-for="item in items" :key="keyOf(item)">
      <template v-if="rows[keyOf(item)]?.draft && !item.managed_by_suggestion">
        <strong>{{ kind === 'alias' ? item.alias : `${item.source_name} → ${item.target_name}` }}</strong>
        <details><summary>核对证据与影响</summary><WorldEvidenceSummary v-if="kind === 'alias'" :item="item" kind="alias" /><WorldEvidenceSummary v-for="member in kind === 'relation' ? item.members || [] : []" :key="member.id" :item="member.evidence_summary || member" kind="relation" /><p>证据不足或身份有歧义时，请留待单条处理；归并会迁移所选候选证据。</p></details>
        <p v-if="kind === 'relation'">本组 {{ item.members?.length || 0 }} 条候选；只处理已准备范围，其余保留待审。</p>
        <div v-if="kind === 'alias'" class="review-batch-fields"><input v-model="rows[keyOf(item)].query" aria-label="搜索别名归属对象" placeholder="名称或别名" @keydown.enter.prevent="search(item)" /><button type="button" class="btn btn-sm" @click="search(item)">查找归属</button><select v-model="rows[keyOf(item)].draft.target_entity_id" aria-label="别名归属" @change="changed(item)"><option :value="item.entity_id">{{ item.entity_name || '原归属对象' }}</option><option v-for="target in rows[keyOf(item)].matches.filter(target => target.id !== item.entity_id)" :key="target.id" :value="target.id">{{ target.name }}</option></select></div>
        <div v-else><span>{{ rows[keyOf(item)].draft.source_id === item.source_id ? `${item.source_name} → ${item.target_name}` : `${item.target_name} → ${item.source_name}` }}</span><button type="button" class="btn btn-sm" @click="swap(item)">交换方向</button></div>
        <div class="review-batch-fields"><select v-model="rows[keyOf(item)].draft[`${kind}_kind`]" aria-label="分类" @change="changed(item)"><option value="">选择分类</option><option v-for="option in kinds" :key="option.value" :value="option.value">{{ option.label }}</option></select><select v-model="rows[keyOf(item)].draft[`${kind}_type`]" aria-label="详细类型" @change="changed(item)"><option v-if="!types.some(option => option.value === rows[keyOf(item)].draft[`${kind}_type`])" :value="rows[keyOf(item)].draft[`${kind}_type`]">保留现有自定义类型</option><option v-for="option in types" :key="option.value" :value="option.value">{{ option.label }}</option></select><button class="btn btn-sm" type="button" :disabled="rows[keyOf(item)].reviewed" @click="confirmRow(item)">{{ rows[keyOf(item)].reviewed ? '已核对并选中' : '已核对，加入本次处理' }}</button></div><p v-if="rows[keyOf(item)].error" role="alert">{{ rows[keyOf(item)].error }}</p>
      </template><p v-else>此项需要先处理对象或补齐证据，请从单条审阅入口查看。</p>
    </article><datalist :id="`review-batch-types-${kind}`"><option v-for="option in types" :key="option.value" :value="option.value">{{ option.label }}</option></datalist>
  </details>
</template>
<style scoped>
.review-batch{margin-block:12px;padding:12px;border:1px solid var(--border);border-radius:var(--radius-md)}.review-batch article{padding-block:12px;border-bottom:1px solid var(--border)}.review-batch-fields{display:flex;gap:8px;flex-wrap:wrap;margin-block:8px}.review-batch input,.review-batch select{min-width:0;max-width:100%;min-height:44px}.review-batch button{min-height:44px}
</style>
