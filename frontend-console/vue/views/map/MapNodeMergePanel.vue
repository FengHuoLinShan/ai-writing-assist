<template>
  <details v-if="node?.status === 'adopted'" class="card map-node-merge">
    <summary>整理重复地图</summary>
    <p>把当前地图的空间内容合并到同级地图。各自坐标和空间保持独立，不会猜测两图的位置关系。</p>
    <label>合并到哪张地图<select v-model="targetId" class="form-select" :disabled="locked" @change="clearPreview"><option value="">请选择目标地图</option><option v-for="target in targets" :key="target.id" :value="target.id">{{ target.title }}</option></select></label>
    <p v-if="!targets.length">还没有可选的同级地图。</p>
    <button class="btn btn-sm" :disabled="locked || !targetId" @click="prepare">预览地图合并</button>
    <section v-if="preview" class="merge-impact" aria-label="地图合并预览">
      <div class="merge-pair"><div><span>来源地图</span><strong>{{ preview.source_title }}</strong><p>{{ hierarchy(preview.source_hierarchy) }} · {{ preview.source_document?.features.length || 0 }} 个图元</p></div><div><span>保留的目标地图</span><strong>{{ preview.target_title }}</strong><p>{{ hierarchy(preview.target_hierarchy) }} · {{ preview.target_document?.features.length || 0 }} 个图元</p></div></div>
      <p>共 {{ preview.affected_count }} 项变更。合并后来源从正式目录移出，旧链接保留提示；原版本与资料依据保留。</p>
      <ul v-if="preview.blockers.length"><li v-for="blocker in preview.blockers" :key="blocker">{{ blocker }}</li></ul>
      <template v-if="preview.can_execute"><label class="merge-consent"><input v-model="sourceConfirmed" type="checkbox" :disabled="locked" />我确认将来源地图保留为只读合并记录，后续从目标地图继续编辑。</label><button class="btn btn-primary" :disabled="locked || !sourceConfirmed" @click="apply">确认合并地图</button></template>
      <button class="btn btn-sm" :disabled="locked" @click="clearPreview">取消预览</button>
    </section>
    <section v-if="node.merged_sources?.length" class="merge-history" aria-label="合并记录">
      <h3>已合并的来源</h3><div v-for="source in node.merged_sources" :key="source.id"><span>{{ source.title }}</span><button class="btn btn-sm" :disabled="locked" @click="prepareUndo(source)">预览撤回合并</button></div>
    </section>
    <section v-if="undoPreview" class="merge-impact" aria-label="撤回合并预览">
      <p>恢复“{{ undoSource.title }}”到正式目录，为“{{ node.title }}”追加合并前内容的恢复版本；合并历史仍保留。共 {{ undoPreview.affected_count }} 项变更。</p>
      <ul v-if="undoPreview.blockers.length"><li v-for="blocker in undoPreview.blockers" :key="blocker">{{ blocker }}</li></ul>
      <button v-if="undoPreview.can_undo" class="btn btn-primary" :disabled="locked" @click="undo">确认撤回合并</button><button class="btn btn-sm" :disabled="locked" @click="undoPreview = null">取消撤回</button>
    </section>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">正在核对并处理地图…</p>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getConfirmAction } from '../../bridge/index.js'
import { confirmAsync } from '../../../shared/confirmAsync.js'
const props = defineProps({ projectId: { type: String, required: true }, node: { type: Object, default: null }, nodes: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['state', 'changed'])
const api = getApi(), targetId = ref(''), preview = ref(null), sourceConfirmed = ref(false), undoPreview = ref(null), undoSource = ref(null), busy = ref(false), error = ref(''), message = ref('')
let active = true, epoch = 0
const locked = computed(() => props.disabled || busy.value)
const targets = computed(() => props.nodes.filter(item => item.id !== props.node?.id && item.level === props.node?.level && (item.parent_id || null) === (props.node?.parent_id || null)))
const levels = { region: '区域', city: '城市', district: '街区', street: '街道', interior: '室内' }
function hierarchy(value) { return [value?.parent_title || '顶层', levels[value?.level] || '地图'].join(' · ') }
function clearPreview() { preview.value = null; sourceConfirmed.value = false; undoPreview.value = null; error.value = '' }
watch(busy, value => emit('state', { busy: value }), { flush: 'sync' })
watch(() => [props.projectId, props.node?.id], () => { epoch++; targetId.value = ''; clearPreview(); message.value = '' })
onBeforeUnmount(() => { active = false; epoch++; emit('state', { busy: false }) })
async function run(action) {
  if (locked.value || !props.node) return
  const token = ++epoch, projectId = props.projectId, nodeId = props.node.id
  busy.value = true; error.value = ''
  try { await action({ projectId, nodeId, current: () => active && token === epoch && props.projectId === projectId && props.node?.id === nodeId }) }
  catch (failure) { if (active && token === epoch) { clearPreview(); error.value = failure.status === 409 ? '地图或来源已变化，选择仍保留；请重新预览后再确认。' : failure.message || '操作未完成，请重试。' } }
  finally { if (active) busy.value = false }
}
async function prepare() {
  if (!targetId.value) return
  await run(async ({ projectId, nodeId, current }) => {
    const result = await api.world.previewMapNodeMerge(projectId, { source_node_id: nodeId, target_node_id: targetId.value })
    if (current()) { clearPreview(); preview.value = result; message.value = '' }
  })
}
async function apply() {
  if (!preview.value?.can_execute || !sourceConfirmed.value) return
  await run(async ({ projectId, current }) => {
    const frozen = preview.value
    if (!await confirmAsync(`将“${frozen.source_title}”合并到“${frozen.target_title}”？来源地图将保留为只读合并记录。`, '确认合并', { confirmAction: getConfirmAction() }) || !current()) return
    const result = await api.world.mergeMapNodes(projectId, { source_node_id: frozen.source_node_id, target_node_id: frozen.target_node_id, preview_fingerprint: frozen.fingerprint, confirmed_source_disposition: true })
    if (current()) { clearPreview(); message.value = result.label; emit('changed', result) }
  })
}
async function prepareUndo(source) {
  await run(async ({ projectId, nodeId, current }) => {
    const result = await api.world.previewMapNodeMergeUndo(projectId, { source_node_id: source.id, target_node_id: nodeId })
    if (current()) { clearPreview(); undoSource.value = source; undoPreview.value = result; message.value = '' }
  })
}
async function undo() {
  if (!undoPreview.value?.can_undo) return
  await run(async ({ projectId, current }) => {
    const frozen = undoPreview.value
    if (!await confirmAsync('恢复来源地图，并为目标追加恢复版本？合并与撤回历史都会保留。', '确认撤回', { confirmAction: getConfirmAction() }) || !current()) return
    const result = await api.world.undoMapNodeMerge(projectId, { source_node_id: frozen.source_node_id, target_node_id: frozen.target_node_id, preview_fingerprint: frozen.fingerprint, confirmed: true })
    if (current()) { clearPreview(); message.value = '已撤回合并，来源地图已恢复。'; emit('changed', result) }
  })
}
</script>

<style scoped>
.map-node-merge { padding: 16px; margin-bottom: 16px; }
.map-node-merge summary { cursor: pointer; font-weight: 600; }
.map-node-merge label { display: grid; gap: 8px; margin: 12px 0; }
.map-node-merge .form-select { max-width: 100%; }
.merge-impact, .merge-history { padding: 14px 0; border-top: 1px solid var(--border-color, #ddd); margin-top: 14px; }
.merge-pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.merge-pair strong, .merge-pair span { display: block; overflow-wrap: anywhere; }
.merge-consent { grid-template-columns: auto 1fr; align-items: start; }
.merge-history > div { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
@media (max-width: 600px) { .merge-pair { grid-template-columns: 1fr; } }
</style>
