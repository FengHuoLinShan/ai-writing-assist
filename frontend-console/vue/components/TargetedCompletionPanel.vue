<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getAppState, getConfirm, getRouter } from "../bridge/index.js"
import { useWorkflowPolling } from "../composables/useWorkflowPolling.js"
import { clearActiveWorkflow, persistActiveWorkflow, recoverActiveWorkflows } from "../../shared/workflowProgress.js"
import { ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"

const props = defineProps({ projectId: { type: String, required: true }, entityId: { type: String, default: null }, initialName: { type: String, default: "" }, sourceTaskId: { type: String, default: null } })
const emit = defineEmits(["applied"])
const api = getApi(), confirm = getConfirm(), polling = useWorkflowPolling()
const name = ref(props.initialName), startChapter = ref(1), endChapter = ref(0)
const taskId = ref(null), task = ref(null), error = ref(""), submitting = ref(false)
const storageWarning = ref("")
const artifact = ref(null), artifactBusy = ref(false)
const identities = ref({}), identityChoices = ref({})
let epoch = 0, alive = true
const key = computed(() => `${props.projectId}:${props.sourceTaskId || props.entityId || 'manual'}`)
const info = computed(() => task.value?.result?.targeted_completion || {})
const busy = computed(() => submitting.value || ["pending", "running"].includes(task.value?.status))
const canResume = computed(() => !info.value.rollback_status && ((task.value?.available_actions || []).includes("resume") || info.value.status === "partial"))
const canRollback = computed(() => taskId.value && !busy.value && info.value.rollback_status !== "rolled_back" && (Number(info.value.created || 0) + Number(info.value.filled || 0) > 0))
const statusLabel = computed(() => info.value.rollback_status === "partial" ? "已撤销可安全恢复的部分；后续修改或引用冲突已保留，可审阅后重试撤销。" : info.value.rollback_status === "rolled_back" ? "本次补全已安全撤销。" : info.value.message || ({ pending: "等待补全", running: "正在查证并补全", done: "本轮处理结束", failed: "补全未完成，已处理结果保留", cancelled: "已停止，已处理结果保留" }[task.value?.status] || ""))
const owns = (token, scope) => alive && token === epoch && scope === key.value && (!getAppState()?.currentProjectId || getAppState().currentProjectId === props.projectId)
function accountMarker() { try { return localStorage.getItem(ACCOUNT_MARKER_KEY) } catch { return null } }
function receiptScope() { return { account: accountMarker(), projectId: props.projectId, meta: { completionKey: key.value, name: name.value, startChapter: startChapter.value, endChapter: endChapter.value } } }
function saveReceipt(id, scope) {
  if (scope.account !== accountMarker()) return
  try { persistActiveWorkflow({ taskId: id, workflowType: "targeted_completion", projectId: scope.projectId, label: "查漏补全", view: "world", meta: scope.meta }) }
  catch { storageWarning.value = "任务已在服务端保留，但本机无法保存恢复入口；请保留当前页面，待处理结束后再离开。" }
}
function forget(id) { try { clearActiveWorkflow(id) } catch {} }
function refreshAssets() { api.clearCache?.(); emit("applied") }
async function showSources(packageId) {
  const token = epoch, scope = key.value
  artifactBusy.value = true; error.value = ""
  try {
    const value = await api.world.getAdoptionArtifact(packageId, props.projectId)
    if (owns(token, scope)) artifact.value = value
  } catch (err) { if (owns(token, scope)) error.value = err.message || "出处暂时无法读取，请重试。" }
  finally { if (owns(token, scope)) artifactBusy.value = false }
}
function reviewPackage(packageId) { getRouter()?.navigate("world", "bible", true, new URLSearchParams({ adoption_package_id: packageId })) }
function proposedFields(item) {
  const value = item.payload?.entity || item.payload?.fields || {}
  return [["概要", value.summary], ["公开资料", value.public_info], ["作者资料", value.hidden_truth]].filter(([, text]) => text)
}
async function loadIdentities(item) {
  const token = epoch, scope = key.value
  const ids = (item.candidate_ids || []).filter(id => !identities.value[id])
  const results = await Promise.all(ids.map(async id => {
    try { const entity = await api.world.getEntity(id, props.projectId); return [id, { name: entity.name, summary: entity.summary || entity.public_info || "暂无说明" }] }
    catch { return [id, { unavailable: true, name: "对象暂不可用", summary: "请从人物与世界核对身份" }] }
  }))
  if (owns(token, scope)) identities.value = { ...identities.value, ...Object.fromEntries(results) }
}
async function completeIdentity(item) {
  const id = identityChoices.value[item.key]
  if (busy.value || !item.candidate_ids.includes(id) || identities.value[id]?.unavailable) return
  const token = ++epoch, scope = key.value
  submitting.value = true; error.value = ""
  try {
    const range = info.value.chapter_range || {}
    const value = await api.imports.targetedCompletion({ novel_id: props.projectId, targets: [{ entity_id: id }], start_chapter: range.start || 1, end_chapter: range.end || 0, authorization_confirmed: true })
    if (!value?.task_id) throw new Error("新补全未能开始，原结果仍保留。")
    saveReceipt(value.task_id, receiptScope())
    if (owns(token, scope)) getRouter()?.navigate("writing", null, true, new URLSearchParams({ novel_id: props.projectId, import_task_id: value.task_id }))
  } catch (err) { if (owns(token, scope)) error.value = err.message || "新补全未能开始。" }
  finally { if (owns(token, scope)) submitting.value = false }
}
function observe(id, token = epoch, scope = key.value) {
  polling.stopAll()
  polling.start({ taskId: id, novelId: props.projectId, workflowType: "targeted_completion",
    onUpdate: (_progress, value) => { if (owns(token, scope) && value) task.value = value },
    onDone: () => { if (owns(token, scope)) refreshAssets() },
    onFailed: (progress, value) => { if (owns(token, scope)) { task.value = value || { status: "failed" }; error.value = progress.errorMessage || "补全未完成，可以稍后继续。"; refreshAssets() } },
  })
}
async function start() {
  if (busy.value) return
  if (!name.value.trim() && !props.entityId) { error.value = "请输入要补全的名称。"; return }
  if (!Number.isInteger(startChapter.value) || startChapter.value < 1 || !Number.isInteger(endChapter.value) || endChapter.value < 0 || (endChapter.value && endChapter.value < startChapter.value)) { error.value = "请填写有效的章节范围。"; return }
  const token = ++epoch, scope = key.value
  const receipt = receiptScope()
  submitting.value = true; error.value = ""
  try {
    const targets = props.entityId && name.value.trim() === props.initialName.trim() ? [{ entity_id: props.entityId }] : [{ name: name.value.trim() }]
    const value = await api.imports.targetedCompletion({ novel_id: props.projectId, targets, start_chapter: startChapter.value, end_chapter: endChapter.value, authorization_confirmed: true })
    if (!value?.task_id) throw new Error("补全未能开始，请重试。")
    saveReceipt(value.task_id, receipt)
    if (!owns(token, scope)) return
    if (taskId.value && taskId.value !== value.task_id) forget(taskId.value)
    taskId.value = value.task_id; task.value = { status: "pending" }
    observe(value.task_id, token, scope)
  } catch (err) { if (owns(token, scope)) error.value = err.message || "补全未能开始，输入已保留。" }
  finally { if (owns(token, scope)) submitting.value = false }
}
async function act(action) {
  if (!taskId.value || submitting.value) return
  if (action === "rollback" && !confirm("撤销这次补全？仅恢复仍与本次结果一致的内容，后续人工修改或引用冲突会留待处理。")) return
  const token = epoch, scope = key.value, id = taskId.value
  const receiptScopeSnapshot = receiptScope()
  submitting.value = true; error.value = ""
  try {
    if (action === "cancel") await api.tasks.cancel(id, props.projectId)
    else if (action === "rollback") {
      const receipt = await api.imports.rollbackTargetedCompletion(id, props.projectId)
      if (!owns(token, scope)) return
      if (!["rolled_back", "partial"].includes(receipt.status)) throw new Error("尚未取得明确的撤销结果，请重新读取任务状态。")
      const partial = receipt.status === "partial"
      task.value = { ...task.value, result: { ...task.value?.result, targeted_completion: { ...info.value, rollback_status: partial ? "partial" : "rolled_back", rollback_conflicts: receipt.conflicts || 0 } } }
      if (!partial) forget(id)
      refreshAssets(); return
    } else {
      const value = await api.imports.resumeDeepImport(id)
      if (value?.task_id) saveReceipt(value.task_id, receiptScopeSnapshot)
      if (!owns(token, scope)) return
      if (value?.task_id && value.task_id !== id) { forget(id); taskId.value = value.task_id }
    }
    if (owns(token, scope)) observe(taskId.value, token, scope)
  } catch (err) { if (owns(token, scope)) error.value = err.message || "操作未完成，原进度仍保留。" }
  finally { if (owns(token, scope)) submitting.value = false }
}
watch(key, () => {
  epoch += 1; polling.stopAll(); taskId.value = null; task.value = null; submitting.value = false; error.value = ""; name.value = props.initialName
  artifact.value = null; artifactBusy.value = false
  if (props.sourceTaskId) { taskId.value = props.sourceTaskId; observe(props.sourceTaskId); return }
  let saved
  try { saved = recoverActiveWorkflows(props.projectId).filter(item => item.workflowType === "targeted_completion" && item.meta?.completionKey === key.value).at(-1) }
  catch { storageWarning.value = "本机恢复记录暂时不可用；补全期间请保留当前页面。" }
  if (saved) { taskId.value = saved.taskId; name.value = saved.meta.name || name.value; startChapter.value = saved.meta.startChapter || 1; endChapter.value = saved.meta.endChapter || 0; observe(saved.taskId) }
}, { immediate: true, flush: "sync" })
onBeforeUnmount(() => { alive = false; epoch += 1 })
</script>

<template>
  <details class="targeted-completion">
    <summary>{{ sourceTaskId ? '本轮补全结果' : '查漏补全' }}<span v-if="taskId"> · {{ statusLabel }}</span></summary>
    <div class="targeted-completion__body">
      <form v-if="!sourceTaskId" @submit.prevent="start">
        <label>补全对象<input v-model="name" class="form-input" maxlength="200" :disabled="busy" placeholder="已有对象或漏掉的名称" /></label>
        <div class="targeted-completion__range">
          <label>起始章节<input v-model.number="startChapter" class="form-input" type="number" min="1" :disabled="busy" /></label>
          <label>结束章节（0 表示末章）<input v-model.number="endChapter" class="form-input" type="number" min="0" :disabled="busy" /></label>
        </div>
        <p>将查读所选章节的工作稿并核对直接关联对象。有可靠原文依据时新增资料、填补空白；已有内容、同名歧义和冲突留待审阅。可离开后继续。</p>
        <button type="submit" class="btn btn-sm" :disabled="busy">{{ submitting ? '正在提交…' : '授权并开始补全' }}</button>
      </form>
      <p v-if="statusLabel" role="status">{{ statusLabel }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="storageWarning" role="alert">{{ storageWarning }}</p>
      <p v-if="taskId">已处理 {{ info.completed_roots || 0 }} / {{ info.root_count || 0 }} 个目标 · 新增 {{ info.created || 0 }} · 填空 {{ info.filled || 0 }} · 待审 {{ info.review || 0 }}</p>
      <p v-for="warning in info.warnings || []" :key="warning">{{ warning }}</p>
      <fieldset v-for="item in info.ambiguities || []" :key="item.key">
        <legend>{{ item.name }}：需要确认身份</legend>
        <label>选择这次要补全的对象
          <select v-model="identityChoices[item.key]" class="form-select" :disabled="busy" @focus="loadIdentities(item)">
            <option value="">请选择</option>
            <option v-for="id in item.candidate_ids" :key="id" :value="id" :disabled="!identities[id] || identities[id].unavailable">{{ identities[id]?.name || '正在读取对象…' }}{{ identities[id]?.summary ? ' · ' + identities[id].summary.slice(0, 100) : '' }}</option>
          </select>
        </label>
        <p>确认后按原章节范围发起一次新的查漏；原任务和已有结果保留。</p>
        <button class="btn btn-sm" :disabled="busy || !identityChoices[item.key]" @click="completeIdentity(item)">确认身份并重新查漏</button>
      </fieldset>
      <div class="targeted-completion__actions">
        <button v-if="busy && taskId" type="button" class="btn btn-sm" :disabled="submitting" @click="act('cancel')">停止补全</button>
        <button v-if="canResume && !busy" type="button" class="btn btn-sm" @click="act('resume')">继续未完成的补全</button>
        <button v-if="canRollback" type="button" class="btn btn-sm" @click="act('rollback')">撤销这次补全</button>
      </div>
      <details v-if="info.package_refs?.length">
        <summary>查看修改与出处</summary>
        <div v-for="(entry, index) in info.package_refs" :key="entry.id" class="targeted-completion__actions">
          <button type="button" class="btn btn-sm" :disabled="artifactBusy" @click="showSources(entry.id)">查看第 {{ index + 1 }} 组依据</button>
          <button v-if="entry.status === 'review'" type="button" class="btn btn-sm" @click="reviewPackage(entry.id)">审阅这组待处理资料</button>
        </div>
        <article v-for="item in artifact?.payload_json?.items || []" :key="item.item_key">
          <strong>{{ item.payload?.entity?.name || initialName || '所选资料' }} · {{ item.kind === 'entity_alias' ? '别名' : item.kind === 'entity_relation' ? '关系' : '对象资料' }}</strong>
          <p v-for="[label, text] in proposedFields(item)" :key="label">{{ label }}：{{ text }}</p>
          <p v-if="item.payload?.alias">{{ item.payload.alias }}</p>
          <p v-if="item.payload?.description">{{ item.payload.description }}</p>
          <p v-for="(source, index) in item.source_refs || []" :key="index">{{ source.source_range?.chapter_index ? `第 ${source.source_range.chapter_index} 章：` : '' }}{{ source.quote || '已保留来源引用' }}</p>
          <p v-if="item.review_reasons?.length">此项依据仍需核对，已保留在待处理资料中。</p>
        </article>
      </details>
    </div>
  </details>
</template>

<style scoped>
.targeted-completion { border: 1px solid var(--border); border-radius: var(--radius-md); margin: 12px 0; min-width: 0; }
.targeted-completion > summary { padding: 12px; cursor: pointer; font-weight: 600; overflow-wrap: anywhere; }
.targeted-completion > summary span, .targeted-completion p { color: var(--text-muted); font-weight: 400; }
.targeted-completion__body { display: grid; gap: 12px; padding: 0 12px 12px; }
.targeted-completion form, .targeted-completion label { display: grid; gap: 8px; min-width: 0; }
.targeted-completion__range { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.targeted-completion input { min-width: 0; width: 100%; box-sizing: border-box; }
.targeted-completion p { margin: 0; overflow-wrap: anywhere; }
.targeted-completion__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.targeted-completion .btn, .targeted-completion input, .targeted-completion summary { min-height: 44px; }
@media (max-width: 460px) { .targeted-completion__range { grid-template-columns: 1fr; } }
</style>
