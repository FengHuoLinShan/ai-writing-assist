<template>
  <section class="trial-editor" aria-label="继续调整试改">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="backupFailed" role="alert">修改暂未备份，请留在此页或先复制文字。</p>
    <details v-if="retained"><summary>找回上一修订的本地文字</summary><p>这些文字尚未写入服务器，可复制对照或载入后重新检查。</p><article v-for="item in retained.draft" :key="item.resource.kind + item.resource.id"><strong>{{ item.label }}</strong><AssistantValue :value="item.value" /></article><button type="button" class="btn btn-sm" :disabled="locked || busy || pending" @click="restoreRetained">载入保留文字继续调整</button></details>
    <div class="trial-actions">
      <button v-if="trial.status === 'open' && !trial.stale" class="btn btn-sm" type="button" :disabled="locked || busy" @click="editing = !editing">手动调整这一版</button>
      <button v-if="trial.status !== 'merged'" class="btn btn-sm" type="button" :disabled="locked || busy || pending" @click="recover('rebase')">按当前稿重建试改</button>
      <button v-else class="btn btn-sm" type="button" :disabled="locked || busy || pending" @click="recover('revert')">准备撤回这次采用</button>
      <button v-if="pending && !conflicts.length" class="btn btn-sm" type="button" :disabled="locked || busy" @click="execute">恢复原操作</button>
    </div>
    <form v-if="editing" @submit.prevent="save">
      <fieldset v-for="item in draft" :key="item.resource.kind + item.resource.id" :disabled="locked || busy">
        <legend>{{ item.label }}</legend>
        <label v-for="key in textFields(item.value)" :key="key">{{ fieldLabel(key) }}<textarea v-model="item.value[key]" rows="5" @input="backup" /></label>
      </fieldset>
      <button class="btn btn-primary btn-sm" :disabled="locked || busy" type="submit">保存为新的试改修订</button>
    </form>
    <form v-if="conflicts.length" @submit.prevent="resolve">
      <p>当前稿与试改修改了同一处，请逐项选择；保存后仍需重新检查。</p>
      <fieldset v-for="(item, index) in conflicts" :key="item.resource.id" :disabled="locked || busy">
        <legend>{{ item.label }}</legend>
        <div v-for="field in item.fields" :key="field" class="trial-conflict">
          <strong>{{ fieldLabel(field) }}</strong>
          <label><input v-model="choices[index][field]" type="radio" :value="'current'" @change="backup" />保留当前稿</label><AssistantValue :value="item.current?.[field] ?? item.current" />
          <label><input v-model="choices[index][field]" type="radio" :value="'trial'" @change="backup" />采用试改内容</label><AssistantValue :value="item.trial?.[field] ?? item.trial" />
        </div>
      </fieldset>
      <button class="btn btn-primary btn-sm" type="submit" :disabled="locked || busy">保存选择并另建试改</button>
    </form>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from "vue"
import { getApi, registerAuxiliaryLeaveGuard } from "../bridge/index.js"
import { ACCOUNT_INVALIDATED_EVENT, ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"
import AssistantValue from "./AssistantValue.vue"
const props = defineProps({ projectId: { type: String, required: true }, trial: { type: Object, required: true }, locked: Boolean })
const emit = defineEmits(["updated"])
const draft = ref([]), editing = ref(false), pending = ref(null), conflicts = ref([]), choices = ref([])
const retained = ref(null)
const busy = ref(false), error = ref(""), backupFailed = ref(false)
let generation = 0, disposed = false
const api = () => getApi().collaboration
const key = () => `novel_creative_trial:${localStorage.getItem(ACCOUNT_MARKER_KEY) || "local"}:${props.projectId}:${props.trial.id}`
const clone = value => JSON.parse(JSON.stringify(value))
const textFields = value => Object.keys(value || {}).filter(key => typeof value[key] === "string")
const fieldLabel = key => ({ content: "正文", title: "标题", free_text: "设定文字", goal: "场景目标", core_conflict: "核心冲突", emotional_beat: "情绪变化", must_happen: "必须发生", must_not_happen: "必须保留的边界", description: "说明", foreshadowing: "伏笔安排", reveal: "信息揭示", sections_json: "分节内容" })[key] || "这一处内容"
function backup() { try { localStorage.setItem(key(), JSON.stringify({ revision: props.trial.revision_id, draft: draft.value, editing: editing.value, pending: pending.value, conflicts: conflicts.value, choices: choices.value, retained: retained.value })); backupFailed.value = false } catch { backupFailed.value = true } }
watch(() => [props.projectId, props.trial.id, props.trial.revision_id], () => {
  generation++; busy.value = false; error.value = ""; editing.value = false
  draft.value = clone(props.trial.editable_resources || [])
  pending.value = null; conflicts.value = []; choices.value = []; retained.value = null
  try { const saved = JSON.parse(localStorage.getItem(key()) || "null"); if (saved) { retained.value = saved.retained || null; pending.value = saved.pending; conflicts.value = saved.conflicts || []; choices.value = saved.choices || []; if (saved.revision === props.trial.revision_id) { draft.value = saved.draft; editing.value = saved.editing } else if (saved.editing) { retained.value = saved; error.value = "原试改已有新版本，请在保留文字中核对差异。" } } } catch { backupFailed.value = true }
}, { immediate: true })
function restoreRetained() {
  draft.value = draft.value.map(item => {
    const saved = retained.value.draft.find(value => value.resource.kind === item.resource.kind && value.resource.id === item.resource.id)
    return saved ? clone(saved) : item
  })
  editing.value = true; backup()
}
function canLeave() { return !backupFailed.value || !(editing.value || pending.value || retained.value) || globalThis.confirm("试改文字尚未备份。请取消离开并复制文字；仍要离开吗？") }
const unregisterGuard = registerAuxiliaryLeaveGuard(canLeave)
function beforeUnload(event) { if (backupFailed.value && (editing.value || pending.value || retained.value)) { event.preventDefault(); event.returnValue = "" } }
globalThis.addEventListener?.("beforeunload", beforeUnload)
defineExpose({ canLeave })
function recover(kind) { pending.value = { kind, body: { operation_id: crypto.randomUUID(), expected_revision_id: props.trial.revision_id } }; backup(); return execute() }
async function execute() {
  if (props.locked || busy.value || !pending.value) return
  const token = generation, request = clone(pending.value)
  busy.value = true; error.value = ""
  try {
    const result = await api()[request.kind](props.projectId, props.trial.id, request.body)
    if (disposed || token !== generation) return
    if (result.status === "conflict") { conflicts.value = result.conflicts; choices.value = result.conflicts.map(item => Object.fromEntries(item.fields.map(field => [field, "current"]))); pending.value.body.expected_current_hash = result.current_hash; backup() }
    else { pending.value = null; conflicts.value = []; editing.value = false; backup(); emit("updated", result.workspace || result) }
  } catch (err) { if (token === generation) error.value = err.message || "操作结果尚未确认，可以恢复原请求。" }
  finally { if (token === generation) busy.value = false }
}
function save() { if (!draft.value.some(item => JSON.stringify(item.value) !== JSON.stringify(props.trial.editable_resources?.find(source => source.resource.kind === item.resource.kind && source.resource.id === item.resource.id)?.value))) { error.value = "尚未修改任何内容。"; return } pending.value = { kind: "edit", body: { expected_revision_id: props.trial.revision_id, patches: draft.value.filter(item => JSON.stringify(item.value) !== JSON.stringify(props.trial.editable_resources?.find(source => source.resource.kind === item.resource.kind && source.resource.id === item.resource.id)?.value)).map(item => ({ ...item.resource, operation: "replace", value: item.value })) } }; backup(); return execute() }
function resolve() {
  pending.value.body.resolutions = conflicts.value.map((item, index) => {
    if (item.fields.includes("content") && (item.trial === null || item.base === null)) {
      const value = choices.value[index].content === "trial" ? item.trial : item.current
      return { ...item.resource, operation: value === null ? "delete" : "replace", value }
    }
    const value = clone(item.current)
    for (const field of Object.keys(value)) {
      if (item.fields.includes(field)) value[field] = choices.value[index][field] === "trial" ? item.trial[field] : item.current[field]
      else if (JSON.stringify(item.trial[field]) !== JSON.stringify(item.base[field])) value[field] = item.trial[field]
    }
    return { ...item.resource, operation: "replace", value }
  })
  backup(); return execute()
}
function clear() { generation++; draft.value = []; conflicts.value = []; choices.value = []; pending.value = null; editing.value = false }
globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, clear)
onBeforeUnmount(() => { disposed = true; generation++; unregisterGuard(); globalThis.removeEventListener("beforeunload", beforeUnload); globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, clear) })
</script>

<style scoped>
.trial-editor { margin-block: 1rem; font-size: 13px; }
.trial-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.trial-editor fieldset { border: 1px solid var(--border-color, var(--border)); border-radius: .5rem; padding: .8rem; margin-block: .8rem; }
.trial-editor label { display: block; margin-block: .5rem; }
.trial-editor textarea { width: 100%; box-sizing: border-box; resize: vertical; padding: .6rem; font: inherit; color: inherit; background: var(--bg-primary, var(--bg-base)); }
.trial-conflict { border-top: 1px solid var(--border-color, var(--border)); margin-top: .8rem; padding-top: .6rem; }
.trial-editor [role=alert] { color: var(--danger); }
</style>
