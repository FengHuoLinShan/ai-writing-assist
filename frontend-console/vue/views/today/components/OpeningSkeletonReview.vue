<template>
  <section class="skeleton-review" aria-label="骨架逐条取舍">
    <p v-if="loading" role="status">正在读取骨架…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <aside v-if="savedDraft" role="note"><p>重新读取前的修改已备份。核对最新内容后，可恢复修改并重新保存。</p><button type="button" class="btn" :disabled="busy || loading" @click="recoverDraft">恢复我的修改</button></aside>
    <template v-if="suggestion">
      <p v-if="!adopted">勾选要保留的条目；改名、修改简介或排除冲突后，先保存取舍再采用。</p>
      <article v-for="item in items" :key="item.item_key">
        <label><input v-model="item.included" type="checkbox" :disabled="adopted || busy || loading" /> {{ item.label }}</label>
        <template v-if="item.editable && !adopted">
          <label>名称 <input v-model="item.name" maxlength="255" :disabled="busy || loading" /></label>
          <label>简介 <textarea v-model="item.summary" rows="2" maxlength="10000" :disabled="busy || loading" /></label>
        </template>
        <p v-else>{{ item.summary }}</p>
        <p v-if="item.reviewReason" role="note">{{ item.reviewReason }}</p>
        <p v-if="conflictText(item.item_key)" role="note">{{ conflictText(item.item_key) }}；请修改或取消勾选。</p>
      </article>
      <div v-if="!adopted" class="opening-flow__actions">
        <button type="button" class="btn" :disabled="busy || loading || !dirty" @click="save">保存取舍</button>
        <button type="button" class="btn btn-primary" data-action="opening-adopt" :disabled="busy || loading || dirty || !items.some(item => item.included) || hasConflicts || !previewHash" @click="$emit('adopt', previewHash)">采用所选条目</button>
        <button type="button" class="btn" :disabled="busy || loading" @click="load">重新读取</button>
      </div>
      <div v-else class="opening-flow__actions">
        <button type="button" class="btn" :disabled="busy || loading || rolledBack" @click="rollback">撤销这次骨架采用</button>
      </div>
      <p v-if="notice" role="status">{{ notice }}</p>
      <p v-for="entry in rollbackResults" :key="entry.item_key">{{ items.find(item => item.item_key === entry.item_key)?.label || '骨架条目' }}：{{ ({ rolled_back: '已撤销', already_rolled_back: '此前已撤销', modified_after_adoption: '采用后已编辑，保留', referenced_by_author: '已被引用，保留' })[entry.status] || '已保留，请核对原对象' }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getConfirmAction, registerAuxiliaryLeaveGuard } from "../../../bridge/index.js"
import { confirmAsync } from "../../../../shared/confirmAsync.js"

const props = defineProps({ projectId: { type: String, required: true }, packageId: { type: String, required: true }, adopted: Boolean })
const emit = defineEmits(["adopt", "rolled-back"])
const api = getApi()
const suggestion = ref(null), items = ref([]), conflicts = ref([])
const loading = ref(false), busy = ref(false), error = ref(""), notice = ref("")
const previewHash = ref(""), baseline = ref(""), rolledBack = ref(false), rollbackResults = ref([])
const savedDraft = ref(null)
let knownNames = new Map()
const backupKey = computed(() => `opening-skeleton-draft:${props.projectId}:${props.packageId}`)
function backupDraft(key = backupKey.value) {
  if (!dirty.value) return true
  savedDraft.value = JSON.parse(JSON.stringify(items.value))
  try { localStorage.setItem(key, JSON.stringify(savedDraft.value)); return true } catch { error.value = "本地备份不可用；请保留此页，当前修改仍在恢复副本中。"; return false }
}
function recoverDraft() {
  const edits = new Map((savedDraft.value || []).map(item => [item.item_key, item]))
  items.value = items.value.map(item => edits.has(item.item_key) ? { ...item, included: edits.get(item.item_key).included, ...(item.editable ? { name: edits.get(item.item_key).name, summary: edits.get(item.item_key).summary } : {}) } : item)
  previewHash.value = ""
  notice.value = "已恢复修改；请核对最新条目后重新保存。"
}
const dirty = computed(() => JSON.stringify(items.value) !== baseline.value)
const hasConflicts = computed(() => conflicts.value.some(entry => items.value.find(item => item.item_key === entry.item_key)?.included && entry.conflicts?.length))
function conflictText(key) {
  return (conflicts.value.find(entry => entry.item_key === key)?.conflicts || []).map(entry => entry.reason === "duplicate_name" ? `与所选条目重名：${(entry.with || []).join('、')}` : `与已有对象重名：${(entry.with || []).join('、')}`).join('；')
}
function restore(value, existingNames = knownNames) {
  suggestion.value = value
  const packageItems = value.payload_json?.items || []
  const names = new Map(packageItems.map(item => [item.item_key, item.payload?.entity?.name || item.payload?.title || '已有对象']))
  const endpoint = reference => names.get(String(reference).replace(/^local:/, "")) || existingNames.get(String(reference).replace(/^existing:/, "")) || '已有对象（请在设定中核对）'
  items.value = packageItems.map(item => {
    const payload = item.payload || {}, entity = payload.entity || {}
    let label = entity.name || payload.title || existingNames.get(payload.entity_id) || '已有对象'
    let summary = entity.summary || Object.values(payload.fields || {}).join('；')
    if (item.kind === "entity_relation") { label = `${endpoint(payload.source_ref)} → ${endpoint(payload.target_ref)}：${payload.relation_type}`; summary = payload.description || '关系无补充说明' }
    if (item.kind === "entity_alias") { label = `${endpoint(payload.entity_ref)}的别名：${payload.alias}`; summary = '别名附着于已有对象，不创建新对象' }
    if (item.kind === "world_bible_page") summary = [payload.free_text, ...(payload.sections_json || []).map(section => [section.title, section.body_markdown].filter(Boolean).join('：')), ...(payload.claim_mappings || []).map(claim => claim.claim)].filter(Boolean).join('\n')
    const reasons = { endpoint_excluded: '关联对象已排除；本条依赖该对象，需一并核对', endpoint_requires_review: '关联对象待核对', duplicate_name: '名称重复，需核对', source_stale: '来源已变化，需重新核对' }
    return { item_key: item.item_key, included: item.disposition === "include", editable: item.kind === "core_entity" && payload.operation === "create", name: entity.name || "", summary, label, reviewReason: (item.review_reasons || []).map(reason => reasons[reason] || '此条需要作者核对后采用').join('；') }
  })
  baseline.value = JSON.stringify(items.value)
  rolledBack.value = Boolean(value.result_ref_json?.rollback)
  rollbackResults.value = value.result_ref_json?.rollback || []
}
async function load() {
  const projectId = props.projectId, packageId = props.packageId
  error.value = ""
  if (!backupDraft()) return
  loading.value = true
  try {
    const value = await api.world.getAdoptionArtifact(packageId, projectId)
    const existingIds = [...new Set((value.payload_json?.items || []).flatMap(item => [item.payload?.entity_id, item.payload?.source_ref, item.payload?.target_ref, item.payload?.entity_ref]).filter(reference => reference && !reference.startsWith("local:")).map(reference => reference.replace(/^existing:/, "")))]
    const existingNames = new Map(await Promise.all(existingIds.map(async id => [id, (await api.world.getEntity(id, projectId)).name])))
    const preview = props.adopted ? null : await api.world.previewAdoptionPackage(packageId, projectId)
    if (projectId !== props.projectId || packageId !== props.packageId) return
    knownNames = existingNames
    restore(value, existingNames); previewHash.value = preview?.expected_preview_hash || ""
    conflicts.value = (preview?.canon_diff || []).filter(item => item.conflicts?.length)
  } catch (cause) { if (projectId === props.projectId && packageId === props.packageId) error.value = cause.message || "骨架暂时无法读取，请重试。" }
  finally { if (projectId === props.projectId && packageId === props.packageId) loading.value = false }
}
async function save() {
  const projectId = props.projectId, packageId = props.packageId
  const originals = JSON.parse(baseline.value)
  const edits = items.value.filter(item => JSON.stringify(item) !== JSON.stringify(originals.find(original => original.item_key === item.item_key))).map(item => ({ item_key: item.item_key, included: item.included, ...(item.editable ? { ...(item.name !== originals.find(original => original.item_key === item.item_key)?.name ? { name: item.name } : {}), ...(item.summary !== originals.find(original => original.item_key === item.item_key)?.summary ? { summary: item.summary } : {}) } : {}) }))
  busy.value = true; error.value = ""
  try {
    let result
    let expectedUpdatedAt = suggestion.value.updated_at
    for (let index = 0; index < edits.length; index += 32) {
      result = await api.world.updateAdoptionPackageItems(packageId, { novel_id: projectId, expected_updated_at: expectedUpdatedAt, items: edits.slice(index, index + 32) })
      expectedUpdatedAt = result.suggestion.updated_at
    }
    if (projectId !== props.projectId || packageId !== props.packageId) return
    savedDraft.value = null
    try { localStorage.removeItem(backupKey.value) } catch { /* Saved server copy remains authoritative. */ }
    restore(result.suggestion); conflicts.value = result.item_conflicts || []; previewHash.value = ""
    notice.value = "取舍已保存；只有点击采用才会写入正式设定。"
    try {
      const preview = await api.world.previewAdoptionPackage(packageId, projectId)
      if (projectId !== props.projectId || packageId !== props.packageId) return
      previewHash.value = preview.expected_preview_hash
    } catch { error.value = "取舍已保存，但采用预览读取失败；请重新读取后再采用。" }
  } catch (cause) { if (projectId === props.projectId && packageId === props.packageId) error.value = cause.status === 409 ? "骨架已被更新；当前修改仍保留，请重新读取后核对。" : cause.message || "取舍未保存，请重试。" }
  finally { busy.value = false }
}
async function rollback() {
  if (!await confirmAsync("撤销这次骨架采用？之后已编辑或被引用的对象会保留，并说明原因。", "撤销采用", { confirmAction: getConfirmAction() })) return
  const projectId = props.projectId, packageId = props.packageId
  busy.value = true; error.value = ""
  try {
    const result = await api.world.rollbackAdoptionPackage(packageId, projectId)
    if (projectId !== props.projectId || packageId !== props.packageId) return
    rolledBack.value = true
    rollbackResults.value = result.results || []
    emit("rolled-back")
    notice.value = `已处理撤销：${(result.results || []).length} 条回执；已改动或被引用的内容会保留。`
  } catch (cause) { if (projectId === props.projectId && packageId === props.packageId) error.value = cause.message || "撤销未完成，请重试。" }
  finally { busy.value = false }
}
const unregisterGuard = registerAuxiliaryLeaveGuard(() => backupDraft())
function beforeUnload(event) {
  if (!backupDraft()) { event.preventDefault(); event.returnValue = "" }
}
window.addEventListener("beforeunload", beforeUnload)
onBeforeUnmount(() => { backupDraft(); unregisterGuard(); window.removeEventListener("beforeunload", beforeUnload) })
watch(() => [props.projectId, props.packageId], () => { suggestion.value = null; items.value = []; baseline.value = "[]"; error.value = ""; notice.value = ""; savedDraft.value = null; try { savedDraft.value = JSON.parse(localStorage.getItem(backupKey.value) || "null") } catch { /* Keep the server copy readable. */ } void load() }, { immediate: true })
</script>

<style scoped>
.skeleton-review{display:grid;gap:12px}.skeleton-review article{padding:12px;border:1px solid var(--border);border-radius:8px}.skeleton-review label{display:block;margin:8px 0}.skeleton-review input:not([type=checkbox]),.skeleton-review textarea{width:100%;box-sizing:border-box}.skeleton-review [role=alert]{color:var(--danger)}
</style>
