<script setup>
/**
 * 表格迁移 — 第三步：AI 整理（可选）。
 * 大纲类表默认预选；作者确认后发起，进度经 WorkflowProgressCard 展示。
 */
import { computed, ref } from "vue"
import {
  sheetKindLabel,
  sheetWantsAiByDefault,
} from "../../logic/spreadsheetMigration.js"

const props = defineProps({
  session: { type: Object, required: true },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(["start", "skip"])

const outlineSheets = computed(() =>
  (props.session.sheets || []).filter(
    (sheet) => sheet.kind !== "skip" && sheetWantsAiByDefault(sheet.kind) && sheet.kind !== "characters" && sheet.kind !== "world_objects" && sheet.kind !== "relations",
  ),
)
const cleanupCandidates = computed(() =>
  (props.session.sheets || [])
    .filter((sheet) => sheet.kind === "characters" || sheet.kind === "world_objects")
    .flatMap((sheet) =>
      (sheet.columns || [])
        .filter((column) => column.target === "author_note")
        .map((column) => ({ sheet, column })),
    ),
)

const selectedOutline = ref(
  outlineSheets.value
    .filter((sheet) => !sheet.hidden)
    .map((sheet) => sheet.sheet_key),
)
const selectedCleanup = ref(
  cleanupCandidates.value.map(({ sheet, column }) => `${sheet.sheet_key}:${column.column_key}`),
)
const confirmed = ref(false)

const selectedRows = computed(() =>
  (props.session.sheets || [])
    .filter((sheet) => selectedOutline.value.includes(sheet.sheet_key))
    .reduce((sum, sheet) => sum + (sheet.row_count || 0), 0),
)
const ai = computed(() => props.session.ai || {})
const busy = computed(() => props.submitting || ai.value.status === "queued" || ai.value.status === "running")

function toggleOutline(key) {
  const index = selectedOutline.value.indexOf(key)
  if (index >= 0) selectedOutline.value.splice(index, 1)
  else selectedOutline.value.push(key)
}

function toggleCleanup(key) {
  const index = selectedCleanup.value.indexOf(key)
  if (index >= 0) selectedCleanup.value.splice(index, 1)
  else selectedCleanup.value.push(key)
}

function start() {
  emit("start", {
    outline_sheet_keys: [...selectedOutline.value],
    cleanup: selectedCleanup.value
      .map((key) => {
        const [sheet_key, column_key] = key.split(":")
        return { sheet_key, column_key }
      })
      .filter((item) => item.sheet_key && item.column_key),
  })
}

const aiStatusLabel = computed(() => ({
  idle: "未开始",
  queued: "排队中",
  running: "正在整理",
  done: "整理完成",
  failed: "整理失败",
}[ai.value.status] || ai.value.status || "未开始"))
</script>

<template>
  <div class="sm-ai" data-testid="sm-ai">
    <p class="sm-ai__hint">
      大纲类表格是自由文本，建议先交给 AI 忠实整理成结构（可整理卷、剧情线、伏笔、
      章节细纲和总纲）；也可以跳过，直接按规则导入原文。整理结果只作为预览，
      你确认后才会采用。
    </p>

    <div v-if="outlineSheets.length" class="sm-ai__group">
      <div class="sm-ai__group-title">大纲类表格（{{ selectedRows }} 行已选）</div>
      <label
        v-for="sheet in outlineSheets"
        :key="sheet.sheet_key"
        class="sm-ai__option"
      >
        <input
          type="checkbox"
          :checked="selectedOutline.includes(sheet.sheet_key)"
          :data-action="`sm-ai-sheet-${sheet.sheet_key}`"
          @change="toggleOutline(sheet.sheet_key)"
        />
        <span>{{ sheet.name }}（{{ sheetKindLabel(sheet.kind) }}，约 {{ sheet.row_count }} 行）</span>
      </label>
    </div>

    <div v-if="cleanupCandidates.length" class="sm-ai__group">
      <div class="sm-ai__group-title">人物小传拆字段（可选）</div>
      <label
        v-for="{ sheet, column } in cleanupCandidates"
        :key="`${sheet.sheet_key}:${column.column_key}`"
        class="sm-ai__option"
      >
        <input
          type="checkbox"
          :checked="selectedCleanup.includes(`${sheet.sheet_key}:${column.column_key}`)"
          @change="toggleCleanup(`${sheet.sheet_key}:${column.column_key}`)"
        />
        <span>{{ sheet.name }} / 「{{ column.header }}」拆成人物字段</span>
      </label>
    </div>

    <div class="sm-ai__status" :data-ai-status="ai.status">
      <span>AI 整理：{{ aiStatusLabel }}</span>
      <span v-if="ai.estimate" class="sm-ai__muted">
        {{ ai.estimate.rows }} 行 · 约 {{ ai.estimate.chars }} 字 · {{ ai.estimate.requests }} 次模型调用
      </span>
      <span v-if="ai.blocked_count" class="sm-ai__muted">
        {{ ai.blocked_count }} 组未通过复核，将按原文回落规则导入
      </span>
    </div>

    <div class="sm-ai__actions">
      <label class="sm-ai__confirm">
        <input v-model="confirmed" type="checkbox" data-action="sm-ai-confirm" />
        我确认整理上述内容（使用本项目的模型额度）
      </label>
      <button
        type="button"
        class="btn"
        data-action="sm-ai-start"
        :disabled="busy || !confirmed || (!selectedOutline.length && !selectedCleanup.length)"
        @click="start"
      >{{ busy ? "整理进行中…" : "开始 AI 整理" }}</button>
      <button
        type="button"
        class="btn btn-ghost"
        data-action="sm-ai-skip"
        :disabled="busy"
        @click="emit('skip')"
      >跳过 AI，直接用规则导入</button>
    </div>
  </div>
</template>

<style scoped>
.sm-ai { display: flex; flex-direction: column; gap: 12px; }
.sm-ai__hint { margin: 0; line-height: 1.6; }
.sm-ai__group { border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.sm-ai__group-title { font-weight: 600; font-size: 13px; }
.sm-ai__option { display: flex; gap: 8px; align-items: baseline; font-size: 14px; }
.sm-ai__status { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; }
.sm-ai__muted { color: var(--text-muted, #6b7280); }
.sm-ai__actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.sm-ai__confirm { font-size: 13px; }
</style>
