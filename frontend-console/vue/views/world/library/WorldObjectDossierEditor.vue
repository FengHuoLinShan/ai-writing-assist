<template>
  <section class="object-dossier-editor" :aria-busy="loading || Boolean(busyKey)">
    <header class="object-dossier-editor__header">
      <div>
        <h3>对象档案</h3>
        <p>长期设定按面向记录；本场发生的变化仍以 Story 时点状态为准。</p>
      </div>
      <button type="button" class="btn btn-sm" :disabled="loading || Boolean(busyKey)" @click="loadAll({ confirmDiscard: true })">重新读取</button>
    </header>

    <p v-if="loading" role="status">正在读取对象档案…</p>
    <p v-if="loadError" class="error-card" role="alert">{{ loadError }}</p>
    <p v-if="notice" class="object-dossier-editor__notice" role="status">{{ notice }}</p>

    <template v-if="dossier">
      <p class="object-dossier-editor__coverage">
        已保存修订 {{ dossier.total_count }} 条；本次返回 {{ entries.length }} 条
        <template v-if="dossier.omitted_count">，另有 {{ dossier.omitted_count }} 条未显示</template>。
      </p>

      <div v-if="entries.length" class="object-dossier-editor__entries">
        <article v-for="entry in entries" :key="entry.id" class="object-dossier-editor__entry">
          <header>
            <div>
              <strong>{{ entry.facing_label || entry.facing?.key || '档案条目' }}</strong>
              <span class="object-dossier-editor__revision">修订 {{ entry.revision_number }}</span>
            </div>
            <span v-if="entry.visibility === 'secret'" class="object-dossier-editor__secret">作者秘密</span>
          </header>
          <p class="object-dossier-editor__content">{{ entry.content }}</p>
          <div v-if="entry.tags?.length" class="object-dossier-editor__tags">
            <span v-for="tag in entry.tags" :key="tag">{{ tag }}</span>
          </div>
          <p v-if="entry.validity" class="object-dossier-editor__meta">生效范围：{{ validityLabel(entry.validity) }}</p>
          <p v-if="entry.anchor_problem" class="object-dossier-editor__warning" role="status">生效范围暂无法核对：{{ entry.anchor_problem }}</p>

          <form v-if="editingId === entry.id" class="object-dossier-editor__form" @submit.prevent="saveEdit(entry)">
            <p v-if="conflict?.revisionId === entry.id" class="object-dossier-editor__warning" role="alert">
              {{ conflict.message }}
              <span v-if="conflict.serverEntry">服务器已有修订 {{ conflict.serverEntry.revision_number }}。</span>
              <span v-else>服务器上已没有当前修订，不能安全覆盖。</span>
              <span class="object-dossier-editor__conflict-actions">
                <button type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="resolveEditConflict('reload')">{{ conflict.serverEntry ? '载入服务器版本' : '放弃草稿并关闭' }}</button>
                <button v-if="conflict.serverEntry" type="button" class="btn btn-sm btn-ghost" :disabled="Boolean(busyKey)" @click="resolveEditConflict('keep')">保留我的草稿并基于新版本保存</button>
              </span>
            </p>
            <label><span>内容</span><textarea v-model="editDraft.content" rows="4" maxlength="20000" :disabled="readOnly || Boolean(busyKey)" /></label>
            <label><span>标签（用逗号分隔）</span><input v-model="editDraft.tagsText" maxlength="800" :disabled="readOnly || Boolean(busyKey)"></label>
            <label><span>可见范围</span><select v-model="editDraft.visibility" :disabled="readOnly || Boolean(busyKey)"><option value="public">公开</option><option value="secret">作者秘密</option></select></label>
            <div class="object-dossier-editor__validity">
              <label><span>从哪场开始生效</span><select v-model="editDraft.startAnchor" :disabled="readOnly || Boolean(busyKey)"><option value="">全书</option><option v-if="editDraft.startAnchor && !sceneOptionExists(editDraft.startAnchor)" :value="editDraft.startAnchor">{{ anchorChoiceLabel(editDraft.startAnchor) }}</option><option v-for="scene in scenes" :key="scene.id" :value="`scene:${scene.id}`">{{ sceneLabel(scene) }}</option></select></label>
              <label><span>到哪场结束生效</span><select v-model="editDraft.endAnchor" :disabled="readOnly || Boolean(busyKey)"><option value="">持续至今</option><option v-if="editDraft.endAnchor && !sceneOptionExists(editDraft.endAnchor)" :value="editDraft.endAnchor">{{ anchorChoiceLabel(editDraft.endAnchor) }}</option><option v-for="scene in scenes" :key="scene.id" :value="`scene:${scene.id}`">{{ sceneLabel(scene) }}</option></select></label>
            </div>
            <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
            <div class="object-dossier-editor__actions">
              <button type="submit" class="btn btn-sm btn-primary" :disabled="readOnly || Boolean(busyKey) || !editDirty">{{ busyKey === `edit:${entry.id}` ? '保存中…' : '保存新修订' }}</button>
              <button type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="cancelEdit">取消</button>
            </div>
          </form>
          <div v-else-if="!readOnly" class="object-dossier-editor__actions">
            <button type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="beginEdit(entry)">编辑</button>
          </div>

          <details class="object-dossier-editor__history" @toggle="event => event.target.open && loadHistory(entry.entry_group_id)">
            <summary>查看修订历史</summary>
            <p v-if="historyLoadingId === entry.entry_group_id" role="status">正在读取历史…</p>
            <p v-else-if="historyErrors[entry.entry_group_id]" class="field-error" role="alert">{{ historyErrors[entry.entry_group_id] }}</p>
            <template v-else-if="historyByGroup[entry.entry_group_id]">
              <article v-for="revision in historyByGroup[entry.entry_group_id].entries" :key="revision.id" class="object-dossier-editor__history-item">
                <header><strong>修订 {{ revision.revision_number }}</strong><span>{{ revisionReason(revision.revision_reason) }}</span><time v-if="revision.created_at">{{ formatDate(revision.created_at) }}</time></header>
                <p>{{ revision.content || '此版本清除了内容，不能恢复。' }}</p>
                <p v-if="revision.restored_from_id" class="object-dossier-editor__meta">由历史恢复而来</p>
                <button v-if="!readOnly && revision.content && revision.status !== 'cleared' && revision.id !== entry.id" type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="startRestore(revision, entry)">恢复此版本</button>
                <div v-if="restoreTarget?.revision.id === revision.id" class="object-dossier-editor__restore" role="alertdialog" aria-label="确认恢复档案历史">
                  <p>将追加一条新修订，采用修订 {{ revision.revision_number }} 的内容；已有历史会保留。</p>
                  <p v-if="restoreError" class="field-error" role="alert">{{ restoreError }}</p>
                  <div class="object-dossier-editor__actions">
                    <button type="button" class="btn btn-sm btn-primary" :disabled="Boolean(busyKey)" @click="confirmRestore">{{ busyKey === `restore:${revision.id}` ? '恢复中…' : '确认恢复' }}</button>
                    <button type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="restoreTarget = null">取消</button>
                  </div>
                </div>
              </article>
              <p v-if="historyByGroup[entry.entry_group_id].omitted_count" class="object-dossier-editor__meta">还有 {{ historyByGroup[entry.entry_group_id].omitted_count }} 条历史未显示。</p>
            </template>
            <p v-else>尚未读取历史。</p>
          </details>
        </article>
      </div>
      <div v-if="conflict && !conflict.serverEntry" class="object-dossier-editor__warning" role="alert">
        服务器上已没有这条档案的当前修订。草稿仍保留在此会话中；重新载入服务器状态会关闭编辑。
        <button type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="cancelEdit">放弃草稿并关闭</button>
      </div>
      <p v-if="!conflict && !entries.length && dossier.unknown" class="object-dossier-editor__empty">当前没有已确认的稳定档案条目。</p>
      <p v-else-if="!conflict && !entries.length" class="object-dossier-editor__empty">本次读取没有返回条目；如范围不完整，请先重新读取。</p>

      <section v-if="!readOnly" class="object-dossier-editor__new">
        <h4>新增档案条目</h4>
        <p v-if="facetError" class="field-error" role="alert">{{ facetError }}</p>
        <form class="object-dossier-editor__form" @submit.prevent="createEntry">
          <label><span>档案面向</span><select v-model="newDraft.facingKey" :disabled="Boolean(busyKey) || !facets.length"><option value="">选择面向</option><option v-for="facet in facets" :key="facingKey(facet.facing)" :value="facingKey(facet.facing)">{{ facet.label }}<template v-if="facet.source === 'project'"> · 项目自定义</template></option></select></label>
          <p v-if="selectedFacet?.description" class="object-dossier-editor__meta">{{ selectedFacet.description }}</p>
          <label><span>内容</span><textarea v-model="newDraft.content" rows="4" maxlength="20000" :disabled="Boolean(busyKey)" /></label>
          <label><span>标签（用逗号分隔）</span><input v-model="newDraft.tagsText" maxlength="800" :disabled="Boolean(busyKey)"></label>
          <label><span>可见范围</span><select v-model="newDraft.visibility" :disabled="Boolean(busyKey)"><option value="public">公开</option><option value="secret">作者秘密</option></select></label>
          <div class="object-dossier-editor__validity">
            <label><span>从哪场开始生效</span><select v-model="newDraft.startSceneId" :disabled="Boolean(busyKey)"><option value="">全书</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ sceneLabel(scene) }}</option></select></label>
            <label><span>到哪场结束生效</span><select v-model="newDraft.endSceneId" :disabled="Boolean(busyKey)"><option value="">持续至今</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ sceneLabel(scene) }}</option></select></label>
          </div>
          <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
          <div class="object-dossier-editor__actions"><button type="submit" class="btn btn-sm btn-primary" :disabled="Boolean(busyKey) || !newDraft.facingKey || !newDraft.content.trim()">{{ busyKey === 'create' ? '保存中…' : '保存档案条目' }}</button></div>
        </form>
      </section>

      <section class="object-dossier-editor__templates">
        <header><div><h4>档案模板</h4><p>为“{{ typeLabel }}”定义可复用的面向、字段说明与必填项。</p></div><button type="button" class="btn btn-sm" :disabled="templateLoading || Boolean(busyKey)" @click="loadTemplate">{{ templateLoading ? '读取中…' : '读取模板' }}</button></header>
        <p v-if="templateError" class="field-error" role="alert">{{ templateError }}</p>
        <p v-if="templateSaved" class="object-dossier-editor__notice" role="status">模板已保存为第 {{ templateSaved.version_number }} 版。</p>
        <template v-if="templateLoaded">
          <p v-if="templateConflict" class="object-dossier-editor__warning" role="alert">
            {{ templateConflict.message }}<span class="object-dossier-editor__conflict-actions"><button type="button" class="btn btn-sm" :disabled="Boolean(busyKey)" @click="resolveTemplateConflict('reload')">载入服务器模板</button><button v-if="templateConflict.server" type="button" class="btn btn-sm btn-ghost" :disabled="Boolean(busyKey)" @click="resolveTemplateConflict('keep')">保留我的模板草稿</button></span>
          </p>
          <p v-if="templateVersion != null" class="object-dossier-editor__meta">当前模板第 {{ templateVersion }} 版；未保存内容不会显示为已保存。</p>
          <p v-else class="object-dossier-editor__meta">尚无模板；保存后会创建第 1 版。</p>
          <fieldset class="object-dossier-editor__template-fields" :disabled="readOnly || Boolean(busyKey)">
            <legend>模板字段（{{ templateFields.length }}）</legend>
            <label v-for="(field, index) in templateFields" :key="fieldKey(field, index)" class="object-dossier-editor__template-field">
              <span>{{ facetLabel(field.facing) }}</span>
              <input v-model="field.label" aria-label="模板字段显示名称" maxlength="120" placeholder="字段名称">
              <input v-model="field.description" aria-label="模板字段说明" maxlength="500" placeholder="填写说明">
              <select v-model="field.value_kind" aria-label="模板字段类型"><option value="text">单行文本</option><option value="text_list">文本列表</option></select>
              <label><input v-model="field.required" type="checkbox"> 必填</label>
              <button v-if="!readOnly" type="button" class="btn btn-sm btn-ghost" :disabled="Boolean(busyKey)" @click="removeTemplateField(index)">移除</button>
            </label>
            <label v-if="!readOnly"><span>添加已有面向</span><select v-model="templateFacingToAdd"><option value="">选择面向</option><option v-for="facet in availableTemplateFacets" :key="facingKey(facet.facing)" :value="facingKey(facet.facing)">{{ facet.label }}</option></select></label>
            <button v-if="!readOnly" type="button" class="btn btn-sm" :disabled="Boolean(busyKey) || !templateFacingToAdd" @click="addTemplateField">添加字段</button>
            <details v-if="!readOnly"><summary>高级显示规则</summary><label><span>显示规则 JSON</span><textarea v-model="templateDisplaySchemaText" rows="3" aria-label="显示规则 JSON" /></label></details>
          </fieldset>
          <div v-if="!readOnly" class="object-dossier-editor__actions"><button type="button" class="btn btn-sm btn-primary" :disabled="Boolean(busyKey) || !templateDirty" @click="saveTemplate">{{ busyKey === 'template' ? '保存中…' : '保存模板' }}</button></div>
          <details class="object-dossier-editor__history" @toggle="event => event.target.open && loadTemplateHistory()">
            <summary>模板历史</summary>
            <p v-if="templateHistoryLoading" role="status">正在读取模板历史…</p>
            <p v-else-if="templateHistoryError" class="field-error" role="alert">{{ templateHistoryError }}</p>
            <article v-for="revision in templateHistory" :key="revision.revision_id || revision.id" class="object-dossier-editor__history-item"><header><strong>第 {{ revision.version_number }} 版</strong><time v-if="revision.created_at">{{ formatDate(revision.created_at) }}</time></header><p>{{ revision.revision_reason || '模板修订' }}</p></article>
          </details>
        </template>
      </section>
    </template>
    <p v-if="readOnly" class="object-dossier-editor__readonly" role="status">当前为只读演示；档案、历史恢复和模板均不会显示写入操作。</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { getApi, getConfirm } from "../../../bridge/index.js"

const props = defineProps({
  entity: { type: Object, required: true },
  projectId: { type: String, required: true },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(["dirty", "saved"])
const entityId = computed(() => props.entity?.id || props.entity?.entity_id || "")
const typeLabel = computed(() => ({ character: "人物", location: "地点", item: "物件", faction: "势力", organization: "组织", rule: "规则", secret: "秘密" })[props.entity?.entity_type] || props.entity?.entity_type || "对象")
const readOnly = computed(() => props.readOnly)
const dossier = ref(null)
const facets = ref([])
const scenes = ref([])
const loading = ref(false)
const loadError = ref("")
const facetError = ref("")
const actionError = ref("")
const notice = ref("")
const busyKey = ref("")
const editingId = ref("")
const editExpectedRevisionId = ref("")
const editDraft = reactive({ content: "", tagsText: "", visibility: "public", startAnchor: "", endAnchor: "" })
const newDraft = reactive({ facingKey: "", content: "", tagsText: "", visibility: "public", startSceneId: "", endSceneId: "" })
const conflict = ref(null)
const restoreTarget = ref(null)
const restoreError = ref("")
const historyByGroup = ref({})
const historyErrors = ref({})
const historyLoadingId = ref("")
const template = ref(null)
const templateLoaded = ref(false)
const templateLoading = ref(false)
const templateError = ref("")
const templateSaved = ref(null)
const templateConflict = ref(null)
const templateFields = ref([])
const templateDisplaySchemaText = ref("{}")
const templateBaseline = ref("")
const templateFacingToAdd = ref("")
const templateHistory = ref([])
const templateHistoryLoading = ref(false)
const templateHistoryError = ref("")
let generation = 0
let loadSequence = 0
let dossierReadSequence = 0

const entries = computed(() => dossier.value?.entries || [])
const selectedFacet = computed(() => facets.value.find((item) => facingKey(item.facing) === newDraft.facingKey) || null)
const editDirty = computed(() => {
  const original = editingOriginal.value
  return Boolean(original) && JSON.stringify({ content: editDraft.content, tagsText: editDraft.tagsText, visibility: editDraft.visibility, startAnchor: editDraft.startAnchor, endAnchor: editDraft.endAnchor }) !== JSON.stringify({ content: original.content, tagsText: tagsText(original.tags), visibility: original.visibility, startAnchor: anchorValue(original.validity?.start), endAnchor: anchorValue(original.validity?.end) })
})
const newDraftDirty = computed(() => Boolean(newDraft.facingKey || newDraft.content.trim() || newDraft.tagsText.trim() || newDraft.startSceneId || newDraft.endSceneId || newDraft.visibility !== "public"))
const editingOriginal = computed(() => entries.value.find((item) => item.id === editingId.value) || null)
const templateVersion = computed(() => template.value?.version_number ?? null)
const templateDirty = computed(() => templateLoaded.value && templateSnapshot() !== templateBaseline.value)
const availableTemplateFacets = computed(() => facets.value.filter((item) => !templateFields.value.some((field) => facingKey(field.facing) === facingKey(item.facing))))

function current(token, projectId, id) { return token === generation && props.projectId === projectId && entityId.value === id }
function resetData() {
  generation += 1
  loadSequence += 1
  dossierReadSequence += 1
  dossier.value = null; facets.value = []; scenes.value = []
  loading.value = false; loadError.value = ""; facetError.value = ""; actionError.value = ""; notice.value = ""
  busyKey.value = ""; editingId.value = ""; editExpectedRevisionId.value = ""; conflict.value = null
  restoreTarget.value = null; restoreError.value = ""; historyByGroup.value = {}; historyErrors.value = {}; historyLoadingId.value = ""
  template.value = null; templateLoaded.value = false; templateLoading.value = false; templateError.value = ""; templateSaved.value = null; templateConflict.value = null
  templateFields.value = []; templateDisplaySchemaText.value = "{}"; templateBaseline.value = ""; templateFacingToAdd.value = ""
  templateHistory.value = []; templateHistoryLoading.value = false; templateHistoryError.value = ""
  clearNewDraft()
}

function clearNewDraft() {
  newDraft.facingKey = ""; newDraft.content = ""; newDraft.tagsText = ""; newDraft.visibility = "public"; newDraft.startSceneId = ""; newDraft.endSceneId = ""
}

async function loadAll({ confirmDiscard = false } = {}) {
  if (!props.projectId || !entityId.value) return
  if (confirmDiscard && (editDirty.value || newDraftDirty.value || templateDirty.value || conflict.value)) {
    if (!getConfirm()("当前对象有未保存草稿，确定放弃并重新读取吗？")) return
    resetData()
  }
  const projectId = props.projectId; const id = entityId.value; const token = generation; const requestId = ++loadSequence
  loading.value = true; loadError.value = ""; facetError.value = ""
  const api = getApi()
  const [dossierResult, facetResult, sceneResult] = await Promise.allSettled([
    api.world.getEntityDossier(id, projectId, { cache: "no-store" }),
    api.world.listEntityDossierFacets(id, projectId, { cache: "no-store" }),
    api.outline.listScenesOrdered(projectId),
  ])
  if (!current(token, projectId, id) || requestId !== loadSequence) return
  if (dossierResult.status === "fulfilled") dossier.value = dossierResult.value
  else loadError.value = dossierResult.reason?.message || "对象档案暂时无法读取；不能据此判断档案为空。"
  if (facetResult.status === "fulfilled") facets.value = facetResult.value?.items || []
  else facetError.value = facetResult.reason?.message || "档案面向暂时无法读取，新增条目不可用。"
  if (sceneResult.status === "fulfilled") scenes.value = Array.isArray(sceneResult.value) ? sceneResult.value : sceneResult.value?.items || []
  loading.value = false
  emitDirty()
}

async function reloadDossier() {
  if (!props.projectId || !entityId.value) return null
  const projectId = props.projectId; const id = entityId.value; const token = generation; const requestId = ++dossierReadSequence
  try {
    const result = await getApi().world.getEntityDossier(id, projectId, { cache: "no-store" })
    if (!current(token, projectId, id) || requestId !== dossierReadSequence) return null
    dossier.value = result; loadError.value = ""; emitDirty(); return result
  } catch (error) {
    if (current(token, projectId, id)) loadError.value = error?.message || "对象档案重新读取失败。"
    return null
  }
}

function beginEdit(entry) {
  editingId.value = entry.id; editExpectedRevisionId.value = entry.id
  editDraft.content = entry.content || ""; editDraft.tagsText = tagsText(entry.tags); editDraft.visibility = entry.visibility || "public"
  editDraft.startAnchor = anchorValue(entry.validity?.start); editDraft.endAnchor = anchorValue(entry.validity?.end)
  conflict.value = null; actionError.value = ""; notice.value = ""
  emitDirty()
}
function cancelEdit() {
  editingId.value = ""; editExpectedRevisionId.value = ""; conflict.value = null; actionError.value = ""; emitDirty()
}

async function saveEdit(entry) {
  if (readOnly.value || busyKey.value || !editDirty.value || editingId.value !== entry.id) return
  const projectId = props.projectId; const id = entityId.value; const token = generation
  busyKey.value = `edit:${entry.id}`; actionError.value = ""; notice.value = ""
  try {
    await getApi().world.updateEntityDossierEntry(id, entry.id, projectId, {
      expected_revision_id: editExpectedRevisionId.value,
      content: editDraft.content,
      tags: parseTags(editDraft.tagsText),
      visibility: editDraft.visibility,
      validity: editDraft.startAnchor || editDraft.endAnchor ? {
        start: parseAnchorChoice(editDraft.startAnchor),
        end: parseAnchorChoice(editDraft.endAnchor),
      } : null,
    })
    if (!current(token, projectId, id)) return
    cancelEdit(); await reloadDossier()
    if (!current(token, projectId, id)) return
    notice.value = "档案新修订已保存。"; emit("saved", id)
  } catch (error) {
    if (!current(token, projectId, id)) return
    if (error?.status === 409) {
      const latest = await reloadDossier()
      if (!current(token, projectId, id)) return
      const serverEntry = latest?.entries?.find((item) => item.entry_group_id === entry.entry_group_id) || null
      if (serverEntry) editingId.value = serverEntry.id
      conflict.value = { revisionId: serverEntry?.id || entry.id, serverEntry, message: error.message || "档案已在别处更新。" }
    } else actionError.value = error?.message || "保存失败，草稿已保留。"
  } finally { if (current(token, projectId, id)) busyKey.value = ""; emitDirty() }
}

function resolveEditConflict(choice) {
  const server = conflict.value?.serverEntry
  if (choice === "reload" && server) beginEdit(server)
  else if (choice === "reload") cancelEdit()
  else if (choice === "keep" && server) { editExpectedRevisionId.value = server.id; conflict.value = null; actionError.value = "草稿已保留；再次保存会以服务器修订为基线。" }
  else actionError.value = "服务器上没有可用的当前修订；请载入最新档案后重新编辑。"
  emitDirty()
}

async function createEntry() {
  if (readOnly.value || busyKey.value || !newDraft.facingKey || !newDraft.content.trim()) return
  const projectId = props.projectId; const id = entityId.value; const token = generation
  const facet = selectedFacet.value
  if (!facet) return
  const payload = {
    facing: facet.facing,
    content: newDraft.content,
    tags: parseTags(newDraft.tagsText),
    visibility: newDraft.visibility,
    validity: newDraft.startSceneId || newDraft.endSceneId ? {
      start: newDraft.startSceneId ? { kind: "scene", id: newDraft.startSceneId } : null,
      end: newDraft.endSceneId ? { kind: "scene", id: newDraft.endSceneId } : null,
    } : null,
  }
  busyKey.value = "create"; actionError.value = ""; notice.value = ""
  try {
    await getApi().world.createEntityDossierEntry(id, projectId, payload)
    if (!current(token, projectId, id)) return
    clearNewDraft(); await reloadDossier()
    if (!current(token, projectId, id)) return
    notice.value = "档案条目已保存。"; emit("saved", id)
  } catch (error) { if (current(token, projectId, id)) actionError.value = error?.message || "新增失败；输入已保留。" }
  finally { if (current(token, projectId, id)) busyKey.value = ""; emitDirty() }
}

async function loadHistory(groupId) {
  if (historyByGroup.value[groupId] || historyLoadingId.value) return
  const projectId = props.projectId; const id = entityId.value; const token = generation
  historyLoadingId.value = groupId; historyErrors.value = { ...historyErrors.value, [groupId]: "" }
  try {
    const result = await getApi().world.listEntityDossierHistory(id, projectId, { entryGroupId: groupId, limit: 100, offset: 0 })
    if (!current(token, projectId, id)) return
    historyByGroup.value = { ...historyByGroup.value, [groupId]: result }
  } catch (error) { if (current(token, projectId, id)) historyErrors.value = { ...historyErrors.value, [groupId]: error?.message || "历史暂时无法读取。" } }
  finally { if (current(token, projectId, id)) historyLoadingId.value = "" }
}

function startRestore(revision, currentEntry) { restoreTarget.value = { revision, currentEntry }; restoreError.value = "" }
async function confirmRestore() {
  if (readOnly.value || busyKey.value || !restoreTarget.value) return
  const { revision, currentEntry } = restoreTarget.value
  const projectId = props.projectId; const id = entityId.value; const token = generation
  busyKey.value = `restore:${revision.id}`; restoreError.value = ""
  try {
    await getApi().world.restoreEntityDossierEntry(id, revision.entry_group_id, projectId, {
      revision_id: revision.id,
      expected_current_revision_id: entries.value.find((item) => item.entry_group_id === revision.entry_group_id)?.id || null,
    })
    if (!current(token, projectId, id)) return
    restoreTarget.value = null; await reloadDossier()
    if (!current(token, projectId, id)) return
    notice.value = `已恢复“${currentEntry.facing_label || '档案条目'}”的历史版本。`; emit("saved", id)
  } catch (error) {
    if (!current(token, projectId, id)) return
    if (error?.status === 409) await reloadDossier()
    if (!current(token, projectId, id)) return
    restoreError.value = error?.message || "恢复失败；历史和当前内容均已保留。"
  } finally { if (current(token, projectId, id)) busyKey.value = "" }
}

async function loadTemplate() {
  if (templateLoading.value || busyKey.value || !props.projectId) return
  if (templateDirty.value && !getConfirm()("模板有未保存修改，确定放弃草稿并读取服务器模板吗？")) return
  const projectId = props.projectId; const id = entityId.value; const token = generation
  templateLoading.value = true; templateError.value = ""; templateSaved.value = null
  try {
    let value
    try { value = await getApi().world.getEntityDossierTemplate(props.entity.entity_type, projectId, { cache: "no-store" }) }
    catch (error) { if (error?.status === 404) value = null; else throw error }
    if (!current(token, projectId, id)) return
    template.value = value
    templateFields.value = (value?.fields || []).map((field) => ({ ...field, facing: { ...field.facing } }))
    templateDisplaySchemaText.value = JSON.stringify(value?.display_schema || {}, null, 2)
    templateLoaded.value = true; templateConflict.value = null; templateBaseline.value = templateSnapshot()
  } catch (error) { if (current(token, projectId, id)) templateError.value = error?.message || "模板暂时无法读取；不能据此判断模板为空。" }
  finally { if (current(token, projectId, id)) templateLoading.value = false }
}

function addTemplateField() {
  const facet = facets.value.find((item) => facingKey(item.facing) === templateFacingToAdd.value)
  if (!facet) return
  templateFields.value = [...templateFields.value, { facing: { ...facet.facing }, label: facet.label, description: facet.description || "", required: false, value_kind: "text" }]
  templateFacingToAdd.value = ""; templateSaved.value = null
}
function removeTemplateField(index) { templateFields.value = templateFields.value.filter((_, itemIndex) => itemIndex !== index); templateSaved.value = null }

async function saveTemplate() {
  if (readOnly.value || busyKey.value || !templateDirty.value) return
  const projectId = props.projectId; const id = entityId.value; const token = generation
  let displaySchema
  try { displaySchema = JSON.parse(templateDisplaySchemaText.value || "{}") }
  catch { templateError.value = "显示规则必须是有效 JSON。"; return }
  busyKey.value = "template"; templateError.value = ""; templateSaved.value = null
  try {
    const value = await getApi().world.saveEntityDossierTemplate(props.entity.entity_type, projectId, {
      expected_version_number: templateVersion.value,
      fields: templateFields.value.map(({ facing, label, description, required, value_kind }) => ({ facing, label, description, required, value_kind })),
      display_schema: displaySchema,
    })
    if (!current(token, projectId, id)) return
    template.value = value; templateBaseline.value = templateSnapshot(); templateSaved.value = value; templateConflict.value = null
  } catch (error) {
    if (!current(token, projectId, id)) return
    if (error?.status === 409) {
      let server = null
      try { server = await getApi().world.getEntityDossierTemplate(props.entity.entity_type, projectId, { cache: "no-store" }) } catch { /* template may have been created after a 404 */ }
      if (!current(token, projectId, id)) return
      templateConflict.value = { message: error.message || "模板已在别处更新。", server }
    } else templateError.value = error?.message || "模板保存失败；草稿已保留。"
  } finally { if (current(token, projectId, id)) busyKey.value = ""; emitDirty() }
}

function resolveTemplateConflict(choice) {
  const server = templateConflict.value?.server
  if (choice === "reload" && server) {
    template.value = server; templateFields.value = (server.fields || []).map((field) => ({ ...field, facing: { ...field.facing } })); templateDisplaySchemaText.value = JSON.stringify(server.display_schema || {}, null, 2); templateBaseline.value = templateSnapshot(); templateConflict.value = null
  } else if (choice === "keep" && server) {
    template.value = server; templateConflict.value = null; templateError.value = "模板草稿已保留；再次保存会以服务器版本为基线。"; templateBaseline.value = JSON.stringify({ fields: server.fields || [], display_schema: server.display_schema || {} })
  } else templateError.value = "服务器模板仍不可读，请重试读取后再保存。"
}

async function loadTemplateHistory() {
  if (templateHistory.value.length || templateHistoryLoading.value) return
  const projectId = props.projectId; const id = entityId.value; const token = generation
  templateHistoryLoading.value = true; templateHistoryError.value = ""
  try {
    const result = await getApi().world.listEntityDossierTemplateHistory(props.entity.entity_type, projectId, { cache: "no-store" })
    if (!current(token, projectId, id)) return
    templateHistory.value = result?.items || []
  } catch (error) { if (current(token, projectId, id)) templateHistoryError.value = error?.message || "模板历史读取失败。" }
  finally { if (current(token, projectId, id)) templateHistoryLoading.value = false }
}

function templateSnapshot() {
  let displaySchema = {}
  try { displaySchema = JSON.parse(templateDisplaySchemaText.value || "{}") } catch { displaySchema = templateDisplaySchemaText.value }
  return JSON.stringify({ fields: templateFields.value, display_schema: displaySchema })
}
function emitDirty() { emit("dirty", Boolean(editingId.value && editDirty.value || conflict.value || newDraftDirty.value || templateDirty.value)) }
function tagsText(tags) { return Array.isArray(tags) ? tags.join(", ") : "" }
function parseTags(value) { return [...new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean))].slice(0, 24) }
function facingKey(facing) { return facing?.kind === "project" ? `project:${facing.term_id}` : `core:${facing?.key || ""}` }
function facetLabel(facing) { return facets.value.find((item) => facingKey(item.facing) === facingKey(facing))?.label || facing?.key || "项目面向" }
function fieldKey(field, index) { return `${facingKey(field.facing)}:${index}` }
function sceneLabel(scene) { return scene.title || (scene.scene_index != null ? `第 ${scene.scene_index} 场` : "未命名场景") }
function anchorValue(anchor) { return anchor?.kind && anchor?.id ? `${anchor.kind}:${anchor.id}` : "" }
function parseAnchorChoice(value) {
  if (!value) return null
  const [kind, id] = value.split(":", 2)
  return { kind, id }
}
function sceneOptionExists(value) { return scenes.value.some((scene) => value === `scene:${scene.id}`) }
function anchorChoiceLabel(value) {
  const anchor = parseAnchorChoice(value)
  return anchor?.kind === "chapter" ? `原章节边界 ${String(anchor.id).slice(0, 8)}` : `原场景边界 ${String(anchor?.id || "").slice(0, 8)}`
}
function validityLabel(validity) {
  const label = (anchor) => !anchor ? "全书" : anchor.kind === "scene" ? (scenes.value.find((scene) => scene.id === anchor.id) ? sceneLabel(scenes.value.find((scene) => scene.id === anchor.id)) : `Scene ${String(anchor.id).slice(0, 8)}`) : `章节 ${String(anchor.id).slice(0, 8)}`
  return `${label(validity?.start)} — ${label(validity?.end)}`
}
function revisionReason(reason) { return ({ author_edit: "作者编辑", author_restore: "作者恢复", author_cleared: "作者清除", legacy_import: "旧档案迁入" })[reason] || reason || "历史修订" }
function formatDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString() }

watch(() => [props.projectId, entityId.value], () => { resetData(); if (props.projectId && entityId.value) void loadAll() })
watch([editDirty, newDraftDirty, templateDirty], () => {
  if (templateDirty.value) templateSaved.value = null
  emitDirty()
})
onMounted(() => { if (props.projectId && entityId.value) void loadAll() })
onBeforeUnmount(() => { generation += 1; loadSequence += 1; dossierReadSequence += 1; emit("dirty", false) })
</script>

<style scoped>
.object-dossier-editor{display:grid;gap:14px;min-width:0}.object-dossier-editor__header,.object-dossier-editor__templates>header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.object-dossier-editor h3,.object-dossier-editor h4,.object-dossier-editor p{margin-top:0}.object-dossier-editor__header h3,.object-dossier-editor__templates h4{margin-bottom:3px}.object-dossier-editor__header p,.object-dossier-editor__templates header p{margin-bottom:0;color:var(--text-secondary);font-size:12px;line-height:1.5}.object-dossier-editor__coverage,.object-dossier-editor__meta,.object-dossier-editor__revision,.object-dossier-editor__readonly{color:var(--text-secondary);font-size:12px;line-height:1.5}.object-dossier-editor__entries{display:grid;gap:10px}.object-dossier-editor__entry,.object-dossier-editor__new,.object-dossier-editor__templates{display:grid;gap:10px;min-width:0;padding:12px;border:1px solid var(--border-color,var(--border));border-radius:9px;background:var(--bg-primary,var(--surface))}.object-dossier-editor__entry>header,.object-dossier-editor__entry>header>div,.object-dossier-editor__history-item>header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}.object-dossier-editor__revision{margin-left:8px}.object-dossier-editor__secret{color:var(--danger,#a1362f);font-size:11px}.object-dossier-editor__content{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}.object-dossier-editor__tags{display:flex;flex-wrap:wrap;gap:5px}.object-dossier-editor__tags span{padding:2px 7px;border-radius:999px;background:var(--bg-muted,#f4f2ee);font-size:11px}.object-dossier-editor__form{display:grid;gap:9px}.object-dossier-editor__form>label,.object-dossier-editor__validity>label{display:grid;gap:4px;min-width:0}.object-dossier-editor__form label>span,.object-dossier-editor__validity label>span{color:var(--text-secondary);font-size:12px}.object-dossier-editor textarea,.object-dossier-editor input,.object-dossier-editor select{max-width:100%;min-width:0}.object-dossier-editor__validity{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.object-dossier-editor__actions,.object-dossier-editor__conflict-actions{display:flex;flex-wrap:wrap;gap:7px}.object-dossier-editor__warning{display:grid;gap:7px;padding:9px;border-left:3px solid var(--warning,#a66a00);background:var(--warning-soft,rgba(176,132,32,.08));font-size:12px;line-height:1.5}.object-dossier-editor__history{border-top:1px solid var(--border-color,var(--border));padding-top:8px}.object-dossier-editor__history summary{cursor:pointer;font-size:12px;font-weight:600}.object-dossier-editor__history-item,.object-dossier-editor__restore{display:grid;gap:7px;margin-top:8px;padding:9px;border:1px solid var(--border-color,var(--border));border-radius:7px}.object-dossier-editor__history-item p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.object-dossier-editor__empty{padding:10px;border:1px dashed var(--border-color,var(--border));color:var(--text-secondary)}.object-dossier-editor__templates{background:transparent}.object-dossier-editor__template-fields{display:grid;gap:8px;min-width:0;margin:0;padding:10px;border:1px solid var(--border-color,var(--border));border-radius:7px}.object-dossier-editor__template-field{display:grid;grid-template-columns:minmax(80px,1fr) minmax(100px,1fr) minmax(120px,2fr) minmax(100px,auto) auto auto;align-items:center;gap:7px;padding:8px 0;border-bottom:1px solid var(--border-color,var(--border))}.object-dossier-editor__notice{padding:8px;border-left:3px solid var(--success,#31846a);background:var(--success-soft,rgba(49,132,106,.08));font-size:12px}.object-dossier-editor__readonly{margin:0}@media(max-width:650px){.object-dossier-editor__header,.object-dossier-editor__templates>header{flex-direction:column}.object-dossier-editor__header>.btn,.object-dossier-editor__templates>header>.btn{width:100%;min-height:42px}.object-dossier-editor__validity{grid-template-columns:minmax(0,1fr)}.object-dossier-editor__template-field{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.object-dossier-editor__template-field>span{grid-column:1/-1}}
</style>
