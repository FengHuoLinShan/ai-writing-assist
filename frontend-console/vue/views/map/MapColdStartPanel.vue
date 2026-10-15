<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { getApi, getRouter } from '../../bridge/index.js'
import ReadingFlow from '../../components/ReadingFlow.vue'
import WritingFlowHost from '../writing/components/WritingFlowHost.vue'
import MapCandidateLocations from './MapCandidateLocations.vue'
import { projectSettingsSession } from '../settings/projectSettingsSession.js'

const props = defineProps({ projectId: { type: String, required: true }, disabled: Boolean })
const emit = defineEmits(['state', 'review'])
const state = reactive({ view: null, busy: false, error: '', visible: true })
const evolution = ref(null), opened = ref(false), ready = ref(false), dirty = ref(false), authorizing = ref(false)
const locationState = ref({ selected: false, busy: false })
const scope = reactive({ kind: 'reading', endChapter: 1, from: 1, through: 1, limit: 20 })
const step = computed(() => state.view?.stop?.step_id)
const panel = computed(() => state.view?.panel || {})
const run = computed(() => evolution.value?.run)
const locked = computed(() => props.disabled || state.busy || authorizing.value || locationState.value.busy)
const controller = { state, dismiss: () => { opened.value = false } }
let epoch = 0, alive = true
async function perform(action, readOnly = false) {
  if (state.busy || authorizing.value || locationState.value.busy || (props.disabled && !readOnly)) return
  const token = epoch, projectId = props.projectId
  state.busy = true; state.error = ''
  try {
    const result = await action(projectId)
    if (!alive || epoch !== token) return
    if (result?.run_id && result.flow_id === 'map_cold_start') state.view = result
    return result
  } catch (error) { if (alive && epoch === token) state.error = error.message || '引导暂未更新，已有预览与结果保留。' }
  finally { if (alive && epoch === token) state.busy = false }
}
async function toggle(event) {
  opened.value = event.target.open
  if (!opened.value || state.view) return
  await perform(async projectId => {
    const token = epoch
    const [latest, status] = await Promise.all([getApi().assistant.guidedFlowLatest(projectId, 'map_cold_start'), getApi().evolution.status(projectId)])
    if (alive && epoch === token) { evolution.value = status; ready.value = true; scope.through = Math.max(1, status.run?.completed_scenes || 1); scope.endChapter = (status.run?.end_chapter || 0) + 1 }
    return latest
  }, true)
}
async function start() {
  if (!ready.value) return
  await perform(projectId => getApi().assistant.guidedFlowStart({ novel_id: projectId, flow_id: 'map_cold_start' }))
}
async function choose(action, payload = {}) {
  if (!state.view) return
  await perform(projectId => getApi().assistant.guidedFlowAdvance(state.view.run_id, { novel_id: projectId, choice: { step_id: step.value, action, ...payload } }))
}
async function refreshLocations(message) { await choose('refresh'); if (alive) state.error = message }
async function prepare() {
  const budgetMode = run.value?.budget_mode || evolution.value?.default_budget_mode
  const args = { operation_id: crypto.randomUUID(), request_limit: budgetMode === 'confirmed_scope' ? null : Number(scope.limit) }
  let capability
  if (scope.kind === 'rescan') {
    capability = 'evolution.prepare_spatial_rescan'
    Object.assign(args, { run_key: run.value?.run_key, from_scene_index: Number(scope.from) - 1, through_scene_index: Number(scope.through) - 1 })
  } else {
    capability = 'evolution.prepare_spatial_reading'
    const status = run.value?.status
    const mode = status === 'completed' ? 'append' : status === 'needs_budget' ? 'continue' : status === 'source_changed' ? 'revise' : status === 'failed' ? 'scoped_recompute' : 'bootstrap'
    Object.assign(args, { mode, run_key: mode === 'bootstrap' ? null : run.value?.run_key, end_chapter: ['continue', 'revise', 'scoped_recompute'].includes(mode) ? run.value.end_chapter : Number(scope.endChapter), discover_spatial: true, discover_details: mode === 'bootstrap' ? false : !!run.value?.discovery_enabled, ...(mode === 'scoped_recompute' ? { from_scene_index: Number(scope.from) - 1 } : {}) })
  }
  await choose('prepare_preview', { capability, arguments: args })
  if (step.value === 'authorization') dirty.value = false
}
function openEvolution() { projectSettingsSession.tab = 'deep'; getRouter().navigate('project-settings') }
async function abandon() {
  const result = await perform(projectId => getApi().assistant.guidedFlowAbandon(projectId, state.view.run_id))
  if (result?.status === 'cancelled') { state.view = null; dirty.value = false }
}
watch([() => dirty.value, () => state.busy, authorizing, locationState], () => emit('state', { dirty: dirty.value || locationState.value.selected, busy: state.busy || authorizing.value || locationState.value.busy }))
watch(() => props.projectId, () => { epoch++; state.view = null; state.busy = false; state.error = ''; evolution.value = null; ready.value = false; opened.value = false; dirty.value = false; authorizing.value = false; locationState.value = { selected: false, busy: false } })
onBeforeUnmount(() => { alive = false; epoch++ })
</script>

<template>
  <details class="map-cold-start card" :open="opened" @toggle="toggle">
    <summary>从正文建立可用地图</summary>
    <p v-if="state.error" role="alert">{{ state.error }}</p>
    <p v-if="state.busy && !ready" role="status">正在读取当前引导与演化范围…</p>
    <template v-if="!state.view">
      <p>先确认阅读或已读范围补扫，再由你确认模型费用。发现结果进入草图，审核后才成为正式地图。</p>
      <button class="btn" :disabled="locked || !ready" @click="start">开始地图引导</button>
      <button class="btn btn-sm" :disabled="locked" @click="toggle({ target: { open: true } })">重新读取引导</button>
    </template>
    <WritingFlowHost v-else :controller="controller" custom-actions>
      <form v-if="step === 'scope'" class="map-cold-scope" @submit.prevent="prepare" @input="dirty = true" @change="dirty = true">
        <p v-if="evolution?.engine?.engine !== 'evolution'">请先在作品偏好中启用逐场景理解，再回来准备范围。</p>
        <fieldset :disabled="locked || evolution?.engine?.engine !== 'evolution'">
          <legend>空间发现范围</legend>
          <label>处理方式<select v-model="scope.kind"><option value="reading">读取正文并发现空间</option><option value="rescan" :disabled="run?.status !== 'completed'">已读范围补扫空间</option></select></label>
          <label v-if="scope.kind === 'reading'">读到第几章<input v-model.number="scope.endChapter" type="number" min="1" required></label>
          <template v-if="scope.kind === 'rescan' || run?.status === 'failed'"><label>从第几场<input v-model.number="scope.from" type="number" min="1" :max="run?.completed_scenes || run?.total_scenes" required></label><label v-if="scope.kind === 'rescan'">到第几场<input v-model.number="scope.through" type="number" :min="scope.from" :max="run?.completed_scenes" required></label></template>
          <label v-if="(run?.budget_mode || evolution?.default_budget_mode) !== 'confirmed_scope'">本次模型调用上限<input v-model.number="scope.limit" type="number" min="1" max="1000" required></label>
          <button class="btn btn-primary" type="submit">预览空间范围与费用</button>
        </fieldset>
      </form>
      <ReadingFlow v-if="step === 'authorization'" :key="panel.arguments?.operation_id" :project-id="projectId" :prepared-authorization="panel" :authorization-disabled="disabled || state.busy" @authorized="choose('bind_authorized_run', { run_key: $event })" @authorization-state="authorizing = $event.busy" />
      <p v-if="panel.progress" role="status">{{ ({ pending: '等待演化执行', running: '演化正在处理', completed: '演化处理完成', needs_reconciliation: '原请求结果未知，请核对回执；不会重发' })[panel.progress.status] || '演化需要作者核对' }}</p>
      <section v-if="panel.drafts" aria-label="待审核空间草图">
        <p>候选 {{ panel.drafts.candidate_count }} 项 · 已保存地图 {{ panel.drafts.saved_node_count }} 张。每批最多 {{ panel.batch_limit || 20 }} 项变更。</p>
        <p v-if="panel.drafts.truncated">当前仅显示部分摘要，请在下方地图草图托盘分批审核。</p>
        <p>打开下方“阅读生成的地图草图”，按独立空间与地图层级定位、预览并审核。</p>
        <button class="btn" :disabled="locked" @click="emit('review')">前往草图审核</button>
      </section>
      <MapCandidateLocations v-if="step === 'locations'" :project-id="projectId" :locations="panel.candidate_locations || panel.drafts?.candidate_locations || []" :truncated="panel.candidate_locations_truncated || panel.drafts?.candidate_locations_truncated" :disabled="disabled || state.busy || authorizing" @state="locationState = $event" @adopted="choose('refresh')" @stale="refreshLocations" />
      <div class="map-cold-actions">
        <button v-if="['completed', 'cancelled'].includes(state.view.status)" class="btn" :disabled="locked" @click="start">开始新的地图引导</button>
        <button v-if="['monitor', 'review'].includes(step)" class="btn" :disabled="locked" @click="choose('refresh')">刷新地图引导进度</button>
        <button v-if="step === 'locations'" class="btn" :disabled="locked" @click="getRouter().navigate('world')">去世界资料核对地点</button>
        <button v-if="step === 'locations'" class="btn btn-primary" :disabled="locked || locationState.selected" @click="choose('finish')">完成地图引导</button>
        <button v-if="state.view.status !== 'completed'" class="btn btn-sm" :disabled="locked" @click="openEvolution">去演化核对</button>
        <button v-if="!['completed', 'cancelled'].includes(state.view.status)" class="btn btn-sm" :disabled="locked" @click="abandon">结束本次引导</button>
      </div>
    </WritingFlowHost>
  </details>
</template>

<style scoped>
.map-cold-start { padding: 1rem; margin-block: 1rem; min-width: 0; }
.map-cold-start summary { cursor: pointer; font-weight: 600; }
.map-cold-scope fieldset { display: grid; gap: .75rem; min-width: 0; }
.map-cold-scope label { display: grid; gap: .35rem; }
.map-cold-scope input, .map-cold-scope select { width: 100%; min-height: 44px; box-sizing: border-box; }
.map-cold-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
p { overflow-wrap: anywhere; }
</style>
