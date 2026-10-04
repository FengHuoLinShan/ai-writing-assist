<template>
  <details class="world-entity-revision-history" :open="autoOpen || undefined" @toggle="onToggle">
    <summary>改动历史</summary>
    <p v-if="loading" role="status">正在读取…</p>
    <div v-else-if="error" class="world-entity-revision-history__error" role="alert">
      <p>{{ error }}</p>
      <button type="button" class="btn btn-sm" data-action="revision-history-retry" @click="load(skip)">重试</button>
    </div>
    <p v-else-if="!revisions.length">还没有改动记录</p>
    <template v-else>
      <article
        v-for="revision in revisions"
        :key="revision.revision_id"
        class="world-entity-revision-history__item"
        :class="{ 'is-highlighted': revision.revision_id === highlightRevisionId }"
        :data-revision-id="revision.revision_id"
      >
        <header class="world-entity-revision-history__meta">
          <span class="muted" :title="formatFullTime(revision.created_at)">{{ formatRelativeTime(revision.created_at) }}</span>
          <span class="pill">{{ revisionReasonLabel(revision.revision_reason) }}</span>
          <span v-if="writingProgress(revision)" class="muted">{{ writingProgress(revision) }}</span>
          <span v-if="revision.restored_from_revision_id" class="muted">来自一次恢复操作</span>
        </header>
        <p v-if="changedFieldsText(revision)" class="world-entity-revision-history__fields">
          改动字段：{{ changedFieldsText(revision) }}<template v-if="revision.changed_fields_exact === false">（大致）</template>
        </p>
        <div class="world-entity-revision-history__note">
          <p v-if="!noteEditing(revision) && revision.change_note">备注：{{ revision.change_note }}</p>
          <p v-if="noteError(revision)" class="field-error" role="alert">{{ noteError(revision) }}</p>
          <div v-if="noteEditing(revision)" class="world-entity-revision-history__note-form">
            <label>
              <span>备注（最多 500 字，留空即删除）</span>
              <textarea v-model="noteDrafts[revision.revision_id]" rows="2" maxlength="500" :data-note-input="revision.revision_id" :disabled="noteSaving"></textarea>
            </label>
            <div class="row-actions">
              <button type="button" class="btn btn-sm btn-primary" :disabled="noteSaving" :data-note-save="revision.revision_id" @click="saveNote(revision)">{{ noteSaving ? '保存中…' : '保存备注' }}</button>
              <button type="button" class="btn btn-sm" :disabled="noteSaving" @click="cancelNote(revision)">取消</button>
            </div>
          </div>
          <button v-else type="button" class="btn btn-sm btn-ghost" :data-note-edit="revision.revision_id" @click="startNote(revision)">{{ revision.change_note ? '编辑备注' : '补写备注' }}</button>
        </div>
        <div class="row-actions world-entity-revision-history__actions">
          <button type="button" class="btn btn-sm" :data-compare-toggle="revision.revision_id" @click="toggleCompare(revision)">{{ comparing(revision) ? '收起对比' : '这次改动前 ↔ 现在' }}</button>
          <button
            v-if="revision.can_restore !== false && restoringId !== revision.revision_id"
            type="button"
            class="btn btn-sm"
            :data-restore="revision.revision_id"
            @click="startRestore(revision)"
          >恢复到这次改动前</button>
          <span v-else-if="revision.can_restore === false" class="muted">对象已移除，先把对象恢复回来才能恢复历史</span>
        </div>
        <div v-if="comparing(revision)" class="world-entity-revision-history__compare" :data-compare-panel="revision.revision_id">
          <template v-if="compareRows(revision).length">
            <div v-for="row in compareRows(revision)" :key="row.key" class="world-entity-revision-history__compare-row">
              <span class="world-entity-revision-history__compare-label">{{ row.label }}</span>
              <template v-if="row.text">
                <VersionTextDiff :diff="row.text" left-label="这次改动前" right-label="现在" />
              </template>
              <div v-else-if="row.json" class="world-entity-revision-history__json" :data-compare-json="row.key">
                <div>
                  <span class="muted">这次改动前</span>
                  <AssistantValue :value="row.before" />
                </div>
                <div>
                  <span class="muted">现在</span>
                  <AssistantValue :value="row.after" />
                </div>
              </div>
              <p v-else class="world-entity-revision-history__inline">{{ row.before }} <span aria-hidden="true">→</span> {{ row.after }}</p>
            </div>
          </template>
          <p v-else>这份快照与当前内容一致。</p>
        </div>
        <div v-if="restoringId === revision.revision_id" class="world-entity-revision-history__confirm" role="alertdialog" aria-label="确认恢复" :data-restore-confirm="revision.revision_id">
          <h4>恢复到这次改动前</h4>
          <template v-if="restoreFields(revision).length">
            <p>将把以下字段改回这次改动之前：</p>
            <ul>
              <li v-for="field in restoreFields(revision)" :key="field.key">
                <strong>{{ field.label }}</strong>
                <span v-if="field.inline">：{{ field.before }} → {{ field.after }}</span>
              </li>
            </ul>
          </template>
          <p v-else>将把这份设定恢复到这次改动之前（当前内容与快照一致）。</p>
          <p>状态保持不变；恢复后会多一条记录，并且可以再撤回。</p>
          <p v-if="restoreError" class="field-error" role="alert">{{ restoreError }}</p>
          <div class="row-actions">
            <button type="button" class="btn btn-sm btn-primary" :disabled="restoreBusy" data-action="revision-restore-confirm" @click="confirmRestore(revision)">{{ restoreBusy ? '正在恢复…' : '确认恢复' }}</button>
            <button type="button" class="btn btn-sm" :disabled="restoreBusy" data-action="revision-restore-cancel" @click="cancelRestore">取消</button>
          </div>
        </div>
      </article>
      <div class="row-actions">
        <button v-if="skip > 0" type="button" class="btn" :disabled="loading" data-action="revision-history-prev" @click="load(Math.max(0, skip - PAGE_SIZE))">上一页</button>
        <button v-if="skip + PAGE_SIZE < total" type="button" class="btn" :disabled="loading" data-action="revision-history-next" @click="load(skip + PAGE_SIZE)">下一页</button>
      </div>
    </template>
  </details>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { getApi, getToast } from "../../../bridge/index.js"
import { confirmEditorialImpact } from "../../../composables/useEditorialGuard.js"
import AssistantValue from "../../../components/AssistantValue.vue"
import VersionTextDiff from "../../../components/VersionTextDiff.vue"
import { buildVersionDiff } from "../../../../shared/versionDiff.js"
import {
  ENTITY_REVISION_FIELD_LABELS,
  IMPORTANCE_LEVEL_LABELS,
  REVEAL_LEVEL_LABELS,
  formatChangedFields,
  formatFullTime,
  formatRelativeTime,
  formatWritingProgress,
  revisionReasonLabel,
} from "../../../../shared/revisionHistory.js"
import { SYSTEM_ENTITY_TYPE_FALLBACK } from "../logic/worldQuery.js"

const props = defineProps({
  entity: { type: Object, required: true },
  projectId: { type: String, required: true },
  autoOpen: { type: Boolean, default: false },
  highlightRevisionId: { type: String, default: "" },
})
const emit = defineEmits(["restored"])

const PAGE_SIZE = 20
const revisions = ref([])
const total = ref(0)
const skip = ref(0)
const loading = ref(false)
const error = ref("")
const opened = ref(props.autoOpen)
let epoch = 0

const entityId = computed(() => props.entity?.id || props.entity?.entity_id || "")

async function load(skipTo = 0) {
  if (!entityId.value) return
  const token = ++epoch
  loading.value = true
  error.value = ""
  try {
    const result = await getApi().world.getEntityRevisions(entityId.value, props.projectId, { skip: skipTo, limit: PAGE_SIZE })
    if (token !== epoch) return
    revisions.value = Array.isArray(result?.items) ? result.items : []
    total.value = Number(result?.total || 0)
    skip.value = skipTo
  } catch (err) {
    if (token !== epoch) return
    error.value = err?.message || "历史读取失败，请重试"
  } finally {
    if (token === epoch) loading.value = false
  }
}

function onToggle(event) {
  opened.value = event.target.open
  if (event.target.open && !revisions.value.length && !loading.value) void load(0)
}

watch(() => [props.projectId, entityId.value], () => {
  epoch += 1
  revisions.value = []
  total.value = 0
  skip.value = 0
  loading.value = false
  error.value = ""
  cancelRestore()
  comparingIds.splice(0, comparingIds.length)
})

function writingProgress(revision) {
  return formatWritingProgress(revision?.writing_chapter_index)
}

function changedFieldsText(revision) {
  return formatChangedFields(revision?.changed_fields)
}

// ---- 备注补写/修改/删除 ----
const noteDrafts = reactive({})
const noteEditingIds = reactive([])
const noteErrors = reactive({})
const noteSaving = ref(false)

function noteEditing(revision) {
  return noteEditingIds.includes(revision.revision_id)
}
function noteError(revision) {
  return noteErrors[revision.revision_id] || ""
}
function startNote(revision) {
  noteDrafts[revision.revision_id] = revision.change_note || ""
  if (!noteEditingIds.includes(revision.revision_id)) noteEditingIds.push(revision.revision_id)
  delete noteErrors[revision.revision_id]
}
function cancelNote(revision) {
  const index = noteEditingIds.indexOf(revision.revision_id)
  if (index >= 0) noteEditingIds.splice(index, 1)
  delete noteDrafts[revision.revision_id]
  delete noteErrors[revision.revision_id]
}
async function saveNote(revision) {
  if (noteSaving.value) return
  const note = String(noteDrafts[revision.revision_id] ?? "").trim()
  if (note.length > 500) {
    noteErrors[revision.revision_id] = "备注最多 500 字"
    return
  }
  noteSaving.value = true
  delete noteErrors[revision.revision_id]
  try {
    await getApi().world.setRevisionNote({ target_kind: "entity", revision_id: revision.revision_id, note }, props.projectId)
    revision.change_note = note || null
    cancelNote(revision)
    getToast()("备注已保存", "success")
  } catch (err) {
    // 失败保留输入，提示失败。
    noteErrors[revision.revision_id] = err?.message || "备注保存失败，输入已保留"
  } finally {
    noteSaving.value = false
  }
}

// ---- 展开「这次改动前 ↔ 现在」 ----
const comparingIds = reactive([])
function comparing(revision) {
  return comparingIds.includes(revision.revision_id)
}
function toggleCompare(revision) {
  const index = comparingIds.indexOf(revision.revision_id)
  if (index >= 0) comparingIds.splice(index, 1)
  else comparingIds.push(revision.revision_id)
}

// ---- 快照与当前的逐字段比较 ----
function typeLabel(value) {
  return SYSTEM_ENTITY_TYPE_FALLBACK.find((item) => item.value === value)?.label || value || "未设置"
}
function aliasList(source) {
  const list = Array.isArray(source) ? source : []
  return list.map((item) => (typeof item === "string" ? item : item?.alias)).filter(Boolean)
}
function snapshotAliases(revision) {
  return aliasList(revision?.snapshot?.aliases)
}
function currentAliases() {
  return aliasList(props.entity?.content_json?.aliases)
}
function importanceText(source) {
  return IMPORTANCE_LEVEL_LABELS[source?.importance_level] || "普通设定"
}
function revealText(source) {
  return REVEAL_LEVEL_LABELS[source?.reveal_level] || "仅作者可见"
}

const COMPARE_FIELDS = [
  { key: "entity_type", label: ENTITY_REVISION_FIELD_LABELS.entity_type, inline: true, before: (r) => typeLabel(r?.snapshot?.entity_type), after: () => typeLabel(props.entity?.entity_type) },
  { key: "name", label: ENTITY_REVISION_FIELD_LABELS.name, inline: true, before: (r) => r?.snapshot?.name || "（空）", after: () => props.entity?.name || "（空）" },
  { key: "summary", label: ENTITY_REVISION_FIELD_LABELS.summary, text: true, before: (r) => r?.snapshot?.summary || "", after: () => props.entity?.summary || "" },
  { key: "public_info", label: ENTITY_REVISION_FIELD_LABELS.public_info, text: true, before: (r) => r?.snapshot?.public_info || "", after: () => props.entity?.public_info || "" },
  { key: "hidden_truth", label: ENTITY_REVISION_FIELD_LABELS.hidden_truth, text: true, before: (r) => r?.snapshot?.hidden_truth || "", after: () => props.entity?.hidden_truth || "" },
  { key: "aliases", label: ENTITY_REVISION_FIELD_LABELS.aliases, inline: true, before: (r) => snapshotAliases(r).join("、") || "（无）", after: () => currentAliases().join("、") || "（无）" },
  { key: "content", label: ENTITY_REVISION_FIELD_LABELS.content, json: true, before: (r) => r?.snapshot?.content_json || null, after: () => props.entity?.content_json || null },
  { key: "importance", label: ENTITY_REVISION_FIELD_LABELS.importance, inline: true, before: (r) => importanceText(r?.snapshot), after: () => importanceText(props.entity) },
  { key: "reveal_level", label: ENTITY_REVISION_FIELD_LABELS.reveal_level, inline: true, before: (r) => revealText(r?.snapshot), after: () => revealText(props.entity) },
]

function fieldChanged(field, revision) {
  if (field.key === "content") {
    return stableStringify(normalizeJson(field.before(revision))) !== stableStringify(normalizeJson(field.after()))
  }
  if (field.key === "aliases") {
    return snapshotAliases(revision).join("\u0000") !== currentAliases().join("\u0000")
  }
  if (field.text) return String(field.before(revision) || "") !== String(field.after() || "")
  return field.before(revision) !== field.after()
}

/** 与后端快照视图同口径：去掉内部来源标记，别名单独比较（快照 content_json 已不含 aliases）。 */
function normalizeJson(value) {
  if (!value || typeof value !== "object") return value ?? null
  const copy = { ...value }
  delete copy._meta
  delete copy.aliases
  delete copy.updated_at
  return copy
}

/** 键序无关的 JSON 序列化，避免同内容不同键序被误判为改动。 */
function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`
  }
  return JSON.stringify(value ?? null)
}

/** 展开对比行：文本字段带 VersionTextDiff，其他资料前后并列展示，其余内联「前 → 后」。 */
function compareRows(revision) {
  return COMPARE_FIELDS
    .filter((field) => fieldChanged(field, revision))
    .map((field) => ({
      key: field.key,
      label: field.label,
      inline: Boolean(field.inline),
      json: Boolean(field.json),
      text: field.text ? buildVersionDiff(String(field.before(revision) || ""), String(field.after() || "")) : null,
      before: field.json ? normalizeJson(field.before(revision)) : (field.inline ? field.before(revision) : ""),
      after: field.json ? normalizeJson(field.after()) : (field.inline ? field.after() : ""),
    }))
}

/** 确认区列出的将改回字段（含其他资料这类 JSON 字段的提示行）。 */
function restoreFields(revision) {
  return COMPARE_FIELDS
    .filter((field) => fieldChanged(field, revision))
    .map((field) => ({
      key: field.key,
      label: field.label,
      inline: Boolean(field.inline) && !field.json,
      before: field.inline ? field.before(revision) : "",
      after: field.inline ? field.after() : "",
    }))
}

// ---- 恢复到这次改动前 ----
const restoringId = ref(null)
const restoreBusy = ref(false)
const restoreError = ref("")

async function startRestore(revision) {
  restoreError.value = ""
  restoringId.value = revision.revision_id
  // 先做编辑审读影响确认（复用 worldEntityOps 的 confirmEditorialImpact）。
  const allowed = await confirmEditorialImpact(props.projectId, { kind: "world" })
  if (restoringId.value !== revision.revision_id) return
  if (!allowed) cancelRestore()
}
function cancelRestore() {
  restoringId.value = null
  restoreError.value = ""
}

async function confirmRestore(revision) {
  if (restoreBusy.value) return
  restoreBusy.value = true
  restoreError.value = ""
  try {
    await getApi().world.rollbackEntityToRevision(
      entityId.value,
      { revision_id: revision.revision_id, expected_updated_at: props.entity?.updated_at || null },
      props.projectId,
    )
    cancelRestore()
    getToast()("已恢复，并记下了这次恢复", "success")
    emit("restored", entityId.value)
    await load(0)
  } catch (err) {
    if (Number(err?.status) === 409 && ["edit_baseline_required", "edit_baseline_stale"].includes(err?.body?.error)) {
      // 基线过期：已重新读取，请作者用新内容再确认一次。
      restoreError.value = "这个设定刚在别处改过，已重新读取，请再确认一次"
      emit("restored", entityId.value)
      await load(skip.value)
    } else {
      restoreError.value = err?.message || "恢复失败，请重试"
    }
  } finally {
    restoreBusy.value = false
  }
}

defineExpose({ load })
</script>

<style scoped>
.world-entity-revision-history { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; display: grid; gap: 10px; }
.world-entity-revision-history > summary { cursor: pointer; font-weight: 600; }
.world-entity-revision-history__item { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; display: grid; gap: 8px; }
.world-entity-revision-history__item.is-highlighted { outline: 2px solid var(--accent, #2563eb); outline-offset: 2px; }
.world-entity-revision-history__meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.world-entity-revision-history__fields { margin: 0; }
.world-entity-revision-history__note { display: grid; gap: 4px; }
.world-entity-revision-history__note > p { margin: 0; white-space: pre-wrap; }
.world-entity-revision-history__note-form { display: grid; gap: 6px; }
.world-entity-revision-history__note-form label { display: grid; gap: 4px; }
.world-entity-revision-history__note-form span { color: var(--text-secondary); font-size: var(--text-sm); }
.world-entity-revision-history__note-form textarea { width: 100%; }
.world-entity-revision-history__compare { border-top: 1px dashed var(--border); padding-top: 8px; display: grid; gap: 10px; }
.world-entity-revision-history__compare-row { display: grid; gap: 4px; }
.world-entity-revision-history__compare-label { font-weight: 600; font-size: var(--text-sm); }
.world-entity-revision-history__inline { margin: 0; white-space: pre-wrap; }
.world-entity-revision-history__json { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; }
.world-entity-revision-history__json > div { display: grid; gap: 4px; min-width: 0; }
.world-entity-revision-history__confirm { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 10px 12px; display: grid; gap: 8px; }
.world-entity-revision-history__confirm h4 { margin: 0; }
.world-entity-revision-history__confirm p, .world-entity-revision-history__confirm ul { margin: 0; }
.world-entity-revision-history__error { display: grid; gap: 6px; }
@media (max-width: 760px) {
  .world-entity-revision-history__actions .btn, .world-entity-revision-history__note-form .btn { min-height: 44px; }
  .world-entity-revision-history__note-form textarea { min-height: 44px; }
}
</style>
