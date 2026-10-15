<template>
  <details class="card auto-drafts" @toggle="onToggle">
    <summary>阅读生成的地图草图<span v-if="loaded"> · {{ total }} 个版本</span></summary>
    <p>按空间和层级分片整理，原地图位置与锁定点会保留。草图需要单独审核。</p>
    <button class="btn btn-sm" :disabled="locked" @click="load">{{ loading ? '正在读取…' : '重新读取草图' }}</button>
    <p v-if="error" class="atlas-error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="loaded && !batches.length && !items.length">还没有阅读草图。空间发现或补扫完成后，可在这里核对。</p>
    <p v-if="truncated">本次批次摘要未全部列出，请按候选分页继续核对。</p>
    <nav v-if="total > pageSize" class="draft-actions" aria-label="草图候选分页"><button class="btn btn-sm" :disabled="locked || Boolean(selected) || offset === 0" @click="changePage(-1)">上一页草图</button><span>{{ offset + 1 }}–{{ offset + items.length }} / {{ total }}</span><button class="btn btn-sm" :disabled="locked || Boolean(selected) || offset + items.length >= total" @click="changePage(1)">下一页草图</button></nav>
    <ul class="draft-batches"><li v-for="batch in batches" :key="batch.batch_id">
      <span>{{ statuses[batch.status] }} · {{ batch.completed_chunks }} / {{ batch.total_chunks }} 片</span>
      <button v-if="batch.status === 'running'" class="btn btn-sm" :disabled="locked" @click="resume(batch)">继续整理分片</button>
      <button v-else class="btn btn-sm" :disabled="locked" @click="redo(batch)">重新整理这一批</button>
      <p v-if="batch.status === 'stale'">来源或身份已变化，请先补扫或核对，再重新整理。</p>
    </li></ul>
    <article v-for="draft in items" :key="draft.revision_id" class="draft-item">
      <strong>{{ draft.node_title }}</strong><span> · {{ draft.status === 'superseded' ? '已被取代' : '待审核草图' }} · {{ draft.document.features.length }} 个图元</span>
      <p v-if="draft.stale" role="status">来源已变化，核对后才能继续使用。</p>
      <p v-for="warning in draft.warnings" :key="warning">{{ warning }}</p>
      <button class="btn btn-sm" :disabled="locked || Boolean(selected)" @click="emit('review', draft)">打开地图逐项审核</button>
      <details v-if="draft.conflicts.length"><summary>{{ draft.conflicts.length }} 处层级来源冲突</summary><p v-for="conflict in draft.conflicts" :key="conflict.fingerprint">按{{ hierarchySources[conflict.chosen_source] || '已核对来源' }}保留父级；另有 {{ conflict.alternatives.length }} 个不同来源，需要人工核对。</p></details>
      <details v-if="draft.pending_tray.length"><summary>待放置托盘 · {{ draft.pending_tray.length }} 项</summary>
        <ul class="draft-tray"><li v-for="tray in draft.pending_tray" :key="tray.item_id">
          <strong>{{ tray.endpoint.surface || (tray.endpoint.state === 'candidate' ? '候选地点' : '已绑定地点') }}</strong><p>{{ reasons[tray.reason] || '需要核对后放置' }}</p><blockquote>{{ tray.quote }}</blockquote>
          <p v-if="tray.source_mode === 'working'">工作稿线索；正式采用前仍需核对原文与地点身份。</p>
          <button class="btn btn-sm" :disabled="locked || draft.stale || draft.status !== 'candidate' || batchStatus(draft.batch_id) !== 'completed'" @click="selectTray(draft, tray)">在草图上选择位置</button>
        </li></ul>
      </details>
    </article>
    <section v-if="selected" class="tray-placement" aria-label="待放置地点定位">
      <h3>{{ selected.tray.endpoint.surface || '待放置地点' }} · {{ selected.draft.node_title }}</h3>
      <p>点击或轻触示意图选择位置，也可聚焦图后按 Enter 选点、方向键微调。确认后生成新的草图候选，坐标会锁定。</p>
      <label>放到哪个空间<select v-model="spaceId" class="form-select" :disabled="locked" @change="resetPoint"><option v-for="space in selected.draft.document.spaces" :key="space.id" :value="space.id">{{ space.label }}</option></select></label>
      <svg ref="canvas" class="tray-canvas" :viewBox="`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`" role="group" tabindex="0" aria-label="待放置位置，点击或按 Enter 选点、方向键微调" @click="choosePoint" @keydown="keyPoint">
        <rect :x="bounds.x" :y="bounds.y" :width="bounds.width" :height="bounds.height" class="tray-background" />
        <g v-for="feature in visibleFeatures" :key="feature.id">
          <polyline v-if="feature.points.length > 1" :points="pointsAttribute(feature.points)" fill="none" stroke="currentColor" />
          <circle v-if="feature.points.length" :cx="feature.points[0].x" :cy="feature.points[0].y" r="6" class="tray-existing" />
          <text v-if="feature.points.length" :x="feature.points[0].x + 10" :y="feature.points[0].y">{{ feature.label }}</text>
        </g>
        <circle v-if="point" :cx="point.x" :cy="point.y" r="10" class="tray-point" />
      </svg>
      <p v-if="point" role="status">位置已选，可先预览影响。</p>
      <div class="draft-actions"><button class="btn btn-sm" :disabled="locked || !point" @click="preparePlacement">预览放置影响</button><button class="btn btn-sm" :disabled="locked" @click="selected = null">取消定位</button></div>
      <div v-if="preview" class="tray-impact">
        <p>图元 {{ preview.old_feature_count }} → {{ preview.new_feature_count }} 个，放置后剩余 {{ preview.remaining_tray_count }} 项。</p>
        <ul><li v-for="impact in preview.impacts" :key="impact">{{ impact }}</li></ul>
        <p v-for="warning in preview.warnings" :key="warning">{{ warning }}</p>
        <button class="btn btn-primary" :disabled="locked" @click="place">确认放入草图候选</button>
      </div>
    </section>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getConfirmAction } from '../../bridge/index.js'
import { confirmAsync } from '../../../shared/confirmAsync.js'
import { mapBounds, pointsAttribute } from './mapStructureEditor.js'
const props = defineProps({ projectId: { type: String, required: true }, disabled: Boolean })
const emit = defineEmits(['state', 'changed', 'review'])
const api = getApi(), items = ref([]), batches = ref([]), total = ref(0), truncated = ref(false), offset = ref(0), loaded = ref(false), loading = ref(false), busy = ref(false), confirming = ref(false), error = ref(''), message = ref('')
const pageSize = 20
const selected = ref(null), spaceId = ref('main'), point = ref(null), preview = ref(null), canvas = ref(null)
const expanded = ref(false), refreshPending = ref(false)
let active = true, epoch = 0
const statuses = { running: '分片整理中', completed: '分片整理完成', stale: '待核对来源' }
const hierarchySources = { world_adopted: '已采用世界关系', saved_map: '已保存地图', reviewed_clue: '已复核线索', world_candidate: '候选世界关系' }
const reasons = { unresolved_endpoint: '地点身份未确定', endpoint_not_location: '端点不是地点', ambiguous_source_quote: '原文定位有歧义', feature_limit: '当前分片图元已达上限', placement_failed: '自动排布未成功', hierarchy_conflict: '层级来源不一致', source_stale: '原文来源已变化', endpoint_stale: '端点身份已变化', non_event_modality: '不是客观事件观察', relation_limit: '关系数量已达上限' }
const locked = computed(() => props.disabled || busy.value || loading.value || confirming.value)
const visibleFeatures = computed(() => (selected.value?.draft.document.features || []).filter(feature => (feature.space_id || 'main') === spaceId.value))
const bounds = computed(() => mapBounds(visibleFeatures.value))
const batchStatus = id => batches.value.find(item => item.batch_id === id)?.status
watch([busy, loading, confirming, selected], () => emit('state', { dirty: Boolean(selected.value), busy: busy.value || loading.value || confirming.value }), { immediate: true, flush: 'sync' })
watch(() => props.projectId, () => { epoch++; items.value = []; batches.value = []; total.value = 0; offset.value = 0; truncated.value = false; loaded.value = false; loading.value = false; busy.value = false; confirming.value = false; selected.value = null; resetPoint(); error.value = ''; message.value = '' })
onBeforeUnmount(() => { active = false; epoch++; emit('state', { dirty: false, busy: false }) })
watch([locked, selected], flushRefresh)
defineExpose({ refresh: requestRefresh })
function requestRefresh() { loaded.value = false; refreshPending.value = true; flushRefresh() }
function flushRefresh() { if (refreshPending.value && expanded.value && !locked.value && !selected.value) { refreshPending.value = false; void load() } }
function resetPoint() { point.value = null; preview.value = null }
function onToggle(event) { expanded.value = event.target.open; if (expanded.value && !loaded.value) { refreshPending.value = false; void load() } }
async function load() {
  if (locked.value || selected.value) return
  const token = ++epoch, projectId = props.projectId
  loading.value = true; error.value = ''
  try { const result = await api.world.listMapAutoDrafts(projectId, { limit: pageSize, offset: offset.value }); if (active && token === epoch && projectId === props.projectId) { items.value = result.items; total.value = result.total_count; batches.value = result.batches || []; truncated.value = Boolean(result.batches_truncated); loaded.value = true; resetPoint() } }
  catch (failure) { if (active && token === epoch) error.value = failure.message || '草图读取失败，请重试。' }
  finally { if (active && token === epoch) loading.value = false }
}
function changePage(delta) { if (locked.value || selected.value) return; offset.value = Math.max(0, offset.value + delta * pageSize); void load() }
async function confirmIntent(text, label) {
  if (locked.value || !active) return false
  const token = epoch, projectId = props.projectId
  confirming.value = true
  try { return await confirmAsync(text, label, { confirmAction: getConfirmAction() }) && active && token === epoch && projectId === props.projectId && !props.disabled }
  finally { if (active && token === epoch) confirming.value = false }
}
async function run(action, success) {
  if (locked.value || !active) return
  const token = ++epoch, projectId = props.projectId
  busy.value = true; error.value = ''; message.value = ''
  try { await action(); if (!active || token !== epoch || projectId !== props.projectId) return; selected.value = null; resetPoint(); message.value = success; emit('changed') }
  catch (failure) { if (active && token === epoch) { error.value = failure.status === 409 ? '地图、来源或托盘已变化，请重新读取后核对。' : failure.message || '草图操作未完成，请重新读取核对结果。'; preview.value = null } }
  finally { if (active && token === epoch) busy.value = false }
  if (active && token === epoch && !error.value) await load()
}
async function resume(batch) { await run(() => api.world.resumeMapAutoDrafts(props.projectId, batch.batch_id, { expected_fingerprint: batch.fingerprint, confirmed: true }), '本片已整理，已完成候选保留。可继续下一片或打开地图审核。') }
async function redo(batch) {
  if (!await confirmIntent('重新整理这一批草图？将保留原候选历史和已保存地图，重新核对线索与排布。', '确认重新整理')) return
  await run(() => api.world.redoMapAutoDrafts(props.projectId, batch.batch_id, { expected_fingerprint: batch.fingerprint, reason: 'author_requested', confirmed: true }), '已提交重新整理，请核对新草图。')
}
function selectTray(draft, tray) { if (locked.value || draft.stale || draft.status !== 'candidate' || batchStatus(draft.batch_id) !== 'completed') return; selected.value = { draft, tray }; spaceId.value = draft.document.spaces?.[0]?.id || 'main'; resetPoint() }
function choosePoint(event) {
  if (locked.value || !canvas.value) return
  const transform = canvas.value.getScreenCTM()
  if (!transform) return
  const location = canvas.value.createSVGPoint(); location.x = event.clientX; location.y = event.clientY
  const value = location.matrixTransform(transform.inverse())
  if (!Number.isFinite(value.x) || !Number.isFinite(value.y) || Math.abs(value.x) > 100000 || Math.abs(value.y) > 100000) return
  point.value = { x: Math.round(value.x), y: Math.round(value.y) }; preview.value = null
}
function keyPoint(event) {
  if (locked.value || !['Enter', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
  event.preventDefault()
  const current = point.value || { x: bounds.value.x + bounds.value.width / 2, y: bounds.value.y + bounds.value.height / 2 }
  const delta = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10], Enter: [0, 0] }[event.key]
  point.value = { x: Math.max(-100000, Math.min(100000, Math.round(current.x + delta[0]))), y: Math.max(-100000, Math.min(100000, Math.round(current.y + delta[1]))) }; preview.value = null
}
function placementRequest() { return { expected_fingerprint: selected.value.tray.fingerprint, base_revision_id: selected.value.draft.node.current_revision_id, space_id: spaceId.value, point: { ...point.value } } }
async function preparePlacement() {
  if (locked.value || !selected.value || !point.value) return
  const token = ++epoch, projectId = props.projectId, { draft, tray } = selected.value, request = placementRequest()
  busy.value = true; error.value = ''
  try { const result = await api.world.previewAutoDraftTrayPlacement(projectId, draft.batch_id, draft.node_id, draft.revision_id, tray.item_id, request); if (active && token === epoch && projectId === props.projectId) preview.value = { ...result, request } }
  catch (failure) { if (active && token === epoch) { error.value = failure.message || '放置预览失败，请重新核对来源。'; preview.value = null } }
  finally { if (active && token === epoch) busy.value = false }
}
async function place() {
  if (!selected.value || !preview.value || !await confirmIntent('按预览位置把这个地点放入新的草图候选？正式地图需继续单独审核。', '确认放置')) return
  const { draft, tray } = selected.value, request = { ...preview.value.request, preview_fingerprint: preview.value.preview_fingerprint, confirmed: true }
  await run(() => api.world.placeAutoDraftTrayItem(props.projectId, draft.batch_id, draft.node_id, draft.revision_id, tray.item_id, request), '已放入新的草图候选，请继续逐项审核。')
}
</script>

<style scoped>
.auto-drafts { margin-block: 1rem; padding: 1rem; }
.auto-drafts summary { cursor: pointer; font-weight: 600; }
.auto-drafts p, .auto-drafts span { color: var(--text-secondary); }
.draft-batches, .draft-tray { padding-inline-start: 1.25rem; }
.draft-batches li, .draft-tray li { margin-block: .75rem; }
.draft-item { border-top: 1px solid var(--border); margin-top: 1rem; padding-top: 1rem; overflow-wrap: anywhere; }
.draft-item details { margin-block: .75rem; }
.draft-item blockquote { margin: .5rem 0; padding-inline-start: .75rem; border-inline-start: 2px solid var(--border); }
.tray-placement { margin-top: 1rem; padding: .75rem; border: 1px solid var(--border); border-radius: .5rem; }
.tray-canvas { display: block; width: 100%; height: 300px; margin-block: .75rem; color: var(--text-primary); border: 1px solid var(--border); touch-action: manipulation; cursor: crosshair; }
.tray-background { fill: var(--bg-panel, #fafafa); }
.tray-existing { fill: var(--text-secondary, #555); }
.tray-point { fill: var(--accent, #1265e5); stroke: var(--text-primary); stroke-width: 2; }
.tray-canvas text { font-size: 14px; }
.draft-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
@media (max-width: 640px) { .draft-actions button { flex: 1 1 8rem; min-height: 2.75rem; } }
</style>
