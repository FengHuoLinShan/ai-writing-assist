<template>
  <section v-if="open" class="panel worldbook-import-panel" aria-labelledby="worldbook-import-title">
    <div class="world-bible-panel__header">
      <div>
        <h2 id="worldbook-import-title">导入世界书目录</h2>
        <p>支持 Markdown、TXT、JSON、YAML。导入只创建未发布工作稿，不会自动写入正式设定。</p>
      </div>
      <button type="button" class="btn btn-sm btn-ghost" @click="close">关闭</button>
    </div>
    <input
      ref="inputEl"
      class="sr-only"
      type="file"
      multiple
      webkitdirectory
      directory
      aria-label="选择世界书目录"
      @change="selectFiles"
    />
    <div class="world-bible-panel__actions">
      <button type="button" class="btn btn-sm btn-primary" data-action="worldbook-import-select" :disabled="busy" @click="inputEl?.click()">{{ files.length ? "重新选择目录" : "选择目录" }}</button>
      <button v-if="files.length" type="button" class="btn btn-sm" data-action="worldbook-import-preview" :disabled="busy" @click="previewFiles">{{ pending === "preview" ? "正在检查…" : "预览导入" }}</button>
    </div>
    <p v-if="selectionSummary" class="world-bible-empty-hint">{{ selectionSummary }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <template v-if="preview">
      <div class="worldbook-import-counts" aria-label="导入预览统计">
        <span>新建 {{ count("create") }}</span>
        <span>更新 {{ count("update") }}</span>
        <span>保留 {{ count("preserve") }}</span>
        <span>冲突 {{ count("conflict") }}</span>
        <span>源缺失 {{ count("missing") }}</span>
      </div>
      <p>识别为 {{ formatLabel }}；{{ preview.ignored_paths?.length || 0 }} 个控制或不支持文件已忽略。</p>
      <details v-if="preview.ignored_paths?.length" class="worldbook-import-ignored">
        <summary>查看已忽略文件</summary>
        <ul>
          <li v-for="path in preview.ignored_paths" :key="path">{{ path }}</li>
        </ul>
      </details>
      <ul class="worldbook-import-items">
        <li v-for="item in preview.items" :key="`${item.source_key}:${item.action}`">
          <strong>{{ item.title }}</strong>
          <span>{{ actionLabel(item.action) }} · {{ item.path }}</span>
          <small>{{ item.reason }}</small>
        </li>
      </ul>
      <div class="world-bible-panel__actions">
        <button type="button" class="btn btn-sm btn-primary" data-action="worldbook-import-apply" :disabled="busy" @click="applyImport">{{ pending === "apply" ? "正在应用…" : "创建或更新工作稿" }}</button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { getApi, getConfirm, getRouter, getToast } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, required: true },
  open: Boolean,
  suggestionId: { type: String, default: "" },
})
const emit = defineEmits(["close"])
const api = getApi()
const confirm = getConfirm()
const router = getRouter()
const toast = getToast()
const inputEl = ref(null)
const files = ref([])
const preview = ref(null)
const error = ref("")
const pending = ref("")
let requestGeneration = 0

const busy = computed(() => Boolean(pending.value))
const isSupportedText = (file) => /\.(md|txt|json|ya?ml)$/i.test(file.name)
const selectionSummary = computed(() => files.value.length
  ? `已选择 ${files.value.length} 个文件，其中 ${files.value.filter(isSupportedText).length} 个可读文本，共 ${files.value.filter(isSupportedText).reduce((sum, item) => sum + item.size, 0).toLocaleString("zh-CN")} 字节。`
  : "")
const formatLabel = computed(() => ({ obsidian: "Obsidian Vault", llmwiki: "LLM Wiki", generic: "通用目录" })[preview.value?.source_format] || "通用目录")
const count = (key) => Number(preview.value?.counts?.[key] || 0)
const actionLabel = (action) => ({ create: "新建工作稿", update: "安全更新", preserve: "保留项目版本", conflict: "需要核对", missing: "来源缺失" })[action] || action

function close() {
  requestGeneration += 1
  pending.value = ""
  emit("close")
}

function selectFiles(event) {
  error.value = ""
  preview.value = null
  const selected = [...(event.target.files || [])]
  const supported = selected.filter(isSupportedText)
  if (!supported.length) return error.value = "目录中没有可导入的文本文件。"
  if (selected.length > 2000) return error.value = "一次最多导入 2,000 个文本文件。"
  if (supported.some((file) => file.size > 2 * 1024 * 1024)) return error.value = "单个文本文件不能超过 2 MiB。"
  if (supported.reduce((sum, file) => sum + file.size, 0) > 25 * 1024 * 1024) return error.value = "文本总量不能超过 25 MiB。"
  files.value = selected
}

async function previewFiles() {
  if (!files.value.length || busy.value) return false
  const generation = ++requestGeneration
  pending.value = "preview"
  error.value = ""
  try {
    const payload = []
    for (const file of files.value) {
      payload.push({
        path: file.webkitRelativePath || file.name,
        content: isSupportedText(file) ? await file.text() : "",
      })
    }
    const result = await api.world.previewWorldbookImport(props.projectId, payload)
    if (generation !== requestGeneration) return false
    preview.value = result
    return true
  } catch (err) {
    if (generation === requestGeneration) error.value = err?.message || "无法预览这个目录。"
    return false
  } finally {
    if (generation === requestGeneration) pending.value = ""
  }
}

async function applyImport() {
  if (!preview.value || busy.value) return false
  if (!confirm("只会创建或更新未发布工作稿；冲突不会覆盖，是否继续？")) return false
  const generation = ++requestGeneration
  pending.value = "apply"
  error.value = ""
  try {
    const result = await api.world.applyWorldbookImport(preview.value.suggestion_id, props.projectId, preview.value.preview_hash)
    if (generation !== requestGeneration) return false
    toast(`导入完成：${result.draft_ids.length} 个工作稿，${result.conflict_ids.length} 个待核对冲突`, "success")
    const query = new URLSearchParams()
    if (result.draft_ids[0]) query.set("draft_id", result.draft_ids[0])
    router.navigate("world", "bible", true, query)
    return true
  } catch (err) {
    if (generation === requestGeneration) error.value = err?.message || "应用导入失败；选择和预览仍保留。"
    return false
  } finally {
    if (generation === requestGeneration) pending.value = ""
  }
}

async function restorePreview() {
  if (!props.open || !props.suggestionId || busy.value) return
  const generation = ++requestGeneration
  pending.value = "preview"
  try {
    const result = await api.world.getWorldbookImport(props.suggestionId, props.projectId)
    if (generation === requestGeneration) preview.value = result
  } catch (err) {
    if (generation === requestGeneration) error.value = err?.message || "无法恢复导入预览。"
  } finally {
    if (generation === requestGeneration) pending.value = ""
  }
}

onMounted(restorePreview)
watch(() => props.suggestionId, restorePreview)
</script>
