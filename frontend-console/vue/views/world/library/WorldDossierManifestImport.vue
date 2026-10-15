<template>
  <section class="manifest-import">
    <h4>从档案清单导入</h4>
    <p>选择已导出的 JSON 文件，核对面向和生效范围后再采用到“{{ entity.name }}”。</p>
    <label class="manifest-import__file">选择档案清单文件
      <input type="file" accept=".json,application/json" @change="chooseFile">
    </label>
    <p v-if="error" role="alert" class="field-error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="manifest">
      <p>来源对象：{{ manifest.source_entity_name }}；档案条目 {{ manifest.entries.length }} 条。</p>
      <details open><summary>核对将导入的内容</summary>
        <ul><li v-for="entry in manifest.entries" :key="entry.source_revision_id">
          <strong>{{ entry.facing_label }}</strong> · {{ entry.visibility === 'secret' ? '作者秘密' : '公开' }}：{{ entry.content }}
        </li></ul>
      </details>
      <fieldset v-if="manifest.template" :disabled="Boolean(busy)">
        <legend>模板版本</legend>
        <p v-if="targetTemplate">目标当前模板第 {{ targetTemplate.version_number }} 版。清单中的模板仅作来源说明，不会覆盖目标模板。</p>
        <p v-else class="field-error">目标类型尚无模板，请先在上方创建模板后重新读取。</p>
        <label><input v-model="templateConfirmed" type="checkbox" @change="invalidatePreview"> 已核对目标模板</label>
      </fieldset>
      <fieldset v-if="sourceFacings.length" :disabled="Boolean(busy)">
        <legend>面向映射</legend>
        <label v-for="face in sourceFacings" :key="face.key">
          <span>来源：{{ face.label }}</span>
          <select v-model="face.target" @change="invalidatePreview">
            <option value="">{{ face.required ? '请选择目标面向' : '沿用原面向' }}</option>
            <option v-for="facet in facets" :key="facingKey(facet.facing)" :value="facingKey(facet.facing)">{{ facet.label }}</option>
          </select>
        </label>
      </fieldset>
      <fieldset v-if="sourceAnchors.length" :disabled="Boolean(busy)">
        <legend>来源生效范围</legend>
        <label v-for="(anchor, index) in sourceAnchors" :key="anchor.key">
          <span>来源{{ anchor.kind === 'scene' ? '场景' : '章节' }}边界 {{ index + 1 }}</span>
          <select v-model="anchor.target" @change="invalidatePreview">
            <option value="">请选择目标{{ anchor.kind === 'scene' ? '场景' : '章节' }}</option>
            <option v-for="option in anchor.kind === 'scene' ? scenes : chapters" :key="option.id" :value="option.id">{{ option.label }}</option>
          </select>
        </label>
      </fieldset>
      <fieldset v-if="sourceStoryFields.length" :disabled="Boolean(busy)">
        <legend>Story 状态字段</legend>
        <label v-for="field in sourceStoryFields" :key="field.key">
          <span>来源：{{ field.label }}</span>
          <select v-model="field.target" @change="invalidatePreview">
            <option value="">请选择目标状态字段</option>
            <option v-for="candidate in targetTemplate?.state_fields || []" :key="candidate.key" :value="candidate.key">{{ candidate.label }}</option>
          </select>
        </label>
      </fieldset>
      <div class="manifest-import__actions">
        <button type="button" class="btn btn-sm" :disabled="busy || !ready" @click="previewImport">{{ busy === 'preview' ? '预览中…' : '预览导入' }}</button>
        <button type="button" class="btn btn-sm btn-ghost" :disabled="Boolean(busy)" @click="clearFile">放弃文件</button>
      </div>
      <section v-if="preview" class="manifest-import__review" aria-label="导入预览">
        <p>将新增 {{ preview.create_count }} 条、更新 {{ preview.update_count }} 条；已有 {{ preview.already_imported_count }} 条，跳过 {{ preview.skipped_count }} 条。</p>
        <p v-for="warning in preview.warnings" :key="warning" class="object-dossier-editor__warning">{{ warning }}</p>
        <fieldset v-if="preview.conflicts.length" :disabled="Boolean(busy)">
          <legend>冲突条目</legend>
          <label v-for="item in preview.conflicts" :key="item.source_revision_id">
            <input v-model="skipConflicts" type="checkbox" :value="item.source_revision_id" @change="invalidatePreview">
            跳过“{{ item.facing_label }}”（{{ conflictLabel(item.reason) }}）
          </label>
          <p>选择跳过后需重新预览。</p>
        </fieldset>
        <label v-if="preview.can_apply"><input v-model="confirmed" type="checkbox"> 我已核对内容、秘密可见范围和冲突处理</label>
        <button type="button" class="btn btn-sm btn-primary" :disabled="busy || !preview.can_apply || !confirmed" @click="applyImport">{{ busy === 'apply' ? '采用中…' : '确认采用档案清单' }}</button>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, required: true },
  entity: { type: Object, required: true },
  facets: { type: Array, default: () => [] },
  scenes: { type: Array, default: () => [] },
})
const emit = defineEmits(["dirty", "saved"])
const manifest = ref(null)
const targetTemplate = ref(null)
const chapters = ref([])
const sourceFacings = ref([])
const sourceAnchors = ref([])
const sourceStoryFields = ref([])
const templateConfirmed = ref(false)
const skipConflicts = ref([])
const preview = ref(null)
const confirmed = ref(false)
const busy = ref("")
const error = ref("")
const notice = ref("")
let generation = 0

const ready = computed(() => manifest.value && (!manifest.value.template || (targetTemplate.value && templateConfirmed.value)) &&
  sourceFacings.value.every((item) => !item.required || item.target) &&
  sourceAnchors.value.every((item) => item.target) && sourceStoryFields.value.every((item) => item.target))
function facingKey(facing) { return facing?.kind === "project" ? `project:${facing.term_id}` : `core:${facing?.key}` }
function conflictLabel(reason) { return ({ already_changed: "目标已由作者修改", target_group_collision: "目标条目身份冲突", target_facing_changed: "目标面向已变化" })[reason] || "需要核对" }
function invalidatePreview() { preview.value = null; confirmed.value = false }
function clearFile() {
  generation += 1
  manifest.value = null; targetTemplate.value = null; chapters.value = []
  sourceFacings.value = []; sourceAnchors.value = []; sourceStoryFields.value = []
  templateConfirmed.value = false; skipConflicts.value = []; invalidatePreview()
  busy.value = ""; error.value = ""; notice.value = ""; emit("dirty", false)
}
function transferRequest() {
  const facetByKey = new Map(props.facets.map((item) => [facingKey(item.facing), item.facing]))
  return {
    manifest: manifest.value,
    facing_mappings: sourceFacings.value.filter((item) => item.target).map((item) => ({ source: item.source, target: facetByKey.get(item.target) })),
    expected_template_version_number: targetTemplate.value?.version_number ?? null,
    template_mapping_confirmed: Boolean(manifest.value.template && templateConfirmed.value),
    story_field_mappings: Object.fromEntries(sourceStoryFields.value.map((item) => [item.key, item.target])),
    anchor_mappings: sourceAnchors.value.map((item) => ({ source: item.source, target: { kind: item.kind, id: item.target } })),
    skip_conflicts: skipConflicts.value,
  }
}
async function chooseFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ""
  if (!file) return
  clearFile()
  if (!file.name.toLowerCase().endsWith(".json") || file.size > 2_000_000) { error.value = "请选择不超过 2 MB 的档案 JSON 文件。"; return }
  const projectId = props.projectId; const entityId = props.entity.id; const token = generation
  busy.value = "file"
  try {
    const parsed = JSON.parse(await file.text())
    if (parsed?.format !== "novelcraft.world.dossier-manifest" || parsed.format_version !== 1 || !Array.isArray(parsed.entries) || parsed.entries.length > 250) throw new Error("文件不是受支持的档案清单。")
    const [templateResult, chapterResult] = await Promise.allSettled([
      getApi().world.getEntityDossierTemplate(props.entity.entity_type, projectId, { cache: "no-store" }),
      getApi().writing.listChapters(projectId),
    ])
    if (token !== generation || projectId !== props.projectId || entityId !== props.entity.id) return
    if (templateResult.status === "rejected" && templateResult.reason?.status !== 404) throw templateResult.reason
    targetTemplate.value = templateResult.status === "fulfilled" ? templateResult.value : null
    chapters.value = chapterResult.status === "fulfilled" ? (Array.isArray(chapterResult.value) ? chapterResult.value : chapterResult.value?.items || []).map((item, index) => ({ id: item.id, label: item.title || `第 ${index + 1} 章` })) : []
    manifest.value = parsed
    const cross = parsed.source_project_id !== projectId
    const faces = new Map()
    for (const entry of parsed.entries) faces.set(facingKey(entry.facing), { source: entry.facing, label: entry.facing_label })
    for (const field of parsed.template?.fields || []) if (!faces.has(facingKey(field.facing))) faces.set(facingKey(field.facing), { source: field.facing, label: field.label })
    for (const facing of parsed.template?.borrowed_facings || []) if (!faces.has(facingKey(facing))) faces.set(facingKey(facing), { source: facing, label: "来源借用面向" })
    sourceFacings.value = [...faces.entries()].map(([key, item]) => ({ ...item, key, required: cross && item.source.kind === "project", target: "" }))
    const anchors = new Map()
    for (const entry of parsed.entries) for (const anchor of [entry.validity?.start, entry.validity?.end]) if (anchor) anchors.set(`${anchor.kind}:${anchor.id}`, anchor)
    sourceAnchors.value = cross ? [...anchors.entries()].map(([key, source]) => ({ key, source, kind: source.kind, target: "" })) : []
    const keys = [...new Set(parsed.entries.map((item) => item.story_field_key).filter(Boolean))]
    sourceStoryFields.value = cross ? keys.map((key) => ({ key, label: parsed.template?.state_fields?.find((field) => field.key === key)?.label || "来源状态字段", target: "" })) : []
    busy.value = ""
    emit("dirty", true)
  } catch (failure) { if (token === generation) error.value = failure?.message || "文件读取失败。" }
  finally { if (token === generation) busy.value = "" }
}
async function previewImport() {
  if (!ready.value || busy.value) return
  const token = generation; const projectId = props.projectId; const entityId = props.entity.id
  busy.value = "preview"; error.value = ""; notice.value = ""; invalidatePreview()
  try {
    const result = await getApi().world.previewEntityDossierManifest(entityId, projectId, transferRequest())
    if (token === generation && projectId === props.projectId && entityId === props.entity.id) preview.value = result
  } catch (failure) { if (token === generation) error.value = failure?.message || "预览失败；文件和映射已保留。" }
  finally { if (token === generation) busy.value = "" }
}
async function applyImport() {
  if (busy.value || !confirmed.value || !preview.value?.can_apply) return
  const token = generation; const projectId = props.projectId; const entityId = props.entity.id
  const payload = { ...transferRequest(), expected_preview_hash: preview.value.preview_hash, confirmed: true }
  busy.value = "apply"; error.value = ""; notice.value = ""
  try {
    const result = await getApi().world.applyEntityDossierManifest(entityId, projectId, payload)
    if (token !== generation || projectId !== props.projectId || entityId !== props.entity.id) return
    invalidatePreview()
    notice.value = `已采用 ${result.applied_count + result.updated_count} 条档案；重新预览可核对重复采用结果。`
    emit("saved", entityId)
  } catch (failure) {
    if (token !== generation) return
    if (failure?.status === 409) invalidatePreview()
    error.value = failure?.message || "采用失败；文件和映射已保留。"
  } finally { if (token === generation) busy.value = "" }
}
watch(() => [props.projectId, props.entity.id], clearFile)
</script>

<style scoped>
.manifest-import{display:grid;gap:10px;padding:12px;border:1px solid var(--border-color,var(--border));border-radius:9px;min-width:0}.manifest-import h4,.manifest-import p{margin:0}.manifest-import p{overflow-wrap:anywhere}.manifest-import fieldset{display:grid;gap:8px;min-width:0;margin:0;padding:10px;border:1px solid var(--border-color,var(--border));border-radius:7px}.manifest-import fieldset>label,.manifest-import__file{display:grid;gap:5px}.manifest-import fieldset>label:has(input[type="checkbox"]){display:flex;align-items:flex-start}.manifest-import select,.manifest-import input{max-width:100%;min-width:0}.manifest-import li{overflow-wrap:anywhere;white-space:pre-wrap}.manifest-import__actions{display:flex;gap:8px;flex-wrap:wrap}.manifest-import__review{display:grid;gap:8px}.manifest-import__review label{display:flex;align-items:flex-start;gap:6px}@media(max-width:650px){.manifest-import__actions{flex-direction:column}.manifest-import button{min-height:42px;width:100%}}
</style>
