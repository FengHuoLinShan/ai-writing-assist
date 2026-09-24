<template>
  <details class="understanding" @toggle="opened">
    <summary>本书已保留的理解</summary>
    <p>这些是有来源的解释，不会改写设定或正文。修正会保留旧版本，后续任务只读取适用的理解。</p>
    <button class="btn btn-sm" :disabled="busy" type="button" @click="load">刷新</button>
    <p v-if="busy" role="status">正在处理…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="loaded && !items.length">还没有保留的理解。查证时可在授权范围中选择保留有依据的结果。</p>
    <article v-for="item in items" :key="item.id">
      <p>{{ item.text }}</p>
      <small>{{ item.author_status === 'corrected' ? '作者修正 · ' : '' }}{{ freshness(item.freshness) }} · {{ item.source_count }} 份来源</small>
      <div class="understanding-actions">
        <button type="button" class="btn btn-sm" :disabled="busy || !!editing || item.author_status === 'withdrawn'" @click="edit(item)">修正</button>
        <button type="button" class="btn btn-sm" :disabled="busy || !!editing || item.author_status === 'withdrawn'" @click="withdraw(item)">撤回这条理解…</button>
        <button type="button" class="btn btn-sm" :disabled="busy" @click="history(item)">查看历史</button>
      </div>
      <form v-if="editing?.id === item.id" @submit.prevent="save(item)">
        <label>修正后的理解<textarea v-model="draft" rows="3" maxlength="3000" :disabled="busy" @input="pending = null" /></label>
        <button type="submit" class="btn btn-primary" :disabled="busy || !draft.trim()">保存修正</button>
        <button type="button" class="btn" :disabled="busy" @click="editing = null; pending = null">取消</button>
        <button v-if="conflict" type="button" class="btn" :disabled="busy" @click="rebase(item)">读取新版并保留输入</button>
      </form>
      <ul v-if="historyFor === item.id"><li v-for="version in versions" :key="version.revision_id">{{ version.text }}（{{ freshness(version.freshness) }}）</li></ul>
    </article>
  </details>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from "vue"
import { getApi, registerAuxiliaryLeaveGuard } from "../bridge/index.js"
const props = defineProps({ projectId: { type: String, required: true } })
const items = ref([]), head = ref(null), busy = ref(false), loaded = ref(false), error = ref(""), message = ref("")
const conflict = ref(false)
const editing = ref(null), draft = ref(""), pending = ref(null), historyFor = ref(null), versions = ref([])
let generation = 0
const api = () => getApi().collaboration
const freshness = value => ({ current: "来源未变化", stale: "来源已变化，暂停复用", withdrawn: "已撤回", history: "历史版本", needs_scope_check: "需按本次资料范围核对", unsupported: "暂不支持复用" })[value] || "待核对"
function opened(event) { if (event.target.open && !loaded.value) void load() }
async function load() {
  const token = generation
  busy.value = true; error.value = ""
  try { const result = await api().understanding(props.projectId); if (token !== generation) return; items.value = result.items; head.value = result.head_commit_id; loaded.value = true }
  catch (err) { if (token === generation) error.value = err.message || "暂时无法读取理解。" }
  finally { if (token === generation) busy.value = false }
}
function edit(item) { editing.value = { ...item, expectedHead: head.value }; draft.value = item.text; pending.value = null; conflict.value = false; message.value = "" }
async function apply(item, body) {
  if (busy.value) return
  const token = generation
  busy.value = true; error.value = ""; message.value = ""
  try { await api().correctUnderstanding(props.projectId, item.id, body); if (token !== generation) return; editing.value = null; pending.value = null; message.value = body.action === 'withdraw' ? "已撤回，旧记录仍可查看。" : "修正已保存。"; await load() }
  catch (err) { if (token === generation) { error.value = err.message || "结果尚未确认，请保留输入后重试。"; if (err.status === 409) { pending.value = null; conflict.value = true } } }
  finally { if (token === generation) busy.value = false }
}
async function rebase(item) {
  await load()
  const latest = items.value.find(value => value.id === item.id)
  if (!error.value && latest) { editing.value = { ...latest, expectedHead: head.value }; pending.value = null; conflict.value = false; message.value = "已读取新版，输入仍保留；请对照后再保存。" }
}
function save(item) {
  pending.value ||= { operation_id: crypto.randomUUID(), expected_commit_id: editing.value.expectedHead, expected_revision_id: editing.value.revision_id, action: "correct", text: draft.value }
  return apply(item, pending.value)
}
function withdraw(item) {
  if (!globalThis.confirm("撤回后，后续任务不再复用这条理解。旧记录仍可查看。确认撤回吗？")) return
  return apply(item, { operation_id: crypto.randomUUID(), expected_commit_id: head.value, expected_revision_id: item.revision_id, action: "withdraw", confirm_withdrawal: true })
}
async function history(item) {
  const token = generation
  try { const result = await api().understandingHistory(props.projectId, item.id); if (token === generation) { historyFor.value = item.id; versions.value = result.items } }
  catch (err) { if (token === generation) error.value = err.message }
}
function protectInput() { return !editing.value || draft.value === editing.value.text || globalThis.confirm("修正尚未保存，仍要离开吗？") }
defineExpose({ canLeave: protectInput })
const unregister = registerAuxiliaryLeaveGuard(protectInput)
function beforeUnload(event) { if (editing.value && draft.value !== editing.value.text) { event.preventDefault(); event.returnValue = "" } }
globalThis.addEventListener?.("beforeunload", beforeUnload)
watch(() => props.projectId, () => { generation++; items.value = []; head.value = null; editing.value = pending.value = null; historyFor.value = null; versions.value = []; draft.value = error.value = message.value = ""; loaded.value = busy.value = false })
onBeforeUnmount(() => { generation++; unregister(); globalThis.removeEventListener?.("beforeunload", beforeUnload) })
</script>

<style scoped>
.understanding { margin-block: 1rem; }
.understanding summary { cursor: pointer; font-weight: 600; }
.understanding article { padding-block: .8rem; border-bottom: 1px solid var(--border-color, #ddd); }
.understanding p { overflow-wrap: anywhere; }
.understanding-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-block: .5rem; }
.understanding textarea { display: block; width: 100%; box-sizing: border-box; margin-block: .5rem; }
</style>
