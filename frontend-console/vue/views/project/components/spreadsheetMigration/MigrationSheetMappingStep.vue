<script setup>
/**
 * 表格迁移 — 第二步：逐表核对表类型、表头行与列映射。
 * 窄屏下卡片式排布；保存走 revision CAS，409 时提示刷新。
 */
import { computed, ref } from "vue"
import { getApi } from "../../../../bridge/index.js"
import {
  SHEET_KIND_LABELS,
  columnTargetLabel,
  columnTargetOptions,
  sheetKindLabel,
} from "../../logic/spreadsheetMigration.js"

const props = defineProps({
  session: { type: Object, required: true },
  projectId: { type: String, required: true },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(["save"])

const drafts = ref(
  (props.session.sheets || []).map((sheet) => ({
    sheet_key: sheet.sheet_key,
    name: sheet.name,
    hidden: sheet.hidden,
    row_count: sheet.row_count,
    warnings: sheet.warnings || [],
    sample_rows: sheet.sample_rows || [],
    headers: (sheet.columns || []).map((column) => column.header),
    kind: sheet.kind,
    kind_suggested: sheet.kind_suggested,
    header_row: sheet.header_row,
    default_entity_type: sheet.default_entity_type,
    dossier_profile_type: sheet.dossier_profile_type || sheet.default_entity_type || "",
    dossier_profile_type_mode: ["character", "location", "item", "faction", "species", "rule", "secret", "event"].includes(sheet.dossier_profile_type || sheet.default_entity_type) ? (sheet.dossier_profile_type || sheet.default_entity_type) : "custom",
    custom_dossier_profile_type: ["character", "location", "item", "faction", "species", "rule", "secret", "event"].includes(sheet.dossier_profile_type || sheet.default_entity_type) ? "" : (sheet.dossier_profile_type || sheet.default_entity_type || ""),
    columns: Object.fromEntries((sheet.columns || []).map((column) => [column.column_key, column.target])),
    facing_mappings: Object.fromEntries(Object.entries(sheet.facing_mappings || {}).map(([key, value]) => [key, { ...value }])),
    columns_meta: sheet.columns || [],
  })),
)

const kindEntries = computed(() => Object.entries(SHEET_KIND_LABELS))
const profileTypeOptions = [
  ["character", "人物"], ["location", "地点"], ["item", "物件"], ["faction", "势力"],
  ["species", "种族"], ["rule", "规则"], ["secret", "秘密"], ["event", "事件"],
]
const facetsBySheet = ref({})
const facetErrors = ref({})
const facetLoading = ref({})
const facetSequences = new Map()
const mappingError = computed(() => {
  for (const draft of drafts.value) {
    const dossierColumns = Object.entries(draft.columns || {}).filter(([, target]) => target === "dossier_facing").map(([key]) => key)
    if (!dossierColumns.length) continue
    if (!resolvedProfileType(draft)) return `“${draft.name}”需要先选择档案列对应的对象类型。`
    if (dossierColumns.some((key) => !draft.facing_mappings?.[key]?.kind)) return `“${draft.name}”的每个档案面向列都需要明确选择面向。`
  }
  return ""
})

function resolvedProfileType(draft) {
  return draft.dossier_profile_type_mode === "custom"
    ? String(draft.custom_dossier_profile_type || "").trim().toLowerCase()
    : String(draft.dossier_profile_type_mode || "").trim().toLowerCase()
}

function hasDossierColumns(draft) {
  return Object.values(draft.columns || {}).includes("dossier_facing")
}

function onTargetChange(draft) {
  if (hasDossierColumns(draft) && !facetsBySheet.value[draft.sheet_key]) void loadFacets(draft)
}

function facingKey(facing, draft) {
  if (facing?.kind === "project") return `project:${facing.term_id || ""}`
  return `core:${facing?.source_entity_type || resolvedProfileType(draft)}:${facing?.key || ""}`
}

function columnFacingValue(draft, columnKey) {
  const mapping = draft.facing_mappings?.[columnKey]
  return mapping ? facingKey(mapping, draft) : ""
}

function setColumnFacing(draft, columnKey, value) {
  const facet = (facetsBySheet.value[draft.sheet_key] || []).find((item) => facingKey(item.facing, draft) === value)
  if (!facet) {
    delete draft.facing_mappings[columnKey]
    return
  }
  const facing = { ...facet.facing }
  if (facing.kind === "core") facing.source_entity_type = facing.source_entity_type || resolvedProfileType(draft)
  draft.facing_mappings[columnKey] = {
    ...facing,
    visibility: draft.facing_mappings[columnKey]?.visibility || "public",
  }
}

function setColumnVisibility(draft, columnKey, visibility) {
  const mapping = draft.facing_mappings[columnKey]
  if (mapping) mapping.visibility = visibility
}

function setProfileType(draft) {
  draft.dossier_profile_type = resolvedProfileType(draft)
  draft.default_entity_type = draft.dossier_profile_type || draft.default_entity_type
  draft.facing_mappings = {}
  facetsBySheet.value = { ...facetsBySheet.value, [draft.sheet_key]: [] }
  facetErrors.value = { ...facetErrors.value, [draft.sheet_key]: "" }
  if (draft.dossier_profile_type) void loadFacets(draft)
}

async function loadFacets(draft) {
  const profileType = resolvedProfileType(draft)
  if (!profileType || !props.projectId) return
  const sequence = (facetSequences.get(draft.sheet_key) || 0) + 1
  facetSequences.set(draft.sheet_key, sequence)
  facetLoading.value = { ...facetLoading.value, [draft.sheet_key]: true }
  facetErrors.value = { ...facetErrors.value, [draft.sheet_key]: "" }
  try {
    const result = await getApi().world.listDossierFacetsForType(profileType, props.projectId, { cache: "no-store" })
    if (facetSequences.get(draft.sheet_key) !== sequence) return
    facetsBySheet.value = { ...facetsBySheet.value, [draft.sheet_key]: result.items || [] }
  } catch (error) {
    if (facetSequences.get(draft.sheet_key) === sequence) facetErrors.value = { ...facetErrors.value, [draft.sheet_key]: error?.message || "面向读取失败，请重新选择对象类型后重试。" }
  } finally {
    if (facetSequences.get(draft.sheet_key) === sequence) facetLoading.value = { ...facetLoading.value, [draft.sheet_key]: false }
  }
}

for (const draft of drafts.value) if (hasDossierColumns(draft)) void loadFacets(draft)

function targetsFor(draft) {
  const options = columnTargetOptions(draft.kind)
  // 旧会话的设定表可能已选人物字段：当前值不在新选项中时保留显示，不强制清空。
  const missing = Object.values(draft.columns || {}).filter(
    (target) => target && !options.includes(target),
  )
  return missing.length ? [...options, ...missing] : options
}

function save() {
  if (mappingError.value) return
  emit("save", {
    sheets: drafts.value.map((draft) => ({
      sheet_key: draft.sheet_key,
      kind: draft.kind,
      header_row: Number(draft.header_row) || 0,
      // 携带默认实体类型，整体保存时不因省略而被清掉
      ...(draft.default_entity_type
        ? { default_entity_type: draft.default_entity_type }
        : {}),
      ...(hasDossierColumns(draft)
        ? {
            dossier_profile_type: resolvedProfileType(draft),
            facing_mappings: Object.fromEntries(
              Object.entries(draft.facing_mappings || {}).filter(([key]) => draft.columns[key] === "dossier_facing"),
            ),
          }
        : {}),
      columns: { ...draft.columns },
    })),
  })
}
</script>

<template>
  <div class="sm-mapping" data-testid="sm-mapping">
    <p class="sm-mapping__hint">
      核对每张表的类型、表头行和列含义；识别只是建议，全部可以调整。
      未识别的列会作为「作者备注」保留，不会丢失。
    </p>
    <div
      v-for="draft in drafts"
      :key="draft.sheet_key"
      class="sm-mapping__card"
      :data-sheet="draft.sheet_key"
    >
      <div class="sm-mapping__card-head">
        <strong>{{ draft.name }}</strong>
        <span v-if="draft.hidden" class="sm-mapping__muted">（隐藏表）</span>
        <span class="sm-mapping__muted">{{ draft.row_count }} 行</span>
        <label class="sm-mapping__inline">
          表类型
          <select v-model="draft.kind" :data-action="`sm-kind-${draft.sheet_key}`">
            <option v-for="[value, label] in kindEntries" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
        <label class="sm-mapping__inline">
          表头行
          <input v-model.number="draft.header_row" type="number" min="0" max="32" class="sm-mapping__number" />
        </label>
        <span v-if="draft.kind_suggested" class="sm-mapping__suggested">系统建议：{{ sheetKindLabel(draft.kind) }}</span>
      </div>
      <p v-for="warning in draft.warnings" :key="warning.message" class="sm-mapping__warning">{{ warning.message }}</p>
      <div v-if="hasDossierColumns(draft)" class="sm-mapping__dossier-type">
        <label>档案对象类型
          <select v-model="draft.dossier_profile_type_mode" @change="setProfileType(draft)">
            <option v-for="[value, label] in profileTypeOptions" :key="value" :value="value">{{ label }}</option>
            <option value="custom">自定义类型</option>
          </select>
        </label>
        <label v-if="draft.dossier_profile_type_mode === 'custom'">类型名称
          <input v-model="draft.custom_dossier_profile_type" maxlength="64" placeholder="例如：灵兽" @change="setProfileType(draft)" />
        </label>
        <p v-if="facetLoading[draft.sheet_key]" role="status">正在读取此对象类型可用的档案面向…</p>
        <p v-if="facetErrors[draft.sheet_key]" class="sm-mapping__warning" role="alert">{{ facetErrors[draft.sheet_key] }}</p>
      </div>
      <div class="sm-mapping__columns">
        <div v-for="column in draft.columns_meta" :key="column.column_key" class="sm-mapping__column">
          <span class="sm-mapping__column-header" :title="column.header">{{ column.header || "（空列）" }}</span>
          <select v-model="draft.columns[column.column_key]" :data-action="`sm-target-${draft.sheet_key}-${column.column_key}`" @change="onTargetChange(draft)">
            <option v-for="target in targetsFor(draft)" :key="target" :value="target">{{ columnTargetLabel(target) }}</option>
          </select>
          <template v-if="draft.columns[column.column_key] === 'dossier_facing'">
            <label>写入面向
              <select :value="columnFacingValue(draft, column.column_key)" :disabled="facetLoading[draft.sheet_key] || !resolvedProfileType(draft)" @change="setColumnFacing(draft, column.column_key, $event.target.value)">
                <option value="">选择面向</option>
                <option v-for="facet in facetsBySheet[draft.sheet_key] || []" :key="facingKey(facet.facing, draft)" :value="facingKey(facet.facing, draft)">{{ facet.label }}<template v-if="facet.source === 'project'"> · 项目面向</template></option>
              </select>
            </label>
            <label>可见范围
              <select :value="draft.facing_mappings[column.column_key]?.visibility || 'public'" :disabled="!draft.facing_mappings[column.column_key]" @change="setColumnVisibility(draft, column.column_key, $event.target.value)"><option value="public">公开档案</option><option value="secret">作者秘密</option></select>
            </label>
          </template>
        </div>
      </div>
      <details class="sm-mapping__samples">
        <summary>样例行</summary>
        <div class="sm-mapping__sample-table" role="table">
          <span
            v-for="(cell, index) in draft.headers"
            :key="`h-${index}`"
            class="sm-mapping__sample-cell sm-mapping__sample-cell--head"
            role="columnheader"
          >{{ cell }}</span>
          <template v-for="(row, rowIndex) in draft.sample_rows" :key="`r-${rowIndex}`">
            <span v-for="(cell, cellIndex) in row" :key="`r-${rowIndex}-${cellIndex}`" class="sm-mapping__sample-cell" role="cell">{{ cell }}</span>
          </template>
        </div>
      </details>
    </div>
    <div class="sm-mapping__actions">
      <button
        type="button"
        class="btn"
        data-action="sm-save-mapping"
          :disabled="saving || Boolean(mappingError)"
        @click="save"
      >{{ saving ? "正在保存…" : "保存映射并生成预览" }}</button>
      <p v-if="mappingError" class="sm-mapping__warning" role="alert">{{ mappingError }}</p>
    </div>
  </div>
</template>

<style scoped>
.sm-mapping { display: flex; flex-direction: column; gap: 12px; }
.sm-mapping__hint { margin: 0; color: var(--text-muted, #6b7280); }
.sm-mapping__card { border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.sm-mapping__card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.sm-mapping__muted { color: var(--text-muted, #6b7280); font-size: 13px; }
.sm-mapping__suggested { font-size: 12px; color: var(--accent, #2563eb); }
.sm-mapping__warning { margin: 0; color: #92400e; font-size: 13px; }
.sm-mapping__columns { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.sm-mapping__column { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.sm-mapping__column-header { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sm-mapping__number { width: 5rem; }
.sm-mapping__samples summary { cursor: pointer; color: var(--text-muted, #6b7280); font-size: 13px; }
.sm-mapping__sample-table { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 2px; margin-top: 6px; font-size: 12px; }
.sm-mapping__sample-cell { padding: 2px 6px; border: 1px solid var(--border-color, #f3f4f6); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sm-mapping__sample-cell--head { background: var(--bg-subtle, #f9fafb); font-weight: 600; }
.sm-mapping__actions { display: flex; gap: 8px; }
@media (max-width: 640px) {
  .sm-mapping__columns { grid-template-columns: 1fr; }
}
</style>
