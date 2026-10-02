<script setup>
/**
 * 表格迁移 — 第二步：逐表核对表类型、表头行与列映射。
 * 窄屏下卡片式排布；保存走 revision CAS，409 时提示刷新。
 */
import { computed, ref } from "vue"
import {
  SHEET_KIND_LABELS,
  columnTargetLabel,
  columnTargetOptions,
  sheetKindLabel,
} from "../../logic/spreadsheetMigration.js"

const props = defineProps({
  session: { type: Object, required: true },
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
    columns: Object.fromEntries((sheet.columns || []).map((column) => [column.column_key, column.target])),
    columns_meta: sheet.columns || [],
  })),
)

const kindEntries = computed(() => Object.entries(SHEET_KIND_LABELS))

function targetsFor(draft) {
  return columnTargetOptions(draft.kind)
}

function save() {
  emit("save", {
    sheets: drafts.value.map((draft) => ({
      sheet_key: draft.sheet_key,
      kind: draft.kind,
      header_row: Number(draft.header_row) || 0,
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
      <div class="sm-mapping__columns">
        <div v-for="column in draft.columns_meta" :key="column.column_key" class="sm-mapping__column">
          <span class="sm-mapping__column-header" :title="column.header">{{ column.header || "（空列）" }}</span>
          <select v-model="draft.columns[column.column_key]" :data-action="`sm-target-${draft.sheet_key}-${column.column_key}`">
            <option v-for="target in targetsFor(draft)" :key="target" :value="target">{{ columnTargetLabel(target) }}</option>
          </select>
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
        :disabled="saving"
        @click="save"
      >{{ saving ? "正在保存…" : "保存映射并生成预览" }}</button>
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
