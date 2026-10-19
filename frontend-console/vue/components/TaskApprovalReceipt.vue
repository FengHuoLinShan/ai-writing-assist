<template>
  <section class="approval-receipt" aria-label="本任务自动修改授权">
    <p v-if="error" role="alert">{{ error }} <button type="button" :disabled="busy || loading" @click="load">重新读取</button></p>
    <template v-if="receipt?.status">
      <p role="status">{{ ({ active: '本任务自动修改已开启', revoked: '自动修改已撤回，已完成项仍保留', finished: '本任务授权已结束，回执已保留', expired: '本任务自动修改授权已到期' })[receipt.status] || '请核对本任务授权状态' }}</p>
      <p>{{ receipt.task?.intent }}</p>
      <p v-if="receipt.task?.preserve?.length">必须保留：{{ receipt.task.preserve.join('；') }}</p>
      <button v-if="receipt.status === 'active'" type="button" :disabled="busy" @click="revoke">{{ busy ? '正在撤回…' : '撤回自动修改' }}</button>
      <ul v-if="receipt.decisions?.length">
        <li v-for="item in receipt.decisions" :key="item.id"><strong>{{ decisionLabel(item) }}</strong>：{{ item.reason }}<span v-if="item.execution">；{{ item.execution.status === 'completed' ? '已执行，回执已保留' : '请核对实际执行回执' }}</span></li>
      </ul>
    </template>
    <p v-else-if="!error" role="status">{{ loading ? '正在核对本任务的自动修改授权…' : '尚未读到本任务授权，请核对提交结果。' }} <button v-if="!loading" type="button" @click="load">重新读取</button></p>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getApi } from '../bridge/index.js'
const props = defineProps({ projectId: { type: String, required: true }, runId: { type: String, required: true }, revision: { type: [String, Number], default: null }, live: Boolean })
const receipt = ref(null), error = ref(''), busy = ref(false), loading = ref(false)
let generation = 0, timer = null, reloadNeeded = false
function decisionLabel(item) { return ({ allow: '允许执行', ask: '需要作者决定', deny: '拒绝执行', pending: '判断结果待核对' })[item.decision] || '待核对' }
async function load() {
  if (loading.value) { reloadNeeded = true; return }
  if (!props.projectId || !props.runId) return
  const token = generation, projectId = props.projectId, runId = props.runId
  loading.value = true
  try { const value = await getApi().assistant.taskApproval(projectId, runId); if (token === generation) { receipt.value = value; error.value = '' } }
  catch (cause) { if (token === generation) error.value = cause.message || '授权暂时无法读取，请重试。' }
  finally { if (token === generation) { loading.value = false; if (reloadNeeded) { reloadNeeded = false; void load() } } }
}
async function revoke() {
  const token = generation, version = receipt.value?.version
  if (!version || busy.value) return
  busy.value = true
  try { const value = await getApi().assistant.revokeTaskApproval(props.projectId, props.runId, version); if (token === generation) { receipt.value = value; error.value = '' } }
  catch (cause) { if (token === generation) { error.value = cause.message || '尚未确认撤回成功，请重新核对。'; if (Number(cause.status) === 409) await load() } }
  finally { if (token === generation) busy.value = false }
}
watch(() => [props.projectId, props.runId], () => { generation++; reloadNeeded = false; receipt.value = null; error.value = ''; busy.value = false; loading.value = false; void load() }, { immediate: true })
watch(() => props.revision, () => { void load() })
onMounted(() => { timer = setInterval(() => { if (props.live && !busy.value) void load() }, 2500) })
onBeforeUnmount(() => { generation++; clearInterval(timer) })
</script>

<style scoped>
.approval-receipt { border: 1px solid var(--border-color, var(--border)); border-radius: .6rem; padding: .8rem; overflow-wrap: anywhere; }
.approval-receipt p { margin: .3rem 0; line-height: 1.5; }
.approval-receipt ul { margin: .5rem 0; padding-inline-start: 1.25rem; }
.approval-receipt button { min-height: 44px; padding: .45rem .7rem; color: var(--text-primary); background: var(--bg-secondary); border: 1px solid var(--border-color, var(--border)); border-radius: .4rem; }
</style>
