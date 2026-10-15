<template>
  <details class="card spatial-clues" @toggle="onToggle">
    <summary>阅读发现的空间线索<span v-if="loaded"> · {{ total }} 条</span></summary>
    <p>核对原文后确认、拒绝或合并线索。确认线索后，地图草图仍需单独审核。</p>
    <div class="clue-toolbar">
      <label>状态<select v-model="filter" class="form-select" :disabled="locked || dirty" @change="changeFilter"><option value="pending">待审核与待核对</option><option value="all">全部状态</option><option v-for="(label, value) in statuses" :key="value" :value="value">{{ label }}</option></select></label>
      <button class="btn btn-sm" :disabled="locked || dirty" @click="load">{{ loading ? '正在读取…' : '重新读取' }}</button>
    </div>
    <p v-if="error" class="atlas-error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="loading" role="status">正在读取空间线索…</p>
    <p v-else-if="loaded && !items.length">当前范围没有空间线索。已授权的演化阅读或空间补扫完成后，可在这里核对。</p>
    <ul class="clue-list">
      <li v-for="clue in items" :key="clue.id" :class="{ selected: selected?.id === clue.id }">
        <button class="clue-choice" :aria-pressed="selected?.id === clue.id" :disabled="locked" @click="select(clue)">
          <strong>{{ kinds[clue.kind] || clue.kind }} · {{ statuses[clue.status] }}</strong>
          <span>场景 {{ clue.scene_index + 1 }} · {{ modalities[clue.modality] || clue.modality }}</span>
          <q>{{ clue.quote }}</q>
        </button>
        <form v-if="selected?.id === clue.id" class="clue-review" @submit.prevent="decide('adopt')">
          <p>起点：{{ endpointLabel(clue.subject) }}<template v-if="clue.target"> → 终点：{{ endpointLabel(clue.target) }}</template></p>
          <p v-if="clue.relation">关系：{{ clue.relation }}</p>
          <p v-if="clue.modality !== 'event_observed'">这条线索属于{{ modalities[clue.modality] || clue.modality }}，不作为客观空间事实参与计算。</p>
          <p v-if="clue.verification_note" role="status">待核对：{{ clue.verification_note }}</p>
          <details v-if="clue.type_proposal"><summary>新类型提议：{{ clue.type_proposal.name }}</summary><p>{{ clue.type_proposal.description }}</p><ul><li v-for="(proof, index) in clue.type_proposal.evidence" :key="index">{{ proof.quote }}</li></ul></details>
          <details><summary>来源与端点身份</summary><p>场景：{{ clue.scene_id }}</p><p v-if="clue.subject.entity_id">起点：{{ clue.subject.entity_id }}</p><p v-if="clue.target?.entity_id">终点：{{ clue.target.entity_id }}</p><p v-if="clue.type_ref">固定类型：{{ clue.type_ref }} · 修订 {{ clue.type_revision_id }}</p><p v-if="clue.attributes?.access_conditions?.length">通行条件：{{ clue.attributes.access_conditions.join('、') }}</p><p v-if="clue.attributes?.transport_label">交通方式：{{ clue.attributes.transport_label }}</p></details>
          <template v-if="reviewable(clue)">
            <label>复核说明<textarea v-model="reason" class="form-textarea" maxlength="500" rows="2" :disabled="locked" /></label>
            <div class="clue-actions"><button class="btn btn-primary" :disabled="locked || clue.status !== 'pending_review'">确认这条线索</button><button type="button" class="btn" :disabled="locked" @click="decide('reject')">拒绝线索</button></div>
            <p v-if="clue.status === 'pending_verification'">来源或含义仍待核对，请修正来源并补扫后再确认。</p>
            <label>合并到本页同类线索<select v-model="mergeTarget" class="form-select" :disabled="locked"><option value="">选择保留的线索</option><option v-for="target in mergeChoices" :key="target.id" :value="target.id">场景 {{ target.scene_index + 1 }} · {{ target.quote }}</option></select></label>
            <button type="button" class="btn btn-sm" :disabled="locked || !mergeTarget" @click="decide('merge')">确认合并</button>
          </template>
          <button type="button" class="btn btn-sm" :disabled="locked" @click="close">收起复核</button>
        </form>
      </li>
    </ul>
    <nav v-if="loaded && total > limit" class="clue-actions" aria-label="空间线索翻页"><button class="btn btn-sm" :disabled="locked || dirty || offset === 0" @click="page(-1)">上一页</button><span>{{ offset + 1 }}–{{ Math.min(offset + items.length, total) }} / {{ total }}</span><button class="btn btn-sm" :disabled="locked || dirty || offset + limit >= total" @click="page(1)">下一页</button></nav>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getConfirmAction } from '../../bridge/index.js'
import { confirmAsync } from '../../../shared/confirmAsync.js'

const props = defineProps({ projectId: { type: String, required: true }, disabled: Boolean })
const emit = defineEmits(['state', 'changed'])
const api = getApi(), limit = 20
const statuses = { pending_review: '待审核', pending_verification: '待核对', adopted: '已确认', rejected: '已拒绝', superseded: '已合并或取代' }
const kinds = { contains: '包含', bearing: '方位', adjacency: '相邻', connection: '连接', journey: '行程', access_condition: '通行条件', effective_change: '生效变化' }
const modalities = { event_observed: '原文已发生', character_statement: '人物陈述', belief: '主观认知', hypothesis: '假设', author_plan: '作者计划', figurative: '比喻', unclear: '含义待核对' }
const items = ref([]), total = ref(0), offset = ref(0), filter = ref('pending'), loaded = ref(false), loading = ref(false), busy = ref(false), confirming = ref(false)
const selected = ref(null), reason = ref(''), mergeTarget = ref(''), error = ref(''), message = ref('')
let active = true, sequence = 0
const dirty = computed(() => Boolean(reason.value.trim() || mergeTarget.value))
const locked = computed(() => props.disabled || busy.value || loading.value || confirming.value)
const reviewable = clue => ['pending_review', 'pending_verification'].includes(clue.status)
const mergeChoices = computed(() => items.value.filter(item => item.id !== selected.value?.id && item.kind === selected.value?.kind && ['pending_review', 'adopted'].includes(item.status)))
watch([dirty, busy, confirming, loading], () => emit('state', { dirty: dirty.value, busy: busy.value || confirming.value || loading.value }), { immediate: true })
watch(() => props.projectId, () => { sequence++; items.value = []; total.value = 0; offset.value = 0; loaded.value = false; loading.value = false; busy.value = false; confirming.value = false; selected.value = null; reason.value = ''; mergeTarget.value = ''; error.value = ''; message.value = '' })
onBeforeUnmount(() => { active = false; sequence++ })
function endpointLabel(endpoint) { return endpoint.surface || (endpoint.state === 'canonical' ? '已采用实体（原文见上）' : '候选实体（原文见上）') }
async function confirmIntent(text, label) {
  if (!active || locked.value) return false
  const token = sequence, projectId = props.projectId
  confirming.value = true
  try { return await confirmAsync(text, label, { confirmAction: getConfirmAction() }) && active && token === sequence && projectId === props.projectId && !props.disabled }
  finally { if (token === sequence) confirming.value = false }
}
async function discard() { return !dirty.value || await confirmIntent('复核说明尚未提交，放弃这次编辑吗？', '确认放弃') }
async function select(clue) { if (!locked.value && await discard() && active && !locked.value) { selected.value = clue; reason.value = ''; mergeTarget.value = '' } }
async function close() { if (!locked.value && await discard() && active && !locked.value) { selected.value = null; reason.value = ''; mergeTarget.value = '' } }
async function load() {
  if (locked.value || dirty.value) return
  const token = ++sequence, projectId = props.projectId
  loading.value = true; error.value = ''
  const status = filter.value === 'pending' ? ['pending_review', 'pending_verification'] : filter.value === 'all' ? undefined : [filter.value]
  try {
    const result = await api.world.listSpatialClues(projectId, { status, limit, offset: offset.value })
    if (!active || token !== sequence || projectId !== props.projectId) return
    items.value = result.items; total.value = result.total_count; loaded.value = true; selected.value = null
  } catch (failure) { if (active && token === sequence) error.value = failure.message || '线索读取失败，请重试。' }
  finally { if (active && token === sequence) loading.value = false }
}
function onToggle(event) { if (event.target.open && !loaded.value) load() }
function changeFilter() { offset.value = 0; load() }
function page(delta) { offset.value = Math.max(0, offset.value + delta * limit); load() }
async function decide(action) {
  const clue = selected.value, target = mergeChoices.value.find(item => item.id === mergeTarget.value)
  if (!clue || !reviewable(clue) || (action === 'adopt' && clue.status !== 'pending_review') || (action === 'merge' && !target)) return
  const labels = { adopt: '确认线索', reject: '拒绝线索', merge: '确认合并' }
  const detail = action === 'merge' ? `将此线索合并到“${target.quote}”？保留目标线索及历史来源。` : `${labels[action]}“${clue.quote}”？`
  if (!await confirmIntent(detail, labels[action])) return
  const token = ++sequence, projectId = props.projectId
  const payload = { action, expected_fingerprint: clue.fingerprint, confirmed: true, reason: reason.value }
  if (action === 'merge') { payload.target_clue_id = target.id; payload.target_fingerprint = target.fingerprint }
  busy.value = true; error.value = ''; message.value = ''
  try {
    await api.world.reviewSpatialClue(projectId, clue.id, payload)
    if (!active || token !== sequence || projectId !== props.projectId) return
    reason.value = ''; mergeTarget.value = ''; selected.value = null
    message.value = action === 'adopt' ? '线索已确认。请继续核对地图草图。' : action === 'merge' ? '线索已合并。' : '线索已拒绝。'
    emit('changed')
  } catch (failure) { if (active && token === sequence) error.value = failure.status === 409 ? '线索或来源已变化，说明已保留。请复制说明、收起复核，再重新读取核对。' : failure.message || '复核未完成，说明已保留。' }
  finally { if (active && token === sequence) busy.value = false }
  if (active && token === sequence && !error.value) await load()
}
</script>

<style scoped>
.spatial-clues { margin-block: 1rem; padding: 1rem; }
.spatial-clues summary { cursor: pointer; font-weight: 600; }
.spatial-clues p, .clue-choice span { color: var(--text-secondary); }
.clue-toolbar, .clue-actions { display: flex; align-items: end; flex-wrap: wrap; gap: .75rem; margin-block: .75rem; }
.clue-toolbar label { flex: 1 1 12rem; }
.clue-list { list-style: none; padding: 0; display: grid; gap: .75rem; }
.clue-list > li { border: 1px solid var(--border); border-radius: .5rem; min-width: 0; }
.clue-list > li.selected { border-color: var(--accent); }
.clue-choice { width: 100%; padding: .85rem; text-align: left; font: inherit; color: var(--text-primary); background: transparent; border: 0; cursor: pointer; }
.clue-choice strong, .clue-choice span, .clue-choice q, .clue-review label { display: block; }
.clue-choice q { margin-top: .5rem; line-height: 1.6; overflow-wrap: anywhere; }
.clue-review { padding: 0 .85rem .85rem; overflow-wrap: anywhere; }
.clue-review label, .clue-review details { margin-block: .75rem; }
.clue-actions button { min-height: 2.75rem; }
@media (max-width: 640px) { .clue-actions > button { flex: 1 1 8rem; } }
</style>
