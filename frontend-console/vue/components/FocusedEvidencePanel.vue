<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getAppState } from "../bridge/index.js"
import { useWorkflowPolling } from "../composables/useWorkflowPolling.js"
import { clearActiveWorkflow, persistActiveWorkflow, recoverActiveWorkflows } from "../../shared/workflowProgress.js"
import { ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"

const props = defineProps({
  projectId: { type: String, required: true },
  consumer: { type: String, default: "author" },
  scopeKey: { type: String, default: "" },
  sceneId: { type: String, default: null },
  chapterIndex: { type: Number, default: null },
  contentMode: { type: String, default: "canonical" },
  roots: { type: Array, default: () => [] },
  initialName: { type: String, default: "" },
  question: { type: String, default: "查找这一对象的资料与直接关联的原文依据" },
  selectedRefs: { type: Array, default: () => [] },
  excludedRefs: { type: Array, default: () => [] },
  selectLabel: { type: String, default: "加入本次参考资料" },
})
const emit = defineEmits(["select-source", "clear-selection"])
const api = getApi()
const polling = useWorkflowPolling()
const name = ref(props.initialName), questionText = ref(props.question)
const taskId = ref(null), status = ref(""), result = ref(null), error = ref("")
const submitting = ref(false), canResume = ref(false), expanded = ref(false)
const storageWarning = ref("")
const nameInput = ref(null)
let generation = 0, alive = true
const busy = computed(() => submitting.value || ["pending", "running"].includes(status.value))
const contextKey = computed(() => JSON.stringify([props.projectId, props.consumer, props.scopeKey, props.sceneId, props.chapterIndex, props.contentMode, props.roots, props.initialName, props.question, props.excludedRefs]))
const coverage = computed(() => result.value?.coverage)
const evidence = computed(() => result.value?.evidence || [])
const scopeLabel = computed(() => props.consumer === "writing"
  ? `查读截至本场的可见资料${props.chapterIndex ? ` · 第 ${props.chapterIndex} 章` : ""}`
  : props.contentMode === "working" ? "查读当前工作稿及对象资料" : "查读正式正文及已采用资料")
const statusLabel = computed(() => ({ pending: "正在等待查证", running: "正在查找原文与核对直接关联", completed: "本轮查证结束", recoverable: "本轮尚未查完，可以继续", failed: "查证未完成", cancelled: "查证已停止" }[status.value] || ""))
const activeProject = () => !getAppState()?.currentProjectId || getAppState().currentProjectId === props.projectId
const owns = (token, key) => alive && token === generation && key === contextKey.value && activeProject()

function accountMarker() { try { return localStorage.getItem(ACCOUNT_MARKER_KEY) } catch { return null } }
function receiptScope() { return { account: accountMarker(), projectId: props.projectId, view: props.consumer, meta: { contextKey: contextKey.value, name: name.value, question: questionText.value } } }
function remember(id, scope) {
  if (scope.account !== accountMarker()) return
  try { persistActiveWorkflow({ taskId: id, workflowType: "evidence_focused_search", label: "专项查证", projectId: scope.projectId, view: scope.view, meta: scope.meta }) }
  catch { storageWarning.value = "任务已在服务端保留，但本机无法保存恢复入口；请保留当前页面，待查证结束后再离开。" }
}
function forget(id) { try { clearActiveWorkflow(id) } catch {} }
function observe(id, token = generation, key = contextKey.value) {
  polling.stopAll()
  polling.start({
    taskId: id, novelId: props.projectId, workflowType: "evidence_focused_search",
    apiClient: { tasks: { get: async (requestedId, novelId) => {
      let value
      try { value = await api.context.getFocusedSearch(requestedId, novelId) }
      catch (err) {
        if (![400, 409, 422].includes(Number(err.status))) throw err
        value = { status: "failed", can_resume: false, result: null, error: "原文或知识资料已变化，原查证无法继续，请重新查证。" }
      }
      return { id: requestedId, task_type: "evidence_focused_search", status: value.status === "completed" || value.can_resume ? "done" : value.status, result: value.result, error_message: value.error, focused: value }
    } } },
    onUpdate: (_progress, task) => {
      if (!owns(token, key)) return
      if (!task) { error.value = "暂时无法读取进度，正在重试；已提交任务仍保留。"; return }
      const value = task.focused
      status.value = value.status
      canResume.value = value.can_resume
      if (value.result || value.status === "failed") result.value = value.result
      error.value = value.error || ""
    },
    onFailed: (progress, task) => {
      if (!owns(token, key)) return
      status.value = task?.focused?.status || "failed"
      error.value = task?.focused?.error || progress.errorMessage || "查证未完成，可稍后重试。"
    },
  })
}
async function start() {
  if (busy.value) return
  const typedName = name.value.trim()
  const useRoots = props.roots.length && typedName === props.initialName.trim()
  const roots = useRoots ? props.roots : typedName ? [{ name: typedName }] : props.roots
  if (!roots.length) { error.value = "请输入要查证的人物、地点或设定名称。"; return }
  const token = ++generation, key = contextKey.value
  const receipt = receiptScope()
  submitting.value = true; error.value = ""; expanded.value = true
  try {
    const submitted = await api.context.startFocusedSearch({
      novel_id: props.projectId, roots, question: questionText.value.trim(), consumer: props.consumer,
      content_mode: props.contentMode, max_depth: 1,
      ...(props.sceneId ? { scene_id: props.sceneId } : {}),
      ...(props.chapterIndex ? { chapter_index: props.chapterIndex } : {}),
      pinned_refs: props.selectedRefs, excluded_refs: props.excludedRefs,
    })
    if (!submitted?.task_id) throw new Error("未能启动查证，请重试。")
    remember(submitted.task_id, receipt)
    if (!owns(token, key)) return
    if (taskId.value && taskId.value !== submitted.task_id) forget(taskId.value)
    taskId.value = submitted.task_id; status.value = submitted.status
    result.value = null; canResume.value = false
    observe(submitted.task_id, token, key)
  } catch (err) { if (owns(token, key)) error.value = err.message || "查证未能开始，输入已保留。" }
  finally { if (owns(token, key)) submitting.value = false }
}
async function resume() {
  if (!taskId.value || busy.value) return
  const token = ++generation, key = contextKey.value, previous = taskId.value
  const receipt = receiptScope()
  submitting.value = true; error.value = ""
  try {
    const value = await api.context.resumeFocusedSearch(previous, props.projectId)
    if (!value?.task_id) throw new Error("暂时无法继续原查证。")
    remember(value.task_id, receipt)
    if (!owns(token, key)) return
    if (previous !== value.task_id) forget(previous)
    taskId.value = value.task_id; status.value = value.status; canResume.value = false
    observe(value.task_id, token, key)
  } catch (err) { if (owns(token, key)) error.value = err.message || "恢复失败，原进度仍保留。" }
  finally { if (owns(token, key)) submitting.value = false }
}
async function cancel() {
  const token = generation, key = contextKey.value, id = taskId.value
  if (!id) return
  try { await api.tasks.cancel(id, props.projectId); if (owns(token, key)) observe(id, token, key) }
  catch (err) { if (owns(token, key)) error.value = err.message || "停止未成功，任务状态仍保留。" }
}
function isSelected(item) { return props.selectedRefs.some(value => JSON.stringify(value) === JSON.stringify(item.selection_ref)) }
function title(item) {
  if (item.source_ref?.chapter_index) return `第 ${item.source_ref.chapter_index} 章原文`
  return (result.value?.targets || []).find(target => item.target_keys?.includes(target.key))?.name || "对象资料"
}
watch(contextKey, () => {
  generation += 1; polling.stopAll()
  name.value = props.initialName; questionText.value = props.question
  taskId.value = null; status.value = ""; result.value = null; error.value = ""; submitting.value = false; canResume.value = false
  let saved
  try { saved = recoverActiveWorkflows(props.projectId).filter(item => item.workflowType === "evidence_focused_search" && item.meta?.contextKey === contextKey.value).at(-1) }
  catch { storageWarning.value = "本机恢复记录暂时不可用；查证期间请保留当前页面。" }
  if (saved) { taskId.value = saved.taskId; name.value = saved.meta.name || name.value; questionText.value = saved.meta.question || questionText.value; observe(saved.taskId) }
}, { immediate: true, flush: "sync" })
onBeforeUnmount(() => { alive = false; generation += 1 })
defineExpose({ open: async () => { expanded.value = true; await nextTick(); nameInput.value?.focus(); nameInput.value?.scrollIntoView?.({ block: "nearest" }) } })
</script>

<template>
  <details class="focused-evidence" :open="expanded || undefined">
    <summary>查证资料<span v-if="statusLabel"> · {{ statusLabel }}</span></summary>
    <div class="focused-evidence__body">
      <p class="focused-evidence__hint">{{ scopeLabel }}。同时核对直接关联对象，不自动修改设定或正文。</p>
      <form @submit.prevent="start">
        <label>人物、地点或设定名称<input ref="nameInput" v-model="name" class="form-input" maxlength="200" :disabled="busy" placeholder="也可以输入尚未入库的名称" /></label>
        <label>想核对什么<textarea v-model="questionText" class="form-textarea" rows="2" maxlength="1000" :disabled="busy" /></label>
        <button class="btn btn-sm" :disabled="busy">{{ submitting ? '正在提交…' : '开始查证' }}</button>
      </form>
      <p v-if="statusLabel" role="status">{{ statusLabel }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="storageWarning" role="alert">{{ storageWarning }}</p>
      <div class="focused-evidence__actions">
        <button v-if="busy && taskId" type="button" class="btn btn-sm" @click="cancel">停止查证</button>
        <button v-if="canResume && !busy" type="button" class="btn btn-sm" @click="resume">继续未完成的查证</button>
      </div>
      <template v-if="result">
        <p v-if="coverage" class="focused-evidence__hint">已扫描 {{ coverage.scanned_chapters }} / {{ coverage.total_chapters }} 章 · 找到 {{ coverage.matched_occurrences }} 处提及 · 本轮返回 {{ evidence.length }} 段资料。{{ coverage.complete ? '声明范围内的查读已结束，不代表对象没有其他遗漏。' : '还有资料未覆盖，当前为部分结果。' }}</p>
        <p v-for="warning in result.warnings || []" :key="warning" class="focused-evidence__hint">{{ warning }}</p>
        <ul v-if="result.targets?.length" class="focused-evidence__targets">
          <li v-for="target in result.targets" :key="target.key">{{ target.name }} · {{ target.depth ? '直接关联' : '本次目标' }}<span v-if="target.resolution === 'ambiguous'"> · 同名身份待确认</span><span v-else-if="target.resolution === 'unresolved'"> · 尚无明确档案</span></li>
        </ul>
        <p v-if="!evidence.length">本轮没有找到可展示的证据，可以补充别名或更具体的原文线索。</p>
        <article v-for="item in evidence" :key="item.key" class="focused-evidence__item">
          <strong>{{ title(item) }}</strong>
          <p>{{ item.text?.slice(0, 240) }}</p>
          <details v-if="item.text?.length > 240"><summary>展开这段出处</summary><p>{{ item.text }}</p></details>
          <button v-if="item.selection_ref" type="button" class="btn btn-sm" :disabled="isSelected(item)" @click="emit('select-source', item.selection_ref)">{{ isSelected(item) ? '已加入待确认资料' : selectLabel }}</button>
        </article>
      </template>
      <div v-if="selectedRefs.length" class="focused-evidence__selection">
        <p class="focused-evidence__hint">已加入 {{ selectedRefs.length }} 项；生成前仍会预览并确认实际使用的资料。</p>
        <button type="button" class="btn btn-sm" @click="emit('clear-selection')">清空本次资料选择</button>
      </div>
    </div>
  </details>
</template>

<style scoped>
.focused-evidence { border: 1px solid var(--border); border-radius: var(--radius-md); margin: 12px 0; min-width: 0; }
.focused-evidence > summary { padding: 12px; cursor: pointer; font-weight: 600; overflow-wrap: anywhere; }
.focused-evidence > summary > span, .focused-evidence__hint { font-weight: 400; color: var(--text-muted); }
.focused-evidence__body, .focused-evidence form, .focused-evidence label { display: grid; gap: 10px; min-width: 0; }
.focused-evidence__body { padding: 0 12px 12px; }
.focused-evidence input, .focused-evidence textarea { width: 100%; min-width: 0; box-sizing: border-box; }
.focused-evidence p { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.focused-evidence__item { display: grid; gap: 8px; border-top: 1px solid var(--border); padding-top: 12px; }
.focused-evidence__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.focused-evidence__targets { padding-left: 20px; margin: 0; overflow-wrap: anywhere; }
.focused-evidence .btn, .focused-evidence summary, .focused-evidence input { min-height: 44px; }
</style>
