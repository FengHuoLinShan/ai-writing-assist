<template>
  <details ref="detailsEl" class="revision-groups" @toggle="opened">
    <summary>选择修改组</summary>
    <p>相互依赖的修改一起选择。组成新候选后将重新检查整章，通过后再采用。</p>
    <p v-if="loading" role="status">正在读取修改差异…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error && !pendingRequest && !task" type="button" class="btn btn-sm" :disabled="loading" @click="load">重新读取差异</button>
    <fieldset v-if="preview" :disabled="busy || loading || Boolean(pendingRequest) || Boolean(task) && !(reselecting && canReselect)">
      <legend>本次保留哪些修改</legend>
      <article v-for="(group, index) in preview.groups" :key="group.id">
        <label><input v-model="selected" type="checkbox" :value="group.id" @change="changed">第 {{ index + 1 }} 组<small v-if="group.whole_only">（无法可靠拆分，仅支持整组）</small></label>
        <div v-for="(change, changeIndex) in group.changes" :key="changeIndex" class="revision-groups__diff">
          <div><strong>原文</strong><pre>{{ change.before }}</pre></div>
          <div><strong>修改后</strong><pre>{{ change.after }}</pre></div>
        </div>
      </article>
    </fieldset>
    <button v-if="(preview || pendingRequest) && (!task || reselecting && canReselect)" type="button" class="btn btn-sm" :disabled="busy || loading || (!pendingRequest && !selected.length)" @click="submit">{{ busy ? '正在提交…' : pendingRequest ? '核对上次提交（不重复开任务）' : '组成新候选并重新审查' }}</button>
    <p v-if="task" role="status">{{ taskStatus }}</p>
    <button v-if="task?.result?.candidate_draft_id" type="button" class="btn btn-sm" @click="$emit('open-candidate', task.result.candidate_draft_id)">打开新候选比较与采用</button>
    <button v-if="task?.task_id" type="button" class="btn btn-sm" :disabled="busy" @click="poll(task.task_id)">核对任务结果</button>
    <button v-if="canReselect && !reselecting" type="button" class="btn btn-sm" :disabled="busy || loading || Boolean(pendingRequest)" @click="load({ reselect: true })">重新选择修改组</button>
    <p v-if="backupError" role="alert">{{ backupError }}</p>
  </details>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getLocalDraftAccountScope, getLocalDraftStorage } from '../../../bridge/index.js'
import { readLocalDraftBackup, writeLocalDraftBackup } from '../../../shared/localDraftBackup.js'
import { createOperationId } from '../../../../shared/workflowProgress.js'
const props = defineProps({ projectId: { type: String, required: true }, draftId: { type: String, required: true } })
const emit = defineEmits(['open-candidate', 'selection-change'])
const preview = ref(null), selected = ref([]), loading = ref(false), busy = ref(false), error = ref(''), backupError = ref(''), pendingRequest = ref(null), task = ref(null)
const reselecting = ref(false), taskVerified = ref(false)
const canReselect = computed(() => taskVerified.value && ['done', 'failed', 'cancelled'].includes(task.value?.status) && !task.value?.operation?.possible_charge && !task.value?.lifecycle?.recovery_required)
const detailsEl = ref(null)
let epoch = 0, timer = null
const taskStatus = computed(() => {
  if (['pending', 'running'].includes(task.value?.status)) return '正在组成候选并重新审查，工作稿未改动。'
  if (task.value?.result?.degraded) return '新候选已保留，独立审查未完成，暂不可采用。'
  if (task.value?.result?.candidate_draft_id) return '新候选已保留；打开后核对实际审查结论。'
  return task.value?.error_message || task.value?.error || '尚未取得可用候选，请核对任务回执。'
})
function scope() { return { accountId: getLocalDraftAccountScope(), projectId: props.projectId, objectId: props.draftId, section: 'revision-groups' } }
function persist() {
  const result = writeLocalDraftBackup(getLocalDraftStorage(), scope(), preview.value?.preview_hash || null, { selected: selected.value, pendingRequest: pendingRequest.value, task: task.value?.task_id ? { task_id: task.value.task_id, status: task.value.status } : null, reselecting: reselecting.value })
  backupError.value = result.ok ? '' : '修改组选择未能备份；当前页面仍保留，请先核对任务结果再离开。'
}
function changed() { emit('selection-change', Boolean(task.value || pendingRequest.value || selected.value.length !== preview.value?.groups.length)); persist() }
async function opened(event) { if (event.target.open && !preview.value && !loading.value) await load() }
async function load({ reselect = false } = {}) {
  if (reselect && (!canReselect.value || busy.value || pendingRequest.value)) return
  const token = ++epoch
  clearTimeout(timer)
  loading.value = true; error.value = ''
  try {
    const value = await getApi().writing.revisionGroups(props.draftId, props.projectId)
    if (token !== epoch) return
    preview.value = value
    if (reselect) {
      selected.value = value.groups.map(group => group.id)
      reselecting.value = true
      emit('selection-change', true)
      persist()
      return
    }
    const saved = readLocalDraftBackup(getLocalDraftStorage(), scope())
    if (!saved.ok) backupError.value = '本机修改组记录无法读取；请核对当前选择。'
    selected.value = saved.draft?.base_version === value.preview_hash && Array.isArray(saved.draft.payload.selected) ? saved.draft.payload.selected.filter(id => value.groups.some(group => group.id === id)) : value.groups.map(group => group.id)
    if (saved.draft?.base_version && saved.draft.base_version !== value.preview_hash) error.value = '来源已变化，旧选择已保留在本机；请按新差异重新选择。'
    pendingRequest.value ||= saved.draft?.payload?.pendingRequest || null
    task.value ||= saved.draft?.payload?.task || null
    reselecting.value = saved.draft?.payload?.reselecting === true
    emit('selection-change', Boolean(pendingRequest.value || task.value || selected.value.length !== value.groups.length))
    if (task.value?.task_id) void poll(task.value.task_id)
  } catch (cause) { if (token === epoch) error.value = cause.message || '差异暂时无法读取，原建议仍保留。' }
  finally { if (token === epoch) loading.value = false }
}
async function submit() {
  if (busy.value || loading.value || (task.value && !(reselecting.value && canReselect.value)) || (!pendingRequest.value && (!preview.value || !selected.value.length))) return
  const token = ++epoch, projectId = props.projectId, draftId = props.draftId
  clearTimeout(timer)
  pendingRequest.value ||= { novel_id: projectId, operation_id: createOperationId(), expected_preview_hash: preview.value.preview_hash, group_ids: [...selected.value] }
  persist(); emit('selection-change', true); busy.value = true; error.value = ''
  try {
    const value = await getApi().writing.selectRevisionGroups(draftId, pendingRequest.value)
    if (token !== epoch) return
    task.value = { task_id: value.task_id, status: value.status }
    taskVerified.value = false; reselecting.value = false
    pendingRequest.value = null; persist(); void poll(value.task_id)
  } catch (cause) {
    if (token === epoch) {
      error.value = cause.message || '提交结果未知，选择和提交标识已保留，请核对原请求。'
      if ([400, 403, 404, 409, 422].includes(Number(cause.status))) { pendingRequest.value = null; persist() }
    }
  }
  finally { if (token === epoch) busy.value = false }
}
async function poll(taskId) {
  clearTimeout(timer)
  const token = epoch
  taskVerified.value = false
  try {
    const value = await getApi().tasks.get(taskId, props.projectId)
    if (token !== epoch) return
    task.value = { ...value, task_id: taskId }; taskVerified.value = true; persist()
    if (['pending', 'running'].includes(value.status)) timer = setTimeout(() => poll(taskId), 2000)
  } catch (cause) { if (token === epoch) error.value = cause.message || '任务结果未能读取，请核对后再处理。' }
}
watch([() => props.projectId, () => props.draftId, () => getLocalDraftAccountScope()], () => {
  epoch++; clearTimeout(timer); preview.value = null; selected.value = []; loading.value = false; busy.value = false; error.value = ''; backupError.value = ''; task.value = null; pendingRequest.value = null; reselecting.value = false; taskVerified.value = false; emit('selection-change', false)
  const saved = readLocalDraftBackup(getLocalDraftStorage(), scope())
  pendingRequest.value = saved.draft?.payload?.pendingRequest || null
  task.value = saved.draft?.payload?.task || null
  reselecting.value = saved.draft?.payload?.reselecting === true
  if (pendingRequest.value || task.value) emit('selection-change', true)
  if (task.value?.task_id) void poll(task.value.task_id)
  const token = epoch
  void nextTick(() => { if (token === epoch && detailsEl.value?.open && !preview.value && !loading.value) void load() })
}, { immediate: true })
onBeforeUnmount(() => { epoch++; clearTimeout(timer) })
</script>

<style scoped>
.revision-groups { border: 1px solid var(--border-color, var(--border)); border-radius: .5rem; padding: .6rem; }
.revision-groups summary { cursor: pointer; min-height: 44px; align-content: center; }
.revision-groups fieldset { padding: 0; border: 0; min-width: 0; }
.revision-groups article { margin-block: .8rem; }
.revision-groups label { display: flex; align-items: center; gap: .5rem; min-height: 44px; flex-wrap: wrap; }
.revision-groups pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; margin: .4rem 0; max-height: 16rem; overflow: auto; }
.revision-groups__diff { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .7rem; padding: .5rem; background: var(--bg-secondary); }
.revision-groups .btn { min-height: 44px; margin: .3rem .3rem .3rem 0; }
@media (max-width: 640px) { .revision-groups__diff { grid-template-columns: 1fr; } }
</style>
