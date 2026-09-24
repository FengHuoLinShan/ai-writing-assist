<template>
  <details v-if="enabled" class="rp-forecast" @toggle="opened = $event.target.open">
    <summary>下一步灵感 <span v-if="running">· 正在准备</span></summary>
    <p>只参考你已选择的发展，方向由你决定。</p>
    <button type="button" :disabled="busy || locked || composing || running" @click="evaluate">想几个下一步</button>
    <button v-if="running" type="button" :disabled="busy" @click="cancel">停止分析</button>
    <div v-if="run?.status === 'pending' && run?.local_agent && !run.local_agent.approved" role="status">
      <p>本轮 {{ run.local_agent.kind }} CLI 在你的 Mac 上直接运行，可访问当前用户允许的文件和命令；工作目录不是沙箱。用量和费用可能无法准确估算。</p>
      <button type="button" :disabled="busy" @click="approveLocalForecast">确认本轮在本机执行</button>
    </div>
    <button v-if="pending && !running" type="button" :disabled="busy || locked" @click="recover">找回上次请求</button>
    <button v-if="run?.can_resume" type="button" :disabled="busy || locked || composing" @click="resume">从原进度继续分析</button>
    <p v-if="locked">请先处理当前回应，再准备新的灵感。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="backupFailed" role="alert">请求记录尚未备份，请留在此页直到结果确认。</p>
    <p v-if="run && ['failed', 'cancelled', 'budget_exceeded'].includes(run.status)">本次分析未完成，旅程内容已保留。</p>
    <article v-for="item in feed?.items || []" :key="item.issue_key">
      <h4>{{ item.title }}</h4><p v-for="(statement, index) in item.statements" :key="index">{{ statement.text }}</p>
      <div v-for="direction in item.directions" :key="direction.direction_id"><strong>{{ direction.title }}</strong><p>{{ direction.condition }}：{{ direction.proposal }}</p><button type="button" :disabled="busy || locked || composing" @click="prefill(item, direction)">带入输入框</button></div>
      <details><summary>依据与未定之处</summary><p v-for="reference in item.evidence" :key="reference.evidence_id">{{ reference.label }}</p><p v-for="unknown in item.unknowns" :key="unknown">{{ unknown }}</p></details>
      <button type="button" :disabled="busy" @click="dismiss(item)">这次先不展开</button>
    </article>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getConfirm } from "../../bridge/index.js"
import { ACCOUNT_INVALIDATED_EVENT, ACCOUNT_MARKER_KEY } from "../../../shared/accountStorage.js"
const props = defineProps({ journey: { type: Object, default: null }, locked: Boolean, composing: Boolean })
const emit = defineEmits(["prefill"])
const enabled = ref(false), opened = ref(false), feed = ref(null), run = ref(null), pending = ref(null)
const busy = ref(false), error = ref(""), backupFailed = ref(false)
const running = computed(() => ["pending", "running"].includes(run.value?.status))
const api = () => getApi()?.interactionForecasts
let generation = 0, sequence = 0, disposed = false
const clientId = crypto.randomUUID()
const current = token => !disposed && token === generation
const storageKey = () => `novel_rp_forecast:${localStorage.getItem(ACCOUNT_MARKER_KEY) || "local"}:${props.journey?.id}`
function save() { try { localStorage.setItem(storageKey(), JSON.stringify({ pending: pending.value, run: run.value?.run_id })); backupFailed.value = false } catch { backupFailed.value = true } }
function focus() { return { client_context_id: clientId, focus_seq: sequence, selected_leaf_node_id: props.journey.selected_leaf_node_id, selection_epoch: props.journey.selection_epoch, source_context_epoch: props.journey.source?.source_context_epoch ?? 0, overview_epoch: props.journey.overview_epoch ?? 0 } }
async function refresh(token = generation) {
  if (!enabled.value || props.locked || props.composing || !api()) return
  try {
    if (run.value && running.value) { const value = await api().run(props.journey.id, run.value.run_id); if (!current(token)) return; run.value = value }
    const value = await api().feed(props.journey.id, { context: focus() })
    if (current(token) && value.focus_seq === sequence) feed.value = value
  } catch (err) { if (current(token)) { feed.value = null; error.value = err.message || "建议暂时无法载入，旅程仍可继续。" } }
}
watch(() => [props.journey?.id, props.journey?.selected_leaf_node_id, props.journey?.selection_epoch, props.journey?.source?.source_context_epoch, props.journey?.overview_epoch], async () => {
  const token = ++generation; sequence++; enabled.value = false; feed.value = null; run.value = null; error.value = ""; busy.value = false
  if (!props.journey || !api()) return
  try {
    const value = await api().capabilities(props.journey.id)
    if (!current(token)) return
    enabled.value = value.enabled
    const saved = JSON.parse(localStorage.getItem(storageKey()) || "{}")
    pending.value = saved.pending || null
    if (saved.run) { const restored = await api().run(props.journey.id, saved.run); if (current(token)) run.value = restored }
    if (current(token) && opened.value) await refresh(token)
  } catch (err) { if (current(token)) error.value = err.message }
}, { immediate: true })
watch(opened, value => { if (value) void refresh() })
watch(() => props.locked, value => { if (!value && opened.value) void refresh() })
async function evaluate() {
  if (busy.value || props.locked || props.composing || running.value) return
  if (!pending.value) pending.value = { operation_id: crypto.randomUUID(), context: focus() }
  save(); const token = generation; busy.value = true; error.value = ""
  try {
    const value = await api().evaluate(props.journey.id, pending.value)
    if (!current(token)) return
    run.value = { run_id: value.run_id, status: value.status }
    pending.value = null; save(); await refresh(token)
  } catch (err) { if (current(token)) error.value = err.message || "提交结果尚未确认，可找回原请求。" }
  finally { if (current(token)) busy.value = false }
}
async function recover() {
  if (!pending.value || busy.value) return
  const token = generation; busy.value = true
  try { const value = await api().operation(props.journey.id, pending.value.operation_id); if (current(token)) { run.value = value; pending.value = null; save(); await refresh(token) } }
  catch (err) { if (current(token)) error.value = err.status === 404 ? "尚未找到运行记录。点击想几个下一步会使用原请求重试。" : err.message }
  finally { if (current(token)) busy.value = false }
}
async function resume() { const token = generation; busy.value = true; try { const value = await api().resume(props.journey.id, run.value.run_id); if (current(token)) { run.value = value; save(); await refresh(token) } } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function cancel() { const token = generation; busy.value = true; try { const value = await api().cancel(props.journey.id, run.value.run_id); if (current(token)) run.value = value } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function approveLocalForecast() {
  if (!run.value?.task_id || !getConfirm()("确认本轮 CLI 可使用当前 Mac 用户的文件与命令权限？")) return
  const token = generation
  busy.value = true
  try {
    await getApi().localAgent.approve(props.journey.novel_id, run.value.task_id)
    const updated = await api().run(props.journey.id, run.value.run_id)
    if (current(token)) run.value = updated
  } catch (err) { if (current(token)) error.value = err.message || "本轮授权未完成。" }
  finally { if (current(token)) busy.value = false }
}
async function prefill(item, direction) { const token = generation; busy.value = true; try { const value = await api().prefill(props.journey.id, item.candidate_id, { direction_id: direction.direction_id, expected_assessment_hash: item.assessment_hash }); if (current(token) && !props.locked && !props.composing) emit("prefill", value) } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
async function dismiss(item) { const token = generation; busy.value = true; try { await api().decide(props.journey.id, item.candidate_id, { action: "as_ordinary_detail", expected_notice_version: item.notice_version, expected_assessment_hash: item.assessment_hash }); if (current(token)) await refresh(token) } catch (err) { if (current(token)) error.value = err.message } finally { if (current(token)) busy.value = false } }
const timer = setInterval(() => { if (opened.value && running.value && !busy.value) void refresh() }, 15000)
function invalidated() { generation++; enabled.value = false; feed.value = run.value = pending.value = null }
globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidated)
onBeforeUnmount(() => { disposed = true; generation++; clearInterval(timer); globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, invalidated) })
</script>

<style scoped>
.rp-forecast { width: min(100%, 48rem); box-sizing: border-box; margin: .5rem auto; padding: .8rem 1rem; border: 1px solid var(--border-color, var(--border)); border-radius: .6rem; font-size: .8rem; line-height: 1.65; }
.rp-forecast summary { cursor: pointer; min-height: 2rem; }
.rp-forecast h4 { margin: .6rem 0; }
.rp-forecast article { border-top: 1px solid var(--border-color, var(--border)); margin-top: 1rem; }
.rp-forecast button { margin: .2rem .5rem .2rem 0; min-height: 2rem; }
.rp-forecast [role=alert] { color: var(--danger); }
</style>
