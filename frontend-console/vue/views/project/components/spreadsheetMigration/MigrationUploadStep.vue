<script setup>
/**
 * 表格迁移 — 第一步：上传 xlsx/csv。
 * 校验（扩展名/数量/10MB）在 useImportUpload 的纯函数中，便于测试。
 */
import { computed, ref } from "vue"
import { getToast } from "../../../../bridge/index.js"
import {
  MAX_SPREADSHEET_FILE_BYTES,
  SPREADSHEET_FILE_ACCEPT,
  validateSpreadsheetFiles,
} from "../../../../composables/useImportUpload.js"

const props = defineProps({
  uploading: { type: Boolean, default: false },
})
const emit = defineEmits(["upload"])

const fileInput = ref(null)
const uploadingLocal = ref(false)
const busy = computed(() => props.uploading || uploadingLocal.value)

async function submit() {
  const input = fileInput.value
  const files = Array.from(input?.files || [])
  const error = validateSpreadsheetFiles(files)
  if (error) {
    getToast()(error, "warning")
    return
  }
  uploadingLocal.value = true
  try {
    await emit("upload", files)
  } finally {
    uploadingLocal.value = false
    if (input) input.value = ""
  }
}
</script>

<template>
  <div class="sm-upload" data-testid="sm-upload">
    <p class="sm-upload__hint">
      把你在 Excel、WPS、飞书、腾讯文档或 Notion 里维护的人物表、设定表、关系表、
      大纲表导出为 <strong>.xlsx</strong> 或 <strong>.csv</strong> 后上传（一次最多 5 个文件，
      单个不超过 {{ Math.round(MAX_SPREADSHEET_FILE_BYTES / 1024 / 1024) }}MB）。
      旧版 .xls 请先在 Excel/WPS 中另存为 .xlsx。
    </p>
    <p class="sm-upload__hint sm-upload__hint--muted">
      建议：已有人物表、设定表、大纲表？先导入表格再导入正文，深度导入会自动对上你的人物。
    </p>
    <div class="sm-upload__form">
      <input
        ref="fileInput"
        type="file"
        class="sm-upload__input"
        :accept="SPREADSHEET_FILE_ACCEPT"
        multiple
        data-testid="sm-file-input"
      />
      <button
        type="button"
        class="btn"
        data-action="sm-upload"
        :disabled="busy"
        @click="submit"
      >{{ busy ? "正在上传并识别…" : "上传并识别表格" }}</button>
    </div>
  </div>
</template>

<style scoped>
.sm-upload { display: flex; flex-direction: column; gap: 8px; }
.sm-upload__hint { margin: 0; line-height: 1.6; }
.sm-upload__hint--muted { color: var(--text-muted, #6b7280); font-size: 13px; }
.sm-upload__form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
</style>
