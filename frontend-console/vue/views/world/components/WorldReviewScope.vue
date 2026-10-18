<script setup>
import { computed, ref, watch } from 'vue'
import { getApi, getLocalDraftAccountScope, getLocalDraftStorage, getRouter, openProjectAssistant } from '../../../bridge/index.js'
import { readLocalDraftBackup, writeLocalDraftBackup } from '../../../shared/localDraftBackup.js'

const props = defineProps({ projectId: { type: String, required: true }, filters: { type: Object, default: () => ({}) } })
const open = ref(false)
const scope = ref(null)
const history = ref([])
const busy = ref(false)
const error = ref('')
const selectedIds = ref([])
let epoch = 0
let pendingFreeze = null
const selectedItems = computed(() => (scope.value?.items || []).filter(item => selectedIds.value.includes(item.entity_id)))
const pageReady = computed(() => selectedItems.value.length > 0 && selectedItems.value.every(item => !item.stale))
const wholePage = computed(() => selectedItems.value.length === scope.value?.items?.length)
const key = () => ({ accountId: getLocalDraftAccountScope(), projectId: props.projectId, section: 'world-review-scope', objectId: 'current' })
const unwrap = result => result?.data ?? result
function persist() {
  const result = writeLocalDraftBackup(getLocalDraftStorage(), key(), null, { scopeId: scope.value?.id, skip: scope.value?.skip || 0, selectedIds: selectedIds.value, pendingFreeze })
  if (!result.ok) error.value = '本机恢复记录未能保存；已冻结范围仍保存在服务器，可从最近清单恢复。'
}
async function request(action) {
  const turn = epoch
  busy.value = true; error.value = ''
  try { const result = await action(); if (turn === epoch) return unwrap(result) }
  catch (cause) { if (turn === epoch) error.value = cause.message || '暂时未能读取整理范围，请重读实际进度。' }
  finally { if (turn === epoch) busy.value = false }
}
async function load(id = scope.value?.id, skip = scope.value?.skip || 0) {
  if (!id) return
  const value = await request(() => getApi().world.entityReviewScope(props.projectId, id, skip))
  if (value) {
    if (scope.value?.id !== value.id || scope.value?.skip !== value.skip) selectedIds.value = value.items.map(item => item.entity_id)
    scope.value = value; persist()
  }
}
async function show() {
  if (!open.value) return
  const turn = epoch
  const data = await request(() => getApi().world.recentEntityReviewScopes(props.projectId))
  if (turn !== epoch) return
  history.value = Array.isArray(data) ? data : []
  const saved = readLocalDraftBackup(getLocalDraftStorage(), key())
  pendingFreeze = saved?.draft?.payload?.pendingFreeze || pendingFreeze
  if (!scope.value && saved?.draft?.payload?.scopeId) {
    await load(saved.draft.payload.scopeId, saved.draft.payload.skip)
    if (turn !== epoch) return
    if (Array.isArray(saved.draft.payload.selectedIds)) { selectedIds.value = saved.draft.payload.selectedIds; persist() }
  }
}
async function freeze() {
  if (!pendingFreeze) {
    if (props.filters.focus) { error.value = '热点分类会随阅读活动变化；请清除热点分类后再冻结筛选结果。'; return }
    const filters = {}
    for (const name of ['entity_type', 'status', 'display_state', 'q', 'source', 'workflow_id', 'needs_review', 'auto_ingested', 'suggested_action', 'scene_id', 'scene_index', 'source_chapter_index', 'confidence_min', 'confidence_max']) {
      const value = props.filters[name]
      if (value !== '' && value !== null && value !== undefined) filters[name] = ['needs_review', 'auto_ingested'].includes(name) ? value === true || value === 'true' : value
    }
    pendingFreeze = { operation_id: crypto.randomUUID(), filters }
    persist()
  }
  const value = await request(() => getApi().world.freezeEntityReviewScope(props.projectId, pendingFreeze))
  if (value) { pendingFreeze = null; selectedIds.value = value.items.map(item => item.entity_id); scope.value = value; persist(); await show() }
}
async function decide(disposition) {
  const current = scope.value
  const value = await request(() => getApi().world.decideEntityReviewScope(props.projectId, current.id, {
    expected_revision: current.revision, entity_ids: selectedItems.value.map(item => item.entity_id), disposition,
  }))
  if (value) await load(current.id, current.skip)
}
async function discuss() {
  if (!pageReady.value) return
  await request(() => openProjectAssistant({ projectId: props.projectId, context: {
    page: 'world', scope: 'current', task_hint: 'organize',
    selected_entities: selectedItems.value.map(item => ({ kind: 'entity', entity_id: item.entity_id, updated_at: item.updated_at })),
  }, message: `本清单共 ${scope.value.total} 个对象；本次只核对第 ${scope.value.skip + 1} 至 ${scope.value.skip + scope.value.items.length} 项中明确勾选的 ${selectedItems.value.length} 项。分页读回原资料，按缺漏、同名线索和可准备修改分组，说明未检查范围。不要凭同名认定同一对象；每批仍按既有容量和批准规则执行。` }))
}
function locate(item) {
  getRouter()?.navigate('world', 'bible', true, new URLSearchParams({ entity_id: item.entity_id }))
}
watch(() => [getLocalDraftAccountScope(), props.projectId], () => {
  epoch++; scope.value = null; history.value = []; selectedIds.value = []; pendingFreeze = null; error.value = ''; busy.value = false
  if (open.value) void show()
})
</script>

<template>
  <details class="card world-review-scope" :open="open" @toggle="open = $event.target.open; show()">
    <summary>按冻结清单整理全部匹配对象</summary>
    <p>先保存当前筛选的对象和版本，再分页核对。每页最多 20 项；讨论与修改只处理当前页。新对象不会自动加入。</p>
    <button type="button" class="btn btn-sm" :disabled="busy" @click="freeze">{{ pendingFreeze ? '核对上次冻结结果' : '冻结当前筛选结果' }}</button>
    <label v-if="history.length">恢复最近的冻结清单
      <select class="form-select" aria-label="恢复冻结清单" :value="scope?.id || ''" :disabled="busy" @change="load($event.target.value, 0)">
        <option value="" disabled>选择清单</option>
        <option v-for="item in history" :key="item.id" :value="item.id">{{ new Date(item.created_at).toLocaleString() }} · {{ item.total }} 项{{ item.filters.q ? ` · ${item.filters.q}` : '' }}</option>
      </select>
    </label>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="scope" aria-label="冻结范围与核对进度">
      <p role="status">冻结 {{ scope.total }} 项 · 人工已核对 {{ scope.checked }} · 暂缓 {{ scope.deferred }} · 待核对 {{ scope.remaining }} · 版本已变 {{ scope.stale }}</p>
      <p>{{ scope.omission }}</p>
      <p v-if="!scope.total">本次筛选没有对象。可调整筛选后另建清单。</p>
      <ul><li v-for="item in scope.items" :key="item.entity_id">
        <label class="scope-choice"><input v-model="selectedIds" type="checkbox" :value="item.entity_id" :disabled="busy" :aria-label="`选择核对${item.name}`" @change="persist" />选择</label>
        <button type="button" class="btn btn-sm btn-ghost" @click="locate(item)">{{ item.name }} · 打开核对</button>
        <span>{{ item.stale ? '版本已变，请重新冻结' : item.disposition === 'checked' ? '人工已核对' : item.disposition === 'deferred' ? '暂缓' : '待核对' }}</span>
      </li></ul>
      <p v-if="scope.items.length">本页勾选 {{ selectedItems.length }} / {{ scope.items.length }} 项。讨论和标记只处理勾选项；版本已变的对象可取消勾选，其他对象仍可继续。</p>
      <div v-if="scope.items.length" class="row-actions">
        <button type="button" class="btn btn-sm" :disabled="busy || !pageReady" @click="discuss">{{ wholePage ? '讨论本页对象' : '讨论所选对象' }}</button>
        <button type="button" class="btn btn-sm" :disabled="busy || !pageReady" @click="decide('checked')">{{ wholePage ? '我已核对本页' : '我已核对所选' }}</button>
        <button type="button" class="btn btn-sm" :disabled="busy || !pageReady" @click="decide('deferred')">{{ wholePage ? '本页留待以后' : '所选留待以后' }}</button>
        <button type="button" class="btn btn-sm" :disabled="busy || !selectedItems.length" @click="decide('pending')">{{ wholePage ? '本页重新待核对' : '所选重新待核对' }}</button>
      </div>
      <div class="row-actions">
        <button type="button" class="btn btn-sm" :disabled="busy || !scope.skip" @click="load(scope.id, Math.max(0, scope.skip - scope.limit))">上一页</button>
        <span>{{ scope.items.length ? scope.skip + 1 : 0 }}–{{ scope.skip + scope.items.length }} / {{ scope.total }}</span>
        <button type="button" class="btn btn-sm" :disabled="busy || !scope.has_more" @click="load(scope.id, scope.skip + scope.limit)">下一页</button>
        <button type="button" class="btn btn-sm" :disabled="busy" @click="load()">重读实际进度</button>
      </div>
    </section>
  </details>
</template>

<style scoped>
.world-review-scope { margin-block: 1rem; }
.world-review-scope summary { cursor: pointer; font-weight: 600; }
.world-review-scope label { display: block; margin-block: .75rem; }
.world-review-scope li { margin-block: .4rem; }
.world-review-scope .scope-choice { display: inline-flex; align-items: center; gap: .4rem; min-height: 44px; margin: 0; }
.row-actions { flex-wrap: wrap; }
</style>
