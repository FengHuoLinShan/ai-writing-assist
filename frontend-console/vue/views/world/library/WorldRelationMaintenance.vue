<template>
  <details class="relation-maintenance" @toggle="$event.target.open && !ready && load()">
    <summary>维护与恢复这条关系</summary>
    <p>结束有效期会保留关系。移除需要本人确认；本入口的操作保留修改前快照。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="backupError" role="alert">{{ backupError }}</p>
    <button v-if="!ready && !pending" class="btn btn-sm" type="button" :disabled="busy" @click="load">{{ busy ? '正在读取…' : '读取当前关系与历史' }}</button>
    <form v-if="ready" @submit.prevent="prepare()">
      <fieldset :disabled="busy || Boolean(pending)">
        <legend>{{ removed ? '关系已移除，可从下面的记录恢复' : '准备具体修改' }}</legend>
        <label>关系操作<select v-model="action"><option value="edit" :disabled="removed">修改描述与强度</option><option value="end" :disabled="removed">结束作者有效期</option><option value="remove" :disabled="removed">移除关系（本人确认）</option></select></label>
        <template v-if="action === 'edit' && !removed"><label>关系描述<textarea v-model="description" maxlength="12000" /></label><label>关系强度<input v-model.number="strength" type="number" min="0" max="1" step="0.1" /></label></template>
        <label v-if="action === 'end' && !removed">到哪个场景结束<select v-model="endId"><option value="">选择本作品场景</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || `第 ${scene.scene_index ?? '?'} 场` }}</option></select></label>
        <button class="btn btn-sm" type="submit" :disabled="removed || (action === 'end' && !endId)">查看修改预览</button>
      </fieldset>
    </form>
    <section v-if="preview" aria-label="关系修改预览">
      <strong>{{ preview.preview.title }}</strong>
      <p>{{ actionLabel(preview.preview.action) }}；方向保持不变。</p>
      <div class="relation-maintenance__comparison"><div><strong>当前</strong><p>{{ preview.preview.before.description || '未填写描述' }}</p><p>{{ statusLabel(preview.preview.before.status) }} · 强度 {{ preview.preview.before.strength }}</p><p>{{ validityLabel(preview.preview.before.validity) }}</p></div><div><strong>修改后</strong><p>{{ preview.preview.after.description || '未填写描述' }}</p><p>{{ statusLabel(preview.preview.after.status) }} · 强度 {{ preview.preview.after.strength }}</p><p>{{ validityLabel(preview.preview.after.validity) }}</p></div></div>
      <button class="btn btn-sm" :class="preview.preview.action === 'remove' ? 'btn-danger' : 'btn-primary'" type="button" :disabled="busy" @click="confirm">{{ preview.preview.action === 'remove' ? '本人确认移除' : preview.preview.action === 'restore' ? '确认恢复' : '确认修改' }}</button>
    </section>
    <button v-else-if="pending" class="btn btn-sm" type="button" :disabled="busy" @click="confirm">核对上次执行结果</button>
    <p v-if="receipt" role="status">{{ receipt.label }}。原回执已保留。</p>
    <section v-if="ready" aria-label="关系操作历史">
      <h4>修改与恢复记录</h4>
      <p v-if="!history.length">本入口尚无修改记录；旧操作缺少快照时无法猜测恢复。</p>
      <article v-for="item in history" :key="item.id"><p>{{ actionLabel(item.action) }} · {{ new Date(item.created_at).toLocaleString() }}</p><button class="btn btn-sm" type="button" :disabled="busy || Boolean(pending)" @click="prepare(item)">比较并恢复到这次修改前</button></article>
      <button v-if="hasMore" class="btn btn-sm" type="button" :disabled="busy" @click="load(true)">读取更早的记录</button>
    </section>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getLocalDraftAccountScope, getLocalDraftStorage } from '../../../bridge/index.js'
import { clearLocalDraftBackup, readLocalDraftBackup, writeLocalDraftBackup } from '../../../shared/localDraftBackup.js'
import { createOperationId } from '../../../../shared/workflowProgress.js'
const props = defineProps({ projectId: { type: String, required: true }, relation: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const ready = ref(false), busy = ref(false), error = ref(''), backupError = ref(''), action = ref('edit'), description = ref(''), strength = ref(.5), endId = ref(''), scenes = ref([]), history = ref([]), hasMore = ref(false), current = ref(null), baseVersion = ref(null), preview = ref(null), previewArgs = ref(null), pending = ref(null), receipt = ref(null)
let epoch = 0
const removed = computed(() => current.value?.status === 'deprecated')
function scope() { return { accountId: getLocalDraftAccountScope(), projectId: props.projectId, objectId: props.relation.id || props.relation.relationship_id, section: 'relation-maintenance' } }
function persist() {
  const saved = writeLocalDraftBackup(getLocalDraftStorage(), scope(), baseVersion.value, { action: action.value, description: description.value, strength: strength.value, endId: endId.value, pending: pending.value })
  backupError.value = saved.ok ? '' : '关系修改要求未能备份；当前输入仍保留，请核对结果后再离开。'
}
const actionLabel = value => ({ edit: '修改关系', end: '结束有效期', remove: '移除关系', restore: '恢复快照' })[value] || '关系操作'
const statusLabel = value => ({ canonical: '已采用', candidate: '待处理', deprecated: '已移除' })[value] || '状态待核对'
function validityLabel(value) {
  if (!value) return '未限制作者有效期'
  const name = anchor => !anchor ? null : scenes.value.find(scene => scene.id === anchor.id)?.title || (anchor.kind === 'chapter' ? '原章节锚点（待核对）' : '原场景锚点（待核对）')
  return `从${name(value.start) || '全书开始'}到${name(value.end) || '持续至今'}`
}
async function load(more = false) {
  if (busy.value) return
  const token = epoch, id = scope().objectId
  busy.value = true; error.value = ''
  try {
    const result = await getApi().world.relationChangeHistory(id, props.projectId, more ? history.value.length : 0)
    if (token !== epoch) return
    current.value = result.current; baseVersion.value = result.current_version
    history.value = more ? [...history.value, ...result.items] : result.items; hasMore.value = result.has_more
    if (!more) {
      ready.value = false
      const saved = readLocalDraftBackup(getLocalDraftStorage(), scope())
      action.value = saved.draft?.payload?.action || 'edit'; description.value = saved.draft?.payload?.description ?? result.current.description ?? ''; strength.value = saved.draft?.payload?.strength ?? result.current.strength; endId.value = saved.draft?.payload?.endId || ''; pending.value = saved.draft?.payload?.pending || null
      if (saved.draft?.base_version && saved.draft.base_version !== result.current_version) error.value = '关系已有新改动，本机输入仍保留；请对照当前关系重新准备预览。'
      if (!saved.ok) backupError.value = '本机修改要求暂时无法读取，请核对当前输入。'
      ready.value = true
      try { const value = await getApi().outline.listScenesOrdered(props.projectId); if (token === epoch) scenes.value = Array.isArray(value) ? value : value.items || [] }
      catch { if (token === epoch) error.value ||= '场景列表暂时无法读取；结束有效期前请重试，原修改要求仍保留。' }
    }
  } catch (cause) { if (token === epoch) error.value = cause.message || '关系记录暂时无法读取。' }
  finally { if (token === epoch) busy.value = false }
}
async function prepare(item = null) {
  if (busy.value || pending.value) return
  const token = epoch, id = scope().objectId
  const args = item?.id ? { relation_id: id, action: 'restore', history_id: item.id } : { relation_id: id, action: action.value, ...(action.value === 'edit' ? { changes: { description: description.value, strength: strength.value } } : action.value === 'end' ? { end: { kind: 'scene', id: endId.value } } : {}) }
  busy.value = true; error.value = ''; preview.value = null
  try { const value = await getApi().world.previewRelationChange(id, props.projectId, args); if (token === epoch) { previewArgs.value = args; preview.value = value } }
  catch (cause) { if (token === epoch) error.value = cause.message || '预览失败，关系没有改动。' }
  finally { if (token === epoch) busy.value = false }
}
async function confirm() {
  if (busy.value || (!pending.value && !preview.value)) return
  const token = epoch, id = scope().objectId
  pending.value ||= { ...previewArgs.value, operation_id: createOperationId(), expected_preview_hash: preview.value.preview_hash, confirmed: true }
  persist(); busy.value = true; error.value = ''
  const operationId = pending.value.operation_id
  try {
    const value = await getApi().world.confirmRelationChange(id, props.projectId, pending.value)
    if (token !== epoch) return
    receipt.value = value; pending.value = null; preview.value = null; previewArgs.value = null
    ready.value = false
    const saved = readLocalDraftBackup(getLocalDraftStorage(), scope()).draft
    if (saved?.payload?.pending?.operation_id === operationId) clearLocalDraftBackup(getLocalDraftStorage(), saved)
    emit('changed', value)
  } catch (cause) {
    if (token === epoch) { error.value = cause.message || '执行结果未知，请核对原请求，不要重新提交。'; if ([400, 403, 404, 409, 422].includes(Number(cause.status))) { pending.value = null; preview.value = null; persist() } }
  } finally { if (token === epoch) { busy.value = false; if (receipt.value && !ready.value) void load() } }
}
watch([action, description, strength, endId], () => { if (ready.value && !pending.value) { preview.value = null; persist() } }, { flush: 'sync' })
watch([() => props.projectId, () => props.relation.id || props.relation.relationship_id, () => getLocalDraftAccountScope()], () => {
  epoch++; ready.value = false; busy.value = false; error.value = ''; backupError.value = ''; history.value = []; hasMore.value = false; current.value = null; preview.value = null; previewArgs.value = null; receipt.value = null
  pending.value = readLocalDraftBackup(getLocalDraftStorage(), scope()).draft?.payload?.pending || null
}, { immediate: true })
onBeforeUnmount(() => { epoch++ })
</script>

<style scoped>
.relation-maintenance { border: 1px solid var(--border-color, var(--border)); border-radius: .5rem; padding: .6rem; margin-block: .6rem; overflow-wrap: anywhere; }
.relation-maintenance summary { cursor: pointer; min-height: 44px; align-content: center; }
.relation-maintenance label { display: grid; gap: .4rem; margin-block: .6rem; }
.relation-maintenance fieldset { border: 0; padding: 0; min-width: 0; }
.relation-maintenance input, .relation-maintenance select, .relation-maintenance textarea, .relation-maintenance button { min-height: 44px; max-width: 100%; }
.relation-maintenance textarea { min-height: 6rem; }
.relation-maintenance__comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .6rem; }
@media (max-width: 640px) { .relation-maintenance__comparison { grid-template-columns: 1fr; } }
</style>
